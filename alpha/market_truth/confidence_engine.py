from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from alpha.market_truth.models import (
    ConfidenceAssessment,
    ConfidenceBand,
    DataQuality,
    EvidenceClass,
    ProviderDataset,
    QualityAssessment,
)


class MarketTruthConfidenceEngine:
    """Derive transparent data confidence from authority and measured quality."""

    def assess(
        self,
        dataset: ProviderDataset | None,
        quality: QualityAssessment,
    ) -> ConfidenceAssessment:
        if dataset is None or quality.quality is DataQuality.UNAVAILABLE:
            return ConfidenceAssessment(
                confidence_pct=Decimal("0"),
                band=ConfidenceBand.NONE,
                reasons=("No market data evidence is available.",),
            )
        authority = _authority_score(dataset.evidence_class)
        quality_factor = {
            DataQuality.COMPLETE: Decimal("1"),
            DataQuality.PARTIAL: Decimal("0.80"),
            DataQuality.DEGRADED: Decimal("0.45"),
            DataQuality.UNAVAILABLE: Decimal("0"),
        }[quality.quality]
        score = (authority * quality_factor * quality.completeness).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return ConfidenceAssessment(
            confidence_pct=score,
            band=_band(score),
            reasons=(
                f"Evidence authority base: {authority}%.",
                f"Quality factor: {quality_factor}.",
                f"Reported completeness: {quality.completeness}.",
            ),
        )


def _authority_score(evidence: EvidenceClass) -> Decimal:
    return {
        EvidenceClass.AUTHORITATIVE: Decimal("100"),
        EvidenceClass.LICENSED: Decimal("95"),
        EvidenceClass.CACHED_AUTHORITATIVE: Decimal("90"),
        EvidenceClass.FORWARD_OBSERVED: Decimal("85"),
        EvidenceClass.BROKER_OBSERVED: Decimal("75"),
        EvidenceClass.RECONSTRUCTED: Decimal("50"),
        EvidenceClass.UNKNOWN: Decimal("0"),
    }[evidence]


def _band(score: Decimal) -> ConfidenceBand:
    if score >= Decimal("90"):
        return ConfidenceBand.VERY_HIGH
    if score >= Decimal("75"):
        return ConfidenceBand.HIGH
    if score >= Decimal("50"):
        return ConfidenceBand.MEDIUM
    if score > 0:
        return ConfidenceBand.LOW
    return ConfidenceBand.NONE


__all__ = ["MarketTruthConfidenceEngine"]
