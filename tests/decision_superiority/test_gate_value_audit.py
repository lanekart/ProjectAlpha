from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.governed_approval_gate_forensics import B5_READY
from alpha.benchmark_replay.governed_setup_matched_evidence import B7_READY
from alpha.decision_superiority import GovernedGateValueAudit
from alpha.decision_superiority.input_contract import GovernedInputContractError
from alpha.decision_superiority.signed_audit import GovernedSignedGateValueAudit


def _write(
    path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixtures(tmp_path: Path) -> tuple[Path, Path, Path]:
    candidates = tmp_path / "candidates.csv"
    gates = tmp_path / "gates.csv"
    outcomes = tmp_path / "outcomes.csv"
    _write(
        candidates,
        ("price_view", "observed_on", "symbol", "input_fingerprint"),
        [
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "GAIN",
                "input_fingerprint": "a",
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-03",
                "symbol": "LOSS",
                "input_fingerprint": "b",
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-04",
                "symbol": "CO",
                "input_fingerprint": "c",
            },
        ],
    )
    _write(
        gates,
        (
            "price_view",
            "observed_on",
            "symbol",
            "stage",
            "gate_code",
            "gate_category",
            "gate_ordinal",
            "stage_reached",
            "outcome",
            "primary",
        ),
        [
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "GAIN",
                "stage": "BASE",
                "gate_code": "GATE_A",
                "gate_category": "QUALITY",
                "gate_ordinal": 1,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": True,
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-03",
                "symbol": "LOSS",
                "stage": "BASE",
                "gate_code": "GATE_B",
                "gate_category": "RISK",
                "gate_ordinal": 2,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": True,
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-04",
                "symbol": "CO",
                "stage": "BASE",
                "gate_code": "GATE_A",
                "gate_category": "QUALITY",
                "gate_ordinal": 1,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": True,
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-04",
                "symbol": "CO",
                "stage": "STRESS",
                "gate_code": "GATE_B",
                "gate_category": "RISK",
                "gate_ordinal": 2,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": False,
            },
        ],
    )
    _write(
        outcomes,
        (
            "price_view",
            "observed_on",
            "symbol",
            "completed",
            "won",
            "realized_return_pct",
            "realized_r",
        ),
        [
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "GAIN",
                "completed": True,
                "won": True,
                "realized_return_pct": "12",
                "realized_r": "2",
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-03",
                "symbol": "LOSS",
                "completed": True,
                "won": False,
                "realized_return_pct": "-8",
                "realized_r": "-1",
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-04",
                "symbol": "CO",
                "completed": True,
                "won": True,
                "realized_return_pct": "3",
                "realized_r": "0.5",
            },
        ],
    )
    return candidates, gates, outcomes


