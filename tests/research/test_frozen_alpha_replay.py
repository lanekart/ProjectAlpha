from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import duckdb

from alpha.recommendation_intelligence import RecommendationDecision
from alpha.research.frozen_alpha_replay import (
    FrozenAlphaReplayEngine,
    ResearchMarketDataStore,
)
from alpha.research.lab_models import ResearchExperimentSpec, StrategyMode
from alpha.research.lab_service import ConversationalResearchLab


def _database(path: Path) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE research_daily_candle(
                trading_date DATE, governed_identity_id VARCHAR, isin VARCHAR,
                symbol VARCHAR, series VARCHAR, adjusted_open DOUBLE,
                adjusted_high DOUBLE, adjusted_low DOUBLE, adjusted_close DOUBLE,
                adjusted_volume BIGINT, exchange VARCHAR,
                research_eligibility_state VARCHAR
            );
            CREATE TABLE research_price_certification(
                contract_version VARCHAR, start_date DATE, end_date DATE,
                expected_sessions BIGINT, observed_sessions BIGINT,
                eligible_securities BIGINT, total_raw_rows BIGINT,
                eligible_raw_rows BIGINT, ineligible_non_equity_rows BIGINT,
                research_rows BIGINT, logical_sha256 VARCHAR,
                readiness_state VARCHAR, production_influence BOOLEAN
            );
            """
        )
        connection.executemany(
            "INSERT INTO research_daily_candle VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    date(2020, 1, 2),
                    "nse:isin:INEOLD",
                    "INEOLD",
                    "ALPHA",
                    "EQ",
                    90,
                    95,
                    89,
                    94,
                    100,
                    "NSE",
                    "ELIGIBLE_EQUITY",
                ),
                (
                    date(2020, 1, 3),
                    "nse:isin:INENEW",
                    "INENEW",
                    "ALPHA",
                    "EQ",
                    100,
                    105,
                    99,
                    104,
                    200,
                    "NSE",
                    "ELIGIBLE_EQUITY",
                ),
                (
                    date(2020, 1, 2),
                    "nse:isin:INENEW",
                    "INENEW",
                    "ALPHA",
                    "EQ",
                    98,
                    101,
                    97,
                    100,
                    180,
                    "NSE",
                    "ELIGIBLE_EQUITY",
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO research_price_certification VALUES
            ('contract', DATE '2020-01-01', DATE '2020-01-03',
             2, 2, 2, 2, 2, 0, 2, 'data-hash',
             'POST2016_ADJUSTED_REPLAY_READY', false)
            """
        )


def test_history_is_bound_to_current_governed_identity(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)

    with ResearchMarketDataStore(database) as store:
        history = store.find_history_by_symbols(
            symbols=("ALPHA",),
            end_date=date(2020, 1, 3),
            limit=250,
        )

    assert [item.date() for item in history["trade_date"]] == [
        date(2020, 1, 2),
        date(2020, 1, 3),
    ]
    assert history["close"].tolist() == [100.0, 104.0]


def test_replay_is_retrospective_deterministic_and_production_isolated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)

    class FakeRunner:
        def __init__(self, **_: object) -> None:
            pass

        def run_day(self, observed_on: date) -> SimpleNamespace:
            recommendation = SimpleNamespace(
                observed_on=observed_on,
                symbol="ALPHA",
                decision=RecommendationDecision.BUY,
                score=Decimal("72.5"),
                trade_setup=SimpleNamespace(
                    setup_name="BREAKOUT",
                    setup_category="MOMENTUM",
                ),
                actionable_trade_strategy=None,
                score_breakdown={"strategy": "20"},
                supporting_evidence=({"label": "trend"},),
                opposing_evidence=(),
                trade_plan={"entry": "next open"},
            )
            return SimpleNamespace(
                intelligence=SimpleNamespace(
                    recommendations=(recommendation,),
                    market_report=SimpleNamespace(
                        bias=SimpleNamespace(value="BULLISH")
                    ),
                )
            )

    monkeypatch.setattr(
        "alpha.research.frozen_alpha_replay.CanonicalAlphaRunner",
        FakeRunner,
    )
    engine = FrozenAlphaReplayEngine()
    first = engine.run(
        database,
        start_date=date(2020, 1, 3),
        end_date=date(2020, 1, 3),
        source_commit="abc123",
    )
    second = engine.run(
        database,
        start_date=date(2020, 1, 3),
        end_date=date(2020, 1, 3),
        source_commit="abc123",
    )

    assert first == second
    assert first.recommendation_count == 1
    assert first.buy_count == 1
    assert first.sessions_failed == 0
    assert first.readiness_state == "RETROSPECTIVE_ALPHA_REPLAY_READY"
    with duckdb.connect(str(database), read_only=True) as connection:
        row = connection.execute(
            """
            SELECT signal_source_state, production_influence, COUNT(*)
            FROM frozen_recommendation GROUP BY 1, 2
            """
        ).fetchone()
    assert row == ("RETROSPECTIVE_FROZEN_ALPHA_REPLAY", False, 1)


def test_alpha_frame_loads_full_history_only_for_signalled_identities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)

    class FakeRunner:
        def __init__(self, **_: object) -> None:
            pass

        def run_day(self, observed_on: date) -> SimpleNamespace:
            recommendation = SimpleNamespace(
                observed_on=observed_on,
                symbol="ALPHA",
                decision=RecommendationDecision.BUY,
                score=Decimal("70"),
                trade_setup=SimpleNamespace(
                    setup_name="BREAKOUT",
                    setup_category="MOMENTUM",
                ),
                actionable_trade_strategy=None,
                score_breakdown={},
                supporting_evidence=(),
                opposing_evidence=(),
                trade_plan={},
            )
            return SimpleNamespace(
                intelligence=SimpleNamespace(
                    recommendations=(recommendation,),
                    market_report=SimpleNamespace(
                        bias=SimpleNamespace(value="BULLISH")
                    ),
                )
            )

    monkeypatch.setattr(
        "alpha.research.frozen_alpha_replay.CanonicalAlphaRunner",
        FakeRunner,
    )
    FrozenAlphaReplayEngine().run(
        database,
        start_date=date(2020, 1, 3),
        end_date=date(2020, 1, 3),
        source_commit="abc123",
    )
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            UPDATE frozen_recommendation_replay_run
            SET start_date = DATE '2020-01-02'
            """
        )
    spec = ResearchExperimentSpec(
        experiment_id="ARL-000001",
        research_session_id="ARS-000001",
        experiment_name="retrospective",
        parent_experiment_id=None,
        strategy_mode=StrategyMode.ALPHA_SIGNAL,
        data_start=date(2020, 1, 2),
        data_end=date(2020, 1, 3),
        base_signal_source=("BUY", "STRONG_BUY"),
    )
    lab = ConversationalResearchLab(database=database, root=tmp_path / "research")

    frame = lab._load_frame(spec)

    assert frame["security_id"].unique().tolist() == ["INENEW"]
    assert [item.date() for item in frame["trading_date"]] == [
        date(2020, 1, 2),
        date(2020, 1, 3),
    ]
    assert frame["final_signal"].isna().tolist() == [True, False]
