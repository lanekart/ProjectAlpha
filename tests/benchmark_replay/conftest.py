from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pytest

from alpha.benchmark_replay.models import (
    BASELINE_ID,
    BENCHMARK_VERSION,
    REPLAY_CLASSIFICATION,
    ApprovalStatistic,
    BenchmarkAvailability,
    BenchmarkComparison,
    BenchmarkManifest,
    BenchmarkPolicy,
    BenchmarkReplayReport,
    CandidateStatistic,
    CapitalCurveRecord,
    IdleCapitalRecord,
    OpportunityCaptureRecord,
    PeriodReturn,
    PortfolioStatistics,
    RejectionCategory,
    VersionFreeze,
)


@pytest.fixture
def benchmark_report() -> BenchmarkReplayReport:
    policy = BenchmarkPolicy()
    versions = VersionFreeze(
        warehouse_version="TEST_WAREHOUSE",
        warehouse_hash="warehouse-hash",
        feature_version="feature-v1",
        feature_hash="feature-hash",
        candidate_generation_version="candidate-v1",
        candidate_generation_hash="candidate-hash",
        setup_discovery_version="setup-v1",
        setup_discovery_hash="setup-hash",
        feature_attribution_version="attribution-v1",
        feature_attribution_hash="attribution-hash",
        approval_policy_version="approval-v1",
        approval_policy_hash="approval-hash",
        trade_plan_policy_version="trade-plan-v1",
        trade_plan_policy_hash="trade-plan-hash",
        decision_engine_version="decision-v1",
        decision_engine_hash="decision-hash",
        source_commit="commit",
        source_tree_hash="tree-hash",
        source_tree_state="CLEAN",
        python_version="3.13.0",
        dependency_lock_hash="lock-hash",
    )
    manifest = BenchmarkManifest(
        baseline_id=BASELINE_ID,
        benchmark_version=BENCHMARK_VERSION,
        replay_classification=REPLAY_CLASSIFICATION,
        run_id=BASELINE_ID,
        replay_start=date(2024, 1, 2),
        replay_end=date(2024, 1, 3),
        sessions=2,
        universe_label="OBSERVED HISTORICAL UNIVERSE",
        historical_index_membership="UNKNOWN / NOT USED",
        historical_sector_membership="UNKNOWN / NOT ASSERTED",
        point_in_time_enforced=True,
        no_future_leakage=True,
        policy=policy,
        versions=versions,
        input_hash="input-hash",
        artifact_hashes=MappingProxyType({}),
        notes=("No future data entered decisions.",),
    )
    candidates = (
        CandidateStatistic(
            observed_on=date(2024, 1, 2),
            period_week="2024-W01",
            period_month="2024-01",
            period_year="2024",
            eligible_securities=1,
            technical_candidates=1,
            buy_candidates=0,
            strong_buy_candidates=0,
            institutional_approvals=0,
            portfolio_entries=0,
            rejected_ranking=0,
            rejected_capital=0,
            rejected_liquidity=0,
            runtime_status="SUCCESS",
        ),
    )
    approvals = (
        ApprovalStatistic(
            observed_on=date(2024, 1, 2),
            symbol="TEST",
            approved=False,
            opportunity_score=Decimal("50"),
            opportunity_grade="REJECT",
            primary_reason_code="WEAK_VERDICT",
            rejection_category=RejectionCategory.NO_CANDIDATE,
            explanation="Only BUY candidates are deployable.",
        ),
    )
    curve = (
        CapitalCurveRecord(
            observed_on=date(2024, 1, 2),
            cash=Decimal("1000000"),
            invested_capital=Decimal("0"),
            portfolio_value=Decimal("1000000"),
            idle_cash=Decimal("1000000"),
            capital_utilisation_percent=Decimal("0"),
            daily_return_percent=Decimal("0"),
            drawdown_percent=Decimal("0"),
            open_positions=0,
            pending_orders=0,
        ),
    )
    stats = PortfolioStatistics(
        starting_capital=Decimal("1000000"),
        ending_capital=Decimal("1000000"),
        logical_trades=0,
        winning_trades=0,
        losing_trades=0,
        breakeven_trades=0,
        win_rate_percent=None,
        average_winner_percent=None,
        average_loser_percent=None,
        median_winner_percent=None,
        median_loser_percent=None,
        profit_factor=None,
        expectancy_percent=None,
        median_holding_period_days=None,
        average_holding_period_days=None,
        cagr_percent=Decimal("0"),
        maximum_drawdown_percent=Decimal("0"),
        ulcer_index=Decimal("0"),
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        annualized_volatility_percent=Decimal("0"),
        average_invested_capital=Decimal("0"),
        median_invested_capital=Decimal("0"),
        maximum_invested_capital=Decimal("0"),
        average_idle_cash=Decimal("1000000"),
        average_capital_utilisation_percent=Decimal("0"),
        days_fully_invested=0,
        days_fully_in_cash=1,
        turnover_percent=Decimal("0"),
        exit_attribution=MappingProxyType({}),
    )
    opportunity = (
        OpportunityCaptureRecord(
            opportunity_definition="ALL",
            major_opportunities=10,
            tradable_opportunities=5,
            candidates_generated=1,
            approved=0,
            entered=0,
            captured=0,
            missed=10,
            capture_rate_percent=Decimal("0"),
            median_captured_move_percent=None,
            median_missed_move_percent=Decimal("25"),
        ),
    )
    comparison = (
        BenchmarkComparison(
            benchmark="NIFTY_50_BUY_AND_HOLD",
            availability=BenchmarkAvailability.UNAVAILABLE,
            start_date=None,
            end_date=None,
            starting_value=None,
            ending_value=None,
            total_return_percent=None,
            cagr_percent=None,
            excess_cagr_percent=None,
            reason="Index history unavailable.",
        ),
    )
    return BenchmarkReplayReport(
        manifest=manifest,
        candidate_statistics=candidates,
        approval_statistics=approvals,
        trades=(),
        position_history=(),
        capital_curve=curve,
        monthly_returns=(
            PeriodReturn(
                "2024-01", Decimal("1000000"), Decimal("1000000"), Decimal("0")
            ),
        ),
        yearly_returns=(
            PeriodReturn("2024", Decimal("1000000"), Decimal("1000000"), Decimal("0")),
        ),
        opportunity_capture=opportunity,
        idle_capital=(
            IdleCapitalRecord(
                period="2024-01",
                sessions=1,
                average_invested_capital=Decimal("0"),
                median_invested_capital=Decimal("0"),
                maximum_invested_capital=Decimal("0"),
                average_idle_cash=Decimal("1000000"),
                average_utilisation_percent=Decimal("0"),
                fully_invested_days=0,
                fully_in_cash_days=1,
            ),
        ),
        benchmark_comparison=comparison,
        portfolio_statistics=stats,
        top_rejection_reasons=(("WEAK_VERDICT", 1),),
        eligible_securities=1,
        eligible_security_observations=1,
    )
