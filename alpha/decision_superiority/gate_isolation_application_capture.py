"""Application boundary and acceptance artifacts for DSI-002A capture."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from alpha.application.intelligence_inputs import IntelligenceInputSet
from alpha.decision_superiority.gate_isolation_frozen_input_assembler import (
    FrozenInputAssembler,
    FrozenInputAssemblyRequest,
)
from alpha.decision_superiority.gate_isolation_frozen_input_capture import (
    FrozenInputCaptureResult,
    FrozenInputCaptureWriter,
)


class IntelligenceInputProvider(Protocol):
    """Build immutable engine-ready application inputs."""

    def build(self, *, observed_on: date) -> IntelligenceInputSet:
        """Return one deterministic application input set."""
        ...


class FrozenInputAssemblyRequestProvider(Protocol):
    """Build all governed capture inputs from the immutable application seam."""

    def build(
        self,
        *,
        inputs: IntelligenceInputSet,
        observed_on: date,
    ) -> FrozenInputAssemblyRequest:
        """Return a complete seven-section assembly request."""
        ...


class FrozenInputApplicationObserver(Protocol):
    """Observe one application input set without changing decision behaviour."""

    def capture(
        self,
        *,
        inputs: IntelligenceInputSet,
        observed_on: date,
    ) -> FrozenInputCaptureResult:
        """Persist one complete point-in-time frozen-input snapshot."""
        ...


class CapturingIntelligenceInputProvider:
    """Disabled-by-default capture hook at the immutable input boundary."""

    def __init__(
        self,
        *,
        delegate: IntelligenceInputProvider,
        observer: FrozenInputApplicationObserver | None = None,
        enabled: bool = False,
    ) -> None:
        if enabled and observer is None:
            raise ValueError("enabled frozen-input capture requires an observer")
        self._delegate = delegate
        self._observer = observer
        self._enabled = enabled

    def build(self, *, observed_on: date) -> IntelligenceInputSet:
        """Return unchanged inputs after optional strict diagnostic capture."""

        inputs = self._delegate.build(observed_on=observed_on)
        if self._enabled:
            observer = self._observer
            if observer is None:
                raise ValueError("enabled frozen-input capture requires an observer")
            observer.capture(inputs=inputs, observed_on=observed_on)
        return inputs


class GovernedFrozenInputApplicationObserver:
    """Assemble and append one complete snapshot at the application seam."""

    def __init__(
        self,
        *,
        request_provider: FrozenInputAssemblyRequestProvider,
        capture_root: Path,
    ) -> None:
        self._request_provider = request_provider
        self._assembler = FrozenInputAssembler()
        self._writer = FrozenInputCaptureWriter(capture_root)

    def capture(
        self,
        *,
        inputs: IntelligenceInputSet,
        observed_on: date,
    ) -> FrozenInputCaptureResult:
        """Build, validate, and persist a replay-ready snapshot."""

        request = self._request_provider.build(
            inputs=inputs,
            observed_on=observed_on,
        )
        result = self._assembler.assemble(request)
        if not result.replay_ready or not result.persistence_permitted:
            raise ValueError("application capture requires a replay-ready snapshot")
        return self._writer.capture(result.snapshot)


@dataclass(frozen=True, slots=True)
class DSI002AAcceptanceResult:
    """Governed acceptance boundary for complete forward capture."""

    capture: FrozenInputCaptureResult
    parity_verified: bool
    duplicate_protection_verified: bool
    missing_section_block_verified: bool
    post_observation_block_verified: bool
    capture_failure_isolation_verified: bool
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("DSI-002A acceptance must remain diagnostic-only")

    @property
    def accepted(self) -> bool:
        """Return whether every governed acceptance condition passed."""

        return all(
            (
                self.capture.replay_ready,
                self.parity_verified,
                self.duplicate_protection_verified,
                self.missing_section_block_verified,
                self.post_observation_block_verified,
                self.capture_failure_isolation_verified,
                not self.production_influence,
            )
        )


def export_dsi002a_acceptance(
    result: DSI002AAcceptanceResult,
    output: Path,
) -> tuple[Path, Path]:
    """Write deterministic JSON certificate and CSV acceptance summary."""

    output.mkdir(parents=True, exist_ok=True)
    certificate = output / "dsi002a_forward_capture_certificate.json"
    summary = output / "dsi002a_forward_capture_acceptance.csv"
    payload = {
        "accepted": result.accepted,
        "candidate": {
            "input_fingerprint": result.capture.candidate.input_fingerprint,
            "observed_on": result.capture.candidate.observed_on,
            "price_view": result.capture.candidate.price_view,
            "symbol": result.capture.candidate.symbol,
        },
        "capture_failure_isolation_verified": (
            result.capture_failure_isolation_verified
        ),
        "duplicate_protection_verified": result.duplicate_protection_verified,
        "missing_section_block_verified": result.missing_section_block_verified,
        "parity_verified": result.parity_verified,
        "post_observation_block_verified": (
            result.post_observation_block_verified
        ),
        "production_influence": result.production_influence,
        "replay_ready": result.capture.replay_ready,
        "snapshot_sha256": result.capture.snapshot_sha256,
    }
    certificate.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    with summary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(payload))
        writer.writeheader()
        writer.writerow(
            {
                key: json.dumps(value, sort_keys=True)
                if isinstance(value, dict)
                else value
                for key, value in payload.items()
            }
        )
    return certificate, summary


__all__ = [
    "CapturingIntelligenceInputProvider",
    "DSI002AAcceptanceResult",
    "FrozenInputApplicationObserver",
    "FrozenInputAssemblyRequestProvider",
    "GovernedFrozenInputApplicationObserver",
    "IntelligenceInputProvider",
    "export_dsi002a_acceptance",
]
