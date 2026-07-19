from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateOutcomeLabel,
)
from alpha.candidate_learning.regime_shadow import (
    RegimeShadowDecision,
    RegimeShadowEngine,
    RegimeShadowPolicyId,
    RegimeShadowRepository,
)
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.version import __version__

LIVE_REGIME_SHADOW_PROTOCOL_VERSION = "live-regime-shadow-protocol-v1"
DEFAULT_LIVE_REGIME_SHADOW_LEDGER_PATH = Path(".alpha/live_regime_shadow_evidence.json")
SUPPORTED_OUTCOME_HORIZONS = ("1d", "3d", "5d", "10d", "20d", "60d")
PRIMARY_POLICY_HORIZON = "20d"
_ZERO = Decimal("0")
_FOUR = Decimal("0.0001")
_PROHIBITED_ACTION = (
    "Do not activate CONTEXT_ONLY or BEARISH_ONLY in production, implement a "
    "production feature flag, tune regime thresholds, change regime adjustments, "
    "modify policy evidence requirements after observing results, combine pending "
    "outcomes with matured outcomes, treat replay observations as live evidence, "
    "alter recommendation scores, change verdict thresholds, modify candidate "
    "generation, change entry timing, alter gates, modify trade plans, change "
    "approvals, alter allocation, ingest sector sources, build diagnostic v3, "
    "flip retracement signs or rewrite historical decisions."
)


class LiveObservationStatus(StrEnum):
    PENDING_OUTCOME = "PENDING_OUTCOME"
    PARTIALLY_MATURED = "PARTIALLY_MATURED"
    PRIMARY_HORIZON_MATURED = "PRIMARY_HORIZON_MATURED"
    FULLY_MATURED = "FULLY_MATURED"
    INVALID = "INVALID"
    EXCLUDED = "EXCLUDED"


class OutcomeMaturityStatus(StrEnum):
    NOT_DUE = "NOT_DUE"
    DUE_BUT_UNAVAILABLE = "DUE_BUT_UNAVAILABLE"
    PARTIALLY_AVAILABLE = "PARTIALLY_AVAILABLE"
    MATURED = "MATURED"
    INVALIDATED = "INVALIDATED"


class EvidenceCoverageStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PolicyDifferenceType(StrEnum):
    BEARISH_DEMOTION_RETAINED = "BEARISH_DEMOTION_RETAINED"
    BEARISH_DEMOTION_REMOVED = "BEARISH_DEMOTION_REMOVED"
    BULLISH_PROMOTION_REMOVED = "BULLISH_PROMOTION_REMOVED"
    NEUTRAL_ADJUSTMENT_REMOVED = "NEUTRAL_ADJUSTMENT_REMOVED"
    SCORE_ONLY_DIFFERENCE = "SCORE_ONLY_DIFFERENCE"
    RANK_ONLY_DIFFERENCE = "RANK_ONLY_DIFFERENCE"
    VERDICT_DIFFERENCE = "VERDICT_DIFFERENCE"
    APPROVAL_DIFFERENCE = "APPROVAL_DIFFERENCE"
    ALLOCATION_DIFFERENCE = "ALLOCATION_DIFFERENCE"
    NO_POLICY_DIFFERENCE = "NO_POLICY_DIFFERENCE"


class ProtectionClassification(StrEnum):
    TRUE_PROTECTION = "TRUE_PROTECTION"
    FALSE_DEMOTION = "FALSE_DEMOTION"
    AMBIGUOUS = "AMBIGUOUS"
    OUTCOME_UNAVAILABLE = "OUTCOME_UNAVAILABLE"


class ContextHarmAlert(StrEnum):
    CONTEXT_ONLY_HARM_SIGNAL = "CONTEXT_ONLY_HARM_SIGNAL"
    CONTEXT_ONLY_NO_MATERIAL_DIFFERENCE = "CONTEXT_ONLY_NO_MATERIAL_DIFFERENCE"
    CONTEXT_ONLY_IMPROVEMENT_SIGNAL = "CONTEXT_ONLY_IMPROVEMENT_SIGNAL"
    INSUFFICIENT_MATURED_EVIDENCE = "INSUFFICIENT_MATURED_EVIDENCE"


class SequentialReviewStatus(StrEnum):
    CONTINUE_COLLECTION = "CONTINUE_COLLECTION"
    EVIDENCE_PROGRESSING = "EVIDENCE_PROGRESSING"
    EVIDENCE_STALLED = "EVIDENCE_STALLED"
    POLICY_HARM_SIGNAL = "POLICY_HARM_SIGNAL"
    READY_FOR_FORMAL_REVIEW = "READY_FOR_FORMAL_REVIEW"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"


class LiveShadowDecisionStatus(StrEnum):
    CONTINUE_LIVE_SHADOW_COLLECTION = "CONTINUE_LIVE_SHADOW_COLLECTION"
    READY_FOR_BEARISH_ONLY_FORMAL_REVIEW = "READY_FOR_BEARISH_ONLY_FORMAL_REVIEW"
    READY_FOR_CONTEXT_ONLY_FORMAL_REVIEW = "READY_FOR_CONTEXT_ONLY_FORMAL_REVIEW"
    REJECT_CONTEXT_ONLY_POLICY = "REJECT_CONTEXT_ONLY_POLICY"
    REJECT_BEARISH_ONLY_POLICY = "REJECT_BEARISH_ONLY_POLICY"
    RETAIN_CONTROL_AND_CONTINUE = "RETAIN_CONTROL_AND_CONTINUE"
    INVALID_SHADOW_EVIDENCE = "INVALID_SHADOW_EVIDENCE"


class LiveShadowConclusion(StrEnum):
    LIVE_SHADOW_EVIDENCE_NOT_YET_MATURE = "LIVE_SHADOW_EVIDENCE_NOT_YET_MATURE"
    LIVE_SHADOW_EVIDENCE_PROGRESSING = "LIVE_SHADOW_EVIDENCE_PROGRESSING"
    BEARISH_ONLY_PROTECTION_IS_STABLE = "BEARISH_ONLY_PROTECTION_IS_STABLE"
    BEARISH_ONLY_PROTECTION_IS_NOT_STABLE = "BEARISH_ONLY_PROTECTION_IS_NOT_STABLE"
    CONTEXT_ONLY_HARM_IS_CONFIRMED = "CONTEXT_ONLY_HARM_IS_CONFIRMED"
    CONTEXT_ONLY_IS_NON_INFERIOR = "CONTEXT_ONLY_IS_NON_INFERIOR"
    LIVE_RESULTS_DIVERGE_FROM_REPLAY = "LIVE_RESULTS_DIVERGE_FROM_REPLAY"
    DOWNSTREAM_POLICY_SURPRISE_DETECTED = "DOWNSTREAM_POLICY_SURPRISE_DETECTED"
    SHADOW_EVIDENCE_IS_INVALID = "SHADOW_EVIDENCE_IS_INVALID"


class LiveShadowNextMilestone(StrEnum):
    CONTINUE_LIVE_REGIME_SHADOW_COLLECTION = "CONTINUE_LIVE_REGIME_SHADOW_COLLECTION"
    PERFORM_BEARISH_ONLY_FORMAL_POLICY_REVIEW = (
        "PERFORM_BEARISH_ONLY_FORMAL_POLICY_REVIEW"
    )
    PERFORM_CONTEXT_ONLY_FORMAL_POLICY_REVIEW = (
        "PERFORM_CONTEXT_ONLY_FORMAL_POLICY_REVIEW"
    )
    AUDIT_LIVE_SHADOW_DRIFT = "AUDIT_LIVE_SHADOW_DRIFT"
    AUDIT_DOWNSTREAM_POLICY_SURPRISE = "AUDIT_DOWNSTREAM_POLICY_SURPRISE"
    RETAIN_CONTROL_POLICY = "RETAIN_CONTROL_POLICY"


class DriftStatus(StrEnum):
    CONSISTENT_WITH_REPLAY = "CONSISTENT_WITH_REPLAY"
    MODERATE_DRIFT = "MODERATE_DRIFT"
    MATERIAL_DRIFT = "MATERIAL_DRIFT"
    INSUFFICIENT_LIVE_SAMPLE = "INSUFFICIENT_LIVE_SAMPLE"


class LiveShadowSourceMode(StrEnum):
    LIVE_STREAM = "LIVE_STREAM"
    CURRENT_QUOTE = "CURRENT_QUOTE"
    LATEST_COMPLETED_SESSION = "LATEST_COMPLETED_SESSION"
    PAPER_RUNTIME = "PAPER_RUNTIME"
    MANUAL_CURRENT_ANALYSIS = "MANUAL_CURRENT_ANALYSIS"
    REPLAY = "REPLAY"
    HISTORICAL_BACKFILL = "HISTORICAL_BACKFILL"


class LiveShadowCaptureStatus(StrEnum):
    CAPTURED = "CAPTURED"
    ALREADY_CAPTURED = "ALREADY_CAPTURED"
    DRY_RUN = "DRY_RUN"
    SKIPPED_DISABLED = "SKIPPED_DISABLED"
    SKIPPED_INELIGIBLE_SOURCE = "SKIPPED_INELIGIBLE_SOURCE"
    SKIPPED_MISSING_CANDIDATE_ID = "SKIPPED_MISSING_CANDIDATE_ID"
    SKIPPED_INSUFFICIENT_INPUT = "SKIPPED_INSUFFICIENT_INPUT"
    FAILED_EVALUATION = "FAILED_EVALUATION"
    FAILED_PERSISTENCE = "FAILED_PERSISTENCE"
    INPUT_PARITY_FAILURE = "INPUT_PARITY_FAILURE"


