from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Protocol, cast

import requests
from loguru import logger

from alpha.data.models import DownloadResult
from alpha.data.providers.base import MarketDataProvider
from alpha.exceptions import BhavcopyNotFoundError


class HTTPResponse(Protocol):
    """Minimal response surface required by the NSE provider."""

    status_code: int
    content: bytes


class HTTPSession(Protocol):
    """Minimal session surface required by the NSE provider."""

    headers: Any

    def get(self, url: str, **kwargs: Any) -> HTTPResponse:
        """Perform an HTTP GET request."""
        ...


class NSEArchiveBhavcopyProvider(MarketDataProvider):
    """
    NSE historical archive bhavcopy provider.

    This provider intentionally targets the NSE historical archive. It is
    reliable for published historical files but is not responsible for
    same-day/live publication logic. Live/latest providers will be added as
    separate implementations behind the market data provider chain.
    """

    BASE_URL = "https://archives.nseindia.com/content/historical/EQUITIES"
    NSE_HOME_URL = "https://www.nseindia.com"

    _ZIP_SIGNATURES = (
        b"PK\x03\x04",
        b"PK\x05\x06",
        b"PK\x07\x08",
    )

    provider_name = "nse_archive"

    def __init__(
        self,
        *,
        session: HTTPSession | None = None,
        request_timeout_seconds: int = 20,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")

        if session is None:
            resolved_session = cast(HTTPSession, requests.Session())
        else:
            resolved_session = session

        self.session = resolved_session
        self.request_timeout_seconds = request_timeout_seconds

        _install_browser_like_headers(self.session)

    def download_bhavcopy(
        self,
        target_date: date,
        lookback_days: int = 10,
    ) -> DownloadResult:
        """
        Attempt to download the nearest available archived bhavcopy.

        The archive may not publish same-day data immediately. The lookback
        window is retained for backward compatibility with the existing
        ingestion workflow.
        """

        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")

        self._prime_session()

        attempts: list[str] = []
        last_error = "no attempts"

        for offset in range(lookback_days):
            candidate = target_date - timedelta(days=offset)
            url = self._build_url(candidate)

            try:
                response = self.session.get(
                    url,
                    timeout=self.request_timeout_seconds,
                )

                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}"
                    attempts.append(f"{candidate.isoformat()} {last_error}")
                    logger.warning(f"No data at {url}: {last_error}")
                    continue

                if not _is_zip_response(response.content):
                    last_error = "non-zip response"
                    attempts.append(f"{candidate.isoformat()} {last_error}")
                    logger.warning(f"Rejected NSE response at {url}: {last_error}")
                    continue

                logger.info(f"Downloaded NSE bhavcopy: {url}")
                return DownloadResult(
                    trade_date=candidate,
                    source_url=url,
                    content=response.content,
                )

            except Exception as exc:
                last_error = str(exc)
                attempts.append(f"{candidate.isoformat()} {last_error}")
                logger.warning(f"Error downloading {url}: {last_error}")

        attempt_summary = "; ".join(attempts)
        raise BhavcopyNotFoundError(
            f"No NSE bhavcopy found within {lookback_days} day(s). "
            f"Last error: {last_error}. Attempts: {attempt_summary}"
        )

    def _prime_session(self) -> None:
        """
        Prime NSE session cookies.

        NSE endpoints often behave better after visiting the home page first.
        Priming failure is tolerated because archive downloads can still
        succeed in some environments.
        """

        try:
            self.session.get(
                self.NSE_HOME_URL,
                timeout=self.request_timeout_seconds,
            )
        except Exception as exc:
            logger.warning(f"Unable to prime NSE session: {exc}")

    def _build_url(self, trade_date: date) -> str:
        """
        Build the NSE historical archive URL.

        Example
        -------
        https://archives.nseindia.com/content/historical/EQUITIES/2024/JAN/cm15JAN2024bhav.csv.zip
        """

        year = trade_date.strftime("%Y")
        month = trade_date.strftime("%b").upper()
        day = trade_date.strftime("%d")
        filename = f"cm{day}{month}{year}bhav.csv.zip"

        return f"{self.BASE_URL}/{year}/{month}/{filename}"


class NSEBhavcopyProvider(NSEArchiveBhavcopyProvider):
    """
    Backward-compatible NSE provider name.

    Existing application code imports `NSEBhavcopyProvider`. Keeping this
    subclass preserves the stable public API while making the archive-specific
    provider explicit for the new market data framework.
    """


def _install_browser_like_headers(session: HTTPSession) -> None:
    headers = cast(Any, session.headers)
    headers.update(
        {
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Referer": NSEArchiveBhavcopyProvider.NSE_HOME_URL,
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
    )


def _is_zip_response(content: bytes) -> bool:
    return any(
        content.startswith(signature)
        for signature in NSEArchiveBhavcopyProvider._ZIP_SIGNATURES
    )
