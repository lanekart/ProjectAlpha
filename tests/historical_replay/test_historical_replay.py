from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pandas as pd
from typer.testing import CliRunner

from alpha.candidate_learning import LearningLedgerRepository
from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateOutcomeLabel,
)
from alpha.candidate_learning.raw_universe import (
    ExclusionStage,
    RawCandidateRecord,
)
from alpha.cli import app
from alpha.config import settings
from alpha.data.repositories.database import Database
from alpha.data.repositories.prices import PricesRepository
from alpha.historical_replay import (
    BayesianWeightUpdater,
    BestSetupPlaybookBuilder,
    EvidenceCubeBuilder,
    FeatureImportanceEngine,
    HistoricalObservationFactory,
    HistoricalReplayEngine,
    HistoricalReplayRepository,
    ReplayCandidateObservation,
    SimulationLab,
    SimulationParameters,
    WalkForwardEngine,
    WalkForwardSplit,
    render_best_setup_playbook,
    render_walk_forward,
)
from alpha.recommendation_intelligence.models import OHLCVBar


def test_replay_stores_raw_emitted_and_approved_recommendations(tmp_path) -> None:
    learning = LearningLedgerRepository(tmp_path / "learning.json")
    replay = HistoricalReplayRepository(tmp_path / "replay.json")
    observation = _observation("AAA", emitted=True, approved=True)

    runs = HistoricalReplayEngine(
        replay_repository=replay,
        learning_repository=learning,
    ).run(
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 1),
        observations=(observation,),
    )

    assert runs[0].candidates_stored == 1
    assert runs[0].emitted_decisions == 1
    assert runs[0].approved_recommendations == 1
    assert learning.load_raw_records()[0].symbol == "AAA"
    assert learning.load_records()[0].approved_for_deployment is True


def test_replay_evaluates_forward_outcomes_after_decision_date(tmp_path) -> None:
    learning = LearningLedgerRepository(tmp_path / "learning.json")
    observation = _observation("AAA", emitted=True)

    HistoricalReplayEngine(
        replay_repository=HistoricalReplayRepository(tmp_path / "replay.json"),
        learning_repository=learning,
    ).run(
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 1),
        observations=(observation,),
    )

    outcome = learning.load_raw_outcomes()[0]
    assert outcome.windows[0].forward_return_pct_from_close == Decimal("6.00")
    assert outcome.windows[0].outcome_label is CandidateOutcomeLabel.WOULD_HAVE_WON


def test_replay_does_not_mutate_point_in_time_candidate_data(tmp_path) -> None:
    learning = LearningLedgerRepository(tmp_path / "learning.json")
    observation = _observation(
        "AAA",
        bars=(
            _bar(0, open_price="100", high="101", low="99", close="100"),
            _bar(1, open_price="100", high="250", low="99", close="240"),
        ),
    )

    HistoricalReplayEngine(
        replay_repository=HistoricalReplayRepository(tmp_path / "replay.json"),
        learning_repository=learning,
    ).run(
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 1),
        observations=(observation,),
    )

    assert learning.load_raw_records()[0].close_price == Decimal("100")
    assert learning.load_raw_records()[0].evaluation_date == date(2026, 1, 1)


def test_same_candle_target_stop_is_conservative(tmp_path) -> None:
    learning = LearningLedgerRepository(tmp_path / "learning.json")
    observation = _observation(
        "AAA",
        bars=(_bar(1, open_price="100", high="115", low="94", close="112"),),
    )

    HistoricalReplayEngine(
        replay_repository=HistoricalReplayRepository(tmp_path / "replay.json"),
        learning_repository=learning,
    ).run(
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 1),
        observations=(observation,),
    )

    window = learning.load_raw_outcomes()[0].windows[0]
    assert window.target_1_touched is True
    assert window.risk_stop_touched is True
    assert window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_LOST


def test_replay_summary_aggregation(tmp_path) -> None:
    replay = HistoricalReplayRepository(tmp_path / "replay.json")
    HistoricalReplayEngine(
        replay_repository=replay,
        learning_repository=LearningLedgerRepository(tmp_path / "learning.json"),
    ).run(
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 1),
        observations=(_observation("AAA"), _observation("BBB")),
    )

    summary = replay.summary()
    assert summary.total_runs == 1
    assert summary.symbols_scanned == 2
    assert summary.candidates_stored == 2


