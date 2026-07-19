from __future__ import annotations

import csv
import json
import os
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from alpha.market_dna.models import MARKET_DNA_SCHEMA_VERSION, DNADiscoveryReport

DEFAULT_DNA_REGISTRY = Path(".alpha/market_dna/dna_registry.json")


class DNARegistry:
    """Append-only memory for accepted and rejected Market DNA experiments."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_dna_registry(path)

    def record(self, report: DNADiscoveryReport) -> bool:
        payload = self._read()
        reports = _rows(payload.get("reports"))
        row = _jsonable(report)
        existing = next(
            (item for item in reports if item.get("report_id") == report.report_id),
            None,
        )
        if existing is not None:
            if existing != row:
                raise ValueError("immutable Market DNA report conflict")
            return False
        reports.append(row)
        payload["reports"] = sorted(
            reports, key=lambda item: str(item.get("report_id", ""))
        )
        self._write(payload)
        return True

    def latest_payload(self) -> dict[str, Any] | None:
        reports = _rows(self._read().get("reports"))
        return reports[-1] if reports else None

    def export_json(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self._read(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    def export_csv(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        columns = (
            "report_id",
            "dataset_version",
            "pattern_id",
            "outcome_cohort",
            "scope",
            "conditions",
            "direction",
            "enrichment_ratio",
            "effect_size",
            "adjusted_p_value",
            "sample_size",
            "evidence_class",
            "stability",
            "status",
            "rejection_reasons",
            "production_influence",
        )
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for report in _rows(self._read().get("reports")):
                for pattern in _rows(report.get("patterns")):
                    writer.writerow(_csv_row(report, pattern))
        return destination

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": MARKET_DNA_SCHEMA_VERSION,
                "production_influence": False,
                "reports": [],
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Market DNA registry root must be an object")
        if payload.get("production_influence") is not False:
            raise ValueError("Market DNA registry must remain research-only")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        payload["schema_version"] = MARKET_DNA_SCHEMA_VERSION
        payload["production_influence"] = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


def resolve_dna_registry(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.getenv("ALPHA_MARKET_DNA_REGISTRY", "").strip()
    return Path(configured) if configured else DEFAULT_DNA_REGISTRY


def _jsonable(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _jsonable(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _csv_row(report: dict[str, Any], pattern: dict[str, Any]) -> dict[str, object]:
    return {
        "report_id": report.get("report_id", ""),
        "dataset_version": report.get("dataset_version", ""),
        "pattern_id": pattern.get("pattern_id", ""),
        "outcome_cohort": pattern.get("outcome_cohort", ""),
        "scope": pattern.get("scope", ""),
        "conditions": json.dumps(pattern.get("feature_conditions", []), sort_keys=True),
        "direction": pattern.get("direction", ""),
        "enrichment_ratio": pattern.get("enrichment_ratio", ""),
        "effect_size": pattern.get("effect_size", ""),
        "adjusted_p_value": pattern.get("adjusted_p_value", ""),
        "sample_size": pattern.get("sample_size", ""),
        "evidence_class": pattern.get("evidence_class", ""),
        "stability": pattern.get("robustness_classification", ""),
        "status": pattern.get("status", ""),
        "rejection_reasons": " | ".join(
            str(item) for item in pattern.get("rejection_reasons", [])
        ),
        "production_influence": "false",
    }


__all__ = ["DEFAULT_DNA_REGISTRY", "DNARegistry", "resolve_dna_registry"]
