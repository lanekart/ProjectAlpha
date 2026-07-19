from __future__ import annotations

import csv
import json
import os
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile

from alpha.benchmark_replay.provenance import file_hash
from alpha.gate_dependency_audit.models import (
    DEFAULT_OUTPUT,
    CandidateGateLineage,
    GateDependencyAuditReport,
)
from alpha.gate_dependency_audit.rendering import render_executive_report

DEFAULT_GATE_DEPENDENCY_OUTPUT = Path(DEFAULT_OUTPUT)


class GateDependencyAuditExporter:
    """Write deterministic GDSBA evidence and its checksum manifest."""

    def export(
        self,
        report: GateDependencyAuditReport,
        *,
        output_directory: Path | str = DEFAULT_GATE_DEPENDENCY_OUTPUT,
    ) -> tuple[Path, ...]:
        output = Path(output_directory)
        self._assert_compatible(output, report)
        output.mkdir(parents=True, exist_ok=True)
        paths = [
            _write_csv(
                output / "gate_lineage.csv",
                tuple(
                    row
                    for candidate in report.lineages
                    for row in _lineage_rows(candidate)
                ),
            ),
            _write_csv(output / "first_failure.csv", report.first_failures),
            _write_csv(output / "gate_survival.csv", report.survival),
            _write_csv(output / "dependency_matrix.csv", report.dependencies),
            _write_csv(output / "interaction_matrix.csv", report.interactions),
            _write_csv(output / "marginal_value.csv", report.marginal_values),
            _write_csv(
                output / "false_rejection_paths.csv",
                report.false_rejection_paths,
            ),
            _write_csv(
                output / "correct_rejection_paths.csv",
                report.correct_rejection_paths,
            ),
            _write_csv(output / "gate_report_card.csv", report.report_cards),
            _write_csv(output / "gate_order.csv", (report.gate_order,)),
            _write_text(
                output / "executive_report.md",
                render_executive_report(report),
            ),
        ]
        artifact_hashes = {path.name: file_hash(path) for path in sorted(paths)}
        manifest = replace(report.manifest, artifact_hashes=artifact_hashes)
        paths.append(
            _write_text(
                output / "manifest.json",
                json.dumps(_json_value(manifest), indent=2, sort_keys=True) + "\n",
            )
        )
        return tuple(paths)

    @staticmethod
    def _assert_compatible(
        output: Path,
        report: GateDependencyAuditReport,
    ) -> None:
        path = output / "manifest.json"
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("igta_manifest_hash") != report.manifest.igta_manifest_hash
            or payload.get("gate_sequence_hash") != report.manifest.gate_sequence_hash
        ):
            raise ValueError(
                "immutable GDSBA output already exists for different evidence"
            )


def load_gate_dependency_manifest(
    output_directory: Path | str = DEFAULT_GATE_DEPENDENCY_OUTPUT,
) -> dict[str, object]:
    path = Path(output_directory) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(
            "GDSBA manifest unavailable; run alpha gate-dependency audit"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("production_influence") is not False
    ):
        raise ValueError("invalid GDSBA manifest")
    return {str(key): value for key, value in payload.items()}


def _lineage_rows(item: CandidateGateLineage) -> tuple[dict[str, object], ...]:
    common: dict[str, object] = {
        "candidate_id": item.candidate_id,
        "observed_on": item.observed_on,
        "symbol": item.symbol,
        "final_signal": item.final_signal,
        "candidate_score": item.candidate_score,
        "outcome_classification": item.outcome_classification,
        "planned_net_return_percent": item.planned_net_return_percent,
        "planned_realized_r": item.planned_realized_r,
        "first_failed_gate": item.first_failed_gate,
        "first_failed_group": item.first_failed_group,
        "failed_gates": item.failed_gates,
        "failed_groups": item.failed_groups,
    }
    return tuple(
        {
            **common,
            "gate_id": step.gate_id,
            "display_name": step.display_name,
            "gate_group": step.gate_group,
            "sequence": step.sequence,
            "observed_status": step.observed_status,
            "sequential_status": step.sequential_status,
            "failure_codes": step.failure_codes,
            "failure_explanations": step.failure_explanations,
            "first_failure": step.first_failure,
        }
        for step in item.lineage
    )


def _write_csv(path: Path, rows: tuple[object, ...]) -> Path:
    normalized = tuple(_row(item) for item in rows)
    fieldnames = tuple(normalized[0]) if normalized else ()
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    if fieldnames:
        writer.writeheader()
        writer.writerows(normalized)
    return _write_text(path, stream.getvalue())


def _row(value: object) -> dict[str, object]:
    if is_dataclass(value) and not isinstance(value, type):
        raw = {item.name: getattr(value, item.name) for item in fields(value)}
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise TypeError("GDSBA CSV rows must be dataclasses or mappings")
    return {str(key): _csv_value(item) for key, item in raw.items()}


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, Decimal)):
        return str(value)
    if isinstance(value, Mapping):
        return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))
    if isinstance(value, (tuple, list)):
        return "|".join(str(_csv_value(item)) for item in value)
    return value


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(
            {item.name: getattr(value, item.name) for item in fields(value)}
        )
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, Decimal, Path)):
        return str(value)
    return value


def _write_text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


__all__ = [
    "DEFAULT_GATE_DEPENDENCY_OUTPUT",
    "GateDependencyAuditExporter",
    "load_gate_dependency_manifest",
]
