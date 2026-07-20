from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from alpha.historical_truth_reconciliation_v11 import (
    DIAGNOSTIC_ONLY,
    PRODUCTION_INFLUENCE,
    export_precision_audit,
    run_precision_audit,
)


def _database(path: Path) -> None:
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
                ('2026-01-14', 'AAA', 100.0),
                ('2026-01-16', 'AAA', 101.0)
            """
        )


def test_content_schema_required_for_raw_data(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "corporate_actions.csv").write_text(
        "ex_date,symbol,action_type\n2026-01-10,AAA,SPLIT\n",
        encoding="utf-8",
    )
    (repository / "benchmark_report.csv").write_text(
        "metric,value\nauc,0.7\n",
        encoding="utf-8",
    )
    artifacts = repository / "artifacts"
    artifacts.mkdir()
    (artifacts / "sector_mapping.csv").write_text(
        "symbol,sector\nAAA,Industrials\n",
        encoding="utf-8",
    )

    evidence, datasets, sessions = run_precision_audit(
        repository_root=repository,
        database=database,
        period_start=date(2026, 1, 14),
        period_end=date(2026, 1, 16),
    )
    by_key = {row.dataset_key: row for row in datasets}

    assert by_key["corporate_actions"].classification == "RAW_DATA_CONFIRMED"
    assert by_key["benchmark_history"].classification == (
        "EVIDENCE_ONLY_NO_USABLE_RAW_DATA"
    )
    assert by_key["sector_mapping"].classification == "NO_USABLE_RAW_DATA"
    assert all("artifacts/" not in row.relative_path for row in evidence)
    assert sessions[0].classification == "VERIFIED_EXCHANGE_HOLIDAY"


def test_exact_paths_and_deterministic_exports(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    repository = tmp_path / "repo"
    raw = repository / "raw"
    raw.mkdir(parents=True)
    (raw / "index_constituents.csv").write_text(
        "effective_date,symbol\n2026-01-01,AAA\n",
        encoding="utf-8",
    )

    evidence, datasets, sessions = run_precision_audit(
        repository_root=repository,
        database=database,
        period_start=date(2026, 1, 14),
        period_end=date(2026, 1, 16),
    )
    output = tmp_path / "output"
    first = export_precision_audit(
        evidence,
        datasets,
        sessions,
        output=output,
        period_start=date(2026, 1, 14),
        period_end=date(2026, 1, 16),
    )
    before = {path.name: path.read_bytes() for path in first}
    second = export_precision_audit(
        evidence,
        datasets,
        sessions,
        output=output,
        period_start=date(2026, 1, 14),
        period_end=date(2026, 1, 16),
    )

    assert before == {path.name: path.read_bytes() for path in second}
    precision = (output / "evidence_precision.csv").read_text(encoding="utf-8")
    assert "raw/index_constituents.csv" in precision
    report = (output / "report.md").read_text(encoding="utf-8")
    assert "PRODUCTION_INFLUENCE=false" in report
    assert DIAGNOSTIC_ONLY is True
    assert PRODUCTION_INFLUENCE is False
