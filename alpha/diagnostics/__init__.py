"""Reusable diagnostics foundation for Project Alpha."""

from .base import DiagnosticEngine
from .exports import export_findings_csv, export_json, export_markdown, render_markdown
from .models import (
    DiagnosticContext,
    DiagnosticResult,
    Finding,
    FindingStatus,
    Recommendation,
    ScoreCard,
    ScoreDimension,
    Severity,
)
from .registry import DiagnosticRegistry, registry
from .scoring import build_scorecard

__all__ = [
    "DiagnosticContext",
    "DiagnosticEngine",
    "DiagnosticRegistry",
    "DiagnosticResult",
    "Finding",
    "FindingStatus",
    "Recommendation",
    "ScoreCard",
    "ScoreDimension",
    "Severity",
    "build_scorecard",
    "export_findings_csv",
    "export_json",
    "export_markdown",
    "registry",
    "render_markdown",
]
