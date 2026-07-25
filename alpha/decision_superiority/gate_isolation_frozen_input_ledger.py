"""Population-level frozen-input preservation ledger for DSI-002A."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from alpha.decision_superiority.gate_isolation_baseline import (
    FrozenBaselinePopulation,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenCandidateInputSnapshot,
    FrozenInputContractValidator,
    FrozenInputReadiness,
    FrozenInputSection,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey


@dataclass(frozen=True, slots=True)
class FrozenInputLedgerRow:
    """One candidate-level frozen-input preservation result."""

    candidate: FrozenCandidateKey
    snapshot_present: bool
    snapshot_sha256: str
    readiness: FrozenInputReadiness
    present_sections: tuple[FrozenInputSection, ...]
    missing_sections: tuple[FrozenInputSection, ...]
    invalid_sections: tuple[FrozenInputSection, ...]
    replay_ready: bool
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("frozen input ledger must remain diagnostic-only")
        for values, name in (
            (self.present_sections, "present_sections"),
            (self.missing_sections, "missing_sections"),
            (self.invalid_sections, "invalid_sections"),
        ):
            if tuple(sorted(set(values), key=lambda item: item.value)) != values:
                raise ValueError(f"{name} must be unique and sorted")
        if self.snapshot_present and not self.snapshot_sha256.strip():
            raise ValueError("present snapshot requires snapshot_sha256")
        if not self.snapshot_present and self.snapshot_sha256:
            raise ValueError("absent snapshot cannot have snapshot_sha256")
        if self.replay_ready and self.readiness is not FrozenInputReadiness.READY:
            raise ValueError("replay_ready requires READY readiness")


@dataclass(frozen=True, slots=True)
class FrozenInputPopulationAudit:
    """Deterministic population audit for frozen-input preservation."""

    rows: tuple[FrozenInputLedgerRow, ...]
    candidate_count: int
    snapshot_present_count: int
    replay_ready_count: int
    incomplete_count: int
    invalid_count: int
    missing_snapshot_count: int
    population_replay_ready: bool
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("frozen input audit must remain diagnostic-only")
        keys = tuple(row.candidate for row in self.rows)
        if keys != tuple(sorted(keys)):
            raise ValueError("frozen input ledger rows must be sorted")
        if len(set(keys)) != len(keys):
            raise ValueError("frozen input ledger candidates must be unique")
        if self.candidate_count != len(self.rows):
            raise ValueError("candidate_count must equal ledger row count")
        if self.population_replay_ready != (
            self.candidate_count > 0 and self.replay_ready_count == self.candidate_count
        ):
            raise ValueError("population_replay_ready disagrees with counts")


class FrozenInputPopulationAuditor:
    """Audit preserved snapshots against the canonical baseline population."""

    def audit(
        self,
        *,
        population: FrozenBaselinePopulation,
        snapshots: tuple[FrozenCandidateInputSnapshot, ...] = (),
    ) -> FrozenInputPopulationAudit:
        indexed = _index_snapshots(snapshots)
        canonical = {item.candidate for item in population.candidates}
        extra = sorted(set(indexed) - canonical)
        if extra:
            raise ValueError(f"frozen input snapshots contain extra candidates:{len(extra)}")

        validator = FrozenInputContractValidator()
        rows: list[FrozenInputLedgerRow] = []
        required = tuple(sorted(FrozenInputSection, key=lambda item: item.value))
        for candidate in sorted(canonical):
            snapshot = indexed.get(candidate)
            if snapshot is None:
                rows.append(
                    FrozenInputLedgerRow(
                        candidate=candidate,
                        snapshot_present=False,
                        snapshot_sha256="",
                        readiness=FrozenInputReadiness.INCOMPLETE,
                        present_sections=(),
                        missing_sections=required,
                        invalid_sections=(),
                        replay_ready=False,
                    )
                )
                continue
            validation = validator.validate(snapshot)
            present = tuple(
                sorted(
                    (section.section for section in snapshot.sections),
                    key=lambda item: item.value,
                )
            )
            rows.append(
                FrozenInputLedgerRow(
                    candidate=candidate,
                    snapshot_present=True,
                    snapshot_sha256=snapshot.snapshot_sha256,
                    readiness=validation.readiness,
                    present_sections=present,
                    missing_sections=validation.missing_sections,
                    invalid_sections=validation.invalid_sections,
                    replay_ready=validation.replay_ready,
                )
            )

        ordered = tuple(rows)
        ready = sum(row.replay_ready for row in ordered)
        incomplete = sum(
            row.readiness is FrozenInputReadiness.INCOMPLETE for row in ordered
        )
        invalid = sum(
            row.readiness
            in {
                FrozenInputReadiness.HASH_MISMATCH,
                FrozenInputReadiness.IDENTITY_MISMATCH,
                FrozenInputReadiness.POST_OBSERVATION_INPUT,
            }
            for row in ordered
        )
        missing_snapshots = sum(not row.snapshot_present for row in ordered)
        return FrozenInputPopulationAudit(
            rows=ordered,
            candidate_count=len(ordered),
            snapshot_present_count=sum(row.snapshot_present for row in ordered),
            replay_ready_count=ready,
            incomplete_count=incomplete,
            invalid_count=invalid,
            missing_snapshot_count=missing_snapshots,
            population_replay_ready=bool(ordered) and ready == len(ordered),
        )


def export_frozen_input_population_audit(
    audit: FrozenInputPopulationAudit,
    output: Path,
) -> tuple[Path, Path]:
    """Export deterministic candidate ledger and population summary CSVs."""

    output.mkdir(parents=True, exist_ok=True)
    ledger_path = output / "dsi002_frozen_input_preservation_ledger.csv"
    summary_path = output / "dsi002_frozen_input_completeness_summary.csv"

    fields = (
        "price_view",
        "observed_on",
        "symbol",
        "input_fingerprint",
        "snapshot_present",
        "snapshot_sha256",
        "readiness",
        "present_sections",
        "missing_sections",
        "invalid_sections",
        "replay_ready",
        "production_influence",
    )
    with ledger_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in audit.rows:
            writer.writerow(
                {
                    "price_view": row.candidate.price_view,
                    "observed_on": row.candidate.observed_on,
                    "symbol": row.candidate.symbol,
                    "input_fingerprint": row.candidate.input_fingerprint,
                    "snapshot_present": str(row.snapshot_present).lower(),
                    "snapshot_sha256": row.snapshot_sha256,
                    "readiness": row.readiness.value,
                    "present_sections": "|".join(
                        section.value for section in row.present_sections
                    ),
                    "missing_sections": "|".join(
                        section.value for section in row.missing_sections
                    ),
                    "invalid_sections": "|".join(
                        section.value for section in row.invalid_sections
                    ),
                    "replay_ready": str(row.replay_ready).lower(),
                    "production_influence": "false",
                }
            )

    summary = {
        "candidate_count": audit.candidate_count,
        "snapshot_present_count": audit.snapshot_present_count,
        "replay_ready_count": audit.replay_ready_count,
        "incomplete_count": audit.incomplete_count,
        "invalid_count": audit.invalid_count,
        "missing_snapshot_count": audit.missing_snapshot_count,
        "population_replay_ready": audit.population_replay_ready,
        "production_influence": False,
    }
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(summary))
        writer.writeheader()
        writer.writerow(summary)

    return ledger_path, summary_path


def _index_snapshots(
    snapshots: tuple[FrozenCandidateInputSnapshot, ...],
) -> dict[FrozenCandidateKey, FrozenCandidateInputSnapshot]:
    result: dict[FrozenCandidateKey, FrozenCandidateInputSnapshot] = {}
    for snapshot in snapshots:
        if snapshot.candidate in result:
            raise ValueError("duplicate frozen input snapshot candidate")
        result[snapshot.candidate] = snapshot
    return result


__all__ = [
    "FrozenInputLedgerRow",
    "FrozenInputPopulationAudit",
    "FrozenInputPopulationAuditor",
    "export_frozen_input_population_audit",
]
