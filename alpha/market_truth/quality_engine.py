from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from alpha.market_truth.models import (
    DataQuality,
    DatasetKind,
    MarketBar,
    MarketTick,
    MarketTruthRecord,
    MarketTruthRequest,
    ProviderDataset,
    QualityAssessment,
)


class MarketTruthQualityEngine:
    """Validate structural truth without repairing or inventing provider data."""

    def assess(
        self,
        request: MarketTruthRequest,
        dataset: ProviderDataset | None,
    ) -> QualityAssessment:
        if dataset is None or not dataset.records:
            return QualityAssessment(
                quality=DataQuality.UNAVAILABLE,
                completeness=Decimal("0"),
                valid_records=0,
                rejected_records=0,
                reasons=("No provider returned market data.",),
            )
        reasons = list(dataset.warnings)
        invalid = sum(not _valid_record(request, record) for record in dataset.records)
        duplicates = len(dataset.records) - len(
            {_record_key(record) for record in dataset.records}
        )
        if invalid:
            reasons.append(f"{invalid} structurally invalid record(s).")
        if duplicates:
            reasons.append(f"{duplicates} duplicate record(s).")
        stale = _is_stale(request, dataset.records)
        if stale:
            reasons.append("Latest record exceeds the request freshness limit.")
        completeness = dataset.reported_completeness
        if invalid or duplicates or stale or completeness < Decimal("0.50"):
            quality = DataQuality.DEGRADED
        elif completeness < Decimal("0.95") or reasons:
            quality = DataQuality.PARTIAL
        else:
            quality = DataQuality.COMPLETE
        return QualityAssessment(
            quality=quality,
            completeness=completeness,
            valid_records=len(dataset.records) - invalid - duplicates,
            rejected_records=invalid + duplicates,
            reasons=tuple(reasons) or ("All structural quality checks passed.",),
        )


def _valid_record(request: MarketTruthRequest, record: MarketTruthRecord) -> bool:
    if isinstance(record, MarketBar):
        if request.dataset not in {
            DatasetKind.DAILY,
            DatasetKind.WEEKLY,
            DatasetKind.MONTHLY,
            DatasetKind.MINUTE_1,
            DatasetKind.MINUTE_5,
        }:
            return False
        if record.high_price < max(record.open_price, record.close_price):
            return False
        if record.low_price > min(record.open_price, record.close_price):
            return False
        if record.low_price < 0 or record.volume < 0:
            return False
        return _inside_time_window(request, record.observed_at)
    if isinstance(record, MarketTick):
        return (
            request.dataset is DatasetKind.TICK
            and record.last_price >= 0
            and _inside_time_window(request, record.observed_at)
        )
    return True


def _inside_time_window(request: MarketTruthRequest, observed_at: object) -> bool:
    if not isinstance(observed_at, datetime):
        return True
    if request.start is not None and observed_at < request.start:
        return False
    return request.end is None or observed_at <= request.end


def _is_stale(
    request: MarketTruthRequest,
    records: tuple[MarketTruthRecord, ...],
) -> bool:
    if request.maximum_age_seconds is None or request.as_of is None:
        return False
    timestamps = tuple(
        value
        for record in records
        if isinstance((value := getattr(record, "observed_at", None)), datetime)
    )
    if not timestamps:
        return True
    age_seconds = (request.as_of - max(timestamps)).total_seconds()
    return age_seconds > request.maximum_age_seconds


def _record_key(record: MarketTruthRecord) -> tuple[str, ...]:
    if isinstance(record, MarketBar):
        return (
            "BAR",
            record.symbol,
            record.interval.value,
            record.observed_at.isoformat(),
        )
    if isinstance(record, MarketTick):
        return ("TICK", record.symbol, record.observed_at.isoformat())
    return (record.__class__.__name__, repr(record))


__all__ = ["MarketTruthQualityEngine"]
