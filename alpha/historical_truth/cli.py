from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.bridge_aware_continuity_cli import (
    bridge_aware_continuity_certify,
)
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.complete_corporate_action_cli import (
    complete_corporate_action_dataset,
)
from alpha.historical_truth.complete_security_dataset_cli import (
    complete_security_dataset_certify,
)
from alpha.historical_truth.corporate_action_price_cli import (
    corporate_action_price_certify,
)
from alpha.historical_truth.event_sourced_universe_cli import (
    event_sourced_universe_certify,
)
from alpha.historical_truth.foundation_readiness_cli import (
    tier_a_foundation_readiness,
)
from alpha.historical_truth.integrity import HistoricalTruthIntegrityAudit
from alpha.historical_truth.legacy_rights_reference_bridge_cli import (
    legacy_rights_reference_bridge_certify,
)
from alpha.historical_truth.lifecycle_session_cli import (
    lifecycle_session_semantics_certify,
)
from alpha.historical_truth.pilot import (
    DEFAULT_CROSS_ERA_DATES,
    HistoricalBackfillPilot,
)
from alpha.historical_truth.point_in_time_identity_cli import (
    point_in_time_universe_certify,
)
from alpha.historical_truth.population import HistoricalPopulationEngine
from alpha.historical_truth.replay_eligibility_integrity_cli import (
    replay_eligibility_integrity_audit,
)
from alpha.historical_truth.research_price_cli import research_price_certify
from alpha.historical_truth.resumable import HistoricalTruthWarehouse
from alpha.historical_truth.security_population_repair_cli import (
    security_population_repair,
)
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine
from alpha.historical_truth.special_session_recovery_cli import (
    session_calendar_build,
    special_session_candle_recover,
)
from alpha.historical_truth.special_session_snapshot_parity_cli import (
    special_session_snapshot_repair,
)

historical_truth_app = typer.Typer(
    help="Build and audit official historical market truth."
)

historical_truth_app.command("event-sourced-universe-certify")(
    event_sourced_universe_certify
)
historical_truth_app.command("corporate-action-price-certify")(
    corporate_action_price_certify
)
historical_truth_app.command("complete-security-dataset-certify")(
    complete_security_dataset_certify
)
historical_truth_app.command("security-population-repair")(security_population_repair)
historical_truth_app.command("lifecycle-session-semantics-certify")(
    lifecycle_session_semantics_certify
)
historical_truth_app.command("tier-a-foundation-readiness")(tier_a_foundation_readiness)
historical_truth_app.command("complete-corporate-action-dataset")(
    complete_corporate_action_dataset
)
historical_truth_app.command("legacy-rights-reference-bridge-certify")(
    legacy_rights_reference_bridge_certify
)
historical_truth_app.command("bridge-aware-continuity-certify")(
    bridge_aware_continuity_certify
)
historical_truth_app.command("research-price-certify")(research_price_certify)


def _parse_date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option_name,
        ) from exc


def _parse_range(start: str, end: str) -> tuple[date, date]:
    start_date = _parse_date(start, "--start")
    end_date = _parse_date(end, "--end")
    if start_date > end_date:
        raise typer.BadParameter(
            "must be on or before --end",
            param_hint="--start",
        )
    return start_date, end_date


@historical_truth_app.command("init")
def initialise(
    root: Path = typer.Option(Path("alpha_data"), "--root"),
) -> None:
    warehouse = HistoricalTruthWarehouse(root)
    warehouse.initialise()
    print(f"Historical Truth Warehouse initialised: {root}")


@historical_truth_app.command("plan")
def plan(
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
) -> None:
    start_date, end_date = _parse_range(start, end)
    warehouse = HistoricalTruthWarehouse(root)
    requests = warehouse.plan_nse_bhavcopies(start_date, end_date)
    print(f"Planned NSE bhavcopy requests: {len(requests)}")
    for request in requests:
        print(
            f"{request.trading_date.isoformat()} | {request.source_url} | "
            f"{request.relative_path}"
        )


@historical_truth_app.command("fetch")
def fetch(
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    retry_failed: bool = typer.Option(
        True,
        "--retry-failed/--no-retry-failed",
        help="Retry files whose latest manifest state is FAILED.",
    ),
) -> None:
    start_date, end_date = _parse_range(start, end)
    warehouse = HistoricalTruthWarehouse(root)
    requests = warehouse.plan_nse_bhavcopies(start_date, end_date)
    records = warehouse.fetch_many(requests, retry_failed=retry_failed)
    for record in records:
        print(
            f"{record.trading_date.isoformat()} | {record.status.value} | "
            f"{record.relative_path}"
        )


