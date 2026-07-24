from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.governed_approval_gate_forensics import (
    _CANDIDATE_FIELDS,
    _COMPARISON_FIELDS,
    _DEFICIENCY_FIELDS,
    _GATE_FIELDS,
    _PREVALENCE_FIELDS,
    _PROBE_FIELDS,
    B5_BLOCKED_DEFECT,
    B5_BLOCKED_DIVERGENCE,
    B5_BLOCKED_EVIDENCE,
    B5_BLOCKED_UNREACHED,
    B5_BLOCKED_VACUOUS,
    B5_READY,
    HTR010B5_CONTRACT_VERSION,
    RESEARCH_SCOPE,
    BenchmarkApprovalBundle,
    ForensicCandidate,
    _arm_comparison,
    _csv_value,
    _digest_mapping,
    _digest_sequence,
    _json_ready,
    _pipeline_component_hashes,
    _readiness,
    _reconcile_arm,
    _structural_probes,
    _validate_b4_handoff,
    _validate_bundle_lineage,
    _validate_frozen_pipeline_components,
    _validate_pair_lineage,
    _validate_ready_certificate_semantics,
    _validated_forensic_attestations,
    export_governed_approval_gate_forensics,
    validate_governed_approval_gate_forensics_certificate,
)
from alpha.decision_intelligence import RejectionReasonCode


def _base_report() -> dict[str, object]:
    return {
        "contract_version": HTR010B5_CONTRACT_VERSION,
        "b2_report_sha256": "1" * 64,
        "b2_report_file_sha256": "2" * 64,
        "b4_trade_formation_certificate_sha256": "3" * 64,
        "b4_trade_formation_certificate_file_sha256": "4" * 64,
        "raw_manifest_sha256": "5" * 64,
        "adjusted_manifest_sha256": "6" * 64,
        "identity_artifact_sha256": "7" * 64,
        "corporate_action_artifact_sha256": "8" * 64,
        "input_artifact_file_sha256s": {
            "b2_report": "2" * 64,
            "b4_certificate": "4" * 64,
            "raw_benchmark_manifest": "5" * 64,
            "adjusted_benchmark_manifest": "6" * 64,
            "identity_artifact": "7" * 64,
            "corporate_action_artifact": "8" * 64,
            "final_closure_report": "f" * 64,
            "admission_contract": "a" * 64,
            "identity_admission": "b" * 64,
            "raw_universe": "c" * 64,
            "adjusted_universe": "d" * 64,
        },
        "governed_store_lineage": {
            "identity_session_sha256": "9" * 64,
            "final_closure_report_sha256": "a" * 64,
            "admission_contract_sha256": "b" * 64,
            "governed_input_manifest_sha256": "c" * 64,
            "canonical_attestation_sha256s": ["d" * 64],
            "raw_forensic_canonical_attestation_sha256s": ["d" * 64],
            "adjusted_forensic_canonical_attestation_sha256s": ["d" * 64],
            "forensic_canonical_attestation_sha256s": ["d" * 64],
        },
        "frozen_pipeline_component_sha256s": {
            "feature_hash": "3" * 64,
            "candidate_generation_hash": "4" * 64,
            "setup_discovery_hash": "5" * 64,
            "feature_attribution_hash": "6" * 64,
            "approval_policy_hash": "7" * 64,
            "trade_plan_policy_hash": "8" * 64,
            "decision_engine_hash": "9" * 64,
        },
        "institutional_policy_source_sha256s": {
            "alpha/decision_intelligence/engine.py": "e" * 64,
            "alpha/decision_intelligence/stress.py": "f" * 64,
            "alpha/decision_intelligence/tradeplan.py": "0" * 64,
            "alpha/decision_intelligence/models.py": "1" * 64,
            "alpha/canonical_universe_audit/canonical_runner.py": "2" * 64,
        },
        "readiness_decision": B5_READY,
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
        "forensic_contract": {
            "policy_change_permitted": False,
            "threshold_change_permitted": False,
            "synthetic_probe_influences_replay": False,
            "empirical_gate_population_required_per_arm": 1,
            "all_base_gate_families_must_be_discriminating": True,
            "stress_rejection_path_must_be_discriminating": True,
            "trade_plan_rejection_path_must_be_discriminating": True,
            "all_institutional_stages_must_be_discriminating": True,
            "acceptance_path_must_be_reachable": True,
        },
        "raw_forensic_summary": {
            "approvable_candidate_count": 1,
            "institutional_approval_count": 0,
            "unexplained_terminal_gate_count": 0,
        },
        "adjusted_forensic_summary": {
            "approvable_candidate_count": 1,
            "institutional_approval_count": 0,
            "unexplained_terminal_gate_count": 0,
        },
        "raw_reconciliation_summary": {"parity_mismatch_count": 0},
        "adjusted_reconciliation_summary": {"parity_mismatch_count": 0},
        "structural_probe_summary": {
            "acceptance_path_reachable": True,
            "all_base_gate_families_discriminating": True,
            "stress_rejection_path_discriminating": True,
            "trade_plan_rejection_path_discriminating": True,
            "all_institutional_stages_discriminating": True,
            "deterministic": True,
        },
        "replay_start": "2020-01-01",
        "replay_end": "2020-01-02",
        "session_count": 2,
        "empirical_gate_reached": True,
        "approval_gate_trace_complete": True,
        "approval_gate_non_vacuous": True,
        "zero_approval_policy_consistent": True,
        "readiness_blockers": [],
        "implementation_defects": [],
        "implementation_defect_count": 0,
        "unexplained_arm_divergence_count": 0,
    }


