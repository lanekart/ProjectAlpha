"""Tests for immutable HTR-004 canonical replay snapshots."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from alpha.recovery.canonical_replay import CanonicalReplayBuilder
from alpha.recovery.corporate_actions import CorporateActionBar, CorporateActionTimeline
from alpha.recovery.replay_snapshot import (
    CanonicalReplaySnapshot,
    CanonicalReplaySnapshotRepository,
)


def _bar(trading_date: date, close: str = "100") -> CorporateActionBar:
    return CorporateActionBar(
        security_id="SEC-1",
        symbol="ALPHA",
        trading_date=trading_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal("1000"),
    )


def _snapshot(as_of: date, *bars: CorporateActionBar) -> CanonicalReplaySnapshot:
    replay = CanonicalReplayBuilder(CorporateActionTimeline(())).build(
        bars,
        as_of=as_of,
    )
    return CanonicalReplaySnapshot.build(replay, as_of=as_of)


def test_repository_round_trip_is_idempotent(tmp_path: Path) -> None:
    snapshot = _snapshot(date(2025, 1, 15), _bar(date(2025, 1, 10)))
    repository = CanonicalReplaySnapshotRepository(tmp_path)

    first = repository.write(snapshot)
    second = repository.write(snapshot)
    restored = repository.read(date(2025, 1, 15))

    assert first == second
    assert restored == snapshot
    assert repository.available_dates() == (date(2025, 1, 15),)


def test_repository_detects_tampered_replay_content(tmp_path: Path) -> None:
    snapshot = _snapshot(date(2025, 1, 15), _bar(date(2025, 1, 10)))
    repository = CanonicalReplaySnapshotRepository(tmp_path)
    directory = repository.write(snapshot)
    data_path = directory / "replay.jsonl"
    data_path.write_text(
        data_path.read_text(encoding="utf-8").replace("100", "101", 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="snapshot_sha256"):
        repository.read(date(2025, 1, 15))


def test_repository_refuses_conflicting_immutable_snapshot(tmp_path: Path) -> None:
    repository = CanonicalReplaySnapshotRepository(tmp_path)
    first = _snapshot(date(2025, 1, 15), _bar(date(2025, 1, 10), "100"))
    second = _snapshot(date(2025, 1, 15), _bar(date(2025, 1, 10), "101"))
    repository.write(first)

    with pytest.raises(ValueError, match="content already differs"):
        repository.write(second)


def test_latest_on_or_before_uses_nearest_snapshot(tmp_path: Path) -> None:
    repository = CanonicalReplaySnapshotRepository(tmp_path)
    older = _snapshot(date(2025, 1, 10), _bar(date(2025, 1, 10)))
    newer = _snapshot(date(2025, 1, 15), _bar(date(2025, 1, 15)))
    repository.write(newer)
    repository.write(older)
    (tmp_path / "notes").mkdir()

    restored = repository.latest_on_or_before(date(2025, 1, 12))

    assert restored.as_of == date(2025, 1, 10)


def test_snapshot_rejects_duplicate_replay_keys() -> None:
    as_of = date(2025, 1, 15)
    replay = CanonicalReplayBuilder(CorporateActionTimeline(())).build(
        (_bar(date(2025, 1, 10)),),
        as_of=as_of,
    )

    with pytest.raises(ValueError, match="duplicate bars"):
        CanonicalReplaySnapshot.build((*replay, *replay), as_of=as_of)
