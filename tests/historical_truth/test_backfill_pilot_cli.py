from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from alpha.historical_truth.cli import historical_truth_app
from alpha.historical_truth.resumable import HistoricalTruthWarehouse


def _seed_legacy_archive(root: Path, trading_date: date) -> None:
    warehouse = HistoricalTruthWarehouse(root, retry_backoff_seconds=0)
    warehouse.initialise()
    request = warehouse.plan_nse_bhavcopies(trading_date, trading_date)[0]
    destination = warehouse.raw_root / request.relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    csv_content = (
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,ISIN\n"
        "ALPHA,EQ,90,110,80,100,1000,INE000000001\n"
    )
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(destination.name.removesuffix(".zip"), csv_content)


def test_pilot_cli_exports_deterministic_artifacts_without_live_download(
    tmp_path: Path,
) -> None:
    root = tmp_path / "alpha_data"
    output = tmp_path / "artifacts"
    trading_date = date(2016, 1, 4)
    _seed_legacy_archive(root, trading_date)

    result = CliRunner().invoke(
        historical_truth_app,
        [
            "pilot",
            "--root",
            str(root),
            "--date",
            trading_date.isoformat(),
            "--output-dir",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Pilot Complete: True" in result.output
    assert "Schemas Observed: legacy" in result.output
    assert (output / "htr007_backfill_pilot.json").exists()
    assert (output / "htr007_backfill_pilot.csv").exists()
    assert (output / "htr007_backfill_pilot.md").exists()
