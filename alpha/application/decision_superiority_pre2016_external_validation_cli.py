"""Permanent CLI for governed DSI-010 pre-2016 external validation."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from alpha.config.settings import settings
from alpha.decision_superiority.pre2016_calendar import (
    certify_pre2016_calendar,
    export_pre2016_calendar_certification,
)
from alpha.decision_superiority.pre2016_external_validation import (
    GovernedPre2016ExternalValidationEngine,
)
from alpha.decision_superiority.pre2016_external_validation_artifacts import (
    export_pre2016_external_validation,
    validate_pre2016_external_validation_certificate,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
    DSI010_EXTERNAL_END,
    DSI010_EXTERNAL_START,
    Pre2016ExternalValidationError,
    Pre2016ExternalValidationSourcePaths,
)
from alpha.decision_superiority.pre2016_population import (
    Pre2016PopulationError,
    populate_pre2016_historical_truth,
)

DEFAULT_DSI010_OUTPUT = Path(".alpha/benchmark/dsi010_pre2016_external_validation")
DEFAULT_DSI010_POPULATION_OUTPUT = Path("artifacts/dsi010_pre2016_population")
DEFAULT_DSI010_CALENDAR_OUTPUT = Path("artifacts/dsi010_pre2016_calendar")


def register_decision_superiority_pre2016_external_validation_command(
    app: typer.Typer,
) -> None:
    """Register DSI-010 population, calendar, runner, and verifier commands."""

    app.command("decision-superiority-pre2016-archive-backfill")(
        decision_superiority_pre2016_archive_backfill
    )
    app.command("decision-superiority-pre2016-calendar-certify")(
        decision_superiority_pre2016_calendar_certify
    )
    app.command("decision-superiority-pre2016-external-validation")(
        decision_superiority_pre2016_external_validation
    )
    app.command("decision-superiority-pre2016-external-validation-verify")(
        decision_superiority_pre2016_external_validation_verify
    )


def decision_superiority_pre2016_archive_backfill(
    start: Annotated[
        str,
        typer.Option("--start"),
    ] = DSI010_EXTERNAL_START.isoformat(),
    end: Annotated[
        str,
        typer.Option("--end"),
    ] = DSI010_EXTERNAL_END.isoformat(),
    root: Annotated[
        Path,
        typer.Option("--root"),
    ] = Path("alpha_data"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir"),
    ] = DEFAULT_DSI010_POPULATION_OUTPUT,
    retry_failed: Annotated[
        bool,
        typer.Option("--retry-failed/--no-retry-failed"),
    ] = True,
) -> None:
    """Populate official pre-2016 candles into governed Historical Truth."""

    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
        _validate_external_dates(start_date, end_date)
        result = populate_pre2016_historical_truth(
            root=root,
            output_dir=output_dir,
            start=start_date,
            end=end_date,
            retry_failed=retry_failed,
        )
    except (OSError, Pre2016PopulationError, ValueError) as exc:
        typer.echo(f"PRE2016_ARCHIVE_BACKFILL_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Requested Start: {result.requested_start}")
    typer.echo(f"Requested End: {result.requested_end}")
    typer.echo(f"Planned Requests: {result.planned_requests}")
    typer.echo(f"Weekday Request Coverage: {result.coverage_ratio:.2%}")
    typer.echo(f"Candle Snapshots: {result.candle_snapshots}")
    typer.echo(f"Evidence-Complete Snapshots: {result.evidence_complete_snapshots}")
    typer.echo(f"Evidence-Incomplete Snapshots: {result.evidence_incomplete_snapshots}")
    typer.echo(f"Failed: {result.failed}")
    typer.echo(f"Unavailable: {result.unavailable}")
    typer.echo(f"Skipped: {result.skipped}")
    typer.echo(f"Rows Ingested This Run: {result.ingested_rows}")
    typer.echo(f"Rows Available in Snapshots: {result.available_rows}")
    typer.echo(f"Historical Truth Database: {result.database}")
    typer.echo(f"Snapshot Root: {result.snapshot_root}")
    typer.echo("DOWNSTREAM_GOVERNED_A_TO_B_REBUILD_REQUIRED=true")
    typer.echo("LEGACY_INGESTION_DATABASE_USED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output_dir} ({len(result.artifact_paths)} files)")


def decision_superiority_pre2016_calendar_certify(
    official_source: Annotated[
        list[Path],
        typer.Option(
            "--official-source",
            help="Immutable official NSE calendar JSON; repeat for multiple years.",
        ),
    ],
    database: Annotated[
        Path,
        typer.Option("--database"),
    ] = settings.database_path,
    manifest: Annotated[
        Path,
        typer.Option("--manifest"),
    ] = Path("alpha_data/manifests/archive_manifest.jsonl"),
    output: Annotated[
        Path,
        typer.Option("--output"),
    ] = DEFAULT_DSI010_CALENDAR_OUTPUT,
) -> None:
    """Certify the official pre-2016 calendar against candles and manifest states."""

    try:
        result = certify_pre2016_calendar(
            database=database,
            manifest=manifest,
            official_sources=tuple(official_source),
        )
        paths = export_pre2016_calendar_certification(
            result,
            output,
            database=database,
        )
    except (OSError, Pre2016ExternalValidationError, ValueError) as exc:
        typer.echo(f"PRE2016_CALENDAR_CERTIFICATION_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc

    report = result.report
    typer.echo(f"Calendar Start: {report.start_date}")
    typer.echo(f"Calendar End: {report.end_date}")
    typer.echo(f"Certification State: {report.certification_state.value}")
    typer.echo(f"Official Sources: {len(report.sources)}")
    typer.echo(f"Official Holidays: {report.official_holiday_count}")
    typer.echo(f"Official Special Sessions: {report.official_special_session_count}")
    typer.echo(f"Expected Sessions: {report.expected_session_count}")
    typer.echo(f"Observed Sessions: {report.observed_session_count}")
    typer.echo(f"Unresolved Weekdays: {report.unresolved_weekday_count}")
    typer.echo(
        f"Unconfirmed Special Sessions: {report.unconfirmed_special_session_count}"
    )
    typer.echo(f"Missing Special Sessions: {report.missing_special_session_count}")
    typer.echo(f"Calendar Conflicts: {report.conflict_count}")
    typer.echo(f"Manifest Unavailable: {result.manifest_unavailable_count}")
    typer.echo(f"Manifest Holiday Matches: {result.manifest_holiday_match_count}")
    typer.echo(f"Manifest Unresolved: {result.manifest_unresolved_count}")
    typer.echo(
        "Manifest Status Case Normalized: "
        f"{str(result.manifest_status_case_normalized).lower()}"
    )
    typer.echo(f"Calendar Report SHA-256: {report.report_sha256}")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")

    if report.certification_state.value != "certified":
        raise typer.Exit(1)
    if result.manifest_unresolved_count:
        raise typer.Exit(1)


def decision_superiority_pre2016_external_validation(
    dsi009_certificate: Annotated[
        Path,
        typer.Option("--dsi009-certificate"),
    ],
    dsi007_certificate: Annotated[
        Path,
        typer.Option("--dsi007-certificate"),
    ],
    calendar_report: Annotated[
        Path,
        typer.Option("--calendar-report"),
    ],
    historical_truth_snapshots: Annotated[
        Path,
        typer.Option("--historical-truth-snapshots"),
    ],
    benchmark: Annotated[
        Path,
        typer.Option("--benchmark"),
    ],
    database: Annotated[
        Path,
        typer.Option("--database"),
    ] = settings.database_path,
    output: Annotated[
        Path,
        typer.Option("--output"),
    ] = DEFAULT_DSI010_OUTPUT,
) -> None:
    """Run frozen-policy transport and independent pre-2016 replication."""

    try:
        result = GovernedPre2016ExternalValidationEngine().run(
            sources=Pre2016ExternalValidationSourcePaths(
                dsi009_certificate=dsi009_certificate,
                dsi007_certificate=dsi007_certificate,
                calendar_report=calendar_report,
                database=database,
                historical_truth_snapshots=historical_truth_snapshots,
                benchmark=benchmark,
                project_root=Path("."),
            )
        )
        paths = export_pre2016_external_validation(result, output)
    except (OSError, Pre2016ExternalValidationError, ValueError) as exc:
        typer.echo(f"PRE2016_EXTERNAL_VALIDATION_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    for slice_id, readiness in result.readiness.items():
        typer.echo(f"DSI-010{slice_id} Readiness: {readiness}")
    incumbent = result.summaries["incumbent"]
    challenger = result.summaries["challenger"]
    benchmark_summary = result.summaries["benchmark"]
    typer.echo(f"External Period: {DSI010_EXTERNAL_START} to {DSI010_EXTERNAL_END}")
    typer.echo(
        f"Actual Transport Period: {result.summaries['actual_transport_start']} "
        f"to {result.summaries['actual_transport_end']}"
    )
    typer.echo(f"Market Sessions: {result.summaries['market_sessions']}")
    typer.echo(f"Market Securities: {result.summaries['market_securities']}")
    typer.echo(f"Market Rows: {result.summaries['market_rows']}")
    typer.echo(f"Incumbent Net CAGR: {_percent(incumbent.get('net_cagr'))}")
    typer.echo(f"Challenger Net CAGR: {_percent(challenger.get('net_cagr'))}")
    typer.echo(f"Nifty TRI Net CAGR: {_percent(benchmark_summary.get('net_cagr'))}")
    typer.echo(
        "Benchmark Gap Closed: "
        f"{_percent(result.summaries.get('benchmark_gap_closed'))}"
    )
    typer.echo(f"External Classification: {result.summaries['classification']}")
    typer.echo(
        "Forward Paper Eligible: "
        f"{str(result.summaries['forward_paper_eligible']).lower()}"
    )
    typer.echo("STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def decision_superiority_pre2016_external_validation_verify(
    certificate: Annotated[
        Path,
        typer.Option("--certificate"),
    ],
    require_ready: Annotated[
        bool,
        typer.Option("--require-ready"),
    ] = False,
) -> None:
    """Validate a public DSI-010 certificate and support package."""

    try:
        payload = validate_pre2016_external_validation_certificate(
            certificate,
            require_ready=require_ready,
        )
    except Pre2016ExternalValidationError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo(
        f"External Classification: {payload['external_validation_classification']}"
    )
    typer.echo(
        f"Forward Paper Eligible: {str(payload['forward_paper_eligible']).lower()}"
    )
    typer.echo("Certificate: VALID")


def _validate_external_dates(start: date, end: date) -> None:
    if end >= date(2016, 1, 1):
        raise ValueError("pre-2016 archive backfill cannot include 2016")
    if start != DSI010_EXTERNAL_START or end != DSI010_EXTERNAL_END:
        raise ValueError(
            "DSI-010 archive backfill is frozen to 2005-01-01 through 2015-12-31"
        )


def _percent(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    try:
        return f"{float(str(value)) * 100:.2f}%"
    except (TypeError, ValueError):
        return "UNKNOWN"


__all__ = [
    "register_decision_superiority_pre2016_external_validation_command",
]
