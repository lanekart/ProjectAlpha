from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

import pandas as pd

from alpha.application.intelligence_inputs import (
    DemoIntelligenceInputBuilder,
    HistoricalPriceRepository,
    IntelligenceInputBuilder,
    IntelligenceInputSet,
)
from alpha.explainability import (
    ExplainabilityReport,
    IntelligenceExplainabilityEngine,
)
from alpha.learning_intelligence import concise_adaptive_line
from alpha.market_intelligence import (
    IntelligenceBias,
    MarketIntelligenceCompositeEngine,
    MarketIntelligenceReport,
)
from alpha.portfolio_intelligence import (
    AllocationReasonCode,
    AllocationReport,
    CapitalAllocationEngine,
    CapitalAllocationPlan,
    PortfolioConstructionEngine,
)
from alpha.recommendation_intelligence import (
    EdgeConfidence,
    EntryTriggerStyle,
    EntryZoneBasis,
    RecommendationCandidate,
    RecommendationEngine,
    RecommendationReport,
    StrategyEdgeStats,
    TradeStrategyAction,
    TradeStrategyPlaybook,
    TriggerStatus,
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
    raw_candidates: tuple[RecommendationCandidate, ...] = ()

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
    def from_analysis(
        cls,
        *,
        analysis: pd.DataFrame,
        price_repository: HistoricalPriceRepository | None = None,
        history_window: int = 250,
    ) -> IntelligenceApplicationService:
        """
        Build a production-style service backed by analyzed market data.

        This preserves the deterministic default demo path while exposing a
        clean seam for live wiring.
        """

        return cls(
            input_provider=_AnalysisIntelligenceInputProvider(
                analysis=analysis,
                builder=IntelligenceInputBuilder(
                    price_repository=price_repository,
                    history_window=history_window,
                ),
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
            raw_candidates=inputs.recommendation_candidates,
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
                "Capital Deployment Dashboard:",
            )
        )
        lines.extend(
            _capital_deployment_dashboard_lines(
                recommendations=recommendations,
                allocation_plan=allocation_plan,
            )
        )

        lines.extend(
            (
                "",
                "Recommendations:",
            )
        )
        for index, recommendation in enumerate(recommendations, start=1):
            lines.extend(_recommendation_detail_lines(index, recommendation))

        lines.extend(
            (
                "",
                "Portfolio Allocation:",
                "- Approved Capital: "
                f"{_money_text(allocation_plan.total_allocated_amount)}",
                f"- Remaining Cash: {_money_text(allocation_plan.remaining_cash)}",
                f"- Deployment Count: {_deployment_count(allocation_plan)}",
                "",
                "Positions:",
            )
        )
        for index, allocation_report in enumerate(allocation_plan.reports, start=1):
            allocation_recommendation = recommendation_by_symbol.get(
                allocation_report.symbol
            )
            if allocation_recommendation is None:
                investment_verdict = "UNKNOWN"
                execution_status = "DO NOTHING"
            else:
                investment_verdict = _verdict_label(allocation_recommendation)
                execution_status = _execution_status(allocation_recommendation)
            capital_action = _allocation_capital_action(allocation_report.reasons)

            lines.extend(
                (
                    f"{index}. {allocation_report.symbol}",
                    f"   Investment Verdict: {investment_verdict}",
                    f"   Execution Status: {execution_status}",
                    (
                        "   Allocation Status: "
                        f"{_allocation_status(allocation_report, capital_action)}"
                    ),
                    "   Approved Capital: "
                    f"{_money_text(allocation_report.target_amount)}",
                    "   Target Weight: "
                    f"{_weight_percent(allocation_report.target_weight)}",
                    "   Reason: "
                    f"{_allocation_reason(capital_action, execution_status)}",
                )
            )
            if capital_action == "reduced_deployment":
                lines.extend(_reduced_allocation_reason_lines())

        lines.extend(
            (
                "",
                "Final Decision Summary:",
            )
        )
        lines.extend(
            _final_decision_summary_lines(
                recommendations=recommendations,
                allocation_plan=allocation_plan,
                market_report=market_report,
            )
        )

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


def _deployment_count(allocation_plan: CapitalAllocationPlan) -> int:
    return len(
        tuple(report for report in allocation_plan.reports if report.target_weight > 0)
    )


def _allocation_status(
    allocation_report: AllocationReport,
    capital_action: str,
) -> str:
    if allocation_report.target_weight <= Decimal("0"):
        return "NO ALLOCATION"
    if capital_action == "reduced_deployment":
        return "REDUCED ALLOCATION"
    if capital_action == "full_deployment":
        return "ALLOCATION APPROVED"
    return "NOT ELIGIBLE"


def _allocation_reason(capital_action: str, execution_status: str = "") -> str:
    if capital_action == "full_deployment":
        return "Approved for deployment."
    if capital_action == "reduced_deployment":
        return "Reduced allocation approved by policy."
    if capital_action == "skip":
        if execution_status == "WAIT FOR CONFIRMATION":
            return "Waiting for entry confirmation."
        return "Skipped by allocation policy."
    return _sentence_label(capital_action)


def _capital_deployment_dashboard_lines(
    *,
    recommendations: tuple[RecommendationReport, ...],
    allocation_plan: CapitalAllocationPlan,
) -> tuple[str, ...]:
    recommendation_by_symbol = {
        recommendation.symbol: recommendation for recommendation in recommendations
    }
    deploy_today: list[str] = []
    reserve_watch: list[str] = []
    no_deployment: list[str] = []
    exit_sell: list[str] = []

    for report in allocation_plan.reports:
        recommendation = recommendation_by_symbol.get(report.symbol)
        if recommendation is None:
            continue
        strategy = recommendation.actionable_trade_strategy
        if report.target_weight > Decimal("0") and strategy is not None:
            deploy_today.append(
                f"- {report.symbol}: {strategy.name}, "
                f"{_money_text(report.target_amount)}, "
                f"{_weight_percent(report.target_weight)}, "
                f"risk stop {strategy.stop_rule}, "
                f"holding period {strategy.expected_holding_period}",
            )
        elif recommendation.final_signal == "WATCHLIST":
            reserve_watch.append(
                f"- {report.symbol}: reserve/watch; trigger not confirmed"
            )
        elif recommendation.final_signal in {"SELL", "STRONG_SELL"}:
            exit_sell.append(f"- {report.symbol}: exit/sell")
        else:
            no_deployment.append(f"- {report.symbol}: no deployment")

    return (
        "- Deploy Today:",
        *(deploy_today or ("  none",)),
        "- Reserve / Watch:",
        *(reserve_watch or ("  none",)),
        "- No Deployment:",
        *(no_deployment or ("  none",)),
        "- Exit / Sell:",
        *(exit_sell or ("  none",)),
    )


def _reduced_allocation_reason_lines() -> tuple[str, ...]:
    labels = tuple(
        _sentence_label(code.value)
        for code in (
            AllocationReasonCode.POSITION_SIZE_CAP,
            AllocationReasonCode.VOLATILITY_ADJUSTMENT,
            AllocationReasonCode.CASH_RESERVE_RULE,
        )
    )
    return (
        "   Why Reduced:",
        *(f"   - {label}" for label in labels),
    )


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
    index: int,
    recommendation: RecommendationReport,
) -> tuple[str, ...]:
    unavailable_lines = _data_completion_lines(recommendation)
    lines = [
        f"{index}. {recommendation.symbol} — {_verdict_label(recommendation)}",
        f"   Final Verdict: {_verdict_label(recommendation)}",
        (
            f"   Score: {recommendation.final_score}/100 | "
            f"Confidence: {recommendation.confidence}"
        ),
        f"   Execution Status: {_execution_status(recommendation)}",
        f"   Portfolio Allocation: {_portfolio_allocation_status(recommendation)}",
        f"   Current View: {_current_view(recommendation)}",
        f"   Data Quality: {_recommendation_data_quality(recommendation)}",
        f"   Next Trigger: {_next_trigger_text(recommendation)}",
        f"   Entry Instruction: {_entry_instruction(recommendation)}",
        "",
        "   Action Now:",
        f"   - Execution: {_execution_status(recommendation)}",
        f"   - Actionable Strategy: {_actionable_strategy_text(recommendation)}",
        f"   - Entry: {_action_now_entry_text(recommendation)}",
        f"   - Risk Stop: {_action_now_stop_text(recommendation)}",
        (
            "   - Current Market Price: "
            f"{_money_text(recommendation.current_market_price)}"
        ),
        (
            "   - Current Market R/R to Target 1: "
            f"{_reward_risk_text(recommendation.current_market_risk_reward_ratio)}"
        ),
    ]
    reentry_watch = _reentry_watch_level(recommendation)
    if reentry_watch is not None:
        lines.append(f"   Re-entry Watch Level: {reentry_watch}")
    lines.extend(
        [
            "",
            "   Setup:",
            f"   - Name: {_sentence_label(recommendation.setup_name)}",
            f"   - Category: {_sentence_label(recommendation.setup_category)}",
            f"   - Quality: {recommendation.setup_quality_label}",
            f"   - Stage: {_sentence_label(recommendation.setup_stage)}",
            f"   - Entry Ready: {_yes_no(recommendation.setup_entry_ready)}",
            "",
            "   Trade Strategies:",
        ]
    )
    lines.extend(_trade_strategy_lines(recommendation))
    recommended = _recommended_strategy_lines(recommendation)
    if recommended:
        lines.extend(("", "   Recommended Strategy:"))
        lines.extend(recommended)
    lines.extend(("", "   Risk Controls:"))
    lines.extend(_risk_control_lines(recommendation))
    lines.extend(
        (
            "",
            "   Evidence:",
            f"   - Price/Volume: {_price_volume_sentence(recommendation)}",
            f"   - Trend: {_trend_sentence(recommendation)}",
            f"   - Retracement: {_retracement_sentence(recommendation)}",
            f"   - Candle: {_candle_sentence(recommendation)}",
            "   - Relative Volume: "
            f"{_relative_volume_text(recommendation.relative_volume)}",
            _adaptive_learning_line(recommendation),
        )
    )
    lines.extend(("", "   Why It May Work:"))
    lines.extend(
        f"   - {reason}" for reason in _supporting_trade_reasons(recommendation)
    )
    lines.extend(("", "   Why It May Fail:"))
    lines.extend(f"   - {reason}" for reason in _against_trade_reasons(recommendation))
    if unavailable_lines:
        lines.extend(("", "   Data Completion:"))
        lines.extend(unavailable_lines)
    lines.extend(
        (
            "",
            "   Decision Reason:",
            f"   - {_decision_reason(recommendation)}",
        )
    )
    return tuple(lines)


