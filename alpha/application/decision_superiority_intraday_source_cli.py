"""Permanent CLI for governed DSI-013 intraday source certification."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from alpha.decision_superiority.intraday_execution_models import (
    IntradayExecutionError,
)
from alpha.decision_superiority.intraday_source_artifacts import (
    validate_intraday_source_certificate,
)
from alpha.decision_superiority.intraday_source_runner import (
    IntradaySourceCertificationRunner,
)

DEFAULT_DSI013_CACHE = Path(".alpha/intraday/dsi013_source_cache")
DEFAULT_DSI013_SOURCE_OUTPUT = Path(
    ".alpha/benchmark/dsi013_intraday_source_certification"
)


def register_decision_superiority_intraday_source_command(
    app: typer.Typer,
) -> None:
    """Register the DSI-013 source-certification runner and verifier."""

    app.command("decision-superiority-intraday-source-certify")(
        decision_superiority_intraday_source_certify
    )
    app.command("decision-superiority-intraday-source-verify")(
        decision_superiority_intraday_source_verify
    )


def decision_superiority_intraday_source_certify(
    dsi009_certificate: Annotated[
        Path,
        typer.Option("--dsi009-certificate"),
    ],
    instrument_json: Annotated[
        Path,
        typer.Option("--instrument-json"),
    ],
    daily_reference_csv: Annotated[
        Path,
        typer.Option("--daily-reference-csv"),
    ],
    cache_root: Annotated[
        Path,
        typer.Option("--cache-root"),
    ] = DEFAULT_DSI013_CACHE,
    output: Annotated[
        Path,
        typer.Option("--output"),
    ] = DEFAULT_DSI013_SOURCE_OUTPUT,
) -> None:
    """Certify candidate-bounded five-minute source evidence fail-closed."""

    try:
        result, paths = IntradaySourceCertificationRunner().run(
            source_commit=_git_head(Path(".")),
            dsi009_certificate=dsi009_certificate,
            instrument_json=instrument_json,
            daily_reference_csv=daily_reference_csv,
            cache_root=cache_root,
            output=output,
            access_token=os.environ.get("UPSTOX_ACCESS_TOKEN", ""),
        )
    except (OSError, IntradayExecutionError, ValueError) as exc:
        typer.echo(f"GOVERNED_INTRADAY_SOURCE_CERTIFICATION_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Readiness: {result.readiness.value}")
    typer.echo(f"Candidates: {result.summaries['candidate_count']}")
    typer.echo(f"Unique Requests: {result.summaries['request_count']}")
    typer.echo(f"Admitted Requests: {result.summaries['admitted_request_count']}")
    typer.echo(f"Identity Failures: {result.summaries['identity_failure_count']}")
    typer.echo(
        "Source-Unavailable Requests: "
        f"{result.summaries['source_unavailable_count']}"
    )
    typer.echo(
        "Session-Integrity Failures: "
        f"{result.summaries['session_failure_count']}"
    )
    typer.echo(
        "Daily-Reconciliation Failures: "
        f"{result.summaries['reconciliation_failure_count']}"
    )
    typer.echo("VALIDATED_STRATEGY=false")
    typer.echo("INTRADAY_LIVE_TRADING_ENABLED=false")
    typer.echo("AUTOMATIC_STRATEGY_PROMOTION_ENABLED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def decision_superiority_intraday_source_verify(
    certificate: Annotated[Path, typer.Option("--certificate")],
    require_ready: Annotated[
        bool,
        typer.Option("--require-ready"),
    ] = False,
) -> None:
    """Validate a public DSI-013 source certificate and support package."""

    try:
        payload = validate_intraday_source_certificate(
            certificate,
            require_ready=require_ready,
        )
    except IntradayExecutionError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo("Validated Strategy: false")
    typer.echo("Intraday Live Trading: false")
    typer.echo("Certificate: VALID")


def _git_head(project_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise IntradayExecutionError("DSI013_SOURCE_COMMIT_UNAVAILABLE") from exc


__all__ = [
    "register_decision_superiority_intraday_source_command",
]