def test_structural_probes_discriminate_every_institutional_stage() -> None:
    rows, summary, defects = _structural_probes()

    expected = {code.value for code in RejectionReasonCode}
    observed = {
        str(row["expected_gate_code"])
        for row in rows
        if row["probe_scope"] == "BASE_GATE_FAMILY"
    }
    assert defects == ()
    assert observed == expected
    assert summary["acceptance_path_reachable"] is True
    assert summary["all_base_gate_families_discriminating"] is True
    assert summary["stress_rejection_path_discriminating"] is True
    assert summary["trade_plan_rejection_path_discriminating"] is True
    assert summary["all_institutional_stages_discriminating"] is True
    assert summary["deterministic"] is True
    assert {row["probe_scope"] for row in rows} == {
        "FULL_PATH",
        "BASE_GATE_FAMILY",
        "STRESS_STAGE",
        "TRADE_PLAN_STAGE",
    }
    assert all(row["expectation_matched"] is True for row in rows)


def test_frozen_pipeline_components_match_signed_benchmark(
    tmp_path: Path,
) -> None:
    sources = {
        "alpha/analysis/core.py": "CORE = 1\n",
        "alpha/analysis/signals/signal.py": "SIGNAL = 1\n",
        "alpha/recommendation_intelligence/__init__.py": "\n",
        "alpha/recommendation_intelligence/engines.py": "ENGINE = 1\n",
        "alpha/application/intelligence_inputs.py": "INPUTS = 1\n",
        "alpha/canonical_universe_audit/canonical_runner.py": "RUNNER = 1\n",
        "alpha/setup_discovery/__init__.py": "\n",
        "alpha/feature_attribution_research/__init__.py": "\n",
        "alpha/decision_intelligence/engine.py": "GATE = 1\n",
        "alpha/decision_intelligence/stress.py": "STRESS = 1\n",
        "alpha/decision_intelligence/tradeplan.py": "PLAN = 1\n",
        "alpha/decision_intelligence/models.py": "MODELS = 1\n",
    }
    for relative, content in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    expected = _pipeline_component_hashes(tmp_path)
    manifest = {"versions": expected}

    assert (
        _validate_frozen_pipeline_components(
            project_root=tmp_path,
            raw_manifest=manifest,
            adjusted_manifest=manifest,
        )
        == expected
    )

    changed = tmp_path / "alpha/decision_intelligence/engine.py"
    changed.write_text("GATE = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="current pipeline differs"):
        _validate_frozen_pipeline_components(
            project_root=tmp_path,
            raw_manifest=manifest,
            adjusted_manifest=manifest,
        )


def test_ready_certificate_rejects_scalar_evidence_lists() -> None:
    report = _base_report()
    report["implementation_defects"] = "NONE"

    with pytest.raises(ValueError, match="implementation defects must be a list"):
        _validate_ready_certificate_semantics(report)


def test_one_sided_candidate_is_an_unexplained_arm_divergence() -> None:
    observed_on = date(2020, 1, 2)
    raw = (
        {
            "observed_on": observed_on,
            "symbol": "ALPHA",
            "final_signal": "BUY",
            "recommendation_score": 90,
            "input_fingerprint": "a" * 64,
            "terminal_gate": "WEAK_CONFIDENCE",
            "institutional_approved": False,
        },
    )

    rows, count = _arm_comparison(raw, ())

    assert count == 1
    assert rows[0]["raw_present"] is True
    assert rows[0]["adjusted_present"] is False
    assert rows[0]["unexplained_gate_divergence"] is True


def test_certificate_binds_every_supporting_artifact(tmp_path: Path) -> None:
    report = _base_report()
    paths = export_governed_approval_gate_forensics(
        report=report,
        candidate_rows=(),
        gate_rows=(),
        prevalence_rows=(),
        comparison_rows=(),
        probe_rows=(),
        deficiency_rows=(),
        output=tmp_path,
    )

    assert len(paths) == 8
    certificate = validate_governed_approval_gate_forensics_certificate(
        paths[0],
        require_ready=True,
    )
    assert certificate["report_sha256"] == report["report_sha256"]
    support = paths[1]
    support.write_text(support.read_text(encoding="utf-8") + "tampered\n")
    with pytest.raises(ValueError, match="supporting artifact digest mismatch"):
        validate_governed_approval_gate_forensics_certificate(paths[0])


def test_certificate_rejects_incomplete_support_artifact_set(
    tmp_path: Path,
) -> None:
    paths = export_governed_approval_gate_forensics(
        report=_base_report(),
        candidate_rows=(),
        gate_rows=(),
        prevalence_rows=(),
        comparison_rows=(),
        probe_rows=(),
        deficiency_rows=(),
        output=tmp_path,
    )
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    hashes = payload["artifact_hashes"]
    hashes.pop("htr010b5_gate_prevalence.csv")
    payload["report_sha256"] = _digest_mapping(payload)
    paths[0].write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="supporting artifact set mismatch"):
        validate_governed_approval_gate_forensics_certificate(paths[0])


