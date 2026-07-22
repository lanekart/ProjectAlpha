"""Deterministic HTR-010A3 artifact export."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from alpha.historical_truth.foundation_readiness_models import (
    FoundationReadinessReport,
)


class FoundationReadinessArtifactExporter:
    """Write the 26 governed HTR-010A3 artifacts."""

    def export(
        self, report: FoundationReadinessReport, output: Path
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        paths = [
            _write_json(output / "htr010a3_executive_report.json", _executive(report)),
            _write_text(output / "htr010a3_executive_report.md", _executive_md(report)),
        ]
        datasets: tuple[tuple[str, Any], ...] = (
            ("tier_a_conflict_cases", report.conflict_cases),
            ("conflict_evidence", report.conflict_evidence),
            ("conflict_resolutions", report.conflict_resolutions),
            ("tier_a_gap_resolutions", report.gap_resolutions),
            ("2026_discrepancies", report.discrepancies_2026),
            ("tier_a_termination_boundaries", report.termination_boundaries),
            ("suspension_evidence_ceiling", report.suspension_ceiling),
            ("daily_source_contract", report.daily_source_contracts),
            ("corporate_action_join_readiness", report.join_readiness),
            ("quarantined_identities", report.quarantined_identities),
            ("rejected_evidence", report.rejected_evidence),
        )
        for name, records in datasets:
            rows = [_jsonable(item) for item in records]
            paths.append(_write_csv(output / f"htr010a3_{name}.csv", rows))
            paths.append(_write_json(output / f"htr010a3_{name}.json", rows))
        readiness = {
            "readiness": _jsonable(report.readiness),
            "canonical_candle_fingerprint": report.canonical_candle_fingerprint,
            "report_sha256": report.report_sha256,
            "production_influence": report.production_influence,
        }
        paths.extend(
            (
                _write_json(output / "htr010a3_readiness.json", readiness),
                _write_text(output / "htr010a3_readiness.md", _readiness_md(report)),
            )
        )
        return tuple(paths)


def _executive(report: FoundationReadinessReport) -> dict[str, Any]:
    outcomes: dict[str, int] = {}
    joins: dict[str, int] = {}
    for resolution in report.conflict_resolutions:
        outcomes[resolution.outcome.value] = (
            outcomes.get(resolution.outcome.value, 0) + 1
        )
    for readiness in report.join_readiness:
        joins[readiness.state.value] = joins.get(readiness.state.value, 0) + 1
    return {
        "contract_version": report.contract_version,
        "tier_a_conflict_cases": len(report.conflict_cases),
        "conflict_outcomes": dict(sorted(outcomes.items())),
        "blocking_conflicts": sum(row.blocking for row in report.conflict_resolutions),
        "tier_a_gap_resolutions": len(report.gap_resolutions),
        "discrepancies_2026": len(report.discrepancies_2026),
        "join_readiness": dict(sorted(joins.items())),
        "termination_boundaries": len(report.termination_boundaries),
        "readiness": report.readiness.state.value,
        "full_benchmark_replays": 0,
        "candidate_independent": True,
        "production_influence": report.production_influence,
        "report_sha256": report.report_sha256,
    }


def _executive_md(report: FoundationReadinessReport) -> str:
    data = _executive(report)
    return "\n".join(
        (
            "# HTR-010A3 Tier A Historical Foundation Readiness",
            "",
            f"- Tier A conflict case files: {data['tier_a_conflict_cases']}",
            f"- Blocking identity conflicts: {data['blocking_conflicts']}",
            f"- Tier A lifecycle gaps classified: {data['tier_a_gap_resolutions']}",
            f"- 2026 discrepancies treated: {data['discrepancies_2026']}",
            f"- Corporate-action join population: {len(report.join_readiness)}",
            f"- Readiness: {data['readiness']}",
            "- Full benchmark replays: 0",
            "- Production influence: false",
            "",
            "Same-ISIN parallel series are non-blocking because series remains in "
            "the source-row key. Bounded membership and partial tradability remain "
            "explicit rather than being promoted to exact historical facts.",
            "",
        )
    )


def _readiness_md(report: FoundationReadinessReport) -> str:
    return "\n".join(
        (
            "# HTR-010A3 Readiness",
            "",
            f"**Decision:** {report.readiness.state.value}",
            "",
            "## Blockers",
            *([f"- {item}" for item in report.readiness.blockers] or ["- None"]),
            "",
            "## Quarantine policy",
            report.readiness.quarantine_policy,
            "",
            "## Next milestone",
            report.readiness.recommended_next_milestone,
            "",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )


def _write_json(path: Path, payload: Any) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
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


__all__ = ["FoundationReadinessArtifactExporter"]
