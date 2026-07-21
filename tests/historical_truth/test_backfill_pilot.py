from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.pilot import (
    DEFAULT_CROSS_ERA_DATES,
    BackfillPilotStatus,
    HistoricalBackfillPilot,
)
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
    member_prefix: str = "",
) -> Path:
    request = warehouse.plan_nse_bhavcopies(trading_date, trading_date)[0]
    destination = warehouse.raw_root / request.relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = (
        _udiff_csv(close=close)
        if trading_date >= date(2024, 7, 8)
        else _legacy_csv(close=close)
    )
    member_name = f"{member_prefix}{destination.name.removesuffix('.zip')}"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, content)
    return destination


def _pilot(tmp_path: Path) -> tuple[HistoricalTruthWarehouse, HistoricalBackfillPilot]:
    root = tmp_path / "alpha_data"
    archive = HistoricalTruthWarehouse(root, retry_backoff_seconds=0)
    archive.initialise()
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    snapshots = PointInTimeSnapshotEngine(canonical, root / "snapshots")
    return archive, HistoricalBackfillPilot(archive, canonical, snapshots)


def test_cross_era_pilot_is_complete_idempotent_and_deterministic(
    tmp_path: Path,
) -> None:
    archive, pilot = _pilot(tmp_path)
    for trading_date in DEFAULT_CROSS_ERA_DATES:
        _seed_archive(archive, trading_date)

    first = pilot.run()
    second = pilot.run()

    assert first.complete
    assert first.schemas_observed == ("legacy", "udiff")
    assert all(record.status is BackfillPilotStatus.COMPLETE for record in first.records)
    assert all(record.snapshot_valid for record in first.records)
    assert all(record.archive_row_count == 1 for record in first.records)
    assert first.as_dict() == second.as_dict()
    assert first.report_sha256 == second.report_sha256

    first_paths = pilot.export(first, tmp_path / "artifacts")
    first_content = {
        path.name: path.read_text(encoding="utf-8") for path in first_paths
    }
    second_paths = pilot.export(second, tmp_path / "artifacts")
    second_content = {
        path.name: path.read_text(encoding="utf-8") for path in second_paths
    }
    assert first_content == second_content
    payload = json.loads(first_content["htr007_backfill_pilot.json"])
    assert payload["complete"] is True
    assert payload["live_downloads_executed_by_ci"] is False
    assert payload["report_sha256"] == first.report_sha256


def test_cross_era_pilot_blocks_immutable_archive_checksum_drift(
    tmp_path: Path,
) -> None:
    archive, pilot = _pilot(tmp_path)
    trading_date = date(2016, 1, 4)
    destination = _seed_archive(archive, trading_date, close=100)

    assert pilot.run((trading_date,)).complete
    destination.unlink()
    _seed_archive(archive, trading_date, close=101)

    report = pilot.run((trading_date,))

    assert not report.complete
    assert report.records[0].status is BackfillPilotStatus.FAILED
    assert report.records[0].checksum_drift
    assert report.records[0].error == "immutable archive checksum drift detected"


def test_cross_era_pilot_rejects_nested_archive_members(tmp_path: Path) -> None:
    archive, pilot = _pilot(tmp_path)
    trading_date = date(2026, 1, 2)
    _seed_archive(archive, trading_date, member_prefix="nested/")

    report = pilot.run((trading_date,))

    assert not report.complete
    assert report.records[0].status is BackfillPilotStatus.FAILED
    assert report.records[0].snapshot_relative_path is None
    assert "safe top-level file" in (report.records[0].error or "")
