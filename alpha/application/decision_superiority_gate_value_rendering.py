"""Human-readable diagnostic rendering for the governed DSI-001 CLI."""

from __future__ import annotations

from collections.abc import Mapping


def render_gate_diagnostics(report: Mapping[str, object]) -> tuple[str, ...]:
    """Render deterministic gate evidence, confidence, and recommendations."""

    recommendations = _rows_by_gate(report.get("gate_recommendations"))
    conclusions = _rows_by_gate(report.get("gate_conclusions"))
    evidence = _rows_by_gate(report.get("evidence_summary"))
    confidence = _rows_by_gate(report.get("confidence_summary"))

    gate_codes = sorted(
        set(recommendations) | set(conclusions) | set(evidence) | set(confidence)
    )
    lines = ["Governed Gate Diagnostics"]
    if not gate_codes:
        lines.append("No governed gate diagnostics available.")
        return tuple(lines)

    for gate_code in gate_codes:
        recommendation = recommendations.get(gate_code, {})
        conclusion = conclusions.get(gate_code, {})
        evidence_row = evidence.get(gate_code, {})
        confidence_row = confidence.get(gate_code, {})

        _require_diagnostic_only(
            gate_code,
            recommendation,
            conclusion,
            evidence_row,
            confidence_row,
        )

        lines.append(
            f"- {gate_code}: "
            f"recommendation={_value(recommendation, 'recommendation')}; "
            f"evidence={_value(evidence_row, 'evidence_strength')}; "
            f"confidence={_value(evidence_row, 'confidence_status')}; "
            f"economic={_value(conclusion, 'economic_direction')}; "
            f"statistical={_value(conclusion, 'statistical_direction')}; "
            f"net={_value(recommendation, 'net_gate_value')}; "
            f"mean_ci={_interval(confidence_row)}; "
            f"reason={_value(recommendation, 'reason_code')}"
        )

    return tuple(lines)


def _rows_by_gate(value: object) -> dict[str, Mapping[str, object]]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise ValueError("diagnostic report rows must be a list")

    rows: dict[str, Mapping[str, object]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("diagnostic report row must be a mapping")
        gate_code = str(item.get("gate_code", "")).strip()
        if not gate_code:
            raise ValueError("diagnostic report row requires gate_code")
        if gate_code in rows:
            raise ValueError("diagnostic report gate_code values must be unique")
        rows[gate_code] = item
    return rows


def _require_diagnostic_only(
    gate_code: str,
    *rows: Mapping[str, object],
) -> None:
    for row in rows:
        if row and row.get("production_influence") is not False:
            raise ValueError(
                f"gate {gate_code} diagnostic rendering requires "
                "production_influence=false"
            )


def _value(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if value is None or value == "":
        return "UNAVAILABLE"
    return str(value)


def _interval(row: Mapping[str, object]) -> str:
    lower = row.get("mean_interval_lower")
    upper = row.get("mean_interval_upper")
    if lower is None or lower == "" or upper is None or upper == "":
        return "UNAVAILABLE"
    return f"[{lower},{upper}]"


__all__ = ["render_gate_diagnostics"]
