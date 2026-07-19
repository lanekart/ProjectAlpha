from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from alpha.adaptive_weights.models import (
    AblationContribution,
    CandidateWeightPolicy,
    ComponentWeightDecision,
    ConditionalWeightPolicy,
    ConfidenceAssessment,
    ContributionEstimate,
    OverlapFinding,
    PolicyComparison,
    PromotionAssessment,
    StabilityAssessment,
    WeightProposal,
    WeightSet,
    to_primitive,
)


def render_weight_audit(
    canonical: WeightSet,
    deployed: WeightSet,
    *,
    evidence_count: int,
    partition_counts: dict[str, int],
) -> str:
    lines = [
        "Adaptive Indicator Weight Research Audit",
        f"Completed Eligible Outcomes: {evidence_count}",
        "Partitions: "
        + (
            ", ".join(
                f"{key}={value}" for key, value in sorted(partition_counts.items())
            )
            or "none"
        ),
        "",
        "Canonical Weights (immutable):",
    ]
    for item in canonical.weights:
        lines.append(f"- {_label(item.component.value)}: {_number(item.weight)}")
    lines.extend(
        (
            "",
            f"Deployed Policy: {deployed.policy_id}",
            "Canonical/Deployed Separation: ACTIVE",
            "PRODUCTION_INFLUENCE=false",
            "AUTOMATIC_WEIGHT_MUTATION=false",
        )
    )
    return "\n".join(lines) + "\n"


def render_contributions(
    contributions: tuple[ContributionEstimate, ...],
    ablations: tuple[AblationContribution, ...],
    stabilities: tuple[StabilityAssessment, ...],
    confidences: tuple[ConfidenceAssessment, ...],
    decisions: tuple[ComponentWeightDecision, ...] = (),
) -> str:
    ablation_by = {item.component: item for item in ablations}
    stability_by = {item.component: item for item in stabilities}
    confidence_by = {item.component: item for item in confidences}
    decision_by = {item.component: item for item in decisions}
    lines = [
        "Component Contribution Report",
        "Component | Delta Expectancy | Delta Profit Factor | Delta Drawdown | "
        "Unique Contribution | Stability | Confidence | Decision | Proposed Weight",
    ]
    for item in contributions:
        ablation = ablation_by[item.component]
        decision = decision_by.get(item.component)
        lines.append(
            " | ".join(
                (
                    _label(item.component.value),
                    _number(ablation.delta_expectancy),
                    _number(ablation.delta_profit_factor),
                    _number(ablation.delta_drawdown),
                    _number(item.marginal_contribution),
                    stability_by[item.component].classification.value,
                    confidence_by[item.component].confidence.value,
                    decision.decision.value if decision else "NOT_PROPOSED",
                    _number(decision.proposed_weight) if decision else "unavailable",
                )
            )
        )
    lines.append("PRODUCTION_INFLUENCE=false")
    return "\n".join(lines) + "\n"


def render_overlap(findings: tuple[OverlapFinding, ...]) -> str:
    lines = [
        "Indicator Overlap Report",
        "Component A | Component B | Correlation | Candidate Overlap | "
        "Source Overlap | Redundancy Class | Recommended Action",
    ]
    for item in findings:
        lines.append(
            " | ".join(
                (
                    _label(item.component_a.value),
                    _label(item.component_b.value),
                    _number(item.score_correlation),
                    _number(item.candidate_overlap),
                    "YES" if item.shared_source_lineage else "NO",
                    item.redundancy_class.value,
                    item.recommended_action,
                )
            )
        )
    lines.append("PRODUCTION_INFLUENCE=false")
    return "\n".join(lines) + "\n"


def render_stability(assessments: tuple[StabilityAssessment, ...]) -> str:
    lines = [
        "Component Stability Report",
        "Component | Sample | Direction | Magnitude | Rank | Sector | Setup | "
        "Regime | Holdout | Forward | Class",
    ]
    for item in assessments:
        lines.append(
            " | ".join(
                (
                    _label(item.component.value),
                    str(item.sample_size),
                    _number(item.directional_stability),
                    _number(item.magnitude_stability),
                    _number(item.rank_stability),
                    _number(item.sector_stability),
                    _number(item.setup_stability),
                    _number(item.regime_stability),
                    _boolean(item.holdout_consistency),
                    _boolean(item.forward_consistency),
                    item.classification.value,
                )
            )
        )
    lines.append("PRODUCTION_INFLUENCE=false")
    return "\n".join(lines) + "\n"


