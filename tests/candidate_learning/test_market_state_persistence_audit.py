from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from typer.testing import CliRunner

from alpha.candidate_learning import (
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
    LearningLedgerRepository,
)
from alpha.candidate_learning.market_state_persistence_audit import (
    ClassifierReplayAgreement,
    MarketStateConclusion,
    MarketStatePersistenceAuditConfig,
    MarketStatePersistenceAuditEngine,
    MarketStateReconstructionStatus,
    NeutralFallbackReason,
    NextMarketStateMilestone,
    TimestampAlignment,
    export_market_state_persistence_audit_csv,
    export_market_state_persistence_audit_json,
    group_market_state_persistence_audit,
    render_market_state_persistence_audit,
)
from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.cli import app


def test_inventory_reconstruction_and_policy_integrity() -> None:
    report = MarketStatePersistenceAuditEngine().analyze(
        records=_records(),
        outcomes=_outcomes(),
    )

    assert report.inventory
    assert any(
        item.reconstruction_status
        is MarketStateReconstructionStatus.PARTIALLY_RECONSTRUCTED
        for item in report.snapshots
    )
    assert report.recommendation_scores_unchanged is True
    assert report.verdicts_unchanged is True
    assert report.timing_states_unchanged is True
    assert report.approvals_unchanged is True
    assert report.trade_plans_unchanged is True
    assert report.allocations_unchanged is True
    assert report.production_regime_labels_unchanged is True
    assert report.persisted_candidate_records_unchanged is True


def test_timestamp_alignment_states_are_classified() -> None:
    report = MarketStatePersistenceAuditEngine().analyze(
        records=(
            _record("EXACT", source_date="2026-01-01"),
            _record("STALE", source_date="2025-12-01"),
            _record("FUTURE", source_date="2026-02-01"),
            _record("MISSING", regime=None),
        ),
        outcomes=(
            _outcome("candidate-EXACT", Decimal("4")),
            _outcome("candidate-STALE", Decimal("-3")),
            _outcome("candidate-FUTURE", Decimal("-2")),
            _outcome("candidate-MISSING", Decimal("1")),
        ),
    )
    alignments = {item.alignment for item in report.timestamp_findings}

    assert TimestampAlignment.EXACT in alignments
    assert TimestampAlignment.CARRIED_FORWARD_STALE in alignments
    assert TimestampAlignment.FUTURE_TIMESTAMP in alignments
    assert TimestampAlignment.MISSING_TIMESTAMP in alignments


def test_fallback_attribution_separates_genuine_and_default_neutral() -> None:
    report = MarketStatePersistenceAuditEngine().analyze(
        records=(
            _record("GENUINE", regime="NEUTRAL", benchmark=Decimal("0")),
            _record("DEFAULT", regime="NEUTRAL", include_benchmark=False),
        ),
        outcomes=(
            _outcome("candidate-GENUINE", Decimal("1")),
            _outcome("candidate-DEFAULT", Decimal("-4")),
        ),
    )
    reasons = {item.primary_reason for item in report.fallback_attributions}

    assert NeutralFallbackReason.GENUINE_NEUTRAL_CLASSIFICATION in reasons
    assert NeutralFallbackReason.MISSING_BENCHMARK_INPUT in reasons


def test_classifier_replay_neutral_collapse_and_sign_conflict() -> None:
    report = MarketStatePersistenceAuditEngine().analyze(
        records=(
            _record("COLLAPSE", regime="NEUTRAL", benchmark=Decimal("-6")),
            _record("CONFLICT", regime="BULL", benchmark=Decimal("-7")),
        ),
        outcomes=(
            _outcome("candidate-COLLAPSE", Decimal("-5")),
            _outcome("candidate-CONFLICT", Decimal("-6")),
        ),
    )
    agreements = {item.agreement for item in report.classifier_replay}

    assert ClassifierReplayAgreement.NEUTRAL_COLLAPSE in agreements
    assert ClassifierReplayAgreement.SIGN_CONFLICT in agreements


def test_conclusion_and_next_milestone_are_deterministic() -> None:
    empty = MarketStatePersistenceAuditEngine().analyze(records=(), outcomes=())
    populated = MarketStatePersistenceAuditEngine(
        MarketStatePersistenceAuditConfig(minimum_sample=3)
    ).analyze(
        records=_records(),
        outcomes=_outcomes(),
    )

    assert (
        empty.decision.primary_conclusion
        is MarketStateConclusion.INSUFFICIENT_EVIDENCE_FOR_MARKET_STATE_CONCLUSION
    )
    assert (
        populated.decision.primary_conclusion
        is MarketStateConclusion.MARKET_STATE_HISTORY_NOT_PERSISTED
    )
    assert (
        populated.decision.recommended_next_milestone
        is NextMarketStateMilestone.ADD_AUTHORITATIVE_MARKET_STATE_SNAPSHOTS
    )


