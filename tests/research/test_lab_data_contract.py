from __future__ import annotations

from pathlib import Path

import duckdb

from alpha.research.lab_data_contract import ResearchDataContractAuditor


def _database(path: Path) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE daily_candle(
                trading_date DATE, exchange VARCHAR, series VARCHAR, isin VARCHAR
            );
            CREATE TABLE research_daily_candle(
                trading_date DATE, governed_identity_id VARCHAR,
                series VARCHAR, identity_source VARCHAR, price_basis_state VARCHAR,
                adjusted_open DOUBLE, adjusted_high DOUBLE,
                adjusted_low DOUBLE, adjusted_close DOUBLE,
                research_eligibility_state VARCHAR
            );
            CREATE TABLE corporate_action_event(
                action_id VARCHAR, price_adjustment_required BOOLEAN
            );
            CREATE TABLE corporate_action_adjustment_factor(
                action_id VARCHAR, effective_date DATE, state VARCHAR
            );
            CREATE TABLE research_price_certification(
                contract_version VARCHAR, start_date DATE, end_date DATE,
                logical_sha256 VARCHAR, readiness_state VARCHAR
            );
            CREATE TABLE frozen_recommendation(
                run_id VARCHAR, generated_at DATE, signal_source_state VARCHAR
            );
            CREATE TABLE frozen_recommendation_replay_run(
                run_id VARCHAR, start_date DATE, end_date DATE,
                sessions_failed BIGINT, readiness_state VARCHAR,
                data_logical_sha256 VARCHAR, ledger_logical_sha256 VARCHAR,
                source_commit VARCHAR, engine_version VARCHAR
            );
            INSERT INTO daily_candle VALUES
                (DATE '2016-01-01', 'NSE', 'EQ', 'INE0001'),
                (DATE '2016-01-04', 'NSE', 'EQ', 'INE0001');
            INSERT INTO research_daily_candle VALUES
                (DATE '2016-01-01', 'nse:isin:INE0001', 'EQ',
                 'EXACT_DAILY_CANDLE_ISIN', 'CERTIFIED_FACTOR_ONE',
                 100, 101, 99, 100, 'ELIGIBLE_EQUITY'),
                (DATE '2016-01-04', 'nse:isin:INE0001', 'EQ',
                 'EXACT_DAILY_CANDLE_ISIN', 'CERTIFIED_FACTOR_ONE',
                 101, 102, 100, 101, 'ELIGIBLE_EQUITY');
            INSERT INTO research_price_certification VALUES
                ('v1', DATE '2016-01-01', DATE '2016-01-04',
                 'data-hash', 'POST2016_ADJUSTED_REPLAY_READY');
            """
        )


def test_short_smoke_replay_does_not_unlock_full_contract(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO frozen_recommendation VALUES
                ('smoke', DATE '2016-01-01',
                 'RETROSPECTIVE_FROZEN_ALPHA_REPLAY');
            INSERT INTO frozen_recommendation_replay_run VALUES
                ('smoke', DATE '2016-01-01', DATE '2016-01-01', 0,
                 'RETROSPECTIVE_ALPHA_REPLAY_READY',
                 'data-hash', 'ledger-hash', 'source', 'engine');
            """
        )

    contract = ResearchDataContractAuditor().audit(database)

    assert contract.ready
    assert contract.retrospective_alpha_signal_records == 0
    assert not contract.retrospective_alpha_replay_ready


def test_covering_replay_unlocks_retrospective_source(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO frozen_recommendation VALUES
                ('full', DATE '2016-01-01',
                 'RETROSPECTIVE_FROZEN_ALPHA_REPLAY'),
                ('full', DATE '2016-01-04',
                 'RETROSPECTIVE_FROZEN_ALPHA_REPLAY');
            INSERT INTO frozen_recommendation_replay_run VALUES
                ('full', DATE '2016-01-01', DATE '2016-01-04', 0,
                 'RETROSPECTIVE_ALPHA_REPLAY_READY',
                 'data-hash', 'ledger-hash', 'source', 'engine');
            """
        )

    contract = ResearchDataContractAuditor().audit(database)

    assert contract.retrospective_alpha_signal_records == 2
    assert contract.retrospective_alpha_replay_ready
    assert not contract.recorded_historical_signal_ready
    assert not contract.walk_forward_alpha_replay_ready
