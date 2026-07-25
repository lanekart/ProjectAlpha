from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.application.decision_superiority_gate_value_rendering import (
    render_gate_diagnostics,
)


def _report() -> dict[str, object]:
    return {
        "gate_recommendations": [
            {
                "gate_code": "GATE_B",
                "recommendation": "REMOVE",
                "reason_code": "NEGATIVE_NET_VALUE_AND_POSITIVE_REJECTED_RETURN",
                "net_gate_value": Decimal("-3"),
                "production_influence": False,
            },
            {
                "gate_code": "GATE_A",
                "recommendation": "RETAIN",
                "reason_code": "POSITIVE_NET_VALUE_AND_NEGATIVE_REJECTED_RETURN",
                "net_gate_value": Decimal("8"),
                "production_influence": False,
            },
        ],
        "gate_conclusions": [
            {
                "gate_code": "GATE_A",
                "economic_direction": "POSITIVE",
                "statistical_direction": "NEGATIVE",
                "production_influence": False,
            },
            {
                "gate_code": "GATE_B",
                "economic_direction": "NEGATIVE",
                "statistical_direction": "POSITIVE",
                "production_influence": False,
            },
        ],
        "evidence_summary": [
            {
                "gate_code": "GATE_A",
                "evidence_strength": "MODERATE",
                "confidence_status": "SUFFICIENT",
                "production_influence": False,
            },
            {
                "gate_code": "GATE_B",
                "evidence_strength": "LOW",
                "confidence_status": "SUFFICIENT",
                "production_influence": False,
            },
        ],
        "confidence_summary": [
            {
                "gate_code": "GATE_A",
                "mean_interval_lower": Decimal("-5"),
                "mean_interval_upper": Decimal("-1"),
                "production_influence": False,
            },
            {
                "gate_code": "GATE_B",
                "mean_interval_lower": Decimal("1"),
                "mean_interval_upper": Decimal("4"),
                "production_influence": False,
            },
        ],
    }


def test_rendering_is_deterministic_and_gate_sorted() -> None:
    lines = render_gate_diagnostics(_report())

    assert lines[0] == "Governed Gate Diagnostics"
    assert lines[1].startswith("- GATE_A:")
    assert lines[2].startswith("- GATE_B:")
    assert render_gate_diagnostics(_report()) == lines


def test_rendering_exposes_governed_diagnostic_fields() -> None:
    lines = render_gate_diagnostics(_report())
    gate_a = lines[1]

    assert "recommendation=RETAIN" in gate_a
    assert "evidence=MODERATE" in gate_a
    assert "confidence=SUFFICIENT" in gate_a
    assert "economic=POSITIVE" in gate_a
    assert "statistical=NEGATIVE" in gate_a
    assert "net=8" in gate_a
    assert "mean_ci=[-5,-1]" in gate_a
    assert "reason=POSITIVE_NET_VALUE_AND_NEGATIVE_REJECTED_RETURN" in gate_a


def test_rendering_handles_empty_gate_population() -> None:
    assert render_gate_diagnostics({}) == (
        "Governed Gate Diagnostics",
        "No governed gate diagnostics available.",
    )


def test_rendering_uses_unavailable_for_missing_optional_fields() -> None:
    report = {
        "gate_recommendations": [
            {
                "gate_code": "GATE_A",
                "recommendation": "INSUFFICIENT_EVIDENCE",
                "reason_code": "NO_RESOLVED_OUTCOMES",
                "production_influence": False,
            }
        ]
    }

    line = render_gate_diagnostics(report)[1]

    assert "evidence=UNAVAILABLE" in line
    assert "confidence=UNAVAILABLE" in line
    assert "mean_ci=UNAVAILABLE" in line


def test_rendering_rejects_production_influence() -> None:
    report = _report()
    recommendations = report["gate_recommendations"]
    assert isinstance(recommendations, list)
    first = recommendations[0]
    assert isinstance(first, dict)
    first["production_influence"] = True

    with pytest.raises(ValueError, match="production_influence=false"):
        render_gate_diagnostics(report)


def test_rendering_rejects_duplicate_gate_codes() -> None:
    report = _report()
    recommendations = report["gate_recommendations"]
    assert isinstance(recommendations, list)
    recommendations.append(dict(recommendations[0]))

    with pytest.raises(ValueError, match="must be unique"):
        render_gate_diagnostics(report)
