from datetime import date

from alpha.data.downloader.bhavcopy import BhavcopyDownloader


class DummyProvider:
    def __init__(self) -> None:
        self.calls = 0

    def download_bhavcopy(self, target_date: date):
        self.calls += 1

        class Result:
            trade_date = target_date
            content = b"dummy"

        return Result()


def test_download_uses_local_cache(tmp_path) -> None:
    """
    Downloader should not hit the provider
    when the archive already exists.
    """

    provider = DummyProvider()

    downloader = BhavcopyDownloader(provider)

    downloader.data_dir = tmp_path

    first = downloader.download(date(2024, 1, 2))
    second = downloader.download(date(2024, 1, 2))

    assert first == second

    assert provider.calls == 1
