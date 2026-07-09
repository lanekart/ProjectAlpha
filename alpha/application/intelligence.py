from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

import pandas as pd

from alpha.application.intelligence_inputs import (
    DemoIntelligenceInputBuilder,
    IntelligenceInputBuilder,
    IntelligenceInputSet,
)
from alpha.explainability import (
    ExplainabilityReport,
    IntelligenceExplainabilityEngine,
)
from alpha.market_intelligence import (
    IntelligenceBias,
    MarketIntelligenceCompositeEngine,
    MarketIntelligenceReport,
)
from alpha.portfolio_intelligence import (
    CapitalAllocationEngine,
    CapitalAllocationPlan,
    PortfolioConstructionEngine,
)
from alpha.recommendation_intelligence import (
    RecommendationEngine,
    RecommendationReport,
)


class IntelligenceInputProvider(Protocol):
    def build(self, *, observed_on: date) -> IntelligenceInputSet:
        """Build engine-ready deterministic intelligence inputs."""
        ...


@dataclass(frozen=True, slots=True)
class IntelligenceRun:
    """End-to-end deterministic intelligence result."""

    observed_on: date
    market_report: MarketIntelligenceReport
    recommendations: tuple[RecommendationReport, ...]
    allocation_plan: CapitalAllocationPlan
    summary_lines: tuple[str, ...]
    explainability_report: ExplainabilityReport

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
            "explainability": self.explainability_report.as_dict(),
        }


class IntelligenceApplicationService:
    """Orchestrate existing intelligence engines into a user-facing report."""

    def __init__(
        self,
        *,
        input_provider: IntelligenceInputProvider | None = None,
        market_engine: MarketIntelligenceCompositeEngine | None = None,
        recommendation_engine: RecommendationEngine | None = None,
        allocation_engine: CapitalAllocationEngine | None = None,
        construction_engine: PortfolioConstructionEngine | None = None,
        explainability_engine: IntelligenceExplainabilityEngine | None = None,
    ) -> None:
        self._input_provider = input_provider or DemoIntelligenceInputBuilder()
        self._market_engine = market_engine or MarketIntelligenceCompositeEngine()
        self._recommendation_engine = recommendation_engine or RecommendationEngine()
        self._allocation_engine = allocation_engine or CapitalAllocationEngine()
        self._construction_engine = construction_engine or PortfolioConstructionEngine(
            self._allocation_engine
        )
        self._explainability_engine = (
            explainability_engine or IntelligenceExplainabilityEngine()
        )

    @classmethod
    def from_analysis(cls, *, analysis: pd.DataFrame) -> IntelligenceApplicationService:
        """
        Build a production-style service backed by analyzed market data.

        This preserves the deterministic default demo path while exposing a
        clean seam for live wiring.
        """

        return cls(
            input_provider=_AnalysisIntelligenceInputProvider(
                analysis=analysis,
                builder=IntelligenceInputBuilder(),
            )
        )

    def run(self, *, observed_on: date) -> IntelligenceRun:
        """Run a deterministic product-facing intelligence workflow."""

        inputs = self._input_provider.build(observed_on=observed_on)

        market_report = self._market_engine.assess(
            stock=inputs.stock,
            breadth=inputs.breadth,
            sectors=inputs.sectors,
            correlation=inputs.correlation,
        )
        recommendations = self._recommendation_engine.build(
            inputs.recommendation_candidates,
            portfolio=inputs.recommendation_portfolio_context,
        )
        allocation_plan = self._construction_engine.construct(
            inputs.allocation_candidates(recommendations),
            inputs.allocation_portfolio_context,
        )
        explainability_report = self._explainability_engine.explain(
            observed_on=observed_on.isoformat(),
            market_report=market_report,
            recommendations=recommendations,
            allocation_plan=allocation_plan,
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
            explainability_report=explainability_report,
        )

    def _summary_lines(
        self,
        *,
        observed_on: date,
        market_report: MarketIntelligenceReport,
        recommendations: tuple[RecommendationReport, ...],
        allocation_plan: CapitalAllocationPlan,
    ) -> tuple[str, ...]:
        recommendation_by_symbol = {
            recommendation.symbol: recommendation for recommendation in recommendations
        }
        top_sector = market_report.sector_rotation.top_sector.sector
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
            f"Top Sector       : {top_sector}",
        ]
        metadata_notice = _sector_metadata_notice(top_sector)
        if metadata_notice is not None:
            lines.append(metadata_notice)
        lines.extend(
            (
                f"Correlation Risk : {market_report.correlation.classification}",
                "",
                "Market Intelligence Reasons:",
            )
        )
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
                f"score={recommendation.score} action="
                f"{recommendation.action.value} raw_allocation_hint="
                f"{recommendation.allocation.adjusted_allocation_percent}%"
            )
            driver_line = _recommendation_driver_line(recommendation)
            if driver_line is not None:
                lines.append(driver_line)
            lines.extend(_recommendation_detail_lines(recommendation))
            for explanation in recommendation.explanation[:5]:
                lines.append(f"   - {explanation}")

        lines.extend(
            (
                "",
                "Portfolio Allocation:",
                "Approved Deployment Weight : "
                f"{allocation_plan.total_allocated_weight}",
                "Approved Deployment Amount : "
                f"{allocation_plan.total_allocated_amount}",
                f"Remaining Cash              : {allocation_plan.remaining_cash}",
                _approved_deployment_summary(allocation_plan.reasons),
            )
        )
        lines.extend(("", "Portfolio Summary:"))
        lines.extend(_portfolio_summary_lines(recommendations, allocation_plan))
        for allocation_report in allocation_plan.reports:
            allocation_recommendation = recommendation_by_symbol.get(
                allocation_report.symbol
            )
            if allocation_recommendation is None:
                recommendation_context = "recommendation=UNKNOWN"
            else:
                recommendation_context = (
                    f"recommendation={allocation_recommendation.decision.value} "
                    f"action={allocation_recommendation.action.value} "
                    f"score={allocation_recommendation.score}"
                )
            capital_action = _allocation_capital_action(allocation_report.reasons)

            lines.append(
                f"- {allocation_report.symbol}: {allocation_report.decision.value} "
                f"capital_action={capital_action} "
                f"target_weight={allocation_report.target_weight} "
                f"target_amount={allocation_report.target_amount} "
                f"{recommendation_context}"
            )
            for reason in allocation_report.reasons[:4]:
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


