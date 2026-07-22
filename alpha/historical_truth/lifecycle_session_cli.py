"""CLI for HTR-010A2 lifecycle/session certification."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.lifecycle_session_engine import (
    LifecycleSessionSemanticsEngine,
)
from alpha.historical_truth.lifecycle_session_exports import (
    LifecycleSessionArtifactExporter,
)


def lifecycle_session_semantics_certify(
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
    htr010a1_output: Path = typer.Option(
        Path("artifacts/htr010a1_population_interval_repair"),
        "--htr010a1-output",
        exists=True,
        file_okay=False,
    ),
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010a2_lifecycle_session_semantics"), "--output"
    ),
    refresh_sources: bool = typer.Option(False, "--refresh-sources"),
    verify_only: bool = typer.Option(False, "--verify-only"),
    symbol: list[str] = typer.Option([], "--symbol"),
    isin: list[str] = typer.Option([], "--isin"),
    support_tier: list[str] = typer.Option([], "--support-tier"),
    primary_state: list[str] = typer.Option([], "--primary-state"),
    issue_flag: list[str] = typer.Option([], "--issue-flag"),
    source_family: list[str] = typer.Option([], "--source-family"),
    only_overlaps: bool = typer.Option(False, "--only-overlaps"),
    only_gaps: bool = typer.Option(False, "--only-gaps"),
    only_missing_sessions: bool = typer.Option(False, "--only-missing-sessions"),
    only_tier_a: bool = typer.Option(False, "--only-tier-a"),
    only_unresolved: bool = typer.Option(False, "--only-unresolved"),
) -> None:
    """Certify canonical lifecycle and official row semantics."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    if verify_only and refresh_sources:
        raise typer.BadParameter(
            "cannot be combined with --refresh-sources", param_hint="--verify-only"
        )
    report = LifecycleSessionSemanticsEngine(database, root).run(
        htr010a_output=htr010a_output,
        htr010a1_output=htr010a1_output,
        start_date=start_date,
        end_date=end_date,
        output=output,
        refresh_sources=refresh_sources,
        verify_only=verify_only,
    )
    paths = LifecycleSessionArtifactExporter().export(report, output)
    selected = _selected_count(
        report,
        symbol,
        isin,
        support_tier,
        primary_state,
        issue_flag,
        source_family,
        only_overlaps,
        only_gaps,
        only_missing_sessions,
        only_tier_a,
        only_unresolved,
    )
    print("HTR-010A2 Lifecycle and Security-Session Semantics")
    print(f"Identities: {len(report.primary_certifications):,}")
    tier_a = sum(
        row.support_state == "TIER_A_CORE_EQUITY"
        for row in report.primary_certifications
    )
    print(f"Tier A: {tier_a:,}")
    print(
        f"Duplicate source records classified: {len(report.duplicate_source_records):,}"
    )
    print(f"Canonical observations: {len(report.canonical_observations):,}")
    print(f"Remaining overlaps: {len(report.remaining_overlaps):,}")
    print(f"Remaining gaps: {len(report.remaining_gaps):,}")
    print(f"Diagnostic records selected: {selected:,}")
    print(f"HTR-010B readiness: {report.readiness.state.value}")
    print(f"Report SHA256: {report.report_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")


def _selected_count(
    report: object,
    symbol: list[str],
    isin: list[str],
    support: list[str],
    primary: list[str],
    issue: list[str],
    source: list[str],
    overlaps: bool,
    gaps: bool,
    missing: bool,
    tier_a: bool,
    unresolved: bool,
) -> int:
    del symbol, isin, support, primary, issue, source, tier_a, unresolved
    from alpha.historical_truth.lifecycle_session_models import LifecycleSessionReport

    if not isinstance(report, LifecycleSessionReport):
        return 0
    if overlaps:
        return len(report.remaining_overlaps)
    if gaps:
        return len(report.remaining_gaps)
    if missing:
        return len(report.missing_session_reclassification)
    return len(report.primary_certifications)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must use YYYY-MM-DD", param_hint=option) from exc


__all__ = ["lifecycle_session_semantics_certify"]
