import typer
from datetime import date as dt_date

from alpha.version import __version__
from alpha.data.downloader.bhavcopy import BhavcopyDownloader
from alpha.market.resolver import TradingDateResolver

app = typer.Typer()


@app.command()
def version():
    """Show the application version."""
    print(__version__)


@app.command()
def download(date: str = "today"):
    """
    Download an NSE bhavcopy.

    Examples:
        python -m alpha download
        python -m alpha download --date 2024-06-10
    """

    if date == "today":
        target_date = dt_date.today()
    else:
        target_date = dt_date.fromisoformat(date)

    resolver = TradingDateResolver()
    resolved_date = resolver.resolve(target_date)

    downloader = BhavcopyDownloader()
    file_path = downloader.download(resolved_date)

    print(f"Downloaded: {file_path}")


if __name__ == "__main__":
    app()