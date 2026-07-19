from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from alpha.analysis.signals.daily_report import DailyMarketReport
from alpha.application.intelligence_inputs import IntelligenceInputBuilder
from alpha.canonical_integrity_audit.attribution import ZeroTradeAttributionEngine
from alpha.canonical_integrity_audit.case_studies import CaseStudyEngine
from alpha.canonical_integrity_audit.classification import economic_attribution
from alpha.canonical_integrity_audit.exports import CanonicalIntegrityAuditExporter
from alpha.canonical_integrity_audit.models import (
    CANONICAL_POLICY_ID,
    NO_POLICY_RELAXATION,
    PRODUCTION_INFLUENCE,
    CanonicalIntegrityAuditReport,
    CanonicalTradeEvent,
    CoverageClassification,
    EconomicProblem,
    EvidenceClass,
    FailureCategory,
    IntegrityAuditSummary,
    MajorOpportunityEvent,
    OpportunityCoverageRecord,
    OpportunityDefinition,
    ParityClassification,
    PineExperimentMetadata,
    PineTrade,
    RuntimeFailureRecord,
    RuntimeReplayComparison,
    ZeroTradeReason,
)
from alpha.canonical_integrity_audit.opportunity_coverage import (
    MajorOpportunityCoverageEngine,
)
from alpha.canonical_integrity_audit.opportunity_events import (
    MajorOpportunityEventEngine,
)
from alpha.canonical_integrity_audit.parity_engine import TradingViewParityEngine
from alpha.canonical_integrity_audit.parity_inputs import frozen_policy_manifest
from alpha.canonical_integrity_audit.parity_matching import match_pine_trade
from alpha.canonical_integrity_audit.pine_trade_import import PineTradeImporter
from alpha.canonical_integrity_audit.research_integration import (
    record_integrity_experiment,
    research_diagnostic_plugins,
)
from alpha.canonical_integrity_audit.runtime_failures import (
    classify_runtime_failure,
    group_runtime_failures,
)
from alpha.canonical_universe_audit.canonical_runner import (
    CanonicalAuditInputBuilder,
    _valid_ohlcv_rows,
)
from alpha.canonical_universe_audit.models import CandidateOutcomeRecord
from alpha.cli import app
from alpha.recommendation_intelligence import RecommendationEngine
from alpha.research.research_registry import ResearchExperimentRegistry


def test_policy_is_frozen_and_production_isolated() -> None:
    manifest = frozen_policy_manifest(source_commit="test-commit")

    assert manifest.policy_id == CANONICAL_POLICY_ID
    assert manifest.source_commit == "test-commit"
    assert manifest.weights["price_structure"] == "0.20"
    assert manifest.thresholds["buy"] == "75"
    assert PRODUCTION_INFLUENCE is False
    assert NO_POLICY_RELAXATION is True


def test_diagnostic_adapter_repairs_only_allocation_drawdown_contract() -> None:
    observed_on = date(2025, 1, 2)
    frame = _extreme_price_frame(observed_on)
    analysis = DailyMarketReport().generate(frame)["analysis"]
    builder = CanonicalAuditInputBuilder(history_window=250)
    pre_repair = IntelligenceInputBuilder.build(
        builder,
        observed_on=observed_on,
        analysis=analysis,
    )
    recommendations = RecommendationEngine().build(
        pre_repair.recommendation_candidates,
        portfolio=pre_repair.recommendation_portfolio_context,
    )

    assert any(item.expected_value.expected_drawdown > 1 for item in recommendations)
    with pytest.raises(ValueError, match="expected drawdown"):
        pre_repair.allocation_candidates(recommendations)

    repaired = builder.build(observed_on=observed_on, analysis=analysis)
    repaired_recommendations = RecommendationEngine().build(
        repaired.recommendation_candidates,
        portfolio=repaired.recommendation_portfolio_context,
    )
    allocation = repaired.allocation_candidates(repaired_recommendations)

    assert tuple(item.final_score for item in repaired_recommendations) == tuple(
        item.final_score for item in recommendations
    )
    assert all(item.expected_drawdown <= 1 for item in allocation)
    assert any(
        item.expected_value.expected_drawdown > 1 for item in repaired_recommendations
    )


