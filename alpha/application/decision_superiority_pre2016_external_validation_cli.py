"""Permanent CLI for governed DSI-010 pre-2016 external validation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.config.settings import settings
from alpha.decision_superiority.pre2016_external_validation import (
    GovernedPre2016ExternalValidationEngine,
)
from alpha.decision_superiority.pre2016_external_validation_artifacts import (
    export_pre2016_external_validation,
    validate_pre2016_external_validation_certificate,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
    Pre2016ExternalValidationError,
    Pre2016ExternalValidationPolicy,
    Pre2016ExternalValidationSourcePaths,
)

DEFAULT_DSI010_OUTPUT = Path(".alpha/benchmark/dsi010_pre2016_external_validation")


def register_decision_superiority_pre2016_external_validation_command(
    app: typer.Typer,
) -> None:
    """Register the DSI-010 runner and public verifier."""

    app.command("decision-superiority-pre2016-external-validation")(
        decision_superiority_pre2016_external_validation
    )
    app.command("decision-superiority-pre2016-external-validation-verify")(
        decision_superiority_pre2016_external_validation_verify
    )


def decision_superiority_pre2016_external_validation(
    dsi009_certificate: Annotated[
        Path,
        typer.Option("--dsi009-certificate"),
    ],
    dsi007_certificate: Annotated[
        Path,
        typer.Option("--dsi007-certificate"),
    ],
    database: Annotated[
        Path,
        typer.Option("--database"),
    ] = settings.database_path,
    historical_truth_snapshots: Annotated[
        Path,
        typer.Option("--historical-truth-snapshots"),
    ] = settings.project_root / "alpha_data" / "snapshots",
    benchmark: Annotated[
        str,
        typer.Option("--benchmark"),
    ] = "AUTO",
    start: Annotated[
        str,
        typer.Option("--start"),
    ] = "2005-01-01",
    end: Annotated[
        str,
        typer.Option("--end"),
    ] = "2015-12-31",
    output: Annotated[
        Path,
        typer.Option("--output"),
    ] = DEFAULT_DSI010_OUTPUT,
) -> None:
    """Run the frozen DSI-009 challenger on a pre-2016 external era."""

    try:
        result = GovernedPre2016ExternalValidationEngine().run(
            sources=Pre2016ExternalValidationSourcePaths(
                dsi009_certificate=dsi009_certificate,
                dsi007_certificate=dsi007_certificate,
                database=database,
                historical_truth_snapshots=historical_truth_snapshots,
                benchmark=benchmark,
                project_root=Path("."),
            ),
            policy=Pre2016ExternalValidationPolicy(
                external_start=start,
                external_end=end,
            ),
        )
        paths = export_pre2016_external_validation(result, output)
    except (OSError, Pre2016ExternalValidationError, ValueError) as exc:
        typer.echo(f"GOVERNED_PRE2016_EXTERNAL_VALIDATION_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    for slice_id, readiness in result.readiness.items():
        typer.echo(f"DSI-010{slice_id} Readiness: {readiness}")
    summary = result.summaries
    incumbent = summary["test_a_incumbent"]
    challenger = summary["test_a_challenger"]
    benchmark_summary = summary["benchmark"]
    typer.echo(f"External Incumbent CAGR: {_percent(incumbent.get('net_cagr'))}")
    typer.echo(f"External Challenger CAGR: {_percent(challenger.get('net_cagr'))}")
    typer.echo(f"External Benchmark CAGR: {_percent(benchmark_summary.get('net_cagr'))}")
    typer.echo(
        "External Classification: "
        f"{summary['external_validation_classification']}"
    )
    typer.echo(
        "Extended Forward Paper Eligible: "
        f"{str(summary['forward_paper_eligible']).lower()}"
    )
    typer.echo("STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def decision_superiority_pre2016_external_validation_verify(
    certificate: Annotated[Path, typer.Option("--certificate")],
    require_ready: Annotated[
        bool,
        typer.Option("--require-ready"),
    ] = False,
) -> None:
    """Validate a public DSI-010 certificate and support package."""

    try:
        payload = validate_pre2016_external_validation_certificate(
            certificate,
            require_ready=require_ready,
        )
    except Pre2016ExternalValidationError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo(
        "External Classification: "
        f"{payload['external_validation_classification']}"
    )
    typer.echo("Certificate: VALID")


def _percent(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "UNKNOWN"


__all__ = [
    "register_decision_superiority_pre2016_external_validation_command",
]
