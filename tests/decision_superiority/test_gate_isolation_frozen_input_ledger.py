from __future__ import annotations

import csv
from pathlib import Path

import pytest

from alpha.decision_superiority.gate_isolation_baseline import (
    FrozenBaselineCandidate,
    FrozenBaselinePopulation,
)
from alpha.decision_superiority.gate_isolation_frozen_input_ledger import (
    FrozenInputPopulationAuditor,
    export_frozen_input_population_audit,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenCandidateInputSnapshot,
    FrozenInputSection,
    FrozenInputSectionSnapshot,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey


def _candidate(symbol: str = "AAA") -> FrozenCandidateKey:
    return FrozenCandidateKey("RAW", "2026-01-02", symbol, f"fp-{symbol.lower()}")


def _baseline(candidate: FrozenCandidateKey) -> FrozenBaselineCandidate:
    return FrozenBaselineCandidate(
        candidate=candidate,
        observed_failure_codes=("GATE_A",),
        resolved_outcome=False,
        outcome_status="PENDING",
        realized_return_pct=None,
        realized_r=None,
        b5_present=True,
        b7_present=False,
        b10_present=False,
        dsi001_present=True,
    )


def _population(*candidates: FrozenCandidateKey) -> FrozenBaselinePopulation:
    ordered_keys = tuple(sorted(candidates))
    ordered = tuple(_baseline(candidate) for candidate in ordered_keys)
    return FrozenBaselinePopulation(
        candidates=ordered,
        raw_candidate_count=len(ordered),
        adjusted_candidate_count=0,
        raw_adjusted_identity_mismatch_count=len(ordered),
    )


def _section(
    section: FrozenInputSection,
    *,
    observed_on: str = "2026-01-02",
) -> FrozenInputSectionSnapshot:
    return FrozenInputSectionSnapshot.from_mapping(
        section=section,
        payload={"section": section.value},
        source_version="v1",
        observed_on=observed_on,
    )


def _snapshot(candidate: FrozenCandidateKey) -> FrozenCandidateInputSnapshot:
    return FrozenCandidateInputSnapshot.build(
        candidate=candidate,
        sections=tuple(_section(section) for section in FrozenInputSection),
    )


def test_missing_snapshots_are_explicitly_recorded() -> None:
    population = _population(_candidate("BBB"), _candidate("AAA"))

    audit = FrozenInputPopulationAuditor().audit(population=population)

    assert audit.candidate_count == 2
    assert audit.snapshot_present_count == 0
    assert audit.replay_ready_count == 0
    assert audit.incomplete_count == 2
    assert audit.invalid_count == 0
    assert audit.missing_snapshot_count == 2
    assert audit.population_replay_ready is False
    assert tuple(row.candidate.symbol for row in audit.rows) == ("AAA", "BBB")
    assert all(
        len(row.missing_sections) == len(FrozenInputSection) for row in audit.rows
    )


def test_complete_snapshots_make_population_ready() -> None:
    first = _candidate("AAA")
    second = _candidate("BBB")
    population = _population(first, second)

    audit = FrozenInputPopulationAuditor().audit(
        population=population,
        snapshots=(_snapshot(second), _snapshot(first)),
    )

    assert audit.snapshot_present_count == 2
    assert audit.replay_ready_count == 2
    assert audit.incomplete_count == 0
    assert audit.missing_snapshot_count == 0
    assert audit.population_replay_ready is True
    assert all(row.replay_ready for row in audit.rows)


def test_partial_snapshot_is_preserved_without_fabrication() -> None:
    candidate = _candidate()
    snapshot = FrozenCandidateInputSnapshot.build(
        candidate=candidate,
        sections=(_section(FrozenInputSection.SOURCE_LINEAGE),),
    )

    audit = FrozenInputPopulationAuditor().audit(
        population=_population(candidate),
        snapshots=(snapshot,),
    )

    row = audit.rows[0]
    assert row.snapshot_present is True
    assert row.present_sections == (FrozenInputSection.SOURCE_LINEAGE,)
    assert FrozenInputSection.CANDIDATE_FEATURES in row.missing_sections
    assert row.replay_ready is False
    assert audit.incomplete_count == 1


def test_extra_snapshot_candidate_fails_closed() -> None:
    population = _population(_candidate("AAA"))

    with pytest.raises(ValueError, match="extra candidates:1"):
        FrozenInputPopulationAuditor().audit(
            population=population,
            snapshots=(_snapshot(_candidate("EXTRA")),),
        )


def test_duplicate_snapshot_candidate_fails_closed() -> None:
    candidate = _candidate()
    snapshot = _snapshot(candidate)

    with pytest.raises(ValueError, match="duplicate frozen input snapshot"):
        FrozenInputPopulationAuditor().audit(
            population=_population(candidate),
            snapshots=(snapshot, snapshot),
        )


def test_export_is_deterministic(tmp_path: Path) -> None:
    candidate = _candidate()
    audit = FrozenInputPopulationAuditor().audit(
        population=_population(candidate),
        snapshots=(_snapshot(candidate),),
    )

    first = export_frozen_input_population_audit(audit, tmp_path / "first")
    second = export_frozen_input_population_audit(audit, tmp_path / "second")

    assert tuple(path.read_bytes() for path in first) == tuple(
        path.read_bytes() for path in second
    )
    with first[1].open(encoding="utf-8", newline="") as handle:
        summary = next(csv.DictReader(handle))
    assert summary["candidate_count"] == "1"
    assert summary["population_replay_ready"] == "True"
    assert summary["production_influence"] == "False"
