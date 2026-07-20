from __future__ import annotations

from datetime import date
from pathlib import Path

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse


def _write_bhavcopy(path: Path) -> None:
    path.write_text(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,ISIN\n"
        "ABC,EQ,100,110,95,108,1000,INE000A01001\n"
        "XYZ,EQ,200,205,190,195,2500,INE000B01002\n",
        encoding="utf-8",
    )


def test_initialise_creates_canonical_tables(tmp_path: Path) -> None:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "market.duckdb")

    warehouse.initialise()

    assert (tmp_path / "market.duckdb").exists()


def test_ingest_and_snapshot_are_point_in_time(tmp_path: Path) -> None:
    csv_path = tmp_path / "bhav.csv"
    _write_bhavcopy(csv_path)
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "market.duckdb")

    count = warehouse.ingest_bhavcopy_csv(
        csv_path,
        trading_date=date(2026, 7, 17),
        source_sha256="abc123",
    )
    snapshot = warehouse.snapshot(date(2026, 7, 17))

    assert count == 2
    assert snapshot.symbol_count == 2
    assert snapshot.total_volume == 3500
    assert [candle.symbol for candle in snapshot.candles] == ["ABC", "XYZ"]
    assert snapshot.candles[0].isin == "INE000A01001"


def test_reingestion_is_idempotent(tmp_path: Path) -> None:
    csv_path = tmp_path / "bhav.csv"
    _write_bhavcopy(csv_path)
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "market.duckdb")

    warehouse.ingest_bhavcopy_csv(csv_path, trading_date=date(2026, 7, 17))
    warehouse.ingest_bhavcopy_csv(csv_path, trading_date=date(2026, 7, 17))

    assert warehouse.snapshot(date(2026, 7, 17)).symbol_count == 2


def test_completeness_reports_missing_weekdays(tmp_path: Path) -> None:
    csv_path = tmp_path / "bhav.csv"
    _write_bhavcopy(csv_path)
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "market.duckdb")
    warehouse.ingest_bhavcopy_csv(csv_path, trading_date=date(2026, 7, 17))

    report = warehouse.completeness(date(2026, 7, 17), date(2026, 7, 20))

    assert report.observed_dates == (date(2026, 7, 17),)
    assert report.missing_weekdays == (date(2026, 7, 20),)
    assert report.coverage_ratio == 0.5


def test_missing_columns_fail_closed(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("SYMBOL,SERIES\nABC,EQ\n", encoding="utf-8")
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "market.duckdb")

    try:
        warehouse.ingest_bhavcopy_csv(csv_path, trading_date=date(2026, 7, 17))
    except ValueError as exc:
        assert "missing required columns" in str(exc)
    else:
        raise AssertionError("missing schema should fail closed")
