from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

PRODUCTION_INFLUENCE = False
NO_GATE_CHANGES = True
NO_ORDER_CHANGES = True
NO_THRESHOLD_CHANGES = True
GDSBA_VERSION = "GDSBA_v1.0"
BASELINE_ID = "ALPHA_BASELINE_v1.0"
DEFAULT_OUTPUT = ".alpha/gate_dependency/GDSBA_v1.0"


class GateGroup(StrEnum):
    VERDICT = "VERDICT"
    TIMING = "TIMING"
    EVIDENCE = "EVIDENCE"
    SETUP_TREND = "SETUP_TREND"
    TRADE_PLAN = "TRADE_PLAN"
    RISK = "RISK"
    DATA_QUALITY = "DATA_QUALITY"
    CAPACITY = "CAPACITY"
    LIVE_FEED = "LIVE_FEED"
    INSTITUTIONAL = "INSTITUTIONAL"
    PORTFOLIO = "PORTFOLIO"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_REACHED = "NOT_REACHED"


class GateGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    RESEARCH_ONLY = "Research Only"


class EvidenceConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class GateDefinition:
    gate_id: str
    display_name: str
    group: GateGroup
    sequence: int
    conditional_on: str | None = None

    def __post_init__(self) -> None:
        if not self.gate_id.strip() or not self.display_name.strip():
            raise ValueError("gate definition requires identity")
        if self.sequence < 1:
            raise ValueError("gate sequence must be positive")


@dataclass(frozen=True, slots=True)
class GateLineageStep:
    gate_id: str
    display_name: str
    gate_group: GateGroup
    sequence: int
    observed_status: GateStatus
    sequential_status: GateStatus
    failure_codes: tuple[str, ...]
    failure_explanations: tuple[str, ...]
    first_failure: bool


@dataclass(frozen=True, slots=True)
class CandidateGateLineage:
    candidate_id: str
    observed_on: date
    symbol: str
    final_signal: str
    candidate_score: Decimal
    outcome_classification: str
    planned_net_return_percent: Decimal | None
    planned_realized_r: Decimal | None
    first_failed_gate: str | None
    first_failed_group: GateGroup | None
    failed_gates: tuple[str, ...]
    failed_groups: tuple[GateGroup, ...]
    lineage: tuple[GateLineageStep, ...]


@dataclass(frozen=True, slots=True)
class FirstFailureStatistic:
    scope: str
    gate_id: str
    gate_group: str
    candidates: int
    population_percent: Decimal
    correct_rejections: int
    false_rejections: int
    marginal: int
    data_uncertain: int
    average_return_percent: Decimal | None


@dataclass(frozen=True, slots=True)
class GateSurvivalStatistic:
    gate_id: str
    display_name: str
    gate_group: GateGroup
    sequence: int
    entered_stage: int
    passed: int
    rejected: int
    not_reached: int
    pass_percent: Decimal | None
    reject_percent: Decimal | None
    cumulative_survival_percent: Decimal


@dataclass(frozen=True, slots=True)
class MarginalGateValue:
    gate_id: str
    display_name: str
    gate_group: GateGroup
    candidates_failed_gate: int
    additional_survivors_if_removed: int
    correct_rejections_released: int
    false_rejections_released: int
    marginal_released: int
    data_uncertain_released: int
    average_return_percent: Decimal | None
    opportunity_value_lost: Decimal
    capital_protection_gained: Decimal
    net_capital_protection: Decimal
    diagnostic_conclusion: str


@dataclass(frozen=True, slots=True)
class DependencyCell:
    prior_gate: str
    evaluated_gate: str
    population: int
    prior_passed: int
    evaluated_gate_failures: int
    incremental_failures_after_prior_pass: int
    conditional_reject_percent: Decimal | None
    standalone_reject_percent: Decimal | None
    retained_information_percent: Decimal | None
    correct_incremental_rejections: int
    false_incremental_rejections: int


@dataclass(frozen=True, slots=True)
class InteractionCell:
    gate_a: str
    gate_b: str
    population: int
    gate_a_failures: int
    gate_b_failures: int
    joint_failures: int
    only_a_failures: int
    only_b_failures: int
    neither_failures: int
    jaccard_percent: Decimal | None
    interaction_lift: Decimal | None
    joint_correct_rejections: int
    joint_false_rejections: int


