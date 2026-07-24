from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from alpha.canonical_universe_audit.models import DatasetManifest

_PRICE_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "sector",
    "exchange",
)


class LegacyMarketDataStore:
    """Read-only access to the frozen legacy DuckDB population."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"legacy market database not found: {self.path}")
        self.connection = duckdb.connect(str(self.path), read_only=True)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> LegacyMarketDataStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def manifest(self) -> DatasetManifest:
        row = self.connection.execute(
            """
            SELECT
                COUNT(*) AS row_count,
                COUNT(DISTINCT symbol) AS symbol_count,
                COUNT(DISTINCT trade_date) AS session_count,
                MIN(trade_date) AS first_session,
                MAX(trade_date) AS last_session,
                COUNT(sector) AS sector_rows,
                STRING_AGG(DISTINCT exchange, ', ' ORDER BY exchange) AS exchanges
            FROM daily_prices
            """
        ).fetchone()
        if row is None or row[3] is None or row[4] is None:
            raise ValueError("legacy daily_prices population is empty")
        return DatasetManifest(
            dataset_version="LEGACY_DATASET",
            first_session=row[3],
            last_session=row[4],
            sessions=int(row[2]),
            rows=int(row[0]),
            symbols=int(row[1]),
            exchange=str(row[6]),
            sector_rows=int(row[5]),
        )

    def trade_dates(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[date, ...]:
        first = start or date.min
        last = end or date.max
        rows = self.connection.execute(
            """
            SELECT DISTINCT trade_date
            FROM daily_prices
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            (first, last),
        ).fetchall()
        return tuple(row[0] for row in rows)

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        result = self.connection.execute(
            """
            SELECT symbol, trade_date, open, high, low, close, volume, sector, exchange
            FROM daily_prices
            WHERE trade_date = ?
              AND open > 0
              AND high > 0
              AND low > 0
              AND close > 0
              AND volume >= 0
            ORDER BY symbol
            """,
            (trade_date,),
        )
        return result.fetchdf()

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        normalized = tuple(
            dict.fromkeys(
                symbol.strip().upper() for symbol in symbols if symbol.strip()
            )
        )
        if not normalized:
            return pd.DataFrame(columns=_PRICE_COLUMNS)
        if limit < 1:
            raise ValueError("history limit must be positive")
        placeholders = ", ".join("?" for _ in normalized)
        result = self.connection.execute(
            f"""
            WITH ranked AS (
                SELECT
                    symbol, trade_date, open, high, low, close, volume, sector,
                    exchange,
                    ROW_NUMBER() OVER (
                        PARTITION BY symbol ORDER BY trade_date DESC
                    ) AS row_number
                FROM daily_prices
                WHERE UPPER(symbol) IN ({placeholders})
                  AND trade_date <= ?
                  AND open > 0
                  AND high > 0
                  AND low > 0
                  AND close > 0
                  AND volume >= 0
            )
            SELECT symbol, trade_date, open, high, low, close, volume, sector, exchange
            FROM ranked
            WHERE row_number <= ?
            ORDER BY symbol, trade_date
            """,
            (*normalized, end_date, limit),
        )
        return result.fetchdf()

    def history_counts_before(self, observed_on: date) -> dict[str, int]:
        rows = self.connection.execute(
            """
            SELECT UPPER(symbol), COUNT(*)
            FROM daily_prices
            WHERE trade_date < ?
              AND open > 0
              AND high > 0
              AND low > 0
              AND close > 0
              AND volume >= 0
            GROUP BY UPPER(symbol)
            """,
            (observed_on,),
        ).fetchall()
        return {str(symbol): int(count) for symbol, count in rows}

    def eligible_security_count(
        self,
        *,
        start: date,
        end: date,
        minimum_history: int = 200,
    ) -> int:
        """Count observed securities meeting the governed history requirement."""

        if end < start:
            raise ValueError("eligibility range end cannot precede start")
        if minimum_history < 1:
            raise ValueError("minimum history must be positive")

        row = self.connection.execute(
            """
            WITH history AS (
                SELECT UPPER(symbol) AS symbol, COUNT(*) AS observations
                FROM daily_prices
                WHERE trade_date <= ?
                  AND open > 0
                  AND high > 0
                  AND low > 0
                  AND close > 0
                  AND volume >= 0
                GROUP BY UPPER(symbol)
                HAVING COUNT(*) >= ?
            ), observed AS (
                SELECT DISTINCT UPPER(symbol) AS symbol
                FROM daily_prices
                WHERE trade_date BETWEEN ? AND ?
            )
            SELECT COUNT(*)
            FROM history
            JOIN observed USING (symbol)
            """,
            (end, minimum_history, start, end),
        ).fetchone()

        return 0 if row is None else int(row[0])

    def liquidity_statistics(self) -> pd.DataFrame:
        return self.connection.execute(
            """
            SELECT
                UPPER(symbol) AS symbol,
                AVG(CAST(volume AS DOUBLE)) AS average_daily_volume,
                AVG(close * CAST(volume AS DOUBLE)) AS average_daily_turnover,
                COUNT(*) AS sessions,
                MIN(trade_date) AS first_session,
                MAX(trade_date) AS last_session
            FROM daily_prices
            WHERE close > 0 AND volume >= 0
            GROUP BY UPPER(symbol)
            ORDER BY symbol
            """
        ).fetchdf()

    def future_bars(self, candidates: pd.DataFrame, *, limit: int) -> pd.DataFrame:
        required = {"candidate_id", "symbol", "observed_on"}
        if not required.issubset(candidates.columns):
            raise ValueError("future-bar candidates require id, symbol, and date")
        if candidates.empty:
            return pd.DataFrame(columns=("candidate_id", *_PRICE_COLUMNS))
        if limit < 1:
            raise ValueError("future-bar limit must be positive")
        self.connection.register("_acu_candidates", candidates)
        try:
            return self.connection.execute(
                """
                WITH matched AS (
                    SELECT
                        candidates.candidate_id,
                        prices.symbol,
                        prices.trade_date,
                        prices.open,
                        prices.high,
                        prices.low,
                        prices.close,
                        prices.volume,
                        prices.sector,
                        prices.exchange,
                        ROW_NUMBER() OVER (
                            PARTITION BY candidates.candidate_id
                            ORDER BY prices.trade_date
                        ) AS forward_row
                    FROM _acu_candidates AS candidates
                    JOIN daily_prices AS prices
                      ON UPPER(prices.symbol) = UPPER(candidates.symbol)
                     AND prices.trade_date > candidates.observed_on
                    WHERE prices.open > 0
                      AND prices.high > 0
                      AND prices.low > 0
                      AND prices.close > 0
                      AND prices.volume >= 0
                )
                SELECT
                    candidate_id, symbol, trade_date, open, high, low, close,
                    volume, sector, exchange
                FROM matched
                WHERE forward_row <= ?
                ORDER BY candidate_id, trade_date
                """,
                (limit,),
            ).fetchdf()
        finally:
            self.connection.unregister("_acu_candidates")

    def return_history(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int = 60,
    ) -> pd.DataFrame:
        frame = self.find_history_by_symbols(
            symbols=symbols,
            end_date=end_date,
            limit=limit + 1,
        )
        if frame.empty:
            return pd.DataFrame()
        frame = frame.copy()
        frame["return"] = frame.groupby("symbol", sort=False)["close"].pct_change()
        return frame.pivot(index="trade_date", columns="symbol", values="return")


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    return Decimal(str(value))


__all__ = ["LegacyMarketDataStore", "decimal_or_none"]
