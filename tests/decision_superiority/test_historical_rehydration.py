from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority.historical_rehydration import (
    GovernedHistoricalRecommendationRehydrationEngine,
    canonical_json,
    classify_historical_candidate,
    governance_flags,
    stable_sha256,
    structural_probe_rows,
)
from alpha.decision_superiority.historical_rehydration_artifacts import (
    DSI004_ARTIFACTS,
    DSI004_CERTIFICATE,
    export_historical_rehydration,
    validate_historical_rehydration_certificate,
)
from alpha.decision_superiority.historical_rehydration_models import (
    HistoricalRehydrationError,
    HistoricalRehydrationSourcePaths,
    RecommendationClassification,
    SliceReadiness,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DSI003 = (
    PROJECT_ROOT
    / "artifacts/dsi003_acceptance/20260726T093602Z/run_a"
    / "dsi003_population_expansion_certificate.json"
)


@pytest.fixture(scope="module")
def result():
    return GovernedHistoricalRecommendationRehydrationEngine().run(
        sources=HistoricalRehydrationSourcePaths(
            dsi003_certificate=DSI003,
            project_root=PROJECT_ROOT,
        )
    )


def test_governance_flags_are_all_false() -> None:
    flags = governance_flags()
    assert flags
    assert all(value is False for value in flags.values())
    assert flags["PRODUCTION_INFLUENCE"] is False
    assert flags["CURRENT_DEFAULT_BACKFILL_PERMITTED"] is False
    assert flags["HISTORICAL_OBJECT_FABRICATION_PERMITTED"] is False


def test_canonical_json_is_deterministic() -> None:
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert stable_sha256({"a": 1}) == stable_sha256({"a": 1})


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "exact_object": True,
                "complete_inputs": True,
                "deterministic": True,
                "fingerprint_parity": True,
                "recommendation_parity": True,
                "downstream_parity": True,
            },
            RecommendationClassification.EXACT_SERIALISED_OBJECT_REHYDRATED,
        ),
        (
            {
                "exact_object": False,
                "complete_inputs": False,
                "deterministic": True,
                "fingerprint_parity": True,
                "recommendation_parity": True,
                "downstream_parity": True,
            },
            RecommendationClassification.INPUT_UNAVAILABLE,
        ),
        (
            {
                "exact_object": False,
                "complete_inputs": True,
                "deterministic": False,
                "fingerprint_parity": True,
                "recommendation_parity": True,
                "downstream_parity": True,
            },
            RecommendationClassification.NONDETERMINISTIC,
        ),
        (
            {
                "exact_object": False,
                "complete_inputs": True,
                "deterministic": True,
                "fingerprint_parity": False,
                "recommendation_parity": True,
                "downstream_parity": True,
            },
            RecommendationClassification.FINGERPRINT_FAILED,
        ),
        (
            {
                "exact_object": False,
                "complete_inputs": True,
                "deterministic": True,
                "fingerprint_parity": True,
                "recommendation_parity": False,
                "downstream_parity": True,
            },
            RecommendationClassification.RECOMMENDATION_FAILED,
        ),
        (
            {
                "exact_object": False,
                "complete_inputs": True,
                "deterministic": True,
                "fingerprint_parity": True,
                "recommendation_parity": True,
                "downstream_parity": False,
            },
            RecommendationClassification.DOWNSTREAM_FAILED,
        ),
        (
            {
                "exact_object": False,
                "complete_inputs": True,
                "deterministic": True,
                "fingerprint_parity": True,
                "recommendation_parity": True,
                "downstream_parity": True,
            },
            RecommendationClassification.PARITY_PROVEN,
        ),
    ],
)
def test_fail_closed_candidate_classification(
    kwargs: dict[str, bool],
    expected: RecommendationClassification,
) -> None:
    assert classify_historical_candidate(**kwargs) is expected


def test_structural_probes_are_isolated() -> None:
    probes = structural_probe_rows()
    assert len(probes) == 22
    assert all(row["passed"] is True for row in probes)
    assert all(row["included_in_empirical_counts"] is False for row in probes)


def test_signed_source_population_is_preserved(result) -> None:
    assert result.summaries["dsi003_economic_candidate_count"] == 1331
    assert result.summaries["candidate_arm_count"] == 2661
    assert result.summaries["point_in_time_leakage_count"] == 0
    assert result.summaries["implementation_defect_count"] == 0


def test_recommendation_contract_is_complete_and_source_bound(result) -> None:
    rows = result.rows["recommendation_contract"]
    assert len(rows) > 100
    assert any(row["field_path"] == "recommendation.symbol" for row in rows)
    assert any("trade_plan" in str(row["field_path"]) for row in rows)
    assert all(len(str(row["source_sha256"])) == 64 for row in rows)
    assert all(row["fingerprint_participation"] is True for row in rows)


def test_historical_schema_does_not_apply_current_defaults(result) -> None:
    rows = result.rows["schema_mapping"]
    assert any(
        row["mapping_status"] == "INSUFFICIENT_FOR_OBJECT_REHYDRATION" for row in rows
    )
    assert all(row["current_default_applied"] is False for row in rows)


