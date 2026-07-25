from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.governed_setup_matched_evidence import (
    B7_BLOCKED_DIVERGENCE,
    B7_BLOCKED_EMPTY,
    B7_BLOCKED_PROVENANCE,
    B7_BLOCKED_SETUP,
    B7_READY,
    HTR010B7_CONTRACT_VERSION,
    RESEARCH_SCOPE,
    EvidenceSeed,
    _arm_comparison,
    _build_evidence_rows,
    _diagnostic_suspicions,
    _digest_mapping,
    _evidence_probes,
    _json_ready,
    _observed_causes,
    _outcome_status,
    _readiness,
    _sample_coverage_ratio,
    _sample_deficit,
    _subset_provenance_check,
    _validate_handoff,
    export_governed_setup_matched_evidence,
    validate_governed_setup_matched_evidence_certificate,
)
from alpha.canonical_universe_audit.models import (
    CandidateOutcomeRecord,
    CandidateRankingRecord,
    LiquidityBucket,
)


def _outcome(
    *,
    entered: bool = True,
    completed: bool = True,
    won: bool | None = True,
    exit_reason: str = "TARGET",
) -> CandidateOutcomeRecord:
    return CandidateOutcomeRecord(
        observed_on=date(2026, 1, 2),
        symbol="ALPHA",
        entered=entered,
        completed=completed,
        won=won,
        realized_return_pct=Decimal("2") if completed else None,
        realized_r=Decimal("1") if completed else None,
        holding_period_days=5 if completed else None,
        exit_reason=exit_reason,
        evidence_note="Governed deterministic test outcome.",
    )


def _ranking(*, setup_type: str = "VCP") -> CandidateRankingRecord:
    return CandidateRankingRecord(
        observed_on=date(2026, 1, 2),
        rank=1,
        symbol="ALPHA",
        final_signal="BUY",
        score=Decimal("90"),
        confidence="MEDIUM",
        sector="TEST",
        liquidity_bucket=LiquidityBucket.HIGH,
        expected_r=Decimal("3"),
        suggested_priority="RESEARCH_PRIORITY_HIGH",
        approval_candidate=True,
        institutional_approved=False,
        portfolio_eligible=False,
        setup_type=setup_type,
        setup_stage="ENTRY_READY",
        entry_price=Decimal("100"),
        initial_stop=Decimal("95"),
        target_1=Decimal("115"),
        expected_return=Decimal("15"),
        holding_period_days=20,
    )


def _candidate(
    *,
    price_view: str = "RAW",
    sample_count: str = "20",
    fingerprint: str = "a" * 64,
) -> dict[str, str]:
    return {
        "price_view": price_view,
        "observed_on": "2026-01-02",
        "symbol": "ALPHA",
        "rank": "1",
        "final_signal": "BUY",
        "setup_stage": "ENTRY_READY",
        "evidence_strength": "MODERATE",
        "evidence_sample_count": sample_count,
        "posterior_probability": "0.50",
        "expectancy": "0.05",
        "input_fingerprint": fingerprint,
    }


def _evidence_row(
    *,
    price_view: str,
    sample_count: int = 20,
    fingerprint: str = "a" * 64,
    setup_type: str = "VCP",
) -> dict[str, object]:
    return {
        "price_view": price_view,
        "observed_on": date(2026, 1, 2),
        "symbol": "ALPHA",
        "setup_type": setup_type,
        "evidence_sample_count": sample_count,
        "sample_deficit": 60 - sample_count,
        "forward_outcome_status": "COMPLETED_WIN",
        "observed_cause_codes": ("MATCHED_OUTCOME_DEFICIT",),
        "input_fingerprint": fingerprint,
    }