def test_evidence_cube_grouping_and_ev(tmp_path) -> None:
    learning = _replayed_learning(tmp_path)

    cube = EvidenceCubeBuilder(repository=learning).build(minimum_sample_size=1)
    regimes = {
        cell.key: cell for cell in cube.cells if cell.dimension == "market_regime"
    }
    setups = {cell.key for cell in cube.cells if cell.dimension == "setup_type"}
    combinations = {
        cell.key for cell in cube.cells if cell.dimension == "indicator_combination"
    }

    assert regimes["BULLISH"].sample_size == 3
    assert regimes["BULLISH"].expected_value_pct == Decimal("2.00")
    assert "breakout" in setups
    assert "breakout+volume" in combinations


def test_feature_importance_ev_lift_and_weight_suggestion(tmp_path) -> None:
    learning = _replayed_learning(tmp_path)
    report = FeatureImportanceEngine(repository=learning).rank(minimum_sample_size=1)
    features = {feature.feature: feature for feature in report.features}

    assert features["volume"].ev_lift == Decimal("15.00")
    suggestions = BayesianWeightUpdater().suggestions(
        report=report,
        minimum_sample_size=10,
    )
    assert suggestions[0].direction.value == "INSUFFICIENT_SAMPLE"


def test_simulation_lab_parameter_comparison(tmp_path) -> None:
    learning = _replayed_learning(tmp_path)
    result = SimulationLab(repository=learning).run_strategy(
        parameters=SimulationParameters(
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 3),
            setup="breakout",
            regime="BULLISH",
            holding_period="20d",
            stop_atr=Decimal("2.0"),
            min_volume_ratio=Decimal("0"),
            min_relative_strength=Decimal("0"),
            require_sector_strength=False,
            require_volume_confirmation=True,
            top=10,
        )
    )

    assert result.trades == 1
    assert result.expected_value_pct == Decimal("12.00")
    assert result.best_regime == "BULLISH"


def test_walk_forward_reports_in_and_out_of_sample(tmp_path) -> None:
    learning = _replayed_learning(tmp_path)
    result = WalkForwardEngine(learning_repository=learning).run(
        split=WalkForwardSplit(
            train_start=date(2026, 1, 1),
            train_end=date(2026, 1, 2),
            validate_start=date(2026, 1, 3),
            validate_end=date(2026, 1, 3),
        ),
        minimum_sample_size=1,
    )

    assert result.observations == 1
    assert result.in_sample_ev == Decimal("-3.96")
    assert result.out_of_sample_ev == Decimal("10.89")
    assert result.sample_confidence.value == "WEAK"
    assert "Validation Verdict:" in "\n".join(render_walk_forward(result))


def test_best_setup_playbook_ranks_learned_patterns(tmp_path) -> None:
    learning = _replayed_learning(tmp_path)

    playbook = BestSetupPlaybookBuilder(repository=learning).build(
        minimum_sample_size=1
    )
    output = "\n".join(render_best_setup_playbook(playbook))

    assert playbook.completed_samples == 3
    assert playbook.best_setup_types[0].name == "breakout"
    assert playbook.best_holding_periods
    assert "Best Setup Playbook" in output
    assert "Playbook Verdict:" in output
    assert "How Alpha Should Use This:" in output
    assert "Worst Patterns To Avoid:" in output


def test_playbook_report_cli_output(tmp_path) -> None:
    env = {"ALPHA_CANDIDATE_LEARNING_LEDGER": str(tmp_path / "learning.json")}
    _replayed_learning(tmp_path)

    result = CliRunner().invoke(
        app,
        ["playbook", "report", "--min-sample-size", "1"],
        env=env,
    )

    assert result.exit_code == 0
    assert "Best Setup Playbook" in result.stdout
    assert "Best Holding Periods:" in result.stdout


def test_observation_factory_builds_point_in_time_replay_observations(
    tmp_path: Path,
) -> None:
    replay_date = date(2026, 1, 10)
    db = Database(str(tmp_path / "factory_prices.duckdb"))
    repo = PricesRepository(db)
    _insert_replay_price_history(repo, replay_date=replay_date)

    result = HistoricalObservationFactory(price_repository=repo).build(
        from_date=replay_date,
        to_date=replay_date,
    )

    assert result.skipped_dates == ()
    assert result.replay_dates == (replay_date,)
    assert result.observations
    first = result.observations[0]
    assert first.raw_candidate.evaluation_date == replay_date
    assert first.raw_candidate.run_id == "historical_replay|2026-01-10"
    assert first.bars
    assert all(bar.observed_on > replay_date for bar in first.bars)
    assert first.raw_candidate.close_price is not None


