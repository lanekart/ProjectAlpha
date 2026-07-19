from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from alpha.forward_validation.models import (
    CURRENT_POLICY_VERSION,
    CounterfactualPolicy,
    PolicyStage,
    PolicyVersion,
)

DEFAULT_POLICY_REGISTRY_PATH = Path(".alpha/forward_validation/policies.json")


class PolicyVersionRegistry:
    """Immutable registry of offline policy candidates and stage transitions."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_POLICY_REGISTRY_PATH

    def current(self) -> PolicyVersion:
        return PolicyVersion(CURRENT_POLICY_VERSION)

    def next_version(self) -> PolicyVersion:
        versions = [self.current(), *self.versions()]
        return PolicyVersion(f"APPROVAL_POLICY_V{max(v.number for v in versions) + 1}")

    def versions(self) -> tuple[PolicyVersion, ...]:
        policies = self._read().get("policies", [])
        if not isinstance(policies, list):
            return ()
        return tuple(
            sorted(
                {
                    PolicyVersion(str(item["policy_version"]))
                    for item in policies
                    if isinstance(item, dict) and item.get("policy_version")
                },
                key=lambda item: item.number,
            )
        )

    def entries(self) -> tuple[dict[str, str], ...]:
        policies = self._read().get("policies", [])
        if not isinstance(policies, list):
            return ()
        return tuple(
            {
                str(key): str(value)
                for key, value in item.items()
                if not isinstance(value, (dict, list))
            }
            for item in policies
            if isinstance(item, dict)
        )

    def register(self, candidate: CounterfactualPolicy) -> bool:
        payload = self._read()
        policies = payload.setdefault("policies", [])
        if not isinstance(policies, list):
            raise ValueError("policy registry policies must be a list")
        row = {
            "policy_version": candidate.policy_version.value,
            "operation": candidate.operation.value,
            "changed_gate_ids": list(candidate.changed_gate_ids),
            "description": candidate.description,
            "parameters": dict(candidate.parameters),
            "stage": candidate.stage.value,
            "production_influence": False,
            "registered_at": datetime.now(tz=UTC).isoformat(),
        }
        existing = next(
            (
                item
                for item in policies
                if isinstance(item, dict)
                and item.get("policy_version") == candidate.policy_version.value
            ),
            None,
        )
        if existing is not None:
            comparable_existing = dict(existing)
            comparable_existing.pop("registered_at", None)
            comparable_existing.pop("stage", None)
            comparable_row = dict(row)
            comparable_row.pop("registered_at", None)
            comparable_row.pop("stage", None)
            if comparable_existing != comparable_row:
                raise ValueError("immutable policy version conflict")
            return False
        policies.append(row)
        self._write(payload)
        return True

    def promote(self, version: PolicyVersion, stage: PolicyStage) -> None:
        if stage in {PolicyStage.CURRENT, PolicyStage.CANDIDATE_FOR_DEPLOYMENT}:
            raise ValueError(
                "diagnostic policy registry cannot activate or deploy a policy"
            )
        payload = self._read()
        policies = payload.get("policies", [])
        if not isinstance(policies, list):
            raise ValueError("policy registry policies must be a list")
        for item in policies:
            if isinstance(item, dict) and item.get("policy_version") == version.value:
                prior = PolicyStage(str(item["stage"]))
                if _stage_rank(stage) < _stage_rank(prior):
                    raise ValueError("policy stage cannot move backwards")
                item["stage"] = stage.value
                self._write(payload)
                return
        raise KeyError(version.value)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "current_policy": CURRENT_POLICY_VERSION,
                "production_influence": False,
                "policies": [],
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("policy registry must be an object")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        payload["current_policy"] = CURRENT_POLICY_VERSION
        payload["production_influence"] = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


def _stage_rank(stage: PolicyStage) -> int:
    order = {
        PolicyStage.GENERATED: 0,
        PolicyStage.TRAINING_PASSED: 1,
        PolicyStage.VALIDATION_PASSED: 2,
        PolicyStage.HOLDOUT_PASSED: 3,
        PolicyStage.FORWARD_VALIDATION: 4,
        PolicyStage.REJECTED: 5,
        PolicyStage.CURRENT: 6,
        PolicyStage.CANDIDATE_FOR_DEPLOYMENT: 7,
    }
    return order[stage]


__all__ = ["DEFAULT_POLICY_REGISTRY_PATH", "PolicyVersionRegistry"]
