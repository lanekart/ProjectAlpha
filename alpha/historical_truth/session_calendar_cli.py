from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.session_calendar import OfficialSessionCalendarEngine

session_calendar_app = typer.Typer(
    help=(
        "Acquire official NSE CM calendar evidence and reconcile it with "
        "canonical historical sessions."
    ),
    no_args_is_help=True,
)


def _parse_date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option_name,
        ) from exc


def _progress(label: str, current: int, total: int) -> None:
    width = 32
    total = max(total, 1)
    current = min(current, total)
    filled = int(width * current / total)
    percent = int(100 * current / total)
    print(
        f"\r{label} [{'#' * filled}{'-' * (width - filled)}] "
        f"{percent:3d}% ({current}/{total})",
        end="" if current < total else "\n",
        flush=True,
    )


@session_calendar_app.callback()
def session_calendar() -> None:
    """Coordinate governed official-session calendar commands."""


@session_calendar_app.command("download-current")
def download_current(
    source_dir: Path = typer.Option(
        Path("alpha_data/raw/nse/calendar"),
        "--source-dir",
    ),
    timeout_seconds: float = typer.Option(30.0, "--timeout-seconds", min=1.0),
) -> None:
    """Download the current official NSE trading-holiday API payload."""

    _progress("Official calendar download", 0, 1)
    path = OfficialSessionCalendarEngine.fetch_current_official_source(
        source_dir,
        timeout_seconds=timeout_seconds,
    )
    _progress("Official calendar download", 1, 1)
    print(path)


@session_calendar_app.command("reconcile")
def reconcile(
    end: str = typer.Option(..., "--end"),
    start: str = typer.Option("2016-01-01", "--start"),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    source_dir: Path = typer.Option(
        Path("alpha_data/raw/nse/calendar"),
        "--source-dir",
    ),
    source_file: list[Path] = typer.Option(
        [],
        "--source-file",
        help="Official source JSON; repeat to supply multiple source documents.",
    ),
    fetch_current: bool = typer.Option(
        False,
        "--fetch-current/--no-fetch-current",
    ),
    output_dir: Path = typer.Option(
        Path("artifacts/htr007_session_calendar"),
        "--output-dir",
    ),
) -> None:
    """Reconcile official holidays and special sessions against candles."""

    start_date = _parse_date(start, "--start")
    end_date = _parse_date(end, "--end")
    if start_date > end_date:
        raise typer.BadParameter(
            "must be on or before --end",
            param_hint="--start",
        )

    selected = list(source_file)
    if fetch_current:
        selected.append(
            OfficialSessionCalendarEngine.fetch_current_official_source(source_dir)
        )
    if not source_file:
        selected.extend(sorted(source_dir.glob("*.json")))
    unique_paths = tuple(dict.fromkeys(path.resolve() for path in selected))
    if not unique_paths:
        raise typer.BadParameter(
            "no official source JSON files were found",
            param_hint="--source-file",
        )

    sources = []
    for index, path in enumerate(unique_paths, start=1):
        sources.append(OfficialSessionCalendarEngine.load_source(path))
        _progress("Official source loading", index, len(unique_paths))

    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    engine = OfficialSessionCalendarEngine(canonical)
    _progress("Session reconciliation", 0, 1)
    report = engine.reconcile(start_date, end_date, sources)
    paths = engine.export(report, output_dir)
    _progress("Session reconciliation", 1, 1)

    print(f"Certification State: {report.certification_state.value}")
    print(f"Official Sources: {len(report.sources)}")
    print(f"Official Holidays: {report.official_holiday_count}")
    print(f"Official Special Sessions: {report.official_special_session_count}")
    print(f"Expected Sessions: {report.expected_session_count}")
    print(f"Observed Sessions: {report.observed_session_count}")
    print(f"Unresolved Weekdays: {report.unresolved_weekday_count}")
    print(f"Unconfirmed Special Sessions: {report.unconfirmed_special_session_count}")
    print(f"Missing Special Sessions: {report.missing_special_session_count}")
    print(f"Conflicts: {report.conflict_count}")
    print(f"Report SHA-256: {report.report_sha256}")
    for path in paths:
        print(path)

    if report.conflict_count or report.missing_special_session_count:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    session_calendar_app()
