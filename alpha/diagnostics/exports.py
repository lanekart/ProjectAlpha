"""Deterministic JSON, CSV and Markdown exports for diagnostic results."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from .models import DiagnosticResult


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError(f"unsupported export value: {type(value).__name__}")


def export_json(result: DiagnosticResult, path: Path) -> Path:
    """Write the complete result as stable, sorted JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(result), indent=2, sort_keys=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )
    return path


def export_findings_csv(result: DiagnosticResult, path: Path) -> Path:
    """Write one row per finding using deterministic column order."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["check_key", "status", "severity", "summary", "details", "evidence"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for finding in result.findings:
            writer.writerow(
                {
                    "check_key": finding.check_key,
                    "status": finding.status.value,
                    "severity": finding.severity.value,
                    "summary": finding.summary,
                    "details": finding.details,
                    "evidence": json.dumps(
                        dict(finding.evidence), sort_keys=True, default=_json_default
                    ),
                }
            )
    return path


def render_markdown(result: DiagnosticResult) -> str:
    """Render a compact human-readable report."""

    lines = [
        f"# Diagnostic Report: {result.engine_key}",
        "",
        f"- Version: `{result.engine_version}`",
        f"- Generated: `{result.generated_at.isoformat()}`",
        f"- Classification: **{result.classification}**",
        f"- Weighted score: **{result.scorecard.weighted_score:.2f}**",
        "",
        "## Scorecard",
        "",
        "| Dimension | Score | Weight | Rationale |",
        "|---|---:|---:|---|",
    ]
    for dimension in result.scorecard.dimensions:
        lines.append(
            f"| {dimension.key} | {dimension.score:.2f} | "
            f"{dimension.weight:.2f} | {dimension.rationale} |"
        )

    lines.extend(["", "## Findings", ""])
    if result.findings:
        for finding in result.findings:
            lines.append(
                f"- **{finding.severity.value} / {finding.status.value}** "
                f"`{finding.check_key}` — {finding.summary}"
            )
    else:
        lines.append("- No findings.")

    lines.extend(["", "## Recommendations", ""])
    if result.recommendations:
        for recommendation in result.recommendations:
            lines.append(
                f"- **{recommendation.severity.value}** "
                f"`{recommendation.key}` — {recommendation.next_action}"
            )
    else:
        lines.append("- No recommendations.")

    return "\n".join(lines) + "\n"


def export_markdown(result: DiagnosticResult, path: Path) -> Path:
    """Write the human-readable Markdown report."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(result), encoding="utf-8")
    return path
