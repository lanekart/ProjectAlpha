"""Deterministic text rendering for Institutional Research Director reports."""

from __future__ import annotations

from decimal import Decimal

from alpha.research.metric_truth_audit import (
    ApprovalPrecisionContract,
    MetricTruthAuditReport,
)
from alpha.research.models import (
    DiagnosticEvidence,
    EngineeringRoiReport,
    ExecutiveResearchBrief,
    RankedBottleneck,
    RegisteredResearchExperiment,
    ResearchMetric,
    ResearchRoadmap,
    RoadmapPriority,
)


def render_bottlenecks(bottlenecks: tuple[RankedBottleneck, ...]) -> str:
    lines = [
        "Institutional Research Director - Bottlenecks",
        "PRODUCTION_INFLUENCE=false",
        f"Opportunities Assessed: {len(bottlenecks)}",
    ]
    if not bottlenecks:
        lines.append("No diagnostic evidence is registered.")
        return _finish(lines)
    for index, item in enumerate(bottlenecks, start=1):
        lines.extend(
            (
                "",
                f"{index}. [{item.priority.value}] {item.title}",
                f"   Subsystem: {item.subsystem.value}",
                f"   Status: {item.status.value}",
                f"   Current Maturity: {item.current_maturity.value}",
                f"   Evidence Quality: {item.evidence_quality.value}",
                f"   Confidence: {item.confidence.value}",
                f"   Engineering Complexity: {item.engineering_complexity.value}",
                f"   Dependencies: {_joined(item.dependencies)}",
                f"   Supporting Diagnostics: {_joined(item.supporting_diagnostics)}",
                f"   Evidence: {item.evidence_summary}",
                f"   Next Research Action: {item.recommended_action}",
            )
        )
    return _finish(lines)


def render_roadmap(roadmap: ResearchRoadmap) -> str:
    lines = [
        "Institutional Research Director - Evidence Roadmap",
        "PRODUCTION_INFLUENCE=false",
    ]
    for priority in (
        RoadmapPriority.P0,
        RoadmapPriority.P1,
        RoadmapPriority.P2,
        RoadmapPriority.DEFERRED,
    ):
        lines.extend(("", priority.value))
        items = roadmap.items_for(priority)
        if not items:
            lines.append("- None")
            continue
        for item in items:
            lines.extend(
                (
                    f"- {item.title}",
                    f"  Project: {item.project_id}",
                    f"  Subsystem: {item.subsystem.value}",
                    f"  Supporting Diagnostics: {_joined(item.supporting_diagnostics)}",
                    f"  Dependencies: {_joined(item.dependencies)}",
                    f"  Basis: {item.rationale}",
                )
            )
    return _finish(lines)


def render_roi(report: EngineeringRoiReport) -> str:
    lines = [
        "Institutional Research Director - Engineering ROI",
        "PRODUCTION_INFLUENCE=false",
        "",
        "Measured ROI",
        f"Completed Experiments: {report.completed_experiments}",
    ]
    if not report.measured:
        lines.append("- Unavailable: no comparable completed experiment deltas.")
    else:
        for measured_item in report.measured:
            lines.append(
                f"- {measured_item.experiment_id} / "
                f"{measured_item.metric_label}: "
                f"{measured_item.baseline} -> {measured_item.treatment}; "
                f"delta {measured_item.absolute_change} {measured_item.unit}; "
                f"confidence {measured_item.confidence.value}"
            )
    lines.extend(
        (
            "",
            "Estimated ROI",
            "Estimated values are not measured and are never merged with measured ROI.",
        )
    )
    if not report.estimated:
        lines.append("- No proven bottleneck requires an estimate.")
    else:
        for estimated_item in report.estimated:
            lines.append(
                f"- {estimated_item.bottleneck_id}: UNKNOWN. "
                f"{estimated_item.explanation}"
            )
    lines.extend(
        (
            "",
            "Highest ROI Completed Project: "
            f"{report.highest_roi_completed_project or 'Unavailable'}",
            f"Comparison Guardrail: {report.comparison_warning}",
        )
    )
    return _finish(lines)


