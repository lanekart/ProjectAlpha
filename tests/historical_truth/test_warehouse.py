from __future__ import annotations

from datetime import date
from pathlib import Path

from alpha.historical_truth import HistoricalTruthWarehouse


def test_plan_nse_bhavcopies_skips_weekends(tmp_path: Path) -> None:
    warehouse = HistoricalTruthWarehouse(tmp_path)

    requests = warehouse.plan_nse_bhavcopies(
        date(2026, 7, 17),
        date(2026, 7, 20),
    )

    assert [item.trading_date for item in requests] == [
        date(2026, 7, 17),
        date(2026, 7, 20),
    ]
    assert requests[0].source_url.endswith("cm17JUL2026bhav.csv.zip")


def test_initialise_creates_immutable_layout(tmp_path: Path) -> None:
    warehouse = HistoricalTruthWarehouse(tmp_path)

    warehouse.initialise()

    assert (tmp_path / "raw" / "nse").is_dir()
    assert (tmp_path / "raw" / "bse").is_dir()
    assert (tmp_path / "manifests").is_dir()
    assert (tmp_path / "snapshots").is_dir()


def test_validate_bhavcopy_detects_impossible_ohlc(tmp_path: Path) -> None:
    csv_path = tmp_path / "bhav.csv"
    csv_path.write_text(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY\n"
        "ABC,EQ,100,99,95,98,1000\n",
        encoding="utf-8",
    )
    warehouse = HistoricalTruthWarehouse(tmp_path / "warehouse")

    issues = warehouse.validate_bhavcopy_csv(csv_path)

    assert [issue.code for issue in issues] == ["IMPOSSIBLE_OHLC"]


def test_status_exports_are_deterministic_when_empty(tmp_path: Path) -> None:
    warehouse = HistoricalTruthWarehouse(tmp_path / "warehouse")

    paths = warehouse.export_status(tmp_path / "artifacts")

    assert [path.name for path in paths] == [
        "historical_truth_status.json",
        "historical_truth_status.csv",
        "historical_truth_status.md",
    ]
    assert paths[0].read_text(encoding="utf-8") == "[]"
