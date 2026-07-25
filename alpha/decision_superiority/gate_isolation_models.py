"""Immutable models and governance states for DSI-002 gate isolation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

DSI002_CONTRACT_VERSION = "DSI-002-v1.0.0"
DSI002_RESEARCH_SCOPE = "GOVERNED_GATE_ISOLATION_SHADOW_DIAGNOSTIC_ONLY"


class GateIsolationReadiness(StrEnum):
    """Governed DSI-002 readiness decisions."""

    READY = "READY_FOR_GOVERNED_GATE_ISOLATION_RESEARCH"
    NO_EFFECTIVE_SINGLE_GATE_ARMS = "BLOCKED_BY_NO_EFFECTIVE_SINGLE_GATE_ARMS"
    NO_VALID_MINIMAL_REMEDIATION_SETS = (
        "BLOCKED_BY_NO_VALID_MINIMAL_REMEDIATION_SETS"
    )
    INSUFFICIENT_ISOLATED_OUTCOMES = "BLOCKED_BY_INSUFFICIENT_ISOLATED_OUTCOMES"
    COUNTERFACTUAL_SEMANTIC_INVALIDITY = (
        "BLOCKED_BY_COUNTERFACTUAL_SEMANTIC_INVALIDITY"
    )
    COMBINATORIAL_LIMIT = "BLOCKED_BY_COMBINATORIAL_LIMIT"
    MULTIPLE_TESTING_RISK = "BLOCKED_BY_MULTIPLE_TESTING_RISK"
    POINT_IN_TIME_LEAKAGE = "BLOCKED_BY_POINT_IN_TIME_LEAKAGE"
    UNEXPLAINED_ARM_DIVERGENCE = "BLOCKED_BY_UNEXPLAINED_ARM_DIVERGENCE"
    SOURCE_CONTRACT_FAILURE = "BLOCKED_BY_SOURCE_CONTRACT_FAILURE"
    IMPLEMENTATION_DEFECT = "BLOCKED_BY_IMPLEMENTATION_DEFECT"


class CounterfactualArmType(StrEnum):
    """Supported frozen-policy shadow arm families."""

    BASELINE = "BASELINE"
    SINGLE_GATE_PASS = "SINGLE_GATE_PASS"
    MINIMAL_REMEDIATION_SET = "MINIMAL_REMEDIATION_SET"


class CounterfactualSemanticStatus(StrEnum):
    """Explicit semantic validity and fail-closed states."""

    VALID_SINGLE_GATE_INTERVENTION = "VALID_SINGLE_GATE_INTERVENTION"
    VALID_MINIMAL_REMEDIATION_SET = "VALID_MINIMAL_REMEDIATION_SET"
    NO_DOWNSTREAM_EFFECT = "NO_DOWNSTREAM_EFFECT"
    NOT_SEMANTICALLY_VALID = "NOT_SEMANTICALLY_VALID"
    NOT_MINIMAL = "NOT_MINIMAL"
    COMBINATORIAL_LIMIT_REACHED = "COMBINATORIAL_LIMIT_REACHED"
    OUTCOME_UNAVAILABLE = "OUTCOME_UNAVAILABLE"
    CONFOUNDED_POPULATION = "CONFOUNDED_POPULATION"
    POINT_IN_TIME_LEAKAGE_DETECTED = "POINT_IN_TIME_LEAKAGE_DETECTED"
    UNEXPLAINED_ARM_DIVERGENCE = "UNEXPLAINED_ARM_DIVERGENCE"


@dataclass(frozen=True, slots=True, order=True)
class FrozenCandidateKey:
    """Stable point-in-time identity for one governed candidate."""

    price_view: str
    observed_on: str
    symbol: str
    input_fingerprint: str

    def __post_init__(self) -> None:
        for name, value in (
            ("price_view", self.price_view),
            ("observed_on", self.observed_on),
            ("symbol", self.symbol),
            ("input_fingerprint", self.input_fingerprint),
        ):
            if not value.strip():
                raise ValueError(f"{name} cannot be empty")


@dataclass(frozen=True, slots=True)
class GateIsolationArm:
    """One deterministic frozen-policy shadow intervention."""

    arm_id: str
    arm_type: CounterfactualArmType
    candidate: FrozenCandidateKey
    passed_gate_codes: tuple[str, ...]
    observed_failure_codes: tuple[str, ...]
    semantic_status: CounterfactualSemanticStatus
    production_influence: bool = False

    def __post_init__(self) -> None:
        if not self.arm_id.strip():
            raise ValueError("arm_id cannot be empty")
        if self.production_influence:
            raise ValueError("DSI-002 arms must remain diagnostic-only")
        if tuple(sorted(set(self.passed_gate_codes))) != self.passed_gate_codes:
            raise ValueError("passed_gate_codes must be unique and sorted")
        if tuple(sorted(set(self.observed_failure_codes))) != self.observed_failure_codes:
            raise ValueError("observed_failure_codes must be unique and sorted")
        unknown = set(self.passed_gate_codes) - set(self.observed_failure_codes)
        if unknown:
            raise ValueError("passed gates must be observed candidate failures")
        if self.arm_type is CounterfactualArmType.BASELINE and self.passed_gate_codes:
            raise ValueError("baseline arm cannot pass gates")
        if (
            self.arm_type is CounterfactualArmType.SINGLE_GATE_PASS
            and len(self.passed_gate_codes) != 1
        ):
            raise ValueError("single-gate arm must pass exactly one gate")
        if (
            self.arm_type is CounterfactualArmType.MINIMAL_REMEDIATION_SET
            and not self.passed_gate_codes
        ):
            raise ValueError("minimal remediation arm requires at least one gate")

    @property
    def remaining_failure_codes(self) -> tuple[str, ...]:
        """Return observed failures not shadow-passed by this arm."""

        passed = set(self.passed_gate_codes)
        return tuple(code for code in self.observed_failure_codes if code not in passed)

    @property
    def clears_all_observed_failures(self) -> bool:
        """Whether the intervention clears every observed blocker."""

        return not self.remaining_failure_codes


@dataclass(frozen=True, slots=True)
class DSI002GovernanceBoundary:
    """Immutable research-only influence contract."""

    causal_claim_permitted: bool = False
    threshold_change_permitted: bool = False
    approval_policy_change_permitted: bool = False
    portfolio_policy_change_permitted: bool = False
    execution_policy_change_permitted: bool = False
    recommendation_influence: bool = False
    execution_influence: bool = False
    active_replay_integration: bool = False
    production_influence: bool = False

    def __post_init__(self) -> None:
        if any(
            (
                self.causal_claim_permitted,
                self.threshold_change_permitted,
                self.approval_policy_change_permitted,
                self.portfolio_policy_change_permitted,
                self.execution_policy_change_permitted,
                self.recommendation_influence,
                self.execution_influence,
                self.active_replay_integration,
                self.production_influence,
            )
        ):
            raise ValueError("DSI-002 governance flags must remain false")


__all__ = [
    "CounterfactualArmType",
    "CounterfactualSemanticStatus",
    "DSI002_CONTRACT_VERSION",
    "DSI002_RESEARCH_SCOPE",
    "DSI002GovernanceBoundary",
    "FrozenCandidateKey",
    "GateIsolationArm",
    "GateIsolationReadiness",
]
