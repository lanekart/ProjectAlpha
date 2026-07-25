from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from alpha.decision_superiority.gate_isolation_frozen_input_capture import (
    FrozenInputCaptureWriter,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenCandidateInputSnapshot,
    FrozenInputSection,
    FrozenInputSectionSnapshot,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey


def _candidate(symbol: str = "AAA") -> FrozenCandidateKey:
    return FrozenCandidateKey("RAW", "2026-07-26", symbol, f"fp-{symbol.lower()}")


def _snapshot(
    candidate: FrozenCandidateKey,
    *,
    complete: bool = True,
) -> FrozenCandidateInputSnapshot:
    sections = (
        tuple(FrozenInputSection) if complete else (FrozenInputSection.SOURCE_LINEAGE,)
    )
    return FrozenCandidateInputSnapshot.build(
        candidate=candidate,
        sections=tuple(
            FrozenInputSectionSnapshot.from_mapping(
                section=section,
                payload={"section": section.value, "symbol": candidate.symbol},
                source_version="v1",
                observed_on=candidate.observed_on,
            )
            for section in sections
        ),
    )


def test_capture_writes_canonical_snapshot_and_index(tmp_path: Path) -> None:
    snapshot = _snapshot(_candidate())

    result = FrozenInputCaptureWriter(tmp_path).capture(snapshot)

    assert result.replay_ready is True
    assert result.production_influence is False
    assert result.snapshot_path.is_file()
    assert result.index_path.is_file()
    payload = json.loads(result.snapshot_path.read_text(encoding="utf-8"))
    assert payload["snapshot_sha256"] == snapshot.snapshot_sha256
    assert payload["production_influence"] is False
    assert len(payload["sections"]) == len(FrozenInputSection)
    with result.index_path.open(encoding="utf-8", newline="") as handle:
        rows = tuple(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAA"
    assert rows[0]["replay_ready"] == "true"
    assert rows[0]["production_influence"] == "false"


def test_capture_is_append_only_for_candidate(tmp_path: Path) -> None:
    snapshot = _snapshot(_candidate())
    writer = FrozenInputCaptureWriter(tmp_path)
    writer.capture(snapshot)

    with pytest.raises((FileExistsError, ValueError)):
        writer.capture(snapshot)


def test_capture_rejects_incomplete_snapshot(tmp_path: Path) -> None:
    snapshot = _snapshot(_candidate(), complete=False)

    with pytest.raises(ValueError, match="replay-ready snapshot"):
        FrozenInputCaptureWriter(tmp_path).capture(snapshot)


def test_capture_appends_distinct_candidates_deterministically(
    tmp_path: Path,
) -> None:
    writer = FrozenInputCaptureWriter(tmp_path)
    first = writer.capture(_snapshot(_candidate("AAA")))
    second = writer.capture(_snapshot(_candidate("BBB")))

    assert first.snapshot_path != second.snapshot_path
    with second.index_path.open(encoding="utf-8", newline="") as handle:
        rows = tuple(csv.DictReader(handle))
    assert tuple(row["symbol"] for row in rows) == ("AAA", "BBB")


def test_snapshot_filename_does_not_escape_capture_directory(
    tmp_path: Path,
) -> None:
    candidate = FrozenCandidateKey(
        "RAW",
        "2026-07-26",
        "AAA/BBB",
        "fp-safe",
    )

    result = FrozenInputCaptureWriter(tmp_path).capture(_snapshot(candidate))

    assert result.snapshot_path.parent == tmp_path / "snapshots"
    assert "/" not in result.snapshot_path.name
