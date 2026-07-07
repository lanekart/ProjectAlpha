from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.market_intelligence import (
    EmpiricalProbabilityEngine,
    HistoricalOutcome,
    HistoricalSimilarityEngine,
    MarketFeatureSnapshot,
    RecommendationOutcome,
)


def test_market_feature_snapshot_normalizes_symbol_and_features() -> None:
    snapshot = MarketFeatureSnapshot(
        symbol=" hal ",
        observed_on=date(2026, 1, 10),
        features={
            " Delivery_Score ": Decimal("0.82"),
            "oi_score": Decimal("0.64"),
        },
    )

    assert snapshot.symbol == "HAL"
    assert tuple(snapshot.features) == (
        "delivery_score",
        "oi_score",
    )
    assert snapshot.get("DELIVERY_SCORE") == Decimal("0.82")
    assert snapshot.get("missing") == Decimal("0")


def test_market_feature_snapshot_rejects_empty_features() -> None:
    with pytest.raises(ValueError, match="features cannot be empty"):
        MarketFeatureSnapshot(
            symbol="HAL",
            observed_on=date(2026, 1, 10),
            features={},
        )


def test_similarity_engine_sorts_matches_by_similarity() -> None:
    current = _snapshot(
        symbol="HAL",
        observed_on=date(2026, 1, 10),
        delivery=Decimal("0.80"),
        derivatives=Decimal("0.70"),
    )
    close_match = _outcome(
        symbol="HAL",
        observed_on=date(2025, 1, 10),
        delivery=Decimal("0.78"),
        derivatives=Decimal("0.68"),
        outcome=HistoricalOutcome.SUCCESS,
    )
    distant_match = _outcome(
        symbol="HAL",
        observed_on=date(2024, 1, 10),
        delivery=Decimal("0.20"),
        derivatives=Decimal("0.30"),
        outcome=HistoricalOutcome.FAILURE,
    )

    matches = HistoricalSimilarityEngine().match(
        current=current,
        history=(distant_match, close_match),
        action="buy",
    )

    assert len(matches) == 2
    assert matches[0].outcome is close_match
    assert matches[0].similarity > matches[1].similarity


def test_similarity_engine_filters_by_action() -> None:
    current = _snapshot(
        symbol="HAL",
        observed_on=date(2026, 1, 10),
        delivery=Decimal("0.80"),
        derivatives=Decimal("0.70"),
    )
    buy_outcome = _outcome(
        symbol="HAL",
        observed_on=date(2025, 1, 10),
        delivery=Decimal("0.78"),
        derivatives=Decimal("0.68"),
        outcome=HistoricalOutcome.SUCCESS,
        action="BUY",
    )
    sell_outcome = _outcome(
        symbol="HAL",
        observed_on=date(2024, 1, 10),
        delivery=Decimal("0.79"),
        derivatives=Decimal("0.69"),
        outcome=HistoricalOutcome.FAILURE,
        action="SELL",
    )

    matches = HistoricalSimilarityEngine().match(
        current=current,
        history=(buy_outcome, sell_outcome),
        action="BUY",
    )

    assert len(matches) == 1
    assert matches[0].outcome.action == "BUY"


def test_similarity_engine_respects_limit() -> None:
    current = _snapshot(
        symbol="HAL",
        observed_on=date(2026, 1, 10),
        delivery=Decimal("0.80"),
        derivatives=Decimal("0.70"),
    )
    history = tuple(
        _outcome(
            symbol="HAL",
            observed_on=date(2020 + index, 1, 10),
            delivery=Decimal("0.80"),
            derivatives=Decimal("0.70"),
            outcome=HistoricalOutcome.SUCCESS,
        )
        for index in range(5)
    )

    matches = HistoricalSimilarityEngine().match(
        current=current,
        history=history,
        action="BUY",
        limit=2,
    )

    assert len(matches) == 2


