from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from alpha.adaptive_weights.models import (
    ADAPTIVE_WEIGHT_METHOD_VERSION,
    AlphaComponent,
    CandidatePolicyState,
    CandidateWeightPolicy,
    ComponentDecisionState,
    ComponentWeight,
    ComponentWeightDecision,
    ConditionalWeightSet,
    EvidenceQuality,
    ProposalGuardrails,
    WeightLayer,
    WeightProposal,
    WeightSet,
    to_primitive,
)


class CandidateWeightPolicyFactory:
    def create(
        self,
        proposal: WeightProposal,
        *,
        policy_id: str,
        parent_policy: str,
        conditional_weights: tuple[ConditionalWeightSet, ...],
        evidence_window: str,
        dataset_version: str,
        created_at: datetime | None = None,
    ) -> CandidateWeightPolicy:
        timestamp = (created_at or datetime.now(UTC)).astimezone(UTC)
        quality = _quality_state(proposal)
        payload = {
            "policy_id": policy_id,
            "parent_policy": parent_policy,
            "canonical_weights": to_primitive(proposal.baseline),
            "proposed_weights": to_primitive(proposal.proposed),
            "conditional_weights": to_primitive(conditional_weights),
            "evidence_window": evidence_window,
            "dataset_version": dataset_version,
            "outcome_count": proposal.evidence_count,
            "method_version": ADAPTIVE_WEIGHT_METHOD_VERSION,
            "guardrails": to_primitive(proposal.guardrails),
            "quality_state": quality.value,
            "validation_status": proposal.validation_status,
            "holdout_status": proposal.holdout_status,
            "forward_status": proposal.forward_status,
            "state": CandidatePolicyState.DRAFT.value,
            "created_at": timestamp.isoformat(),
            "component_decisions": to_primitive(proposal.decisions),
            "production_influence": False,
        }
        manifest_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return CandidateWeightPolicy(
            policy_id=policy_id,
            parent_policy=parent_policy,
            canonical_weights=proposal.baseline,
            proposed_weights=WeightSet(
                layer=WeightLayer.RESEARCH_PROPOSED_WEIGHTS,
                policy_id=policy_id,
                weights=proposal.proposed.weights,
            ),
            conditional_weights=conditional_weights,
            evidence_window=evidence_window,
            dataset_version=dataset_version,
            outcome_count=proposal.evidence_count,
            method_version=ADAPTIVE_WEIGHT_METHOD_VERSION,
            guardrails=proposal.guardrails,
            quality_state=quality,
            validation_status=proposal.validation_status,
            holdout_status=proposal.holdout_status,
            forward_status=proposal.forward_status,
            state=CandidatePolicyState.DRAFT,
            created_at=timestamp,
            manifest_hash=manifest_hash,
            component_decisions=proposal.decisions,
        )


