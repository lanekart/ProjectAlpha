"""CLI for DSI-010 official calendar evidence discovery and normalization."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.config.settings import settings
from alpha.decision_superiority.pre2016_calendar_api_probe import (
    export_pre2016_holiday_api_probe,
    probe_pre2016_holiday_api,
)
from alpha.decision_superiority.pre2016_calendar_sources import (
    build_reviewed_official_calendar_source,
    discover_pre2016_calendar_evidence,
    export_pre2016_calendar_discovery,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
    Pre2016ExternalValidationError,
)

DEFAULT_DSI010_DISCOVERY_OUTPUT = Path("artifacts/dsi010_pre2016_calendar_discovery")
DEFAULT_DSI010_API_PROBE_OUTPUT = Path(
    "artifacts/dsi010_pre2016_holiday_api_probe"
)


def register_decision_superiority_pre2016_calendar_source_commands(
    app: typer.Typer,
) -> None:
    """Register calendar discovery and reviewed-source build commands."""

    app.command("decision-superiority-pre2016-calendar-discovery")(
        decision_superiority_pre2016_calendar_discovery
    )
    app.command("decision-superiority-pre2016-calendar-api-probe")(
        decision_superiority_pre2016_calendar_api_probe
    )
    app.command("decision-superiority-pre2016-calendar-source-build")(
        decision_superiority_pre2016_calendar_source_build
    )


def decision_superiority_pre2016_calendar_discovery(
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
    ] = DEFAULT_DSI010_DISCOVERY_OUTPUT,
) -> None:
    """Export dates that still require official calendar evidence."""

    try:
        result = discover_pre2016_calendar_evidence(
            database=database,
            manifest=manifest,
        )
        paths = export_pre2016_calendar_discovery(result, output)
    except (OSError, Pre2016ExternalValidationError, ValueError) as exc:
        typer.echo(f"PRE2016_CALENDAR_DISCOVERY_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Archive Unavailable Dates: {len(result.unavailable_rows)}")
    typer.echo(f"Observed Weekend Sessions: {len(result.weekend_session_rows)}")
    typer.echo(
        "Manifest Status Case Normalized: "
        f"{str(result.manifest_status_case_normalized).lower()}"
    )
    typer.echo("CALENDAR_INFERENCE_FROM_HTTP_404_PERMITTED=false")
    typer.echo("CALENDAR_INFERENCE_FROM_OBSERVED_CANDLES_PERMITTED=false")
    typer.echo("CALENDAR_CERTIFICATION_PERMITTED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def decision_superiority_pre2016_calendar_api_probe(
    output: Annotated[
        Path,
        typer.Option("--output"),
    ] = DEFAULT_DSI010_API_PROBE_OUTPUT,
    year: Annotated[
        list[int],
        typer.Option("--year"),
    ] = [],
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout-seconds", min=1.0),
    ] = 30.0,
) -> None:
    """Probe whether official NSE APIs serve genuine historical holiday years."""

    years = tuple(year) if year else tuple(range(2005, 2016))
    try:
        result = probe_pre2016_holiday_api(
            output=output,
            years=years,
            timeout_seconds=timeout_seconds,
        )
        paths = export_pre2016_holiday_api_probe(result, output)
    except (OSError, Pre2016ExternalValidationError, ValueError) as exc:
        typer.echo(f"PRE2016_CALENDAR_API_PROBE_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Requested Years: {','.join(str(item) for item in result.requested_years)}")
    typer.echo(f"Accepted Years: {','.join(str(item) for item in result.accepted_years) or 'NONE'}")
    typer.echo(f"Missing Years: {','.join(str(item) for item in result.missing_years) or 'NONE'}")
    typer.echo(f"Probe Attempts: {len(result.attempts)}")
    typer.echo(
        "HISTORICAL_YEAR_API_SUPPORT="
        f"{str(not result.missing_years).lower()}"
    )
    typer.echo("UNSUPPORTED_OR_CURRENT_YEAR_PAYLOADS_REJECTED=true")
    typer.echo("CALENDAR_CERTIFICATION_PERMITTED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} summary files plus raw responses)")


def decision_superiority_pre2016_calendar_source_build(
    review_csv: Annotated[
        Path,
        typer.Option("--review-csv"),
    ],
    source_document: Annotated[
        Path,
        typer.Option("--source-document"),
    ],
    source_url: Annotated[
        str,
        typer.Option("--source-url"),
    ],
    source_id: Annotated[
        str,
        typer.Option("--source-id"),
    ],
    covered_year: Annotated[
        list[int],
        typer.Option("--covered-year"),
    ],
    output: Annotated[
        Path,
        typer.Option("--output"),
    ],
) -> None:
    """Build one immutable official calendar source from reviewed evidence."""

    try:
        path = build_reviewed_official_calendar_source(
            review_csv=review_csv,
            source_document=source_document,
            source_url=source_url,
            source_id=source_id,
            covered_years=tuple(covered_year),
            output=output,
        )
    except (OSError, Pre2016ExternalValidationError, ValueError) as exc:
        typer.echo(f"PRE2016_CALENDAR_SOURCE_BUILD_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Official Calendar Source: {path}")
    typer.echo(f"Covered Years: {','.join(str(item) for item in sorted(covered_year))}")
    typer.echo("CLASSIFICATION_INFERRED_FROM_ARCHIVE_STATUS=false")
    typer.echo("CLASSIFICATION_INFERRED_FROM_OBSERVED_CANDLES=false")
    typer.echo("PRODUCTION_INFLUENCE=false")


__all__ = [
    "register_decision_superiority_pre2016_calendar_source_commands",
]
