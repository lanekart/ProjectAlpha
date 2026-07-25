from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.governed_approval_gate_forensics import B5_READY
from alpha.benchmark_replay.governed_setup_matched_evidence import B7_READY
from alpha.decision_superiority.gate_value_audit import DSI001Result
from alpha.decision_superiority.signed_audit import GovernedSignedGateValueAudit

_DIAGNOSTIC_ARTIFACTS = (
    "dsi001_gate_conclusions.csv",
    "dsi001_evidence_summary.csv",
    "dsi001_confidence_summary.csv",
    "dsi001_gate_recommendations.csv",
)


def _write_csv(
    path: Path,
    fields: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _serialized(value: object) -> object:
    """Return the exact JSON-compatible representation written to certificates."""

    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _signed_inputs(
    tmp_path: Path,
    *,
    resolved: bool,
) -> tuple[Path, Path, Path, Path, Path]:
    candidates = tmp_path / "htr010b5_candidate_gate_forensics.csv"
    gates = tmp_path / "htr010b5_gate_event_ledger.csv"
    outcomes = tmp_path / "htr010b7_outcome_coverage_ledger.csv"

    _write_csv(
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
                "gate_code": "GATE_A",
                "gate_category": "EVIDENCE",
                "stage": "INSTITUTIONAL",
                "gate_ordinal": 1,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": True,
            }
        ],
    )
    outcome_rows: list[dict[str, object]] = []
    if resolved:
        outcome_rows.append(
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "AAA",
                "completed": True,
                "won": False,
                "realized_return_pct": "-5",
                "realized_r": "-1",
            }
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
        outcome_rows,
    )

    b5_certificate = tmp_path / "b5-certificate.json"
    b7_certificate = tmp_path / "b7-certificate.json"
    b5_certificate.write_text(
        json.dumps(
            {
                "contract_version": "HTR-010B5-v1.0.0",
                "readiness_decision": B5_READY,
                "report_sha256": "a" * 64,
                "artifact_hashes": {
                    candidates.name: _sha256(candidates),
                    gates.name: _sha256(gates),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    b7_certificate.write_text(
        json.dumps(
            {
                "contract_version": "HTR-010B7-v1.0.0",
                "readiness_decision": B7_READY,
                "report_sha256": "b" * 64,
                "artifact_hashes": {outcomes.name: _sha256(outcomes)},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return b5_certificate, b7_certificate, candidates, gates, outcomes


def _run_signed(
    *,
    inputs: tuple[Path, Path, Path, Path, Path],
    output: Path,
) -> DSI001Result:
    b5, b7, candidates, gates, outcomes = inputs
    return GovernedSignedGateValueAudit().run(
        b5_certificate=b5,
        b7_certificate=b7,
        candidate_gate_forensics=candidates,
        gate_event_ledger=gates,
        outcome_coverage_ledger=outcomes,
        output=output,
    )


def test_signed_end_to_end_run_is_deterministic_and_hash_bound(
    tmp_path: Path,
) -> None:
    inputs = _signed_inputs(tmp_path / "inputs", resolved=True)
    first = _run_signed(inputs=inputs, output=tmp_path / "first")
    second = _run_signed(inputs=inputs, output=tmp_path / "second")

    assert first.report == second.report
    assert first.report["source_contract_verified"] is True
    assert first.report["diagnostic_artifact_names"] == list(_DIAGNOSTIC_ARTIFACTS)
    for name in _DIAGNOSTIC_ARTIFACTS:
        first_path = tmp_path / "first" / name
        second_path = tmp_path / "second" / name
        assert first_path.read_bytes() == second_path.read_bytes()
        assert first.report["artifact_hashes"][name] == _sha256(first_path)

    certificate = json.loads(
        (tmp_path / "first" / "dsi001_gate_value_audit_certificate.json").read_text(
            encoding="utf-8"
        )
    )
    assert certificate == _serialized(first.report)


def test_signed_end_to_end_cli_renders_governed_diagnostics(tmp_path: Path) -> None:
    inputs = _signed_inputs(tmp_path / "inputs", resolved=True)
    b5, b7, candidates, gates, outcomes = inputs
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--b5-certificate",
            str(b5),
            "--b7-certificate",
            str(b7),
            "--candidate-gate-forensics",
            str(candidates),
            "--gate-event-ledger",
            str(gates),
            "--outcome-coverage-ledger",
            str(outcomes),
            "--output",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Governed Gate Diagnostics" in result.output
    assert "GATE_A: recommendation=RETAIN" in result.output
    assert "confidence=SUFFICIENT" in result.output
    assert "economic=POSITIVE" in result.output
    assert "statistical=NEGATIVE" in result.output
    assert "reason=POSITIVE_NET_VALUE_AND_NEGATIVE_REJECTED_RETURN" in result.output


def test_signed_end_to_end_fails_closed_without_resolved_outcomes(
    tmp_path: Path,
) -> None:
    inputs = _signed_inputs(tmp_path / "inputs", resolved=False)
    result = _run_signed(inputs=inputs, output=tmp_path / "out")

    recommendation = result.report["gate_recommendations"][0]
    evidence = result.report["evidence_summary"][0]
    confidence = result.report["confidence_summary"][0]

    assert recommendation["recommendation"] == "INSUFFICIENT_EVIDENCE"
    assert recommendation["reason_code"] == "NO_ISOLATED_RESOLVED_OUTCOMES"
    assert evidence["confidence_status"] == "UNAVAILABLE"
    assert evidence["sufficient"] is False
    assert confidence["mean_interval_lower"] == ""
    assert confidence["mean_interval_upper"] == ""


def test_signed_end_to_end_preserves_all_governance_boundaries(
    tmp_path: Path,
) -> None:
    result = _run_signed(
        inputs=_signed_inputs(tmp_path / "inputs", resolved=True),
        output=tmp_path / "out",
    )

    for key in (
        "causal_claim_permitted",
        "threshold_change_permitted",
        "approval_policy_change_permitted",
        "portfolio_policy_change_permitted",
        "execution_policy_change_permitted",
        "recommendation_influence",
        "execution_influence",
        "active_replay_integration",
        "production_influence",
    ):
        assert result.report[key] is False

    for section in (
        "gate_conclusions",
        "evidence_summary",
        "confidence_summary",
        "gate_recommendations",
    ):
        assert all(
            row["production_influence"] is False for row in result.report[section]
        )
