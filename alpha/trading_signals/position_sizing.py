from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from types import MappingProxyType

from alpha.trading_signals.ensemble import (
    EnsembleDecisionReport,
    TradeRecommendation,
)
from alpha.trading_signals.models import SignalSide

_ZERO = Decimal("0")
_ONE = Decimal("1")
_DEFAULT_MINIMUM_SCORE = Decimal("0.55")
_DEFAULT_MAX_POSITION_WEIGHT = Decimal("0.10")
_DEFAULT_CASH_RESERVE_WEIGHT = Decimal("0.10")
_DEFAULT_LOT_SIZE = 1


@dataclass(frozen=True, slots=True)
class PositionSizingConfig:
    """Deterministic constraints for recommendation position sizing."""

    portfolio_value: Decimal
    cash_reserve_weight: Decimal = _DEFAULT_CASH_RESERVE_WEIGHT
    max_position_weight: Decimal = _DEFAULT_MAX_POSITION_WEIGHT
    minimum_recommendation_score: Decimal = _DEFAULT_MINIMUM_SCORE
    lot_size: int = _DEFAULT_LOT_SIZE

    def __post_init__(self) -> None:
        portfolio_value = Decimal(str(self.portfolio_value))
        cash_reserve_weight = _bounded_decimal(
            value=self.cash_reserve_weight,
            label="cash reserve weight",
            allow_one=False,
        )
        max_position_weight = _bounded_decimal(
            value=self.max_position_weight,
            label="maximum position weight",
            allow_zero=False,
        )
        minimum_score = _bounded_decimal(
            value=self.minimum_recommendation_score,
            label="minimum recommendation score",
        )

        if portfolio_value <= _ZERO:
            raise ValueError("portfolio value must be greater than zero")
        if self.lot_size <= 0:
            raise ValueError("lot size must be positive")

        object.__setattr__(self, "portfolio_value", portfolio_value)
        object.__setattr__(self, "cash_reserve_weight", cash_reserve_weight)
        object.__setattr__(self, "max_position_weight", max_position_weight)
        object.__setattr__(
            self,
            "minimum_recommendation_score",
            minimum_score,
        )

    @property
    def deployable_weight(self) -> Decimal:
        return _ONE - self.cash_reserve_weight

    @property
    def deployable_capital(self) -> Decimal:
        return self.portfolio_value * self.deployable_weight


@dataclass(frozen=True, slots=True)
class SizedTradeRecommendation:
    """Recommendation enriched with deterministic portfolio sizing."""

    symbol: str
    action: SignalSide
    recommendation_score: Decimal
    target_weight: Decimal
    target_notional: Decimal
    estimated_price: Decimal
    quantity: int
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        recommendation_score = _bounded_decimal(
            value=self.recommendation_score,
            label="recommendation score",
        )
        target_weight = _bounded_decimal(
            value=self.target_weight,
            label="target weight",
        )
        target_notional = Decimal(str(self.target_notional))
        estimated_price = Decimal(str(self.estimated_price))
        reasons = tuple(reason.strip() for reason in self.reasons)

        if not symbol:
            raise ValueError("sized recommendation symbol cannot be empty")
        if target_notional < _ZERO:
            raise ValueError("target notional cannot be negative")
        if estimated_price <= _ZERO:
            raise ValueError("estimated price must be greater than zero")
        if any(not reason for reason in reasons):
            raise ValueError("sized recommendation reasons cannot be empty")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "recommendation_score", recommendation_score)
        object.__setattr__(self, "target_weight", target_weight)
        object.__setattr__(self, "target_notional", target_notional)
        object.__setattr__(self, "estimated_price", estimated_price)
        object.__setattr__(self, "reasons", reasons)

    @property
    def is_actionable(self) -> bool:
        return self.quantity != 0


