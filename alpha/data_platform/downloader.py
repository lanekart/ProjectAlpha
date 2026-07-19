from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from hashlib import sha256

from alpha.data_platform.dataset_registry import DatasetRegistry
from alpha.data_platform.models import (
    DownloadCheckpoint,
    DownloadJob,
    DownloadStatus,
    stable_hash,
)


class DownloadFramework:
    """Pure state machine for future acquisition; it performs no network I/O."""

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry

    def plan_incremental(
        self,
        *,
        dataset_id: str,
        start: date,
        end: date,
        requested_at: datetime,
        partition_days: int = 1,
        incremental_after: date | None = None,
        maximum_retries: int = 3,
    ) -> tuple[DownloadJob, ...]:
        self._registry.get(dataset_id)
        if end < start:
            raise ValueError("ADP download interval is invalid")
        if partition_days < 1:
            raise ValueError("ADP partition size must be positive")
        jobs = []
        cursor = start
        while cursor <= end:
            partition_end = min(end, cursor + timedelta(days=partition_days - 1))
            partition = f"{cursor.isoformat()}_{partition_end.isoformat()}"
            payload = (dataset_id, partition, requested_at, incremental_after)
            jobs.append(
                DownloadJob(
                    job_id="adp-download-" + stable_hash(payload)[:24],
                    dataset_id=dataset_id,
                    partition=partition,
                    requested_at=requested_at,
                    expected_checksum=None,
                    incremental_after=incremental_after,
                    maximum_retries=maximum_retries,
                )
            )
            cursor = partition_end + timedelta(days=1)
        return tuple(jobs)

    @staticmethod
    def initial_checkpoint(job: DownloadJob) -> DownloadCheckpoint:
        return DownloadCheckpoint(
            job_id=job.job_id,
            status=DownloadStatus.PLANNED,
            next_offset=0,
            attempts=0,
            completed_parts=(),
            checksum_verified=False,
            corruption_count=0,
            last_error=None,
        )

    @staticmethod
    def begin(checkpoint: DownloadCheckpoint) -> DownloadCheckpoint:
        if checkpoint.status not in {
            DownloadStatus.PLANNED,
            DownloadStatus.PAUSED,
            DownloadStatus.FAILED,
        }:
            raise ValueError("ADP checkpoint cannot begin from its current state")
        return replace(
            checkpoint,
            status=DownloadStatus.RUNNING,
            attempts=checkpoint.attempts + 1,
            last_error=None,
        )

    @staticmethod
    def record_part(
        checkpoint: DownloadCheckpoint,
        *,
        part_id: str,
        next_offset: int,
    ) -> DownloadCheckpoint:
        if checkpoint.status is not DownloadStatus.RUNNING:
            raise ValueError("ADP parts can only be recorded for running downloads")
        if next_offset < checkpoint.next_offset:
            raise ValueError("ADP download offset cannot move backward")
        return replace(
            checkpoint,
            next_offset=next_offset,
            completed_parts=(*checkpoint.completed_parts, part_id),
        )

    @staticmethod
    def pause(checkpoint: DownloadCheckpoint) -> DownloadCheckpoint:
        if checkpoint.status is not DownloadStatus.RUNNING:
            raise ValueError("ADP can only pause a running download")
        return replace(checkpoint, status=DownloadStatus.PAUSED)

    @staticmethod
    def fail(
        job: DownloadJob,
        checkpoint: DownloadCheckpoint,
        *,
        reason: str,
    ) -> DownloadCheckpoint:
        terminal = checkpoint.attempts > job.maximum_retries
        return replace(
            checkpoint,
            status=DownloadStatus.FAILED if terminal else DownloadStatus.PAUSED,
            last_error=reason,
        )

    @staticmethod
    def verify(
        checkpoint: DownloadCheckpoint,
        *,
        payload: bytes,
        expected_checksum: str,
    ) -> DownloadCheckpoint:
        actual = sha256(payload).hexdigest()
        if actual != expected_checksum:
            return replace(
                checkpoint,
                status=DownloadStatus.CORRUPT,
                checksum_verified=False,
                corruption_count=checkpoint.corruption_count + 1,
                last_error="SHA-256 checksum mismatch.",
            )
        return replace(
            checkpoint,
            status=DownloadStatus.COMPLETE,
            checksum_verified=True,
            last_error=None,
        )

    @staticmethod
    def recover_corruption(checkpoint: DownloadCheckpoint) -> DownloadCheckpoint:
        if checkpoint.status is not DownloadStatus.CORRUPT:
            raise ValueError("ADP corruption recovery requires a corrupt checkpoint")
        return replace(
            checkpoint,
            status=DownloadStatus.PLANNED,
            next_offset=0,
            completed_parts=(),
            checksum_verified=False,
            last_error=None,
        )

    @staticmethod
    def parallel_batches(
        jobs: tuple[DownloadJob, ...], *, maximum_parallelism: int
    ) -> tuple[tuple[DownloadJob, ...], ...]:
        if maximum_parallelism < 1:
            raise ValueError("ADP parallelism must be positive")
        ordered = tuple(sorted(jobs, key=lambda item: item.job_id))
        return tuple(
            ordered[index : index + maximum_parallelism]
            for index in range(0, len(ordered), maximum_parallelism)
        )


__all__ = ["DownloadFramework"]
