from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from statistics import median

from alpha.candidate_learning.approval_diagnostics import (
    ApprovalDiagnosticsEngine,
)
from alpha.candidate_learning.approval_outcomes import (
    ApprovalOutcomeAnalysisEngine,
)
from alpha.candidate_learning.entry_timing import (
    EntryTimingOutcomeRow,
    EntryTimingReplayReport,
    EntryTimingState,
    TimingConfidence,
    build_entry_timing_replay_report,
)
from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_HUNDRED = Decimal("100")


class ApprovalConcept(StrEnum):
    RAW_APPROVAL = "raw approval"
    INSTITUTIONAL_APPROVAL = "institutional approval"
    TRADE_PLAN_APPROVAL = "trade-plan approval"
    RECOMMENDATION_APPROVAL = "recommendation approval"
    ALLOCATION_APPROVAL = "allocation approval"
    OTHER = "other"


class ApprovalBaselineConclusion(StrEnum):
    APPROVAL_BASELINES_RECONCILED = "APPROVAL_BASELINES_RECONCILED"
    DIFFERENT_APPROVAL_CONCEPTS = "DIFFERENT_APPROVAL_CONCEPTS"
    DIFFERENT_REPLAY_UNIVERSES = "DIFFERENT_REPLAY_UNIVERSES"
    DIFFERENT_REPLAY_FILTERS = "DIFFERENT_REPLAY_FILTERS"
    APPROVAL_BASELINE_INCONSISTENT = "APPROVAL_BASELINE_INCONSISTENT"
    APPROVAL_BASELINE_UNAVAILABLE = "APPROVAL_BASELINE_UNAVAILABLE"


class IncrementalValueConclusion(StrEnum):
    TIMING_ADDS_INCREMENTAL_INFORMATION = "TIMING_ADDS_INCREMENTAL_INFORMATION"
    TIMING_DUPLICATES_STOP_DISTANCE = "TIMING_DUPLICATES_STOP_DISTANCE"
    TIMING_DUPLICATES_EXTENSION = "TIMING_DUPLICATES_EXTENSION"
    TIMING_ONLY_IDENTIFIES_EXTREME_LATENESS = "TIMING_ONLY_IDENTIFIES_EXTREME_LATENESS"
    TIMING_HAS_WEAK_INCREMENTAL_VALUE = "TIMING_HAS_WEAK_INCREMENTAL_VALUE"
    INSUFFICIENT_EVIDENCE_FOR_INCREMENTAL_VALUE = (
        "INSUFFICIENT_EVIDENCE_FOR_INCREMENTAL_VALUE"
    )


class BoundaryFlag(StrEnum):
    STABLE_BOUNDARY = "STABLE_BOUNDARY"
    SENSITIVE_BOUNDARY = "SENSITIVE_BOUNDARY"
    OVERLAPPING_OUTCOMES = "OVERLAPPING_OUTCOMES"
    INSUFFICIENT_BOUNDARY_SAMPLE = "INSUFFICIENT_BOUNDARY_SAMPLE"
    POSSIBLE_CLASSIFICATION_DISCONTINUITY = "POSSIBLE_CLASSIFICATION_DISCONTINUITY"


class TimingAuditConclusion(StrEnum):
    TIMING_SEPARATES_OUTCOMES = "TIMING_SEPARATES_OUTCOMES"
    TIMING_ONLY_IDENTIFIES_EXTREME_LATENESS = "TIMING_ONLY_IDENTIFIES_EXTREME_LATENESS"
    PREFERRED_STATE_NOT_EMPIRICALLY_SUPPORTED = (
        "PREFERRED_STATE_NOT_EMPIRICALLY_SUPPORTED"
    )
    CONFIRMATION_STATE_NOT_EMPIRICALLY_SUPPORTED = (
        "CONFIRMATION_STATE_NOT_EMPIRICALLY_SUPPORTED"
    )
    ACCEPTABLE_TIMING_DIRECTIONAL_EDGE_ABSENT = (
        "ACCEPTABLE_TIMING_DIRECTIONAL_EDGE_ABSENT"
    )
    ACCEPTABLE_TIMING_NON_ENTRY_GATES_REJECT = (
        "ACCEPTABLE_TIMING_NON_ENTRY_GATES_REJECT"
    )
    TIMING_AND_NON_ENTRY_GATES_BOTH_FAIL = "TIMING_AND_NON_ENTRY_GATES_BOTH_FAIL"
    TIMING_DUPLICATES_STOP_DISTANCE = "TIMING_DUPLICATES_STOP_DISTANCE"
    TIMING_DUPLICATES_EXTENSION = "TIMING_DUPLICATES_EXTENSION"
    TIMING_ADDS_INCREMENTAL_INFORMATION = "TIMING_ADDS_INCREMENTAL_INFORMATION"
    TIMING_MODEL_NOT_CALIBRATED = "TIMING_MODEL_NOT_CALIBRATED"
    ENTRY_STATE_BOUNDARIES_UNSTABLE = "ENTRY_STATE_BOUNDARIES_UNSTABLE"
    APPROVAL_BASELINE_INCONSISTENT = "APPROVAL_BASELINE_INCONSISTENT"
    INSUFFICIENT_STATE_SAMPLE = "INSUFFICIENT_STATE_SAMPLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class NextMilestoneRecommendation(StrEnum):
    PROCEED_TO_DYNAMIC_ENTRY_ZONE_OPTIMIZATION = (
        "PROCEED_TO_DYNAMIC_ENTRY_ZONE_OPTIMIZATION"
    )
    REFINE_ENTRY_TIMING_CLASSIFICATION = "REFINE_ENTRY_TIMING_CLASSIFICATION"
    INVESTIGATE_NON_ENTRY_GATES = "INVESTIGATE_NON_ENTRY_GATES"
    INVESTIGATE_DIRECTIONAL_SIGNAL_QUALITY = "INVESTIGATE_DIRECTIONAL_SIGNAL_QUALITY"
    RECONCILE_APPROVAL_PIPELINE_FIRST = "RECONCILE_APPROVAL_PIPELINE_FIRST"
    COLLECT_MORE_REPLAY_EVIDENCE = "COLLECT_MORE_REPLAY_EVIDENCE"
    NO_CHANGE_RECOMMENDED = "NO_CHANGE_RECOMMENDED"


@dataclass(frozen=True, slots=True)
class EntryTimingValidationConfig:
    minimum_state_sample: int = 30
    minimum_boundary_sample: int = 20
    boundary_distance_pct: Decimal = Decimal("1.00")
    trimmed_mean_fraction: Decimal = Decimal("0.10")
    material_success_spread: Decimal = Decimal("0.10")
    material_return_spread: Decimal = Decimal("5.00")
    preferred_support_distance_pct: Decimal = Decimal("3")
    early_support_distance_pct: Decimal = Decimal("5")
    extended_support_distance_pct: Decimal = Decimal("10")


@dataclass(frozen=True, slots=True)
class ApprovalBaselineSource:
    diagnostic_name: str
    replay_dataset_identifier: str
    replay_date_range: tuple[date | None, date | None]
    candidate_universe: str
    candidate_count: int
    completed_outcome_count: int
    approval_stage: str
    approval_definition: str
    approval_concept: ApprovalConcept
    approval_count: int
    rejection_count: int
    missing_outcome_count: int
    filters_applied: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApprovalBaselineComparison:
    sources: tuple[ApprovalBaselineSource, ...]
    conclusion: ApprovalBaselineConclusion
    explanation: str


