from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import Annotated, Any

import typer

from alpha.application.governed_adjusted_benchmark_cli import (
    register_governed_adjusted_benchmark_command,
)
from alpha.application.governed_adjusted_stability_cli import (
    register_governed_adjusted_stability_command,
)
from alpha.benchmark_replay import (
    DEFAULT_BENCHMARK_OUTPUT,
    BenchmarkArtifactExporter,
    BenchmarkPolicy,
    CanonicalBenchmarkReplayEngine,
    ReplayRequest,
    render_replay_summary,
)
from alpha.benchmark_replay.signal_audit import (
    export_diagnostic_signal_audit,
    run_diagnostic_signal_audit,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.config.settings import settings
from alpha.historical_truth.replay import HistoricalTruthReplayStore

benchmark_app = typer.Typer(
    help="Run and inspect the immutable Canonical Alpha Benchmark Replay.",
    no_args_is_help=True,
)

register_governed_adjusted_benchmark_command(benchmark_app)
register_governed_adjusted_stability_command(benchmark_app)


@benchmark_app.command("replay")
def benchmark_replay(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    historical_truth_snapshots: Annotated[
        Path | None,
        typer.Option("--historical-truth-snapshots"),
    ] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
    capital: Annotated[str, typer.Option("--capital")] = "1000000",
    max_positions: Annotated[int, typer.Option("--max-positions", min=1)] = 3,
    transaction_cost: Annotated[str, typer.Option("--transaction-cost")] = "0.20",
    slippage: Annotated[str, typer.Option("--slippage")] = "0.10",
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_csv: Annotated[bool, typer.Option("--csv")] = False,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Execute the frozen current Alpha stack over observed market history."""

    policy = BenchmarkPolicy(
        initial_capital=_decimal(capital, "capital"),
        maximum_positions=max_positions,
        transaction_cost_percent=_decimal(transaction_cost, "transaction cost"),
        slippage_percent=_decimal(slippage, "slippage"),
    )
    replay_start = _date(start)
    replay_end = _date(end)
    store = (
        HistoricalTruthReplayStore(
            database_path=database,
            snapshot_root=historical_truth_snapshots,
            start=replay_start,
            end=replay_end,
        )
        if historical_truth_snapshots is not None
        else LegacyMarketDataStore(database)
    )
    with store:
        report = CanonicalBenchmarkReplayEngine().run(
            store=store,
            request=ReplayRequest(
                start=replay_start,
                end=replay_end,
                policy=policy,
            ),
            project_root=settings.project_root,
            progress=None if quiet else _progress,
        )
    destination = output or Path(".alpha/benchmark") / report.manifest.run_id
    paths = BenchmarkArtifactExporter().export(
        report,
        output_directory=destination,
    )
    if as_json:
        typer.echo(json.dumps(_summary(report), indent=2, sort_keys=True))
    elif as_csv:
        stream = StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=tuple(_summary(report)))
        writer.writeheader()
        writer.writerow(_summary(report))
        typer.echo(stream.getvalue(), nl=False)
    else:
        typer.echo(render_replay_summary(report), nl=False)
    typer.echo(f"Artifacts: {destination} ({len(paths)} files)")


@benchmark_app.command("signal-audit")
def benchmark_signal_audit(
    benchmark_output: Annotated[Path, typer.Option("--benchmark-output")] = (
        DEFAULT_BENCHMARK_OUTPUT
    ),
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    historical_truth_snapshots: Annotated[
        Path | None,
        typer.Option("--historical-truth-snapshots"),
    ] = None,
    audit_output: Annotated[Path | None, typer.Option("--audit-output")] = None,
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
) -> None:
    """Audit raw BUY/STRONG BUY signals using future observations only as labels."""

    replay_start = _date(start)
    replay_end = _date(end)
    store = (
        HistoricalTruthReplayStore(
            database_path=database,
            snapshot_root=historical_truth_snapshots,
            start=replay_start,
            end=replay_end,
        )
        if historical_truth_snapshots is not None
        else LegacyMarketDataStore(database)
    )
    approvals = benchmark_output / "approval_statistics.csv"
    destination = audit_output or benchmark_output / "diagnostic_signal_audit"
    with store:
        audit = run_diagnostic_signal_audit(
            store=store,
            approval_statistics=approvals,
        )
    paths = export_diagnostic_signal_audit(
        audit,
        output_directory=destination,
    )
    typer.echo("Diagnostic Signal Audit")
    typer.echo(
        f"Raw BUY/STRONG BUY signals: {audit.summary['raw_buy_or_strong_buy_signals']}"
    )
    typer.echo("DIAGNOSTIC_ONLY=true")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {destination} ({len(paths)} files)")


@benchmark_app.command("report")
def benchmark_report(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_BENCHMARK_OUTPUT,
) -> None:
    """Print the permanent benchmark executive report."""

    typer.echo(_read(output / "executive_report.md"), nl=False)


@benchmark_app.command("trades")
def benchmark_trades(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_BENCHMARK_OUTPUT,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 50,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show executed logical trades and exit attribution."""

    rows = _csv_rows(output / "trade_log.csv")[:limit]
    if as_json:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    typer.echo("Canonical Benchmark Trades")
    if not rows:
        typer.echo("No trades executed under the frozen approval policy.")
    for index, row in enumerate(rows, start=1):
        typer.echo(
            f"{index}. {row['symbol']}: {row['entry_date']} to {row['exit_date']}; "
            f"net={row['net_return_percent']}%; exit={row['exit_reason']}"
        )
    typer.echo("PRODUCTION_INFLUENCE=false")


@benchmark_app.command("portfolio")
def benchmark_portfolio(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_BENCHMARK_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show portfolio performance and capital deployment."""

    rows = _csv_rows(output / "portfolio_statistics.csv")
    row = rows[0] if rows else {}
    if as_json:
        typer.echo(json.dumps(row, indent=2, sort_keys=True))
        return
    typer.echo("Canonical Benchmark Portfolio")
    for label, key in (
        ("Starting Capital", "starting_capital"),
        ("Ending Capital", "ending_capital"),
        ("CAGR", "cagr_percent"),
        ("Maximum Drawdown", "maximum_drawdown_percent"),
        ("Sharpe", "sharpe_ratio"),
        ("Sortino", "sortino_ratio"),
        ("Average Utilisation", "average_capital_utilisation_percent"),
        ("Average Idle Cash", "average_idle_cash"),
    ):
        typer.echo(f"{label}: {row.get(key) or 'unavailable'}")
    typer.echo("PRODUCTION_INFLUENCE=false")


@benchmark_app.command("opportunity")
def benchmark_opportunity(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_BENCHMARK_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show major-opportunity capture and rejection evidence."""

    rows = _csv_rows(output / "opportunity_capture.csv")
    if as_json:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    typer.echo("Canonical Benchmark Opportunity Capture")
    for row in rows:
        typer.echo(
            f"- {row['opportunity_definition']}: major={row['major_opportunities']}, "
            f"tradable={row['tradable_opportunities']}, "
            f"captured={row['captured']}, rate="
            f"{row['capture_rate_percent'] or 'unavailable'}%"
        )
    typer.echo("PRODUCTION_INFLUENCE=false")


def _summary(report: Any) -> dict[str, object]:
    stats = report.portfolio_statistics
    opportunity = next(
        (
            item
            for item in report.opportunity_capture
            if item.opportunity_definition == "ALL"
        ),
        None,
    )
    return {
        "baseline_id": report.manifest.baseline_id,
        "sessions": report.manifest.sessions,
        "eligible_securities": report.eligible_securities,
        "eligible_security_observations": report.eligible_security_observations,
        "total_candidates": sum(
            item.technical_candidates for item in report.candidate_statistics
        ),
        "total_approvals": sum(
            item.institutional_approvals for item in report.candidate_statistics
        ),
        "trades_executed": stats.logical_trades,
        "win_rate_percent": stats.win_rate_percent,
        "profit_factor": stats.profit_factor,
        "expectancy_percent": stats.expectancy_percent,
        "cagr_percent": stats.cagr_percent,
        "maximum_drawdown_percent": stats.maximum_drawdown_percent,
        "sharpe_ratio": stats.sharpe_ratio,
        "sortino_ratio": stats.sortino_ratio,
        "calmar_ratio": stats.calmar_ratio,
        "average_capital_utilisation_percent": (
            stats.average_capital_utilisation_percent
        ),
        "average_idle_cash": stats.average_idle_cash,
        "opportunity_capture_rate_percent": (
            None if opportunity is None else opportunity.capture_rate_percent
        ),
        "production_influence": False,
    }


def _progress(current: int, total: int, observed_on: date) -> None:
    if current == 1 or current == total or current % 100 == 0:
        typer.echo(
            f"CABR progress: {current}/{total} through {observed_on}",
            err=True,
        )


def _date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("dates must use YYYY-MM-DD") from error


def _decimal(value: str, label: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise typer.BadParameter(f"{label} must be numeric") from error
    if parsed < 0:
        raise typer.BadParameter(f"{label} cannot be negative")
    return parsed


def _read(path: Path) -> str:
    if not path.exists():
        raise typer.BadParameter(
            "benchmark artifacts unavailable; run benchmark replay"
        )
    return path.read_text(encoding="utf-8")


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise typer.BadParameter(
            "benchmark artifacts unavailable; run benchmark replay"
        )
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


__all__ = ["benchmark_app"]
