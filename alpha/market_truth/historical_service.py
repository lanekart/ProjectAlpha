from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from alpha.data.downloader.bhavcopy import BhavcopyDownloader, DownloadedArchive
from alpha.data.providers.base import MarketDataProvider
from alpha.data.providers.nse import NSEArchiveBhavcopyProvider
from alpha.market_truth.models import (
    DatasetKind,
    MarketBar,
    MarketTruth,
    MarketTruthRequest,
    PriceHistoryMode,
    Provenance,
    canonical_json,
)
from alpha.market_truth.provider_router import MarketTruthProviderRouter


class HistoricalMarketTruthService:
    """Serve point-in-time historical bars through the MTE router only."""

    def __init__(self, router: MarketTruthProviderRouter) -> None:
        self.router = router

    def daily(
        self,
        *,
        symbols: tuple[str, ...] = (),
        start: date,
        end: date,
        as_of: date | None = None,
        provider_hint: str | None = None,
        price_mode: PriceHistoryMode = PriceHistoryMode.RAW,
        warehouse_version: str | None = None,
    ) -> MarketTruth:
        request = _request(
            DatasetKind.DAILY,
            symbols=symbols,
            start=start,
            end=end,
            as_of=as_of,
            provider_hint=provider_hint,
            price_mode=price_mode,
            warehouse_version=warehouse_version,
        )
        return self.router.route(request)

    def weekly(
        self,
        *,
        symbols: tuple[str, ...] = (),
        start: date,
        end: date,
        as_of: date | None = None,
        provider_hint: str | None = None,
        price_mode: PriceHistoryMode = PriceHistoryMode.RAW,
        warehouse_version: str | None = None,
    ) -> MarketTruth:
        daily = self.daily(
            symbols=symbols,
            start=start,
            end=end,
            as_of=as_of,
            provider_hint=provider_hint,
            price_mode=price_mode,
            warehouse_version=warehouse_version,
        )
        return _aggregate_truth(daily, DatasetKind.WEEKLY)

    def monthly(
        self,
        *,
        symbols: tuple[str, ...] = (),
        start: date,
        end: date,
        as_of: date | None = None,
        provider_hint: str | None = None,
        price_mode: PriceHistoryMode = PriceHistoryMode.RAW,
        warehouse_version: str | None = None,
    ) -> MarketTruth:
        daily = self.daily(
            symbols=symbols,
            start=start,
            end=end,
            as_of=as_of,
            provider_hint=provider_hint,
            price_mode=price_mode,
            warehouse_version=warehouse_version,
        )
        return _aggregate_truth(daily, DatasetKind.MONTHLY)


class MarketTruthArchiveDownloader:
    """Compatibility gateway that keeps provider ownership inside MTE."""

    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        data_dir: Path | None = None,
        *,
        provider_mode: str = "MTE_DEFAULT",
    ) -> None:
        resolved = provider
        if provider_mode == "NSE_OFFICIAL_ARCHIVE":
            resolved = NSEArchiveBhavcopyProvider()
        self._delegate = BhavcopyDownloader(provider=resolved, data_dir=data_dir)

    def download(self, target_date: date) -> Path:
        return self._delegate.download(target_date)

    def download_archive(self, target_date: date) -> DownloadedArchive:
        return self._delegate.download_archive(target_date)


def market_bars(truth: MarketTruth) -> tuple[MarketBar, ...]:
    return tuple(item for item in truth.records if isinstance(item, MarketBar))


def _request(
    dataset: DatasetKind,
    *,
    symbols: tuple[str, ...],
    start: date,
    end: date,
    as_of: date | None,
    provider_hint: str | None,
    price_mode: PriceHistoryMode = PriceHistoryMode.RAW,
    warehouse_version: str | None = None,
) -> MarketTruthRequest:
    if end < start:
        raise ValueError("historical market truth end cannot precede start")
    effective_as_of = as_of or end
    return MarketTruthRequest(
        dataset=dataset,
        symbols=symbols,
        start=datetime.combine(start, time.min, tzinfo=UTC),
        end=datetime.combine(end, time.max, tzinfo=UTC),
        as_of=datetime.combine(effective_as_of, time.max, tzinfo=UTC),
        provider_hint=provider_hint,
        price_mode=price_mode,
        warehouse_version=warehouse_version,
    )


def _aggregate_truth(daily: MarketTruth, interval: DatasetKind) -> MarketTruth:
    request = MarketTruthRequest(
        dataset=interval,
        symbols=daily.request.symbols,
        start=daily.request.start,
        end=daily.request.end,
        as_of=daily.request.as_of,
        provider_hint=daily.request.provider_hint,
        price_mode=daily.request.price_mode,
        warehouse_version=daily.request.warehouse_version,
    )
    bars = market_bars(daily)
    aggregated = tuple(
        _aggregate_group(group, interval) for group in _groups(bars, interval) if group
    )
    payload = {
        "request_id": request.request_id,
        "source_version": daily.version,
        "records": [
            f"{item.symbol}|{item.observed_at.isoformat()}|{item.close_price}"
            for item in aggregated
        ],
    }
    lineage = sha256(canonical_json(payload).encode()).hexdigest()
    provenance = Provenance(
        provenance_id="mte-provenance-" + lineage[:24],
        request_id=request.request_id,
        source=daily.source,
        provider_id=daily.provider,
        source_reference=f"Aggregated from {daily.version}",
        provider_checksum=daily.provenance.provider_checksum,
        lineage_hash=lineage,
        attempts=daily.provenance.attempts,
        generated_at=daily.timestamp,
    )
    return MarketTruth(
        request=request,
        records=aggregated,
        source=daily.source,
        provider=daily.provider,
        timestamp=daily.timestamp,
        evidence_class=daily.evidence_class,
        confidence=daily.confidence,
        quality=daily.quality,
        version=(f"{daily.version}-{interval.value.lower()}-{lineage[:12]}"),
        provenance=provenance,
        completeness=daily.completeness,
    )


def _groups(
    bars: tuple[MarketBar, ...],
    interval: DatasetKind,
) -> tuple[tuple[MarketBar, ...], ...]:
    grouped: dict[tuple[object, ...], list[MarketBar]] = {}
    for bar in bars:
        observed = bar.observed_at.date()
        if interval is DatasetKind.WEEKLY:
            iso = observed.isocalendar()
            key: tuple[object, ...] = (bar.symbol, iso.year, iso.week)
        else:
            key = (bar.symbol, observed.year, observed.month)
        grouped.setdefault(key, []).append(bar)
    return tuple(
        tuple(sorted(values, key=lambda item: item.observed_at))
        for _, values in sorted(grouped.items(), key=lambda item: item[0])
    )


def _aggregate_group(
    values: Iterable[MarketBar],
    interval: DatasetKind,
) -> MarketBar:
    bars = tuple(values)
    first = bars[0]
    last = bars[-1]
    return MarketBar(
        symbol=first.symbol,
        observed_at=last.observed_at,
        open_price=first.open_price,
        high_price=max(item.high_price for item in bars),
        low_price=min(item.low_price for item in bars),
        close_price=last.close_price,
        volume=sum((item.volume for item in bars), Decimal("0")),
        interval=interval,
        exchange=first.exchange,
        series=first.series,
    )


__all__ = [
    "HistoricalMarketTruthService",
    "MarketTruthArchiveDownloader",
    "DownloadedArchive",
    "market_bars",
]
