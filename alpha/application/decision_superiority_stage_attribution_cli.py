"""Permanent benchmark CLI for governed DSI-002D stage attribution."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.decision_superiority.gate_isolation_stage_attribution import (
    DSI002DSourceContractError,
    GovernedStageAttributionEngine,
)
from alpha.decision_superiority.gate_isolation_stage_attribution_artifacts import (
    export_dsi002d,
)

DEFAULT_DSI002D_OUTPUT = Path(
    ".alpha/benchmark/dsi002d_gate_isolation_stage_attribution"
)


def register_decision_superiority_stage_attribution_command(
    app: typer.Typer,
) -> None:
    """Register the permanent DSI-002D command."""

    app.command("decision-superiority-gate-isolation-stage-attribution")(
        decision_superiority_stage_attribution
    )


def decision_superiority_stage_attribution(
    dsi002a_certificate: Annotated[
        Path,
        typer.Option("--dsi002a-certificate"),
    ],
    dsi002b_certificate: Annotated[
        Path,
        typer.Option("--dsi002b-certificate"),
    ],
    dsi002c_certificate: Annotated[
        Path,
        typer.Option("--dsi002c-certificate"),
    ],
    output: Annotated[
        Path,
        typer.Option("--output"),
    ] = DEFAULT_DSI002D_OUTPUT,
) -> None:
    """Replay the signed baseline and attribute its real evaluator stages."""

    typer.echo("DSI-002D source validation")
    try:
        result = GovernedStageAttributionEngine().run(
            dsi002a_certificate=dsi002a_certificate,
            dsi002b_certificate=dsi002b_certificate,
            dsi002c_certificate=dsi002c_certificate,
        )
    except DSI002DSourceContractError as exc:
        typer.echo(f"SIGNED_EXECUTION_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo("DSI-002D canonical stage replay")
    paths = export_dsi002d(result, output)
    typer.echo(f"Readiness: {result.readiness.value}")
    typer.echo(f"Candidates: {len(result.attributions)}")
    typer.echo(f"Stage inventory entries: {len(result.stage_inventory)}")
    typer.echo(f"Stage events: {len(result.events)}")
    typer.echo(
        "Attribution complete: "
        f"{sum(item.attribution_complete for item in result.attributions)}"
    )
    typer.echo(
        "Missing evaluator wiring: "
        f"{sum(not item.wired_into_baseline for item in result.stage_inventory)}"
    )
    typer.echo(
        "Blockers: " + ("; ".join(result.blockers) if result.blockers else "NONE")
    )
    typer.echo("COUNTERFACTUAL_GATE_OVERRIDE_ENABLED=false")
    typer.echo("RECOMMENDATION_INFLUENCE=false")
    typer.echo("EXECUTION_INFLUENCE=false")
    typer.echo("ACTIVE_REPLAY_INTEGRATION=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


__all__ = [
    "DEFAULT_DSI002D_OUTPUT",
    "decision_superiority_stage_attribution",
    "register_decision_superiority_stage_attribution_command",
]
