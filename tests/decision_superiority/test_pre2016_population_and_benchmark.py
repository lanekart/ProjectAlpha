from __future__ import annotations

import hashlib
import inspect
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from typer.testing import CliRunner

from alpha.application import (
    decision_superiority_pre2016_external_validation_cli as cli,
)
from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority.pre2016_benchmark import load_pre2016_governed_tri
from alpha.decision_superiority.pre2016_population import (
    Pre2016PopulationError,
    Pre2016PopulationResult,
    populate_pre2016_historical_truth,
)


def test_official_tri_schema_and_provenance_are_accepted(tmp_path: Path) -> None:
    benchmark = _write_tri(
        tmp_path,
        dates=("2007-01-02", "2007-01-03"),
        values=(1000.0, 1010.0),
    )

    frame, rows = load_pre2016_governed_tri(
        benchmark,
        sessions=(date(2007, 1, 2), date(2007, 1, 3)),
        start=date(2007, 1, 2),
        end=date(2007, 1, 3),
    )

    assert list(frame.columns) == ["trading_date", "benchmark_value"]
    assert rows[0]["status"] == "AVAILABLE_TOTAL_RETURN"
    assert rows[0]["missing_governed_sessions"] == 0
    assert rows[0]["benchmark_kind"] == "TOTAL_RETURN"


def test_official_tri_missing_external_sessions_is_partial(tmp_path: Path) -> None:
    benchmark = _write_tri(
        tmp_path,
        dates=("2007-01-02", "2007-01-03"),
        values=(1000.0, 1010.0),
    )

    _, rows = load_pre2016_governed_tri(
        benchmark,
        sessions=(
            date(2007, 1, 2),
            date(2007, 1, 3),
            date(2007, 1, 4),
        ),
        start=date(2007, 1, 2),
        end=date(2007, 1, 4),
    )

    assert rows[0]["status"] == "PARTIAL_TOTAL_RETURN"
    assert rows[0]["missing_governed_sessions"] == 1
    assert rows[0]["used_for_external_superiority"] is False


def test_population_rejects_2016_before_touching_storage(tmp_path: Path) -> None:
    with pytest.raises(
        Pre2016PopulationError,
        match="PRE2016_POPULATION_OVERLAPS_2016",
    ):
        populate_pre2016_historical_truth(
            root=tmp_path / "alpha_data",
            output_dir=tmp_path / "artifacts",
            start=date(2005, 1, 1),
            end=date(2016, 1, 1),
        )


def test_population_fails_closed_on_low_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "alpha.decision_superiority.pre2016_population.shutil.disk_usage",
        lambda _: SimpleNamespace(free=1024),
    )

    with pytest.raises(
        Pre2016PopulationError,
        match="PRE2016_POPULATION_INSUFFICIENT_DISK_SPACE",
    ):
        populate_pre2016_historical_truth(
            root=tmp_path / "alpha_data",
            output_dir=tmp_path / "artifacts",
            start=date(2005, 1, 1),
            end=date(2015, 12, 31),
        )


def test_archive_cli_uses_governed_population_not_legacy_ingestion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = Pre2016PopulationResult(
        requested_start=date(2005, 1, 1),
        requested_end=date(2015, 12, 31),
        planned_requests=2869,
        coverage_ratio=0.99,
        candle_snapshots=2700,
        evidence_complete_snapshots=0,
        evidence_incomplete_snapshots=2700,
        failed=0,
        unavailable=169,
        skipped=0,
        ingested_rows=1_000_000,
        available_rows=1_000_000,
        free_bytes_before=20 * 1024**3,
        database=tmp_path / "alpha_data/warehouse/historical_truth.duckdb",
        snapshot_root=tmp_path / "alpha_data/snapshots",
        artifact_paths=(tmp_path / "population.json",),
    )
    monkeypatch.setattr(cli, "populate_pre2016_historical_truth", lambda **_: result)

    invocation = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-pre2016-archive-backfill",
            "--root",
            str(tmp_path / "alpha_data"),
            "--output-dir",
            str(tmp_path / "artifacts"),
        ],
    )

    assert invocation.exit_code == 0
    assert "Historical Truth Database" in invocation.stdout
    assert "DOWNSTREAM_GOVERNED_A_TO_B_REBUILD_REQUIRED=true" in invocation.stdout
    assert "LEGACY_INGESTION_DATABASE_USED=false" in invocation.stdout
    assert "HistoricalIngestionService" not in inspect.getsource(cli)


def _write_tri(
    root: Path,
    *,
    dates: tuple[str, ...],
    values: tuple[float, ...],
) -> Path:
    path = root / "nifty500_tri_2005_2015.csv"
    pd.DataFrame(
        {
            "Date": dates,
            "Index Name": ("Nifty 500",) * len(dates),
            "TotalReturnsIndex": values,
            "NTR_Value": values,
        }
    ).to_csv(path, index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    provenance = {
        "acquired_at": "2026-07-27T00:00:00+05:30",
        "adjustment_treatment": "OFFICIAL_NIFTY_INDICES_TOTAL_RETURN_SERIES",
        "benchmark_kind": "TOTAL_RETURN",
        "currency": "INR",
        "dividend_treatment": "GROSS_TOTAL_RETURN_INDEX",
        "index_identifier": "NIFTY500",
        "index_name": "Nifty 500",
        "raw_source_sha256": digest,
        "source": "https://www.niftyindices.com/BackPage/getTotalReturnIndexString",
        "source_version": "TEST",
    }
    path.with_suffix(path.suffix + ".provenance.json").write_text(
        json.dumps(provenance, sort_keys=True),
        encoding="utf-8",
    )
    return path