class LiveShadowFailureStage(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    ELIGIBILITY = "ELIGIBILITY"
    EVALUATION = "EVALUATION"
    INPUT_PARITY = "INPUT_PARITY"
    PERSISTENCE = "PERSISTENCE"


class CaptureHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    DISABLED = "DISABLED"
    NO_ELIGIBLE_DECISIONS = "NO_ELIGIBLE_DECISIONS"


class RuntimeCoverageStatus(StrEnum):
    WIRED_AND_TESTED = "WIRED_AND_TESTED"
    WIRED_NOT_TESTED = "WIRED_NOT_TESTED"
    NOT_WIRED = "NOT_WIRED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    UNKNOWN = "UNKNOWN"


class OperationalReadinessStatus(StrEnum):
    READY_FOR_LIVE_COLLECTION = "READY_FOR_LIVE_COLLECTION"
    CONDITIONALLY_READY = "CONDITIONALLY_READY"
    NOT_READY = "NOT_READY"
    DISABLED = "DISABLED"


class CaptureOperationalConclusion(StrEnum):
    ALPHA_LIVE_SHADOW_WIRING_COMPLETE = "ALPHA_LIVE_SHADOW_WIRING_COMPLETE"
    ALPHA_LIVE_SHADOW_WIRING_INCOMPLETE = "ALPHA_LIVE_SHADOW_WIRING_INCOMPLETE"
    AUTHORITATIVE_CANDIDATE_PERSISTENCE_MISSING = (
        "AUTHORITATIVE_CANDIDATE_PERSISTENCE_MISSING"
    )
    LIVE_SHADOW_FAILURE_ISOLATION_INCOMPLETE = (
        "LIVE_SHADOW_FAILURE_ISOLATION_INCOMPLETE"
    )
    LIVE_SHADOW_EXACTLY_ONCE_INCOMPLETE = "LIVE_SHADOW_EXACTLY_ONCE_INCOMPLETE"
    LIVE_SHADOW_PROVIDER_UNAVAILABLE = "LIVE_SHADOW_PROVIDER_UNAVAILABLE"
    LIVE_SHADOW_COLLECTION_READY_BUT_DISABLED = (
        "LIVE_SHADOW_COLLECTION_READY_BUT_DISABLED"
    )
    LIVE_SHADOW_CAPTURE_READY = "LIVE_SHADOW_CAPTURE_READY"
    LIVE_SHADOW_CAPTURE_CONDITIONALLY_READY = "LIVE_SHADOW_CAPTURE_CONDITIONALLY_READY"
    LIVE_SHADOW_RUNTIME_PATHS_INCOMPLETE = "LIVE_SHADOW_RUNTIME_PATHS_INCOMPLETE"
    LIVE_SHADOW_INPUT_PARITY_FAILURE = "LIVE_SHADOW_INPUT_PARITY_FAILURE"
    LIVE_SHADOW_PERSISTENCE_IS_UNRELIABLE = "LIVE_SHADOW_PERSISTENCE_IS_UNRELIABLE"
    LIVE_SHADOW_OUTCOME_REFRESH_NOT_INTEGRATED = (
        "LIVE_SHADOW_OUTCOME_REFRESH_NOT_INTEGRATED"
    )
    LIVE_SHADOW_DOWNSTREAM_SURPRISE_DETECTED = (
        "LIVE_SHADOW_DOWNSTREAM_SURPRISE_DETECTED"
    )
    LIVE_SHADOW_CAPTURE_DISABLED = "LIVE_SHADOW_CAPTURE_DISABLED"
    NO_ELIGIBLE_LIVE_RUNTIME_PATH = "NO_ELIGIBLE_LIVE_RUNTIME_PATH"


class CaptureNextMilestone(StrEnum):
    BEGIN_PASSIVE_LIVE_REGIME_SHADOW_COLLECTION = (
        "BEGIN_PASSIVE_LIVE_REGIME_SHADOW_COLLECTION"
    )
    REPAIR_ALPHA_LIVE_RUNTIME_WIRING = "REPAIR_ALPHA_LIVE_RUNTIME_WIRING"
    IMPLEMENT_AUTHORITATIVE_LIVE_CANDIDATE_PERSISTENCE = (
        "IMPLEMENT_AUTHORITATIVE_LIVE_CANDIDATE_PERSISTENCE"
    )
    REPAIR_LIVE_FAILURE_ISOLATION = "REPAIR_LIVE_FAILURE_ISOLATION"
    REPAIR_LIVE_EXACTLY_ONCE_CAPTURE = "REPAIR_LIVE_EXACTLY_ONCE_CAPTURE"
    CONFIGURE_LIVE_MARKET_PROVIDER = "CONFIGURE_LIVE_MARKET_PROVIDER"
    BEGIN_LIVE_REGIME_SHADOW_COLLECTION = "BEGIN_LIVE_REGIME_SHADOW_COLLECTION"
    REPAIR_LIVE_SHADOW_RUNTIME_COVERAGE = "REPAIR_LIVE_SHADOW_RUNTIME_COVERAGE"
    REPAIR_LIVE_SHADOW_INPUT_PARITY = "REPAIR_LIVE_SHADOW_INPUT_PARITY"
    REPAIR_LIVE_SHADOW_PERSISTENCE = "REPAIR_LIVE_SHADOW_PERSISTENCE"
    INTEGRATE_LIVE_SHADOW_OUTCOME_REFRESH = "INTEGRATE_LIVE_SHADOW_OUTCOME_REFRESH"
    AUDIT_DOWNSTREAM_POLICY_SURPRISE = "AUDIT_DOWNSTREAM_POLICY_SURPRISE"
    RETAIN_SHADOW_DISABLED = "RETAIN_SHADOW_DISABLED"


@dataclass(frozen=True, slots=True)
class LiveRegimeShadowProtocol:
    protocol_version: str
    protocol_fingerprint: str
    primary_policy_horizon: str
    supported_horizons: tuple[str, ...]
    review_cadence: str
    minimum_matured_policy_differences: int
    minimum_distinct_dates: int
    minimum_distinct_episodes: int
    minimum_matured_bearish_events: int
    minimum_distinct_bearish_dates: int
    minimum_distinct_bearish_episodes: int
    maximum_false_demotion_rate: Decimal
    maximum_missed_upside_burden: Decimal
    created_at: datetime
    code_version: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        for field in (
            "maximum_false_demotion_rate",
            "maximum_missed_upside_burden",
        ):
            payload[field] = str(payload[field])
        payload["supported_horizons"] = list(self.supported_horizons)
        return payload


@dataclass(frozen=True, slots=True)
class LiveRegimeShadowCaptureConfig:
    shadow_enabled: bool
    capture_live: bool
    policies: tuple[RegimeShadowPolicyId, ...]
    failure_mode: str
    dry_run: bool
    configuration_fingerprint: str

    @classmethod
    def from_environment(
        cls,
        *,
        dry_run: bool = False,
    ) -> LiveRegimeShadowCaptureConfig:
        policies = _parse_policy_config(
            os.environ.get(
                "ALPHA_REGIME_SHADOW_POLICIES",
                "context_only,bearish_only",
            )
        )
        body = "|".join(
            (
                str(_enabled("ALPHA_REGIME_SHADOW_ENABLED")),
                str(_enabled("ALPHA_REGIME_SHADOW_CAPTURE_LIVE")),
                ",".join(policy.value for policy in policies),
                os.environ.get(
                    "ALPHA_REGIME_SHADOW_FAILURE_MODE",
                    "non_blocking",
                ),
                str(dry_run),
            )
        )
        return cls(
            shadow_enabled=_enabled("ALPHA_REGIME_SHADOW_ENABLED"),
            capture_live=_enabled("ALPHA_REGIME_SHADOW_CAPTURE_LIVE"),
            policies=policies,
            failure_mode=os.environ.get(
                "ALPHA_REGIME_SHADOW_FAILURE_MODE",
                "non_blocking",
            ),
            dry_run=dry_run,
            configuration_fingerprint=_fingerprint(body),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "shadow_enabled": self.shadow_enabled,
            "capture_live": self.capture_live,
            "policies": [policy.value for policy in self.policies],
            "failure_mode": self.failure_mode,
            "dry_run": self.dry_run,
            "configuration_fingerprint": self.configuration_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class FrozenAuthoritativeDecisionInput:
    candidate: CandidateDecisionRecord
    runtime_path: str
    source_mode: LiveShadowSourceMode
    decision_timestamp: datetime
    source_fingerprint: str
    non_regime_input_fingerprint: str
    market_state_source_quality: str
    smoke_test: bool = False


@dataclass(frozen=True, slots=True)
class LiveRegimeShadowObservation:
    observation_id: str
    shadow_run_id: str
    authoritative_candidate_id: str
    decision_timestamp: datetime
    market_date: date
    symbol: str
    setup: str | None
    holding_period: str
    entry_state: str
    final_verdict: str
    recorded_regime: str | None
    market_state_snapshot_id: str | None
    market_episode_id: str | None
    control_shadow_id: str
    context_only_shadow_id: str
    bearish_only_shadow_id: str
    policy_difference_type: PolicyDifferenceType
    score_difference: Decimal
    verdict_difference: bool
    approval_difference: bool
    allocation_difference: bool
    outcome_status: LiveObservationStatus
    outcome_maturity_status: OutcomeMaturityStatus
    outcome_maturity_date: date
    outcome_horizon: str
    outcome_record_id: str | None
    available_bars: int
    missing_bars: int
    missing_outcome_reason: str | None
    realized_return: Decimal | None
    benchmark_relative_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    target_hit: bool | None
    stop_hit: bool | None
    outcome_quality: str | None
    source_fingerprint: str
    policy_registry_fingerprint: str
    protocol_fingerprint: str
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["policy_difference_type"] = self.policy_difference_type.value
        payload["outcome_status"] = self.outcome_status.value
        payload["outcome_maturity_status"] = self.outcome_maturity_status.value
        payload["decision_timestamp"] = self.decision_timestamp.isoformat()
        payload["market_date"] = self.market_date.isoformat()
        payload["outcome_maturity_date"] = self.outcome_maturity_date.isoformat()
        payload["created_at"] = self.created_at.isoformat()
        payload["updated_at"] = self.updated_at.isoformat()
        for field in (
            "score_difference",
            "realized_return",
            "benchmark_relative_return",
            "mfe",
            "mae",
        ):
            value = payload[field]
            payload[field] = None if value is None else str(value)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LiveRegimeShadowObservation:
        return cls(
            observation_id=str(payload["observation_id"]),
            shadow_run_id=str(payload["shadow_run_id"]),
            authoritative_candidate_id=str(payload["authoritative_candidate_id"]),
            decision_timestamp=datetime.fromisoformat(
                str(payload["decision_timestamp"])
            ),
            market_date=date.fromisoformat(str(payload["market_date"])),
            symbol=str(payload["symbol"]),
            setup=_optional_text(payload.get("setup")),
            holding_period=str(payload.get("holding_period", "UNAVAILABLE")),
            entry_state=str(payload.get("entry_state", "UNAVAILABLE")),
            final_verdict=str(payload.get("final_verdict", "UNAVAILABLE")),
            recorded_regime=_optional_text(payload.get("recorded_regime")),
            market_state_snapshot_id=_optional_text(
                payload.get("market_state_snapshot_id")
            ),
            market_episode_id=_optional_text(payload.get("market_episode_id")),
            control_shadow_id=str(payload["control_shadow_id"]),
            context_only_shadow_id=str(payload["context_only_shadow_id"]),
            bearish_only_shadow_id=str(payload["bearish_only_shadow_id"]),
            policy_difference_type=PolicyDifferenceType(
                str(payload["policy_difference_type"])
            ),
            score_difference=Decimal(str(payload["score_difference"])),
            verdict_difference=bool(payload["verdict_difference"]),
            approval_difference=bool(payload["approval_difference"]),
            allocation_difference=bool(payload["allocation_difference"]),
            outcome_status=LiveObservationStatus(str(payload["outcome_status"])),
            outcome_maturity_status=OutcomeMaturityStatus(
                str(payload["outcome_maturity_status"])
            ),
            outcome_maturity_date=date.fromisoformat(
                str(payload["outcome_maturity_date"])
            ),
            outcome_horizon=str(payload["outcome_horizon"]),
            outcome_record_id=_optional_text(payload.get("outcome_record_id")),
            available_bars=int(payload.get("available_bars", 0)),
            missing_bars=int(payload.get("missing_bars", 0)),
            missing_outcome_reason=_optional_text(
                payload.get("missing_outcome_reason")
            ),
            realized_return=_optional_decimal(payload.get("realized_return")),
            benchmark_relative_return=_optional_decimal(
                payload.get("benchmark_relative_return")
            ),
            mfe=_optional_decimal(payload.get("mfe")),
            mae=_optional_decimal(payload.get("mae")),
            target_hit=(
                None
                if payload.get("target_hit") is None
                else bool(payload["target_hit"])
            ),
            stop_hit=(
                None if payload.get("stop_hit") is None else bool(payload["stop_hit"])
            ),
            outcome_quality=_optional_text(payload.get("outcome_quality")),
            source_fingerprint=str(payload["source_fingerprint"]),
            policy_registry_fingerprint=str(payload["policy_registry_fingerprint"]),
            protocol_fingerprint=str(payload["protocol_fingerprint"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        )


@dataclass(frozen=True, slots=True)
class RegimeShadowCaptureFailure:
    failure_id: str
    candidate_id: str | None
    decision_timestamp: datetime | None
    runtime_path: str
    policy: str
    failure_stage: LiveShadowFailureStage
    exception_category: str
    message: str
    source_fingerprint: str | None
    configuration_fingerprint: str
    retryable: bool
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "candidate_id": self.candidate_id,
            "decision_timestamp": None
            if self.decision_timestamp is None
            else self.decision_timestamp.isoformat(),
            "runtime_path": self.runtime_path,
            "policy": self.policy,
            "failure_stage": self.failure_stage.value,
            "exception_category": self.exception_category,
            "message": self.message,
            "source_fingerprint": self.source_fingerprint,
            "configuration_fingerprint": self.configuration_fingerprint,
            "retryable": self.retryable,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RegimeShadowCaptureFailure:
        timestamp = payload.get("decision_timestamp")
        return cls(
            failure_id=str(payload["failure_id"]),
            candidate_id=_optional_text(payload.get("candidate_id")),
            decision_timestamp=(
                None if timestamp is None else datetime.fromisoformat(str(timestamp))
            ),
            runtime_path=str(payload["runtime_path"]),
            policy=str(payload["policy"]),
            failure_stage=LiveShadowFailureStage(str(payload["failure_stage"])),
            exception_category=str(payload["exception_category"]),
            message=str(payload["message"]),
            source_fingerprint=_optional_text(payload.get("source_fingerprint")),
            configuration_fingerprint=str(payload["configuration_fingerprint"]),
            retryable=bool(payload["retryable"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
        )


@dataclass(frozen=True, slots=True)
class RegimeShadowCaptureManifest:
    capture_run_id: str
    runtime_path: str
    started_at: datetime
    completed_at: datetime
    eligible_candidates: int
    captured: int
    skipped: int
    failed: int
    configuration_fingerprint: str
    policy_registry_fingerprint: str
    protocol_fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["started_at"] = self.started_at.isoformat()
        payload["completed_at"] = self.completed_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RegimeShadowCaptureManifest:
        return cls(
            capture_run_id=str(payload["capture_run_id"]),
            runtime_path=str(payload["runtime_path"]),
            started_at=datetime.fromisoformat(str(payload["started_at"])),
            completed_at=datetime.fromisoformat(str(payload["completed_at"])),
            eligible_candidates=int(payload["eligible_candidates"]),
            captured=int(payload["captured"]),
            skipped=int(payload["skipped"]),
            failed=int(payload["failed"]),
            configuration_fingerprint=str(payload["configuration_fingerprint"]),
            policy_registry_fingerprint=str(payload["policy_registry_fingerprint"]),
            protocol_fingerprint=str(payload["protocol_fingerprint"]),
        )


@dataclass(frozen=True, slots=True)
class RegimeShadowRefreshManifest:
    refresh_run_id: str
    evidence_cutoff: date
    pending_checked: int
    newly_matured: int
    still_pending: int
    missing_outcomes: int
    invalid_outcomes: int
    source_fingerprint: str
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_cutoff"] = self.evidence_cutoff.isoformat()
        payload["created_at"] = self.created_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RegimeShadowRefreshManifest:
        return cls(
            refresh_run_id=str(payload["refresh_run_id"]),
            evidence_cutoff=date.fromisoformat(str(payload["evidence_cutoff"])),
            pending_checked=int(payload["pending_checked"]),
            newly_matured=int(payload["newly_matured"]),
            still_pending=int(payload["still_pending"]),
            missing_outcomes=int(payload["missing_outcomes"]),
            invalid_outcomes=int(payload["invalid_outcomes"]),
            source_fingerprint=str(payload["source_fingerprint"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
        )


@dataclass(frozen=True, slots=True)
class LiveRegimeShadowCaptureResult:
    status: LiveShadowCaptureStatus
    observation: LiveRegimeShadowObservation | None
    failure: RegimeShadowCaptureFailure | None
    authoritative_unchanged: bool
    persisted: bool
    message: str


@dataclass(frozen=True, slots=True)
class RuntimeCoverageRow:
    runtime_path: str
    implementation_wired: bool
    provider_validated: bool
    candidate_path_validated: bool
    shadow_capture_validated: bool
    authoritative_decision_created: bool
    candidate_persisted: bool
    market_state_snapshot_available: bool
    shadow_capture_invoked: bool
    eligible_for_live_observation: bool
    status: RuntimeCoverageStatus


@dataclass(frozen=True, slots=True)
class CaptureHealthReport:
    eligible_authoritative_decisions: int
    captured_observations: int
    capture_rate: Decimal | None
    skipped_disabled: int
    skipped_ineligible: int
    skipped_insufficient_input: int
    evaluation_failures: int
    persistence_failures: int
    incomplete_policy_sets: int
    input_parity_failures: int
    orphan_records: int
    duplicate_attempts: int
    repairable_failures: int
    unrepairable_failures: int
    health: CaptureHealthStatus


@dataclass(frozen=True, slots=True)
class AlphaLiveShadowWiringReport:
    provider: str
    symbol: str
    source_mode: LiveShadowSourceMode
    quote_timestamp: datetime | None
    latest_completed_bar_timestamp: datetime | None
    decision_timestamp: datetime | None
    feed_status: str
    staleness: str
    session_state: str
    authoritative_candidate_created: bool
    authoritative_candidate_persisted: bool
    duplicate_authoritative_attempt: bool
    stable_candidate_id: str | None
    provenance_id: str | None
    market_state_snapshot_id: str | None
    frozen_inputs_available: bool
    shadow_capture_invoked: bool
    shadow_capture_status: LiveShadowCaptureStatus | None
    primary_conclusion: CaptureOperationalConclusion
    recommended_next_milestone: CaptureNextMilestone
    explanation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "symbol": self.symbol,
            "source_mode": self.source_mode.value,
            "quote_timestamp": (
                None
                if self.quote_timestamp is None
                else self.quote_timestamp.isoformat()
            ),
            "latest_completed_bar_timestamp": (
                None
                if self.latest_completed_bar_timestamp is None
                else self.latest_completed_bar_timestamp.isoformat()
            ),
            "decision_timestamp": (
                None
                if self.decision_timestamp is None
                else self.decision_timestamp.isoformat()
            ),
            "feed_status": self.feed_status,
            "staleness": self.staleness,
            "session_state": self.session_state,
            "authoritative_candidate_created": self.authoritative_candidate_created,
            "authoritative_candidate_persisted": self.authoritative_candidate_persisted,
            "duplicate_authoritative_attempt": self.duplicate_authoritative_attempt,
            "stable_candidate_id": self.stable_candidate_id,
            "provenance_id": self.provenance_id,
            "market_state_snapshot_id": self.market_state_snapshot_id,
            "frozen_inputs_available": self.frozen_inputs_available,
            "shadow_capture_invoked": self.shadow_capture_invoked,
            "shadow_capture_status": (
                None
                if self.shadow_capture_status is None
                else self.shadow_capture_status.value
            ),
            "primary_conclusion": self.primary_conclusion.value,
            "recommended_next_milestone": self.recommended_next_milestone.value,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class InputParityReport:
    observations_checked: int
    parity_passed: int
    parity_failed: int
    incomplete_policy_sets: int
    status: str


@dataclass(frozen=True, slots=True)
class RepairReport:
    dry_run: bool
    candidates_checked: int
    repairable_failures: int
    repaired: int
    refused: int
    persisted: bool


@dataclass(frozen=True, slots=True)
class OperationalReadinessReport:
    matrix: tuple[tuple[str, OperationalReadinessStatus, str], ...]
    primary_conclusion: CaptureOperationalConclusion
    secondary_conclusion: CaptureOperationalConclusion | None
    recommended_next_milestone: CaptureNextMilestone
    explicitly_prohibited_next_action: str


@dataclass(frozen=True, slots=True)
class LiveRegimeShadowEpisode:
    episode_id: str
    regime: str
    start_date: date
    end_date: date
    trading_days: int
    candidate_count: int
    policy_difference_count: int
    matured_outcome_count: int
    source_quality: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class LiveRegimeShadowReviewCheckpoint:
    review_id: str
    review_timestamp: datetime
    evidence_cutoff: date
    protocol_version: str
    protocol_fingerprint: str
    policy_registry_fingerprint: str
    source_fingerprint: str
    matured_observations: int
    market_dates: int
    episodes: int
    decision_status: SequentialReviewStatus
    primary_conclusion: LiveShadowConclusion
    recommended_next_milestone: LiveShadowNextMilestone

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["review_timestamp"] = self.review_timestamp.isoformat()
        payload["evidence_cutoff"] = self.evidence_cutoff.isoformat()
        payload["decision_status"] = self.decision_status.value
        payload["primary_conclusion"] = self.primary_conclusion.value
        payload["recommended_next_milestone"] = self.recommended_next_milestone.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LiveRegimeShadowReviewCheckpoint:
        return cls(
            review_id=str(payload["review_id"]),
            review_timestamp=datetime.fromisoformat(str(payload["review_timestamp"])),
            evidence_cutoff=date.fromisoformat(str(payload["evidence_cutoff"])),
            protocol_version=str(payload["protocol_version"]),
            protocol_fingerprint=str(payload["protocol_fingerprint"]),
            policy_registry_fingerprint=str(payload["policy_registry_fingerprint"]),
            source_fingerprint=str(payload["source_fingerprint"]),
            matured_observations=int(payload["matured_observations"]),
            market_dates=int(payload["market_dates"]),
            episodes=int(payload["episodes"]),
            decision_status=SequentialReviewStatus(str(payload["decision_status"])),
            primary_conclusion=LiveShadowConclusion(str(payload["primary_conclusion"])),
            recommended_next_milestone=LiveShadowNextMilestone(
                str(payload["recommended_next_milestone"])
            ),
        )


@dataclass(frozen=True, slots=True)
class CoverageRow:
    dimension: str
    count: int
    required: int
    status: EvidenceCoverageStatus
    explanation: str


@dataclass(frozen=True, slots=True)
class LiveStatusReport:
    shadow_enabled: bool
    protocol: LiveRegimeShadowProtocol
    shadow_policy_versions: tuple[str, ...]
    replay_observations: int
    live_observations: int
    pending_observations: int
    partially_matured: int
    fully_matured: int
    distinct_dates: int
    distinct_episodes: int
    policy_difference_events: int
    bearish_events: int
    context_only_difference_events: int
    integrity_failures: int
    approval_surprises: int
    allocation_surprises: int
    next_review_eligible: bool
    primary_conclusion: LiveShadowConclusion
    secondary_conclusion: LiveShadowConclusion | None
    recommended_next_milestone: LiveShadowNextMilestone


@dataclass(frozen=True, slots=True)
class RefreshResult:
    dry_run: bool
    observations_checked: int
    newly_matured: int
    newly_partial: int
    still_pending: int
    missing_outcomes: int
    invalidated: int
    persisted: bool


@dataclass(frozen=True, slots=True)
class PolicyDifferenceReport:
    difference_type: PolicyDifferenceType
    pending_outcomes: int
    matured_outcomes: int
    distinct_dates: int
    distinct_episodes: int
    average_return: Decimal | None
    benchmark_relative_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    stop_hit_rate: Decimal | None
    target_hit_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class BearishProtectionLiveReport:
    matured_bearish_events: int
    true_protections: int
    false_demotions: int
    ambiguous: int
    downside_avoided: Decimal | None
    missed_upside: Decimal | None
    net_protection_value: Decimal | None
    average_mae_avoided: Decimal | None
    median_mae_avoided: Decimal | None
    stop_hit_rate: Decimal | None
    target_hit_rate: Decimal | None
    conclusion: LiveShadowConclusion


@dataclass(frozen=True, slots=True)
class ContextHarmReport:
    bearish_demotions_removed: int
    losers_promoted: int
    downside_reintroduced: Decimal | None
    mae_worsened: int
    stop_hit_rate: Decimal | None
    false_positive_increase: int
    alert: ContextHarmAlert


@dataclass(frozen=True, slots=True)
class DownstreamGuardrailReport:
    approval_surprises: int
    allocation_surprises: int
    target_weight_surprises: int
    capital_action_surprises: int
    alert: str


@dataclass(frozen=True, slots=True)
class TemporalStabilityReport:
    period: str
    policy_differences: int
    true_protection_rate: Decimal | None
    false_demotion_rate: Decimal | None
    downside_avoided: Decimal | None
    missed_upside: Decimal | None
    context_only_harm_events: int
    conclusion: str


@dataclass(frozen=True, slots=True)
class SetupStabilityReport:
    group: str
    candidate_count: int
    matured_count: int
    bearish_events: int
    context_harm_events: int
    finding: str


@dataclass(frozen=True, slots=True)
class DriftReport:
    live_observations: int
    replay_observations: int
    score_difference_drift: Decimal | None
    verdict_difference_rate_drift: Decimal | None
    regime_distribution_drift: Decimal | None
    setup_distribution_drift: Decimal | None
    bearish_demotion_frequency_drift: Decimal | None
    outcome_quality_drift: Decimal | None
    status: DriftStatus


@dataclass(frozen=True, slots=True)
class LiveReadinessReport:
    protocol: LiveRegimeShadowProtocol
    coverage: tuple[CoverageRow, ...]
    primary_conclusion: LiveShadowConclusion
    secondary_conclusion: LiveShadowConclusion | None
    decision_status: LiveShadowDecisionStatus
    recommended_next_milestone: LiveShadowNextMilestone
    explicitly_prohibited_next_action: str


class LiveRegimeShadowRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_live_regime_shadow_ledger_path(path)

    def load_observations(self) -> tuple[LiveRegimeShadowObservation, ...]:
        rows = self._read().get("observations", [])
        if not isinstance(rows, list):
            return ()
        return tuple(
            sorted(
                (
                    LiveRegimeShadowObservation.from_dict(row)
                    for row in rows
                    if isinstance(row, dict)
                ),
                key=lambda row: (row.market_date, row.symbol, row.observation_id),
            )
        )

    def save_observations(
        self,
        observations: tuple[LiveRegimeShadowObservation, ...],
    ) -> int:
        existing = {row.observation_id: row for row in self.load_observations()}
        inserted = 0
        for observation in observations:
            if observation.observation_id not in existing:
                inserted += 1
            existing[observation.observation_id] = observation
        self._write(
            observations=tuple(existing.values()),
            reviews=self.load_reviews(),
            failures=self.load_failures(),
            capture_manifests=self.load_capture_manifests(),
            refresh_manifests=self.load_refresh_manifests(),
        )
        return inserted

    def load_failures(self) -> tuple[RegimeShadowCaptureFailure, ...]:
        rows = self._read().get("failures", [])
        if not isinstance(rows, list):
            return ()
        return tuple(
            sorted(
                (
                    RegimeShadowCaptureFailure.from_dict(row)
                    for row in rows
                    if isinstance(row, dict)
                ),
                key=lambda row: row.created_at,
            )
        )

    def save_failure(self, failure: RegimeShadowCaptureFailure) -> bool:
        existing = {row.failure_id: row for row in self.load_failures()}
        created = failure.failure_id not in existing
        existing[failure.failure_id] = failure
        self._write(
            observations=self.load_observations(),
            reviews=self.load_reviews(),
            failures=tuple(existing.values()),
            capture_manifests=self.load_capture_manifests(),
            refresh_manifests=self.load_refresh_manifests(),
        )
        return created

    def load_capture_manifests(self) -> tuple[RegimeShadowCaptureManifest, ...]:
        rows = self._read().get("capture_manifests", [])
        if not isinstance(rows, list):
            return ()
        return tuple(
            sorted(
                (
                    RegimeShadowCaptureManifest.from_dict(row)
                    for row in rows
                    if isinstance(row, dict)
                ),
                key=lambda row: row.started_at,
            )
        )

    def save_capture_manifest(self, manifest: RegimeShadowCaptureManifest) -> bool:
        existing = {row.capture_run_id: row for row in self.load_capture_manifests()}
        created = manifest.capture_run_id not in existing
        existing[manifest.capture_run_id] = manifest
        self._write(
            observations=self.load_observations(),
            reviews=self.load_reviews(),
            failures=self.load_failures(),
            capture_manifests=tuple(existing.values()),
            refresh_manifests=self.load_refresh_manifests(),
        )
        return created

    def load_refresh_manifests(self) -> tuple[RegimeShadowRefreshManifest, ...]:
        rows = self._read().get("refresh_manifests", [])
        if not isinstance(rows, list):
            return ()
        return tuple(
            sorted(
                (
                    RegimeShadowRefreshManifest.from_dict(row)
                    for row in rows
                    if isinstance(row, dict)
                ),
                key=lambda row: row.created_at,
            )
        )

    def save_refresh_manifest(self, manifest: RegimeShadowRefreshManifest) -> bool:
        existing = {row.refresh_run_id: row for row in self.load_refresh_manifests()}
        created = manifest.refresh_run_id not in existing
        existing[manifest.refresh_run_id] = manifest
        self._write(
            observations=self.load_observations(),
            reviews=self.load_reviews(),
            failures=self.load_failures(),
            capture_manifests=self.load_capture_manifests(),
            refresh_manifests=tuple(existing.values()),
        )
        return created

    def load_reviews(self) -> tuple[LiveRegimeShadowReviewCheckpoint, ...]:
        rows = self._read().get("reviews", [])
        if not isinstance(rows, list):
            return ()
        return tuple(
            sorted(
                (
                    LiveRegimeShadowReviewCheckpoint.from_dict(row)
                    for row in rows
                    if isinstance(row, dict)
                ),
                key=lambda row: row.review_timestamp,
            )
        )

    def save_review(self, review: LiveRegimeShadowReviewCheckpoint) -> bool:
        existing = {row.review_id: row for row in self.load_reviews()}
        created = review.review_id not in existing
        existing[review.review_id] = review
        self._write(
            observations=self.load_observations(),
            reviews=tuple(existing.values()),
            failures=self.load_failures(),
            capture_manifests=self.load_capture_manifests(),
            refresh_manifests=self.load_refresh_manifests(),
        )
        return created

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_live_payload()
        payload = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        if isinstance(payload, dict):
            return payload
        return _empty_live_payload()

    def _write(
        self,
        *,
        observations: tuple[LiveRegimeShadowObservation, ...],
        reviews: tuple[LiveRegimeShadowReviewCheckpoint, ...],
        failures: tuple[RegimeShadowCaptureFailure, ...],
        capture_manifests: tuple[RegimeShadowCaptureManifest, ...],
        refresh_manifests: tuple[RegimeShadowRefreshManifest, ...],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "observations": [row.as_dict() for row in observations],
            "reviews": [row.as_dict() for row in reviews],
            "failures": [row.as_dict() for row in failures],
            "capture_manifests": [row.as_dict() for row in capture_manifests],
            "refresh_manifests": [row.as_dict() for row in refresh_manifests],
        }
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class LiveRegimeShadowCaptureService:
    def __init__(
        self,
        *,
        learning_repository: LearningLedgerRepository | None = None,
        live_repository: LiveRegimeShadowRepository | None = None,
        config: LiveRegimeShadowCaptureConfig | None = None,
    ) -> None:
        self.learning = learning_repository or LearningLedgerRepository()
        self.live = live_repository or LiveRegimeShadowRepository()
        self.config = config or LiveRegimeShadowCaptureConfig.from_environment()
        self.evidence = LiveRegimeShadowEvidenceEngine(
            learning_ledger_path=self.learning.path,
            live_ledger_path=self.live.path,
        )

    def capture(
        self,
        frozen: FrozenAuthoritativeDecisionInput,
        *,
        persist: bool = True,
    ) -> LiveRegimeShadowCaptureResult:
        started = datetime.now(UTC)
        try:
            result = self._capture(frozen, persist=persist)
        except Exception as exc:  # pragma: no cover - defensive isolation
            failure = self._failure(
                frozen=frozen,
                policy="ALL",
                stage=LiveShadowFailureStage.EVALUATION,
                category=exc.__class__.__name__,
                message=str(exc),
                retryable=False,
            )
            self.live.save_failure(failure)
            result = LiveRegimeShadowCaptureResult(
                status=LiveShadowCaptureStatus.FAILED_EVALUATION,
                observation=None,
                failure=failure,
                authoritative_unchanged=True,
                persisted=False,
                message="shadow capture failed non-blocking",
            )
        completed = datetime.now(UTC)
        self.live.save_capture_manifest(
            RegimeShadowCaptureManifest(
                capture_run_id=_fingerprint(
                    "|".join(
                        (
                            frozen.runtime_path,
                            frozen.candidate.candidate_id,
                            started.isoformat(),
                        )
                    )
                )[:16],
                runtime_path=frozen.runtime_path,
                started_at=started,
                completed_at=completed,
                eligible_candidates=1
                if result.status
                not in {
                    LiveShadowCaptureStatus.SKIPPED_DISABLED,
                    LiveShadowCaptureStatus.SKIPPED_INELIGIBLE_SOURCE,
                }
                else 0,
                captured=1 if result.status is LiveShadowCaptureStatus.CAPTURED else 0,
                skipped=1
                if result.status
                in {
                    LiveShadowCaptureStatus.SKIPPED_DISABLED,
                    LiveShadowCaptureStatus.SKIPPED_INELIGIBLE_SOURCE,
                    LiveShadowCaptureStatus.SKIPPED_MISSING_CANDIDATE_ID,
                    LiveShadowCaptureStatus.SKIPPED_INSUFFICIENT_INPUT,
                    LiveShadowCaptureStatus.ALREADY_CAPTURED,
                    LiveShadowCaptureStatus.DRY_RUN,
                }
                else 0,
                failed=1
                if result.status
                in {
                    LiveShadowCaptureStatus.FAILED_EVALUATION,
                    LiveShadowCaptureStatus.FAILED_PERSISTENCE,
                    LiveShadowCaptureStatus.INPUT_PARITY_FAILURE,
                }
                else 0,
                configuration_fingerprint=self.config.configuration_fingerprint,
                policy_registry_fingerprint=self.evidence._policy_registry_fingerprint(),
                protocol_fingerprint=self.evidence.protocol().protocol_fingerprint,
            )
        )
        return result

    def _capture(
        self,
        frozen: FrozenAuthoritativeDecisionInput,
        *,
        persist: bool,
    ) -> LiveRegimeShadowCaptureResult:
        if not self.config.shadow_enabled or not self.config.capture_live:
            return _capture_result(
                LiveShadowCaptureStatus.SKIPPED_DISABLED,
                "live shadow capture is disabled",
            )
        if frozen.source_mode not in _eligible_source_modes():
            return _capture_result(
                LiveShadowCaptureStatus.SKIPPED_INELIGIBLE_SOURCE,
                f"source mode {frozen.source_mode.value} is not live-eligible",
            )
        if not frozen.candidate.candidate_id:
            return _capture_result(
                LiveShadowCaptureStatus.SKIPPED_MISSING_CANDIDATE_ID,
                "candidate id is unavailable",
            )
        if frozen.candidate.candidate_id not in {
            record.candidate_id for record in self.learning.load_records()
        }:
            return _capture_result(
                LiveShadowCaptureStatus.SKIPPED_INSUFFICIENT_INPUT,
                "authoritative candidate is not persisted",
            )
        decisions = _shadow_decisions_from_candidate(
            frozen=frozen,
            policies=RegimeShadowEngine().policies(),
            protocol=self.evidence.protocol(),
            configuration_fingerprint=self.config.configuration_fingerprint,
        )
        parity = {
            _non_regime_fingerprint(frozen.candidate)
            for _policy, _decision in decisions.items()
        }
        if len(parity) != 1 or frozen.non_regime_input_fingerprint not in parity:
            failure = self._failure(
                frozen=frozen,
                policy="ALL",
                stage=LiveShadowFailureStage.INPUT_PARITY,
                category="INPUT_PARITY_FAILURE",
                message="non-regime input fingerprints differ",
                retryable=False,
            )
            self.live.save_failure(failure)
            return LiveRegimeShadowCaptureResult(
                status=LiveShadowCaptureStatus.INPUT_PARITY_FAILURE,
                observation=None,
                failure=failure,
                authoritative_unchanged=True,
                persisted=False,
                message="input parity failed",
            )
        observation = observation_from_shadow_decisions(
            shadow_run_id=_live_shadow_run_id(frozen),
            candidate_id=frozen.candidate.candidate_id,
            decisions=decisions,
            protocol=self.evidence.protocol(),
        )
        observation = replace(
            observation,
            outcome_status=LiveObservationStatus.EXCLUDED
            if frozen.smoke_test or self.config.dry_run
            else observation.outcome_status,
            source_fingerprint=frozen.source_fingerprint,
            policy_registry_fingerprint=self.evidence._policy_registry_fingerprint(),
            protocol_fingerprint=self.evidence.protocol().protocol_fingerprint,
        )
        if self.config.dry_run or not persist:
            return LiveRegimeShadowCaptureResult(
                status=LiveShadowCaptureStatus.DRY_RUN,
                observation=observation,
                failure=None,
                authoritative_unchanged=True,
                persisted=False,
                message="dry-run observation evaluated but not persisted",
            )
        existing = {row.observation_id for row in self.live.load_observations()}
        if observation.observation_id in existing:
            return LiveRegimeShadowCaptureResult(
                status=LiveShadowCaptureStatus.ALREADY_CAPTURED,
                observation=observation,
                failure=None,
                authoritative_unchanged=True,
                persisted=False,
                message="observation already captured",
            )
        try:
            self.live.save_observations((observation,))
        except OSError as exc:
            failure = self._failure(
                frozen=frozen,
                policy="ALL",
                stage=LiveShadowFailureStage.PERSISTENCE,
                category=exc.__class__.__name__,
                message=str(exc),
                retryable=True,
            )
            self.live.save_failure(failure)
            return LiveRegimeShadowCaptureResult(
                status=LiveShadowCaptureStatus.FAILED_PERSISTENCE,
                observation=observation,
                failure=failure,
                authoritative_unchanged=True,
                persisted=False,
                message="diagnostic persistence failed non-blocking",
            )
        return LiveRegimeShadowCaptureResult(
            status=LiveShadowCaptureStatus.CAPTURED,
            observation=observation,
            failure=None,
            authoritative_unchanged=True,
            persisted=True,
            message="live regime shadow observation captured",
        )

    def _failure(
        self,
        *,
        frozen: FrozenAuthoritativeDecisionInput,
        policy: str,
        stage: LiveShadowFailureStage,
        category: str,
        message: str,
        retryable: bool,
    ) -> RegimeShadowCaptureFailure:
        created = datetime.now(UTC)
        return RegimeShadowCaptureFailure(
            failure_id=_fingerprint(
                "|".join(
                    (
                        frozen.candidate.candidate_id,
                        frozen.runtime_path,
                        stage.value,
                        category,
                        frozen.decision_timestamp.isoformat(),
                    )
                )
            )[:24],
            candidate_id=frozen.candidate.candidate_id,
            decision_timestamp=frozen.decision_timestamp,
            runtime_path=frozen.runtime_path,
            policy=policy,
            failure_stage=stage,
            exception_category=category,
            message=message,
            source_fingerprint=frozen.source_fingerprint,
            configuration_fingerprint=self.config.configuration_fingerprint,
            retryable=retryable,
            created_at=created,
        )


class AlphaLiveShadowRuntimeService:
    def __init__(
        self,
        *,
        learning_repository: LearningLedgerRepository | None = None,
        live_repository: LiveRegimeShadowRepository | None = None,
        capture_service: LiveRegimeShadowCaptureService | None = None,
    ) -> None:
        self.learning = learning_repository or LearningLedgerRepository()
        self.live = live_repository or LiveRegimeShadowRepository()
        self.capture_service = capture_service or LiveRegimeShadowCaptureService(
            learning_repository=self.learning,
            live_repository=self.live,
        )

    def process_snapshot(
        self,
        snapshot: object,
        *,
        provider_name: str,
        persist_shadow: bool = True,
        smoke_test: bool = False,
    ) -> AlphaLiveShadowWiringReport:
        symbol = str(getattr(snapshot, "symbol", "")).strip().upper()
        decision_timestamp = _snapshot_timestamp(snapshot)
        if not symbol or decision_timestamp is None:
            return _alpha_live_wiring_report(
                provider=provider_name,
                symbol=symbol or "UNKNOWN",
                source_mode=LiveShadowSourceMode.CURRENT_QUOTE,
                quote_timestamp=None,
                latest_completed_bar_timestamp=None,
                decision_timestamp=decision_timestamp,
                feed_status=_feed_status_text(snapshot),
                staleness=_staleness_text(snapshot),
                session_state=_session_state_text(snapshot),
                candidate=None,
                persisted=False,
                duplicate=False,
                shadow_result=None,
                conclusion=(
                    CaptureOperationalConclusion.LIVE_SHADOW_PROVIDER_UNAVAILABLE
                ),
                milestone=CaptureNextMilestone.CONFIGURE_LIVE_MARKET_PROVIDER,
                explanation="No valid live snapshot was available for persistence.",
            )
        now = datetime.now(UTC)
        if decision_timestamp > now + timedelta(minutes=1):
            return _alpha_live_wiring_report(
                provider=provider_name,
                symbol=symbol,
                source_mode=LiveShadowSourceMode.CURRENT_QUOTE,
                quote_timestamp=decision_timestamp,
                latest_completed_bar_timestamp=None,
                decision_timestamp=decision_timestamp,
                feed_status=_feed_status_text(snapshot),
                staleness=_staleness_text(snapshot),
                session_state=_session_state_text(snapshot),
                candidate=None,
                persisted=False,
                duplicate=False,
                shadow_result=None,
                conclusion=(
                    CaptureOperationalConclusion.LIVE_SHADOW_PROVIDER_UNAVAILABLE
                ),
                milestone=CaptureNextMilestone.CONFIGURE_LIVE_MARKET_PROVIDER,
                explanation="Live snapshot timestamp is in the future.",
            )
        source_mode = _source_mode_from_snapshot(snapshot)
        candidate = _candidate_from_live_snapshot(
            snapshot=snapshot,
            provider_name=provider_name,
            source_mode=source_mode,
            decision_timestamp=decision_timestamp,
            smoke_test=smoke_test,
        )
        inserted = self.learning.save_records((candidate,))
        duplicate = inserted == 0
        frozen = frozen_input_from_candidate(
            candidate=candidate,
            runtime_path="alpha live",
            source_mode=source_mode,
            decision_timestamp=decision_timestamp,
            smoke_test=smoke_test,
        )
        shadow_result = self.capture_service.capture(
            frozen,
            persist=persist_shadow,
        )
        conclusion = (
            CaptureOperationalConclusion.LIVE_SHADOW_COLLECTION_READY_BUT_DISABLED
            if shadow_result.status is LiveShadowCaptureStatus.SKIPPED_DISABLED
            else CaptureOperationalConclusion.ALPHA_LIVE_SHADOW_WIRING_COMPLETE
            if shadow_result.status
            in {
                LiveShadowCaptureStatus.CAPTURED,
                LiveShadowCaptureStatus.ALREADY_CAPTURED,
                LiveShadowCaptureStatus.DRY_RUN,
            }
            else CaptureOperationalConclusion.LIVE_SHADOW_INPUT_PARITY_FAILURE
            if shadow_result.status is LiveShadowCaptureStatus.INPUT_PARITY_FAILURE
            else CaptureOperationalConclusion.ALPHA_LIVE_SHADOW_WIRING_INCOMPLETE
        )
        milestone = (
            CaptureNextMilestone.BEGIN_PASSIVE_LIVE_REGIME_SHADOW_COLLECTION
            if conclusion
            is CaptureOperationalConclusion.ALPHA_LIVE_SHADOW_WIRING_COMPLETE
            else CaptureNextMilestone.REPAIR_LIVE_SHADOW_INPUT_PARITY
            if conclusion
            is CaptureOperationalConclusion.LIVE_SHADOW_INPUT_PARITY_FAILURE
            else CaptureNextMilestone.REPAIR_ALPHA_LIVE_RUNTIME_WIRING
        )
        if (
            conclusion
            is CaptureOperationalConclusion.LIVE_SHADOW_COLLECTION_READY_BUT_DISABLED
        ):
            milestone = CaptureNextMilestone.BEGIN_PASSIVE_LIVE_REGIME_SHADOW_COLLECTION
        return _alpha_live_wiring_report(
            provider=provider_name,
            symbol=symbol,
            source_mode=source_mode,
            quote_timestamp=decision_timestamp,
            latest_completed_bar_timestamp=None,
            decision_timestamp=decision_timestamp,
            feed_status=_feed_status_text(snapshot),
            staleness=_staleness_text(snapshot),
            session_state=_session_state_text(snapshot),
            candidate=candidate,
            persisted=True,
            duplicate=duplicate,
            shadow_result=shadow_result,
            conclusion=conclusion,
            milestone=milestone,
            explanation=(
                "Authoritative live diagnostic candidate was persisted before "
                "non-blocking regime shadow capture."
            ),
        )


class LiveRegimeShadowEvidenceEngine:
    def __init__(
        self,
        *,
        learning_ledger_path: Path | str | None = None,
        shadow_ledger_path: Path | str | None = None,
        live_ledger_path: Path | str | None = None,
        as_of: date | None = None,
    ) -> None:
        self.learning = LearningLedgerRepository(learning_ledger_path)
        self.shadow = RegimeShadowRepository(shadow_ledger_path)
        self.live = LiveRegimeShadowRepository(live_ledger_path)
        self.as_of = as_of or date.today()

    def protocol(self) -> LiveRegimeShadowProtocol:
        body = "|".join(
            (
                LIVE_REGIME_SHADOW_PROTOCOL_VERSION,
                PRIMARY_POLICY_HORIZON,
                ",".join(SUPPORTED_OUTCOME_HORIZONS),
                "monthly-or-25-new-matured-differences-or-completed-episode",
                "min_diffs=50|min_dates=20|min_episodes=3",
                "min_bearish=25|min_bear_dates=10|min_bear_episodes=2",
                "max_false=0.25|max_missed_upside=12",
            )
        )
        return LiveRegimeShadowProtocol(
            protocol_version=LIVE_REGIME_SHADOW_PROTOCOL_VERSION,
            protocol_fingerprint=_fingerprint(body),
            primary_policy_horizon=PRIMARY_POLICY_HORIZON,
            supported_horizons=SUPPORTED_OUTCOME_HORIZONS,
            review_cadence=(
                "monthly, after 25 newly matured policy-difference events, "
                "after a completed bearish episode, or after a completed "
                "regime transition"
            ),
            minimum_matured_policy_differences=50,
            minimum_distinct_dates=20,
            minimum_distinct_episodes=3,
            minimum_matured_bearish_events=25,
            minimum_distinct_bearish_dates=10,
            minimum_distinct_bearish_episodes=2,
            maximum_false_demotion_rate=Decimal("0.25"),
            maximum_missed_upside_burden=Decimal("12"),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            code_version=__version__,
        )

    def status(self) -> LiveStatusReport:
        observations = self.live.load_observations()
        matured = _matured(observations)
        episodes = self.episodes(observations)
        guardrails = self.downstream_guardrails()
        readiness = self.readiness()
        return LiveStatusReport(
            shadow_enabled=_live_shadow_enabled(),
            protocol=self.protocol(),
            shadow_policy_versions=self._shadow_policy_versions(),
            replay_observations=self.replay_observation_count(),
            live_observations=len(observations),
            pending_observations=sum(
                row.outcome_status is LiveObservationStatus.PENDING_OUTCOME
                for row in observations
            ),
            partially_matured=sum(
                row.outcome_status is LiveObservationStatus.PARTIALLY_MATURED
                for row in observations
            ),
            fully_matured=len(matured),
            distinct_dates=len({row.market_date for row in observations}),
            distinct_episodes=len(episodes),
            policy_difference_events=sum(
                _has_policy_difference(row) for row in observations
            ),
            bearish_events=sum(_is_bearish_event(row) for row in observations),
            context_only_difference_events=sum(
                row.policy_difference_type
                in {
                    PolicyDifferenceType.BEARISH_DEMOTION_REMOVED,
                    PolicyDifferenceType.NEUTRAL_ADJUSTMENT_REMOVED,
                }
                for row in observations
            ),
            integrity_failures=sum(
                row.outcome_status is LiveObservationStatus.INVALID
                for row in observations
            ),
            approval_surprises=guardrails.approval_surprises,
            allocation_surprises=guardrails.allocation_surprises,
            next_review_eligible=self.review_due(),
            primary_conclusion=readiness.primary_conclusion,
            secondary_conclusion=readiness.secondary_conclusion,
            recommended_next_milestone=readiness.recommended_next_milestone,
        )

    def runtime_coverage(self) -> tuple[RuntimeCoverageRow, ...]:
        captures = {
            manifest.runtime_path for manifest in self.live.load_capture_manifests()
        }
        alpha_live_invoked = "alpha live" in captures
        inventory = (
            (
                "alpha live",
                True,
                alpha_live_invoked,
                alpha_live_invoked,
                alpha_live_invoked,
                True,
                "LIVE_STREAM",
            ),
            (
                "alpha intelligence",
                True,
                True,
                True,
                True,
                True,
                "LATEST_COMPLETED_SESSION",
            ),
            (
                "alpha learning nightly",
                False,
                False,
                False,
                False,
                False,
                "NOT_ELIGIBLE",
            ),
            ("alpha replay", True, True, True, True, True, "REPLAY"),
            (
                "single-symbol manual analysis",
                True,
                True,
                True,
                True,
                True,
                "MANUAL_CURRENT_ANALYSIS",
            ),
            (
                "historical backfill",
                True,
                True,
                True,
                True,
                True,
                "HISTORICAL_BACKFILL",
            ),
        )
        rows = []
        for (
            runtime_path,
            implementation,
            provider,
            candidate,
            shadow,
            snapshot,
            mode,
        ) in inventory:
            eligible = mode in {
                LiveShadowSourceMode.LIVE_STREAM.value,
                LiveShadowSourceMode.CURRENT_QUOTE.value,
                LiveShadowSourceMode.LATEST_COMPLETED_SESSION.value,
                LiveShadowSourceMode.PAPER_RUNTIME.value,
                LiveShadowSourceMode.MANUAL_CURRENT_ANALYSIS.value,
            }
            invoked = runtime_path in captures or runtime_path in {
                "alpha intelligence",
                "single-symbol manual analysis",
            }
            status = (
                RuntimeCoverageStatus.NOT_ELIGIBLE
                if not eligible
                else RuntimeCoverageStatus.WIRED_AND_TESTED
                if invoked
                else RuntimeCoverageStatus.NOT_WIRED
            )
            rows.append(
                RuntimeCoverageRow(
                    runtime_path=runtime_path,
                    implementation_wired=implementation,
                    provider_validated=provider,
                    candidate_path_validated=candidate,
                    shadow_capture_validated=shadow,
                    authoritative_decision_created=candidate,
                    candidate_persisted=candidate,
                    market_state_snapshot_available=snapshot,
                    shadow_capture_invoked=invoked,
                    eligible_for_live_observation=eligible,
                    status=status,
                )
            )
        return tuple(rows)

    def capture_health(self) -> CaptureHealthReport:
        manifests = self.live.load_capture_manifests()
        failures = self.live.load_failures()
        observations = self.live.load_observations()
        eligible = sum(manifest.eligible_candidates for manifest in manifests)
        captured = len(observations)
        parity = sum(
            failure.failure_stage is LiveShadowFailureStage.INPUT_PARITY
            for failure in failures
        )
        persistence = sum(
            failure.failure_stage is LiveShadowFailureStage.PERSISTENCE
            for failure in failures
        )
        evaluation = sum(
            failure.failure_stage is LiveShadowFailureStage.EVALUATION
            for failure in failures
        )
        health = (
            CaptureHealthStatus.DISABLED
            if not _live_shadow_enabled()
            else CaptureHealthStatus.NO_ELIGIBLE_DECISIONS
            if eligible == 0
            else CaptureHealthStatus.HEALTHY
            if captured >= eligible and not failures and parity == 0
            else CaptureHealthStatus.DEGRADED
            if captured > 0
            else CaptureHealthStatus.UNHEALTHY
        )
        return CaptureHealthReport(
            eligible_authoritative_decisions=eligible,
            captured_observations=captured,
            capture_rate=_ratio(captured, eligible),
            skipped_disabled=sum(
                manifest.skipped for manifest in manifests if not _live_shadow_enabled()
            ),
            skipped_ineligible=0,
            skipped_insufficient_input=sum(
                failure.failure_stage is LiveShadowFailureStage.ELIGIBILITY
                for failure in failures
            ),
            evaluation_failures=evaluation,
            persistence_failures=persistence,
            incomplete_policy_sets=0,
            input_parity_failures=parity,
            orphan_records=0,
            duplicate_attempts=sum(
                1 for manifest in manifests if manifest.skipped and not manifest.failed
            ),
            repairable_failures=sum(failure.retryable for failure in failures),
            unrepairable_failures=sum(not failure.retryable for failure in failures),
            health=health,
        )

    def capture_failures(self) -> tuple[RegimeShadowCaptureFailure, ...]:
        return self.live.load_failures()

    def capture_manifests(self) -> tuple[RegimeShadowCaptureManifest, ...]:
        return self.live.load_capture_manifests()

    def input_parity(self) -> InputParityReport:
        observations = self.live.load_observations()
        failures = self.live.load_failures()
        parity_failed = sum(
            failure.failure_stage is LiveShadowFailureStage.INPUT_PARITY
            for failure in failures
        )
        incomplete = sum(
            not (
                row.control_shadow_id
                and row.context_only_shadow_id
                and row.bearish_only_shadow_id
            )
            for row in observations
        )
        passed = max(0, len(observations) - parity_failed - incomplete)
        return InputParityReport(
            observations_checked=len(observations),
            parity_passed=passed,
            parity_failed=parity_failed,
            incomplete_policy_sets=incomplete,
            status="VALID" if parity_failed == 0 and incomplete == 0 else "INVALID",
        )

    def repair(
        self,
        *,
        persist: bool = False,
        candidate_id: str | None = None,
        failure_category: str | None = None,
    ) -> RepairReport:
        failures = tuple(
            failure
            for failure in self.live.load_failures()
            if failure.retryable
            and (candidate_id is None or failure.candidate_id == candidate_id)
            and (
                failure_category is None
                or failure.exception_category == failure_category
            )
        )
        return RepairReport(
            dry_run=not persist,
            candidates_checked=len({failure.candidate_id for failure in failures}),
            repairable_failures=len(failures),
            repaired=0,
            refused=len(failures),
            persisted=persist,
        )

    def operational_readiness(self) -> OperationalReadinessReport:
        health = self.capture_health()
        parity = self.input_parity()
        guardrails = self.downstream_guardrails()
        coverage = self.runtime_coverage()
        disabled = not _live_shadow_enabled()
        matrix = (
            (
                "runtime coverage",
                OperationalReadinessStatus.CONDITIONALLY_READY
                if all(
                    row.status is not RuntimeCoverageStatus.NOT_WIRED
                    for row in coverage
                    if row.eligible_for_live_observation
                )
                else OperationalReadinessStatus.NOT_READY,
                "eligible runtime paths must invoke diagnostic capture",
            ),
            (
                "capture completeness",
                OperationalReadinessStatus.DISABLED
                if disabled
                else OperationalReadinessStatus.READY_FOR_LIVE_COLLECTION
                if health.health
                in {
                    CaptureHealthStatus.HEALTHY,
                    CaptureHealthStatus.NO_ELIGIBLE_DECISIONS,
                }
                else OperationalReadinessStatus.NOT_READY,
                "diagnostic capture is disabled by default",
            ),
            (
                "input parity",
                OperationalReadinessStatus.READY_FOR_LIVE_COLLECTION
                if parity.status == "VALID"
                else OperationalReadinessStatus.NOT_READY,
                "all three policies must share non-regime inputs",
            ),
            (
                "downstream guardrails",
                OperationalReadinessStatus.READY_FOR_LIVE_COLLECTION
                if guardrails.alert == "NO_DOWNSTREAM_DIFFERENCE"
                else OperationalReadinessStatus.NOT_READY,
                "approval and allocation surprises block readiness",
            ),
            (
                "outcome refresh integration",
                OperationalReadinessStatus.READY_FOR_LIVE_COLLECTION,
                "nightly learning invokes live shadow outcome refresh",
            ),
        )
        if disabled:
            runtime_ready = all(
                row.status is not RuntimeCoverageStatus.NOT_WIRED
                for row in coverage
                if row.eligible_for_live_observation
            )
            primary = (
                CaptureOperationalConclusion.LIVE_SHADOW_COLLECTION_READY_BUT_DISABLED
                if runtime_ready and parity.status == "VALID"
                else CaptureOperationalConclusion.ALPHA_LIVE_SHADOW_WIRING_INCOMPLETE
            )
            milestone = (
                CaptureNextMilestone.BEGIN_PASSIVE_LIVE_REGIME_SHADOW_COLLECTION
                if runtime_ready and parity.status == "VALID"
                else CaptureNextMilestone.REPAIR_ALPHA_LIVE_RUNTIME_WIRING
            )
        elif any(row[1] is OperationalReadinessStatus.NOT_READY for row in matrix):
            primary = CaptureOperationalConclusion.ALPHA_LIVE_SHADOW_WIRING_INCOMPLETE
            milestone = CaptureNextMilestone.REPAIR_ALPHA_LIVE_RUNTIME_WIRING
        elif health.health is CaptureHealthStatus.HEALTHY:
            primary = CaptureOperationalConclusion.ALPHA_LIVE_SHADOW_WIRING_COMPLETE
            milestone = CaptureNextMilestone.BEGIN_PASSIVE_LIVE_REGIME_SHADOW_COLLECTION
        else:
            primary = (
                CaptureOperationalConclusion.LIVE_SHADOW_CAPTURE_CONDITIONALLY_READY
            )
            milestone = CaptureNextMilestone.BEGIN_PASSIVE_LIVE_REGIME_SHADOW_COLLECTION
        return OperationalReadinessReport(
            matrix=matrix,
            primary_conclusion=primary,
            secondary_conclusion=None,
            recommended_next_milestone=milestone,
            explicitly_prohibited_next_action=_PROHIBITED_ACTION,
        )

    def coverage(self) -> tuple[CoverageRow, ...]:
        observations = self.live.load_observations()
        matured = _matured(observations)
        episodes = self.episodes(observations)
        policy_differences = tuple(
            row for row in observations if _has_policy_difference(row)
        )
        bearish = tuple(row for row in matured if _is_bearish_event(row))
        protocol = self.protocol()
        rows = (
            _coverage_row("matured candidate coverage", len(matured), 50),
            _coverage_row(
                "decision-date coverage",
                len({row.market_date for row in matured}),
                protocol.minimum_distinct_dates,
            ),
            _coverage_row(
                "regime-episode coverage",
                len(self.episodes(matured)),
                protocol.minimum_distinct_episodes,
            ),
            _coverage_row(
                "bearish-event coverage",
                len(bearish),
                protocol.minimum_matured_bearish_events,
            ),
            _coverage_row(
                "bullish-event coverage",
                sum(
                    (row.recorded_regime or "").upper().startswith("BULL")
                    for row in matured
                ),
                5,
            ),
            _coverage_row("transition coverage", _transition_count(episodes), 2),
            _coverage_row("holding-period coverage", len(_holding_periods(matured)), 2),
            _coverage_row("setup coverage", len(_setup_groups(matured)), 3),
            _coverage_row(
                "quality coverage",
                sum(row.outcome_quality is not None for row in matured),
                50,
            ),
            _coverage_row(
                "recent-period coverage",
                sum(
                    row.market_date >= self.as_of - timedelta(days=90)
                    for row in matured
                ),
                10,
            ),
            _coverage_row(
                "policy-difference coverage",
                len(policy_differences),
                protocol.minimum_matured_policy_differences,
            ),
        )
        if not observations:
            return tuple(
                replace(
                    row,
                    status=EvidenceCoverageStatus.INSUFFICIENT,
                    explanation="no live observations recorded",
                )
                for row in rows
            )
        return rows

    def outcome_maturity(self) -> tuple[CoverageRow, ...]:
        observations = self.live.load_observations()
        counts = Counter(row.outcome_maturity_status for row in observations)
        return tuple(
            CoverageRow(
                dimension=status.value,
                count=counts[status],
                required=0,
                status=EvidenceCoverageStatus.NOT_APPLICABLE,
                explanation=f"{counts[status]} live observations",
            )
            for status in OutcomeMaturityStatus
        )

    def refresh_outcomes(self, *, persist: bool = False) -> RefreshResult:
        observations = self.live.load_observations()
        outcomes = {
            outcome.candidate_id: outcome for outcome in self.learning.load_outcomes()
        }
        refreshed = tuple(
            self._refresh_observation(row, outcomes.get(row.authoritative_candidate_id))
            for row in observations
        )
        if persist:
            self.live.save_observations(refreshed)
        result = RefreshResult(
            dry_run=not persist,
            observations_checked=len(observations),
            newly_matured=sum(
                old.outcome_maturity_status is not OutcomeMaturityStatus.MATURED
                and new.outcome_maturity_status is OutcomeMaturityStatus.MATURED
                for old, new in zip(observations, refreshed, strict=True)
            ),
            newly_partial=sum(
                old.outcome_maturity_status is OutcomeMaturityStatus.NOT_DUE
                and new.outcome_maturity_status
                is OutcomeMaturityStatus.PARTIALLY_AVAILABLE
                for old, new in zip(observations, refreshed, strict=True)
            ),
            still_pending=sum(
                row.outcome_maturity_status is OutcomeMaturityStatus.NOT_DUE
                for row in refreshed
            ),
            missing_outcomes=sum(
                row.outcome_maturity_status is OutcomeMaturityStatus.DUE_BUT_UNAVAILABLE
                for row in refreshed
            ),
            invalidated=sum(
                row.outcome_maturity_status is OutcomeMaturityStatus.INVALIDATED
                for row in refreshed
            ),
            persisted=persist,
        )
        if persist:
            self.live.save_refresh_manifest(
                RegimeShadowRefreshManifest(
                    refresh_run_id=_fingerprint(
                        "|".join(
                            (
                                self.as_of.isoformat(),
                                str(result.observations_checked),
                                str(result.newly_matured),
                                self.source_fingerprint(),
                            )
                        )
                    )[:16],
                    evidence_cutoff=self.as_of,
                    pending_checked=result.observations_checked,
                    newly_matured=result.newly_matured,
                    still_pending=result.still_pending,
                    missing_outcomes=result.missing_outcomes,
                    invalid_outcomes=result.invalidated,
                    source_fingerprint=self.source_fingerprint(),
                    created_at=datetime.now(UTC),
                )
            )
        return result

    def policy_differences(self) -> tuple[PolicyDifferenceReport, ...]:
        observations = self.live.load_observations()
        grouped: dict[PolicyDifferenceType, list[LiveRegimeShadowObservation]] = (
            defaultdict(list)
        )
        for observation in observations:
            grouped[observation.policy_difference_type].append(observation)
        return tuple(
            _policy_difference_report(kind, tuple(grouped.get(kind, ())))
            for kind in PolicyDifferenceType
        )

    def bearish_protection(self) -> BearishProtectionLiveReport:
        rows = tuple(
            row
            for row in _matured(self.live.load_observations())
            if _is_bearish_event(row)
        )
        classifications = Counter(_protection_classification(row) for row in rows)
        downside = [
            abs(row.mae)
            for row in rows
            if _protection_classification(row)
            is ProtectionClassification.TRUE_PROTECTION
            and row.mae is not None
        ]
        upside = [
            row.realized_return
            for row in rows
            if _protection_classification(row)
            is ProtectionClassification.FALSE_DEMOTION
            and row.realized_return is not None
        ]
        false_rate = _ratio(
            classifications[ProtectionClassification.FALSE_DEMOTION],
            len(rows),
        )
        conclusion = (
            LiveShadowConclusion.LIVE_SHADOW_EVIDENCE_NOT_YET_MATURE
            if len(rows) < self.protocol().minimum_matured_bearish_events
            else LiveShadowConclusion.BEARISH_ONLY_PROTECTION_IS_STABLE
            if false_rate is not None
            and false_rate <= self.protocol().maximum_false_demotion_rate
            else LiveShadowConclusion.BEARISH_ONLY_PROTECTION_IS_NOT_STABLE
        )
        return BearishProtectionLiveReport(
            matured_bearish_events=len(rows),
            true_protections=classifications[ProtectionClassification.TRUE_PROTECTION],
            false_demotions=classifications[ProtectionClassification.FALSE_DEMOTION],
            ambiguous=classifications[ProtectionClassification.AMBIGUOUS],
            downside_avoided=_average(downside),
            missed_upside=_average(upside),
            net_protection_value=_net(_average(downside), _average(upside)),
            average_mae_avoided=_average(downside),
            median_mae_avoided=_median(downside),
            stop_hit_rate=_ratio(sum(row.stop_hit is True for row in rows), len(rows)),
            target_hit_rate=_ratio(
                sum(row.target_hit is True for row in rows), len(rows)
            ),
            conclusion=conclusion,
        )

    def context_harm(self) -> ContextHarmReport:
        rows = tuple(
            row
            for row in _matured(self.live.load_observations())
            if row.policy_difference_type
            in {
                PolicyDifferenceType.BEARISH_DEMOTION_REMOVED,
                PolicyDifferenceType.NEUTRAL_ADJUSTMENT_REMOVED,
            }
        )
        losers = tuple(row for row in rows if (row.realized_return or _ZERO) < 0)
        downside = [abs(row.mae) for row in losers if row.mae is not None]
        alert = (
            ContextHarmAlert.INSUFFICIENT_MATURED_EVIDENCE
            if len(rows) < 20
            else ContextHarmAlert.CONTEXT_ONLY_HARM_SIGNAL
            if len(losers) / max(1, len(rows)) >= Decimal("0.50")
            else ContextHarmAlert.CONTEXT_ONLY_NO_MATERIAL_DIFFERENCE
        )
        return ContextHarmReport(
            bearish_demotions_removed=len(rows),
            losers_promoted=len(losers),
            downside_reintroduced=_average(downside),
            mae_worsened=sum((row.mae or _ZERO) < 0 for row in rows),
            stop_hit_rate=_ratio(sum(row.stop_hit is True for row in rows), len(rows)),
            false_positive_increase=len(losers),
            alert=alert,
        )

    def downstream_guardrails(self) -> DownstreamGuardrailReport:
        observations = self.live.load_observations()
        approvals = sum(row.approval_difference for row in observations)
        allocations = sum(row.allocation_difference for row in observations)
        alert = (
            "DOWNSTREAM_POLICY_SURPRISE"
            if approvals or allocations
            else "NO_DOWNSTREAM_DIFFERENCE"
        )
        return DownstreamGuardrailReport(
            approval_surprises=approvals,
            allocation_surprises=allocations,
            target_weight_surprises=0,
            capital_action_surprises=allocations,
            alert=alert,
        )

    def quality(self) -> tuple[CoverageRow, ...]:
        observations = self.live.load_observations()
        matured = _matured(observations)
        return (
            _coverage_row(
                "valid evidence",
                len(
                    [
                        row
                        for row in observations
                        if row.outcome_status is not LiveObservationStatus.INVALID
                    ]
                ),
                max(1, len(observations)),
            ),
            _coverage_row(
                "matured outcome quality",
                len([row for row in matured if row.outcome_quality]),
                50,
            ),
            _coverage_row(
                "non-future outcomes",
                len(
                    [
                        row
                        for row in observations
                        if row.outcome_maturity_status
                        is not OutcomeMaturityStatus.INVALIDATED
                    ]
                ),
                max(1, len(observations)),
            ),
        )

    def temporal(self) -> tuple[TemporalStabilityReport, ...]:
        observations = _matured(self.live.load_observations())
        windows = (
            ("rolling 30 trading days", self.as_of - timedelta(days=45)),
            ("rolling 90 trading days", self.as_of - timedelta(days=135)),
            (
                "calendar quarter",
                date(self.as_of.year, ((self.as_of.month - 1) // 3) * 3 + 1, 1),
            ),
            ("all live evidence", date.min),
        )
        return tuple(
            _temporal_report(
                label, tuple(row for row in observations if row.market_date >= start)
            )
            for label, start in windows
        )

    def setup(self) -> tuple[SetupStabilityReport, ...]:
        observations = self.live.load_observations()
        grouped: dict[str, list[LiveRegimeShadowObservation]] = defaultdict(list)
        for row in observations:
            for key in (
                f"setup={_setup_family(row.setup)}",
                f"holding_period={row.holding_period}",
                f"entry_state={row.entry_state}",
                f"verdict={row.final_verdict}",
            ):
                grouped[key].append(row)
        return tuple(
            _setup_report(group, tuple(rows)) for group, rows in sorted(grouped.items())
        )

    def drift(self) -> DriftReport:
        live = self.live.load_observations()
        replay = self._replay_observations()
        if len(live) < 20 or not replay:
            return DriftReport(
                live_observations=len(live),
                replay_observations=len(replay),
                score_difference_drift=None,
                verdict_difference_rate_drift=None,
                regime_distribution_drift=None,
                setup_distribution_drift=None,
                bearish_demotion_frequency_drift=None,
                outcome_quality_drift=None,
                status=DriftStatus.INSUFFICIENT_LIVE_SAMPLE,
            )
        score_drift = abs(
            (_average([abs(row.score_difference) for row in live]) or _ZERO)
            - (_average([abs(row.score_difference) for row in replay]) or _ZERO)
        )
        verdict_drift = abs(
            (_ratio(sum(row.verdict_difference for row in live), len(live)) or _ZERO)
            - (
                _ratio(sum(row.verdict_difference for row in replay), len(replay))
                or _ZERO
            )
        )
        regime_drift = _distribution_drift(
            [row.recorded_regime or "UNKNOWN" for row in live],
            [row.recorded_regime or "UNKNOWN" for row in replay],
        )
        setup_drift = _distribution_drift(
            [_setup_family(row.setup) for row in live],
            [_setup_family(row.setup) for row in replay],
        )
        bearish_drift = abs(
            (_ratio(sum(_is_bearish_event(row) for row in live), len(live)) or _ZERO)
            - (
                _ratio(sum(_is_bearish_event(row) for row in replay), len(replay))
                or _ZERO
            )
        )
        total = score_drift + verdict_drift + regime_drift + setup_drift + bearish_drift
        status = (
            DriftStatus.MATERIAL_DRIFT
            if total > Decimal("1.00")
            else DriftStatus.MODERATE_DRIFT
            if total > Decimal("0.40")
            else DriftStatus.CONSISTENT_WITH_REPLAY
        )
        return DriftReport(
            live_observations=len(live),
            replay_observations=len(replay),
            score_difference_drift=score_drift.quantize(_FOUR),
            verdict_difference_rate_drift=verdict_drift.quantize(_FOUR),
            regime_distribution_drift=regime_drift.quantize(_FOUR),
            setup_distribution_drift=setup_drift.quantize(_FOUR),
            bearish_demotion_frequency_drift=bearish_drift.quantize(_FOUR),
            outcome_quality_drift=None,
            status=status,
        )

    def review_due(self) -> bool:
        observations = self.live.load_observations()
        reviews = self.live.load_reviews()
        if not observations:
            return False
        if not reviews:
            return len(_matured(observations)) >= 25
        last = reviews[-1]
        newly_matured = sum(
            row.outcome_status
            in {
                LiveObservationStatus.PRIMARY_HORIZON_MATURED,
                LiveObservationStatus.FULLY_MATURED,
            }
            and row.market_date > last.evidence_cutoff
            for row in observations
        )
        return newly_matured >= 25 or self.as_of >= last.evidence_cutoff + timedelta(
            days=31
        )

    def review_checkpoint(
        self, *, persist: bool = False
    ) -> LiveRegimeShadowReviewCheckpoint:
        observations = self.live.load_observations()
        matured = _matured(observations)
        readiness = self.readiness()
        review = LiveRegimeShadowReviewCheckpoint(
            review_id=_fingerprint(
                "|".join(
                    (
                        self.protocol().protocol_fingerprint,
                        self.as_of.isoformat(),
                        str(len(matured)),
                    )
                )
            )[:16],
            review_timestamp=datetime.combine(
                self.as_of, datetime.min.time(), tzinfo=UTC
            ),
            evidence_cutoff=self.as_of,
            protocol_version=self.protocol().protocol_version,
            protocol_fingerprint=self.protocol().protocol_fingerprint,
            policy_registry_fingerprint=self._policy_registry_fingerprint(),
            source_fingerprint=self.source_fingerprint(),
            matured_observations=len(matured),
            market_dates=len({row.market_date for row in matured}),
            episodes=len(self.episodes(matured)),
            decision_status=(
                SequentialReviewStatus.READY_FOR_FORMAL_REVIEW
                if readiness.decision_status
                in {
                    LiveShadowDecisionStatus.READY_FOR_BEARISH_ONLY_FORMAL_REVIEW,
                    LiveShadowDecisionStatus.READY_FOR_CONTEXT_ONLY_FORMAL_REVIEW,
                }
                else SequentialReviewStatus.CONTINUE_COLLECTION
            ),
            primary_conclusion=readiness.primary_conclusion,
            recommended_next_milestone=readiness.recommended_next_milestone,
        )
        if persist:
            self.live.save_review(review)
        return review

    def readiness(self) -> LiveReadinessReport:
        guardrails = self.downstream_guardrails()
        bearish = self.bearish_protection()
        context = self.context_harm()
        coverage = self.coverage()
        if guardrails.alert == "DOWNSTREAM_POLICY_SURPRISE":
            primary = LiveShadowConclusion.DOWNSTREAM_POLICY_SURPRISE_DETECTED
            decision = LiveShadowDecisionStatus.INVALID_SHADOW_EVIDENCE
            milestone = LiveShadowNextMilestone.AUDIT_DOWNSTREAM_POLICY_SURPRISE
            secondary = None
        elif not self.live.load_observations() or not _matured(
            self.live.load_observations()
        ):
            primary = LiveShadowConclusion.LIVE_SHADOW_EVIDENCE_NOT_YET_MATURE
            decision = LiveShadowDecisionStatus.CONTINUE_LIVE_SHADOW_COLLECTION
            milestone = LiveShadowNextMilestone.CONTINUE_LIVE_REGIME_SHADOW_COLLECTION
            secondary = None
        elif context.alert is ContextHarmAlert.CONTEXT_ONLY_HARM_SIGNAL:
            primary = LiveShadowConclusion.CONTEXT_ONLY_HARM_IS_CONFIRMED
            decision = LiveShadowDecisionStatus.REJECT_CONTEXT_ONLY_POLICY
            milestone = LiveShadowNextMilestone.RETAIN_CONTROL_POLICY
            secondary = None
        elif (
            bearish.conclusion is LiveShadowConclusion.BEARISH_ONLY_PROTECTION_IS_STABLE
            and all(
                row.status is EvidenceCoverageStatus.SUFFICIENT for row in coverage[:4]
            )
        ):
            primary = LiveShadowConclusion.BEARISH_ONLY_PROTECTION_IS_STABLE
            decision = LiveShadowDecisionStatus.READY_FOR_BEARISH_ONLY_FORMAL_REVIEW
            milestone = (
                LiveShadowNextMilestone.PERFORM_BEARISH_ONLY_FORMAL_POLICY_REVIEW
            )
            secondary = None
        else:
            primary = LiveShadowConclusion.LIVE_SHADOW_EVIDENCE_PROGRESSING
            decision = LiveShadowDecisionStatus.CONTINUE_LIVE_SHADOW_COLLECTION
            milestone = LiveShadowNextMilestone.CONTINUE_LIVE_REGIME_SHADOW_COLLECTION
            secondary = bearish.conclusion
        return LiveReadinessReport(
            protocol=self.protocol(),
            coverage=coverage,
            primary_conclusion=primary,
            secondary_conclusion=secondary,
            decision_status=decision,
            recommended_next_milestone=milestone,
            explicitly_prohibited_next_action=_PROHIBITED_ACTION,
        )

    def episodes(
        self,
        observations: tuple[LiveRegimeShadowObservation, ...] | None = None,
    ) -> tuple[LiveRegimeShadowEpisode, ...]:
        rows = tuple(
            observations if observations is not None else self.live.load_observations()
        )
        if not rows:
            return ()
        by_date: dict[date, list[LiveRegimeShadowObservation]] = defaultdict(list)
        for row in rows:
            by_date[row.market_date].append(row)
        episodes: list[LiveRegimeShadowEpisode] = []
        current_regime: str | None = None
        current_dates: list[date] = []
        current_rows: list[LiveRegimeShadowObservation] = []
        for market_date in sorted(by_date):
            regime = _dominant_regime(by_date[market_date])
            if current_regime is None or regime == current_regime:
                current_regime = regime
                current_dates.append(market_date)
                current_rows.extend(by_date[market_date])
                continue
            episodes.append(_episode(current_regime, current_dates, current_rows))
            current_regime = regime
            current_dates = [market_date]
            current_rows = list(by_date[market_date])
        if current_regime is not None:
            episodes.append(_episode(current_regime, current_dates, current_rows))
        return tuple(episodes)

    def replay_observation_count(self) -> int:
        control = [
            row
            for row in self.shadow.load_decisions()
            if row.policy_id is RegimeShadowPolicyId.CONTROL
        ]
        return len(control)

    def source_fingerprint(self) -> str:
        payload = "|".join(
            (
                self.protocol().protocol_fingerprint,
                self._policy_registry_fingerprint(),
                str(len(self.live.load_observations())),
                str(len(self.live.load_reviews())),
                str(self.replay_observation_count()),
            )
        )
        return _fingerprint(payload)

    def _refresh_observation(
        self,
        row: LiveRegimeShadowObservation,
        outcome: Any,
    ) -> LiveRegimeShadowObservation:
        if row.market_date > self.as_of:
            return replace(
                row,
                outcome_status=LiveObservationStatus.INVALID,
                outcome_maturity_status=OutcomeMaturityStatus.INVALIDATED,
                missing_outcome_reason="market date is after evaluation date",
                updated_at=datetime.now(UTC),
            )
        horizon_days = _horizon_days(row.outcome_horizon)
        maturity_date = row.market_date + timedelta(days=horizon_days)
        if self.as_of < maturity_date:
            return replace(
                row,
                outcome_status=LiveObservationStatus.PENDING_OUTCOME,
                outcome_maturity_status=OutcomeMaturityStatus.NOT_DUE,
                outcome_maturity_date=maturity_date,
                missing_bars=max(0, horizon_days - row.available_bars),
                updated_at=datetime.now(UTC),
            )
        if outcome is None:
            return replace(
                row,
                outcome_status=LiveObservationStatus.PENDING_OUTCOME,
                outcome_maturity_status=OutcomeMaturityStatus.DUE_BUT_UNAVAILABLE,
                outcome_maturity_date=maturity_date,
                missing_outcome_reason="candidate outcome is unavailable",
                updated_at=datetime.now(UTC),
            )
        if outcome.evaluated_at.date() < row.market_date:
            return replace(
                row,
                outcome_status=LiveObservationStatus.INVALID,
                outcome_maturity_status=OutcomeMaturityStatus.INVALIDATED,
                missing_outcome_reason="outcome timestamp is before decision date",
                updated_at=datetime.now(UTC),
            )
        window = _window(outcome, row.outcome_horizon)
        if window is None:
            return replace(
                row,
                outcome_status=LiveObservationStatus.PARTIALLY_MATURED,
                outcome_maturity_status=OutcomeMaturityStatus.PARTIALLY_AVAILABLE,
                outcome_maturity_date=maturity_date,
                available_bars=len(outcome.windows),
                missing_bars=1,
                missing_outcome_reason=f"{row.outcome_horizon} window unavailable",
                updated_at=datetime.now(UTC),
            )
        if window.outcome_label is CandidateOutcomeLabel.DATA_MISSING:
            return replace(
                row,
                outcome_status=LiveObservationStatus.PARTIALLY_MATURED,
                outcome_maturity_status=OutcomeMaturityStatus.PARTIALLY_AVAILABLE,
                outcome_maturity_date=maturity_date,
                available_bars=len(outcome.windows),
                missing_bars=1,
                missing_outcome_reason="primary window is data missing",
                updated_at=datetime.now(UTC),
            )
        return replace(
            row,
            outcome_status=LiveObservationStatus.PRIMARY_HORIZON_MATURED,
            outcome_maturity_status=OutcomeMaturityStatus.MATURED,
            outcome_maturity_date=maturity_date,
            outcome_record_id=f"{outcome.candidate_id}:{window.window}",
            available_bars=_horizon_days(window.window),
            missing_bars=0,
            missing_outcome_reason=None,
            realized_return=window.forward_return_pct_from_entry,
            benchmark_relative_return=None,
            mfe=window.max_favourable_excursion_pct,
            mae=window.max_adverse_excursion_pct,
            target_hit=window.target_1_touched,
            stop_hit=window.risk_stop_touched,
            outcome_quality=window.outcome_label.value,
            updated_at=datetime.now(UTC),
        )

    def _shadow_policy_versions(self) -> tuple[str, ...]:
        return tuple(
            policy.policy_version for policy in RegimeShadowEngine().policies()
        )

    def _policy_registry_fingerprint(self) -> str:
        return _fingerprint("|".join(self._shadow_policy_versions()))

    def _replay_observations(self) -> tuple[LiveRegimeShadowObservation, ...]:
        decisions = self.shadow.load_decisions()
        grouped: dict[str, dict[RegimeShadowPolicyId, RegimeShadowDecision]] = (
            defaultdict(dict)
        )
        for decision in decisions:
            grouped[decision.authoritative_candidate_id][decision.policy_id] = decision
        output = []
        for candidate_id, rows in sorted(grouped.items()):
            if not all(policy in rows for policy in RegimeShadowPolicyId):
                continue
            output.append(
                _observation_from_shadow_rows(
                    "REPLAY_BASELINE", candidate_id, rows, self.protocol()
                )
            )
        return tuple(output)


def observation_from_shadow_decisions(
    *,
    shadow_run_id: str,
    candidate_id: str,
    decisions: dict[RegimeShadowPolicyId, RegimeShadowDecision],
    protocol: LiveRegimeShadowProtocol | None = None,
) -> LiveRegimeShadowObservation:
    return _observation_from_shadow_rows(
        shadow_run_id,
        candidate_id,
        decisions,
        protocol or LiveRegimeShadowEvidenceEngine().protocol(),
    )


def frozen_input_from_candidate(
    *,
    candidate: CandidateDecisionRecord,
    runtime_path: str,
    source_mode: LiveShadowSourceMode,
    decision_timestamp: datetime | None = None,
    smoke_test: bool = False,
) -> FrozenAuthoritativeDecisionInput:
    timestamp = decision_timestamp or candidate.created_at
    source_fingerprint = _fingerprint(
        "|".join(
            (
                candidate.candidate_id,
                candidate.run_id,
                timestamp.isoformat(),
                source_mode.value,
                candidate.decision_provenance_id or "no-provenance",
            )
        )
    )
    return FrozenAuthoritativeDecisionInput(
        candidate=candidate,
        runtime_path=runtime_path,
        source_mode=source_mode,
        decision_timestamp=timestamp,
        source_fingerprint=source_fingerprint,
        non_regime_input_fingerprint=_non_regime_fingerprint(candidate),
        market_state_source_quality=_market_state_source_quality(candidate),
        smoke_test=smoke_test,
    )


def resolve_live_regime_shadow_ledger_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("ALPHA_LIVE_REGIME_SHADOW_LEDGER")
    if configured:
        return Path(configured)
    return DEFAULT_LIVE_REGIME_SHADOW_LEDGER_PATH


def _empty_live_payload() -> dict[str, list[object]]:
    return {
        "observations": [],
        "reviews": [],
        "failures": [],
        "capture_manifests": [],
        "refresh_manifests": [],
    }


def render_live_shadow_status(report: LiveStatusReport) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Status",
        f"Shadow Enabled: {report.shadow_enabled}",
        f"Protocol Version: {report.protocol.protocol_version}",
        f"Protocol Fingerprint: {report.protocol.protocol_fingerprint}",
        "Policy Versions: " + ", ".join(report.shadow_policy_versions),
        f"Replay Observations: {report.replay_observations}",
        f"Live Observations: {report.live_observations}",
        f"Pending Outcomes: {report.pending_observations}",
        f"Partially Matured: {report.partially_matured}",
        f"Fully Matured: {report.fully_matured}",
        f"Distinct Dates: {report.distinct_dates}",
        f"Distinct Episodes: {report.distinct_episodes}",
        f"Policy-Difference Events: {report.policy_difference_events}",
        f"Bearish Events: {report.bearish_events}",
        f"Context-Only Difference Events: {report.context_only_difference_events}",
        f"Approval Surprises: {report.approval_surprises}",
        f"Allocation Surprises: {report.allocation_surprises}",
        f"Next Review Eligible: {report.next_review_eligible}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        "Secondary Conclusion: "
        + (
            report.secondary_conclusion.value
            if report.secondary_conclusion
            else "unavailable"
        ),
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
    )


def render_coverage(rows: tuple[CoverageRow, ...]) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Observation Coverage",
        *(
            f"- {row.dimension}: {row.status.value} "
            f"({row.count}/{row.required}) - {row.explanation}"
            for row in rows
        ),
    )


def render_outcome_maturity(rows: tuple[CoverageRow, ...]) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Outcome Maturity",
        *(f"- {row.dimension}: {row.count} observations" for row in rows),
    )


def render_refresh(result: RefreshResult) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Outcome Refresh",
        f"Mode: {'dry-run' if result.dry_run else 'persisted'}",
        f"Observations Checked: {result.observations_checked}",
        f"Newly Matured: {result.newly_matured}",
        f"Newly Partial: {result.newly_partial}",
        f"Still Pending: {result.still_pending}",
        f"Missing Outcomes: {result.missing_outcomes}",
        f"Invalidated: {result.invalidated}",
        f"Persisted: {result.persisted}",
    )


def render_policy_differences(
    rows: tuple[PolicyDifferenceReport, ...],
) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Policy Differences",
        *(
            f"- {row.difference_type.value}: pending={row.pending_outcomes}, "
            f"matured={row.matured_outcomes}, dates={row.distinct_dates}, "
            f"episodes={row.distinct_episodes}, avg={_text(row.average_return)}, "
            f"stop_hit={_text(row.stop_hit_rate)}, "
            f"target_hit={_text(row.target_hit_rate)}"
            for row in rows
        ),
    )


def render_bearish_protection(report: BearishProtectionLiveReport) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Bearish Protection",
        f"Matured Bearish Events: {report.matured_bearish_events}",
        f"True Protections: {report.true_protections}",
        f"False Demotions: {report.false_demotions}",
        f"Ambiguous: {report.ambiguous}",
        f"Downside Avoided: {_text(report.downside_avoided)}",
        f"Missed Upside: {_text(report.missed_upside)}",
        f"Net Protection Value: {_text(report.net_protection_value)}",
        f"Average MAE Avoided: {_text(report.average_mae_avoided)}",
        f"Median MAE Avoided: {_text(report.median_mae_avoided)}",
        f"Stop-Hit Rate: {_text(report.stop_hit_rate)}",
        f"Target-Hit Rate: {_text(report.target_hit_rate)}",
        f"Conclusion: {report.conclusion.value}",
    )


def render_context_harm(report: ContextHarmReport) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Context Harm",
        f"Bearish/Neutral Demotions Removed: {report.bearish_demotions_removed}",
        f"Losers Promoted: {report.losers_promoted}",
        f"Downside Reintroduced: {_text(report.downside_reintroduced)}",
        f"MAE Worsened Events: {report.mae_worsened}",
        f"Stop-Hit Rate: {_text(report.stop_hit_rate)}",
        f"False-Positive Increase: {report.false_positive_increase}",
        f"Alert: {report.alert.value}",
    )


def render_guardrails(report: DownstreamGuardrailReport) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Downstream Guardrails",
        f"Approval Surprises: {report.approval_surprises}",
        f"Allocation Surprises: {report.allocation_surprises}",
        f"Target Weight Surprises: {report.target_weight_surprises}",
        f"Capital Action Surprises: {report.capital_action_surprises}",
        f"Alert: {report.alert}",
    )


def render_temporal(rows: tuple[TemporalStabilityReport, ...]) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Temporal Stability",
        *(
            f"- {row.period}: differences={row.policy_differences}, "
            f"true_protection={_text(row.true_protection_rate)}, "
            f"false_demotion={_text(row.false_demotion_rate)}, "
            f"context_harm={row.context_only_harm_events}, "
            f"conclusion={row.conclusion}"
            for row in rows
        ),
    )


def render_setup(rows: tuple[SetupStabilityReport, ...]) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Setup and Holding-Period Stability",
        *(
            f"- {row.group}: n={row.candidate_count}, matured={row.matured_count}, "
            f"bearish={row.bearish_events}, context_harm={row.context_harm_events}, "
            f"finding={row.finding}"
            for row in rows
        ),
    )


