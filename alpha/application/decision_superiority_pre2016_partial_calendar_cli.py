"""CLI for non-certifying DSI-010 partial calendar reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha.config.settings import settings
from alpha.decision_superiority.pre2016_calendar_partial import (
    audit_pre2016_calendar_partial,
)
from alpha.decision_superiority.pre2016_calendar_partial_artifacts import (
    export_pre2016_partial_calendar_audit,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
    Pre2016ExternalValidationError,
)

DEFAULT_DSI010_PARTIAL_CALENDAR_OUTPUT = Path(
    "artifacts/dsi010_pre2016_partial_calendar"
)


def register_decision_superiority_pre2016_partial_calendar_command(
    app: typer.Typer,
) -> None:
    """Register the non-certifying partial official-calendar audit."""

    app.command("decision-superiority-pre2016-calendar-partial-audit")(
        decision_superiority_pre2016_calendar_partial_audit
    )


def decision_superiority_pre2016_calendar_partial_audit(
    official_source: Annotated[
        list[Path],
        typer.Option(
            "--official-source",
            help="Immutable official NSE calendar JSON; repeat for each covered year.",
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
    ] = DEFAULT_DSI010_PARTIAL_CALENDAR_OUTPUT,
) -> None:
    """Audit a supported year subset without granting calendar certification."""

    try:
        result = audit_pre2016_calendar_partial(
            database=database,
            manifest=manifest,
            official_sources=tuple(official_source),
        )
        paths = export_pre2016_partial_calendar_audit(result, output)
    except (OSError, Pre2016ExternalValidationError, ValueError) as exc:
        typer.echo(f"PRE2016_PARTIAL_CALENDAR_AUDIT_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(
        "Covered Years: "
        + (",".join(str(year) for year in result.covered_years) or "NONE")
    )
    typer.echo(
        "Missing Years: "
        + (",".join(str(year) for year in result.missing_years) or "NONE")
    )
    typer.echo(f"Official Holidays: {result.report.official_holiday_count}")
    typer.echo(f"Holiday/Candle Conflicts: {len(result.conflict_rows)}")
    typer.echo(f"Covered-Year Unresolved Weekdays: {len(result.unresolved_rows)}")
    typer.echo(
        "Covered-Year Manifest Unavailable: "
        f"{len(result.manifest_unavailable_rows)}"
    )
    typer.echo("CALENDAR_CERTIFICATION_PERMITTED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


__all__ = ["register_decision_superiority_pre2016_partial_calendar_command"]
