from __future__ import annotations

from decimal import Decimal

from typer.testing import CliRunner

from alpha.candidate_learning import LearningLedgerRepository
from alpha.cli import app
from alpha.decision_intelligence import (
    CapacityAssessment,
    DecisionEvidenceCardBuilder,
    DecisionStressTestEngine,
    DisqualificationCategory,
    ExitStrategyType,
    FinalDecisionAction,
    GateDecision,
    InstitutionalCandidate,
    InstitutionalDecisionEngine,
    OpportunityGrade,
    RejectionReasonCode,
    RiskCommitteeVerdict,
    SetupQualityScorecard,
    StopQuality,
    StopQualityReview,
    StressReasonCode,
    TargetQuality,
    TargetQualityReview,
    TradePlanOptimizationEngine,
    TradeSetupDisqualificationReporter,
    render_decision_audit,
    render_decision_evidence_cards,
    render_decision_report,
    render_default_opportunities,
    render_trade_plan_audit,
    render_trade_setup_disqualification_report,
)


def test_gate_accepts_strong_opportunity() -> None:
    report = InstitutionalDecisionEngine().evaluate((_candidate("AAA"),))

    decision = report.accepted_opportunities[0]
    assert decision.gate_decision is GateDecision.ACCEPT
    assert decision.opportunity_score > Decimal("0")


def test_gate_rejects_weak_confidence() -> None:
    decision = _single_decision(_candidate("AAA", confidence="LOW"))

    assert decision.gate_decision is GateDecision.REJECT
    assert _codes(decision) == (RejectionReasonCode.WEAK_CONFIDENCE,)


def test_gate_rejects_poor_reward_risk() -> None:
    decision = _single_decision(_candidate("AAA", reward_risk=Decimal("1.2")))

    assert RejectionReasonCode.POOR_REWARD_RISK in _codes(decision)


def test_gate_rejects_score_below_deployment_threshold() -> None:
    decision = _single_decision(_candidate("AAA", final_score=Decimal("84")))

    assert RejectionReasonCode.WEAK_SETUP in _codes(decision)


def test_gate_rejects_stop_distance_above_deployment_threshold() -> None:
    decision = _single_decision(_candidate("AAA", stop_distance=Decimal("10.5")))

    assert RejectionReasonCode.EXCESS_DOWNSIDE_RISK in _codes(decision)


def test_gate_rejects_poor_data_completeness() -> None:
    decision = _single_decision(_candidate("AAA", data="PARTIAL"))

    assert RejectionReasonCode.POOR_DATA_COMPLETENESS in _codes(decision)


def test_gate_rejects_insufficient_capacity() -> None:
    decision = _single_decision(
        _candidate(
            "AAA",
            capacity=CapacityAssessment(
                capacity_score=Decimal("20"),
                deployable_capital_estimate=None,
                liquidity_warning="insufficient",
                explanation="Insufficient capacity data.",
                data_sufficient=False,
            ),
        )
    )

    assert RejectionReasonCode.INSUFFICIENT_CAPACITY in _codes(decision)


def test_score_breakdown_stability() -> None:
    decision = _single_decision(_candidate("AAA"))

    assert decision.score_breakdown.as_mapping()["reward_risk"] == "75.00"
    assert decision.score_breakdown.as_mapping()["capacity"] == "90.00"


def test_opportunity_grade_boundaries() -> None:
    strong = _single_decision(_candidate("AAA", posterior=Decimal("0.95")))
    rejected = _single_decision(_candidate("BBB", confidence="LOW"))

    assert strong.opportunity_grade in {
        OpportunityGrade.A_PLUS,
        OpportunityGrade.A,
        OpportunityGrade.B,
    }
    assert rejected.opportunity_grade is OpportunityGrade.REJECT


def test_portfolio_sector_concentration_penalty() -> None:
    report = InstitutionalDecisionEngine().evaluate(
        (_candidate("AAA", sector="IT"), _candidate("BBB", sector="IT"))
    )

    assert report.concentration_warnings


def test_no_trade_output() -> None:
    report = InstitutionalDecisionEngine().evaluate(
        (_candidate("AAA", confidence="LOW"),)
    )

    output = "\n".join(render_default_opportunities(report))

    assert "No high-quality trade setup today." in output
    assert "Institutional Deployment Status: NO DEPLOYABLE TRADE" in output
    assert "Approval precision is unavailable" in output
    assert "Candidates rejected: 1" in output


