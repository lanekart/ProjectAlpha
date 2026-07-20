"""Typed models shared by Project Alpha diagnostic engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Mapping


class Severity(StrEnum):
    """Severity assigned to a diagnostic finding or recommendation."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingStatus(StrEnum):
    """Outcome of an individual diagnostic check."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DiagnosticContext:
    """Immutable execution context supplied to a diagnostic engine."""

    engine_key: str
    as_of: datetime
    output_directory: Path | None = None
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Finding:
    """A deterministic observation produced during validation."""

    check_key: str
    status: FindingStatus
    severity: Severity
    summary: str
    details: str = ""
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoreDimension:
    """One independently reported component of a diagnostic scorecard."""

    key: str
    score: float
    weight: float
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class ScoreCard:
    """Component scores and their transparent weighted aggregate."""

    dimensions: tuple[ScoreDimension, ...]
    weighted_score: float


@dataclass(frozen=True, slots=True)
class Recommendation:
    """A deterministic remediation or follow-up recommendation."""

    key: str
    severity: Severity
    issue: str
    impact: str
    rationale: str
    next_action: str


@dataclass(frozen=True, slots=True)
class DiagnosticResult:
    """Complete output of one governed diagnostic lifecycle."""

    engine_key: str
    engine_version: str
    generated_at: datetime
    classification: str
    discovery: Mapping[str, object]
    findings: tuple[Finding, ...]
    scorecard: ScoreCard
    recommendations: tuple[Recommendation, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)
