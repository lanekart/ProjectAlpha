"""CLI for the governed DSI-001 gate value audit with signed B5/B7 orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.decision_superiority.input_contract import GovernedInputContractError
from alpha.decision_superiority.signed_audit import GovernedSignedGateValueAudit

DEFAULT_DSI001_OUTPUT = Path(".alpha/benchmark/dsi001_gate_value_audit")


def register_decision_superiority_gate_value_command(app: typer.Typer) -> None:
    app.command("decision-superiority-gate-value")(decision_superiority_gate_value)


def decision_superiority_gate_value(
    b5_certificate: Annotated[Path, typer.Option("--b5-certificate")],
    b7_certificate: Annotated[Path, typer.Option("--b7-certificate")],
    candidate_gate_forensics: Annotated[
        Path, typer.Option("--candidate-gate-forensics")
    ],
    gate_event_ledger: Annotated[Path, typer.Option("--gate-event-ledger")],
    outcome_coverage_ledger: Annotated[Path, typer.Option("--outcome-coverage-ledger")],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DSI001_OUTPUT,
) -> None:
    """Run DSI-001 audit exclusively through signed B5/B7 orchestration."""

    try:
        result = GovernedSignedGateValueAudit().run(
            b5_certificate=b5_certificate,
            b7_certificate=b7_certificate,
            candidate_gate_forensics=candidate_gate_forensics,
            gate_event_ledger=gate_event_ledger,
            outcome_coverage_ledger=outcome_coverage_ledger,
            output=output,
        )
    except GovernedInputContractError as exc:
        typer.echo(f"SIGNED_EXECUTION_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc

    report = result.report
    values = report["gate_value_summary"]
    positive = [
        row for row in values if row["conclusion"] == "GATE_ADDS_MEASURABLE_VALUE"
    ]
    negative = [
        row for row in values if row["conclusion"] == "GATE_DESTROYS_MEASURABLE_VALUE"
    ]
    typer.echo("DSI-001 Governed Decision Superiority and Gate Value Audit")
    typer.echo(f"Readiness: {report['readiness_decision']}")
    typer.echo(f"Candidates audited: {report['candidate_count']}")
    typer.echo(f"Resolved outcomes: {report['resolved_outcome_count']}")
    typer.echo(f"Gate count: {report['gate_count']}")
    typer.echo(f"Profitable rejections: {report['profitable_rejection_count']}")
    typer.echo(f"Avoided losses: {report['avoided_loss_count']}")
    typer.echo(
        "Highest positive gate value: "
        + (
            str(max(positive, key=lambda row: row["net_gate_value"])["gate_code"])
            if positive
            else "NONE"
        )
    )
    typer.echo(
        "Highest negative gate value: "
        + (
            str(min(negative, key=lambda row: row["net_gate_value"])["gate_code"])
            if negative
            else "NONE"
        )
    )
    typer.echo(f"Report SHA256: {report['report_sha256']}")
    typer.echo(
        f"B5 Contract: {report['upstream_certificates']['b5']['contract_version']}"
    )
    typer.echo(
        f"B7 Contract: {report['upstream_certificates']['b7']['contract_version']}"
    )
    typer.echo(f"Source Contract Verified: {report['source_contract_verified']}")
    typer.echo("RECOMMENDATION_INFLUENCE=false")
    typer.echo("EXECUTION_INFLUENCE=false")
    typer.echo("ACTIVE_REPLAY_INTEGRATION=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(result.paths)} files)")


__all__ = [
    "DEFAULT_DSI001_OUTPUT",
    "decision_superiority_gate_value",
    "register_decision_superiority_gate_value_command",
]
