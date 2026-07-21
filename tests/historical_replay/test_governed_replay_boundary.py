"""Regression tests preventing raw historical observation replay bypasses."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from alpha.cli import app


def test_production_observation_factory_construction_is_governed() -> None:
    """Only the governed wrapper may construct the lower-level raw factory."""

    alpha_root = Path("alpha")
    allowed = {
        Path("alpha/historical_replay/factory.py"),
        Path("alpha/historical_replay/governed_factory.py"),
    }
    offenders = tuple(
        str(path)
        for path in sorted(alpha_root.rglob("*.py"))
        if path not in allowed
        and "HistoricalObservationFactory(" in path.read_text(encoding="utf-8")
    )

    assert offenders == ()


def test_primary_replay_cli_has_no_raw_factory_or_engine_construction() -> None:
    cli_source = Path("alpha/cli.py").read_text(encoding="utf-8")

    assert "HistoricalObservationFactory(" not in cli_source
    assert "HistoricalReplayEngine(" not in cli_source
    assert "execute_governed_historical_replay(" in cli_source


def test_replay_run_requires_governed_recovery_artifacts() -> None:
    result = CliRunner().invoke(
        app,
        [
            "replay",
            "run",
            "--from-date",
            "2025-01-01",
            "--to-date",
            "2025-01-31",
        ],
    )

    assert result.exit_code != 0
    assert "--identity-artifact" in result.output
    assert "--corporate-action-artifact" in result.output


def test_refresh_replay_fails_closed_without_governed_artifacts() -> None:
    result = CliRunner().invoke(
        app,
        [
            "learning",
            "combinations",
            "--refresh-replay",
            "--from-date",
            "2025-01-01",
            "--to-date",
            "2025-01-31",
        ],
    )

    assert result.exit_code != 0
    assert "requires --identity-artifact" in result.output
    assert "--corporate-action-artifact" in result.output
