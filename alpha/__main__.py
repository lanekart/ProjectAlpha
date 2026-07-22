from __future__ import annotations

import sys

import typer


def _historical_truth_app() -> typer.Typer:
    from alpha.historical_truth.adjustment_replay_admission_cli import (
        adjustment_replay_admission_certify,
    )
    from alpha.historical_truth.cli import historical_truth_app

    command_name = "adjustment-replay-admission-certify"
    if not any(
        command.name == command_name
        for command in historical_truth_app.registered_commands
    ):
        historical_truth_app.command(command_name)(adjustment_replay_admission_certify)
    return historical_truth_app


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "historical-truth":
        historical_truth_app = _historical_truth_app()
        sys.argv.pop(1)
        historical_truth_app()
        return

    from alpha.cli import app

    app()


if __name__ == "__main__":
    main()
