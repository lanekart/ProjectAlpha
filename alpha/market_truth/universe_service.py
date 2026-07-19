from __future__ import annotations

from datetime import UTC, date, datetime, time

from alpha.market_truth.models import (
    DatasetKind,
    MarketTruth,
    MarketTruthRequest,
    UniverseObservation,
)
from alpha.market_truth.provider_router import MarketTruthProviderRouter


class MarketUniverseService:
    def __init__(self, router: MarketTruthProviderRouter) -> None:
        self.router = router

    def resolve(
        self,
        *,
        as_of: date,
        symbols: tuple[str, ...] = (),
        provider_hint: str | None = None,
    ) -> MarketTruth:
        timestamp = datetime.combine(as_of, time.max, tzinfo=UTC)
        return self.router.route(
            MarketTruthRequest(
                dataset=DatasetKind.UNIVERSE,
                symbols=symbols,
                end=timestamp,
                as_of=timestamp,
                provider_hint=provider_hint,
            )
        )

    @staticmethod
    def observations(truth: MarketTruth) -> tuple[UniverseObservation, ...]:
        return tuple(
            item for item in truth.records if isinstance(item, UniverseObservation)
        )


__all__ = ["MarketUniverseService"]
