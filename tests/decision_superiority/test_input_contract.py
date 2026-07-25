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
    assert verified.artifact_hashes == (
        ("support.csv", _sha256(tmp_path / "support.csv")),
    )


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


def test_rejects_missing_certificate_file(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.json"

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_NOT_FOUND",
    ):
        verify_certificate(
            missing,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset(),
        )


def test_rejects_invalid_json_in_certificate(tmp_path: Path) -> None:
    certificate = tmp_path / "invalid.json"
    certificate.write_text("{ this is not valid json", encoding="utf-8")

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_JSON_INVALID",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset(),
        )


def test_rejects_non_object_json_in_certificate(tmp_path: Path) -> None:
    certificate = tmp_path / "array.json"
    certificate.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_JSON_NOT_OBJECT",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset(),
        )


def test_rejects_missing_contract_version(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    certificate.write_text(
        json.dumps(
            {
                "readiness_decision": "READY_FOR_RESEARCH",
                "report_sha256": "a" * 64,
                "artifact_hashes": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_FIELD_INVALID:contract_version",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset(),
        )


def test_rejects_missing_readiness_decision(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    certificate.write_text(
        json.dumps(
            {
                "contract_version": "UPSTREAM-v1",
                "report_sha256": "a" * 64,
                "artifact_hashes": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_FIELD_INVALID:readiness_decision",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset(),
        )


def test_rejects_missing_report_sha256(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    certificate.write_text(
        json.dumps(
            {
                "contract_version": "UPSTREAM-v1",
                "readiness_decision": "READY_FOR_RESEARCH",
                "artifact_hashes": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_FIELD_INVALID:report_sha256",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset(),
        )


def test_rejects_invalid_sha256_hash_format(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    certificate.write_text(
        json.dumps(
            {
                "contract_version": "UPSTREAM-v1",
                "readiness_decision": "READY_FOR_RESEARCH",
                "report_sha256": "not_a_valid_sha256",
                "artifact_hashes": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_SHA256_INVALID:report_sha256",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset(),
        )


def test_rejects_artifact_hash_with_invalid_format(tmp_path: Path) -> None:
    support = tmp_path / "support.csv"
    support.write_text("value\n1\n", encoding="utf-8")
    certificate = tmp_path / "certificate.json"
    certificate.write_text(
        json.dumps(
            {
                "contract_version": "UPSTREAM-v1",
                "readiness_decision": "READY_FOR_RESEARCH",
                "report_sha256": "a" * 64,
                "artifact_hashes": {"support.csv": "not_a_sha256"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_ARTIFACT_SHA256_INVALID:support.csv",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset(),
        )


def test_rejects_empty_artifact_hashes(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.json"
    certificate.write_text(
        json.dumps(
            {
                "contract_version": "UPSTREAM-v1",
                "readiness_decision": "READY_FOR_RESEARCH",
                "report_sha256": "a" * 64,
                "artifact_hashes": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        GovernedInputContractError,
        match="CERTIFICATE_ARTIFACT_HASHES_INVALID",
    ):
        verify_certificate(
            certificate,
            accepted_readiness=frozenset({"READY_FOR_RESEARCH"}),
            required_artifacts=frozenset({"something.csv"}),
        )
