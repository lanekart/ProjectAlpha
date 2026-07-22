from __future__ import annotations

import sys


def main() -> None:
    if (
        len(sys.argv) > 2
        and sys.argv[1] == "historical-truth"
        and sys.argv[2] == "adjustment-replay-admission-certify"
    ):
        import typer

        from alpha.historical_truth.adjustment_replay_admission_cli import (
            adjustment_replay_admission_certify,
        )

        del sys.argv[1:3]
        typer.run(adjustment_replay_admission_certify)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "historical-truth":
        from alpha.historical_truth.cli import historical_truth_app

        sys.argv.pop(1)
        historical_truth_app()
        return

    from alpha.cli import app

    app()


if __name__ == "__main__":
    main()
