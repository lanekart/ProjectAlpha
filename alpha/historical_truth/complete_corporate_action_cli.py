"""CLI for HTR-010B corporate-action completion."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.complete_corporate_action_engine import (
    CompleteCorporateActionDatasetEngine,
)
from alpha.historical_truth.complete_corporate_action_exports import (
    CompleteCorporateActionArtifactExporter,
)


def complete_corporate_action_dataset(
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    htr010a3_output: Path = typer.Option(
        Path("artifacts/htr010a3_tier_a_foundation_readiness"),
        "--htr010a3-output",
        exists=True,
        file_okay=False,
    ),
    htr009a2_output: Path | None = typer.Option(
        None,
        "--htr009a2-output",
        exists=True,
        file_okay=False,
        help="Optional signed HTR-009A2 output for legacy missing-ISIN bridges.",
    ),
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010b_complete_corporate_action_dataset"), "--output"
    ),
    refresh_sources: bool = typer.Option(False, "--refresh-sources"),
    verify_only: bool = typer.Option(False, "--verify-only"),
    symbol: list[str] = typer.Option([], "--symbol"),
    isin: list[str] = typer.Option([], "--isin"),
    action_type: list[str] = typer.Option([], "--action-type"),
    factor_state: list[str] = typer.Option([], "--factor-state"),
    price_basis_state: list[str] = typer.Option([], "--price-basis-state"),
    certification_state: list[str] = typer.Option([], "--certification-state"),
    year: list[int] = typer.Option([], "--year"),
    only_tier_a: bool = typer.Option(False, "--only-tier-a"),
    only_unresolved: bool = typer.Option(False, "--only-unresolved"),
    only_conflicting: bool = typer.Option(False, "--only-conflicting"),
    only_mixed_basis: bool = typer.Option(False, "--only-mixed-basis"),
    only_adjustment_required: bool = typer.Option(False, "--only-adjustment-required"),
) -> None:
    """Build the candidate-independent Tier A corporate-action evidence set."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    if refresh_sources and verify_only:
        raise typer.BadParameter(
            "cannot be combined with --refresh-sources", param_hint="--verify-only"
        )
    report = CompleteCorporateActionDatasetEngine(database, root).run(
        htr010a3_output=htr010a3_output,
        htr009a2_output=htr009a2_output,
        start_date=start_date,
        end_date=end_date,
        output=output,
        refresh_sources=refresh_sources,
        verify_only=verify_only,
    )
    paths = CompleteCorporateActionArtifactExporter().export(report, output)
    selected = _selected_count(
        report.canonical_events,
        report.adjustment_factors,
        report.price_basis_intervals,
        report.identity_coverage_matrix,
        symbol,
        isin,
        action_type,
        factor_state,
        price_basis_state,
        certification_state,
        year,
        only_tier_a,
        only_unresolved,
        only_conflicting,
        only_mixed_basis,
        only_adjustment_required,
    )
    print("HTR-010B Complete Tier A Corporate-Action Dataset")
    print(f"Tier A identities: {len(report.identity_coverage_matrix):,}")
    print(f"Raw official records: {len(report.raw_event_census):,}")
    print(f"Canonical events: {len(report.canonical_events):,}")
    print(f"Adjustment factors: {len(report.adjustment_factors):,}")
    print(f"Diagnostic records selected: {selected:,}")
    print(f"Replay readiness: {report.replay_readiness['state']}")
    print(f"Report SHA256: {report.report_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")


def _selected_count(
    events: tuple[dict[str, object], ...],
    factors: tuple[dict[str, object], ...],
    intervals: tuple[dict[str, object], ...],
    coverage: tuple[dict[str, object], ...],
    symbols: list[str],
    isins: list[str],
    action_types: list[str],
    factor_states: list[str],
    basis_states: list[str],
    certification_states: list[str],
    years: list[int],
    only_tier_a: bool,
    only_unresolved: bool,
    only_conflicting: bool,
    only_mixed: bool,
    only_required: bool,
) -> int:
    del only_tier_a
    if factor_states:
        return sum(str(row["factor_state"]) in factor_states for row in factors)
    if basis_states or only_mixed:
        wanted = set(basis_states)
        if only_mixed:
            wanted.add("MIXED_PRICE_BASIS")
        return sum(str(row["price_basis_state"]) in wanted for row in intervals)
    if certification_states:
        return sum(
            str(row["certification_state"]) in certification_states for row in coverage
        )
    selected = events
    if symbols:
        wanted_symbols = {item.upper() for item in symbols}
        selected = tuple(
            row for row in selected if str(row["symbol"]).upper() in wanted_symbols
        )
    if isins:
        wanted_isins = {item.upper() for item in isins}
        selected = tuple(
            row for row in selected if str(row["isin"]).upper() in wanted_isins
        )
    if action_types:
        selected = tuple(
            row for row in selected if str(row["action_type"]) in action_types
        )
    if years:
        selected = tuple(
            row for row in selected if int(str(row["effective_date"])[:4]) in years
        )
    if only_unresolved:
        selected = tuple(
            row
            for row in selected
            if "UNKNOWN" in str(row["factor_state"])
            or "UNRESOLVED" in str(row["admission_state"])
        )
    if only_conflicting:
        selected = tuple(
            row
            for row in selected
            if "CONFLICT" in str(row["factor_state"])
            or "CONFLICT" in str(row["admission_state"])
        )
    if only_required:
        selected = tuple(row for row in selected if row["price_adjustment_required"])
    return len(selected)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must use YYYY-MM-DD", param_hint=option) from exc


__all__ = ["complete_corporate_action_dataset"]
