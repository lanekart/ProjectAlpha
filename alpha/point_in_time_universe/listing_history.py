"""Listing, suspension, relisting, and tradability history."""

from __future__ import annotations

from datetime import date

from alpha.point_in_time_universe.models import (
    ListingHistoryRecord,
    TradabilityStatus,
)


class ListingHistory:
    def __init__(self, records: tuple[ListingHistoryRecord, ...] = ()) -> None:
        self.records = tuple(sorted(records, key=lambda item: item.security_id))
        self._by_id = {item.security_id: item for item in self.records}
        if len(self._by_id) != len(self.records):
            raise ValueError("listing history requires unique security ids")

    def status(self, security_id: str, as_of: date) -> TradabilityStatus:
        record = self._by_id.get(security_id)
        if record is None or record.listing_date is None:
            return TradabilityStatus.UNKNOWN
        first_tradable = record.first_tradable_date or record.listing_date
        if as_of < first_tradable:
            return TradabilityStatus.NOT_YET_LISTED
        if record.delisting_date is not None and as_of > record.delisting_date:
            return TradabilityStatus.DELISTED
        if any(item.interval.covers(as_of) for item in record.suspensions):
            return TradabilityStatus.SUSPENDED
        return TradabilityStatus.TRADABLE

    def record(self, security_id: str) -> ListingHistoryRecord | None:
        return self._by_id.get(security_id)


__all__ = ["ListingHistory"]