def test_only_bel_has_complete_frozen_inputs(result) -> None:
    rows = result.rows["candidate_inputs"]
    complete = [row for row in rows if row["complete_for_reconstruction"] is True]
    assert len(complete) == 1
    assert complete[0]["symbol"] == "BEL"
    assert complete[0]["future_only_count"] == 0
    assert complete[0]["wrong_arm_count"] == 0
    assert sum(int(row["missing_count"]) > 0 for row in rows) == 1330


def test_summary_payload_is_not_mislabelled_as_full_exact_object(result) -> None:
    inventory = result.rows["exact_inventory"]
    ledger = result.rows["exact_rehydration"]
    assert inventory[0]["full_canonical_object"] is False
    assert inventory[0]["admission_eligible"] is False
    assert ledger[0]["exactness"] == "STRUCTURAL_PARSE_ONLY"
    assert ledger[0]["admitted"] is False


def test_bel_reconstruction_is_deterministic_and_parity_proven(result) -> None:
    rows = [
        row
        for row in result.rows["reconstruction"]
        if row["classification"] == RecommendationClassification.PARITY_PROVEN.value
    ]
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BEL"
    assert rows[0]["deterministic"] is True
    assert len(str(rows[0]["object_sha256"])) == 64
    assert len(str(rows[0]["fingerprint"])) == 64


def test_reconstruction_has_exact_fingerprint_parity(result) -> None:
    row = result.rows["fingerprint_parity"][0]
    assert row["fingerprint_parity"] is True
    assert row["reconstructed_fingerprint"] == row["authoritative_fingerprint"]
    assert row["fingerprint_dimensions_complete"] is True


def test_reconstruction_has_downstream_parity(result) -> None:
    row = result.rows["downstream_parity"][0]
    assert row["candidate_construction_parity"] is True
    assert row["base_decision_parity"] is True
    assert row["terminal_parity"] is True
    assert row["allocation_parity"] is True


def test_admission_is_fail_closed(result) -> None:
    admitted = [row for row in result.rows["population"] if row["admitted"] is True]
    assert len(admitted) == 1
    assert admitted[0]["symbol"] == "BEL"
    assert admitted[0]["classification"] == (
        RecommendationClassification.PARITY_PROVEN.value
    )
    assert len(result.rows["exclusions"]) == 1330
    assert all(
        row["synthetic_object_created"] is False for row in result.rows["exclusions"]
    )


def test_complete_stack_invokes_each_stage_exactly_once(result) -> None:
    rows = result.rows["complete_stack_stages"]
    assert len(rows) == 6
    assert [int(row["stage_order"]) for row in rows] == [1, 2, 3, 4, 5, 6]
    assert all(row["stage_invoked"] is True for row in rows)
    assert all(int(row["invocation_count"]) == 1 for row in rows)
    assert all(row["canonical_stage_order"] is True for row in rows)


def test_complete_stack_matches_dsi003_terminal(result) -> None:
    comparison = result.rows["terminal_comparison"][0]
    assert comparison["difference_class"] == "EXACT_TERMINAL_PARITY"
    assert comparison["dsi003_terminal"] == comparison["dsi004_terminal"]
    assert comparison["explained"] is True


def test_batch_dsi002_reuses_certified_engine(result) -> None:
    assert len(result.rows["single_arms"]) == 7
    assert len(result.rows["remediation_search"]) == 128
    assert all(
        row["candidate_identity"].startswith("RAW|2026-07-26|BEL|")
        for row in result.rows["single_arms"]
    )


def test_batch_dsi002_has_zero_shadow_approvals(result) -> None:
    assert result.summaries["shadow_approval_count"] == 0
    assert result.readiness["H"] == SliceReadiness.H_ZERO_APPROVALS.value


def test_outcomes_remain_unobservable_without_trade(result) -> None:
    rows = result.rows["outcome_comparability"]
    assert rows
    assert all(row["completed_outcome"] is False for row in rows)
    assert all(
        row["comparability"] == "COUNTERFACTUAL_PATH_UNOBSERVABLE" for row in rows
    )
    assert result.summaries["comparable_outcome_count"] == 0


def test_population_reconciliation_has_no_silent_loss(result) -> None:
    rows = result.rows["reconciliation"]
    assert rows
    assert all(row["reconciled"] is True for row in rows)


def test_slice_readiness_preserves_blocked_exact_object_boundary(result) -> None:
    assert result.readiness["A"] == SliceReadiness.A_READY.value
    assert result.readiness["C"] == SliceReadiness.C_NO_OBJECTS.value
    assert result.readiness["K"] == SliceReadiness.K_MECHANICAL.value
    assert result.blockers == (SliceReadiness.C_NO_OBJECTS.value,)


def test_engine_does_not_mutate_signed_input() -> None:
    before = DSI003.read_bytes()
    GovernedHistoricalRecommendationRehydrationEngine().run(
        sources=HistoricalRehydrationSourcePaths(
            dsi003_certificate=DSI003,
            project_root=PROJECT_ROOT,
        )
    )
    assert DSI003.read_bytes() == before