def test_certificate_rejects_readiness_enablement_disagreement(
    tmp_path: Path,
) -> None:
    paths = export_governed_approval_gate_forensics(
        report=_base_report(),
        candidate_rows=(),
        gate_rows=(),
        prevalence_rows=(),
        comparison_rows=(),
        probe_rows=(),
        deficiency_rows=(),
        output=tmp_path,
    )
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["governed_approval_gate_research_enabled"] = False
    payload["report_sha256"] = _digest_mapping(payload)
    paths[0].write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="readiness and research enablement"):
        validate_governed_approval_gate_forensics_certificate(paths[0])


def test_certificate_rejects_input_lineage_disagreement(
    tmp_path: Path,
) -> None:
    paths = export_governed_approval_gate_forensics(
        report=_base_report(),
        candidate_rows=(),
        gate_rows=(),
        prevalence_rows=(),
        comparison_rows=(),
        probe_rows=(),
        deficiency_rows=(),
        output=tmp_path,
    )
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["input_artifact_file_sha256s"]["b2_report"] = "f" * 64
    payload["report_sha256"] = _digest_mapping(payload)
    paths[0].write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="input artifact lineage disagrees"):
        validate_governed_approval_gate_forensics_certificate(paths[0])


@pytest.mark.parametrize(
    ("lineage_updates", "message"),
    (
        (
            {
                "adjusted_forensic_canonical_attestation_sha256s": ["e" * 64],
            },
            "attestation union is inconsistent",
        ),
        (
            {
                "raw_forensic_canonical_attestation_sha256s": ["e" * 64],
                "adjusted_forensic_canonical_attestation_sha256s": ["e" * 64],
                "forensic_canonical_attestation_sha256s": ["e" * 64],
            },
            "outside B2 lineage",
        ),
    ),
)
def test_certificate_rejects_invalid_forensic_attestation_lineage(
    tmp_path: Path,
    lineage_updates: dict[str, object],
    message: str,
) -> None:
    report = _base_report()
    lineage = report["governed_store_lineage"]
    assert isinstance(lineage, dict)
    lineage.update(lineage_updates)
    paths = export_governed_approval_gate_forensics(
        report=report,
        candidate_rows=(),
        gate_rows=(),
        prevalence_rows=(),
        comparison_rows=(),
        probe_rows=(),
        deficiency_rows=(),
        output=tmp_path,
    )

    with pytest.raises(ValueError, match=message):
        validate_governed_approval_gate_forensics_certificate(paths[0])


