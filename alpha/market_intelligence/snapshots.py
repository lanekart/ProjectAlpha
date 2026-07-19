from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from alpha.market_intelligence.benchmark import (
    BenchmarkAlignment,
    BenchmarkFeatureCompleteness,
    BenchmarkState,
    canonical_benchmark_configuration,
)
from alpha.market_intelligence.intelligence import MarketIntelligenceReport

MARKET_STATE_CLASSIFIER_VERSION = "market-intelligence-composite-v1"
MARKET_STATE_SNAPSHOT_SCHEMA_VERSION = "1.0"
DEFAULT_MARKET_STATE_SNAPSHOT_PATH = Path(".alpha/market_state_snapshots.json")


class MarketStateInputCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    MINIMUM_VIABLE = "MINIMUM_VIABLE"
    INSUFFICIENT = "INSUFFICIENT"
    UNAVAILABLE = "UNAVAILABLE"


class MarketStateFallbackReason(StrEnum):
    NONE = "NONE"
    BENCHMARK_NOT_CONFIGURED = "BENCHMARK_NOT_CONFIGURED"
    BENCHMARK_MAPPING_MISSING = "BENCHMARK_MAPPING_MISSING"
    BENCHMARK_HISTORY_UNAVAILABLE = "BENCHMARK_HISTORY_UNAVAILABLE"
    BENCHMARK_LOOKBACK_INSUFFICIENT = "BENCHMARK_LOOKBACK_INSUFFICIENT"
    BENCHMARK_LATEST_BAR_STALE = "BENCHMARK_LATEST_BAR_STALE"
    BENCHMARK_TIMESTAMP_INVALID = "BENCHMARK_TIMESTAMP_INVALID"
    BENCHMARK_FEATURE_BUILD_FAILED = "BENCHMARK_FEATURE_BUILD_FAILED"
    MISSING_BENCHMARK_INPUT = "MISSING_BENCHMARK_INPUT"
    MISSING_BREADTH_INPUT = "MISSING_BREADTH_INPUT"
    MISSING_VOLATILITY_INPUT = "MISSING_VOLATILITY_INPUT"
    MISSING_PARTICIPATION_INPUT = "MISSING_PARTICIPATION_INPUT"
    MISSING_SECTOR_INPUT = "MISSING_SECTOR_INPUT"
    INSUFFICIENT_LOOKBACK = "INSUFFICIENT_LOOKBACK"
    STALE_SOURCE_DATA = "STALE_SOURCE_DATA"
    CLASSIFIER_INPUT_UNAVAILABLE = "CLASSIFIER_INPUT_UNAVAILABLE"
    CLASSIFIER_EXCEPTION = "CLASSIFIER_EXCEPTION"
    DEFAULT_NEUTRAL = "DEFAULT_NEUTRAL"
    UNKNOWN = "UNKNOWN"


class MarketStatePersistenceStatus(StrEnum):
    SNAPSHOT_PERSISTED = "SNAPSHOT_PERSISTED"
    SNAPSHOT_ALREADY_EXISTS = "SNAPSHOT_ALREADY_EXISTS"
    SNAPSHOT_PERSISTENCE_FAILED = "SNAPSHOT_PERSISTENCE_FAILED"
    SNAPSHOT_UNAVAILABLE = "SNAPSHOT_UNAVAILABLE"


class MarketStateBackfillPlanStatus(StrEnum):
    AUTHORITATIVE_SOURCE_AVAILABLE = "AUTHORITATIVE_SOURCE_AVAILABLE"
    FULLY_RECONSTRUCTABLE = "FULLY_RECONSTRUCTABLE"
    PARTIALLY_RECONSTRUCTABLE = "PARTIALLY_RECONSTRUCTABLE"
    INSUFFICIENT_SOURCE_DATA = "INSUFFICIENT_SOURCE_DATA"
    NO_BENCHMARK_HISTORY = "NO_BENCHMARK_HISTORY"
    NO_BREADTH_HISTORY = "NO_BREADTH_HISTORY"
    NO_MARKET_DATE = "NO_MARKET_DATE"