def test_late_setup_is_rejected_for_fresh_deployment() -> None:
    decision = _single_decision(
        _candidate(
            "AAA",
            setup_stage="LATE",
            entry_ready=False,
            execution_status="HOLD / NO FRESH ENTRY",
        )
    )

    assert RejectionReasonCode.LATE_ENTRY in _codes(decision)


def test_pending_trigger_blocks_capital_deployment() -> None:
    decision = _single_decision(
        _candidate(
            "AAA",
            entry_ready=False,
            trigger_status="WAITING_FOR_CLOSE_ABOVE",
            execution_status="WAIT FOR CONFIRMATION",
        )
    )

    assert RejectionReasonCode.PENDING_ENTRY_TRIGGER in _codes(decision)


def test_setup_scorecard_rejects_poor_entry_quality() -> None:
    decision = _single_decision(
        _candidate(
            "AAA",
            scorecard=SetupQualityScorecard(
                trend_alignment=Decimal("80"),
                price_volume_confirmation=Decimal("80"),
                entry_quality=Decimal("30"),
                stop_quality=Decimal("70"),
                target_realism=Decimal("70"),
                reward_risk_quality=Decimal("75"),
                historical_evidence=Decimal("60"),
                liquidity_capacity=Decimal("80"),
                market_regime_fit=Decimal("80"),
                total_score=Decimal("65"),
                setup_grade=OpportunityGrade.C,
                summary="Entry quality is not actionable.",
            ),
        )
    )

    assert RejectionReasonCode.WEAK_SETUP in _codes(decision)
    assert RejectionReasonCode.PENDING_ENTRY_TRIGGER in _codes(decision)


def test_default_output_renders_digestible_decision_card() -> None:
    report = InstitutionalDecisionEngine().evaluate((_candidate("AAA"),))

    output = "\n".join(render_default_opportunities(report))

    assert "AAA — BUY" in output
    assert "Setup Grade:" in output
    assert "Entry Status: Entry ready; trigger already confirmed." in output
    assert "What Would Change My Mind:" in output


def test_rejection_reason_rendering() -> None:
    report = InstitutionalDecisionEngine().evaluate(
        (_candidate("AAA", reward_risk=Decimal("1")),)
    )

    output = "\n".join(render_decision_report(report, verbose=True))

    assert "POOR_REWARD_RISK" in output
    assert "Reward/risk is below" in output


def test_decision_report_cli() -> None:
    result = CliRunner().invoke(
        app,
        ["decision", "report", "--demo", "--date", "2026-01-30"],
    )

    assert result.exit_code == 0
    assert "Institutional Decision Report" in result.stdout
    assert "Candidates Scanned:" in result.stdout


def test_unified_decision_card_approves_accepted_setup(tmp_path) -> None:
    decision = _single_decision(_candidate("AAA"))
    builder = DecisionEvidenceCardBuilder(
        repository=LearningLedgerRepository(tmp_path / "learning.json")
    )

    card = builder.build(decision)
    output = "\n".join(render_decision_evidence_cards((card,), verbose=True))

    assert card.action is RiskCommitteeVerdict.APPROVED
    assert card.gate_results == ("PASSED",)
    assert card.similar_cases.sample_count == 0
    assert "Unified Decision Cards" in output
    assert "Risk Committee:" in output


def test_unified_decision_card_waits_for_pending_trigger(tmp_path) -> None:
    decision = _single_decision(
        _candidate(
            "WAIT",
            entry_ready=False,
            trigger_status="WAITING_FOR_CLOSE_ABOVE",
            execution_status="WAIT FOR CONFIRMATION",
        )
    )
    card = DecisionEvidenceCardBuilder(
        repository=LearningLedgerRepository(tmp_path / "learning.json")
    ).build(decision)

    assert card.action is RiskCommitteeVerdict.WAIT
    assert card.disqualification_category is DisqualificationCategory.BAD_ENTRY
    assert "Wait because" in card.risk_committee_reason