@dataclass(frozen=True, slots=True)
class EntryStateValidationStats:
    entry_state: EntryTimingState
    total_candidates: int
    completed_outcomes: int
    winners: int
    losers: int
    flat_outcomes: int
    success_rate: Decimal | None
    failure_rate: Decimal | None
    mean_return: Decimal | None
    median_return: Decimal | None
    trimmed_mean_return: Decimal | None
    min_return: Decimal | None
    max_return: Decimal | None
    return_quartiles: tuple[Decimal | None, Decimal | None, Decimal | None]
    standard_deviation: Decimal | None
    average_mae: Decimal | None
    average_mfe: Decimal | None
    stop_hit_rate: Decimal | None
    target_1_hit_rate: Decimal | None
    target_2_hit_rate: Decimal | None
    average_realised_reward_risk: Decimal | None
    average_planned_reward_risk: Decimal | None
    average_stop_distance: Decimal | None
    median_stop_distance: Decimal | None
    average_support_distance: Decimal | None
    average_price_extension: Decimal | None
    average_timing_score: Decimal | None
    median_timing_score: Decimal | None
    average_timing_confidence: Decimal | None
    insufficient_evidence: bool


@dataclass(frozen=True, slots=True)
class ProfitableRejectionTimingAttribution:
    entry_state: EntryTimingState
    candidate_count: int
    percentage_of_profitable_rejections: Decimal | None
    average_return: Decimal | None
    median_return: Decimal | None
    average_timing_score: Decimal | None
    average_stop_distance: Decimal | None
    average_support_distance: Decimal | None
    average_reward_risk: Decimal | None
    primary_rejection_criterion: str | None
    failed_criteria: tuple[str, ...]
    average_failed_gate_count: Decimal | None
    near_approval_count: int
    materially_rejected_count: int
    category: str


@dataclass(frozen=True, slots=True)
class WinnerLoserAuditComparison:
    feature: str
    winner_mean: Decimal | None
    loser_mean: Decimal | None
    winner_median: Decimal | None
    loser_median: Decimal | None
    absolute_difference: Decimal | None
    normalized_difference: Decimal | None
    winner_count: int
    loser_count: int
    missing_count: int


@dataclass(frozen=True, slots=True)
class IncrementalValueDiagnostic:
    feature_family: str
    success_spread: Decimal | None
    return_spread: Decimal | None
    bucket_count: int
    sample_count: int
    conclusion: IncrementalValueConclusion


@dataclass(frozen=True, slots=True)
class BoundaryAuditResult:
    boundary: str
    controlling_variables: tuple[str, ...]
    threshold_values: tuple[str, ...]
    close_candidate_count: int
    left_success_rate: Decimal | None
    right_success_rate: Decimal | None
    left_mean_return: Decimal | None
    right_mean_return: Decimal | None
    left_median_return: Decimal | None
    right_median_return: Decimal | None
    distance_from_threshold: Decimal | None
    flag: BoundaryFlag


@dataclass(frozen=True, slots=True)
class TimingAuditDecision:
    primary_conclusion: TimingAuditConclusion
    secondary_conclusions: tuple[TimingAuditConclusion, ...]
    supporting_metrics: tuple[str, ...]
    contradictions: tuple[str, ...]
    caveats: tuple[str, ...]
    recommended_next_milestone: NextMilestoneRecommendation
    prohibited_next_step: str | None


@dataclass(frozen=True, slots=True)
class EntryTimingValidationReport:
    baseline_comparison: ApprovalBaselineComparison
    state_validation: tuple[EntryStateValidationStats, ...]
    profitable_rejection_attribution: tuple[ProfitableRejectionTimingAttribution, ...]
    winner_loser_comparison: tuple[WinnerLoserAuditComparison, ...]
    incremental_value: tuple[IncrementalValueDiagnostic, ...]
    boundary_audit: tuple[BoundaryAuditResult, ...]
    decision: TimingAuditDecision
    candidates_evaluated: int
    completed_outcomes: int
    profitable_rejection_count: int
    approval_count_before: int
    approval_count_after: int


class ApprovalBaselineAuditEngine:
    def compare(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
        timing_report: EntryTimingReplayReport,
    ) -> ApprovalBaselineComparison:
        institutional = ApprovalDiagnosticsEngine().build(
            records=records,
            outcomes=outcomes,
        )
        completed = timing_report.completed_outcomes
        date_range = _date_range(records)
        missing = len(records) - completed
        sources = (
            ApprovalBaselineSource(
                diagnostic_name="replay approval-diagnostics",
                replay_dataset_identifier="candidate_learning_ledger",
                replay_date_range=date_range,
                candidate_universe="candidate records evaluated by strict gate",
                candidate_count=institutional.total_candidates,
                completed_outcome_count=completed,
                approval_stage="institutional gatekeeper",
                approval_definition=(
                    "is_deployment_approved(record) with strict AND logic"
                ),
                approval_concept=ApprovalConcept.INSTITUTIONAL_APPROVAL,
                approval_count=institutional.approved_candidates,
                rejection_count=institutional.rejected_candidates,
                missing_outcome_count=missing,
                filters_applied=(),
            ),
            ApprovalBaselineSource(
                diagnostic_name="replay entry-timing",
                replay_dataset_identifier="candidate_learning_ledger",
                replay_date_range=date_range,
                candidate_universe="candidate records classified for timing",
                candidate_count=timing_report.candidates_evaluated,
                completed_outcome_count=completed,
                approval_stage="recorded recommendation flag",
                approval_definition="record.approved_for_deployment",
                approval_concept=ApprovalConcept.RAW_APPROVAL,
                approval_count=timing_report.approval_count_before,
                rejection_count=(
                    timing_report.candidates_evaluated
                    - timing_report.approval_count_before
                ),
                missing_outcome_count=missing,
                filters_applied=(),
            ),
        )
        conclusion = _baseline_conclusion(sources)
        explanation = _baseline_explanation(sources, conclusion)
        return ApprovalBaselineComparison(
            sources=sources,
            conclusion=conclusion,
            explanation=explanation,
        )


