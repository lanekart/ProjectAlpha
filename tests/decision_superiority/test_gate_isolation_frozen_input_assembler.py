from __future__ import annotations

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
        source_lineage=SourceLineageCaptureInput(
            artifact_hashes={"analysis": "abc"},
            provider_versions={"nse": "v1"},
            source_paths={"analysis": "artifacts/analysis.csv"},
            dataset_versions={"historical_truth": "2026-07-26"},
            observed_on="2026-07-26",
        ),
    )


def test_assembler_preserves_five_available_sections() -> None:
    result = FrozenInputAssembler().assemble(_request())

    assert result.present_sections == (
        FrozenInputSection.APPROVAL_POLICY,
        FrozenInputSection.CANDIDATE_FEATURES,
        FrozenInputSection.ENTRY_POLICY,
        FrozenInputSection.PORTFOLIO_STATE,
        FrozenInputSection.SOURCE_LINEAGE,
    )
    assert result.missing_sections == (
        FrozenInputSection.EXECUTION_STATE,
        FrozenInputSection.OUTCOME_POLICY,
    )


def test_incomplete_snapshot_is_not_persistable() -> None:
    result = FrozenInputAssembler().assemble(_request())

    assert result.readiness is FrozenInputReadiness.INCOMPLETE
    assert result.replay_ready is False
    assert result.persistence_permitted is False
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
            source_lineage=SourceLineageCaptureInput(
                artifact_hashes={"analysis": "abc"},
                provider_versions={"nse": "v1"},
                source_paths={"analysis": "artifacts/analysis.csv"},
                dataset_versions={"historical_truth": "2026-07-26"},
                observed_on="2026-07-25",
            ),
        )
    except ValueError as exc:
        assert "observation date mismatch" in str(exc)
    else:
        raise AssertionError("expected observation date mismatch")
