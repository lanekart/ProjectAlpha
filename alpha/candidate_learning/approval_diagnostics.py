from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path
from statistics import median

from alpha.candidate_learning.aggregator import is_deployment_approved
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
HistoricalContext = dict[
    tuple[str | None, str | None],
    tuple[int, Decimal | None, Decimal | None],
]


class ApprovalCriterionId(StrEnum):
    EVIDENCE_SCORE = "evidence_score"
    STOP_DISTANCE = "stop_distance"
    HISTORICAL_SAMPLES = "historical_samples"
    STRONG_EVIDENCE_EXCEPTION = "strong_evidence_exception"
    EXPECTANCY = "expectancy"
    POSTERIOR_PROBABILITY = "posterior_probability"
    ENTRY_AVAILABLE = "entry_available"
    STOP_AVAILABLE = "stop_available"
    TARGETS_AVAILABLE = "targets_available"
    ATR_AVAILABLE = "atr_available"
    DMA20_INVALIDATION_AVAILABLE = "dma20_invalidation_available"
    INSTITUTIONAL_ACCEPTANCE = "institutional_acceptance"


class ApprovalFailureSeverity(StrEnum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    MATERIAL = "material"
    CRITICAL = "critical"


class ApprovalRejectionReasonCode(StrEnum):
    INSUFFICIENT_EVIDENCE_SCORE = "insufficient_evidence_score"
    EXCESSIVE_STOP_DISTANCE = "excessive_stop_distance"
    INSUFFICIENT_HISTORICAL_SAMPLES = "insufficient_historical_samples"
    NEGATIVE_OR_WEAK_EXPECTANCY = "negative_or_weak_expectancy"
    INSUFFICIENT_POSTERIOR_PROBABILITY = "insufficient_posterior_probability"
    INCOMPLETE_ENTRY = "incomplete_entry"
    INCOMPLETE_STOP = "incomplete_stop"
    INCOMPLETE_TARGETS = "incomplete_targets"
    MISSING_ATR = "missing_atr"
    MISSING_20DMA_INVALIDATION = "missing_20dma_invalidation"
    INSTITUTIONAL_LAYER_REJECTED = "institutional_layer_rejected"
    MATERIALLY_INCOMPLETE_DATA = "materially_incomplete_data"
    MULTIPLE_MATERIAL_FAILURES = "multiple_material_failures"
    UNCLASSIFIED = "unclassified"


class ApprovalReadinessState(StrEnum):
    APPROVED = "APPROVED"
    NEAR_APPROVAL = "NEAR_APPROVAL"
    CONDITIONAL = "CONDITIONAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MATERIAL_DATA_GAP = "MATERIAL_DATA_GAP"
    STRUCTURALLY_WEAK = "STRUCTURALLY_WEAK"
    INCOMPLETE_TRADE_PLAN = "INCOMPLETE_TRADE_PLAN"


class EvidenceCompletenessState(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"


class TradePlanCompletenessState(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class ComparisonOperator(StrEnum):
    GTE = ">="
    LTE = "<="
    PRESENT = "present"
    BOOLEAN = "boolean"


@dataclass(frozen=True, slots=True)
class ApprovalDiagnosticsConfig:
    minimum_evidence_score: Decimal = Decimal("85")
    maximum_stop_distance_percent: Decimal = Decimal("10")
    minimum_historical_samples: int = 60
    minimum_expectancy: Decimal = Decimal("0.10")
    minimum_posterior_probability: Decimal = Decimal("0.52")
    near_approval_minimum_margin: Decimal = Decimal("0.92")
    conditional_minimum_margin: Decimal = Decimal("0.70")
    maximum_failed_criteria_for_near_approval: int = 1
    maximum_failed_criteria_for_conditional: int = 2
    normalized_margin_cap: Decimal = Decimal("1.25")
    nearest_candidate_limit: int = 10
    minimum_intersection_count: int = 2


@dataclass(frozen=True, slots=True)
class InstitutionalApprovalCriterionResult:
    criterion_id: ApprovalCriterionId
    display_name: str
    actual_value: str | None
    required_value: str
    comparison_operator: ComparisonOperator
    passed: bool
    applicable: bool
    failure_severity: ApprovalFailureSeverity
    failure_code: ApprovalRejectionReasonCode | None
    explanation: str
    normalized_margin: Decimal
    data_available: bool
    threshold_gap: str | None


@dataclass(frozen=True, slots=True)
class InstitutionalApprovalDiagnostic:
    symbol: str
    replay_date: date
    candidate_id: str
    final_verdict: str
    institutional_decision: str
    approved: bool
    criterion_results: tuple[InstitutionalApprovalCriterionResult, ...]
    failed_criteria: tuple[ApprovalCriterionId, ...]
    primary_rejection_reason: ApprovalRejectionReasonCode
    secondary_rejection_reasons: tuple[ApprovalRejectionReasonCode, ...]
    approval_margin: Decimal
    weakest_criterion_margin: Decimal
    failed_criteria_count: int
    material_failure_count: int
    approval_readiness: ApprovalReadinessState
    evidence_completeness: EvidenceCompletenessState
    data_gap_reasons: tuple[str, ...]
    trade_plan_completeness: TradePlanCompletenessState
    nearest_to_approval_rank: int | None
    final_score: Decimal
    matched_samples: int | None
    expectancy: Decimal | None
    posterior_probability: Decimal | None
    stop_distance_percent: Decimal | None
    setup_type: str | None
    market_regime: str | None
    sector: str | None


@dataclass(frozen=True, slots=True)
class ApprovalDiagnosticSummary:
    diagnostics: tuple[InstitutionalApprovalDiagnostic, ...]
    nearest_candidates: tuple[InstitutionalApprovalDiagnostic, ...]
    total_candidates: int
    approved_candidates: int
    rejected_candidates: int
    rejection_rate: Decimal
    failing_one_criterion: int
    failing_two_criteria: int
    failing_three_or_more_criteria: int
    criterion_counts: tuple[tuple[ApprovalCriterionId, int, Decimal], ...]
    primary_reason_counts: tuple[tuple[ApprovalRejectionReasonCode, int, Decimal], ...]
    readiness_counts: tuple[tuple[ApprovalReadinessState, int, Decimal], ...]
    criterion_intersections: tuple[tuple[str, int], ...]
    average_approval_margin: Decimal | None
    median_approval_margin: Decimal | None
    highest_approval_margin: Decimal | None
    near_approval_count: int
    data_gap_count: int
    incomplete_trade_plan_count: int


class ApprovalDiagnosticsEngine:
    def __init__(self, config: ApprovalDiagnosticsConfig | None = None) -> None:
        self.config = config or ApprovalDiagnosticsConfig()

    def build(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> ApprovalDiagnosticSummary:
        historical = _historical_context(records=records, outcomes=outcomes)
        diagnostics = tuple(
            self._diagnostic(record=record, historical=historical) for record in records
        )
        nearest = self._rank_nearest(diagnostics)
        ranked_ids = {
            item.candidate_id: index for index, item in enumerate(nearest, start=1)
        }
        ranked_diagnostics = tuple(
            _with_rank(diagnostic, ranked_ids.get(diagnostic.candidate_id))
            for diagnostic in diagnostics
        )
        return _summary(
            diagnostics=ranked_diagnostics,
            nearest_candidates=tuple(
                _with_rank(item, ranked_ids.get(item.candidate_id)) for item in nearest
            ),
            config=self.config,
        )

    def _diagnostic(
        self,
        *,
        record: CandidateDecisionRecord,
        historical: HistoricalContext,
    ) -> InstitutionalApprovalDiagnostic:
        key = (record.setup_type, record.market_regime)
        sample_count, expectancy, posterior = historical.get(key, (0, None, None))
        score = record.strategy_score
        stop_distance = _record_stop_distance(record)
        institutional_acceptance = is_deployment_approved(record)
        strong_evidence_exception = _has_strong_evidence_exception(record)
        criteria = (
            _numeric_min(
                ApprovalCriterionId.EVIDENCE_SCORE,
                "Final evidence score",
                score,
                self.config.minimum_evidence_score,
                ApprovalRejectionReasonCode.INSUFFICIENT_EVIDENCE_SCORE,
                "points",
                self.config.normalized_margin_cap,
            ),
            _numeric_max(
                ApprovalCriterionId.STOP_DISTANCE,
                "Stop distance",
                stop_distance,
                self.config.maximum_stop_distance_percent,
                ApprovalRejectionReasonCode.EXCESSIVE_STOP_DISTANCE,
                "percentage points",
                self.config.normalized_margin_cap,
            ),
            _historical_sample_criterion(
                ApprovalCriterionId.HISTORICAL_SAMPLES,
                "Matched historical samples",
                sample_count,
                self.config.minimum_historical_samples,
                self.config.normalized_margin_cap,
                strong_evidence_exception=strong_evidence_exception,
            ),
            _binary(
                ApprovalCriterionId.STRONG_EVIDENCE_EXCEPTION,
                "Strong-evidence exception",
                strong_evidence_exception,
                ApprovalRejectionReasonCode.UNCLASSIFIED,
                applicable=strong_evidence_exception,
                explanation=(
                    "Strong-evidence exception present."
                    if strong_evidence_exception
                    else "Strong-evidence exception not present."
                ),
            ),
            _numeric_min(
                ApprovalCriterionId.EXPECTANCY,
                "Historical expectancy",
                expectancy,
                self.config.minimum_expectancy,
                ApprovalRejectionReasonCode.NEGATIVE_OR_WEAK_EXPECTANCY,
                "expectancy",
                self.config.normalized_margin_cap,
            ),
            _numeric_min(
                ApprovalCriterionId.POSTERIOR_PROBABILITY,
                "Posterior probability",
                posterior,
                self.config.minimum_posterior_probability,
                ApprovalRejectionReasonCode.INSUFFICIENT_POSTERIOR_PROBABILITY,
                "probability points",
                self.config.normalized_margin_cap,
            ),
            _presence(
                ApprovalCriterionId.ENTRY_AVAILABLE,
                "Entry",
                record.confirmation_entry or record.entry_zone_high,
                ApprovalRejectionReasonCode.INCOMPLETE_ENTRY,
            ),
            _presence(
                ApprovalCriterionId.STOP_AVAILABLE,
                "Stop",
                record.risk_stop,
                ApprovalRejectionReasonCode.INCOMPLETE_STOP,
            ),
            _binary(
                ApprovalCriterionId.TARGETS_AVAILABLE,
                "Targets",
                record.target_1 is not None
                and record.target_2 is not None
                and record.target_3 is not None,
                ApprovalRejectionReasonCode.INCOMPLETE_TARGETS,
            ),
            _binary(
                ApprovalCriterionId.ATR_AVAILABLE,
                "ATR",
                _has_atr_text(record.trailing_stop_plan),
                ApprovalRejectionReasonCode.MISSING_ATR,
                explanation="ATR must be present in the trailing stop plan.",
            ),
            _binary(
                ApprovalCriterionId.DMA20_INVALIDATION_AVAILABLE,
                "20-DMA invalidation",
                _has_20dma_text(record.explanation),
                ApprovalRejectionReasonCode.MISSING_20DMA_INVALIDATION,
                explanation="20-DMA invalidation must be recorded.",
            ),
            _binary(
                ApprovalCriterionId.INSTITUTIONAL_ACCEPTANCE,
                "Institutional decision acceptance",
                institutional_acceptance,
                ApprovalRejectionReasonCode.INSTITUTIONAL_LAYER_REJECTED,
            ),
        )
        failed = tuple(
            result.criterion_id
            for result in criteria
            if result.applicable and not result.passed
        )
        reasons = _failure_reasons(criteria)
        material_count = sum(
            1
            for result in criteria
            if result.failure_severity
            in {ApprovalFailureSeverity.MATERIAL, ApprovalFailureSeverity.CRITICAL}
        )
        primary = _primary_reason(reasons, material_count)
        secondary = tuple(reason for reason in reasons if reason != primary)
        margin, weakest = _approval_margin(criteria)
        evidence_state = _evidence_state(sample_count, expectancy, posterior)
        plan_state = _trade_plan_state(criteria)
        data_gaps = tuple(
            result.explanation for result in criteria if not result.data_available
        )
        readiness = _readiness(
            approved=institutional_acceptance,
            failed_count=len(failed),
            material_count=material_count,
            margin=margin,
            evidence_state=evidence_state,
            trade_plan_state=plan_state,
            data_gaps=data_gaps,
            config=self.config,
        )
        return InstitutionalApprovalDiagnostic(
            symbol=record.symbol,
            replay_date=record.evaluation_date,
            candidate_id=record.candidate_id,
            final_verdict=record.final_verdict,
            institutional_decision="ACCEPT" if institutional_acceptance else "REJECT",
            approved=institutional_acceptance,
            criterion_results=criteria,
            failed_criteria=failed,
            primary_rejection_reason=primary,
            secondary_rejection_reasons=secondary,
            approval_margin=margin,
            weakest_criterion_margin=weakest,
            failed_criteria_count=len(failed),
            material_failure_count=material_count,
            approval_readiness=readiness,
            evidence_completeness=evidence_state,
            data_gap_reasons=data_gaps,
            trade_plan_completeness=plan_state,
            nearest_to_approval_rank=None,
            final_score=score,
            matched_samples=sample_count,
            expectancy=expectancy,
            posterior_probability=posterior,
            stop_distance_percent=stop_distance,
            setup_type=record.setup_type,
            market_regime=record.market_regime,
            sector=record.sector,
        )

    def _rank_nearest(
        self,
        diagnostics: tuple[InstitutionalApprovalDiagnostic, ...],
    ) -> tuple[InstitutionalApprovalDiagnostic, ...]:
        rejected = tuple(item for item in diagnostics if not item.approved)
        ranked = sorted(
            rejected,
            key=lambda item: (
                item.failed_criteria_count,
                item.material_failure_count,
                -item.approval_margin,
                -item.weakest_criterion_margin,
                item.evidence_completeness.value,
                item.trade_plan_completeness.value,
                -item.final_score,
                -(item.expectancy or Decimal("-999")),
                -(item.posterior_probability or Decimal("-999")),
                item.symbol,
                item.replay_date,
            ),
        )
        return tuple(ranked[: self.config.nearest_candidate_limit])


def render_approval_diagnostics(summary: ApprovalDiagnosticSummary) -> tuple[str, ...]:
    lines = [
        "Institutional Approval Diagnostics",
        f"Candidates Evaluated: {summary.total_candidates}",
        f"Approved: {summary.approved_candidates}",
        f"Rejected: {summary.rejected_candidates}",
        f"Rejection Rate: {_pct(summary.rejection_rate)}",
        f"Candidates Failing One Criterion: {summary.failing_one_criterion}",
        "Candidates Failing Multiple Criteria: "
        f"{summary.failing_two_criteria + summary.failing_three_or_more_criteria}",
        f"Near-Approval Candidates: {summary.near_approval_count}",
        f"Material Data Gaps: {summary.data_gap_count}",
        f"Incomplete Trade Plans: {summary.incomplete_trade_plan_count}",
        f"Average Approval Margin: {_metric(summary.average_approval_margin)}",
        f"Median Approval Margin: {_metric(summary.median_approval_margin)}",
        "",
        "Top Rejection Criteria:",
        *_count_lines(summary.criterion_counts),
        "",
        "Primary Rejection Reasons:",
        *_count_lines(summary.primary_reason_counts),
        "",
        "Approval Readiness Distribution:",
        *_count_lines(summary.readiness_counts),
        "",
        "Criterion Intersections:",
        *_intersection_lines(summary.criterion_intersections),
        "",
        "Nearest Candidates To Approval:",
        *_nearest_lines(summary.nearest_candidates),
        "",
        "Policy Integrity: no approval thresholds were changed.",
    ]
    if summary.approved_candidates == 0:
        lines.extend(
            (
                "",
                "Institutional Deployment Status: NO DEPLOYABLE TRADE",
                "Alpha is refusing deployment because no candidate satisfied all "
                "current institutional deployment criteria.",
                "Zero approvals do not prove that no profitable setup existed; they "
                "mean no candidate met every current requirement.",
                "Approval precision is unavailable because no approvals were emitted.",
            )
        )
    return tuple(lines)


def render_approval_failures(
    diagnostics: tuple[InstitutionalApprovalDiagnostic, ...],
) -> tuple[str, ...]:
    lines = ["Institutional Approval Failures"]
    if not diagnostics:
        return tuple([*lines, "- none"])
    for item in diagnostics:
        lines.append(
            f"- {item.symbol} {item.replay_date}: "
            f"{item.primary_rejection_reason.value}; "
            f"readiness {item.approval_readiness.value}; "
            f"margin {item.approval_margin}; "
            f"failed {', '.join(criterion.value for criterion in item.failed_criteria)}"
        )
        for result in item.criterion_results:
            if result.applicable and not result.passed:
                lines.append(f"  - {result.display_name}: {result.explanation}")
    return tuple(lines)


def filter_diagnostics(
    diagnostics: tuple[InstitutionalApprovalDiagnostic, ...],
    *,
    criterion: str | None = None,
    reason: str | None = None,
    readiness: str | None = None,
    symbol: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    single_failure_only: bool = False,
    near_approval_only: bool = False,
    data_gaps_only: bool = False,
    incomplete_plan_only: bool = False,
) -> tuple[InstitutionalApprovalDiagnostic, ...]:
    result = diagnostics
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
    if readiness:
        normalized = readiness.strip().upper()
        result = tuple(
            item for item in result if item.approval_readiness.value == normalized
        )
    if symbol:
        normalized_symbol = symbol.strip().upper()
        result = tuple(item for item in result if item.symbol == normalized_symbol)
    if from_date:
        result = tuple(item for item in result if item.replay_date >= from_date)
    if to_date:
        result = tuple(item for item in result if item.replay_date <= to_date)
    if single_failure_only:
        result = tuple(item for item in result if item.failed_criteria_count == 1)
    if near_approval_only:
        result = tuple(
            item
            for item in result
            if item.approval_readiness is ApprovalReadinessState.NEAR_APPROVAL
        )
    if data_gaps_only:
        result = tuple(item for item in result if item.data_gap_reasons)
    if incomplete_plan_only:
        result = tuple(
            item
            for item in result
            if item.trade_plan_completeness is TradePlanCompletenessState.INCOMPLETE
        )
    return tuple(sorted(result, key=lambda item: (item.replay_date, item.symbol)))


def export_approval_diagnostics_json(
    diagnostics: tuple[InstitutionalApprovalDiagnostic, ...],
    path: Path,
) -> None:
    path.write_text(
        json.dumps([_diagnostic_dict(item) for item in diagnostics], indent=2) + "\n",
        encoding="utf-8",
    )


def export_approval_diagnostics_csv(
    diagnostics: tuple[InstitutionalApprovalDiagnostic, ...],
    path: Path,
) -> None:
    rows = []
    for item in diagnostics:
        for result in item.criterion_results:
            row = _diagnostic_flat_dict(item)
            row.update(
                {
                    "criterion_id": result.criterion_id.value,
                    "display_name": result.display_name,
                    "actual_value": result.actual_value,
                    "required_value": result.required_value,
                    "comparison_operator": result.comparison_operator.value,
                    "passed": str(result.passed),
                    "applicable": str(result.applicable),
                    "failure_severity": result.failure_severity.value,
                    "failure_code": result.failure_code.value
                    if result.failure_code
                    else "",
                    "normalized_margin": str(result.normalized_margin),
                    "threshold_gap": result.threshold_gap or "",
                    "explanation": result.explanation,
                }
            )
            rows.append(row)
    _write_csv(rows, path)


def group_diagnostics(
    diagnostics: tuple[InstitutionalApprovalDiagnostic, ...],
    *,
    group_by: str,
) -> tuple[str, ...]:
    counters: Counter[str] = Counter()
    for item in diagnostics:
        if group_by == "criterion":
            for criterion in item.failed_criteria:
                counters[criterion.value] += 1
        elif group_by == "rejection-reason":
            counters[item.primary_rejection_reason.value] += 1
        elif group_by == "readiness":
            counters[item.approval_readiness.value] += 1
        elif group_by == "symbol":
            counters[item.symbol] += 1
        elif group_by == "replay-date":
            counters[item.replay_date.isoformat()] += 1
        elif group_by == "verdict":
            counters[item.final_verdict] += 1
        elif group_by == "sector":
            counters[item.sector or "UNKNOWN"] += 1
        elif group_by == "market-regime":
            counters[item.market_regime or "UNKNOWN"] += 1
        elif group_by == "setup-type":
            counters[item.setup_type or "UNKNOWN"] += 1
        else:
            raise ValueError(f"Unsupported grouping: {group_by}")
    return tuple(f"- {key}: {value}" for key, value in sorted(counters.items()))


def _summary(
    *,
    diagnostics: tuple[InstitutionalApprovalDiagnostic, ...],
    nearest_candidates: tuple[InstitutionalApprovalDiagnostic, ...],
    config: ApprovalDiagnosticsConfig,
) -> ApprovalDiagnosticSummary:
    total = len(diagnostics)
    approved = sum(1 for item in diagnostics if item.approved)
    rejected = total - approved
    margins = tuple(item.approval_margin for item in diagnostics)
    criterion_counts = Counter(
        criterion for item in diagnostics for criterion in item.failed_criteria
    )
    reason_counts = Counter(item.primary_rejection_reason for item in diagnostics)
    readiness_counts = Counter(item.approval_readiness for item in diagnostics)
    intersections = _criterion_intersections(
        diagnostics,
        config.minimum_intersection_count,
    )
    failing_one_criterion = sum(
        1 for item in diagnostics if item.failed_criteria_count == 1
    )
    failing_two_criteria = sum(
        1 for item in diagnostics if item.failed_criteria_count == 2
    )
    return ApprovalDiagnosticSummary(
        diagnostics=diagnostics,
        nearest_candidates=nearest_candidates,
        total_candidates=total,
        approved_candidates=approved,
        rejected_candidates=rejected,
        rejection_rate=_ratio(rejected, total),
        failing_one_criterion=failing_one_criterion,
        failing_two_criteria=failing_two_criteria,
        failing_three_or_more_criteria=sum(
            1 for item in diagnostics if item.failed_criteria_count >= 3
        ),
        criterion_counts=_count_tuple(criterion_counts, total),
        primary_reason_counts=_count_tuple(reason_counts, total),
        readiness_counts=_count_tuple(readiness_counts, total),
        criterion_intersections=intersections,
        average_approval_margin=_average(margins),
        median_approval_margin=_median(margins),
        highest_approval_margin=max(margins) if margins else None,
        near_approval_count=sum(
            1
            for item in diagnostics
            if item.approval_readiness is ApprovalReadinessState.NEAR_APPROVAL
        ),
        data_gap_count=sum(1 for item in diagnostics if item.data_gap_reasons),
        incomplete_trade_plan_count=sum(
            1
            for item in diagnostics
            if item.trade_plan_completeness is TradePlanCompletenessState.INCOMPLETE
        ),
    )


def _historical_context(
    *,
    records: tuple[CandidateDecisionRecord, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> dict[tuple[str | None, str | None], tuple[int, Decimal | None, Decimal | None]]:
    outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
    returns: dict[tuple[str | None, str | None], list[Decimal]] = defaultdict(list)
    wins: dict[tuple[str | None, str | None], int] = defaultdict(int)
    for record in records:
        window = _primary_window(outcome_by_id.get(record.candidate_id))
        if window is None or window.forward_return_pct_from_entry is None:
            continue
        key = (record.setup_type, record.market_regime)
        returns[key].append(window.forward_return_pct_from_entry)
        if window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_WON:
            wins[key] += 1
    context: HistoricalContext = {}
    for key, values in returns.items():
        sample_count = len(values)
        expectancy = (sum(values, _ZERO) / Decimal(sample_count)).quantize(
            _TWO,
            rounding=ROUND_HALF_UP,
        )
        posterior = _ratio(wins[key], sample_count)
        context[key] = (sample_count, expectancy, posterior)
    return context


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


def _numeric_min(
    criterion_id: ApprovalCriterionId,
    display_name: str,
    actual: Decimal | None,
    required: Decimal,
    failure_code: ApprovalRejectionReasonCode,
    unit: str,
    cap: Decimal,
) -> InstitutionalApprovalCriterionResult:
    if actual is None:
        return _missing_numeric(
            criterion_id,
            display_name,
            required,
            ComparisonOperator.GTE,
            failure_code,
        )
    passed = actual >= required
    margin = min(actual / required if required != _ZERO else _ONE, cap)
    gap = None if passed else f"shortfall {(required - actual).quantize(_TWO)} {unit}"
    return _criterion(
        criterion_id=criterion_id,
        display_name=display_name,
        actual_value=str(actual),
        required_value=str(required),
        comparison_operator=ComparisonOperator.GTE,
        passed=passed,
        failure_code=failure_code,
        normalized_margin=margin.quantize(_FOUR, rounding=ROUND_HALF_UP),
        data_available=True,
        threshold_gap=gap,
        explanation=(
            f"{display_name}: {actual} / {required} — {'PASS' if passed else 'FAIL'}"
        )
        + (f"; {gap}" if gap else ""),
    )


def _integer_min(
    criterion_id: ApprovalCriterionId,
    display_name: str,
    actual: int | None,
    required: int,
    failure_code: ApprovalRejectionReasonCode,
    cap: Decimal,
) -> InstitutionalApprovalCriterionResult:
    if actual is None:
        return _missing_numeric(
            criterion_id,
            display_name,
            Decimal(required),
            ComparisonOperator.GTE,
            failure_code,
        )
    actual_decimal = Decimal(actual)
    required_decimal = Decimal(required)
    passed = actual >= required
    margin = min(actual_decimal / required_decimal, cap)
    gap = None if passed else f"shortfall {required - actual} samples"
    return _criterion(
        criterion_id=criterion_id,
        display_name=display_name,
        actual_value=str(actual),
        required_value=str(required),
        comparison_operator=ComparisonOperator.GTE,
        passed=passed,
        failure_code=failure_code,
        normalized_margin=margin.quantize(_FOUR, rounding=ROUND_HALF_UP),
        data_available=True,
        threshold_gap=gap,
        explanation=(
            f"{display_name}: {actual} / {required} — {'PASS' if passed else 'FAIL'}"
        )
        + (f"; {gap}" if gap else ""),
    )


def _historical_sample_criterion(
    criterion_id: ApprovalCriterionId,
    display_name: str,
    actual: int,
    required: int,
    cap: Decimal,
    *,
    strong_evidence_exception: bool,
) -> InstitutionalApprovalCriterionResult:
    if strong_evidence_exception and actual < required:
        return _criterion(
            criterion_id=criterion_id,
            display_name=display_name,
            actual_value=str(actual),
            required_value=f"{required} unless strong evidence exception applies",
            comparison_operator=ComparisonOperator.GTE,
            passed=True,
            failure_code=None,
            normalized_margin=_ONE,
            data_available=True,
            threshold_gap=None,
            explanation=(
                f"{display_name}: {actual} / {required}; PASS via "
                "strong-evidence exception."
            ),
        )
    return _integer_min(
        criterion_id,
        display_name,
        actual,
        required,
        ApprovalRejectionReasonCode.INSUFFICIENT_HISTORICAL_SAMPLES,
        cap,
    )


def _numeric_max(
    criterion_id: ApprovalCriterionId,
    display_name: str,
    actual: Decimal | None,
    required: Decimal,
    failure_code: ApprovalRejectionReasonCode,
    unit: str,
    cap: Decimal,
) -> InstitutionalApprovalCriterionResult:
    if actual is None:
        return _missing_numeric(
            criterion_id,
            display_name,
            required,
            ComparisonOperator.LTE,
            failure_code,
        )
    passed = actual <= required
    margin = cap if actual <= _ZERO else min(required / actual, cap)
    gap = None if passed else f"excess {(actual - required).quantize(_TWO)} {unit}"
    return _criterion(
        criterion_id=criterion_id,
        display_name=display_name,
        actual_value=str(actual),
        required_value=str(required),
        comparison_operator=ComparisonOperator.LTE,
        passed=passed,
        failure_code=failure_code,
        normalized_margin=margin.quantize(_FOUR, rounding=ROUND_HALF_UP),
        data_available=True,
        threshold_gap=gap,
        explanation=(
            f"{display_name}: {actual} / {required} — {'PASS' if passed else 'FAIL'}"
        )
        + (f"; {gap}" if gap else ""),
    )


def _presence(
    criterion_id: ApprovalCriterionId,
    display_name: str,
    actual: object | None,
    failure_code: ApprovalRejectionReasonCode,
) -> InstitutionalApprovalCriterionResult:
    return _binary(
        criterion_id,
        display_name,
        actual is not None,
        failure_code,
        explanation=(
            f"Required field missing: {display_name}"
            if actual is None
            else f"{display_name} available."
        ),
    )


def _binary(
    criterion_id: ApprovalCriterionId,
    display_name: str,
    passed: bool,
    failure_code: ApprovalRejectionReasonCode,
    *,
    applicable: bool = True,
    explanation: str | None = None,
) -> InstitutionalApprovalCriterionResult:
    return _criterion(
        criterion_id=criterion_id,
        display_name=display_name,
        actual_value=str(passed),
        required_value="True",
        comparison_operator=ComparisonOperator.BOOLEAN,
        passed=passed if applicable else True,
        applicable=applicable,
        failure_code=None if passed or not applicable else failure_code,
        normalized_margin=_ONE if passed or not applicable else _ZERO,
        data_available=True,
        threshold_gap=(
            None
            if passed or not applicable
            else f"required field missing: {display_name}"
        ),
        explanation=explanation
        or f"{display_name}: {'PASS' if passed or not applicable else 'FAIL'}",
    )


def _has_strong_evidence_exception(record: CandidateDecisionRecord) -> bool:
    normalized_layers = {
        layer.strip().lower().replace("_", "-") for layer in record.evidence_layers
    }
    return "strong-evidence-exception" in normalized_layers


def _missing_numeric(
    criterion_id: ApprovalCriterionId,
    display_name: str,
    required: Decimal,
    operator: ComparisonOperator,
    failure_code: ApprovalRejectionReasonCode,
) -> InstitutionalApprovalCriterionResult:
    return _criterion(
        criterion_id=criterion_id,
        display_name=display_name,
        actual_value=None,
        required_value=str(required),
        comparison_operator=operator,
        passed=False,
        failure_code=failure_code,
        normalized_margin=_ZERO,
        data_available=False,
        threshold_gap=f"required value missing: {display_name}",
        explanation=f"{display_name} unavailable; cannot evaluate threshold.",
    )


def _criterion(
    *,
    criterion_id: ApprovalCriterionId,
    display_name: str,
    actual_value: str | None,
    required_value: str,
    comparison_operator: ComparisonOperator,
    passed: bool,
    failure_code: ApprovalRejectionReasonCode | None,
    normalized_margin: Decimal,
    data_available: bool,
    threshold_gap: str | None,
    explanation: str,
    applicable: bool = True,
) -> InstitutionalApprovalCriterionResult:
    severity = ApprovalFailureSeverity.NONE
    if applicable and not passed:
        severity = (
            ApprovalFailureSeverity.CRITICAL
            if criterion_id
            in {
                ApprovalCriterionId.ENTRY_AVAILABLE,
                ApprovalCriterionId.STOP_AVAILABLE,
                ApprovalCriterionId.TARGETS_AVAILABLE,
                ApprovalCriterionId.ATR_AVAILABLE,
                ApprovalCriterionId.DMA20_INVALIDATION_AVAILABLE,
            }
            else ApprovalFailureSeverity.MATERIAL
        )
    return InstitutionalApprovalCriterionResult(
        criterion_id=criterion_id,
        display_name=display_name,
        actual_value=actual_value,
        required_value=required_value,
        comparison_operator=comparison_operator,
        passed=passed,
        applicable=applicable,
        failure_severity=severity,
        failure_code=failure_code if applicable and not passed else None,
        explanation=explanation,
        normalized_margin=max(_ZERO, normalized_margin),
        data_available=data_available,
        threshold_gap=threshold_gap,
    )


def _failure_reasons(
    criteria: tuple[InstitutionalApprovalCriterionResult, ...],
) -> tuple[ApprovalRejectionReasonCode, ...]:
    return tuple(
        dict.fromkeys(
            result.failure_code
            for result in criteria
            if result.applicable and not result.passed and result.failure_code
        )
    )


def _primary_reason(
    reasons: tuple[ApprovalRejectionReasonCode, ...],
    material_count: int,
) -> ApprovalRejectionReasonCode:
    if material_count >= 3:
        return ApprovalRejectionReasonCode.MULTIPLE_MATERIAL_FAILURES
    priority = (
        ApprovalRejectionReasonCode.INCOMPLETE_ENTRY,
        ApprovalRejectionReasonCode.INCOMPLETE_STOP,
        ApprovalRejectionReasonCode.INCOMPLETE_TARGETS,
        ApprovalRejectionReasonCode.MISSING_ATR,
        ApprovalRejectionReasonCode.MISSING_20DMA_INVALIDATION,
        ApprovalRejectionReasonCode.INSUFFICIENT_EVIDENCE_SCORE,
        ApprovalRejectionReasonCode.INSUFFICIENT_HISTORICAL_SAMPLES,
        ApprovalRejectionReasonCode.NEGATIVE_OR_WEAK_EXPECTANCY,
        ApprovalRejectionReasonCode.INSUFFICIENT_POSTERIOR_PROBABILITY,
        ApprovalRejectionReasonCode.EXCESSIVE_STOP_DISTANCE,
        ApprovalRejectionReasonCode.INSTITUTIONAL_LAYER_REJECTED,
    )
    for reason in priority:
        if reason in reasons:
            return reason
    return ApprovalRejectionReasonCode.UNCLASSIFIED


def _approval_margin(
    criteria: tuple[InstitutionalApprovalCriterionResult, ...],
) -> tuple[Decimal, Decimal]:
    margins = tuple(
        result.normalized_margin for result in criteria if result.applicable
    )
    if not margins:
        return (_ZERO, _ZERO)
    weakest = min(margins)
    harmonic = Decimal(len(margins)) / sum(
        (_ONE / max(margin, Decimal("0.0001"))) for margin in margins
    )
    failed_count = sum(1 for margin in margins if margin < _ONE)
    penalty = Decimal("1") + (Decimal(failed_count) * Decimal("0.12"))
    return (
        (harmonic * Decimal("0.65") + weakest * Decimal("0.35")) / penalty
    ).quantize(_FOUR, rounding=ROUND_HALF_UP), weakest.quantize(
        _FOUR,
        rounding=ROUND_HALF_UP,
    )


def _evidence_state(
    sample_count: int | None,
    expectancy: Decimal | None,
    posterior: Decimal | None,
) -> EvidenceCompletenessState:
    if sample_count is None or expectancy is None or posterior is None:
        return EvidenceCompletenessState.MISSING
    if sample_count < 60:
        return EvidenceCompletenessState.PARTIAL
    return EvidenceCompletenessState.COMPLETE


def _trade_plan_state(
    criteria: tuple[InstitutionalApprovalCriterionResult, ...],
) -> TradePlanCompletenessState:
    plan_ids = {
        ApprovalCriterionId.ENTRY_AVAILABLE,
        ApprovalCriterionId.STOP_AVAILABLE,
        ApprovalCriterionId.TARGETS_AVAILABLE,
        ApprovalCriterionId.ATR_AVAILABLE,
        ApprovalCriterionId.DMA20_INVALIDATION_AVAILABLE,
    }
    failed = any(
        result.criterion_id in plan_ids and result.applicable and not result.passed
        for result in criteria
    )
    return (
        TradePlanCompletenessState.INCOMPLETE
        if failed
        else TradePlanCompletenessState.COMPLETE
    )


def _readiness(
    *,
    approved: bool,
    failed_count: int,
    material_count: int,
    margin: Decimal,
    evidence_state: EvidenceCompletenessState,
    trade_plan_state: TradePlanCompletenessState,
    data_gaps: tuple[str, ...],
    config: ApprovalDiagnosticsConfig,
) -> ApprovalReadinessState:
    if approved:
        return ApprovalReadinessState.APPROVED
    if trade_plan_state is TradePlanCompletenessState.INCOMPLETE:
        return ApprovalReadinessState.INCOMPLETE_TRADE_PLAN
    if data_gaps:
        return ApprovalReadinessState.MATERIAL_DATA_GAP
    if evidence_state is not EvidenceCompletenessState.COMPLETE:
        return ApprovalReadinessState.INSUFFICIENT_EVIDENCE
    if (
        failed_count <= config.maximum_failed_criteria_for_near_approval
        and material_count == 1
        and margin >= config.near_approval_minimum_margin
    ):
        return ApprovalReadinessState.NEAR_APPROVAL
    if (
        failed_count <= config.maximum_failed_criteria_for_conditional
        and margin >= config.conditional_minimum_margin
    ):
        return ApprovalReadinessState.CONDITIONAL
    return ApprovalReadinessState.STRUCTURALLY_WEAK


def _criterion_intersections(
    diagnostics: tuple[InstitutionalApprovalDiagnostic, ...],
    minimum_count: int,
) -> tuple[tuple[str, int], ...]:
    pairs = (
        (ApprovalCriterionId.EVIDENCE_SCORE, ApprovalCriterionId.HISTORICAL_SAMPLES),
        (ApprovalCriterionId.EVIDENCE_SCORE, ApprovalCriterionId.POSTERIOR_PROBABILITY),
        (ApprovalCriterionId.STOP_DISTANCE, ApprovalCriterionId.TARGETS_AVAILABLE),
        (ApprovalCriterionId.EXPECTANCY, ApprovalCriterionId.POSTERIOR_PROBABILITY),
        (ApprovalCriterionId.HISTORICAL_SAMPLES, ApprovalCriterionId.ATR_AVAILABLE),
    )
    rows = []
    for left, right in pairs:
        count = sum(
            1
            for item in diagnostics
            if left in item.failed_criteria and right in item.failed_criteria
        )
        if count >= minimum_count:
            rows.append((f"{left.value} + {right.value}", count))
    return tuple(rows)


def _with_rank(
    diagnostic: InstitutionalApprovalDiagnostic,
    rank: int | None,
) -> InstitutionalApprovalDiagnostic:
    return replace(diagnostic, nearest_to_approval_rank=rank)


def _record_stop_distance(record: CandidateDecisionRecord) -> Decimal | None:
    entry = record.confirmation_entry or record.entry_zone_high
    stop = record.risk_stop
    if entry is None or stop is None or entry <= _ZERO:
        return None
    return ((entry - stop) / entry * Decimal("100")).quantize(_TWO)


def _has_atr_text(value: str | None) -> bool:
    return value is not None and "atr" in value.lower()


def _has_20dma_text(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.lower().replace("-", "")
    return "20dma" in normalized or "20 dma" in normalized


def _count_tuple[K: StrEnum](
    counter: Counter[K],
    total: int,
) -> tuple[tuple[K, int, Decimal], ...]:
    return tuple(
        (key, count, _ratio(count, total))
        for key, count in sorted(
            counter.items(),
            key=lambda item: (-item[1], str(item[0])),
        )
    )


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(_FOUR)


def _median(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return Decimal(str(median(values))).quantize(_FOUR)


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return _ZERO
    return (Decimal(numerator) / Decimal(denominator)).quantize(_FOUR)


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _pct(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(_TWO)}%"


def _count_lines[K: StrEnum](rows: tuple[tuple[K, int, Decimal], ...]) -> list[str]:
    if not rows:
        return ["- unavailable"]
    return [f"- {key.value}: {count} ({_pct(pct)})" for key, count, pct in rows[:10]]


def _intersection_lines(rows: tuple[tuple[str, int], ...]) -> list[str]:
    if not rows:
        return ["- unavailable"]
    return [f"- {name}: {count}" for name, count in rows]


def _nearest_lines(
    candidates: tuple[InstitutionalApprovalDiagnostic, ...],
) -> list[str]:
    if not candidates:
        return ["- unavailable"]
    lines = []
    for item in candidates[:10]:
        lines.append(
            "- "
            f"{item.symbol} {item.replay_date}: "
            f"score {item.final_score}/85, "
            f"samples {item.matched_samples}/60, "
            f"expectancy {_metric(item.expectancy)}/0.10, "
            f"posterior {_metric(item.posterior_probability)}/0.52, "
            f"stop {_metric(item.stop_distance_percent)}/10, "
            f"failed {item.failed_criteria_count}, "
            f"margin {item.approval_margin}, "
            f"readiness {item.approval_readiness.value}, "
            f"reason {item.primary_rejection_reason.value}"
        )
    return lines


def _diagnostic_dict(item: InstitutionalApprovalDiagnostic) -> dict[str, object]:
    data = _diagnostic_flat_dict(item)
    data["criterion_results"] = [
        {
            "criterion_id": result.criterion_id.value,
            "display_name": result.display_name,
            "actual_value": result.actual_value,
            "required_value": result.required_value,
            "comparison_operator": result.comparison_operator.value,
            "passed": result.passed,
            "applicable": result.applicable,
            "failure_severity": result.failure_severity.value,
            "failure_code": result.failure_code.value if result.failure_code else None,
            "normalized_margin": str(result.normalized_margin),
            "threshold_gap": result.threshold_gap,
            "data_available": result.data_available,
            "explanation": result.explanation,
        }
        for result in item.criterion_results
    ]
    return data


def _diagnostic_flat_dict(item: InstitutionalApprovalDiagnostic) -> dict[str, object]:
    return {
        "symbol": item.symbol,
        "replay_date": item.replay_date.isoformat(),
        "candidate_id": item.candidate_id,
        "final_verdict": item.final_verdict,
        "institutional_decision": item.institutional_decision,
        "approved": str(item.approved),
        "failed_criteria": ",".join(
            criterion.value for criterion in item.failed_criteria
        ),
        "primary_rejection_reason": item.primary_rejection_reason.value,
        "secondary_rejection_reasons": ",".join(
            reason.value for reason in item.secondary_rejection_reasons
        ),
        "approval_margin": str(item.approval_margin),
        "weakest_criterion_margin": str(item.weakest_criterion_margin),
        "approval_readiness": item.approval_readiness.value,
        "evidence_completeness": item.evidence_completeness.value,
        "trade_plan_completeness": item.trade_plan_completeness.value,
        "nearest_to_approval_rank": item.nearest_to_approval_rank or "",
        "final_score": str(item.final_score),
        "matched_samples": item.matched_samples or "",
        "expectancy": str(item.expectancy) if item.expectancy is not None else "",
        "posterior_probability": str(item.posterior_probability)
        if item.posterior_probability is not None
        else "",
        "stop_distance_percent": str(item.stop_distance_percent)
        if item.stop_distance_percent is not None
        else "",
        "setup_type": item.setup_type or "",
        "market_regime": item.market_regime or "",
        "sector": item.sector or "",
    }


def _write_csv(rows: list[dict[str, object]], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


__all__ = [
    "ApprovalDiagnosticsConfig",
    "ApprovalDiagnosticsEngine",
    "ApprovalDiagnosticSummary",
    "ApprovalCriterionId",
    "ApprovalFailureSeverity",
    "ApprovalReadinessState",
    "ApprovalRejectionReasonCode",
    "EvidenceCompletenessState",
    "InstitutionalApprovalCriterionResult",
    "InstitutionalApprovalDiagnostic",
    "TradePlanCompletenessState",
    "export_approval_diagnostics_csv",
    "export_approval_diagnostics_json",
    "filter_diagnostics",
    "group_diagnostics",
    "render_approval_diagnostics",
    "render_approval_failures",
]
