from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.governed_adaptive_evidence_lineage import (
    _ADAPTIVE_METADATA_CONTRACT,
    _SOURCE_CONTRACT_PATHS,
    B8_BLOCKED_ARM,
    B8_BLOCKED_DEFECT,
    B8_BLOCKED_EMPTY,
    B8_BLOCKED_FINGERPRINT,
    B8_BLOCKED_LEAKAGE,
    B8_BLOCKED_PUBLICATION,
    B8_READY,
    HTR010B8_CONTRACT_VERSION,
    _adaptive_assessment,
    _candidate_records,
    _evidence_source_separation,
    _fingerprint_contract_probes,
    _non_vacuity_probes,
    _outcome_eligibility,
    _probe_fingerprint,
    _publication_source_contract,
    _readiness,
    export_governed_adaptive_evidence_lineage,
    validate_governed_adaptive_evidence_lineage_certificate,
)
from alpha.learning_intelligence import LearningOutcomeSample


def test_contract_and_readiness_states_are_stable() -> None:
    assert HTR010B8_CONTRACT_VERSION == "HTR-010B8-v1.0.0"
    assert B8_READY == "READY_FOR_GOVERNED_ADAPTIVE_EVIDENCE_LINEAGE_RESEARCH"
    assert {
        B8_BLOCKED_EMPTY,
        B8_BLOCKED_FINGERPRINT,
        B8_BLOCKED_PUBLICATION,
        B8_BLOCKED_LEAKAGE,
        B8_BLOCKED_DEFECT,
        B8_BLOCKED_ARM,
    } == {
        "BLOCKED_BY_EMPTY_POINT_IN_TIME_ADAPTIVE_POPULATION",
        "BLOCKED_BY_FINGERPRINT_CONTRACT_MISMATCH",
        "BLOCKED_BY_UNEXPLAINED_ADAPTIVE_EVIDENCE_PUBLICATION_GAP",
        "BLOCKED_BY_POINT_IN_TIME_EVIDENCE_LEAKAGE",
        "BLOCKED_BY_ADAPTIVE_EVIDENCE_IMPLEMENTATION_DEFECT",
        "BLOCKED_BY_UNEXPLAINED_ADAPTIVE_ARM_DIVERGENCE",
    }


@pytest.mark.parametrize(
    ("status", "completion", "fingerprint_match", "same_arm", "expected"),
    (
        ("COMPLETED_WIN", date(2026, 1, 9), True, True, True),
        ("COMPLETED_WIN", date(2026, 1, 10), True, True, False),
        ("COMPLETED_WIN", date(2026, 1, 11), True, True, False),
        ("PENDING_END_OF_DATA", None, True, True, False),
        ("COMPLETED_WIN", date(2026, 1, 9), False, True, False),
        ("COMPLETED_WIN", date(2026, 1, 9), True, False, False),
    ),
)
def test_point_in_time_eligibility_is_strict(
    status: str,
    completion: date | None,
    fingerprint_match: bool,
    same_arm: bool,
    expected: bool,
) -> None:
    observed, _ = _outcome_eligibility(
        candidate_date=date(2026, 1, 10),
        outcome_status=status,
        inferred_completion_date=completion,
        fingerprint_match=fingerprint_match,
        same_price_arm=same_arm,
    )

    assert observed is expected


def test_shadow_assessment_uses_existing_adaptive_engine() -> None:
    fingerprint = _probe_fingerprint()
    sample = LearningOutcomeSample(
        fingerprint=fingerprint,
        completed=True,
        win=True,
        pending=False,
        not_triggered=False,
        target_1_hit=True,
        target_2_hit=False,
        target_3_hit=False,
        stop_hit=False,
        realized_r=Decimal("2"),
        holding_period_days=4,
    )

    assessment = _adaptive_assessment(
        fingerprint=fingerprint,
        samples=(sample,),
        base_confidence="LOW",
    )

    assert assessment["completed_sample_count"] == 1
    assert assessment["win_count"] == 1
    assert assessment["loss_count"] == 0
    assert assessment["posterior_win_probability"] == Decimal("0.6667")
    assert assessment["evidence_strength"] == "insufficient"


