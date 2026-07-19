"""Deterministic WDA CSV, Markdown, and manifest exports."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from alpha.warehouse_delta_audit.models import WarehouseDeltaReport
from alpha.warehouse_delta_audit.provenance import manifest_payload
from alpha.warehouse_delta_audit.rendering import (
    render_executive_report,
    render_purchase_justification,
)

DEFAULT_WDA_OUTPUT = Path(".alpha/warehouse_delta/WDA_v1.0")


class WarehouseDeltaExporter:
    """Write the complete immutable WDA evidence bundle."""

    def export(
        self,
        report: WarehouseDeltaReport,
        output_directory: Path | str = DEFAULT_WDA_OUTPUT,
    ) -> tuple[Path, ...]:
        output = Path(output_directory)
        artifacts = {
            "price_delta.csv": _csv(_price_rows(report)),
            "indicator_delta.csv": _csv(_indicator_rows(report)),
            "candidate_delta.csv": _csv(_candidate_rows(report)),
            "decision_delta.csv": _csv(_decision_rows(report)),
            "replay_delta.csv": _csv(_replay_rows(report)),
            "corporate_action_delta.csv": _csv(_corporate_action_rows(report)),
            "purchase_justification.md": render_purchase_justification(report),
            "executive_report.md": render_executive_report(report),
            "manifest.json": json.dumps(
                manifest_payload(report.manifest),
                indent=2,
                sort_keys=True,
            )
            + "\n",
        }
        paths = []
        for name, content in sorted(artifacts.items()):
            destination = output / name
            _write_text(destination, content)
            paths.append(destination)
        return tuple(paths)


def _price_rows(report: WarehouseDeltaReport) -> list[dict[str, object]]:
    return [
        {
            "symbol": item.symbol,
            "matched_observations": item.matched_observations,
            "exact_observations": item.exact_observations,
            "small_difference_observations": item.small_difference_observations,
            "large_difference_observations": item.large_difference_observations,
            "missing_from_comparison": item.missing_from_comparison,
            "missing_from_legacy": item.missing_from_legacy,
            "legacy_duplicates": item.legacy_duplicate_observations,
            "comparison_duplicates": item.comparison_duplicate_observations,
            "legacy_invalid_observations": item.legacy_invalid_observations,
            "comparison_invalid_observations": (item.comparison_invalid_observations),
            "open_changed": item.open_changed,
            "high_changed": item.high_changed,
            "low_changed": item.low_changed,
            "close_changed": item.close_changed,
            "volume_changed": item.volume_changed,
            "maximum_close_relative_delta": _optional(
                item.maximum_close_relative_delta
            ),
            "maximum_volume_relative_delta": _optional(
                item.maximum_volume_relative_delta
            ),
            "manifest_hash": report.manifest.manifest_hash,
        }
        for item in report.price_deltas
    ]


def _indicator_rows(report: WarehouseDeltaReport) -> list[dict[str, object]]:
    return [
        {
            "symbol": item.symbol,
            "indicator": item.indicator,
            "compared_observations": item.compared_observations,
            "identical_observations": item.identical_observations,
            "minor_changes": item.minor_changes,
            "material_changes": item.material_changes,
            "signal_changes": item.signal_changes,
            "maximum_relative_delta": _optional(item.maximum_relative_delta),
            "manifest_hash": report.manifest.manifest_hash,
        }
        for item in report.indicator_deltas
    ]


def _candidate_rows(report: WarehouseDeltaReport) -> list[dict[str, object]]:
    return [
        {
            "symbol": item.symbol,
            "candidate_on_both": item.candidate_on_both,
            "candidate_only_legacy": item.candidate_only_legacy,
            "candidate_only_comparison": item.candidate_only_comparison,
            "timing_shifted": item.timing_shifted,
            "score_shifted": item.score_shifted,
            "average_absolute_score_shift": _optional(
                item.average_absolute_score_shift
            ),
            "maximum_absolute_score_shift": _optional(
                item.maximum_absolute_score_shift
            ),
            "manifest_hash": report.manifest.manifest_hash,
        }
        for item in report.candidate_deltas
    ]


def _decision_rows(report: WarehouseDeltaReport) -> list[dict[str, object]]:
    return [
        {
            "observed_on": item.observed_on.isoformat(),
            "symbol": item.symbol,
            "legacy_score": _optional(item.legacy_score),
            "comparison_score": _optional(item.comparison_score),
            "legacy_approved": _optional(item.legacy_approved),
            "comparison_approved": _optional(item.comparison_approved),
            "legacy_reason": item.legacy_reason,
            "comparison_reason": item.comparison_reason,
            "severity": item.severity.value,
            "explanation": item.explanation,
            "manifest_hash": report.manifest.manifest_hash,
        }
        for item in report.decision_deltas
    ]


def _replay_rows(report: WarehouseDeltaReport) -> list[dict[str, object]]:
    return [
        {
            "metric": item.metric,
            "legacy_value": _optional(item.legacy_value),
            "comparison_value": _optional(item.comparison_value),
            "delta": _optional(item.delta),
            "unit": item.unit,
            "interpretation": item.interpretation,
            "manifest_hash": report.manifest.manifest_hash,
        }
        for item in report.replay_deltas
    ]


def _corporate_action_rows(report: WarehouseDeltaReport) -> list[dict[str, object]]:
    return [
        {
            "event_type": item.event_type,
            "legacy_events": _optional(item.legacy_events),
            "comparison_events": _optional(item.comparison_events),
            "indicator_changing_events": _optional(item.indicator_changing_events),
            "replay_changing_events": _optional(item.replay_changing_events),
            "status": item.status,
            "explanation": item.explanation,
            "manifest_hash": report.manifest.manifest_hash,
        }
        for item in report.corporate_action_deltas
    ]


def _csv(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=tuple(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _optional(value: object | None) -> object:
    return "UNKNOWN" if value is None else value


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


__all__ = ["DEFAULT_WDA_OUTPUT", "WarehouseDeltaExporter"]
