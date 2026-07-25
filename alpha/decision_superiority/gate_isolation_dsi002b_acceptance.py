"""Executable acceptance boundary for DSI-002B frozen policy replay."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from alpha.decision_superiority.gate_isolation_frozen_policy_replay import (
    FrozenPolicyReplayLoader,
    FrozenReplayBundle,
    FrozenReplayReadiness,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputSection,
)


@dataclass(frozen=True, slots=True)
class DSI002BAcceptanceResult:
    """Governed acceptance result for frozen evaluator reconstruction."""

    replay: FrozenReplayBundle
    tamper_block_verified: bool
    incomplete_block_verified: bool
    unsupported_policy_block_verified: bool
    evaluator_lineage_verified: bool
    deterministic_reconstruction_verified: bool
    point_in_time_verified: bool
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("DSI-002B acceptance must remain diagnostic-only")

    @property
    def accepted(self) -> bool:
        """Return whether all governed acceptance conditions passed."""

        return all(
            (
                self.replay.readiness is FrozenReplayReadiness.READY,
                self.tamper_block_verified,
                self.incomplete_block_verified,
                self.unsupported_policy_block_verified,
                self.evaluator_lineage_verified,
                self.deterministic_reconstruction_verified,
                self.point_in_time_verified,
                not self.production_influence,
            )
        )


def run_dsi002b_acceptance(
    *,
    snapshot_path: Path,
    output: Path,
) -> DSI002BAcceptanceResult:
    """Run deterministic replay reconstruction and fail-closed checks."""

    loader = FrozenPolicyReplayLoader()
    replay = loader.load(snapshot_path)
    second = loader.load(snapshot_path)
    deterministic = replay == second
    evaluator_lineage = (
        replay.readiness is FrozenReplayReadiness.READY
        and len(replay.evaluators) == len(FrozenInputSection)
        and all(item.source_version.strip() for item in replay.evaluators)
    )
    point_in_time = _point_in_time_verified(snapshot_path)
    tamper_block = _tamper_block_verified(snapshot_path, output)
    incomplete_block = _incomplete_block_verified(snapshot_path, output)
    unsupported_block = _unsupported_policy_block_verified(snapshot_path)
    result = DSI002BAcceptanceResult(
        replay=replay,
        tamper_block_verified=tamper_block,
        incomplete_block_verified=incomplete_block,
        unsupported_policy_block_verified=unsupported_block,
        evaluator_lineage_verified=evaluator_lineage,
        deterministic_reconstruction_verified=deterministic,
        point_in_time_verified=point_in_time,
    )
    export_dsi002b_acceptance(result, output)
    return result


def export_dsi002b_acceptance(
    result: DSI002BAcceptanceResult,
    output: Path,
) -> tuple[Path, Path, Path]:
    """Export certificate, evaluator lineage, and summary artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    certificate = output / "dsi002b_frozen_policy_replay_certificate.json"
    lineage = output / "dsi002b_evaluator_lineage.csv"
    summary = output / "dsi002b_frozen_policy_replay_acceptance.csv"
    payload = {
        "accepted": result.accepted,
        "candidate_identity": result.replay.candidate_identity,
        "deterministic_reconstruction_verified": (
            result.deterministic_reconstruction_verified
        ),
        "evaluator_count": len(result.replay.evaluators),
        "evaluator_lineage_verified": result.evaluator_lineage_verified,
        "incomplete_block_verified": result.incomplete_block_verified,
        "point_in_time_verified": result.point_in_time_verified,
        "production_influence": result.production_influence,
        "readiness": result.replay.readiness.value,
        "snapshot_sha256": result.replay.snapshot_sha256,
        "tamper_block_verified": result.tamper_block_verified,
        "unsupported_policy_block_verified": (
            result.unsupported_policy_block_verified
        ),
    }
    certificate.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    with lineage.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "section",
                "source_version",
                "policy_version",
                "snapshot_sha256",
                "production_influence",
            ),
        )
        writer.writeheader()
        for evaluator in result.replay.evaluators:
            writer.writerow(
                {
                    "section": evaluator.section.value,
                    "source_version": evaluator.source_version,
                    "policy_version": evaluator.policy_version,
                    "snapshot_sha256": result.replay.snapshot_sha256,
                    "production_influence": False,
                }
            )
    with summary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(payload))
        writer.writeheader()
        writer.writerow(payload)
    return certificate, lineage, summary


def _point_in_time_verified(snapshot_path: Path) -> bool:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    candidate = payload.get("candidate")
    sections = payload.get("sections")
    if not isinstance(candidate, dict) or not isinstance(sections, list):
        return False
    observed_on = candidate.get("observed_on")
    if not isinstance(observed_on, str):
        return False
    return all(
        isinstance(section, dict)
        and section.get("observed_on") <= observed_on
        and section.get("contains_post_observation_data") is False
        for section in sections
    )


def _tamper_block_verified(snapshot_path: Path, output: Path) -> bool:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        return False
    candidate["symbol"] = "TAMPERED"
    tampered = output / "_tampered_snapshot.json"
    tampered.parent.mkdir(parents=True, exist_ok=True)
    tampered.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readiness = FrozenPolicyReplayLoader().load(tampered).readiness
    tampered.unlink()
    return readiness is FrozenReplayReadiness.TAMPERED


def _incomplete_block_verified(snapshot_path: Path, output: Path) -> bool:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    sections = payload.get("sections")
    if not isinstance(sections, list):
        return False
    payload["sections"] = sections[:-1]
    incomplete = output / "_incomplete_snapshot.json"
    incomplete.parent.mkdir(parents=True, exist_ok=True)
    incomplete.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readiness = FrozenPolicyReplayLoader().load(incomplete).readiness
    incomplete.unlink()
    return readiness is FrozenReplayReadiness.INCOMPLETE


def _unsupported_policy_block_verified(snapshot_path: Path) -> bool:
    from alpha.decision_superiority.gate_isolation_frozen_policy_replay import (
        FrozenPolicyRegistry,
    )

    registry = FrozenPolicyRegistry(
        {section: "unsupported" for section in FrozenInputSection}
    )
    readiness = FrozenPolicyReplayLoader(registry).load(snapshot_path).readiness
    return readiness is FrozenReplayReadiness.UNSUPPORTED_POLICY


__all__ = [
    "DSI002BAcceptanceResult",
    "export_dsi002b_acceptance",
    "run_dsi002b_acceptance",
]
