from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.governed_adaptive_institutional_trade_shadow import (
    B10_BLOCKED_ARM,
    B10_BLOCKED_DEFAULT,
    B10_BLOCKED_DEFECT,
    B10_BLOCKED_EMPTY,
    B10_BLOCKED_INSTITUTIONAL,
    B10_BLOCKED_LEAKAGE,
    B10_BLOCKED_RECOMMENDATION,
    B10_BLOCKED_TRADE,
    B10_READY,
    HTR010B10_CONTRACT_VERSION,
    _arm_effect_comparison,
    _non_vacuity_probes,
    _readiness,
    export_governed_adaptive_institutional_trade_shadow,
    validate_governed_adaptive_institutional_trade_shadow_certificate,
)


def _report() -> dict[str, object]:
    return {
        "contract_version": HTR010B10_CONTRACT_VERSION,
        "b9_contract_version": "HTR-010B9-v1.0.0",
        "b9_report_sha256": "1" * 64,
        "b9_certificate_file_sha256": "2" * 64,
        "b8_contract_version": "HTR-010B8-v1.0.0",
        "b8_report_sha256": "3" * 64,
        "b8_certificate_file_sha256": "4" * 64,
        "b7_contract_version": "HTR-010B7-v1.0.0",
        "b7_report_sha256": "5" * 64,
        "b7_certificate_file_sha256": "6" * 64,
        "b7_candidate_ledger_sha256": "7" * 64,
        "input_artifact_file_sha256s": {},
        "source_contract_file_sha256s": {},
        "b9_source_contract_file_sha256s": {},
        "replay_start": "2026-01-01",
        "replay_end": "2026-07-20",
        "session_count": 126,
        "default_population_summary": {
            "raw_session_count": 126,
            "adjusted_session_count": 126,
            "raw_ledger_entry_count": 1,
            "adjusted_ledger_entry_count": 1,
            "raw_completed_outcome_count": 1,
            "adjusted_completed_outcome_count": 1,
        },
        "publication_summary": {
            "row_count": 2,
            "raw_row_count": 1,
            "adjusted_row_count": 1,
            "rows_with_prior_completed_evidence": 2,
            "maximum_sample_count": 60,
            "metadata_contract_defect_count": 0,
        },
        "institutional_effect_summary": {
            "candidate_count": 2,
            "default_approval_count": 0,
            "adaptive_approval_count": 0,
            "approval_change_count": 0,
            "decision_change_count": 2,
            "unexplained_divergence_count": 0,
        },
        "trade_formation_summary": {
            "default_trade_formation_count": 0,
            "adaptive_trade_formation_count": 0,
            "trade_formation_change_count": 0,
            "paired_trade_count": 0,
            "completed_outcome_count": 0,
            "unexplained_divergence_count": 0,
        },
        "point_in_time_summary": {
            "eligibility_row_count": 2,
            "eligible_count": 2,
            "leakage_count": 0,
            "strict_prior_entry_and_completion_required": True,
        },
        "arm_effect_summary": {
            "pair_count": 1,
            "unexplained_divergence_count": 0,
        },
        "default_path_summary": {
            "probe_count": 2,
            "drift_count": 0,
            "publisher_call_count": 0,
        },
        "probe_summary": {
            "probe_count": 6,
            "passed_probe_count": 6,
            "failed_probe_count": 0,
            "deterministic": True,
        },
        "adaptive_shadow_population_nonempty": True,
        "point_in_time_adaptive_leakage_count": 0,
        "recommendation_semantic_drift_count": 0,
        "unexplained_institutional_decision_divergence_count": 0,
        "unexplained_trade_formation_divergence_count": 0,
        "unexplained_adaptive_arm_divergence_count": 0,
        "default_path_drift_count": 0,
        "handoff_defects": [],
        "handoff_defect_count": 0,
        "implementation_defects": [],
        "implementation_defect_count": 0,
        "readiness_blockers": [],
        "readiness_decision": B10_READY,
        "default_runtime_adaptive_publication_enabled": False,
        "governed_shadow_adaptive_publication_enabled": True,
        "approval_policy_change_permitted": False,
        "evidence_threshold_change_permitted": False,
        "fingerprint_matching_change_permitted": False,
        "portfolio_policy_change_permitted": False,
        "execution_policy_change_permitted": False,
        "production_ledger_mutation_enabled": False,
        "synthetic_outcomes_permitted": False,
        "counterfactual_approval_claimed": False,
        "economic_superiority_claimed": False,
        "live_scoring_enabled": False,
        "recommendation_influence": False,
        "portfolio_policy_influence": False,
        "execution_influence": False,
        "learning_mutation_enabled": False,
        "active_replay_integration": False,
        "production_influence": False,
        "research_scope": (
            "GOVERNED_ADAPTIVE_INSTITUTIONAL_TRADE_SHADOW_RESEARCH_ONLY"
        ),
    }


def _empty_rows() -> tuple[dict[str, object], ...]:
    return ()


