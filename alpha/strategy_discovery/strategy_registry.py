from __future__ import annotations

import csv
import json
import os
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from alpha.strategy_discovery.models import (
    DISCOVERY_SCHEMA_VERSION,
    HoldoutAccessRecord,
    SearchSpaceManifest,
    StrategyLeaderboardEntry,
    StrategySpecification,
)

DEFAULT_STRATEGY_REGISTRY_PATH = Path(".alpha/strategy_discovery/registry.json")


class StrategyRegistry:
    """Persistent research ledger retaining every tested strategy."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_strategy_registry_path(path)

    def record_search(
        self,
        *,
        dataset_payload: dict[str, object],
        manifest: SearchSpaceManifest,
        strategies: tuple[StrategySpecification, ...],
    ) -> bool:
        payload = self._read()
        search_id = sha256(
            f"{dataset_payload['dataset_version']}|{manifest.search_space_hash}".encode()
        ).hexdigest()[:24]
        row = {
            "search_id": search_id,
            "dataset": dataset_payload,
            "manifest": _jsonable(manifest),
            "strategies": [_jsonable(item) for item in strategies],
            "production_influence": False,
        }
        searches = _rows(payload, "searches")
        existing = next(
            (item for item in searches if item.get("search_id") == search_id), None
        )
        if existing is not None:
            if existing != row:
                raise ValueError("immutable strategy search conflict")
            return False
        versions = {
            str(item.get("strategy_version")): str(item.get("strategy_hash"))
            for search in searches
            for item in search.get("strategies", [])
            if isinstance(search, dict)
            and isinstance(search.get("strategies"), list)
            and isinstance(item, dict)
        }
        for strategy in strategies:
            prior_hash = versions.get(strategy.strategy_version)
            if prior_hash is not None and prior_hash != strategy.strategy_hash:
                raise ValueError("strategy version already has a different hash")
        searches.append(row)
        payload["searches"] = searches
        self._write(payload)
        return True

    def record_leaderboard(
        self,
        *,
        dataset_version: str,
        entries: tuple[StrategyLeaderboardEntry, ...],
        decision: str,
    ) -> None:
        payload = self._read()
        boards = _rows(payload, "leaderboards")
        row = {
            "dataset_version": dataset_version,
            "entries": [_jsonable(item) for item in entries],
            "decision": decision,
            "production_influence": False,
        }
        existing = next(
            (item for item in boards if item.get("dataset_version") == dataset_version),
            None,
        )
        if existing is not None:
            if existing != row:
                raise ValueError("immutable strategy leaderboard conflict")
            return
        boards.append(row)
        payload["leaderboards"] = boards
        self._write(payload)

    def record_holdout_access(
        self,
        *,
        dataset_version: str,
        strategy_versions: tuple[str, ...],
        purpose: str,
        result_hash: str,
        accessed_at: datetime | None = None,
    ) -> HoldoutAccessRecord:
        payload = self._read()
        accesses = _rows(payload, "holdout_accesses")
        normalized_versions = tuple(sorted(strategy_versions))
        access_id = sha256(
            f"{dataset_version}|{'|'.join(normalized_versions)}|{purpose}".encode()
        ).hexdigest()[:24]
        existing = next(
            (
                item
                for item in accesses
                if item.get("dataset_version") == dataset_version
            ),
            None,
        )
        if existing is not None:
            if (
                tuple(existing.get("strategy_versions", [])) != normalized_versions
                or existing.get("purpose") != purpose
                or existing.get("result_hash") != result_hash
            ):
                raise ValueError(
                    "holdout was already accessed for a different final shortlist"
                )
            return _holdout_record(existing)
        record = HoldoutAccessRecord(
            access_id=access_id,
            accessed_at=accessed_at or datetime.now(tz=UTC),
            dataset_version=dataset_version,
            strategy_versions=normalized_versions,
            purpose=purpose,
            result_hash=result_hash,
        )
        accesses.append(_jsonable(record))
        payload["holdout_accesses"] = accesses
        self._write(payload)
        return record

    def holdout_accesses(self) -> tuple[HoldoutAccessRecord, ...]:
        return tuple(
            _holdout_record(item) for item in _rows(self._read(), "holdout_accesses")
        )

    def latest_leaderboard_payload(self) -> dict[str, Any] | None:
        boards = _rows(self._read(), "leaderboards")
        return boards[-1] if boards else None

    def export_json(self, path: Path | str) -> Path:
        destination = Path(path)
        _write_text(
            destination,
            json.dumps(self._read(), indent=2, sort_keys=True) + "\n",
        )
        return destination

    def export_csv(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fields = (
            "dataset_version",
            "rank",
            "strategy_version",
            "strategy_hash",
            "family",
            "classification",
            "training_expectancy_pct",
            "validation_expectancy_pct",
            "holdout_expectancy_pct",
            "completed_trades",
            "decision",
            "production_influence",
        )
        with destination.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for board in _rows(self._read(), "leaderboards"):
                entries = board.get("entries", [])
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    writer.writerow(_leaderboard_csv_row(board, entry))
        return destination

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": DISCOVERY_SCHEMA_VERSION,
                "production_influence": False,
                "searches": [],
                "holdout_accesses": [],
                "leaderboards": [],
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("strategy registry must be an object")
        if payload.get("production_influence") is not False:
            raise ValueError("strategy registry production influence must be false")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        payload["schema_version"] = DISCOVERY_SCHEMA_VERSION
        payload["production_influence"] = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


def resolve_strategy_registry_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.getenv("ALPHA_STRATEGY_DISCOVERY_REGISTRY_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_STRATEGY_REGISTRY_PATH


def _jsonable(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
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


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _holdout_record(payload: dict[str, Any]) -> HoldoutAccessRecord:
    versions = payload.get("strategy_versions", [])
    return HoldoutAccessRecord(
        access_id=str(payload["access_id"]),
        accessed_at=datetime.fromisoformat(str(payload["accessed_at"])),
        dataset_version=str(payload["dataset_version"]),
        strategy_versions=tuple(str(item) for item in versions),
        purpose=str(payload["purpose"]),
        result_hash=str(payload["result_hash"]),
    )


def _leaderboard_csv_row(
    board: dict[str, Any], entry: dict[str, Any]
) -> dict[str, object]:
    strategy = entry.get("strategy", {})
    evaluation = entry.get("evaluation", {})
    training = (
        evaluation.get("training_metrics", {}) if isinstance(evaluation, dict) else {}
    )
    validation = (
        evaluation.get("validation_metrics", {}) if isinstance(evaluation, dict) else {}
    )
    holdout = (
        evaluation.get("holdout_metrics", {}) if isinstance(evaluation, dict) else {}
    )
    return {
        "dataset_version": board.get("dataset_version", ""),
        "rank": entry.get("rank", ""),
        "strategy_version": strategy.get("strategy_version", "")
        if isinstance(strategy, dict)
        else "",
        "strategy_hash": strategy.get("strategy_hash", "")
        if isinstance(strategy, dict)
        else "",
        "family": strategy.get("family", "") if isinstance(strategy, dict) else "",
        "classification": entry.get("classification", ""),
        "training_expectancy_pct": training.get("expectancy_pct", "")
        if isinstance(training, dict)
        else "",
        "validation_expectancy_pct": validation.get("expectancy_pct", "")
        if isinstance(validation, dict)
        else "",
        "holdout_expectancy_pct": holdout.get("expectancy_pct", "")
        if isinstance(holdout, dict)
        else "",
        "completed_trades": validation.get("completed_trades", "")
        if isinstance(validation, dict)
        else "",
        "decision": board.get("decision", ""),
        "production_influence": "false",
    }


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def dataset_payload(dataset: object) -> dict[str, object]:
    from alpha.strategy_discovery.models import DiscoveryDataset

    if not isinstance(dataset, DiscoveryDataset):
        raise TypeError("dataset must be DiscoveryDataset")
    return {
        "dataset_version": dataset.dataset_version,
        "generated_at": dataset.generated_at.isoformat(),
        "source": dataset.source,
        "source_hash": dataset.source_hash,
        "population_class": dataset.population_class.value,
        "row_count": dataset.row_count,
        "rows": [row.as_dict() for row in dataset.rows],
        "exclusions": [_jsonable(item) for item in dataset.exclusions],
        "quarantined_population": dataset.quarantined_population,
        "production_influence": False,
    }


__all__ = [
    "DEFAULT_STRATEGY_REGISTRY_PATH",
    "StrategyRegistry",
    "dataset_payload",
    "resolve_strategy_registry_path",
]
