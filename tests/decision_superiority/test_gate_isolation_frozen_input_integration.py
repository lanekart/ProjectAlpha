from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from alpha.decision_superiority.gate_isolation_frozen_input_integration import (
    FrozenInputCaptureIntegration,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenCandidateInputSnapshot,
    FrozenInputSection,
    FrozenInputSectionSnapshot,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey


def _candidate(symbol: str = "AAA") -> FrozenCandidateKey:
    return FrozenCandidateKey("RAW", "2026-07-26", symbol, f"fp-{symbol.lower()}")


def _snapshot(candidate: FrozenCandidateKey) -> FrozenCandidateInputSnapshot:
    sections = tuple(
        FrozenInputSectionSnapshot.from_mapping(
            section=section,
            payload={"section": section.value, "candidate": candidate.symbol},
            source_version="v1",
            observed_on=candidate.observed_on,
        )
        for section in FrozenInputSection
    )
    return FrozenCandidateInputSnapshot.build(
        candidate=candidate,
        sections=sections,
    )


@dataclass
class _Assembler:
    captured: list[FrozenCandidateKey]
    override: FrozenCandidateKey | None = None

    def assemble(
        self,
        *,
        candidate: FrozenCandidateKey,
    ) -> FrozenCandidateInputSnapshot:
        self.captured.append(candidate)
        return _snapshot(self.override or candidate)


def test_integration_captures_complete_candidate_snapshot(tmp_path: Path) -> None:
    assembler = _Assembler([])
    candidate = _candidate()
    integration = FrozenInputCaptureIntegration(
        assembler=assembler,
        capture_root=tmp_path,
    )

    result = integration.capture_candidate(candidate=candidate)

    assert assembler.captured == [candidate]
    assert result.candidate == candidate
    assert result.capture.replay_ready is True
    assert result.capture.snapshot_path.is_file()
    assert result.capture.index_path.is_file()
    assert result.recommendation_influence is False
    assert result.approval_influence is False
    assert result.portfolio_influence is False
    assert result.execution_influence is False
    assert result.production_influence is False


def test_integration_rejects_assembler_identity_mismatch(tmp_path: Path) -> None:
    integration = FrozenInputCaptureIntegration(
        assembler=_Assembler([], override=_candidate("BBB")),
        capture_root=tmp_path,
    )

    with pytest.raises(ValueError, match="assembled snapshot candidate identity"):
        integration.capture_candidate(candidate=_candidate("AAA"))


def test_integration_remains_append_only(tmp_path: Path) -> None:
    candidate = _candidate()
    integration = FrozenInputCaptureIntegration(
        assembler=_Assembler([]),
        capture_root=tmp_path,
    )

    integration.capture_candidate(candidate=candidate)

    with pytest.raises(
        (FileExistsError, ValueError),
        match="already exists|already has",
    ):
        integration.capture_candidate(candidate=candidate)


def test_integration_does_not_accept_influence_flags(tmp_path: Path) -> None:
    candidate = _candidate()
    result = FrozenInputCaptureIntegration(
        assembler=_Assembler([]),
        capture_root=tmp_path,
    ).capture_candidate(candidate=candidate)

    with pytest.raises(ValueError, match="influence flags"):
        type(result)(
            candidate=result.candidate,
            capture=result.capture,
            recommendation_influence=True,
        )
