from __future__ import annotations

from pathlib import Path

import duckdb

from alpha.market_truth.warehouse.models import ReconciliationReport
from alpha.market_truth.warehouse.storage import WarehouseStore


class CurrentStoreReconciler:
    """Compare legacy canonical data in DuckDB without loading it into memory."""

    def __init__(self, warehouse: WarehouseStore) -> None:
        self.warehouse = warehouse

    def reconcile(self, current_database: Path) -> ReconciliationReport:
        if not current_database.exists():
            return _empty()
        database = duckdb.connect(str(current_database), read_only=True)
        try:
            tables = {str(row[0]) for row in database.execute("SHOW TABLES").fetchall()}
            if "daily_prices" not in tables:
                return _empty()
            warehouse_path = str(self.warehouse.paths.database).replace("'", "''")
            database.execute(f"ATTACH '{warehouse_path}' AS authoritative (READ_ONLY)")
            current_sessions = _count(
                database,
                "SELECT COUNT(DISTINCT trade_date) FROM daily_prices",
            )
            warehouse_sessions = _count(
                database,
                "SELECT COUNT(DISTINCT trading_date) "
                "FROM authoritative.canonical_daily",
            )
            current_symbols = _count(
                database,
                "SELECT COUNT(*) FROM (SELECT DISTINCT UPPER(exchange), "
                "UPPER(symbol) FROM daily_prices)",
            )
            warehouse_symbols = _count(
                database,
                "SELECT COUNT(*) FROM (SELECT DISTINCT exchange, "
                "symbol_as_traded FROM authoritative.canonical_daily)",
            )
            session_overlap = _count(database, _SESSION_OVERLAP)
            symbol_overlap = _count(database, _SYMBOL_OVERLAP)
            compared = _count(database, _COMPARED)
            matching = _count(database, _MATCHING)
            differences = compared - matching
            affected = _count(database, _ACTION_AFFECTED)
            identity_differences = _count(database, _IDENTITY_DIFFERENCES)
            return ReconciliationReport(
                current_sessions=current_sessions,
                warehouse_sessions=warehouse_sessions,
                overlapping_sessions=session_overlap,
                missing_sessions=current_sessions - session_overlap,
                extra_sessions=warehouse_sessions - session_overlap,
                current_symbols=current_symbols,
                warehouse_symbols=warehouse_symbols,
                symbol_overlap=symbol_overlap,
                compared_rows=compared,
                matching_rows=matching,
                ohlcv_differences=differences,
                identity_differences=identity_differences,
                corporate_action_affected_differences=affected,
                unexplained_differences=max(0, differences - affected),
                quarantine_candidates=max(0, differences - affected),
            )
        finally:
            database.close()


_JOIN = """
FROM daily_prices c
JOIN authoritative.canonical_daily w
  ON UPPER(c.exchange) = w.exchange
 AND UPPER(c.symbol) = w.symbol_as_traded
 AND c.trade_date = w.trading_date
"""

_DIFFERENCE = """
(
    ABS(c.open - CAST(w.open AS DOUBLE)) > 0.0001 OR
    ABS(c.high - CAST(w.high AS DOUBLE)) > 0.0001 OR
    ABS(c.low - CAST(w.low AS DOUBLE)) > 0.0001 OR
    ABS(c.close - CAST(w.close AS DOUBLE)) > 0.0001 OR
    ABS(c.volume - CAST(w.volume AS DOUBLE)) > 0.0001
)
"""

_SESSION_OVERLAP = """
SELECT COUNT(*) FROM (
    SELECT DISTINCT c.trade_date
    FROM daily_prices c
    JOIN authoritative.canonical_daily w ON c.trade_date = w.trading_date
)
"""

_SYMBOL_OVERLAP = """
SELECT COUNT(*) FROM (
    SELECT DISTINCT UPPER(c.exchange), UPPER(c.symbol)
    FROM daily_prices c
    JOIN authoritative.canonical_daily w
      ON UPPER(c.exchange) = w.exchange
     AND UPPER(c.symbol) = w.symbol_as_traded
)
"""

_COMPARED = "SELECT COUNT(*) " + _JOIN
_MATCHING = "SELECT COUNT(*) " + _JOIN + " WHERE NOT " + _DIFFERENCE

_ACTION_AFFECTED = (
    "SELECT COUNT(DISTINCT (w.exchange, w.security_id, w.trading_date)) "
    + _JOIN
    + " JOIN authoritative.corporate_actions a ON a.security_id = w.security_id "
    "AND a.ex_date IS NOT NULL "
    "AND ABS(DATE_DIFF('day', a.ex_date, w.trading_date)) <= 2 "
    "WHERE " + _DIFFERENCE
)

_IDENTITY_DIFFERENCES = """
SELECT COUNT(*) FROM (
    SELECT DISTINCT w.exchange, w.symbol_as_traded
    FROM authoritative.canonical_daily w
    LEFT JOIN authoritative.identity_history i
      ON i.exchange = w.exchange
     AND i.symbol = w.symbol_as_traded
     AND i.symbol_valid_from <= w.trading_date
     AND (i.symbol_valid_to IS NULL OR i.symbol_valid_to >= w.trading_date)
    WHERE i.security_id IS NULL
)
"""


def _count(database: duckdb.DuckDBPyConnection, query: str) -> int:
    row = database.execute(query).fetchone()
    return 0 if row is None else int(str(row[0]))


def _empty() -> ReconciliationReport:
    return ReconciliationReport(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


__all__ = ["CurrentStoreReconciler"]