def render_registry(
    *,
    diagnostics: tuple[DiagnosticEvidence, ...],
    experiments: tuple[RegisteredResearchExperiment, ...],
) -> str:
    lines = [
        "Institutional Research Director - Registries",
        "PRODUCTION_INFLUENCE=false",
        "",
        f"Diagnostic Registry ({len(diagnostics)})",
    ]
    if not diagnostics:
        lines.append("- Empty")
    for diagnostic in diagnostics:
        lines.extend(
            (
                f"- {diagnostic.diagnostic_id}: {diagnostic.title}",
                f"  Subsystem: {diagnostic.subsystem.value}",
                f"  State: {diagnostic.state.value}",
                f"  Source: {diagnostic.source_module}",
                f"  Version: {diagnostic.source_version}",
                "  Metrics: "
                f"{_joined(tuple(metric.metric_id for metric in diagnostic.metrics))}",
            )
        )
    lines.extend(("", f"Research Experiment Registry ({len(experiments)})"))
    if not experiments:
        lines.append("- No governed experiments recorded.")
    for experiment in experiments:
        lines.extend(
            (
                f"- {experiment.experiment_id}: {experiment.title}",
                f"  Date: {experiment.experiment_date.isoformat()}",
                f"  Subsystem: {experiment.subsystem.value}",
                "  Status / Decision: "
                f"{experiment.status.value} / {experiment.decision.value}",
                f"  Statistical Confidence: {experiment.statistical_confidence.value}",
                f"  Evidence Sources: {_joined(experiment.evidence_sources)}",
                f"  Metrics: {_joined(experiment.metrics)}",
            )
        )
    lines.extend(
        (
            "",
            "Metric Provenance Contract:",
            "- Every metric retains source, definition, population, and version.",
            "- Definition-incompatible metrics are never compared.",
        )
    )
    return _finish(lines)


def render_briefing(brief: ExecutiveResearchBrief) -> str:
    lines = [
        "Institutional Research Director - Executive Research Brief",
        "PRODUCTION_INFLUENCE=false",
        f"Diagnostics Considered: {brief.diagnostics_considered}",
        "",
        f"Current Replay Readiness: {brief.current_replay_readiness}",
        f"Largest Proven Bottleneck: {brief.largest_proven_bottleneck}",
        f"Largest Unknown: {brief.largest_unknown}",
        f"Highest Confidence Finding: {brief.highest_confidence_finding}",
        f"Highest ROI Completed Project: {brief.highest_roi_completed_project}",
        f"Highest Priority Future Project: {brief.highest_priority_future_project}",
        f"Recommended Next Sprint: {brief.recommended_next_sprint}",
        f"Overall Research Confidence: {brief.overall_research_confidence.value}",
        "Confidence Scope: diagnostic evidence, not production readiness.",
        "",
        "Initial Evidence",
    ]
    if not brief.initial_evidence:
        lines.append("- None available")
    else:
        lines.extend(f"- {render_metric(metric)}" for metric in brief.initial_evidence)
    return _finish(lines)


def render_metric(metric: ResearchMetric) -> str:
    value = _metric_value(metric)
    provenance = metric.provenance
    fraction = (
        ""
        if metric.numerator is None and metric.denominator is None
        else f"; numerator={metric.numerator}; denominator={metric.denominator}"
    )
    return (
        f"{metric.label}: {value} [{metric.availability_status.value}] | "
        f"source={provenance.source}; "
        f"definition={provenance.definition}; population={provenance.population}; "
        f"version={provenance.version}{fraction}"
    )


