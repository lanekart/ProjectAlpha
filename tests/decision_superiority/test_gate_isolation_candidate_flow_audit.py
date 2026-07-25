from __future__ import annotations

import csv
from pathlib import Path

from alpha.decision_superiority.gate_isolation_candidate_flow_audit import (
    CandidateCreationFlowAuditor,
    CandidateFlowAvailability,
    export_candidate_flow_audit,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import FrozenInputSection


def test_audit_covers_every_section_deterministically() -> None:
    audit = CandidateCreationFlowAuditor().audit()

    assert tuple(item.section for item in audit.findings) == tuple(
        sorted(FrozenInputSection, key=lambda item: item.value)
    )
    assert audit.authoritative_method == "IntelligenceApplicationService.run"
    assert audit.capture_ready is False
    assert audit.production_influence is False


def test_capture_seam_precedes_recommendation_build() -> None:
    audit = CandidateCreationFlowAuditor().audit()

    assert "after IntelligenceInputSet construction" in audit.capture_seam
    assert "before recommendation engine build" in audit.capture_seam
    assert audit.recommendation_influence is False
    assert audit.approval_influence is False
    assert audit.portfolio_influence is False
    assert audit.execution_influence is False


def test_available_and_missing_sections_are_explicit() -> None:
    audit = CandidateCreationFlowAuditor().audit()
    by_section = {item.section: item for item in audit.findings}

    assert (
        by_section[FrozenInputSection.CANDIDATE_FEATURES].availability
        is CandidateFlowAvailability.AVAILABLE
    )
    assert (
        by_section[FrozenInputSection.EXECUTION_STATE].availability
        is CandidateFlowAvailability.UNAVAILABLE
    )
    assert (
        by_section[FrozenInputSection.OUTCOME_POLICY].availability
        is CandidateFlowAvailability.UNAVAILABLE
    )
    assert by_section[FrozenInputSection.PORTFOLIO_STATE].missing_inputs
    assert by_section[FrozenInputSection.SOURCE_LINEAGE].missing_inputs


def test_export_is_deterministic(tmp_path: Path) -> None:
    audit = CandidateCreationFlowAuditor().audit()

    first = export_candidate_flow_audit(audit, tmp_path / "first")
    second = export_candidate_flow_audit(audit, tmp_path / "second")

    assert tuple(path.read_bytes() for path in first) == tuple(
        path.read_bytes() for path in second
    )
    with first[1].open(encoding="utf-8", newline="") as handle:
        summary = next(csv.DictReader(handle))
    assert summary["capture_ready"] == "False"
    assert summary["production_influence"] == "False"
