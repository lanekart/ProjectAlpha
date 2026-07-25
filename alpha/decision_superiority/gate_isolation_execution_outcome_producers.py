"""Execution-state and outcome-policy producers for DSI-002A capture."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from alpha.decision_superiority.gate_isolation_frozen_input_producers import (
    _normalise,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputSection,
    FrozenInputSectionSnapshot,
)

EXECUTION_STATE_PRODUCER_VERSION = "DSI-002A-execution-state-v1"
OUTCOME_POLICY_PRODUCER_VERSION = "DSI-002A-outcome-policy-v1"


@dataclass(frozen=True, slots=True)
class ExecutionStateCaptureInput:
    """Immutable execution state available before recommendation evaluation."""

    cash_state: Mapping[str, object]
    sizing_state: Mapping[str, object]
    liquidity_constraints: Mapping[str, object]
    participation_constraints: Mapping[str, object]
    queue_state: Mapping[str, object]
    risk_budget_state: Mapping[str, object]
    state_version: str
    observed_on: str

    def __post_init__(self) -> None:
        required = (
            ("cash_state", self.cash_state),
            ("sizing_state", self.sizing_state),
            ("participation_constraints", self.participation_constraints),
            ("risk_budget_state", self.risk_budget_state),
        )
        for name, value in required:
            if not value:
                raise ValueError(f"{name} cannot be empty")
        if not self.state_version.strip():
            raise ValueError("state_version cannot be empty")
        if not self.observed_on.strip():
            raise ValueError("observed_on cannot be empty")


@dataclass(frozen=True, slots=True)
class OutcomePolicyCaptureInput:
    """Frozen exit-policy configuration without a formed-trade claim."""

    exit_policy: Mapping[str, object]
    stop_policy: Mapping[str, object]
    target_policy: Mapping[str, object]
    trailing_policy: Mapping[str, object]
    time_exit_policy: Mapping[str, object]
    ambiguity_policy: Mapping[str, object]
    policy_version: str
    dependency_versions: Mapping[str, str]
    observed_on: str

    def __post_init__(self) -> None:
        if not self.exit_policy:
            raise ValueError("exit_policy cannot be empty")
        if not self.policy_version.strip():
            raise ValueError("policy_version cannot be empty")
        if not self.dependency_versions:
            raise ValueError("dependency_versions cannot be empty")
        if any(
            not key.strip() or not value.strip()
            for key, value in self.dependency_versions.items()
        ):
            raise ValueError(
                "dependency_versions keys and values cannot be empty"
            )
        if not self.observed_on.strip():
            raise ValueError("observed_on cannot be empty")


class ExecutionStateSnapshotProducer:
    """Produce canonical pre-decision execution-state evidence."""

    def produce(
        self,
        capture_input: ExecutionStateCaptureInput,
    ) -> FrozenInputSectionSnapshot:
        """Return a deterministic execution-state snapshot."""

        payload = {
            "cash_state": _normalise(capture_input.cash_state),
            "liquidity_constraints": _normalise(
                capture_input.liquidity_constraints
            ),
            "participation_constraints": _normalise(
                capture_input.participation_constraints
            ),
            "queue_state": _normalise(capture_input.queue_state),
            "risk_budget_state": _normalise(
                capture_input.risk_budget_state
            ),
            "sizing_state": _normalise(capture_input.sizing_state),
            "state_version": capture_input.state_version,
        }
        return FrozenInputSectionSnapshot.from_mapping(
            section=FrozenInputSection.EXECUTION_STATE,
            payload=payload,
            source_version=EXECUTION_STATE_PRODUCER_VERSION,
            observed_on=capture_input.observed_on,
        )


class OutcomePolicySnapshotProducer:
    """Produce canonical frozen outcome policy without outcome attachment."""

    def produce(
        self,
        capture_input: OutcomePolicyCaptureInput,
    ) -> FrozenInputSectionSnapshot:
        """Return a deterministic outcome-policy snapshot."""

        payload = {
            "ambiguity_policy": _normalise(
                capture_input.ambiguity_policy
            ),
            "dependency_versions": _normalise(
                capture_input.dependency_versions
            ),
            "exit_policy": _normalise(capture_input.exit_policy),
            "formed_trade_identity": None,
            "policy_version": capture_input.policy_version,
            "stop_policy": _normalise(capture_input.stop_policy),
            "target_policy": _normalise(capture_input.target_policy),
            "time_exit_policy": _normalise(
                capture_input.time_exit_policy
            ),
            "trailing_policy": _normalise(
                capture_input.trailing_policy
            ),
        }
        return FrozenInputSectionSnapshot.from_mapping(
            section=FrozenInputSection.OUTCOME_POLICY,
            payload=payload,
            source_version=OUTCOME_POLICY_PRODUCER_VERSION,
            observed_on=capture_input.observed_on,
        )


__all__ = [
    "EXECUTION_STATE_PRODUCER_VERSION",
    "OUTCOME_POLICY_PRODUCER_VERSION",
    "ExecutionStateCaptureInput",
    "ExecutionStateSnapshotProducer",
    "OutcomePolicyCaptureInput",
    "OutcomePolicySnapshotProducer",
]
