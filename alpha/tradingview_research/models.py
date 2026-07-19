"""Immutable evidence models for the TradingView Research Laboratory."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

TRL_SCHEMA_VERSION = "tradingview-research-laboratory-v2"
PRODUCTION_INFLUENCE = False


class ResearchPartition(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"


class ObservationRole(StrEnum):
    ALPHA_BASELINE = "ALPHA_BASELINE"
    TREATMENT = "TREATMENT"


class CombinationMode(StrEnum):
    ANY = "ANY"
    ALL = "ALL"
    MINIMUM_N = "MINIMUM_N"
    WEIGHTED = "WEIGHTED"


class VariantFamily(StrEnum):
    COMPONENT_ABLATION = "COMPONENT_ABLATION"
    STOP_EXIT = "STOP_EXIT"
    MULTI_TIMEFRAME = "MULTI_TIMEFRAME"


class IndicatorId(StrEnum):
    EMA_TREND = "EMA_TREND"
    SMA_TREND = "SMA_TREND"
    VWAP = "VWAP"
    RELATIVE_VOLUME = "RELATIVE_VOLUME"
    VOLUME_MA = "VOLUME_MA"
    ADX = "ADX"
    RSI = "RSI"
    MACD = "MACD"
    ATR = "ATR"
    PRICE_STRUCTURE = "PRICE_STRUCTURE"
    RELATIVE_STRENGTH = "RELATIVE_STRENGTH"
    CANDLESTICK = "CANDLESTICK"
    BREAKOUT = "BREAKOUT"
    RETRACEMENT = "RETRACEMENT"
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class StrategyId(StrEnum):
    MOMENTUM_BREAKOUT = "MOMENTUM_BREAKOUT"
    PULLBACK_ENTRY = "PULLBACK_ENTRY"
    AGGRESSIVE_ACCUMULATION = "AGGRESSIVE_ACCUMULATION"
    RETEST_HOLD = "RETEST_HOLD"
    BULL_FLAG = "BULL_FLAG"
    FLAT_BASE = "FLAT_BASE"
    CUP_AND_HANDLE = "CUP_AND_HANDLE"
    VCP = "VCP"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"


class ComparisonOutcome(StrEnum):
    IMPROVED = "IMPROVED"
    UNCHANGED = "UNCHANGED"
    WORSE = "WORSE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class PromotionDecision(StrEnum):
    PROMOTE_TO_ALPHA_REPLAY = "PROMOTE_TO_ALPHA_REPLAY"
    REJECT = "REJECT"


class PromotionReason(StrEnum):
    MISSING_DEVELOPMENT = "MISSING_DEVELOPMENT"
    MISSING_VALIDATION = "MISSING_VALIDATION"
    MISSING_HOLDOUT = "MISSING_HOLDOUT"
    MISSING_COMPARABLE_METRICS = "MISSING_COMPARABLE_METRICS"
    NO_COMPLETED_TRADES = "NO_COMPLETED_TRADES"
    EXPECTANCY_NOT_IMPROVED = "EXPECTANCY_NOT_IMPROVED"
    DRAWDOWN_WORSE = "DRAWDOWN_WORSE"
    INSUFFICIENT_SYMBOL_DIVERSITY = "INSUFFICIENT_SYMBOL_DIVERSITY"
    INSUFFICIENT_SECTOR_DIVERSITY = "INSUFFICIENT_SECTOR_DIVERSITY"
    PARTITION_LEAKAGE = "PARTITION_LEAKAGE"
    ALL_RESEARCH_GATES_PASSED = "ALL_RESEARCH_GATES_PASSED"


@dataclass(frozen=True, slots=True)
class IndicatorSetting:
    indicator: IndicatorId
    enabled: bool

    def as_dict(self) -> dict[str, object]:
        return {"enabled": self.enabled, "indicator": self.indicator.value}


@dataclass(frozen=True, slots=True)
class StrategySetting:
    strategy: StrategyId
    enabled: bool
    weight: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        _require_finite_non_negative(self.weight, "strategy weight")

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "strategy": self.strategy.value,
            "weight": str(self.weight),
        }


@dataclass(frozen=True, slots=True)
class ComponentWeight:
    component: str
    weight: Decimal

    def __post_init__(self) -> None:
        component = self.component.strip().lower()
        if not component:
            raise ValueError("component cannot be blank")
        _require_finite_non_negative(self.weight, "component weight")
        object.__setattr__(self, "component", component)

    def as_dict(self) -> dict[str, str]:
        return {"component": self.component, "weight": str(self.weight)}


@dataclass(frozen=True, slots=True)
class LabConfiguration:
    name: str
    indicators: tuple[IndicatorSetting, ...]
    strategies: tuple[StrategySetting, ...]
    combination_mode: CombinationMode
    minimum_strategies: int
    weights: tuple[ComponentWeight, ...]
    stop_model: str
    exit_model: str
    trend_timeframe: str
    setup_timeframe: str
    entry_timeframe: str
    universe: str
    sector_scope: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("configuration name cannot be blank")
        indicator_ids = tuple(item.indicator for item in self.indicators)
        strategy_ids = tuple(item.strategy for item in self.strategies)
        component_ids = tuple(item.component for item in self.weights)
        if len(indicator_ids) != len(set(indicator_ids)):
            raise ValueError("indicator settings must be unique")
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("strategy settings must be unique")
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("component weights must be unique")
        enabled_strategies = sum(item.enabled for item in self.strategies)
        if self.minimum_strategies < 1:
            raise ValueError("minimum_strategies must be positive")
        if (
            self.combination_mode is CombinationMode.MINIMUM_N
            and self.minimum_strategies > enabled_strategies
        ):
            raise ValueError("minimum_strategies exceeds enabled strategies")
        for field_name in (
            "stop_model",
            "exit_model",
            "trend_timeframe",
            "setup_timeframe",
            "entry_timeframe",
            "universe",
            "sector_scope",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be blank")
        indicators = tuple(
            sorted(self.indicators, key=lambda item: item.indicator.value)
        )
        strategies = tuple(
            sorted(self.strategies, key=lambda item: item.strategy.value)
        )
        weights = tuple(sorted(self.weights, key=lambda item: item.component))
        object.__setattr__(self, "indicators", indicators)
        object.__setattr__(self, "strategies", strategies)
        object.__setattr__(self, "weights", weights)

    @property
    def configuration_id(self) -> str:
        encoded = json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "trl-config-" + hashlib.sha256(encoded).hexdigest()[:16]

    def as_dict(self) -> dict[str, object]:
        return {
            "combination_mode": self.combination_mode.value,
            "entry_timeframe": self.entry_timeframe,
            "exit_model": self.exit_model,
            "indicators": [item.as_dict() for item in self.indicators],
            "minimum_strategies": self.minimum_strategies,
            "name": self.name,
            "sector_scope": self.sector_scope,
            "setup_timeframe": self.setup_timeframe,
            "stop_model": self.stop_model,
            "strategies": [item.as_dict() for item in self.strategies],
            "trend_timeframe": self.trend_timeframe,
            "universe": self.universe,
            "weights": [item.as_dict() for item in self.weights],
        }


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    trade_count: int
    win_rate_pct: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    maximum_drawdown_pct: Decimal | None
    net_return_pct: Decimal | None
    average_winner: Decimal | None
    average_loser: Decimal | None
    stop_out_rate_pct: Decimal | None = None
    average_holding_period: Decimal | None = None

    def __post_init__(self) -> None:
        if self.trade_count < 0:
            raise ValueError("trade_count cannot be negative")
        for name in (
            "win_rate_pct",
            "profit_factor",
            "expectancy",
            "maximum_drawdown_pct",
            "net_return_pct",
            "average_winner",
            "average_loser",
            "stop_out_rate_pct",
            "average_holding_period",
        ):
            value = getattr(self, name)
            if value is not None and not value.is_finite():
                raise ValueError(f"{name} must be finite when available")
        for name in ("win_rate_pct", "stop_out_rate_pct"):
            value = getattr(self, name)
            if value is not None and not Decimal("0") <= value <= Decimal("100"):
                raise ValueError(f"{name} must be between 0 and 100")
        if self.maximum_drawdown_pct is not None and self.maximum_drawdown_pct < 0:
            raise ValueError("maximum_drawdown_pct cannot be negative")
        if self.profit_factor is not None and self.profit_factor < 0:
            raise ValueError("profit_factor cannot be negative")
        if self.trade_count == 0 and any(
            getattr(self, name) is not None
            for name in (
                "win_rate_pct",
                "profit_factor",
                "expectancy",
                "average_winner",
                "average_loser",
            )
        ):
            raise ValueError("zero-trade observations cannot carry trade metrics")

    def as_dict(self) -> dict[str, object]:
        return {
            "average_holding_period": _decimal_text(self.average_holding_period),
            "average_loser": _decimal_text(self.average_loser),
            "average_winner": _decimal_text(self.average_winner),
            "expectancy": _decimal_text(self.expectancy),
            "maximum_drawdown_pct": _decimal_text(self.maximum_drawdown_pct),
            "net_return_pct": _decimal_text(self.net_return_pct),
            "profit_factor": _decimal_text(self.profit_factor),
            "stop_out_rate_pct": _decimal_text(self.stop_out_rate_pct),
            "trade_count": self.trade_count,
            "win_rate_pct": _decimal_text(self.win_rate_pct),
        }


@dataclass(frozen=True, slots=True)
class ExperimentObservation:
    role: ObservationRole
    partition: ResearchPartition
    symbol: str
    sector: str
    period_start: date
    period_end: date
    metrics: PerformanceMetrics
    data_source: str = "TRADINGVIEW"

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        sector = self.sector.strip().upper()
        if not symbol or not sector:
            raise ValueError("observation symbol and sector are required")
        if self.period_end < self.period_start:
            raise ValueError("observation period cannot end before it starts")
        if self.data_source != "TRADINGVIEW":
            raise ValueError("TRL observations must retain TradingView provenance")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "sector", sector)

    @property
    def population_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.partition.value,
            self.symbol,
            self.sector,
            self.period_start.isoformat(),
            self.period_end.isoformat(),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "data_source": self.data_source,
            "metrics": self.metrics.as_dict(),
            "partition": self.partition.value,
            "period_end": self.period_end.isoformat(),
            "period_start": self.period_start.isoformat(),
            "role": self.role.value,
            "sector": self.sector,
            "symbol": self.symbol,
        }


@dataclass(frozen=True, slots=True)
class TradingViewExperiment:
    experiment_id: str
    title: str
    purpose: str
    experiment_date: date
    baseline: LabConfiguration
    treatment: LabConfiguration
    observations: tuple[ExperimentObservation, ...]
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        experiment_id = self.experiment_id.strip()
        if not experiment_id or not self.title.strip() or not self.purpose.strip():
            raise ValueError("experiment id, title, and purpose are required")
        if self.production_influence:
            raise ValueError("TRL experiments cannot influence production")
        role_keys = tuple(
            (item.role, item.population_key) for item in self.observations
        )
        if len(role_keys) != len(set(role_keys)):
            raise ValueError(
                "experiment observations must be unique by role and cohort"
            )
        object.__setattr__(self, "experiment_id", experiment_id)
        object.__setattr__(
            self,
            "observations",
            tuple(
                sorted(
                    self.observations,
                    key=lambda item: (item.population_key, item.role.value),
                )
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "baseline": self.baseline.as_dict(),
            "experiment_date": self.experiment_date.isoformat(),
            "experiment_id": self.experiment_id,
            "observations": [item.as_dict() for item in self.observations],
            "production_influence": self.production_influence,
            "purpose": self.purpose,
            "schema_version": TRL_SCHEMA_VERSION,
            "title": self.title,
            "treatment": self.treatment.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class MetricDelta:
    metric: str
    baseline: Decimal | int | None
    treatment: Decimal | int | None
    improvement: Decimal | int | None
    higher_is_better: bool


@dataclass(frozen=True, slots=True)
class CohortComparison:
    population_key: tuple[str, str, str, str, str]
    baseline_trades: int
    treatment_trades: int
    deltas: tuple[MetricDelta, ...]
    outcome: ComparisonOutcome

    def delta(self, metric: str) -> MetricDelta | None:
        return next((item for item in self.deltas if item.metric == metric), None)


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    experiment_id: str
    cohorts: tuple[CohortComparison, ...]
    unmatched_baseline_cohorts: int
    unmatched_treatment_cohorts: int
    improved_cohorts: int
    unchanged_cohorts: int
    worse_cohorts: int
    insufficient_cohorts: int
    weighted_expectancy_improvement: Decimal | None
    weighted_drawdown_improvement: Decimal | None
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class PromotionAssessment:
    experiment_id: str
    decision: PromotionDecision
    promote: bool
    passed_reasons: tuple[PromotionReason, ...]
    failed_reasons: tuple[PromotionReason, ...]
    explanation: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    rank: int
    experiment_id: str
    promotion_decision: PromotionDecision
    matched_cohorts: int
    improved_cohorts: int
    weighted_expectancy_improvement: Decimal | None
    weighted_drawdown_improvement: Decimal | None
    primary_rejection: PromotionReason | None
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class WeightRange:
    component: str
    minimum: Decimal
    maximum: Decimal
    step: Decimal

    def __post_init__(self) -> None:
        if not self.component.strip():
            raise ValueError("weight range component cannot be blank")
        for value in (self.minimum, self.maximum, self.step):
            _require_finite_non_negative(value, "weight range")
        if self.maximum < self.minimum or self.step <= 0:
            raise ValueError("weight range requires min <= max and step > 0")


@dataclass(frozen=True, slots=True)
class UniverseMember:
    symbol: str
    sector: str

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.sector.strip():
            raise ValueError("universe member requires symbol and sector")


@dataclass(frozen=True, slots=True)
class BatchRun:
    run_id: str
    symbol: str
    sector: str
    partition: ResearchPartition
    configuration_id: str


@dataclass(frozen=True, slots=True)
class DistributionStatistic:
    observation_count: int
    available_count: int
    missing_count: int
    minimum: Decimal | None
    median: Decimal | None
    maximum: Decimal | None

    def __post_init__(self) -> None:
        if (
            min(
                self.observation_count,
                self.available_count,
                self.missing_count,
            )
            < 0
        ):
            raise ValueError("distribution counts cannot be negative")
        if self.available_count + self.missing_count != self.observation_count:
            raise ValueError("distribution availability counts must reconcile")
        values = (self.minimum, self.median, self.maximum)
        if self.available_count == 0 and any(value is not None for value in values):
            raise ValueError("empty distributions cannot carry values")
        if self.available_count > 0 and any(value is None for value in values):
            raise ValueError("measured distributions require min, median, and max")


@dataclass(frozen=True, slots=True)
class SectorResearchSummary:
    partition: ResearchPartition
    sector: str
    symbols: tuple[str, ...]
    matched_cohorts: int
    treatment_trades: int
    win_rate_pct: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    recommendation: ComparisonOutcome
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class UniverseDistribution:
    partition: ResearchPartition
    role: ObservationRole
    symbols: tuple[str, ...]
    observations: int
    trade_count: int
    win_rate_pct: DistributionStatistic
    profit_factor: DistributionStatistic
    expectancy: DistributionStatistic
    production_influence: bool = PRODUCTION_INFLUENCE


def _require_finite_non_negative(value: Decimal, label: str) -> None:
    if not value.is_finite() or value < 0:
        raise ValueError(f"{label} must be finite and non-negative")


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
