from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import duckdb

from alpha.market_truth.cache_manager import (
    MarketTruthCacheIntegrityError,
    MarketTruthCacheManager,
)
from alpha.market_truth.confidence_engine import MarketTruthConfidenceEngine
from alpha.market_truth.models import (
    DataQuality,
    EvidenceClass,
    MarketTruth,
    MarketTruthRequest,
    ProviderAttempt,
    ProviderDataset,
    ProviderHealth,
    ProviderHealthState,
    utc,
)
from alpha.market_truth.provenance_engine import MarketTruthProvenanceEngine
from alpha.market_truth.provider_failover import ProviderFailover
from alpha.market_truth.provider_health import ProviderHealthMonitor
from alpha.market_truth.provider_registry import (
    MarketTruthProviderError,
    MarketTruthProviderRegistry,
)
from alpha.market_truth.quality_engine import MarketTruthQualityEngine
from alpha.market_truth.versioning import MarketTruthVersioning


class MarketTruthProviderRouter:
    """Resolve market truth through deterministic, observable provider failover."""

    def __init__(
        self,
        *,
        registry: MarketTruthProviderRegistry,
        cache: MarketTruthCacheManager,
        health: ProviderHealthMonitor,
        failover: ProviderFailover | None = None,
        quality: MarketTruthQualityEngine | None = None,
        confidence: MarketTruthConfidenceEngine | None = None,
        provenance: MarketTruthProvenanceEngine | None = None,
        versioning: MarketTruthVersioning | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.registry = registry
        self.cache = cache
        self.health = health
        self.failover = failover or ProviderFailover()
        self.quality = quality or MarketTruthQualityEngine()
        self.confidence = confidence or MarketTruthConfidenceEngine()
        self.provenance = provenance or MarketTruthProvenanceEngine()
        self.versioning = versioning or MarketTruthVersioning()
        self.clock = clock or (lambda: datetime.now(tz=UTC))

    def route(self, request: MarketTruthRequest) -> MarketTruth:
        plan = self.failover.plan(self.registry, request)
        attempts: list[ProviderAttempt] = []
        degraded: ProviderDataset | None = None
        for provider in plan.providers:
            timestamp = utc(self.clock())
            descriptor = provider.descriptor
            if not descriptor.configured:
                attempts.append(
                    ProviderAttempt(
                        provider_id=descriptor.provider_id,
                        attempted_at=timestamp,
                        succeeded=False,
                        reason="Provider is not configured.",
                    )
                )
                continue
            try:
                dataset = provider.fetch(request)
                _validate_provider_response(request, descriptor.provider_id, dataset)
                assessment = self.quality.assess(request, dataset)
                if assessment.quality is DataQuality.UNAVAILABLE:
                    raise MarketTruthProviderError("provider returned no usable data")
                attempts.append(
                    ProviderAttempt(
                        provider_id=descriptor.provider_id,
                        attempted_at=timestamp,
                        succeeded=True,
                        reason=f"Returned {len(dataset.records)} record(s).",
                        dataset_checksum=dataset.checksum,
                    )
                )
                self.health.record(
                    ProviderHealth(
                        provider_id=descriptor.provider_id,
                        state=(
                            ProviderHealthState.HEALTHY
                            if assessment.quality is DataQuality.COMPLETE
                            else ProviderHealthState.DEGRADED
                        ),
                        checked_at=timestamp,
                        latency_ms=None,
                        message=f"Last request quality: {assessment.quality.value}.",
                    )
                )
                if assessment.quality is DataQuality.DEGRADED:
                    degraded = degraded or dataset
                    continue
                self._cache(request, dataset, descriptor.provider_class.value)
                return self._truth(request, dataset, tuple(attempts), timestamp)
            except (
                MarketTruthProviderError,
                OSError,
                RuntimeError,
                ValueError,
                duckdb.Error,
            ) as exc:
                reason = _sanitized_reason(exc)
                attempts.append(
                    ProviderAttempt(
                        provider_id=descriptor.provider_id,
                        attempted_at=timestamp,
                        succeeded=False,
                        reason=reason,
                    )
                )
                self.health.record(
                    ProviderHealth(
                        provider_id=descriptor.provider_id,
                        state=ProviderHealthState.UNAVAILABLE,
                        checked_at=timestamp,
                        latency_ms=None,
                        message=reason,
                        consecutive_failures=1,
                    )
                )
        timestamp = utc(self.clock())
        return self._truth(request, degraded, tuple(attempts), timestamp)

    def _cache(
        self,
        request: MarketTruthRequest,
        dataset: ProviderDataset,
        provider_class: str,
    ) -> None:
        if provider_class == "LOCAL_CACHE":
            return
        try:
            self.cache.put(request, dataset)
        except MarketTruthCacheIntegrityError:
            return

    def _truth(
        self,
        request: MarketTruthRequest,
        dataset: ProviderDataset | None,
        attempts: tuple[ProviderAttempt, ...],
        generated_at: datetime,
    ) -> MarketTruth:
        quality = self.quality.assess(request, dataset)
        confidence = self.confidence.assess(dataset, quality)
        provenance = self.provenance.build(
            request=request,
            dataset=dataset,
            attempts=attempts,
            generated_at=generated_at,
        )
        return MarketTruth(
            request=request,
            records=() if dataset is None else dataset.records,
            source="NO_DATA" if dataset is None else dataset.source,
            provider="NO_DATA" if dataset is None else dataset.provider_id,
            timestamp=generated_at,
            evidence_class=(
                EvidenceClass.UNKNOWN if dataset is None else dataset.evidence_class
            ),
            confidence=confidence,
            quality=quality,
            version=self.versioning.version(request=request, dataset=dataset),
            provenance=provenance,
            completeness=quality.completeness,
        )


def _validate_provider_response(
    request: MarketTruthRequest,
    provider_id: str,
    dataset: ProviderDataset,
) -> None:
    if dataset.request_id != request.request_id:
        raise MarketTruthProviderError("provider response request id mismatch")
    if dataset.provider_id != provider_id:
        raise MarketTruthProviderError("provider response identity mismatch")


def _sanitized_reason(error: BaseException) -> str:
    message = " ".join(str(error).split())
    return message[:1000] if message else error.__class__.__name__


__all__ = ["MarketTruthProviderRouter"]
