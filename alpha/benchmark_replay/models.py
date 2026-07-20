from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

PRODUCTION_INFLUENCE = False
BASELINE_ID = "ALPHA_BASELINE_v1.0"
REPLAY_CLASSIFICATION = "OBSERVED_MARKET_REPLAY"
BENCHMARK_VERSION = "CABR_v1.0"


class RejectionCategory(StrEnum):
    NO_CANDIDATE = "No Candidate"
    WEAK_SCORE = "Weak Score"
    TIMING = "Timing"
    TRADE_PLAN = "Trade Plan"
    APPROVAL = "Approval"
    RANKING = "Ranking"
    CAPITAL = "Capital"
    LIQUIDITY = "Liquidity"
    UNKNOWN = "Unknown"


class BenchmarkAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class BenchmarkPolicy:
    initial_capital: Decimal = Decimal("1000000")
    maximum_positions: int = 3
    position_size_percent: Decimal = Decimal("10")
    cash_reserve_percent: Decimal = Decimal("70")
    transaction_cost_percent: Decimal = Decimal("0.20")
    slippage_percent: Decimal = Decimal("0.10")
    maximum_sector_exposure_percent: Decimal = Decimal("25")
    maximum_single_name_exposure_percent: Decimal = Decimal("10")
    entry_validity_sessions: int = 5

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial capital must be positive")
        if self.maximum_positions < 1:
            raise ValueError("maximum positions must be positive")
        if self.entry_validity_sessions < 1:
            raise ValueError("entry validity sessions must be positive")
        for name in (
            "position_size_percent",
            "cash_reserve_percent",
            "transaction_cost_percent",
            "slippage_percent",
            "maximum_sector_exposure_percent",
            "maximum_single_name_exposure_percent",
        ):
            value = Decimal(str(getattr(self, name)))
            if value < 0 or value > 100:
                raise ValueError(f"{name} must be between 0 and 100")
            object.__setattr__(self, name, value)
        if self.position_size_percent > self.maximum_single_name_exposure_percent:
            raise ValueError("position size cannot exceed the single-name cap")

    @property
    def deployable_capital(self) -> Decimal:
        return (
            self.initial_capital
            * (Decimal("100") - self.cash_reserve_percent)
            / Decimal("100")
        )

    @property
    def round_trip_friction_percent(self) -> Decimal:
        return self.transaction_cost_percent + self.slippage_percent


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    start: date | None = None
    end: date | None = None
    policy: BenchmarkPolicy = field(default_factory=BenchmarkPolicy)

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("benchmark end date cannot precede start date")


@dataclass(frozen=True, slots=True)
class CandidateStatistic:
    observed_on: date
    period_week: str
    period_month: str
    period_year: str
    eligible_securities: int
    technical_candidates: int
    buy_candidates: int
    strong_buy_candidates: int
    institutional_approvals: int
    portfolio_entries: int
    rejected_ranking: int
    rejected_capital: int
    rejected_liquidity: int
    runtime_status: str


@dataclass(frozen=True, slots=True)
class ApprovalStatistic:
    observed_on: date
    symbol: str
    approved: bool
    opportunity_score: Decimal
    opportunity_grade: str
    final_signal: str
    primary_reason_code: str
    rejection_category: RejectionCategory
    explanation: str


@dataclass(frozen=True, slots=True)
class TradeRecord:
    trade_id: str
    symbol: str
    sector: str
    decision_date: date
    entry_date: date
    exit_date: date
    entry_price: Decimal
    exit_price: Decimal
    initial_stop: Decimal
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    quantity: Decimal
    gross_profit_loss: Decimal
    net_profit_loss: Decimal
    gross_return_percent: Decimal
    net_return_percent: Decimal
    realised_r: Decimal
    holding_sessions: int
    holding_days: int
    exit_reason: str
    targets_hit: tuple[int, ...]
    transaction_cost: Decimal
    slippage_cost: Decimal
    ambiguity_count: int


@dataclass(frozen=True, slots=True)
class PositionHistoryRecord:
    observed_on: date
    trade_id: str
    symbol: str
    status: str
    quantity: Decimal
    average_cost: Decimal
    close_price: Decimal
    stop_price: Decimal
    market_value: Decimal
    unrealized_profit_loss: Decimal
    highest_close: Decimal
    holding_sessions: int


@dataclass(frozen=True, slots=True)
class CapitalCurveRecord:
    observed_on: date
    cash: Decimal
    invested_capital: Decimal
    portfolio_value: Decimal
    idle_cash: Decimal
    capital_utilisation_percent: Decimal
    daily_return_percent: Decimal
    drawdown_percent: Decimal
    open_positions: int
    pending_orders: int


@dataclass(frozen=True, slots=True)
class PeriodReturn:
    period: str
    opening_value: Decimal
    closing_value: Decimal
    return_percent: Decimal


@dataclass(frozen=True, slots=True)
class OpportunityCaptureRecord:
    opportunity_definition: str
    major_opportunities: int
    tradable_opportunities: int
    candidates_generated: int
    approved: int
    entered: int
    captured: int
    missed: int
    capture_rate_percent: Decimal | None
    median_captured_move_percent: Decimal | None
    median_missed_move_percent: Decimal | None


