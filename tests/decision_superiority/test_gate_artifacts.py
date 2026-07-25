from __future__ import annotations

import csv
import hashlib
from decimal import Decimal
from pathlib import Path

from alpha.decision_superiority.gate_artifacts import build_gate_artifact_rows
from alpha.decision_superiority.gate_pipeline import (
    GatePipelineInput,
    run_gate_pipeline,
)
from alpha.decision_superiority.gate_value_audit import GovernedGateValueAudit


def _write(
    path: Path,
    fields: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
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
                "symbol": "LOSS",
                "input_fingerprint": "a",
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-03",
                "symbol": "GAIN",
                "input_fingerprint": "b",
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
                "symbol": "LOSS",
                "stage": "BASE",
                "gate_code": "GATE_A",
                "gate_category": "RISK",
                "gate_ordinal": 1,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": True,
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-03",
                "symbol": "GAIN",
                "stage": "BASE",
                "gate_code": "GATE_B",
                "gate_category": "QUALITY",
                "gate_ordinal": 2,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": True,
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
                "symbol": "LOSS",
                "completed": True,
                "won": False,
                "realized_return_pct": "-5",
                "realized_r": "-1",
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-03",
                "symbol": "GAIN",
                "completed": True,
                "won": True,
                "realized_return_pct": "4",
                "realized_r": "1",
            },
        ],
    )
    return candidates, gates, outcomes


def test_projection_rows_are_deterministic_and_diagnostic_only() -> None:
    gate_a = run_gate_pipeline(
        GatePipelineInput(
            gate_code="GATE_A",
            sample_count=1,
            returns_pct=(Decimal("-5"),),
            minimum_required=0,
        )
    )
    gate_b = run_gate_pipeline(
        GatePipelineInput(
            gate_code="GATE_B",
            sample_count=1,
            returns_pct=(Decimal("4"),),
            minimum_required=0,
        )
    )

    rows = build_gate_artifact_rows({"GATE_B": gate_b, "GATE_A": gate_a})

    assert [row["gate_code"] for row in rows.conclusions] == [
        "GATE_A",
        "GATE_B",
    ]
    assert rows.conclusions[0]["recommendation"] == "RETAIN"
    assert rows.conclusions[1]["recommendation"] == "REMOVE"
    assert all(row["production_influence"] is False for row in rows.conclusions)
    assert all(row["production_influence"] is False for row in rows.evidence)
    assert all(row["production_influence"] is False for row in rows.confidence)
    assert all(row["production_influence"] is False for row in rows.recommendations)


def test_audit_writes_and_hash_binds_new_diagnostic_artifacts(
    tmp_path: Path,
) -> None:
    candidates, gates, outcomes = _inputs(tmp_path)
    output = tmp_path / "out"

    result = GovernedGateValueAudit().run(
        candidate_gate_forensics=candidates,
        gate_event_ledger=gates,
        outcome_coverage_ledger=outcomes,
        output=output,
    )

    expected = {
        "dsi001_gate_conclusions.csv",
        "dsi001_evidence_summary.csv",
        "dsi001_confidence_summary.csv",
        "dsi001_gate_recommendations.csv",
    }
    assert set(result.report["diagnostic_artifact_names"]) == expected
    for name in expected:
        path = output / name
        assert path.exists()
        assert result.report["artifact_hashes"][name] == hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

    conclusions = list(
        csv.DictReader(
            (output / "dsi001_gate_conclusions.csv").open(
                newline="",
                encoding="utf-8",
            )
        )
    )
    assert [row["gate_code"] for row in conclusions] == ["GATE_A", "GATE_B"]
    assert conclusions[0]["production_influence"] == "False"
    assert result.report["production_influence"] is False


def test_new_artifacts_do_not_change_legacy_result_path_contract(
    tmp_path: Path,
) -> None:
    candidates, gates, outcomes = _inputs(tmp_path)
    result = GovernedGateValueAudit().run(
        candidate_gate_forensics=candidates,
        gate_event_ledger=gates,
        outcome_coverage_ledger=outcomes,
        output=tmp_path / "out",
    )

    diagnostic_names = set(result.report["diagnostic_artifact_names"])
    assert diagnostic_names.isdisjoint(path.name for path in result.paths)