def test_publication_source_contract_attributes_guarded_b9_gap() -> None:
    rows, summary = _publication_source_contract()

    assert len(rows) == len(_ADAPTIVE_METADATA_CONTRACT) == 5
    assert summary["consumer_contract_key_count"] == 5
    assert summary["producer_publication_key_count"] == 0
    assert summary["orchestrator_invokes_adaptive_assessment"] is True
    assert summary["attributed_gap_count"] == 5
    assert summary["unexplained_gap_count"] == 0
    assert all(row["gap_explained"] is True for row in rows)


def test_fingerprint_contract_gap_is_explained_and_parity_is_reachable() -> None:
    rows, summary = _fingerprint_contract_probes()

    assert len(rows) == 2
    assert summary["current_contract_mismatch"] is True
    assert summary["current_gap_explained"] is True
    assert summary["current_mismatch_codes"] == [
        "CANDLE_PATTERN_NOT_RECORDED",
        "RETRACEMENT_STATE_NOT_RECORDED",
    ]
    assert summary["complete_snapshot_parity_reachable"] is True
    assert summary["complete_snapshot_mismatch_codes"] == []


def test_evidence_sources_are_separated() -> None:
    rows = _evidence_source_separation()

    assert len(rows) == 4
    assert sum(row["equivalent_to_adaptive_learning"] is True for row in rows) == 1
    assert all(row["cross_source_merge_permitted"] is False for row in rows)


def test_non_vacuity_probes_are_complete_and_deterministic() -> None:
    rows, summary, defects = _non_vacuity_probes()

    assert defects == ()
    assert summary["probe_count"] == len(rows)
    assert summary["passed_probe_count"] == len(rows)
    assert summary["failed_probe_count"] == 0
    assert summary["deterministic"] is True
    assert len(rows) >= 12


def test_candidate_reconciliation_fails_closed_on_missing_outcome() -> None:
    candidate = {
        "price_view": "RAW",
        "observed_on": "2026-01-02",
        "symbol": "ABC",
        "final_signal": "BUY",
        "setup_type": "MOMENTUM CONTINUATION",
        "setup_stage": "ENTRY_READY",
    }

    records, defects = _candidate_records((candidate,), ())

    assert records == ()
    assert defects == ("B7_OUTCOME_MISSING@RAW:2026-01-02:ABC",)


@pytest.mark.parametrize(
    (
        "empirical",
        "fingerprints",
        "publication",
        "leakage",
        "defects",
        "arms",
        "expected",
    ),
    (
        (1, 0, 0, 0, (), 0, B8_READY),
        (0, 0, 0, 0, (), 0, B8_BLOCKED_EMPTY),
        (1, 1, 0, 0, (), 0, B8_BLOCKED_FINGERPRINT),
        (1, 0, 1, 0, (), 0, B8_BLOCKED_PUBLICATION),
        (1, 0, 0, 1, (), 0, B8_BLOCKED_LEAKAGE),
        (1, 0, 0, 0, ("DEFECT",), 0, B8_BLOCKED_DEFECT),
        (1, 0, 0, 0, (), 1, B8_BLOCKED_ARM),
    ),
)
def test_readiness_precedence(
    empirical: int,
    fingerprints: int,
    publication: int,
    leakage: int,
    defects: tuple[str, ...],
    arms: int,
    expected: str,
) -> None:
    readiness, _ = _readiness(
        empirical_population_count=empirical,
        unexplained_fingerprint_mismatches=fingerprints,
        unexplained_publication_gaps=publication,
        leakage_count=leakage,
        implementation_defects=defects,
        unexplained_arm_divergences=arms,
    )

    assert readiness == expected