def test_runtime_failure_classification_and_grouping_are_deterministic() -> None:
    category, stage = classify_runtime_failure(
        ValueError("expected drawdown must be between 0 and 1"),
        source_file="alpha/portfolio_intelligence/allocation.py",
    )
    records = (
        _runtime(date(2024, 1, 2), "AAA"),
        _runtime(date(2024, 1, 2), "BBB"),
        _runtime(date(2024, 1, 3), "AAA"),
    )

    groups = group_runtime_failures(records)

    assert category is FailureCategory.DATA_INVALID
    assert stage == "PORTFOLIO_ALLOCATION_ADAPTER"
    assert groups[0].failure_days == 2
    assert groups[0].affected_candidates == 3
    assert groups[0].repeated


def test_invalid_ohlcv_repair_excludes_bar_without_fabricating_price() -> None:
    frame = pd.DataFrame(
        (
            {"symbol": "BAD", "open": 100, "high": 105, "low": 95, "close": 110},
            {"symbol": "GOOD", "open": 100, "high": 105, "low": 95, "close": 102},
        )
    )

    filtered = _valid_ohlcv_rows(frame)

    assert tuple(filtered["symbol"]) == ("GOOD",)
    assert filtered.iloc[0]["close"] == 102


def test_pine_csv_import_and_screenshot_evidence_classification(tmp_path: Path) -> None:
    metadata = {
        "symbol": "AAA",
        "exchange": "NSE",
        "chart_timeframe": "1D",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "entry_threshold": "75",
        "strategy_family": "BREAKOUT",
        "setup_selection": "BREAKOUT",
        "commission": "0.1",
        "slippage": "0.05",
        "position_size": "100000",
        "market_regime_setting": "OFF",
        "sector_setting": "OFF",
        "script_version": "1.0",
        "framework_version": "1.0",
        "evidence_class": "SCREENSHOT_DERIVED",
    }
    (tmp_path / "experiment.json").write_text(json.dumps(metadata), encoding="utf-8")
    (tmp_path / "trades.csv").write_text(
        "symbol,exchange,entry_date,entry_price,stop,target_1,score,setup,strategy\n"
        "AAA,NSE,2024-02-01,100,95,110,80,BREAKOUT,BREAKOUT\n",
        encoding="utf-8",
    )

    experiments, trades = PineTradeImporter().import_directory(tmp_path)

    assert experiments[0].evidence_class is EvidenceClass.SCREENSHOT_DERIVED
    assert trades[0].evidence_class is EvidenceClass.CSV_TRADE_LEVEL
    assert trades[0].entry_price == Decimal("100")
    assert trades[0].score == Decimal("80")


@pytest.mark.parametrize(
    ("changes", "expected"),
    (
        ({}, ParityClassification.EXACT_MATCH),
        (
            {"entry": Decimal("100.20")},
            ParityClassification.SEMANTIC_MATCH,
        ),
        (
            {"score": Decimal("78")},
            ParityClassification.ALPHA_CANDIDATE_DIFFERENT_SCORE,
        ),
        (
            {"setup": "PULLBACK"},
            ParityClassification.ALPHA_SETUP_NOT_DETECTED,
        ),
        (
            {"observed_on": date(2024, 1, 3)},
            ParityClassification.ALPHA_ENTRY_TIMING_DIFFERENCE,
        ),
        (
            {"rejection_reason": "WEAK_VERDICT", "final_gate": "WEAK_VERDICT"},
            ParityClassification.ALPHA_CANDIDATE_REJECTED,
        ),
    ),
)
def test_progressive_pine_matching(
    changes: dict[str, object],
    expected: ParityClassification,
) -> None:
    alpha = replace(_candidate(), **changes)
    assert match_pine_trade(_pine(), (alpha,)).classification is expected


