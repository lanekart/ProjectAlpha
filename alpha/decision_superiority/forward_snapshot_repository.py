"""Append-only content-addressed repository for DSI-006 evidence."""

from __future__ import annotations

import csv
import json
import os
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import MappingProxyType
from typing import Any

from alpha.decision_superiority.forward_snapshot_models import (
    ForwardSnapshotError,
    OutcomeEvent,
    OutcomeEventType,
    RepositoryDisposition,
    SnapshotIndexRow,
)
from alpha.decision_superiority.historical_rehydration import (
    canonical_json,
    stable_sha256,
)
from alpha.decision_superiority.recommendation_snapshot_recorder import (
    CanonicalRecommendationSnapshotRecorder,
    validate_snapshot_package,
)
from alpha.portfolio_intelligence import CapitalAllocationPlan
from alpha.recommendation_intelligence import RecommendationReport

_MINIMUM_FREE_BYTES = 1_048_576
_TERMINAL_EVENTS = frozenset(
    {
        OutcomeEventType.ENTRY_NOT_TRIGGERED,
        OutcomeEventType.OUTCOME_COMPLETED,
        OutcomeEventType.OUTCOME_INVALIDATED,
    }
)


class ContentAddressedSnapshotRepository:
    """Publish immutable DSI-005 packages and outcome events atomically."""

    def __init__(self, root: Path, *, minimum_free_bytes: int = _MINIMUM_FREE_BYTES):
        if minimum_free_bytes < 0:
            raise ForwardSnapshotError("MINIMUM_FREE_BYTES_INVALID")
        self.root = _safe_root(root)
        self.packages = self.root / "packages"
        self.events = self.root / "events"
        self.temporary = self.root / ".temporary"
        self.index_path = self.root / "snapshot_index.csv"
        self.minimum_free_bytes = minimum_free_bytes

    def publish_package(self, source: Path) -> RepositoryDisposition:
        """Validate and atomically publish one package without overwrite."""

        payload = validate_snapshot_package(source)
        package_sha = str(payload["package_sha256"])
        encoded = canonical_json(payload) + "\n"
        self._preflight(len(encoded.encode("utf-8")))
        if self.package_paths() and not self.index_path.exists():
            self.rebuild_index()
        existing_rows = self.index_rows()
        candidate_arm_ids = _derived_candidate_arm_ids(payload)
        target = self.packages / f"{package_sha}.json"
        if target.exists():
            if target.read_text(encoding="utf-8") != encoded:
                raise ForwardSnapshotError("CONFLICTING_MANIFEST")
            return RepositoryDisposition.IDENTICAL
        for row in existing_rows:
            if row.candidate_arm_id in candidate_arm_ids:
                raise ForwardSnapshotError("CONFLICTING_CAPTURE_FOR_SAME_CANDIDATE_ARM")

        self.packages.mkdir(parents=True, exist_ok=True)
        self.temporary.mkdir(parents=True, exist_ok=True)
        temporary = self._temporary_file(encoded)
        try:
            if canonical_json(validate_snapshot_package(temporary)) + "\n" != encoded:
                raise ForwardSnapshotError("PACKAGE_HASH_DEFECT")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        self.rebuild_index()
        return RepositoryDisposition.NEW

    def package_paths(self) -> tuple[Path, ...]:
        """Return immutable packages in stable content-address order."""

        if not self.packages.exists():
            return ()
        return tuple(sorted(self.packages.glob("*.json"), key=lambda item: item.name))

    def index_rows(self) -> tuple[SnapshotIndexRow, ...]:
        """Load and validate the deterministic package index."""

        if not self.index_path.exists():
            return ()
        with self.index_path.open("r", encoding="utf-8", newline="") as handle:
            rows = tuple(
                SnapshotIndexRow(
                    session_id=row["session_id"],
                    session_date=date.fromisoformat(row["session_date"]),
                    package_sha256=row["package_sha256"],
                    package_path=row["package_path"],
                    economic_candidate_id=row["economic_candidate_id"],
                    candidate_arm_id=row["candidate_arm_id"],
                    recommendation_object_id=row["recommendation_object_id"],
                    complete_stack_baseline_id=row["complete_stack_baseline_id"],
                    recorded_plan_id=row["recorded_plan_id"],
                    outcome_stream_id=row["outcome_stream_id"],
                    symbol=row["symbol"],
                    verdict=row["verdict"],
                    price_arm=row["price_arm"],
                    policy_hash=row["policy_hash"],
                )
                for row in csv.DictReader(handle)
            )
        expected = self._derived_index_rows()
        if rows != expected:
            raise ForwardSnapshotError("CAPTURE_INDEX_RECONCILIATION_DEFECT")
        return rows

    def rebuild_index(self) -> tuple[SnapshotIndexRow, ...]:
        """Deterministically rebuild the index from immutable packages."""

        rows = self._derived_index_rows()
        self.root.mkdir(parents=True, exist_ok=True)
        fields = tuple(SnapshotIndexRow.__dataclass_fields__)
        content = _csv_text(
            fields,
            (
                {
                    key: (value.isoformat() if isinstance(value, date) else str(value))
                    for key, value in asdict(row).items()
                }
                for row in rows
            ),
        )
        _atomic_text(self.index_path, content)
        return rows

    def append_outcome_event(
        self,
        *,
        candidate_arm_id: str,
        event_type: OutcomeEventType,
        observation_date: date,
        effective_date: date,
        completion_date: date | None,
        source_lineage: str,
        source_hash: str,
        payload: Mapping[str, object] | None = None,
        predecessor_event_id: str | None = None,
    ) -> tuple[OutcomeEvent, RepositoryDisposition]:
        """Append one immutable event linked to an indexed candidate arm."""

        rows = tuple(
            row for row in self.index_rows() if row.candidate_arm_id == candidate_arm_id
        )
        if len(rows) != 1:
            raise ForwardSnapshotError("OUTCOME_EVENT_CANDIDATE_IDENTITY_DEFECT")
        row = rows[0]
        if observation_date < row.session_date or effective_date < row.session_date:
            raise ForwardSnapshotError("POINT_IN_TIME_OUTCOME_LEAKAGE")
        if (
            event_type in _TERMINAL_EVENTS
            and completion_date is not None
            and completion_date <= row.session_date
        ):
            raise ForwardSnapshotError("SAME_DATE_TERMINAL_OUTCOME_INVALID")
        existing = self.outcome_events(candidate_arm_id=candidate_arm_id)
        if predecessor_event_id is not None and all(
            item.event_id != predecessor_event_id for item in existing
        ):
            raise ForwardSnapshotError("OUTCOME_EVENT_PREDECESSOR_MISSING")
        terminal = tuple(
            item for item in existing if item.event_type in _TERMINAL_EVENTS
        )
        if terminal and event_type in _TERMINAL_EVENTS:
            if event_type is not OutcomeEventType.OUTCOME_CORRECTION:
                raise ForwardSnapshotError("CONFLICTING_OUTCOME_EVENTS")
        normalized_payload = dict(sorted((payload or {}).items()))
        payload_hash = stable_sha256(normalized_payload)
        body: dict[str, object] = {
            "economic_candidate_id": row.economic_candidate_id,
            "candidate_arm_id": row.candidate_arm_id,
            "snapshot_package_sha256": row.package_sha256,
            "recorded_plan_id": row.recorded_plan_id,
            "event_type": event_type.value,
            "observation_date": observation_date.isoformat(),
            "effective_date": effective_date.isoformat(),
            "completion_date": (
                None if completion_date is None else completion_date.isoformat()
            ),
            "source_lineage": source_lineage,
            "source_hash": source_hash,
            "point_in_time_eligible": True,
            "payload": normalized_payload,
            "payload_hash": payload_hash,
            "predecessor_event_id": predecessor_event_id,
        }
        event_id = stable_sha256(body)
        event = OutcomeEvent(
            event_id=event_id,
            economic_candidate_id=row.economic_candidate_id,
            candidate_arm_id=row.candidate_arm_id,
            snapshot_package_sha256=row.package_sha256,
            recorded_plan_id=row.recorded_plan_id,
            event_type=event_type,
            observation_date=observation_date,
            effective_date=effective_date,
            completion_date=completion_date,
            source_lineage=source_lineage,
            source_hash=source_hash,
            point_in_time_eligible=True,
            payload=MappingProxyType(normalized_payload),
            payload_hash=payload_hash,
            predecessor_event_id=predecessor_event_id,
        )
        self.events.mkdir(parents=True, exist_ok=True)
        target = self.events / f"{event_id}.json"
        encoded = canonical_json({"event_id": event_id, **body}) + "\n"
        if target.exists():
            if target.read_text(encoding="utf-8") != encoded:
                raise ForwardSnapshotError("CONFLICTING_OUTCOME_EVENT_IDENTITY")
            return event, RepositoryDisposition.IDENTICAL
        _atomic_text(target, encoded, exclusive=True)
        return event, RepositoryDisposition.NEW

    def outcome_events(
        self,
        *,
        candidate_arm_id: str | None = None,
    ) -> tuple[OutcomeEvent, ...]:
        """Load and hash-validate immutable outcome events."""

        if not self.events.exists():
            return ()
        result: list[OutcomeEvent] = []
        for path in sorted(self.events.glob("*.json"), key=lambda item: item.name):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ForwardSnapshotError("OUTCOME_EVENT_READ_FAILED") from exc
            if not isinstance(data, dict):
                raise ForwardSnapshotError("OUTCOME_EVENT_OBJECT_REQUIRED")
            event_id = str(data.pop("event_id", ""))
            if stable_sha256(data) != event_id or path.stem != event_id:
                raise ForwardSnapshotError("OUTCOME_EVENT_TAMPERED")
            if stable_sha256(data.get("payload", {})) != data.get("payload_hash"):
                raise ForwardSnapshotError("OUTCOME_EVENT_PAYLOAD_TAMPERED")
            event = _event_from_payload(event_id, data)
            if candidate_arm_id is None or event.candidate_arm_id == candidate_arm_id:
                result.append(event)
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    item.effective_date,
                    item.event_type.value,
                    item.event_id,
                ),
            )
        )

    def verify_inventory(self) -> MappingProxyType[str, int]:
        """Validate every package and event and reconcile the package index."""

        packages = self.package_paths()
        for path in packages:
            payload = validate_snapshot_package(path)
            if path.read_text(encoding="utf-8") != canonical_json(payload) + "\n":
                raise ForwardSnapshotError("PACKAGE_CANONICAL_BYTES_MISMATCH")
            if path.stem != payload["package_sha256"]:
                raise ForwardSnapshotError("PACKAGE_FILENAME_HASH_MISMATCH")
        rows = self.rebuild_index()
        events = self.outcome_events()
        return MappingProxyType(
            {
                "package_count": len(packages),
                "index_row_count": len(rows),
                "event_count": len(events),
            }
        )

    def recover_stale_temporary_files(self) -> int:
        """Remove unpublished temporary files without touching evidence."""

        if not self.temporary.exists():
            return 0
        stale = tuple(path for path in self.temporary.iterdir() if path.is_file())
        for path in stale:
            path.unlink()
        return len(stale)

    def _derived_index_rows(self) -> tuple[SnapshotIndexRow, ...]:
        rows: list[SnapshotIndexRow] = []
        for path in self.package_paths():
            payload = validate_snapshot_package(path)
            observed_on = date.fromisoformat(str(payload["observed_on"]))
            recommendations = _mapping_list(payload, "recommendations")
            fingerprints = _string_list(payload, "recommendation_fingerprints")
            recommendation_ids = _string_list(payload, "recommendation_object_ids")
            plan_ids = _string_list(payload, "recorded_plan_ids")
            outcome_ids = _string_list(payload, "outcome_link_ids")
            candidate_arm_ids = _string_list(payload, "candidate_arm_ids")
            lengths = {
                len(recommendations),
                len(fingerprints),
                len(recommendation_ids),
                len(plan_ids),
                len(outcome_ids),
                len(candidate_arm_ids),
            }
            if len(lengths) != 1:
                raise ForwardSnapshotError("SNAPSHOT_PACKAGE_IDENTITY_LENGTH_MISMATCH")
            policy_hash = str(payload["policy_hash"])
            session_id = stable_sha256(
                {
                    "observed_on": observed_on.isoformat(),
                    "capture_id": payload["capture_id"],
                    "policy_hash": policy_hash,
                }
            )
            price_arms = _string_list(payload, "price_arms")
            default_arm = price_arms[0] if len(price_arms) == 1 else "MIXED"
            for index, recommendation in enumerate(recommendations):
                symbol = str(recommendation.get("symbol", "")).strip().upper()
                if not symbol:
                    raise ForwardSnapshotError("SNAPSHOT_RECOMMENDATION_SYMBOL_MISSING")
                price_arm = str(
                    _metadata(recommendation).get("price_view", default_arm)
                ).upper()
                economic_id = stable_sha256(
                    {
                        "symbol": symbol,
                        "observed_on": observed_on.isoformat(),
                        "policy_hash": policy_hash,
                    }
                )
                arm_id = stable_sha256(
                    {
                        "economic_candidate_id": economic_id,
                        "price_arm": price_arm,
                        "recommendation_fingerprint": fingerprints[index],
                    }
                )
                rows.append(
                    SnapshotIndexRow(
                        session_id=session_id,
                        session_date=observed_on,
                        package_sha256=str(payload["package_sha256"]),
                        package_path=f"packages/{path.name}",
                        economic_candidate_id=economic_id,
                        candidate_arm_id=arm_id,
                        recommendation_object_id=recommendation_ids[index],
                        complete_stack_baseline_id=str(
                            payload["complete_stack_baseline_id"]
                        ),
                        recorded_plan_id=plan_ids[index],
                        outcome_stream_id=stable_sha256(
                            {
                                "economic_candidate_id": economic_id,
                                "candidate_arm_id": arm_id,
                                "recorded_plan_id": plan_ids[index],
                            }
                        ),
                        symbol=symbol,
                        verdict=_verdict(recommendation),
                        price_arm=price_arm,
                        policy_hash=policy_hash,
                    )
                )
        return tuple(
            sorted(
                rows,
                key=lambda item: (
                    item.session_date,
                    item.economic_candidate_id,
                    item.price_arm,
                    item.candidate_arm_id,
                ),
            )
        )

    def _preflight(self, incoming_bytes: int) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not os.access(self.root, os.W_OK):
            raise ForwardSnapshotError("CAPTURE_ROOT_NOT_WRITABLE")
        free = shutil.disk_usage(self.root).free
        if free < self.minimum_free_bytes + incoming_bytes:
            raise ForwardSnapshotError("CAPTURE_DISK_SPACE_PREFLIGHT_FAILED")

    def _temporary_file(self, content: str) -> Path:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=self.temporary,
            prefix="package-",
            suffix=".json",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            return Path(handle.name)


