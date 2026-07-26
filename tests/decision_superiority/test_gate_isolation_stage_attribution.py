from __future__ import annotations

import csv
import json
import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority.gate_isolation_stage_attribution import (
    DSI002DReadiness,
    DSI002DSourceContractError,
    DSI002DSourceValidator,
    GovernedStageAttributionEngine,
    StageOmissionState,
    StageResultState,
)
from alpha.decision_superiority.gate_isolation_stage_attribution_artifacts import (
    GOVERNANCE_FLAGS,
    SUPPORT_NAMES,
    DSI002DArtifactError,
    export_dsi002d,
    validate_dsi002d_certificate,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
A_ROOT = PROJECT_ROOT / "artifacts/dsi002a_acceptance/20260725T225821Z"
B_ROOT = PROJECT_ROOT / "artifacts/dsi002b_acceptance/20260726T063400Z"
C_ROOT = PROJECT_ROOT / "artifacts/dsi002c_acceptance/20260726T064625Z"
A_CERT = A_ROOT / "dsi002a_forward_capture_certificate.json"
B_CERT = B_ROOT / "dsi002b_frozen_policy_replay_certificate.json"
C_CERT = C_ROOT / "dsi002c_recorded_decision_parity_certificate.json"


@pytest.fixture(scope="module")
def governed_result():
    return GovernedStageAttributionEngine().run(
        dsi002a_certificate=A_CERT,
        dsi002b_certificate=B_CERT,
        dsi002c_certificate=C_CERT,
    )


def test_valid_signed_chain_is_bound_to_one_population(governed_result) -> None:
    assert [source.bundle for source in governed_result.sources] == [
        "DSI-002A",
        "DSI-002B",
        "DSI-002C",
    ]
    assert len({source.candidate_identity for source in governed_result.sources}) == 1
    assert len({source.snapshot_sha256 for source in governed_result.sources}) == 1
    assert all(
        len(source.certificate_file_sha256) == 64 for source in governed_result.sources
    )
    assert all(
        len(source.internal_report_sha256) == 64 for source in governed_result.sources
    )


@pytest.mark.parametrize("certificate", ("a", "b", "c"))
def test_missing_certificate_fails_closed(
    certificate: str,
    tmp_path: Path,
) -> None:
    paths = {"a": A_CERT, "b": B_CERT, "c": C_CERT}
    paths[certificate] = tmp_path / "missing.json"
    with pytest.raises(DSI002DSourceContractError):
        DSI002DSourceValidator().validate(
            dsi002a_certificate=paths["a"],
            dsi002b_certificate=paths["b"],
            dsi002c_certificate=paths["c"],
        )


def test_tampered_certificate_schema_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(A_CERT.read_text(encoding="utf-8"))
    payload["untrusted_field"] = True
    tampered = tmp_path / A_CERT.name
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        DSI002DSourceContractError,
        match="certificate schema mismatch",
    ):
        DSI002DSourceValidator().validate(
            dsi002a_certificate=tampered,
            dsi002b_certificate=B_CERT,
            dsi002c_certificate=C_CERT,
        )


def test_tampered_support_artifact_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "a"
    shutil.copytree(A_ROOT, root)
    snapshot = next((root / "capture/snapshots").glob("*.json"))
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["snapshot_sha256"] = "0" * 64
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DSI002DSourceContractError, match="not replay ready"):
        DSI002DSourceValidator().validate(
            dsi002a_certificate=root / A_CERT.name,
            dsi002b_certificate=B_CERT,
            dsi002c_certificate=C_CERT,
        )


def test_stage_inventory_is_stable_and_exact(governed_result) -> None:
    assert [item.stage_order for item in governed_result.stage_inventory] == list(
        range(1, 12)
    )
    assert governed_result.stage_inventory[0].evaluator_id == "PriceVolumeSignalEngine"
    assert governed_result.stage_inventory[-1].evaluator_id == "compare_run_to_baseline"
    assert all(
        len(item.source_sha256) == 64 for item in governed_result.stage_inventory
    )
    assert (
        sum(not item.wired_into_baseline for item in governed_result.stage_inventory)
        == 3
    )


def test_canonical_events_preserve_unknown_and_not_applicable(governed_result) -> None:
    events = {item.stage_id: item for item in governed_result.events}
    assert (
        events["recommendation.candle_pattern"].result_state
        is StageResultState.NOT_APPLICABLE
    )
    assert (
        events["institutional.base_decision"].result_state
        is StageResultState.NOT_REACHED
    )
    assert events["institutional.base_decision"].stage_invoked is False
    assert events["institutional.base_decision"].invocation_count == 0


