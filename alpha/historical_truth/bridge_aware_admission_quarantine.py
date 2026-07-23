"""Admission-interval quarantine augmentation for HTR-010B1E."""

from __future__ import annotations

from typing import Any

from alpha.historical_truth.adjustment_replay_admission_models import (
    AdmissionState,
    stable_id,
)

_QUARANTINED_ADMISSION_STATES = {
    AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED.value,
    AdmissionState.FACTOR_UNKNOWN_QUARANTINED.value,
    AdmissionState.FACTOR_AMBIGUOUS_QUARANTINED.value,
    AdmissionState.MIXED_PRICE_BASIS_QUARANTINED.value,
    AdmissionState.CONFLICTING_EVIDENCE_QUARANTINED.value,
    AdmissionState.INSUFFICIENT_EVIDENCE_QUARANTINED.value,
    AdmissionState.UNRESOLVED.value,
}


def augment_quarantine_with_admission_intervals(
    evidence_rows: tuple[dict[str, Any], ...],
    admission_intervals: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Include every blocked admission interval in economic quarantine ranges."""

    combined: dict[str, dict[str, Any]] = {}
    for row in evidence_rows:
        key = str(row.get("quarantine_id") or "") or stable_id(
            "quarantine-evidence",
            row.get("identity_key"),
            row.get("interval_start"),
            row.get("interval_end"),
            row.get("quarantine_reason"),
        )
        combined[key] = row
    for row in admission_intervals:
        state = str(row.get("admission_state") or "")
        if state not in _QUARANTINED_ADMISSION_STATES:
            continue
        key = stable_id(
            "quarantine-admission-interval",
            row.get("identity_key"),
            row.get("start_date"),
            row.get("end_date"),
            state,
        )
        combined[key] = {
            "quarantine_id": key,
            "identity_key": row.get("identity_key"),
            "symbol": row.get("symbol"),
            "series": row.get("series"),
            "isin": row.get("isin"),
            "interval_start": row.get("start_date"),
            "interval_end": row.get("end_date"),
            "quarantine_reason": state,
            "action_ids": [],
            "source": "REPLAY_ADMISSION_INTERVAL",
            "production_influence": False,
        }
    return tuple(
        sorted(
            combined.values(),
            key=lambda row: (
                str(row.get("identity_key") or ""),
                str(row.get("interval_start") or ""),
                str(row.get("interval_end") or ""),
                str(row.get("quarantine_reason") or ""),
            ),
        )
    )


__all__ = ["augment_quarantine_with_admission_intervals"]