def test_decision_cards_cli_output(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        ["decision", "cards", "--demo", "--date", "2026-01-30", "--verbose"],
        env={"ALPHA_CANDIDATE_LEARNING_LEDGER": str(tmp_path / "learning.json")},
    )

    assert result.exit_code == 0
    assert "Unified Decision Cards" in result.stdout
    assert "Risk Committee:" in result.stdout
    assert "Similar Cases:" in result.stdout


def test_live_trade_review_cli(tmp_path) -> None:
    journal = tmp_path / "trades.json"
    result = CliRunner().invoke(
        app,
        [
            "trades",
            "review",
            "--symbol",
            "AAA",
            "--entry",
            "100",
            "--stop",
            "95",
            "--target",
            "115",
            "--quantity",
            "10",
            "--thesis",
            "Breakout with volume",
            "--alpha-entry",
            "100",
            "--alpha-stop",
            "95",
            "--alpha-target",
            "115",
            "--journal",
            str(journal),
        ],
    )

    assert result.exit_code == 0
    assert "Live Trade Review" in result.stdout
    assert "Reward/Risk: 3.00R" in result.stdout
    assert "Trade Quality: HIGH" in result.stdout
    assert "Journaled Trade ID:" in result.stdout
    assert journal.exists()


def test_user_trade_journal_cli_persists_and_summarizes(tmp_path) -> None:
    journal = tmp_path / "trades.json"
    runner = CliRunner()
    review = runner.invoke(
        app,
        [
            "trades",
            "review",
            "--symbol",
            "CHASE",
            "--entry",
            "104",
            "--stop",
            "96",
            "--target",
            "116",
            "--alpha-entry",
            "100",
            "--alpha-stop",
            "96",
            "--alpha-target",
            "116",
            "--journal",
            str(journal),
        ],
    )
    listing = runner.invoke(app, ["trades", "journal", "--journal", str(journal)])
    summary = runner.invoke(app, ["trades", "summary", "--journal", str(journal)])

    assert review.exit_code == 0
    assert "Chased: Yes" in review.stdout
    assert listing.exit_code == 0
    assert "User Trade Journal" in listing.stdout
    assert "CHASE" in listing.stdout
    assert summary.exit_code == 0
    assert "User Trade Journal Summary" in summary.stdout
    assert "Chased Trades: 1" in summary.stdout


def test_verbose_rejected_candidate_output() -> None:
    report = InstitutionalDecisionEngine().evaluate(
        (_candidate("AAA", confidence="LOW"),)
    )

    output = "\n".join(render_decision_report(report, verbose=True))

    assert "Rejected Candidates:" in output
    assert "Gate Decisions:" in output
    assert "Score Breakdown:" in output


def test_missing_data_does_not_fabricate_values() -> None:
    decision = _single_decision(
        _candidate("AAA", reward_risk=None, posterior=None, expectancy=None)
    )

    mapping = decision.score_breakdown.as_mapping()
    assert mapping["posterior_probability"] == "unavailable"
    assert mapping["expectancy"] == "unavailable"
    assert RejectionReasonCode.MISSING_TRADE_PLAN in _codes(decision)


def test_accepted_opportunities_are_ranked_correctly() -> None:
    report = InstitutionalDecisionEngine().evaluate(
        (
            _candidate("LOW", posterior=Decimal("0.55"), expectancy=Decimal("0.2")),
            _candidate("HIGH", posterior=Decimal("0.90"), expectancy=Decimal("1.5")),
        )
    )

    assert report.accepted_opportunities[0].candidate.symbol == "HIGH"


def test_fragile_setup_rejection() -> None:
    decision = _single_decision(_candidate("AAA", near_resistance=True))

    assert not decision.accepted
    assert _failed_stress_codes(decision) == (StressReasonCode.FRAGILE_NEAR_RESISTANCE,)


def test_high_confidence_but_low_sample_penalty() -> None:
    decision = _single_decision(_candidate("AAA", sample_count=2))

    assert not decision.accepted
    assert RejectionReasonCode.INSUFFICIENT_EVIDENCE in _codes(decision)


def test_unrealistic_tight_stop_detection() -> None:
    assessment = StopQualityReview().assess(
        _candidate("AAA", stop_distance=Decimal("1.5"))
    )

    assert assessment.stop_quality is StopQuality.INVALID
    assert "tight" in assessment.explanation


