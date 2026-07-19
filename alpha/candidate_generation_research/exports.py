from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable
from dataclasses import fields, is_dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, cast

from alpha.candidate_generation_research.models import (
    CandidateFunnelRecord,
    CandidateResearchReport,
    CandidateResearchSummary,
    CandidateTimingRecord,
    CandidateVariantResult,
    ChronologicalValidationResult,
    MissedCandidateAttribution,
    PineCandidateParityRecord,
    PineLogicalTradeAudit,
    SetupRecognitionMetric,
    TradableOpportunityOnset,
    ZeroCandidateDiagnostic,
    to_primitive,
)
from alpha.candidate_generation_research.rendering import render_executive_report
from alpha.canonical_integrity_audit.models import MajorOpportunityEvent

DEFAULT_CANDIDATE_RESEARCH_OUTPUT = Path(
    ".alpha/candidate_research/ALPHA_CANONICAL_v1.0"
)


class CandidateResearchExporter:
    def export(
        self,
        report: CandidateResearchReport,
        *,
        output_directory: Path | str = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
    ) -> tuple[Path, ...]:
        root = Path(output_directory)
        root.mkdir(parents=True, exist_ok=True)
        return (
            _json(root / "candidate_research.json", report),
            _json(root / "candidate_research_manifest.json", report.manifest),
            _csv(
                root / "forward_move_events.csv",
                report.forward_move_events,
                MajorOpportunityEvent,
            ),
            _csv(
                root / "tradable_opportunity_onsets.csv",
                report.onsets,
                TradableOpportunityOnset,
            ),
            _csv(
                root / "tradable_vs_hindsight_summary.csv",
                (report.summary,),
                CandidateResearchSummary,
            ),
            _csv(
                root / "candidate_generation_funnel.csv",
                report.funnel,
                CandidateFunnelRecord,
            ),
            _csv(
                root / "setup_recognition_metrics.csv",
                report.setup_metrics,
                SetupRecognitionMetric,
            ),
            _csv(
                root / "candidate_timing_metrics.csv",
                report.timing_metrics,
                CandidateTimingRecord,
            ),
            _csv(
                root / "missed_candidate_attribution.csv",
                report.missed_attribution,
                MissedCandidateAttribution,
            ),
            _csv(
                root / "candidate_variant_results.csv",
                report.variant_results,
                CandidateVariantResult,
            ),
            _csv(
                root / "chronological_validation.csv",
                report.validations,
                ChronologicalValidationResult,
            ),
            _csv(
                root / "zero_candidate_diagnostics.csv",
                report.zero_candidates,
                ZeroCandidateDiagnostic,
            ),
            _csv(
                root / "pine_logical_trade_audit.csv",
                report.pine_logical_trades,
                PineLogicalTradeAudit,
            ),
            _csv(
                root / "pine_candidate_parity.csv",
                report.pine_candidate_parity,
                PineCandidateParityRecord,
            ),
            _json_payload(
                root / "case_studies.json",
                [to_primitive(item) for item in report.case_studies],
            ),
            _json(root / "candidate_policy_proposal.json", report.policy_proposal),
            _text(root / "executive_report.md", render_executive_report(report)),
        )


def load_candidate_research_payload(
    directory: Path | str = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
) -> dict[str, object]:
    path = Path(directory) / "candidate_research.json"
    if not path.exists():
        raise FileNotFoundError(f"candidate research is unavailable at {path}")
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(decoded, dict)
        or decoded.get("production_influence") is not False
    ):
        raise ValueError("invalid candidate research artifact")
    return {str(key): value for key, value in decoded.items()}


def _csv(path: Path, rows: Iterable[object], row_type: type[object]) -> Path:
    materialized = tuple(rows)
    first = materialized[0] if materialized else row_type
    if not is_dataclass(first) or isinstance(first, type):
        if not is_dataclass(row_type):
            raise TypeError("candidate research CSV rows must be dataclasses")
    columns = tuple(item.name for item in fields(cast(Any, first)))
    primitive_rows = []
    for item in materialized:
        primitive = to_primitive(item)
        if not isinstance(primitive, dict):
            raise TypeError("candidate research CSV row must serialize to an object")
        primitive_rows.append(
            {column: _csv_value(primitive.get(column)) for column in columns}
        )
    buffer = _CsvBuffer()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(primitive_rows)
    return _text(path, buffer.value)


def _json(path: Path, value: object) -> Path:
    return _json_payload(path, to_primitive(value))


def _json_payload(path: Path, value: object) -> Path:
    return _text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _csv_value(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "" if value is None else value


def _text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


class _CsvBuffer:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, value: str) -> int:
        self.parts.append(value)
        return len(value)

    @property
    def value(self) -> str:
        return "".join(self.parts)


__all__ = [
    "DEFAULT_CANDIDATE_RESEARCH_OUTPUT",
    "CandidateResearchExporter",
    "load_candidate_research_payload",
]
