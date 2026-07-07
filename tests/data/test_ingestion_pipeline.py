import zipfile
from pathlib import Path

from alpha.data.ingestion.pipeline import BhavcopyIngestionPipeline
from alpha.data.repositories.database import Database
from alpha.data.repositories.prices import PricesRepository


def _write_bhavcopy_fixture(zip_path: Path) -> None:
    csv_name = "cm10JUN2024bhav.csv"
    header = (
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,"
        "TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN\n"
    )
    rows = (
        "RELIANCE,EQ,2900.00,2925.00,2880.00,2910.00,2911.00,"
        "2895.00,100000,291000000.00,10-JUN-2024,1000,INE002A01018\n"
        "TCS,EQ,3800.00,3840.00,3780.00,3825.00,3824.00,"
        "3790.00,50000,191250000.00,10-JUN-2024,800,INE467B01029\n"
        "INFY,EQ,1450.00,1475.00,1435.00,1460.00,1461.00,"
        "1445.00,75000,109500000.00,10-JUN-2024,900,INE009A01021\n"
        "RELIANCE,EQ,2900.00,2925.00,2880.00,2910.00,2911.00,"
        "2895.00,100000,291000000.00,10-JUN-2024,1000,INE002A01018\n"
    )

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(csv_name, header + rows)


def test_ingestion_pipeline_runs_end_to_end(tmp_path: Path) -> None:
    """
    Verify the complete ingestion pipeline can:

    - extract a bhavcopy archive
    - load it
    - normalize it
    - validate it
    - persist unique rows

    The test creates its own fixture ZIP under tmp_path so it does not depend on
    data/raw, developer-local downloads, or any runtime cache.
    """

    db_path = tmp_path / "test_ingestion.duckdb"
    zip_path = tmp_path / "bhavcopy_2024-06-10.zip"

    _write_bhavcopy_fixture(zip_path)

    db = Database(str(db_path))
    pipeline = BhavcopyIngestionPipeline(db)

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
