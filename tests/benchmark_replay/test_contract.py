from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.engine import observed_equal_weight_comparison
from alpha.benchmark_replay.models import (
    BASELINE_ID,
    PRODUCTION_INFLUENCE,
    REPLAY_CLASSIFICATION,
    BenchmarkPolicy,
    BenchmarkReplayReport,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore


def test_canonical_policy_matches_frozen_research_defaults() -> None:
    policy = BenchmarkPolicy()
    assert policy.initial_capital == Decimal("1000000")
    assert policy.maximum_positions == 3
    assert policy.position_size_percent == Decimal("10")
    assert policy.cash_reserve_percent == Decimal("70")
    assert policy.transaction_cost_percent == Decimal("0.20")
    assert policy.slippage_percent == Decimal("0.10")
    assert policy.maximum_sector_exposure_percent == Decimal("25")
    assert policy.maximum_single_name_exposure_percent == Decimal("10")


def test_invalid_research_parameters_fail_closed() -> None:
    with pytest.raises(ValueError, match="initial capital"):
        BenchmarkPolicy(initial_capital=Decimal("0"))
    with pytest.raises(ValueError, match="single-name cap"):
        BenchmarkPolicy(position_size_percent=Decimal("20"))


def test_manifest_cannot_enable_production(
    benchmark_report: BenchmarkReplayReport,
) -> None:
    manifest = benchmark_report.manifest
    with pytest.raises(ValueError, match="never influence production"):
        replace(manifest, production_influence=True)


def test_cli_contract_exposes_required_commands_and_options() -> None:
    runner = CliRunner()
    root = runner.invoke(benchmark_app, ["--help"], terminal_width=200)
    replay = runner.invoke(benchmark_app, ["replay", "--help"], terminal_width=200)
    assert root.exit_code == replay.exit_code == 0
    for command in ("replay", "report", "trades", "portfolio", "opportunity"):
        assert command in root.stdout
    for option in (
        "--start",
        "--end",
        "--capital",
        "--max-positions",
        "--transaction-cost",
        "--slippage",
        "--json",
        "--csv",
    ):
        assert option in replay.stdout
    assert BASELINE_ID == "ALPHA_BASELINE_v1.0"
    assert REPLAY_CLASSIFICATION == "OBSERVED_MARKET_REPLAY"
    assert PRODUCTION_INFLUENCE is False


def test_non_economic_equal_weight_benchmark_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "prices.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(
        """
        CREATE TABLE daily_prices (
            symbol VARCHAR,
            trade_date DATE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            sector VARCHAR,
            exchange VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ("TEST", date(2024, 1, 1), 1, 1, 1, 1, 100, None, "NSE"),
            (
                "TEST",
                date(2024, 1, 2),
                1e20,
                1e20,
                1e20,
                1e20,
                100,
                None,
                "NSE",
            ),
        ),
    )
    connection.close()

    with LegacyMarketDataStore(database) as store:
        result = observed_equal_weight_comparison(
            store,
            date(2024, 1, 1),
            date(2024, 1, 2),
            Decimal("1000000"),
        )

    assert result.availability.value == "UNAVAILABLE"
    assert result.ending_value is None
    assert "failed closed" in result.reason
