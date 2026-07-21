from __future__ import annotations

import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

from alpha.historical_truth.backfill import (
    PLANNING_BASIS,
    BackfillCertificationState,
    BackfillRecordStatus,
    HistoricalBackfillEngine,
)
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.models import ManifestRecord, ManifestStatus
from alpha.historical_truth.resumable import HistoricalTruthWarehouse
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine


def _legacy_csv(*, close: int = 100) -> str:
    return (
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,ISIN\n"
        f"ALPHA,EQ,90,110,80,{close},1000,INE000000001\n"
    )


def _udiff_csv(*, close: int = 100) -> str:
    return (
        "TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,ISIN\n"
        f"ALPHA,EQ,90,110,80,{close},1000,INE000000001\n"
    )


def _seed_archive(
    warehouse: HistoricalTruthWarehouse,
    trading_date: date,
    *,
    close: int = 100,
) -> Path:
    request = warehouse.plan_nse_bhavcopies(trading_date, trading_date)[0]
    destination = warehouse.raw_root / request.relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = (
        _udiff_csv(close=close)
        if trading_date >= date(2024, 7, 8)
        else _legacy_csv(close=close)
    )
    member_name = destination.name.removesuffix(".zip")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, content)
    return destination


def _engine(
    tmp_path: Path,
    *,
    archive: HistoricalTruthWarehouse | None = None,
) -> tuple[HistoricalTruthWarehouse, HistoricalBackfillEngine]:
    root = tmp_path / "alpha_data"
    warehouse = archive or HistoricalTruthWarehouse(
        root,
        retry_backoff_seconds=0,
    )
    warehouse.initialise()
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    snapshots = PointInTimeSnapshotEngine(canonical, root / "snapshots")
    return warehouse, HistoricalBackfillEngine(warehouse, canonical, snapshots)


def test_backfill_is_idempotent_deterministic_and_explicitly_uncertified(
    tmp_path: Path,
) -> None:
    archive, engine = _engine(tmp_path)
    start = date(2024, 7, 5)
    end = date(2024, 7, 8)
    for trading_date in (start, end):
        _seed_archive(archive, trading_date)

    first = engine.run(start, end, workers=2)
    second = engine.run(start, end, workers=2)

    assert first.operationally_complete
    assert first.run_complete
    assert first.complete_count == 2
    assert first.unavailable_count == 0
    assert first.failed_count == 0
    assert first.planning_basis == PLANNING_BASIS
    assert (
        first.certification_state
        is BackfillCertificationState.UNRECONCILED_NOT_CERTIFIED
    )
    assert all(record.snapshot_valid for record in first.records)
    assert all(record.population_status == "available" for record in first.records)
    assert first.as_dict() == second.as_dict()
    assert first.report_sha256 == second.report_sha256

    first_paths = engine.export(first, tmp_path / "artifacts")
    first_content = {
        path.name: path.read_text(encoding="utf-8") for path in first_paths
    }
    second_paths = engine.export(second, tmp_path / "artifacts")
    second_content = {
        path.name: path.read_text(encoding="utf-8") for path in second_paths
    }
    assert first_content == second_content
    payload = json.loads(first_content["htr007_backfill.json"])
    assert payload["certification_state"] == "unreconciled_not_certified"


def test_backfill_resumes_after_a_partial_population_run(tmp_path: Path) -> None:
    archive, engine = _engine(tmp_path)
    start = date(2024, 7, 5)
    end = date(2024, 7, 8)
    for trading_date in (start, end):
        _seed_archive(archive, trading_date)

    partial = engine.run(start, end, workers=2, max_records=1)
    resumed = engine.run(start, end, workers=2)
    repeated = engine.run(start, end, workers=2)

    assert not partial.run_complete
    assert partial.deferred_count == 1
    assert resumed.run_complete
    assert resumed.operationally_complete
    assert resumed.complete_count == 2
    assert resumed.as_dict() == repeated.as_dict()


def test_backfill_blocks_immutable_raw_archive_drift(tmp_path: Path) -> None:
    archive, engine = _engine(tmp_path)
    trading_date = date(2016, 1, 4)
    destination = _seed_archive(archive, trading_date, close=100)

    assert engine.run(trading_date, trading_date).operationally_complete
    destination.unlink()
    _seed_archive(archive, trading_date, close=101)

    report = engine.run(trading_date, trading_date)

    assert not report.operationally_complete
    assert report.failed_count == 1
    assert report.records[0].status is BackfillRecordStatus.FAILED
    assert report.records[0].error == "immutable archive checksum drift detected"


class _UnavailableWarehouse(HistoricalTruthWarehouse):
    def fetch(self, request):  # type: ignore[no-untyped-def]
        return ManifestRecord(
            exchange=request.exchange,
            dataset=request.dataset,
            trading_date=request.trading_date,
            source_url=request.source_url,
            relative_path=str(request.relative_path),
            status=ManifestStatus.UNAVAILABLE,
            retrieved_at=datetime.now(UTC),
            error="official archive returned HTTP 404",
        )


def test_backfill_records_unavailable_candidate_dates_explicitly(
    tmp_path: Path,
) -> None:
    root = tmp_path / "alpha_data"
    archive = _UnavailableWarehouse(root, retry_backoff_seconds=0)
    _, engine = _engine(tmp_path, archive=archive)
    trading_date = date(2024, 1, 1)

    report = engine.run(trading_date, trading_date)

    assert report.run_complete
    assert report.operationally_complete
    assert report.unavailable_count == 1
    assert report.records[0].status is BackfillRecordStatus.UNAVAILABLE
    assert report.records[0].error == "official archive returned HTTP 404"


class _FailingWarehouse(HistoricalTruthWarehouse):
    def __init__(self, root: Path) -> None:
        super().__init__(root, retry_backoff_seconds=0)
        self.fetch_calls = 0

    def fetch(self, request):  # type: ignore[no-untyped-def]
        self.fetch_calls += 1
        return ManifestRecord(
            exchange=request.exchange,
            dataset=request.dataset,
            trading_date=request.trading_date,
            source_url=request.source_url,
            relative_path=str(request.relative_path),
            status=ManifestStatus.FAILED,
            retrieved_at=datetime.now(UTC),
            error="synthetic failure",
        )


def test_no_retry_failed_uses_restored_failed_checkpoint_state(
    tmp_path: Path,
) -> None:
    root = tmp_path / "alpha_data"
    archive = _FailingWarehouse(root)
    _, engine = _engine(tmp_path, archive=archive)
    trading_date = date(2024, 1, 2)

    first = engine.run(trading_date, trading_date, retry_failed=True)
    second = engine.run(trading_date, trading_date, retry_failed=False)

    assert first.failed_count == 1
    assert archive.fetch_calls == 1
    assert second.skipped_count == 1
    assert second.records[0].status is BackfillRecordStatus.SKIPPED
