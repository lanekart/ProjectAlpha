from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import DemoIntelligenceInputBuilder
from alpha.decision_intelligence.engine import InstitutionalDecisionEngine
from alpha.decision_superiority.gate_isolation_shadow import (
    GateIsolationShadowEngine,
    _minimal_set_rows,
)
from alpha.decision_superiority.gate_isolation_shadow_artifacts import (
    GateIsolationShadowArtifactError,
    export_gate_isolation_shadow,
    validate_gate_isolation_shadow_certificate,
)
from alpha.decision_superiority.gate_isolation_shadow_models import (
    DSI002EReadiness,
    DSI002FReadiness,
    DSI002GReadiness,
    DSI002HReadiness,
    DSI002IReadiness,
    DSI002JReadiness,
    OverrideEligibility,
)
from alpha.decision_superiority.gate_isolation_shadow_statistics import (
    benjamini_hochberg,
    deterministic_bootstrap_interval,
    holm_adjustment,
    jaccard,
    wilson_interval,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT = PROJECT_ROOT / "artifacts/dsi002d1_acceptance/20260726T074552Z"
D1 = ROOT / "dsi002d1_wiring_repair_certificate.json"
B2 = ROOT / "dsi002b2/dsi002b2_complete_evaluator_certificate.json"
C2 = ROOT / "dsi002c2/dsi002c2_complete_stack_baseline_certificate.json"
D2 = ROOT / "dsi002d2/dsi002d2_complete_stack_attribution_certificate.json"


@pytest.fixture(scope="module")
def shadow_result():
    return _run()


def _run(*, maximum_search_subsets: int = 4096):
    return GateIsolationShadowEngine(maximum_search_subsets=maximum_search_subsets).run(
        dsi002d1_certificate=D1,
        dsi002b2_certificate=B2,
        dsi002c2_certificate=C2,
        dsi002d2_certificate=D2,
    )


def test_valid_renewed_source_chain_is_bound(shadow_result) -> None:
    assert [source.boundary for source in shadow_result.sources] == [
        "D1",
        "B2",
        "C2",
        "D2",
    ]
    assert len({source.candidate_identity for source in shadow_result.sources}) == 1
    assert len({source.snapshot_sha256 for source in shadow_result.sources}) == 1
    assert all(
        source.readiness.startswith("READY_") for source in shadow_result.sources
    )


def test_missing_source_certificate_fails_closed(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ValueError)):
        GateIsolationShadowEngine().run(
            dsi002d1_certificate=tmp_path / "missing.json",
            dsi002b2_certificate=B2,
            dsi002c2_certificate=C2,
            dsi002d2_certificate=D2,
        )


def test_substituted_source_certificate_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "c2"
    shutil.copytree(C2.parent, root)
    certificate = root / C2.name
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["candidate_identity"] = payload["candidate_identity"].replace("BEL", "TCS")
    certificate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        GateIsolationShadowEngine().run(
            dsi002d1_certificate=D1,
            dsi002b2_certificate=B2,
            dsi002c2_certificate=certificate,
            dsi002d2_certificate=D2,
        )


def test_observed_conditions_have_stable_unique_identity() -> None:
    run = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=date(2026, 7, 26))
    recommendation = next(item for item in run.recommendations if item.symbol == "BEL")
    engine = InstitutionalDecisionEngine()
    trace = engine.evaluate_recommendations_with_trace((recommendation,)).traces[0]
    first = engine.observed_gate_conditions(trace.candidate)
    second = engine.observed_gate_conditions(trace.candidate)
    assert first == second
    assert len(first) == 10
    assert len({condition.condition_id for condition in first}) == 10


def test_one_condition_pass_changes_only_observed_condition() -> None:
    run = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=date(2026, 7, 26))
    recommendation = next(item for item in run.recommendations if item.symbol == "BEL")
    engine = InstitutionalDecisionEngine()
    baseline = engine.evaluate_recommendations_with_trace((recommendation,)).traces[0]
    condition = engine.observed_gate_conditions(baseline.candidate)[0]
    shadow = engine.evaluate_candidate_with_condition_passes(
        baseline.candidate,
        passed_condition_ids=frozenset({condition.condition_id}),
    )
    assert shadow.candidate == baseline.candidate
    assert len(shadow.base_decision.rejection_reasons) == (
        len(baseline.base_decision.rejection_reasons) - 1
    )
    assert condition.reason not in shadow.base_decision.rejection_reasons
    assert shadow.base_invocation_count == 1
    assert shadow.stress_invocation_count == 1
    assert shadow.trade_plan_invocation_count == 1


