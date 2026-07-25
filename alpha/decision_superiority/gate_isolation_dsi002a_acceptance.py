"""Executable deterministic acceptance run for DSI-002A forward capture."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import (
    DemoIntelligenceInputBuilder,
    IntelligenceInputSet,
)
from alpha.decision_superiority.gate_isolation_application_capture import (
    CapturingIntelligenceInputProvider,
    DSI002AAcceptanceResult,
    GovernedFrozenInputApplicationObserver,
    export_dsi002a_acceptance,
)
from alpha.decision_superiority.gate_isolation_configured_request_provider import (
    ConfiguredFrozenInputAssemblyRequestProvider,
    FrozenCapturePolicyBundle,
)
from alpha.decision_superiority.gate_isolation_frozen_input_assembler import (
    FrozenInputAssembler,
)
from alpha.decision_superiority.gate_isolation_frozen_input_capture import (
    FrozenInputCaptureResult,
    FrozenInputCaptureWriter,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenCandidateInputSnapshot,
    FrozenInputContractValidator,
    FrozenInputReadiness,
)


def default_acceptance_bundle() -> FrozenCapturePolicyBundle:
    """Return the governed deterministic acceptance configuration."""

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


class _RecordingObserver:
    def __init__(self, delegate: GovernedFrozenInputApplicationObserver) -> None:
        self._delegate = delegate
        self.result: FrozenInputCaptureResult | None = None

    def capture(
        self,
        *,
        inputs: IntelligenceInputSet,
        observed_on: date,
    ) -> FrozenInputCaptureResult:
        self.result = self._delegate.capture(
            inputs=inputs,
            observed_on=observed_on,
        )
        return self.result


class _FailingObserver:
    def capture(
        self,
        *,
        inputs: IntelligenceInputSet,
        observed_on: date,
    ) -> FrozenInputCaptureResult:
        del inputs, observed_on
        raise RuntimeError("capture failed")


def run_dsi002a_acceptance(output: Path) -> DSI002AAcceptanceResult:
    """Execute capture, parity, duplicate, and fail-closed checks."""

    observed_on = date(2026, 7, 26)
    provider = ConfiguredFrozenInputAssemblyRequestProvider(default_acceptance_bundle())
    baseline = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=observed_on)
    capture_root = output / "capture"
    recorder = _RecordingObserver(
        GovernedFrozenInputApplicationObserver(
            request_provider=provider,
            capture_root=capture_root,
        )
    )
    captured = IntelligenceApplicationService(
        input_provider=CapturingIntelligenceInputProvider(
            delegate=DemoIntelligenceInputBuilder(),
            observer=recorder,
            enabled=True,
        )
    ).run(observed_on=observed_on)
    parity_verified = captured.as_dict() == baseline.as_dict()
    capture_result = recorder.result
    if capture_result is None:
        raise RuntimeError("acceptance capture did not produce a result")

    inputs = DemoIntelligenceInputBuilder().build(observed_on=observed_on)
    request = provider.build(inputs=inputs, observed_on=observed_on)
    assembly = FrozenInputAssembler().assemble(request)
    writer = FrozenInputCaptureWriter(capture_root)
    duplicate_protection_verified = False
    try:
        writer.capture(assembly.snapshot)
    except (FileExistsError, ValueError):
        duplicate_protection_verified = True

    incomplete = FrozenCandidateInputSnapshot.build(
        candidate=assembly.snapshot.candidate,
        sections=assembly.snapshot.sections[:-1],
    )
    missing_validation = FrozenInputContractValidator().validate(incomplete)
    missing_section_block_verified = (
        missing_validation.readiness is FrozenInputReadiness.INCOMPLETE
    )

    first = assembly.snapshot.sections[0]
    post_observation_section = replace(
        first,
        contains_post_observation_data=True,
    )
    post_observation_snapshot = FrozenCandidateInputSnapshot.build(
        candidate=assembly.snapshot.candidate,
        sections=(post_observation_section, *assembly.snapshot.sections[1:]),
    )
    post_validation = FrozenInputContractValidator().validate(post_observation_snapshot)
    post_observation_block_verified = (
        post_validation.readiness is FrozenInputReadiness.POST_OBSERVATION_INPUT
    )

    capture_failure_isolation_verified = False
    failing_provider = CapturingIntelligenceInputProvider(
        delegate=DemoIntelligenceInputBuilder(),
        observer=_FailingObserver(),
        enabled=True,
    )
    try:
        IntelligenceApplicationService(input_provider=failing_provider).run(
            observed_on=observed_on
        )
    except RuntimeError:
        capture_failure_isolation_verified = True

    result = DSI002AAcceptanceResult(
        capture=capture_result,
        parity_verified=parity_verified,
        duplicate_protection_verified=duplicate_protection_verified,
        missing_section_block_verified=missing_section_block_verified,
        post_observation_block_verified=post_observation_block_verified,
        capture_failure_isolation_verified=(capture_failure_isolation_verified),
    )
    export_dsi002a_acceptance(result, output)
    return result


__all__ = [
    "default_acceptance_bundle",
    "run_dsi002a_acceptance",
]
