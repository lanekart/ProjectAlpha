from __future__ import annotations

import asyncio
from datetime import date as dt_date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import typer

from alpha.application.backtest import BacktestApplicationService, BacktestSummary
from alpha.application.backtest_export import BacktestExportService
from alpha.application.historical_ingestion import HistoricalIngestionService
from alpha.application.intelligence import (
    IntelligenceRun,
    _allocation_reason,
    _allocation_status,
    _capital_deployment_dashboard_lines,
    _execution_status,
    _recommendation_detail_lines,
    _sector_metadata_notice,
    _verdict_label,
)
from alpha.application.intelligence_export import IntelligenceExportService
from alpha.application.research_cli import research_app
from alpha.application.runtime import ProjectAlphaRuntime
from alpha.application.runtime_models import RuntimeResult
from alpha.backtest.backtest_report import BacktestReportRenderer
from alpha.exceptions import BhavcopyNotFoundError, ProjectAlphaError
from alpha.live import (
    InstrumentSubscription,
    UpstoxLiveMarketDataProvider,
    run_live_monitor,
)
from alpha.performance_intelligence import (
    PerformanceIntelligenceService,
    RecommendationLedgerRepository,
    RecommendationPerformanceRecorder,
    render_update_summary,
    resolve_ledger_path,
)
from alpha.release import current_release
from alpha.version import __version__

app = typer.Typer()
performance_app = typer.Typer()
app.add_typer(research_app, name="research")
app.add_typer(performance_app, name="performance")


@app.command()
def version() -> None:
    print(__version__)


@app.command()
def doctor() -> None:
    """
    Print Project Alpha release and quality gate metadata.
    """

    release = current_release()
    print("\n".join(release.as_lines()))


@app.command()
def live(
    symbols: list[str] | None = typer.Option(
        None,
        "--symbols",
        help="Comma-separated NSE symbols to monitor.",
    ),
    symbol: list[str] | None = typer.Option(
        None,
        "--symbol",
        help="Repeatable NSE symbol to monitor.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Print live feed diagnostics and latency details.",
    ),
) -> None:
    """
    Monitor live market data without fabricating fallback prices.
    """

    provider = UpstoxLiveMarketDataProvider.from_environment()
    parsed_symbols = _parse_live_symbols(symbols=symbols, repeated_symbols=symbol)
    subscriptions = tuple(
        InstrumentSubscription(symbol=symbol, instrument_key=f"NSE_EQ|{symbol}")
        for symbol in parsed_symbols
    )
    if not provider.configured():
        print("Live feed unavailable.")
        print("Reason: Upstox credentials are not configured.")
        print("Required env vars: UPSTOX_ACCESS_TOKEN")
        print("No live recommendations generated.")
        return
    print("Live Market Monitor")
    print(f"Provider: Upstox ({provider.websocket_url})")
    print("Subscriptions:")
    for subscription in subscriptions:
        print(f"- {subscription.symbol}: {subscription.instrument_key}")
    snapshots = asyncio.run(
        run_live_monitor(
            provider=provider,
            subscriptions=subscriptions,
            max_ticks=1,
        )
    )
    for snapshot in snapshots:
        _print_live_snapshot(snapshot, verbose=verbose)


def _parse_live_symbols(
    *,
    symbols: list[str] | None,
    repeated_symbols: list[str] | None,
) -> tuple[str, ...]:
    raw_values: list[str] = []
    for value in symbols or []:
        raw_values.extend(value.split(","))
    raw_values.extend(repeated_symbols or [])
    parsed = tuple(
        dict.fromkeys(value.strip().upper() for value in raw_values if value.strip())
    )
    if not parsed:
        raise typer.BadParameter(
            "Provide at least one symbol via --symbols A,B or repeated --symbol A."
        )
    return parsed


