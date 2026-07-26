from __future__ import annotations

import json
from pathlib import Path

from alpha.decision_superiority.gate_isolation_dsi002a_acceptance import (
    run_dsi002a_acceptance,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputSection,
)
from alpha.decision_superiority.gate_isolation_frozen_policy_replay import (
    FrozenPolicyRegistry,
    FrozenPolicyReplayLoader,
    FrozenReplayReadiness,
)


def _accepted_snapshot(tmp_path: Path) -> Path:
    result = run_dsi002a_acceptance(tmp_path)
    assert result.accepted is True
    return result.capture.snapshot_path


def test_loader_reconstructs_all_governed_evaluators(tmp_path: Path) -> None:
    snapshot_path = _accepted_snapshot(tmp_path)

    bundle = FrozenPolicyReplayLoader().load(snapshot_path)

    assert bundle.readiness is FrozenReplayReadiness.READY
    assert bundle.production_influence is False
    assert len(bundle.evaluators) == len(FrozenInputSection)
    assert {item.section for item in bundle.evaluators} == set(
        FrozenInputSection
    )


def test_loader_detects_snapshot_tamper(tmp_path: Path) -> None:
    snapshot_path = _accepted_snapshot(tmp_path)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["candidate"]["symbol"] = "TAMPERED"
    snapshot_path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    bundle = FrozenPolicyReplayLoader().load(snapshot_path)

    assert bundle.readiness is FrozenReplayReadiness.TAMPERED
    assert bundle.evaluators == ()


def test_loader_blocks_unsupported_policy_version(tmp_path: Path) -> None:
    snapshot_path = _accepted_snapshot(tmp_path)
    registry = FrozenPolicyRegistry(
        {
            section: "unsupported"
            for section in FrozenInputSection
        }
    )

    bundle = FrozenPolicyReplayLoader(registry).load(snapshot_path)

    assert bundle.readiness is FrozenReplayReadiness.UNSUPPORTED_POLICY
    assert bundle.evaluators == ()


def test_loader_blocks_incomplete_snapshot(tmp_path: Path) -> None:
    snapshot_path = _accepted_snapshot(tmp_path)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["sections"] = payload["sections"][:-1]
    snapshot_path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    bundle = FrozenPolicyReplayLoader().load(snapshot_path)

    assert bundle.readiness is FrozenReplayReadiness.INCOMPLETE
    assert bundle.evaluators == ()
