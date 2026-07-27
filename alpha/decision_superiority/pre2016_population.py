"""Governed raw Historical Truth population for the frozen DSI-010 era."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.population import HistoricalPopulationEngine
from alpha.historical_truth.resumable import HistoricalTruthWarehouse
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine

_MINIMUM_FREE_BYTES = 8 * 1024**3


class Pre2016PopulationError(RuntimeError):
    """Raised when governed pre-2016 raw population cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class Pre2016PopulationResult:
    """Summary of one governed raw Historical Truth population pass."""

    requested_start: date
    requested_end: date
    planned_requests: int
    coverage_ratio: float
    candle_snapshots: int
    evidence_complete_snapshots: int
    evidence_incomplete_snapshots: int
    failed: int
    unavailable: int
    skipped: int
    ingested_rows: int
    available_rows: int
    free_bytes_before: int
    database: Path
    snapshot_root: Path
    artifact_paths: tuple[Path, ...]


def populate_pre2016_historical_truth(
    *,
    root: Path,
    output_dir: Path,
    start: date,
    end: date,
    retry_failed: bool = True,
) -> Pre2016PopulationResult:
    """Download and populate raw candles into the governed Historical Truth store."""

    if end < start:
        raise Pre2016PopulationError("PRE2016_POPULATION_RANGE_INVERTED")
    if end >= date(2016, 1, 1):
        raise Pre2016PopulationError("PRE2016_POPULATION_OVERLAPS_2016")

    root = root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(root).free
    if free_bytes < _MINIMUM_FREE_BYTES:
        raise Pre2016PopulationError(
            "PRE2016_POPULATION_INSUFFICIENT_DISK_SPACE:"
            f"required={_MINIMUM_FREE_BYTES}:available={free_bytes}"
        )

    archive = HistoricalTruthWarehouse(root)
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    snapshots = PointInTimeSnapshotEngine(canonical, root / "snapshots")
    engine = HistoricalPopulationEngine(archive, canonical, snapshots)
    requests = archive.plan_nse_bhavcopies(start, end)
    records = engine.populate(requests, retry_failed=retry_failed)
    summary = engine.summarise(records)
    paths = tuple(engine.export(records, output_dir))

    return Pre2016PopulationResult(
        requested_start=start,
        requested_end=end,
        planned_requests=len(requests),
        coverage_ratio=summary.coverage_ratio,
        candle_snapshots=summary.candle_snapshots,
        evidence_complete_snapshots=summary.evidence_complete_snapshots,
        evidence_incomplete_snapshots=summary.evidence_incomplete_snapshots,
        failed=summary.failed,
        unavailable=summary.unavailable,
        skipped=summary.skipped,
        ingested_rows=summary.ingested_rows,
        available_rows=summary.available_rows,
        free_bytes_before=free_bytes,
        database=root / "warehouse" / "historical_truth.duckdb",
        snapshot_root=root / "snapshots",
        artifact_paths=paths,
    )


__all__ = [
    "Pre2016PopulationError",
    "Pre2016PopulationResult",
    "populate_pre2016_historical_truth",
]
