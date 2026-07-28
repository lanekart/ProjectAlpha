from __future__ import annotations

from pathlib import Path

ENGINE = Path("alpha/historical_truth/point_in_time_identity_engine.py")
TEST = Path("tests/historical_truth/test_point_in_time_identity_pre2016_regressions.py")


def _replace_once(text: str, old: str, new: str, code: str) -> str:
    if old not in text:
        raise RuntimeError(code)
    return text.replace(old, new, 1)


def main() -> None:
    text = ENGINE.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        """                FROM scoped_candle c JOIN reused r
                  ON UPPER(c.symbol) = r.symbol AND UPPER(c.series) = r.series
                GROUP BY UPPER(c.symbol), UPPER(c.series), UPPER(c.isin)
""",
        """                FROM scoped_candle c JOIN reused r
                  ON UPPER(c.symbol) = r.symbol AND UPPER(c.series) = r.series
                WHERE c.isin IS NOT NULL
                GROUP BY UPPER(c.symbol), UPPER(c.series), UPPER(c.isin)
""",
        "HTR009A_NULL_ISIN_QUERY_BOUNDARY_MISSING",
    )
    text = _replace_once(
        text,
        """        for symbol, series, isins, summaries, candles, _ in rows:
            parsed = [item.split(\":\") for item in summaries]
            intervals = [
                (date.fromisoformat(parts[1]), date.fromisoformat(parts[2]))
                for parts in parsed
            ]
""",
        """        for symbol, series, isins, summaries, candles, _ in rows:
            valid_isins = tuple(str(item) for item in isins if item is not None)
            valid_summaries = tuple(
                str(item) for item in summaries if item is not None
            )
            parsed = [item.split(\":\") for item in valid_summaries]
            intervals = [
                (date.fromisoformat(parts[1]), date.fromisoformat(parts[2]))
                for parts in parsed
            ]
""",
        "HTR009A_NULL_ISIN_PARSE_BOUNDARY_MISSING",
    )
    text = _replace_once(
        text,
        """                    tuple(str(item) for item in isins),
                    tuple(str(item) for item in summaries),
""",
        """                    valid_isins,
                    valid_summaries,
""",
        "HTR009A_NULL_ISIN_RECORD_BOUNDARY_MISSING",
    )
    ENGINE.write_text(text, encoding="utf-8")

    TEST.write_text(
        '''from __future__ import annotations

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
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
