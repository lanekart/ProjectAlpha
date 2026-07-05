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
        Initialize required tables if they do not exist.
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
