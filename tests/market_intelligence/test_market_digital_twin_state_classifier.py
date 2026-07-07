from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.market_intelligence import (
    DeliveryBehavior,
    DerivativesPositioning,
    MarketDirectionBias,
    MarketMood,
    MarketStateAssessment,
    MarketStateClassifier,
    StockMarketState,
)


def test_classifier_detects_bullish_accumulation_with_new_longs() -> None:
    state = StockMarketState(
        symbol=" tcs ",
        observed_on=date(2026, 1, 10),
        price_change_percent=Decimal("4"),
        delivery_percent=Decimal("72"),
        delivery_change_percent=Decimal("18"),
        volume_change_percent=Decimal("44"),
        futures_oi_change_percent=Decimal("12"),
    )

    assessment = MarketStateClassifier().classify(state)

    assert assessment.symbol == "TCS"
    assert assessment.delivery_behavior is DeliveryBehavior.ACCUMULATION
    assert assessment.derivatives_positioning is DerivativesPositioning.NEW_LONGS
    assert assessment.mood is MarketMood.BULLISH_ACCUMULATION
    assert assessment.direction_bias is MarketDirectionBias.POSITIVE
    assert assessment.is_constructive is True
    assert assessment.is_defensive is False
    assert assessment.accumulation_score > assessment.distribution_score
    assert assessment.derivatives_bias_score == Decimal("0.85")


def test_classifier_detects_speculative_rally_without_delivery_support() -> None:
    state = StockMarketState(
        symbol="INFY",
        observed_on=date(2026, 1, 10),
        price_change_percent=Decimal("5"),
        delivery_percent=Decimal("22"),
        delivery_change_percent=Decimal("-8"),
        volume_change_percent=Decimal("55"),
        futures_oi_change_percent=Decimal("20"),
    )

    assessment = MarketStateClassifier().classify(state)

    assert assessment.delivery_behavior is DeliveryBehavior.SPECULATIVE
    assert assessment.derivatives_positioning is DerivativesPositioning.NEW_LONGS
    assert assessment.mood is MarketMood.SPECULATIVE_RALLY
    assert assessment.direction_bias is MarketDirectionBias.NEUTRAL
    assert assessment.speculative_score > Decimal("0.50")


def test_classifier_detects_bearish_distribution() -> None:
    state = StockMarketState(
        symbol="RELIANCE",
        observed_on=date(2026, 1, 10),
        price_change_percent=Decimal("-3"),
        delivery_percent=Decimal("68"),
        delivery_change_percent=Decimal("14"),
        volume_change_percent=Decimal("36"),
        futures_oi_change_percent=Decimal("8"),
    )

    assessment = MarketStateClassifier().classify(state)

    assert assessment.delivery_behavior is DeliveryBehavior.DISTRIBUTION
    assert assessment.derivatives_positioning is DerivativesPositioning.NEW_SHORTS
    assert assessment.mood is MarketMood.BEARISH_DISTRIBUTION
    assert assessment.direction_bias is MarketDirectionBias.NEGATIVE
    assert assessment.is_defensive is True
    assert assessment.distribution_score > Decimal("0.30")


def test_classifier_detects_short_covering_separately_from_new_longs() -> None:
    state = StockMarketState(
        symbol="SBIN",
        observed_on=date(2026, 1, 10),
        price_change_percent=Decimal("3"),
        delivery_percent=Decimal("42"),
        delivery_change_percent=Decimal("1"),
        volume_change_percent=Decimal("18"),
        futures_oi_change_percent=Decimal("-9"),
    )

    assessment = MarketStateClassifier().classify(state)

    assert assessment.derivatives_positioning is DerivativesPositioning.SHORT_COVERING
    assert assessment.delivery_behavior is DeliveryBehavior.NEUTRAL
    assert assessment.mood is MarketMood.NEUTRAL
    assert assessment.derivatives_bias_score == Decimal("0.60")


def test_classifier_detects_long_unwinding_as_exhaustion() -> None:
    state = StockMarketState(
        symbol="HDFCBANK",
        observed_on=date(2026, 1, 10),
        price_change_percent=Decimal("-2"),
        delivery_percent=Decimal("40"),
        delivery_change_percent=Decimal("-3"),
        volume_change_percent=Decimal("10"),
        futures_oi_change_percent=Decimal("-11"),
    )

    assessment = MarketStateClassifier().classify(state)

    assert assessment.derivatives_positioning is DerivativesPositioning.LONG_UNWINDING
    assert assessment.mood is MarketMood.EXHAUSTION
    assert assessment.direction_bias is MarketDirectionBias.NEGATIVE
    assert assessment.derivatives_bias_score == Decimal("0.35")


def test_market_state_validates_delivery_percent() -> None:
    with pytest.raises(ValueError, match="delivery percent"):
        StockMarketState(
            symbol="TCS",
            observed_on=date(2026, 1, 10),
            price_change_percent=Decimal("1"),
            delivery_percent=Decimal("101"),
            delivery_change_percent=Decimal("0"),
            volume_change_percent=Decimal("0"),
            futures_oi_change_percent=Decimal("0"),
        )


def test_assessment_validates_scores_and_reasons() -> None:
    with pytest.raises(ValueError, match="accumulation score"):
        MarketStateAssessment(
            symbol="TCS",
            observed_on=date(2026, 1, 10),
            delivery_behavior=DeliveryBehavior.NEUTRAL,
            derivatives_positioning=DerivativesPositioning.NEUTRAL,
            mood=MarketMood.NEUTRAL,
            direction_bias=MarketDirectionBias.NEUTRAL,
            accumulation_score=Decimal("1.1"),
            distribution_score=Decimal("0"),
            speculative_score=Decimal("0"),
            derivatives_bias_score=Decimal("0.5"),
            reasons=("test",),
        )
