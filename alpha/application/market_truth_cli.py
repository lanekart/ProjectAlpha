from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import typer

from alpha.market_truth.market_truth_engine import MarketTruthEngine
from alpha.market_truth.models import DatasetKind, MarketTruth
from alpha.market_truth.rendering import (
    export_truth_csv,
    export_truth_json,
    render_health,
    render_providers,
    render_system_report,
    render_truth,
)

market_truth_app = typer.Typer(
    help="Unified, fail-closed historical and live market truth."
)


@market_truth_app.command(name="providers")
def providers(
    remote: bool = typer.Option(False, "--remote"),
    database: Path | None = typer.Option(None, "--database"),
) -> None:
    engine = _engine(remote=remote, database=database)
    _print(render_providers(engine.registry.descriptors()))


@market_truth_app.command(name="health")
def health(
    remote: bool = typer.Option(False, "--remote"),
    database: Path | None = typer.Option(None, "--database"),
) -> None:
    _print(render_health(_engine(remote=remote, database=database).health()))


@market_truth_app.command(name="quality")
def quality(
    symbol: str = typer.Option(..., "--symbol"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    remote: bool = typer.Option(False, "--remote"),
    database: Path | None = typer.Option(None, "--database"),
) -> None:
    truth = _daily(_engine(remote=remote, database=database), symbol, start, end)
    _print(render_truth(truth, title="Market Truth Quality Report"))


@market_truth_app.command(name="confidence")
def confidence(
    symbol: str = typer.Option(..., "--symbol"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    remote: bool = typer.Option(False, "--remote"),
    database: Path | None = typer.Option(None, "--database"),
) -> None:
    truth = _daily(_engine(remote=remote, database=database), symbol, start, end)
    _print(render_truth(truth, title="Market Truth Confidence Report"))


@market_truth_app.command(name="identity")
def identity(
    symbols: str = typer.Option("", "--symbols"),
    as_of: str = typer.Option("today", "--as-of"),
    database: Path | None = typer.Option(None, "--database"),
) -> None:
    truth = _engine(database=database).identity.resolve(
        symbols=_symbols(symbols),
        as_of=_date(as_of),
    )
    _print(render_truth(truth, title="Market Truth Identity"))


@market_truth_app.command(name="corporate-actions")
def corporate_actions(
    symbols: str = typer.Option("", "--symbols"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    as_of: str = typer.Option("today", "--as-of"),
    database: Path | None = typer.Option(None, "--database"),
) -> None:
    truth = _engine(database=database).corporate_actions.events(
        symbols=_symbols(symbols),
        start=_date(start),
        end=_date(end),
        as_of=_date(as_of),
    )
    _print(render_truth(truth, title="Market Truth Corporate Actions"))


@market_truth_app.command(name="daily")
def daily(
    symbol: str = typer.Option(..., "--symbol"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    remote: bool = typer.Option(False, "--remote"),
    database: Path | None = typer.Option(None, "--database"),
    json_path: Path | None = typer.Option(None, "--json"),
    csv_path: Path | None = typer.Option(None, "--csv"),
) -> None:
    truth = _daily(_engine(remote=remote, database=database), symbol, start, end)
    _export(truth, json_path, csv_path)
    _print(render_truth(truth, title="Market Truth Daily"))


@market_truth_app.command(name="weekly")
def weekly(
    symbol: str = typer.Option(..., "--symbol"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    remote: bool = typer.Option(False, "--remote"),
    database: Path | None = typer.Option(None, "--database"),
) -> None:
    engine = _engine(remote=remote, database=database)
    truth = engine.historical.weekly(
        symbols=(symbol,), start=_date(start), end=_date(end), as_of=_date(end)
    )
    _print(render_truth(truth, title="Market Truth Weekly"))


@market_truth_app.command(name="monthly")
def monthly(
    symbol: str = typer.Option(..., "--symbol"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    remote: bool = typer.Option(False, "--remote"),
    database: Path | None = typer.Option(None, "--database"),
) -> None:
    engine = _engine(remote=remote, database=database)
    truth = engine.historical.monthly(
        symbols=(symbol,), start=_date(start), end=_date(end), as_of=_date(end)
    )
    _print(render_truth(truth, title="Market Truth Monthly"))


@market_truth_app.command(name="intraday")
def intraday(
    symbol: str = typer.Option(..., "--symbol"),
    interval: DatasetKind = typer.Option(DatasetKind.MINUTE_1, "--interval"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    database: Path | None = typer.Option(None, "--database"),
) -> None:
    if interval not in {
        DatasetKind.TICK,
        DatasetKind.MINUTE_1,
        DatasetKind.MINUTE_5,
    }:
        raise typer.BadParameter(
            "intraday interval must be TICK, MINUTE_1, or MINUTE_5"
        )
    engine = _engine(database=database)
    start_at = _datetime(start)
    end_at = _datetime(end)
    if interval is DatasetKind.TICK:
        truth = engine.intraday.ticks(
            symbols=(symbol,), start=start_at, end=end_at, as_of=end_at
        )
    elif interval is DatasetKind.MINUTE_1:
        truth = engine.intraday.one_minute(
            symbols=(symbol,), start=start_at, end=end_at, as_of=end_at
        )
    else:
        truth = engine.intraday.five_minute(
            symbols=(symbol,), start=start_at, end=end_at, as_of=end_at
        )
    _print(render_truth(truth, title="Market Truth Intraday"))


@market_truth_app.command(name="report")
def report(
    remote: bool = typer.Option(False, "--remote"),
    database: Path | None = typer.Option(None, "--database"),
) -> None:
    _print(render_system_report(_engine(remote=remote, database=database).report()))


def _engine(
    *,
    remote: bool = False,
    database: Path | None = None,
) -> MarketTruthEngine:
    return MarketTruthEngine.default(include_remote=remote, database_path=database)


def _daily(
    engine: MarketTruthEngine,
    symbol: str,
    start: str,
    end: str,
) -> MarketTruth:
    return engine.historical.daily(
        symbols=(symbol,), start=_date(start), end=_date(end), as_of=_date(end)
    )


def _date(value: str) -> date:
    return date.today() if value == "today" else date.fromisoformat(value)


def _datetime(value: str) -> datetime:
    if value == "now":
        return datetime.now(tz=UTC)
    parsed = datetime.fromisoformat(value)
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


def _symbols(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _export(
    truth: MarketTruth,
    json_path: Path | None,
    csv_path: Path | None,
) -> None:
    if json_path is not None:
        export_truth_json(truth, json_path)
    if csv_path is not None:
        export_truth_csv(truth, csv_path)


def _print(lines: tuple[str, ...]) -> None:
    typer.echo("\n".join(lines))


__all__ = ["market_truth_app"]