def _print_live_snapshot(snapshot: object, *, verbose: bool) -> None:
    health = getattr(snapshot, "feed_health", None)
    latency = getattr(snapshot, "latency", None)
    warnings = tuple(getattr(snapshot, "warnings", ()))
    tick_quality = getattr(snapshot, "tick_quality", None)
    feed_status = (
        health.status.value if health is not None else getattr(snapshot, "feed_status")
    )
    feed_quality = (
        f"{health.feed_quality_score}/100" if health is not None else "unavailable"
    )
    latency_text = (
        str(latency.rolling_average_seconds)
        if latency is not None and latency.rolling_average_seconds is not None
        else "unavailable"
    )

    print("\nProvider")
    print(f"Status: {feed_status}")
    print(f"Latency: {latency_text}")
    print(f"Feed Quality: {feed_quality}")
    print("Active Symbols: 1")
    print(f"Last Tick: {getattr(snapshot, 'bar_started_at').isoformat()}")
    print(
        "Warnings: "
        + (", ".join(warning.warning_type.value for warning in warnings) or "none")
    )

    print(f"\n{getattr(snapshot, 'symbol')}")
    print(f"Price: ₹{getattr(snapshot, 'price')}")
    print("Change: unavailable")
    print(f"Volume: {getattr(snapshot, 'volume')}")
    print(f"VWAP: {getattr(snapshot, 'vwap') or 'unavailable'}")
    print(f"Current Bar: {getattr(snapshot, 'bar_started_at').isoformat()}")
    print(f"Feed Age: {'stale' if getattr(snapshot, 'stale') else 'fresh'}")
    print(f"Tick Count: {getattr(snapshot, 'tick_count', 0)}")
    print(f"Recommendation: {getattr(snapshot, 'action_now')}")
    print(
        "Risk Flags: " + (", ".join(warning.message for warning in warnings) or "none")
    )

    if not verbose:
        return

    print("\nTick Diagnostics")
    if tick_quality is None:
        print("Status: unavailable")
    else:
        print(f"Status: {tick_quality.status.value}")
        print(f"Reasons: {', '.join(tick_quality.reasons) or 'none'}")

    print("\nLatency Breakdown")
    if latency is None or latency.sample_count == 0:
        print("Latency samples: unavailable")
    else:
        print(f"Samples: {latency.sample_count}")
        print(f"Rolling Average: {latency.rolling_average_seconds}")
        print(f"Rolling Max: {latency.rolling_max_seconds}")
        print(f"Rolling P95: {latency.rolling_p95_seconds}")
        print(f"Rolling P99: {latency.rolling_p99_seconds}")

    print("\nRejected Ticks")
    print("Invalid ticks are rejected before bar building.")

    print("\nSession State")
    if health is None:
        print("Health: unavailable")
    else:
        print(f"Health: {health.status.value}")
        print(f"Heartbeat Age: {health.heartbeat_age_seconds or 'unavailable'}")
        print(f"Reconnect Attempts: {health.reconnect_attempts}")

    print("\nHealth History")
    if health is None or not health.reasons:
        print("No health warnings.")
    else:
        for reason in health.reasons:
            print(f"- {reason}")


@app.command()
def download(date: str = "today") -> None:
    """
    Download NSE bhavcopy.
    """

    service = HistoricalIngestionService()
    try:
        count = service.download_only(date)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Data download failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    print(f"Downloaded records: {count}")


@app.command()
def report(date: str = "today") -> None:
    """
    Generate daily report.
    """

    service = HistoricalIngestionService()
    try:
        report_data = service.generate_report(date)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Report generation failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    print("\n📊 NSE DAILY REPORT\n")
    print(f"Observed On: {report_data['observed_on']}")

    print("\n🔥 Top Gainers:")
    print(
        report_data["top_gainers"]
        .loc[:, ["symbol", "momentum_score"]]
        .to_string(index=False)
    )

    print("\n📉 Top Losers:")
    print(
        report_data["top_losers"]
        .loc[:, ["symbol", "momentum_score"]]
        .to_string(index=False)
    )

    print("\n📈 Market Regime:", report_data["regime"])


