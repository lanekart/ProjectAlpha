from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
from pytest import MonkeyPatch
from typer.testing import CliRunner

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.candidate_learning.regime_influence import (
    RegimeCounterfactualView,
    RegimeDependencyRole,
    RegimeInfluenceConclusion,
    RegimeInfluenceNextMilestone,
    RegimeProductionInfluenceAuditEngine,
    export_regime_influence_csv,
    export_regime_influence_json,
)
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.cli import app


def test_dependency_map_identifies_score_gate_display_and_unused_paths(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)

    roles = {row.role for row in engine.dependency_map()}

    assert RegimeDependencyRole.DIRECT_SCORE_INPUT in roles
    assert RegimeDependencyRole.DIRECT_GATE_INPUT in roles
    assert RegimeDependencyRole.DISPLAY_ONLY in roles
    assert RegimeDependencyRole.UNUSED in roles


def test_score_and_verdict_influence_detect_boundary_crossing(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)

    by_view = {row.view: row for row in engine.score_influence()}
    no_regime = by_view[RegimeCounterfactualView.NO_REGIME_INTERVENTION]

    assert no_regime.candidate_count == 4
    assert no_regime.material_score_change >= 1
    assert no_regime.score_rank_changes >= 1

    transitions = {
        row.transition: row.candidate_count for row in engine.verdict_influence()
    }
    assert transitions["BUY -> WATCHLIST"] == 1
    assert transitions["AVOID -> WATCHLIST"] == 1
    assert transitions["WATCHLIST -> WATCHLIST"] >= 1


