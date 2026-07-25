"""Partial frozen-input assembly for DSI-002A pre-decision capture."""

from __future__ import annotations

from dataclasses import dataclass

from alpha.decision_superiority.gate_isolation_frozen_input_producers import (
    CandidateFeatureCaptureInput,
    CandidateFeatureSnapshotProducer,
    PortfolioStateCaptureInput,
    PortfolioStateSnapshotProducer,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenCandidateInputSnapshot,
    FrozenInputContractValidator,
    FrozenInputReadiness,
    FrozenInputSection,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey
from alpha.decision_superiority.gate_isolation_policy_producers import (
    ApprovalPolicyCaptureInput,
    ApprovalPolicySnapshotProducer,
    EntryPolicyCaptureInput,
    EntryPolicySnapshotProducer,
)


@dataclass(frozen=True, slots=True)
class FrozenInputAssemblyRequest:
    """Inputs available at the pre-recommendation capture seam."""

    candidate: FrozenCandidateKey
    candidate_features: CandidateFeatureCaptureInput
    approval_policy: ApprovalPolicyCaptureInput
    portfolio_state: PortfolioStateCaptureInput
    entry_policy: EntryPolicyCaptureInput

    def __post_init__(self) -> None:
        observed_on = self.candidate.observed_on
        dated_inputs = (
            ("candidate feature", self.candidate_features.observed_on),
            ("approval policy", self.approval_policy.observed_on),
            ("portfolio state", self.portfolio_state.observed_on),
            ("entry policy", self.entry_policy.observed_on),
        )
        for name, section_date in dated_inputs:
            if section_date != observed_on:
                raise ValueError(f"{name} observation date mismatch")


@dataclass(frozen=True, slots=True)
class FrozenInputAssemblyResult:
    """Partial snapshot plus explicit unavailable section diagnostics."""

    snapshot: FrozenCandidateInputSnapshot
    present_sections: tuple[FrozenInputSection, ...]
    missing_sections: tuple[FrozenInputSection, ...]
    readiness: FrozenInputReadiness
    replay_ready: bool
    persistence_permitted: bool
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("frozen-input assembly must remain diagnostic-only")
        if self.persistence_permitted and not self.replay_ready:
            raise ValueError("incomplete snapshot cannot be persisted")
        if tuple(sorted(self.present_sections)) != self.present_sections:
            raise ValueError("present_sections must be sorted")
        if tuple(sorted(self.missing_sections)) != self.missing_sections:
            raise ValueError("missing_sections must be sorted")


class FrozenInputAssembler:
    """Assemble available sections without fabricating unavailable inputs."""

    def assemble(
        self,
        request: FrozenInputAssemblyRequest,
    ) -> FrozenInputAssemblyResult:
        """Build a partial snapshot and fail closed on persistence readiness."""

        sections = (
            ApprovalPolicySnapshotProducer().produce(
                request.approval_policy
            ),
            CandidateFeatureSnapshotProducer().produce(
                request.candidate_features
            ),
            EntryPolicySnapshotProducer().produce(request.entry_policy),
            PortfolioStateSnapshotProducer().produce(
                request.portfolio_state
            ),
        )
        snapshot = FrozenCandidateInputSnapshot.build(
            candidate=request.candidate,
            sections=sections,
        )
        validation = FrozenInputContractValidator().validate(snapshot)
        present = tuple(sorted(item.section for item in snapshot.sections))
        missing = tuple(sorted(validation.missing_sections))
        return FrozenInputAssemblyResult(
            snapshot=snapshot,
            present_sections=present,
            missing_sections=missing,
            readiness=validation.readiness,
            replay_ready=validation.replay_ready,
            persistence_permitted=validation.replay_ready,
        )


__all__ = [
    "FrozenInputAssembler",
    "FrozenInputAssemblyRequest",
    "FrozenInputAssemblyResult",
]