def test_unobserved_condition_pass_is_rejected() -> None:
    run = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=date(2026, 7, 26))
    recommendation = next(item for item in run.recommendations if item.symbol == "BEL")
    engine = InstitutionalDecisionEngine()
    candidate = (
        engine.evaluate_recommendations_with_trace((recommendation,))
        .traces[0]
        .candidate
    )
    with pytest.raises(ValueError, match="unobserved institutional gate"):
        engine.evaluate_candidate_with_condition_passes(
            candidate,
            passed_condition_ids=frozenset({"INSTITUTIONAL_BASE.UNKNOWN.01"}),
        )


def test_e_classifies_exact_override_eligibility(shadow_result) -> None:
    rows = shadow_result.rows["eligibility"]
    eligible = tuple(
        row
        for row in rows
        if row["eligibility"] == OverrideEligibility.OVERRIDE_ELIGIBLE.value
    )
    ineligible = tuple(row for row in rows if row not in eligible)
    assert len(rows) == 10
    assert len(eligible) == 7
    assert len(ineligible) == 3
    assert all(
        row["eligibility"]
        == OverrideEligibility.MULTI_CONDITION_EVALUATOR_NOT_ISOLATABLE.value
        for row in ineligible
    )
    assert shadow_result.e_readiness is DSI002EReadiness.PARTIAL


def test_e_single_gate_arms_preserve_identity_and_are_deterministic(
    shadow_result,
) -> None:
    arms = shadow_result.rows["single_arms"]
    assert len(arms) == 7
    assert all(row["changed_condition_count"] == 1 for row in arms)
    assert all(row["changed_field_count"] == 1 for row in arms)
    assert all(row["pre_intervention_drift_count"] == 0 for row in arms)
    assert all(row["candidate_identity_unchanged"] is True for row in arms)
    assert all(row["deterministic"] is True for row in arms)
    assert all(row["terminal_institutional_result"] == "REJECT" for row in arms)


def test_e_stage_order_and_invocation_count_are_invariant(shadow_result) -> None:
    by_arm: dict[str, list[dict[str, object]]] = {}
    for row in shadow_result.rows["single_transitions"]:
        by_arm.setdefault(str(row["arm_id"]), []).append(row)
    assert len(by_arm) == 7
    for rows in by_arm.values():
        assert [row["stage_order"] for row in rows] == [1, 2, 3, 4]
        assert all(row["stage_invoked"] is True for row in rows)
        assert all(row["invocation_count"] == 1 for row in rows)


def test_f_exact_search_exhausts_all_subsets(shadow_result) -> None:
    rows = shadow_result.rows["search"]
    assert len(rows) == 128
    assert [row["tested_ordinal"] for row in rows] == list(range(1, 129))
    assert {row["cardinality"] for row in rows} == set(range(8))
    assert all(row["proof_status"] == "COMPLETE" for row in rows)
    assert all(row["target_reached"] is False for row in rows)
    assert shadow_result.f_readiness is DSI002FReadiness.PARTIAL


def test_f_no_sufficient_set_is_proven_not_inferred(shadow_result) -> None:
    assert shadow_result.rows["inclusion_minimal"] == (
        {
            "candidate_identity": shadow_result.candidate_identity,
            "set_id": "NONE",
            "condition_ids": "",
            "cardinality": "UNKNOWN",
            "solution_state": "NO_SUFFICIENT_SET_PROVEN",
            "proof_complete": True,
        },
    )
    assert (
        shadow_result.rows["minimum_cardinality"]
        == (shadow_result.rows["inclusion_minimal"])
    )


def test_f_minimality_distinguishes_inclusion_and_minimum() -> None:
    candidate = "RAW|2026-01-01|TEST|fingerprint"
    inclusion, minimum = _minimal_set_rows(
        candidate,
        (
            ("A",),
            ("B", "C"),
            ("A", "D"),
        ),
    )
    assert {row["condition_ids"] for row in inclusion} == {"A", "B|C"}
    assert {row["condition_ids"] for row in minimum} == {"A"}


def test_f_multiple_minimum_solutions_are_preserved() -> None:
    _, minimum = _minimal_set_rows(
        "RAW|2026-01-01|TEST|fingerprint",
        (("A", "B"), ("C", "D")),
    )
    assert {row["condition_ids"] for row in minimum} == {"A|B", "C|D"}


