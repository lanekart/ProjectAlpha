from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from alpha.historical_truth.complete_security_dataset_engine import (
    CompleteSecurityDatasetCertificationEngine,
)


def test_census_sorts_nullable_isin_without_coercing_or_dropping_it(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            create table daily_candle (
                exchange varchar,
                symbol varchar,
                series varchar,
                isin varchar,
                trading_date date
            )
            """
        )
        connection.executemany(
            "insert into daily_candle values (?, ?, ?, ?, ?)",
            [
                ("NSE", "ALPHA", "EQ", None, date(2005, 1, 4)),
                ("NSE", "ALPHA", "EQ", "INE000A01001", date(2005, 1, 3)),
            ],
        )
        engine = CompleteSecurityDatasetCertificationEngine(
            tmp_path / "unused.duckdb",
            tmp_path,
        )
        records = engine._census(
            connection,
            date(2005, 1, 1),
            date(2005, 12, 31),
        )
    finally:
        connection.close()

    assert [record.isin for record in records] == ["INE000A01001", None]
    assert records[0].identity_key == "nse:isin:INE000A01001"
    assert records[1].isin is None
    assert records[1].candle_rows == 1
    assert "None" not in records[1].identity_key