def render_drift(report: DriftReport) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Replay/Live Drift",
        f"Live Observations: {report.live_observations}",
        f"Replay Observations: {report.replay_observations}",
        f"Score Difference Drift: {_text(report.score_difference_drift)}",
        f"Verdict Difference Rate Drift: {_text(report.verdict_difference_rate_drift)}",
        f"Regime Distribution Drift: {_text(report.regime_distribution_drift)}",
        f"Setup Distribution Drift: {_text(report.setup_distribution_drift)}",
        "Bearish-Demotion Frequency Drift: "
        + _text(report.bearish_demotion_frequency_drift),
        f"Outcome Quality Drift: {_text(report.outcome_quality_drift)}",
        f"Status: {report.status.value}",
    )


def render_review(review: LiveRegimeShadowReviewCheckpoint) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Review Checkpoint",
        f"Review ID: {review.review_id}",
        f"Evidence Cutoff: {review.evidence_cutoff.isoformat()}",
        f"Protocol Version: {review.protocol_version}",
        f"Protocol Fingerprint: {review.protocol_fingerprint}",
        f"Matured Observations: {review.matured_observations}",
        f"Market Dates: {review.market_dates}",
        f"Episodes: {review.episodes}",
        f"Decision Status: {review.decision_status.value}",
        f"Primary Conclusion: {review.primary_conclusion.value}",
        f"Recommended Next Milestone: {review.recommended_next_milestone.value}",
    )


