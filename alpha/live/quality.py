from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from alpha.live.models import (
    InstrumentSubscription,
    LiveTick,
    TickQualityAssessment,
    TickQualityStatistics,
    TickQualityStatus,
)


@dataclass(slots=True)
class TickQualityEngine:
    subscriptions: tuple[InstrumentSubscription, ...]
    extreme_price_jump_percent: Decimal = Decimal("10")
    extreme_volume_multiplier: Decimal = Decimal("10")
    _last_tick_by_symbol: dict[str, LiveTick] = field(default_factory=dict)
    _total_ticks: int = 0
    _valid_ticks: int = 0
    _suspect_ticks: int = 0
    _invalid_ticks: int = 0
    _rejection_reasons: dict[str, int] = field(default_factory=dict)

    def validate_tick(self, tick: LiveTick) -> TickQualityAssessment:
        return self.validate_fields(
            symbol=tick.symbol,
            price=tick.price,
            volume=tick.volume,
            observed_at=tick.observed_at,
            instrument_key=tick.instrument_key,
            tick=tick,
        )

    def validate_fields(
        self,
        *,
        symbol: str | None,
        price: Decimal | None,
        volume: Decimal | None,
        observed_at: datetime | None,
        instrument_key: str | None = None,
        tick: LiveTick | None = None,
    ) -> TickQualityAssessment:
        self._total_ticks += 1
        normalized_symbol = (symbol or "UNKNOWN").strip().upper()
        reasons: list[str] = []
        invalid = False

        if not symbol or not symbol.strip():
            reasons.append("missing symbol")
            invalid = True
        if observed_at is None:
            reasons.append("missing timestamp")
            invalid = True
        if price is None:
            reasons.append("missing price")
            invalid = True
        elif price == Decimal("0"):
            reasons.append("zero price")
            invalid = True
        elif price < Decimal("0"):
            reasons.append("negative price")
            invalid = True
        if volume is None:
            reasons.append("missing volume")
            invalid = True
        elif volume < Decimal("0"):
            reasons.append("negative volume")
            invalid = True

        if normalized_symbol != "UNKNOWN" and normalized_symbol not in self._symbols:
            reasons.append("invalid instrument")
            invalid = True
        if instrument_key is not None and instrument_key not in self._instrument_keys:
            reasons.append("invalid instrument")
            invalid = True

        previous = self._last_tick_by_symbol.get(normalized_symbol)
        if previous is not None and observed_at is not None:
            if observed_at < previous.observed_at:
                reasons.append("timestamp regression")
                invalid = True
            elif observed_at == previous.observed_at:
                reasons.append("duplicate timestamp")
        if previous is not None and price is not None:
            if price == previous.price:
                reasons.append("duplicate price")
            elif previous.price > Decimal("0"):
                change = abs((price - previous.price) / previous.price) * Decimal("100")
                if change > self.extreme_price_jump_percent:
                    reasons.append("extreme price jump")
        if (
            previous is not None
            and volume is not None
            and previous.volume > Decimal("0")
        ):
            if volume > previous.volume * self.extreme_volume_multiplier:
                reasons.append("extreme volume spike")

        status = TickQualityStatus.INVALID if invalid else TickQualityStatus.VALID
        if not invalid and reasons:
            status = TickQualityStatus.SUSPECT

        if status is TickQualityStatus.VALID:
            self._valid_ticks += 1
        elif status is TickQualityStatus.SUSPECT:
            self._suspect_ticks += 1
        else:
            self._invalid_ticks += 1
            for reason in reasons:
                self._rejection_reasons[reason] = (
                    self._rejection_reasons.get(reason, 0) + 1
                )

        if status is not TickQualityStatus.INVALID and tick is not None:
            self._last_tick_by_symbol[normalized_symbol] = tick

        return TickQualityAssessment(
            symbol=normalized_symbol,
            status=status,
            reasons=tuple(reasons),
            observed_at=observed_at,
        )

    @property
    def statistics(self) -> TickQualityStatistics:
        return TickQualityStatistics(
            total_ticks=self._total_ticks,
            valid_ticks=self._valid_ticks,
            suspect_ticks=self._suspect_ticks,
            invalid_ticks=self._invalid_ticks,
            rejection_reasons=dict(self._rejection_reasons),
        )

    @property
    def _symbols(self) -> set[str]:
        return {subscription.symbol for subscription in self.subscriptions}

    @property
    def _instrument_keys(self) -> set[str]:
        return {subscription.instrument_key for subscription in self.subscriptions}


__all__ = ["TickQualityEngine"]
