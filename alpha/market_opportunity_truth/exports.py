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
from alpha.market_opportunity_truth.models import (
    DEFAULT_OUTPUT,
    MarketOpportunityTruthReport,
)
from alpha.market_opportunity_truth.rendering import render_executive_report

DEFAULT_MARKET_OPPORTUNITY_OUTPUT = Path(DEFAULT_OUTPUT)


class MarketOpportunityTruthExporter:
    """Write deterministic MOTA artifacts and a checksum manifest."""

    def export(
        self,
        report: MarketOpportunityTruthReport,
        *,
        output_directory: Path | str = DEFAULT_MARKET_OPPORTUNITY_OUTPUT,
    ) -> tuple[Path, ...]:
        output = Path(output_directory)
        self._assert_compatible(output, report)
        output.mkdir(parents=True, exist_ok=True)
        paths = [
            _write_csv(output / "market_opportunities.csv", report.opportunities),
            _write_csv(output / "opportunity_calendar.csv", report.calendar),
            _write_csv(output / "opportunity_density.csv", report.density),
            _write_csv(
                output / "quality_distribution.csv",
                report.quality_distribution,
            ),
            _write_csv(output / "opportunity_clusters.csv", report.clusters),
            _write_csv(output / "alpha_vs_market.csv", report.alpha_comparison),
            _write_csv(
                output / "capture_statistics.csv",
                (report.capture_statistics,),
            ),
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
        report: MarketOpportunityTruthReport,
    ) -> None:
        path = output / "manifest.json"
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("baseline_manifest_hash")
            != report.manifest.baseline_manifest_hash
            or payload.get("quality_policy_version")
            != report.manifest.quality_policy_version
        ):
            raise ValueError(
                "immutable MOTA output already exists for different evidence"
            )


def load_market_opportunity_manifest(
    output_directory: Path | str = DEFAULT_MARKET_OPPORTUNITY_OUTPUT,
) -> dict[str, object]:
    path = Path(output_directory) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(
            "MOTA manifest unavailable; run alpha market-opportunity audit"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("production_influence") is not False
    ):
        raise ValueError("invalid MOTA manifest")
    return {str(key): value for key, value in payload.items()}


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
        raise TypeError("MOTA CSV rows must be dataclasses or mappings")
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
    "DEFAULT_MARKET_OPPORTUNITY_OUTPUT",
    "MarketOpportunityTruthExporter",
    "load_market_opportunity_manifest",
]
