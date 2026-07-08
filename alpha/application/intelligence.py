from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from alpha.market_intelligence import (
    CorrelationInput,
    IntelligenceBias,
    MarketBreadthInput,
    MarketIntelligenceCompositeEngine,
    MarketIntelligenceReport,
    SectorPerformanceInput,
    StockIntelligenceInput,
)
from alpha.portfolio_intelligence import (
    AllocationCandidate,
    CapitalAllocationEngine,
    CapitalAllocationPlan,
    PortfolioConstructionEngine,
    RiskBudget,
    SectorExposure,
)
from alpha.portfolio_intelligence import (
    PortfolioContext as AllocationPortfolioContext,
)
from alpha.recommendation_intelligence import (
    PortfolioContext as RecommendationPortfolioContext,
)
from alpha.recommendation_intelligence import (
    RecommendationAction,
    RecommendationCandidate,
    RecommendationEngine,
    RecommendationEvidence,
    RecommendationReport,
    RecommendationRisk,
)

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class IntelligenceRun:
    """End-to-end deterministic intelligence result."""

    observed_on: date
    market_report: MarketIntelligenceReport
    recommendations: tuple[RecommendationReport, ...]
    allocation_plan: CapitalAllocationPlan
    summary_lines: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a deterministic machine-readable intelligence payload."""

        return {
            "metadata": {
                "observed_on": self.observed_on.isoformat(),
            },
            "market": {
                "symbol": self.market_report.symbol,
                "bias": self.market_report.bias.value,
                "composite_score": str(self.market_report.composite_score),
                "accumulation": self.market_report.accumulation.classification,
                "distribution": self.market_report.distribution.classification,
                "liquidity": self.market_report.liquidity.classification,
                "breadth": self.market_report.breadth.classification,
                "sector_rotation": self.market_report.sector_rotation.phase.value,
                "top_sector": self.market_report.sector_rotation.top_sector.sector,
                "correlation_risk": self.market_report.correlation.classification,
                "reasons": list(self.market_report.reasons),
            },
            "recommendations": [
                {
                    "rank": index,
                    "symbol": recommendation.symbol,
                    "action": recommendation.action.value,
                    "decision": recommendation.decision.value,
                    "score": str(recommendation.score),
                    "allocation_percent": str(
                        recommendation.allocation.adjusted_allocation_percent
                    ),
                    "expected_return": str(
                        recommendation.expected_value.expected_return
                    ),
                    "expected_drawdown": str(
                        recommendation.expected_value.expected_drawdown
                    ),
                    "explanation": list(recommendation.explanation),
                }
                for index, recommendation in enumerate(
                    self.recommendations,
                    start=1,
                )
            ],
            "allocation": {
                "generated_on": self.allocation_plan.generated_on.isoformat(),
                "allocated_weight": str(self.allocation_plan.total_allocated_weight),
                "allocated_amount": str(self.allocation_plan.total_allocated_amount),
                "remaining_cash": str(self.allocation_plan.remaining_cash),
                "reasons": list(self.allocation_plan.reasons),
                "reports": [
                    {
                        "symbol": allocation_report.symbol,
                        "sector": allocation_report.sector,
                        "decision": allocation_report.decision.value,
                        "target_weight": str(allocation_report.target_weight),
                        "target_amount": str(allocation_report.target_amount),
                        "reasons": list(allocation_report.reasons),
                        "constraints": [
                            constraint.value
                            for constraint in allocation_report.risk_budget.constraints
                        ],
                    }
                    for allocation_report in self.allocation_plan.reports
                ],
            },
        }


class IntelligenceApplicationService:
    """Orchestrate existing intelligence engines into a user-facing report."""

    def __init__(
        self,
        *,
        market_engine: MarketIntelligenceCompositeEngine | None = None,
        recommendation_engine: RecommendationEngine | None = None,
        allocation_engine: CapitalAllocationEngine | None = None,
        construction_engine: PortfolioConstructionEngine | None = None,
    ) -> None:
        self._market_engine = market_engine or MarketIntelligenceCompositeEngine()
        self._recommendation_engine = recommendation_engine or RecommendationEngine()
        self._allocation_engine = allocation_engine or CapitalAllocationEngine()
        self._construction_engine = construction_engine or PortfolioConstructionEngine(
            self._allocation_engine
        )

    def run(self, *, observed_on: date) -> IntelligenceRun:
        """Run a deterministic product-facing intelligence workflow."""

        market_report = self._market_engine.assess(
            stock=self._stock_input(observed_on),
            breadth=self._breadth_input(observed_on),
            sectors=self._sector_inputs(),
            correlation=self._correlation_input(),
        )
        recommendation_candidates = self._recommendation_candidates(
            observed_on=observed_on,
            market_report=market_report,
        )
        recommendations = self._recommendation_engine.build(
            recommendation_candidates,
            portfolio=self._recommendation_portfolio_context(),
        )
        allocation_plan = self._construction_engine.construct(
            self._allocation_candidates(recommendations),
            self._allocation_portfolio_context(),
        )

        return IntelligenceRun(
            observed_on=observed_on,
            market_report=market_report,
            recommendations=recommendations,
            allocation_plan=allocation_plan,
            summary_lines=self._summary_lines(
                observed_on=observed_on,
                market_report=market_report,
                recommendations=recommendations,
                allocation_plan=allocation_plan,
            ),
        )

    def _stock_input(self, observed_on: date) -> StockIntelligenceInput:
        return StockIntelligenceInput(
            symbol="HAL",
            observed_on=observed_on,
            price_change_percent=Decimal("4.20"),
            delivery_percent=Decimal("68.00"),
            delivery_change_percent=Decimal("14.00"),
            volume_change_percent=Decimal("22.00"),
            turnover_value=Decimal("850000000"),
            average_turnover_value=Decimal("500000000"),
            spread_percent=Decimal("0.18"),
            volatility_percent=Decimal("3.20"),
        )

    def _breadth_input(self, observed_on: date) -> MarketBreadthInput:
        return MarketBreadthInput(
            observed_on=observed_on,
            advances=1220,
            declines=760,
            unchanged=120,
        )

    def _sector_inputs(self) -> tuple[SectorPerformanceInput, ...]:
        return (
            SectorPerformanceInput(
                sector="defence",
                return_percent=Decimal("3.80"),
                breadth_percent=Decimal("72.00"),
                turnover_change_percent=Decimal("18.00"),
            ),
            SectorPerformanceInput(
                sector="capital goods",
                return_percent=Decimal("2.10"),
                breadth_percent=Decimal("64.00"),
                turnover_change_percent=Decimal("11.00"),
            ),
            SectorPerformanceInput(
                sector="banks",
                return_percent=Decimal("0.80"),
                breadth_percent=Decimal("51.00"),
                turnover_change_percent=Decimal("4.00"),
            ),
        )

    def _correlation_input(self) -> CorrelationInput:
        return CorrelationInput(
            symbol="HAL",
            correlation_to_index=Decimal("0.42"),
            correlation_to_sector=Decimal("0.55"),
        )

    def _recommendation_candidates(
        self,
        *,
        observed_on: date,
        market_report: MarketIntelligenceReport,
    ) -> tuple[RecommendationCandidate, ...]:
        market_score = market_report.composite_score
        liquidity_score = market_report.liquidity.score
        risk_score = market_report.correlation.score

        return (
            RecommendationCandidate(
                symbol="HAL",
                observed_on=observed_on,
                action=RecommendationAction.BUY,
                strategy_score=Decimal("0.88"),
                probability_score=Decimal("0.74"),
                market_intelligence_score=market_score,
                liquidity_score=liquidity_score,
                risk_score=risk_score,
                expected_return=Decimal("0.14"),
                expected_drawdown=Decimal("0.045"),
                expected_holding_period_days=Decimal("45"),
                evidence=(
                    RecommendationEvidence(
                        label="Market Intelligence",
                        score_points=market_score * Decimal("25"),
                        max_points=Decimal("25"),
                        rationale=(
                            "constructive accumulation, liquidity, breadth, "
                            "sector leadership, and correlation profile"
                        ),
                    ),
                    RecommendationEvidence(
                        label="Strategy Strength",
                        score_points=Decimal("22"),
                        max_points=Decimal("25"),
                        rationale="momentum setup remains strong",
                    ),
                ),
                risks=(
                    RecommendationRisk(
                        label="Drawdown",
                        penalty_points=Decimal("2"),
                        rationale="expected drawdown remains controlled",
                    ),
                ),
                metadata={"source": "pat-005-orchestration"},
            ),
            RecommendationCandidate(
                symbol="BEL",
                observed_on=observed_on,
                action=RecommendationAction.ACCUMULATE,
                strategy_score=Decimal("0.81"),
                probability_score=Decimal("0.70"),
                market_intelligence_score=max(market_score - Decimal("0.04"), _ZERO),
                liquidity_score=Decimal("0.82"),
                risk_score=Decimal("0.63"),
                expected_return=Decimal("0.11"),
                expected_drawdown=Decimal("0.040"),
                expected_holding_period_days=Decimal("40"),
                evidence=(
                    RecommendationEvidence(
                        label="Sector Leadership",
                        score_points=Decimal("18"),
                        max_points=Decimal("25"),
                        rationale="defence sector remains a top leadership pocket",
                    ),
                ),
                risks=(
                    RecommendationRisk(
                        label="Correlation",
                        penalty_points=Decimal("3"),
                        rationale="sector overlap with the top-ranked candidate",
                    ),
                ),
                metadata={"source": "pat-005-orchestration"},
            ),
            RecommendationCandidate(
                symbol="LT",
                observed_on=observed_on,
                action=RecommendationAction.ACCUMULATE,
                strategy_score=Decimal("0.76"),
                probability_score=Decimal("0.66"),
                market_intelligence_score=Decimal("0.62"),
                liquidity_score=Decimal("0.90"),
                risk_score=Decimal("0.72"),
                expected_return=Decimal("0.095"),
                expected_drawdown=Decimal("0.035"),
                expected_holding_period_days=Decimal("50"),
                evidence=(
                    RecommendationEvidence(
                        label="Liquidity",
                        score_points=Decimal("13.50"),
                        max_points=Decimal("15"),
                        rationale="high liquidity supports institutional sizing",
                    ),
                ),
                risks=(
                    RecommendationRisk(
                        label="Opportunity Cost",
                        penalty_points=Decimal("2"),
                        rationale="higher-ranked opportunities are available",
                    ),
                ),
                metadata={"source": "pat-005-orchestration"},
            ),
        )

    def _recommendation_portfolio_context(self) -> RecommendationPortfolioContext:
        return RecommendationPortfolioContext(
            existing_symbols=("LT",),
            sector_exposure={
                "DEFENCE": Decimal("12"),
                "CAPITAL GOODS": Decimal("8"),
            },
            symbol_sector={
                "HAL": "DEFENCE",
                "BEL": "DEFENCE",
                "LT": "CAPITAL GOODS",
            },
            max_single_position_percent=Decimal("10"),
            max_sector_exposure_percent=Decimal("25"),
        )

    def _allocation_candidates(
        self,
        recommendations: Iterable[RecommendationReport],
    ) -> tuple[AllocationCandidate, ...]:
        sector_by_symbol = {
            "HAL": "defence",
            "BEL": "defence",
            "LT": "capital goods",
        }
        correlation_by_symbol = {
            "HAL": Decimal("0.42"),
            "BEL": Decimal("0.68"),
            "LT": Decimal("0.48"),
        }
        liquidity_by_symbol = {
            "HAL": Decimal("0.90"),
            "BEL": Decimal("0.82"),
            "LT": Decimal("0.90"),
        }

        return tuple(
            AllocationCandidate(
                symbol=recommendation.symbol,
                sector=sector_by_symbol.get(recommendation.symbol, "unknown"),
                observed_on=recommendation.observed_on,
                recommendation_score=recommendation.score,
                success_probability=recommendation.expected_value.score,
                expected_return=recommendation.expected_value.expected_return,
                expected_drawdown=recommendation.expected_value.expected_drawdown,
                correlation_to_portfolio=correlation_by_symbol.get(
                    recommendation.symbol,
                    Decimal("0.50"),
                ),
                liquidity_score=liquidity_by_symbol.get(
                    recommendation.symbol,
                    Decimal("0.60"),
                ),
                conviction_score=recommendation.score / Decimal("100"),
                metadata={"source": "recommendation_intelligence"},
            )
            for recommendation in recommendations
        )

    def _allocation_portfolio_context(self) -> AllocationPortfolioContext:
        return AllocationPortfolioContext(
            total_capital=Decimal("1000000"),
            available_cash=Decimal("300000"),
            current_positions={"LT": Decimal("0.08")},
            sector_exposures=(
                SectorExposure(
                    sector="defence",
                    current_weight=Decimal("0.12"),
                ),
                SectorExposure(
                    sector="capital goods",
                    current_weight=Decimal("0.08"),
                ),
            ),
            risk_budget=RiskBudget(
                max_position_weight=Decimal("0.10"),
                max_sector_weight=Decimal("0.25"),
                max_correlation=Decimal("0.75"),
                max_portfolio_risk_weight=Decimal("0.35"),
                min_recommendation_score=Decimal("60"),
            ),
        )

    def _summary_lines(
        self,
        *,
        observed_on: date,
        market_report: MarketIntelligenceReport,
        recommendations: tuple[RecommendationReport, ...],
        allocation_plan: CapitalAllocationPlan,
    ) -> tuple[str, ...]:
        lines = [
            "Project Alpha Intelligence Report",
            "",
            f"Observed On      : {observed_on.isoformat()}",
            f"Market Symbol    : {market_report.symbol}",
            f"Market Bias      : {market_report.bias.value}",
            f"Composite Score  : {market_report.composite_score}",
            f"Accumulation     : {market_report.accumulation.classification}",
            f"Distribution     : {market_report.distribution.classification}",
            f"Liquidity        : {market_report.liquidity.classification}",
            f"Breadth          : {market_report.breadth.classification}",
            f"Sector Rotation  : {market_report.sector_rotation.phase.value}",
            f"Top Sector       : {market_report.sector_rotation.top_sector.sector}",
            f"Correlation Risk : {market_report.correlation.classification}",
            "",
            "Market Intelligence Reasons:",
        ]
        lines.extend(f"- {reason}" for reason in market_report.reasons)

        lines.extend(
            (
                "",
                "Recommendations:",
            )
        )
        for index, recommendation in enumerate(recommendations, start=1):
            lines.append(
                f"{index}. {recommendation.symbol}: {recommendation.decision.value} "
                f"score={recommendation.score} allocation="
                f"{recommendation.allocation.adjusted_allocation_percent}%"
            )
            for explanation in recommendation.explanation[:5]:
                lines.append(f"   - {explanation}")

        lines.extend(
            (
                "",
                "Portfolio Allocation:",
                f"Allocated Weight : {allocation_plan.total_allocated_weight}",
                f"Allocated Amount : {allocation_plan.total_allocated_amount}",
                f"Remaining Cash   : {allocation_plan.remaining_cash}",
            )
        )
        for allocation_report in allocation_plan.reports:
            lines.append(
                f"- {allocation_report.symbol}: {allocation_report.decision.value} "
                f"target_weight={allocation_report.target_weight} "
                f"target_amount={allocation_report.target_amount}"
            )
            for reason in allocation_report.reasons[:3]:
                lines.append(f"  - {reason}")

        if market_report.bias is IntelligenceBias.NEGATIVE:
            lines.extend(
                (
                    "",
                    "Warning:",
                    "- Negative market bias; review allocations before execution.",
                )
            )

        return tuple(lines)


__all__ = ["IntelligenceApplicationService", "IntelligenceRun"]