@pytest.mark.parametrize(
    "fieldnames",
    (
        _CANDIDATE_FIELDS,
        _GATE_FIELDS,
        _PREVALENCE_FIELDS,
        _COMPARISON_FIELDS,
        _PROBE_FIELDS,
        _DEFICIENCY_FIELDS,
    ),
)
def test_csv_schemas_have_unique_columns(
    fieldnames: tuple[str, ...],
) -> None:
    assert len(fieldnames) == len(set(fieldnames))


def test_set_serialization_is_deterministic() -> None:
    assert _json_ready({"values": {"beta", "alpha"}}) == {"values": ["alpha", "beta"]}
    assert _csv_value(frozenset({"beta", "alpha"})) == "alpha|beta"


def test_benchmark_parity_mismatch_is_an_implementation_defect(
    tmp_path: Path,
) -> None:
    observed_on = date(2020, 1, 2)
    candidate = ForensicCandidate(
        price_view="RAW",
        observed_on=observed_on,
        symbol="ALPHA",
        rank=1,
        final_signal="BUY",
        approvable_signal=True,
        recommendation_score=Decimal("90"),
        adjusted_confidence="HIGH",
        setup_stage="ENTRY_READY",
        entry_ready=True,
        trigger_status="TRIGGER_CONFIRMED",
        execution_status="BUY NOW",
        allocation_eligible=True,
        evidence_strength="strong",
        evidence_sample_count=100,
        posterior_probability=Decimal("0.60"),
        expectancy=Decimal("0.20"),
        reward_risk_ratio=Decimal("3"),
        stop_distance_percent=Decimal("5"),
        data_completeness="COMPLETE",
        capacity_score=Decimal("90"),
        base_gate_decision="REJECT",
        base_failure_codes=("WEAK_CONFIDENCE",),
        stress_stage_reached=False,
        stress_failure_codes=(),
        stress_final_action="NOT_REACHED",
        trade_plan_stage_reached=False,
        trade_plan_quality_score=None,
        trade_plan_final_action="NOT_REACHED",
        terminal_stage="BASE_GATE",
        terminal_gate="WEAK_CONFIDENCE",
        institutional_approved=False,
        provisional_allocation_target_amount=Decimal("0"),
        portfolio_eligible=False,
        input_fingerprint="a" * 64,
    )
    bundle = BenchmarkApprovalBundle(
        root=tmp_path,
        manifest={},
        manifest_sha256="b" * 64,
        approval_rows=(
            {
                "observed_on": observed_on.isoformat(),
                "symbol": "ALPHA",
                "approved": "false",
                "opportunity_score": "89",
                "final_signal": "BUY",
                "primary_reason_code": "WEAK_CONFIDENCE",
            },
        ),
        candidate_rows=(
            {
                "observed_on": observed_on.isoformat(),
                "technical_candidates": "1",
                "buy_candidates": "1",
                "strong_buy_candidates": "0",
                "institutional_approvals": "0",
            },
        ),
    )

    rows, reconciliation = _reconcile_arm(
        (candidate,),
        bundle,
        {
            "candidate_count": 1,
            "approvable_signal_count": 1,
            "institutional_approval_count": 0,
        },
        price_view="RAW",
    )

    assert rows[0]["benchmark_parity"] is False
    assert reconciliation["parity_mismatch_count"] == 1
    assert reconciliation["defects"] == (
        "RAW_BENCHMARK_PARITY_MISMATCH@2020-01-02|ALPHA",
    )


