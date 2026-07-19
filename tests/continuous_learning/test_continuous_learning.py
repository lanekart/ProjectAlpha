from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.cli import app, learning_app
from alpha.continuous_learning.concept_drift_engine import ConceptDriftEngine
from alpha.continuous_learning.confidence_calibration import (
    ConfidenceCalibrationEngine,
)
from alpha.continuous_learning.continuous_learning_engine import (
    ContinuousLearningEngine,
)
from alpha.continuous_learning.feature_drift_engine import FeatureDriftEngine
from alpha.continuous_learning.learning_registry import ContinuousLearningRegistry
from alpha.continuous_learning.models import (
    DriftStatus,
    LearningConfidence,
    LearningEvent,
    LearningOutcomeStatus,
    OutcomeObservation,
    StrategyHealthClassification,
)
from alpha.continuous_learning.outcome_collector import OutcomeCollector
from alpha.continuous_learning.prediction_tracker import PredictionTracker
from alpha.continuous_learning.rendering import (
    render_calibration,
    render_collection,
    render_drift,
    render_learning_report,
    render_outcomes,
    render_recommendations,
    render_strategy_health,
)
from alpha.continuous_learning.research_trigger_engine import ResearchTriggerEngine
from alpha.continuous_learning.strategy_health_monitor import StrategyHealthMonitor
from alpha.forward_validation.validation_registry import ForwardValidationRegistry
from alpha.performance_intelligence.ledger import RecommendationLedgerRepository
from alpha.performance_intelligence.models import (
    RecommendationExitReason,
    RecommendationLedgerEntry,
    RecommendationOutcome,
    RecommendationOutcomeStatus,
)
from alpha.research.diagnostic_registry import default_diagnostic_registry


def test_outcome_collection_preserves_observed_trade_fields() -> None:
    entry = _entry(1)
    outcome = _outcome(1, realised=Decimal("8"), stop=False, target=True)

    observations = OutcomeCollector().collect(
        entries=(entry,), outcomes=(outcome,), snapshots=(), events=()
    )

    assert len(observations) == 1
    item = observations[0]
    assert item.status is LearningOutcomeStatus.EXITED
    assert item.entry_achieved is True
    assert item.target_1_hit is True
    assert item.stop_hit is False
    assert item.realised_return_pct == Decimal("8.00")
    assert item.mfe_pct == Decimal("10.00")
    assert item.mae_pct == Decimal("-2.00")
    assert item.holding_period_days == 5


def test_prediction_tracker_compares_frozen_direction_and_actual() -> None:
    winning = _observation(1, realised=Decimal("3"), confidence="HIGH")
    losing = _observation(2, realised=Decimal("-2"), confidence="HIGH")

    assessments = PredictionTracker().assess((winning, losing))

    assert assessments[0].recommendation_correct is True
    assert assessments[0].direction_correct is True
    assert assessments[1].recommendation_correct is False
    assert assessments[1].predicted_probability == Decimal("0.80")


def test_concept_drift_detects_significant_deterioration() -> None:
    rows = tuple(
        _observation(index, realised=Decimal("5") if index < 20 else Decimal("-5"))
        for index in range(40)
    )

    drifts = ConceptDriftEngine().assess(rows)

    precision = next(item for item in drifts if item.dimension == "PRECISION")
    expectancy = next(item for item in drifts if item.dimension == "EXPECTANCY")
    assert precision.status is DriftStatus.SIGNIFICANT_DRIFT
    assert expectancy.status is DriftStatus.SIGNIFICANT_DRIFT


def test_feature_drift_does_not_treat_missing_sector_as_market_shift() -> None:
    rows = tuple(_observation(index, sector=None) for index in range(40))

    sector = next(
        item
        for item in FeatureDriftEngine().assess(rows)
        if item.dimension == "SECTOR_MIX"
    )

    assert sector.status is DriftStatus.UNKNOWN
    assert sector.confidence is LearningConfidence.INSUFFICIENT


