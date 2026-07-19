from __future__ import annotations

from datetime import UTC, date, datetime, time

from alpha.market_truth.models import DatasetKind, MarketTruth, MarketTruthRequest
from alpha.market_truth.provider_router import MarketTruthProviderRouter


class IndexMarketTruthService:
    def __init__(self, router: MarketTruthProviderRouter) -> None:
        self.router = router

    def history(
        self,
        *,
        indices: tuple[str, ...],
        start: date,
        end: date,
        as_of: date,
    ) -> MarketTruth:
        return self.router.route(
            MarketTruthRequest(
                dataset=DatasetKind.INDEX,
                symbols=indices,
                start=datetime.combine(start, time.min, tzinfo=UTC),
                end=datetime.combine(end, time.max, tzinfo=UTC),
                as_of=datetime.combine(as_of, time.max, tzinfo=UTC),
            )
        )


__all__ = ["IndexMarketTruthService"]
