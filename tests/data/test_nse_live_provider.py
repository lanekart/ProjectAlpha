from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest

from alpha.data.providers.nse_live import NSEUdiffBhavcopyProvider
from alpha.exceptions import BhavcopyNotFoundError


@dataclass(slots=True)
class FakeResponse:
    status_code: int
    content: bytes


@dataclass(slots=True)
class FakeSession:
    archive_responses: list[FakeResponse]
    home_status_code: int = 200
    home_raises: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    urls: list[str] = field(default_factory=list)
    primed: bool = False

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.urls.append(url)
        if url == NSEUdiffBhavcopyProvider.NSE_HOME_URL:
            self.primed = True
            if self.home_raises:
                raise RuntimeError("home unavailable")
            return FakeResponse(status_code=self.home_status_code, content=b"html")
        return self.archive_responses.pop(0)


def test_udiff_provider_builds_expected_filename() -> None:
    provider = NSEUdiffBhavcopyProvider(
        session=FakeSession(archive_responses=[]),
    )

    assert (
        provider._build_filename(date(2026, 7, 6))
        == "BhavCopy_NSE_CM_0_0_0_20260706_F_0000.csv.zip"
    )


def test_udiff_provider_installs_browser_headers() -> None:
    session = FakeSession(archive_responses=[])

    NSEUdiffBhavcopyProvider(session=session)

    assert session.headers["Referer"] == NSEUdiffBhavcopyProvider.NSE_HOME_URL
    assert "User-Agent" in session.headers


def test_udiff_provider_downloads_valid_zip_response() -> None:
    session = FakeSession(
        archive_responses=[
            FakeResponse(status_code=200, content=b"PK\x03\x04archive"),
        ]
    )
    provider = NSEUdiffBhavcopyProvider(session=session)

    result = provider.download_bhavcopy(date(2026, 7, 6))

    assert session.primed
    assert result.trade_date == date(2026, 7, 6)
    assert result.source_url.endswith("BhavCopy_NSE_CM_0_0_0_20260706_F_0000.csv.zip")
    assert result.content == b"PK\x03\x04archive"


def test_udiff_provider_tries_secondary_url_before_lookback() -> None:
    session = FakeSession(
        archive_responses=[
            FakeResponse(status_code=404, content=b"not found"),
            FakeResponse(status_code=200, content=b"PK\x03\x04archive"),
        ]
    )
    provider = NSEUdiffBhavcopyProvider(session=session, lookback_days=1)

    result = provider.download_bhavcopy(date(2026, 7, 6))

    assert result.trade_date == date(2026, 7, 6)
    assert session.urls[1].startswith(NSEUdiffBhavcopyProvider.PRIMARY_BASE_URL)
    assert session.urls[2].startswith(NSEUdiffBhavcopyProvider.SECONDARY_BASE_URL)


def test_udiff_provider_looks_back_after_all_urls_fail() -> None:
    session = FakeSession(
        archive_responses=[
            FakeResponse(status_code=404, content=b"not found"),
            FakeResponse(status_code=404, content=b"not found"),
            FakeResponse(status_code=200, content=b"PK\x03\x04archive"),
        ]
    )
    provider = NSEUdiffBhavcopyProvider(session=session, lookback_days=2)

    result = provider.download_bhavcopy(date(2026, 7, 6))

    assert result.trade_date == date(2026, 7, 5)


def test_udiff_provider_rejects_non_zip_success_response() -> None:
    session = FakeSession(
        archive_responses=[
            FakeResponse(status_code=200, content=b"<html>blocked</html>"),
        ]
    )
    provider = NSEUdiffBhavcopyProvider(session=session, lookback_days=1)

    with pytest.raises(BhavcopyNotFoundError, match="No NSE UDiFF bhavcopy found"):
        provider.download_bhavcopy(date(2026, 7, 6))


def test_udiff_provider_tolerates_home_prime_failure() -> None:
    session = FakeSession(
        archive_responses=[
            FakeResponse(status_code=200, content=b"PK\x03\x04archive"),
        ],
        home_raises=True,
    )
    provider = NSEUdiffBhavcopyProvider(session=session, lookback_days=1)

    result = provider.download_bhavcopy(date(2026, 7, 6))

    assert session.primed
    assert result.trade_date == date(2026, 7, 6)


def test_udiff_provider_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="lookback_days"):
        NSEUdiffBhavcopyProvider(
            session=FakeSession(archive_responses=[]),
            lookback_days=0,
        )

    with pytest.raises(ValueError, match="request_timeout_seconds"):
        NSEUdiffBhavcopyProvider(
            session=FakeSession(archive_responses=[]),
            request_timeout_seconds=0,
        )
