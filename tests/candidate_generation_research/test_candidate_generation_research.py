from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from alpha.application.candidate_research_cli import candidate_research_app
from alpha.candidate_generation_research.candidate_funnel import (
    CandidateGenerationFunnelEngine,
)
from alpha.candidate_generation_research.candidate_policy import (
    CandidatePolicyProposalEngine,
)
from alpha.candidate_generation_research.case_studies import (
    CandidateResearchCaseStudyEngine,
)
from alpha.candidate_generation_research.chronological_validation import (
    ChronologicalCandidateValidationEngine,
)
from alpha.candidate_generation_research.event_onset import (
    TradableOpportunityOnsetEngine,
    merge_duplicate_onsets,
)
from alpha.candidate_generation_research.exports import CandidateResearchExporter
from alpha.candidate_generation_research.feature_snapshots import (
    PointInTimeFeatureEngine,
)
from alpha.candidate_generation_research.models import (
    CANDIDATE_EXPLOSION_PENALTY,
    CANONICAL_POLICY_ID,
    HOLDOUT_REQUIRED,
    NO_FUTURE_LEAKAGE,
    POINT_IN_TIME_ONLY,
    PRODUCTION_INFLUENCE,
    RESEARCH_POLICY_ID,
    CandidateCoverage,
    CandidatePartition,
    CandidateResearchManifest,
    CandidateResearchReport,
    CandidateResearchSummary,
    CandidateVariantResult,
    OpportunityFamily,
    PointInTimeFeatureSnapshot,
    PolicyProposalStatus,
    TimingClassification,
    TradableOpportunityOnset,
    VariantFamily,
)
from alpha.candidate_generation_research.pine_trade_import import (
    PineLogicalTradeAuditEngine,
    chart_line_mapping,
)
from alpha.candidate_generation_research.timing_windows import (
    CandidateTimingAuditEngine,
)
from alpha.candidate_generation_research.tradability import TradabilityEngine
from alpha.candidate_generation_research.variant_generator import (
    default_candidate_variants,
)
from alpha.canonical_integrity_audit.models import (
    CanonicalTradeEvent,
    MajorOpportunityEvent,
)
from alpha.research.diagnostic_registry import default_diagnostic_registry

runner = CliRunner()


def test_future_move_does_not_define_entry_onset() -> None:
    frame = _breakout_frame()
    prefix = frame.iloc[:41].copy()
    with_future = pd.concat(
        (
            prefix,
            pd.DataFrame(
                [
                    _bar(41, Decimal("150"), Decimal("152"), Decimal("149"), 250000),
                    _bar(42, Decimal("180"), Decimal("182"), Decimal("178"), 300000),
                ]
            ),
        ),
        ignore_index=True,
    )

    prefix_onsets = TradableOpportunityOnsetEngine().detect_frame(prefix)
    future_onsets = TradableOpportunityOnsetEngine().detect_frame(with_future)

    assert prefix_onsets
    assert prefix_onsets[0] == next(
        item for item in future_onsets if item.onset_date == prefix_onsets[0].onset_date
    )
    assert (
        prefix_onsets[0].point_in_time_inputs["future_return_used_for_detection"]
        == "false"
    )


def test_point_in_time_base_and_breakout_detection() -> None:
    onsets = TradableOpportunityOnsetEngine().detect_frame(_breakout_frame())

    assert onsets
    breakout = next(
        item
        for item in onsets
        if item.event_family
        in {
            OpportunityFamily.BREAKOUT_FROM_BASE,
            OpportunityFamily.VOLUME_BREAKOUT,
            OpportunityFamily.VOLATILITY_CONTRACTION_BREAKOUT,
        }
    )
    assert breakout.prospective_stop < breakout.entry_trigger
    assert breakout.prospective_target > breakout.entry_trigger


def test_feature_snapshot_hash_ignores_later_bars() -> None:
    frame = _breakout_frame()
    first = PointInTimeFeatureEngine().build(frame.iloc[:41])[-1]
    changed_future = pd.concat(
        (
            frame.iloc[:41],
            pd.DataFrame(
                [_bar(41, Decimal("999"), Decimal("1000"), Decimal("998"), 1)]
            ),
        ),
        ignore_index=True,
    )
    second = next(
        item
        for item in PointInTimeFeatureEngine().build(changed_future)
        if item.observed_on == first.observed_on
    )

    assert first.observed_on == second.observed_on
    assert first.input_hash == second.input_hash


