from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority import pre2016_calendar_recovery
from alpha.decision_superiority.pre2016_calendar_recovery import (
    recover_pre2011_official_calendar_sources,
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


def _registry(root: Path, *, year: int, url: str, raw: bytes) -> Path:
    path = root / "candidate_registry.json"
    path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "year": year,
                        "source_id": f"NSE_CMTR_TEST_{year}",
                        "source_url": url,
                        "segment_scope": "CAPITAL_MARKET",
                        "expected_sha256": hashlib.sha256(raw).hexdigest(),
                        "expected_download_number": "28337",
                        "expected_circular_date": "December 12, 2014",
                        "expected_subject": (
                            "trading holidays for the calendar year 2015"
                        ),
                        "requires_muhurat_statement": True,
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_2015_capital_market_calendar_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://nsearchives.nseindia.com/content/circulars/CMTR28337.pdf"
    raw = b"%PDF-1.7 governed 2015 fixture"
    monkeypatch.setattr(
        pre2016_calendar_recovery,
        "_extract_pdf_text",
        lambda _: (
            "National Stock Exchange of India Limited\n"
            "Department: Capital Market Segment\n"
            "Trading holidays for the calendar year 2015\n"
            "Download Ref No: NSE/CMTR/28337\n"
            "Date: December 12, 2014\n"
            "January 26, 2015 Republic Day\n"
            "Muhurat Trading will be conducted"
        ),
    )

    result = recover_pre2011_official_calendar_sources(
        candidate_registry=_registry(tmp_path, year=2015, url=url, raw=raw),
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

    assert result.fully_recovered_years == (2015,)
    assert result.unrecovered_years == ()
    assert result.attempts[0].circular_date_match is True
    assert result.attempts[0].content_validation_passed is True


def test_2016_calendar_candidate_remains_outside_dsi010_period(tmp_path: Path) -> None:
    url = "https://nsearchives.nseindia.com/content/circulars/CMTR31297.pdf"
    raw = b"%PDF-1.7 outside-period fixture"

    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2011_CALENDAR_CANDIDATE_YEAR_INVALID",
    ):
        recover_pre2011_official_calendar_sources(
            candidate_registry=_registry(tmp_path, year=2016, url=url, raw=raw),
            output=tmp_path / "output",
            session=FakeSession({}),
        )


def test_pre2016_recovery_command_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])
    assert result.exit_code == 0
    assert "decision-superiority-pre2016-calendar-source-recovery" in result.stdout
    assert "decision-superiority-pre2011-calendar-source-recovery" in result.stdout
