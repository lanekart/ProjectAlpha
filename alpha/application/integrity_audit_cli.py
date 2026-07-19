from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import typer

from alpha.canonical_integrity_audit.audit_service import CanonicalIntegrityAuditEngine
from alpha.canonical_integrity_audit.exports import (
    DEFAULT_INTEGRITY_OUTPUT_DIRECTORY,
    CanonicalIntegrityAuditExporter,
    load_integrity_report_payload,
)
from alpha.canonical_integrity_audit.models import (
    CANONICAL_POLICY_ID,
    LEGACY_DATASET_VERSION,
    OpportunityDefinition,
    to_primitive,
)
from alpha.canonical_integrity_audit.opportunity_events import (
    DEFAULT_OPPORTUNITY_DEFINITIONS,
)
from alpha.canonical_integrity_audit.pine_trade_import import PineTradeImporter
from alpha.canonical_integrity_audit.rendering import (
    render_executive_report,
    render_runtime_summary,
)
from alpha.canonical_integrity_audit.research_integration import (
    record_integrity_experiment,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.config.settings import settings

integrity_audit_app = typer.Typer(
    help="Audit canonical runtime integrity, Pine parity, and missed opportunities.",
    no_args_is_help=True,
)

DEFAULT_ACU_DIRECTORY = Path(".alpha/acu/ALPHA_CANONICAL_v1.0")


@integrity_audit_app.command("runtime")
def runtime_audit(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    before_acu: Annotated[Path, typer.Option("--before-acu")] = DEFAULT_ACU_DIRECTORY,
    after_acu: Annotated[Path, typer.Option("--after-acu")] = DEFAULT_ACU_DIRECTORY,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_INTEGRITY_OUTPUT_DIRECTORY,
    replay: Annotated[bool, typer.Option("--replay")] = False,
) -> None:
    """Reproduce classified failures and optionally report repaired replay."""

    report = _run(
        database=database,
        before_acu=before_acu,
        after_acu=after_acu,
        output=output,
    )
    typer.echo(render_runtime_summary(report), nl=False)
    if replay:
        typer.echo(f"Repair Replay: {report.runtime_replay.repair}")


@integrity_audit_app.command("pine-import")
def pine_import(
    directory: Annotated[Path, typer.Option("--directory")],
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_INTEGRITY_OUTPUT_DIRECTORY,
) -> None:
    """Import exact TradingView exports and separately label attestations."""

    metadata, trades = PineTradeImporter().import_directory(directory)
    output.mkdir(parents=True, exist_ok=True)
    (output / "pine_import.json").write_text(
        json.dumps(
            {
                "metadata": [to_primitive(item) for item in metadata],
                "production_influence": False,
                "trades": [to_primitive(item) for item in trades],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_rows(output / "tradingview_trades_imported.csv", trades)
    typer.echo("TradingView Evidence Import")
    typer.echo(f"Metadata Records: {len(metadata)}")
    typer.echo(f"Trade-Level CSV Trades: {len(trades)}")
    typer.echo("PRODUCTION_INFLUENCE=false")


@integrity_audit_app.command("parity")
def parity(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_INTEGRITY_OUTPUT_DIRECTORY,
) -> None:
    """Render the measured Pine-to-canonical parity result."""

    payload = load_integrity_report_payload(output)
    summary = _mapping(payload.get("summary"), "summary")
    typer.echo("TradingView-to-Alpha Parity Audit")
    typer.echo(f"Trades Imported: {summary.get('pine_trades_imported', 0)}")
    typer.echo(f"Exact Parity Rate: {_percent(summary.get('exact_parity_rate'))}")
    typer.echo(
        f"Exact + Semantic Rate: {_percent(summary.get('semantic_parity_rate'))}"
    )
    typer.echo(f"Largest Divergence: {summary.get('largest_divergence_stage')}")


@integrity_audit_app.command("opportunities")
def opportunities(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_INTEGRITY_OUTPUT_DIRECTORY,
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    event_definition: Annotated[str | None, typer.Option("--event-definition")] = None,
) -> None:
    """Show deterministic major-opportunity event coverage."""

    payload = load_integrity_report_payload(output)
    rows = _sequence(payload.get("opportunities"), "opportunities")
    selected = [
        _mapping(item, "opportunity")
        for item in rows
        if (
            symbol is None
            or _mapping(item, "opportunity").get("symbol") == symbol.upper()
        )
        and (
            event_definition is None
            or _mapping(item, "opportunity").get("event_definition")
            == event_definition.upper()
        )
    ]
    typer.echo("Major Opportunity Coverage Audit")
    typer.echo(f"Events: {len(selected)}")
    for item in selected[:50]:
        typer.echo(
            f"- {item.get('symbol')} {item.get('start_date')}: "
            f"{item.get('event_definition')} return={item.get('forward_return')}"
        )


@integrity_audit_app.command("missed")
def missed(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_INTEGRITY_OUTPUT_DIRECTORY,
) -> None:
    """Show missed, rejected, data-blocked, and runtime-blocked opportunities."""

    payload = load_integrity_report_payload(output)
    rows = tuple(
        _mapping(item, "coverage")
        for item in _sequence(payload.get("coverage"), "coverage")
        if _mapping(item, "coverage").get("classification")
        in {"MISSED", "REJECTED", "RUNTIME_BLOCKED", "DATA_BLOCKED"}
    )
    typer.echo("Missed Opportunity Attribution")
    typer.echo(f"Missed / Rejected / Blocked: {len(rows)}")
    for item in rows[:50]:
        typer.echo(
            f"- {item.get('symbol')} {item.get('classification')}: "
            f"{item.get('primary_blocker')}"
        )


@integrity_audit_app.command("zero-trades")
def zero_trades(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_INTEGRITY_OUTPUT_DIRECTORY,
) -> None:
    """Explain every symbol with no canonical institutional trade."""

    payload = load_integrity_report_payload(output)
    rows = _sequence(payload.get("zero_trades"), "zero_trades")
    typer.echo("Zero-Trade Diagnostics")
    typer.echo(f"Symbols: {len(rows)}")
    counts: dict[str, int] = {}
    for value in rows:
        row = _mapping(value, "zero trade")
        reason = str(row.get("explanation"))
        counts[reason] = counts.get(reason, 0) + 1
    for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        typer.echo(f"- {reason}: {count}")


@integrity_audit_app.command("case-study")
def case_study(
    symbol: Annotated[str, typer.Option("--symbol")],
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_INTEGRITY_OUTPUT_DIRECTORY,
) -> None:
    """Print one mandatory symbol trace."""

    payload = load_integrity_report_payload(output)
    studies = tuple(
        _mapping(item, "case study")
        for item in _sequence(payload.get("case_studies"), "case studies")
    )
    selected = next(
        (
            item
            for item in studies
            if item.get("requested_symbol") == symbol.upper()
            or item.get("resolved_symbol") == symbol.upper()
        ),
        None,
    )
    if selected is None:
        raise typer.BadParameter(f"case study unavailable for {symbol.upper()}")
    typer.echo(json.dumps(selected, indent=2, sort_keys=True))


@integrity_audit_app.command("report")
def report(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    before_acu: Annotated[Path, typer.Option("--before-acu")] = DEFAULT_ACU_DIRECTORY,
    after_acu: Annotated[Path, typer.Option("--after-acu")] = DEFAULT_ACU_DIRECTORY,
    pine_directory: Annotated[Path | None, typer.Option("--pine-directory")] = None,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_INTEGRITY_OUTPUT_DIRECTORY,
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    event_definition: Annotated[str | None, typer.Option("--event-definition")] = None,
    policy_version: Annotated[
        str, typer.Option("--policy-version")
    ] = CANONICAL_POLICY_ID,
    dataset_version: Annotated[
        str, typer.Option("--dataset-version")
    ] = LEGACY_DATASET_VERSION,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    csv_output: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    """Run and export the integrated canonical integrity audit."""

    if policy_version != CANONICAL_POLICY_ID:
        raise typer.BadParameter(f"only {CANONICAL_POLICY_ID} is auditable")
    if dataset_version != LEGACY_DATASET_VERSION:
        raise typer.BadParameter(f"only {LEGACY_DATASET_VERSION} is available")
    definitions = _definitions(event_definition)
    with LegacyMarketDataStore(database) as store:
        audit = CanonicalIntegrityAuditEngine().run(
            store=store,
            before_acu_directory=before_acu,
            after_acu_directory=after_acu,
            pine_directory=pine_directory,
            start=_date(start),
            end=_date(end),
            symbol=symbol,
            definitions=definitions,
        )
    paths = CanonicalIntegrityAuditExporter().export(audit, output_directory=output)
    record_integrity_experiment(audit)
    typer.echo(render_executive_report(audit), nl=False)
    if json_output:
        typer.echo(f"JSON: {output / 'integrity_audit.json'}")
    if csv_output:
        typer.echo(f"CSV Artifacts: {sum(path.suffix == '.csv' for path in paths)}")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def _run(
    *,
    database: Path,
    before_acu: Path,
    after_acu: Path,
    output: Path,
) -> Any:
    with LegacyMarketDataStore(database) as store:
        audit = CanonicalIntegrityAuditEngine().run(
            store=store,
            before_acu_directory=before_acu,
            after_acu_directory=after_acu,
        )
    CanonicalIntegrityAuditExporter().export(audit, output_directory=output)
    return audit


def _definitions(value: str | None) -> tuple[OpportunityDefinition, ...]:
    if value is None:
        return DEFAULT_OPPORTUNITY_DEFINITIONS
    normalized = value.strip().upper()
    selected = tuple(
        item for item in DEFAULT_OPPORTUNITY_DEFINITIONS if item.name == normalized
    )
    if not selected:
        raise typer.BadParameter(f"unknown event definition: {value}")
    return selected


def _date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("dates must use YYYY-MM-DD") from error


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise typer.BadParameter(f"invalid integrity {label} artifact")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise typer.BadParameter(f"invalid integrity {label} artifact")
    return tuple(value)


def _percent(value: object) -> str:
    if value is None:
        return "unavailable"
    from decimal import Decimal

    return f"{Decimal(str(value)) * 100:.2f}%"


def _write_rows(path: Path, rows: tuple[object, ...]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    first = to_primitive(rows[0])
    if not isinstance(first, dict):
        raise TypeError("Pine CSV row must be an object")
    columns = tuple(first)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for item in rows:
            primitive = to_primitive(item)
            assert isinstance(primitive, dict)
            writer.writerow(
                {
                    key: (
                        json.dumps(value, sort_keys=True)
                        if isinstance(value, (dict, list))
                        else value
                    )
                    for key, value in primitive.items()
                }
            )


__all__ = ["integrity_audit_app"]
