"""Transaction cost objective."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any

from alpha.costs import CostInput, TransactionCostEstimator
from alpha.optimization.objective_result import ObjectiveResult
from alpha.portfolio.optimizer import OptimizationInput


@dataclass(frozen=True, slots=True)
class TransactionCostObjective:
    """Objective that scores estimated transaction costs as portfolio weight."""

    cost_estimator: TransactionCostEstimator = field(
        default_factory=TransactionCostEstimator
    )
    min_trade_weight: Decimal = Decimal("0")
    name: str = "transaction_cost"

    def __post_init__(self) -> None:
        if self.min_trade_weight < Decimal("0"):
            raise ValueError("min_trade_weight cannot be negative")

    def evaluate(
        self,
        optimization_input: OptimizationInput,
        target_weights: Mapping[str, Decimal],
    ) -> ObjectiveResult:
        portfolio_value = self._portfolio_value(optimization_input.metadata)
        if portfolio_value <= Decimal("0"):
            return ObjectiveResult(
                name=self.name,
                score=Decimal("0"),
                components={"transaction_cost": Decimal("0")},
            )

        prices = self._prices(optimization_input.metadata)
        total_cost = Decimal("0")

        symbols = set(optimization_input.current_weights) | set(target_weights)
        for symbol in symbols:
            current_weight = optimization_input.current_weights.get(
                symbol,
                Decimal("0"),
            )
            target_weight = target_weights.get(symbol, Decimal("0"))
            weight_delta = target_weight - current_weight

            if abs(weight_delta) <= self.min_trade_weight:
                continue

            price = prices.get(symbol)
            if price is None:
                raise ValueError(f"missing price for {symbol}")

            quantity = self._quantity_from_weight_delta(
                weight_delta=weight_delta,
                price=price,
                portfolio_value=portfolio_value,
            )
            if quantity == 0:
                continue

            total_cost += self.cost_estimator.estimate(
                CostInput(symbol=symbol, quantity=quantity, price=price)
            ).total

        cost_weight = total_cost / portfolio_value

        return ObjectiveResult(
            name=self.name,
            score=cost_weight,
            components={
                "transaction_cost": total_cost,
                "transaction_cost_weight": cost_weight,
            },
        )

    def _portfolio_value(self, metadata: Mapping[str, Any]) -> Decimal:
        raw_value = metadata.get("portfolio_value", Decimal("0"))
        value = self._decimal(raw_value)
        if value < Decimal("0"):
            raise ValueError("portfolio_value cannot be negative")
        return value

    def _prices(self, metadata: Mapping[str, Any]) -> Mapping[str, Decimal]:
        raw_prices = metadata.get("prices", {})
        if not isinstance(raw_prices, Mapping):
            raise TypeError("metadata prices must be a mapping")

        prices = {symbol: self._decimal(price) for symbol, price in raw_prices.items()}
        for symbol, price in prices.items():
            if not symbol:
                raise ValueError("price symbol cannot be empty")
            if price <= Decimal("0"):
                raise ValueError(f"price for {symbol} must be positive")

        return prices

    def _quantity_from_weight_delta(
        self,
        *,
        weight_delta: Decimal,
        price: Decimal,
        portfolio_value: Decimal,
    ) -> int:
        signed_notional = weight_delta * portfolio_value
        signed_quantity = (signed_notional / price).to_integral_value(
            rounding=ROUND_DOWN
        )
        return int(signed_quantity)

    def _decimal(self, value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int | str):
            return Decimal(value)
        raise TypeError("numeric metadata must be Decimal, int, or str")
