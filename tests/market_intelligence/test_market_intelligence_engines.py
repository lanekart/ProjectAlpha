from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.market_intelligence import (
    AccumulationPhase,
    BreadthCondition,
    CorrelationInput,
    CorrelationRisk,
    CorrelationRiskEngine,
    DistributionEngine,
    DistributionPhase,
    InstitutionalAccumulationEngine,
    IntelligenceBias,
    LiquidityIntelligenceEngine,
    LiquidityQuality,
    MarketBreadthEngine,
    MarketBreadthInput,
    MarketIntelligenceCompositeEngine,
    SectorPerformanceInput,
    SectorRotationEngine,
    SectorRotationPhase,
    StockIntelligenceInput,
)


def test_institutional_accumulation_detects_strong_accumulation() -> None:
    assessment = InstitutionalAccumulationEngine().assess(
        _stock(
            price_change_percent=Decimal("4.2"),
            delivery_percent=Decimal("78"),
            delivery_change_percent=Decimal("18"),
            volume_change_percent=Decimal("35"),
        )
    )

    assert assessment.classification == AccumulationPhase.STRONG_ACCUMULATION.value
    assert assessment.bias is IntelligenceBias.POSITIVE
    assert assessment.score >= Decimal("0.70")
    assert assessment.metrics["delivery_percent"] == Decimal("78")

    with pytest.raises(TypeError):
        assessment.metrics["delivery_percent"] = Decimal("1")


def test_distribution_engine_detects_price_weakness_with_delivery() -> None:
    assessment = DistributionEngine().assess(
        _stock(
            price_change_percent=Decimal("-7"),
            delivery_percent=Decimal("72"),
            delivery_change_percent=Decimal("12"),
            volume_change_percent=Decimal("40"),
        )
    )

    assert assessment.classification == DistributionPhase.STRONG_DISTRIBUTION.value
    assert assessment.bias is IntelligenceBias.NEGATIVE
    assert assessment.score >= Decimal("0.65")


def test_liquidity_engine_classifies_high_quality_liquidity() -> None:
    assessment = LiquidityIntelligenceEngine().assess(
        _stock(
            turnover_value=Decimal("1800000000"),
            average_turnover_value=Decimal("1200000000"),
            spread_percent=Decimal("0.20"),
            volatility_percent=Decimal("2.5"),
        )
    )

    assert assessment.classification == LiquidityQuality.HIGH.value
    assert assessment.bias is IntelligenceBias.POSITIVE
    assert assessment.score >= Decimal("0.70")


def test_market_breadth_engine_classifies_broad_participation() -> None:
    assessment = MarketBreadthEngine().assess(
        MarketBreadthInput(
            observed_on=date(2026, 1, 10),
            advances=360,
            declines=160,
            unchanged=20,
        )
    )

    assert assessment.classification == BreadthCondition.BROAD_PARTICIPATION.value
    assert assessment.bias is IntelligenceBias.POSITIVE
    assert assessment.metrics["advance_ratio"] > Decimal("0.60")


def test_sector_rotation_engine_ranks_sector_leadership() -> None:
    assessment = SectorRotationEngine().assess(
        (
            SectorPerformanceInput(
                sector="it",
                return_percent=Decimal("1.2"),
                breadth_percent=Decimal("52"),
                turnover_change_percent=Decimal("8"),
            ),
            SectorPerformanceInput(
                sector="defence",
                return_percent=Decimal("5.4"),
                breadth_percent=Decimal("82"),
                turnover_change_percent=Decimal("30"),
            ),
            SectorPerformanceInput(
                sector="fmcg",
                return_percent=Decimal("-0.5"),
                breadth_percent=Decimal("38"),
                turnover_change_percent=Decimal("-3"),
            ),
        )
    )

    assert assessment.top_sector.sector == "DEFENCE"
    assert assessment.top_sector.rank == 1
    assert assessment.phase is SectorRotationPhase.SELECTIVE_LEADERSHIP


def test_correlation_risk_engine_identifies_high_correlation_risk() -> None:
    assessment = CorrelationRiskEngine().assess(
        CorrelationInput(
            symbol="hal",
            correlation_to_index=Decimal("0.91"),
            correlation_to_sector=Decimal("0.86"),
        )
    )

    assert assessment.classification == CorrelationRisk.HIGH.value
    assert assessment.bias is IntelligenceBias.NEGATIVE
    assert assessment.metrics["average_correlation"] == Decimal("0.885")


def test_market_intelligence_composite_builds_constructive_report() -> None:
    report = MarketIntelligenceCompositeEngine().assess(
        stock=_stock(
            symbol=" hal ",
            price_change_percent=Decimal("4"),
            delivery_percent=Decimal("76"),
            delivery_change_percent=Decimal("22"),
            volume_change_percent=Decimal("42"),
            turnover_value=Decimal("1500000000"),
            average_turnover_value=Decimal("1000000000"),
            spread_percent=Decimal("0.25"),
            volatility_percent=Decimal("3"),
        ),
        breadth=MarketBreadthInput(
            observed_on=date(2026, 1, 10),
            advances=420,
            declines=130,
            unchanged=10,
        ),
        sectors=(
            SectorPerformanceInput(
                sector="defence",
                return_percent=Decimal("5"),
                breadth_percent=Decimal("80"),
                turnover_change_percent=Decimal("25"),
            ),
            SectorPerformanceInput(
                sector="capital goods",
                return_percent=Decimal("4"),
                breadth_percent=Decimal("75"),
                turnover_change_percent=Decimal("20"),
            ),
        ),
        correlation=CorrelationInput(
            symbol="hal",
            correlation_to_index=Decimal("0.42"),
            correlation_to_sector=Decimal("0.58"),
        ),
    )

    assert report.symbol == "HAL"
    assert report.bias is IntelligenceBias.POSITIVE
    assert report.is_constructive is True
    assert report.composite_score >= Decimal("0.60")
    assert report.sector_rotation.top_sector.sector == "DEFENCE"
    assert "accumulation: STRONG_ACCUMULATION" in report.reasons


def test_market_intelligence_inputs_validate_ranges() -> None:
    with pytest.raises(ValueError, match="delivery_percent"):
        _stock(delivery_percent=Decimal("101"))

    with pytest.raises(ValueError, match="requires at least one constituent"):
        MarketBreadthInput(
            observed_on=date(2026, 1, 10),
            advances=0,
            declines=0,
        )

    with pytest.raises(ValueError, match="correlation_to_index"):
        CorrelationInput(
            symbol="HAL",
            correlation_to_index=Decimal("1.1"),
            correlation_to_sector=Decimal("0.2"),
        )


def _stock(
    *,
    symbol: str = "HAL",
    price_change_percent: Decimal = Decimal("1"),
    delivery_percent: Decimal = Decimal("55"),
    delivery_change_percent: Decimal = Decimal("5"),
    volume_change_percent: Decimal = Decimal("10"),
    turnover_value: Decimal = Decimal("1000000000"),
    average_turnover_value: Decimal = Decimal("1000000000"),
    spread_percent: Decimal = Decimal("0.50"),
    volatility_percent: Decimal = Decimal("4"),
) -> StockIntelligenceInput:
    return StockIntelligenceInput(
        symbol=symbol,
        observed_on=date(2026, 1, 10),
        price_change_percent=price_change_percent,
        delivery_percent=delivery_percent,
        delivery_change_percent=delivery_change_percent,
        volume_change_percent=volume_change_percent,
        turnover_value=turnover_value,
        average_turnover_value=average_turnover_value,
        spread_percent=spread_percent,
        volatility_percent=volatility_percent,
    )
