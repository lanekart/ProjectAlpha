from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol

import duckdb

from alpha.data_platform import DatasetCategory, build_default_platform
from alpha.historical_truth_acquisition.checkpoints import CheckpointStore
from alpha.historical_truth_acquisition.evidence import EvidenceStore
from alpha.historical_truth_acquisition.index_membership import (
    IndexMembershipRepository,
    parse_membership_file,
)
from alpha.historical_truth_acquisition.models import (
    CheckpointStatus,
    EvidenceEvent,
    HTAStage,
    StageRunResult,
    StageStatus,
)
from alpha.historical_truth_acquisition.stages import selected_stages
from alpha.market_truth.warehouse import HistoricalMarketWarehouse
from alpha.market_truth.warehouse.models import (
    Exchange,
    IngestionStatus,
    WarehouseDataset,
)


@dataclass(frozen=True, slots=True)
class AcquisitionRequest:
    dataset_id: str
    start: date | None
    end: date | None
    destination: Path


class OfficialSourceConnector(Protocol):
    """Injectable connector; the HTA core ships with no unlicensed scraper."""

    def fetch(self, request: AcquisitionRequest) -> tuple[Path, ...]: ...


@dataclass(frozen=True, slots=True)
class AcquisitionOptions:
    output_directory: Path
    source_directory: Path | None
    lawfully_obtained: bool
    selected_dataset: str | None
    start: date | None
    end: date | None
    resume: bool
    verify: bool
    force: bool
    parallelism: int
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.parallelism < 1:
            raise ValueError("HTA parallelism must be positive")
        if self.start and self.end and self.end < self.start:
            raise ValueError("HTA acquisition date range is invalid")