def test_b4_zero_trade_handoff_is_semantically_bound() -> None:
    payload: dict[str, object] = {
        "contract_version": "HTR-010B4-v1.0.0",
        "readiness_decision": "BLOCKED_BY_ZERO_TRADE_POPULATION",
        "research_scope": "GOVERNED_TRADE_FORMATION_RESEARCH_ONLY",
        "economic_superiority_claimed": False,
        "zero_trade_policy_consistent": True,
        "trade_formation_certified": True,
        "funnel_metrics_evaluated": True,
        "economic_metrics_evaluated": False,
        "implementation_defect_count": 0,
        "implementation_defects": [],
        "unexplained_terminal_gate_count": 0,
        "unexplained_gate_divergence_count": 0,
        "unexplained_trade_divergence_count": 0,
        "readiness_blockers": ["ZERO_TRADE_POPULATION"],
        "raw_funnel_summary": {
            "trade_count": 0,
            "institutional_approval_count": 0,
        },
        "adjusted_funnel_summary": {
            "trade_count": 0,
            "institutional_approval_count": 0,
        },
        "governed_adjusted_trade_research_enabled": False,
    }

    _validate_b4_handoff(payload)
    payload["economic_metrics_evaluated"] = True
    with pytest.raises(ValueError, match="zero-trade economics"):
        _validate_b4_handoff(payload)


def test_benchmark_session_lineage_is_fail_closed() -> None:
    bundle = BenchmarkApprovalBundle(
        root=Path("."),
        manifest={
            "sessions": 2,
            "replay_start": "2020-01-01",
            "replay_end": "2020-01-02",
        },
        manifest_sha256="a" * 64,
        approval_rows=(
            {"observed_on": "2020-01-01", "symbol": "A", "approved": "false"},
            {"observed_on": "2020-01-02", "symbol": "B", "approved": "false"},
        ),
        candidate_rows=(
            {
                "observed_on": "2020-01-01",
                "technical_candidates": "1",
                "buy_candidates": "1",
                "strong_buy_candidates": "0",
                "institutional_approvals": "0",
            },
            {
                "observed_on": "2020-01-02",
                "technical_candidates": "1",
                "buy_candidates": "0",
                "strong_buy_candidates": "0",
                "institutional_approvals": "0",
            },
        ),
    )
    b2 = {
        "raw_summary": {
            "session_count": 2,
            "technical_candidate_count": 2,
            "institutional_approval_count": 0,
        }
    }
    b4 = {
        "session_count": 2,
        "replay_start": "2020-01-01",
        "replay_end": "2020-01-02",
        "raw_funnel_summary": {
            "candidate_count": 2,
            "approvable_signal_count": 1,
            "institutional_approval_count": 0,
        },
    }

    _validate_bundle_lineage(bundle, b2, b4, price_view="RAW")
    reversed_bundle = BenchmarkApprovalBundle(
        root=bundle.root,
        manifest=bundle.manifest,
        manifest_sha256=bundle.manifest_sha256,
        approval_rows=bundle.approval_rows,
        candidate_rows=tuple(reversed(bundle.candidate_rows)),
    )
    with pytest.raises(ValueError, match="not deterministic"):
        _validate_bundle_lineage(reversed_bundle, b2, b4, price_view="RAW")


