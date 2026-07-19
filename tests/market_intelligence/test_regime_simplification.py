from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
from pytest import MonkeyPatch
from typer.testing import CliRunner

from alpha.candidate_learning import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
    LearningLedgerRepository,
)
from alpha.cli import app
from alpha.market_intelligence import (
    RegimeInputRole,
    RegimeSimplificationAuditEngine,
    RegimeSimplificationConclusion,
    ResearchRegimeLabel,
    ResearchRegimeModel,
    SectorImpactClass,
    SimplifiedRegimeClassifier,
    SimplifiedRegimeFeatureRow,
    export_regime_simplification_csv,
    export_regime_simplification_json,
    render_regime_parsimony_decision,
    render_simplified_regime_distribution,
    render_simplified_regime_outcomes,
)


def test_dependency_audit_marks_sector_and_benchmark_inputs_explicitly(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)

    dependencies = engine.dependency_audit()
    by_name = {dependency.input_name: dependency for dependency in dependencies}

    assert by_name["sector score"].role is RegimeInputRole.UNAVAILABLE
    assert (
        by_name["point-in-time breadth"].role
        is RegimeInputRole.MATERIAL_CLASSIFICATION_INPUT
    )
    assert "indexed v2 table" in by_name["benchmark returns"].availability
    assert "insufficient input" in by_name["benchmark returns"].fallback_behavior


def test_simplified_classifier_is_deterministic_and_input_aware() -> None:
    classifier = SimplifiedRegimeClassifier()
    row = SimplifiedRegimeFeatureRow(
        market_date=date(2026, 1, 1),
        v2_regime="BULLISH",
        breadth_ratio=Decimal("0.62"),
        percent_above_20dma=Decimal("0.70"),
        percent_above_50dma=Decimal("0.64"),
        percent_above_200dma=Decimal("0.58"),
        diagnostic_quality="HIGH_COVERAGE",
        benchmark_return_20d=Decimal("0.03"),
        benchmark_above_50dma=True,
        benchmark_above_200dma=True,
        benchmark_volatility=Decimal("0.018"),
    )

    assert (
        classifier.classify(ResearchRegimeModel.BENCHMARK_TREND_ONLY, row)
        is ResearchRegimeLabel.BULLISH
    )
    assert (
        classifier.classify(ResearchRegimeModel.BENCHMARK_TREND_VOLATILITY, row)
        is ResearchRegimeLabel.BULLISH
    )
    assert (
        classifier.classify(ResearchRegimeModel.BENCHMARK_BREADTH, row)
        is ResearchRegimeLabel.BULLISH
    )

    high_vol = replace(row, benchmark_volatility=Decimal("0.05"))
    assert (
        classifier.classify(ResearchRegimeModel.BENCHMARK_TREND_VOLATILITY, high_vol)
        is ResearchRegimeLabel.HIGH_VOLATILITY
    )

    indexed_row = SimplifiedRegimeFeatureRow(
        market_date=date(2026, 1, 2),
        v2_regime="NEUTRAL",
        breadth_ratio=Decimal("0.50"),
        percent_above_20dma=Decimal("0.50"),
        percent_above_50dma=Decimal("0.50"),
        percent_above_200dma=Decimal("0.50"),
        diagnostic_quality="HIGH_COVERAGE",
    )
    assert (
        classifier.classify(ResearchRegimeModel.BENCHMARK_TREND_ONLY, indexed_row)
        is ResearchRegimeLabel.INSUFFICIENT_INPUT
    )


