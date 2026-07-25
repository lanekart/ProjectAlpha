"""Signed B5/B7 orchestration for the governed DSI-001 audit."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Final

from alpha.benchmark_replay.governed_approval_gate_forensics import B5_READY
from alpha.benchmark_replay.governed_setup_matched_evidence import B7_READY
from alpha.decision_superiority.gate_value_audit import DSI001Result
from alpha.decision_superiority.input_contract import (
    VerifiedCertificate,
    verify_bound_artifact,
    verify_certificate,
)
from alpha.decision_superiority.phase4f_audit import GovernedPhase4FGateValueAudit

_B5_CANDIDATE: Final = "htr010b5_candidate_gate_forensics.csv"
_B5_GATE_EVENTS: Final = "htr010b5_gate_event_ledger.csv"
_B7_OUTCOMES: Final = "htr010b7_outcome_coverage_ledger.csv"
_SOURCE_CONTRACT_NAME: Final = "dsi001_source_contract_snapshot.csv"
_CERTIFICATE_NAME: Final = "dsi001_gate_value_audit_certificate.json"


class GovernedSignedGateValueAudit:
    """Run DSI-001 only from verified B5/B7 certificates and bound ledgers."""

    def run(
        self,
        *,
        b5_certificate: Path,
        b7_certificate: Path,
        candidate_gate_forensics: Path,
        gate_event_ledger: Path,
        outcome_coverage_ledger: Path,
        output: Path,
    ) -> DSI001Result:
        b5 = verify_certificate(
            b5_certificate,
            accepted_readiness=frozenset({B5_READY}),
            required_artifacts=frozenset({_B5_CANDIDATE, _B5_GATE_EVENTS}),
        )
        b7 = verify_certificate(
            b7_certificate,
            accepted_readiness=frozenset({B7_READY}),
            required_artifacts=frozenset({_B7_OUTCOMES}),
        )
        bound_hashes = {
            _B5_CANDIDATE: verify_bound_artifact(
                b5,
                candidate_gate_forensics,
                expected_name=_B5_CANDIDATE,
            ),
            _B5_GATE_EVENTS: verify_bound_artifact(
                b5,
                gate_event_ledger,
                expected_name=_B5_GATE_EVENTS,
            ),
            _B7_OUTCOMES: verify_bound_artifact(
                b7,
                outcome_coverage_ledger,
                expected_name=_B7_OUTCOMES,
            ),
        }

        result = GovernedPhase4FGateValueAudit().run(
            candidate_gate_forensics=candidate_gate_forensics,
            gate_event_ledger=gate_event_ledger,
            outcome_coverage_ledger=outcome_coverage_ledger,
            output=output,
        )
        source_path = output / _SOURCE_CONTRACT_NAME
        _write_source_contract(source_path, b5=b5, b7=b7, bound_hashes=bound_hashes)

        report = dict(result.report)
        artifact_hashes = dict(report["artifact_hashes"])
        artifact_hashes[source_path.name] = _sha256(source_path)
        report["artifact_hashes"] = dict(sorted(artifact_hashes.items()))
        report["upstream_certificates"] = {
            "b5": _certificate_snapshot(b5),
            "b7": _certificate_snapshot(b7),
        }
        report["source_contract_verified"] = True
        report.pop("report_sha256", None)
        report["report_sha256"] = hashlib.sha256(
            json.dumps(report, sort_keys=True, default=str).encode()
        ).hexdigest()

        certificate = output / _CERTIFICATE_NAME
        certificate.write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        paths = tuple(
            path for path in result.paths if path.name != _CERTIFICATE_NAME
        ) + (source_path, certificate)
        return DSI001Result(report=report, paths=paths)


def _certificate_snapshot(certificate: VerifiedCertificate) -> dict[str, Any]:
    return {
        "path": str(certificate.path),
        "file_sha256": certificate.file_sha256,
        "contract_version": certificate.contract_version,
        "readiness_decision": certificate.readiness_decision,
        "report_sha256": certificate.report_sha256,
    }


def _write_source_contract(
    path: Path,
    *,
    b5: VerifiedCertificate,
    b7: VerifiedCertificate,
    bound_hashes: dict[str, str],
) -> None:
    rows = [
        {
            "source": "B5",
            "certificate_path": str(b5.path),
            "certificate_sha256": b5.file_sha256,
            "contract_version": b5.contract_version,
            "readiness_decision": b5.readiness_decision,
            "artifact_name": name,
            "artifact_sha256": bound_hashes[name],
        }
        for name in (_B5_CANDIDATE, _B5_GATE_EVENTS)
    ]
    rows.append(
        {
            "source": "B7",
            "certificate_path": str(b7.path),
            "certificate_sha256": b7.file_sha256,
            "contract_version": b7.contract_version,
            "readiness_decision": b7.readiness_decision,
            "artifact_name": _B7_OUTCOMES,
            "artifact_sha256": bound_hashes[_B7_OUTCOMES],
        }
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["GovernedSignedGateValueAudit"]
