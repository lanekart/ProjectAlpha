from __future__ import annotations

from datetime import date
from decimal import Decimal

from typer.testing import CliRunner

from alpha.cli import app
from alpha.strategy_regime import (
    HoldingPeriod,
    MarketRegime,
    SampleConfidence,
    StrategyRegimeBacktestEngine,
    StrategyRegimeBacktestRepository,
    StrategySignalObservation,
    historical_edge_metadata,
    recommendation_historical_edge_metadata,
    render_strategy_regime_report,
)


def test_regime_specific_performance_grouping() -> None:
    run = _run(minimum_sample_size=1)

    regimes = {result.regime for result in run.results}

    assert MarketRegime.BULLISH in regimes
    assert MarketRegime.BEARISH in regimes


def test_individual_indicator_backtest() -> None:
    run = _run(minimum_sample_size=1, strategies=("breakout",))
    result = next(item for item in run.results if item.strategy_name == "breakout")

    assert result.best_holding_period is not None
    assert result.best_holding_period.total_trades == 4


def test_indicator_combination_backtest() -> None:
    run = _run(minimum_sample_size=1)

    combination = next(
        item
        for item in run.results
        if item.strategy_name == "breakout + relative-strength"
        and item.regime is MarketRegime.BULLISH
    )

    assert combination.best_holding_period is not None
    assert combination.best_holding_period.total_trades == 3


def test_ev_calculation() -> None:
    run = _run(minimum_sample_size=1, strategies=("breakout",))
    result = next(item for item in run.results if item.strategy_name == "breakout")
    performance = next(
        item
        for item in result.holding_period_results
        if item.holding_period is HoldingPeriod.NEXT_DAY
    )

    assert performance.expected_value_pct == Decimal("-0.25")


def test_profit_factor_calculation() -> None:
    run = _run(minimum_sample_size=1, strategies=("breakout",))
    result = next(item for item in run.results if item.strategy_name == "breakout")
    performance = next(
        item
        for item in result.holding_period_results
        if item.holding_period is HoldingPeriod.NEXT_DAY
    )

    assert performance.profit_factor == Decimal("0.9231")


def test_sample_size_confidence_labels() -> None:
    run = _run(minimum_sample_size=3, strategies=("breakout",))
    result = next(item for item in run.results if item.strategy_name == "breakout")

    assert result.best_holding_period is not None
    assert (
        result.best_holding_period.sample_size_confidence
        is SampleConfidence.WEAK_EVIDENCE
    )


def test_holding_period_comparison() -> None:
    run = _run(minimum_sample_size=1, strategies=("breakout",))
    result = next(item for item in run.results if item.strategy_name == "breakout")

    assert result.best_holding_period is not None
    assert result.best_holding_period.holding_period is HoldingPeriod.THREE_DAYS


def test_conservative_same_candle_stop_target_handling() -> None:
    run = StrategyRegimeBacktestEngine().run(
        observations=(
            _observation(
                "AAA",
                indicators=("breakout",),
                holding_close={"1d": Decimal("110")},
                path_high={"1d": Decimal("115")},
                path_low={"1d": Decimal("94")},
                stop=Decimal("95"),
                target=Decimal("112"),
            ),
        ),
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 31),
        strategies=("breakout",),
        holding_periods=(HoldingPeriod.NEXT_DAY,),
        minimum_sample_size=1,
    )
    performance = run.results[0].holding_period_results[0]

    assert performance.losing_trades == 1
    assert performance.expected_value_pct == Decimal("-5.00")


def test_report_ranks_by_ev_not_win_rate_only() -> None:
    run = _run(minimum_sample_size=1)

    assert run.ranks[0].strategy_name == "breakout + relative-strength"


def test_insufficient_sample_warning() -> None:
    run = _run(minimum_sample_size=30, strategies=("breakout",))
    output = "\n".join(render_strategy_regime_report(run))

    assert "INSUFFICIENT_SAMPLE" in output


