"""Typed research-only contracts for DSI-004 recommendation rehydration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

DSI004_CONTRACT_VERSION = "DSI-004-v1.0.0"
DSI004_RESEARCH_SCOPE = "GOVERNED_HISTORICAL_RECOMMENDATION_REHYDRATION_DIAGNOSTIC_ONLY"


class HistoricalRehydrationError(ValueError):
    """Raised when DSI-004 cannot preserve its governed evidence boundary."""


class RecommendationClassification(StrEnum):
    """Mutually exclusive historical recommendation classifications."""

    EXACT_FROZEN_OBJECT = "EXACT_FROZEN_OBJECT"
    EXACT_SERIALISED_OBJECT_REHYDRATED = "EXACT_SERIALISED_OBJECT_REHYDRATED"
    PARITY_PROVEN = "CANONICAL_POINT_IN_TIME_RECONSTRUCTION_PARITY_PROVEN"
    PARTIAL = "CANONICAL_POINT_IN_TIME_RECONSTRUCTION_PARTIAL"
    CONTRACT_INCOMPLETE = "OBJECT_CONTRACT_INCOMPLETE"
    INPUT_UNAVAILABLE = "REQUIRED_INPUT_UNAVAILABLE"
    INPUT_AMBIGUOUS = "REQUIRED_INPUT_AMBIGUOUS"
    POLICY_UNAVAILABLE = "POLICY_VERSION_UNAVAILABLE"
    SOURCE_UNAVAILABLE = "SOURCE_VERSION_UNAVAILABLE"
    FINGERPRINT_FAILED = "FINGERPRINT_PARITY_FAILED"
    RECOMMENDATION_FAILED = "RECOMMENDATION_PARITY_FAILED"
    DOWNSTREAM_FAILED = "DOWNSTREAM_PARITY_FAILED"
    POINT_IN_TIME_INVALID = "POINT_IN_TIME_INVALID"
    ARM_AMBIGUOUS = "RAW_ADJUSTED_ARM_AMBIGUOUS"
    NONDETERMINISTIC = "NONDETERMINISTIC_RECONSTRUCTION"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_HISTORICAL_SCHEMA"
    IMPLEMENTATION_ERROR = "IMPLEMENTATION_ERROR"


class InputAvailability(StrEnum):
    """Point-in-time availability of one required recommendation input."""

    EXACT = "AVAILABLE_EXACT"
    RECONSTRUCTABLE = "AVAILABLE_RECONSTRUCTABLE"
    PROVEN_MAPPING = "AVAILABLE_WITH_PROVEN_MAPPING"
    AMBIGUOUS = "AVAILABLE_BUT_AMBIGUOUS"
    MISSING = "MISSING"
    FUTURE_ONLY = "FUTURE_ONLY"
    WRONG_ARM = "WRONG_PRICE_ARM"
    WRONG_POLICY = "WRONG_POLICY_VERSION"
    INVALID_LINEAGE = "SOURCE_LINEAGE_INVALID"
    NOT_REQUIRED = "NOT_REQUIRED_FOR_HISTORICAL_VERSION"


class ParityGrade(StrEnum):
    """Governed recommendation reconstruction parity grades."""

    BYTE_IDENTICAL = "BYTE_IDENTICAL"
    NORMALIZED_IDENTICAL = "NORMALIZED_OBJECT_IDENTICAL"
    SEMANTICALLY_IDENTICAL = "SEMANTICALLY_IDENTICAL"
    DOWNSTREAM_IDENTICAL = "DOWNSTREAM_DECISION_IDENTICAL"
    PARTIAL = "PARTIAL_PARITY"
    FINGERPRINT_FAILED = "FINGERPRINT_PARITY_FAILED"
    RECOMMENDATION_FAILED = "RECOMMENDATION_PARITY_FAILED"
    DOWNSTREAM_FAILED = "DOWNSTREAM_PARITY_FAILED"
    NO_REFERENCE = "NO_AUTHORITATIVE_REFERENCE"


class SliceReadiness(StrEnum):
    """Readiness states used by the implemented DSI-004 A-K chain."""

    A_READY = "READY_FOR_GOVERNED_RECOMMENDATION_REHYDRATION"
    B_PARTIAL = "READY_WITH_PARTIAL_INPUT_COVERAGE"
    C_NO_OBJECTS = "BLOCKED_BY_NO_VALID_SERIALISED_OBJECTS"
    D_PARTIAL = "READY_WITH_PARTIAL_CANONICAL_RECONSTRUCTION"
    E_RESTRICTED = "READY_WITH_RESTRICTED_RECONSTRUCTION_METHODS"
    F_PARTIAL = "READY_WITH_PARTIAL_REHYDRATED_POPULATION"
    G_PARTIAL = "READY_WITH_PARTIAL_COMPLETE_STACK_BASELINE"
    H_ZERO_APPROVALS = "READY_WITH_ZERO_SHADOW_APPROVALS"
    I_NO_OUTCOMES = "READY_WITH_NO_COMPARABLE_SHADOW_OUTCOMES"
    J_MECHANICAL = "READY_FOR_MECHANICAL_TRANSFERABILITY_ONLY"
    K_MECHANICAL = "READY_FOR_MECHANICAL_REHYDRATION_RESEARCH_ONLY"
    INVALID_SOURCE = "BLOCKED_BY_INVALID_SOURCE_CHAIN"
    NO_POPULATION = "BLOCKED_BY_NO_TRUSTWORTHY_REHYDRATED_POPULATION"
    IMPLEMENTATION = "BLOCKED_BY_DSI004_IMPLEMENTATION_DEFECT"


@dataclass(frozen=True, slots=True)
class HistoricalRehydrationSourcePaths:
    """Caller-selected DSI-003 certificate and governed repository root."""

    dsi003_certificate: Path
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class HistoricalRehydrationResult:
    """All deterministic empirical rows and governed DSI-004 conclusions."""

    source_commit: str
    readiness: MappingProxyType[str, str]
    summaries: MappingProxyType[str, object]
    rows: MappingProxyType[str, tuple[Mapping[str, object], ...]]
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
    "DSI004_CONTRACT_VERSION",
    "DSI004_RESEARCH_SCOPE",
    "HistoricalRehydrationError",
    "HistoricalRehydrationResult",
    "HistoricalRehydrationSourcePaths",
    "InputAvailability",
    "ParityGrade",
    "RecommendationClassification",
    "SliceReadiness",
]
