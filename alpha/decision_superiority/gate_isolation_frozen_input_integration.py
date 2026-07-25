"""Diagnostic-only integration boundary for forward frozen-input capture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from alpha.decision_superiority.gate_isolation_frozen_input_capture import (
    FrozenInputCaptureResult,
    FrozenInputCaptureWriter,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenCandidateInputSnapshot,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey


class FrozenInputSnapshotAssembler(Protocol):
    """Assemble all seven point-in-time sections for a newly created candidate."""

    def assemble(
        self,
        *,
        candidate: FrozenCandidateKey,
    ) -> FrozenCandidateInputSnapshot:
        """Return a complete candidate-bound frozen-input snapshot."""


@dataclass(frozen=True, slots=True)
class FrozenInputCaptureIntegrationResult:
    """Result of one diagnostic-only candidate capture integration call."""

    candidate: FrozenCandidateKey
    capture: FrozenInputCaptureResult
    recommendation_influence: bool = False
    approval_influence: bool = False
    portfolio_influence: bool = False
    execution_influence: bool = False
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.capture.candidate != self.candidate:
            raise ValueError("capture candidate identity does not match integration result")
        if any(
            (
                self.recommendation_influence,
                self.approval_influence,
                self.portfolio_influence,
                self.execution_influence,
                self.production_influence,
            )
        ):
            raise ValueError("frozen-input integration influence flags must remain false")


class FrozenInputCaptureIntegration:
    """Capture a newly created candidate without affecting decision behaviour."""

    def __init__(
        self,
        *,
        assembler: FrozenInputSnapshotAssembler,
        capture_root: Path,
    ) -> None:
        self._assembler = assembler
        self._writer = FrozenInputCaptureWriter(capture_root)

    def capture_candidate(
        self,
        *,
        candidate: FrozenCandidateKey,
    ) -> FrozenInputCaptureIntegrationResult:
        """Assemble, validate, and append one complete candidate snapshot."""

        snapshot = self._assembler.assemble(candidate=candidate)
        if snapshot.candidate != candidate:
            raise ValueError("assembled snapshot candidate identity mismatch")
        capture = self._writer.capture(snapshot)
        return FrozenInputCaptureIntegrationResult(
            candidate=candidate,
            capture=capture,
        )


__all__ = [
    "FrozenInputCaptureIntegration",
    "FrozenInputCaptureIntegrationResult",
    "FrozenInputSnapshotAssembler",
]
