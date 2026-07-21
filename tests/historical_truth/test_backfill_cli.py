from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from alpha.historical_truth.backfill_cli import backfill_app
from alpha.historical_truth.resumable import HistoricalTruthWarehouse

runner = CliRunner()


def _seed_archive(warehouse: HistoricalTruthWarehouse, trading_date: date) -> None:
    request = warehouse.plan_nse_bhavcopies(trading_date, trading_date)[0]
    destination = warehouse.raw_root / request.relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if trading_date >= date(2024, 7, 8):
        content = (
            "TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,"
            "TtlTradgVol,ISIN\n"
            "ALPHA,EQ,90,110,80,100,1000,INE000000001\n"
        )
    else:
        content = (
            "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,ISIN\n"
            "ALPHA,EQ,90,110,80,100,1000,INE000000001\n"
        )
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(destination.name.removesuffix(".zip"), content)


def test_backfill_cli_runs_fixture_window_and_reports_uncertified_state(
    tmp_path: Path,
) -> None:
    root = tmp_path / "alpha_data"
    warehouse = HistoricalTruthWarehouse(root, retry_backoff_seconds=0)
    warehouse.initialise()
    for trading_date in (date(2024, 7, 5), date(2024, 7, 8)):
        _seed_archive(warehouse, trading_date)

    output_dir = tmp_path / "artifacts"
    result = runner.invoke(
        backfill_app,
        [
            "run",
            "--start",
            "2024-07-05",
            "--end",
            "2024-07-08",
            "--root",
            str(root),
            "--output-dir",
            str(output_dir),
            "--workers",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Run Complete: True" in result.output
    assert "Operationally Complete: True" in result.output
    assert "Certification State: unreconciled_not_certified" in result.output
    assert "Candidate Dates: 2" in result.output
    assert (output_dir / "htr007_backfill.json").exists()
    assert (output_dir / "htr007_backfill.csv").exists()
    assert (output_dir / "htr007_backfill.md").exists()
