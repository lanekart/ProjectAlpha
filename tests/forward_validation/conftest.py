from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.forward_validation.models import RecommendationSnapshot
from alpha.forward_validation.validation_registry import canonical_json


@pytest.fixture
def snapshot_factory():  # type: ignore[no-untyped-def]
    def build(
        *,
        recommendation_id: str = "rec-1",
        symbol: str = "ALPHA",
        generated_at: datetime | None = None,
        verdict: str = "BUY",
        trigger_style: str = "CLOSE_ABOVE",
        trigger_status: str = "TRIGGER_CONFIRMED",
        current_price: Decimal | None = Decimal("100"),
        confirmation_entry: Decimal | None = Decimal("105"),
        stop: Decimal | None = Decimal("90"),
        target_1: Decimal | None = Decimal("110"),
        target_2: Decimal | None = Decimal("120"),
        target_3: Decimal | None = Decimal("130"),
        approved_deployment: Decimal | None = Decimal("1000"),
        maximum_holding_days: int | None = 10,
        policy_version: str = "APPROVAL_POLICY_V1",
        atr_value: Decimal | None = Decimal("5"),
    ) -> RecommendationSnapshot:
        timestamp = generated_at or datetime(2026, 1, 1, tzinfo=UTC)
        diagnostics = {"price": {"close": str(current_price or "unavailable")}}
        evidence_hashes = {
            "price": sha256(canonical_json(diagnostics["price"]).encode()).hexdigest()
        }
        payload: dict[str, object] = {
            "recommendation_id": recommendation_id,
            "generated_at": timestamp.isoformat(),
            "source_run_id": "run-1",
            "symbol": symbol,
            "current_market_price": _text(current_price),
            "final_verdict": verdict,
            "recommendation_score": "90",
            "confidence": "HIGH",
            "entry_zone_low": "98",
            "entry_zone_high": "102",
            "confirmation_entry": _text(confirmation_entry),
            "trigger_style": trigger_style,
            "trigger_status": trigger_status,
            "stop_loss": _text(stop),
            "target_1": _text(target_1),
            "target_2": _text(target_2),
            "target_3": _text(target_3),
            "holding_period": "10 days",
            "maximum_holding_days": maximum_holding_days,
            "risk_reward": "2",
            "atr_value": _text(atr_value),
            "dma_20": "95",
            "trailing_stop_strategy": (
                "After target 1, trail at 2 x ATR below highest close."
            ),
            "invalidation_level": "88",
            "market_regime": "BULLISH",
            "sector": "TECHNOLOGY",
            "engine_version": "test",
            "data_version": "data-test",
            "policy_version": policy_version,
            "approved_deployment": _text(approved_deployment),
            "diagnostics": diagnostics,
            "evidence_hashes": evidence_hashes,
        }
        payload["snapshot_hash"] = sha256(canonical_json(payload).encode()).hexdigest()
        return RecommendationSnapshot.from_dict(payload)

    return build


@pytest.fixture
def policy_evidence():  # type: ignore[no-untyped-def]
    records: list[CandidateDecisionRecord] = []
    outcomes: list[CandidateForwardOutcome] = []
    start = date(2025, 1, 1)
    for index in range(30):
        candidate_id = f"candidate-{index:02d}"
        evaluated = start + timedelta(days=index)
        record = CandidateDecisionRecord(
            candidate_id=candidate_id,
            run_id=f"run-{index:02d}",
            evaluation_date=evaluated,
            symbol=f"STOCK{index:02d}",
            final_verdict="BUY",
            capital_action="BUY",
            approved_for_deployment=True,
            rejection_reasons=(),
            setup_type="BREAKOUT",
            market_regime="BULLISH",
            long_trade_permission=True,
            strategy_score=Decimal("90"),
            confidence="HIGH",
            data_quality="COMPLETE",
            entry_zone_low=Decimal("98"),
            entry_zone_high=Decimal("100"),
            confirmation_entry=Decimal("100"),
            risk_stop=Decimal("85"),
            target_1=Decimal("115"),
            target_2=Decimal("130"),
            target_3=Decimal("145"),
            trailing_stop_plan="2 x ATR",
            expected_holding_period="20 days",
            indicators_active=("price-volume",),
            indicator_scores={"price": "90"},
            evidence_layers=("price", "volume"),
            explanation="Deterministic policy fixture.",
            created_at=datetime.combine(evaluated, datetime.min.time(), tzinfo=UTC),
            sector="TECHNOLOGY",
        )
        window = CandidateForwardWindowOutcome(
            window="20d",
            forward_open=Decimal("100"),
            forward_high=Decimal("120"),
            forward_low=Decimal("94"),
            forward_close=Decimal("110"),
            forward_return_pct_from_close=Decimal("10"),
            forward_return_pct_from_entry=Decimal("10"),
            max_favourable_excursion_pct=Decimal("20"),
            max_adverse_excursion_pct=Decimal("-6"),
            target_1_touched=True,
            risk_stop_touched=False,
            outcome_label=CandidateOutcomeLabel.WOULD_HAVE_WON,
        )
        records.append(record)
        outcomes.append(
            CandidateForwardOutcome(
                candidate_id=candidate_id,
                symbol=record.symbol,
                evaluated_at=datetime.combine(
                    evaluated + timedelta(days=20),
                    datetime.min.time(),
                    tzinfo=UTC,
                ),
                windows=(window,),
            )
        )
    return tuple(records), tuple(outcomes)


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
