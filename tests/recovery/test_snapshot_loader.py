"""Tests for exact snapshot-backed canonical replay selection."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from alpha.recovery.canonical_replay import (
    CanonicalReplayBar,
    CanonicalReplayStatus,
)
from alpha.recovery.replay_snapshot import (
    CanonicalReplaySnapshot,
    CanonicalReplaySnapshotRepository,
)
from alpha.recovery.snapshot_loader import CanonicalReplaySnapshotLoader

_AS_OF = date(2025, 1, 15)
_TRADE_DATE = date(2025, 1, 10)


def _bar(
    *,
    trading_date: date = _TRADE_DATE,
    as_of: date = _AS_OF,
    status: CanonicalReplayStatus = CanonicalReplayStatus.READY,
    recovery_version: str = "HTR-004-v1.0.0",
) -> CanonicalReplayBar:
    unresolved = (
        ("SEC-1:RIGHTS:2025-01-15",)
        if status is CanonicalReplayStatus.QUARANTINED
        else ()
    )
    return CanonicalReplayBar(
        security_id="SEC-1",
        raw_symbol="ALPHA",
        canonical_symbol="NEWALPHA",
        trading_date=trading_date,
        as_of=as_of,
        raw_open=Decimal("100"),
        raw_high=Decimal("110"),
        raw_low=Decimal("90"),
        raw_close=Decimal("104"),
        raw_volume=Decimal("1000"),
        adjusted_open=Decimal("50"),
        adjusted_high=Decimal("55"),
        adjusted_low=Decimal("45"),
        adjusted_close=Decimal("52"),
        adjusted_volume=Decimal("2000"),
        cumulative_price_factor=Decimal("0.5"),
        cumulative_volume_factor=Decimal("2"),
        applied_event_ids=("SEC-1:SPLIT:2025-01-15",),
        unresolved_event_ids=unresolved,
        status=status,
        recovery_version=recovery_version,
    )


def _repository(
    tmp_path: Path,
    bars: tuple[CanonicalReplayBar, ...],
) -> CanonicalReplaySnapshotRepository:
    repository = CanonicalReplaySnapshotRepository(tmp_path)
    repository.write(CanonicalReplaySnapshot.build(bars, as_of=_AS_OF))
    return repository


def test_loads_exact_snapshot_and_requested_trade_date(tmp_path: Path) -> None:
    older = _bar(trading_date=date(2025, 1, 9))
    requested = _bar()
    loader = CanonicalReplaySnapshotLoader(_repository(tmp_path, (older, requested)))

    result = loader.load(trade_date=_TRADE_DATE, as_of=_AS_OF)

    assert result.trade_date == _TRADE_DATE
    assert result.as_of == _AS_OF
    assert result.recovery_version == "HTR-004-v1.0.0"
    assert result.bars == (requested,)
    assert len(result.snapshot_sha256) == 64
    assert len(result.selected_sha256) == 64


def test_requires_exact_as_of_snapshot_without_fallback(tmp_path: Path) -> None:
    loader = CanonicalReplaySnapshotLoader(_repository(tmp_path, (_bar(),)))

    with pytest.raises(FileNotFoundError, match="snapshot not found"):
        loader.load(trade_date=_TRADE_DATE, as_of=date(2025, 1, 16))


def test_rejects_trade_date_after_as_of(tmp_path: Path) -> None:
    loader = CanonicalReplaySnapshotLoader(_repository(tmp_path, (_bar(),)))

    with pytest.raises(ValueError, match="trade_date cannot be after"):
        loader.load(trade_date=date(2025, 1, 16), as_of=_AS_OF)


def test_rejects_missing_requested_trade_date(tmp_path: Path) -> None:
    loader = CanonicalReplaySnapshotLoader(
        _repository(tmp_path, (_bar(trading_date=date(2025, 1, 9)),))
    )

    with pytest.raises(FileNotFoundError, match="contains no bars"):
        loader.load(trade_date=_TRADE_DATE, as_of=_AS_OF)


def test_rejects_quarantined_snapshot_selection(tmp_path: Path) -> None:
    loader = CanonicalReplaySnapshotLoader(
        _repository(
            tmp_path,
            (_bar(status=CanonicalReplayStatus.QUARANTINED),),
        )
    )

    with pytest.raises(ValueError, match="selection is quarantined"):
        loader.load(trade_date=_TRADE_DATE, as_of=_AS_OF)


def test_rejects_mixed_recovery_versions(tmp_path: Path) -> None:
    older = replace(
        _bar(trading_date=date(2025, 1, 9)),
        recovery_version="HTR-004-v0.9.0",
    )
    loader = CanonicalReplaySnapshotLoader(_repository(tmp_path, (_bar(), older)))

    with pytest.raises(ValueError, match="mixed recovery versions"):
        loader.load(trade_date=_TRADE_DATE, as_of=_AS_OF)


def test_rejects_tampered_snapshot_manifest(tmp_path: Path) -> None:
    repository = _repository(tmp_path, (_bar(),))
    manifest_path = tmp_path / _AS_OF.isoformat() / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["snapshot_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    loader = CanonicalReplaySnapshotLoader(repository)

    with pytest.raises(ValueError, match="snapshot_sha256"):
        loader.load(trade_date=_TRADE_DATE, as_of=_AS_OF)
