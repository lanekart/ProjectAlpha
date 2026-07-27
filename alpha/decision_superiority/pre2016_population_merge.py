"""Fail-closed merger for year-sharded DSI-010 Historical Truth populations."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse

_CANONICAL_TABLES = (
    "security_identity",
    "daily_candle",
    "validation_quarantine",
    "corporate_action",
    "candle_ingestion_lineage",
)
_COPY_ROOTS = ("raw", "snapshots", "quarantine")
_BATCH_SIZE = 10_000


class Pre2016PopulationMergeError(RuntimeError):
    """Raised when population shards cannot be merged without ambiguity."""


@dataclass(frozen=True, slots=True)
class Pre2016PopulationShard:
    """Validated input shard and its calendar-year boundary."""

    root: Path
    database: Path
    manifest: Path
    covered_year: int
    manifest_records: int
    daily_candle_rows: int


@dataclass(frozen=True, slots=True)
class Pre2016PopulationMergeResult:
    """Deterministic summary of one merged governed Historical Truth store."""

    output_root: Path
    database: Path
    manifest: Path
    lineage: Path
    shard_count: int
    covered_years: tuple[int, ...]
    manifest_records: int
    daily_candle_rows: int
    observed_sessions: int
    raw_files: int
    snapshot_files: int
    quarantine_files: int
    production_influence: bool = False


def merge_pre2016_population_shards(
    *,
    shard_roots: tuple[Path, ...],
    output_root: Path,
    expected_years: tuple[int, ...],
) -> Pre2016PopulationMergeResult:
    """Merge one non-overlapping governed shard per expected calendar year."""

    years = tuple(sorted(set(expected_years)))
    if not years or len(years) != len(expected_years):
        raise Pre2016PopulationMergeError("PRE2016_MERGE_EXPECTED_YEARS_INVALID")
    if years[0] < 2005 or years[-1] > 2015:
        raise Pre2016PopulationMergeError(
            "PRE2016_MERGE_EXPECTED_YEAR_OUTSIDE_PROTOCOL"
        )
    if not shard_roots:
        raise Pre2016PopulationMergeError("PRE2016_MERGE_SHARDS_MISSING")

    resolved_output = output_root.expanduser().resolve()
    resolved_shards = tuple(root.expanduser().resolve() for root in shard_roots)
    if resolved_output in resolved_shards:
        raise Pre2016PopulationMergeError("PRE2016_MERGE_OUTPUT_IS_INPUT_SHARD")
    if resolved_output.exists() and any(resolved_output.iterdir()):
        raise Pre2016PopulationMergeError("PRE2016_MERGE_OUTPUT_NOT_EMPTY")

    shards = tuple(_inspect_shard(root) for root in resolved_shards)
    actual_years = tuple(sorted(shard.covered_year for shard in shards))
    if len(set(actual_years)) != len(actual_years):
        raise Pre2016PopulationMergeError("PRE2016_MERGE_SHARD_YEAR_OVERLAP")
    if actual_years != years:
        raise Pre2016PopulationMergeError(
            f"PRE2016_MERGE_YEAR_MISMATCH:expected={years}:actual={actual_years}"
        )

    resolved_output.mkdir(parents=True, exist_ok=True)
    database = resolved_output / "warehouse" / "historical_truth.duckdb"
    canonical = CanonicalPointInTimeWarehouse(database)
    canonical.initialise()

    table_rows: dict[str, int] = {table: 0 for table in _CANONICAL_TABLES}
    copied = {name: 0 for name in _COPY_ROOTS}
    manifest_rows: list[tuple[date, int, dict[str, Any]]] = []
    lineage_rows: list[dict[str, object]] = []

    for shard in sorted(shards, key=lambda item: item.covered_year):
        for root_name in _COPY_ROOTS:
            copied[root_name] += _copy_immutable_tree(
                shard.root / root_name,
                resolved_output / root_name,
            )
        manifest_rows.extend(_manifest_rows(shard))
        merged = _merge_database(database, shard)
        for table, count in merged.items():
            table_rows[table] += count
        lineage_rows.append(
            {
                "covered_year": shard.covered_year,
                "shard_root": str(shard.root),
                "database_path": str(shard.database),
                "database_sha256": _sha256(shard.database),
                "manifest_path": str(shard.manifest),
                "manifest_sha256": _sha256(shard.manifest),
                "manifest_records": shard.manifest_records,
                "daily_candle_rows": shard.daily_candle_rows,
            }
        )

    manifest = resolved_output / "manifests" / "archive_manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        "".join(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
            for _, _, payload in sorted(
                manifest_rows,
                key=lambda item: (
                    item[0],
                    str(item[2].get("exchange") or ""),
                    str(item[2].get("dataset") or ""),
                    item[1],
                ),
            )
        ),
        encoding="utf-8",
    )
    _verify_manifest_raw_files(resolved_output, manifest)

    with duckdb.connect(str(database), read_only=True) as connection:
        result = connection.execute(
            """
            SELECT count(*), count(distinct trading_date)
            FROM daily_candle
            WHERE exchange = 'nse'
              AND trading_date BETWEEN DATE '2005-01-01' AND DATE '2015-12-31'
            """
        ).fetchone()
    if result is None:
        raise Pre2016PopulationMergeError("PRE2016_MERGE_DATABASE_SUMMARY_MISSING")
    daily_rows = int(result[0])
    observed_sessions = int(result[1])
    if daily_rows != table_rows["daily_candle"]:
        raise Pre2016PopulationMergeError(
            "PRE2016_MERGE_DAILY_CANDLE_COUNT_MISMATCH:"
            f"merged={table_rows['daily_candle']}:observed={daily_rows}"
        )

    lineage = resolved_output / "merge_lineage.json"
    lineage.write_text(
        json.dumps(
            {
                "covered_years": list(years),
                "shard_count": len(shards),
                "shards": lineage_rows,
                "table_rows_inserted": table_rows,
                "manifest_records": len(manifest_rows),
                "raw_files": copied["raw"],
                "snapshot_files": copied["snapshots"],
                "quarantine_files": copied["quarantine"],
                "classification_inferred_from_archive_status": False,
                "classification_inferred_from_observed_candles": False,
                "production_influence": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = Pre2016PopulationMergeResult(
        output_root=resolved_output,
        database=database,
        manifest=manifest,
        lineage=lineage,
        shard_count=len(shards),
        covered_years=years,
        manifest_records=len(manifest_rows),
        daily_candle_rows=daily_rows,
        observed_sessions=observed_sessions,
        raw_files=copied["raw"],
        snapshot_files=copied["snapshots"],
        quarantine_files=copied["quarantine"],
    )
    (resolved_output / "merge_summary.json").write_text(
        json.dumps(_result_payload(summary), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _inspect_shard(root: Path) -> Pre2016PopulationShard:
    database = root / "warehouse" / "historical_truth.duckdb"
    manifest = root / "manifests" / "archive_manifest.jsonl"
    if not database.is_file():
        raise Pre2016PopulationMergeError(
            f"PRE2016_MERGE_SHARD_DATABASE_MISSING:{root}"
        )
    if not manifest.is_file():
        raise Pre2016PopulationMergeError(
            f"PRE2016_MERGE_SHARD_MANIFEST_MISSING:{root}"
        )

    records = _read_manifest(manifest)
    manifest_years = {item[0].year for item in records}
    if len(manifest_years) != 1:
        raise Pre2016PopulationMergeError(
            f"PRE2016_MERGE_SHARD_MANIFEST_YEAR_INVALID:{root}:{sorted(manifest_years)}"
        )
    covered_year = next(iter(manifest_years))
    if covered_year < 2005 or covered_year > 2015:
        raise Pre2016PopulationMergeError(
            f"PRE2016_MERGE_SHARD_YEAR_OUTSIDE_PROTOCOL:{covered_year}"
        )

    with duckdb.connect(str(database), read_only=True) as connection:
        daily_result = connection.execute(
            "SELECT count(*) FROM daily_candle"
        ).fetchone()
        date_rows = connection.execute(
            "SELECT DISTINCT year(trading_date) FROM daily_candle ORDER BY 1"
        ).fetchall()
    if daily_result is None:
        raise Pre2016PopulationMergeError("PRE2016_MERGE_SHARD_DATABASE_INVALID")
    database_years = {int(row[0]) for row in date_rows if row[0] is not None}
    if database_years and database_years != {covered_year}:
        raise Pre2016PopulationMergeError(
            f"PRE2016_MERGE_SHARD_DATABASE_YEAR_INVALID:{root}:{sorted(database_years)}"
        )

    return Pre2016PopulationShard(
        root=root,
        database=database,
        manifest=manifest,
        covered_year=covered_year,
        manifest_records=len(records),
        daily_candle_rows=int(daily_result[0]),
    )


def _manifest_rows(
    shard: Pre2016PopulationShard,
) -> list[tuple[date, int, dict[str, Any]]]:
    rows = _read_manifest(shard.manifest)
    for trading_date, _, _ in rows:
        if trading_date.year != shard.covered_year:
            raise Pre2016PopulationMergeError(
                f"PRE2016_MERGE_MANIFEST_DATE_OUTSIDE_SHARD:{shard.root}:{trading_date}"
            )
    return rows


def _read_manifest(path: Path) -> list[tuple[date, int, dict[str, Any]]]:
    rows: list[tuple[date, int, dict[str, Any]]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise TypeError
            trading_date = date.fromisoformat(str(payload.get("trading_date") or ""))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise Pre2016PopulationMergeError(
                f"PRE2016_MERGE_MANIFEST_ROW_INVALID:{path}:{index + 1}"
            ) from exc
        rows.append((trading_date, index, payload))
    if not rows:
        raise Pre2016PopulationMergeError(f"PRE2016_MERGE_MANIFEST_EMPTY:{path}")
    return rows


def _merge_database(
    target_path: Path,
    shard: Pre2016PopulationShard,
) -> dict[str, int]:
    inserted: dict[str, int] = {table: 0 for table in _CANONICAL_TABLES}
    escaped_path = str(shard.database).replace("'", "''")
    with (
        duckdb.connect(str(shard.database), read_only=True) as source,
        duckdb.connect(str(target_path)) as target,
    ):
        target.execute(f"ATTACH '{escaped_path}' AS source_shard (READ_ONLY)")
        try:
            for table in _CANONICAL_TABLES:
                if not _table_exists(source, table):
                    continue
                source_columns = _table_columns(source, table)
                target_columns = _table_columns(target, table)
                if source_columns != target_columns:
                    raise Pre2016PopulationMergeError(
                        f"PRE2016_MERGE_TABLE_SCHEMA_MISMATCH:{table}"
                    )
                source_count_result = source.execute(
                    f'SELECT count(*) FROM "{table}"'
                ).fetchone()
                before_result = target.execute(
                    f'SELECT count(*) FROM "{table}"'
                ).fetchone()
                if source_count_result is None:
                    raise Pre2016PopulationMergeError(
                        f"PRE2016_MERGE_TABLE_COUNT_MISSING:{table}"
                    )
                if before_result is None:
                    raise Pre2016PopulationMergeError(
                        f"PRE2016_MERGE_TARGET_COUNT_MISSING:{table}"
                    )
                source_count = int(source_count_result[0])
                before = int(before_result[0])
                target.execute(
                    f'INSERT OR IGNORE INTO main."{table}" '
                    f'SELECT * FROM source_shard.main."{table}"'
                )
                after_result = target.execute(
                    f'SELECT count(*) FROM "{table}"'
                ).fetchone()
                if after_result is None:
                    raise Pre2016PopulationMergeError(
                        f"PRE2016_MERGE_TARGET_COUNT_MISSING:{table}"
                    )
                added = int(after_result[0]) - before
                if (
                    table in {"daily_candle", "validation_quarantine"}
                    and added != source_count
                ):
                    raise Pre2016PopulationMergeError(
                        f"PRE2016_MERGE_TABLE_OVERLAP:{table}:"
                        f"source={source_count}:inserted={added}:"
                        f"year={shard.covered_year}"
                    )
                inserted[table] = added
        finally:
            target.execute("DETACH source_shard")
    return inserted


def _table_exists(connection: duckdb.DuckDBPyConnection, table: str) -> bool:
    result = connection.execute(
        """
        SELECT count(*)
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        """,
        [table],
    ).fetchone()
    return result is not None and int(result[0]) == 1


def _table_columns(
    connection: duckdb.DuckDBPyConnection,
    table: str,
) -> tuple[str, ...]:
    rows = connection.execute(f"PRAGMA table_info('{table}')").fetchall()
    return tuple(str(row[1]) for row in rows)


def _copy_immutable_tree(source_root: Path, destination_root: Path) -> int:
    if not source_root.exists():
        return 0
    count = 0
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        destination = destination_root / source.relative_to(source_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if _sha256(destination) != _sha256(source):
                raise Pre2016PopulationMergeError(
                    f"PRE2016_MERGE_IMMUTABLE_FILE_CONFLICT:{destination}"
                )
        else:
            shutil.copy2(source, destination)
        count += 1
    return count


def _verify_manifest_raw_files(root: Path, manifest: Path) -> None:
    for _, _, payload in _read_manifest(manifest):
        status = str(payload.get("status") or "").casefold()
        if status not in {"downloaded", "validated"}:
            continue
        relative_path = str(payload.get("relative_path") or "")
        expected_sha256 = str(payload.get("sha256") or "")
        if not relative_path or not expected_sha256:
            raise Pre2016PopulationMergeError(
                "PRE2016_MERGE_TRUSTED_MANIFEST_IDENTITY_MISSING"
            )
        raw_path = root / "raw" / relative_path
        if not raw_path.is_file():
            raise Pre2016PopulationMergeError(
                f"PRE2016_MERGE_TRUSTED_RAW_FILE_MISSING:{raw_path}"
            )
        observed = _sha256(raw_path)
        if observed != expected_sha256:
            raise Pre2016PopulationMergeError(
                f"PRE2016_MERGE_TRUSTED_RAW_HASH_MISMATCH:{raw_path}"
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _result_payload(result: Pre2016PopulationMergeResult) -> dict[str, object]:
    payload = asdict(result)
    for key in ("output_root", "database", "manifest", "lineage"):
        payload[key] = str(payload[key])
    payload["covered_years"] = list(result.covered_years)
    return payload


__all__ = [
    "Pre2016PopulationMergeError",
    "Pre2016PopulationMergeResult",
    "Pre2016PopulationShard",
    "merge_pre2016_population_shards",
]