def _allocation_capital_action(reasons: tuple[str, ...]) -> str:
    prefix = "capital action: "
    for reason in reasons:
        if reason.startswith(prefix):
            return reason.removeprefix(prefix)
    return "unknown"


def _approved_deployment_summary(reasons: tuple[str, ...]) -> str:
    prefix = "approved capital deployments: "
    for reason in reasons:
        if reason.startswith(prefix):
            return reason
    return "approved capital deployments: 0"


def _recommendation_driver_line(
    recommendation: RecommendationReport,
) -> str | None:
    driver_labels = [evidence.label for evidence in recommendation.supporting_evidence]
    driver_labels.extend(risk.label for risk in recommendation.opposing_evidence)
    drivers = tuple(
        dict.fromkeys(_driver_slug(label) for label in driver_labels if label.strip())
    )
    if not drivers:
        return None
    return f"   drivers: {', '.join(drivers[:4])}"


def _recommendation_detail_lines(
    recommendation: RecommendationReport,
) -> tuple[str, ...]:
    price = recommendation.price_evidence
    volume = recommendation.volume_evidence
    atr_value = _optional_decimal_text(recommendation.trade_plan.atr_value)
    dma_20 = _optional_decimal_text(recommendation.trade_plan.dma_20_invalidation)
    candle_entry = _optional_decimal_text(recommendation.candle_entry_trigger)
    candle_stop = _optional_decimal_text(recommendation.candle_stop_level)
    candle_invalidation = _optional_decimal_text(
        recommendation.candle_invalidation_level
    )

    return (
        "   Recommendation Output:",
        f"      final_signal={recommendation.final_signal}",
        f"      final_score={recommendation.final_score}",
        f"      confidence={recommendation.confidence}",
        "      Price-Volume Evidence: "
        f"price_trend={price.trend_state}; "
        f"structure={price.structure_state}; "
        f"breakout={price.breakout_state}; "
        f"retracement={price.retracement_state}; "
        f"support_resistance={price.support_resistance_state}; "
        f"close_strength={price.close_strength}; "
        f"volatility={price.volatility_state}; "
        f"price_score={price.price_score}; "
        f"volume_vs_average={volume.volume_vs_average}; "
        f"volume_score={volume.volume_score}; "
        f"breakout_volume_confirmation={volume.breakout_volume_confirmation}; "
        f"selloff_volume_penalty={volume.selloff_volume_penalty}",
        "      Trend Evidence: "
        f"20/50/200 trend points="
        f"{recommendation.score_breakdown.trend_structure_points}; "
        f"price trend={price.trend_state}",
        "      Retracement Evidence: "
        f"score={recommendation.retracement_score}; "
        f"weight={recommendation.retracement_weight}; "
        f"zone={recommendation.retracement_zone}; "
        f"nearest_fibonacci_level={recommendation.nearest_fibonacci_level}; "
        f"swing_high={recommendation.swing_high}; "
        f"swing_low={recommendation.swing_low}; "
        f"support_level_used={recommendation.support_level_used}",
        "      Candle Pattern Evidence: "
        f"pattern={recommendation.candle_pattern}; "
        f"score={recommendation.candle_score}; "
        f"weight={recommendation.candle_weight}; "
        f"confirmation={recommendation.candle_confirmation}; "
        f"entry_trigger={candle_entry}; "
        f"stop_level={candle_stop}; "
        f"invalidation_level={candle_invalidation}; "
        f"explanation={recommendation.candle_explanation}",
        "      Entry Zone: "
        f"{recommendation.entry_zone_low} to {recommendation.entry_zone_high}",
        f"      Entry Trigger: {recommendation.entry_price}",
        f"      Initial Stop Loss: {recommendation.initial_stop_loss}",
        "      20-DMA Invalidation: "
        f"Trade invalid if daily close is below 20-DMA, currently {dma_20}.",
        f"      ATR Value: {atr_value}",
        f"      Trailing Stop: {recommendation.trailing_stop_strategy}",
        f"      Target 1: {recommendation.target_1}",
        f"      Target 2: {recommendation.target_2}",
        f"      Target 3: {recommendation.target_3}",
        f"      Risk-Reward Ratio: {recommendation.risk_reward_ratio}",
        "      Invalidation: "
        f"{recommendation.invalidation_level} "
        f"({recommendation.invalidation_reason})",
        f"      Why: {recommendation.trade_plan_explanation}",
    )