def test_observation_factory_ignores_invalid_ohlc_rows(tmp_path: Path) -> None:
    replay_date = date(2026, 1, 10)
    db = Database(str(tmp_path / "factory_invalid_prices.duckdb"))
    repo = PricesRepository(db)
    _insert_replay_price_history(repo, replay_date=replay_date)
    repo.insert(
        pd.DataFrame(
            [
                {
                    "symbol": "BROKEN",
                    "trade_date": replay_date,
                    "open": 50.0,
                    "high": 40.0,
                    "low": 30.0,
                    "close": 45.0,
                    "volume": 100000,
                    "sector": "IT",
                    "exchange": "NSE",
                }
            ]
        )
    )

    result = HistoricalObservationFactory(price_repository=repo).build(
        from_date=replay_date,
        to_date=replay_date,
    )

    assert result.skipped_dates == ()
    assert result.observations


def test_cli_replay_evidence_feature_and_simulation_commands(
    tmp_path,
    monkeypatch,
) -> None:
    replay_date = date(2026, 1, 1)
    db_path = tmp_path / "cli_prices.duckdb"
    db = Database(str(db_path))
    repo = PricesRepository(db)
    _insert_replay_price_history(repo, replay_date=replay_date)
    db.close()
    monkeypatch.setattr(settings, "database_path", db_path)
    env = {
        "ALPHA_CANDIDATE_LEARNING_LEDGER": str(tmp_path / "learning.json"),
        "ALPHA_HISTORICAL_REPLAY_LEDGER": str(tmp_path / "replay.json"),
    }
    _replayed_learning(tmp_path)

    runner = CliRunner()
    replay = runner.invoke(
        app,
        ["replay", "run", "--from-date", "2026-01-01", "--to-date", "2026-01-01"],
        env=env,
    )
    evidence = runner.invoke(app, ["evidence", "report"], env=env)
    features = runner.invoke(app, ["evidence", "features"], env=env)
    simulation = runner.invoke(
        app,
        [
            "simulate",
            "strategy",
            "--from-date",
            "2026-01-01",
            "--to-date",
            "2026-01-03",
        ],
        env=env,
    )

    assert replay.exit_code == 0
    assert "Historical Replay Run" in replay.stdout
    assert "Raw candidates stored: " in replay.stdout
    assert evidence.exit_code == 0
    assert "Evidence Cube Report" in evidence.stdout
    assert features.exit_code == 0
    assert "Feature Importance" in features.stdout
    assert simulation.exit_code == 0
    assert "Strategy Simulation" in simulation.stdout


def test_alpha_run_prints_historical_evidence_block(tmp_path) -> None:
    env = {
        "ALPHA_CANDIDATE_LEARNING_LEDGER": str(tmp_path / "learning.json"),
        "ALPHA_RECOMMENDATION_LEDGER": str(tmp_path / "recommendations.json"),
        "ALPHA_STRATEGY_REGIME_BACKTESTS": str(tmp_path / "strategy.json"),
    }

    result = CliRunner().invoke(
        app,
        ["run", "--demo", "--date", "2026-01-30"],
        env=env,
    )

    assert result.exit_code == 0
    assert "Historical Evidence:" in result.stdout
    assert "- Historical EV: Not yet computed" in result.stdout


def _insert_replay_price_history(
    repo: PricesRepository,
    *,
    replay_date: date,
) -> None:
    start = replay_date - timedelta(days=1300)
    rows: list[dict[str, object]] = []
    symbols = (
        ("AAA", "IT", Decimal("100"), Decimal("0.050")),
        ("BBB", "BANKS", Decimal("180"), Decimal("0.035")),
        ("CCC", "CAPITAL GOODS", Decimal("260"), Decimal("0.020")),
    )
    for offset in range(1370):
        trade_date = start + timedelta(days=offset)
        for symbol, sector, base_price, drift in symbols:
            close = base_price + Decimal(offset) * drift
            open_price = close * Decimal("0.995")
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": float(open_price),
                    "high": float(close * Decimal("1.015")),
                    "low": float(close * Decimal("0.985")),
                    "close": float(close),
                    "volume": 100000 + offset * 10,
                    "sector": sector,
                    "exchange": "NSE",
                }
            )
    repo.insert(pd.DataFrame(rows))


