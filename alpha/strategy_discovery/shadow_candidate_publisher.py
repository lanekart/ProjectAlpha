from __future__ import annotations

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
    GeneralisationClassification,
    ShadowStrategyCandidate,
    StrategyDiscoveryReport,
)

DEFAULT_SHADOW_COHORT_REGISTRY_PATH = Path(
    ".alpha/forward_validation/strategy_shadow_cohorts.json"
)
NO_STRATEGY_DECISION = "NO_GENERALISABLE_STRATEGY_FOUND"


class ShadowCandidatePublisher:
    """Publish immutable research specifications to an isolated shadow registry."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = (
            Path(path) if path is not None else DEFAULT_SHADOW_COHORT_REGISTRY_PATH
        )

    def publish(
        self,
        report: StrategyDiscoveryReport,
        *,
        recommendation_engine_version: str = "recommendation-intelligence-current",
    ) -> ShadowStrategyCandidate | None:
        qualified = tuple(
            entry
            for entry in report.leaderboard
            if entry.classification
            is GeneralisationClassification.SHADOW_VALIDATION_CANDIDATE
        )
        if not qualified:
            return None
        selected = qualified[0]
        cohort = "FORWARD_STRATEGY_V2_SHADOW"
        specification_hash = sha256(
            json.dumps(
                {
                    "cohort_version": cohort,
                    "dataset_version": report.dataset.dataset_version,
                    "recommendation_engine_version": recommendation_engine_version,
                    "strategy_hash": selected.strategy.strategy_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        candidate = ShadowStrategyCandidate(
            cohort_version=cohort,
            strategy=selected.strategy,
            published_at=report.generated_at.astimezone(UTC),
            recommendation_engine_version=recommendation_engine_version,
            source_dataset_version=report.dataset.dataset_version,
            immutable_specification_hash=specification_hash,
        )
        self._record(candidate)
        return candidate

    def load(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("production_influence") is not False
        ):
            raise ValueError("shadow strategy registry must be research-only")
        rows = payload.get("candidates", [])
        if not isinstance(rows, list):
            raise ValueError("shadow strategy candidates must be a list")
        return tuple(dict(row) for row in rows if isinstance(row, dict))

    def _record(self, candidate: ShadowStrategyCandidate) -> None:
        rows = list(self.load())
        encoded = _jsonable(candidate)
        existing = next(
            (
                row
                for row in rows
                if row.get("immutable_specification_hash")
                == candidate.immutable_specification_hash
            ),
            None,
        )
        if existing is not None:
            if existing != encoded:
                raise ValueError("immutable shadow strategy specification changed")
            return
        if any(row.get("cohort_version") == candidate.cohort_version for row in rows):
            raise ValueError(
                "shadow cohort version already belongs to another strategy"
            )
        rows.append(encoded)
        payload = {
            "schema_version": "strategy-shadow-cohort-v1",
            "production_influence": False,
            "capital_allocation_enabled": False,
            "broker_execution_enabled": False,
            "candidates": rows,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


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
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


__all__ = [
    "DEFAULT_SHADOW_COHORT_REGISTRY_PATH",
    "NO_STRATEGY_DECISION",
    "ShadowCandidatePublisher",
]