def render_proposal(proposal: WeightProposal) -> str:
    lines = [
        "Adaptive Weight Proposal (Research Only)",
        f"Completed Outcomes: {proposal.evidence_count}",
        f"Validation: {proposal.validation_status}",
        f"Holdout: {proposal.holdout_status}",
        f"Forward: {proposal.forward_status}",
        "Component | Canonical | Proposed | Change | Decision | Reason | Blockers",
    ]
    for item in proposal.decisions:
        lines.append(
            " | ".join(
                (
                    _label(item.component.value),
                    _number(item.current_weight),
                    _number(item.proposed_weight),
                    _number(item.absolute_change),
                    item.decision.value,
                    item.primary_reason,
                    "; ".join(item.blocking_reasons) or "none",
                )
            )
        )
    lines.extend(
        (
            "",
            "Guardrails:",
            "- Maximum relative revision: "
            + _number(proposal.guardrails.maximum_relative_change),
            "- Maximum component weight: "
            + _number(proposal.guardrails.maximum_absolute_weight),
            "- Total proposed weight: "
            + _number(
                sum((item.weight for item in proposal.proposed.weights), start=0)
            ),
            "AUTOMATIC_WEIGHT_MUTATION=false",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return "\n".join(lines) + "\n"


def render_conditional(policy: ConditionalWeightPolicy) -> str:
    lines = [
        "Conditional Weight Research",
        f"Minimum Sample: {policy.minimum_sample_size}",
        "Setup | Regime | Horizon | Sample | Quality | Policy",
    ]
    if not policy.conditionals:
        lines.append("No conditional policy has sufficient completed evidence.")
    for item in policy.conditionals:
        lines.append(
            " | ".join(
                (
                    item.setup or "ANY",
                    item.regime or "ANY",
                    item.horizon or "ANY",
                    str(item.sample_size),
                    item.evidence_quality.value,
                    item.weights.policy_id,
                )
            )
        )
    lines.extend(
        (
            "Fallback: setup+regime -> setup -> regime -> "
            "universal adaptive -> canonical",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return "\n".join(lines) + "\n"


def render_policy(policy: CandidateWeightPolicy | None) -> str:
    if policy is None:
        return (
            "Adaptive Weight Candidate Policy\n"
            "Status: no frozen candidate policy\n"
            "PRODUCTION_INFLUENCE=false\n"
        )
    lines = [
        "Adaptive Weight Candidate Policy",
        f"Policy ID: {policy.policy_id}",
        f"Parent: {policy.parent_policy}",
        f"State: {policy.state.value}",
        f"Quality: {policy.quality_state.value}",
        f"Completed Outcomes: {policy.outcome_count}",
        f"Dataset Version: {policy.dataset_version}",
        f"Validation: {policy.validation_status}",
        f"Holdout: {policy.holdout_status}",
        f"Forward: {policy.forward_status}",
        f"Manifest Hash: {policy.manifest_hash}",
        "Direct Deployment: PROHIBITED",
        "PRODUCTION_INFLUENCE=false",
    ]
    return "\n".join(lines) + "\n"


def render_comparisons(comparisons: tuple[PolicyComparison, ...]) -> str:
    lines = [
        "Canonical vs Candidate Policy Comparison",
        "Partition | Policy | Expectancy | Profit Factor | Win Rate | "
        "Average Winner R | Average Loser R | Drawdown | Trades | Turnover | "
        "Sector Concentration | Setup Concentration",
    ]
    if not comparisons:
        lines.append("Comparable completed policy outcomes are unavailable.")
    for comparison in comparisons:
        for policy, metrics in (
            (comparison.baseline_policy, comparison.baseline),
            (comparison.candidate_policy, comparison.candidate),
        ):
            lines.append(
                " | ".join(
                    (
                        comparison.partition.value,
                        policy,
                        _number(metrics.expectancy),
                        _number(metrics.profit_factor),
                        _number(metrics.win_rate),
                        _number(metrics.average_winner_r),
                        _number(metrics.average_loser_r),
                        _number(metrics.max_drawdown),
                        str(metrics.trade_count),
                        _number(metrics.turnover),
                        _number(metrics.sector_concentration),
                        _number(metrics.setup_concentration),
                    )
                )
            )
    lines.append("PRODUCTION_INFLUENCE=false")
    return "\n".join(lines) + "\n"


def render_promotion(assessment: PromotionAssessment) -> str:
    return "\n".join(
        (
            "Adaptive Weight Promotion Assessment",
            f"Candidate: {assessment.candidate_policy}",
            f"Decision: {assessment.decision.value}",
            "Blockers: " + ("; ".join(assessment.blockers) or "none"),
            "Supporting Evidence: "
            + ("; ".join(assessment.supporting_evidence) or "none"),
            f"Next Step: {assessment.required_next_step}",
            "AUTOMATIC_DEPLOYMENT=false",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_primitive(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: tuple[object, ...]) -> None:
    primitives = [to_primitive(item) for item in rows]
    flat = [
        _flatten(item if isinstance(item, dict) else {"value": item})
        for item in primitives
    ]
    fieldnames = sorted({key for row in flat for key in row})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat)


def _flatten(value: dict[str, Any], prefix: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            result.update(_flatten(item, name))
        elif isinstance(item, list):
            result[name] = json.dumps(item, sort_keys=True)
        elif item is None:
            result[name] = ""
        else:
            result[name] = str(item)
    return result


def _number(value: object) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.0001")))
    return str(value)


def _boolean(value: bool | None) -> str:
    return "unavailable" if value is None else ("YES" if value else "NO")


def _label(value: str) -> str:
    return value.replace("_", " ").title()


__all__ = [
    "render_comparisons",
    "render_conditional",
    "render_contributions",
    "render_overlap",
    "render_policy",
    "render_promotion",
    "render_proposal",
    "render_stability",
    "render_weight_audit",
    "write_csv",
    "write_json",
]
