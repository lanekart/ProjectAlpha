"""Immutable frozen-policy producers for DSI-002A capture."""

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

APPROVAL_POLICY_PRODUCER_VERSION = "DSI-002A-approval-policy-v1"
ENTRY_POLICY_PRODUCER_VERSION = "DSI-002A-entry-policy-v1"


@dataclass(frozen=True, slots=True)
class ApprovalPolicyCaptureInput:
    """Immutable approval-policy payload available at candidate creation."""

    policy_payload: Mapping[str, object]
    policy_version: str
    threshold_provenance: Mapping[str, object]
    dependency_versions: Mapping[str, str]
    observed_on: str

    def __post_init__(self) -> None:
        if not self.policy_payload:
            raise ValueError("policy_payload cannot be empty")
        if not self.policy_version.strip():
            raise ValueError("policy_version cannot be empty")
        if not self.threshold_provenance:
            raise ValueError("threshold_provenance cannot be empty")
        if not self.dependency_versions:
            raise ValueError("dependency_versions cannot be empty")
        if not self.observed_on.strip():
            raise ValueError("observed_on cannot be empty")
        if any(
            not key.strip() or not value.strip()
            for key, value in self.dependency_versions.items()
        ):
            raise ValueError("dependency_versions keys and values cannot be empty")


@dataclass(frozen=True, slots=True)
class EntryPolicyCaptureInput:
    """Immutable entry-policy payload available at candidate creation."""

    policy_payload: Mapping[str, object]
    policy_version: str
    trigger_payload: Mapping[str, object]
    trigger_source_hashes: Mapping[str, str]
    observed_on: str

    def __post_init__(self) -> None:
        if not self.policy_payload:
            raise ValueError("policy_payload cannot be empty")
        if not self.policy_version.strip():
            raise ValueError("policy_version cannot be empty")
        if not self.trigger_payload:
            raise ValueError("trigger_payload cannot be empty")
        if not self.trigger_source_hashes:
            raise ValueError("trigger_source_hashes cannot be empty")
        if not self.observed_on.strip():
            raise ValueError("observed_on cannot be empty")
        if any(
            not key.strip() or not value.strip()
            for key, value in self.trigger_source_hashes.items()
        ):
            raise ValueError("trigger_source_hashes keys and values cannot be empty")


class ApprovalPolicySnapshotProducer:
    """Produce a canonical frozen approval-policy section."""

    def produce(
        self,
        capture_input: ApprovalPolicyCaptureInput,
    ) -> FrozenInputSectionSnapshot:
        """Return a deterministic approval-policy snapshot."""

        payload = {
            "dependency_versions": _normalise(capture_input.dependency_versions),
            "policy": _normalise(capture_input.policy_payload),
            "policy_version": capture_input.policy_version,
            "threshold_provenance": _normalise(capture_input.threshold_provenance),
        }
        return FrozenInputSectionSnapshot.from_mapping(
            section=FrozenInputSection.APPROVAL_POLICY,
            payload=payload,
            source_version=APPROVAL_POLICY_PRODUCER_VERSION,
            observed_on=capture_input.observed_on,
        )


class EntryPolicySnapshotProducer:
    """Produce a canonical frozen entry-policy section."""

    def produce(
        self,
        capture_input: EntryPolicyCaptureInput,
    ) -> FrozenInputSectionSnapshot:
        """Return a deterministic entry-policy snapshot."""

        payload = {
            "policy": _normalise(capture_input.policy_payload),
            "policy_version": capture_input.policy_version,
            "trigger": _normalise(capture_input.trigger_payload),
            "trigger_source_hashes": _normalise(capture_input.trigger_source_hashes),
        }
        return FrozenInputSectionSnapshot.from_mapping(
            section=FrozenInputSection.ENTRY_POLICY,
            payload=payload,
            source_version=ENTRY_POLICY_PRODUCER_VERSION,
            observed_on=capture_input.observed_on,
        )


__all__ = [
    "APPROVAL_POLICY_PRODUCER_VERSION",
    "ENTRY_POLICY_PRODUCER_VERSION",
    "ApprovalPolicyCaptureInput",
    "ApprovalPolicySnapshotProducer",
    "EntryPolicyCaptureInput",
    "EntryPolicySnapshotProducer",
]
