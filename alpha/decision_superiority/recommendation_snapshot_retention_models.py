"""Typed research-only contracts for DSI-005 replay retention."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

DSI005_CONTRACT_VERSION = "DSI-005-v1.0.0"
DSI005_RESEARCH_SCOPE = (
    "GOVERNED_RECOMMENDATION_INPUT_MATERIALISATION_AND_RETENTION_ONLY"
)
SNAPSHOT_PACKAGE_VERSION = "ALPHA-RECOMMENDATION-SNAPSHOT-v1.0.0"


class ReplayRetentionError(ValueError):
    """Raised when replay retention cannot preserve its evidence boundary."""


class DeficitClassification(StrEnum):
    """Reason one required historical recommendation input is unavailable."""

    EXACT_VALUE_MISSING = "EXACT_VALUE_MISSING"
    PRIMITIVE_MISSING = "HISTORICAL_PRIMITIVE_MISSING"
    PRIMITIVE_AVAILABLE = "HISTORICAL_PRIMITIVE_AVAILABLE"
    ALGORITHM_VERSION_MISSING = "ALGORITHM_VERSION_MISSING"
    POLICY_VERSION_MISSING = "POLICY_VERSION_MISSING"
    ENUM_MAPPING_MISSING = "ENUM_MAPPING_MISSING"
    UNIVERSE_STATE_MISSING = "UNIVERSE_STATE_MISSING"
    CORPORATE_ACTION_STATE_MISSING = "CORPORATE_ACTION_STATE_MISSING"
    MARKET_REGIME_STATE_MISSING = "MARKET_REGIME_STATE_MISSING"
    SECTOR_STATE_MISSING = "SECTOR_STATE_MISSING"
    LIQUIDITY_STATE_MISSING = "LIQUIDITY_STATE_MISSING"
    EVIDENCE_STATE_MISSING = "EVIDENCE_STATE_MISSING"
    DATA_COMPLETENESS_STATE_MISSING = "DATA_COMPLETENESS_STATE_MISSING"
    FINGERPRINT_DIMENSION_MISSING = "FINGERPRINT_DIMENSION_MISSING"
    SERIALISATION_STATE_MISSING = "SERIALISATION_STATE_MISSING"
    POINT_IN_TIME_AMBIGUOUS = "POINT_IN_TIME_BOUNDARY_AMBIGUOUS"
    SOURCE_LINEAGE_INVALID = "SOURCE_LINEAGE_INVALID"
    NOT_REQUIRED = "NOT_REQUIRED_FOR_HISTORICAL_VERSION"


class Derivability(StrEnum):
    """Governed historical derivability of one required field."""

    RETAINED = "RETAINED_EXACT_VALUE"
    EXACT = "EXACTLY_DERIVABLE_FROM_IMMUTABLE_PRIMITIVES"
    MAPPED = "EXACTLY_DERIVABLE_WITH_SIGNED_VERSIONED_MAPPING"
    ALGORITHM_UNAVAILABLE = "DERIVABLE_BUT_HISTORICAL_ALGORITHM_UNAVAILABLE"
    POLICY_UNAVAILABLE = "DERIVABLE_BUT_HISTORICAL_POLICY_UNAVAILABLE"
    TIMING_AMBIGUOUS = "DERIVABLE_BUT_POINT_IN_TIME_BOUNDARY_AMBIGUOUS"
    CURRENT_DEFAULT_ONLY = "DERIVABLE_ONLY_WITH_CURRENT_DEFAULT"
    FUTURE_ONLY = "DERIVABLE_ONLY_WITH_FUTURE_INFORMATION"
    MULTIPLE_VALUES = "MULTIPLE_VALID_HISTORICAL_VALUES"
    PRIMITIVE_INCOMPLETE = "PRIMITIVE_SOURCE_INCOMPLETE"
    PRIMITIVE_INVALID = "PRIMITIVE_SOURCE_INVALID"
    NOT_DERIVABLE = "NOT_DERIVABLE"


class CaptureDisposition(StrEnum):
    """Append-only result for one prospective snapshot package."""

    NEW = "NEW_CAPTURE"
    IDENTICAL = "IDENTICAL_CAPTURE_ALREADY_EXISTS"
    CONFLICT = "CONFLICTING_CAPTURE_FOR_SAME_IDENTITY"


class SliceReadiness(StrEnum):
    """Readiness states for the implemented DSI-005 A-I sequence."""

    A_READY = "READY_FOR_GOVERNED_INPUT_DERIVABILITY_RESEARCH"
    B_PARTIAL = "READY_WITH_PARTIAL_DERIVABILITY"
    C_ZERO_ADDITIONAL = "READY_WITH_ZERO_ADDITIONAL_HISTORICAL_SNAPSHOTS"
    D_PROSPECTIVE_ONLY = "READY_FOR_PROSPECTIVE_CAPTURE_ONLY"
    E_NO_ADDITIONAL = "READY_WITH_NO_ADDITIONAL_HISTORICAL_ADMISSION"
    F_READY = "READY_FOR_GOVERNED_PROSPECTIVE_RECOMMENDATION_CAPTURE"
    G_READY = "READY_FOR_GOVERNED_SNAPSHOT_ROUND_TRIP_REPLAY"
    H_PROSPECTIVE_ONLY = "READY_FOR_PROSPECTIVE_CAPTURE_ONLY"
    I_READY = "READY_FOR_GOVERNED_RECOMMENDATION_SNAPSHOT_RETENTION"
    INVALID_SOURCE = "BLOCKED_BY_INVALID_DSI004_SOURCE_CHAIN"
    IMPLEMENTATION = "BLOCKED_BY_DSI005_IMPLEMENTATION_DEFECT"


@dataclass(frozen=True, slots=True)
class ReplayRetentionSourcePaths:
    """Caller-selected DSI-004 certificate and repository root."""

    dsi004_certificate: Path
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class ReplayRetentionResult:
    """Deterministic DSI-005 evidence rows and conclusions."""

    source_commit: str
    readiness: MappingProxyType[str, str]
    summaries: MappingProxyType[str, object]
    rows: MappingProxyType[str, tuple[Mapping[str, object], ...]]
    jsonl_rows: tuple[Mapping[str, object], ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.source_commit.strip():
            raise ValueError("source commit cannot be empty")
        if tuple(sorted(self.readiness)) != tuple(self.readiness):
            raise ValueError("slice readiness must be sorted")
        if tuple(sorted(self.rows)) != tuple(self.rows):
            raise ValueError("row collections must be sorted")
        if tuple(sorted(set(self.blockers))) != self.blockers:
            raise ValueError("blockers must be unique and sorted")


__all__ = [
    "CaptureDisposition",
    "DSI005_CONTRACT_VERSION",
    "DSI005_RESEARCH_SCOPE",
    "DeficitClassification",
    "Derivability",
    "ReplayRetentionError",
    "ReplayRetentionResult",
    "ReplayRetentionSourcePaths",
    "SNAPSHOT_PACKAGE_VERSION",
    "SliceReadiness",
]
