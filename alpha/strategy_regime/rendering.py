from __future__ import annotations

from decimal import Decimal

from alpha.strategy_regime.models import (
    IndicatorCombinationResult,
    MarketRegime,
    StrategyRegimeBacktestRun,
)


def render_backtest_run(
    run: StrategyRegimeBacktestRun,
    *,
    top: int = 10,
) -> tuple[str, ...]:
    lines = [
        "Strategy-Regime Backtest",
        f"Run ID: {run.run_id}",
        f"Date Range: {run.from_date.isoformat()} to {run.to_date.isoformat()}",
        f"Strategies Evaluated: {len(run.results)}",
        "",
        "Top Ranked Setups:",
    ]
    if not run.ranks:
        lines.append("- none")
    for rank in run.ranks[:top]:
        lines.append(
            f"{rank.rank}. {rank.strategy_name} / {rank.regime.value} / "
            f"{rank.holding_period.value}: EV={_metric(rank.expected_value_pct)}%, "
            f"PF={_metric(rank.profit_factor)}, "
            f"Evidence={rank.sample_size_confidence.value}"
        )
    return tuple(lines)


def render_strategy_regime_report(
    run: StrategyRegimeBacktestRun | None,
    *,
    top: int = 10,
) -> tuple[str, ...]:
    if run is None:
        return (
            "Strategy-Regime Report",
            "No strategy-regime backtest results are stored yet.",
            "Run `poetry run python -m alpha strategy-regime backtest` first.",
        )
    lines = [
        "Strategy-Regime Report",
        f"Latest Run: {run.run_id}",
        f"Date Range: {run.from_date.isoformat()} to {run.to_date.isoformat()}",
    ]
    for summary in run.summaries:
        lines.extend(_summary_lines(summary.regime, summary.best_strategies[:top]))
        lines.append("Avoid:")
        if summary.avoid_strategies:
            lines.extend(f"- {name}" for name in summary.avoid_strategies)
        else:
            lines.append("- none")
        lines.append("")
    lines.append("Best Indicator Combinations:")
    for rank in run.ranks[:top]:
        lines.append(
            f"- {rank.strategy_name} in {rank.regime.value}: "
            f"EV={_metric(rank.expected_value_pct)}%, "
            f"holding={rank.holding_period.value}, "
            f"evidence={rank.sample_size_confidence.value}"
        )
    lines.append("Sample-size warnings are shown as INSUFFICIENT_SAMPLE.")
    return tuple(lines)


def _summary_lines(
    regime: MarketRegime,
    strategies: tuple[IndicatorCombinationResult, ...],
) -> list[str]:
    lines = ["", f"Market Regime: {regime.value}", "Top Historical Setups:"]
    if not strategies:
        lines.append("- none")
        return lines
    for index, strategy in enumerate(strategies, start=1):
        lines.extend(
            (
                f"{index}. {_title(strategy.strategy_name)}",
                f"   Trades: {strategy.total_trades}",
                f"   Win Rate: {_percent(strategy.win_rate)}",
                f"   EV: {_signed(strategy.expected_value_pct)}%",
                f"   Profit Factor: {_metric(strategy.profit_factor)}",
                f"   Best Holding Period: {strategy.best_holding_period.value}",
                f"   Evidence: {strategy.sample_size_confidence.value}",
            )
        )
    return lines


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _percent(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{(value * Decimal('100')).quantize(Decimal('0.01'))}%"


def _signed(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    prefix = "+" if value > Decimal("0") else ""
    return f"{prefix}{value}"


def _title(value: str) -> str:
    return value.replace("-", " ").replace("+", "+").title()


__all__ = ["render_backtest_run", "render_strategy_regime_report"]
