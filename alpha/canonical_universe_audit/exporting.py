from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable
from dataclasses import fields, is_dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from alpha.canonical_universe_audit.models import (
    CanonicalUniverseAuditReport,
    to_primitive,
)
from alpha.canonical_universe_audit.rendering import render_executive_report

DEFAULT_ACU_OUTPUT_DIRECTORY = Path(".alpha/acu/ALPHA_CANONICAL_v1.0")


class CanonicalUniverseAuditExporter:
    """Write the complete deterministic ACU artifact set."""

    def export(
        self,
        report: CanonicalUniverseAuditReport,
        *,
        output_directory: Path | str = DEFAULT_ACU_OUTPUT_DIRECTORY,
    ) -> tuple[Path, ...]:
        destination = Path(output_directory)
        destination.mkdir(parents=True, exist_ok=True)
        paths = (
            self._json(destination / "opportunity_capacity.json", report),
            self._csv(
                destination / "opportunity_capacity.csv",
                (report.executive,),
            ),
            self._csv(destination / "gate_attribution.csv", report.gates),
            self._csv(destination / "sector_opportunities.csv", report.sectors),
            self._csv(destination / "daily_opportunities.csv", report.daily),
            self._csv(destination / "monthly_summary.csv", report.monthly),
            self._csv(destination / "candidate_rankings.csv", report.rankings),
            self._csv(destination / "liquidity_capacity.csv", report.liquidity),
            self._csv(destination / "symbol_statistics.csv", report.symbols),
            self._text(
                destination / "executive_report.md",
                render_executive_report(report),
            ),
            self._json_payload(
                destination / "trl_validation_bridge.json",
                {
                    "audit_id": report.audit_id,
                    "canonical_engine_version": report.canonical_engine_version,
                    "candidate_rankings": "candidate_rankings.csv",
                    "dataset_version": report.dataset.dataset_version,
                    "purpose": (
                        "Reference population for future matched TradingView "
                        "Research Laboratory validations."
                    ),
                    "production_influence": False,
                    "validation_status": "NOT_RUN",
                },
            ),
        )
        return paths

    def _json(self, path: Path, report: CanonicalUniverseAuditReport) -> Path:
        payload = to_primitive(report)
        return self._json_payload(path, payload)

    def _json_payload(self, path: Path, payload: object) -> Path:
        return _atomic_write(
            path,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
        )

    def _csv(self, path: Path, rows: Iterable[object]) -> Path:
        materialized = tuple(rows)
        if not materialized:
            return _atomic_write(path, "")
        first = materialized[0]
        if not is_dataclass(first) or isinstance(first, type):
            raise TypeError("ACU CSV rows must be dataclass instances")
        columns = tuple(item.name for item in fields(first))
        string_rows = []
        for row in materialized:
            primitive = to_primitive(row)
            if not isinstance(primitive, dict):
                raise TypeError("ACU CSV row did not serialize to a mapping")
            string_rows.append(
                {column: primitive.get(column, "") for column in columns}
            )
        buffer = _CsvBuffer()
        writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(string_rows)
        return _atomic_write(path, buffer.value)

    def _text(self, path: Path, text: str) -> Path:
        return _atomic_write(path, text)


class _CsvBuffer:
    def __init__(self) -> None:
        self._parts: list[str] = []

    def write(self, value: str) -> int:
        self._parts.append(value)
        return len(value)

    @property
    def value(self) -> str:
        return "".join(self._parts)


def load_audit_payload(
    output_directory: Path | str = DEFAULT_ACU_OUTPUT_DIRECTORY,
) -> dict[str, Any]:
    path = Path(output_directory) / "opportunity_capacity.json"
    if not path.exists():
        raise FileNotFoundError(
            f"ACU artifacts are unavailable at {path}; run `alpha acu run` first"
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("ACU opportunity-capacity artifact must be a JSON object")
    if value.get("production_influence") is not False:
        raise ValueError("ACU artifact production influence must remain false")
    return value


def _atomic_write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


__all__ = [
    "DEFAULT_ACU_OUTPUT_DIRECTORY",
    "CanonicalUniverseAuditExporter",
    "load_audit_payload",
]
