from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.session_calendar import (
    CalendarCertificationState,
    OfficialSessionCalendarEngine,
)
from alpha.historical_truth.special_session_recovery import (
    SpecialSessionCandleRecoveryEngine,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint="--date",
        ) from exc


def _range_date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option_name,
        ) from exc


def _calendar_source_paths(calendar_report: Path) -> tuple[Path, ...]:
    try:
        payload = json.loads(calendar_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(
            f"invalid governed calendar report: {exc}",
            param_hint="--evidence-dir",
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise typer.BadParameter(
            "governed calendar report has no source registry",
            param_hint="--evidence-dir",
        )
    expected_hash = payload.get("report_sha256")
    without_hash = dict(payload)
    without_hash.pop("report_sha256", None)
    observed_hash = hashlib.sha256(
        json.dumps(
            without_hash,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if expected_hash != observed_hash:
        raise typer.BadParameter(
            "governed calendar report checksum verification failed",
            param_hint="--evidence-dir",
        )
    paths: list[Path] = []
    for source in payload["sources"]:
        if not isinstance(source, dict) or not isinstance(
            source.get("source_path"), str
        ):
            raise typer.BadParameter(
                "governed calendar source registry is malformed",
                param_hint="--evidence-dir",
            )
        path = Path(source["source_path"])
        if not path.exists():
            raise typer.BadParameter(
                f"governed calendar source is missing: {path}",
                param_hint="--evidence-dir",
            )
        source_sha = source.get("source_sha256")
        if source_sha != hashlib.sha256(path.read_bytes()).hexdigest():
            raise typer.BadParameter(
                f"governed calendar source checksum mismatch: {path}",
                param_hint="--evidence-dir",
            )
        paths.append(path)
    return tuple(paths)


def _progress(current: int, total: int, trading_date: date) -> None:
    width = 36
    bounded_total = max(total, 1)
    filled = int(width * current / bounded_total)
    line = (
        "Special-session recovery "
        f"[{'#' * filled}{'-' * (width - filled)}] "
        f"{int(100 * current / bounded_total):3d}% "
        f"({current}/{bounded_total}) | {trading_date}"
    )
    if sys.stdout.isatty():
        print(
            f"\r\x1b[2K{line}",
            end="" if current < total else "\n",
            flush=True,
        )
    else:
        print(line, flush=True)


def special_session_candle_recover(
    calendar_report: Path = typer.Option(
        ...,
        "--calendar-report",
        exists=True,
        dir_okay=False,
    ),
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
    ),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    output: Path = typer.Option(
        Path("artifacts/htr007b_special_session_recovery"),
        "--output",
    ),
    selected_date: list[str] = typer.Option(
        [],
        "--date",
        help="Official special-session date; repeat to filter diagnostics.",
    ),
    timeout_seconds: float = typer.Option(30.0, "--timeout-seconds", min=1.0),
    refresh: bool = typer.Option(False, "--refresh"),
) -> None:
    """Recover missing official NSE CM special-session candles."""

    canonical = CanonicalPointInTimeWarehouse(database)
    engine = SpecialSessionCandleRecoveryEngine(
        root,
        canonical,
        timeout_seconds=timeout_seconds,
    )
    try:
        report = engine.recover(
            calendar_report,
            selected_dates=tuple(_date(value) for value in selected_date),
            refresh=refresh,
            progress=_progress,
        )
    except ValueError as exc:
        raise typer.BadParameter(
            str(exc),
            param_hint="--calendar-report",
        ) from exc
    paths = engine.export(report, output)
    print(f"Sessions Evaluated: {len(report.records)}")
    print(f"Recovered: {report.complete_count}")
    print(f"Reused: {report.reused_count}")
    print(f"Failed: {report.failed_count}")
    print(f"Report SHA-256: {report.report_sha256}")
    print("PRODUCTION_INFLUENCE=false")
    for record in report.records:
        print(
            f"{record.trading_date} | {record.recovery_status.value} | "
            f"rows={record.row_count} | "
            f"{record.failure_code.value if record.failure_code else 'OK'}"
        )
    for path in paths:
        print(path)
    if not report.complete:
        raise typer.Exit(code=1)


def session_calendar_build(
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    evidence_dir: Path = typer.Option(..., "--evidence-dir"),
    output: Path = typer.Option(
        Path("artifacts/htr007_historical_session_evidence"),
        "--output",
    ),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
) -> None:
    """Reconcile canonical observations with governed calendar evidence."""

    start_date = _range_date(start, "--start")
    end_date = _range_date(end, "--end")
    if start_date > end_date:
        raise typer.BadParameter(
            "must be on or before --end",
            param_hint="--start",
        )
    calendar_report = evidence_dir / "htr007_session_calendar.json"
    if not calendar_report.exists():
        raise typer.BadParameter(
            f"governed calendar report not found: {calendar_report}",
            param_hint="--evidence-dir",
        )
    source_paths = _calendar_source_paths(calendar_report)
    sources = tuple(
        OfficialSessionCalendarEngine.load_source(path) for path in source_paths
    )
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    engine = OfficialSessionCalendarEngine(canonical)
    report = engine.reconcile(start_date, end_date, sources)
    paths = engine.export(report, output)
    print(f"Certification State: {report.certification_state.value}")
    print(f"Official Sources: {len(report.sources)}")
    print(f"Official Holidays: {report.official_holiday_count}")
    print(f"Official Special Sessions: {report.official_special_session_count}")
    print(f"Expected Sessions: {report.expected_session_count}")
    print(f"Observed Sessions: {report.observed_session_count}")
    print(f"Unresolved Weekdays: {report.unresolved_weekday_count}")
    print(f"Unconfirmed Special Sessions: {report.unconfirmed_special_session_count}")
    print(f"Missing Special Sessions: {report.missing_special_session_count}")
    print(f"Calendar Report SHA-256: {report.report_sha256}")
    for path in paths:
        print(path)
    if report.certification_state is not CalendarCertificationState.CERTIFIED:
        raise typer.Exit(code=1)
