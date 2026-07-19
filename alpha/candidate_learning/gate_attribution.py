from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import combinations
from pathlib import Path
from statistics import median

from alpha.candidate_learning.approval_diagnostics import (
    ApprovalCriterionId,
    ApprovalDiagnosticsConfig,
    ApprovalDiagnosticsEngine,
    ApprovalRejectionReasonCode,
    InstitutionalApprovalCriterionResult,
    InstitutionalApprovalDiagnostic,
)
from alpha.candidate_learning.entry_timing import (
    EntryTimingOutcomeRow,
    EntryTimingState,
    build_entry_timing_replay_report,
)
from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_CATASTROPHIC_LOSS_THRESHOLD = Decimal("-15")

PRIMARY_ENTRY_STATES = (
    EntryTimingState.AGGRESSIVE_ENTRY,
    EntryTimingState.PREFERRED_ENTRY,
    EntryTimingState.CONFIRMATION_ENTRY,
)
SECONDARY_ENTRY_STATES = (
    EntryTimingState.SETUP_FORMING,
    EntryTimingState.EARLY_ENTRY,
    EntryTimingState.EXTENDED_ENTRY,
    EntryTimingState.LATE_ENTRY,
    EntryTimingState.INVALID_ENTRY,
    EntryTimingState.ENTRY_UNAVAILABLE,
)


class GateCategory(StrEnum):
    DIRECTIONAL_EVIDENCE = "DIRECTIONAL_EVIDENCE"
    RISK_ECONOMICS = "RISK_ECONOMICS"
    HISTORICAL_EVIDENCE = "HISTORICAL_EVIDENCE"
    PROBABILITY_CALIBRATION = "PROBABILITY_CALIBRATION"
    TRADE_PLAN_QUALITY = "TRADE_PLAN_QUALITY"
    DATA_COMPLETENESS = "DATA_COMPLETENESS"
    META_APPROVAL = "META_APPROVAL"
    MIXED_ENTRY_AND_PLAN = "MIXED_ENTRY_AND_PLAN"


class GateScope(StrEnum):
    NON_ENTRY = "NON_ENTRY"
    MIXED = "MIXED"
    META = "META"


class MissingDataTreatment(StrEnum):
    FAILURE = "FAILURE"
    UNAVAILABLE = "UNAVAILABLE"
    NEUTRAL = "NEUTRAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AttributionUniverse(StrEnum):
    PRIMARY_ACCEPTABLE_TIMING = "PRIMARY_ACCEPTABLE_TIMING"
    SECONDARY_CONTEXT = "SECONDARY_CONTEXT"
    ALL_COMPLETED = "ALL_COMPLETED"


class CandidateOutcomeClass(StrEnum):
    WINNER = "WINNER"
    LOSER = "LOSER"
    FLAT = "FLAT"


class FalseNegativeAttribution(StrEnum):
    GATE_FAILED_ON_WINNER = "GATE_FAILED_ON_WINNER"
    GATE_UNIQUELY_FAILED_ON_WINNER = "GATE_UNIQUELY_FAILED_ON_WINNER"
    GATE_FAILED_WITH_OTHER_GATES_ON_WINNER = "GATE_FAILED_WITH_OTHER_GATES_ON_WINNER"
    GATE_UNAVAILABLE_ON_WINNER = "GATE_UNAVAILABLE_ON_WINNER"


class GateOverlapClassification(StrEnum):
    HIGHLY_REDUNDANT = "HIGHLY_REDUNDANT"
    PARTIALLY_REDUNDANT = "PARTIALLY_REDUNDANT"
    MOSTLY_INDEPENDENT = "MOSTLY_INDEPENDENT"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


class GateOverlapType(StrEnum):
    OUTCOME_OVERLAP = "OUTCOME_OVERLAP"
    FEATURE_OVERLAP = "FEATURE_OVERLAP"
    DECISION_OVERLAP = "DECISION_OVERLAP"
    POSSIBLE_REDUNDANCY = "POSSIBLE_REDUNDANCY"


class GateIncrementalValueFinding(StrEnum):
    HIGH_INCREMENTAL_VALUE = "HIGH_INCREMENTAL_VALUE"
    MODERATE_INCREMENTAL_VALUE = "MODERATE_INCREMENTAL_VALUE"
    LOW_INCREMENTAL_VALUE = "LOW_INCREMENTAL_VALUE"
    NO_OBSERVABLE_INCREMENTAL_VALUE = "NO_OBSERVABLE_INCREMENTAL_VALUE"
    POSSIBLE_DUPLICATE_GATE = "POSSIBLE_DUPLICATE_GATE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class GateInteractionFinding(StrEnum):
    PROTECTIVE_INTERACTION = "PROTECTIVE_INTERACTION"
    HIGH_FALSE_NEGATIVE_INTERACTION = "HIGH_FALSE_NEGATIVE_INTERACTION"
    MIXED_INTERACTION = "MIXED_INTERACTION"
    POSSIBLE_DUPLICATION_CLUSTER = "POSSIBLE_DUPLICATION_CLUSTER"
    INSUFFICIENT_INTERACTION_SAMPLE = "INSUFFICIENT_INTERACTION_SAMPLE"


class GateAttributionFinding(StrEnum):
    GATE_PROVIDES_DOWNSIDE_PROTECTION = "GATE_PROVIDES_DOWNSIDE_PROTECTION"
    GATE_HAS_HIGH_FALSE_NEGATIVE_BURDEN = "GATE_HAS_HIGH_FALSE_NEGATIVE_BURDEN"
    GATE_ADDS_INCREMENTAL_INFORMATION = "GATE_ADDS_INCREMENTAL_INFORMATION"
    GATE_HAS_LOW_OUTCOME_SEPARATION = "GATE_HAS_LOW_OUTCOME_SEPARATION"
    GATE_IS_HIGHLY_OVERLAPPING = "GATE_IS_HIGHLY_OVERLAPPING"
    GATE_MAY_DUPLICATE_ANOTHER_GATE = "GATE_MAY_DUPLICATE_ANOTHER_GATE"
    GATE_IS_DATA_LIMITED = "GATE_IS_DATA_LIMITED"
    GATE_INPUT_QUALITY_IS_WEAK = "GATE_INPUT_QUALITY_IS_WEAK"
    DIRECTIONAL_SIGNAL_QUALITY_DOMINATES = "DIRECTIONAL_SIGNAL_QUALITY_DOMINATES"
    MULTIPLE_GATES_JOINTLY_DOMINATE = "MULTIPLE_GATES_JOINTLY_DOMINATE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class GateInvestigationRecommendation(StrEnum):
    KEEP_GATE_UNCHANGED = "KEEP_GATE_UNCHANGED"
    INVESTIGATE_GATE_FURTHER = "INVESTIGATE_GATE_FURTHER"
    INVESTIGATE_GATE_INPUT_DATA = "INVESTIGATE_GATE_INPUT_DATA"
    INVESTIGATE_PROBABILITY_CALIBRATION = "INVESTIGATE_PROBABILITY_CALIBRATION"
    INVESTIGATE_HISTORICAL_EVIDENCE_QUALITY = "INVESTIGATE_HISTORICAL_EVIDENCE_QUALITY"
    INVESTIGATE_DIRECTIONAL_SIGNAL_QUALITY = "INVESTIGATE_DIRECTIONAL_SIGNAL_QUALITY"
    INVESTIGATE_TRADE_PLAN_QUALITY = "INVESTIGATE_TRADE_PLAN_QUALITY"
    INVESTIGATE_DATA_COMPLETENESS = "INVESTIGATE_DATA_COMPLETENESS"
    INVESTIGATE_GATE_DUPLICATION = "INVESTIGATE_GATE_DUPLICATION"
    COLLECT_MORE_REPLAY_EVIDENCE = "COLLECT_MORE_REPLAY_EVIDENCE"
    NO_ACTION_RECOMMENDED = "NO_ACTION_RECOMMENDED"


class GateAttributionConclusion(StrEnum):
    NON_ENTRY_GATES_PROVIDE_MEANINGFUL_PROTECTION = (
        "NON_ENTRY_GATES_PROVIDE_MEANINGFUL_PROTECTION"
    )
    NON_ENTRY_GATES_HAVE_HIGH_FALSE_NEGATIVE_BURDEN = (
        "NON_ENTRY_GATES_HAVE_HIGH_FALSE_NEGATIVE_BURDEN"
    )
    NON_ENTRY_GATE_REDUNDANCY_DOMINATES = "NON_ENTRY_GATE_REDUNDANCY_DOMINATES"
    NON_ENTRY_GATE_INPUT_DATA_IS_PRIMARY_BOTTLENECK = (
        "NON_ENTRY_GATE_INPUT_DATA_IS_PRIMARY_BOTTLENECK"
    )
    DIRECTIONAL_SIGNAL_QUALITY_IS_PRIMARY_BOTTLENECK = (
        "DIRECTIONAL_SIGNAL_QUALITY_IS_PRIMARY_BOTTLENECK"
    )
    PROBABILITY_CALIBRATION_REQUIRES_INVESTIGATION = (
        "PROBABILITY_CALIBRATION_REQUIRES_INVESTIGATION"
    )
    HISTORICAL_EVIDENCE_REQUIRES_INVESTIGATION = (
        "HISTORICAL_EVIDENCE_REQUIRES_INVESTIGATION"
    )
    TRADE_PLAN_QUALITY_REQUIRES_INVESTIGATION = (
        "TRADE_PLAN_QUALITY_REQUIRES_INVESTIGATION"
    )
    DATA_COMPLETENESS_IS_PRIMARY_BOTTLENECK = "DATA_COMPLETENESS_IS_PRIMARY_BOTTLENECK"
    MIXED_GATE_AND_SIGNAL_QUALITY_PROBLEM = "MIXED_GATE_AND_SIGNAL_QUALITY_PROBLEM"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class NextGateAttributionMilestone(StrEnum):
    DIRECTIONAL_SIGNAL_QUALITY_AUDIT = "DIRECTIONAL_SIGNAL_QUALITY_AUDIT"
    HISTORICAL_EVIDENCE_QUALITY_AUDIT = "HISTORICAL_EVIDENCE_QUALITY_AUDIT"
    PROBABILITY_CALIBRATION_AUDIT = "PROBABILITY_CALIBRATION_AUDIT"
    TRADE_PLAN_GATE_AUDIT = "TRADE_PLAN_GATE_AUDIT"
    DATA_COMPLETENESS_REMEDIATION = "DATA_COMPLETENESS_REMEDIATION"
    GATE_REDUNDANCY_REVIEW = "GATE_REDUNDANCY_REVIEW"
    GATE_CALIBRATION_RESEARCH = "GATE_CALIBRATION_RESEARCH"
    COLLECT_MORE_REPLAY_EVIDENCE = "COLLECT_MORE_REPLAY_EVIDENCE"
    NO_CHANGE_RECOMMENDED = "NO_CHANGE_RECOMMENDED"


