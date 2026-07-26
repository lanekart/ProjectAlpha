"""Permanent CLI for DSI-002D1 complete-stack baseline renewal."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.decision_superiority.gate_isolation_complete_stack_baseline import (
    CompleteStackArtifactError,
    CompleteStackBaselineEngine,
    export_complete_stack_result,
)
from alpha.decision_superiority.gate_isolation_stage_attribution import (
    DSI002DSourceContractError,
)

DEFAULT_DSI002D1_OUTPUT = Path(".alpha/benchmark/dsi002d1_complete_stack_baseline")


def register_decision_superiority_complete_stack_command(app: typer.Typer) -> None:
    """Register the permanent DSI-002D1 command."""

    app.command("decision-superiority-complete-stack-baseline")(
        decision_superiority_complete_stack_baseline
    )


def decision_superiority_complete_stack_baseline(
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
    dsi002d_certificate: Annotated[
        Path,
        typer.Option("--dsi002d-certificate"),
    ],
    output: Annotated[
        Path,
        typer.Option("--output"),
    ] = DEFAULT_DSI002D1_OUTPUT,
) -> None:
    """Diagnose old wiring and renew the governed complete-stack baseline."""

    typer.echo("DSI-002D1 signed source validation")
    try:
        result = CompleteStackBaselineEngine().run(
            dsi002a_certificate=dsi002a_certificate,
            dsi002b_certificate=dsi002b_certificate,
            dsi002c_certificate=dsi002c_certificate,
            dsi002d_certificate=dsi002d_certificate,
        )
        paths = export_complete_stack_result(result, output)
    except (DSI002DSourceContractError, CompleteStackArtifactError) as exc:
        typer.echo(f"SIGNED_EXECUTION_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"DSI-002D1 Readiness: {result.readiness.value}")
    typer.echo("DSI-002B2 Readiness: READY_FOR_COMPLETE_STACK_RECORDED_BASELINE")
    typer.echo("DSI-002C2 Readiness: READY_FOR_COMPLETE_STACK_STAGE_ATTRIBUTION")
    typer.echo("DSI-002D2 Readiness: READY_FOR_GOVERNED_STAGE_ATTRIBUTION_RESEARCH")
    typer.echo(f"Candidate: {result.candidate_identity}")
    typer.echo(f"Old terminal recommendation: {result.old_terminal_decision}")
    typer.echo(
        f"Renewed terminal institutional decision: {result.new_terminal_decision}"
    )
    typer.echo(f"Allocation decision: {result.allocation_decision}")
    typer.echo(
        "Institutional evaluator invocations: "
        + ", ".join(
            f"{row['stage_id']}={row['invocation_count']}"
            for row in result.invocation_rows
            if str(row["stage_id"]).startswith("institutional_")
        )
    )
    typer.echo("DEFAULT_RUNTIME_BEHAVIOUR_CHANGED=false")
    typer.echo("LIVE_SCORING_ENABLED=false")
    typer.echo("RECOMMENDATION_INFLUENCE=false")
    typer.echo("EXECUTION_INFLUENCE=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


__all__ = [
    "DEFAULT_DSI002D1_OUTPUT",
    "decision_superiority_complete_stack_baseline",
    "register_decision_superiority_complete_stack_command",
]
