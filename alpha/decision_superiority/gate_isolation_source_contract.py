"""Fail-closed signed source-contract verification for DSI-002."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from alpha.benchmark_replay.governed_adaptive_institutional_trade_shadow import (
    B10_READY,
    HTR010B10_CONTRACT_VERSION,
    validate_governed_adaptive_institutional_trade_shadow_certificate,
)
from alpha.benchmark_replay.governed_approval_gate_forensics import B5_READY
from alpha.benchmark_replay.governed_setup_matched_evidence import B7_READY
from alpha.decision_superiority.gate_value_audit import (
    DSI001_CONTRACT_VERSION,
    DSI001_READY,
)
from alpha.decision_superiority.input_contract import (
    VerifiedCertificate,
    verify_bound_artifact,
    verify_certificate,
)

_B5_CANDIDATE: Final = "htr010b5_candidate_gate_forensics.csv"
_B5_GATE_EVENTS: Final = "htr010b5_gate_event_ledger.csv"
_B7_OUTCOMES: Final = "htr010b7_outcome_coverage_ledger.csv"
_B10_DECISIONS: Final = "htr010b10_institutional_decision_comparison.csv"
_B10_GATES: Final = "htr010b10_gate_transition_ledger.csv"
_B10_TRADES: Final = "htr010b10_portfolio_trade_formation_comparison.csv"
_B10_OUTCOMES: Final = "htr010b10_completed_trade_outcome_comparison.csv"
_DSI001_CANDIDATES: Final = "dsi001_candidate_gate_failure_ledger.csv"
_DSI001_INVENTORY: Final = "dsi001_gate_inventory.csv"
_DSI001_COUNTERFACTUALS: Final = "dsi001_single_gate_counterfactual_ledger.csv"
_DSI001_VALUES: Final = "dsi001_gate_value_summary.csv"
_DSI001_ATTRIBUTION: Final = "dsi001_gate_attribution_summary.csv"
_DSI001_RECOMMENDATIONS: Final = "dsi001_gate_recommendations.csv"
_DSI001_SOURCE: Final = "dsi001_source_contract_snapshot.csv"


class GateIsolationSourceContractError(ValueError):
    """Raised when DSI-002 cannot trust an upstream signed handoff."""


@dataclass(frozen=True, slots=True)
class GateIsolationSourcePaths:
    """Caller-selected signed certificates and exact consumed ledgers."""

    b5_certificate: Path
    b7_certificate: Path
    b10_certificate: Path
    dsi001_certificate: Path
    b5_candidate_ledger: Path
    b5_gate_ledger: Path
    b7_outcome_ledger: Path
    b10_decision_ledger: Path
    b10_gate_ledger: Path
    b10_trade_ledger: Path
    b10_outcome_ledger: Path
    dsi001_candidate_ledger: Path
    dsi001_gate_inventory: Path
    dsi001_counterfactual_ledger: Path
    dsi001_gate_value_summary: Path
    dsi001_attribution_summary: Path
    dsi001_recommendations: Path
    dsi001_source_snapshot: Path


@dataclass(frozen=True, slots=True)
class SourceCertificateSnapshot:
    """Immutable identity of one verified upstream certificate."""

    source: str
    path: str
    file_sha256: str
    contract_version: str
    readiness_decision: str
    report_sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedGateIsolationSources:
    """Complete DSI-002 source handoff after fail-closed verification."""

    certificates: tuple[SourceCertificateSnapshot, ...]
    bound_artifact_hashes: tuple[tuple[str, str], ...]
    source_contract_verified: bool = True

    def __post_init__(self) -> None:
        if not self.source_contract_verified:
            raise ValueError("verified source contract must be true")
        sources = tuple(snapshot.source for snapshot in self.certificates)
        if sources != tuple(sorted(set(sources))):
            raise ValueError("certificate sources must be unique and sorted")
        names = tuple(name for name, _ in self.bound_artifact_hashes)
        if names != tuple(sorted(set(names))):
            raise ValueError("bound artifact names must be unique and sorted")


class GateIsolationSourceContractVerifier:
    """Verify B5, B7, B10, and DSI-001 certificates and consumed ledgers."""

    def verify(self, paths: GateIsolationSourcePaths) -> VerifiedGateIsolationSources:
        b5 = verify_certificate(
            paths.b5_certificate,
            accepted_readiness=frozenset({B5_READY}),
            required_artifacts=frozenset({_B5_CANDIDATE, _B5_GATE_EVENTS}),
        )
        b7 = verify_certificate(
            paths.b7_certificate,
            accepted_readiness=frozenset({B7_READY}),
            required_artifacts=frozenset({_B7_OUTCOMES}),
        )
        b10 = _verify_b10(paths.b10_certificate)
        dsi001 = _verify_dsi001(paths.dsi001_certificate)

        hashes = {
            f"B5:{_B5_CANDIDATE}": verify_bound_artifact(
                b5,
                paths.b5_candidate_ledger,
                expected_name=_B5_CANDIDATE,
            ),
            f"B5:{_B5_GATE_EVENTS}": verify_bound_artifact(
                b5,
                paths.b5_gate_ledger,
                expected_name=_B5_GATE_EVENTS,
            ),
            f"B7:{_B7_OUTCOMES}": verify_bound_artifact(
                b7,
                paths.b7_outcome_ledger,
                expected_name=_B7_OUTCOMES,
            ),
        }
        hashes.update(
            _verify_named_paths(
                source="B10",
                declared=b10["artifact_hashes"],
                selected={
                    _B10_DECISIONS: paths.b10_decision_ledger,
                    _B10_GATES: paths.b10_gate_ledger,
                    _B10_TRADES: paths.b10_trade_ledger,
                    _B10_OUTCOMES: paths.b10_outcome_ledger,
                },
            )
        )
        hashes.update(
            _verify_named_paths(
                source="DSI001",
                declared=dsi001["artifact_hashes"],
                selected={
                    _DSI001_CANDIDATES: paths.dsi001_candidate_ledger,
                    _DSI001_INVENTORY: paths.dsi001_gate_inventory,
                    _DSI001_COUNTERFACTUALS: paths.dsi001_counterfactual_ledger,
                    _DSI001_VALUES: paths.dsi001_gate_value_summary,
                    _DSI001_ATTRIBUTION: paths.dsi001_attribution_summary,
                    _DSI001_RECOMMENDATIONS: paths.dsi001_recommendations,
                    _DSI001_SOURCE: paths.dsi001_source_snapshot,
                },
            )
        )

        snapshots = tuple(
            sorted(
                (
                    _snapshot_verified("B5", b5),
                    _snapshot_verified("B7", b7),
                    _snapshot_mapping("B10", paths.b10_certificate, b10),
                    _snapshot_mapping("DSI001", paths.dsi001_certificate, dsi001),
                ),
                key=lambda item: item.source,
            )
        )
        return VerifiedGateIsolationSources(
            certificates=snapshots,
            bound_artifact_hashes=tuple(sorted(hashes.items())),
        )


def _verify_b10(path: Path) -> dict[str, Any]:
    try:
        payload = validate_governed_adaptive_institutional_trade_shadow_certificate(
            path,
            require_ready=True,
        )
    except (OSError, ValueError) as exc:
        raise GateIsolationSourceContractError(f"B10_SOURCE_CONTRACT_INVALID:{exc}") from exc
    if payload.get("contract_version") != HTR010B10_CONTRACT_VERSION:
        raise GateIsolationSourceContractError("B10_CONTRACT_VERSION_MISMATCH")
    if payload.get("readiness_decision") != B10_READY:
        raise GateIsolationSourceContractError("B10_READINESS_NOT_ACCEPTED")
    return payload


def _verify_dsi001(path: Path) -> dict[str, Any]:
    payload = _json_mapping(path, "DSI001")
    if payload.get("contract_version") != DSI001_CONTRACT_VERSION:
        raise GateIsolationSourceContractError("DSI001_CONTRACT_VERSION_MISMATCH")
    if payload.get("readiness_decision") != DSI001_READY:
        raise GateIsolationSourceContractError("DSI001_READINESS_NOT_ACCEPTED")
    if payload.get("source_contract_verified") is not True:
        raise GateIsolationSourceContractError("DSI001_SOURCE_CONTRACT_NOT_VERIFIED")
    expected = str(payload.get("report_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("report_sha256", None)
    observed = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, default=str).encode()
    ).hexdigest()
    if expected != observed:
        raise GateIsolationSourceContractError(
            f"DSI001_REPORT_SHA256_MISMATCH:{expected}:{observed}"
        )
    declared = payload.get("artifact_hashes")
    if not isinstance(declared, dict):
        raise GateIsolationSourceContractError("DSI001_ARTIFACT_HASHES_INVALID")
    required = {
        _DSI001_CANDIDATES,
        _DSI001_INVENTORY,
        _DSI001_COUNTERFACTUALS,
        _DSI001_VALUES,
        _DSI001_ATTRIBUTION,
        _DSI001_RECOMMENDATIONS,
        _DSI001_SOURCE,
    }
    if not required.issubset({str(name) for name in declared}):
        raise GateIsolationSourceContractError("DSI001_REQUIRED_ARTIFACTS_MISSING")
    for name, digest in declared.items():
        artifact = path.parent / str(name)
        if not artifact.is_file() or _sha256(artifact) != str(digest):
            raise GateIsolationSourceContractError(
                f"DSI001_ARTIFACT_HASH_MISMATCH:{name}"
            )
    return payload


def _verify_named_paths(
    *,
    source: str,
    declared: object,
    selected: dict[str, Path],
) -> dict[str, str]:
    if not isinstance(declared, dict):
        raise GateIsolationSourceContractError(f"{source}_ARTIFACT_HASHES_INVALID")
    result: dict[str, str] = {}
    for expected_name, path in sorted(selected.items()):
        if path.name != expected_name:
            raise GateIsolationSourceContractError(
                f"{source}_BOUND_ARTIFACT_NAME_MISMATCH:{expected_name}:{path.name}"
            )
        expected = str(declared.get(expected_name) or "")
        observed = _sha256(path)
        if expected != observed:
            raise GateIsolationSourceContractError(
                f"{source}_BOUND_ARTIFACT_HASH_MISMATCH:{expected_name}"
            )
        result[f"{source}:{expected_name}"] = observed
    return result


def _snapshot_verified(source: str, certificate: VerifiedCertificate) -> SourceCertificateSnapshot:
    return SourceCertificateSnapshot(
        source=source,
        path=str(certificate.path),
        file_sha256=certificate.file_sha256,
        contract_version=certificate.contract_version,
        readiness_decision=certificate.readiness_decision,
        report_sha256=certificate.report_sha256,
    )


def _snapshot_mapping(
    source: str,
    path: Path,
    payload: dict[str, Any],
) -> SourceCertificateSnapshot:
    return SourceCertificateSnapshot(
        source=source,
        path=str(path),
        file_sha256=_sha256(path),
        contract_version=str(payload["contract_version"]),
        readiness_decision=str(payload["readiness_decision"]),
        report_sha256=str(payload["report_sha256"]),
    )


def _json_mapping(path: Path, source: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateIsolationSourceContractError(
            f"{source}_CERTIFICATE_JSON_INVALID:{path}"
        ) from exc
    if not isinstance(payload, dict):
        raise GateIsolationSourceContractError(
            f"{source}_CERTIFICATE_JSON_NOT_OBJECT:{path}"
        )
    return payload


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise GateIsolationSourceContractError(f"BOUND_ARTIFACT_NOT_FOUND:{path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "GateIsolationSourceContractError",
    "GateIsolationSourceContractVerifier",
    "GateIsolationSourcePaths",
    "SourceCertificateSnapshot",
    "VerifiedGateIsolationSources",
]