def test_runtime_blocked_pine_match() -> None:
    match = match_pine_trade(
        _pine(),
        (),
        (_runtime(date(2024, 1, 2), "AAA"),),
    )

    assert match.classification is ParityClassification.ALPHA_RUNTIME_BLOCKED


def test_parity_engine_reports_ranked_divergence() -> None:
    trades = (_pine(), replace(_pine(), trade_id="pine-2", symbol="MISSING"))

    matches, divergences = TradingViewParityEngine().compare(
        pine_trades=trades,
        alpha_events=(_candidate(),),
    )

    assert len(matches) == 2
    assert divergences[0].divergence_stage == "ALPHA_SETUP_NOT_DETECTED"
    assert divergences[0].share == Decimal("0.5")


def test_major_event_construction_merges_duplicate_windows() -> None:
    start = date(2024, 1, 1)
    closes = (100, 105, 112, 125, 130, 132, 133)
    frame = pd.DataFrame(
        {
            "symbol": ["AAA"] * len(closes),
            "trade_date": [
                start + timedelta(days=index) for index in range(len(closes))
            ],
            "high": [value + 2 for value in closes],
            "low": [value - 2 for value in closes],
            "close": closes,
            "volume": [1000, 900, 1100, 1800, 1500, 1200, 1000],
        }
    )

    events = MajorOpportunityEventEngine().construct_from_frame(
        frame,
        definitions=(
            OpportunityDefinition("UP_20_WITHIN_4", Decimal("0.20"), 4),
            OpportunityDefinition("UP_30_WITHIN_4", Decimal("0.30"), 4),
        ),
    )

    assert len(events) == 1
    assert events[0].forward_return >= Decimal("0.20")
    assert events[0].time_to_peak > 0


def test_opportunity_coverage_classifies_captured_partial_rejected_missed_runtime() -> (
    None
):
    events = tuple(
        replace(_event(), event_id=f"event-{index}", symbol=symbol)
        for index, symbol in enumerate(("CAP", "PART", "REJ", "MISS", "RUN"), start=1)
    )
    candidates = (
        replace(_candidate(), symbol="CAP", candidate_id="cap"),
        replace(_candidate(), symbol="PART", candidate_id="part"),
        replace(
            _candidate(),
            symbol="REJ",
            candidate_id="rej",
            rejection_reason="WEAK_VERDICT",
            final_gate="WEAK_VERDICT",
        ),
    )
    outcomes = (
        _outcome("CAP", Decimal("25")),
        _outcome("PART", Decimal("5")),
    )
    runtime = (_runtime(date(2024, 1, 3), "RUN"),)

    rows = MajorOpportunityCoverageEngine().classify(
        events=events,
        candidates=candidates,
        outcomes=outcomes,
        runtime_failures=runtime,
    )

    assert tuple(item.classification for item in rows) == (
        CoverageClassification.CAPTURED,
        CoverageClassification.PARTIALLY_CAPTURED,
        CoverageClassification.REJECTED,
        CoverageClassification.MISSED,
        CoverageClassification.RUNTIME_BLOCKED,
    )


def test_extreme_unreconciled_move_is_data_blocked() -> None:
    event = replace(_event(), forward_return=Decimal("10"))

    row = MajorOpportunityCoverageEngine().classify(
        events=(event,),
        candidates=(),
    )[0]

    assert row.classification is CoverageClassification.DATA_BLOCKED
    assert "corporate-action" in (row.primary_blocker or "")


