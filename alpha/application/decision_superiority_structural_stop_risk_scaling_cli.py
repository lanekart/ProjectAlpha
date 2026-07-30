"""Permanent CLI for governed DSI-012 structural-stop risk scaling."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.config.settings import settings
from alpha.decision_superiority.structural_stop_risk_scaling import (
    GovernedStructuralStopRiskScalingEngine,
)
from alpha.decision_superiority.structural_stop_risk_scaling_artifacts import (
    export_structural_stop_risk_scaling,
    validate_structural_stop_risk_scaling_certificate,
)
from alpha.decision_superiority.structural_stop_risk_scaling_models import (
    StructuralStopRiskScalingError,
    StructuralStopRiskScalingSourcePaths,
)

DEFAULT_DSI012_OUTPUT = Path(
    ".alpha/benchmark/dsi012_structural_stop_risk_scaling"
)


def register_decision_superiority_structural_stop_risk_scaling_command(
    app: typer.Typer,
) -> None:
    """Register the DSI-012 runner and verifier."""

    app.command("decision-superiority-structural-stop-risk-scaling")(
        decision_superiority_structural_stop_risk_scaling
    )
    app.command("decision-superiority-structural-stop-risk-scaling-verify")(
        decision_superiority_structural_stop_risk_scaling_verify
    )


def decision_superiority_structural_stop_risk_scaling(
    dsi009_certificate: Annotated[
        Path,
        typer.Option("--dsi009-certificate"),
    ],
    dsi008_certificate: Annotated[
        Path,
        typer.Option("--dsi008-certificate"),
    ],
    dsi007_certificate: Annotated[
        Path,
        typer.Option("--dsi007-certificate"),
    ],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DSI012_OUTPUT,
    database: Annotated[
        Path,
        typer.Option("--database"),
    ] = settings.database_path,
) -> None:
    """Run the fixed research-only 1.50x structural-stop overlay."""

    try:
        result = GovernedStructuralStopRiskScalingEngine().run(
            sources=StructuralStopRiskScalingSourcePaths(
                dsi009_certificate=dsi009_certificate,
                dsi008_certificate=dsi008_certificate,
                dsi007_certificate=dsi007_certificate,
                database=database,
                project_root=Path("."),
            )
        )
        paths = export_structural_stop_risk_scaling(result, output)
    except (OSError, StructuralStopRiskScalingError, ValueError) as exc:
        typer.echo(f"GOVERNED_STRUCTURAL_STOP_RISK_SCALING_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    scaled = result.summaries["base_financing"]
    stress = result.summaries["stress_financing"]
    typer.echo(f"Readiness: {result.readiness}")
    typer.echo("Mechanism: STOP-STRUCTURAL-10D")
    typer.echo("Risk Multiplier: 1.50x")
    typer.echo(f"Base-Financing CAGR: {_percent(scaled.get('net_cagr'))}")
    typer.echo(
        "Base-Financing Maximum Drawdown: "
        f"{_percent(scaled.get('maximum_drawdown'))}"
    )
    typer.echo(f"Base-Financing Calmar: {_number(scaled.get('calmar'))}")
    typer.echo(
        "Base-Financing Daily Profit Factor: "
        f"{_number(scaled.get('daily_profit_factor'))}"
    )
    typer.echo(f"Stress-Financing CAGR: {_percent(stress.get('net_cagr'))}")
    typer.echo(
        f"Acceptance Passed: {str(result.summaries['acceptance_passed']).lower()}"
    )
    typer.echo("VALIDATED_STRATEGY=false")
    typer.echo("AUTOMATIC_STRATEGY_PROMOTION_ENABLED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def decision_superiority_structural_stop_risk_scaling_verify(
    certificate: Annotated[Path, typer.Option("--certificate")],
    require_target_match: Annotated[
        bool,
        typer.Option("--require-target-match"),
    ] = False,
) -> None:
    """Validate a public DSI-012 certificate and support package."""

    try:
        payload = validate_structural_stop_risk_scaling_certificate(
            certificate,
            require_target_match=require_target_match,
        )
    except StructuralStopRiskScalingError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo(
        f"Acceptance Passed: {str(payload['acceptance_passed']).lower()}"
    )
    typer.echo("Validated Strategy: false")
    typer.echo("Certificate: VALID")


def _percent(value: object) -> str:
    return "UNKNOWN" if value is None else f"{float(value) * 100:.2f}%"


def _number(value: object) -> str:
    return "UNKNOWN" if value is None else f"{float(value):.2f}"


__all__ = [
    "register_decision_superiority_structural_stop_risk_scaling_command",
]
