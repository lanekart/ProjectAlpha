"""Command-line entry point for HTR-008 replay eligibility certification."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.replay_eligibility_exports import (
    ReplayEligibilityArtifactExporter,
)
from alpha.historical_truth.replay_eligibility_integrity import (
    ReplayEligibilityIntegrityEngine,
)
from alpha.historical_truth.replay_eligibility_models import (
    CANONICAL_MINIMUM_HISTORY_SESSIONS,
    EligibilityAuditPolicy,
    ReplayReadinessClassification,
)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option,
        ) from exc


def _classification(value: str) -> ReplayReadinessClassification:
    try:
        return ReplayReadinessClassification(value.strip().upper())
    except ValueError as exc:
        raise typer.BadParameter(
            f"unknown HTR-008 classification: {value}",
            param_hint="--classification",
        ) from exc


def replay_eligibility_integrity_audit(
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    calendar_report: Path = typer.Option(
        ...,
        "--calendar-report",
        exists=True,
        dir_okay=False,
    ),
    snapshot_root: Path = typer.Option(
        Path("alpha_data/snapshots"),
        "--snapshot-root",
        exists=True,
        file_okay=False,
    ),
    benchmark_output: Path = typer.Option(
        ...,
        "--benchmark-output",
        exists=True,
        file_okay=False,
    ),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    minimum_history_sessions: int = typer.Option(
        CANONICAL_MINIMUM_HISTORY_SESSIONS,
        "--minimum-history-sessions",
        min=1,
    ),
    output: Path = typer.Option(
        Path("artifacts/htr008_replay_eligibility_integrity"),
        "--output",
    ),
    symbol: list[str] = typer.Option([], "--symbol"),
    isin: list[str] = typer.Option([], "--isin"),
    year: list[int] = typer.Option([], "--year"),
    classification: list[str] = typer.Option([], "--classification"),
    issue_code: list[str] = typer.Option([], "--issue-code"),
    only_not_ready: bool = typer.Option(False, "--only-not-ready"),
) -> None:
    """Certify replay eligibility without changing benchmark behavior."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter(
            "must be on or before --end",
            param_hint="--start",
        )
    if minimum_history_sessions != CANONICAL_MINIMUM_HISTORY_SESSIONS:
        raise typer.BadParameter(
            "HTR-008 preserves the canonical 200-session threshold",
            param_hint="--minimum-history-sessions",
        )
    engine = ReplayEligibilityIntegrityEngine(
        database,
        snapshot_root,
        policy=EligibilityAuditPolicy(
            minimum_history_sessions=minimum_history_sessions
        ),
    )
    report = engine.run(
        calendar_report=calendar_report,
        benchmark_output=benchmark_output,
        start_date=start_date,
        end_date=end_date,
        symbols=tuple(symbol),
        isins=tuple(isin),
        years=tuple(year),
        classifications=tuple(_classification(value) for value in classification),
        issue_codes=tuple(issue_code),
        only_not_ready=only_not_ready,
    )
    paths = ReplayEligibilityArtifactExporter().export(report, output)
    print("HTR-008 Replay Eligibility Integrity")
    print(f"Observed identities: {report.depth.identity_count}")
    print(f"Governed identities: {report.population.governed_identities}")
    print(f"Identities with 200 valid sessions: {report.depth.at_least_200}")
    print(
        "Replay-ready identities: "
        f"{report.reconciliation.final_replay_ready_identities}"
    )
    print(
        "Replay-ready security-days: "
        f"{report.reconciliation.final_replay_ready_security_days}"
    )
    print(f"Certification: {report.certification.primary_state.value}")
    for blocker in report.certification.secondary_blockers:
        print(f"Secondary blocker: {blocker.value}")
    print(f"Report SHA-256: {report.report_sha256}")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Artifacts: {output} ({len(paths)} files)")


__all__ = ["replay_eligibility_integrity_audit"]
