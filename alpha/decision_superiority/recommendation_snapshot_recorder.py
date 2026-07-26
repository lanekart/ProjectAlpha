"""Append-only canonical recommendation snapshot recorder for DSI-005."""

from __future__ import annotations

import inspect
import json
import types
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Union, get_args, get_origin, get_type_hints

from alpha.application.intelligence_inputs import IntelligenceInputSet
from alpha.decision_superiority.historical_rehydration import (
    canonical_json,
    stable_sha256,
)
from alpha.decision_superiority.recommendation_snapshot_retention_models import (
    SNAPSHOT_PACKAGE_VERSION,
    CaptureDisposition,
    ReplayRetentionError,
)
from alpha.portfolio_intelligence import CapitalAllocationPlan
from alpha.recommendation_intelligence import RecommendationEngine, RecommendationReport

_SENSITIVE_KEYS = (
    "access_token",
    "api_key",
    "authorization_code",
    "client_secret",
    "password",
    "refresh_token",
)


@dataclass(slots=True)
class _PendingCapture:
    observed_on: date
    inputs: IntelligenceInputSet
    recommendations: tuple[RecommendationReport, ...] | None = None


@dataclass(frozen=True, slots=True)
class SnapshotRoundTripResult:
    """Deterministic parity result for one prospective package."""

    capture_id: str
    input_parity: bool
    recommendation_parity: bool
    fingerprint_parity: bool
    complete_stack_parity: bool
    plan_identity_parity: bool
    tamper_validation_passed: bool

    @property
    def ready(self) -> bool:
        return all(
            (
                self.input_parity,
                self.recommendation_parity,
                self.fingerprint_parity,
                self.complete_stack_parity,
                self.plan_identity_parity,
                self.tamper_validation_passed,
            )
        )


