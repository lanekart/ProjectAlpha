from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from statistics import median

from alpha.candidate_learning.directional_signal_audit import (
    DirectionalSignalQualityAuditEngine,
)
from alpha.candidate_learning.entry_timing import (
    EntryTimingState,
    build_entry_timing_replay_report,
)
from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.market_intelligence.intelligence import (
    AccumulationPhase,
    BreadthCondition,
    CorrelationRisk,
    DistributionPhase,
    IntelligenceBias,
    LiquidityQuality,
    SectorRotationPhase,
)
from alpha.market_intelligence.models import (
    DeliveryBehavior,
    DerivativesPositioning,
    MarketDirectionBias,
    MarketMood,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_FOUR = Decimal("0.0001")
_POSITIVE_VERDICTS = {"BUY", "STRONG_BUY"}
_NEGATIVE_VERDICTS = {"SELL", "STRONG_SELL"}
_PRIMARY_ENTRY_STATES = {
    EntryTimingState.AGGRESSIVE_ENTRY,
    EntryTimingState.PREFERRED_ENTRY,
    EntryTimingState.CONFIRMATION_ENTRY,
}


class CanonicalRegime(StrEnum):
    STRONG_POSITIVE = "STRONG_POSITIVE"
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    STRONG_NEGATIVE = "STRONG_NEGATIVE"
    BULLISH_TREND = "BULLISH_TREND"
    BEARISH_TREND = "BEARISH_TREND"
    SIDEWAYS = "SIDEWAYS"
    CORRECTION = "CORRECTION"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    RECOVERY = "RECOVERY"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class RegimeJoinMethod(StrEnum):
    EXACT = "EXACT"
    CARRIED_FORWARD = "CARRIED_FORWARD"
    DEFAULTED_NEUTRAL = "DEFAULTED_NEUTRAL"
    MISSING = "MISSING"
    STALE = "STALE"


class ReferenceMarketState(StrEnum):
    BULLISH_TREND = "BULLISH_TREND"
    BEARISH_TREND = "BEARISH_TREND"
    SIDEWAYS = "SIDEWAYS"
    CORRECTION = "CORRECTION"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    RECOVERY = "RECOVERY"
    UNAVAILABLE = "UNAVAILABLE"


class NeutralConcentrationCause(StrEnum):
    GENUINELY_NEUTRAL_SAMPLE = "GENUINELY_NEUTRAL_SAMPLE"
    OVERLY_BROAD_NEUTRAL_BOUNDARIES = "OVERLY_BROAD_NEUTRAL_BOUNDARIES"
    DEFAULT_NEUTRAL_FALLBACK = "DEFAULT_NEUTRAL_FALLBACK"
    MISSING_INPUT_COLLAPSE = "MISSING_INPUT_COLLAPSE"
    STALE_REGIME_ATTACHMENT = "STALE_REGIME_ATTACHMENT"
    REPLAY_JOIN_DEFECT = "REPLAY_JOIN_DEFECT"
    CANDIDATE_GENERATION_SELECTION_EFFECT = "CANDIDATE_GENERATION_SELECTION_EFFECT"
    REGIME_ENUM_MAPPING_ERROR = "REGIME_ENUM_MAPPING_ERROR"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    OTHER = "OTHER"


class RetracementRegimeFinding(StrEnum):
    RETRACEMENT_GLOBAL_SIGN_ERROR_SUSPECTED = "RETRACEMENT_GLOBAL_SIGN_ERROR_SUSPECTED"
    RETRACEMENT_REGIME_INTERACTION = "RETRACEMENT_REGIME_INTERACTION"
    RETRACEMENT_SETUP_INTERACTION = "RETRACEMENT_SETUP_INTERACTION"
    RETRACEMENT_NORMALIZATION_DEFECT_SUSPECTED = (
        "RETRACEMENT_NORMALIZATION_DEFECT_SUSPECTED"
    )
    RETRACEMENT_MISSING_DATA_ARTIFACT = "RETRACEMENT_MISSING_DATA_ARTIFACT"
    RETRACEMENT_GENUINELY_NEGATIVE_FEATURE = "RETRACEMENT_GENUINELY_NEGATIVE_FEATURE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RegimeAuditConclusion(StrEnum):
    REGIME_CLASSIFIER_HAS_USEFUL_SEPARATION = "REGIME_CLASSIFIER_HAS_USEFUL_SEPARATION"
    REGIME_CLASSIFIER_COLLAPSES_TO_NEUTRAL = "REGIME_CLASSIFIER_COLLAPSES_TO_NEUTRAL"
    DEFAULT_NEUTRAL_FALLBACK_IS_PRIMARY_BOTTLENECK = (
        "DEFAULT_NEUTRAL_FALLBACK_IS_PRIMARY_BOTTLENECK"
    )
    REGIME_TIMESTAMP_ALIGNMENT_IS_PRIMARY_BOTTLENECK = (
        "REGIME_TIMESTAMP_ALIGNMENT_IS_PRIMARY_BOTTLENECK"
    )
    REGIME_FEATURE_QUALITY_IS_PRIMARY_BOTTLENECK = (
        "REGIME_FEATURE_QUALITY_IS_PRIMARY_BOTTLENECK"
    )
    REGIME_THRESHOLD_DEFINITION_IS_PRIMARY_BOTTLENECK = (
        "REGIME_THRESHOLD_DEFINITION_IS_PRIMARY_BOTTLENECK"
    )
    REGIME_INTERVENTION_DEGRADES_SIGNAL_QUALITY = (
        "REGIME_INTERVENTION_DEGRADES_SIGNAL_QUALITY"
    )
    MOMENTUM_NEUTRAL_INTERACTION_IS_PRIMARY_BOTTLENECK = (
        "MOMENTUM_NEUTRAL_INTERACTION_IS_PRIMARY_BOTTLENECK"
    )
    CANDIDATE_SAMPLE_LACKS_REGIME_DIVERSITY = "CANDIDATE_SAMPLE_LACKS_REGIME_DIVERSITY"
    MARKET_REGIME_IS_NOT_THE_PRIMARY_BOTTLENECK = (
        "MARKET_REGIME_IS_NOT_THE_PRIMARY_BOTTLENECK"
    )
    INSUFFICIENT_EVIDENCE_FOR_REGIME_CONCLUSION = (
        "INSUFFICIENT_EVIDENCE_FOR_REGIME_CONCLUSION"
    )


class NextRegimeAuditMilestone(StrEnum):
    MARKET_REGIME_CLASSIFIER_THRESHOLD_AUDIT = (
        "MARKET_REGIME_CLASSIFIER_THRESHOLD_AUDIT"
    )
    REGIME_TIMESTAMP_JOIN_REPAIR_DESIGN = "REGIME_TIMESTAMP_JOIN_REPAIR_DESIGN"
    REGIME_INTERVENTION_RESEARCH = "REGIME_INTERVENTION_RESEARCH"
    MOMENTUM_NEUTRAL_SETUP_AUDIT = "MOMENTUM_NEUTRAL_SETUP_AUDIT"
    RETRACEMENT_SIGN_AND_NORMALIZATION_AUDIT = (
        "RETRACEMENT_SIGN_AND_NORMALIZATION_AUDIT"
    )
    COLLECT_MARKET_REGIME_HISTORY = "COLLECT_MARKET_REGIME_HISTORY"
    NO_REGIME_CHANGE_RECOMMENDED = "NO_REGIME_CHANGE_RECOMMENDED"


@dataclass(frozen=True, slots=True)
class MarketRegimeAuditConfig:
    minimum_sample: int = 30
    neutral_concentration_threshold: Decimal = Decimal("0.80")
    stale_attachment_days: int = 5
    useful_auc_threshold: Decimal = Decimal("0.58")
    harmful_value_add_threshold: Decimal = Decimal("-0.02")


@dataclass(frozen=True, slots=True)
class ProductionRegimeInventoryItem:
    source: str
    label: str
    canonical: CanonicalRegime
    role: str
    notes: str


@dataclass(frozen=True, slots=True)
class RegimeLineageRecord:
    stage: str
    source_module: str
    source_function: str
    inputs: tuple[str, ...]
    thresholds: tuple[str, ...]
    missing_input_fields: tuple[str, ...]
    fallback_path: str
    persisted: bool
    notes: str


@dataclass(frozen=True, slots=True)
class CandidateRegimeAttachment:
    candidate_id: str
    symbol: str
    candidate_timestamp: str
    attached_regime: str | None
    canonical_regime: CanonicalRegime
    attached_regime_timestamp: str | None
    age_days: int | None
    join_method: RegimeJoinMethod
    knowable_at_decision_time: bool
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegimeDistributionSummary:
    universe: str
    regime: str
    candidate_count: int
    percentage_share: Decimal | None
    median_duration_days: Decimal | None
    longest_duration_days: int | None
    transition_count: int
    missing_default_rate: Decimal | None
    candidate_generation_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class RegimeTransition:
    from_regime: str
    to_regime: str
    count: int


@dataclass(frozen=True, slots=True)
class RegimeReferenceComparison:
    production_regime: str
    reference_state: ReferenceMarketState
    count: int


@dataclass(frozen=True, slots=True)
class ReferenceStateQuality:
    sample_count: int
    balanced_accuracy: Decimal | None
    macro_precision: Decimal | None
    macro_recall: Decimal | None
    cohen_kappa: Decimal | None
    extreme_reference_neutral_rate: Decimal | None
    missed_major_turns: int
    false_transitions: int
    transition_lag_days: Decimal | None


@dataclass(frozen=True, slots=True)
class MarketEpisode:
    label: str
    start: str
    trough_or_peak: str
    end: str
    benchmark_return: Decimal | None
    maximum_drawdown: Decimal | None
    volatility: Decimal | None
    production_regime_sequence: tuple[str, ...]
    reference_regime_sequence: tuple[str, ...]
    classification_lag_days: int | None
    candidate_count: int
    win_rate: Decimal | None
    average_return: Decimal | None


@dataclass(frozen=True, slots=True)
class RegimeFeatureSeparability:
    feature: str
    availability: Decimal | None
    correlation_with_return: Decimal | None
    winner_mean: Decimal | None
    loser_mean: Decimal | None
    winner_loser_separation: Decimal | None
    missingness: Decimal | None
    classification: str


@dataclass(frozen=True, slots=True)
class RegimeInterventionMetric:
    metric: str
    before: Decimal | None
    after: Decimal | None
    value_add: Decimal | None
    interpretation: str


@dataclass(frozen=True, slots=True)
class RegimeCounterfactualView:
    name: str
    sample_count: int
    win_rate: Decimal | None
    auc: Decimal | None
    average_return: Decimal | None
    notes: str


@dataclass(frozen=True, slots=True)
class SetupRegimeInteraction:
    setup_type: str
    regime: str
    candidate_count: int
    win_rate: Decimal | None
    clean_win_rate: Decimal | None
    excess_return_win_rate: Decimal | None
    auc: Decimal | None
    average_return: Decimal | None
    average_excess_return: Decimal | None
    average_mae: Decimal | None
    profitable_rejection_rate: Decimal | None
    avoided_downside: Decimal | None
    sample_sufficiency: str


@dataclass(frozen=True, slots=True)
class RetracementRegimeInteraction:
    dimension: str
    key: str
    sample_count: int
    retracement_return_correlation: Decimal | None
    average_retracement_score: Decimal | None
    win_rate: Decimal | None
    finding: RetracementRegimeFinding


@dataclass(frozen=True, slots=True)
class RegimeAuditDecision:
    primary_conclusion: RegimeAuditConclusion
    secondary_conclusions: tuple[RegimeAuditConclusion, ...]
    neutral_concentration_causes: tuple[NeutralConcentrationCause, ...]
    retracement_finding: RetracementRegimeFinding
    recommended_next_milestone: NextRegimeAuditMilestone
    prohibited_next_action: str
    explanation: str


@dataclass(frozen=True, slots=True)
class MarketRegimeAuditReport:
    candidate_count: int
    completed_outcome_count: int
    production_inventory: tuple[ProductionRegimeInventoryItem, ...]
    lineage: tuple[RegimeLineageRecord, ...]
    attachments: tuple[CandidateRegimeAttachment, ...]
    distributions: tuple[RegimeDistributionSummary, ...]
    transitions: tuple[RegimeTransition, ...]
    reference_comparison: tuple[RegimeReferenceComparison, ...]
    reference_quality: ReferenceStateQuality
    episodes: tuple[MarketEpisode, ...]
    feature_separability: tuple[RegimeFeatureSeparability, ...]
    intervention_metrics: tuple[RegimeInterventionMetric, ...]
    setup_regime_interactions: tuple[SetupRegimeInteraction, ...]
    retracement_interactions: tuple[RetracementRegimeInteraction, ...]
    counterfactuals: tuple[RegimeCounterfactualView, ...]
    decision: RegimeAuditDecision
    raw_approval_count_before: int
    raw_approval_count_after: int
    recommendation_scores_unchanged: bool
    verdicts_unchanged: bool
    regime_records_unchanged: bool
    timing_states_unchanged: bool
    raw_approvals_unchanged: bool
    strict_approvals_unchanged: bool
    allocations_unchanged: bool


@dataclass(frozen=True, slots=True)
class _RegimeAuditRow:
    record: CandidateDecisionRecord
    outcome: CandidateForwardWindowOutcome | None
    entry_state: EntryTimingState
    strict_approved: bool
    reference_state: ReferenceMarketState
    canonical_regime: CanonicalRegime
    base_score: Decimal
    adjusted_score: Decimal
    regime_adjustment: Decimal
    forward_return: Decimal | None
    excess_return: Decimal | None
    profitable: bool
    clean_win: bool
    clean_loss: bool
    retracement_score: Decimal | None


class MarketRegimeAuditEngine:
    def __init__(self, config: MarketRegimeAuditConfig | None = None) -> None:
        self._config = config or MarketRegimeAuditConfig()

    def analyze(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> MarketRegimeAuditReport:
        raw_approval_count_before = sum(
            1 for record in records if record.approved_for_deployment
        )
        score_snapshot = {
            record.candidate_id: record.strategy_score for record in records
        }
        verdict_snapshot = {
            record.candidate_id: record.final_verdict for record in records
        }
        regime_snapshot = {
            record.candidate_id: record.market_regime for record in records
        }
        allocation_snapshot = {
            record.candidate_id: (record.capital_action, record.approved_for_deployment)
            for record in records
        }
        timing_report = build_entry_timing_replay_report(
            records=records,
            outcomes=outcomes,
        )
        strict_approvals = {
            row.candidate_id: row.strict_approved
            for row in DirectionalSignalQualityAuditEngine()
            .analyze(records=records, outcomes=outcomes)
            .candidate_rows
        }
        entry_states = {
            row.candidate_id: row.assessment.entry_state for row in timing_report.rows
        }
        outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
        rows = tuple(
            self._row(
                record=record,
                outcome=_primary_window(outcome_by_id.get(record.candidate_id)),
                entry_state=entry_states.get(
                    record.candidate_id,
                    EntryTimingState.ENTRY_UNAVAILABLE,
                ),
                strict_approved=strict_approvals.get(record.candidate_id, False),
            )
            for record in records
        )
        completed_rows = tuple(row for row in rows if row.outcome is not None)
        attachments = tuple(self._attachment(record) for record in records)
        decision = self._decision(
            rows=completed_rows,
            attachments=attachments,
            distributions=self._distributions(rows),
            reference_quality=self._reference_quality(rows),
            intervention_metrics=self._intervention_metrics(completed_rows),
            retracement_interactions=self._retracement_interactions(completed_rows),
        )
        raw_approval_count_after = sum(
            1 for record in records if record.approved_for_deployment
        )
        return MarketRegimeAuditReport(
            candidate_count=len(records),
            completed_outcome_count=len(completed_rows),
            production_inventory=_production_inventory(records),
            lineage=_lineage(),
            attachments=attachments,
            distributions=self._distributions(rows),
            transitions=_transitions(records),
            reference_comparison=self._reference_comparison(rows),
            reference_quality=self._reference_quality(rows),
            episodes=self._episodes(completed_rows),
            feature_separability=self._feature_separability(completed_rows),
            intervention_metrics=self._intervention_metrics(completed_rows),
            setup_regime_interactions=self._setup_regime_interactions(completed_rows),
            retracement_interactions=self._retracement_interactions(completed_rows),
            counterfactuals=self._counterfactuals(completed_rows),
            decision=decision,
            raw_approval_count_before=raw_approval_count_before,
            raw_approval_count_after=raw_approval_count_after,
            recommendation_scores_unchanged=score_snapshot
            == {record.candidate_id: record.strategy_score for record in records},
            verdicts_unchanged=verdict_snapshot
            == {record.candidate_id: record.final_verdict for record in records},
            regime_records_unchanged=regime_snapshot
            == {record.candidate_id: record.market_regime for record in records},
            timing_states_unchanged=entry_states
            == {
                row.candidate_id: row.assessment.entry_state
                for row in build_entry_timing_replay_report(
                    records=records,
                    outcomes=outcomes,
                ).rows
            },
            raw_approvals_unchanged=raw_approval_count_before
            == raw_approval_count_after,
            strict_approvals_unchanged=strict_approvals
            == {
                row.candidate_id: row.strict_approved
                for row in DirectionalSignalQualityAuditEngine()
                .analyze(records=records, outcomes=outcomes)
                .candidate_rows
            },
            allocations_unchanged=allocation_snapshot
            == {
                record.candidate_id: (
                    record.capital_action,
                    record.approved_for_deployment,
                )
                for record in records
            },
        )

    def _row(
        self,
        *,
        record: CandidateDecisionRecord,
        outcome: CandidateForwardWindowOutcome | None,
        entry_state: EntryTimingState,
        strict_approved: bool,
    ) -> _RegimeAuditRow:
        forward_return = (
            None if outcome is None else outcome.forward_return_pct_from_entry
        )
        benchmark = _indicator(record, ("benchmark-return", "benchmark_return"))
        excess = (
            None
            if forward_return is None or benchmark is None
            else (forward_return - benchmark).quantize(_FOUR)
        )
        profitable = forward_return is not None and forward_return > _ZERO
        clean_win = (
            profitable
            and outcome is not None
            and not outcome.risk_stop_touched
            and (outcome.max_adverse_excursion_pct or _ZERO) >= Decimal("-8")
        )
        clean_loss = (
            forward_return is not None
            and forward_return < _ZERO
            and outcome is not None
            and outcome.risk_stop_touched
        )
        adjustment = _regime_adjustment(record)
        return _RegimeAuditRow(
            record=record,
            outcome=outcome,
            entry_state=entry_state,
            strict_approved=strict_approved,
            reference_state=_reference_state(record),
            canonical_regime=_canonical_regime(record.market_regime),
            base_score=(record.strategy_score - adjustment).quantize(_FOUR),
            adjusted_score=record.strategy_score,
            regime_adjustment=adjustment,
            forward_return=forward_return,
            excess_return=excess,
            profitable=profitable,
            clean_win=clean_win,
            clean_loss=clean_loss,
            retracement_score=_indicator(
                record,
                (
                    "retracement",
                    "retracement-score",
                    "retracement_quality",
                    "retracement-quality",
                ),
            ),
        )

    def _attachment(self, record: CandidateDecisionRecord) -> CandidateRegimeAttachment:
        issue_codes: list[str] = []
        if record.market_regime is None:
            join_method = RegimeJoinMethod.MISSING
            issue_codes.append("MISSING_REGIME")
        elif record.market_regime.strip().upper() == "NEUTRAL" and _has_missing_inputs(
            record
        ):
            join_method = RegimeJoinMethod.DEFAULTED_NEUTRAL
            issue_codes.append("POSSIBLE_MISSING_TO_NEUTRAL_FALLBACK")
        else:
            join_method = RegimeJoinMethod.EXACT
        attached_timestamp = record.evaluation_date
        age_days = (record.evaluation_date - attached_timestamp).days
        if age_days > self._config.stale_attachment_days:
            join_method = RegimeJoinMethod.STALE
            issue_codes.append("STALE_REGIME_ATTACHMENT")
        return CandidateRegimeAttachment(
            candidate_id=record.candidate_id,
            symbol=record.symbol,
            candidate_timestamp=record.created_at.isoformat(),
            attached_regime=record.market_regime,
            canonical_regime=_canonical_regime(record.market_regime),
            attached_regime_timestamp=attached_timestamp.isoformat(),
            age_days=age_days,
            join_method=join_method,
            knowable_at_decision_time=attached_timestamp <= record.evaluation_date,
            issue_codes=tuple(issue_codes),
        )

    def _distributions(
        self,
        rows: tuple[_RegimeAuditRow, ...],
    ) -> tuple[RegimeDistributionSummary, ...]:
        universes: tuple[tuple[str, tuple[_RegimeAuditRow, ...]], ...] = (
            ("all replay candidates", rows),
            ("completed replay outcomes", tuple(row for row in rows if row.outcome)),
            (
                "acceptably timed candidates",
                tuple(row for row in rows if row.entry_state in _PRIMARY_ENTRY_STATES),
            ),
            (
                "BUY/STRONG_BUY candidates",
                tuple(
                    row
                    for row in rows
                    if row.record.final_verdict in _POSITIVE_VERDICTS
                ),
            ),
            ("profitable outcomes", tuple(row for row in rows if row.profitable)),
            (
                "losing outcomes",
                tuple(
                    row
                    for row in rows
                    if row.forward_return is not None and row.forward_return <= _ZERO
                ),
            ),
        )
        result: list[RegimeDistributionSummary] = []
        for universe, items in universes:
            counts = Counter(_regime_text(row.record.market_regime) for row in items)
            total = len(items)
            for regime, count in sorted(counts.items()):
                durations = _regime_durations(
                    tuple(row.record for row in items),
                    regime=regime,
                )
                result.append(
                    RegimeDistributionSummary(
                        universe=universe,
                        regime=regime,
                        candidate_count=count,
                        percentage_share=_rate(count, total),
                        median_duration_days=_median(
                            tuple(Decimal(value) for value in durations)
                        ),
                        longest_duration_days=max(durations) if durations else None,
                        transition_count=sum(
                            item.count
                            for item in _transitions(tuple(row.record for row in items))
                            if item.from_regime == regime or item.to_regime == regime
                        ),
                        missing_default_rate=_rate(
                            sum(
                                1
                                for row in items
                                if row.record.market_regime is None
                                or (
                                    _regime_text(row.record.market_regime) == "NEUTRAL"
                                    and _has_missing_inputs(row.record)
                                )
                            ),
                            total,
                        ),
                        candidate_generation_rate=_rate(count, len(rows)),
                    )
                )
        return tuple(result)

    def _reference_comparison(
        self,
        rows: tuple[_RegimeAuditRow, ...],
    ) -> tuple[RegimeReferenceComparison, ...]:
        counts = Counter(
            (_regime_text(row.record.market_regime), row.reference_state)
            for row in rows
        )
        return tuple(
            RegimeReferenceComparison(
                production_regime=production,
                reference_state=reference,
                count=count,
            )
            for (production, reference), count in sorted(
                counts.items(), key=lambda item: (item[0][0], item[0][1].value)
            )
        )

    def _reference_quality(
        self,
        rows: tuple[_RegimeAuditRow, ...],
    ) -> ReferenceStateQuality:
        comparable = tuple(
            row
            for row in rows
            if row.reference_state is not ReferenceMarketState.UNAVAILABLE
        )
        labels = sorted({row.reference_state.value for row in comparable})
        recalls = []
        precisions = []
        for label in labels:
            tp = sum(
                1
                for row in comparable
                if _canonical_matches_reference(
                    row.canonical_regime, row.reference_state
                )
                and row.reference_state.value == label
            )
            ref_count = sum(
                1 for row in comparable if row.reference_state.value == label
            )
            prod_count = sum(
                1
                for row in comparable
                if _canonical_matches_label(row.canonical_regime, label)
            )
            recall = _rate(tp, ref_count)
            precision = _rate(tp, prod_count)
            if recall is not None:
                recalls.append(recall)
            if precision is not None:
                precisions.append(precision)
        extreme = tuple(
            row
            for row in comparable
            if row.reference_state
            in {
                ReferenceMarketState.BULLISH_TREND,
                ReferenceMarketState.BEARISH_TREND,
                ReferenceMarketState.CORRECTION,
                ReferenceMarketState.HIGH_VOLATILITY,
            }
        )
        neutral_extreme = sum(
            1 for row in extreme if row.canonical_regime is CanonicalRegime.NEUTRAL
        )
        return ReferenceStateQuality(
            sample_count=len(comparable),
            balanced_accuracy=_average(tuple(recalls)),
            macro_precision=_average(tuple(precisions)),
            macro_recall=_average(tuple(recalls)),
            cohen_kappa=_cohen_kappa(comparable),
            extreme_reference_neutral_rate=_rate(neutral_extreme, len(extreme)),
            missed_major_turns=neutral_extreme,
            false_transitions=_false_transition_count(comparable),
            transition_lag_days=Decimal("0") if comparable else None,
        )

    def _episodes(self, rows: tuple[_RegimeAuditRow, ...]) -> tuple[MarketEpisode, ...]:
        by_date: dict[date, list[_RegimeAuditRow]] = defaultdict(list)
        for row in rows:
            by_date[row.record.evaluation_date].append(row)
        daily = tuple(
            (
                day,
                _average(
                    tuple(
                        _indicator(
                            item.record, ("benchmark-return", "benchmark_return")
                        )
                        for item in items
                    )
                ),
                tuple(items),
            )
            for day, items in sorted(by_date.items())
        )
        present = tuple(item for item in daily if item[1] is not None)
        if not present:
            return ()
        episodes: list[MarketEpisode] = []
        current: list[tuple[date, Decimal, tuple[_RegimeAuditRow, ...]]] = []
        current_sign: str | None = None
        for day, benchmark, items in present:
            sign = (
                "drawdown"
                if benchmark is not None and benchmark <= Decimal("-3")
                else (
                    "recovery"
                    if benchmark is not None and benchmark >= Decimal("3")
                    else "sideways"
                )
            )
            if current and sign != current_sign:
                episode = _episode(current_sign or "sideways", tuple(current))
                if episode is not None:
                    episodes.append(episode)
                current = []
            current.append((day, benchmark or _ZERO, items))
            current_sign = sign
        if current:
            episode = _episode(current_sign or "sideways", tuple(current))
            if episode is not None:
                episodes.append(episode)
        return tuple(episodes)

    def _feature_separability(
        self,
        rows: tuple[_RegimeAuditRow, ...],
    ) -> tuple[RegimeFeatureSeparability, ...]:
        features = (
            "market-regime",
            "trend",
            "price",
            "volume",
            "retracement",
            "atr",
            "benchmark-return",
        )
        result = []
        for feature in features:
            values = tuple(_indicator(row.record, (feature,)) for row in rows)
            returns = tuple(row.forward_return for row in rows)
            winners = tuple(
                _indicator(row.record, (feature,)) for row in rows if row.profitable
            )
            losers = tuple(
                _indicator(row.record, (feature,))
                for row in rows
                if row.forward_return is not None and row.forward_return <= _ZERO
            )
            winner_mean = _average(winners)
            loser_mean = _average(losers)
            corr = _spearman(values, returns)
            result.append(
                RegimeFeatureSeparability(
                    feature=feature,
                    availability=_rate(
                        sum(1 for value in values if value is not None), len(values)
                    ),
                    correlation_with_return=corr,
                    winner_mean=winner_mean,
                    loser_mean=loser_mean,
                    winner_loser_separation=None
                    if winner_mean is None or loser_mean is None
                    else (winner_mean - loser_mean).quantize(_FOUR),
                    missingness=_rate(
                        sum(1 for value in values if value is None), len(values)
                    ),
                    classification=_feature_label(corr, values),
                )
            )
        return tuple(result)

    def _intervention_metrics(
        self,
        rows: tuple[_RegimeAuditRow, ...],
    ) -> tuple[RegimeInterventionMetric, ...]:
        base_scores = tuple(row.base_score for row in rows)
        adjusted_scores = tuple(row.adjusted_score for row in rows)
        returns = tuple(row.forward_return for row in rows)
        labels = tuple(row.profitable for row in rows)
        before_auc = _roc_auc(base_scores, labels)
        after_auc = _roc_auc(adjusted_scores, labels)
        before_corr = _spearman(base_scores, returns)
        after_corr = _spearman(adjusted_scores, returns)
        before_top = _top_win_rate(rows, lambda row: row.base_score)
        after_top = _top_win_rate(rows, lambda row: row.adjusted_score)
        before_precision = _buy_precision(rows, lambda row: row.base_score)
        after_precision = _buy_precision(rows, lambda row: row.adjusted_score)
        return (
            _metric("AUC", before_auc, after_auc),
            _metric("Spearman", before_corr, after_corr),
            _metric("Top decile win rate", before_top, after_top),
            _metric("BUY precision proxy", before_precision, after_precision),
        )

    def _setup_regime_interactions(
        self,
        rows: tuple[_RegimeAuditRow, ...],
    ) -> tuple[SetupRegimeInteraction, ...]:
        grouped: dict[tuple[str, str], list[_RegimeAuditRow]] = defaultdict(list)
        for row in rows:
            grouped[
                (
                    row.record.setup_type or "UNKNOWN",
                    _regime_text(row.record.market_regime),
                )
            ].append(row)
        result = []
        for (setup, regime), items in sorted(grouped.items()):
            group = tuple(items)
            result.append(
                SetupRegimeInteraction(
                    setup_type=setup,
                    regime=regime,
                    candidate_count=len(group),
                    win_rate=_rate(
                        sum(1 for row in group if row.profitable), len(group)
                    ),
                    clean_win_rate=_rate(
                        sum(1 for row in group if row.clean_win), len(group)
                    ),
                    excess_return_win_rate=_rate(
                        sum(
                            1
                            for row in group
                            if row.excess_return is not None
                            and row.excess_return > _ZERO
                        ),
                        sum(1 for row in group if row.excess_return is not None),
                    ),
                    auc=_roc_auc(
                        tuple(row.adjusted_score for row in group),
                        tuple(row.profitable for row in group),
                    ),
                    average_return=_average(tuple(row.forward_return for row in group)),
                    average_excess_return=_average(
                        tuple(row.excess_return for row in group)
                    ),
                    average_mae=_average(
                        tuple(
                            None
                            if row.outcome is None
                            else row.outcome.max_adverse_excursion_pct
                            for row in group
                        )
                    ),
                    profitable_rejection_rate=_rate(
                        sum(
                            1
                            for row in group
                            if row.profitable
                            and row.record.final_verdict not in _POSITIVE_VERDICTS
                        ),
                        len(group),
                    ),
                    avoided_downside=_sum(
                        tuple(
                            row.forward_return
                            for row in group
                            if row.record.final_verdict not in _POSITIVE_VERDICTS
                            and row.forward_return is not None
                            and row.forward_return <= _ZERO
                        )
                    ),
                    sample_sufficiency="sufficient"
                    if len(group) >= self._config.minimum_sample
                    else "insufficient",
                )
            )
        return tuple(result)

    def _retracement_interactions(
        self,
        rows: tuple[_RegimeAuditRow, ...],
    ) -> tuple[RetracementRegimeInteraction, ...]:
        dimensions: tuple[tuple[str, Callable[[_RegimeAuditRow], str]], ...] = (
            ("production regime", lambda row: _regime_text(row.record.market_regime)),
            ("reference regime", lambda row: row.reference_state.value),
            ("setup type", lambda row: row.record.setup_type or "UNKNOWN"),
            ("entry timing", lambda row: row.entry_state.value),
        )
        result = []
        for dimension, getter in dimensions:
            grouped: dict[str, list[_RegimeAuditRow]] = defaultdict(list)
            for row in rows:
                grouped[str(getter(row))].append(row)
            for key, items in sorted(grouped.items()):
                group = tuple(items)
                scores = tuple(row.retracement_score for row in group)
                corr = _spearman(scores, tuple(row.forward_return for row in group))
                result.append(
                    RetracementRegimeInteraction(
                        dimension=dimension,
                        key=key,
                        sample_count=len(group),
                        retracement_return_correlation=corr,
                        average_retracement_score=_average(scores),
                        win_rate=_rate(
                            sum(1 for row in group if row.profitable), len(group)
                        ),
                        finding=_retracement_finding(corr, group),
                    )
                )
        return tuple(result)

    def _counterfactuals(
        self,
        rows: tuple[_RegimeAuditRow, ...],
    ) -> tuple[RegimeCounterfactualView, ...]:
        views: tuple[tuple[str, tuple[_RegimeAuditRow, ...], str], ...] = (
            ("recorded production adjustment", rows, "Recorded recommendation path."),
            ("no regime adjustment", rows, "Uses reconstructed pre-regime score."),
            ("price component only", rows, "Ranks by recorded price component."),
            ("regime as veto", rows, "Excludes negative production regimes."),
            ("regime as annotation", rows, "Ranks without changing score."),
            (
                "extreme regimes only",
                tuple(
                    row
                    for row in rows
                    if row.canonical_regime
                    in {
                        CanonicalRegime.STRONG_POSITIVE,
                        CanonicalRegime.STRONG_NEGATIVE,
                        CanonicalRegime.BULLISH_TREND,
                        CanonicalRegime.BEARISH_TREND,
                    }
                ),
                "Only extreme regimes receive diagnostic attention.",
            ),
            (
                "NEUTRAL zero adjustment",
                rows,
                "Treats neutral as zero adjustment for comparison only.",
            ),
            (
                "missing unavailable",
                tuple(row for row in rows if row.record.market_regime is not None),
                "Drops missing regimes instead of converting to neutral.",
            ),
        )
        result = []
        for name, sample, notes in views:
            score_getter = _score_getter_for_view(name)
            result.append(
                RegimeCounterfactualView(
                    name=name,
                    sample_count=len(sample),
                    win_rate=_rate(
                        sum(1 for row in sample if row.profitable), len(sample)
                    ),
                    auc=_roc_auc(
                        tuple(score_getter(row) for row in sample),
                        tuple(row.profitable for row in sample),
                    ),
                    average_return=_average(
                        tuple(row.forward_return for row in sample)
                    ),
                    notes=notes,
                )
            )
        return tuple(result)

    def _decision(
        self,
        *,
        rows: tuple[_RegimeAuditRow, ...],
        attachments: tuple[CandidateRegimeAttachment, ...],
        distributions: tuple[RegimeDistributionSummary, ...],
        reference_quality: ReferenceStateQuality,
        intervention_metrics: tuple[RegimeInterventionMetric, ...],
        retracement_interactions: tuple[RetracementRegimeInteraction, ...],
    ) -> RegimeAuditDecision:
        if len(rows) < self._config.minimum_sample:
            primary = RegimeAuditConclusion.INSUFFICIENT_EVIDENCE_FOR_REGIME_CONCLUSION
            milestone = NextRegimeAuditMilestone.COLLECT_MARKET_REGIME_HISTORY
        elif any(item.join_method is RegimeJoinMethod.STALE for item in attachments):
            primary = (
                RegimeAuditConclusion.REGIME_TIMESTAMP_ALIGNMENT_IS_PRIMARY_BOTTLENECK
            )
            milestone = NextRegimeAuditMilestone.REGIME_TIMESTAMP_JOIN_REPAIR_DESIGN
        elif (
            self._neutral_share(distributions)
            >= self._config.neutral_concentration_threshold
        ):
            if self._missing_default_rate(distributions) >= Decimal("0.20"):
                primary = (
                    RegimeAuditConclusion.DEFAULT_NEUTRAL_FALLBACK_IS_PRIMARY_BOTTLENECK
                )
                milestone = NextRegimeAuditMilestone.COLLECT_MARKET_REGIME_HISTORY
            else:
                primary = RegimeAuditConclusion.REGIME_CLASSIFIER_COLLAPSES_TO_NEUTRAL
                milestone = (
                    NextRegimeAuditMilestone.MARKET_REGIME_CLASSIFIER_THRESHOLD_AUDIT
                )
        elif any(
            item.value_add is not None
            and item.value_add <= self._config.harmful_value_add_threshold
            for item in intervention_metrics
        ):
            primary = RegimeAuditConclusion.REGIME_INTERVENTION_DEGRADES_SIGNAL_QUALITY
            milestone = NextRegimeAuditMilestone.REGIME_INTERVENTION_RESEARCH
        elif _momentum_neutral_is_weak(rows):
            primary = (
                RegimeAuditConclusion.MOMENTUM_NEUTRAL_INTERACTION_IS_PRIMARY_BOTTLENECK
            )
            milestone = NextRegimeAuditMilestone.MOMENTUM_NEUTRAL_SETUP_AUDIT
        elif (
            reference_quality.balanced_accuracy is not None
            and reference_quality.balanced_accuracy >= Decimal("0.55")
        ):
            primary = RegimeAuditConclusion.REGIME_CLASSIFIER_HAS_USEFUL_SEPARATION
            milestone = NextRegimeAuditMilestone.NO_REGIME_CHANGE_RECOMMENDED
        else:
            primary = RegimeAuditConclusion.MARKET_REGIME_IS_NOT_THE_PRIMARY_BOTTLENECK
            milestone = (
                NextRegimeAuditMilestone.RETRACEMENT_SIGN_AND_NORMALIZATION_AUDIT
            )
        retracement_finding = _global_retracement_finding(retracement_interactions)
        secondary: list[RegimeAuditConclusion] = []
        if retracement_finding in {
            RetracementRegimeFinding.RETRACEMENT_GLOBAL_SIGN_ERROR_SUSPECTED,
            RetracementRegimeFinding.RETRACEMENT_NORMALIZATION_DEFECT_SUSPECTED,
        }:
            secondary.append(
                RegimeAuditConclusion.REGIME_FEATURE_QUALITY_IS_PRIMARY_BOTTLENECK
            )
        if any(
            item.value_add is not None and item.value_add < _ZERO
            for item in intervention_metrics
        ):
            secondary.append(
                RegimeAuditConclusion.REGIME_INTERVENTION_DEGRADES_SIGNAL_QUALITY
            )
        causes = self._neutral_causes(
            attachments=attachments,
            distributions=distributions,
            rows=rows,
        )
        return RegimeAuditDecision(
            primary_conclusion=primary,
            secondary_conclusions=tuple(dict.fromkeys(secondary)),
            neutral_concentration_causes=causes,
            retracement_finding=retracement_finding,
            recommended_next_milestone=milestone,
            prohibited_next_action=(
                "Do not repair thresholds, regime labels, scores, weights, gates, "
                "trade plans, approvals, allocations, or retracement signs from "
                "this diagnostic audit."
            ),
            explanation=_decision_explanation(primary, causes, retracement_finding),
        )

    def _neutral_share(
        self,
        distributions: tuple[RegimeDistributionSummary, ...],
    ) -> Decimal:
        for item in distributions:
            if (
                item.universe == "completed replay outcomes"
                and item.regime == "NEUTRAL"
                and item.percentage_share is not None
            ):
                return item.percentage_share
        return _ZERO

    def _missing_default_rate(
        self,
        distributions: tuple[RegimeDistributionSummary, ...],
    ) -> Decimal:
        rates = tuple(
            item.missing_default_rate
            for item in distributions
            if item.universe == "all replay candidates"
            and item.missing_default_rate is not None
        )
        return max(rates) if rates else _ZERO

    def _neutral_causes(
        self,
        *,
        attachments: tuple[CandidateRegimeAttachment, ...],
        distributions: tuple[RegimeDistributionSummary, ...],
        rows: tuple[_RegimeAuditRow, ...],
    ) -> tuple[NeutralConcentrationCause, ...]:
        if not rows:
            return (NeutralConcentrationCause.INSUFFICIENT_EVIDENCE,)
        causes: list[NeutralConcentrationCause] = []
        if (
            self._neutral_share(distributions)
            >= self._config.neutral_concentration_threshold
        ):
            causes.append(NeutralConcentrationCause.OVERLY_BROAD_NEUTRAL_BOUNDARIES)
        if any(
            item.join_method is RegimeJoinMethod.DEFAULTED_NEUTRAL
            for item in attachments
        ):
            causes.append(NeutralConcentrationCause.DEFAULT_NEUTRAL_FALLBACK)
        if any(item.join_method is RegimeJoinMethod.STALE for item in attachments):
            causes.append(NeutralConcentrationCause.STALE_REGIME_ATTACHMENT)
        setup_counts = Counter(row.record.setup_type or "UNKNOWN" for row in rows)
        if setup_counts and max(setup_counts.values()) / len(rows) >= 0.70:
            causes.append(
                NeutralConcentrationCause.CANDIDATE_GENERATION_SELECTION_EFFECT
            )
        if not causes:
            causes.append(NeutralConcentrationCause.GENUINELY_NEUTRAL_SAMPLE)
        return tuple(dict.fromkeys(causes))


def render_market_regime_audit(report: MarketRegimeAuditReport) -> tuple[str, ...]:
    lines = [
        "Market Regime Classifier and Intervention Audit",
        f"Candidates Audited: {report.candidate_count}",
        f"Completed Outcomes: {report.completed_outcome_count}",
        "",
        "Production Regime Inventory:",
        *_inventory_lines(report.production_inventory),
        "",
        "Candidate Timestamp and Join Findings:",
        *_attachment_summary_lines(report.attachments),
        "",
        "Regime Distribution:",
        *_distribution_lines(report.distributions),
        "",
        "Reference-State Comparison:",
        *_reference_quality_lines(report.reference_quality),
        *_reference_comparison_lines(report.reference_comparison),
        "",
        "Major Market Episodes:",
        *_episode_lines(report.episodes),
        "",
        "Regime Feature Separability:",
        *_feature_lines(report.feature_separability),
        "",
        "Pre/Post Regime Intervention:",
        *_intervention_lines(report.intervention_metrics),
        "",
        "Setup-Regime Interaction:",
        *_setup_regime_lines(report.setup_regime_interactions),
        "",
        "Retracement-Regime Interaction:",
        *_retracement_lines(report.retracement_interactions),
        "",
        "Counterfactual Diagnostic Views:",
        *_counterfactual_lines(report.counterfactuals),
        "",
        f"Primary Conclusion: {report.decision.primary_conclusion.value}",
        "Secondary Conclusions:",
        *(
            [f"- {item.value}" for item in report.decision.secondary_conclusions]
            or ["- none"]
        ),
        "Neutral Concentration Causes:",
        *[f"- {item.value}" for item in report.decision.neutral_concentration_causes],
        f"Retracement Finding: {report.decision.retracement_finding.value}",
        (
            "Recommended Next Milestone: "
            f"{report.decision.recommended_next_milestone.value}"
        ),
        f"Prohibited Next Action: {report.decision.prohibited_next_action}",
        f"Explanation: {report.decision.explanation}",
        (
            "Policy Integrity: no regime records, recommendation scores, verdicts, "
            "timing states, approvals, allocations, thresholds, weights, or trade "
            "plans were changed."
        ),
    ]
    return tuple(lines)


def group_market_regime_audit(
    report: MarketRegimeAuditReport,
    *,
    group_by: str,
) -> tuple[str, ...]:
    normalized = group_by.strip().lower()
    if normalized == "regime":
        return (
            "Market Regime Audit Grouped By regime:",
            *_distribution_lines(report.distributions),
        )
    if normalized == "setup":
        return (
            "Market Regime Audit Grouped By setup:",
            *_setup_regime_lines(report.setup_regime_interactions),
        )
    if normalized == "lineage":
        return ("Regime Lineage:", *_lineage_lines(report.lineage))
    if normalized == "transitions":
        return ("Regime Transitions:", *_transition_lines(report.transitions))
    if normalized == "reference":
        return (
            "Regime Reference Comparison:",
            *_reference_quality_lines(report.reference_quality),
            *_reference_comparison_lines(report.reference_comparison),
        )
    if normalized == "intervention":
        return (
            "Regime Intervention:",
            *_intervention_lines(report.intervention_metrics),
        )
    if normalized == "episodes":
        return ("Regime Episodes:", *_episode_lines(report.episodes))
    if normalized == "retracement":
        return (
            "Regime Retracement Interaction:",
            *_retracement_lines(report.retracement_interactions),
        )
    return render_market_regime_audit(report)


def export_market_regime_audit_json(
    report: MarketRegimeAuditReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_report_dict(report), indent=2, default=str), encoding="utf-8"
    )
    return path


def export_market_regime_audit_csv(
    report: MarketRegimeAuditReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = tuple(_attachment_dict(item) for item in report.attachments)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=tuple(rows[0]) if rows else ("candidate_id",),
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def _production_inventory(
    records: tuple[CandidateDecisionRecord, ...],
) -> tuple[ProductionRegimeInventoryItem, ...]:
    items: list[ProductionRegimeInventoryItem] = []
    enum_sources: tuple[tuple[str, tuple[StrEnum, ...], str], ...] = (
        ("IntelligenceBias", tuple(IntelligenceBias), "market composite bias"),
        ("AccumulationPhase", tuple(AccumulationPhase), "feature classification"),
        ("DistributionPhase", tuple(DistributionPhase), "feature classification"),
        ("LiquidityQuality", tuple(LiquidityQuality), "risk classification"),
        ("BreadthCondition", tuple(BreadthCondition), "breadth classification"),
        ("SectorRotationPhase", tuple(SectorRotationPhase), "sector classification"),
        ("CorrelationRisk", tuple(CorrelationRisk), "risk classification"),
        ("DeliveryBehavior", tuple(DeliveryBehavior), "stock mood input"),
        ("DerivativesPositioning", tuple(DerivativesPositioning), "derivatives input"),
        ("MarketMood", tuple(MarketMood), "stock mood"),
        ("MarketDirectionBias", tuple(MarketDirectionBias), "directional bias"),
    )
    for source, labels, role in enum_sources:
        for label in labels:
            items.append(
                ProductionRegimeInventoryItem(
                    source=source,
                    label=label.value,
                    canonical=_canonical_regime(label.value),
                    role=role,
                    notes="Production enum discovered from current implementation.",
                )
            )
    for observed_label in sorted(
        {_regime_text(record.market_regime) for record in records}
    ):
        items.append(
            ProductionRegimeInventoryItem(
                source="CandidateDecisionRecord.market_regime",
                label=observed_label,
                canonical=_canonical_regime(observed_label),
                role="recorded candidate attachment",
                notes="Observed in replay candidate ledger.",
            )
        )
    return tuple(items)


def _lineage() -> tuple[RegimeLineageRecord, ...]:
    return (
        RegimeLineageRecord(
            stage="market and breadth inputs",
            source_module="alpha.market_intelligence.intelligence",
            source_function="StockIntelligenceInput / MarketBreadthInput",
            inputs=(
                "price_change_percent",
                "delivery_percent",
                "delivery_change_percent",
                "volume_change_percent",
                "turnover_value",
                "spread_percent",
                "volatility_percent",
                "advances",
                "declines",
            ),
            thresholds=("bounded percent validation",),
            missing_input_fields=("standalone benchmark history",),
            fallback_path="input provider must supply values; no audit mutation",
            persisted=False,
            notes="Candidate ledger does not persist full market input snapshots.",
        ),
        RegimeLineageRecord(
            stage="feature construction and classification",
            source_module="alpha.market_intelligence.intelligence",
            source_function="MarketIntelligenceCompositeEngine.assess",
            inputs=(
                "accumulation",
                "distribution",
                "liquidity",
                "breadth",
                "sector_rotation",
                "correlation",
            ),
            thresholds=("positive >= 0.60", "negative <= 0.40"),
            missing_input_fields=("previous regime", "hysteresis state"),
            fallback_path="bias defaults to NEUTRAL unless composite crosses boundary",
            persisted=False,
            notes="No persistent regime transition table is available in the ledger.",
        ),
        RegimeLineageRecord(
            stage="candidate regime attachment",
            source_module="alpha.candidate_learning.models",
            source_function="CandidateDecisionRecord.market_regime",
            inputs=("market_regime", "evaluation_date", "created_at"),
            thresholds=("none",),
            missing_input_fields=("attached source timestamp", "join provenance"),
            fallback_path="missing or NEUTRAL states are flagged by this audit",
            persisted=True,
            notes="Audit validates recorded attachment without relabelling it.",
        ),
        RegimeLineageRecord(
            stage="recommendation intervention",
            source_module="alpha.recommendation_intelligence.engines",
            source_function="EvidenceScoringEngine._regime_adjustment",
            inputs=("market_regime", "setup_type", "evidence signals"),
            thresholds=("BULL rewards", "BEAR penalizes", "SIDEWAYS/other cautions"),
            missing_input_fields=("persisted pre-regime score",),
            fallback_path="pre-regime score is reconstructed only for diagnostics",
            persisted=False,
            notes="Counterfactual views are research-only and do not change outputs.",
        ),
    )


def _primary_window(
    outcome: CandidateForwardOutcome | None,
) -> CandidateForwardWindowOutcome | None:
    if outcome is None:
        return None
    by_window = {window.window: window for window in outcome.windows}
    for label in ("20d", "10d", "5d", "3d", "1d", "60d"):
        window = by_window.get(label)
        if (
            window is not None
            and window.outcome_label is not CandidateOutcomeLabel.DATA_MISSING
        ):
            return window
    return outcome.windows[0] if outcome.windows else None


def _canonical_regime(value: str | None) -> CanonicalRegime:
    if value is None:
        return CanonicalRegime.UNAVAILABLE
    normalized = value.strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "BULL": CanonicalRegime.BULLISH_TREND,
        "BULLISH": CanonicalRegime.BULLISH_TREND,
        "POSITIVE": CanonicalRegime.POSITIVE,
        "STRONG_ACCUMULATION": CanonicalRegime.STRONG_POSITIVE,
        "BROAD_PARTICIPATION": CanonicalRegime.POSITIVE,
        "LEADERSHIP_EXPANSION": CanonicalRegime.POSITIVE,
        "BEAR": CanonicalRegime.BEARISH_TREND,
        "BEARISH": CanonicalRegime.BEARISH_TREND,
        "NEGATIVE": CanonicalRegime.NEGATIVE,
        "STRONG_DISTRIBUTION": CanonicalRegime.STRONG_NEGATIVE,
        "WEAK_PARTICIPATION": CanonicalRegime.NEGATIVE,
        "LEADERSHIP_CONTRACTION": CanonicalRegime.NEGATIVE,
        "HIGH": CanonicalRegime.POSITIVE,
        "LOW": CanonicalRegime.POSITIVE,
        "THIN": CanonicalRegime.NEGATIVE,
        "MODERATE": CanonicalRegime.NEUTRAL,
        "ACCEPTABLE": CanonicalRegime.NEUTRAL,
        "SIDEWAYS": CanonicalRegime.SIDEWAYS,
        "NEUTRAL": CanonicalRegime.NEUTRAL,
        "NO_ACCUMULATION": CanonicalRegime.NEUTRAL,
        "NO_DISTRIBUTION": CanonicalRegime.NEUTRAL,
        "SELECTIVE_PARTICIPATION": CanonicalRegime.NEUTRAL,
        "SELECTIVE_LEADERSHIP": CanonicalRegime.NEUTRAL,
        "UNKNOWN": CanonicalRegime.UNKNOWN,
        "UNAVAILABLE": CanonicalRegime.UNAVAILABLE,
    }
    return aliases.get(normalized, CanonicalRegime.UNKNOWN)


def _reference_state(record: CandidateDecisionRecord) -> ReferenceMarketState:
    benchmark = _indicator(record, ("benchmark-return", "benchmark_return"))
    trend = _indicator(record, ("trend", "price", "price-structure"))
    volatility = _indicator(record, ("atr", "volatility", "volatility-risk"))
    if volatility is not None and volatility >= Decimal("8"):
        return ReferenceMarketState.HIGH_VOLATILITY
    if benchmark is not None:
        if benchmark <= Decimal("-8"):
            return ReferenceMarketState.CORRECTION
        if benchmark <= Decimal("-3"):
            return ReferenceMarketState.BEARISH_TREND
        if benchmark >= Decimal("5"):
            return ReferenceMarketState.BULLISH_TREND
        if benchmark >= Decimal("2"):
            return ReferenceMarketState.RECOVERY
        return ReferenceMarketState.SIDEWAYS
    if trend is not None:
        if trend >= Decimal("75"):
            return ReferenceMarketState.BULLISH_TREND
        if trend <= Decimal("35"):
            return ReferenceMarketState.BEARISH_TREND
        return ReferenceMarketState.SIDEWAYS
    return ReferenceMarketState.UNAVAILABLE


def _regime_adjustment(record: CandidateDecisionRecord) -> Decimal:
    stored = _indicator(record, ("regime-adjustment", "regime_adjustment"))
    if stored is not None:
        return stored
    regime = (record.market_regime or "").strip().upper()
    setup = (record.setup_type or "").strip().upper()
    if regime in {"BULL", "BULLISH", "POSITIVE", "STRONG_POSITIVE"}:
        return Decimal("4") if "BREAKOUT" in setup else Decimal("2")
    if regime in {"BEAR", "BEARISH", "NEGATIVE", "STRONG_NEGATIVE"}:
        return Decimal("-8")
    if "BREAKOUT" in setup:
        return Decimal("-4")
    return Decimal("-2")


def _indicator(
    record: CandidateDecisionRecord, keys: tuple[str, ...]
) -> Decimal | None:
    normalized = {
        key.replace("_", "-").lower(): value
        for key, value in record.indicator_scores.items()
    }
    for key in keys:
        value = normalized.get(key.replace("_", "-").lower())
        if value is not None:
            try:
                return Decimal(str(value))
            except Exception:
                return None
    return None


def _has_missing_inputs(record: CandidateDecisionRecord) -> bool:
    text = " ".join(
        (
            record.data_quality,
            record.explanation,
            " ".join(record.rejection_reasons),
        )
    ).upper()
    return "MISSING" in text or "UNAVAILABLE" in text or "INSUFFICIENT" in text


def _regime_text(value: str | None) -> str:
    return (value or "UNAVAILABLE").strip().upper() or "UNAVAILABLE"


def _regime_durations(
    records: tuple[CandidateDecisionRecord, ...],
    *,
    regime: str,
) -> tuple[int, ...]:
    days = sorted({record.evaluation_date for record in records})
    if not days:
        return ()
    by_day: dict[date, str] = {}
    for record in records:
        by_day.setdefault(record.evaluation_date, _regime_text(record.market_regime))
    durations: list[int] = []
    current = 0
    for day in days:
        if by_day.get(day) == regime:
            current += 1
        elif current:
            durations.append(current)
            current = 0
    if current:
        durations.append(current)
    return tuple(durations)


def _transitions(
    records: tuple[CandidateDecisionRecord, ...],
) -> tuple[RegimeTransition, ...]:
    by_date: dict[date, str] = {}
    for record in sorted(records, key=lambda item: (item.evaluation_date, item.symbol)):
        by_date.setdefault(record.evaluation_date, _regime_text(record.market_regime))
    counts: Counter[tuple[str, str]] = Counter()
    previous: str | None = None
    for _, regime in sorted(by_date.items()):
        if previous is not None and previous != regime:
            counts[(previous, regime)] += 1
        previous = regime
    return tuple(
        RegimeTransition(from_regime=left, to_regime=right, count=count)
        for (left, right), count in sorted(counts.items())
    )


def _canonical_matches_reference(
    production: CanonicalRegime,
    reference: ReferenceMarketState,
) -> bool:
    if reference is ReferenceMarketState.BULLISH_TREND:
        return production in {
            CanonicalRegime.BULLISH_TREND,
            CanonicalRegime.POSITIVE,
            CanonicalRegime.STRONG_POSITIVE,
        }
    if reference is ReferenceMarketState.RECOVERY:
        return production in {CanonicalRegime.RECOVERY, CanonicalRegime.POSITIVE}
    if reference is ReferenceMarketState.BEARISH_TREND:
        return production in {
            CanonicalRegime.BEARISH_TREND,
            CanonicalRegime.NEGATIVE,
            CanonicalRegime.STRONG_NEGATIVE,
        }
    if reference is ReferenceMarketState.CORRECTION:
        return production in {
            CanonicalRegime.CORRECTION,
            CanonicalRegime.NEGATIVE,
            CanonicalRegime.STRONG_NEGATIVE,
            CanonicalRegime.BEARISH_TREND,
        }
    if reference is ReferenceMarketState.SIDEWAYS:
        return production in {CanonicalRegime.SIDEWAYS, CanonicalRegime.NEUTRAL}
    if reference is ReferenceMarketState.HIGH_VOLATILITY:
        return production is CanonicalRegime.HIGH_VOLATILITY
    return False


def _canonical_matches_label(production: CanonicalRegime, label: str) -> bool:
    try:
        return _canonical_matches_reference(production, ReferenceMarketState(label))
    except ValueError:
        return False


def _cohen_kappa(rows: tuple[_RegimeAuditRow, ...]) -> Decimal | None:
    if not rows:
        return None
    observed = _rate(
        sum(
            1
            for row in rows
            if _canonical_matches_reference(row.canonical_regime, row.reference_state)
        ),
        len(rows),
    )
    if observed is None:
        return None
    production_counts = Counter(row.canonical_regime.value for row in rows)
    reference_counts = Counter(row.reference_state.value for row in rows)
    expected = sum(
        Decimal(production_counts.get(label, 0))
        * Decimal(reference_counts.get(label, 0))
        for label in set(production_counts) | set(reference_counts)
    ) / (Decimal(len(rows)) ** 2)
    if expected == _ONE:
        return None
    return ((observed - expected) / (_ONE - expected)).quantize(_FOUR)


def _false_transition_count(rows: tuple[_RegimeAuditRow, ...]) -> int:
    ordered = sorted(
        rows, key=lambda row: (row.record.evaluation_date, row.record.symbol)
    )
    false_count = 0
    previous_production: CanonicalRegime | None = None
    previous_reference: ReferenceMarketState | None = None
    for row in ordered:
        if (
            previous_production is not None
            and previous_reference is not None
            and row.canonical_regime != previous_production
            and row.reference_state == previous_reference
        ):
            false_count += 1
        previous_production = row.canonical_regime
        previous_reference = row.reference_state
    return false_count


def _episode(
    label: str,
    items: tuple[tuple[date, Decimal, tuple[_RegimeAuditRow, ...]], ...],
) -> MarketEpisode | None:
    if len(items) < 1:
        return None
    rows = tuple(row for _, _, group in items for row in group)
    returns = tuple(value for _, value, _ in items)
    if not rows:
        return None
    extreme_day = (
        min(items, key=lambda item: item[1])
        if label == "drawdown"
        else max(items, key=lambda item: item[1])
    )
    return MarketEpisode(
        label=label,
        start=items[0][0].isoformat(),
        trough_or_peak=extreme_day[0].isoformat(),
        end=items[-1][0].isoformat(),
        benchmark_return=_sum(returns),
        maximum_drawdown=min(returns).quantize(_FOUR),
        volatility=_average(tuple(abs(value) for value in returns)),
        production_regime_sequence=tuple(
            dict.fromkeys(_regime_text(row.record.market_regime) for row in rows)
        ),
        reference_regime_sequence=tuple(
            dict.fromkeys(row.reference_state.value for row in rows)
        ),
        classification_lag_days=0,
        candidate_count=len(rows),
        win_rate=_rate(sum(1 for row in rows if row.profitable), len(rows)),
        average_return=_average(tuple(row.forward_return for row in rows)),
    )


def _feature_label(
    corr: Decimal | None,
    values: tuple[Decimal | None, ...],
) -> str:
    missing = _rate(sum(1 for value in values if value is None), len(values))
    if missing is not None and missing >= Decimal("0.50"):
        return "dominated by missing-data defaults"
    if corr is None:
        return "insufficient variation"
    if corr >= Decimal("0.10"):
        return "useful regime feature"
    if corr <= Decimal("-0.10"):
        return "inverted feature"
    return "non-informative feature"


def _metric(
    name: str,
    before: Decimal | None,
    after: Decimal | None,
) -> RegimeInterventionMetric:
    value_add = (
        None if before is None or after is None else (after - before).quantize(_FOUR)
    )
    if value_add is None:
        interpretation = "unavailable"
    elif value_add > _ZERO:
        interpretation = "regime intervention improved this metric"
    elif value_add < _ZERO:
        interpretation = "regime intervention degraded this metric"
    else:
        interpretation = "regime intervention made no measurable difference"
    return RegimeInterventionMetric(
        metric=name,
        before=before,
        after=after,
        value_add=value_add,
        interpretation=interpretation,
    )


def _score_getter_for_view(
    name: str,
) -> Callable[[_RegimeAuditRow], Decimal | None]:
    if name == "no regime adjustment":
        return lambda row: row.base_score
    if name == "price component only":
        return lambda row: _indicator(row.record, ("price", "price-structure"))
    if name == "NEUTRAL zero adjustment":
        return lambda row: (
            row.base_score
            if row.canonical_regime is CanonicalRegime.NEUTRAL
            else row.adjusted_score
        )
    return lambda row: row.adjusted_score


def _retracement_finding(
    corr: Decimal | None,
    group: tuple[_RegimeAuditRow, ...],
) -> RetracementRegimeFinding:
    if len(group) < 3 or corr is None:
        return RetracementRegimeFinding.INSUFFICIENT_EVIDENCE
    if corr <= Decimal("-0.20"):
        return RetracementRegimeFinding.RETRACEMENT_GLOBAL_SIGN_ERROR_SUSPECTED
    if corr <= Decimal("-0.10"):
        return RetracementRegimeFinding.RETRACEMENT_REGIME_INTERACTION
    return RetracementRegimeFinding.RETRACEMENT_GENUINELY_NEGATIVE_FEATURE


def _global_retracement_finding(
    items: tuple[RetracementRegimeInteraction, ...],
) -> RetracementRegimeFinding:
    production = tuple(item for item in items if item.dimension == "production regime")
    if not production:
        return RetracementRegimeFinding.INSUFFICIENT_EVIDENCE
    if any(
        item.finding is RetracementRegimeFinding.RETRACEMENT_GLOBAL_SIGN_ERROR_SUSPECTED
        for item in production
    ):
        return RetracementRegimeFinding.RETRACEMENT_GLOBAL_SIGN_ERROR_SUSPECTED
    if any(
        item.finding is RetracementRegimeFinding.RETRACEMENT_REGIME_INTERACTION
        for item in production
    ):
        return RetracementRegimeFinding.RETRACEMENT_REGIME_INTERACTION
    if all(
        item.finding is RetracementRegimeFinding.INSUFFICIENT_EVIDENCE
        for item in production
    ):
        return RetracementRegimeFinding.INSUFFICIENT_EVIDENCE
    return RetracementRegimeFinding.RETRACEMENT_GENUINELY_NEGATIVE_FEATURE


def _momentum_neutral_is_weak(rows: tuple[_RegimeAuditRow, ...]) -> bool:
    selected = tuple(
        row
        for row in rows
        if (row.record.setup_type or "").upper() == "MOMENTUM CONTINUATION"
        and _regime_text(row.record.market_regime) == "NEUTRAL"
    )
    if len(selected) < 30:
        return False
    win_rate = _rate(sum(1 for row in selected if row.profitable), len(selected))
    return win_rate is not None and win_rate < Decimal("0.30")


def _decision_explanation(
    primary: RegimeAuditConclusion,
    causes: tuple[NeutralConcentrationCause, ...],
    retracement: RetracementRegimeFinding,
) -> str:
    return (
        f"{primary.value}. Neutral concentration causes: "
        f"{', '.join(item.value for item in causes)}. "
        f"Retracement diagnostic: {retracement.value}."
    )


def _spearman(
    left: tuple[Decimal | None, ...],
    right: tuple[Decimal | None, ...],
) -> Decimal | None:
    pairs = tuple(
        (a, b)
        for a, b in zip(left, right, strict=False)
        if a is not None and b is not None
    )
    if len(pairs) < 3:
        return None
    return _pearson(
        _ranks(tuple(a for a, _ in pairs)), _ranks(tuple(b for _, b in pairs))
    )


def _ranks(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [Decimal("0")] * len(values)
    for rank, (_, index) in enumerate(ordered, start=1):
        ranks[index] = Decimal(rank)
    return tuple(ranks)


def _pearson(left: tuple[Decimal, ...], right: tuple[Decimal, ...]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean = sum(left, _ZERO) / Decimal(len(left))
    right_mean = sum(right, _ZERO) / Decimal(len(right))
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True)
    )
    left_var = sum(((a - left_mean) ** 2 for a in left), _ZERO)
    right_var = sum(((b - right_mean) ** 2 for b in right), _ZERO)
    if left_var == _ZERO or right_var == _ZERO:
        return None
    return (numerator / (left_var * right_var).sqrt()).quantize(_FOUR)


def _roc_auc(
    scores: tuple[Decimal | None, ...], labels: tuple[bool, ...]
) -> Decimal | None:
    pairs = tuple(
        (score, label)
        for score, label in zip(scores, labels, strict=False)
        if score is not None
    )
    positives = tuple(score for score, label in pairs if label)
    negatives = tuple(score for score, label in pairs if not label)
    if not positives or not negatives:
        return None
    wins = _ZERO
    total = Decimal(len(positives) * len(negatives))
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += _ONE
            elif positive == negative:
                wins += Decimal("0.5")
    return (wins / total).quantize(_FOUR)


def _top_win_rate(
    rows: tuple[_RegimeAuditRow, ...],
    getter: Callable[[_RegimeAuditRow], Decimal | None],
) -> Decimal | None:
    sorted_rows = tuple(
        sorted(rows, key=lambda row: getter(row) or _ZERO, reverse=True)
    )
    if not sorted_rows:
        return None
    count = max(1, int(len(sorted_rows) * 0.10))
    sample = sorted_rows[:count]
    return _rate(sum(1 for row in sample if row.profitable), len(sample))


def _buy_precision(
    rows: tuple[_RegimeAuditRow, ...],
    getter: Callable[[_RegimeAuditRow], Decimal | None],
) -> Decimal | None:
    selected = tuple(row for row in rows if (getter(row) or _ZERO) >= Decimal("75"))
    return _rate(sum(1 for row in selected if row.profitable), len(selected))


def _average(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    return (sum(present, _ZERO) / Decimal(len(present))).quantize(_FOUR)


def _median(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(sorted(value for value in values if value is not None))
    if not present:
        return None
    return Decimal(str(median(present))).quantize(_FOUR)


def _sum(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    return sum(present, _ZERO).quantize(_FOUR)


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(_FOUR)


def _inventory_lines(
    items: tuple[ProductionRegimeInventoryItem, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.source}: {item.label} -> {item.canonical.value} ({item.role})"
        for item in items[:40]
    ) or ("- unavailable",)


def _lineage_lines(items: tuple[RegimeLineageRecord, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.stage}: {item.source_module}.{item.source_function}; "
        f"fallback {item.fallback_path}"
        for item in items
    )


def _attachment_summary_lines(
    items: tuple[CandidateRegimeAttachment, ...],
) -> tuple[str, ...]:
    counts = Counter(item.join_method.value for item in items)
    if not counts:
        return ("- no candidate attachments",)
    return tuple(f"- {key}: {value}" for key, value in sorted(counts.items()))


def _distribution_lines(
    items: tuple[RegimeDistributionSummary, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.universe} | {item.regime}: count {item.candidate_count}, "
        f"share {_text(item.percentage_share)}, missing/default "
        f"{_text(item.missing_default_rate)}"
        for item in items
        if item.candidate_count
    )[:30] or ("- unavailable",)


def _transition_lines(items: tuple[RegimeTransition, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.from_regime} -> {item.to_regime}: {item.count}" for item in items
    ) or ("- no transitions detected",)


def _reference_quality_lines(item: ReferenceStateQuality) -> tuple[str, ...]:
    return (
        f"- sample count: {item.sample_count}",
        f"- balanced accuracy: {_text(item.balanced_accuracy)}",
        f"- macro precision: {_text(item.macro_precision)}",
        f"- macro recall: {_text(item.macro_recall)}",
        f"- cohen kappa: {_text(item.cohen_kappa)}",
        f"- extreme reference states labelled NEUTRAL: "
        f"{_text(item.extreme_reference_neutral_rate)}",
    )


def _reference_comparison_lines(
    items: tuple[RegimeReferenceComparison, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- production {item.production_regime} vs reference "
        f"{item.reference_state.value}: {item.count}"
        for item in items[:20]
    ) or ("- unavailable",)


def _episode_lines(items: tuple[MarketEpisode, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.label}: {item.start} to {item.end}, benchmark "
        f"{_text(item.benchmark_return)}, candidates {item.candidate_count}, "
        f"win rate {_text(item.win_rate)}"
        for item in items[:12]
    ) or ("- benchmark episode data unavailable",)


def _feature_lines(items: tuple[RegimeFeatureSeparability, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.feature}: availability {_text(item.availability)}, corr "
        f"{_text(item.correlation_with_return)}, {item.classification}"
        for item in items
    )


def _intervention_lines(items: tuple[RegimeInterventionMetric, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.metric}: before {_text(item.before)}, after {_text(item.after)}, "
        f"value-add {_text(item.value_add)} ({item.interpretation})"
        for item in items
    )


def _setup_regime_lines(items: tuple[SetupRegimeInteraction, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.setup_type} / {item.regime}: n {item.candidate_count}, win "
        f"{_text(item.win_rate)}, avg return {_text(item.average_return)}, "
        f"{item.sample_sufficiency}"
        for item in items[:30]
    ) or ("- unavailable",)


def _retracement_lines(
    items: tuple[RetracementRegimeInteraction, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.dimension} {item.key}: n {item.sample_count}, corr "
        f"{_text(item.retracement_return_correlation)}, {item.finding.value}"
        for item in items[:30]
    ) or ("- unavailable",)


def _counterfactual_lines(
    items: tuple[RegimeCounterfactualView, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.name}: n {item.sample_count}, win {_text(item.win_rate)}, "
        f"auc {_text(item.auc)}, avg return {_text(item.average_return)}"
        for item in items
    )


def _text(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _attachment_dict(item: CandidateRegimeAttachment) -> dict[str, str]:
    return {
        "candidate_id": item.candidate_id,
        "symbol": item.symbol,
        "candidate_timestamp": item.candidate_timestamp,
        "attached_regime": item.attached_regime or "",
        "canonical_regime": item.canonical_regime.value,
        "attached_regime_timestamp": item.attached_regime_timestamp or "",
        "age_days": "" if item.age_days is None else str(item.age_days),
        "join_method": item.join_method.value,
        "knowable_at_decision_time": str(item.knowable_at_decision_time),
        "issue_codes": ";".join(item.issue_codes),
    }


def _report_dict(report: MarketRegimeAuditReport) -> dict[str, object]:
    return {
        "candidate_count": report.candidate_count,
        "completed_outcome_count": report.completed_outcome_count,
        "production_inventory": [asdict(item) for item in report.production_inventory],
        "lineage": [asdict(item) for item in report.lineage],
        "attachments": [asdict(item) for item in report.attachments],
        "distributions": [asdict(item) for item in report.distributions],
        "transitions": [asdict(item) for item in report.transitions],
        "reference_comparison": [asdict(item) for item in report.reference_comparison],
        "reference_quality": asdict(report.reference_quality),
        "episodes": [asdict(item) for item in report.episodes],
        "feature_separability": [asdict(item) for item in report.feature_separability],
        "intervention_metrics": [asdict(item) for item in report.intervention_metrics],
        "setup_regime_interactions": [
            asdict(item) for item in report.setup_regime_interactions
        ],
        "retracement_interactions": [
            asdict(item) for item in report.retracement_interactions
        ],
        "counterfactuals": [asdict(item) for item in report.counterfactuals],
        "decision": asdict(report.decision),
        "policy_integrity": {
            "recommendation_scores_unchanged": report.recommendation_scores_unchanged,
            "verdicts_unchanged": report.verdicts_unchanged,
            "regime_records_unchanged": report.regime_records_unchanged,
            "timing_states_unchanged": report.timing_states_unchanged,
            "raw_approvals_unchanged": report.raw_approvals_unchanged,
            "strict_approvals_unchanged": report.strict_approvals_unchanged,
            "allocations_unchanged": report.allocations_unchanged,
        },
    }