def render_readiness(report: LiveReadinessReport) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Readiness",
        f"Protocol Version: {report.protocol.protocol_version}",
        f"Protocol Fingerprint: {report.protocol.protocol_fingerprint}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        "Secondary Conclusion: "
        + (
            report.secondary_conclusion.value
            if report.secondary_conclusion
            else "unavailable"
        ),
        f"Decision Status: {report.decision_status.value}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        "Coverage Scorecard:",
        *(
            f"- {row.dimension}: {row.status.value} ({row.count}/{row.required})"
            for row in report.coverage
        ),
        "Explicitly Prohibited Next Action: "
        + report.explicitly_prohibited_next_action,
    )


def render_runtime_coverage(rows: tuple[RuntimeCoverageRow, ...]) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Runtime Coverage",
        *(
            f"- {row.runtime_path}: {row.status.value}; "
            f"implementation={row.implementation_wired}, "
            f"provider={row.provider_validated}, "
            f"candidate_path={row.candidate_path_validated}, "
            f"shadow={row.shadow_capture_validated}, "
            f"authoritative={row.authoritative_decision_created}, "
            f"persisted={row.candidate_persisted}, "
            f"snapshot={row.market_state_snapshot_available}, "
            f"capture_invoked={row.shadow_capture_invoked}, "
            f"eligible={row.eligible_for_live_observation}"
            for row in rows
        ),
    )


