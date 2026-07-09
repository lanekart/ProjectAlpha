from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from alpha.live.models import MarketSessionState


@dataclass(frozen=True, slots=True)
class MarketSessionEngine:
    holidays: frozenset[date] = frozenset()

    def state_at(self, observed_at: datetime) -> MarketSessionState:
        current_date = observed_at.date()
        current_time = observed_at.time()
        if current_date in self.holidays:
            return MarketSessionState.HOLIDAY
        if observed_at.weekday() >= 5:
            return MarketSessionState.WEEKEND
        if time(9, 0) <= current_time < time(9, 8):
            return MarketSessionState.PRE_OPEN
        if time(9, 8) <= current_time < time(9, 15):
            return MarketSessionState.OPENING_AUCTION
        if time(9, 15) <= current_time < time(10, 0):
            return MarketSessionState.OPEN
        if time(10, 0) <= current_time < time(14, 30):
            return MarketSessionState.MID_SESSION
        if time(14, 30) <= current_time < time(15, 15):
            return MarketSessionState.POWER_HOUR
        if time(15, 15) <= current_time < time(15, 30):
            return MarketSessionState.CLOSING_SESSION
        if current_time >= time(15, 30):
            return MarketSessionState.POST_CLOSE
        return MarketSessionState.UNKNOWN

    def is_trading(self, observed_at: datetime) -> bool:
        return self.state_at(observed_at) in {
            MarketSessionState.OPEN,
            MarketSessionState.MID_SESSION,
            MarketSessionState.POWER_HOUR,
            MarketSessionState.CLOSING_SESSION,
        }

    def bars_expected(self, observed_at: datetime) -> bool:
        return self.is_trading(observed_at)

    def accept_live_ticks(self, observed_at: datetime) -> bool:
        return self.state_at(observed_at) in {
            MarketSessionState.OPENING_AUCTION,
            MarketSessionState.OPEN,
            MarketSessionState.MID_SESSION,
            MarketSessionState.POWER_HOUR,
            MarketSessionState.CLOSING_SESSION,
        }


__all__ = ["MarketSessionEngine"]