def test_too_wide_stop_detection() -> None:
    assessment = StopQualityReview().assess(
        _candidate("AAA", stop_distance=Decimal("13"))
    )

    assert assessment.stop_quality is StopQuality.INVALID
    assert "wide" in assessment.explanation


def test_optimistic_target_detection() -> None:
    assessment = TargetQualityReview().assess(
        _candidate("AAA", reward_risk=Decimal("5.5"))
    )

    assert assessment.target_quality is TargetQuality.WEAK
    assert "optimistic" in assessment.explanation


def test_bad_regime_downgrade() -> None:
    decision = _single_decision(_candidate("AAA", regime="BEARISH"))

    assert decision.decision_quality is not None
    assert decision.decision_quality.final_action is FinalDecisionAction.DOWNGRADE
    assert StressReasonCode.BAD_MARKET_REGIME in _failed_stress_codes(decision)


def test_buy_contradicted_by_sell_indicators_is_rejected() -> None:
    decision = _single_decision(
        _candidate(
            "AAA",
            bearish_indicator_count=3,
            bearish_indicator_reasons=(
                "Price breakdown below support.",
                "Heavy selloff volume.",
                "Bearish candle confirmation.",
            ),
        )
    )

    assert not decision.accepted
    assert StressReasonCode.BUY_CONTRADICTED_BY_SELL_INDICATORS in _failed_stress_codes(
        decision
    )
    assert decision.decision_quality is not None
    assert decision.decision_quality.final_action is FinalDecisionAction.REJECT


def test_insufficient_five_year_history_rejects_buy() -> None:
    decision = _single_decision(_candidate("AAA", historical_bar_count=250))

    assert not decision.accepted
    assert StressReasonCode.INSUFFICIENT_FIVE_YEAR_HISTORY in _failed_stress_codes(
        decision
    )


def test_poor_historical_edge_rejects_apparent_buy() -> None:
    decision = _single_decision(
        _candidate(
            "TRAP",
            evidence="strong",
            sample_count=45,
            expectancy=Decimal("-0.35"),
            posterior=Decimal("0.58"),
        )
    )

    assert not decision.accepted
    assert RejectionReasonCode.POOR_HISTORICAL_EDGE in _codes(decision)


def test_tiny_negative_sample_does_not_create_historical_edge_veto() -> None:
    decision = _single_decision(
        _candidate(
            "EARLY",
            evidence="moderate",
            sample_count=8,
            expectancy=Decimal("-0.35"),
            posterior=Decimal("0.58"),
        )
    )

    assert RejectionReasonCode.POOR_HISTORICAL_EDGE not in _codes(decision)
    assert RejectionReasonCode.INSUFFICIENT_EVIDENCE in _codes(decision)


def test_buy_requires_sufficient_historical_sample_for_deployment() -> None:
    decision = _single_decision(
        _candidate(
            "THIN",
            evidence="moderate",
            sample_count=20,
            expectancy=Decimal("1.0"),
            posterior=Decimal("0.70"),
        )
    )

    assert not decision.accepted
    assert RejectionReasonCode.INSUFFICIENT_EVIDENCE in _codes(decision)


def test_buy_requires_positive_historical_expectancy() -> None:
    decision = _single_decision(
        _candidate(
            "LOWEV",
            evidence="moderate",
            sample_count=90,
            expectancy=Decimal("0.05"),
            posterior=Decimal("0.70"),
        )
    )

    assert not decision.accepted
    assert RejectionReasonCode.POOR_HISTORICAL_EDGE in _codes(decision)


def test_buy_requires_supportive_posterior_probability() -> None:
    decision = _single_decision(
        _candidate(
            "LOWPROB",
            evidence="moderate",
            sample_count=90,
            expectancy=Decimal("1.0"),
            posterior=Decimal("0.50"),
        )
    )

    assert not decision.accepted
    assert RejectionReasonCode.POOR_HISTORICAL_EDGE in _codes(decision)


def test_buy_requires_complete_deployment_trade_plan() -> None:
    decision = _single_decision(
        _candidate(
            "NOPLAN",
            target_2=None,
            atr=None,
            dma_20=None,
        )
    )

    assert not decision.accepted
    assert RejectionReasonCode.MISSING_TRADE_PLAN in _codes(decision)