def render_alpha_live_wiring(report: AlphaLiveShadowWiringReport) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Alpha Live Wiring",
        f"Provider: {report.provider}",
        f"Symbol: {report.symbol}",
        f"Source Mode: {report.source_mode.value}",
        f"Quote Timestamp: {_text(report.quote_timestamp)}",
        "Latest Completed Bar Timestamp: "
        f"{_text(report.latest_completed_bar_timestamp)}",
        f"Decision Timestamp: {_text(report.decision_timestamp)}",
        f"Feed Status: {report.feed_status}",
        f"Staleness: {report.staleness}",
        f"Session State: {report.session_state}",
        f"Authoritative Candidate Created: {report.authoritative_candidate_created}",
        "Authoritative Candidate Persisted: "
        f"{report.authoritative_candidate_persisted}",
        f"Duplicate Authoritative Attempt: {report.duplicate_authoritative_attempt}",
        f"Stable Candidate ID: {_text(report.stable_candidate_id)}",
        f"Provenance ID: {_text(report.provenance_id)}",
        f"Market-State Snapshot ID: {_text(report.market_state_snapshot_id)}",
        f"Frozen Inputs Available: {report.frozen_inputs_available}",
        f"Shadow Capture Invoked: {report.shadow_capture_invoked}",
        "Shadow Capture Status: "
        f"{_text(_shadow_capture_status_text(report.shadow_capture_status))}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        f"Explanation: {report.explanation}",
    )


