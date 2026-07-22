"""Deterministic HTR-010A2 artifact export."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from alpha.historical_truth.lifecycle_session_models import LifecycleSessionReport


class LifecycleSessionArtifactExporter:
    """Write the governed lifecycle and session-semantics evidence book."""

    def export(self, report: LifecycleSessionReport, output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        paths = [
            _write_json(output / "htr010a2_executive_report.json", _executive(report)),
            _write_text(output / "htr010a2_executive_report.md", _executive_md(report)),
        ]
        datasets: tuple[tuple[str, Any], ...] = (
            ("certification_state_reconciliation", report.certification_reconciliation),
            ("duplicate_source_records", report.duplicate_source_records),
            ("canonical_observations", report.canonical_observations),
            ("canonical_lifecycle_intervals", report.lifecycle_intervals),
            ("interval_repairs", report.interval_repairs),
            ("remaining_overlaps", report.remaining_overlaps),
            ("remaining_gaps", report.remaining_gaps),
            ("boundary_ranges", report.boundary_ranges),
            ("suspension_source_inventory", report.suspension_source_inventory),
            ("suspension_events", report.suspension_events),
            ("daily_source_semantics", report.daily_source_semantics),
            ("session_expectation_summary", report.session_expectations),
            (
                "missing_session_reclassification",
                report.missing_session_reclassification,
            ),
            ("2026_checkpoint_reconciliation", report.checkpoint_reconciliation_2026),
            ("certification_matrix", report.primary_certifications),
            ("rejected_evidence", report.rejected_evidence),
        )
        for name, records in datasets:
            rows = [_jsonable(item) for item in records]
            paths.append(_write_csv(output / f"htr010a2_{name}.csv", rows))
            paths.append(_write_json(output / f"htr010a2_{name}.json", rows))
        readiness = {
            "readiness": _jsonable(report.readiness),
            "report_sha256": report.report_sha256,
            "canonical_candle_fingerprint": report.canonical_candle_fingerprint,
            "production_influence": report.production_influence,
        }
        paths.extend(
            (
                _write_json(output / "htr010a2_htr010b_readiness.json", readiness),
                _write_text(
                    output / "htr010a2_htr010b_readiness.md",
                    _readiness_md(report),
                ),
            )
        )
        return tuple(paths)


def _executive(report: LifecycleSessionReport) -> dict[str, Any]:
    primary: dict[str, int] = {}
    issues: dict[str, int] = {}
    for row in report.primary_certifications:
        primary[row.primary_state.value] = primary.get(row.primary_state.value, 0) + 1
        for issue in row.issue_flags:
            issues[issue.value] = issues.get(issue.value, 0) + 1
    return {
        "contract_version": report.contract_version,
        "lifecycle_version": report.lifecycle_version,
        "analysis_window": [report.start_date.isoformat(), report.end_date.isoformat()],
        "identity_count": len(report.primary_certifications),
        "primary_state_counts": dict(sorted(primary.items())),
        "issue_flag_counts_non_exclusive": dict(sorted(issues.items())),
        "duplicate_source_records": len(report.duplicate_source_records),
        "canonical_observations": len(report.canonical_observations),
        "canonical_lifecycle_intervals": len(report.lifecycle_intervals),
        "remaining_overlaps": len(report.remaining_overlaps),
        "remaining_gaps": len(report.remaining_gaps),
        "readiness": report.readiness.state.value,
        "full_benchmark_replays": 0,
        "candidate_independent": True,
        "production_influence": report.production_influence,
        "report_sha256": report.report_sha256,
    }


def _executive_md(report: LifecycleSessionReport) -> str:
    executive = _executive(report)
    return "\n".join(
        (
            "# HTR-010A2 Lifecycle and Session Semantics",
            "",
            f"- Identities: {executive['identity_count']:,}",
            f"- Canonical observations: {executive['canonical_observations']:,}",
            "- Classified duplicate source records: "
            f"{executive['duplicate_source_records']:,}",
            "- Canonical lifecycle intervals: "
            f"{executive['canonical_lifecycle_intervals']:,}",
            f"- Remaining overlaps: {executive['remaining_overlaps']:,}",
            f"- Remaining gaps: {executive['remaining_gaps']:,}",
            f"- HTR-010B readiness: {executive['readiness']}",
            "- Full benchmark replays: 0",
            "- Production influence: false",
            "",
            "Primary states are mutually exclusive. Issue flags overlap and must "
            "not be summed.",
            "Daily-file absence is not treated as a source gap where the "
            "activity-row contract does not guarantee a row.",
            "Candles remain observational evidence and do not certify listing "
            "or termination dates.",
            "",
        )
    )


def _readiness_md(report: LifecycleSessionReport) -> str:
    lines = [
        "# HTR-010B Readiness",
        "",
        f"**Decision:** {report.readiness.state.value}",
        "",
        "## Blockers",
        *[f"- {item}" for item in report.readiness.blockers],
        "",
        "## Next milestone",
        report.readiness.recommended_next_milestone,
        "",
        "PRODUCTION_INFLUENCE=false",
        "",
    ]
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_csv(path: Path, rows: list[Any]) -> Path:
    normalized = [row if isinstance(row, dict) else {"value": row} for row in rows]
    fields = sorted({key for row in normalized for key in row}) or ["value"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in normalized:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )
    return path


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


__all__ = ["LifecycleSessionArtifactExporter"]
