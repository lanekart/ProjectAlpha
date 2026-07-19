from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from alpha.historical_truth_acquisition.models import (
    AcquisitionCheckpoint,
    CheckpointStatus,
    json_value,
    stable_hash,
)


class CheckpointStore:
    """Atomic, restart-safe acquisition progress with bounded retry metadata."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def records(self) -> tuple[AcquisitionCheckpoint, ...]:
        with self._lock:
            if not self.path.exists():
                return ()
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("HTA checkpoint store must contain a JSON list")
            return tuple(_checkpoint(item) for item in payload)

    def get_or_plan(
        self,
        *,
        dataset_id: str,
        source_key: str,
        observed_at: datetime,
    ) -> AcquisitionCheckpoint:
        checkpoint_id = "hta-checkpoint-" + stable_hash((dataset_id, source_key))[:24]
        for item in self.records():
            if item.checkpoint_id == checkpoint_id:
                return item
        checkpoint = AcquisitionCheckpoint(
            checkpoint_id=checkpoint_id,
            dataset_id=dataset_id,
            source_key=source_key,
            status=CheckpointStatus.PLANNED,
            attempts=0,
            completed_bytes=0,
            checksum=None,
            last_error=None,
            next_retry_seconds=0,
            updated_at=observed_at,
        )
        self._upsert(checkpoint)
        return checkpoint

    def begin(
        self, checkpoint: AcquisitionCheckpoint, *, observed_at: datetime
    ) -> AcquisitionCheckpoint:
        if checkpoint.status is CheckpointStatus.COMPLETE:
            return checkpoint
        updated = replace(
            checkpoint,
            status=CheckpointStatus.RUNNING,
            attempts=checkpoint.attempts + 1,
            last_error=None,
            next_retry_seconds=0,
            updated_at=observed_at,
        )
        self._upsert(updated)
        return updated

    def verified(
        self,
        checkpoint: AcquisitionCheckpoint,
        *,
        checksum: str,
        completed_bytes: int,
        observed_at: datetime,
    ) -> AcquisitionCheckpoint:
        updated = replace(
            checkpoint,
            status=CheckpointStatus.VERIFIED,
            checksum=checksum,
            completed_bytes=completed_bytes,
            last_error=None,
            updated_at=observed_at,
        )
        self._upsert(updated)
        return updated

    def progress(
        self,
        checkpoint: AcquisitionCheckpoint,
        *,
        completed_bytes: int,
        observed_at: datetime,
    ) -> AcquisitionCheckpoint:
        if checkpoint.status is not CheckpointStatus.RUNNING:
            raise ValueError("HTA progress requires a running checkpoint")
        if completed_bytes < checkpoint.completed_bytes:
            raise ValueError("HTA acquisition offset cannot move backward")
        updated = replace(
            checkpoint,
            completed_bytes=completed_bytes,
            updated_at=observed_at,
        )
        self._upsert(updated)
        return updated

    def complete(
        self, checkpoint: AcquisitionCheckpoint, *, observed_at: datetime
    ) -> AcquisitionCheckpoint:
        if checkpoint.status not in {
            CheckpointStatus.VERIFIED,
            CheckpointStatus.COMPLETE,
        }:
            raise ValueError("HTA checkpoint must be verified before completion")
        updated = replace(
            checkpoint,
            status=CheckpointStatus.COMPLETE,
            next_retry_seconds=0,
            updated_at=observed_at,
        )
        self._upsert(updated)
        return updated

    def fail(
        self,
        checkpoint: AcquisitionCheckpoint,
        *,
        reason: str,
        observed_at: datetime,
        corrupt: bool = False,
        base_backoff_seconds: int = 2,
        maximum_backoff_seconds: int = 300,
    ) -> AcquisitionCheckpoint:
        if base_backoff_seconds < 1 or maximum_backoff_seconds < 1:
            raise ValueError("HTA retry backoff must be positive")
        exponent = max(0, checkpoint.attempts - 1)
        delay = min(maximum_backoff_seconds, base_backoff_seconds * (2**exponent))
        updated = replace(
            checkpoint,
            status=(CheckpointStatus.CORRUPT if corrupt else CheckpointStatus.FAILED),
            last_error=reason,
            next_retry_seconds=delay,
            updated_at=observed_at,
        )
        self._upsert(updated)
        return updated

    def reset_corruption(
        self, checkpoint: AcquisitionCheckpoint, *, observed_at: datetime
    ) -> AcquisitionCheckpoint:
        if checkpoint.status is not CheckpointStatus.CORRUPT:
            raise ValueError("only corrupt HTA checkpoints may be reset")
        updated = replace(
            checkpoint,
            status=CheckpointStatus.PLANNED,
            completed_bytes=0,
            checksum=None,
            last_error=None,
            updated_at=observed_at,
        )
        self._upsert(updated)
        return updated

    def _upsert(self, checkpoint: AcquisitionCheckpoint) -> None:
        with self._lock:
            indexed = {item.checkpoint_id: item for item in self.records()}
            indexed[checkpoint.checkpoint_id] = checkpoint
            payload = [json_value(indexed[key]) for key in sorted(indexed)]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                temporary = Path(handle.name)
            os.replace(temporary, self.path)


def _checkpoint(value: object) -> AcquisitionCheckpoint:
    if not isinstance(value, dict):
        raise ValueError("HTA checkpoint record is invalid")
    return AcquisitionCheckpoint(
        checkpoint_id=str(value["checkpoint_id"]),
        dataset_id=str(value["dataset_id"]),
        source_key=str(value["source_key"]),
        status=CheckpointStatus(str(value["status"])),
        attempts=int(str(value["attempts"])),
        completed_bytes=int(str(value["completed_bytes"])),
        checksum=(None if value.get("checksum") is None else str(value["checksum"])),
        last_error=(
            None if value.get("last_error") is None else str(value["last_error"])
        ),
        next_retry_seconds=int(str(value["next_retry_seconds"])),
        updated_at=datetime.fromisoformat(str(value["updated_at"])).astimezone(UTC),
    )


__all__ = ["CheckpointStore"]