class HistoricalTruthAcquirer:
    """Lawful-source intake into an isolated Warehouse v2 candidate store."""

    def __init__(
        self,
        options: AcquisitionOptions,
        *,
        connectors: Mapping[str, OfficialSourceConnector] | None = None,
    ) -> None:
        self.options = options
        self.warehouse = HistoricalMarketWarehouse(
            options.output_directory / "warehouse_v2_candidate" / "warehouse"
        )
        metadata = options.output_directory / "metadata"
        self.checkpoints = CheckpointStore(metadata / "checkpoints.json")
        self.evidence = EvidenceStore(metadata / "dataset_evidence.json")
        self.memberships = IndexMembershipRepository(metadata / "index_membership.json")
        self.connectors = dict(connectors or {})
        self.platform = build_default_platform()

    def acquire(self) -> tuple[StageRunResult, ...]:
        if self.options.verify:
            self.verify_vault()
        results = []
        blocked_by: HTAStage | None = None
        for stage in selected_stages(self.options.selected_dataset):
            dataset_ids = (
                stage.dataset_ids
                if self.options.selected_dataset is None
                else (self.options.selected_dataset,)
            )
            if blocked_by is not None:
                results.append(
                    StageRunResult(
                        stage=stage.stage,
                        status=StageStatus.BLOCKED_DEPENDENCY,
                        attempted_datasets=(),
                        imported_files=0,
                        duplicate_files=0,
                        rejected_records=0,
                        reasons=(
                            f"Stage blocked because {blocked_by.value} did not "
                            "complete successfully.",
                        ),
                    )
                )
                continue
            result = self._run_stage(stage.stage, dataset_ids)
            results.append(result)
            if (
                self.options.selected_dataset is None
                and result.status is not StageStatus.COMPLETE
            ):
                blocked_by = stage.stage
        return tuple(results)

    def verify_vault(self) -> None:
        for record in self.warehouse.vault.records():
            self.warehouse.vault.verify(record)

    def _run_stage(
        self, stage: HTAStage, dataset_ids: tuple[str, ...]
    ) -> StageRunResult:
        imported = 0
        duplicates = 0
        rejected = 0
        completed_datasets = 0
        reasons: list[str] = []
        for dataset_id in dataset_ids:
            files = self._source_files(dataset_id)
            if not files:
                connector = self.connectors.get(dataset_id)
                if connector is None:
                    reasons.append(
                        f"{dataset_id}: no lawfully supplied source files or "
                        "authorised connector are configured."
                    )
                    continue
                files = connector.fetch(
                    AcquisitionRequest(
                        dataset_id=dataset_id,
                        start=self.options.start,
                        end=self.options.end,
                        destination=self.options.output_directory / "downloads",
                    )
                )
            for path, checksum in _preflight(files, self.options.parallelism):
                outcome = self._import(dataset_id, path, checksum)
                imported += int(not outcome[0])
                duplicates += int(outcome[0])
                rejected += outcome[1]
                reasons.extend(outcome[2])
            completed_datasets += int(bool(files))
        if completed_datasets == len(dataset_ids) and rejected == 0:
            status = StageStatus.COMPLETE
        elif imported or duplicates:
            status = StageStatus.FAILED
        else:
            status = StageStatus.BLOCKED_SOURCE_UNAVAILABLE
        return StageRunResult(
            stage=stage,
            status=status,
            attempted_datasets=tuple(dataset_ids),
            imported_files=imported,
            duplicate_files=duplicates,
            rejected_records=rejected,
            reasons=tuple(reasons),
        )

    def _import(
        self, dataset_id: str, path: Path, checksum: str
    ) -> tuple[bool, int, tuple[str, ...]]:
        checkpoint = self.checkpoints.get_or_plan(
            dataset_id=dataset_id,
            source_key=str(path.resolve()),
            observed_at=self.options.observed_at,
        )
        if (
            checkpoint.status is CheckpointStatus.COMPLETE
            and self.options.resume
            and not self.options.force
        ):
            return True, 0, (f"{dataset_id}: resumed from verified checkpoint.",)
        checkpoint = self.checkpoints.begin(
            checkpoint, observed_at=self.options.observed_at
        )
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != checksum:
            self.checkpoints.fail(
                checkpoint,
                reason="source changed between preflight and import",
                observed_at=self.options.observed_at,
                corrupt=True,
            )
            raise RuntimeError(f"HTA source checksum changed during import: {path}")
        checkpoint = self.checkpoints.verified(
            checkpoint,
            checksum=checksum,
            completed_bytes=path.stat().st_size,
            observed_at=self.options.observed_at,
        )
        try:
            if dataset_id == "nse-historical-index-membership":
                duplicate, rejected, reasons = self._import_membership(dataset_id, path)
            else:
                duplicate, rejected, reasons = self._import_warehouse_file(
                    dataset_id, path
                )
            self.checkpoints.complete(checkpoint, observed_at=self.options.observed_at)
            return duplicate, rejected, reasons
        except Exception as error:
            self.checkpoints.fail(
                checkpoint,
                reason=str(error),
                observed_at=self.options.observed_at,
            )
            raise

    def _import_warehouse_file(
        self, dataset_id: str, path: Path
    ) -> tuple[bool, int, tuple[str, ...]]:
        exchange, warehouse_dataset = _binding(dataset_id)
        authorisation = f"{exchange.value}_{warehouse_dataset.value}_MANUAL_V1"
        if not self.options.lawfully_obtained:
            raise PermissionError(
                "HTA manual import requires --lawfully-obtained attestation"
            )
        result = self.warehouse.ingestion.import_file(
            path,
            exchange=exchange,
            dataset=warehouse_dataset,
            authorisation_record_id=authorisation,
            lawfully_obtained=True,
            trading_date=_date_from_filename(path),
            retrieval_timestamp=self.options.observed_at,
        )
        self.warehouse.vault.verify(result.source_file)
        observed_dates = self._observed_dates(result.source_file.source_file_id)
        event = EvidenceEvent(
            source_file_id=result.source_file.source_file_id,
            dataset_id=dataset_id,
            checksum=result.source_file.sha256,
            schema_fingerprint=result.source_file.schema_fingerprint,
            accepted_records=result.accepted_records,
            rejected_records=result.rejected_records,
            duplicate_records=result.duplicate_records,
            coverage_start=(None if not observed_dates else observed_dates[0]),
            coverage_end=(None if not observed_dates else observed_dates[-1]),
            observed_dates=observed_dates,
            checksum_verified=True,
        )
        self.evidence.append(event)
        return result.idempotent, result.rejected_records, result.reasons

    def _import_membership(
        self, dataset_id: str, path: Path
    ) -> tuple[bool, int, tuple[str, ...]]:
        if not self.options.lawfully_obtained:
            raise PermissionError(
                "HTA manual import requires --lawfully-obtained attestation"
            )
        authorisation = self.warehouse.policy.permit_manual(
            "NSE_INDICES_MANUAL_V1",
            lawfully_obtained=True,
            on_date=self.options.observed_at.date(),
        )
        source, duplicate = self.warehouse.vault.import_file(
            path,
            exchange=Exchange.NSE,
            dataset=WarehouseDataset.INDICES,
            authorisation=authorisation,
            trading_date=_date_from_filename(path),
            retrieval_timestamp=self.options.observed_at,
        )
        self.warehouse.vault.verify(source)
        records, issues, unresolved = parse_membership_file(
            self.warehouse.vault.path_for(source),
            source_file_id=source.source_file_id,
            identities=self.warehouse.store.identity_records(),
        )
        self.memberships.append(records)
        status = (
            IngestionStatus.VALIDATED
            if records and not issues
            else IngestionStatus.PARTIAL
            if records
            else IngestionStatus.QUARANTINED
        )
        self.warehouse.vault.update_status(source.source_file_id, status)
        dates = tuple(sorted({item.effective_date for item in records}))
        self.evidence.append(
            EvidenceEvent(
                source_file_id=source.source_file_id,
                dataset_id=dataset_id,
                checksum=source.sha256,
                schema_fingerprint=source.schema_fingerprint,
                accepted_records=len(records),
                rejected_records=len(issues),
                duplicate_records=int(duplicate),
                coverage_start=None if not dates else dates[0],
                coverage_end=None if not dates else dates[-1],
                observed_dates=dates,
                checksum_verified=True,
                unresolved_identity_records=unresolved,
            )
        )
        return duplicate, len(issues), issues

    def _source_files(self, dataset_id: str) -> tuple[Path, ...]:
        root = self.options.source_directory
        if root is None:
            return ()
        directory = root / dataset_id
        supported = (".csv", ".txt", ".zip", ".gz")
        files: list[Path] = []
        if directory.is_dir():
            files.extend(
                item
                for item in directory.iterdir()
                if item.is_file() and item.name.lower().endswith(supported)
            )
        files.extend(
            item
            for item in root.glob(dataset_id + ".*")
            if item.is_file() and item.name.lower().endswith(supported)
        )
        return tuple(sorted(set(files)))

    def _observed_dates(self, source_file_id: str) -> tuple[date, ...]:
        queries = (
            "SELECT trading_date FROM canonical_daily_history WHERE source_file_id = ?",
            "SELECT trading_date FROM index_daily_history WHERE source_file_id = ?",
            "SELECT trading_date FROM deliverable_history WHERE source_file_id = ?",
            "SELECT session_date FROM session_inventory WHERE source_file_id = ?",
            "SELECT announcement_date FROM corporate_actions WHERE source_file_id = ?",
            "SELECT symbol_valid_from FROM identity_history WHERE source_file_id = ?",
        )
        dates: set[date] = set()
        with self.warehouse.store.connection() as database:
            for query in queries:
                rows = database.execute(query, (source_file_id,)).fetchall()
                dates.update(row[0] for row in rows if isinstance(row[0], date))
        return tuple(sorted(dates))