def _make_signed_certificates(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, Path]:
    """Create valid B5 and B7 certificates with bound ledgers."""
    candidates = tmp_path / "htr010b5_candidate_gate_forensics.csv"
    gates = tmp_path / "htr010b5_gate_event_ledger.csv"
    outcomes = tmp_path / "htr010b7_outcome_coverage_ledger.csv"

    _write(
        candidates,
        ("price_view", "observed_on", "symbol", "input_fingerprint"),
        [
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "AAA",
                "input_fingerprint": "fp-a",
            }
        ],
    )
    _write(
        gates,
        (
            "price_view",
            "observed_on",
            "symbol",
            "gate_code",
            "gate_category",
            "stage",
            "gate_ordinal",
            "stage_reached",
            "outcome",
            "primary",
        ),
        [
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "AAA",
                "gate_code": "GATE.A",
                "gate_category": "EVIDENCE",
                "stage": "INSTITUTIONAL",
                "gate_ordinal": 1,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": True,
            }
        ],
    )
    _write(
        outcomes,
        (
            "price_view",
            "observed_on",
            "symbol",
            "completed",
            "won",
            "realized_return_pct",
            "realized_r",
        ),
        [
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "AAA",
                "completed": True,
                "won": False,
                "realized_return_pct": "-5",
                "realized_r": "-1",
            }
        ],
    )

    b5_cert = tmp_path / "b5-certificate.json"
    b7_cert = tmp_path / "b7-certificate.json"

    b5_cert.write_text(
        json.dumps(
            {
                "contract_version": "HTR-010B5-v1.0.0",
                "readiness_decision": B5_READY,
                "report_sha256": "a" * 64,
                "artifact_hashes": {
                    candidates.name: _sha256_file(candidates),
                    gates.name: _sha256_file(gates),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    b7_cert.write_text(
        json.dumps(
            {
                "contract_version": "HTR-010B7-v1.0.0",
                "readiness_decision": B7_READY,
                "report_sha256": "b" * 64,
                "artifact_hashes": {
                    outcomes.name: _sha256_file(outcomes),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return b5_cert, b7_cert, candidates, gates, outcomes


def test_gate_value_audit_separates_unique_and_coblocked(tmp_path: Path) -> None:
    candidates, gates, outcomes = _fixtures(tmp_path)
    result = GovernedGateValueAudit().run(
        candidate_gate_forensics=candidates,
        gate_event_ledger=gates,
        outcome_coverage_ledger=outcomes,
        output=tmp_path / "out",
    )
    assert (
        result.report["readiness_decision"]
        == "READY_FOR_GOVERNED_DECISION_SUPERIORITY_RESEARCH"
    )
    values = {row["gate_code"]: row for row in result.report["gate_value_summary"]}
    assert values["GATE_A"]["unique_blocked_candidate_count"] == 1
    assert values["GATE_A"]["co_blocked_candidate_count"] == 1
    assert values["GATE_A"]["conclusion"] == "GATE_DESTROYS_MEASURABLE_VALUE"
    assert values["GATE_B"]["conclusion"] == "GATE_ADDS_MEASURABLE_VALUE"
    assert result.report["production_influence"] is False


def test_artifacts_are_hash_bound(tmp_path: Path) -> None:
    candidates, gates, outcomes = _fixtures(tmp_path)
    result = GovernedGateValueAudit().run(
        candidate_gate_forensics=candidates,
        gate_event_ledger=gates,
        outcome_coverage_ledger=outcomes,
        output=tmp_path / "out",
    )
    certificate = json.loads(
        (tmp_path / "out" / "dsi001_gate_value_audit_certificate.json").read_text()
    )
    assert certificate["artifact_hashes"]
    assert len(result.paths) == 7


def test_signed_audit_binds_b5_b7_and_source_snapshot(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    result = GovernedSignedGateValueAudit().run(
        b5_certificate=b5,
        b7_certificate=b7,
        candidate_gate_forensics=candidate,
        gate_event_ledger=gates,
        outcome_coverage_ledger=outcomes,
        output=tmp_path / "out",
    )

    report = result.report
    assert report["source_contract_verified"] is True
    assert report["upstream_certificates"]["b5"]["readiness_decision"] == B5_READY
    assert report["upstream_certificates"]["b7"]["readiness_decision"] == B7_READY
    source = tmp_path / "out" / "dsi001_source_contract_snapshot.csv"
    assert report["artifact_hashes"][source.name] == _sha256_file(source)
    assert source in result.paths


def test_signed_audit_rejects_substituted_ledger(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    candidate.write_text(
        "price_view,observed_on,symbol,input_fingerprint\nRAW,2026-01-02,BBB,fp-b\n",
        encoding="utf-8",
    )

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_ARTIFACT_HASH_MISMATCH",
    ):
        GovernedSignedGateValueAudit().run(
            b5_certificate=b5,
            b7_certificate=b7,
            candidate_gate_forensics=candidate,
            gate_event_ledger=gates,
            outcome_coverage_ledger=outcomes,
            output=tmp_path / "out",
        )


def test_signed_audit_rejects_missing_b5_certificate(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    missing = tmp_path / "missing-b5.json"

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_NOT_FOUND",
    ):
        GovernedSignedGateValueAudit().run(
            b5_certificate=missing,
            b7_certificate=b7,
            candidate_gate_forensics=candidate,
            gate_event_ledger=gates,
            outcome_coverage_ledger=outcomes,
            output=tmp_path / "out",
        )


def test_signed_audit_rejects_missing_b7_certificate(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    missing = tmp_path / "missing-b7.json"

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_NOT_FOUND",
    ):
        GovernedSignedGateValueAudit().run(
            b5_certificate=b5,
            b7_certificate=missing,
            candidate_gate_forensics=candidate,
            gate_event_ledger=gates,
            outcome_coverage_ledger=outcomes,
            output=tmp_path / "out",
        )


def test_signed_audit_preserves_b5_contract_version(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    result = GovernedSignedGateValueAudit().run(
        b5_certificate=b5,
        b7_certificate=b7,
        candidate_gate_forensics=candidate,
        gate_event_ledger=gates,
        outcome_coverage_ledger=outcomes,
        output=tmp_path / "out",
    )

    assert (
        result.report["upstream_certificates"]["b5"]["contract_version"]
        == "HTR-010B5-v1.0.0"
    )


def test_signed_audit_preserves_b7_contract_version(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    result = GovernedSignedGateValueAudit().run(
        b5_certificate=b5,
        b7_certificate=b7,
        candidate_gate_forensics=candidate,
        gate_event_ledger=gates,
        outcome_coverage_ledger=outcomes,
        output=tmp_path / "out",
    )

    assert (
        result.report["upstream_certificates"]["b7"]["contract_version"]
        == "HTR-010B7-v1.0.0"
    )


def test_signed_audit_preserves_certificate_sha256(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    result = GovernedSignedGateValueAudit().run(
        b5_certificate=b5,
        b7_certificate=b7,
        candidate_gate_forensics=candidate,
        gate_event_ledger=gates,
        outcome_coverage_ledger=outcomes,
        output=tmp_path / "out",
    )

    assert result.report["upstream_certificates"]["b5"]["file_sha256"] == _sha256_file(
        b5
    )
    assert result.report["upstream_certificates"]["b7"]["file_sha256"] == _sha256_file(
        b7
    )


def test_cli_signed_execution_success(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output
    assert "Source Contract Verified: True" in result.output


def test_cli_rejects_missing_b5_certificate(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    missing = tmp_path / "missing-b5.json"
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(missing),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 1
    assert "SIGNED_EXECUTION_FAILED" in result.output


def test_cli_rejects_missing_b7_certificate(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    missing = tmp_path / "missing-b7.json"
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(missing),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 1
    assert "SIGNED_EXECUTION_FAILED" in result.output


def test_cli_rejects_tampered_ledger(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    candidate.write_text(
        "price_view,observed_on,symbol,input_fingerprint\nRAW,2026-01-02,TAMPERED,fp-tampered\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 1
    assert "SIGNED_EXECUTION_FAILED" in result.output
    assert "CERTIFICATE_ARTIFACT_HASH_MISMATCH" in result.output


def test_cli_emits_governance_flags(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 0
    assert "RECOMMENDATION_INFLUENCE=false" in result.output
    assert "EXECUTION_INFLUENCE=false" in result.output
    assert "ACTIVE_REPLAY_INTEGRATION=false" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output


def test_cli_requires_b5_certificate_option(tmp_path: Path) -> None:
    """CLI must fail when --b5-certificate is not provided."""
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code != 0
    assert "Missing option" in result.output or "requires" in result.output.lower()


def test_cli_requires_b7_certificate_option(tmp_path: Path) -> None:
    """CLI must fail when --b7-certificate is not provided."""
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code != 0
    assert "Missing option" in result.output or "requires" in result.output.lower()


def test_cli_rejects_invalid_json_in_b5_certificate(tmp_path: Path) -> None:
    """CLI must fail when B5 certificate contains invalid JSON."""
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    b5.write_text("{ this is not valid json", encoding="utf-8")
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 1
    assert "SIGNED_EXECUTION_FAILED" in result.output
    assert "CERTIFICATE_JSON_INVALID" in result.output


def test_cli_rejects_invalid_json_in_b7_certificate(tmp_path: Path) -> None:
    """CLI must fail when B7 certificate contains invalid JSON."""
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    b7.write_text("{ this is not valid json", encoding="utf-8")
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 1
    assert "SIGNED_EXECUTION_FAILED" in result.output
    assert "CERTIFICATE_JSON_INVALID" in result.output


def test_cli_deterministic_execution_produces_same_report_hash(tmp_path: Path) -> None:
    """CLI must produce deterministic output with same report hash for same inputs."""
    # Use the same inputs for both runs
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)

    # Run 1
    result1 = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli1"),
        ],
    )

    # Run 2 with different output directory but same inputs
    result2 = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli2"),
        ],
    )

    assert result1.exit_code == 0, result1.output
    assert result2.exit_code == 0, result2.output

    # Extract report SHA-256 from both runs
    import re

    match1 = re.search(r"Report SHA256: ([a-f0-9]{64})", result1.output)
    match2 = re.search(r"Report SHA256: ([a-f0-9]{64})", result2.output)

    assert match1, f"Could not find Report SHA256 in output:\n{result1.output}"
    assert match2, f"Could not find Report SHA256 in output:\n{result2.output}"

    sha256_1 = match1.group(1)
    sha256_2 = match2.group(1)
    assert sha256_1 == sha256_2, f"Report SHAs differ: {sha256_1} vs {sha256_2}"


def test_cli_preserves_certificate_file_sha256(tmp_path: Path) -> None:
    """CLI must preserve and report B5/B7 certificate file SHA-256."""
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 0, result.output

    # Load the final certificate to verify preservation
    import hashlib

    certificate_path = tmp_path / "cli" / "dsi001_gate_value_audit_certificate.json"
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))

    # Verify upstream certificates are preserved with file SHA-256
    assert "upstream_certificates" in certificate
    assert "b5" in certificate["upstream_certificates"]
    assert "b7" in certificate["upstream_certificates"]

    b5_cert = certificate["upstream_certificates"]["b5"]
    b7_cert = certificate["upstream_certificates"]["b7"]

    assert "file_sha256" in b5_cert
    assert "file_sha256" in b7_cert
    assert b5_cert["file_sha256"] == hashlib.sha256(b5.read_bytes()).hexdigest()
    assert b7_cert["file_sha256"] == hashlib.sha256(b7.read_bytes()).hexdigest()


def test_cli_preserves_contract_versions(tmp_path: Path) -> None:
    """CLI must preserve B5/B7 contract versions in certificate."""
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 0, result.output

    certificate_path = tmp_path / "cli" / "dsi001_gate_value_audit_certificate.json"
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))

    # Verify contract versions are preserved
    b5_cert = certificate["upstream_certificates"]["b5"]
    b7_cert = certificate["upstream_certificates"]["b7"]

    assert b5_cert["contract_version"] == "HTR-010B5-v1.0.0"
    assert b7_cert["contract_version"] == "HTR-010B7-v1.0.0"


def test_cli_preserves_readiness_decisions(tmp_path: Path) -> None:
    """CLI must preserve B5/B7 readiness decisions in certificate."""
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 0, result.output

    certificate_path = tmp_path / "cli" / "dsi001_gate_value_audit_certificate.json"
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))

    # Verify readiness decisions are preserved
    b5_cert = certificate["upstream_certificates"]["b5"]
    b7_cert = certificate["upstream_certificates"]["b7"]

    assert b5_cert["readiness_decision"] == B5_READY
    assert b7_cert["readiness_decision"] == B7_READY


def test_cli_preserves_ledger_artifact_sha256(tmp_path: Path) -> None:
    """CLI must preserve exact consumed ledger SHA-256 in source contract."""
    b5, b7, candidate, gates, outcomes = _make_signed_certificates(tmp_path)

    import hashlib

    candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    gates_sha = hashlib.sha256(gates.read_bytes()).hexdigest()
    outcomes_sha = hashlib.sha256(outcomes.read_bytes()).hexdigest()

    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidate),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 0, result.output

    source_contract_path = tmp_path / "cli" / "dsi001_source_contract_snapshot.csv"
    with source_contract_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    # Verify B5 candidate and gate event ledger SHAs
    b5_rows = [row for row in rows if row["source"] == "B5"]
    candidate_row = next(
        (
            row
            for row in b5_rows
            if row["artifact_name"] == "htr010b5_candidate_gate_forensics.csv"
        ),
        None,
    )
    gates_row = next(
        (
            row
            for row in b5_rows
            if row["artifact_name"] == "htr010b5_gate_event_ledger.csv"
        ),
        None,
    )

    assert candidate_row is not None
    assert gates_row is not None
    assert candidate_row["artifact_sha256"] == candidate_sha
    assert gates_row["artifact_sha256"] == gates_sha

    # Verify B7 outcome coverage ledger SHA
    b7_rows = [row for row in rows if row["source"] == "B7"]
    outcomes_row = next(
        (
            row
            for row in b7_rows
            if row["artifact_name"] == "htr010b7_outcome_coverage_ledger.csv"
        ),
        None,
    )

    assert outcomes_row is not None
    assert outcomes_row["artifact_sha256"] == outcomes_sha
