from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from hashlib import sha256

from alpha.application.runtime_models import RuntimeResult
from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.performance_intelligence.recorder import source_run_id
from alpha.recommendation_intelligence.models import RecommendationReport
from alpha.strategy_regime import setup_to_indicators


@dataclass(frozen=True, slots=True)
class CandidateMarketStateContext:
    snapshot_id: str
    as_of: datetime
    fallback_applied: bool
    completeness: str
    classifier_version: str
    decision_provenance_id: str | None = None


class CandidateDecisionRecorder:
    def __init__(self, repository: LearningLedgerRepository) -> None:
        self.repository = repository

    def record_runtime(
        self,
        runtime_result: RuntimeResult,
        *,
        market_state_context: CandidateMarketStateContext | None = None,
    ) -> tuple[int, int]:
        run_id = source_run_id(runtime_result)
        run = getattr(runtime_result, "intelligence_run")
        generated_at = datetime.combine(
            getattr(runtime_result, "observed_on"),
            time.min,
            tzinfo=UTC,
        )
        allocation_by_symbol = {
            report.symbol: report for report in run.allocation_plan.reports
        }
        records = tuple(
            recommendation_to_candidate_record(
                recommendation=recommendation,
                run_id=run_id,
                market_regime=run.market_report.bias.value,
                created_at=generated_at,
                allocation_report=allocation_by_symbol.get(recommendation.symbol),
                market_state_context=market_state_context,
            )
            for recommendation in run.recommendations
        )
        inserted = self.repository.save_records(records)
        return len(records), inserted


def recommendation_to_candidate_record(
    *,
    recommendation: RecommendationReport,
    run_id: str,
    market_regime: str | None,
    created_at: datetime,
    allocation_report: object | None,
    market_state_context: CandidateMarketStateContext | None = None,
) -> CandidateDecisionRecord:
    allocation_approved = allocation_report is not None and getattr(
        allocation_report, "target_amount", Decimal("0")
    ) > Decimal("0")
    approved = allocation_approved and _institutional_approval(
        recommendation=recommendation,
        allocation_report=allocation_report,
    )
    indicators = setup_to_indicators(recommendation.setup_name)
    return CandidateDecisionRecord(
        candidate_id=_candidate_id(run_id=run_id, symbol=recommendation.symbol),
        run_id=run_id,
        evaluation_date=recommendation.observed_on,
        symbol=recommendation.symbol,
        company_name=recommendation.metadata.get("company_name"),
        sector=recommendation.metadata.get("sector"),
        final_verdict=recommendation.final_signal,
        capital_action=recommendation.action.value,
        approved_for_deployment=approved,
        rejection_reasons=_rejection_reasons(recommendation),
        setup_type=recommendation.setup_name,
        market_regime=market_regime or recommendation.metadata.get("market_regime"),
        long_trade_permission=recommendation.final_signal in {"STRONG_BUY", "BUY"},
        strategy_score=recommendation.final_score,
        confidence=recommendation.confidence,
        data_quality=recommendation.metadata.get("data_quality", "UNKNOWN"),
        entry_zone_low=recommendation.entry_zone_low,
        entry_zone_high=recommendation.entry_zone_high,
        confirmation_entry=recommendation.trade_plan.confirmation_entry,
        risk_stop=recommendation.initial_stop_loss,
        target_1=recommendation.target_1,
        target_2=recommendation.target_2,
        target_3=recommendation.target_3,
        trailing_stop_plan=recommendation.trailing_stop_strategy,
        expected_holding_period=recommendation.trade_plan.expected_holding_period,
        indicators_active=indicators,
        indicator_scores={
            "price": str(recommendation.price_evidence.price_score),
            "volume": str(recommendation.volume_evidence.volume_score),
            "retracement": str(recommendation.retracement_score),
            "candle": str(recommendation.candle_score),
        },
        evidence_layers=tuple(
            evidence.label for evidence in recommendation.supporting_evidence
        ),
        explanation=" ".join(recommendation.explanation),
        created_at=created_at,
        recommendation_id=None,
        market_state_snapshot_id=(
            None if market_state_context is None else market_state_context.snapshot_id
        ),
        market_state_as_of=(
            None if market_state_context is None else market_state_context.as_of
        ),
        market_state_fallback_applied=(
            None
            if market_state_context is None
            else market_state_context.fallback_applied
        ),
        market_state_completeness=(
            None if market_state_context is None else market_state_context.completeness
        ),
        classifier_version=(
            None
            if market_state_context is None
            else market_state_context.classifier_version
        ),
        decision_provenance_id=(
            None
            if market_state_context is None
            else market_state_context.decision_provenance_id
        ),
    )


def _rejection_reasons(recommendation: RecommendationReport) -> tuple[str, ...]:
    if recommendation.final_signal in {"STRONG_BUY", "BUY"}:
        return ()
    reasons = tuple(risk.label for risk in recommendation.opposing_evidence)
    return reasons or (f"Final verdict {recommendation.final_signal}",)


def _institutional_approval(
    *,
    recommendation: RecommendationReport,
    allocation_report: object | None,
) -> bool:
    from alpha.decision_intelligence.engine import (
        InstitutionalDecisionEngine,
        candidate_from_recommendation,
    )

    decision = (
        InstitutionalDecisionEngine()
        .evaluate(
            (
                candidate_from_recommendation(
                    recommendation,
                    allocation_report=allocation_report,
                ),
            )
        )
        .decisions[0]
    )
    return decision.accepted


def _candidate_id(*, run_id: str, symbol: str) -> str:
    raw = f"{run_id}|{symbol.strip().upper()}"
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


__all__ = [
    "CandidateDecisionRecorder",
    "CandidateMarketStateContext",
    "recommendation_to_candidate_record",
]
