from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from alpha.market_truth.warehouse.models import Exchange, IdentityRecord
from alpha.market_truth.warehouse.storage import WarehouseStore


class AmbiguousIdentityError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class IdentityAudit:
    records: int
    securities: int
    symbols: int
    duplicate_intervals: int
    ambiguous_symbols: int
    isin_continuity_breaks: int


class HistoricalIdentityService:
    def __init__(self, store: WarehouseStore) -> None:
        self.store = store

    def resolve(
        self, *, exchange: Exchange, symbol: str, as_of: date
    ) -> IdentityRecord | None:
        matching = tuple(
            item
            for item in self.store.identity_records(exchange=exchange)
            if item.symbol == symbol.upper()
            and item.symbol_valid_from <= as_of
            and (item.symbol_valid_to is None or as_of <= item.symbol_valid_to)
        )
        security_ids = {item.security_id for item in matching}
        if len(security_ids) > 1:
            raise AmbiguousIdentityError(
                f"{exchange.value}:{symbol.upper()} is ambiguous on {as_of.isoformat()}"
            )
        return max(matching, key=lambda item: item.identity_confidence, default=None)

    def continuity(
        self, *, exchange: Exchange, security_id: str
    ) -> tuple[IdentityRecord, ...]:
        return tuple(
            item
            for item in self.store.identity_records(exchange=exchange)
            if item.security_id == security_id
        )

    def audit(self) -> IdentityAudit:
        records = self.store.identity_records()
        intervals: set[tuple[object, ...]] = set()
        duplicates = 0
        symbol_dates: dict[tuple[Exchange, str, date], set[str]] = {}
        isins: dict[str, set[str]] = {}
        for item in records:
            key = (
                item.exchange,
                item.security_id,
                item.symbol,
                item.symbol_valid_from,
                item.symbol_valid_to,
            )
            if key in intervals:
                duplicates += 1
            intervals.add(key)
            symbol_dates.setdefault(
                (item.exchange, item.symbol, item.symbol_valid_from), set()
            ).add(item.security_id)
            if item.isin:
                isins.setdefault(item.security_id, set()).add(item.isin)
        return IdentityAudit(
            records=len(records),
            securities=len({item.security_id for item in records}),
            symbols=len({(item.exchange, item.symbol) for item in records}),
            duplicate_intervals=duplicates,
            ambiguous_symbols=sum(len(values) > 1 for values in symbol_dates.values()),
            isin_continuity_breaks=sum(len(values) > 1 for values in isins.values()),
        )


__all__ = [
    "AmbiguousIdentityError",
    "HistoricalIdentityService",
    "IdentityAudit",
]
