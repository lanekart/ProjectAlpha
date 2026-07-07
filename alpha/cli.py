from __future__ import annotations

from datetime import date as dt_date
from decimal import Decimal, InvalidOperation

import typer

from alpha.application.backtest import CliBacktestService
from alpha.application.historical_ingestion import HistoricalIngestionService
from alpha.version import __version__

app = typer.Typer()


@app.command()
def version() -> None:
    print(__version__)


@app.command()
def download(date: str = "today") -> None:
    """
    Download NSE bhavcopy.
    """

    service = HistoricalIngestionService()
    count = service.download_only(date)

    print(f"Downloaded records: {count}")


@app.command()
def report(date: str = "today") -> None:
    """
    Generate daily report.
    """

    service = HistoricalIngestionService()
    report_data = service.generate_report(date)

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
def backtest(
    strategy: str = typer.Option(..., help="Strategy name"),
    start: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option(..., help="End date (YYYY-MM-DD)"),
    cash: str = typer.Option("1000000", help="Starting cash"),
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

    service = CliBacktestService()
    try:
        summary = service.run(
            strategy=strategy,
            start=start_date,
            end=end_date,
            starting_cash=starting_cash,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    result = summary.result

    print("\nProject Alpha Backtest\n")
    print(f"Strategy       : {summary.strategy}")
    print(f"Start          : {summary.start.isoformat()}")
    print(f"End            : {summary.end.isoformat()}")
    print(f"Processed Days : {summary.processed_days}")
    print(f"Starting Cash  : {summary.starting_cash}")
    print(f"Ending Cash    : {result.ending_cash}")
    print(f"Equity         : {result.equity}")
    print(f"Orders         : {summary.order_count}")
    print(f"Trades         : {result.trade_count}")

    if result.positions:
        print("\nPositions:")
        for symbol, quantity in sorted(result.positions.items()):
            print(f"{symbol}: {quantity}")
    else:
        print("\nPositions: none")


def _parse_date(date_str: str) -> dt_date:
    if date_str == "today":
        return dt_date.today()

    return dt_date.fromisoformat(date_str)


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise typer.BadParameter("Expected a decimal value.") from error


if __name__ == "__main__":
    app()
