from __future__ import annotations

from datetime import date
from pathlib import Path

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import DemoIntelligenceInputBuilder
from alpha.decision_superiority.gate_isolation_application_capture import (
    CapturingIntelligenceInputProvider,
    GovernedFrozenInputApplicationObserver,
)
from alpha.decision_superiority.gate_isolation_configured_request_provider import (
    ConfiguredFrozenInputAssemblyRequestProvider,
    FrozenCapturePolicyBundle,
)
from alpha.decision_superiority.gate_isolation_frozen_input_assembler import (
    FrozenInputAssembler,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputReadiness,
    FrozenInputSection,
)


def _bundle() -> FrozenCapturePolicyBundle:
    return FrozenCapturePolicyBundle(
        feature_version="feature-v1",
        approval_policy={"minimum_score": "70"},
        approval_policy_version="approval-v1",
        threshold_provenance={"minimum_score": "governed"},
        approval_dependency_versions={"recommendation": "v1"},
        portfolio_state_version="portfolio-v1",
        entry_policy={"trigger_style": "BREAKOUT"},
        entry_policy_version="entry-v1",
        trigger_payload={"status": "PENDING"},
        trigger_source_hashes={"price_history": "def"},
        execution_state={
            "cash": "100000",
            "participation_limit": "0.05",
            "queue": [],
            "risk_budget": "0.01",
            "sizing_limit": "0.10",
        },
        execution_state_version="execution-v1",
        execution_source_hashes={"broker_state": "ghi"},
        outcome_policy={
            "exit_rules": ["STOP", "TARGET", "TIME"],
            "formed_trade_identity": None,
        },
        outcome_policy_version="outcome-v1",
        outcome_dependency_versions={"trade_plan": "v1"},
        provider_versions={"analysis": "v1"},
        dataset_versions={"market": "2026-07-26"},
        source_paths={"analysis": "memory://analysis"},
        artifact_hashes={"analysis": "abc"},
    )


def test_configured_provider_builds_complete_request() -> None:
    observed_on = date(2026, 7, 26)
    inputs = DemoIntelligenceInputBuilder().build(observed_on=observed_on)
    provider = ConfiguredFrozenInputAssemblyRequestProvider(_bundle())

    request = provider.build(inputs=inputs, observed_on=observed_on)
    result = FrozenInputAssembler().assemble(request)

    assert result.readiness is FrozenInputReadiness.READY
    assert result.replay_ready is True
    assert result.persistence_permitted is True
    assert result.missing_sections == ()
    assert set(result.present_sections) == set(FrozenInputSection)


def test_application_capture_writes_snapshot_without_output_change(
    tmp_path: Path,
) -> None:
    observed_on = date(2026, 7, 26)
    baseline = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=observed_on)
    observer = GovernedFrozenInputApplicationObserver(
        request_provider=ConfiguredFrozenInputAssemblyRequestProvider(_bundle()),
        capture_root=tmp_path,
    )
    captured = IntelligenceApplicationService(
        input_provider=CapturingIntelligenceInputProvider(
            delegate=DemoIntelligenceInputBuilder(),
            observer=observer,
            enabled=True,
        )
    ).run(observed_on=observed_on)

    assert captured.as_dict() == baseline.as_dict()
    snapshots = tuple((tmp_path / "snapshots").glob("*.json"))
    assert len(snapshots) == 1
    assert (tmp_path / "dsi002_frozen_input_capture_index.csv").exists()


def test_request_provider_is_deterministic() -> None:
    observed_on = date(2026, 7, 26)
    inputs = DemoIntelligenceInputBuilder().build(observed_on=observed_on)
    provider = ConfiguredFrozenInputAssemblyRequestProvider(_bundle())

    first = provider.build(inputs=inputs, observed_on=observed_on)
    second = provider.build(inputs=inputs, observed_on=observed_on)

    assert first == second
    assert first.candidate.input_fingerprint == (second.candidate.input_fingerprint)