def test_recommendation_edge_hook_uses_stored_results(tmp_path, monkeypatch) -> None:
    repository = StrategyRegimeBacktestRepository(tmp_path / "edges.json")
    run = _run(minimum_sample_size=1)
    repository.save_run(run)
    monkeypatch.setenv("ALPHA_STRATEGY_REGIME_BACKTESTS", str(tmp_path / "edges.json"))

    metadata = recommendation_historical_edge_metadata(
        setup_name="breakout relative strength",
        market_regime="BULLISH",
    )

    assert metadata["historical_setup_edge"] == "computed"
    assert metadata["historical_setup_best_holding_period"] == "3d"


def test_historical_edge_metadata_insufficient_data() -> None:
    metadata = historical_edge_metadata(
        setup_indicators=("breakout",),
        regime="BULLISH",
        run=_run(minimum_sample_size=30),
    )

    assert metadata["historical_setup_edge"] == "Not yet computed"


def test_cli_backtest_command_works(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHA_STRATEGY_REGIME_BACKTESTS", str(tmp_path / "edges.json"))
    result = CliRunner().invoke(
        app,
        [
            "strategy-regime",
            "backtest",
            "--from-date",
            "2026-01-01",
            "--to-date",
            "2026-01-31",
            "--min-sample-size",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "Strategy-Regime Backtest" in result.stdout


def test_cli_report_command_works(tmp_path, monkeypatch) -> None:
    repository = StrategyRegimeBacktestRepository(tmp_path / "edges.json")
    repository.save_run(_run(minimum_sample_size=1))
    monkeypatch.setenv("ALPHA_STRATEGY_REGIME_BACKTESTS", str(tmp_path / "edges.json"))

    result = CliRunner().invoke(app, ["strategy-regime", "report"])

    assert result.exit_code == 0
    assert "Strategy-Regime Report" in result.stdout
    assert "Best Indicator Combinations" in result.stdout


def _run(
    *,
    minimum_sample_size: int,
    strategies: tuple[str, ...] | None = None,
):
    return StrategyRegimeBacktestEngine().run(
        observations=_observations(),
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 31),
        regimes=(MarketRegime.BULLISH, MarketRegime.BEARISH),
        strategies=strategies,
        holding_periods=(HoldingPeriod.NEXT_DAY, HoldingPeriod.THREE_DAYS),
        minimum_sample_size=minimum_sample_size,
    )


def _observations() -> tuple[StrategySignalObservation, ...]:
    return (
        _observation(
            "AAA",
            indicators=("breakout", "relative-strength"),
            holding_close={"1d": Decimal("106"), "3d": Decimal("112")},
        ),
        _observation(
            "BBB",
            indicators=("breakout", "relative-strength"),
            holding_close={"1d": Decimal("106"), "3d": Decimal("111")},
        ),
        _observation(
            "CCC",
            indicators=("breakout", "relative-strength"),
            holding_close={"1d": Decimal("94"), "3d": Decimal("105")},
        ),
        _observation(
            "DDD",
            indicators=("breakout",),
            holding_close={"1d": Decimal("93"), "3d": Decimal("95")},
        ),
        _observation(
            "EEE",
            regime=MarketRegime.BEARISH,
            indicators=("mean-reversion",),
            holding_close={"1d": Decimal("97"), "3d": Decimal("96")},
        ),
    )


def _observation(
    symbol: str,
    *,
    regime: MarketRegime = MarketRegime.BULLISH,
    indicators: tuple[str, ...],
    holding_close: dict[str, Decimal],
    path_high: dict[str, Decimal] | None = None,
    path_low: dict[str, Decimal] | None = None,
    stop: Decimal | None = None,
    target: Decimal | None = None,
) -> StrategySignalObservation:
    return StrategySignalObservation(
        symbol=symbol,
        observed_on=date(2026, 1, 2),
        regime=regime,
        indicators=indicators,
        entry_open=Decimal("100"),
        holding_close=holding_close,
        path_high=path_high or holding_close,
        path_low=path_low or holding_close,
        stop_loss=stop,
        target_price=target,
        sector="IT",
        capital=Decimal("100000"),
    )
