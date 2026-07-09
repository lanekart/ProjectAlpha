from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from alpha.data.downloader.bhavcopy import BhavcopyDownloader, DownloadedArchive
from alpha.data.providers.base import BhavcopyDownloadResult


@dataclass
class FakeProvider:
    trade_date: date
    content: bytes = b"zip-bytes"

    def download_bhavcopy(self, target_date: date) -> BhavcopyDownloadResult:
        return BhavcopyDownloadResult(
            trade_date=self.trade_date,
            content=self.content,
            source_url=f"https://example.test/{self.trade_date.isoformat()}.zip",
        )


def test_downloader_writes_provider_result_using_effective_trade_date(
    tmp_path: Path,
) -> None:
    downloader = BhavcopyDownloader(
        provider=FakeProvider(trade_date=date(2026, 7, 7)),  # type: ignore[arg-type]
        data_dir=tmp_path,
    )

    archive = downloader.download_archive(date(2026, 7, 8))

    assert isinstance(archive, DownloadedArchive)
    assert archive.requested_date == date(2026, 7, 8)
    assert archive.trade_date == date(2026, 7, 7)
    assert archive.path == tmp_path / "bhavcopy_2026-07-07.zip"
    assert archive.path.read_bytes() == b"zip-bytes"
    assert archive.cached is False


def test_downloader_returns_cached_requested_archive(tmp_path: Path) -> None:
    cached_path = tmp_path / "bhavcopy_2026-07-08.zip"
    cached_path.write_bytes(b"cached")

    downloader = BhavcopyDownloader(
        provider=FakeProvider(trade_date=date(2026, 7, 7)),  # type: ignore[arg-type]
        data_dir=tmp_path,
    )

    archive = downloader.download_archive(date(2026, 7, 8))

    assert archive.requested_date == date(2026, 7, 8)
    assert archive.trade_date == date(2026, 7, 8)
    assert archive.path == cached_path
    assert archive.cached is True
    assert archive.path.read_bytes() == b"cached"


def test_downloader_returns_cached_effective_archive(tmp_path: Path) -> None:
    cached_path = tmp_path / "bhavcopy_2026-07-07.zip"
    cached_path.write_bytes(b"cached-effective")

    downloader = BhavcopyDownloader(
        provider=FakeProvider(trade_date=date(2026, 7, 7)),  # type: ignore[arg-type]
        data_dir=tmp_path,
    )

    archive = downloader.download_archive(date(2026, 7, 8))

    assert archive.requested_date == date(2026, 7, 8)
    assert archive.trade_date == date(2026, 7, 7)
    assert archive.path == cached_path
    assert archive.cached is True
    assert archive.path.read_bytes() == b"cached-effective"


def test_download_keeps_backward_compatible_path_return(tmp_path: Path) -> None:
    downloader = BhavcopyDownloader(
        provider=FakeProvider(trade_date=date(2026, 7, 7)),  # type: ignore[arg-type]
        data_dir=tmp_path,
    )

    path = downloader.download(date(2026, 7, 8))

    assert path == tmp_path / "bhavcopy_2026-07-07.zip"
    assert path.read_bytes() == b"zip-bytes"
