from __future__ import annotations

import csv
from pathlib import Path

from alpha.decision_superiority.gate_isolation_frozen_input_backfill import (
    FrozenInputBackfillMode,
    FrozenInputBackfillPlanner,
    FrozenInputBackfillReadiness,
    export_frozen_input_backfill_plan,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import FrozenInputSection


def test_plan_covers_all_sections_deterministically() -> None:
    plan = FrozenInputBackfillPlanner().plan()

    assert tuple(item.section for item in plan.findings) == tuple(
        sorted(FrozenInputSection, key=lambda item: item.value)
    )
    assert plan.historical_ready_section_count == 1
    assert plan.partial_section_count == 4
    assert plan.forward_only_section_count == 2
    assert plan.complete_historical_backfill_possible is False
    assert plan.production_influence is False


def test_source_lineage_is_historically_reconstructable() -> None:
    plan = FrozenInputBackfillPlanner().plan()
    finding = next(
        item
        for item in plan.findings
        if item.section is FrozenInputSection.SOURCE_LINEAGE
    )

    assert finding.mode is FrozenInputBackfillMode.HISTORICAL_RECONSTRUCTION
    assert finding.readiness is FrozenInputBackfillReadiness.READY
    assert finding.missing_inputs == ()


def test_portfolio_and_execution_are_forward_capture_only() -> None:
    plan = FrozenInputBackfillPlanner().plan()
    by_section = {item.section: item for item in plan.findings}

    for section in (
        FrozenInputSection.PORTFOLIO_STATE,
        FrozenInputSection.EXECUTION_STATE,
    ):
        finding = by_section[section]
        assert finding.mode is FrozenInputBackfillMode.FORWARD_CAPTURE_ONLY
        assert finding.readiness is FrozenInputBackfillReadiness.UNAVAILABLE
        assert finding.reconstructable_inputs == ()
        assert finding.missing_inputs


def test_partial_sections_do_not_claim_full_reconstruction() -> None:
    plan = FrozenInputBackfillPlanner().plan()
    partial = tuple(
        item
        for item in plan.findings
        if item.readiness is FrozenInputBackfillReadiness.PARTIAL
    )

    assert len(partial) == 4
    assert all(item.mode is FrozenInputBackfillMode.HYBRID for item in partial)
    assert all(item.missing_inputs for item in partial)
    assert all(item.reconstructable_inputs for item in partial)


def test_export_is_deterministic(tmp_path: Path) -> None:
    plan = FrozenInputBackfillPlanner().plan()

    first = export_frozen_input_backfill_plan(plan, tmp_path / "first")
    second = export_frozen_input_backfill_plan(plan, tmp_path / "second")

    assert tuple(path.read_bytes() for path in first) == tuple(
        path.read_bytes() for path in second
    )
    with first[1].open(encoding="utf-8", newline="") as handle:
        summary = next(csv.DictReader(handle))
    assert summary["historical_ready_section_count"] == "1"
    assert summary["partial_section_count"] == "4"
    assert summary["forward_only_section_count"] == "2"
    assert summary["complete_historical_backfill_possible"] == "False"
    assert summary["production_influence"] == "False"
