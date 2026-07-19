from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
from typer.testing import CliRunner

from alpha.cli import app
from alpha.historical_replay import (
    HistoricalDataCoverageAnalyzer,
    render_data_coverage_report,
)


class FakeCoverageRepository:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        del start_date, end_date
        return self.frame[self.frame["symbol"].str.upper().isin(symbols)].copy()


def test_coverage_analyzer_marks_full_and_partial_history() -> None:
    as_of = date(2026, 7, 10)
    frame = pd.concat(
        [
            _bars("FULL", as_of=as_of, count=2520),
            _bars("PARTIAL", as_of=as_of, count=700),
        ],
        ignore_index=True,
    )

    report = HistoricalDataCoverageAnalyzer(
        price_repository=FakeCoverageRepository(frame),
    ).analyze(symbols=("FULL", "PARTIAL", "MISSING"), as_of=as_of, years=10)

    by_symbol = {item.symbol: item for item in report.symbols}
    assert by_symbol["FULL"].quality == "FULL"
    assert by_symbol["FULL"].coverage_ratio == Decimal("1.0000")
    assert by_symbol["PARTIAL"].quality == "LISTED_HISTORY_LIMITED"
    assert by_symbol["MISSING"].quality == "MISSING"


def test_coverage_report_rendering_explains_data_depth() -> None:
    as_of = date(2026, 7, 10)
    report = HistoricalDataCoverageAnalyzer(
        price_repository=FakeCoverageRepository(_bars("AAA", as_of=as_of, count=100)),
    ).analyze(symbols=("AAA",), as_of=as_of, years=10)

    output = "\n".join(render_data_coverage_report(report))

    assert "Historical Data Coverage" in output
    assert "AAA: 100/2520 bars" in output
    assert "LISTED_HISTORY_LIMITED" in output


def test_replay_coverage_cli_output(monkeypatch) -> None:
    as_of = date(2026, 7, 10)

    monkeypatch.setattr(
        "alpha.cli.MarketTruthPriceRepository",
        lambda: FakeCoverageRepository(_bars("AAA", as_of=as_of, count=2520)),
    )

    result = CliRunner().invoke(
        app,
        ["replay", "coverage", "--symbol", "AAA", "--as-of", "2026-07-10"],
    )

    assert result.exit_code == 0
    assert "Historical Data Coverage" in result.stdout
    assert "AAA: 2520/2520 bars" in result.stdout


def _bars(symbol: str, *, as_of: date, count: int) -> pd.DataFrame:
    start = as_of - timedelta(days=count)
    return pd.DataFrame(
        {
            "symbol": [symbol] * count,
            "trade_date": [start + timedelta(days=index) for index in range(count)],
            "open": [100] * count,
            "high": [101] * count,
            "low": [99] * count,
            "close": [100] * count,
            "volume": [1000] * count,
            "sector": [None] * count,
            "exchange": ["NSE"] * count,
        }
    )
