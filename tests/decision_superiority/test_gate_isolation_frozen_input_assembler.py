from __future__ import annotations

from alpha.decision_superiority.gate_isolation_execution_outcome_producers import (
    ExecutionStateCaptureInput,
    OutcomePolicyCaptureInput,
)
from alpha.decision_superiority.gate_isolation_frozen_input_assembler import (
    FrozenInputAssembler,
    FrozenInputAssemblyRequest,
)
from alpha.decision_superiority.gate_isolation_frozen_input_producers import (
    CandidateFeatureCaptureInput,
    PortfolioStateCaptureInput,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputReadiness,
    FrozenInputSection,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey
from alpha.decision_superiority.gate_isolation_policy_producers import (
    ApprovalPolicyCaptureInput,
    EntryPolicyCaptureInput,
)
from alpha.decision_superiority.gate_isolation_source_lineage_producer import (
    SourceLineageCaptureInput,
)


def _request() -> FrozenInputAssemblyRequest:
    candidate = FrozenCandidateKey(
        "RAW",
        "2026-07-26",
        "AAA",
        "fp-a",
    )
    return FrozenInputAssemblyRequest(
        candidate=candidate,
        candidate_features=CandidateFeatureCaptureInput(
            candidate_payload={"score": "7.5", "symbol": "AAA"},
            market_payload={"regime": "BULL"},
            feature_version="feature-v1",
            source_hashes={"analysis": "abc"},
            observed_on="2026-07-26",
        ),
        approval_policy=ApprovalPolicyCaptureInput(
            policy_payload={"minimum_score": "70"},
            policy_version="approval-v1",
            threshold_provenance={"minimum_score": "governed"},
            dependency_versions={"recommendation": "v1"},
            observed_on="2026-07-26",
        ),
        portfolio_state=PortfolioStateCaptureInput(
            recommendation_context={"cash": "1000"},
            allocation_context={"heat": "0.25"},
            state_version="portfolio-v1",
            observed_on="2026-07-26",
        ),
        entry_policy=EntryPolicyCaptureInput(
            policy_payload={"trigger_style": "BREAKOUT"},
            policy_version="entry-v1",
            trigger_payload={"status": "PENDING"},
            trigger_source_hashes={"price_history": "def"},
            observed_on="2026-07-26",
        ),
        execution_state=ExecutionStateCaptureInput(
            cash_state={"available_cash": "1000"},
            sizing_state={"max_position_weight": "0.05"},
            liquidity_constraints={"minimum_adv": "1000000"},
            participation_constraints={"maximum_participation": "0.10"},
            queue_state={"pending_orders": 0},
            risk_budget_state={"portfolio_heat": "0.25"},
            state_version="execution-v1",
            observed_on="2026-07-26",
        ),
        outcome_policy=OutcomePolicyCaptureInput(
            exit_policy={"mode": "RULE_BASED"},
            stop_policy={"atr_multiple": "2"},
            target_policy={"reward_multiple": "3"},
            trailing_policy={"enabled": True},
            time_exit_policy={"maximum_sessions": 20},
            ambiguity_policy={"same_bar": "STOP_FIRST"},
            policy_version="outcome-v1",
            dependency_versions={"price_semantics": "v1"},
            observed_on="2026-07-26",
        ),
        source_lineage=SourceLineageCaptureInput(
            artifact_hashes={"analysis": "abc"},
            provider_versions={"nse": "v1"},
            source_paths={"analysis": "artifacts/analysis.csv"},
            dataset_versions={"daily_history": "2026-07-26"},
            observed_on="2026-07-26",
        ),
    )


def test_assembler_preserves_all_seven_sections() -> None:
    result = FrozenInputAssembler().assemble(_request())

    assert result.present_sections == tuple(sorted(FrozenInputSection))
    assert result.missing_sections == ()
    assert len(result.present_sections) == 7


def test_complete_snapshot_is_persistable() -> None:
    result = FrozenInputAssembler().assemble(_request())

    assert result.readiness is FrozenInputReadiness.READY
    assert result.replay_ready is True
    assert result.persistence_permitted is True
    assert result.production_influence is False


def test_assembly_is_deterministic() -> None:
    first = FrozenInputAssembler().assemble(_request())
    second = FrozenInputAssembler().assemble(_request())

    assert first == second
    assert first.snapshot.snapshot_sha256 == second.snapshot.snapshot_sha256


def test_observation_date_mismatch_fails_closed() -> None:
    request = _request()

    try:
        FrozenInputAssemblyRequest(
            candidate=request.candidate,
            candidate_features=request.candidate_features,
            approval_policy=request.approval_policy,
            portfolio_state=request.portfolio_state,
            entry_policy=request.entry_policy,
            execution_state=request.execution_state,
            outcome_policy=request.outcome_policy,
            source_lineage=SourceLineageCaptureInput(
                artifact_hashes={"analysis": "abc"},
                provider_versions={"nse": "v1"},
                source_paths={"analysis": "artifacts/analysis.csv"},
                dataset_versions={"daily_history": "2026-07-26"},
                observed_on="2026-07-25",
            ),
        )
    except ValueError as exc:
        assert "observation date mismatch" in str(exc)
    else:
        raise AssertionError("expected observation date mismatch")
