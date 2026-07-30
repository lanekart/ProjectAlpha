from __future__ import annotations

from datetime import date

import duckdb

from alpha.historical_truth.point_in_time_identity_engine import (
    PointInTimeIdentityCertificationEngine,
)
from alpha.historical_truth.point_in_time_identity_models import IdentityState


def test_symbol_reuse_ignores_null_isin_rows_without_losing_conflict() -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            create table scoped_candle (
                symbol varchar,
                series varchar,
                isin varchar,
                trading_date date
            )
            """
        )
        connection.executemany(
            "insert into scoped_candle values (?, ?, ?, ?)",
            [
                ("REUSED", "EQ", "INE000A01001", date(2005, 1, 3)),
                ("REUSED", "EQ", None, date(2005, 1, 4)),
                ("REUSED", "EQ", "INE000B01002", date(2006, 1, 3)),
            ],
        )
        records = PointInTimeIdentityCertificationEngine._symbol_reuse(connection)
    finally:
        connection.close()

    assert len(records) == 1
    record = records[0]
    assert record.involved_isins == ("INE000A01001", "INE000B01002")
    assert all("None" not in item for item in record.interval_summaries)
    assert record.candle_count == 2
    assert record.final_classification is IdentityState.SYMBOL_REUSE_CONFLICT
