"""CLI for HTR-010A complete historical security certification."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.complete_security_dataset_engine import (
    CompleteSecurityDatasetCertificationEngine,
)
from alpha.historical_truth.complete_security_dataset_exports import (
    CompleteSecurityDatasetArtifactExporter,
)
from alpha.historical_truth.complete_security_dataset_models import (
    IdentityState,
    MembershipState,
)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD", param_hint=option
        ) from exc


def _identity_state(value: str) -> IdentityState:
    try:
        return IdentityState(value.strip().upper())
    except ValueError as exc:
        raise typer.BadParameter(
            f"unknown HTR-010A identity state: {value}",
            param_hint="--identity-state",
        ) from exc


def _membership_state(value: str) -> MembershipState:
    try:
        return MembershipState(value.strip().upper())
    except ValueError as exc:
        raise typer.BadParameter(
            f"unknown HTR-010A membership state: {value}",
            param_hint="--membership-state",
        ) from exc


def complete_security_dataset_certify(
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
    snapshot_root: Path = typer.Option(Path("alpha_data/snapshots"), "--snapshot-root"),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option("auto", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010a_complete_security_dataset"), "--output"
    ),
    symbol: list[str] = typer.Option([], "--symbol"),
    isin: list[str] = typer.Option([], "--isin"),
    year: list[int] = typer.Option([], "--year"),
    identity_state: list[str] = typer.Option([], "--identity-state"),
    membership_state: list[str] = typer.Option([], "--membership-state"),
    only_unresolved: bool = typer.Option(False, "--only-unresolved"),
    only_conflicting: bool = typer.Option(False, "--only-conflicting"),
    verify_only: bool = typer.Option(False, "--verify-only"),
    refresh_sources: bool = typer.Option(False, "--refresh-sources"),
) -> None:
    """Build and certify the candidate-independent historical NSE CM dataset."""

    start_date = _date(start, "--start")
    end_date = None if end.strip().lower() == "auto" else _date(end, "--end")
    if end_date is not None and end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    if verify_only and refresh_sources:
        raise typer.BadParameter(
            "cannot be combined with --refresh-sources", param_hint="--verify-only"
        )
    report = CompleteSecurityDatasetCertificationEngine(database, root).run(
        calendar_report=calendar_report,
        snapshot_root=snapshot_root,
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
        only_conflicting=only_conflicting,
    )
    paths = CompleteSecurityDatasetArtifactExporter().export(report, output)
    population = report.population_summary
    membership = report.membership_summary
    candles = report.candle_summary
    print("HTR-010A Complete Historical Security Identity and Membership Dataset")
    print(f"Analysis window: {report.start_date} to {report.end_date}")
    print(f"Raw symbols: {population.raw_symbols}")
    print(f"Symbol-series pairs: {population.symbol_series_pairs}")
    print(f"Valid ISINs: {population.isins}")
    print(f"Governed identities: {population.governed_identities}")
    print(f"Provisional identities: {population.provisional_identities}")
    print(f"Unresolved identities: {population.unresolved_identities}")
    print(f"Membership intervals: {membership.membership_intervals}")
    print(f"Tradability intervals: {membership.tradability_intervals}")
    print(f"Canonical rows reconciled: {candles.total_rows}")
    print(f"Certified candle rows: {candles.certified_rows}")
    print(f"Unresolved candle rows: {candles.unresolved_rows}")
    print(f"2026 YTD state: {report.ytd_summary.final_state}")
    print(f"Certification: {report.certification.primary_state.value}")
    for blocker in report.certification.secondary_blockers:
        print(f"Secondary blocker: {blocker.value}")
    print("Candidate-shaped acquisition: false")
    print("Full benchmark replays run: 0")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Report SHA-256: {report.report_sha256}")
    print(f"Artifacts: {output} ({len(paths)} files)")


__all__ = ["complete_security_dataset_certify"]