def _preflight(
    files: tuple[Path, ...], parallelism: int
) -> tuple[tuple[Path, str], ...]:
    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        checksums = tuple(executor.map(_checksum, files))
    return tuple(zip(files, checksums, strict=True))


def _checksum(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _binding(dataset_id: str) -> tuple[Exchange, WarehouseDataset]:
    record = build_default_platform().registry.get(dataset_id)
    exchange = Exchange.BSE if record.exchange.upper() == "BSE" else Exchange.NSE
    mapping = {
        DatasetCategory.DAILY_OHLCV: WarehouseDataset.BHAVCOPY,
        DatasetCategory.DELIVERY: WarehouseDataset.DELIVERABLES,
        DatasetCategory.CORPORATE_ACTION: WarehouseDataset.CORPORATE_ACTIONS,
        DatasetCategory.SECURITY_MASTER: WarehouseDataset.SECURITIES,
        DatasetCategory.IDENTITY: WarehouseDataset.SECURITIES,
        DatasetCategory.SYMBOL_HISTORY: WarehouseDataset.SECURITIES,
        DatasetCategory.TRADING_CALENDAR: WarehouseDataset.CALENDAR,
        DatasetCategory.INDEX_OHLCV: WarehouseDataset.INDICES,
    }
    try:
        return exchange, mapping[record.category]
    except KeyError as error:
        message = f"HTA dataset requires a specialized parser: {dataset_id}"
        raise ValueError(message) from error


def _date_from_filename(path: Path) -> date | None:
    for token in path.stem.replace("_", "-").split("-"):
        if len(token) == 8 and token.isdigit():
            try:
                return date(int(token[:4]), int(token[4:6]), int(token[6:]))
            except ValueError:
                continue
    parts = path.stem.replace("_", "-").split("-")
    for index in range(max(0, len(parts) - 2)):
        try:
            return date.fromisoformat("-".join(parts[index : index + 3]))
        except ValueError:
            continue
    return None


def validate_candidate_database(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with duckdb.connect(str(path), read_only=True) as database:
            database.execute("SELECT COUNT(*) FROM source_files").fetchone()
    except duckdb.Error:
        return False
    return True


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


__all__ = [
    "AcquisitionOptions",
    "AcquisitionRequest",
    "HistoricalTruthAcquirer",
    "OfficialSourceConnector",
    "utc_now",
    "validate_candidate_database",
]
