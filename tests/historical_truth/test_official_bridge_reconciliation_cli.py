from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_reconciliation_cli_exports_governed_report(tmp_path: Path) -> None:
    certifications = [
        {
            "bridge_case_id": f"case-{index}",
            "continuity_decision": (
                "CERTIFIED_CONTINUOUS_IDENTITY"
                if index < 23
                else "INSUFFICIENT_OFFICIAL_EVIDENCE"
            ),
            "effective_from": "2026-01-02",
        }
        for index in range(24)
    ]
    validations = [
        {
            "bridge_case_id": f"case-{index}",
            "bridge_certified_for_replay": index < 23,
        }
        for index in range(24)
    ]
    intervals = [
        {
            "bridge_case_id": f"case-{index}",
            "admission_state": (
                "RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT"
                if index < 23
                else "BRIDGE_UNCERTIFIED_QUARANTINED"
            ),
            "admitted_price_view": "RAW" if index < 23 else "NONE",
        }
        for index in range(24)
    ]
    output = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alpha.historical_truth.official_bridge_reconciliation_cli",
            "--bridge-certifications",
            str(_write(tmp_path / "certifications.json", certifications)),
            "--validation-results",
            str(_write(tmp_path / "validations.json", validations)),
            "--admission-intervals",
            str(_write(tmp_path / "intervals.json", intervals)),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Certified propagation: 23" in result.stdout
    assert "Governed exclusions: 1" in result.stdout
    report = json.loads(
        (output / "htr010b1g_reconciliation_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["implementation_defect_count"] == 0
    assert report["production_influence"] is False
