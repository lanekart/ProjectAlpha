from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

from alpha.historical_truth.adjustment_replay_admission_residual_attribution import (
    attribute_residual_factor_cases,
)
from alpha.historical_truth.adjustment_replay_admission_session_coverage import (
    governed_session_coverage,
)


def _database(path: Path) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE daily_candle("
            "trading_date DATE, exchange VARCHAR, symbol VARCHAR, series VARCHAR, "
            "isin VARCHAR, open_price DOUBLE, high_price DOUBLE, low_price DOUBLE, "
            "close_price DOUBLE, volume BIGINT)"
        )


def _insert(
    path: Path,
    *,
    isin: str,
    dates_and_opens: list[tuple[date, float]],
    volume: int = 10000,
) -> None:
    rows = [
        (
            trading_date,
            "nse",
            "TEST",
            "EQ",
            isin,
            open_price,
            open_price + 1.0,
            open_price - 1.0,
            open_price,
            volume,
        )
        for trading_date, open_price in dates_and_opens
    ]
    with duckdb.connect(str(path)) as connection:
        connection.executemany(
            "INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def _calendar(path: Path, observed: set[date]) -> None:
    records = [
        {
            "trading_date": current.isoformat(),
            "classification": "regular_session",
            "observed_candles": current in observed,
            "description": None,
            "source_ids": ["official"],
            "issue_codes": [],
        }
        for current in (date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3))
    ]
    payload = {
        "contract_version": "1.0",
        "start_date": "2026-01-01",
        "end_date": "2026-01-03",
        "exchange": "nse",
        "certification_state": "certified",
        "sources": [],
        "annual_summaries": [],
        "records": records,
        "official_holiday_count": 0,
        "official_special_session_count": 0,
        "expected_session_count": 3,
        "observed_session_count": len(observed),
        "unresolved_weekday_count": 0,
        "unconfirmed_special_session_count": 0,
        "missing_special_session_count": 0,
        "conflict_count": 0,
    }
    payload["report_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_internal_missing_session_fails_even_when_boundaries_match(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    report = tmp_path / "calendar.json"
    _database(database)
    observed = {date(2026, 1, 1), date(2026, 1, 3)}
    _insert(
        database,
        isin="INE000A01001",
        dates_and_opens=[(item, 100.0) for item in sorted(observed)],
    )
    _calendar(report, observed)

    result = governed_session_coverage(
        calendar_report=report,
        database_path=database,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
    )

    assert result["state"] == "GOVERNED_SESSION_COVERAGE_INCOMPLETE"
    assert result["missing_expected_session_count"] == 1
    assert result["missing_expected_sessions"] == ["2026-01-02"]
    assert "MISSING_EXPECTED_TRADING_SESSIONS" in result["blockers"]


def _defect_row(
    *,
    factor: float,
    effective: date,
    event_id: str,
) -> dict[str, object]:
    return {
        "case_id": f"case-{event_id}",
        "event_id": event_id,
        "identity_key": "nse:isin:INE000A01001",
        "symbol": "TEST",
        "series": "EQ",
        "isin": "INE000A01001",
        "action_type": "SPLIT",
        "effective_date": effective.isoformat(),
        "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
        "price_factor": factor,
        "raw_gap_atr": 0.0,
        "adjusted_gap_atr": 20.0,
        "inverse_adjusted_gap_atr": 20.0,
        "action_session": effective.isoformat(),
        "validation_outcome": "IMPLEMENTATION_DEFECT",
        "implementation_defect_code": "FACTOR_DOES_NOT_RESTORE_CONTINUITY",
        "admitted_to_replay": False,
        "requires_quarantine": True,
    }


def test_effective_date_offset_is_attributed_without_factor_mutation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    start = date(2026, 1, 1)
    dates_and_opens = [(start + timedelta(days=offset), 100.0) for offset in range(16)]
    dates_and_opens.append((date(2026, 1, 17), 50.0))
    _insert(database, isin="INE000A01001", dates_and_opens=dates_and_opens)

    enriched, summary = attribute_residual_factor_cases(
        database_path=database,
        results=(
            _defect_row(
                factor=0.5,
                effective=date(2026, 1, 16),
                event_id="event-offset",
            ),
        ),
    )

    assert enriched[0]["residual_attribution"] == "POSSIBLE_EFFECTIVE_DATE_OFFSET"
    detail = enriched[0]["residual_attribution_detail"]
    assert detail["candidate_date"] == "2026-01-17"
    assert detail["official_factor_retained"] is True
    assert summary["possible_effective_date_offset_count"] == 1


def test_same_day_cumulative_factor_is_diagnostic_only(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    start = date(2026, 1, 1)
    dates_and_opens = [(start + timedelta(days=offset), 100.0) for offset in range(15)]
    dates_and_opens.append((date(2026, 1, 16), 25.0))
    _insert(database, isin="INE000A01001", dates_and_opens=dates_and_opens)

    results = (
        _defect_row(
            factor=0.5,
            effective=date(2026, 1, 16),
            event_id="event-a",
        ),
        _defect_row(
            factor=0.5,
            effective=date(2026, 1, 16),
            event_id="event-b",
        ),
    )
    enriched, summary = attribute_residual_factor_cases(
        database_path=database,
        results=results,
    )

    assert all(
        row["residual_attribution"]
        == "POSSIBLE_MULTIPLE_ACTION_CUMULATIVE_FACTOR"
        for row in enriched
    )
    assert all(
        row["residual_attribution_detail"]["official_factors_retained"] is True
        for row in enriched
    )
    assert summary["possible_multiple_action_cumulative_factor_count"] == 2
