from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any

from alpha.historical_truth.models import (
    ArchiveDataset,
    ArchiveRequest,
    ManifestRecord,
    ManifestStatus,
)
from alpha.historical_truth.resumable import HistoricalTruthWarehouse


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ArchiveTask:
    task_id: str
    request: ArchiveRequest
    state: TaskState = TaskState.PENDING
    attempts: int = 0
    updated_at: datetime | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DownloadSummary:
    total: int
    complete: int
    failed: int
    unavailable: int
    skipped: int


class HistoricalArchiveManager:
    """Checkpointed, bounded-concurrency coordinator for archive retrieval."""

    def __init__(
        self,
        warehouse: HistoricalTruthWarehouse,
        *,
        checkpoint_path: Path | None = None,
    ) -> None:
        self.warehouse = warehouse
        self.checkpoint_path = checkpoint_path or (
            warehouse.root / "manifests" / "download_checkpoint.json"
        )
        self._lock = Lock()

    def build_tasks(
        self,
        requests: tuple[ArchiveRequest, ...],
    ) -> tuple[ArchiveTask, ...]:
        previous = self._read_checkpoint()
        tasks: list[ArchiveTask] = []
        for request in requests:
            task_id = self.task_id(request)
            restored = previous.get(task_id)
            if restored is None:
                tasks.append(ArchiveTask(task_id=task_id, request=request))
                continue
            restored_state = (
                TaskState.PENDING
                if restored.state is TaskState.RUNNING
                else restored.state
            )
            restored_error = (
                "interrupted while running; reset to pending"
                if restored.state is TaskState.RUNNING
                else restored.error
            )
            tasks.append(
                ArchiveTask(
                    task_id=task_id,
                    request=request,
                    state=restored_state,
                    attempts=restored.attempts,
                    updated_at=restored.updated_at,
                    error=restored_error,
                )
            )
        return tuple(tasks)

    def run(
        self,
        tasks: tuple[ArchiveTask, ...],
        *,
        workers: int = 4,
        retry_failed: bool = True,
    ) -> tuple[ArchiveTask, ...]:
        if workers < 1:
            raise ValueError("workers must be at least 1")

        state = {task.task_id: task for task in tasks}
        runnable = [
            task
            for task in tasks
            if task.state not in {TaskState.COMPLETE, TaskState.UNAVAILABLE}
            and (retry_failed or task.state is not TaskState.FAILED)
        ]
        for task in tasks:
            if task not in runnable and task.state is TaskState.FAILED:
                state[task.task_id] = self._replace(task, TaskState.SKIPPED)

        self._write_checkpoint(tuple(state.values()))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self._execute, task): task.task_id for task in runnable
            }
            for future in as_completed(futures):
                task_id = futures[future]
                try:
                    completed = future.result()
                except Exception as exc:  # defensive worker boundary
                    current = state[task_id]
                    completed = self._replace(
                        current,
                        TaskState.FAILED,
                        attempts=current.attempts + 1,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                with self._lock:
                    state[task_id] = completed
                    self._write_checkpoint(tuple(state.values()))
        return tuple(state[task.task_id] for task in tasks)

    @staticmethod
    def summarise(tasks: tuple[ArchiveTask, ...]) -> DownloadSummary:
        counts = {state: 0 for state in TaskState}
        for task in tasks:
            counts[task.state] += 1
        return DownloadSummary(
            total=len(tasks),
            complete=counts[TaskState.COMPLETE],
            failed=counts[TaskState.FAILED],
            unavailable=counts[TaskState.UNAVAILABLE],
            skipped=counts[TaskState.SKIPPED],
        )

    def _execute(self, task: ArchiveTask) -> ArchiveTask:
        running = self._replace(
            task,
            TaskState.RUNNING,
            attempts=task.attempts + 1,
            error=None,
        )
        return self._from_manifest(running, self.warehouse.fetch(task.request))

    def _read_checkpoint(self) -> dict[str, ArchiveTask]:
        if not self.checkpoint_path.exists():
            return {}
        payload: list[dict[str, Any]] = json.loads(
            self.checkpoint_path.read_text(encoding="utf-8")
        )
        restored: dict[str, ArchiveTask] = {}
        for item in payload:
            request_data = item["request"]
            request = ArchiveRequest(
                exchange=str(request_data["exchange"]),
                dataset=ArchiveDataset(str(request_data["dataset"])),
                trading_date=datetime.fromisoformat(
                    str(request_data["trading_date"])
                ).date(),
                source_url=str(request_data["source_url"]),
                relative_path=Path(str(request_data["relative_path"])),
            )
            task_id = str(item["task_id"])
            restored[task_id] = ArchiveTask(
                task_id=task_id,
                request=request,
                state=TaskState(str(item["state"])),
                attempts=int(item["attempts"]),
                updated_at=(
                    datetime.fromisoformat(str(item["updated_at"]))
                    if item.get("updated_at")
                    else None
                ),
                error=str(item["error"]) if item.get("error") else None,
            )
        return restored

    def _write_checkpoint(self, tasks: tuple[ArchiveTask, ...]) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.checkpoint_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps([self._serialise(task) for task in tasks], indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.checkpoint_path)

    @staticmethod
    def _from_manifest(task: ArchiveTask, record: ManifestRecord) -> ArchiveTask:
        if record.status in {ManifestStatus.DOWNLOADED, ManifestStatus.VALIDATED}:
            return HistoricalArchiveManager._replace(task, TaskState.COMPLETE)
        if record.status is ManifestStatus.UNAVAILABLE:
            return HistoricalArchiveManager._replace(
                task,
                TaskState.UNAVAILABLE,
                error=record.error,
            )
        return HistoricalArchiveManager._replace(
            task,
            TaskState.FAILED,
            error=record.error,
        )

    @staticmethod
    def _replace(
        task: ArchiveTask,
        state: TaskState,
        *,
        attempts: int | None = None,
        error: str | None = None,
    ) -> ArchiveTask:
        return ArchiveTask(
            task_id=task.task_id,
            request=task.request,
            state=state,
            attempts=task.attempts if attempts is None else attempts,
            updated_at=datetime.now(UTC),
            error=error,
        )

    @staticmethod
    def task_id(request: ArchiveRequest) -> str:
        return ":".join(
            (
                request.exchange.lower(),
                request.dataset.value,
                request.trading_date.isoformat(),
            )
        )

    @staticmethod
    def _task_id(request: ArchiveRequest) -> str:
        return HistoricalArchiveManager.task_id(request)

    @staticmethod
    def _serialise(task: ArchiveTask) -> dict[str, object]:
        request = asdict(task.request)
        request["dataset"] = task.request.dataset.value
        request["trading_date"] = task.request.trading_date.isoformat()
        request["relative_path"] = str(task.request.relative_path)
        return {
            "task_id": task.task_id,
            "request": request,
            "state": task.state.value,
            "attempts": task.attempts,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            "error": task.error,
        }
