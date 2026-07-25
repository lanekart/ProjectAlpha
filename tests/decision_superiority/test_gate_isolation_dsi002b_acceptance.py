from __future__ import annotations

import csv
import json
from pathlib import Path

from alpha.decision_superiority.gate_isolation_dsi002a_acceptance import (
    run_dsi002a_acceptance,
)
from alpha.decision_superiority.gate_isolation_dsi002b_acceptance import (
    run_dsi002b_acceptance,
)
from alpha.decision_superiority.gate_isolation_frozen_policy_replay import (
    FrozenReplayReadiness,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputSection,
)


def test_dsi002b_acceptance_is_complete(tmp_path: Path) -> None:
    capture_output = tmp_path / "capture"
    captured = run_dsi002a_acceptance(capture_output)
    output = tmp_path / "replay"

    result = run_dsi002b_acceptance(
        snapshot_path=captured.capture.snapshot_path,
        output=output,
    )

    assert result.accepted is True
    assert result.replay.readiness is FrozenReplayReadiness.READY
    assert result.production_influence is False
    assert len(result.replay.evaluators) == len(FrozenInputSection)
    certificate = json.loads(
        (output / "dsi002b_frozen_policy_replay_certificate.json").read_text(
            encoding="utf-8"
        )
    )
    assert certificate["accepted"] is True
    assert certificate["production_influence"] is False


def test_dsi002b_lineage_export_is_complete(tmp_path: Path) -> None:
    captured = run_dsi002a_acceptance(tmp_path / "capture")
    output = tmp_path / "replay"

    run_dsi002b_acceptance(
        snapshot_path=captured.capture.snapshot_path,
        output=output,
    )

    with (output / "dsi002b_evaluator_lineage.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = tuple(csv.DictReader(handle))
    assert len(rows) == len(FrozenInputSection)
    assert {row["section"] for row in rows} == {
        section.value for section in FrozenInputSection
    }
    assert all(row["production_influence"] == "False" for row in rows)
