from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from pathlib import Path

import typer

from alpha.config import settings
from alpha.market_truth.warehouse.models import Exchange, WarehouseDataset
from alpha.market_truth.warehouse.rendering import (
    export_csv,
    export_json,
    render_authorisations,
    render_coverage,
    render_ingestion,
    render_quality,
    render_reconciliation,
    render_status,
)
from alpha.market_truth.warehouse.warehouse_engine import HistoricalMarketWarehouse

warehouse_app = typer.Typer(help="Authoritative historical market-data warehouse.")
sessions_app = typer.Typer(help="Historical exchange-session inventory.")
identities_app = typer.Typer(help="Point-in-time security identity audits.")
corporate_actions_app = typer.Typer(help="Corporate-action warehouse audits.")
adjustments_app = typer.Typer(help="Price-adjustment audits and builds.")
universe_app = typer.Typer(
    help="Point-in-time historical universe.", invoke_without_command=True
)
warehouse_app.add_typer(sessions_app, name="sessions")
warehouse_app.add_typer(identities_app, name="identities")
warehouse_app.add_typer(corporate_actions_app, name="corporate-actions")
warehouse_app.add_typer(adjustments_app, name="adjustments")
warehouse_app.add_typer(universe_app, name="universe")


@warehouse_app.command(name="status")
def status(root: Path = typer.Option(Path("data/market_truth"), "--root")) -> None:
    _print(render_status(_warehouse(root).status()))


@warehouse_app.command(name="authorisations")
def authorisations(
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
    json_path: Path | None = typer.Option(None, "--json"),
    csv_path: Path | None = typer.Option(None, "--csv"),
) -> None:
    records = _warehouse(root).authorisations.records()
    _exports(records, json_path, csv_path)
    _print(render_authorisations(records))


