from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from hashlib import sha256
from typing import TYPE_CHECKING

from alpha.performance_intelligence.ledger import RecommendationLedgerRepository
from alpha.performance_intelligence.models import RecommendationLedgerEntry
from alpha.recommendation_intelligence.models import RecommendationReport

if TYPE_CHECKING:
    from alpha.application.runtime_models import RuntimeResult


class RecommendationPerformanceRecorder:
    """Build and persist recommendation ledger rows from runtime output."""

    def __init__(self, repository: RecommendationLedgerRepository) -> None:
        self.repository = repository

    def record_runtime(self, runtime_result: RuntimeResult) -> int:
        run_id = source_run_id(runtime_result)
        generated_at = datetime.combine(
            runtime_result.observed_on,
            time.min,
            tzinfo=UTC,
        )
        allocation_by_symbol = {
            report.symbol: report
            for report in runtime_result.intelligence_run.allocation_plan.reports
        }
        entries = tuple(
            recommendation_to_ledger_entry(
                recommendation=recommendation,
                generated_at=generated_at,
                source_run_id=run_id,
                market_regime=runtime_result.intelligence_run.market_report.bias.value,
                allocation_report=allocation_by_symbol.get(recommendation.symbol),
            )
            for recommendation in runtime_result.intelligence_run.recommendations
        )
        return self.repository.save_entries(entries)


def source_run_id(runtime_result: RuntimeResult) -> str:
    existing = runtime_result.metadata.attributes.get("run_id")
    if existing:
        return existing
    return "|".join(
        (
            runtime_result.mode.value,
            runtime_result.workflow,
            runtime_result.observed_on.isoformat(),
        )
    )


def recommendation_to_ledger_entry(
    *,
    recommendation: RecommendationReport,
    generated_at: datetime,
    source_run_id: str,
    market_regime: str | None,
    allocation_report: object | None = None,
) -> RecommendationLedgerEntry:
    recommendation_id = _recommendation_id(
        source_run_id=source_run_id,
        symbol=recommendation.symbol,
        generated_at=generated_at,
    )
    strategy = recommendation.actionable_trade_strategy or next(
        iter(recommendation.trade_strategies),
        None,
    )
    edge_stats = strategy.edge_stats if strategy is not None else None
    approved_deployment = _allocation_amount(allocation_report)
    entry_price = recommendation.entry_price or recommendation.entry_zone_high
    quantity = _quantity(amount=approved_deployment, price=entry_price)

    return RecommendationLedgerEntry(
        recommendation_id=recommendation_id,
        generated_at=generated_at,
        symbol=recommendation.symbol,
        final_verdict=recommendation.final_signal,
        confidence=recommendation.confidence,
        score=recommendation.final_score,
        setup_type=recommendation.setup_name,
        setup_state=recommendation.setup_stage,
        entry_zone_low=recommendation.entry_zone_low,
        entry_zone_high=recommendation.entry_zone_high,
        confirmation_entry=recommendation.trade_plan.confirmation_entry,
        stop_loss=recommendation.initial_stop_loss,
        target_1=recommendation.target_1,
        target_2=recommendation.target_2,
        target_3=recommendation.target_3,
        trailing_stop_strategy=recommendation.trailing_stop_strategy,
        holding_period=recommendation.trade_plan.expected_holding_period,
        market_regime=market_regime,
        sector=recommendation.metadata.get("sector"),
        key_indicator_snapshot={
            "price_trend": recommendation.price_evidence.trend_state,
            "price_structure": recommendation.price_evidence.structure_state,
            "price_breakout": recommendation.price_evidence.breakout_state,
            "retracement_state": (recommendation.price_evidence.retracement_state),
            "candle_pattern": recommendation.candle_pattern,
            "price_score": _decimal_text(recommendation.price_evidence.price_score),
            "volume_score": _decimal_text(recommendation.volume_evidence.volume_score),
            "relative_volume": _optional_decimal_text(recommendation.relative_volume),
            "dma_20": _optional_decimal_text(
                recommendation.trade_plan.dma_20_invalidation
            ),
            "dma_50": _optional_decimal_text(recommendation.dma_50),
            "dma_200": _optional_decimal_text(recommendation.dma_200),
            "atr": _optional_decimal_text(recommendation.trade_plan.atr_value),
        },
        statistical_edge_snapshot={
            "strategy": strategy.name if strategy is not None else "unavailable",
            "sample_size": str(edge_stats.sample_size)
            if edge_stats is not None
            else "0",
            "confidence": edge_stats.confidence.value
            if edge_stats is not None
            else "INSUFFICIENT_DATA",
            "target_1_hit_rate": _optional_decimal_text(
                edge_stats.target_1_hit_rate if edge_stats is not None else None
            ),
            "stop_loss_hit_rate": _optional_decimal_text(
                edge_stats.stop_loss_hit_rate if edge_stats is not None else None
            ),
            "expectancy": _optional_decimal_text(
                edge_stats.expectancy if edge_stats is not None else None
            ),
            "fill_probability": _optional_decimal_text(
                edge_stats.fill_probability if edge_stats is not None else None
            ),
        },
        data_completeness_snapshot={
            "data_quality": recommendation.metadata.get("data_quality", "unknown"),
            "historical_bars": str(recommendation.historical_bar_count),
            "unavailable_reasons": "; ".join(recommendation.unavailable_reasons),
        },
        source_run_id=source_run_id,
        company_name=recommendation.metadata.get("company_name"),
        recommended_position_size_rs=approved_deployment,
        recommended_quantity=quantity,
        approved_deployment_rs=approved_deployment,
        candle_pattern=recommendation.candle_pattern,
        reward_risk=recommendation.risk_reward_ratio,
        expected_value=edge_stats.expectancy if edge_stats is not None else None,
        explanation=recommendation.trade_plan_explanation,
        status="OPEN",
    )


def _recommendation_id(
    *,
    source_run_id: str,
    symbol: str,
    generated_at: datetime,
) -> str:
    raw = f"{source_run_id}|{symbol.upper()}|{generated_at.isoformat()}"
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def _decimal_text(value: Decimal) -> str:
    return str(value)


def _optional_decimal_text(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _allocation_amount(allocation_report: object | None) -> Decimal | None:
    if allocation_report is None:
        return None
    amount = getattr(allocation_report, "target_amount", None)
    if amount is None or amount <= Decimal("0"):
        return None
    return Decimal(str(amount))


def _quantity(*, amount: Decimal | None, price: Decimal | None) -> Decimal | None:
    if amount is None or price is None or price <= Decimal("0"):
        return None
    return (amount / price).quantize(Decimal("0.01"))


__all__ = [
    "RecommendationPerformanceRecorder",
    "recommendation_to_ledger_entry",
    "source_run_id",
]
