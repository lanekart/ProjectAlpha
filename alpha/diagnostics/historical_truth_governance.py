"""Govern historical-truth dataset readiness through the diagnostics framework."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path

from alpha.research_dataset_inventory import DatasetInventoryRow, build_inventory

from .base import DiagnosticEngine
from .models import (
    DiagnosticContext,
    Finding,
    FindingStatus,
    Recommendation,
    ScoreCard,
    ScoreDimension,
    Severity,
)
from .scoring import build_scorecard

_REQUIRED_DIMENSIONS = (
    "coverage",
    "integrity",
    "lineage",
    "replay_readiness",
    "intelligence_readiness",
    "production_readiness",
)


class HistoricalTruthGovernanceEngine(DiagnosticEngine):
    """Assess annual historical-truth readiness without modifying source data."""

    engine_key = "historical-truth-governance"
    engine_version = "1.0.0"

    def discover(self, context: DiagnosticContext) -> Mapping[str, object]:
        year = _required_int(context.parameters, "year")
        database = _required_path(context.parameters, "database")
        snapshots = _optional_path(context.parameters, "snapshots")
        as_of = _optional_date(context.parameters, "as_of")
        rows = build_inventory(
            year=year,
            database=database,
            snapshots=snapshots,
            as_of=as_of,
        )
        return {
            "year": year,
            "database": database,
            "snapshots": snapshots,
            "as_of": as_of,
            "rows": rows,
        }

    def validate(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
    ) -> tuple[Finding, ...]:
        del context
        rows = _inventory_rows(discovery)
        findings: list[Finding] = []
        for row in rows:
            status = FindingStatus.PASS if row.certification_ready else FindingStatus.FAIL
            if not row.required and not row.certification_ready:
                status = FindingStatus.WARNING
            severity = _severity(row)
            findings.append(
                Finding(
                    check_key=row.dataset_key,
                    status=status,
                    severity=severity,
                    summary=f"{row.dataset_name}: {row.status}",
                    details=row.limitation,
                    evidence={
                        "required": row.required,
                        "blocking": row.blocking,
                        "row_count": row.row_count,
                        "coverage_percent": row.coverage_percent,
                        "matched_tables": row.matched_tables,
                        "matched_files": row.matched_files,
                    },
                )
            )
        return tuple(findings)

    def score(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
        findings: tuple[Finding, ...],
    ) -> ScoreCard:
        del context, findings
        rows = _inventory_rows(discovery)
        required = tuple(row for row in rows if row.required)
        blocking = tuple(row for row in required if row.blocking)
        optional = tuple(row for row in rows if not row.required)

        coverage = _ready_percent(required)
        integrity = _non_empty_percent(required)
        lineage = _keys_ready_percent(
            rows,
            ("security_identity", "listing_history", "delisting_history"),
        )
        replay = _ready_percent(blocking)
        intelligence = _ready_percent(required + optional)
        production = min(coverage, integrity, lineage, replay)

        dimensions = (
            ScoreDimension("coverage", coverage, 0.20, "Required datasets ready."),
            ScoreDimension(
                "integrity",
                integrity,
                0.20,
                "Required datasets are present and non-empty.",
            ),
            ScoreDimension(
                "lineage",
                lineage,
                0.15,
                "Identity, listing and delisting history readiness.",
            ),
            ScoreDimension(
                "replay_readiness",
                replay,
                0.20,
                "Blocking replay dependencies ready.",
            ),
            ScoreDimension(
                "intelligence_readiness",
                intelligence,
                0.10,
                "Required and optional intelligence datasets ready.",
            ),
            ScoreDimension(
                "production_readiness",
                production,
                0.15,
                "Conservative minimum of core readiness dimensions.",
            ),
        )
        assert tuple(item.key for item in dimensions) == _REQUIRED_DIMENSIONS
        return build_scorecard(dimensions)

    def classify(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
        findings: tuple[Finding, ...],
        scorecard: ScoreCard,
    ) -> str:
        del context, discovery
        has_blocker = any(
            finding.status is FindingStatus.FAIL
            and finding.severity is Severity.CRITICAL
            for finding in findings
        )
        if has_blocker:
            return "NOT_CERTIFIED"
        if scorecard.weighted_score < 100.0:
            return "CONDITIONALLY_CERTIFIED"
        return "CERTIFIED"

    def recommend(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
        findings: tuple[Finding, ...],
        scorecard: ScoreCard,
        classification: str,
    ) -> tuple[Recommendation, ...]:
        del context, discovery, scorecard, classification
        recommendations = [
            Recommendation(
                key=f"remediate-{finding.check_key}",
                severity=finding.severity,
                issue=finding.summary,
                impact=_impact(finding.severity),
                rationale=finding.details,
                next_action=_next_action(finding.check_key),
            )
            for finding in findings
            if finding.status is not FindingStatus.PASS
        ]
        return tuple(sorted(recommendations, key=_recommendation_sort_key))

    def metadata(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
        findings: tuple[Finding, ...],
        scorecard: ScoreCard,
    ) -> Mapping[str, object]:
        del context, scorecard
        rows = _inventory_rows(discovery)
        return {
            "diagnostic_only": True,
            "production_influence": False,
            "dataset_count": len(rows),
            "blocking_issue_count": sum(
                finding.status is FindingStatus.FAIL
                and finding.severity is Severity.CRITICAL
                for finding in findings
            ),
        }


def _required_int(parameters: Mapping[str, object], key: str) -> int:
    value = parameters.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _required_path(parameters: Mapping[str, object], key: str) -> Path:
    value = parameters.get(key)
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value)
    raise ValueError(f"{key} must be a path")


def _optional_path(parameters: Mapping[str, object], key: str) -> Path | None:
    value = parameters.get(key)
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value)
    raise ValueError(f"{key} must be a path or None")


def _optional_date(parameters: Mapping[str, object], key: str) -> date | None:
    value = parameters.get(key)
    if value is None:
        return None
    if isinstance(value, date):
        return value
    raise ValueError(f"{key} must be a date or None")


def _inventory_rows(discovery: Mapping[str, object]) -> tuple[DatasetInventoryRow, ...]:
    value = discovery.get("rows")
    if not isinstance(value, tuple) or not all(
        isinstance(row, DatasetInventoryRow) for row in value
    ):
        raise TypeError("discovery rows must contain DatasetInventoryRow values")
    return value


def _severity(row: DatasetInventoryRow) -> Severity:
    if row.blocking and not row.certification_ready:
        return Severity.CRITICAL
    if row.required and not row.certification_ready:
        return Severity.HIGH
    if not row.certification_ready:
        return Severity.MEDIUM
    return Severity.INFO


def _ready_percent(rows: tuple[DatasetInventoryRow, ...]) -> float:
    if not rows:
        return 0.0
    ready = sum(row.certification_ready for row in rows)
    return round(ready / len(rows) * 100.0, 2)


def _non_empty_percent(rows: tuple[DatasetInventoryRow, ...]) -> float:
    if not rows:
        return 0.0
    non_empty = sum(row.status not in {"MISSING", "PRESENT_EMPTY"} for row in rows)
    return round(non_empty / len(rows) * 100.0, 2)


def _keys_ready_percent(
    rows: tuple[DatasetInventoryRow, ...],
    keys: tuple[str, ...],
) -> float:
    selected = tuple(row for row in rows if row.dataset_key in keys)
    return _ready_percent(selected)


def _impact(severity: Severity) -> str:
    if severity is Severity.CRITICAL:
        return "Blocks annual historical-truth certification and reliable replay."
    if severity is Severity.HIGH:
        return "Reduces survivorship, lineage or attribution reliability."
    return "Reduces intelligence depth but does not independently block replay."


def _next_action(dataset_key: str) -> str:
    actions = {
        "corporate_actions": "Acquire and validate official 2026 corporate actions.",
        "security_identity": "Canonicalize the recovered security master.",
        "listing_history": "Canonicalize and validate listing history.",
        "delisting_history": "Acquire official delisting and suspension evidence.",
        "trading_calendar": "Load the official exchange trading calendar.",
        "benchmark_history": "Acquire and validate official benchmark history.",
        "sector_mapping": "Normalize the recovered sector-history schema.",
        "index_constituents": "Normalize index-membership history.",
    }
    return actions.get(dataset_key, f"Validate and canonicalize {dataset_key}.")


def _recommendation_sort_key(
    recommendation: Recommendation,
) -> tuple[int, str]:
    order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
        Severity.INFO: 4,
    }
    return order[recommendation.severity], recommendation.key
