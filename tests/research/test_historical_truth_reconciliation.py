from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import duckdb

from alpha.historical_truth_reconciliation import (
    DIAGNOSTIC_ONLY,
    PRODUCTION_INFLUENCE,
    _classify,
    export_reconciliation,
    run_reconciliation,
)


def _write_inventory(path: Path) -> None:
    rows = [
        {"dataset_key": "corporate_actions", "status": "PRESENT_EMPTY"},
        {"dataset_key": "security_identity", "status": "PARTIAL"},
        {"dataset_key": "listing_history", "status": "MISSING"},
        {"dataset_key": "delisting_history", "status": "MISSING"},
        {"dataset_key": "trading_calendar", "status": "DERIVED_ONLY"},
        {"dataset_key": "benchmark_history", "status": "MISSING"},
        {"dataset_key": "sector_mapping", "status": "MISSING"},
        {"dataset_key": "index_constituents", "status": "MISSING"},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["dataset_key", "status"])
        writer.writeheader()
        writer.writerows(rows)


def _build_database(path: Path) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE daily_candle (
                trading_date DATE,
                symbol VARCHAR,
                close DOUBLE
            )
            """
        )
        connection.execute(
            """
            INSERT INTO daily_candle VALUES
                ('2026-01-01', 'AAA', 100.0),
                ('2026-01-02', 'AAA', 101.0),
                ('2026-01-06', 'AAA', 102.0)
            """
        )
        connection.execute(
            """
            CREATE TABLE corporate_action (
                ex_date DATE,
                symbol VARCHAR,
                action_type VARCHAR
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE legacy_sector_mapping (
                effective_date DATE,
                symbol VARCHAR,
                sector VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO legacy_sector_mapping VALUES
                ('2026-01-01', 'AAA', 'Industrials')
            """
        )


def test_classification_precedence(tmp_path: Path) -> None:
    raw = tmp_path / "corporate_actions.csv"
    raw.write_text("date,symbol\n", encoding="utf-8")

    assert (
        _classify(
            canonical_exists=True,
            canonical_rows=10,
            alternate_tables=(),
            raw_files=(),
            source_proof_found=False,
            parser_found=False,
            inventory_status="PARTIAL",
        )
        == "CANONICAL_TABLE_POPULATED_UNCERTIFIED"
    )
    assert (
        _classify(
            canonical_exists=False,
            canonical_rows=None,
            alternate_tables=("main.legacy",),
            raw_files=(),
            source_proof_found=False,
            parser_found=False,
            inventory_status="MISSING",
        )
        == "INGESTED_NONCANONICAL"
    )
    assert (
        _classify(
            canonical_exists=False,
            canonical_rows=None,
            alternate_tables=(),
            raw_files=(raw,),
            source_proof_found=True,
            parser_found=True,
            inventory_status="MISSING",
        )
        == "PARSED_NOT_INGESTED"
    )
    assert (
        _classify(
            canonical_exists=False,
            canonical_rows=None,
            alternate_tables=(),
            raw_files=(),
            source_proof_found=True,
            parser_found=False,
            inventory_status="MISSING",
        )
        == "SOURCE_PROOF_ONLY"
    )
    assert (
        _classify(
            canonical_exists=True,
            canonical_rows=0,
            alternate_tables=(),
            raw_files=(),
            source_proof_found=False,
            parser_found=False,
            inventory_status="PRESENT_EMPTY",
        )
        == "CANONICAL_TABLE_EMPTY"
    )
    assert (
        _classify(
            canonical_exists=False,
            canonical_rows=None,
            alternate_tables=(),
            raw_files=(),
            source_proof_found=False,
            parser_found=False,
            inventory_status="MISSING",
        )
        == "TRULY_MISSING"
    )


def test_reconciliation_detects_existing_evidence_and_holidays(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _build_database(database)
    inventory = tmp_path / "dataset_inventory.csv"
    _write_inventory(inventory)

    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "corporate_action_adapter.py").write_text(
        "def parse_corporate_actions(): pass\n",
        encoding="utf-8",
    )
    (repository / "corporate_actions.csv").write_text(
        "ex_date,symbol,action_type\n2026-01-03,AAA,SPLIT\n",
        encoding="utf-8",
    )
    (repository / "exchange_holidays_2026.csv").write_text(
        "date,name\n2026-01-05,Exchange holiday\n",
        encoding="utf-8",
    )

    rows, sessions = run_reconciliation(
        database=database,
        repository_root=repository,
        snapshots=None,
        inventory_csv=inventory,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 6),
    )
    by_key = {row.dataset_key: row for row in rows}

    assert by_key["corporate_actions"].primary_classification == "PARSED_NOT_INGESTED"
    assert by_key["corporate_actions"].recoverable_without_download is True
    assert by_key["sector_mapping"].primary_classification == "INGESTED_NONCANONICAL"
    assert by_key["listing_history"].primary_classification == "TRULY_MISSING"
    assert all(row.production_influence is False for row in rows)

    by_date = {row.session_date: row.classification for row in sessions}
    assert by_date == {"2026-01-05": "VERIFIED_EXCHANGE_HOLIDAY"}


def test_exports_are_deterministic_and_diagnostic_only(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _build_database(database)
    inventory = tmp_path / "dataset_inventory.csv"
    _write_inventory(inventory)
    repository = tmp_path / "repo"
    repository.mkdir()

    rows, sessions = run_reconciliation(
        database=database,
        repository_root=repository,
        snapshots=None,
        inventory_csv=inventory,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 6),
    )
    output = tmp_path / "artifacts"
    first = export_reconciliation(
        rows,
        sessions,
        output=output,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 6),
    )
    first_contents = {path.name: path.read_bytes() for path in first}
    second = export_reconciliation(
        rows,
        sessions,
        output=output,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 6),
    )

    assert [path.name for path in first] == [path.name for path in second]
    assert first_contents == {path.name: path.read_bytes() for path in second}
    assert DIAGNOSTIC_ONLY is True
    assert PRODUCTION_INFLUENCE is False
    report = (output / "report.md").read_text(encoding="utf-8")
    assert "PRODUCTION_INFLUENCE=false" in report
    assert (
        "No production signal, gate, portfolio, or risk policy was changed." in report
    )
