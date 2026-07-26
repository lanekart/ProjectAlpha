"""Recorded decision baseline envelope for DSI-002C replay parity."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from alpha.application.intelligence import IntelligenceRun

BASELINE_ENVELOPE_VERSION = "DSI-002C-v1.0.0"


@dataclass(frozen=True, slots=True)
class RecordedDecisionBaselineEnvelope:
    """Immutable decision outputs linked to one frozen-input snapshot."""

    candidate_identity: str
    snapshot_sha256: str
    observed_on: str
    output_payload_json: str
    output_sha256: str
    envelope_version: str = BASELINE_ENVELOPE_VERSION
    production_influence: bool = False

    def __post_init__(self) -> None:
        required = (
            self.candidate_identity,
            self.snapshot_sha256,
            self.observed_on,
            self.output_payload_json,
            self.output_sha256,
        )
        if any(not value.strip() for value in required):
            raise ValueError("baseline envelope fields cannot be empty")
        if self.envelope_version != BASELINE_ENVELOPE_VERSION:
            raise ValueError("unsupported baseline envelope version")
        if self.production_influence:
            raise ValueError("baseline envelope must remain diagnostic-only")
        payload = json.loads(self.output_payload_json)
        if not isinstance(payload, dict):
            raise ValueError("output payload must encode a JSON object")
        if _sha256(self.output_payload_json) != self.output_sha256:
            raise ValueError("output_sha256 does not match output payload")

    @classmethod
    def from_run(
        cls,
        *,
        run: IntelligenceRun,
        candidate_identity: str,
        snapshot_sha256: str,
    ) -> RecordedDecisionBaselineEnvelope:
        """Create a deterministic envelope from one completed intelligence run."""

        payload_json = _canonical_json(run.as_dict())
        return cls(
            candidate_identity=candidate_identity,
            snapshot_sha256=snapshot_sha256,
            observed_on=run.observed_on.isoformat(),
            output_payload_json=payload_json,
            output_sha256=_sha256(payload_json),
        )


class RecordedDecisionBaselineStore:
    """Append-only persistence and verified loading for baseline envelopes."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def write(
        self,
        envelope: RecordedDecisionBaselineEnvelope,
    ) -> Path:
        """Persist one immutable envelope without overwrite."""

        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / "dsi002c_recorded_decision_baseline.json"
        if path.exists():
            raise FileExistsError(f"baseline envelope already exists:{path}")
        payload = {
            "candidate_identity": envelope.candidate_identity,
            "envelope_version": envelope.envelope_version,
            "observed_on": envelope.observed_on,
            "output_payload_json": envelope.output_payload_json,
            "output_sha256": envelope.output_sha256,
            "production_influence": envelope.production_influence,
            "snapshot_sha256": envelope.snapshot_sha256,
        }
        path.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def load(self, path: Path) -> RecordedDecisionBaselineEnvelope:
        """Load and verify one recorded decision baseline."""

        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("baseline envelope must encode a JSON object")
        return RecordedDecisionBaselineEnvelope(
            candidate_identity=_required_text(payload, "candidate_identity"),
            snapshot_sha256=_required_text(payload, "snapshot_sha256"),
            observed_on=_required_text(payload, "observed_on"),
            output_payload_json=_required_text(payload, "output_payload_json"),
            output_sha256=_required_text(payload, "output_sha256"),
            envelope_version=_required_text(payload, "envelope_version"),
            production_influence=bool(payload.get("production_influence", False)),
        )


@dataclass(frozen=True, slots=True)
class DecisionReplayParityResult:
    """Exact output parity result against a recorded baseline envelope."""

    baseline_output_sha256: str
    replay_output_sha256: str
    exact_payload_match: bool
    candidate_identity_match: bool
    snapshot_identity_match: bool
    production_influence: bool = False

    @property
    def parity_verified(self) -> bool:
        """Return whether every governed parity condition passed."""

        return all(
            (
                self.exact_payload_match,
                self.candidate_identity_match,
                self.snapshot_identity_match,
                not self.production_influence,
            )
        )


def compare_run_to_baseline(
    *,
    run: IntelligenceRun,
    baseline: RecordedDecisionBaselineEnvelope,
    candidate_identity: str,
    snapshot_sha256: str,
) -> DecisionReplayParityResult:
    """Compare a deterministic replay run against its recorded envelope."""

    payload_json = _canonical_json(run.as_dict())
    replay_hash = _sha256(payload_json)
    return DecisionReplayParityResult(
        baseline_output_sha256=baseline.output_sha256,
        replay_output_sha256=replay_hash,
        exact_payload_match=(
            payload_json == baseline.output_payload_json
            and replay_hash == baseline.output_sha256
        ),
        candidate_identity_match=(candidate_identity == baseline.candidate_identity),
        snapshot_identity_match=(snapshot_sha256 == baseline.snapshot_sha256),
    )


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_text(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


__all__ = [
    "BASELINE_ENVELOPE_VERSION",
    "DecisionReplayParityResult",
    "RecordedDecisionBaselineEnvelope",
    "RecordedDecisionBaselineStore",
    "compare_run_to_baseline",
]
