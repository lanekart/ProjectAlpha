from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from typer.testing import CliRunner

from alpha.candidate_learning.market_state_persistence_audit import (
    MarketStatePersistenceAuditEngine,
    MarketStateReconstructionStatus,
)
from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.candidate_learning.recorder import CandidateMarketStateContext
from alpha.cli import app
from alpha.market_intelligence import (
    AccumulationPhase,
    BreadthCondition,
    CorrelationRisk,
    DistributionPhase,
    IntelligenceAssessment,
    IntelligenceBias,
    LiquidityQuality,
    MarketStatePersistenceStatus,
    MarketStateSnapshot,
    MarketStateSnapshotConflictError,
    MarketStateSnapshotRepository,
    SectorLeadership,
    SectorRotationAssessment,
    SectorRotationPhase,
)
from alpha.market_intelligence.intelligence import MarketIntelligenceReport


def test_market_state_snapshot_identity_is_stable() -> None:
    first = _snapshot()
    second = MarketStateSnapshot.from_market_report(
        _market_report(),
        as_of_timestamp=datetime(2026, 1, 2, 10, 0, tzinfo=UTC),
        created_at=datetime(2026, 1, 2, 10, 1, tzinfo=UTC),
    )

    assert first.snapshot_id == second.snapshot_id
    assert first.classifier_version == "market-intelligence-composite-v1"
    assert first.input_completeness.value == "PARTIAL"


def test_snapshot_repository_is_idempotent_and_conflict_safe(tmp_path) -> None:
    repository = MarketStateSnapshotRepository(tmp_path / "snapshots.json")
    snapshot = _snapshot()

    first = repository.save(snapshot)
    second = repository.save(snapshot)

    assert first.status is MarketStatePersistenceStatus.SNAPSHOT_PERSISTED
    assert second.status is MarketStatePersistenceStatus.SNAPSHOT_ALREADY_EXISTS
    assert len(repository.load_all()) == 1

    conflicting = MarketStateSnapshot(
        **{
            **snapshot.as_dict(),
            "classifier_regime": "NEGATIVE",
            "input_completeness": snapshot.input_completeness,
            "fallback_reason": snapshot.fallback_reason,
            "classifier_inputs": snapshot.classifier_inputs,
            "missing_fields": snapshot.missing_fields,
            "source_lineage": snapshot.source_lineage,
            "market_date": snapshot.market_date,
            "as_of_timestamp": snapshot.as_of_timestamp,
            "source_timestamp": snapshot.source_timestamp,
            "created_at": snapshot.created_at,
            "benchmark_close": snapshot.benchmark_close,
            "benchmark_return_1d": snapshot.benchmark_return_1d,
            "benchmark_return_5d": snapshot.benchmark_return_5d,
            "benchmark_return_20d": snapshot.benchmark_return_20d,
            "benchmark_distance_20dma": snapshot.benchmark_distance_20dma,
            "benchmark_distance_50dma": snapshot.benchmark_distance_50dma,
            "benchmark_distance_200dma": snapshot.benchmark_distance_200dma,
            "benchmark_atr": snapshot.benchmark_atr,
            "benchmark_volatility": snapshot.benchmark_volatility,
            "breadth_ratio": snapshot.breadth_ratio,
            "percent_above_20dma": snapshot.percent_above_20dma,
            "percent_above_50dma": snapshot.percent_above_50dma,
            "percent_above_200dma": snapshot.percent_above_200dma,
            "sector_dispersion": snapshot.sector_dispersion,
            "market_trend_score": snapshot.market_trend_score,
            "breadth_score": snapshot.breadth_score,
            "volatility_score": snapshot.volatility_score,
            "participation_score": snapshot.participation_score,
            "classifier_confidence": snapshot.classifier_confidence,
        }
    )
    try:
        repository.save(conflicting)
    except MarketStateSnapshotConflictError:
        pass
    else:
        raise AssertionError("expected conflicting snapshot to be rejected")


def test_candidate_record_persists_market_state_linkage() -> None:
    snapshot = _snapshot()
    record = _candidate_record(
        market_state_context=CandidateMarketStateContext(
            snapshot_id=snapshot.snapshot_id,
            as_of=snapshot.as_of_timestamp,
            fallback_applied=snapshot.fallback_applied,
            completeness=snapshot.input_completeness.value,
            classifier_version=snapshot.classifier_version,
        )
    )
    restored = CandidateDecisionRecord.from_dict(record.as_dict())

    assert restored.market_state_snapshot_id == snapshot.snapshot_id
    assert restored.market_state_as_of == snapshot.as_of_timestamp
    assert restored.market_state_completeness == "PARTIAL"
    assert restored.classifier_version == "market-intelligence-composite-v1"


def test_market_state_audit_prefers_authoritative_snapshot() -> None:
    snapshot = _snapshot()
    record = _candidate_record(
        market_state_context=CandidateMarketStateContext(
            snapshot_id=snapshot.snapshot_id,
            as_of=snapshot.as_of_timestamp,
            fallback_applied=snapshot.fallback_applied,
            completeness=snapshot.input_completeness.value,
            classifier_version=snapshot.classifier_version,
        )
    )

    report = MarketStatePersistenceAuditEngine().analyze(
        records=(record,),
        outcomes=(),
        authoritative_snapshots=(snapshot,),
    )

    assert report.authoritative_snapshots_available == 1
    assert (
        report.snapshots[0].reconstruction_status
        is MarketStateReconstructionStatus.AUTHORITATIVE
    )
    assert report.snapshots[0].classifier_version == snapshot.classifier_version