@warehouse_app.command(name="import-file")
def import_file(
    path: Path = typer.Argument(..., exists=True, dir_okay=False),
    exchange: Exchange = typer.Option(..., "--exchange"),
    dataset: WarehouseDataset = typer.Option(..., "--dataset"),
    authorisation: str = typer.Option(..., "--authorisation"),
    lawfully_obtained: bool = typer.Option(False, "--lawfully-obtained"),
    trading_date: str | None = typer.Option(None, "--trading-date"),
    publication_timestamp: str | None = typer.Option(None, "--published-at"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    result = _warehouse(root).import_file(
        path,
        exchange=exchange,
        dataset=dataset,
        authorisation_record_id=authorisation,
        lawfully_obtained=lawfully_obtained,
        trading_date=None if trading_date is None else date.fromisoformat(trading_date),
        publication_timestamp=(
            None
            if publication_timestamp is None
            else datetime.fromisoformat(publication_timestamp)
        ),
    )
    _print(render_ingestion(result))


@warehouse_app.command(name="import-directory")
def import_directory(
    directory: Path = typer.Argument(..., exists=True, file_okay=False),
    exchange: Exchange = typer.Option(..., "--exchange"),
    dataset: WarehouseDataset = typer.Option(..., "--dataset"),
    authorisation: str = typer.Option(..., "--authorisation"),
    lawfully_obtained: bool = typer.Option(False, "--lawfully-obtained"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    results = _warehouse(root).ingestion.import_directory(
        directory,
        exchange=exchange,
        dataset=dataset,
        authorisation_record_id=authorisation,
        lawfully_obtained=lawfully_obtained,
    )
    lines = ["Warehouse Directory Import", f"Files Processed: {len(results)}"]
    lines.extend(
        f"- {item.source_file.original_filename}: {item.status.value}; "
        f"accepted={item.accepted_records}; rejected={item.rejected_records}"
        for item in results
    )
    _print(tuple(lines))


@warehouse_app.command(name="acquire")
def acquire(
    authorisation: str = typer.Option(..., "--authorisation"),
    session_date: str = typer.Option(..., "--date"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    warehouse = _warehouse(root)
    warehouse.policy.permit_automated(
        authorisation, on_date=date.fromisoformat(session_date)
    )
    _print(
        (
            "Warehouse Acquisition",
            "Authorisation: accepted",
            "Transport: unavailable; configure an authorised provider adapter.",
            "No archive download was attempted.",
        )
    )


@warehouse_app.command(name="backfill")
def backfill(
    directory: Path = typer.Argument(..., exists=True, file_okay=False),
    exchange: Exchange = typer.Option(..., "--exchange"),
    dataset: WarehouseDataset = typer.Option(WarehouseDataset.BHAVCOPY, "--dataset"),
    authorisation: str = typer.Option(..., "--authorisation"),
    lawfully_obtained: bool = typer.Option(False, "--lawfully-obtained"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    import_directory(
        directory, exchange, dataset, authorisation, lawfully_obtained, root
    )


@warehouse_app.command(name="update")
def update(
    as_of: str = typer.Option(..., "--as-of"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    result = _warehouse(root).materialise(as_of=date.fromisoformat(as_of))
    _print(
        (
            "Warehouse Incremental Materialisation",
            f"Adjusted Records: {result.adjusted_records}",
            f"Point-in-Time Records: {result.point_in_time_records}",
            f"Weekly Bars: {result.weekly_bars}",
            f"Monthly Bars: {result.monthly_bars}",
            f"Universe Records: {result.universe_records}",
            f"Dataset Version: {result.dataset_version.version}",
            "Production Influence: false",
        )
    )


@warehouse_app.command(name="resume")
def resume(root: Path = typer.Option(Path("data/market_truth"), "--root")) -> None:
    work = _warehouse(root).ingestion.resume()
    _print(
        (
            "Warehouse Resume Queue",
            f"Items Requiring Explicit Operator Resume: {len(work)}",
            *(f"- {item}" for item in work),
        )
    )


@sessions_app.command(name="audit")
def sessions_audit(
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option(date.today().isoformat(), "--end"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    warehouse = _warehouse(root)
    warehouse.sessions.materialise(
        start=date.fromisoformat(start), end=date.fromisoformat(end)
    )
    _print(_coverage_lines(warehouse, start, end))


@sessions_app.command(name="missing")
def sessions_missing(
    exchange: Exchange | None = typer.Option(None, "--exchange"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    records = _warehouse(root).sessions.missing(exchange)
    _print(
        (
            "Missing and Incomplete Sessions",
            f"Count: {len(records)}",
            *(
                f"- {item.exchange.value} {item.session_date}: {item.state.value}"
                for item in records
            ),
        )
    )


@sessions_app.command(name="coverage")
def sessions_coverage(
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option(date.today().isoformat(), "--end"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    _print(_coverage_lines(_warehouse(root), start, end))


@warehouse_app.command(name="coverage")
def coverage(
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option(date.today().isoformat(), "--end"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    sessions_coverage(start, end, root)


@universe_app.callback()
def universe(
    ctx: typer.Context,
    session_date: str | None = typer.Option(None, "--date"),
    exchange: Exchange | None = typer.Option(None, "--exchange"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if session_date is None:
        raise typer.BadParameter("--date is required")
    warehouse = _warehouse(root)
    target = date.fromisoformat(session_date)
    exchanges = tuple(Exchange) if exchange is None else (exchange,)
    records = tuple(
        item
        for venue in exchanges
        for item in warehouse.universe.materialise(
            session_date=target,
            exchange=venue,
            identity_version="identity-current",
        )
    )
    _print(
        (
            f"Point-in-Time Universe: {target}",
            f"Securities: {len(records)}",
            f"Tradable: {sum(item.tradable for item in records)}",
            f"Research Eligible: {sum(item.eligible_for_research for item in records)}",
            *(
                f"- {item.exchange.value}:{item.symbol} - {item.eligibility_reason}"
                for item in records
            ),
        )
    )


@universe_app.command(name="audit")
def universe_audit(
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    status_value = _warehouse(root).status()
    _print(
        (
            "Point-in-Time Universe Audit",
            f"Materialised Membership Rows: {status_value.universe_records}",
            "Present-day membership is never backfilled without "
            "dated identity evidence.",
        )
    )


@identities_app.command(name="audit")
def identities_audit(
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    report = _warehouse(root).identities.audit()
    _print(
        (
            "Historical Identity Audit",
            f"Records: {report.records}",
            f"Securities: {report.securities}",
            f"Symbols: {report.symbols}",
            f"Duplicate Intervals: {report.duplicate_intervals}",
            f"Ambiguous Symbols: {report.ambiguous_symbols}",
            f"ISIN Continuity Breaks: {report.isin_continuity_breaks}",
        )
    )


@corporate_actions_app.command(name="audit")
def corporate_actions_audit(
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    actions = _warehouse(root).store.corporate_action_records()
    kinds = Counter(item.action_type.value for item in actions)
    incomplete = sum(
        item.reconciliation_status.value == "INCOMPLETE" for item in actions
    )
    quarantined = sum(
        item.reconciliation_status.value == "QUARANTINED" for item in actions
    )
    _print(
        (
            "Corporate Actions Audit",
            f"Actions: {len(actions)}",
            *(f"- {key}: {value}" for key, value in sorted(kinds.items())),
            f"Incomplete: {incomplete}",
            f"Quarantined: {quarantined}",
        )
    )


@adjustments_app.command(name="audit")
def adjustments_audit(
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    report = _warehouse(root).adjustments.audit()
    _print(
        (
            "Adjustment Audit",
            f"Actions: {report.actions}",
            f"Confirmed: {report.confirmed}",
            f"Conflicting: {report.conflicting}",
            f"Incomplete: {report.incomplete}",
            f"Quarantined: {report.quarantined}",
            f"Adjustable: {report.adjustable}",
            f"Adjusted Rows: {report.adjusted_rows}",
        )
    )


@warehouse_app.command(name="quality")
def quality(
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
    json_path: Path | None = typer.Option(None, "--json"),
) -> None:
    report = _warehouse(root).quality.audit()
    if json_path is not None:
        export_json(report, json_path)
    _print(render_quality(report))


@warehouse_app.command(name="reconcile-current")
def reconcile_current(
    current_database: Path = typer.Option(settings.database_path, "--database"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    _print(
        render_reconciliation(_warehouse(root).reconciler.reconcile(current_database))
    )


@warehouse_app.command(name="publish")
def publish(
    confirm: bool = typer.Option(False, "--confirm"),
    root: Path = typer.Option(Path("data/market_truth"), "--root"),
) -> None:
    target = _warehouse(root).publish(confirm=confirm)
    _print(
        (
            "Warehouse Publication",
            f"Published To: {target}",
            "Research consumers must request this exact dataset version through MTE.",
            "Production Influence: false",
        )
    )


@warehouse_app.command(name="report")
def report(root: Path = typer.Option(Path("data/market_truth"), "--root")) -> None:
    warehouse = _warehouse(root)
    daily = warehouse.store.daily_records()
    sources = warehouse.vault.records()
    actions = warehouse.store.corporate_action_records()
    lines = ["Authoritative Historical Warehouse Report"]
    for exchange in Exchange:
        exchange_rows = tuple(item for item in daily if item.exchange is exchange)
        dates = tuple(item.trading_date for item in exchange_rows)
        lines.extend(
            (
                f"{exchange.value} Daily Rows: {len(exchange_rows)}",
                f"{exchange.value} Date Coverage: "
                + (
                    "unavailable"
                    if not dates
                    else f"{min(dates).isoformat()} to {max(dates).isoformat()}"
                ),
                f"{exchange.value} Securities: "
                f"{len({item.security_id for item in exchange_rows})}",
            )
        )
    source_types = Counter(item.dataset_type.value for item in sources)
    action_types = Counter(item.action_type.value for item in actions)
    lines.extend(
        (
            "",
            "Archive Coverage:",
            *(f"- {key}: {value}" for key, value in sorted(source_types.items())),
            "Corporate Action Coverage:",
            *(f"- {key}: {value}" for key, value in sorted(action_types.items())),
            f"Storage Used: {_directory_size(root)} bytes",
            "",
        )
    )
    _print(
        tuple(lines)
        + render_status(warehouse.status())
        + ("",)
        + render_quality(warehouse.quality.audit())
    )


def _warehouse(root: Path) -> HistoricalMarketWarehouse:
    return HistoricalMarketWarehouse(root)


def _coverage_lines(
    warehouse: HistoricalMarketWarehouse, start: str, end: str
) -> tuple[str, ...]:
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    values = tuple(
        warehouse.sessions.coverage(exchange=item, start=start_date, end=end_date)
        for item in Exchange
    )
    return render_coverage(values)


def _exports(
    values: tuple[object, ...], json_path: Path | None, csv_path: Path | None
) -> None:
    if json_path is not None:
        export_json(values, json_path)
    if csv_path is not None:
        export_csv(values, csv_path)


def _print(lines: tuple[str, ...]) -> None:
    typer.echo("\n".join(lines))


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


__all__ = ["warehouse_app"]
