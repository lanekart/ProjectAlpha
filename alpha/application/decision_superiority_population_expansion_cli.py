"""Permanent CLI for DSI-003 governed population expansion."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.decision_superiority.population_expansion import (
    GovernedPopulationExpansionEngine,
)
from alpha.decision_superiority.population_expansion_artifacts import (
    export_population_expansion,
    validate_population_expansion_certificate,
)
from alpha.decision_superiority.population_expansion_models import (
    PopulationExpansionError,
    PopulationExpansionSourcePaths,
)

DEFAULT_DSI003_OUTPUT = Path(".alpha/benchmark/dsi003_population_expansion")


def register_decision_superiority_population_expansion_command(
    app: typer.Typer,
) -> None:
    """Register DSI-003 execution and public verification commands."""

    app.command("decision-superiority-population-expansion")(
        decision_superiority_population_expansion
    )
    app.command("decision-superiority-population-expansion-verify")(
        decision_superiority_population_expansion_verify
    )


def decision_superiority_population_expansion(
    b5_certificate: Annotated[Path, typer.Option("--b5-certificate")],
    b7_certificate: Annotated[Path, typer.Option("--b7-certificate")],
    b10_certificate: Annotated[Path, typer.Option("--b10-certificate")],
    dsi001_certificate: Annotated[Path, typer.Option("--dsi001-certificate")],
    dsi002a_certificate: Annotated[Path, typer.Option("--dsi002a-certificate")],
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
    dsi002_certificate: Annotated[Path, typer.Option("--dsi002-certificate")],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DSI003_OUTPUT,
) -> None:
    """Execute DSI-003 A-I from caller-selected signed evidence."""

    paths = PopulationExpansionSourcePaths(
        b5_certificate=b5_certificate,
        b7_certificate=b7_certificate,
        b10_certificate=b10_certificate,
        dsi001_certificate=dsi001_certificate,
        dsi002a_certificate=dsi002a_certificate,
        dsi002d1_certificate=dsi002d1_certificate,
        dsi002b2_certificate=dsi002b2_certificate,
        dsi002c2_certificate=dsi002c2_certificate,
        dsi002d2_certificate=dsi002d2_certificate,
        dsi002_certificate=dsi002_certificate,
    )
    typer.echo("DSI-003 signed source-chain validation")
    try:
        result = GovernedPopulationExpansionEngine().run(
            sources=paths,
            project_root=Path("."),
        )
        artifacts = export_population_expansion(result, output)
    except (OSError, PopulationExpansionError, ValueError) as exc:
        typer.echo(f"SIGNED_EXECUTION_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    for slice_id, readiness in result.readiness.items():
        typer.echo(f"DSI-003{slice_id} Readiness: {readiness}")
    typer.echo(
        "Candidate arms / economic candidates: "
        f"{result.summaries['candidate_arm_count']} / "
        f"{result.summaries['unique_economic_candidate_count']}"
    )
    typer.echo(
        "Securities / dates: "
        f"{result.summaries['security_count']} / "
        f"{result.summaries['unique_date_count']}"
    )
    typer.echo(
        "Plans / completed outcomes: "
        f"{result.summaries['plan_count']} / "
        f"{result.summaries['completed_outcome_count']}"
    )
    typer.echo(
        f"Exact DSI-002 candidates: {result.summaries['exact_dsi002_candidate_count']}"
    )
    typer.echo("DEFAULT_RUNTIME_BEHAVIOUR_CHANGED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(artifacts)} files)")


def decision_superiority_population_expansion_verify(
    certificate: Annotated[Path, typer.Option("--certificate")],
    require_ready: Annotated[bool, typer.Option("--require-ready")] = False,
) -> None:
    """Verify the DSI-003 certificate and all 20 bound support artifacts."""

    try:
        payload = validate_population_expansion_certificate(
            certificate,
            require_ready=require_ready,
        )
    except PopulationExpansionError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo("Certificate: VALID")


__all__ = [
    "DEFAULT_DSI003_OUTPUT",
    "decision_superiority_population_expansion",
    "decision_superiority_population_expansion_verify",
    "register_decision_superiority_population_expansion_command",
]
