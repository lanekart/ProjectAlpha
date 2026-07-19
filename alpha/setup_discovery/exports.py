from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable
from dataclasses import fields, is_dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, cast

from alpha.setup_discovery.evidence_book import TopMissedOpportunityEvidenceBook
from alpha.setup_discovery.models import (
    LookbackEvidence,
    SetupCluster,
    SetupDiscoveryReport,
    SetupFeatureRecord,
    to_primitive,
)
from alpha.setup_discovery.rendering import render_recommendations

DEFAULT_SETUP_DISCOVERY_OUTPUT = Path(".alpha/setup_discovery/SDE_v1.0")


class SetupDiscoveryExporter:
    def export(
        self,
        report: SetupDiscoveryReport,
        *,
        output_directory: Path | str = DEFAULT_SETUP_DISCOVERY_OUTPUT,
    ) -> tuple[Path, ...]:
        root = Path(output_directory)
        root.mkdir(parents=True, exist_ok=True)
        paths = (
            _csv(root / "setup_clusters.csv", report.clusters, SetupCluster),
            _csv(
                root / "lookback_evidence.csv",
                report.lookback_evidence,
                LookbackEvidence,
            ),
            _json(root / "setup_family_catalog.json", report.catalog),
            _text(root / "setup_recommendations.md", render_recommendations(report)),
            _text(root / "kalyan_deep_dive.md", report.kalyan_deep_dive),
            _text(root / "pcjeweller_deep_dive.md", report.pcjeweller_deep_dive),
            _json(root / "setup_discovery_manifest.json", report.manifest),
            _json(root / "setup_discovery_summary.json", report.summary),
            _csv(
                root / "point_in_time_setup_features.csv",
                report.features,
                SetupFeatureRecord,
            ),
            _json(root / "top100_missed_opportunities.json", report.top_opportunities),
        )
        pdf = TopMissedOpportunityEvidenceBook().write(
            report, root / "top100_missed_opportunities.pdf"
        )
        return (*paths, pdf)


def load_setup_discovery_summary(
    directory: Path | str = DEFAULT_SETUP_DISCOVERY_OUTPUT,
) -> dict[str, object]:
    root = Path(directory)
    summary = _load_mapping(root / "setup_discovery_summary.json")
    manifest = _load_mapping(root / "setup_discovery_manifest.json")
    if manifest.get("production_influence") is not False:
        raise ValueError("setup discovery artifact has invalid production influence")
    return {"summary": summary, "manifest": manifest}


def _csv(path: Path, rows: Iterable[object], row_type: type[object]) -> Path:
    materialized = tuple(rows)
    template = materialized[0] if materialized else row_type
    if not is_dataclass(template) and not is_dataclass(row_type):
        raise TypeError("setup discovery CSV rows must be dataclasses")
    columns = tuple(item.name for item in fields(cast(Any, template)))
    buffer = _CsvBuffer()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in materialized:
        primitive = to_primitive(row)
        if not isinstance(primitive, dict):
            raise TypeError("setup discovery CSV row must serialize to an object")
        writer.writerow(
            {column: _csv_value(primitive.get(column)) for column in columns}
        )
    return _text(path, buffer.value)


def _json(path: Path, value: object) -> Path:
    return _text(path, json.dumps(to_primitive(value), indent=2, sort_keys=True) + "\n")


def _load_mapping(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"setup discovery artifact unavailable: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid setup discovery artifact: {path}")
    return {str(key): item for key, item in value.items()}


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
    "DEFAULT_SETUP_DISCOVERY_OUTPUT",
    "SetupDiscoveryExporter",
    "load_setup_discovery_summary",
]
