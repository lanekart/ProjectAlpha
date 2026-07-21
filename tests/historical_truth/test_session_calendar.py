from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.session_calendar import (
    CalendarCertificationState,
    OfficialSessionCalendarEngine,
    SessionClassification,
)


def _seed_candles(
    warehouse: CanonicalPointInTimeWarehouse,
    trading_dates: tuple[date, ...],
) -> None:
    warehouse.initialise()
    with warehouse._connect() as connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO daily_candle VALUES (
                ?, 'nse', 'ALPHA', 'EQ', 'INE000000001',
                100, 110, 90, 105, 1000, 'fixture-sha'
            )
            """,
            [(trading_date,) for trading_date in trading_dates],
        )


def _write_source(
    path: Path,
    *,
    holidays: list[dict[str, str]],
    special_sessions: list[dict[str, str]],
) -> Path:
    payload = {
        "covered_years": [2024],
        "source_url": "https://www.nseindia.com/official-fixture",
        "holidays": holidays,
        "special_sessions": special_sessions,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_session_calendar_certifies_complete_official_window(tmp_path: Path) -> None:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    _seed_candles(
        warehouse,
        (
            date(2024, 1, 2),
            date(2024, 1, 3),
            date(2024, 1, 4),
            date(2024, 1, 5),
            date(2024, 1, 6),
        ),
    )
    source_path = _write_source(
        tmp_path / "calendar.json",
        holidays=[{"tradingDate": "01-Jan-2024", "description": "New Year"}],
        special_sessions=[
            {
                "tradingDate": "06-Jan-2024",
                "description": "Official Saturday special session",
            }
        ],
    )
    source = OfficialSessionCalendarEngine.load_source(source_path)
    engine = OfficialSessionCalendarEngine(warehouse)

    report = engine.reconcile(
        date(2024, 1, 1),
        date(2024, 1, 6),
        (source,),
    )

    assert report.certification_state is CalendarCertificationState.CERTIFIED
    assert report.expected_session_count == 5
    assert report.observed_session_count == 5
    assert report.unresolved_weekday_count == 0
    assert report.conflict_count == 0
    assert report.unconfirmed_special_session_count == 0
    assert report.records[0].classification is SessionClassification.HOLIDAY
    assert report.records[-1].classification is SessionClassification.SPECIAL_SESSION


def test_observed_weekend_without_official_special_evidence_is_unconfirmed(
    tmp_path: Path,
) -> None:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    _seed_candles(warehouse, (date(2024, 1, 6),))
    source_path = _write_source(
        tmp_path / "calendar.json",
        holidays=[],
        special_sessions=[],
    )
    source = OfficialSessionCalendarEngine.load_source(source_path)
    engine = OfficialSessionCalendarEngine(warehouse)

    report = engine.reconcile(
        date(2024, 1, 6),
        date(2024, 1, 6),
        (source,),
    )

    assert (
        report.certification_state
        is CalendarCertificationState.INCOMPLETE_OFFICIAL_EVIDENCE
    )
    assert report.unconfirmed_special_session_count == 1
    assert report.records[0].issue_codes == ("UNCONFIRMED_SPECIAL_SESSION",)


def test_holiday_with_observed_candle_is_a_conflict(tmp_path: Path) -> None:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    _seed_candles(warehouse, (date(2024, 1, 1),))
    source_path = _write_source(
        tmp_path / "calendar.json",
        holidays=[{"tradingDate": "01-Jan-2024", "description": "New Year"}],
        special_sessions=[],
    )
    source = OfficialSessionCalendarEngine.load_source(source_path)
    engine = OfficialSessionCalendarEngine(warehouse)

    report = engine.reconcile(
        date(2024, 1, 1),
        date(2024, 1, 1),
        (source,),
    )

    assert report.conflict_count == 1
    assert report.records[0].issue_codes == ("HOLIDAY_HAS_OBSERVED_CANDLES",)


def test_calendar_report_and_exports_are_deterministic(tmp_path: Path) -> None:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    _seed_candles(warehouse, (date(2024, 1, 2),))
    source_path = _write_source(
        tmp_path / "calendar.json",
        holidays=[{"tradingDate": "01-Jan-2024", "description": "New Year"}],
        special_sessions=[],
    )
    source = OfficialSessionCalendarEngine.load_source(source_path)
    engine = OfficialSessionCalendarEngine(warehouse)

    first = engine.reconcile(
        date(2024, 1, 1),
        date(2024, 1, 2),
        (source,),
    )
    second = engine.reconcile(
        date(2024, 1, 1),
        date(2024, 1, 2),
        (source,),
    )

    assert first == second
    assert first.report_sha256 == second.report_sha256
    paths = engine.export(first, tmp_path / "artifacts")
    assert all(path.exists() for path in paths)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["report_sha256"] == first.report_sha256


def test_raw_nse_api_payload_uses_cm_segment(tmp_path: Path) -> None:
    path = tmp_path / "nse-api.json"
    path.write_text(
        json.dumps(
            {
                "CM": [
                    {
                        "tradingDate": "26-Jan-2026",
                        "description": "Republic Day",
                    }
                ],
                "FO": [
                    {
                        "tradingDate": "27-Jan-2026",
                        "description": "Not a CM fixture holiday",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    source = OfficialSessionCalendarEngine.load_source(path)

    assert source.covered_years == (2026,)
    assert tuple(item.trading_date for item in source.holidays) == (date(2026, 1, 26),)
