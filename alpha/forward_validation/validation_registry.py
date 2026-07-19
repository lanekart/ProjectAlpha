from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from alpha.forward_validation.models import (
    ForwardValidationConfig,
    PortfolioValuation,
    PositionEvent,
    PositionEventDraft,
    RecommendationSnapshot,
)

DEFAULT_FORWARD_REGISTRY_PATH = Path(".alpha/forward_validation/registry.json")


class ForwardValidationIntegrityError(ValueError):
    """Raised when immutable forward evidence fails integrity validation."""


class ForwardValidationRegistry:
    """Append-only, hash-validated store for frozen forward evidence."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_forward_registry_path(path)

    def initialize(self, config: ForwardValidationConfig) -> bool:
        payload = self._read_payload()
        current = payload.get("config")
        requested = config.as_dict()
        if current is not None:
            if current != requested:
                raise ForwardValidationIntegrityError(
                    "forward registry is already initialized with different settings"
                )
            return False
        payload["config"] = requested
        self._write_payload(payload)
        return True

    def load_config(self) -> ForwardValidationConfig:
        payload = self._read_payload().get("config")
        if not isinstance(payload, dict):
            raise ForwardValidationIntegrityError(
                "forward validation is not initialized; run `alpha forward start`"
            )
        return ForwardValidationConfig.from_dict(payload)

    def append_snapshots(
        self,
        snapshots: tuple[RecommendationSnapshot, ...],
    ) -> int:
        payload = self._read_payload()
        rows = _dict_rows(payload.get("snapshots"))
        by_id = {str(row.get("recommendation_id")): row for row in rows}
        inserted = 0
        for snapshot in sorted(
            snapshots,
            key=lambda item: (item.generated_at, item.symbol, item.recommendation_id),
        ):
            self._validate_snapshot(snapshot)
            row = snapshot.as_dict()
            existing = by_id.get(snapshot.recommendation_id)
            if existing is not None:
                if existing != row:
                    raise ForwardValidationIntegrityError(
                        f"immutable snapshot conflict: {snapshot.recommendation_id}"
                    )
                continue
            rows.append(row)
            by_id[snapshot.recommendation_id] = row
            inserted += 1
        payload["snapshots"] = rows
        self._write_payload(payload)
        return inserted

    def load_snapshots(self) -> tuple[RecommendationSnapshot, ...]:
        rows = _dict_rows(self._read_payload().get("snapshots"))
        snapshots = tuple(RecommendationSnapshot.from_dict(row) for row in rows)
        for snapshot in snapshots:
            self._validate_snapshot(snapshot)
        return tuple(
            sorted(
                snapshots,
                key=lambda item: (
                    item.generated_at,
                    item.symbol,
                    item.recommendation_id,
                ),
            )
        )

    def append_event(self, draft: PositionEventDraft) -> PositionEvent:
        payload = self._read_payload()
        rows = _dict_rows(payload.get("events"))
        existing = self.load_events()
        semantic_payload = _draft_payload(draft)
        event_id = sha256(canonical_json(semantic_payload).encode()).hexdigest()[:24]
        match = next((event for event in existing if event.event_id == event_id), None)
        if match is not None:
            return match
        sequence = len(existing) + 1
        previous_hash = existing[-1].event_hash if existing else "GENESIS"
        unhashed = {
            "sequence": sequence,
            "event_id": event_id,
            **semantic_payload,
            "previous_hash": previous_hash,
        }
        event_hash = sha256(canonical_json(unhashed).encode()).hexdigest()
        event = PositionEvent(
            sequence=sequence,
            event_id=event_id,
            recommendation_id=draft.recommendation_id,
            symbol=draft.symbol,
            occurred_at=draft.occurred_at,
            event_type=draft.event_type,
            price=draft.price,
            quantity=draft.quantity,
            cash_delta=draft.cash_delta,
            reason=draft.reason,
            metadata=dict(draft.metadata),
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        rows.append(event.as_dict())
        payload["events"] = rows
        self._write_payload(payload)
        return event

    def load_events(self) -> tuple[PositionEvent, ...]:
        rows = _dict_rows(self._read_payload().get("events"))
        events = tuple(PositionEvent.from_dict(row) for row in rows)
        previous_hash = "GENESIS"
        for expected_sequence, event in enumerate(events, start=1):
            if (
                event.sequence != expected_sequence
                or event.previous_hash != previous_hash
            ):
                raise ForwardValidationIntegrityError(
                    "forward event chain is discontinuous"
                )
            expected_hash = sha256(
                canonical_json(event.as_dict(include_hash=False)).encode()
            ).hexdigest()
            if expected_hash != event.event_hash:
                raise ForwardValidationIntegrityError(
                    f"forward event hash mismatch: {event.event_id}"
                )
            previous_hash = event.event_hash
        return events

    def append_valuation(self, valuation: PortfolioValuation) -> bool:
        payload = self._read_payload()
        rows = _dict_rows(payload.get("valuations"))
        row = valuation.as_dict()
        identity = (
            row["valued_at"],
            row["policy_version"],
            row["event_head_hash"],
        )
        for existing in rows:
            existing_identity = (
                existing.get("valued_at"),
                existing.get("policy_version"),
                existing.get("event_head_hash"),
            )
            if existing_identity == identity:
                if existing != row:
                    raise ForwardValidationIntegrityError(
                        "immutable portfolio valuation conflict"
                    )
                return False
        rows.append(row)
        payload["valuations"] = rows
        self._write_payload(payload)
        return True

    def load_valuations(self) -> tuple[PortfolioValuation, ...]:
        rows = _dict_rows(self._read_payload().get("valuations"))
        return tuple(
            sorted(
                (PortfolioValuation.from_dict(row) for row in rows),
                key=lambda item: (item.valued_at, item.policy_version.number),
            )
        )

    def export_json(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self._read_payload(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    def export_csv(self, directory: Path | str) -> tuple[Path, ...]:
        destination = Path(directory)
        destination.mkdir(parents=True, exist_ok=True)
        exports = (
            ("snapshots.csv", _dict_rows(self._read_payload().get("snapshots"))),
            ("events.csv", _dict_rows(self._read_payload().get("events"))),
            ("valuations.csv", _dict_rows(self._read_payload().get("valuations"))),
        )
        written: list[Path] = []
        for filename, rows in exports:
            output = destination / filename
            flattened = tuple(_flatten(row) for row in rows)
            fields = sorted({key for row in flattened for key in row})
            with output.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(flattened)
            written.append(output)
        return tuple(written)

    def _validate_snapshot(self, snapshot: RecommendationSnapshot) -> None:
        expected = sha256(
            canonical_json(snapshot.as_dict(include_hash=False)).encode()
        ).hexdigest()
        if snapshot.snapshot_hash != expected:
            raise ForwardValidationIntegrityError(
                f"recommendation snapshot hash mismatch: {snapshot.recommendation_id}"
            )

    def _read_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": "1.0",
                "production_influence": False,
                "config": None,
                "snapshots": [],
                "events": [],
                "valuations": [],
            }
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ForwardValidationIntegrityError("forward registry must be an object")
        if bool(data.get("production_influence", False)):
            raise ForwardValidationIntegrityError(
                "forward registry cannot declare production influence"
            )
        return data

    def _write_payload(self, payload: dict[str, Any]) -> None:
        payload["production_influence"] = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


def canonical_json(value: object) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))


def resolve_forward_registry_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.getenv("ALPHA_FORWARD_VALIDATION_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_FORWARD_REGISTRY_PATH


def _draft_payload(draft: PositionEventDraft) -> dict[str, object]:
    return {
        "recommendation_id": draft.recommendation_id,
        "symbol": draft.symbol,
        "occurred_at": draft.occurred_at.isoformat(),
        "event_type": draft.event_type.value,
        "price": None if draft.price is None else str(draft.price),
        "quantity": None if draft.quantity is None else str(draft.quantity),
        "cash_delta": str(draft.cash_delta),
        "reason": draft.reason,
        "metadata": dict(draft.metadata),
    }


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "as_dict"):
        return _jsonable(value.as_dict())
    return str(value)


def _flatten(payload: dict[str, Any]) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            flattened[key] = canonical_json(value)
        elif value is None:
            flattened[key] = ""
        else:
            flattened[key] = str(value)
    return flattened


__all__ = [
    "DEFAULT_FORWARD_REGISTRY_PATH",
    "ForwardValidationIntegrityError",
    "ForwardValidationRegistry",
    "canonical_json",
    "resolve_forward_registry_path",
]
