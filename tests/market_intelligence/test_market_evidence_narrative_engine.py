from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.market_intelligence import (
    EvidenceCategory,
    EvidenceDirection,
    EvidenceNarrativeEngine,
    MarketEvidenceSignal,
)


def test_evidence_narrative_explains_supporting_market_evidence() -> None:
    narrative = EvidenceNarrativeEngine().build(
        symbol="hal",
        recommendation="buy",
        score=Decimal("91.4"),
        evidence=(
            MarketEvidenceSignal(
                category=EvidenceCategory.DELIVERY,
                label="Delivery accumulation",
                direction=EvidenceDirection.SUPPORTIVE,
                strength=Decimal("88"),
                observation="Delivery rose from 46% to 73%",
                meaning=(
                    "More buyers are carrying shares forward instead of "
                    "only trading intraday."
                ),
                score_points=Decimal("18.2"),
            ),
            MarketEvidenceSignal(
                category=EvidenceCategory.INSTITUTIONAL_FLOW,
                label="FII interest",
                direction=EvidenceDirection.SUPPORTIVE,
                strength=Decimal("81"),
                observation="FII participation improved for 3 sessions",
                meaning="Foreign institutional interest is improving.",
                score_points=Decimal("14.4"),
            ),
        ),
    )

    lines = EvidenceNarrativeEngine().explain(narrative)

    assert lines[0] == "Why HAL is BUY:"
    assert "Recommendation Score: 91.4/100" in lines
    assert any("Delivery rose from 46% to 73%" in line for line in lines)
    assert any("FII participation improved" in line for line in lines)
    assert narrative.total_supportive_points == Decimal("32.6")


def test_evidence_narrative_sorts_evidence_by_score_points() -> None:
    narrative = EvidenceNarrativeEngine().build(
        symbol="tcs",
        recommendation="hold",
        score=Decimal("64"),
        evidence=(
            MarketEvidenceSignal(
                category=EvidenceCategory.BREADTH,
                label="Market breadth",
                direction=EvidenceDirection.SUPPORTIVE,
                strength=Decimal("80"),
                observation="Breadth improved",
                meaning="Broader participation is supportive.",
                score_points=Decimal("7"),
            ),
            MarketEvidenceSignal(
                category=EvidenceCategory.DELIVERY,
                label="Delivery trend",
                direction=EvidenceDirection.SUPPORTIVE,
                strength=Decimal("75"),
                observation="Delivery improved",
                meaning="Buyer conviction improved.",
                score_points=Decimal("12"),
            ),
        ),
    )

    assert narrative.supportive[0].label == "Delivery trend"
    assert narrative.supportive[1].label == "Market breadth"


def test_evidence_narrative_separates_cautionary_signals() -> None:
    narrative = EvidenceNarrativeEngine().build(
        symbol="infy",
        recommendation="buy",
        score=Decimal("72"),
        evidence=(
            MarketEvidenceSignal(
                category=EvidenceCategory.RISK,
                label="Options resistance",
                direction=EvidenceDirection.CAUTION,
                strength=Decimal("66"),
                observation="Call open interest is concentrated near spot",
                meaning="Upside may be capped in the short term.",
                score_points=Decimal("4"),
            ),
        ),
    )

    lines = EvidenceNarrativeEngine().explain(narrative)

    assert narrative.strongest_support is None
    assert narrative.strongest_caution is not None
    assert any("Evidence that can reduce conviction:" in line for line in lines)
    assert any("Options resistance" in line for line in lines)


def test_evidence_narrative_renders_metadata() -> None:
    narrative = EvidenceNarrativeEngine().build(
        symbol="bel",
        recommendation="buy",
        score=Decimal("88"),
        evidence=(
            MarketEvidenceSignal(
                category=EvidenceCategory.DERIVATIVES,
                label="New long build-up",
                direction=EvidenceDirection.SUPPORTIVE,
                strength=Decimal("82"),
                observation="Price rose while open interest expanded",
                meaning="Fresh leveraged long positions are likely.",
                score_points=Decimal("13"),
                metadata={"price_change": "+3.2%", "oi_change": "+9.4%"},
            ),
        ),
    )

    lines = EvidenceNarrativeEngine().explain(narrative)

    assert "  oi_change: +9.4%" in lines
    assert "  price_change: +3.2%" in lines


def test_market_evidence_signal_rejects_invalid_strength() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        MarketEvidenceSignal(
            category=EvidenceCategory.DELIVERY,
            label="Delivery",
            direction=EvidenceDirection.SUPPORTIVE,
            strength=Decimal("101"),
            observation="Delivery expanded",
            meaning="Buyer conviction improved.",
        )


def test_market_evidence_signal_rejects_negative_score_points() -> None:
    with pytest.raises(ValueError, match="score points"):
        MarketEvidenceSignal(
            category=EvidenceCategory.RISK,
            label="Risk",
            direction=EvidenceDirection.CAUTION,
            strength=Decimal("40"),
            observation="Risk increased",
            meaning="Conviction should be reduced.",
            score_points=Decimal("-1"),
        )


def test_market_evidence_signal_normalizes_label_and_metadata() -> None:
    signal = MarketEvidenceSignal(
        category=EvidenceCategory.OTHER,
        label=" Delivery quality ",
        direction=EvidenceDirection.NEUTRAL,
        strength=Decimal("50"),
        observation="Delivery is normal",
        meaning="No strong conviction change.",
        metadata={" percentile ": " 55 "},
    )

    assert signal.label == "Delivery quality"
    assert signal.metadata["percentile"] == "55"

    with pytest.raises(TypeError):
        signal.metadata["percentile"] = "60"
