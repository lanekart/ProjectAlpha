"""Permanent CLI for DSI-005 recommendation replay retention."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.decision_superiority.recommendation_snapshot_recorder import (
    replay_snapshot_package,
    validate_snapshot_package,
)
from alpha.decision_superiority.recommendation_snapshot_retention import (
    GovernedRecommendationReplayRetentionEngine,
)
from alpha.decision_superiority.recommendation_snapshot_retention_artifacts import (
    export_replay_retention,
    validate_replay_retention_certificate,
)
from alpha.decision_superiority.recommendation_snapshot_retention_models import (
    ReplayRetentionError,
    ReplayRetentionSourcePaths,
)

DEFAULT_DSI005_OUTPUT = Path(".alpha/benchmark/dsi005_replay_retention")


def register_decision_superiority_snapshot_retention_command(
    app: typer.Typer,
) -> None:
    """Register DSI-005 execution, certificate, and snapshot commands."""

    app.command("decision-superiority-recommendation-snapshot-retention")(
        decision_superiority_recommendation_snapshot_retention
    )
    app.command("decision-superiority-recommendation-snapshot-retention-verify")(
        decision_superiority_recommendation_snapshot_retention_verify
    )
    app.command("verify-recommendation-snapshot")(verify_recommendation_snapshot)


def decision_superiority_recommendation_snapshot_retention(
    dsi004_certificate: Annotated[
        Path,
        typer.Option("--dsi004-certificate"),
    ],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DSI005_OUTPUT,
) -> None:
    """Execute the governed DSI-005 A-I chain."""

    typer.echo("DSI-005 signed DSI-004 source-chain validation")
    try:
        result = GovernedRecommendationReplayRetentionEngine().run(
            sources=ReplayRetentionSourcePaths(
                dsi004_certificate=dsi004_certificate,
                project_root=Path("."),
            )
        )
        paths = export_replay_retention(result, output)
    except (OSError, ReplayRetentionError, ValueError) as exc:
        typer.echo(f"SIGNED_EXECUTION_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    for slice_id, readiness in result.readiness.items():
        typer.echo(f"DSI-005{slice_id} Readiness: {readiness}")
    typer.echo(
        "Excluded / newly materialised / total admitted: "
        f"{result.summaries['dsi004_excluded_candidate_count']} / "
        f"{result.summaries['newly_materialised_candidate_count']} / "
        f"{result.summaries['total_admitted_candidate_count']}"
    )
    typer.echo(
        "Prospective round trips / successes: "
        f"{result.summaries['round_trip_package_count']} / "
        f"{result.summaries['round_trip_success_count']}"
    )
    typer.echo("DEFAULT_SNAPSHOT_CAPTURE_ENABLED=false")
    typer.echo("DEFAULT_RUNTIME_BEHAVIOUR_CHANGED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def decision_superiority_recommendation_snapshot_retention_verify(
    certificate: Annotated[Path, typer.Option("--certificate")],
    require_ready: Annotated[bool, typer.Option("--require-ready")] = False,
) -> None:
    """Validate one DSI-005 certificate and all bound artifacts."""

    try:
        payload = validate_replay_retention_certificate(
            certificate,
            require_ready=require_ready,
            project_root=Path("."),
        )
    except ReplayRetentionError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo("Certificate: VALID")


def verify_recommendation_snapshot(
    snapshot_package: Annotated[Path, typer.Option("--snapshot-package")],
    replay: Annotated[bool, typer.Option("--replay")] = False,
) -> None:
    """Validate and optionally replay one prospective snapshot package."""

    try:
        payload = validate_snapshot_package(snapshot_package)
        result = replay_snapshot_package(snapshot_package) if replay else None
    except ReplayRetentionError as exc:
        typer.echo(f"SNAPSHOT_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Capture ID: {payload['capture_id']}")
    typer.echo("Snapshot: VALID")
    if result is not None:
        typer.echo(f"Round Trip: {'READY' if result.ready else 'FAILED'}")


__all__ = [
    "DEFAULT_DSI005_OUTPUT",
    "decision_superiority_recommendation_snapshot_retention",
    "decision_superiority_recommendation_snapshot_retention_verify",
    "register_decision_superiority_snapshot_retention_command",
    "verify_recommendation_snapshot",
]
