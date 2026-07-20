from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from typing import Final

import requests

from alpha.historical_truth.models import (
    ArchiveRequest,
    ManifestRecord,
    ManifestStatus,
)
from alpha.historical_truth.service import HistoricalTruthWarehouse as BaseWarehouse

_CHUNK_SIZE: Final[int] = 1024 * 1024


class HistoricalTruthWarehouse(BaseWarehouse):
    """Historical archive store with byte-range and job-level resume support."""

    def __init__(
        self,
        root: Path,
        *,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        super().__init__(root, timeout_seconds=timeout_seconds)
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds

    def fetch(self, request: ArchiveRequest) -> ManifestRecord:
        self.initialise()
        destination = self.raw_root / request.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        existing = self._existing_record(request)
        if destination.exists():
            digest, byte_size = self._hash_file(destination)
            record = ManifestRecord(
                exchange=request.exchange,
                dataset=request.dataset,
                trading_date=request.trading_date,
                source_url=request.source_url,
                relative_path=str(request.relative_path),
                status=ManifestStatus.DOWNLOADED,
                retrieved_at=existing.retrieved_at if existing else None,
                sha256=digest,
                byte_size=byte_size,
            )
            self._append_manifest(record)
            return record

        temporary = destination.with_suffix(destination.suffix + ".part")
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                self._download_attempt(request.source_url, temporary)
                if not temporary.exists() or temporary.stat().st_size == 0:
                    raise ValueError("official archive returned an empty response")
                os.replace(temporary, destination)
                digest, byte_size = self._hash_file(destination)
                record = ManifestRecord(
                    exchange=request.exchange,
                    dataset=request.dataset,
                    trading_date=request.trading_date,
                    source_url=request.source_url,
                    relative_path=str(request.relative_path),
                    status=ManifestStatus.DOWNLOADED,
                    retrieved_at=datetime.now(UTC),
                    sha256=digest,
                    byte_size=byte_size,
                )
                self._append_manifest(record)
                return record
            except _ArchiveUnavailableError as exc:
                temporary.unlink(missing_ok=True)
                record = self._failure_record(
                    request,
                    ManifestStatus.UNAVAILABLE,
                    str(exc),
                )
                self._append_manifest(record)
                return record
            except (OSError, requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < self.max_attempts and self.retry_backoff_seconds:
                    sleep(self.retry_backoff_seconds * attempt)

        record = self._failure_record(
            request,
            ManifestStatus.FAILED,
            f"{type(last_error).__name__}: {last_error}",
        )
        self._append_manifest(record)
        return record

    def fetch_many(
        self,
        requests_: Iterable[ArchiveRequest],
        *,
        retry_failed: bool = True,
    ) -> tuple[ManifestRecord, ...]:
        """Resume a historical job using immutable files and latest manifest state."""

        latest = {
            (record.exchange, record.dataset, record.trading_date): record
            for record in self.records()
        }
        results: list[ManifestRecord] = []
        for request in requests_:
            key = (request.exchange, request.dataset, request.trading_date)
            record = latest.get(key)
            destination = self.raw_root / request.relative_path
            if record is not None and record.status is ManifestStatus.UNAVAILABLE:
                results.append(record)
                continue
            if (
                record is not None
                and record.status is ManifestStatus.FAILED
                and not retry_failed
            ):
                results.append(record)
                continue
            if destination.exists():
                results.append(self.fetch(request))
                continue
            results.append(self.fetch(request))
        return tuple(results)

    def _download_attempt(self, source_url: str, temporary: Path) -> None:
        offset = temporary.stat().st_size if temporary.exists() else 0
        headers = {"User-Agent": "ProjectAlpha-HistoricalTruth/1.0"}
        if offset:
            headers["Range"] = f"bytes={offset}-"

        with requests.get(
            source_url,
            timeout=self.timeout_seconds,
            headers=headers,
            stream=True,
        ) as response:
            if response.status_code == 404:
                raise _ArchiveUnavailableError("official archive returned HTTP 404")
            response.raise_for_status()

            append = offset > 0 and response.status_code == 206
            if append:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {offset}-"):
                    raise ValueError(
                        "archive returned an invalid Content-Range for resume"
                    )
            mode = "ab" if append else "wb"
            with temporary.open(mode) as handle:
                for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                    if chunk:
                        handle.write(chunk)


class _ArchiveUnavailableError(Exception):
    pass
