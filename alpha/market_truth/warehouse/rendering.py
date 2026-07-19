from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from alpha.market_truth.warehouse.models import (
    IngestionResult,
    ReconciliationReport,
    SourceAuthorisation,
    WarehouseQualityReport,
    WarehouseStatus,
)
from alpha.market_truth.warehouse.session_inventory import SessionCoverage


def render_status(status: WarehouseStatus) -> tuple[str, ...]:
    return (
        "Historical Market Warehouse",
        f"Source Files: {status.source_files}",
        f"Validated Source Files: {status.validated_source_files}",
        f"Canonical Daily Records: {status.daily_records}",
        f"Identity Records: {status.identity_records}",
        f"Corporate Actions: {status.corporate_actions}",
        f"Adjusted Records: {status.adjusted_records}",
        f"Aggregate Records: {status.aggregate_records}",
        f"Universe Records: {status.universe_records}",
        f"Quarantined Records: {status.quarantined_records}",
        f"Latest Dataset Version: {status.latest_version or 'unavailable'}",
        f"Latest Published Version: {status.latest_published_version or 'unavailable'}",
        "Production Influence: false",
    )


def render_authorisations(records: tuple[SourceAuthorisation, ...]) -> tuple[str, ...]:
    lines = ["Source Authorisation Matrix"]
    for item in records:
        lines.append(
            f"- {item.record_id}: {item.status.value}; "
            f"method={item.acquisition_method.value}; storage="
            f"{'yes' if item.internal_storage_permitted else 'no'}; "
            f"research={'yes' if item.internal_research_permitted else 'no'}; "
            "redistribution=no"
        )
    lines.append("Unknown permission is never treated as permission.")
    return tuple(lines)


def render_ingestion(result: IngestionResult) -> tuple[str, ...]:
    return (
        "Warehouse Import",
        f"Source File ID: {result.source_file.source_file_id}",
        f"Exchange: {result.source_file.exchange.value}",
        f"Dataset: {result.source_file.dataset_type.value}",
        f"Status: {result.status.value}",
        f"Accepted Records: {result.accepted_records}",
        f"Rejected Records: {result.rejected_records}",
        f"Duplicate Records: {result.duplicate_records}",
        f"Idempotent Replay: {'yes' if result.idempotent else 'no'}",
        f"SHA-256: {result.source_file.sha256}",
    )


def render_coverage(values: tuple[SessionCoverage, ...]) -> tuple[str, ...]:
    lines = ["Historical Session Coverage"]
    for item in values:
        lines.extend(
            (
                f"{item.exchange.value} {item.start.isoformat()} "
                f"to {item.end.isoformat()}",
                f"  Expected: {item.expected}",
                f"  Validated: {item.validated}",
                f"  Partial: {item.partial}",
                f"  Missing: {item.missing}",
                f"  Holidays: {item.holidays}",
                f"  Special Sessions: {item.special_sessions}",
                f"  Quarantined: {item.quarantined}",
            )
        )
    return tuple(lines)


def render_quality(report: WarehouseQualityReport) -> tuple[str, ...]:
    lines = ["Warehouse Data Quality"]
    for item in report.components:
        lines.append(
            f"- {item.name}: {item.state.value}; checked={item.checked_records}; "
            f"affected={item.affected_records}; {item.explanation}"
        )
    lines.extend(
        (
            f"Quarantined Records: {report.quarantined_records}",
            "Production Influence: false",
        )
    )
    return tuple(lines)


def render_reconciliation(report: ReconciliationReport) -> tuple[str, ...]:
    return (
        "Current Store Reconciliation",
        f"Current Sessions: {report.current_sessions}",
        f"Warehouse Sessions: {report.warehouse_sessions}",
        f"Session Overlap: {report.overlapping_sessions}",
        f"Missing Sessions: {report.missing_sessions}",
        f"Extra Sessions: {report.extra_sessions}",
        f"Current Symbols: {report.current_symbols}",
        f"Warehouse Symbols: {report.warehouse_symbols}",
        f"Symbol Overlap: {report.symbol_overlap}",
        f"Rows Compared: {report.compared_rows}",
        f"Matching Rows: {report.matching_rows}",
        f"OHLCV Differences: {report.ohlcv_differences}",
        "Corporate-Action-Affected Differences: "
        f"{report.corporate_action_affected_differences}",
        f"Unexplained Differences: {report.unexplained_differences}",
        f"Quarantine Candidates: {report.quarantine_candidates}",
    )


def export_json(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_serialise(value), indent=2, sort_keys=True) + "\n")


def export_csv(values: tuple[object, ...], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = tuple(_flat(_serialise(item)) for item in values)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _serialise(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _serialise(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _serialise(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialise(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _flat(value: Any, prefix: str = "") -> dict[str, object]:
    if not isinstance(value, dict):
        return {prefix or "value": value}
    output: dict[str, object] = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            output.update(_flat(item, name))
        else:
            output[name] = (
                json.dumps(item, sort_keys=True) if isinstance(item, list) else item
            )
    return output


__all__ = [
    "export_csv",
    "export_json",
    "render_authorisations",
    "render_coverage",
    "render_ingestion",
    "render_quality",
    "render_reconciliation",
    "render_status",
]
