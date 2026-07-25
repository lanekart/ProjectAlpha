"""Deterministic arm construction for DSI-002 gate-isolation research."""

from __future__ import annotations

from dataclasses import dataclass

from alpha.decision_superiority.gate_isolation_models import (
    CounterfactualArmType,
    CounterfactualSemanticStatus,
    FrozenCandidateKey,
    GateIsolationArm,
)

DEFAULT_MAX_REMEDIATION_SET_SIZE = 8


@dataclass(frozen=True, slots=True)
class GateIsolationArmBatch:
    """Deterministic arm population for one frozen candidate."""

    baseline: GateIsolationArm
    single_gate_arms: tuple[GateIsolationArm, ...]
    minimal_remediation_arms: tuple[GateIsolationArm, ...]
    combinatorial_limit_reached: bool = False

    def __post_init__(self) -> None:
        if self.baseline.arm_type is not CounterfactualArmType.BASELINE:
            raise ValueError("baseline must use BASELINE arm type")
        arm_ids = [
            self.baseline.arm_id,
            *(arm.arm_id for arm in self.single_gate_arms),
            *(arm.arm_id for arm in self.minimal_remediation_arms),
        ]
        if len(set(arm_ids)) != len(arm_ids):
            raise ValueError("arm_id values must be unique")


class GateIsolationArmBuilder:
    """Build baseline, single-gate, and bounded remediation-set arms."""

    def __init__(self, *, max_remediation_set_size: int = DEFAULT_MAX_REMEDIATION_SET_SIZE):
        if max_remediation_set_size < 1:
            raise ValueError("max_remediation_set_size must be positive")
        self._max_remediation_set_size = max_remediation_set_size

    def build(
        self,
        *,
        candidate: FrozenCandidateKey,
        observed_failure_codes: tuple[str, ...],
    ) -> GateIsolationArmBatch:
        failures = _normalized_codes(observed_failure_codes)
        prefix = _candidate_prefix(candidate)
        baseline = GateIsolationArm(
            arm_id=f"{prefix}|BASELINE",
            arm_type=CounterfactualArmType.BASELINE,
            candidate=candidate,
            passed_gate_codes=(),
            observed_failure_codes=failures,
            semantic_status=CounterfactualSemanticStatus.NO_DOWNSTREAM_EFFECT,
        )
        single_gate_arms = tuple(
            GateIsolationArm(
                arm_id=f"{prefix}|PASS:{gate_code}",
                arm_type=CounterfactualArmType.SINGLE_GATE_PASS,
                candidate=candidate,
                passed_gate_codes=(gate_code,),
                observed_failure_codes=failures,
                semantic_status=(
                    CounterfactualSemanticStatus.VALID_SINGLE_GATE_INTERVENTION
                    if len(failures) == 1
                    else CounterfactualSemanticStatus.NO_DOWNSTREAM_EFFECT
                ),
            )
            for gate_code in failures
        )

        limit_reached = len(failures) > self._max_remediation_set_size
        minimal_arms: tuple[GateIsolationArm, ...]
        if not failures or limit_reached:
            minimal_arms = ()
        else:
            minimal_arms = (
                GateIsolationArm(
                    arm_id=f"{prefix}|PASS:{'+'.join(failures)}",
                    arm_type=CounterfactualArmType.MINIMAL_REMEDIATION_SET,
                    candidate=candidate,
                    passed_gate_codes=failures,
                    observed_failure_codes=failures,
                    semantic_status=(
                        CounterfactualSemanticStatus.VALID_MINIMAL_REMEDIATION_SET
                    ),
                ),
            )
        return GateIsolationArmBatch(
            baseline=baseline,
            single_gate_arms=single_gate_arms,
            minimal_remediation_arms=minimal_arms,
            combinatorial_limit_reached=limit_reached,
        )


def prove_inclusion_minimal(arm: GateIsolationArm) -> bool:
    """Prove an arm is inclusion-minimal for its observed blocker set.

    At this construction layer, clearing every observed blocker requires passing the
    complete observed failure set. Downstream semantic replay may later invalidate
    the arm, but cannot make a strict subset clear the same observed blockers.
    """

    if arm.arm_type is not CounterfactualArmType.MINIMAL_REMEDIATION_SET:
        return False
    if not arm.clears_all_observed_failures:
        return False
    for gate_code in arm.passed_gate_codes:
        strict_subset = tuple(
            code for code in arm.passed_gate_codes if code != gate_code
        )
        remaining = set(arm.observed_failure_codes) - set(strict_subset)
        if not remaining:
            return False
    return True


def _normalized_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(sorted({value.strip() for value in values if value.strip()}))
    if len(normalized) != len(values):
        raise ValueError("observed_failure_codes must be non-empty, unique, and sorted")
    if normalized != values:
        raise ValueError("observed_failure_codes must be non-empty, unique, and sorted")
    return normalized


def _candidate_prefix(candidate: FrozenCandidateKey) -> str:
    return "|".join(
        (
            candidate.price_view,
            candidate.observed_on,
            candidate.symbol,
            candidate.input_fingerprint,
        )
    )


__all__ = [
    "DEFAULT_MAX_REMEDIATION_SET_SIZE",
    "GateIsolationArmBatch",
    "GateIsolationArmBuilder",
    "prove_inclusion_minimal",
]
