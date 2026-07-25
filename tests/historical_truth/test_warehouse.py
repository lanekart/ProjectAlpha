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
    assert requests[0].source_url.endswith(
        "BhavCopy_NSE_CM_0_0_0_20260717_F_0000.csv.zip"
    )
    assert "/content/cm/" in requests[0].source_url


def test_plan_nse_bhavcopies_uses_legacy_format_before_udiff(tmp_path: Path) -> None:
    warehouse = HistoricalTruthWarehouse(tmp_path)

    request = warehouse.plan_nse_bhavcopies(
        date(2024, 7, 5),
        date(2024, 7, 5),
    )[0]

    assert request.source_url.endswith("cm05JUL2024bhav.csv.zip")
    assert "/content/historical/EQUITIES/2024/JUL/" in request.source_url


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
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY\nABC,EQ,100,99,95,98,1000\n",
        encoding="utf-8",
    )
    warehouse = HistoricalTruthWarehouse(tmp_path / "warehouse")

    issues = warehouse.validate_bhavcopy_csv(csv_path)

    assert [issue.code for issue in issues] == ["IMPOSSIBLE_OHLC"]


def test_validate_udiff_bhavcopy_schema(tmp_path: Path) -> None:
    csv_path = tmp_path / "udiff.csv"
    csv_path.write_text(
        "TckrSymb,SctySrs,ISIN,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol\n"
        "ABC,EQ,INE000A01001,100,110,95,108,1000\n",
        encoding="utf-8",
    )
    warehouse = HistoricalTruthWarehouse(tmp_path / "warehouse")

    assert warehouse.validate_bhavcopy_csv(csv_path) == ()


def test_status_exports_are_deterministic_when_empty(tmp_path: Path) -> None:
    warehouse = HistoricalTruthWarehouse(tmp_path / "warehouse")

    paths = warehouse.export_status(tmp_path / "artifacts")

    assert [path.name for path in paths] == [
        "historical_truth_status.json",
        "historical_truth_status.csv",
        "historical_truth_status.md",
    ]
    assert paths[0].read_text(encoding="utf-8") == "[]"


def test_validate_t0_close_range_exception_is_warning(tmp_path: Path) -> None:
    csv_path = tmp_path / "bhav.csv"
    csv_path.write_text(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY\n"
        "IDEA,T0,11.27,11.27,11.27,10.98,1000\n",
        encoding="utf-8",
    )
    warehouse = HistoricalTruthWarehouse(tmp_path / "warehouse")

    issues = warehouse.validate_bhavcopy_csv(csv_path)

    assert [issue.code for issue in issues] == ["T0_CLOSE_RANGE_EXCEPTION"]
    assert issues[0].severity.value == "warning"
    assert "symbol=IDEA" in issues[0].message
    assert "violations=low>close" in issues[0].message
