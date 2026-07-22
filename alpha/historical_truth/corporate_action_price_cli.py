"""CLI for HTR-009B corporate-action and price-basis certification."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.corporate_action_price_engine import (
    CorporateActionPriceCertificationEngine,
)
from alpha.historical_truth.corporate_action_price_exports import (
    CorporateActionPriceArtifactExporter,
)
from alpha.historical_truth.corporate_action_price_models import (
    CorporateActionType,
    PriceBasisState,
)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option,
        ) from exc


def _action_type(value: str) -> CorporateActionType:
    try:
        return CorporateActionType(value.strip().upper())
    except ValueError as exc:
        raise typer.BadParameter(
            f"unknown corporate-action type: {value}",
            param_hint="--action-type",
        ) from exc


def _price_basis_state(value: str) -> PriceBasisState:
    try:
        return PriceBasisState(value.strip().upper())
    except ValueError as exc:
        raise typer.BadParameter(
            f"unknown price-basis state: {value}",
            param_hint="--price-basis-state",
        ) from exc


def corporate_action_price_certify(
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
        Path("artifacts/htr009b_corporate_action_price_continuity"),
        "--output",
    ),
    symbol: list[str] = typer.Option([], "--symbol"),
    isin: list[str] = typer.Option([], "--isin"),
    year: list[int] = typer.Option([], "--year"),
    action_type: list[str] = typer.Option([], "--action-type"),
    price_basis_state: list[str] = typer.Option([], "--price-basis-state"),
    only_unresolved: bool = typer.Option(False, "--only-unresolved"),
    only_candidate_exposed: bool = typer.Option(
        False,
        "--only-candidate-exposed",
    ),
    verify_only: bool = typer.Option(False, "--verify-only"),
    refresh_sources: bool = typer.Option(False, "--refresh-sources"),
) -> None:
    """Certify official corporate actions and governed price continuity."""

    start_date = _date(start, "--start")
    end_date = None if end.strip().lower() == "auto" else _date(end, "--end")
    if end_date is not None and end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    if verify_only and refresh_sources:
        raise typer.BadParameter(
            "cannot be combined with --refresh-sources",
            param_hint="--verify-only",
        )
    report = CorporateActionPriceCertificationEngine(database, root).run(
        calendar_report=calendar_report,
        start_date=start_date,
        requested_end=end_date,
        refresh_sources=refresh_sources,
        verify_only=verify_only,
        symbols=tuple(symbol),
        isins=tuple(isin),
        years=tuple(year),
        action_types=tuple(_action_type(value) for value in action_type),
        price_basis_states=tuple(
            _price_basis_state(value) for value in price_basis_state
        ),
        only_unresolved=only_unresolved,
        only_candidate_exposed=only_candidate_exposed,
    )
    paths = CorporateActionPriceArtifactExporter().export(report, output)
    print("HTR-009B Corporate Actions and Price-Basis Continuity")
    print(f"Analysis window: {report.start_date} to {report.end_date}")
    print(f"Sources attempted: {report.source_summary.attempted}")
    print(f"Sources acquired: {report.source_summary.acquired}")
    print(f"Sources reused: {report.source_summary.reused}")
    print(f"Sources failed: {report.source_summary.failed}")
    print(f"Events admitted: {report.event_summary.admitted}")
    print(f"Events rejected: {report.event_summary.rejected}")
    known_factors = report.factor_summary.known + report.factor_summary.derived
    print(f"Known/derived factors: {known_factors}")
    print(f"Unknown factors: {report.factor_summary.unknown}")
    print(f"Raw candle rows: {report.price_basis_summary.raw_candle_rows}")
    print(f"Derived adjusted rows: {report.price_basis_summary.adjusted_candle_rows}")
    print(f"Raw discontinuities: {report.continuity_summary.raw_discontinuities}")
    print(
        "Adjusted discontinuities: "
        f"{report.continuity_summary.adjusted_discontinuities}"
    )
    print(f"Technical candidates: {report.candidate_exposure_summary.technical}")
    print(
        "Candidate-level linkage: "
        f"{report.candidate_exposure_summary.linkage_available}"
    )
    print(f"2026 YTD certified: {report.cutoffs.ytd_2026_certified}")
    print(f"Certification: {report.certification.primary_state.value}")
    for blocker in report.certification.secondary_blockers:
        print(f"Secondary blocker: {blocker.value}")
    print(f"Report SHA-256: {report.report_sha256}")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Artifacts: {output} ({len(paths)} files)")


__all__ = ["corporate_action_price_certify"]
