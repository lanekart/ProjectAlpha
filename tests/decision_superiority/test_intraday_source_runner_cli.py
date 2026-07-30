from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority.intraday_execution_models import (
    IntradayExecutionError,
)
from alpha.decision_superiority.intraday_source_runner import (
    load_daily_references,
)


def _write_daily_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = sorted({field for row in rows for field in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_daily_reference_loader_accepts_governed_raw_aliases(tmp_path: Path) -> None:
    path = tmp_path / "daily.csv"
    _write_daily_csv(
        path,
        [
            {
                "identity_key": "nse:isin:INE000A01000",
                "trading_date": "2024-01-03",
                "raw_open": "100",
                "raw_high": "101",
                "raw_low": "99",
                "raw_close": "100.5",
                "raw_volume": "1000",
                "price_basis": "RAW",
                "source_sha256": "a" * 64,
            }
        ],
    )

    references = load_daily_references(path)

    reference = references[("nse:isin:INE000A01000", date(2024, 1, 3))]
    assert reference.open == 100.0
    assert reference.high == 101.0
    assert reference.low == 99.0
    assert reference.close == 100.5
    assert reference.volume == 1000
    assert reference.price_basis == "RAW"


def test_daily_reference_loader_rejects_conflicting_duplicates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.csv"
    base = {
        "identity_key": "nse:isin:INE000A01000",
        "trading_date": "2024-01-03",
        "open": "100",
        "high": "101",
        "low": "99",
        "volume": "1000",
        "price_basis": "RAW",
        "source_sha256": "a" * 64,
    }
    _write_daily_csv(
        path,
        [
            {**base, "close": "100.5"},
            {**base, "close": "100.6"},
        ],
    )

    with pytest.raises(
        IntradayExecutionError,
        match="DSI013_DAILY_REFERENCE_DUPLICATE_CONFLICT",
    ):
        load_daily_references(path)


def test_benchmark_help_registers_intraday_source_commands() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])

    assert result.exit_code == 0
    assert "decision-superiority-intraday-source-plan" in result.stdout
    assert "decision-superiority-intraday-source-certify" in result.stdout
    assert "decision-superiority-intraday-source-verify" in result.stdout


def test_source_plan_help_is_credential_free() -> None:
    result = CliRunner().invoke(
        benchmark_app,
        ["decision-superiority-intraday-source-plan", "--help"],
    )

    assert result.exit_code == 0
    assert "--dsi009-certificate" in result.stdout
    assert "--output" in result.stdout
    assert "access-token" not in result.stdout.lower()
    assert "instrument-json" not in result.stdout.lower()


def test_source_certify_help_exposes_no_token_option() -> None:
    result = CliRunner().invoke(
        benchmark_app,
        ["decision-superiority-intraday-source-certify", "--help"],
    )

    assert result.exit_code == 0
    assert "--dsi009-certificate" in result.stdout
    assert "--instrument-json" in result.stdout
    assert "--daily-reference-csv" in result.stdout
    assert "--cache-root" in result.stdout
    assert "--output" in result.stdout
    assert "access-token" not in result.stdout.lower()
    assert "upstox-access-token" not in result.stdout.lower()
