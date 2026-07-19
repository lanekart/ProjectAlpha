from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pandas as pd
from typer.testing import CliRunner

from alpha.cli import app
from alpha.market_intelligence import (
    BenchmarkAlignment,
    BenchmarkFeatureCompleteness,
    BenchmarkStateBuilder,
    MarketStateFallbackReason,
    MarketStateSnapshot,
    MarketStateSnapshotRepository,
    canonical_benchmark_configuration,
)
from tests.market_intelligence.test_market_state_snapshots import _market_report


def test_canonical_benchmark_resolution_and_override() -> None:
    default = canonical_benchmark_configuration()
    override = canonical_benchmark_configuration(provider_symbol="TESTETF")

    assert default.provider_symbol == "NIFTYBEES"
    assert default.instrument_identifier == "NSE_EQ|NIFTYBEES"
    assert default.asset_type == "ETF"
    assert override.provider_symbol == "TESTETF"


def test_benchmark_feature_builder_calculates_returns_dma_atr_and_volatility() -> None:
    config = canonical_benchmark_configuration(provider_symbol="TESTETF")
    state = BenchmarkStateBuilder(configuration=config).build(
        bars=_benchmark_frame(days=220, symbol="TESTETF"),
        decision_as_of=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
    )

    assert state.benchmark_close == Decimal("319")
    assert state.benchmark_return_1d == Decimal("0.0031")
    assert state.benchmark_return_5d == Decimal("0.0159")
    assert state.benchmark_return_20d == Decimal("0.0669")
    assert state.benchmark_dma_20 == Decimal("309.5000")
    assert state.benchmark_dma_50 == Decimal("294.5000")
    assert state.benchmark_dma_200 == Decimal("219.5000")
    assert state.benchmark_distance_20dma == Decimal("0.0307")
    assert state.benchmark_atr_14 == Decimal("3.0000")
    assert state.benchmark_volatility is not None
    assert state.completeness is BenchmarkFeatureCompleteness.COMPLETE


def test_benchmark_builder_excludes_future_bars_and_marks_previous_session() -> None:
    config = canonical_benchmark_configuration(provider_symbol="TESTETF")
    frame = _benchmark_frame(days=222, symbol="TESTETF")
    state = BenchmarkStateBuilder(configuration=config).build(
        bars=frame,
        decision_as_of=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
    )

    assert state.benchmark_close == Decimal("319")
    assert state.latest_bar_timestamp == datetime(2026, 1, 2, tzinfo=UTC)
    assert state.alignment is BenchmarkAlignment.SAME_TRADING_DAY

    previous = BenchmarkStateBuilder(configuration=config).build(
        bars=frame,
        decision_as_of=datetime(2026, 1, 3, 9, 0, tzinfo=UTC),
    )
    assert previous.alignment is BenchmarkAlignment.PREVIOUS_COMPLETED_SESSION


def test_benchmark_feature_builder_reports_insufficient_lookback() -> None:
    config = canonical_benchmark_configuration(provider_symbol="TESTETF")
    state = BenchmarkStateBuilder(configuration=config).build(
        bars=_benchmark_frame(days=40, symbol="TESTETF"),
        decision_as_of=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
    )

    assert state.benchmark_dma_200 is None
    assert state.completeness is BenchmarkFeatureCompleteness.INSUFFICIENT
    assert "benchmark_dma_200" in state.missing_fields


def test_snapshot_persists_benchmark_state_and_genuine_neutral() -> None:
    config = canonical_benchmark_configuration(provider_symbol="TESTETF")
    state = BenchmarkStateBuilder(configuration=config).build(
        bars=_benchmark_frame(days=220, symbol="TESTETF"),
        decision_as_of=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
    )
    snapshot = MarketStateSnapshot.from_market_report(
        _market_report(),
        as_of_timestamp=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
        created_at=datetime(2026, 1, 2, 18, 1, tzinfo=UTC),
        benchmark_state=state,
    )

    assert snapshot.benchmark_symbol == "TESTETF"
    assert snapshot.benchmark_close == Decimal("319")
    assert snapshot.benchmark_dma_200 == Decimal("219.5000")
    assert snapshot.benchmark_alignment == "SAME_TRADING_DAY"
    assert snapshot.fallback_reason is MarketStateFallbackReason.NONE
    assert snapshot.fallback_applied is False


def test_benchmark_cli_outputs_and_exports(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "snapshots.json"
    monkeypatch.setenv("ALPHA_MARKET_STATE_SNAPSHOT_LEDGER", str(snapshot_path))
    snapshot = MarketStateSnapshot.from_market_report(
        _market_report(),
        as_of_timestamp=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
        created_at=datetime(2026, 1, 2, 18, 1, tzinfo=UTC),
    )
    MarketStateSnapshotRepository(snapshot_path).save(snapshot)

    benchmark = CliRunner().invoke(app, ["market-state", "benchmark"])
    completeness = CliRunner().invoke(app, ["market-state", "completeness"])

    assert benchmark.exit_code == 0
    assert "Provider Symbol: NIFTYBEES" in benchmark.output
    assert completeness.exit_code == 0
    assert "Market-State Snapshot Completeness" in completeness.output


def _benchmark_frame(*, days: int, symbol: str) -> pd.DataFrame:
    start = date(2025, 3, 3)
    rows = []
    current = start
    index = 0
    while len(rows) < days:
        if current.weekday() < 5:
            close = Decimal("100") + Decimal(index)
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": current,
                    "open": close - Decimal("1"),
                    "high": close + Decimal("1"),
                    "low": close - Decimal("2"),
                    "close": close,
                    "volume": 1000 + index,
                    "exchange": "NSE",
                }
            )
            index += 1
        current += timedelta(days=1)
    return pd.DataFrame(rows)