class GovernedForwardSnapshotRecorder:
    """Adapt DSI-005 capture to the DSI-006 content-addressed repository."""

    def __init__(self, repository: ContentAddressedSnapshotRepository) -> None:
        self.repository = repository
        self._staging = repository.root / ".recorder-staging"
        self._delegate = CanonicalRecommendationSnapshotRecorder(self._staging)
        self._dispositions: dict[str, RepositoryDisposition] = {}
        self._package_hashes: dict[str, str] = {}

    def begin_capture(self, *, observed_on: date, inputs: object) -> str:
        from alpha.application.intelligence_inputs import IntelligenceInputSet

        if not isinstance(inputs, IntelligenceInputSet):
            raise ForwardSnapshotError("FORWARD_CAPTURE_INPUT_TYPE_INVALID")
        return self._delegate.begin_capture(observed_on=observed_on, inputs=inputs)

    def capture_recommendations(
        self,
        *,
        capture_id: str,
        recommendations: tuple[RecommendationReport, ...],
    ) -> None:
        self._delegate.capture_recommendations(
            capture_id=capture_id,
            recommendations=recommendations,
        )

    def complete_capture(
        self,
        *,
        capture_id: str,
        recommendations: tuple[RecommendationReport, ...],
        institutional_evaluation: object | None,
        allocation_plan: CapitalAllocationPlan,
    ) -> None:
        self._delegate.complete_capture(
            capture_id=capture_id,
            recommendations=recommendations,
            institutional_evaluation=institutional_evaluation,
            allocation_plan=allocation_plan,
        )
        source = self._delegate.package_path(capture_id)
        payload = validate_snapshot_package(source)
        try:
            disposition = self.repository.publish_package(source)
        finally:
            source.unlink(missing_ok=True)
            if self._staging.exists() and not any(self._staging.iterdir()):
                self._staging.rmdir()
        self._dispositions[capture_id] = disposition
        self._package_hashes[capture_id] = str(payload["package_sha256"])

    def disposition(self, capture_id: str) -> RepositoryDisposition | None:
        return self._dispositions.get(capture_id)

    def package_sha256(self, capture_id: str) -> str | None:
        return self._package_hashes.get(capture_id)