def test_market_state_cli_renders_snapshot_commands(tmp_path, monkeypatch) -> None:
    path = tmp_path / "snapshots.json"
    monkeypatch.setenv("ALPHA_MARKET_STATE_SNAPSHOT_LEDGER", str(path))
    snapshot = _snapshot()
    MarketStateSnapshotRepository(path).save(snapshot)

    latest = CliRunner().invoke(app, ["market-state", "latest"])
    show = CliRunner().invoke(
        app,
        ["market-state", "show", "--snapshot-id", snapshot.snapshot_id],
    )
    coverage = CliRunner().invoke(app, ["market-state", "coverage"])

    assert latest.exit_code == 0
    assert "Market State Snapshot" in latest.output
    assert snapshot.snapshot_id in latest.output
    assert show.exit_code == 0
    assert "Classifier Version: market-intelligence-composite-v1" in show.output
    assert coverage.exit_code == 0
    assert "Total Snapshots: 1" in coverage.output


def _snapshot() -> MarketStateSnapshot:
    return MarketStateSnapshot.from_market_report(
        _market_report(),
        as_of_timestamp=datetime(2026, 1, 2, 10, 0, tzinfo=UTC),
        created_at=datetime(2026, 1, 2, 10, 1, tzinfo=UTC),
    )


def _market_report() -> MarketIntelligenceReport:
    return MarketIntelligenceReport(
        symbol="NIFTY",
        observed_on=date(2026, 1, 2),
        accumulation=IntelligenceAssessment(
            name="Accumulation",
            score=Decimal("0.70"),
            bias=IntelligenceBias.POSITIVE,
            classification=AccumulationPhase.MODERATE_ACCUMULATION.value,
            reasons=("delivery rising",),
            metrics={"delivery": Decimal("0.62")},
        ),
        distribution=IntelligenceAssessment(
            name="Distribution",
            score=Decimal("0.20"),
            bias=IntelligenceBias.POSITIVE,
            classification=DistributionPhase.NO_DISTRIBUTION.value,
            reasons=("selling pressure low",),
        ),
        liquidity=IntelligenceAssessment(
            name="Liquidity",
            score=Decimal("0.80"),
            bias=IntelligenceBias.POSITIVE,
            classification=LiquidityQuality.HIGH.value,
            reasons=("turnover healthy",),
            metrics={"volatility_penalty": Decimal("0.18")},
        ),
        breadth=IntelligenceAssessment(
            name="Breadth",
            score=Decimal("0.75"),
            bias=IntelligenceBias.POSITIVE,
            classification=BreadthCondition.BROAD_PARTICIPATION.value,
            reasons=("advances: 120", "declines: 70", "unchanged: 10"),
            metrics={"advance_ratio": Decimal("0.60")},
        ),
        sector_rotation=SectorRotationAssessment(
            phase=SectorRotationPhase.LEADERSHIP_EXPANSION,
            leaders=(
                SectorLeadership(
                    sector="BANKING",
                    score=Decimal("0.80"),
                    rank=1,
                    reasons=("leadership expanding",),
                ),
                SectorLeadership(
                    sector="IT",
                    score=Decimal("0.50"),
                    rank=2,
                    reasons=("lagging",),
                ),
            ),
            score=Decimal("0.72"),
            reasons=("sector participation broad",),
        ),
        correlation=IntelligenceAssessment(
            name="Correlation",
            score=Decimal("0.65"),
            bias=IntelligenceBias.POSITIVE,
            classification=CorrelationRisk.MODERATE.value,
            reasons=("correlation acceptable",),
        ),
        composite_score=Decimal("0.68"),
        bias=IntelligenceBias.POSITIVE,
        reasons=("composite constructive",),
    )


def _candidate_record(
    *,
    market_state_context: CandidateMarketStateContext | None,
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id="candidate-1",
        run_id="run-1",
        evaluation_date=date(2026, 1, 2),
        symbol="ABC",
        company_name="ABC Ltd",
        sector="BANKING",
        final_verdict="BUY",
        capital_action="BUY",
        approved_for_deployment=True,
        rejection_reasons=(),
        setup_type="Momentum Continuation",
        market_regime="POSITIVE",
        long_trade_permission=True,
        strategy_score=Decimal("82"),
        confidence="HIGH",
        data_quality="GOOD",
        entry_zone_low=Decimal("100"),
        entry_zone_high=Decimal("102"),
        confirmation_entry=Decimal("103"),
        risk_stop=Decimal("95"),
        target_1=Decimal("115"),
        target_2=Decimal("125"),
        target_3=Decimal("135"),
        trailing_stop_plan="2 ATR below highest close",
        expected_holding_period="20 days",
        indicators_active=("price", "volume"),
        indicator_scores={"price": "0.80", "volume": "0.70"},
        evidence_layers=("price-volume constructive",),
        explanation="Test record",
        created_at=datetime(2026, 1, 2, 10, 1, tzinfo=UTC),
        market_state_snapshot_id=(
            None if market_state_context is None else market_state_context.snapshot_id
        ),
        market_state_as_of=(
            None if market_state_context is None else market_state_context.as_of
        ),
        market_state_fallback_applied=(
            None
            if market_state_context is None
            else market_state_context.fallback_applied
        ),
        market_state_completeness=(
            None if market_state_context is None else market_state_context.completeness
        ),
        classifier_version=(
            None
            if market_state_context is None
            else market_state_context.classifier_version
        ),
    )
