"""Historical backfill feasibility planning for DSI-002A frozen inputs."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputSection,
)


class FrozenInputBackfillMode(StrEnum):
    """Permitted acquisition mode for one frozen-input section."""

    HISTORICAL_RECONSTRUCTION = "HISTORICAL_RECONSTRUCTION"
    FORWARD_CAPTURE_ONLY = "FORWARD_CAPTURE_ONLY"
    HYBRID = "HYBRID"


class FrozenInputBackfillReadiness(StrEnum):
    """Governed readiness for historical backfill of one section."""

    READY = "READY_FOR_HISTORICAL_BACKFILL"
    PARTIAL = "PARTIAL_HISTORICAL_BACKFILL"
    UNAVAILABLE = "HISTORICAL_BACKFILL_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class FrozenInputBackfillFinding:
    """One section-level backfill decision and evidence gap."""

    section: FrozenInputSection
    mode: FrozenInputBackfillMode
    readiness: FrozenInputBackfillReadiness
    reconstructable_inputs: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    required_sources: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not self.rationale.strip():
            raise ValueError("rationale cannot be empty")
        if (
            tuple(sorted(set(self.reconstructable_inputs)))
            != self.reconstructable_inputs
        ):
            raise ValueError("reconstructable_inputs must be unique and sorted")
        if tuple(sorted(set(self.missing_inputs))) != self.missing_inputs:
            raise ValueError("missing_inputs must be unique and sorted")
        if tuple(sorted(set(self.required_sources))) != self.required_sources:
            raise ValueError("required_sources must be unique and sorted")


@dataclass(frozen=True, slots=True)
class FrozenInputBackfillPlan:
    """Deterministic DSI-002A historical backfill plan."""

    findings: tuple[FrozenInputBackfillFinding, ...]
    historical_ready_section_count: int
    partial_section_count: int
    forward_only_section_count: int
    complete_historical_backfill_possible: bool
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("backfill planning must remain diagnostic-only")
        expected = tuple(sorted(self.findings, key=lambda item: item.section.value))
        if expected != self.findings:
            raise ValueError("findings must be deterministically sorted")
        if len({item.section for item in self.findings}) != len(self.findings):
            raise ValueError("findings must contain unique sections")
        if {item.section for item in self.findings} != set(FrozenInputSection):
            raise ValueError("findings must cover every frozen-input section")


class FrozenInputBackfillPlanner:
    """Classify which frozen inputs may be backfilled without fabrication."""

    def plan(self) -> FrozenInputBackfillPlan:
        """Return the governed default plan for the current signed evidence boundary."""

        findings = tuple(
            sorted(
                (
                    FrozenInputBackfillFinding(
                        section=FrozenInputSection.CANDIDATE_FEATURES,
                        mode=FrozenInputBackfillMode.HYBRID,
                        readiness=FrozenInputBackfillReadiness.PARTIAL,
                        reconstructable_inputs=(
                            "candidate identity",
                            "failure-code lineage",
                            "historical daily candles",
                        ),
                        missing_inputs=(
                            "complete historical feature vector",
                            "feature-computation version",
                            "source-level feature lineage",
                        ),
                        required_sources=(
                            "B5 candidate ledger",
                            "DSI-001 candidate ledger",
                            "historical truth warehouse",
                        ),
                        rationale=(
                            "Some market-derived features may be recomputed from "
                            "point-in-time history, but the exact original "
                            "feature vector and computation version were not "
                            "preserved."
                        ),
                    ),
                    FrozenInputBackfillFinding(
                        section=FrozenInputSection.APPROVAL_POLICY,
                        mode=FrozenInputBackfillMode.HYBRID,
                        readiness=FrozenInputBackfillReadiness.PARTIAL,
                        reconstructable_inputs=(
                            "observed gate failures",
                            "recorded approval outcome",
                        ),
                        missing_inputs=(
                            "exact historical approval policy payload",
                            "policy dependency versions",
                            "threshold provenance",
                        ),
                        required_sources=(
                            "B5 gate ledger",
                            "policy registry history",
                        ),
                        rationale=(
                            "Observed approval decisions are available, but the "
                            "exact historical policy state required for "
                            "counterfactual recomputation is incomplete."
                        ),
                    ),
                    FrozenInputBackfillFinding(
                        section=FrozenInputSection.PORTFOLIO_STATE,
                        mode=FrozenInputBackfillMode.FORWARD_CAPTURE_ONLY,
                        readiness=FrozenInputBackfillReadiness.UNAVAILABLE,
                        reconstructable_inputs=(),
                        missing_inputs=(
                            "cash balance",
                            "concurrent holdings",
                            "portfolio heat",
                            "sector exposure",
                        ),
                        required_sources=("append-only portfolio state snapshots",),
                        rationale=(
                            "The signed research ledgers do not preserve "
                            "historical portfolio state; reconstructing it now "
                            "would require assumptions and would not be "
                            "governed."
                        ),
                    ),
                    FrozenInputBackfillFinding(
                        section=FrozenInputSection.ENTRY_POLICY,
                        mode=FrozenInputBackfillMode.HYBRID,
                        readiness=FrozenInputBackfillReadiness.PARTIAL,
                        reconstructable_inputs=(
                            "historical daily candles",
                            "observed entry blocker",
                        ),
                        missing_inputs=(
                            "exact historical entry policy",
                            "intraday trigger evidence",
                            "trigger computation version",
                        ),
                        required_sources=(
                            "B7 outcome ledger",
                            "historical truth warehouse",
                            "policy registry history",
                        ),
                        rationale=(
                            "Daily history may support limited trigger "
                            "reconstruction, but exact historical entry "
                            "semantics and intraday evidence are incomplete."
                        ),
                    ),
                    FrozenInputBackfillFinding(
                        section=FrozenInputSection.EXECUTION_STATE,
                        mode=FrozenInputBackfillMode.FORWARD_CAPTURE_ONLY,
                        readiness=FrozenInputBackfillReadiness.UNAVAILABLE,
                        reconstructable_inputs=(),
                        missing_inputs=(
                            "available cash",
                            "execution queue state",
                            "liquidity and participation constraints",
                            "sizing and fill state",
                        ),
                        required_sources=("append-only execution state snapshots",),
                        rationale=(
                            "Execution state was not preserved at observation "
                            "time and cannot be recreated from end-of-day "
                            "decision ledgers without fabrication."
                        ),
                    ),
                    FrozenInputBackfillFinding(
                        section=FrozenInputSection.OUTCOME_POLICY,
                        mode=FrozenInputBackfillMode.HYBRID,
                        readiness=FrozenInputBackfillReadiness.PARTIAL,
                        reconstructable_inputs=(
                            "historical daily candles",
                            "observed outcome status",
                            "realized return where recorded",
                        ),
                        missing_inputs=(
                            "counterfactual trade identity",
                            "exact frozen exit policy",
                        ),
                        required_sources=(
                            "B7 outcome ledger",
                            "historical truth warehouse",
                            "policy registry history",
                        ),
                        rationale=(
                            "Observed outcomes can be retained, but they cannot "
                            "be rebound to a new counterfactual trade without "
                            "its exact identity and exit policy."
                        ),
                    ),
                    FrozenInputBackfillFinding(
                        section=FrozenInputSection.SOURCE_LINEAGE,
                        mode=FrozenInputBackfillMode.HISTORICAL_RECONSTRUCTION,
                        readiness=FrozenInputBackfillReadiness.READY,
                        reconstructable_inputs=(
                            "artifact hashes",
                            "candidate identity",
                            "certificate lineage",
                            "source file paths",
                        ),
                        missing_inputs=(),
                        required_sources=(
                            "B10 certificate",
                            "B5 certificate",
                            "B7 certificate",
                            "DSI-001 certificate",
                        ),
                        rationale=(
                            "Signed certificates and bound artifact hashes permit "
                            "deterministic historical reconstruction of the "
                            "current source-lineage boundary."
                        ),
                    ),
                ),
                key=lambda item: item.section.value,
            )
        )
        ready = sum(
            item.readiness is FrozenInputBackfillReadiness.READY for item in findings
        )
        partial = sum(
            item.readiness is FrozenInputBackfillReadiness.PARTIAL for item in findings
        )
        forward_only = sum(
            item.mode is FrozenInputBackfillMode.FORWARD_CAPTURE_ONLY
            for item in findings
        )
        return FrozenInputBackfillPlan(
            findings=findings,
            historical_ready_section_count=ready,
            partial_section_count=partial,
            forward_only_section_count=forward_only,
            complete_historical_backfill_possible=all(
                item.readiness is FrozenInputBackfillReadiness.READY
                for item in findings
            ),
        )


def export_frozen_input_backfill_plan(
    plan: FrozenInputBackfillPlan,
    output: Path,
) -> tuple[Path, Path]:
    """Export deterministic section and summary CSV artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    detail = output / "dsi002_frozen_input_backfill_plan.csv"
    summary = output / "dsi002_frozen_input_backfill_summary.csv"
    with detail.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "section",
                "mode",
                "readiness",
                "reconstructable_inputs",
                "missing_inputs",
                "required_sources",
                "rationale",
            ),
        )
        writer.writeheader()
        for item in plan.findings:
            writer.writerow(
                {
                    "section": item.section.value,
                    "mode": item.mode.value,
                    "readiness": item.readiness.value,
                    "reconstructable_inputs": "|".join(item.reconstructable_inputs),
                    "missing_inputs": "|".join(item.missing_inputs),
                    "required_sources": "|".join(item.required_sources),
                    "rationale": item.rationale,
                }
            )
    with summary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "historical_ready_section_count",
                "partial_section_count",
                "forward_only_section_count",
                "complete_historical_backfill_possible",
                "production_influence",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "historical_ready_section_count": plan.historical_ready_section_count,
                "partial_section_count": plan.partial_section_count,
                "forward_only_section_count": plan.forward_only_section_count,
                "complete_historical_backfill_possible": (
                    plan.complete_historical_backfill_possible
                ),
                "production_influence": plan.production_influence,
            }
        )
    return detail, summary


__all__ = [
    "FrozenInputBackfillFinding",
    "FrozenInputBackfillMode",
    "FrozenInputBackfillPlan",
    "FrozenInputBackfillPlanner",
    "FrozenInputBackfillReadiness",
    "export_frozen_input_backfill_plan",
]
