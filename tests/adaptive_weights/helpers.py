from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from alpha.adaptive_weights.models import (
    AlphaComponent,
    CompletedOutcomeEvidence,
    ComponentScore,
    EvidencePartition,
    ResearchPerformance,
    canonical_weight_set,
)


def completed_evidence(
    index: int,
    *,
    partition: EvidencePartition = EvidencePartition.DEVELOPMENT,
    setup: str = "MOMENTUM_BREAKOUT",
    regime: str = "BULL",
    sector: str = "FINANCIALS",
    horizon: str = "20D",
    policy: str = "ALPHA_CANONICAL",
    score_overrides: dict[AlphaComponent, Decimal] | None = None,
    realised_r: Decimal | None = None,
    lineage_overrides: dict[AlphaComponent, str] | None = None,
) -> CompletedOutcomeEvidence:
    scores = {
        component: Decimal(((index + 1) * (position * 2 + 3)) % 17) / Decimal("16")
        for position, component in enumerate(AlphaComponent)
    }
    scores.update(score_overrides or {})
    lineages = {component: f"fixture.{component.value}" for component in AlphaComponent}
    lineages.update(lineage_overrides or {})
    outcome_r = (
        realised_r
        if realised_r is not None
        else (
            Decimal("1.4") * (scores[AlphaComponent.PRICE_STRUCTURE] - Decimal("0.5"))
            - Decimal("0.9") * (scores[AlphaComponent.VOLUME] - Decimal("0.5"))
            + Decimal("0.1")
        )
    )
    entry = Decimal("100")
    stop = Decimal("95")
    exit_price = entry + outcome_r * (entry - stop)
    return CompletedOutcomeEvidence(
        recommendation_id=f"REC-{partition.value}-{index:04d}",
        candidate_id=f"CAND-{index:04d}",
        symbol=f"SYM{index % 7}",
        exchange="NSE",
        decision_date=date(2020, 1, 1) + timedelta(days=index),
        setup_family=setup,
        strategy_family="ALPHA_DIRECTIONAL",
        market_regime=regime,
        sector=sector,
        holding_horizon=horizon,
        component_scores=tuple(
            ComponentScore(
                component=component,
                score=scores[component],
                available=True,
                source_lineage=lineages[component],
            )
            for component in AlphaComponent
        ),
        canonical_weights=canonical_weight_set(),
        entry=entry,
        stop=stop,
        exit=exit_price,
        realized_return=(exit_price - entry) / entry * Decimal("100"),
        realized_r_multiple=outcome_r,
        winner=outcome_r > Decimal("0"),
        transaction_costs=Decimal("0.10"),
        dataset_version="FIXTURE-DATA-V1",
        policy_version=policy,
        provenance="tests.completed_outcome_fixture",
        partition=partition,
        approved=index % 2 == 0,
        stop_policy="FIXED_1R",
        exit_policy="TIME_EXIT",
        exit_date=date(2020, 1, 1) + timedelta(days=index + 20),
    )


def performance(
    *,
    expectancy: str,
    win_rate: str,
    profit_factor: str,
    drawdown: str,
    trades: int = 50,
    average_winner: str = "1.5",
    average_loser: str = "-1",
) -> ResearchPerformance:
    return ResearchPerformance(
        expectancy=Decimal(expectancy),
        win_rate=Decimal(win_rate),
        average_winner_r=Decimal(average_winner),
        average_loser_r=Decimal(average_loser),
        profit_factor=Decimal(profit_factor),
        max_drawdown=Decimal(drawdown),
        trade_count=trades,
        average_holding_period=Decimal("12"),
        turnover=Decimal("4"),
        transaction_costs=Decimal("0.2"),
        sector_concentration=Decimal("0.3"),
        setup_concentration=Decimal("0.4"),
    )
