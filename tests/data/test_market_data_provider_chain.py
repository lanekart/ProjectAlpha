from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from alpha.data.models import DownloadResult
from alpha.data.providers.base import MarketDataProvider
from alpha.data.providers.chain import MarketDataProviderChain
from alpha.exceptions import BhavcopyNotFoundError, DownloadError


@dataclass(slots=True)
class SuccessfulProvider(MarketDataProvider):
    provider_name: str = "success"
    calls: int = 0

    def download_bhavcopy(self, target_date: date) -> DownloadResult:
        self.calls += 1
        return DownloadResult(
            trade_date=target_date,
            source_url=f"memory://{self.provider_name}",
            content=b"PK\x03\x04archive",
        )


@dataclass(slots=True)
class MissingProvider(MarketDataProvider):
    provider_name: str = "missing"
    calls: int = 0

    def download_bhavcopy(self, target_date: date) -> DownloadResult:
        self.calls += 1
        raise BhavcopyNotFoundError(f"{self.provider_name} unavailable")


def test_provider_chain_rejects_empty_provider_list() -> None:
    with pytest.raises(ValueError, match="requires at least one provider"):
        MarketDataProviderChain(providers=())


def test_provider_chain_uses_first_successful_provider() -> None:
    first = SuccessfulProvider(provider_name="first")
    second = SuccessfulProvider(provider_name="second")
    chain = MarketDataProviderChain(providers=(first, second))

    result = chain.download_bhavcopy(date(2024, 1, 15))

    assert result.trade_date == date(2024, 1, 15)
    assert result.source_url == "memory://first"
    assert first.calls == 1
    assert second.calls == 0


def test_provider_chain_falls_back_after_download_error() -> None:
    missing = MissingProvider(provider_name="archive")
    success = SuccessfulProvider(provider_name="fallback")
    chain = MarketDataProviderChain(providers=(missing, success))

    result = chain.download_bhavcopy(date(2024, 1, 15))

    assert result.source_url == "memory://fallback"
    assert missing.calls == 1
    assert success.calls == 1


def test_provider_chain_reports_all_failures() -> None:
    first = MissingProvider(provider_name="archive")
    second = MissingProvider(provider_name="live")
    chain = MarketDataProviderChain(providers=(first, second))

    with pytest.raises(DownloadError) as exc_info:
        chain.download_bhavcopy(date(2024, 1, 15))

    message = str(exc_info.value)

    assert "No market data provider could download bhavcopy" in message
    assert "archive unavailable" in message
    assert "live unavailable" in message


def test_provider_chain_exposes_provider_metadata() -> None:
    chain = MarketDataProviderChain(
        providers=(
            MissingProvider(provider_name="archive"),
            SuccessfulProvider(provider_name="live"),
        )
    )

    assert chain.provider_count == 2
    assert chain.provider_names == ("archive", "live")
