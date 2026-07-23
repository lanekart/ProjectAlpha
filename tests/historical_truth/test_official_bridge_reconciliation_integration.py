from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.official_bridge_reconciliation import (
    OfficialBridgeReconciliationEngine,
)


def test_b1f_certifications_flow_to_b1g_without_replay_activation(
    tmp_path: Path,
) -> None:
    certifications = [
        {
            "bridge_case_id": f"case-{index}",
            "continuity_decision": (
                "CERTIFIED_CONTINUOUS_IDENTITY"
                if index < 23
                else "INSUFFICIENT_OFFICIAL_EVIDENCE"
            ),
            "bridge_type": "CROSS_SERIES" if index == 22 else "CROSS_ISIN",
            "effective_from": "2026-01-02",
        }
        for index in range(24)
    ]
    validations = [
        {
            "bridge_case_id": f"case-{index}",
            "bridge_certified_for_replay": index < 23,
        }
        for index in range(24)
    ]
    intervals = [
        {
            "bridge_case_id": f"case-{index}",
            "admission_state": (
                "RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT"
                if index < 23
                else "BRIDGE_UNCERTIFIED_QUARANTINED"
            ),
            "admitted_price_view": "RAW" if index < 23 else "NONE",
        }
        for index in range(24)
    ]
    paths = []
    for name, rows in (
        ("certifications", certifications),
        ("validations", validations),
        ("intervals", intervals),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        paths.append(path)

    report = OfficialBridgeReconciliationEngine().run(
        bridge_certifications_path=paths[0],
        validation_results_path=paths[1],
        admission_intervals_path=paths[2],
    )

    assert report["certified_propagation_count"] == 23
    assert report["governed_exclusion_count"] == 1
    assert report["ready_for_admission_state_rebuild"] is True
    assert report["ready_for_adjusted_replay_integration"] is False
    assert report["benchmark_replay_count"] == 0
    assert report["production_influence"] is False
