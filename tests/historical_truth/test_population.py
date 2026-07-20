from __future__ import annotations

import zipfile
from datetime import date, datetime, UTC
from pathlib import Path

from alpha.historical_truth import (
    ArchiveDataset,
    ArchiveRequest,
    CanonicalPointInTimeWarehouse,
    HistoricalPopulationEngine,
    HistoricalTruthWarehouse,
    PointInTimeSnapshotEngine,
    PopulationStatus,
)


def _request() -> ArchiveRequest:
    return ArchiveRequest(
        exchange="nse",
        dataset=ArchiveDataset.BHAVCOPY,
        trading_date=date(2026, 7, 17),
        source_url="https://example.invalid/cm17JUL2026bhav.csv.zip",
        relative_path=Path("nse/bhavcopy/2026/cm17JUL2026bhav.csv.zip"),
    )


def _write_archive(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,ISIN\n"
        "AAA,EQ,100,110,95,108,1000,INE000A01001\n"
        "BBB,EQ,200,210,190,205,2000,INE000B01002\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("cm17JUL2026bhav.csv", content)


def _engine(tmp_path: Path) -> HistoricalPopulationEngine:
    archive = HistoricalTruthWarehouse(tmp_path / "alpha_data")
    canonical = CanonicalPointInTimeWarehouse(tmp_path / "alpha_data/warehouse/truth.duckdb")
    snapshots = PointInTimeSnapshotEngine(
        canonical,
        tmp_path / "alpha_data/snapshots",
    )
    return HistoricalPopulationEngine(archive, canonical, snapshots)


def test_populate_ingests_and_writes_partial_snapshot(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    request = _request()
    _write_archive(engine.archive.raw_root / request.relative_path)

    records = engine.populate((request,))

    assert records[0].status is PopulationStatus.PARTIAL
    assert records[0].ingested_rows == 2
    assert records[0].validated is True
    assert records[0].snapshot_path is not None


def test_populate_skips_valid_existing_snapshot(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    request = _request()
    _write_archive(engine.archive.raw_root / request.relative_path)

    first = engine.populate((request,))
    second = engine.populate((request,))

    assert first[0].status is PopulationStatus.PARTIAL
    assert second[0].status is PopulationStatus.SKIPPED
    assert second[0].ingested_rows == 2


def test_invalid_zip_is_reported_as_failed(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    request = _request()
    archive_path = engine.archive.raw_root / request.relative_path
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(b"not-a-zip")

    records = engine.populate((request,))

    assert records[0].status is PopulationStatus.FAILED
    assert records[0].downloaded is True
    assert "BadZipFile" in (records[0].error or "")


def test_population_summary_counts_coverage(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    request = _request()
    _write_archive(engine.archive.raw_root / request.relative_path)

    records = engine.populate((request,))
    summary = engine.summarise(records)

    assert summary.total == 1
    assert summary.partial == 1
    assert summary.coverage_ratio == 1.0
    assert summary.ingested_rows == 2


def test_population_exports_are_deterministic(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    request = _request()
    _write_archive(engine.archive.raw_root / request.relative_path)

    records = engine.populate((request,))
    paths = engine.export(records, tmp_path / "artifacts")

    assert [path.name for path in paths] == [
        "historical_population.json",
        "historical_population.csv",
        "historical_population.md",
    ]
    assert "Coverage: 100.00%" in paths[2].read_text(encoding="utf-8")
