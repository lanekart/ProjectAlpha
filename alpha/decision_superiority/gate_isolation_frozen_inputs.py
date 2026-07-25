"""Governed frozen-input preservation contract for DSI-002 replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey

FROZEN_INPUT_CONTRACT_VERSION = "DSI-002A-v1.0.0"


class FrozenInputSection(StrEnum):
    """Required point-in-time input sections for deterministic replay."""

    CANDIDATE_FEATURES = "CANDIDATE_FEATURES"
    APPROVAL_POLICY = "APPROVAL_POLICY"
    PORTFOLIO_STATE = "PORTFOLIO_STATE"
    ENTRY_POLICY = "ENTRY_POLICY"
    EXECUTION_STATE = "EXECUTION_STATE"
    OUTCOME_POLICY = "OUTCOME_POLICY"
    SOURCE_LINEAGE = "SOURCE_LINEAGE"


class FrozenInputReadiness(StrEnum):
    """Fail-closed readiness state for one frozen-input snapshot."""

    READY = "READY_FOR_FROZEN_POLICY_REPLAY"
    INCOMPLETE = "BLOCKED_BY_INCOMPLETE_FROZEN_INPUTS"
    HASH_MISMATCH = "BLOCKED_BY_FROZEN_INPUT_HASH_MISMATCH"
    IDENTITY_MISMATCH = "BLOCKED_BY_FROZEN_INPUT_IDENTITY_MISMATCH"
    POST_OBSERVATION_INPUT = "BLOCKED_BY_POST_OBSERVATION_INPUT"


@dataclass(frozen=True, slots=True)
class FrozenInputSectionSnapshot:
    """Canonical payload and lineage for one frozen input section."""

    section: FrozenInputSection
    payload_json: str
    payload_sha256: str
    source_version: str
    observed_on: str
    contains_post_observation_data: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("payload_json", self.payload_json),
            ("payload_sha256", self.payload_sha256),
            ("source_version", self.source_version),
            ("observed_on", self.observed_on),
        ):
            if not value.strip():
                raise ValueError(f"{name} cannot be empty")
        try:
            parsed = json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("payload_json must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("payload_json must encode a JSON object")
        if _sha256(self.payload_json) != self.payload_sha256:
            raise ValueError("payload_sha256 does not match payload_json")

    @classmethod
    def from_mapping(
        cls,
        *,
        section: FrozenInputSection,
        payload: Mapping[str, object],
        source_version: str,
        observed_on: str,
        contains_post_observation_data: bool = False,
    ) -> FrozenInputSectionSnapshot:
        """Create a canonical section snapshot from a mapping."""

        payload_json = _canonical_json(payload)
        return cls(
            section=section,
            payload_json=payload_json,
            payload_sha256=_sha256(payload_json),
            source_version=source_version,
            observed_on=observed_on,
            contains_post_observation_data=contains_post_observation_data,
        )


@dataclass(frozen=True, slots=True)
class FrozenCandidateInputSnapshot:
    """Complete candidate input bundle for frozen policy replay."""

    candidate: FrozenCandidateKey
    contract_version: str
    sections: tuple[FrozenInputSectionSnapshot, ...]
    snapshot_sha256: str
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("frozen input snapshots must remain diagnostic-only")
        if self.contract_version != FROZEN_INPUT_CONTRACT_VERSION:
            raise ValueError("unsupported frozen input contract version")
        ordered = tuple(sorted(self.sections, key=lambda item: item.section.value))
        if ordered != self.sections:
            raise ValueError("sections must be deterministically sorted")
        if len({item.section for item in self.sections}) != len(self.sections):
            raise ValueError("sections must be unique")
        expected = _snapshot_sha256(
            candidate=self.candidate,
            contract_version=self.contract_version,
            sections=self.sections,
        )
        if expected != self.snapshot_sha256:
            raise ValueError("snapshot_sha256 does not match snapshot contents")

    @classmethod
    def build(
        cls,
        *,
        candidate: FrozenCandidateKey,
        sections: tuple[FrozenInputSectionSnapshot, ...],
    ) -> FrozenCandidateInputSnapshot:
        """Build a deterministic complete snapshot candidate bundle."""

        ordered = tuple(sorted(sections, key=lambda item: item.section.value))
        return cls(
            candidate=candidate,
            contract_version=FROZEN_INPUT_CONTRACT_VERSION,
            sections=ordered,
            snapshot_sha256=_snapshot_sha256(
                candidate=candidate,
                contract_version=FROZEN_INPUT_CONTRACT_VERSION,
                sections=ordered,
            ),
        )


@dataclass(frozen=True, slots=True)
class FrozenInputValidationResult:
    """Validation result for one candidate frozen-input bundle."""

    readiness: FrozenInputReadiness
    missing_sections: tuple[FrozenInputSection, ...]
    invalid_sections: tuple[FrozenInputSection, ...]
    replay_ready: bool


class FrozenInputContractValidator:
    """Validate completeness, timing, identity, and deterministic hashes."""

    def validate(
        self,
        snapshot: FrozenCandidateInputSnapshot,
    ) -> FrozenInputValidationResult:
        required = set(FrozenInputSection)
        observed = {item.section for item in snapshot.sections}
        missing = tuple(sorted(required - observed, key=lambda item: item.value))
        post_observation = tuple(
            item.section
            for item in snapshot.sections
            if item.contains_post_observation_data
            or item.observed_on > snapshot.candidate.observed_on
        )
        if post_observation:
            return FrozenInputValidationResult(
                readiness=FrozenInputReadiness.POST_OBSERVATION_INPUT,
                missing_sections=missing,
                invalid_sections=tuple(sorted(post_observation)),
                replay_ready=False,
            )
        if missing:
            return FrozenInputValidationResult(
                readiness=FrozenInputReadiness.INCOMPLETE,
                missing_sections=missing,
                invalid_sections=(),
                replay_ready=False,
            )
        return FrozenInputValidationResult(
            readiness=FrozenInputReadiness.READY,
            missing_sections=(),
            invalid_sections=(),
            replay_ready=True,
        )


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _snapshot_sha256(
    *,
    candidate: FrozenCandidateKey,
    contract_version: str,
    sections: tuple[FrozenInputSectionSnapshot, ...],
) -> str:
    payload = {
        "candidate": {
            "price_view": candidate.price_view,
            "observed_on": candidate.observed_on,
            "symbol": candidate.symbol,
            "input_fingerprint": candidate.input_fingerprint,
        },
        "contract_version": contract_version,
        "sections": [
            {
                "section": item.section.value,
                "payload_sha256": item.payload_sha256,
                "source_version": item.source_version,
                "observed_on": item.observed_on,
                "contains_post_observation_data": (item.contains_post_observation_data),
            }
            for item in sections
        ],
    }
    return _sha256(_canonical_json(payload))


__all__ = [
    "FROZEN_INPUT_CONTRACT_VERSION",
    "FrozenCandidateInputSnapshot",
    "FrozenInputContractValidator",
    "FrozenInputReadiness",
    "FrozenInputSection",
    "FrozenInputSectionSnapshot",
    "FrozenInputValidationResult",
]
