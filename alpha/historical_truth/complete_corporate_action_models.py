"""Immutable HTR-010B corporate-action and price-basis contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Any

HTR010B_CONTRACT_VERSION = "HTR-010B-v1.1.0"
ADJUSTMENT_POLICY_VERSION = "HTR-010B-ADJUSTMENT-v1.1.0"
PRODUCTION_INFLUENCE = False


class GovernedActionType(StrEnum):
    SPLIT = "SPLIT"
    BONUS = "BONUS"
    RIGHTS = "RIGHTS"
    DIVIDEND_ORDINARY = "DIVIDEND_ORDINARY"
    DIVIDEND_SPECIAL = "DIVIDEND_SPECIAL"
    DIVIDEND_INTERIM = "DIVIDEND_INTERIM"
    DIVIDEND_FINAL = "DIVIDEND_FINAL"
    FACE_VALUE_CHANGE = "FACE_VALUE_CHANGE"
    CAPITAL_REDUCTION = "CAPITAL_REDUCTION"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    AMALGAMATION = "AMALGAMATION"
    SCHEME_OF_ARRANGEMENT = "SCHEME_OF_ARRANGEMENT"
    SPIN_OFF = "SPIN_OFF"
    SECURITY_REPLACEMENT = "SECURITY_REPLACEMENT"
    ISIN_CHANGE = "ISIN_CHANGE"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
    SERIES_CHANGE = "SERIES_CHANGE"
    RELISTING = "RELISTING"
    SHARE_CANCELLATION = "SHARE_CANCELLATION"
    BUYBACK = "BUYBACK"
    PARTLY_PAID_CALL = "PARTLY_PAID_CALL"
    PARTLY_PAID_TO_FULLY_PAID = "PARTLY_PAID_TO_FULLY_PAID"
    RIGHTS_ENTITLEMENT = "RIGHTS_ENTITLEMENT"
    OTHER_NON_ADJUSTING_EVENT = "OTHER_NON_ADJUSTING_EVENT"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"


class AssignmentMethod(StrEnum):
    OFFICIAL_ISIN_INTERVAL = "OFFICIAL_ISIN_INTERVAL"
    PREDECESSOR_SUCCESSOR = "PREDECESSOR_SUCCESSOR"
    EFFECTIVE_DATED_ISIN_TRANSITION = "EFFECTIVE_DATED_ISIN_TRANSITION"
    EFFECTIVE_DATED_SYMBOL_SERIES = "EFFECTIVE_DATED_SYMBOL_SERIES"
    BOUNDED_MEMBERSHIP = "BOUNDED_MEMBERSHIP"
    UNRESOLVED = "UNRESOLVED"


class EventAdmission(StrEnum):
    ADMITTED_COMPLETE = "ADMITTED_COMPLETE"
    ADMITTED_NON_ADJUSTING = "ADMITTED_NON_ADJUSTING"
    ADMITTED_FACTOR_DERIVABLE = "ADMITTED_FACTOR_DERIVABLE"
    ADMITTED_FACTOR_UNKNOWN = "ADMITTED_FACTOR_UNKNOWN"
    ADMITTED_BOUNDED_IDENTITY = "ADMITTED_BOUNDED_IDENTITY"
    REJECTED_IDENTITY_UNRESOLVED = "REJECTED_IDENTITY_UNRESOLVED"
    REJECTED_WRONG_INSTRUMENT = "REJECTED_WRONG_INSTRUMENT"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_CANCELLED = "REJECTED_CANCELLED"
    REJECTED_INVALID_TERMS = "REJECTED_INVALID_TERMS"
    REJECTED_CONFLICTING_OFFICIAL_EVIDENCE = "REJECTED_CONFLICTING_OFFICIAL_EVIDENCE"
    REJECTED_OUTSIDE_AUDIT_WINDOW = "REJECTED_OUTSIDE_AUDIT_WINDOW"
    UNRESOLVED_EVENT_TYPE = "UNRESOLVED_EVENT_TYPE"
    UNRESOLVED_EFFECTIVE_DATE = "UNRESOLVED_EFFECTIVE_DATE"


class FactorState(StrEnum):
    FACTOR_CERTIFIED = "FACTOR_CERTIFIED"
    FACTOR_CERTIFIED_REFERENCE_PRICE = "FACTOR_CERTIFIED_REFERENCE_PRICE"
    FACTOR_DERIVED_OFFICIAL_TERMS = "FACTOR_DERIVED_OFFICIAL_TERMS"
    FACTOR_PROVISIONAL_REFERENCE_PRICE = "FACTOR_PROVISIONAL_REFERENCE_PRICE"
    FACTOR_NOT_REQUIRED = "FACTOR_NOT_REQUIRED"
    FACTOR_UNKNOWN_MISSING_TERMS = "FACTOR_UNKNOWN_MISSING_TERMS"
    FACTOR_AMBIGUOUS_TERMS = "FACTOR_AMBIGUOUS_TERMS"
    FACTOR_CONFLICTING_EVENTS = "FACTOR_CONFLICTING_EVENTS"
    FACTOR_NOT_MULTIPLICATIVE = "FACTOR_NOT_MULTIPLICATIVE"
    FACTOR_IDENTITY_TRANSITION_ONLY = "FACTOR_IDENTITY_TRANSITION_ONLY"
    FACTOR_INVALID = "FACTOR_INVALID"


class PriceBasisState(StrEnum):
    RAW_NO_ACTION_EXPOSURE = "RAW_NO_ACTION_EXPOSURE"
    RAW_ADJUSTMENT_REQUIRED = "RAW_ADJUSTMENT_REQUIRED"
    BACKWARD_ADJUSTED_CERTIFIED = "BACKWARD_ADJUSTED_CERTIFIED"
    BACKWARD_ADJUSTED_PARTIAL = "BACKWARD_ADJUSTED_PARTIAL"
    FORWARD_ADJUSTED_CERTIFIED = "FORWARD_ADJUSTED_CERTIFIED"
    TOTAL_RETURN_AVAILABLE = "TOTAL_RETURN_AVAILABLE"
    MIXED_PRICE_BASIS = "MIXED_PRICE_BASIS"
    FACTOR_UNKNOWN = "FACTOR_UNKNOWN"
    FACTOR_AMBIGUOUS = "FACTOR_AMBIGUOUS"
    IDENTITY_TRANSITION_BOUNDARY = "IDENTITY_TRANSITION_BOUNDARY"
    NON_COMPARABLE_PREDECESSOR_SUCCESSOR = "NON_COMPARABLE_PREDECESSOR_SUCCESSOR"
    CONFLICTING_OFFICIAL_EVIDENCE = "CONFLICTING_OFFICIAL_EVIDENCE"


class ContinuityState(StrEnum):
    CONTINUITY_RESTORED = "CONTINUITY_RESTORED"
    CONTINUITY_IMPROVED = "CONTINUITY_IMPROVED"
    RESIDUAL_MARKET_GAP = "RESIDUAL_MARKET_GAP"
    FACTOR_LIKELY_INCORRECT = "FACTOR_LIKELY_INCORRECT"
    EVENT_DATE_UNCERTAINTY = "EVENT_DATE_UNCERTAINTY"
    INSUFFICIENT_ADJACENT_OBSERVATIONS = "INSUFFICIENT_ADJACENT_OBSERVATIONS"
    NON_COMPARABLE_REORGANISATION = "NON_COMPARABLE_REORGANISATION"


class CertificationState(StrEnum):
    CORPORATE_ACTION_CERTIFIED = "CORPORATE_ACTION_CERTIFIED"
    CORPORATE_ACTION_CERTIFIED_PRICE_PARTIAL = (
        "CORPORATE_ACTION_CERTIFIED_PRICE_PARTIAL"
    )
    IDENTITY_TRANSITION_CERTIFIED_PRICE_NONCOMPARABLE = (
        "IDENTITY_TRANSITION_CERTIFIED_PRICE_NONCOMPARABLE"
    )
    FACTOR_COVERAGE_PARTIAL = "FACTOR_COVERAGE_PARTIAL"
    EVENT_COVERAGE_PARTIAL = "EVENT_COVERAGE_PARTIAL"
    CONFLICTING = "CONFLICTING"
    NO_MATERIAL_ACTIONS_FOUND = "NO_MATERIAL_ACTIONS_FOUND"
    UNKNOWN_EVENT_COVERAGE = "UNKNOWN_EVENT_COVERAGE"


class ReplayReadiness(StrEnum):
    READY_FOR_ADJUSTED_REPLAY_INTEGRATION = "READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
    CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION = (
        "CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
    )
    NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION = (
        "NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
    )


@dataclass(frozen=True, slots=True)
class CompleteCorporateActionReport:
    contract_version: str
    adjustment_policy_version: str
    production_influence: bool
    start_date: date
    end_date: date
    source_completeness: tuple[dict[str, Any], ...]
    raw_event_census: tuple[dict[str, Any], ...]
    canonical_events: tuple[dict[str, Any], ...]
    event_lineage: tuple[dict[str, Any], ...]
    duplicate_groups: tuple[dict[str, Any], ...]
    rejected_events: tuple[dict[str, Any], ...]
    adjustment_factors: tuple[dict[str, Any], ...]
    cumulative_factors: tuple[dict[str, Any], ...]
    identity_transitions: tuple[dict[str, Any], ...]
    price_basis_intervals: tuple[dict[str, Any], ...]
    adjusted_candle_summary: tuple[dict[str, Any], ...]
    price_continuity: tuple[dict[str, Any], ...]
    false_signal_contamination: tuple[dict[str, Any], ...]
    identity_coverage_matrix: tuple[dict[str, Any], ...]
    ytd_2026: dict[str, Any]
    replay_readiness: dict[str, Any]
    certification: dict[str, Any]
    source_checksums: tuple[tuple[str, str], ...]
    raw_candle_fingerprint: str
    report_sha256: str

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = _jsonable(asdict(self))
        if not isinstance(payload, dict):
            raise TypeError("HTR-010B report must serialize to an object")
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
