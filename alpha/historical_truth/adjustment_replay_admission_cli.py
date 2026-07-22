"""CLI for HTR-010B1 adjustment validation and replay admission."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.adjustment_replay_admission_engine import (
    AdjustmentReplayAdmissionEngine,
)
from alpha.historical_truth.adjustment_replay_admission_exports import (
    AdjustmentReplayAdmissionArtifactExporter,
)


def adjustment_replay_admission_certify(
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
    htr010b_output: Path = typer.Option(
        Path("artifacts/htr010b_complete_corporate_action_dataset"),
        "--htr010b-output",
        exists=True,
        file_okay=False,
    ),
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010b1_adjustment_replay_admission"), "--output"
    ),
    refresh_sources: bool = typer.Option(False, "--refresh-sources"),
    verify_only: bool = typer.Option(False, "--verify-only"),
    symbol: list[str] = typer.Option([], "--symbol"),
    isin: list[str] = typer.Option([], "--isin"),
    action_type: list[str] = typer.Option([], "--action-type"),
    validation_outcome: list[str] = typer.Option([], "--validation-outcome"),
    quarantine_reason: list[str] = typer.Option([], "--quarantine-reason"),
    admission_state: list[str] = typer.Option([], "--admission-state"),
    year: list[int] = typer.Option([], "--year"),
    only_suspected_factors: bool = typer.Option(False, "--only-suspected-factors"),
    only_mixed_basis: bool = typer.Option(False, "--only-mixed-basis"),
    only_unknown_factors: bool = typer.Option(False, "--only-unknown-factors"),
    only_quarantined: bool = typer.Option(False, "--only-quarantined"),
    only_tier_a: bool = typer.Option(False, "--only-tier-a"),
) -> None:
    """Validate factors and produce identity-date replay admission intervals."""

    del database, root, htr010a3_output, refresh_sources, verify_only, only_tier_a
    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    report = AdjustmentReplayAdmissionEngine().run(
        htr010b_output=htr010b_output,
        start_date=start_date,
        end_date=end_date,
    )
    paths = AdjustmentReplayAdmissionArtifactExporter().export(report, output)
    selected = _selected_count(
        report,
        symbol=symbol,
        isin=isin,
        action_type=action_type,
        validation_outcome=validation_outcome,
        quarantine_reason=quarantine_reason,
        admission_state=admission_state,
        year=year,
        only_suspected_factors=only_suspected_factors,
        only_mixed_basis=only_mixed_basis,
        only_unknown_factors=only_unknown_factors,
        only_quarantined=only_quarantined,
    )
    print("HTR-010B1 Adjustment Validation and Replay Admission")
    print(f"Factor validation cases: {len(report.factor_validation_cases):,}")
    print(f"Quarantine intervals: {len(report.quarantine_census):,}")
    print(f"Replay admission intervals: {len(report.replay_admission_intervals):,}")
    print(f"Diagnostic records selected: {selected:,}")
    print(f"Replay readiness: {report.replay_readiness['state']}")
    print(f"Report SHA256: {report.report_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")


def _selected_count(report: object, **filters: object) -> int:
    from alpha.historical_truth.adjustment_replay_admission_models import (
        AdjustmentReplayAdmissionReport,
    )

    if not isinstance(report, AdjustmentReplayAdmissionReport):
        return 0
    rows = list(report.factor_validation_results)
    symbols = {str(item).upper() for item in filters["symbol"]}
    isins = {str(item).upper() for item in filters["isin"]}
    action_types = {str(item) for item in filters["action_type"]}
    outcomes = {str(item) for item in filters["validation_outcome"]}
    years = {int(item) for item in filters["year"]}
    if symbols:
        rows = [row for row in rows if str(row.get("symbol", "")).upper() in symbols]
    if isins:
        rows = [row for row in rows if str(row.get("isin", "")).upper() in isins]
    if action_types:
        rows = [row for row in rows if str(row.get("action_type")) in action_types]
    if outcomes:
        rows = [row for row in rows if str(row.get("validation_outcome")) in outcomes]
    if years:
        rows = [
            row
            for row in rows
            if row.get("effective_date")
            and int(str(row["effective_date"])[:4]) in years
        ]
    if filters["only_suspected_factors"]:
        return len(rows)
    if filters["only_mixed_basis"]:
        return len(report.mixed_basis_resolution)
    if filters["only_unknown_factors"]:
        return len(report.unknown_factor_impact)
    if filters["only_quarantined"] or filters["quarantine_reason"]:
        wanted = {str(item) for item in filters["quarantine_reason"]}
        return sum(
            not wanted or str(row.get("quarantine_reason")) in wanted
            for row in report.quarantine_census
        )
    if filters["admission_state"]:
        wanted = {str(item) for item in filters["admission_state"]}
        return sum(
            str(row.get("admission_state")) in wanted
            for row in report.replay_admission_intervals
        )
    return len(rows)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must use YYYY-MM-DD", param_hint=option) from exc


__all__ = ["adjustment_replay_admission_certify"]