def test_exported_ready_certificate_validates_and_tamper_fails(
    tmp_path: Path,
) -> None:
    report = _ready_report()
    paths = export_governed_adaptive_evidence_lineage(
        report=report,
        candidate_rows=(),
        eligibility_rows=(),
        fingerprint_rows=(),
        assessment_rows=(),
        publication_rows=(),
        source_separation_rows=(),
        comparison_rows=(),
        probe_rows=(),
        output=tmp_path,
    )
    certificate = paths[0]

    payload = validate_governed_adaptive_evidence_lineage_certificate(
        certificate,
        require_ready=True,
    )

    assert payload["readiness_decision"] == B8_READY
    assert payload["adaptive_metadata_publication_enabled"] is False

    support = tmp_path / "htr010b8_non_vacuity_probe_ledger.csv"
    support.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="supporting artifact changed"):
        validate_governed_adaptive_evidence_lineage_certificate(certificate)


def test_benchmark_cli_registers_b8_command() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])

    assert result.exit_code == 0
    assert "governed-adaptive-evidence-lineage" in result.stdout


def _ready_report() -> dict[str, object]:
    digest = "a" * 64
    source_hashes = {path: digest for path in _SOURCE_CONTRACT_PATHS}
    empty_summary = {
        "candidate_count": 0,
        "candidate_with_prior_evidence_count": 0,
    }
    return {
        "contract_version": HTR010B8_CONTRACT_VERSION,
        "b7_contract_version": "HTR-010B7-v1.0.0",
        "b7_report_sha256": digest,
        "b7_certificate_file_sha256": digest,
        "b7_candidate_ledger_sha256": digest,
        "b7_outcome_ledger_sha256": digest,
        "replay_start": "2026-01-01",
        "replay_end": "2026-07-20",
        "session_count": 133,
        "source_contract_file_sha256s": source_hashes,
        "b7_institutional_policy_source_sha256s": {"policy": digest},
        "b7_frozen_pipeline_component_sha256s": {"pipeline": digest},
        "raw_adaptive_summary": empty_summary,
        "adjusted_adaptive_summary": empty_summary,
        "publication_contract_summary": {
            "orchestrator_invokes_adaptive_assessment": False,
            "producer_publication_key_count": 0,
            "metadata_key_count": 5,
            "attributed_gap_count": 5,
        },
        "fingerprint_contract_summary": {
            "current_contract_mismatch": True,
            "current_gap_explained": True,
            "complete_snapshot_parity_reachable": True,
        },
        "point_in_time_summary": {
            "maximum_candidate_sample_count": 1,
        },
        "evidence_source_summary": {
            "source_count": 4,
        },
        "probe_summary": {
            "probe_count": 12,
            "passed_probe_count": 12,
            "failed_probe_count": 0,
            "deterministic": True,
        },
        "adaptive_population_nonempty": True,
        "candidate_population_count": 1,
        "candidate_with_prior_evidence_count": 1,
        "point_in_time_leakage_count": 0,
        "fingerprint_contract_mismatch_count": 1,
        "unexplained_fingerprint_mismatch_count": 0,
        "publication_gap_count": 5,
        "unexplained_publication_gap_count": 0,
        "implementation_defects": [],
        "implementation_defect_count": 0,
        "unexplained_adaptive_arm_divergence_count": 0,
        "readiness_blockers": [],
        "readiness_decision": B8_READY,
        "governed_adaptive_evidence_lineage_research_enabled": True,
        "governed_setup_matched_evidence_research_enabled": True,
        "adaptive_metadata_publication_enabled": False,
        "approval_policy_change_permitted": False,
        "evidence_threshold_change_permitted": False,
        "fingerprint_matching_change_permitted": False,
        "production_ledger_mutation_enabled": False,
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
        "research_scope": "GOVERNED_ADAPTIVE_EVIDENCE_LINEAGE_RESEARCH_ONLY",
    }
