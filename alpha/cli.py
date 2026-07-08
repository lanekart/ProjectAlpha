from __future__ import annotations

from datetime import date as dt_date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import typer

from alpha.application.backtest import BacktestApplicationService, BacktestSummary
from alpha.application.backtest_export import BacktestExportService
from alpha.application.historical_ingestion import HistoricalIngestionService
from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.research_cli import research_app
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

    print("🔥 Top Gainers:")
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


@app.command()
def intelligence(date: str = "today") -> None:
    """
    Run the deterministic intelligence orchestration report.
    """

    observed_on = _parse_date(date)
    service = IntelligenceApplicationService()
    run = service.run(observed_on=observed_on)

    print()
    for line in run.summary_lines:
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

    _validate_export_paths(export_json=export_json, export_text=export_text)

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


def _print_backtest_summary(summary: BacktestSummary) -> None:
    renderer = BacktestReportRenderer()

    print()
    for line in renderer.render(summary.report):
        print(line)


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
