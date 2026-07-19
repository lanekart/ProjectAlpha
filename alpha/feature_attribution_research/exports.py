"""Deterministic CSV, JSON, Parquet, and Markdown exports."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, cast

import pandas as pd

from alpha.feature_attribution_research.models import FeatureAttributionReport
from alpha.feature_attribution_research.redundancy import clustered_feature_groups
from alpha.feature_attribution_research.rendering import (
    render_feature_cards,
    render_report,
)

DEFAULT_FEATURE_ATTRIBUTION_OUTPUT = Path(
    ".alpha/feature_attribution/POINT_IN_TIME_FEATURE_ATTRIBUTION_v1.0"
)


class FeatureAttributionExporter:
    def export(
        self,
        report: FeatureAttributionReport,
        *,
        output_directory: Path | str = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    ) -> tuple[Path, ...]:
        root = Path(output_directory)
        root.mkdir(parents=True, exist_ok=True)
        paths = []
        paths.append(_write_csv(root / "research_population.csv", report.population))
        paths.append(
            _write_json(root / "feature_registry.json", report.feature_definitions)
        )
        paths.append(_write_parquet(root / "feature_snapshots.parquet", report))
        paths.append(_write_csv(root / "outcome_labels.csv", report.outcomes))
        paths.append(_write_csv(root / "feature_quality.csv", report.quality))
        paths.append(_write_csv(root / "feature_leakage_audit.csv", report.leakage))
        paths.append(_write_csv(root / "univariate_attribution.csv", report.univariate))
        paths.append(
            _write_csv(root / "negative_feature_audit.csv", report.negative_features)
        )
        paths.append(
            _write_csv(root / "conditional_attribution.csv", report.conditional)
        )
        paths.append(_write_csv(root / "feature_redundancy.csv", report.redundancy))
        paths.append(
            _write_csv(
                root / "feature_clusters.csv",
                tuple(
                    {"cluster_id": index, "features": "|".join(group)}
                    for index, group in enumerate(
                        clustered_feature_groups(report.redundancy), start=1
                    )
                ),
            )
        )
        paths.append(_write_csv(root / "interaction_results.csv", report.interactions))
        paths.append(_write_csv(root / "chronological_stability.csv", report.stability))
        paths.append(
            _write_csv(root / "orthogonal_edge_results.csv", report.orthogonal)
        )
        paths.append(
            _write_csv(root / "information_decay.csv", report.information_decay)
        )
        paths.append(_write_csv(root / "feature_rankings.csv", report.rankings))
        paths.append(
            _write_csv(
                root / "missing_information_audit.csv", report.missing_information
            )
        )
        paths.append(_write_json(root / "case_studies.json", report.case_studies))
        paths.append(_write_json(root / "feature_cards.json", report.feature_cards))
        cards_path = root / "top20_feature_cards.md"
        cards_path.write_text(
            render_feature_cards(report.feature_cards), encoding="utf-8"
        )
        paths.append(cards_path)
        report_path = root / "executive_report.md"
        report_path.write_text(render_report(report), encoding="utf-8")
        paths.append(report_path)
        paths.append(_write_json(root / "manifest.json", _manifest_payload(report)))
        return tuple(paths)


def _write_parquet(path: Path, report: FeatureAttributionReport) -> Path:
    rows = []
    for item in report.feature_snapshots:
        row: dict[str, Any] = {
            "onset_id": item.onset_id,
            "symbol": item.symbol,
            "onset_date": item.onset_date,
            "partition": item.partition.value,
            "source_max_date": item.source_max_date,
            "feature_snapshot_hash": item.feature_snapshot_hash,
        }
        row.update(dict(item.values))
        rows.append(row)
    pd.DataFrame(rows).to_parquet(path, index=False, engine="pyarrow")
    return path


def _write_csv(path: Path, values: tuple[object, ...]) -> Path:
    rows = [_flatten(_convert(item)) for item in values]
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    fields = tuple(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_json(path: Path, value: object) -> Path:
    path.write_text(
        json.dumps(_convert(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _manifest_payload(report: FeatureAttributionReport) -> dict[str, object]:
    return {
        **_convert(report.manifest),
        "guardrails": {
            "PRODUCTION_INFLUENCE": False,
            "NO_WEIGHT_CHANGES": True,
            "NO_THRESHOLD_CHANGES": True,
            "NO_SETUP_CHANGES": True,
            "NO_APPROVAL_RELAXATION": True,
            "NO_AUTOMATIC_PROMOTION": True,
            "NO_FUTURE_LEAKAGE": True,
            "POINT_IN_TIME_ONLY": True,
            "HOLDOUT_REQUIRED": True,
            "LEGACY_DATA_IS_PROVISIONAL": True,
        },
        "population_summary": _convert(report.population_summary),
        "feature_count": len(report.feature_definitions),
        "point_in_time_safe_feature_count": sum(
            item.point_in_time_safe for item in report.feature_definitions
        ),
        "blocked_feature_count": sum(
            not item.point_in_time_safe for item in report.feature_definitions
        ),
        "top_feature_cards": [item.feature_id for item in report.feature_cards],
    }


def _convert(value: object) -> Any:
    if is_dataclass(value):
        return {key: _convert(item) for key, item in asdict(cast(Any, value)).items()}
    if isinstance(value, dict):
        return {str(key): _convert(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_convert(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _flatten(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"value": value}
    result: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, (dict, list)):
            result[key] = json.dumps(item, sort_keys=True, separators=(",", ":"))
        else:
            result[key] = item
    return result


__all__ = [
    "DEFAULT_FEATURE_ATTRIBUTION_OUTPUT",
    "FeatureAttributionExporter",
]