def test_trade_setup_disqualification_report_classifies_failure_reason() -> None:
    report = InstitutionalDecisionEngine().evaluate(
        (
            _candidate("BADRR", reward_risk=Decimal("1.2")),
            _candidate("BEAR", bearish_indicator_count=3),
            _candidate(
                "BADEDGE",
                evidence="strong",
                sample_count=45,
                expectancy=Decimal("-0.35"),
            ),
        )
    )

    disqualification = TradeSetupDisqualificationReporter().build(report)
    output = "\n".join(render_trade_setup_disqualification_report(disqualification))

    categories = {item.symbol: item.category for item in disqualification.disqualified}
    assert categories["BADRR"] is DisqualificationCategory.POOR_REWARD_RISK
    assert categories["BEAR"] is DisqualificationCategory.BEARISH_CONTRADICTION
    assert categories["BADEDGE"] is DisqualificationCategory.POOR_HISTORICAL_EDGE
    assert "Trade Setup Disqualification Report" in output
    assert "poor reward/risk" in output
    assert "bearish contradiction" in output
    assert "poor historical edge" in output


def test_trade_setup_disqualification_cli_output() -> None:
    result = CliRunner().invoke(
        app,
        ["decision", "disqualifications", "--demo", "--date", "2026-01-30"],
    )

    assert result.exit_code == 0
    assert "Trade Setup Disqualification Report" in result.stdout
    assert "Failure Mix:" in result.stdout


def test_weak_evidence_overconfidence_reduction() -> None:
    decision = _single_decision(
        _candidate("AAA", evidence="weak", sample_count=3, confidence="HIGH")
    )

    assert not decision.accepted
    assert RejectionReasonCode.INSUFFICIENT_EVIDENCE in _codes(decision)


def test_decision_quality_score_stability() -> None:
    decision = _single_decision(_candidate("AAA"))

    assert decision.decision_quality is not None
    assert decision.decision_quality.decision_quality_score == Decimal("81.95")


def test_accepted_setup_remains_accepted_after_passing_stress_tests() -> None:
    decision = _single_decision(_candidate("AAA", expectancy=Decimal("1.5")))

    assert decision.accepted
    assert decision.decision_quality is not None
    assert decision.decision_quality.final_action is FinalDecisionAction.ACCEPT


def test_marginal_setup_becomes_no_trade() -> None:
    report = InstitutionalDecisionEngine().evaluate(
        (_candidate("AAA", reward_risk=Decimal("2.2")),)
    )

    assert not report.accepted_opportunities
    assert report.no_trade_reason == "No high-quality trade setup today."


def test_decision_audit_cli_output() -> None:
    result = CliRunner().invoke(
        app,
        ["decision", "audit", "--demo", "--date", "2026-01-30"],
    )

    assert result.exit_code == 0
    assert "Decision Audit Report" in result.stdout
    assert "Rejected By Stress Test:" in result.stdout
    assert "Stop Quality Distribution:" in result.stdout


def test_verbose_rejected_marginal_candidate_rendering() -> None:
    report = InstitutionalDecisionEngine().evaluate(
        (_candidate("AAA", reward_risk=Decimal("2.2")),)
    )

    output = "\n".join(render_decision_report(report, verbose=True))

    assert "Stress Test Results:" in output
    assert "Failed:" in output
    assert "Rejected Candidates:" in output


def test_decision_audit_rendering() -> None:
    engine = InstitutionalDecisionEngine()
    report = engine.evaluate((_candidate("AAA", reward_risk=Decimal("2.2")),))
    audit = DecisionStressTestEngine().audit(report.decisions)

    output = "\n".join(render_decision_audit(audit))

    assert "Top Failure Modes:" in output
    assert "No high-quality trade setup today." in output


def test_optimizer_selects_structural_stop() -> None:
    assessment = TradePlanOptimizationEngine().assess(
        _candidate(
            "AAA",
            support=Decimal("95"),
            swing_low=Decimal("93"),
            dma_20=Decimal("96"),
            atr=Decimal("3"),
        )
    )

    assert assessment.final_selected_plan is not None
    assert assessment.final_selected_plan.selected_stop == Decimal("96")
    assert assessment.stop_quality is StopQuality.GOOD


def test_optimizer_rejects_too_tight_stop() -> None:
    stops = TradePlanOptimizationEngine().stop_candidates(
        _candidate("AAA", stop=Decimal("99"), stop_distance=Decimal("1"))
    )

    default = next(stop for stop in stops if stop.name == "default")
    assert not default.accepted
    assert default.quality is StopQuality.INVALID


