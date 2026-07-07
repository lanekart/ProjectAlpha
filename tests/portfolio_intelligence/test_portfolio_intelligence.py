from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.portfolio_intelligence import (
    AllocationCandidate,
    AllocationConstraint,
    AllocationDecision,
    CapitalAllocationEngine,
    KellySizingEngine,
    PortfolioConstructionEngine,
    PortfolioContext,
    RiskBudget,
    SectorExposure,
)


def test_kelly_sizing_engine_builds_capped_explainable_weight() -> None:
    assessment = KellySizingEngine().assess(
        _candidate("hal"),
        max_position_weight=Decimal("0.10"),
    )

    assert assessment.symbol == "HAL"
    assert assessment.suggested_weight > Decimal("0.06")
    assert assessment.suggested_weight <= Decimal("0.10")
    assert any("reward to risk" in reason for reason in assessment.reasons)


def test_capital_allocation_allocates_best_ranked_candidate_first() -> None:
    context = _context()
    plan = CapitalAllocationEngine().allocate(
        (
            _candidate("tcs", recommendation_score=Decimal("72")),
            _candidate("hal", recommendation_score=Decimal("94")),
        ),
        context,
    )

    assert len(plan.reports) == 2
    assert plan.reports[0].symbol == "HAL"
    assert plan.reports[0].decision is AllocationDecision.ALLOCATE
    assert plan.approved_reports[0].target_amount > Decimal("0")
    assert plan.remaining_cash < context.available_cash


def test_allocation_engine_reduces_highly_correlated_candidate() -> None:
    plan = CapitalAllocationEngine().allocate(
        (
            _candidate(
                "bel",
                correlation_to_portfolio=Decimal("0.88"),
            ),
        ),
        _context(),
    )

    report = plan.reports[0]

    assert report.correlation.penalty == Decimal("0.50")
    assert report.target_weight < report.sizing.suggested_weight
    assert report.decision is AllocationDecision.REDUCE


def test_allocation_engine_blocks_low_conviction_candidate() -> None:
    plan = CapitalAllocationEngine().allocate(
        (
            _candidate(
                "infy",
                recommendation_score=Decimal("61"),
            ),
        ),
        _context(),
    )

    report = plan.reports[0]

    assert report.decision is AllocationDecision.SKIP
    assert report.target_weight == Decimal("0.0000")
    assert AllocationConstraint.LOW_CONVICTION in report.risk_budget.constraints


def test_sector_constraint_caps_allocation() -> None:
    context = PortfolioContext(
        total_capital=Decimal("1000000"),
        available_cash=Decimal("300000"),
        sector_exposures=(
            SectorExposure(
                sector="defence",
                current_weight=Decimal("0.27"),
            ),
        ),
        risk_budget=RiskBudget(max_sector_weight=Decimal("0.30")),
    )

    plan = CapitalAllocationEngine().allocate(
        (_candidate("hal", sector="defence"),),
        context,
    )

    report = plan.reports[0]

    assert report.target_weight <= Decimal("0.0300")
    assert AllocationConstraint.SECTOR_LIMIT in report.risk_budget.constraints


def test_portfolio_construction_engine_delegates_allocation() -> None:
    plan = PortfolioConstructionEngine().construct(
        (_candidate("hal"),),
        _context(),
    )

    assert plan.approved_reports[0].symbol == "HAL"
    assert plan.total_allocated_weight > Decimal("0")


def test_portfolio_context_rejects_invalid_cash() -> None:
    with pytest.raises(ValueError, match="available cash cannot exceed"):
        PortfolioContext(
            total_capital=Decimal("1000000"),
            available_cash=Decimal("1000001"),
        )


def _candidate(
    symbol: str,
    *,
    sector: str = "defence",
    recommendation_score: Decimal = Decimal("94"),
    success_probability: Decimal = Decimal("0.72"),
    expected_return: Decimal = Decimal("0.12"),
    expected_drawdown: Decimal = Decimal("0.04"),
    correlation_to_portfolio: Decimal = Decimal("0.42"),
    liquidity_score: Decimal = Decimal("0.90"),
    conviction_score: Decimal = Decimal("0.88"),
) -> AllocationCandidate:
    return AllocationCandidate(
        symbol=symbol,
        sector=sector,
        observed_on=date(2026, 1, 10),
        recommendation_score=recommendation_score,
        success_probability=success_probability,
        expected_return=expected_return,
        expected_drawdown=expected_drawdown,
        correlation_to_portfolio=correlation_to_portfolio,
        liquidity_score=liquidity_score,
        conviction_score=conviction_score,
        metadata={"source": "recommendation_engine"},
    )


def _context() -> PortfolioContext:
    return PortfolioContext(
        total_capital=Decimal("1000000"),
        available_cash=Decimal("300000"),
        current_positions={"lt": Decimal("0.05")},
        sector_exposures=(
            SectorExposure(
                sector="capital goods",
                current_weight=Decimal("0.05"),
            ),
        ),
        risk_budget=RiskBudget(
            max_position_weight=Decimal("0.10"),
            max_sector_weight=Decimal("0.30"),
            max_correlation=Decimal("0.75"),
            min_recommendation_score=Decimal("70"),
        ),
    )