def test_confidence_calibration_reports_brier_and_reliability() -> None:
    observations = tuple(
        _observation(index, realised=Decimal("2") if index < 10 else Decimal("-2"))
        for index in range(20)
    )
    predictions = PredictionTracker().assess(observations)

    report = ConfidenceCalibrationEngine().assess(predictions)

    assert report.completed_predictions == 20
    assert report.brier_score == Decimal("0.3400")
    assert report.expected_calibration_error == Decimal("0.3000")
    assert report.status == "SIGNIFICANT_MISCALIBRATION"


def test_calibration_never_escalates_two_observations() -> None:
    predictions = PredictionTracker().assess(
        (
            _observation(1, realised=Decimal("2")),
            _observation(2, realised=Decimal("-2")),
        )
    )

    report = ConfidenceCalibrationEngine().assess(predictions)

    assert report.brier_score == Decimal("0.3400")
    assert report.status == "INSUFFICIENT_EVIDENCE"
    assert report.confidence is LearningConfidence.INSUFFICIENT


def test_strategy_health_can_be_healthy_but_never_auto_promotes() -> None:
    rows = tuple(_observation(index, realised=Decimal("2")) for index in range(30))

    health = StrategyHealthMonitor().assess(rows)

    assert len(health) == 1
    assert health[0].classification is StrategyHealthClassification.HEALTHY
    assert health[0].health_score is not None
    assert any("cannot retire" in item for item in health[0].evidence)


def test_research_trigger_references_evidence() -> None:
    rows = tuple(
        _observation(index, realised=Decimal("5") if index < 20 else Decimal("-5"))
        for index in range(40)
    )
    predictions = PredictionTracker().assess(rows)
    drifts = ConceptDriftEngine().assess(rows)
    health = StrategyHealthMonitor().assess(rows)
    calibration = ConfidenceCalibrationEngine().assess(predictions)

    recommendations = ResearchTriggerEngine().recommend(
        drifts=drifts,
        health=health,
        calibration=calibration,
    )

    assert recommendations
    assert all(item.evidence_ids for item in recommendations)
    assert all(item.production_influence is False for item in recommendations)


def test_registry_is_idempotent_and_exports_json_csv(tmp_path: Path) -> None:
    registry = ContinuousLearningRegistry(tmp_path / "learning.json")
    observation = _observation(1, realised=Decimal("2"))
    event = LearningEvent(
        event_id="event-1",
        occurred_at=observation.observed_at,
        recommendation_id=observation.recommendation_id,
        event_type="TEST",
        learning="A deterministic test learning.",
        evidence=(observation.evidence_hash,),
        confidence=LearningConfidence.LOW,
        suggested_research=None,
        source_observation_id=observation.observation_id,
    )

    assert registry.append_observations((observation,)) == 1
    assert registry.append_observations((observation,)) == 0
    assert registry.append_learning_events((event,)) == 1
    assert registry.append_learning_events((event,)) == 0
    assert registry.export_json(tmp_path / "export.json").exists()
    csv_path = registry.export_csv(tmp_path / "export.csv")
    assert "OUTCOME_OBSERVATION" in csv_path.read_text(encoding="utf-8")
    assert registry.latest_observations() == (observation,)


def test_registry_accepts_legacy_event_without_rewriting_it(tmp_path: Path) -> None:
    registry = ContinuousLearningRegistry(tmp_path / "learning.json")
    observation = _observation(1)
    event = LearningEvent(
        event_id="event-legacy",
        occurred_at=observation.observed_at,
        recommendation_id=observation.recommendation_id,
        event_type="TEST",
        learning="Legacy event remains immutable.",
        evidence=(observation.evidence_hash,),
        confidence=LearningConfidence.LOW,
        suggested_research=None,
        source_observation_id=observation.observation_id,
        outcome=observation.status.value,
    )
    registry.append_learning_events((event,))
    payload = json.loads(registry.path.read_text(encoding="utf-8"))
    del payload["learning_events"][0]["outcome"]
    registry.path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    assert registry.append_learning_events((event,)) == 0
    stored = json.loads(registry.path.read_text(encoding="utf-8"))
    assert "outcome" not in stored["learning_events"][0]