def test_optimizer_rejects_too_wide_stop() -> None:
    stops = TradePlanOptimizationEngine().stop_candidates(
        _candidate("AAA", stop=Decimal("87"), stop_distance=Decimal("13"))
    )

    default = next(stop for stop in stops if stop.name == "default")
    assert not default.accepted
    assert default.quality is StopQuality.INVALID


def test_target_realism_rejects_overextended_target() -> None:
    targets = TradePlanOptimizationEngine().target_candidates(
        _candidate("AAA", target_3=Decimal("180"), atr=Decimal("4"))
    )

    aggressive = next(
        target for target in targets if target.name == "aggressive target"
    )
    assert not aggressive.accepted
    assert aggressive.quality is TargetQuality.WEAK


def test_partial_profit_plan_creation() -> None:
    assessment = TradePlanOptimizationEngine().assess(_candidate("AAA"))

    assert assessment.final_selected_plan is not None
    assert assessment.final_selected_plan.partial_profit_plan is not None
    assert (
        assessment.final_selected_plan.partial_profit_plan.target_1_exit_percent
        == Decimal("50")
    )


def test_trailing_stop_plan_creation() -> None:
    assessment = TradePlanOptimizationEngine().assess(_candidate("AAA"))

    assert assessment.final_selected_plan is not None
    assert assessment.final_selected_plan.trailing_stop_rule is not None
    assert "Trail" in assessment.final_selected_plan.trailing_stop_rule


def test_exit_strategy_comparison_selects_partial_runner() -> None:
    assessment = TradePlanOptimizationEngine().assess(_candidate("AAA"))

    selected = tuple(
        strategy
        for strategy in assessment.exit_strategy_comparison
        if strategy.selected
    )
    assert len(selected) == 1
    assert selected[0].strategy_type is ExitStrategyType.PARTIAL_PROFIT_RUNNER


def test_weak_trade_plan_rejection() -> None:
    assessment = TradePlanOptimizationEngine().assess(
        _candidate(
            "AAA",
            entry=None,
            stop=None,
            target_1=None,
            target_2=None,
            target_3=None,
            reward_risk=None,
        )
    )

    assert assessment.final_action is FinalDecisionAction.REJECT
    assert assessment.final_selected_plan is None


def test_trade_plan_grade_boundaries() -> None:
    strong = TradePlanOptimizationEngine().assess(_candidate("AAA"))
    weak = TradePlanOptimizationEngine().assess(
        _candidate("BBB", entry=None, stop=None, target_1=None, reward_risk=None)
    )

    assert strong.trade_plan_grade in {
        OpportunityGrade.A_PLUS,
        OpportunityGrade.A,
        OpportunityGrade.B,
    }
    assert weak.trade_plan_grade is OpportunityGrade.REJECT


def test_default_output_includes_optimized_trade_plan() -> None:
    report = InstitutionalDecisionEngine().evaluate((_candidate("AAA"),))

    output = "\n".join(render_default_opportunities(report))

    assert "Final Selected Entry:" in output
    assert "Optimized Stop:" in output
    assert "Optimized Targets:" in output
    assert "Trade Plan Grade:" in output


def test_verbose_candidate_rendering_includes_trade_plan_candidates() -> None:
    report = InstitutionalDecisionEngine().evaluate(
        (
            _candidate(
                "AAA",
                target_1=Decimal("105"),
                target_2=Decimal("112"),
                target_3=None,
            ),
        )
    )

    output = "\n".join(render_decision_report(report, verbose=True))

    assert "Trade Plan Grade:" in output
    assert "Optimized Targets:" in output


def test_tradeplan_audit_cli_output() -> None:
    result = CliRunner().invoke(
        app,
        ["tradeplan", "audit", "--demo", "--date", "2026-01-30"],
    )

    assert result.exit_code == 0
    assert "Trade Plan Audit" in result.stdout
    assert "Accepted Opportunities Reviewed:" in result.stdout


