from typing import Any

import pandas as pd


class PricesRepository:
    """
    Repository responsible for persisting price data into DuckDB.
    Guarantees schema alignment at boundary.
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    def insert(self, df: pd.DataFrame) -> None:
        """
        Insert normalized DataFrame into daily_prices table safely.
        """

        df = df.copy()

        # ----------------------------
        # STEP 1: normalize existing columns first
        # ----------------------------
        df["symbol"] = df["symbol"].astype(str).str.strip()
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

        # ----------------------------
        # STEP 2: derive missing required columns
        # ----------------------------
        if "exchange" not in df.columns:
            df["exchange"] = "NSE"
        else:
            df["exchange"] = df["exchange"].fillna("NSE").astype(str).str.strip()

        # ----------------------------
        # STEP 3: define required schema AFTER enrichment
        # ----------------------------
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

        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        df = df[required_cols]

        # ----------------------------
        # STEP 4: enforce uniqueness
        # ----------------------------
        df = df.drop_duplicates(
            subset=["symbol", "trade_date", "exchange"],
            keep="last",
        )

        # ----------------------------
        # STEP 5: insert
        # ----------------------------
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
