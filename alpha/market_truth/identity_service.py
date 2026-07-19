from __future__ import annotations

from datetime import UTC, date, datetime, time

from alpha.market_truth.models import (
    DatasetKind,
    MarketTruth,
    MarketTruthRequest,
    SecurityIdentity,
)
from alpha.market_truth.provider_router import MarketTruthProviderRouter


class MarketIdentityService:
    def __init__(self, router: MarketTruthProviderRouter) -> None:
        self.router = router

    def resolve(
        self,
        *,
        symbols: tuple[str, ...] = (),
        as_of: date,
    ) -> MarketTruth:
        timestamp = datetime.combine(as_of, time.max, tzinfo=UTC)
        return self.router.route(
            MarketTruthRequest(
                dataset=DatasetKind.IDENTITY,
                symbols=symbols,
                end=timestamp,
                as_of=timestamp,
            )
        )

    def identities(
        self,
        *,
        symbols: tuple[str, ...] = (),
        as_of: date,
    ) -> tuple[SecurityIdentity, ...]:
        truth = self.resolve(symbols=symbols, as_of=as_of)
        return tuple(
            item for item in truth.records if isinstance(item, SecurityIdentity)
        )


__all__ = ["MarketIdentityService"]
