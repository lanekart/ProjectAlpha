import os
from pathlib import Path

from alpha.data.ingestion.pipeline import BhavcopyIngestionPipeline
from alpha.data.repositories.database import Database
from alpha.data.repositories.prices import PricesRepository


def test_ingestion_pipeline_runs_end_to_end() -> None:
    """
    Verify the complete ingestion pipeline can:

    - extract a bhavcopy
    - load it
    - normalize it
    - validate it
    - persist unique rows
    """

    db_path = "data/test_ingestion.duckdb"

    if os.path.exists(db_path):
        os.remove(db_path)

    db = Database(db_path)

    pipeline = BhavcopyIngestionPipeline(db)

    zip_path = Path("data/raw/bhavcopy_2024-06-10.zip")

    df = pipeline.run(zip_path)

    assert not df.empty

    repo = PricesRepository(db)
    repo.insert(df)

    inserted = db.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]

    expected = (
        df.assign(exchange="NSE")
        .drop_duplicates(
            subset=["symbol", "trade_date", "exchange"],
            keep="last",
        )
        .shape[0]
    )

    assert inserted == expected
