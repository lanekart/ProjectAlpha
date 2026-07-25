from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import (
    DemoIntelligenceInputBuilder,
    IntelligenceInputSet,
)
from alpha.decision_superiority.gate_isolation_application_capture import (
    CapturingIntelligenceInputProvider,
    DSI002AAcceptanceResult,
    export_dsi002a_acceptance,
)
from alpha.decision_superiority.gate_isolation_frozen_input_capture import (
    FrozenInputCaptureResult,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey


@dataclass(slots=True)
class _RecordingObserver:
    result: FrozenInputCaptureResult
    calls: list[tuple[IntelligenceInputSet, date]] = field(default_factory=list)

    def capture(
        self,
        *,
        inputs: IntelligenceInputSet,
        observed_on: date,
    ) -> FrozenInputCaptureResult:
        self.calls.append((inputs, observed_on))
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


def _capture_result(tmp_path: Path) -> FrozenInputCaptureResult:
    return FrozenInputCaptureResult(
        candidate=FrozenCandidateKey(
            "RAW",
            "2026-07-26",
            "AAA",
            "fp-a",
        ),
        snapshot_sha256="a" * 64,
        snapshot_path=tmp_path / "snapshot.json",
        index_path=tmp_path / "index.csv",
        replay_ready=True,
    )


def test_capture_hook_is_disabled_by_default(tmp_path: Path) -> None:
    observer = _RecordingObserver(_capture_result(tmp_path))
    provider = CapturingIntelligenceInputProvider(
        delegate=DemoIntelligenceInputBuilder(),
        observer=observer,
    )

    provider.build(observed_on=date(2026, 7, 26))

    assert observer.calls == []


def test_enabled_capture_preserves_application_output_parity(
    tmp_path: Path,
) -> None:
    observed_on = date(2026, 7, 26)
    baseline = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=observed_on)
    observer = _RecordingObserver(_capture_result(tmp_path))
    captured = IntelligenceApplicationService(
        input_provider=CapturingIntelligenceInputProvider(
            delegate=DemoIntelligenceInputBuilder(),
            observer=observer,
            enabled=True,
        )
    ).run(observed_on=observed_on)

    assert captured.as_dict() == baseline.as_dict()
    assert captured.raw_candidates == baseline.raw_candidates
    assert len(observer.calls) == 1


def test_capture_failure_stops_before_decision_result() -> None:
    provider = CapturingIntelligenceInputProvider(
        delegate=DemoIntelligenceInputBuilder(),
        observer=_FailingObserver(),
        enabled=True,
    )

    with pytest.raises(RuntimeError, match="capture failed"):
        IntelligenceApplicationService(input_provider=provider).run(
            observed_on=date(2026, 7, 26)
        )


def test_enabled_capture_requires_observer() -> None:
    with pytest.raises(ValueError, match="requires an observer"):
        CapturingIntelligenceInputProvider(
            delegate=DemoIntelligenceInputBuilder(),
            enabled=True,
        )


def test_acceptance_certificate_is_deterministic(tmp_path: Path) -> None:
    result = DSI002AAcceptanceResult(
        capture=_capture_result(tmp_path),
        parity_verified=True,
        duplicate_protection_verified=True,
        missing_section_block_verified=True,
        post_observation_block_verified=True,
        capture_failure_isolation_verified=True,
    )

    first = export_dsi002a_acceptance(result, tmp_path / "first")
    second = export_dsi002a_acceptance(result, tmp_path / "second")

    assert result.accepted is True
    assert tuple(path.read_bytes() for path in first) == tuple(
        path.read_bytes() for path in second
    )
    certificate = json.loads(first[0].read_text(encoding="utf-8"))
    assert certificate["accepted"] is True
    assert certificate["production_influence"] is False
