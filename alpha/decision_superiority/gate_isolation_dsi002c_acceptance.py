"""Executable acceptance boundary for DSI-002C recorded decision parity."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import DemoIntelligenceInputBuilder
from alpha.decision_superiority.gate_isolation_decision_baseline import (
    DecisionReplayParityResult,
    RecordedDecisionBaselineEnvelope,
    RecordedDecisionBaselineStore,
    compare_run_to_baseline,
)
from alpha.decision_superiority.gate_isolation_frozen_policy_replay import (
    FrozenPolicyReplayLoader,
    FrozenReplayReadiness,
)


@dataclass(frozen=True, slots=True)
class DSI002CAcceptanceResult:
    """Governed acceptance result for recorded decision replay parity."""

    parity: DecisionReplayParityResult
    baseline_path: Path
    baseline_tamper_block_verified: bool
    candidate_identity_block_verified: bool
    snapshot_identity_block_verified: bool
    deterministic_replay_verified: bool
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("DSI-002C acceptance must remain diagnostic-only")

    @property
    def accepted(self) -> bool:
        """Return whether every governed acceptance condition passed."""

        return all(
            (
                self.parity.parity_verified,
                self.baseline_tamper_block_verified,
                self.candidate_identity_block_verified,
                self.snapshot_identity_block_verified,
                self.deterministic_replay_verified,
                not self.production_influence,
            )
        )


def run_dsi002c_acceptance(
    *,
    snapshot_path: Path,
    output: Path,
) -> DSI002CAcceptanceResult:
    """Capture a baseline envelope and prove deterministic replay parity."""

    replay = FrozenPolicyReplayLoader().load(snapshot_path)
    if replay.readiness is not FrozenReplayReadiness.READY:
        raise ValueError("DSI-002C requires a replay-ready frozen snapshot")
    observed_on = _candidate_date(replay.candidate_identity)
    baseline_run = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=observed_on)
    baseline = RecordedDecisionBaselineEnvelope.from_run(
        run=baseline_run,
        candidate_identity=replay.candidate_identity,
        snapshot_sha256=replay.snapshot_sha256,
    )
    store = RecordedDecisionBaselineStore(output / "baseline")
    baseline_path = store.write(baseline)
    loaded = store.load(baseline_path)
    replay_run = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=observed_on)
    parity = compare_run_to_baseline(
        run=replay_run,
        baseline=loaded,
        candidate_identity=replay.candidate_identity,
        snapshot_sha256=replay.snapshot_sha256,
    )
    second_run = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=observed_on)
    deterministic = replay_run.as_dict() == second_run.as_dict()
    tamper_block = _baseline_tamper_block_verified(store, baseline_path, output)
    candidate_block = not compare_run_to_baseline(
        run=replay_run,
        baseline=loaded,
        candidate_identity="MISMATCH",
        snapshot_sha256=replay.snapshot_sha256,
    ).parity_verified
    snapshot_block = not compare_run_to_baseline(
        run=replay_run,
        baseline=loaded,
        candidate_identity=replay.candidate_identity,
        snapshot_sha256="MISMATCH",
    ).parity_verified
    result = DSI002CAcceptanceResult(
        parity=parity,
        baseline_path=baseline_path,
        baseline_tamper_block_verified=tamper_block,
        candidate_identity_block_verified=candidate_block,
        snapshot_identity_block_verified=snapshot_block,
        deterministic_replay_verified=deterministic,
    )
    export_dsi002c_acceptance(result, output)
    return result


def export_dsi002c_acceptance(
    result: DSI002CAcceptanceResult,
    output: Path,
) -> tuple[Path, Path]:
    """Export deterministic DSI-002C certificate and parity summary."""

    output.mkdir(parents=True, exist_ok=True)
    certificate = output / "dsi002c_recorded_decision_parity_certificate.json"
    summary = output / "dsi002c_recorded_decision_parity_acceptance.csv"
    payload = {
        "accepted": result.accepted,
        "baseline_output_sha256": result.parity.baseline_output_sha256,
        "baseline_tamper_block_verified": (
            result.baseline_tamper_block_verified
        ),
        "candidate_identity_block_verified": (
            result.candidate_identity_block_verified
        ),
        "deterministic_replay_verified": result.deterministic_replay_verified,
        "exact_payload_match": result.parity.exact_payload_match,
        "parity_verified": result.parity.parity_verified,
        "production_influence": result.production_influence,
        "replay_output_sha256": result.parity.replay_output_sha256,
        "snapshot_identity_block_verified": (
            result.snapshot_identity_block_verified
        ),
    }
    certificate.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    with summary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(payload))
        writer.writeheader()
        writer.writerow(payload)
    return certificate, summary


def _candidate_date(candidate_identity: str) -> date:
    parts = candidate_identity.split("|")
    if len(parts) != 4:
        raise ValueError("candidate identity must contain four fields")
    return date.fromisoformat(parts[1])


def _baseline_tamper_block_verified(
    store: RecordedDecisionBaselineStore,
    baseline_path: Path,
    output: Path,
) -> bool:
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return False
    payload["output_sha256"] = "0" * 64
    tampered = output / "_tampered_baseline.json"
    tampered.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        store.load(tampered)
    except ValueError:
        tampered.unlink()
        return True
    tampered.unlink()
    return False


__all__ = [
    "DSI002CAcceptanceResult",
    "export_dsi002c_acceptance",
    "run_dsi002c_acceptance",
]