def test_f_search_limit_blocks_minimality_claim() -> None:
    result = _run(maximum_search_subsets=64)
    assert result.f_readiness is DSI002FReadiness.EXHAUSTED
    assert result.rows["search"][0]["proof_status"] == "SEARCH_SPACE_EXHAUSTED"
    assert result.g_readiness is DSI002GReadiness.F
    assert result.j_readiness is DSI002JReadiness.SLICE


def test_g_zero_approval_population_is_reconciled(shadow_result) -> None:
    assert shadow_result.g_readiness is DSI002GReadiness.ZERO_APPROVAL
    approvals = shadow_result.rows["approval_transitions"]
    funnel = shadow_result.rows["funnel"]
    assert len(approvals) == len(funnel) == 7
    assert all(row["transition"] == "STILL_REJECTED" for row in approvals)
    assert all(row["allocation_decision"] == "SKIP" for row in funnel)
    assert all(row["portfolio_eligible"] is False for row in funnel)
    assert all(row["entry_ready"] is False for row in funnel)
    assert all(row["trade_formed"] is False for row in funnel)


def test_h_never_attaches_baseline_outcome_to_unformed_shadow_trade(
    shadow_result,
) -> None:
    assert shadow_result.h_readiness is DSI002HReadiness.NO_OUTCOMES
    outcomes = shadow_result.rows["outcomes"]
    assert len(outcomes) == 7
    assert all(
        row["comparability"] == "COUNTERFACTUAL_PATH_UNOBSERVABLE" for row in outcomes
    )
    assert all(row["completed_outcome"] is False for row in outcomes)
    assert all(row["realized_return_pct"] == "UNKNOWN" for row in outcomes)
    assert all(
        row["net_gate_value_pct"] == "UNKNOWN"
        for row in shadow_result.rows["gate_value"]
    )


def test_i_uses_candidate_not_arm_as_analytic_unit(shadow_result) -> None:
    assert shadow_result.i_readiness is DSI002IReadiness.DESCRIPTIVE
    interval = shadow_result.rows["uncertainty"][0]
    assert interval["analysis_unit"] == "candidate"
    assert interval["sample_count"] == 1
    assert interval["confidence_grade"] == "INSUFFICIENT_SAMPLE"
    assert all(
        row["independent_observations"] is False
        for row in shadow_result.rows["dependence"]
    )
    assert shadow_result.rows["multiple_testing"][0]["hypothesis_count"] == 0


def test_wilson_interval_is_bounded_and_deterministic() -> None:
    assert wilson_interval(0, 1) == wilson_interval(0, 1)
    interval = wilson_interval(0, 1)
    assert interval is not None
    assert Decimal("0") <= interval[0] <= interval[1] <= Decimal("1")
    assert wilson_interval(0, 0) is None


def test_deterministic_bootstrap_and_invalid_empty_sample() -> None:
    values = (Decimal("-2"), Decimal("1"), Decimal("4"))
    first = deterministic_bootstrap_interval(
        values,
        package_identity="signed-package",
        statistic="mean",
        samples=200,
    )
    second = deterministic_bootstrap_interval(
        values,
        package_identity="signed-package",
        statistic="mean",
        samples=200,
    )
    assert first == second
    assert (
        deterministic_bootstrap_interval(
            (),
            package_identity="signed-package",
            statistic="mean",
        )
        is None
    )


def test_jaccard_and_multiple_testing_adjustments() -> None:
    assert jaccard(frozenset({"A"}), frozenset({"A", "B"})) == Decimal("0.500000")
    assert jaccard(frozenset(), frozenset()) is None
    values = (Decimal("0.01"), Decimal("0.04"), Decimal("0.20"))
    bh = benjamini_hochberg(values)
    holm = holm_adjustment(values)
    assert bh == (Decimal("0.030000"), Decimal("0.060000"), Decimal("0.200000"))
    assert holm == (Decimal("0.030000"), Decimal("0.080000"), Decimal("0.200000"))


def test_invalid_p_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        benjamini_hochberg((Decimal("1.1"),))
    with pytest.raises(ValueError, match="between zero and one"):
        holm_adjustment((Decimal("-0.1"),))


