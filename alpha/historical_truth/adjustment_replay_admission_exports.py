"""Deterministic HTR-010B1 and HTR-010B1A artifact exports."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from alpha.historical_truth.adjustment_replay_admission_models import (
    AdjustmentReplayAdmissionReport,
)


class AdjustmentReplayAdmissionArtifactExporter:
    """Write the governed adjustment-validation evidence package."""

    def export(
        self, report: AdjustmentReplayAdmissionReport, output: Path
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        executive = _executive(report)
        paths = [
            _write_json(output / "htr010b1_executive_report.json", executive),
            _write_text(
                output / "htr010b1_executive_report.md",
                _executive_markdown(executive),
            ),
        ]
        datasets: tuple[tuple[str, tuple[dict[str, Any], ...]], ...] = (
            ("quarantine_census", report.quarantine_census),
            ("quarantine_economic_weight", report.quarantine_economic_weight),
            ("factor_validation_cases", report.factor_validation_cases),
            ("factor_validation_results", report.factor_validation_results),
            ("event_boundaries", report.event_boundaries),
            ("multiple_action_cases", report.multiple_action_cases),
            ("series_applicability", report.series_applicability),
            ("unknown_factor_impact", report.unknown_factor_impact),
            ("mixed_basis_resolution", report.mixed_basis_resolution),
            ("adjusted_row_audit", report.adjusted_row_audit),
            ("replay_admission_intervals", report.replay_admission_intervals),
            ("indicator_lookback_safety", report.indicator_lookback_safety),
            ("coverage_matrix", report.coverage_matrix),
            ("rejected_evidence", report.rejected_evidence),
        )
        for name, rows in datasets:
            paths.append(_write_csv(output / f"htr010b1_{name}.csv", rows))
            paths.append(_write_json(output / f"htr010b1_{name}.json", list(rows)))
        reports = (
            (
                "input_contract_diagnostics",
                report.input_contract_diagnostics,
                _mapping_markdown,
            ),
            (
                "population_reconciliation",
                report.population_reconciliation,
                _mapping_markdown,
            ),
            (
                "quarantine_population_reconciliation",
                report.quarantine_population_reconciliation,
                _mapping_markdown,
            ),
            (
                "transformation_contract",
                report.transformation_contract,
                _mapping_markdown,
            ),
            ("replay_readiness", report.replay_readiness, _readiness_markdown),
        )
        for name, payload, renderer in reports:
            paths.append(_write_json(output / f"htr010b1_{name}.json", payload))
            paths.append(
                _write_text(
                    output / f"htr010b1_{name}.md",
                    renderer(name.replace("_", " ").title(), payload),
                )
            )
        return tuple(paths)


def _executive(report: AdjustmentReplayAdmissionReport) -> dict[str, Any]:
    outcomes = Counter(
        str(row["validation_outcome"]) for row in report.factor_validation_results
    )
    admissions = Counter(
        str(row["admission_state"]) for row in report.replay_admission_intervals
    )
    mixed = Counter(
        str(row["resolution_state"]) for row in report.mixed_basis_resolution
    )
    evidence_ids = {_identity(row) for row in report.quarantine_census}
    reconciliation = report.quarantine_population_reconciliation
    readiness = report.replay_readiness
    return {
        "contract_version": report.contract_version,
        "transformation_contract_version": report.transformation_contract_version,
        "audit_start": report.start_date.isoformat(),
        "audit_end": report.end_date.isoformat(),
        "factor_validation_cases": len(report.factor_validation_cases),
        "validation_outcomes": dict(sorted(outcomes.items())),
        "evidence_quarantined_identities": reconciliation.get(
            "evidence_quarantined_identity_count", len(evidence_ids)
        ),
        "admission_quarantined_identities": reconciliation.get(
            "admission_quarantined_identity_count",
            readiness.get("quarantined_identity_count", 0),
        ),
        "unresolved_case_identities": reconciliation.get(
            "unresolved_case_identity_count",
            readiness.get("unresolved_factor_case_count", 0),
        ),
        "quarantined_intervals": len(report.quarantine_census),
        "admission_intervals": len(report.replay_admission_intervals),
        "mixed_basis_resolutions": dict(sorted(mixed.items())),
        "admission_state_counts": dict(sorted(admissions.items())),
        "economic_weight_measurement_state": reconciliation.get(
            "economic_weight_measurement_state", "NOT_REPORTED"
        ),
        "pct_observed_tier_a_rows_quarantined": reconciliation.get(
            "pct_observed_tier_a_rows_quarantined"
        ),
        "pct_observed_tier_a_identity_sessions_quarantined": reconciliation.get(
            "pct_observed_tier_a_identity_sessions_quarantined"
        ),
        "population_window_fully_observed": report.population_reconciliation.get(
            "requested_window_fully_observed"
        ),
        "replay_readiness": readiness["state"],
        "readiness_blockers": readiness.get("blockers", []),
        "report_sha256": report.report_sha256,
        "full_benchmark_replays": 0,
        "candidate_independent": True,
        "production_influence": report.production_influence,
    }


def _executive_markdown(payload: dict[str, Any]) -> str:
    blockers = payload.get("readiness_blockers") or []
    return "\n".join(
        (
            "# HTR-010B1A Admission Contract Integrity Repair",
            "",
            f"- Factor validation cases: {payload['factor_validation_cases']:,}",
            "- Evidence-quarantined identities: "
            f"{payload['evidence_quarantined_identities']:,}",
            "- Admission-quarantined identities: "
            f"{payload['admission_quarantined_identities']:,}",
            f"- Unresolved-case identities: {payload['unresolved_case_identities']:,}",
            f"- Quarantine evidence rows: {payload['quarantined_intervals']:,}",
            f"- Segmented admission intervals: {payload['admission_intervals']:,}",
            f"- Economic-weight state: {payload['economic_weight_measurement_state']}",
            "- Observed Tier A row weight quarantined: "
            f"{_display(payload['pct_observed_tier_a_rows_quarantined'])}",
            "- Observed Tier A identity-session weight quarantined: "
            f"{_display(payload['pct_observed_tier_a_identity_sessions_quarantined'])}",
            f"- Replay readiness: {payload['replay_readiness']}",
            f"- Readiness blockers: {_display(blockers)}",
            f"- Report SHA-256: `{payload['report_sha256']}`",
            "- Full benchmark replays: 0",
            "- Production influence: false",
            "",
            "Raw OHLCV remains immutable. Missing contracts and unknown economic "
            "weights now fail readiness closed.",
            "",
        )
    )


def _readiness_markdown(title: str, payload: dict[str, Any]) -> str:
    blockers = payload.get("blockers") or []
    admission_quarantined = payload.get(
        "admission_quarantined_identity_count",
        payload.get("quarantined_identity_count", 0),
    )
    unresolved = payload.get(
        "unresolved_case_identity_count",
        payload.get("unresolved_factor_case_count", 0),
    )
    silent_mixed = payload.get("silent_mixed_basis_count", 0)
    return "\n".join(
        (
            f"# {title}",
            "",
            f"**Decision:** {payload['state']}",
            "",
            "## Blockers",
            *([f"- {item}" for item in blockers] or ["- None"]),
            "",
            f"Admission-quarantined identities: {admission_quarantined}",
            "Evidence-quarantined identities: "
            f"{payload.get('evidence_quarantined_identity_count', 0)}",
            f"Unresolved-case identities: {unresolved}",
            f"Silent mixed-basis intervals: {silent_mixed}",
            "",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )


def _mapping_markdown(title: str, payload: dict[str, Any]) -> str:
    lines = [f"# {title}", ""]
    lines.extend(
        f"- {key.replace('_', ' ').title()}: {_display(value)}"
        for key, value in sorted(payload.items())
    )
    lines.extend(("", "PRODUCTION_INFLUENCE=false", ""))
    return "\n".join(lines)


def _identity(row: dict[str, Any]) -> str:
    return str(
        row.get("identity_key")
        or row.get("governed_identity_id")
        or row.get("identity_id")
        or ""
    )


def _display(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "UNKNOWN"
    return str(value)


def _write_json(path: Path, payload: Any) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _write_csv(path: Path, rows: tuple[dict[str, Any], ...]) -> Path:
    fields = sorted({key for row in rows for key in row}) or ["value"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})
    return path


def _csv_value(value: Any) -> Any:
    return (
        json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
    )


def _write_text(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


__all__ = ["AdjustmentReplayAdmissionArtifactExporter"]
