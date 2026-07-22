from __future__ import annotations

from typer.testing import CliRunner

from alpha.__main__ import _historical_truth_app

COMMAND_NAME = "adjustment-replay-admission-certify"


def test_htr010b1_command_is_listed_in_historical_truth_help() -> None:
    result = CliRunner().invoke(_historical_truth_app(), ["--help"])

    assert result.exit_code == 0
    assert COMMAND_NAME in result.stdout


def test_htr010b1_registration_is_idempotent() -> None:
    app = _historical_truth_app()
    before = sum(
        command.name == COMMAND_NAME for command in app.registered_commands
    )

    same_app = _historical_truth_app()
    after = sum(
        command.name == COMMAND_NAME for command in same_app.registered_commands
    )

    assert same_app is app
    assert before == 1
    assert after == 1
