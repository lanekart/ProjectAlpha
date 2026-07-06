from __future__ import annotations

from dataclasses import dataclass

from alpha.execution.execution_engine import ExecutionEngine
from alpha.execution.order_book import OrderBook
from alpha.market.features.feature_engine import FeatureEngine
from alpha.market.signals.signal_engine import SignalEngine
from alpha.portfolio.decision_engine import DecisionEngine
from alpha.portfolio.execution_bridge import ExecutionBridge
from alpha.portfolio.portfolio_engine import PortfolioEngine


@dataclass(slots=True)
class BacktestResult:
    """
    Final output of a backtest run.
    """

    final_portfolio: object
    executions: list[object]


@dataclass(slots=True)
class BacktestOrchestrator:
    """
    Full deterministic trading system simulator.

    Now includes portfolio state evolution.
    """

    feature_engine: FeatureEngine
    signal_engine: SignalEngine
    decision_engine: DecisionEngine
    execution_bridge: ExecutionBridge

    execution_engine: ExecutionEngine
    order_book: OrderBook

    portfolio_engine: PortfolioEngine

    def run(self, series, symbol: str) -> BacktestResult:
        all_fills: list[object] = []

        # IMPORTANT: portfolio is now live state
        portfolio = self.portfolio_engine

        features = self.feature_engine.build(series)
        signals = self.signal_engine.generate(features)
        intents = self.decision_engine.generate(signals, symbol)
        orders = self.execution_bridge.translate(intents)

        for order in orders:
            self.order_book.register(order)

            result = self.execution_engine.execute(order)

            # CRITICAL: apply every fill immediately
            for fill in result.fills:
                portfolio.apply_fill(fill)
                all_fills.append(fill)

        return BacktestResult(
            final_portfolio=portfolio,
            executions=all_fills,
        )
