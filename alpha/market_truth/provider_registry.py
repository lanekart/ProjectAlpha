from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

import duckdb
import pandas as pd

from alpha.config import settings
from alpha.data.downloader.bhavcopy import BhavcopyDownloader
from alpha.data.ingestion.extractor import ArchiveExtractor
from alpha.data.ingestion.loader import CSVLoader
from alpha.data.ingestion.normalizer import Normalizer
from alpha.exceptions import ProjectAlphaError
from alpha.market_truth.cache_manager import MarketTruthCacheManager
from alpha.market_truth.models import (
    DatasetKind,
    EvidenceClass,
    MarketBar,
    MarketTruthRequest,
    ProviderClass,
    ProviderDataset,
    ProviderDescriptor,
)


class MarketTruthProviderError(RuntimeError):
    pass


class MarketTruthProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def fetch(self, request: MarketTruthRequest) -> ProviderDataset: ...


class MarketTruthProviderRegistry:
    """Deterministic plugin registry; core routing never names provider classes."""

    def __init__(self, providers: tuple[MarketTruthProvider, ...] = ()) -> None:
        self._providers: dict[str, MarketTruthProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: MarketTruthProvider) -> bool:
        provider_id = provider.descriptor.provider_id
        existing = self._providers.get(provider_id)
        if existing is not None:
            if existing.descriptor != provider.descriptor:
                raise ValueError(f"provider id {provider_id} has conflicting metadata")
            return False
        self._providers[provider_id] = provider
        return True

    def providers(
        self,
        dataset: DatasetKind | None = None,
    ) -> tuple[MarketTruthProvider, ...]:
        values = tuple(self._providers.values())
        if dataset is not None:
            values = tuple(
                item for item in values if dataset in item.descriptor.capabilities
            )
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.descriptor.priority,
                    item.descriptor.provider_id,
                ),
            )
        )

    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(item.descriptor for item in self.providers())

    def require(self, provider_id: str) -> MarketTruthProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"unknown market truth provider: {provider_id}") from exc


@dataclass(frozen=True, slots=True)
class UnavailableMarketTruthProvider:
    descriptor: ProviderDescriptor
    reason: str

    def fetch(self, request: MarketTruthRequest) -> ProviderDataset:
        del request
        raise MarketTruthProviderError(self.reason)


@dataclass(frozen=True, slots=True)
class StaticMarketTruthProvider:
    descriptor: ProviderDescriptor
    responder: Callable[[MarketTruthRequest], ProviderDataset]

    def fetch(self, request: MarketTruthRequest) -> ProviderDataset:
        return self.responder(request)


