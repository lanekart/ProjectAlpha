from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import duckdb

from alpha.research_dataset_inventory import build_inventory, export_inventory


def _database(path: Path, sessions: tuple[date, ...]) -> None:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            "CREATE TABLE daily_candle("
            "trading_date DATE, exchange VARCHAR, symbol VARCHAR, "
            "series VARCHAR, isin VARCHAR, open_price DECIMAL(18,4), "
            "high_price DECIMAL(18,4), low_price DECIMAL(18,4), "
            "close_price DECIMAL(18,4), volume BIGINT, "
            "source_sha256 VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO daily_candle VALUES "
            "(?, 'NSE', 'AAA', 'EQ', 'INE0001', 99, 101, 98, 100, "
            "1000, 'hash')",
            [(session,) for session in sessions],
        )
        connection.execute(
            "CREATE TABLE corporate_action("
            "ex_date DATE, exchange VARCHAR, symbol VARCHAR, "
            "series VARCHAR, isin VARCHAR, action_type VARCHAR)"
        )
        connection.execute(
            "CREATE TABLE security_identity("
            "exchange VARCHAR, symbol VARCHAR, series VARCHAR, "
            "isin VARCHAR, valid_from DATE, valid_to DATE)"
        )
    finally:
        connection.close()


def _snapshots(root: Path, sessions: tuple[date, ...]) -> None:
    destination = root / "nse" / "2026"
    destination.mkdir(parents=True)
    for session in sessions:
        payload = {
            "snapshot_date": session.isoformat(),
            "availability": {
                "candles": True,
                "identity": True,
                "corporate_actions": False,
                "delivery": False,
                "indices": False,
                "vix": False,
            },
        }
        (destination / f"{session.isoformat()}.json").write_text(
            json.dumps(payload, sort_keys=True),
            encoding="utf-8",
        )


def test_inventory_uses_canonical_candles_and_snapshots(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    snapshots = tmp_path / "snapshots"
    sessions = (
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
    )
    _database(database, sessions)
    _snapshots(snapshots, sessions)

    rows = build_inventory(
        year=2026,
        database=database,
        snapshots=snapshots,
        as_of=date(2026, 1, 6),
    )
    by_key = {row.dataset_key: row for row in rows}

    daily = by_key["daily_ohlcv"]
    assert daily.status == "COMPLETE_CANDIDATE"
    assert daily.certification_ready is True
    assert daily.matched_tables == "main.daily_candle"
    assert daily.observed_sessions == 3
    assert daily.last_date == "2026-01-06"
    assert "snapshot_sessions=3" in daily.evidence

    identity = by_key["security_identity"]
    assert identity.status == "PARTIAL"
    assert identity.certification_ready is False
    assert "candle_isin_coverage=100.00%" in identity.evidence
    assert by_key["corporate_actions"].status == "PRESENT_EMPTY"
    assert by_key["trading_calendar"].status == "DERIVED_ONLY"
    assert all(row.diagnostic_only for row in rows)
    assert not any(row.production_influence for row in rows)


def test_as_of_caps_expected_sessions_and_export_is_deterministic(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    snapshots = tmp_path / "snapshots"
    sessions = (date(2026, 7, 17), date(2026, 7, 20))
    _database(database, sessions)
    _snapshots(snapshots, sessions)
    as_of = date(2026, 7, 20)
    rows = build_inventory(
        year=2026,
        database=database,
        snapshots=snapshots,
        as_of=as_of,
    )
    output = tmp_path / "artifacts"

    first_paths = export_inventory(
        rows,
        year=2026,
        output=output,
        as_of=as_of,
    )
    first = {path.name: path.read_bytes() for path in first_paths}
    second_paths = export_inventory(
        rows,
        year=2026,
        output=output,
        as_of=as_of,
    )
    second = {path.name: path.read_bytes() for path in second_paths}

    assert first == second
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["period_end"] == "2026-07-20"
    assert summary["certification"] == "NOT_CERTIFIED"
    assert summary["production_influence"] is False
    assert "daily_ohlcv" not in summary["blocking_datasets"]
    assert summary["recommended_next_action"] == "Corporate Actions"
    with (output / "dataset_inventory.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        records = list(csv.DictReader(handle))
    assert len(records) == 12
    report = (output / "report.md").read_text(encoding="utf-8")
    assert "Period end: **2026-07-20**" in report
    assert report.endswith("**PRODUCTION_INFLUENCE=false**\n")


def test_missing_database_is_reported_without_fabrication(
    tmp_path: Path,
) -> None:
    rows = build_inventory(
        year=2026,
        database=tmp_path / "missing.duckdb",
        snapshots=tmp_path / "missing-snapshots",
        as_of=date(2026, 7, 20),
    )

    assert all(row.status == "MISSING" for row in rows)
    assert all(row.row_count is None for row in rows)
    assert all(row.coverage_percent is None for row in rows)
