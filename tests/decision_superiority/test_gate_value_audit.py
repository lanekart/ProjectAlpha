from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority import GovernedGateValueAudit


def _write(
    path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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


def test_cli_emits_governance(tmp_path: Path) -> None:
    candidates, gates, outcomes = _fixtures(tmp_path)
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-gate-value",
            "--candidate-gate-forensics",
            str(candidates),
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
