from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from statistics import median

from alpha.candidate_learning.approval_diagnostics import (
    ApprovalCriterionId,
    ApprovalDiagnosticsConfig,
    ApprovalDiagnosticsEngine,
    ApprovalRejectionReasonCode,
    InstitutionalApprovalDiagnostic,
)
from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_HUNDRED = Decimal("100")


class RejectedOutcomeClassification(StrEnum):
    PROFITABLE_REJECTION = "PROFITABLE_REJECTION"
    TARGET_1_REACHED_REJECTION = "TARGET_1_REACHED_REJECTION"
    TARGET_2_REACHED_REJECTION = "TARGET_2_REACHED_REJECTION"
    HIGH_MFE_REJECTION = "HIGH_MFE_REJECTION"
    POSITIVE_HORIZON_RETURN_REJECTION = "POSITIVE_HORIZON_RETURN_REJECTION"
    TRUE_NEGATIVE_REJECTION = "TRUE_NEGATIVE_REJECTION"
    INCOMPLETE_OUTCOME = "INCOMPLETE_OUTCOME"
    UNAVAILABLE_OUTCOME = "UNAVAILABLE_OUTCOME"


class EntryState(StrEnum):
    EARLY_ENTRY = "EARLY_ENTRY"
    PREFERRED_ENTRY = "PREFERRED_ENTRY"
    CONFIRMED_ENTRY = "CONFIRMED_ENTRY"
    EXTENDED_ENTRY = "EXTENDED_ENTRY"
    LATE_ENTRY = "LATE_ENTRY"
    ENTRY_UNAVAILABLE = "ENTRY_UNAVAILABLE"


class BottleneckConclusion(StrEnum):
    CANDIDATE_GENERATION_WEAK = "CANDIDATE_GENERATION_WEAK"
    ENTRY_TIMING_PRIMARY_BOTTLENECK = "ENTRY_TIMING_PRIMARY_BOTTLENECK"
    HISTORICAL_MATCHING_TOO_HETEROGENEOUS = "HISTORICAL_MATCHING_TOO_HETEROGENEOUS"
    EXPECTANCY_MODEL_MISCALIBRATED = "EXPECTANCY_MODEL_MISCALIBRATED"
    POSTERIOR_MODEL_MISCALIBRATED = "POSTERIOR_MODEL_MISCALIBRATED"
    DATA_COVERAGE_INSUFFICIENT = "DATA_COVERAGE_INSUFFICIENT"
    INSTITUTIONAL_GATES_REJECT_MANY_WINNERS = "INSTITUTIONAL_GATES_REJECT_MANY_WINNERS"
    MULTIPLE_BOTTLENECKS = "MULTIPLE_BOTTLENECKS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class ApprovalOutcomeConfig:
    primary_window: str = "20d"
    high_mfe_threshold_pct: Decimal = Decimal("10")
    minimum_bucket_sample: int = 2
    delayed_entry_window_days: int = 20
    profitable_return_threshold: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class CandidateOutcomeDiagnostic:
    symbol: str
    replay_date: date
    candidate_id: str
    setup_type: str | None
    market_regime: str | None
    sector: str | None
    verdict: str
    approved: bool
    evidence_score: Decimal
    stop_distance: Decimal | None
    matched_samples: int | None
    expectancy: Decimal | None
    posterior_probability: Decimal | None
    failed_criteria: tuple[ApprovalCriterionId, ...]
    primary_rejection_reason: ApprovalRejectionReasonCode
    secondary_rejection_reasons: tuple[ApprovalRejectionReasonCode, ...]
    entry_state: EntryState
    outcome_classification: RejectedOutcomeClassification
    completed_outcome: bool
    forward_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    target_1_hit: bool | None
    target_2_hit: bool | None
    stop_hit: bool | None
    invalidation_hit: bool | None
    holding_period_outcome: CandidateOutcomeLabel | None
    reward_risk: Decimal | None
    atr_percent: Decimal | None
    distance_from_20dma: Decimal | None
    distance_from_50dma: Decimal | None
    relative_strength: Decimal | None
    volume_confirmation: Decimal | None


@dataclass(frozen=True, slots=True)
class OutcomeStats:
    candidate_count: int
    completed_outcomes: int
    profitable_outcomes: int
    unsuccessful_outcomes: int
    profitable_rejection_rate: Decimal | None
    average_forward_return: Decimal | None
    median_forward_return: Decimal | None
    target_1_hit_rate: Decimal | None
    stop_hit_rate: Decimal | None
    average_mfe: Decimal | None
    average_mae: Decimal | None


@dataclass(frozen=True, slots=True)
class GateOutcomeStatistic:
    criterion: ApprovalCriterionId
    stats: OutcomeStats


@dataclass(frozen=True, slots=True)
class CriterionInteractionStatistic:
    criteria: tuple[ApprovalCriterionId, ...]
    stats: OutcomeStats


@dataclass(frozen=True, slots=True)
class ThresholdDistanceBucket:
    criterion: ApprovalCriterionId
    bucket: str
    stats: OutcomeStats


@dataclass(frozen=True, slots=True)
class FeatureDistributionComparison:
    feature: str
    winner_count: int
    loser_count: int
    winner_mean: Decimal | None
    loser_mean: Decimal | None
    winner_median: Decimal | None
    loser_median: Decimal | None
    winner_range: tuple[Decimal | None, Decimal | None]
    loser_range: tuple[Decimal | None, Decimal | None]
    missing_count: int


@dataclass(frozen=True, slots=True)
class EntryStateStatistic:
    entry_state: EntryState
    stats: OutcomeStats


@dataclass(frozen=True, slots=True)
class DelayedEntryOpportunity:
    symbol: str
    original_replay_date: date
    delayed_replay_date: date
    days_until_valid_entry: int
    original_stop_distance: Decimal | None
    delayed_stop_distance: Decimal | None
    original_reward_risk: Decimal | None
    delayed_reward_risk: Decimal | None
    delayed_candidate_id: str
    explanation: str


@dataclass(frozen=True, slots=True)
class HistoricalMatchHeterogeneity:
    symbol: str
    replay_date: date
    candidate_id: str
    matched_sample_count: int
    effective_homogeneous_sample_count: int
    setup_types_represented: int
    regimes_represented: int
    dominant_setup_concentration: Decimal
    dominant_regime_concentration: Decimal
    similarity_dispersion: Decimal
    warning: str | None


@dataclass(frozen=True, slots=True)
class SegmentedExpectationStatistic:
    segment: str
    key: str
    sample_count: int
    expectancy: Decimal | None
    posterior_probability: Decimal | None


@dataclass(frozen=True, slots=True)
class PosteriorCalibrationBucket:
    bucket: str
    predicted_average_probability: Decimal | None
    observed_success_rate: Decimal | None
    calibration_error: Decimal | None
    sample_count: int
    completed_outcomes: int
    brier_score: Decimal | None


