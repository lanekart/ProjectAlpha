from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Protocol, cast

import pandas as pd

from alpha.analysis.signals.daily_report import DailyMarketReport
from alpha.application.ingestion import IngestionService
from alpha.backtest.backtest_report import BacktestReport, BacktestReportBuilder
from alpha.backtest.engine import BacktestEngine
from alpha.backtest.models import BacktestOrder, BacktestResult
from alpha.backtest.performance import PerformanceAnalytics, PerformanceSummary
from alpha.backtest.performance_export import (
    PerformanceReport,
    PerformanceReportBuilder,
)
from alpha.backtest.strategy_statistics import (
    StrategyStatistics,
    StrategyStatisticsEngine,
)
from alpha.backtest.strategy_statistics_export import (
    StrategyStatisticsReport,
    StrategyStatisticsReportBuilder,
)
from alpha.data.downloader.bhavcopy import BhavcopyDownloader
from alpha.market.resolver import TradingDateResolver


class MarketReportGenerator(Protocol):
    def generate(self, df: pd.DataFrame) -> Any:
        """Generate a deterministic market report from normalized prices."""
        ...


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    """Stable application-facing summary for deterministic backtest runs."""

    strategy: str
    start: date
    end: date
    starting_cash: Decimal
    ending_cash: Decimal
    equity: Decimal
    processed_days: int
    order_count: int
    trade_count: int
    position_count: int
    positions: Mapping[str, int]
    result: BacktestResult
    performance: PerformanceSummary = field(init=False)
    performance_report: PerformanceReport = field(init=False)
    strategy_statistics: StrategyStatistics = field(init=False)
    strategy_statistics_report: StrategyStatisticsReport = field(init=False)
    report: BacktestReport = field(init=False)

    def __post_init__(self) -> None:
        normalized_strategy = self.strategy.strip().lower()
        if not normalized_strategy:
            raise ValueError("strategy cannot be empty")
        if self.end < self.start:
            raise ValueError("end date must be on or after start date")
        if self.starting_cash <= Decimal("0"):
            raise ValueError("starting cash must be greater than zero")
        if self.processed_days <= 0:
            raise ValueError("processed days must be positive")
        if self.order_count < 0:
            raise ValueError("order count cannot be negative")
        if self.trade_count < 0:
            raise ValueError("trade count cannot be negative")
        if self.position_count < 0:
            raise ValueError("position count cannot be negative")

        copied_positions: dict[str, int] = {}
        for symbol, quantity in self.positions.items():
            normalized_symbol = symbol.strip()
            if not normalized_symbol:
                raise ValueError("position symbol cannot be empty")
            copied_positions[normalized_symbol] = quantity

        if self.position_count != len(copied_positions):
            raise ValueError("position count must match positions")

        performance = PerformanceAnalytics().summarize(self.result)
        performance_report = PerformanceReportBuilder().build(performance)
        strategy_statistics = StrategyStatisticsEngine().summarize(
            performance,
            trade_pnls=self._trade_pnls(),
            observed_periods=self.processed_days,
        )
        strategy_statistics_report = StrategyStatisticsReportBuilder().build(
            strategy_statistics
        )
        report = BacktestReportBuilder().build(
            strategy=normalized_strategy,
            start=self.start.isoformat(),
            end=self.end.isoformat(),
            processed_days=self.processed_days,
            starting_cash=self.starting_cash,
            ending_cash=self.ending_cash,
            equity=self.equity,
            order_count=self.order_count,
            trade_count=self.trade_count,
            position_count=self.position_count,
            positions=copied_positions,
            performance=performance_report,
            strategy_statistics=strategy_statistics_report,
        )

        object.__setattr__(self, "strategy", normalized_strategy)
        object.__setattr__(self, "positions", MappingProxyType(copied_positions))
        object.__setattr__(self, "performance", performance)
        object.__setattr__(self, "performance_report", performance_report)
        object.__setattr__(self, "strategy_statistics", strategy_statistics)
        object.__setattr__(
            self,
            "strategy_statistics_report",
            strategy_statistics_report,
        )
        object.__setattr__(self, "report", report)

    @property
    def total_return(self) -> Decimal:
        return self.performance.total_return

    @property
    def cagr(self) -> Decimal:
        return self.performance.cagr

    @property
    def volatility(self) -> Decimal:
        return self.performance.volatility

    @property
    def sharpe_ratio(self) -> Decimal:
        return self.performance.sharpe_ratio

    @property
    def sortino_ratio(self) -> Decimal:
        return self.performance.sortino_ratio

    @property
    def calmar_ratio(self) -> Decimal:
        return self.performance.calmar_ratio

    @property
    def maximum_drawdown(self) -> Decimal:
        return self.performance.maximum_drawdown

    @property
    def win_rate(self) -> Decimal:
        return self.performance.win_rate

    @property
    def profit_factor(self) -> Decimal:
        return self.performance.profit_factor

    @property
    def average_win(self) -> Decimal:
        return self.performance.average_win

    @property
    def average_loss(self) -> Decimal:
        return self.performance.average_loss

    @property
    def expectancy(self) -> Decimal:
        return self.performance.expectancy

    @property
    def exposure(self) -> Decimal:
        return self.performance.exposure

    @property
    def ending_equity(self) -> Decimal:
        return self.performance.ending_equity

    @property
    def cash_balance(self) -> Decimal:
        return self.performance.cash_balance

    def _trade_pnls(self) -> tuple[Decimal, ...]:
        quantities: dict[str, int] = {}
        average_costs: dict[str, Decimal] = {}
        pnls: list[Decimal] = []

        for trade in self.result.trades:
            current_quantity = quantities.get(trade.symbol, 0)
            current_average_cost = average_costs.get(trade.symbol, Decimal("0"))

            if trade.quantity > 0:
                new_quantity = current_quantity + trade.quantity
                new_average_cost = (
                    (current_average_cost * Decimal(current_quantity)) + trade.notional
                ) / Decimal(new_quantity)
                quantities[trade.symbol] = new_quantity
                average_costs[trade.symbol] = new_average_cost
                continue

            sell_quantity = abs(trade.quantity)
            if current_quantity <= 0:
                continue

            closed_quantity = min(sell_quantity, current_quantity)
            pnl = (trade.price - current_average_cost) * Decimal(closed_quantity)
            pnls.append(pnl)

            remaining_quantity = current_quantity - closed_quantity
            if remaining_quantity > 0:
                quantities[trade.symbol] = remaining_quantity
                average_costs[trade.symbol] = current_average_cost
            else:
                quantities.pop(trade.symbol, None)
                average_costs.pop(trade.symbol, None)

        return tuple(pnls)


