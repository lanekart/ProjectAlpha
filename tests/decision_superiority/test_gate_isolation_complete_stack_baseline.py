from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import DemoIntelligenceInputBuilder
from alpha.decision_intelligence.engine import InstitutionalDecisionEngine
from alpha.decision_superiority.gate_isolation_complete_stack_baseline import (
    CompleteStackArtifactError,
    CompleteStackBaselineEngine,
    DSI002D1Readiness,
    export_complete_stack_result,
    validate_complete_stack_certificate,
)
from alpha.decision_superiority.gate_isolation_decision_baseline import (
    RecordedDecisionBaselineStore,
)
from alpha.decision_superiority.gate_isolation_stage_attribution import (
    DSI002DSourceContractError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
A_ROOT = PROJECT_ROOT / "artifacts/dsi002a_acceptance/20260725T225821Z"
B_ROOT = PROJECT_ROOT / "artifacts/dsi002b_acceptance/20260726T063400Z"
C_ROOT = PROJECT_ROOT / "artifacts/dsi002c_acceptance/20260726T064625Z"
D_ROOT = PROJECT_ROOT / "artifacts/dsi002d_acceptance/20260726T071750Z"
A_CERT = A_ROOT / "dsi002a_forward_capture_certificate.json"
B_CERT = B_ROOT / "dsi002b_frozen_policy_replay_certificate.json"
C_CERT = C_ROOT / "dsi002c_recorded_decision_parity_certificate.json"
D_CERT = D_ROOT / "dsi002d_stage_attribution_certificate.json"


@pytest.fixture(scope="module")
def complete_result():
    return CompleteStackBaselineEngine().run(
        dsi002a_certificate=A_CERT,
        dsi002b_certificate=B_CERT,
        dsi002c_certificate=C_CERT,
        dsi002d_certificate=D_CERT,
    )


def test_current_call_graph_discovers_exact_wiring_defect(complete_result) -> None:
    rows = {row["component"]: row for row in complete_result.current_call_graph}
    required_contract_fields = {
        "stage_order",
        "component",
        "instantiated",
        "invoked",
        "implementation",
        "input_contract",
        "output_contract",
        "output_recorded",
        "affects_terminal_status",
        "early_return_behavior",
        "exception_behavior",
        "dependency_injection_seam",
        "tests_exercise_component",
    }
    assert all(set(row) == required_contract_fields for row in rows.values())
    assert rows["frozen_input_assembler"]["instantiated"] is False
    assert rows["recommendation_creation"]["invoked"] is True
    assert rows["institutional_candidate_construction"]["invoked"] is False
    assert rows["institutional_base_decision"]["instantiated"] is False
    assert rows["institutional_stress"]["invoked"] is False
    assert rows["institutional_trade_plan_optimizer"]["invoked"] is False
    assert rows["portfolio_allocation"]["invoked"] is True


def test_wiring_defect_classification_is_explicit(complete_result) -> None:
    codes = {str(row["defect_code"]) for row in complete_result.defect_rows}
    assert codes == {
        "ALTERNATE_DECISION_PATH_USED",
        "EVALUATOR_NOT_INJECTED",
        "RECORDED_DECISION_BYPASSES_INSTITUTIONAL_STACK",
    }


def test_repaired_call_graph_uses_authoritative_evaluators(
    complete_result,
) -> None:
    rows = {str(row["component"]): row for row in complete_result.repaired_call_graph}
    assert rows["institutional_base_decision"]["implementation"] == (
        "InstitutionalDecisionEngine._decision"
    )
    assert rows["institutional_stress"]["implementation"] == (
        "DecisionStressTestEngine.stress_test"
    )
    assert rows["institutional_trade_plan_optimizer"]["implementation"] == (
        "TradePlanOptimizationEngine.optimize_decision"
    )
    assert all(row["invoked"] is True for row in rows.values())


def test_each_governed_stage_is_invoked_exactly_once(complete_result) -> None:
    rows = {str(row["stage_id"]): row for row in complete_result.invocation_rows}
    required = (
        "institutional_candidate_construction",
        "institutional_base_decision",
        "institutional_stress",
        "institutional_trade_plan_optimizer",
        "terminal_institutional_decision",
        "portfolio_allocation",
    )
    assert tuple(rows) == required
    assert all(row["invocation_count"] == 1 for row in rows.values())
    assert all(row["duplicate_invocation"] is False for row in rows.values())
    assert rows["institutional_base_decision"]["result"] == "REJECT"
    assert rows["institutional_stress"]["result"] == ("NOT_APPLICABLE_BASE_REJECTED")
    assert rows["institutional_trade_plan_optimizer"]["result"] == (
        "NOT_APPLICABLE_UPSTREAM_REJECTED"
    )


def test_authoritative_trace_propagates_terminal_state() -> None:
    recommendations = (
        IntelligenceApplicationService(input_provider=DemoIntelligenceInputBuilder())
        .run(observed_on=date(2026, 7, 26))
        .recommendations
    )
    selected = tuple(item for item in recommendations if item.symbol == "BEL")
    engine = InstitutionalDecisionEngine()
    traced = engine.evaluate_recommendations_with_trace(selected)
    ordinary = engine.evaluate_recommendations(selected)
    assert traced.report == ordinary
    assert len(traced.traces) == 1
    trace = traced.traces[0]
    assert trace.base_decision.gate_decision.value == "REJECT"
    assert trace.stress_decision == trace.base_decision
    assert trace.trade_plan_decision == trace.stress_decision
    assert traced.report.decisions == (trace.trade_plan_decision,)


def test_default_runtime_payload_remains_exact_old_baseline() -> None:
    baseline_path = C_ROOT / "baseline/dsi002c_recorded_decision_baseline.json"
    baseline = RecordedDecisionBaselineStore(baseline_path.parent).load(baseline_path)
    run = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=date(2026, 7, 26))
    payload_json = json.dumps(run.as_dict(), sort_keys=True, separators=(",", ":"))
    assert payload_json == baseline.output_payload_json
    assert "institutional" not in run.as_dict()


