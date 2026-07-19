"""Deterministic exports and artifact repository for historical universes."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb

from alpha.point_in_time_universe.models import UniverseManifest

DEFAULT_UNIVERSE_OUTPUT = Path(
    ".alpha/point_in_time_universe/POINT_IN_TIME_UNIVERSE_v1.0"
)


class UniverseExporter:
    def export_rows(
        self,
        *,
        output_directory: Path,
        manifest: UniverseManifest,
        security_master: tuple[object, ...],
        universe_size_by_date: tuple[dict[str, object], ...],
        index_membership_changes: tuple[dict[str, object], ...],
        sector_history: tuple[dict[str, object], ...],
        listing_history: tuple[dict[str, object], ...],
        corporate_actions: tuple[dict[str, object], ...],
        survivorship_audit: tuple[dict[str, object], ...],
        executive_report: str,
    ) -> tuple[Path, ...]:
        output_directory.mkdir(parents=True, exist_ok=True)
        paths = (
            _write_csv(
                output_directory / "universe_size_by_date.csv",
                universe_size_by_date,
                ("date", "observed_universe_size", "confidence"),
            ),
            _write_csv(
                output_directory / "index_membership_changes.csv",
                index_membership_changes,
                (
                    "date",
                    "index",
                    "status",
                    "member_count",
                    "additions",
                    "removals",
                    "source",
                    "confidence",
                ),
            ),
            _write_csv(
                output_directory / "sector_history.csv",
                sector_history,
                (
                    "security_id",
                    "effective_from",
                    "effective_to",
                    "sector",
                    "industry",
                    "source",
                    "confidence",
                    "status",
                ),
            ),
            _write_csv(
                output_directory / "listing_history.csv",
                listing_history,
                (
                    "security_id",
                    "symbol",
                    "first_local_observation",
                    "last_local_observation",
                    "official_listing_date",
                    "official_delisting_date",
                    "suspended_periods",
                    "relisting_dates",
                    "source",
                    "confidence",
                ),
            ),
            _write_csv(
                output_directory / "corporate_actions.csv",
                corporate_actions,
                (
                    "action_id",
                    "security_id",
                    "action_type",
                    "effective_date",
                    "ratio",
                    "old_symbol",
                    "new_symbol",
                    "predecessors",
                    "successors",
                    "source",
                    "confidence",
                ),
            ),
            _write_csv(
                output_directory / "survivorship_audit.csv",
                survivorship_audit,
                (
                    "date",
                    "observed_universe_size",
                    "invalid_securities",
                    "future_constituent_leaks",
                    "stale_sector_mappings",
                    "unknown_indices",
                    "unknown_sectors",
                    "status",
                ),
            ),
            _write_json(output_directory / "security_master.json", security_master),
            _write_json(output_directory / "manifest.json", manifest),
            _write_text(output_directory / "executive_report.md", executive_report),
        )
        return paths


class UniverseArtifactRepository:
    def __init__(self, directory: Path = DEFAULT_UNIVERSE_OUTPUT) -> None:
        self.directory = directory

    def manifest_payload(self) -> dict[str, object]:
        path = self.directory / "manifest.json"
        if not path.exists():
            raise FileNotFoundError(f"universe artifacts unavailable: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("universe manifest is invalid")
        return {str(key): value for key, value in payload.items()}

    def members_on(
        self, as_of: date, *, limit: int | None = None
    ) -> tuple[dict[str, object], ...]:
        path = self.directory / "universe_membership.parquet"
        if not path.exists():
            raise FileNotFoundError(f"universe membership unavailable: {path}")
        query = """
            SELECT as_of, security_id, symbol, exchange, tradability,
                   sector, sector_status, confidence
            FROM read_parquet(?)
            WHERE as_of = ?
            ORDER BY symbol, security_id
        """
        parameters: list[object] = [str(path), as_of]
        if limit is not None:
            if limit < 1:
                raise ValueError("limit must be positive")
            query += " LIMIT ?"
            parameters.append(limit)
        with duckdb.connect(":memory:") as connection:
            rows = connection.execute(query, parameters).fetchall()
        columns = (
            "as_of",
            "security_id",
            "symbol",
            "exchange",
            "tradability",
            "sector",
            "sector_status",
            "confidence",
        )
        return tuple(dict(zip(columns, row, strict=True)) for row in rows)

    def index_rows(self, index_name: str) -> tuple[dict[str, str], ...]:
        path = self.directory / "index_membership_changes.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            return tuple(
                row for row in csv.DictReader(handle) if row["index"] == index_name
            )


def _write_csv(
    path: Path,
    rows: tuple[dict[str, object], ...],
    fieldnames: tuple[str, ...],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            {key: _scalar(row.get(key)) for key in fieldnames} for row in rows
        )
    return path


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return _scalar(value)


def _scalar(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if value is None:
        return ""
    return value


__all__ = [
    "DEFAULT_UNIVERSE_OUTPUT",
    "UniverseArtifactRepository",
    "UniverseExporter",
]
