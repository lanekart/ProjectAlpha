from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from alpha.benchmark_replay.governed_adaptive_institutional_trade_shadow import (
    B10_READY,
    HTR010B10_CONTRACT_VERSION,
)
from alpha.benchmark_replay.governed_approval_gate_forensics import B5_READY
from alpha.benchmark_replay.governed_setup_matched_evidence import B7_READY
from alpha.decision_superiority.gate_isolation_source_contract import (
    GateIsolationSourceContractError,
    GateIsolationSourceContractVerifier,
    GateIsolationSourcePaths,
    SourceCertificateSnapshot,
    VerifiedGateIsolationSources,
)
from alpha.decision_superiority.gate_value_audit import (
    DSI001_CONTRACT_VERSION,
    DSI001_READY,
)
from alpha.decision_superiority.input_contract import VerifiedCertificate


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, text: str = "value\n1\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _signed_dsi001(root: Path) -> Path:
    required = (
        "dsi001_candidate_gate_failure_ledger.csv",
        "dsi001_gate_inventory.csv",
        "dsi001_single_gate_counterfactual_ledger.csv",
        "dsi001_gate_value_summary.csv",
        "dsi001_gate_attribution_summary.csv",
        "dsi001_gate_recommendations.csv",
        "dsi001_source_contract_snapshot.csv",
    )
    paths = tuple(_write(root / name) for name in required)
    payload: dict[str, Any] = {
        "contract_version": DSI001_CONTRACT_VERSION,
        "readiness_decision": DSI001_READY,
        "source_contract_verified": True,
        "artifact_hashes": {path.name: _sha256(path) for path in paths},
        "production_influence": False,
    }
    payload["report_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    certificate = root / "dsi001_gate_value_audit_certificate.json"
    certificate.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return certificate


def _paths(root: Path) -> GateIsolationSourcePaths:
    b5_candidate = _write(root / "htr010b5_candidate_gate_forensics.csv")
    b5_gates = _write(root / "htr010b5_gate_event_ledger.csv")
    b7_outcomes = _write(root / "htr010b7_outcome_coverage_ledger.csv")
    b10_decisions = _write(root / "htr010b10_institutional_decision_comparison.csv")
    b10_gates = _write(root / "htr010b10_gate_transition_ledger.csv")
    b10_trades = _write(
        root / "htr010b10_portfolio_trade_formation_comparison.csv"
    )
    b10_outcomes = _write(root / "htr010b10_completed_trade_outcome_comparison.csv")
    dsi001 = _signed_dsi001(root)
    return GateIsolationSourcePaths(
        b5_certificate=_write(root / "b5.json", "{}\n"),
        b7_certificate=_write(root / "b7.json", "{}\n"),
        b10_certificate=_write(root / "b10.json", "{}\n"),
        dsi001_certificate=dsi001,
        b5_candidate_ledger=b5_candidate,
        b5_gate_ledger=b5_gates,
        b7_outcome_ledger=b7_outcomes,
        b10_decision_ledger=b10_decisions,
        b10_gate_ledger=b10_gates,
        b10_trade_ledger=b10_trades,
        b10_outcome_ledger=b10_outcomes,
        dsi001_candidate_ledger=root / "dsi001_candidate_gate_failure_ledger.csv",
        dsi001_gate_inventory=root / "dsi001_gate_inventory.csv",
        dsi001_counterfactual_ledger=(
            root / "dsi001_single_gate_counterfactual_ledger.csv"
        ),
        dsi001_gate_value_summary=root / "dsi001_gate_value_summary.csv",
        dsi001_attribution_summary=root / "dsi001_gate_attribution_summary.csv",
        dsi001_recommendations=root / "dsi001_gate_recommendations.csv",
        dsi001_source_snapshot=root / "dsi001_source_contract_snapshot.csv",
    )


def _verified(path: Path, contract: str, readiness: str) -> VerifiedCertificate:
    return VerifiedCertificate(
        path=path,
        file_sha256=_sha256(path),
        contract_version=contract,
        readiness_decision=readiness,
        report_sha256="a" * 64,
        artifact_hashes=(),
    )


def test_verified_sources_require_sorted_unique_populations() -> None:
    first = SourceCertificateSnapshot("B5", "a", "1", "v", "r", "h")
    second = SourceCertificateSnapshot("B7", "b", "2", "v", "r", "h")
    verified = VerifiedGateIsolationSources(
        certificates=(first, second),
        bound_artifact_hashes=(("A", "1"), ("B", "2")),
    )
    assert verified.source_contract_verified is True

    with pytest.raises(ValueError, match="certificate sources"):
        VerifiedGateIsolationSources(
            certificates=(second, first),
            bound_artifact_hashes=(),
        )


def test_verifier_binds_all_selected_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)

    def fake_verify_certificate(
        path: Path,
        *,
        accepted_readiness: frozenset[str],
        required_artifacts: frozenset[str],
    ) -> VerifiedCertificate:
        del required_artifacts
        readiness = next(iter(accepted_readiness))
        contract = "HTR-010B5-v1.0.0" if readiness == B5_READY else "HTR-010B7-v1.0.0"
        return _verified(path, contract, readiness)

    def fake_bound(
        certificate: VerifiedCertificate,
        artifact: Path,
        *,
        expected_name: str,
    ) -> str:
        del certificate
        assert artifact.name == expected_name
        return _sha256(artifact)

    b10_hashes = {
        path.name: _sha256(path)
        for path in (
            paths.b10_decision_ledger,
            paths.b10_gate_ledger,
            paths.b10_trade_ledger,
            paths.b10_outcome_ledger,
        )
    }
    b10_payload = {
        "contract_version": HTR010B10_CONTRACT_VERSION,
        "readiness_decision": B10_READY,
        "report_sha256": "b" * 64,
        "artifact_hashes": b10_hashes,
    }

    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_source_contract.verify_certificate",
        fake_verify_certificate,
    )
    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_source_contract.verify_bound_artifact",
        fake_bound,
    )
    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_source_contract."
        "validate_governed_adaptive_institutional_trade_shadow_certificate",
        lambda path, require_ready: b10_payload,
    )

    result = GateIsolationSourceContractVerifier().verify(paths)

    assert tuple(item.source for item in result.certificates) == (
        "B10",
        "B5",
        "B7",
        "DSI001",
    )
    assert len(result.bound_artifact_hashes) == 14
    assert result.source_contract_verified is True


