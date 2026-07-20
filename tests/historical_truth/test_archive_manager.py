from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from alpha.historical_truth.manager import (
    ArchiveTask,
    HistoricalArchiveManager,
    TaskState,
)
from alpha.historical_truth.models import (
    ArchiveDataset,
    ArchiveRequest,
    ManifestRecord,
    ManifestStatus,
)
from alpha.historical_truth.plugins import NseBhavcopyPlugin
from alpha.historical_truth.registry import DatasetRegistry
from alpha.historical_truth.resumable import HistoricalTruthWarehouse


class StubWarehouse(HistoricalTruthWarehouse):
    def fetch(self, request: ArchiveRequest) -> ManifestRecord:
        status = (
            ManifestStatus.UNAVAILABLE
            if request.trading_date.day == 2
            else ManifestStatus.DOWNLOADED
        )
        return ManifestRecord(
            exchange=request.exchange,
            dataset=request.dataset,
            trading_date=request.trading_date,
            source_url=request.source_url,
            relative_path=str(request.relative_path),
            status=status,
        )


def _request(day: int) -> ArchiveRequest:
    return ArchiveRequest(
        exchange="nse",
        dataset=ArchiveDataset.BHAVCOPY,
        trading_date=date(2026, 7, day),
        source_url=f"https://example.invalid/{day}.zip",
        relative_path=Path("nse") / f"{day}.zip",
    )


def test_manager_runs_tasks_and_persists_checkpoint(tmp_path: Path) -> None:
    manager = HistoricalArchiveManager(StubWarehouse(tmp_path))
    tasks = manager.build_tasks((_request(1), _request(2)))

    completed = manager.run(tasks, workers=2)

    assert [task.state for task in completed] == [
        TaskState.COMPLETE,
        TaskState.UNAVAILABLE,
    ]
    assert manager.checkpoint_path.exists()


def test_completed_checkpoint_tasks_are_not_requeued(tmp_path: Path) -> None:
    manager = HistoricalArchiveManager(StubWarehouse(tmp_path))
    completed = manager.run(manager.build_tasks((_request(1),)), workers=1)

    restored = manager.build_tasks((_request(1),))

    assert restored == completed


def test_manager_rejects_zero_workers(tmp_path: Path) -> None:
    manager = HistoricalArchiveManager(StubWarehouse(tmp_path))

    with pytest.raises(ValueError, match="workers must be at least 1"):
        manager.run(manager.build_tasks((_request(1),)), workers=0)


def test_summary_counts_terminal_states() -> None:
    tasks = (
        ArchiveTask("a", _request(1), TaskState.COMPLETE),
        ArchiveTask("b", _request(2), TaskState.UNAVAILABLE),
        ArchiveTask("c", _request(3), TaskState.FAILED),
    )

    summary = HistoricalArchiveManager.summarise(tasks)

    assert summary.total == 3
    assert summary.complete == 1
    assert summary.unavailable == 1
    assert summary.failed == 1


def test_registry_fails_closed_on_duplicate_plugin(tmp_path: Path) -> None:
    registry = DatasetRegistry()
    plugin = NseBhavcopyPlugin(StubWarehouse(tmp_path))
    registry.register(plugin)

    with pytest.raises(ValueError, match="dataset already registered"):
        registry.register(plugin)