def test_trend_reversal_onset_is_supported() -> None:
    snapshot = _snapshot(
        close=Decimal("101"),
        prior_close=Decimal("98"),
        ema20=Decimal("96"),
        prior_ema20=Decimal("95"),
        ema50=Decimal("100"),
        resistance=Decimal("110"),
        support=Decimal("90"),
        volume_ratio=Decimal("1.30"),
    )

    onset = TradabilityEngine().assess(snapshot)

    assert onset is not None
    assert onset.event_family is OpportunityFamily.TREND_REVERSAL


def test_duplicate_onsets_merge_deterministically() -> None:
    first = _onset()
    duplicate = replace(
        first,
        onset_id="duplicate",
        onset_date=first.onset_date + timedelta(days=3),
        onset_sequence=first.onset_sequence + 3,
    )
    distinct = replace(
        first,
        onset_id="distinct",
        onset_date=first.onset_date + timedelta(days=11),
        onset_sequence=first.onset_sequence + 11,
    )

    assert merge_duplicate_onsets((distinct, duplicate, first)) == (first, distinct)


def test_non_tradable_future_winner_is_not_called_missed() -> None:
    event = _event()

    row = CandidateGenerationFunnelEngine().trace(
        events=(event,), onsets=(), candidates=()
    )[0]

    assert row.coverage is CandidateCoverage.NOT_ACTUALLY_TRADABLE
    assert row.canonical_candidate_created.value == "NOT_APPLICABLE"


def test_canonical_setup_false_negative_is_attributed() -> None:
    onset = _onset()
    event = _event()

    row = CandidateGenerationFunnelEngine().trace(
        events=(event,), onsets=(onset,), candidates=()
    )[0]

    assert row.coverage is CandidateCoverage.CANONICAL_SETUP_MISSED
    assert row.failure_reason is not None
    assert row.evidence_limitation is not None


def test_setup_detected_too_late() -> None:
    onset = _onset()
    event = _event(peak_date=date(2024, 4, 30))
    candidate = _candidate(
        observed_on=date(2024, 4, 25), setup_state="READY_FOR_CONFIRMATION"
    )
    sessions = tuple(date(2024, 4, 1) + timedelta(days=index) for index in range(30))

    timing = CandidateTimingAuditEngine().measure(
        events=(event,),
        onsets=(onset,),
        candidates=(candidate,),
        sessions=sessions,
    )[0]

    assert timing.classification in {
        TimingClassification.MATERIALLY_LATE,
        TimingClassification.MISSED_TIMING_WINDOW,
    }


def test_candidate_never_created_is_no_candidate_timing() -> None:
    timing = CandidateTimingAuditEngine().measure(
        events=(_event(),),
        onsets=(_onset(),),
        candidates=(),
        sessions=tuple(date(2024, 4, 1) + timedelta(days=index) for index in range(20)),
    )[0]

    assert timing.classification is TimingClassification.NO_CANDIDATE


def test_validation_only_success_cannot_select_variant() -> None:
    results = (
        _variant_result(CandidatePartition.DEVELOPMENT, passed=False),
        _variant_result(CandidatePartition.VALIDATION, passed=True),
        _variant_result(CandidatePartition.HOLDOUT, passed=True),
    )

    _, validations = ChronologicalCandidateValidationEngine().validate(results)

    assert validations[0].status is PolicyProposalStatus.REJECTED
    assert validations[0].selected_without_holdout is False


def test_holdout_failure_blocks_policy_promotion() -> None:
    results = (
        _variant_result(CandidatePartition.DEVELOPMENT, expectancy="0.05"),
        _variant_result(CandidatePartition.VALIDATION, expectancy="0.04"),
        _variant_result(CandidatePartition.HOLDOUT, passed=False, expectancy="-0.01"),
    )

    _, validations = ChronologicalCandidateValidationEngine().validate(results)

    assert validations[0].selected_without_holdout is True
    assert validations[0].holdout_pass is False
    assert validations[0].status is PolicyProposalStatus.REJECTED