def test_rejects_dsi001_metadata_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    payload = json.loads(paths.dsi001_certificate.read_text(encoding="utf-8"))
    payload["production_influence"] = True
    paths.dsi001_certificate.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_source_contract.verify_certificate",
        lambda path, accepted_readiness, required_artifacts: _verified(
            path,
            "HTR-010B5-v1.0.0",
            next(iter(accepted_readiness)),
        ),
    )
    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_source_contract."
        "validate_governed_adaptive_institutional_trade_shadow_certificate",
        lambda path, require_ready: {
            "contract_version": HTR010B10_CONTRACT_VERSION,
            "readiness_decision": B10_READY,
            "report_sha256": "b" * 64,
            "artifact_hashes": {},
        },
    )

    with pytest.raises(
        GateIsolationSourceContractError,
        match="DSI001_REPORT_SHA256_MISMATCH",
    ):
        GateIsolationSourceContractVerifier().verify(paths)


def test_rejects_wrong_selected_artifact_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    wrong = _write(tmp_path / "wrong.csv")
    paths = GateIsolationSourcePaths(
        **{
            **paths.__dict__,
            "b10_decision_ledger": wrong,
        }
    )
    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_source_contract.verify_certificate",
        lambda path, accepted_readiness, required_artifacts: _verified(
            path,
            "HTR-010B5-v1.0.0",
            next(iter(accepted_readiness)),
        ),
    )
    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_source_contract.verify_bound_artifact",
        lambda certificate, artifact, expected_name: _sha256(artifact),
    )
    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_source_contract."
        "validate_governed_adaptive_institutional_trade_shadow_certificate",
        lambda path, require_ready: {
            "contract_version": HTR010B10_CONTRACT_VERSION,
            "readiness_decision": B10_READY,
            "report_sha256": "b" * 64,
            "artifact_hashes": {},
        },
    )

    with pytest.raises(
        GateIsolationSourceContractError,
        match="B10_BOUND_ARTIFACT_NAME_MISMATCH",
    ):
        GateIsolationSourceContractVerifier().verify(paths)
