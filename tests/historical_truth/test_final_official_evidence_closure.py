from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from alpha.historical_truth.adjustment_replay_admission_models import (
    ValidationOutcome,
)
from alpha.historical_truth.final_official_evidence_closure import (
    AcceptedFactor,
    _accepted_factors,
    _adjusted_logical_digest,
    _create_adjusted_rows,
    _create_materialization_tables,
    _insert_factors,
    _materialization_counts,
    _resolution_counts,
)


def _accepted() -> AcceptedFactor:
    return AcceptedFactor(
        event_id="event-1",
        factor_id="factor-1",
        identity_key="nse:isin:INE000A01001",
        symbol="TEST",
        series="EQ",
        effective_date=date(2010, 1, 3),
        price_factor=0.5,
        quantity_factor=2.0,
        validation_outcome=(
            ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP.value
        ),
    )


def test_official_terms_without_testable_atr_enters_factor_ledger() -> None:
    outcome = (
        ValidationOutcome.FACTOR_CERTIFIED_OFFICIAL_TERMS_CONTINUITY_NOT_TESTABLE.value
    )
    accepted, ledger = _accepted_factors(
        (
            {
                "event_id": "event-1",
                "validation_outcome": outcome,
                "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
                "price_factor": 0.5,
                "continuity_testable": False,
            },
        ),
        {
            "event-1": {
                "canonical_event_id": "event-1",
                "governed_identity_id": "nse:isin:INE000A01001",
                "symbol": "TEST",
                "series_applicability": ["EQ"],
                "action_type": "BONUS",
                "effective_date": "2010-01-03",
            }
        },
        {
            "event-1": {
                "factor_id": "factor-1",
                "identity_key": "nse:isin:INE000A01001",
                "quantity_factor": 2.0,
            }
        },
    )

    assert len(accepted) == 1
    assert accepted[0].price_factor == 0.5
    assert accepted[0].quantity_factor == 2.0
    assert ledger[0]["continuity_testable"] is False
    assert ledger[0]["terminal"] is True


def _raw_database(path: Path) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE daily_candle(
                trading_date DATE, exchange VARCHAR, symbol VARCHAR,
                series VARCHAR, isin VARCHAR, open_price DOUBLE,
                high_price DOUBLE, low_price DOUBLE, close_price DOUBLE,
                volume BIGINT, source_sha256 VARCHAR,
                PRIMARY KEY(trading_date,exchange,symbol,series)
            )
            """
        )
        connection.executemany(
            "INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    date(2010, 1, 1),
                    "NSE",
                    "TEST",
                    "EQ",
                    "INE000A01001",
                    100.0,
                    110.0,
                    90.0,
                    100.0,
                    100,
                    "a" * 64,
                ),
                (
                    date(2010, 1, 2),
                    "NSE",
                    "TEST",
                    "EQ",
                    None,
                    102.0,
                    112.0,
                    92.0,
                    102.0,
                    200,
                    "b" * 64,
                ),
                (
                    date(2010, 1, 3),
                    "NSE",
                    "TEST",
                    "EQ",
                    "INE000A01001",
                    51.0,
                    56.0,
                    46.0,
                    51.0,
                    400,
                    "c" * 64,
                ),
            ],
        )


def test_adjusted_overlay_uses_exact_and_certified_bridge_rows(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw.duckdb"
    output = tmp_path / "adjusted.duckdb"
    _raw_database(raw)
    with duckdb.connect(str(output)) as connection:
        _create_materialization_tables(connection)
        _insert_factors(connection, (_accepted(),))
        connection.execute(
            "INSERT INTO governed_missing_isin_identity VALUES "
            "('2010-01-02','NSE','TEST','EQ',?,'nse:isin:INE000A01001',"
            "'CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE','contract','report')",
            ["b" * 64],
        )
        escaped = str(raw).replace("'", "''")
        connection.execute(f"ATTACH '{escaped}' AS source_db (READ_ONLY)")
        _create_adjusted_rows(
            connection,
            date(2010, 1, 1),
            date(2010, 1, 3),
        )
        first = connection.execute(
            "SELECT identity_state,adjusted_close,adjusted_volume "
            "FROM governed_adjusted_daily_candle ORDER BY trading_date"
        ).fetchall()
        counts = _materialization_counts(connection)
        digest_a = _adjusted_logical_digest(connection)
        digest_b = _adjusted_logical_digest(connection)

    assert first == [
        ("EXACT_ISIN_CANDLE", 50.0, 200),
        ("CERTIFIED_DATED_BRIDGE_CANDLE", 51.0, 400),
    ]
    assert counts["required_row_count"] == 2
    assert counts["adjusted_row_count"] == 2
    assert counts["exact_isin_adjusted_row_count"] == 1
    assert counts["certified_bridge_adjusted_row_count"] == 1
    assert counts["invalid_adjusted_row_count"] == 0
    assert digest_a == digest_b


def test_rejected_identity_row_remains_outside_adjusted_overlay(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw.duckdb"
    output = tmp_path / "adjusted.duckdb"
    _raw_database(raw)
    with duckdb.connect(str(output)) as connection:
        _create_materialization_tables(connection)
        _insert_factors(connection, (_accepted(),))
        connection.execute(
            "INSERT INTO rejected_missing_isin_identity VALUES "
            "('2010-01-02','NSE','TEST','EQ',?,'nse:isin:INE000A01001',"
            "'NO_MATCHING_OFFICIAL_INTERVAL')",
            ["b" * 64],
        )
        escaped = str(raw).replace("'", "''")
        connection.execute(f"ATTACH '{escaped}' AS source_db (READ_ONLY)")
        _create_adjusted_rows(
            connection,
            date(2010, 1, 1),
            date(2010, 1, 3),
        )
        counts = _materialization_counts(connection)

    assert counts["adjusted_row_count"] == 1
    assert counts["unresolved_identity_adjustment_row_count"] == 1
    assert counts["required_row_count"] == 2


def test_resolution_counts_preserve_b4_missing_component_taxonomy(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "b4"
    baseline.mkdir()
    (baseline / "dsi010b4_remaining_blockers.json").write_text(
        (
            '[{"event_id":"event-1","missing_component":'
            '"FOURTEEN_GOVERNED_PRE_EVENT_BARS"},'
            '{"event_id":"event-2","missing_component":'
            '"GOVERNED_REFERENCE_PRICE_IDENTITY"}]\n'
        ),
        encoding="utf-8",
    )

    counts = _resolution_counts(
        baseline,
        (
            {"event_id": "event-1", "resolved": True},
            {"event_id": "event-2", "resolved": False},
        ),
    )

    assert counts["FOURTEEN_GOVERNED_PRE_EVENT_BARS"] == 1
    assert counts["TOTAL_STARTING_CASES"] == 2
    assert counts["TOTAL_RESOLVED_CASES"] == 1
    assert counts["TOTAL_REMAINING_EVENT_CASES"] == 1
