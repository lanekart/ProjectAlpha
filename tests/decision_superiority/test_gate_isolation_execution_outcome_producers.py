from __future__ import annotations

import json

import pytest

from alpha.decision_superiority.gate_isolation_execution_outcome_producers import (
    EXECUTION_STATE_PRODUCER_VERSION,
    OUTCOME_POLICY_PRODUCER_VERSION,
    ExecutionStateCaptureInput,
    ExecutionStateSnapshotProducer,
    OutcomePolicyCaptureInput,
    OutcomePolicySnapshotProducer,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputSection,
)


def _execution_input() -> ExecutionStateCaptureInput:
    return ExecutionStateCaptureInput(
        cash_state={"available_cash": "1000"},
        sizing_state={"max_position_weight": "0.05"},
        liquidity_constraints={"minimum_adv": "1000000"},
        participation_constraints={"maximum_participation": "0.10"},
        queue_state={"pending_orders": 0},
        risk_budget_state={"portfolio_heat": "0.25"},
        state_version="execution-v1",
        observed_on="2026-07-26",
    )


def _outcome_input() -> OutcomePolicyCaptureInput:
    return OutcomePolicyCaptureInput(
        exit_policy={"mode": "RULE_BASED"},
        stop_policy={"atr_multiple": "2"},
        target_policy={"reward_multiple": "3"},
        trailing_policy={"enabled": True},
        time_exit_policy={"maximum_sessions": 20},
        ambiguity_policy={"same_bar": "STOP_FIRST"},
        policy_version="outcome-v1",
        dependency_versions={"price_semantics": "v1"},
        observed_on="2026-07-26",
    )


def test_execution_state_producer_is_deterministic() -> None:
    first = ExecutionStateSnapshotProducer().produce(_execution_input())
    second = ExecutionStateSnapshotProducer().produce(_execution_input())

    assert first == second
    assert first.section is FrozenInputSection.EXECUTION_STATE
    assert first.source_version == EXECUTION_STATE_PRODUCER_VERSION
    payload = json.loads(first.payload_json)
    assert payload["queue_state"]["pending_orders"] == 0
    assert payload["state_version"] == "execution-v1"


def test_outcome_policy_has_no_formed_trade_claim() -> None:
    snapshot = OutcomePolicySnapshotProducer().produce(_outcome_input())

    assert snapshot.section is FrozenInputSection.OUTCOME_POLICY
    assert snapshot.source_version == OUTCOME_POLICY_PRODUCER_VERSION
    payload = json.loads(snapshot.payload_json)
    assert payload["formed_trade_identity"] is None
    assert payload["ambiguity_policy"]["same_bar"] == "STOP_FIRST"


def test_execution_state_requires_every_subsection() -> None:
    with pytest.raises(ValueError, match="queue_state cannot be empty"):
        ExecutionStateCaptureInput(
            cash_state={"available_cash": "1000"},
            sizing_state={"max_position_weight": "0.05"},
            liquidity_constraints={"minimum_adv": "1000000"},
            participation_constraints={"maximum_participation": "0.10"},
            queue_state={},
            risk_budget_state={"portfolio_heat": "0.25"},
            state_version="execution-v1",
            observed_on="2026-07-26",
        )


def test_outcome_policy_requires_dependency_versions() -> None:
    with pytest.raises(ValueError, match="dependency_versions cannot be empty"):
        OutcomePolicyCaptureInput(
            exit_policy={"mode": "RULE_BASED"},
            stop_policy={"atr_multiple": "2"},
            target_policy={"reward_multiple": "3"},
            trailing_policy={"enabled": True},
            time_exit_policy={"maximum_sessions": 20},
            ambiguity_policy={"same_bar": "STOP_FIRST"},
            policy_version="outcome-v1",
            dependency_versions={},
            observed_on="2026-07-26",
        )
