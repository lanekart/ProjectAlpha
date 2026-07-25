"""Authoritative candidate-creation flow audit for DSI-002A capture integration."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from alpha.decision_superiority.gate_isolation_frozen_inputs import FrozenInputSection


class CandidateFlowAvailability(StrEnum):
    """Availability of a frozen-input section at the candidate boundary."""

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CandidateFlowFinding:
    """One section-level finding at the authoritative candidate boundary."""

    section: FrozenInputSection
    availability: CandidateFlowAvailability
    producer_path: str
    available_inputs: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not self.producer_path.strip():
            raise ValueError("producer_path cannot be empty")
        if not self.rationale.strip():
            raise ValueError("rationale cannot be empty")
        if tuple(sorted(set(self.available_inputs))) != self.available_inputs:
            raise ValueError("available_inputs must be unique and sorted")
        if tuple(sorted(set(self.missing_inputs))) != self.missing_inputs:
            raise ValueError("missing_inputs must be unique and sorted")


@dataclass(frozen=True, slots=True)
class CandidateFlowAudit:
    """Deterministic audit of the candidate immutability and capture seam."""

    authoritative_service_path: str
    authoritative_method: str
    capture_seam: str
    findings: tuple[CandidateFlowFinding, ...]
    capture_ready: bool
    recommendation_influence: bool = False
    approval_influence: bool = False
    portfolio_influence: bool = False
    execution_influence: bool = False
    production_influence: bool = False

    def __post_init__(self) -> None:
        if not self.authoritative_service_path.strip():
            raise ValueError("authoritative_service_path cannot be empty")
        if not self.authoritative_method.strip():
            raise ValueError("authoritative_method cannot be empty")
        if not self.capture_seam.strip():
            raise ValueError("capture_seam cannot be empty")
        ordered = tuple(sorted(self.findings, key=lambda item: item.section.value))
        if ordered != self.findings:
            raise ValueError("findings must be deterministically sorted")
        if {item.section for item in self.findings} != set(FrozenInputSection):
            raise ValueError("findings must cover every frozen-input section")
        if any(
            (
                self.recommendation_influence,
                self.approval_influence,
                self.portfolio_influence,
                self.execution_influence,
                self.production_influence,
            )
        ):
            raise ValueError("candidate-flow audit influence flags must remain false")


class CandidateCreationFlowAuditor:
    """Audit the current application flow without changing application behaviour."""

    def audit(self) -> CandidateFlowAudit:
        """Return the governed default audit for the current application seam."""

        findings = tuple(
            sorted(
                (
                    CandidateFlowFinding(
                        section=FrozenInputSection.CANDIDATE_FEATURES,
                        availability=CandidateFlowAvailability.AVAILABLE,
                        producer_path="alpha/application/intelligence_inputs.py",
                        available_inputs=(
                            "allocation portfolio context",
                            "market intelligence inputs",
                            "recommendation candidates",
                            "recommendation portfolio context",
                        ),
                        missing_inputs=(
                            "explicit feature-computation version",
                            "source-level feature hashes",
                        ),
                        rationale=(
                            "IntelligenceInputSet is the canonical engine-ready input seam, "
                            "but version and source hashes are not yet emitted."
                        ),
                    ),
                    CandidateFlowFinding(
                        section=FrozenInputSection.APPROVAL_POLICY,
                        availability=CandidateFlowAvailability.PARTIAL,
                        producer_path="alpha/application/intelligence.py",
                        available_inputs=("recommendation engine instance",),
                        missing_inputs=(
                            "approval policy payload",
                            "approval policy version",
                            "threshold provenance",
                        ),
                        rationale=(
                            "The application service invokes the recommendation engine, but "
                            "does not preserve a serialised frozen approval policy."
                        ),
                    ),
                    CandidateFlowFinding(
                        section=FrozenInputSection.PORTFOLIO_STATE,
                        availability=CandidateFlowAvailability.AVAILABLE,
                        producer_path="alpha/application/intelligence_inputs.py",
                        available_inputs=(
                            "allocation portfolio context",
                            "recommendation portfolio context",
                        ),
                        missing_inputs=(
                            "append-only portfolio-state identity",
                            "portfolio-state version",
                        ),
                        rationale=(
                            "Both portfolio contexts are available before recommendation and "
                            "allocation, but are not persisted as immutable snapshots."
                        ),
                    ),
                    CandidateFlowFinding(
                        section=FrozenInputSection.ENTRY_POLICY,
                        availability=CandidateFlowAvailability.PARTIAL,
                        producer_path="alpha/recommendation_intelligence/models.py",
                        available_inputs=("candidate entry and trigger fields",),
                        missing_inputs=(
                            "entry policy payload",
                            "entry policy version",
                            "trigger source hashes",
                        ),
                        rationale=(
                            "Candidate models carry entry semantics, but the governing policy "
                            "and exact source lineage are not captured."
                        ),
                    ),
                    CandidateFlowFinding(
                        section=FrozenInputSection.EXECUTION_STATE,
                        availability=CandidateFlowAvailability.UNAVAILABLE,
                        producer_path="alpha/application/intelligence.py",
                        available_inputs=(),
                        missing_inputs=(
                            "cash and execution queue state",
                            "fill and participation constraints",
                            "sizing state",
                        ),
                        rationale=(
                            "The intelligence workflow constructs recommendations and an "
                            "allocation plan; it does not expose an execution-state snapshot."
                        ),
                    ),
                    CandidateFlowFinding(
                        section=FrozenInputSection.OUTCOME_POLICY,
                        availability=CandidateFlowAvailability.UNAVAILABLE,
                        producer_path="alpha/application/intelligence.py",
                        available_inputs=(),
                        missing_inputs=(
                            "exit policy payload",
                            "formed trade identity",
                            "outcome policy version",
                        ),
                        rationale=(
                            "Outcome policy is downstream of candidate creation and is not "
                            "available in the current application transaction."
                        ),
                    ),
                    CandidateFlowFinding(
                        section=FrozenInputSection.SOURCE_LINEAGE,
                        availability=CandidateFlowAvailability.PARTIAL,
                        producer_path="alpha/application/intelligence_inputs.py",
                        available_inputs=("observed_on", "symbol identity"),
                        missing_inputs=(
                            "input artifact hashes",
                            "provider and dataset versions",
                            "source path lineage",
                        ),
                        rationale=(
                            "Candidate identity and observation date exist, but complete input "
                            "artifact lineage is not emitted by the current builder."
                        ),
                    ),
                ),
                key=lambda item: item.section.value,
            )
        )
        return CandidateFlowAudit(
            authoritative_service_path="alpha/application/intelligence.py",
            authoritative_method="IntelligenceApplicationService.run",
            capture_seam=(
                "after IntelligenceInputSet construction and before recommendation engine build"
            ),
            findings=findings,
            capture_ready=all(
                item.availability is CandidateFlowAvailability.AVAILABLE
                and not item.missing_inputs
                for item in findings
            ),
        )


def export_candidate_flow_audit(
    audit: CandidateFlowAudit,
    output: Path,
) -> tuple[Path, Path]:
    """Export deterministic detail and summary CSV artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    detail = output / "dsi002_candidate_creation_flow_audit.csv"
    summary = output / "dsi002_candidate_creation_flow_summary.csv"
    with detail.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "section",
                "availability",
                "producer_path",
                "available_inputs",
                "missing_inputs",
                "rationale",
            ),
        )
        writer.writeheader()
        for item in audit.findings:
            writer.writerow(
                {
                    "section": item.section.value,
                    "availability": item.availability.value,
                    "producer_path": item.producer_path,
                    "available_inputs": "|".join(item.available_inputs),
                    "missing_inputs": "|".join(item.missing_inputs),
                    "rationale": item.rationale,
                }
            )
    with summary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "authoritative_service_path",
                "authoritative_method",
                "capture_seam",
                "capture_ready",
                "recommendation_influence",
                "approval_influence",
                "portfolio_influence",
                "execution_influence",
                "production_influence",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "authoritative_service_path": audit.authoritative_service_path,
                "authoritative_method": audit.authoritative_method,
                "capture_seam": audit.capture_seam,
                "capture_ready": audit.capture_ready,
                "recommendation_influence": audit.recommendation_influence,
                "approval_influence": audit.approval_influence,
                "portfolio_influence": audit.portfolio_influence,
                "execution_influence": audit.execution_influence,
                "production_influence": audit.production_influence,
            }
        )
    return detail, summary


__all__ = [
    "CandidateCreationFlowAuditor",
    "CandidateFlowAudit",
    "CandidateFlowAvailability",
    "CandidateFlowFinding",
    "export_candidate_flow_audit",
]
