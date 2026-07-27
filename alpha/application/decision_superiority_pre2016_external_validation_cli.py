"""Permanent CLI for governed DSI-010 pre-2016 external validation."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from alpha.application.historical_ingestion import HistoricalIngestionService
from alpha.config.settings import settings
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

DEFAULT_DSI010_OUTPUT = Path(
    ".alpha/benchmark/dsi010_pre2016_external_validation"
)


def register_decision_superiority_pre2016_external_validation_command(
    app: typer.Typer,
) -> None:
    """Register DSI-010 backfill, runner, and verifier commands."""

    app.command("decision-superiority-pre2016-archive-backfill")(
        decision_superiority_pre2016_archive_backfill
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
) -> None:
    """Download and ingest official NSE archives for the frozen external era."""

    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
        _validate_external_dates(start_date, end_date)
        result = HistoricalIngestionService().backfill_legacy_archive(
            start_date,
            end_date,
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"PRE2016_ARCHIVE_BACKFILL_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Requested Start: {result.requested_start}")
    typer.echo(f"Requested End: {result.requested_end}")
    typer.echo(f"Attempted Weekdays: {result.attempted_days}")
    typer.echo(f"Processed Archives: {result.processed_archives}")
    typer.echo(f"Skipped Weekend Days: {result.skipped_non_trading_days}")
    typer.echo(f"Failed Dates: {len(result.failed_dates)}")
    for failure in result.failed_dates:
        typer.echo(f"FAILED_DATE: {failure}")
    typer.echo("PRODUCTION_INFLUENCE=false")


def decision_superiority_pre2016_external_validation(
    dsi009_certificate: Annotated[
        Path,
        typer.Option("--dsi009-certificate"),
    ],
    dsi007_certificate: Annotated[
        Path,
        typer.Option("--dsi007-certificate"),
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
    typer.echo(
        f"Nifty TRI Net CAGR: {_percent(benchmark_summary.get('net_cagr'))}"
    )
    typer.echo(
        "Benchmark Gap Closed: "
        f"{_percent(result.summaries.get('benchmark_gap_closed'))}"
    )
    typer.echo(
        "External Classification: "
        f"{result.summaries['classification']}"
    )
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
        "External Classification: "
        f"{payload['external_validation_classification']}"
    )
    typer.echo(
        "Forward Paper Eligible: "
        f"{str(payload['forward_paper_eligible']).lower()}"
    )
    typer.echo("Certificate: VALID")


def _validate_external_dates(start: date, end: date) -> None:
    if start != DSI010_EXTERNAL_START or end != DSI010_EXTERNAL_END:
        raise ValueError(
            "DSI-010 archive backfill is frozen to 2005-01-01 through 2015-12-31"
        )
    if end >= date(2016, 1, 1):
        raise ValueError("pre-2016 archive backfill cannot include 2016")


def _percent(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "UNKNOWN"


__all__ = [
    "register_decision_superiority_pre2016_external_validation_command",
]
