from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from alpha.historical_truth_acquisition.checkpoints import CheckpointStore
from alpha.historical_truth_acquisition.models import CheckpointStatus


@dataclass(frozen=True, slots=True)
class DownloadPartition:
    dataset_id: str
    partition_id: str
    start: date | None
    end: date | None
    filename: str


@dataclass(frozen=True, slots=True)
class DownloadChunk:
    payload: bytes
    complete: bool
    expected_checksum: str | None = None

    def __post_init__(self) -> None:
        if self.complete and self.expected_checksum is None:
            raise ValueError("a complete HTA download requires an expected checksum")
        if self.expected_checksum is not None and len(self.expected_checksum) != 64:
            raise ValueError("HTA expected checksum must be SHA-256")


class ChunkedOfficialConnector(Protocol):
    """Licensed provider adapter capable of range/offset continuation."""

    def read(self, partition: DownloadPartition, offset: int) -> DownloadChunk: ...


class ResumableDownloadCoordinator:
    """Provider-independent offset resume, retry, checksum, and parallelism."""

    def __init__(
        self,
        *,
        checkpoints: CheckpointStore,
        destination: Path,
        maximum_retries: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        if maximum_retries < 0:
            raise ValueError("HTA maximum retries cannot be negative")
        self.checkpoints = checkpoints
        self.destination = destination
        self.maximum_retries = maximum_retries
        self.sleeper = sleeper
        self.clock = clock

    def acquire(
        self,
        partition: DownloadPartition,
        connector: ChunkedOfficialConnector,
    ) -> Path:
        filename = Path(partition.filename).name
        if not filename or filename != partition.filename:
            raise ValueError("HTA download filename must be a safe basename")
        target = self.destination / partition.dataset_id / filename
        partial = target.with_suffix(target.suffix + ".part")
        source_key = f"{partition.dataset_id}|{partition.partition_id}"
        checkpoint = self.checkpoints.get_or_plan(
            dataset_id=partition.dataset_id,
            source_key=source_key,
            observed_at=self.clock(),
        )
        if checkpoint.status is CheckpointStatus.COMPLETE:
            if not target.exists() or checkpoint.checksum is None:
                raise RuntimeError("completed HTA download bytes are unavailable")
            if sha256(target.read_bytes()).hexdigest() != checkpoint.checksum:
                raise RuntimeError("completed HTA download checksum mismatch")
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        for retry in range(self.maximum_retries + 1):
            checkpoint = self.checkpoints.begin(checkpoint, observed_at=self.clock())
            try:
                wrong_offset = (
                    partial.exists()
                    and partial.stat().st_size != checkpoint.completed_bytes
                )
                if wrong_offset:
                    raise RuntimeError(
                        "partial HTA download offset does not match checkpoint"
                    )
                if not partial.exists() and checkpoint.completed_bytes:
                    raise RuntimeError("partial HTA download bytes are missing")
                while True:
                    chunk = connector.read(partition, checkpoint.completed_bytes)
                    if not chunk.payload and not chunk.complete:
                        raise RuntimeError("HTA connector returned no progress")
                    with partial.open("ab") as handle:
                        handle.write(chunk.payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                    checkpoint = self.checkpoints.progress(
                        checkpoint,
                        completed_bytes=checkpoint.completed_bytes + len(chunk.payload),
                        observed_at=self.clock(),
                    )
                    if not chunk.complete:
                        continue
                    assert chunk.expected_checksum is not None
                    actual = sha256(partial.read_bytes()).hexdigest()
                    if actual != chunk.expected_checksum:
                        checkpoint = self.checkpoints.fail(
                            checkpoint,
                            reason="SHA-256 checksum mismatch",
                            observed_at=self.clock(),
                            corrupt=True,
                        )
                        if retry >= self.maximum_retries:
                            raise RuntimeError("HTA download checksum mismatch")
                        partial.unlink(missing_ok=True)
                        delay = checkpoint.next_retry_seconds
                        checkpoint = self.checkpoints.reset_corruption(
                            checkpoint, observed_at=self.clock()
                        )
                        self.sleeper(float(delay))
                        break
                    checkpoint = self.checkpoints.verified(
                        checkpoint,
                        checksum=actual,
                        completed_bytes=partial.stat().st_size,
                        observed_at=self.clock(),
                    )
                    os.replace(partial, target)
                    self.checkpoints.complete(checkpoint, observed_at=self.clock())
                    return target
            except Exception as error:
                if checkpoint.status is CheckpointStatus.CORRUPT:
                    raise
                checkpoint = self.checkpoints.fail(
                    checkpoint,
                    reason=str(error),
                    observed_at=self.clock(),
                )
                if retry >= self.maximum_retries:
                    raise
                self.sleeper(float(checkpoint.next_retry_seconds))
        raise RuntimeError("HTA download retry loop terminated unexpectedly")

    def acquire_many(
        self,
        partitions: tuple[DownloadPartition, ...],
        connectors: Mapping[str, ChunkedOfficialConnector],
        *,
        parallelism: int,
    ) -> tuple[Path, ...]:
        if parallelism < 1:
            raise ValueError("HTA parallelism must be positive")

        def execute(partition: DownloadPartition) -> Path:
            try:
                connector = connectors[partition.dataset_id]
            except KeyError as error:
                raise KeyError(
                    f"no HTA connector for {partition.dataset_id}"
                ) from error
            return self.acquire(partition, connector)

        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            paths = tuple(executor.map(execute, partitions))
        return tuple(sorted(paths))


__all__ = [
    "ChunkedOfficialConnector",
    "DownloadChunk",
    "DownloadPartition",
    "ResumableDownloadCoordinator",
]