def test_exports_and_cli_rendering(tmp_path, monkeypatch) -> None:
    ledger = LearningLedgerRepository(tmp_path / "learning.json")
    ledger.save_records(_records())
    ledger.upsert_outcomes(_outcomes())
    monkeypatch.setenv(
        "ALPHA_CANDIDATE_LEARNING_LEDGER",
        str(tmp_path / "learning.json"),
    )
    report = MarketStatePersistenceAuditEngine().analyze(
        records=ledger.load_records(),
        outcomes=ledger.load_outcomes(),
    )
    json_path = tmp_path / "market_state.json"
    csv_path = tmp_path / "market_state.csv"

    export_market_state_persistence_audit_json(report, json_path)
    export_market_state_persistence_audit_csv(report, csv_path)
    rendered = "\n".join(render_market_state_persistence_audit(report))
    grouped = "\n".join(
        group_market_state_persistence_audit(report, group_by="fallback")
    )
    cli = CliRunner().invoke(app, ["replay", "market-state-persistence-audit"])
    inventory = CliRunner().invoke(app, ["replay", "market-state-inventory"])

    assert json.loads(json_path.read_text(encoding="utf-8"))["candidate_count"] == 4
    assert "reconstruction_status" in csv_path.read_text(encoding="utf-8")
    assert "Market State Persistence & Reconstruction Audit" in rendered
    assert "Market State Fallbacks" in grouped
    assert cli.exit_code == 0
    assert "Primary Conclusion" in cli.stdout
    assert inventory.exit_code == 0
    assert "Market State Inventory" in inventory.stdout


def _records() -> tuple[CandidateDecisionRecord, ...]:
    return (
        _record("A", regime="NEUTRAL", benchmark=Decimal("-6")),
        _record("B", regime="NEUTRAL", include_benchmark=False),
        _record("C", regime="BULL", benchmark=Decimal("6")),
        _record("D", regime="BEAR", benchmark=Decimal("-8")),
    )


def _outcomes() -> tuple[CandidateForwardOutcome, ...]:
    return (
        _outcome("candidate-A", Decimal("-4")),
        _outcome("candidate-B", Decimal("-3")),
        _outcome("candidate-C", Decimal("6")),
        _outcome("candidate-D", Decimal("-5")),
    )


def _record(
    symbol: str,
    *,
    regime: str | None = "NEUTRAL",
    benchmark: Decimal = Decimal("1"),
    include_benchmark: bool = True,
    source_date: str | None = None,
) -> CandidateDecisionRecord:
    scores = {
        "price": "70",
        "trend": "70",
        "volume": "60",
        "breadth-score": "55",
        "atr": "3",
        "classifier-version": "test-v1",
    }
    if include_benchmark:
        scores["benchmark-return"] = str(benchmark)
    if source_date is not None:
        scores["market-state-source-date"] = source_date
    return CandidateDecisionRecord(
        candidate_id=f"candidate-{symbol}",
        run_id="run",
        evaluation_date=date(2026, 1, 1),
        symbol=symbol,
        final_verdict="BUY" if regime == "BULL" else "AVOID",
        capital_action="BUY" if regime == "BULL" else "AVOID",
        approved_for_deployment=regime == "BULL",
        rejection_reasons=() if regime == "BULL" else ("test rejection",),
        setup_type="MOMENTUM CONTINUATION",
        market_regime=regime,
        long_trade_permission=True,
        strategy_score=Decimal("80") if regime == "BULL" else Decimal("60"),
        confidence="HIGH",
        data_quality="COMPLETE",
        entry_zone_low=Decimal("100"),
        entry_zone_high=Decimal("102"),
        confirmation_entry=Decimal("102"),
        risk_stop=Decimal("95"),
        target_1=Decimal("112"),
        target_2=Decimal("125"),
        target_3=Decimal("140"),
        trailing_stop_plan="Trail using 2 x ATR.",
        expected_holding_period="20d",
        indicators_active=("price", "trend", "volume"),
        indicator_scores=scores,
        evidence_layers=("Price/Volume",),
        explanation="Synthetic market-state audit candidate.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        sector="IT",
    )


def _outcome(candidate_id: str, forward_return: Decimal) -> CandidateForwardOutcome:
    won = forward_return > Decimal("0")
    return CandidateForwardOutcome(
        candidate_id=candidate_id,
        symbol=candidate_id.replace("candidate-", ""),
        evaluated_at=datetime(2026, 1, 22, tzinfo=UTC),
        windows=(
            CandidateForwardWindowOutcome(
                window="20d",
                forward_open=Decimal("100"),
                forward_high=Decimal("115") if won else Decimal("103"),
                forward_low=Decimal("98") if won else Decimal("90"),
                forward_close=Decimal("100") + forward_return,
                forward_return_pct_from_close=forward_return,
                forward_return_pct_from_entry=forward_return,
                max_favourable_excursion_pct=Decimal("10") if won else Decimal("2"),
                max_adverse_excursion_pct=Decimal("-2") if won else Decimal("-9"),
                target_1_touched=won,
                risk_stop_touched=not won,
                outcome_label=CandidateOutcomeLabel.WOULD_HAVE_WON
                if won
                else CandidateOutcomeLabel.WOULD_HAVE_LOST,
            ),
        ),
    )
