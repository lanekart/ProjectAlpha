from __future__ import annotations

import csv
from pathlib import Path

from pytest import MonkeyPatch

from alpha.decision_superiority import gate_value_audit
from alpha.decision_superiority.gate_pipeline import (
    GatePipelineInput,
    GatePipelineResult,
    run_gate_pipeline,
)
from alpha.decision_superiority.gate_value_audit import GovernedGateValueAudit


def _write(
    path: Path,
    fields: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    candidates = tmp_path / "candidates.csv"
    gates = tmp_path / "gates.csv"
    outcomes = tmp_path / "outcomes.csv"

    _write(
        candidates,
        ("price_view", "observed_on", "symbol", "input_fingerprint"),
        [
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "UNIQUE_LOSS",
                "input_fingerprint": "a",
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-03",
                "symbol": "COBLOCKED_GAIN",
                "input_fingerprint": "b",
            },
        ],
    )
    _write(
        gates,
        (
            "price_view",
            "observed_on",
            "symbol",
            "stage",
            "gate_code",
            "gate_category",
            "gate_ordinal",
            "stage_reached",
            "outcome",
            "primary",
        ),
        [
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "UNIQUE_LOSS",
                "stage": "BASE",
                "gate_code": "GATE_A",
                "gate_category": "RISK",
                "gate_ordinal": 1,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": True,
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-03",
                "symbol": "COBLOCKED_GAIN",
                "stage": "BASE",
                "gate_code": "GATE_A",
                "gate_category": "RISK",
                "gate_ordinal": 1,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": True,
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-03",
                "symbol": "COBLOCKED_GAIN",
                "stage": "STRESS",
                "gate_code": "GATE_B",
                "gate_category": "QUALITY",
                "gate_ordinal": 2,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": False,
            },
        ],
    )
    _write(
        outcomes,
        (
            "price_view",
            "observed_on",
            "symbol",
            "completed",
            "won",
            "realized_return_pct",
            "realized_r",
        ),
        [
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "UNIQUE_LOSS",
                "completed": True,
                "won": False,
                "realized_return_pct": "-8",
                "realized_r": "-1",
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-03",
                "symbol": "COBLOCKED_GAIN",
                "completed": True,
                "won": True,
                "realized_return_pct": "12",
                "realized_r": "2",
            },
        ],
    )
    return candidates, gates, outcomes


def test_audit_routes_unique_gate_value_through_pipeline(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    candidates, gates, outcomes = _inputs(tmp_path)
    observed_inputs: list[GatePipelineInput] = []

    def recording_pipeline(
        pipeline_input: GatePipelineInput,
    ) -> GatePipelineResult:
        observed_inputs.append(pipeline_input)
        return run_gate_pipeline(pipeline_input)

    monkeypatch.setattr(gate_value_audit, "run_gate_pipeline", recording_pipeline)

    result = GovernedGateValueAudit().run(
        candidate_gate_forensics=candidates,
        gate_event_ledger=gates,
        outcome_coverage_ledger=outcomes,
        output=tmp_path / "out",
    )

    assert [row.gate_code for row in observed_inputs] == ["GATE_A", "GATE_B"]
    gate_a_input = observed_inputs[0]
    assert gate_a_input.sample_count == 1
    assert tuple(str(value) for value in gate_a_input.returns_pct) == ("-8",)
    assert gate_a_input.minimum_required == 0

    gate_b_input = observed_inputs[1]
    assert gate_b_input.sample_count == 0
    assert gate_b_input.returns_pct == ()
    assert gate_b_input.minimum_required == 0

    values = {row["gate_code"]: row for row in result.report["gate_value_summary"]}
    assert values["GATE_A"]["resolved_outcome_count"] == 2
    assert str(values["GATE_A"]["average_return_pct"]) == "2"
    assert str(values["GATE_A"]["avoided_loss_benefit"]) == "8"
    assert str(values["GATE_A"]["profitable_rejection_cost"]) == "0"
    assert str(values["GATE_A"]["net_gate_value"]) == "8"
    assert values["GATE_A"]["conclusion"] == "GATE_ADDS_MEASURABLE_VALUE"
    assert values["GATE_B"]["conclusion"] == "GATE_VALUE_INCONCLUSIVE"
    assert result.report["production_influence"] is False