@dataclass(frozen=True, slots=True)
class IdleCapitalRecord:
    period: str
    sessions: int
    average_invested_capital: Decimal
    median_invested_capital: Decimal
    maximum_invested_capital: Decimal
    average_idle_cash: Decimal
    average_utilisation_percent: Decimal
    fully_invested_days: int
    fully_in_cash_days: int


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    benchmark: str
    availability: BenchmarkAvailability
    start_date: date | None
    end_date: date | None
    starting_value: Decimal | None
    ending_value: Decimal | None
    total_return_percent: Decimal | None
    cagr_percent: Decimal | None
    excess_cagr_percent: Decimal | None
    reason: str


@dataclass(frozen=True, slots=True)
class PortfolioStatistics:
    starting_capital: Decimal
    ending_capital: Decimal
    logical_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_percent: Decimal | None
    average_winner_percent: Decimal | None
    average_loser_percent: Decimal | None
    median_winner_percent: Decimal | None
    median_loser_percent: Decimal | None
    profit_factor: Decimal | None
    expectancy_percent: Decimal | None
    median_holding_period_days: Decimal | None
    average_holding_period_days: Decimal | None
    cagr_percent: Decimal
    maximum_drawdown_percent: Decimal
    ulcer_index: Decimal
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    calmar_ratio: Decimal | None
    annualized_volatility_percent: Decimal
    average_invested_capital: Decimal
    median_invested_capital: Decimal
    maximum_invested_capital: Decimal
    average_idle_cash: Decimal
    average_capital_utilisation_percent: Decimal
    days_fully_invested: int
    days_fully_in_cash: int
    turnover_percent: Decimal
    exit_attribution: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "exit_attribution",
            MappingProxyType(dict(sorted(self.exit_attribution.items()))),
        )


@dataclass(frozen=True, slots=True)
class VersionFreeze:
    warehouse_version: str
    warehouse_hash: str
    feature_version: str
    feature_hash: str
    candidate_generation_version: str
    candidate_generation_hash: str
    setup_discovery_version: str
    setup_discovery_hash: str
    feature_attribution_version: str
    feature_attribution_hash: str
    approval_policy_version: str
    approval_policy_hash: str
    trade_plan_policy_version: str
    trade_plan_policy_hash: str
    decision_engine_version: str
    decision_engine_hash: str
    source_commit: str
    source_tree_hash: str
    source_tree_state: str
    python_version: str
    dependency_lock_hash: str


@dataclass(frozen=True, slots=True)
class BenchmarkManifest:
    baseline_id: str
    benchmark_version: str
    replay_classification: str
    run_id: str
    replay_start: date
    replay_end: date
    sessions: int
    universe_label: str
    historical_index_membership: str
    historical_sector_membership: str
    point_in_time_enforced: bool
    no_future_leakage: bool
    policy: BenchmarkPolicy
    versions: VersionFreeze
    input_hash: str
    artifact_hashes: Mapping[str, str]
    notes: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("CABR must never influence production")
        object.__setattr__(
            self,
            "artifact_hashes",
            MappingProxyType(dict(sorted(self.artifact_hashes.items()))),
        )
        object.__setattr__(self, "notes", tuple(self.notes))


@dataclass(frozen=True, slots=True)
class BenchmarkReplayReport:
    manifest: BenchmarkManifest
    candidate_statistics: tuple[CandidateStatistic, ...]
    approval_statistics: tuple[ApprovalStatistic, ...]
    trades: tuple[TradeRecord, ...]
    position_history: tuple[PositionHistoryRecord, ...]
    capital_curve: tuple[CapitalCurveRecord, ...]
    monthly_returns: tuple[PeriodReturn, ...]
    yearly_returns: tuple[PeriodReturn, ...]
    opportunity_capture: tuple[OpportunityCaptureRecord, ...]
    idle_capital: tuple[IdleCapitalRecord, ...]
    benchmark_comparison: tuple[BenchmarkComparison, ...]
    portfolio_statistics: PortfolioStatistics
    top_rejection_reasons: tuple[tuple[str, int], ...]
    eligible_securities: int
    eligible_security_observations: int


__all__ = [
    "BASELINE_ID",
    "BENCHMARK_VERSION",
    "PRODUCTION_INFLUENCE",
    "REPLAY_CLASSIFICATION",
    "ApprovalStatistic",
    "BenchmarkAvailability",
    "BenchmarkComparison",
    "BenchmarkManifest",
    "BenchmarkPolicy",
    "BenchmarkReplayReport",
    "CandidateStatistic",
    "CapitalCurveRecord",
    "IdleCapitalRecord",
    "OpportunityCaptureRecord",
    "PeriodReturn",
    "PortfolioStatistics",
    "PositionHistoryRecord",
    "RejectionCategory",
    "ReplayRequest",
    "TradeRecord",
    "VersionFreeze",
]
