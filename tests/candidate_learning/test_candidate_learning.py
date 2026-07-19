from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

from typer.testing import CliRunner

from alpha.candidate_learning import (
    CandidateForwardOutcomeEvaluator,
    CandidateOutcomeLabel,
    ExclusionStage,
    IndicatorCombinationEdgeEngine,
    LearningLedgerRepository,
    LearningSummaryAggregator,
    NightlyLearningLoop,
    RawCandidateForwardOutcome,
    RawCandidateForwardOutcomeEvaluator,
    RawCandidateRecord,
    RawForwardWindowOutcome,
    RawIndicatorCombinationEdgeEngine,
    RawUniverseLearningAggregator,
)
from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.cli import app
from alpha.recommendation_intelligence.models import (
    OHLCVBar,
    RecommendationAction,
    RecommendationCandidate,
    RecommendationEvidence,
)


def test_every_candidate_is_stored(tmp_path) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")

    inserted = repository.save_records(
        (_record("AAA"), _record("BBB", verdict="AVOID"))
    )

    assert inserted == 2
    assert len(repository.load_records()) == 2


def test_rejected_and_watchlist_candidates_are_stored(tmp_path) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    repository.save_records(
        (
            _record("AAA", verdict="WATCHLIST"),
            _record("BBB", verdict="AVOID"),
        )
    )

    verdicts = {record.final_verdict for record in repository.load_records()}
    assert verdicts == {"WATCHLIST", "AVOID"}


def test_duplicate_run_symbol_is_not_double_counted(tmp_path) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    record = _record("AAA")

    assert repository.save_records((record,)) == 1
    assert repository.save_records((record,)) == 0
    assert len(repository.load_records()) == 1


def test_duplicate_candidate_does_not_rewrite_existing_record(tmp_path) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    original = _record("AAA", verdict="BUY")
    replacement = _record("AAA", verdict="AVOID")

    assert repository.save_records((original,)) == 1
    assert repository.save_records((replacement,)) == 0

    assert repository.load_records()[0].final_verdict == "BUY"


def test_forward_return_is_computed_correctly() -> None:
    outcome = CandidateForwardOutcomeEvaluator().evaluate(
        record=_record("AAA"),
        bars=(_bar(1, open_price="100", high="110", low="99", close="106"),),
    )

    window = outcome.windows[0]
    assert window.forward_return_pct_from_close == Decimal("6.00")
    assert window.forward_return_pct_from_entry == Decimal("4.95")
    assert window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_WON


def test_target_stop_same_candle_is_conservative() -> None:
    outcome = CandidateForwardOutcomeEvaluator().evaluate(
        record=_record("AAA", stop=Decimal("95"), target_1=Decimal("110")),
        bars=(_bar(1, open_price="100", high="112", low="94", close="108"),),
    )

    window = outcome.windows[0]
    assert window.target_1_touched is True
    assert window.risk_stop_touched is True
    assert window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_LOST


def test_false_positive_detection() -> None:
    summary = _summary(
        _record("AAA", approved=True),
        _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_LOST),
    )

    assert summary.quality.false_positive_count == 1


def test_false_negative_detection() -> None:
    summary = _summary(
        _record("AAA", approved=False, verdict="AVOID"),
        _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
    )

    assert summary.quality.false_negative_count == 1


def test_correct_approval_and_reject_detection() -> None:
    summary = LearningSummaryAggregator(minimum_sample_size=1).summarize(
        records=(
            _record("AAA", approved=True),
            _record("BBB", approved=False, verdict="AVOID"),
        ),
        outcomes=(
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome("candidate-BBB", CandidateOutcomeLabel.WOULD_HAVE_LOST),
        ),
    )

    assert summary.quality.correct_approval_count == 1
    assert summary.quality.correct_reject_count == 1


def test_missed_opportunity_calculation() -> None:
    summary = _summary(
        _record("AAA", approved=False, verdict="WATCHLIST"),
        _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
    )

    assert summary.quality.missed_opportunity_rate == Decimal("1.0000")