@dataclass(frozen=True, slots=True)
class GateOrderAssessment:
    current_order: tuple[str, ...]
    most_efficient_order: tuple[str, ...]
    active_gate_count: int
    permutations_tested: int
    equally_efficient_orders: int
    current_average_gates_evaluated: Decimal
    minimum_average_gates_evaluated: Decimal
    efficiency_improvement_percent: Decimal
    accepted_current_order: int
    accepted_best_order: int
    false_rejections_current_order: int
    false_rejections_best_order: int
    decision_outcomes_changed: bool
    conclusion: str


@dataclass(frozen=True, slots=True)
class GatePathStatistic:
    outcome_classification: str
    failure_path: str
    candidates: int
    average_return_percent: Decimal | None
    representative_symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GateReportCard:
    gate_id: str
    display_name: str
    gate_group: GateGroup
    failures: int
    evaluable_population: int
    correct_rejections: int
    false_rejections: int
    accuracy_percent: Decimal | None
    rejection_precision_percent: Decimal | None
    incremental_survivors: int
    incremental_value: Decimal
    false_rejection_contribution_percent: Decimal | None
    capital_protection: Decimal
    opportunity_cost: Decimal
    confidence: EvidenceConfidence
    grade: GateGrade
    explanation: str


@dataclass(frozen=True, slots=True)
class BottleneckSummary:
    largest_bottleneck: str
    largest_bottleneck_candidates: int
    largest_false_rejection_contributor: str
    largest_false_rejection_count: int
    largest_sequential_false_rejection_contributor: str
    largest_sequential_false_rejection_count: int
    largest_capital_protection_contributor: str
    largest_capital_protection: Decimal
    most_redundant_gate_pair: str
    redundancy_percent: Decimal | None
    strongest_gate_interaction: str
    interaction_lift: Decimal | None
    ordering_materially_changes_outcomes: bool
    recommended_next_research_question: str


@dataclass(frozen=True, slots=True)
class GDSBAManifest:
    audit_version: str
    baseline_id: str
    igta_manifest_hash: str
    approval_policy_version: str
    approval_policy_hash: str
    gate_sequence_hash: str
    source_hashes: Mapping[str, str]
    artifact_hashes: Mapping[str, str] = field(default_factory=dict)
    production_influence: bool = PRODUCTION_INFLUENCE
    no_gate_changes: bool = NO_GATE_CHANGES
    no_order_changes: bool = NO_ORDER_CHANGES
    no_threshold_changes: bool = NO_THRESHOLD_CHANGES

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("GDSBA must never influence production")
        if not (
            self.no_gate_changes and self.no_order_changes and self.no_threshold_changes
        ):
            raise ValueError("GDSBA isolation guardrails cannot be disabled")
        object.__setattr__(
            self,
            "source_hashes",
            MappingProxyType(dict(sorted(self.source_hashes.items()))),
        )
        object.__setattr__(
            self,
            "artifact_hashes",
            MappingProxyType(dict(sorted(self.artifact_hashes.items()))),
        )


@dataclass(frozen=True, slots=True)
class GateDependencyAuditReport:
    manifest: GDSBAManifest
    technical_candidates: int
    buy_candidates: int
    lineages: tuple[CandidateGateLineage, ...]
    first_failures: tuple[FirstFailureStatistic, ...]
    survival: tuple[GateSurvivalStatistic, ...]
    dependencies: tuple[DependencyCell, ...]
    interactions: tuple[InteractionCell, ...]
    marginal_values: tuple[MarginalGateValue, ...]
    false_rejection_paths: tuple[GatePathStatistic, ...]
    correct_rejection_paths: tuple[GatePathStatistic, ...]
    report_cards: tuple[GateReportCard, ...]
    gate_order: GateOrderAssessment
    bottleneck: BottleneckSummary


__all__ = [
    "BASELINE_ID",
    "DEFAULT_OUTPUT",
    "GDSBA_VERSION",
    "NO_GATE_CHANGES",
    "NO_ORDER_CHANGES",
    "NO_THRESHOLD_CHANGES",
    "PRODUCTION_INFLUENCE",
    "BottleneckSummary",
    "CandidateGateLineage",
    "DependencyCell",
    "EvidenceConfidence",
    "FirstFailureStatistic",
    "GDSBAManifest",
    "GateDefinition",
    "GateDependencyAuditReport",
    "GateGrade",
    "GateGroup",
    "GateLineageStep",
    "GateOrderAssessment",
    "GatePathStatistic",
    "GateReportCard",
    "GateStatus",
    "GateSurvivalStatistic",
    "InteractionCell",
    "MarginalGateValue",
]
