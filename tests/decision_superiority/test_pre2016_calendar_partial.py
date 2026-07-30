from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority import pre2016_calendar_partial
from alpha.decision_superiority.pre2016_calendar_partial import (
    audit_pre2016_calendar_partial,
)
from alpha.decision_superiority.pre2016_calendar_partial_artifacts import (
    export_pre2016_partial_calendar_audit,
)
from alpha.historical_truth.session_calendar import (
    AnnualSessionSummary,
    CalendarCertificationState,
    SessionCalendarRecord,
    SessionCalendarReport,
    SessionClassification,
)


def test_partial_audit_exposes_conflicts_without_certifying(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "official_2011_2012.json"
    source.write_text("{}\n", encoding="utf-8")
    database = tmp_path / "historical_truth.duckdb"
    database.write_bytes(b"duckdb-placeholder")
    manifest = tmp_path / "archive_manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "trading_date": "2011-01-26",
                "status": "unavailable",
                "error": "official archive returned HTTP 404",
                "source_url": "https://nsearchives.nseindia.com/example.zip",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = _partial_report()

    class FakeCalendarEngine:
        def __init__(self, _: object) -> None:
            pass

        @staticmethod
        def load_source(_: Path) -> object:
            return SimpleNamespace(covered_years=(2011, 2012))

        def reconcile(self, *_: object) -> SessionCalendarReport:
            return report

    monkeypatch.setattr(
        pre2016_calendar_partial,
        "OfficialSessionCalendarEngine",
        FakeCalendarEngine,
    )
    monkeypatch.setattr(
        pre2016_calendar_partial,
        "CanonicalPointInTimeWarehouse",
        lambda _: object(),
    )

    result = audit_pre2016_calendar_partial(
        database=database,
        manifest=manifest,
        official_sources=(source,),
    )

    assert result.covered_years == (2011, 2012)
    assert result.missing_years == (
        2005,
        2006,
        2007,
        2008,
        2009,
        2010,
        2013,
        2014,
        2015,
    )
    assert len(result.conflict_rows) == 1
    assert result.conflict_rows[0]["trading_date"] == date(2011, 10, 26)
    assert len(result.unresolved_rows) == 1
    assert result.unresolved_rows[0]["trading_date"] == date(2011, 3, 2)
    assert len(result.manifest_unavailable_rows) == 1
    assert result.manifest_unavailable_rows[0]["official_holiday_match"] is True
    assert result.report.certification_state is (
        CalendarCertificationState.INCOMPLETE_OFFICIAL_EVIDENCE
    )

    paths = export_pre2016_partial_calendar_audit(result, tmp_path / "output")
    assert len(paths) == 5
    summary = json.loads(paths[-1].read_text(encoding="utf-8"))
    assert summary["calendar_certification_permitted"] is False
    assert summary["conflict_count"] == 1
    assert summary["covered_year_unresolved_count"] == 1
    assert summary["covered_years"] == [2011, 2012]


def test_partial_calendar_command_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])
    assert result.exit_code == 0
    assert "decision-superiority-pre2016-calendar-partial-audit" in result.stdout


def _partial_report() -> SessionCalendarReport:
    annual = tuple(
        AnnualSessionSummary(
            year=year,
            official_source_covered=year in {2011, 2012},
            weekday_candidates=1,
            official_weekday_holidays=1 if year == 2011 else 0,
            official_special_sessions=0,
            expected_sessions=1,
            observed_sessions=1 if year in {2011, 2012} else 0,
            unresolved_weekdays=1 if year == 2011 else 0,
            unconfirmed_special_sessions=0,
            missing_special_sessions=0,
            conflicts=1 if year == 2011 else 0,
        )
        for year in range(2005, 2016)
    )
    records = (
        SessionCalendarRecord(
            trading_date=date(2011, 1, 26),
            classification=SessionClassification.HOLIDAY,
            observed_candles=False,
            description="Republic Day",
            source_ids=("official-2011",),
            issue_codes=(),
        ),
        SessionCalendarRecord(
            trading_date=date(2011, 3, 2),
            classification=SessionClassification.UNRESOLVED_WEEKDAY,
            observed_candles=False,
            description=None,
            source_ids=(),
            issue_codes=(),
        ),
        SessionCalendarRecord(
            trading_date=date(2011, 10, 26),
            classification=SessionClassification.HOLIDAY,
            observed_candles=True,
            description="Diwali Laxmi Pujan",
            source_ids=("official-2011",),
            issue_codes=("HOLIDAY_HAS_OBSERVED_CANDLES",),
        ),
    )
    return SessionCalendarReport(
        contract_version="1.0",
        start_date=date(2005, 1, 1),
        end_date=date(2015, 12, 31),
        exchange="nse",
        certification_state=CalendarCertificationState.INCOMPLETE_OFFICIAL_EVIDENCE,
        sources=(),
        annual_summaries=annual,
        records=records,
        official_holiday_count=2,
        official_special_session_count=0,
        expected_session_count=2,
        observed_session_count=2,
        unresolved_weekday_count=1,
        unconfirmed_special_session_count=0,
        missing_special_session_count=0,
        conflict_count=1,
        report_sha256="partial-report",
    )
