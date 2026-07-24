from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from alpha.historical_truth import (
    CanonicalPointInTimeWarehouse,
    HistoricalTruthReplayStore,
    PointInTimeSnapshotEngine,
)


def _source(
    tmp_path: Path,
    *,
    dates: tuple[date, ...] = (date(2026, 7, 17), date(2026, 7, 20)),
    persist_dates: tuple[date, ...] | None = None,
) -> tuple[Path, Path]:
    root = tmp_path / "alpha_data"
    database = root / "warehouse" / "historical_truth.duckdb"
    snapshot_root = root / "snapshots"
    warehouse = CanonicalPointInTimeWarehouse(database)
    snapshots = PointInTimeSnapshotEngine(warehouse, snapshot_root)
    for offset, trading_date in enumerate(dates):
        csv_path = tmp_path / f"{trading_date.isoformat()}.csv"
        csv_path.write_text(
            "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,ISIN\n"
            f"ABC,EQ,{100 + offset},{110 + offset},{95 + offset},"
            f"{108 + offset},1000,INE000A01001\n"
            f"ABC,T0,{101 + offset},{111 + offset},{96 + offset},"
            f"{109 + offset},50,INE000A01001\n",
            encoding="utf-8",
        )
        warehouse.ingest_bhavcopy_csv(csv_path, trading_date=trading_date)
        if persist_dates is None or trading_date in persist_dates:
            snapshot = snapshots.build(
                trading_date,
                generated_at=datetime(2026, 7, 21, tzinfo=UTC),
            )
            snapshots.persist(snapshot)
    return database, snapshot_root


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_replay_store_exposes_verified_eq_candles_without_source_writes(
    tmp_path: Path,
) -> None:
    database, snapshot_root = _source(tmp_path)
    before = _sha256(database)

    with HistoricalTruthReplayStore(
        database_path=database,
        snapshot_root=snapshot_root,
    ) as store:
        manifest = store.manifest()
        frame = store.find_by_trade_date(date(2026, 7, 17))

    assert manifest.dataset_version == "HISTORICAL_TRUTH_SNAPSHOT_V1"
    assert manifest.sessions == 2
    assert manifest.rows == 2
    assert manifest.symbols == 1
    assert frame["symbol"].tolist() == ["ABC"]
    assert frame["close"].tolist() == [108.0]
    assert frame["isin"].tolist() == ["INE000A01001"]
    assert frame["security_id"].tolist() == ["nse:isin:INE000A01001"]
    assert _sha256(database) == before


def test_replay_store_is_deterministic(tmp_path: Path) -> None:
    database, snapshot_root = _source(tmp_path)

    with HistoricalTruthReplayStore(
        database_path=database,
        snapshot_root=snapshot_root,
    ) as first:
        first_manifest = first.manifest()
        first_rows = first.find_history_by_symbols(
            symbols=("ABC",),
            end_date=date(2026, 7, 20),
            limit=10,
        ).to_dict(orient="records")
    with HistoricalTruthReplayStore(
        database_path=database,
        snapshot_root=snapshot_root,
    ) as second:
        second_manifest = second.manifest()
        second_rows = second.find_history_by_symbols(
            symbols=("ABC",),
            end_date=date(2026, 7, 20),
            limit=10,
        ).to_dict(orient="records")

    assert first_manifest == second_manifest
    assert first_rows == second_rows
    assert {row["isin"] for row in first_rows} == {"INE000A01001"}
    assert {row["security_id"] for row in first_rows} == {"nse:isin:INE000A01001"}


def test_replay_store_exposes_exact_trade_dates_and_ranges(tmp_path: Path) -> None:
    database, snapshot_root = _source(tmp_path)

    with HistoricalTruthReplayStore(
        database_path=database,
        snapshot_root=snapshot_root,
    ) as store:
        dates = store.find_trade_dates(
            start=date(2026, 7, 17),
            end=date(2026, 7, 20),
        )
        frame = store.find_range_by_symbols(
            symbols=("ABC",),
            start_date=date(2026, 7, 20),
            end_date=date(2026, 7, 20),
        )

    assert dates == (date(2026, 7, 17), date(2026, 7, 20))
    assert frame["trade_date"].dt.date.tolist() == [date(2026, 7, 20)]
    assert frame["close"].tolist() == [109.0]
    assert frame["isin"].tolist() == ["INE000A01001"]
    assert frame["security_id"].tolist() == ["nse:isin:INE000A01001"]


def test_replay_store_fails_closed_when_observed_snapshot_is_missing(
    tmp_path: Path,
) -> None:
    first = date(2026, 7, 17)
    database, snapshot_root = _source(tmp_path, persist_dates=(first,))

    with pytest.raises(ValueError, match="immutable snapshot missing for 2026-07-20"):
        HistoricalTruthReplayStore(
            database_path=database,
            snapshot_root=snapshot_root,
        )


def test_replay_store_fails_closed_on_snapshot_tampering(tmp_path: Path) -> None:
    database, snapshot_root = _source(
        tmp_path,
        dates=(date(2026, 7, 17),),
    )
    snapshot_path = snapshot_root / "nse" / "2026" / "2026-07-17.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["candles"][0]["close_price"] = 107.0
    snapshot_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="snapshot checksum mismatch"):
        HistoricalTruthReplayStore(
            database_path=database,
            snapshot_root=snapshot_root,
        )


def test_replay_store_respects_requested_window(tmp_path: Path) -> None:
    database, snapshot_root = _source(tmp_path)

    with HistoricalTruthReplayStore(
        database_path=database,
        snapshot_root=snapshot_root,
        start=date(2026, 7, 20),
        end=date(2026, 7, 20),
    ) as store:
        assert store.trade_dates() == (date(2026, 7, 20),)
        assert store.manifest().rows == 1
