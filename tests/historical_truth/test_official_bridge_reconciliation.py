from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.official_bridge_reconciliation import (
    HTR010B1G_CONTRACT_VERSION,
    OfficialBridgeReconciliationEngine,
)


def _write(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_reconciliation_propagates_certified_and_quarantines_unresolved(
    tmp_path: Path,
) -> None:
    certifications = []
    validations = []
    intervals = []
    for index in range(24):
        case_id = f"case-{index}"
        certified = index != 23
        certifications.append(
            {
                "bridge_case_id": case_id,
                "continuity_decision": (
                    "CERTIFIED_CONTINUOUS_IDENTITY"
                    if certified
                    else "INSUFFICIENT_OFFICIAL_EVIDENCE"
                ),
                "bridge_type": "CROSS_ISIN",
                "pre_isin": f"PRE{index}",
                "post_isin": f"POST{index}",
                "effective_from": "2026-01-02",
            }
        )
        validations.append(
            {
                "bridge_case_id": case_id,
                "bridge_certified_for_replay": certified,
            }
        )
        intervals.append(
            {
                "bridge_case_id": case_id,
                "admission_state": (
                    "RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT"
                    if certified
                    else "BRIDGE_UNCERTIFIED_QUARANTINED"
                ),
                "admitted_price_view": "RAW" if certified else "NONE",
            }
        )

    report = OfficialBridgeReconciliationEngine().run(
        bridge_certifications_path=_write(
            tmp_path / "certifications.json", certifications
        ),
        validation_results_path=_write(tmp_path / "validations.json", validations),
        admission_intervals_path=_write(tmp_path / "intervals.json", intervals),
    )

    assert report["contract_version"] == HTR010B1G_CONTRACT_VERSION
    assert report["certified_propagation_count"] == 23
    assert report["governed_exclusion_count"] == 1
    assert report["stale_downstream_case_count"] == 0
    assert report["implementation_defect_count"] == 0
    assert report["ready_for_admission_state_rebuild"] is True
    assert report["ready_for_adjusted_replay_integration"] is False
    assert report["production_influence"] is False


def test_reconciliation_detects_stale_and_unsafe_downstream_state(
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
            "effective_from": "2026-01-02",
        }
        for index in range(24)
    ]
    validations = [
        {"bridge_case_id": f"case-{index}", "bridge_certified_for_replay": False}
        for index in range(24)
    ]
    intervals = [
        {
            "bridge_case_id": f"case-{index}",
            "admission_state": "RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT",
            "admitted_price_view": "RAW",
        }
        for index in range(24)
    ]

    report = OfficialBridgeReconciliationEngine().run(
        bridge_certifications_path=_write(
            tmp_path / "certifications.json", certifications
        ),
        validation_results_path=_write(tmp_path / "validations.json", validations),
        admission_intervals_path=_write(tmp_path / "intervals.json", intervals),
    )

    assert report["stale_downstream_case_count"] == 24
    assert report["governed_exclusion_count"] == 1
    states = report["reconciliation_state_counts"]
    assert states["CERTIFIED_BUT_DOWNSTREAM_STALE"] == 23
    assert states["UNRESOLVED_BUT_DOWNSTREAM_ADMITTED"] == 1