def _sector_metadata_notice(sector: str) -> str | None:
    if sector.strip().upper() == "UNKNOWN":
        return "Metadata Notice: Sector metadata unavailable from current live feed."
    return None


def _recommendation_data_quality(recommendation: RecommendationReport) -> str:
    return recommendation.metadata.get(
        "data_quality",
        "Partial" if recommendation.unavailable_reasons else "Complete",
    )


def _data_completion_lines(recommendation: RecommendationReport) -> tuple[str, ...]:
    lines: list[str] = []
    for reason in recommendation.unavailable_reasons:
        available = _available_bars_from_reason(reason)
        available_after_fetch = (
            available
            if available is not None
            else str(recommendation.historical_bar_count)
        )
        lines.extend(
            (
                f"   - Requirement: {reason}",
                "   - Archive fetch attempted: yes",
                f"   - Available after fetch: {available_after_fetch}",
                "   - Status: still insufficient",
            )
        )
    return tuple(lines)


def _available_bars_from_reason(reason: str) -> str | None:
    marker = "has "
    if marker not in reason:
        return None
    return reason.rsplit(marker, maxsplit=1)[-1].strip()


def _actionable_strategy_text(recommendation: RecommendationReport) -> str:
    strategy = recommendation.actionable_trade_strategy
    if strategy is None:
        return "none"
    return strategy.name