def test_distribution_outcomes_and_quality_are_diagnostic_only(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    models = {row.model: row for row in engine.models()}
    assert models[
        ResearchRegimeModel.BENCHMARK_TREND_ONLY
    ].classification_coverage == Decimal("0.0000")
    assert models[
        ResearchRegimeModel.BENCHMARK_BREADTH
    ].classification_coverage == Decimal("1.0000")

    distributions = {
        row.model: row
        for row in engine.distributions()
        if row.model is ResearchRegimeModel.BENCHMARK_BREADTH
    }
    assert distributions[ResearchRegimeModel.BENCHMARK_BREADTH].bullish_dates == 1
    assert distributions[ResearchRegimeModel.BENCHMARK_BREADTH].bearish_dates == 1

    outcomes = {
        row.regime: row
        for row in engine.outcomes()
        if row.model is ResearchRegimeModel.BENCHMARK_BREADTH
        and row.quality_slice == "ALL"
        and row.weighting == "CANDIDATE"
    }
    assert outcomes[ResearchRegimeLabel.BULLISH].average_return == Decimal("5.0000")
    assert outcomes[ResearchRegimeLabel.BEARISH].stop_hit_rate == Decimal("1.0000")

    rendered = "\n".join(render_simplified_regime_outcomes(tuple(outcomes.values())))
    assert "Simplified Regime Outcomes" in rendered
    assert "target=1.0000" in rendered


def test_sector_impact_and_parsimony_do_not_require_sector_history(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)

    sector = engine.sector_maximum_impact()
    assert sector.classification is SectorImpactClass.SECTOR_UNUSED
    assert sector.maximum_plausible_label_changes == 0

    decision = engine.parsimony_decision()
    assert decision.primary_conclusion is _sector_unlikely_conclusion()
    assert decision.universe.integrity_passed is True

    rendered = "\n".join(render_regime_parsimony_decision(decision))
    assert "Regime Parsimony Decision" in rendered
    assert "Explicitly Prohibited Next Action" in rendered


def test_exports_are_machine_readable(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    json_path = export_regime_simplification_json(
        engine.sector_maximum_impact(),
        tmp_path / "sector.json",
    )
    csv_path = export_regime_simplification_csv(
        engine.distributions(),
        tmp_path / "distribution.csv",
    )

    assert json.loads(json_path.read_text(encoding="utf-8"))["classification"] == (
        SectorImpactClass.SECTOR_UNUSED.value
    )
    assert "model" in csv_path.read_text(encoding="utf-8").splitlines()[0]


def test_replay_cli_regime_simplification_reports_and_exports(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    store_path = _store(tmp_path)
    ledger_path = _ledger(tmp_path)
    monkeypatch.setenv("ALPHA_POINT_IN_TIME_ANALYTICAL_STORE", str(store_path))
    monkeypatch.setenv("ALPHA_CANDIDATE_LEARNING_LEDGER", str(ledger_path))

    runner = CliRunner()
    result = runner.invoke(app, ["replay", "simplified-regime-distribution"])
    assert result.exit_code == 0
    assert "Simplified Regime Distribution" in result.output

    output = tmp_path / "parsimony.json"
    result = runner.invoke(
        app,
        [
            "replay",
            "regime-parsimony-decision",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    assert "Regime parsimony decision written" in result.output
    assert json.loads(output.read_text(encoding="utf-8"))["primary_conclusion"] == (
        RegimeSimplificationConclusion.SECTOR_HISTORY_IS_UNLIKELY_TO_JUSTIFY_ACQUISITION.value
    )


def test_selection_interaction_threshold_and_incremental_reports(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)

    assert engine.threshold_stability()
    assert engine.incremental_value()
    assert engine.intervention()
    assert engine.setup_interaction()
    assert engine.retracement_interaction()
    assert engine.selection_effect()
    assert engine.interpretability()

    rendered = "\n".join(render_simplified_regime_distribution(engine.distributions()))
    assert "insufficient=3" in rendered


def _engine(tmp_path: Path) -> RegimeSimplificationAuditEngine:
    return RegimeSimplificationAuditEngine(
        store_path=_store(tmp_path),
        ledger_path=_ledger(tmp_path),
    )


def _store(tmp_path: Path) -> Path:
    path = tmp_path / "pit.duckdb"
    if path.exists():
        return path
    with duckdb.connect(str(path)) as con:
        con.execute(
            """
            CREATE TABLE diagnostic_pit_builds (
                build_id VARCHAR PRIMARY KEY,
                store_version VARCHAR,
                materialization_version VARCHAR,
                dataset_version VARCHAR,
                status VARCHAR,
                source_fingerprint VARCHAR,
                configuration_fingerprint VARCHAR,
                universe_fingerprint VARCHAR,
                breadth_fingerprint VARCHAR,
                sector_fingerprint VARCHAR,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                imported_at TIMESTAMP,
                completed_dates INTEGER,
                universe_rows INTEGER,
                security_rows INTEGER,
                breadth_rows INTEGER,
                sector_state_rows INTEGER,
                checkpoints INTEGER
            )
            """
        )
        con.execute(
            """
            INSERT INTO diagnostic_pit_builds VALUES (
                'build-1', '1', '1', 'dataset-1', 'COMPLETE',
                'source-fp', 'config-fp', 'universe-fp', 'breadth-fp',
                'sector-fp', '2026-01-01', '2026-01-01', '2026-01-01',
                3, 3, 3, 3, 0, 1
            )
            """
        )
        con.execute(
            """
            CREATE TABLE diagnostic_market_state_v2 (
                build_id VARCHAR,
                reconstruction_id VARCHAR PRIMARY KEY,
                market_date DATE,
                candidate_count INTEGER,
                v2_regime VARCHAR,
                breadth_ratio DOUBLE,
                percent_above_20dma DOUBLE,
                percent_above_50dma DOUBLE,
                percent_above_200dma DOUBLE,
                input_completeness VARCHAR,
                diagnostic_quality VARCHAR,
                classifier_version VARCHAR,
                classifier_fingerprint VARCHAR,
                dataset_version VARCHAR,
                created_at TIMESTAMP
            )
            """
        )
        con.executemany(
            """
            INSERT INTO diagnostic_market_state_v2 VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    "build-1",
                    "recon-1",
                    date(2026, 1, 1),
                    1,
                    "BULLISH",
                    0.62,
                    0.70,
                    0.66,
                    0.58,
                    "COMPLETE",
                    "HIGH_COVERAGE",
                    "v2",
                    "classifier-fp",
                    "dataset-1",
                    datetime(2026, 1, 1, tzinfo=UTC),
                ),
                (
                    "build-1",
                    "recon-2",
                    date(2026, 1, 2),
                    1,
                    "BEARISH",
                    0.40,
                    0.42,
                    0.39,
                    0.35,
                    "COMPLETE",
                    "HIGH_COVERAGE",
                    "v2",
                    "classifier-fp",
                    "dataset-1",
                    datetime(2026, 1, 2, tzinfo=UTC),
                ),
                (
                    "build-1",
                    "recon-3",
                    date(2026, 1, 3),
                    1,
                    "NEUTRAL",
                    0.50,
                    0.51,
                    0.49,
                    0.48,
                    "PARTIAL",
                    "LOW_COVERAGE",
                    "v2",
                    "classifier-fp",
                    "dataset-1",
                    datetime(2026, 1, 3, tzinfo=UTC),
                ),
            ],
        )
        con.execute(
            """
            CREATE TABLE diagnostic_market_state_v2_candidate_links (
                build_id VARCHAR,
                reconstruction_id VARCHAR,
                candidate_stable_id VARCHAR,
                candidate_decision_timestamp TIMESTAMP,
                recorded_candidate_regime VARCHAR,
                v2_regime VARCHAR,
                setup_type VARCHAR,
                final_verdict VARCHAR,
                entry_state VARCHAR,
                outcome_available BOOLEAN,
                link_status VARCHAR
            )
            """
        )
        con.executemany(
            """
            INSERT INTO diagnostic_market_state_v2_candidate_links VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    "build-1",
                    "recon-1",
                    "candidate-AAA",
                    datetime(2026, 1, 1, 9, tzinfo=UTC),
                    "BULLISH",
                    "BULLISH",
                    "BREAKOUT",
                    "BUY",
                    "ENTRY_READY",
                    True,
                    "MATCHED",
                ),
                (
                    "build-1",
                    "recon-2",
                    "candidate-BBB",
                    datetime(2026, 1, 2, 9, tzinfo=UTC),
                    "BEARISH",
                    "BEARISH",
                    "RETRACEMENT",
                    "AVOID",
                    "INVALID",
                    True,
                    "MATCHED",
                ),
                (
                    "build-1",
                    "recon-3",
                    "candidate-CCC",
                    datetime(2026, 1, 3, 9, tzinfo=UTC),
                    "NEUTRAL",
                    "NEUTRAL",
                    "BREAKOUT",
                    "WATCHLIST",
                    "WAITING_FOR_CONFIRMATION",
                    True,
                    "MATCHED",
                ),
            ],
        )
    return path


def _ledger(tmp_path: Path) -> Path:
    path = tmp_path / "learning.json"
    if path.exists():
        return path
    repository = LearningLedgerRepository(path)
    repository.save_records(
        (
            _record("candidate-AAA", "AAA", date(2026, 1, 1), "BUY"),
            _record("candidate-BBB", "BBB", date(2026, 1, 2), "AVOID"),
            _record("candidate-CCC", "CCC", date(2026, 1, 3), "WATCHLIST"),
        )
    )
    repository.upsert_outcomes(
        (
            _outcome("candidate-AAA", "AAA", Decimal("5"), target=True),
            _outcome("candidate-BBB", "BBB", Decimal("-3"), stop=True),
            _outcome("candidate-CCC", "CCC", Decimal("1")),
        )
    )
    return path


def _sector_unlikely_conclusion() -> RegimeSimplificationConclusion:
    return (
        RegimeSimplificationConclusion.SECTOR_HISTORY_IS_UNLIKELY_TO_JUSTIFY_ACQUISITION
    )


def _record(
    candidate_id: str,
    symbol: str,
    evaluation_date: date,
    verdict: str,
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id=candidate_id,
        run_id="run-1",
        evaluation_date=evaluation_date,
        symbol=symbol,
        final_verdict=verdict,
        capital_action=verdict,
        approved_for_deployment=verdict == "BUY",
        rejection_reasons=(),
        setup_type="BREAKOUT",
        market_regime="BULLISH",
        long_trade_permission=verdict == "BUY",
        strategy_score=Decimal("75"),
        confidence="HIGH",
        data_quality="HIGH",
        entry_zone_low=Decimal("100"),
        entry_zone_high=Decimal("102"),
        confirmation_entry=Decimal("103"),
        risk_stop=Decimal("95"),
        target_1=Decimal("112"),
        target_2=Decimal("120"),
        target_3=Decimal("128"),
        trailing_stop_plan="2 ATR",
        expected_holding_period="20 days",
        indicators_active=("price-volume",),
        indicator_scores={"price": "strong"},
        evidence_layers=("price-volume",),
        explanation="Synthetic diagnostic record.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _outcome(
    candidate_id: str,
    symbol: str,
    return_pct: Decimal,
    *,
    target: bool = False,
    stop: bool = False,
) -> CandidateForwardOutcome:
    return CandidateForwardOutcome(
        candidate_id=candidate_id,
        symbol=symbol,
        evaluated_at=datetime(2026, 2, 1, tzinfo=UTC),
        windows=(
            CandidateForwardWindowOutcome(
                window="20d",
                forward_open=Decimal("100"),
                forward_high=Decimal("110"),
                forward_low=Decimal("95"),
                forward_close=Decimal("105"),
                forward_return_pct_from_close=return_pct,
                forward_return_pct_from_entry=return_pct,
                max_favourable_excursion_pct=return_pct.copy_abs(),
                max_adverse_excursion_pct=Decimal("-1.5"),
                target_1_touched=target,
                risk_stop_touched=stop,
                outcome_label=(
                    CandidateOutcomeLabel.WOULD_HAVE_WON
                    if return_pct > 0
                    else CandidateOutcomeLabel.WOULD_HAVE_LOST
                ),
            ),
        ),
    )
