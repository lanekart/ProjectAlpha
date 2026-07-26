"""Typed research-only contracts for DSI-008 performance improvement."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

DSI008_CONTRACT_VERSION = "DSI-008-v1.0.0"
DSI008_RESEARCH_SCOPE = "GOVERNED_PERFORMANCE_IMPROVEMENT_RESEARCH"


class PerformanceImprovementError(ValueError):
    """Raised when a governed DSI-008 contract cannot be satisfied."""


class BenchmarkKind(StrEnum):
    """Governed benchmark return semantics."""

    TOTAL_RETURN = "TOTAL_RETURN"
    NET_TOTAL_RETURN = "NET_TOTAL_RETURN"
    PRICE_INDEX = "PRICE_INDEX"


class ChallengerState(StrEnum):
    """Outcome of one bounded champion-challenger comparison."""

    REJECTED = "CHALLENGER_REJECTED"
    DESCRIPTIVELY_BETTER = "CHALLENGER_DESCRIPTIVELY_BETTER"
    DIRECTIONALLY_STABLE = "CHALLENGER_DIRECTIONALLY_STABLE"
    ROBUSTLY_BETTER = "CHALLENGER_ROBUSTLY_BETTER"
    INSUFFICIENT_SAMPLE = "CHALLENGER_INSUFFICIENT_SAMPLE"
    OVERFIT = "CHALLENGER_OVERFIT"
    HIGH_CONCENTRATION = "CHALLENGER_HIGH_CONCENTRATION"
    INVALID = "CHALLENGER_INVALID"


class RobustnessGrade(StrEnum):
    """Governed interpretation after stress and search controls."""

    ROBUST_NET_WEALTH_IMPROVEMENT = "ROBUST_NET_WEALTH_IMPROVEMENT"
    DIRECTIONALLY_STABLE_IMPROVEMENT = "DIRECTIONALLY_STABLE_IMPROVEMENT"
    ACCURACY_IMPROVED_WEALTH_NOT_IMPROVED = "ACCURACY_IMPROVED_WEALTH_NOT_IMPROVED"
    WEALTH_IMPROVED_ACCURACY_NOT_IMPROVED = "WEALTH_IMPROVED_ACCURACY_NOT_IMPROVED"
    DESCRIPTIVE_ONLY = "DESCRIPTIVE_ONLY"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    HIGH_CONCENTRATION = "HIGH_CONCENTRATION"
    HIGH_PARAMETER_SENSITIVITY = "HIGH_PARAMETER_SENSITIVITY"
    MULTIPLE_TESTING_NOT_SURVIVED = "MULTIPLE_TESTING_NOT_SURVIVED"
    NO_RELIABLE_IMPROVEMENT_FOUND = "NO_RELIABLE_IMPROVEMENT_FOUND"


class FinalReadiness(StrEnum):
    """Final DSI-008 research readiness."""

    FORWARD_PAPER = "READY_FOR_FORWARD_PAPER_STRATEGY_RESEARCH"
    FORWARD_HIGH_CONVICTION = "READY_FOR_FORWARD_HIGH_CONVICTION_SIGNAL_RESEARCH"
    DESCRIPTIVE_ONLY = "READY_FOR_DESCRIPTIVE_MECHANISM_RESEARCH_ONLY"
    NO_RELIABLE_IMPROVEMENT = "READY_WITH_NO_RELIABLE_IMPROVEMENT"
    TRI_UNAVAILABLE = "BLOCKED_BY_TRI_BENCHMARK_UNAVAILABLE"
    ATTRIBUTION_DEFECT = "BLOCKED_BY_PERFORMANCE_ATTRIBUTION_DEFECT"
    CALIBRATION_DEFECT = "BLOCKED_BY_CALIBRATION_DEFECT"
    CHALLENGER_LEAKAGE = "BLOCKED_BY_CHAMPION_CHALLENGER_LEAKAGE"
    HIGH_CONVICTION_SAMPLE = "BLOCKED_BY_INSUFFICIENT_HIGH_CONVICTION_SAMPLE"
    NO_EXCESS_WEALTH = "BLOCKED_BY_NO_BENCHMARK_RELATIVE_WEALTH_IMPROVEMENT"
    ROBUSTNESS = "BLOCKED_BY_MULTIPLE_TESTING_OR_ROBUSTNESS"
    POPULATION = "BLOCKED_BY_POPULATION_RECONCILIATION_DEFECT"
    ARTIFACT = "BLOCKED_BY_ARTIFACT_INTEGRITY_DEFECT"
    IMPLEMENTATION = "BLOCKED_BY_DSI008_IMPLEMENTATION_DEFECT"


@dataclass(frozen=True, slots=True)
class BenchmarkProvenance:
    """Immutable provenance supplied beside an official benchmark series."""

    index_identifier: str
    index_name: str
    benchmark_kind: BenchmarkKind
    source: str
    source_version: str
    currency: str
    dividend_treatment: str
    adjustment_treatment: str
    raw_source_sha256: str
    acquired_at: str

    def __post_init__(self) -> None:
        if not self.index_identifier.strip() or not self.index_name.strip():
            raise PerformanceImprovementError("benchmark identity is required")
        if self.currency != "INR":
            raise PerformanceImprovementError("benchmark currency must be INR")
        if len(self.raw_source_sha256) != 64:
            raise PerformanceImprovementError("benchmark raw source SHA-256 is invalid")


@dataclass(frozen=True, slots=True)
class ChallengerDefinition:
    """One pre-registered, one-factor research challenger."""

    challenger_id: str
    parent_mechanism: str
    changed_field: str
    operator: str
    value: float | str
    unchanged_fields: tuple[str, ...]
    hypothesis: str
    expected_benefit: str
    expected_failure_mode: str
    complexity_cost: int
    training_only_selection_rule: str
    valid_regimes: tuple[str, ...] = ()
    invalid_combinations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.challenger_id.strip():
            raise PerformanceImprovementError("challenger ID is required")
        if self.complexity_cost != 1:
            raise PerformanceImprovementError(
                "DSI-008 registry permits one-factor challengers only"
            )
        if not self.changed_field.strip():
            raise PerformanceImprovementError("challenger changed field is required")


@dataclass(frozen=True, slots=True)
class ImprovementPolicy:
    """Frozen DSI-008 research assumptions."""

    minimum_fold_trades: int = 5
    minimum_elite_completed: int = 30
    minimum_high_conviction_completed: int = 20
    elite_accuracy_target: float = 0.75
    confidence_level: float = 0.95
    maximum_challengers: int = 12
    benchmark_calendar_tolerance: float = 0.02

    def __post_init__(self) -> None:
        if self.minimum_fold_trades < 1:
            raise PerformanceImprovementError("minimum fold trades must be positive")
        if self.minimum_elite_completed < 1:
            raise PerformanceImprovementError("minimum Elite sample must be positive")
        if not 0 < self.elite_accuracy_target < 1:
            raise PerformanceImprovementError("Elite accuracy target must be in (0, 1)")
        if self.maximum_challengers < 1:
            raise PerformanceImprovementError(
                "maximum challenger count must be positive"
            )
        if not 0 <= self.benchmark_calendar_tolerance < 1:
            raise PerformanceImprovementError(
                "benchmark calendar tolerance must be in [0, 1)"
            )


@dataclass(frozen=True, slots=True)
class ImprovementSourcePaths:
    """Caller-selected immutable DSI-008 inputs."""

    dsi007_certificate: Path
    tri_benchmark: Path
    database: Path | None = None
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class PerformanceImprovementResult:
    """Deterministic DSI-008 rows and conclusions."""

    source_commit: str
    readiness: MappingProxyType[str, str]
    blockers: tuple[str, ...]
    rows: MappingProxyType[str, tuple[dict[str, Any], ...]]
    summaries: MappingProxyType[str, Any]
    governance: MappingProxyType[str, bool] = field(
        default_factory=lambda: MappingProxyType({})
    )
