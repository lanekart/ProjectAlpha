"""Configured application request provider for DSI-002A forward capture."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from alpha.application.intelligence_inputs import IntelligenceInputSet
from alpha.decision_superiority.gate_isolation_execution_outcome_producers import (
    ExecutionStateCaptureInput,
    OutcomePolicyCaptureInput,
)
from alpha.decision_superiority.gate_isolation_frozen_input_assembler import (
    FrozenInputAssemblyRequest,
)
from alpha.decision_superiority.gate_isolation_frozen_input_producers import (
    CandidateFeatureCaptureInput,
    PortfolioStateCaptureInput,
    _normalise,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey
from alpha.decision_superiority.gate_isolation_policy_producers import (
    ApprovalPolicyCaptureInput,
    EntryPolicyCaptureInput,
)
from alpha.decision_superiority.gate_isolation_source_lineage_producer import (
    SourceLineageCaptureInput,
)


@dataclass(frozen=True, slots=True)
class FrozenCapturePolicyBundle:
    """Explicit governed policies and state versions for forward capture."""

    feature_version: str
    approval_policy: Mapping[str, object]
    approval_policy_version: str
    threshold_provenance: Mapping[str, object]
    approval_dependency_versions: Mapping[str, str]
    portfolio_state_version: str
    entry_policy: Mapping[str, object]
    entry_policy_version: str
    trigger_payload: Mapping[str, object]
    trigger_source_hashes: Mapping[str, str]
    execution_state: Mapping[str, object]
    execution_state_version: str
    execution_source_hashes: Mapping[str, str]
    outcome_policy: Mapping[str, object]
    outcome_policy_version: str
    outcome_dependency_versions: Mapping[str, str]
    provider_versions: Mapping[str, str]
    dataset_versions: Mapping[str, str]
    source_paths: Mapping[str, str]
    artifact_hashes: Mapping[str, str]
    price_view: str = "RAW"

    def __post_init__(self) -> None:
        required_text = (
            self.feature_version,
            self.approval_policy_version,
            self.portfolio_state_version,
            self.entry_policy_version,
            self.execution_state_version,
            self.outcome_policy_version,
            self.price_view,
        )
        if any(not value.strip() for value in required_text):
            raise ValueError("capture policy bundle versions cannot be empty")


class ConfiguredFrozenInputAssemblyRequestProvider:
    """Build one complete request from canonical application inputs."""

    def __init__(self, bundle: FrozenCapturePolicyBundle) -> None:
        self._bundle = bundle

    def build(
        self,
        *,
        inputs: IntelligenceInputSet,
        observed_on: date,
    ) -> FrozenInputAssemblyRequest:
        """Capture the deterministic first candidate at the input seam."""

        candidate = sorted(
            inputs.recommendation_candidates,
            key=lambda item: item.symbol,
        )[0]
        observed_text = observed_on.isoformat()
        candidate_payload = {"candidate": candidate}
        market_payload = {
            "breadth": inputs.breadth,
            "correlation": inputs.correlation,
            "sectors": inputs.sectors,
            "stock": inputs.stock,
        }
        candidate_hash = _payload_hash(candidate_payload)
        market_hash = _payload_hash(market_payload)
        fingerprint = _payload_hash(
            {
                "candidate_hash": candidate_hash,
                "market_hash": market_hash,
                "observed_on": observed_text,
                "symbol": candidate.symbol,
            }
        )
        key = FrozenCandidateKey(
            self._bundle.price_view,
            observed_text,
            candidate.symbol,
            fingerprint,
        )
        artifact_hashes = dict(self._bundle.artifact_hashes)
        artifact_hashes.update(
            {
                "candidate_input": candidate_hash,
                "market_input": market_hash,
            }
        )
        execution = self._bundle.execution_state
        outcome = self._bundle.outcome_policy
        return FrozenInputAssemblyRequest(
            candidate=key,
            candidate_features=CandidateFeatureCaptureInput(
                candidate_payload=candidate_payload,
                market_payload=market_payload,
                feature_version=self._bundle.feature_version,
                source_hashes={
                    "candidate_input": candidate_hash,
                    "market_input": market_hash,
                },
                observed_on=observed_text,
            ),
            approval_policy=ApprovalPolicyCaptureInput(
                policy_payload=self._bundle.approval_policy,
                policy_version=self._bundle.approval_policy_version,
                threshold_provenance=self._bundle.threshold_provenance,
                dependency_versions=(
                    self._bundle.approval_dependency_versions
                ),
                observed_on=observed_text,
            ),
            portfolio_state=PortfolioStateCaptureInput(
                recommendation_context=(
                    inputs.recommendation_portfolio_context
                ),
                allocation_context=inputs.allocation_portfolio_context,
                state_version=self._bundle.portfolio_state_version,
                observed_on=observed_text,
            ),
            entry_policy=EntryPolicyCaptureInput(
                policy_payload=self._bundle.entry_policy,
                policy_version=self._bundle.entry_policy_version,
                trigger_payload=self._bundle.trigger_payload,
                trigger_source_hashes=self._bundle.trigger_source_hashes,
                observed_on=observed_text,
            ),
            execution_state=ExecutionStateCaptureInput(
                cash_state={"cash": execution.get("cash")},
                sizing_state={
                    "sizing_limit": execution.get("sizing_limit")
                },
                liquidity_constraints=_mapping_field(
                    execution,
                    "liquidity_constraints",
                ),
                participation_constraints={
                    "participation_limit": execution.get(
                        "participation_limit"
                    )
                },
                queue_state={"queue": execution.get("queue", [])},
                risk_budget_state={
                    "risk_budget": execution.get("risk_budget")
                },
                state_version=self._bundle.execution_state_version,
                observed_on=observed_text,
            ),
            outcome_policy=OutcomePolicyCaptureInput(
                exit_policy={"exit_rules": outcome.get("exit_rules", [])},
                stop_policy=_mapping_field(outcome, "stop_policy"),
                target_policy=_mapping_field(outcome, "target_policy"),
                trailing_policy=_mapping_field(outcome, "trailing_policy"),
                time_exit_policy=_mapping_field(
                    outcome,
                    "time_exit_policy",
                ),
                ambiguity_policy=_mapping_field(
                    outcome,
                    "ambiguity_policy",
                ),
                policy_version=self._bundle.outcome_policy_version,
                dependency_versions=(
                    self._bundle.outcome_dependency_versions
                ),
                observed_on=observed_text,
            ),
            source_lineage=SourceLineageCaptureInput(
                artifact_hashes=artifact_hashes,
                provider_versions=self._bundle.provider_versions,
                source_paths=self._bundle.source_paths,
                dataset_versions=self._bundle.dataset_versions,
                observed_on=observed_text,
            ),
        )


def _mapping_field(
    container: Mapping[str, object],
    key: str,
) -> dict[str, object]:
    value = container.get(key, {})
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return {str(item_key): item for item_key, item in value.items()}


def _payload_hash(payload: Mapping[str, object]) -> str:
    normalised = _normalise(payload)
    encoded = json.dumps(
        normalised,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ConfiguredFrozenInputAssemblyRequestProvider",
    "FrozenCapturePolicyBundle",
]