@dataclass(frozen=True, slots=True)
class BottleneckDecision:
    conclusion: BottleneckConclusion
    supporting_metrics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApprovalOutcomeReport:
    candidate_outcomes: tuple[CandidateOutcomeDiagnostic, ...]
    profitable_rejections: tuple[CandidateOutcomeDiagnostic, ...]
    true_negative_rejections: tuple[CandidateOutcomeDiagnostic, ...]
    gate_statistics: tuple[GateOutcomeStatistic, ...]
    interaction_statistics: tuple[CriterionInteractionStatistic, ...]
    threshold_buckets: tuple[ThresholdDistanceBucket, ...]
    feature_comparisons: tuple[FeatureDistributionComparison, ...]
    entry_state_statistics: tuple[EntryStateStatistic, ...]
    delayed_entry_opportunities: tuple[DelayedEntryOpportunity, ...]
    heterogeneity: tuple[HistoricalMatchHeterogeneity, ...]
    segmented_expectancy: tuple[SegmentedExpectationStatistic, ...]
    posterior_calibration: tuple[PosteriorCalibrationBucket, ...]
    bottleneck_decision: BottleneckDecision
    candidates_evaluated: int
    completed_outcomes: int
    profitable_rejected_count: int
    true_negative_rejected_count: int
    profitable_rejection_rate: Decimal | None


