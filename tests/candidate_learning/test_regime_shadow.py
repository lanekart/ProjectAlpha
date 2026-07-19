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
from alpha.candidate_learning.regime_shadow import (
    RegimeShadowDecisionStatus,
    RegimeShadowEngine,
    RegimeShadowIntegrityStatus,
    RegimeShadowPolicyId,
    RegimeShadowRepository,
    export_regime_shadow_csv,
    export_regime_shadow_json,
)
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.cli import app


def test_shadow_policy_registry_is_versioned_and_stable(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    policies = {policy.policy_id: policy for policy in engine.policies()}

    assert (
        policies[RegimeShadowPolicyId.CONTROL].policy_version
        == "regime-shadow-control-v1"
    )
    assert (
        policies[RegimeShadowPolicyId.CONTEXT_ONLY].policy_version
        == "regime-shadow-context-only-v1"
    )
    assert (
        policies[RegimeShadowPolicyId.BEARISH_ONLY].policy_version
        == "regime-shadow-bearish-only-v1"
    )
    assert policies[RegimeShadowPolicyId.CONTROL].policy_fingerprint
    assert policies[RegimeShadowPolicyId.CONTEXT_ONLY].policy_fingerprint
    assert policies[RegimeShadowPolicyId.BEARISH_ONLY].policy_fingerprint


def test_control_context_only_and_bearish_only_decisions(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    decisions = engine.build(persist=False).decisions

    by_key = {(row.authoritative_candidate_id, row.policy_id): row for row in decisions}
    control = by_key[("candidate-AAA", RegimeShadowPolicyId.CONTROL)]
    context = by_key[("candidate-AAA", RegimeShadowPolicyId.CONTEXT_ONLY)]
    bearish = by_key[("candidate-AAA", RegimeShadowPolicyId.BEARISH_ONLY)]
    bear_context = by_key[("candidate-BBB", RegimeShadowPolicyId.CONTEXT_ONLY)]
    bear_only = by_key[("candidate-BBB", RegimeShadowPolicyId.BEARISH_ONLY)]

    assert control.shadow_score == Decimal("78.0000")
    assert control.shadow_verdict == control.authoritative_verdict == "BUY"
    assert context.regime_adjustment == Decimal("0")
    assert context.shadow_score == Decimal("74.0000")
    assert context.shadow_verdict == "WATCHLIST"
    assert bearish.shadow_score == Decimal("74.0000")
    assert bear_context.shadow_score == Decimal("66.0000")
    assert bear_context.shadow_verdict == "WATCHLIST"
    assert bear_only.regime_adjustment == Decimal("-8")
    assert bear_only.shadow_verdict == "AVOID"
    assert all(row.authoritative is False for row in decisions)
    assert all(row.executable is False for row in decisions)
    assert all(row.capital_effect == "none" for row in decisions)


def test_shadow_repository_persistence_is_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    first = engine.build(persist=True)
    second = engine.build(persist=True)
    stored = RegimeShadowRepository(_shadow_ledger(tmp_path)).load_decisions()

    assert first.inserted_decisions == 12
    assert second.inserted_decisions == 0
    assert len(stored) == 12


def test_integrity_comparisons_and_attribution_reports(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.build(persist=True)

    integrity = engine.integrity()
    scores = {row.policy_id: row for row in engine.score_comparison()}
    approvals = {row.policy_id: row for row in engine.approval_comparison()}
    outcomes = {row.policy_id: row for row in engine.outcomes()}
    protection = engine.bearish_protection()
    promotion = engine.bullish_promotion()
    setup = engine.setup_attribution()
    readiness = engine.readiness()

    assert integrity.status is RegimeShadowIntegrityStatus.VALID
    assert scores[RegimeShadowPolicyId.CONTEXT_ONLY].changed_scores >= 3
    assert (
        approvals[RegimeShadowPolicyId.CONTEXT_ONLY].approval_eligibility_changes == 1
    )
    assert outcomes[RegimeShadowPolicyId.CONTROL].completed_outcomes == 4
    assert protection.bearish_demotions_removed >= 1
    assert promotion.bullish_promotions_under_control >= 1
    assert {row.setup_family for row in setup} >= {"BREAKOUT", "PULLBACK_RETRACEMENT"}
    assert (
        readiness.readiness_status
        is RegimeShadowDecisionStatus.NOT_READY_FOR_POLICY_CHANGE
    )


def test_shadow_exports_are_deterministic(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    result = engine.build(persist=False)
    json_path = export_regime_shadow_json(
        result,
        tmp_path / "shadow.json",
    )
    csv_path = export_regime_shadow_csv(
        result.decisions,
        tmp_path / "shadow.csv",
    )

    assert json.loads(json_path.read_text(encoding="utf-8"))["dry_run"] is True
    assert "policy_id" in csv_path.read_text(encoding="utf-8").splitlines()[0]


def test_live_shadow_is_disabled_by_default(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    engine = _engine(tmp_path)
    monkeypatch.delenv("ALPHA_REGIME_SHADOW_ENABLED", raising=False)

    assert engine.live_shadow_enabled() is False
    monkeypatch.setenv("ALPHA_REGIME_SHADOW_ENABLED", "true")
    assert engine.live_shadow_enabled() is True


def test_replay_cli_regime_shadow_commands(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHA_CANDIDATE_LEARNING_LEDGER", str(_ledger(tmp_path)))
    monkeypatch.setenv("ALPHA_POINT_IN_TIME_ANALYTICAL_STORE", str(_store(tmp_path)))
    monkeypatch.setenv("ALPHA_REGIME_SHADOW_LEDGER", str(_shadow_ledger(tmp_path)))
    runner = CliRunner()

    build = runner.invoke(
        app,
        ["replay", "regime-shadow-build", "--persist-diagnostic"],
    )
    assert build.exit_code == 0, build.output
    assert "Mode: persisted" in build.output

    commands = (
        "regime-shadow-status",
        "regime-shadow-integrity",
        "regime-shadow-score-comparison",
        "regime-shadow-verdict-comparison",
        "regime-shadow-approval-comparison",
        "regime-shadow-allocation-comparison",
        "regime-shadow-outcomes",
        "regime-shadow-bearish-protection",
        "regime-shadow-bullish-promotion",
        "regime-shadow-setup-attribution",
        "regime-shadow-quality",
        "regime-shadow-temporal-stability",
        "regime-shadow-readiness",
    )
    for command in commands:
        result = runner.invoke(app, ["replay", command])
        assert result.exit_code == 0, result.output
        assert "Regime Shadow" in result.output

    weighted = runner.invoke(
        app,
        ["replay", "regime-shadow-outcomes", "--date-weighted"],
    )
    assert weighted.exit_code == 0, weighted.output
    assert "/DATE" in weighted.output

    output = tmp_path / "shadow-status.json"
    exported = runner.invoke(
        app,
        [
            "replay",
            "regime-shadow-status",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )
    assert exported.exit_code == 0, exported.output
    assert json.loads(output.read_text(encoding="utf-8"))["stored_decisions"] == 12


def _engine(tmp_path: Path) -> RegimeShadowEngine:
    return RegimeShadowEngine(
        learning_ledger_path=_ledger(tmp_path),
        shadow_ledger_path=_shadow_ledger(tmp_path),
        store_path=_store(tmp_path),
    )


def _shadow_ledger(tmp_path: Path) -> Path:
    return tmp_path / "regime-shadow.json"


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
        explanation="Synthetic regime shadow record.",
        market_state_snapshot_id=f"snapshot-{symbol}",
        decision_provenance_id=f"provenance-{symbol}",
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
