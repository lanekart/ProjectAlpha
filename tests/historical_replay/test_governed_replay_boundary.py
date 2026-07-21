"""Regression tests preventing raw historical observation replay bypasses."""

from __future__ import annotations

import ast
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
        and _constructs(path, "HistoricalObservationFactory")
    )

    assert offenders == ()


def test_primary_replay_cli_has_no_raw_factory_or_engine_construction() -> None:
    cli_path = Path("alpha/cli.py")
    cli_source = cli_path.read_text(encoding="utf-8")

    assert not _constructs(cli_path, "HistoricalObservationFactory")
    assert not _constructs(cli_path, "HistoricalReplayEngine")
    assert "execute_governed_historical_replay(" in cli_source


def test_replay_run_requires_governed_recovery_artifacts() -> None:
    base_arguments = [
        "replay",
        "run",
        "--from-date",
        "2025-01-01",
        "--to-date",
        "2025-01-31",
    ]
    missing_identity = CliRunner().invoke(app, base_arguments)
    missing_actions = CliRunner().invoke(
        app,
        [*base_arguments, "--identity-artifact", "identities.csv"],
    )

    assert missing_identity.exit_code != 0
    assert "--identity-artifact" in missing_identity.output
    assert missing_actions.exit_code != 0
    assert "--corporate-action-artifact" in missing_actions.output


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


def _constructs(path: Path, symbol: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name) and function.id == symbol:
            return True
        if isinstance(function, ast.Attribute) and function.attr == symbol:
            return True
    return False