@app.command(name="run")
def run_daily(
    date: str = "today",
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Use deterministic demo inputs instead of live analysis.",
    ),
    export_json: Path | None = typer.Option(
        None,
        "--export-json",
        help="Write deterministic daily intelligence JSON to this path.",
    ),
    export_text: Path | None = typer.Option(
        None,
        "--export-text",
        help="Write deterministic daily intelligence text to this path.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Render full strategy, evidence, and portfolio details.",
    ),
) -> None:
    """
    Run the daily Project Alpha investment workflow.
    """

    _validate_command_export_paths(export_json=export_json, export_text=export_text)

    try:
        runtime_result = _run_daily_runtime(date=date, demo=demo)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Daily run failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    _print_daily_runtime_result(runtime_result, verbose=verbose)
    _record_recommendation_performance(runtime_result)
    _export_intelligence_run(
        run=runtime_result.intelligence_run,
        export_json=export_json,
        export_text=export_text,
    )


@app.command()
def intelligence(
    date: str = "today",
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Use deterministic demo intelligence inputs instead of live analysis.",
    ),
    export_json: Path | None = typer.Option(
        None,
        "--export-json",
        help="Write deterministic recommendation intelligence JSON to this path.",
    ),
    export_text: Path | None = typer.Option(
        None,
        "--export-text",
        help="Write deterministic recommendation intelligence text to this path.",
    ),
) -> None:
    """
    Run the intelligence orchestration report.
    """

    _validate_command_export_paths(export_json=export_json, export_text=export_text)

    try:
        runtime_result = _run_intelligence_runtime(date=date, demo=demo)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Intelligence generation failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    print()
    for line in runtime_result.summary_lines:
        print(line)

    _record_recommendation_performance(runtime_result)
    _export_intelligence_run(
        run=runtime_result.intelligence_run,
        export_json=export_json,
        export_text=export_text,
    )


@performance_app.command(name="update")
def performance_update(
    ledger: Path | None = typer.Option(
        None,
        "--ledger",
        help="Recommendation ledger path.",
    ),
) -> None:
    """
    Update recommendation outcomes from available later bars.
    """

    service = PerformanceIntelligenceService.from_path(ledger)
    summary = service.update()
    print()
    for line in render_update_summary(summary):
        print(line)


@performance_app.command(name="report")
def performance_report(
    ledger: Path | None = typer.Option(
        None,
        "--ledger",
        help="Recommendation ledger path.",
    ),
) -> None:
    """
    Print recommendation performance statistics from the ledger.
    """

    service = PerformanceIntelligenceService.from_path(ledger)
    print()
    for line in service.report_lines():
        print(line)