class CanonicalRecommendationSnapshotRecorder:
    """Write complete recommendation packages once under a governed root."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._pending: dict[str, _PendingCapture] = {}
        self._dispositions: dict[str, CaptureDisposition] = {}

    def begin_capture(
        self,
        *,
        observed_on: date,
        inputs: IntelligenceInputSet,
    ) -> str:
        input_payload = _payload(inputs)
        capture_id = stable_sha256(
            {
                "contract": SNAPSHOT_PACKAGE_VERSION,
                "observed_on": observed_on.isoformat(),
                "inputs": input_payload,
            }
        )
        pending = self._pending.get(capture_id)
        if pending is not None and canonical_json(pending.inputs) != canonical_json(
            inputs
        ):
            raise ReplayRetentionError("CONFLICTING_PENDING_CAPTURE")
        self._pending[capture_id] = _PendingCapture(
            observed_on=observed_on,
            inputs=inputs,
        )
        return capture_id

    def capture_recommendations(
        self,
        *,
        capture_id: str,
        recommendations: tuple[RecommendationReport, ...],
    ) -> None:
        pending = self._required_pending(capture_id)
        normalized = tuple(recommendations)
        if pending.recommendations is not None and canonical_json(
            pending.recommendations
        ) != canonical_json(normalized):
            raise ReplayRetentionError("CONFLICTING_RECOMMENDATION_CAPTURE")
        pending.recommendations = normalized

    def complete_capture(
        self,
        *,
        capture_id: str,
        recommendations: tuple[RecommendationReport, ...],
        institutional_evaluation: object | None,
        allocation_plan: CapitalAllocationPlan,
    ) -> None:
        pending = self._required_pending(capture_id)
        if pending.recommendations is None:
            raise ReplayRetentionError("RECOMMENDATION_CAPTURE_MISSING")
        if canonical_json(pending.recommendations) != canonical_json(recommendations):
            raise ReplayRetentionError("RECOMMENDATION_CAPTURE_CHANGED")
        package = _snapshot_package(
            capture_id=capture_id,
            pending=pending,
            recommendations=recommendations,
            institutional_evaluation=institutional_evaluation,
            allocation_plan=allocation_plan,
        )
        _assert_no_secrets(package)
        encoded = canonical_json(package) + "\n"
        self._root.mkdir(parents=True, exist_ok=True)
        path = self.package_path(capture_id)
        if path.exists():
            if path.read_text(encoding="utf-8") == encoded:
                self._dispositions[capture_id] = CaptureDisposition.IDENTICAL
                self._pending.pop(capture_id, None)
                return
            self._dispositions[capture_id] = CaptureDisposition.CONFLICT
            raise ReplayRetentionError("CONFLICTING_CAPTURE_FOR_SAME_IDENTITY")
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
        except FileExistsError as exc:
            raise ReplayRetentionError("CONFLICTING_CAPTURE_FOR_SAME_IDENTITY") from exc
        self._dispositions[capture_id] = CaptureDisposition.NEW
        self._pending.pop(capture_id, None)

    def package_path(self, capture_id: str) -> Path:
        return self._root / f"{capture_id}.json"

    def disposition(self, capture_id: str) -> CaptureDisposition | None:
        return self._dispositions.get(capture_id)

    def _required_pending(self, capture_id: str) -> _PendingCapture:
        try:
            return self._pending[capture_id]
        except KeyError as exc:
            raise ReplayRetentionError("UNKNOWN_CAPTURE_ID") from exc


class _FixedInputProvider:
    def __init__(self, inputs: IntelligenceInputSet) -> None:
        self._inputs = inputs

    def build(self, *, observed_on: date) -> IntelligenceInputSet:
        if observed_on != self._inputs.recommendation_candidates[0].observed_on:
            raise ReplayRetentionError("ROUND_TRIP_OBSERVATION_DATE_MISMATCH")
        return self._inputs


def validate_snapshot_package(path: Path) -> dict[str, Any]:
    """Validate package integrity, canonical identity, paths, and secret safety."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayRetentionError("SNAPSHOT_PACKAGE_READ_FAILED") from exc
    if not isinstance(payload, dict):
        raise ReplayRetentionError("SNAPSHOT_PACKAGE_OBJECT_REQUIRED")
    if payload.get("contract_version") != SNAPSHOT_PACKAGE_VERSION:
        raise ReplayRetentionError("SNAPSHOT_PACKAGE_VERSION_UNSUPPORTED")
    digest = str(payload.get("package_sha256") or "")
    body = dict(payload)
    body.pop("package_sha256", None)
    if stable_sha256(body) != digest:
        raise ReplayRetentionError("SNAPSHOT_PACKAGE_TAMPERED")
    expected_capture = stable_sha256(
        {
            "contract": SNAPSHOT_PACKAGE_VERSION,
            "observed_on": payload.get("observed_on"),
            "inputs": payload.get("input_snapshot"),
        }
    )
    if payload.get("capture_id") != expected_capture:
        raise ReplayRetentionError("SNAPSHOT_CAPTURE_ID_MISMATCH")
    _assert_no_secrets(payload)
    return payload


