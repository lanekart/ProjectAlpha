from __future__ import annotations

from datetime import date

from alpha.data.downloader.bhavcopy import BhavcopyDownloader
from alpha.data.models import DownloadResult
from alpha.data.providers.chain import MarketDataProviderChain


class DummyProvider:
    def __init__(self) -> None:
        self.calls = 0

    def download_bhavcopy(self, target_date: date) -> DownloadResult:
        self.calls += 1
        return DownloadResult(
            trade_date=target_date,
            source_url="dummy://bhavcopy",
            content=b"dummy",
        )


class ResolvingProvider:
    def __init__(self, resolved_date: date) -> None:
        self.resolved_date = resolved_date

    def download_bhavcopy(self, target_date: date) -> DownloadResult:
        return DownloadResult(
            trade_date=self.resolved_date,
            source_url="dummy://resolved-bhavcopy",
            content=b"dummy",
        )


def test_download_uses_local_cache(tmp_path) -> None:
    """
    Downloader should not hit the provider when the archive already exists.
    """

    provider = DummyProvider()

    downloader = BhavcopyDownloader(provider, data_dir=tmp_path)

    first = downloader.download(date(2024, 1, 2))
    second = downloader.download(date(2024, 1, 2))

    assert first == second
    assert provider.calls == 1


def test_default_downloader_uses_market_data_provider_chain(tmp_path) -> None:
    downloader = BhavcopyDownloader(data_dir=tmp_path)

    assert isinstance(downloader.provider, MarketDataProviderChain)


def test_download_caches_using_resolved_trade_date(tmp_path) -> None:
    provider = ResolvingProvider(resolved_date=date(2024, 1, 12))
    downloader = BhavcopyDownloader(provider, data_dir=tmp_path)

    path = downloader.download(date(2024, 1, 15))

    assert path == tmp_path / "bhavcopy_2024-01-12.zip"
    assert path.read_bytes() == b"dummy"
