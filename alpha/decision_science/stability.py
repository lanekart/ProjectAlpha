from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from alpha.decision_lifecycle import LifecycleState


class StabilityBand(StrEnum):
    FRAGILE = "FRAGILE"
    MODERATE = "MODERATE"
    STABLE = "STABLE"
    VERY_STABLE = "VERY_STABLE"


@dataclass(frozen=True, slots=True)
class StabilityScenario:
    """One deterministic perturbation and its resulting lifecycle state."""

    scenario_id: str
    description: str
    resulting_state: LifecycleState
    weight: Decimal = Decimal("1")
    critical: bool = False

    def __post_init__(self) -> None:
        scenario_id = self.scenario_id.strip().upper()
        description = self.description.strip()
        if not scenario_id:
            raise ValueError("scenario_id cannot be empty")
        if not description:
            raise ValueError("scenario description cannot be empty")
        if self.weight <= 0:
            raise ValueError("scenario weight must be positive")
        object.__setattr__(self, "scenario_id", scenario_id)
        object.__setattr__(self, "description", description)
        object.__setattr__(
            self,
            "resulting_state",
            LifecycleState(self.resulting_state),
        )
        object.__setattr__(self, "weight", Decimal(self.weight))


@dataclass(frozen=True, slots=True)
class DecisionStabilityAssessment:
    baseline_state: LifecycleState
    score: int
    band: StabilityBand
    scenarios_tested: int
    unchanged_scenarios: int
    changed_scenarios: int
    critical_flips: tuple[str, ...]
    changed_scenario_ids: tuple[str, ...]
    production_influence: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError("stability score must be between 0 and 100")
        if self.scenarios_tested <= 0:
            raise ValueError("stability assessment requires at least one scenario")
        if self.unchanged_scenarios + self.changed_scenarios != self.scenarios_tested:
            raise ValueError("scenario counts must reconcile")
        if self.production_influence:
            raise ValueError(
                "stability assessment cannot influence production execution"
            )
        object.__setattr__(self, "baseline_state", LifecycleState(self.baseline_state))
        object.__setattr__(self, "band", StabilityBand(self.band))
        object.__setattr__(self, "critical_flips", tuple(self.critical_flips))
        object.__setattr__(
            self,
            "changed_scenario_ids",
            tuple(self.changed_scenario_ids),
        )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["baseline_state"] = self.baseline_state.value
        payload["band"] = self.band.value
        return payload


class DecisionStabilityEngine:
    """Measure how often a governed decision survives explicit perturbations."""

    def assess(
        self,
        *,
        baseline_state: LifecycleState,
        scenarios: tuple[StabilityScenario, ...],
    ) -> DecisionStabilityAssessment:
        baseline_state = LifecycleState(baseline_state)
        if not scenarios:
            raise ValueError("at least one stability scenario is required")

        scenario_ids = [scenario.scenario_id for scenario in scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("stability scenario ids must be unique")

        total_weight = sum((scenario.weight for scenario in scenarios), Decimal("0"))
        unchanged_weight = sum(
            (
                scenario.weight
                for scenario in scenarios
                if scenario.resulting_state is baseline_state
            ),
            Decimal("0"),
        )
        score = int(
            ((unchanged_weight / total_weight) * Decimal("100")).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )

        changed = tuple(
            scenario
            for scenario in scenarios
            if scenario.resulting_state is not baseline_state
        )
        critical_flips = tuple(
            scenario.scenario_id for scenario in changed if scenario.critical
        )
        return DecisionStabilityAssessment(
            baseline_state=baseline_state,
            score=score,
            band=_band_for_score(score),
            scenarios_tested=len(scenarios),
            unchanged_scenarios=len(scenarios) - len(changed),
            changed_scenarios=len(changed),
            critical_flips=critical_flips,
            changed_scenario_ids=tuple(scenario.scenario_id for scenario in changed),
        )


def _band_for_score(score: int) -> StabilityBand:
    if score >= 90:
        return StabilityBand.VERY_STABLE
    if score >= 70:
        return StabilityBand.STABLE
    if score >= 40:
        return StabilityBand.MODERATE
    return StabilityBand.FRAGILE


def render_stability_assessment(
    assessment: DecisionStabilityAssessment,
) -> tuple[str, ...]:
    lines = [
        "Decision Stability Assessment",
        f"Baseline State: {assessment.baseline_state.value}",
        f"Stability Score: {assessment.score}/100",
        f"Stability Band: {assessment.band.value}",
        f"Scenarios Tested: {assessment.scenarios_tested}",
        f"Decision Flips: {assessment.changed_scenarios}",
    ]
    if assessment.changed_scenario_ids:
        lines.append(
            "Changed Scenarios: " + ", ".join(assessment.changed_scenario_ids)
        )
    if assessment.critical_flips:
        lines.append("Critical Flips: " + ", ".join(assessment.critical_flips))
    lines.append("Execution Status: NON-EXECUTABLE DECISION DIAGNOSTIC")
    return tuple(lines)


def export_stability_json(assessment: DecisionStabilityAssessment) -> str:
    return json.dumps(assessment.to_dict(), indent=2, sort_keys=True)