class LocalCanonicalStoreProvider:
    """Expose Alpha's persisted canonical prices as a cache provider plugin."""

    def __init__(self, database_path: Path | str | None = None) -> None:
        self.database_path = Path(database_path or settings.database_path)
        self._descriptor = ProviderDescriptor(
            provider_id="LOCAL_CANONICAL_CACHE",
            provider_class=ProviderClass.LOCAL_CACHE,
            display_name="Local Canonical Market Cache",
            capabilities=(DatasetKind.DAILY,),
            priority=90,
            authoritative=False,
            configured=self.database_path.exists(),
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def fetch(self, request: MarketTruthRequest) -> ProviderDataset:
        if request.dataset is not DatasetKind.DAILY:
            raise MarketTruthProviderError("local canonical cache supports daily data")
        if request.start is None or request.end is None:
            raise MarketTruthProviderError("daily request requires start and end")
        if not self.database_path.exists():
            raise MarketTruthProviderError("local canonical price database is absent")
        database = duckdb.connect(str(self.database_path), read_only=True)
        try:
            if request.symbols:
                placeholders = ", ".join("?" for _ in request.symbols)
                result = database.execute(
                    f"""
                    SELECT symbol, trade_date, open, high, low, close, volume,
                           sector, exchange
                    FROM daily_prices
                    WHERE UPPER(symbol) IN ({placeholders})
                      AND trade_date BETWEEN ? AND ?
                    ORDER BY symbol, trade_date
                    """,
                    (*request.symbols, request.start.date(), request.end.date()),
                )
            else:
                result = database.execute(
                    """
                    SELECT symbol, trade_date, open, high, low, close, volume,
                           sector, exchange
                    FROM daily_prices
                    WHERE trade_date BETWEEN ? AND ?
                    ORDER BY symbol, trade_date
                    """,
                    (request.start.date(), request.end.date()),
                )
            frame = pd.DataFrame(
                result.fetchall(),
                columns=(
                    "symbol",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "sector",
                    "exchange",
                ),
            )
            expected_row = database.execute(
                "SELECT COUNT(DISTINCT trade_date) FROM daily_prices "
                "WHERE trade_date BETWEEN ? AND ?",
                (request.start.date(), request.end.date()),
            ).fetchone()
            expected_sessions = int(
                expected_row[0] or 0 if expected_row is not None else 0
            )
        finally:
            database.close()
        records = _bars_from_frame(frame, interval=DatasetKind.DAILY)
        expected_records = expected_sessions * max(len(request.symbols), 1)
        completeness = (
            Decimal("0")
            if expected_records == 0
            else min(
                Decimal("1"),
                Decimal(len(records)) / Decimal(expected_records),
            )
        )
        return ProviderDataset(
            request_id=request.request_id,
            provider_id=self.descriptor.provider_id,
            source="Alpha canonical persisted price store",
            evidence_class=EvidenceClass.CACHED_AUTHORITATIVE,
            observed_at=request.as_of or request.end,
            records=records,
            reported_completeness=completeness,
            source_reference=str(self.database_path),
            warnings=() if records else ("No matching persisted prices.",),
        )


class DeterministicCacheProvider:
    def __init__(self, cache: MarketTruthCacheManager) -> None:
        self.cache = cache
        self._descriptor = ProviderDescriptor(
            provider_id="LOCAL_VERSIONED_CACHE",
            provider_class=ProviderClass.LOCAL_CACHE,
            display_name="Local Versioned Market Truth Cache",
            capabilities=tuple(DatasetKind),
            priority=95,
            authoritative=False,
            configured=True,
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def fetch(self, request: MarketTruthRequest) -> ProviderDataset:
        dataset = self.cache.get(request)
        if dataset is None:
            raise MarketTruthProviderError("versioned market truth cache miss")
        return ProviderDataset(
            request_id=dataset.request_id,
            provider_id=self.descriptor.provider_id,
            source=f"Cached copy of {dataset.source}",
            evidence_class=(
                EvidenceClass.CACHED_AUTHORITATIVE
                if dataset.evidence_class
                in {EvidenceClass.AUTHORITATIVE, EvidenceClass.LICENSED}
                else dataset.evidence_class
            ),
            observed_at=dataset.observed_at,
            records=dataset.records,
            reported_completeness=dataset.reported_completeness,
            source_reference=f"cache:{dataset.checksum}",
            warnings=dataset.warnings,
        )


class NSEOfficialProvider:
    """MTE-owned adapter for current and historical official NSE bhavcopies."""

    def __init__(self, downloader: BhavcopyDownloader | None = None) -> None:
        self.downloader = downloader or BhavcopyDownloader()
        self._descriptor = ProviderDescriptor(
            provider_id="NSE_OFFICIAL",
            provider_class=ProviderClass.NSE_OFFICIAL,
            display_name="NSE Official",
            capabilities=(DatasetKind.DAILY,),
            priority=10,
            authoritative=True,
            configured=True,
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def fetch(self, request: MarketTruthRequest) -> ProviderDataset:
        if request.dataset is not DatasetKind.DAILY:
            raise MarketTruthProviderError("NSE official adapter supports daily bars")
        if request.start is None or request.end is None:
            raise MarketTruthProviderError("NSE daily request requires start and end")
        dates = tuple(_weekdays(request.start.date(), request.end.date()))
        frames: list[pd.DataFrame] = []
        failures: list[str] = []
        for trading_day in dates:
            try:
                archive = self.downloader.download_archive(trading_day)
                extracted = ArchiveExtractor().extract(archive.path)
                frame = Normalizer().transform(CSVLoader().load(extracted))
                frames.append(frame)
            except (OSError, ProjectAlphaError, RuntimeError, ValueError) as exc:
                failures.append(f"{trading_day.isoformat()}: {exc}")
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        records = _bars_from_frame(frame, interval=DatasetKind.DAILY)
        if request.symbols:
            records = tuple(item for item in records if item.symbol in request.symbols)
        completeness = (
            Decimal("0")
            if not dates
            else Decimal(len({item.observed_at.date() for item in records}))
            / Decimal(len(dates))
        )
        if not records:
            raise MarketTruthProviderError(
                "NSE official returned no usable records"
                + (f"; failures={'; '.join(failures)}" if failures else "")
            )
        return ProviderDataset(
            request_id=request.request_id,
            provider_id=self.descriptor.provider_id,
            source="NSE official bhavcopy",
            evidence_class=EvidenceClass.AUTHORITATIVE,
            observed_at=request.as_of or request.end,
            records=records,
            reported_completeness=min(Decimal("1"), completeness),
            source_reference="NSE official current/archive endpoints",
            warnings=tuple(failures),
        )


def default_provider_registry(
    *,
    cache: MarketTruthCacheManager | None = None,
    include_remote: bool = False,
    database_path: Path | str | None = None,
    warehouse_path: Path | str | None = None,
) -> MarketTruthProviderRegistry:
    manager = cache or MarketTruthCacheManager()
    providers: list[MarketTruthProvider] = []
    resolved_warehouse = Path(warehouse_path or "data/market_truth")
    if (resolved_warehouse / "warehouse.duckdb").exists():
        from alpha.market_truth.warehouse.models import WarehousePaths
        from alpha.market_truth.warehouse.providers import (
            warehouse_market_truth_providers,
        )

        providers.extend(
            warehouse_market_truth_providers(WarehousePaths(resolved_warehouse))
        )
    providers.append(
        NSEOfficialProvider()
        if include_remote
        else _unconfigured(
            "NSE_OFFICIAL",
            ProviderClass.NSE_OFFICIAL,
            "NSE Official",
            (DatasetKind.DAILY,),
            10,
            "Remote provider access is disabled for this MTE instance.",
        )
    )
    providers.extend(
        (
            _unconfigured(
                "BSE_OFFICIAL",
                ProviderClass.BSE_OFFICIAL,
                "BSE Official",
                (
                    DatasetKind.DAILY,
                    DatasetKind.IDENTITY,
                    DatasetKind.CORPORATE_ACTIONS,
                ),
                20,
                "BSE official adapter is not configured.",
            ),
            _unconfigured(
                "LICENSED_HISTORICAL_ARCHIVE",
                ProviderClass.LICENSED_HISTORICAL_ARCHIVE,
                "Licensed Historical Archive",
                (
                    DatasetKind.DAILY,
                    DatasetKind.IDENTITY,
                    DatasetKind.CORPORATE_ACTIONS,
                    DatasetKind.CALENDAR,
                    DatasetKind.INDEX,
                    DatasetKind.FUNDAMENTAL,
                ),
                30,
                "No licensed historical archive is configured.",
            ),
            _unconfigured(
                "LICENSED_LIVE_FEED",
                ProviderClass.LICENSED_LIVE_FEED,
                "Licensed Live Feed",
                (DatasetKind.TICK, DatasetKind.MINUTE_1, DatasetKind.MINUTE_5),
                40,
                "No licensed live feed is configured.",
            ),
            _unconfigured(
                "BROKER_FEED_FALLBACK",
                ProviderClass.BROKER_FALLBACK,
                "Broker Feed (Fallback)",
                (DatasetKind.TICK, DatasetKind.MINUTE_1, DatasetKind.MINUTE_5),
                50,
                (
                    "Broker feed is unavailable."
                    if not os.environ.get("UPSTOX_ACCESS_TOKEN")
                    else "Broker MTE adapter requires a bounded feed capture."
                ),
            ),
            LocalCanonicalStoreProvider(database_path),
            DeterministicCacheProvider(manager),
        )
    )
    return MarketTruthProviderRegistry(tuple(providers))


def _unconfigured(
    provider_id: str,
    provider_class: ProviderClass,
    name: str,
    capabilities: tuple[DatasetKind, ...],
    priority: int,
    reason: str,
) -> UnavailableMarketTruthProvider:
    return UnavailableMarketTruthProvider(
        descriptor=ProviderDescriptor(
            provider_id=provider_id,
            provider_class=provider_class,
            display_name=name,
            capabilities=capabilities,
            priority=priority,
            authoritative=provider_class
            in {ProviderClass.NSE_OFFICIAL, ProviderClass.BSE_OFFICIAL},
            configured=False,
        ),
        reason=reason,
    )


def _bars_from_frame(
    frame: pd.DataFrame,
    *,
    interval: DatasetKind,
) -> tuple[MarketBar, ...]:
    if frame.empty:
        return ()
    bars: list[MarketBar] = []
    for row in frame.itertuples(index=False):
        observed = cast(date, row.trade_date)
        bars.append(
            MarketBar(
                symbol=str(row.symbol),
                observed_at=datetime.combine(observed, time.min, tzinfo=UTC),
                open_price=Decimal(str(row.open)),
                high_price=Decimal(str(row.high)),
                low_price=Decimal(str(row.low)),
                close_price=Decimal(str(row.close)),
                volume=Decimal(str(row.volume)),
                interval=interval,
                exchange=str(getattr(row, "exchange", "NSE")),
                series=cast(str | None, getattr(row, "series", None)),
            )
        )
    return tuple(sorted(bars, key=lambda item: (item.symbol, item.observed_at)))


def _weekdays(start: date, end: date) -> tuple[date, ...]:
    values: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return tuple(values)


__all__ = [
    "DeterministicCacheProvider",
    "LocalCanonicalStoreProvider",
    "MarketTruthProvider",
    "MarketTruthProviderError",
    "MarketTruthProviderRegistry",
    "NSEOfficialProvider",
    "StaticMarketTruthProvider",
    "UnavailableMarketTruthProvider",
    "default_provider_registry",
]