@dataclass(frozen=True, slots=True)
class NonEntryGateAttributionConfig:
    minimum_gate_sample: int = 20
    minimum_overlap_sample: int = 10
    highly_redundant_jaccard: Decimal = Decimal("0.75")
    partially_redundant_jaccard: Decimal = Decimal("0.40")
    high_false_negative_rate: Decimal = Decimal("0.30")
    protective_loser_rejection_rate: Decimal = Decimal("0.60")
    catastrophic_loss_threshold: Decimal = _CATASTROPHIC_LOSS_THRESHOLD


@dataclass(frozen=True, slots=True)
class GateInventoryRecord:
    gate_id: ApprovalCriterionId
    gate_category: GateCategory
    gate_scope: GateScope
    description: str
    authoritative_pass_fail_source: str
    threshold_source: str
    mandatory: bool
    can_be_unavailable: bool
    missing_data_treatment: MissingDataTreatment
    approval_stage: str
    features_consumed: tuple[str, ...]
    similar_feature_gates: tuple[ApprovalCriterionId, ...]


@dataclass(frozen=True, slots=True)
class CandidateGateAuditRow:
    candidate_id: str
    symbol: str
    replay_date: date
    outcome_class: CandidateOutcomeClass
    completed_outcome: bool
    forward_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    target_1_hit: bool | None
    target_2_hit: bool | None
    stop_hit: bool | None
    entry_state: EntryTimingState
    timing_score: Decimal
    raw_approved: bool
    strict_approved: bool
    failed_non_entry_gates: tuple[ApprovalCriterionId, ...]
    uniquely_failed_gate: ApprovalCriterionId | None
    primary_rejection_reason: ApprovalRejectionReasonCode
    secondary_rejection_reasons: tuple[ApprovalRejectionReasonCode, ...]
    final_verdict: str
    setup_type: str | None
    market_regime: str | None
    sector: str | None
    probability: Decimal | None
    historical_evidence_quality: str
    trade_plan_quality: str
    stop_distance: Decimal | None
    support_distance: Decimal | None
    reward_risk: Decimal | None
    data_completeness_status: str
    failed_gate_count: int
    diagnostic: InstitutionalApprovalDiagnostic
    timing_row: EntryTimingOutcomeRow


@dataclass(frozen=True, slots=True)
class GateEconomicImpact:
    gross_missed_upside: Decimal
    gross_avoided_downside: Decimal
    gross_net_replay_attribution: Decimal
    unique_missed_upside: Decimal
    unique_avoided_downside: Decimal
    unique_net_replay_attribution: Decimal
    sample_count: int
    winner_count: int
    loser_count: int
    flat_count: int
    average_outcome: Decimal | None
    median_outcome: Decimal | None
    downside_tail_protection: Decimal | None
    upside_tail_opportunity_cost: Decimal | None
    caveats: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GateOutcomeAttribution:
    universe: AttributionUniverse
    gate_id: ApprovalCriterionId
    gate_category: GateCategory
    gate_scope: GateScope
    candidates_evaluated: int
    candidates_reaching_gate: int
    candidates_passing: int
    candidates_failing: int
    candidates_unavailable: int
    candidates_with_missing_inputs: int
    completed_outcomes: int
    winners_failing_gate: int
    losers_failing_gate: int
    flat_failing_gate: int
    profitable_rejected_candidates: int
    true_negative_rejected_candidates: int
    raw_approved_candidates: int
    strict_approved_candidates: int
    winner_rejection_rate: Decimal | None
    loser_rejection_rate: Decimal | None
    gate_pass_rate: Decimal | None
    gate_failure_rate: Decimal | None
    missing_data_rate: Decimal | None
    mean_return_failures: Decimal | None
    median_return_failures: Decimal | None
    return_quartiles_failures: tuple[Decimal | None, Decimal | None, Decimal | None]
    mean_return_passes: Decimal | None
    median_return_passes: Decimal | None
    winner_rate_failures: Decimal | None
    winner_rate_passes: Decimal | None
    loser_rate_failures: Decimal | None
    loser_rate_passes: Decimal | None
    average_timing_score: Decimal | None
    median_timing_score: Decimal | None
    average_planned_reward_risk: Decimal | None
    median_planned_reward_risk: Decimal | None
    average_stop_distance: Decimal | None
    median_stop_distance: Decimal | None
    average_support_distance: Decimal | None
    average_directional_confidence: Decimal | None
    average_probability: Decimal | None
    average_failed_gate_count: Decimal | None
    false_negative_attribution: tuple[FalseNegativeAttribution, ...]
    economic_impact: GateEconomicImpact
    findings: tuple[GateAttributionFinding, ...]
    recommendation: GateInvestigationRecommendation


@dataclass(frozen=True, slots=True)
class GateOverlapReport:
    gate_a: ApprovalCriterionId
    gate_b: ApprovalCriterionId
    failure_count_a: int
    failure_count_b: int
    joint_failure_count: int
    union_failure_count: int
    overlap_percentage: Decimal | None
    jaccard_similarity: Decimal | None
    probability_b_given_a: Decimal | None
    probability_a_given_b: Decimal | None
    lift: Decimal | None
    joint_winner_count: int
    joint_loser_count: int
    average_joint_failure_return: Decimal | None
    median_joint_failure_return: Decimal | None
    classification: GateOverlapClassification
    overlap_types: tuple[GateOverlapType, ...]


@dataclass(frozen=True, slots=True)
class GateInteractionCluster:
    gates: tuple[ApprovalCriterionId, ...]
    combination_frequency: int
    percentage_of_rejected_candidates: Decimal | None
    winner_count: int
    loser_count: int
    winner_rate: Decimal | None
    loser_rate: Decimal | None
    mean_return: Decimal | None
    median_return: Decimal | None
    total_missed_upside: Decimal
    total_avoided_downside: Decimal
    average_timing_score: Decimal | None
    average_failed_gate_count: Decimal | None
    finding: GateInteractionFinding


@dataclass(frozen=True, slots=True)
class GateIncrementalValueReport:
    gate_id: ApprovalCriterionId
    candidates_uniquely_failed: int
    winners_uniquely_failed: int
    losers_uniquely_failed: int
    unique_failure_winner_rate: Decimal | None
    unique_failure_loser_rate: Decimal | None
    unique_failure_mean_return: Decimal | None
    unique_failure_median_return: Decimal | None
    unique_avoided_downside: Decimal
    unique_missed_upside: Decimal
    strongest_overlapping_gate: ApprovalCriterionId | None
    adds_separation_beyond_overlap: bool
    finding: GateIncrementalValueFinding


@dataclass(frozen=True, slots=True)
class GateRankingReport:
    downside_protection: tuple[ApprovalCriterionId, ...]
    opportunity_cost: tuple[ApprovalCriterionId, ...]
    incremental_information: tuple[ApprovalCriterionId, ...]
    redundancy: tuple[tuple[ApprovalCriterionId, ApprovalCriterionId], ...]
    missing_data_burden: tuple[ApprovalCriterionId, ...]


@dataclass(frozen=True, slots=True)
class AcceptablyTimedCandidateAnalysis:
    candidate_count: int
    completed_outcomes: int
    entry_state_counts: tuple[tuple[EntryTimingState, int], ...]
    verdict_counts: tuple[tuple[str, int], ...]
    setup_type_counts: tuple[tuple[str, int], ...]
    market_regime_counts: tuple[tuple[str, int], ...]
    sector_counts: tuple[tuple[str, int], ...]
    evidence_quality_counts: tuple[tuple[str, int], ...]
    probability_band_counts: tuple[tuple[str, int], ...]
    trade_plan_quality_counts: tuple[tuple[str, int], ...]
    dominant_failed_gates: tuple[tuple[ApprovalCriterionId, int], ...]


@dataclass(frozen=True, slots=True)
class GateAttributionDecision:
    primary_conclusion: GateAttributionConclusion
    secondary_conclusions: tuple[GateAttributionConclusion, ...]
    strongest_protective_gate: ApprovalCriterionId | None
    highest_opportunity_cost_gate: ApprovalCriterionId | None
    strongest_incremental_gate: ApprovalCriterionId | None
    most_overlapping_gate_pair: tuple[ApprovalCriterionId, ApprovalCriterionId] | None
    dominant_rejection_cluster: tuple[ApprovalCriterionId, ...]
    dominant_unresolved_bottleneck: str
    recommended_next_milestone: NextGateAttributionMilestone
    prohibited_next_step: str


@dataclass(frozen=True, slots=True)
class GateAttributionReport:
    inventory: tuple[GateInventoryRecord, ...]
    candidate_rows: tuple[CandidateGateAuditRow, ...]
    primary_attribution: tuple[GateOutcomeAttribution, ...]
    secondary_attribution: tuple[GateOutcomeAttribution, ...]
    mixed_gate_attribution: tuple[GateOutcomeAttribution, ...]
    overlap_matrix: tuple[GateOverlapReport, ...]
    interaction_clusters: tuple[GateInteractionCluster, ...]
    incremental_value: tuple[GateIncrementalValueReport, ...]
    rankings: GateRankingReport
    acceptably_timed_analysis: AcceptablyTimedCandidateAnalysis
    decision: GateAttributionDecision
    raw_approval_count_before: int
    raw_approval_count_after: int
    strict_approval_count_before: int
    strict_approval_count_after: int
    candidates_evaluated: int
    completed_outcomes: int
    primary_universe_count: int
    secondary_universe_count: int


class GateInventoryConflictError(ValueError):
    pass


