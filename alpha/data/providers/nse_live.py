from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol, cast

import requests
from loguru import logger

from alpha.data.models import DownloadResult
from alpha.data.providers.base import MarketDataProvider
from alpha.exceptions import BhavcopyNotFoundError


class HTTPResponse(Protocol):
    """Minimal HTTP response surface needed by NSE live provider."""

    status_code: int
    content: bytes


class HTTPSession(Protocol):
    """Minimal HTTP session surface needed by NSE live provider."""

    headers: MutableMapping[str, str]

    def get(self, url: str, **kwargs: Any) -> HTTPResponse:
        """Execute an HTTP GET request."""


@dataclass(frozen=True, slots=True)
class NSELiveProviderAttempt:
    """Immutable record of a live provider download attempt."""

    trade_date: date
    url: str
    status: str


@dataclass(slots=True)
class NSEUdiffBhavcopyProvider(MarketDataProvider):
    """Download NSE post-2024 UDiFF common bhavcopy ZIP files.

    NSE discontinued the legacy CM bhavcopy CSV reports from July 08, 2024.
    This provider targets the UDiFF Common Bhavcopy Final ZIP format and is
    intentionally separate from the legacy archive provider so ingestion can be
    migrated safely in G26.3.
    """

    session: HTTPSession | None = None
    lookback_days: int = 5
    request_timeout_seconds: int = 20
    attempts: tuple[NSELiveProviderAttempt, ...] = field(
        init=False,
        default_factory=tuple,
    )

    NSE_HOME_URL = "https://www.nseindia.com"
    PRIMARY_BASE_URL = "https://archives.nseindia.com/content/cm"
    SECONDARY_BASE_URL = "https://nsearchives.nseindia.com/content/cm"
    ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

    def __post_init__(self) -> None:
        if self.lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")

        resolved_session: HTTPSession
        if self.session is None:
            resolved_session = cast(HTTPSession, requests.Session())
        else:
            resolved_session = self.session

        _install_default_headers(resolved_session)
        object.__setattr__(self, "session", resolved_session)

    def download_bhavcopy(self, target_date: date) -> DownloadResult:
        """Download UDiFF bhavcopy ZIP for target date or nearest lookback date."""

        session = _require_session(self.session)
        self._prime_session(session)
        attempts: list[NSELiveProviderAttempt] = []
        last_error = "None"

        for candidate in _lookback_dates(target_date, self.lookback_days):
            for url in self._candidate_urls(candidate):
                try:
                    response = session.get(
                        url,
                        timeout=self.request_timeout_seconds,
                    )
                    status = _response_status(response)
                    attempts.append(
                        NSELiveProviderAttempt(
                            trade_date=candidate,
                            url=url,
                            status=status,
                        )
                    )

                    if response.status_code != 200:
                        logger.warning(f"No UDiFF bhavcopy at {url}: {status}")
                        last_error = status
                        continue

                    if not _is_zip_response(response.content):
                        logger.warning(f"Rejected non-ZIP UDiFF response at {url}")
                        last_error = "non-ZIP response"
                        continue

                    object.__setattr__(self, "attempts", tuple(attempts))
                    logger.info(f"Downloaded NSE UDiFF bhavcopy: {url}")
                    return DownloadResult(
                        trade_date=candidate,
                        source_url=url,
                        content=response.content,
                    )
                except Exception as exc:
                    status = str(exc)
                    attempts.append(
                        NSELiveProviderAttempt(
                            trade_date=candidate,
                            url=url,
                            status=status,
                        )
                    )
                    last_error = status
                    logger.warning(f"Error downloading UDiFF bhavcopy {url}: {exc}")

        object.__setattr__(self, "attempts", tuple(attempts))
        raise BhavcopyNotFoundError(
            "No NSE UDiFF bhavcopy found within "
            f"{self.lookback_days} day(s). "
            f"Last error: {last_error}. "
            f"Attempts: {_format_attempts(attempts)}"
        )

    def _candidate_urls(self, trade_date: date) -> tuple[str, ...]:
        filename = self._build_filename(trade_date)
        return (
            f"{self.PRIMARY_BASE_URL}/{filename}",
            f"{self.SECONDARY_BASE_URL}/{filename}",
        )

    def _build_filename(self, trade_date: date) -> str:
        compact_date = trade_date.strftime("%Y%m%d")
        return f"BhavCopy_NSE_CM_0_0_0_{compact_date}_F_0000.csv.zip"

    def _prime_session(self, session: HTTPSession) -> None:
        try:
            session.get(
                self.NSE_HOME_URL,
                timeout=self.request_timeout_seconds,
            )
        except Exception as exc:
            logger.warning(f"Unable to prime NSE live session: {exc}")


def _require_session(session: HTTPSession | None) -> HTTPSession:
    if session is None:
        raise RuntimeError("NSE live provider session has not been initialized")
    return session


def _install_default_headers(session: HTTPSession) -> None:
    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Referer": NSEUdiffBhavcopyProvider.NSE_HOME_URL,
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        }
    )


def _lookback_dates(target_date: date, lookback_days: int) -> Iterable[date]:
    for offset in range(lookback_days):
        yield target_date - timedelta(days=offset)


def _response_status(response: HTTPResponse) -> str:
    return f"HTTP {response.status_code}"


def _is_zip_response(content: bytes) -> bool:
    return any(
        content.startswith(signature)
        for signature in NSEUdiffBhavcopyProvider.ZIP_SIGNATURES
    )


def _format_attempts(attempts: list[NSELiveProviderAttempt]) -> str:
    if len(attempts) == 0:
        return "none"
    return "; ".join(
        f"{attempt.trade_date.isoformat()} {attempt.status}" for attempt in attempts
    )


__all__ = [
    "NSELiveProviderAttempt",
    "NSEUdiffBhavcopyProvider",
]