def test_zero_trade_explanation_is_stage_specific() -> None:
    weak = replace(_candidate(), symbol="WEAK", final_signal="WATCHLIST")
    timing = replace(
        _candidate(),
        symbol="TIME",
        candidate_id="time",
        setup_state="READY_FOR_CONFIRMATION",
    )
    plan = replace(_candidate(), symbol="PLAN", candidate_id="plan", stop=None)
    gate = replace(
        _candidate(),
        symbol="GATE",
        candidate_id="gate",
        rejection_reason="INSUFFICIENT_EVIDENCE",
        final_gate="INSUFFICIENT_EVIDENCE",
    )

    rows = ZeroTradeAttributionEngine().diagnose(
        symbols=("NONE", "WEAK", "TIME", "PLAN", "GATE"),
        sessions_examined=100,
        candidates=(weak, timing, plan, gate),
    )
    by_symbol = {item.symbol: item for item in rows}

    assert by_symbol["NONE"].explanation is ZeroTradeReason.NO_TRADES_BECAUSE_NO_SETUP
    assert by_symbol["WEAK"].explanation is ZeroTradeReason.NO_TRADES_BECAUSE_WEAK_SCORE
    assert by_symbol["TIME"].explanation is ZeroTradeReason.NO_TRADES_BECAUSE_TIMING
    assert by_symbol["PLAN"].explanation is ZeroTradeReason.NO_TRADES_BECAUSE_TRADE_PLAN
    assert (
        by_symbol["GATE"].explanation
        is ZeroTradeReason.NO_TRADES_BECAUSE_INSTITUTIONAL_GATE
    )


def test_kalyan_and_pc_jeweller_case_studies_are_resolved() -> None:
    kalyan_event = replace(_event(), symbol="KALYANKJIL", event_id="kalyan")
    pc_event = replace(_event(), symbol="PCJEWELLER", event_id="pc")
    coverage = (
        _coverage(kalyan_event, CoverageClassification.REJECTED),
        _coverage(pc_event, CoverageClassification.MISSED),
    )

    studies = CaseStudyEngine().build(
        requested_symbols=("KALYANKJIL", "PCJEWELLER"),
        available_symbols=("KALYANKJIL", "PCJEWELLER"),
        events=(kalyan_event, pc_event),
        coverage=coverage,
        candidates=(replace(_candidate(), symbol="KALYANKJIL"),),
    )

    assert studies[0].resolved_symbol == "KALYANKJIL"
    assert studies[0].candidate_creation_status == "CREATED"
    assert studies[1].resolved_symbol == "PCJEWELLER"
    assert studies[1].candidate_creation_status == "NOT_CREATED"


def test_economic_attribution_does_not_default_to_approval_policy() -> None:
    missed = _coverage(_event(), CoverageClassification.MISSED)

    primary, secondary = economic_attribution(
        coverage=(missed,),
        divergences=(),
        runtime_failures=(),
    )

    assert primary is EconomicProblem.SETUP_RECOGNITION_PROBLEM
    assert EconomicProblem.APPROVAL_POLICY_PROBLEM not in secondary


def test_exports_cli_ird_and_registry_are_diagnostic_only(tmp_path: Path) -> None:
    report = _report()
    output = tmp_path / "integrity"
    paths = CanonicalIntegrityAuditExporter().export(report, output_directory=output)

    assert len(paths) == 14
    assert (output / "runtime_failures.csv").exists()
    assert (output / "pine_alpha_trade_matches.csv").exists()
    assert (output / "major_opportunities.csv").exists()
    assert (output / "case_studies.json").exists()
    assert "PRODUCTION_INFLUENCE=false" in (output / "executive_report.md").read_text(
        encoding="utf-8"
    )

    runner = CliRunner()
    assert (
        runner.invoke(
            app, ["integrity-audit", "parity", "--output", str(output)]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["integrity-audit", "zero-trades", "--output", str(output)]
        ).exit_code
        == 0
    )
    case = runner.invoke(
        app,
        [
            "integrity-audit",
            "case-study",
            "--symbol",
            "KALYANKJIL",
            "--output",
            str(output),
        ],
    )
    assert case.exit_code == 0
    assert "KALYANKJIL" in case.output

    registry = ResearchExperimentRegistry(tmp_path / "research.json")
    assert record_integrity_experiment(report, registry=registry)
    assert not record_integrity_experiment(report, registry=registry)
    assert registry.load()[0].production_influence is False
    plugin = research_diagnostic_plugins()[0]
    assert plugin.diagnostic_id == "canonical-runtime-parity-opportunity-audit"