def authoritative_gate_inventory() -> tuple[GateInventoryRecord, ...]:
    config = ApprovalDiagnosticsConfig()
    inventory = (
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.EVIDENCE_SCORE,
            gate_category=GateCategory.DIRECTIONAL_EVIDENCE,
            gate_scope=GateScope.NON_ENTRY,
            description="Final evidence score must clear institutional quality.",
            authoritative_pass_fail_source="ApprovalDiagnosticsEngine._numeric_min",
            threshold_source=f"ApprovalDiagnosticsConfig.minimum_evidence_score={config.minimum_evidence_score}",
            mandatory=True,
            can_be_unavailable=False,
            missing_data_treatment=MissingDataTreatment.FAILURE,
            approval_stage="institutional gatekeeper",
            features_consumed=("strategy_score",),
            similar_feature_gates=(ApprovalCriterionId.INSTITUTIONAL_ACCEPTANCE,),
        ),
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.STOP_DISTANCE,
            gate_category=GateCategory.RISK_ECONOMICS,
            gate_scope=GateScope.NON_ENTRY,
            description="Stop distance must be economically acceptable.",
            authoritative_pass_fail_source="ApprovalDiagnosticsEngine._numeric_max",
            threshold_source=f"ApprovalDiagnosticsConfig.maximum_stop_distance_percent={config.maximum_stop_distance_percent}",
            mandatory=True,
            can_be_unavailable=True,
            missing_data_treatment=MissingDataTreatment.FAILURE,
            approval_stage="institutional gatekeeper",
            features_consumed=("confirmation_entry", "entry_zone_high", "risk_stop"),
            similar_feature_gates=(ApprovalCriterionId.STOP_AVAILABLE,),
        ),
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.HISTORICAL_SAMPLES,
            gate_category=GateCategory.HISTORICAL_EVIDENCE,
            gate_scope=GateScope.NON_ENTRY,
            description="Matched historical setup sample must be sufficient.",
            authoritative_pass_fail_source=(
                "ApprovalDiagnosticsEngine._historical_sample_criterion"
            ),
            threshold_source=f"ApprovalDiagnosticsConfig.minimum_historical_samples={config.minimum_historical_samples}",
            mandatory=True,
            can_be_unavailable=False,
            missing_data_treatment=MissingDataTreatment.FAILURE,
            approval_stage="institutional gatekeeper",
            features_consumed=("setup_type", "market_regime", "completed_outcomes"),
            similar_feature_gates=(
                ApprovalCriterionId.EXPECTANCY,
                ApprovalCriterionId.POSTERIOR_PROBABILITY,
            ),
        ),
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.STRONG_EVIDENCE_EXCEPTION,
            gate_category=GateCategory.DIRECTIONAL_EVIDENCE,
            gate_scope=GateScope.NON_ENTRY,
            description="Optional exception that can satisfy historical samples.",
            authoritative_pass_fail_source="ApprovalDiagnosticsEngine._binary",
            threshold_source=(
                "record.evidence_layers contains strong-evidence-exception"
            ),
            mandatory=False,
            can_be_unavailable=False,
            missing_data_treatment=MissingDataTreatment.NOT_APPLICABLE,
            approval_stage="institutional gatekeeper",
            features_consumed=("evidence_layers",),
            similar_feature_gates=(ApprovalCriterionId.EVIDENCE_SCORE,),
        ),
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.EXPECTANCY,
            gate_category=GateCategory.HISTORICAL_EVIDENCE,
            gate_scope=GateScope.NON_ENTRY,
            description="Historical matched setup expectancy must be positive.",
            authoritative_pass_fail_source="ApprovalDiagnosticsEngine._numeric_min",
            threshold_source=f"ApprovalDiagnosticsConfig.minimum_expectancy={config.minimum_expectancy}",
            mandatory=True,
            can_be_unavailable=True,
            missing_data_treatment=MissingDataTreatment.FAILURE,
            approval_stage="institutional gatekeeper",
            features_consumed=("setup_type", "market_regime", "forward_return"),
            similar_feature_gates=(
                ApprovalCriterionId.HISTORICAL_SAMPLES,
                ApprovalCriterionId.POSTERIOR_PROBABILITY,
            ),
        ),
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.POSTERIOR_PROBABILITY,
            gate_category=GateCategory.PROBABILITY_CALIBRATION,
            gate_scope=GateScope.NON_ENTRY,
            description="Posterior win probability must clear institutional floor.",
            authoritative_pass_fail_source="ApprovalDiagnosticsEngine._numeric_min",
            threshold_source=f"ApprovalDiagnosticsConfig.minimum_posterior_probability={config.minimum_posterior_probability}",
            mandatory=True,
            can_be_unavailable=True,
            missing_data_treatment=MissingDataTreatment.FAILURE,
            approval_stage="institutional gatekeeper",
            features_consumed=("setup_type", "market_regime", "outcome_label"),
            similar_feature_gates=(
                ApprovalCriterionId.HISTORICAL_SAMPLES,
                ApprovalCriterionId.EXPECTANCY,
            ),
        ),
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.ENTRY_AVAILABLE,
            gate_category=GateCategory.MIXED_ENTRY_AND_PLAN,
            gate_scope=GateScope.MIXED,
            description="Executable entry must be present.",
            authoritative_pass_fail_source="ApprovalDiagnosticsEngine._presence",
            threshold_source="record.confirmation_entry or record.entry_zone_high",
            mandatory=True,
            can_be_unavailable=True,
            missing_data_treatment=MissingDataTreatment.FAILURE,
            approval_stage="institutional gatekeeper",
            features_consumed=("confirmation_entry", "entry_zone_high"),
            similar_feature_gates=(ApprovalCriterionId.STOP_DISTANCE,),
        ),
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.STOP_AVAILABLE,
            gate_category=GateCategory.TRADE_PLAN_QUALITY,
            gate_scope=GateScope.NON_ENTRY,
            description="Initial risk stop must be present.",
            authoritative_pass_fail_source="ApprovalDiagnosticsEngine._presence",
            threshold_source="record.risk_stop",
            mandatory=True,
            can_be_unavailable=True,
            missing_data_treatment=MissingDataTreatment.FAILURE,
            approval_stage="institutional gatekeeper",
            features_consumed=("risk_stop",),
            similar_feature_gates=(ApprovalCriterionId.STOP_DISTANCE,),
        ),
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.TARGETS_AVAILABLE,
            gate_category=GateCategory.TRADE_PLAN_QUALITY,
            gate_scope=GateScope.NON_ENTRY,
            description="All three target levels must be present.",
            authoritative_pass_fail_source="ApprovalDiagnosticsEngine._binary",
            threshold_source="record.target_1, target_2, target_3 all present",
            mandatory=True,
            can_be_unavailable=True,
            missing_data_treatment=MissingDataTreatment.FAILURE,
            approval_stage="institutional gatekeeper",
            features_consumed=("target_1", "target_2", "target_3"),
            similar_feature_gates=(ApprovalCriterionId.STOP_DISTANCE,),
        ),
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.ATR_AVAILABLE,
            gate_category=GateCategory.TRADE_PLAN_QUALITY,
            gate_scope=GateScope.NON_ENTRY,
            description="ATR must be recorded in trailing stop plan.",
            authoritative_pass_fail_source="ApprovalDiagnosticsEngine._binary",
            threshold_source="trailing_stop_plan contains ATR",
            mandatory=True,
            can_be_unavailable=True,
            missing_data_treatment=MissingDataTreatment.FAILURE,
            approval_stage="institutional gatekeeper",
            features_consumed=("trailing_stop_plan",),
            similar_feature_gates=(ApprovalCriterionId.DMA20_INVALIDATION_AVAILABLE,),
        ),
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.DMA20_INVALIDATION_AVAILABLE,
            gate_category=GateCategory.TRADE_PLAN_QUALITY,
            gate_scope=GateScope.NON_ENTRY,
            description="20-DMA invalidation must be recorded.",
            authoritative_pass_fail_source="ApprovalDiagnosticsEngine._binary",
            threshold_source="explanation contains 20-DMA invalidation",
            mandatory=True,
            can_be_unavailable=True,
            missing_data_treatment=MissingDataTreatment.FAILURE,
            approval_stage="institutional gatekeeper",
            features_consumed=("explanation",),
            similar_feature_gates=(ApprovalCriterionId.ATR_AVAILABLE,),
        ),
        GateInventoryRecord(
            gate_id=ApprovalCriterionId.INSTITUTIONAL_ACCEPTANCE,
            gate_category=GateCategory.META_APPROVAL,
            gate_scope=GateScope.META,
            description="Aggregate institutional deployment decision.",
            authoritative_pass_fail_source="is_deployment_approved(record)",
            threshold_source="portfolio/recommendation institutional policy",
            mandatory=True,
            can_be_unavailable=False,
            missing_data_treatment=MissingDataTreatment.FAILURE,
            approval_stage="institutional gatekeeper",
            features_consumed=("candidate_decision_record",),
            similar_feature_gates=tuple(
                gate
                for gate in ApprovalCriterionId
                if gate is not ApprovalCriterionId.INSTITUTIONAL_ACCEPTANCE
            ),
        ),
    )
    _validate_inventory(inventory)
    return inventory


