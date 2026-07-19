from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from alpha.market_truth.cache_manager import MarketTruthCacheManager
from alpha.market_truth.calendar_service import TradingCalendarService
from alpha.market_truth.corporate_action_service import CorporateActionService
from alpha.market_truth.fundamental_service import FundamentalMarketTruthService
from alpha.market_truth.historical_service import HistoricalMarketTruthService
from alpha.market_truth.identity_service import MarketIdentityService
from alpha.market_truth.index_service import IndexMarketTruthService
from alpha.market_truth.intraday_service import IntradayMarketTruthService
from alpha.market_truth.models import (
    MarketTruthSystemReport,
    ProviderHealthReport,
    ProviderHealthState,
)
from alpha.market_truth.provider_health import ProviderHealthMonitor
from alpha.market_truth.provider_registry import (
    MarketTruthProviderRegistry,
    default_provider_registry,
)
from alpha.market_truth.provider_router import MarketTruthProviderRouter
from alpha.market_truth.universe_service import MarketUniverseService


class MarketTruthEngine:
    """Single consumer-facing source for all Project Alpha market truth."""

    def __init__(
        self,
        *,
        registry: MarketTruthProviderRegistry,
        cache: MarketTruthCacheManager,
        health_monitor: ProviderHealthMonitor,
    ) -> None:
        self.registry = registry
        self.cache = cache
        self.health_monitor = health_monitor
        self.router = MarketTruthProviderRouter(
            registry=registry,
            cache=cache,
            health=health_monitor,
        )
        self.historical = HistoricalMarketTruthService(self.router)
        self.intraday = IntradayMarketTruthService(self.router)
        self.identity = MarketIdentityService(self.router)
        self.corporate_actions = CorporateActionService(self.router)
        self.calendar = TradingCalendarService(self.router)
        self.indices = IndexMarketTruthService(self.router)
        self.fundamentals = FundamentalMarketTruthService(self.router)
        self.universe = MarketUniverseService(self.router)

    @classmethod
    def default(
        cls,
        *,
        include_remote: bool = False,
        cache_path: Path | str | None = None,
        health_path: Path | str | None = None,
        database_path: Path | str | None = None,
        warehouse_path: Path | str | None = None,
    ) -> MarketTruthEngine:
        cache = MarketTruthCacheManager(cache_path)
        registry = default_provider_registry(
            cache=cache,
            include_remote=include_remote,
            database_path=database_path,
            warehouse_path=warehouse_path,
        )
        return cls(
            registry=registry,
            cache=cache,
            health_monitor=ProviderHealthMonitor(health_path),
        )

    def health(self, *, generated_at: datetime | None = None) -> ProviderHealthReport:
        return self.health_monitor.report(
            self.registry.descriptors(),
            generated_at=generated_at,
        )

    def report(
        self, *, generated_at: datetime | None = None
    ) -> MarketTruthSystemReport:
        now = generated_at or datetime.now(tz=UTC)
        health = self.health(generated_at=now)
        return MarketTruthSystemReport(
            generated_at=now,
            provider_count=len(self.registry.descriptors()),
            configured_providers=sum(
                item.configured for item in self.registry.descriptors()
            ),
            healthy_providers=sum(
                item.state is ProviderHealthState.HEALTHY for item in health.providers
            ),
            degraded_providers=sum(
                item.state is ProviderHealthState.DEGRADED for item in health.providers
            ),
            unavailable_providers=sum(
                item.state
                in {
                    ProviderHealthState.UNAVAILABLE,
                    ProviderHealthState.UNCONFIGURED,
                }
                for item in health.providers
            ),
            cached_datasets=self.cache.count(),
            schema_version="market-truth-v1",
        )

    def bars_for_symbol(
        self,
        *,
        symbol: str,
        start: date,
        end: date,
    ) -> tuple[object, ...]:
        """Compatibility read used by migrated lifecycle consumers."""

        return self.historical.daily(
            symbols=(symbol,), start=start, end=end, as_of=end
        ).records


__all__ = ["MarketTruthEngine"]