def _metric_value(metric: ResearchMetric) -> str:
    value = metric.value
    if value is None:
        return metric.availability_status.value
    if metric.unit == "ratio" and isinstance(value, Decimal):
        return f"{value * Decimal('100'):.2f}%"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def render_approval_precision_truth(report: MetricTruthAuditReport) -> str:
    lines = [
        "Approval Precision Truth Audit",
        "PRODUCTION_INFLUENCE=false",
        f"Audit Version: {report.audit_version}",
        f"Data As Of: {report.data_as_of.isoformat()}",
        "",
        "Approval Definition Inventory",
    ]
    for definition in report.approval_definitions:
        lines.extend(
            (
                f"- {definition.canonical_name}",
                f"  Source: {definition.source_module}",
                f"  Predicate: {definition.exact_predicate}",
                f"  Alias Of: {definition.alias_of or 'None'}",
                "  Population / Approved / Eligible: "
                f"{definition.population_size} / {definition.approval_count} / "
                f"{definition.eligible_approval_count}",
                "  TP / FP / Incomplete: "
                f"{definition.true_positives} / {definition.false_positives} / "
                f"{definition.incomplete_approval_count}",
                (
                    "  Precision / Recall: "
                    + _ratio_text(
                        definition.precision,
                        definition.precision_status.value,
                    )
                    + f" / {_ratio_text(definition.recall)}"
                ),
                f"  Outcome Rule: {definition.outcome_eligibility_rule}",
                f"  Success Rule: {definition.success_threshold}",
                f"  Missing Outcomes: {definition.incomplete_outcome_treatment}",
                f"  Duplicates: {definition.duplicate_treatment}",
                f"  Replay Version: {definition.replay_version}",
            )
        )
    lines.extend(("", "Canonical Metric Contracts"))
    lines.extend(_contract_lines(report.raw_approval_contract))
    lines.extend(("",))
    lines.extend(_contract_lines(report.strict_approval_contract))
    attribution = report.strict_attribution
    lines.extend(
        (
            "",
            "Strict Approval Zero-Count Attribution",
            f"Classification: {attribution.conclusion.value}",
            "Implementation Matches Predicate: "
            f"{'Yes' if attribution.implementation_matches_predicate else 'No'}",
            f"Strict Approvals: {attribution.strict_approvals}/"
            f"{attribution.total_candidates}",
            f"Near Approvals: {attribution.near_approval_count}",
            f"Failing One Criterion: {attribution.failing_one_criterion}",
            f"Failing Two Criteria: {attribution.failing_two_criteria}",
            "Failing Three Or More Criteria: "
            f"{attribution.failing_three_or_more_criteria}",
            "Profitable Rejected Candidates: "
            f"{attribution.profitable_rejected_candidates}",
            "Completed Rejected Candidates: "
            f"{attribution.completed_rejected_candidates}",
            f"Explanation: {attribution.explanation}",
            "",
            "Sequential Gate Survival",
        )
    )
    lines.extend(
        f"- {gate.gate_id}: reached={gate.reached}; "
        f"rejected_at_gate={gate.rejected_at_gate}; survived={gate.survived}; "
        f"cumulative={_ratio_text(gate.cumulative_survival)}"
        for gate in attribution.gate_survival
    )
    lines.extend(("", "Mutually Exclusive Primary Failures"))
    lines.extend(
        f"- {failure.gate_id}: {failure.count}"
        for failure in attribution.mutually_exclusive_primary_failures
    )
    lines.extend(("", "Overlapping Strict Predicate Failures"))
    lines.extend(
        f"- {failure.gate_id}: {failure.count}"
        for failure in attribution.overlapping_failures
    )
    lines.extend(("", "Extended Diagnostic Failures"))
    lines.extend(
        f"- {failure.gate_id}: {failure.count}"
        for failure in attribution.extended_diagnostic_failures
    )
    return _finish(lines)


def render_approval_population_reconciliation(
    report: MetricTruthAuditReport,
) -> str:
    item = report.reconciliation
    lines = [
        "Approval Population Reconciliation",
        "PRODUCTION_INFLUENCE=false",
        "",
        "Earlier Metric",
        f"Precision: {_ratio_text(item.earlier_precision)}",
        f"Approvals: {item.earlier_approval_count}",
        f"Successful Approvals: {item.earlier_successful_approvals}",
        f"Incomplete Approvals: {item.earlier_incomplete_approvals}",
        f"Population: {item.earlier_population}",
        f"Definition: {item.earlier_definition}",
        f"Origin: {item.earlier_origin_status}",
        "",
        "Current Metric",
        f"Precision: {_ratio_text(item.current_precision)}",
        f"Approvals: {item.current_approval_count}",
        f"Successful Approvals: {item.current_successful_approvals}",
        f"Incomplete Approvals: {item.current_incomplete_approvals}",
        f"Population: {item.current_population}",
        f"Definition: {item.current_definition}",
        "",
        "Candidate-Level Reconciliation",
        f"In Both ({len(item.candidates_in_both)}): {_joined(item.candidates_in_both)}",
        "Earlier Only "
        f"({len(item.earlier_only_candidates)}): "
        f"{_joined(item.earlier_only_candidates)}",
        "Current Only "
        f"({len(item.current_only_candidates)}): "
        f"{_joined(item.current_only_candidates)}",
        "Outcome Classification Differences "
        f"({len(item.outcome_classification_differences)}): "
        f"{_joined(item.outcome_classification_differences)}",
        f"Duplicate Candidate IDs: {_joined(item.duplicate_candidate_ids)}",
        f"Overwritten Records: {item.overwritten_record_count}",
        f"Changed Horizons: {item.changed_horizon_count}",
        f"Changed Success Definitions: {item.changed_success_definition_count}",
        "",
        "Exact Delta Attribution",
    ]
    lines.extend(f"- {line}" for line in item.exact_attribution)
    lines.extend(
        (
            f"Precision Delta: {_signed_percentage(item.precision_delta)}",
            f"Unexplained Remainder: {item.unexplained_remainder}",
        )
    )
    return _finish(lines)