def test_period_summaries_and_indicator_aggregation(tmp_path) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    repository.save_records((_record("AAA"),))
    repository.upsert_outcomes(
        (_outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),)
    )
    loop = NightlyLearningLoop(repository=repository)

    for period in ("daily", "weekly", "monthly", "yearly", "lifetime"):
        summary = loop.summarize(period=period)
        assert summary.total_candidates_evaluated == 1
        assert summary.best_indicator_combinations
        assert summary.best_setup_regime_combinations


def test_insufficient_sample_warning() -> None:
    summary = _summary(
        _record("AAA"),
        _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
        minimum_sample_size=30,
    )

    assert summary.sufficient_sample is False


def test_nightly_command_works(tmp_path) -> None:
    env = {
        "ALPHA_CANDIDATE_LEARNING_LEDGER": str(tmp_path / "learning.json"),
        "ALPHA_RECOMMENDATION_LEDGER": str(tmp_path / "recommendations.json"),
        "ALPHA_STRATEGY_REGIME_BACKTESTS": str(tmp_path / "strategy.json"),
    }
    result = CliRunner().invoke(app, ["learning", "nightly"], env=env)

    assert result.exit_code == 0
    assert "Nightly Learning Loop" in result.stdout
    assert "Strategy-Regime Backtests: missing" in result.stdout


def test_learning_summary_command_works(tmp_path) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    repository.save_records((_record("AAA"),))
    repository.upsert_outcomes(
        (_outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),)
    )
    env = {"ALPHA_CANDIDATE_LEARNING_LEDGER": str(tmp_path / "learning.json")}

    result = CliRunner().invoke(app, ["learning", "summary"], env=env)

    assert result.exit_code == 0
    assert "Candidate Learning Summary" in result.stdout
    assert "False Positives:" in result.stdout


def test_indicator_combination_edge_is_regime_aware() -> None:
    records = (
        _record("AAA", indicators=("breakout", "relative-strength"), regime="BULLISH"),
        _record("BBB", indicators=("breakout", "relative-strength"), regime="BULLISH"),
        _record("CCC", indicators=("breakout", "weak-volume"), regime="SIDEWAYS"),
        _record("DDD", indicators=("breakout", "weak-volume"), regime="SIDEWAYS"),
    )
    outcomes = (
        _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
        _outcome("candidate-BBB", CandidateOutcomeLabel.WOULD_HAVE_WON),
        _outcome("candidate-CCC", CandidateOutcomeLabel.WOULD_HAVE_LOST),
        _outcome("candidate-DDD", CandidateOutcomeLabel.WOULD_HAVE_LOST),
    )

    report = IndicatorCombinationEdgeEngine(minimum_sample_size=2).analyze(
        records=records,
        outcomes=outcomes,
    )

    assert report.strongest[0].combination == ("breakout", "relative-strength")
    assert report.strongest[0].market_regime == "BULLISH"
    assert report.strongest[0].win_rate == Decimal("1.0000")
    assert report.weakest[0].combination == ("breakout", "weak-volume")
    assert report.weakest[0].market_regime == "SIDEWAYS"


def test_indicator_combination_edge_does_not_promote_weak_sample() -> None:
    report = IndicatorCombinationEdgeEngine(minimum_sample_size=3).analyze(
        records=(
            _record("AAA", indicators=("breakout", "relative-strength")),
            _record("BBB", indicators=("breakout", "relative-strength")),
        ),
        outcomes=(
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome("candidate-BBB", CandidateOutcomeLabel.WOULD_HAVE_WON),
        ),
    )

    assert report.strongest == ()
    assert report.insufficient[0].evidence_strength == "insufficient"
    assert report.insufficient[0].completed_count == 2


