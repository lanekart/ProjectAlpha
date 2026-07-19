from __future__ import annotations

from alpha.forward_validation.approval_gate_optimizer import ApprovalGateOptimizer
from alpha.forward_validation.approval_policy_optimizer import ApprovalPolicyOptimizer
from alpha.forward_validation.counterfactual_engine import CounterfactualPolicyEngine
from alpha.forward_validation.models import (
    CounterfactualOperation,
    OptimizationRecommendation,
    PolicyStage,
    StopAuditClassification,
)


def test_gate_analysis_attributes_profitable_stop_rejections(policy_evidence) -> None:  # type: ignore[no-untyped-def]
    records, outcomes = policy_evidence
    metrics = ApprovalGateOptimizer().analyze(records=records, outcomes=outcomes)
    stop = next(item for item in metrics if item.gate_id == "stop_distance")

    assert stop.candidates_entering == 30
    assert stop.candidates_passing == 0
    assert stop.profitable_rejected_candidates == 30
    assert stop.precision_contribution_pct is None


def test_counterfactual_generation_covers_required_operations(policy_evidence) -> None:  # type: ignore[no-untyped-def]
    records, _ = policy_evidence
    candidates = CounterfactualPolicyEngine().generate(records)
    operations = {candidate.operation for candidate in candidates}

    assert operations == set(CounterfactualOperation)
    assert any(
        candidate.parameters.get("gate_id") == "stop_distance"
        and candidate.operation is CounterfactualOperation.RELAX
        for candidate in candidates
    )


def test_optimizer_validates_stop_relaxation_across_all_replay_splits(
    policy_evidence,
) -> None:  # type: ignore[no-untyped-def]
    records, outcomes = policy_evidence
    report = ApprovalPolicyOptimizer().optimize(records=records, outcomes=outcomes)

    assert report.stop_distance_audit.classification is (
        StopAuditClassification.OVER_RESTRICTIVE
    )
    assert report.recommendation is (
        OptimizationRecommendation.DEPLOY_POLICY_V2_TO_FORWARD_VALIDATION
    )
    selected = next(
        candidate
        for candidate in report.candidates
        if candidate.policy_version.number == 2
    )
    assert selected.stage is PolicyStage.HOLDOUT_PASSED
    assert len(selected.scorecards) == 3
    assert all(scorecard.passed_baseline for scorecard in selected.scorecards)


def test_atr_replacement_is_rejected_when_frozen_input_is_missing(
    policy_evidence,
) -> None:  # type: ignore[no-untyped-def]
    records, outcomes = policy_evidence
    report = ApprovalPolicyOptimizer().optimize(records=records, outcomes=outcomes)
    replacement = next(
        candidate
        for candidate in report.candidates
        if candidate.operation is CounterfactualOperation.REPLACE
    )

    assert replacement.stage is PolicyStage.REJECTED
    assert replacement.scorecards[0].reason == "Required frozen input is unavailable."
