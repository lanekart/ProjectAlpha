from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import DemoIntelligenceInputBuilder
from alpha.decision_superiority.historical_rehydration import stable_sha256
from alpha.decision_superiority.recommendation_snapshot_recorder import (
    CanonicalRecommendationSnapshotRecorder,
    replay_snapshot_package,
    validate_snapshot_package,
)
from alpha.decision_superiority.recommendation_snapshot_retention import (
    GovernedRecommendationReplayRetentionEngine,
    governance_flags,
    structural_probe_rows,
)
from alpha.decision_superiority.recommendation_snapshot_retention_artifacts import (
    DSI005_ARTIFACTS,
    DSI005_CERTIFICATE,
    DSI005_JSONL,
    DSI005_REPORT,
    DSI005_SNAPSHOT_PROBE,
    export_replay_retention,
    validate_replay_retention_certificate,
)
from alpha.decision_superiority.recommendation_snapshot_retention_models import (
    CaptureDisposition,
    ReplayRetentionError,
    ReplayRetentionSourcePaths,
    SliceReadiness,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DSI004_CERTIFICATE = (
    _PROJECT_ROOT
    / "artifacts/dsi004_acceptance/20260726T104436Z/run_a"
    / "dsi004_rehydration_certificate.json"
)


@pytest.fixture(scope="module")
def retention_result():
    return GovernedRecommendationReplayRetentionEngine().run(
        sources=ReplayRetentionSourcePaths(
            dsi004_certificate=_DSI004_CERTIFICATE,
            project_root=_PROJECT_ROOT,
        )
    )


@pytest.fixture()
def captured_package(
    tmp_path: Path,
) -> tuple[Path, CanonicalRecommendationSnapshotRecorder]:
    recorder = CanonicalRecommendationSnapshotRecorder(tmp_path)
    IntelligenceApplicationService(
        governed_recommendation_snapshot_recorder=recorder,
        governed_recommendation_snapshot_capture_enabled=True,
    ).run(observed_on=date(2026, 7, 26))
    return next(tmp_path.glob("*.json")), recorder


def test_dsi004_certificate_is_required(tmp_path: Path) -> None:
    with pytest.raises(ReplayRetentionError, match="INVALID_DSI004_CERTIFICATE"):
        GovernedRecommendationReplayRetentionEngine().run(
            sources=ReplayRetentionSourcePaths(
                dsi004_certificate=tmp_path / "missing.json",
                project_root=_PROJECT_ROOT,
            )
        )


def test_all_governance_flags_are_false() -> None:
    flags = governance_flags()
    assert flags
    assert not any(flags.values())
    assert flags["DEFAULT_SNAPSHOT_CAPTURE_ENABLED"] is False
    assert flags["PRODUCTION_INFLUENCE"] is False


def test_deficit_population_is_fully_accounted(retention_result) -> None:
    assert retention_result.summaries["dsi004_excluded_candidate_count"] == 1330
    assert retention_result.summaries["missing_required_field_row_count"] == 19950
    assert len(retention_result.rows["deficits"]) == 19950
    assert retention_result.summaries["deficit_signature_count"] == 1


def test_every_deficit_is_attributed(retention_result) -> None:
    rows = retention_result.rows["deficits"]
    assert all(row["missing_reason"] for row in rows)
    assert all(row["potential_primitive_source"] for row in rows)
    assert all(row["fingerprint_critical"] is True for row in rows)


def test_signature_groups_all_excluded_candidates(retention_result) -> None:
    row = retention_result.rows["deficit_signatures"][0]
    assert row["candidate_count"] == 1330
    assert row["field_count"] == 15
    assert row["currently_irrecoverable_field_count"] == 15


def test_historical_derivability_does_not_invent_values(retention_result) -> None:
    assert retention_result.summaries["exactly_derivable_value_count"] == 0
    assert retention_result.summaries["current_default_only_value_count"] == 0
    assert retention_result.summaries["future_only_value_count"] == 0
    assert all(
        row["admitted_for_materialisation"] is False
        for row in retention_result.rows["derivability"]
    )


def test_bel_retained_snapshot_is_preserved(retention_result) -> None:
    assert len(retention_result.jsonl_rows) == 1
    snapshot = retention_result.jsonl_rows[0]
    assert snapshot["security_identity"] == "BEL"
    assert snapshot["newly_materialised"] is False
    assert snapshot["production_influence"] is False


def test_historical_snapshot_has_field_provenance(retention_result) -> None:
    rows = retention_result.rows["historical_provenance"]
    assert len(rows) == 7
    assert all(row["field_state"] == "RETAINED" for row in rows)
    assert all(row["point_in_time_valid"] is True for row in rows)


def test_materialisation_parity_is_bel_only(retention_result) -> None:
    row = retention_result.rows["materialisation_parity"][0]
    assert row["method"] == "RETAINED_DSI002A_FROZEN_SNAPSHOT"
    assert row["fingerprint_parity"] == "true"
    assert row["complete_stack_parity"] is True
    assert row["admitted_method"] is True


def test_point_in_time_probes_are_fail_closed(retention_result) -> None:
    rows = retention_result.rows["pit_validation"]
    assert len(rows) == 11
    assert retention_result.summaries["point_in_time_failure_count"] == 0
    assert retention_result.summaries["point_in_time_leakage_count"] == 0


def test_zero_additional_historical_admission(retention_result) -> None:
    assert retention_result.summaries["newly_materialised_candidate_count"] == 0
    assert retention_result.summaries["newly_admitted_candidate_count"] == 0
    assert retention_result.summaries["total_admitted_candidate_count"] == 1
    assert len(retention_result.rows["renewed_exclusions"]) == 1330


def test_renewed_dsi002_boundary_is_unchanged(retention_result) -> None:
    row = retention_result.rows["renewed_dsi002"][0]
    assert row["candidate_count"] == 1
    assert row["new_candidate_count"] == 0
    assert row["shadow_approval_count"] == 0
    assert row["comparable_outcome_count"] == 0


def test_slice_readiness_preserves_retrospective_limit(retention_result) -> None:
    assert retention_result.readiness["C"] == SliceReadiness.C_ZERO_ADDITIONAL
    assert retention_result.readiness["E"] == SliceReadiness.E_NO_ADDITIONAL
    assert retention_result.readiness["I"] == SliceReadiness.I_READY


def test_default_service_does_not_capture(tmp_path: Path) -> None:
    IntelligenceApplicationService().run(observed_on=date(2026, 7, 26))
    assert tuple(tmp_path.iterdir()) == ()


def test_enabled_capture_requires_recorder() -> None:
    with pytest.raises(ValueError, match="requires an injected recorder"):
        IntelligenceApplicationService(
            governed_recommendation_snapshot_capture_enabled=True
        )


def test_new_capture_is_append_only(captured_package) -> None:
    package, recorder = captured_package
    payload = validate_snapshot_package(package)
    assert recorder.disposition(str(payload["capture_id"])) is CaptureDisposition.NEW


def test_repeated_identical_capture_is_idempotent(tmp_path: Path) -> None:
    recorder = CanonicalRecommendationSnapshotRecorder(tmp_path)
    service = IntelligenceApplicationService(
        governed_recommendation_snapshot_recorder=recorder,
        governed_recommendation_snapshot_capture_enabled=True,
    )
    service.run(observed_on=date(2026, 7, 26))
    package = next(tmp_path.glob("*.json"))
    payload = validate_snapshot_package(package)
    before = package.read_bytes()
    service.run(observed_on=date(2026, 7, 26))
    assert package.read_bytes() == before
    assert (
        recorder.disposition(str(payload["capture_id"])) is CaptureDisposition.IDENTICAL
    )


def test_conflicting_existing_capture_fails_closed(tmp_path: Path) -> None:
    recorder = CanonicalRecommendationSnapshotRecorder(tmp_path)
    service = IntelligenceApplicationService(
        governed_recommendation_snapshot_recorder=recorder,
        governed_recommendation_snapshot_capture_enabled=True,
    )
    service.run(observed_on=date(2026, 7, 26))
    package = next(tmp_path.glob("*.json"))
    package.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ReplayRetentionError, match="CONFLICTING_CAPTURE"):
        service.run(observed_on=date(2026, 7, 26))