def test_negative_expectancy_variant_is_rejected() -> None:
    results = (
        _variant_result(
            CandidatePartition.DEVELOPMENT, passed=False, expectancy="-0.02"
        ),
        _variant_result(
            CandidatePartition.VALIDATION, passed=False, expectancy="-0.01"
        ),
        _variant_result(CandidatePartition.HOLDOUT, passed=False, expectancy="-0.03"),
    )

    _, validations = ChronologicalCandidateValidationEngine().validate(results)

    assert validations[0].status is PolicyProposalStatus.REJECTED


def test_candidate_explosion_failure_is_preserved() -> None:
    row = replace(
        _variant_result(CandidatePartition.DEVELOPMENT, passed=False),
        candidates_per_day=Decimal("25"),
        explosion_penalty=Decimal("1.5"),
        failure_reasons=("CANDIDATE_EXPLOSION_PENALTY",),
    )

    assert row.passed is False
    assert "CANDIDATE_EXPLOSION_PENALTY" in row.failure_reasons


def test_policy_manifest_is_deterministic_without_validated_variant() -> None:
    definitions = default_candidate_variants()
    results = (
        _variant_result(CandidatePartition.DEVELOPMENT, passed=False),
        _variant_result(CandidatePartition.VALIDATION, passed=False),
        _variant_result(CandidatePartition.HOLDOUT, passed=False),
    )
    _, validations = ChronologicalCandidateValidationEngine().validate(results)

    first = CandidatePolicyProposalEngine().build(
        definitions=definitions, results=results, validations=validations
    )
    second = CandidatePolicyProposalEngine().build(
        definitions=definitions, results=results, validations=validations
    )

    assert first == second
    assert first.policy_id == "NO_CANDIDATE_POLICY_PROPOSAL"
    assert first.production_influence is False


def test_kalyan_case_fixture_contains_point_in_time_plan() -> None:
    event = _event(symbol="KALYANKJIL")
    onset = _onset(symbol="KALYANKJIL")
    funnel = CandidateGenerationFunnelEngine().trace(
        events=(event,), onsets=(onset,), candidates=()
    )

    study = CandidateResearchCaseStudyEngine().build(
        events=(event,),
        onsets=(onset,),
        funnel=funnel,
        timing=(),
        variants=(),
        available_symbols=("KALYANKJIL",),
    )[0]

    assert study.requested_symbol == "KALYANKJIL"
    assert study.onset_date == onset.onset_date
    assert study.prospective_stop is not None


def test_pc_jeweller_future_move_without_onset_is_not_mislabeled_missed() -> None:
    event = _event(symbol="PCJEWELLER")
    funnel = CandidateGenerationFunnelEngine().trace(
        events=(event,), onsets=(), candidates=()
    )

    studies = CandidateResearchCaseStudyEngine().build(
        events=(event,),
        onsets=(),
        funnel=funnel,
        timing=(),
        variants=(),
        available_symbols=("PCJEWELLER",),
    )
    study = next(item for item in studies if item.requested_symbol == "PCJEWELLER")

    assert study.coverage_classification == "NOT_ACTUALLY_TRADABLE"
    assert "missed" not in study.primary_reason.lower()


def test_pine_partial_exits_are_one_logical_trade() -> None:
    rows = (
        _pine_direct("2024-01-10", "2024-01-20", "50"),
        _pine_direct("2024-01-10", "2024-02-01", "49"),
    )

    audit = PineLogicalTradeAuditEngine().audit_rows(rows)

    assert len({item.logical_entry_id for item in audit}) == 1
    assert len(audit) == 2
    assert audit[-1].remaining_quantity == Decimal("1")
    assert audit[-1].issue == "RESIDUAL_POSITION"


def test_pine_final_leg_closes_residual_and_marks_boundary() -> None:
    rows = (
        _pine_direct("2024-01-10", "2024-01-20", "50"),
        _pine_direct("2024-01-10", "2024-02-01", "49"),
        {
            **_pine_direct("2024-01-10", "2024-02-05", "1"),
            "comment": "FORCED_BOUNDARY_EXIT",
        },
    )

    audit = PineLogicalTradeAuditEngine().audit_rows(rows)

    assert audit[-1].remaining_quantity == 0
    assert audit[-1].issue == "CLOSED"
    assert audit[-1].forced_boundary_exit is True


