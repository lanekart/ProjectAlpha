"""Permanent CLI for governed DSI-004 historical recommendation rehydration."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.decision_superiority.historical_rehydration import (
    GovernedHistoricalRecommendationRehydrationEngine,
)
from alpha.decision_superiority.historical_rehydration_artifacts import (
    export_historical_rehydration,
    validate_historical_rehydration_certificate,
)
from alpha.decision_superiority.historical_rehydration_models import (
    HistoricalRehydrationError,
    HistoricalRehydrationSourcePaths,
)

DEFAULT_DSI004_OUTPUT = Path(".alpha/benchmark/dsi004_historical_rehydration")


def register_decision_superiority_historical_rehydration_command(
    app: typer.Typer,
) -> None:
    """Register DSI-004 execution and public verification commands."""

    app.command("decision-superiority-historical-recommendation-rehydration")(
        decision_superiority_historical_recommendation_rehydration
    )
    app.command("decision-superiority-historical-recommendation-rehydration-verify")(
        decision_superiority_historical_recommendation_rehydration_verify
    )


def decision_superiority_historical_recommendation_rehydration(
    dsi003_certificate: Annotated[
        Path,
        typer.Option("--dsi003-certificate"),
    ],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DSI004_OUTPUT,
) -> None:
    """Execute the governed DSI-004 A-K chain."""

    typer.echo("DSI-004 signed source-chain validation")
    try:
        result = GovernedHistoricalRecommendationRehydrationEngine().run(
            sources=HistoricalRehydrationSourcePaths(
                dsi003_certificate=dsi003_certificate,
                project_root=Path("."),
            )
        )
        paths = export_historical_rehydration(result, output)
    except (OSError, HistoricalRehydrationError, ValueError) as exc:
        typer.echo(f"SIGNED_EXECUTION_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    for slice_id, readiness in result.readiness.items():
        typer.echo(f"DSI-004{slice_id} Readiness: {readiness}")
    typer.echo(
        "DSI-003 / admitted economic candidates: "
        f"{result.summaries['dsi003_economic_candidate_count']} / "
        f"{result.summaries['admitted_economic_candidate_count']}"
    )
    typer.echo(
        "Reconstruction attempts / parity-proven: "
        f"{result.summaries['reconstruction_attempt_count']} / "
        f"{result.summaries['parity_proven_reconstruction_count']}"
    )
    typer.echo(
        "Single-gate arms / subsets / shadow approvals: "
        f"{result.summaries['single_gate_arm_count']} / "
        f"{result.summaries['remediation_subset_count']} / "
        f"{result.summaries['shadow_approval_count']}"
    )
    typer.echo("DEFAULT_RUNTIME_BEHAVIOUR_CHANGED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def decision_superiority_historical_recommendation_rehydration_verify(
    certificate: Annotated[Path, typer.Option("--certificate")],
    require_ready: Annotated[bool, typer.Option("--require-ready")] = False,
) -> None:
    """Validate one DSI-004 certificate and every bound support artifact."""

    try:
        payload = validate_historical_rehydration_certificate(
            certificate,
            require_ready=require_ready,
            project_root=Path("."),
        )
    except HistoricalRehydrationError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo("Certificate: VALID")


__all__ = [
    "DEFAULT_DSI004_OUTPUT",
    "decision_superiority_historical_recommendation_rehydration",
    "decision_superiority_historical_recommendation_rehydration_verify",
    "register_decision_superiority_historical_rehydration_command",
]