def _base_report() -> dict[str, object]:
    arm_summary = {
        "candidate_count": 1,
        "setup_type_count": 1,
        "known_sample_count": 1,
        "unknown_sample_count": 0,
        "zero_sample_count": 0,
        "below_requirement_count": 1,
        "requirement_satisfied_count": 0,
        "minimum_sample_count": 20,
        "median_sample_count": "20.00",
        "maximum_sample_count": 20,
        "average_sample_count": "20.00",
        "total_sample_deficit": 40,
        "forward_completed_count": 1,
        "forward_pending_count": 0,
        "forward_not_entered_count": 0,
        "forward_completion_rate": "100.00",
        "dominant_setup_type": "VCP",
        "dominant_observed_cause": "MATCHED_OUTCOME_DEFICIT",
        "evidence_provenance_complete": True,
    }
    return {
        "contract_version": HTR010B7_CONTRACT_VERSION,
        "b5_contract_version": "HTR-010B5-v1.0.0",
        "b5_report_sha256": "1" * 64,
        "b5_certificate_file_sha256": "2" * 64,
        "b6_contract_version": "HTR-010B6-v1.0.0",
        "b6_report_sha256": "3" * 64,
        "b6_certificate_file_sha256": "4" * 64,
        "b5_candidate_ledger_sha256": "5" * 64,
        "b5_gate_ledger_sha256": "6" * 64,
        "b6_frontier_ledger_sha256": "7" * 64,
        "b6_margin_ledger_sha256": "8" * 64,
        "input_artifact_file_sha256s": {
            "identity_artifact": "9" * 64,
            "corporate_action_artifact": "a" * 64,
            "final_closure_report": "b" * 64,
            "admission_contract": "c" * 64,
            "identity_admission": "d" * 64,
            "raw_universe": "e" * 64,
            "adjusted_universe": "f" * 64,
        },
        "replay_start": "2026-01-01",
        "replay_end": "2026-01-02",
        "session_count": 2,
        "required_matched_sample_count": 60,
        "minimum_approval_posterior": "0.52",
        "minimum_approval_expectancy": "0.10",
        "governed_store_lineage": {
            "identity_session_sha256": "1" * 64,
            "final_closure_report_sha256": "2" * 64,
            "admission_contract_sha256": "3" * 64,
            "b5_path_sensitive_input_manifest_sha256": "4" * 64,
            "rebuilt_path_sensitive_input_manifest_sha256": "5" * 64,
            "path_neutral_input_artifact_sha256": "6" * 64,
            "path_representation_neutral_lineage_validated": True,
        },
        "institutional_policy_source_sha256s": {
            "alpha/decision_intelligence/engine.py": "7" * 64,
        },
        "frozen_pipeline_component_sha256s": {
            "decision_engine_hash": "8" * 64,
        },
        "raw_evidence_summary": dict(arm_summary),
        "adjusted_evidence_summary": dict(arm_summary),
        "setup_cohort_summary": {
            "cohort_count": 2,
            "setup_type_count": 1,
            "rarity_suspicion_count": 2,
            "fragmentation_suspicion_count": 0,
            "causal_claim_permitted": False,
        },
        "outcome_coverage_summary": {
            "outcome_row_count": 2,
            "completed_count": 2,
            "pending_end_of_data_count": 0,
            "not_entered_count": 0,
            "incomplete_count": 0,
            "status_distribution": {"COMPLETED_WIN": 2},
        },
        "deficit_attribution_summary": {
            "certified_observation_type_count": 1,
            "diagnostic_suspicion_type_count": 1,
            "dominant_certified_observation": "MATCHED_OUTCOME_DEFICIT",
            "dominant_diagnostic_suspicion": "SETUP_RARITY_SUSPECTED",
            "diagnostic_suspicion_may_be_claimed_as_causality": False,
        },
        "probe_summary": {
            "probe_count": 6,
            "passed_probe_count": 6,
            "failed_probe_count": 0,
            "deterministic": True,
        },
        "setup_matched_population_nonempty": True,
        "setup_identity_complete": True,
        "evidence_provenance_complete": True,
        "setup_identity_defects": [],
        "setup_identity_defect_count": 0,
        "implementation_defects": [],
        "implementation_defect_count": 0,
        "unexplained_evidence_divergence_count": 0,
        "readiness_blockers": [],
        "readiness_decision": B7_READY,
        "governed_setup_matched_evidence_research_enabled": True,
        "governed_approval_constraint_research_enabled": True,
        "governed_approval_gate_research_enabled": True,
        "governed_adjusted_trade_research_enabled": False,
        "research_scope": RESEARCH_SCOPE,
        "threshold_change_permitted": False,
        "synthetic_outcomes_permitted": False,
        "outcome_backfill_mutation_enabled": False,
        "diagnostic_suspicion_may_be_claimed_as_causality": False,
        "economic_superiority_claimed": False,
        "live_scoring_enabled": False,
        "recommendation_influence": False,
        "portfolio_policy_influence": False,
        "execution_influence": False,
        "learning_mutation_enabled": False,
        "active_replay_integration": False,
        "production_influence": False,
    }


