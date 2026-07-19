from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from alpha.market_opportunity_truth.models import (
    LiquidityState,
    MarketOpportunity,
    OpportunityQuality,
    OpportunityQualityAssessment,
    QualityDistributionRecord,
    RawOpportunityOnset,
    TradabilityAssessment,
    TrendState,
    VolatilityState,
)

_TWO = Decimal("0.01")


class OpportunityQualityEngine:
    """Apply the pre-registered MOTA quality rubric without outcome inputs."""

    def assess(
        self,
        onset: RawOpportunityOnset,
        tradability: TradabilityAssessment,
    ) -> OpportunityQualityAssessment:
        if not tradability.tradable:
            return OpportunityQualityAssessment(
                quality=OpportunityQuality.NOT_TRADABLE,
                score=Decimal("0.00"),
                components=(),
                explanation="Not tradable: " + ", ".join(tradability.reasons),
            )
        components = (
            ("reward_risk", _reward_risk_score(onset.prospective_rr)),
            ("source_confidence", _confidence_score(onset.source_confidence)),
            ("liquidity", _liquidity_score(tradability.liquidity_state)),
            ("trend", _trend_score(tradability.trend_state)),
            ("volatility", _volatility_score(tradability.volatility_state)),
            ("extension", _extension_adjustment(tradability.extension_percent)),
            ("base_depth", _base_adjustment(tradability.base_depth_percent)),
        )
        score = max(
            Decimal("0"),
            min(Decimal("100"), sum((value for _, value in components), Decimal("0"))),
        ).quantize(_TWO, rounding=ROUND_HALF_UP)
        quality = _quality(score)
        return OpportunityQualityAssessment(
            quality=quality,
            score=score,
            components=components,
            explanation=(
                f"{quality.value} from point-in-time reward/risk "
                f"{onset.prospective_rr.quantize(_TWO)}, "
                f"{tradability.liquidity_state.value.lower()} liquidity, "
                f"{tradability.trend_state.value.lower()} trend, and "
                f"{tradability.volatility_state.value.lower()} volatility."
            ),
        )


def quality_distribution(
    opportunities: tuple[MarketOpportunity, ...],
) -> tuple[QualityDistributionRecord, ...]:
    grouped: dict[OpportunityQuality, list[MarketOpportunity]] = defaultdict(list)
    for item in opportunities:
        grouped[item.quality].append(item)
    rows = []
    for quality in OpportunityQuality:
        values = grouped.get(quality, [])
        mature = tuple(
            item
            for item in values
            if item.target_before_stop is not None
            and item.mfe_percent is not None
            and item.mae_percent is not None
        )
        rows.append(
            QualityDistributionRecord(
                quality=quality,
                opportunities=len(values),
                population_percent=_rate(len(values), len(opportunities)),
                mature_outcomes=len(mature),
                target_before_stop_count=sum(
                    item.target_before_stop is True for item in mature
                ),
                target_before_stop_rate=_rate(
                    sum(item.target_before_stop is True for item in mature),
                    len(mature),
                ),
                stop_hit_rate=_rate(
                    sum(item.stop_hit is True for item in mature),
                    len(mature),
                ),
                average_realized_r=_mean(
                    tuple(
                        item.rr_achieved
                        for item in mature
                        if item.rr_achieved is not None
                    )
                ),
                average_mfe_percent=_mean(
                    tuple(
                        item.mfe_percent
                        for item in mature
                        if item.mfe_percent is not None
                    )
                ),
                average_mae_percent=_mean(
                    tuple(
                        item.mae_percent
                        for item in mature
                        if item.mae_percent is not None
                    )
                ),
            )
        )
    return tuple(rows)


def _reward_risk_score(value: Decimal) -> Decimal:
    if value >= Decimal("3"):
        return Decimal("30")
    if value >= Decimal("2.5"):
        return Decimal("25")
    if value >= Decimal("2"):
        return Decimal("20")
    return Decimal("15")


def _confidence_score(value: Decimal) -> Decimal:
    if value >= Decimal("0.9"):
        return Decimal("25")
    if value >= Decimal("0.8"):
        return Decimal("20")
    if value >= Decimal("0.7"):
        return Decimal("15")
    if value >= Decimal("0.6"):
        return Decimal("10")
    return Decimal("5")


def _liquidity_score(value: LiquidityState) -> Decimal:
    return {
        LiquidityState.INSTITUTIONAL: Decimal("20"),
        LiquidityState.HIGH: Decimal("16"),
        LiquidityState.MEDIUM: Decimal("12"),
        LiquidityState.MINIMUM: Decimal("5"),
    }.get(value, Decimal("0"))


def _trend_score(value: TrendState) -> Decimal:
    return {
        TrendState.UP_ALIGNED: Decimal("15"),
        TrendState.PRICE_ABOVE_EMA20: Decimal("8"),
    }.get(value, Decimal("0"))


def _volatility_score(value: VolatilityState) -> Decimal:
    return {
        VolatilityState.LOW: Decimal("10"),
        VolatilityState.NORMAL: Decimal("7"),
        VolatilityState.ELEVATED: Decimal("3"),
    }.get(value, Decimal("0"))


def _extension_adjustment(value: Decimal | None) -> Decimal:
    if value is None:
        return Decimal("-5")
    if value > Decimal("7"):
        return Decimal("-10")
    if value > Decimal("5"):
        return Decimal("-5")
    return Decimal("0")


def _base_adjustment(value: Decimal | None) -> Decimal:
    if value is None:
        return Decimal("-5")
    return Decimal("-5") if value > Decimal("20") else Decimal("0")


def _quality(score: Decimal) -> OpportunityQuality:
    if score >= Decimal("85"):
        return OpportunityQuality.A_PLUS
    if score >= Decimal("75"):
        return OpportunityQuality.A
    if score >= Decimal("60"):
        return OpportunityQuality.B
    return OpportunityQuality.C


def _rate(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0.00")
    return (Decimal(numerator) / Decimal(denominator) * Decimal("100")).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


__all__ = ["OpportunityQualityEngine", "quality_distribution"]
