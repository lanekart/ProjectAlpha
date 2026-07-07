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

        required_cols = [
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
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
                exchange
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            "exchange",
        ]

        return pd.DataFrame(rows, columns=columns)
