from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Annotated

import typer

from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.config.settings import settings
from alpha.market_opportunity_truth import (
    DEFAULT_MARKET_OPPORTUNITY_OUTPUT,
    MarketOpportunityTruthEngine,
    MarketOpportunityTruthExporter,
    render_audit_summary,
)
from alpha.market_opportunity_truth.opportunity_population import (
    DEFAULT_ACU_OUTPUT,
    DEFAULT_BENCHMARK_OUTPUT,
    DEFAULT_FEATURE_OUTPUT,
)

market_opportunity_app = typer.Typer(
    help="Measure point-in-time market opportunity supply independently of Alpha.",
    no_args_is_help=True,
)


@market_opportunity_app.command("audit")
def market_opportunity_audit(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    feature_output: Annotated[
        Path, typer.Option("--feature-output")
    ] = DEFAULT_FEATURE_OUTPUT,
    benchmark_output: Annotated[
        Path, typer.Option("--benchmark-output")
    ] = DEFAULT_BENCHMARK_OUTPUT,
    acu_output: Annotated[Path, typer.Option("--acu-output")] = DEFAULT_ACU_OUTPUT,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_MARKET_OPPORTUNITY_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run MOTA against the frozen pre-association opportunity population."""

    with LegacyMarketDataStore(database) as store:
        report = MarketOpportunityTruthEngine().run(
            store=store,
            feature_output=feature_output,
            benchmark_output=benchmark_output,
            acu_output=acu_output,
        )
    paths = MarketOpportunityTruthExporter().export(
        report,
        output_directory=output,
    )
    if as_json:
        supply = report.supply_summary
        capture = report.capture_statistics
        payload = {
            "total_market_opportunities": supply.total_opportunities,
            "provisional_a_plus_a_opportunities": (
                supply.institutional_quality_opportunities
            ),
            "average_provisional_a_plus_a_opportunities_per_month": str(
                supply.average_institutional_opportunities_per_month
            ),
            "provisional_quality_status": supply.institutional_quality_status,
            "alpha_candidate_recall_percent": str(
                capture.institutional_candidate_recall_percent
            ),
            "alpha_approval_recall_percent": str(
                capture.institutional_approval_recall_percent
            ),
            "production_influence": False,
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(render_audit_summary(report), nl=False)
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


@market_opportunity_app.command("calendar")
def market_opportunity_calendar(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_MARKET_OPPORTUNITY_OUTPUT,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 24,
) -> None:
    """Show the monthly market opportunity calendar."""

    rows = _csv_rows(output / "opportunity_calendar.csv")
    typer.echo("Market Opportunity Calendar")
    for row in rows[-limit:]:
        typer.echo(
            f"{row['month']}: opportunities={row['opportunities']}; "
            f"provisional_a_plus_a={row['institutional_quality']}; "
            f"per_session={row['opportunities_per_session']}"
        )
    typer.echo("PRODUCTION_INFLUENCE=false")


@market_opportunity_app.command("density")
def market_opportunity_density(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_MARKET_OPPORTUNITY_OUTPUT,
    period_type: Annotated[str, typer.Option("--period-type")] = "YEAR",
) -> None:
    """Show opportunity density for a calendar aggregation level."""

    normalized = period_type.strip().upper()
    if normalized not in {"DAY", "WEEK", "MONTH", "QUARTER", "YEAR"}:
        raise typer.BadParameter(
            "period type must be DAY, WEEK, MONTH, QUARTER, or YEAR"
        )
    rows = [
        row
        for row in _csv_rows(output / "opportunity_density.csv")
        if row["period_type"] == normalized
    ]
    typer.echo(f"Market Opportunity Density: {normalized}")
    for row in rows:
        typer.echo(
            f"{row['period']}: total={row['opportunities']}; "
            f"high={row['high_quality']}; medium={row['medium_quality']}; "
            f"low={row['low_quality']}"
        )
    typer.echo("PRODUCTION_INFLUENCE=false")


@market_opportunity_app.command("compare")
def market_opportunity_compare(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_MARKET_OPPORTUNITY_OUTPUT,
) -> None:
    """Show market-denominator Alpha recall and capture statistics."""

    rows = _csv_rows(output / "capture_statistics.csv")
    row = rows[0] if rows else {}
    typer.echo("Alpha vs Market Opportunities")
    for label, key in (
        ("Market Opportunities", "market_opportunities"),
        ("Provisional A+/A", "institutional_quality_opportunities"),
        ("Detection Proxy Recall", "institutional_detection_recall_percent"),
        ("Candidate Recall", "institutional_candidate_recall_percent"),
        ("Approval Recall", "institutional_approval_recall_percent"),
        ("Execution Recall", "institutional_execution_recall_percent"),
        ("Opportunity Capture", "opportunity_capture_rate_percent"),
        ("Move Capture", "move_capture_percent"),
        ("Capital Capture", "capital_capture_percent"),
    ):
        typer.echo(f"{label}: {row.get(key) or 'unavailable'}")
    typer.echo("PRODUCTION_INFLUENCE=false")


@market_opportunity_app.command("report")
def market_opportunity_report(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_MARKET_OPPORTUNITY_OUTPUT,
) -> None:
    """Print the complete MOTA executive report."""

    path = output / "executive_report.md"
    if not path.exists():
        raise typer.BadParameter(
            "MOTA artifacts unavailable; run alpha market-opportunity audit"
        )
    typer.echo(path.read_text(encoding="utf-8"), nl=False)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise typer.BadParameter(
            "MOTA artifacts unavailable; run alpha market-opportunity audit"
        )
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


__all__ = ["market_opportunity_app"]