def test_sample_deficit_preserves_frozen_sixty_sample_rule() -> None:
    assert _sample_deficit(None, "INSUFFICIENT") == 60
    assert _sample_deficit(0, "MODERATE") == 60
    assert _sample_deficit(59, "MODERATE") == 1
    assert _sample_deficit(60, "MODERATE") == 0
    assert _sample_deficit(61, "MODERATE") == 0
    assert _sample_deficit(0, "STRONG") == 0


def test_sample_coverage_ratio_is_bounded_and_strong_override_is_governed() -> None:
    assert _sample_coverage_ratio(None, "MODERATE") == Decimal("0.0000")
    assert _sample_coverage_ratio(30, "MODERATE") == Decimal("0.5000")
    assert _sample_coverage_ratio(100, "MODERATE") == Decimal("1.0000")
    assert _sample_coverage_ratio(0, "STRONG") == Decimal("1.0000")


def test_observed_causes_keep_certified_facts_separate() -> None:
    causes = _observed_causes(
        sample_count=None,
        evidence_strength="",
        posterior=None,
        expectancy=None,
        outcome=_outcome(
            entered=False,
            completed=False,
            won=None,
            exit_reason="NO_ENTRY",
        ),
    )

    assert causes == (
        "SAMPLE_COUNT_UNAVAILABLE",
        "EVIDENCE_STRENGTH_UNAVAILABLE",
        "POSTERIOR_UNAVAILABLE",
        "EXPECTANCY_UNAVAILABLE",
        "ENTRY_NON_OCCURRENCE",
    )


def test_diagnostic_suspicion_is_not_causal_attribution() -> None:
    assert _diagnostic_suspicions(
        sample_count=20,
        evidence_strength="MODERATE",
        cohort_candidate_count=20,
    ) == ("SETUP_RARITY_SUSPECTED",)
    assert _diagnostic_suspicions(
        sample_count=20,
        evidence_strength="MODERATE",
        cohort_candidate_count=60,
    ) == ("MATCHING_FRAGMENTATION_SUSPECTED",)
    assert (
        _diagnostic_suspicions(
            sample_count=0,
            evidence_strength="STRONG",
            cohort_candidate_count=1,
        )
        == ()
    )


def test_outcome_status_preserves_pending_and_non_entry_states() -> None:
    pending = _outcome(
        entered=False,
        completed=False,
        won=None,
        exit_reason="PENDING_END_OF_DATA",
    )
    not_entered = _outcome(
        entered=False,
        completed=False,
        won=None,
        exit_reason="NO_ENTRY",
    )

    assert _outcome_status(pending) == "PENDING_END_OF_DATA"
    assert _outcome_status(not_entered) == "NOT_ENTERED"


