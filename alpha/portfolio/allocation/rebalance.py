from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from alpha.portfolio.allocation.target import PortfolioAllocation
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot


@dataclass(frozen=True, slots=True)
class RebalanceOrder:
    """
    Immutable rebalance instruction for one symbol.
    """

    symbol: str
    target_weight: Decimal
    current_quantity: int
    target_quantity: int
    delta_quantity: int
    price: Decimal

    @property
    def is_buy(self) -> bool:
        return self.delta_quantity > 0

    @property
    def is_sell(self) -> bool:
        return self.delta_quantity < 0

    @property
    def is_noop(self) -> bool:
        return self.delta_quantity == 0

    @property
    def notional(self) -> Decimal:
        return abs(Decimal(self.delta_quantity)) * self.price


@dataclass(frozen=True, slots=True)
class RebalancePlan:
    """
    Immutable collection of rebalance orders.
    """

    orders: tuple[RebalanceOrder, ...]

    @property
    def buy_orders(self) -> tuple[RebalanceOrder, ...]:
        return tuple(order for order in self.orders if order.is_buy)

    @property
    def sell_orders(self) -> tuple[RebalanceOrder, ...]:
        return tuple(order for order in self.orders if order.is_sell)

    @property
    def noop_orders(self) -> tuple[RebalanceOrder, ...]:
        return tuple(order for order in self.orders if order.is_noop)

    @property
    def total_buy_notional(self) -> Decimal:
        return sum(
            (order.notional for order in self.buy_orders),
            Decimal("0"),
        )

    @property
    def total_sell_notional(self) -> Decimal:
        return sum(
            (order.notional for order in self.sell_orders),
            Decimal("0"),
        )


@dataclass(frozen=True, slots=True)
class RebalancePlanner:
    """
    Converts target allocation weights into concrete rebalance orders.
    """

    def plan(
        self,
        snapshot: PortfolioSnapshot,
        allocation: PortfolioAllocation,
        prices: dict[str, Decimal],
    ) -> RebalancePlan:
        orders: list[RebalanceOrder] = []

        current_quantities = {
            position.symbol: position.quantity for position in snapshot.positions
        }

        for target in allocation.targets:
            price = prices.get(target.symbol)

            if price is None:
                raise ValueError(
                    f"Missing price for allocation target: {target.symbol}"
                )

            if price <= Decimal("0"):
                raise ValueError(
                    f"Invalid price for allocation target: {target.symbol}"
                )

            current_quantity = current_quantities.get(target.symbol, 0)

            target_notional = snapshot.total_equity * target.weight
            target_quantity = int(
                (target_notional / price).to_integral_value(
                    rounding=ROUND_FLOOR,
                )
            )

            orders.append(
                RebalanceOrder(
                    symbol=target.symbol,
                    target_weight=target.weight,
                    current_quantity=current_quantity,
                    target_quantity=target_quantity,
                    delta_quantity=target_quantity - current_quantity,
                    price=price,
                )
            )

        return RebalancePlan(orders=tuple(orders))