def _action_now_entry_text(recommendation: RecommendationReport) -> str:
    strategy = recommendation.actionable_trade_strategy
    if strategy is None:
        return "not actionable"
    return _strategy_entry_text(strategy)


def _action_now_stop_text(recommendation: RecommendationReport) -> str:
    strategy = recommendation.actionable_trade_strategy
    if strategy is None:
        return "not applicable"
    return strategy.stop_rule


def _trade_strategy_lines(recommendation: RecommendationReport) -> list[str]:
    if not recommendation.trade_strategies:
        return _trade_plan_lines(recommendation)
    lines: list[str] = []
    for index, strategy in enumerate(recommendation.trade_strategies, start=1):
        lines.extend(
            (
                f"   {index}. {_sentence_label(strategy.name)}",
                f"      Action: {_strategy_action_text(strategy.action)}",
                f"      Strategy Rank: {strategy.strategy_rank.label}",
                (
                    "      Strategy Quality: "
                    f"{_sentence_label(strategy.strategy_rank.quality.value)}"
                ),
                f"      Entry: {_strategy_entry_text(strategy)}",
                "      Entry Zone Basis:",
            )
        )
        lines.extend(_entry_zone_basis_lines(strategy.entry_zone_basis))
        lines.extend(
            (
                f"      Trigger: {strategy.trigger_text}",
                f"      Risk Stop: {strategy.stop_rule}",
            )
        )
        if strategy.trend_invalidation_reference is not None:
            lines.append(
                f"      Trend Reference: {strategy.trend_invalidation_reference}"
            )
        lines.extend(
            (
                "      Targets: "
                + _targets_text(
                    strategy.target_1,
                    strategy.target_2,
                    strategy.target_3,
                ),
                "      Risk / Reward:",
            )
        )
        lines.extend(_risk_reward_lines(strategy))
        lines.extend(("      Strategy Scorecard:",))
        lines.extend(_strategy_scorecard_lines(strategy))
        lines.extend(("      Historical Edge:",))
        lines.extend(_historical_edge_lines(strategy.edge_stats))
        lines.extend(
            (
                "      Fill Probability: "
                f"{_fill_probability_text(strategy.edge_stats)}",
                (
                    "      Position Size: "
                    f"{strategy.position_size_multiplier}x base allocation"
                ),
                f"      Holding Period: {strategy.expected_holding_period}",
                f"      Comment: {strategy.explanation}",
            )
        )
    return lines


def _entry_zone_basis_lines(basis: tuple[EntryZoneBasis, ...]) -> list[str]:
    return [
        (
            "      - "
            f"{_sentence_label(item.basis_type.value)}: "
            f"{_money_text(item.level)} - {item.description}"
        )
        for item in basis
    ]


def _risk_reward_lines(strategy: TradeStrategyPlaybook) -> list[str]:
    entry = strategy.entry_high or strategy.entry_low
    if entry is None or strategy.stop_loss is None:
        return [
            f"      - Entry: {_strategy_entry_text(strategy)}",
            f"      - Risk Stop: {strategy.stop_rule}",
            "      - Reward/Risk to Target 1: unavailable",
        ]
    max_risk = _signed_percent_text(_return_ratio(strategy.stop_loss, entry))
    target_1 = _signed_percent_text(_return_ratio(strategy.target_1, entry))
    target_2 = _signed_percent_text(_return_ratio(strategy.target_2, entry))
    target_3 = _signed_percent_text(_return_ratio(strategy.target_3, entry))
    return [
        f"      - Entry: {_strategy_entry_text(strategy)}",
        f"      - Risk Stop: {strategy.stop_rule}",
        f"      - Max Risk: {max_risk}",
        f"      - Target 1 Upside: {target_1}",
        f"      - Target 2 Upside: {target_2}",
        f"      - Target 3 Upside: {target_3}",
        (f"      - Reward/Risk to Target 1: {_reward_risk_text(strategy.risk_reward)}"),
    ]


def _return_ratio(target: Decimal | None, entry: Decimal) -> Decimal | None:
    if target is None or entry <= Decimal("0"):
        return None
    return (target - entry) / entry


