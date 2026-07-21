from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.cli import historical_truth_app
from alpha.historical_truth.session_calendar import (
    CalendarCertificationState,
    OfficialSessionCalendarEngine,
)
from alpha.historical_truth.special_session_recovery import (
    PRODUCTION_INFLUENCE,
    SpecialSessionCandleRecoveryEngine,
    SpecialSessionFailureCode,
    SpecialSessionIngestionStatus,
    SpecialSessionRecoveryStatus,
    SpecialSessionValidationStatus,
)

SPECIAL_SESSIONS = (
    date(2016, 10, 30),
    date(2019, 10, 27),
    date(2020, 11, 14),
    date(2023, 11, 12),
)


class _History:
    def __init__(self, url: str) -> None:
        self.url = url


class _Response:
    def __init__(
        self,
        content: bytes,
        *,
        status_code: int = 200,
        content_type: str = "application/zip",
        url: str | None = None,
        history: tuple[_History, ...] = (),
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.url = url
        self.history = history


class _Session:
    def __init__(self, responses: dict[str, _Response]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: Any) -> _Response:
        self.calls.append(url)
        response = self.responses.get(
            url,
            _Response(b"not found", status_code=404, content_type="text/plain"),
        )
        if response.url is None:
            response.url = url
        return response


def _fixed_clock() -> datetime:
    return datetime(2026, 7, 22, 10, 0, tzinfo=UTC)


def _calendar_report(
    tmp_path: Path,
    special_sessions: tuple[date, ...] = (SPECIAL_SESSIONS[0],),
) -> Path:
    source_path = tmp_path / "official_calendar_source.json"
    source_payload = {
        "covered_years": sorted({item.year for item in special_sessions}),
        "source_url": "https://archives.nseindia.com/content/circulars/fixture.pdf",
        "holidays": [],
        "special_sessions": [
            {
                "tradingDate": item.strftime("%d-%b-%Y"),
                "description": "Official NSE Muhurat trading session",
            }
            for item in special_sessions
        ],
    }
    source_path.write_text(
        json.dumps(source_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    source_id = f"nse-calendar:{source_sha}"
    payload: dict[str, object] = {
        "contract_version": "HTR-007-v1.0.0",
        "sources": [
            {
                "source_id": source_id,
                "source_path": str(source_path),
                "source_url": source_payload["source_url"],
                "source_sha256": source_sha,
                "covered_years": source_payload["covered_years"],
                "holiday_count": 0,
                "special_session_count": len(special_sessions),
            }
        ],
        "records": [
            {
                "trading_date": item.isoformat(),
                "classification": "special_session",
                "observed_candles": False,
                "description": "Official NSE Muhurat trading session",
                "source_ids": [source_id],
                "issue_codes": ["MISSING_OFFICIAL_SPECIAL_SESSION"],
            }
            for item in special_sessions
        ],
    }
    payload["report_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    report = tmp_path / "htr007_session_calendar.json"
    report.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _csv(
    trading_date: date,
    *,
    symbol: str = "ALPHA",
    open_price: float = 100.0,
    high_price: float = 110.0,
    low_price: float = 95.0,
    close_price: float = 108.0,
    volume: int = 1000,
) -> bytes:
    return (
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,ISIN,TIMESTAMP\n"
        f"{symbol},EQ,{open_price},{high_price},{low_price},{close_price},"
        f"{volume},INE000000001,{trading_date.strftime('%d-%b-%Y')}\n"
    ).encode()


def _zip(
    trading_date: date,
    raw_csv: bytes | None = None,
    *,
    member_date: date | None = None,
) -> bytes:
    member_date = member_date or trading_date
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        token = member_date.strftime("%d%b%Y").upper()
        archive.writestr(
            f"cm{token}bhav.csv",
            raw_csv if raw_csv is not None else _csv(trading_date),
        )
    return output.getvalue()


def _source_url(trading_date: date, index: int = 0) -> str:
    return SpecialSessionCandleRecoveryEngine._source_candidates(trading_date)[index][1]


def _engine(
    tmp_path: Path,
    session: _Session,
) -> tuple[SpecialSessionCandleRecoveryEngine, CanonicalPointInTimeWarehouse]:
    canonical = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    engine = SpecialSessionCandleRecoveryEngine(
        tmp_path / "alpha_data",
        canonical,
        session=session,  # type: ignore[arg-type]
        clock=_fixed_clock,
    )
    return engine, canonical


def _successful_session(
    trading_dates: tuple[date, ...],
) -> _Session:
    return _Session(
        {
            _source_url(item): _Response(_zip(item), url=_source_url(item))
            for item in trading_dates
        }
    )


def test_missing_official_weekend_session_is_acquired_and_ingested(
    tmp_path: Path,
) -> None:
    trading_date = SPECIAL_SESSIONS[0]
    calendar = _calendar_report(tmp_path)
    session = _successful_session((trading_date,))
    engine, canonical = _engine(tmp_path, session)

    report = engine.recover(calendar)

    record = report.records[0]
    assert report.complete
    assert record.recovery_status is SpecialSessionRecoveryStatus.COMPLETE
    assert record.validation_status is SpecialSessionValidationStatus.VALID
    assert record.ingestion_status is SpecialSessionIngestionStatus.INGESTED
    assert record.row_count == 1
    assert record.unique_securities == 1
    assert record.source_sha256
    assert record.raw_archive_path and Path(record.raw_archive_path).exists()
    assert record.normalized_path and Path(record.normalized_path).exists()
    assert canonical.snapshot(trading_date).symbol_count == 1


def test_ordinary_weekend_is_rejected_without_network_access(tmp_path: Path) -> None:
    ordinary_weekend = date(2016, 10, 29)
    calendar = _calendar_report(tmp_path)
    session = _Session({})
    engine, canonical = _engine(tmp_path, session)

    report = engine.recover(calendar, selected_dates=(ordinary_weekend,))

    record = report.records[0]
    assert record.failure_code is SpecialSessionFailureCode.NOT_OFFICIAL_SPECIAL_SESSION
    assert session.calls == []
    assert canonical.snapshot(ordinary_weekend).symbol_count == 0


def test_archive_member_date_mismatch_fails_closed(tmp_path: Path) -> None:
    trading_date = SPECIAL_SESSIONS[0]
    calendar = _calendar_report(tmp_path)
    session = _Session(
        {
            _source_url(trading_date): _Response(
                _zip(trading_date, member_date=date(2016, 10, 31))
            )
        }
    )
    engine, canonical = _engine(tmp_path, session)

    record = engine.recover(calendar).records[0]

    assert record.failure_code is SpecialSessionFailureCode.ARCHIVE_DATE_MISMATCH
    assert canonical.snapshot(trading_date).symbol_count == 0


def test_candle_row_date_mismatch_fails_closed(tmp_path: Path) -> None:
    trading_date = SPECIAL_SESSIONS[0]
    calendar = _calendar_report(tmp_path)
    session = _Session(
        {
            _source_url(trading_date): _Response(
                _zip(trading_date, _csv(date(2016, 10, 31)))
            )
        }
    )
    engine, canonical = _engine(tmp_path, session)

    record = engine.recover(calendar).records[0]

    assert record.failure_code is SpecialSessionFailureCode.SOURCE_DATE_MISMATCH
    assert record.validation_findings[0].code == "SOURCE_DATE_MISMATCH"
    assert canonical.snapshot(trading_date).symbol_count == 0


def test_mixed_date_source_file_fails_closed(tmp_path: Path) -> None:
    trading_date = SPECIAL_SESSIONS[0]
    mixed = (
        _csv(trading_date) + _csv(date(2016, 10, 31), symbol="BETA").split(b"\n", 1)[1]
    )
    calendar = _calendar_report(tmp_path)
    session = _Session(
        {_source_url(trading_date): _Response(_zip(trading_date, mixed))}
    )
    engine, canonical = _engine(tmp_path, session)

    record = engine.recover(calendar).records[0]

    assert record.failure_code is SpecialSessionFailureCode.MIXED_TRADING_DATES
    assert canonical.snapshot(trading_date).symbol_count == 0


def test_impossible_ohlc_is_rejected(tmp_path: Path) -> None:
    trading_date = SPECIAL_SESSIONS[0]
    calendar = _calendar_report(tmp_path)
    invalid = _csv(trading_date, high_price=90.0, low_price=95.0)
    session = _Session(
        {_source_url(trading_date): _Response(_zip(trading_date, invalid))}
    )
    engine, canonical = _engine(tmp_path, session)

    record = engine.recover(calendar).records[0]

    assert record.failure_code is SpecialSessionFailureCode.INVALID_CANDLE_DATA
    assert any(item.code == "IMPOSSIBLE_OHLC" for item in record.validation_findings)
    assert canonical.snapshot(trading_date).symbol_count == 0


def test_identical_existing_rows_are_idempotently_reused(tmp_path: Path) -> None:
    trading_date = SPECIAL_SESSIONS[0]
    calendar = _calendar_report(tmp_path)
    session = _successful_session((trading_date,))
    engine, canonical = _engine(tmp_path, session)

    first = engine.recover(calendar)
    second = engine.recover(calendar)

    assert first.records[0].inserted_rows == 1
    assert second.records[0].recovery_status is SpecialSessionRecoveryStatus.REUSED
    assert second.records[0].reused_rows == 1
    assert second.records[0].lineage_rows == 0
    assert len(session.calls) == 1
    assert canonical.snapshot(trading_date).symbol_count == 1


def test_conflicting_canonical_rows_are_not_overwritten(tmp_path: Path) -> None:
    trading_date = SPECIAL_SESSIONS[0]
    calendar = _calendar_report(tmp_path)
    session = _successful_session((trading_date,))
    engine, canonical = _engine(tmp_path, session)
    existing = tmp_path / "existing.csv"
    existing.write_bytes(_csv(trading_date, close_price=101.0))
    canonical.ingest_bhavcopy_csv(
        existing,
        trading_date=trading_date,
        source_sha256="existing-source",
    )

    record = engine.recover(calendar).records[0]

    assert record.failure_code is SpecialSessionFailureCode.CANONICAL_CONFLICT
    assert record.ingestion_status is SpecialSessionIngestionStatus.CONFLICT
    assert canonical.snapshot(trading_date).candles[0].close_price == 101.0


def test_tampered_immutable_archive_fails_checksum_verification(
    tmp_path: Path,
) -> None:
    trading_date = SPECIAL_SESSIONS[0]
    calendar = _calendar_report(tmp_path)
    session = _successful_session((trading_date,))
    engine, _ = _engine(tmp_path, session)
    first = engine.recover(calendar)
    archive = Path(first.records[0].raw_archive_path or "")
    archive.write_bytes(b"tampered")

    record = engine.recover(calendar).records[0]

    assert record.failure_code is SpecialSessionFailureCode.CHECKSUM_MISMATCH


def test_partial_recovery_reports_each_date_independently(tmp_path: Path) -> None:
    sessions = SPECIAL_SESSIONS[:2]
    calendar = _calendar_report(tmp_path, sessions)
    session = _successful_session((sessions[0],))
    engine, canonical = _engine(tmp_path, session)

    report = engine.recover(calendar)

    assert report.complete_count == 1
    assert report.failed_count == 1
    assert report.records[1].failure_code is (
        SpecialSessionFailureCode.OFFICIAL_ARCHIVE_NOT_FOUND
    )
    assert len(report.records[1].attempts) == 2
    assert canonical.snapshot(sessions[0]).symbol_count == 1
    assert canonical.snapshot(sessions[1]).symbol_count == 0


def test_all_four_special_sessions_recover_and_export_exact_audit_set(
    tmp_path: Path,
) -> None:
    calendar = _calendar_report(tmp_path, SPECIAL_SESSIONS)
    session = _successful_session(SPECIAL_SESSIONS)
    engine, canonical = _engine(tmp_path, session)

    report = engine.recover(calendar)
    paths = engine.export(report, tmp_path / "artifacts")

    assert report.complete_count == 4
    assert report.failed_count == 0
    assert len(paths) == 7
    assert {path.name for path in paths} == {
        "htr007b_special_session_recovery.json",
        "htr007b_special_session_recovery.csv",
        "htr007b_special_session_recovery.md",
        "htr007b_special_session_validation.json",
        "htr007b_special_session_validation.csv",
        "htr007b_special_session_ingestion.json",
        "htr007b_special_session_ingestion.csv",
    }
    assert all(canonical.snapshot(item).symbol_count == 1 for item in SPECIAL_SESSIONS)


def test_calendar_certification_changes_only_after_canonical_ingestion(
    tmp_path: Path,
) -> None:
    trading_date = SPECIAL_SESSIONS[0]
    source_file = tmp_path / "calendar_source.json"
    source_file.write_text(
        json.dumps(
            {
                "covered_years": [trading_date.year],
                "source_url": "https://archives.nseindia.com/official.pdf",
                "holidays": [],
                "special_sessions": [
                    {
                        "tradingDate": trading_date.strftime("%d-%b-%Y"),
                        "description": "Official NSE Muhurat trading session",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    canonical = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    calendar_engine = OfficialSessionCalendarEngine(canonical)
    source = calendar_engine.load_source(source_file)
    before = calendar_engine.reconcile(
        trading_date,
        trading_date,
        (source,),
    )
    report_path = calendar_engine.export(before, tmp_path / "calendar")[0]
    session = _successful_session((trading_date,))
    recovery = SpecialSessionCandleRecoveryEngine(
        tmp_path / "alpha_data",
        canonical,
        session=session,  # type: ignore[arg-type]
        clock=_fixed_clock,
    )

    assert before.certification_state is (
        CalendarCertificationState.INCOMPLETE_OFFICIAL_EVIDENCE
    )
    assert recovery.recover(report_path).complete
    after = calendar_engine.reconcile(
        trading_date,
        trading_date,
        (source,),
    )
    assert after.certification_state is CalendarCertificationState.CERTIFIED


def test_cli_command_is_registered_and_production_influence_is_false() -> None:
    result = CliRunner().invoke(historical_truth_app, ["--help"])

    assert result.exit_code == 0
    assert "special-session-candle-recover" in result.stdout
    assert PRODUCTION_INFLUENCE is False


def test_cli_recovers_session_and_writes_governed_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trading_date = SPECIAL_SESSIONS[0]
    calendar = _calendar_report(tmp_path)

    def fake_get(
        session: object,
        url: str,
        **_: object,
    ) -> _Response:
        del session
        return _Response(_zip(trading_date), url=url)

    monkeypatch.setattr("requests.Session.get", fake_get)
    output = tmp_path / "artifacts"
    result = CliRunner().invoke(
        historical_truth_app,
        [
            "special-session-candle-recover",
            "--calendar-report",
            str(calendar),
            "--database",
            str(tmp_path / "truth.duckdb"),
            "--root",
            str(tmp_path / "alpha_data"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "Recovered: 1" in result.stdout
    assert "PRODUCTION_INFLUENCE=false" in result.stdout
    assert len(tuple(output.iterdir())) == 7