def test_readiness_precedence_is_fail_closed_and_zero_trades_can_be_ready() -> None:
    base = {
        "handoff_defects": (),
        "population_nonempty": True,
        "default_path_drift_count": 0,
        "leakage_count": 0,
        "recommendation_semantic_drift_count": 0,
        "unexplained_institutional_divergence_count": 0,
        "unexplained_trade_divergence_count": 0,
        "unexplained_arm_divergence_count": 0,
        "implementation_defects": (),
    }
    assert _readiness(**base) == (B10_READY, ())
    assert _readiness(**{**base, "population_nonempty": False})[0] == B10_BLOCKED_EMPTY
    assert _readiness(**{**base, "default_path_drift_count": 1})[0] == B10_BLOCKED_DEFAULT
    assert _readiness(**{**base, "leakage_count": 1})[0] == B10_BLOCKED_LEAKAGE
    assert _readiness(**{**base, "recommendation_semantic_drift_count": 1})[0] == B10_BLOCKED_RECOMMENDATION
    assert _readiness(**{**base, "unexplained_institutional_divergence_count": 1})[0] == B10_BLOCKED_INSTITUTIONAL
    assert _readiness(**{**base, "unexplained_trade_divergence_count": 1})[0] == B10_BLOCKED_TRADE
    assert _readiness(**{**base, "unexplained_arm_divergence_count": 1})[0] == B10_BLOCKED_ARM
    assert _readiness(**{**base, "implementation_defects": ("DEFECT",)})[0] == B10_BLOCKED_DEFECT


def test_raw_adjusted_effect_difference_requires_signed_input_difference() -> None:
    decision_rows = (
        {
            "price_view": "RAW",
            "observed_on": date(2026, 1, 2),
            "symbol": "TEST",
            "adaptive_metadata_changed": True,
            "adaptive_sample_count": 60,
            "approval_changed": True,
            "default_primary_gate": "INSUFFICIENT_EVIDENCE",
            "adaptive_primary_gate": "ACCEPTED",
            "decision_changed": True,
        },
        {
            "price_view": "ADJUSTED",
            "observed_on": date(2026, 1, 2),
            "symbol": "TEST",
            "adaptive_metadata_changed": True,
            "adaptive_sample_count": 59,
            "approval_changed": False,
            "default_primary_gate": "INSUFFICIENT_EVIDENCE",
            "adaptive_primary_gate": "INSUFFICIENT_EVIDENCE",
            "decision_changed": True,
        },
    )
    trade_rows = (
        {
            "price_view": "RAW",
            "observed_on": date(2026, 1, 2),
            "symbol": "TEST",
            "trade_formation_changed": True,
        },
        {
            "price_view": "ADJUSTED",
            "observed_on": date(2026, 1, 2),
            "symbol": "TEST",
            "trade_formation_changed": False,
        },
    )
    rows, divergences = _arm_effect_comparison(
        decision_rows=decision_rows,
        trade_rows=trade_rows,
        input_fingerprints={
            ("RAW", date(2026, 1, 2), "TEST"): "same",
            ("ADJUSTED", date(2026, 1, 2), "TEST"): "same",
        },
    )
    assert len(rows) == 1
    assert divergences == 1
    assert rows[0]["unexplained_adaptive_arm_divergence"] is True


def test_non_vacuity_probes_are_deterministic() -> None:
    rows, summary, defects = _non_vacuity_probes()
    assert rows
    assert summary["failed_probe_count"] == 0
    assert summary["deterministic"] is True
    assert defects == ()


def test_export_and_validator_bind_all_support_artifacts(tmp_path: Path) -> None:
    paths = export_governed_adaptive_institutional_trade_shadow(
        report=_report(),
        publication_rows=_empty_rows(),
        decision_rows=_empty_rows(),
        gate_rows=_empty_rows(),
        trade_rows=_empty_rows(),
        outcome_rows=_empty_rows(),
        eligibility_rows=_empty_rows(),
        arm_rows=_empty_rows(),
        default_rows=_empty_rows(),
        source_rows=_empty_rows(),
        probe_rows=_empty_rows(),
        output=tmp_path,
    )
    payload = validate_governed_adaptive_institutional_trade_shadow_certificate(
        paths[0],
        require_ready=True,
    )
    assert payload["readiness_decision"] == B10_READY
    assert len(paths) == 12


def test_certificate_support_tampering_fails_closed(tmp_path: Path) -> None:
    paths = export_governed_adaptive_institutional_trade_shadow(
        report=_report(),
        publication_rows=_empty_rows(),
        decision_rows=_empty_rows(),
        gate_rows=_empty_rows(),
        trade_rows=_empty_rows(),
        outcome_rows=_empty_rows(),
        eligibility_rows=_empty_rows(),
        arm_rows=_empty_rows(),
        default_rows=_empty_rows(),
        source_rows=_empty_rows(),
        probe_rows=_empty_rows(),
        output=tmp_path,
    )
    support = tmp_path / "htr010b10_default_path_invariance.csv"
    support.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        validate_governed_adaptive_institutional_trade_shadow_certificate(paths[0])


def test_certificate_digest_tampering_fails_closed(tmp_path: Path) -> None:
    certificate = export_governed_adaptive_institutional_trade_shadow(
        report=_report(),
        publication_rows=_empty_rows(),
        decision_rows=_empty_rows(),
        gate_rows=_empty_rows(),
        trade_rows=_empty_rows(),
        outcome_rows=_empty_rows(),
        eligibility_rows=_empty_rows(),
        arm_rows=_empty_rows(),
        default_rows=_empty_rows(),
        source_rows=_empty_rows(),
        probe_rows=_empty_rows(),
        output=tmp_path,
    )[0]
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["readiness_decision"] = B10_BLOCKED_DEFAULT
    certificate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        validate_governed_adaptive_institutional_trade_shadow_certificate(certificate)


def test_b10_cli_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])
    assert result.exit_code == 0
    assert "governed-adaptive-institutional-trade-shadow" in result.stdout
