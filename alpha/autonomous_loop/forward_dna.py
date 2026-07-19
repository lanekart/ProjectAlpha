from __future__ import annotations

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256

from alpha.autonomous_loop.models import (
    DecisionResolution,
    DNADriftAssessment,
    DriftState,
    ForwardDNACohort,
    ForwardDNAObservation,
    FrozenDecision,
    LoopEvidenceClass,
    ResolutionKind,
)
from alpha.autonomous_loop.registry import AutonomousLoopRegistry, canonical_json


class ForwardObservedDNAEngine:
    """Maintain evidence-isolated DNA cohorts from matured decision markouts."""

    def __init__(self, registry: AutonomousLoopRegistry) -> None:
        self.registry = registry

    def update(self) -> tuple[int, tuple[DNADriftAssessment, ...]]:
        decisions = {item.decision_id: item for item in self.registry.decisions()}
        observations = tuple(
            observation
            for resolution in self.registry.resolutions()
            if (decision := decisions.get(resolution.decision_id)) is not None
            and (observation := _observation(decision, resolution)) is not None
        )
        inserted = self.registry.append_forward_dna(observations)
        drifts = ForwardDNADriftEngine().assess(
            observations=self.registry.forward_dna(),
            resolutions=self.registry.resolutions(),
        )
        self.registry.append_dna_drifts(drifts)
        return inserted, drifts


class ForwardDNADriftEngine:
    """Detect forward cohort prevalence shifts with explicit sample guards."""

    def __init__(
        self,
        *,
        minimum_segment: int = 10,
        early_change_pp: Decimal = Decimal("10"),
        significant_change_pp: Decimal = Decimal("20"),
    ) -> None:
        if minimum_segment <= 0:
            raise ValueError("DNA drift segment must be positive")
        self.minimum_segment = minimum_segment
        self.early_change_pp = early_change_pp
        self.significant_change_pp = significant_change_pp

    def assess(
        self,
        *,
        observations: tuple[ForwardDNAObservation, ...],
        resolutions: tuple[DecisionResolution, ...],
    ) -> tuple[DNADriftAssessment, ...]:
        ordered = tuple(sorted(resolutions, key=lambda item: item.resolved_at))
        cohort_by_resolution = {
            item.source_resolution_id: item.cohort for item in observations
        }
        midpoint = len(ordered) // 2
        baseline = ordered[:midpoint]
        recent = ordered[midpoint:]
        return tuple(
            self._cohort(cohort, baseline, recent, cohort_by_resolution)
            for cohort in ForwardDNACohort
        )

    def _cohort(
        self,
        cohort: ForwardDNACohort,
        baseline: tuple[DecisionResolution, ...],
        recent: tuple[DecisionResolution, ...],
        cohort_by_resolution: dict[str, ForwardDNACohort],
    ) -> DNADriftAssessment:
        evidence_ids = tuple(item.resolution_id for item in baseline + recent)
        identity = sha256(
            canonical_json(
                {"cohort": cohort.value, "evidence_ids": evidence_ids}
            ).encode()
        ).hexdigest()[:20]
        if len(baseline) < self.minimum_segment or len(recent) < self.minimum_segment:
            return DNADriftAssessment(
                drift_id=f"forward-dna-drift-{identity}",
                cohort=cohort,
                baseline_count=len(baseline),
                recent_count=len(recent),
                baseline_prevalence_pct=None,
                recent_prevalence_pct=None,
                change_pct_points=None,
                state=DriftState.UNKNOWN,
                evidence_ids=evidence_ids,
                explanation=(
                    "Insufficient resolved FORWARD_OBSERVED decisions for two "
                    "guarded chronological segments."
                ),
            )
        baseline_rate = _prevalence(baseline, cohort, cohort_by_resolution)
        recent_rate = _prevalence(recent, cohort, cohort_by_resolution)
        change = _q(recent_rate - baseline_rate)
        absolute = abs(change)
        state = (
            DriftState.SIGNIFICANT_DRIFT
            if absolute >= self.significant_change_pp
            else DriftState.EARLY_DRIFT
            if absolute >= self.early_change_pp
            else DriftState.NO_DRIFT
        )
        return DNADriftAssessment(
            drift_id=f"forward-dna-drift-{identity}",
            cohort=cohort,
            baseline_count=len(baseline),
            recent_count=len(recent),
            baseline_prevalence_pct=baseline_rate,
            recent_prevalence_pct=recent_rate,
            change_pct_points=change,
            state=state,
            evidence_ids=evidence_ids,
            explanation=(
                f"Chronological {cohort.value} prevalence changed from "
                f"{baseline_rate}% to {recent_rate}% using forward evidence only."
            ),
        )


def cohort_counts(
    observations: tuple[ForwardDNAObservation, ...],
) -> dict[ForwardDNACohort, int]:
    counts = Counter(item.cohort for item in observations)
    return {cohort: counts.get(cohort, 0) for cohort in ForwardDNACohort}


def _observation(
    decision: FrozenDecision, resolution: DecisionResolution
) -> ForwardDNAObservation | None:
    cohort = _cohort(resolution.resolution_kind)
    if cohort is None:
        return None
    payload = {
        "decision_id": decision.decision_id,
        "resolution_id": resolution.resolution_id,
        "cohort": cohort.value,
        "evidence_class": LoopEvidenceClass.FORWARD_OBSERVED.value,
    }
    observation_id = sha256(canonical_json(payload).encode()).hexdigest()[:24]
    return ForwardDNAObservation(
        observation_id=observation_id,
        decision_id=decision.decision_id,
        recommendation_id=decision.recommendation_id,
        observed_at=resolution.resolved_at,
        symbol=decision.symbol,
        cohort=cohort,
        realised_return_pct=resolution.realised_return_pct,
        features=dict(decision.feature_snapshot),
        source_resolution_id=resolution.resolution_id,
    )


def _cohort(kind: ResolutionKind) -> ForwardDNACohort | None:
    return {
        ResolutionKind.WINNER: ForwardDNACohort.WINNERS,
        ResolutionKind.LOSER: ForwardDNACohort.LOSERS,
        ResolutionKind.CATASTROPHIC_LOSS: ForwardDNACohort.CATASTROPHIC_LOSSES,
        ResolutionKind.MISSED_OPPORTUNITY: ForwardDNACohort.MISSED_OPPORTUNITIES,
        ResolutionKind.REJECTED_OPPORTUNITY: ForwardDNACohort.REJECTED_OPPORTUNITIES,
    }.get(kind)


def _prevalence(
    rows: tuple[DecisionResolution, ...],
    cohort: ForwardDNACohort,
    cohort_by_resolution: dict[str, ForwardDNACohort],
) -> Decimal:
    matches = sum(
        1 for item in rows if cohort_by_resolution.get(item.resolution_id) is cohort
    )
    return _q(Decimal(matches) / Decimal(len(rows)) * Decimal("100"))


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


__all__ = [
    "ForwardDNADriftEngine",
    "ForwardObservedDNAEngine",
    "cohort_counts",
]
