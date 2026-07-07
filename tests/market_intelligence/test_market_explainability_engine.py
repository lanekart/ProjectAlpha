from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.market_intelligence import (
    EvidencePoint,
    ExplainabilityEngine,
    ExplanationChangeReport,
    ExplanationDelta,
    ExplanationLevel,
    RecommendationExplanation,
    RiskFactor,
    ScoreContribution,
    build_evidence_points,
)


def test_explainability_engine_renders_beginner_explanation() -> None:
    explanation = RecommendationExplanation(
        symbol="hal",
        action="buy",
        score=Decimal("91.4"),
        explanation_level=ExplanationLevel.BEGINNER,
        contributions=(
            ScoreContribution(
                name="Institutional Accumulation",
                points=Decimal("18.2"),
                max_points=Decimal("20"),
                evidence=(
                    EvidencePoint(
                        label="Delivery trend",
                        value="46% to 73%",
                        interpretation=(
                            "More shares are being carried forward by buyers."
                        ),
                    ),
                ),
                plain_language=(
                    "Delivery has risen, which means more investors are "
                    "choosing to keep the shares instead of trading intraday."
                ),
            ),
        ),
        risks=(
            RiskFactor(
                name="Crowded options zone",
                severity="medium",
                explanation="Nearby option open interest may cap upside.",
            ),
        ),
        metadata={"Regime": "Bull Expansion"},
    )

    lines = ExplainabilityEngine().explain(explanation)

    assert lines[0] == "HAL BUY explanation"
    assert "Recommendation Score: 91.4/100" in lines
    assert any("Delivery has risen" in line for line in lines)
    assert any("Counterarguments and risks:" in line for line in lines)
    assert any("Regime: Bull Expansion" in line for line in lines)


def test_explainability_engine_renders_intermediate_evidence() -> None:
    explanation = RecommendationExplanation(
        symbol="tcs",
        action="hold",
        score=Decimal("64.5"),
        explanation_level=ExplanationLevel.INTERMEDIATE,
        contributions=(
            ScoreContribution(
                name="FII Interest",
                points=Decimal("11.4"),
                max_points=Decimal("15"),
                evidence=(
                    EvidencePoint(
                        label="FII flow",
                        value="Net buying improved for 3 sessions",
                        interpretation=(
                            "Foreign institutional participation is improving."
                        ),
                    ),
                ),
                plain_language="FII buying has improved.",
            ),
        ),
    )

    lines = ExplainabilityEngine().explain(explanation)

    assert "- FII flow: Net buying improved for 3 sessions" in lines
    assert any("Foreign institutional participation" in line for line in lines)


def test_explainability_engine_renders_professional_ratio() -> None:
    explanation = RecommendationExplanation(
        symbol="bel",
        action="buy",
        score=Decimal("88.0"),
        explanation_level=ExplanationLevel.PROFESSIONAL,
        contributions=(
            ScoreContribution(
                name="Derivatives Positioning",
                points=Decimal("12"),
                max_points=Decimal("16"),
                evidence=(
                    EvidencePoint(
                        label="Price and OI",
                        value="Price up, OI up",
                        interpretation="New long build-up is likely.",
                    ),
                ),
                plain_language="Derivatives positioning is supportive.",
            ),
        ),
    )

    lines = ExplainabilityEngine().explain(explanation)

    assert "  Contribution ratio: 0.7500" in lines


def test_explanation_sorts_change_report_by_absolute_impact() -> None:
    report = ExplanationChangeReport(
        symbol="hal",
        previous_score=Decimal("84.6"),
        current_score=Decimal("91.4"),
        deltas=(
            ExplanationDelta(
                label="Delivery",
                previous="61%",
                current="73%",
                impact=Decimal("4.1"),
                explanation="Delivery expansion improved accumulation quality.",
            ),
            ExplanationDelta(
                label="Options risk",
                previous="low",
                current="medium",
                impact=Decimal("-1.2"),
                explanation="Resistance concentration increased near spot.",
            ),
        ),
    )

    lines = ExplainabilityEngine().explain_changes(report)

    assert lines[0] == "What changed for HAL:"
    assert lines[1] == ("Recommendation Score increased: 84.6 to 91.4")
    assert "Key changes:" in lines

    delivery_index = _line_index(
        lines,
        prefix="- Delivery:",
    )
    options_index = _line_index(
        lines,
        prefix="- Options risk:",
    )

    assert delivery_index < options_index


def _line_index(lines: tuple[str, ...], *, prefix: str) -> int:
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index

    raise AssertionError(f"Expected line starting with {prefix!r}")


def test_score_contribution_rejects_invalid_points() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        ScoreContribution(
            name="Delivery",
            points=Decimal("21"),
            max_points=Decimal("20"),
            evidence=(
                EvidencePoint(
                    label="Delivery",
                    value="High",
                    interpretation="Supportive",
                ),
            ),
            plain_language="Delivery is supportive.",
        )


def test_recommendation_explanation_is_normalized_and_immutable() -> None:
    explanation = RecommendationExplanation(
        symbol=" infy ",
        action=" buy ",
        score=Decimal("77"),
        explanation_level=ExplanationLevel.BEGINNER,
        contributions=(
            ScoreContribution(
                name="Trend",
                points=Decimal("8"),
                max_points=Decimal("10"),
                evidence=(
                    EvidencePoint(
                        label="Trend",
                        value="Positive",
                        interpretation="Trend is supportive.",
                    ),
                ),
                plain_language="Trend is supportive.",
            ),
        ),
        metadata={" sector ": " it "},
    )

    assert explanation.symbol == "INFY"
    assert explanation.action == "BUY"
    assert explanation.metadata["sector"] == "it"

    with pytest.raises(TypeError):
        explanation.metadata["sector"] = "banks"


def test_build_evidence_points_creates_valid_points() -> None:
    points = build_evidence_points(
        (
            (
                "Delivery",
                "73%",
                "High delivery suggests stronger buyer conviction.",
            ),
            (
                "FII",
                "Net buying",
                "Institutional interest is supportive.",
            ),
        )
    )

    assert len(points) == 2
    assert points[0].label == "Delivery"
    assert points[1].value == "Net buying"