@dataclass(frozen=True, slots=True)
class TradePlan:
    """Immutable portfolio-aware trade plan."""

    generated_for: date
    portfolio_value: Decimal
    cash_reserve_weight: Decimal
    trades: tuple[SizedTradeRecommendation, ...]

    def __post_init__(self) -> None:
        portfolio_value = Decimal(str(self.portfolio_value))
        cash_reserve_weight = _bounded_decimal(
            value=self.cash_reserve_weight,
            label="cash reserve weight",
            allow_one=False,
        )
        sorted_trades = tuple(
            sorted(
                self.trades,
                key=lambda trade: (
                    _action_sort_key(trade.action),
                    -trade.recommendation_score,
                    trade.symbol,
                ),
            )
        )

        if portfolio_value <= _ZERO:
            raise ValueError("portfolio value must be greater than zero")
        if len({trade.symbol for trade in sorted_trades}) != len(sorted_trades):
            raise ValueError("trade plan cannot contain duplicate symbols")

        object.__setattr__(self, "portfolio_value", portfolio_value)
        object.__setattr__(self, "cash_reserve_weight", cash_reserve_weight)
        object.__setattr__(self, "trades", sorted_trades)

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def actionable(self) -> tuple[SizedTradeRecommendation, ...]:
        return tuple(trade for trade in self.trades if trade.is_actionable)

    @property
    def buys(self) -> tuple[SizedTradeRecommendation, ...]:
        return tuple(trade for trade in self.trades if trade.action is SignalSide.BUY)

    @property
    def sells(self) -> tuple[SizedTradeRecommendation, ...]:
        return tuple(trade for trade in self.trades if trade.action is SignalSide.SELL)

    @property
    def gross_buy_notional(self) -> Decimal:
        return sum(
            (trade.target_notional for trade in self.buys),
            _ZERO,
        )

    @property
    def gross_sell_notional(self) -> Decimal:
        return sum(
            (trade.target_notional for trade in self.sells),
            _ZERO,
        )

    def get(self, symbol: str) -> SizedTradeRecommendation:
        normalized_symbol = symbol.strip().upper()
        for trade in self.trades:
            if trade.symbol == normalized_symbol:
                return trade
        raise KeyError(f"unknown trade plan symbol: {symbol}")


