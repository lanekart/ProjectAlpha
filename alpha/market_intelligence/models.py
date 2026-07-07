from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_HIGH_DELIVERY = Decimal("60")
_LOW_DELIVERY = Decimal("35")
_RISING = Decimal("0")
_FALLING = Decimal("0")
_STRONG_VOLUME_EXPANSION = Decimal("20")


class DeliveryBehavior(StrEnum):
    """Classification of ownership transfer quality."""

    ACCUMULATION = "ACCUMULATION"
    DISTRIBUTION = "DISTRIBUTION"
    SPECULATIVE = "SPECULATIVE"
    NEUTRAL = "NEUTRAL"


class DerivativesPositioning(StrEnum):
    """Classification of futures price and open-interest behavior."""

    NEW_LONGS = "NEW_LONGS"
    SHORT_COVERING = "SHORT_COVERING"
    NEW_SHORTS = "NEW_SHORTS"
    LONG_UNWINDING = "LONG_UNWINDING"
    NEUTRAL = "NEUTRAL"


class MarketMood(StrEnum):
    """Deterministic stock-level market mood."""

    BULLISH_ACCUMULATION = "BULLISH_ACCUMULATION"
    SPECULATIVE_RALLY = "SPECULATIVE_RALLY"
    BEARISH_DISTRIBUTION = "BEARISH_DISTRIBUTION"
    BEARISH_SHORT_BUILDUP = "BEARISH_SHORT_BUILDUP"
    EXHAUSTION = "EXHAUSTION"
    NEUTRAL = "NEUTRAL"


