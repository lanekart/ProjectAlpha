from __future__ import annotations

from datetime import datetime

from alpha.market_truth.models import DatasetKind, MarketTruth, MarketTruthRequest
from alpha.market_truth.provider_router import MarketTruthProviderRouter


class IntradayMarketTruthService:
    def __init__(self, router: MarketTruthProviderRouter) -> None:
        self.router = router

    def ticks(
        self,
        *,
        symbols: tuple[str, ...],
        start: datetime,
        end: datetime,
        as_of: datetime,
    ) -> MarketTruth:
        return self._fetch(
            DatasetKind.TICK, symbols, start, end, as_of, maximum_age_seconds=60
        )

    def one_minute(
        self,
        *,
        symbols: tuple[str, ...],
        start: datetime,
        end: datetime,
        as_of: datetime,
    ) -> MarketTruth:
        return self._fetch(
            DatasetKind.MINUTE_1,
            symbols,
            start,
            end,
            as_of,
            maximum_age_seconds=120,
        )

    def five_minute(
        self,
        *,
        symbols: tuple[str, ...],
        start: datetime,
        end: datetime,
        as_of: datetime,
    ) -> MarketTruth:
        return self._fetch(
            DatasetKind.MINUTE_5,
            symbols,
            start,
            end,
            as_of,
            maximum_age_seconds=600,
        )

    def _fetch(
        self,
        dataset: DatasetKind,
        symbols: tuple[str, ...],
        start: datetime,
        end: datetime,
        as_of: datetime,
        maximum_age_seconds: int,
    ) -> MarketTruth:
        return self.router.route(
            MarketTruthRequest(
                dataset=dataset,
                symbols=symbols,
                start=start,
                end=end,
                as_of=as_of,
                maximum_age_seconds=maximum_age_seconds,
            )
        )


__all__ = ["IntradayMarketTruthService"]
