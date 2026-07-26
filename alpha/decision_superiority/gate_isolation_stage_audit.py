"""Deterministic source audit for DSI-002 frozen downstream stage replay."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from alpha.decision_superiority.gate_isolation_transitions import DownstreamStage


class StageReplayAvailability(StrEnum):
    """Whether one downstream stage can be replayed from signed evidence."""

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class FrozenStageAuditFinding:
    """One explicit stage-level replayability finding."""

    stage: DownstreamStage
    candidate_component: str
    required_inputs: tuple[str, ...]
    signed_inputs_present: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    point_in_time_safe: bool
    deterministic_replay_possible: bool
    availability: StageReplayAvailability
    rationale: str
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("stage audit must remain diagnostic-only")
        if not self.candidate_component.strip():
            raise ValueError("candidate_component cannot be empty")
        if not self.rationale.strip():
            raise ValueError("rationale cannot be empty")
        if tuple(sorted(set(self.required_inputs))) != self.required_inputs:
            raise ValueError("required_inputs must be unique and sorted")
        if tuple(sorted(set(self.signed_inputs_present))) != self.signed_inputs_present:
            raise ValueError("signed_inputs_present must be unique and sorted")
        if tuple(sorted(set(self.missing_inputs))) != self.missing_inputs:
            raise ValueError("missing_inputs must be unique and sorted")
        if set(self.signed_inputs_present) & set(self.missing_inputs):
            raise ValueError("present and missing inputs cannot overlap")
        if self.availability is StageReplayAvailability.AVAILABLE:
            if self.missing_inputs or not self.deterministic_replay_possible:
                raise ValueError("available stage cannot have missing replay inputs")
        if self.deterministic_replay_possible and not self.point_in_time_safe:
            raise ValueError("deterministic replay cannot be point-in-time unsafe")


@dataclass(frozen=True, slots=True)
class FrozenStageAuditReport:
    """Ordered frozen-stage replayability findings."""

    findings: tuple[FrozenStageAuditFinding, ...]
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("stage audit must remain diagnostic-only")
        stages = tuple(item.stage for item in self.findings)
        expected = (
            DownstreamStage.APPROVAL,
            DownstreamStage.PORTFOLIO_ELIGIBILITY,
            DownstreamStage.ENTRY_READINESS,
            DownstreamStage.TRADE_FORMATION,
            DownstreamStage.OUTCOME,
        )
        if stages != expected:
            raise ValueError("stage audit findings must use canonical stage order")

    @property
    def replay_ready(self) -> bool:
        """Whether every stage is available for deterministic frozen replay."""

        return all(
            item.availability is StageReplayAvailability.AVAILABLE
            for item in self.findings
        )


class FrozenStageSourceAuditor:
    """Audit replayability strictly against currently signed DSI-002 evidence."""

    def audit(self) -> FrozenStageAuditReport:
        """Return the governed current-state stage audit.

        This audit intentionally records components as candidates, not as verified
        adapters. A stage is unavailable until all frozen inputs and policy state are
        signed, point-in-time safe, and sufficient for deterministic recomputation.
        """

        return FrozenStageAuditReport(
            findings=(
                _finding(
                    stage=DownstreamStage.APPROVAL,
                    component="canonical institutional approval evaluator",
                    required=(
                        "candidate feature snapshot",
                        "frozen approval policy version",
                        "gate input lineage",
                        "point-in-time market context",
                    ),
                    present=("gate input lineage",),
                    rationale=(
                        "Signed ledgers preserve observed failures and decisions "
                        "but do not preserve the complete candidate feature "
                        "snapshot and frozen approval policy state required to "
                        "recompute approval."
                    ),
                ),
                _finding(
                    stage=DownstreamStage.PORTFOLIO_ELIGIBILITY,
                    component="canonical portfolio eligibility evaluator",
                    required=(
                        "candidate approval result",
                        "frozen portfolio holdings",
                        "frozen portfolio policy version",
                        "point-in-time capacity and exposure state",
                    ),
                    present=("candidate approval result",),
                    rationale=(
                        "The signed source set does not contain the complete frozen "
                        "portfolio book, exposure state, and portfolio-policy version."
                    ),
                ),
                _finding(
                    stage=DownstreamStage.ENTRY_READINESS,
                    component="canonical entry readiness evaluator",
                    required=(
                        "approved portfolio-eligible candidate",
                        "frozen entry policy version",
                        "point-in-time trigger inputs",
                        "point-in-time tradability state",
                    ),
                    present=("point-in-time trigger outcome",),
                    rationale=(
                        "Observed pending-entry outcomes are available, but the "
                        "signed inputs required to recompute the trigger under "
                        "the frozen entry policy are incomplete."
                    ),
                ),
                _finding(
                    stage=DownstreamStage.TRADE_FORMATION,
                    component="canonical trade formation evaluator",
                    required=(
                        "entry-ready candidate",
                        "frozen execution policy version",
                        "point-in-time liquidity and sizing inputs",
                        "portfolio cash and risk budget",
                    ),
                    present=(),
                    rationale=(
                        "The signed ledgers report observed trade-formation "
                        "outcomes but do not preserve the complete execution, "
                        "sizing, cash, liquidity, and risk-budget state needed "
                        "for counterfactual formation."
                    ),
                ),
                _finding(
                    stage=DownstreamStage.OUTCOME,
                    component="canonical completed-trade outcome binder",
                    required=(
                        "counterfactual formed trade identity",
                        "frozen exit policy version",
                        "point-in-time post-entry market path",
                        "signed completed-trade outcome",
                    ),
                    present=(
                        "point-in-time post-entry market path",
                        "signed completed-trade outcome",
                    ),
                    rationale=(
                        "Some observed outcomes exist, but no counterfactual "
                        "formed-trade identity or frozen exit-policy lineage "
                        "exists to bind those outcomes to a newly formed shadow "
                        "trade."
                    ),
                ),
            )
        )


def export_frozen_stage_audit(
    report: FrozenStageAuditReport,
    output: Path,
) -> tuple[Path, Path]:
    """Export deterministic CSV and Markdown audit artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "dsi002_frozen_stage_source_audit.csv"
    md_path = output / "dsi002_frozen_stage_source_audit.md"
    fieldnames = (
        "stage",
        "candidate_component",
        "required_inputs",
        "signed_inputs_present",
        "missing_inputs",
        "point_in_time_safe",
        "deterministic_replay_possible",
        "availability",
        "rationale",
        "production_influence",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for finding in report.findings:
            row = asdict(finding)
            row["stage"] = finding.stage.value
            row["availability"] = finding.availability.value
            row["required_inputs"] = "|".join(finding.required_inputs)
            row["signed_inputs_present"] = "|".join(finding.signed_inputs_present)
            row["missing_inputs"] = "|".join(finding.missing_inputs)
            writer.writerow(row)

    lines = [
        "# DSI-002 Frozen Stage Source Audit",
        "",
        f"Replay ready: **{str(report.replay_ready).lower()}**",
        "",
        "| Stage | Availability | Candidate component | Missing inputs |",
        "|---|---|---|---|",
    ]
    for finding in report.findings:
        lines.append(
            "| "
            f"{finding.stage.value} | {finding.availability.value} | "
            f"{finding.candidate_component} | "
            f"{'<br>'.join(finding.missing_inputs)} |"
        )
    lines.extend(("", "Production influence: **false**", ""))
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path


def _finding(
    *,
    stage: DownstreamStage,
    component: str,
    required: tuple[str, ...],
    present: tuple[str, ...],
    rationale: str,
) -> FrozenStageAuditFinding:
    required_sorted = tuple(sorted(required))
    present_sorted = tuple(sorted(present))
    missing = tuple(sorted(set(required_sorted) - set(present_sorted)))
    availability = (
        StageReplayAvailability.PARTIAL
        if present_sorted
        else StageReplayAvailability.UNAVAILABLE
    )
    return FrozenStageAuditFinding(
        stage=stage,
        candidate_component=component,
        required_inputs=required_sorted,
        signed_inputs_present=present_sorted,
        missing_inputs=missing,
        point_in_time_safe=True,
        deterministic_replay_possible=False,
        availability=availability,
        rationale=rationale,
    )


__all__ = [
    "FrozenStageAuditFinding",
    "FrozenStageAuditReport",
    "FrozenStageSourceAuditor",
    "StageReplayAvailability",
    "export_frozen_stage_audit",
]
