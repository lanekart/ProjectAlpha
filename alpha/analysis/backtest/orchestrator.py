from __future__ import annotations

from dataclasses import dataclass

from alpha.analysis.execution.engine import ExecutionAnalyticsEngine
from alpha.analysis.execution.report import ExecutionAnalyticsReport
from alpha.analysis.performance.engine import PerformanceEngine
from alpha.analysis.performance.report import PerformanceReport
from alpha.analysis.portfolio.engine import PortfolioAnalyticsEngine
from alpha.analysis.portfolio.report import PortfolioAnalyticsReport
from alpha.execution.execution_engine import ExecutionEngine
from alpha.execution.fill import Fill
from alpha.execution.order_book import OrderBook
from alpha.market.bar_series import BarSeries
from alpha.market.features.feature_engine import FeatureEngine
from alpha.market.signals.signal_engine import SignalEngine
from alpha.portfolio.decision_engine import DecisionEngine
from alpha.portfolio.equity_curve import EquityCurve
from alpha.portfolio.execution_bridge import ExecutionBridge
from alpha.portfolio.portfolio_engine import PortfolioEngine
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """
    Final immutable output of a deterministic backtest run.
    """

    final_snapshot: PortfolioSnapshot
    snapshots: tuple[PortfolioSnapshot, ...]
    equity_curve: EquityCurve
    performance: PerformanceReport
    execution_analytics: ExecutionAnalyticsReport
    portfolio_analytics: PortfolioAnalyticsReport
    executions: tuple[Fill, ...]


@dataclass(slots=True)
class BacktestOrchestrator:
    """
    Full deterministic trading system simulator.
    """

    feature_engine: FeatureEngine
    signal_engine: SignalEngine
    decision_engine: DecisionEngine
    execution_bridge: ExecutionBridge

    execution_engine: ExecutionEngine
    order_book: OrderBook

    portfolio_engine: PortfolioEngine
    performance_engine: PerformanceEngine = PerformanceEngine()
    execution_analytics_engine: ExecutionAnalyticsEngine = ExecutionAnalyticsEngine()
    portfolio_analytics_engine: PortfolioAnalyticsEngine = PortfolioAnalyticsEngine()

    def run(self, series: BarSeries, symbol: str) -> BacktestResult:
        all_fills: list[Fill] = []
        snapshots: list[PortfolioSnapshot] = []

        features = self.feature_engine.build(series)
        signals = self.signal_engine.generate(features)
        intents = self.decision_engine.generate(signals, symbol)
        orders = self.execution_bridge.translate(intents)

        for order in orders:
            result = self.execution_engine.submit(order)

            for fill in result.fills:
                self.portfolio_engine.apply_fill(fill)
                all_fills.append(fill)
                snapshots.append(self.portfolio_engine.create_snapshot())

        if snapshots:
            final_snapshot = snapshots[-1]
        else:
            final_snapshot = self.portfolio_engine.create_snapshot()
            snapshots.append(final_snapshot)

        snapshot_history = tuple(snapshots)
        equity_curve = EquityCurve.from_snapshots(snapshot_history)
        executions = tuple(all_fills)

        return BacktestResult(
            final_snapshot=final_snapshot,
            snapshots=snapshot_history,
            equity_curve=equity_curve,
            performance=self.performance_engine.analyze(equity_curve),
            execution_analytics=self.execution_analytics_engine.analyze(executions),
            portfolio_analytics=self.portfolio_analytics_engine.analyze(
                final_snapshot,
            ),
            executions=executions,
        )