def replay_snapshot_package(path: Path) -> SnapshotRoundTripResult:
    """Re-execute a prospective package without mutable application state."""

    from alpha.application.intelligence import IntelligenceApplicationService
    from alpha.decision_intelligence import InstitutionalDecisionEngine

    payload = validate_snapshot_package(path)
    inputs = _decode_dataclass(payload["input_snapshot"], IntelligenceInputSet)
    if not isinstance(inputs, IntelligenceInputSet):
        raise ReplayRetentionError("INPUT_ROUND_TRIP_TYPE_INVALID")
    expected_recommendations = tuple(
        _decode_dataclass(item, RecommendationReport)
        for item in _required_list(payload, "recommendations")
    )
    if not all(
        isinstance(item, RecommendationReport) for item in expected_recommendations
    ):
        raise ReplayRetentionError("RECOMMENDATION_ROUND_TRIP_TYPE_INVALID")
    observed_on = date.fromisoformat(str(payload["observed_on"]))
    complete_stack = _required_mapping(payload, "complete_stack")
    expected_institutional = complete_stack.get("institutional_evaluation")
    institutional_enabled = expected_institutional is not None
    rerun = IntelligenceApplicationService(
        input_provider=_FixedInputProvider(inputs),
        institutional_engine=(
            InstitutionalDecisionEngine() if institutional_enabled else None
        ),
        governed_institutional_evaluation_enabled=institutional_enabled,
    ).run(observed_on=observed_on)
    input_parity = canonical_json(inputs) == canonical_json(
        _normalize_midnight_dates(payload["input_snapshot"])
    )
    recommendation_parity = canonical_json(rerun.recommendations) == canonical_json(
        expected_recommendations
    )
    expected_fingerprints = tuple(
        str(item) for item in _required_list(payload, "recommendation_fingerprints")
    )
    actual_fingerprints = tuple(stable_sha256(item) for item in rerun.recommendations)
    expected_plan_ids = tuple(
        str(item) for item in _required_list(payload, "recorded_plan_ids")
    )
    actual_plan_ids = tuple(
        stable_sha256(item.trade_plan) for item in rerun.recommendations
    )
    return SnapshotRoundTripResult(
        capture_id=str(payload["capture_id"]),
        input_parity=input_parity,
        recommendation_parity=recommendation_parity,
        fingerprint_parity=actual_fingerprints == expected_fingerprints,
        complete_stack_parity=(
            canonical_json(rerun.allocation_plan)
            == canonical_json(complete_stack.get("allocation_plan"))
            and canonical_json(rerun.institutional_evaluation)
            == canonical_json(expected_institutional)
        ),
        plan_identity_parity=actual_plan_ids == expected_plan_ids,
        tamper_validation_passed=True,
    )


def _snapshot_package(
    *,
    capture_id: str,
    pending: _PendingCapture,
    recommendations: tuple[RecommendationReport, ...],
    institutional_evaluation: object | None,
    allocation_plan: CapitalAllocationPlan,
) -> dict[str, object]:
    input_payload = _payload(pending.inputs)
    recommendation_payloads = [_payload(item) for item in recommendations]
    fingerprints = [stable_sha256(item) for item in recommendations]
    plan_ids = [stable_sha256(item.trade_plan) for item in recommendations]
    source_hashes = _source_hashes()
    body: dict[str, object] = {
        "contract_version": SNAPSHOT_PACKAGE_VERSION,
        "capture_id": capture_id,
        "observed_on": pending.observed_on.isoformat(),
        "price_arms": sorted(
            {
                candidate.metadata.get("price_view", "UNKNOWN")
                for candidate in pending.inputs.recommendation_candidates
            }
        ),
        "economic_candidate_ids": [
            stable_sha256(
                {
                    "symbol": item.symbol,
                    "observed_on": item.observed_on.isoformat(),
                }
            )
            for item in recommendations
        ],
        "candidate_arm_ids": [
            stable_sha256(
                {
                    "symbol": item.symbol,
                    "observed_on": item.observed_on.isoformat(),
                    "price_arm": item.metadata.get("price_view", "UNKNOWN"),
                }
            )
            for item in recommendations
        ],
        "recommendation_object_ids": [
            stable_sha256({"fingerprint": item}) for item in fingerprints
        ],
        "complete_stack_baseline_id": stable_sha256(
            {
                "recommendations": fingerprints,
                "allocation_plan": _payload(allocation_plan),
            }
        ),
        "recorded_plan_ids": plan_ids,
        "outcome_link_ids": [
            stable_sha256({"recommendation": item, "outcome": "UNLINKED"})
            for item in fingerprints
        ],
        "input_snapshot": input_payload,
        "recommendations": recommendation_payloads,
        "recommendation_fingerprints": fingerprints,
        "complete_stack": {
            "institutional_evaluation": _payload(institutional_evaluation),
            "allocation_plan": _payload(allocation_plan),
        },
        "source_manifest": source_hashes,
        "policy_hash": source_hashes["recommendation_engine"],
        "serializer_hash": source_hashes["snapshot_recorder"],
        "fingerprint_contract_hash": source_hashes["historical_rehydration"],
        "outcome_links": [],
    }
    body["package_sha256"] = stable_sha256(body)
    return body


