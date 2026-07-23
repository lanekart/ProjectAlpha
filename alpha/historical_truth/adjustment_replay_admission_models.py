"""Immutable HTR-010B1 adjustment validation and replay-admission contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Any

HTR010B1_CONTRACT_VERSION = "HTR-010B1-v1.0.0"
HTR010B1A_CONTRACT_VERSION = "HTR-010B1A-v1.0.0"
TRANSFORMATION_CONTRACT_VERSION = "HTR-010B1-TRANSFORM-v1.0.0"
PRODUCTION_INFLUENCE = False


class ValidationOutcome(StrEnum):
    FACTOR_CONFIRMED_CORRECT_MARKET_GAP = "FACTOR_CONFIRMED_CORRECT_MARKET_GAP"
    FACTOR_CONFIRMED_CORRECT_THIN_TRADING = "FACTOR_CONFIRMED_CORRECT_THIN_TRADING"
    FACTOR_CONFIRMED_CORRECT_EVENT_DATE_OFFSET = (
        "FACTOR_CONFIRMED_CORRECT_EVENT_DATE_OFFSET"
    )
    FACTOR_CONFIRMED_CORRECT_MULTIPLE_ACTIONS = (
        "FACTOR_CONFIRMED_CORRECT_MULTIPLE_ACTIONS"
    )
    FACTOR_CORRECTED_RATIO = "FACTOR_CORRECTED_RATIO"
    FACTOR_CORRECTED_EFFECTIVE_DATE = "FACTOR_CORRECTED_EFFECTIVE_DATE"
    FACTOR_CORRECTED_EVENT_TYPE = "FACTOR_CORRECTED_EVENT_TYPE"
    FACTOR_CORRECTED_CUMULATIVE_ORDER = "FACTOR_CORRECTED_CUMULATIVE_ORDER"
    FACTOR_CORRECTED_SERIES_APPLICABILITY = "FACTOR_CORRECTED_SERIES_APPLICABILITY"
    FACTOR_REQUIRES_REFERENCE_PRICE = "FACTOR_REQUIRES_REFERENCE_PRICE"
    FACTOR_NON_MULTIPLICATIVE = "FACTOR_NON_MULTIPLICATIVE"
    FACTOR_CONFLICTING_OFFICIAL_EVIDENCE = "FACTOR_CONFLICTING_OFFICIAL_EVIDENCE"
    FACTOR_INSUFFICIENT_EVIDENCE = "FACTOR_INSUFFICIENT_EVIDENCE"
    IMPLEMENTATION_DEFECT = "IMPLEMENTATION_DEFECT"
    UNRESOLVED = "UNRESOLVED"


class ReplayImpact(StrEnum):
    NO_TECHNICAL_ADJUSTMENT_REQUIRED = "NO_TECHNICAL_ADJUSTMENT_REQUIRED"
    RAW_SAFE_WITHIN_POST_EVENT_INTERVAL = "RAW_SAFE_WITHIN_POST_EVENT_INTERVAL"
    SEGMENT_HISTORY_AT_EVENT = "SEGMENT_HISTORY_AT_EVENT"
    REQUIRE_CERTIFIED_FACTOR = "REQUIRE_CERTIFIED_FACTOR"
    IDENTITY_TRANSITION_NONCOMPARABLE = "IDENTITY_TRANSITION_NONCOMPARABLE"
    TOTAL_RETURN_ONLY_IMPACT = "TOTAL_RETURN_ONLY_IMPACT"
    QUARANTINE_INTERVAL = "QUARANTINE_INTERVAL"
    UNRESOLVED = "UNRESOLVED"


class MixedBasisResolution(StrEnum):
    FULLY_ADJUSTED_CERTIFIED = "FULLY_ADJUSTED_CERTIFIED"
    ADJUSTED_WITH_SEGMENTED_UNCERTIFIED_INTERVAL = (
        "ADJUSTED_WITH_SEGMENTED_UNCERTIFIED_INTERVAL"
    )
    RAW_ONLY_CERTIFIED_INTERVALS = "RAW_ONLY_CERTIFIED_INTERVALS"
    IDENTITY_TRANSITION_SEGMENTED = "IDENTITY_TRANSITION_SEGMENTED"
    MIXED_BASIS_IMPLEMENTATION_REPAIRED = "MIXED_BASIS_IMPLEMENTATION_REPAIRED"
    MIXED_BASIS_QUARANTINED = "MIXED_BASIS_QUARANTINED"
    UNRESOLVED = "UNRESOLVED"


class AdmissionState(StrEnum):
    ADJUSTED_REPLAY_CERTIFIED = "ADJUSTED_REPLAY_CERTIFIED"
    ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL = (
        "ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL"
    )
    RAW_REPLAY_CERTIFIED_NO_ACTION_EXPOSURE = "RAW_REPLAY_CERTIFIED_NO_ACTION_EXPOSURE"
    RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT = "RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT"
    SEGMENT_BOUNDARY_REQUIRED = "SEGMENT_BOUNDARY_REQUIRED"
    IDENTITY_TRANSITION_NONCOMPARABLE = "IDENTITY_TRANSITION_NONCOMPARABLE"
    FACTOR_UNKNOWN_QUARANTINED = "FACTOR_UNKNOWN_QUARANTINED"
    FACTOR_AMBIGUOUS_QUARANTINED = "FACTOR_AMBIGUOUS_QUARANTINED"
    BRIDGE_UNCERTIFIED_QUARANTINED = "BRIDGE_UNCERTIFIED_QUARANTINED"
    MIXED_PRICE_BASIS_QUARANTINED = "MIXED_PRICE_BASIS_QUARANTINED"
    CONFLICTING_EVIDENCE_QUARANTINED = "CONFLICTING_EVIDENCE_QUARANTINED"
    INSUFFICIENT_EVIDENCE_QUARANTINED = "INSUFFICIENT_EVIDENCE_QUARANTINED"
    UNRESOLVED = "UNRESOLVED"


class ReplayReadiness(StrEnum):
    READY_FOR_ADJUSTED_REPLAY_INTEGRATION = "READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
    CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION = (
        "CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
    )
    NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION = (
        "NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
    )


@dataclass(frozen=True, slots=True)
class AdjustmentReplayAdmissionReport:
    contract_version: str
    transformation_contract_version: str
    production_influence: bool
    start_date: date
    end_date: date
    quarantine_census: tuple[dict[str, Any], ...]
    quarantine_economic_weight: tuple[dict[str, Any], ...]
    factor_validation_cases: tuple[dict[str, Any], ...]
    factor_validation_results: tuple[dict[str, Any], ...]
    event_boundaries: tuple[dict[str, Any], ...]
    multiple_action_cases: tuple[dict[str, Any], ...]
    series_applicability: tuple[dict[str, Any], ...]
    unknown_factor_impact: tuple[dict[str, Any], ...]
    mixed_basis_resolution: tuple[dict[str, Any], ...]
    adjusted_row_audit: tuple[dict[str, Any], ...]
    replay_admission_intervals: tuple[dict[str, Any], ...]
    indicator_lookback_safety: tuple[dict[str, Any], ...]
    transformation_contract: dict[str, Any]
    coverage_matrix: tuple[dict[str, Any], ...]
    replay_readiness: dict[str, Any]
    rejected_evidence: tuple[dict[str, Any], ...]
    report_sha256: str
    input_contract_diagnostics: dict[str, Any] = field(default_factory=dict)
    population_reconciliation: dict[str, Any] = field(default_factory=dict)
    quarantine_population_reconciliation: dict[str, Any] = field(default_factory=dict)

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = _jsonable(asdict(self))
        if not isinstance(payload, dict):
            raise TypeError("HTR-010B1 report must serialize to an object")
        if not include_hash:
            payload["report_sha256"] = ""
        return payload

    def calculated_sha256(self) -> str:
        encoded = json.dumps(
            self.payload(include_hash=False), sort_keys=True, separators=(",", ":")
        ).encode()
        return sha256(encoded).hexdigest()


def stable_id(prefix: str, *values: object) -> str:
    material = "|".join(str(value or "").upper() for value in values)
    return f"{prefix}:{sha256(material.encode()).hexdigest()}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


__all__ = [name for name in globals() if not name.startswith("_")]