class NonEntryGateAttributionEngine:
    def __init__(self, config: NonEntryGateAttributionConfig | None = None) -> None:
        self.config = config or NonEntryGateAttributionConfig()

    def analyze(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> GateAttributionReport:
        inventory = authoritative_gate_inventory()
        diagnostics = ApprovalDiagnosticsEngine(
            ApprovalDiagnosticsConfig(minimum_intersection_count=1)
        ).build(records=records, outcomes=outcomes)
        timing_report = build_entry_timing_replay_report(
            records=records,
            outcomes=outcomes,
        )
        rows = _candidate_rows(
            diagnostics=diagnostics.diagnostics,
            timing_rows=timing_report.rows,
            inventory=inventory,
        )
        completed = tuple(row for row in rows if row.completed_outcome)
        primary = tuple(
            row for row in completed if row.entry_state in PRIMARY_ENTRY_STATES
        )
        secondary = tuple(
            row for row in completed if row.entry_state in SECONDARY_ENTRY_STATES
        )
        non_entry_gates = _gates_by_scope(inventory, GateScope.NON_ENTRY)
        mixed_gates = _gates_by_scope(inventory, GateScope.MIXED)
        primary_attr = tuple(
            _gate_attribution(
                gate=gate,
                rows=primary,
                universe=AttributionUniverse.PRIMARY_ACCEPTABLE_TIMING,
                inventory=inventory,
                config=self.config,
            )
            for gate in non_entry_gates
        )
        secondary_attr = tuple(
            _gate_attribution(
                gate=gate,
                rows=secondary,
                universe=AttributionUniverse.SECONDARY_CONTEXT,
                inventory=inventory,
                config=self.config,
            )
            for gate in non_entry_gates
        )
        mixed_attr = tuple(
            _gate_attribution(
                gate=gate,
                rows=completed,
                universe=AttributionUniverse.ALL_COMPLETED,
                inventory=inventory,
                config=self.config,
            )
            for gate in mixed_gates
        )
        overlap = _overlap_matrix(primary, non_entry_gates, inventory, self.config)
        incremental = _incremental_value(primary, non_entry_gates, overlap, self.config)
        interactions = _interaction_clusters(primary, non_entry_gates, self.config)
        rankings = _rankings(primary_attr, incremental, overlap)
        acceptably_timed = _acceptably_timed_analysis(primary)
        decision = _decision(primary_attr, incremental, overlap, interactions, rankings)
        raw_before = sum(1 for record in records if record.approved_for_deployment)
        strict_before = diagnostics.approved_candidates
        return GateAttributionReport(
            inventory=inventory,
            candidate_rows=completed,
            primary_attribution=primary_attr,
            secondary_attribution=secondary_attr,
            mixed_gate_attribution=mixed_attr,
            overlap_matrix=overlap,
            interaction_clusters=interactions,
            incremental_value=incremental,
            rankings=rankings,
            acceptably_timed_analysis=acceptably_timed,
            decision=decision,
            raw_approval_count_before=raw_before,
            raw_approval_count_after=raw_before,
            strict_approval_count_before=strict_before,
            strict_approval_count_after=strict_before,
            candidates_evaluated=len(records),
            completed_outcomes=len(completed),
            primary_universe_count=len(primary),
            secondary_universe_count=len(secondary),
        )


def render_gate_attribution_report(report: GateAttributionReport) -> tuple[str, ...]:
    secondary = [f"- {item.value}" for item in report.decision.secondary_conclusions]
    lines = [
        "Non-Entry Gate Attribution Intelligence",
        f"Candidates Evaluated: {report.candidates_evaluated}",
        f"Completed Outcomes: {report.completed_outcomes}",
        f"Primary Acceptably Timed Candidates: {report.primary_universe_count}",
        f"Secondary Context Candidates: {report.secondary_universe_count}",
        "Raw Approvals: "
        f"{report.raw_approval_count_before} -> {report.raw_approval_count_after}",
        "Strict Institutional Approvals: "
        f"{report.strict_approval_count_before} -> "
        f"{report.strict_approval_count_after}",
        "",
        "Authoritative Non-Entry Gate Inventory:",
        *_inventory_lines(report.inventory),
        "",
        "Primary Per-Gate Attribution:",
        *_attribution_lines(report.primary_attribution),
        "",
        "Profitable-Rejection Attribution:",
        *_opportunity_cost_lines(report.primary_attribution),
        "",
        "True-Negative Rejection Attribution:",
        *_downside_lines(report.primary_attribution),
        "",
        "Gate Rankings:",
        *_ranking_lines(report.rankings),
        "",
        "Gate Overlap Matrix:",
        *_overlap_lines(report.overlap_matrix),
        "",
        "Gate Interaction Clusters:",
        *_interaction_lines(report.interaction_clusters),
        "",
        "Acceptably Timed Candidate Analysis:",
        *_acceptable_lines(report.acceptably_timed_analysis),
        "",
        f"Primary Conclusion: {report.decision.primary_conclusion.value}",
        "Secondary Conclusions:",
        *(secondary or ["- none"]),
        f"Dominant Bottleneck: {report.decision.dominant_unresolved_bottleneck}",
        "Recommended Next Milestone: "
        f"{report.decision.recommended_next_milestone.value}",
        f"Prohibited Next Step: {report.decision.prohibited_next_step}",
        "Policy Integrity: no thresholds, gates, recommendations, timing states, "
        "trade plans, allocations, approvals, or replay decisions were changed.",
    ]
    return tuple(lines)


def group_gate_attribution_report(
    report: GateAttributionReport,
    *,
    group_by: str,
) -> tuple[str, ...]:
    if group_by == "gate":
        return _attribution_lines(report.primary_attribution)
    if group_by == "opportunity-cost":
        return _opportunity_cost_lines(report.primary_attribution)
    if group_by == "downside-protection":
        return _downside_lines(report.primary_attribution)
    if group_by == "overlap":
        return _overlap_lines(report.overlap_matrix)
    if group_by == "interactions":
        return _interaction_lines(report.interaction_clusters)
    if group_by == "ranking":
        return _ranking_lines(report.rankings)
    if group_by == "economic-impact":
        return _economic_lines(report.primary_attribution)
    if group_by == "candidate-export":
        return tuple(
            f"- {row.replay_date} {row.symbol}: {row.outcome_class.value}, "
            f"entry {row.entry_state.value}, failed "
            f"{','.join(gate.value for gate in row.failed_non_entry_gates) or 'none'}"
            for row in report.candidate_rows
        )
    raise ValueError(f"Unsupported grouping: {group_by}")


def export_gate_attribution_json(report: GateAttributionReport, path: Path) -> None:
    path.write_text(json.dumps(_report_dict(report), indent=2) + "\n", encoding="utf-8")


def export_gate_attribution_csv(report: GateAttributionReport, path: Path) -> None:
    rows = []
    for attribution_item in report.primary_attribution:
        rows.append(
            {
                "section": "primary_attribution",
                **_attribution_dict(attribution_item),
            }
        )
    for attribution_item in report.secondary_attribution:
        rows.append(
            {
                "section": "secondary_attribution",
                **_attribution_dict(attribution_item),
            }
        )
    for overlap_item in report.overlap_matrix:
        rows.append({"section": "overlap", **_overlap_dict(overlap_item)})
    for interaction_item in report.interaction_clusters:
        rows.append({"section": "interaction", **_interaction_dict(interaction_item)})
    _write_csv(rows, path)


def export_gate_candidate_audit_csv(
    rows: tuple[CandidateGateAuditRow, ...],
    path: Path,
) -> None:
    _write_csv(tuple(_candidate_dict(row) for row in rows), path)


def export_gate_candidate_audit_json(
    rows: tuple[CandidateGateAuditRow, ...],
    path: Path,
) -> None:
    path.write_text(
        json.dumps([_candidate_dict(row) for row in rows], indent=2) + "\n",
        encoding="utf-8",
    )


def _validate_inventory(inventory: tuple[GateInventoryRecord, ...]) -> None:
    seen: dict[ApprovalCriterionId, GateInventoryRecord] = {}
    for item in inventory:
        existing = seen.get(item.gate_id)
        if existing is not None and existing != item:
            raise GateInventoryConflictError(
                f"Conflicting definitions for gate {item.gate_id.value}"
            )
        seen[item.gate_id] = item
    missing = set(ApprovalCriterionId) - set(seen)
    if missing:
        missing_text = ", ".join(sorted(item.value for item in missing))
        raise GateInventoryConflictError(f"Missing gate definitions: {missing_text}")


def _gates_by_scope(
    inventory: tuple[GateInventoryRecord, ...],
    scope: GateScope,
) -> tuple[ApprovalCriterionId, ...]:
    return tuple(
        item.gate_id
        for item in inventory
        if item.gate_scope is scope
        and item.gate_id is not ApprovalCriterionId.STRONG_EVIDENCE_EXCEPTION
    )


def _candidate_rows(
    *,
    diagnostics: tuple[InstitutionalApprovalDiagnostic, ...],
    timing_rows: tuple[EntryTimingOutcomeRow, ...],
    inventory: tuple[GateInventoryRecord, ...],
) -> tuple[CandidateGateAuditRow, ...]:
    timing_by_id = {row.candidate_id: row for row in timing_rows}
    non_entry = set(_gates_by_scope(inventory, GateScope.NON_ENTRY))
    rows = []
    for diagnostic in diagnostics:
        timing = timing_by_id.get(diagnostic.candidate_id)
        if timing is None or not timing.completed_outcome:
            continue
        failed = tuple(gate for gate in diagnostic.failed_criteria if gate in non_entry)
        unique = failed[0] if len(failed) == 1 else None
        rows.append(
            CandidateGateAuditRow(
                candidate_id=diagnostic.candidate_id,
                symbol=diagnostic.symbol,
                replay_date=diagnostic.replay_date,
                outcome_class=_outcome_class(timing),
                completed_outcome=True,
                forward_return=timing.forward_return,
                mfe=timing.mfe,
                mae=timing.mae,
                target_1_hit=timing.target_1_hit,
                target_2_hit=timing.target_2_hit,
                stop_hit=timing.stop_hit,
                entry_state=timing.assessment.entry_state,
                timing_score=timing.assessment.timing_score,
                raw_approved=timing.approved,
                strict_approved=diagnostic.approved,
                failed_non_entry_gates=failed,
                uniquely_failed_gate=unique,
                primary_rejection_reason=diagnostic.primary_rejection_reason,
                secondary_rejection_reasons=diagnostic.secondary_rejection_reasons,
                final_verdict=diagnostic.final_verdict,
                setup_type=diagnostic.setup_type,
                market_regime=diagnostic.market_regime,
                sector=diagnostic.sector,
                probability=diagnostic.posterior_probability,
                historical_evidence_quality=diagnostic.evidence_completeness.value,
                trade_plan_quality=diagnostic.trade_plan_completeness.value,
                stop_distance=diagnostic.stop_distance_percent,
                support_distance=timing.assessment.distance_from_support_pct,
                reward_risk=timing.assessment.reward_risk,
                data_completeness_status=timing.assessment.data_completeness.value,
                failed_gate_count=len(failed),
                diagnostic=diagnostic,
                timing_row=timing,
            )
        )
    return tuple(
        sorted(rows, key=lambda row: (row.replay_date, row.symbol, row.candidate_id))
    )


def _gate_attribution(
    *,
    gate: ApprovalCriterionId,
    rows: tuple[CandidateGateAuditRow, ...],
    universe: AttributionUniverse,
    inventory: tuple[GateInventoryRecord, ...],
    config: NonEntryGateAttributionConfig,
) -> GateOutcomeAttribution:
    inventory_item = _inventory_item(inventory, gate)
    criteria = tuple((_criterion(row, gate), row) for row in rows)
    applicable = tuple((result, row) for result, row in criteria if result.applicable)
    passes = tuple(row for result, row in applicable if result.passed)
    failures = tuple(row for result, row in applicable if not result.passed)
    unavailable = tuple(
        (result, row) for result, row in criteria if not result.applicable
    )
    missing = tuple(
        (result, row) for result, row in criteria if not result.data_available
    )
    winners_failed = tuple(
        row for row in failures if row.outcome_class is CandidateOutcomeClass.WINNER
    )
    losers_failed = tuple(
        row for row in failures if row.outcome_class is CandidateOutcomeClass.LOSER
    )
    flats_failed = tuple(
        row for row in failures if row.outcome_class is CandidateOutcomeClass.FLAT
    )
    rejected_failures = tuple(row for row in failures if not row.strict_approved)
    profitable_rejections = tuple(
        row
        for row in rejected_failures
        if row.outcome_class is CandidateOutcomeClass.WINNER
    )
    true_negative_rejections = tuple(
        row
        for row in rejected_failures
        if row.outcome_class is CandidateOutcomeClass.LOSER
    )
    all_winners = tuple(
        row for row in rows if row.outcome_class is CandidateOutcomeClass.WINNER
    )
    all_losers = tuple(
        row for row in rows if row.outcome_class is CandidateOutcomeClass.LOSER
    )
    economic = _economic_impact(gate, failures, rows, config)
    findings = _gate_findings(
        failures=failures,
        rows=rows,
        economic=economic,
        missing_count=len(missing),
        config=config,
    )
    return GateOutcomeAttribution(
        universe=universe,
        gate_id=gate,
        gate_category=inventory_item.gate_category,
        gate_scope=inventory_item.gate_scope,
        candidates_evaluated=len(rows),
        candidates_reaching_gate=len(applicable),
        candidates_passing=len(passes),
        candidates_failing=len(failures),
        candidates_unavailable=len(unavailable),
        candidates_with_missing_inputs=len(missing),
        completed_outcomes=len(rows),
        winners_failing_gate=len(winners_failed),
        losers_failing_gate=len(losers_failed),
        flat_failing_gate=len(flats_failed),
        profitable_rejected_candidates=len(profitable_rejections),
        true_negative_rejected_candidates=len(true_negative_rejections),
        raw_approved_candidates=sum(1 for row in rows if row.raw_approved),
        strict_approved_candidates=sum(1 for row in rows if row.strict_approved),
        winner_rejection_rate=_rate(len(winners_failed), len(all_winners)),
        loser_rejection_rate=_rate(len(losers_failed), len(all_losers)),
        gate_pass_rate=_rate(len(passes), len(applicable)),
        gate_failure_rate=_rate(len(failures), len(applicable)),
        missing_data_rate=_rate(len(missing), len(rows)),
        mean_return_failures=_average(tuple(row.forward_return for row in failures)),
        median_return_failures=_median(tuple(row.forward_return for row in failures)),
        return_quartiles_failures=_quartiles(
            tuple(row.forward_return for row in failures)
        ),
        mean_return_passes=_average(tuple(row.forward_return for row in passes)),
        median_return_passes=_median(tuple(row.forward_return for row in passes)),
        winner_rate_failures=_rate(len(winners_failed), len(failures)),
        winner_rate_passes=_rate(
            sum(
                1 for row in passes if row.outcome_class is CandidateOutcomeClass.WINNER
            ),
            len(passes),
        ),
        loser_rate_failures=_rate(len(losers_failed), len(failures)),
        loser_rate_passes=_rate(
            sum(
                1 for row in passes if row.outcome_class is CandidateOutcomeClass.LOSER
            ),
            len(passes),
        ),
        average_timing_score=_average(tuple(row.timing_score for row in failures)),
        median_timing_score=_median(tuple(row.timing_score for row in failures)),
        average_planned_reward_risk=_average(
            tuple(row.reward_risk for row in failures)
        ),
        median_planned_reward_risk=_median(tuple(row.reward_risk for row in failures)),
        average_stop_distance=_average(tuple(row.stop_distance for row in failures)),
        median_stop_distance=_median(tuple(row.stop_distance for row in failures)),
        average_support_distance=_average(
            tuple(row.support_distance for row in failures)
        ),
        average_directional_confidence=_average(
            tuple(row.diagnostic.final_score for row in failures)
        ),
        average_probability=_average(tuple(row.probability for row in failures)),
        average_failed_gate_count=_average(
            tuple(Decimal(row.failed_gate_count) for row in failures)
        ),
        false_negative_attribution=_false_negative_attribution(gate, criteria),
        economic_impact=economic,
        findings=findings,
        recommendation=_recommendation(inventory_item, findings),
    )


def _economic_impact(
    gate: ApprovalCriterionId,
    failures: tuple[CandidateGateAuditRow, ...],
    all_rows: tuple[CandidateGateAuditRow, ...],
    config: NonEntryGateAttributionConfig,
) -> GateEconomicImpact:
    winners = tuple(
        row for row in failures if row.outcome_class is CandidateOutcomeClass.WINNER
    )
    losers = tuple(
        row for row in failures if row.outcome_class is CandidateOutcomeClass.LOSER
    )
    flats = tuple(
        row for row in failures if row.outcome_class is CandidateOutcomeClass.FLAT
    )
    unique_failures = tuple(row for row in all_rows if row.uniquely_failed_gate is gate)
    unique_winners = tuple(
        row
        for row in unique_failures
        if row.outcome_class is CandidateOutcomeClass.WINNER
    )
    unique_losers = tuple(
        row
        for row in unique_failures
        if row.outcome_class is CandidateOutcomeClass.LOSER
    )
    gross_missed = _positive_sum(tuple(row.forward_return for row in winners))
    gross_avoided = _loss_abs_sum(tuple(row.forward_return for row in losers))
    unique_missed = _positive_sum(tuple(row.forward_return for row in unique_winners))
    unique_avoided = _loss_abs_sum(tuple(row.forward_return for row in unique_losers))
    lower_tail = tuple(
        row.forward_return
        for row in losers
        if row.forward_return is not None
        and row.forward_return <= config.catastrophic_loss_threshold
    )
    upper_tail = tuple(
        row.forward_return for row in winners if row.forward_return is not None
    )
    return GateEconomicImpact(
        gross_missed_upside=gross_missed,
        gross_avoided_downside=gross_avoided,
        gross_net_replay_attribution=(gross_avoided - gross_missed).quantize(_FOUR),
        unique_missed_upside=unique_missed,
        unique_avoided_downside=unique_avoided,
        unique_net_replay_attribution=(unique_avoided - unique_missed).quantize(_FOUR),
        sample_count=len(failures),
        winner_count=len(winners),
        loser_count=len(losers),
        flat_count=len(flats),
        average_outcome=_average(tuple(row.forward_return for row in failures)),
        median_outcome=_median(tuple(row.forward_return for row in failures)),
        downside_tail_protection=_loss_abs_sum(lower_tail) if lower_tail else None,
        upside_tail_opportunity_cost=_percentile(upper_tail, Decimal("0.90")),
        caveats=(
            "Gates are not independently assigned.",
            "Multiple gates may fail the same candidate.",
            "Gross totals may overlap across gates.",
            "This is replay attribution, not causal proof or portfolio P&L.",
            "This must not be used directly to loosen thresholds.",
        ),
    )


def _overlap_matrix(
    rows: tuple[CandidateGateAuditRow, ...],
    gates: tuple[ApprovalCriterionId, ...],
    inventory: tuple[GateInventoryRecord, ...],
    config: NonEntryGateAttributionConfig,
) -> tuple[GateOverlapReport, ...]:
    reports = []
    total = len(rows)
    failed_by_gate = {
        gate: {row.candidate_id for row in rows if gate in row.failed_non_entry_gates}
        for gate in gates
    }
    by_id = {row.candidate_id: row for row in rows}
    for left, right in combinations(gates, 2):
        left_ids = failed_by_gate[left]
        right_ids = failed_by_gate[right]
        joint_ids = left_ids & right_ids
        union_ids = left_ids | right_ids
        joint_rows = tuple(by_id[item] for item in sorted(joint_ids))
        jaccard = _rate(len(joint_ids), len(union_ids))
        p_b_given_a = _rate(len(joint_ids), len(left_ids))
        p_a_given_b = _rate(len(joint_ids), len(right_ids))
        p_b = _rate(len(right_ids), total)
        lift = (
            (p_b_given_a / p_b).quantize(_FOUR)
            if p_b_given_a is not None and p_b is not None and p_b > _ZERO
            else None
        )
        reports.append(
            GateOverlapReport(
                gate_a=left,
                gate_b=right,
                failure_count_a=len(left_ids),
                failure_count_b=len(right_ids),
                joint_failure_count=len(joint_ids),
                union_failure_count=len(union_ids),
                overlap_percentage=p_b_given_a,
                jaccard_similarity=jaccard,
                probability_b_given_a=p_b_given_a,
                probability_a_given_b=p_a_given_b,
                lift=lift,
                joint_winner_count=sum(
                    1
                    for row in joint_rows
                    if row.outcome_class is CandidateOutcomeClass.WINNER
                ),
                joint_loser_count=sum(
                    1
                    for row in joint_rows
                    if row.outcome_class is CandidateOutcomeClass.LOSER
                ),
                average_joint_failure_return=_average(
                    tuple(row.forward_return for row in joint_rows)
                ),
                median_joint_failure_return=_median(
                    tuple(row.forward_return for row in joint_rows)
                ),
                classification=_overlap_classification(len(joint_ids), jaccard, config),
                overlap_types=_overlap_types(left, right, jaccard, inventory),
            )
        )
    return tuple(
        sorted(
            reports,
            key=lambda item: (
                -(item.joint_failure_count),
                item.gate_a.value,
                item.gate_b.value,
            ),
        )
    )


def _incremental_value(
    rows: tuple[CandidateGateAuditRow, ...],
    gates: tuple[ApprovalCriterionId, ...],
    overlap: tuple[GateOverlapReport, ...],
    config: NonEntryGateAttributionConfig,
) -> tuple[GateIncrementalValueReport, ...]:
    result = []
    for gate in gates:
        unique = tuple(row for row in rows if row.uniquely_failed_gate is gate)
        winners = tuple(
            row for row in unique if row.outcome_class is CandidateOutcomeClass.WINNER
        )
        losers = tuple(
            row for row in unique if row.outcome_class is CandidateOutcomeClass.LOSER
        )
        strongest = _strongest_overlap(gate, overlap)
        unique_loser_rate = _rate(len(losers), len(unique))
        unique_winner_rate = _rate(len(winners), len(unique))
        finding = _incremental_finding(
            sample=len(unique),
            loser_rate=unique_loser_rate,
            winner_rate=unique_winner_rate,
            strongest=strongest,
            config=config,
        )
        result.append(
            GateIncrementalValueReport(
                gate_id=gate,
                candidates_uniquely_failed=len(unique),
                winners_uniquely_failed=len(winners),
                losers_uniquely_failed=len(losers),
                unique_failure_winner_rate=unique_winner_rate,
                unique_failure_loser_rate=unique_loser_rate,
                unique_failure_mean_return=_average(
                    tuple(row.forward_return for row in unique)
                ),
                unique_failure_median_return=_median(
                    tuple(row.forward_return for row in unique)
                ),
                unique_avoided_downside=_loss_abs_sum(
                    tuple(row.forward_return for row in losers)
                ),
                unique_missed_upside=_positive_sum(
                    tuple(row.forward_return for row in winners)
                ),
                strongest_overlapping_gate=strongest[0] if strongest else None,
                adds_separation_beyond_overlap=finding
                in {
                    GateIncrementalValueFinding.HIGH_INCREMENTAL_VALUE,
                    GateIncrementalValueFinding.MODERATE_INCREMENTAL_VALUE,
                },
                finding=finding,
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda item: (
                -item.unique_avoided_downside,
                item.unique_missed_upside,
                item.gate_id.value,
            ),
        )
    )


def _interaction_clusters(
    rows: tuple[CandidateGateAuditRow, ...],
    gates: tuple[ApprovalCriterionId, ...],
    config: NonEntryGateAttributionConfig,
) -> tuple[GateInteractionCluster, ...]:
    rejected = tuple(row for row in rows if row.failed_non_entry_gates)
    counts: dict[tuple[ApprovalCriterionId, ...], list[CandidateGateAuditRow]] = (
        defaultdict(list)
    )
    for row in rejected:
        failed = tuple(gate for gate in row.failed_non_entry_gates if gate in gates)
        for size in (2, 3):
            for combo in combinations(failed, size):
                counts[tuple(sorted(combo, key=lambda gate: gate.value))].append(row)
    clusters = []
    for combo, combo_rows_list in counts.items():
        combo_rows = tuple(combo_rows_list)
        if len(combo_rows) < 2:
            continue
        winners = tuple(
            row
            for row in combo_rows
            if row.outcome_class is CandidateOutcomeClass.WINNER
        )
        losers = tuple(
            row
            for row in combo_rows
            if row.outcome_class is CandidateOutcomeClass.LOSER
        )
        clusters.append(
            GateInteractionCluster(
                gates=combo,
                combination_frequency=len(combo_rows),
                percentage_of_rejected_candidates=_rate(len(combo_rows), len(rejected)),
                winner_count=len(winners),
                loser_count=len(losers),
                winner_rate=_rate(len(winners), len(combo_rows)),
                loser_rate=_rate(len(losers), len(combo_rows)),
                mean_return=_average(tuple(row.forward_return for row in combo_rows)),
                median_return=_median(tuple(row.forward_return for row in combo_rows)),
                total_missed_upside=_positive_sum(
                    tuple(row.forward_return for row in winners)
                ),
                total_avoided_downside=_loss_abs_sum(
                    tuple(row.forward_return for row in losers)
                ),
                average_timing_score=_average(
                    tuple(row.timing_score for row in combo_rows)
                ),
                average_failed_gate_count=_average(
                    tuple(Decimal(row.failed_gate_count) for row in combo_rows)
                ),
                finding=_interaction_finding(len(combo_rows), winners, losers, config),
            )
        )
    return tuple(
        sorted(
            clusters,
            key=lambda item: (
                -item.combination_frequency,
                tuple(gate.value for gate in item.gates),
            ),
        )[:10]
    )


def _rankings(
    attribution: tuple[GateOutcomeAttribution, ...],
    incremental: tuple[GateIncrementalValueReport, ...],
    overlap: tuple[GateOverlapReport, ...],
) -> GateRankingReport:
    return GateRankingReport(
        downside_protection=tuple(
            item.gate_id
            for item in sorted(
                attribution,
                key=lambda item: (
                    -item.economic_impact.unique_avoided_downside,
                    -(item.loser_rejection_rate or _ZERO),
                    item.gate_id.value,
                ),
            )
        ),
        opportunity_cost=tuple(
            item.gate_id
            for item in sorted(
                attribution,
                key=lambda item: (
                    -item.economic_impact.unique_missed_upside,
                    -item.profitable_rejected_candidates,
                    item.gate_id.value,
                ),
            )
        ),
        incremental_information=tuple(item.gate_id for item in incremental),
        redundancy=tuple(
            (item.gate_a, item.gate_b)
            for item in sorted(
                overlap,
                key=lambda item: (
                    -(item.jaccard_similarity or _ZERO),
                    -item.joint_failure_count,
                    item.gate_a.value,
                    item.gate_b.value,
                ),
            )[:10]
        ),
        missing_data_burden=tuple(
            item.gate_id
            for item in sorted(
                attribution,
                key=lambda item: (
                    -(item.missing_data_rate or _ZERO),
                    -item.candidates_with_missing_inputs,
                    item.gate_id.value,
                ),
            )
        ),
    )


def _acceptably_timed_analysis(
    rows: tuple[CandidateGateAuditRow, ...],
) -> AcceptablyTimedCandidateAnalysis:
    return AcceptablyTimedCandidateAnalysis(
        candidate_count=len(rows),
        completed_outcomes=len(rows),
        entry_state_counts=_enum_counts(rows, lambda row: row.entry_state),
        verdict_counts=_text_counts(rows, lambda row: row.final_verdict),
        setup_type_counts=_text_counts(rows, lambda row: row.setup_type or "UNKNOWN"),
        market_regime_counts=_text_counts(
            rows, lambda row: row.market_regime or "UNKNOWN"
        ),
        sector_counts=_text_counts(rows, lambda row: row.sector or "UNKNOWN"),
        evidence_quality_counts=_text_counts(
            rows, lambda row: row.historical_evidence_quality
        ),
        probability_band_counts=_text_counts(
            rows, lambda row: _probability_band(row.probability)
        ),
        trade_plan_quality_counts=_text_counts(
            rows, lambda row: row.trade_plan_quality
        ),
        dominant_failed_gates=tuple(
            Counter(
                gate for row in rows for gate in row.failed_non_entry_gates
            ).most_common(10)
        ),
    )


def _decision(
    attribution: tuple[GateOutcomeAttribution, ...],
    incremental: tuple[GateIncrementalValueReport, ...],
    overlap: tuple[GateOverlapReport, ...],
    interactions: tuple[GateInteractionCluster, ...],
    rankings: GateRankingReport,
) -> GateAttributionDecision:
    secondary: list[GateAttributionConclusion] = []
    protective = _first_gate(rankings.downside_protection)
    opportunity = _first_gate(rankings.opportunity_cost)
    incremental_gate = _first_gate(rankings.incremental_information)
    overlap_pair = rankings.redundancy[0] if rankings.redundancy else None
    dominant_cluster = interactions[0].gates if interactions else ()
    evidence_gate = _find_attr(attribution, ApprovalCriterionId.EVIDENCE_SCORE)
    probability_gate = _find_attr(
        attribution, ApprovalCriterionId.POSTERIOR_PROBABILITY
    )
    historical_gate = _find_attr(attribution, ApprovalCriterionId.HISTORICAL_SAMPLES)
    trade_plan_burden = sum(
        item.candidates_failing
        for item in attribution
        if item.gate_category is GateCategory.TRADE_PLAN_QUALITY
    )
    highest_missing = max(
        (item.candidates_with_missing_inputs for item in attribution),
        default=0,
    )
    if not attribution or sum(item.candidates_evaluated for item in attribution) == 0:
        primary = GateAttributionConclusion.INSUFFICIENT_EVIDENCE
        next_milestone = NextGateAttributionMilestone.COLLECT_MORE_REPLAY_EVIDENCE
        bottleneck = "insufficient completed acceptable-timing candidates"
    elif evidence_gate and (evidence_gate.winner_rate_failures or _ZERO) >= Decimal(
        "0.25"
    ):
        primary = (
            GateAttributionConclusion.DIRECTIONAL_SIGNAL_QUALITY_IS_PRIMARY_BOTTLENECK
        )
        next_milestone = NextGateAttributionMilestone.DIRECTIONAL_SIGNAL_QUALITY_AUDIT
        bottleneck = "directional evidence rejects many winners and losers"
    elif probability_gate and probability_gate.candidates_with_missing_inputs > 0:
        primary = (
            GateAttributionConclusion.PROBABILITY_CALIBRATION_REQUIRES_INVESTIGATION
        )
        next_milestone = NextGateAttributionMilestone.PROBABILITY_CALIBRATION_AUDIT
        bottleneck = "posterior probability coverage/calibration"
    elif historical_gate and historical_gate.candidates_with_missing_inputs > 0:
        primary = GateAttributionConclusion.HISTORICAL_EVIDENCE_REQUIRES_INVESTIGATION
        next_milestone = NextGateAttributionMilestone.HISTORICAL_EVIDENCE_QUALITY_AUDIT
        bottleneck = "historical evidence quality"
    elif trade_plan_burden > 0:
        primary = GateAttributionConclusion.TRADE_PLAN_QUALITY_REQUIRES_INVESTIGATION
        next_milestone = NextGateAttributionMilestone.TRADE_PLAN_GATE_AUDIT
        bottleneck = "trade-plan quality gates"
    elif highest_missing > 0:
        primary = GateAttributionConclusion.DATA_COMPLETENESS_IS_PRIMARY_BOTTLENECK
        next_milestone = NextGateAttributionMilestone.DATA_COMPLETENESS_REMEDIATION
        bottleneck = "missing gate inputs"
    else:
        primary = GateAttributionConclusion.MIXED_GATE_AND_SIGNAL_QUALITY_PROBLEM
        next_milestone = NextGateAttributionMilestone.DIRECTIONAL_SIGNAL_QUALITY_AUDIT
        bottleneck = "mixed gate and signal quality"
    if overlap and (overlap[0].jaccard_similarity or _ZERO) >= Decimal("0.40"):
        secondary.append(GateAttributionConclusion.NON_ENTRY_GATE_REDUNDANCY_DOMINATES)
    if opportunity:
        secondary.append(
            GateAttributionConclusion.NON_ENTRY_GATES_HAVE_HIGH_FALSE_NEGATIVE_BURDEN
        )
    if protective:
        secondary.append(
            GateAttributionConclusion.NON_ENTRY_GATES_PROVIDE_MEANINGFUL_PROTECTION
        )
    return GateAttributionDecision(
        primary_conclusion=primary,
        secondary_conclusions=tuple(dict.fromkeys(secondary)),
        strongest_protective_gate=protective,
        highest_opportunity_cost_gate=opportunity,
        strongest_incremental_gate=incremental_gate,
        most_overlapping_gate_pair=overlap_pair,
        dominant_rejection_cluster=dominant_cluster,
        dominant_unresolved_bottleneck=bottleneck,
        recommended_next_milestone=next_milestone,
        prohibited_next_step=(
            "Do not lower thresholds, remove gates, auto-approve candidates, "
            "change allocation, or proceed directly to Dynamic Entry Zone "
            "Optimization from this diagnostic milestone."
        ),
    )


def _criterion(
    row: CandidateGateAuditRow,
    gate: ApprovalCriterionId,
) -> InstitutionalApprovalCriterionResult:
    return next(
        result
        for result in row.diagnostic.criterion_results
        if result.criterion_id is gate
    )


def _outcome_class(row: EntryTimingOutcomeRow) -> CandidateOutcomeClass:
    if row.forward_return is None or row.forward_return == _ZERO:
        return CandidateOutcomeClass.FLAT
    if row.forward_return > _ZERO:
        return CandidateOutcomeClass.WINNER
    return CandidateOutcomeClass.LOSER


def _inventory_item(
    inventory: tuple[GateInventoryRecord, ...],
    gate: ApprovalCriterionId,
) -> GateInventoryRecord:
    return next(item for item in inventory if item.gate_id is gate)


def _false_negative_attribution(
    gate: ApprovalCriterionId,
    criteria: tuple[
        tuple[InstitutionalApprovalCriterionResult, CandidateGateAuditRow], ...
    ],
) -> tuple[FalseNegativeAttribution, ...]:
    flags = []
    for result, row in criteria:
        if row.outcome_class is not CandidateOutcomeClass.WINNER:
            continue
        if not result.applicable:
            flags.append(FalseNegativeAttribution.GATE_UNAVAILABLE_ON_WINNER)
        elif not result.passed and row.uniquely_failed_gate is gate:
            flags.append(FalseNegativeAttribution.GATE_UNIQUELY_FAILED_ON_WINNER)
        elif not result.passed:
            flags.append(
                FalseNegativeAttribution.GATE_FAILED_WITH_OTHER_GATES_ON_WINNER
            )
            flags.append(FalseNegativeAttribution.GATE_FAILED_ON_WINNER)
    return tuple(dict.fromkeys(flags))


def _gate_findings(
    *,
    failures: tuple[CandidateGateAuditRow, ...],
    rows: tuple[CandidateGateAuditRow, ...],
    economic: GateEconomicImpact,
    missing_count: int,
    config: NonEntryGateAttributionConfig,
) -> tuple[GateAttributionFinding, ...]:
    if len(rows) < config.minimum_gate_sample:
        findings = [GateAttributionFinding.INSUFFICIENT_EVIDENCE]
        if missing_count:
            findings.append(GateAttributionFinding.GATE_IS_DATA_LIMITED)
        return tuple(findings)
    findings = []
    winner_rate = _rate(
        sum(1 for row in failures if row.outcome_class is CandidateOutcomeClass.WINNER),
        len(failures),
    )
    loser_rate = _rate(
        sum(1 for row in failures if row.outcome_class is CandidateOutcomeClass.LOSER),
        len(failures),
    )
    if (loser_rate or _ZERO) >= config.protective_loser_rejection_rate:
        findings.append(GateAttributionFinding.GATE_PROVIDES_DOWNSIDE_PROTECTION)
    if (winner_rate or _ZERO) >= config.high_false_negative_rate:
        findings.append(GateAttributionFinding.GATE_HAS_HIGH_FALSE_NEGATIVE_BURDEN)
    if economic.unique_avoided_downside > economic.unique_missed_upside:
        findings.append(GateAttributionFinding.GATE_ADDS_INCREMENTAL_INFORMATION)
    if abs((winner_rate or _ZERO) - (loser_rate or _ZERO)) <= Decimal("0.05"):
        findings.append(GateAttributionFinding.GATE_HAS_LOW_OUTCOME_SEPARATION)
    if missing_count:
        findings.append(GateAttributionFinding.GATE_IS_DATA_LIMITED)
    return tuple(dict.fromkeys(findings)) or (
        GateAttributionFinding.INSUFFICIENT_EVIDENCE,
    )


def _recommendation(
    inventory_item: GateInventoryRecord,
    findings: tuple[GateAttributionFinding, ...],
) -> GateInvestigationRecommendation:
    if GateAttributionFinding.GATE_IS_DATA_LIMITED in findings:
        if inventory_item.gate_category is GateCategory.PROBABILITY_CALIBRATION:
            return GateInvestigationRecommendation.INVESTIGATE_PROBABILITY_CALIBRATION
        if inventory_item.gate_category is GateCategory.HISTORICAL_EVIDENCE:
            return (
                GateInvestigationRecommendation.INVESTIGATE_HISTORICAL_EVIDENCE_QUALITY
            )
        return GateInvestigationRecommendation.INVESTIGATE_GATE_INPUT_DATA
    if GateAttributionFinding.GATE_HAS_HIGH_FALSE_NEGATIVE_BURDEN in findings:
        return GateInvestigationRecommendation.INVESTIGATE_GATE_FURTHER
    if inventory_item.gate_category is GateCategory.TRADE_PLAN_QUALITY:
        return GateInvestigationRecommendation.INVESTIGATE_TRADE_PLAN_QUALITY
    if inventory_item.gate_category is GateCategory.DIRECTIONAL_EVIDENCE:
        return GateInvestigationRecommendation.INVESTIGATE_DIRECTIONAL_SIGNAL_QUALITY
    return GateInvestigationRecommendation.KEEP_GATE_UNCHANGED


def _overlap_classification(
    joint: int,
    jaccard: Decimal | None,
    config: NonEntryGateAttributionConfig,
) -> GateOverlapClassification:
    if joint < config.minimum_overlap_sample or jaccard is None:
        return GateOverlapClassification.INSUFFICIENT_SAMPLE
    if jaccard >= config.highly_redundant_jaccard:
        return GateOverlapClassification.HIGHLY_REDUNDANT
    if jaccard >= config.partially_redundant_jaccard:
        return GateOverlapClassification.PARTIALLY_REDUNDANT
    return GateOverlapClassification.MOSTLY_INDEPENDENT


def _overlap_types(
    left: ApprovalCriterionId,
    right: ApprovalCriterionId,
    jaccard: Decimal | None,
    inventory: tuple[GateInventoryRecord, ...],
) -> tuple[GateOverlapType, ...]:
    left_item = _inventory_item(inventory, left)
    right_item = _inventory_item(inventory, right)
    types = [GateOverlapType.OUTCOME_OVERLAP]
    if (
        right in left_item.similar_feature_gates
        or left in right_item.similar_feature_gates
    ):
        types.append(GateOverlapType.FEATURE_OVERLAP)
    if (jaccard or _ZERO) >= Decimal("0.40"):
        types.append(GateOverlapType.DECISION_OVERLAP)
    if (
        GateOverlapType.FEATURE_OVERLAP in types
        and GateOverlapType.DECISION_OVERLAP in types
    ):
        types.append(GateOverlapType.POSSIBLE_REDUNDANCY)
    return tuple(types)


def _strongest_overlap(
    gate: ApprovalCriterionId,
    overlap: tuple[GateOverlapReport, ...],
) -> tuple[ApprovalCriterionId, Decimal] | None:
    candidates = []
    for item in overlap:
        if item.gate_a is gate and item.jaccard_similarity is not None:
            candidates.append((item.gate_b, item.jaccard_similarity))
        elif item.gate_b is gate and item.jaccard_similarity is not None:
            candidates.append((item.gate_a, item.jaccard_similarity))
    return max(candidates, key=lambda item: item[1], default=None)


def _incremental_finding(
    *,
    sample: int,
    loser_rate: Decimal | None,
    winner_rate: Decimal | None,
    strongest: tuple[ApprovalCriterionId, Decimal] | None,
    config: NonEntryGateAttributionConfig,
) -> GateIncrementalValueFinding:
    if sample < config.minimum_overlap_sample:
        return GateIncrementalValueFinding.INSUFFICIENT_EVIDENCE
    if strongest and strongest[1] >= config.highly_redundant_jaccard:
        return GateIncrementalValueFinding.POSSIBLE_DUPLICATE_GATE
    spread = (loser_rate or _ZERO) - (winner_rate or _ZERO)
    if spread >= Decimal("0.40"):
        return GateIncrementalValueFinding.HIGH_INCREMENTAL_VALUE
    if spread >= Decimal("0.20"):
        return GateIncrementalValueFinding.MODERATE_INCREMENTAL_VALUE
    if spread > _ZERO:
        return GateIncrementalValueFinding.LOW_INCREMENTAL_VALUE
    return GateIncrementalValueFinding.NO_OBSERVABLE_INCREMENTAL_VALUE


def _interaction_finding(
    sample: int,
    winners: tuple[CandidateGateAuditRow, ...],
    losers: tuple[CandidateGateAuditRow, ...],
    config: NonEntryGateAttributionConfig,
) -> GateInteractionFinding:
    if sample < config.minimum_overlap_sample:
        return GateInteractionFinding.INSUFFICIENT_INTERACTION_SAMPLE
    winner_rate = _rate(len(winners), sample) or _ZERO
    loser_rate = _rate(len(losers), sample) or _ZERO
    if loser_rate >= Decimal("0.60"):
        return GateInteractionFinding.PROTECTIVE_INTERACTION
    if winner_rate >= Decimal("0.30"):
        return GateInteractionFinding.HIGH_FALSE_NEGATIVE_INTERACTION
    if abs(winner_rate - loser_rate) <= Decimal("0.10"):
        return GateInteractionFinding.POSSIBLE_DUPLICATION_CLUSTER
    return GateInteractionFinding.MIXED_INTERACTION


def _find_attr(
    attribution: tuple[GateOutcomeAttribution, ...],
    gate: ApprovalCriterionId,
) -> GateOutcomeAttribution | None:
    return next((item for item in attribution if item.gate_id is gate), None)


def _first_gate(items: tuple[ApprovalCriterionId, ...]) -> ApprovalCriterionId | None:
    return items[0] if items else None


def _average(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    return (sum(present, _ZERO) / Decimal(len(present))).quantize(_FOUR)


def _median(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(sorted(value for value in values if value is not None))
    if not present:
        return None
    return Decimal(str(median(present))).quantize(_FOUR)


def _quartiles(
    values: tuple[Decimal | None, ...],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    present = tuple(sorted(value for value in values if value is not None))
    if not present:
        return (None, None, None)
    q1 = present[int((len(present) - 1) * Decimal("0.25"))]
    q2 = Decimal(str(median(present))).quantize(_FOUR)
    q3 = present[int((len(present) - 1) * Decimal("0.75"))]
    return (q1.quantize(_FOUR), q2, q3.quantize(_FOUR))


def _percentile(
    values: tuple[Decimal | None, ...],
    percentile: Decimal,
) -> Decimal | None:
    present = tuple(sorted(value for value in values if value is not None))
    if not present:
        return None
    index = int((len(present) - 1) * percentile)
    return present[index].quantize(_FOUR)


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(_FOUR)


def _positive_sum(values: tuple[Decimal | None, ...]) -> Decimal:
    return sum(
        (value for value in values if value is not None and value > _ZERO), _ZERO
    ).quantize(_FOUR)


def _loss_abs_sum(values: tuple[Decimal | None, ...]) -> Decimal:
    return sum(
        (abs(value) for value in values if value is not None and value < _ZERO), _ZERO
    ).quantize(_FOUR)


def _enum_counts(
    rows: tuple[CandidateGateAuditRow, ...],
    getter: Callable[[CandidateGateAuditRow], EntryTimingState],
) -> tuple[tuple[EntryTimingState, int], ...]:
    counts: Counter[EntryTimingState] = Counter(getter(row) for row in rows)
    return tuple(sorted(counts.items(), key=lambda item: item[0].value))


def _text_counts(
    rows: tuple[CandidateGateAuditRow, ...],
    getter: Callable[[CandidateGateAuditRow], str],
) -> tuple[tuple[str, int], ...]:
    counts: Counter[str] = Counter(getter(row) for row in rows)
    return tuple(sorted(counts.items()))


def _probability_band(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    if value >= Decimal("0.60"):
        return ">=0.60"
    if value >= Decimal("0.52"):
        return "0.52-0.59"
    return "<0.52"


def _inventory_lines(inventory: tuple[GateInventoryRecord, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.gate_id.value}: {item.gate_category.value}, "
        f"scope {item.gate_scope.value}, threshold {item.threshold_source}"
        for item in inventory
        if item.gate_scope is not GateScope.META
    )


def _attribution_lines(items: tuple[GateOutcomeAttribution, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.gate_id.value}: fail {item.candidates_failing}/"
        f"{item.candidates_reaching_gate}, winners failed "
        f"{item.winners_failing_gate}, losers failed {item.losers_failing_gate}, "
        f"failure return mean {_metric(item.mean_return_failures)}"
        for item in items
    )


def _opportunity_cost_lines(
    items: tuple[GateOutcomeAttribution, ...],
) -> tuple[str, ...]:
    return tuple(
        f"- {item.gate_id.value}: profitable rejected "
        f"{item.profitable_rejected_candidates}, unique missed upside "
        f"{item.economic_impact.unique_missed_upside}, gross missed upside "
        f"{item.economic_impact.gross_missed_upside}"
        for item in sorted(
            items,
            key=lambda item: (
                -item.economic_impact.unique_missed_upside,
                item.gate_id.value,
            ),
        )
    )


def _downside_lines(items: tuple[GateOutcomeAttribution, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.gate_id.value}: true-negative rejected "
        f"{item.true_negative_rejected_candidates}, unique avoided downside "
        f"{item.economic_impact.unique_avoided_downside}, gross avoided downside "
        f"{item.economic_impact.gross_avoided_downside}"
        for item in sorted(
            items,
            key=lambda item: (
                -item.economic_impact.unique_avoided_downside,
                item.gate_id.value,
            ),
        )
    )


def _ranking_lines(rankings: GateRankingReport) -> tuple[str, ...]:
    return (
        "- Downside Protection: " + _gate_list(rankings.downside_protection[:5]),
        "- Opportunity Cost: " + _gate_list(rankings.opportunity_cost[:5]),
        "- Incremental Information: "
        + _gate_list(rankings.incremental_information[:5]),
        "- Redundancy: "
        + ", ".join(
            f"{left.value}+{right.value}" for left, right in rankings.redundancy[:5]
        ),
        "- Missing Data Burden: " + _gate_list(rankings.missing_data_burden[:5]),
    )


def _overlap_lines(items: tuple[GateOverlapReport, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.gate_a.value} + {item.gate_b.value}: joint "
        f"{item.joint_failure_count}, jaccard {_metric(item.jaccard_similarity)}, "
        f"{item.classification.value}"
        for item in items[:12]
    ) or ("- none",)


def _interaction_lines(items: tuple[GateInteractionCluster, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {' + '.join(gate.value for gate in item.gates)}: "
        f"count {item.combination_frequency}, winners {item.winner_count}, "
        f"losers {item.loser_count}, {item.finding.value}"
        for item in items
    ) or ("- none",)


def _economic_lines(items: tuple[GateOutcomeAttribution, ...]) -> tuple[str, ...]:
    return tuple(
        f"- {item.gate_id.value}: gross net "
        f"{item.economic_impact.gross_net_replay_attribution}, unique net "
        f"{item.economic_impact.unique_net_replay_attribution}"
        for item in items
    )


def _acceptable_lines(analysis: AcceptablyTimedCandidateAnalysis) -> tuple[str, ...]:
    return (
        f"- Candidates: {analysis.candidate_count}",
        "- Entry States: " + _pair_list(analysis.entry_state_counts),
        "- Verdicts: " + _pair_list(analysis.verdict_counts),
        "- Setup Types: " + _pair_list(analysis.setup_type_counts),
        "- Market Regimes: " + _pair_list(analysis.market_regime_counts),
        "- Dominant Failed Gates: " + _gate_count_list(analysis.dominant_failed_gates),
    )


def _gate_list(items: tuple[ApprovalCriterionId, ...]) -> str:
    return ", ".join(item.value for item in items) or "none"


def _pair_list(items: tuple[tuple[object, int], ...]) -> str:
    return (
        ", ".join(
            f"{key.value if isinstance(key, StrEnum) else key}: {value}"
            for key, value in items
        )
        or "none"
    )


def _gate_count_list(items: tuple[tuple[ApprovalCriterionId, int], ...]) -> str:
    return ", ".join(f"{gate.value}: {count}" for gate, count in items) or "none"


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _pct(value: Decimal | None) -> str:
    return (
        "unavailable"
        if value is None
        else f"{(value * Decimal('100')).quantize(_TWO)}%"
    )


def _report_dict(report: GateAttributionReport) -> dict[str, object]:
    return {
        "candidates_evaluated": report.candidates_evaluated,
        "completed_outcomes": report.completed_outcomes,
        "primary_universe_count": report.primary_universe_count,
        "secondary_universe_count": report.secondary_universe_count,
        "raw_approval_count_before": report.raw_approval_count_before,
        "raw_approval_count_after": report.raw_approval_count_after,
        "strict_approval_count_before": report.strict_approval_count_before,
        "strict_approval_count_after": report.strict_approval_count_after,
        "inventory": [_inventory_dict(item) for item in report.inventory],
        "primary_attribution": [
            _attribution_dict(item) for item in report.primary_attribution
        ],
        "secondary_attribution": [
            _attribution_dict(item) for item in report.secondary_attribution
        ],
        "overlap_matrix": [_overlap_dict(item) for item in report.overlap_matrix],
        "interaction_clusters": [
            _interaction_dict(item) for item in report.interaction_clusters
        ],
        "incremental_value": [
            _incremental_dict(item) for item in report.incremental_value
        ],
        "primary_conclusion": report.decision.primary_conclusion.value,
        "secondary_conclusions": [
            item.value for item in report.decision.secondary_conclusions
        ],
        "recommended_next_milestone": (
            report.decision.recommended_next_milestone.value
        ),
    }


def _inventory_dict(item: GateInventoryRecord) -> dict[str, object]:
    return {
        "gate_id": item.gate_id.value,
        "gate_category": item.gate_category.value,
        "gate_scope": item.gate_scope.value,
        "description": item.description,
        "authoritative_pass_fail_source": item.authoritative_pass_fail_source,
        "threshold_source": item.threshold_source,
        "mandatory": item.mandatory,
        "can_be_unavailable": item.can_be_unavailable,
        "missing_data_treatment": item.missing_data_treatment.value,
        "approval_stage": item.approval_stage,
        "features_consumed": list(item.features_consumed),
        "similar_feature_gates": [gate.value for gate in item.similar_feature_gates],
    }


def _attribution_dict(item: GateOutcomeAttribution) -> dict[str, object]:
    return {
        "universe": item.universe.value,
        "gate_id": item.gate_id.value,
        "gate_category": item.gate_category.value,
        "gate_scope": item.gate_scope.value,
        "candidates_evaluated": item.candidates_evaluated,
        "candidates_reaching_gate": item.candidates_reaching_gate,
        "candidates_passing": item.candidates_passing,
        "candidates_failing": item.candidates_failing,
        "candidates_unavailable": item.candidates_unavailable,
        "candidates_with_missing_inputs": item.candidates_with_missing_inputs,
        "winners_failing_gate": item.winners_failing_gate,
        "losers_failing_gate": item.losers_failing_gate,
        "profitable_rejected_candidates": item.profitable_rejected_candidates,
        "true_negative_rejected_candidates": item.true_negative_rejected_candidates,
        "winner_rejection_rate": _text(item.winner_rejection_rate),
        "loser_rejection_rate": _text(item.loser_rejection_rate),
        "gate_pass_rate": _text(item.gate_pass_rate),
        "gate_failure_rate": _text(item.gate_failure_rate),
        "missing_data_rate": _text(item.missing_data_rate),
        "mean_return_failures": _text(item.mean_return_failures),
        "median_return_failures": _text(item.median_return_failures),
        "mean_return_passes": _text(item.mean_return_passes),
        "median_return_passes": _text(item.median_return_passes),
        "gross_missed_upside": str(item.economic_impact.gross_missed_upside),
        "gross_avoided_downside": str(item.economic_impact.gross_avoided_downside),
        "unique_missed_upside": str(item.economic_impact.unique_missed_upside),
        "unique_avoided_downside": str(item.economic_impact.unique_avoided_downside),
        "findings": [finding.value for finding in item.findings],
        "recommendation": item.recommendation.value,
    }


def _overlap_dict(item: GateOverlapReport) -> dict[str, object]:
    return {
        "gate_a": item.gate_a.value,
        "gate_b": item.gate_b.value,
        "failure_count_a": item.failure_count_a,
        "failure_count_b": item.failure_count_b,
        "joint_failure_count": item.joint_failure_count,
        "union_failure_count": item.union_failure_count,
        "jaccard_similarity": _text(item.jaccard_similarity),
        "probability_b_given_a": _text(item.probability_b_given_a),
        "probability_a_given_b": _text(item.probability_a_given_b),
        "lift": _text(item.lift),
        "joint_winner_count": item.joint_winner_count,
        "joint_loser_count": item.joint_loser_count,
        "classification": item.classification.value,
        "overlap_types": [kind.value for kind in item.overlap_types],
    }


def _interaction_dict(item: GateInteractionCluster) -> dict[str, object]:
    return {
        "gates": [gate.value for gate in item.gates],
        "combination_frequency": item.combination_frequency,
        "percentage_of_rejected_candidates": _text(
            item.percentage_of_rejected_candidates
        ),
        "winner_count": item.winner_count,
        "loser_count": item.loser_count,
        "winner_rate": _text(item.winner_rate),
        "loser_rate": _text(item.loser_rate),
        "mean_return": _text(item.mean_return),
        "median_return": _text(item.median_return),
        "total_missed_upside": str(item.total_missed_upside),
        "total_avoided_downside": str(item.total_avoided_downside),
        "finding": item.finding.value,
    }


def _incremental_dict(item: GateIncrementalValueReport) -> dict[str, object]:
    return {
        "gate_id": item.gate_id.value,
        "candidates_uniquely_failed": item.candidates_uniquely_failed,
        "winners_uniquely_failed": item.winners_uniquely_failed,
        "losers_uniquely_failed": item.losers_uniquely_failed,
        "unique_failure_winner_rate": _text(item.unique_failure_winner_rate),
        "unique_failure_loser_rate": _text(item.unique_failure_loser_rate),
        "unique_avoided_downside": str(item.unique_avoided_downside),
        "unique_missed_upside": str(item.unique_missed_upside),
        "strongest_overlapping_gate": (
            item.strongest_overlapping_gate.value
            if item.strongest_overlapping_gate
            else None
        ),
        "finding": item.finding.value,
    }


def _candidate_dict(row: CandidateGateAuditRow) -> dict[str, object]:
    return {
        "candidate_id": row.candidate_id,
        "symbol": row.symbol,
        "replay_date": row.replay_date.isoformat(),
        "completed_outcome": row.completed_outcome,
        "realised_return": _text(row.forward_return),
        "outcome_class": row.outcome_class.value,
        "entry_timing_state": row.entry_state.value,
        "timing_score": str(row.timing_score),
        "raw_approval": row.raw_approved,
        "strict_institutional_approval": row.strict_approved,
        "failed_non_entry_gates": [gate.value for gate in row.failed_non_entry_gates],
        "uniquely_failed_gate": (
            row.uniquely_failed_gate.value if row.uniquely_failed_gate else None
        ),
        "primary_rejection_reason": row.primary_rejection_reason.value,
        "secondary_rejection_reasons": [
            reason.value for reason in row.secondary_rejection_reasons
        ],
        "final_verdict": row.final_verdict,
        "setup_type": row.setup_type,
        "market_regime": row.market_regime,
        "sector": row.sector,
        "probability": _text(row.probability),
        "historical_evidence_quality": row.historical_evidence_quality,
        "trade_plan_quality": row.trade_plan_quality,
        "stop_distance": _text(row.stop_distance),
        "support_distance": _text(row.support_distance),
        "reward_risk": _text(row.reward_risk),
        "data_completeness_status": row.data_completeness_status,
    }


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _write_csv(
    rows: tuple[dict[str, object], ...] | list[dict[str, object]], path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
