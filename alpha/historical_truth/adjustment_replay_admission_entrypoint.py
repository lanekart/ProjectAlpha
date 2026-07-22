"""Standalone Typer application for HTR-010B1."""

import typer

from alpha.historical_truth.adjustment_replay_admission_cli import (
    adjustment_replay_admission_certify,
)

app = typer.Typer(help="Validate adjustment factors and certify replay admission.")
app.command("certify")(adjustment_replay_admission_certify)


if __name__ == "__main__":
    app()