def test_evidence_rows_bind_setup_sample_and_outcome_evidence() -> None:
    seed = EvidenceSeed(
        key=("RAW", date(2026, 1, 2), "ALPHA"),
        candidate=_candidate(),
        ranking=_ranking(),
        outcome=_outcome(
            entered=False,
            completed=False,
            won=None,
            exit_reason="PENDING_END_OF_DATA",
        ),
        insufficient_gate_failed=True,
        b6_sample_constraint_present=True,
        b6_sample_gap=Decimal("40"),
    )

    candidates, cohorts, outcomes = _build_evidence_rows((seed,))

    assert candidates[0]["setup_type"] == "VCP"
    assert candidates[0]["sample_deficit"] == 40
    assert candidates[0]["sample_coverage_ratio"] == Decimal("0.3333")
    assert candidates[0]["primary_observed_cause"] == "MATCHED_OUTCOME_DEFICIT"
    assert "END_OF_WINDOW_CENSORING" in candidates[0]["observed_cause_codes"]
    assert candidates[0]["diagnostic_suspicion_codes"] == ("SETUP_RARITY_SUSPECTED",)
    assert candidates[0]["evidence_provenance_complete"] is True
    assert cohorts[0]["setup_rarity_suspected"] is True
    assert outcomes[0]["end_of_window_censored"] is True


def test_unchanged_inputs_cannot_explain_changed_evidence_state() -> None:
    rows = (
        _evidence_row(price_view="RAW", sample_count=20),
        _evidence_row(price_view="ADJUSTED", sample_count=21),
    )

    comparison, count = _arm_comparison(rows)

    assert count == 1
    assert comparison[0]["sample_count_changed"] is True
    assert comparison[0]["input_changed"] is False
    assert comparison[0]["unexplained_evidence_divergence"] is True


def test_changed_inputs_can_explain_changed_evidence_state() -> None:
    rows = (
        _evidence_row(price_view="RAW", sample_count=20, fingerprint="a" * 64),
        _evidence_row(
            price_view="ADJUSTED",
            sample_count=21,
            fingerprint="b" * 64,
        ),
    )

    comparison, count = _arm_comparison(rows)

    assert count == 0
    assert comparison[0]["input_changed"] is True
    assert comparison[0]["explained_evidence_difference"] is True


def test_one_sided_evidence_population_is_unexplained() -> None:
    comparison, count = _arm_comparison((_evidence_row(price_view="RAW"),))

    assert count == 1
    assert comparison[0]["adjusted_present"] is False
    assert comparison[0]["unexplained_evidence_divergence"] is True


def test_evidence_boundary_probes_are_complete_and_deterministic() -> None:
    rows, summary, defects = _evidence_probes()

    assert defects == ()
    assert len(rows) == 6
    assert summary["passed_probe_count"] == 6
    assert summary["failed_probe_count"] == 0
    assert summary["deterministic"] is True
    assert all(row["expectation_matched"] is True for row in rows)


def test_subset_provenance_requires_signed_attestations() -> None:
    passed = _subset_provenance_check(
        "TEST",
        "ATTESTATION",
        ("a",),
        ("a", "b"),
        "subset",
    )
    failed = _subset_provenance_check(
        "TEST",
        "ATTESTATION",
        ("c",),
        ("a", "b"),
        "subset",
    )

    assert passed["passed"] is True
    assert failed["passed"] is False


@pytest.mark.parametrize(
    ("overrides", "expected"),
    (
        ({"implementation_defects": ("x",)}, B7_BLOCKED_SETUP),
        ({"setup_identity_complete": False}, B7_BLOCKED_SETUP),
        ({"unexplained_divergences": 1}, B7_BLOCKED_DIVERGENCE),
        ({"population_nonempty": False}, B7_BLOCKED_EMPTY),
        ({"evidence_provenance_complete": False}, B7_BLOCKED_PROVENANCE),
        ({}, B7_READY),
    ),
)
def test_readiness_is_fail_closed(
    overrides: dict[str, object],
    expected: str,
) -> None:
    inputs = {
        "population_nonempty": True,
        "setup_identity_complete": True,
        "evidence_provenance_complete": True,
        "implementation_defects": (),
        "unexplained_divergences": 0,
    }
    inputs.update(overrides)

    decision, _ = _readiness(**inputs)  # type: ignore[arg-type]

    assert decision == expected