def render_regime_metric_truth(report: MetricTruthAuditReport) -> str:
    item = report.regime_truth
    lines = [
        "Market Regime Metric Truth Audit",
        "PRODUCTION_INFLUENCE=false",
        f"Conclusion: {item.conclusion.value}",
        f"Valid For Decision: {'Yes' if item.metric_valid_for_decision else 'No'}",
        f"True Label Source: {item.true_label_source}",
        f"Predicted Label Source: {item.predicted_label_source}",
        f"Class Order: {', '.join(item.class_labels)}",
        f"Observations / Excluded: {item.observations} / {item.excluded_observations}",
        f"Coverage: {_ratio_text(item.coverage)}",
        f"Missing Benchmark Inputs: {item.missing_benchmark_inputs}",
        f"Unknown Predictions: {item.unknown_predicted_labels}",
        f"Exact Date Alignment: {'Yes' if item.exact_date_alignment else 'No'}",
        f"Look-Ahead Detected: {'Yes' if item.look_ahead_detected else 'No'}",
        "Fraction/Percentage Semantics: "
        f"{'Valid' if item.fraction_percentage_semantics_valid else 'Invalid'}",
        "",
        "Metrics",
        "Source Balanced Accuracy: "
        f"{_ratio_text(item.source_reported_balanced_accuracy)}",
        "Recomputed Balanced Accuracy: "
        f"{_ratio_text(item.independently_recomputed_balanced_accuracy)}",
        f"Rendered Percentage: {_decimal_text(item.rendered_percentage, '%')}",
        f"Ordinary Accuracy: {_ratio_text(item.ordinary_accuracy)}",
        f"Macro F1: {_ratio_text(item.macro_f1)}",
        f"Majority-Class Baseline: {_ratio_text(item.majority_class_baseline)}",
        "Nominal Uniform Random Baseline: "
        f"{_ratio_text(item.nominal_uniform_random_baseline)}",
        "",
        "Confusion Matrix (actual rows, predicted columns)",
        "Actual\\Predicted | " + " | ".join(item.class_labels),
    ]
    matrix = {
        (cell.actual_label, cell.predicted_label): cell.count
        for cell in item.confusion_matrix
    }
    for actual in item.class_labels:
        lines.append(
            f"{actual} | "
            + " | ".join(
                str(matrix[(actual, predicted)]) for predicted in item.class_labels
            )
        )
    lines.extend(("", "Per-Class Statistics"))
    for statistic in item.class_statistics:
        lines.append(
            f"- {statistic.label}: support={statistic.support}; "
            f"predicted={statistic.predicted_count}; tp={statistic.true_positive}; "
            f"recall={_ratio_text(statistic.recall)}; "
            f"precision={_ratio_text(statistic.precision)}; "
            f"f1={_ratio_text(statistic.f1)}"
        )
    lines.extend(
        (
            "",
            "Label Normalization",
            *(f"- {source} -> {target}" for source, target in item.label_normalization),
            "",
            "Exact Failure Mode",
            item.exact_failure_mode,
            "",
            "IRD Adapter Validation",
        )
    )
    for validation in report.adapter_validations:
        lines.append(
            f"- {validation.diagnostic_id}: "
            f"{'PASS' if validation.safe_for_prioritization else 'FAIL'}; "
            f"metrics={validation.metric_count}; "
            f"issues={_joined(validation.issues)}"
        )
    return _finish(lines)


