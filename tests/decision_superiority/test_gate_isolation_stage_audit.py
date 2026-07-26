from __future__ import annotations

from pathlib import Path

import pytest

from alpha.decision_superiority.gate_isolation_stage_audit import (
    FrozenStageAuditFinding,
    FrozenStageAuditReport,
    FrozenStageSourceAuditor,
    StageReplayAvailability,
    export_frozen_stage_audit,
)
from alpha.decision_superiority.gate_isolation_transitions import DownstreamStage


def test_current_signed_evidence_is_not_stage_replay_ready() -> None:
    report = FrozenStageSourceAuditor().audit()

    assert report.replay_ready is False
    assert tuple(item.stage for item in report.findings) == (
        DownstreamStage.APPROVAL,
        DownstreamStage.PORTFOLIO_ELIGIBILITY,
        DownstreamStage.ENTRY_READINESS,
        DownstreamStage.TRADE_FORMATION,
        DownstreamStage.OUTCOME,
    )
    assert all(not item.deterministic_replay_possible for item in report.findings)
    assert all(item.production_influence is False for item in report.findings)
    assert report.findings[3].availability is StageReplayAvailability.UNAVAILABLE
    assert report.findings[0].availability is StageReplayAvailability.PARTIAL


def test_audit_exports_are_deterministic(tmp_path: Path) -> None:
    report = FrozenStageSourceAuditor().audit()

    first = export_frozen_stage_audit(report, tmp_path / "first")
    second = export_frozen_stage_audit(report, tmp_path / "second")

    assert tuple(path.read_bytes() for path in first) == tuple(
        path.read_bytes() for path in second
    )
    csv_text = first[0].read_text(encoding="utf-8")
    markdown = first[1].read_text(encoding="utf-8")
    assert "APPROVAL" in csv_text
    assert "counterfactual formed trade identity" in csv_text
    assert "Replay ready: **false**" in markdown
    assert "Production influence: **false**" in markdown


def test_available_finding_rejects_missing_inputs() -> None:
    with pytest.raises(ValueError, match="available stage"):
        FrozenStageAuditFinding(
            stage=DownstreamStage.APPROVAL,
            candidate_component="candidate",
            required_inputs=("a",),
            signed_inputs_present=(),
            missing_inputs=("a",),
            point_in_time_safe=True,
            deterministic_replay_possible=False,
            availability=StageReplayAvailability.AVAILABLE,
            rationale="not actually available",
        )


def test_report_rejects_noncanonical_stage_order() -> None:
    finding = FrozenStageAuditFinding(
        stage=DownstreamStage.APPROVAL,
        candidate_component="candidate",
        required_inputs=("a",),
        signed_inputs_present=(),
        missing_inputs=("a",),
        point_in_time_safe=True,
        deterministic_replay_possible=False,
        availability=StageReplayAvailability.UNAVAILABLE,
        rationale="unavailable",
    )

    with pytest.raises(ValueError, match="canonical stage order"):
        FrozenStageAuditReport(findings=(finding,))
