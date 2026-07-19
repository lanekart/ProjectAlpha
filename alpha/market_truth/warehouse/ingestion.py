from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from alpha.market_truth.warehouse.acquisition_policy import AcquisitionPolicy
from alpha.market_truth.warehouse.archive_vault import RawArchiveVault
from alpha.market_truth.warehouse.models import (
    CanonicalDailyRecord,
    CorporateActionRecord,
    DeliverableRecord,
    Exchange,
    IdentityRecord,
    IndexDailyRecord,
    IngestionResult,
    IngestionStatus,
    SessionInventoryRecord,
    SessionState,
    SourceAuthorisation,
    SourceFileRecord,
    WarehouseDataset,
)
from alpha.market_truth.warehouse.parsers import WarehouseFileParser
from alpha.market_truth.warehouse.storage import WarehouseStore

type AcquisitionFetcher = Callable[[Exchange, WarehouseDataset, date], Path]


class WarehouseIngestionEngine:
    """Idempotent archive-to-canonical pipeline with atomic publication."""

    def __init__(
        self,
        *,
        policy: AcquisitionPolicy,
        vault: RawArchiveVault,
        store: WarehouseStore,
        parser: WarehouseFileParser | None = None,
    ) -> None:
        self.policy = policy
        self.vault = vault
        self.store = store
        self.parser = parser or WarehouseFileParser()

    def import_file(
        self,
        path: Path,
        *,
        exchange: Exchange,
        dataset: WarehouseDataset,
        authorisation_record_id: str,
        lawfully_obtained: bool,
        trading_date: date | None = None,
        publication_timestamp: datetime | None = None,
        retrieval_timestamp: datetime | None = None,
    ) -> IngestionResult:
        authorisation = self.policy.permit_manual(
            authorisation_record_id,
            lawfully_obtained=lawfully_obtained,
            on_date=(retrieval_timestamp or datetime.now(tz=UTC)).date(),
        )
        return self._ingest_authorised(
            path,
            exchange=exchange,
            dataset=dataset,
            authorisation=authorisation,
            trading_date=trading_date,
            publication_timestamp=publication_timestamp,
            retrieval_timestamp=retrieval_timestamp,
        )

    def _ingest_authorised(
        self,
        path: Path,
        *,
        exchange: Exchange,
        dataset: WarehouseDataset,
        authorisation: SourceAuthorisation,
        trading_date: date | None,
        publication_timestamp: datetime | None,
        retrieval_timestamp: datetime | None,
    ) -> IngestionResult:
        if authorisation.provider.upper() != exchange.value:
            raise ValueError("authorisation provider does not match source exchange")
        if authorisation.dataset is not dataset:
            raise ValueError("authorisation dataset does not match imported dataset")
        source, vault_duplicate = self.vault.import_file(
            path,
            exchange=exchange,
            dataset=dataset,
            authorisation=authorisation,
            trading_date=trading_date,
            publication_timestamp=publication_timestamp,
            retrieval_timestamp=retrieval_timestamp,
        )
        completed = self.store.completed_ingestion(source.source_file_id)
        if completed is not None:
            return IngestionResult(
                source_file=source,
                accepted_records=completed[0],
                rejected_records=completed[1],
                duplicate_records=completed[2],
                status=source.ingestion_status,
                reasons=("Source checksum was already ingested.",),
                idempotent=True,
            )
        try:
            parsed = self.parser.parse(self.vault.path_for(source), source)
            with self.store.transaction() as database:
                self.store.record_source_file(source, database=database)
                journal_id = self.store.begin_ingestion(
                    source.source_file_id, database=database
                )
                accepted, duplicates = self._insert(parsed.records, database=database)
                for issue in parsed.issues:
                    self.store.quarantine(
                        source_file_id=source.source_file_id,
                        record_type=dataset.value,
                        record_key=issue.record_key,
                        raw_payload=issue.raw_payload,
                        reason=f"row {issue.row_number}: {issue.reason}",
                        database=database,
                    )
                status = _status(accepted, len(parsed.issues))
                reasons = tuple(issue.reason for issue in parsed.issues[:20])
                if vault_duplicate:
                    reasons += ("Raw checksum was already present in the vault.",)
                self.store.finish_ingestion(
                    journal_id,
                    status=status,
                    accepted=accepted,
                    rejected=len(parsed.issues),
                    duplicates=duplicates,
                    reasons=reasons,
                    database=database,
                )
                self._update_session(
                    source=source,
                    status=status,
                    records=parsed.records,
                    database=database,
                )
                if source.supersedes_file_id is not None:
                    database.execute(
                        "UPDATE source_files SET ingestion_status = 'SUPERSEDED' "
                        "WHERE source_file_id = ?",
                        (source.supersedes_file_id,),
                    )
            source = self.vault.update_status(source.source_file_id, status)
            if source.supersedes_file_id is not None:
                self.vault.update_status(
                    source.supersedes_file_id, IngestionStatus.SUPERSEDED
                )
            return IngestionResult(
                source_file=source,
                accepted_records=accepted,
                rejected_records=len(parsed.issues),
                duplicate_records=duplicates,
                status=status,
                reasons=reasons,
                idempotent=False,
            )
        except Exception:
            self._record_failure(source)
            raise

    def import_directory(
        self,
        directory: Path,
        *,
        exchange: Exchange,
        dataset: WarehouseDataset,
        authorisation_record_id: str,
        lawfully_obtained: bool,
    ) -> tuple[IngestionResult, ...]:
        if not directory.is_dir():
            raise NotADirectoryError(str(directory))
        files = tuple(
            sorted(
                item
                for item in directory.iterdir()
                if item.is_file()
                and item.name.lower().endswith((".csv", ".txt", ".zip", ".gz"))
            )
        )
        return tuple(
            self.import_file(
                item,
                exchange=exchange,
                dataset=dataset,
                authorisation_record_id=authorisation_record_id,
                lawfully_obtained=lawfully_obtained,
            )
            for item in files
        )

    def acquire(
        self,
        *,
        exchange: Exchange,
        dataset: WarehouseDataset,
        session_date: date,
        authorisation_record_id: str,
        fetcher: AcquisitionFetcher,
    ) -> IngestionResult:
        authorisation = self.policy.permit_automated(
            authorisation_record_id, on_date=session_date
        )
        path = fetcher(exchange, dataset, session_date)
        return self._ingest_authorised(
            path,
            exchange=exchange,
            dataset=dataset,
            authorisation=authorisation,
            trading_date=session_date,
            publication_timestamp=None,
            retrieval_timestamp=None,
        )

    def resume(self) -> tuple[str, ...]:
        with self.store.connection() as database:
            rows = database.execute(
                """
                SELECT source_file_id FROM ingestion_journal
                WHERE status IN ('VALIDATING', 'FAILED')
                ORDER BY started_at
                """
            ).fetchall()
        # Inputs are immutable, but lawful-source attestations are not replayed by
        # the system. Return deterministic work items for explicit operator action.
        return tuple(str(row[0]) for row in rows)

    def _insert(
        self,
        records: tuple[
            CanonicalDailyRecord
            | IdentityRecord
            | CorporateActionRecord
            | SessionInventoryRecord
            | IndexDailyRecord
            | DeliverableRecord,
            ...,
        ],
        *,
        database: duckdb.DuckDBPyConnection,
    ) -> tuple[int, int]:
        daily = tuple(
            item for item in records if isinstance(item, CanonicalDailyRecord)
        )
        identities = tuple(item for item in records if isinstance(item, IdentityRecord))
        actions = tuple(
            item for item in records if isinstance(item, CorporateActionRecord)
        )
        sessions = tuple(
            item for item in records if isinstance(item, SessionInventoryRecord)
        )
        indices = tuple(item for item in records if isinstance(item, IndexDailyRecord))
        deliverables = tuple(
            item for item in records if isinstance(item, DeliverableRecord)
        )
        daily_result = self.store.insert_daily(daily, database=database)
        identity_result = self.store.insert_identities(identities, database=database)
        action_result = self.store.insert_corporate_actions(actions, database=database)
        self.store.upsert_sessions(sessions, database=database)
        index_result = self.store.insert_indices(indices, database=database)
        deliverable_result = self.store.insert_deliverables(
            deliverables, database=database
        )
        return (
            daily_result[0]
            + identity_result[0]
            + action_result[0]
            + len(sessions)
            + index_result[0]
            + deliverable_result[0],
            daily_result[1]
            + identity_result[1]
            + action_result[1]
            + index_result[1]
            + deliverable_result[1],
        )

    def _update_session(
        self,
        *,
        source: SourceFileRecord,
        status: IngestionStatus,
        records: tuple[
            CanonicalDailyRecord
            | IdentityRecord
            | CorporateActionRecord
            | SessionInventoryRecord
            | IndexDailyRecord
            | DeliverableRecord,
            ...,
        ],
        database: duckdb.DuckDBPyConnection,
    ) -> None:
        if source.dataset_type is WarehouseDataset.CALENDAR:
            return
        dates = {
            item.trading_date
            for item in records
            if isinstance(
                item, (CanonicalDailyRecord, IndexDailyRecord, DeliverableRecord)
            )
        }
        if source.trading_date is not None:
            dates.add(source.trading_date)
        state = {
            IngestionStatus.VALIDATED: SessionState.VALIDATED,
            IngestionStatus.PARTIAL: SessionState.PARTIAL,
            IngestionStatus.QUARANTINED: SessionState.QUARANTINED,
        }.get(status, SessionState.IMPORTED)
        self.store.upsert_sessions(
            tuple(
                SessionInventoryRecord(
                    exchange=source.exchange,
                    session_date=item,
                    state=state,
                    source_file_id=source.source_file_id,
                    reason=f"{source.dataset_type.value} source is {status.value}.",
                )
                for item in sorted(dates)
            ),
            database=database,
        )

    def _record_failure(self, source: SourceFileRecord) -> None:
        failed = replace(source, ingestion_status=IngestionStatus.FAILED)
        with self.store.transaction() as database:
            self.store.record_source_file(failed, database=database)
            journal_id = self.store.begin_ingestion(
                failed.source_file_id, database=database
            )
            self.store.finish_ingestion(
                journal_id,
                status=IngestionStatus.FAILED,
                accepted=0,
                rejected=0,
                duplicates=0,
                reasons=("Ingestion failed before canonical publication.",),
                database=database,
            )
        self.vault.update_status(failed.source_file_id, IngestionStatus.FAILED)


def _status(accepted: int, rejected: int) -> IngestionStatus:
    if accepted == 0:
        return IngestionStatus.QUARANTINED
    if rejected:
        return IngestionStatus.PARTIAL
    return IngestionStatus.VALIDATED


__all__ = ["AcquisitionFetcher", "WarehouseIngestionEngine"]
