from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


class PricesRepository:
    """
    Repository responsible for persisting price data into DuckDB.

    Guarantees schema alignment at the persistence boundary and exposes
    canonical read methods for application services.
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    def insert(self, df: pd.DataFrame) -> None:
        """
        Insert normalized DataFrame into daily_prices table safely.
        """

        df = df.copy()

        df["symbol"] = df["symbol"].astype(str).str.strip()
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

        if "exchange" not in df.columns:
            df["exchange"] = "NSE"
        else:
            df["exchange"] = df["exchange"].fillna("NSE").astype(str).str.strip()

        if "sector" not in df.columns:
            df["sector"] = None
        else:
            df["sector"] = [_normalize_optional_text(value) for value in df["sector"]]

        required_cols = [
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "sector",
            "exchange",
        ]

        missing = [column for column in required_cols if column not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        df = df[required_cols]

        df = df.drop_duplicates(
            subset=["symbol", "trade_date", "exchange"],
            keep="last",
        )

        rows = list(df.itertuples(index=False, name=None))

        self.db.connection.executemany(
            """
            INSERT INTO daily_prices (
                symbol,
                trade_date,
                open,
                high,
                low,
                close,
                volume,
                sector,
                exchange
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        """
        Load canonical prices for a single trading date.

        This read path is used when an archive has already been processed and
        ingestion correctly returns an empty DataFrame for idempotency.
        """

        result = self.db.execute(
            """
            SELECT
                symbol,
                trade_date,
                open,
                high,
                low,
                close,
                volume,
                sector,
                exchange
            FROM daily_prices
            WHERE trade_date = ?
            ORDER BY symbol
            """,
            (trade_date,),
        )

        rows = result.fetchall()
        columns = [
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "sector",
            "exchange",
        ]

        return pd.DataFrame(rows, columns=columns)

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        """
        Load a rolling historical price window for each requested symbol.

        The query deliberately ranks rows per symbol inside DuckDB so callers
        receive up to ``limit`` bars for each symbol, ordered chronologically.
        """

        normalized_symbols = tuple(
            dict.fromkeys(
                symbol.strip().upper() for symbol in symbols if symbol.strip()
            )
        )
        if not normalized_symbols:
            return pd.DataFrame(columns=_PRICE_COLUMNS)
        if limit <= 0:
            raise ValueError("history limit must be positive")

        placeholders = ", ".join("?" for _ in normalized_symbols)
        result = self.db.execute(
            f"""
            WITH ranked_prices AS (
                SELECT
                    symbol,
                    trade_date,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    sector,
                    exchange,
                    ROW_NUMBER() OVER (
                        PARTITION BY symbol
                        ORDER BY trade_date DESC
                    ) AS row_number
                FROM daily_prices
                WHERE UPPER(symbol) IN ({placeholders})
                  AND trade_date <= ?
            )
            SELECT
                symbol,
                trade_date,
                open,
                high,
                low,
                close,
                volume,
                sector,
                exchange
            FROM ranked_prices
            WHERE row_number <= ?
            ORDER BY symbol, trade_date
            """,
            (*normalized_symbols, end_date, limit),
        )

        return pd.DataFrame(result.fetchall(), columns=_PRICE_COLUMNS)

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        """
        Return persisted trading dates inside a calendar window.
        """

        result = self.db.execute(
            """
            SELECT DISTINCT trade_date
            FROM daily_prices
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            (start, end),
        )
        return tuple(row[0] for row in result.fetchall())

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Load chronological prices for symbols between two dates.
        """

        normalized_symbols = tuple(
            dict.fromkeys(
                symbol.strip().upper() for symbol in symbols if symbol.strip()
            )
        )
        if not normalized_symbols:
            return pd.DataFrame(columns=_PRICE_COLUMNS)
        placeholders = ", ".join("?" for _ in normalized_symbols)
        result = self.db.execute(
            f"""
            SELECT
                symbol,
                trade_date,
                open,
                high,
                low,
                close,
                volume,
                sector,
                exchange
            FROM daily_prices
            WHERE UPPER(symbol) IN ({placeholders})
              AND trade_date BETWEEN ? AND ?
            ORDER BY symbol, trade_date
            """,
            (*normalized_symbols, start_date, end_date),
        )
        return pd.DataFrame(result.fetchall(), columns=_PRICE_COLUMNS)


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip().upper()
    if normalized in {"", "NAN", "NONE", "<NA>", "NAT"}:
        return None
    return normalized


_PRICE_COLUMNS = [
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "sector",
    "exchange",
]
