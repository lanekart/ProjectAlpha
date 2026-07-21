"""Tests for deterministic historical-truth inventory evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from alpha.historical_replay.inventory_readiness import (
    HistoricalTruthInventoryEvidence,
    build_historical_truth_inventory_evidence,
)
from tests.historical_replay.inventory_fixtures import inventory_evidence

_PERIOD_END = date(2025, 1, 10)


def test_complete_inventory_evidence_is_deterministic() -> None:
    first = inventory_evidence(period_end=_PERIOD_END)[0]
    second = inventory_evidence(period_end=_PERIOD_END)[0]

    assert first.blocking_dataset_keys == ()
    assert first.required_unready_dataset_keys == ()
    assert len(first.rows) > 1
    assert len(first.inventory_sha256) == 64
    assert first.inventory_sha256 == second.inventory_sha256
    assert first.as_dict() == second.as_dict()


def test_inventory_evidence_reports_blocking_and_required_gaps() -> None:
    evidence = inventory_evidence(
        period_end=_PERIOD_END,
        unready_keys=("daily_ohlcv", "index_constituents"),
    )[0]

    assert evidence.blocking_dataset_keys == ("daily_ohlcv",)
    assert evidence.required_unready_dataset_keys == (
        "daily_ohlcv",
        "index_constituents",
    )


def test_inventory_rejects_omitted_governed_dataset() -> None:
    complete = inventory_evidence(period_end=_PERIOD_END)[0]

    with pytest.raises(ValueError, match="every governed dataset"):
        HistoricalTruthInventoryEvidence(
            year=complete.year,
            period_end=complete.period_end,
            rows=complete.rows[:-1],
        )


def test_inventory_digest_changes_when_readiness_changes() -> None:
    complete = inventory_evidence(period_end=_PERIOD_END)[0]
    changed_rows = tuple(
        replace(
            row,
            status="MISSING",
            certification_ready=False,
            limitation="missing",
        )
        if row.dataset_key == "daily_ohlcv"
        else row
        for row in complete.rows
    )
    changed = build_historical_truth_inventory_evidence(
        changed_rows,
        year=complete.year,
        period_end=complete.period_end,
    )

    assert changed.inventory_sha256 != complete.inventory_sha256
