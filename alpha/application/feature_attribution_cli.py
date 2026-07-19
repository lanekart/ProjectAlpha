"""CLI for point-in-time feature attribution research."""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.config.settings import settings
from alpha.feature_attribution_research.audit_service import (
    FeatureAttributionResearchEngine,
)
from alpha.feature_attribution_research.exports import (
    DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    FeatureAttributionExporter,
)
from alpha.feature_attribution_research.models import TransactionCostPolicy
from alpha.feature_attribution_research.rendering import (
    render_report,
)

feature_attribution_app = typer.Typer(
    help="Audit point-in-time feature edge without changing production.",
    no_args_is_help=True,
)


@feature_attribution_app.command("report")
def report(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    minimum_support: Annotated[int, typer.Option("--minimum-support")] = 50,
    dataset_version: Annotated[str | None, typer.Option("--dataset-version")] = None,
    transaction_cost_rate: Annotated[
        str, typer.Option("--transaction-cost-rate")
    ] = "0.002",
    transaction_cost_policy_id: Annotated[
        str, typer.Option("--transaction-cost-policy-id")
    ] = "transaction-cost-policy-v1",
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
) -> None:
    if as_json and as_csv:
        raise typer.BadParameter("choose either --json or --csv")
    policy = TransactionCostPolicy(
        policy_id=transaction_cost_policy_id,
        round_trip_rate=_decimal_option(
            transaction_cost_rate, "--transaction-cost-rate"
        ),
    )
    with LegacyMarketDataStore(database) as store:
        result = FeatureAttributionResearchEngine().run(
            store=store,
            start=_date_option(start, "--start"),
            end=_date_option(end, "--end"),
            symbol=symbol,
            minimum_support=minimum_support,
            transaction_cost_policy=policy,
        )
    if (
        dataset_version is not None
        and dataset_version != result.manifest.dataset_version
    ):
        raise typer.BadParameter(
            "dataset version mismatch: requested "
            f"{dataset_version}, actual {result.manifest.dataset_version}"
        )
    paths = FeatureAttributionExporter().export(result, output_directory=output)
    if as_json:
        typer.echo((output / "manifest.json").read_text(encoding="utf-8"), nl=False)
    elif as_csv:
        typer.echo(
            (output / "feature_rankings.csv").read_text(encoding="utf-8"), nl=False
        )
    else:
        typer.echo(render_report(result), nl=False)
        typer.echo(f"Artifacts: {output} ({len(paths)} files)")


