"""Typed value objects for Alpha's TradingView research exporter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path


class ParityClass(StrEnum):
    """Honest reproducibility classification for an Alpha component."""

    EXACT = "EXACT"
    SEMANTICALLY_EQUIVALENT = "SEMANTICALLY_EQUIVALENT"
    APPROXIMATED = "APPROXIMATED"
    UNAVAILABLE_IN_TRADINGVIEW = "UNAVAILABLE_IN_TRADINGVIEW"
    EXCLUDED = "EXCLUDED"


@dataclass(frozen=True, slots=True)
class ComponentParity:
    """Source-to-Pine mapping for one audited Alpha component."""

    component_name: str
    python_source_file: str
    python_symbol_or_class: str
    input_data: tuple[str, ...]
    formula_or_semantics: str
    lookback: str
    warmup_requirement: str
    weight: Decimal | None
    thresholds: tuple[str, ...]
    missing_data_behavior: str
    pine_reproducibility: str
    parity_class: ParityClass
    known_difference: str
    test_method: str

    def as_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible representation."""

        return {
            "component_name": self.component_name,
            "python_source_file": self.python_source_file,
            "python_symbol_or_class": self.python_symbol_or_class,
            "input_data": list(self.input_data),
            "formula_or_semantics": self.formula_or_semantics,
            "lookback": self.lookback,
            "warmup_requirement": self.warmup_requirement,
            "weight": None if self.weight is None else str(self.weight),
            "thresholds": list(self.thresholds),
            "missing_data_behavior": self.missing_data_behavior,
            "pine_reproducibility": self.pine_reproducibility,
            "parity_class": self.parity_class.value,
            "known_difference": self.known_difference,
            "test_method": self.test_method,
        }


@dataclass(frozen=True, slots=True)
class PineExportConfig:
    """Deterministic configuration applied to an exported strategy."""

    strategy: str = "institutional-composite"
    timeframe: str = "D"
    confirmation_timeframe: str = "240"
    setup: str = "ANY_SETUP"
    stop_model: str = "ATR_BUFFERED_SUPPORT"
    target_model: str = "PARTIAL_2R_3R_4R"
    entry_threshold: Decimal = Decimal("85")

    def __post_init__(self) -> None:
        if not self.strategy.strip():
            raise ValueError("strategy cannot be blank")
        if not self.timeframe.strip():
            raise ValueError("timeframe cannot be blank")
        if not self.confirmation_timeframe.strip():
            raise ValueError("confirmation_timeframe cannot be blank")
        timeframe_pattern = re.compile(r"^[A-Za-z0-9]+$")
        if timeframe_pattern.fullmatch(self.timeframe) is None:
            raise ValueError("timeframe contains unsupported Pine characters")
        if timeframe_pattern.fullmatch(self.confirmation_timeframe) is None:
            raise ValueError(
                "confirmation_timeframe contains unsupported Pine characters"
            )
        if self.setup not in {
            "ANY_SETUP",
            "BULL FLAG",
            "EMA PULLBACK",
            "VCP",
            "MOMENTUM CONTINUATION",
        }:
            raise ValueError(f"unsupported setup {self.setup!r}")
        if self.stop_model not in {
            "SUPPORT_BASED",
            "SWING_LOW",
            "ATR_BUFFERED_SUPPORT",
            "MOVING_AVERAGE_INVALIDATION",
            "SETUP_INVALIDATION",
            "FIXED_PERCENT_COMPARATOR",
        }:
            raise ValueError(f"unsupported stop_model {self.stop_model!r}")
        if self.target_model not in {
            "2R",
            "3R",
            "4R_ATR_EXTENSION",
            "PARTIAL_2R_3R_4R",
        }:
            raise ValueError(f"unsupported target_model {self.target_model!r}")
        if not self.entry_threshold.is_finite():
            raise ValueError("entry_threshold must be finite")
        if not Decimal("0") <= self.entry_threshold <= Decimal("100"):
            raise ValueError("entry_threshold must be between 0 and 100")

    def as_dict(self) -> dict[str, str]:
        """Return a stable JSON-compatible representation."""

        return {
            "strategy": self.strategy,
            "timeframe": self.timeframe,
            "confirmation_timeframe": self.confirmation_timeframe,
            "setup": self.setup,
            "stop_model": self.stop_model,
            "target_model": self.target_model,
            "entry_threshold": str(self.entry_threshold),
        }


class ValidationSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True, slots=True)
class PineValidationIssue:
    path: Path
    code: str
    message: str
    severity: ValidationSeverity
    line: int | None = None

    def as_dict(self) -> dict[str, object]:
        """Return a stable machine-readable issue."""

        return {
            "code": self.code,
            "line": self.line,
            "message": self.message,
            "severity": self.severity.value,
        }


@dataclass(frozen=True, slots=True)
class PineSourceMetrics:
    characters: int
    plot_calls: int
    request_calls: int
    table_calls: int
    declared_identifiers: int

    def as_dict(self) -> dict[str, int]:
        return {
            "characters": self.characters,
            "declared_identifiers": self.declared_identifiers,
            "plot_calls": self.plot_calls,
            "request_calls": self.request_calls,
            "table_calls": self.table_calls,
        }


@dataclass(frozen=True, slots=True)
class PineFileValidation:
    path: Path
    issues: tuple[PineValidationIssue, ...]
    metrics: PineSourceMetrics

    def passed(self, *, strict: bool = False) -> bool:
        return not any(
            issue.severity is ValidationSeverity.ERROR
            or (strict and issue.severity is ValidationSeverity.WARNING)
            for issue in self.issues
        )

    def as_dict(self, *, strict: bool = False) -> dict[str, object]:
        return {
            "errors": [
                issue.as_dict()
                for issue in self.issues
                if issue.severity is ValidationSeverity.ERROR
            ],
            "file": str(self.path),
            "metrics": self.metrics.as_dict(),
            "status": "PASS" if self.passed(strict=strict) else "FAIL",
            "warnings": [
                issue.as_dict()
                for issue in self.issues
                if issue.severity is ValidationSeverity.WARNING
            ],
        }


@dataclass(frozen=True, slots=True)
class PineValidationReport:
    files: tuple[PineFileValidation, ...]

    @property
    def files_checked(self) -> int:
        return len(self.files)

    @property
    def issues(self) -> tuple[PineValidationIssue, ...]:
        return tuple(issue for result in self.files for issue in result.issues)

    @property
    def passed(self) -> bool:
        return all(result.passed() for result in self.files)

    @property
    def strict_passed(self) -> bool:
        return all(result.passed(strict=True) for result in self.files)

    def as_dict(self, *, strict: bool = False) -> dict[str, object]:
        return {
            "files": [result.as_dict(strict=strict) for result in self.files],
            "files_checked": self.files_checked,
            "status": (
                "PASS" if (self.strict_passed if strict else self.passed) else "FAIL"
            ),
            "strict": strict,
        }


PRODUCTION_INFLUENCE = False
BROKER_ORDERING = False
AUTONOMOUS_DEPLOYMENT = False
TRADINGVIEW_EXECUTION = False
NO_LOOKAHEAD = True
NO_REPAINTING = True
ALPHA_SOURCE_OF_TRUTH = True
TRADINGVIEW_IS_SECONDARY_VALIDATOR = True
NO_NEW_STRATEGY_LOGIC = True
NO_MANUAL_POST_GENERATION_PATCHING = True
