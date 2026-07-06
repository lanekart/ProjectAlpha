from __future__ import annotations

from dataclasses import dataclass

from alpha.backtest.models import BacktestOrder
from alpha.portfolio.allocation.rebalance import RebalancePlan


@dataclass(frozen=True, slots=True)
class RebalanceExecutionAdapter:
    """
    Converts a rebalance plan into executable backtest orders.

    This keeps the backtest engine order-driven and independent from allocation,
    optimization, and portfolio construction concerns.
    """

    include_noop_orders: bool = False

    def to_orders(self, plan: RebalancePlan) -> tuple[BacktestOrder, ...]:
        orders: list[BacktestOrder] = []

        for rebalance_order in plan.orders:
            if rebalance_order.is_noop and not self.include_noop_orders:
                continue

            orders.append(
                BacktestOrder(
                    symbol=rebalance_order.symbol,
                    quantity=rebalance_order.delta_quantity,
                )
            )

        return tuple(orders)
