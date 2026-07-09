from __future__ import annotations

from datetime import date as dt_date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import typer

from alpha.application.backtest import BacktestApplicationService, BacktestSummary
from alpha.application.backtest_export import BacktestExportService
from alpha.application.historical_ingestion import HistoricalIngestionService
from alpha.application.intelligence import (
    IntelligenceRun,
    _recommendation_detail_lines,
    _recommendation_driver_line,
    _sector_metadata_notice,
)
from alpha.application.intelligence_export import IntelligenceExportService
from alpha.application.research_cli import research_app
from alpha.application.runtime import ProjectAlphaRuntime
from alpha.application.runtime_models import RuntimeResult
from alpha.backtest.backtest_report import BacktestReportRenderer
from alpha.exceptions import BhavcopyNotFoundError, ProjectAlphaError
from alpha.release import current_release
from alpha.version import __version__

app = typer.Typer()
app.add_typer(research_app, name="research")


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

    _print_daily_runtime_result(runtime_result)
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

    _export_intelligence_run(
        run=runtime_result.intelligence_run,
        export_json=export_json,
        export_text=export_text,
    )


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


def _print_daily_runtime_result(runtime_result: RuntimeResult) -> None:
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

    print("\nRecommendations")
    for index, recommendation in enumerate(run.recommendations[:10], start=1):
        print(
            f"{index}. {recommendation.symbol}: "
            f"{recommendation.decision.value} "
            f"action={recommendation.action.value} "
            f"score={recommendation.score} "
            f"raw_allocation_hint="
            f"{recommendation.allocation.adjusted_allocation_percent}%"
        )
        driver_line = _recommendation_driver_line(recommendation)
        if driver_line is not None:
            print(driver_line)
        for line in _recommendation_detail_lines(recommendation):
            print(line)

    print("\nPortfolio Allocation")
    print(f"Approved Deployment Weight : {allocation.total_allocated_weight}")
    print(f"Approved Deployment Amount : {allocation.total_allocated_amount}")
    print(f"Remaining Cash              : {allocation.remaining_cash}")
    print(_approved_deployment_summary(allocation.reasons))

    print("\nPortfolio Summary")
    for line in _portfolio_summary_lines(run):
        print(line)

    if allocation.reports:
        print("\nAllocation Reports")
        for report in allocation.reports[:10]:
            capital_action = _allocation_capital_action(report.reasons)
            print(
                f"- {report.symbol}: {report.decision.value} "
                f"capital_action={capital_action} "
                f"target_weight={report.target_weight} "
                f"target_amount={report.target_amount}"
            )

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
