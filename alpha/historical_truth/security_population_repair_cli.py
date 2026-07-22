"""CLI for HTR-010A1 population and interval repair."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Protocol

import typer

from alpha.historical_truth.security_population_repair_engine import (
    SecurityPopulationRepairEngine,
)
from alpha.historical_truth.security_population_repair_exports import (
    SecurityPopulationRepairArtifactExporter,
)
from alpha.historical_truth.security_population_repair_models import (
    InstrumentType,
    SecurityPopulationRepairReport,
    SupportState,
)


class HasIdentityKey(Protocol):
    @property
    def identity_key(self) -> str: ...


def security_population_repair(
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    htr010a_output: Path = typer.Option(
        Path("artifacts/htr010a_complete_security_dataset"),
        "--htr010a-output",
        exists=True,
        file_okay=False,
    ),
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010a1_population_interval_repair"),
        "--output",
    ),
    verify_only: bool = typer.Option(False, "--verify-only"),
    refresh_sources: bool = typer.Option(False, "--refresh-sources"),
    instrument_type: list[str] = typer.Option([], "--instrument-type"),
    series: list[str] = typer.Option([], "--series"),
    support_state: list[str] = typer.Option([], "--support-state"),
    identity_state: list[str] = typer.Option([], "--identity-state"),
    symbol: list[str] = typer.Option([], "--symbol"),
    isin: list[str] = typer.Option([], "--isin"),
    only_overlaps: bool = typer.Option(False, "--only-overlaps"),
    only_gaps: bool = typer.Option(False, "--only-gaps"),
    only_unresolved: bool = typer.Option(False, "--only-unresolved"),
    only_tier_a: bool = typer.Option(False, "--only-tier-a"),
) -> None:
    """Repair full-market population scope and identity intervals."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    if verify_only and refresh_sources:
        raise typer.BadParameter(
            "cannot be combined with --refresh-sources",
            param_hint="--verify-only",
        )
    instruments = tuple(_instrument(value) for value in instrument_type)
    supports = tuple(_support(value) for value in support_state)
    report = SecurityPopulationRepairEngine(database, root).run(
        htr010a_output=htr010a_output,
        start_date=start_date,
        end_date=end_date,
        output=output,
        refresh_sources=refresh_sources,
        verify_only=verify_only,
    )
    displayed = _filter_report(
        report,
        instruments=instruments,
        series=tuple(item.upper() for item in series),
        supports=supports,
        identity_states=tuple(item.upper() for item in identity_state),
        symbols=tuple(item.upper() for item in symbol),
        isins=tuple(item.upper() for item in isin),
        only_overlaps=only_overlaps,
        only_gaps=only_gaps,
        only_unresolved=only_unresolved,
        only_tier_a=only_tier_a,
    )
    paths = SecurityPopulationRepairArtifactExporter().export(displayed, output)
    population = report.population_summary
    repair = report.repair_summary
    print("HTR-010A1 Full-Market Population and Interval Repair")
    print(f"Analysis window: {report.start_date} to {report.end_date}")
    print(f"Corrected identities: {population.corrected_identities}")
    print(f"Tier A core equity identities: {population.tier_a_identities}")
    print(
        "Preserved unsupported identities: "
        f"{population.preserved_unsupported_identities}"
    )
    print(f"Overlaps classified: {repair.overlaps_classified}")
    print(f"Interval gaps classified: {repair.gaps_classified}")
    print(f"Certification: {report.certification.primary_state}")
    print(f"HTR-010B readiness: {report.certification.readiness_decision}")
    print("Current-universe backward projection: false")
    print("Candidate-based filtering: false")
    print("Full benchmark replays run: 0")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Report SHA-256: {report.report_sha256}")
    print(f"Artifacts: {output} ({len(paths)} files plus sidecar database)")


def _filter_report(
    report: SecurityPopulationRepairReport,
    *,
    instruments: tuple[InstrumentType, ...],
    series: tuple[str, ...],
    supports: tuple[SupportState, ...],
    identity_states: tuple[str, ...],
    symbols: tuple[str, ...],
    isins: tuple[str, ...],
    only_overlaps: bool,
    only_gaps: bool,
    only_unresolved: bool,
    only_tier_a: bool,
) -> SecurityPopulationRepairReport:
    if not any(
        (
            instruments,
            series,
            supports,
            identity_states,
            symbols,
            isins,
            only_overlaps,
            only_gaps,
            only_unresolved,
            only_tier_a,
        )
    ):
        return report
    overlap_keys = {item.identity_key for item in report.interval_overlaps}
    gap_keys = {item.identity_key for item in report.interval_gaps}
    certification = {item.identity_key: item for item in report.certification_matrix}
    selected: set[str] = set()
    for item in report.taxonomy:
        support = next(
            value.support_state
            for value in report.support_policy
            if value.identity_key == item.identity_key
            and value.symbol == item.symbol
            and value.series == item.series
        )
        state = certification[item.identity_key].certification_state.value
        if instruments and item.instrument_type not in instruments:
            continue
        if series and item.series not in series:
            continue
        if supports and support not in supports:
            continue
        if identity_states and state not in identity_states:
            continue
        if symbols and item.symbol not in symbols:
            continue
        if isins and (item.isin or "") not in isins:
            continue
        if only_overlaps and item.identity_key not in overlap_keys:
            continue
        if only_gaps and item.identity_key not in gap_keys:
            continue
        if only_unresolved and state not in {"UNRESOLVED", "CONFLICTING"}:
            continue
        if only_tier_a and support is not SupportState.TIER_A_CORE_EQUITY:
            continue
        selected.add(item.identity_key)
    return replace(
        report,
        taxonomy=_selected(report.taxonomy, selected),
        support_policy=_selected(report.support_policy, selected),
        denominator_audit=_selected(report.denominator_audit, selected),
        interval_overlaps=_selected(report.interval_overlaps, selected),
        interval_repairs=_selected(report.interval_repairs, selected),
        interval_gaps=_selected(report.interval_gaps, selected),
        listing_boundaries=_selected(report.listing_boundaries, selected),
        termination_boundaries=_selected(report.termination_boundaries, selected),
        certification_matrix=_selected(report.certification_matrix, selected),
    )


def _selected[T: HasIdentityKey](
    values: tuple[T, ...], selected: set[str]
) -> tuple[T, ...]:
    return tuple(item for item in values if item.identity_key in selected)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option,
        ) from exc


def _instrument(value: str) -> InstrumentType:
    try:
        return InstrumentType(value.upper())
    except ValueError as exc:
        raise typer.BadParameter(
            f"unknown instrument type: {value}",
            param_hint="--instrument-type",
        ) from exc


def _support(value: str) -> SupportState:
    try:
        return SupportState(value.upper())
    except ValueError as exc:
        raise typer.BadParameter(
            f"unknown support state: {value}",
            param_hint="--support-state",
        ) from exc


__all__ = ["security_population_repair"]
