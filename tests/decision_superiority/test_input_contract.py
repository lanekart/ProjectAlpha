from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from alpha.decision_superiority.input_contract import (
    GovernedInputContractError,
    verify_certificate,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _certificate(tmp_path: Path) -> Path:
    support = tmp_path / "support.csv"
    support.write_text("value\n1\n", encoding="utf-8")
    certificate = tmp_path / "certificate.json"
    certificate.write_text(
        json.dumps(
            {
                "contract_version": "UPSTREAM-v1",
                "readiness_decision": "READY_FOR_RESEARCH",
                "report_sha256": "a" * 64,
                "artifact_hashes": {support.name: _sha256(support)},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return certificate


def test_verifies_bound_certificate_and_support_artifact(tmp_path: Path) -> None:
    certificate = _certificate(tmp_path)

    verified = verify_certificate(
        certificate,
        accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
        required_artifacts=frozenset({"support.csv"}),
    )

    assert verified.contract_version == "UPSTREAM-v1"
    assert verified.readiness_decision == "READY_FOR_RESEARCH"
    assert verified.file_sha256 == _sha256(certificate)
    assert verified.artifact_hashes == (("support.csv", _sha256(tmp_path / "support.csv")),)


def test_rejects_tampered_support_artifact(tmp_path: Path) -> None:
    certificate = _certificate(tmp_path)
    (tmp_path / "support.csv").write_text("value\n2\n", encoding="utf-8")

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_ARTIFACT_HASH_MISMATCH",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset({"support.csv"}),
        )


def test_rejects_unaccepted_readiness(tmp_path: Path) -> None:
    certificate = _certificate(tmp_path)

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_READINESS_NOT_ACCEPTED",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"SOME_OTHER_READINESS"}),
            required_artifacts=frozenset({"support.csv"}),
        )


def test_rejects_missing_required_artifact_declaration(tmp_path: Path) -> None:
    certificate = _certificate(tmp_path)

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_REQUIRED_ARTIFACTS_MISSING",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset({"missing.csv"}),
        )


def test_rejects_unsafe_artifact_path(tmp_path: Path) -> None:
    certificate = _certificate(tmp_path)
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["artifact_hashes"] = {"../outside.csv": "b" * 64}
    certificate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_ARTIFACT_PATH_UNSAFE",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset(),
        )
