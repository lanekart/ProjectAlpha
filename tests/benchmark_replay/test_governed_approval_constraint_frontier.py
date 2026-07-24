from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.governed_approval_constraint_frontier import (
    _CONTRACT_SPECS,
    _NUMERIC_SPECS,
    B6_BLOCKED_DEFECT,
    B6_BLOCKED_DIVERGENCE,
    B6_BLOCKED_EMPTY,
    B6_BLOCKED_EVIDENCE,
    B6_READY,
    HTR010B6_CONTRACT_VERSION,
    RESEARCH_SCOPE,
    _arm_comparison,
    _build_frontier,
    _counterfactual_probes,
    _digest_mapping,
    _digest_sequence,
    _json_ready,
    _margin,
    _readiness,
    _threshold_rows,
    _validate_b5_handoff,
    export_governed_approval_constraint_frontier,
    validate_governed_approval_constraint_frontier_certificate,
)
from alpha.decision_intelligence import RejectionReasonCode, StressReasonCode


def _candidate(
    *,
    price_view: str = "RAW",
    fingerprint: str = "a" * 64,
    score: str = "80",
) -> dict[str, str]:
    return {
        "price_view": price_view,
        "observed_on": "2020-01-02",
        "symbol": "ALPHA",
        "rank": "1",
        "final_signal": "BUY",
        "approvable_signal": "true",
        "recommendation_score": score,
        "adjusted_confidence": "MEDIUM",
        "setup_stage": "ENTRY_READY",
        "entry_ready": "true",
        "trigger_status": "TRIGGER_CONFIRMED",
        "execution_status": "BUY NOW",
        "allocation_eligible": "true",
        "evidence_strength": "moderate",
        "evidence_sample_count": "20",
        "posterior_probability": "0.50",
        "expectancy": "0.05",
        "reward_risk_ratio": "1.5",
        "stop_distance_percent": "11",
        "data_completeness": "COMPLETE",
        "capacity_score": "40",
        "base_gate_decision": "REJECT",
        "base_failure_count": "1",
        "base_failure_codes": "WEAK_SETUP",
        "stress_stage_reached": "false",
        "stress_failure_count": "0",
        "stress_failure_codes": "",
        "stress_final_action": "NOT_REACHED",
        "trade_plan_stage_reached": "false",
        "trade_plan_quality_score": "",
        "trade_plan_final_action": "NOT_REACHED",
        "terminal_stage": "BASE_GATE",
        "terminal_gate": "WEAK_SETUP",
        "institutional_approved": "false",
        "provisional_allocation_target_amount": "0",
        "portfolio_eligible": "false",
        "input_fingerprint": fingerprint,
        "benchmark_present": "true",
        "benchmark_signal": "BUY",
        "benchmark_score": score,
        "benchmark_approved": "false",
        "benchmark_primary_reason": "WEAK_SETUP",
        "benchmark_parity": "true",
    }


def _event(
    *,
    price_view: str = "RAW",
    stage: str = "BASE_GATE",
    gate_code: str = "WEAK_SETUP",
    explanation: str = (
        "Final evidence score is below the stricter deployment threshold."
    ),
) -> dict[str, str]:
    return {
        "price_view": price_view,
        "observed_on": "2020-01-02",
        "symbol": "ALPHA",
        "final_signal": "BUY",
        "approvable_signal": "true",
        "stage": stage,
        "gate_code": gate_code,
        "gate_category": "SETUP",
        "gate_ordinal": "1",
        "stage_reached": "true",
        "outcome": "FAIL",
        "primary": "true",
        "severity": "",
        "suggested_action": "",
        "explanation": explanation,
    }