def test_missing_dsi003_certificate_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(HistoricalRehydrationError):
        GovernedHistoricalRecommendationRehydrationEngine().run(
            sources=HistoricalRehydrationSourcePaths(
                dsi003_certificate=tmp_path / "missing.json",
                project_root=PROJECT_ROOT,
            )
        )


def test_tampered_dsi003_certificate_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / DSI003.name
    payload = json.loads(DSI003.read_text(encoding="utf-8"))
    payload["readiness_decision"] = "READY_FOR_FABRICATION"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HistoricalRehydrationError):
        GovernedHistoricalRecommendationRehydrationEngine().run(
            sources=HistoricalRehydrationSourcePaths(
                dsi003_certificate=target,
                project_root=PROJECT_ROOT,
            )
        )


def test_exports_are_byte_identical(result, tmp_path: Path) -> None:
    first = export_historical_rehydration(result, tmp_path / "first")
    second = export_historical_rehydration(result, tmp_path / "second")
    assert {path.name: path.read_bytes() for path in first} == {
        path.name: path.read_bytes() for path in second
    }
    assert len(first) == 30


def test_certificate_and_all_support_artifacts_validate(result, tmp_path: Path) -> None:
    paths = export_historical_rehydration(result, tmp_path)
    payload = validate_historical_rehydration_certificate(
        paths[0],
        require_ready=True,
        project_root=PROJECT_ROOT,
    )
    assert payload["readiness_decision"] == SliceReadiness.K_MECHANICAL.value
    assert payload["governance_flags"] == governance_flags()
    assert len(payload["support_artifact_manifest"]) == 29


def test_support_artifact_tampering_is_detected(result, tmp_path: Path) -> None:
    paths = export_historical_rehydration(result, tmp_path)
    target = tmp_path / DSI004_ARTIFACTS["population"]
    target.write_text(target.read_text(encoding="utf-8") + "tampered\n")
    with pytest.raises(
        HistoricalRehydrationError,
        match="DSI004_ARTIFACT_TAMPERED",
    ):
        validate_historical_rehydration_certificate(
            paths[0],
            project_root=PROJECT_ROOT,
        )


def test_certificate_tampering_is_detected(result, tmp_path: Path) -> None:
    paths = export_historical_rehydration(result, tmp_path)
    certificate = paths[0]
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["readiness_decision"] = "READY_FOR_PRODUCTION"
    certificate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        HistoricalRehydrationError,
        match="DSI004_REPORT_HASH_MISMATCH",
    ):
        validate_historical_rehydration_certificate(
            certificate,
            project_root=PROJECT_ROOT,
        )


def test_unsafe_support_path_is_detected(result, tmp_path: Path) -> None:
    paths = export_historical_rehydration(result, tmp_path)
    certificate = paths[0]
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    manifest = payload["support_artifact_manifest"]
    digest = manifest.pop(DSI004_ARTIFACTS["population"])
    manifest["../outside.csv"] = digest
    unsigned = dict(payload)
    unsigned.pop("report_sha256")
    payload["report_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    certificate.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        HistoricalRehydrationError,
        match="DSI004_SUPPORT_MANIFEST_INVALID",
    ):
        validate_historical_rehydration_certificate(
            certificate,
            project_root=PROJECT_ROOT,
        )


def test_source_contract_contains_no_absolute_paths(result) -> None:
    for row in result.rows["source_contract"]:
        assert not str(row["certificate_file"]).startswith("/")
        assert not str(row["source_id"]).startswith("/")


def test_cli_executes_all_slices(tmp_path: Path) -> None:
    runner = CliRunner()
    output = tmp_path / "run"
    result = runner.invoke(
        benchmark_app,
        [
            "decision-superiority-historical-recommendation-rehydration",
            "--dsi003-certificate",
            str(DSI003),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "DSI-004A Readiness:" in result.output
    assert "DSI-004K Readiness:" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output
    assert (output / DSI004_CERTIFICATE).is_file()


def test_cli_verifies_certificate(result, tmp_path: Path) -> None:
    certificate = export_historical_rehydration(result, tmp_path)[0]
    runner = CliRunner()
    cli_result = runner.invoke(
        benchmark_app,
        [
            "decision-superiority-historical-recommendation-rehydration-verify",
            "--certificate",
            str(certificate),
            "--require-ready",
        ],
    )
    assert cli_result.exit_code == 0, cli_result.output
    assert "Certificate: VALID" in cli_result.output


def test_export_csvs_have_stable_headers(result, tmp_path: Path) -> None:
    export_historical_rehydration(result, tmp_path)
    for name in DSI004_ARTIFACTS.values():
        with (tmp_path / name).open(newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle))
        assert header
        assert header == sorted(header)


def test_copy_of_bundle_remains_portable(result, tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    certificate = export_historical_rehydration(result, source)[0]
    shutil.copytree(source, target)
    copied = target / certificate.name
    payload = validate_historical_rehydration_certificate(
        copied,
        project_root=PROJECT_ROOT,
    )
    assert payload["readiness_decision"] == SliceReadiness.K_MECHANICAL.value
