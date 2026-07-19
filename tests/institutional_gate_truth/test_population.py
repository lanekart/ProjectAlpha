from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from alpha.benchmark_replay.provenance import file_hash
from alpha.institutional_gate_truth.rejection_population import (
    RejectionPopulationBuilder,
)


def test_rejection_population_uses_frozen_buy_rows_and_preserves_plan(
    tmp_path: Path,
) -> None:
    benchmark = tmp_path / "benchmark"
    acu = tmp_path / "acu"
    benchmark.mkdir()
    acu.mkdir()
    approvals = benchmark / "approval_statistics.csv"
    _write_csv(
        approvals,
        (
            {
                "observed_on": "2024-01-02",
                "symbol": "TEST",
                "approved": "False",
                "opportunity_score": "82",
                "opportunity_grade": "REJECT",
                "primary_reason_code": "WEAK_SETUP",
                "rejection_category": "Approval",
                "explanation": "Rejected.",
            },
        ),
    )
    (benchmark / "manifest.json").write_text(
        json.dumps(
            {
                "baseline_id": "ALPHA_BASELINE_v1.0",
                "production_influence": False,
                "artifact_hashes": {"approval_statistics.csv": file_hash(approvals)},
            }
        ),
        encoding="utf-8",
    )
    _write_csv(
        acu / "candidate_rankings.csv",
        (
            {
                "observed_on": "2024-01-02",
                "rank": "1",
                "symbol": "TEST",
                "final_signal": "BUY",
                "score": "82",
                "confidence": "HIGH",
                "sector": "UNKNOWN",
                "liquidity_bucket": "HIGH",
                "expected_r": "2",
                "suggested_priority": "HIGH",
                "approval_candidate": "True",
                "institutional_approved": "False",
                "portfolio_eligible": "False",
                "setup_type": "BREAKOUT",
                "setup_stage": "ENTRY_READY",
                "entry_price": "100",
                "initial_stop": "90",
                "target_1": "120",
                "expected_return": "0.10",
                "holding_period_days": "20",
            },
        ),
    )
    _write_csv(
        acu / "gate_attribution.csv",
        (
            {
                "observed_on": "2024-01-02",
                "symbol": "TEST",
                "gate_code": "WEAK_SETUP",
                "category": "Trend",
                "explanation": "Weak setup.",
                "primary": "True",
            },
            {
                "observed_on": "2024-01-02",
                "symbol": "TEST",
                "gate_code": "INSUFFICIENT_EVIDENCE",
                "category": "Approval",
                "explanation": "Evidence unavailable.",
                "primary": "False",
            },
        ),
    )
    evidence = RejectionPopulationBuilder().build(
        benchmark_output=benchmark,
        acu_output=acu,
    )
    assert len(evidence.candidates) == 1
    item = evidence.candidates[0]
    assert item.symbol == "TEST"
    assert item.entry_price is not None
    assert item.prospective_stop is not None
    assert item.prospective_target is not None
    assert item.rejection_reasons == ("WEAK_SETUP", "INSUFFICIENT_EVIDENCE")
    assert item.component_scores["status"] == "UNAVAILABLE_IN_CABR_BASELINE"


def test_population_rejects_cabr_acu_score_mismatch(tmp_path: Path) -> None:
    benchmark = tmp_path / "benchmark"
    acu = tmp_path / "acu"
    benchmark.mkdir()
    acu.mkdir()
    approvals = benchmark / "approval_statistics.csv"
    _write_csv(
        approvals,
        (
            {
                "observed_on": "2024-01-02",
                "symbol": "TEST",
                "approved": "False",
                "opportunity_score": "81",
                "primary_reason_code": "WEAK_SETUP",
            },
        ),
    )
    (benchmark / "manifest.json").write_text(
        json.dumps(
            {
                "baseline_id": "ALPHA_BASELINE_v1.0",
                "production_influence": False,
                "artifact_hashes": {"approval_statistics.csv": file_hash(approvals)},
            }
        ),
        encoding="utf-8",
    )
    _write_csv(
        acu / "candidate_rankings.csv",
        (
            {
                "observed_on": "2024-01-02",
                "rank": "1",
                "symbol": "TEST",
                "final_signal": "BUY",
                "score": "82",
                "holding_period_days": "20",
            },
        ),
    )
    _write_csv(
        acu / "gate_attribution.csv",
        (
            {
                "observed_on": "2024-01-02",
                "symbol": "TEST",
                "gate_code": "WEAK_SETUP",
                "category": "Trend",
                "primary": "True",
            },
        ),
    )
    with pytest.raises(ValueError, match="score mismatch"):
        RejectionPopulationBuilder().build(
            benchmark_output=benchmark,
            acu_output=acu,
        )


def _write_csv(path: Path, rows: tuple[dict[str, str], ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