def _base_report() -> dict[str, object]:
    threshold_rows = _threshold_rows()
    summary = {
        "candidate_count": 1,
        "constraint_count": 1,
        "measurable_constraint_count": 1,
        "categorical_constraint_count": 0,
        "minimum_remediation_count": 1,
        "maximum_remediation_count": 1,
        "average_remediation_count": "1.00",
        "dominant_gate_code": "WEAK_SETUP",
        "nearest_frontier_symbol": "ALPHA",
        "nearest_frontier_date": "2020-01-02",
        "constraint_evidence_complete": True,
    }
    return {
        "contract_version": HTR010B6_CONTRACT_VERSION,
        "b5_contract_version": "HTR-010B5-v1.0.0",
        "b5_report_sha256": "1" * 64,
        "b5_certificate_file_sha256": "2" * 64,
        "b5_candidate_ledger_sha256": "3" * 64,
        "b5_gate_ledger_sha256": "4" * 64,
        "replay_start": "2020-01-01",
        "replay_end": "2020-01-02",
        "session_count": 2,
        "institutional_policy_source_sha256s": {
            "alpha/decision_intelligence/engine.py": "5" * 64,
        },
        "frozen_pipeline_component_sha256s": {
            "decision_engine_hash": "6" * 64,
        },
        "threshold_contract_sha256": _digest_sequence(threshold_rows),
        "threshold_contract_row_count": len(threshold_rows),
        "frontier_contract": {
            "policy_change_permitted": False,
            "threshold_change_permitted": False,
            "counterfactual_mutation_enabled": False,
            "counterfactual_approval_claimed": False,
            "minimal_remediation_requires_all_failed_constraints": True,
            "categorical_constraints_may_not_be_imputed_as_numeric": True,
            "source_price_arms_must_remain_distinct": True,
        },
        "raw_frontier_summary": dict(summary),
        "adjusted_frontier_summary": dict(summary),
        "bottleneck_summary": {"raw": [], "adjusted": []},
        "probe_summary": {
            "probe_count": len(_NUMERIC_SPECS),
            "passed_probe_count": len(_NUMERIC_SPECS),
            "failed_probe_count": 0,
            "deterministic": True,
        },
        "constraint_population_nonempty": True,
        "constraint_evidence_complete": True,
        "unexplained_constraint_divergence_count": 0,
        "implementation_defects": [],
        "implementation_defect_count": 0,
        "readiness_blockers": [],
        "readiness_decision": B6_READY,
        "governed_approval_constraint_research_enabled": True,
        "governed_approval_gate_research_enabled": True,
        "governed_adjusted_trade_research_enabled": False,
        "research_scope": RESEARCH_SCOPE,
        "economic_superiority_claimed": False,
        "live_scoring_enabled": False,
        "recommendation_influence": False,
        "portfolio_policy_influence": False,
        "execution_influence": False,
        "learning_mutation_enabled": False,
        "active_replay_integration": False,
        "production_influence": False,
    }


def test_threshold_contract_covers_every_frozen_gate_family() -> None:
    base = {item.gate_code for item in _CONTRACT_SPECS if item.stage == "BASE_GATE"}
    stress = {item.gate_code for item in _CONTRACT_SPECS if item.stage == "STRESS_TEST"}

    assert base == {item.value for item in RejectionReasonCode}
    assert stress == {item.value for item in StressReasonCode}
    assert any(item.stage == "TRADE_PLAN" for item in _CONTRACT_SPECS)
    assert all(item.remediation_class != "UNCLASSIFIED" for item in _CONTRACT_SPECS)


def test_numeric_margin_preserves_frozen_comparator_semantics() -> None:
    ge = next(item for item in _NUMERIC_SPECS if item.comparator == "GE")
    le = next(item for item in _NUMERIC_SPECS if item.comparator == "LE")
    assert ge.threshold is not None
    assert le.threshold is not None

    _, ge_gap, _ = _margin(ge, ge.threshold - Decimal("1"))
    _, ge_at_gap, _ = _margin(ge, ge.threshold)
    _, le_gap, _ = _margin(le, le.threshold + Decimal("1"))
    _, le_at_gap, _ = _margin(le, le.threshold)

    assert ge_gap == Decimal("1.000000")
    assert ge_at_gap == Decimal("0.000000")
    assert le_gap == Decimal("1.000000")
    assert le_at_gap == Decimal("0.000000")


def test_frontier_builds_minimal_policy_neutral_remediation_set() -> None:
    key = ("RAW", date(2020, 1, 2), "ALPHA")
    frontier, margins, remediations, defects = _build_frontier(
        {key: _candidate()},
        {key: (_event(),)},
    )

    assert defects == ()
    assert len(frontier) == 1
    assert frontier[0]["minimum_remediation_count"] == 1
    assert frontier[0]["constraint_evidence_complete"] is True
    assert len(margins) == 1
    assert margins[0]["constraint_id"] == "BASE.WEAK_SETUP.FINAL_SCORE"
    assert margins[0]["gap_to_clear"] == Decimal("5.000000")
    assert remediations[0]["policy_threshold_change_required"] is False
    assert remediations[0]["counterfactual_approval_claimed"] is False


def test_unknown_gate_is_fail_closed_as_an_implementation_defect() -> None:
    key = ("RAW", date(2020, 1, 2), "ALPHA")
    _, margins, _, defects = _build_frontier(
        {key: _candidate()},
        {key: (_event(gate_code="UNKNOWN_GATE"),)},
    )

    assert margins[0]["remediation_class"] == "UNCLASSIFIED"
    assert len(defects) == 1
    assert "UNCLASSIFIED_CONSTRAINT" in defects[0]