class ApprovalOutcomeAnalysisEngine:
    def __init__(self, config: ApprovalOutcomeConfig | None = None) -> None:
        self.config = config or ApprovalOutcomeConfig()

    def analyze(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> ApprovalOutcomeReport:
        approval_summary = ApprovalDiagnosticsEngine(
            ApprovalDiagnosticsConfig(minimum_intersection_count=1)
        ).build(records=records, outcomes=outcomes)
        records_by_id = {record.candidate_id: record for record in records}
        outcomes_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
        diagnostics = tuple(
            self._candidate_outcome(
                record=records_by_id[item.candidate_id],
                diagnostic=item,
                outcome=outcomes_by_id.get(item.candidate_id),
            )
            for item in approval_summary.diagnostics
            if item.candidate_id in records_by_id
        )
        profitable = tuple(
            item
            for item in diagnostics
            if not item.approved
            and item.outcome_classification
            in {
                RejectedOutcomeClassification.PROFITABLE_REJECTION,
                RejectedOutcomeClassification.TARGET_1_REACHED_REJECTION,
                RejectedOutcomeClassification.TARGET_2_REACHED_REJECTION,
                RejectedOutcomeClassification.HIGH_MFE_REJECTION,
                RejectedOutcomeClassification.POSITIVE_HORIZON_RETURN_REJECTION,
            }
        )
        true_negative = tuple(
            item
            for item in diagnostics
            if not item.approved
            and item.outcome_classification
            is RejectedOutcomeClassification.TRUE_NEGATIVE_REJECTION
        )
        completed = tuple(item for item in diagnostics if item.completed_outcome)
        return ApprovalOutcomeReport(
            candidate_outcomes=diagnostics,
            profitable_rejections=tuple(sorted(profitable, key=_candidate_sort_key)),
            true_negative_rejections=tuple(
                sorted(true_negative, key=_candidate_sort_key)
            ),
            gate_statistics=_gate_statistics(diagnostics),
            interaction_statistics=_interaction_statistics(
                diagnostics,
                minimum_sample=self.config.minimum_bucket_sample,
            ),
            threshold_buckets=_threshold_buckets(diagnostics),
            feature_comparisons=_feature_comparisons(diagnostics),
            entry_state_statistics=_entry_state_statistics(diagnostics),
            delayed_entry_opportunities=_delayed_entry_opportunities(diagnostics),
            heterogeneity=_heterogeneity(records, diagnostics),
            segmented_expectancy=_segmented_expectancy(diagnostics),
            posterior_calibration=_posterior_calibration(diagnostics),
            bottleneck_decision=_bottleneck_decision(diagnostics),
            candidates_evaluated=len(diagnostics),
            completed_outcomes=len(completed),
            profitable_rejected_count=len(profitable),
            true_negative_rejected_count=len(true_negative),
            profitable_rejection_rate=_rate(len(profitable), len(completed)),
        )

    def _candidate_outcome(
        self,
        *,
        record: CandidateDecisionRecord,
        diagnostic: InstitutionalApprovalDiagnostic,
        outcome: CandidateForwardOutcome | None,
    ) -> CandidateOutcomeDiagnostic:
        window = _primary_window(outcome, self.config.primary_window)
        completed = _is_completed(window)
        target_2_hit = _target_2_hit(record, window)
        classification = _classification(
            diagnostic=diagnostic,
            window=window,
            target_2_hit=target_2_hit,
            high_mfe_threshold=self.config.high_mfe_threshold_pct,
            profitable_return_threshold=self.config.profitable_return_threshold,
        )
        return CandidateOutcomeDiagnostic(
            symbol=record.symbol,
            replay_date=record.evaluation_date,
            candidate_id=record.candidate_id,
            setup_type=record.setup_type,
            market_regime=record.market_regime,
            sector=record.sector,
            verdict=record.final_verdict,
            approved=diagnostic.approved,
            evidence_score=record.strategy_score,
            stop_distance=diagnostic.stop_distance_percent,
            matched_samples=diagnostic.matched_samples,
            expectancy=diagnostic.expectancy,
            posterior_probability=diagnostic.posterior_probability,
            failed_criteria=diagnostic.failed_criteria,
            primary_rejection_reason=diagnostic.primary_rejection_reason,
            secondary_rejection_reasons=diagnostic.secondary_rejection_reasons,
            entry_state=_entry_state(record, diagnostic.stop_distance_percent),
            outcome_classification=classification,
            completed_outcome=completed,
            forward_return=window.forward_return_pct_from_entry if window else None,
            mfe=window.max_favourable_excursion_pct if window else None,
            mae=window.max_adverse_excursion_pct if window else None,
            target_1_hit=window.target_1_touched if window else None,
            target_2_hit=target_2_hit,
            stop_hit=window.risk_stop_touched if window else None,
            invalidation_hit=None,
            holding_period_outcome=window.outcome_label if window else None,
            reward_risk=_reward_risk(record),
            atr_percent=_indicator_decimal(record, ("atr-percent", "atr_pct")),
            distance_from_20dma=_indicator_decimal(
                record,
                ("distance-from-20dma", "distance_20dma", "20dma-distance"),
            ),
            distance_from_50dma=_indicator_decimal(
                record,
                ("distance-from-50dma", "distance_50dma", "50dma-distance"),
            ),
            relative_strength=_indicator_decimal(
                record,
                ("relative-strength", "relative_strength", "rs"),
            ),
            volume_confirmation=_indicator_decimal(
                record,
                ("volume-confirmation", "volume_confirmation", "volume"),
            ),
        )


def filter_profitable_rejections(
    candidates: tuple[CandidateOutcomeDiagnostic, ...],
    *,
    criterion: str | None = None,
    reason: str | None = None,
    setup_type: str | None = None,
    market_regime: str | None = None,
    entry_state: str | None = None,
    symbol: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    target_1_hit: bool | None = None,
    target_2_hit: bool | None = None,
    minimum_return: Decimal | None = None,
    minimum_mfe: Decimal | None = None,
) -> tuple[CandidateOutcomeDiagnostic, ...]:
    result = candidates
    if criterion:
        result = tuple(
            item
            for item in result
            if criterion in {failed.value for failed in item.failed_criteria}
        )
    if reason:
        result = tuple(
            item for item in result if item.primary_rejection_reason.value == reason
        )
    if setup_type:
        result = tuple(item for item in result if item.setup_type == setup_type)
    if market_regime:
        result = tuple(item for item in result if item.market_regime == market_regime)
    if entry_state:
        result = tuple(item for item in result if item.entry_state.value == entry_state)
    if symbol:
        normalized = symbol.strip().upper()
        result = tuple(item for item in result if item.symbol == normalized)
    if from_date:
        result = tuple(item for item in result if item.replay_date >= from_date)
    if to_date:
        result = tuple(item for item in result if item.replay_date <= to_date)
    if target_1_hit is not None:
        result = tuple(item for item in result if item.target_1_hit is target_1_hit)
    if target_2_hit is not None:
        result = tuple(item for item in result if item.target_2_hit is target_2_hit)
    if minimum_return is not None:
        result = tuple(
            item
            for item in result
            if item.forward_return is not None and item.forward_return >= minimum_return
        )
    if minimum_mfe is not None:
        result = tuple(
            item for item in result if item.mfe is not None and item.mfe >= minimum_mfe
        )
    return tuple(sorted(result, key=_candidate_sort_key))


def group_approval_outcomes(
    report: ApprovalOutcomeReport,
    *,
    group_by: str,
) -> tuple[str, ...]:
    counters: Counter[str] = Counter()
    for item in report.candidate_outcomes:
        if group_by == "criterion":
            for criterion in item.failed_criteria:
                counters[criterion.value] += 1
        elif group_by == "threshold-distance":
            for bucket in _candidate_threshold_buckets(item):
                counters[f"{bucket[0].value}: {bucket[1]}"] += 1
        elif group_by == "rejection-reason":
            counters[item.primary_rejection_reason.value] += 1
        elif group_by == "setup-type":
            counters[item.setup_type or "UNKNOWN"] += 1
        elif group_by == "market-regime":
            counters[item.market_regime or "UNKNOWN"] += 1
        elif group_by == "sector":
            counters[item.sector or "UNKNOWN"] += 1
        elif group_by == "entry-state":
            counters[item.entry_state.value] += 1
        elif group_by == "evidence-score":
            counters[_numeric_band(item.evidence_score, (70, 80, 85, 90))] += 1
        elif group_by == "expectancy":
            counters[_optional_band(item.expectancy, (0, 5, 10))] += 1
        elif group_by == "posterior":
            counters[_optional_band(item.posterior_probability, (30, 40, 50, 60))] += 1
        elif group_by == "stop-distance":
            counters[_optional_band(item.stop_distance, (5, 10, 15, 20))] += 1
        elif group_by == "historical-sample-count":
            value = Decimal(item.matched_samples or 0)
            counters[_numeric_band(value, (10, 30, 60, 100))] += 1
        else:
            raise ValueError(f"Unsupported grouping: {group_by}")
    return tuple(f"- {key}: {value}" for key, value in sorted(counters.items()))


def render_approval_outcomes(report: ApprovalOutcomeReport) -> tuple[str, ...]:
    decision = report.bottleneck_decision
    lines = [
        "Outcome-Conditioned Approval Bottleneck Analysis",
        f"Candidates Evaluated: {report.candidates_evaluated}",
        f"Completed Outcomes: {report.completed_outcomes}",
        f"Profitable Rejected Candidates: {report.profitable_rejected_count}",
        f"True Negative Rejections: {report.true_negative_rejected_count}",
        f"Profitable-Rejection Rate: {_metric_pct(report.profitable_rejection_rate)}",
        "",
        "Top Gates Rejecting Profitable Candidates:",
        *_gate_lines(report.gate_statistics),
        "",
        "Threshold Distance Analysis:",
        *_threshold_lines(report.threshold_buckets),
        "",
        "Winner Versus Loser Feature Differences:",
        *_feature_lines(report.feature_comparisons),
        "",
        "Entry Quality Summary:",
        *_entry_lines(report.entry_state_statistics),
        "",
        "Posterior Calibration Summary:",
        *_calibration_lines(report.posterior_calibration),
        "",
        "Evidence Heterogeneity Warnings:",
        *_heterogeneity_lines(report.heterogeneity),
        "",
        f"Primary Bottleneck: {decision.conclusion.value}",
        "Evidence:",
        *[f"- {metric}" for metric in decision.supporting_metrics],
        "",
        "Policy Integrity: diagnostics used forward outcomes only after the replay "
        "decision and did not alter approval thresholds.",
    ]
    return tuple(lines)


def render_profitable_rejections(
    candidates: tuple[CandidateOutcomeDiagnostic, ...],
) -> tuple[str, ...]:
    lines = ["Profitable Rejected Candidates"]
    if not candidates:
        return tuple([*lines, "- none"])
    for item in candidates:
        matched_samples = (
            str(item.matched_samples)
            if item.matched_samples is not None
            else "unavailable"
        )
        lines.append(
            f"- {item.symbol} {item.replay_date}: {item.outcome_classification.value}; "
            f"return {_metric(item.forward_return)}, MFE {_metric(item.mfe)}, "
            f"MAE {_metric(item.mae)}, failed "
            f"{', '.join(criterion.value for criterion in item.failed_criteria)}"
        )
        lines.append(
            f"  setup {item.setup_type or 'UNKNOWN'}, regime "
            f"{item.market_regime or 'UNKNOWN'}, score {item.evidence_score}, "
            f"stop {_metric(item.stop_distance)}, samples {matched_samples}, "
            f"expectancy {_metric(item.expectancy)}, posterior "
            f"{_metric(item.posterior_probability)}"
        )
    return tuple(lines)


def render_entry_opportunities(
    opportunities: tuple[DelayedEntryOpportunity, ...],
) -> tuple[str, ...]:
    lines = ["Delayed Entry Opportunities"]
    if not opportunities:
        return tuple([*lines, "- none"])
    for item in opportunities:
        lines.append(
            f"- {item.symbol}: original {item.original_replay_date}, delayed "
            f"{item.delayed_replay_date} after {item.days_until_valid_entry} days; "
            f"stop {_metric(item.original_stop_distance)} -> "
            f"{_metric(item.delayed_stop_distance)}, RR "
            f"{_metric(item.original_reward_risk)} -> "
            f"{_metric(item.delayed_reward_risk)}"
        )
        lines.append(f"  {item.explanation}")
    return tuple(lines)


def export_approval_outcomes_json(report: ApprovalOutcomeReport, path: Path) -> None:
    path.write_text(json.dumps(_report_dict(report), indent=2) + "\n", encoding="utf-8")


def export_approval_outcomes_csv(report: ApprovalOutcomeReport, path: Path) -> None:
    _write_csv(tuple(_candidate_dict(item) for item in report.candidate_outcomes), path)


def export_profitable_rejections_json(
    candidates: tuple[CandidateOutcomeDiagnostic, ...],
    path: Path,
) -> None:
    path.write_text(
        json.dumps([_candidate_dict(item) for item in candidates], indent=2) + "\n",
        encoding="utf-8",
    )


def export_profitable_rejections_csv(
    candidates: tuple[CandidateOutcomeDiagnostic, ...],
    path: Path,
) -> None:
    _write_csv(tuple(_candidate_dict(item) for item in candidates), path)


def export_entry_opportunities_json(
    opportunities: tuple[DelayedEntryOpportunity, ...],
    path: Path,
) -> None:
    path.write_text(
        json.dumps([_delayed_dict(item) for item in opportunities], indent=2) + "\n",
        encoding="utf-8",
    )


def export_entry_opportunities_csv(
    opportunities: tuple[DelayedEntryOpportunity, ...],
    path: Path,
) -> None:
    _write_csv(tuple(_delayed_dict(item) for item in opportunities), path)


def _classification(
    *,
    diagnostic: InstitutionalApprovalDiagnostic,
    window: CandidateForwardWindowOutcome | None,
    target_2_hit: bool | None,
    high_mfe_threshold: Decimal,
    profitable_return_threshold: Decimal,
) -> RejectedOutcomeClassification:
    if window is None:
        return RejectedOutcomeClassification.UNAVAILABLE_OUTCOME
    if window.outcome_label is CandidateOutcomeLabel.DATA_MISSING:
        return RejectedOutcomeClassification.UNAVAILABLE_OUTCOME
    if window.forward_return_pct_from_entry is None:
        return RejectedOutcomeClassification.INCOMPLETE_OUTCOME
    if diagnostic.approved:
        return (
            RejectedOutcomeClassification.PROFITABLE_REJECTION
            if window.forward_return_pct_from_entry > profitable_return_threshold
            else RejectedOutcomeClassification.TRUE_NEGATIVE_REJECTION
        )
    if target_2_hit:
        return RejectedOutcomeClassification.TARGET_2_REACHED_REJECTION
    if window.target_1_touched:
        return RejectedOutcomeClassification.TARGET_1_REACHED_REJECTION
    if (
        window.max_favourable_excursion_pct is not None
        and window.max_favourable_excursion_pct >= high_mfe_threshold
    ):
        return RejectedOutcomeClassification.HIGH_MFE_REJECTION
    if window.forward_return_pct_from_entry > profitable_return_threshold:
        return RejectedOutcomeClassification.POSITIVE_HORIZON_RETURN_REJECTION
    return RejectedOutcomeClassification.TRUE_NEGATIVE_REJECTION


def _gate_statistics(
    diagnostics: tuple[CandidateOutcomeDiagnostic, ...],
) -> tuple[GateOutcomeStatistic, ...]:
    rows = []
    for criterion in ApprovalCriterionId:
        failed = tuple(
            item for item in diagnostics if criterion in item.failed_criteria
        )
        if failed:
            rows.append(GateOutcomeStatistic(criterion, _stats(failed)))
    return tuple(sorted(rows, key=lambda item: item.criterion.value))


def _interaction_statistics(
    diagnostics: tuple[CandidateOutcomeDiagnostic, ...],
    *,
    minimum_sample: int,
) -> tuple[CriterionInteractionStatistic, ...]:
    required = (
        (ApprovalCriterionId.EVIDENCE_SCORE, ApprovalCriterionId.EXPECTANCY),
        (
            ApprovalCriterionId.EVIDENCE_SCORE,
            ApprovalCriterionId.POSTERIOR_PROBABILITY,
        ),
        (ApprovalCriterionId.EXPECTANCY, ApprovalCriterionId.POSTERIOR_PROBABILITY),
        (ApprovalCriterionId.STOP_DISTANCE, ApprovalCriterionId.EVIDENCE_SCORE),
        (ApprovalCriterionId.STOP_DISTANCE, ApprovalCriterionId.EXPECTANCY),
        (ApprovalCriterionId.HISTORICAL_SAMPLES, ApprovalCriterionId.EXPECTANCY),
        (
            ApprovalCriterionId.HISTORICAL_SAMPLES,
            ApprovalCriterionId.POSTERIOR_PROBABILITY,
        ),
        (
            ApprovalCriterionId.TARGETS_AVAILABLE,
            ApprovalCriterionId.INSTITUTIONAL_ACCEPTANCE,
        ),
    )
    rows = []
    for pair in required:
        items = tuple(
            item
            for item in diagnostics
            if all(criterion in item.failed_criteria for criterion in pair)
        )
        if len(items) >= minimum_sample:
            rows.append(CriterionInteractionStatistic(pair, _stats(items)))
    return tuple(rows)


def _threshold_buckets(
    diagnostics: tuple[CandidateOutcomeDiagnostic, ...],
) -> tuple[ThresholdDistanceBucket, ...]:
    grouped: dict[tuple[ApprovalCriterionId, str], list[CandidateOutcomeDiagnostic]] = (
        defaultdict(list)
    )
    for item in diagnostics:
        for criterion, bucket in _candidate_threshold_buckets(item):
            grouped[(criterion, bucket)].append(item)
    return tuple(
        ThresholdDistanceBucket(criterion, bucket, _stats(tuple(items)))
        for (criterion, bucket), items in sorted(
            grouped.items(),
            key=lambda entry: (entry[0][0].value, entry[0][1]),
        )
    )


def _candidate_threshold_buckets(
    item: CandidateOutcomeDiagnostic,
) -> tuple[tuple[ApprovalCriterionId, str], ...]:
    rows: list[tuple[ApprovalCriterionId, str]] = []
    if ApprovalCriterionId.EVIDENCE_SCORE in item.failed_criteria:
        rows.append(
            (
                ApprovalCriterionId.EVIDENCE_SCORE,
                _distance_bucket(
                    Decimal("85") - item.evidence_score,
                    ("within 2 points", Decimal("2")),
                    ("2.01-5 points", Decimal("5")),
                    ("5.01-10 points", Decimal("10")),
                    default="more than 10 points",
                ),
            )
        )
    if (
        ApprovalCriterionId.STOP_DISTANCE in item.failed_criteria
        and item.stop_distance is not None
    ):
        rows.append(
            (
                ApprovalCriterionId.STOP_DISTANCE,
                _distance_bucket(
                    item.stop_distance - Decimal("10"),
                    ("within 1 percentage point", Decimal("1")),
                    ("1.01-2 percentage points", Decimal("2")),
                    ("2.01-5 percentage points", Decimal("5")),
                    default="more than 5 percentage points",
                ),
            )
        )
    if (
        ApprovalCriterionId.HISTORICAL_SAMPLES in item.failed_criteria
        and item.matched_samples is not None
    ):
        rows.append(
            (
                ApprovalCriterionId.HISTORICAL_SAMPLES,
                _distance_bucket(
                    Decimal(60 - item.matched_samples),
                    ("short by 1-10", Decimal("10")),
                    ("short by 11-25", Decimal("25")),
                    ("short by 26-50", Decimal("50")),
                    default="short by more than 50",
                ),
            )
        )
    if (
        ApprovalCriterionId.EXPECTANCY in item.failed_criteria
        and item.expectancy is not None
    ):
        rows.append(
            (
                ApprovalCriterionId.EXPECTANCY,
                _distance_bucket(
                    Decimal("0.10") - item.expectancy,
                    ("within 0.02", Decimal("0.02")),
                    ("0.021-0.05", Decimal("0.05")),
                    ("0.051-0.10", Decimal("0.10")),
                    default="more than 0.10 below requirement",
                ),
            )
        )
    if (
        ApprovalCriterionId.POSTERIOR_PROBABILITY in item.failed_criteria
        and item.posterior_probability is not None
    ):
        rows.append(
            (
                ApprovalCriterionId.POSTERIOR_PROBABILITY,
                _distance_bucket(
                    Decimal("0.52") - item.posterior_probability,
                    ("within 2 percentage points", Decimal("0.02")),
                    ("2.01-5 percentage points", Decimal("0.05")),
                    ("5.01-10 percentage points", Decimal("0.10")),
                    default="more than 10 percentage points",
                ),
            )
        )
    return tuple(rows)


def _feature_comparisons(
    diagnostics: tuple[CandidateOutcomeDiagnostic, ...],
) -> tuple[FeatureDistributionComparison, ...]:
    features = (
        ("evidence_score", lambda item: item.evidence_score),
        ("matched_samples", lambda item: _decimal_or_none(item.matched_samples)),
        ("historical_expectancy", lambda item: item.expectancy),
        ("posterior_probability", lambda item: item.posterior_probability),
        ("stop_distance", lambda item: item.stop_distance),
        ("reward_risk", lambda item: item.reward_risk),
        ("atr_percent", lambda item: item.atr_percent),
        ("distance_from_20dma", lambda item: item.distance_from_20dma),
        ("distance_from_50dma", lambda item: item.distance_from_50dma),
        ("relative_strength", lambda item: item.relative_strength),
        ("volume_confirmation", lambda item: item.volume_confirmation),
    )
    rows = []
    for name, getter in features:
        winner_values: list[Decimal] = []
        loser_values: list[Decimal] = []
        missing = 0
        for item in diagnostics:
            if not item.completed_outcome:
                continue
            value = getter(item)
            if value is None:
                missing += 1
            elif _is_profitable(item):
                winner_values.append(value)
            else:
                loser_values.append(value)
        rows.append(
            FeatureDistributionComparison(
                feature=name,
                winner_count=len(winner_values),
                loser_count=len(loser_values),
                winner_mean=_average(tuple(winner_values)),
                loser_mean=_average(tuple(loser_values)),
                winner_median=_median(tuple(winner_values)),
                loser_median=_median(tuple(loser_values)),
                winner_range=_range(tuple(winner_values)),
                loser_range=_range(tuple(loser_values)),
                missing_count=missing,
            )
        )
    return tuple(rows)


def _entry_state_statistics(
    diagnostics: tuple[CandidateOutcomeDiagnostic, ...],
) -> tuple[EntryStateStatistic, ...]:
    return tuple(
        EntryStateStatistic(state, _stats(tuple(_by_entry_state(diagnostics, state))))
        for state in EntryState
        if tuple(_by_entry_state(diagnostics, state))
    )


def _delayed_entry_opportunities(
    diagnostics: tuple[CandidateOutcomeDiagnostic, ...],
) -> tuple[DelayedEntryOpportunity, ...]:
    by_symbol: dict[str, list[CandidateOutcomeDiagnostic]] = defaultdict(list)
    for item in diagnostics:
        by_symbol[item.symbol].append(item)
    opportunities: list[DelayedEntryOpportunity] = []
    for symbol, items in by_symbol.items():
        ordered = sorted(items, key=lambda item: item.replay_date)
        for original in ordered:
            if original.approved:
                continue
            if not (
                ApprovalCriterionId.STOP_DISTANCE in original.failed_criteria
                or (original.reward_risk is not None and original.reward_risk < 2)
            ):
                continue
            later = next(
                (
                    item
                    for item in ordered
                    if item.replay_date > original.replay_date
                    and item.approved
                    and item.entry_state
                    in {EntryState.PREFERRED_ENTRY, EntryState.CONFIRMED_ENTRY}
                ),
                None,
            )
            if later is None:
                continue
            opportunities.append(
                DelayedEntryOpportunity(
                    symbol=symbol,
                    original_replay_date=original.replay_date,
                    delayed_replay_date=later.replay_date,
                    days_until_valid_entry=(
                        later.replay_date - original.replay_date
                    ).days,
                    original_stop_distance=original.stop_distance,
                    delayed_stop_distance=later.stop_distance,
                    original_reward_risk=original.reward_risk,
                    delayed_reward_risk=later.reward_risk,
                    delayed_candidate_id=later.candidate_id,
                    explanation=(
                        "Forward diagnostic only: later replay produced an "
                        "independent approved entry."
                    ),
                )
            )
    return tuple(
        sorted(
            opportunities,
            key=lambda item: (item.original_replay_date, item.symbol),
        )
    )


def _heterogeneity(
    records: tuple[CandidateDecisionRecord, ...],
    diagnostics: tuple[CandidateOutcomeDiagnostic, ...],
) -> tuple[HistoricalMatchHeterogeneity, ...]:
    diag_by_id = {item.candidate_id: item for item in diagnostics}
    rows: list[HistoricalMatchHeterogeneity] = []
    for record in records:
        diag = diag_by_id.get(record.candidate_id)
        if diag is None:
            continue
        comparable = tuple(
            item
            for item in records
            if item.setup_type == record.setup_type
            or item.market_regime == record.market_regime
        )
        setups = Counter(item.setup_type or "UNKNOWN" for item in comparable)
        regimes = Counter(item.market_regime or "UNKNOWN" for item in comparable)
        count = len(comparable)
        dominant_setup = max(setups.values()) if setups else 0
        dominant_regime = max(regimes.values()) if regimes else 0
        setup_concentration = _rate_decimal(dominant_setup, count)
        regime_concentration = _rate_decimal(dominant_regime, count)
        effective = min(dominant_setup, dominant_regime)
        dispersion = _ONE - min(setup_concentration, regime_concentration)
        warning = (
            "Matched pool is heterogeneous; segment historical edge more tightly."
            if count >= 30 and dispersion > Decimal("0.40")
            else None
        )
        rows.append(
            HistoricalMatchHeterogeneity(
                symbol=record.symbol,
                replay_date=record.evaluation_date,
                candidate_id=record.candidate_id,
                matched_sample_count=count,
                effective_homogeneous_sample_count=effective,
                setup_types_represented=len(setups),
                regimes_represented=len(regimes),
                dominant_setup_concentration=setup_concentration,
                dominant_regime_concentration=regime_concentration,
                similarity_dispersion=dispersion.quantize(_FOUR),
                warning=warning,
            )
        )
    return tuple(sorted(rows, key=lambda item: (item.replay_date, item.symbol)))


def _segmented_expectancy(
    diagnostics: tuple[CandidateOutcomeDiagnostic, ...],
) -> tuple[SegmentedExpectationStatistic, ...]:
    segments = (
        ("global", _global_segment_key),
        ("setup", _setup_segment_key),
        ("setup+regime", _setup_regime_segment_key),
        ("setup+regime+sector", _setup_regime_sector_segment_key),
        ("setup+regime+entry", _setup_regime_entry_segment_key),
    )
    rows: list[SegmentedExpectationStatistic] = []
    for segment, key_fn in segments:
        grouped: dict[str, list[CandidateOutcomeDiagnostic]] = defaultdict(list)
        for item in diagnostics:
            if item.completed_outcome:
                grouped[key_fn(item)].append(item)
        for key, items in grouped.items():
            returns = tuple(
                item.forward_return for item in items if item.forward_return is not None
            )
            wins = sum(1 for item in items if _is_profitable(item))
            rows.append(
                SegmentedExpectationStatistic(
                    segment=segment,
                    key=key,
                    sample_count=len(items),
                    expectancy=_average(returns),
                    posterior_probability=_rate(wins, len(items)),
                )
            )
    return tuple(sorted(rows, key=lambda item: (item.segment, item.key)))


def _global_segment_key(item: CandidateOutcomeDiagnostic) -> str:
    del item
    return "ALL"


def _setup_segment_key(item: CandidateOutcomeDiagnostic) -> str:
    return item.setup_type or "UNKNOWN"


def _setup_regime_segment_key(item: CandidateOutcomeDiagnostic) -> str:
    return f"{item.setup_type or 'UNKNOWN'}|{item.market_regime or 'UNKNOWN'}"


def _setup_regime_sector_segment_key(item: CandidateOutcomeDiagnostic) -> str:
    return (
        f"{item.setup_type or 'UNKNOWN'}|{item.market_regime or 'UNKNOWN'}|"
        f"{item.sector or 'UNKNOWN'}"
    )


def _setup_regime_entry_segment_key(item: CandidateOutcomeDiagnostic) -> str:
    return (
        f"{item.setup_type or 'UNKNOWN'}|{item.market_regime or 'UNKNOWN'}|"
        f"{item.entry_state.value}"
    )


def _posterior_calibration(
    diagnostics: tuple[CandidateOutcomeDiagnostic, ...],
) -> tuple[PosteriorCalibrationBucket, ...]:
    buckets = (
        ("below 30%", None, Decimal("0.30")),
        ("30-39.99%", Decimal("0.30"), Decimal("0.40")),
        ("40-49.99%", Decimal("0.40"), Decimal("0.50")),
        ("50-59.99%", Decimal("0.50"), Decimal("0.60")),
        ("60-69.99%", Decimal("0.60"), Decimal("0.70")),
        ("70% and above", Decimal("0.70"), None),
    )
    rows = []
    for label, low, high in buckets:
        items = tuple(
            item
            for item in diagnostics
            if item.completed_outcome
            and item.posterior_probability is not None
            and (low is None or item.posterior_probability >= low)
            and (high is None or item.posterior_probability < high)
        )
        predictions = tuple(
            item.posterior_probability
            for item in items
            if item.posterior_probability is not None
        )
        observed = _rate(sum(1 for item in items if _is_profitable(item)), len(items))
        predicted = _average(predictions)
        rows.append(
            PosteriorCalibrationBucket(
                bucket=label,
                predicted_average_probability=predicted,
                observed_success_rate=observed,
                calibration_error=_abs_diff(predicted, observed),
                sample_count=len(items),
                completed_outcomes=len(items),
                brier_score=_brier_score(items),
            )
        )
    return tuple(rows)


def _bottleneck_decision(
    diagnostics: tuple[CandidateOutcomeDiagnostic, ...],
) -> BottleneckDecision:
    completed = tuple(item for item in diagnostics if item.completed_outcome)
    if len(completed) < 30:
        return BottleneckDecision(
            BottleneckConclusion.INSUFFICIENT_EVIDENCE,
            (f"Only {len(completed)} completed outcomes are available.",),
        )
    profitable_rejected = tuple(
        item for item in completed if not item.approved and _is_profitable(item)
    )
    stop_failures = tuple(
        item
        for item in completed
        if ApprovalCriterionId.STOP_DISTANCE in item.failed_criteria
    )
    hetero_rate = _rate(
        sum(
            1
            for item in completed
            if item.matched_samples is not None
            and item.matched_samples >= 60
            and item.expectancy is not None
            and item.posterior_probability is not None
        ),
        len(completed),
    )
    profitable_rejection_rate = _rate(len(profitable_rejected), len(completed))
    stop_failure_rate = _rate(len(stop_failures), len(completed))
    posterior_error = _average(
        tuple(
            bucket.calibration_error
            for bucket in _posterior_calibration(completed)
            if bucket.calibration_error is not None and bucket.completed_outcomes > 0
        )
    )
    metrics = (
        f"{_metric_pct(profitable_rejection_rate)} of completed candidates were "
        "profitable rejections.",
        f"{_metric_pct(stop_failure_rate)} of completed candidates failed "
        "stop distance.",
        f"Average posterior calibration error is {_metric(posterior_error)}.",
        f"{_metric_pct(hetero_rate)} of completed candidates had populated historical "
        "sample, expectancy, and posterior fields.",
    )
    flags = [
        profitable_rejection_rate is not None
        and profitable_rejection_rate >= Decimal("0.25"),
        stop_failure_rate is not None and stop_failure_rate >= Decimal("0.35"),
        posterior_error is not None and posterior_error >= Decimal("0.15"),
    ]
    if sum(1 for flag in flags if flag) >= 2:
        conclusion = BottleneckConclusion.MULTIPLE_BOTTLENECKS
    elif flags[1]:
        conclusion = BottleneckConclusion.ENTRY_TIMING_PRIMARY_BOTTLENECK
    elif flags[2]:
        conclusion = BottleneckConclusion.POSTERIOR_MODEL_MISCALIBRATED
    elif flags[0]:
        conclusion = BottleneckConclusion.INSTITUTIONAL_GATES_REJECT_MANY_WINNERS
    else:
        conclusion = BottleneckConclusion.CANDIDATE_GENERATION_WEAK
    return BottleneckDecision(conclusion, metrics)


def _stats(items: tuple[CandidateOutcomeDiagnostic, ...]) -> OutcomeStats:
    completed = tuple(item for item in items if item.completed_outcome)
    profitable = tuple(item for item in completed if _is_profitable(item))
    returns = tuple(
        item.forward_return for item in completed if item.forward_return is not None
    )
    mfes = tuple(item.mfe for item in completed if item.mfe is not None)
    maes = tuple(item.mae for item in completed if item.mae is not None)
    return OutcomeStats(
        candidate_count=len(items),
        completed_outcomes=len(completed),
        profitable_outcomes=len(profitable),
        unsuccessful_outcomes=len(completed) - len(profitable),
        profitable_rejection_rate=_rate(len(profitable), len(completed)),
        average_forward_return=_average(returns),
        median_forward_return=_median(returns),
        target_1_hit_rate=_rate(
            sum(1 for item in completed if item.target_1_hit),
            len(completed),
        ),
        stop_hit_rate=_rate(
            sum(1 for item in completed if item.stop_hit),
            len(completed),
        ),
        average_mfe=_average(mfes),
        average_mae=_average(maes),
    )


def _primary_window(
    outcome: CandidateForwardOutcome | None,
    preferred: str,
) -> CandidateForwardWindowOutcome | None:
    if outcome is None:
        return None
    by_window = {window.window: window for window in outcome.windows}
    if preferred in by_window:
        return by_window[preferred]
    return next(
        (
            by_window[label]
            for label in ("20d", "10d", "5d", "3d", "1d", "60d")
            if label in by_window
        ),
        outcome.windows[0] if outcome.windows else None,
    )


def _is_completed(window: CandidateForwardWindowOutcome | None) -> bool:
    return (
        window is not None
        and window.outcome_label is not CandidateOutcomeLabel.DATA_MISSING
        and window.forward_return_pct_from_entry is not None
    )


def _is_profitable(item: CandidateOutcomeDiagnostic) -> bool:
    return item.forward_return is not None and item.forward_return > _ZERO


def _target_2_hit(
    record: CandidateDecisionRecord,
    window: CandidateForwardWindowOutcome | None,
) -> bool | None:
    if window is None or record.target_2 is None or window.forward_high is None:
        return None
    return window.forward_high >= record.target_2


def _entry_state(
    record: CandidateDecisionRecord,
    stop_distance: Decimal | None,
) -> EntryState:
    if record.entry_zone_low is None or record.entry_zone_high is None:
        return EntryState.ENTRY_UNAVAILABLE
    if record.confirmation_entry is None:
        return EntryState.PREFERRED_ENTRY
    if record.entry_zone_low <= record.confirmation_entry <= record.entry_zone_high:
        return EntryState.PREFERRED_ENTRY
    if record.confirmation_entry > record.entry_zone_high:
        if stop_distance is not None and stop_distance > Decimal("15"):
            return EntryState.LATE_ENTRY
        return EntryState.CONFIRMED_ENTRY
    return EntryState.EARLY_ENTRY


def _reward_risk(record: CandidateDecisionRecord) -> Decimal | None:
    entry = record.confirmation_entry or record.entry_zone_high
    stop = record.risk_stop
    target = record.target_2 or record.target_1
    if entry is None or stop is None or target is None or entry <= stop:
        return None
    return ((target - entry) / (entry - stop)).quantize(_TWO)


def _indicator_decimal(
    record: CandidateDecisionRecord,
    keys: tuple[str, ...],
) -> Decimal | None:
    normalized = {
        key.strip().lower().replace("_", "-"): value
        for key, value in record.indicator_scores.items()
    }
    for key in keys:
        value = normalized.get(key.strip().lower().replace("_", "-"))
        if value is not None:
            try:
                return Decimal(str(value))
            except Exception:
                return None
    return None


def _by_entry_state(
    diagnostics: tuple[CandidateOutcomeDiagnostic, ...],
    state: EntryState,
) -> tuple[CandidateOutcomeDiagnostic, ...]:
    return tuple(item for item in diagnostics if item.entry_state is state)


def _distance_bucket(
    value: Decimal,
    *bounds: tuple[str, Decimal],
    default: str,
) -> str:
    for label, maximum in bounds:
        if value <= maximum:
            return label
    return default


def _average(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    return (sum(present, _ZERO) / Decimal(len(present))).quantize(_FOUR)


def _median(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    return Decimal(str(median(present))).quantize(_FOUR)


def _range(values: tuple[Decimal, ...]) -> tuple[Decimal | None, Decimal | None]:
    if not values:
        return (None, None)
    return (min(values), max(values))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(_FOUR)


def _rate_decimal(numerator: int, denominator: int) -> Decimal:
    return _rate(numerator, denominator) or _ZERO


def _abs_diff(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return abs(left - right).quantize(_FOUR)


def _brier_score(items: tuple[CandidateOutcomeDiagnostic, ...]) -> Decimal | None:
    values = []
    for item in items:
        if item.posterior_probability is None:
            continue
        actual = _ONE if _is_profitable(item) else _ZERO
        values.append((item.posterior_probability - actual) ** 2)
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(_FOUR)


def _decimal_or_none(value: int | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _numeric_band(value: Decimal, boundaries: tuple[int, ...]) -> str:
    for boundary in boundaries:
        if value < Decimal(boundary):
            return f"<{boundary}"
    return f">={boundaries[-1]}"


def _optional_band(value: Decimal | None, boundaries: tuple[int, ...]) -> str:
    return "unavailable" if value is None else _numeric_band(value, boundaries)


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _metric_pct(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{(value * _HUNDRED).quantize(_TWO)}%"


def _candidate_sort_key(
    item: CandidateOutcomeDiagnostic,
) -> tuple[date, str, str]:
    return (item.replay_date, item.symbol, item.candidate_id)


def _gate_lines(stats: tuple[GateOutcomeStatistic, ...]) -> tuple[str, ...]:
    ranked = sorted(
        stats,
        key=lambda item: (
            -(item.stats.profitable_outcomes),
            item.criterion.value,
        ),
    )
    return tuple(
        f"- {item.criterion.value}: candidates {item.stats.candidate_count}, "
        f"completed {item.stats.completed_outcomes}, profitable "
        f"{item.stats.profitable_outcomes}, rate "
        f"{_metric_pct(item.stats.profitable_rejection_rate)}, avg return "
        f"{_metric(item.stats.average_forward_return)}"
        for item in ranked[:10]
    ) or ("- unavailable",)


def _threshold_lines(buckets: tuple[ThresholdDistanceBucket, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.criterion.value} / {item.bucket}: completed "
        f"{item.stats.completed_outcomes}, profitable "
        f"{item.stats.profitable_outcomes}, "
        f"rate {_metric_pct(item.stats.profitable_rejection_rate)}"
        for item in buckets[:12]
    ) or ("- unavailable",)


def _feature_lines(
    features: tuple[FeatureDistributionComparison, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.feature}: winners mean {_metric(item.winner_mean)}, losers mean "
        f"{_metric(item.loser_mean)}, missing {item.missing_count}"
        for item in features[:8]
    ) or ("- unavailable",)


def _entry_lines(stats: tuple[EntryStateStatistic, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.entry_state.value}: completed {item.stats.completed_outcomes}, "
        f"profitable {item.stats.profitable_outcomes}, rate "
        f"{_metric_pct(item.stats.profitable_rejection_rate)}, avg return "
        f"{_metric(item.stats.average_forward_return)}"
        for item in stats
    ) or ("- unavailable",)


def _calibration_lines(
    buckets: tuple[PosteriorCalibrationBucket, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.bucket}: predicted "
        f"{_metric_pct(item.predicted_average_probability)}, "
        f"observed {_metric_pct(item.observed_success_rate)}, error "
        f"{_metric(item.calibration_error)}, samples {item.sample_count}, "
        f"Brier {_metric(item.brier_score)}"
        for item in buckets
    )


def _heterogeneity_lines(
    rows: tuple[HistoricalMatchHeterogeneity, ...],
) -> tuple[str, ...]:
    warnings = tuple(item for item in rows if item.warning)
    if not warnings:
        return ("- none",)
    return tuple(
        f"- {item.symbol} {item.replay_date}: dispersion "
        f"{item.similarity_dispersion}; {item.warning}"
        for item in warnings[:10]
    )


def _candidate_dict(item: CandidateOutcomeDiagnostic) -> dict[str, object]:
    return {
        "symbol": item.symbol,
        "replay_date": item.replay_date.isoformat(),
        "candidate_id": item.candidate_id,
        "setup_type": item.setup_type,
        "market_regime": item.market_regime,
        "sector": item.sector,
        "verdict": item.verdict,
        "approved": item.approved,
        "evidence_score": str(item.evidence_score),
        "stop_distance": _text(item.stop_distance),
        "matched_samples": item.matched_samples,
        "expectancy": _text(item.expectancy),
        "posterior_probability": _text(item.posterior_probability),
        "failed_criteria": [criterion.value for criterion in item.failed_criteria],
        "primary_rejection_reason": item.primary_rejection_reason.value,
        "secondary_rejection_reasons": [
            reason.value for reason in item.secondary_rejection_reasons
        ],
        "entry_state": item.entry_state.value,
        "outcome_classification": item.outcome_classification.value,
        "completed_outcome": item.completed_outcome,
        "forward_return": _text(item.forward_return),
        "mfe": _text(item.mfe),
        "mae": _text(item.mae),
        "target_1_hit": item.target_1_hit,
        "target_2_hit": item.target_2_hit,
        "stop_hit": item.stop_hit,
        "invalidation_hit": item.invalidation_hit,
        "holding_period_outcome": item.holding_period_outcome.value
        if item.holding_period_outcome
        else None,
        "reward_risk": _text(item.reward_risk),
    }


def _delayed_dict(item: DelayedEntryOpportunity) -> dict[str, object]:
    return {
        "symbol": item.symbol,
        "original_replay_date": item.original_replay_date.isoformat(),
        "delayed_replay_date": item.delayed_replay_date.isoformat(),
        "days_until_valid_entry": item.days_until_valid_entry,
        "original_stop_distance": _text(item.original_stop_distance),
        "delayed_stop_distance": _text(item.delayed_stop_distance),
        "original_reward_risk": _text(item.original_reward_risk),
        "delayed_reward_risk": _text(item.delayed_reward_risk),
        "delayed_candidate_id": item.delayed_candidate_id,
        "explanation": item.explanation,
    }


def _report_dict(report: ApprovalOutcomeReport) -> dict[str, object]:
    return {
        "candidates_evaluated": report.candidates_evaluated,
        "completed_outcomes": report.completed_outcomes,
        "profitable_rejected_count": report.profitable_rejected_count,
        "true_negative_rejected_count": report.true_negative_rejected_count,
        "profitable_rejection_rate": _text(report.profitable_rejection_rate),
        "candidate_outcomes": [
            _candidate_dict(item) for item in report.candidate_outcomes
        ],
        "gate_statistics": [
            {"criterion": item.criterion.value, **_stats_dict(item.stats)}
            for item in report.gate_statistics
        ],
        "interaction_statistics": [
            {
                "criteria": [criterion.value for criterion in item.criteria],
                **_stats_dict(item.stats),
            }
            for item in report.interaction_statistics
        ],
        "threshold_buckets": [
            {
                "criterion": item.criterion.value,
                "bucket": item.bucket,
                **_stats_dict(item.stats),
            }
            for item in report.threshold_buckets
        ],
        "feature_comparisons": [
            {
                "feature": item.feature,
                "winner_count": item.winner_count,
                "loser_count": item.loser_count,
                "winner_mean": _text(item.winner_mean),
                "loser_mean": _text(item.loser_mean),
                "winner_median": _text(item.winner_median),
                "loser_median": _text(item.loser_median),
                "winner_range": [_text(value) for value in item.winner_range],
                "loser_range": [_text(value) for value in item.loser_range],
                "missing_count": item.missing_count,
            }
            for item in report.feature_comparisons
        ],
        "entry_state_statistics": [
            {"entry_state": item.entry_state.value, **_stats_dict(item.stats)}
            for item in report.entry_state_statistics
        ],
        "profitable_rejections": [
            _candidate_dict(item) for item in report.profitable_rejections
        ],
        "entry_opportunities": [
            _delayed_dict(item) for item in report.delayed_entry_opportunities
        ],
        "posterior_calibration": [
            {
                "bucket": item.bucket,
                "predicted_average_probability": _text(
                    item.predicted_average_probability
                ),
                "observed_success_rate": _text(item.observed_success_rate),
                "calibration_error": _text(item.calibration_error),
                "sample_count": item.sample_count,
                "completed_outcomes": item.completed_outcomes,
                "brier_score": _text(item.brier_score),
            }
            for item in report.posterior_calibration
        ],
        "historical_match_heterogeneity": [
            {
                "symbol": item.symbol,
                "replay_date": item.replay_date.isoformat(),
                "candidate_id": item.candidate_id,
                "matched_sample_count": item.matched_sample_count,
                "effective_homogeneous_sample_count": (
                    item.effective_homogeneous_sample_count
                ),
                "setup_types_represented": item.setup_types_represented,
                "regimes_represented": item.regimes_represented,
                "dominant_setup_concentration": str(item.dominant_setup_concentration),
                "dominant_regime_concentration": str(
                    item.dominant_regime_concentration
                ),
                "similarity_dispersion": str(item.similarity_dispersion),
                "warning": item.warning,
            }
            for item in report.heterogeneity
        ],
        "segmented_expectancy": [
            {
                "segment": item.segment,
                "key": item.key,
                "sample_count": item.sample_count,
                "expectancy": _text(item.expectancy),
                "posterior_probability": _text(item.posterior_probability),
            }
            for item in report.segmented_expectancy
        ],
        "bottleneck_conclusion": report.bottleneck_decision.conclusion.value,
        "bottleneck_metrics": list(report.bottleneck_decision.supporting_metrics),
    }


def _stats_dict(stats: OutcomeStats) -> dict[str, object]:
    return {
        "candidate_count": stats.candidate_count,
        "completed_outcomes": stats.completed_outcomes,
        "profitable_outcomes": stats.profitable_outcomes,
        "unsuccessful_outcomes": stats.unsuccessful_outcomes,
        "profitable_rejection_rate": _text(stats.profitable_rejection_rate),
        "average_forward_return": _text(stats.average_forward_return),
        "median_forward_return": _text(stats.median_forward_return),
        "target_1_hit_rate": _text(stats.target_1_hit_rate),
        "stop_hit_rate": _text(stats.stop_hit_rate),
        "average_mfe": _text(stats.average_mfe),
        "average_mae": _text(stats.average_mae),
    }


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _write_csv(rows: tuple[dict[str, object], ...], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