def test_learning_models_reject_production_influence() -> None:
    observation = _observation(1)

    with pytest.raises(ValueError, match="cannot influence production"):
        LearningEvent(
            event_id="forbidden",
            occurred_at=observation.observed_at,
            recommendation_id=observation.recommendation_id,
            event_type="TEST",
            learning="Forbidden production mutation.",
            evidence=(observation.evidence_hash,),
            confidence=LearningConfidence.LOW,
            suggested_research=None,
            source_observation_id=observation.observation_id,
            outcome=observation.status.value,
            production_influence=True,
        )


def test_continuous_engine_collection_and_rendering(tmp_path: Path) -> None:
    performance = RecommendationLedgerRepository(tmp_path / "performance.json")
    performance.save_entry(_entry(1))
    performance.upsert_outcome(_outcome(1, realised=Decimal("3")))
    engine = ContinuousLearningEngine(
        performance_repository=performance,
        forward_registry=ForwardValidationRegistry(tmp_path / "forward.json"),
        learning_registry=ContinuousLearningRegistry(tmp_path / "learning.json"),
    )

    summary = engine.collect()
    report = engine.report(collect_first=False)

    assert summary.observations_inserted == 1
    assert summary.registry_recommendations == 1
    assert summary.retained_historical_recommendations == 0
    assert summary.learning_events_inserted == 2
    assert report.analytically_eligible_recommendations == 1
    assert report.quarantined_recommendations == 0
    assert any(
        item.event_type == "RESEARCH_TRIGGER" and item.suggested_research is not None
        for item in engine.learning_registry.load_learning_events()
    )
    assert any(
        item.outcome == "EXITED"
        for item in engine.learning_registry.load_learning_events()
    )
    assert "Continuous Learning Collection" in "\n".join(render_collection(summary))
    assert "Continuous Learning Outcomes" in "\n".join(render_outcomes(report.outcomes))
    assert "Drift Report" in "\n".join(render_drift(report.drifts))
    assert "Strategy Health" in "\n".join(
        render_strategy_health(report.strategy_health)
    )
    assert "Confidence Calibration" in "\n".join(render_calibration(report.calibration))
    assert "Research Recommendations" in "\n".join(
        render_recommendations(report.research_recommendations)
    )
    assert "Executive Continuous Learning Report" in "\n".join(
        render_learning_report(report)
    )


def test_report_quarantines_registry_rows_without_current_source_provenance(
    tmp_path: Path,
) -> None:
    performance = RecommendationLedgerRepository(tmp_path / "performance.json")
    performance.save_entry(_entry(1))
    registry = ContinuousLearningRegistry(tmp_path / "learning.json")
    registry.append_observations((_observation(99, realised=Decimal("9")),))
    engine = ContinuousLearningEngine(
        performance_repository=performance,
        forward_registry=ForwardValidationRegistry(tmp_path / "forward.json"),
        learning_registry=registry,
    )

    engine.collect()
    report = engine.report(collect_first=False)

    assert len(report.outcomes) == 2
    assert report.analytically_eligible_recommendations == 1
    assert report.quarantined_recommendations == 1
    assert report.calibration.completed_predictions == 0
    assert all(item.recommendation_id != "rec-99" for item in report.predictions)
    rendered = "\n".join(
        render_outcomes(
            report.outcomes,
            analytically_eligible_recommendations=(
                report.analytically_eligible_recommendations
            ),
            quarantined_recommendations=report.quarantined_recommendations,
        )
    )
    assert "Quarantined Historical Recommendations: 1" in rendered


def test_cli_and_ird_integration_are_registered() -> None:
    names = {command.name for command in learning_app.registered_commands}
    assert {
        "collect",
        "outcomes",
        "drift",
        "strategy-health",
        "calibration",
        "recommendations",
        "report",
    } <= names
    registry = default_diagnostic_registry(discover_plugins=False)
    assert "continuous-learning-evidence" in registry.plugin_ids


