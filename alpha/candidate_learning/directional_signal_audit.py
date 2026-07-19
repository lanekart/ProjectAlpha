from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from statistics import median

from alpha.candidate_learning.approval_diagnostics import (
    ApprovalDiagnosticsConfig,
    ApprovalDiagnosticsEngine,
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

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_POSITIVE_VERDICTS = {"BUY", "STRONG_BUY"}
_NEGATIVE_VERDICTS = {"SELL", "STRONG_SELL"}
_WATCHLIST_VERDICTS = {"WATCHLIST", "HOLD"}
_AVOID_VERDICTS = {"AVOID", "REJECT"}
_PRIMARY_ENTRY_STATES = {
    EntryTimingState.AGGRESSIVE_ENTRY,
    EntryTimingState.PREFERRED_ENTRY,
    EntryTimingState.CONFIRMATION_ENTRY,
}


class DirectionalOutcomeLabel(StrEnum):
    CLEAN_WIN = "CLEAN_WIN"
    VOLATILE_WIN = "VOLATILE_WIN"
    LATE_WIN = "LATE_WIN"
    INVALIDATED_THEN_WIN = "INVALIDATED_THEN_WIN"
    CLEAN_LOSS = "CLEAN_LOSS"
    STOPPED_THEN_RECOVERED = "STOPPED_THEN_RECOVERED"
    FLAT = "FLAT"
    OUTCOME_UNAVAILABLE = "OUTCOME_UNAVAILABLE"


class DirectionalUniverse(StrEnum):
    ALL_COMPLETED = "ALL_COMPLETED"
    ACCEPTABLY_TIMED = "ACCEPTABLY_TIMED"
    POSITIVE_DIRECTION = "POSITIVE_DIRECTION"


class LineageOverlapReason(StrEnum):
    SAME_SOURCE_FEATURES = "SAME_SOURCE_FEATURES"
    DIRECT_DERIVATION = "DIRECT_DERIVATION"
    SAME_THRESHOLD_BOUNDARY = "SAME_THRESHOLD_BOUNDARY"
    SHARED_MISSING_DATA = "SHARED_MISSING_DATA"
    COINCIDENTAL_ON_CURRENT_SAMPLE = "COINCIDENTAL_ON_CURRENT_SAMPLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    OTHER = "OTHER"


class ComponentUsefulness(StrEnum):
    USEFUL_COMPONENT = "USEFUL_COMPONENT"
    NEUTRAL_COMPONENT = "NEUTRAL_COMPONENT"
    INVERSELY_PREDICTIVE_COMPONENT = "INVERSELY_PREDICTIVE_COMPONENT"
    REDUNDANT_COMPONENT = "REDUNDANT_COMPONENT"
    EXCESSIVE_MISSINGNESS = "EXCESSIVE_MISSINGNESS"


class DirectionalSignalConclusion(StrEnum):
    DIRECTIONAL_SIGNAL_HAS_USEFUL_RANKING_BUT_POOR_CALIBRATION = (
        "DIRECTIONAL_SIGNAL_HAS_USEFUL_RANKING_BUT_POOR_CALIBRATION"
    )
    DIRECTIONAL_SIGNAL_HAS_USEFUL_RANKING_BUT_THRESHOLDS_ARE_TOO_STRICT = (
        "DIRECTIONAL_SIGNAL_HAS_USEFUL_RANKING_BUT_THRESHOLDS_ARE_TOO_STRICT"
    )
    DIRECTIONAL_SIGNAL_HAS_WEAK_WINNER_LOSER_SEPARATION = (
        "DIRECTIONAL_SIGNAL_HAS_WEAK_WINNER_LOSER_SEPARATION"
    )
    MOMENTUM_CONTINUATION_SIGNAL_IS_PRIMARY_BOTTLENECK = (
        "MOMENTUM_CONTINUATION_SIGNAL_IS_PRIMARY_BOTTLENECK"
    )
    OUTCOME_LABEL_QUALITY_IS_PRIMARY_BOTTLENECK = (
        "OUTCOME_LABEL_QUALITY_IS_PRIMARY_BOTTLENECK"
    )
    MARKET_REGIME_CLASSIFICATION_IS_PRIMARY_BOTTLENECK = (
        "MARKET_REGIME_CLASSIFICATION_IS_PRIMARY_BOTTLENECK"
    )
    HISTORICAL_EVIDENCE_QUALITY_IS_PRIMARY_BOTTLENECK = (
        "HISTORICAL_EVIDENCE_QUALITY_IS_PRIMARY_BOTTLENECK"
    )
    SIGNAL_COMPONENT_REDUNDANCY_DOMINATES = "SIGNAL_COMPONENT_REDUNDANCY_DOMINATES"
    SIGNAL_COMPONENT_SIGN_ERRORS_DETECTED = "SIGNAL_COMPONENT_SIGN_ERRORS_DETECTED"
    INSUFFICIENT_EVIDENCE_FOR_DIRECTIONAL_CONCLUSION = (
        "INSUFFICIENT_EVIDENCE_FOR_DIRECTIONAL_CONCLUSION"
    )


class NextDirectionalSignalMilestone(StrEnum):
    OUTCOME_LABEL_REFINEMENT = "OUTCOME_LABEL_REFINEMENT"
    MOMENTUM_CONTINUATION_SIGNAL_AUDIT = "MOMENTUM_CONTINUATION_SIGNAL_AUDIT"
    MARKET_REGIME_CLASSIFIER_AUDIT = "MARKET_REGIME_CLASSIFIER_AUDIT"
    HISTORICAL_EVIDENCE_QUALITY_AUDIT = "HISTORICAL_EVIDENCE_QUALITY_AUDIT"
    PROBABILITY_CALIBRATION_AUDIT = "PROBABILITY_CALIBRATION_AUDIT"
    COMPONENT_SIGN_AND_WEIGHT_AUDIT = "COMPONENT_SIGN_AND_WEIGHT_AUDIT"
    COLLECT_MORE_REPLAY_EVIDENCE = "COLLECT_MORE_REPLAY_EVIDENCE"
    NO_CHANGE_RECOMMENDED = "NO_CHANGE_RECOMMENDED"


@dataclass(frozen=True, slots=True)
class DirectionalSignalAuditConfig:
    minimum_sample: int = 30
    clean_loss_threshold: Decimal = Decimal("-2")
    clean_win_threshold: Decimal = Decimal("2")
    volatile_mae_threshold: Decimal = Decimal("-8")
    strong_correlation_threshold: Decimal = Decimal("0.15")
    weak_correlation_threshold: Decimal = Decimal("0.05")


@dataclass(frozen=True, slots=True)
class DirectionalCandidateAuditRow:
    candidate_id: str
    symbol: str
    replay_date: str
    final_verdict: str
    confidence: str
    setup_type: str | None
    market_regime: str | None
    sector: str | None
    recommendation_score: Decimal
    evidence_score: Decimal
    expectancy: Decimal | None
    posterior_probability: Decimal | None
    timing_score: Decimal
    entry_state: EntryTimingState
    forward_return: Decimal | None
    benchmark_return: Decimal | None
    excess_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    target_hit: bool | None
    stop_hit: bool | None
    target_before_stop: bool | None
    stop_before_target: bool | None
    holding_period_return: Decimal | None
    outcome_label: DirectionalOutcomeLabel
    profitable: bool
    clean_win: bool
    clean_loss: bool
    indicator_scores: dict[str, Decimal]
    raw_approved: bool
    strict_approved: bool


@dataclass(frozen=True, slots=True)
class VerdictDirectionalAccuracy:
    universe: DirectionalUniverse
    candidate_count: int
    positive_signal_count: int
    negative_signal_count: int
    watchlist_count: int
    avoid_count: int
    buy_precision: Decimal | None
    sell_precision: Decimal | None
    watchlist_win_rate: Decimal | None
    avoid_win_rate: Decimal | None
    directional_accuracy: Decimal | None
    balanced_accuracy: Decimal | None
    false_positive_rate: Decimal | None
    false_negative_rate: Decimal | None
    profitable_avoid_count: int
    profitable_sell_count: int
    losing_buy_count: int
    losing_strong_buy_count: int
    abstention_rate: Decimal | None
    coverage: Decimal | None
    excess_return_directional_accuracy: Decimal | None


@dataclass(frozen=True, slots=True)
class ScoreRankingMetric:
    score_name: str
    sample_count: int
    spearman_forward_return: Decimal | None
    spearman_excess_return: Decimal | None
    roc_auc: Decimal | None
    pr_auc: Decimal | None
    top_decile_win_rate: Decimal | None
    top_quintile_win_rate: Decimal | None
    bottom_decile_win_rate: Decimal | None
    lift_vs_base_rate: Decimal | None
    monotonicity_by_decile: Decimal | None
    cumulative_return_top_decile: Decimal | None
    average_mae_top_decile: Decimal | None


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    score_name: str
    bucket: str
    sample_count: int
    predicted_probability: Decimal | None
    observed_win_rate: Decimal | None
    observed_clean_win_rate: Decimal | None
    calibration_error: Decimal | None
    brier_score: Decimal | None
    overconfidence: str


@dataclass(frozen=True, slots=True)
class EvidenceLineageRecord:
    output_name: str
    direct_input_features: tuple[str, ...]
    source_modules: tuple[str, ...]
    historical_sample_dependencies: tuple[str, ...]
    fallback_paths: tuple[str, ...]
    missing_data_behaviour: str
    threshold: str | None
    reused_scores: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LineageOverlapFinding:
    left_output: str
    right_output: str
    jaccard: Decimal | None
    reason: LineageOverlapReason
    explanation: str


@dataclass(frozen=True, slots=True)
class ComponentAttribution:
    component: str
    availability: Decimal | None
    winner_mean: Decimal | None
    loser_mean: Decimal | None
    winner_median: Decimal | None
    loser_median: Decimal | None
    rank_correlation_forward_return: Decimal | None
    rank_correlation_excess_return: Decimal | None
    winner_loser_separation: Decimal | None
    missing_value_rate: Decimal | None
    sign_consistency: Decimal | None
    disagreement_with_final_verdict: Decimal | None
    usefulness: ComponentUsefulness


@dataclass(frozen=True, slots=True)
class SegmentDirectionalSummary:
    segment: str
    key: str
    candidate_count: int
    winner_count: int
    loser_count: int
    clean_win_count: int
    clean_loss_count: int
    buy_precision: Decimal | None
    profitable_rejection_rate: Decimal | None
    average_return: Decimal | None
    average_excess_return: Decimal | None
    ranking_correlation: Decimal | None
    sample_sufficient: bool


@dataclass(frozen=True, slots=True)
class HorizonDirectionalSummary:
    horizon: str
    sample_count: int
    average_return: Decimal | None
    win_rate: Decimal | None
    ranking_correlation: Decimal | None
    interpretation: str


@dataclass(frozen=True, slots=True)
class CounterfactualRankingView:
    view_name: str
    selected_count: int
    win_rate: Decimal | None
    average_return: Decimal | None
    average_excess_return: Decimal | None
    clean_win_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class DirectionalSignalDecision:
    primary_conclusion: DirectionalSignalConclusion
    secondary_conclusions: tuple[DirectionalSignalConclusion, ...]
    recommended_next_milestone: NextDirectionalSignalMilestone
    prohibited_next_action: str
    supporting_metrics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DirectionalSignalAuditReport:
    candidate_rows: tuple[DirectionalCandidateAuditRow, ...]
    all_accuracy: VerdictDirectionalAccuracy
    acceptable_timing_accuracy: VerdictDirectionalAccuracy
    positive_direction_accuracy: VerdictDirectionalAccuracy
    ranking_metrics: tuple[ScoreRankingMetric, ...]
    calibration: tuple[CalibrationBucket, ...]
    lineage: tuple[EvidenceLineageRecord, ...]
    lineage_overlap: tuple[LineageOverlapFinding, ...]
    components: tuple[ComponentAttribution, ...]
    setup_family: tuple[SegmentDirectionalSummary, ...]
    market_regime: tuple[SegmentDirectionalSummary, ...]
    verdict_segments: tuple[SegmentDirectionalSummary, ...]
    horizons: tuple[HorizonDirectionalSummary, ...]
    counterfactuals: tuple[CounterfactualRankingView, ...]
    decision: DirectionalSignalDecision
    raw_approval_count_before: int
    raw_approval_count_after: int
    strict_approval_count_before: int
    strict_approval_count_after: int
    recommendation_scores_unchanged: bool
    verdicts_unchanged: bool
    timing_states_unchanged: bool


class DirectionalSignalQualityAuditEngine:
    def __init__(self, config: DirectionalSignalAuditConfig | None = None) -> None:
        self.config = config or DirectionalSignalAuditConfig()

    def analyze(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> DirectionalSignalAuditReport:
        diagnostics = ApprovalDiagnosticsEngine(
            ApprovalDiagnosticsConfig(minimum_intersection_count=1)
        ).build(records=records, outcomes=outcomes)
        timing = build_entry_timing_replay_report(records=records, outcomes=outcomes)
        rows = _candidate_rows(
            records=records,
            outcomes=outcomes,
            diagnostics=diagnostics.diagnostics,
            timing_rows=timing.rows,
            config=self.config,
        )
        all_rows = rows
        acceptable = tuple(
            row for row in rows if row.entry_state in _PRIMARY_ENTRY_STATES
        )
        positive = tuple(row for row in rows if row.final_verdict in _POSITIVE_VERDICTS)
        ranking = _ranking_metrics(all_rows)
        calibration = _calibration(rows)
        lineage = _lineage()
        overlap = _lineage_overlap(rows)
        components = _components(rows)
        setup = _segment(rows, "setup", lambda row: row.setup_type or "UNKNOWN")
        regime = _segment(rows, "regime", lambda row: row.market_regime or "UNKNOWN")
        verdict = _segment(rows, "verdict", lambda row: row.final_verdict)
        horizons = _horizons(records, outcomes)
        counterfactuals = _counterfactuals(rows)
        decision = _decision(
            rows=rows,
            acceptable=acceptable,
            ranking=ranking,
            calibration=calibration,
            components=components,
            setup=setup,
            regime=regime,
        )
        raw = sum(1 for record in records if record.approved_for_deployment)
        strict = diagnostics.approved_candidates
        return DirectionalSignalAuditReport(
            candidate_rows=rows,
            all_accuracy=_accuracy(all_rows, DirectionalUniverse.ALL_COMPLETED),
            acceptable_timing_accuracy=_accuracy(
                acceptable, DirectionalUniverse.ACCEPTABLY_TIMED
            ),
            positive_direction_accuracy=_accuracy(
                positive, DirectionalUniverse.POSITIVE_DIRECTION
            ),
            ranking_metrics=ranking,
            calibration=calibration,
            lineage=lineage,
            lineage_overlap=overlap,
            components=components,
            setup_family=setup,
            market_regime=regime,
            verdict_segments=verdict,
            horizons=horizons,
            counterfactuals=counterfactuals,
            decision=decision,
            raw_approval_count_before=raw,
            raw_approval_count_after=raw,
            strict_approval_count_before=strict,
            strict_approval_count_after=strict,
            recommendation_scores_unchanged=True,
            verdicts_unchanged=True,
            timing_states_unchanged=True,
        )


def render_directional_signal_audit(
    report: DirectionalSignalAuditReport,
) -> tuple[str, ...]:
    secondary = [f"- {item.value}" for item in report.decision.secondary_conclusions]
    return (
        "Directional Signal Quality Audit",
        f"Candidates With Completed Outcomes: {len(report.candidate_rows)}",
        "Universes:",
        f"- All completed: {report.all_accuracy.candidate_count}",
        f"- Acceptably timed: {report.acceptable_timing_accuracy.candidate_count}",
        f"- Positive direction: {report.positive_direction_accuracy.candidate_count}",
        "",
        "Verdict-Level Directional Accuracy:",
        *_accuracy_lines(
            (
                report.all_accuracy,
                report.acceptable_timing_accuracy,
                report.positive_direction_accuracy,
            )
        ),
        "",
        "Ranking Quality:",
        *_ranking_lines(report.ranking_metrics),
        "",
        "Calibration:",
        *_calibration_lines(report.calibration),
        "",
        "Evidence Lineage:",
        *_lineage_lines(report.lineage_overlap),
        "",
        "Component Attribution:",
        *_component_lines(report.components),
        "",
        "Setup-Family Findings:",
        *_segment_lines(report.setup_family),
        "",
        "Market-Regime Findings:",
        *_segment_lines(report.market_regime),
        "",
        "Horizon Findings:",
        *_horizon_lines(report.horizons),
        "",
        "Counterfactual Diagnostic Views:",
        *_counterfactual_lines(report.counterfactuals),
        "",
        f"Primary Conclusion: {report.decision.primary_conclusion.value}",
        "Secondary Conclusions:",
        *(secondary or ["- none"]),
        "Recommended Next Milestone: "
        f"{report.decision.recommended_next_milestone.value}",
        f"Prohibited Next Action: {report.decision.prohibited_next_action}",
        "Policy Integrity: no recommendation, approval, timing, trade-plan, "
        "allocation, threshold, weight, or replay decision was changed.",
    )


def group_directional_signal_audit(
    report: DirectionalSignalAuditReport,
    *,
    group_by: str,
) -> tuple[str, ...]:
    if group_by == "setup":
        return _segment_lines(report.setup_family)
    if group_by == "verdict":
        return _segment_lines(report.verdict_segments)
    if group_by == "regime":
        return _segment_lines(report.market_regime)
    if group_by == "horizon":
        return _horizon_lines(report.horizons)
    if group_by == "ranking":
        return _ranking_lines(report.ranking_metrics)
    if group_by == "calibration":
        return _calibration_lines(report.calibration)
    if group_by == "components":
        return _component_lines(report.components)
    if group_by == "lineage":
        return (
            *_lineage_record_lines(report.lineage),
            *_lineage_lines(report.lineage_overlap),
        )
    if group_by == "outcome-quality":
        counts = Counter(row.outcome_label for row in report.candidate_rows)
        return tuple(f"- {key.value}: {value}" for key, value in sorted(counts.items()))
    if group_by == "counterfactual":
        return _counterfactual_lines(report.counterfactuals)
    raise ValueError(f"Unsupported grouping: {group_by}")


def export_directional_signal_audit_json(
    report: DirectionalSignalAuditReport,
    path: Path,
) -> None:
    path.write_text(
        json.dumps(_report_dict(report), indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def export_directional_signal_audit_csv(
    report: DirectionalSignalAuditReport,
    path: Path,
) -> None:
    rows = [_candidate_dict(row) for row in report.candidate_rows]
    _write_csv(rows, path)


def _candidate_rows(
    *,
    records: tuple[CandidateDecisionRecord, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
    diagnostics: tuple[object, ...],
    timing_rows: tuple[object, ...],
    config: DirectionalSignalAuditConfig,
) -> tuple[DirectionalCandidateAuditRow, ...]:
    outcomes_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
    diagnostics_by_id = {getattr(item, "candidate_id"): item for item in diagnostics}
    timing_by_id = {getattr(row, "candidate_id"): row for row in timing_rows}
    result = []
    for record in records:
        window = _primary_window(outcomes_by_id.get(record.candidate_id))
        timing = timing_by_id.get(record.candidate_id)
        diagnostic = diagnostics_by_id.get(record.candidate_id)
        if window is None or timing is None or diagnostic is None:
            continue
        forward_return = window.forward_return_pct_from_entry
        benchmark = _indicator_decimal(record, ("benchmark-return", "benchmark_return"))
        excess = (
            None
            if forward_return is None or benchmark is None
            else (forward_return - benchmark).quantize(_FOUR)
        )
        target_hit = bool(window.target_1_touched)
        stop_hit = bool(window.risk_stop_touched)
        result.append(
            DirectionalCandidateAuditRow(
                candidate_id=record.candidate_id,
                symbol=record.symbol,
                replay_date=record.evaluation_date.isoformat(),
                final_verdict=record.final_verdict,
                confidence=record.confidence,
                setup_type=record.setup_type,
                market_regime=record.market_regime,
                sector=record.sector,
                recommendation_score=record.strategy_score,
                evidence_score=record.strategy_score,
                expectancy=getattr(diagnostic, "expectancy"),
                posterior_probability=getattr(diagnostic, "posterior_probability"),
                timing_score=getattr(timing, "assessment").timing_score,
                entry_state=getattr(timing, "assessment").entry_state,
                forward_return=forward_return,
                benchmark_return=benchmark,
                excess_return=excess,
                mfe=window.max_favourable_excursion_pct,
                mae=window.max_adverse_excursion_pct,
                target_hit=target_hit,
                stop_hit=stop_hit,
                target_before_stop=target_hit and not stop_hit,
                stop_before_target=stop_hit,
                holding_period_return=forward_return,
                outcome_label=_outcome_quality(window, config),
                profitable=bool(forward_return is not None and forward_return > _ZERO),
                clean_win=False,
                clean_loss=False,
                indicator_scores=_numeric_indicator_scores(record),
                raw_approved=record.approved_for_deployment,
                strict_approved=bool(getattr(diagnostic, "approved")),
            )
        )
    finalized = tuple(_with_clean_flags(row) for row in result)
    return tuple(
        sorted(
            finalized, key=lambda row: (row.replay_date, row.symbol, row.candidate_id)
        )
    )


def _with_clean_flags(
    row: DirectionalCandidateAuditRow,
) -> DirectionalCandidateAuditRow:
    return replace(
        row,
        clean_win=row.outcome_label is DirectionalOutcomeLabel.CLEAN_WIN,
        clean_loss=row.outcome_label is DirectionalOutcomeLabel.CLEAN_LOSS,
    )


def _outcome_quality(
    window: CandidateForwardWindowOutcome,
    config: DirectionalSignalAuditConfig,
) -> DirectionalOutcomeLabel:
    value = window.forward_return_pct_from_entry
    if value is None or window.outcome_label is CandidateOutcomeLabel.DATA_MISSING:
        return DirectionalOutcomeLabel.OUTCOME_UNAVAILABLE
    if value == _ZERO:
        return DirectionalOutcomeLabel.FLAT
    if value > _ZERO:
        if window.risk_stop_touched:
            return DirectionalOutcomeLabel.STOPPED_THEN_RECOVERED
        if (
            window.max_adverse_excursion_pct is not None
            and window.max_adverse_excursion_pct <= config.volatile_mae_threshold
        ):
            return DirectionalOutcomeLabel.VOLATILE_WIN
        if window.target_1_touched and value >= config.clean_win_threshold:
            return DirectionalOutcomeLabel.CLEAN_WIN
        return DirectionalOutcomeLabel.LATE_WIN
    if window.risk_stop_touched or value <= config.clean_loss_threshold:
        return DirectionalOutcomeLabel.CLEAN_LOSS
    return DirectionalOutcomeLabel.FLAT


def _accuracy(
    rows: tuple[DirectionalCandidateAuditRow, ...],
    universe: DirectionalUniverse,
) -> VerdictDirectionalAccuracy:
    positive = tuple(row for row in rows if row.final_verdict in _POSITIVE_VERDICTS)
    negative = tuple(row for row in rows if row.final_verdict in _NEGATIVE_VERDICTS)
    watch = tuple(row for row in rows if row.final_verdict in _WATCHLIST_VERDICTS)
    avoid = tuple(row for row in rows if row.final_verdict in _AVOID_VERDICTS)
    actionable = positive + negative
    correct_positive = sum(1 for row in positive if row.profitable)
    correct_negative = sum(1 for row in negative if not row.profitable)
    positive_actual = tuple(row for row in rows if row.profitable)
    negative_actual = tuple(row for row in rows if not row.profitable)
    false_positive = sum(1 for row in positive if not row.profitable)
    false_negative = sum(
        1
        for row in rows
        if row.profitable and row.final_verdict not in _POSITIVE_VERDICTS
    )
    tpr = _rate(correct_positive, len(positive_actual))
    tnr = _rate(correct_negative, len(negative_actual))
    balanced = (
        None
        if tpr is None or tnr is None
        else ((tpr + tnr) / Decimal("2")).quantize(_FOUR)
    )
    return VerdictDirectionalAccuracy(
        universe=universe,
        candidate_count=len(rows),
        positive_signal_count=len(positive),
        negative_signal_count=len(negative),
        watchlist_count=len(watch),
        avoid_count=len(avoid),
        buy_precision=_rate(correct_positive, len(positive)),
        sell_precision=_rate(correct_negative, len(negative)),
        watchlist_win_rate=_rate(sum(1 for row in watch if row.profitable), len(watch)),
        avoid_win_rate=_rate(sum(1 for row in avoid if row.profitable), len(avoid)),
        directional_accuracy=_rate(
            correct_positive + correct_negative, len(actionable)
        ),
        balanced_accuracy=balanced,
        false_positive_rate=_rate(false_positive, len(negative_actual)),
        false_negative_rate=_rate(false_negative, len(positive_actual)),
        profitable_avoid_count=sum(1 for row in avoid if row.profitable),
        profitable_sell_count=sum(1 for row in negative if row.profitable),
        losing_buy_count=sum(
            1 for row in positive if row.final_verdict == "BUY" and not row.profitable
        ),
        losing_strong_buy_count=sum(
            1
            for row in positive
            if row.final_verdict == "STRONG_BUY" and not row.profitable
        ),
        abstention_rate=_rate(len(watch) + len(avoid), len(rows)),
        coverage=_rate(len(actionable), len(rows)),
        excess_return_directional_accuracy=_excess_accuracy(actionable),
    )


def _ranking_metrics(
    rows: tuple[DirectionalCandidateAuditRow, ...],
) -> tuple[ScoreRankingMetric, ...]:
    score_getters: tuple[
        tuple[str, Callable[[DirectionalCandidateAuditRow], Decimal | None]], ...
    ] = (
        ("recommendation_score", lambda row: row.recommendation_score),
        ("evidence_score", lambda row: row.evidence_score),
        ("expectancy", lambda row: row.expectancy),
        ("posterior_probability", lambda row: row.posterior_probability),
        ("timing_score", lambda row: row.timing_score),
    )
    component_names = sorted({key for row in rows for key in row.indicator_scores})
    score_getters = score_getters + tuple(
        (f"component:{name}", _component_getter(name)) for name in component_names
    )
    return tuple(_ranking_metric(name, rows, getter) for name, getter in score_getters)


def _ranking_metric(
    name: str,
    rows: tuple[DirectionalCandidateAuditRow, ...],
    getter: Callable[[DirectionalCandidateAuditRow], Decimal | None],
) -> ScoreRankingMetric:
    present = tuple((getter(row), row) for row in rows if getter(row) is not None)
    score_values = tuple(score for score, _ in present)
    forward = tuple(row.forward_return for _, row in present)
    excess = tuple(row.excess_return for _, row in present)
    labels = tuple(row.profitable for _, row in present)
    sorted_rows = tuple(
        row
        for _, row in sorted(present, key=lambda item: item[0] or _ZERO, reverse=True)
    )
    top_decile = _top_fraction(sorted_rows, Decimal("0.10"))
    top_quintile = _top_fraction(sorted_rows, Decimal("0.20"))
    bottom_decile = _top_fraction(tuple(reversed(sorted_rows)), Decimal("0.10"))
    base = _rate(sum(1 for row in rows if row.profitable), len(rows))
    top_rate = _rate(sum(1 for row in top_decile if row.profitable), len(top_decile))
    return ScoreRankingMetric(
        score_name=name,
        sample_count=len(present),
        spearman_forward_return=_spearman(score_values, forward),
        spearman_excess_return=_spearman(score_values, excess),
        roc_auc=_roc_auc(score_values, labels),
        pr_auc=_pr_auc(score_values, labels),
        top_decile_win_rate=top_rate,
        top_quintile_win_rate=_rate(
            sum(1 for row in top_quintile if row.profitable), len(top_quintile)
        ),
        bottom_decile_win_rate=_rate(
            sum(1 for row in bottom_decile if row.profitable), len(bottom_decile)
        ),
        lift_vs_base_rate=None
        if top_rate is None or base is None or base == _ZERO
        else (top_rate / base).quantize(_FOUR),
        monotonicity_by_decile=_monotonicity(sorted_rows),
        cumulative_return_top_decile=_sum(
            tuple(row.forward_return for row in top_decile)
        ),
        average_mae_top_decile=_average(tuple(row.mae for row in top_decile)),
    )


def _component_getter(
    name: str,
) -> Callable[[DirectionalCandidateAuditRow], Decimal | None]:
    def getter(row: DirectionalCandidateAuditRow) -> Decimal | None:
        return row.indicator_scores.get(name)

    return getter


def _calibration(
    rows: tuple[DirectionalCandidateAuditRow, ...],
) -> tuple[CalibrationBucket, ...]:
    buckets: dict[str, list[DirectionalCandidateAuditRow]] = defaultdict(list)
    for row in rows:
        buckets[_probability_bucket(row.posterior_probability)].append(row)
    result = []
    for bucket, items in sorted(buckets.items()):
        item_rows = tuple(items)
        predicted = _average(tuple(row.posterior_probability for row in item_rows))
        observed = _rate(sum(1 for row in item_rows if row.profitable), len(item_rows))
        clean = _rate(sum(1 for row in item_rows if row.clean_win), len(item_rows))
        error = (
            None
            if predicted is None or observed is None
            else abs(predicted - observed).quantize(_FOUR)
        )
        result.append(
            CalibrationBucket(
                score_name="posterior_probability",
                bucket=bucket,
                sample_count=len(item_rows),
                predicted_probability=predicted,
                observed_win_rate=observed,
                observed_clean_win_rate=clean,
                calibration_error=error,
                brier_score=_brier(item_rows),
                overconfidence=_confidence_label(predicted, observed),
            )
        )
    return tuple(result)


def _lineage() -> tuple[EvidenceLineageRecord, ...]:
    return (
        EvidenceLineageRecord(
            output_name="evidence_score",
            direct_input_features=("CandidateDecisionRecord.strategy_score",),
            source_modules=("recommendation_intelligence", "candidate_learning"),
            historical_sample_dependencies=(),
            fallback_paths=("recorded score preserved",),
            missing_data_behaviour="score required by candidate record",
            threshold="ApprovalDiagnosticsConfig.minimum_evidence_score=85",
            reused_scores=("recommendation_score",),
        ),
        EvidenceLineageRecord(
            output_name="expectancy",
            direct_input_features=("setup_type", "market_regime", "forward_return"),
            source_modules=("ApprovalDiagnosticsEngine._historical_context",),
            historical_sample_dependencies=(
                "completed replay outcomes by setup/regime",
            ),
            fallback_paths=("None when no completed matching outcomes",),
            missing_data_behaviour="missing fails numeric minimum gate",
            threshold="ApprovalDiagnosticsConfig.minimum_expectancy=0.10",
            reused_scores=(),
        ),
        EvidenceLineageRecord(
            output_name="posterior_probability",
            direct_input_features=("setup_type", "market_regime", "outcome_label"),
            source_modules=("ApprovalDiagnosticsEngine._historical_context",),
            historical_sample_dependencies=(
                "completed replay outcomes by setup/regime",
            ),
            fallback_paths=("None when no completed matching outcomes",),
            missing_data_behaviour="missing fails numeric minimum gate",
            threshold="ApprovalDiagnosticsConfig.minimum_posterior_probability=0.52",
            reused_scores=("historical_samples",),
        ),
        EvidenceLineageRecord(
            output_name="institutional_acceptance",
            direct_input_features=("CandidateDecisionRecord",),
            source_modules=("candidate_learning.aggregator.is_deployment_approved",),
            historical_sample_dependencies=(),
            fallback_paths=("strict AND policy",),
            missing_data_behaviour="missing mandatory fields reject",
            threshold="current institutional policy",
            reused_scores=("evidence_score", "expectancy", "posterior_probability"),
        ),
    )


def _lineage_overlap(
    rows: tuple[DirectionalCandidateAuditRow, ...],
) -> tuple[LineageOverlapFinding, ...]:
    exp_fail = {
        row.candidate_id
        for row in rows
        if row.expectancy is None or row.expectancy < Decimal("0.10")
    }
    post_fail = {
        row.candidate_id
        for row in rows
        if row.posterior_probability is None
        or row.posterior_probability < Decimal("0.52")
    }
    jaccard = _rate(len(exp_fail & post_fail), len(exp_fail | post_fail))
    if not rows:
        reason = LineageOverlapReason.INSUFFICIENT_EVIDENCE
    elif exp_fail == post_fail or all(
        row.expectancy is not None and row.posterior_probability is not None
        for row in rows
    ):
        reason = LineageOverlapReason.SAME_SOURCE_FEATURES
    elif any(
        row.expectancy is None and row.posterior_probability is None for row in rows
    ):
        reason = LineageOverlapReason.SHARED_MISSING_DATA
    else:
        reason = LineageOverlapReason.COINCIDENTAL_ON_CURRENT_SAMPLE
    return (
        LineageOverlapFinding(
            left_output="expectancy",
            right_output="posterior_probability",
            jaccard=jaccard,
            reason=reason,
            explanation=(
                "Both are computed from the same setup_type + market_regime "
                "historical replay grouping, so identical failures indicate shared "
                "source features rather than independent confirmation."
            ),
        ),
    )


def _components(
    rows: tuple[DirectionalCandidateAuditRow, ...],
) -> tuple[ComponentAttribution, ...]:
    names = sorted({key for row in rows for key in row.indicator_scores})
    result = []
    for name in names:
        values = tuple((row.indicator_scores.get(name), row) for row in rows)
        present = tuple((value, row) for value, row in values if value is not None)
        winners = tuple(value for value, row in present if row.profitable)
        losers = tuple(value for value, row in present if not row.profitable)
        corr = _spearman(
            tuple(value for value, _ in present),
            tuple(row.forward_return for _, row in present),
        )
        separation = _diff(_average(winners), _average(losers))
        result.append(
            ComponentAttribution(
                component=name,
                availability=_rate(len(present), len(rows)),
                winner_mean=_average(winners),
                loser_mean=_average(losers),
                winner_median=_median(winners),
                loser_median=_median(losers),
                rank_correlation_forward_return=corr,
                rank_correlation_excess_return=_spearman(
                    tuple(value for value, _ in present),
                    tuple(row.excess_return for _, row in present),
                ),
                winner_loser_separation=separation,
                missing_value_rate=_rate(len(rows) - len(present), len(rows)),
                sign_consistency=None
                if corr is None
                else (Decimal("1") if corr >= _ZERO else _ZERO),
                disagreement_with_final_verdict=_component_disagreement(name, rows),
                usefulness=_component_usefulness(
                    corr, _rate(len(rows) - len(present), len(rows))
                ),
            )
        )
    return tuple(result)


def _segment(
    rows: tuple[DirectionalCandidateAuditRow, ...],
    segment: str,
    key_fn: Callable[[DirectionalCandidateAuditRow], str],
) -> tuple[SegmentDirectionalSummary, ...]:
    grouped: dict[str, list[DirectionalCandidateAuditRow]] = defaultdict(list)
    for row in rows:
        grouped[key_fn(row)].append(row)
    result = []
    for key, items in sorted(grouped.items()):
        item_rows = tuple(items)
        positive = tuple(
            row for row in item_rows if row.final_verdict in _POSITIVE_VERDICTS
        )
        rejected_winners = tuple(
            row
            for row in item_rows
            if row.profitable and row.final_verdict not in _POSITIVE_VERDICTS
        )
        result.append(
            SegmentDirectionalSummary(
                segment=segment,
                key=key,
                candidate_count=len(item_rows),
                winner_count=sum(1 for row in item_rows if row.profitable),
                loser_count=sum(1 for row in item_rows if not row.profitable),
                clean_win_count=sum(1 for row in item_rows if row.clean_win),
                clean_loss_count=sum(1 for row in item_rows if row.clean_loss),
                buy_precision=_rate(
                    sum(1 for row in positive if row.profitable), len(positive)
                ),
                profitable_rejection_rate=_rate(len(rejected_winners), len(item_rows)),
                average_return=_average(tuple(row.forward_return for row in item_rows)),
                average_excess_return=_average(
                    tuple(row.excess_return for row in item_rows)
                ),
                ranking_correlation=_spearman(
                    tuple(row.recommendation_score for row in item_rows),
                    tuple(row.forward_return for row in item_rows),
                ),
                sample_sufficient=len(item_rows) >= 30,
            )
        )
    return tuple(result)


def _horizons(
    records: tuple[CandidateDecisionRecord, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> tuple[HorizonDirectionalSummary, ...]:
    record_by_id = {record.candidate_id: record for record in records}
    grouped: dict[str, list[tuple[Decimal, Decimal]]] = defaultdict(list)
    for outcome in outcomes:
        record = record_by_id.get(outcome.candidate_id)
        if record is None:
            continue
        for window in outcome.windows:
            if window.forward_return_pct_from_entry is not None:
                grouped[window.window].append(
                    (record.strategy_score, window.forward_return_pct_from_entry)
                )
    result = []
    for horizon, values in sorted(grouped.items()):
        returns = tuple(value for _, value in values)
        corr = _spearman(tuple(score for score, _ in values), returns)
        result.append(
            HorizonDirectionalSummary(
                horizon=horizon,
                sample_count=len(values),
                average_return=_average(returns),
                win_rate=_rate(
                    sum(1 for value in returns if value > _ZERO), len(returns)
                ),
                ranking_correlation=corr,
                interpretation=_horizon_interpretation(corr),
            )
        )
    return tuple(result)


def _counterfactuals(
    rows: tuple[DirectionalCandidateAuditRow, ...],
) -> tuple[CounterfactualRankingView, ...]:
    return (
        _counterfactual(
            "ranked_by_recommendation_score_top_decile",
            rows,
            lambda row: row.recommendation_score,
            Decimal("0.10"),
        ),
        _counterfactual(
            "ranked_by_evidence_score_top_decile",
            rows,
            lambda row: row.evidence_score,
            Decimal("0.10"),
        ),
        _counterfactual(
            "ranked_by_posterior_probability_top_decile",
            rows,
            lambda row: row.posterior_probability,
            Decimal("0.10"),
        ),
        _counterfactual(
            "ranked_by_expectancy_top_decile",
            rows,
            lambda row: row.expectancy,
            Decimal("0.10"),
        ),
        _view(
            "buy_and_strong_buy_only",
            tuple(row for row in rows if row.final_verdict in _POSITIVE_VERDICTS),
        ),
        _view(
            "watchlist_included",
            tuple(
                row
                for row in rows
                if row.final_verdict in _POSITIVE_VERDICTS | _WATCHLIST_VERDICTS
            ),
        ),
        _view(
            "profitable_avoid_inspection",
            tuple(
                row
                for row in rows
                if row.final_verdict in _AVOID_VERDICTS and row.profitable
            ),
        ),
    )


def _decision(
    *,
    rows: tuple[DirectionalCandidateAuditRow, ...],
    acceptable: tuple[DirectionalCandidateAuditRow, ...],
    ranking: tuple[ScoreRankingMetric, ...],
    calibration: tuple[CalibrationBucket, ...],
    components: tuple[ComponentAttribution, ...],
    setup: tuple[SegmentDirectionalSummary, ...],
    regime: tuple[SegmentDirectionalSummary, ...],
) -> DirectionalSignalDecision:
    secondary: list[DirectionalSignalConclusion] = []
    dc = DirectionalSignalConclusion
    recommendation_metric = next(
        item for item in ranking if item.score_name == "recommendation_score"
    )
    momentum = next(
        (item for item in setup if item.key == "MOMENTUM CONTINUATION"), None
    )
    largest_regime = max(regime, key=lambda item: item.candidate_count, default=None)
    calibration_error = max(
        (item.calibration_error or _ZERO for item in calibration),
        default=_ZERO,
    )
    inverse_components = tuple(
        item
        for item in components
        if item.usefulness is ComponentUsefulness.INVERSELY_PREDICTIVE_COMPONENT
    )
    if len(rows) < 30:
        primary = (
            DirectionalSignalConclusion.INSUFFICIENT_EVIDENCE_FOR_DIRECTIONAL_CONCLUSION
        )
        next_step = NextDirectionalSignalMilestone.COLLECT_MORE_REPLAY_EVIDENCE
    elif (
        momentum is not None
        and acceptable
        and momentum.candidate_count / max(1, len(rows)) >= Decimal("0.50")
        and (momentum.ranking_correlation or _ZERO) <= Decimal("0.05")
    ):
        primary = dc.MOMENTUM_CONTINUATION_SIGNAL_IS_PRIMARY_BOTTLENECK
        next_step = NextDirectionalSignalMilestone.MOMENTUM_CONTINUATION_SIGNAL_AUDIT
    elif largest_regime is not None and largest_regime.candidate_count / len(
        rows
    ) >= Decimal("0.80"):
        primary = dc.MARKET_REGIME_CLASSIFICATION_IS_PRIMARY_BOTTLENECK
        next_step = NextDirectionalSignalMilestone.MARKET_REGIME_CLASSIFIER_AUDIT
    elif abs(recommendation_metric.spearman_forward_return or _ZERO) < Decimal("0.05"):
        primary = dc.DIRECTIONAL_SIGNAL_HAS_WEAK_WINNER_LOSER_SEPARATION
        next_step = NextDirectionalSignalMilestone.COMPONENT_SIGN_AND_WEIGHT_AUDIT
    elif calibration_error >= Decimal("0.20"):
        primary = dc.DIRECTIONAL_SIGNAL_HAS_USEFUL_RANKING_BUT_POOR_CALIBRATION
        next_step = NextDirectionalSignalMilestone.PROBABILITY_CALIBRATION_AUDIT
    else:
        primary = dc.DIRECTIONAL_SIGNAL_HAS_USEFUL_RANKING_BUT_THRESHOLDS_ARE_TOO_STRICT
        next_step = NextDirectionalSignalMilestone.COMPONENT_SIGN_AND_WEIGHT_AUDIT
    if inverse_components:
        secondary.append(
            DirectionalSignalConclusion.SIGNAL_COMPONENT_SIGN_ERRORS_DETECTED
        )
    if calibration_error >= Decimal("0.20"):
        secondary.append(
            DirectionalSignalConclusion.DIRECTIONAL_SIGNAL_HAS_USEFUL_RANKING_BUT_POOR_CALIBRATION
        )
    if largest_regime is not None and largest_regime.candidate_count / max(
        1, len(rows)
    ) >= Decimal("0.80"):
        secondary.append(
            DirectionalSignalConclusion.MARKET_REGIME_CLASSIFICATION_IS_PRIMARY_BOTTLENECK
        )
    return DirectionalSignalDecision(
        primary_conclusion=primary,
        secondary_conclusions=tuple(
            dict.fromkeys(item for item in secondary if item is not primary)
        ),
        recommended_next_milestone=next_step,
        prohibited_next_action=(
            "Do not modify production scores, verdicts, thresholds, gates, timing, "
            "trade plans, allocation, probabilities, or indicator weights from "
            "this audit."
        ),
        supporting_metrics=(
            f"recommendation_score_spearman={_metric(recommendation_metric.spearman_forward_return)}",
            f"max_calibration_error={calibration_error}",
            f"acceptable_timing_candidates={len(acceptable)}",
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


def _numeric_indicator_scores(record: CandidateDecisionRecord) -> dict[str, Decimal]:
    result = {}
    for key, value in record.indicator_scores.items():
        try:
            result[str(key)] = Decimal(str(value))
        except Exception:
            continue
    return result


def _indicator_decimal(
    record: CandidateDecisionRecord,
    keys: tuple[str, ...],
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


def _excess_accuracy(rows: tuple[DirectionalCandidateAuditRow, ...]) -> Decimal | None:
    known = tuple(row for row in rows if row.excess_return is not None)
    if not known:
        return None
    correct = sum(
        1
        for row in known
        if (
            row.final_verdict in _POSITIVE_VERDICTS
            and row.excess_return is not None
            and row.excess_return > _ZERO
        )
        or (
            row.final_verdict in _NEGATIVE_VERDICTS
            and row.excess_return is not None
            and row.excess_return <= _ZERO
        )
    )
    return _rate(correct, len(known))


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
    left_ranks = _ranks(tuple(a for a, _ in pairs))
    right_ranks = _ranks(tuple(b for _, b in pairs))
    return _pearson(left_ranks, right_ranks)


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
    for pos in positives:
        for neg in negatives:
            if pos > neg:
                wins += _ONE
            elif pos == neg:
                wins += Decimal("0.5")
    return (wins / total).quantize(_FOUR)


def _pr_auc(
    scores: tuple[Decimal | None, ...], labels: tuple[bool, ...]
) -> Decimal | None:
    pairs = sorted(
        (
            (score, label)
            for score, label in zip(scores, labels, strict=False)
            if score is not None
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    positives = sum(1 for _, label in pairs if label)
    if positives == 0 or len(pairs) < 2:
        return None
    precisions = []
    tp = 0
    for index, (_, label) in enumerate(pairs, start=1):
        if label:
            tp += 1
            precisions.append(Decimal(tp) / Decimal(index))
    return (sum(precisions, _ZERO) / Decimal(positives)).quantize(_FOUR)


def _top_fraction(
    rows: tuple[DirectionalCandidateAuditRow, ...],
    fraction: Decimal,
) -> tuple[DirectionalCandidateAuditRow, ...]:
    if not rows:
        return ()
    count = max(1, int(Decimal(len(rows)) * fraction))
    return rows[:count]


def _monotonicity(rows: tuple[DirectionalCandidateAuditRow, ...]) -> Decimal | None:
    if len(rows) < 10:
        return None
    deciles = []
    for index in range(10):
        start = int(len(rows) * index / 10)
        end = int(len(rows) * (index + 1) / 10)
        bucket = rows[start:end]
        deciles.append(
            _rate(sum(1 for row in bucket if row.profitable), len(bucket)) or _ZERO
        )
    drops = sum(
        1 for left, right in zip(deciles, deciles[1:], strict=False) if left >= right
    )
    return _rate(drops, 9)


def _brier(rows: tuple[DirectionalCandidateAuditRow, ...]) -> Decimal | None:
    values = []
    for row in rows:
        if row.posterior_probability is not None:
            actual = _ONE if row.profitable else _ZERO
            values.append((row.posterior_probability - actual) ** 2)
    return _average(tuple(values))


def _probability_bucket(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    if value >= Decimal("0.70"):
        return "0.70+"
    if value >= Decimal("0.60"):
        return "0.60-0.69"
    if value >= Decimal("0.52"):
        return "0.52-0.59"
    return "<0.52"


def _confidence_label(predicted: Decimal | None, observed: Decimal | None) -> str:
    if predicted is None or observed is None:
        return "unavailable"
    diff = predicted - observed
    if diff > Decimal("0.05"):
        return "overconfident"
    if diff < Decimal("-0.05"):
        return "underconfident"
    return "well_calibrated"


def _component_disagreement(
    name: str,
    rows: tuple[DirectionalCandidateAuditRow, ...],
) -> Decimal | None:
    present = tuple(row for row in rows if name in row.indicator_scores)
    if not present:
        return None
    disagreements = sum(
        1
        for row in present
        if (row.indicator_scores[name] >= Decimal("50"))
        != (row.final_verdict in _POSITIVE_VERDICTS)
    )
    return _rate(disagreements, len(present))


def _component_usefulness(
    corr: Decimal | None,
    missing_rate: Decimal | None,
) -> ComponentUsefulness:
    if missing_rate is not None and missing_rate >= Decimal("0.50"):
        return ComponentUsefulness.EXCESSIVE_MISSINGNESS
    if corr is None or abs(corr) < Decimal("0.05"):
        return ComponentUsefulness.NEUTRAL_COMPONENT
    if corr < _ZERO:
        return ComponentUsefulness.INVERSELY_PREDICTIVE_COMPONENT
    return ComponentUsefulness.USEFUL_COMPONENT


def _counterfactual(
    name: str,
    rows: tuple[DirectionalCandidateAuditRow, ...],
    getter: Callable[[DirectionalCandidateAuditRow], Decimal | None],
    fraction: Decimal,
) -> CounterfactualRankingView:
    ranked = tuple(
        row
        for _, row in sorted(
            ((getter(row), row) for row in rows if getter(row) is not None),
            key=lambda item: item[0] or _ZERO,
            reverse=True,
        )
    )
    return _view(name, _top_fraction(ranked, fraction))


def _view(
    name: str,
    rows: tuple[DirectionalCandidateAuditRow, ...],
) -> CounterfactualRankingView:
    return CounterfactualRankingView(
        view_name=name,
        selected_count=len(rows),
        win_rate=_rate(sum(1 for row in rows if row.profitable), len(rows)),
        average_return=_average(tuple(row.forward_return for row in rows)),
        average_excess_return=_average(tuple(row.excess_return for row in rows)),
        clean_win_rate=_rate(sum(1 for row in rows if row.clean_win), len(rows)),
    )


def _horizon_interpretation(corr: Decimal | None) -> str:
    if corr is None:
        return "insufficient variation"
    if corr >= Decimal("0.10"):
        return "directionally useful at this horizon"
    if corr <= Decimal("-0.10"):
        return "inversely aligned at this horizon"
    return "weak or unstable at this horizon"


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


def _diff(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return (left - right).quantize(_FOUR)


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _accuracy_lines(items: tuple[VerdictDirectionalAccuracy, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.universe.value}: count {item.candidate_count}, "
        f"BUY precision {_metric(item.buy_precision)}, "
        f"AVOID win rate {_metric(item.avoid_win_rate)}, "
        f"accuracy {_metric(item.directional_accuracy)}"
        for item in items
    )


def _ranking_lines(items: tuple[ScoreRankingMetric, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.score_name}: n {item.sample_count}, spearman "
        f"{_metric(item.spearman_forward_return)}, auc {_metric(item.roc_auc)}, "
        f"top decile win {_metric(item.top_decile_win_rate)}"
        for item in items[:12]
    )


def _calibration_lines(items: tuple[CalibrationBucket, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.bucket}: n {item.sample_count}, predicted "
        f"{_metric(item.predicted_probability)}, observed "
        f"{_metric(item.observed_win_rate)}, {item.overconfidence}"
        for item in items
    )


def _lineage_record_lines(items: tuple[EvidenceLineageRecord, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.output_name}: inputs {', '.join(item.direct_input_features)}, "
        f"threshold {item.threshold or 'none'}"
        for item in items
    )


def _lineage_lines(items: tuple[LineageOverlapFinding, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.left_output}+{item.right_output}: jaccard "
        f"{_metric(item.jaccard)}, reason {item.reason.value}"
        for item in items
    )


def _component_lines(items: tuple[ComponentAttribution, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.component}: availability {_metric(item.availability)}, "
        f"corr {_metric(item.rank_correlation_forward_return)}, "
        f"{item.usefulness.value}"
        for item in items[:15]
    ) or ("- none",)


def _segment_lines(items: tuple[SegmentDirectionalSummary, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.segment} {item.key}: count {item.candidate_count}, "
        f"winners {item.winner_count}, losers {item.loser_count}, "
        f"avg return {_metric(item.average_return)}, "
        f"ranking corr {_metric(item.ranking_correlation)}"
        for item in items
    )


def _horizon_lines(items: tuple[HorizonDirectionalSummary, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.horizon}: n {item.sample_count}, win rate "
        f"{_metric(item.win_rate)}, corr {_metric(item.ranking_correlation)}, "
        f"{item.interpretation}"
        for item in items
    )


def _counterfactual_lines(
    items: tuple[CounterfactualRankingView, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.view_name}: selected {item.selected_count}, win rate "
        f"{_metric(item.win_rate)}, avg return {_metric(item.average_return)}"
        for item in items
    )


def _candidate_dict(row: DirectionalCandidateAuditRow) -> dict[str, object]:
    return {
        "candidate_id": row.candidate_id,
        "symbol": row.symbol,
        "replay_date": row.replay_date,
        "final_verdict": row.final_verdict,
        "confidence": row.confidence,
        "setup_type": row.setup_type,
        "market_regime": row.market_regime,
        "recommendation_score": str(row.recommendation_score),
        "expectancy": _text(row.expectancy),
        "posterior_probability": _text(row.posterior_probability),
        "timing_score": str(row.timing_score),
        "entry_state": row.entry_state.value,
        "forward_return": _text(row.forward_return),
        "benchmark_return": _text(row.benchmark_return),
        "excess_return": _text(row.excess_return),
        "outcome_label": row.outcome_label.value,
        "profitable": row.profitable,
        "clean_win": row.clean_win,
        "clean_loss": row.clean_loss,
        "raw_approved": row.raw_approved,
        "strict_approved": row.strict_approved,
    }


def _report_dict(report: DirectionalSignalAuditReport) -> dict[str, object]:
    return {
        "candidate_count": len(report.candidate_rows),
        "all_accuracy": _accuracy_dict(report.all_accuracy),
        "acceptable_timing_accuracy": _accuracy_dict(report.acceptable_timing_accuracy),
        "positive_direction_accuracy": _accuracy_dict(
            report.positive_direction_accuracy
        ),
        "ranking_metrics": [asdict(item) for item in report.ranking_metrics],
        "calibration": [asdict(item) for item in report.calibration],
        "lineage_overlap": [asdict(item) for item in report.lineage_overlap],
        "primary_conclusion": report.decision.primary_conclusion.value,
        "secondary_conclusions": [
            item.value for item in report.decision.secondary_conclusions
        ],
        "recommended_next_milestone": report.decision.recommended_next_milestone.value,
        "raw_approval_count_before": report.raw_approval_count_before,
        "raw_approval_count_after": report.raw_approval_count_after,
        "strict_approval_count_before": report.strict_approval_count_before,
        "strict_approval_count_after": report.strict_approval_count_after,
        "candidates": [_candidate_dict(row) for row in report.candidate_rows],
    }


def _accuracy_dict(item: VerdictDirectionalAccuracy) -> dict[str, object]:
    return {
        "universe": item.universe.value,
        "candidate_count": item.candidate_count,
        "buy_precision": _text(item.buy_precision),
        "sell_precision": _text(item.sell_precision),
        "directional_accuracy": _text(item.directional_accuracy),
        "balanced_accuracy": _text(item.balanced_accuracy),
        "profitable_avoid_count": item.profitable_avoid_count,
        "losing_buy_count": item.losing_buy_count,
    }


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
