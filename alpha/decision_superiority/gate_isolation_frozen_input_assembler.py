"""Complete frozen-input assembly for DSI-002A candidate capture."""

from __future__ import annotations

from dataclasses import dataclass

from alpha.decision_superiority.gate_isolation_execution_outcome_producers import (
    ExecutionStateCaptureInput,
    ExecutionStateSnapshotProducer,
    OutcomePolicyCaptureInput,
    OutcomePolicySnapshotProducer,
)
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
from alpha.decision_superiority.gate_isolation_source_lineage_producer import (
    SourceLineageCaptureInput,
    SourceLineageSnapshotProducer,
)


@dataclass(frozen=True, slots=True)
class FrozenInputAssemblyRequest:
    """All seven point-in-time inputs for a newly created candidate."""

    candidate: FrozenCandidateKey
    candidate_features: CandidateFeatureCaptureInput
    approval_policy: ApprovalPolicyCaptureInput
    portfolio_state: PortfolioStateCaptureInput
    entry_policy: EntryPolicyCaptureInput
    execution_state: ExecutionStateCaptureInput
    outcome_policy: OutcomePolicyCaptureInput
    source_lineage: SourceLineageCaptureInput

    def __post_init__(self) -> None:
        observed_on = self.candidate.observed_on
        dated_inputs = (
            ("candidate feature", self.candidate_features.observed_on),
            ("approval policy", self.approval_policy.observed_on),
            ("portfolio state", self.portfolio_state.observed_on),
            ("entry policy", self.entry_policy.observed_on),
            ("execution state", self.execution_state.observed_on),
            ("outcome policy", self.outcome_policy.observed_on),
            ("source lineage", self.source_lineage.observed_on),
        )
        for name, section_date in dated_inputs:
            if section_date != observed_on:
                raise ValueError(f"{name} observation date mismatch")


@dataclass(frozen=True, slots=True)
class FrozenInputAssemblyResult:
    """Complete snapshot and persistence readiness diagnostics."""

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
        if self.persistence_permitted != self.replay_ready:
            raise ValueError("persistence permission must equal replay readiness")
        if tuple(sorted(self.present_sections)) != self.present_sections:
            raise ValueError("present_sections must be sorted")
        if tuple(sorted(self.missing_sections)) != self.missing_sections:
            raise ValueError("missing_sections must be sorted")


class FrozenInputAssembler:
    """Assemble all governed sections without fabricating candidate outcomes."""

    def assemble(
        self,
        request: FrozenInputAssemblyRequest,
    ) -> FrozenInputAssemblyResult:
        """Build and validate one complete frozen-input snapshot."""

        sections = (
            ApprovalPolicySnapshotProducer().produce(
                request.approval_policy
            ),
            CandidateFeatureSnapshotProducer().produce(
                request.candidate_features
            ),
            EntryPolicySnapshotProducer().produce(request.entry_policy),
            ExecutionStateSnapshotProducer().produce(
                request.execution_state
            ),
            OutcomePolicySnapshotProducer().produce(
                request.outcome_policy
            ),
            PortfolioStateSnapshotProducer().produce(
                request.portfolio_state
            ),
            SourceLineageSnapshotProducer().produce(
                request.source_lineage
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