def test_cli_collect_and_report_output(tmp_path: Path) -> None:
    ledger_path = tmp_path / "performance.json"
    forward_path = tmp_path / "forward.json"
    learning_path = tmp_path / "learning.json"
    repository = RecommendationLedgerRepository(ledger_path)
    repository.save_entry(_entry(1))
    repository.upsert_outcome(_outcome(1, realised=Decimal("3")))
    runner = CliRunner()

    collected = runner.invoke(
        app,
        [
            "learning",
            "collect",
            "--ledger",
            str(ledger_path),
            "--forward-registry",
            str(forward_path),
            "--learning-registry",
            str(learning_path),
        ],
    )
    reported = runner.invoke(
        app,
        [
            "learning",
            "report",
            "--ledger",
            str(ledger_path),
            "--forward-registry",
            str(forward_path),
            "--learning-registry",
            str(learning_path),
        ],
    )

    assert collected.exit_code == 0
    assert "New Immutable Observations: 1" in collected.stdout
    assert reported.exit_code == 0
    assert "Executive Continuous Learning Report" in reported.stdout
    assert "PRODUCTION_INFLUENCE=false" in reported.stdout


def _entry(index: int) -> RecommendationLedgerEntry:
    generated = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=index)
    return RecommendationLedgerEntry(
        recommendation_id=f"rec-{index}",
        generated_at=generated,
        symbol=f"S{index}",
        final_verdict="BUY",
        confidence="HIGH",
        score=Decimal("80"),
        setup_type="BREAKOUT",
        setup_state="ENTRY_READY",
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("100"),
        confirmation_entry=Decimal("101"),
        stop_loss=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        trailing_stop_strategy="2 ATR",
        holding_period="20 days",
        market_regime="BULL",
        sector="TECH",
        key_indicator_snapshot={"atr": "2", "average_volume": "100000"},
        statistical_edge_snapshot={},
        data_completeness_snapshot={"status": "COMPLETE"},
        source_run_id="run-1",
    )


def _outcome(
    index: int,
    *,
    realised: Decimal,
    stop: bool = False,
    target: bool = False,
) -> RecommendationOutcome:
    return RecommendationOutcome(
        recommendation_id=f"rec-{index}",
        symbol=f"S{index}",
        status=RecommendationOutcomeStatus.EXITED,
        entry_triggered=True,
        entry_date=date(2025, 1, 2),
        entry_price=Decimal("101"),
        stop_hit=stop,
        target_1_hit=target,
        target_2_hit=False,
        target_3_hit=False,
        trailing_stop_hit=False,
        exit_date=date(2025, 1, 7),
        exit_price=Decimal("109"),
        exit_reason=(
            RecommendationExitReason.STOP_LOSS
            if stop
            else RecommendationExitReason.TARGET_1
        ),
        maximum_favorable_excursion=Decimal("10"),
        maximum_adverse_excursion=Decimal("-2"),
        realized_r_multiple=Decimal("1.5"),
        realized_percent_return=realised,
        holding_period_bars=4,
        holding_period_days=5,
    )


def _observation(
    index: int,
    *,
    realised: Decimal = Decimal("1"),
    confidence: str = "HIGH",
    sector: str | None = "TECH",
) -> OutcomeObservation:
    timestamp = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=index)
    return OutcomeObservation(
        observation_id=f"obs-{index}",
        recommendation_id=f"rec-{index}",
        observed_at=timestamp + timedelta(days=5),
        generated_at=timestamp,
        symbol=f"S{index}",
        final_verdict="BUY",
        predicted_confidence=confidence,
        predicted_score=Decimal("80"),
        setup_type="BREAKOUT",
        status=LearningOutcomeStatus.EXITED,
        entry_achieved=True,
        entry_missed=False,
        stop_hit=realised < 0,
        target_1_hit=realised > 0,
        target_2_hit=False,
        target_3_hit=False,
        time_exit=False,
        mfe_pct=Decimal("5"),
        mae_pct=Decimal("-2"),
        realised_return_pct=realised,
        holding_period_days=5,
        market_regime="BULL",
        sector=sector,
        volatility=Decimal("2"),
        liquidity=Decimal("100000"),
        source="test",
        evidence_hash=f"hash-{index}",
    )
