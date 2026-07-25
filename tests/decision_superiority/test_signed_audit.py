from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from alpha.benchmark_replay.governed_approval_gate_forensics import B5_READY
from alpha.benchmark_replay.governed_setup_matched_evidence import B7_READY
from alpha.decision_superiority.input_contract import GovernedInputContractError
from alpha.decision_superiority.signed_audit import GovernedSignedGateValueAudit


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_certificate(
    path: Path,
    *,
    readiness: str,
    contract_version: str,
    artifacts: tuple[Path, ...],
) -> None:
    path.write_text(
        json.dumps(
            {
                "contract_version": contract_version,
                "readiness_decision": readiness,
                "report_sha256": "a" * 64,
                "artifact_hashes": {
                    artifact.name: _sha256(artifact) for artifact in artifacts
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    candidate = tmp_path / "htr010b5_candidate_gate_forensics.csv"
    gates = tmp_path / "htr010b5_gate_event_ledger.csv"
    outcomes = tmp_path / "htr010b7_outcome_coverage_ledger.csv"
    _write_csv(
        candidate,
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
    _write_csv(
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
    _write_csv(
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
    b5 = tmp_path / "b5-certificate.json"
    b7 = tmp_path / "b7-certificate.json"
    _write_certificate(
        b5,
        readiness=B5_READY,
        contract_version="HTR-010B5-v1.0.0",
        artifacts=(candidate, gates),
    )
    _write_certificate(
        b7,
        readiness=B7_READY,
        contract_version="HTR-010B7-v1.0.0",
        artifacts=(outcomes,),
    )
    return b5, b7, candidate, gates, outcomes


def test_signed_audit_binds_b5_b7_and_source_snapshot(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _inputs(tmp_path)
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
    assert report["artifact_hashes"][source.name] == _sha256(source)
    assert source in result.paths


def test_signed_audit_rejects_substituted_ledger(tmp_path: Path) -> None:
    b5, b7, candidate, gates, outcomes = _inputs(tmp_path)
    candidate.write_text(
        "price_view,observed_on,symbol,input_fingerprint\n"
        "RAW,2026-01-02,BBB,fp-b\n",
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
