"""Tests for recovered security identity decision integration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from alpha.decision_intelligence.identity import (
    RecoveredIdentityDecisionEngine,
    RecoveredSecurityIdentityIndex,
)
from alpha.decision_intelligence.models import (
    CapacityAssessment,
    InstitutionalCandidate,
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


def _index(tmp_path: Path) -> RecoveredSecurityIdentityIndex:
    master = tmp_path / "security_master.json"
    master.write_text(
        json.dumps(
            [
                {
                    "security_id": "SEC-1",
                    "isin": "INE000000001",
                    "symbol": "INFY",
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
    return RecoveredSecurityIdentityIndex.from_recovery_result(result)


def test_resolves_symbol_isin_and_security_id(tmp_path: Path) -> None:
    index = _index(tmp_path)

    assert index.resolve("infy").identity is not None
    assert index.resolve("INE000000001").matched_by == "isin"
    assert index.resolve("SEC-1").matched_by in {"record_key", "security_id"}


def test_canonicalizes_candidate_before_decision(tmp_path: Path) -> None:
    engine = RecoveredIdentityDecisionEngine(_index(tmp_path))

    candidates = engine.canonicalize_candidates((_candidate("infy"),))

    assert candidates[0].symbol == "INFY"
    report = engine.evaluate((_candidate("infy"),))
    assert report.candidates_scanned == 1
    assert report.decisions[0].candidate.symbol == "INFY"


def test_parity_report_detects_unresolved_identity(tmp_path: Path) -> None:
    engine = RecoveredIdentityDecisionEngine(_index(tmp_path))

    report = engine.parity_report((_candidate("INFY"), _candidate("MISSING")))

    assert report.candidate_count == 2
    assert report.resolved_count == 1
    assert report.unresolved_symbols == ("MISSING",)
    assert not report.parity_preserved


def test_strict_mode_blocks_unresolved_identity(tmp_path: Path) -> None:
    engine = RecoveredIdentityDecisionEngine(_index(tmp_path))

    with pytest.raises(KeyError, match="MISSING"):
        engine.evaluate((_candidate("MISSING"),))


def test_preview_csv_can_drive_decision_identity(tmp_path: Path) -> None:
    preview = tmp_path / "canonical_preview.csv"
    preview.write_text(
        "record_key,security_id,isin,symbol,exchange,entity_confidence,"
        "recovery_version\n"
        "SEC-1,SEC-1,INE000000001,INFY,NSE,0.9,HTR-002-v1.0.0\n",
        encoding="utf-8",
    )

    index = RecoveredSecurityIdentityIndex.from_preview_csv(preview)

    resolution = index.resolve("INE000000001")
    assert resolution.identity is not None
    assert resolution.identity.symbol == "INFY"
    assert resolution.identity.confidence == 0.9
