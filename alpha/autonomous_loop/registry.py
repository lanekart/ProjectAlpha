from __future__ import annotations

import csv
import fcntl
import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from alpha.autonomous_loop.models import (
    AUTONOMOUS_LOOP_SCHEMA_VERSION,
    DecisionKind,
    DecisionMark,
    DecisionResolution,
    DNADriftAssessment,
    DriftState,
    ForwardDNACohort,
    ForwardDNAObservation,
    FrozenDecision,
    HypothesisStage,
    ImprovementHypothesis,
    LoopEvidenceClass,
    ResolutionKind,
    RunEvent,
    RunStage,
    ScheduleDefinition,
    UniverseDefinition,
    UniverseSource,
    ValidationEvent,
    ValidationGate,
    ValidationResult,
    mapping,
    optional_decimal,
    optional_text,
)
from alpha.forward_validation.models import PolicyVersion

DEFAULT_AUTONOMOUS_LOOP_REGISTRY = Path(".alpha/autonomous_loop/registry.json")


class AutonomousLoopIntegrityError(ValueError):
    """Raised when append-only autonomous evidence fails validation."""


class AutonomousLoopRegistry:
    """Atomic, append-only store for schedules, runs, decisions, and evidence."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_registry_path(path)

    def register_universe(self, universe: UniverseDefinition) -> bool:
        return self._append_immutable("universes", "universe_id", _jsonable(universe))

    def universes(self) -> tuple[UniverseDefinition, ...]:
        return tuple(
            sorted(
                (_universe(row) for row in self._rows("universes")),
                key=lambda item: item.universe_id,
            )
        )

    def require_universe(self, universe_id: str) -> UniverseDefinition:
        normalized = universe_id.strip().upper()
        match = next(
            (item for item in self.universes() if item.universe_id == normalized),
            None,
        )
        if match is None:
            raise KeyError(f"unknown autonomous universe: {normalized}")
        return match

    @contextmanager
    def execution_lock(self) -> Iterator[None]:
        """Serialize scheduler workers while retaining atomic append semantics."""

        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def register_schedule(self, schedule: ScheduleDefinition) -> bool:
        self.require_universe(schedule.universe_id)
        return self._append_immutable("schedules", "schedule_id", _jsonable(schedule))

    def schedules(self) -> tuple[ScheduleDefinition, ...]:
        return tuple(
            sorted(
                (_schedule(row) for row in self._rows("schedules")),
                key=lambda item: item.schedule_id,
            )
        )

    def require_schedule(self, schedule_id: str) -> ScheduleDefinition:
        normalized = schedule_id.strip().upper()
        match = next(
            (item for item in self.schedules() if item.schedule_id == normalized),
            None,
        )
        if match is None:
            raise KeyError(f"unknown autonomous schedule: {normalized}")
        return match

    def append_run_stage(
        self,
        *,
        run_id: str,
        schedule_id: str,
        scheduled_for: datetime,
        occurred_at: datetime,
        stage: RunStage,
        detail: str,
        metrics: dict[str, str] | None = None,
    ) -> RunEvent:
        scheduled_for = _utc(scheduled_for)
        occurred_at = _utc(occurred_at)
        repeatable = stage in {RunStage.RESUMED, RunStage.FAILED}
        existing = tuple(
            item
            for item in self.run_events()
            if item.run_id == run_id and item.stage is stage
        )
        semantic = {
            "run_id": run_id,
            "schedule_id": schedule_id,
            "scheduled_for": scheduled_for.isoformat(),
            "stage": stage.value,
            "detail": detail,
            "metrics": dict(sorted((metrics or {}).items())),
        }
        if existing and not repeatable:
            candidate = existing[0]
            if (
                candidate.schedule_id != schedule_id
                or candidate.scheduled_for != _datetime(semantic["scheduled_for"])
                or candidate.detail != detail
                or dict(candidate.metrics) != semantic["metrics"]
            ):
                raise AutonomousLoopIntegrityError(
                    f"immutable run-stage conflict: {run_id}/{stage.value}"
                )
            return candidate
        events = self.run_events()
        sequence = len(events) + 1
        previous_hash = events[-1].event_hash if events else "GENESIS"
        event_identity = (
            {**semantic, "occurred_at": occurred_at.isoformat()}
            if repeatable
            else semantic
        )
        event_id = sha256(canonical_json(event_identity).encode()).hexdigest()[:24]
        unhashed = {
            "sequence": sequence,
            "event_id": event_id,
            **semantic,
            "occurred_at": occurred_at.isoformat(),
            "previous_hash": previous_hash,
            "production_influence": False,
        }
        event_hash = sha256(canonical_json(unhashed).encode()).hexdigest()
        event = RunEvent(
            sequence=sequence,
            event_id=event_id,
            run_id=run_id,
            schedule_id=schedule_id,
            scheduled_for=scheduled_for,
            occurred_at=occurred_at,
            stage=stage,
            detail=detail,
            metrics=metrics or {},
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        self._append_row("run_events", _jsonable(event))
        return event

    def run_events(self) -> tuple[RunEvent, ...]:
        events = tuple(_run_event(row) for row in self._rows("run_events"))
        previous_hash = "GENESIS"
        for sequence, event in enumerate(events, start=1):
            if event.sequence != sequence or event.previous_hash != previous_hash:
                raise AutonomousLoopIntegrityError("run event chain is discontinuous")
            row = _jsonable(event)
            row.pop("event_hash")
            expected = sha256(canonical_json(row).encode()).hexdigest()
            if expected != event.event_hash:
                raise AutonomousLoopIntegrityError(
                    f"run event hash mismatch: {event.event_id}"
                )
            previous_hash = event.event_hash
        return events

    def stages_for(self, run_id: str) -> frozenset[RunStage]:
        return frozenset(
            item.stage for item in self.run_events() if item.run_id == run_id
        )

    def append_decisions(self, decisions: tuple[FrozenDecision, ...]) -> int:
        return self._append_typed(
            key="decisions",
            identity="decision_id",
            values=decisions,
            validator=_validate_decision_hash,
        )

    def decisions(self) -> tuple[FrozenDecision, ...]:
        decisions = tuple(_decision(row) for row in self._rows("decisions"))
        for item in decisions:
            _validate_decision_hash(item)
        return tuple(
            sorted(decisions, key=lambda item: (item.generated_at, item.decision_id))
        )

    def append_marks(self, marks: tuple[DecisionMark, ...]) -> int:
        return self._append_typed(
            key="decision_marks",
            identity="mark_id",
            values=marks,
        )

    def marks(self) -> tuple[DecisionMark, ...]:
        return tuple(
            sorted(
                (_mark(row) for row in self._rows("decision_marks")),
                key=lambda item: (item.observed_on, item.mark_id),
            )
        )

    def append_resolutions(self, resolutions: tuple[DecisionResolution, ...]) -> int:
        return self._append_typed(
            key="decision_resolutions",
            identity="resolution_id",
            values=resolutions,
        )

    def resolutions(self) -> tuple[DecisionResolution, ...]:
        return tuple(
            sorted(
                (_resolution(row) for row in self._rows("decision_resolutions")),
                key=lambda item: (item.resolved_at, item.resolution_id),
            )
        )

    def append_forward_dna(
        self, observations: tuple[ForwardDNAObservation, ...]
    ) -> int:
        if any(
            item.evidence_class is not LoopEvidenceClass.FORWARD_OBSERVED
            for item in observations
        ):
            raise AutonomousLoopIntegrityError(
                "forward DNA cannot accept reconstructed evidence"
            )
        return self._append_typed(
            key="forward_dna",
            identity="observation_id",
            values=observations,
        )

    def forward_dna(self) -> tuple[ForwardDNAObservation, ...]:
        return tuple(
            sorted(
                (_dna(row) for row in self._rows("forward_dna")),
                key=lambda item: (item.observed_at, item.observation_id),
            )
        )

    def append_dna_drifts(self, assessments: tuple[DNADriftAssessment, ...]) -> int:
        return self._append_typed(
            key="dna_drift",
            identity="drift_id",
            values=assessments,
        )

    def dna_drifts(self) -> tuple[DNADriftAssessment, ...]:
        return tuple(
            sorted(
                (_dna_drift(row) for row in self._rows("dna_drift")),
                key=lambda item: item.drift_id,
            )
        )

    def append_hypotheses(self, hypotheses: tuple[ImprovementHypothesis, ...]) -> int:
        return self._append_typed(
            key="hypotheses",
            identity="hypothesis_id",
            values=hypotheses,
        )

    def hypotheses(self) -> tuple[ImprovementHypothesis, ...]:
        return tuple(
            sorted(
                (_hypothesis(row) for row in self._rows("hypotheses")),
                key=lambda item: (item.created_at, item.hypothesis_id),
            )
        )

    def append_validations(self, events: tuple[ValidationEvent, ...]) -> int:
        return self._append_typed(
            key="validation_events",
            identity="validation_id",
            values=events,
        )

    def validation_events(self) -> tuple[ValidationEvent, ...]:
        return tuple(
            sorted(
                (_validation(row) for row in self._rows("validation_events")),
                key=lambda item: (item.occurred_at, item.validation_id),
            )
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
        rows: list[dict[str, str]] = []
        for key in (
            "run_events",
            "decisions",
            "decision_marks",
            "decision_resolutions",
            "forward_dna",
            "dna_drift",
            "hypotheses",
            "validation_events",
        ):
            rows.extend(
                {
                    "record_type": key,
                    "record_id": _record_id(row),
                    "payload": canonical_json(row),
                    "production_influence": "false",
                }
                for row in self._rows(key)
            )
        with destination.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "record_type",
                    "record_id",
                    "payload",
                    "production_influence",
                ),
            )
            writer.writeheader()
            writer.writerows(rows)
        return destination

    def _append_typed(
        self,
        *,
        key: str,
        identity: str,
        values: tuple[object, ...],
        validator: object | None = None,
    ) -> int:
        rows = self._rows(key)
        by_id = {str(row.get(identity)): row for row in rows}
        inserted = 0
        for value in values:
            if validator is not None:
                assert callable(validator)
                validator(value)
            row = _jsonable(value)
            record_id = str(row[identity])
            existing = by_id.get(record_id)
            if existing is not None:
                if existing != row:
                    raise AutonomousLoopIntegrityError(
                        f"immutable {key} conflict: {record_id}"
                    )
                continue
            rows.append(row)
            by_id[record_id] = row
            inserted += 1
        if inserted:
            payload = self._read()
            payload[key] = rows
            self._write(payload)
        return inserted

    def _append_immutable(self, key: str, identity: str, row: dict[str, Any]) -> bool:
        return bool(
            self._append_typed(
                key=key,
                identity=identity,
                values=(_MappingRecord(row),),
            )
        )

    def _append_row(self, key: str, row: dict[str, Any]) -> None:
        payload = self._read()
        rows = _dict_rows(payload.get(key))
        rows.append(row)
        payload[key] = rows
        self._write(payload)

    def _rows(self, key: str) -> list[dict[str, Any]]:
        return _dict_rows(self._read().get(key))

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_payload()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise AutonomousLoopIntegrityError("autonomous registry must be an object")
        if payload.get("production_influence") is not False:
            raise AutonomousLoopIntegrityError(
                "autonomous registry must remain research-only"
            )
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        payload["schema_version"] = AUTONOMOUS_LOOP_SCHEMA_VERSION
        payload["production_influence"] = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


class _MappingRecord:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload


def resolve_registry_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.getenv("ALPHA_AUTONOMOUS_LOOP_REGISTRY", "").strip()
    return Path(configured) if configured else DEFAULT_AUTONOMOUS_LOOP_REGISTRY


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _empty_payload() -> dict[str, object]:
    return {
        "schema_version": AUTONOMOUS_LOOP_SCHEMA_VERSION,
        "production_influence": False,
        "universes": [],
        "schedules": [],
        "run_events": [],
        "decisions": [],
        "decision_marks": [],
        "decision_resolutions": [],
        "forward_dna": [],
        "dna_drift": [],
        "hypotheses": [],
        "validation_events": [],
    }


def _jsonable(value: object) -> dict[str, Any]:
    if isinstance(value, _MappingRecord):
        return dict(value.payload)
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("registry values must be dataclass instances")
    return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}


def _json_value(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, PolicyVersion):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _universe(row: dict[str, Any]) -> UniverseDefinition:
    return UniverseDefinition(
        universe_id=str(row["universe_id"]),
        source=UniverseSource(str(row["source"])),
        symbols=tuple(str(item) for item in row.get("symbols", [])),
        version=str(row.get("version", "universe-v1")),
        production_influence=bool(row.get("production_influence", False)),
    )


def _schedule(row: dict[str, Any]) -> ScheduleDefinition:
    return ScheduleDefinition(
        schedule_id=str(row["schedule_id"]),
        universe_id=str(row["universe_id"]),
        local_time=time.fromisoformat(str(row["local_time"])),
        timezone=str(row["timezone"]),
        weekdays=tuple(int(item) for item in row.get("weekdays", [])),
        policy_version=PolicyVersion(str(row["policy_version"])),
        shadow_initial_capital=Decimal(str(row["shadow_initial_capital"])),
        maximum_data_age_days=int(row.get("maximum_data_age_days", 3)),
        markout_horizon_bars=int(row.get("markout_horizon_bars", 20)),
        enabled=bool(row.get("enabled", True)),
        version=str(row.get("version", "schedule-v1")),
        production_influence=bool(row.get("production_influence", False)),
    )


def _run_event(row: dict[str, Any]) -> RunEvent:
    return RunEvent(
        sequence=int(row["sequence"]),
        event_id=str(row["event_id"]),
        run_id=str(row["run_id"]),
        schedule_id=str(row["schedule_id"]),
        scheduled_for=_datetime(row["scheduled_for"]),
        occurred_at=_datetime(row["occurred_at"]),
        stage=RunStage(str(row["stage"])),
        detail=str(row["detail"]),
        metrics={
            str(key): str(value) for key, value in mapping(row.get("metrics")).items()
        },
        previous_hash=str(row["previous_hash"]),
        event_hash=str(row["event_hash"]),
        production_influence=bool(row.get("production_influence", False)),
    )


def _decision(row: dict[str, Any]) -> FrozenDecision:
    return FrozenDecision(
        decision_id=str(row["decision_id"]),
        run_id=str(row["run_id"]),
        schedule_id=str(row["schedule_id"]),
        universe_id=str(row["universe_id"]),
        recommendation_id=optional_text(row.get("recommendation_id")),
        generated_at=_datetime(row["generated_at"]),
        observed_on=date.fromisoformat(str(row["observed_on"])),
        symbol=str(row["symbol"]),
        decision_kind=DecisionKind(str(row["decision_kind"])),
        final_verdict=str(row["final_verdict"]),
        reference_price=optional_decimal(row.get("reference_price")),
        approved_deployment=optional_decimal(row.get("approved_deployment")),
        policy_version=PolicyVersion(str(row["policy_version"])),
        markout_horizon_bars=int(row["markout_horizon_bars"]),
        reasons=tuple(str(item) for item in row.get("reasons", [])),
        feature_snapshot={
            str(key): str(value)
            for key, value in mapping(row.get("feature_snapshot")).items()
        },
        evidence_hashes={
            str(key): str(value)
            for key, value in mapping(row.get("evidence_hashes")).items()
        },
        evidence_class=LoopEvidenceClass(str(row["evidence_class"])),
        artifact_hash=str(row["artifact_hash"]),
        production_influence=bool(row.get("production_influence", False)),
    )


def _mark(row: dict[str, Any]) -> DecisionMark:
    return DecisionMark(
        mark_id=str(row["mark_id"]),
        decision_id=str(row["decision_id"]),
        symbol=str(row["symbol"]),
        observed_on=date.fromisoformat(str(row["observed_on"])),
        close_price=Decimal(str(row["close_price"])),
        high_price=Decimal(str(row["high_price"])),
        low_price=Decimal(str(row["low_price"])),
        return_pct=Decimal(str(row["return_pct"])),
        favorable_excursion_pct=Decimal(str(row["favorable_excursion_pct"])),
        adverse_excursion_pct=Decimal(str(row["adverse_excursion_pct"])),
        source_hash=str(row["source_hash"]),
        production_influence=bool(row.get("production_influence", False)),
    )


def _resolution(row: dict[str, Any]) -> DecisionResolution:
    return DecisionResolution(
        resolution_id=str(row["resolution_id"]),
        decision_id=str(row["decision_id"]),
        resolved_at=_datetime(row["resolved_at"]),
        resolution_kind=ResolutionKind(str(row["resolution_kind"])),
        realised_return_pct=Decimal(str(row["realised_return_pct"])),
        maximum_favorable_excursion_pct=Decimal(
            str(row["maximum_favorable_excursion_pct"])
        ),
        maximum_adverse_excursion_pct=Decimal(
            str(row["maximum_adverse_excursion_pct"])
        ),
        bars_observed=int(row["bars_observed"]),
        reason=str(row["reason"]),
        terminal_mark_id=str(row["terminal_mark_id"]),
        production_influence=bool(row.get("production_influence", False)),
    )


def _dna(row: dict[str, Any]) -> ForwardDNAObservation:
    return ForwardDNAObservation(
        observation_id=str(row["observation_id"]),
        decision_id=str(row["decision_id"]),
        recommendation_id=optional_text(row.get("recommendation_id")),
        observed_at=_datetime(row["observed_at"]),
        symbol=str(row["symbol"]),
        cohort=ForwardDNACohort(str(row["cohort"])),
        realised_return_pct=Decimal(str(row["realised_return_pct"])),
        features={
            str(key): str(value) for key, value in mapping(row.get("features")).items()
        },
        source_resolution_id=str(row["source_resolution_id"]),
        evidence_class=LoopEvidenceClass(
            str(row.get("evidence_class", "FORWARD_OBSERVED"))
        ),
        production_influence=bool(row.get("production_influence", False)),
    )


def _dna_drift(row: dict[str, Any]) -> DNADriftAssessment:
    return DNADriftAssessment(
        drift_id=str(row["drift_id"]),
        cohort=ForwardDNACohort(str(row["cohort"])),
        baseline_count=int(row["baseline_count"]),
        recent_count=int(row["recent_count"]),
        baseline_prevalence_pct=optional_decimal(row.get("baseline_prevalence_pct")),
        recent_prevalence_pct=optional_decimal(row.get("recent_prevalence_pct")),
        change_pct_points=optional_decimal(row.get("change_pct_points")),
        state=DriftState(str(row["state"])),
        evidence_ids=tuple(str(item) for item in row.get("evidence_ids", [])),
        explanation=str(row["explanation"]),
        production_influence=bool(row.get("production_influence", False)),
    )


def _hypothesis(row: dict[str, Any]) -> ImprovementHypothesis:
    return ImprovementHypothesis(
        hypothesis_id=str(row["hypothesis_id"]),
        created_at=_datetime(row["created_at"]),
        title=str(row["title"]),
        subsystem=str(row["subsystem"]),
        statement=str(row["statement"]),
        evidence_ids=tuple(str(item) for item in row.get("evidence_ids", [])),
        limitations=tuple(str(item) for item in row.get("limitations", [])),
        stage=HypothesisStage(str(row["stage"])),
        production_influence=bool(row.get("production_influence", False)),
    )


def _validation(row: dict[str, Any]) -> ValidationEvent:
    return ValidationEvent(
        validation_id=str(row["validation_id"]),
        hypothesis_id=str(row["hypothesis_id"]),
        occurred_at=_datetime(row["occurred_at"]),
        gate=ValidationGate(str(row["gate"])),
        result=ValidationResult(str(row["result"])),
        evidence_artifact_id=str(row["evidence_artifact_id"]),
        explanation=str(row["explanation"]),
        actor=str(row["actor"]),
        production_influence=bool(row.get("production_influence", False)),
    )


def _validate_decision_hash(value: object) -> None:
    if not isinstance(value, FrozenDecision):
        raise TypeError("frozen decision required")
    row = _jsonable(value)
    actual = str(row.pop("artifact_hash"))
    expected = sha256(canonical_json(row).encode()).hexdigest()
    if actual != expected:
        raise AutonomousLoopIntegrityError(
            f"decision artifact hash mismatch: {value.decision_id}"
        )


def _datetime(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _record_id(row: dict[str, Any]) -> str:
    for key in (
        "event_id",
        "decision_id",
        "mark_id",
        "resolution_id",
        "observation_id",
        "drift_id",
        "hypothesis_id",
        "validation_id",
    ):
        if key in row:
            return str(row[key])
    return "unavailable"


__all__ = [
    "DEFAULT_AUTONOMOUS_LOOP_REGISTRY",
    "AutonomousLoopIntegrityError",
    "AutonomousLoopRegistry",
    "canonical_json",
    "resolve_registry_path",
]
