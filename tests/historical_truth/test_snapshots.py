from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from alpha.historical_truth import (
    CanonicalPointInTimeWarehouse,
    PointInTimeSnapshotEngine,
)


def _warehouse_with_candle(tmp_path: Path) -> CanonicalPointInTimeWarehouse:
    csv_path = tmp_path / "bhav.csv"
    csv_path.write_text(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,ISIN\n"
        "ABC,EQ,100,110,95,108,1200,INE000A01001\n",
        encoding="utf-8",
    )
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "market.duckdb")
    warehouse.ingest_bhavcopy_csv(
        csv_path,
        trading_date=date(2026, 7, 17),
        source_sha256="abc123",
    )
    return warehouse


def test_build_snapshot_is_deterministic_for_fixed_time(tmp_path: Path) -> None:
    warehouse = _warehouse_with_candle(tmp_path)
    engine = PointInTimeSnapshotEngine(warehouse, tmp_path / "snapshots")
    generated_at = datetime(2026, 7, 20, 8, 30, tzinfo=UTC)

    first = engine.build(date(2026, 7, 17), generated_at=generated_at)
    second = engine.build(date(2026, 7, 17), generated_at=generated_at)

    assert first == second
    assert first.metadata.symbol_count == 1
    assert first.metadata.availability.candles is True
    assert first.metadata.availability.identity is True
    assert first.metadata.completeness_score == 0.333333


def test_persist_load_and_verify_round_trip(tmp_path: Path) -> None:
    warehouse = _warehouse_with_candle(tmp_path)
    engine = PointInTimeSnapshotEngine(warehouse, tmp_path / "snapshots")
    snapshot = engine.build(
        date(2026, 7, 17),
        generated_at=datetime(2026, 7, 20, 8, 30, tzinfo=UTC),
    )

    path = engine.persist(snapshot)
    loaded = engine.load(date(2026, 7, 17))
    verification = engine.verify(loaded)

    assert path.name == "2026-07-17.json"
    assert loaded == snapshot
    assert verification.valid is True
    assert verification.reason is None


def test_persist_is_idempotent_for_identical_snapshot(tmp_path: Path) -> None:
    warehouse = _warehouse_with_candle(tmp_path)
    engine = PointInTimeSnapshotEngine(warehouse, tmp_path / "snapshots")
    snapshot = engine.build(
        date(2026, 7, 17),
        generated_at=datetime(2026, 7, 20, 8, 30, tzinfo=UTC),
    )

    first = engine.persist(snapshot)
    second = engine.persist(snapshot)

    assert first == second


def test_persist_refuses_different_content_for_existing_date(
    tmp_path: Path,
) -> None:
    warehouse = _warehouse_with_candle(tmp_path)
    engine = PointInTimeSnapshotEngine(warehouse, tmp_path / "snapshots")
    first = engine.build(
        date(2026, 7, 17),
        generated_at=datetime(2026, 7, 20, 8, 30, tzinfo=UTC),
    )
    second = engine.build(
        date(2026, 7, 17),
        generated_at=datetime(2026, 7, 20, 8, 31, tzinfo=UTC),
    )
    engine.persist(first)

    with pytest.raises(FileExistsError, match="immutable snapshot"):
        engine.persist(second)


def test_empty_day_snapshot_fails_closed_on_availability(tmp_path: Path) -> None:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "market.duckdb")
    engine = PointInTimeSnapshotEngine(warehouse, tmp_path / "snapshots")

    snapshot = engine.build(
        date(2026, 7, 18),
        generated_at=datetime(2026, 7, 20, 8, 30, tzinfo=UTC),
    )

    assert snapshot.metadata.symbol_count == 0
    assert snapshot.metadata.availability.candles is False
    assert snapshot.metadata.completeness_score == 0.0