def _safe_root(path: Path) -> Path:
    if not str(path).strip():
        raise ForwardSnapshotError("CAPTURE_ROOT_REQUIRED")
    if ".." in path.parts:
        raise ForwardSnapshotError("CAPTURE_PATH_TRAVERSAL_REJECTED")
    resolved = path.expanduser().resolve()
    if resolved == Path(resolved.anchor):
        raise ForwardSnapshotError("CAPTURE_ROOT_TOO_BROAD")
    return resolved


def _atomic_text(path: Path, content: str, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise ForwardSnapshotError("IMMUTABLE_ARTIFACT_ALREADY_EXISTS")
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        if exclusive and path.exists():
            raise ForwardSnapshotError("IMMUTABLE_ARTIFACT_ALREADY_EXISTS")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _csv_text(
    fields: tuple[str, ...],
    rows: Iterable[Mapping[str, object]],
) -> str:
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def _string_list(payload: Mapping[str, object], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise ForwardSnapshotError(f"SNAPSHOT_LIST_REQUIRED:{name}")
    return tuple(str(item) for item in value)


def _mapping_list(
    payload: Mapping[str, object],
    name: str,
) -> tuple[dict[str, object], ...]:
    value = payload.get(name)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ForwardSnapshotError(f"SNAPSHOT_MAPPING_LIST_REQUIRED:{name}")
    return tuple(dict(item) for item in value)


def _metadata(recommendation: Mapping[str, object]) -> Mapping[str, object]:
    value = recommendation.get("metadata")
    return value if isinstance(value, dict) else {}


def _derived_candidate_arm_ids(
    payload: Mapping[str, object],
) -> frozenset[str]:
    recommendations = _mapping_list(payload, "recommendations")
    fingerprints = _string_list(payload, "recommendation_fingerprints")
    if len(recommendations) != len(fingerprints):
        raise ForwardSnapshotError("SNAPSHOT_PACKAGE_IDENTITY_LENGTH_MISMATCH")
    observed_on = str(payload["observed_on"])
    policy_hash = str(payload["policy_hash"])
    price_arms = _string_list(payload, "price_arms")
    default_arm = price_arms[0] if len(price_arms) == 1 else "MIXED"
    result: set[str] = set()
    for index, recommendation in enumerate(recommendations):
        symbol = str(recommendation.get("symbol", "")).strip().upper()
        price_arm = str(
            _metadata(recommendation).get("price_view", default_arm)
        ).upper()
        economic_id = stable_sha256(
            {
                "symbol": symbol,
                "observed_on": observed_on,
                "policy_hash": policy_hash,
            }
        )
        result.add(
            stable_sha256(
                {
                    "economic_candidate_id": economic_id,
                    "price_arm": price_arm,
                    "recommendation_fingerprint": fingerprints[index],
                }
            )
        )
    return frozenset(result)


def _verdict(recommendation: Mapping[str, object]) -> str:
    for key in ("final_signal", "decision", "action"):
        value = recommendation.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return "UNKNOWN"


def _event_from_payload(
    event_id: str,
    data: Mapping[str, Any],
) -> OutcomeEvent:
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise ForwardSnapshotError("OUTCOME_EVENT_PAYLOAD_OBJECT_REQUIRED")
    return OutcomeEvent(
        event_id=event_id,
        economic_candidate_id=str(data["economic_candidate_id"]),
        candidate_arm_id=str(data["candidate_arm_id"]),
        snapshot_package_sha256=str(data["snapshot_package_sha256"]),
        recorded_plan_id=str(data["recorded_plan_id"]),
        event_type=OutcomeEventType(str(data["event_type"])),
        observation_date=date.fromisoformat(str(data["observation_date"])),
        effective_date=date.fromisoformat(str(data["effective_date"])),
        completion_date=(
            None
            if data.get("completion_date") is None
            else date.fromisoformat(str(data["completion_date"]))
        ),
        source_lineage=str(data["source_lineage"]),
        source_hash=str(data["source_hash"]),
        point_in_time_eligible=bool(data["point_in_time_eligible"]),
        payload=MappingProxyType(dict(sorted(payload.items()))),
        payload_hash=str(data["payload_hash"]),
        predecessor_event_id=(
            None
            if data.get("predecessor_event_id") is None
            else str(data["predecessor_event_id"])
        ),
    )


__all__ = [
    "ContentAddressedSnapshotRepository",
    "GovernedForwardSnapshotRecorder",
]
