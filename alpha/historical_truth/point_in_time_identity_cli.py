"""Command-line entry point for HTR-009A identity certification."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.point_in_time_identity_engine import (
    PointInTimeIdentityCertificationEngine,
)
from alpha.historical_truth.point_in_time_identity_exports import (
    PointInTimeIdentityArtifactExporter,
)
from alpha.historical_truth.point_in_time_identity_models import (
    IdentityState,
    MembershipState,
)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option,
        ) from exc


def _identity_state(value: str) -> IdentityState:
    try:
        return IdentityState(value.strip().upper())
    except ValueError as exc:
        raise typer.BadParameter(
            f"unknown HTR-009A identity state: {value}",
            param_hint="--identity-state",
        ) from exc


def _membership_state(value: str) -> MembershipState:
    try:
        return MembershipState(value.strip().upper())
    except ValueError as exc:
        raise typer.BadParameter(
            f"unknown HTR-009A membership state: {value}",
            param_hint="--membership-state",
        ) from exc


def point_in_time_universe_certify(
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
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option("auto", "--end"),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    output: Path = typer.Option(
        Path("artifacts/htr009a_point_in_time_universe"),
        "--output",
    ),
    symbol: list[str] = typer.Option([], "--symbol"),
    isin: list[str] = typer.Option([], "--isin"),
    year: list[int] = typer.Option([], "--year"),
    identity_state: list[str] = typer.Option([], "--identity-state"),
    membership_state: list[str] = typer.Option([], "--membership-state"),
    only_unresolved: bool = typer.Option(False, "--only-unresolved"),
    verify_only: bool = typer.Option(False, "--verify-only"),
    refresh_sources: bool = typer.Option(False, "--refresh-sources"),
) -> None:
    """Certify identity and universe evidence without production influence."""

    start_date = _date(start, "--start")
    end_date = None if end.strip().lower() == "auto" else _date(end, "--end")
    if end_date is not None and end_date < start_date:
        raise typer.BadParameter(
            "must be on or after --start",
            param_hint="--end",
        )
    if verify_only and refresh_sources:
        raise typer.BadParameter(
            "cannot be combined with --refresh-sources",
            param_hint="--verify-only",
        )
    engine = PointInTimeIdentityCertificationEngine(
        database,
        snapshot_root,
        root,
    )
    report = engine.run(
        calendar_report=calendar_report,
        start_date=start_date,
        requested_end=end_date,
        refresh_sources=refresh_sources,
        verify_only=verify_only,
        symbols=tuple(symbol),
        isins=tuple(isin),
        years=tuple(year),
        identity_states=tuple(_identity_state(value) for value in identity_state),
        membership_states=tuple(_membership_state(value) for value in membership_state),
        only_unresolved=only_unresolved,
    )
    paths = PointInTimeIdentityArtifactExporter().export(report, output)
    boundaries = report.time_boundaries
    governed = sum(
        item.identity_state is IdentityState.GOVERNED_IDENTITY
        for item in report.identities
    )
    provisional = sum(
        item.identity_state is IdentityState.PROVISIONAL_IDENTITY
        for item in report.identities
    )
    print("HTR-009A Point-in-Time Universe and Identity Certification")
    print(f"Analysis window: {report.start_date} to {report.end_date}")
    print(f"Latest calendar date: {boundaries.latest_calendar_date or 'unavailable'}")
    print(f"Latest canonical date: {boundaries.latest_canonical_date or 'unavailable'}")
    print(f"Latest snapshot date: {boundaries.latest_snapshot_date or 'unavailable'}")
    print(
        "Latest official master date: "
        f"{boundaries.latest_official_master_date or 'unavailable'}"
    )
    print(
        "Latest identity-supported date: "
        f"{boundaries.latest_identity_supported_date or 'unavailable'}"
    )
    print(
        "Final common certified date: "
        f"{boundaries.final_common_as_of_date or 'unavailable'}"
    )
    print(f"Observed identities: {len(report.identities)}")
    print(f"Governed identities: {governed}")
    print(f"Provisional identities: {provisional}")
    print(f"Symbol-reuse cases: {len(report.symbol_reuse)}")
    print(f"Certification: {report.certification.primary_state.value}")
    for blocker in report.certification.secondary_blockers:
        print(f"Secondary blocker: {blocker.value}")
    print(f"Report SHA-256: {report.report_sha256}")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Artifacts: {output} ({len(paths)} files)")


__all__ = ["point_in_time_universe_certify"]