@dataclass(frozen=True, slots=True)
class BacktestRun:
    """Complete reusable backtest application result."""

    summary: BacktestSummary
    orders: tuple[BacktestOrder, ...]


@dataclass(slots=True)
class BacktestApplicationService:
    """Application service for deterministic backtest execution."""

    resolver: TradingDateResolver = field(default_factory=TradingDateResolver)
    downloader: BhavcopyDownloader = field(default_factory=BhavcopyDownloader)
    ingestion: IngestionService = field(default_factory=IngestionService)
    report: MarketReportGenerator = field(default_factory=DailyMarketReport)
    engine: BacktestEngine = field(default_factory=BacktestEngine)

    def run(
        self,
        *,
        strategy: str,
        start: date,
        end: date,
        starting_cash: Decimal,
    ) -> BacktestRun:
        normalized_strategy = strategy.strip().lower()
        if normalized_strategy != "momentum":
            raise ValueError(f"unsupported backtest strategy: {strategy}")
        if end < start:
            raise ValueError("end date must be on or after start date")
        if starting_cash <= Decimal("0"):
            raise ValueError("starting cash must be greater than zero")

        latest_frame, processed_days = self._load_market_data(start=start, end=end)
        report_data = self.report.generate(latest_frame)
        signal_frame = cast(pd.DataFrame, report_data["signals"])

        prices = self._prices_from_frame(latest_frame)
        orders = self._momentum_orders(signal_frame=signal_frame, prices=prices)
        result = self.engine.run(
            starting_cash=starting_cash,
            orders=orders,
            prices=prices,
        )

        summary = BacktestSummary(
            strategy=normalized_strategy,
            start=start,
            end=end,
            starting_cash=starting_cash,
            ending_cash=result.ending_cash,
            equity=result.equity,
            processed_days=processed_days,
            order_count=len(orders),
            trade_count=result.trade_count,
            position_count=len(result.positions),
            positions=result.positions,
            result=result,
        )

        return BacktestRun(summary=summary, orders=orders)

    def _load_market_data(self, *, start: date, end: date) -> tuple[pd.DataFrame, int]:
        latest_frame: pd.DataFrame | None = None
        processed_days = 0
        current = start

        while current <= end:
            trading_day = self.resolver.resolve(current)
            archive = self.downloader.download(trading_day)
            frame = self.ingestion.ingest(archive)

            if frame.empty:
                frame = self.ingestion.load_prices_for_trade_date(trading_day)

            if not frame.empty:
                latest_frame = frame

            processed_days += 1
            current += timedelta(days=1)

        if latest_frame is None:
            raise ValueError("no market data available for backtest range")

        return latest_frame, processed_days

    def _prices_from_frame(self, frame: pd.DataFrame) -> dict[str, Decimal]:
        required_columns = {"symbol", "close"}
        missing_columns = required_columns.difference(frame.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"market data missing required columns: {missing}")

        prices: dict[str, Decimal] = {}
        records = cast(
            list[dict[str, Any]],
            frame[["symbol", "close"]].to_dict("records"),
        )
        for record in records:
            symbol = str(record["symbol"]).strip()
            if not symbol:
                continue
            prices[symbol] = Decimal(str(record["close"]))

        if not prices:
            raise ValueError("no close prices available for backtest")

        return prices

    def _momentum_orders(
        self,
        *,
        signal_frame: pd.DataFrame,
        prices: dict[str, Decimal],
    ) -> tuple[BacktestOrder, ...]:
        required_columns = {"symbol", "signal"}
        missing_columns = required_columns.difference(signal_frame.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"signals missing required columns: {missing}")

        records = cast(
            list[dict[str, Any]],
            signal_frame[["symbol", "signal"]].to_dict("records"),
        )
        orders: list[BacktestOrder] = []
        for record in records:
            symbol = str(record["symbol"]).strip()
            signal = str(record["signal"]).strip().upper()
            if signal == "BUY" and symbol in prices:
                orders.append(BacktestOrder(symbol=symbol, quantity=1))

        return tuple(orders)


@dataclass(slots=True)
class CliBacktestService:
    """Backward-compatible RC-005A CLI backtest service adapter."""

    resolver: TradingDateResolver = field(default_factory=TradingDateResolver)
    downloader: BhavcopyDownloader = field(default_factory=BhavcopyDownloader)
    ingestion: IngestionService = field(default_factory=IngestionService)
    report: MarketReportGenerator = field(default_factory=DailyMarketReport)
    engine: BacktestEngine = field(default_factory=BacktestEngine)

    def run(
        self,
        *,
        strategy: str,
        start: date,
        end: date,
        starting_cash: Decimal,
    ) -> BacktestSummary:
        service = BacktestApplicationService(
            resolver=self.resolver,
            downloader=self.downloader,
            ingestion=self.ingestion,
            report=self.report,
            engine=self.engine,
        )
        return service.run(
            strategy=strategy,
            start=start,
            end=end,
            starting_cash=starting_cash,
        ).summary


CliBacktestResult = BacktestSummary