def _source_hashes() -> dict[str, str]:
    from alpha.application import intelligence
    from alpha.decision_superiority import historical_rehydration

    sources = {
        "intelligence_application": inspect.getsourcefile(intelligence),
        "recommendation_engine": inspect.getsourcefile(RecommendationEngine),
        "historical_rehydration": inspect.getsourcefile(historical_rehydration),
        "snapshot_recorder": __file__,
    }
    result: dict[str, str] = {}
    for name, source in sorted(sources.items()):
        if source is None:
            raise ReplayRetentionError(f"SNAPSHOT_SOURCE_MISSING:{name}")
        result[name] = _file_sha256(Path(source))
    return result


def _decode_dataclass(value: object, target: Any) -> object:
    if target is Any or target is object:
        return value
    origin = get_origin(target)
    args = get_args(target)
    if origin in (Union, types.UnionType):
        if value is None and type(None) in args:
            return None
        candidates = tuple(item for item in args if item is not type(None))
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                return _decode_dataclass(value, candidate)
            except (TypeError, ValueError, ReplayRetentionError) as exc:
                last_error = exc
        raise ReplayRetentionError("UNION_VALUE_NOT_DECODABLE") from last_error
    if origin is tuple:
        if not isinstance(value, list):
            raise ReplayRetentionError("TUPLE_VALUE_REQUIRED")
        item_type = args[0] if args else Any
        return tuple(_decode_dataclass(item, item_type) for item in value)
    if origin in (list, set, frozenset):
        if not isinstance(value, list):
            raise ReplayRetentionError("SEQUENCE_VALUE_REQUIRED")
        item_type = args[0] if args else Any
        decoded = [_decode_dataclass(item, item_type) for item in value]
        return origin(decoded)
    if origin is not None and isinstance(value, dict) and len(args) == 2:
        key_type, item_type = args
        return MappingProxyType(
            {
                _decode_dataclass(key, key_type): _decode_dataclass(item, item_type)
                for key, item in sorted(value.items())
            }
        )
    if target is Decimal:
        return Decimal(str(value))
    if target is date:
        return date.fromisoformat(str(value).split("T", maxsplit=1)[0])
    if isinstance(target, type) and issubclass(target, Enum):
        return target(value)
    if isinstance(target, type) and is_dataclass(target):
        if not isinstance(value, dict):
            raise ReplayRetentionError("DATACLASS_OBJECT_REQUIRED")
        hints = get_type_hints(target)
        kwargs = {
            item.name: _decode_dataclass(value[item.name], hints[item.name])
            for item in fields(target)
            if item.name in value
        }
        return target(**kwargs)
    return value


def _payload(value: object) -> Any:
    return json.loads(canonical_json(value))


def _normalize_midnight_dates(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _normalize_midnight_dates(item) for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        return [_normalize_midnight_dates(item) for item in value]
    if isinstance(value, str) and value.endswith("T00:00:00"):
        candidate = value.removesuffix("T00:00:00")
        try:
            return date.fromisoformat(candidate).isoformat()
        except ValueError:
            return value
    return value


def _assert_no_secrets(value: object, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            normalized = str(key).lower()
            if any(marker in normalized for marker in _SENSITIVE_KEYS):
                raise ReplayRetentionError(f"SNAPSHOT_SECRET_FIELD_REJECTED:{child}")
            _assert_no_secrets(item, child)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_secrets(item, f"{path}[{index}]")


def _required_list(payload: Mapping[str, object], name: str) -> list[object]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise ReplayRetentionError(f"SNAPSHOT_LIST_REQUIRED:{name}")
    return value


def _required_mapping(payload: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = payload.get(name)
    if not isinstance(value, dict):
        raise ReplayRetentionError(f"SNAPSHOT_MAPPING_REQUIRED:{name}")
    return value


def _file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "CanonicalRecommendationSnapshotRecorder",
    "SnapshotRoundTripResult",
    "replay_snapshot_package",
    "validate_snapshot_package",
]
