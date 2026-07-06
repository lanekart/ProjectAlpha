"""Cost-aware optimizer decorator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from types import MappingProxyType
from typing import Any

from alpha.costs import CostBreakdown, CostInput, TransactionCostEstimator
from alpha.portfolio.optimization_result import OptimizationResult
from alpha.portfolio.optimizer import OptimizationInput, Optimizer


@dataclass(frozen=True, slots=True)
class EstimatedTradeCost:
    """Immutable cost estimate for one optimization-level rebalance trade."""

    symbol: str
    quantity: int
    price: Decimal
    weight_delta: Decimal
    breakdown: CostBreakdown

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol cannot be empty")
        if self.quantity == 0:
            raise ValueError("quantity cannot be zero")
        if self.price <= Decimal("0"):
            raise ValueError("price must be positive")

    @property
    def total_cost(self) -> Decimal:
        """Return total estimated cost for this trade."""

        return self.breakdown.total


@dataclass(frozen=True, slots=True)
class CostAwareOptimizer(Optimizer):
    """Optimizer decorator that penalizes costly target-weight changes."""

    base_optimizer: Optimizer
    cost_estimator: TransactionCostEstimator = field(
        default_factory=TransactionCostEstimator
    )
    cost_aversion: Decimal = Decimal("1")
    min_trade_weight: Decimal = Decimal("0")
    name: str = "cost_aware"

    def __post_init__(self) -> None:
        if self.cost_aversion < Decimal("0"):
            raise ValueError("cost_aversion cannot be negative")
        if self.min_trade_weight < Decimal("0"):
            raise ValueError("min_trade_weight cannot be negative")

    def optimize(self, optimization_input: OptimizationInput) -> OptimizationResult:
        """Return a cost-aware version of the wrapped optimizer result."""

        base_result = self.base_optimizer.optimize(optimization_input)
        portfolio_value = self._portfolio_value(optimization_input.metadata)
        prices = self._prices(optimization_input.metadata)

        if portfolio_value <= Decimal("0") or self.cost_aversion == Decimal("0"):
            return self._with_metadata(
                result=base_result,
                metadata={
                    "optimizer": self.name,
                    "base_optimizer": self.base_optimizer.name,
                    "cost_adjustment_factor": Decimal("1"),
                    "estimated_cost": Decimal("0"),
                    "estimated_cost_weight": Decimal("0"),
                    "estimated_trades": (),
                    "gross_target_weights": dict(base_result.target_weights),
                },
            )

        estimated_trades = self._estimate_trade_costs(
            current_weights=optimization_input.current_weights,
            target_weights=base_result.target_weights,
            prices=prices,
            portfolio_value=portfolio_value,
        )
        estimated_cost = sum(
            (trade.total_cost for trade in estimated_trades),
            Decimal("0"),
        )
        estimated_cost_weight = estimated_cost / portfolio_value

        adjustment_factor = self._adjustment_factor(
            expected_turnover=base_result.expected_turnover,
            estimated_cost_weight=estimated_cost_weight,
        )
        target_weights = self._shrink_trade_deltas(
            current_weights=optimization_input.current_weights,
            target_weights=base_result.target_weights,
            adjustment_factor=adjustment_factor,
        )

        expected_turnover = self._calculate_turnover(
            current_weights=optimization_input.current_weights,
            target_weights=target_weights,
        )
        violations = optimization_input.constraints.validate(
            target_weights=target_weights,
            current_weights=optimization_input.current_weights,
            sector_by_symbol=optimization_input.sector_by_symbol,
            cash_weight=base_result.cash_weight,
        )

        return OptimizationResult(
            target_weights=target_weights,
            success=base_result.success and len(violations) == 0,
            expected_turnover=expected_turnover,
            cash_weight=base_result.cash_weight,
            constraint_violations=base_result.constraint_violations + violations,
            metadata={
                **dict(base_result.metadata),
                "optimizer": self.name,
                "base_optimizer": self.base_optimizer.name,
                "cost_adjustment_factor": adjustment_factor,
                "estimated_cost": estimated_cost,
                "estimated_cost_weight": estimated_cost_weight,
                "estimated_trades": estimated_trades,
                "gross_target_weights": dict(base_result.target_weights),
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
        return MappingProxyType(prices)

    def _estimate_trade_costs(
        self,
        *,
        current_weights: Mapping[str, Decimal],
        target_weights: Mapping[str, Decimal],
        prices: Mapping[str, Decimal],
        portfolio_value: Decimal,
    ) -> tuple[EstimatedTradeCost, ...]:
        trades: list[EstimatedTradeCost] = []
        symbols = tuple(sorted(set(current_weights) | set(target_weights)))

        for symbol in symbols:
            weight_delta = target_weights.get(
                symbol, Decimal("0")
            ) - current_weights.get(
                symbol,
                Decimal("0"),
            )
            if abs(weight_delta) <= self.min_trade_weight:
                continue

            price = self._price_for_symbol(symbol=symbol, prices=prices)
            quantity = self._quantity_from_weight_delta(
                weight_delta=weight_delta,
                price=price,
                portfolio_value=portfolio_value,
            )
            if quantity == 0:
                continue

            breakdown = self.cost_estimator.estimate(
                CostInput(symbol=symbol, quantity=quantity, price=price)
            )
            trades.append(
                EstimatedTradeCost(
                    symbol=symbol,
                    quantity=quantity,
                    price=price,
                    weight_delta=weight_delta,
                    breakdown=breakdown,
                )
            )

        return tuple(trades)

    def _price_for_symbol(
        self,
        *,
        symbol: str,
        prices: Mapping[str, Decimal],
    ) -> Decimal:
        try:
            return prices[symbol]
        except KeyError as exc:
            raise ValueError(f"missing price for {symbol}") from exc

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

    def _adjustment_factor(
        self,
        *,
        expected_turnover: Decimal,
        estimated_cost_weight: Decimal,
    ) -> Decimal:
        if expected_turnover <= Decimal("0") or estimated_cost_weight <= Decimal("0"):
            return Decimal("1")

        penalty = self.cost_aversion * estimated_cost_weight / expected_turnover
        factor = Decimal("1") - penalty
        if factor < Decimal("0"):
            return Decimal("0")
        if factor > Decimal("1"):
            return Decimal("1")
        return factor

    def _shrink_trade_deltas(
        self,
        *,
        current_weights: Mapping[str, Decimal],
        target_weights: Mapping[str, Decimal],
        adjustment_factor: Decimal,
    ) -> dict[str, Decimal]:
        symbols = tuple(sorted(set(current_weights) | set(target_weights)))
        adjusted_weights: dict[str, Decimal] = {}

        for symbol in symbols:
            current_weight = current_weights.get(symbol, Decimal("0"))
            target_weight = target_weights.get(symbol, Decimal("0"))
            adjusted_weight = current_weight + (
                (target_weight - current_weight) * adjustment_factor
            )
            if adjusted_weight > Decimal("0"):
                adjusted_weights[symbol] = adjusted_weight

        return adjusted_weights

    def _calculate_turnover(
        self,
        *,
        current_weights: Mapping[str, Decimal],
        target_weights: Mapping[str, Decimal],
    ) -> Decimal:
        symbols = set(current_weights) | set(target_weights)
        return sum(
            abs(
                target_weights.get(symbol, Decimal("0"))
                - current_weights.get(symbol, Decimal("0"))
            )
            for symbol in symbols
        ) / Decimal("2")

    def _with_metadata(
        self,
        *,
        result: OptimizationResult,
        metadata: Mapping[str, Any],
    ) -> OptimizationResult:
        return OptimizationResult(
            target_weights=result.target_weights,
            success=result.success,
            expected_turnover=result.expected_turnover,
            cash_weight=result.cash_weight,
            constraint_violations=result.constraint_violations,
            metadata={**dict(result.metadata), **dict(metadata)},
        )

    def _decimal(self, value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int | str):
            return Decimal(value)
        raise TypeError(
            "cost-aware optimizer numeric metadata must be Decimal, int, or str"
        )