@dataclass(frozen=True, slots=True)
class RecommendationPositionSizer:
    """Turn explainable recommendations into deterministic trade sizes."""

    config: PositionSizingConfig

    def size(
        self,
        *,
        report: EnsembleDecisionReport,
        prices: Mapping[str, Decimal],
        current_positions: Mapping[str, int] | None = None,
    ) -> TradePlan:
        normalized_prices = self._normalize_prices(prices)
        normalized_positions = MappingProxyType(dict(current_positions or {}))
        sells = self._sell_trades(
            recommendations=report.sells,
            prices=normalized_prices,
            current_positions=normalized_positions,
        )
        buys = self._buy_trades(
            recommendations=report.buys,
            prices=normalized_prices,
        )

        return TradePlan(
            generated_for=report.generated_for,
            portfolio_value=self.config.portfolio_value,
            cash_reserve_weight=self.config.cash_reserve_weight,
            trades=(*sells, *buys),
        )

    def _normalize_prices(
        self,
        prices: Mapping[str, Decimal],
    ) -> Mapping[str, Decimal]:
        normalized: dict[str, Decimal] = {}
        for symbol, price in prices.items():
            normalized_symbol = symbol.strip().upper()
            normalized_price = Decimal(str(price))
            if not normalized_symbol:
                raise ValueError("price symbol cannot be empty")
            if normalized_price <= _ZERO:
                raise ValueError("prices must be greater than zero")
            normalized[normalized_symbol] = normalized_price
        return MappingProxyType(normalized)

    def _sell_trades(
        self,
        *,
        recommendations: Iterable[TradeRecommendation],
        prices: Mapping[str, Decimal],
        current_positions: Mapping[str, int],
    ) -> tuple[SizedTradeRecommendation, ...]:
        trades: list[SizedTradeRecommendation] = []
        for recommendation in sorted(
            recommendations,
            key=lambda item: item.symbol,
        ):
            held_quantity = current_positions.get(recommendation.symbol, 0)
            if held_quantity <= 0 or recommendation.symbol not in prices:
                continue

            price = prices[recommendation.symbol]
            target_notional = Decimal(held_quantity) * price
            trades.append(
                SizedTradeRecommendation(
                    symbol=recommendation.symbol,
                    action=SignalSide.SELL,
                    recommendation_score=recommendation.recommendation_score,
                    target_weight=_ZERO,
                    target_notional=target_notional,
                    estimated_price=price,
                    quantity=-held_quantity,
                    reasons=(
                        "sell recommendation has current holdings",
                        f"recommendation score: {recommendation.recommendation_score}",
                    ),
                )
            )
        return tuple(trades)

    def _buy_trades(
        self,
        *,
        recommendations: Iterable[TradeRecommendation],
        prices: Mapping[str, Decimal],
    ) -> tuple[SizedTradeRecommendation, ...]:
        eligible = tuple(
            recommendation
            for recommendation in recommendations
            if self._is_eligible_buy(
                recommendation=recommendation,
                prices=prices,
            )
        )
        total_score = sum(
            (recommendation.recommendation_score for recommendation in eligible),
            _ZERO,
        )
        if total_score <= _ZERO:
            return ()

        trades: list[SizedTradeRecommendation] = []
        for recommendation in sorted(
            eligible,
            key=lambda item: (-item.recommendation_score, item.symbol),
        ):
            price = prices[recommendation.symbol]
            target_weight = self._target_weight(
                recommendation=recommendation,
                total_score=total_score,
            )
            target_notional = self.config.portfolio_value * target_weight
            quantity = _floor_quantity(
                notional=target_notional,
                price=price,
                lot_size=self.config.lot_size,
            )
            if quantity <= 0:
                continue

            executable_notional = Decimal(quantity) * price
            trades.append(
                SizedTradeRecommendation(
                    symbol=recommendation.symbol,
                    action=SignalSide.BUY,
                    recommendation_score=recommendation.recommendation_score,
                    target_weight=target_weight,
                    target_notional=executable_notional,
                    estimated_price=price,
                    quantity=quantity,
                    reasons=(
                        "buy recommendation passed score threshold",
                        f"target weight: {target_weight}",
                        f"recommendation score: {recommendation.recommendation_score}",
                    ),
                )
            )
        return tuple(trades)

    def _is_eligible_buy(
        self,
        *,
        recommendation: TradeRecommendation,
        prices: Mapping[str, Decimal],
    ) -> bool:
        return (
            recommendation.action is SignalSide.BUY
            and recommendation.symbol in prices
            and recommendation.recommendation_score
            >= self.config.minimum_recommendation_score
        )

    def _target_weight(
        self,
        *,
        recommendation: TradeRecommendation,
        total_score: Decimal,
    ) -> Decimal:
        score_share = recommendation.recommendation_score / total_score
        uncapped_weight = self.config.deployable_weight * score_share
        return min(uncapped_weight, self.config.max_position_weight)


def _bounded_decimal(
    *,
    value: Decimal,
    label: str,
    allow_zero: bool = True,
    allow_one: bool = True,
) -> Decimal:
    normalized = Decimal(str(value))
    if allow_zero:
        lower_bound_failed = normalized < _ZERO
    else:
        lower_bound_failed = normalized <= _ZERO
    if allow_one:
        upper_bound_failed = normalized > _ONE
    else:
        upper_bound_failed = normalized >= _ONE

    if lower_bound_failed or upper_bound_failed:
        raise ValueError(f"{label} must be between 0 and 1")
    return normalized


def _floor_quantity(
    *,
    notional: Decimal,
    price: Decimal,
    lot_size: int,
) -> int:
    raw_quantity = (notional / price).to_integral_value(
        rounding=ROUND_FLOOR,
    )
    lot_count = (raw_quantity / Decimal(lot_size)).to_integral_value(
        rounding=ROUND_FLOOR,
    )
    return int(lot_count) * lot_size


def _action_sort_key(action: SignalSide) -> int:
    if action is SignalSide.SELL:
        return 0
    if action is SignalSide.BUY:
        return 1
    return 2