@app.command()
def backtest(
    strategy: str = typer.Option(..., help="Strategy name"),
    start: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option(..., help="End date (YYYY-MM-DD)"),
    cash: str = typer.Option("1000000", help="Starting cash"),
    export_json: Path | None = typer.Option(
        None,
        "--export-json",
        help="Write unified backtest report JSON to this path.",
    ),
    export_text: Path | None = typer.Option(
        None,
        "--export-text",
        help="Write unified backtest report text to this path.",
    ),
) -> None:
    """
    Run a deterministic backtest.
    """

    start_date = _parse_date(start)
    end_date = _parse_date(end)

    if end_date < start_date:
        raise typer.BadParameter("End date must be on or after start date.")

    starting_cash = _parse_decimal(cash)
    if starting_cash <= Decimal("0"):
        raise typer.BadParameter("Starting cash must be greater than zero.")

    _validate_command_export_paths(export_json=export_json, export_text=export_text)

    service = BacktestApplicationService()
    try:
        run = service.run(
            strategy=strategy,
            start=start_date,
            end=end_date,
            starting_cash=starting_cash,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    _print_backtest_summary(run.summary)
    _export_backtest_summary(
        summary=run.summary,
        export_json=export_json,
        export_text=export_text,
    )


def _run_daily_runtime(*, date: str, demo: bool) -> RuntimeResult:
    runtime = ProjectAlphaRuntime()
    return runtime.run_daily(date_str=date, demo=demo)


def _run_intelligence_runtime(*, date: str, demo: bool) -> RuntimeResult:
    runtime = ProjectAlphaRuntime()
    return runtime.run_intelligence(date_str=date, demo=demo)


def _print_daily_runtime_result(
    runtime_result: RuntimeResult,
    *,
    verbose: bool = True,
) -> None:
    run = runtime_result.intelligence_run
    allocation = run.allocation_plan
    market_analysis = runtime_result.market_analysis

    print("\nProject Alpha Daily Run")
    print(f"Status       : {runtime_result.status.value}")
    print(f"Mode         : {runtime_result.mode.value}")
    print(f"Requested On : {runtime_result.requested_on.isoformat()}")
    print(f"Observed On  : {runtime_result.observed_on.isoformat()}")
    print(f"Duration     : {runtime_result.metadata.duration_seconds}s")

    if market_analysis is not None:
        print(f"Rows Analyzed: {len(market_analysis.analysis)}")

    print("\nMarket")
    print(f"Symbol       : {run.market_report.symbol}")
    print(f"Bias         : {run.market_report.bias.value}")
    print(f"Score        : {run.market_report.composite_score}")
    top_sector = run.market_report.sector_rotation.top_sector.sector
    print(f"Top Sector   : {top_sector}")
    metadata_notice = _sector_metadata_notice(top_sector)
    if metadata_notice is not None:
        print(metadata_notice)

    print("\nCapital Deployment Dashboard:")
    for line in _capital_deployment_dashboard_lines(
        recommendations=run.recommendations,
        allocation_plan=allocation,
    ):
        print(line)

    if not verbose:
        print("\nTop Recommendations")
        for index, recommendation in enumerate(run.recommendations[:5], start=1):
            strategy = recommendation.actionable_trade_strategy or next(
                iter(recommendation.trade_strategies), None
            )
            strategy_name = strategy.name if strategy is not None else "none"
            risk_stop = strategy.stop_rule if strategy is not None else "not applicable"
            print(f"{index}. {recommendation.symbol} — {recommendation.final_signal}")
            print(f"   Action Now: {_execution_status(recommendation)}")
            print(f"   Recommended Strategy: {strategy_name}")
            print(f"   Risk Stop: {risk_stop}")
            print(f"   Data Quality: {_data_quality_text(recommendation)}")
        print("\nUse --verbose for full strategy options and evidence.")
        return

    print("\nRecommendations")
    for index, recommendation in enumerate(run.recommendations[:10], start=1):
        for line in _recommendation_detail_lines(index, recommendation):
            print(line)

    print("\nPortfolio Allocation")
    print(f"- Approved Capital: ₹{allocation.total_allocated_amount}")
    print(f"- Remaining Cash: ₹{allocation.remaining_cash}")
    deployment_count = len(
        tuple(report for report in allocation.reports if report.target_weight > 0)
    )
    print(f"- Deployment Count: {deployment_count}")

    print("\nPortfolio Summary")
    for line in _portfolio_summary_lines(run):
        print(line)

    if allocation.reports:
        print("\nPositions")
        recommendation_by_symbol = {
            recommendation.symbol: recommendation
            for recommendation in run.recommendations
        }
        for index, report in enumerate(allocation.reports[:10], start=1):
            allocation_recommendation = recommendation_by_symbol.get(report.symbol)
            capital_action = _allocation_capital_action(report.reasons)
            investment_verdict = (
                _verdict_label(allocation_recommendation)
                if allocation_recommendation is not None
                else "UNKNOWN"
            )
            execution_status = (
                _execution_status(allocation_recommendation)
                if allocation_recommendation is not None
                else "DO NOTHING"
            )
            print(f"{index}. {report.symbol}")
            print(f"   Investment Verdict: {investment_verdict}")
            print(f"   Execution Status: {execution_status}")
            print(f"   Allocation Status: {_allocation_status(report, capital_action)}")
            print(f"   Approved Capital: ₹{report.target_amount}")
            print(f"   Target Weight: {(report.target_weight * Decimal('100'))}%")
            print(f"   Reason: {_allocation_reason(capital_action, execution_status)}")

    if market_analysis is not None:
        signals = market_analysis.report["signals"]
        buy_count = int((signals["signal"] == "BUY").sum())
        sell_count = int((signals["signal"] == "SELL").sum())
        hold_count = int((signals["signal"] == "HOLD").sum())

        print("\nTrading Signals")
        print(f"BUY  : {buy_count}")
        print(f"SELL : {sell_count}")
        print(f"HOLD : {hold_count}")


def _print_backtest_summary(summary: BacktestSummary) -> None:
    renderer = BacktestReportRenderer()

    print()
    for line in renderer.render(summary.report):
        print(line)


def _allocation_capital_action(reasons: tuple[str, ...]) -> str:
    prefix = "capital action: "
    for reason in reasons:
        if reason.startswith(prefix):
            return reason.removeprefix(prefix)
    return "unknown"


def _approved_deployment_summary(reasons: tuple[str, ...]) -> str:
    prefix = "approved capital deployments: "
    for reason in reasons:
        if reason.startswith(prefix):
            return reason
    return "approved capital deployments: 0"


def _portfolio_summary_lines(run: IntelligenceRun) -> tuple[str, ...]:
    allocation = run.allocation_plan
    approved_reports = tuple(
        report for report in allocation.reports if report.target_weight > Decimal("0")
    )

    highest_conviction = min(
        run.recommendations,
        key=lambda recommendation: (
            -recommendation.score,
            recommendation.symbol,
        ),
        default=None,
    )
    largest_position = min(
        approved_reports,
        key=lambda report: (
            -report.target_weight,
            report.symbol,
        ),
        default=None,
    )

    highest_conviction_symbol = (
        highest_conviction.symbol
        if highest_conviction is not None and approved_reports
        else "NONE"
    )
    largest_position_text = "NONE"
    if largest_position is not None:
        largest_position_text = (
            f"{largest_position.symbol} "
            f"{_weight_percent(largest_position.target_weight)}"
        )

    return (
        f"Approved Deployments : {len(approved_reports)}",
        f"Approved Capital     : {allocation.total_allocated_amount}",
        f"Cash Remaining       : {allocation.remaining_cash}",
        f"Highest Conviction   : {highest_conviction_symbol}",
        f"Largest Position     : {largest_position_text}",
    )


def _data_quality_text(recommendation: object) -> str:
    unavailable = getattr(recommendation, "unavailable_reasons", ())
    return "Partial" if unavailable else "Complete"


def _weight_percent(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(Decimal('0.01'))}%"


def _export_backtest_summary(
    *,
    summary: BacktestSummary,
    export_json: Path | None,
    export_text: Path | None,
) -> None:
    service = BacktestExportService()
    try:
        result = service.export(
            summary,
            json_path=export_json,
            text_path=export_text,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    if result.json_path is not None:
        print(f"\nJSON report written: {result.json_path}")

    if result.text_path is not None:
        print(f"\nText report written: {result.text_path}")


def _export_intelligence_run(
    *,
    run: IntelligenceRun,
    export_json: Path | None,
    export_text: Path | None,
) -> None:
    service = IntelligenceExportService()
    try:
        result = service.export(
            run,
            json_path=export_json,
            text_path=export_text,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    if result.json_path is not None:
        print(f"\nJSON report written: {result.json_path}")

    if result.text_path is not None:
        print(f"\nText report written: {result.text_path}")


def _record_recommendation_performance(runtime_result: RuntimeResult) -> None:
    repository = RecommendationLedgerRepository(resolve_ledger_path())
    recorder = RecommendationPerformanceRecorder(repository)
    recorder.record_runtime(runtime_result)


def _validate_command_export_paths(
    *,
    export_json: Path | None,
    export_text: Path | None,
) -> None:
    try:
        _validate_export_paths(export_json=export_json, export_text=export_text)
    except typer.BadParameter as error:
        typer.echo(str(error))
        raise typer.Exit(code=2) from error


def _validate_export_paths(
    *,
    export_json: Path | None,
    export_text: Path | None,
) -> None:
    if export_json is not None and export_json.suffix.lower() != ".json":
        raise typer.BadParameter("Expected --export-json path to end with .json.")

    if export_text is not None and export_text.suffix.lower() != ".txt":
        raise typer.BadParameter("Expected --export-text path to end with .txt.")


def _parse_date(date_str: str) -> dt_date:
    if date_str == "today":
        return dt_date.today()

    return dt_date.fromisoformat(date_str)


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise typer.BadParameter("Expected a decimal value.") from error


def _exit_with_error(title: str, exc: ProjectAlphaError) -> None:
    typer.echo(f"{title}: {exc}", err=True)
    raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