class EntryTimingValidationEngine:
    def __init__(self, config: EntryTimingValidationConfig | None = None) -> None:
        self.config = config or EntryTimingValidationConfig()

    def audit(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> EntryTimingValidationReport:
        timing_report = build_entry_timing_replay_report(
            records=records,
            outcomes=outcomes,
        )
        outcome_report = ApprovalOutcomeAnalysisEngine().analyze(
            records=records,
            outcomes=outcomes,
        )
        baseline = ApprovalBaselineAuditEngine().compare(
            records=records,
            outcomes=outcomes,
            timing_report=timing_report,
        )
        profitable_ids = {
            candidate.candidate_id for candidate in outcome_report.profitable_rejections
        }
        profitable_rows = tuple(
            row for row in timing_report.rows if row.candidate_id in profitable_ids
        )
        state_validation = _state_validation(timing_report.rows, self.config)
        attribution = _profitable_attribution(profitable_rows, timing_report.rows)
        winner_loser = _winner_loser_audit(timing_report.rows)
        incremental = _incremental_value(timing_report.rows, self.config)
        boundaries = _boundary_audit(timing_report.rows, self.config)
        decision = _decision(
            baseline=baseline,
            state_validation=state_validation,
            attribution=attribution,
            incremental=incremental,
            boundaries=boundaries,
            profitable_rows=profitable_rows,
            config=self.config,
        )
        return EntryTimingValidationReport(
            baseline_comparison=baseline,
            state_validation=state_validation,
            profitable_rejection_attribution=attribution,
            winner_loser_comparison=winner_loser,
            incremental_value=incremental,
            boundary_audit=boundaries,
            decision=decision,
            candidates_evaluated=timing_report.candidates_evaluated,
            completed_outcomes=timing_report.completed_outcomes,
            profitable_rejection_count=len(profitable_rows),
            approval_count_before=timing_report.approval_count_before,
            approval_count_after=timing_report.approval_count_after,
        )


def render_approval_baseline_audit(
    comparison: ApprovalBaselineComparison,
) -> tuple[str, ...]:
    lines = [
        "Approval Baseline Audit",
        f"Conclusion: {comparison.conclusion.value}",
        comparison.explanation,
        "",
        "Sources:",
    ]
    for source in comparison.sources:
        lines.append(
            f"- {source.diagnostic_name}: {source.approval_count} approvals; "
            f"concept {source.approval_concept.value}; stage "
            f"{source.approval_stage}; candidates {source.candidate_count}"
        )
        lines.append(f"  Definition: {source.approval_definition}")
    return tuple(lines)


def render_entry_timing_validation_report(
    report: EntryTimingValidationReport,
) -> tuple[str, ...]:
    secondary = [f"- {item.value}" for item in report.decision.secondary_conclusions]
    contradictions = [f"- {item}" for item in report.decision.contradictions]
    caveats = [f"- {item}" for item in report.decision.caveats]
    lines = [
        "Entry Timing Validation and Gate Attribution Audit",
        f"Candidates Evaluated: {report.candidates_evaluated}",
        f"Completed Outcomes: {report.completed_outcomes}",
        "Approval Count Before: "
        f"{report.approval_count_before} | After: {report.approval_count_after}",
        f"Profitable Rejections Analysed: {report.profitable_rejection_count}",
        "",
        "Approval Baseline Reconciliation:",
        f"- {report.baseline_comparison.conclusion.value}: "
        f"{report.baseline_comparison.explanation}",
        "",
        "State-Level Outcome Table:",
        *_state_lines(report.state_validation),
        "",
        "Profitable-Rejection Timing Attribution:",
        *_attribution_lines(report.profitable_rejection_attribution),
        "",
        "Winner Versus Loser Comparison:",
        *_winner_loser_lines(report.winner_loser_comparison),
        "",
        "Incremental-Value Diagnostics:",
        *_incremental_lines(report.incremental_value),
        "",
        "Boundary Audit:",
        *_boundary_lines(report.boundary_audit),
        "",
        f"Primary Conclusion: {report.decision.primary_conclusion.value}",
        "Secondary Conclusions:",
        *(secondary or ["- none"]),
        "Supporting Metrics:",
        *[f"- {metric}" for metric in report.decision.supporting_metrics],
        "Contradictions:",
        *(contradictions or ["- none"]),
        "Caveats:",
        *(caveats or ["- none"]),
        "Recommended Next Milestone: "
        f"{report.decision.recommended_next_milestone.value}",
    ]
    if report.decision.prohibited_next_step:
        lines.append(f"Prohibited Next Step: {report.decision.prohibited_next_step}")
    lines.append(
        "Policy Integrity: audit did not change thresholds, weights, approvals, "
        "timing rules, allocation, or recommendation logic."
    )
    return tuple(lines)


def group_entry_timing_validation_report(
    report: EntryTimingValidationReport,
    *,
    group_by: str,
) -> tuple[str, ...]:
    counters: Counter[str] = Counter()
    if group_by == "entry-state":
        for state_item in report.state_validation:
            counters[state_item.entry_state.value] = state_item.total_candidates
    elif group_by == "profitable-rejections":
        for attribution_item in report.profitable_rejection_attribution:
            counters[attribution_item.entry_state.value] = (
                attribution_item.candidate_count
            )
    elif group_by == "winner-loser":
        for comparison_item in report.winner_loser_comparison:
            counters[comparison_item.feature] = int(
                comparison_item.absolute_difference or _ZERO
            )
    elif group_by == "incremental-value":
        for incremental_item in report.incremental_value:
            counters[incremental_item.feature_family] = incremental_item.sample_count
    elif group_by == "boundaries":
        for boundary_item in report.boundary_audit:
            counters[boundary_item.boundary] = boundary_item.close_candidate_count
    else:
        raise ValueError(f"Unsupported grouping: {group_by}")
    return tuple(f"- {key}: {value}" for key, value in sorted(counters.items()))


def export_entry_timing_validation_json(
    report: EntryTimingValidationReport,
    path: Path,
) -> None:
    path.write_text(json.dumps(_report_dict(report), indent=2) + "\n", encoding="utf-8")


def export_entry_timing_validation_csv(
    report: EntryTimingValidationReport,
    path: Path,
) -> None:
    rows: list[dict[str, object]] = []
    for state_item in report.state_validation:
        rows.append({"section": "state", **_state_dict(state_item)})
    for attribution_item in report.profitable_rejection_attribution:
        rows.append(
            {
                "section": "profitable_rejection",
                **_attribution_dict(attribution_item),
            }
        )
    for incremental_item in report.incremental_value:
        rows.append({"section": "incremental", **_incremental_dict(incremental_item)})
    for boundary_item in report.boundary_audit:
        rows.append({"section": "boundary", **_boundary_dict(boundary_item)})
    _write_csv(tuple(rows), path)


def export_approval_baseline_json(
    comparison: ApprovalBaselineComparison,
    path: Path,
) -> None:
    path.write_text(
        json.dumps(_baseline_dict(comparison), indent=2) + "\n",
        encoding="utf-8",
    )


def export_approval_baseline_csv(
    comparison: ApprovalBaselineComparison,
    path: Path,
) -> None:
    _write_csv(tuple(_source_dict(source) for source in comparison.sources), path)


def _baseline_conclusion(
    sources: tuple[ApprovalBaselineSource, ...],
) -> ApprovalBaselineConclusion:
    if not sources:
        return ApprovalBaselineConclusion.APPROVAL_BASELINE_UNAVAILABLE
    candidate_counts = {source.candidate_count for source in sources}
    filters = {source.filters_applied for source in sources}
    concepts = {source.approval_concept for source in sources}
    approval_counts = {source.approval_count for source in sources}
    if len(candidate_counts) > 1:
        return ApprovalBaselineConclusion.DIFFERENT_REPLAY_UNIVERSES
    if len(filters) > 1:
        return ApprovalBaselineConclusion.DIFFERENT_REPLAY_FILTERS
    if len(concepts) > 1:
        return ApprovalBaselineConclusion.DIFFERENT_APPROVAL_CONCEPTS
    if len(approval_counts) > 1:
        return ApprovalBaselineConclusion.APPROVAL_BASELINE_INCONSISTENT
    return ApprovalBaselineConclusion.APPROVAL_BASELINES_RECONCILED


def _baseline_explanation(
    sources: tuple[ApprovalBaselineSource, ...],
    conclusion: ApprovalBaselineConclusion,
) -> str:
    if conclusion is ApprovalBaselineConclusion.DIFFERENT_APPROVAL_CONCEPTS:
        return (
            "The counts differ because strict institutional approval and recorded "
            "raw deployment approval are different approval concepts."
        )
    if conclusion is ApprovalBaselineConclusion.APPROVAL_BASELINES_RECONCILED:
        return "The compared approval counts use the same concept and match."
    if conclusion is ApprovalBaselineConclusion.DIFFERENT_REPLAY_UNIVERSES:
        return "The compared diagnostics use different candidate universes."
    if conclusion is ApprovalBaselineConclusion.DIFFERENT_REPLAY_FILTERS:
        return "The compared diagnostics applied different filters."
    if conclusion is ApprovalBaselineConclusion.APPROVAL_BASELINE_INCONSISTENT:
        return "The same approval concept produced different counts."
    return "Approval baseline data is unavailable."


def _state_validation(
    rows: tuple[EntryTimingOutcomeRow, ...],
    config: EntryTimingValidationConfig,
) -> tuple[EntryStateValidationStats, ...]:
    result = []
    for state in EntryTimingState:
        state_rows = tuple(row for row in rows if row.assessment.entry_state is state)
        if not state_rows:
            result.append(_empty_state(state))
            continue
        completed = tuple(row for row in state_rows if row.completed_outcome)
        returns = tuple(row.forward_return for row in completed)
        winners = tuple(row for row in completed if row.profitable)
        losers = tuple(
            row
            for row in completed
            if row.forward_return is not None and row.forward_return < _ZERO
        )
        flat = tuple(
            row
            for row in completed
            if row.forward_return is not None and row.forward_return == _ZERO
        )
        result.append(
            EntryStateValidationStats(
                entry_state=state,
                total_candidates=len(state_rows),
                completed_outcomes=len(completed),
                winners=len(winners),
                losers=len(losers),
                flat_outcomes=len(flat),
                success_rate=_rate(len(winners), len(completed)),
                failure_rate=_rate(len(losers), len(completed)),
                mean_return=_average(returns),
                median_return=_median(returns),
                trimmed_mean_return=_trimmed_mean(
                    returns,
                    config.trimmed_mean_fraction,
                ),
                min_return=_min(returns),
                max_return=_max(returns),
                return_quartiles=_quartiles(returns),
                standard_deviation=_stddev(returns),
                average_mae=_average(tuple(row.mae for row in completed)),
                average_mfe=_average(tuple(row.mfe for row in completed)),
                stop_hit_rate=_rate(
                    sum(1 for row in completed if row.stop_hit),
                    len(completed),
                ),
                target_1_hit_rate=_rate(
                    sum(1 for row in completed if row.target_1_hit),
                    len(completed),
                ),
                target_2_hit_rate=_rate(
                    sum(1 for row in completed if row.target_2_hit),
                    len(completed),
                ),
                average_realised_reward_risk=_average(
                    tuple(_realised_reward_risk(row) for row in completed)
                ),
                average_planned_reward_risk=_average(
                    tuple(row.assessment.reward_risk for row in completed)
                ),
                average_stop_distance=_average(
                    tuple(row.assessment.stop_distance_pct for row in completed)
                ),
                median_stop_distance=_median(
                    tuple(row.assessment.stop_distance_pct for row in completed)
                ),
                average_support_distance=_average(
                    tuple(row.assessment.distance_from_support_pct for row in completed)
                ),
                average_price_extension=_average(
                    tuple(row.assessment.distance_from_support_atr for row in completed)
                ),
                average_timing_score=_average(
                    tuple(row.assessment.timing_score for row in completed)
                ),
                median_timing_score=_median(
                    tuple(row.assessment.timing_score for row in completed)
                ),
                average_timing_confidence=_average(
                    tuple(
                        _confidence_score(row.assessment.timing_confidence)
                        for row in completed
                    )
                ),
                insufficient_evidence=len(completed) < config.minimum_state_sample,
            )
        )
    return tuple(result)


def _empty_state(state: EntryTimingState) -> EntryStateValidationStats:
    return EntryStateValidationStats(
        entry_state=state,
        total_candidates=0,
        completed_outcomes=0,
        winners=0,
        losers=0,
        flat_outcomes=0,
        success_rate=None,
        failure_rate=None,
        mean_return=None,
        median_return=None,
        trimmed_mean_return=None,
        min_return=None,
        max_return=None,
        return_quartiles=(None, None, None),
        standard_deviation=None,
        average_mae=None,
        average_mfe=None,
        stop_hit_rate=None,
        target_1_hit_rate=None,
        target_2_hit_rate=None,
        average_realised_reward_risk=None,
        average_planned_reward_risk=None,
        average_stop_distance=None,
        median_stop_distance=None,
        average_support_distance=None,
        average_price_extension=None,
        average_timing_score=None,
        median_timing_score=None,
        average_timing_confidence=None,
        insufficient_evidence=True,
    )


def _profitable_attribution(
    profitable_rows: tuple[EntryTimingOutcomeRow, ...],
    all_rows: tuple[EntryTimingOutcomeRow, ...],
) -> tuple[ProfitableRejectionTimingAttribution, ...]:
    total = len(profitable_rows)
    near_ids = _near_approval_ids(all_rows)
    material_ids = _material_rejection_ids(all_rows)
    rows = []
    for state in EntryTimingState:
        state_rows = tuple(
            row for row in profitable_rows if row.assessment.entry_state is state
        )
        failed = tuple(
            reason
            for row in state_rows
            for reason in (
                (row.primary_rejection_reason,) if row.primary_rejection_reason else ()
            )
        )
        category = _attribution_category(state, state_rows)
        rows.append(
            ProfitableRejectionTimingAttribution(
                entry_state=state,
                candidate_count=len(state_rows),
                percentage_of_profitable_rejections=_rate(len(state_rows), total),
                average_return=_average(
                    tuple(row.forward_return for row in state_rows)
                ),
                median_return=_median(tuple(row.forward_return for row in state_rows)),
                average_timing_score=_average(
                    tuple(row.assessment.timing_score for row in state_rows)
                ),
                average_stop_distance=_average(
                    tuple(row.assessment.stop_distance_pct for row in state_rows)
                ),
                average_support_distance=_average(
                    tuple(
                        row.assessment.distance_from_support_pct for row in state_rows
                    )
                ),
                average_reward_risk=_average(
                    tuple(row.assessment.reward_risk for row in state_rows)
                ),
                primary_rejection_criterion=_mode(failed),
                failed_criteria=tuple(sorted(set(failed))),
                average_failed_gate_count=_average(
                    tuple(
                        Decimal(1 if row.primary_rejection_reason else 0)
                        for row in state_rows
                    )
                ),
                near_approval_count=sum(
                    1 for row in state_rows if row.candidate_id in near_ids
                ),
                materially_rejected_count=sum(
                    1 for row in state_rows if row.candidate_id in material_ids
                ),
                category=category,
            )
        )
    return tuple(rows)


def _near_approval_ids(rows: tuple[EntryTimingOutcomeRow, ...]) -> set[str]:
    return {
        row.candidate_id
        for row in rows
        if row.assessment.timing_score >= Decimal("80")
        and row.assessment.stop_distance_pct is not None
        and row.assessment.stop_distance_pct <= Decimal("10")
    }


def _material_rejection_ids(rows: tuple[EntryTimingOutcomeRow, ...]) -> set[str]:
    return {
        row.candidate_id
        for row in rows
        if row.assessment.stop_distance_pct is None
        or row.assessment.stop_distance_pct > Decimal("10")
        or row.assessment.timing_score < Decimal("55")
    }


def _winner_loser_audit(
    rows: tuple[EntryTimingOutcomeRow, ...],
) -> tuple[WinnerLoserAuditComparison, ...]:
    features = (
        ("timing_score", lambda row: row.assessment.timing_score),
        (
            "timing_confidence",
            lambda row: _confidence_score(row.assessment.timing_confidence),
        ),
        ("stop_distance", lambda row: row.assessment.stop_distance_pct),
        ("support_distance", lambda row: row.assessment.distance_from_support_pct),
        ("price_extension", lambda row: row.assessment.distance_from_support_atr),
        ("reward_risk", lambda row: row.assessment.reward_risk),
        ("setup_freshness", lambda row: _decimal_int(row.assessment.setup_age_bars)),
    )
    completed = tuple(row for row in rows if row.completed_outcome)
    result = []
    for name, getter in features:
        winners: list[Decimal] = []
        losers: list[Decimal] = []
        missing = 0
        for row in completed:
            value = getter(row)
            if value is None:
                missing += 1
            elif row.profitable:
                winners.append(value)
            else:
                losers.append(value)
        winner_mean = _average(tuple(winners))
        loser_mean = _average(tuple(losers))
        result.append(
            WinnerLoserAuditComparison(
                feature=name,
                winner_mean=winner_mean,
                loser_mean=loser_mean,
                winner_median=_median(tuple(winners)),
                loser_median=_median(tuple(losers)),
                absolute_difference=_diff(winner_mean, loser_mean),
                normalized_difference=_effect_size(tuple(winners), tuple(losers)),
                winner_count=len(winners),
                loser_count=len(losers),
                missing_count=missing,
            )
        )
    return tuple(result)


def _incremental_value(
    rows: tuple[EntryTimingOutcomeRow, ...],
    config: EntryTimingValidationConfig,
) -> tuple[IncrementalValueDiagnostic, ...]:
    completed = tuple(row for row in rows if row.completed_outcome)
    diagnostics = (
        _feature_spread("stop distance only", completed, _stop_bucket),
        _feature_spread("planned reward/risk only", completed, _reward_bucket),
        _feature_spread("price extension only", completed, _extension_bucket),
        _feature_spread(
            "entry state only",
            completed,
            lambda row: row.assessment.entry_state.value,
        ),
        _feature_spread("timing score only", completed, _timing_score_bucket),
        _feature_spread("combined timing features", completed, _combined_timing_bucket),
        _feature_spread("non-timing evidence features", completed, _non_timing_bucket),
        _feature_spread(
            "non-timing evidence plus timing features",
            completed,
            _non_timing_plus_timing_bucket,
        ),
    )
    stop_spread = diagnostics[0].success_spread or _ZERO
    timing_spread = diagnostics[4].success_spread or _ZERO
    result = []
    for item in diagnostics:
        if item.sample_count < config.minimum_state_sample:
            conclusion = (
                IncrementalValueConclusion.INSUFFICIENT_EVIDENCE_FOR_INCREMENTAL_VALUE
            )
        elif (
            item.feature_family == "timing score only"
            and timing_spread > stop_spread + Decimal("0.05")
        ):
            conclusion = IncrementalValueConclusion.TIMING_ADDS_INCREMENTAL_INFORMATION
        elif item.feature_family == "timing score only" and abs(
            timing_spread - stop_spread
        ) <= Decimal("0.03"):
            conclusion = IncrementalValueConclusion.TIMING_DUPLICATES_STOP_DISTANCE
        elif (
            item.feature_family == "entry state only"
            and item.success_spread
            and item.success_spread >= Decimal("0.10")
        ):
            conclusion = IncrementalValueConclusion.TIMING_HAS_WEAK_INCREMENTAL_VALUE
        else:
            conclusion = IncrementalValueConclusion.TIMING_HAS_WEAK_INCREMENTAL_VALUE
        result.append(
            IncrementalValueDiagnostic(
                feature_family=item.feature_family,
                success_spread=item.success_spread,
                return_spread=item.return_spread,
                bucket_count=item.bucket_count,
                sample_count=item.sample_count,
                conclusion=conclusion,
            )
        )
    return tuple(result)


def _feature_spread(
    name: str,
    rows: tuple[EntryTimingOutcomeRow, ...],
    bucket_fn: Callable[[EntryTimingOutcomeRow], str],
) -> IncrementalValueDiagnostic:
    grouped: dict[str, list[EntryTimingOutcomeRow]] = defaultdict(list)
    for row in rows:
        grouped[bucket_fn(row)].append(row)
    rates = []
    returns = []
    for bucket_rows in grouped.values():
        if len(bucket_rows) < 2:
            continue
        rates.append(
            _rate(sum(1 for row in bucket_rows if row.profitable), len(bucket_rows))
        )
        returns.append(_average(tuple(row.forward_return for row in bucket_rows)))
    present_rates = tuple(rate for rate in rates if rate is not None)
    present_returns = tuple(value for value in returns if value is not None)
    return IncrementalValueDiagnostic(
        feature_family=name,
        success_spread=_spread(present_rates),
        return_spread=_spread(present_returns),
        bucket_count=len(grouped),
        sample_count=len(rows),
        conclusion=IncrementalValueConclusion.TIMING_HAS_WEAK_INCREMENTAL_VALUE,
    )


def _boundary_audit(
    rows: tuple[EntryTimingOutcomeRow, ...],
    config: EntryTimingValidationConfig,
) -> tuple[BoundaryAuditResult, ...]:
    specs = (
        (
            "SETUP_FORMING vs EARLY_ENTRY",
            (EntryTimingState.SETUP_FORMING, EntryTimingState.EARLY_ENTRY),
            "support distance",
            config.early_support_distance_pct,
        ),
        (
            "EARLY_ENTRY vs AGGRESSIVE_ENTRY",
            (EntryTimingState.EARLY_ENTRY, EntryTimingState.AGGRESSIVE_ENTRY),
            "reward/risk",
            Decimal("1.50"),
        ),
        (
            "AGGRESSIVE_ENTRY vs PREFERRED_ENTRY",
            (EntryTimingState.AGGRESSIVE_ENTRY, EntryTimingState.PREFERRED_ENTRY),
            "support distance",
            config.preferred_support_distance_pct,
        ),
        (
            "PREFERRED_ENTRY vs CONFIRMATION_ENTRY",
            (EntryTimingState.PREFERRED_ENTRY, EntryTimingState.CONFIRMATION_ENTRY),
            "volume confirmation",
            Decimal("1.50"),
        ),
        (
            "CONFIRMATION_ENTRY vs EXTENDED_ENTRY",
            (EntryTimingState.CONFIRMATION_ENTRY, EntryTimingState.EXTENDED_ENTRY),
            "support distance",
            config.extended_support_distance_pct,
        ),
        (
            "EXTENDED_ENTRY vs LATE_ENTRY",
            (EntryTimingState.EXTENDED_ENTRY, EntryTimingState.LATE_ENTRY),
            "stop distance",
            Decimal("18"),
        ),
        (
            "LATE_ENTRY vs INVALID_ENTRY",
            (EntryTimingState.LATE_ENTRY, EntryTimingState.INVALID_ENTRY),
            "price versus stop",
            Decimal("0"),
        ),
    )
    results = []
    for name, states, variable, threshold in specs:
        close = tuple(
            row
            for row in rows
            if row.assessment.entry_state in states
            and _boundary_distance(row, variable, threshold) is not None
            and abs(_boundary_distance(row, variable, threshold) or _ZERO)
            <= config.boundary_distance_pct
        )
        left = tuple(row for row in close if row.assessment.entry_state is states[0])
        right = tuple(row for row in close if row.assessment.entry_state is states[1])
        left_rate = _success_rate(left)
        right_rate = _success_rate(right)
        flag = _boundary_flag(left, right, left_rate, right_rate, config)
        results.append(
            BoundaryAuditResult(
                boundary=name,
                controlling_variables=(variable,),
                threshold_values=(str(threshold),),
                close_candidate_count=len(close),
                left_success_rate=left_rate,
                right_success_rate=right_rate,
                left_mean_return=_average(tuple(row.forward_return for row in left)),
                right_mean_return=_average(tuple(row.forward_return for row in right)),
                left_median_return=_median(tuple(row.forward_return for row in left)),
                right_median_return=_median(tuple(row.forward_return for row in right)),
                distance_from_threshold=_average(
                    tuple(_boundary_distance(row, variable, threshold) for row in close)
                ),
                flag=flag,
            )
        )
    return tuple(results)


def _decision(
    *,
    baseline: ApprovalBaselineComparison,
    state_validation: tuple[EntryStateValidationStats, ...],
    attribution: tuple[ProfitableRejectionTimingAttribution, ...],
    incremental: tuple[IncrementalValueDiagnostic, ...],
    boundaries: tuple[BoundaryAuditResult, ...],
    profitable_rows: tuple[EntryTimingOutcomeRow, ...],
    config: EntryTimingValidationConfig,
) -> TimingAuditDecision:
    secondary: list[TimingAuditConclusion] = []
    contradictions: list[str] = []
    caveats: list[str] = []
    preferred = _state_stat(state_validation, EntryTimingState.PREFERRED_ENTRY)
    late = _state_stat(state_validation, EntryTimingState.LATE_ENTRY)
    preferred_supported = (
        preferred.completed_outcomes >= config.minimum_state_sample
        and preferred.success_rate is not None
    )
    late_supported = (
        late.completed_outcomes >= config.minimum_state_sample
        and late.success_rate is not None
    )
    preferred_late_spread = None
    if (
        preferred_supported
        and late_supported
        and preferred.success_rate is not None
        and late.success_rate is not None
    ):
        preferred_late_spread = preferred.success_rate - late.success_rate
    acceptable_count = sum(
        item.candidate_count
        for item in attribution
        if item.entry_state
        in {EntryTimingState.PREFERRED_ENTRY, EntryTimingState.CONFIRMATION_ENTRY}
    )
    acceptable_rate = _rate(acceptable_count, len(profitable_rows))
    timing_incremental = any(
        item.conclusion
        is IncrementalValueConclusion.TIMING_ADDS_INCREMENTAL_INFORMATION
        for item in incremental
    )
    unstable_boundaries = tuple(
        item
        for item in boundaries
        if item.flag
        in {
            BoundaryFlag.SENSITIVE_BOUNDARY,
            BoundaryFlag.POSSIBLE_CLASSIFICATION_DISCONTINUITY,
        }
    )
    if baseline.conclusion is ApprovalBaselineConclusion.APPROVAL_BASELINE_INCONSISTENT:
        primary = TimingAuditConclusion.APPROVAL_BASELINE_INCONSISTENT
        recommendation = NextMilestoneRecommendation.RECONCILE_APPROVAL_PIPELINE_FIRST
    elif preferred_late_spread is not None and preferred_late_spread >= Decimal("0.10"):
        primary = TimingAuditConclusion.TIMING_SEPARATES_OUTCOMES
        recommendation = NextMilestoneRecommendation.INVESTIGATE_NON_ENTRY_GATES
    elif acceptable_rate is not None and acceptable_rate >= Decimal("0.30"):
        primary = TimingAuditConclusion.ACCEPTABLE_TIMING_NON_ENTRY_GATES_REJECT
        recommendation = NextMilestoneRecommendation.INVESTIGATE_NON_ENTRY_GATES
    elif not preferred_supported:
        primary = TimingAuditConclusion.INSUFFICIENT_STATE_SAMPLE
        recommendation = NextMilestoneRecommendation.COLLECT_MORE_REPLAY_EVIDENCE
    else:
        primary = TimingAuditConclusion.TIMING_MODEL_NOT_CALIBRATED
        recommendation = NextMilestoneRecommendation.REFINE_ENTRY_TIMING_CLASSIFICATION
    if not timing_incremental:
        secondary.append(TimingAuditConclusion.TIMING_DUPLICATES_STOP_DISTANCE)
    if unstable_boundaries:
        secondary.append(TimingAuditConclusion.ENTRY_STATE_BOUNDARIES_UNSTABLE)
    if preferred.success_rate is not None and preferred.success_rate < Decimal("0.30"):
        secondary.append(
            TimingAuditConclusion.PREFERRED_STATE_NOT_EMPIRICALLY_SUPPORTED
        )
    if acceptable_rate is not None and acceptable_rate >= Decimal("0.30"):
        secondary.append(TimingAuditConclusion.ACCEPTABLE_TIMING_NON_ENTRY_GATES_REJECT)
    if baseline.conclusion is ApprovalBaselineConclusion.DIFFERENT_APPROVAL_CONCEPTS:
        caveats.append(
            "Zero strict approvals and raw approvals are different concepts."
        )
    if preferred_late_spread is not None and preferred_late_spread > _ZERO:
        contradictions.append(
            "Timing separates late entries but preferred entries still lose on average."
        )
    blocks_optimization = (
        recommendation
        is not NextMilestoneRecommendation.PROCEED_TO_DYNAMIC_ENTRY_ZONE_OPTIMIZATION
    )
    prohibited = (
        "Dynamic Entry Zone Optimization is not recommended until approval "
        "concepts and non-entry gate attribution are fully reconciled."
        if blocks_optimization
        else None
    )
    metrics = (
        f"Preferred success rate: {_pct_text(preferred.success_rate)}.",
        f"Late success rate: {_pct_text(late.success_rate)}.",
        f"Preferred-minus-late spread: {_metric(preferred_late_spread)}.",
        "Acceptable-timing share of profitable rejections: "
        f"{_pct_text(acceptable_rate)}.",
    )
    return TimingAuditDecision(
        primary_conclusion=primary,
        secondary_conclusions=tuple(dict.fromkeys(secondary)),
        supporting_metrics=metrics,
        contradictions=tuple(contradictions),
        caveats=tuple(caveats),
        recommended_next_milestone=recommendation,
        prohibited_next_step=prohibited,
    )


def _state_stat(
    stats: tuple[EntryStateValidationStats, ...],
    state: EntryTimingState,
) -> EntryStateValidationStats:
    return next(item for item in stats if item.entry_state is state)


def _date_range(
    records: tuple[CandidateDecisionRecord, ...],
) -> tuple[date | None, date | None]:
    if not records:
        return (None, None)
    dates = tuple(record.evaluation_date for record in records)
    return (min(dates), max(dates))


def _confidence_score(value: TimingConfidence) -> Decimal:
    return {
        TimingConfidence.HIGH: Decimal("3"),
        TimingConfidence.MEDIUM: Decimal("2"),
        TimingConfidence.LOW: Decimal("1"),
    }[value]


def _attribution_category(
    state: EntryTimingState,
    rows: tuple[EntryTimingOutcomeRow, ...],
) -> str:
    if state in {EntryTimingState.PREFERRED_ENTRY, EntryTimingState.CONFIRMATION_ENTRY}:
        has_entry_failure = any(
            row.assessment.stop_distance_pct is None
            or row.assessment.stop_distance_pct > Decimal("10")
            for row in rows
        )
        return (
            "acceptable timing with both entry and non-entry failures"
            if has_entry_failure
            else "acceptable timing with only non-entry failures"
        )
    if state in {EntryTimingState.LATE_ENTRY, EntryTimingState.EXTENDED_ENTRY}:
        return "poor timing with non-entry failures"
    if state is EntryTimingState.ENTRY_UNAVAILABLE:
        return "timing unavailable"
    if state is EntryTimingState.INVALID_ENTRY:
        return "invalid entry"
    return "setup forming or conditional timing"


def _stop_bucket(row: EntryTimingOutcomeRow) -> str:
    value = row.assessment.stop_distance_pct
    if value is None:
        return "unavailable"
    if value <= Decimal("10"):
        return "<=10"
    if value <= Decimal("18"):
        return "10-18"
    return ">18"


def _reward_bucket(row: EntryTimingOutcomeRow) -> str:
    value = row.assessment.reward_risk
    if value is None:
        return "unavailable"
    if value >= Decimal("3"):
        return ">=3R"
    if value >= Decimal("2"):
        return "2-3R"
    return "<2R"


def _extension_bucket(row: EntryTimingOutcomeRow) -> str:
    return row.assessment.price_extension_state.value


def _timing_score_bucket(row: EntryTimingOutcomeRow) -> str:
    score = row.assessment.timing_score
    if score >= Decimal("85"):
        return "85-100"
    if score >= Decimal("70"):
        return "70-84"
    if score >= Decimal("55"):
        return "55-69"
    if score >= Decimal("40"):
        return "40-54"
    return "<40"


def _combined_timing_bucket(row: EntryTimingOutcomeRow) -> str:
    return f"{row.assessment.entry_state.value}|{_timing_score_bucket(row)}"


def _non_timing_bucket(row: EntryTimingOutcomeRow) -> str:
    if row.approved:
        return "raw-approved"
    if row.primary_rejection_reason:
        return row.primary_rejection_reason
    return "raw-rejected"


def _non_timing_plus_timing_bucket(row: EntryTimingOutcomeRow) -> str:
    return f"{_non_timing_bucket(row)}|{row.assessment.entry_state.value}"


def _boundary_distance(
    row: EntryTimingOutcomeRow,
    variable: str,
    threshold: Decimal,
) -> Decimal | None:
    if variable == "support distance":
        value = row.assessment.distance_from_support_pct
    elif variable == "reward/risk":
        value = row.assessment.reward_risk
    elif variable == "volume confirmation":
        value = (
            Decimal("1.5")
            if "VOLUME_CONFIRMS"
            in {reason.value for reason in row.assessment.timing_reasons}
            else Decimal("0")
        )
    elif variable == "stop distance":
        value = row.assessment.stop_distance_pct
    elif variable == "price versus stop":
        price = row.assessment.current_price
        stop = row.assessment.structural_support
        value = None if price is None or stop is None else price - stop
    else:
        value = None
    return None if value is None else (value - threshold).quantize(_TWO)


def _boundary_flag(
    left: tuple[EntryTimingOutcomeRow, ...],
    right: tuple[EntryTimingOutcomeRow, ...],
    left_rate: Decimal | None,
    right_rate: Decimal | None,
    config: EntryTimingValidationConfig,
) -> BoundaryFlag:
    if len(left) + len(right) < config.minimum_boundary_sample:
        return BoundaryFlag.INSUFFICIENT_BOUNDARY_SAMPLE
    if left_rate is None or right_rate is None:
        return BoundaryFlag.INSUFFICIENT_BOUNDARY_SAMPLE
    if abs(left_rate - right_rate) <= Decimal("0.03"):
        return BoundaryFlag.OVERLAPPING_OUTCOMES
    if abs(left_rate - right_rate) >= Decimal("0.20"):
        return BoundaryFlag.SENSITIVE_BOUNDARY
    return BoundaryFlag.STABLE_BOUNDARY


def _success_rate(rows: tuple[EntryTimingOutcomeRow, ...]) -> Decimal | None:
    completed = tuple(row for row in rows if row.completed_outcome)
    return _rate(sum(1 for row in completed if row.profitable), len(completed))


def _realised_reward_risk(row: EntryTimingOutcomeRow) -> Decimal | None:
    if row.forward_return is None:
        return None
    stop_distance = row.assessment.stop_distance_pct
    if stop_distance is None or stop_distance <= _ZERO:
        return None
    return (row.forward_return / stop_distance).quantize(_FOUR)


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


def _trimmed_mean(
    values: tuple[Decimal | None, ...],
    trim_fraction: Decimal,
) -> Decimal | None:
    present = tuple(sorted(value for value in values if value is not None))
    if not present:
        return None
    trim = int((Decimal(len(present)) * trim_fraction).to_integral_value())
    if trim <= 0 or len(present) <= trim * 2:
        trimmed = present
    else:
        trimmed = present[trim:-trim]
    return _average(trimmed)


def _quartiles(
    values: tuple[Decimal | None, ...],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    present = tuple(sorted(value for value in values if value is not None))
    if not present:
        return (None, None, None)
    return (
        present[int((len(present) - 1) * Decimal("0.25"))],
        present[int((len(present) - 1) * Decimal("0.50"))],
        present[int((len(present) - 1) * Decimal("0.75"))],
    )


def _stddev(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    if len(present) < 2:
        return None
    avg = _average(present)
    if avg is None:
        return None
    variance = sum((value - avg) ** 2 for value in present) / Decimal(len(present))
    return Decimal(str(variance.sqrt())).quantize(_FOUR)


def _min(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    return min(present) if present else None


def _max(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    return max(present) if present else None


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(_FOUR)


def _diff(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return (left - right).quantize(_FOUR)


def _effect_size(
    winners: tuple[Decimal, ...],
    losers: tuple[Decimal, ...],
) -> Decimal | None:
    if len(winners) < 2 or len(losers) < 2:
        return None
    win_mean = _average(winners)
    lose_mean = _average(losers)
    win_std = _stddev(winners)
    lose_std = _stddev(losers)
    if win_mean is None or lose_mean is None or win_std is None or lose_std is None:
        return None
    pooled = ((win_std + lose_std) / Decimal("2")).quantize(_FOUR)
    if pooled == _ZERO:
        return None
    return ((win_mean - lose_mean) / pooled).quantize(_FOUR)


def _spread(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (max(values) - min(values)).quantize(_FOUR)


def _mode(values: tuple[str, ...]) -> str | None:
    if not values:
        return None
    return sorted(Counter(values).items(), key=lambda item: (-item[1], item[0]))[0][0]


def _decimal_int(value: int | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _state_lines(stats: tuple[EntryStateValidationStats, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.entry_state.value}: total {item.total_candidates}, completed "
        f"{item.completed_outcomes}, winners {item.winners}, success "
        f"{_pct_text(item.success_rate)}, mean {_metric(item.mean_return)}, "
        f"median {_metric(item.median_return)}, trimmed "
        f"{_metric(item.trimmed_mean_return)}, stop "
        f"{_metric(item.average_stop_distance)}, timing "
        f"{_metric(item.average_timing_score)}"
        + (" — INSUFFICIENT EVIDENCE" if item.insufficient_evidence else "")
        for item in stats
    )


def _attribution_lines(
    rows: tuple[ProfitableRejectionTimingAttribution, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.entry_state.value}: {item.candidate_count} "
        f"({_pct_text(item.percentage_of_profitable_rejections)}), avg return "
        f"{_metric(item.average_return)}, avg timing "
        f"{_metric(item.average_timing_score)}, category {item.category}"
        for item in rows
    )


def _winner_loser_lines(
    rows: tuple[WinnerLoserAuditComparison, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.feature}: winner mean {_metric(item.winner_mean)}, loser mean "
        f"{_metric(item.loser_mean)}, diff {_metric(item.absolute_difference)}, "
        f"effect {_metric(item.normalized_difference)}, missing {item.missing_count}"
        for item in rows
    )


def _incremental_lines(
    rows: tuple[IncrementalValueDiagnostic, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.feature_family}: success spread {_metric(item.success_spread)}, "
        f"return spread {_metric(item.return_spread)}, buckets {item.bucket_count}, "
        f"conclusion {item.conclusion.value}"
        for item in rows
    )


def _boundary_lines(rows: tuple[BoundaryAuditResult, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.boundary}: close {item.close_candidate_count}, left "
        f"{_pct_text(item.left_success_rate)}, right "
        f"{_pct_text(item.right_success_rate)}, flag {item.flag.value}"
        for item in rows
    )


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _pct_text(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{(value * _HUNDRED).quantize(_TWO)}%"


def _state_dict(item: EntryStateValidationStats) -> dict[str, object]:
    return {
        "entry_state": item.entry_state.value,
        "total_candidates": item.total_candidates,
        "completed_outcomes": item.completed_outcomes,
        "winners": item.winners,
        "losers": item.losers,
        "success_rate": _text(item.success_rate),
        "mean_return": _text(item.mean_return),
        "median_return": _text(item.median_return),
        "trimmed_mean_return": _text(item.trimmed_mean_return),
        "standard_deviation": _text(item.standard_deviation),
        "average_stop_distance": _text(item.average_stop_distance),
        "average_timing_score": _text(item.average_timing_score),
        "insufficient_evidence": item.insufficient_evidence,
    }


def _attribution_dict(item: ProfitableRejectionTimingAttribution) -> dict[str, object]:
    return {
        "entry_state": item.entry_state.value,
        "candidate_count": item.candidate_count,
        "percentage_of_profitable_rejections": _text(
            item.percentage_of_profitable_rejections
        ),
        "average_return": _text(item.average_return),
        "median_return": _text(item.median_return),
        "average_timing_score": _text(item.average_timing_score),
        "average_stop_distance": _text(item.average_stop_distance),
        "average_reward_risk": _text(item.average_reward_risk),
        "primary_rejection_criterion": item.primary_rejection_criterion,
        "failed_criteria": list(item.failed_criteria),
        "average_failed_gate_count": _text(item.average_failed_gate_count),
        "near_approval_count": item.near_approval_count,
        "materially_rejected_count": item.materially_rejected_count,
        "category": item.category,
    }


def _incremental_dict(item: IncrementalValueDiagnostic) -> dict[str, object]:
    return {
        "feature_family": item.feature_family,
        "success_spread": _text(item.success_spread),
        "return_spread": _text(item.return_spread),
        "bucket_count": item.bucket_count,
        "sample_count": item.sample_count,
        "conclusion": item.conclusion.value,
    }


def _boundary_dict(item: BoundaryAuditResult) -> dict[str, object]:
    return {
        "boundary": item.boundary,
        "controlling_variables": list(item.controlling_variables),
        "threshold_values": list(item.threshold_values),
        "close_candidate_count": item.close_candidate_count,
        "left_success_rate": _text(item.left_success_rate),
        "right_success_rate": _text(item.right_success_rate),
        "left_mean_return": _text(item.left_mean_return),
        "right_mean_return": _text(item.right_mean_return),
        "flag": item.flag.value,
    }


def _source_dict(source: ApprovalBaselineSource) -> dict[str, object]:
    return {
        "diagnostic_name": source.diagnostic_name,
        "replay_dataset_identifier": source.replay_dataset_identifier,
        "replay_date_start": source.replay_date_range[0].isoformat()
        if source.replay_date_range[0]
        else None,
        "replay_date_end": source.replay_date_range[1].isoformat()
        if source.replay_date_range[1]
        else None,
        "candidate_universe": source.candidate_universe,
        "candidate_count": source.candidate_count,
        "completed_outcome_count": source.completed_outcome_count,
        "approval_stage": source.approval_stage,
        "approval_definition": source.approval_definition,
        "approval_concept": source.approval_concept.value,
        "approval_count": source.approval_count,
        "rejection_count": source.rejection_count,
        "missing_outcome_count": source.missing_outcome_count,
        "filters_applied": list(source.filters_applied),
    }


def _baseline_dict(comparison: ApprovalBaselineComparison) -> dict[str, object]:
    return {
        "conclusion": comparison.conclusion.value,
        "explanation": comparison.explanation,
        "sources": [_source_dict(source) for source in comparison.sources],
    }


def _report_dict(report: EntryTimingValidationReport) -> dict[str, object]:
    return {
        "candidates_evaluated": report.candidates_evaluated,
        "completed_outcomes": report.completed_outcomes,
        "profitable_rejection_count": report.profitable_rejection_count,
        "approval_count_before": report.approval_count_before,
        "approval_count_after": report.approval_count_after,
        "baseline_comparison": _baseline_dict(report.baseline_comparison),
        "state_validation": [_state_dict(item) for item in report.state_validation],
        "profitable_rejection_attribution": [
            _attribution_dict(item) for item in report.profitable_rejection_attribution
        ],
        "winner_loser_comparison": [
            {
                "feature": item.feature,
                "winner_mean": _text(item.winner_mean),
                "loser_mean": _text(item.loser_mean),
                "absolute_difference": _text(item.absolute_difference),
                "normalized_difference": _text(item.normalized_difference),
                "winner_count": item.winner_count,
                "loser_count": item.loser_count,
                "missing_count": item.missing_count,
            }
            for item in report.winner_loser_comparison
        ],
        "incremental_value": [
            _incremental_dict(item) for item in report.incremental_value
        ],
        "boundary_audit": [_boundary_dict(item) for item in report.boundary_audit],
        "primary_conclusion": report.decision.primary_conclusion.value,
        "secondary_conclusions": [
            item.value for item in report.decision.secondary_conclusions
        ],
        "recommended_next_milestone": (
            report.decision.recommended_next_milestone.value
        ),
        "prohibited_next_step": report.decision.prohibited_next_step,
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
