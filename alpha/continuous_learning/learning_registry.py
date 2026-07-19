from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from alpha.continuous_learning.models import (
    CLL_SCHEMA_VERSION,
    LearningConfidence,
    LearningEvent,
    LearningOutcomeStatus,
    OutcomeObservation,
)

DEFAULT_LEARNING_REGISTRY_PATH = Path(".alpha/continuous_learning/registry.json")


class ContinuousLearningRegistry:
    """Append-only persistence for outcome observations and learning events."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_learning_registry_path(path)

    def append_observations(self, observations: tuple[OutcomeObservation, ...]) -> int:
        payload = self._read()
        rows = _dict_rows(payload.get("outcome_observations"))
        by_id = {str(row.get("observation_id")): row for row in rows}
        inserted = 0
        for observation in observations:
            row = _observation_payload(observation)
            existing = by_id.get(observation.observation_id)
            if existing is not None:
                if existing != row:
                    raise ValueError("immutable learning observation conflict")
                continue
            rows.append(row)
            by_id[observation.observation_id] = row
            inserted += 1
        payload["outcome_observations"] = rows
        self._write(payload)
        return inserted

    def append_learning_events(self, events: tuple[LearningEvent, ...]) -> int:
        payload = self._read()
        rows = _dict_rows(payload.get("learning_events"))
        by_id = {str(row.get("event_id")): row for row in rows}
        inserted = 0
        for event in events:
            row = _event_payload(event)
            existing = by_id.get(event.event_id)
            if existing is not None:
                if existing != row and not _legacy_event_matches(existing, row):
                    raise ValueError("immutable learning event conflict")
                continue
            rows.append(row)
            by_id[event.event_id] = row
            inserted += 1
        payload["learning_events"] = rows
        self._write(payload)
        return inserted

    def load_observations(self) -> tuple[OutcomeObservation, ...]:
        return tuple(
            sorted(
                (
                    _observation_from_payload(row)
                    for row in _dict_rows(self._read().get("outcome_observations"))
                ),
                key=lambda item: (item.observed_at, item.observation_id),
            )
        )

    def load_learning_events(self) -> tuple[LearningEvent, ...]:
        return tuple(
            sorted(
                (
                    _event_from_payload(row)
                    for row in _dict_rows(self._read().get("learning_events"))
                ),
                key=lambda item: (item.occurred_at, item.event_id),
            )
        )

    def latest_observations(self) -> tuple[OutcomeObservation, ...]:
        latest: dict[str, OutcomeObservation] = {}
        for item in self.load_observations():
            current = latest.get(item.recommendation_id)
            if current is None or (item.observed_at, item.observation_id) >= (
                current.observed_at,
                current.observation_id,
            ):
                latest[item.recommendation_id] = item
        return tuple(
            sorted(latest.values(), key=lambda item: (item.generated_at, item.symbol))
        )

    def export_json(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self._read(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    def export_csv(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fields = (
            "record_type",
            "record_id",
            "timestamp",
            "recommendation_id",
            "symbol",
            "status_or_type",
            "outcome",
            "realised_return_pct",
            "learning",
            "confidence",
            "evidence",
            "suggested_research",
            "production_influence",
        )
        with destination.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for observation in self.load_observations():
                writer.writerow(
                    {
                        "record_type": "OUTCOME_OBSERVATION",
                        "record_id": observation.observation_id,
                        "timestamp": observation.observed_at.isoformat(),
                        "recommendation_id": observation.recommendation_id,
                        "symbol": observation.symbol,
                        "status_or_type": observation.status.value,
                        "outcome": observation.status.value,
                        "realised_return_pct": _text(observation.realised_return_pct),
                        "learning": "",
                        "confidence": "",
                        "evidence": observation.evidence_hash,
                        "suggested_research": "",
                        "production_influence": "false",
                    }
                )
            for event in self.load_learning_events():
                writer.writerow(
                    {
                        "record_type": "LEARNING_EVENT",
                        "record_id": event.event_id,
                        "timestamp": event.occurred_at.isoformat(),
                        "recommendation_id": event.recommendation_id or "",
                        "symbol": "",
                        "status_or_type": event.event_type,
                        "outcome": event.outcome or "",
                        "realised_return_pct": "",
                        "learning": event.learning,
                        "confidence": event.confidence.value,
                        "evidence": " | ".join(event.evidence),
                        "suggested_research": event.suggested_research or "",
                        "production_influence": "false",
                    }
                )
        return destination

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_payload()
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("continuous learning registry must be an object")
        if value.get("production_influence") is not False:
            raise ValueError("continuous learning registry must be research-only")
        return value

    def _write(self, payload: dict[str, Any]) -> None:
        payload["schema_version"] = CLL_SCHEMA_VERSION
        payload["production_influence"] = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


def resolve_learning_registry_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.getenv("ALPHA_CONTINUOUS_LEARNING_REGISTRY", "").strip()
    return Path(configured) if configured else DEFAULT_LEARNING_REGISTRY_PATH


def _observation_payload(item: OutcomeObservation) -> dict[str, object]:
    return {
        "observation_id": item.observation_id,
        "recommendation_id": item.recommendation_id,
        "observed_at": item.observed_at.isoformat(),
        "generated_at": item.generated_at.isoformat(),
        "symbol": item.symbol,
        "final_verdict": item.final_verdict,
        "predicted_confidence": item.predicted_confidence,
        "predicted_score": str(item.predicted_score),
        "setup_type": item.setup_type,
        "status": item.status.value,
        "entry_achieved": item.entry_achieved,
        "entry_missed": item.entry_missed,
        "stop_hit": item.stop_hit,
        "target_1_hit": item.target_1_hit,
        "target_2_hit": item.target_2_hit,
        "target_3_hit": item.target_3_hit,
        "time_exit": item.time_exit,
        "mfe_pct": _text(item.mfe_pct),
        "mae_pct": _text(item.mae_pct),
        "realised_return_pct": _text(item.realised_return_pct),
        "holding_period_days": item.holding_period_days,
        "market_regime": item.market_regime,
        "sector": item.sector,
        "volatility": _text(item.volatility),
        "liquidity": _text(item.liquidity),
        "source": item.source,
        "evidence_hash": item.evidence_hash,
        "production_influence": False,
    }


def _observation_from_payload(row: dict[str, Any]) -> OutcomeObservation:
    return OutcomeObservation(
        observation_id=str(row["observation_id"]),
        recommendation_id=str(row["recommendation_id"]),
        observed_at=datetime.fromisoformat(str(row["observed_at"])),
        generated_at=datetime.fromisoformat(str(row["generated_at"])),
        symbol=str(row["symbol"]),
        final_verdict=str(row["final_verdict"]),
        predicted_confidence=str(row["predicted_confidence"]),
        predicted_score=Decimal(str(row["predicted_score"])),
        setup_type=str(row["setup_type"]),
        status=LearningOutcomeStatus(str(row["status"])),
        entry_achieved=bool(row["entry_achieved"]),
        entry_missed=bool(row["entry_missed"]),
        stop_hit=bool(row["stop_hit"]),
        target_1_hit=bool(row["target_1_hit"]),
        target_2_hit=bool(row["target_2_hit"]),
        target_3_hit=bool(row["target_3_hit"]),
        time_exit=bool(row["time_exit"]),
        mfe_pct=_decimal(row.get("mfe_pct")),
        mae_pct=_decimal(row.get("mae_pct")),
        realised_return_pct=_decimal(row.get("realised_return_pct")),
        holding_period_days=(
            None
            if row.get("holding_period_days") is None
            else int(row["holding_period_days"])
        ),
        market_regime=_optional(row.get("market_regime")),
        sector=_optional(row.get("sector")),
        volatility=_decimal(row.get("volatility")),
        liquidity=_decimal(row.get("liquidity")),
        source=str(row["source"]),
        evidence_hash=str(row["evidence_hash"]),
        production_influence=bool(row.get("production_influence", False)),
    )


def _event_payload(item: LearningEvent) -> dict[str, object]:
    return {
        "event_id": item.event_id,
        "occurred_at": item.occurred_at.isoformat(),
        "recommendation_id": item.recommendation_id,
        "event_type": item.event_type,
        "learning": item.learning,
        "evidence": list(item.evidence),
        "confidence": item.confidence.value,
        "suggested_research": item.suggested_research,
        "source_observation_id": item.source_observation_id,
        "outcome": item.outcome,
        "production_influence": False,
    }


def _event_from_payload(row: dict[str, Any]) -> LearningEvent:
    evidence = row.get("evidence", [])
    return LearningEvent(
        event_id=str(row["event_id"]),
        occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
        recommendation_id=_optional(row.get("recommendation_id")),
        event_type=str(row["event_type"]),
        learning=str(row["learning"]),
        evidence=tuple(str(item) for item in evidence),
        confidence=LearningConfidence(str(row["confidence"])),
        suggested_research=_optional(row.get("suggested_research")),
        source_observation_id=_optional(row.get("source_observation_id")),
        outcome=_optional(row.get("outcome")),
        production_influence=bool(row.get("production_influence", False)),
    )


def _empty_payload() -> dict[str, Any]:
    return {
        "schema_version": CLL_SCHEMA_VERSION,
        "production_influence": False,
        "outcome_observations": [],
        "learning_events": [],
    }


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _legacy_event_matches(
    existing: dict[str, Any],
    current: dict[str, object],
) -> bool:
    if "outcome" in existing:
        return False
    legacy_current = dict(current)
    legacy_current.pop("outcome", None)
    return existing == legacy_current


def _decimal(value: object) -> Decimal | None:
    return None if value in {None, ""} else Decimal(str(value))


def _optional(value: object) -> str | None:
    return None if value in {None, ""} else str(value)


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "DEFAULT_LEARNING_REGISTRY_PATH",
    "ContinuousLearningRegistry",
    "resolve_learning_registry_path",
]
