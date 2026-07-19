"""CLI commands for the non-production Data Value and ROI Audit."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.data_value_audit import (
    DEFAULT_DVRA_OUTPUT,
    DataValueAuditExporter,
    build_default_audit,
)
from alpha.data_value_audit.rendering import (
    render_audit,
    render_budgets,
    render_report,
    render_roi,
)

data_value_app = typer.Typer(
    help="Rank historical data investments without affecting production.",
    no_args_is_help=True,
)


@data_value_app.command("audit")
def data_value_audit(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DVRA_OUTPUT,
) -> None:
    """Evaluate every registered dataset and write the complete audit bundle."""

    report = build_default_audit()
    paths = DataValueAuditExporter().export(report, output)
    typer.echo(render_audit(report), nl=False)
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


@data_value_app.command("roi")
def data_value_roi(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DVRA_OUTPUT,
) -> None:
    """Show estimable priorities separately from unknown standalone ROI."""

    report = build_default_audit()
    DataValueAuditExporter().export(report, output)
    typer.echo(render_roi(report), nl=False)


@data_value_app.command("budgets")
def data_value_budgets(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DVRA_OUTPUT,
) -> None:
    """Show the INR 0, INR 1 lakh, INR 5 lakh, and unlimited strategies."""

    report = build_default_audit()
    DataValueAuditExporter().export(report, output)
    typer.echo(render_budgets(report), nl=False)


@data_value_app.command("report")
def data_value_report(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DVRA_OUTPUT,
) -> None:
    """Render the executive decision report and refresh all artifacts."""

    report = build_default_audit()
    DataValueAuditExporter().export(report, output)
    typer.echo(render_report(report), nl=False)


__all__ = ["data_value_app"]
