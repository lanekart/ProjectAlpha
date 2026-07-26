"""Permanent CLI for DSI-006 governed forward snapshot operations."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from alpha.decision_superiority.forward_snapshot_accrual import (
    GovernedForwardSnapshotAccrualEngine,
)
from alpha.decision_superiority.forward_snapshot_artifacts import (
    export_forward_snapshot_accrual,
    validate_forward_snapshot_certificate,
)
from alpha.decision_superiority.forward_snapshot_models import (
    ForwardSnapshotError,
    ForwardSnapshotSourcePaths,
    OutcomeEventType,
)
from alpha.decision_superiority.forward_snapshot_repository import (
    ContentAddressedSnapshotRepository,
)

DEFAULT_DSI005_CERTIFICATE = Path(
    "artifacts/dsi005_acceptance/20260726T112316Z/run_a/"
    "dsi005_replay_retention_certificate.json"
)
DEFAULT_DSI006_OUTPUT = Path(".alpha/benchmark/dsi006_forward_snapshot_accrual")


def register_decision_superiority_forward_snapshot_command(
    app: typer.Typer,
) -> None:
    """Register DSI-006 capture, validation, and accrual commands."""

    app.command("decision-superiority-forward-snapshot-capture")(
        decision_superiority_forward_snapshot_capture
    )
    app.command("decision-superiority-forward-snapshot-verify")(
        decision_superiority_forward_snapshot_verify
    )
    app.command("decision-superiority-forward-repository-verify")(
        decision_superiority_forward_repository_verify
    )
    app.command("decision-superiority-forward-outcome-event")(
        decision_superiority_forward_outcome_event
    )


def decision_superiority_forward_snapshot_capture(
    session_date: Annotated[str, typer.Option("--session-date")],
    database: Annotated[Path, typer.Option("--database")],
    historical_truth_snapshots: Annotated[
        Path,
        typer.Option("--historical-truth-snapshots"),
    ],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DSI006_OUTPUT,
    dsi005_certificate: Annotated[
        Path,
        typer.Option("--dsi005-certificate"),
    ] = DEFAULT_DSI005_CERTIFICATE,
) -> None:
    """Run one explicit research-only forward capture session."""

    try:
        observed_on = date.fromisoformat(session_date)
        result = GovernedForwardSnapshotAccrualEngine().run(
            sources=ForwardSnapshotSourcePaths(
                dsi005_certificate=dsi005_certificate,
                database=database,
                historical_truth_snapshots=historical_truth_snapshots,
                capture_root=output / "repository",
                project_root=Path("."),
            ),
            session_date=observed_on,
        )
        paths = export_forward_snapshot_accrual(result, output / "certification")
    except (OSError, ForwardSnapshotError, ValueError) as exc:
        typer.echo(f"GOVERNED_FORWARD_CAPTURE_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    for slice_id, readiness in result.readiness.items():
        typer.echo(f"DSI-006{slice_id} Readiness: {readiness}")
    typer.echo(
        "Sessions / recommendations / independent candidates: "
        f"{result.summaries['capture_session_count']} / "
        f"{result.summaries['recommendation_count']} / "
        f"{result.summaries['economic_candidate_count']}"
    )
    typer.echo(
        "Completed / comparable outcomes: "
        f"{result.summaries['completed_outcome_count']} / "
        f"{result.summaries['comparable_outcome_count']}"
    )
    typer.echo("DEFAULT_SNAPSHOT_CAPTURE_ENABLED=false")
    typer.echo("PRODUCTION_SNAPSHOT_WRITES_ENABLED=false")
    typer.echo("DEFAULT_RUNTIME_BEHAVIOUR_CHANGED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output / 'certification'} ({len(paths)} files)")


def decision_superiority_forward_snapshot_verify(
    certificate: Annotated[Path, typer.Option("--certificate")],
    require_ready: Annotated[bool, typer.Option("--require-ready")] = False,
) -> None:
    """Validate one DSI-006 certificate and all bound artifacts."""

    try:
        payload = validate_forward_snapshot_certificate(
            certificate,
            require_ready=require_ready,
            project_root=Path("."),
        )
    except ForwardSnapshotError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo("Certificate: VALID")


def decision_superiority_forward_repository_verify(
    repository: Annotated[Path, typer.Option("--repository")],
) -> None:
    """Validate all immutable packages, events, and the rebuilt index."""

    try:
        inventory = ContentAddressedSnapshotRepository(repository).verify_inventory()
    except (OSError, ForwardSnapshotError, ValueError) as exc:
        typer.echo(f"REPOSITORY_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Packages: {inventory['package_count']}")
    typer.echo(f"Candidate Arms: {inventory['index_row_count']}")
    typer.echo(f"Outcome Events: {inventory['event_count']}")
    typer.echo("Repository: VALID")


def decision_superiority_forward_outcome_event(
    repository: Annotated[Path, typer.Option("--repository")],
    candidate_arm_id: Annotated[str, typer.Option("--candidate-arm-id")],
    event_type: Annotated[OutcomeEventType, typer.Option("--event-type")],
    observation_date: Annotated[str, typer.Option("--observation-date")],
    effective_date: Annotated[str, typer.Option("--effective-date")],
    source_lineage: Annotated[str, typer.Option("--source-lineage")],
    source_hash: Annotated[str, typer.Option("--source-hash")],
    completion_date: Annotated[
        str | None,
        typer.Option("--completion-date"),
    ] = None,
    predecessor_event_id: Annotated[
        str | None,
        typer.Option("--predecessor-event-id"),
    ] = None,
) -> None:
    """Append one explicitly sourced point-in-time lifecycle event."""

    try:
        event, disposition = ContentAddressedSnapshotRepository(
            repository
        ).append_outcome_event(
            candidate_arm_id=candidate_arm_id,
            event_type=event_type,
            observation_date=date.fromisoformat(observation_date),
            effective_date=date.fromisoformat(effective_date),
            completion_date=(
                None if completion_date is None else date.fromisoformat(completion_date)
            ),
            source_lineage=source_lineage,
            source_hash=source_hash,
            predecessor_event_id=predecessor_event_id,
        )
    except (OSError, ForwardSnapshotError, ValueError) as exc:
        typer.echo(f"OUTCOME_EVENT_REJECTED: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Event ID: {event.event_id}")
    typer.echo(f"Disposition: {disposition.value}")
    typer.echo("Snapshot Mutated: false")
    typer.echo("PRODUCTION_INFLUENCE=false")


__all__ = [
    "DEFAULT_DSI005_CERTIFICATE",
    "DEFAULT_DSI006_OUTPUT",
    "decision_superiority_forward_outcome_event",
    "decision_superiority_forward_repository_verify",
    "decision_superiority_forward_snapshot_capture",
    "decision_superiority_forward_snapshot_verify",
    "register_decision_superiority_forward_snapshot_command",
]