def test_handoff_requires_b6_to_bind_supplied_b5_file(tmp_path: Path) -> None:
    b5_path = tmp_path / "b5.json"
    b5_path.write_text("{}\n", encoding="utf-8")
    b5_digest = hashlib.sha256(b5_path.read_bytes()).hexdigest()
    b5 = {
        "contract_version": "HTR-010B5-v1.0.0",
        "readiness_decision": "READY_FOR_GOVERNED_APPROVAL_GATE_RESEARCH",
        "production_influence": False,
        "governed_adjusted_trade_research_enabled": False,
        "report_sha256": "1" * 64,
    }
    b6 = {
        "contract_version": "HTR-010B6-v1.0.0",
        "readiness_decision": "READY_FOR_GOVERNED_APPROVAL_CONSTRAINT_RESEARCH",
        "production_influence": False,
        "governed_adjusted_trade_research_enabled": False,
        "b5_report_sha256": "1" * 64,
        "b5_certificate_file_sha256": b5_digest,
    }

    _validate_handoff(b5, b6, b5_certificate=b5_path)
    b6["b5_certificate_file_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="bind the supplied B5 certificate"):
        _validate_handoff(b5, b6, b5_certificate=b5_path)


def test_certificate_binds_every_supporting_artifact(tmp_path: Path) -> None:
    report = _base_report()
    paths = export_governed_setup_matched_evidence(
        report=report,
        candidate_rows=(),
        cohort_rows=(),
        outcome_rows=(),
        attribution_rows=(),
        fragmentation_rows=(),
        comparison_rows=(),
        provenance_rows=(),
        probe_rows=(),
        output=tmp_path,
    )

    assert len(paths) == 10
    certificate = validate_governed_setup_matched_evidence_certificate(
        paths[0],
        require_ready=True,
    )
    assert certificate["report_sha256"] == report["report_sha256"]
    support = paths[1]
    support.write_text(support.read_text(encoding="utf-8") + "tampered\n")
    with pytest.raises(ValueError, match="supporting artifact changed"):
        validate_governed_setup_matched_evidence_certificate(paths[0])


def test_certificate_rejects_threshold_mutation(tmp_path: Path) -> None:
    report = _base_report()
    paths = export_governed_setup_matched_evidence(
        report=report,
        candidate_rows=(),
        cohort_rows=(),
        outcome_rows=(),
        attribution_rows=(),
        fragmentation_rows=(),
        comparison_rows=(),
        provenance_rows=(),
        probe_rows=(),
        output=tmp_path,
    )
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["required_matched_sample_count"] = 59
    payload["report_sha256"] = _digest_mapping(payload)
    paths[0].write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sample threshold changed"):
        validate_governed_setup_matched_evidence_certificate(paths[0])


def test_certificate_rejects_diagnostic_causal_claim(tmp_path: Path) -> None:
    report = _base_report()
    paths = export_governed_setup_matched_evidence(
        report=report,
        candidate_rows=(),
        cohort_rows=(),
        outcome_rows=(),
        attribution_rows=(),
        fragmentation_rows=(),
        comparison_rows=(),
        provenance_rows=(),
        probe_rows=(),
        output=tmp_path,
    )
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["diagnostic_suspicion_may_be_claimed_as_causality"] = True
    payload["report_sha256"] = _digest_mapping(payload)
    paths[0].write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="governance flag must remain false"):
        validate_governed_setup_matched_evidence_certificate(paths[0])


def test_set_serialization_is_deterministic() -> None:
    assert _json_ready({"values": {"beta", "alpha"}}) == {"values": ["alpha", "beta"]}


def test_public_command_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])

    assert result.exit_code == 0
    assert "governed-setup-matched-evidence" in result.stdout
