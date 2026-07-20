from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

from alpha.research_dataset_inventory import build_inventory, export_inventory


def _weekdays(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() < 5
    )


def _database(path: Path) -> None:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            "CREATE TABLE daily_prices("
            "trading_date DATE, symbol VARCHAR, close DECIMAL(18,4))"
        )
        sessions = _weekdays(date(2026, 1, 1), date(2026, 1, 30))
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, 'AAA', 100)",
            [(session,) for session in sessions],
        )
        connection.execute(
            "CREATE TABLE corporate_actions("
            "effective_date DATE, symbol VARCHAR, action_type VARCHAR)"
        )
        connection.execute(
            "INSERT INTO corporate_actions VALUES (?, 'AAA', 'SPLIT')",
            [date(2026, 1, 15)],
        )
    finally:
        connection.close()


def test_inventory_reports_present_partial_and_missing_datasets(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "security_master_2026.csv").write_text(
        "isin,symbol\nINE0001,AAA\n",
        encoding="utf-8",
    )
    _database(database)

    rows = build_inventory(
        year=2026,
        database=database,
        snapshots=snapshots,
    )
    by_key = {row.dataset_key: row for row in rows}

    assert by_key["daily_ohlcv"].status == "COMPLETE_CANDIDATE"
    assert by_key["daily_ohlcv"].coverage_percent == "100.00"
    assert by_key["daily_ohlcv"].missing_sessions == 0
    assert by_key["corporate_actions"].status == "PARTIAL"
    assert by_key["security_identity"].matched_files == 1
    assert by_key["delivery_percentage"].status == "MISSING"
    assert all(row.diagnostic_only for row in rows)
    assert not any(row.production_influence for row in rows)


def test_export_is_deterministic_and_not_certified_with_blockers(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    rows = build_inventory(year=2026, database=database, snapshots=None)
    output = tmp_path / "artifacts"

    first_paths = export_inventory(rows, year=2026, output=output)
    first = {path.name: path.read_bytes() for path in first_paths}
    second_paths = export_inventory(rows, year=2026, output=output)
    second = {path.name: path.read_bytes() for path in second_paths}

    assert first == second
    summary = json.loads(
        (output / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["certification"] == "NOT_CERTIFIED"
    assert summary["production_influence"] is False
    assert "corporate_actions" in summary["blocking_datasets"]
    with (output / "dataset_inventory.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        records = list(csv.DictReader(handle))
    assert len(records) == 12
    report = (output / "report.md").read_text(encoding="utf-8")
    assert report.endswith("**PRODUCTION_INFLUENCE=false**\n")


def test_missing_database_is_reported_without_fabrication(
    tmp_path: Path,
) -> None:
    rows = build_inventory(
        year=2026,
        database=tmp_path / "missing.duckdb",
        snapshots=tmp_path / "missing-snapshots",
    )

    assert all(row.status == "MISSING" for row in rows)
    assert all(row.row_count is None for row in rows)
    assert all(row.coverage_percent is None for row in rows)
