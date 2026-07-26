"""Typed research-only contracts for the DSI-007 strategy tournament."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

DSI007_CONTRACT_VERSION = "DSI-007-v1.0.0"
DSI007_RESEARCH_SCOPE = "GOVERNED_REGIME_STRATEGY_TOURNAMENT"


class TournamentError(ValueError):
    """Raised when a governed DSI-007 contract cannot be satisfied."""


class RegimeState(StrEnum):
    """Point-in-time market states applied only to a later session."""

    BULL_TREND_LOW_VOLATILITY = "BULL_TREND_LOW_VOLATILITY"
    BULL_TREND_HIGH_VOLATILITY = "BULL_TREND_HIGH_VOLATILITY"
    SIDEWAYS_LOW_VOLATILITY = "SIDEWAYS_LOW_VOLATILITY"
    SIDEWAYS_HIGH_VOLATILITY = "SIDEWAYS_HIGH_VOLATILITY"
    BEAR_TREND = "BEAR_TREND"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


class StrategyFamily(StrEnum):
    MOMENTUM_BREAKOUT = "MOMENTUM_BREAKOUT"
    TREND_FOLLOWING = "TREND_FOLLOWING"
    PULLBACK_ENTRY = "PULLBACK_ENTRY"
    RELATIVE_STRENGTH_CONTINUATION = "RELATIVE_STRENGTH_CONTINUATION"
    VOLATILITY_CONTRACTION = "VOLATILITY_CONTRACTION"
    RETEST_HOLD = "RETEST_HOLD"
    MEAN_REVERSION = "MEAN_REVERSION"
    FAILED_BREAKOUT_AVOIDANCE = "FAILED_BREAKOUT_AVOIDANCE"
    TREND_FAILURE_AVOIDANCE = "TREND_FAILURE_AVOIDANCE"
    NO_TRADE = "NO_TRADE"


class EntryState(StrEnum):
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    ENTRY_PENDING = "ENTRY_PENDING"
    ENTRY_TRIGGERED = "ENTRY_TRIGGERED"
    NOT_ENTERED = "NOT_ENTERED"
    INVALIDATED_BEFORE_ENTRY = "INVALIDATED_BEFORE_ENTRY"
    ENTRY_DATA_UNAVAILABLE = "ENTRY_DATA_UNAVAILABLE"


class ExitReason(StrEnum):
    STOP = "STOP"
    TARGET = "TARGET"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_EXIT = "TIME_EXIT"
    INVALIDATION = "INVALIDATION"
    END_OF_DATA = "END_OF_DATA"


class BenchmarkStatus(StrEnum):
    AVAILABLE_TOTAL_RETURN = "AVAILABLE_TOTAL_RETURN"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"


class OverfittingState(StrEnum):
    ROBUST_OUT_OF_SAMPLE_EVIDENCE = "ROBUST_OUT_OF_SAMPLE_EVIDENCE"
    DIRECTIONALLY_STABLE = "DIRECTIONALLY_STABLE"
    DESCRIPTIVE_ONLY = "DESCRIPTIVE_ONLY"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    HIGH_PARAMETER_SENSITIVITY = "HIGH_PARAMETER_SENSITIVITY"
    HIGH_REGIME_SENSITIVITY = "HIGH_REGIME_SENSITIVITY"
    HIGH_SECURITY_CONCENTRATION = "HIGH_SECURITY_CONCENTRATION"
    HIGH_PERIOD_CONCENTRATION = "HIGH_PERIOD_CONCENTRATION"
    MULTIPLE_TESTING_NOT_SURVIVED = "MULTIPLE_TESTING_NOT_SURVIVED"
    NO_GENERALISABLE_STRATEGY_FOUND = "NO_GENERALISABLE_STRATEGY_FOUND"


class SliceReadiness(StrEnum):
    A_READY = "READY_FOR_GOVERNED_STRATEGY_TOURNAMENT"
    A_PARTIAL = "READY_WITH_PARTIAL_HISTORICAL_COVERAGE"
    A_DATA_BLOCKED = "BLOCKED_BY_INSUFFICIENT_HISTORICAL_MARKET_DATA"
    A_SURVIVORSHIP_BLOCKED = "BLOCKED_BY_SURVIVORSHIP_BIAS"
    A_ACTION_BLOCKED = "BLOCKED_BY_CORPORATE_ACTION_INTEGRITY_DEFECT"
    A_UNIVERSE_BLOCKED = "BLOCKED_BY_POINT_IN_TIME_UNIVERSE_DEFECT"
    A_BENCHMARK_BLOCKED = "BLOCKED_BY_BENCHMARK_DATA_DEFECT"
    A_IMPLEMENTATION = "BLOCKED_BY_MARKET_DATA_IMPLEMENTATION_DEFECT"
    B_READY = "READY_FOR_GOVERNED_POINT_IN_TIME_REGIME_RESEARCH"
    B_LIMITED = "READY_WITH_LIMITED_REGIME_COVERAGE"
    B_A_BLOCKED = "BLOCKED_BY_DSI007A_NOT_READY"
    B_LEAKAGE = "BLOCKED_BY_REGIME_LOOKAHEAD_LEAKAGE"
    B_NONDETERMINISTIC = "BLOCKED_BY_REGIME_NONDETERMINISM"
    B_UNKNOWN = "BLOCKED_BY_EXCESSIVE_UNKNOWN_REGIME"
    B_CALIBRATION = "BLOCKED_BY_REGIME_CALIBRATION_DEFECT"
    B_IMPLEMENTATION = "BLOCKED_BY_REGIME_MODEL_IMPLEMENTATION_DEFECT"
    C_READY = "READY_FOR_GOVERNED_STRATEGY_VARIANT_EVALUATION"
    C_B_BLOCKED = "BLOCKED_BY_DSI007B_NOT_READY"
    C_EMPTY = "BLOCKED_BY_EMPTY_STRATEGY_REGISTRY"
    C_UNBOUNDED = "BLOCKED_BY_UNBOUNDED_SEARCH_SPACE"
    C_INVALID = "BLOCKED_BY_INVALID_STRATEGY_COMBINATIONS"
    C_DUPLICATE = "BLOCKED_BY_DUPLICATE_STRATEGY_VARIANTS"
    C_IMPLEMENTATION = "BLOCKED_BY_STRATEGY_REGISTRY_IMPLEMENTATION_DEFECT"
    D_READY = "READY_FOR_GOVERNED_STRATEGY_SIGNAL_REPLAY"
    D_ZERO = "READY_WITH_ZERO_SIGNAL_VARIANTS"
    D_C_BLOCKED = "BLOCKED_BY_DSI007C_NOT_READY"
    D_LEAKAGE = "BLOCKED_BY_SIGNAL_LOOKAHEAD_LEAKAGE"
    D_PLAN = "BLOCKED_BY_INVALID_TRADE_PLAN"
    D_ENTRY = "BLOCKED_BY_ENTRY_EXECUTION_DEFECT"
    D_RECONCILIATION = "BLOCKED_BY_SIGNAL_RECONCILIATION_DEFECT"
    D_IMPLEMENTATION = "BLOCKED_BY_SIGNAL_GENERATION_IMPLEMENTATION_DEFECT"
    E_READY = "READY_FOR_GOVERNED_PORTFOLIO_BACKTEST"
    E_ZERO = "READY_WITH_ZERO_EXECUTED_TRADES"
    E_D_BLOCKED = "BLOCKED_BY_DSI007D_NOT_READY"
    E_CAPITAL = "BLOCKED_BY_PORTFOLIO_CAPITAL_RECONCILIATION_DEFECT"
    E_EXECUTION = "BLOCKED_BY_UNREALISTIC_EXECUTION_ASSUMPTION"
    E_COST = "BLOCKED_BY_COST_MODEL_DEFECT"
    E_LIQUIDITY = "BLOCKED_BY_LIQUIDITY_OR_CAPACITY_DEFECT"
    E_IMPLEMENTATION = "BLOCKED_BY_PORTFOLIO_SIMULATOR_IMPLEMENTATION_DEFECT"
    F_READY = "READY_FOR_GOVERNED_WALK_FORWARD_SELECTION"
    F_NO_QUALIFYING = "READY_WITH_NO_QUALIFYING_STRATEGY"
    F_E_BLOCKED = "BLOCKED_BY_DSI007E_NOT_READY"
    F_LEAKAGE = "BLOCKED_BY_TRAIN_VALIDATION_TEST_LEAKAGE"
    F_SAMPLE = "BLOCKED_BY_INSUFFICIENT_TRAINING_SAMPLE"
    F_NONDETERMINISTIC = "BLOCKED_BY_NONDETERMINISTIC_STRATEGY_SELECTION"
    F_OBJECTIVE = "BLOCKED_BY_SELECTION_OBJECTIVE_DEFECT"
    F_IMPLEMENTATION = "BLOCKED_BY_WALK_FORWARD_IMPLEMENTATION_DEFECT"
    G_READY = "READY_FOR_GOVERNED_REGIME_AWARE_PORTFOLIO_RESEARCH"
    G_NO_ADVANTAGE = "READY_WITH_NO_REGIME_SELECTION_ADVANTAGE"
    G_ZERO = "READY_WITH_ZERO_STRATEGY_DEPLOYMENT"
    G_F_BLOCKED = "BLOCKED_BY_DSI007F_NOT_READY"
    G_LEAKAGE = "BLOCKED_BY_SELECTOR_LOOKAHEAD_LEAKAGE"
    G_MAPPING = "BLOCKED_BY_REGIME_STRATEGY_MAPPING_DEFECT"
    G_COMPARISON = "BLOCKED_BY_COMPARISON_PORTFOLIO_DEFECT"
    G_IMPLEMENTATION = "BLOCKED_BY_SELECTOR_IMPLEMENTATION_DEFECT"
    H_READY = "READY_FOR_GOVERNED_BENCHMARK_RELATIVE_PERFORMANCE_RESEARCH"
    H_LIMITED = "READY_WITH_INSUFFICIENT_HISTORY_FOR_LONG_HORIZON_METRICS"
    H_G_BLOCKED = "BLOCKED_BY_DSI007G_NOT_READY"
    H_BENCHMARK = "BLOCKED_BY_BENCHMARK_ALIGNMENT_DEFECT"
    H_EQUITY = "BLOCKED_BY_EQUITY_CURVE_RECONCILIATION_DEFECT"
    H_CAGR = "BLOCKED_BY_CAGR_CALCULATION_DEFECT"
    H_RISK = "BLOCKED_BY_RISK_METRIC_DEFECT"
    H_IMPLEMENTATION = "BLOCKED_BY_BENCHMARK_ANALYSIS_IMPLEMENTATION_DEFECT"
    I_READY = "READY_FOR_GOVERNED_STRATEGY_TOURNAMENT_CONCLUSION"
    I_DESCRIPTIVE = "READY_WITH_DESCRIPTIVE_STRATEGY_RESULTS_ONLY"
    I_H_BLOCKED = "BLOCKED_BY_DSI007H_NOT_READY"
    I_MULTIPLE = "BLOCKED_BY_MULTIPLE_TESTING_CONTROL_DEFECT"
    I_OVERFIT = "BLOCKED_BY_UNRESOLVED_OVERFITTING_RISK"
    I_ROBUSTNESS = "BLOCKED_BY_ROBUSTNESS_FAILURE"
    I_CLAIM = "BLOCKED_BY_UNSUPPORTED_STRATEGY_SUPERIORITY_CLAIM"
    I_IMPLEMENTATION = "BLOCKED_BY_OVERFITTING_AUDIT_IMPLEMENTATION_DEFECT"
    J_FORWARD = "READY_FOR_FORWARD_PAPER_STRATEGY_RESEARCH"
    J_DESCRIPTIVE = "READY_FOR_DESCRIPTIVE_REGIME_STRATEGY_RESEARCH_ONLY"
    J_NO_GENERALISABLE = "READY_WITH_NO_GENERALISABLE_STRATEGY"
    J_DATA = "BLOCKED_BY_INSUFFICIENT_HISTORICAL_DATA"
    J_MARKET = "BLOCKED_BY_MARKET_DATA_INTEGRITY_DEFECT"
    J_BENCHMARK = "BLOCKED_BY_BENCHMARK_DEFECT"
    J_REGIME_LEAKAGE = "BLOCKED_BY_REGIME_LOOKAHEAD_LEAKAGE"
    J_WALK_FORWARD = "BLOCKED_BY_WALK_FORWARD_LEAKAGE"
    J_PORTFOLIO = "BLOCKED_BY_PORTFOLIO_SIMULATION_DEFECT"
    J_OVERFIT = "BLOCKED_BY_MULTIPLE_TESTING_OR_OVERFITTING"
    J_POPULATION = "BLOCKED_BY_POPULATION_RECONCILIATION_DEFECT"
    J_ARTIFACT = "BLOCKED_BY_ARTIFACT_INTEGRITY_DEFECT"
    J_IMPLEMENTATION = "BLOCKED_BY_DSI007_IMPLEMENTATION_DEFECT"


@dataclass(frozen=True, slots=True)
class TournamentSourcePaths:
    """Caller-selected immutable research inputs."""

    database: Path
    historical_truth_snapshots: Path
    benchmark: str
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class TournamentPolicy:
    """Frozen research assumptions; none alter Alpha production policy."""

    starting_capital: float = 1_000_000.0
    maximum_positions: int = 5
    maximum_position_fraction: float = 0.15
    maximum_gross_exposure: float = 0.75
    maximum_sector_exposure: float = 0.30
    maximum_market_volume_fraction: float = 0.01
    minimum_average_traded_value: float = 5_000_000.0
    transaction_cost_fraction: float = 0.002
    slippage_fraction: float = 0.001
    maximum_variant_count: int = 24
    minimum_selection_trades: int = 8
    risk_free_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.starting_capital <= 0:
            raise TournamentError("starting capital must be positive")
        if self.maximum_positions < 1:
            raise TournamentError("maximum positions must be positive")
        for label, value in (
            ("maximum position fraction", self.maximum_position_fraction),
            ("maximum gross exposure", self.maximum_gross_exposure),
            ("maximum sector exposure", self.maximum_sector_exposure),
            ("maximum market volume fraction", self.maximum_market_volume_fraction),
        ):
            if not 0 < value <= 1:
                raise TournamentError(f"{label} must be in (0, 1]")
        if self.transaction_cost_fraction < 0 or self.slippage_fraction < 0:
            raise TournamentError("cost assumptions cannot be negative")
        if self.maximum_variant_count < 1:
            raise TournamentError("maximum variant count must be positive")
        if self.minimum_selection_trades < 1:
            raise TournamentError("minimum selection trades must be positive")


@dataclass(frozen=True, slots=True)
class StrategyVariant:
    """One bounded, interpretable strategy definition."""

    strategy_variant_id: str
    family: StrategyFamily
    parameters: MappingProxyType[str, float]
    components: tuple[str, ...]
    expected_regimes: tuple[RegimeState, ...]
    complexity_score: int
    source_definition: str
    valid_price_arms: tuple[str, ...] = ("ADJUSTED",)
    prerequisites: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.strategy_variant_id.strip():
            raise TournamentError("strategy variant ID cannot be empty")
        if self.complexity_score < 0:
            raise TournamentError("strategy complexity cannot be negative")
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(sorted(self.parameters.items()))),
        )


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    walk_forward_fold_id: str
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date

    def __post_init__(self) -> None:
        if not (
            self.train_start
            <= self.train_end
            < self.validation_start
            <= self.validation_end
            < self.test_start
            <= self.test_end
        ):
            raise TournamentError("walk-forward periods must be disjoint and ordered")


@dataclass(frozen=True, slots=True)
class TournamentResult:
    """Deterministic DSI-007 rows and conclusions."""

    source_commit: str
    readiness: MappingProxyType[str, str]
    blockers: tuple[str, ...]
    rows: MappingProxyType[str, tuple[dict[str, Any], ...]]
    summaries: MappingProxyType[str, Any]
    governance: MappingProxyType[str, bool] = field(
        default_factory=lambda: MappingProxyType({})
    )
