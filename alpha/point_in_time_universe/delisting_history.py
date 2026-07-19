"""Focused delisting exclusions used by integrity and replay audits."""

from __future__ import annotations

from datetime import date

from alpha.point_in_time_universe.listing_history import ListingHistory
from alpha.point_in_time_universe.models import TradabilityStatus


class DelistingHistory:
    def __init__(self, listings: ListingHistory) -> None:
        self.listings = listings

    def excluded(self, security_id: str, as_of: date) -> bool:
        return self.listings.status(security_id, as_of) is TradabilityStatus.DELISTED

    def delisting_date(self, security_id: str) -> date | None:
        record = self.listings.record(security_id)
        return None if record is None else record.delisting_date


__all__ = ["DelistingHistory"]