@dataclass(frozen=True, slots=True)
class ClassifierInputRecord:
    name: str
    value: str | None
    available: bool
    source: str
    input_timestamp: datetime | None
    staleness_days: int | None
    fallback_status: str

    def __post_init__(self) -> None:
        name = self.name.strip()
        source = self.source.strip()
        fallback_status = self.fallback_status.strip().upper()
        if not name:
            raise ValueError("classifier input name cannot be empty")
        if not source:
            raise ValueError("classifier input source cannot be empty")
        if self.staleness_days is not None and self.staleness_days < 0:
            raise ValueError("classifier input staleness cannot be negative")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value", _optional_text(self.value))
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "fallback_status", fallback_status)
        object.__setattr__(
            self,
            "input_timestamp",
            None if self.input_timestamp is None else _aware(self.input_timestamp),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "available": self.available,
            "source": self.source,
            "input_timestamp": (
                None
                if self.input_timestamp is None
                else self.input_timestamp.isoformat()
            ),
            "staleness_days": self.staleness_days,
            "fallback_status": self.fallback_status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ClassifierInputRecord:
        timestamp = payload.get("input_timestamp")
        return cls(
            name=str(payload["name"]),
            value=_payload_optional_text(payload.get("value")),
            available=bool(payload["available"]),
            source=str(payload["source"]),
            input_timestamp=(
                None if timestamp is None else datetime.fromisoformat(str(timestamp))
            ),
            staleness_days=(
                None
                if payload.get("staleness_days") is None
                else int(payload["staleness_days"])
            ),
            fallback_status=str(payload["fallback_status"]),
        )


@dataclass(frozen=True, slots=True)
class MarketStateSnapshot:
    snapshot_id: str
    market_date: date
    as_of_timestamp: datetime
    source_timestamp: datetime
    created_at: datetime
    benchmark_symbol: str
    benchmark_source: str
    benchmark_close: Decimal | None
    benchmark_return_1d: Decimal | None
    benchmark_return_5d: Decimal | None
    benchmark_return_20d: Decimal | None
    benchmark_dma_20: Decimal | None
    benchmark_dma_50: Decimal | None
    benchmark_dma_200: Decimal | None
    benchmark_above_20dma: bool | None
    benchmark_above_50dma: bool | None
    benchmark_above_200dma: bool | None
    benchmark_distance_20dma: Decimal | None
    benchmark_distance_50dma: Decimal | None
    benchmark_distance_200dma: Decimal | None
    benchmark_atr: Decimal | None
    benchmark_volatility: Decimal | None
    benchmark_latest_bar_timestamp: datetime | None
    benchmark_alignment: str | None
    benchmark_bars_available: int | None
    breadth_advancers: int | None
    breadth_decliners: int | None
    breadth_unchanged: int | None
    breadth_ratio: Decimal | None
    percent_above_20dma: Decimal | None
    percent_above_50dma: Decimal | None
    percent_above_200dma: Decimal | None
    new_highs: int | None
    new_lows: int | None
    sector_leader: str | None
    sector_laggard: str | None
    sector_dispersion: Decimal | None
    market_trend_score: Decimal | None
    breadth_score: Decimal | None
    volatility_score: Decimal | None
    participation_score: Decimal | None
    classifier_regime: str
    classifier_confidence: Decimal | None
    classifier_version: str
    input_completeness: MarketStateInputCompleteness
    fallback_applied: bool
    fallback_reason: MarketStateFallbackReason
    missing_fields: tuple[str, ...]
    source_lineage: tuple[str, ...]
    classifier_inputs: tuple[ClassifierInputRecord, ...]
    provenance_id: str | None = None
    market_classifier_version: str | None = None
    market_classifier_fingerprint: str | None = None
    benchmark_builder_version: str | None = None
    market_feature_definition_version: str | None = None
    fallback_policy_version: str | None = None
    schema_version: str = MARKET_STATE_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id cannot be empty")
        if not self.benchmark_symbol.strip():
            raise ValueError("benchmark_symbol cannot be empty")
        if not self.benchmark_source.strip():
            raise ValueError("benchmark_source cannot be empty")
        if not self.classifier_regime.strip():
            raise ValueError("classifier_regime cannot be empty")
        if not self.classifier_version.strip():
            raise ValueError("classifier_version cannot be empty")
        as_of = _aware(self.as_of_timestamp)
        source = _aware(self.source_timestamp)
        created = _aware(self.created_at)
        if source > as_of:
            raise ValueError("source_timestamp cannot be after as_of_timestamp")
        if created < source:
            raise ValueError("created_at cannot be before source_timestamp")
        for field_name in (
            "breadth_advancers",
            "breadth_decliners",
            "breadth_unchanged",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} cannot be negative")
        if self.benchmark_close is not None and self.benchmark_close <= Decimal("0"):
            raise ValueError("benchmark_close must be positive when available")
        if (
            self.fallback_applied
            and self.fallback_reason is MarketStateFallbackReason.NONE
        ):
            raise ValueError("fallback_applied requires a non-NONE fallback_reason")
        if (
            not self.fallback_applied
            and self.fallback_reason is not MarketStateFallbackReason.NONE
        ):
            raise ValueError(
                "fallback_reason must be NONE when no fallback was applied"
            )
        object.__setattr__(self, "snapshot_id", self.snapshot_id.strip())
        object.__setattr__(self, "as_of_timestamp", as_of)
        object.__setattr__(self, "source_timestamp", source)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(
            self,
            "benchmark_latest_bar_timestamp",
            (
                None
                if self.benchmark_latest_bar_timestamp is None
                else _aware(self.benchmark_latest_bar_timestamp)
            ),
        )
        object.__setattr__(
            self,
            "benchmark_alignment",
            _optional_text(self.benchmark_alignment),
        )
        if (
            self.benchmark_bars_available is not None
            and self.benchmark_bars_available < 0
        ):
            raise ValueError("benchmark_bars_available cannot be negative")
        object.__setattr__(
            self,
            "benchmark_symbol",
            self.benchmark_symbol.strip().upper(),
        )
        object.__setattr__(self, "benchmark_source", self.benchmark_source.strip())
        object.__setattr__(
            self,
            "classifier_regime",
            self.classifier_regime.strip().upper(),
        )
        object.__setattr__(self, "classifier_version", self.classifier_version.strip())
        object.__setattr__(
            self,
            "missing_fields",
            tuple(
                sorted(field.strip() for field in self.missing_fields if field.strip())
            ),
        )
        object.__setattr__(
            self,
            "source_lineage",
            tuple(item.strip() for item in self.source_lineage if item.strip()),
        )
        object.__setattr__(
            self,
            "classifier_inputs",
            tuple(sorted(self.classifier_inputs, key=lambda item: item.name)),
        )
        object.__setattr__(self, "provenance_id", _optional_text(self.provenance_id))
        object.__setattr__(
            self,
            "market_classifier_version",
            _optional_text(self.market_classifier_version) or self.classifier_version,
        )
        object.__setattr__(
            self,
            "market_classifier_fingerprint",
            _optional_text(self.market_classifier_fingerprint),
        )
        object.__setattr__(
            self,
            "benchmark_builder_version",
            _optional_text(self.benchmark_builder_version),
        )
        object.__setattr__(
            self,
            "market_feature_definition_version",
            _optional_text(self.market_feature_definition_version),
        )
        object.__setattr__(
            self,
            "fallback_policy_version",
            _optional_text(self.fallback_policy_version),
        )

    @classmethod
    def from_market_report(
        cls,
        report: MarketIntelligenceReport,
        *,
        as_of_timestamp: datetime,
        created_at: datetime | None = None,
        classifier_version: str = MARKET_STATE_CLASSIFIER_VERSION,
        benchmark_state: BenchmarkState | None = None,
        provenance: object | None = None,
    ) -> MarketStateSnapshot:
        as_of = _aware(as_of_timestamp)
        created = _aware(created_at or datetime.now(tz=UTC))
        source_timestamp = as_of
        advancers = _reason_int(report.breadth.reasons, "advances")
        decliners = _reason_int(report.breadth.reasons, "declines")
        unchanged = _reason_int(report.breadth.reasons, "unchanged")
        breadth_ratio = report.breadth.metrics.get("advance_ratio")
        sector_leaders = report.sector_rotation.leaders
        leader = sector_leaders[0].sector if sector_leaders else None
        laggard = sector_leaders[-1].sector if sector_leaders else None
        dispersion = None
        if sector_leaders:
            scores = tuple(item.score for item in sector_leaders)
            dispersion = max(scores) - min(scores)
        missing = list(_benchmark_missing_fields(benchmark_state))
        if breadth_ratio is None:
            missing.append("breadth_ratio")
        if not sector_leaders:
            missing.append("sector_leadership")
        completeness = _snapshot_completeness(
            missing=missing,
            benchmark_state=benchmark_state,
        )
        fallback_reason = _benchmark_fallback_reason(
            report=report,
            benchmark_state=benchmark_state,
            missing=tuple(missing),
        )
        benchmark_timestamp = (
            as_of
            if benchmark_state is None or benchmark_state.latest_bar_timestamp is None
            else benchmark_state.latest_bar_timestamp
        )
        inputs = (
            _input_record("accumulation_score", report.accumulation.score, as_of),
            _input_record("distribution_score", report.distribution.score, as_of),
            _input_record("liquidity_score", report.liquidity.score, as_of),
            _input_record("breadth_score", report.breadth.score, as_of),
            _input_record("sector_rotation_score", report.sector_rotation.score, as_of),
            _input_record("correlation_score", report.correlation.score, as_of),
            _input_record(
                "benchmark_close",
                None if benchmark_state is None else benchmark_state.benchmark_close,
                benchmark_timestamp,
            ),
            _input_record(
                "benchmark_return_20d",
                None
                if benchmark_state is None
                else benchmark_state.benchmark_return_20d,
                benchmark_timestamp,
            ),
            _input_record(
                "benchmark_dma_50",
                None if benchmark_state is None else benchmark_state.benchmark_dma_50,
                benchmark_timestamp,
            ),
        )
        lineage = (
            "MarketIntelligenceReport",
            "MarketIntelligenceCompositeEngine",
            _benchmark_lineage(benchmark_state),
            f"classifier_version:{classifier_version}",
        )
        benchmark_symbol = (
            report.symbol
            if benchmark_state is None
            else benchmark_state.configuration.provider_symbol
        )
        snapshot_id = market_state_snapshot_id(
            market_date=report.observed_on,
            as_of_timestamp=as_of,
            benchmark_symbol=benchmark_symbol,
            classifier_version=classifier_version,
            classifier_regime=report.bias.value,
            source_lineage=lineage,
        )
        return cls(
            snapshot_id=snapshot_id,
            market_date=report.observed_on,
            as_of_timestamp=as_of,
            source_timestamp=source_timestamp,
            created_at=created,
            benchmark_symbol=benchmark_symbol,
            benchmark_source=(
                "market-intelligence-report"
                if benchmark_state is None
                else "local_daily_prices"
            ),
            benchmark_close=(
                None if benchmark_state is None else benchmark_state.benchmark_close
            ),
            benchmark_return_1d=(
                None if benchmark_state is None else benchmark_state.benchmark_return_1d
            ),
            benchmark_return_5d=(
                None if benchmark_state is None else benchmark_state.benchmark_return_5d
            ),
            benchmark_return_20d=(
                None
                if benchmark_state is None
                else benchmark_state.benchmark_return_20d
            ),
            benchmark_dma_20=(
                None if benchmark_state is None else benchmark_state.benchmark_dma_20
            ),
            benchmark_dma_50=(
                None if benchmark_state is None else benchmark_state.benchmark_dma_50
            ),
            benchmark_dma_200=(
                None if benchmark_state is None else benchmark_state.benchmark_dma_200
            ),
            benchmark_above_20dma=(
                None
                if benchmark_state is None
                else benchmark_state.benchmark_above_20dma
            ),
            benchmark_above_50dma=(
                None
                if benchmark_state is None
                else benchmark_state.benchmark_above_50dma
            ),
            benchmark_above_200dma=(
                None
                if benchmark_state is None
                else benchmark_state.benchmark_above_200dma
            ),
            benchmark_distance_20dma=(
                None
                if benchmark_state is None
                else benchmark_state.benchmark_distance_20dma
            ),
            benchmark_distance_50dma=(
                None
                if benchmark_state is None
                else benchmark_state.benchmark_distance_50dma
            ),
            benchmark_distance_200dma=(
                None
                if benchmark_state is None
                else benchmark_state.benchmark_distance_200dma
            ),
            benchmark_atr=(
                None if benchmark_state is None else benchmark_state.benchmark_atr_14
            ),
            benchmark_volatility=(
                report.liquidity.metrics.get("volatility_penalty")
                if benchmark_state is None
                else benchmark_state.benchmark_volatility
            ),
            benchmark_latest_bar_timestamp=(
                None
                if benchmark_state is None
                else benchmark_state.latest_bar_timestamp
            ),
            benchmark_alignment=(
                None if benchmark_state is None else benchmark_state.alignment.value
            ),
            benchmark_bars_available=(
                None if benchmark_state is None else benchmark_state.bars_available
            ),
            breadth_advancers=advancers,
            breadth_decliners=decliners,
            breadth_unchanged=unchanged,
            breadth_ratio=breadth_ratio,
            percent_above_20dma=None,
            percent_above_50dma=None,
            percent_above_200dma=None,
            new_highs=None,
            new_lows=None,
            sector_leader=leader,
            sector_laggard=laggard,
            sector_dispersion=dispersion,
            market_trend_score=report.composite_score,
            breadth_score=report.breadth.score,
            volatility_score=report.liquidity.score,
            participation_score=report.accumulation.score,
            classifier_regime=report.bias.value,
            classifier_confidence=report.composite_score,
            classifier_version=classifier_version,
            input_completeness=completeness,
            fallback_applied=fallback_reason is not MarketStateFallbackReason.NONE,
            fallback_reason=fallback_reason,
            missing_fields=tuple(missing),
            source_lineage=lineage,
            classifier_inputs=inputs,
            provenance_id=getattr(provenance, "provenance_id", None),
            market_classifier_version=getattr(
                provenance,
                "market_classifier_version",
                classifier_version,
            ),
            market_classifier_fingerprint=getattr(
                provenance,
                "market_classifier_fingerprint",
                None,
            ),
            benchmark_builder_version=getattr(
                provenance,
                "benchmark_builder_version",
                None,
            ),
            market_feature_definition_version=getattr(
                provenance,
                "market_feature_definition_version",
                None,
            ),
            fallback_policy_version=getattr(
                provenance,
                "market_fallback_policy_version",
                None,
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "market_date": self.market_date.isoformat(),
            "as_of_timestamp": self.as_of_timestamp.isoformat(),
            "source_timestamp": self.source_timestamp.isoformat(),
            "created_at": self.created_at.isoformat(),
            "benchmark_symbol": self.benchmark_symbol,
            "benchmark_source": self.benchmark_source,
            "benchmark_close": _text(self.benchmark_close),
            "benchmark_return_1d": _text(self.benchmark_return_1d),
            "benchmark_return_5d": _text(self.benchmark_return_5d),
            "benchmark_return_20d": _text(self.benchmark_return_20d),
            "benchmark_dma_20": _text(self.benchmark_dma_20),
            "benchmark_dma_50": _text(self.benchmark_dma_50),
            "benchmark_dma_200": _text(self.benchmark_dma_200),
            "benchmark_above_20dma": self.benchmark_above_20dma,
            "benchmark_above_50dma": self.benchmark_above_50dma,
            "benchmark_above_200dma": self.benchmark_above_200dma,
            "benchmark_distance_20dma": _text(self.benchmark_distance_20dma),
            "benchmark_distance_50dma": _text(self.benchmark_distance_50dma),
            "benchmark_distance_200dma": _text(self.benchmark_distance_200dma),
            "benchmark_atr": _text(self.benchmark_atr),
            "benchmark_volatility": _text(self.benchmark_volatility),
            "benchmark_latest_bar_timestamp": (
                None
                if self.benchmark_latest_bar_timestamp is None
                else self.benchmark_latest_bar_timestamp.isoformat()
            ),
            "benchmark_alignment": self.benchmark_alignment,
            "benchmark_bars_available": self.benchmark_bars_available,
            "breadth_advancers": self.breadth_advancers,
            "breadth_decliners": self.breadth_decliners,
            "breadth_unchanged": self.breadth_unchanged,
            "breadth_ratio": _text(self.breadth_ratio),
            "percent_above_20dma": _text(self.percent_above_20dma),
            "percent_above_50dma": _text(self.percent_above_50dma),
            "percent_above_200dma": _text(self.percent_above_200dma),
            "new_highs": self.new_highs,
            "new_lows": self.new_lows,
            "sector_leader": self.sector_leader,
            "sector_laggard": self.sector_laggard,
            "sector_dispersion": _text(self.sector_dispersion),
            "market_trend_score": _text(self.market_trend_score),
            "breadth_score": _text(self.breadth_score),
            "volatility_score": _text(self.volatility_score),
            "participation_score": _text(self.participation_score),
            "classifier_regime": self.classifier_regime,
            "classifier_confidence": _text(self.classifier_confidence),
            "classifier_version": self.classifier_version,
            "input_completeness": self.input_completeness.value,
            "fallback_applied": self.fallback_applied,
            "fallback_reason": self.fallback_reason.value,
            "missing_fields": list(self.missing_fields),
            "source_lineage": list(self.source_lineage),
            "classifier_inputs": [item.as_dict() for item in self.classifier_inputs],
            "provenance_id": self.provenance_id,
            "market_classifier_version": self.market_classifier_version,
            "market_classifier_fingerprint": self.market_classifier_fingerprint,
            "benchmark_builder_version": self.benchmark_builder_version,
            "market_feature_definition_version": self.market_feature_definition_version,
            "fallback_policy_version": self.fallback_policy_version,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MarketStateSnapshot:
        return cls(
            snapshot_id=str(payload["snapshot_id"]),
            market_date=date.fromisoformat(str(payload["market_date"])),
            as_of_timestamp=datetime.fromisoformat(str(payload["as_of_timestamp"])),
            source_timestamp=datetime.fromisoformat(str(payload["source_timestamp"])),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            benchmark_symbol=str(payload["benchmark_symbol"]),
            benchmark_source=str(payload["benchmark_source"]),
            benchmark_close=_decimal(payload.get("benchmark_close")),
            benchmark_return_1d=_decimal(payload.get("benchmark_return_1d")),
            benchmark_return_5d=_decimal(payload.get("benchmark_return_5d")),
            benchmark_return_20d=_decimal(payload.get("benchmark_return_20d")),
            benchmark_dma_20=_decimal(payload.get("benchmark_dma_20")),
            benchmark_dma_50=_decimal(payload.get("benchmark_dma_50")),
            benchmark_dma_200=_decimal(payload.get("benchmark_dma_200")),
            benchmark_above_20dma=_optional_bool(payload.get("benchmark_above_20dma")),
            benchmark_above_50dma=_optional_bool(payload.get("benchmark_above_50dma")),
            benchmark_above_200dma=_optional_bool(
                payload.get("benchmark_above_200dma")
            ),
            benchmark_distance_20dma=_decimal(payload.get("benchmark_distance_20dma")),
            benchmark_distance_50dma=_decimal(payload.get("benchmark_distance_50dma")),
            benchmark_distance_200dma=_decimal(
                payload.get("benchmark_distance_200dma")
            ),
            benchmark_atr=_decimal(payload.get("benchmark_atr")),
            benchmark_volatility=_decimal(payload.get("benchmark_volatility")),
            benchmark_latest_bar_timestamp=(
                None
                if payload.get("benchmark_latest_bar_timestamp") is None
                else datetime.fromisoformat(
                    str(payload["benchmark_latest_bar_timestamp"])
                )
            ),
            benchmark_alignment=_payload_optional_text(
                payload.get("benchmark_alignment")
            ),
            benchmark_bars_available=_optional_int(
                payload.get("benchmark_bars_available")
            ),
            breadth_advancers=_optional_int(payload.get("breadth_advancers")),
            breadth_decliners=_optional_int(payload.get("breadth_decliners")),
            breadth_unchanged=_optional_int(payload.get("breadth_unchanged")),
            breadth_ratio=_decimal(payload.get("breadth_ratio")),
            percent_above_20dma=_decimal(payload.get("percent_above_20dma")),
            percent_above_50dma=_decimal(payload.get("percent_above_50dma")),
            percent_above_200dma=_decimal(payload.get("percent_above_200dma")),
            new_highs=_optional_int(payload.get("new_highs")),
            new_lows=_optional_int(payload.get("new_lows")),
            sector_leader=_payload_optional_text(payload.get("sector_leader")),
            sector_laggard=_payload_optional_text(payload.get("sector_laggard")),
            sector_dispersion=_decimal(payload.get("sector_dispersion")),
            market_trend_score=_decimal(payload.get("market_trend_score")),
            breadth_score=_decimal(payload.get("breadth_score")),
            volatility_score=_decimal(payload.get("volatility_score")),
            participation_score=_decimal(payload.get("participation_score")),
            classifier_regime=str(payload["classifier_regime"]),
            classifier_confidence=_decimal(payload.get("classifier_confidence")),
            classifier_version=str(payload["classifier_version"]),
            input_completeness=MarketStateInputCompleteness(
                str(payload["input_completeness"])
            ),
            fallback_applied=bool(payload["fallback_applied"]),
            fallback_reason=MarketStateFallbackReason(str(payload["fallback_reason"])),
            missing_fields=tuple(
                str(item) for item in payload.get("missing_fields", ())
            ),
            source_lineage=tuple(
                str(item) for item in payload.get("source_lineage", ())
            ),
            classifier_inputs=tuple(
                ClassifierInputRecord.from_dict(item)
                for item in payload.get("classifier_inputs", ())
            ),
            provenance_id=_payload_optional_text(payload.get("provenance_id")),
            market_classifier_version=_payload_optional_text(
                payload.get("market_classifier_version")
            ),
            market_classifier_fingerprint=_payload_optional_text(
                payload.get("market_classifier_fingerprint")
            ),
            benchmark_builder_version=_payload_optional_text(
                payload.get("benchmark_builder_version")
            ),
            market_feature_definition_version=_payload_optional_text(
                payload.get("market_feature_definition_version")
            ),
            fallback_policy_version=_payload_optional_text(
                payload.get("fallback_policy_version")
            ),
            schema_version=str(
                payload.get("schema_version", MARKET_STATE_SNAPSHOT_SCHEMA_VERSION)
            ),
        )


@dataclass(frozen=True, slots=True)
class MarketStatePersistenceResult:
    status: MarketStatePersistenceStatus
    snapshot: MarketStateSnapshot | None
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class MarketStateCoverageReport:
    total_snapshots: int
    first_market_date: date | None
    last_market_date: date | None
    classifier_versions: tuple[tuple[str, int], ...]
    completeness_distribution: tuple[tuple[str, int], ...]
    fallback_count: int
    missing_field_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class MarketStateBackfillPlanRow:
    market_date: date
    candidate_count: int
    status: MarketStateBackfillPlanStatus
    expected_completeness: MarketStateInputCompleteness
    required_sources: tuple[str, ...]
    blocking_gaps: tuple[str, ...]
    dry_run_only: bool = True


@dataclass(frozen=True, slots=True)
class MarketStateBackfillPlanReport:
    rows: tuple[MarketStateBackfillPlanRow, ...]
    dry_run_only: bool = True

    @property
    def market_dates_reviewed(self) -> int:
        return len(self.rows)


class MarketStateSnapshotConflictError(ValueError):
    pass


class MarketStateSnapshotRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_market_state_snapshot_path(path)

    def save(self, snapshot: MarketStateSnapshot) -> MarketStatePersistenceResult:
        existing = {item.snapshot_id: item for item in self.load_all()}
        current = existing.get(snapshot.snapshot_id)
        if current is not None and current.as_dict() != snapshot.as_dict():
            raise MarketStateSnapshotConflictError(
                f"market-state snapshot conflict: {snapshot.snapshot_id}"
            )
        if current is not None:
            return MarketStatePersistenceResult(
                status=MarketStatePersistenceStatus.SNAPSHOT_ALREADY_EXISTS,
                snapshot=current,
                path=self.path,
                message="Authoritative market-state snapshot already exists.",
            )
        existing[snapshot.snapshot_id] = snapshot
        self._write(tuple(existing.values()))
        return MarketStatePersistenceResult(
            status=MarketStatePersistenceStatus.SNAPSHOT_PERSISTED,
            snapshot=snapshot,
            path=self.path,
            message="Authoritative market-state snapshot persisted.",
        )

    def load_all(self) -> tuple[MarketStateSnapshot, ...]:
        payload = _read_payload(self.path)
        return tuple(
            sorted(
                (
                    MarketStateSnapshot.from_dict(item)
                    for item in payload.get("snapshots", ())
                ),
                key=lambda item: (
                    item.market_date,
                    item.as_of_timestamp,
                    item.snapshot_id,
                ),
            )
        )

    def get(self, snapshot_id: str) -> MarketStateSnapshot | None:
        normalized = snapshot_id.strip()
        return next(
            (item for item in self.load_all() if item.snapshot_id == normalized),
            None,
        )

    def find_by_market_date(self, market_date: date) -> tuple[MarketStateSnapshot, ...]:
        return tuple(
            item for item in self.load_all() if item.market_date == market_date
        )

    def find_range(
        self,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> tuple[MarketStateSnapshot, ...]:
        return tuple(
            item
            for item in self.load_all()
            if (from_date is None or item.market_date >= from_date)
            and (to_date is None or item.market_date <= to_date)
        )

    def latest(self) -> MarketStateSnapshot | None:
        return max(
            self.load_all(),
            key=lambda item: (item.as_of_timestamp, item.created_at, item.snapshot_id),
            default=None,
        )

    def latest_as_of(self, as_of_timestamp: datetime) -> MarketStateSnapshot | None:
        as_of = _aware(as_of_timestamp)
        eligible = tuple(
            item for item in self.load_all() if item.as_of_timestamp <= as_of
        )
        return max(
            eligible,
            key=lambda item: (item.as_of_timestamp, item.created_at, item.snapshot_id),
            default=None,
        )

    def coverage(self) -> MarketStateCoverageReport:
        snapshots = self.load_all()
        versions: dict[str, int] = {}
        completeness: dict[str, int] = {}
        missing: dict[str, int] = {}
        for item in snapshots:
            versions[item.classifier_version] = (
                versions.get(item.classifier_version, 0) + 1
            )
            key = item.input_completeness.value
            completeness[key] = completeness.get(key, 0) + 1
            for field in item.missing_fields:
                missing[field] = missing.get(field, 0) + 1
        dates = tuple(item.market_date for item in snapshots)
        return MarketStateCoverageReport(
            total_snapshots=len(snapshots),
            first_market_date=min(dates) if dates else None,
            last_market_date=max(dates) if dates else None,
            classifier_versions=tuple(sorted(versions.items())),
            completeness_distribution=tuple(sorted(completeness.items())),
            fallback_count=sum(1 for item in snapshots if item.fallback_applied),
            missing_field_counts=tuple(sorted(missing.items())),
        )

    def _write(self, snapshots: tuple[MarketStateSnapshot, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(
            snapshots,
            key=lambda item: (item.market_date, item.as_of_timestamp, item.snapshot_id),
        )
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": MARKET_STATE_SNAPSHOT_SCHEMA_VERSION,
                    "snapshots": [item.as_dict() for item in ordered],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )


def resolve_market_state_snapshot_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("ALPHA_MARKET_STATE_SNAPSHOT_LEDGER")
    return Path(env) if env else DEFAULT_MARKET_STATE_SNAPSHOT_PATH


def market_state_snapshot_id(
    *,
    market_date: date,
    as_of_timestamp: datetime,
    benchmark_symbol: str,
    classifier_version: str,
    classifier_regime: str,
    source_lineage: tuple[str, ...],
) -> str:
    raw = "|".join(
        (
            market_date.isoformat(),
            _aware(as_of_timestamp).isoformat(),
            benchmark_symbol.strip().upper(),
            classifier_version.strip(),
            classifier_regime.strip().upper(),
            ";".join(source_lineage),
        )
    )
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def render_market_state_snapshot(snapshot: MarketStateSnapshot) -> tuple[str, ...]:
    return (
        "Market State Snapshot",
        f"Snapshot ID: {snapshot.snapshot_id}",
        f"Market Date: {snapshot.market_date.isoformat()}",
        f"As Of: {snapshot.as_of_timestamp.isoformat()}",
        f"Source Timestamp: {snapshot.source_timestamp.isoformat()}",
        f"Benchmark: {snapshot.benchmark_symbol} ({snapshot.benchmark_source})",
        f"Classifier Version: {snapshot.classifier_version}",
        f"Classifier Regime: {snapshot.classifier_regime}",
        f"Classifier Confidence: {_display(snapshot.classifier_confidence)}",
        f"Input Completeness: {snapshot.input_completeness.value}",
        f"Fallback Applied: {'Yes' if snapshot.fallback_applied else 'No'}",
        f"Fallback Reason: {snapshot.fallback_reason.value}",
        f"Benchmark Close: {_display(snapshot.benchmark_close)}",
        "Latest Benchmark Bar: "
        f"{_datetime_display(snapshot.benchmark_latest_bar_timestamp)}",
        f"Benchmark Alignment: {snapshot.benchmark_alignment or 'unavailable'}",
        f"Benchmark Return 1D: {_display(snapshot.benchmark_return_1d)}",
        f"Benchmark Return 5D: {_display(snapshot.benchmark_return_5d)}",
        f"Benchmark Return 20D: {_display(snapshot.benchmark_return_20d)}",
        f"Benchmark 20-DMA: {_display(snapshot.benchmark_dma_20)}",
        f"Benchmark 50-DMA: {_display(snapshot.benchmark_dma_50)}",
        f"Benchmark 200-DMA: {_display(snapshot.benchmark_dma_200)}",
        f"Benchmark ATR: {_display(snapshot.benchmark_atr)}",
        f"Benchmark Volatility: {_display(snapshot.benchmark_volatility)}",
        f"Breadth: {_display_int(snapshot.breadth_advancers)} advances, "
        f"{_display_int(snapshot.breadth_decliners)} declines, "
        f"{_display_int(snapshot.breadth_unchanged)} unchanged",
        f"Breadth Ratio: {_display(snapshot.breadth_ratio)}",
        f"Sector Leader: {snapshot.sector_leader or 'unavailable'}",
        f"Sector Laggard: {snapshot.sector_laggard or 'unavailable'}",
        f"Missing Fields: {_joined(snapshot.missing_fields)}",
        f"Source Lineage: {_joined(snapshot.source_lineage)}",
    )


def render_market_state_history(
    snapshots: tuple[MarketStateSnapshot, ...],
) -> tuple[str, ...]:
    lines = ["Market State Snapshot History", f"Snapshots: {len(snapshots)}"]
    for item in snapshots:
        lines.append(
            f"- {item.market_date.isoformat()} | {item.snapshot_id} | "
            f"{item.classifier_regime} | {item.input_completeness.value} | "
            f"fallback={'yes' if item.fallback_applied else 'no'}"
        )
    return tuple(lines)


def render_market_state_coverage(report: MarketStateCoverageReport) -> tuple[str, ...]:
    return (
        "Market State Snapshot Coverage",
        f"Total Snapshots: {report.total_snapshots}",
        f"First Market Date: {_date_display(report.first_market_date)}",
        f"Last Market Date: {_date_display(report.last_market_date)}",
        f"Classifier Versions: {_pairs(report.classifier_versions)}",
        f"Completeness: {_pairs(report.completeness_distribution)}",
        f"Fallback Count: {report.fallback_count}",
        f"Top Missing Fields: {_pairs(report.missing_field_counts[:10])}",
    )


def render_market_state_lineage(snapshot: MarketStateSnapshot) -> tuple[str, ...]:
    return (
        "Market State Snapshot Lineage",
        f"Snapshot ID: {snapshot.snapshot_id}",
        f"Source Lineage: {_joined(snapshot.source_lineage)}",
        f"Classifier Inputs: {len(snapshot.classifier_inputs)}",
        *(
            f"- {item.name}: {item.value or 'unavailable'} "
            f"({item.source}, {item.fallback_status})"
            for item in snapshot.classifier_inputs
        ),
    )


def render_market_state_persistence_result(
    result: MarketStatePersistenceResult,
) -> tuple[str, ...]:
    snapshot_id = (
        result.snapshot.snapshot_id if result.snapshot is not None else "unavailable"
    )
    return (
        "Market State Snapshot Persistence:",
        f"- Status: {result.status.value}",
        f"- Snapshot ID: {snapshot_id}",
        f"- Ledger: {result.path}",
        f"- Message: {result.message}",
    )


def build_market_state_backfill_plan(
    *,
    records: tuple[Any, ...],
    snapshots: tuple[MarketStateSnapshot, ...],
) -> MarketStateBackfillPlanReport:
    snapshot_dates = {snapshot.market_date for snapshot in snapshots}
    grouped: dict[date, list[Any]] = {}
    for record in records:
        grouped.setdefault(record.evaluation_date, []).append(record)
    rows = []
    for market_date, items in sorted(grouped.items()):
        if market_date in snapshot_dates:
            status = MarketStateBackfillPlanStatus.AUTHORITATIVE_SOURCE_AVAILABLE
            completeness = MarketStateInputCompleteness.COMPLETE
            gaps: tuple[str, ...] = ()
        else:
            has_breadth = any(
                "breadth" in getattr(record, "indicator_scores", {}) for record in items
            )
            has_benchmark = any(
                any(key.startswith("benchmark") for key in record.indicator_scores)
                for record in items
            )
            if has_benchmark and has_breadth:
                status = MarketStateBackfillPlanStatus.PARTIALLY_RECONSTRUCTABLE
                completeness = MarketStateInputCompleteness.PARTIAL
                gaps = ("authoritative_market_state_snapshot",)
            elif has_breadth:
                status = MarketStateBackfillPlanStatus.NO_BENCHMARK_HISTORY
                completeness = MarketStateInputCompleteness.INSUFFICIENT
                gaps = ("benchmark_history", "authoritative_market_state_snapshot")
            elif has_benchmark:
                status = MarketStateBackfillPlanStatus.NO_BREADTH_HISTORY
                completeness = MarketStateInputCompleteness.INSUFFICIENT
                gaps = ("breadth_history", "authoritative_market_state_snapshot")
            else:
                status = MarketStateBackfillPlanStatus.INSUFFICIENT_SOURCE_DATA
                completeness = MarketStateInputCompleteness.UNAVAILABLE
                gaps = (
                    "benchmark_history",
                    "breadth_history",
                    "authoritative_market_state_snapshot",
                )
        rows.append(
            MarketStateBackfillPlanRow(
                market_date=market_date,
                candidate_count=len(items),
                status=status,
                expected_completeness=completeness,
                required_sources=(
                    "benchmark_history",
                    "breadth_history",
                    "sector_history",
                    "classifier_version",
                ),
                blocking_gaps=gaps,
            )
        )
    return MarketStateBackfillPlanReport(rows=tuple(rows))


def render_market_state_backfill_plan(
    report: MarketStateBackfillPlanReport,
) -> tuple[str, ...]:
    benchmark = canonical_benchmark_configuration()
    counts: dict[str, int] = {}
    for row in report.rows:
        counts[row.status.value] = counts.get(row.status.value, 0) + 1
    lines = [
        "Market State Backfill Plan (Dry Run)",
        f"Benchmark Identity: {benchmark.logical_name}",
        f"Benchmark Provider Symbol: {benchmark.provider_symbol}",
        "Benchmark History Source: local_daily_prices",
        "Feature-Build Compatibility: uses live BenchmarkStateBuilder formulas",
        "Timestamp Compatibility: daily bars at or before decision date only",
        "Schema Compatibility: MarketStateSnapshot schema 1.0",
        f"Market Dates Reviewed: {report.market_dates_reviewed}",
        f"Dry Run Only: {'Yes' if report.dry_run_only else 'No'}",
        f"Status Summary: {_pairs(tuple(sorted(counts.items())))}",
    ]
    for row in report.rows[:20]:
        lines.append(
            f"- {row.market_date.isoformat()}: {row.status.value} | "
            f"candidates={row.candidate_count} | "
            f"expected={row.expected_completeness.value} | "
            f"gaps={_joined(row.blocking_gaps)}"
        )
    if len(report.rows) > 20:
        lines.append(f"- ... {len(report.rows) - 20} more dates")
    return tuple(lines)


def _read_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": MARKET_STATE_SNAPSHOT_SCHEMA_VERSION, "snapshots": []}
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _input_completeness(missing_fields: list[str]) -> MarketStateInputCompleteness:
    if not missing_fields:
        return MarketStateInputCompleteness.COMPLETE
    missing = set(missing_fields)
    if "breadth_ratio" in missing and "sector_leadership" in missing:
        return MarketStateInputCompleteness.INSUFFICIENT
    if "benchmark_return_20d" in missing:
        return MarketStateInputCompleteness.PARTIAL
    return MarketStateInputCompleteness.MINIMUM_VIABLE


def _snapshot_completeness(
    *,
    missing: list[str],
    benchmark_state: BenchmarkState | None,
) -> MarketStateInputCompleteness:
    if benchmark_state is None:
        return _input_completeness(missing)
    if benchmark_state.completeness is BenchmarkFeatureCompleteness.COMPLETE:
        if not missing:
            return MarketStateInputCompleteness.COMPLETE
        return MarketStateInputCompleteness.PARTIAL
    if benchmark_state.completeness is BenchmarkFeatureCompleteness.PARTIAL:
        return MarketStateInputCompleteness.PARTIAL
    if benchmark_state.completeness is BenchmarkFeatureCompleteness.MINIMUM_VIABLE:
        return MarketStateInputCompleteness.MINIMUM_VIABLE
    if benchmark_state.completeness is BenchmarkFeatureCompleteness.INSUFFICIENT:
        return MarketStateInputCompleteness.INSUFFICIENT
    return MarketStateInputCompleteness.UNAVAILABLE


def _benchmark_missing_fields(
    benchmark_state: BenchmarkState | None,
) -> tuple[str, ...]:
    if benchmark_state is None:
        return (
            "benchmark_close",
            "benchmark_return_1d",
            "benchmark_return_5d",
            "benchmark_return_20d",
            "benchmark_dma_20",
            "benchmark_dma_50",
            "benchmark_dma_200",
            "benchmark_above_20dma",
            "benchmark_above_50dma",
            "benchmark_above_200dma",
            "benchmark_distance_20dma",
            "benchmark_distance_50dma",
            "benchmark_distance_200dma",
            "benchmark_atr",
            "benchmark_volatility",
        )
    missing = set(benchmark_state.missing_fields)
    for field, value in (
        ("benchmark_above_20dma", benchmark_state.benchmark_above_20dma),
        ("benchmark_above_50dma", benchmark_state.benchmark_above_50dma),
        ("benchmark_above_200dma", benchmark_state.benchmark_above_200dma),
        ("benchmark_distance_20dma", benchmark_state.benchmark_distance_20dma),
        ("benchmark_distance_50dma", benchmark_state.benchmark_distance_50dma),
        ("benchmark_distance_200dma", benchmark_state.benchmark_distance_200dma),
    ):
        if value is None:
            missing.add(field)
    return tuple(sorted(missing))


def _benchmark_fallback_reason(
    *,
    report: MarketIntelligenceReport,
    benchmark_state: BenchmarkState | None,
    missing: tuple[str, ...],
) -> MarketStateFallbackReason:
    if benchmark_state is None:
        return (
            MarketStateFallbackReason.MISSING_BENCHMARK_INPUT
            if report.bias.value == "NEUTRAL"
            else MarketStateFallbackReason.NONE
        )
    if benchmark_state.alignment is BenchmarkAlignment.BENCHMARK_BAR_UNAVAILABLE:
        return MarketStateFallbackReason.BENCHMARK_HISTORY_UNAVAILABLE
    if benchmark_state.alignment is BenchmarkAlignment.FUTURE_BAR_REJECTED:
        return MarketStateFallbackReason.BENCHMARK_TIMESTAMP_INVALID
    if benchmark_state.alignment is BenchmarkAlignment.CARRIED_FORWARD_STALE:
        return MarketStateFallbackReason.BENCHMARK_LATEST_BAR_STALE
    if benchmark_state.completeness in {
        BenchmarkFeatureCompleteness.INSUFFICIENT,
        BenchmarkFeatureCompleteness.UNAVAILABLE,
    }:
        return MarketStateFallbackReason.BENCHMARK_LOOKBACK_INSUFFICIENT
    if "breadth_ratio" in missing:
        return MarketStateFallbackReason.MISSING_BREADTH_INPUT
    return MarketStateFallbackReason.NONE


def _benchmark_lineage(benchmark_state: BenchmarkState | None) -> str:
    if benchmark_state is None:
        return "benchmark_state:unavailable"
    return (
        "benchmark_state:"
        f"{benchmark_state.configuration.provider_symbol}:"
        f"{benchmark_state.alignment.value}:"
        f"{benchmark_state.completeness.value}"
    )


def _input_record(
    name: str,
    value: Decimal | None,
    timestamp: datetime,
) -> ClassifierInputRecord:
    return ClassifierInputRecord(
        name=name,
        value=None if value is None else str(value),
        available=value is not None,
        source="MarketIntelligenceReport",
        input_timestamp=timestamp,
        staleness_days=0,
        fallback_status="AVAILABLE" if value is not None else "MISSING",
    )


def _reason_int(reasons: tuple[str, ...], prefix: str) -> int | None:
    needle = f"{prefix}:"
    for reason in reasons:
        if reason.strip().lower().startswith(needle):
            try:
                return int(reason.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _payload_optional_text(value: object) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(str(value))


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _display(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _display_int(value: int | None) -> str:
    return "unavailable" if value is None else str(value)


def _joined(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "none"


def _date_display(value: date | None) -> str:
    return "unavailable" if value is None else value.isoformat()


def _datetime_display(value: datetime | None) -> str:
    return "unavailable" if value is None else value.isoformat()


def _pairs(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values) if values else "none"


__all__ = [
    "ClassifierInputRecord",
    "DEFAULT_MARKET_STATE_SNAPSHOT_PATH",
    "MARKET_STATE_CLASSIFIER_VERSION",
    "MarketStateBackfillPlanReport",
    "MarketStateBackfillPlanRow",
    "MarketStateBackfillPlanStatus",
    "MarketStateCoverageReport",
    "MarketStateFallbackReason",
    "MarketStateInputCompleteness",
    "MarketStatePersistenceResult",
    "MarketStatePersistenceStatus",
    "MarketStateSnapshot",
    "MarketStateSnapshotConflictError",
    "MarketStateSnapshotRepository",
    "build_market_state_backfill_plan",
    "market_state_snapshot_id",
    "render_market_state_backfill_plan",
    "render_market_state_coverage",
    "render_market_state_history",
    "render_market_state_lineage",
    "render_market_state_persistence_result",
    "render_market_state_snapshot",
    "resolve_market_state_snapshot_path",
]
