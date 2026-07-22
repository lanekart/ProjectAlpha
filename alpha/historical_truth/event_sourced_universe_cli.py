"""CLI for HTR-009A2 event-sourced universe certification."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.event_sourced_universe_engine import (
    EventSourcedUniverseCertificationEngine,
)
from alpha.historical_truth.event_sourced_universe_exports import (
    EventSourcedUniverseArtifactExporter,
)
from alpha.historical_truth.event_sourced_universe_models import (
    MembershipCertificationState,
    SecurityEventType,
)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option,
        ) from exc


def _event_type(value: str) -> SecurityEventType:
    try:
        return SecurityEventType(value.strip().upper())
    except ValueError as exc:
        raise typer.BadParameter(
            f"unknown HTR-009A2 event type: {value}",
            param_hint="--event-type",
        ) from exc


def _membership_state(value: str) -> MembershipCertificationState:
    try:
        return MembershipCertificationState(value.strip().upper())
    except ValueError as exc:
        raise typer.BadParameter(
            f"unknown HTR-009A2 membership state: {value}",
            param_hint="--membership-state",
        ) from exc


def event_sourced_universe_certify(
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
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option("auto", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr009a2_event_sourced_universe"),
        "--output",
    ),
    symbol: list[str] = typer.Option([], "--symbol"),
    isin: list[str] = typer.Option([], "--isin"),
    year: list[int] = typer.Option([], "--year"),
    event_type: list[str] = typer.Option([], "--event-type"),
    membership_state: list[str] = typer.Option([], "--membership-state"),
    only_unresolved: bool = typer.Option(False, "--only-unresolved"),
    verify_only: bool = typer.Option(False, "--verify-only"),
    refresh_sources: bool = typer.Option(False, "--refresh-sources"),
) -> None:
    """Certify the universe from official checkpoints and effective events."""

    start_date = _date(start, "--start")
    end_date = None if end.strip().lower() == "auto" else _date(end, "--end")
    if end_date is not None and end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    if verify_only and refresh_sources:
        raise typer.BadParameter(
            "cannot be combined with --refresh-sources",
            param_hint="--verify-only",
        )
    report = EventSourcedUniverseCertificationEngine(database, root).run(
        calendar_report=calendar_report,
        start_date=start_date,
        requested_end=end_date,
        refresh_sources=refresh_sources,
        verify_only=verify_only,
        symbols=tuple(symbol),
        isins=tuple(isin),
        years=tuple(year),
        event_types=tuple(_event_type(value) for value in event_type),
        membership_states=tuple(_membership_state(value) for value in membership_state),
        only_unresolved=only_unresolved,
    )
    paths = EventSourcedUniverseArtifactExporter().export(report, output)
    print("HTR-009A2 Event-Sourced Point-in-Time Universe Certification")
    print(f"Analysis window: {report.start_date} to {report.end_date}")
    print(f"Official event sources: {report.event_summary.official_event_sources}")
    print(f"Events admitted: {report.event_summary.events_admitted}")
    print(f"Events rejected: {report.event_summary.events_rejected}")
    print(f"Governed identities: {report.identity_summary.governed_identities}")
    print(f"Provisional identities: {report.identity_summary.provisional_identities}")
    print(f"Unresolved identities: {report.identity_summary.unresolved_identities}")
    print(f"Membership intervals: {len(report.membership_intervals)}")
    print(f"Tradability intervals: {len(report.tradability_intervals)}")
    print(
        f"Certified identity-days: {report.membership_summary.certified_identity_days}"
    )
    print(
        "Unresolved identity-days: "
        f"{report.membership_summary.unresolved_identity_days}"
    )
    print(f"Checkpoint dates: {len(report.checkpoints)}")
    print(f"2026 YTD certified: {report.ytd_summary.certified}")
    print(f"Certification: {report.certification.primary_state.value}")
    for blocker in report.certification.secondary_blockers:
        print(f"Secondary blocker: {blocker.value}")
    print(f"Report SHA-256: {report.report_sha256}")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Artifacts: {output} ({len(paths)} files)")


__all__ = ["event_sourced_universe_certify"]
