from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest

from alpha.data.providers.nse import NSEArchiveBhavcopyProvider, NSEBhavcopyProvider
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

    def get(self, url: str, timeout: int) -> FakeResponse:
        assert timeout == 20
        self.urls.append(url)

        if url == NSEArchiveBhavcopyProvider.NSE_HOME_URL:
            self.primed = True
            if self.home_raises:
                raise RuntimeError("home unavailable")
            return FakeResponse(status_code=self.home_status_code, content=b"html")

        return self.archive_responses.pop(0)


def test_provider_downloads_valid_zip_response() -> None:
    session = FakeSession(
        archive_responses=[
            FakeResponse(status_code=200, content=b"PK\x03\x04archive"),
        ]
    )
    provider = NSEBhavcopyProvider(session=session)

    result = provider.download_bhavcopy(date(2024, 1, 15))

    assert session.primed
    assert result.trade_date == date(2024, 1, 15)
    assert result.source_url.endswith("cm15JAN2024bhav.csv.zip")
    assert result.content == b"PK\x03\x04archive"


def test_provider_installs_browser_like_headers() -> None:
    session = FakeSession(
        archive_responses=[
            FakeResponse(status_code=200, content=b"PK\x03\x04archive"),
        ]
    )

    NSEBhavcopyProvider(session=session)

    assert "User-Agent" in session.headers
    assert session.headers["Referer"] == NSEArchiveBhavcopyProvider.NSE_HOME_URL


def test_provider_looks_back_until_valid_zip_response() -> None:
    session = FakeSession(
        archive_responses=[
            FakeResponse(status_code=404, content=b"not found"),
            FakeResponse(status_code=200, content=b"PK\x03\x04archive"),
        ]
    )
    provider = NSEBhavcopyProvider(session=session)

    result = provider.download_bhavcopy(date(2024, 1, 15), lookback_days=2)

    assert result.trade_date == date(2024, 1, 14)
    assert session.urls[0] == NSEArchiveBhavcopyProvider.NSE_HOME_URL
    assert session.urls[1].endswith("cm15JAN2024bhav.csv.zip")
    assert session.urls[2].endswith("cm14JAN2024bhav.csv.zip")


def test_provider_rejects_non_zip_success_response() -> None:
    session = FakeSession(
        archive_responses=[
            FakeResponse(status_code=200, content=b"<html>blocked</html>"),
        ]
    )
    provider = NSEBhavcopyProvider(session=session)

    with pytest.raises(BhavcopyNotFoundError, match="No NSE bhavcopy found"):
        provider.download_bhavcopy(date(2024, 1, 15), lookback_days=1)


def test_provider_raises_after_all_archive_attempts_fail() -> None:
    session = FakeSession(
        archive_responses=[
            FakeResponse(status_code=404, content=b"not found"),
            FakeResponse(status_code=404, content=b"not found"),
        ]
    )
    provider = NSEBhavcopyProvider(session=session)

    with pytest.raises(BhavcopyNotFoundError) as exc_info:
        provider.download_bhavcopy(date(2024, 1, 15), lookback_days=2)

    message = str(exc_info.value)

    assert "No NSE bhavcopy found within 2 day(s)" in message
    assert "2024-01-15 HTTP 404" in message
    assert "2024-01-14 HTTP 404" in message


def test_provider_tolerates_home_prime_failure() -> None:
    session = FakeSession(
        archive_responses=[
            FakeResponse(status_code=200, content=b"PK\x03\x04archive"),
        ],
        home_raises=True,
    )
    provider = NSEBhavcopyProvider(session=session)

    result = provider.download_bhavcopy(date(2024, 1, 15), lookback_days=1)

    assert result.trade_date == date(2024, 1, 15)
    assert session.primed


def test_provider_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="request_timeout_seconds"):
        NSEBhavcopyProvider(
            session=FakeSession(archive_responses=[]),
            request_timeout_seconds=0,
        )


def test_archive_provider_is_explicit_public_provider() -> None:
    assert issubclass(NSEBhavcopyProvider, NSEArchiveBhavcopyProvider)
