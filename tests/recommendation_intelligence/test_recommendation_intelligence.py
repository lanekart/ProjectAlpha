from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.recommendation_intelligence import (
    ExpectedValueEngine,
    OpportunityCostEngine,
    PortfolioContext,
    RecommendationAction,
    RecommendationCandidate,
    RecommendationDecision,
    RecommendationEngine,
    RecommendationEvidence,
    RecommendationRisk,
)


def test_expected_value_engine_scores_reward_to_risk() -> None:
    assessment = ExpectedValueEngine().assess(_candidate("HAL"))

    assert assessment.symbol == "HAL"
    assert assessment.expected_return == Decimal("0.1200")
    assert assessment.expected_drawdown == Decimal("0.0400")
    assert assessment.reward_to_risk == Decimal("3.0000")
    assert assessment.score > Decimal("0.80")


def test_opportunity_cost_engine_ranks_candidates_against_each_other() -> None:
    hal = _candidate("HAL")
    weak = _candidate(
        "TCS",
        strategy_score=Decimal("0.45"),
        probability_score=Decimal("0.40"),
        market_intelligence_score=Decimal("0.35"),
        expected_return=Decimal("0.02"),
    )

    assessment = OpportunityCostEngine().assess(
        target=hal,
        candidates=(weak, hal),
    )

    assert assessment.symbol == "HAL"
    assert assessment.rank == 1
    assert assessment.candidate_count == 2
    assert assessment.better_candidates == ()
    assert assessment.opportunity_cost_points > Decimal("0")


def test_recommendation_engine_builds_sorted_explainable_reports() -> None:
    strong = _candidate("HAL")
    weak = _candidate(
        "TCS",
        strategy_score=Decimal("0.45"),
        probability_score=Decimal("0.40"),
        market_intelligence_score=Decimal("0.35"),
        liquidity_score=Decimal("0.70"),
        risk_score=Decimal("0.65"),
        expected_return=Decimal("0.02"),
        expected_drawdown=Decimal("0.04"),
    )

    reports = RecommendationEngine().build((weak, strong))

    assert len(reports) == 2
    assert reports[0].symbol == "HAL"
    assert reports[0].decision is RecommendationDecision.STRONG_BUY
    assert reports[0].score > reports[1].score
    assert reports[0].opportunity_cost.rank == 1
    assert any("Why this ranks here:" in line for line in reports[0].explanation)
    assert reports[0].allocation.adjusted_allocation_percent > Decimal("0")


def test_portfolio_context_reduces_existing_position_allocation() -> None:
    report = RecommendationEngine().build(
        (_candidate("HAL"),),
        portfolio=PortfolioContext(
            existing_symbols=("hal",),
            sector_exposure={"defence": Decimal("28")},
            symbol_sector={"hal": "defence"},
            max_single_position_percent=Decimal("8"),
            max_sector_exposure_percent=Decimal("25"),
        ),
    )[0]

    assert report.allocation.adjusted_allocation_percent < (
        report.allocation.base_allocation_percent
    )
    assert report.score_breakdown.portfolio_adjustment_points < Decimal("0")
    assert any("existing position" in reason for reason in report.allocation.reasons)


def test_recommendation_candidate_normalizes_metadata_and_rejects_bad_scores() -> None:
    candidate = _candidate(" infy ", metadata={" sector ": " it "})

    assert candidate.symbol == "INFY"
    assert candidate.metadata["sector"] == "it"

    with pytest.raises(ValueError, match="strategy_score"):
        _candidate("BAD", strategy_score=Decimal("1.2"))


def _candidate(
    symbol: str,
    *,
    strategy_score: Decimal = Decimal("0.92"),
    probability_score: Decimal = Decimal("0.86"),
    market_intelligence_score: Decimal = Decimal("0.90"),
    liquidity_score: Decimal = Decimal("0.82"),
    risk_score: Decimal = Decimal("0.88"),
    expected_return: Decimal = Decimal("0.12"),
    expected_drawdown: Decimal = Decimal("0.04"),
    metadata: dict[str, str] | None = None,
) -> RecommendationCandidate:
    return RecommendationCandidate(
        symbol=symbol,
        observed_on=date(2026, 1, 10),
        action=RecommendationAction.BUY,
        strategy_score=strategy_score,
        probability_score=probability_score,
        market_intelligence_score=market_intelligence_score,
        liquidity_score=liquidity_score,
        risk_score=risk_score,
        expected_return=expected_return,
        expected_drawdown=expected_drawdown,
        expected_holding_period_days=Decimal("18"),
        evidence=(
            RecommendationEvidence(
                label="Institutional accumulation",
                score_points=Decimal("18"),
                max_points=Decimal("20"),
                rationale="Delivery and price participation are both strong.",
            ),
        ),
        risks=(
            RecommendationRisk(
                label="Event risk",
                penalty_points=Decimal("2"),
                rationale="News flow can increase volatility.",
            ),
        ),
        metadata=metadata or {},
    )
