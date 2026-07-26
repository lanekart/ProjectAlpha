"""Permanent CLI for the complete DSI-002E-J research package."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.decision_superiority.gate_isolation_shadow import (
    GateIsolationShadowEngine,
    GateIsolationShadowError,
)
from alpha.decision_superiority.gate_isolation_shadow_artifacts import (
    GateIsolationShadowArtifactError,
    export_gate_isolation_shadow,
    validate_gate_isolation_shadow_certificate,
)

DEFAULT_DSI002_EJ_OUTPUT = Path(".alpha/benchmark/dsi002_gate_isolation_shadow")


def register_decision_superiority_gate_isolation_shadow_command(
    app: typer.Typer,
) -> None:
    """Register permanent E-J execution and verification commands."""

    app.command("decision-superiority-gate-isolation-shadow")(
        decision_superiority_gate_isolation_shadow
    )
    app.command("decision-superiority-gate-isolation-shadow-verify")(
        decision_superiority_gate_isolation_shadow_verify
    )


def decision_superiority_gate_isolation_shadow(
    dsi002d1_certificate: Annotated[
        Path,
        typer.Option("--dsi002d1-certificate"),
    ],
    dsi002b2_certificate: Annotated[
        Path,
        typer.Option("--dsi002b2-certificate"),
    ],
    dsi002c2_certificate: Annotated[
        Path,
        typer.Option("--dsi002c2-certificate"),
    ],
    dsi002d2_certificate: Annotated[
        Path,
        typer.Option("--dsi002d2-certificate"),
    ],
    output: Annotated[
        Path,
        typer.Option("--output"),
    ] = DEFAULT_DSI002_EJ_OUTPUT,
) -> None:
    """Execute the governed single-gate through interpretation package."""

    typer.echo("DSI-002E-J renewed source validation")
    try:
        result = GateIsolationShadowEngine().run(
            dsi002d1_certificate=dsi002d1_certificate,
            dsi002b2_certificate=dsi002b2_certificate,
            dsi002c2_certificate=dsi002c2_certificate,
            dsi002d2_certificate=dsi002d2_certificate,
        )
        paths = export_gate_isolation_shadow(result, output)
    except (
        GateIsolationShadowError,
        GateIsolationShadowArtifactError,
        ValueError,
    ) as exc:
        typer.echo(f"SIGNED_EXECUTION_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"DSI-002E Readiness: {result.e_readiness.value}")
    typer.echo(f"DSI-002F Readiness: {result.f_readiness.value}")
    typer.echo(f"DSI-002G Readiness: {result.g_readiness.value}")
    typer.echo(f"DSI-002H Readiness: {result.h_readiness.value}")
    typer.echo(f"DSI-002I Readiness: {result.i_readiness.value}")
    typer.echo(f"DSI-002J Readiness: {result.j_readiness.value}")
    typer.echo(f"Candidate: {result.candidate_identity}")
    eligible_count = sum(
        row["eligibility"] == "OVERRIDE_ELIGIBLE" for row in result.rows["eligibility"]
    )
    typer.echo(
        "Observed/eligible conditions: "
        f"{len(result.rows['eligibility'])}/{eligible_count}"
    )
    typer.echo(f"Exact subsets tested: {len(result.rows['search'])}")
    approval_count = sum(
        row["institutionally_approved"] is True for row in result.rows["funnel"]
    )
    typer.echo(f"Institutional approvals: {approval_count}")
    typer.echo(
        "Comparable completed outcomes: "
        f"{sum(row['completed_outcome'] is True for row in result.rows['outcomes'])}"
    )
    typer.echo("DEFAULT_RUNTIME_BEHAVIOUR_CHANGED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def decision_superiority_gate_isolation_shadow_verify(
    certificate: Annotated[Path, typer.Option("--certificate")],
    require_ready: Annotated[bool, typer.Option("--require-ready")] = False,
) -> None:
    """Validate a final or internal E-J certificate."""

    try:
        payload = validate_gate_isolation_shadow_certificate(
            certificate,
            require_ready=require_ready,
        )
    except GateIsolationShadowArtifactError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo("Certificate: VALID")


__all__ = [
    "DEFAULT_DSI002_EJ_OUTPUT",
    "decision_superiority_gate_isolation_shadow",
    "decision_superiority_gate_isolation_shadow_verify",
    "register_decision_superiority_gate_isolation_shadow_command",
]
