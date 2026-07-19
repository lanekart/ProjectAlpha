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
from typing import Any

from alpha.benchmark_replay.provenance import file_hash
from alpha.institutional_gate_truth.models import (
    DEFAULT_OUTPUT,
    InstitutionalGateTruthReport,
    RejectionAssessment,
    RejectionClassification,
)
from alpha.institutional_gate_truth.rendering import render_executive_report

DEFAULT_GATE_OUTPUT = Path(DEFAULT_OUTPUT)


class InstitutionalGateTruthExporter:
    """Write deterministic IGTA evidence and a checksum manifest."""

    def export(
        self,
        report: InstitutionalGateTruthReport,
        *,
        output_directory: Path | str = DEFAULT_GATE_OUTPUT,
    ) -> tuple[Path, ...]:
        output = Path(output_directory)
        self._assert_compatible(output, report)
        output.mkdir(parents=True, exist_ok=True)
        paths = [
            _write_csv(
                output / "rejected_population.csv",
                tuple(_population_row(item) for item in report.assessments),
            ),
            _write_csv(
                output / "rejection_classification.csv",
                tuple(_classification_row(item) for item in report.assessments),
            ),
            _write_csv(output / "gate_effectiveness.csv", (report.effectiveness,)),
            _write_csv(output / "reason_statistics.csv", report.reason_statistics),
            _write_csv(
                output / "counterfactual_portfolio.csv",
                report.counterfactual_curve,
            ),
            _write_csv(
                output / "counterfactual_trades.csv",
                report.counterfactual_trades,
            ),
            _write_csv(
                output / "counterfactual_statistics.csv",
                (report.counterfactual_statistics,),
            ),
            _write_csv(
                output / "component_attribution.csv",
                report.component_attribution,
            ),
            _write_csv(
                output / "false_rejections.csv",
                tuple(
                    _classification_row(item)
                    for item in report.assessments
                    if item.classification is RejectionClassification.FALSE_REJECTION
                ),
                headers=tuple(_classification_row(report.assessments[0])),
            ),
            _write_text(
                output / "executive_report.md",
                render_executive_report(report),
            ),
        ]
        artifact_hashes = {path.name: file_hash(path) for path in sorted(paths)}
        manifest = replace(report.manifest, artifact_hashes=artifact_hashes)
        manifest_path = _write_text(
            output / "manifest.json",
            json.dumps(_json_value(manifest), indent=2, sort_keys=True) + "\n",
        )
        paths.append(manifest_path)
        return tuple(paths)

    @staticmethod
    def _assert_compatible(
        output: Path,
        report: InstitutionalGateTruthReport,
    ) -> None:
        path = output / "manifest.json"
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("baseline_manifest_hash") != (
            report.manifest.baseline_manifest_hash
        ):
            raise ValueError(
                "immutable IGTA output already exists for different baseline evidence"
            )


def load_gate_manifest(
    output_directory: Path | str = DEFAULT_GATE_OUTPUT,
) -> dict[str, Any]:
    path = Path(output_directory) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError("IGTA manifest unavailable; run alpha gate audit")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("production_influence") is not False
    ):
        raise ValueError("invalid IGTA manifest")
    return {str(key): value for key, value in payload.items()}


def _population_row(item: RejectionAssessment) -> dict[str, object]:
    candidate = item.candidate
    return {
        "candidate_id": candidate.candidate_id,
        "observed_on": candidate.observed_on,
        "symbol": candidate.symbol,
        "final_signal": candidate.final_signal,
        "candidate_score": candidate.candidate_score,
        "confidence": candidate.confidence,
        "setup": candidate.setup,
        "timing": candidate.timing,
        "trade_plan_status": candidate.trade_plan_status,
        "rejection_reason": candidate.rejection_reason,
        "rejection_reasons": candidate.rejection_reasons,
        "rejection_categories": candidate.rejection_categories,
        "component_scores": candidate.component_scores,
        "entry_price": candidate.entry_price,
        "prospective_stop": candidate.prospective_stop,
        "prospective_target": candidate.prospective_target,
        "expected_reward_risk": candidate.expected_reward_risk,
        "expected_return": candidate.expected_return,
        "holding_period_sessions": candidate.holding_period_sessions,
        "sector": candidate.sector,
        "liquidity_bucket": candidate.liquidity_bucket,
        "rank": candidate.rank,
    }


def _classification_row(item: RejectionAssessment) -> dict[str, object]:
    row = _population_row(item)
    row.update(
        {
            "classification": item.classification,
            "classification_reason": item.classification_reason,
            "primary_component": item.primary_component,
        }
    )
    for prefix, outcome in (
        ("planned", item.planned_outcome),
        ("20d", item.horizon_20d),
        ("60d", item.horizon_60d),
        ("120d", item.horizon_120d),
    ):
        row.update(
            {
                f"{prefix}_available_sessions": outcome.available_sessions,
                f"{prefix}_holding_sessions": outcome.holding_sessions,
                f"{prefix}_complete": outcome.complete,
                f"{prefix}_entered": outcome.entered,
                f"{prefix}_entry_date": outcome.entry_date,
                f"{prefix}_execution_price": outcome.execution_price,
                f"{prefix}_exit_date": outcome.exit_date,
                f"{prefix}_exit_price": outcome.exit_price,
                f"{prefix}_exit_reason": outcome.exit_reason,
                f"{prefix}_target_reached": outcome.target_reached,
                f"{prefix}_stop_reached": outcome.stop_reached,
                f"{prefix}_stop_before_target": outcome.stop_before_target,
                f"{prefix}_mfe_percent": (outcome.maximum_favourable_excursion_percent),
                f"{prefix}_mae_percent": outcome.maximum_adverse_excursion_percent,
                f"{prefix}_gross_return_percent": outcome.gross_return_percent,
                f"{prefix}_net_return_percent": outcome.net_return_percent,
                f"{prefix}_realized_r": outcome.realized_r,
                f"{prefix}_positive_after_costs": outcome.positive_after_costs,
                f"{prefix}_ambiguity_count": outcome.ambiguity_count,
            }
        )
    return row


def _write_csv(
    path: Path,
    rows: tuple[object, ...],
    *,
    headers: tuple[str, ...] | None = None,
) -> Path:
    normalized = tuple(_row(item) for item in rows)
    fieldnames = headers or (tuple(normalized[0]) if normalized else ())
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    if fieldnames:
        writer.writeheader()
        writer.writerows(normalized)
    return _write_text(path, stream.getvalue())


def _row(value: object) -> dict[str, object]:
    if is_dataclass(value) and not isinstance(value, type):
        raw = {field.name: getattr(value, field.name) for field in fields(value)}
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise TypeError("IGTA CSV rows must be dataclasses or mappings")
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
            {field.name: getattr(value, field.name) for field in fields(value)}
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


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


__all__ = [
    "DEFAULT_GATE_OUTPUT",
    "InstitutionalGateTruthExporter",
    "load_gate_manifest",
]
