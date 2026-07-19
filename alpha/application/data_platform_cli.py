from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from alpha.application.hta_cli import register_hta_commands
from alpha.data_platform import (
    DEFAULT_DATA_PLATFORM_OUTPUT,
    CanonicalQueryEngine,
    DataPlatformExporter,
    DataQuery,
    DatasetCategory,
    QuerySubject,
    build_default_platform,
    subject_for_category,
)
from alpha.data_platform.rendering import (
    render_architecture,
    render_datasets,
    render_platform_summary,
    render_provenance_model,
    render_query_result,
    render_registry,
)

data_app = typer.Typer(
    help="Inspect the non-production Alpha Data Platform architecture.",
    no_args_is_help=True,
)


@data_app.command("platform")
def data_platform(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DATA_PLATFORM_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Freeze and export the ADP v1.0 architecture bundle."""

    platform = build_default_platform()
    paths = DataPlatformExporter().export(platform, output_directory=output)
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "platform_version": platform.manifest.platform_version,
                    "dataset_count": platform.manifest.dataset_count,
                    "schema_count": platform.manifest.schema_count,
                    "downloaded_files": 0,
                    "production_influence": False,
                    "artifacts": len(paths),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        typer.echo(render_platform_summary(platform), nl=False)
        typer.echo(f"Artifacts: {output} ({len(paths)} files)")


@data_app.command("registry")
def data_registry(
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the permanent ADP dataset registry."""

    platform = build_default_platform()
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "registry_hash": platform.registry.registry_hash,
                    "dataset_ids": [
                        item.dataset_id for item in platform.registry.records
                    ],
                    "production_influence": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        typer.echo(render_registry(platform), nl=False)


@data_app.command("datasets")
def data_datasets(
    source: Annotated[str | None, typer.Option("--source")] = None,
    category: Annotated[str | None, typer.Option("--category")] = None,
) -> None:
    """List supported official datasets without acquiring them."""

    platform = build_default_platform()
    records = platform.registry.records
    if source:
        records = tuple(
            item for item in records if item.source.upper() == source.strip().upper()
        )
    if category:
        try:
            selected = DatasetCategory(category.strip().upper())
        except ValueError as error:
            raise typer.BadParameter("unknown ADP dataset category") from error
        records = tuple(item for item in records if item.category is selected)
    if records == platform.registry.records:
        typer.echo(render_datasets(platform), nl=False)
        return
    typer.echo("ADP Supported Datasets")
    for item in records:
        typer.echo(
            f"- {item.dataset_id}: {item.category.value}; source={item.source}; "
            f"acquired={'YES' if item.acquired else 'NO'}"
        )
    typer.echo("No historical downloads were performed.")


@data_app.command("query")
def data_query(
    dataset: Annotated[str, typer.Option("--dataset")] = "nse-equity-bhavcopy",
    subject: Annotated[str | None, typer.Option("--subject")] = None,
    symbol: Annotated[list[str] | None, typer.Option("--symbol")] = None,
    security_id: Annotated[list[str] | None, typer.Option("--security-id")] = None,
    index: Annotated[list[str] | None, typer.Option("--index")] = None,
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 100,
) -> None:
    """Compile and execute an independent point-in-time dataset query."""

    platform = build_default_platform()
    try:
        record = platform.registry.get(dataset)
    except KeyError as error:
        raise typer.BadParameter(str(error)) from error
    try:
        selected_subject = (
            QuerySubject(subject.strip().upper())
            if subject
            else subject_for_category(record.category)
        )
        query = DataQuery(
            dataset_id=record.dataset_id,
            subject=selected_subject,
            market_start=_date(start),
            market_end=_date(end),
            knowledge_as_of=_datetime(as_of),
            symbols=tuple(symbol or ()),
            security_ids=tuple(security_id or ()),
            index_ids=tuple(index or ()),
            limit=limit,
        )
        result = CanonicalQueryEngine(platform.registry).execute(query)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(render_query_result(result), nl=False)


@data_app.command("provenance")
def data_provenance(
    dataset: Annotated[str | None, typer.Option("--dataset")] = None,
) -> None:
    """Show ADP provenance requirements and readiness."""

    platform = build_default_platform()
    if dataset is not None:
        try:
            platform.registry.get(dataset)
        except KeyError as error:
            raise typer.BadParameter(str(error)) from error
    typer.echo(render_provenance_model(platform), nl=False)


@data_app.command("architecture")
def data_architecture() -> None:
    """Show the active ADP layer contracts and isolation boundary."""

    typer.echo(render_architecture(build_default_platform()), nl=False)


def _date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("ADP dates must use YYYY-MM-DD") from error


def _datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("ADP knowledge cutoff must be ISO-8601") from error


register_hta_commands(data_app)


__all__ = ["data_app"]
