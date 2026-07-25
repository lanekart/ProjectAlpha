"""Governed orchestration for decision-superiority gate diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.decision_superiority.conclusions import (
    GateConclusion,
    conclude_gate,
    rank_conclusions,
)
from alpha.decision_superiority.confidence import (
    DEFAULT_MINIMUM_RESOLVED,
    EvidenceAssessment,
    assess_evidence,
)
from alpha.decision_superiority.metrics import (
    EconomicDistribution,
    EvidenceStrength,
    GateEconomicValue,
    GateMetricSnapshot,
)
from alpha.decision_superiority.statistics import (
    build_distribution,
    build_evidence_strength,
    build_gate_value,
)


@dataclass(frozen=True, slots=True)
class GatePipelineInput:
    """Immutable governed input for one gate-analysis population."""

    gate_code: str
    sample_count: int
    returns_pct: tuple[Decimal, ...]
    minimum_required: int = DEFAULT_MINIMUM_RESOLVED
    empty_reason: str = "NO_RESOLVED_OUTCOMES"
    observed_blocked_count: int = 0
    observed_resolved_count: int = 0
    co_blocked_count: int = 0
    isolation_status: str = "ISOLATED_POPULATION"

    def __post_init__(self) -> None:
        if not self.gate_code.strip():
            raise ValueError("gate_code cannot be empty")
        if self.sample_count < 0:
            raise ValueError("sample_count cannot be negative")
        if self.minimum_required < 0:
            raise ValueError("minimum_required cannot be negative")
        if len(self.returns_pct) > self.sample_count:
            raise ValueError("resolved return count cannot exceed sample_count")
        if not self.empty_reason.strip():
            raise ValueError("empty_reason cannot be empty")
        if not self.isolation_status.strip():
            raise ValueError("isolation_status cannot be empty")
        for name, value in (
            ("observed_blocked_count", self.observed_blocked_count),
            ("observed_resolved_count", self.observed_resolved_count),
            ("co_blocked_count", self.co_blocked_count),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.observed_resolved_count > self.observed_blocked_count:
            raise ValueError(
                "observed_resolved_count cannot exceed observed_blocked_count"
            )
        if self.co_blocked_count > self.observed_blocked_count:
            raise ValueError("co_blocked_count cannot exceed observed_blocked_count")


@dataclass(frozen=True, slots=True)
class GatePipelineResult:
    """Complete immutable diagnostic output for one governed gate."""

    gate_code: str
    distribution: EconomicDistribution
    evidence_strength: EvidenceStrength
    economic_value: GateEconomicValue
    confidence: EvidenceAssessment
    conclusion: GateConclusion
    observed_blocked_count: int = 0
    observed_resolved_count: int = 0
    co_blocked_count: int = 0
    isolation_status: str = "ISOLATED_POPULATION"
    production_influence: bool = False

    def __post_init__(self) -> None:
        if not self.gate_code.strip():
            raise ValueError("gate_code cannot be empty")
        if self.production_influence:
            raise ValueError("DSI gate pipeline must remain diagnostic-only")
        if self.conclusion.production_influence:
            raise ValueError("pipeline conclusion must remain diagnostic-only")
        if self.conclusion.gate_code != self.gate_code:
            raise ValueError("conclusion gate_code must match pipeline gate_code")
        if self.distribution.sample_count != self.evidence_strength.sample_count:
            raise ValueError("distribution and evidence sample_count values must match")
        if self.distribution.resolved_count != self.evidence_strength.resolved_count:
            raise ValueError(
                "distribution and evidence resolved_count values must match"
            )
        if self.distribution.sample_count != self.confidence.sample_count:
            raise ValueError(
                "distribution and confidence sample_count values must match"
            )
        if self.distribution.resolved_count != self.confidence.resolved_count:
            raise ValueError(
                "distribution and confidence resolved_count values must match"
            )
        if not self.isolation_status.strip():
            raise ValueError("isolation_status cannot be empty")
        for name, value in (
            ("observed_blocked_count", self.observed_blocked_count),
            ("observed_resolved_count", self.observed_resolved_count),
            ("co_blocked_count", self.co_blocked_count),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")

    @property
    def metric_snapshot(self) -> GateMetricSnapshot:
        """Return the canonical immutable metric snapshot."""
        return GateMetricSnapshot(
            gate_code=self.gate_code,
            distribution=self.distribution,
            evidence=self.evidence_strength,
            economic_value=self.economic_value,
        )


@dataclass(frozen=True, slots=True)
class GatePipelineBatchResult:
    """Deterministic immutable result for a governed gate population."""

    results: tuple[GatePipelineResult, ...]
    conclusions: tuple[GateConclusion, ...]
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("DSI gate pipeline batch must remain diagnostic-only")
        if len(self.results) != len(self.conclusions):
            raise ValueError("result and conclusion populations must have equal length")
        result_codes = {result.gate_code for result in self.results}
        conclusion_codes = {conclusion.gate_code for conclusion in self.conclusions}
        if result_codes != conclusion_codes:
            raise ValueError("result and conclusion gate populations must match")
        if len(result_codes) != len(self.results):
            raise ValueError("gate_code values must be unique")


def run_gate_pipeline(
    pipeline_input: GatePipelineInput,
) -> GatePipelineResult:
    """Execute the complete governed analytical pipeline for one gate."""
    returns = list(pipeline_input.returns_pct)
    distribution = build_distribution(
        sample_count=pipeline_input.sample_count,
        returns_pct=returns,
    )
    evidence_strength = build_evidence_strength(
        sample_count=pipeline_input.sample_count,
        resolved_count=distribution.resolved_count,
        minimum_required=pipeline_input.minimum_required,
    )
    economic_value = build_gate_value(returns_pct=returns)
    confidence = assess_evidence(
        sample_count=pipeline_input.sample_count,
        returns_pct=returns,
        minimum_required=pipeline_input.minimum_required,
        empty_reason=pipeline_input.empty_reason,
    )
    conclusion = conclude_gate(
        gate_code=pipeline_input.gate_code,
        economic_value=economic_value,
        evidence=confidence,
    )
    return GatePipelineResult(
        gate_code=pipeline_input.gate_code,
        distribution=distribution,
        evidence_strength=evidence_strength,
        economic_value=economic_value,
        confidence=confidence,
        conclusion=conclusion,
        observed_blocked_count=pipeline_input.observed_blocked_count,
        observed_resolved_count=pipeline_input.observed_resolved_count,
        co_blocked_count=pipeline_input.co_blocked_count,
        isolation_status=pipeline_input.isolation_status,
    )


def run_gate_pipeline_batch(
    pipeline_inputs: list[GatePipelineInput],
) -> GatePipelineBatchResult:
    """Execute gates deterministically and reject duplicate gate codes."""
    gate_codes = [pipeline_input.gate_code for pipeline_input in pipeline_inputs]
    if len(set(gate_codes)) != len(gate_codes):
        raise ValueError("gate_code values must be unique")
    results = tuple(
        sorted(
            (run_gate_pipeline(pipeline_input) for pipeline_input in pipeline_inputs),
            key=lambda result: result.gate_code,
        )
    )
    conclusions = rank_conclusions([result.conclusion for result in results])
    return GatePipelineBatchResult(results=results, conclusions=conclusions)