def test_rejection_attribution_preserves_first_and_all_blockers(
    governed_result,
) -> None:
    attribution = governed_result.attributions[0]
    assert attribution.first_blocking_stage == "recommendation.trade_setup"
    assert attribution.first_blocking_gate_code == "ENTRY_NOT_READY"
    assert "recommendation.score_and_rules" in attribution.all_observed_blocking_stages
    assert "portfolio.allocation" in attribution.all_observed_blocking_stages
    assert attribution.recorded_terminal_decision == "WATCHLIST"
    assert attribution.replayed_terminal_decision == "WATCHLIST"
    assert attribution.decision_parity is True
    assert attribution.attribution_complete is False


def test_missing_institutional_wiring_is_explicit_and_blocks_readiness(
    governed_result,
) -> None:
    omitted = [
        item
        for item in governed_result.omissions
        if item.omission_state is StageOmissionState.MISSING_EVALUATOR_WIRING
    ]
    assert len(omitted) == 3
    assert governed_result.readiness is DSI002DReadiness.INCOMPLETE_INVENTORY
    assert DSI002DReadiness.INCOMPLETE_INVENTORY.value in governed_result.blockers
    assert DSI002DReadiness.ATTRIBUTION_DEFECT.value in governed_result.blockers


def test_candidate_flow_reconciles_without_silent_drop(governed_result) -> None:
    rows = {str(row["transition"]): row for row in governed_result.flow_rows}
    assert rows["accepted_captured_input"]["count"] == 1
    assert rows["request_assembly"]["count"] == 1
    assert rows["recommendation_availability"]["count"] == 1
    assert rows["terminal_decision"]["count"] == 1
    assert rows["portfolio_handoff"]["count"] == 1


def test_raw_adjusted_arms_are_not_pooled(governed_result) -> None:
    row = governed_result.arm_rows[0]
    assert row["observed_arm"] == "RAW"
    assert row["paired_arm"] == "ADJUSTED"
    assert row["paired_arm_available"] is False
    assert row["divergence_classification"] == "NOT_COMPARABLE_SINGLE_SIGNED_ARM"
    assert row["unexplained_divergence"] is False


def test_structural_probes_are_separate_from_empirical_counts(
    governed_result,
) -> None:
    assert len(governed_result.probe_rows) == 16
    assert all(row["passed"] is True for row in governed_result.probe_rows)
    assert all(
        row["included_in_empirical_counts"] is False
        for row in governed_result.probe_rows
    )


def test_models_and_canonical_input_are_immutable(governed_result) -> None:
    before = A_CERT.read_bytes()
    with pytest.raises(FrozenInstanceError):
        governed_result.events[0].stage_id = "mutated"
    assert A_CERT.read_bytes() == before


def test_export_is_byte_deterministic_and_publicly_validated(
    governed_result,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_paths = export_dsi002d(governed_result, first)
    second_paths = export_dsi002d(governed_result, second)
    assert [path.name for path in first_paths] == [path.name for path in second_paths]
    for first_path, second_path in zip(first_paths, second_paths, strict=True):
        assert first_path.read_bytes() == second_path.read_bytes()
        if first_path.suffix == ".csv":
            assert b"\r\n" not in first_path.read_bytes()
    certificate = validate_dsi002d_certificate(first_paths[0], require_ready=False)
    assert certificate["readiness_decision"] == (
        DSI002DReadiness.INCOMPLETE_INVENTORY.value
    )
    assert set(certificate["governance_flags"]) == set(GOVERNANCE_FLAGS)
    assert all(value is False for value in certificate["governance_flags"].values())
    assert set(certificate["support_artifact_manifest"]) == set(SUPPORT_NAMES)
    with pytest.raises(DSI002DArtifactError, match="not ready"):
        validate_dsi002d_certificate(first_paths[0], require_ready=True)


def test_public_validator_detects_every_bound_output_tamper(
    governed_result,
    tmp_path: Path,
) -> None:
    output = tmp_path / "bundle"
    paths = export_dsi002d(governed_result, output)
    target = output / SUPPORT_NAMES[1]
    target.write_text(
        target.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8"
    )
    with pytest.raises(DSI002DArtifactError, match="support artifact tampered"):
        validate_dsi002d_certificate(paths[0])


def test_event_ledger_serialization_is_complete(
    governed_result,
    tmp_path: Path,
) -> None:
    export_dsi002d(governed_result, tmp_path)
    with (tmp_path / SUPPORT_NAMES[1]).open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = tuple(csv.DictReader(handle))
    assert len(rows) == 11
    assert rows[0]["candidate_key"].startswith("RAW|2026-07-26|BEL|")
    assert rows[0]["observation_mode"] == "CANONICAL_BASELINE"


def test_cli_renders_blocked_governed_result(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-isolation-stage-attribution",
            "--dsi002a-certificate",
            str(A_CERT),
            "--dsi002b-certificate",
            str(B_CERT),
            "--dsi002c-certificate",
            str(C_CERT),
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "BLOCKED_BY_INCOMPLETE_STAGE_INVENTORY" in result.output
    assert "Missing evaluator wiring: 3" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output
