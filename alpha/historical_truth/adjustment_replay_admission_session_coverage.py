"""Governed session-completeness audit for HTR-010B1C."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

HTR010B1C_CONTRACT_VERSION = "HTR-010B1C-v1.0.0"
_EXPECTED_SESSION_CLASSES = {"regular_session", "special_session"}


def governed_session_coverage(
    *,
    calendar_report: Path,
    database_path: Path,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Compare governed expected sessions with canonical observations."""

    if not calendar_report.exists():
        return _unavailable(
            calendar_report,
            "GOVERNED_SESSION_CALENDAR_REPORT_MISSING",
        )
    try:
        payload = json.loads(calendar_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _unavailable(
            calendar_report,
            "GOVERNED_SESSION_CALENDAR_REPORT_INVALID",
        )
    if not isinstance(payload, dict):
        return _unavailable(
            calendar_report,
            "GOVERNED_SESSION_CALENDAR_REPORT_INVALID",
        )

    checksum_valid = _checksum_valid(payload)
    records = payload.get("records")
    if not isinstance(records, list):
        return _unavailable(
            calendar_report,
            "GOVERNED_SESSION_CALENDAR_RECORDS_MISSING",
            checksum_valid=checksum_valid,
        )

    report_start = _as_date(payload.get("start_date"))
    report_end = _as_date(payload.get("end_date"))
    window_covered = bool(
        report_start
        and report_end
        and report_start <= start_date
        and report_end >= end_date
    )
    expected: set[date] = set()
    unresolved: set[date] = set()
    governed_observed: set[date] = set()
    for row in records:
        if not isinstance(row, dict):
            continue
        trading_date = _as_date(row.get("trading_date"))
        if trading_date is None or not start_date <= trading_date <= end_date:
            continue
        classification = str(row.get("classification") or "")
        if classification in _EXPECTED_SESSION_CLASSES:
            expected.add(trading_date)
        elif classification == "unresolved_weekday":
            unresolved.add(trading_date)
        if bool(row.get("observed_candles")):
            governed_observed.add(trading_date)

    observed = _observed_sessions(database_path, start_date, end_date)
    observed_within_governed = _within_report_window(
        observed,
        report_start,
        report_end,
    )
    observations_beyond_window = sorted(observed - observed_within_governed)
    missing = sorted(expected - observed_within_governed)
    unexpected_within_governed = sorted(observed_within_governed - expected)
    observation_disagreements = sorted(observed_within_governed ^ governed_observed)
    certification_state = str(payload.get("certification_state") or "")
    certified = certification_state == "certified"

    blockers: list[str] = []
    if not checksum_valid:
        blockers.append("GOVERNED_SESSION_CALENDAR_CHECKSUM_INVALID")
    if not window_covered:
        blockers.append("GOVERNED_SESSION_CALENDAR_WINDOW_INCOMPLETE")
    if observations_beyond_window:
        blockers.append("OBSERVATIONS_BEYOND_GOVERNED_CALENDAR_WINDOW")
    if not certified:
        blockers.append("GOVERNED_SESSION_CALENDAR_NOT_CERTIFIED")
    if unresolved:
        blockers.append("UNRESOLVED_GOVERNED_WEEKDAYS")
    if missing:
        blockers.append("MISSING_EXPECTED_TRADING_SESSIONS")
    if unexpected_within_governed:
        blockers.append("UNEXPECTED_OBSERVED_SESSIONS_WITHIN_GOVERNED_WINDOW")
    if observation_disagreements:
        blockers.append("CALENDAR_DATABASE_OBSERVATION_MISMATCH")

    complete = not blockers
    expected_count = len(expected)
    observed_expected_count = len(expected & observed_within_governed)
    return {
        "contract_version": HTR010B1C_CONTRACT_VERSION,
        "state": (
            "GOVERNED_SESSION_COVERAGE_COMPLETE"
            if complete
            else "GOVERNED_SESSION_COVERAGE_INCOMPLETE"
        ),
        "calendar_report": str(calendar_report),
        "calendar_report_sha256": payload.get("report_sha256"),
        "calendar_checksum_valid": checksum_valid,
        "calendar_certification_state": certification_state,
        "calendar_window_start": report_start.isoformat() if report_start else None,
        "calendar_window_end": report_end.isoformat() if report_end else None,
        "requested_window_covered": window_covered,
        "expected_session_count": expected_count,
        "observed_expected_session_count": observed_expected_count,
        "observed_database_session_count": len(observed),
        "observed_within_governed_window_count": len(observed_within_governed),
        "missing_expected_session_count": len(missing),
        "missing_expected_sessions": [item.isoformat() for item in missing],
        "unexpected_observed_session_count": len(unexpected_within_governed),
        "unexpected_observed_sessions": [
            item.isoformat() for item in unexpected_within_governed
        ],
        "observations_beyond_governed_calendar_window_count": len(
            observations_beyond_window
        ),
        "observations_beyond_governed_calendar_window": [
            item.isoformat() for item in observations_beyond_window
        ],
        "unresolved_weekday_count": len(unresolved),
        "unresolved_weekdays": [item.isoformat() for item in sorted(unresolved)],
        "calendar_database_disagreement_count": len(observation_disagreements),
        "calendar_database_disagreements": [
            item.isoformat() for item in observation_disagreements
        ],
        "coverage_ratio": (
            observed_expected_count / expected_count if expected_count else 0.0
        ),
        "blockers": sorted(set(blockers)),
        "production_influence": False,
    }


def _within_report_window(
    observed: set[date],
    report_start: date | None,
    report_end: date | None,
) -> set[date]:
    if report_start is None or report_end is None:
        return set()
    return {
        trading_date
        for trading_date in observed
        if report_start <= trading_date <= report_end
    }


def _observed_sessions(
    database_path: Path,
    start_date: date,
    end_date: date,
) -> set[date]:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        rows = connection.execute(
            "SELECT DISTINCT trading_date FROM daily_candle "
            "WHERE lower(exchange)='nse' AND trading_date BETWEEN ? AND ?",
            [start_date, end_date],
        ).fetchall()
    return {row[0] for row in rows}


def _checksum_valid(payload: dict[str, Any]) -> bool:
    expected = payload.get("report_sha256")
    if not isinstance(expected, str) or not expected:
        return False
    without_hash = dict(payload)
    without_hash.pop("report_sha256", None)
    observed = hashlib.sha256(
        json.dumps(
            without_hash,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return observed == expected


def _unavailable(
    calendar_report: Path,
    blocker: str,
    *,
    checksum_valid: bool = False,
) -> dict[str, Any]:
    return {
        "contract_version": HTR010B1C_CONTRACT_VERSION,
        "state": "GOVERNED_SESSION_COVERAGE_UNAVAILABLE",
        "calendar_report": str(calendar_report),
        "calendar_checksum_valid": checksum_valid,
        "expected_session_count": 0,
        "observed_expected_session_count": 0,
        "missing_expected_session_count": 0,
        "observations_beyond_governed_calendar_window_count": 0,
        "unresolved_weekday_count": 0,
        "coverage_ratio": 0.0,
        "blockers": [blocker],
        "production_influence": False,
    }


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


__all__ = ["HTR010B1C_CONTRACT_VERSION", "governed_session_coverage"]