def test_governed_mode_adds_only_signed_institutional_enrichment() -> None:
    default = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=date(2026, 7, 26))
    governed = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder(),
        institutional_engine=InstitutionalDecisionEngine(),
        governed_institutional_evaluation_enabled=True,
        governed_institutional_symbols=frozenset({"BEL"}),
    ).run(observed_on=date(2026, 7, 26))
    enriched = governed.as_dict()
    institutional = enriched.pop("institutional")
    assert enriched == default.as_dict()
    assert isinstance(institutional, dict)
    assert institutional["execution_mode"] == "GOVERNED_COMPLETE_STACK"
    assert institutional["candidates_scanned"] == 1


def test_governed_mode_requires_explicit_engine_and_population() -> None:
    with pytest.raises(ValueError, match="requires an injected engine"):
        IntelligenceApplicationService(governed_institutional_evaluation_enabled=True)
    service = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder(),
        institutional_engine=InstitutionalDecisionEngine(),
        governed_institutional_evaluation_enabled=True,
        governed_institutional_symbols=frozenset({"MISSING"}),
    )
    with pytest.raises(ValueError, match="population is empty"):
        service.run(observed_on=date(2026, 7, 26))


def test_old_new_baseline_differences_are_explained(complete_result) -> None:
    rows = {str(row["field"]): row for row in complete_result.comparison_rows}
    assert rows["recommendation_and_allocation_payload"]["classification"] == (
        "NO_DIFFERENCE"
    )
    assert rows["terminal_institutional_state"]["classification"] == (
        "LEGITIMATE_COMPLETE_STACK_DECISION_DIFFERENCE"
    )
    assert rows["recorded_decision_payload"]["classification"] == (
        "EXPLAINED_SERIALISATION_ENRICHMENT"
    )
    assert complete_result.old_terminal_decision == "WATCHLIST"
    assert complete_result.new_terminal_decision == "REJECT"
    assert complete_result.allocation_decision == "SKIP"


def test_d1_is_ready_without_changing_default_runtime(complete_result) -> None:
    assert complete_result.readiness is DSI002D1Readiness.READY
    assert complete_result.blockers == ()
    assert complete_result.default_rows[0]["unchanged"] is True
    assert complete_result.default_rows[0]["institutional_key_present"] is False


def test_d2_observes_complete_institutional_stack(complete_result) -> None:
    rows = {str(row["stage_id"]): row for row in complete_result.d2_events}
    assert rows["institutional_base_decision"]["stage_invoked"] is True
    assert rows["institutional_stress"]["stage_invoked"] is True
    assert rows["institutional_trade_plan_optimizer"]["stage_invoked"] is True
    assert rows["terminal_institutional_decision"]["stage_invoked"] is True
    assert rows["institutional_stress"]["result_state"] == "NOT_APPLICABLE"
    assert rows["institutional_trade_plan_optimizer"]["result_state"] == (
        "NOT_APPLICABLE"
    )
    assert complete_result.d2_attribution[0]["attribution_complete"] is True


def test_frozen_inputs_recommendations_and_policy_are_not_mutated(
    complete_result,
) -> None:
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (A_CERT, B_CERT, C_CERT, D_CERT)
    }
    with pytest.raises(FrozenInstanceError):
        complete_result.readiness = DSI002D1Readiness.IMPLEMENTATION
    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (A_CERT, B_CERT, C_CERT, D_CERT)
    }
    assert before == after