def test_chart_line_mapping_and_compact_panel_are_explicit() -> None:
    mapping = chart_line_mapping()
    overlay = Path("tradingview/indicators/Alpha_Trade_Plan_Overlay.pine").read_text()
    strategy = Path(
        "tradingview/strategies/Alpha_03_Institutional_Composite.pine"
    ).read_text()

    assert mapping["blue"] == "EMA20 trend reference"
    assert mapping["orange"] == "EMA50 invalidation reference"
    assert mapping["red"] == "Initial stop"
    assert mapping["green"] == "Entry trigger"
    assert 'plot(ema200, "EMA200 primary trend reference"' in overlay
    assert "table.new(position.top_right, 2, 7" in strategy
    assert "var table metrics" not in strategy


def test_partial_exit_scripts_close_all_remaining_quantity() -> None:
    for filename in (
        "Alpha_03_Institutional_Composite.pine",
        "Alpha_05_Risk_Exit_Lab.pine",
        "Alpha_06_Strategy_Combination_Lab.pine",
    ):
        source = (Path("tradingview/strategies") / filename).read_text()
        assert "FINAL_REMAINING_EXIT" in source
        assert "FORCED_BOUNDARY_EXIT" in source
        assert "qty_percent=100" in source


def test_required_exports_are_written(tmp_path: Path) -> None:
    report = _report()

    paths = CandidateResearchExporter().export(report, output_directory=tmp_path)

    required = {
        "forward_move_events.csv",
        "tradable_opportunity_onsets.csv",
        "tradable_vs_hindsight_summary.csv",
        "candidate_generation_funnel.csv",
        "setup_recognition_metrics.csv",
        "candidate_timing_metrics.csv",
        "missed_candidate_attribution.csv",
        "candidate_variant_results.csv",
        "chronological_validation.csv",
        "zero_candidate_diagnostics.csv",
        "pine_logical_trade_audit.csv",
        "case_studies.json",
        "candidate_policy_proposal.json",
        "executive_report.md",
    }
    assert required.issubset({item.name for item in paths})
    payload = json.loads((tmp_path / "candidate_research.json").read_text())
    assert payload["production_influence"] is False


def test_cli_reads_frozen_candidate_research_artifact(tmp_path: Path) -> None:
    CandidateResearchExporter().export(_report(), output_directory=tmp_path)

    opportunities = runner.invoke(
        candidate_research_app,
        ["define-opportunities", "--output", str(tmp_path)],
    )
    policy = runner.invoke(
        candidate_research_app,
        ["policy", "--output", str(tmp_path)],
    )
    parity = runner.invoke(
        candidate_research_app,
        ["parity", "--output", str(tmp_path)],
    )

    assert opportunities.exit_code == 0
    assert "Future Return Defines Entry: No" in opportunities.stdout
    assert policy.exit_code == 0
    assert "Automatic Deployment: No" in policy.stdout
    assert parity.exit_code == 0
    assert "unavailable" in parity.stdout


def test_ird_registers_candidate_generation_recovery() -> None:
    registry = default_diagnostic_registry(discover_plugins=False)

    assert "candidate-generation-recovery-audit" in registry.plugin_ids


def test_guardrails_are_fail_closed() -> None:
    assert PRODUCTION_INFLUENCE is False
    assert NO_FUTURE_LEAKAGE is True
    assert POINT_IN_TIME_ONLY is True
    assert HOLDOUT_REQUIRED is True
    assert CANDIDATE_EXPLOSION_PENALTY is True


def test_documentation_records_research_boundary() -> None:
    source = Path(
        "docs/TRADABLE_OPPORTUNITY_CANDIDATE_GENERATION_RECOVERY.md"
    ).read_text()

    assert "A forward move is an outcome label" in source
    assert "PRODUCTION_INFLUENCE=false" in source
    assert "Holdout cannot" in source


def _breakout_frame() -> pd.DataFrame:
    rows = []
    start = date(2024, 1, 1)
    for index in range(40):
        center = Decimal("96") + Decimal(index % 10)
        spread = Decimal("1.5") if index < 34 else Decimal("0.4")
        rows.append(
            {
                "symbol": "TEST",
                "trade_date": start + timedelta(days=index),
                "open": float(center - Decimal("0.2")),
                "high": float(center + spread),
                "low": float(center - spread),
                "close": float(center),
                "volume": 100000,
            }
        )
    rows.append(_bar(40, Decimal("107"), Decimal("108"), Decimal("105"), 200000))
    return pd.DataFrame(rows)


