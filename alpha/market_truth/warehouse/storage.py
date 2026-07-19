from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import duckdb

from alpha.market_truth.warehouse.models import (
    AdjustedDailyRecord,
    AdjustmentMode,
    AdjustmentStatus,
    AggregateBar,
    AggregatePeriod,
    CanonicalDailyRecord,
    CorporateActionKind,
    CorporateActionRecord,
    DatasetVersion,
    DeliverableRecord,
    Exchange,
    IdentityRecord,
    IndexDailyRecord,
    IngestionStatus,
    ReconciliationStatus,
    SessionInventoryRecord,
    SessionState,
    SourceFileRecord,
    UniverseMembership,
    WarehousePaths,
    WarehouseQualityState,
    WarehouseStatus,
)


class WarehouseStore:
    """Transactional DuckDB metadata and canonical record store."""

    def __init__(self, paths: WarehousePaths, *, read_only: bool = False) -> None:
        self.paths = paths
        self.read_only = read_only
        if not read_only:
            paths.root.mkdir(parents=True, exist_ok=True)
            self._initialise()
        elif not paths.database.exists():
            raise FileNotFoundError(f"warehouse database is absent: {paths.database}")

    @contextmanager
    def connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        database = duckdb.connect(str(self.paths.database), read_only=self.read_only)
        try:
            yield database
        finally:
            database.close()

    @contextmanager
    def transaction(self) -> Iterator[duckdb.DuckDBPyConnection]:
        if self.read_only:
            raise RuntimeError("read-only warehouse cannot start a transaction")
        with self.connection() as database:
            database.execute("BEGIN TRANSACTION")
            try:
                yield database
            except Exception:
                database.execute("ROLLBACK")
                raise
            else:
                database.execute("COMMIT")

    def record_source_file(
        self,
        record: SourceFileRecord,
        *,
        database: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        if database is None:
            with self.transaction() as active:
                self.record_source_file(record, database=active)
            return
        database.execute(
            """
            INSERT INTO source_files VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT (source_file_id) DO UPDATE SET
                ingestion_status = excluded.ingestion_status
            """,
            (
                record.source_file_id,
                record.provider,
                record.dataset_type.value,
                record.exchange.value,
                record.trading_date,
                record.publication_timestamp,
                record.retrieval_timestamp,
                record.original_filename,
                record.content_type,
                record.file_size,
                record.sha256,
                record.schema_fingerprint,
                record.authorisation_record_id,
                record.ingestion_status.value,
                record.vault_path,
                record.supersedes_file_id,
            ),
        )

    def source_by_checksum(self, checksum: str) -> SourceFileRecord | None:
        with self.connection() as database:
            row = database.execute(
                "SELECT * FROM source_files WHERE sha256 = ? LIMIT 1", (checksum,)
            ).fetchone()
        return None if row is None else _source_file(row)

    def begin_ingestion(
        self,
        source_file_id: str,
        *,
        database: duckdb.DuckDBPyConnection,
    ) -> str:
        journal_id = f"ingestion-{source_file_id}"
        database.execute(
            """
            INSERT INTO ingestion_journal
            (journal_id, source_file_id, started_at, status, accepted_records,
             rejected_records, duplicate_records, reasons)
            VALUES (?, ?, ?, 'VALIDATING', 0, 0, 0, '[]')
            ON CONFLICT (journal_id) DO NOTHING
            """,
            (journal_id, source_file_id, datetime.now(tz=UTC)),
        )
        return journal_id

    def finish_ingestion(
        self,
        journal_id: str,
        *,
        status: IngestionStatus,
        accepted: int,
        rejected: int,
        duplicates: int,
        reasons: tuple[str, ...],
        database: duckdb.DuckDBPyConnection,
    ) -> None:
        database.execute(
            """
            UPDATE ingestion_journal
            SET completed_at = ?, status = ?, accepted_records = ?,
                rejected_records = ?, duplicate_records = ?, reasons = ?
            WHERE journal_id = ?
            """,
            (
                datetime.now(tz=UTC),
                status.value,
                accepted,
                rejected,
                duplicates,
                json.dumps(reasons),
                journal_id,
            ),
        )
        database.execute(
            """
            UPDATE source_files SET ingestion_status = ?
            WHERE source_file_id = (
                SELECT source_file_id FROM ingestion_journal WHERE journal_id = ?
            )
            """,
            (status.value, journal_id),
        )

    def completed_ingestion(self, source_file_id: str) -> tuple[int, int, int] | None:
        with self.connection() as database:
            row = database.execute(
                """
                SELECT accepted_records, rejected_records, duplicate_records
                FROM ingestion_journal
                WHERE source_file_id = ? AND status IN ('VALIDATED', 'PARTIAL')
                """,
                (source_file_id,),
            ).fetchone()
        if row is None:
            return None
        return int(row[0]), int(row[1]), int(row[2])

    def insert_daily(
        self,
        records: tuple[CanonicalDailyRecord, ...],
        *,
        database: duckdb.DuckDBPyConnection,
    ) -> tuple[int, int]:
        accepted = 0
        duplicates = 0
        for item in records:
            existing = database.execute(
                """
                SELECT 1 FROM canonical_daily_history
                WHERE exchange = ? AND trading_date = ? AND security_id = ?
                  AND source_file_id = ? AND record_checksum = ?
                """,
                (
                    item.exchange.value,
                    item.trading_date,
                    item.security_id,
                    item.source_file_id,
                    item.record_checksum,
                ),
            ).fetchone()
            if existing is not None:
                duplicates += 1
                continue
            database.execute(
                """
                INSERT INTO canonical_daily_history VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    item.exchange.value,
                    item.trading_date,
                    item.security_id,
                    item.symbol_as_traded,
                    item.series,
                    item.isin,
                    item.open,
                    item.high,
                    item.low,
                    item.close,
                    item.last_price,
                    item.previous_close,
                    item.volume,
                    item.turnover,
                    item.trade_count,
                    item.vwap,
                    item.deliverable_quantity,
                    item.deliverable_percentage,
                    item.upper_price_band,
                    item.lower_price_band,
                    item.source_file_id,
                    item.record_checksum,
                    item.quality_state.value,
                    item.confidence,
                    item.dataset_version,
                    datetime.now(tz=UTC),
                    item.trading_date.year,
                ),
            )
            accepted += 1
        return accepted, duplicates

    def insert_identities(
        self,
        records: tuple[IdentityRecord, ...],
        *,
        database: duckdb.DuckDBPyConnection,
    ) -> tuple[int, int]:
        accepted = 0
        duplicates = 0
        for item in records:
            key = (
                item.exchange.value,
                item.security_id,
                item.symbol,
                item.symbol_valid_from,
                item.source_file_id,
            )
            if database.execute(
                """SELECT 1 FROM identity_history WHERE exchange = ?
                AND security_id = ? AND symbol = ? AND symbol_valid_from = ?
                AND source_file_id = ?""",
                key,
            ).fetchone():
                duplicates += 1
                continue
            database.execute(
                """
                INSERT INTO identity_history VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    item.exchange.value,
                    item.security_id,
                    item.symbol,
                    item.series,
                    item.isin,
                    item.company_name,
                    item.instrument_type,
                    item.listing_date,
                    item.delisting_date,
                    json.dumps(item.suspension_intervals, default=str),
                    json.dumps(item.relisting_intervals, default=str),
                    item.symbol_valid_from,
                    item.symbol_valid_to,
                    item.series_valid_from,
                    item.series_valid_to,
                    item.identity_authority,
                    item.identity_confidence,
                    item.source_file_id,
                    datetime.now(tz=UTC),
                ),
            )
            accepted += 1
        return accepted, duplicates

    def insert_corporate_actions(
        self,
        records: tuple[CorporateActionRecord, ...],
        *,
        database: duckdb.DuckDBPyConnection,
    ) -> tuple[int, int]:
        accepted = 0
        duplicates = 0
        for item in records:
            if database.execute(
                "SELECT 1 FROM corporate_actions WHERE corporate_action_id = ?",
                (item.corporate_action_id,),
            ).fetchone():
                duplicates += 1
                continue
            database.execute(
                """
                INSERT INTO corporate_actions VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    item.corporate_action_id,
                    item.security_id,
                    item.exchange.value,
                    item.action_type.value,
                    item.announcement_date,
                    item.ex_date,
                    item.record_date,
                    item.effective_date,
                    item.payment_date,
                    item.ratio_numerator,
                    item.ratio_denominator,
                    item.cash_amount,
                    item.currency,
                    item.old_symbol,
                    item.new_symbol,
                    item.old_isin,
                    item.new_isin,
                    item.source_file_id,
                    item.raw_terms,
                    item.normalised_terms,
                    item.evidence_class,
                    item.confidence,
                    item.reconciliation_status.value,
                    item.adjustment_status.value,
                    item.version,
                ),
            )
            accepted += 1
        return accepted, duplicates

    def insert_indices(
        self,
        records: tuple[IndexDailyRecord, ...],
        *,
        database: duckdb.DuckDBPyConnection,
    ) -> tuple[int, int]:
        accepted = duplicates = 0
        for item in records:
            existing = database.execute(
                """
                SELECT 1 FROM index_daily_history
                WHERE exchange = ? AND index_id = ? AND trading_date = ?
                  AND source_file_id = ?
                """,
                (
                    item.exchange.value,
                    item.index_id,
                    item.trading_date,
                    item.source_file_id,
                ),
            ).fetchone()
            if existing is not None:
                duplicates += 1
                continue
            database.execute(
                """
                INSERT INTO index_daily_history (
                    exchange, index_id, index_name, trading_date,
                    open, high, low, close, volume, source_file_id,
                    dataset_version, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.exchange.value,
                    item.index_id,
                    item.index_name,
                    item.trading_date,
                    item.open,
                    item.high,
                    item.low,
                    item.close,
                    item.volume,
                    item.source_file_id,
                    item.dataset_version,
                    datetime.now(tz=UTC),
                ),
            )
            accepted += 1
        return accepted, duplicates

    def insert_deliverables(
        self,
        records: tuple[DeliverableRecord, ...],
        *,
        database: duckdb.DuckDBPyConnection,
    ) -> tuple[int, int]:
        accepted = duplicates = 0
        for item in records:
            existing = database.execute(
                """
                SELECT 1 FROM deliverable_history
                WHERE exchange = ? AND security_id = ? AND trading_date = ?
                  AND source_file_id = ?
                """,
                (
                    item.exchange.value,
                    item.security_id,
                    item.trading_date,
                    item.source_file_id,
                ),
            ).fetchone()
            if existing is not None:
                duplicates += 1
                continue
            database.execute(
                "INSERT INTO deliverable_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item.exchange.value,
                    item.trading_date,
                    item.security_id,
                    item.symbol,
                    item.series,
                    item.deliverable_quantity,
                    item.deliverable_percentage,
                    item.source_file_id,
                    datetime.now(tz=UTC),
                ),
            )
            accepted += 1
        return accepted, duplicates

    def index_records(self) -> tuple[IndexDailyRecord, ...]:
        with self.connection() as database:
            rows = database.execute(
                """
                SELECT h.exchange, h.index_id, h.index_name, h.trading_date,
                       h.open, h.high, h.low, h.close, h.source_file_id,
                       h.dataset_version, h.volume
                FROM index_daily_history h JOIN source_files s USING (source_file_id)
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY h.exchange, h.index_id, h.trading_date
                    ORDER BY s.retrieval_timestamp DESC, h.source_file_id DESC
                ) = 1
                ORDER BY h.index_id, h.trading_date
                """
            ).fetchall()
        return tuple(
            IndexDailyRecord(
                exchange=Exchange(str(row[0])),
                index_id=str(row[1]),
                index_name=str(row[2]),
                trading_date=cast(date, row[3]),
                open=None if row[4] is None else _decimal(row[4]),
                high=None if row[5] is None else _decimal(row[5]),
                low=None if row[6] is None else _decimal(row[6]),
                close=_decimal(row[7]),
                source_file_id=str(row[8]),
                dataset_version=str(row[9]),
                volume=None if row[10] is None else _decimal(row[10]),
            )
            for row in rows
        )

    def quarantine(
        self,
        *,
        source_file_id: str,
        record_type: str,
        record_key: str,
        raw_payload: str,
        reason: str,
        database: duckdb.DuckDBPyConnection,
    ) -> None:
        quarantine_id = (
            "quarantine-"
            + _hash(
                f"{source_file_id}|{record_type}|{record_key}|{reason}|{raw_payload}"
            )[:24]
        )
        database.execute(
            """
            INSERT INTO quarantine VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (quarantine_id) DO NOTHING
            """,
            (
                quarantine_id,
                source_file_id,
                record_type,
                record_key,
                raw_payload,
                reason,
                datetime.now(tz=UTC),
            ),
        )

    def daily_records(
        self,
        *,
        exchange: Exchange | None = None,
        symbols: tuple[str, ...] = (),
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[CanonicalDailyRecord, ...]:
        where = ["1 = 1"]
        parameters: list[object] = []
        if exchange is not None:
            where.append("exchange = ?")
            parameters.append(exchange.value)
        if symbols:
            where.append(
                "UPPER(symbol_as_traded) IN (" + ",".join("?" for _ in symbols) + ")"
            )
            parameters.extend(item.upper() for item in symbols)
        if start is not None:
            where.append("trading_date >= ?")
            parameters.append(start)
        if end is not None:
            where.append("trading_date <= ?")
            parameters.append(end)
        with self.connection() as database:
            rows = database.execute(
                "SELECT * EXCLUDE (ingested_at, partition_year) FROM canonical_daily "
                f"WHERE {' AND '.join(where)} ORDER BY security_id, trading_date",
                tuple(parameters),
            ).fetchall()
        return tuple(_daily(row) for row in rows)

    def identity_records(
        self, *, exchange: Exchange | None = None
    ) -> tuple[IdentityRecord, ...]:
        query = "SELECT * EXCLUDE (ingested_at) FROM identity_history"
        parameters: tuple[object, ...] = ()
        if exchange is not None:
            query += " WHERE exchange = ?"
            parameters = (exchange.value,)
        query += " ORDER BY security_id, symbol_valid_from"
        with self.connection() as database:
            rows = database.execute(query, parameters).fetchall()
        return tuple(_identity(row) for row in rows)

    def corporate_action_records(
        self,
        *,
        security_ids: tuple[str, ...] = (),
        announced_as_of: date | None = None,
    ) -> tuple[CorporateActionRecord, ...]:
        where = ["1 = 1"]
        parameters: list[object] = []
        if security_ids:
            where.append("security_id IN (" + ",".join("?" for _ in security_ids) + ")")
            parameters.extend(security_ids)
        if announced_as_of is not None:
            where.append("announcement_date <= ?")
            parameters.append(announced_as_of)
        with self.connection() as database:
            rows = database.execute(
                "SELECT * FROM corporate_actions "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY security_id, ex_date, announcement_date",
                tuple(parameters),
            ).fetchall()
        return tuple(_corporate_action(row) for row in rows)

    def replace_adjusted(
        self,
        records: tuple[AdjustedDailyRecord, ...],
        *,
        mode: AdjustmentMode,
        database: duckdb.DuckDBPyConnection,
    ) -> None:
        if records:
            security_ids = tuple(sorted({item.raw.security_id for item in records}))
            adjustment_as_of = records[0].adjustment_as_of
            database.execute(
                "DELETE FROM adjusted_daily WHERE mode = ? "
                "AND adjustment_as_of = ? AND security_id IN ("
                + ",".join("?" for _ in security_ids)
                + ")",
                (mode.value, adjustment_as_of, *security_ids),
            )
        for item in records:
            database.execute(
                """
                INSERT INTO adjusted_daily VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    item.mode.value,
                    item.raw.exchange.value,
                    item.raw.trading_date,
                    item.raw.security_id,
                    item.raw.symbol_as_traded,
                    item.open,
                    item.high,
                    item.low,
                    item.close,
                    item.volume,
                    item.adjustment_policy_version,
                    item.corporate_action_version,
                    item.cumulative_price_factor,
                    item.cumulative_volume_factor,
                    item.adjustment_as_of,
                    json.dumps(item.source_event_ids),
                    item.raw.source_file_id,
                    item.raw.dataset_version,
                ),
            )

    def adjusted_records(
        self, mode: AdjustmentMode, *, as_of: date | None = None
    ) -> tuple[AdjustedDailyRecord, ...]:
        with self.connection() as database:
            if as_of is None:
                rows = database.execute(
                    """
                    SELECT * FROM adjusted_daily WHERE mode = ?
                    QUALIFY adjustment_as_of = MAX(adjustment_as_of) OVER ()
                    ORDER BY security_id, trading_date
                    """,
                    (mode.value,),
                ).fetchall()
            else:
                rows = database.execute(
                    "SELECT * FROM adjusted_daily "
                    "WHERE mode = ? AND adjustment_as_of = ? "
                    "ORDER BY security_id, trading_date",
                    (mode.value, as_of),
                ).fetchall()
        raw_by_key = {
            (item.exchange.value, item.trading_date, item.security_id): item
            for item in self.daily_records()
        }
        output: list[AdjustedDailyRecord] = []
        for row in rows:
            raw = raw_by_key[(str(row[1]), cast(date, row[2]), str(row[3]))]
            output.append(
                AdjustedDailyRecord(
                    raw=raw,
                    open=_decimal(row[5]),
                    high=_decimal(row[6]),
                    low=_decimal(row[7]),
                    close=_decimal(row[8]),
                    volume=_decimal(row[9]),
                    adjustment_policy_version=str(row[10]),
                    corporate_action_version=str(row[11]),
                    cumulative_price_factor=_decimal(row[12]),
                    cumulative_volume_factor=_decimal(row[13]),
                    adjustment_as_of=cast(date, row[14]),
                    source_event_ids=tuple(json.loads(str(row[15]))),
                    mode=AdjustmentMode(str(row[0])),
                )
            )
        return tuple(output)

    def replace_aggregates(
        self,
        records: tuple[AggregateBar, ...],
        *,
        period: AggregatePeriod,
        database: duckdb.DuckDBPyConnection,
    ) -> None:
        database.execute("DELETE FROM aggregate_bars WHERE period = ?", (period.value,))
        for item in records:
            database.execute(
                """
                INSERT INTO aggregate_bars VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    item.period.value,
                    item.exchange.value,
                    item.security_id,
                    item.symbol,
                    item.period_start,
                    item.period_end,
                    item.first_trading_date,
                    item.last_trading_date,
                    item.open,
                    item.high,
                    item.low,
                    item.close,
                    item.volume,
                    item.turnover,
                    item.trade_count,
                    item.vwap,
                    item.session_count,
                    item.expected_session_count,
                    item.completeness,
                    item.source_daily_version,
                    item.adjustment_policy_version,
                ),
            )

    def replace_universe(
        self,
        records: tuple[UniverseMembership, ...],
        *,
        session_date: date,
        exchange: Exchange,
        database: duckdb.DuckDBPyConnection,
    ) -> None:
        database.execute(
            "DELETE FROM universe_snapshots WHERE trading_date = ? AND exchange = ?",
            (session_date, exchange.value),
        )
        for item in records:
            database.execute(
                "INSERT INTO universe_snapshots VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item.trading_date,
                    item.exchange.value,
                    item.security_id,
                    item.symbol,
                    item.series,
                    item.listed,
                    item.suspended,
                    item.tradable,
                    item.eligible_for_research,
                    item.eligibility_reason,
                    item.identity_version,
                    item.universe_version,
                ),
            )

    def universe(self, *, session_date: date) -> tuple[UniverseMembership, ...]:
        with self.connection() as database:
            rows = database.execute(
                "SELECT * FROM universe_snapshots WHERE trading_date = ? "
                "ORDER BY exchange, symbol",
                (session_date,),
            ).fetchall()
        return tuple(_universe(row) for row in rows)

    def upsert_sessions(
        self,
        records: tuple[SessionInventoryRecord, ...],
        *,
        database: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        if database is None:
            with self.transaction() as active:
                self.upsert_sessions(records, database=active)
            return
        for item in records:
            database.execute(
                """
                INSERT INTO session_inventory VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (exchange, session_date) DO UPDATE SET
                    state = excluded.state,
                    source_file_id = excluded.source_file_id,
                    reason = excluded.reason
                """,
                (
                    item.exchange.value,
                    item.session_date,
                    item.state.value,
                    item.source_file_id,
                    item.reason,
                ),
            )

    def sessions(
        self,
        *,
        exchange: Exchange | None = None,
        states: tuple[SessionState, ...] = (),
    ) -> tuple[SessionInventoryRecord, ...]:
        where = ["1 = 1"]
        parameters: list[object] = []
        if exchange is not None:
            where.append("exchange = ?")
            parameters.append(exchange.value)
        if states:
            where.append("state IN (" + ",".join("?" for _ in states) + ")")
            parameters.extend(item.value for item in states)
        with self.connection() as database:
            rows = database.execute(
                "SELECT * FROM session_inventory "
                f"WHERE {' AND '.join(where)} ORDER BY exchange, session_date",
                tuple(parameters),
            ).fetchall()
        return tuple(
            SessionInventoryRecord(
                exchange=Exchange(str(row[0])),
                session_date=cast(date, row[1]),
                state=SessionState(str(row[2])),
                source_file_id=None if row[3] is None else str(row[3]),
                reason=str(row[4]),
            )
            for row in rows
        )

    def record_version(self, version: DatasetVersion) -> None:
        with self.transaction() as database:
            database.execute(
                """
                INSERT INTO dataset_versions VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                ) ON CONFLICT (version) DO NOTHING
                """,
                (
                    version.version,
                    version.raw_manifest_hash,
                    version.session_range_start,
                    version.session_range_end,
                    json.dumps([item.value for item in version.exchange_coverage]),
                    version.security_count,
                    version.record_count,
                    version.identity_version,
                    version.corporate_action_version,
                    version.adjustment_policy_version,
                    version.quality_report_hash,
                    version.build_timestamp,
                    version.code_commit,
                    version.parent_version,
                ),
            )

    def latest_version(self) -> str | None:
        with self.connection() as database:
            row = database.execute(
                "SELECT version FROM dataset_versions "
                "ORDER BY build_timestamp DESC LIMIT 1"
            ).fetchone()
        return None if row is None else str(row[0])

    def record_publication(self, *, version: str, path: str) -> None:
        with self.transaction() as database:
            database.execute(
                """
                INSERT INTO warehouse_publications VALUES (?, ?, ?)
                ON CONFLICT (version) DO NOTHING
                """,
                (version, path, datetime.now(tz=UTC)),
            )

    def latest_published_version(self) -> str | None:
        with self.connection() as database:
            row = database.execute(
                "SELECT version FROM warehouse_publications "
                "ORDER BY published_at DESC, version DESC LIMIT 1"
            ).fetchone()
        return None if row is None else str(row[0])

    def status(self) -> WarehouseStatus:
        with self.connection() as database:
            counts: dict[str, int] = {}
            for table in (
                "source_files",
                "canonical_daily",
                "identity_history",
                "corporate_actions",
                "adjusted_daily",
                "aggregate_bars",
                "universe_snapshots",
                "quarantine",
            ):
                row = database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                counts[table] = 0 if row is None else int(str(row[0]))
            validated_row = database.execute(
                "SELECT COUNT(*) FROM source_files "
                "WHERE ingestion_status IN ('VALIDATED', 'PARTIAL')"
            ).fetchone()
            validated = 0 if validated_row is None else int(str(validated_row[0]))
        return WarehouseStatus(
            source_files=counts["source_files"],
            validated_source_files=validated,
            daily_records=counts["canonical_daily"],
            identity_records=counts["identity_history"],
            corporate_actions=counts["corporate_actions"],
            adjusted_records=counts["adjusted_daily"],
            aggregate_records=counts["aggregate_bars"],
            universe_records=counts["universe_snapshots"],
            quarantined_records=counts["quarantine"],
            latest_version=self.latest_version(),
            latest_published_version=self.latest_published_version(),
        )

    def _initialise(self) -> None:
        with self.connection() as database:
            database.execute(_SCHEMA)
            database.execute(
                "ALTER TABLE index_daily_history "
                "ADD COLUMN IF NOT EXISTS volume DECIMAL(30,4)"
            )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_files (
    source_file_id VARCHAR PRIMARY KEY, provider VARCHAR NOT NULL,
    dataset_type VARCHAR NOT NULL, exchange VARCHAR NOT NULL, trading_date DATE,
    publication_timestamp TIMESTAMPTZ, retrieval_timestamp TIMESTAMPTZ NOT NULL,
    original_filename VARCHAR NOT NULL, content_type VARCHAR NOT NULL,
    file_size BIGINT NOT NULL, sha256 VARCHAR NOT NULL UNIQUE,
    schema_fingerprint VARCHAR NOT NULL, authorisation_record_id VARCHAR NOT NULL,
    ingestion_status VARCHAR NOT NULL, vault_path VARCHAR NOT NULL,
    supersedes_file_id VARCHAR
);
CREATE TABLE IF NOT EXISTS ingestion_journal (
    journal_id VARCHAR PRIMARY KEY, source_file_id VARCHAR NOT NULL UNIQUE,
    started_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
    status VARCHAR NOT NULL, accepted_records BIGINT NOT NULL,
    rejected_records BIGINT NOT NULL, duplicate_records BIGINT NOT NULL,
    reasons JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS canonical_daily_history (
    exchange VARCHAR NOT NULL, trading_date DATE NOT NULL, security_id VARCHAR NOT NULL,
    symbol_as_traded VARCHAR NOT NULL, series VARCHAR, isin VARCHAR,
    open DECIMAL(24,8) NOT NULL, high DECIMAL(24,8) NOT NULL,
    low DECIMAL(24,8) NOT NULL, close DECIMAL(24,8) NOT NULL,
    last_price DECIMAL(24,8), previous_close DECIMAL(24,8),
    volume DECIMAL(30,4) NOT NULL, turnover DECIMAL(30,4), trade_count BIGINT,
    vwap DECIMAL(24,8), deliverable_quantity DECIMAL(30,4),
    deliverable_percentage DECIMAL(12,6), upper_price_band DECIMAL(24,8),
    lower_price_band DECIMAL(24,8), source_file_id VARCHAR NOT NULL,
    record_checksum VARCHAR NOT NULL, quality_state VARCHAR NOT NULL,
    confidence DECIMAL(8,4) NOT NULL, dataset_version VARCHAR NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL, partition_year INTEGER NOT NULL,
    PRIMARY KEY (exchange, trading_date, security_id, source_file_id)
);
CREATE OR REPLACE VIEW canonical_daily AS
SELECT h.* FROM canonical_daily_history h
JOIN source_files s USING (source_file_id)
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY h.exchange, h.trading_date, h.security_id
    ORDER BY s.retrieval_timestamp DESC, h.source_file_id DESC
) = 1;
CREATE TABLE IF NOT EXISTS identity_history (
    exchange VARCHAR NOT NULL, security_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL,
    series VARCHAR, isin VARCHAR, company_name VARCHAR, instrument_type VARCHAR,
    listing_date DATE, delisting_date DATE, suspension_intervals JSON NOT NULL,
    relisting_intervals JSON NOT NULL, symbol_valid_from DATE NOT NULL,
    symbol_valid_to DATE, series_valid_from DATE NOT NULL, series_valid_to DATE,
    identity_authority VARCHAR NOT NULL, identity_confidence DECIMAL(8,4) NOT NULL,
    source_file_id VARCHAR NOT NULL, ingested_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (exchange, security_id, symbol, symbol_valid_from, source_file_id)
);
CREATE TABLE IF NOT EXISTS corporate_actions (
    corporate_action_id VARCHAR PRIMARY KEY, security_id VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL, action_type VARCHAR NOT NULL,
    announcement_date DATE NOT NULL, ex_date DATE, record_date DATE,
    effective_date DATE, payment_date DATE, ratio_numerator DECIMAL(24,8),
    ratio_denominator DECIMAL(24,8), cash_amount DECIMAL(24,8), currency VARCHAR,
    old_symbol VARCHAR, new_symbol VARCHAR, old_isin VARCHAR, new_isin VARCHAR,
    source_file_id VARCHAR NOT NULL, raw_terms VARCHAR NOT NULL,
    normalised_terms VARCHAR NOT NULL, evidence_class VARCHAR NOT NULL,
    confidence DECIMAL(8,4) NOT NULL, reconciliation_status VARCHAR NOT NULL,
    adjustment_status VARCHAR NOT NULL, version VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS index_daily_history (
    exchange VARCHAR NOT NULL, index_id VARCHAR NOT NULL, index_name VARCHAR NOT NULL,
    trading_date DATE NOT NULL, open DECIMAL(24,8), high DECIMAL(24,8),
    low DECIMAL(24,8), close DECIMAL(24,8) NOT NULL, volume DECIMAL(30,4),
    source_file_id VARCHAR NOT NULL,
    dataset_version VARCHAR NOT NULL, ingested_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (exchange, index_id, trading_date, source_file_id)
);
CREATE TABLE IF NOT EXISTS deliverable_history (
    exchange VARCHAR NOT NULL, trading_date DATE NOT NULL,
    security_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL, series VARCHAR,
    deliverable_quantity DECIMAL(30,4), deliverable_percentage DECIMAL(12,6),
    source_file_id VARCHAR NOT NULL, ingested_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (exchange, security_id, trading_date, source_file_id)
);
CREATE TABLE IF NOT EXISTS adjusted_daily (
    mode VARCHAR NOT NULL, exchange VARCHAR NOT NULL, trading_date DATE NOT NULL,
    security_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL,
    open DECIMAL(24,8) NOT NULL, high DECIMAL(24,8) NOT NULL,
    low DECIMAL(24,8) NOT NULL, close DECIMAL(24,8) NOT NULL,
    volume DECIMAL(30,4) NOT NULL, adjustment_policy_version VARCHAR NOT NULL,
    corporate_action_version VARCHAR NOT NULL,
    cumulative_price_factor DECIMAL(30,12) NOT NULL,
    cumulative_volume_factor DECIMAL(30,12) NOT NULL, adjustment_as_of DATE NOT NULL,
    source_event_ids JSON NOT NULL, source_file_id VARCHAR NOT NULL,
    source_daily_version VARCHAR NOT NULL,
    PRIMARY KEY (mode, exchange, trading_date, security_id, adjustment_as_of)
);
CREATE TABLE IF NOT EXISTS aggregate_bars (
    period VARCHAR NOT NULL, exchange VARCHAR NOT NULL, security_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL,
    first_trading_date DATE NOT NULL, last_trading_date DATE NOT NULL,
    open DECIMAL(24,8) NOT NULL, high DECIMAL(24,8) NOT NULL,
    low DECIMAL(24,8) NOT NULL, close DECIMAL(24,8) NOT NULL,
    volume DECIMAL(30,4) NOT NULL, turnover DECIMAL(30,4), trade_count BIGINT,
    vwap DECIMAL(24,8), session_count INTEGER NOT NULL,
    expected_session_count INTEGER NOT NULL, completeness DECIMAL(12,8) NOT NULL,
    source_daily_version VARCHAR NOT NULL, adjustment_policy_version VARCHAR NOT NULL,
    PRIMARY KEY (period, exchange, security_id, period_start, adjustment_policy_version)
);
CREATE TABLE IF NOT EXISTS universe_snapshots (
    trading_date DATE NOT NULL, exchange VARCHAR NOT NULL, security_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL, series VARCHAR, listed BOOLEAN NOT NULL,
    suspended BOOLEAN NOT NULL, tradable BOOLEAN NOT NULL,
    eligible_for_research BOOLEAN NOT NULL, eligibility_reason VARCHAR NOT NULL,
    identity_version VARCHAR NOT NULL, universe_version VARCHAR NOT NULL,
    PRIMARY KEY (trading_date, exchange, security_id)
);
CREATE TABLE IF NOT EXISTS session_inventory (
    exchange VARCHAR NOT NULL, session_date DATE NOT NULL, state VARCHAR NOT NULL,
    source_file_id VARCHAR, reason VARCHAR NOT NULL,
    PRIMARY KEY (exchange, session_date)
);
CREATE TABLE IF NOT EXISTS quarantine (
    quarantine_id VARCHAR PRIMARY KEY, source_file_id VARCHAR NOT NULL,
    record_type VARCHAR NOT NULL, record_key VARCHAR NOT NULL,
    raw_payload VARCHAR NOT NULL, reason VARCHAR NOT NULL,
    quarantined_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_versions (
    version VARCHAR PRIMARY KEY, raw_manifest_hash VARCHAR NOT NULL,
    session_range_start DATE, session_range_end DATE, exchange_coverage JSON NOT NULL,
    security_count BIGINT NOT NULL, record_count BIGINT NOT NULL,
    identity_version VARCHAR NOT NULL, corporate_action_version VARCHAR NOT NULL,
    adjustment_policy_version VARCHAR NOT NULL, quality_report_hash VARCHAR NOT NULL,
    build_timestamp TIMESTAMPTZ NOT NULL, code_commit VARCHAR, parent_version VARCHAR
);
CREATE TABLE IF NOT EXISTS warehouse_publications (
    version VARCHAR PRIMARY KEY, publication_path VARCHAR NOT NULL,
    published_at TIMESTAMPTZ NOT NULL
);
"""


def _source_file(row: tuple[object, ...]) -> SourceFileRecord:
    from alpha.market_truth.warehouse.models import WarehouseDataset

    return SourceFileRecord(
        source_file_id=str(row[0]),
        provider=str(row[1]),
        dataset_type=WarehouseDataset(str(row[2])),
        exchange=Exchange(str(row[3])),
        trading_date=cast(date | None, row[4]),
        publication_timestamp=cast(datetime | None, row[5]),
        retrieval_timestamp=cast(datetime, row[6]),
        original_filename=str(row[7]),
        content_type=str(row[8]),
        file_size=int(str(row[9])),
        sha256=str(row[10]),
        schema_fingerprint=str(row[11]),
        authorisation_record_id=str(row[12]),
        ingestion_status=IngestionStatus(str(row[13])),
        vault_path=str(row[14]),
        supersedes_file_id=None if row[15] is None else str(row[15]),
    )


def _daily(row: tuple[object, ...]) -> CanonicalDailyRecord:
    return CanonicalDailyRecord(
        exchange=Exchange(str(row[0])),
        trading_date=cast(date, row[1]),
        security_id=str(row[2]),
        symbol_as_traded=str(row[3]),
        series=None if row[4] is None else str(row[4]),
        isin=None if row[5] is None else str(row[5]),
        open=_decimal(row[6]),
        high=_decimal(row[7]),
        low=_decimal(row[8]),
        close=_decimal(row[9]),
        last_price=None if row[10] is None else _decimal(row[10]),
        previous_close=None if row[11] is None else _decimal(row[11]),
        volume=_decimal(row[12]),
        turnover=None if row[13] is None else _decimal(row[13]),
        trade_count=None if row[14] is None else int(str(row[14])),
        vwap=None if row[15] is None else _decimal(row[15]),
        deliverable_quantity=None if row[16] is None else _decimal(row[16]),
        deliverable_percentage=None if row[17] is None else _decimal(row[17]),
        upper_price_band=None if row[18] is None else _decimal(row[18]),
        lower_price_band=None if row[19] is None else _decimal(row[19]),
        source_file_id=str(row[20]),
        quality_state=WarehouseQualityState(str(row[22])),
        confidence=_decimal(row[23]),
        dataset_version=str(row[24]),
    )


def _identity(row: tuple[object, ...]) -> IdentityRecord:
    return IdentityRecord(
        exchange=Exchange(str(row[0])),
        security_id=str(row[1]),
        symbol=str(row[2]),
        series=None if row[3] is None else str(row[3]),
        isin=None if row[4] is None else str(row[4]),
        company_name=None if row[5] is None else str(row[5]),
        instrument_type=None if row[6] is None else str(row[6]),
        listing_date=cast(date | None, row[7]),
        delisting_date=cast(date | None, row[8]),
        suspension_intervals=_intervals(row[9]),
        relisting_intervals=_intervals(row[10]),
        symbol_valid_from=cast(date, row[11]),
        symbol_valid_to=cast(date | None, row[12]),
        series_valid_from=cast(date, row[13]),
        series_valid_to=cast(date | None, row[14]),
        identity_authority=str(row[15]),
        identity_confidence=_decimal(row[16]),
        source_file_id=str(row[17]),
    )


def _corporate_action(row: tuple[object, ...]) -> CorporateActionRecord:
    return CorporateActionRecord(
        corporate_action_id=str(row[0]),
        security_id=str(row[1]),
        exchange=Exchange(str(row[2])),
        action_type=CorporateActionKind(str(row[3])),
        announcement_date=cast(date, row[4]),
        ex_date=cast(date | None, row[5]),
        record_date=cast(date | None, row[6]),
        effective_date=cast(date | None, row[7]),
        payment_date=cast(date | None, row[8]),
        ratio_numerator=None if row[9] is None else _decimal(row[9]),
        ratio_denominator=None if row[10] is None else _decimal(row[10]),
        cash_amount=None if row[11] is None else _decimal(row[11]),
        currency=None if row[12] is None else str(row[12]),
        old_symbol=None if row[13] is None else str(row[13]),
        new_symbol=None if row[14] is None else str(row[14]),
        old_isin=None if row[15] is None else str(row[15]),
        new_isin=None if row[16] is None else str(row[16]),
        source_file_id=str(row[17]),
        raw_terms=str(row[18]),
        normalised_terms=str(row[19]),
        evidence_class=str(row[20]),
        confidence=_decimal(row[21]),
        reconciliation_status=ReconciliationStatus(str(row[22])),
        adjustment_status=AdjustmentStatus(str(row[23])),
        version=str(row[24]),
    )


def _universe(row: tuple[object, ...]) -> UniverseMembership:
    return UniverseMembership(
        trading_date=cast(date, row[0]),
        exchange=Exchange(str(row[1])),
        security_id=str(row[2]),
        symbol=str(row[3]),
        series=None if row[4] is None else str(row[4]),
        listed=bool(row[5]),
        suspended=bool(row[6]),
        tradable=bool(row[7]),
        eligible_for_research=bool(row[8]),
        eligibility_reason=str(row[9]),
        identity_version=str(row[10]),
        universe_version=str(row[11]),
    )


def _intervals(value: object) -> tuple[tuple[date, date | None], ...]:
    payload = json.loads(str(value))
    return tuple(
        (
            date.fromisoformat(str(start)),
            None if end is None else date.fromisoformat(str(end)),
        )
        for start, end in payload
    )


def _hash(value: str) -> str:
    from hashlib import sha256

    return sha256(value.encode()).hexdigest()


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


__all__ = ["WarehouseStore"]