def render_metric_truth_summary(report: MetricTruthAuditReport) -> str:
    raw = report.raw_approval_contract
    strict = report.strict_approval_contract
    reconciliation = report.reconciliation
    attribution = report.strict_attribution
    regime = report.regime_truth
    lines = [
        "Approval Precision and Regime Metric Truth Summary",
        "PRODUCTION_INFLUENCE=false",
        "",
        "Authoritative Raw Approval Precision: "
        f"{_ratio_text(raw.precision, raw.precision_status.value)} "
        f"({raw.numerator}/{raw.denominator})",
        "Confidence Interval: "
        f"{_ratio_text(raw.confidence_interval_low)} to "
        f"{_ratio_text(raw.confidence_interval_high)} (95% Wilson)",
        "Strict Institutional Approval Precision: "
        f"{_ratio_text(strict.precision, strict.precision_status.value)}",
        f"Strict Approvals: {attribution.strict_approvals}/"
        f"{attribution.total_candidates}",
        f"Reason Strict Approvals Are Zero: {attribution.explanation}",
        f"Zero-Count Classification: {attribution.conclusion.value}",
        "",
        "Earlier 31.71% Metric: "
        f"{reconciliation.earlier_successful_approvals}/"
        f"{reconciliation.earlier_approval_count}; "
        f"{reconciliation.earlier_population}; "
        f"{reconciliation.earlier_definition}.",
        "Current 34.29% Metric: "
        f"{reconciliation.current_successful_approvals}/"
        f"{reconciliation.current_approval_count}; "
        f"{reconciliation.current_population}; "
        f"{reconciliation.current_definition}.",
        "Exact Reason For Difference: "
        f"{len(reconciliation.current_only_candidates)} newly included completed "
        f"approvals added {reconciliation.added_successes} wins and "
        f"{reconciliation.added_failures} non-wins; shared outcome changes=0, "
        "definition changes=0, duplicate/overwrite changes=0.",
        f"Unexplained Remainder: {reconciliation.unexplained_remainder}",
        "",
        "Market Regime Balanced Accuracy: "
        f"{_ratio_text(regime.source_reported_balanced_accuracy)} native arithmetic; "
        "INVALID for decision use.",
        f"Metric Validity Conclusion: {regime.conclusion.value}",
        f"Failure Mode: {regime.exact_failure_mode}",
        "",
        "Strict Gate Survival",
    ]
    lines.extend(
        f"- {gate.gate_id}: reached={gate.reached}; "
        f"rejected={gate.rejected_at_gate}; survived={gate.survived}; "
        f"cumulative={_ratio_text(gate.cumulative_survival)}"
        for gate in attribution.gate_survival
    )
    lines.extend(
        (
            "",
            "IRD Roadmap Before",
            *(f"- {item}" for item in report.roadmap_before),
            "",
            "IRD Roadmap After",
            *(f"- {item}" for item in report.roadmap_after),
            f"Roadmap Impact: {report.roadmap_impact}",
            f"Recommended Next Sprint: {report.recommended_next_sprint}",
        )
    )
    return _finish(lines)


def _contract_lines(contract: ApprovalPrecisionContract) -> tuple[str, ...]:
    return (
        f"{contract.metric_name}",
        f"- Approval Concept: {contract.approval_concept}",
        f"- Eligible Population: {contract.eligible_population}",
        f"- Outcome Horizon: {contract.outcome_horizon}",
        f"- Success Threshold: {contract.success_threshold}",
        f"- Required Outcome: {contract.required_completed_outcome}",
        f"- Transaction Costs: {contract.transaction_cost_treatment}",
        f"- Missing Observations: {contract.missing_observation_treatment}",
        f"- Duplicates: {contract.duplicate_treatment}",
        f"- Version: {contract.replay_version}",
        "- Precision: "
        f"{_ratio_text(contract.precision, contract.precision_status.value)} "
        f"({contract.numerator}/{contract.denominator})",
        "- 95% Wilson Interval: "
        f"{_ratio_text(contract.confidence_interval_low)} to "
        f"{_ratio_text(contract.confidence_interval_high)}",
    )


def _ratio_text(value: Decimal | None, missing: str = "NOT_ESTIMABLE") -> str:
    return missing if value is None else f"{value * Decimal('100'):.2f}%"


def _signed_percentage(value: Decimal) -> str:
    return f"{value * Decimal('100'):+.2f} percentage points"


def _decimal_text(value: Decimal | None, suffix: str = "") -> str:
    return "NOT_ESTIMABLE" if value is None else f"{value:.2f}{suffix}"


def _joined(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "None"


def _finish(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


__all__ = [
    "render_bottlenecks",
    "render_approval_population_reconciliation",
    "render_approval_precision_truth",
    "render_briefing",
    "render_metric",
    "render_metric_truth_summary",
    "render_regime_metric_truth",
    "render_registry",
    "render_roadmap",
    "render_roi",
]
