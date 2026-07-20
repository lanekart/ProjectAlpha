"""Tests for decision parity validation."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alpha.decision_intelligence.identity import (
    RecoveredIdentityDecisionEngine,
    RecoveredSecurityIdentityIndex,
)
from alpha.decision_intelligence.models import (
    CapacityAssessment,
    InstitutionalCandidate,
)
from alpha.decision_intelligence.parity import (
    DecisionParityClassification,
    DecisionParityValidator,
    export_decision_parity,
)
from alpha.recovery import RecoveryContext, SecurityEntityRecoveryEngine


def _candidate(symbol: str) -> InstitutionalCandidate:
    return InstitutionalCandidate(
        symbol=symbol,
        final_verdict="BUY",
        adjusted_confidence="HIGH",
        evidence_strength="strong",
        final_score=Decimal("90"),
        reward_risk_ratio=Decimal("2.5"),
        stop_distance_percent=Decimal("5"),
        data_completeness="COMPLETE",
        setup_quality="HIGH",
        sector="IT",
        market_regime="BULL",
        sector_fit=Decimal("90"),
        portfolio_fit=Decimal("90"),
        posterior_probability=Decimal("0.60"),
        expectancy=Decimal("0.20"),
        entry=Decimal("100"),
        stop=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        capacity=CapacityAssessment(
            capacity_score=Decimal("90"),
            deployable_capital_estimate=Decimal("100000"),
            liquidity_warning=None,
            explanation="Sufficient liquidity.",
            data_sufficient=True,
        ),
        dma_20=Decimal("96"),
        atr=Decimal("2"),
        evidence_sample_count=100,
    )


def _engine(tmp_path: Path, symbol: str = "INFY") -> RecoveredIdentityDecisionEngine:
    master = tmp_path / "security_master.json"
    master.write_text(
        json.dumps(
            [
                {
                    "security_id": "SEC-1",
                    "isin": "INE000000001",
                    "symbol": symbol,
                    "exchange": "NSE",
                }
            ]
        ),
        encoding="utf-8",
    )
    result = SecurityEntityRecoveryEngine().run(
        RecoveryContext(
            engine_key="security-entity-recovery",
            as_of=datetime(2026, 7, 20, tzinfo=UTC),
            parameters={"security_master": master},
        )
    )
    index = RecoveredSecurityIdentityIndex.from_recovery_result(result)
    return RecoveredIdentityDecisionEngine(index)


def test_identical_decisions_pass(tmp_path: Path) -> None:
    report = DecisionParityValidator(_engine(tmp_path)).validate((_candidate("INFY"),))

    assert report.passed
    assert report.identical == 1
    assert report.unexpected_changes == 0


def test_symbol_rename_is_expected(tmp_path: Path) -> None:
    report = DecisionParityValidator(_engine(tmp_path, "INFY")).validate(
        (_candidate("infy"),)
    )

    assert report.passed
    assert report.expected_changes == 1
    assert report.candidate_results[0].classification is (
        DecisionParityClassification.EXPECTED_CHANGE
    )


def test_score_change_is_unexpected(tmp_path: Path) -> None:
    validator = DecisionParityValidator(_engine(tmp_path))
    candidate = _candidate("INFY")
    legacy = validator.legacy_engine.evaluate((candidate,))
    recovered = validator.legacy_engine.evaluate(
        (replace(candidate, final_score=Decimal("89")),)
    )

    report = validator.compare_reports(legacy, recovered)

    assert not report.passed
    assert report.unexpected_changes == 1


def test_empty_input_passes(tmp_path: Path) -> None:
    report = DecisionParityValidator(_engine(tmp_path)).validate(())

    assert report.passed
    assert report.candidates_compared == 0
    assert report.parity_percentage == Decimal("100.00")


def test_exports_are_deterministic(tmp_path: Path) -> None:
    report = DecisionParityValidator(_engine(tmp_path)).validate((_candidate("INFY"),))

    paths = export_decision_parity(report, tmp_path / "parity")

    assert tuple(path.name for path in paths) == (
        "summary.json",
        "summary.csv",
        "candidate_differences.csv",
        "unexpected_changes.csv",
        "report.md",
    )
    assert json.loads(paths[0].read_text(encoding="utf-8"))["passed"] is True
    assert paths[-1].read_text(encoding="utf-8").startswith(
        "# Decision Parity Validation\n"
    )