def test_structural_probes_are_non_vacuous_and_isolated(complete_result) -> None:
    assert len(complete_result.probe_rows) == 17
    assert all(row["passed"] is True for row in complete_result.probe_rows)
    assert all(
        row["included_in_empirical_counts"] is False
        for row in complete_result.probe_rows
    )


def test_raw_adjusted_arms_remain_isolated(complete_result) -> None:
    row = complete_result.arm_rows[0]
    assert row["observed_arm"] == "RAW"
    assert row["paired_arm_available"] is False
    assert row["wiring_divergence"] == "NOT_COMPARABLE_SINGLE_SIGNED_ARM"
    assert row["unexplained_divergence"] is False


def test_renewed_certificates_are_ready_and_deterministic(
    complete_result,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_paths = export_complete_stack_result(complete_result, first)
    second_paths = export_complete_stack_result(complete_result, second)
    first_by_relative = {path.relative_to(first): path for path in first_paths}
    second_by_relative = {path.relative_to(second): path for path in second_paths}
    assert set(first_by_relative) == set(second_by_relative)
    for relative, first_path in first_by_relative.items():
        assert first_path.read_bytes() == second_by_relative[relative].read_bytes()
    certificates = (
        first / "dsi002d1_wiring_repair_certificate.json",
        first / "dsi002b2/dsi002b2_complete_evaluator_certificate.json",
        first / "dsi002c2/dsi002c2_complete_stack_baseline_certificate.json",
        first / "dsi002d2/dsi002d2_complete_stack_attribution_certificate.json",
    )
    payloads = tuple(
        validate_complete_stack_certificate(path, require_ready=True)
        for path in certificates
    )
    assert [payload["contract_version"] for payload in payloads] == [
        "DSI-002D1-v1.0.0",
        "DSI-002B2-v1.0.0",
        "DSI-002C2-v1.0.0",
        "DSI-002D2-v1.0.0",
    ]
    d2 = payloads[-1]
    assert d2["institutional_base_decision_stage_observed"] is True
    assert d2["institutional_stress_stage_observed"] is True
    assert d2["trade_plan_optimizer_stage_observed"] is True
    assert d2["terminal_institutional_stage_observed"] is True


def test_every_governance_flag_is_false(complete_result, tmp_path: Path) -> None:
    paths = export_complete_stack_result(complete_result, tmp_path)
    certificates = tuple(
        path for path in paths if path.suffix == ".json" and "certificate" in path.name
    )
    assert len(certificates) == 4
    for certificate in certificates:
        payload = json.loads(certificate.read_text(encoding="utf-8"))
        assert len(payload["governance_flags"]) == 21
        assert all(value is False for value in payload["governance_flags"].values())


def test_support_artifact_tamper_is_rejected(
    complete_result,
    tmp_path: Path,
) -> None:
    output = tmp_path / "bundle"
    export_complete_stack_result(complete_result, output)
    target = output / "dsi002d1_current_call_graph.csv"
    target.write_text(target.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
    with pytest.raises(CompleteStackArtifactError, match="tampered"):
        validate_complete_stack_certificate(
            output / "dsi002d1_wiring_repair_certificate.json"
        )


def test_missing_governance_flag_is_rejected(
    complete_result,
    tmp_path: Path,
) -> None:
    output = tmp_path / "bundle"
    export_complete_stack_result(complete_result, output)
    certificate = output / "dsi002d1_wiring_repair_certificate.json"
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    del payload["governance_flags"]["PRODUCTION_INFLUENCE"]
    certificate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CompleteStackArtifactError, match="governance flags"):
        validate_complete_stack_certificate(certificate)


def test_old_d_certificate_substitution_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "d"
    shutil.copytree(D_ROOT, root)
    certificate = root / D_CERT.name
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["captured_population_identity"] = "RAW|2026-07-26|OTHER|fingerprint"
    certificate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DSI002DSourceContractError, match="invalid historical"):
        CompleteStackBaselineEngine().run(
            dsi002a_certificate=A_CERT,
            dsi002b_certificate=B_CERT,
            dsi002c_certificate=C_CERT,
            dsi002d_certificate=certificate,
        )


def test_cli_generates_complete_ready_chain(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-complete-stack-baseline",
            "--dsi002a-certificate",
            str(A_CERT),
            "--dsi002b-certificate",
            str(B_CERT),
            "--dsi002c-certificate",
            str(C_CERT),
            "--dsi002d-certificate",
            str(D_CERT),
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "READY_FOR_COMPLETE_STACK_BASELINE_RENEWAL" in result.output
    assert "READY_FOR_GOVERNED_STAGE_ATTRIBUTION_RESEARCH" in result.output
    assert "institutional_base_decision=1" in result.output
    assert "DEFAULT_RUNTIME_BEHAVIOUR_CHANGED=false" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output
