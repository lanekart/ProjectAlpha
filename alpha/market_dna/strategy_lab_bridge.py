from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from alpha.market_dna.models import (
    MARKET_DNA_SCHEMA_VERSION,
    DNAHypothesis,
    StrategyLabHypothesisSpecification,
)

DEFAULT_BRIDGE_REGISTRY = Path(".alpha/market_dna/strategy_lab_hypotheses.json")


class StrategyLabBridge:
    """Publish an inert, versioned research specification without executing it."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_BRIDGE_REGISTRY

    def publish(self, hypothesis: DNAHypothesis) -> StrategyLabHypothesisSpecification:
        if hypothesis.production_influence:
            raise ValueError("production-influencing hypotheses cannot be published")
        specification = StrategyLabHypothesisSpecification(
            specification_id="DNA_LAB_SPEC_"
            + sha256(
                (
                    hypothesis.hypothesis_id
                    + "|"
                    + "|".join(
                        item.canonical_key for item in hypothesis.canonical_conditions
                    )
                ).encode()
            )
            .hexdigest()[:16]
            .upper(),
            hypothesis_id=hypothesis.hypothesis_id,
            originating_pattern_ids=hypothesis.originating_pattern_ids,
            conditions=hypothesis.canonical_conditions,
            entry_logic=hypothesis.proposed_entry_logic,
            horizon=hypothesis.proposed_horizon,
            evidence_class=hypothesis.evidence_class,
            assumptions=(
                "Specification is research-only and is not executed automatically.",
                "Strategy Lab, walk-forward, robustness, and shadow validation "
                "remain mandatory.",
            ),
        )
        self._record(specification)
        return specification

    def _record(self, specification: StrategyLabHypothesisSpecification) -> bool:
        payload = self._read()
        rows = _rows(payload.get("specifications"))
        row = _jsonable(specification)
        existing = next(
            (
                item
                for item in rows
                if item.get("specification_id") == specification.specification_id
            ),
            None,
        )
        if existing is not None:
            if existing != row:
                raise ValueError("immutable Strategy Lab hypothesis conflict")
            return False
        rows.append(row)
        payload["specifications"] = sorted(
            rows, key=lambda item: str(item.get("specification_id", ""))
        )
        self._write(payload)
        return True

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": MARKET_DNA_SCHEMA_VERSION,
                "production_influence": False,
                "execute_automatically": False,
                "specifications": [],
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Strategy Lab bridge registry must be an object")
        if (
            payload.get("production_influence") is not False
            or payload.get("execute_automatically") is not False
        ):
            raise ValueError("Strategy Lab bridge registry must remain inert")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        payload["schema_version"] = MARKET_DNA_SCHEMA_VERSION
        payload["production_influence"] = False
        payload["execute_automatically"] = False
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


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


__all__ = ["DEFAULT_BRIDGE_REGISTRY", "StrategyLabBridge"]
