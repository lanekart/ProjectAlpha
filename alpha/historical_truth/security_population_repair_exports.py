"""Deterministic artifact export for HTR-010A1."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, cast

from alpha.historical_truth.security_population_repair_models import (
    SecurityPopulationRepairReport,
)


class SecurityPopulationRepairArtifactExporter:
    """Write the complete governed HTR-010A1 evidence book."""

    def export(
        self,
        report: SecurityPopulationRepairReport,
        output: Path,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        executive = _executive_payload(report)
        paths.extend(
            (
                _write_json(output / "htr010a1_executive_report.json", executive),
                _write_text(
                    output / "htr010a1_executive_report.md",
                    _executive_markdown(report),
                ),
            )
        )
        datasets: tuple[tuple[str, Any], ...] = (
            ("instrument_taxonomy", report.taxonomy),
            ("support_policy", report.support_policy),
            ("census_reconciliation", report.census_reconciliation),
            ("identity_denominator_audit", report.denominator_audit),
            ("interval_overlaps", report.interval_overlaps),
            ("interval_repairs", report.interval_repairs),
            ("interval_gaps", report.interval_gaps),
            ("symbol_reuse", report.symbol_reuse),
            ("listing_boundaries", report.listing_boundaries),
            ("termination_boundaries", report.termination_boundaries),
            ("suspension_evidence", report.suspension_evidence),
            ("checkpoint_reconciliation", report.checkpoint_reconciliation),
            ("2026_universe_reconciliation", report.universe_2026),
            ("candle_reconciliation", report.candle_reconciliation),
            ("security_session_continuity", report.continuity),
            ("certification_matrix", report.certification_matrix),
            ("rejected_evidence", report.rejected_evidence),
        )
        for name, records in datasets:
            normalized = [_jsonable(item) for item in records]
            paths.append(_write_csv(output / f"htr010a1_{name}.csv", normalized))
            paths.append(_write_json(output / f"htr010a1_{name}.json", normalized))
        paths.extend(
            (
                _write_json(
                    output / "htr010a1_certification.json",
                    {
                        "certification": _jsonable(report.certification),
                        "denominators": _jsonable(report.denominator_summary),
                        "report_sha256": report.report_sha256,
                        "production_influence": report.production_influence,
                    },
                ),
                _write_text(
                    output / "htr010a1_certification.md",
                    _certification_markdown(report),
                ),
            )
        )
        return tuple(paths)


def _executive_payload(report: SecurityPopulationRepairReport) -> dict[str, Any]:
    return {
        "contract_version": report.contract_version,
        "support_policy_version": report.support_policy_version,
        "analysis_window": {
            "start": report.start_date.isoformat(),
            "end": report.end_date.isoformat(),
        },
        "population": _jsonable(report.population_summary),
        "repair": _jsonable(report.repair_summary),
        "denominators": _jsonable(report.denominator_summary),
        "certification": _jsonable(report.certification),
        "audit_answers": _audit_answers(report),
        "candidate_independent": True,
        "full_benchmark_replays_run": 0,
        "production_influence": report.production_influence,
        "report_sha256": report.report_sha256,
    }


def _audit_answers(report: SecurityPopulationRepairReport) -> list[dict[str, str]]:
    population = report.population_summary
    repair = report.repair_summary
    tier_a = next(
        (
            item
            for item in report.denominator_summary
            if item.support_state.value == "TIER_A_CORE_EQUITY"
        ),
        None,
    )
    active = next(
        (
            item
            for item in report.universe_2026
            if item.support_state.value == "TIER_A_CORE_EQUITY"
        ),
        None,
    )
    return [
        {
            "question": "Why did the census increase from 6,334 to 15,428 symbols?",
            "answer": (
                "HTR-010A added official full-market masters containing debt, funds, "
                "government securities, temporary series and master-only records; "
                "HTR-008 was narrower."
            ),
        },
        {
            "question": "What were the unsupported security types?",
            "answer": (
                "They are preserved non-equity or administrative classifications, "
                f"now separated as {population.preserved_unsupported_identities:,} "
                "identities."
            ),
        },
        {
            "question": "Is the 16,074 identity count inflated?",
            "answer": (
                f"The census contains {population.corrected_identities:,} stable keys "
                f"and {population.duplicate_identity_records:,} repeated "
                "identity-series records. The identity count is a census count, not "
                "an equity denominator."
            ),
        },
        {
            "question": "Why were interval overlaps created?",
            "answer": (
                f"All {repair.overlaps_classified:,} flagged identities are "
                "attributed; current-master backfill and parallel series are "
                "separated from unresolved conflicts."
            ),
        },
        {
            "question": "Is the previous unresolved denominator valid?",
            "answer": (
                "No. It mixed unsupported records and projected checkpoint evidence. "
                "The primary denominator now contains only explicitly supported, "
                "bounded intervals."
            ),
        },
        {
            "question": "What is the Tier A denominator?",
            "answer": (
                f"{tier_a.expected_identity_days if tier_a else 0:,} expected "
                "identity-sessions, with certified, provisional and unresolved "
                "totals reported separately."
            ),
        },
        {
            "question": "What is the corrected 2026 active equity universe?",
            "answer": (
                f"{active.active_identities if active else 0:,} Tier A identities "
                "are supported at the requested cutoff; unsupported and provisional "
                "populations are separate."
            ),
        },
        {
            "question": "Is the foundation ready for HTR-010B?",
            "answer": report.certification.readiness_decision,
        },
    ]


def _executive_markdown(report: SecurityPopulationRepairReport) -> str:
    population = report.population_summary
    repair = report.repair_summary
    lines = [
        "# HTR-010A1 Executive Report",
        "",
        f"Analysis window: {report.start_date} to {report.end_date}",
        f"Support policy: `{report.support_policy_version}`",
        "",
        "## Population",
        "",
        f"- HTR-008 raw symbols: {population.htr008_raw_symbols:,}",
        f"- HTR-010A raw symbols: {population.htr010a_raw_symbols:,}",
        f"- Corrected identities: {population.corrected_identities:,}",
        f"- Tier A core equity: {population.tier_a_identities:,}",
        f"- Supported non-core equity: {population.supported_non_core_identities:,}",
        "- Separate supported asset classes: "
        f"{population.separate_asset_class_identities:,}",
        f"- Preserved unsupported: {population.preserved_unsupported_identities:,}",
        f"- Unknown classification: {population.unknown_classification_identities:,}",
        "- Conflicting classification: "
        f"{population.conflicting_classification_identities:,}",
        "",
        "## Interval Repair",
        "",
        f"- Overlaps classified: {repair.overlaps_classified:,}",
        f"- Duplicate overlaps repaired: {repair.duplicate_overlaps_repaired:,}",
        f"- Legitimate overlaps retained: {repair.legitimate_overlaps_retained:,}",
        f"- Unresolved overlaps: {repair.unresolved_overlaps:,}",
        f"- Gaps classified: {repair.gaps_classified:,}",
        f"- Unresolved gaps: {repair.unresolved_gaps:,}",
        "",
        "## Required Audit Answers",
        "",
    ]
    for index, item in enumerate(_audit_answers(report), 1):
        lines.extend((f"### {index}. {item['question']}", "", item["answer"], ""))
    lines.extend(
        (
            "## Governance",
            "",
            "- Candidate-based filtering: false",
            "- Full benchmark replays run: 0",
            "- Canonical candle mutation: false",
            "- Production influence: false",
            f"- Report SHA-256: `{report.report_sha256}`",
        )
    )
    return "\n".join(lines) + "\n"


def _certification_markdown(report: SecurityPopulationRepairReport) -> str:
    certification = report.certification
    lines = [
        "# HTR-010A1 Certification",
        "",
        f"Primary state: **{certification.primary_state}**",
        f"Readiness decision: **{certification.readiness_decision}**",
        "",
        certification.rationale,
        "",
        "## Secondary Blockers",
        "",
    ]
    lines.extend(f"- {item}" for item in certification.secondary_blockers)
    if not certification.secondary_blockers:
        lines.append("- None")
    lines.extend(("", "`PRODUCTION_INFLUENCE=false`", ""))
    return "\n".join(lines)


def _write_json(path: Path, value: Any) -> Path:
    path.write_text(
        json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_csv(path: Path, records: list[Any]) -> Path:
    normalized = [item for item in records if isinstance(item, dict)]
    fields = sorted({key for row in normalized for key in row})
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if fields:
            writer.writeheader()
            for row in normalized:
                writer.writerow({key: _csv_value(row.get(key)) for key in fields})
    return path


def _write_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(cast(Any, value)))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


__all__ = ["SecurityPopulationRepairArtifactExporter"]
