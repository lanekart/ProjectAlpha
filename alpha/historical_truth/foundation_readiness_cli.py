"""CLI for HTR-010A3 Tier A foundation readiness."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.foundation_readiness_engine import (
    TierAFoundationReadinessEngine,
)
from alpha.historical_truth.foundation_readiness_exports import (
    FoundationReadinessArtifactExporter,
)


def tier_a_foundation_readiness(
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
    htr010a2_output: Path = typer.Option(
        Path("artifacts/htr010a2_lifecycle_session_semantics"),
        "--htr010a2-output",
        exists=True,
        file_okay=False,
    ),
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010a3_tier_a_foundation_readiness"), "--output"
    ),
    refresh_sources: bool = typer.Option(False, "--refresh-sources"),
    verify_only: bool = typer.Option(False, "--verify-only"),
    symbol: list[str] = typer.Option([], "--symbol"),
    isin: list[str] = typer.Option([], "--isin"),
    conflict_type: list[str] = typer.Option([], "--conflict-type"),
    resolution_state: list[str] = typer.Option([], "--resolution-state"),
    join_readiness: list[str] = typer.Option([], "--join-readiness"),
    only_tier_a: bool = typer.Option(False, "--only-tier-a"),
    only_blocking: bool = typer.Option(False, "--only-blocking"),
    only_quarantined: bool = typer.Option(False, "--only-quarantined"),
    only_2026_differences: bool = typer.Option(False, "--only-2026-differences"),
) -> None:
    """Certify Tier A identity closure and corporate-action join readiness."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    if refresh_sources and verify_only:
        raise typer.BadParameter(
            "cannot be combined with --refresh-sources", param_hint="--verify-only"
        )
    report = TierAFoundationReadinessEngine(database, root).run(
        htr010a_output=htr010a_output,
        htr010a1_output=htr010a1_output,
        htr010a2_output=htr010a2_output,
        start_date=start_date,
        end_date=end_date,
        output=output,
        refresh_sources=refresh_sources,
        verify_only=verify_only,
    )
    paths = FoundationReadinessArtifactExporter().export(report, output)
    selected = _selected_count(
        report,
        symbol,
        isin,
        conflict_type,
        resolution_state,
        join_readiness,
        only_tier_a,
        only_blocking,
        only_quarantined,
        only_2026_differences,
    )
    print("HTR-010A3 Tier A Historical Foundation Readiness")
    print(f"Conflict case files: {len(report.conflict_cases)}")
    blocking_count = sum(row.blocking for row in report.conflict_resolutions)
    print(f"Blocking conflicts: {blocking_count}")
    print(f"Tier A gaps classified: {len(report.gap_resolutions)}")
    print(f"2026 discrepancies treated: {len(report.discrepancies_2026)}")
    print(f"Join population: {len(report.join_readiness):,}")
    print(f"Quarantined: {len(report.quarantined_identities)}")
    print(f"Diagnostic records selected: {selected:,}")
    print(f"Readiness: {report.readiness.state.value}")
    print(f"Report SHA256: {report.report_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")


def _selected_count(
    report: object,
    symbol: list[str],
    isin: list[str],
    conflict_type: list[str],
    resolution: list[str],
    join: list[str],
    tier_a: bool,
    blocking: bool,
    quarantined: bool,
    differences: bool,
) -> int:
    del symbol, isin, conflict_type, resolution, join, tier_a
    from alpha.historical_truth.foundation_readiness_models import (
        FoundationReadinessReport,
    )

    if not isinstance(report, FoundationReadinessReport):
        return 0
    if blocking:
        return sum(row.blocking for row in report.conflict_resolutions)
    if quarantined:
        return len(report.quarantined_identities)
    if differences:
        return len(report.discrepancies_2026)
    return len(report.join_readiness)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must use YYYY-MM-DD", param_hint=option) from exc


__all__ = ["tier_a_foundation_readiness"]