def test_j_reconciles_complete_limited_population(shadow_result) -> None:
    assert shadow_result.j_readiness is DSI002JReadiness.NO_OUTCOMES
    rows = {
        str(row["population_stage"]): row
        for row in shadow_result.rows["reconciliation"]
    }
    assert rows["renewed_c2_candidate"]["record_count"] == 1
    assert rows["failed_gate_conditions"]["record_count"] == 10
    assert rows["override_eligible_conditions"]["record_count"] == 7
    assert rows["single_gate_arms"]["record_count"] == 7
    assert rows["tested_remediation_subsets"]["record_count"] == 128
    assert rows["institutional_approvals"]["record_count"] == 0
    assert rows["trades_formed"]["record_count"] == 0
    assert all(row["silent_loss_count"] == 0 for row in rows.values())


def test_structural_probes_never_enter_empirical_counts(shadow_result) -> None:
    probes = shadow_result.rows["probes"]
    assert len(probes) == 48
    assert all(row["passed"] is True for row in probes)
    assert all(row["included_in_empirical_counts"] is False for row in probes)


def test_default_runtime_and_prerequisite_artifacts_remain_immutable(
    shadow_result,
) -> None:
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (D1, B2, C2, D2)
    }
    with pytest.raises(FrozenInstanceError):
        shadow_result.source_commit = "mutated"
    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (D1, B2, C2, D2)
    }
    assert before == after
    first = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=date(2026, 7, 26))
    second = IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=date(2026, 7, 26))
    assert first.as_dict() == second.as_dict()
    assert "institutional" not in first.as_dict()


def test_exports_are_byte_identical_and_all_certificates_validate(
    shadow_result,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_paths = export_gate_isolation_shadow(shadow_result, first)
    second_paths = export_gate_isolation_shadow(shadow_result, second)
    first_relative = {path.relative_to(first): path for path in first_paths}
    second_relative = {path.relative_to(second): path for path in second_paths}
    assert set(first_relative) == set(second_relative)
    assert len(first_paths) == 29
    for relative, path in first_relative.items():
        assert path.read_bytes() == second_relative[relative].read_bytes()
    certificates = tuple(
        path for path in first_paths if path.name.endswith("_certificate.json")
    )
    assert len(certificates) == 6
    payloads = tuple(
        validate_gate_isolation_shadow_certificate(path, require_ready=True)
        for path in certificates
    )
    assert all(
        str(payload["readiness_decision"]).startswith("READY_") for payload in payloads
    )


def test_all_governance_flags_are_present_and_false(
    shadow_result,
    tmp_path: Path,
) -> None:
    paths = export_gate_isolation_shadow(shadow_result, tmp_path)
    for path in paths:
        if not path.name.endswith("_certificate.json"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert len(payload["governance_flags"]) == 22
        assert all(value is False for value in payload["governance_flags"].values())


def test_support_artifact_tamper_is_rejected(
    shadow_result,
    tmp_path: Path,
) -> None:
    export_gate_isolation_shadow(shadow_result, tmp_path)
    target = tmp_path / "dsi002_single_gate_shadow_arms.csv"
    target.write_text(target.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
    with pytest.raises(GateIsolationShadowArtifactError, match="tampered"):
        validate_gate_isolation_shadow_certificate(
            tmp_path / "dsi002_gate_isolation_shadow_certificate.json"
        )


def test_unsafe_manifest_path_is_rejected(
    shadow_result,
    tmp_path: Path,
) -> None:
    export_gate_isolation_shadow(shadow_result, tmp_path)
    certificate = tmp_path / "dsi002e_single_gate_shadow_certificate.json"
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["support_artifact_manifest"]["../escape.csv"] = "0" * 64
    certificate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GateIsolationShadowArtifactError, match="unsafe"):
        validate_gate_isolation_shadow_certificate(certificate)


def test_cli_runs_and_verify_command_accepts_final_certificate(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-isolation-shadow",
            "--dsi002d1-certificate",
            str(D1),
            "--dsi002b2-certificate",
            str(B2),
            "--dsi002c2-certificate",
            str(C2),
            "--dsi002d2-certificate",
            str(D2),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "READY_WITH_PARTIAL_OVERRIDE_ELIGIBILITY" in result.output
    assert "READY_WITH_VALID_MECHANICS_AND_NO_COMPARABLE_OUTCOMES" in result.output
    assert "Observed/eligible conditions: 10/7" in result.output
    assert "Exact subsets tested: 128" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output
    verify = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-isolation-shadow-verify",
            "--certificate",
            str(output / "dsi002_gate_isolation_shadow_certificate.json"),
            "--require-ready",
        ],
    )
    assert verify.exit_code == 0, verify.output
    assert "Certificate: VALID" in verify.output