def test_one_sided_frontier_is_an_unexplained_divergence() -> None:
    key = ("RAW", date(2020, 1, 2), "ALPHA")
    frontier, margins, _, defects = _build_frontier(
        {key: _candidate()},
        {key: (_event(),)},
    )
    assert defects == ()

    rows, count = _arm_comparison(frontier, margins)

    assert count == 1
    assert rows[0]["raw_present"] is True
    assert rows[0]["adjusted_present"] is False
    assert rows[0]["unexplained_constraint_divergence"] is True


def test_boundary_probes_cover_every_numeric_constraint() -> None:
    rows, summary, defects = _counterfactual_probes()

    assert defects == ()
    assert len(rows) == len(_NUMERIC_SPECS)
    assert summary["failed_probe_count"] == 0
    assert summary["deterministic"] is True
    assert all(row["expectation_matched"] is True for row in rows)


def test_certificate_binds_every_supporting_artifact(tmp_path: Path) -> None:
    report = _base_report()
    paths = export_governed_approval_constraint_frontier(
        report=report,
        frontier_rows=(),
        margin_rows=(),
        prevalence_rows=(),
        remediation_rows=(),
        comparison_rows=(),
        threshold_rows=_threshold_rows(),
        probe_rows=(),
        output=tmp_path,
    )

    assert len(paths) == 9
    certificate = validate_governed_approval_constraint_frontier_certificate(
        paths[0],
        require_ready=True,
    )
    assert certificate["report_sha256"] == report["report_sha256"]
    support = paths[1]
    support.write_text(support.read_text(encoding="utf-8") + "tampered\n")
    with pytest.raises(ValueError, match="supporting artifact digest mismatch"):
        validate_governed_approval_constraint_frontier_certificate(paths[0])


def test_certificate_rejects_threshold_change_permission(tmp_path: Path) -> None:
    report = _base_report()
    paths = export_governed_approval_constraint_frontier(
        report=report,
        frontier_rows=(),
        margin_rows=(),
        prevalence_rows=(),
        remediation_rows=(),
        comparison_rows=(),
        threshold_rows=_threshold_rows(),
        probe_rows=(),
        output=tmp_path,
    )
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["frontier_contract"]["threshold_change_permitted"] = True
    payload["report_sha256"] = _digest_mapping(payload)
    paths[0].write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="frontier contract is invalid"):
        validate_governed_approval_constraint_frontier_certificate(paths[0])


@pytest.mark.parametrize(
    ("kwargs", "decision"),
    (
        ({"defects": ("x",)}, B6_BLOCKED_DEFECT),
        ({"unexplained_divergences": 1}, B6_BLOCKED_DIVERGENCE),
        ({"population_nonempty": False}, B6_BLOCKED_EMPTY),
        ({"evidence_complete": False}, B6_BLOCKED_EVIDENCE),
        ({}, B6_READY),
    ),
)
def test_readiness_is_fail_closed(
    kwargs: dict[str, object],
    decision: str,
) -> None:
    inputs = {
        "defects": (),
        "unexplained_divergences": 0,
        "population_nonempty": True,
        "evidence_complete": True,
    }
    inputs.update(kwargs)

    result, _ = _readiness(**inputs)  # type: ignore[arg-type]

    assert result == decision


def test_b5_handoff_requires_signed_ready_zero_approval_state() -> None:
    payload: dict[str, object] = {
        "contract_version": "HTR-010B5-v1.0.0",
        "readiness_decision": "READY_FOR_GOVERNED_APPROVAL_GATE_RESEARCH",
        "governed_approval_gate_research_enabled": True,
        "empirical_gate_reached": True,
        "approval_gate_trace_complete": True,
        "approval_gate_non_vacuous": True,
        "zero_approval_policy_consistent": True,
        "implementation_defect_count": 0,
        "unexplained_arm_divergence_count": 0,
        "governed_adjusted_trade_research_enabled": False,
        "production_influence": False,
    }

    _validate_b5_handoff(payload)
    payload["zero_approval_policy_consistent"] = False
    with pytest.raises(ValueError, match="zero_approval_policy_consistent"):
        _validate_b5_handoff(payload)


def test_set_serialization_is_deterministic() -> None:
    assert _json_ready({"values": {"beta", "alpha"}}) == {"values": ["alpha", "beta"]}


def test_public_command_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])

    assert result.exit_code == 0
    assert "governed-approval-constraint-frontier" in result.stdout
