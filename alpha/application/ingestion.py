from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from alpha.config import settings
from alpha.data.ingestion.pipeline import BhavcopyIngestionPipeline
from alpha.data.repositories.database import Database
from alpha.data.repositories.prices import PricesRepository


class IngestionService:
    """
    Application service responsible for orchestrating bhavcopy ingestion.
    """

    def __init__(self) -> None:
        self.db = Database(str(settings.database_path))
        self.pipeline = BhavcopyIngestionPipeline(self.db)
        self.prices = PricesRepository(self.db)

    def ingest(self, zip_path: Path) -> pd.DataFrame:
        """
        Execute the complete ingestion workflow.
        """

        df = self.pipeline.run(zip_path)

        if not df.empty:
            self.prices.insert(df)

        return df

    def load_prices_for_trade_date(self, trade_date: date) -> pd.DataFrame:
        """
        Load persisted canonical prices for a trading date.

        This supports idempotent reporting. When an archive has already been
        processed, the ingestion pipeline returns an empty DataFrame to avoid
        duplicate writes. Reporting can then reload the canonical data already
        persisted in DuckDB.
        """

        return self.prices.find_by_trade_date(trade_date)
