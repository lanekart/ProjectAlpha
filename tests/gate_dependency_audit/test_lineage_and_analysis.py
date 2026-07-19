from __future__ import annotations

from decimal import Decimal

from alpha.gate_dependency_audit.bottleneck import (
    first_failure_statistics,
    gate_report_cards,
    sequential_survival,
)
from alpha.gate_dependency_audit.dependency_graph import dependency_matrix
from alpha.gate_dependency_audit.gate_order import evaluate_gate_order
from alpha.gate_dependency_audit.interaction_matrix import interaction_matrix
from alpha.gate_dependency_audit.marginal_value import marginal_gate_values
from alpha.gate_dependency_audit.models import CandidateGateLineage, GateStatus


def test_lineage_reconstructs_observed_and_sequential_truth(
    gate_lineages: tuple[CandidateGateLineage, ...],
) -> None:
    item = gate_lineages[0]
    assert len(item.lineage) == 20
    assert item.first_failed_gate == "FINAL_EVIDENCE_SCORE"
    final = next(
        step for step in item.lineage if step.gate_id == "FINAL_EVIDENCE_SCORE"
    )
    sample = next(step for step in item.lineage if step.gate_id == "HISTORICAL_SAMPLE")
    assert final.observed_status is GateStatus.FAIL
    assert final.sequential_status is GateStatus.FAIL
    assert final.first_failure is True
    assert sample.observed_status is GateStatus.FAIL
    assert sample.sequential_status is GateStatus.NOT_REACHED


def test_first_failure_and_sequential_survival_are_exact(
    gate_lineages: tuple[CandidateGateLineage, ...],
) -> None:
    first = first_failure_statistics(gate_lineages)
    criteria = {row.gate_id: row for row in first if row.scope == "CRITERION"}
    assert criteria["FINAL_EVIDENCE_SCORE"].candidates == 2
    assert criteria["HISTORICAL_SAMPLE"].candidates == 1
    assert criteria["STOP_DISTANCE"].candidates == 1
    survival = {row.gate_id: row for row in sequential_survival(gate_lineages)}
    assert survival["FINAL_EVIDENCE_SCORE"].entered_stage == 4
    assert survival["FINAL_EVIDENCE_SCORE"].rejected == 2
    assert survival["HISTORICAL_SAMPLE"].entered_stage == 2
    assert survival["HISTORICAL_SAMPLE"].rejected == 1
    assert survival["STOP_DISTANCE"].entered_stage == 1
    assert survival["STOP_DISTANCE"].rejected == 1


def test_dependency_and_interaction_matrices_quantify_overlap(
    gate_lineages: tuple[CandidateGateLineage, ...],
) -> None:
    dependencies = dependency_matrix(gate_lineages)
    row = next(
        item
        for item in dependencies
        if item.prior_gate == "FINAL_EVIDENCE_SCORE"
        and item.evaluated_gate == "HISTORICAL_SAMPLE"
    )
    assert row.prior_passed == 2
    assert row.incremental_failures_after_prior_pass == 1
    assert row.conditional_reject_percent == Decimal("50.00")
    interactions = interaction_matrix(gate_lineages)
    overlap = next(
        item
        for item in interactions
        if item.gate_a == "FINAL_EVIDENCE_SCORE" and item.gate_b == "HISTORICAL_SAMPLE"
    )
    assert overlap.joint_failures == 1
    assert overlap.only_a_failures == 1
    assert overlap.only_b_failures == 1
    assert overlap.jaccard_percent == Decimal("33.33")


def test_gate_permutations_do_not_change_conjunctive_decisions(
    gate_lineages: tuple[CandidateGateLineage, ...],
) -> None:
    result = evaluate_gate_order(gate_lineages)
    assert result.active_gate_count == 3
    assert result.permutations_tested == 6
    assert result.accepted_current_order == result.accepted_best_order == 0
    assert result.false_rejections_current_order == 1
    assert result.false_rejections_best_order == 1
    assert result.decision_outcomes_changed is False


def test_marginal_value_and_gate_report_cards_use_unique_survivors(
    gate_lineages: tuple[CandidateGateLineage, ...],
) -> None:
    marginal = marginal_gate_values(
        gate_lineages,
        initial_capital=Decimal("1000000"),
    )
    by_gate = {item.gate_id: item for item in marginal}
    assert by_gate["HISTORICAL_SAMPLE"].additional_survivors_if_removed == 1
    assert by_gate["HISTORICAL_SAMPLE"].false_rejections_released == 1
    assert by_gate["FINAL_EVIDENCE_SCORE"].additional_survivors_if_removed == 1
    cards = gate_report_cards(
        gate_lineages,
        marginal_values=marginal,
        initial_capital=Decimal("1000000"),
    )
    sample = next(item for item in cards if item.gate_id == "HISTORICAL_SAMPLE")
    assert sample.failures == 2
    assert sample.correct_rejections == 1
    assert sample.false_rejections == 1
    assert sample.incremental_survivors == 1
    assert sample.grade.value == "Research Only"
