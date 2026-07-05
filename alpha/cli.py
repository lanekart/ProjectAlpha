from datetime import date as dt_date

import typer

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
) -> None:
    """
    Prepare a backtest configuration.

    Execution engine will be added in a later commit.
    """

    start_date = _parse_date(start)
    end_date = _parse_date(end)

    if end_date < start_date:
        raise typer.BadParameter("End date must be on or after start date.")

    print("\nProject Alpha Backtest\n")
    print(f"Strategy : {strategy}")
    print(f"Start    : {start_date.isoformat()}")
    print(f"End      : {end_date.isoformat()}")


def _parse_date(date_str: str) -> dt_date:
    if date_str == "today":
        return dt_date.today()

    return dt_date.fromisoformat(date_str)


if __name__ == "__main__":
    app()
