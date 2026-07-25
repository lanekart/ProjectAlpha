"""Fail-closed verification for signed DSI-001 upstream inputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_SHA256_HEX_LENGTH: Final = 64


class GovernedInputContractError(ValueError):
    """Raised when a signed upstream input cannot be trusted."""


@dataclass(frozen=True, slots=True)
class VerifiedCertificate:
    """Verified certificate identity and bound support artifacts."""

    path: Path
    file_sha256: str
    contract_version: str
    readiness_decision: str
    report_sha256: str
    artifact_hashes: tuple[tuple[str, str], ...]


def verify_certificate(
    path: Path,
    *,
    accepted_readiness: frozenset[str],
    required_artifacts: frozenset[str],
) -> VerifiedCertificate:
    """Verify certificate structure, report digest, readiness, and artifacts."""

    if not path.is_file():
        raise GovernedInputContractError(f"CERTIFICATE_NOT_FOUND:{path}")

    payload = _read_json_object(path)
    readiness = _required_text(payload, "readiness_decision")
    if readiness not in accepted_readiness:
        raise GovernedInputContractError(
            f"CERTIFICATE_READINESS_NOT_ACCEPTED:{readiness}"
        )

    contract_version = _required_text(payload, "contract_version")
    report_sha256 = _required_sha256(payload, "report_sha256")
    artifact_hashes = _artifact_hashes(payload)
    declared_names = frozenset(name for name, _ in artifact_hashes)
    missing = sorted(required_artifacts - declared_names)
    if missing:
        raise GovernedInputContractError(
            "CERTIFICATE_REQUIRED_ARTIFACTS_MISSING:" + "|".join(missing)
        )

    for name, expected_sha256 in artifact_hashes:
        artifact = _resolve_artifact(path.parent, name)
        actual_sha256 = _sha256(artifact)
        if actual_sha256 != expected_sha256:
            raise GovernedInputContractError(
                "CERTIFICATE_ARTIFACT_HASH_MISMATCH:"
                f"{name}:{expected_sha256}:{actual_sha256}"
            )

    computed_report_sha256 = _report_digest(payload)
    if computed_report_sha256 != report_sha256:
        raise GovernedInputContractError(
            "CERTIFICATE_REPORT_SHA256_MISMATCH:"
            f"{report_sha256}:{computed_report_sha256}"
        )

    return VerifiedCertificate(
        path=path,
        file_sha256=_sha256(path),
        contract_version=contract_version,
        readiness_decision=readiness,
        report_sha256=report_sha256,
        artifact_hashes=artifact_hashes,
    )


def verify_bound_artifact(
    certificate: VerifiedCertificate,
    artifact: Path,
    *,
    expected_name: str,
) -> str:
    """Verify a caller-supplied artifact matches the signed certificate binding."""

    if artifact.name != expected_name:
        raise GovernedInputContractError(
            f"BOUND_ARTIFACT_NAME_MISMATCH:{expected_name}:{artifact.name}"
        )
    if not artifact.is_file():
        raise GovernedInputContractError(f"BOUND_ARTIFACT_NOT_FOUND:{artifact}")

    declared = dict(certificate.artifact_hashes)
    expected_sha256 = declared.get(expected_name)
    if expected_sha256 is None:
        raise GovernedInputContractError(f"BOUND_ARTIFACT_NOT_DECLARED:{expected_name}")

    actual_sha256 = _sha256(artifact)
    if actual_sha256 != expected_sha256:
        raise GovernedInputContractError(
            "BOUND_ARTIFACT_HASH_MISMATCH:"
            f"{expected_name}:{expected_sha256}:{actual_sha256}"
        )
    return actual_sha256


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernedInputContractError(f"CERTIFICATE_JSON_INVALID:{path}") from exc
    if not isinstance(parsed, dict):
        raise GovernedInputContractError(f"CERTIFICATE_JSON_NOT_OBJECT:{path}")
    return parsed


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GovernedInputContractError(f"CERTIFICATE_FIELD_INVALID:{key}")
    return value.strip()


def _required_sha256(payload: dict[str, Any], key: str) -> str:
    value = _required_text(payload, key).lower()
    if not _is_sha256(value):
        raise GovernedInputContractError(f"CERTIFICATE_SHA256_INVALID:{key}")
    return value


def _artifact_hashes(payload: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    raw = payload.get("artifact_hashes")
    if not isinstance(raw, dict) or not raw:
        raise GovernedInputContractError("CERTIFICATE_ARTIFACT_HASHES_INVALID")

    verified: list[tuple[str, str]] = []
    for raw_name, raw_hash in raw.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise GovernedInputContractError("CERTIFICATE_ARTIFACT_NAME_INVALID")
        if not isinstance(raw_hash, str) or not _is_sha256(raw_hash.lower()):
            raise GovernedInputContractError(
                f"CERTIFICATE_ARTIFACT_SHA256_INVALID:{raw_name}"
            )
        name = raw_name.strip()
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise GovernedInputContractError(f"CERTIFICATE_ARTIFACT_PATH_UNSAFE:{name}")
        verified.append((name, raw_hash.lower()))
    return tuple(sorted(verified))


def _resolve_artifact(root: Path, name: str) -> Path:
    artifact = root / name
    if not artifact.is_file():
        raise GovernedInputContractError(f"CERTIFICATE_ARTIFACT_NOT_FOUND:{name}")
    return artifact


def _report_digest(payload: dict[str, Any]) -> str:
    report = dict(payload)
    report.pop("report_sha256", None)
    encoded = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == _SHA256_HEX_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "GovernedInputContractError",
    "VerifiedCertificate",
    "verify_bound_artifact",
    "verify_certificate",
]