def _reward_risk_text(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"1 : {value.quantize(Decimal('0.01'))}"


def _historical_edge_lines(stats: StrategyEdgeStats | None) -> list[str]:
    if stats is None:
        return [
            "      - Status: Not yet computed",
            "      - Reason: empirical setup matching unavailable",
            "      - Data Fetch Status: not attempted",
        ]
    if (
        stats.confidence is EdgeConfidence.INSUFFICIENT_DATA
        and stats.target_1_hit_rate is None
    ):
        return [
            "      - Status: Not yet computed",
            "      - Dataset Source: local historical bars",
            "      - Lookback Period: available repository history",
            f"      - Historical Bars Used: {stats.sample_size}",
            "      - Matched Setups: 0",
            "      - Match Criteria: setup, trend, volume, DMA state",
            "      - Confidence Level: insufficient data",
            "      - Archive Fetch Status: attempted; empirical matcher unavailable",
            "      - Reason: empirical setup matching unavailable",
        ]
    return [
        f"      - Sample Size: {stats.sample_size}",
        f"      - Target 1 Hit Rate: {_percent_text(stats.target_1_hit_rate)}",
        f"      - Target 2 Hit Rate: {_percent_text(stats.target_2_hit_rate)}",
        f"      - Target 3 Hit Rate: {_percent_text(stats.target_3_hit_rate)}",
        f"      - Stop Loss Hit Rate: {_percent_text(stats.stop_loss_hit_rate)}",
        f"      - Average Return: {_signed_percent_text(stats.average_return)}",
        f"      - Median Holding Period: {_holding_period_text(stats)}",
        f"      - Expectancy: {_signed_percent_text(stats.expectancy)}",
    ]


def _strategy_scorecard_lines(strategy: TradeStrategyPlaybook) -> list[str]:
    scorecard = _strategy_scorecard(strategy)
    return [
        f"      - Risk/Reward Score: {scorecard['risk_reward']}/100",
        f"      - Historical Edge Score: {scorecard['historical_edge']}/100",
        f"      - Trend Strength Score: {scorecard['trend_strength']}/100",
        f"      - Liquidity Score: {scorecard['liquidity']}/100",
        f"      - Volatility Score: {scorecard['volatility']}/100",
        f"      - Execution Ease Score: {scorecard['execution_ease']}/100",
        f"      - Overall Strategy Score: {scorecard['overall']}/100",
    ]


def _strategy_scorecard(strategy: TradeStrategyPlaybook) -> dict[str, int]:
    risk_reward = _score_from_ratio(strategy.risk_reward)
    historical_edge = (
        0
        if strategy.edge_stats is None or strategy.edge_stats.target_1_hit_rate is None
        else int((strategy.edge_stats.target_1_hit_rate * Decimal("100")).to_integral())
    )
    trend_strength = 75 if strategy.action is TradeStrategyAction.BUY_NOW else 65
    liquidity = 70
    volatility = 65 if strategy.strategy_type is not None else 50
    execution_ease = _execution_ease_score(strategy.action)
    overall = int(
        (
            risk_reward
            + historical_edge
            + trend_strength
            + liquidity
            + volatility
            + execution_ease
        )
        / 6
    )
    return {
        "risk_reward": risk_reward,
        "historical_edge": historical_edge,
        "trend_strength": trend_strength,
        "liquidity": liquidity,
        "volatility": volatility,
        "execution_ease": execution_ease,
        "overall": overall,
    }


def _score_from_ratio(value: Decimal | None) -> int:
    if value is None:
        return 0
    return int(min(value * Decimal("25"), Decimal("100")).to_integral())


def _execution_ease_score(action: TradeStrategyAction) -> int:
    if action is TradeStrategyAction.BUY_NOW:
        return 90
    if action is TradeStrategyAction.WAIT_FOR_PULLBACK:
        return 65
    if action is TradeStrategyAction.WAIT_FOR_DEEP_PULLBACK:
        return 40
    if action is TradeStrategyAction.WAIT_FOR_CONFIRMATION:
        return 55
    return 0


def _fill_probability_text(stats: StrategyEdgeStats | None) -> str:
    if stats is None or stats.fill_probability is None:
        return "unavailable"
    if stats.fill_window_days == 0:
        return "Already in entry zone / trigger confirmed"
    window = (
        f" within {stats.fill_window_days} trading days"
        if stats.fill_window_days is not None
        else ""
    )
    return f"{_percent_text(stats.fill_probability)}{window}"


def _recommended_strategy_lines(
    recommendation: RecommendationReport,
) -> list[str]:
    strategy = _recommended_strategy(recommendation)
    if strategy is None:
        return []
    capital = (
        "deploy now only if this is the BUY NOW strategy"
        if strategy.action is TradeStrategyAction.BUY_NOW
        else "reserve only; not deployed now"
    )
    return [
        (
            f"   {strategy.strategy_rank.label} {_sentence_label(strategy.name)} — "
            f"{_sentence_label(strategy.strategy_rank.quality.value)}"
        ),
        f"   - Action: {_strategy_action_text(strategy.action)}",
        f"   - Entry: {_strategy_entry_text(strategy)}",
        f"   - Why: {strategy.strategy_rank.rationale}",
        f"   - Capital: {capital}",
    ]


def _recommended_strategy(
    recommendation: RecommendationReport,
) -> TradeStrategyPlaybook | None:
    ranked = tuple(
        strategy
        for strategy in recommendation.trade_strategies
        if strategy.strategy_rank.rank is not None
        and strategy.action is not TradeStrategyAction.AVOID
    )
    return min(ranked, key=_strategy_rank_key, default=None)


def _strategy_rank_key(strategy: TradeStrategyPlaybook) -> int:
    if strategy.strategy_rank.rank is None:
        return 999
    return strategy.strategy_rank.rank


def _risk_control_lines(recommendation: RecommendationReport) -> list[str]:
    if _is_exit_or_avoid(recommendation):
        return [
            "   - Initial Risk Stop: not applicable",
            "   - Trend Reference: not actionable",
        ]
    strategy = recommendation.actionable_trade_strategy or _recommended_strategy(
        recommendation
    )
    stop = strategy.stop_rule if strategy is not None else "not applicable"
    trend_reference = (
        strategy.trend_invalidation_reference
        if strategy is not None and strategy.trend_invalidation_reference is not None
        else "unavailable"
    )
    lines = [
        f"   - Initial Risk Stop: {stop}",
        f"   - Trend Reference: {trend_reference}",
    ]
    lines.extend(_trailing_stop_lines())
    return lines


def _trailing_stop_lines() -> list[str]:
    return [
        "   - Trailing Stop: Not active until Target 1",
        "   - After Target 1: move stop to breakeven",
        (
            "   - After Target 2: trail using highest valid level among "
            "20-DMA, 2x ATR, and swing low"
        ),
        "   - Current Computed Trail: unavailable until live/next close data",
    ]


def _strategy_action_text(action: TradeStrategyAction) -> str:
    return action.value.replace("_", " ")


def _strategy_entry_text(strategy: TradeStrategyPlaybook) -> str:
    if strategy.entry_low is not None and strategy.entry_high is not None:
        return (
            f"{_money_text(strategy.entry_low)} to {_money_text(strategy.entry_high)}"
        )
    if strategy.entry_low is not None:
        return _money_text(strategy.entry_low)
    if strategy.entry_high is not None:
        return _money_text(strategy.entry_high)
    return "not applicable"


def _targets_text(
    target_1: Decimal | None,
    target_2: Decimal | None,
    target_3: Decimal | None,
) -> str:
    targets = tuple(
        _money_text(target)
        for target in (target_1, target_2, target_3)
        if target is not None
    )
    if not targets:
        return "not applicable"
    return " / ".join(targets)


def _probability_text(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{(value * Decimal('100')).quantize(Decimal('1'))}%"


def _percent_text(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{(value * Decimal('100')).quantize(Decimal('1'))}%"


def _signed_percent_text(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    sign = "+" if value >= Decimal("0") else ""
    return f"{sign}{(value * Decimal('100')).quantize(Decimal('0.1'))}%"


def _holding_period_text(stats: StrategyEdgeStats) -> str:
    if stats.median_holding_period_days is None:
        return "unavailable"
    return f"{stats.median_holding_period_days} sessions"


def _trade_plan_lines(recommendation: RecommendationReport) -> list[str]:
    return [
        (
            "   - Expected Holding Period: "
            f"{recommendation.trade_plan.expected_holding_period}"
        ),
        f"   - Entry Style: {_entry_style(recommendation)}",
        f"   - Entry Zone: {_entry_zone_text(recommendation)}",
        f"   - Entry Trigger: {_entry_trigger_text(recommendation)}",
        f"   - Initial Stop Loss: {_money_text(recommendation.initial_stop_loss)}",
        (f"   - Invalidation: {_invalidation_text(recommendation)}"),
        f"   - ATR: {_money_text(recommendation.trade_plan.atr_value)}",
        f"   - Trailing Stop: {_trailing_stop_text(recommendation)}",
        f"   - Target 1: {_money_text(recommendation.target_1)}",
        f"   - Target 2: {_money_text(recommendation.target_2)}",
        f"   - Target 3: {_money_text(recommendation.target_3)}",
        f"   - Risk/Reward: {_plain_text(recommendation.risk_reward_ratio)}",
        (
            "   - Current Market Risk/Reward: "
            f"{_reward_risk_text(recommendation.current_market_risk_reward_ratio)}"
        ),
    ]


def _entry_zone_text(recommendation: RecommendationReport) -> str:
    low = recommendation.entry_zone_low
    high = recommendation.entry_zone_high
    if low is not None and high is not None:
        return f"{_money_text(low)} to {_money_text(high)}"
    if low is not None:
        return _money_text(low)
    if high is not None:
        return _money_text(high)
    return "unavailable"


def _entry_trigger_text(recommendation: RecommendationReport) -> str:
    trigger = _money_text(recommendation.entry_price)
    style = recommendation.trade_plan.entry_trigger_style
    if recommendation.entry_price is None:
        return "unavailable"
    if style is EntryTriggerStyle.CROSS_ABOVE:
        return f"Price crosses above {trigger} during market hours."
    if style is EntryTriggerStyle.BREAKOUT_WITH_VOLUME:
        return (
            f"Breakout above {trigger} with volume at least 1.5x the "
            "20-day average volume."
        )
    if style is EntryTriggerStyle.RETEST_HOLD:
        return f"Retest holds near support, then price closes above {trigger}."
    if style is EntryTriggerStyle.PULLBACK_TO_LEVEL:
        return f"Pullback enters the zone and closes back above {trigger}."
    if style is EntryTriggerStyle.ENTER_IN_ZONE:
        return "Enter only while price trades inside the planned entry zone."
    return f"Daily close above {trigger}."


def _verdict_label(recommendation: RecommendationReport) -> str:
    if recommendation.final_signal == "STRONG_BUY":
        return "STRONG BUY"
    if recommendation.final_signal == "STRONG_SELL":
        return "STRONG SELL"
    if recommendation.final_signal == "REJECT":
        return "AVOID / REJECT"
    return recommendation.final_signal.replace("_", " ")


def _next_trigger_text(recommendation: RecommendationReport) -> str:
    if _is_exit_or_avoid(recommendation):
        return "Action: Avoid / Exit."
    if recommendation.trigger_status is TriggerStatus.TRIGGER_CONFIRMED:
        return "Already confirmed."
    if recommendation.entry_price is None:
        return "No actionable trigger is available yet."
    trigger = _money_text(recommendation.entry_price)
    if recommendation.trigger_status is TriggerStatus.WAITING_FOR_CROSS_ABOVE:
        return f"Buy only after price crosses above {trigger} during market hours."
    if recommendation.trigger_status is TriggerStatus.WAITING_FOR_VOLUME_CONFIRMATION:
        return (
            f"Buy only after breakout above {trigger} with volume at least "
            "1.5x the 20-day average volume."
        )
    if recommendation.trigger_status is TriggerStatus.INVALID_OR_NOT_ACTIONABLE:
        return "No actionable trigger is available yet."
    return f"Buy only after daily close above {trigger}."


def _entry_instruction(recommendation: RecommendationReport) -> str:
    if _is_exit_or_avoid(recommendation):
        return "Avoid / Exit."
    if (
        recommendation.setup_entry_ready
        and recommendation.trigger_status is TriggerStatus.TRIGGER_CONFIRMED
    ):
        return (
            f"Buy within the entry zone {_entry_zone_text(recommendation)}, "
            "subject to portfolio risk limits."
        )
    return "Wait. Do not enter yet."


def _reentry_watch_level(recommendation: RecommendationReport) -> str | None:
    if not _is_exit_or_avoid(recommendation) or recommendation.entry_price is None:
        return None
    return (
        f"Daily close above {_money_text(recommendation.entry_price)}, "
        "only if setup improves."
    )


def _is_exit_or_avoid(recommendation: RecommendationReport) -> bool:
    return recommendation.final_signal in {
        "AVOID",
        "REJECT",
        "SELL",
        "STRONG_SELL",
    }


def _entry_style(recommendation: RecommendationReport) -> str:
    style = recommendation.trade_plan.entry_trigger_style
    if style is EntryTriggerStyle.BREAKOUT_WITH_VOLUME:
        return "Breakout"
    if style is EntryTriggerStyle.RETEST_HOLD:
        return "Retest"
    if style is EntryTriggerStyle.PULLBACK_TO_LEVEL:
        return "Pullback"
    if style is EntryTriggerStyle.ENTER_IN_ZONE:
        return "Accumulation"
    return "Breakout" if recommendation.setup_category == "BREAKOUT" else "Confirmation"


def _invalidation_text(recommendation: RecommendationReport) -> str:
    dma_20 = recommendation.trade_plan.dma_20_invalidation
    if dma_20 is not None and "20-DMA" in recommendation.invalidation_reason:
        return (
            f"Exit if daily close is below the 20-DMA, currently {_money_text(dma_20)}."
        )
    if recommendation.invalidation_level is None:
        return "unavailable"
    return (
        f"Exit if invalidation level breaks at "
        f"{_money_text(recommendation.invalidation_level)}"
        f"{_reason_suffix(recommendation.invalidation_reason)}."
    )


def _trailing_stop_text(recommendation: RecommendationReport) -> str:
    return (
        "After Target 1, move stop to breakeven. After Target 2, trail using "
        "the higher of the 20-DMA or 2x ATR."
    )


def _execution_status(recommendation: RecommendationReport) -> str:
    if recommendation.final_signal in {"SELL", "STRONG_SELL"}:
        return "EXIT / SELL"
    if recommendation.final_signal in {"AVOID", "REJECT"}:
        return "DO NOTHING"
    if (
        recommendation.setup_stage in {"ENTRY_READY", "ACTIVE"}
        and recommendation.setup_entry_ready
        and recommendation.trigger_status is TriggerStatus.TRIGGER_CONFIRMED
        and recommendation.entry_price is not None
    ):
        return "BUY NOW"
    if recommendation.setup_stage == "READY_FOR_CONFIRMATION":
        return "WAIT FOR CONFIRMATION"
    if recommendation.setup_stage == "BUILDING":
        return "WATCH ONLY"
    if recommendation.setup_stage == "LATE":
        return "HOLD EXISTING"
    if recommendation.final_signal == "HOLD":
        return "HOLD EXISTING"
    if recommendation.final_signal == "REDUCE":
        return "TRIM / REDUCE EXPOSURE"
    return "WATCH ONLY"


def _portfolio_allocation_status(recommendation: RecommendationReport) -> str:
    if recommendation.final_signal in {"SELL", "STRONG_SELL"}:
        return "EXIT POSITION"
    if recommendation.final_signal in {"AVOID", "REJECT"}:
        return "NO ALLOCATION"
    if recommendation.final_signal == "WATCHLIST":
        return "NO ALLOCATION — waiting for confirmation"
    if (
        recommendation.final_signal in {"BUY", "STRONG_BUY"}
        and _execution_status(recommendation) == "BUY NOW"
        and recommendation.trigger_status is TriggerStatus.TRIGGER_CONFIRMED
    ):
        return "ALLOCATION ELIGIBLE — final size set by portfolio policy"
    return "NOT ELIGIBLE"


def _current_view(recommendation: RecommendationReport) -> str:
    if recommendation.final_signal == "WATCHLIST":
        return "Bullish setup, but not entry-ready."
    if recommendation.final_signal in {"BUY", "STRONG_BUY"}:
        return "Setup is entry-ready with a valid trade plan."
    if recommendation.final_signal in {"SELL", "STRONG_SELL"}:
        return "Bearish or invalid setup; risk control takes priority."
    if recommendation.final_signal in {"AVOID", "REJECT"}:
        return "No deployable setup is available."
    return "Hold or monitor; no fresh action is required."


def _reason_suffix(reason: str) -> str:
    if not reason.strip():
        return ""
    return f" ({reason.strip()})"


def _price_volume_sentence(recommendation: RecommendationReport) -> str:
    price = recommendation.price_evidence
    volume = recommendation.volume_evidence
    breakout = "breakout confirmed"
    if price.breakout_state == "BREAKDOWN":
        breakout = "breakdown risk"
    elif price.breakout_state == "NONE":
        breakout = "no breakout yet"
    volume_phrase = "volume confirms the move"
    if volume.selloff_volume_penalty >= Decimal("0.70"):
        volume_phrase = "heavy selloff volume is a warning"
    elif volume.breakout_volume_confirmation < Decimal("0.45"):
        volume_phrase = "volume confirmation is weak"
    return (
        f"{_sentence_label(price.trend_state)}, "
        f"{_sentence_label(price.structure_state)}, {breakout}; "
        f"{volume_phrase}."
    )


def _trend_sentence(recommendation: RecommendationReport) -> str:
    dma_20 = _money_text(recommendation.trade_plan.dma_20_invalidation)
    dma_50 = _money_text(recommendation.dma_50)
    dma_200 = _money_text(recommendation.dma_200)
    return (
        f"{_sentence_label(recommendation.price_evidence.trend_state)} with "
        f"20-DMA {dma_20}, 50-DMA {dma_50}, 200-DMA {dma_200}."
    )


def _retracement_sentence(recommendation: RecommendationReport) -> str:
    support = _money_text(recommendation.support_level_used)
    fibonacci = _money_text(recommendation.nearest_fibonacci_level)
    return (
        f"{_sentence_label(recommendation.price_evidence.retracement_state)} "
        f"retracement near {support}; nearest Fibonacci level {fibonacci}."
    )


def _candle_sentence(recommendation: RecommendationReport) -> str:
    return (
        f"{_sentence_label(recommendation.candle_pattern)} pattern "
        f"{_sentence_label(recommendation.candle_confirmation).lower()} the setup."
    )


def _supporting_trade_reasons(
    recommendation: RecommendationReport,
) -> tuple[str, ...]:
    reasons: list[str] = []
    price = recommendation.price_evidence
    volume = recommendation.volume_evidence
    current = recommendation.current_market_price
    dma_20 = recommendation.trade_plan.dma_20_invalidation
    dma_50 = recommendation.dma_50
    dma_200 = recommendation.dma_200
    moving_average_reason = _moving_average_reason(
        current=current,
        dma_20=dma_20,
        dma_50=dma_50,
        dma_200=dma_200,
    )
    if moving_average_reason is not None:
        reasons.append(moving_average_reason)
    if price.structure_state in {"CONSTRUCTIVE", "HIGHER_HIGH_HIGHER_LOW"}:
        reasons.append(
            "Recent price structure is not showing lower-high/lower-low damage; "
            "buyers are still defending pullbacks."
        )
    if recommendation.entry_price is not None and recommendation.setup_entry_ready:
        reasons.append(
            f"The entry trigger at {_money_text(recommendation.entry_price)} is "
            "already confirmed, so Alpha is not asking the user to wait for a "
            "fresh breakout."
        )
    elif recommendation.entry_price is not None:
        reasons.append(
            f"The next bullish confirmation level is "
            f"{_money_text(recommendation.entry_price)}."
        )
    if volume.breakout_volume_confirmation >= Decimal("0.60"):
        reasons.append(
            "Volume is supporting the setup; relative volume is "
            f"{_relative_volume_text(recommendation.relative_volume)} versus "
            "its recent average."
        )
    current_rr = recommendation.current_market_risk_reward_ratio
    if current_rr is not None and current_rr >= Decimal("2"):
        reasons.append(
            f"From the current price {_money_text(current)}, Target 1 at "
            f"{_money_text(recommendation.target_1)} versus stop "
            f"{_money_text(recommendation.initial_stop_loss)} offers "
            f"{_reward_risk_text(current_rr)}."
        )
    if "CONFIRM" in recommendation.candle_confirmation.upper():
        reasons.append(
            f"Candle evidence supports the setup: "
            f"{_sentence_label(recommendation.candle_pattern)}"
            f"{_candle_level_suffix(recommendation)}."
        )
    if not reasons:
        reasons.append("No strong bullish technical support is available yet.")
    return tuple(reasons[:4])


def _against_trade_reasons(
    recommendation: RecommendationReport,
) -> tuple[str, ...]:
    reasons: list[str] = []
    volume = recommendation.volume_evidence
    if recommendation.final_signal in {"AVOID", "REJECT", "SELL", "STRONG_SELL"}:
        reasons.append("Alpha does not classify this as an actionable long trade.")
    if not recommendation.setup_entry_ready:
        if recommendation.entry_price is not None:
            reasons.append(
                f"Entry is not ready; Alpha requires confirmation above "
                f"{_money_text(recommendation.entry_price)} before a long trade."
            )
        else:
            reasons.append("Entry is not ready; confirmation is still pending.")
    if volume.breakout_volume_confirmation < Decimal("0.45"):
        reasons.append(
            "Volume confirmation is weak; relative volume is "
            f"{_relative_volume_text(recommendation.relative_volume)}, so the "
            "move does not yet show strong participation."
        )
    if volume.selloff_volume_penalty >= Decimal("0.70"):
        reasons.append("Heavy selloff volume is present.")
    current_rr = recommendation.current_market_risk_reward_ratio
    if (
        recommendation.final_signal in {"BUY", "STRONG_BUY", "WATCHLIST", "HOLD"}
        and current_rr is None
    ):
        reasons.append(
            "Current market risk/reward is unavailable or invalid because Alpha "
            "does not have a complete current price, stop, and Target 1."
        )
    elif current_rr is not None and current_rr < Decimal("2"):
        reasons.append(
            f"Current market risk/reward is only {_reward_risk_text(current_rr)}, "
            "below Alpha's preferred 2R threshold."
        )
    adaptive = recommendation.metadata.get("adaptive_evidence_strength", "")
    if adaptive.lower() in {"", "insufficient", "insufficient_sample"}:
        reasons.append("Adaptive historical evidence is still insufficient.")
    if recommendation.unavailable_reasons:
        reasons.append(
            "Some indicator history is incomplete: "
            f"{recommendation.unavailable_reasons[0]}."
        )
    for risk in recommendation.opposing_evidence[:2]:
        label = getattr(risk, "label", "Risk")
        rationale = getattr(risk, "rationale", "")
        text = f"{label}: {rationale}".strip()
        if text not in reasons:
            reasons.append(text)
    if not reasons:
        reasons.append(
            "Primary risk is normal execution risk: gap, slippage, or failed "
            "follow-through."
        )
    return tuple(reasons[:5])


def _moving_average_reason(
    *,
    current: Decimal | None,
    dma_20: Decimal | None,
    dma_50: Decimal | None,
    dma_200: Decimal | None,
) -> str | None:
    if current is None:
        return None
    comparisons: list[str] = []
    if dma_20 is not None:
        relation = "above" if current >= dma_20 else "below"
        comparisons.append(f"{relation} 20-DMA {_money_text(dma_20)}")
    if dma_50 is not None:
        relation = "above" if current >= dma_50 else "below"
        comparisons.append(f"{relation} 50-DMA {_money_text(dma_50)}")
    if dma_200 is not None:
        relation = "above" if current >= dma_200 else "below"
        comparisons.append(f"{relation} 200-DMA {_money_text(dma_200)}")
    if not comparisons:
        return None
    return (
        f"Current market price {_money_text(current)} is "
        + ", ".join(comparisons)
        + "."
    )


def _candle_level_suffix(recommendation: RecommendationReport) -> str:
    parts: list[str] = []
    if recommendation.candle_entry_trigger is not None:
        parts.append(
            f"entry trigger {_money_text(recommendation.candle_entry_trigger)}"
        )
    if recommendation.candle_stop_level is not None:
        parts.append(f"candle stop {_money_text(recommendation.candle_stop_level)}")
    if not parts:
        return "."
    return " using " + " and ".join(parts) + "."


def _decision_reason(recommendation: RecommendationReport) -> str:
    holding_period = (
        f" Expected holding period is "
        f"{recommendation.trade_plan.expected_holding_period} based on "
        f"{recommendation.trade_plan.holding_period_basis}."
    )
    if (
        recommendation.final_signal in {"BUY", "STRONG_BUY"}
        and recommendation.setup_entry_ready
        and recommendation.trigger_status is TriggerStatus.TRIGGER_CONFIRMED
    ):
        return (
            "BUY because the setup is entry-ready, trigger is already "
            "confirmed, and price-volume evidence is constructive."
            f"{holding_period}"
        )
    if recommendation.final_signal == "WATCHLIST":
        return (
            "WATCHLIST because the setup is bullish but confirmation is still "
            "pending. No capital is approved until the trigger confirms."
            f"{holding_period}"
        )
    if _is_exit_or_avoid(recommendation):
        return (
            f"{_verdict_label(recommendation)} because the setup is not "
            "actionable and risk control takes priority."
            f"{holding_period}"
        )
    return (
        f"{_verdict_label(recommendation)} because the detected "
        f"{_sentence_label(recommendation.setup_name)} is in "
        f"{_sentence_label(recommendation.setup_stage)} stage, "
        "entry confirmation is still pending, "
        f"and price-volume evidence is "
        f"{_sentence_label(recommendation.price_evidence.structure_state).lower()}. "
        f"{holding_period.strip()}"
    )


def _sentence_label(value: str) -> str:
    return value.strip().replace("_", " ").replace("/", " / ").title()


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _final_decision_summary_lines(
    *,
    recommendations: tuple[RecommendationReport, ...],
    allocation_plan: CapitalAllocationPlan,
    market_report: MarketIntelligenceReport,
) -> tuple[str, ...]:
    strong_buy_count = _verdict_count(recommendations, "STRONG_BUY")
    buy_count = _verdict_count(recommendations, "BUY")
    watchlist_count = _verdict_count(recommendations, "WATCHLIST")
    hold_count = _verdict_count(recommendations, "HOLD")
    reduce_count = _verdict_count(recommendations, "REDUCE")
    sell_count = sum(
        1
        for recommendation in recommendations
        if recommendation.final_signal in {"SELL", "STRONG_SELL"}
    )
    avoid_count = sum(
        1
        for recommendation in recommendations
        if recommendation.final_signal in {"AVOID", "REJECT"}
    )
    deployable = tuple(
        recommendation
        for recommendation in recommendations
        if recommendation.final_signal in {"BUY", "STRONG_BUY"}
        and _execution_status(recommendation) == "BUY NOW"
        and recommendation.trigger_status is TriggerStatus.TRIGGER_CONFIRMED
    )
    highest_conviction = max(
        recommendations,
        key=lambda recommendation: (
            recommendation.score,
            recommendation.setup_confidence,
        ),
        default=None,
    )
    best_setup = max(
        recommendations,
        key=lambda recommendation: (
            recommendation.setup_confidence,
            recommendation.score,
        ),
        default=None,
    )
    return (
        f"- Strong Buy: {strong_buy_count}",
        f"- Buy: {buy_count}",
        f"- Watchlist: {watchlist_count}",
        f"- Hold: {hold_count}",
        f"- Reduce: {reduce_count}",
        f"- Sell / Strong Sell: {sell_count}",
        f"- Avoid / Reject: {avoid_count}",
        f"- Deployable Ideas: {len(deployable)}",
        f"- Capital Approved: {_money_text(allocation_plan.total_allocated_amount)}",
        f"- Cash Remaining: {_money_text(allocation_plan.remaining_cash)}",
        f"- Highest Conviction: {_summary_symbol(highest_conviction)}",
        f"- Best Setup: {_summary_setup(best_setup)}",
        f"- Main Market Risk: {market_report.correlation.classification}",
    )


def _verdict_count(
    recommendations: tuple[RecommendationReport, ...],
    verdict: str,
) -> int:
    return sum(
        1
        for recommendation in recommendations
        if recommendation.final_signal == verdict
    )


def _summary_symbol(recommendation: RecommendationReport | None) -> str:
    if recommendation is None:
        return "NONE"
    return f"{recommendation.symbol} ({recommendation.final_signal})"


def _summary_setup(recommendation: RecommendationReport | None) -> str:
    if recommendation is None:
        return "NONE"
    return (
        f"{recommendation.symbol} - {_sentence_label(recommendation.setup_name)} "
        f"({recommendation.setup_quality_label})"
    )


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


def _plain_text(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return str(value)


def _money_text(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"₹{value}"


def _relative_volume_text(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value}x"


def _adaptive_learning_line(recommendation: RecommendationReport) -> str:
    metadata = recommendation.metadata
    evidence_strength = metadata.get("adaptive_evidence_strength", "insufficient")
    base_confidence = metadata.get(
        "adaptive_base_confidence",
        recommendation.confidence,
    )
    adjusted_confidence = metadata.get("adaptive_adjusted_confidence", base_confidence)
    sample_count = int(metadata.get("adaptive_sample_count", "0"))
    return concise_adaptive_line(
        evidence_strength=evidence_strength,
        adjusted_confidence=adjusted_confidence,
        base_confidence=base_confidence,
        sample_count=sample_count,
    )


def _dma_20_invalidation_text(level: Decimal | None) -> str:
    if level is None:
        return "20-DMA invalidation unavailable due to insufficient price history."
    return f"Trade invalid if daily close is below 20-DMA, currently ₹{level}."


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