def test_snapshot_package_contains_complete_contract(captured_package) -> None:
    package, _ = captured_package
    payload = validate_snapshot_package(package)
    assert payload["input_snapshot"]
    assert payload["recommendations"]
    assert payload["recommendation_fingerprints"]
    assert payload["complete_stack"]
    assert payload["recorded_plan_ids"]
    assert payload["outcome_link_ids"]
    assert payload["source_manifest"]


def test_snapshot_round_trip_reproduces_decisions(captured_package) -> None:
    package, _ = captured_package
    result = replay_snapshot_package(package)
    assert result.ready
    assert result.input_parity
    assert result.recommendation_parity
    assert result.fingerprint_parity
    assert result.complete_stack_parity
    assert result.plan_identity_parity


@pytest.mark.parametrize(
    "field",
    (
        "input_snapshot",
        "recommendation_fingerprints",
        "policy_hash",
        "complete_stack",
        "recorded_plan_ids",
        "source_manifest",
        "outcome_links",
    ),
)
def test_snapshot_tampering_is_detected(
    captured_package,
    tmp_path: Path,
    field: str,
) -> None:
    package, _ = captured_package
    payload = json.loads(package.read_text(encoding="utf-8"))
    payload[field] = {"tampered": True}
    target = tmp_path / f"{field}.json"
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(ReplayRetentionError, match="TAMPERED|MISMATCH"):
        validate_snapshot_package(target)