def _candidate() -> CanonicalTradeEvent:
    return CanonicalTradeEvent(
        candidate_id="2024-01-02|AAA",
        symbol="AAA",
        observed_on=date(2024, 1, 2),
        score=Decimal("80"),
        setup="BREAKOUT",
        setup_state="ENTRY_READY",
        strategy="BREAKOUT",
        entry=Decimal("100"),
        stop=Decimal("95"),
        targets=(Decimal("110"), Decimal("115"), Decimal("120")),
        final_signal="BUY",
        final_gate="PASSED",
        rejection_reason=None,
    )


def _pine() -> PineTrade:
    return PineTrade(
        trade_id="pine-1",
        symbol="AAA",
        exchange="NSE",
        entry_date=date(2024, 1, 2),
        entry_bar=10,
        setup_family="BREAKOUT",
        strategy_family="BREAKOUT",
        score=Decimal("80"),
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        exit_date=date(2024, 1, 10),
        exit_price=Decimal("110"),
        net_return_pct=Decimal("10"),
        evidence_class=EvidenceClass.CSV_TRADE_LEVEL,
        source_file="trades.csv",
    )


def _runtime(observed_on: date, symbol: str) -> RuntimeFailureRecord:
    return RuntimeFailureRecord(
        trading_date=observed_on,
        symbol=symbol,
        candidate_id=f"{observed_on}|{symbol}",
        pipeline_stage="PORTFOLIO_ALLOCATION_ADAPTER",
        category=FailureCategory.DATA_INVALID,
        exception_type="ValueError",
        exception_message="expected drawdown must be between 0 and 1",
        source_file="alpha/portfolio_intelligence/allocation.py",
        source_line=64,
        input_state={"expected_drawdown": "1.5"},
        missing_fields=(),
        provider_state="LEGACY_DATASET/PROVISIONAL/READ_ONLY",
        dataset_version="LEGACY_DATASET",
        deterministic_reproduction=True,
        failure_hash="same-root-cause",
        directly_triggered=True,
    )


def _event() -> MajorOpportunityEvent:
    return MajorOpportunityEvent(
        event_id="event-1",
        symbol="AAA",
        start_date=date(2024, 1, 1),
        breakout_date=date(2024, 1, 1),
        peak_date=date(2024, 2, 1),
        forward_horizon=60,
        forward_return=Decimal("0.30"),
        event_definition="UP_20_WITHIN_60",
        maximum_forward_return=Decimal("0.30"),
        time_to_peak=20,
        maximum_adverse_excursion_before_peak=Decimal("-0.05"),
        volume_expansion=Decimal("1.5"),
        base_length=20,
        trend_state="ABOVE_20_SESSION_MEAN",
        start_price=Decimal("100"),
        peak_price=Decimal("130"),
        dataset_version="LEGACY_DATASET",
    )


def _outcome(symbol: str, return_pct: Decimal) -> CandidateOutcomeRecord:
    return CandidateOutcomeRecord(
        observed_on=date(2024, 1, 2),
        symbol=symbol,
        entered=True,
        completed=True,
        won=return_pct > 0,
        realized_return_pct=return_pct,
        realized_r=return_pct / Decimal("10"),
        holding_period_days=10,
        exit_reason="TARGET",
        evidence_note="deterministic fixture",
    )


def _coverage(
    event: MajorOpportunityEvent,
    classification: CoverageClassification,
) -> OpportunityCoverageRecord:
    return OpportunityCoverageRecord(
        event_id=event.event_id,
        symbol=event.symbol,
        classification=classification,
        alpha_candidate_id=None,
        entry_delay_sessions=None,
        captured_return=None,
        captured_r=None,
        share_of_total_move=None,
        exit_efficiency=None,
        stop_efficiency=None,
        time_in_trade=None,
        mfe=None,
        mae=None,
        primary_blocker="WEAK_VERDICT"
        if classification is CoverageClassification.REJECTED
        else "NO_CANDIDATE",
        secondary_blocker=None,
        score=None,
        setup_state=None,
        timing_state=None,
        trade_plan_grade=None,
        stop_distance=None,
        minimum_rr=None,
        volume_confirmation=None,
        trend_confirmation=None,
    )


