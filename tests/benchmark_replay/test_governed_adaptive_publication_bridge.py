from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.governed_adaptive_publication_bridge import (
    B9_BLOCKED_ARM,
    B9_BLOCKED_DEFAULT,
    B9_BLOCKED_DEFECT,
    B9_BLOCKED_FINGERPRINT,
    B9_BLOCKED_LEAKAGE,
    B9_BLOCKED_ROUND_TRIP,
    B9_READY,
    HTR010B9_CONTRACT_VERSION,
    _arm_transport_comparison,
    _b8_transport_rows,
    _non_vacuity_probes,
    _readiness,
    export_governed_adaptive_publication_bridge,
    validate_governed_adaptive_publication_bridge_certificate,
)


def _report() -> dict[str, object]:
    return {
        "contract_version": HTR010B9_CONTRACT_VERSION,
        "b8_contract_version": "HTR-010B8-v1.0.0",
        "b8_report_sha256": "1" * 64,
        "b8_certificate_file_sha256": "2" * 64,
        "b8_shadow_assessment_sha256": "3" * 64,
        "b8_candidate_lineage_sha256": "4" * 64,
        "b8_arm_comparison_sha256": "5" * 64,
        "source_contract_file_sha256s": {},
        "b8_source_contract_file_sha256s": {},
        "round_trip_summary": {
            "row_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "metadata_key_count": 5,
            "publisher_probe_row_count": 0,
            "b8_transport_row_count": 0,
        },
        "default_path_summary": {
            "probe_count": 1,
            "drift_count": 0,
            "publisher_call_count": 0,
        },
        "recorder_parity_summary": {
            "recommendation_count": 1,
            "parity_count": 1,
            "defect_count": 0,
            "candle_pattern_recorded": True,
            "retracement_state_recorded": True,
        },
        "point_in_time_summary": {
            "eligibility_row_count": 1,
            "eligible_count": 1,
            "excluded_count": 0,
            "leakage_count": 0,
            "strict_prior_completion_required": True,
        },
        "arm_transport_summary": {
            "pair_count": 1,
            "unexplained_divergence_count": 0,
        },
        "probe_summary": {
            "probe_count": 1,
            "passed_probe_count": 1,
            "failed_probe_count": 0,
            "deterministic": True,
        },
        "round_trip_defect_count": 0,
        "fingerprint_recorder_parity_defect_count": 0,
        "default_path_drift_count": 0,
        "point_in_time_publication_leakage_count": 0,
        "implementation_defects": [],
        "implementation_defect_count": 0,
        "unexplained_publication_arm_divergence_count": 0,
        "readiness_blockers": [],
        "readiness_decision": B9_READY,
        "default_runtime_adaptive_publication_enabled": False,
        "governed_shadow_adaptive_publication_enabled": True,
        "approval_policy_change_permitted": False,
        "evidence_threshold_change_permitted": False,
        "fingerprint_matching_change_permitted": False,
        "production_ledger_backfill_enabled": False,
        "synthetic_outcomes_permitted": False,
        "counterfactual_approval_claimed": False,
        "governed_adjusted_trade_research_enabled": False,
        "economic_superiority_claimed": False,
        "live_scoring_enabled": False,
        "recommendation_influence": False,
        "portfolio_policy_influence": False,
        "execution_influence": False,
        "learning_mutation_enabled": False,
        "active_replay_integration": False,
        "production_influence": False,
        "research_scope": "GOVERNED_ADAPTIVE_PUBLICATION_SHADOW_REPLAY_ONLY",
    }


def _empty_rows() -> tuple[dict[str, object], ...]:
    return ()