def test_trade_plan_audit_rendering() -> None:
    engine = InstitutionalDecisionEngine()
    report = engine.evaluate((_candidate("AAA"),))
    audit = engine.trade_plan_optimizer.audit(report.decisions)

    output = "\n".join(render_trade_plan_audit(audit))

    assert "Optimized Plans:" in output
    assert "Selected Exit Strategy Distribution:" in output


def test_missing_trade_plan_data_does_not_fabricate_levels() -> None:
    assessment = TradePlanOptimizationEngine().assess(
        _candidate(
            "AAA",
            entry=None,
            stop=None,
            target_1=None,
            target_2=None,
            target_3=None,
            support=None,
            swing_low=None,
            dma_20=None,
            atr=None,
            reward_risk=None,
        )
    )

    assert assessment.final_selected_plan is None
    assert all(stop.level is None for stop in assessment.rejected_stop_candidates)


def _single_decision(candidate: InstitutionalCandidate):
    return InstitutionalDecisionEngine().evaluate((candidate,)).decisions[0]


def _codes(decision) -> tuple[RejectionReasonCode, ...]:
    return tuple(reason.code for reason in decision.rejection_reasons)


def _failed_stress_codes(decision) -> tuple[StressReasonCode, ...]:
    return tuple(
        result.reason_code for result in decision.stress_tests if not result.passed
    )


def _candidate(
    symbol: str,
    *,
    confidence: str = "HIGH",
    reward_risk: Decimal | None = Decimal("3"),
    data: str = "COMPLETE",
    sector: str = "IT",
    posterior: Decimal | None = Decimal("0.70"),
    expectancy: Decimal | None = Decimal("1.0"),
    capacity: CapacityAssessment | None = None,
    evidence: str = "moderate",
    sample_count: int | None = 80,
    stop_distance: Decimal = Decimal("6"),
    regime: str = "BULLISH",
    near_resistance: bool = False,
    entry: Decimal | None = Decimal("100"),
    stop: Decimal | None = Decimal("94"),
    target_1: Decimal | None = Decimal("112"),
    target_2: Decimal | None = Decimal("118"),
    target_3: Decimal | None = Decimal("124"),
    support: Decimal | None = None,
    swing_low: Decimal | None = None,
    dma_20: Decimal | None = Decimal("98"),
    atr: Decimal | None = Decimal("4"),
    resistance: Decimal | None = None,
    swing_high: Decimal | None = None,
    setup_stage: str = "ENTRY_READY",
    entry_ready: bool = True,
    trigger_status: str = "TRIGGER_CONFIRMED",
    execution_status: str = "BUY NOW",
    allocation_eligible: bool = True,
    scorecard: SetupQualityScorecard | None = None,
    historical_bar_count: int = 1260,
    bearish_indicator_count: int = 0,
    bearish_indicator_reasons: tuple[str, ...] = (),
    final_score: Decimal = Decimal("88"),
) -> InstitutionalCandidate:
    return InstitutionalCandidate(
        symbol=symbol,
        final_verdict="BUY",
        adjusted_confidence=confidence,
        evidence_strength=evidence,
        final_score=final_score,
        reward_risk_ratio=reward_risk,
        stop_distance_percent=stop_distance,
        data_completeness=data,
        setup_quality="HIGH",
        sector=sector,
        market_regime=regime,
        sector_fit=Decimal("75"),
        portfolio_fit=Decimal("80"),
        posterior_probability=posterior,
        expectancy=expectancy,
        entry=entry,
        stop=stop,
        target_1=target_1,
        target_2=target_2,
        target_3=target_3,
        capacity=capacity
        or CapacityAssessment(
            capacity_score=Decimal("90"),
            deployable_capital_estimate=Decimal("100000"),
            liquidity_warning=None,
            explanation="Capacity is supported by traded value.",
            data_sufficient=True,
        ),
        support_level=support,
        swing_low=swing_low,
        dma_20=dma_20,
        atr=atr,
        resistance_level=resistance,
        swing_high=swing_high,
        evidence_sample_count=sample_count,
        near_resistance=near_resistance,
        setup_stage=setup_stage,
        entry_ready=entry_ready,
        trigger_status=trigger_status,
        execution_status=execution_status,
        allocation_eligible=allocation_eligible,
        setup_scorecard=scorecard,
        historical_bar_count=historical_bar_count,
        bearish_indicator_count=bearish_indicator_count,
        bearish_indicator_reasons=bearish_indicator_reasons,
    )