def test_rebuilt_store_lineage_matches_b2_exactly() -> None:
    unobserved = ("ID-C",)
    pair = SimpleNamespace(
        identity_session_sha256="i" * 64,
        final_closure_report_sha256="f" * 64,
        admission_contract_sha256="a" * 64,
        governed_input_manifest_sha256="g" * 64,
        admitted_identity_count=3,
        observed_identity_count=2,
        unobserved_admitted_identity_ids=unobserved,
        raw=SimpleNamespace(canonical_attestation_sha256s=()),
        adjusted=SimpleNamespace(canonical_attestation_sha256s=()),
        canonical_attestation_sha256s=(),
    )
    b2 = {
        "comparison": {"parity": {"identity_session_sha256": "i" * 64}},
        "identity_coverage": {
            "admitted_identity_count": 3,
            "observed_identity_count": 2,
            "unobserved_admitted_identity_count": 1,
            "unobserved_admitted_identity_sha256": _digest_sequence(unobserved),
        },
        "final_closure_report_sha256": "f" * 64,
        "admission_contract_sha256": "a" * 64,
        "governed_input_manifest_sha256": "g" * 64,
        "canonical_attestation_sha256s": ["c" * 64],
        "canonical_attestation_count": 1,
    }

    expected = _validate_pair_lineage(pair, b2)
    pair.raw.canonical_attestation_sha256s = ("c" * 64,)
    pair.adjusted.canonical_attestation_sha256s = ("c" * 64,)
    pair.canonical_attestation_sha256s = ("c" * 64,)
    assert _validated_forensic_attestations(
        pair,
        expected_attestations=expected,
    ) == (("c" * 64,), ("c" * 64,), ("c" * 64,))

    pair.adjusted.canonical_attestation_sha256s = ("e" * 64,)
    pair.canonical_attestation_sha256s = ("c" * 64, "e" * 64)
    with pytest.raises(ValueError, match="outside the signed HTR-010B2 lineage"):
        _validated_forensic_attestations(
            pair,
            expected_attestations=expected,
        )

    pair.raw.canonical_attestation_sha256s = ()
    pair.adjusted.canonical_attestation_sha256s = ()
    pair.canonical_attestation_sha256s = ()
    pair.identity_session_sha256 = "x" * 64
    with pytest.raises(ValueError, match="identity-session lineage"):
        _validate_pair_lineage(pair, b2)


@pytest.mark.parametrize(
    ("kwargs", "decision"),
    [
        ({"defects": ("x",)}, B5_BLOCKED_DEFECT),
        ({"unexplained_divergences": 1}, B5_BLOCKED_DIVERGENCE),
        ({"empirical_gate_reached": False}, B5_BLOCKED_UNREACHED),
        ({"trace_complete": False}, B5_BLOCKED_EVIDENCE),
        ({"gate_non_vacuous": False}, B5_BLOCKED_VACUOUS),
        ({}, B5_READY),
    ],
)
def test_readiness_is_fail_closed(
    kwargs: dict[str, object],
    decision: str,
) -> None:
    inputs = {
        "defects": (),
        "unexplained_divergences": 0,
        "empirical_gate_reached": True,
        "trace_complete": True,
        "gate_non_vacuous": True,
    }
    inputs.update(kwargs)

    result, _ = _readiness(**inputs)  # type: ignore[arg-type]

    assert result == decision


def test_public_command_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])

    assert result.exit_code == 0
    assert "governed-approval-gate-forensics" in result.stdout