def test_readiness_precedence_is_fail_closed() -> None:
    assert _readiness(
        round_trip_defect_count=0,
        recorder_parity_defect_count=0,
        default_path_drift_count=0,
        point_in_time_leakage_count=0,
        implementation_defects=(),
        unexplained_arm_divergence_count=0,
    ) == (B9_READY, ())
    assert _readiness(
        round_trip_defect_count=1,
        recorder_parity_defect_count=0,
        default_path_drift_count=0,
        point_in_time_leakage_count=0,
        implementation_defects=(),
        unexplained_arm_divergence_count=0,
    )[0] == B9_BLOCKED_ROUND_TRIP
    assert _readiness(
        round_trip_defect_count=0,
        recorder_parity_defect_count=1,
        default_path_drift_count=0,
        point_in_time_leakage_count=0,
        implementation_defects=(),
        unexplained_arm_divergence_count=0,
    )[0] == B9_BLOCKED_FINGERPRINT
    assert _readiness(
        round_trip_defect_count=0,
        recorder_parity_defect_count=0,
        default_path_drift_count=1,
        point_in_time_leakage_count=0,
        implementation_defects=(),
        unexplained_arm_divergence_count=0,
    )[0] == B9_BLOCKED_DEFAULT
    assert _readiness(
        round_trip_defect_count=0,
        recorder_parity_defect_count=0,
        default_path_drift_count=0,
        point_in_time_leakage_count=1,
        implementation_defects=(),
        unexplained_arm_divergence_count=0,
    )[0] == B9_BLOCKED_LEAKAGE
    assert _readiness(
        round_trip_defect_count=0,
        recorder_parity_defect_count=0,
        default_path_drift_count=0,
        point_in_time_leakage_count=0,
        implementation_defects=("DEFECT",),
        unexplained_arm_divergence_count=0,
    )[0] == B9_BLOCKED_DEFECT
    assert _readiness(
        round_trip_defect_count=0,
        recorder_parity_defect_count=0,
        default_path_drift_count=0,
        point_in_time_leakage_count=0,
        implementation_defects=(),
        unexplained_arm_divergence_count=1,
    )[0] == B9_BLOCKED_ARM


def test_signed_b8_shadow_transport_round_trips_all_five_fields() -> None:
    rows, defects = _b8_transport_rows(
        (
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "TEST",
                "adjusted_confidence": "HIGH",
                "evidence_strength": "strong",
                "posterior_win_probability": "0.7000",
                "expectancy": "0.25",
                "completed_sample_count": "60",
            },
        )
    )

    assert len(rows) == 5
    assert all(row["passed"] for row in rows)
    assert defects == ()


def test_raw_adjusted_transport_difference_blocks_parity() -> None:
    base = {
        "observed_on": "2026-01-02",
        "symbol": "TEST",
        "adjusted_confidence": "HIGH",
        "evidence_strength": "strong",
        "posterior_win_probability": "0.7000",
        "expectancy": "0.25",
        "completed_sample_count": "60",
    }
    rows, divergences = _arm_transport_comparison(
        (
            {"price_view": "RAW", **base},
            {"price_view": "ADJUSTED", **base, "completed_sample_count": "59"},
        )
    )

    assert len(rows) == 1
    assert divergences == 1
    assert rows[0]["explained"] is False


def test_non_vacuity_probes_are_deterministic() -> None:
    rows, summary, defects = _non_vacuity_probes()

    assert rows
    assert summary["failed_probe_count"] == 0
    assert summary["deterministic"] is True
    assert defects == ()


def test_export_and_validator_bind_all_support_artifacts(tmp_path: Path) -> None:
    paths = export_governed_adaptive_publication_bridge(
        report=_report(),
        round_trip_rows=_empty_rows(),
        default_rows=_empty_rows(),
        recorder_rows=_empty_rows(),
        eligibility_rows=_empty_rows(),
        arm_rows=_empty_rows(),
        source_rows=_empty_rows(),
        probe_rows=_empty_rows(),
        output=tmp_path,
    )

    certificate = paths[0]
    payload = validate_governed_adaptive_publication_bridge_certificate(
        certificate,
        require_ready=True,
    )

    assert payload["readiness_decision"] == B9_READY
    assert len(paths) == 9


def test_certificate_support_tampering_fails_closed(tmp_path: Path) -> None:
    paths = export_governed_adaptive_publication_bridge(
        report=_report(),
        round_trip_rows=_empty_rows(),
        default_rows=_empty_rows(),
        recorder_rows=_empty_rows(),
        eligibility_rows=_empty_rows(),
        arm_rows=_empty_rows(),
        source_rows=_empty_rows(),
        probe_rows=_empty_rows(),
        output=tmp_path,
    )
    support = tmp_path / "htr010b9_default_path_invariance.csv"
    support.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed"):
        validate_governed_adaptive_publication_bridge_certificate(paths[0])


def test_certificate_digest_tampering_fails_closed(tmp_path: Path) -> None:
    certificate = export_governed_adaptive_publication_bridge(
        report=_report(),
        round_trip_rows=_empty_rows(),
        default_rows=_empty_rows(),
        recorder_rows=_empty_rows(),
        eligibility_rows=_empty_rows(),
        arm_rows=_empty_rows(),
        source_rows=_empty_rows(),
        probe_rows=_empty_rows(),
        output=tmp_path,
    )[0]
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["readiness_decision"] = B9_BLOCKED_DEFAULT
    certificate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="digest"):
        validate_governed_adaptive_publication_bridge_certificate(certificate)


def test_b9_cli_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])

    assert result.exit_code == 0
    assert "governed-adaptive-publication-bridge" in result.stdout
