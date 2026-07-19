from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable
from dataclasses import fields, is_dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, cast

from alpha.canonical_integrity_audit.models import (
    CanonicalIntegrityAuditReport,
    CoverageClassification,
    MajorOpportunityEvent,
    OpportunityCoverageRecord,
    ParityDivergenceSummary,
    PineAlphaTradeMatch,
    PineTrade,
    RuntimeFailureGroup,
    RuntimeFailureRecord,
    RuntimeReplayComparison,
    ZeroTradeDiagnostic,
    to_primitive,
)
from alpha.canonical_integrity_audit.rendering import render_executive_report

DEFAULT_INTEGRITY_OUTPUT_DIRECTORY = Path(
    ".alpha/canonical_integrity/ALPHA_CANONICAL_v1.0"
)


class CanonicalIntegrityAuditExporter:
    def export(
        self,
        report: CanonicalIntegrityAuditReport,
        *,
        output_directory: Path | str = DEFAULT_INTEGRITY_OUTPUT_DIRECTORY,
    ) -> tuple[Path, ...]:
        root = Path(output_directory)
        root.mkdir(parents=True, exist_ok=True)
        missed = tuple(
            item
            for item in report.coverage
            if item.classification
            in {
                CoverageClassification.MISSED,
                CoverageClassification.REJECTED,
                CoverageClassification.RUNTIME_BLOCKED,
                CoverageClassification.DATA_BLOCKED,
            }
        )
        return (
            _json(root / "integrity_audit.json", report),
            _json(root / "policy_manifest.json", report.policy),
            _csv(
                root / "runtime_failures.csv",
                report.runtime_failures,
                RuntimeFailureRecord,
            ),
            _csv(
                root / "runtime_failure_groups.csv",
                report.runtime_groups,
                RuntimeFailureGroup,
            ),
            _csv(
                root / "runtime_replay_comparison.csv",
                (report.runtime_replay,),
                RuntimeReplayComparison,
            ),
            _csv(
                root / "tradingview_trades_imported.csv", report.pine_trades, PineTrade
            ),
            _csv(
                root / "pine_alpha_trade_matches.csv",
                report.parity_matches,
                PineAlphaTradeMatch,
            ),
            _csv(
                root / "parity_divergence_summary.csv",
                report.divergences,
                ParityDivergenceSummary,
            ),
            _csv(
                root / "major_opportunities.csv",
                report.opportunities,
                MajorOpportunityEvent,
            ),
            _csv(
                root / "major_opportunity_coverage.csv",
                report.coverage,
                OpportunityCoverageRecord,
            ),
            _csv(root / "missed_opportunities.csv", missed, OpportunityCoverageRecord),
            _csv(
                root / "zero_trade_diagnostics.csv",
                report.zero_trades,
                ZeroTradeDiagnostic,
            ),
            _json_payload(
                root / "case_studies.json",
                [to_primitive(item) for item in report.case_studies],
            ),
            _text(root / "executive_report.md", render_executive_report(report)),
        )


def load_integrity_report_payload(
    directory: Path | str = DEFAULT_INTEGRITY_OUTPUT_DIRECTORY,
) -> dict[str, object]:
    path = Path(directory) / "integrity_audit.json"
    if not path.exists():
        raise FileNotFoundError(f"integrity audit is unavailable at {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("production_influence") is not False:
        raise ValueError("invalid integrity audit artifact")
    return {str(key): item for key, item in value.items()}


def _csv(path: Path, rows: Iterable[object], row_type: type[object]) -> Path:
    materialized = tuple(rows)
    first = materialized[0] if materialized else row_type
    if not is_dataclass(first) or isinstance(first, type):
        if not is_dataclass(row_type):
            raise TypeError("integrity CSV rows must be dataclass instances")
    columns = tuple(item.name for item in fields(cast(Any, first)))
    primitive_rows = []
    for item in materialized:
        primitive = to_primitive(item)
        if not isinstance(primitive, dict):
            raise TypeError("integrity CSV row must serialize to an object")
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
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
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
    "DEFAULT_INTEGRITY_OUTPUT_DIRECTORY",
    "CanonicalIntegrityAuditExporter",
    "load_integrity_report_payload",
]
