"""Typed research-only contracts for DSI-006 forward snapshot accrual."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

DSI006_CONTRACT_VERSION = "DSI-006-v1.0.0"
DSI006_RESEARCH_SCOPE = "GOVERNED_FORWARD_SNAPSHOT_ACCRUAL_ONLY"


class ForwardSnapshotError(ValueError):
    """Raised when governed forward evidence cannot be preserved safely."""


class OperatingMode(StrEnum):
    """Explicit DSI-006 operating modes."""

    CAPTURE_DISABLED = "CAPTURE_DISABLED"
    FORWARD_CAPTURE = "GOVERNED_FORWARD_SHADOW_CAPTURE"
    PACKAGE_VERIFY = "SNAPSHOT_PACKAGE_VERIFY"
    SNAPSHOT_REPLAY = "SNAPSHOT_REPLAY"
    OUTCOME_ACCRUAL = "OUTCOME_EVENT_ACCRUAL"
    DSI_REPLAY = "DSI_COUNTERFACTUAL_REPLAY"
    READINESS_AUDIT = "POPULATION_READINESS_AUDIT"


class CaptureSessionState(StrEnum):
    """Result of one genuine forward-shadow session."""

    NONEMPTY = "CAPTURED_NONEMPTY_SESSION"
    ZERO_RECOMMENDATION = "CAPTURED_ZERO_RECOMMENDATION_SESSION"
    INPUT_UNAVAILABLE = "SESSION_INPUT_UNAVAILABLE"
    NOT_ADMITTED = "SESSION_NOT_ADMITTED"
    FAILED = "SESSION_CAPTURE_FAILED"


class RepositoryDisposition(StrEnum):
    """Append-only package publication result."""

    NEW = "NEW_CAPTURE"
    IDENTICAL = "IDENTICAL_CAPTURE_ALREADY_EXISTS"
    CANDIDATE_CONFLICT = "CONFLICTING_CAPTURE_FOR_SAME_CANDIDATE_ARM"
    MANIFEST_CONFLICT = "CONFLICTING_MANIFEST"
    INVALID = "INVALID_PACKAGE"


class IdentityClassification(StrEnum):
    """Relationship between one package and the governed population."""

    DISTINCT = "NOT_DUPLICATE"
    RAW_ADJUSTED_PAIR = "RAW_ADJUSTED_PAIR"
    IDENTICAL_RERUN = "IDENTICAL_RERUN"
    MULTI_SESSION = "MULTI_SESSION_DISTINCT_CANDIDATE"
    RECOMMENDATION_CONFLICT = "CONFLICTING_RECOMMENDATION_IDENTITY"
    ECONOMIC_CONFLICT = "CONFLICTING_ECONOMIC_CANDIDATE_IDENTITY"
    POLICY_CONFLICT = "CONFLICTING_POLICY_VERSION"
    PRICE_ARM_CONFLICT = "CONFLICTING_PRICE_ARM"
    PLAN_CONFLICT = "CONFLICTING_PLAN_IDENTITY"


class OutcomeEventType(StrEnum):
    """Append-only DSI-006 lifecycle event."""

    PLAN_RECORDED = "PLAN_RECORDED"
    ENTRY_PENDING = "ENTRY_PENDING"
    ENTRY_NOT_TRIGGERED = "ENTRY_NOT_TRIGGERED"
    ENTRY_TRIGGERED = "ENTRY_TRIGGERED"
    POSITION_OPEN = "POSITION_OPEN"
    OUTCOME_PENDING = "OUTCOME_PENDING"
    OUTCOME_COMPLETED = "OUTCOME_COMPLETED"
    OUTCOME_INVALIDATED = "OUTCOME_INVALIDATED"
    OUTCOME_CORRECTION = "OUTCOME_CORRECTION_RECORDED"


class OutcomeState(StrEnum):
    """Reconciled outcome state for one candidate arm."""

    NO_PLAN = "NO_RECORDED_PLAN"
    ENTRY_PENDING = "ENTRY_PENDING"
    NOT_ENTERED = "NOT_ENTERED"
    POSITION_OPEN = "POSITION_OPEN"
    PENDING_END = "PENDING_END_OF_DATA"
    COMPLETED_COMPARABLE = "COMPLETED_COMPARABLE_OUTCOME"
    COMPLETED_NONCOMPARABLE = "COMPLETED_NONCOMPARABLE_OUTCOME"
    MISSING = "MISSING_OUTCOME"
    INVALID_LINEAGE = "INVALID_OUTCOME_LINEAGE"
    CONFLICTING = "CONFLICTING_OUTCOME_EVENTS"


class ReplayClassification(StrEnum):
    """Independent snapshot replay result."""

    FULL_PARITY = "FULL_ROUND_TRIP_PARITY"
    RECOMMENDATION_ONLY = "RECOMMENDATION_PARITY_ONLY"
    STACK_FAILED = "COMPLETE_STACK_PARITY_FAILED"
    PLAN_FAILED = "PLAN_IDENTITY_PARITY_FAILED"
    SOURCE_DRIFT = "SOURCE_HASH_DRIFT"
    POLICY_DRIFT = "POLICY_HASH_DRIFT"
    TAMPERED = "PACKAGE_TAMPERED"
    OUTCOME_IMMATURE = "OUTCOME_NOT_MATURE"
    DSI_INELIGIBLE = "DSI002_SEMANTICALLY_INELIGIBLE"
    DSI_COMPLETE = "DSI002_REPLAY_COMPLETE"


class SliceReadiness(StrEnum):
    """Readiness states for the DSI-006 A-I sequence."""

    A_READY = "READY_FOR_GOVERNED_FORWARD_SHADOW_CAPTURE"
    B_READY = "READY_FOR_GOVERNED_FORWARD_CAPTURE_OPERATIONS"
    B_ZERO = "READY_WITH_ZERO_NEW_CAPTURE_POPULATION"
    C_READY = "READY_FOR_GOVERNED_APPEND_ONLY_SNAPSHOT_STORAGE"
    D_READY = "READY_FOR_GOVERNED_FORWARD_POPULATION_IDENTITY"
    D_WARNINGS = "READY_WITH_DEPENDENCE_WARNINGS"
    E_READY = "READY_FOR_GOVERNED_APPEND_ONLY_OUTCOME_ACCRUAL"
    E_NO_MATURE = "READY_WITH_NO_MATURE_OUTCOMES"
    F_READY = "READY_FOR_GOVERNED_LONGITUDINAL_REPLAY"
    F_MECHANICAL = "READY_FOR_MECHANICAL_DSI_TRANSFER_ONLY"
    F_NO_MATURE = "READY_WITH_NO_MATURE_COUNTERFACTUAL_OUTCOMES"
    G_READY = "READY_FOR_GOVERNED_FORWARD_CAPTURE_OPERATIONS"
    G_WARNINGS = "READY_WITH_OPERATIONAL_WARNINGS"
    H_READY = "READY_FOR_GOVERNED_LONGITUDINAL_DSI_RESEARCH"
    H_ACCRUAL = "READY_FOR_FORWARD_POPULATION_ACCRUAL_ONLY"
    H_MECHANICAL = "READY_FOR_MECHANICAL_REPLAY_ONLY"
    I_READY = "READY_FOR_GOVERNED_FORWARD_SNAPSHOT_OPERATIONS"
    I_ACCRUAL = "READY_FOR_FORWARD_POPULATION_ACCRUAL_ONLY"
    I_MECHANICAL = "READY_FOR_MECHANICAL_LONGITUDINAL_DSI_REPLAY"
    I_DESCRIPTIVE = "READY_FOR_DESCRIPTIVE_LONGITUDINAL_DSI_RESEARCH"
    INVALID_SOURCE = "BLOCKED_BY_INVALID_DSI005_SOURCE_CHAIN"
    IMPLEMENTATION = "BLOCKED_BY_DSI006_IMPLEMENTATION_DEFECT"


@dataclass(frozen=True, slots=True)
class ForwardSnapshotSourcePaths:
    """Caller-selected signed inputs and immutable market sources."""

    dsi005_certificate: Path
    database: Path
    historical_truth_snapshots: Path
    capture_root: Path
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class CaptureSessionRecord:
    """Deterministic result for one requested market session."""

    session_id: str
    session_date: date
    state: CaptureSessionState
    package_sha256: str | None
    recommendation_count: int
    disposition: RepositoryDisposition | None
    explanation: str


@dataclass(frozen=True, slots=True)
class SnapshotIndexRow:
    """One recommendation arm address inside an immutable package."""

    session_id: str
    session_date: date
    package_sha256: str
    package_path: str
    economic_candidate_id: str
    candidate_arm_id: str
    recommendation_object_id: str
    complete_stack_baseline_id: str
    recorded_plan_id: str
    outcome_stream_id: str
    symbol: str
    verdict: str
    price_arm: str
    policy_hash: str


@dataclass(frozen=True, slots=True)
class OutcomeEvent:
    """Immutable content-addressed event linked to a captured package."""

    event_id: str
    economic_candidate_id: str
    candidate_arm_id: str
    snapshot_package_sha256: str
    recorded_plan_id: str
    event_type: OutcomeEventType
    observation_date: date
    effective_date: date
    completion_date: date | None
    source_lineage: str
    source_hash: str
    point_in_time_eligible: bool
    payload: MappingProxyType[str, object]
    payload_hash: str
    predecessor_event_id: str | None = None

    def __post_init__(self) -> None:
        if self.effective_date < self.observation_date:
            raise ForwardSnapshotError(
                "OUTCOME_EVENT_EFFECTIVE_DATE_PRECEDES_OBSERVATION"
            )
        if (
            self.completion_date is not None
            and self.completion_date < self.effective_date
        ):
            raise ForwardSnapshotError(
                "OUTCOME_EVENT_COMPLETION_PRECEDES_EFFECTIVE_DATE"
            )
        if not self.point_in_time_eligible:
            raise ForwardSnapshotError("POINT_IN_TIME_OUTCOME_EVENT_INELIGIBLE")


@dataclass(frozen=True, slots=True)
class ForwardSnapshotResult:
    """Deterministic DSI-006 evidence rows and certification conclusions."""

    source_commit: str
    readiness: MappingProxyType[str, str]
    summaries: MappingProxyType[str, object]
    rows: MappingProxyType[str, tuple[Mapping[str, object], ...]]
    jsonl_rows: tuple[Mapping[str, object], ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.source_commit.strip():
            raise ForwardSnapshotError("SOURCE_COMMIT_REQUIRED")
        if tuple(sorted(self.readiness)) != tuple(self.readiness):
            raise ForwardSnapshotError("SLICE_READINESS_NOT_SORTED")
        if tuple(sorted(self.rows)) != tuple(self.rows):
            raise ForwardSnapshotError("ROW_COLLECTIONS_NOT_SORTED")
        if tuple(sorted(set(self.blockers))) != self.blockers:
            raise ForwardSnapshotError("BLOCKERS_NOT_UNIQUE_AND_SORTED")


__all__ = [
    "CaptureSessionRecord",
    "CaptureSessionState",
    "DSI006_CONTRACT_VERSION",
    "DSI006_RESEARCH_SCOPE",
    "ForwardSnapshotError",
    "ForwardSnapshotResult",
    "ForwardSnapshotSourcePaths",
    "IdentityClassification",
    "OperatingMode",
    "OutcomeEvent",
    "OutcomeEventType",
    "OutcomeState",
    "ReplayClassification",
    "RepositoryDisposition",
    "SliceReadiness",
    "SnapshotIndexRow",
]