def test_probability_engine_estimates_weighted_success_probability() -> None:
    current = _snapshot(
        symbol="HAL",
        observed_on=date(2026, 1, 10),
        delivery=Decimal("0.80"),
        derivatives=Decimal("0.70"),
    )
    history = (
        _outcome(
            symbol="HAL",
            observed_on=date(2025, 1, 10),
            delivery=Decimal("0.80"),
            derivatives=Decimal("0.70"),
            outcome=HistoricalOutcome.SUCCESS,
            realized_return=Decimal("0.12"),
            maximum_drawdown=Decimal("0.03"),
            holding_period_days=18,
        ),
        _outcome(
            symbol="HAL",
            observed_on=date(2024, 1, 10),
            delivery=Decimal("0.30"),
            derivatives=Decimal("0.20"),
            outcome=HistoricalOutcome.FAILURE,
            realized_return=Decimal("-0.04"),
            maximum_drawdown=Decimal("0.08"),
            holding_period_days=9,
        ),
    )
    matches = HistoricalSimilarityEngine().match(
        current=current,
        history=history,
        action="BUY",
    )

    estimate = EmpiricalProbabilityEngine().estimate(
        current=current,
        action="BUY",
        matches=matches,
    )

    assert estimate.symbol == "HAL"
    assert estimate.action == "BUY"
    assert estimate.generated_on == date(2026, 1, 10)
    assert estimate.match_count == 2
    assert estimate.success_probability > Decimal("0.5")
    assert estimate.failure_probability < Decimal("0.5")
    assert estimate.expected_return > Decimal("0")
    assert estimate.expected_drawdown > Decimal("0")
    assert estimate.expected_holding_period_days > Decimal("0")
    assert estimate.is_actionable is True
    assert estimate.evidence[0] == "Based on 2 closed historical matches."


def test_probability_engine_ignores_open_outcomes() -> None:
    current = _snapshot(
        symbol="HAL",
        observed_on=date(2026, 1, 10),
        delivery=Decimal("0.80"),
        derivatives=Decimal("0.70"),
    )
    history = (
        _outcome(
            symbol="HAL",
            observed_on=date(2025, 1, 10),
            delivery=Decimal("0.80"),
            derivatives=Decimal("0.70"),
            outcome=HistoricalOutcome.OPEN,
        ),
    )
    matches = HistoricalSimilarityEngine().match(
        current=current,
        history=history,
        action="BUY",
    )

    estimate = EmpiricalProbabilityEngine().estimate(
        current=current,
        action="BUY",
        matches=matches,
    )

    assert estimate.match_count == 0
    assert estimate.success_probability == Decimal("0.0000")
    assert estimate.failure_probability == Decimal("0.0000")
    assert estimate.is_actionable is False
    assert estimate.evidence == ("No closed historical matches were available.",)


def test_recommendation_outcome_rejects_negative_drawdown() -> None:
    with pytest.raises(ValueError, match="maximum_drawdown cannot be negative"):
        RecommendationOutcome(
            snapshot=_snapshot(
                symbol="HAL",
                observed_on=date(2026, 1, 10),
                delivery=Decimal("0.80"),
                derivatives=Decimal("0.70"),
            ),
            action="BUY",
            outcome=HistoricalOutcome.SUCCESS,
            realized_return=Decimal("0.10"),
            maximum_drawdown=Decimal("-0.01"),
            holding_period_days=10,
        )


def test_similarity_engine_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError, match="limit must be positive"):
        HistoricalSimilarityEngine().match(
            current=_snapshot(
                symbol="HAL",
                observed_on=date(2026, 1, 10),
                delivery=Decimal("0.80"),
                derivatives=Decimal("0.70"),
            ),
            history=(),
            action="BUY",
            limit=0,
        )


def _snapshot(
    *,
    symbol: str,
    observed_on: date,
    delivery: Decimal,
    derivatives: Decimal,
) -> MarketFeatureSnapshot:
    return MarketFeatureSnapshot(
        symbol=symbol,
        observed_on=observed_on,
        features={
            "delivery_score": delivery,
            "derivatives_score": derivatives,
        },
    )


def _outcome(
    *,
    symbol: str,
    observed_on: date,
    delivery: Decimal,
    derivatives: Decimal,
    outcome: HistoricalOutcome,
    action: str = "BUY",
    realized_return: Decimal = Decimal("0.10"),
    maximum_drawdown: Decimal = Decimal("0.03"),
    holding_period_days: int = 12,
) -> RecommendationOutcome:
    return RecommendationOutcome(
        snapshot=_snapshot(
            symbol=symbol,
            observed_on=observed_on,
            delivery=delivery,
            derivatives=derivatives,
        ),
        action=action,
        outcome=outcome,
        realized_return=realized_return,
        maximum_drawdown=maximum_drawdown,
        holding_period_days=holding_period_days,
    )
