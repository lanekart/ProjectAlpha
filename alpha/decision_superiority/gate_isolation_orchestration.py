"""Signed DSI-002 orchestration for deterministic real-data dry runs."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from alpha.decision_superiority.gate_isolation_arms import GateIsolationArmBuilder
from alpha.decision_superiority.gate_isolation_baseline import (
    FrozenBaselinePopulation,
    FrozenBaselineReconstructor,
    FrozenBaselineSourcePaths,
)
from alpha.decision_superiority.gate_isolation_models import (
    CounterfactualArmType,
    FrozenCandidateKey,
)
from alpha.decision_superiority.gate_isolation_source_contract import (
    GateIsolationSourceContractVerifier,
    GateIsolationSourcePaths,
    VerifiedGateIsolationSources,
)
from alpha.decision_superiority.gate_isolation_transitions import (
    BaselineDownstreamState,
    GateIsolationTransition,
    GateIsolationTransitionEngine,
)


@dataclass(frozen=True, slots=True)
class GateIsolationDryRunSummary:
    """Deterministic non-economic checkpoint metrics for DSI-002."""

    candidate_count: int
    single_gate_arm_count: int
    effective_single_gate_arm_count: int
    minimal_remediation_arm_count: int
    newly_approved_count: int
    newly_portfolio_eligible_count: int
    newly_entry_ready_count: int
    newly_trade_formed_count: int
    resolved_outcome_transition_count: int
    unavailable_outcome_transition_count: int
    raw_adjusted_identity_mismatch_count: int
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("DSI-002 dry runs must remain diagnostic-only")
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name != "production_influence" and value < 0:
                raise ValueError(f"{item.name} cannot be negative")


@dataclass(frozen=True, slots=True)
class GateIsolationDryRunResult:
    """Signed source evidence, baseline population, transitions, and summary."""

    verified_sources: VerifiedGateIsolationSources
    baseline_population: FrozenBaselinePopulation
    transitions: tuple[GateIsolationTransition, ...]
    summary: GateIsolationDryRunSummary


class GateIsolationDryRunOrchestrator:
    """Execute the current DSI-002 stack without economic interpretation."""

    def run(
        self,
        *,
        source_paths: GateIsolationSourcePaths,
        baseline_paths: FrozenBaselineSourcePaths,
        max_remediation_set_size: int = 8,
    ) -> GateIsolationDryRunResult:
        verified = GateIsolationSourceContractVerifier().verify(source_paths)
        population = FrozenBaselineReconstructor().reconstruct(baseline_paths)
        downstream = _baseline_states(baseline_paths.b10_decision_ledger)
        builder = GateIsolationArmBuilder(
            max_remediation_set_size=max_remediation_set_size
        )
        engine = GateIsolationTransitionEngine()

        transitions: list[GateIsolationTransition] = []
        for candidate in population.candidates:
            state = downstream.get(candidate.candidate)
            if state is None:
                raise ValueError("B10 downstream state missing for baseline candidate")
            batch = builder.build(
                candidate=candidate.candidate,
                observed_failure_codes=candidate.observed_failure_codes,
            )
            arms = (
                batch.baseline,
                *batch.single_gate_arms,
                *batch.minimal_remediation_arms,
            )
            transitions.extend(
                engine.replay(candidate=candidate, arm=arm, baseline=state)
                for arm in arms
            )

        ordered = tuple(sorted(transitions, key=lambda item: item.arm.arm_id))
        summary = _summarize(population, ordered)
        return GateIsolationDryRunResult(
            verified_sources=verified,
            baseline_population=population,
            transitions=ordered,
            summary=summary,
        )


def export_gate_isolation_dry_run(
    result: GateIsolationDryRunResult,
    output: Path,
) -> tuple[Path, Path]:
    """Export deterministic transition and summary CSVs for checkpoint review."""

    output.mkdir(parents=True, exist_ok=True)
    transition_path = output / "dsi002_dry_run_transition_ledger.csv"
    summary_path = output / "dsi002_dry_run_summary.csv"
    transition_fields = (
        "arm_id",
        "arm_type",
        "price_view",
        "observed_on",
        "symbol",
        "input_fingerprint",
        "passed_gate_codes",
        "remaining_failure_codes",
        "semantic_status",
        "first_changed_stage",
        "newly_approved",
        "newly_portfolio_eligible",
        "newly_entry_ready",
        "newly_trade_formed",
        "outcome_available",
        "production_influence",
    )
    with transition_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=transition_fields)
        writer.writeheader()
        for item in result.transitions:
            writer.writerow(
                {
                    "arm_id": item.arm.arm_id,
                    "arm_type": item.arm.arm_type.value,
                    "price_view": item.arm.candidate.price_view,
                    "observed_on": item.arm.candidate.observed_on,
                    "symbol": item.arm.candidate.symbol,
                    "input_fingerprint": item.arm.candidate.input_fingerprint,
                    "passed_gate_codes": "|".join(item.arm.passed_gate_codes),
                    "remaining_failure_codes": "|".join(
                        item.arm.remaining_failure_codes
                    ),
                    "semantic_status": item.semantic_status.value,
                    "first_changed_stage": item.first_changed_stage.value,
                    "newly_approved": str(item.newly_approved).lower(),
                    "newly_portfolio_eligible": str(
                        item.newly_portfolio_eligible
                    ).lower(),
                    "newly_entry_ready": str(item.newly_entry_ready).lower(),
                    "newly_trade_formed": str(item.newly_trade_formed).lower(),
                    "outcome_available": str(
                        item.counterfactual.outcome_available
                    ).lower(),
                    "production_influence": "false",
                }
            )
    summary_row = asdict(result.summary)
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(summary_row))
        writer.writeheader()
        writer.writerow(summary_row)
    return transition_path, summary_path


def _summarize(
    population: FrozenBaselinePopulation,
    transitions: tuple[GateIsolationTransition, ...],
) -> GateIsolationDryRunSummary:
    single = tuple(
        item
        for item in transitions
        if item.arm.arm_type is CounterfactualArmType.SINGLE_GATE_PASS
    )
    minimal = tuple(
        item
        for item in transitions
        if item.arm.arm_type is CounterfactualArmType.MINIMAL_REMEDIATION_SET
    )
    changed = tuple(item for item in transitions if item.newly_approved)
    return GateIsolationDryRunSummary(
        candidate_count=len(population.candidates),
        single_gate_arm_count=len(single),
        effective_single_gate_arm_count=sum(item.newly_approved for item in single),
        minimal_remediation_arm_count=len(minimal),
        newly_approved_count=sum(item.newly_approved for item in transitions),
        newly_portfolio_eligible_count=sum(
            item.newly_portfolio_eligible for item in transitions
        ),
        newly_entry_ready_count=sum(item.newly_entry_ready for item in transitions),
        newly_trade_formed_count=sum(item.newly_trade_formed for item in transitions),
        resolved_outcome_transition_count=sum(
            item.counterfactual.outcome_available for item in changed
        ),
        unavailable_outcome_transition_count=sum(
            not item.counterfactual.outcome_available for item in changed
        ),
        raw_adjusted_identity_mismatch_count=(
            population.raw_adjusted_identity_mismatch_count
        ),
    )


def _baseline_states(
    path: Path,
) -> dict[FrozenCandidateKey, BaselineDownstreamState]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = tuple(dict(row) for row in csv.DictReader(handle))
    result: dict[FrozenCandidateKey, BaselineDownstreamState] = {}
    for row in rows:
        key = FrozenCandidateKey(
            price_view=str(row.get("price_view") or "").strip().upper(),
            observed_on=str(row.get("observed_on") or "").strip(),
            symbol=str(row.get("symbol") or "").strip().upper(),
            input_fingerprint=str(
                row.get("input_fingerprint") or row.get("fingerprint_key") or ""
            ).strip(),
        )
        if key in result:
            raise ValueError("duplicate B10 downstream candidate identity")
        approved = _truthy(row.get("default_accepted") or row.get("approved"))
        portfolio = _truthy(
            row.get("default_portfolio_eligible")
            or row.get("portfolio_eligible")
        )
        entry = _truthy(row.get("default_entry_ready") or row.get("entry_ready"))
        trade = _truthy(row.get("default_trade_formed") or row.get("trade_formed"))
        outcome = _truthy(
            row.get("default_outcome_available") or row.get("outcome_available")
        )
        result[key] = BaselineDownstreamState(
            approved=approved,
            portfolio_eligible=portfolio,
            entry_ready=entry,
            trade_formed=trade,
            outcome_available=outcome,
        )
    return result


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


__all__ = [
    "GateIsolationDryRunOrchestrator",
    "GateIsolationDryRunResult",
    "GateIsolationDryRunSummary",
    "export_gate_isolation_dry_run",
]
