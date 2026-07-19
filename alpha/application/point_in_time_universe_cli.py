"""CLI for the diagnostic point-in-time historical universe."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from alpha.config.settings import settings
from alpha.point_in_time_universe.exports import (
    DEFAULT_UNIVERSE_OUTPUT,
    UniverseArtifactRepository,
)
from alpha.point_in_time_universe.models import normalize_index
from alpha.point_in_time_universe.universe_builder import (
    LegacyPointInTimeUniverseMaterializer,
)

universe_app = typer.Typer(
    help="Build and inspect immutable point-in-time research universes.",
    no_args_is_help=True,
)


@universe_app.command("build")
def build(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_UNIVERSE_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    result = LegacyPointInTimeUniverseMaterializer().materialize(
        source_database=database,
        output_directory=output,
    )
    if as_json:
        typer.echo((output / "manifest.json").read_text(encoding="utf-8"), nl=False)
        return
    coverage = result.manifest.coverage
    typer.echo("Point-in-Time Historical Universe Build")
    typer.echo(f"Security Master: {coverage.security_master_size}")
    typer.echo(f"Sessions: {coverage.sessions}")
    typer.echo(f"Observed Membership Rows: {coverage.observation_rows}")
    typer.echo(f"Unknown History: {coverage.unknown_history_percentage:.2f}%")
    typer.echo(f"Confidence: {coverage.confidence.value}")
    typer.echo(f"Artifacts: {output} ({len(result.paths)} files)")
    typer.echo("PRODUCTION_INFLUENCE=false")


@universe_app.command("audit")
def audit(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_UNIVERSE_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    repository = UniverseArtifactRepository(output)
    manifest = repository.manifest_payload()
    rows = _csv_rows(output / "survivorship_audit.csv")
    hard_failures = sum(int(row["invalid_securities"]) for row in rows)
    future_leaks = sum(int(row["future_constituent_leaks"]) for row in rows)
    unknown_sessions = sum(row["status"] != "PASS" for row in rows)
    payload = {
        "sessions_audited": len(rows),
        "hard_failures": hard_failures,
        "future_constituent_leaks": future_leaks,
        "sessions_with_unknown_history": unknown_sessions,
        "production_influence": False,
        "build_id": manifest["build_id"],
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo("Point-in-Time Universe Survivorship Audit")
    typer.echo(f"Sessions Audited: {len(rows)}")
    typer.echo(f"Hard Failures: {hard_failures}")
    typer.echo(f"Future Constituent Leaks: {future_leaks}")
    typer.echo(f"Sessions With Unknown History: {unknown_sessions}")
    typer.echo(
        "Status: PASS_WITH_UNKNOWN_HISTORY"
        if hard_failures == 0 and future_leaks == 0
        else "Status: FAIL"
    )
    typer.echo("PRODUCTION_INFLUENCE=false")


@universe_app.command("date")
def universe_date(
    value: Annotated[str, typer.Option("--date")],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_UNIVERSE_OUTPUT,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 50,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        as_of = date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("--date must use YYYY-MM-DD") from error
    repository = UniverseArtifactRepository(output)
    all_members = repository.members_on(as_of)
    selected = all_members[:limit]
    if as_json:
        typer.echo(json.dumps(selected, indent=2, default=str, sort_keys=True))
        return
    typer.echo(f"Point-in-Time Universe: {as_of}")
    traded = sum(row["tradability"] == "TRADABLE" for row in all_members)
    typer.echo(f"Observed Market Instruments: {len(all_members)}")
    typer.echo(f"Traded With Positive Volume: {traded}")
    typer.echo(f"Tradability Unknown: {len(all_members) - traded}")
    typer.echo("Equity Eligibility: UNKNOWN")
    typer.echo("Index Membership: UNKNOWN")
    typer.echo("Sector Membership: UNKNOWN")
    typer.echo("Confidence: LOW")
    for row in selected:
        typer.echo(f"- {row['symbol']} [{row['exchange']}]")
    if len(all_members) > len(selected):
        typer.echo(f"... {len(all_members) - len(selected)} more")


@universe_app.command("index")
def universe_index(
    index: Annotated[str, typer.Option("--index")],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_UNIVERSE_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        normalized = normalize_index(index)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    rows = UniverseArtifactRepository(output).index_rows(normalized)
    known = tuple(row for row in rows if row["status"] == "KNOWN")
    if as_json:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    typer.echo(f"Historical Index Membership: {normalized}")
    typer.echo(f"Sessions: {len(rows)}")
    typer.echo(f"Known Sessions: {len(known)}")
    typer.echo(f"Unknown Sessions: {len(rows) - len(known)}")
    typer.echo("Current constituents were not backfilled.")
    typer.echo("Confidence: UNKNOWN" if not known else "Confidence: MIXED")


def _csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.exists():
        raise typer.BadParameter(f"universe artifact unavailable: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(csv.DictReader(handle))


__all__ = ["universe_app"]
