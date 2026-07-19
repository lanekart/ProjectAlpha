from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from alpha.market_truth.warehouse.models import DatasetVersion, WarehousePaths
from alpha.market_truth.warehouse.storage import WarehouseStore


class WarehousePublicationError(RuntimeError):
    pass


class WarehousePublisher:
    """Create immutable local Parquet research views after explicit confirmation."""

    def __init__(self, store: WarehouseStore, paths: WarehousePaths) -> None:
        self.store = store
        self.paths = paths

    def publish(
        self,
        version: DatasetVersion,
        *,
        confirm: bool,
    ) -> Path:
        if not confirm:
            raise WarehousePublicationError(
                "canonical publication requires explicit confirmation"
            )
        target = self.paths.publications / version.version
        if target.exists():
            metadata_path = target / "dataset_version.json"
            if metadata_path.is_file():
                self.store.record_publication(version=version.version, path=str(target))
                return target
            raise WarehousePublicationError(
                f"incomplete publication directory exists: {target}"
            )
        temporary = self.paths.publications / f".{version.version}.tmp"
        temporary.mkdir(parents=True, exist_ok=False)
        try:
            self._copy_table(
                "SELECT * FROM canonical_daily",
                temporary / "canonical" / "daily",
                partition_by="exchange, partition_year",
            )
            self._copy_table(
                "SELECT *, year(trading_date) AS partition_year FROM adjusted_daily",
                temporary / "adjusted" / "daily",
                partition_by="mode, exchange, partition_year",
            )
            self._copy_table(
                "SELECT * FROM identity_history",
                temporary / "canonical" / "identities.parquet",
            )
            self._copy_table(
                "SELECT * FROM corporate_actions",
                temporary / "canonical" / "corporate_actions.parquet",
            )
            self._copy_table(
                "SELECT * FROM index_daily_history",
                temporary / "canonical" / "indices.parquet",
            )
            self._copy_table(
                "SELECT * FROM deliverable_history",
                temporary / "canonical" / "deliverables.parquet",
            )
            self._copy_table(
                "SELECT * FROM aggregate_bars",
                temporary / "aggregates" / "bars.parquet",
            )
            self._copy_table(
                "SELECT * FROM universe_snapshots",
                temporary / "canonical" / "universe.parquet",
            )
            metadata_payload = asdict(version)
            metadata_payload["exchange_coverage"] = [
                item.value for item in version.exchange_coverage
            ]
            (temporary / "dataset_version.json").write_text(
                json.dumps(metadata_payload, indent=2, sort_keys=True, default=str)
                + "\n"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(target)
            self.store.record_publication(version=version.version, path=str(target))
        except Exception:
            # Keep failed staging evidence for explicit resume/rollback diagnosis.
            raise
        return target

    def _copy_table(
        self, query: str, target: Path, *, partition_by: str | None = None
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.store.connection() as database:
            count_row = database.execute(f"SELECT COUNT(*) FROM ({query})").fetchone()
            count = 0 if count_row is None else int(str(count_row[0]))
            if count == 0:
                target.mkdir(parents=True, exist_ok=True) if partition_by else None
                return
            escaped = str(target).replace("'", "''")
            options = "FORMAT PARQUET, COMPRESSION ZSTD"
            if partition_by:
                target.mkdir(parents=True, exist_ok=True)
                options += f", PARTITION_BY ({partition_by})"
            database.execute(f"COPY ({query}) TO '{escaped}' ({options})")


__all__ = ["WarehousePublicationError", "WarehousePublisher"]