def _bar(
    index: int,
    close: Decimal,
    high: Decimal,
    low: Decimal,
    volume: int,
) -> dict[str, object]:
    return {
        "symbol": "TEST",
        "trade_date": date(2024, 1, 1) + timedelta(days=index),
        "open": float((close + low) / 2),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": volume,
    }


def _snapshot(
    *,
    close: Decimal,
    prior_close: Decimal,
    ema20: Decimal,
    prior_ema20: Decimal,
    ema50: Decimal,
    resistance: Decimal,
    support: Decimal,
    volume_ratio: Decimal,
) -> PointInTimeFeatureSnapshot:
    return PointInTimeFeatureSnapshot(
        symbol="TEST",
        observed_on=date(2024, 4, 1),
        sequence=100,
        open=Decimal("99"),
        high=close + 1,
        low=close - 2,
        close=close,
        volume=Decimal("200000"),
        prior_close=prior_close,
        prior_high=prior_close + 1,
        resistance_20=resistance,
        support_20=support,
        ema_20=ema20,
        prior_ema_20=prior_ema20,
        ema_50=ema50,
        atr_14=Decimal("2"),
        volume_ratio_20=volume_ratio,
        average_turnover_20=Decimal("20000000"),
        base_width=(resistance - support) / support,
        recent_range_ratio=Decimal("0.01"),
        prior_range_ratio=Decimal("0.03"),
        return_20=Decimal("-0.05"),
        relative_strength_20=None,
        close_location=Decimal("0.80"),
        recent_low_10=ema20 - 1,
        prior_breakout=False,
        input_hash="feature-hash",
    )


def _event(
    *,
    symbol: str = "TEST",
    peak_date: date = date(2024, 4, 20),
) -> MajorOpportunityEvent:
    return MajorOpportunityEvent(
        event_id=f"event-{symbol}",
        symbol=symbol,
        start_date=date(2024, 4, 1),
        breakout_date=date(2024, 4, 1),
        peak_date=peak_date,
        forward_horizon=60,
        forward_return=Decimal("0.50"),
        event_definition="UP_20_WITHIN_60",
        maximum_forward_return=Decimal("0.50"),
        time_to_peak=15,
        maximum_adverse_excursion_before_peak=Decimal("-0.05"),
        volume_expansion=Decimal("1.5"),
        base_length=20,
        trend_state="ABOVE_20_SESSION_MEAN",
        start_price=Decimal("100"),
        peak_price=Decimal("150"),
        dataset_version="LEGACY_DATASET",
    )


def _onset(*, symbol: str = "TEST") -> TradableOpportunityOnset:
    return TradableOpportunityOnset(
        onset_id=f"onset-{symbol}",
        forward_event_id=f"event-{symbol}",
        symbol=symbol,
        onset_date=date(2024, 4, 1),
        onset_sequence=100,
        event_family=OpportunityFamily.BREAKOUT_FROM_BASE,
        setup_evidence=("bounded_pre_onset_base", "observable_volume_confirmation"),
        entry_trigger=Decimal("100"),
        reference_level=Decimal("99"),
        prospective_stop=Decimal("95"),
        prospective_target=Decimal("112"),
        prospective_rr=Decimal("2.4"),
        extension_state="ACCEPTABLE",
        liquidity_state="PASS",
        confidence=Decimal("0.70"),
        point_in_time_inputs={
            "volume_ratio_20": "1.5",
            "extension_pct": "0.03",
            "relative_strength_20": "UNAVAILABLE",
        },
        dataset_version="LEGACY_DATASET",
    )


def _candidate(
    *,
    symbol: str = "TEST",
    observed_on: date = date(2024, 4, 2),
    setup_state: str = "ENTRY_READY",
) -> CanonicalTradeEvent:
    return CanonicalTradeEvent(
        candidate_id=f"{observed_on}|{symbol}",
        symbol=symbol,
        observed_on=observed_on,
        score=Decimal("80"),
        setup="Flat Base",
        setup_state=setup_state,
        strategy="Breakout",
        entry=Decimal("101"),
        stop=Decimal("95"),
        targets=(Decimal("113"), None, None),
        final_signal="BUY",
        final_gate="PASSED",
        rejection_reason=None,
    )


