"""Immutable contracts for the conversational Alpha Research Lab."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

LAB_VERSION = "DSI-011-v1.0.0"
PRODUCTION_INFLUENCE = False


class StrategyMode(StrEnum):
    ALPHA_SIGNAL = "ALPHA_SIGNAL"
    PURE_TECHNICAL = "PURE_TECHNICAL"
    HYBRID = "HYBRID"


class AlphaSignalSource(StrEnum):
    RECORDED_HISTORICAL_ALPHA_SIGNAL = "RECORDED_HISTORICAL_ALPHA_SIGNAL"
    RETROSPECTIVE_FROZEN_ALPHA_REPLAY = "RETROSPECTIVE_FROZEN_ALPHA_REPLAY"
    WALK_FORWARD_ALPHA_REPLAY = "WALK_FORWARD_ALPHA_REPLAY"


class LogicOperator(StrEnum):
    ALL = "ALL"
    ANY = "ANY"
    NOT = "NOT"
    N_OF_M = "N_OF_M"


class RuleKind(StrEnum):
    INDICATOR = "INDICATOR"
    CANDLE = "CANDLE"
    SIGNAL = "SIGNAL"


class ComparisonOperator(StrEnum):
    ABOVE = "ABOVE"
    BELOW = "BELOW"
    AT_LEAST = "AT_LEAST"
    AT_MOST = "AT_MOST"
    CROSSES_ABOVE = "CROSSES_ABOVE"
    CROSSES_BELOW = "CROSSES_BELOW"
    IS_TRUE = "IS_TRUE"


class SameSessionPolicy(StrEnum):
    ASSUME_STOP_FIRST = "ASSUME_STOP_FIRST"
    ASSUME_TARGET_FIRST = "ASSUME_TARGET_FIRST"


class ExperimentStatus(StrEnum):
    COMPILED = "COMPILED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class Condition:
    """One registry-governed leaf in the entry/exit expression tree."""

    condition_id: str
    kind: RuleKind
    name: str
    operator: ComparisonOperator = ComparisonOperator.IS_TRUE
    value: Decimal | None = None
    period: int | None = None
    reference: str | None = None
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.condition_id.strip() or not self.name.strip():
            raise ValueError("condition id and name are required")
        if self.period is not None and self.period < 1:
            raise ValueError("condition period must be positive")
        object.__setattr__(self, "condition_id", self.condition_id.strip().upper())
        object.__setattr__(self, "name", self.name.strip().upper())
        object.__setattr__(self, "parameters", tuple(sorted(self.parameters)))


@dataclass(frozen=True, slots=True)
class ConditionGroup:
    """Typed logical expression with no arbitrary-code execution surface."""

    operator: LogicOperator = LogicOperator.ALL
    conditions: tuple[Condition, ...] = ()
    groups: tuple[ConditionGroup, ...] = ()
    required_count: int | None = None

    def __post_init__(self) -> None:
        child_count = len(self.conditions) + len(self.groups)
        if self.operator is LogicOperator.NOT and child_count != 1:
            raise ValueError("NOT requires exactly one child")
        if self.operator is LogicOperator.N_OF_M:
            if self.required_count is None:
                raise ValueError("N_OF_M requires required_count")
            if self.required_count < 1 or self.required_count > child_count:
                raise ValueError("N_OF_M required_count is outside child count")
        elif self.required_count is not None:
            raise ValueError("required_count is supported only by N_OF_M")

    @property
    def empty(self) -> bool:
        return not self.conditions and not self.groups


@dataclass(frozen=True, slots=True)
class EntryRule:
    rule_id: str = "NEXT_VALID_SESSION_OPEN"
    delay_sessions: int = 0
    expiry_sessions: int = 5
    retracement_percent: Decimal | None = None
    atr_multiple: Decimal | None = None
    condition_must_remain_valid: bool = False

    def __post_init__(self) -> None:
        if self.delay_sessions < 0:
            raise ValueError("entry delay cannot be negative")
        if self.expiry_sessions < 1:
            raise ValueError("entry expiry must be positive")


@dataclass(frozen=True, slots=True)
class StopRule:
    rule_id: str
    value: Decimal | None = None
    atr_period: int | None = None
    activation_gain_percent: Decimal | None = None


@dataclass(frozen=True, slots=True)
class StopPolicy:
    rules: tuple[StopRule, ...] = ()
    combination: str | None = None

    def __post_init__(self) -> None:
        if len(self.rules) > 1 and self.combination not in {
            "TIGHTER",
            "WIDER",
            "FIRST_TRIGGERED",
            "STAGED",
        }:
            raise ValueError("multiple stops require an explicit combination policy")


@dataclass(frozen=True, slots=True)
class TargetRule:
    rule_id: str
    value: Decimal | None = None
    exit_percent: Decimal = Decimal("100")

    def __post_init__(self) -> None:
        if self.exit_percent <= 0 or self.exit_percent > 100:
            raise ValueError("target exit percent must be in (0, 100]")


@dataclass(frozen=True, slots=True)
class TargetPolicy:
    rules: tuple[TargetRule, ...] = ()
    trailing_rule: StopRule | None = None

    def __post_init__(self) -> None:
        allocated = sum((item.exit_percent for item in self.rules), Decimal("0"))
        if allocated > 100:
            raise ValueError("staged target exits cannot exceed 100 percent")


@dataclass(frozen=True, slots=True)
class ParameterSweep:
    field: str
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.field.strip() or not self.values:
            raise ValueError("parameter sweep requires a field and values")


@dataclass(frozen=True, slots=True)
class ResearchExperimentSpec:
    """Complete deterministic input consumed by the research runner."""

    experiment_id: str
    research_session_id: str
    experiment_name: str
    parent_experiment_id: str | None
    strategy_mode: StrategyMode
    data_start: date
    data_end: date
    universe_definition: str = "POINT_IN_TIME_ELIGIBLE_UNIVERSE"
    base_signal_source: tuple[str, ...] = ()
    entry_conditions: ConditionGroup = field(default_factory=ConditionGroup)
    entry_rule: EntryRule = field(default_factory=EntryRule)
    exit_conditions: ConditionGroup = field(default_factory=ConditionGroup)
    stop_policy: StopPolicy = field(default_factory=StopPolicy)
    target_policy: TargetPolicy = field(default_factory=TargetPolicy)
    maximum_holding_sessions: int | None = 20
    position_sizing_method: str = "EQUAL_WEIGHT"
    initial_capital: Decimal = Decimal("10000000")
    maximum_concurrent_positions: int = 10
    rebalance_rule: str = "ON_ENTRY_EXIT"
    sector_filters: tuple[str, ...] = ()
    regime_filters: tuple[str, ...] = ()
    price_basis: str = "FULLY_ADJUSTED"
    transaction_cost_model: str = "NONE"
    slippage_model: str = "NONE"
    fractional_shares: bool = False
    same_session_policy: SameSessionPolicy = SameSessionPolicy.ASSUME_STOP_FIRST
    parameter_sweeps: tuple[ParameterSweep, ...] = ()
    output_requirements: tuple[str, ...] = ("STANDARD",)
    alpha_signal_source: AlphaSignalSource = (
        AlphaSignalSource.RETROSPECTIVE_FROZEN_ALPHA_REPLAY
    )
    compiler_version: str = LAB_VERSION
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.data_start < date(2016, 1, 1):
            raise ValueError("DSI-011 cannot use pre-2016 data")
        if self.data_end < self.data_start:
            raise ValueError("experiment end cannot precede start")
        if self.initial_capital <= 0:
            raise ValueError("initial capital must be positive")
        if self.maximum_concurrent_positions < 1:
            raise ValueError("maximum positions must be positive")
        if self.maximum_holding_sessions is not None:
            if self.maximum_holding_sessions < 1:
                raise ValueError("holding period must be positive")
        if self.transaction_cost_model != "NONE" or self.slippage_model != "NONE":
            raise ValueError("DSI-011 supports gross, zero-friction research only")
        if self.production_influence:
            raise ValueError("research experiments cannot influence production")
        if (
            self.strategy_mode is not StrategyMode.PURE_TECHNICAL
            and not self.base_signal_source
        ):
            raise ValueError("Alpha-signal and hybrid strategies need signal sources")
        if (
            not self.stop_policy.rules
            and not self.target_policy.rules
            and self.target_policy.trailing_rule is None
            and self.maximum_holding_sessions is None
            and self.exit_conditions.empty
        ):
            raise ValueError("experiment requires at least one exit rule")
        object.__setattr__(
            self,
            "base_signal_source",
            tuple(sorted(set(self.base_signal_source))),
        )
        object.__setattr__(self, "sector_filters", tuple(sorted(self.sector_filters)))
        object.__setattr__(self, "regime_filters", tuple(sorted(self.regime_filters)))

    def as_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(asdict(self)))

    def to_json(self) -> str:
        return json.dumps(
            self.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    @property
    def specification_sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    def with_identity(
        self,
        *,
        experiment_id: str,
        parent_experiment_id: str | None,
    ) -> ResearchExperimentSpec:
        return replace(
            self,
            experiment_id=experiment_id,
            parent_experiment_id=parent_experiment_id,
        )


@dataclass(frozen=True, slots=True)
class CompilationIssue:
    field: str
    message: str
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SpecificationChange:
    field: str
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class CompilationResult:
    status: ExperimentStatus
    normalized_request: str
    intent: str
    specification: ResearchExperimentSpec | None
    changes: tuple[SpecificationChange, ...] = ()
    issues: tuple[CompilationIssue, ...] = ()
    planned_children: int = 0

    @property
    def executable(self) -> bool:
        return (
            self.status is ExperimentStatus.COMPILED and self.specification is not None
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


__all__ = [
    "LAB_VERSION",
    "PRODUCTION_INFLUENCE",
    "AlphaSignalSource",
    "CompilationIssue",
    "CompilationResult",
    "ComparisonOperator",
    "Condition",
    "ConditionGroup",
    "EntryRule",
    "ExperimentStatus",
    "LogicOperator",
    "ParameterSweep",
    "ResearchExperimentSpec",
    "RuleKind",
    "SameSessionPolicy",
    "SpecificationChange",
    "StopPolicy",
    "StopRule",
    "StrategyMode",
    "TargetPolicy",
    "TargetRule",
]
