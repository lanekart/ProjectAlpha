from __future__ import annotations

from typing import Any

import duckdb

from alpha.data.schema.audit_schema import AUDIT_TABLE_SQL


class Database:
    """
    Thin wrapper over DuckDB connection.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.connection = duckdb.connect(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        """
        Initialize required tables and migrate legacy local schemas.
        """

        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_prices (
                symbol TEXT,
                trade_date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                exchange TEXT,
                PRIMARY KEY (symbol, trade_date, exchange)
            )
            """
        )

        self.connection.execute(AUDIT_TABLE_SQL)
        self._migrate_audit_schema()

    def _migrate_audit_schema(self) -> None:
        """
        Migrate older ingestion_audit tables in existing local DuckDB files.

        Early development databases may contain only file_name and processed_at.
        Current repositories expect status and error columns. This migration is
        intentionally idempotent and preserves legacy rows as successful audits.
        """

        columns = self._table_columns("ingestion_audit")

        if "status" not in columns:
            self.connection.execute(
                "ALTER TABLE ingestion_audit ADD COLUMN status TEXT"
            )

        if "error" not in columns:
            self.connection.execute("ALTER TABLE ingestion_audit ADD COLUMN error TEXT")

        if "processed_at" not in columns:
            self.connection.execute(
                "ALTER TABLE ingestion_audit ADD COLUMN processed_at TIMESTAMP"
            )

        self.connection.execute(
            """
            UPDATE ingestion_audit
            SET status = 'SUCCESS'
            WHERE status IS NULL
            """
        )
        self.connection.execute(
            """
            UPDATE ingestion_audit
            SET processed_at = CURRENT_TIMESTAMP
            WHERE processed_at IS NULL
            """
        )

    def _table_columns(self, table_name: str) -> set[str]:
        rows = self.connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        return {str(row[1]) for row in rows}

    def execute(self, sql: str, parameters: tuple[Any, ...] | None = None) -> Any:
        """
        Execute a SQL query safely.
        """

        if parameters:
            return self.connection.execute(sql, parameters)
        return self.connection.execute(sql)

    def commit(self) -> None:
        """
        DuckDB auto-commits.
        """
        return None

    def close(self) -> None:
        """
        Close DB connection.
        """
        self.connection.close()