def test_ranking_approval_allocation_and_asymmetry_reports(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    ranking = {row.view: row for row in engine.ranking_influence()}[
        RegimeCounterfactualView.NO_REGIME_INTERVENTION
    ]
    assert ranking.auc is not None
    assert ranking.top_decile_membership_overlap is not None

    approval = engine.approval_influence()
    assert approval.raw_recorded_approval_count == 1
    assert approval.raw_no_regime_approval_count == 0
    assert approval.profitable_approvals_lost == 1

    allocation = engine.allocation_influence()
    assert allocation.direct_allocation_consumer is False
    assert allocation.candidates_with_allocation_change == 1

    asymmetry = engine.asymmetry()
    assert asymmetry.bullish_promotions == 1
    assert asymmetry.bearish_demotions == 1
    assert asymmetry.bullish_promoted_winners == 1
    assert asymmetry.bearish_demoted_losers == 1


def test_recorded_vs_v2_context_only_and_readiness(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    comparison = engine.recorded_vs_v2()
    assert comparison.agreement_count == 3
    assert comparison.disagreement_count == 1
    assert comparison.score_differences >= 1

    context = engine.context_only()
    assert context.score_unchanged is True
    assert context.verdict_unchanged is True
    assert "explainability" in context.retained_capabilities

    readiness = engine.safe_deactivation_readiness()
    assert (
        readiness.primary_conclusion
        is RegimeInfluenceConclusion.INSUFFICIENT_EVIDENCE_FOR_REGIME_DEACTIVATION
    )
    assert (
        readiness.recommended_next_milestone
        is RegimeInfluenceNextMilestone.IMPLEMENT_REGIME_CONTEXT_ONLY_SHADOW_MODE
    )


def test_exports_are_deterministic(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    json_path = export_regime_influence_json(
        engine.approval_influence(),
        tmp_path / "approval.json",
    )
    csv_path = export_regime_influence_csv(
        engine.score_influence(),
        tmp_path / "score.csv",
    )

    assert (
        json.loads(json_path.read_text(encoding="utf-8"))["raw_recorded_approval_count"]
        == 1
    )
    assert "view" in csv_path.read_text(encoding="utf-8").splitlines()[0]


def test_replay_cli_regime_influence_commands(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHA_CANDIDATE_LEARNING_LEDGER", str(_ledger(tmp_path)))
    monkeypatch.setenv("ALPHA_POINT_IN_TIME_ANALYTICAL_STORE", str(_store(tmp_path)))
    runner = CliRunner()

    commands = (
        "regime-production-dependency",
        "regime-score-influence",
        "regime-verdict-influence",
        "regime-ranking-influence",
        "regime-selection-influence",
        "regime-approval-influence",
        "regime-allocation-influence",
        "regime-setup-influence",
        "regime-asymmetry",
        "recorded-vs-v2-regime-influence",
        "regime-context-only",
        "regime-safe-deactivation-readiness",
    )
    for command in commands:
        result = runner.invoke(app, ["replay", command])
        assert result.exit_code == 0, result.output
        assert "Regime" in result.output

    output = tmp_path / "readiness.json"
    result = runner.invoke(
        app,
        [
            "replay",
            "regime-safe-deactivation-readiness",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    assert (
        json.loads(output.read_text(encoding="utf-8"))["primary_conclusion"]
        == RegimeInfluenceConclusion.INSUFFICIENT_EVIDENCE_FOR_REGIME_DEACTIVATION.value
    )


def _engine(tmp_path: Path) -> RegimeProductionInfluenceAuditEngine:
    return RegimeProductionInfluenceAuditEngine(
        ledger_path=_ledger(tmp_path),
        store_path=_store(tmp_path),
    )


def _ledger(tmp_path: Path) -> Path:
    path = tmp_path / "learning.json"
    if path.exists():
        return path
    repository = LearningLedgerRepository(path)
    repository.save_records(
        (
            _record(
                "candidate-AAA", "AAA", "BULL", "BREAKOUT", Decimal("78"), "BUY", True
            ),
            _record(
                "candidate-BBB",
                "BBB",
                "BEAR",
                "RETRACEMENT",
                Decimal("58"),
                "AVOID",
                False,
            ),
            _record(
                "candidate-CCC",
                "CCC",
                "NEUTRAL",
                "MOMENTUM",
                Decimal("62"),
                "WATCHLIST",
                False,
            ),
            _record(
                "candidate-DDD",
                "DDD",
                None,
                "NO VALID SETUP",
                Decimal("35"),
                "SELL",
                False,
            ),
        )
    )
    repository.upsert_outcomes(
        (
            _outcome("candidate-AAA", "AAA", Decimal("8"), target=True),
            _outcome("candidate-BBB", "BBB", Decimal("-6"), stop=True),
            _outcome("candidate-CCC", "CCC", Decimal("2")),
            _outcome("candidate-DDD", "DDD", Decimal("-3")),
        )
    )
    return path


def _record(
    candidate_id: str,
    symbol: str,
    regime: str | None,
    setup: str,
    score: Decimal,
    verdict: str,
    approved: bool,
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id=candidate_id,
        run_id="run-1",
        evaluation_date=date(2026, 1, int(candidate_id[-1], 36) % 9 + 1),
        symbol=symbol,
        final_verdict=verdict,
        capital_action="BUY" if approved else verdict,
        approved_for_deployment=approved,
        rejection_reasons=(),
        setup_type=setup,
        market_regime=regime,
        long_trade_permission=approved,
        strategy_score=score,
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
        indicator_scores={"price": "0.80"},
        evidence_layers=("price-volume",),
        explanation="Synthetic regime influence record.",
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
                forward_low=Decimal("90"),
                forward_close=Decimal("105"),
                forward_return_pct_from_close=return_pct,
                forward_return_pct_from_entry=return_pct,
                max_favourable_excursion_pct=max(return_pct, Decimal("0")),
                max_adverse_excursion_pct=min(return_pct, Decimal("0")),
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


def _store(tmp_path: Path) -> Path:
    path = tmp_path / "pit.duckdb"
    if path.exists():
        return path
    with duckdb.connect(str(path)) as con:
        con.execute(
            """
            CREATE TABLE diagnostic_pit_builds (
                build_id VARCHAR,
                source_fingerprint VARCHAR,
                imported_at TIMESTAMP
            )
            """
        )
        con.execute(
            "INSERT INTO diagnostic_pit_builds VALUES ('build-1', 'fp-1', '2026-01-01')"
        )
        con.execute(
            """
            CREATE TABLE diagnostic_market_state_v2 (
                reconstruction_id VARCHAR,
                diagnostic_quality VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO diagnostic_market_state_v2 VALUES (?, ?)",
            (
                ("recon-1", "HIGH_COVERAGE"),
                ("recon-2", "HIGH_COVERAGE"),
                ("recon-3", "HIGH_COVERAGE"),
                ("recon-4", "HIGH_COVERAGE"),
            ),
        )
        con.execute(
            """
            CREATE TABLE diagnostic_market_state_v2_candidate_links (
                reconstruction_id VARCHAR,
                candidate_stable_id VARCHAR,
                v2_regime VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO diagnostic_market_state_v2_candidate_links VALUES (?, ?, ?)",
            (
                ("recon-1", "candidate-AAA", "BULLISH"),
                ("recon-2", "candidate-BBB", "BEARISH"),
                ("recon-3", "candidate-CCC", "BULLISH"),
                ("recon-4", "candidate-DDD", "UNKNOWN"),
            ),
        )
    return path
