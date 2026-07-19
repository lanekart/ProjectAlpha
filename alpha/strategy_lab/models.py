from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from alpha.recommendation_intelligence.models import OHLCVBar
from alpha.strategy_discovery.models import StrategyCondition

PRODUCTION_INFLUENCE = False
STRATEGY_LAB_SCHEMA_VERSION = "strategy-lab-v1.2"


class LabEvidenceClass(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    RECONSTRUCTED = "RECONSTRUCTED"
    PROVISIONAL = "PROVISIONAL"
    FORWARD_OBSERVED = "FORWARD_OBSERVED"


class EvidenceLabel(StrEnum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    RECONSTRUCTED_RESEARCH_ONLY = "RECONSTRUCTED_RESEARCH_ONLY"
    PROVISIONAL = "PROVISIONAL"
    OUT_OF_SAMPLE_VALIDATED = "OUT_OF_SAMPLE_VALIDATED"
    FORWARD_OBSERVED = "FORWARD_OBSERVED"
    AUTHORITATIVE = "AUTHORITATIVE"


class StrategyClassification(StrEnum):
    INVALID_DATA = "INVALID_DATA"
    LEAKAGE_RISK = "LEAKAGE_RISK"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    NEGATIVE_EXPECTANCY = "NEGATIVE_EXPECTANCY"
    NO_MATERIAL_EDGE = "NO_MATERIAL_EDGE"
    OVERFIT = "OVERFIT"
    UNSTABLE = "UNSTABLE"
    RECONSTRUCTED_RESEARCH_ONLY = "RECONSTRUCTED_RESEARCH_ONLY"
    WALK_FORWARD_CANDIDATE = "WALK_FORWARD_CANDIDATE"
    SHADOW_VALIDATION_CANDIDATE = "SHADOW_VALIDATION_CANDIDATE"


class AttributionClassification(StrEnum):
    POSITIVE_MARGINAL_VALUE = "POSITIVE_MARGINAL_VALUE"
    NEGATIVE_MARGINAL_VALUE = "NEGATIVE_MARGINAL_VALUE"
    REDUNDANT = "REDUNDANT"
    UNSTABLE = "UNSTABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    LINEAGE_CONFOUNDED = "LINEAGE_CONFOUNDED"


class EntryRule(StrEnum):
    RECORDED_REFERENCE = "RECORDED_REFERENCE"
    NEXT_SESSION_OPEN = "NEXT_SESSION_OPEN"
    NEXT_SESSION_CLOSE = "NEXT_SESSION_CLOSE"
    PREFERRED_ENTRY = "PREFERRED_ENTRY"
    AGGRESSIVE_ENTRY = "AGGRESSIVE_ENTRY"
    CONFIRMATION_ENTRY = "CONFIRMATION_ENTRY"
    BREAKOUT_ENTRY = "BREAKOUT_ENTRY"
    LIMIT_ENTRY_ZONE = "LIMIT_ENTRY_ZONE"


class StopRule(StrEnum):
    RECORDED_PLAN = "RECORDED_PLAN"
    FIXED_PERCENT = "FIXED_PERCENT"
    ATR_BASED = "ATR_BASED"
    SUPPORT_BASED = "SUPPORT_BASED"
    SWING_LOW = "SWING_LOW"
    VOLATILITY_ADJUSTED = "VOLATILITY_ADJUSTED"


class TargetRule(StrEnum):
    RECORDED_PLAN = "RECORDED_PLAN"
    FIXED_REWARD_RISK = "FIXED_REWARD_RISK"
    PARTIAL_THEN_RUNNER = "PARTIAL_THEN_RUNNER"
    TRAILING_AFTER_TARGET_1 = "TRAILING_AFTER_TARGET_1"
    TIME_EXIT = "TIME_EXIT"


class TradeExitReason(StrEnum):
    STOP = "STOP"
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    TARGET_3 = "TARGET_3"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_EXIT = "TIME_EXIT"
    END_OF_HORIZON = "END_OF_HORIZON"
    NOT_ENTERED = "NOT_ENTERED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class LeaderboardView(StrEnum):
    COMPOSITE = "COMPOSITE"
    EXPECTANCY = "EXPECTANCY"
    PRECISION = "PRECISION"
    PROFIT_FACTOR = "PROFIT_FACTOR"
    PAYOFF = "PAYOFF"
    DRAWDOWN = "DRAWDOWN"
    RISK_ADJUSTED = "RISK_ADJUSTED"
    CAPITAL_UTILISATION = "CAPITAL_UTILISATION"
    STABILITY = "STABILITY"


@dataclass(frozen=True, slots=True)
class IndicatorDefinition:
    canonical_id: str
    name: str
    category: str
    unit: str
    valid_range: str
    timestamp_semantics: str
    missing_data_treatment: str
    provenance: str
    historical_availability: str
    evidence_class: LabEvidenceClass
    lineage_overlaps: tuple[str, ...]
    known_defects: tuple[str, ...]
    quarantined: bool
    quarantine_reason: str | None

    def __post_init__(self) -> None:
        if not self.canonical_id or not self.name or not self.provenance:
            raise ValueError("indicator identity and provenance are required")
        if self.quarantined and not self.quarantine_reason:
            raise ValueError("quarantined indicator requires a reason")


@dataclass(frozen=True, slots=True)
class StrategyTemplate:
    template_id: str
    name: str
    family: str
    description: str
    maximum_components: int
    supported_entry_rules: tuple[EntryRule, ...]
    supported_stop_rules: tuple[StopRule, ...]
    supported_target_rules: tuple[TargetRule, ...]
    benchmark: bool = False


@dataclass(frozen=True, slots=True)
class ExecutionAssumptionProfile:
    profile_id: str
    brokerage_bps: Decimal
    stt_bps: Decimal
    exchange_charge_bps: Decimal
    gst_bps: Decimal
    stamp_duty_bps: Decimal
    other_transaction_cost_bps: Decimal
    slippage_bps: Decimal
    bid_ask_impact_bps: Decimal
    entry_delay_sessions: int
    entry_validity_sessions: int
    partial_fill_fraction: Decimal
    capital_per_trade_pct: Decimal
    gap_through_stop_policy: str
    ambiguous_bar_policy: str
    rationale: str
    version: str

    def __post_init__(self) -> None:
        values = (
            self.brokerage_bps,
            self.stt_bps,
            self.exchange_charge_bps,
            self.gst_bps,
            self.stamp_duty_bps,
            self.other_transaction_cost_bps,
            self.slippage_bps,
            self.bid_ask_impact_bps,
        )
        if any(value < Decimal("0") for value in values):
            raise ValueError("execution costs cannot be negative")
        if self.entry_validity_sessions < 1 or self.entry_delay_sessions < 0:
            raise ValueError("execution windows must be non-negative")
        if not Decimal("0") < self.partial_fill_fraction <= Decimal("1"):
            raise ValueError("partial fill fraction must be in (0, 1]")

    @property
    def one_way_cost_bps(self) -> Decimal:
        return sum(
            (
                self.brokerage_bps,
                self.stt_bps,
                self.exchange_charge_bps,
                self.gst_bps,
                self.stamp_duty_bps,
                self.other_transaction_cost_bps,
                self.slippage_bps,
                self.bid_ask_impact_bps,
            ),
            start=Decimal("0"),
        )

    @property
    def round_trip_cost_pct(self) -> Decimal:
        return self.one_way_cost_bps * Decimal("2") / Decimal("100")


@dataclass(frozen=True, slots=True)
class LabStrategySpecification:
    strategy_id: str
    strategy_hash: str
    source_strategy_version: str
    name: str
    family: str
    conditions: tuple[StrategyCondition, ...]
    entry_rule: EntryRule
    stop_rule: StopRule
    target_rule: TargetRule
    holding_period_days: int
    execution_profile_id: str
    dataset_version: str
    evidence_class: LabEvidenceClass
    benchmark: bool
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("strategy lab specifications cannot influence production")
        if self.holding_period_days < 1:
            raise ValueError("holding period must be positive")
        object.__setattr__(
            self,
            "conditions",
            tuple(sorted(self.conditions, key=lambda item: item.canonical_key)),
        )


@dataclass(frozen=True, slots=True)
class SearchSpaceSummary:
    search_space_hash: str
    total_trials: int
    generated_strategies: int
    duplicate_rules_removed: int
    impossible_rules_rejected: int
    lineage_redundancy_flags: int
    maximum_components: int
    maximum_variants_per_family: int
    family_counts: Mapping[str, int]
    rules_tested: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "family_counts",
            MappingProxyType(dict(sorted(self.family_counts.items()))),
        )


@dataclass(frozen=True, slots=True)
class TradeSimulationRequest:
    recommendation_id: str
    symbol: str
    decision_time: datetime
    bars: tuple[OHLCVBar, ...]
    entry_rule: EntryRule
    stop_rule: StopRule
    target_rule: TargetRule
    entry_zone_low: Decimal | None = None
    entry_zone_high: Decimal | None = None
    confirmation_entry: Decimal | None = None
    recorded_stop: Decimal | None = None
    target_1: Decimal | None = None
    target_2: Decimal | None = None
    target_3: Decimal | None = None
    support: Decimal | None = None
    swing_low: Decimal | None = None
    atr: Decimal | None = None
    fixed_stop_pct: Decimal = Decimal("5")
    fixed_target_r: Decimal = Decimal("2")
    holding_period_days: int = 20


@dataclass(frozen=True, slots=True)
class TradeSimulation:
    recommendation_id: str
    symbol: str
    entered: bool
    entry_time: datetime | None
    entry_price: Decimal | None
    entry_delay_sessions: int | None
    stop_price: Decimal | None
    targets: tuple[Decimal, ...]
    exit_time: datetime | None
    exit_price: Decimal | None
    exit_reason: TradeExitReason
    gross_return_pct: Decimal | None
    net_return_pct: Decimal | None
    mfe_pct: Decimal | None
    mae_pct: Decimal | None
    realised_r_multiple: Decimal | None
    holding_period_days: int | None
    costs_pct: Decimal
    slippage_pct: Decimal
    partial_exit_fraction: Decimal
    ambiguity_count: int
    missed_trade_reason: str | None
    audit: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyPerformanceMetrics:
    signals_generated: int
    trades_entered: int
    missed_entries: int
    completed_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_pct: Decimal | None
    loss_rate_pct: Decimal | None
    precision_pct: Decimal | None
    precision_ci_low_pct: Decimal | None
    precision_ci_high_pct: Decimal | None
    recall_pct: Decimal | None
    false_positives: int | None
    false_negatives: int | None
    average_return_pct: Decimal | None
    median_return_pct: Decimal | None
    average_winner_pct: Decimal | None
    median_winner_pct: Decimal | None
    average_loser_pct: Decimal | None
    median_loser_pct: Decimal | None
    payoff_ratio: Decimal | None
    expectancy_pct: Decimal | None
    gross_expectancy_pct: Decimal | None
    profit_factor: Decimal | None
    average_r_multiple: Decimal | None
    median_r_multiple: Decimal | None
    average_mfe_pct: Decimal | None
    average_mae_pct: Decimal | None
    average_holding_period_days: Decimal | None
    maximum_drawdown_pct: Decimal | None
    average_drawdown_pct: Decimal | None
    downside_deviation_pct: Decimal | None
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    calmar_ratio: Decimal | None
    longest_losing_streak: int
    longest_winning_streak: int
    worst_trade_pct: Decimal | None
    best_trade_pct: Decimal | None
    tail_loss_pct: Decimal | None
    gap_loss_exposure_pct: Decimal | None
    starting_capital: Decimal
    ending_capital: Decimal
    cagr_pct: Decimal | None
    total_return_pct: Decimal | None
    capital_utilisation_pct: Decimal | None
    turnover: int
    maximum_concurrent_positions: int | None
    cash_drag_pct: Decimal | None
    largest_winner_contribution_pct: Decimal | None
    symbol_concentration_pct: Decimal | None
    positive_period_pct: Decimal | None
    years_represented: int
    symbols_represented: int
    net_cost_drag_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class PeriodPerformance:
    period: str
    completed_trades: int
    precision_pct: Decimal | None
    expectancy_pct: Decimal | None
    profit_factor: Decimal | None
    net_return_pct: Decimal | None
    maximum_drawdown_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class RollingPerformance:
    end_date: date
    window: int
    completed_trades: int
    precision_pct: Decimal | None
    expectancy_pct: Decimal | None
    profit_factor: Decimal | None
    drawdown_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class TimeSeriesReport:
    strategy_id: str
    annual: tuple[PeriodPerformance, ...]
    quarterly: tuple[PeriodPerformance, ...]
    rolling_20: tuple[RollingPerformance, ...]
    rolling_50: tuple[RollingPerformance, ...]
    equity_curve: tuple[tuple[date, Decimal], ...]
    underwater_curve: tuple[tuple[date, Decimal], ...]


@dataclass(frozen=True, slots=True)
class ComponentAttribution:
    component_id: str
    strategy_id: str
    baseline_strategy_id: str | None
    trade_count_delta: int
    precision_delta_pct: Decimal | None
    expectancy_delta_pct: Decimal | None
    profit_factor_delta: Decimal | None
    payoff_delta: Decimal | None
    drawdown_delta_pct: Decimal | None
    capital_utilisation_delta_pct: Decimal | None
    turnover_delta: int
    classification: AttributionClassification
    lineage_warning: str | None
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CombinationAttribution:
    strategy_id: str
    source: str
    dominant_component: str | None
    opportunity_reduction_pct: Decimal | None
    symbol_concentration_pct: Decimal | None
    period_concentration_pct: Decimal | None
    winner_concentration_pct: Decimal | None
    explanation: str


@dataclass(frozen=True, slots=True)
class LabRobustnessResult:
    strategy_id: str
    fold_consistency_pct: Decimal | None
    parameter_perturbation_passed: bool
    indicator_ablation_passed: bool
    cost_stress_passed: bool
    slippage_stress_passed: bool
    delayed_entry_status: str
    missed_fill_status: str
    stop_gap_status: str
    bootstrap_expectancy_low_pct: Decimal | None
    bootstrap_expectancy_high_pct: Decimal | None
    adjusted_p_value: Decimal | None
    hypotheses_tested: int
    overfit: bool
    weaknesses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LabStrategyResult:
    strategy: LabStrategySpecification
    metrics: StrategyPerformanceMetrics
    evidence_label: EvidenceLabel
    classification: StrategyClassification
    classification_reasons: tuple[str, ...]
    research_score: Decimal | None
    score_breakdown: Mapping[str, Decimal | None]
    selected_candidate_ids: tuple[str, ...]
    timeline: TimeSeriesReport
    robustness: LabRobustnessResult | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "score_breakdown",
            MappingProxyType(dict(sorted(self.score_breakdown.items()))),
        )


