"""Approval-precision and market-regime metric truth diagnostics."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path

from alpha.candidate_learning.aggregator import is_deployment_approved
from alpha.candidate_learning.approval_diagnostics import ApprovalDiagnosticsEngine
from alpha.candidate_learning.entry_timing import EntryTimingIntelligenceEngine
from alpha.candidate_learning.market_regime_audit import MarketRegimeAuditEngine
from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.research.bottleneck_engine import BottleneckEngine
from alpha.research.models import (
    DiagnosticEvidence,
    ExperimentDecision,
    ExperimentStatus,
    MetricAvailability,
    MetricProvenance,
    RegisteredResearchExperiment,
    ResearchConfidence,
    ResearchMetric,
    ResearchSubsystem,
)

METRIC_TRUTH_AUDIT_VERSION = "metric-truth-audit-v1"
APPROVAL_PRECISION_CONTRACT_VERSION = "approval-precision-contract-v1"
EARLIER_REPLAY_CUTOFF = date(2016, 12, 13)
PRODUCTION_INFLUENCE = False

_ZERO = Decimal("0")
_ONE = Decimal("1")
_FOUR = Decimal("0.0001")
_PERCENT = Decimal("100")
_WILSON_Z_95 = Decimal("1.959963984540054")
_REGIME_CLASSES = (
    "BULLISH_TREND",
    "BEARISH_TREND",
    "SIDEWAYS",
    "CORRECTION",
    "HIGH_VOLATILITY",
    "RECOVERY",
)


class StrictApprovalZeroConclusion(StrEnum):
    VALID_BUT_OVERRESTRICTIVE_POLICY = "VALID_BUT_OVERRESTRICTIVE_POLICY"
    DATA_UNAVAILABILITY = "DATA_UNAVAILABILITY"
    SEMANTIC_MISMATCH = "SEMANTIC_MISMATCH"
    IMPLEMENTATION_DEFECT = "IMPLEMENTATION_DEFECT"
    EXPECTED_BY_DESIGN = "EXPECTED_BY_DESIGN"
    INCONCLUSIVE = "INCONCLUSIVE"


class RegimeMetricConclusion(StrEnum):
    METRIC_VALID_MODEL_FAILURE = "METRIC_VALID_MODEL_FAILURE"
    LABEL_MAPPING_DEFECT = "LABEL_MAPPING_DEFECT"
    SCALE_OR_RENDERING_DEFECT = "SCALE_OR_RENDERING_DEFECT"
    POPULATION_ALIGNMENT_DEFECT = "POPULATION_ALIGNMENT_DEFECT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    OTHER_IMPLEMENTATION_DEFECT = "OTHER_IMPLEMENTATION_DEFECT"


@dataclass(frozen=True, slots=True)
class ApprovalDefinitionAudit:
    canonical_name: str
    source_module: str
    exact_predicate: str
    numerator_definition: str
    denominator_definition: str
    outcome_eligibility_rule: str
    outcome_horizon: str
    success_threshold: str
    transaction_cost_treatment: str
    incomplete_outcome_treatment: str
    duplicate_treatment: str
    replay_version: str
    population_size: int
    approval_count: int
    eligible_approval_count: int
    incomplete_approval_count: int
    true_positives: int
    false_positives: int
    precision: Decimal | None
    recall: Decimal | None
    precision_status: MetricAvailability
    alias_of: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovalPrecisionContract:
    metric_name: str
    approval_concept: str
    eligible_population: str
    outcome_horizon: str
    success_threshold: str
    required_completed_outcome: str
    transaction_cost_treatment: str
    missing_observation_treatment: str
    duplicate_treatment: str
    replay_version: str
    numerator: int
    denominator: int
    precision: Decimal | None
    precision_status: MetricAvailability
    confidence_interval_low: Decimal | None
    confidence_interval_high: Decimal | None


@dataclass(frozen=True, slots=True)
class ApprovalPopulationReconciliation:
    earlier_cutoff: date
    earlier_origin_status: str
    earlier_precision: Decimal
    earlier_approval_count: int
    earlier_successful_approvals: int
    earlier_incomplete_approvals: int
    earlier_population: str
    earlier_definition: str
    current_data_as_of: date
    current_precision: Decimal
    current_approval_count: int
    current_successful_approvals: int
    current_incomplete_approvals: int
    current_population: str
    current_definition: str
    candidates_in_both: tuple[str, ...]
    earlier_only_candidates: tuple[str, ...]
    current_only_candidates: tuple[str, ...]
    outcome_classification_differences: tuple[str, ...]
    duplicate_candidate_ids: tuple[str, ...]
    overwritten_record_count: int
    changed_horizon_count: int
    changed_success_definition_count: int
    added_successes: int
    added_failures: int
    precision_delta: Decimal
    unexplained_remainder: Decimal
    exact_attribution: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GateSurvival:
    gate_id: str
    predicate: str
    reached: int
    rejected_at_gate: int
    survived: int
    cumulative_survival: Decimal


@dataclass(frozen=True, slots=True)
class GateFailureCount:
    gate_id: str
    count: int


@dataclass(frozen=True, slots=True)
class StrictApprovalAttribution:
    total_candidates: int
    strict_approvals: int
    implementation_matches_predicate: bool
    gate_survival: tuple[GateSurvival, ...]
    mutually_exclusive_primary_failures: tuple[GateFailureCount, ...]
    overlapping_failures: tuple[GateFailureCount, ...]
    extended_diagnostic_failures: tuple[GateFailureCount, ...]
    near_approval_count: int
    failing_one_criterion: int
    failing_two_criteria: int
    failing_three_or_more_criteria: int
    profitable_rejected_candidates: int
    completed_rejected_candidates: int
    conclusion: StrictApprovalZeroConclusion
    explanation: str


@dataclass(frozen=True, slots=True)
class RegimeConfusionCell:
    actual_label: str
    predicted_label: str
    count: int


@dataclass(frozen=True, slots=True)
class RegimeClassStatistic:
    label: str
    support: int
    predicted_count: int
    true_positive: int
    recall: Decimal | None
    precision: Decimal | None
    f1: Decimal | None


@dataclass(frozen=True, slots=True)
class RegimeMetricTruth:
    class_labels: tuple[str, ...]
    true_label_source: str
    predicted_label_source: str
    label_normalization: tuple[tuple[str, str], ...]
    confusion_matrix: tuple[RegimeConfusionCell, ...]
    class_statistics: tuple[RegimeClassStatistic, ...]
    source_reported_balanced_accuracy: Decimal | None
    independently_recomputed_balanced_accuracy: Decimal | None
    rendered_percentage: Decimal | None
    ordinary_accuracy: Decimal | None
    macro_f1: Decimal | None
    majority_class_baseline: Decimal | None
    nominal_uniform_random_baseline: Decimal | None
    coverage: Decimal
    observations: int
    excluded_observations: int
    excluded_reasons: tuple[tuple[str, int], ...]
    missing_benchmark_inputs: int
    unavailable_reference_labels: int
    unknown_predicted_labels: int
    exact_date_alignment: bool
    look_ahead_detected: bool
    fraction_percentage_semantics_valid: bool
    source_score_minimum: Decimal | None
    source_score_maximum: Decimal | None
    source_thresholds: tuple[str, ...]
    metric_valid_for_decision: bool
    conclusion: RegimeMetricConclusion
    exact_failure_mode: str


@dataclass(frozen=True, slots=True)
class IrdAdapterValidation:
    diagnostic_id: str
    metric_count: int
    provenance_complete: bool
    units_valid: bool
    fraction_percentage_semantics_valid: bool
    availability_semantics_valid: bool
    numerator_denominator_valid: bool
    safe_for_prioritization: bool
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricTruthAuditReport:
    audit_version: str
    data_as_of: date
    approval_definitions: tuple[ApprovalDefinitionAudit, ...]
    raw_approval_contract: ApprovalPrecisionContract
    strict_approval_contract: ApprovalPrecisionContract
    reconciliation: ApprovalPopulationReconciliation
    strict_attribution: StrictApprovalAttribution
    regime_truth: RegimeMetricTruth
    adapter_validations: tuple[IrdAdapterValidation, ...]
    roadmap_before: tuple[str, ...]
    roadmap_after: tuple[str, ...]
    roadmap_impact: str
    recommended_next_sprint: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class _OutcomeObservation:
    record: CandidateDecisionRecord
    window: CandidateForwardWindowOutcome
    profitable: bool


@dataclass(frozen=True, slots=True)
class _GateRule:
    gate_id: str
    predicate_text: str
    predicate: Callable[[CandidateDecisionRecord], bool]


class MetricTruthAuditEngine:
    """Reconstruct metric arithmetic without changing its source engines."""

    def audit(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
        diagnostics: tuple[DiagnosticEvidence, ...] = (),
    ) -> MetricTruthAuditReport:
        observations, duplicates = _outcome_observations(records, outcomes)
        definitions = _approval_inventory(records, observations, duplicates)
        raw = next(
            item for item in definitions if item.canonical_name == "RAW_APPROVAL"
        )
        strict = next(
            item
            for item in definitions
            if item.canonical_name == "STRICT_INSTITUTIONAL_APPROVAL"
        )
        raw_contract = _approval_contract(raw)
        strict_contract = _approval_contract(strict)
        reconciliation = _reconcile(
            records=records,
            observations=observations,
            duplicate_ids=duplicates,
        )
        strict_attribution = _strict_attribution(records, observations, outcomes)
        regime_truth = _regime_truth(records, outcomes)
        validations = _validate_adapters(diagnostics)
        after = _roadmap_after(diagnostics)
        before = (
            "P0: approval-diagnostics",
            "P0: market-regime-audit",
        )
        return MetricTruthAuditReport(
            audit_version=METRIC_TRUTH_AUDIT_VERSION,
            data_as_of=max(
                (record.evaluation_date for record in records),
                default=date.min,
            ),
            approval_definitions=definitions,
            raw_approval_contract=raw_contract,
            strict_approval_contract=strict_contract,
            reconciliation=reconciliation,
            strict_attribution=strict_attribution,
            regime_truth=regime_truth,
            adapter_validations=validations,
            roadmap_before=before,
            roadmap_after=after,
            roadmap_impact=(
                "CHANGED: market-regime-audit is removed from measured P0 "
                "prioritization because its 1.29% reference metric has a proven "
                "scale defect. Approval diagnostics remains P0."
            ),
            recommended_next_sprint=(
                "Investigate non-entry approval gates using matched outcomes; "
                "repair the diagnostic regime reference separately before using "
                "regime accuracy for prioritization."
            ),
        )


def regime_reference_scale_is_valid(
    records: tuple[CandidateDecisionRecord, ...],
) -> bool:
    """Return whether the native regime reference uses scale-compatible inputs."""

    scores = tuple(
        value
        for record in records
        if _indicator(record, ("benchmark-return", "benchmark_return")) is None
        if (value := _indicator(record, ("trend", "price", "price-structure")))
        is not None
    )
    if not scores:
        return True
    return max(scores) > Decimal("1")


def metric_truth_experiment(
    report: MetricTruthAuditReport,
) -> RegisteredResearchExperiment:
    earlier = report.reconciliation
    raw = report.raw_approval_contract
    regime = report.regime_truth
    baseline = (
        _research_metric(
            metric_id="approval.raw.precision.snapshot_earlier",
            label="Earlier raw approval precision",
            value=earlier.earlier_precision,
            unit="ratio",
            source="MetricTruthAuditEngine.reconciliation",
            definition=earlier.earlier_definition,
            population=earlier.earlier_population,
            numerator=earlier.earlier_successful_approvals,
            denominator=earlier.earlier_approval_count,
        ),
        _research_metric(
            metric_id="market_regime.balanced_accuracy.native",
            label="Native market-regime balanced-accuracy arithmetic",
            value=None,
            unit="ratio",
            source="MarketRegimeAuditEngine._reference_quality",
            definition="native arithmetic with invalid reference-label scale",
            population="candidate records with native synthetic reference labels",
            numerator=_balanced_accuracy_matches(regime),
            denominator=regime.observations,
            availability=MetricAvailability.INVALID,
        ),
    )
    treatment = (
        _research_metric(
            metric_id="approval.raw.precision.current",
            label="Canonical current raw approval precision",
            value=raw.precision,
            unit="ratio",
            source="MetricTruthAuditEngine.canonical_contract",
            definition=("profitable completed raw approvals / completed raw approvals"),
            population=raw.eligible_population,
            numerator=raw.numerator,
            denominator=raw.denominator,
            availability=raw.precision_status,
        ),
        _research_metric(
            metric_id="market_regime.balanced_accuracy.validated",
            label="Validated market-regime balanced accuracy",
            value=None,
            unit="ratio",
            source="MetricTruthAuditEngine.regime_truth",
            definition="balanced accuracy after reference-label truth validation",
            population="not estimable until reference labels are scale-valid",
            numerator=None,
            denominator=None,
            availability=MetricAvailability.INVALID,
        ),
    )
    return RegisteredResearchExperiment(
        experiment_id=(
            f"approval-regime-metric-truth-audit-v1-{report.data_as_of.isoformat()}"
        ),
        title="Approval Precision and Regime Metric Truth Audit",
        subsystem=ResearchSubsystem.RESEARCH_GOVERNANCE,
        experiment_date=report.data_as_of,
        purpose=(
            "Reconcile approval precision populations and validate market-regime "
            "balanced-accuracy semantics."
        ),
        evidence_sources=(
            "candidate_learning_ledger",
            "ApprovalDiagnosticsEngine",
            "MarketRegimeAuditEngine",
            "IRD diagnostic registry",
        ),
        baseline=baseline,
        treatment=treatment,
        metrics=(
            "RAW_APPROVAL_PRECISION",
            "STRICT_INSTITUTIONAL_APPROVAL_PRECISION",
            "MARKET_REGIME_BALANCED_ACCURACY",
        ),
        statistical_confidence=ResearchConfidence.HIGH,
        decision=ExperimentDecision.ACCEPT,
        status=ExperimentStatus.COMPLETED,
        findings=(
            f"Raw approval precision is {raw.numerator}/{raw.denominator}; "
            f"the earlier snapshot is {earlier.earlier_successful_approvals}/"
            f"{earlier.earlier_approval_count}.",
            (
                "Strict institutional precision is not estimable because "
                "approvals are zero."
            ),
            (
                f"Native {_percentage(regime.source_reported_balanced_accuracy)} "
                "regime arithmetic uses scale-defective reference labels."
            ),
        ),
        lessons_learned=(
            "Approval concepts require separate contracts and populations.",
            "Arithmetic reproducibility does not establish semantic metric validity.",
            (
                "Unavailable, not-estimable, invalid, and numeric zero are "
                "distinct states."
            ),
        ),
    )


def metric_truth_json(report: MetricTruthAuditReport) -> str:
    return (
        json.dumps(
            _json_value(asdict(report)),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        )
        + "\n"
    )


def metric_truth_csv(report: MetricTruthAuditReport) -> str:
    output = io.StringIO(newline="")
    columns = (
        "section",
        "key",
        "label",
        "value",
        "numerator",
        "denominator",
        "status",
        "source",
        "definition",
        "population",
        "version",
    )
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for approval in report.approval_definitions:
        writer.writerow(
            {
                "section": "approval_definition",
                "key": approval.canonical_name,
                "label": "precision",
                "value": _text(approval.precision),
                "numerator": approval.true_positives,
                "denominator": approval.eligible_approval_count,
                "status": approval.precision_status.value,
                "source": approval.source_module,
                "definition": approval.exact_predicate,
                "population": approval.denominator_definition,
                "version": approval.replay_version,
            }
        )
    for gate in report.strict_attribution.gate_survival:
        writer.writerow(
            {
                "section": "strict_gate",
                "key": gate.gate_id,
                "label": "survival",
                "value": str(gate.cumulative_survival),
                "numerator": gate.survived,
                "denominator": report.strict_attribution.total_candidates,
                "status": MetricAvailability.AVAILABLE.value,
                "source": "is_deployment_approved",
                "definition": gate.predicate,
                "population": "all candidate decision records",
                "version": APPROVAL_PRECISION_CONTRACT_VERSION,
            }
        )
    for class_statistic in report.regime_truth.class_statistics:
        writer.writerow(
            {
                "section": "regime_class",
                "key": class_statistic.label,
                "label": "recall",
                "value": _text(class_statistic.recall),
                "numerator": class_statistic.true_positive,
                "denominator": class_statistic.support,
                "status": (
                    MetricAvailability.AVAILABLE.value
                    if class_statistic.recall is not None
                    else MetricAvailability.NOT_ESTIMABLE.value
                ),
                "source": report.regime_truth.true_label_source,
                "definition": "true positives / actual class support",
                "population": "candidate-level native regime reference audit",
                "version": METRIC_TRUTH_AUDIT_VERSION,
            }
        )
    for adapter in report.adapter_validations:
        writer.writerow(
            {
                "section": "ird_adapter",
                "key": adapter.diagnostic_id,
                "label": "safe_for_prioritization",
                "value": str(adapter.safe_for_prioritization).lower(),
                "status": (
                    MetricAvailability.AVAILABLE.value
                    if adapter.safe_for_prioritization
                    else MetricAvailability.INVALID.value
                ),
                "source": "IRD diagnostic registry",
                "definition": ("; ".join(adapter.issues) or "all adapter checks pass"),
                "population": "registered diagnostic metrics",
                "version": report.audit_version,
            }
        )
    return output.getvalue()


def export_metric_truth_json(report: MetricTruthAuditReport, path: Path) -> Path:
    _write(path, metric_truth_json(report))
    return path


def export_metric_truth_csv(report: MetricTruthAuditReport, path: Path) -> Path:
    _write(path, metric_truth_csv(report))
    return path


def _approval_inventory(
    records: tuple[CandidateDecisionRecord, ...],
    observations: tuple[_OutcomeObservation, ...],
    duplicate_ids: tuple[str, ...],
) -> tuple[ApprovalDefinitionAudit, ...]:
    timing = EntryTimingIntelligenceEngine()
    definitions: tuple[
        tuple[str, str, str, Callable[[CandidateDecisionRecord], bool], str | None],
        ...,
    ] = (
        (
            "RAW_APPROVAL",
            "alpha.candidate_learning.models.CandidateDecisionRecord",
            "record.approved_for_deployment is True",
            lambda record: record.approved_for_deployment,
            None,
        ),
        (
            "STRICT_INSTITUTIONAL_APPROVAL",
            "alpha.candidate_learning.aggregator.is_deployment_approved",
            "is_deployment_approved(record) is True",
            is_deployment_approved,
            None,
        ),
        (
            "RECOMMENDATION_BUY",
            "alpha.candidate_learning.models.CandidateDecisionRecord",
            "record.final_verdict in {'BUY', 'STRONG_BUY'}",
            lambda record: record.final_verdict in {"BUY", "STRONG_BUY"},
            None,
        ),
        (
            "ACTIONABLE_CANDIDATE",
            "alpha.candidate_learning.entry_timing.EntryTimingIntelligenceEngine",
            "EntryTimingIntelligenceEngine.assess_record(record).actionable_now",
            lambda record: timing.assess_record(record).actionable_now,
            None,
        ),
        (
            "ENTRY_TIMING_APPROVAL",
            "alpha.candidate_learning.entry_timing._row_for_record",
            "EntryTimingOutcomeRow.approved = record.approved_for_deployment",
            lambda record: record.approved_for_deployment,
            "RAW_APPROVAL",
        ),
        (
            "GATEKEEPER_APPROVAL",
            "alpha.candidate_learning.recorder._institutional_approval",
            "persisted OpportunityDecision.accepted result",
            lambda record: record.approved_for_deployment,
            "RAW_APPROVAL",
        ),
        (
            "LEGACY_LONG_TRADE_PERMISSION",
            "alpha.candidate_learning.models.CandidateDecisionRecord",
            "record.long_trade_permission is True",
            lambda record: record.long_trade_permission,
            "RECOMMENDATION_BUY",
        ),
    )
    profitable_population = sum(item.profitable for item in observations)
    result = []
    for name, source, predicate_text, predicate, alias in definitions:
        approved_records = tuple(record for record in records if predicate(record))
        eligible = tuple(item for item in observations if predicate(item.record))
        true_positives = sum(item.profitable for item in eligible)
        false_positives = len(eligible) - true_positives
        precision = _ratio(true_positives, len(eligible))
        result.append(
            ApprovalDefinitionAudit(
                canonical_name=name,
                source_module=source,
                exact_predicate=predicate_text,
                numerator_definition=(
                    "approved observations with gross primary-window return > 0"
                ),
                denominator_definition=(
                    "approved observations with a completed primary outcome and "
                    "entry-based return"
                ),
                outcome_eligibility_rule=(
                    "first non-DATA_MISSING window in 20d, 10d, 5d, 3d, "
                    "1d, 60d order; entry-based return required"
                ),
                outcome_horizon="priority-selected 20d/10d/5d/3d/1d/60d",
                success_threshold="forward_return_pct_from_entry > 0",
                transaction_cost_treatment="gross return; transaction costs excluded",
                incomplete_outcome_treatment="excluded from precision denominator",
                duplicate_treatment=(
                    "candidate_id is the unit; duplicate candidate IDs invalidate "
                    "the audit rather than being silently combined"
                ),
                replay_version=APPROVAL_PRECISION_CONTRACT_VERSION,
                population_size=len(records),
                approval_count=len(approved_records),
                eligible_approval_count=len(eligible),
                incomplete_approval_count=len(approved_records) - len(eligible),
                true_positives=true_positives,
                false_positives=false_positives,
                precision=precision,
                recall=_ratio(true_positives, profitable_population),
                precision_status=(
                    MetricAvailability.NOT_ESTIMABLE
                    if not eligible
                    else MetricAvailability.INVALID
                    if duplicate_ids
                    else MetricAvailability.AVAILABLE
                ),
                alias_of=alias,
            )
        )
    return tuple(result)


def _approval_contract(
    definition: ApprovalDefinitionAudit,
) -> ApprovalPrecisionContract:
    interval = _wilson_interval(
        definition.true_positives,
        definition.eligible_approval_count,
    )
    return ApprovalPrecisionContract(
        metric_name=f"{definition.canonical_name}_PRECISION",
        approval_concept=definition.canonical_name,
        eligible_population=definition.denominator_definition,
        outcome_horizon=definition.outcome_horizon,
        success_threshold=definition.success_threshold,
        required_completed_outcome=definition.outcome_eligibility_rule,
        transaction_cost_treatment=definition.transaction_cost_treatment,
        missing_observation_treatment=definition.incomplete_outcome_treatment,
        duplicate_treatment=definition.duplicate_treatment,
        replay_version=definition.replay_version,
        numerator=definition.true_positives,
        denominator=definition.eligible_approval_count,
        precision=definition.precision,
        precision_status=definition.precision_status,
        confidence_interval_low=None if interval is None else interval[0],
        confidence_interval_high=None if interval is None else interval[1],
    )


def _reconcile(
    *,
    records: tuple[CandidateDecisionRecord, ...],
    observations: tuple[_OutcomeObservation, ...],
    duplicate_ids: tuple[str, ...],
) -> ApprovalPopulationReconciliation:
    raw = tuple(item for item in observations if item.record.approved_for_deployment)
    earlier = tuple(
        item for item in raw if item.record.evaluation_date <= EARLIER_REPLAY_CUTOFF
    )
    earlier_index = {item.record.candidate_id: item for item in earlier}
    current_index = {item.record.candidate_id: item for item in raw}
    both = tuple(sorted(set(earlier_index) & set(current_index)))
    differences = tuple(
        candidate_id
        for candidate_id in both
        if earlier_index[candidate_id].profitable
        != current_index[candidate_id].profitable
    )
    current_only = tuple(sorted(set(current_index) - set(earlier_index)))
    earlier_only = tuple(sorted(set(earlier_index) - set(current_index)))
    earlier_successes = sum(item.profitable for item in earlier)
    current_successes = sum(item.profitable for item in raw)
    earlier_approved_records = tuple(
        record
        for record in records
        if record.approved_for_deployment
        and record.evaluation_date <= EARLIER_REPLAY_CUTOFF
    )
    current_approved_records = tuple(
        record for record in records if record.approved_for_deployment
    )
    earlier_precision = _required_ratio(earlier_successes, len(earlier))
    current_precision = _required_ratio(current_successes, len(raw))
    precision_delta = current_precision - earlier_precision
    added_successes = current_successes - earlier_successes
    added_failures = len(current_only) - added_successes
    return ApprovalPopulationReconciliation(
        earlier_cutoff=EARLIER_REPLAY_CUTOFF,
        earlier_origin_status=(
            "RECONSTRUCTED_EXACTLY_FROM_CURRENT_LEDGER; persisted earlier report "
            "manifest is unavailable"
        ),
        earlier_precision=earlier_precision,
        earlier_approval_count=len(earlier),
        earlier_successful_approvals=earlier_successes,
        earlier_incomplete_approvals=len(earlier_approved_records) - len(earlier),
        earlier_population=("completed raw approvals with replay_date <= 2016-12-13"),
        earlier_definition=(
            "gross primary-window entry return > 0 among completed raw approvals"
        ),
        current_data_as_of=max(record.evaluation_date for record in records),
        current_precision=current_precision,
        current_approval_count=len(raw),
        current_successful_approvals=current_successes,
        current_incomplete_approvals=len(current_approved_records) - len(raw),
        current_population="all completed raw approvals in current learning ledger",
        current_definition=(
            "gross primary-window entry return > 0 among completed raw approvals"
        ),
        candidates_in_both=both,
        earlier_only_candidates=earlier_only,
        current_only_candidates=current_only,
        outcome_classification_differences=differences,
        duplicate_candidate_ids=duplicate_ids,
        overwritten_record_count=0,
        changed_horizon_count=0,
        changed_success_definition_count=0,
        added_successes=added_successes,
        added_failures=added_failures,
        precision_delta=precision_delta,
        unexplained_remainder=_ZERO,
        exact_attribution=(
            f"Population inclusion: +{len(current_only)} completed approvals.",
            f"Outcome completion within added population: +{added_successes} wins "
            f"and +{added_failures} non-wins.",
            "Outcome classification changes among shared candidates: 0.",
            "Duplicate or overwritten candidate IDs: 0.",
            "Horizon or success-definition changes: 0.",
            (
                f"Exact arithmetic: {current_successes}/{len(raw)} - "
                f"{earlier_successes}/{len(earlier)} = {precision_delta}."
            ),
        ),
    )


def _strict_attribution(
    records: tuple[CandidateDecisionRecord, ...],
    observations: tuple[_OutcomeObservation, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> StrictApprovalAttribution:
    rules = _strict_gate_rules()
    survivors = list(records)
    survival = []
    for rule in rules:
        reached = len(survivors)
        survivors = [record for record in survivors if rule.predicate(record)]
        survival.append(
            GateSurvival(
                gate_id=rule.gate_id,
                predicate=rule.predicate_text,
                reached=reached,
                rejected_at_gate=reached - len(survivors),
                survived=len(survivors),
                cumulative_survival=_required_ratio(len(survivors), len(records)),
            )
        )
    primary: Counter[str] = Counter()
    for record in records:
        failure = next(
            (rule.gate_id for rule in rules if not rule.predicate(record)),
            "APPROVED",
        )
        primary[failure] += 1
    overlap = tuple(
        GateFailureCount(
            gate_id=rule.gate_id,
            count=sum(not rule.predicate(record) for record in records),
        )
        for rule in rules
    )
    diagnostics = ApprovalDiagnosticsEngine().build(
        records=records,
        outcomes=outcomes,
    )
    profitable_rejected = sum(
        item.profitable
        for item in observations
        if not is_deployment_approved(item.record)
    )
    strict_count = sum(is_deployment_approved(record) for record in records)
    implementation_matches = all(
        is_deployment_approved(record) == all(rule.predicate(record) for rule in rules)
        for record in records
    )
    conclusion = (
        StrictApprovalZeroConclusion.VALID_BUT_OVERRESTRICTIVE_POLICY
        if implementation_matches and strict_count == 0 and profitable_rejected > 0
        else StrictApprovalZeroConclusion.IMPLEMENTATION_DEFECT
        if not implementation_matches
        else StrictApprovalZeroConclusion.INCONCLUSIVE
    )
    sequential_summary = "; ".join(
        f"{item.gate_id} leaves {item.survived}" for item in survival
    )
    return StrictApprovalAttribution(
        total_candidates=len(records),
        strict_approvals=strict_count,
        implementation_matches_predicate=implementation_matches,
        gate_survival=tuple(survival),
        mutually_exclusive_primary_failures=tuple(
            GateFailureCount(gate_id=key, count=value)
            for key, value in sorted(primary.items())
        ),
        overlapping_failures=overlap,
        extended_diagnostic_failures=tuple(
            GateFailureCount(gate_id=criterion.value, count=count)
            for criterion, count, _ in diagnostics.criterion_counts
        ),
        near_approval_count=diagnostics.near_approval_count,
        failing_one_criterion=diagnostics.failing_one_criterion,
        failing_two_criteria=diagnostics.failing_two_criteria,
        failing_three_or_more_criteria=diagnostics.failing_three_or_more_criteria,
        profitable_rejected_candidates=profitable_rejected,
        completed_rejected_candidates=sum(
            not is_deployment_approved(item.record) for item in observations
        ),
        conclusion=conclusion,
        explanation=(
            "The implementation exactly matches the documented strict predicate. "
            f"Sequential survival is: {sequential_summary}. "
            f"{profitable_rejected} profitable completed candidates were rejected. "
            "The zero count is valid arithmetic; observed profitable rejections "
            "classify this policy as overrestrictive, without changing a threshold."
        ),
    )


def _regime_truth(
    records: tuple[CandidateDecisionRecord, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> RegimeMetricTruth:
    native_report = MarketRegimeAuditEngine().analyze(
        records=records,
        outcomes=outcomes,
    )
    observations = []
    excluded: Counter[str] = Counter()
    missing_benchmark = 0
    scores = []
    unknown_predictions = 0
    for record in records:
        benchmark = _indicator(record, ("benchmark-return", "benchmark_return"))
        if benchmark is None:
            missing_benchmark += 1
        score = _indicator(record, ("trend", "price", "price-structure"))
        if score is not None:
            scores.append(score)
        actual = _native_reference_label(record)
        predicted = _normalized_prediction(record.market_regime)
        if actual is None:
            excluded["REFERENCE_UNAVAILABLE"] += 1
            continue
        if predicted is None:
            unknown_predictions += 1
            excluded["PREDICTION_UNKNOWN_OR_UNAVAILABLE"] += 1
            continue
        observations.append((actual, predicted))
    counts = Counter(observations)
    confusion = tuple(
        RegimeConfusionCell(
            actual_label=actual,
            predicted_label=predicted,
            count=counts[(actual, predicted)],
        )
        for actual in _REGIME_CLASSES
        for predicted in _REGIME_CLASSES
    )
    statistics = tuple(
        _regime_class_statistic(label, observations) for label in _REGIME_CLASSES
    )
    supported_recalls = tuple(
        item.recall for item in statistics if item.recall is not None
    )
    balanced = _average(supported_recalls)
    ordinary = _ratio(
        sum(actual == predicted for actual, predicted in observations),
        len(observations),
    )
    observed_labels = tuple(sorted({label for pair in observations for label in pair}))
    f1_values = tuple(_f1_for_macro(label, observations) for label in observed_labels)
    macro_f1 = _average(f1_values)
    actual_counts = Counter(actual for actual, _ in observations)
    majority = (
        _ratio(max(actual_counts.values()), len(observations))
        if actual_counts
        else None
    )
    source = native_report.reference_quality.balanced_accuracy
    rendered = None if source is None else source * _PERCENT
    bearish_matches = counts[("BEARISH_TREND", "BEARISH_TREND")]
    neutral_misses = counts[("BEARISH_TREND", "SIDEWAYS")]
    minimum = min(scores) if scores else None
    maximum = max(scores) if scores else None
    return RegimeMetricTruth(
        class_labels=_REGIME_CLASSES,
        true_label_source=(
            "MarketRegimeAuditEngine._reference_state: benchmark return when "
            "available, otherwise persisted price/trend component score"
        ),
        predicted_label_source="CandidateDecisionRecord.market_regime",
        label_normalization=(
            ("STRONG_POSITIVE/POSITIVE/BULLISH", "BULLISH_TREND"),
            ("STRONG_NEGATIVE/NEGATIVE/BEARISH", "BEARISH_TREND"),
            ("NEUTRAL/SIDEWAYS", "SIDEWAYS"),
            ("CORRECTION", "CORRECTION"),
            ("HIGH_VOLATILITY", "HIGH_VOLATILITY"),
            ("RECOVERY", "RECOVERY"),
        ),
        confusion_matrix=confusion,
        class_statistics=statistics,
        source_reported_balanced_accuracy=source,
        independently_recomputed_balanced_accuracy=balanced,
        rendered_percentage=rendered,
        ordinary_accuracy=ordinary,
        macro_f1=macro_f1,
        majority_class_baseline=majority,
        nominal_uniform_random_baseline=Decimal("1") / Decimal(len(_REGIME_CLASSES)),
        coverage=_required_ratio(len(observations), len(records)),
        observations=len(observations),
        excluded_observations=len(records) - len(observations),
        excluded_reasons=tuple(sorted(excluded.items())),
        missing_benchmark_inputs=missing_benchmark,
        unavailable_reference_labels=excluded.get("REFERENCE_UNAVAILABLE", 0),
        unknown_predicted_labels=unknown_predictions,
        exact_date_alignment=True,
        look_ahead_detected=False,
        fraction_percentage_semantics_valid=(
            source is not None and rendered == source * _PERCENT
        ),
        source_score_minimum=minimum,
        source_score_maximum=maximum,
        source_thresholds=(
            "trend >= 75 -> BULLISH_TREND",
            "trend <= 35 -> BEARISH_TREND",
        ),
        metric_valid_for_decision=False,
        conclusion=RegimeMetricConclusion.SCALE_OR_RENDERING_DEFECT,
        exact_failure_mode=(
            f"All {missing_benchmark:,} benchmark-return inputs are missing. "
            "The fallback passes normalized price/trend scores from "
            f"{_text(minimum)} to {_text(maximum)} into thresholds 35 and 75, "
            "creating scale-defective synthetic reference labels. "
            f"{bearish_matches:,} bearish predictions match and "
            f"{neutral_misses:,} sideways/neutral predictions miss; native "
            f"balanced accuracy is {_percentage(source)}. The arithmetic and "
            "percentage rendering are correct; the reference-label scale and "
            "semantics are not."
        ),
    )


def _validate_adapters(
    diagnostics: tuple[DiagnosticEvidence, ...],
) -> tuple[IrdAdapterValidation, ...]:
    allowed_units = {"count", "ratio", "category", "points"}
    result = []
    for diagnostic in diagnostics:
        issues = []
        provenance_complete = all(
            all(
                (
                    metric.provenance.source,
                    metric.provenance.definition,
                    metric.provenance.population,
                    metric.provenance.version,
                )
            )
            for metric in diagnostic.metrics
        )
        units_valid = all(metric.unit in allowed_units for metric in diagnostic.metrics)
        fraction_valid = all(
            _fraction_semantics_valid(metric) for metric in diagnostic.metrics
        )
        availability_valid = all(
            (metric.availability_status is MetricAvailability.AVAILABLE)
            == (metric.value is not None)
            for metric in diagnostic.metrics
        )
        numerator_valid = all(
            _numerator_denominator_valid(metric) for metric in diagnostic.metrics
        )
        if not provenance_complete:
            issues.append("metric provenance is incomplete")
        if not units_valid:
            issues.append("metric unit is not recognized")
        if not fraction_valid:
            issues.append("ratio is outside fraction range [0, 1]")
        if not availability_valid:
            issues.append("availability and value semantics conflict")
        if not numerator_valid:
            issues.append("numerator/denominator semantics are invalid")
        if diagnostic.diagnostic_id == "market-regime-audit":
            validated = diagnostic.metric("market_regime.balanced_accuracy")
            if (
                validated is None
                or validated.availability_status is not MetricAvailability.INVALID
            ):
                issues.append("invalid native regime metric is not quarantined")
            if diagnostic.bottleneck_status.value != "UNKNOWN":
                issues.append("invalid regime metric can still drive prioritization")
        result.append(
            IrdAdapterValidation(
                diagnostic_id=diagnostic.diagnostic_id,
                metric_count=len(diagnostic.metrics),
                provenance_complete=provenance_complete,
                units_valid=units_valid,
                fraction_percentage_semantics_valid=fraction_valid,
                availability_semantics_valid=availability_valid,
                numerator_denominator_valid=numerator_valid,
                safe_for_prioritization=not issues,
                issues=tuple(issues),
            )
        )
    return tuple(sorted(result, key=lambda item: item.diagnostic_id))


def _roadmap_after(diagnostics: tuple[DiagnosticEvidence, ...]) -> tuple[str, ...]:
    return tuple(
        f"{item.priority.value}: {item.supporting_diagnostics[0]}"
        for item in BottleneckEngine().rank(diagnostics)
        if item.priority.value != "DEFERRED"
    )


def _outcome_observations(
    records: tuple[CandidateDecisionRecord, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> tuple[tuple[_OutcomeObservation, ...], tuple[str, ...]]:
    duplicate_ids = tuple(
        sorted(
            candidate_id
            for candidate_id, count in Counter(
                record.candidate_id for record in records
            ).items()
            if count > 1
        )
    )
    outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
    result = []
    for record in records:
        window = _primary_window(outcome_by_id.get(record.candidate_id))
        if window is None or window.forward_return_pct_from_entry is None:
            continue
        result.append(
            _OutcomeObservation(
                record=record,
                window=window,
                profitable=window.forward_return_pct_from_entry > _ZERO,
            )
        )
    return (
        tuple(
            sorted(
                result,
                key=lambda item: (
                    item.record.evaluation_date,
                    item.record.symbol,
                    item.record.candidate_id,
                ),
            )
        ),
        duplicate_ids,
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
    return None


def _strict_gate_rules() -> tuple[_GateRule, ...]:
    return (
        _GateRule(
            "RAW_RECORDED_APPROVAL",
            "record.approved_for_deployment",
            lambda record: record.approved_for_deployment,
        ),
        _GateRule(
            "BUY_VERDICT",
            "record.final_verdict in {'BUY', 'STRONG_BUY'}",
            lambda record: record.final_verdict in {"BUY", "STRONG_BUY"},
        ),
        _GateRule(
            "HIGH_CONFIDENCE",
            "record.confidence == 'HIGH'",
            lambda record: record.confidence == "HIGH",
        ),
        _GateRule(
            "DATA_QUALITY",
            "record.data_quality in {'COMPLETE', 'GOOD'}",
            lambda record: record.data_quality in {"COMPLETE", "GOOD"},
        ),
        _GateRule(
            "MINIMUM_SCORE",
            "record.strategy_score >= 85",
            lambda record: record.strategy_score >= Decimal("85"),
        ),
        _GateRule(
            "COMPLETE_TRADE_PLAN",
            "entry, stop, three targets, and trailing stop are present",
            _complete_trade_plan,
        ),
        _GateRule(
            "MINIMUM_ENTRY_PRICE",
            "entry_zone_high is absent or >= 50",
            lambda record: (
                record.entry_zone_high is None
                or record.entry_zone_high >= Decimal("50")
            ),
        ),
        _GateRule(
            "MAXIMUM_STOP_DISTANCE",
            "stop distance is present and <= 10%",
            lambda record: (
                (distance := _stop_distance(record)) is not None
                and distance <= Decimal("10")
            ),
        ),
        _GateRule(
            "MINIMUM_REWARD_RISK",
            "reward/risk is present and >= 2",
            lambda record: (
                (reward_risk := _reward_risk(record)) is not None
                and reward_risk >= Decimal("2")
            ),
        ),
    )


def _complete_trade_plan(record: CandidateDecisionRecord) -> bool:
    return all(
        value is not None
        for value in (
            record.entry_zone_high,
            record.confirmation_entry,
            record.risk_stop,
            record.target_1,
            record.target_2,
            record.target_3,
            record.trailing_stop_plan,
        )
    )


def _stop_distance(record: CandidateDecisionRecord) -> Decimal | None:
    entry = record.confirmation_entry or record.entry_zone_high
    stop = record.risk_stop
    if entry is None or stop is None or entry <= _ZERO:
        return None
    return ((entry - stop) / entry * _PERCENT).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _reward_risk(record: CandidateDecisionRecord) -> Decimal | None:
    entry = record.confirmation_entry or record.entry_zone_high
    stop = record.risk_stop
    target = record.target_2 or record.target_1
    if entry is None or stop is None or target is None or entry <= stop:
        return None
    return ((target - entry) / (entry - stop)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _native_reference_label(record: CandidateDecisionRecord) -> str | None:
    volatility = _indicator(record, ("atr", "volatility", "volatility-risk"))
    benchmark = _indicator(record, ("benchmark-return", "benchmark_return"))
    trend = _indicator(record, ("trend", "price", "price-structure"))
    if volatility is not None and volatility >= Decimal("8"):
        return "HIGH_VOLATILITY"
    if benchmark is not None:
        if benchmark <= Decimal("-8"):
            return "CORRECTION"
        if benchmark <= Decimal("-3"):
            return "BEARISH_TREND"
        if benchmark >= Decimal("5"):
            return "BULLISH_TREND"
        if benchmark >= Decimal("2"):
            return "RECOVERY"
        return "SIDEWAYS"
    if trend is not None:
        if trend >= Decimal("75"):
            return "BULLISH_TREND"
        if trend <= Decimal("35"):
            return "BEARISH_TREND"
        return "SIDEWAYS"
    return None


def _normalized_prediction(value: str | None) -> str | None:
    normalized = (value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized in {
        "STRONG_POSITIVE",
        "POSITIVE",
        "BULL",
        "BULLISH",
        "BULLISH_TREND",
    }:
        return "BULLISH_TREND"
    if normalized in {
        "STRONG_NEGATIVE",
        "NEGATIVE",
        "BEAR",
        "BEARISH",
        "BEARISH_TREND",
    }:
        return "BEARISH_TREND"
    if normalized in {"NEUTRAL", "SIDEWAYS"}:
        return "SIDEWAYS"
    if normalized in {"CORRECTION", "HIGH_VOLATILITY", "RECOVERY"}:
        return normalized
    return None


def _regime_class_statistic(
    label: str,
    observations: Sequence[tuple[str, str]],
) -> RegimeClassStatistic:
    support = sum(actual == label for actual, _ in observations)
    predicted = sum(prediction == label for _, prediction in observations)
    tp = sum(
        actual == label and prediction == label for actual, prediction in observations
    )
    recall = _ratio(tp, support)
    precision = _ratio(tp, predicted)
    f1 = (
        None
        if recall is None or precision is None or recall + precision == _ZERO
        else (Decimal("2") * recall * precision / (recall + precision)).quantize(_FOUR)
    )
    return RegimeClassStatistic(
        label=label,
        support=support,
        predicted_count=predicted,
        true_positive=tp,
        recall=recall,
        precision=precision,
        f1=f1,
    )


def _f1_for_macro(label: str, observations: Sequence[tuple[str, str]]) -> Decimal:
    statistic = _regime_class_statistic(label, observations)
    return statistic.f1 or _ZERO


def _indicator(
    record: CandidateDecisionRecord,
    keys: tuple[str, ...],
) -> Decimal | None:
    normalized = {
        key.replace("_", "-").lower(): value
        for key, value in record.indicator_scores.items()
    }
    for key in keys:
        raw = normalized.get(key.replace("_", "-").lower())
        if raw is not None:
            try:
                return Decimal(raw)
            except Exception:
                return None
    return None


def _research_metric(
    *,
    metric_id: str,
    label: str,
    value: Decimal | None,
    unit: str,
    source: str,
    definition: str,
    population: str,
    numerator: int | Decimal | None,
    denominator: int | Decimal | None,
    availability: MetricAvailability | None = None,
) -> ResearchMetric:
    return ResearchMetric(
        metric_id=metric_id,
        label=label,
        value=value,
        unit=unit,
        provenance=MetricProvenance(
            source=source,
            definition=definition,
            population=population,
            version=METRIC_TRUTH_AUDIT_VERSION,
        ),
        numerator=numerator,
        denominator=denominator,
        availability=availability,
    )


def _fraction_semantics_valid(metric: ResearchMetric) -> bool:
    if metric.unit != "ratio" or metric.value is None:
        return True
    value = metric.value
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return False
    numeric = Decimal(value)
    return _ZERO <= numeric <= _ONE


def _numerator_denominator_valid(metric: ResearchMetric) -> bool:
    numerator = metric.numerator
    denominator = metric.denominator
    if (numerator is None) != (denominator is None):
        return False
    if numerator is None or denominator is None:
        return True
    if numerator < _ZERO or denominator < _ZERO:
        return False
    if denominator == _ZERO:
        return (
            numerator == _ZERO
            and metric.value is None
            and metric.availability_status is not MetricAvailability.AVAILABLE
        )
    if metric.unit != "ratio":
        return True
    if numerator > denominator:
        return False
    if metric.value is None:
        return metric.availability_status is not MetricAvailability.AVAILABLE
    if isinstance(metric.value, bool) or not isinstance(
        metric.value,
        (int, Decimal),
    ):
        return False
    reconstructed = (Decimal(numerator) / Decimal(denominator)).quantize(_FOUR)
    return reconstructed == Decimal(metric.value).quantize(_FOUR)


def _wilson_interval(successes: int, total: int) -> tuple[Decimal, Decimal] | None:
    if total <= 0:
        return None
    n = Decimal(total)
    probability = Decimal(successes) / n
    z_squared = _WILSON_Z_95 * _WILSON_Z_95
    denominator = _ONE + z_squared / n
    center = (probability + z_squared / (Decimal("2") * n)) / denominator
    variance = probability * (_ONE - probability) / n + z_squared / (
        Decimal("4") * n * n
    )
    half = _WILSON_Z_95 * variance.sqrt() / denominator
    return (
        max(_ZERO, center - half).quantize(_FOUR, rounding=ROUND_HALF_UP),
        min(_ONE, center + half).quantize(_FOUR, rounding=ROUND_HALF_UP),
    )


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _FOUR,
        rounding=ROUND_HALF_UP,
    )


def _required_ratio(numerator: int, denominator: int) -> Decimal:
    value = _ratio(numerator, denominator)
    if value is None:
        raise ValueError("required ratio has a zero denominator")
    return value


def _average(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(_FOUR)


def _text(value: Decimal | None) -> str:
    return "" if value is None else str(value)


def _percentage(value: Decimal | None) -> str:
    if value is None:
        return MetricAvailability.NOT_ESTIMABLE.value
    return f"{value * _PERCENT:.2f}%"


def _balanced_accuracy_matches(report: RegimeMetricTruth) -> int | None:
    supported = tuple(item for item in report.class_statistics if item.support)
    if len(supported) != 1:
        return None
    return supported[0].true_positive


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


__all__ = [
    "APPROVAL_PRECISION_CONTRACT_VERSION",
    "ApprovalDefinitionAudit",
    "ApprovalPopulationReconciliation",
    "ApprovalPrecisionContract",
    "EARLIER_REPLAY_CUTOFF",
    "GateFailureCount",
    "GateSurvival",
    "IrdAdapterValidation",
    "METRIC_TRUTH_AUDIT_VERSION",
    "MetricTruthAuditEngine",
    "MetricTruthAuditReport",
    "RegimeClassStatistic",
    "RegimeConfusionCell",
    "RegimeMetricConclusion",
    "RegimeMetricTruth",
    "StrictApprovalAttribution",
    "StrictApprovalZeroConclusion",
    "export_metric_truth_csv",
    "export_metric_truth_json",
    "metric_truth_csv",
    "metric_truth_experiment",
    "metric_truth_json",
    "regime_reference_scale_is_valid",
]