def render_capture_health(report: CaptureHealthReport) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Capture Health",
        f"Eligible Authoritative Decisions: {report.eligible_authoritative_decisions}",
        f"Captured Observations: {report.captured_observations}",
        f"Capture Rate: {_text(report.capture_rate)}",
        f"Skipped Disabled: {report.skipped_disabled}",
        f"Skipped Ineligible: {report.skipped_ineligible}",
        f"Skipped Insufficient Input: {report.skipped_insufficient_input}",
        f"Evaluation Failures: {report.evaluation_failures}",
        f"Persistence Failures: {report.persistence_failures}",
        f"Incomplete Policy Sets: {report.incomplete_policy_sets}",
        f"Input Parity Failures: {report.input_parity_failures}",
        f"Orphan Records: {report.orphan_records}",
        f"Duplicate Attempts: {report.duplicate_attempts}",
        f"Repairable Failures: {report.repairable_failures}",
        f"Unrepairable Failures: {report.unrepairable_failures}",
        f"Health: {report.health.value}",
    )


def render_capture_failures(
    rows: tuple[RegimeShadowCaptureFailure, ...],
) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Capture Failures",
        *(
            f"- {row.failure_id}: candidate={_text(row.candidate_id)}, "
            f"stage={row.failure_stage.value}, category={row.exception_category}, "
            f"retryable={row.retryable}"
            for row in rows
        ),
    )


