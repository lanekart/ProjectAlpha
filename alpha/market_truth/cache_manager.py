from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from alpha.market_truth.models import (
    EvidenceClass,
    MarketTruthRequest,
    ProviderDataset,
    record_as_dict,
    record_from_dict,
)

DEFAULT_MARKET_TRUTH_CACHE = Path(".alpha/market_truth/cache.json")
CACHE_SCHEMA_VERSION = "market-truth-cache-v1"


class MarketTruthCacheIntegrityError(ValueError):
    pass


class MarketTruthCacheManager:
    """Content-verified deterministic cache for immutable provider datasets."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_MARKET_TRUTH_CACHE

    def put(self, request: MarketTruthRequest, dataset: ProviderDataset) -> bool:
        if request.request_id != dataset.request_id:
            raise ValueError("cache request and provider dataset do not match")
        payload = self._read()
        entries = _entries(payload)
        existing = entries.get(request.request_id)
        serialized = _dataset_dict(dataset)
        if existing is not None:
            if existing != serialized:
                raise MarketTruthCacheIntegrityError(
                    "immutable market truth cache key has conflicting content"
                )
            return False
        entries[request.request_id] = serialized
        self._write({"schema_version": CACHE_SCHEMA_VERSION, "entries": entries})
        return True

    def get(self, request: MarketTruthRequest) -> ProviderDataset | None:
        row = _entries(self._read()).get(request.request_id)
        if row is None:
            return None
        dataset = _dataset_from_dict(row)
        if dataset.request_id != request.request_id:
            raise MarketTruthCacheIntegrityError("cache request id mismatch")
        stored_checksum = str(row.get("checksum", ""))
        if dataset.checksum != stored_checksum:
            raise MarketTruthCacheIntegrityError("cache checksum verification failed")
        return dataset

    def count(self) -> int:
        return len(_entries(self._read()))

    def clear_for_tests(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": CACHE_SCHEMA_VERSION, "entries": {}}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise MarketTruthCacheIntegrityError("cache root must be an object")
        if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
            raise MarketTruthCacheIntegrityError("unsupported cache schema version")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


def _entries(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get("entries", {})
    if not isinstance(raw, dict):
        raise MarketTruthCacheIntegrityError("cache entries must be an object")
    entries: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise MarketTruthCacheIntegrityError("cache entry must be an object")
        entries[str(key)] = value
    return entries


def _dataset_dict(dataset: ProviderDataset) -> dict[str, Any]:
    return {
        "request_id": dataset.request_id,
        "provider_id": dataset.provider_id,
        "source": dataset.source,
        "evidence_class": dataset.evidence_class.value,
        "observed_at": dataset.observed_at.isoformat(),
        "records": [record_as_dict(item) for item in dataset.records],
        "reported_completeness": str(dataset.reported_completeness),
        "source_reference": dataset.source_reference,
        "warnings": list(dataset.warnings),
        "checksum": dataset.checksum,
    }


def _dataset_from_dict(row: dict[str, Any]) -> ProviderDataset:
    from datetime import datetime
    from decimal import Decimal

    raw_records = row.get("records", [])
    if not isinstance(raw_records, list):
        raise MarketTruthCacheIntegrityError("cache records must be a list")
    records = tuple(
        record_from_dict(item) for item in raw_records if isinstance(item, dict)
    )
    if len(records) != len(raw_records):
        raise MarketTruthCacheIntegrityError("cache contains malformed records")
    return ProviderDataset(
        request_id=str(row["request_id"]),
        provider_id=str(row["provider_id"]),
        source=str(row["source"]),
        evidence_class=EvidenceClass(str(row["evidence_class"])),
        observed_at=datetime.fromisoformat(str(row["observed_at"])),
        records=records,
        reported_completeness=Decimal(str(row["reported_completeness"])),
        source_reference=str(row["source_reference"]),
        warnings=tuple(str(item) for item in row.get("warnings", [])),
    )


__all__ = [
    "CACHE_SCHEMA_VERSION",
    "DEFAULT_MARKET_TRUTH_CACHE",
    "MarketTruthCacheIntegrityError",
    "MarketTruthCacheManager",
]