@feature_attribution_app.command("population")
def population(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    manifest = _manifest(output)
    if as_csv:
        _echo_file(output / "research_population.csv")
    elif as_json:
        typer.echo(json.dumps(_population_summary(manifest), indent=2, sort_keys=True))
    else:
        summary = _population_summary(manifest)
        typer.echo("Point-in-Time Research Population")
        typer.echo(
            f"All Market Opportunities: {summary['reconstructed_market_opportunities']}"
        )
        typer.echo(
            f"Labelled Opportunities: {summary['labelled_market_opportunities']}"
        )
        typer.echo(f"Raw Linked Onsets: {summary['raw_linked_onsets']}")
        typer.echo(
            f"Deduplicated Linked Onsets: {summary['deduplicated_linked_onsets']}"
        )
        cost_policy = manifest["transaction_cost_policy"]
        assert isinstance(cost_policy, dict)
        cost_rate = Decimal(str(cost_policy["round_trip_rate"])) * 100
        typer.echo(f"Costs Used: {cost_rate:.2f}%")


@feature_attribution_app.command("features")
def features(
    feature: Annotated[str | None, typer.Option("--feature")] = None,
    feature_group: Annotated[str | None, typer.Option("--feature-group")] = None,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    rows = _json_rows(output / "feature_registry.json")
    rows = _filter(rows, feature=feature, feature_group=feature_group)
    _render_rows(rows, as_json=as_json, as_csv=as_csv)


@feature_attribution_app.command("quality")
def quality(
    feature: Annotated[str | None, typer.Option("--feature")] = None,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    _render_csv(
        output / "feature_quality.csv", feature=feature, as_json=as_json, as_csv=as_csv
    )


@feature_attribution_app.command("leakage")
def leakage(
    feature: Annotated[str | None, typer.Option("--feature")] = None,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    _render_csv(
        output / "feature_leakage_audit.csv",
        feature=feature,
        as_json=as_json,
        as_csv=as_csv,
    )


@feature_attribution_app.command("univariate")
def univariate(
    feature: Annotated[str | None, typer.Option("--feature")] = None,
    outcome: Annotated[str | None, typer.Option("--outcome")] = None,
    partition: Annotated[str | None, typer.Option("--partition")] = None,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    _render_csv(
        output / "univariate_attribution.csv",
        feature=feature,
        outcome=outcome,
        partition=partition,
        as_json=as_json,
        as_csv=as_csv,
    )


@feature_attribution_app.command("conditional")
def conditional(
    feature: Annotated[str | None, typer.Option("--feature")] = None,
    outcome: Annotated[str | None, typer.Option("--outcome")] = None,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    _render_csv(
        output / "conditional_attribution.csv",
        feature=feature,
        outcome=outcome,
        as_json=as_json,
        as_csv=as_csv,
    )


@feature_attribution_app.command("redundancy")
def redundancy(
    feature: Annotated[str | None, typer.Option("--feature")] = None,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    rows = _csv_rows(output / "feature_redundancy.csv")
    if feature:
        rows = tuple(
            row
            for row in rows
            if feature in {row.get("feature_a"), row.get("feature_b")}
        )
    _render_rows(rows, as_json=as_json, as_csv=as_csv)


@feature_attribution_app.command("interactions")
def interactions(
    partition: Annotated[str | None, typer.Option("--partition")] = None,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    _render_csv(
        output / "interaction_results.csv",
        partition=partition,
        as_json=as_json,
        as_csv=as_csv,
    )


@feature_attribution_app.command("stability")
def stability(
    feature: Annotated[str | None, typer.Option("--feature")] = None,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    _render_csv(
        output / "chronological_stability.csv",
        feature=feature,
        as_json=as_json,
        as_csv=as_csv,
    )


@feature_attribution_app.command("missing-information")
def missing_information(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    _render_csv(
        output / "missing_information_audit.csv", as_json=as_json, as_csv=as_csv
    )


@feature_attribution_app.command("case-study")
def case_study(
    symbol: Annotated[str, typer.Option("--symbol")],
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    rows = _json_rows(output / "case_studies.json")
    selected = tuple(row for row in rows if row.get("symbol") == symbol.strip().upper())
    if not selected:
        raise typer.BadParameter(f"case study unavailable for {symbol}")
    if as_json:
        typer.echo(json.dumps(selected[0], indent=2, sort_keys=True))
    else:
        row = selected[0]
        typer.echo(f"{row['symbol']} Feature Case Study")
        typer.echo(f"Onset: {row['onset_date'] or 'unavailable'}")
        typer.echo(f"Outcome: {row['outcome']}")
        typer.echo(f"Canonical Result: {row['canonical_result']}")
        typer.echo(str(row["explanation"]))


def _manifest(output: Path) -> dict[str, object]:
    path = output / "manifest.json"
    if not path.exists():
        raise typer.BadParameter(
            f"feature-attribution artifacts unavailable: {path}; run report first"
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise typer.BadParameter("feature-attribution manifest is invalid")
    return value


def _date_option(value: str | None, option: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(
            f"{option} must use ISO date format YYYY-MM-DD"
        ) from error


def _decimal_option(value: str, option: str) -> Decimal:
    try:
        return Decimal(value)
    except ArithmeticError as error:
        raise typer.BadParameter(f"{option} must be a decimal value") from error


def _population_summary(manifest: dict[str, object]) -> dict[str, object]:
    value = manifest.get("population_summary")
    if not isinstance(value, dict):
        raise typer.BadParameter("feature-attribution population summary is invalid")
    return {str(key): item for key, item in value.items()}


def _render_csv(
    path: Path,
    *,
    feature: str | None = None,
    outcome: str | None = None,
    partition: str | None = None,
    as_json: bool,
    as_csv: bool,
) -> None:
    rows = _filter(
        _csv_rows(path), feature=feature, outcome=outcome, partition=partition
    )
    _render_rows(rows, as_json=as_json, as_csv=as_csv)


def _filter(
    rows: tuple[dict[str, object], ...],
    *,
    feature: str | None = None,
    feature_group: str | None = None,
    outcome: str | None = None,
    partition: str | None = None,
) -> tuple[dict[str, object], ...]:
    result = rows
    if feature:
        result = tuple(row for row in result if row.get("feature_id") == feature)
    if feature_group:
        result = tuple(
            row for row in result if row.get("feature_group") == feature_group.upper()
        )
    if outcome:
        result = tuple(
            row for row in result if row.get("outcome_id") == outcome.upper()
        )
    if partition:
        result = tuple(
            row for row in result if row.get("partition") == partition.upper()
        )
    return result


def _render_rows(
    rows: tuple[dict[str, object], ...], *, as_json: bool, as_csv: bool
) -> None:
    if as_json:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    if as_csv:
        if not rows:
            return
        fields = tuple(dict.fromkeys(key for row in rows for key in row))
        typer.echo(",".join(fields))
        for row in rows:
            typer.echo(",".join(str(row.get(field, "")) for field in fields))
        return
    for row in rows[:100]:
        typer.echo(" | ".join(f"{key}: {value}" for key, value in row.items()))
    if len(rows) > 100:
        typer.echo(
            f"Showing 100 of {len(rows)} rows. Use --csv or --json for complete output."
        )


def _csv_rows(path: Path) -> tuple[dict[str, object], ...]:
    if not path.exists():
        raise typer.BadParameter(
            f"feature-attribution artifact unavailable: {path}; run report first"
        )
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _json_rows(path: Path) -> tuple[dict[str, object], ...]:
    if not path.exists():
        raise typer.BadParameter(
            f"feature-attribution artifact unavailable: {path}; run report first"
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise typer.BadParameter(f"feature-attribution artifact is invalid: {path}")
    return tuple(value)


def _echo_file(path: Path) -> None:
    if not path.exists():
        raise typer.BadParameter(
            f"feature-attribution artifact unavailable: {path}; run report first"
        )
    typer.echo(path.read_text(encoding="utf-8"), nl=False)


__all__ = ["feature_attribution_app"]
