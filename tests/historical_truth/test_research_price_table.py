from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from alpha.historical_truth.research_price_table import ResearchPriceTableBuilder


def _database(path: Path, *, unresolved: bool = False) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE daily_candle(
                trading_date DATE, exchange VARCHAR, symbol VARCHAR, series VARCHAR,
                isin VARCHAR, open_price DOUBLE, high_price DOUBLE, low_price DOUBLE,
                close_price DOUBLE, volume BIGINT, source_sha256 VARCHAR
            );
            CREATE TABLE adjusted_daily_candle(
                contract_version VARCHAR, trading_date DATE, exchange VARCHAR,
                symbol VARCHAR, series VARCHAR, isin VARCHAR, raw_open DOUBLE,
                raw_high DOUBLE, raw_low DOUBLE, raw_close DOUBLE, raw_volume BIGINT,
                price_factor DOUBLE, quantity_factor DOUBLE, adjusted_open DOUBLE,
                adjusted_high DOUBLE, adjusted_low DOUBLE, adjusted_close DOUBLE,
                adjusted_volume BIGINT, action_ids VARCHAR,
                calculation_version VARCHAR, as_of_date DATE
            );
            CREATE TABLE adjusted_candle_lineage(
                contract_version VARCHAR, trading_date DATE, exchange VARCHAR,
                symbol VARCHAR, series VARCHAR, raw_source_sha256 VARCHAR,
                action_ids VARCHAR, factor_ids VARCHAR, lineage_digest VARCHAR
            );
            CREATE TABLE corporate_action_event(
                action_id VARCHAR, price_adjustment_required BOOLEAN
            );
            CREATE TABLE corporate_action_adjustment_factor(
                action_id VARCHAR, effective_date DATE, state VARCHAR
            );
            """
        )
        connection.executemany(
            "INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    date(2020, 1, 2),
                    "NSE",
                    "ALPHA",
                    "EQ",
                    "INE000A01010",
                    100,
                    105,
                    99,
                    104,
                    1000,
                    "raw-1",
                ),
                (
                    date(2020, 1, 3),
                    "NSE",
                    "ALPHA",
                    "BE",
                    "INE000A01010",
                    110,
                    112,
                    108,
                    111,
                    900,
                    "raw-2",
                ),
                (
                    date(2020, 1, 3),
                    "NSE",
                    "BOND",
                    "N1",
                    "INE000A07010",
                    100,
                    100,
                    100,
                    100,
                    5,
                    "raw-3",
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO adjusted_daily_candle VALUES
            ('v', DATE '2020-01-02', 'NSE', 'ALPHA', 'EQ', 'INE000A01010',
             100, 105, 99, 104, 1000, .5, 2, 50, 52.5, 49.5, 52, 2000,
             'action-1', 'calc-v1', DATE '2020-01-03')
            """
        )
        connection.execute(
            """
            INSERT INTO adjusted_candle_lineage VALUES
            ('v', DATE '2020-01-02', 'NSE', 'ALPHA', 'EQ', 'raw-1',
             'action-1', 'factor-1', 'lineage-1')
            """
        )
        if unresolved:
            connection.execute(
                "INSERT INTO corporate_action_event VALUES ('event-1', true)"
            )
            connection.execute(
                """
                INSERT INTO corporate_action_adjustment_factor VALUES
                ('event-1', DATE '2020-01-03', 'UNKNOWN')
                """
            )


def test_complete_table_combines_adjusted_overlay_and_factor_one_rows(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)

    report = ResearchPriceTableBuilder().build(
        database,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
    )

    assert report.research_rows == 2
    assert report.total_raw_rows == 3
    assert report.ineligible_non_equity_rows == 1
    assert report.adjusted_factor_rows == 1
    assert report.factor_one_rows == 1
    assert report.unexplained_missing_rows == 0
    assert report.invalid_adjusted_ohlc_rows == 0
    assert report.preserved_separate_identity_boundaries == 0
    assert report.readiness_state == "POST2016_ADJUSTED_REPLAY_READY"
    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT series, adjusted_close, cumulative_price_factor,
                   research_eligibility_state
            FROM research_daily_candle ORDER BY trading_date
            """
        ).fetchall()
    assert rows == [
        ("EQ", 52.0, 0.5, "ELIGIBLE_EQUITY"),
        ("BE", 111.0, 1.0, "ELIGIBLE_EQUITY"),
        ("N1", 100.0, 1.0, "INELIGIBLE_NON_EQUITY"),
    ]


def test_unresolved_multiplicative_factor_blocks_materialization(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database, unresolved=True)

    with pytest.raises(ValueError, match="unresolved multiplicative factors"):
        ResearchPriceTableBuilder().build(
            database,
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 3),
        )
