from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType

import pytest

from alpha.gate_dependency_audit.bottleneck import (
    bottleneck_summary,
    first_failure_statistics,
    gate_report_cards,
    path_statistics,
    sequential_survival,
)
from alpha.gate_dependency_audit.dependency_graph import dependency_matrix
from alpha.gate_dependency_audit.gate_order import evaluate_gate_order
from alpha.gate_dependency_audit.interaction_matrix import interaction_matrix
from alpha.gate_dependency_audit.lineage import reconstruct_candidate_lineage
from alpha.gate_dependency_audit.marginal_value import marginal_gate_values
from alpha.gate_dependency_audit.models import (
    CandidateGateLineage,
    GateDependencyAuditReport,
    GDSBAManifest,
)


def lineage(
    candidate_id: str,
    classification: str,
    failures: tuple[tuple[str, str], ...],
    *,
    return_percent: str,
) -> CandidateGateLineage:
    row = {
        "candidate_id": candidate_id,
        "observed_on": "2024-01-02",
        "symbol": candidate_id,
        "final_signal": "BUY",
        "candidate_score": "82",
        "classification": classification,
        "planned_net_return_percent": return_percent,
        "planned_realized_r": "1.25",
    }
    evidence = tuple(
        {"gate_code": code, "explanation": explanation}
        for code, explanation in failures
    )
    return reconstruct_candidate_lineage(row, evidence)


@pytest.fixture
def gate_lineages() -> tuple[CandidateGateLineage, ...]:
    final = (
        "WEAK_SETUP",
        "Final evidence score is below the institutional minimum of 85.",
    )
    sample = (
        "INSUFFICIENT_EVIDENCE",
        "Fresh deployment requires at least 60 completed historical samples.",
    )
    stop = (
        "EXCESS_DOWNSIDE_RISK",
        "Stop distance exceeds the frozen policy maximum.",
    )
    return (
        lineage(
            "CORRECT",
            "CORRECT_REJECTION",
            (final, sample, stop),
            return_percent="-8",
        ),
        lineage(
            "FALSE",
            "FALSE_REJECTION",
            (sample,),
            return_percent="12",
        ),
        lineage(
            "MARGINAL",
            "MARGINAL",
            (final,),
            return_percent="1",
        ),
        lineage(
            "UNCERTAIN",
            "DATA_UNCERTAIN",
            (stop,),
            return_percent="0",
        ),
    )


@pytest.fixture
def dependency_report(
    gate_lineages: tuple[CandidateGateLineage, ...],
) -> GateDependencyAuditReport:
    first = first_failure_statistics(gate_lineages)
    marginal = marginal_gate_values(
        gate_lineages,
        initial_capital=Decimal("1000000"),
    )
    interactions = interaction_matrix(gate_lineages)
    cards = gate_report_cards(
        gate_lineages,
        marginal_values=marginal,
        initial_capital=Decimal("1000000"),
    )
    return GateDependencyAuditReport(
        manifest=GDSBAManifest(
            audit_version="GDSBA_v1.0",
            baseline_id="ALPHA_BASELINE_v1.0",
            igta_manifest_hash="igta-hash",
            approval_policy_version="approval-v1",
            approval_policy_hash="approval-hash",
            gate_sequence_hash="sequence-hash",
            source_hashes=MappingProxyType({"source.csv": "source-hash"}),
        ),
        technical_candidates=25,
        buy_candidates=4,
        lineages=gate_lineages,
        first_failures=first,
        survival=sequential_survival(gate_lineages),
        dependencies=dependency_matrix(gate_lineages),
        interactions=interactions,
        marginal_values=marginal,
        false_rejection_paths=path_statistics(
            gate_lineages,
            outcome_classification="FALSE_REJECTION",
        ),
        correct_rejection_paths=path_statistics(
            gate_lineages,
            outcome_classification="CORRECT_REJECTION",
        ),
        report_cards=cards,
        gate_order=evaluate_gate_order(gate_lineages),
        bottleneck=bottleneck_summary(
            first_failures=first,
            report_cards=cards,
            interactions=interactions,
            marginal_values=marginal,
        ),
    )


__all__ = ["lineage"]