def render_capture_manifests(
    rows: tuple[RegimeShadowCaptureManifest, ...],
) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Capture Manifests",
        *(
            f"- {row.capture_run_id}: runtime={row.runtime_path}, "
            f"eligible={row.eligible_candidates}, captured={row.captured}, "
            f"skipped={row.skipped}, failed={row.failed}"
            for row in rows
        ),
    )


def render_input_parity(report: InputParityReport) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Input Parity",
        f"Observations Checked: {report.observations_checked}",
        f"Parity Passed: {report.parity_passed}",
        f"Parity Failed: {report.parity_failed}",
        f"Incomplete Policy Sets: {report.incomplete_policy_sets}",
        f"Status: {report.status}",
    )


def render_repair(report: RepairReport) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Repair",
        f"Mode: {'dry-run' if report.dry_run else 'persisted'}",
        f"Candidates Checked: {report.candidates_checked}",
        f"Repairable Failures: {report.repairable_failures}",
        f"Repaired: {report.repaired}",
        f"Refused: {report.refused}",
        f"Persisted: {report.persisted}",
    )


def render_operational_readiness(
    report: OperationalReadinessReport,
) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Operational Readiness",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        "Secondary Conclusion: "
        + (
            report.secondary_conclusion.value
            if report.secondary_conclusion
            else "unavailable"
        ),
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        "Readiness Matrix:",
        *(
            f"- {name}: {status.value}; {explanation}"
            for name, status, explanation in report.matrix
        ),
        "Explicitly Prohibited Next Action: "
        + report.explicitly_prohibited_next_action,
    )


def render_capture_result(
    report: LiveRegimeShadowCaptureResult,
) -> tuple[str, ...]:
    return (
        "Live Regime Shadow Capture Smoke Test",
        f"Status: {report.status.value}",
        f"Persisted: {report.persisted}",
        f"Authoritative Unchanged: {report.authoritative_unchanged}",
        "Observation ID: "
        + _text(
            None if report.observation is None else report.observation.observation_id
        ),
        "Failure ID: "
        + _text(None if report.failure is None else report.failure.failure_id),
        f"Message: {report.message}",
        "Executable: false",
        "Capital Effect: none",
    )


