"""Shared deterministic inventory evidence fixtures for HTR-006 tests."""

from __future__ import annotations

from datetime import date

from alpha.historical_replay.inventory_readiness import (
    HistoricalTruthInventoryEvidence,
    build_historical_truth_inventory_evidence,
)
from alpha.research_dataset_inventory import DATASETS, DatasetInventoryRow


def inventory_evidence(
    *,
    period_end: date,
    unready_keys: tuple[str, ...] = (),
) -> tuple[HistoricalTruthInventoryEvidence, ...]:
    """Return one complete annual inventory proof for deterministic tests."""

    period_start = date(period_end.year, 1, 1)
    rows = tuple(
        DatasetInventoryRow(
            dataset_key=definition.key,
            dataset_name=definition.name,
            required=definition.required,
            blocking=definition.blocking,
            capability=definition.capability,
            status="MISSING" if definition.key in unready_keys else "READY",
            evidence="test",
            matched_tables="",
            matched_files=0,
            row_count=0 if definition.key in unready_keys else 1,
            first_date=(
                None if definition.key in unready_keys else period_start.isoformat()
            ),
            last_date=None if definition.key in unready_keys else period_end.isoformat(),
            observed_sessions=0 if definition.key in unready_keys else 1,
            expected_sessions=1,
            missing_sessions=1 if definition.key in unready_keys else 0,
            coverage_percent=(
                "0.00" if definition.key in unready_keys else "100.00"
            ),
            certification_ready=definition.key not in unready_keys,
            limitation="missing" if definition.key in unready_keys else "",
        )
        for definition in DATASETS
    )
    return (
        build_historical_truth_inventory_evidence(
            rows,
            year=period_end.year,
            period_end=period_end,
        ),
    )


__all__ = ["inventory_evidence"]