class MarketDirectionBias(StrEnum):
    """Forward-looking directional bias used by recommendation engines."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True, slots=True)
class StockMarketState:
    """Immutable stock-level state used by the market digital twin.

    Percent fields are represented as percentage points, not fractions.
    Example: delivery_percent=Decimal("72") means 72% delivery.
    """

    symbol: str
    observed_on: date
    price_change_percent: Decimal
    delivery_percent: Decimal
    delivery_change_percent: Decimal
    volume_change_percent: Decimal
    futures_oi_change_percent: Decimal

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        price_change = Decimal(str(self.price_change_percent))
        delivery_percent = Decimal(str(self.delivery_percent))
        delivery_change = Decimal(str(self.delivery_change_percent))
        volume_change = Decimal(str(self.volume_change_percent))
        oi_change = Decimal(str(self.futures_oi_change_percent))

        if not symbol:
            raise ValueError("market state symbol cannot be empty")
        if delivery_percent < _ZERO or delivery_percent > _HUNDRED:
            raise ValueError("delivery percent must be between 0 and 100")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "price_change_percent", price_change)
        object.__setattr__(self, "delivery_percent", delivery_percent)
        object.__setattr__(self, "delivery_change_percent", delivery_change)
        object.__setattr__(self, "volume_change_percent", volume_change)
        object.__setattr__(self, "futures_oi_change_percent", oi_change)


@dataclass(frozen=True, slots=True)
class MarketStateAssessment:
    """Explainable digital-twin assessment for one stock."""

    symbol: str
    observed_on: date
    delivery_behavior: DeliveryBehavior
    derivatives_positioning: DerivativesPositioning
    mood: MarketMood
    direction_bias: MarketDirectionBias
    accumulation_score: Decimal
    distribution_score: Decimal
    speculative_score: Decimal
    derivatives_bias_score: Decimal
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        reasons = tuple(reason.strip() for reason in self.reasons)

        if not symbol:
            raise ValueError("assessment symbol cannot be empty")
        if any(not reason for reason in reasons):
            raise ValueError("assessment reasons cannot be empty")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "accumulation_score",
            _bounded_score(self.accumulation_score, "accumulation score"),
        )
        object.__setattr__(
            self,
            "distribution_score",
            _bounded_score(self.distribution_score, "distribution score"),
        )
        object.__setattr__(
            self,
            "speculative_score",
            _bounded_score(self.speculative_score, "speculative score"),
        )
        object.__setattr__(
            self,
            "derivatives_bias_score",
            _bounded_score(
                self.derivatives_bias_score,
                "derivatives bias score",
            ),
        )
        object.__setattr__(self, "reasons", reasons)

    @property
    def is_constructive(self) -> bool:
        return self.direction_bias is MarketDirectionBias.POSITIVE

    @property
    def is_defensive(self) -> bool:
        return self.direction_bias is MarketDirectionBias.NEGATIVE


@dataclass(frozen=True, slots=True)
class MarketStateClassifier:
    """Classify stock mood from delivery and derivatives participation."""

    def classify(self, state: StockMarketState) -> MarketStateAssessment:
        delivery_behavior = self._delivery_behavior(state)
        positioning = self._derivatives_positioning(state)
        accumulation_score = self._accumulation_score(state)
        distribution_score = self._distribution_score(state)
        speculative_score = self._speculative_score(state)
        derivatives_bias_score = self._derivatives_bias_score(positioning)
        mood = self._mood(
            delivery_behavior=delivery_behavior,
            positioning=positioning,
            state=state,
        )
        direction_bias = self._direction_bias(mood)

        return MarketStateAssessment(
            symbol=state.symbol,
            observed_on=state.observed_on,
            delivery_behavior=delivery_behavior,
            derivatives_positioning=positioning,
            mood=mood,
            direction_bias=direction_bias,
            accumulation_score=accumulation_score,
            distribution_score=distribution_score,
            speculative_score=speculative_score,
            derivatives_bias_score=derivatives_bias_score,
            reasons=self._reasons(
                state=state,
                delivery_behavior=delivery_behavior,
                positioning=positioning,
                mood=mood,
            ),
        )

    def _delivery_behavior(
        self,
        state: StockMarketState,
    ) -> DeliveryBehavior:
        if (
            state.delivery_percent >= _HIGH_DELIVERY
            and state.delivery_change_percent > _RISING
            and state.price_change_percent > _RISING
        ):
            return DeliveryBehavior.ACCUMULATION

        if (
            state.delivery_percent >= _HIGH_DELIVERY
            and state.price_change_percent < _FALLING
        ):
            return DeliveryBehavior.DISTRIBUTION

        if (
            state.delivery_percent <= _LOW_DELIVERY
            and state.volume_change_percent >= _STRONG_VOLUME_EXPANSION
        ):
            return DeliveryBehavior.SPECULATIVE

        return DeliveryBehavior.NEUTRAL

    def _derivatives_positioning(
        self,
        state: StockMarketState,
    ) -> DerivativesPositioning:
        price_up = state.price_change_percent > _RISING
        price_down = state.price_change_percent < _FALLING
        oi_up = state.futures_oi_change_percent > _RISING
        oi_down = state.futures_oi_change_percent < _FALLING

        if price_up and oi_up:
            return DerivativesPositioning.NEW_LONGS
        if price_up and oi_down:
            return DerivativesPositioning.SHORT_COVERING
        if price_down and oi_up:
            return DerivativesPositioning.NEW_SHORTS
        if price_down and oi_down:
            return DerivativesPositioning.LONG_UNWINDING
        return DerivativesPositioning.NEUTRAL

    def _accumulation_score(self, state: StockMarketState) -> Decimal:
        delivery_component = state.delivery_percent / _HUNDRED
        delivery_trend = _positive_percent_score(state.delivery_change_percent)
        price_component = _positive_percent_score(state.price_change_percent)
        return _bounded_score(
            (
                delivery_component * Decimal("0.50")
                + delivery_trend * Decimal("0.30")
                + price_component * Decimal("0.20")
            ),
            "accumulation score",
        )

    def _distribution_score(self, state: StockMarketState) -> Decimal:
        delivery_component = state.delivery_percent / _HUNDRED
        price_weakness = _positive_percent_score(-state.price_change_percent)
        oi_component = _positive_percent_score(state.futures_oi_change_percent)
        return _bounded_score(
            (
                delivery_component * Decimal("0.45")
                + price_weakness * Decimal("0.35")
                + oi_component * Decimal("0.20")
            ),
            "distribution score",
        )

    def _speculative_score(self, state: StockMarketState) -> Decimal:
        low_delivery_component = (_HUNDRED - state.delivery_percent) / _HUNDRED
        volume_component = _positive_percent_score(state.volume_change_percent)
        oi_component = _positive_percent_score(state.futures_oi_change_percent)
        return _bounded_score(
            (
                low_delivery_component * Decimal("0.40")
                + volume_component * Decimal("0.30")
                + oi_component * Decimal("0.30")
            ),
            "speculative score",
        )

    def _derivatives_bias_score(
        self,
        positioning: DerivativesPositioning,
    ) -> Decimal:
        if positioning is DerivativesPositioning.NEW_LONGS:
            return Decimal("0.85")
        if positioning is DerivativesPositioning.SHORT_COVERING:
            return Decimal("0.60")
        if positioning is DerivativesPositioning.NEW_SHORTS:
            return Decimal("0.15")
        if positioning is DerivativesPositioning.LONG_UNWINDING:
            return Decimal("0.35")
        return Decimal("0.50")

    def _mood(
        self,
        *,
        delivery_behavior: DeliveryBehavior,
        positioning: DerivativesPositioning,
        state: StockMarketState,
    ) -> MarketMood:
        if (
            delivery_behavior is DeliveryBehavior.ACCUMULATION
            and positioning is DerivativesPositioning.NEW_LONGS
        ):
            return MarketMood.BULLISH_ACCUMULATION

        if (
            delivery_behavior is DeliveryBehavior.SPECULATIVE
            and state.price_change_percent > _RISING
        ):
            return MarketMood.SPECULATIVE_RALLY

        if delivery_behavior is DeliveryBehavior.DISTRIBUTION:
            return MarketMood.BEARISH_DISTRIBUTION

        if positioning is DerivativesPositioning.NEW_SHORTS:
            return MarketMood.BEARISH_SHORT_BUILDUP

        if positioning is DerivativesPositioning.LONG_UNWINDING:
            return MarketMood.EXHAUSTION

        return MarketMood.NEUTRAL

    def _direction_bias(self, mood: MarketMood) -> MarketDirectionBias:
        if mood is MarketMood.BULLISH_ACCUMULATION:
            return MarketDirectionBias.POSITIVE
        if mood in {
            MarketMood.BEARISH_DISTRIBUTION,
            MarketMood.BEARISH_SHORT_BUILDUP,
            MarketMood.EXHAUSTION,
        }:
            return MarketDirectionBias.NEGATIVE
        return MarketDirectionBias.NEUTRAL

    def _reasons(
        self,
        *,
        state: StockMarketState,
        delivery_behavior: DeliveryBehavior,
        positioning: DerivativesPositioning,
        mood: MarketMood,
    ) -> tuple[str, ...]:
        return (
            f"delivery behavior: {delivery_behavior.value}",
            f"derivatives positioning: {positioning.value}",
            f"market mood: {mood.value}",
            f"delivery percent: {state.delivery_percent}",
            f"futures oi change percent: {state.futures_oi_change_percent}",
        )


def _positive_percent_score(value: Decimal) -> Decimal:
    if value <= _ZERO:
        return _ZERO
    return min(value / _HUNDRED, _ONE)


def _bounded_score(value: Decimal, label: str) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < _ZERO or normalized > _ONE:
        raise ValueError(f"{label} must be between 0 and 1")
    return normalized
