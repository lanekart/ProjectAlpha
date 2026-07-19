from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import typer

from alpha.canonical_universe_audit.engine import (
    AuditRunRequest,
    CanonicalUniverseAuditEngine,
)
from alpha.canonical_universe_audit.exporting import (
    DEFAULT_ACU_OUTPUT_DIRECTORY,
    CanonicalUniverseAuditExporter,
    load_audit_payload,
)
from alpha.canonical_universe_audit.rendering import render_run_summary
from alpha.canonical_universe_audit.research_integration import record_acu_experiment
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.config.settings import settings
from alpha.research.research_registry import ResearchExperimentRegistry

acu_app = typer.Typer(
    help="Audit frozen Alpha opportunity capacity over the canonical universe.",
    no_args_is_help=True,
)


@acu_app.command("run")
def acu_run(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_ACU_OUTPUT_DIRECTORY,
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
    research_registry: Annotated[
        Path | None,
        typer.Option("--research-registry"),
    ] = None,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Run the complete frozen-engine universe audit and export all artifacts."""

    with LegacyMarketDataStore(database) as store:
        report = CanonicalUniverseAuditEngine().run(
            store=store,
            request=AuditRunRequest(start=_date(start), end=_date(end)),
            progress=None if quiet else _progress,
        )
    paths = CanonicalUniverseAuditExporter().export(report, output_directory=output)
    record_acu_experiment(
        report,
        registry=(
            None
            if research_registry is None
            else ResearchExperimentRegistry(research_registry)
        ),
    )
    typer.echo(render_run_summary(report), nl=False)
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


@acu_app.command("opportunities")
def acu_opportunities(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_ACU_OUTPUT_DIRECTORY,
) -> None:
    """Show opportunity frequency, clustering, and idle-day evidence."""

    payload = load_audit_payload(output)
    executive = _mapping(payload.get("executive"), "executive")
    typer.echo("ACU Opportunity Capacity")
    _labels(payload)
    for label, key in (
        ("Average / Day", "average_opportunities_per_day"),
        ("Median / Day", "median_opportunities_per_day"),
        ("Maximum / Day", "maximum_opportunities_per_day"),
        ("Average / Month", "average_opportunities_per_month"),
        ("Maximum / Month", "maximum_opportunities_per_month"),
        ("Average / Week", "average_opportunities_per_week"),
        ("Median / Week", "median_opportunities_per_week"),
        ("Maximum / Week", "maximum_opportunities_per_week"),
        ("Average / Year", "average_opportunities_per_year"),
        ("Median / Year", "median_opportunities_per_year"),
        ("Maximum / Year", "maximum_opportunities_per_year"),
        ("Zero-Opportunity Days", "zero_opportunity_days"),
        ("One-Opportunity Days", "one_opportunity_days"),
        ("Two-Plus Days", "two_plus_opportunity_days"),
        ("Five-Plus Days", "five_plus_opportunity_days"),
        ("Raw Approvals", "raw_simultaneous_approvals"),
        ("Independent Approvals", "independent_simultaneous_approvals"),
        ("Opportunity-Day Clusters", "opportunity_day_clusters"),
        ("Longest Opportunity Streak", "longest_opportunity_day_streak"),
    ):
        typer.echo(f"{label}: {executive.get(key, 'unavailable')}")


@acu_app.command("sectors")
def acu_sectors(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_ACU_OUTPUT_DIRECTORY,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 20,
) -> None:
    """Show sector opportunity concentration and outcome evidence."""

    payload = load_audit_payload(output)
    sectors = _sequence(payload.get("sectors"), "sectors")
    ranked = sorted(
        (_mapping(item, "sector") for item in sectors),
        key=lambda item: (
            -_integer(item.get("approved_opportunities", 0)),
            -_integer(item.get("candidates", 0)),
            str(item.get("sector", "")),
        ),
    )[:limit]
    typer.echo("ACU Sector Opportunities")
    _labels(payload)
    for index, item in enumerate(ranked, start=1):
        typer.echo(
            f"{index}. {item.get('sector')}: candidates={item.get('candidates')}, "
            f"approved={item.get('approved_opportunities')}, "
            f"win_rate={item.get('win_rate') or 'unavailable'}, "
            f"payoff={item.get('average_realized_return_pct') or 'unavailable'}"
        )
    typer.echo("Industry/theme/market-cap: unavailable in LEGACY_DATASET")


@acu_app.command("gates")
def acu_gates(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_ACU_OUTPUT_DIRECTORY,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 20,
) -> None:
    """Rank current rejection gates and attribution categories."""

    payload = load_audit_payload(output)
    gates = tuple(
        _mapping(item, "gate") for item in _sequence(payload.get("gates"), "gates")
    )
    primary = Counter(
        str(item.get("gate_code")) for item in gates if item.get("primary") is True
    )
    categories = Counter(str(item.get("category")) for item in gates)
    typer.echo("ACU Rejection Gate Attribution")
    _labels(payload)
    typer.echo("Primary Gates:")
    for code, count in sorted(primary.items(), key=lambda item: (-item[1], item[0]))[
        :limit
    ]:
        typer.echo(f"- {code}: {count}")
    typer.echo("Categories:")
    for category, count in sorted(
        categories.items(), key=lambda item: (-item[1], item[0])
    ):
        typer.echo(f"- {category}: {count}")


@acu_app.command("liquidity")
def acu_liquidity(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_ACU_OUTPUT_DIRECTORY,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 20,
) -> None:
    """Show the highest legacy traded-value capacity observations."""

    payload = load_audit_payload(output)
    rows = tuple(
        _mapping(item, "liquidity")
        for item in _sequence(payload.get("liquidity"), "liquidity")
    )
    ranked = sorted(
        rows,
        key=lambda item: (
            -_decimal(item.get("average_daily_turnover")),
            str(item.get("symbol", "")),
        ),
    )[:limit]
    typer.echo("ACU Liquidity Capacity")
    _labels(payload)
    typer.echo("APPROXIMATE / LEGACY DATA; 1% average-turnover participation")
    for index, item in enumerate(ranked, start=1):
        typer.echo(
            f"{index}. {item.get('symbol')}: {item.get('liquidity_bucket')}, "
            f"ADV INR {item.get('average_daily_turnover') or 'unavailable'}, "
            f"capacity INR {item.get('deployable_at_10_crore') or 'unavailable'}"
        )
    typer.echo("Free float and live spread: unavailable")


@acu_app.command("capacity")
def acu_capacity(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_ACU_OUTPUT_DIRECTORY,
) -> None:
    """Show approximate INR 1 crore portfolio utilisation evidence."""

    payload = load_audit_payload(output)
    executive = _mapping(payload.get("executive"), "executive")
    typer.echo("ACU Portfolio Capacity Estimate")
    _labels(payload)
    typer.echo("Reference Capital: INR 1,00,00,000")
    typer.echo(f"Average Invested: {executive.get('average_invested_percent')}%")
    typer.echo(f"Average Idle: {executive.get('average_idle_percent')}%")
    typer.echo(f"Average Positions: {executive.get('average_positions')}")
    typer.echo("Classification: APPROXIMATE / LEGACY DATA")


@acu_app.command("report")
def acu_report(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_ACU_OUTPUT_DIRECTORY,
) -> None:
    """Print the complete investor-readable executive audit report."""

    path = output / "executive_report.md"
    if not path.exists():
        raise typer.BadParameter("ACU report unavailable; run `alpha acu run` first")
    typer.echo(path.read_text(encoding="utf-8"), nl=False)


def _progress(current: int, total: int, observed_on: date) -> None:
    if current == 1 or current == total or current % 100 == 0:
        typer.echo(
            f"ACU progress: {current}/{total} sessions through "
            f"{observed_on.isoformat()}",
            err=True,
        )


def _date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("dates must use YYYY-MM-DD") from error


def _labels(payload: dict[str, Any]) -> None:
    dataset = _mapping(payload.get("dataset"), "dataset")
    labels = _sequence(dataset.get("labels"), "dataset labels")
    typer.echo(" / ".join(str(item) for item in labels))


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise typer.BadParameter(f"invalid ACU {label} artifact")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise typer.BadParameter(f"invalid ACU {label} artifact")
    return tuple(value)


def _integer(value: object) -> int:
    return int(str(value))


def _decimal(value: object) -> Decimal:
    if value in {None, ""}:
        return Decimal("0")
    return Decimal(str(value))


__all__ = ["acu_app"]
