from __future__ import annotations

from datetime import date

from alpha.market_truth.warehouse.models import (
    Exchange,
    IdentityRecord,
    UniverseMembership,
    stable_hash,
)
from alpha.market_truth.warehouse.storage import WarehouseStore


class PointInTimeUniverseService:
    def __init__(self, store: WarehouseStore) -> None:
        self.store = store

    def materialise(
        self,
        *,
        session_date: date,
        exchange: Exchange,
        identity_version: str,
    ) -> tuple[UniverseMembership, ...]:
        identities = tuple(
            item
            for item in self.store.identity_records(exchange=exchange)
            if _valid(item, session_date)
        )
        universe_version = (
            "universe-"
            + stable_hash(
                {
                    "date": session_date,
                    "exchange": exchange.value,
                    "identity_version": identity_version,
                    "securities": sorted(item.security_id for item in identities),
                }
            )[:20]
        )
        records = tuple(
            _membership(item, session_date, identity_version, universe_version)
            for item in identities
        )
        with self.store.transaction() as database:
            self.store.replace_universe(
                records,
                session_date=session_date,
                exchange=exchange,
                database=database,
            )
        return records

    def query(self, session_date: date) -> tuple[UniverseMembership, ...]:
        return self.store.universe(session_date=session_date)


def _valid(identity: IdentityRecord, session_date: date) -> bool:
    if identity.symbol_valid_from > session_date:
        return False
    if identity.symbol_valid_to is not None and session_date > identity.symbol_valid_to:
        return False
    if identity.listing_date is not None and session_date < identity.listing_date:
        return False
    return identity.delisting_date is None or session_date <= identity.delisting_date


def _membership(
    identity: IdentityRecord,
    session_date: date,
    identity_version: str,
    universe_version: str,
) -> UniverseMembership:
    suspended = any(
        start <= session_date and (end is None or session_date <= end)
        for start, end in identity.suspension_intervals
    )
    eligible_series = identity.series in {None, "EQ", "BE", "A", "B", "T"}
    tradable = not suspended and eligible_series
    reason = (
        "Eligible point-in-time listed security."
        if tradable
        else "Suspended on this date."
        if suspended
        else f"Series {identity.series} is outside the configured research universe."
    )
    return UniverseMembership(
        trading_date=session_date,
        exchange=identity.exchange,
        security_id=identity.security_id,
        symbol=identity.symbol,
        series=identity.series,
        listed=True,
        suspended=suspended,
        tradable=tradable,
        eligible_for_research=tradable,
        eligibility_reason=reason,
        identity_version=identity_version,
        universe_version=universe_version,
    )


__all__ = ["PointInTimeUniverseService"]
