from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority import pre2016_calendar_recovery
from alpha.decision_superiority.pre2016_calendar_recovery import (
    export_pre2011_calendar_recovery,
    recover_pre2011_official_calendar_sources,
)
from alpha.decision_superiority.pre2016_calendar_sources import (
    build_reviewed_official_calendar_source,
    validate_hash_bound_official_calendar_source,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
    Pre2016ExternalValidationError,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        content: bytes,
        content_type: str,
        url: str,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers: Mapping[str, str] = {"Content-Type": content_type}
        self.url = url


class FakeSession:
    def __init__(self, responses: Mapping[str, FakeResponse]) -> None:
        self.responses = responses

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        del headers, timeout
        return self.responses[url]


def test_valid_capital_market_pdf_is_recovered_and_exported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://nsearchives.nseindia.com/content/circulars/cm2005.pdf"
    raw = b"%PDF-1.4 governed fixture"
    registry = _write_registry(
        tmp_path,
        candidates=(
            _candidate(
                year=2005,
                source_id="NSE_CM_2005_CALENDAR",
                source_url=url,
                segment_scope="CAPITAL_MARKET",
                expected_sha256=hashlib.sha256(raw).hexdigest(),
                requires_muhurat_statement=True,
            ),
        ),
    )
    monkeypatch.setattr(
        pre2016_calendar_recovery,
        "_extract_pdf_text",
        lambda _: (
            "National Stock Exchange of India Limited\n"
            "Capital Market Segment\n"
            "Sub: Trading holidays for the calendar year 2005\n"
            "2005-01-26 Republic Day\n"
            "Muhurat Trading will be conducted"
        ),
    )

    result = recover_pre2011_official_calendar_sources(
        candidate_registry=registry,
        output=tmp_path / "output",
        session=FakeSession(
            {
                url: FakeResponse(
                    status_code=200,
                    content=raw,
                    content_type="application/pdf",
                    url=url,
                )
            }
        ),
    )

    assert result.fully_recovered_years == (2005,)
    assert result.partially_recovered_years == ()
    attempt = result.attempts[0]
    assert attempt.content_validation_passed is True
    assert attempt.recovery_state == "VERIFIED_OFFICIAL_EVIDENCE"
    assert attempt.response_sha256 == hashlib.sha256(raw).hexdigest()
    assert attempt.document_path is not None
    assert attempt.extracted_text_path is not None

    paths = export_pre2011_calendar_recovery(result, tmp_path / "output")
    assert len(paths) == 5
    summary = json.loads(paths[2].read_text(encoding="utf-8"))
    assert summary["fully_recovered_years"] == [2005]
    assert summary["calendar_certification_permitted"] is False
    assert summary["production_influence"] is False


def test_valid_official_archive_html_is_recovered(tmp_path: Path) -> None:
    url = "https://nsearchives.nseindia.com/content/circulars/cmtr5633.htm"
    raw = b"""<!doctype html><html><body>
    National Stock Exchange of India Limited
    Capital Market Operations
    Sub: Trading holidays for the calendar year 2005
    Download No. NSE/CMTR/5633
    Date: December 07, 2004
    Wednesday, January 26, 2005 Republic Day
    Muhurat Trading will be conducted
    </body></html>"""
    registry = _write_registry(
        tmp_path,
        candidates=(
            _candidate(
                year=2005,
                source_id="NSE_CM_2005_CALENDAR_HTML",
                source_url=url,
                segment_scope="CAPITAL_MARKET",
                expected_sha256=hashlib.sha256(raw).hexdigest(),
                requires_muhurat_statement=True,
            ),
        ),
    )

    result = recover_pre2011_official_calendar_sources(
        candidate_registry=registry,
        output=tmp_path / "output",
        session=FakeSession(
            {
                url: FakeResponse(
                    status_code=200,
                    content=raw,
                    content_type="text/html; charset=utf-8",
                    url=url,
                )
            }
        ),
    )

    attempt = result.attempts[0]
    assert result.fully_recovered_years == (2005,)
    assert attempt.document_format == "HTML"
    assert attempt.pdf_signature_valid is False
    assert attempt.text_extraction_status == "EXTRACTED"
    assert attempt.content_validation_passed is True
    assert attempt.recovery_state == "VERIFIED_OFFICIAL_EVIDENCE"
    assert attempt.document_path is not None
    assert attempt.document_path.endswith(".htm")


def test_html_200_response_is_rejected_without_pdf_extraction(tmp_path: Path) -> None:
    url = "https://www.nseindia.com/content/circulars/cm2006.pdf"
    registry = _write_registry(
        tmp_path,
        candidates=(
            _candidate(
                year=2006,
                source_id="NSE_CM_2006_CALENDAR",
                source_url=url,
                segment_scope="CAPITAL_MARKET",
            ),
        ),
    )

    result = recover_pre2011_official_calendar_sources(
        candidate_registry=registry,
        output=tmp_path / "output",
        session=FakeSession(
            {
                url: FakeResponse(
                    status_code=200,
                    content=b"<html>access denied</html>",
                    content_type="text/html",
                    url=url,
                )
            }
        ),
    )

    attempt = result.attempts[0]
    assert attempt.pdf_signature_valid is False
    assert attempt.text_extraction_status == "NOT_ATTEMPTED"
    assert attempt.recovery_state == "OFFICIAL_SOURCE_CONTENT_INVALID"
    assert attempt.error == "HTML_RESPONSE_REJECTED"
    assert result.unrecovered_years == (2006,)


def test_valid_fo_document_remains_cross_segment_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://nsearchives.nseindia.com/content/circulars/faop2010.pdf"
    raw = b"%PDF-1.7 governed fixture"
    registry = _write_registry(
        tmp_path,
        candidates=(
            _candidate(
                year=2010,
                source_id="NSE_FAOP_2010_CALENDAR",
                source_url=url,
                segment_scope="FUTURES_AND_OPTIONS",
            ),
        ),
    )
    monkeypatch.setattr(
        pre2016_calendar_recovery,
        "_extract_pdf_text",
        lambda _: (
            "National Stock Exchange of India Limited\n"
            "Futures and Options Segment\n"
            "Sub: Trading holidays for the calendar year 2010\n"
            "05-Nov-2010 Laxmi Pujan"
        ),
    )

    result = recover_pre2011_official_calendar_sources(
        candidate_registry=registry,
        output=tmp_path / "output",
        session=FakeSession(
            {
                url: FakeResponse(
                    status_code=200,
                    content=raw,
                    content_type="application/pdf",
                    url=url,
                )
            }
        ),
    )

    assert result.fully_recovered_years == ()
    assert result.partially_recovered_years == (2010,)
    assert result.attempts[0].recovery_state == ("PARTIALLY_VERIFIED_OFFICIAL_EVIDENCE")


def test_duplicate_documents_are_detected_by_sha256(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_url = "https://nsearchives.nseindia.com/content/circulars/cm2007a.pdf"
    second_url = "https://nsearchives.nseindia.com/content/circulars/cm2007b.pdf"
    raw = b"%PDF-1.4 duplicate fixture"
    registry = _write_registry(
        tmp_path,
        candidates=(
            _candidate(
                year=2007,
                source_id="NSE_CM_2007_A",
                source_url=first_url,
                segment_scope="CAPITAL_MARKET",
            ),
            _candidate(
                year=2007,
                source_id="NSE_CM_2007_B",
                source_url=second_url,
                segment_scope="CAPITAL_MARKET",
            ),
        ),
    )
    monkeypatch.setattr(
        pre2016_calendar_recovery,
        "_extract_pdf_text",
        lambda _: (
            "National Stock Exchange of India Limited\n"
            "Capital Market Segment\n"
            "Sub: Trading holidays for the calendar year 2007\n"
            "2007-01-26 Republic Day"
        ),
    )
    response = lambda url: FakeResponse(  # noqa: E731
        status_code=200,
        content=raw,
        content_type="application/pdf",
        url=url,
    )

    result = recover_pre2011_official_calendar_sources(
        candidate_registry=registry,
        output=tmp_path / "output",
        session=FakeSession(
            {
                first_url: response(first_url),
                second_url: response(second_url),
            }
        ),
    )

    assert result.attempts[0].recovery_state == "VERIFIED_OFFICIAL_EVIDENCE"
    assert result.attempts[1].recovery_state == "DUPLICATE_DOCUMENT"
    assert result.attempts[1].duplicate_of_source_id == "NSE_CM_2007_A"


def test_hash_bound_source_rejects_tamper_and_cross_segment_cm_use(
    tmp_path: Path,
) -> None:
    source_document = tmp_path / "faop.pdf"
    source_document.write_bytes(b"%PDF-1.4 source")
    extracted_text = tmp_path / "extracted.txt"
    extracted_text.write_text("official source\n", encoding="utf-8")
    validation = tmp_path / "validation.txt"
    validation.write_text("OFFICIAL_CIRCULAR_CONTENT_VALID=true\n", encoding="utf-8")
    review_csv = tmp_path / "reviewed_calendar.csv"
    _write_review(
        review_csv,
        rows=(
            {
                "trading_date": "2010-11-05",
                "classification": "SPECIAL_SESSION",
                "description": "Muhurat Trading",
                "review_state": "VERIFIED_OFFICIAL_EVIDENCE",
                "segment_scope": "FUTURES_AND_OPTIONS",
                "source_id": "NSE_FAOP_2010_CALENDAR",
            },
        ),
    )
    output = tmp_path / "nse_2010_official_calendar.json"

    build_reviewed_official_calendar_source(
        review_csv=review_csv,
        source_document=source_document,
        source_url="https://nsearchives.nseindia.com/content/circulars/faop2010.pdf",
        source_id="NSE_FAOP_2010_CALENDAR",
        covered_years=(2010,),
        output=output,
        segment_scope="FUTURES_AND_OPTIONS",
        extracted_text=extracted_text,
        content_validation=validation,
    )

    payload = validate_hash_bound_official_calendar_source(output)
    assert payload["content_validation_passed"] is True
    assert payload["manual_review_completed"] is True
    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_CAPITAL_MARKET_SEGMENT_SCOPE_INSUFFICIENT",
    ):
        validate_hash_bound_official_calendar_source(
            output,
            require_capital_market_scope=True,
        )

    review_csv.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_CALENDAR_REVIEW_HASH_MISMATCH",
    ):
        validate_hash_bound_official_calendar_source(output)


def test_pre2011_recovery_command_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])
    assert result.exit_code == 0
    assert "decision-superiority-pre2011-calendar-source-recovery" in result.stdout


def _write_registry(
    root: Path,
    *,
    candidates: tuple[dict[str, object], ...],
) -> Path:
    path = root / "candidate_registry.json"
    path.write_text(
        json.dumps({"candidates": candidates}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _candidate(
    *,
    year: int,
    source_id: str,
    source_url: str,
    segment_scope: str,
    expected_sha256: str | None = None,
    requires_muhurat_statement: bool = False,
) -> dict[str, object]:
    return {
        "year": year,
        "source_id": source_id,
        "source_url": source_url,
        "segment_scope": segment_scope,
        "expected_sha256": expected_sha256,
        "expected_download_number": None,
        "expected_circular_date": None,
        "expected_subject": "trading holidays",
        "requires_muhurat_statement": requires_muhurat_statement,
    }


def _write_review(
    path: Path,
    *,
    rows: tuple[dict[str, str], ...],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "trading_date",
                "classification",
                "description",
                "review_state",
                "segment_scope",
                "source_id",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)
