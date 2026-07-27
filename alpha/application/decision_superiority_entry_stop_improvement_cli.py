"""Permanent CLI for governed DSI-009 entry and stop research."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.application.decision_superiority_pre2016_external_validation_cli import (
    register_decision_superiority_pre2016_external_validation_command,
)
from alpha.config.settings import settings
from alpha.decision_superiority.entry_stop_improvement import (
    GovernedEntryStopImprovementEngine,
)
from alpha.decision_superiority.entry_stop_improvement_artifacts import (
    export_entry_stop_improvement,
    validate_entry_stop_improvement_certificate,
)
from alpha.decision_superiority.entry_stop_improvement_models import (
    EntryStopImprovementError,
    EntryStopSourcePaths,
)

DEFAULT_DSI009_OUTPUT = Path(".alpha/benchmark/dsi009_entry_stop_improvement")


def register_decision_superiority_entry_stop_improvement_command(
    app: typer.Typer,
) -> None:
    """Register DSI-009 and its governed DSI-010 successor commands."""

    app.command("decision-superiority-entry-stop-improvement")(
        decision_superiority_entry_stop_improvement
    )
    app.command("decision-superiority-entry-stop-improvement-verify")(
        decision_superiority_entry_stop_improvement_verify
    )
    register_decision_superiority_pre2016_external_validation_command(app)


def decision_superiority_entry_stop_improvement(
    dsi008_certificate: Annotated[
        Path,
        typer.Option("--dsi008-certificate"),
    ],
    dsi007_certificate: Annotated[
        Path,
        typer.Option("--dsi007-certificate"),
    ],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DSI009_OUTPUT,
    database: Annotated[
        Path,
        typer.Option("--database"),
    ] = settings.database_path,
) -> None:
    """Run research-only DSI-009 entry and stop improvement."""

    try:
        result = GovernedEntryStopImprovementEngine().run(
            sources=EntryStopSourcePaths(
                dsi008_certificate=dsi008_certificate,
                dsi007_certificate=dsi007_certificate,
                database=database,
                project_root=Path("."),
            )
        )
        paths = export_entry_stop_improvement(result, output)
    except (OSError, EntryStopImprovementError, ValueError) as exc:
        typer.echo(f"GOVERNED_ENTRY_STOP_IMPROVEMENT_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    for slice_id, readiness in result.readiness.items():
        typer.echo(f"DSI-009{slice_id} Readiness: {readiness}")
    summary = result.summaries
    incumbent = summary["incumbent"]
    benchmark = summary["benchmark"]
    typer.echo(f"Incumbent CAGR: {_percent(incumbent['net_cagr'])}")
    typer.echo(f"Nifty 500 TRI CAGR: {_percent(benchmark['cagr'])}")
    typer.echo(f"Incumbent Excess CAGR: {_percent(incumbent['excess_cagr'])}")
    typer.echo(f"Entry Champion: {summary['entry_champion'] or 'NONE'}")
    typer.echo(f"Stop Champion: {summary['stop_champion'] or 'NONE'}")
    typer.echo(f"Sequential Champion: {summary['sequential_champion'] or 'NONE'}")
    descriptive = summary["best_descriptive_result"]
    typer.echo(
        "Best Descriptive Result: "
        + (
            "NONE"
            if descriptive is None
            else (
                f"{descriptive['family']}/{descriptive['mechanism_id']} "
                f"({_percent(descriptive['net_cagr'])} CAGR)"
            )
        )
    )
    typer.echo(
        f"Forward Paper Eligible: {str(summary['forward_paper_eligible']).lower()}"
    )
    typer.echo("STRATEGY_AUTOMATIC_PROMOTION_ENABLED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def decision_superiority_entry_stop_improvement_verify(
    certificate: Annotated[Path, typer.Option("--certificate")],
    require_ready: Annotated[
        bool,
        typer.Option("--require-ready"),
    ] = False,
) -> None:
    """Validate a public DSI-009 certificate and support package."""

    try:
        payload = validate_entry_stop_improvement_certificate(
            certificate,
            require_ready=require_ready,
        )
    except EntryStopImprovementError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo(
        f"Forward Paper Eligible: {str(payload['forward_paper_eligible']).lower()}"
    )
    typer.echo("Certificate: VALID")


def _percent(value: object) -> str:
    if value is None or not isinstance(value, (str, int, float)):
        return "UNKNOWN"
    return f"{float(value) * 100:.2f}%"


__all__ = [
    "register_decision_superiority_entry_stop_improvement_command",
]
