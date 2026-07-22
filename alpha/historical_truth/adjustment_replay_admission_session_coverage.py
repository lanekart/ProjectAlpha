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
    """Compare every governed expected session with canonical observations."""

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
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    governed_observation_disagreements = sorted(observed ^ governed_observed)
    certification_state = str(payload.get("certification_state") or "")
    certified = certification_state == "certified"

    blockers: list[str] = []
    if not checksum_valid:
        blockers.append("GOVERNED_SESSION_CALENDAR_CHECKSUM_INVALID")
    if not window_covered:
        blockers.append("GOVERNED_SESSION_CALENDAR_WINDOW_INCOMPLETE")
    if not certified:
        blockers.append("GOVERNED_SESSION_CALENDAR_NOT_CERTIFIED")
    if unresolved:
        blockers.append("UNRESOLVED_GOVERNED_WEEKDAYS")
    if missing:
        blockers.append("MISSING_EXPECTED_TRADING_SESSIONS")
    if governed_observation_disagreements:
        blockers.append("CALENDAR_DATABASE_OBSERVATION_MISMATCH")

    complete = not blockers
    expected_count = len(expected)
    observed_expected_count = len(expected & observed)
    return {
        "contract_version": HTR010B1C_CONTRACT_VERSION,
        "state": "GOVERNED_SESSION_COVERAGE_COMPLETE"
        if complete
        else "GOVERNED_SESSION_COVERAGE_INCOMPLETE",
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
        "missing_expected_session_count": len(missing),
        "missing_expected_sessions": [item.isoformat() for item in missing],
        "unexpected_observed_session_count": len(unexpected),
        "unexpected_observed_sessions": [item.isoformat() for item in unexpected],
        "unresolved_weekday_count": len(unresolved),
        "unresolved_weekdays": [item.isoformat() for item in sorted(unresolved)],
        "calendar_database_disagreement_count": len(governed_observation_disagreements),
        "calendar_database_disagreements": [
            item.isoformat() for item in governed_observation_disagreements
        ],
        "coverage_ratio": (
            observed_expected_count / expected_count if expected_count else 0.0
        ),
        "blockers": sorted(set(blockers)),
        "production_influence": False,
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