def test_raw_indicator_combination_edge_uses_historical_replay_records() -> None:
    report = RawIndicatorCombinationEdgeEngine(minimum_sample_size=2).analyze(
        records=(
            _raw_record("AAA", indicators=("breakout", "relative-strength")),
            _raw_record("BBB", indicators=("breakout", "relative-strength")),
            _raw_record(
                "CCC",
                indicators=("breakout", "weak-volume"),
                regime="SIDEWAYS",
            ),
            _raw_record(
                "DDD",
                indicators=("breakout", "weak-volume"),
                regime="SIDEWAYS",
            ),
        ),
        outcomes=(
            _raw_outcome("raw-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _raw_outcome("raw-BBB", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _raw_outcome("raw-CCC", CandidateOutcomeLabel.WOULD_HAVE_LOST),
            _raw_outcome("raw-DDD", CandidateOutcomeLabel.WOULD_HAVE_LOST),
        ),
    )

    assert report.strongest[0].combination == ("breakout", "relative-strength")
    assert report.strongest[0].market_regime == "BULLISH"
    assert report.weakest[0].combination == ("breakout", "weak-volume")
    assert report.weakest[0].market_regime == "SIDEWAYS"


def test_learning_combinations_command_works(tmp_path) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    repository.save_raw_records(
        (
            _raw_record("AAA", indicators=("breakout", "relative-strength")),
            _raw_record("BBB", indicators=("breakout", "relative-strength")),
        )
    )
    repository.upsert_raw_outcomes(
        (
            _raw_outcome("raw-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _raw_outcome("raw-BBB", CandidateOutcomeLabel.WOULD_HAVE_WON),
        )
    )
    env = {"ALPHA_CANDIDATE_LEARNING_LEDGER": str(tmp_path / "learning.json")}

    result = CliRunner().invoke(
        app,
        ["learning", "combinations", "--min-sample-size", "2"],
        env=env,
    )

    assert result.exit_code == 0
    assert "Indicator Combination Edge Report" in result.stdout
    assert "breakout + relative-strength [BULLISH]" in result.stdout


def test_learning_combinations_command_supports_live_source(tmp_path) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    repository.save_records(
        (
            _record("AAA", indicators=("breakout", "relative-strength")),
            _record("BBB", indicators=("breakout", "relative-strength")),
        )
    )
    repository.upsert_outcomes(
        (
            _outcome("candidate-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _outcome("candidate-BBB", CandidateOutcomeLabel.WOULD_HAVE_WON),
        )
    )
    env = {"ALPHA_CANDIDATE_LEARNING_LEDGER": str(tmp_path / "learning.json")}

    result = CliRunner().invoke(
        app,
        [
            "learning",
            "combinations",
            "--source",
            "live",
            "--min-sample-size",
            "2",
        ],
        env=env,
    )

    assert result.exit_code == 0
    assert "breakout + relative-strength [BULLISH]" in result.stdout


def test_alpha_run_prints_learning_ledger_section(tmp_path) -> None:
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
    assert "Learning Ledger:" in result.stdout
    assert "- Candidates evaluated today:" in result.stdout
    assert "- Indicator combination edge:" in result.stdout
    assert "Raw Universe Learning:" in result.stdout
    assert "Live Trades Check-In:" in result.stdout


def test_raw_candidates_are_stored_and_deduplicated(tmp_path) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    raw = _raw_record("AAA")

    assert repository.save_raw_records((raw,)) == 1
    assert repository.save_raw_records((raw,)) == 0
    assert repository.load_raw_records() == (raw,)


def test_raw_record_derives_indicator_labels_from_candidate_scores() -> None:
    from alpha.candidate_learning import raw_record_from_candidate

    record = raw_record_from_candidate(
        candidate=_candidate_with_scores(),
        run_id="run-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        emitted_verdict_by_symbol={},
    )

    assert "trend-strong" in record.indicators_active
    assert "volume-constructive" in record.indicators_active
    assert "relative-strength-constructive" in record.indicators_active
    assert "breakout-constructive" in record.indicators_active
    assert "risk-constructive" in record.indicators_active
    assert "weak-volume" not in record.indicators_active


def test_emitted_and_non_emitted_raw_candidates_are_preserved(tmp_path) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    repository.save_raw_records(
        (
            _raw_record("AAA", emitted=True, verdict="BUY"),
            _raw_record(
                "BBB",
                emitted=False,
                stage=ExclusionStage.LIQUIDITY_FILTER,
                reasons=("Liquidity below threshold",),
            ),
        )
    )

    records = {record.symbol: record for record in repository.load_raw_records()}
    assert records["AAA"].was_emitted_decision is True
    assert records["AAA"].emitted_verdict == "BUY"
    assert records["BBB"].was_emitted_decision is False
    assert records["BBB"].excluded_stage is ExclusionStage.LIQUIDITY_FILTER
    assert records["BBB"].exclusion_reasons == ("Liquidity below threshold",)


def test_raw_candidate_forward_outcome_is_computed() -> None:
    outcome = RawCandidateForwardOutcomeEvaluator().evaluate(
        record=_raw_record("AAA", close=Decimal("100"), target_1=Decimal("108")),
        bars=(_bar(1, open_price="100", high="109", low="98", close="106"),),
    )

    window = outcome.windows[0]
    assert window.forward_return_pct_from_close == Decimal("6.00")
    assert window.target_1_touched is True
    assert window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_WON


def test_raw_candidate_stop_and_target_same_candle_is_conservative() -> None:
    outcome = RawCandidateForwardOutcomeEvaluator().evaluate(
        record=_raw_record("AAA", close=Decimal("100"), stop=Decimal("95")),
        bars=(_bar(1, open_price="100", high="112", low="94", close="108"),),
    )

    window = outcome.windows[0]
    assert window.target_1_touched is True
    assert window.risk_stop_touched is True
    assert window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_LOST


def test_raw_false_negative_and_correct_reject_by_stage() -> None:
    summary = RawUniverseLearningAggregator().summarize(
        records=(
            _raw_record("AAA", stage=ExclusionStage.SETUP_FILTER),
            _raw_record("BBB", stage=ExclusionStage.RISK_FILTER),
        ),
        outcomes=(
            _raw_outcome("raw-AAA", CandidateOutcomeLabel.WOULD_HAVE_WON),
            _raw_outcome("raw-BBB", CandidateOutcomeLabel.WOULD_HAVE_LOST),
        ),
        minimum_sample_size=1,
    )

    assert summary.false_negatives == 1
    assert summary.correct_rejects == 1
    assert summary.top_exclusion_stage == ExclusionStage.SETUP_FILTER.value
    by_stage = {item.exclusion_stage: item for item in summary.filter_quality}
    assert by_stage[ExclusionStage.SETUP_FILTER.value].false_negative_count == 1
    assert by_stage[ExclusionStage.SETUP_FILTER.value].exclusion_reason == "Not emitted"


def test_raw_filter_quality_and_emitted_comparison_work() -> None:
    summary = RawUniverseLearningAggregator().summarize(
        records=(
            _raw_record("AAA", emitted=True, stage=ExclusionStage.FINAL_RECOMMENDATION),
            _raw_record("BBB", stage=ExclusionStage.SETUP_FILTER),
            _raw_record("CCC", stage=ExclusionStage.LIQUIDITY_FILTER),
        ),
        outcomes=(
            _raw_outcome(
                "raw-AAA",
                CandidateOutcomeLabel.WOULD_HAVE_WON,
                forward_return=Decimal("8"),
            ),
            _raw_outcome(
                "raw-BBB",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                forward_return=Decimal("-4"),
            ),
            _raw_outcome(
                "raw-CCC",
                CandidateOutcomeLabel.WOULD_HAVE_LOST,
                forward_return=Decimal("-2"),
            ),
        ),
        minimum_sample_size=1,
    )

    assert summary.average_return_emitted == Decimal("8")
    assert summary.average_return_non_emitted == Decimal("-3.00")
    assert summary.filter_value_added == Decimal("11.00")
    assert summary.best_filters[0][0] == ExclusionStage.FINAL_RECOMMENDATION.value
    assert summary.weakest_filters[0][0] == ExclusionStage.SETUP_FILTER.value
    by_stage = {item.exclusion_stage: item for item in summary.filter_quality}
    assert dict(
        by_stage[ExclusionStage.LIQUIDITY_FILTER.value].average_forward_returns
    )["20d"] == Decimal("-2")


def test_raw_summary_command_works(tmp_path) -> None:
    repository = LearningLedgerRepository(tmp_path / "learning.json")
    repository.save_raw_records((_raw_record("AAA"),))
    env = {"ALPHA_CANDIDATE_LEARNING_LEDGER": str(tmp_path / "learning.json")}

    result = CliRunner().invoke(app, ["learning", "raw-summary"], env=env)

    assert result.exit_code == 0
    assert "Raw Universe Learning Summary" in result.stdout
    assert (
        "Raw universe learning: Not yet computed; insufficient sample." in result.stdout
    )


def _summary(
    record: CandidateDecisionRecord,
    outcome,
    *,
    minimum_sample_size: int = 1,
):
    return LearningSummaryAggregator(minimum_sample_size=minimum_sample_size).summarize(
        records=(record,),
        outcomes=(outcome,),
    )


def _record(
    symbol: str,
    *,
    approved: bool = True,
    verdict: str = "BUY",
    stop: Decimal | None = Decimal("96"),
    target_1: Decimal | None = Decimal("112"),
    indicators: tuple[str, ...] = ("breakout", "relative-strength"),
    regime: str = "BULLISH",
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id=f"candidate-{symbol}",
        run_id="run-1",
        evaluation_date=date(2026, 1, 1),
        symbol=symbol,
        final_verdict=verdict,
        capital_action="BUY" if approved else "AVOID",
        approved_for_deployment=approved,
        rejection_reasons=() if approved else ("weak setup",),
        setup_type="BREAKOUT",
        market_regime=regime,
        long_trade_permission=approved,
        strategy_score=Decimal("88"),
        confidence="HIGH",
        data_quality="COMPLETE",
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("101"),
        confirmation_entry=Decimal("101"),
        risk_stop=stop,
        target_1=target_1,
        target_2=Decimal("118"),
        target_3=Decimal("124"),
        trailing_stop_plan="Trail below highest close.",
        expected_holding_period="2-4 weeks",
        indicators_active=indicators,
        indicator_scores={"price": "80"},
        evidence_layers=("Price/Volume",),
        explanation="Test candidate.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        sector="IT",
    )


def _outcome(candidate_id: str, label: CandidateOutcomeLabel):
    from alpha.candidate_learning.models import (
        CandidateForwardOutcome,
        CandidateForwardWindowOutcome,
    )

    won = label is CandidateOutcomeLabel.WOULD_HAVE_WON
    return CandidateForwardOutcome(
        candidate_id=candidate_id,
        symbol=candidate_id.replace("candidate-", ""),
        evaluated_at=datetime(2026, 1, 2, tzinfo=UTC),
        windows=(
            CandidateForwardWindowOutcome(
                window="20d",
                forward_open=Decimal("100"),
                forward_high=Decimal("110"),
                forward_low=Decimal("95"),
                forward_close=Decimal("106") if won else Decimal("96"),
                forward_return_pct_from_close=Decimal("6") if won else Decimal("-4"),
                forward_return_pct_from_entry=Decimal("5") if won else Decimal("-5"),
                max_favourable_excursion_pct=Decimal("10"),
                max_adverse_excursion_pct=Decimal("-5"),
                target_1_touched=label is CandidateOutcomeLabel.WOULD_HAVE_WON,
                risk_stop_touched=label is CandidateOutcomeLabel.WOULD_HAVE_LOST,
                outcome_label=label,
            ),
        ),
    )


def _raw_record(
    symbol: str,
    *,
    emitted: bool = False,
    verdict: str | None = None,
    stage: ExclusionStage = ExclusionStage.SETUP_FILTER,
    reasons: tuple[str, ...] = ("Not emitted",),
    close: Decimal = Decimal("100"),
    stop: Decimal | None = Decimal("95"),
    target_1: Decimal | None = Decimal("110"),
    indicators: tuple[str, ...] = ("breakout",),
    regime: str = "BULLISH",
) -> RawCandidateRecord:
    return RawCandidateRecord(
        raw_candidate_id=f"raw-{symbol}",
        run_id="run-1",
        evaluation_date=date(2026, 1, 1),
        symbol=symbol,
        company_name=f"{symbol} Ltd",
        sector="IT",
        universe_source="test",
        was_emitted_decision=emitted,
        emitted_verdict=verdict,
        excluded_stage=ExclusionStage.FINAL_RECOMMENDATION if emitted else stage,
        exclusion_reasons=() if emitted else reasons,
        raw_rank=1,
        preliminary_score=Decimal("72"),
        data_quality_score=Decimal("1"),
        liquidity_score=Decimal("0.80"),
        trend_score=Decimal("0.70"),
        momentum_score=Decimal("0.65"),
        volume_score=Decimal("0.60"),
        volatility_score=Decimal("0.40"),
        relative_strength_score=Decimal("0.75"),
        setup_score=Decimal("0.70"),
        risk_score=Decimal("0.65"),
        regime_score=Decimal("0.60"),
        final_strategy_score=Decimal("72"),
        indicators_active=indicators,
        indicator_scores=MappingProxyType({"strategy": "72"}),
        market_regime=regime,
        long_trade_permission=emitted,
        close_price=close,
        entry_candidate_price=close,
        risk_stop=stop,
        target_1=target_1,
        target_2=Decimal("116"),
        target_3=Decimal("122"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _candidate_with_scores() -> RecommendationCandidate:
    return RecommendationCandidate(
        symbol="AAA",
        observed_on=date(2026, 1, 1),
        action=RecommendationAction.BUY,
        strategy_score=Decimal("0.82"),
        probability_score=Decimal("0.70"),
        market_intelligence_score=Decimal("0.65"),
        liquidity_score=Decimal("0.72"),
        risk_score=Decimal("0.30"),
        expected_return=Decimal("0.12"),
        expected_drawdown=Decimal("0.05"),
        expected_holding_period_days=Decimal("15"),
        evidence=(
            RecommendationEvidence(
                label="Price Volume",
                score_points=Decimal("8"),
                max_points=Decimal("10"),
                rationale="Constructive.",
            ),
        ),
        trend_structure_score=Decimal("0.76"),
        volume_confirmation_score=Decimal("0.71"),
        relative_strength_score=Decimal("0.74"),
        breakout_setup_score=Decimal("0.68"),
        retracement_score=Decimal("0.55"),
        market_regime_score=Decimal("0.61"),
        market_regime="BULLISH",
    )


def _raw_outcome(
    raw_candidate_id: str,
    label: CandidateOutcomeLabel,
    *,
    forward_return: Decimal | None = None,
) -> RawCandidateForwardOutcome:
    if forward_return is None:
        forward_return = (
            Decimal("6")
            if label is CandidateOutcomeLabel.WOULD_HAVE_WON
            else Decimal("-4")
        )
    return RawCandidateForwardOutcome(
        raw_candidate_id=raw_candidate_id,
        symbol=raw_candidate_id.replace("raw-", ""),
        evaluated_at=datetime(2026, 1, 2, tzinfo=UTC),
        windows=(
            RawForwardWindowOutcome(
                window="20d",
                forward_return_pct_from_close=forward_return,
                max_favourable_excursion_pct=Decimal("10"),
                max_adverse_excursion_pct=Decimal("-5"),
                target_1_touched=label is CandidateOutcomeLabel.WOULD_HAVE_WON,
                risk_stop_touched=label is CandidateOutcomeLabel.WOULD_HAVE_LOST,
                outcome_label=label,
            ),
        ),
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