class CandidateWeightPolicyRegistry:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = (
            Path(path)
            if path is not None
            else Path(".alpha/adaptive_weights/policies.json")
        )

    def next_policy_id(self) -> str:
        numbers = []
        for policy in self.load():
            suffix = policy.policy_id.rsplit("_", 1)[-1]
            if suffix.isdigit():
                numbers.append(int(suffix))
        return f"ALPHA_WEIGHT_RESEARCH_{max(numbers, default=0) + 1:04d}"

    def register(self, policy: CandidateWeightPolicy) -> bool:
        existing = {item.policy_id: item for item in self.load()}
        current = existing.get(policy.policy_id)
        if current is not None:
            if current.manifest_hash != policy.manifest_hash:
                raise ValueError(
                    "candidate policy IDs are immutable and cannot be replaced"
                )
            return False
        existing[policy.policy_id] = policy
        self._write(tuple(existing.values()))
        return True

    def load(self) -> tuple[CandidateWeightPolicy, ...]:
        if not self.path.exists():
            return ()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        rows = raw.get("policies", []) if isinstance(raw, dict) else []
        return tuple(
            sorted(
                (_policy_from_dict(row) for row in rows if isinstance(row, dict)),
                key=lambda item: item.policy_id,
            )
        )

    def get(self, policy_id: str) -> CandidateWeightPolicy | None:
        return next((item for item in self.load() if item.policy_id == policy_id), None)

    def export_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"policies": [to_primitive(item) for item in self.load()]},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def export_csv(self, path: Path) -> None:
        rows = []
        for policy in self.load():
            for weight in policy.proposed_weights.weights:
                rows.append(
                    {
                        "policy_id": policy.policy_id,
                        "parent_policy": policy.parent_policy,
                        "component": weight.component.value,
                        "canonical_weight": str(
                            policy.canonical_weights.for_component(weight.component)
                        ),
                        "proposed_weight": str(weight.weight),
                        "outcome_count": policy.outcome_count,
                        "quality_state": policy.quality_state.value,
                        "validation_status": policy.validation_status,
                        "holdout_status": policy.holdout_status,
                        "forward_status": policy.forward_status,
                        "state": policy.state.value,
                        "manifest_hash": policy.manifest_hash,
                        "production_influence": "false",
                    }
                )
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "policy_id",
            "parent_policy",
            "component",
            "canonical_weight",
            "proposed_weight",
            "outcome_count",
            "quality_state",
            "validation_status",
            "holdout_status",
            "forward_status",
            "state",
            "manifest_hash",
            "production_influence",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _write(self, policies: tuple[CandidateWeightPolicy, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "policies": [
                        to_primitive(item)
                        for item in sorted(policies, key=lambda value: value.policy_id)
                    ]
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _quality_state(proposal: WeightProposal) -> EvidenceQuality:
    decisions = {item.decision for item in proposal.decisions}
    if decisions == {ComponentDecisionState.INSUFFICIENT_EVIDENCE}:
        return EvidenceQuality.INSUFFICIENT
    if "INSUFFICIENT" in proposal.holdout_status:
        return EvidenceQuality.WEAK
    return EvidenceQuality.SUFFICIENT


def _weight_set(raw: object) -> WeightSet:
    payload = _object(raw, "weight set")
    weights = tuple(
        ComponentWeight(
            component=AlphaComponent(
                str(_object(item, "component weight")["component"])
            ),
            weight=Decimal(str(_object(item, "component weight")["weight"])),
        )
        for item in _list(payload.get("weights"), "weights")
    )
    return WeightSet(
        layer=WeightLayer(str(payload["layer"])),
        policy_id=str(payload["policy_id"]),
        weights=weights,
    )


def _guardrails(raw: object) -> ProposalGuardrails:
    payload = _object(raw, "guardrails")
    return ProposalGuardrails(
        maximum_relative_change=Decimal(str(payload["maximum_relative_change"])),
        maximum_absolute_weight=Decimal(str(payload["maximum_absolute_weight"])),
        minimum_absolute_weight=Decimal(str(payload["minimum_absolute_weight"])),
        weak_evidence_shrinkage=Decimal(str(payload["weak_evidence_shrinkage"])),
        moderate_evidence_shrinkage=Decimal(
            str(payload["moderate_evidence_shrinkage"])
        ),
        strong_evidence_shrinkage=Decimal(str(payload["strong_evidence_shrinkage"])),
        minimum_holdout_samples=int(payload["minimum_holdout_samples"]),
        minimum_forward_samples=int(payload["minimum_forward_samples"]),
        overlap_penalty=Decimal(str(payload["overlap_penalty"])),
    )


def _decision(raw: object) -> ComponentWeightDecision:
    payload = _object(raw, "component decision")
    return ComponentWeightDecision(
        component=AlphaComponent(str(payload["component"])),
        current_weight=Decimal(str(payload["current_weight"])),
        proposed_raw_weight=Decimal(str(payload["proposed_raw_weight"])),
        proposed_weight=Decimal(str(payload["proposed_weight"])),
        absolute_change=Decimal(str(payload["absolute_change"])),
        relative_change=Decimal(str(payload["relative_change"])),
        payoff_multiplier=Decimal(str(payload["payoff_multiplier"])),
        confidence_multiplier=Decimal(str(payload["confidence_multiplier"])),
        stability_multiplier=Decimal(str(payload["stability_multiplier"])),
        uniqueness_multiplier=Decimal(str(payload["uniqueness_multiplier"])),
        decision=ComponentDecisionState(str(payload["decision"])),
        primary_reason=str(payload["primary_reason"]),
        supporting_metrics=tuple(
            str(item) for item in _list(payload.get("supporting_metrics"), "metrics")
        ),
        blocking_reasons=tuple(
            str(item) for item in _list(payload.get("blocking_reasons"), "blockers")
        ),
    )


def _conditional(raw: object) -> ConditionalWeightSet:
    payload = _object(raw, "conditional weights")
    return ConditionalWeightSet(
        setup=_optional_text(payload.get("setup")),
        regime=_optional_text(payload.get("regime")),
        horizon=_optional_text(payload.get("horizon")),
        sample_size=int(payload["sample_size"]),
        weights=_weight_set(payload["weights"]),
        evidence_quality=EvidenceQuality(str(payload["evidence_quality"])),
    )


def _policy_from_dict(raw: dict[str, Any]) -> CandidateWeightPolicy:
    return CandidateWeightPolicy(
        policy_id=str(raw["policy_id"]),
        parent_policy=str(raw["parent_policy"]),
        canonical_weights=_weight_set(raw["canonical_weights"]),
        proposed_weights=_weight_set(raw["proposed_weights"]),
        conditional_weights=tuple(
            _conditional(item)
            for item in _list(raw.get("conditional_weights"), "conditionals")
        ),
        evidence_window=str(raw["evidence_window"]),
        dataset_version=str(raw["dataset_version"]),
        outcome_count=int(raw["outcome_count"]),
        method_version=str(raw["method_version"]),
        guardrails=_guardrails(raw["guardrails"]),
        quality_state=EvidenceQuality(str(raw["quality_state"])),
        validation_status=str(raw["validation_status"]),
        holdout_status=str(raw["holdout_status"]),
        forward_status=str(raw["forward_status"]),
        state=CandidatePolicyState(str(raw["state"])),
        created_at=datetime.fromisoformat(str(raw["created_at"])),
        manifest_hash=str(raw["manifest_hash"]),
        component_decisions=tuple(
            _decision(item)
            for item in _list(raw.get("component_decisions"), "decisions")
        ),
        production_influence=bool(raw.get("production_influence", False)),
    )


def _object(raw: object, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object")
    return raw


def _list(raw: object, label: str) -> list[object]:
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list")
    return raw


def _optional_text(raw: object) -> str | None:
    text = "" if raw is None else str(raw).strip()
    return text or None


__all__ = ["CandidateWeightPolicyFactory", "CandidateWeightPolicyRegistry"]
