from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from alpha.__main__ import _historical_truth_app


def _write_upstream(root: Path) -> Path:
    root.mkdir(parents=True)
    cases: list[dict[str, object]] = []
    for index in range(15):
        cases.append(
            {
                "case_id": f"unique-{index}",
                "htr010b1d2_contract_version": "HTR-010B1D2-v1.0.0",
                "effective_date": f"2026-01-{index + 1:02d}",
                "bridge_type": "CROSS_ISIN",
                "bridge_dependency_state": "UNCERTIFIED_CROSS_ISIN",
                "prior_isin": f"INE000000{index:03d}",
                "current_isin": f"INE100000{index:03d}",
                "prior_symbol": f"SYM{index}",
                "current_symbol": f"SYM{index}",
                "prior_series": "EQ",
                "current_series": "EQ",
                "factor_quality_confirmed": True,
            }
        )
    for index in range(4):
        for suffix in ("a", "b"):
            cases.append(
                {
                    "case_id": f"duplicate-{index}-{suffix}",
                    "htr010b1d2_contract_version": "HTR-010B1D2-v1.0.0",
                    "effective_date": f"2026-02-{index + 1:02d}",
                    "bridge_type": "CROSS_ISIN",
                    "bridge_dependency_state": "UNCERTIFIED_CROSS_ISIN",
                    "prior_isin": f"INE200000{index:03d}",
                    "current_isin": f"INE300000{index:03d}",
                    "prior_symbol": f"DUP{index}",
                    "current_symbol": f"DUP{index}",
                    "prior_series": "EQ",
                    "current_series": "EQ",
                    "factor_quality_confirmed": True,
                }
            )
    cases.append(
        {
            "case_id": "kotyark-series",
            "htr010b1d2_contract_version": "HTR-010B1D2-v1.0.0",
            "effective_date": "2026-06-24",
            "bridge_type": "CROSS_SERIES",
            "bridge_dependency_state": "UNCERTIFIED_CROSS_SERIES",
            "prior_isin": "INE0J0B01017",
            "current_isin": "INE0J0B01017",
            "prior_symbol": "KOTYARK",
            "current_symbol": "KOTYARK",
            "prior_series": "EQ",
            "current_series": "BE",
            "factor_quality_confirmed": True,
        }
    )
    (root / "htr010b1d2_reclassified_cases.json").write_text(
        json.dumps(cases), encoding="utf-8"
    )
    return root


def test_completion_command_is_registered() -> None:
    commands = {command.name for command in _historical_truth_app().registered_commands}
    assert "official-bridge-complete" in commands


def test_completion_cli_runs_governed_no_download_baseline(tmp_path: Path) -> None:
    runner = CliRunner()
    output = tmp_path / "completion"
    result = runner.invoke(
        _historical_truth_app(),
        [
            "official-bridge-complete",
            "--htr010b1d2-output",
            str(_write_upstream(tmp_path / "upstream")),
            "--no-download-documents",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "HTR-010B1F Completion Bundle" in result.stdout
    assert "Bridge cases: 24" in result.stdout
    assert "Unique dossiers: 20" in result.stdout
    assert "Implementation defects: 0" in result.stdout
    assert "NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION" in result.stdout
    assert (output / "htr010b1f_completion_report.json").exists()