def _report() -> CanonicalIntegrityAuditReport:
    policy = frozen_policy_manifest(source_commit="test")
    runtime = _runtime(date(2024, 1, 2), "AAA")
    group = group_runtime_failures((runtime,))[0]
    pine = _pine()
    match = match_pine_trade(pine, (_candidate(),))
    event = replace(_event(), symbol="KALYANKJIL")
    coverage = _coverage(event, CoverageClassification.REJECTED)
    study = CaseStudyEngine().build(
        requested_symbols=("KALYANKJIL",),
        available_symbols=("KALYANKJIL",),
        events=(event,),
        coverage=(coverage,),
        candidates=(replace(_candidate(), symbol="KALYANKJIL"),),
    )[0]
    replay = RuntimeReplayComparison(
        before_failure_days=1,
        after_failure_days=0,
        before_affected_candidates=10,
        after_affected_candidates=0,
        before_scored_candidates=0,
        after_scored_candidates=10,
        before_approval_candidates=0,
        after_approval_candidates=1,
        before_institutional_approvals=0,
        after_institutional_approvals=0,
        repair="bounded adapter value",
        repair_scope="CANONICAL_DIAGNOSTIC_ADAPTER_ONLY",
    )
    summary = IntegrityAuditSummary(
        runtime_failure_days_before=1,
        runtime_failure_days_after=0,
        affected_candidates_before=10,
        affected_candidates_after=0,
        pine_trades_imported=1,
        exact_parity_rate=Decimal("1"),
        semantic_parity_rate=Decimal("1"),
        major_opportunities=1,
        captured=0,
        partially_captured=0,
        rejected=1,
        missed=0,
        runtime_blocked=0,
        data_blocked=0,
        largest_divergence_stage="NONE",
        highest_value_missed_opportunity="KALYANKJIL +30%",
        primary_bottleneck=EconomicProblem.SIGNAL_QUALITY_PROBLEM,
        secondary_bottlenecks=(),
    )
    return CanonicalIntegrityAuditReport(
        audit_id="CIA-1|ALPHA_CANONICAL_v1.0|2024-01-01|2024-02-01",
        generated_at=datetime(2024, 2, 2, tzinfo=UTC),
        policy=policy,
        runtime_failures=(runtime,),
        runtime_groups=(group,),
        runtime_replay=replay,
        pine_metadata=(
            PineExperimentMetadata(
                symbol="AAA",
                exchange="NSE",
                chart_timeframe="1D",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 2, 1),
                entry_threshold=Decimal("75"),
                strategy_family="BREAKOUT",
                setup_selection="BREAKOUT",
                commission=Decimal("0.1"),
                slippage=Decimal("0.05"),
                position_size=Decimal("100000"),
                market_regime_setting="OFF",
                sector_setting="OFF",
                script_version="1.0",
                framework_version="1.0",
                evidence_class=EvidenceClass.CSV_SUMMARY,
                source_file="metadata.json",
            ),
        ),
        pine_trades=(pine,),
        parity_matches=(match,),
        divergences=(),
        opportunities=(event,),
        coverage=(coverage,),
        zero_trades=(
            ZeroTradeAttributionEngine().diagnose(
                symbols=("KALYANKJIL",),
                sessions_examined=20,
                candidates=(
                    replace(
                        _candidate(),
                        symbol="KALYANKJIL",
                        rejection_reason="WEAK_VERDICT",
                        final_gate="WEAK_VERDICT",
                    ),
                ),
            )[0],
        ),
        case_studies=(study,),
        summary=summary,
    )


def _extreme_price_frame(observed_on: date) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": [f"S{index:02d}" for index in range(12)],
            "trade_date": [observed_on] * 12,
            "open": [100] * 12,
            "high": [250 + index for index in range(12)],
            "low": [10] * 12,
            "close": [105 + index for index in range(12)],
            "volume": [100_000 + index * 1_000 for index in range(12)],
            "sector": [None] * 12,
            "exchange": ["NSE"] * 12,
        }
    )
