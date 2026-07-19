from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest

from alpha.market_opportunity_truth.comparison import capture_statistics
from alpha.market_opportunity_truth.market_supply import market_supply_summary
from alpha.market_opportunity_truth.models import (
    AlphaComparisonRecord,
    DetectionStatus,
    LiquidityState,
    MarketOpportunity,
    MarketOpportunityTruthReport,
    MOTAManifest,
    OpportunityQuality,
    OutcomeMaturity,
    TrendState,
    VolatilityState,
)
from alpha.market_opportunity_truth.opportunity_calendar import (
    build_opportunity_calendar,
)
from alpha.market_opportunity_truth.opportunity_clusters import cluster_summaries
from alpha.market_opportunity_truth.opportunity_density import (
    build_opportunity_density,
)
from alpha.market_opportunity_truth.opportunity_quality import quality_distribution


def market_opportunity(
    opportunity_id: str,
    symbol: str,
    onset_date: date,
    quality: OpportunityQuality,
    *,
    cluster: str = "ALIGNED_CONTINUATION",
    target_before_stop: bool = True,
) -> MarketOpportunity:
    return MarketOpportunity(
        opportunity_id=opportunity_id,
        symbol=symbol,
        onset_date=onset_date,
        entry=Decimal("100"),
        initial_stop=Decimal("90"),
        reasonable_target=Decimal("125"),
        prospective_rr=Decimal("2.5"),
        liquidity_turnover=Decimal("100000000"),
        liquidity_state=LiquidityState.INSTITUTIONAL,
        trend_state=TrendState.UP_ALIGNED,
        volatility_state=VolatilityState.LOW,
        quality=quality,
        quality_score=Decimal("85"),
        quality_explanation="Point-in-time quality.",
        cluster_id=cluster,
        cluster_explanation="Point-in-time cluster.",
        market_regime="UNAVAILABLE_AUTHORITATIVE_HISTORY",
        days_to_peak=3,
        days_to_failure=None,
        mfe_percent=Decimal("25"),
        mae_percent=Decimal("-5"),
        rr_achieved=Decimal("2.5"),
        target_before_stop=target_before_stop,
        stop_hit=not target_before_stop,
        lifecycle_status=OutcomeMaturity.COMPLETE,
        available_forward_bars=120,
        exit_reason="PLAN_TARGET" if target_before_stop else "STOP",
        first_event_date=onset_date + timedelta(days=3),
        point_in_time_decision_hash=f"hash-{opportunity_id}",
    )


@pytest.fixture
def market_opportunities() -> tuple[MarketOpportunity, ...]:
    return (
        market_opportunity("op-1", "AAA", date(2024, 1, 2), OpportunityQuality.A_PLUS),
        market_opportunity(
            "op-2",
            "BBB",
            date(2024, 1, 3),
            OpportunityQuality.A,
            target_before_stop=False,
        ),
        market_opportunity(
            "op-3",
            "CCC",
            date(2024, 2, 1),
            OpportunityQuality.B,
            cluster="VOLUME_EXPANSION",
        ),
    )


@pytest.fixture
def mota_report(
    market_opportunities: tuple[MarketOpportunity, ...],
) -> MarketOpportunityTruthReport:
    sessions = (
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 2, 1),
        date(2024, 2, 2),
    )
    comparison = tuple(
        AlphaComparisonRecord(
            opportunity_id=item.opportunity_id,
            symbol=item.symbol,
            onset_date=item.onset_date,
            quality=item.quality,
            institutional_quality=item.quality.institutional,
            detected_status=(
                DetectionStatus.DETECTED
                if item.opportunity_id == "op-1"
                else DetectionStatus.NOT_DETECTED
            ),
            detection_date=item.onset_date if item.opportunity_id == "op-1" else None,
            detection_delay_sessions=0 if item.opportunity_id == "op-1" else None,
            candidate_created=item.opportunity_id == "op-1",
            candidate_date=item.onset_date if item.opportunity_id == "op-1" else None,
            candidate_delay_sessions=0 if item.opportunity_id == "op-1" else None,
            candidate_signal="BUY" if item.opportunity_id == "op-1" else None,
            institutional_approved=False,
            approval_date=None,
            executed=False,
            execution_date=None,
            matching_window_sessions=5,
            matching_explanation="Frozen test matching policy.",
        )
        for item in market_opportunities
    )
    calendar = build_opportunity_calendar(market_opportunities, sessions=sessions)
    return MarketOpportunityTruthReport(
        manifest=MOTAManifest(
            audit_version="MOTA_v1.0",
            baseline_id="ALPHA_BASELINE_v1.0",
            baseline_manifest_hash="baseline-hash",
            source_commit="source-commit",
            warehouse_version="warehouse-v1",
            candidate_version="candidate-v1",
            feature_version="feature-v1",
            opportunity_definition_version="opportunity-v1",
            quality_policy_version="quality-v1",
            cluster_policy_version="cluster-v1",
            comparison_policy_version="comparison-v1",
            horizon_sessions=120,
            matching_window_sessions=5,
            source_hashes=MappingProxyType({"source": "hash"}),
        ),
        opportunities=market_opportunities,
        calendar=calendar,
        density=build_opportunity_density(market_opportunities, sessions=sessions),
        quality_distribution=quality_distribution(market_opportunities),
        clusters=cluster_summaries(market_opportunities),
        alpha_comparison=comparison,
        capture_statistics=capture_statistics(comparison),
        supply_summary=market_supply_summary(
            market_opportunities,
            monthly_counts=tuple(
                (item.month, item.opportunities, item.institutional_quality)
                for item in calendar
            ),
        ),
    )


__all__ = ["market_opportunity"]