def _variant_result(
    partition: CandidatePartition,
    *,
    passed: bool = True,
    expectancy: str = "0.05",
) -> CandidateVariantResult:
    return CandidateVariantResult(
        variant_id="CANONICAL",
        variant_family=VariantFamily.RECOGNITION_TOLERANCE,
        partition=partition,
        candidates=100,
        trading_days=100,
        candidates_per_day=Decimal("1"),
        candidates_per_month=Decimal("21"),
        candidate_precision=Decimal("0.20"),
        candidate_recall=Decimal("0.50"),
        forward_expectancy_after_costs=Decimal(expectancy),
        false_candidate_rate=Decimal("0.80"),
        duplicate_candidate_rate=Decimal("0.02"),
        sector_concentration=None,
        symbol_concentration=Decimal("0.03"),
        turnover=None,
        trade_plan_feasibility=Decimal("1"),
        tradable_onset_coverage=Decimal("0.50"),
        major_move_capture_rate=Decimal("0.50"),
        average_prospective_rr=Decimal("2"),
        maximum_drawdown_proxy=Decimal("-0.10"),
        explosion_penalty=Decimal("0.02"),
        stability="PENDING_CROSS_PARTITION_COMPARISON",
        passed=passed,
        failure_reasons=() if passed else ("TEST_FAILURE",),
    )


def _pine_direct(entry: str, exit_date: str, exit_quantity: str) -> dict[str, str]:
    return {
        "symbol": "TEST",
        "entry_date": entry,
        "entry_price": "100",
        "entry_quantity": "100",
        "exit_date": exit_date,
        "exit_quantity": exit_quantity,
        "setup": "BREAKOUT",
    }


def _manifest() -> CandidateResearchManifest:
    return CandidateResearchManifest(
        policy_id=RESEARCH_POLICY_ID,
        parent_policy_id=CANONICAL_POLICY_ID,
        source_commit="test",
        dataset_version="LEGACY_DATASET",
        candidate_engine_version="candidate-generation-research-v1.0",
        setup_engine_version="test",
        timing_engine_version="test",
        score_version="test",
        approval_policy_version="test",
        trade_plan_version="test",
        outcome_version="test",
        research_thresholds={"holdout": "required"},
    )


def _report() -> CandidateResearchReport:
    definitions = default_candidate_variants()
    results = (
        _variant_result(CandidatePartition.DEVELOPMENT, passed=False),
        _variant_result(CandidatePartition.VALIDATION, passed=False),
        _variant_result(CandidatePartition.HOLDOUT, passed=False),
    )
    _, validations = ChronologicalCandidateValidationEngine().validate(results)
    proposal = CandidatePolicyProposalEngine().build(
        definitions=definitions, results=results, validations=validations
    )
    summary = CandidateResearchSummary(
        forward_move_events=0,
        tradable_onsets=0,
        tradable_event_count=0,
        non_tradable_event_count=0,
        future_moves_actually_tradable_share=None,
        canonical_setup_recall=None,
        canonical_candidate_recall=None,
        median_candidate_delay=None,
        primary_setup_blocker="UNAVAILABLE",
        primary_timing_blocker="UNAVAILABLE",
        variants_tested=1,
        best_validated_variant="NONE",
        candidate_explosion_risk="BOUNDED",
        kalyan_classification="UNAVAILABLE",
        pc_jeweller_classification="UNAVAILABLE",
        promotion_blockers=("insufficient evidence",),
    )
    return CandidateResearchReport(
        audit_id="CGR-TEST",
        generated_at=datetime(2026, 7, 19, tzinfo=UTC),
        manifest=_manifest(),
        forward_move_events=(),
        onsets=(),
        funnel=(),
        setup_metrics=(),
        timing_metrics=(),
        missed_attribution=(),
        variant_results=results,
        validations=validations,
        zero_candidates=(),
        pine_logical_trades=(),
        pine_candidate_parity=(),
        case_studies=(),
        policy_proposal=proposal,
        summary=summary,
    )