def test_secret_field_is_rejected_even_with_valid_hash(
    captured_package,
    tmp_path: Path,
) -> None:
    package, _ = captured_package
    payload = json.loads(package.read_text(encoding="utf-8"))
    payload["source_manifest"]["client_secret"] = "never-store"
    body = dict(payload)
    body.pop("package_sha256")
    payload["package_sha256"] = stable_sha256(body)
    target = tmp_path / "secret.json"
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(ReplayRetentionError, match="SECRET_FIELD_REJECTED"):
        validate_snapshot_package(target)


def test_secret_in_input_metadata_blocks_capture(tmp_path: Path) -> None:
    inputs = DemoIntelligenceInputBuilder().build(observed_on=date(2026, 7, 26))
    candidate = inputs.recommendation_candidates[0]
    secret_candidate = replace(
        candidate,
        metadata={**candidate.metadata, "access_token": "never-store"},
    )
    secret_inputs = replace(
        inputs,
        recommendation_candidates=(
            secret_candidate,
            *inputs.recommendation_candidates[1:],
        ),
    )

    class SecretProvider:
        def build(self, *, observed_on: date):
            return secret_inputs

    service = IntelligenceApplicationService(
        input_provider=SecretProvider(),
        governed_recommendation_snapshot_recorder=(
            CanonicalRecommendationSnapshotRecorder(tmp_path)
        ),
        governed_recommendation_snapshot_capture_enabled=True,
    )
    with pytest.raises(ReplayRetentionError, match="SECRET_FIELD_REJECTED"):
        service.run(observed_on=date(2026, 7, 26))


def test_structural_probes_never_enter_empirical_counts() -> None:
    rows = structural_probe_rows()
    assert len(rows) == 24
    assert all(row["empirical_counted"] is False for row in rows)


def test_export_is_byte_identical(
    retention_result,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_paths = export_replay_retention(retention_result, first)
    second_paths = export_replay_retention(retention_result, second)
    assert [path.name for path in first_paths] == [path.name for path in second_paths]
    assert all(
        (first / path.name).read_bytes() == (second / path.name).read_bytes()
        for path in first_paths
    )


def test_export_contains_required_artifacts(retention_result, tmp_path: Path) -> None:
    paths = export_replay_retention(retention_result, tmp_path)
    names = {path.name for path in paths}
    assert DSI005_CERTIFICATE in names
    assert DSI005_REPORT in names
    assert DSI005_JSONL in names
    assert DSI005_SNAPSHOT_PROBE in names
    assert set(DSI005_ARTIFACTS.values()).issubset(names)


def test_exported_probe_package_replays_independently(
    retention_result,
    tmp_path: Path,
) -> None:
    export_replay_retention(retention_result, tmp_path)
    assert replay_snapshot_package(tmp_path / DSI005_SNAPSHOT_PROBE).ready


def test_certificate_validates_strictly(retention_result, tmp_path: Path) -> None:
    export_replay_retention(retention_result, tmp_path)
    payload = validate_replay_retention_certificate(
        tmp_path / DSI005_CERTIFICATE,
        require_ready=True,
        project_root=_PROJECT_ROOT,
    )
    assert payload["readiness_decision"] == SliceReadiness.I_READY


def test_certificate_detects_artifact_tampering(
    retention_result,
    tmp_path: Path,
) -> None:
    export_replay_retention(retention_result, tmp_path)
    artifact = tmp_path / DSI005_ARTIFACTS["deficits"]
    artifact.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ReplayRetentionError, match="ARTIFACT_TAMPERED"):
        validate_replay_retention_certificate(
            tmp_path / DSI005_CERTIFICATE,
            project_root=_PROJECT_ROOT,
        )


def test_portable_outputs_contain_no_machine_paths(
    retention_result,
    tmp_path: Path,
) -> None:
    paths = export_replay_retention(retention_result, tmp_path)
    assert all(b"/Users/" not in path.read_bytes() for path in paths)
    assert all(b"/private/tmp/" not in path.read_bytes() for path in paths)


def test_cli_executes_all_slices(tmp_path: Path) -> None:
    output = tmp_path / "run"
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-recommendation-snapshot-retention",
            "--dsi004-certificate",
            str(_DSI004_CERTIFICATE),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "DSI-005A Readiness" in result.output
    assert "DSI-005I Readiness" in result.output
    assert "DEFAULT_SNAPSHOT_CAPTURE_ENABLED=false" in result.output


def test_cli_verifies_certificate(retention_result, tmp_path: Path) -> None:
    export_replay_retention(retention_result, tmp_path)
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-recommendation-snapshot-retention-verify",
            "--certificate",
            str(tmp_path / DSI005_CERTIFICATE),
            "--require-ready",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Certificate: VALID" in result.output


def test_cli_verifies_and_replays_snapshot(captured_package) -> None:
    package, _ = captured_package
    result = CliRunner().invoke(
        benchmark_app,
        [
            "verify-recommendation-snapshot",
            "--snapshot-package",
            str(package),
            "--replay",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Snapshot: VALID" in result.output
    assert "Round Trip: READY" in result.output
