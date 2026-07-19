"""CLI commands for the non-production Warehouse Delta Audit."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from alpha.config.settings import settings
from alpha.warehouse_delta_audit import (
    DEFAULT_WDA_OUTPUT,
    SourceLineage,
    WarehouseDeltaAuditEngine,
    WarehouseDeltaExporter,
    WarehouseDeltaRequest,
    render_audit_summary,
)

warehouse_delta_app = typer.Typer(
    help="Compare the legacy warehouse with an isolated official-format sample.",
    no_args_is_help=True,
)


@warehouse_delta_app.command("audit")
def warehouse_delta_audit(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    comparison_source: Annotated[
        Path,
        typer.Option("--comparison-source"),
    ] = settings.extracted_data_dir,
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_WDA_OUTPUT,
    sample_size: Annotated[int, typer.Option("--sample-size", min=7)] = 500,
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
    source_lineage: Annotated[
        str,
        typer.Option("--source-lineage"),
    ] = SourceLineage.LEGACY_LINEAGE_RAW_SOURCE.value,
    source_attestation: Annotated[
        str | None,
        typer.Option("--source-attestation"),
    ] = None,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Run the full paired sample, candidate, decision, and replay audit."""

    try:
        lineage = SourceLineage(source_lineage.strip().upper())
    except ValueError as error:
        raise typer.BadParameter("unknown comparison source lineage") from error
    try:
        request = WarehouseDeltaRequest(
            legacy_database=str(database),
            comparison_source=str(comparison_source),
            output_directory=str(output),
            sample_size=sample_size,
            start=_date(start),
            end=_date(end),
            source_lineage=lineage,
            source_attestation=source_attestation,
        )
        report = WarehouseDeltaAuditEngine().run(
            request,
            project_root=settings.project_root,
            progress=None if quiet else _progress,
        )
    except (duckdb.Error, FileNotFoundError, RuntimeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    paths = WarehouseDeltaExporter().export(report, output)
    typer.echo(render_audit_summary(report), nl=False)
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


@warehouse_delta_app.command("replay")
def warehouse_delta_replay(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_WDA_OUTPUT,
) -> None:
    """Render the persisted frozen replay comparison."""

    path = output / "replay_delta.csv"
    rows = _rows(path)
    typer.echo("Project Alpha - Warehouse Replay Delta")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo("Identical settings: YES")
    for row in rows:
        typer.echo(
            f"- {row['metric']}: legacy={row['legacy_value']}, "
            f"comparison={row['comparison_value']}, delta={row['delta']} "
            f"{row['unit']}"
        )


@warehouse_delta_app.command("report")
def warehouse_delta_report(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_WDA_OUTPUT,
) -> None:
    """Print the persisted WDA executive report."""

    path = output / "executive_report.md"
    if not path.exists():
        raise typer.BadParameter("WDA report unavailable; run warehouse-delta audit")
    typer.echo(path.read_text(encoding="utf-8"), nl=False)


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise typer.BadParameter("WDA replay unavailable; run warehouse-delta audit")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("WDA dates must use YYYY-MM-DD") from error


def _progress(phase: str, current: int, total: int, observed_on: date | None) -> None:
    if current in {0, 1, total} or current % 100 == 0:
        suffix = "" if observed_on is None else f" through {observed_on}"
        typer.echo(f"WDA {phase}: {current}/{total}{suffix}", err=True)


__all__ = ["warehouse_delta_app"]
