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
        portfolio_state=PortfolioStateCaptureInput(
            recommendation_context={"cash": "1000"},
            allocation_context={"heat": "0.25"},
            state_version="portfolio-v1",
            observed_on="2026-07-26",
        ),
    )


def test_assembler_preserves_only_available_sections() -> None:
    result = FrozenInputAssembler().assemble(_request())

    assert result.present_sections == (
        FrozenInputSection.CANDIDATE_FEATURES,
        FrozenInputSection.PORTFOLIO_STATE,
    )
    assert len(result.missing_sections) == 5
    assert FrozenInputSection.EXECUTION_STATE in result.missing_sections
    assert FrozenInputSection.OUTCOME_POLICY in result.missing_sections


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
            candidate_features=CandidateFeatureCaptureInput(
                candidate_payload={"symbol": "AAA"},
                market_payload={"regime": "BULL"},
                feature_version="feature-v1",
                source_hashes={"analysis": "abc"},
                observed_on="2026-07-25",
            ),
            portfolio_state=request.portfolio_state,
        )
    except ValueError as exc:
        assert "observation date mismatch" in str(exc)
    else:
        raise AssertionError("expected observation date mismatch")
