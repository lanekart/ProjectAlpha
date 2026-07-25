from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.decision_superiority import gate_value_audit
from alpha.decision_superiority.gate_pipeline import (
    GatePipelineInput,
    run_gate_pipeline,
)
from alpha.decision_superiority.gate_value_audit import (
    GateAccumulator,
    GateAuditState,
    GovernedGateValueAudit,
)


def _accumulator(
    *,
    unique: int,
    unique_returns: list[Decimal],
    resolved: int | None = None,
) -> GateAccumulator:
    return GateAccumulator(
        blocked=unique,
        unique=unique,
        resolved=len(unique_returns) if resolved is None else resolved,
        positive=sum(value > 0 for value in unique_returns),
        negative=sum(value < 0 for value in unique_returns),
        flat=sum(value == 0 for value in unique_returns),
        return_sum=sum(unique_returns, Decimal("0")),
        unique_returns=unique_returns,
    )


def test_gate_states_builds_one_canonical_pipeline_result_per_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[GatePipelineInput] = []

    def recording_pipeline(pipeline_input: GatePipelineInput):
        observed.append(pipeline_input)
        return run_gate_pipeline(pipeline_input)

    monkeypatch.setattr(gate_value_audit, "run_gate_pipeline", recording_pipeline)
    states = GovernedGateValueAudit._gate_states(
        {
            "GATE_B": _accumulator(
                unique=1,
                unique_returns=[Decimal("2")],
            ),
            "GATE_A": _accumulator(
                unique=2,
                unique_returns=[Decimal("-3"), Decimal("-1")],
            ),
        }
    )

    assert list(states) == ["GATE_A", "GATE_B"]
    assert [row.gate_code for row in observed] == ["GATE_A", "GATE_B"]
    assert states["GATE_A"].pipeline.gate_code == "GATE_A"
    assert states["GATE_A"].pipeline.economic_value.net_gate_value == Decimal("4")


def test_value_rows_consumes_existing_pipeline_result_without_reexecution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = GovernedGateValueAudit._gate_states(
        {
            "GATE_A": _accumulator(
                unique=1,
                unique_returns=[Decimal("-8")],
            )
        }
    )

    def fail_if_called(pipeline_input: GatePipelineInput):
        raise AssertionError(f"pipeline unexpectedly re-executed: {pipeline_input}")

    monkeypatch.setattr(gate_value_audit, "run_gate_pipeline", fail_if_called)
    rows = GovernedGateValueAudit._value_rows(states)

    assert len(rows) == 1
    assert rows[0]["gate_code"] == "GATE_A"
    assert rows[0]["avoided_loss_benefit"] == Decimal("8")
    assert rows[0]["net_gate_value"] == Decimal("8")


def test_gate_audit_state_rejects_sample_count_mismatch() -> None:
    accumulator = _accumulator(
        unique=2,
        unique_returns=[Decimal("-1")],
    )
    pipeline = run_gate_pipeline(
        GatePipelineInput(
            gate_code="GATE_A",
            sample_count=1,
            returns_pct=(Decimal("-1"),),
            minimum_required=0,
        )
    )

    with pytest.raises(ValueError, match="sample_count"):
        GateAuditState(
            accumulator=accumulator,
            pipeline=pipeline,
        )


def test_gate_audit_state_rejects_resolved_count_mismatch() -> None:
    accumulator = _accumulator(
        unique=2,
        unique_returns=[Decimal("-1")],
        resolved=2,
    )
    pipeline = run_gate_pipeline(
        GatePipelineInput(
            gate_code="GATE_A",
            sample_count=2,
            returns_pct=(),
            minimum_required=0,
        )
    )

    with pytest.raises(ValueError, match="resolved_count"):
        GateAuditState(
            accumulator=accumulator,
            pipeline=pipeline,
        )