def _sector_metadata_notice(sector: str) -> str | None:
    if sector.strip().upper() == "UNKNOWN":
        return "Metadata Notice: Sector metadata unavailable from current live feed."
    return None


def _driver_slug(value: str) -> str:
    normalized = []
    previous_was_separator = False
    for character in value.strip().lower():
        if character.isalnum():
            normalized.append(character)
            previous_was_separator = False
        elif not previous_was_separator:
            normalized.append("_")
            previous_was_separator = True
    return "".join(normalized).strip("_")


def _portfolio_summary_lines(
    recommendations: tuple[RecommendationReport, ...],
    allocation_plan: CapitalAllocationPlan,
) -> tuple[str, ...]:
    approved_reports = tuple(
        report
        for report in allocation_plan.reports
        if report.target_weight > Decimal("0")
    )
    highest_conviction = min(
        recommendations,
        key=lambda recommendation: (
            -recommendation.score,
            recommendation.symbol,
        ),
        default=None,
    )
    largest_position = min(
        approved_reports,
        key=lambda report: (
            -report.target_weight,
            report.symbol,
        ),
        default=None,
    )

    highest_conviction_symbol = (
        highest_conviction.symbol
        if highest_conviction is not None and approved_reports
        else "NONE"
    )
    largest_position_text = "NONE"
    if largest_position is not None:
        largest_position_text = (
            f"{largest_position.symbol} "
            f"{_weight_percent(largest_position.target_weight)}"
        )

    return (
        f"Approved Deployments : {len(approved_reports)}",
        f"Approved Capital     : {allocation_plan.total_allocated_amount}",
        f"Cash Remaining       : {allocation_plan.remaining_cash}",
        f"Highest Conviction   : {highest_conviction_symbol}",
        f"Largest Position     : {largest_position_text}",
    )


def _weight_percent(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(Decimal('0.01'))}%"


def _optional_decimal_text(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return str(value)


@dataclass(frozen=True, slots=True)
class _AnalysisIntelligenceInputProvider:
    analysis: pd.DataFrame
    builder: IntelligenceInputBuilder

    def build(self, *, observed_on: date) -> IntelligenceInputSet:
        return self.builder.build(observed_on=observed_on, analysis=self.analysis)


__all__ = [
    "IntelligenceApplicationService",
    "IntelligenceInputProvider",
    "IntelligenceRun",
    "_recommendation_detail_lines",
]
