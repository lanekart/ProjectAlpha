from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

PRODUCTION_INFLUENCE = False
CANONICAL_ENGINE_VERSION = "ALPHA_CANONICAL_v1.0"
ACU_SCHEMA_VERSION = "alpha-canonical-universe-audit-v1.0"
ACU_RUN_VERSION = "ACU-1"
DATASET_VERSION = "LEGACY_DATASET"
DATASET_CONFIDENCE = Decimal("0.90")
EVIDENCE_LABELS = (
    "PROVISIONAL",
    "NOT AUTHORITATIVE",
    DATASET_VERSION,
)


class GateCategory(StrEnum):
    PRICE = "Price"
    TREND = "Trend"
    VOLUME = "Volume"
    RETRACEMENT = "Retracement"
    CANDLES = "Candles"
    BREAKOUT = "Breakout"
    RISK = "Risk"
    ENTRY_TIMING = "Entry Timing"
    APPROVAL = "Approval"
    PORTFOLIO = "Portfolio"
    OTHER = "Other"


class OpportunityHeat(StrEnum):
    ALMOST_NONE = "ALMOST_NONE"
    AVERAGE = "AVERAGE"
    VERY_HIGH = "VERY_HIGH"


class LiquidityBucket(StrEnum):
    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    dataset_version: str
    first_session: date
    last_session: date
    sessions: int
    rows: int
    symbols: int
    exchange: str
    sector_rows: int
    confidence: Decimal = DATASET_CONFIDENCE
    labels: tuple[str, ...] = EVIDENCE_LABELS

    def __post_init__(self) -> None:
        if self.sessions < 1 or self.rows < 1 or self.symbols < 1:
            raise ValueError("legacy dataset manifest must describe non-empty data")
        if self.first_session > self.last_session:
            raise ValueError("dataset first session cannot follow last session")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("dataset confidence must be in [0, 1]")
        object.__setattr__(self, "labels", tuple(self.labels))


@dataclass(frozen=True, slots=True)
class DailyOpportunityRecord:
    observed_on: date
    universe_size: int
    eligible_securities: int
    technical_candidates: int
    approval_candidates: int
    institutional_approvals: int
    portfolio_eligible: int
    raw_approvals: int
    independent_approvals: int
    average_score: Decimal | None
    median_score: Decimal | None
    maximum_score: Decimal | None
    score_80_plus: int
    score_90_plus: int
    score_95_plus: int
    estimated_invested_capital: Decimal
    estimated_position_count: int
    runtime_status: str = "SUCCESS"
    runtime_error: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateRankingRecord:
    observed_on: date
    rank: int
    symbol: str
    final_signal: str
    score: Decimal
    confidence: str
    sector: str
    liquidity_bucket: LiquidityBucket
    expected_r: Decimal | None
    suggested_priority: str
    approval_candidate: bool
    institutional_approved: bool
    portfolio_eligible: bool
    setup_type: str
    setup_stage: str
    entry_price: Decimal | None
    initial_stop: Decimal | None
    target_1: Decimal | None
    expected_return: Decimal | None
    holding_period_days: int

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("candidate symbol cannot be empty")
        if self.rank < 1:
            raise ValueError("candidate rank must be positive")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self, "liquidity_bucket", LiquidityBucket(self.liquidity_bucket)
        )


@dataclass(frozen=True, slots=True)
class GateAttributionRecord:
    observed_on: date
    symbol: str
    gate_code: str
    category: GateCategory
    explanation: str
    primary: bool

    def __post_init__(self) -> None:
        if not self.gate_code.strip() or not self.explanation.strip():
            raise ValueError("gate attribution requires a code and explanation")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "category", GateCategory(self.category))


@dataclass(frozen=True, slots=True)
class CandidateOutcomeRecord:
    observed_on: date
    symbol: str
    entered: bool
    completed: bool
    won: bool | None
    realized_return_pct: Decimal | None
    realized_r: Decimal | None
    holding_period_days: int | None
    exit_reason: str
    evidence_note: str


@dataclass(frozen=True, slots=True)
class MonthlyOpportunitySummary:
    month: str
    trading_days: int
    total_opportunities: int
    average_opportunities_per_day: Decimal
    maximum_opportunities: int
    heat: OpportunityHeat


@dataclass(frozen=True, slots=True)
class PeriodOpportunitySummary:
    period: str
    trading_days: int
    total_opportunities: int
    average_opportunities_per_day: Decimal
    maximum_opportunities_in_day: int


@dataclass(frozen=True, slots=True)
class SectorOpportunitySummary:
    sector: str
    candidates: int
    approved_opportunities: int
    average_opportunities_per_day: Decimal
    completed_outcomes: int
    win_rate: Decimal | None
    average_realized_return_pct: Decimal | None
    average_expected_return: Decimal | None
    industry: str = "UNAVAILABLE"
    theme: str = "UNAVAILABLE"
    market_cap: str = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class LiquidityCapacityRecord:
    symbol: str
    average_daily_volume: Decimal | None
    average_daily_turnover: Decimal | None
    free_float: Decimal | None
    liquidity_bucket: LiquidityBucket
    deployable_at_10_lakh: Decimal | None
    deployable_at_50_lakh: Decimal | None
    deployable_at_1_crore: Decimal | None
    deployable_at_5_crore: Decimal | None
    deployable_at_10_crore: Decimal | None
    label: str = "APPROXIMATE / LEGACY DATA"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(
            self, "liquidity_bucket", LiquidityBucket(self.liquidity_bucket)
        )


