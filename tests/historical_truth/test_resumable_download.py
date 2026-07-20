from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import requests

from alpha.historical_truth import (
    ArchiveDataset,
    ArchiveRequest,
    HistoricalTruthWarehouse,
    ManifestStatus,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        chunks: tuple[bytes, ...],
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._chunks = chunks
        self.headers = headers or {}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, *, chunk_size: int) -> Iterator[bytes]:
        del chunk_size
        yield from self._chunks


def _request() -> ArchiveRequest:
    return ArchiveRequest(
        exchange="nse",
        dataset=ArchiveDataset.BHAVCOPY,
        trading_date=date(2026, 7, 17),
        source_url="https://example.test/cm17JUL2026bhav.csv.zip",
        relative_path=Path("nse/bhavcopy/2026/cm17JUL2026bhav.csv.zip"),
    )


def test_fetch_resumes_part_file_with_range_header(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    warehouse = HistoricalTruthWarehouse(
        tmp_path,
        max_attempts=1,
        retry_backoff_seconds=0,
    )
    request = _request()
    part = (tmp_path / "raw" / request.relative_path).with_suffix(".zip.part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"first-")
    observed_headers: dict[str, str] = {}

    def fake_get(*args: object, **kwargs: object) -> FakeResponse:
        del args
        observed_headers.update(kwargs["headers"])
        return FakeResponse(
            status_code=206,
            chunks=(b"second",),
            headers={"Content-Range": "bytes 6-11/12"},
        )

    monkeypatch.setattr(requests, "get", fake_get)

    record = warehouse.fetch(request)

    destination = tmp_path / "raw" / request.relative_path
    assert observed_headers["Range"] == "bytes=6-"
    assert destination.read_bytes() == b"first-second"
    assert record.status is ManifestStatus.DOWNLOADED
    assert not part.exists()


def test_fetch_restarts_when_server_ignores_range(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    warehouse = HistoricalTruthWarehouse(
        tmp_path,
        max_attempts=1,
        retry_backoff_seconds=0,
    )
    request = _request()
    part = (tmp_path / "raw" / request.relative_path).with_suffix(".zip.part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"stale-prefix")

    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            status_code=200,
            chunks=(b"complete-file",),
        ),
    )

    record = warehouse.fetch(request)

    destination = tmp_path / "raw" / request.relative_path
    assert destination.read_bytes() == b"complete-file"
    assert record.status is ManifestStatus.DOWNLOADED


def test_failed_attempt_preserves_partial_file_for_next_run(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    warehouse = HistoricalTruthWarehouse(
        tmp_path,
        max_attempts=1,
        retry_backoff_seconds=0,
    )
    request = _request()

    class BrokenResponse(FakeResponse):
        def iter_content(self, *, chunk_size: int) -> Iterator[bytes]:
            del chunk_size
            yield b"partial"
            raise requests.ConnectionError("connection lost")

    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: BrokenResponse(status_code=200, chunks=()),
    )

    record = warehouse.fetch(request)

    part = (tmp_path / "raw" / request.relative_path).with_suffix(".zip.part")
    assert record.status is ManifestStatus.FAILED
    assert part.read_bytes() == b"partial"


def test_fetch_many_skips_manifest_unavailable_without_network(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    warehouse = HistoricalTruthWarehouse(
        tmp_path,
        max_attempts=1,
        retry_backoff_seconds=0,
    )
    request = _request()
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: FakeResponse(status_code=404, chunks=()),
    )
    first = warehouse.fetch(request)
    assert first.status is ManifestStatus.UNAVAILABLE

    def unexpected_get(*args: object, **kwargs: object) -> FakeResponse:
        raise AssertionError("network should not be called")

    monkeypatch.setattr(requests, "get", unexpected_get)

    records = warehouse.fetch_many((request,))

    assert records == (first,)
