from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alpha.historical_truth.historical_session_evidence import (
    HistoricalEvidenceStatus,
    HistoricalSessionEvidenceEngine,
)
from alpha.historical_truth.session_calendar import OfficialSessionCalendarEngine


class _Response:
    def __init__(self, content: bytes, *, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, responses: dict[str, _Response]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: Any) -> _Response:
        self.calls.append(url)
        return self.responses[url]


def _annual_text(year: int) -> str:
    return f"""
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


def test_discovers_nearest_official_cmtr_pdf() -> None:
    page = """
    <table><tr><td>Capital Market (Equities) Trade</td>
    <td><a href="https://nsearchives.nseindia.com/content/circulars/CMTR65587.pdf">
    Download</a></td></tr>
    <tr><td>Futures & Options</td><td><a href="FAOP65588.pdf">Download</a></td></tr>
    </table>
    """

    result = HistoricalSessionEvidenceEngine.discover_cm_circular_url(
        page,
        "https://www.nseindia.com/static/holidays-for-the-calendar-year-2025",
    )

    assert result.endswith("/CMTR65587.pdf")


def test_discovery_fails_closed_when_cm_attachment_is_ambiguous() -> None:
    page = """
    Capital Market (Equities) Trade
    <a href="https://nsearchives.nseindia.com/content/circulars/CMTR1.pdf">A</a>
    <a href="https://nsearchives.nseindia.com/content/circulars/CMTR2.pdf">B</a>
    """

    with pytest.raises(ValueError, match="ambiguous"):
        HistoricalSessionEvidenceEngine.discover_cm_circular_url(
            page,
            "https://www.nseindia.com/static/holidays-for-the-calendar-year-2025",
        )


def test_parses_annual_holiday_table_and_muhurat_session() -> None:
    parsed = HistoricalSessionEvidenceEngine.parse_annual_calendar_text(
        _annual_text(2025),
        2025,
    )

    assert len(parsed.holidays) == 12
    assert parsed.special_sessions == (parsed.holidays[-2],)
    assert parsed.special_sessions[0].isoformat() == "2025-11-01"


def test_acquisition_persists_immutable_normalized_evidence_and_reuses_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year = 2025
    page_url = "https://www.nseindia.com/static/holidays-for-the-calendar-year-2025"
    pdf_url = "https://nsearchives.nseindia.com/content/circulars/CMTR65587.pdf"
    page = (
        "Capital Market (Equities) Trade "
        f'<a href="{pdf_url}">Capital Market circular</a>'
    ).encode()
    session = _Session(
        {
            "https://www.nseindia.com/": _Response(b"home"),
            page_url: _Response(page),
            pdf_url: _Response(b"%PDF-fixture"),
        }
    )
    monkeypatch.setattr(
        HistoricalSessionEvidenceEngine,
        "extract_pdf_text",
        staticmethod(lambda _: _annual_text(year)),
    )
    engine = HistoricalSessionEvidenceEngine(tmp_path / "alpha_data")

    first = engine.acquire_year(year, session=session)
    second = engine.acquire_year(year, session=_Session({}))

    assert first.status is HistoricalEvidenceStatus.COMPLETE
    assert second.status is HistoricalEvidenceStatus.REUSED
    assert first.holiday_count == 12
    assert first.special_session_count == 1
    assert first.normalized_path is not None
    source = OfficialSessionCalendarEngine.load_source(Path(first.normalized_path))
    assert source.covered_years == (2025,)
    assert len(source.holidays) == 12
    assert len(source.special_sessions) == 1


def test_failed_year_remains_explicit_and_report_hash_is_deterministic(
    tmp_path: Path,
) -> None:
    engine = HistoricalSessionEvidenceEngine(tmp_path / "alpha_data")
    session = _Session(
        {
            "https://www.nseindia.com/": _Response(b"home"),
            "https://www.nseindia.com/static/holidays-for-the-calendar-year-2024": (
                _Response(b"not found", status_code=404)
            ),
        }
    )

    first = engine.acquire_range(2024, 2024, session=session)
    second = engine._report(2024, 2024, first.records)

    assert first.failed_count == 1
    assert first.records[0].status is HistoricalEvidenceStatus.FAILED
    assert first.report_sha256 == second.report_sha256
