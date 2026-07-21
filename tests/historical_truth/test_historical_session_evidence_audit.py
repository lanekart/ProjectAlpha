from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from alpha.historical_truth.historical_session_evidence import (
    HistoricalEvidenceRecord,
    HistoricalEvidenceStatus,
    HistoricalSessionEvidenceEngine,
)
from alpha.historical_truth.historical_session_evidence_audit import (
    NSE_CIRCULAR_DIRECTORY,
    NSE_HOLIDAY_DIRECTORY,
    AcquisitionFailureCode,
    DocumentParser,
    HistoricalSessionEvidenceRepairEngine,
)
from alpha.historical_truth.historical_session_evidence_cli import _progress


class _History:
    def __init__(self, url: str) -> None:
        self.url = url


class _Response:
    def __init__(
        self,
        content: bytes,
        *,
        status_code: int = 200,
        url: str = "",
        content_type: str = "text/html",
        history: tuple[_History, ...] = (),
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.url = url
        self.headers = {"Content-Type": content_type}
        self.history = history


class _Session:
    def __init__(self, responses: dict[str, _Response]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: Any) -> _Response:
        self.calls.append(url)
        return self.responses[url]


def _failed_record(
    year: int, error: str = "RuntimeError: HTTP 404"
) -> HistoricalEvidenceRecord:
    return HistoricalEvidenceRecord(
        year=year,
        status=HistoricalEvidenceStatus.FAILED,
        year_page_url=(
            f"https://www.nseindia.com/static/holidays-for-the-calendar-year-{year}"
        ),
        year_page_path=None,
        year_page_sha256=None,
        circular_url=None,
        circular_path=None,
        circular_sha256=None,
        normalized_path=None,
        normalized_sha256=None,
        holiday_count=0,
        special_session_count=0,
        error=error,
    )


def _annual_text(year: int) -> str:
    return f"""
    Capital Market (Equities)
    Trading holidays for the calendar year {year}
    1 26-January-{year} Republic Day
    2 08-March-{year} Festival
    3 25-March-{year} Festival
    4 29-March-{year} Festival
    5 11-April-{year} Festival
    6 17-April-{year} Festival
    7 01-May-{year} Maharashtra Day
    8 17-June-{year} Festival
    9 15-August-{year} Independence Day
    10 02-October-{year} Gandhi Jayanti
    11 01-November-{year} Diwali Laxmi Pujan
    12 25-December-{year} Christmas
    The holidays falling on Saturday / Sunday are as follows
    Muhurat Trading will be conducted on November 01, {year}.
    """


def test_content_inspection_uses_bytes_before_filename() -> None:
    parser, extension = HistoricalSessionEvidenceRepairEngine.inspect_content(
        b"%PDF-fixture", "text/html", "https://nsearchives.nseindia.com/a.html"
    )

    assert parser is DocumentParser.PDF
    assert extension == ".pdf"


def test_pdf_redirected_to_html_is_structured_failure(tmp_path: Path) -> None:
    url = "https://nsearchives.nseindia.com/content/circulars/CMTR1.pdf"
    session = _Session(
        {
            url: _Response(
                b"<html>access page</html>",
                url=url,
                content_type="text/html",
                history=(_History("https://www.nseindia.com/redirect"),),
            )
        }
    )
    engine = HistoricalSessionEvidenceRepairEngine(tmp_path)

    document = engine._fetch(
        2024,
        "test",
        url,
        session,
        {},
        1,
    )

    assert document is None
    attempt = engine.attempts[-1]
    assert attempt.failure_code is AcquisitionFailureCode.REDIRECTED_TO_HTML
    assert attempt.redirect_chain == ("https://www.nseindia.com/redirect",)


def test_discovery_keeps_official_cm_and_rejects_derivative_segment() -> None:
    page = """
    <div>2024 Capital Market trading holiday
      <a href="https://nsearchives.nseindia.com/content/circulars/CMTR123.pdf">CM</a>
      <a href="https://nsearchives.nseindia.com/content/circulars/FAOP124.pdf">FO</a>
      <a href="https://example.com/CMTR999.pdf">Third party</a>
    </div>
    """

    result = HistoricalSessionEvidenceRepairEngine.discover_documents(
        page,
        NSE_CIRCULAR_DIRECTORY,
        2024,
    )

    assert result == ("https://nsearchives.nseindia.com/content/circulars/CMTR123.pdf",)


def test_repair_admits_valid_alternate_official_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year = 2024
    attachment = "https://nsearchives.nseindia.com/content/circulars/CMTR123.pdf"
    holiday_page = f"{NSE_HOLIDAY_DIRECTORY}?year={year}"
    page = f"""
    <html><div>{year} Capital Market trading holiday
      <a href="{attachment}">official circular</a>
    </div></html>
    """.encode()
    session = _Session(
        {
            holiday_page: _Response(page, url=holiday_page),
            attachment: _Response(
                b"%PDF-fixture",
                url=attachment,
                content_type="application/pdf",
            ),
        }
    )
    monkeypatch.setattr(
        HistoricalSessionEvidenceEngine,
        "acquire_year",
        lambda self, requested_year, **kwargs: _failed_record(requested_year),
    )
    monkeypatch.setattr(
        HistoricalSessionEvidenceRepairEngine,
        "extract_pdf_text",
        staticmethod(lambda _: _annual_text(year)),
    )
    if (
        "source_family"
        in inspect.signature(
            HistoricalSessionEvidenceEngine._normalized_payload
        ).parameters
    ):
        monkeypatch.setattr(
            HistoricalSessionEvidenceRepairEngine,
            "_normalized_payload",
            staticmethod(
                lambda parsed, **kwargs: {
                    "contract_version": "1.0",
                    "covered_years": [parsed.year],
                    "source_url": kwargs["circular_url"],
                    "source_evidence": {
                        key: str(value) for key, value in kwargs.items()
                    },
                    "holidays": [
                        {"date": item.isoformat(), "description": "holiday"}
                        for item in parsed.holidays
                    ],
                    "special_sessions": [
                        {"date": item.isoformat(), "description": "special"}
                        for item in parsed.special_sessions
                    ],
                }
            ),
        )
    engine = HistoricalSessionEvidenceRepairEngine(tmp_path / "alpha_data")

    record = engine.acquire_year_repaired(year, session=session)

    assert record.status is HistoricalEvidenceStatus.COMPLETE
    assert record.holiday_count == 12
    assert record.special_session_count == 1
    assert record.circular_url == attachment
    assert record.normalized_path is not None
    assert Path(record.normalized_path).exists()
    assert any(item.evidence_status == "admitted" for item in engine.attempts)


def test_failed_candidates_remain_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year = 2023
    holiday_page = f"{NSE_HOLIDAY_DIRECTORY}?year={year}"
    session = _Session(
        {
            holiday_page: _Response(b"missing", status_code=404, url=holiday_page),
            NSE_CIRCULAR_DIRECTORY: _Response(
                b"missing", status_code=404, url=NSE_CIRCULAR_DIRECTORY
            ),
        }
    )
    monkeypatch.setattr(
        HistoricalSessionEvidenceEngine,
        "acquire_year",
        lambda self, requested_year, **kwargs: _failed_record(requested_year),
    )
    engine = HistoricalSessionEvidenceRepairEngine(tmp_path / "alpha_data")

    record = engine.acquire_year_repaired(year, session=session)

    assert record.status is HistoricalEvidenceStatus.FAILED
    assert [item.failure_code for item in engine.attempts] == [
        AcquisitionFailureCode.OFFICIAL_DOCUMENT_NOT_FOUND,
        AcquisitionFailureCode.OFFICIAL_DOCUMENT_NOT_FOUND,
        AcquisitionFailureCode.OFFICIAL_DOCUMENT_NOT_FOUND,
    ]


def test_audit_exports_have_governed_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year = 2022
    holiday_page = f"{NSE_HOLIDAY_DIRECTORY}?year={year}"
    session = _Session(
        {
            holiday_page: _Response(b"missing", status_code=404, url=holiday_page),
            NSE_CIRCULAR_DIRECTORY: _Response(
                b"missing", status_code=404, url=NSE_CIRCULAR_DIRECTORY
            ),
        }
    )
    monkeypatch.setattr(
        HistoricalSessionEvidenceEngine,
        "acquire_year",
        lambda self, requested_year, **kwargs: _failed_record(requested_year),
    )
    engine = HistoricalSessionEvidenceRepairEngine(tmp_path / "alpha_data")
    evidence, audit = engine.acquire_range_with_audit(year, year, session=session)

    paths = engine.export_audit(audit, tmp_path / "artifacts")

    assert evidence.failed_count == 1
    assert tuple(path.name for path in paths) == (
        "htr007a_acquisition_audit.json",
        "htr007a_acquisition_audit.csv",
        "htr007a_acquisition_audit.md",
        "htr007a_rejected_evidence.json",
        "htr007a_rejected_evidence.csv",
    )
    assert all(path.exists() for path in paths)


def test_primary_failure_mapping_is_structured() -> None:
    attempt = HistoricalSessionEvidenceRepairEngine._primary_attempt(
        _failed_record(2021, "ValueError: resolved attachment is not a PDF")
    )

    assert attempt.failure_code is AcquisitionFailureCode.REDIRECTED_TO_HTML


def test_captured_progress_does_not_use_carriage_returns(capsys: Any) -> None:
    _progress("Annual NSE evidence", 1, 2, "2024")
    _progress("Annual NSE evidence", 2, 2, "2025")

    output = capsys.readouterr().out
    assert "\r" not in output
    assert output.splitlines() == [
        "Annual NSE evidence: 1/2 | 2024",
        "Annual NSE evidence: 2/2 | 2025",
    ]