@dataclass(frozen=True, slots=True)
class SymbolOpportunitySummary:
    symbol: str
    candidate_count: int
    approval_count: int
    portfolio_eligible_count: int
    active_years: Decimal
    candidates_per_year: Decimal
    approvals_per_year: Decimal
    candidates_per_decade: Decimal
    average_score: Decimal | None
    trades_per_year: Decimal = Decimal("0")
    trades_per_decade: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class ExecutiveSummary:
    total_sessions: int
    total_candidates: int
    total_approval_candidates: int
    total_institutional_approvals: int
    total_portfolio_eligible: int
    average_opportunities_per_day: Decimal
    median_opportunities_per_day: Decimal
    maximum_opportunities_per_day: int
    average_opportunities_per_month: Decimal
    maximum_opportunities_per_month: int
    zero_opportunity_days: int
    one_opportunity_days: int
    two_plus_opportunity_days: int
    five_plus_opportunity_days: int
    average_invested_percent: Decimal
    average_idle_percent: Decimal
    average_positions: Decimal
    average_score: Decimal | None
    median_score: Decimal | None
    score_80_plus: int
    score_90_plus: int
    score_95_plus: int
    largest_gate: str
    largest_gate_rejections: int
    raw_simultaneous_approvals: int
    independent_simultaneous_approvals: int
    completed_outcomes: int
    win_rate: Decimal | None
    expected_payoff_pct: Decimal | None
    canonical_runtime_failure_days: int = 0
    scored_candidates: int = 0
    average_opportunities_per_week: Decimal = Decimal("0")
    median_opportunities_per_week: Decimal = Decimal("0")
    maximum_opportunities_per_week: int = 0
    average_opportunities_per_year: Decimal = Decimal("0")
    median_opportunities_per_year: Decimal = Decimal("0")
    maximum_opportunities_per_year: int = 0
    average_trades_per_symbol: Decimal = Decimal("0")
    median_trades_per_symbol: Decimal = Decimal("0")
    opportunity_day_clusters: int = 0
    longest_opportunity_day_streak: int = 0
    pending_outcomes: int = 0
    not_entered_outcomes: int = 0


@dataclass(frozen=True, slots=True)
class CanonicalUniverseAuditReport:
    audit_id: str
    generated_at: datetime
    canonical_engine_version: str
    dataset: DatasetManifest
    daily: tuple[DailyOpportunityRecord, ...]
    rankings: tuple[CandidateRankingRecord, ...]
    gates: tuple[GateAttributionRecord, ...]
    outcomes: tuple[CandidateOutcomeRecord, ...]
    monthly: tuple[MonthlyOpportunitySummary, ...]
    weekly: tuple[PeriodOpportunitySummary, ...]
    yearly: tuple[PeriodOpportunitySummary, ...]
    sectors: tuple[SectorOpportunitySummary, ...]
    liquidity: tuple[LiquidityCapacityRecord, ...]
    symbols: tuple[SymbolOpportunitySummary, ...]
    executive: ExecutiveSummary
    definitions: MappingProxyType[str, str]
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("ACU cannot influence production")
        if self.canonical_engine_version != CANONICAL_ENGINE_VERSION:
            raise ValueError("ACU report must use the frozen canonical engine")
        object.__setattr__(self, "daily", tuple(self.daily))
        object.__setattr__(self, "rankings", tuple(self.rankings))
        object.__setattr__(self, "gates", tuple(self.gates))
        object.__setattr__(self, "outcomes", tuple(self.outcomes))
        object.__setattr__(self, "monthly", tuple(self.monthly))
        object.__setattr__(self, "weekly", tuple(self.weekly))
        object.__setattr__(self, "yearly", tuple(self.yearly))
        object.__setattr__(self, "sectors", tuple(self.sectors))
        object.__setattr__(self, "liquidity", tuple(self.liquidity))
        object.__setattr__(self, "symbols", tuple(self.symbols))
        object.__setattr__(
            self,
            "definitions",
            MappingProxyType(dict(sorted(self.definitions.items()))),
        )


def to_primitive(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, MappingProxyType):
        return {key: to_primitive(item) for key, item in value.items()}
    if isinstance(value, dict):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_primitive(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: to_primitive(getattr(value, item.name)) for item in fields(value)
        }
    return value


__all__ = [
    "ACU_SCHEMA_VERSION",
    "ACU_RUN_VERSION",
    "CANONICAL_ENGINE_VERSION",
    "DATASET_CONFIDENCE",
    "DATASET_VERSION",
    "EVIDENCE_LABELS",
    "PRODUCTION_INFLUENCE",
    "CandidateOutcomeRecord",
    "CandidateRankingRecord",
    "CanonicalUniverseAuditReport",
    "DailyOpportunityRecord",
    "DatasetManifest",
    "ExecutiveSummary",
    "GateAttributionRecord",
    "GateCategory",
    "LiquidityBucket",
    "LiquidityCapacityRecord",
    "MonthlyOpportunitySummary",
    "OpportunityHeat",
    "PeriodOpportunitySummary",
    "SectorOpportunitySummary",
    "SymbolOpportunitySummary",
    "to_primitive",
]
