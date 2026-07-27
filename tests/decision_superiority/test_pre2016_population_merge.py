from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from alpha.decision_superiority.pre2016_population_merge import (
    Pre2016PopulationMergeError,
    merge_pre2016_population_shards,
)
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse


def test_merge_population_shards_builds_governed_store(tmp_path: Path) -> None:
    first = _build_shard(tmp_path / "shard-2005", date(2005, 1, 3))
    second = _build_shard(tmp_path / "shard-2006", date(2006, 1, 2))
    output = tmp_path / "merged"

    result = merge_pre2016_population_shards(
        shard_roots=(second, first),
        output_root=output,
        expected_years=(2005, 2006),
    )

    assert result.covered_years == (2005, 2006)
    assert result.shard_count == 2
    assert result.manifest_records == 2
    assert result.daily_candle_rows == 2
    assert result.observed_sessions == 2
    assert result.raw_files == 2
    assert result.snapshot_files == 2
    assert result.quarantine_files == 0
    assert result.production_influence is False

    manifest_rows = [
        json.loads(line)
        for line in result.manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["trading_date"] for row in manifest_rows] == [
        "2005-01-03",
        "2006-01-02",
    ]
    with duckdb.connect(str(result.database), read_only=True) as connection:
        rows = connection.execute(
            "SELECT trading_date, symbol FROM daily_candle ORDER BY trading_date"
        ).fetchall()
    assert rows == [
        (date(2005, 1, 3), "TEST2005"),
        (date(2006, 1, 2), "TEST2006"),
    ]

    lineage = json.loads(result.lineage.read_text(encoding="utf-8"))
    assert lineage["covered_years"] == [2005, 2006]
    assert lineage["classification_inferred_from_archive_status"] is False
    assert lineage["classification_inferred_from_observed_candles"] is False
    assert lineage["production_influence"] is False


def test_merge_population_shards_rejects_year_overlap(tmp_path: Path) -> None:
    first = _build_shard(tmp_path / "first", date(2005, 1, 3))
    second = _build_shard(tmp_path / "second", date(2005, 1, 4))

    with pytest.raises(
        Pre2016PopulationMergeError,
        match="PRE2016_MERGE_SHARD_YEAR_OVERLAP",
    ):
        merge_pre2016_population_shards(
            shard_roots=(first, second),
            output_root=tmp_path / "merged",
            expected_years=(2005, 2006),
        )


def test_merge_population_shards_rejects_missing_manifest(tmp_path: Path) -> None:
    shard = tmp_path / "shard"
    canonical = CanonicalPointInTimeWarehouse(
        shard / "warehouse" / "historical_truth.duckdb"
    )
    canonical.initialise()

    with pytest.raises(
        Pre2016PopulationMergeError,
        match="PRE2016_MERGE_SHARD_MANIFEST_MISSING",
    ):
        merge_pre2016_population_shards(
            shard_roots=(shard,),
            output_root=tmp_path / "merged",
            expected_years=(2005,),
        )


def test_merge_population_shards_rejects_nonempty_output(tmp_path: Path) -> None:
    shard = _build_shard(tmp_path / "shard", date(2005, 1, 3))
    output = tmp_path / "merged"
    output.mkdir()
    (output / "existing.txt").write_text("occupied\n", encoding="utf-8")

    with pytest.raises(
        Pre2016PopulationMergeError,
        match="PRE2016_MERGE_OUTPUT_NOT_EMPTY",
    ):
        merge_pre2016_population_shards(
            shard_roots=(shard,),
            output_root=output,
            expected_years=(2005,),
        )


def test_merge_population_shards_rejects_immutable_file_conflict(
    tmp_path: Path,
) -> None:
    shared_path = Path("shared") / "archive.zip"
    first = _build_shard(
        tmp_path / "first",
        date(2005, 1, 3),
        relative_path=shared_path,
        raw_bytes=b"first archive",
    )
    second = _build_shard(
        tmp_path / "second",
        date(2006, 1, 2),
        relative_path=shared_path,
        raw_bytes=b"second archive",
    )

    with pytest.raises(
        Pre2016PopulationMergeError,
        match="PRE2016_MERGE_IMMUTABLE_FILE_CONFLICT",
    ):
        merge_pre2016_population_shards(
            shard_roots=(first, second),
            output_root=tmp_path / "merged",
            expected_years=(2005, 2006),
        )


def test_merge_population_shards_rejects_manifest_hash_mismatch(
    tmp_path: Path,
) -> None:
    shard = _build_shard(tmp_path / "shard", date(2005, 1, 3))
    manifest = shard / "manifests" / "archive_manifest.jsonl"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(
        Pre2016PopulationMergeError,
        match="PRE2016_MERGE_TRUSTED_RAW_HASH_MISMATCH",
    ):
        merge_pre2016_population_shards(
            shard_roots=(shard,),
            output_root=tmp_path / "merged",
            expected_years=(2005,),
        )


def _build_shard(
    root: Path,
    trading_date: date,
    *,
    relative_path: Path | None = None,
    raw_bytes: bytes | None = None,
) -> Path:
    year = trading_date.year
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    canonical.initialise()
    with duckdb.connect(str(canonical.database_path)) as connection:
        connection.execute(
            """
            INSERT INTO daily_candle VALUES (?, 'nse', ?, 'EQ', ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                trading_date,
                f"TEST{year}",
                f"INE{year}",
                100.0,
                105.0,
                95.0,
                102.0,
                1_000,
                f"source-{year}",
            ],
        )

    raw_relative = relative_path or (
        Path("nse") / "bhavcopy" / str(year) / f"cm{trading_date:%d%b%Y}bhav.csv.zip"
    )
    raw = raw_bytes or f"official archive {year}".encode()
    raw_path = root / "raw" / raw_relative
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    manifest = root / "manifests" / "archive_manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "exchange": "nse",
                "dataset": "bhavcopy",
                "trading_date": trading_date.isoformat(),
                "source_url": f"https://nsearchives.nseindia.com/{raw_relative}",
                "relative_path": str(raw_relative),
                "status": "downloaded",
                "retrieved_at": None,
                "sha256": digest,
                "byte_size": len(raw),
                "error": None,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = root / "snapshots" / "nse" / f"{trading_date.isoformat()}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps({"trading_date": trading_date.isoformat()}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root
