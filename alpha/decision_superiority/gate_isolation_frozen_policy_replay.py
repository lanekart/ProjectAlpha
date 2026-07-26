"""Frozen policy replay and evaluator reconstruction for DSI-002B."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FROZEN_INPUT_CONTRACT_VERSION,
    FrozenInputSection,
)


class FrozenReplayReadiness(StrEnum):
    """Governed replay readiness for one persisted snapshot."""

    READY = "READY_FOR_FROZEN_EVALUATOR_REPLAY"
    TAMPERED = "BLOCKED_BY_SNAPSHOT_TAMPER"
    INCOMPLETE = "BLOCKED_BY_INCOMPLETE_SNAPSHOT"
    UNSUPPORTED_POLICY = "BLOCKED_BY_UNSUPPORTED_POLICY_VERSION"
    INVALID_IDENTITY = "BLOCKED_BY_INVALID_CANDIDATE_IDENTITY"


@dataclass(frozen=True, slots=True)
class FrozenEvaluatorConfig:
    """Reconstructed evaluator configuration from one frozen section."""

    section: FrozenInputSection
    source_version: str
    policy_version: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class FrozenReplayBundle:
    """Tamper-verified snapshot plus reconstructed evaluator configs."""

    snapshot_path: Path
    snapshot_sha256: str
    candidate_identity: str
    evaluators: tuple[FrozenEvaluatorConfig, ...]
    readiness: FrozenReplayReadiness
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("frozen replay must remain diagnostic-only")
        if tuple(sorted(self.evaluators, key=lambda item: item.section.value)) != (
            self.evaluators
        ):
            raise ValueError("evaluators must be deterministically sorted")


class FrozenPolicyRegistry:
    """Allow only explicitly governed frozen producer versions."""

    def __init__(self, supported_versions: dict[FrozenInputSection, str]) -> None:
        self._supported_versions = dict(supported_versions)

    @classmethod
    def dsi002a_v1(cls) -> FrozenPolicyRegistry:
        """Return the supported DSI-002A producer-version registry."""

        return cls(
            {
                FrozenInputSection.APPROVAL_POLICY: ("DSI-002A-approval-policy-v1"),
                FrozenInputSection.CANDIDATE_FEATURES: (
                    "DSI-002A-candidate-features-v1"
                ),
                FrozenInputSection.ENTRY_POLICY: "DSI-002A-entry-policy-v1",
                FrozenInputSection.EXECUTION_STATE: ("DSI-002A-execution-state-v1"),
                FrozenInputSection.OUTCOME_POLICY: ("DSI-002A-outcome-policy-v1"),
                FrozenInputSection.PORTFOLIO_STATE: ("DSI-002A-portfolio-state-v1"),
                FrozenInputSection.SOURCE_LINEAGE: ("DSI-002A-source-lineage-v1"),
            }
        )

    def supports(self, section: FrozenInputSection, source_version: str) -> bool:
        """Return whether one producer version is governed and supported."""

        return self._supported_versions.get(section) == source_version


class FrozenPolicyReplayLoader:
    """Load, verify, and reconstruct one persisted frozen-input snapshot."""

    def __init__(self, registry: FrozenPolicyRegistry | None = None) -> None:
        self._registry = registry or FrozenPolicyRegistry.dsi002a_v1()

    def load(self, snapshot_path: Path) -> FrozenReplayBundle:
        """Return a fail-closed replay bundle for one persisted snapshot."""

        raw = snapshot_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("snapshot payload must be a JSON object")
        if payload.get("contract_version") != FROZEN_INPUT_CONTRACT_VERSION:
            return _blocked_bundle(
                snapshot_path,
                payload,
                FrozenReplayReadiness.TAMPERED,
            )
        candidate = payload.get("candidate")
        if not isinstance(candidate, dict):
            return _blocked_bundle(
                snapshot_path,
                payload,
                FrozenReplayReadiness.INVALID_IDENTITY,
            )
        candidate_identity = _candidate_identity(candidate)
        if candidate_identity is None:
            return _blocked_bundle(
                snapshot_path,
                payload,
                FrozenReplayReadiness.INVALID_IDENTITY,
            )
        sections = payload.get("sections")
        if not isinstance(sections, list):
            return _blocked_bundle(
                snapshot_path,
                payload,
                FrozenReplayReadiness.INCOMPLETE,
            )
        if len(sections) != len(FrozenInputSection):
            return _blocked_bundle(
                snapshot_path,
                payload,
                FrozenReplayReadiness.INCOMPLETE,
            )
        evaluators: list[FrozenEvaluatorConfig] = []
        seen: set[FrozenInputSection] = set()
        for raw_section in sections:
            if not isinstance(raw_section, dict):
                return _blocked_bundle(
                    snapshot_path,
                    payload,
                    FrozenReplayReadiness.TAMPERED,
                )
            reconstructed = self._reconstruct(raw_section)
            if reconstructed is None:
                return _blocked_bundle(
                    snapshot_path,
                    payload,
                    FrozenReplayReadiness.UNSUPPORTED_POLICY,
                )
            if reconstructed.section in seen:
                return _blocked_bundle(
                    snapshot_path,
                    payload,
                    FrozenReplayReadiness.TAMPERED,
                )
            seen.add(reconstructed.section)
            evaluators.append(reconstructed)
        if seen != set(FrozenInputSection):
            return _blocked_bundle(
                snapshot_path,
                payload,
                FrozenReplayReadiness.INCOMPLETE,
            )
        stored_sha = payload.get("snapshot_sha256")
        if not isinstance(stored_sha, str) or not stored_sha.strip():
            return _blocked_bundle(
                snapshot_path,
                payload,
                FrozenReplayReadiness.TAMPERED,
            )
        computed_sha = _snapshot_sha256(payload)
        if stored_sha != computed_sha:
            return _blocked_bundle(
                snapshot_path,
                payload,
                FrozenReplayReadiness.TAMPERED,
            )
        return FrozenReplayBundle(
            snapshot_path=snapshot_path,
            snapshot_sha256=stored_sha,
            candidate_identity=candidate_identity,
            evaluators=tuple(sorted(evaluators, key=lambda item: item.section.value)),
            readiness=FrozenReplayReadiness.READY,
        )

    def _reconstruct(
        self,
        raw_section: dict[str, object],
    ) -> FrozenEvaluatorConfig | None:
        section_text = raw_section.get("section")
        source_version = raw_section.get("source_version")
        payload_json = raw_section.get("payload_json")
        payload_sha256 = raw_section.get("payload_sha256")
        if not all(
            isinstance(value, str)
            for value in (
                section_text,
                source_version,
                payload_json,
                payload_sha256,
            )
        ):
            return None
        try:
            section = FrozenInputSection(str(section_text))
        except ValueError:
            return None
        if not self._registry.supports(section, str(source_version)):
            return None
        if _sha256(str(payload_json)) != str(payload_sha256):
            return None
        decoded = json.loads(str(payload_json))
        if not isinstance(decoded, dict):
            return None
        policy_version = decoded.get(
            "policy_version",
            decoded.get("state_version", decoded.get("feature_version", "")),
        )
        if not isinstance(policy_version, str):
            policy_version = ""
        return FrozenEvaluatorConfig(
            section=section,
            source_version=str(source_version),
            policy_version=policy_version,
            payload=decoded,
        )


def _blocked_bundle(
    snapshot_path: Path,
    payload: dict[str, object],
    readiness: FrozenReplayReadiness,
) -> FrozenReplayBundle:
    stored_sha = payload.get("snapshot_sha256")
    candidate = payload.get("candidate")
    identity = "UNKNOWN"
    if isinstance(candidate, dict):
        parsed = _candidate_identity(candidate)
        if parsed is not None:
            identity = parsed
    return FrozenReplayBundle(
        snapshot_path=snapshot_path,
        snapshot_sha256=stored_sha if isinstance(stored_sha, str) else "UNKNOWN",
        candidate_identity=identity,
        evaluators=(),
        readiness=readiness,
    )


def _candidate_identity(candidate: dict[str, object]) -> str | None:
    fields = (
        candidate.get("price_view"),
        candidate.get("observed_on"),
        candidate.get("symbol"),
        candidate.get("input_fingerprint"),
    )
    if not all(isinstance(value, str) and value.strip() for value in fields):
        return None
    return "|".join(str(value) for value in fields)


def _snapshot_sha256(payload: dict[str, object]) -> str:
    candidate = payload["candidate"]
    sections = payload["sections"]
    if not isinstance(candidate, dict) or not isinstance(sections, list):
        return ""
    digest_payload = {
        "candidate": {
            "price_view": candidate.get("price_view"),
            "observed_on": candidate.get("observed_on"),
            "symbol": candidate.get("symbol"),
            "input_fingerprint": candidate.get("input_fingerprint"),
        },
        "contract_version": payload.get("contract_version"),
        "sections": [
            {
                "section": item.get("section"),
                "payload_sha256": item.get("payload_sha256"),
                "source_version": item.get("source_version"),
                "observed_on": item.get("observed_on"),
                "contains_post_observation_data": item.get(
                    "contains_post_observation_data"
                ),
            }
            for item in sections
            if isinstance(item, dict)
        ],
    }
    encoded = json.dumps(
        digest_payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(encoded)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "FrozenEvaluatorConfig",
    "FrozenPolicyRegistry",
    "FrozenPolicyReplayLoader",
    "FrozenReplayBundle",
    "FrozenReplayReadiness",
]
