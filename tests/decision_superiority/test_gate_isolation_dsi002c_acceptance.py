from __future__ import annotations

import json
from pathlib import Path

from alpha.decision_superiority.gate_isolation_dsi002a_acceptance import (
    run_dsi002a_acceptance,
)
from alpha.decision_superiority.gate_isolation_dsi002c_acceptance import (
    run_dsi002c_acceptance,
)


def test_dsi002c_acceptance_is_complete(tmp_path: Path) -> None:
    captured = run_dsi002a_acceptance(tmp_path / "capture")
    output = tmp_path / "parity"

    result = run_dsi002c_acceptance(
        snapshot_path=captured.capture.snapshot_path,
        output=output,
    )

    assert result.accepted is True
    assert result.parity.parity_verified is True
    assert result.baseline_tamper_block_verified is True
    assert result.candidate_identity_block_verified is True
    assert result.snapshot_identity_block_verified is True
    assert result.deterministic_replay_verified is True
    assert result.production_influence is False
    certificate = json.loads(
        (
            output / "dsi002c_recorded_decision_parity_certificate.json"
        ).read_text(encoding="utf-8")
    )
    assert certificate["accepted"] is True
    assert certificate["production_influence"] is False
