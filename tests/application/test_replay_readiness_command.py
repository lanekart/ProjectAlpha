"""Tests for the diagnostic replay readiness CLI command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import alpha.cli as cli_module


def test_replay_readiness_command_is_diagnostic_and_forwards_inputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    identity_path = tmp_path / "identities.csv"
    action_path = tmp_path / "actions.csv"
    database = tmp_path / "truth.duckdb"
    snapshots = tmp_path / "snapshots"
    output = tmp_path / "readiness"
    identity_path.write_text("security_id,symbol,exchange\n", encoding="utf-8")
    action_path.write_text(
        "event_id,security_id,symbol,action_type,effective_date,status\n",
        encoding="utf-8",
    )
    snapshots.mkdir()
    captured: dict[str, object] = {}
    assessment = object()

    def fake_assess(**kwargs):
        captured.update(kwargs)
        return assessment

    monkeypatch.setattr(cli_module, "assess_governed_historical_replay", fake_assess)
    monkeypatch.setattr(
        cli_module,
        "render_governed_historical_replay_assessment",
        lambda value: (
            (
                "Historical Replay Readiness Assessment",
                "Status: BLOCKED",
                "Executor Invoked: false",
            )
            if value is assessment
            else ()
        ),
    )

    result = CliRunner().invoke(
        cli_module.app,
        [
            "replay",
            "readiness",
            "--from-date",
            "2026-01-01",
            "--to-date",
            "2026-07-20",
            "--identity-artifact",
            str(identity_path),
            "--corporate-action-artifact",
            str(action_path),
            "--database",
            str(database),
            "--historical-truth-snapshots",
            str(snapshots),
            "--output",
            str(output),
        ],
        env={"_TYPER_FORCE_DISABLE_TERMINAL": "1"},
    )

    assert result.exit_code == 0
    assert "Status: BLOCKED" in result.stdout
    assert "Executor Invoked: false" in result.stdout
    assert captured["database_path"] == database
    assert captured["snapshots_path"] == snapshots
    assert captured["output"] == output
