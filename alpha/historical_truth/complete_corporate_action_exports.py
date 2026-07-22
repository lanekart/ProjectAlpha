"""Deterministic HTR-010B artifact exports."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from alpha.historical_truth.complete_corporate_action_models import (
    CompleteCorporateActionReport,
)


class CompleteCorporateActionArtifactExporter:
    """Write the governed HTR-010B evidence package."""

    def export(
        self, report: CompleteCorporateActionReport, output: Path
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        executive = _executive(report)
        paths = [
            _write_json(output / "htr010b_executive_report.json", executive),
            _write_text(
                output / "htr010b_executive_report.md",
                _executive_markdown(executive),
            ),
        ]
        datasets: tuple[tuple[str, tuple[dict[str, Any], ...]], ...] = (
            ("source_completeness", report.source_completeness),
            ("raw_event_census", report.raw_event_census),
            ("canonical_events", report.canonical_events),
            ("event_lineage", report.event_lineage),
            ("duplicate_groups", report.duplicate_groups),
            ("rejected_events", report.rejected_events),
            ("adjustment_factors", report.adjustment_factors),
            ("cumulative_factors", report.cumulative_factors),
            ("identity_transitions", report.identity_transitions),
            ("price_basis_intervals", report.price_basis_intervals),
            ("adjusted_candle_summary", report.adjusted_candle_summary),
            ("price_continuity", report.price_continuity),
            ("false_signal_contamination", report.false_signal_contamination),
            ("identity_coverage_matrix", report.identity_coverage_matrix),
        )
        for name, rows in datasets:
            paths.append(_write_csv(output / f"htr010b_{name}.csv", rows))
            paths.append(_write_json(output / f"htr010b_{name}.json", list(rows)))
        reports = (
            ("2026_ytd_report", report.ytd_2026, _mapping_markdown),
            (
                "adjusted_replay_readiness",
                report.replay_readiness,
                _readiness_markdown,
            ),
            ("certification", report.certification, _mapping_markdown),
        )
        for name, payload, renderer in reports:
            paths.append(_write_json(output / f"htr010b_{name}.json", payload))
            paths.append(
                _write_text(
                    output / f"htr010b_{name}.md",
                    renderer(name.replace("_", " ").title(), payload),
                )
            )
        return tuple(paths)


def _executive(report: CompleteCorporateActionReport) -> dict[str, Any]:
    actions = Counter(str(row["action_type"]) for row in report.canonical_events)
    factors = Counter(str(row["factor_state"]) for row in report.adjustment_factors)
    basis = Counter(
        str(row["price_basis_state"]) for row in report.adjusted_candle_summary
    )
    continuity = Counter(
        str(row["continuity_state"]) for row in report.price_continuity
    )
    return {
        "contract_version": report.contract_version,
        "adjustment_policy_version": report.adjustment_policy_version,
        "audit_start": report.start_date.isoformat(),
        "audit_end": report.end_date.isoformat(),
        "tier_a_identities": len(report.identity_coverage_matrix),
        "identities_with_events": sum(
            int(row["event_count"]) > 0 for row in report.identity_coverage_matrix
        ),
        "raw_event_records": len(report.raw_event_census),
        "canonical_events": len(report.canonical_events),
        "duplicate_groups": len(report.duplicate_groups),
        "rejected_events": len(report.rejected_events),
        "actions_by_type": dict(sorted(actions.items())),
        "factors_by_state": dict(sorted(factors.items())),
        "price_basis_by_state": dict(sorted(basis.items())),
        "continuity_by_state": dict(sorted(continuity.items())),
        "replay_readiness": report.replay_readiness["state"],
        "raw_candle_fingerprint": report.raw_candle_fingerprint,
        "report_sha256": report.report_sha256,
        "candidate_independent": True,
        "full_benchmark_replays": 0,
        "production_influence": report.production_influence,
    }


def _executive_markdown(payload: dict[str, Any]) -> str:
    return "\n".join(
        (
            "# HTR-010B Complete Tier A Corporate-Action Dataset",
            "",
            f"- Tier A identities: {payload['tier_a_identities']:,}",
            f"- Raw official records: {payload['raw_event_records']:,}",
            f"- Canonical events: {payload['canonical_events']:,}",
            f"- Duplicate groups: {payload['duplicate_groups']:,}",
            f"- Rejected or unresolved evidence: {payload['rejected_events']:,}",
            f"- Replay readiness: {payload['replay_readiness']}",
            f"- Report SHA-256: `{payload['report_sha256']}`",
            "- Full benchmark replays: 0",
            "- Production influence: false",
            "",
            "Raw OHLCV remains immutable. Unknown factors remain unknown and are "
            "quarantined from certified adjusted-price integration.",
            "",
        )
    )


def _readiness_markdown(title: str, payload: dict[str, Any]) -> str:
    blockers = payload.get("blockers") or []
    return "\n".join(
        (
            f"# {title}",
            "",
            f"**Decision:** {payload['state']}",
            "",
            "## Blockers",
            *([f"- {item}" for item in blockers] or ["- None"]),
            "",
            f"Quarantined identities: {payload['quarantined_identity_count']}",
            f"Quarantined intervals: {payload['quarantined_interval_count']}",
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


def _display(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, bool):
        return str(value).lower()
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


__all__ = ["CompleteCorporateActionArtifactExporter"]
