from __future__ import annotations

import csv
from pathlib import Path

from alpha.decision_superiority.phase4f_audit import GovernedPhase4FGateValueAudit


def _write(
    path: Path,
    fields: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_phase4f_publishes_all_gates_and_preserves_confounding(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.csv"
    gates = tmp_path / "gates.csv"
    outcomes = tmp_path / "outcomes.csv"
    output = tmp_path / "out"
    _write(
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
    gate_fields = (
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
    )
    _write(
        gates,
        gate_fields,
        [
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "AAA",
                "gate_code": "GATE_A",
                "gate_category": "EVIDENCE",
                "stage": "BASE",
                "gate_ordinal": 1,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": True,
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "AAA",
                "gate_code": "GATE_B",
                "gate_category": "RISK",
                "stage": "BASE",
                "gate_ordinal": 2,
                "stage_reached": True,
                "outcome": "FAIL",
                "primary": False,
            },
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "AAA",
                "gate_code": "GATE_C",
                "gate_category": "DATA",
                "stage": "BASE",
                "gate_ordinal": 3,
                "stage_reached": True,
                "outcome": "PASS",
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
                "symbol": "AAA",
                "completed": True,
                "won": False,
                "realized_return_pct": "-5",
                "realized_r": "-1",
            }
        ],
    )

    result = GovernedPhase4FGateValueAudit().run(
        candidate_gate_forensics=candidates,
        gate_event_ledger=gates,
        outcome_coverage_ledger=outcomes,
        output=output,
    )

    recommendations = {
        row["gate_code"]: row for row in result.report["gate_recommendations"]
    }
    assert set(recommendations) == {"GATE_A", "GATE_B", "GATE_C"}
    for gate_code in ("GATE_A", "GATE_B"):
        row = recommendations[gate_code]
        assert row["reason_code"] == "NO_UNIQUE_BLOCKERS"
        assert row["isolated_net_gate_value"] == "UNAVAILABLE"
        assert row["isolation_status"] == "CONFOUNDED_CO_BLOCKED_ONLY"
    assert recommendations["GATE_C"]["reason_code"] == "NO_OBSERVED_FAILURES"
    assert recommendations["GATE_C"]["isolation_status"] == "NOT_OBSERVED_TO_FAIL"

    evidence = {row["gate_code"]: row for row in result.report["evidence_summary"]}
    assert evidence["GATE_A"]["observed_resolved_count"] == 1
    assert evidence["GATE_A"]["isolated_resolved_count"] == 0
    assert evidence["GATE_A"]["co_blocked_count"] == 1
    assert result.report["gate_population_reconciliation"] == {
        "observed_gate_count": 3,
        "published_gate_count": 3,
        "recommendation_population": "UNIQUE_BLOCKER_ONLY",
        "co_blocked_outcomes_are_descriptive_only": True,
    }