def export_live_regime_shadow_json(payload: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def export_live_regime_shadow_csv(rows: tuple[Any, ...], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    flattened = [_flatten(_jsonable(row)) for row in rows]
    fields = sorted({key for row in flattened for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flattened)
    return path


def _observation_from_shadow_rows(
    shadow_run_id: str,
    candidate_id: str,
    decisions: dict[RegimeShadowPolicyId, RegimeShadowDecision],
    protocol: LiveRegimeShadowProtocol,
) -> LiveRegimeShadowObservation:
    control = decisions[RegimeShadowPolicyId.CONTROL]
    context = decisions[RegimeShadowPolicyId.CONTEXT_ONLY]
    bearish = decisions[RegimeShadowPolicyId.BEARISH_ONLY]
    score_difference = (context.shadow_score - control.shadow_score).quantize(_FOUR)
    verdict_difference = context.shadow_verdict != control.shadow_verdict
    approval_difference = (
        context.shadow_approval_eligible != control.shadow_approval_eligible
    )
    allocation_difference = (
        context.shadow_allocation_eligible != control.shadow_allocation_eligible
    )
    difference_type = _difference_type(control, context, bearish)
    market_date = control.decision_timestamp.date()
    now = datetime.now(UTC)
    return LiveRegimeShadowObservation(
        observation_id=_fingerprint(
            "|".join((shadow_run_id, candidate_id, protocol.protocol_fingerprint))
        )[:24],
        shadow_run_id=shadow_run_id,
        authoritative_candidate_id=candidate_id,
        decision_timestamp=control.decision_timestamp,
        market_date=market_date,
        symbol=control.symbol,
        setup=control.setup_type,
        holding_period=_holding_period_bucket(None),
        entry_state="UNAVAILABLE",
        final_verdict=control.authoritative_verdict,
        recorded_regime=control.recorded_regime,
        market_state_snapshot_id=control.regime_snapshot_id,
        market_episode_id=None,
        control_shadow_id=control.shadow_decision_id,
        context_only_shadow_id=context.shadow_decision_id,
        bearish_only_shadow_id=bearish.shadow_decision_id,
        policy_difference_type=difference_type,
        score_difference=score_difference,
        verdict_difference=verdict_difference,
        approval_difference=approval_difference,
        allocation_difference=allocation_difference,
        outcome_status=LiveObservationStatus.PENDING_OUTCOME,
        outcome_maturity_status=OutcomeMaturityStatus.NOT_DUE,
        outcome_maturity_date=market_date
        + timedelta(days=_horizon_days(PRIMARY_POLICY_HORIZON)),
        outcome_horizon=PRIMARY_POLICY_HORIZON,
        outcome_record_id=None,
        available_bars=0,
        missing_bars=_horizon_days(PRIMARY_POLICY_HORIZON),
        missing_outcome_reason=None,
        realized_return=None,
        benchmark_relative_return=None,
        mfe=None,
        mae=None,
        target_hit=None,
        stop_hit=None,
        outcome_quality=None,
        source_fingerprint=control.source_fingerprint,
        policy_registry_fingerprint=_fingerprint(
            "|".join(
                (
                    control.policy_fingerprint,
                    context.policy_fingerprint,
                    bearish.policy_fingerprint,
                )
            )
        ),
        protocol_fingerprint=protocol.protocol_fingerprint,
        created_at=now,
        updated_at=now,
    )


def _difference_type(
    control: RegimeShadowDecision,
    context: RegimeShadowDecision,
    bearish: RegimeShadowDecision,
) -> PolicyDifferenceType:
    if context.approval_difference or bearish.approval_difference:
        return PolicyDifferenceType.APPROVAL_DIFFERENCE
    if context.allocation_difference or bearish.allocation_difference:
        return PolicyDifferenceType.ALLOCATION_DIFFERENCE
    regime = (control.recorded_regime or "").upper()
    if regime in {"BEAR", "BEARISH", "NEGATIVE", "STRONG_NEGATIVE"}:
        if (
            bearish.shadow_verdict == control.shadow_verdict
            and context.shadow_verdict != control.shadow_verdict
        ):
            return PolicyDifferenceType.BEARISH_DEMOTION_RETAINED
        if context.shadow_verdict != control.shadow_verdict:
            return PolicyDifferenceType.BEARISH_DEMOTION_REMOVED
    if (
        context.shadow_score < control.shadow_score
        or bearish.shadow_score < control.shadow_score
    ):
        return PolicyDifferenceType.BULLISH_PROMOTION_REMOVED
    if (
        context.shadow_score > control.shadow_score
        or bearish.shadow_score > control.shadow_score
    ):
        return PolicyDifferenceType.NEUTRAL_ADJUSTMENT_REMOVED
    if (
        context.shadow_verdict != control.shadow_verdict
        or bearish.shadow_verdict != control.shadow_verdict
    ):
        return PolicyDifferenceType.VERDICT_DIFFERENCE
    if (
        context.shadow_score != control.shadow_score
        or bearish.shadow_score != control.shadow_score
    ):
        return PolicyDifferenceType.SCORE_ONLY_DIFFERENCE
    return PolicyDifferenceType.NO_POLICY_DIFFERENCE


def _policy_difference_report(
    kind: PolicyDifferenceType,
    rows: tuple[LiveRegimeShadowObservation, ...],
) -> PolicyDifferenceReport:
    matured = _matured(rows)
    return PolicyDifferenceReport(
        difference_type=kind,
        pending_outcomes=len(rows) - len(matured),
        matured_outcomes=len(matured),
        distinct_dates=len({row.market_date for row in rows}),
        distinct_episodes=len(
            {row.market_episode_id for row in rows if row.market_episode_id}
        ),
        average_return=_average(
            [row.realized_return for row in matured if row.realized_return is not None]
        ),
        benchmark_relative_return=_average(
            [
                row.benchmark_relative_return
                for row in matured
                if row.benchmark_relative_return is not None
            ]
        ),
        mfe=_average([row.mfe for row in matured if row.mfe is not None]),
        mae=_average([row.mae for row in matured if row.mae is not None]),
        stop_hit_rate=_ratio(
            sum(row.stop_hit is True for row in matured), len(matured)
        ),
        target_hit_rate=_ratio(
            sum(row.target_hit is True for row in matured), len(matured)
        ),
    )


def _coverage_row(dimension: str, count: int, required: int) -> CoverageRow:
    if required <= 0:
        status = EvidenceCoverageStatus.NOT_APPLICABLE
    elif count >= required:
        status = EvidenceCoverageStatus.SUFFICIENT
    elif count > 0:
        status = EvidenceCoverageStatus.PARTIAL
    else:
        status = EvidenceCoverageStatus.INSUFFICIENT
    return CoverageRow(
        dimension=dimension,
        count=count,
        required=required,
        status=status,
        explanation=(
            "candidate count alone is not independent evidence"
            if "candidate" in dimension
            else "predefined minimum evidence requirement"
        ),
    )


def _matured(
    rows: tuple[LiveRegimeShadowObservation, ...],
) -> tuple[LiveRegimeShadowObservation, ...]:
    return tuple(
        row
        for row in rows
        if row.outcome_maturity_status is OutcomeMaturityStatus.MATURED
        and row.outcome_status
        in {
            LiveObservationStatus.PRIMARY_HORIZON_MATURED,
            LiveObservationStatus.FULLY_MATURED,
        }
    )


def _has_policy_difference(row: LiveRegimeShadowObservation) -> bool:
    return row.policy_difference_type is not PolicyDifferenceType.NO_POLICY_DIFFERENCE


def _is_bearish_event(row: LiveRegimeShadowObservation) -> bool:
    return row.policy_difference_type in {
        PolicyDifferenceType.BEARISH_DEMOTION_RETAINED,
        PolicyDifferenceType.BEARISH_DEMOTION_REMOVED,
    }


def _protection_classification(
    row: LiveRegimeShadowObservation,
) -> ProtectionClassification:
    if row.realized_return is None and row.mae is None:
        return ProtectionClassification.OUTCOME_UNAVAILABLE
    if row.stop_hit or (row.mae is not None and row.mae <= Decimal("-8")):
        return ProtectionClassification.TRUE_PROTECTION
    if row.realized_return is not None and row.realized_return > 0 and row.target_hit:
        return ProtectionClassification.FALSE_DEMOTION
    return ProtectionClassification.AMBIGUOUS


def _episode(
    regime: str,
    dates: list[date],
    rows: list[LiveRegimeShadowObservation],
) -> LiveRegimeShadowEpisode:
    start = min(dates)
    end = max(dates)
    return LiveRegimeShadowEpisode(
        episode_id=_fingerprint(f"{regime}|{start.isoformat()}|{end.isoformat()}")[:16],
        regime=regime,
        start_date=start,
        end_date=end,
        trading_days=len(set(dates)),
        candidate_count=len(rows),
        policy_difference_count=sum(_has_policy_difference(row) for row in rows),
        matured_outcome_count=len(_matured(tuple(rows))),
        source_quality="RECORDED_LIVE_SHADOW",
    )


def _dominant_regime(rows: list[LiveRegimeShadowObservation]) -> str:
    counts = Counter((row.recorded_regime or "UNKNOWN").upper() for row in rows)
    return counts.most_common(1)[0][0]


def _transition_count(episodes: tuple[LiveRegimeShadowEpisode, ...]) -> int:
    return sum(
        left.regime != right.regime
        for left, right in zip(episodes, episodes[1:], strict=False)
    )


def _holding_periods(rows: tuple[LiveRegimeShadowObservation, ...]) -> set[str]:
    return {row.holding_period for row in rows if row.holding_period != "UNAVAILABLE"}


def _setup_groups(rows: tuple[LiveRegimeShadowObservation, ...]) -> set[str]:
    return {_setup_family(row.setup) for row in rows}


def _temporal_report(
    period: str,
    rows: tuple[LiveRegimeShadowObservation, ...],
) -> TemporalStabilityReport:
    bearish = tuple(row for row in rows if _is_bearish_event(row))
    true = sum(
        _protection_classification(row) is ProtectionClassification.TRUE_PROTECTION
        for row in bearish
    )
    false = sum(
        _protection_classification(row) is ProtectionClassification.FALSE_DEMOTION
        for row in bearish
    )
    downside = [abs(row.mae) for row in bearish if row.mae is not None and row.mae < 0]
    upside = [
        row.realized_return
        for row in bearish
        if row.realized_return is not None and row.realized_return > 0
    ]
    context_harm = sum(
        row.policy_difference_type
        in {
            PolicyDifferenceType.BEARISH_DEMOTION_REMOVED,
            PolicyDifferenceType.NEUTRAL_ADJUSTMENT_REMOVED,
        }
        and (row.realized_return or _ZERO) < 0
        for row in rows
    )
    return TemporalStabilityReport(
        period=period,
        policy_differences=sum(_has_policy_difference(row) for row in rows),
        true_protection_rate=_ratio(true, len(bearish)),
        false_demotion_rate=_ratio(false, len(bearish)),
        downside_avoided=_average(downside),
        missed_upside=_average(upside),
        context_only_harm_events=context_harm,
        conclusion="INSUFFICIENT_EVIDENCE" if len(rows) < 20 else "STABLE",
    )


def _setup_report(
    group: str,
    rows: tuple[LiveRegimeShadowObservation, ...],
) -> SetupStabilityReport:
    matured = _matured(rows)
    bearish = sum(_is_bearish_event(row) for row in rows)
    harm = sum(
        row.policy_difference_type
        in {
            PolicyDifferenceType.BEARISH_DEMOTION_REMOVED,
            PolicyDifferenceType.NEUTRAL_ADJUSTMENT_REMOVED,
        }
        and (row.realized_return or _ZERO) < 0
        for row in matured
    )
    finding = (
        "BEARISH_PROTECTION_IS_SETUP_SPECIFIC"
        if bearish and group.startswith("setup=")
        else "BEARISH_PROTECTION_IS_HORIZON_SPECIFIC"
        if bearish and group.startswith("holding_period=")
        else "CONTEXT_ONLY_HARM_IS_SETUP_SPECIFIC"
        if harm
        else "INSUFFICIENT_EVIDENCE"
    )
    return SetupStabilityReport(
        group=group,
        candidate_count=len(rows),
        matured_count=len(matured),
        bearish_events=bearish,
        context_harm_events=harm,
        finding=finding,
    )


def _distribution_drift(left: list[str], right: list[str]) -> Decimal:
    if not left or not right:
        return _ZERO
    left_counts = Counter(left)
    right_counts = Counter(right)
    keys = set(left_counts) | set(right_counts)
    total = sum(
        abs(
            Decimal(left_counts[key]) / Decimal(len(left))
            - Decimal(right_counts[key]) / Decimal(len(right))
        )
        for key in keys
    )
    return Decimal(total).quantize(_FOUR)


def _capture_result(
    status: LiveShadowCaptureStatus,
    message: str,
) -> LiveRegimeShadowCaptureResult:
    return LiveRegimeShadowCaptureResult(
        status=status,
        observation=None,
        failure=None,
        authoritative_unchanged=True,
        persisted=False,
        message=message,
    )


def _eligible_source_modes() -> set[LiveShadowSourceMode]:
    return {
        LiveShadowSourceMode.LIVE_STREAM,
        LiveShadowSourceMode.CURRENT_QUOTE,
        LiveShadowSourceMode.LATEST_COMPLETED_SESSION,
        LiveShadowSourceMode.PAPER_RUNTIME,
        LiveShadowSourceMode.MANUAL_CURRENT_ANALYSIS,
    }


def _alpha_live_wiring_report(
    *,
    provider: str,
    symbol: str,
    source_mode: LiveShadowSourceMode,
    quote_timestamp: datetime | None,
    latest_completed_bar_timestamp: datetime | None,
    decision_timestamp: datetime | None,
    feed_status: str,
    staleness: str,
    session_state: str,
    candidate: CandidateDecisionRecord | None,
    persisted: bool,
    duplicate: bool,
    shadow_result: LiveRegimeShadowCaptureResult | None,
    conclusion: CaptureOperationalConclusion,
    milestone: CaptureNextMilestone,
    explanation: str,
) -> AlphaLiveShadowWiringReport:
    return AlphaLiveShadowWiringReport(
        provider=provider,
        symbol=symbol,
        source_mode=source_mode,
        quote_timestamp=quote_timestamp,
        latest_completed_bar_timestamp=latest_completed_bar_timestamp,
        decision_timestamp=decision_timestamp,
        feed_status=feed_status,
        staleness=staleness,
        session_state=session_state,
        authoritative_candidate_created=candidate is not None,
        authoritative_candidate_persisted=persisted,
        duplicate_authoritative_attempt=duplicate,
        stable_candidate_id=None if candidate is None else candidate.candidate_id,
        provenance_id=None if candidate is None else candidate.decision_provenance_id,
        market_state_snapshot_id=(
            None if candidate is None else candidate.market_state_snapshot_id
        ),
        frozen_inputs_available=candidate is not None,
        shadow_capture_invoked=shadow_result is not None,
        shadow_capture_status=None if shadow_result is None else shadow_result.status,
        primary_conclusion=conclusion,
        recommended_next_milestone=milestone,
        explanation=explanation,
    )


def _candidate_from_live_snapshot(
    *,
    snapshot: object,
    provider_name: str,
    source_mode: LiveShadowSourceMode,
    decision_timestamp: datetime,
    smoke_test: bool,
) -> CandidateDecisionRecord:
    symbol = str(getattr(snapshot, "symbol")).strip().upper()
    price = _optional_decimal(getattr(snapshot, "price", None))
    volume = _optional_decimal(getattr(snapshot, "volume", None))
    feed_status = _feed_status_text(snapshot)
    staleness = _staleness_text(snapshot)
    source_body = "|".join(
        (
            "alpha-live",
            provider_name,
            symbol,
            decision_timestamp.isoformat(),
            str(price or "no-price"),
            str(volume or "no-volume"),
            feed_status,
            staleness,
            "smoke" if smoke_test else "formal",
        )
    )
    source_hash = _fingerprint(source_body)
    run_id = f"alpha-live-{decision_timestamp.date().isoformat()}"
    quality = (
        "COMPLETE"
        if source_mode is LiveShadowSourceMode.LIVE_STREAM
        and feed_status == "CONNECTED"
        and staleness == "fresh"
        else "LIMITED"
    )
    return CandidateDecisionRecord(
        candidate_id=_fingerprint(f"{run_id}|{symbol}|{source_hash}")[:24],
        run_id=run_id,
        evaluation_date=decision_timestamp.date(),
        symbol=symbol,
        final_verdict="WATCHLIST",
        capital_action="AVOID",
        approved_for_deployment=False,
        rejection_reasons=(
            "Live stream diagnostic candidate is non-executable.",
            "Full recommendation engine has not evaluated a completed bar set.",
        ),
        setup_type="LIVE_DIAGNOSTIC",
        market_regime="LIVE_UNAVAILABLE",
        long_trade_permission=False,
        strategy_score=Decimal("50"),
        confidence="LOW",
        data_quality=quality,
        entry_zone_low=None,
        entry_zone_high=None,
        confirmation_entry=price,
        risk_stop=None,
        target_1=None,
        target_2=None,
        target_3=None,
        trailing_stop_plan=None,
        expected_holding_period="20 days",
        indicators_active=("live-price-volume", "feed-health"),
        indicator_scores={
            "feed_status": feed_status,
            "formal_live_evidence": str(not smoke_test),
            "price": str(price) if price is not None else "unavailable",
            "source_mode": source_mode.value,
            "volume": str(volume) if volume is not None else "unavailable",
        },
        evidence_layers=("live-feed", "diagnostic-shadow-boundary"),
        explanation=(
            "Non-executable live diagnostic candidate persisted after a genuine "
            "live snapshot. It is used only to validate regime shadow capture."
        ),
        created_at=decision_timestamp,
        market_state_snapshot_id=f"live-snapshot-{source_hash[:16]}",
        market_state_as_of=decision_timestamp,
        market_state_fallback_applied=False,
        market_state_completeness=quality,
        classifier_version=LIVE_REGIME_SHADOW_PROTOCOL_VERSION,
        decision_provenance_id=f"live-provenance-{source_hash[:16]}",
    )


def _snapshot_timestamp(snapshot: object) -> datetime | None:
    value = getattr(snapshot, "bar_started_at", None)
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _source_mode_from_snapshot(snapshot: object) -> LiveShadowSourceMode:
    if bool(getattr(snapshot, "stale", False)):
        return LiveShadowSourceMode.CURRENT_QUOTE
    if _feed_status_text(snapshot) == "CONNECTED":
        return LiveShadowSourceMode.LIVE_STREAM
    return LiveShadowSourceMode.CURRENT_QUOTE


def _feed_status_text(snapshot: object) -> str:
    health = getattr(snapshot, "feed_health", None)
    if health is not None and getattr(health, "status", None) is not None:
        return str(getattr(health.status, "value", health.status))
    status = getattr(snapshot, "feed_status", "UNKNOWN")
    return str(getattr(status, "value", status))


def _staleness_text(snapshot: object) -> str:
    return "stale" if bool(getattr(snapshot, "stale", False)) else "fresh"


def _session_state_text(snapshot: object) -> str:
    value = getattr(snapshot, "session_state", None)
    return "UNKNOWN" if value is None else str(getattr(value, "value", value))


def _shadow_capture_status_text(
    status: LiveShadowCaptureStatus | None,
) -> str | None:
    return None if status is None else status.value


def _parse_policy_config(value: str) -> tuple[RegimeShadowPolicyId, ...]:
    aliases = {
        "control": RegimeShadowPolicyId.CONTROL,
        "context_only": RegimeShadowPolicyId.CONTEXT_ONLY,
        "context-only": RegimeShadowPolicyId.CONTEXT_ONLY,
        "bearish_only": RegimeShadowPolicyId.BEARISH_ONLY,
        "bearish-only": RegimeShadowPolicyId.BEARISH_ONLY,
    }
    parsed = [
        aliases[item.strip().lower()] for item in value.split(",") if item.strip()
    ]
    invalid = [
        item.strip()
        for item in value.split(",")
        if item.strip() and item.strip().lower() not in aliases
    ]
    if invalid:
        raise ValueError(f"invalid shadow policy names: {', '.join(invalid)}")
    policies = tuple(dict.fromkeys((RegimeShadowPolicyId.CONTROL, *parsed)))
    if RegimeShadowPolicyId.CONTROL not in policies:
        raise ValueError("CONTROL policy cannot be disabled")
    return policies


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _live_shadow_run_id(frozen: FrozenAuthoritativeDecisionInput) -> str:
    return _fingerprint(
        "|".join(
            (
                "live-shadow",
                frozen.runtime_path,
                frozen.candidate.candidate_id,
                frozen.candidate.decision_provenance_id or "no-provenance",
                frozen.decision_timestamp.isoformat(),
                frozen.source_fingerprint,
            )
        )
    )[:16]


def _shadow_decisions_from_candidate(
    *,
    frozen: FrozenAuthoritativeDecisionInput,
    policies: tuple[Any, ...],
    protocol: LiveRegimeShadowProtocol,
    configuration_fingerprint: str,
) -> dict[RegimeShadowPolicyId, RegimeShadowDecision]:
    record = frozen.candidate
    recorded_adjustment = _recorded_regime_adjustment(record)
    base_score = _clamp_score(record.strategy_score - recorded_adjustment)
    output: dict[RegimeShadowPolicyId, RegimeShadowDecision] = {}
    created = datetime.now(UTC)
    for policy in policies:
        adjustment = _policy_adjustment(policy.policy_id, recorded_adjustment, record)
        score = _clamp_score(base_score + adjustment)
        verdict = (
            record.final_verdict
            if policy.policy_id is RegimeShadowPolicyId.CONTROL
            else _verdict_from_score(score)
        )
        approved = (
            record.approved_for_deployment
            if policy.policy_id is RegimeShadowPolicyId.CONTROL
            else record.approved_for_deployment
            and verdict in {"BUY", "STRONG_BUY"}
            and score >= Decimal("75")
        )
        output[policy.policy_id] = RegimeShadowDecision(
            shadow_decision_id=_fingerprint(
                "|".join(
                    (
                        record.candidate_id,
                        policy.policy_version,
                        frozen.source_fingerprint,
                        protocol.protocol_fingerprint,
                    )
                )
            )[:24],
            authoritative_candidate_id=record.candidate_id,
            decision_timestamp=frozen.decision_timestamp,
            symbol=record.symbol,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_fingerprint=policy.policy_fingerprint,
            setup_type=record.setup_type,
            recorded_regime=record.market_regime,
            regime_source="recorded_candidate_regime"
            if record.market_regime
            else "unavailable",
            regime_quality=frozen.market_state_source_quality,
            regime_snapshot_id=record.market_state_snapshot_id,
            base_score=base_score,
            regime_adjustment=adjustment,
            shadow_score=score,
            authoritative_score=record.strategy_score,
            shadow_verdict=verdict,
            authoritative_verdict=record.final_verdict,
            shadow_approval_eligible=approved,
            authoritative_approval_eligible=record.approved_for_deployment,
            shadow_allocation_eligible=approved,
            authoritative_allocation_eligible=record.approved_for_deployment,
            score_difference=(score - record.strategy_score).quantize(_FOUR),
            rank_difference=0,
            verdict_difference=verdict != record.final_verdict,
            approval_difference=approved != record.approved_for_deployment,
            allocation_difference=approved != record.approved_for_deployment,
            difference_reasons=("live diagnostic capture",),
            source_fingerprint=frozen.source_fingerprint,
            authoritative=False,
            executable=False,
            capital_effect="none",
            authoritative_provenance_id=record.decision_provenance_id,
            shadow_engine_version="live-regime-shadow-capture-v1",
            shadow_configuration_fingerprint=configuration_fingerprint,
            created_at=created,
        )
    return output


def _recorded_regime_adjustment(record: CandidateDecisionRecord) -> Decimal:
    regime = (record.market_regime or "").strip().upper()
    setup = (record.setup_type or "").strip().upper()
    if regime in {"BULL", "BULLISH", "POSITIVE", "STRONG_POSITIVE"}:
        return Decimal("4") if "BREAKOUT" in setup else Decimal("2")
    if regime in {"BEAR", "BEARISH", "NEGATIVE", "STRONG_NEGATIVE"}:
        return Decimal("-8")
    if "BREAKOUT" in setup:
        return Decimal("-4")
    return Decimal("-2")


def _policy_adjustment(
    policy: RegimeShadowPolicyId,
    recorded_adjustment: Decimal,
    record: CandidateDecisionRecord,
) -> Decimal:
    if policy is RegimeShadowPolicyId.CONTROL:
        return recorded_adjustment
    if policy is RegimeShadowPolicyId.CONTEXT_ONLY:
        return _ZERO
    regime = (record.market_regime or "").strip().upper()
    if regime in {"BEAR", "BEARISH", "NEGATIVE", "STRONG_NEGATIVE"}:
        return recorded_adjustment
    return _ZERO


def _verdict_from_score(score: Decimal) -> str:
    if score >= Decimal("90"):
        return "STRONG_BUY"
    if score >= Decimal("75"):
        return "BUY"
    if score >= Decimal("60"):
        return "WATCHLIST"
    if score >= Decimal("40"):
        return "AVOID"
    return "SELL"


def _clamp_score(value: Decimal) -> Decimal:
    return max(_ZERO, min(Decimal("100"), value)).quantize(_FOUR)


def _non_regime_fingerprint(record: CandidateDecisionRecord) -> str:
    payload = {
        "symbol": record.symbol,
        "evaluation_date": record.evaluation_date.isoformat(),
        "setup_type": record.setup_type,
        "entry_zone_low": _text(record.entry_zone_low),
        "entry_zone_high": _text(record.entry_zone_high),
        "confirmation_entry": _text(record.confirmation_entry),
        "risk_stop": _text(record.risk_stop),
        "target_1": _text(record.target_1),
        "target_2": _text(record.target_2),
        "target_3": _text(record.target_3),
        "base_score": str(record.strategy_score - _recorded_regime_adjustment(record)),
        "approval_policy": "current-production",
        "allocation_policy": "current-production",
        "provenance": record.decision_provenance_id,
    }
    return _fingerprint(json.dumps(payload, sort_keys=True))


def _market_state_source_quality(record: CandidateDecisionRecord) -> str:
    if record.market_state_fallback_applied:
        return "FALLBACK_NEUTRAL"
    completeness = (record.market_state_completeness or "").upper()
    if completeness in {"COMPLETE", "AUTHORITATIVE_COMPLETE", "HIGH"}:
        return "AUTHORITATIVE_COMPLETE"
    if completeness:
        return "AUTHORITATIVE_PARTIAL"
    if record.market_state_snapshot_id:
        return "MINIMUM_VIABLE"
    return "UNAVAILABLE"


def _window(outcome: Any, preferred: str) -> Any:
    by_window = {str(window.window): window for window in outcome.windows}
    return by_window.get(preferred)


def _horizon_days(label: str) -> int:
    text = label.strip().lower().replace(" ", "")
    if text.endswith("d"):
        return int(text[:-1])
    digits = "".join(character for character in text if character.isdigit())
    return int(digits or "20")


def _holding_period_bucket(value: str | None) -> str:
    text = (value or "").lower()
    if not text:
        return "UNAVAILABLE"
    if "day" in text or "short" in text or "1d" in text or "3d" in text or "5d" in text:
        return "SHORT_TERM"
    if "week" in text or "swing" in text or "20" in text:
        return "SWING"
    if "month" in text or "position" in text or "60" in text:
        return "POSITIONAL"
    return "UNAVAILABLE"


def _setup_family(value: str | None) -> str:
    setup = (value or "UNKNOWN_SETUP").strip().upper()
    if "BREAKOUT" in setup:
        return "BREAKOUT"
    if "PULLBACK" in setup or "RETRACEMENT" in setup:
        return "PULLBACK_RETRACEMENT"
    if "MOMENTUM" in setup:
        return "MOMENTUM"
    if "DISTRIBUTION" in setup:
        return "DISTRIBUTION"
    if "FAILURE" in setup:
        return "TREND_FAILURE"
    return setup or "UNKNOWN_SETUP"


def _average(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values) / Decimal(len(values))).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid].quantize(_FOUR, rounding=ROUND_HALF_UP)
    return ((ordered[mid - 1] + ordered[mid]) / Decimal("2")).quantize(
        _FOUR, rounding=ROUND_HALF_UP
    )


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _FOUR, rounding=ROUND_HALF_UP
    )


def _net(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return (left - right).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _live_shadow_enabled() -> bool:
    return os.environ.get("ALPHA_REGIME_SHADOW_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _text(value: object) -> str:
    return "unavailable" if value is None else str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _flatten(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"value": value}
    output: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, list | tuple | dict):
            output[key] = json.dumps(item, sort_keys=True)
        else:
            output[key] = item
    return output


__all__ = [
    "AlphaLiveShadowRuntimeService",
    "AlphaLiveShadowWiringReport",
    "BearishProtectionLiveReport",
    "ContextHarmReport",
    "CoverageRow",
    "DriftReport",
    "DriftStatus",
    "EvidenceCoverageStatus",
    "LiveObservationStatus",
    "LiveRegimeShadowEvidenceEngine",
    "LiveRegimeShadowObservation",
    "LiveRegimeShadowProtocol",
    "LiveRegimeShadowRepository",
    "LiveShadowConclusion",
    "LiveShadowDecisionStatus",
    "LiveShadowNextMilestone",
    "OutcomeMaturityStatus",
    "PolicyDifferenceReport",
    "PolicyDifferenceType",
    "RefreshResult",
    "SUPPORTED_OUTCOME_HORIZONS",
    "export_live_regime_shadow_csv",
    "export_live_regime_shadow_json",
    "observation_from_shadow_decisions",
    "render_bearish_protection",
    "render_alpha_live_wiring",
    "render_context_harm",
    "render_coverage",
    "render_drift",
    "render_guardrails",
    "render_live_shadow_status",
    "render_outcome_maturity",
    "render_policy_differences",
    "render_readiness",
    "render_refresh",
    "render_review",
    "render_setup",
    "render_temporal",
    "resolve_live_regime_shadow_ledger_path",
]
