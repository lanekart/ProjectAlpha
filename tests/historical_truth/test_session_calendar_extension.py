from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from alpha.__main__ import _historical_truth_app
from alpha.historical_truth.adjustment_replay_admission_integrity_engine import (
    economic_weight_measurement_state,
)
from alpha.historical_truth.adjustment_replay_admission_session_coverage import (
    governed_session_coverage,
)
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.session_calendar import (
    CalendarCertificationState,
    OfficialSessionCalendarEngine,
)
from alpha.historical_truth.session_calendar_extension import (
    GovernedSessionCalendarExtensionEngine,
)


def _seed_candles(path: Path, trading_dates: tuple[date, ...]) -> None:
    warehouse = CanonicalPointInTimeWarehouse(path)
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


def _source(path: Path, year: int) -> Path:
    path.write_text(
        json.dumps(
            {
                "covered_years": [year],
                "source_url": "https://www.nseindia.com/official-fixture",
                "holidays": [],
                "special_sessions": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _existing_report(tmp_path: Path, database: Path) -> Path:
    source_path = _source(tmp_path / "calendar-2025.json", 2025)
    source = OfficialSessionCalendarEngine.load_source(source_path)
    warehouse = CanonicalPointInTimeWarehouse(database)
    report = OfficialSessionCalendarEngine(warehouse).reconcile(
        date(2025, 12, 29),
        date(2025, 12, 31),
        (source,),
    )
    assert report.certification_state is CalendarCertificationState.CERTIFIED
    return OfficialSessionCalendarEngine(warehouse).export(
        report,
        tmp_path / "existing",
    )[0]


def test_extension_appends_2026_and_preserves_historical_parity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    _seed_candles(
        database,
        (
            date(2025, 12, 29),
            date(2025, 12, 30),
            date(2025, 12, 31),
            date(2026, 1, 1),
            date(2026, 1, 2),
        ),
    )
    existing = _existing_report(tmp_path, database)
    current = _source(tmp_path / "calendar-2026.json", 2026)

    report, audit = GovernedSessionCalendarExtensionEngine().extend(
        existing_calendar_report=existing,
        database_path=database,
        source_dir=tmp_path / "sources",
        through_date=date(2026, 1, 2),
        current_source_path=current,
        refresh=False,
    )

    assert report.certification_state is CalendarCertificationState.CERTIFIED
    assert report.end_date == date(2026, 1, 2)
    assert report.expected_session_count == 5
    assert report.observed_session_count == 5
    assert audit.appended_years == (2026,)
    assert audit.historical_parity_mismatch_count == 0
    assert audit.historical_parity_state == "HISTORICAL_CALENDAR_PARITY_PRESERVED"
    assert len(report.sources) == 2


def test_extension_rejects_source_without_required_year(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _seed_candles(
        database,
        (
            date(2025, 12, 29),
            date(2025, 12, 30),
            date(2025, 12, 31),
        ),
    )
    existing = _existing_report(tmp_path, database)
    wrong_source = _source(tmp_path / "calendar-2024.json", 2024)

    try:
        GovernedSessionCalendarExtensionEngine().extend(
            existing_calendar_report=existing,
            database_path=database,
            source_dir=tmp_path / "sources",
            through_date=date(2026, 1, 2),
            current_source_path=wrong_source,
            refresh=False,
        )
    except ValueError as exc:
        assert "does not cover required years" in str(exc)
    else:
        raise AssertionError("missing target-year evidence must fail closed")


def test_extension_rejects_tampered_existing_report(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _seed_candles(
        database,
        (
            date(2025, 12, 29),
            date(2025, 12, 30),
            date(2025, 12, 31),
        ),
    )
    existing = _existing_report(tmp_path, database)
    payload = json.loads(existing.read_text(encoding="utf-8"))
    payload["end_date"] = "2025-12-30"
    existing.write_text(json.dumps(payload), encoding="utf-8")

    try:
        GovernedSessionCalendarExtensionEngine().extend(
            existing_calendar_report=existing,
            database_path=database,
            source_dir=tmp_path / "sources",
            through_date=date(2026, 1, 2),
            current_source_path=_source(tmp_path / "calendar-2026.json", 2026),
            refresh=False,
        )
    except ValueError as exc:
        assert "checksum mismatch" in str(exc)
    else:
        raise AssertionError("tampered governed report must fail closed")


def test_stale_calendar_reports_beyond_window_not_database_mismatch(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    _seed_candles(
        database,
        (
            date(2025, 12, 29),
            date(2025, 12, 30),
            date(2025, 12, 31),
            date(2026, 1, 1),
        ),
    )
    existing = _existing_report(tmp_path, database)

    result = governed_session_coverage(
        calendar_report=existing,
        database_path=database,
        start_date=date(2025, 12, 29),
        end_date=date(2026, 1, 1),
    )

    assert result["calendar_database_disagreement_count"] == 0
    assert result["observations_beyond_governed_calendar_window_count"] == 1
    assert "OBSERVATIONS_BEYOND_GOVERNED_CALENDAR_WINDOW" in result["blockers"]
    assert "CALENDAR_DATABASE_OBSERVATION_MISMATCH" not in result["blockers"]


def test_economic_weight_state_requires_governed_complete_window() -> None:
    assert economic_weight_measurement_state(
        {"state": "GOVERNED_SESSION_COVERAGE_INCOMPLETE"}
    ) == "MEASURED_OBSERVED_DATABASE_WINDOW"
    assert economic_weight_measurement_state(
        {"state": "GOVERNED_SESSION_COVERAGE_COMPLETE"}
    ) == "MEASURED_GOVERNED_COMPLETE_WINDOW"


def test_extension_command_is_visible_once() -> None:
    app = _historical_truth_app()
    names = [command.name for command in app.registered_commands]
    assert names.count("session-calendar-extend-certify") == 1