def _replayed_learning(tmp_path) -> LearningLedgerRepository:
    learning = LearningLedgerRepository(tmp_path / "learning.json")
    replay = HistoricalReplayRepository(tmp_path / "replay.json")
    observations = (
        _observation(
            "AAA",
            offset=0,
            emitted=True,
            indicators=("breakout",),
            forward_close="104",
        ),
        _observation(
            "BBB",
            offset=1,
            emitted=True,
            indicators=("breakout",),
            forward_close="90",
        ),
        _observation(
            "CCC",
            offset=2,
            emitted=True,
            indicators=("breakout", "volume"),
            forward_close="112",
        ),
    )
    HistoricalReplayEngine(
        replay_repository=replay,
        learning_repository=learning,
    ).run(
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 3),
        observations=observations,
    )
    return learning


def _observation(
    symbol: str,
    *,
    offset: int = 0,
    emitted: bool = False,
    approved: bool = False,
    indicators: tuple[str, ...] = ("breakout",),
    bars: tuple[OHLCVBar, ...] | None = None,
    forward_close: str = "106",
) -> ReplayCandidateObservation:
    replay_date = date(2026, 1, 1) + timedelta(days=offset)
    raw = _raw_record(symbol, replay_date=replay_date, indicators=indicators)
    if bars is None:
        close = Decimal(forward_close)
        bars = tuple(
            OHLCVBar(
                observed_on=replay_date + timedelta(days=day),
                open_price=Decimal("100"),
                high_price=max(Decimal("112"), close),
                low_price=min(Decimal("98"), close),
                close_price=close,
                volume=Decimal("100000"),
            )
            for day in range(1, 61)
        )
    decision = (
        _decision(symbol, replay_date=replay_date, approved=approved)
        if emitted
        else None
    )
    return ReplayCandidateObservation(
        raw_candidate=raw,
        emitted_decision=decision,
        bars=bars,
    )


def _raw_record(
    symbol: str,
    *,
    replay_date: date,
    indicators: tuple[str, ...],
) -> RawCandidateRecord:
    return RawCandidateRecord(
        raw_candidate_id=f"raw-{symbol}-{replay_date.isoformat()}",
        run_id=f"replay-{replay_date.isoformat()}",
        evaluation_date=replay_date,
        symbol=symbol,
        universe_source="test",
        was_emitted_decision=False,
        emitted_verdict=None,
        excluded_stage=ExclusionStage.SETUP_FILTER,
        exclusion_reasons=("Not emitted",),
        preliminary_score=Decimal("70"),
        data_quality_score=Decimal("1"),
        liquidity_score=Decimal("0.80"),
        trend_score=Decimal("0.70"),
        momentum_score=Decimal("0.70"),
        volume_score=Decimal("0.80"),
        volatility_score=Decimal("0.40"),
        relative_strength_score=Decimal("0.80"),
        setup_score=Decimal("0.70"),
        risk_score=Decimal("0.70"),
        regime_score=Decimal("0.70"),
        final_strategy_score=Decimal("70"),
        indicators_active=indicators,
        indicator_scores=MappingProxyType({"strategy": "70"}),
        market_regime="BULLISH",
        long_trade_permission=True,
        close_price=Decimal("100"),
        entry_candidate_price=Decimal("100"),
        risk_stop=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("116"),
        target_3=Decimal("122"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        sector="IT",
    )


def _decision(
    symbol: str,
    *,
    replay_date: date,
    approved: bool,
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id=f"candidate-{symbol}-{replay_date.isoformat()}",
        run_id=f"replay-{replay_date.isoformat()}",
        evaluation_date=replay_date,
        symbol=symbol,
        final_verdict="BUY",
        capital_action="BUY",
        approved_for_deployment=approved,
        rejection_reasons=(),
        setup_type="BREAKOUT",
        market_regime="BULLISH",
        long_trade_permission=True,
        strategy_score=Decimal("80"),
        confidence="HIGH",
        data_quality="COMPLETE",
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("101"),
        confirmation_entry=Decimal("101"),
        risk_stop=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("116"),
        target_3=Decimal("122"),
        trailing_stop_plan="Trail below highest close.",
        expected_holding_period="20d",
        indicators_active=("breakout",),
        indicator_scores={"strategy": "80"},
        evidence_layers=("Price/Volume",),
        explanation="Replay test decision.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        sector="IT",
    )


def _bar(
    offset: int,
    *,
    open_price: str,
    high: str,
    low: str,
    close: str,
) -> OHLCVBar:
    return OHLCVBar(
        observed_on=date(2026, 1, 1) + timedelta(days=offset),
        open_price=Decimal(open_price),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
        volume=Decimal("100000"),
    )
