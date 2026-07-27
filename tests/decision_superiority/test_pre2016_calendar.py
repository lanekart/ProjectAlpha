from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority import pre2016_calendar
from alpha.decision_superiority.pre2016_calendar import (
    certify_pre2016_calendar,
    validate_pre2016_calendar_report,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
    Pre2016ExternalValidationError,
)
from alpha.historical_truth.session_calendar import (
    AnnualSessionSummary,
    CalendarCertificationState,
    SessionCalendarRecord,
    SessionCalendarReport,
    SessionClassification,
)


def test_lowercase_unavailable_manifest_status_is_reconciled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "official_calendar.json"
    source.write_text("{}\n", encoding="utf-8")
    manifest = tmp_path / "archive_manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "exchange": "nse",
                "dataset": "bhavcopy",
                "trading_date": "2005-01-26",
                "status": "unavailable",
                "error": "official archive returned HTTP 404",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    database = tmp_path / "historical_truth.duckdb"
    database.write_bytes(b"duckdb-placeholder")

    report = _calendar_report()

    class FakeCalendarEngine:
        def __init__(self, _: object) -> None:
            pass

        @staticmethod
        def load_source(_: Path) -> object:
            return SimpleNamespace(covered_years=tuple(range(2005, 2016)))

        def reconcile(self, *_: object) -> SessionCalendarReport:
            return report

    monkeypatch.setattr(
        pre2016_calendar,
        "OfficialSessionCalendarEngine",
        FakeCalendarEngine,
    )
    monkeypatch.setattr(
        pre2016_calendar,
        "CanonicalPointInTimeWarehouse",
        lambda _: object(),
    )
    monkeypatch.setattr(
        pre2016_calendar,
        "validate_hash_bound_official_calendar_source",
        lambda *_args, **_kwargs: {},
    )

    result = certify_pre2016_calendar(
        database=database,
        manifest=manifest,
        official_sources=(source,),
    )

    assert result.manifest_unavailable_count == 1
    assert result.manifest_holiday_match_count == 1
    assert result.manifest_unresolved_count == 0
    assert result.manifest_rows[0]["manifest_status_normalized"] == "unavailable"
    assert result.manifest_rows[0]["official_holiday_match"] is True


def test_calendar_certification_rejects_missing_official_years(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "official_calendar.json"
    source.write_text("{}\n", encoding="utf-8")
    manifest = tmp_path / "archive_manifest.jsonl"
    manifest.write_text("", encoding="utf-8")
    database = tmp_path / "historical_truth.duckdb"
    database.write_bytes(b"duckdb-placeholder")

    monkeypatch.setattr(
        pre2016_calendar.OfficialSessionCalendarEngine,
        "load_source",
        lambda _: SimpleNamespace(covered_years=(2015,)),
    )
    monkeypatch.setattr(
        pre2016_calendar,
        "validate_hash_bound_official_calendar_source",
        lambda *_args, **_kwargs: {},
    )

    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_OFFICIAL_CALENDAR_YEARS_MISSING",
    ):
        certify_pre2016_calendar(
            database=database,
            manifest=manifest,
            official_sources=(source,),
        )


def test_calendar_report_must_be_certified_and_hash_bound(tmp_path: Path) -> None:
    source = tmp_path / "official_source.json"
    source.write_text('{"covered_years":[2005]}\n', encoding="utf-8")
    payload = _calendar_payload(
        source,
        certification_state="incomplete_official_evidence",
    )
    report = tmp_path / "htr007_session_calendar.json"
    report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_CALENDAR_NOT_CERTIFIED",
    ):
        validate_pre2016_calendar_report(report)

    payload["certification_state"] = "certified"
    payload["report_sha256"] = "tampered"
    report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_CALENDAR_REPORT_HASH_MISMATCH",
    ):
        validate_pre2016_calendar_report(report)


def test_calendar_report_verifies_bound_source_hash(tmp_path: Path) -> None:
    source = tmp_path / "official_source.json"
    source.write_text('{"covered_years":[2005]}\n', encoding="utf-8")
    payload = _calendar_payload(source, certification_state="certified")
    report = tmp_path / "htr007_session_calendar.json"
    report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    source.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_CALENDAR_SOURCE_HASH_MISMATCH",
    ):
        validate_pre2016_calendar_report(report)


def test_calendar_cli_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])
    assert result.exit_code == 0
    assert "decision-superiority-pre2016-calendar-certify" in result.stdout


def _calendar_report() -> SessionCalendarReport:
    annual = tuple(
        AnnualSessionSummary(
            year=year,
            official_source_covered=True,
            weekday_candidates=1,
            official_weekday_holidays=1 if year == 2005 else 0,
            official_special_sessions=0,
            expected_sessions=0,
            observed_sessions=0,
            unresolved_weekdays=0,
            unconfirmed_special_sessions=0,
            missing_special_sessions=0,
            conflicts=0,
        )
        for year in range(2005, 2016)
    )
    records = (
        SessionCalendarRecord(
            trading_date=date(2005, 1, 26),
            classification=SessionClassification.HOLIDAY,
            observed_candles=False,
            description="Republic Day",
            source_ids=("official",),
            issue_codes=(),
        ),
    )
    return SessionCalendarReport(
        contract_version="1.0",
        start_date=date(2005, 1, 1),
        end_date=date(2015, 12, 31),
        exchange="nse",
        certification_state=CalendarCertificationState.CERTIFIED,
        sources=(),
        annual_summaries=annual,
        records=records,
        official_holiday_count=1,
        official_special_session_count=0,
        expected_session_count=0,
        observed_session_count=0,
        unresolved_weekday_count=0,
        unconfirmed_special_session_count=0,
        missing_special_session_count=0,
        conflict_count=0,
        report_sha256="report",
    )


def _calendar_payload(source: Path, *, certification_state: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": "1.0",
        "start_date": "2005-01-01",
        "end_date": "2015-12-31",
        "exchange": "nse",
        "certification_state": certification_state,
        "sources": [
            {
                "source_path": str(source),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        ],
        "annual_summaries": [],
        "records": [],
        "official_holiday_count": 153,
        "official_special_session_count": 0,
        "expected_session_count": 2716,
        "observed_session_count": 2716,
        "unresolved_weekday_count": 0,
        "unconfirmed_special_session_count": 0,
        "missing_special_session_count": 0,
        "conflict_count": 0,
    }
    payload["report_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload
