from __future__ import annotations

import json
from pathlib import Path

from alpha.decision_superiority.gate_isolation_dsi002a_acceptance import (
    run_dsi002a_acceptance,
)


def test_dsi002a_acceptance_run_is_complete(tmp_path: Path) -> None:
    result = run_dsi002a_acceptance(tmp_path)

    assert result.accepted is True
    assert result.capture.replay_ready is True
    assert result.parity_verified is True
    assert result.duplicate_protection_verified is True
    assert result.missing_section_block_verified is True
    assert result.post_observation_block_verified is True
    assert result.capture_failure_isolation_verified is True
    assert result.production_influence is False

    certificate_path = tmp_path / "dsi002a_forward_capture_certificate.json"
    summary_path = tmp_path / "dsi002a_forward_capture_acceptance.csv"
    assert certificate_path.exists()
    assert summary_path.exists()
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    assert certificate["accepted"] is True
    assert certificate["production_influence"] is False
