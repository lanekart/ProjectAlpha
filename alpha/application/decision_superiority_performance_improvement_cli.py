"""Permanent CLI for governed DSI-008 performance improvement research."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.decision_superiority.performance_improvement import (
    GovernedPerformanceImprovementEngine,
)
from alpha.decision_superiority.performance_improvement_artifacts import (
    export_performance_improvement,
    validate_performance_improvement_certificate,
)
from alpha.decision_superiority.performance_improvement_models import (
    ImprovementSourcePaths,
    PerformanceImprovementError,
)

DEFAULT_DSI008_OUTPUT = Path(".alpha/benchmark/dsi008_performance_improvement")


def register_decision_superiority_performance_improvement_command(
    app: typer.Typer,
) -> None:
    """Register the DSI-008 runner and certificate verifier."""

    app.command("decision-superiority-performance-improvement")(
        decision_superiority_performance_improvement
    )
    app.command("decision-superiority-performance-improvement-verify")(
        decision_superiority_performance_improvement_verify
    )


def decision_superiority_performance_improvement(
    dsi007_certificate: Annotated[
        Path,
        typer.Option("--dsi007-certificate"),
    ],
    tri_benchmark: Annotated[Path, typer.Option("--tri-benchmark")],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DSI008_OUTPUT,
    database: Annotated[
        Path | None,
        typer.Option("--database"),
    ] = None,
) -> None:
    """Run the research-only DSI-008 benchmark and mechanism audit."""

    try:
        result = GovernedPerformanceImprovementEngine().run(
            sources=ImprovementSourcePaths(
                dsi007_certificate=dsi007_certificate,
                tri_benchmark=tri_benchmark,
                database=database,
                project_root=Path("."),
            )
        )
        paths = export_performance_improvement(result, output)
    except (OSError, PerformanceImprovementError, ValueError) as exc:
        typer.echo(
            f"GOVERNED_PERFORMANCE_IMPROVEMENT_FAILED: {exc}",
            err=True,
        )
        raise typer.Exit(1) from exc
    for slice_id, readiness in result.readiness.items():
        typer.echo(f"DSI-008{slice_id} Readiness: {readiness}")
    summary = result.summaries
    benchmark = summary["benchmark"]
    incumbent = summary["incumbent"]
    typer.echo(f"Benchmark: {benchmark['name']} ({benchmark['kind']})")
    typer.echo(f"Benchmark CAGR: {_percent(benchmark['cagr'])}")
    typer.echo(f"Incumbent CAGR: {_percent(incumbent['net_cagr'])}")
    typer.echo(f"Incumbent Excess CAGR: {_percent(incumbent['excess_cagr'])}")
    typer.echo(f"Accepted Challenger: {summary['accepted_challenger'] or 'NONE'}")
    typer.echo(f"Robustness Grade: {summary['robustness_grade']}")
    typer.echo("STRATEGY_AUTOMATIC_PROMOTION_ENABLED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def decision_superiority_performance_improvement_verify(
    certificate: Annotated[Path, typer.Option("--certificate")],
    require_ready: Annotated[
        bool,
        typer.Option("--require-ready"),
    ] = False,
) -> None:
    """Validate a public DSI-008 certificate and support package."""

    try:
        payload = validate_performance_improvement_certificate(
            certificate,
            require_ready=require_ready,
        )
    except PerformanceImprovementError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo("Certificate: VALID")


def _percent(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    if not isinstance(value, (str, int, float)):
        return "UNKNOWN"
    return f"{float(value) * 100:.2f}%"


__all__ = [
    "register_decision_superiority_performance_improvement_command",
]