@historical_truth_app.command("populate")
def populate(
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    output_dir: Path = typer.Option(
        Path("artifacts/historical_population"),
        "--output-dir",
    ),
    retry_failed: bool = typer.Option(
        True,
        "--retry-failed/--no-retry-failed",
    ),
) -> None:
    start_date, end_date = _parse_range(start, end)
    archive = HistoricalTruthWarehouse(root)
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    snapshots = PointInTimeSnapshotEngine(canonical, root / "snapshots")
    engine = HistoricalPopulationEngine(archive, canonical, snapshots)
    requests = archive.plan_nse_bhavcopies(start_date, end_date)
    records = engine.populate(requests, retry_failed=retry_failed)
    summary = engine.summarise(records)
    paths = engine.export(records, output_dir)
    print(f"Weekday request coverage: {summary.coverage_ratio:.2%}")
    print(f"Candle snapshots available: {summary.candle_snapshots}")
    print(f"Evidence-complete snapshots: {summary.evidence_complete_snapshots}")
    print(f"Evidence-incomplete snapshots: {summary.evidence_incomplete_snapshots}")
    print(f"Failed: {summary.failed}")
    print(f"Unavailable: {summary.unavailable}")
    print(f"Skipped: {summary.skipped}")
    print(f"Rows ingested this run: {summary.ingested_rows}")
    print(f"Rows available in snapshots: {summary.available_rows}")
    for path in paths:
        print(path)


historical_truth_app.command("session-calendar-build")(session_calendar_build)
historical_truth_app.command("special-session-candle-recover")(
    special_session_candle_recover
)
historical_truth_app.command("special-session-snapshot-repair")(
    special_session_snapshot_repair
)
historical_truth_app.command("replay-eligibility-integrity-audit")(
    replay_eligibility_integrity_audit
)
historical_truth_app.command("point-in-time-universe-certify")(
    point_in_time_universe_certify
)


@historical_truth_app.command("pilot")
def backfill_pilot(
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    pilot_date: list[str] = typer.Option(
        [],
        "--date",
        help="Representative NSE trading date; repeat to override defaults.",
    ),
    output_dir: Path = typer.Option(
        Path("artifacts/htr007_backfill_pilot"),
        "--output-dir",
    ),
) -> None:
    """Run the governed HTR-007 cross-era acquisition pilot."""

    dates = (
        tuple(_parse_date(value, "--date") for value in pilot_date)
        if pilot_date
        else DEFAULT_CROSS_ERA_DATES
    )
    archive = HistoricalTruthWarehouse(root)
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    snapshots = PointInTimeSnapshotEngine(canonical, root / "snapshots")
    engine = HistoricalBackfillPilot(archive, canonical, snapshots)
    report = engine.run(dates)
    paths = engine.export(report, output_dir)
    print(f"Pilot Complete: {report.complete}")
    print(f"Schemas Observed: {', '.join(report.schemas_observed)}")
    print(f"Report SHA-256: {report.report_sha256}")
    for record in report.records:
        print(
            f"{record.trading_date.isoformat()} | {record.status.value} | "
            f"{record.detected_schema or '-'} | {record.error or ''}"
        )
    for path in paths:
        print(path)
    if not report.complete:
        raise typer.Exit(code=1)


@historical_truth_app.command("status")
def status(
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    output_dir: Path = typer.Option(
        Path("artifacts/historical_truth"),
        "--output-dir",
    ),
) -> None:
    warehouse = HistoricalTruthWarehouse(root)
    records = warehouse.records()
    paths = warehouse.export_status(output_dir)
    print(f"Manifest records: {len(records)}")
    for path in paths:
        print(path)


@historical_truth_app.command("validate-csv")
def validate_csv(
    csv_path: Path = typer.Argument(..., exists=True, dir_okay=False),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
) -> None:
    warehouse = HistoricalTruthWarehouse(root)
    issues = warehouse.validate_bhavcopy_csv(csv_path)
    if not issues:
        print("VALID")
        return
    for issue in issues:
        location = f" row={issue.row_number}" if issue.row_number else ""
        print(f"{issue.severity.value.upper()} {issue.code}{location}: {issue.message}")
    raise typer.Exit(code=1)


@historical_truth_app.command("integrity-audit")
def integrity_audit(
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    as_of: str = typer.Option(
        ...,
        "--as-of",
        help="Deterministic knowledge cutoff in YYYY-MM-DD format.",
    ),
    holiday: list[str] = typer.Option(
        [],
        "--holiday",
        help="Explicit exchange holiday; repeat for multiple dates.",
    ),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    output_dir: Path = typer.Option(
        Path("artifacts/historical_truth_integrity"),
        "--output-dir",
    ),
) -> None:
    start_date, end_date = _parse_range(start, end)
    as_of_date = _parse_date(as_of, "--as-of")
    holiday_dates = frozenset(_parse_date(value, "--holiday") for value in holiday)
    archive = HistoricalTruthWarehouse(root)
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    snapshots = PointInTimeSnapshotEngine(canonical, root / "snapshots")
    engine = HistoricalTruthIntegrityAudit(
        archive,
        canonical,
        snapshots,
        holiday_dates=holiday_dates,
    )
    report = engine.audit(
        start_date,
        end_date,
        as_of_date=as_of_date,
    )
    paths = engine.export(report, output_dir)
    summary = report.summary
    print(f"Expected trading days: {summary.expected_trading_days}")
    print(f"Observed trading days: {summary.observed_trading_days}")
    print(f"Coverage: {summary.coverage_ratio:.2%}")
    print(f"Candle replay ready: {summary.candle_replay_ready}")
    print(f"Full-evidence replay ready: {summary.full_evidence_replay_ready}")
    for blocker in report.replay_blockers:
        print(f"BLOCKER {blocker}")
    for path in paths:
        print(path)
