from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from alpha.adaptive_weights.ablation_engine import MatchedAblationEngine
from alpha.adaptive_weights.evidence_builder import CompletedOutcomeEvidenceBuilder
from alpha.adaptive_weights.marginal_contribution import MarginalContributionEngine
from alpha.adaptive_weights.models import (
    AblationObservation,
    AblationRole,
    AlphaComponent,
    EvidencePartition,
)
from alpha.performance_intelligence.models import (
    RecommendationExitReason,
    RecommendationLedgerEntry,
    RecommendationOutcome,
    RecommendationOutcomeStatus,
)
from tests.adaptive_weights.helpers import completed_evidence, performance


def test_unresolved_outcome_is_never_completed_evidence() -> None:
    entry = RecommendationLedgerEntry(
        recommendation_id="REC-1",
        generated_at=datetime(2025, 1, 1, tzinfo=UTC),
        symbol="ABC",
        final_verdict="BUY",
        confidence="HIGH",
        score=Decimal("80"),
        setup_type="BREAKOUT",
        setup_state="ENTRY_READY",
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("101"),
        confirmation_entry=Decimal("102"),
        stop_loss=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        trailing_stop_strategy="2 ATR",
        holding_period="20D",
        market_regime="BULL",
        sector="TECH",
        key_indicator_snapshot={"price_score": "0.8"},
        statistical_edge_snapshot={
            "policy_version": "ALPHA_CANONICAL",
            "transaction_costs": "0.1",
        },
        data_completeness_snapshot={"dataset_version": "DATA-V1"},
        source_run_id="RUN-1",
    )
    pending = RecommendationOutcome(
        recommendation_id="REC-1",
        symbol="ABC",
        status=RecommendationOutcomeStatus.PENDING,
    )
    evidence, audit = CompletedOutcomeEvidenceBuilder().from_performance_ledger(
        (entry,),
        (pending,),
        partition=EvidencePartition.FORWARD_OBSERVED,
    )
    assert evidence == ()
    assert audit.excluded_unresolved == 1


def test_resolved_complete_ledger_entry_becomes_forward_evidence() -> None:
    entry = RecommendationLedgerEntry(
        recommendation_id="REC-2",
        generated_at=datetime(2025, 1, 1, tzinfo=UTC),
        symbol="ABC",
        final_verdict="BUY",
        confidence="HIGH",
        score=Decimal("80"),
        setup_type="BREAKOUT",
        setup_state="ENTRY_READY",
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("101"),
        confirmation_entry=Decimal("102"),
        stop_loss=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        trailing_stop_strategy="2 ATR",
        holding_period="20D",
        market_regime="BULL",
        sector="TECH",
        key_indicator_snapshot={
            "price_score": "0.8",
            "volume_score": "0.7",
        },
        statistical_edge_snapshot={
            "policy_version": "ALPHA_CANONICAL",
            "transaction_costs": "0.1",
            "strategy": "MOMENTUM",
        },
        data_completeness_snapshot={"dataset_version": "DATA-V1"},
        source_run_id="RUN-1",
    )
    outcome = RecommendationOutcome(
        recommendation_id="REC-2",
        symbol="ABC",
        status=RecommendationOutcomeStatus.EXITED,
        entry_triggered=True,
        entry_date=date(2025, 1, 2),
        entry_price=Decimal("100"),
        exit_date=date(2025, 1, 20),
        exit_price=Decimal("110"),
        exit_reason=RecommendationExitReason.TARGET_1,
        realized_r_multiple=Decimal("2"),
        realized_percent_return=Decimal("10"),
    )
    evidence, audit = CompletedOutcomeEvidenceBuilder().from_performance_ledger(
        (entry,),
        (outcome,),
        partition=EvidencePartition.FORWARD_OBSERVED,
    )
    assert audit.eligible_records == 1
    assert evidence[0].realized_r_multiple == Decimal("2")
    assert evidence[0].score_for(AlphaComponent.TREND) is None


def test_matched_ablation_separates_win_rate_from_expectancy() -> None:
    common = {
        "research_id": "TRL-1",
        "component": AlphaComponent.RETRACEMENT,
        "symbol": "ABC",
        "decision_date": date(2024, 1, 1),
        "strategy_family": "MOMENTUM",
        "setup_family": "BREAKOUT",
        "stop_policy": "ATR",
        "exit_policy": "2R",
        "cost_profile": "COST-V1",
        "dataset_version": "DATA-V1",
        "partition": EvidencePartition.HOLDOUT,
    }
    observations = (
        AblationObservation(
            **common,
            role=AblationRole.WITH_COMPONENT,
            performance=performance(
                expectancy="-0.10", win_rate="0.65", profit_factor="0.8", drawdown="8"
            ),
        ),
        AblationObservation(
            **common,
            role=AblationRole.WITHOUT_COMPONENT,
            performance=performance(
                expectancy="0.20", win_rate="0.55", profit_factor="1.3", drawdown="6"
            ),
        ),
    )
    report = MatchedAblationEngine().analyze(observations)
    retracement = next(
        item for item in report if item.component is AlphaComponent.RETRACEMENT
    )
    assert retracement.delta_win_rate == Decimal("0.10")
    assert retracement.delta_expectancy == Decimal("-0.30")


def test_marginal_engine_reports_distinct_transparent_methods() -> None:
    partitions = tuple(EvidencePartition)
    evidence = tuple(
        completed_evidence(index, partition=partitions[index % len(partitions)])
        for index in range(48)
    )
    estimates = MarginalContributionEngine().analyze(evidence)
    price = next(
        item for item in estimates if item.component is AlphaComponent.PRICE_STRUCTURE
    )
    assert price.sample_size == 48
    assert price.standalone_contribution is not None
    assert price.marginal_contribution is not None
    assert price.leave_one_out_contribution is not None
    assert price.permutation_importance is not None
    assert "ridge" in price.method_label