@dataclass(frozen=True, slots=True)
class StrategyComparison:
    strategy_ids: tuple[str, ...]
    rule_definitions: Mapping[str, tuple[str, ...]]
    shared_population: int
    common_trade_count: int
    unique_trade_counts: Mapping[str, int]
    precision_deltas: Mapping[str, Decimal | None]
    expectancy_deltas: Mapping[str, Decimal | None]
    drawdown_deltas: Mapping[str, Decimal | None]
    capital_utilisation_deltas: Mapping[str, Decimal | None]
    cost_sensitivity_pct: Mapping[str, Decimal | None]
    yearly_expectancy_deltas: Mapping[str, tuple[tuple[str, Decimal | None], ...]]
    evidence_confidence: str
    conclusion: str


@dataclass(frozen=True, slots=True)
class StrategyLabReport:
    generated_at: datetime
    experiment_id: str
    dataset_version: str
    evidence_class: LabEvidenceClass
    source_rows: int
    excluded_rows: int
    indicators: tuple[IndicatorDefinition, ...]
    templates: tuple[StrategyTemplate, ...]
    search_space: SearchSpaceSummary
    execution_profile: ExecutionAssumptionProfile
    results: tuple[LabStrategyResult, ...]
    component_attribution: tuple[ComponentAttribution, ...]
    combination_attribution: tuple[CombinationAttribution, ...]
    final_conclusion: str
    strongest_strategy_id: str | None
    highest_value_evidence_gap: str
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("strategy lab reports cannot influence production")
        if self.generated_at.tzinfo is None:
            object.__setattr__(
                self, "generated_at", self.generated_at.replace(tzinfo=UTC)
            )


__all__ = [
    "AttributionClassification",
    "CombinationAttribution",
    "ComponentAttribution",
    "EntryRule",
    "EvidenceLabel",
    "ExecutionAssumptionProfile",
    "IndicatorDefinition",
    "LabEvidenceClass",
    "LabRobustnessResult",
    "LabStrategyResult",
    "LabStrategySpecification",
    "LeaderboardView",
    "PRODUCTION_INFLUENCE",
    "PeriodPerformance",
    "RollingPerformance",
    "STRATEGY_LAB_SCHEMA_VERSION",
    "SearchSpaceSummary",
    "StopRule",
    "StrategyClassification",
    "StrategyComparison",
    "StrategyLabReport",
    "StrategyPerformanceMetrics",
    "StrategyTemplate",
    "TargetRule",
    "TimeSeriesReport",
    "TradeExitReason",
    "TradeSimulation",
    "TradeSimulationRequest",
]
