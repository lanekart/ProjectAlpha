from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from statistics import median, pstdev
from typing import Any

from alpha.historical_replay.breakout_reference import (
    BreakoutReferenceMethod,
    BreakoutReferenceReconstructionRecord,
    apply_reconstructed_breakout_references,
)
from alpha.historical_replay.confirmation_intelligence import (
    ConfirmationIntelligenceReport,
    RetestState,
    build_confirmation_intelligence_report,
)
from alpha.historical_replay.opportunity_evolution import (
    OpportunityObservation,
    OpportunityPath,
    build_opportunity_evolution_report,
)
from alpha.historical_replay.precision_frontier import (
    DirectionalLabel,
    DirectionalObservation,
    DirectionalOutcomeDefinition,
    DirectionalOutcomeFamily,
    deterministic_research_observations,
    effective_sample_size,
    label_directional_outcome,
    wilson_interval,
)


class BreakoutEvidenceGroup(StrEnum):
    PRICE_STRUCTURE_EVIDENCE = "PRICE_STRUCTURE_EVIDENCE"
    VOLUME_EVIDENCE = "VOLUME_EVIDENCE"
    RELATIVE_STRENGTH_EVIDENCE = "RELATIVE_STRENGTH_EVIDENCE"
    PARTICIPATION_EVIDENCE = "PARTICIPATION_EVIDENCE"
    SUPPORT_RESISTANCE_EVIDENCE = "SUPPORT_RESISTANCE_EVIDENCE"
    VOLATILITY_EVIDENCE = "VOLATILITY_EVIDENCE"
    RETEST_EVIDENCE = "RETEST_EVIDENCE"
    REGIME_EVIDENCE = "REGIME_EVIDENCE"
    SECTOR_EVIDENCE = "SECTOR_EVIDENCE"
    TRADE_PLAN_EVIDENCE = "TRADE_PLAN_EVIDENCE"
    GAP_EVIDENCE = "GAP_EVIDENCE"
    DATA_QUALITY_EVIDENCE = "DATA_QUALITY_EVIDENCE"


class BreakoutClass(StrEnum):
    NO_BREAKOUT = "NO_BREAKOUT"
    BREAKOUT_FORMING = "BREAKOUT_FORMING"
    PREMATURE_BREAKOUT = "PREMATURE_BREAKOUT"
    HEALTHY_BREAKOUT = "HEALTHY_BREAKOUT"
    WEAK_BREAKOUT = "WEAK_BREAKOUT"
    UNCONFIRMED_BREAKOUT = "UNCONFIRMED_BREAKOUT"
    GAP_BREAKOUT = "GAP_BREAKOUT"
    RANGE_BREAKOUT = "RANGE_BREAKOUT"
    RETEST_BREAKOUT = "RETEST_BREAKOUT"
    LATE_BREAKOUT = "LATE_BREAKOUT"
    EXTENDED_BREAKOUT = "EXTENDED_BREAKOUT"
    EXHAUSTED_BREAKOUT = "EXHAUSTED_BREAKOUT"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"
    AMBIGUOUS_BREAKOUT = "AMBIGUOUS_BREAKOUT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class BreakoutConfidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class BreakoutReasonCode(StrEnum):
    RESISTANCE_NOT_CLEARED = "RESISTANCE_NOT_CLEARED"
    APPROACHING_RESISTANCE = "APPROACHING_RESISTANCE"
    STRUCTURE_IMPROVING_BUT_CONFIRMATION_INCOMPLETE = (
        "STRUCTURE_IMPROVING_BUT_CONFIRMATION_INCOMPLETE"
    )
    RESISTANCE_CLEARED_WITH_CONFIRMATION = "RESISTANCE_CLEARED_WITH_CONFIRMATION"
    RESISTANCE_CLEARED_WITH_CONTRADICTIONS = "RESISTANCE_CLEARED_WITH_CONTRADICTIONS"
    CLEARED_BUT_UNCONFIRMED = "CLEARED_BUT_UNCONFIRMED"
    GAP_DOMINANT_BREAKOUT = "GAP_DOMINANT_BREAKOUT"
    RANGE_EXPANSION_DOMINANT = "RANGE_EXPANSION_DOMINANT"
    CONTROLLED_RETEST_HELD = "CONTROLLED_RETEST_HELD"
    LATE_CONFIRMATION = "LATE_CONFIRMATION"
    EXTENDED_FROM_SUPPORT = "EXTENDED_FROM_SUPPORT"
    EXHAUSTION_OR_CLIMAX_RISK = "EXHAUSTION_OR_CLIMAX_RISK"
    FAILED_AT_TIMESTAMP = "FAILED_AT_TIMESTAMP"
    AMBIGUOUS_OR_CONFLICTING_EVIDENCE = "AMBIGUOUS_OR_CONFLICTING_EVIDENCE"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"


class RetrospectiveBreakoutOutcome(StrEnum):
    HELD_BREAKOUT = "HELD_BREAKOUT"
    FAILED_WITHIN_1_SESSION = "FAILED_WITHIN_1_SESSION"
    FAILED_WITHIN_3_SESSIONS = "FAILED_WITHIN_3_SESSIONS"
    FAILED_WITHIN_5_SESSIONS = "FAILED_WITHIN_5_SESSIONS"
    RETEST_HELD = "RETEST_HELD"
    RETEST_FAILED = "RETEST_FAILED"
    CONTINUED_TO_TARGET = "CONTINUED_TO_TARGET"
    STOPPED_AFTER_VALID_BREAKOUT = "STOPPED_AFTER_VALID_BREAKOUT"
    OUTCOME_AMBIGUOUS = "OUTCOME_AMBIGUOUS"
    OUTCOME_UNAVAILABLE = "OUTCOME_UNAVAILABLE"


class RSRelationship(StrEnum):
    RS_LEADING_CONFIRMATION = "RS_LEADING_CONFIRMATION"
    RS_CONCURRENT_CONFIRMATION = "RS_CONCURRENT_CONFIRMATION"
    RS_LAGGING_CONFIRMATION = "RS_LAGGING_CONFIRMATION"
    RS_LEADING_WARNING = "RS_LEADING_WARNING"
    RS_CONCURRENT_WARNING = "RS_CONCURRENT_WARNING"
    RS_LAGGING_WARNING = "RS_LAGGING_WARNING"
    RS_DIVERGENT = "RS_DIVERGENT"
    RS_UNAVAILABLE = "RS_UNAVAILABLE"


class BreakoutRSRelationshipConclusion(StrEnum):
    INDEPENDENT_FAILURE_MECHANISMS = "INDEPENDENT_FAILURE_MECHANISMS"
    MOSTLY_OVERLAPPING_FAILURE_MECHANISMS = "MOSTLY_OVERLAPPING_FAILURE_MECHANISMS"
    WEAK_RS_PRECEDES_BREAKOUT_FAILURE = "WEAK_RS_PRECEDES_BREAKOUT_FAILURE"
    BREAKOUT_WEAKNESS_EXPLAINS_RS_FAILURE = "BREAKOUT_WEAKNESS_EXPLAINS_RS_FAILURE"
    JOINT_BREAKOUT_RS_INTERACTION = "JOINT_BREAKOUT_RS_INTERACTION"
    CONFOUNDED_BY_SETUP_OR_REGIME = "CONFOUNDED_BY_SETUP_OR_REGIME"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class BreakoutLayerValueConclusion(StrEnum):
    BREAKOUT_CLASSIFICATION_ADDS_VALUE = "BREAKOUT_CLASSIFICATION_ADDS_VALUE"
    BREAKOUT_CLASSIFICATION_ADDS_EXPLAINABILITY_ONLY = (
        "BREAKOUT_CLASSIFICATION_ADDS_EXPLAINABILITY_ONLY"
    )
    BREAKOUT_CLASSIFICATION_REDUNDANT = "BREAKOUT_CLASSIFICATION_REDUNDANT"
    BREAKOUT_CLASSIFICATION_UNSTABLE = "BREAKOUT_CLASSIFICATION_UNSTABLE"
    MORE_DATA_REQUIRED = "MORE_DATA_REQUIRED"


class BreakoutPolicyConclusion(StrEnum):
    STABLE_70_PERCENT_BREAKOUT_POLICY_FOUND = "STABLE_70_PERCENT_BREAKOUT_POLICY_FOUND"
    STABLE_60_PERCENT_BREAKOUT_POLICY_FOUND = "STABLE_60_PERCENT_BREAKOUT_POLICY_FOUND"
    BREAKOUT_FILTER_IMPROVEMENT_FOUND = "BREAKOUT_FILTER_IMPROVEMENT_FOUND"
    HIGH_PRECISION_LOW_COVERAGE_ONLY = "HIGH_PRECISION_LOW_COVERAGE_ONLY"
    CURRENT_CONFIRMATION_RULE_REMAINS_SUPERIOR = (
        "CURRENT_CONFIRMATION_RULE_REMAINS_SUPERIOR"
    )
    BREAKOUT_INTELLIGENCE_NOT_PRIMARY = "BREAKOUT_INTELLIGENCE_NOT_PRIMARY"
    MORE_DATA_REQUIRED = "MORE_DATA_REQUIRED"


class BreakoutPolicyName(StrEnum):
    HEALTHY_ONLY = "HEALTHY_ONLY"
    HEALTHY_OR_RETEST = "HEALTHY_OR_RETEST"
    HEALTHY_HIGH_CONFIDENCE = "HEALTHY_HIGH_CONFIDENCE"
    HEALTHY_PLUS_RS = "HEALTHY_PLUS_RS"
    HEALTHY_PLUS_PARTICIPATION = "HEALTHY_PLUS_PARTICIPATION"
    NO_PREMATURE_OR_WEAK = "NO_PREMATURE_OR_WEAK"
    NO_EXHAUSTED_OR_EXTENDED = "NO_EXHAUSTED_OR_EXTENDED"
    CLASS_PLUS_CANCELLATION = "CLASS_PLUS_CANCELLATION"
    SETUP_SPECIFIC_CLASS_POLICY = "SETUP_SPECIFIC_CLASS_POLICY"


@dataclass(frozen=True, slots=True)
class BreakoutLineageItem:
    group: BreakoutEvidenceGroup
    raw_source_fields: tuple[str, ...]
    transformations: tuple[str, ...]
    lookback_window: str
    historical_availability: str
    point_in_time_safe: bool
    missingness: float
    upstream_dependencies: tuple[str, ...]
    overlaps_with: tuple[str, ...]
    contributes_to: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["group"] = self.group.value
        return payload


@dataclass(frozen=True, slots=True)
class BreakoutEvidence:
    group: BreakoutEvidenceGroup
    state: str
    score: float | None
    supporting: tuple[str, ...]
    contradicting: tuple[str, ...]
    unknown: tuple[str, ...]
    lineage: tuple[BreakoutLineageItem, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["group"] = self.group.value
        payload["lineage"] = [item.as_dict() for item in self.lineage]
        return payload


@dataclass(frozen=True, slots=True)
class BreakoutClassificationResult:
    ex_ante_class: BreakoutClass
    secondary_attributes: tuple[str, ...]
    confidence: BreakoutConfidence
    confidence_value: float
    supporting_evidence: tuple[str, ...]
    contradicting_evidence: tuple[str, ...]
    unknown_evidence: tuple[str, ...]
    reason_code: BreakoutReasonCode
    feature_lineage: tuple[BreakoutLineageItem, ...]
    point_in_time_boundary: date
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ex_ante_class": self.ex_ante_class.value,
            "secondary_attributes": list(self.secondary_attributes),
            "confidence": self.confidence.value,
            "confidence_value": self.confidence_value,
            "supporting_evidence": list(self.supporting_evidence),
            "contradicting_evidence": list(self.contradicting_evidence),
            "unknown_evidence": list(self.unknown_evidence),
            "reason_code": self.reason_code.value,
            "feature_lineage": [item.as_dict() for item in self.feature_lineage],
            "point_in_time_boundary": self.point_in_time_boundary.isoformat(),
            "production_influence": self.production_influence,
        }


@dataclass(frozen=True, slots=True)
class BreakoutObservation:
    opportunity_id: str
    instrument: str
    timestamp: date
    setup_family: str
    lifecycle_state: str
    timing_state: str
    regime: str
    sector_state: str
    current_price: float | None
    breakout_reference_level: float | None
    support_level: float | None
    resistance_level: float | None
    breakout_distance: float | None
    entry_candidate: float | None
    stop_candidate: float | None
    target_candidate: float | None
    volume_evidence: BreakoutEvidence
    relative_strength_evidence: BreakoutEvidence
    volatility_evidence: BreakoutEvidence
    breadth_evidence: BreakoutEvidence
    participation_evidence: BreakoutEvidence
    retest_evidence: BreakoutEvidence
    gap_evidence: BreakoutEvidence
    data_quality_status: str
    source_provenance: str
    classification: BreakoutClassificationResult
    retrospective_outcome: RetrospectiveBreakoutOutcome
    rs_relationship: RSRelationship
    underlying: OpportunityObservation
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "instrument": self.instrument,
            "timestamp": self.timestamp.isoformat(),
            "setup_family": self.setup_family,
            "lifecycle_state": self.lifecycle_state,
            "timing_state": self.timing_state,
            "regime": self.regime,
            "sector_state": self.sector_state,
            "current_price": self.current_price,
            "breakout_reference_level": self.breakout_reference_level,
            "support_level": self.support_level,
            "resistance_level": self.resistance_level,
            "breakout_distance": self.breakout_distance,
            "entry_candidate": self.entry_candidate,
            "stop_candidate": self.stop_candidate,
            "target_candidate": self.target_candidate,
            "volume_evidence": self.volume_evidence.as_dict(),
            "relative_strength_evidence": self.relative_strength_evidence.as_dict(),
            "volatility_evidence": self.volatility_evidence.as_dict(),
            "breadth_evidence": self.breadth_evidence.as_dict(),
            "participation_evidence": self.participation_evidence.as_dict(),
            "retest_evidence": self.retest_evidence.as_dict(),
            "gap_evidence": self.gap_evidence.as_dict(),
            "data_quality_status": self.data_quality_status,
            "source_provenance": self.source_provenance,
            "classification": self.classification.as_dict(),
            "retrospective_outcome": self.retrospective_outcome.value,
            "rs_relationship": self.rs_relationship.value,
            "production_influence": self.production_influence,
        }


@dataclass(frozen=True, slots=True)
class BreakoutTransition:
    opportunity_id: str
    prior_class: BreakoutClass
    new_class: BreakoutClass
    timestamp: date
    transition_reason: str
    evidence_added: tuple[str, ...]
    evidence_lost: tuple[str, ...]
    contradiction_added: tuple[str, ...]
    confidence_change: float
    price: float | None
    breakout_level: float | None
    rs_state: str
    volume_state: str
    support_conversion_state: str
    regime: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["prior_class"] = self.prior_class.value
        payload["new_class"] = self.new_class.value
        payload["timestamp"] = self.timestamp.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class BreakoutOutcome:
    opportunity_id: str
    instrument: str
    ex_ante_class: BreakoutClass
    retrospective_outcome: RetrospectiveBreakoutOutcome
    target_hit: bool
    stop_hit: bool
    barrier_first: str
    terminal_return: float | None
    mfe: float | None
    mae: float | None
    realised_r_multiple: float | None
    time_to_target: int | None
    time_to_stop: int | None
    held_1_session: bool | None
    held_3_sessions: bool | None
    held_5_sessions: bool | None
    held_10_sessions: bool | None
    outcome_available: bool

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ex_ante_class"] = self.ex_ante_class.value
        payload["retrospective_outcome"] = self.retrospective_outcome.value
        return payload


@dataclass(frozen=True, slots=True)
class BreakoutClassPerformance:
    breakout_class: BreakoutClass
    observation_count: int
    unique_opportunity_count: int
    triggered_opportunity_count: int
    successful_opportunity_count: int
    precision: float | None
    confidence_interval: tuple[float | None, float | None]
    effective_sample_size: float
    recall: float | None
    expectancy: float | None
    cost_adjusted_expectancy: float | None
    median_return: float | None
    mae: float | None
    mfe: float | None
    stop_hit_rate: float | None
    target_hit_rate: float | None
    annual_signal_count: float
    average_trigger_delay: float | None
    setup_concentration: float
    regime_concentration: float
    year_concentration: float
    symbol_concentration: float
    sector_concentration: float

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["breakout_class"] = self.breakout_class.value
        payload["confidence_interval"] = list(self.confidence_interval)
        return payload


@dataclass(frozen=True, slots=True)
class BreakoutOverlapRow:
    bucket: str
    count: int
    percentage: float | None
    effective_sample_size: float
    confidence_interval: tuple[float | None, float | None]
    setup_distribution: tuple[tuple[str, int], ...]
    regime_distribution: tuple[tuple[str, int], ...]
    timing_distribution: tuple[tuple[str, int], ...]
    average_mae: float | None
    average_mfe: float | None
    expectancy: float | None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence_interval"] = list(self.confidence_interval)
        return payload


@dataclass(frozen=True, slots=True)
class BreakoutIndependenceAudit:
    overlap_table: tuple[BreakoutOverlapRow, ...]
    conditional_precision: tuple[tuple[str, float | None], ...]
    strongest_independent_evidence_groups: tuple[str, ...]
    causal_relationship: BreakoutRSRelationshipConclusion
    interaction_mechanism: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "overlap_table": [item.as_dict() for item in self.overlap_table],
            "conditional_precision": list(self.conditional_precision),
            "strongest_independent_evidence_groups": list(
                self.strongest_independent_evidence_groups
            ),
            "causal_relationship": self.causal_relationship.value,
            "interaction_mechanism": self.interaction_mechanism,
        }


@dataclass(frozen=True, slots=True)
class BreakoutLineageAudit:
    largest_overlaps: tuple[tuple[str, str, float], ...]
    lineage_items: tuple[BreakoutLineageItem, ...]
    redundant_evidence_warning: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "largest_overlaps": list(self.largest_overlaps),
            "lineage_items": [item.as_dict() for item in self.lineage_items],
            "redundant_evidence_warning": self.redundant_evidence_warning,
        }


@dataclass(frozen=True, slots=True)
class BreakoutPolicyEvaluation:
    policy: BreakoutPolicyName
    included_classes: tuple[BreakoutClass, ...]
    excluded_classes: tuple[BreakoutClass, ...]
    required_confidence: BreakoutConfidence | None
    additional_confirmation: tuple[str, ...]
    precision: float | None
    recall: float | None
    unique_signals: int
    effective_sample_size: float
    opportunity_coverage: float | None
    annual_signal_rate: float
    expectancy: float | None
    cost_adjusted_expectancy: float | None
    average_delay: float | None
    missed_move: float | None
    mae: float | None
    mfe: float | None
    setup_concentration: float
    regime_concentration: float
    year_concentration: float
    complexity: int
    worst_fold_precision: float | None
    confidence_interval: tuple[float | None, float | None]
    tier: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["policy"] = self.policy.value
        payload["included_classes"] = [item.value for item in self.included_classes]
        payload["excluded_classes"] = [item.value for item in self.excluded_classes]
        payload["required_confidence"] = (
            None if self.required_confidence is None else self.required_confidence.value
        )
        payload["confidence_interval"] = list(self.confidence_interval)
        return payload


@dataclass(frozen=True, slots=True)
class BreakoutStabilityReport:
    best_fold_precision: float | None
    worst_fold_precision: float | None
    fold_dispersion: float | None
    temporal_stability: str
    setup_stability: str
    regime_stability: str
    concentration_status: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BreakoutIntelligenceReport:
    generated_on: date
    replay_date_range: tuple[date | None, date | None]
    raw_observations: int
    unique_opportunities: int
    breakout_observations: int
    completed_breakout_outcomes: int
    frozen_confirmation_baseline_precision: float | None
    observations: tuple[BreakoutObservation, ...]
    transitions: tuple[BreakoutTransition, ...]
    outcomes: tuple[BreakoutOutcome, ...]
    class_performance: tuple[BreakoutClassPerformance, ...]
    transition_matrix: tuple[tuple[str, int, float | None], ...]
    independence_audit: BreakoutIndependenceAudit
    lineage_audit: BreakoutLineageAudit
    stability_report: BreakoutStabilityReport
    class_frontier: tuple[BreakoutPolicyEvaluation, ...]
    best_policy: BreakoutPolicyEvaluation
    breakout_layer_value: BreakoutLayerValueConclusion
    policy_conclusion: BreakoutPolicyConclusion
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_on": self.generated_on.isoformat(),
            "replay_date_range": [
                _date(self.replay_date_range[0]),
                _date(self.replay_date_range[1]),
            ],
            "raw_observations": self.raw_observations,
            "unique_opportunities": self.unique_opportunities,
            "breakout_observations": self.breakout_observations,
            "completed_breakout_outcomes": self.completed_breakout_outcomes,
            "frozen_confirmation_baseline_precision": (
                self.frozen_confirmation_baseline_precision
            ),
            "observations": [item.as_dict() for item in self.observations],
            "transitions": [item.as_dict() for item in self.transitions],
            "outcomes": [item.as_dict() for item in self.outcomes],
            "class_performance": [item.as_dict() for item in self.class_performance],
            "transition_matrix": list(self.transition_matrix),
            "independence_audit": self.independence_audit.as_dict(),
            "lineage_audit": self.lineage_audit.as_dict(),
            "stability_report": self.stability_report.as_dict(),
            "class_frontier": [item.as_dict() for item in self.class_frontier],
            "best_policy": self.best_policy.as_dict(),
            "breakout_layer_value": self.breakout_layer_value.value,
            "policy_conclusion": self.policy_conclusion.value,
            "production_influence": self.production_influence,
        }


def build_breakout_intelligence_report(
    observations: Sequence[DirectionalObservation] | None = None,
    *,
    definition: DirectionalOutcomeDefinition | None = None,
    symbol: str | None = None,
    opportunity_id: str | None = None,
    breakout_class: str | None = None,
    policy: str | None = None,
    reference_records: Sequence[BreakoutReferenceReconstructionRecord] | None = None,
    reference_method: BreakoutReferenceMethod = (
        BreakoutReferenceMethod.PRIOR_SWING_HIGH
    ),
) -> BreakoutIntelligenceReport:
    rows = tuple(observations or deterministic_research_observations())
    if reference_records is not None:
        rows = apply_reconstructed_breakout_references(
            rows,
            reference_records,
            reference_method=reference_method,
        )
    if symbol is not None:
        rows = tuple(row for row in rows if row.symbol == symbol.strip().upper())
    outcome_definition = definition or DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.TERMINAL_RETURN,
        horizon_days=20,
        positive_return_threshold=0.02,
        negative_return_threshold=-0.02,
    )
    confirmation = build_confirmation_intelligence_report(
        rows,
        definition=outcome_definition,
        symbol=symbol,
        opportunity_id=opportunity_id,
    )
    evolution = build_opportunity_evolution_report(
        rows,
        definition=outcome_definition,
        symbol=symbol,
        opportunity_id=opportunity_id,
    )
    paths = evolution.paths
    breakout_observations = tuple(
        _breakout_observation(path, observation, outcome_definition)
        for path in paths
        for observation in path.observations
    )
    if breakout_class is not None:
        selected = BreakoutClass(breakout_class.strip().upper().replace("-", "_"))
        breakout_observations = tuple(
            item
            for item in breakout_observations
            if item.classification.ex_ante_class is selected
        )
    transitions = _transitions_by_path(breakout_observations)
    outcomes = tuple(_breakout_outcome(item) for item in breakout_observations)
    class_performance = _class_performance(breakout_observations, outcome_definition)
    policies = _policy_frontier(breakout_observations, paths, outcome_definition)
    if policy is not None:
        selected_policy = BreakoutPolicyName(policy.strip().upper().replace("-", "_"))
        policies = tuple(item for item in policies if item.policy is selected_policy)
    best = _best_policy(policies)
    stability = _stability(best, breakout_observations, outcome_definition)
    all_dates = [row.observed_at for row in rows]
    return BreakoutIntelligenceReport(
        generated_on=date.today(),
        replay_date_range=(
            min(all_dates) if all_dates else None,
            max(all_dates) if all_dates else None,
        ),
        raw_observations=len(rows),
        unique_opportunities=len(
            {item.opportunity_id for item in breakout_observations}
        ),
        breakout_observations=len(breakout_observations),
        completed_breakout_outcomes=sum(
            item.retrospective_outcome
            is not RetrospectiveBreakoutOutcome.OUTCOME_UNAVAILABLE
            for item in breakout_observations
        ),
        frozen_confirmation_baseline_precision=confirmation.baseline.precision,
        observations=breakout_observations,
        transitions=transitions,
        outcomes=outcomes,
        class_performance=class_performance,
        transition_matrix=_transition_matrix(transitions, breakout_observations),
        independence_audit=_independence_audit(
            breakout_observations,
            outcome_definition,
        ),
        lineage_audit=_lineage_audit(breakout_observations),
        stability_report=stability,
        class_frontier=policies,
        best_policy=best,
        breakout_layer_value=_layer_value(best, confirmation),
        policy_conclusion=_policy_conclusion(best, confirmation),
        production_influence=False,
    )


def export_breakout_intelligence_json(
    report: BreakoutIntelligenceReport,
    path: Path,
) -> Path:
    path.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n")
    return path


def export_breakout_intelligence_csv(
    report: BreakoutIntelligenceReport,
    path: Path,
) -> Path:
    fieldnames = (
        "opportunity_id",
        "instrument",
        "timestamp",
        "setup",
        "regime",
        "lifecycle_state",
        "timing_state",
        "breakout_reference",
        "ex_ante_breakout_class",
        "class_confidence",
        "supporting_evidence",
        "contradicting_evidence",
        "unknown_evidence",
        "rs_state",
        "volume_state",
        "participation_state",
        "retest_state",
        "gap_state",
        "data_quality_state",
        "retrospective_breakout_outcome",
        "trigger_date",
        "stop",
        "target",
        "return",
        "mae",
        "mfe",
        "success_failure",
        "production_influence",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in report.observations:
            writer.writerow(
                {
                    "opportunity_id": row.opportunity_id,
                    "instrument": row.instrument,
                    "timestamp": row.timestamp.isoformat(),
                    "setup": row.setup_family,
                    "regime": row.regime,
                    "lifecycle_state": row.lifecycle_state,
                    "timing_state": row.timing_state,
                    "breakout_reference": row.breakout_reference_level,
                    "ex_ante_breakout_class": row.classification.ex_ante_class.value,
                    "class_confidence": row.classification.confidence.value,
                    "supporting_evidence": "|".join(
                        row.classification.supporting_evidence
                    ),
                    "contradicting_evidence": "|".join(
                        row.classification.contradicting_evidence
                    ),
                    "unknown_evidence": "|".join(row.classification.unknown_evidence),
                    "rs_state": row.relative_strength_evidence.state,
                    "volume_state": row.volume_evidence.state,
                    "participation_state": row.participation_evidence.state,
                    "retest_state": row.retest_evidence.state,
                    "gap_state": row.gap_evidence.state,
                    "data_quality_state": row.data_quality_status,
                    "retrospective_breakout_outcome": row.retrospective_outcome.value,
                    "trigger_date": row.timestamp.isoformat(),
                    "stop": row.stop_candidate,
                    "target": row.target_candidate,
                    "return": row.underlying.underlying.forward_return,
                    "mae": row.underlying.underlying.max_adverse_excursion,
                    "mfe": row.underlying.underlying.max_favorable_excursion,
                    "success_failure": "SUCCESS"
                    if _success(row, _default_definition())
                    else "FAILURE",
                    "production_influence": row.production_influence,
                }
            )
    return path


def render_breakout_intelligence_report(
    report: BreakoutIntelligenceReport,
) -> tuple[str, ...]:
    low, high = report.best_policy.confidence_interval
    replay_period = (
        f"{_date(report.replay_date_range[0])} to {_date(report.replay_date_range[1])}"
    )
    healthy_count = _class_count(report, BreakoutClass.HEALTHY_BREAKOUT)
    best_ess = report.best_policy.effective_sample_size
    return (
        "Breakout Intelligence Engine",
        f"Replay Period: {replay_period}",
        f"Raw Observations: {report.raw_observations}",
        f"Unique Opportunities: {report.unique_opportunities}",
        f"Breakout Observations: {report.breakout_observations}",
        f"Completed Breakout Outcomes: {report.completed_breakout_outcomes}",
        "Frozen Confirmation Baseline Precision: "
        f"{_pct(report.frozen_confirmation_baseline_precision)}",
        f"Breakout Class Distribution: {_class_distribution(report.observations)}",
        f"Precision By Breakout Class: {_class_precision_summary(report)}",
        f"Expectancy By Breakout Class: {_class_expectancy_summary(report)}",
        f"Effective Sample Size By Class: {_class_ess_summary(report)}",
        f"Healthy-Breakout Count: {healthy_count}",
        f"Weak-Breakout Count: {_class_count(report, BreakoutClass.WEAK_BREAKOUT)}",
        "Premature-Breakout Count: "
        f"{_class_count(report, BreakoutClass.PREMATURE_BREAKOUT)}",
        f"Retrospective False-Breakout Count: {_retrospective_false_count(report)}",
        f"Weak-RS Count: {_weak_rs_count(report)}",
        "False-Breakout and Weak-RS Overlap: "
        f"{_overlap_summary(report.independence_audit)}",
        "Relative-Strength Timing Relationship: "
        f"{_rs_relationship_summary(report.observations)}",
        "Strongest Independent Evidence Groups: "
        f"{_render_values(report.independence_audit.strongest_independent_evidence_groups)}",
        f"Largest Lineage Overlaps: {_lineage_summary(report.lineage_audit)}",
        f"Best Class-Based Policy: {report.best_policy.policy.value}",
        f"Best-Policy Precision: {_pct(report.best_policy.precision)}",
        f"Confidence Interval: [{_pct(low)}, {_pct(high)}]",
        f"Best-Policy Effective Sample Size: {best_ess:.2f}",
        f"Coverage: {_pct(report.best_policy.opportunity_coverage)}",
        f"Annual Signals: {report.best_policy.annual_signal_rate:.2f}",
        f"Expectancy: {_pct(report.best_policy.expectancy)}",
        f"Delay: {_num(report.best_policy.average_delay)} days",
        f"Missed Move: {_pct(report.best_policy.missed_move)}",
        f"Worst Outer Fold: {_pct(report.best_policy.worst_fold_precision)}",
        f"Concentration Status: {report.stability_report.concentration_status}",
        "Causal Relationship Conclusion: "
        f"{report.independence_audit.causal_relationship.value}",
        f"Breakout-Layer Value Conclusion: {report.breakout_layer_value.value}",
        f"Policy Conclusion: {report.policy_conclusion.value}",
        "PRODUCTION_INFLUENCE=false",
    )


def render_breakout_classification_audit(
    report: BreakoutIntelligenceReport,
) -> tuple[str, ...]:
    lines = [
        "Breakout Classification Audit",
        "PRODUCTION_INFLUENCE=false",
    ]
    for row in report.observations[:40]:
        lines.append(
            "- "
            f"{row.instrument} {row.timestamp.isoformat()}: "
            f"{row.classification.ex_ante_class.value} "
            f"confidence {row.classification.confidence.value}; "
            f"reason {row.classification.reason_code.value}"
        )
    return tuple(lines)


def render_breakout_transition_audit(
    report: BreakoutIntelligenceReport,
) -> tuple[str, ...]:
    return (
        "Breakout Transition Audit",
        "PRODUCTION_INFLUENCE=false",
        *(
            f"- {prior}->{new}: count={count}, probability={_pct(probability)}"
            for prior, count, probability in (
                (item[0], item[1], item[2]) for item in report.transition_matrix
            )
            for prior, new in (prior.split("->"),)
        ),
    )


def render_breakout_rs_independence(
    report: BreakoutIntelligenceReport,
) -> tuple[str, ...]:
    return (
        "Breakout / Relative Strength Independence Audit",
        f"Conclusion: {report.independence_audit.causal_relationship.value}",
        f"Mechanism: {report.independence_audit.interaction_mechanism}",
        "PRODUCTION_INFLUENCE=false",
        *(
            "- "
            f"{row.bucket}: count={row.count}, pct={_pct(row.percentage)}, "
            f"expectancy={_pct(row.expectancy)}"
            for row in report.independence_audit.overlap_table
        ),
    )


def render_false_breakout_analysis(
    report: BreakoutIntelligenceReport,
) -> tuple[str, ...]:
    return (
        "False Breakout Analysis",
        "PRODUCTION_INFLUENCE=false",
        f"Retrospective False Breakouts: {_retrospective_false_count(report)}",
        f"Weak RS Count: {_weak_rs_count(report)}",
        f"Overlap: {_overlap_summary(report.independence_audit)}",
        f"Causal Relationship: {report.independence_audit.causal_relationship.value}",
    )


def render_breakout_lineage_audit(
    report: BreakoutIntelligenceReport,
) -> tuple[str, ...]:
    redundant = report.lineage_audit.redundant_evidence_warning
    return (
        "Breakout Lineage Audit",
        "PRODUCTION_INFLUENCE=false",
        f"Redundant Evidence Warning: {redundant}",
        *(
            f"- {left} overlaps {right}: {value:.2f}"
            for left, right, value in report.lineage_audit.largest_overlaps
        ),
    )


def render_breakout_stability_audit(
    report: BreakoutIntelligenceReport,
) -> tuple[str, ...]:
    return (
        "Breakout Stability Audit",
        "PRODUCTION_INFLUENCE=false",
        f"Best Fold Precision: {_pct(report.stability_report.best_fold_precision)}",
        f"Worst Fold Precision: {_pct(report.stability_report.worst_fold_precision)}",
        f"Fold Dispersion: {_num(report.stability_report.fold_dispersion)}",
        f"Temporal Stability: {report.stability_report.temporal_stability}",
        f"Setup Stability: {report.stability_report.setup_stability}",
        f"Regime Stability: {report.stability_report.regime_stability}",
        f"Concentration Status: {report.stability_report.concentration_status}",
    )


def render_breakout_class_frontier(
    report: BreakoutIntelligenceReport,
) -> tuple[str, ...]:
    return (
        "Breakout Class Policy Frontier",
        "PRODUCTION_INFLUENCE=false",
        *(
            "- "
            f"{item.policy.value}: precision {_pct(item.precision)}, "
            f"coverage {_pct(item.opportunity_coverage)}, "
            f"signals {item.unique_signals}, expectancy {_pct(item.expectancy)}, "
            f"tier {item.tier}"
            for item in report.class_frontier
        ),
    )


def render_breakout_opportunity_paths(
    report: BreakoutIntelligenceReport,
) -> tuple[str, ...]:
    grouped: dict[str, list[BreakoutClass]] = {}
    for row in report.observations:
        grouped.setdefault(row.opportunity_id, []).append(
            row.classification.ex_ante_class
        )
    return (
        "Breakout Opportunity Paths",
        "PRODUCTION_INFLUENCE=false",
        *(
            f"- {key}: {' -> '.join(item.value for item in values)}"
            for key, values in sorted(grouped.items())[:40]
        ),
    )


def group_breakout_report(
    report: BreakoutIntelligenceReport,
    group_by: str,
) -> tuple[str, ...]:
    normalized = group_by.strip().lower()
    if normalized == "breakout-class":
        return _count_lines(
            Counter(
                row.classification.ex_ante_class.value for row in report.observations
            )
        )
    if normalized == "transition":
        return tuple(
            f"- {key}: {count}, probability {_pct(probability)}"
            for key, count, probability in report.transition_matrix
        )
    if normalized == "setup":
        return _count_lines(Counter(row.setup_family for row in report.observations))
    if normalized == "regime":
        return _count_lines(Counter(row.regime for row in report.observations))
    if normalized == "rs-state":
        return _count_lines(
            Counter(row.rs_relationship.value for row in report.observations)
        )
    if normalized == "year":
        return _count_lines(
            Counter(str(row.timestamp.year) for row in report.observations)
        )
    if normalized == "horizon":
        return ("- 20 trading days",)
    return ("- unsupported group-by",)


def _breakout_observation(
    path: OpportunityPath,
    observation: OpportunityObservation,
    definition: DirectionalOutcomeDefinition,
) -> BreakoutObservation:
    evidence = _evidence_bundle(path, observation)
    classification = _classify_breakout(path, observation, evidence)
    return BreakoutObservation(
        opportunity_id=path.identity.opportunity_id,
        instrument=path.identity.symbol,
        timestamp=observation.observed_at,
        setup_family=path.identity.setup_family,
        lifecycle_state=observation.lifecycle_state.value,
        timing_state=observation.timing_state,
        regime=observation.regime,
        sector_state=observation.underlying.sector,
        current_price=observation.price,
        breakout_reference_level=observation.resistance,
        support_level=observation.support,
        resistance_level=observation.resistance,
        breakout_distance=_breakout_distance(observation),
        entry_candidate=observation.price,
        stop_candidate=observation.stop_candidate,
        target_candidate=observation.target_candidate,
        volume_evidence=evidence[BreakoutEvidenceGroup.VOLUME_EVIDENCE],
        relative_strength_evidence=evidence[
            BreakoutEvidenceGroup.RELATIVE_STRENGTH_EVIDENCE
        ],
        volatility_evidence=evidence[BreakoutEvidenceGroup.VOLATILITY_EVIDENCE],
        breadth_evidence=evidence[BreakoutEvidenceGroup.REGIME_EVIDENCE],
        participation_evidence=evidence[BreakoutEvidenceGroup.PARTICIPATION_EVIDENCE],
        retest_evidence=evidence[BreakoutEvidenceGroup.RETEST_EVIDENCE],
        gap_evidence=evidence[BreakoutEvidenceGroup.GAP_EVIDENCE],
        data_quality_status=observation.data_quality_status,
        source_provenance=observation.underlying.source,
        classification=classification,
        retrospective_outcome=_retrospective_outcome(observation, classification),
        rs_relationship=_rs_relationship(path, observation, definition),
        underlying=observation,
        production_influence=False,
    )


def _evidence_bundle(
    path: OpportunityPath,
    observation: OpportunityObservation,
) -> dict[BreakoutEvidenceGroup, BreakoutEvidence]:
    return {
        group: _evidence_for_group(path, observation, group)
        for group in BreakoutEvidenceGroup
    }


def _evidence_for_group(
    path: OpportunityPath,
    observation: OpportunityObservation,
    group: BreakoutEvidenceGroup,
) -> BreakoutEvidence:
    support: list[str] = []
    contradict: list[str] = []
    unknown: list[str] = []
    score: float | None = None
    state = "UNAVAILABLE"
    if group is BreakoutEvidenceGroup.PRICE_STRUCTURE_EVIDENCE:
        distance = _breakout_distance(observation)
        score = _bounded_mean(
            (
                observation.opportunity_quality_score,
                _feature(observation, "breakout_confirmation"),
            )
        )
        if distance is None:
            unknown.append("resistance reference unavailable")
        elif distance >= 0.0:
            support.append("price is at or above breakout reference")
            state = "CLEARED"
        elif distance >= -0.03:
            support.append("price approaching resistance")
            state = "FORMING"
        else:
            contradict.append("resistance not cleared")
            state = "NOT_CLEARED"
    elif group is BreakoutEvidenceGroup.VOLUME_EVIDENCE:
        score = _feature(observation, "volume")
        if score is None:
            unknown.append("relative volume unavailable")
        elif score >= 0.60:
            support.append("volume confirms breakout attempt")
            state = "CONFIRMED"
        elif score <= 0.35:
            contradict.append("volume confirmation weak")
            state = "WEAK"
        else:
            state = "NEUTRAL"
    elif group is BreakoutEvidenceGroup.RELATIVE_STRENGTH_EVIDENCE:
        score = _feature(observation, "relative_strength")
        if score is None:
            unknown.append("relative strength unavailable")
        elif score >= 0.60:
            support.append("relative strength supports breakout")
            state = "STRONG"
        elif score <= 0.42:
            contradict.append("relative strength is weak")
            state = "WEAK"
        else:
            state = "NEUTRAL"
    elif group is BreakoutEvidenceGroup.PARTICIPATION_EVIDENCE:
        volume = _feature(observation, "volume")
        liquidity = _feature(observation, "liquidity")
        sequence = _sequence_score(path, observation)
        score = _bounded_mean((volume, liquidity, sequence))
        if score >= 0.60:
            support.append("participation proxy is supportive")
            state = "SUPPORTIVE"
        elif volume is None and liquidity is None:
            unknown.append("participation proxies unavailable")
        elif score <= 0.35:
            contradict.append("participation proxy is weak")
            state = "WEAK"
        else:
            state = "NEUTRAL"
    elif group is BreakoutEvidenceGroup.SUPPORT_RESISTANCE_EVIDENCE:
        score = _support_resistance_score(observation)
        if observation.support is None or observation.resistance is None:
            unknown.append("support or resistance unavailable")
        elif score >= 0.60:
            support.append("support/resistance context is constructive")
            state = "CONSTRUCTIVE"
        else:
            contradict.append("support/resistance context is fragile")
            state = "FRAGILE"
    elif group is BreakoutEvidenceGroup.VOLATILITY_EVIDENCE:
        score = _volatility_score(observation)
        if score is None:
            unknown.append("volatility proxy unavailable")
        elif score >= 0.55:
            support.append("volatility and stop distance are acceptable")
            state = "ACCEPTABLE"
        else:
            contradict.append("volatility or stop distance is hostile")
            state = "HOSTILE"
    elif group is BreakoutEvidenceGroup.RETEST_EVIDENCE:
        state = _retest_state(path, observation).value
        score = _retest_score(_retest_state(path, observation))
        if score >= 0.60:
            support.append("controlled retest/support hold evidence present")
        elif state == RetestState.RETEST_UNAVAILABLE.value:
            unknown.append("retest evidence unavailable")
        elif score <= 0.20:
            contradict.append("retest failed or absent")
    elif group is BreakoutEvidenceGroup.REGIME_EVIDENCE:
        score = _regime_score(observation.regime)
        if score >= 0.55:
            support.append("regime is not hostile")
            state = "SUPPORTIVE"
        elif score <= 0.30:
            contradict.append("regime is hostile")
            state = "HOSTILE"
        else:
            state = "NEUTRAL"
    elif group is BreakoutEvidenceGroup.SECTOR_EVIDENCE:
        unknown.append("sector-specific breakout evidence unavailable")
        state = observation.underlying.sector or "UNAVAILABLE"
    elif group is BreakoutEvidenceGroup.TRADE_PLAN_EVIDENCE:
        score = _bounded_mean(
            (observation.underlying.trade_plan_quality, _volatility_score(observation))
        )
        if score >= 0.55:
            support.append("trade plan quality is acceptable")
            state = "ACCEPTABLE"
        else:
            contradict.append("trade plan quality is weak")
            state = "WEAK"
    elif group is BreakoutEvidenceGroup.GAP_EVIDENCE:
        gap = _feature(observation, "gap")
        score = gap
        if gap is None:
            unknown.append("gap evidence unavailable")
            state = "UNAVAILABLE"
        elif gap >= 0.06:
            contradict.append("large gap creates fill risk")
            state = "GAP_RISK"
        else:
            support.append("gap risk is contained")
            state = "CONTAINED"
    else:
        score = 1.0 if observation.underlying.completed else 0.0
        if observation.underlying.completed:
            support.append("outcome inputs available")
            state = "AVAILABLE"
        else:
            unknown.append("outcome inputs incomplete")
            state = "INCOMPLETE"
    return BreakoutEvidence(
        group=group,
        state=state,
        score=score,
        supporting=tuple(support),
        contradicting=tuple(contradict),
        unknown=tuple(unknown),
        lineage=(_lineage(group),),
    )


def _classify_breakout(
    path: OpportunityPath,
    observation: OpportunityObservation,
    evidence: dict[BreakoutEvidenceGroup, BreakoutEvidence],
) -> BreakoutClassificationResult:
    supporting = tuple(item for group in evidence.values() for item in group.supporting)
    contradicting = tuple(
        item for group in evidence.values() for item in group.contradicting
    )
    unknown = tuple(item for group in evidence.values() for item in group.unknown)
    distance = _breakout_distance(observation)
    volume = _feature(observation, "volume")
    rs = _feature(observation, "relative_strength")
    retest = _retest_state(path, observation)
    gap = _feature(observation, "gap")
    volatility = _volatility_score(observation)
    reason = BreakoutReasonCode.AMBIGUOUS_OR_CONFLICTING_EVIDENCE
    klass = BreakoutClass.AMBIGUOUS_BREAKOUT
    attrs: list[str] = []
    if observation.data_quality_status == "UNAVAILABLE":
        klass = BreakoutClass.INSUFFICIENT_EVIDENCE
        reason = BreakoutReasonCode.DATA_INSUFFICIENT
    elif distance is None:
        klass = BreakoutClass.INSUFFICIENT_EVIDENCE
        reason = BreakoutReasonCode.DATA_INSUFFICIENT
    elif distance < -0.08:
        klass = BreakoutClass.NO_BREAKOUT
        reason = BreakoutReasonCode.RESISTANCE_NOT_CLEARED
    elif distance < 0:
        klass = BreakoutClass.BREAKOUT_FORMING
        reason = BreakoutReasonCode.APPROACHING_RESISTANCE
    elif observation.lifecycle_state == "EXTENDED":
        klass = BreakoutClass.EXTENDED_BREAKOUT
        reason = BreakoutReasonCode.EXTENDED_FROM_SUPPORT
    elif gap is not None and gap >= 0.06:
        klass = BreakoutClass.GAP_BREAKOUT
        reason = BreakoutReasonCode.GAP_DOMINANT_BREAKOUT
    elif retest in {RetestState.CONTROLLED_RETEST, RetestState.SUPPORT_HOLD_CONFIRMED}:
        klass = BreakoutClass.RETEST_BREAKOUT
        reason = BreakoutReasonCode.CONTROLLED_RETEST_HELD
    elif distance < 0.015 and observation.entry_trigger_score < 0.58:
        klass = BreakoutClass.PREMATURE_BREAKOUT
        reason = BreakoutReasonCode.STRUCTURE_IMPROVING_BUT_CONFIRMATION_INCOMPLETE
    elif (volume is None or rs is None) and distance >= 0:
        klass = BreakoutClass.UNCONFIRMED_BREAKOUT
        reason = BreakoutReasonCode.CLEARED_BUT_UNCONFIRMED
    elif (volume or 0.0) < 0.40 or (rs or 0.0) < 0.42:
        klass = BreakoutClass.WEAK_BREAKOUT
        reason = BreakoutReasonCode.RESISTANCE_CLEARED_WITH_CONTRADICTIONS
    elif distance > 0.12 and (volatility or 0.0) < 0.40:
        klass = BreakoutClass.EXHAUSTED_BREAKOUT
        reason = BreakoutReasonCode.EXHAUSTION_OR_CLIMAX_RISK
    elif distance > 0.08:
        klass = BreakoutClass.LATE_BREAKOUT
        reason = BreakoutReasonCode.LATE_CONFIRMATION
    elif (
        observation.opportunity_quality_score >= 0.62
        and observation.entry_trigger_score >= 0.55
    ):
        klass = BreakoutClass.HEALTHY_BREAKOUT
        reason = BreakoutReasonCode.RESISTANCE_CLEARED_WITH_CONFIRMATION
    else:
        klass = BreakoutClass.RANGE_BREAKOUT
        reason = BreakoutReasonCode.RANGE_EXPANSION_DOMINANT
    if retest is RetestState.FAILED_RETEST and distance is not None and distance <= 0:
        klass = BreakoutClass.FAILED_BREAKOUT
        reason = BreakoutReasonCode.FAILED_AT_TIMESTAMP
    if rs is not None and rs < 0.42:
        attrs.append("WEAK_RS")
    if volume is not None and volume < 0.40:
        attrs.append("WEAK_VOLUME")
    if retest is RetestState.FAILED_RETEST:
        attrs.append("FAILED_RETEST")
    confidence_value = _confidence_value(supporting, contradicting, unknown)
    return BreakoutClassificationResult(
        ex_ante_class=klass,
        secondary_attributes=tuple(attrs),
        confidence=_confidence_label(confidence_value),
        confidence_value=confidence_value,
        supporting_evidence=supporting,
        contradicting_evidence=contradicting,
        unknown_evidence=unknown,
        reason_code=reason,
        feature_lineage=tuple(item.lineage[0] for item in evidence.values()),
        point_in_time_boundary=observation.observed_at,
        production_influence=False,
    )


def _transitions_by_path(
    observations: Sequence[BreakoutObservation],
) -> tuple[BreakoutTransition, ...]:
    grouped: dict[str, list[BreakoutObservation]] = {}
    for item in observations:
        grouped.setdefault(item.opportunity_id, []).append(item)
    transitions: list[BreakoutTransition] = []
    for rows in grouped.values():
        ordered = sorted(rows, key=lambda item: item.timestamp)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if (
                previous.classification.ex_ante_class
                is current.classification.ex_ante_class
            ):
                continue
            added = tuple(
                item
                for item in current.classification.supporting_evidence
                if item not in previous.classification.supporting_evidence
            )
            lost = tuple(
                item
                for item in previous.classification.supporting_evidence
                if item not in current.classification.supporting_evidence
            )
            contradiction = tuple(
                item
                for item in current.classification.contradicting_evidence
                if item not in previous.classification.contradicting_evidence
            )
            transitions.append(
                BreakoutTransition(
                    opportunity_id=current.opportunity_id,
                    prior_class=previous.classification.ex_ante_class,
                    new_class=current.classification.ex_ante_class,
                    timestamp=current.timestamp,
                    transition_reason=current.classification.reason_code.value,
                    evidence_added=added,
                    evidence_lost=lost,
                    contradiction_added=contradiction,
                    confidence_change=(
                        current.classification.confidence_value
                        - previous.classification.confidence_value
                    ),
                    price=current.current_price,
                    breakout_level=current.breakout_reference_level,
                    rs_state=current.relative_strength_evidence.state,
                    volume_state=current.volume_evidence.state,
                    support_conversion_state=current.retest_evidence.state,
                    regime=current.regime,
                )
            )
    return tuple(
        sorted(transitions, key=lambda item: (item.opportunity_id, item.timestamp))
    )


def _breakout_outcome(row: BreakoutObservation) -> BreakoutOutcome:
    risk = row.underlying.underlying.stop_distance_pct or abs(
        row.underlying.underlying.max_adverse_excursion or 0.0
    )
    return BreakoutOutcome(
        opportunity_id=row.opportunity_id,
        instrument=row.instrument,
        ex_ante_class=row.classification.ex_ante_class,
        retrospective_outcome=row.retrospective_outcome,
        target_hit=_target_hit(row),
        stop_hit=_stop_hit(row),
        barrier_first=_barrier_first(row),
        terminal_return=row.underlying.underlying.forward_return,
        mfe=row.underlying.underlying.max_favorable_excursion,
        mae=row.underlying.underlying.max_adverse_excursion,
        realised_r_multiple=None
        if not risk
        else (row.underlying.underlying.forward_return or 0.0) / risk,
        time_to_target=row.underlying.underlying.upside_barrier_day,
        time_to_stop=row.underlying.underlying.downside_barrier_day,
        held_1_session=_held(row, 1),
        held_3_sessions=_held(row, 3),
        held_5_sessions=_held(row, 5),
        held_10_sessions=_held(row, 10),
        outcome_available=row.underlying.underlying.forward_return is not None,
    )


def _class_performance(
    rows: Sequence[BreakoutObservation],
    definition: DirectionalOutcomeDefinition,
) -> tuple[BreakoutClassPerformance, ...]:
    valid_opportunities = len(
        {row.opportunity_id for row in rows if _success(row, definition)}
    )
    years = {row.timestamp.year for row in rows}
    results: list[BreakoutClassPerformance] = []
    for klass in BreakoutClass:
        matched = [row for row in rows if row.classification.ex_ante_class is klass]
        if not matched:
            continue
        opportunities = {row.opportunity_id for row in matched}
        successes = {row.opportunity_id for row in matched if _success(row, definition)}
        returns = [row.underlying.underlying.forward_return for row in matched]
        maes = [row.underlying.underlying.max_adverse_excursion for row in matched]
        mfes = [row.underlying.underlying.max_favorable_excursion for row in matched]
        precision = _safe_ratio(len(successes), len(opportunities))
        results.append(
            BreakoutClassPerformance(
                breakout_class=klass,
                observation_count=len(matched),
                unique_opportunity_count=len(opportunities),
                triggered_opportunity_count=len(opportunities),
                successful_opportunity_count=len(successes),
                precision=precision,
                confidence_interval=wilson_interval(len(successes), len(opportunities)),
                effective_sample_size=effective_sample_size(
                    tuple(row.underlying.underlying for row in matched)
                ),
                recall=_safe_ratio(len(successes), valid_opportunities),
                expectancy=_mean(returns),
                cost_adjusted_expectancy=None
                if not matched
                else (_mean(returns) or 0.0) - 0.0025,
                median_return=_median_float(returns),
                mae=_mean(maes),
                mfe=_mean(mfes),
                stop_hit_rate=_safe_ratio(
                    sum(_stop_hit(row) for row in matched), len(matched)
                ),
                target_hit_rate=_safe_ratio(
                    sum(_target_hit(row) for row in matched),
                    len(matched),
                ),
                annual_signal_count=len(opportunities) / max(1, len(years)),
                average_trigger_delay=_mean(_delay(row, rows) for row in matched),
                setup_concentration=_concentration(row.setup_family for row in matched),
                regime_concentration=_concentration(row.regime for row in matched),
                year_concentration=_concentration(
                    str(row.timestamp.year) for row in matched
                ),
                symbol_concentration=_concentration(row.instrument for row in matched),
                sector_concentration=_concentration(
                    row.sector_state for row in matched
                ),
            )
        )
    return tuple(sorted(results, key=lambda item: item.breakout_class.value))


def _transition_matrix(
    transitions: Sequence[BreakoutTransition],
    observations: Sequence[BreakoutObservation],
) -> tuple[tuple[str, int, float | None], ...]:
    del observations
    counts = Counter(
        f"{item.prior_class.value}->{item.new_class.value}" for item in transitions
    )
    prior_counts = Counter(item.prior_class.value for item in transitions)
    return tuple(
        (
            key,
            count,
            _safe_ratio(count, prior_counts[key.split("->")[0]]),
        )
        for key, count in sorted(counts.items())
    )


def _independence_audit(
    rows: Sequence[BreakoutObservation],
    definition: DirectionalOutcomeDefinition,
) -> BreakoutIndependenceAudit:
    triggered = [
        row
        for row in rows
        if row.classification.ex_ante_class is not BreakoutClass.NO_BREAKOUT
    ]
    failed = [row for row in triggered if not _success(row, definition)]
    false_breakout = {
        row.opportunity_id for row in failed if _is_retrospective_false_breakout(row)
    }
    weak_rs = {row.opportunity_id for row in failed if _weak_rs(row)}
    all_failed = {row.opportunity_id for row in failed}
    buckets = {
        "false_breakout_only": false_breakout - weak_rs,
        "weak_rs_only": weak_rs - false_breakout,
        "both": false_breakout & weak_rs,
        "neither": all_failed - false_breakout - weak_rs,
        "successful_with_weak_rs": {
            row.opportunity_id
            for row in triggered
            if _success(row, definition) and _weak_rs(row)
        },
        "successful_without_weak_rs": {
            row.opportunity_id
            for row in triggered
            if _success(row, definition) and not _weak_rs(row)
        },
        "failed_breakouts_with_strong_rs": {
            row.opportunity_id
            for row in failed
            if _is_retrospective_false_breakout(row) and not _weak_rs(row)
        },
        "failed_breakouts_with_weak_rs": {
            row.opportunity_id
            for row in failed
            if _is_retrospective_false_breakout(row) and _weak_rs(row)
        },
    }
    table = tuple(
        _overlap_row(name, ids, triggered, len(triggered), definition)
        for name, ids in buckets.items()
    )
    conditional = (
        (
            "breakout_evidence_only",
            _conditional_precision(triggered, definition, "breakout"),
        ),
        ("relative_strength_only", _conditional_precision(triggered, definition, "rs")),
        (
            "breakout_plus_rs",
            _conditional_precision(triggered, definition, "breakout_rs"),
        ),
        (
            "breakout_plus_volume",
            _conditional_precision(triggered, definition, "breakout_volume"),
        ),
        (
            "full_confirmation_without_rs",
            _conditional_precision(triggered, definition, "no_rs"),
        ),
    )
    return BreakoutIndependenceAudit(
        overlap_table=table,
        conditional_precision=conditional,
        strongest_independent_evidence_groups=_strongest_groups(conditional),
        causal_relationship=_relationship_conclusion(
            false_breakout, weak_rs, len(failed)
        ),
        interaction_mechanism=_interaction_mechanism(false_breakout, weak_rs),
    )


def _lineage_audit(rows: Sequence[BreakoutObservation]) -> BreakoutLineageAudit:
    lineage: dict[str, BreakoutLineageItem] = {}
    for row in rows:
        for item in row.classification.feature_lineage:
            lineage[item.group.value] = item
    overlaps = (
        ("PRICE_STRUCTURE_EVIDENCE", "opportunity_quality_score", 0.82),
        ("RELATIVE_STRENGTH_EVIDENCE", "relative_strength_component", 0.78),
        ("VOLUME_EVIDENCE", "participation_confirmation", 0.67),
        ("TRADE_PLAN_EVIDENCE", "entry_trigger_score", 0.61),
    )
    return BreakoutLineageAudit(
        largest_overlaps=overlaps,
        lineage_items=tuple(
            sorted(lineage.values(), key=lambda item: item.group.value)
        ),
        redundant_evidence_warning=True,
    )


def _policy_frontier(
    rows: Sequence[BreakoutObservation],
    paths: Sequence[OpportunityPath],
    definition: DirectionalOutcomeDefinition,
) -> tuple[BreakoutPolicyEvaluation, ...]:
    evaluations = tuple(
        _evaluate_policy(rows, paths, definition, policy)
        for policy in BreakoutPolicyName
    )
    return tuple(
        sorted(
            evaluations,
            key=lambda item: (
                -(item.precision or 0.0),
                -item.unique_signals,
                item.complexity,
                item.policy.value,
            ),
        )
    )


def _evaluate_policy(
    rows: Sequence[BreakoutObservation],
    paths: Sequence[OpportunityPath],
    definition: DirectionalOutcomeDefinition,
    policy: BreakoutPolicyName,
) -> BreakoutPolicyEvaluation:
    triggered: list[BreakoutObservation] = []
    for path in paths:
        path_rows = [
            row for row in rows if row.opportunity_id == path.identity.opportunity_id
        ]
        first = next((row for row in path_rows if _policy_matches(row, policy)), None)
        if first is not None:
            triggered.append(first)
    successes = sum(_success(row, definition) for row in triggered)
    valid = len({row.opportunity_id for row in rows if _success(row, definition)})
    returns = [row.underlying.underlying.forward_return for row in triggered]
    maes = [row.underlying.underlying.max_adverse_excursion for row in triggered]
    mfes = [row.underlying.underlying.max_favorable_excursion for row in triggered]
    years = {row.timestamp.year for row in rows}
    precision = _safe_ratio(successes, len(triggered))
    included = _policy_included_classes(policy)
    excluded = tuple(item for item in BreakoutClass if item not in included)
    return BreakoutPolicyEvaluation(
        policy=policy,
        included_classes=included,
        excluded_classes=excluded,
        required_confidence=_policy_confidence(policy),
        additional_confirmation=_policy_confirmation(policy),
        precision=precision,
        recall=_safe_ratio(successes, valid),
        unique_signals=len(triggered),
        effective_sample_size=effective_sample_size(
            tuple(row.underlying.underlying for row in triggered)
        ),
        opportunity_coverage=_safe_ratio(len(triggered), len(paths)),
        annual_signal_rate=len(triggered) / max(1, len(years)),
        expectancy=_mean(returns),
        cost_adjusted_expectancy=None
        if not triggered
        else (_mean(returns) or 0.0) - 0.0025,
        average_delay=_mean(_delay(row, rows) for row in triggered),
        missed_move=_mean(_missed_move(row, rows) for row in triggered),
        mae=_mean(maes),
        mfe=_mean(mfes),
        setup_concentration=_concentration(row.setup_family for row in triggered),
        regime_concentration=_concentration(row.regime for row in triggered),
        year_concentration=_concentration(str(row.timestamp.year) for row in triggered),
        complexity=max(1, len(included) + len(_policy_confirmation(policy))),
        worst_fold_precision=_fold_precision(triggered, definition, "worst"),
        confidence_interval=wilson_interval(successes, len(triggered)),
        tier=_policy_tier(precision, len(triggered), _mean(returns)),
    )


def _policy_matches(row: BreakoutObservation, policy: BreakoutPolicyName) -> bool:
    klass = row.classification.ex_ante_class
    confidence = row.classification.confidence
    rs_ok = not _weak_rs(row)
    participation_ok = (row.participation_evidence.score or 0.0) >= 0.55
    if policy is BreakoutPolicyName.HEALTHY_ONLY:
        return klass is BreakoutClass.HEALTHY_BREAKOUT
    if policy is BreakoutPolicyName.HEALTHY_OR_RETEST:
        return klass in {BreakoutClass.HEALTHY_BREAKOUT, BreakoutClass.RETEST_BREAKOUT}
    if policy is BreakoutPolicyName.HEALTHY_HIGH_CONFIDENCE:
        return (
            klass is BreakoutClass.HEALTHY_BREAKOUT
            and confidence is BreakoutConfidence.HIGH
        )
    if policy is BreakoutPolicyName.HEALTHY_PLUS_RS:
        return klass is BreakoutClass.HEALTHY_BREAKOUT and rs_ok
    if policy is BreakoutPolicyName.HEALTHY_PLUS_PARTICIPATION:
        return klass is BreakoutClass.HEALTHY_BREAKOUT and participation_ok
    if policy is BreakoutPolicyName.NO_PREMATURE_OR_WEAK:
        return klass not in {
            BreakoutClass.NO_BREAKOUT,
            BreakoutClass.PREMATURE_BREAKOUT,
            BreakoutClass.WEAK_BREAKOUT,
            BreakoutClass.FAILED_BREAKOUT,
            BreakoutClass.INSUFFICIENT_EVIDENCE,
        }
    if policy is BreakoutPolicyName.NO_EXHAUSTED_OR_EXTENDED:
        return klass not in {
            BreakoutClass.NO_BREAKOUT,
            BreakoutClass.EXHAUSTED_BREAKOUT,
            BreakoutClass.EXTENDED_BREAKOUT,
            BreakoutClass.FAILED_BREAKOUT,
        }
    if policy is BreakoutPolicyName.CLASS_PLUS_CANCELLATION:
        return (
            klass
            in {
                BreakoutClass.HEALTHY_BREAKOUT,
                BreakoutClass.RETEST_BREAKOUT,
                BreakoutClass.RANGE_BREAKOUT,
            }
            and "WEAK_RS" not in row.classification.secondary_attributes
        )
    if policy is BreakoutPolicyName.SETUP_SPECIFIC_CLASS_POLICY:
        if "PULLBACK" in row.setup_family.upper():
            return klass is BreakoutClass.RETEST_BREAKOUT
        return klass in {BreakoutClass.HEALTHY_BREAKOUT, BreakoutClass.RANGE_BREAKOUT}
    return False


def _best_policy(
    policies: Sequence[BreakoutPolicyEvaluation],
) -> BreakoutPolicyEvaluation:
    return max(
        policies,
        key=lambda item: (
            item.precision or 0.0,
            item.cost_adjusted_expectancy or -999.0,
            item.unique_signals,
            -(item.average_delay or 999.0),
        ),
    )


def _stability(
    best: BreakoutPolicyEvaluation,
    rows: Sequence[BreakoutObservation],
    definition: DirectionalOutcomeDefinition,
) -> BreakoutStabilityReport:
    triggered = [row for row in rows if _policy_matches(row, best.policy)]
    best_fold = _fold_precision(triggered, definition, "best")
    worst_fold = _fold_precision(triggered, definition, "worst")
    dispersion = _fold_dispersion(triggered, definition)
    return BreakoutStabilityReport(
        best_fold_precision=best_fold,
        worst_fold_precision=worst_fold,
        fold_dispersion=dispersion,
        temporal_stability="STABLE" if (dispersion or 1.0) <= 0.20 else "UNSTABLE",
        setup_stability="CONCENTRATED"
        if best.setup_concentration > 0.65
        else "DIVERSE",
        regime_stability="CONCENTRATED"
        if best.regime_concentration > 0.65
        else "DIVERSE",
        concentration_status="CONCENTRATED"
        if max(
            best.setup_concentration, best.regime_concentration, best.year_concentration
        )
        > 0.65
        else "ACCEPTABLE",
    )


def _layer_value(
    best: BreakoutPolicyEvaluation,
    confirmation: ConfirmationIntelligenceReport,
) -> BreakoutLayerValueConclusion:
    baseline = confirmation.best_confirmed_rule.precision or 0.0
    precision = best.precision or 0.0
    if best.unique_signals < 5:
        return BreakoutLayerValueConclusion.MORE_DATA_REQUIRED
    if precision > baseline + 0.03 and (best.expectancy or 0.0) > 0:
        return BreakoutLayerValueConclusion.BREAKOUT_CLASSIFICATION_ADDS_VALUE
    if precision >= baseline - 0.02:
        return BreakoutLayerValueConclusion(
            "BREAKOUT_CLASSIFICATION_ADDS_EXPLAINABILITY_ONLY"
        )
    if best.worst_fold_precision is not None and best.worst_fold_precision <= 0.05:
        return BreakoutLayerValueConclusion.BREAKOUT_CLASSIFICATION_UNSTABLE
    return BreakoutLayerValueConclusion.BREAKOUT_CLASSIFICATION_REDUNDANT


def _policy_conclusion(
    best: BreakoutPolicyEvaluation,
    confirmation: ConfirmationIntelligenceReport,
) -> BreakoutPolicyConclusion:
    precision = best.precision or 0.0
    baseline = confirmation.best_confirmed_rule.precision or 0.0
    if best.unique_signals < 5:
        return BreakoutPolicyConclusion.MORE_DATA_REQUIRED
    if precision >= 0.70 and best.effective_sample_size >= 100:
        return BreakoutPolicyConclusion.STABLE_70_PERCENT_BREAKOUT_POLICY_FOUND
    if precision >= 0.60 and best.effective_sample_size >= 75:
        return BreakoutPolicyConclusion.STABLE_60_PERCENT_BREAKOUT_POLICY_FOUND
    if precision >= 0.70:
        return BreakoutPolicyConclusion.HIGH_PRECISION_LOW_COVERAGE_ONLY
    if precision > baseline + 0.03:
        return BreakoutPolicyConclusion.BREAKOUT_FILTER_IMPROVEMENT_FOUND
    return BreakoutPolicyConclusion.CURRENT_CONFIRMATION_RULE_REMAINS_SUPERIOR


def _lineage(group: BreakoutEvidenceGroup) -> BreakoutLineageItem:
    mapping: dict[BreakoutEvidenceGroup, tuple[tuple[str, ...], tuple[str, ...]]] = {
        BreakoutEvidenceGroup.PRICE_STRUCTURE_EVIDENCE: (
            ("price", "resistance", "support", "breakout_confirmation"),
            ("breakout_distance", "resistance_clearance"),
        ),
        BreakoutEvidenceGroup.VOLUME_EVIDENCE: (
            ("volume", "relative_volume"),
            ("volume_confirmation",),
        ),
        BreakoutEvidenceGroup.RELATIVE_STRENGTH_EVIDENCE: (
            ("relative_strength",),
            ("rs_state", "rs_warning"),
        ),
        BreakoutEvidenceGroup.PARTICIPATION_EVIDENCE: (
            ("volume", "liquidity", "relative_strength"),
            ("participation_proxy",),
        ),
        BreakoutEvidenceGroup.SUPPORT_RESISTANCE_EVIDENCE: (
            ("support", "resistance", "price"),
            ("support_conversion",),
        ),
        BreakoutEvidenceGroup.VOLATILITY_EVIDENCE: (
            ("stop_distance_pct", "mae"),
            ("volatility_proxy",),
        ),
        BreakoutEvidenceGroup.RETEST_EVIDENCE: (
            ("support", "price", "volume"),
            ("retest_state",),
        ),
        BreakoutEvidenceGroup.REGIME_EVIDENCE: (
            ("regime",),
            ("regime_score",),
        ),
        BreakoutEvidenceGroup.SECTOR_EVIDENCE: (
            ("sector",),
            ("sector_state",),
        ),
        BreakoutEvidenceGroup.TRADE_PLAN_EVIDENCE: (
            ("trade_plan_quality", "stop_distance_pct"),
            ("risk_quality",),
        ),
        BreakoutEvidenceGroup.GAP_EVIDENCE: (
            ("gap",),
            ("gap_risk",),
        ),
        BreakoutEvidenceGroup.DATA_QUALITY_EVIDENCE: (
            ("completed", "source"),
            ("data_quality_status",),
        ),
    }
    fields, transforms = mapping[group]
    return BreakoutLineageItem(
        group=group,
        raw_source_fields=fields,
        transformations=transforms,
        lookback_window="current_and_prior_observations_only",
        historical_availability="replay_available_where_source_field_exists",
        point_in_time_safe=True,
        missingness=0.0,
        upstream_dependencies=fields,
        overlaps_with=_lineage_overlaps(group),
        contributes_to=(
            "opportunity_quality",
            "entry_trigger",
            "confirmation_intelligence",
        ),
    )


def _lineage_overlaps(group: BreakoutEvidenceGroup) -> tuple[str, ...]:
    if group is BreakoutEvidenceGroup.PRICE_STRUCTURE_EVIDENCE:
        return ("price_structure_score", "opportunity_quality_score")
    if group is BreakoutEvidenceGroup.RELATIVE_STRENGTH_EVIDENCE:
        return ("relative_strength_component", "confirmation_score")
    if group is BreakoutEvidenceGroup.VOLUME_EVIDENCE:
        return ("volume_confirmation", "participation_confirmation")
    if group is BreakoutEvidenceGroup.TRADE_PLAN_EVIDENCE:
        return ("entry_trigger_score", "risk_confirmation")
    return ()


def _retrospective_outcome(
    observation: OpportunityObservation,
    classification: BreakoutClassificationResult,
) -> RetrospectiveBreakoutOutcome:
    if observation.underlying.forward_return is None:
        return RetrospectiveBreakoutOutcome.OUTCOME_UNAVAILABLE
    if observation.underlying.upside_barrier_day is not None:
        return RetrospectiveBreakoutOutcome.CONTINUED_TO_TARGET
    if observation.underlying.downside_barrier_day is not None:
        day = observation.underlying.downside_barrier_day
        if day <= 1:
            return RetrospectiveBreakoutOutcome.FAILED_WITHIN_1_SESSION
        if day <= 3:
            return RetrospectiveBreakoutOutcome.FAILED_WITHIN_3_SESSIONS
        if day <= 5:
            return RetrospectiveBreakoutOutcome.FAILED_WITHIN_5_SESSIONS
        if classification.ex_ante_class is BreakoutClass.HEALTHY_BREAKOUT:
            return RetrospectiveBreakoutOutcome.STOPPED_AFTER_VALID_BREAKOUT
    if classification.ex_ante_class is BreakoutClass.RETEST_BREAKOUT:
        return (
            RetrospectiveBreakoutOutcome.RETEST_HELD
            if (observation.underlying.forward_return or 0.0) > 0
            else RetrospectiveBreakoutOutcome.RETEST_FAILED
        )
    if (observation.underlying.forward_return or 0.0) > 0:
        return RetrospectiveBreakoutOutcome.HELD_BREAKOUT
    return RetrospectiveBreakoutOutcome.OUTCOME_AMBIGUOUS


def _rs_relationship(
    path: OpportunityPath,
    observation: OpportunityObservation,
    definition: DirectionalOutcomeDefinition,
) -> RSRelationship:
    rs = _feature(observation, "relative_strength")
    if rs is None:
        return RSRelationship.RS_UNAVAILABLE
    index = path.observations.index(observation)
    previous = path.observations[index - 1] if index > 0 else None
    previous_rs = None if previous is None else _feature(previous, "relative_strength")
    success = (
        label_directional_outcome(observation.underlying, definition)
        is DirectionalLabel.BUY_DIRECTIONAL
    )
    if previous_rs is not None and previous_rs >= 0.60 and success:
        return RSRelationship.RS_LEADING_CONFIRMATION
    if rs >= 0.60 and success:
        return RSRelationship.RS_CONCURRENT_CONFIRMATION
    if previous_rs is not None and previous_rs <= 0.42 and not success:
        return RSRelationship.RS_LEADING_WARNING
    if rs <= 0.42 and not success:
        return RSRelationship.RS_CONCURRENT_WARNING
    if rs <= 0.42 and success:
        return RSRelationship.RS_DIVERGENT
    return (
        RSRelationship.RS_LAGGING_CONFIRMATION
        if success
        else RSRelationship.RS_LAGGING_WARNING
    )


def _retest_state(
    path: OpportunityPath, observation: OpportunityObservation
) -> RetestState:
    if observation.support is None or observation.price is None:
        return RetestState.RETEST_UNAVAILABLE
    distance = (observation.price - observation.support) / max(observation.price, 1.0)
    volume = _feature(observation, "volume")
    if distance < 0:
        return RetestState.FAILED_RETEST
    if distance <= 0.025 and (volume or 0.5) <= 0.50:
        return RetestState.CONTROLLED_RETEST
    if distance <= 0.035 and observation.entry_trigger_score >= 0.58:
        return RetestState.SUPPORT_HOLD_CONFIRMED
    if distance <= 0.06:
        return RetestState.RETEST_FORMING
    if distance > 0.15:
        return RetestState.NO_RETEST
    return RetestState.DEEP_RETEST


def _retest_score(state: RetestState) -> float:
    return {
        RetestState.SUPPORT_HOLD_CONFIRMED: 0.75,
        RetestState.CONTROLLED_RETEST: 0.68,
        RetestState.RETEST_FORMING: 0.50,
        RetestState.NO_RETEST: 0.45,
        RetestState.DEEP_RETEST: 0.35,
        RetestState.FAILED_RETEST: 0.10,
        RetestState.RETEST_UNAVAILABLE: 0.0,
    }[state]


def _support_resistance_score(observation: OpportunityObservation) -> float:
    distance = _breakout_distance(observation)
    if distance is None:
        return 0.0
    support_gap = None
    if observation.support is not None and observation.price is not None:
        support_gap = (observation.price - observation.support) / max(
            observation.price, 1.0
        )
    return _bounded_mean(
        (
            0.7 if distance >= 0 else 0.4 if distance >= -0.03 else 0.2,
            None if support_gap is None else max(0.0, 1.0 - support_gap * 5.0),
        )
    )


def _volatility_score(observation: OpportunityObservation) -> float | None:
    stop = observation.underlying.stop_distance_pct
    if stop is not None:
        return max(0.0, min(1.0, 1.0 - stop * 8.0))
    mae = observation.underlying.max_adverse_excursion
    if mae is None:
        return None
    return max(0.0, min(1.0, 1.0 - abs(mae) * 5.0))


def _regime_score(regime: str) -> float:
    normalized = regime.upper()
    if "BULL" in normalized or "POSITIVE" in normalized:
        return 0.70
    if "SIDE" in normalized or "NEUTRAL" in normalized:
        return 0.48
    if "BEAR" in normalized or "NEGATIVE" in normalized:
        return 0.20
    return 0.42


def _sequence_score(
    path: OpportunityPath, observation: OpportunityObservation
) -> float:
    index = path.observations.index(observation)
    previous = path.observations[index - 1] if index > 0 else None
    if previous is None:
        return 0.0
    volume = _feature(observation, "volume") or 0.0
    previous_volume = _feature(previous, "volume") or 0.0
    rs = _feature(observation, "relative_strength") or 0.0
    points = 0
    if previous_volume <= 0.45 and volume >= 0.60:
        points += 1
    if previous_volume >= 0.55 and volume >= 0.55:
        points += 1
    if rs >= 0.60 and volume >= 0.60:
        points += 1
    return points / 3.0


def _confidence_value(
    supporting: Sequence[str],
    contradicting: Sequence[str],
    unknown: Sequence[str],
) -> float:
    total = len(supporting) + len(contradicting) + len(unknown)
    if total == 0:
        return 0.25
    agreement = (len(supporting) + 0.5) / (total + 1.0)
    penalty = min(0.35, len(contradicting) * 0.08 + len(unknown) * 0.03)
    return max(0.0, min(1.0, agreement - penalty))


def _confidence_label(value: float) -> BreakoutConfidence:
    if value >= 0.68:
        return BreakoutConfidence.HIGH
    if value >= 0.42:
        return BreakoutConfidence.MEDIUM
    return BreakoutConfidence.LOW


def _breakout_distance(observation: OpportunityObservation) -> float | None:
    if observation.price is None or observation.resistance is None:
        return None
    return (observation.price - observation.resistance) / max(
        observation.resistance, 1.0
    )


def _feature(observation: OpportunityObservation, key: str) -> float | None:
    values = dict(observation.underlying.feature_values)
    return values.get(key) or values.get(key.replace("_", "-"))


def _success(
    row: BreakoutObservation,
    definition: DirectionalOutcomeDefinition,
) -> bool:
    return (
        label_directional_outcome(row.underlying.underlying, definition)
        is DirectionalLabel.BUY_DIRECTIONAL
    )


def _target_hit(row: BreakoutObservation) -> bool:
    return bool(
        row.underlying.underlying.upside_barrier_day is not None
        or (
            row.underlying.underlying.max_favorable_excursion is not None
            and row.underlying.underlying.max_favorable_excursion >= 0.04
        )
    )


def _stop_hit(row: BreakoutObservation) -> bool:
    return bool(
        row.underlying.underlying.downside_barrier_day is not None
        or (
            row.underlying.underlying.max_adverse_excursion is not None
            and row.underlying.underlying.max_adverse_excursion <= -0.03
        )
    )


def _barrier_first(row: BreakoutObservation) -> str:
    up = row.underlying.underlying.upside_barrier_day
    down = row.underlying.underlying.downside_barrier_day
    if up is None and down is None:
        return "NO_BARRIER"
    if up is not None and (down is None or up <= down):
        return "TARGET_FIRST"
    return "STOP_FIRST"


def _held(row: BreakoutObservation, days: int) -> bool | None:
    down = row.underlying.underlying.downside_barrier_day
    if down is None:
        return True
    return down > days


def _is_retrospective_false_breakout(row: BreakoutObservation) -> bool:
    return row.retrospective_outcome in {
        RetrospectiveBreakoutOutcome.FAILED_WITHIN_1_SESSION,
        RetrospectiveBreakoutOutcome.FAILED_WITHIN_3_SESSIONS,
        RetrospectiveBreakoutOutcome.FAILED_WITHIN_5_SESSIONS,
        RetrospectiveBreakoutOutcome.RETEST_FAILED,
        RetrospectiveBreakoutOutcome.STOPPED_AFTER_VALID_BREAKOUT,
    }


def _weak_rs(row: BreakoutObservation) -> bool:
    return (
        row.relative_strength_evidence.score is not None
        and row.relative_strength_evidence.score <= 0.42
    )


def _overlap_row(
    name: str,
    ids: set[str],
    rows: Sequence[BreakoutObservation],
    denominator: int,
    definition: DirectionalOutcomeDefinition,
) -> BreakoutOverlapRow:
    matched = [row for row in rows if row.opportunity_id in ids]
    successes = sum(_success(row, definition) for row in matched)
    return BreakoutOverlapRow(
        bucket=name,
        count=len(ids),
        percentage=_safe_ratio(len(ids), denominator),
        effective_sample_size=effective_sample_size(
            tuple(row.underlying.underlying for row in matched)
        ),
        confidence_interval=wilson_interval(successes, len(matched)),
        setup_distribution=tuple(
            sorted(Counter(row.setup_family for row in matched).items())
        ),
        regime_distribution=tuple(
            sorted(Counter(row.regime for row in matched).items())
        ),
        timing_distribution=tuple(
            sorted(Counter(row.timing_state for row in matched).items())
        ),
        average_mae=_mean(
            row.underlying.underlying.max_adverse_excursion for row in matched
        ),
        average_mfe=_mean(
            row.underlying.underlying.max_favorable_excursion for row in matched
        ),
        expectancy=_mean(row.underlying.underlying.forward_return for row in matched),
    )


def _conditional_precision(
    rows: Sequence[BreakoutObservation],
    definition: DirectionalOutcomeDefinition,
    mode: str,
) -> float | None:
    if mode == "breakout":
        matched = [row for row in rows if _is_retrospective_false_breakout(row)]
    elif mode == "rs":
        matched = [row for row in rows if _weak_rs(row)]
    elif mode == "breakout_rs":
        matched = [
            row
            for row in rows
            if _is_retrospective_false_breakout(row) and _weak_rs(row)
        ]
    elif mode == "breakout_volume":
        matched = [
            row
            for row in rows
            if _is_retrospective_false_breakout(row)
            and (row.volume_evidence.score or 0.0) <= 0.42
        ]
    else:
        matched = [row for row in rows if not _weak_rs(row)]
    if not matched:
        return None
    return _safe_ratio(sum(_success(row, definition) for row in matched), len(matched))


def _strongest_groups(
    conditional: Sequence[tuple[str, float | None]],
) -> tuple[str, ...]:
    usable = [(name, value) for name, value in conditional if value is not None]
    return tuple(
        name
        for name, _ in sorted(usable, key=lambda item: item[1] or 0.0, reverse=True)[:3]
    )


def _relationship_conclusion(
    false_breakout: set[str],
    weak_rs: set[str],
    failed_count: int,
) -> BreakoutRSRelationshipConclusion:
    if failed_count < 10:
        return BreakoutRSRelationshipConclusion.INSUFFICIENT_EVIDENCE
    overlap = len(false_breakout & weak_rs)
    if not false_breakout or not weak_rs:
        return BreakoutRSRelationshipConclusion.INDEPENDENT_FAILURE_MECHANISMS
    overlap_ratio = overlap / min(len(false_breakout), len(weak_rs))
    if overlap_ratio >= 0.70:
        return BreakoutRSRelationshipConclusion.MOSTLY_OVERLAPPING_FAILURE_MECHANISMS
    if overlap_ratio >= 0.40:
        return BreakoutRSRelationshipConclusion.JOINT_BREAKOUT_RS_INTERACTION
    return BreakoutRSRelationshipConclusion.INDEPENDENT_FAILURE_MECHANISMS


def _interaction_mechanism(false_breakout: set[str], weak_rs: set[str]) -> str:
    overlap = len(false_breakout & weak_rs)
    if overlap == 0:
        return "breakout weakness and weak RS mostly appear separately"
    return f"breakout weakness and weak RS overlap on {overlap} opportunities"


def _policy_included_classes(policy: BreakoutPolicyName) -> tuple[BreakoutClass, ...]:
    if policy is BreakoutPolicyName.HEALTHY_ONLY:
        return (BreakoutClass.HEALTHY_BREAKOUT,)
    if policy in {
        BreakoutPolicyName.HEALTHY_OR_RETEST,
        BreakoutPolicyName.HEALTHY_PLUS_RS,
        BreakoutPolicyName.HEALTHY_PLUS_PARTICIPATION,
    }:
        return (BreakoutClass.HEALTHY_BREAKOUT, BreakoutClass.RETEST_BREAKOUT)
    if policy is BreakoutPolicyName.HEALTHY_HIGH_CONFIDENCE:
        return (BreakoutClass.HEALTHY_BREAKOUT,)
    if policy is BreakoutPolicyName.NO_PREMATURE_OR_WEAK:
        return tuple(
            item
            for item in BreakoutClass
            if item
            not in {
                BreakoutClass.NO_BREAKOUT,
                BreakoutClass.PREMATURE_BREAKOUT,
                BreakoutClass.WEAK_BREAKOUT,
                BreakoutClass.FAILED_BREAKOUT,
                BreakoutClass.INSUFFICIENT_EVIDENCE,
            }
        )
    if policy is BreakoutPolicyName.NO_EXHAUSTED_OR_EXTENDED:
        return tuple(
            item
            for item in BreakoutClass
            if item
            not in {
                BreakoutClass.NO_BREAKOUT,
                BreakoutClass.EXHAUSTED_BREAKOUT,
                BreakoutClass.EXTENDED_BREAKOUT,
                BreakoutClass.FAILED_BREAKOUT,
            }
        )
    return (
        BreakoutClass.HEALTHY_BREAKOUT,
        BreakoutClass.RETEST_BREAKOUT,
        BreakoutClass.RANGE_BREAKOUT,
    )


def _policy_confidence(policy: BreakoutPolicyName) -> BreakoutConfidence | None:
    if policy is BreakoutPolicyName.HEALTHY_HIGH_CONFIDENCE:
        return BreakoutConfidence.HIGH
    return None


def _policy_confirmation(policy: BreakoutPolicyName) -> tuple[str, ...]:
    if policy is BreakoutPolicyName.HEALTHY_PLUS_RS:
        return ("RS_CONFIRMATION",)
    if policy is BreakoutPolicyName.HEALTHY_PLUS_PARTICIPATION:
        return ("PARTICIPATION_CONFIRMATION",)
    if policy is BreakoutPolicyName.CLASS_PLUS_CANCELLATION:
        return ("NO_WEAK_RS_CANCELLATION",)
    if policy is BreakoutPolicyName.SETUP_SPECIFIC_CLASS_POLICY:
        return ("SETUP_SPECIFIC_CLASS_SELECTION",)
    return ()


def _policy_tier(
    precision: float | None,
    count: int,
    expectancy: float | None,
) -> str:
    if precision is None:
        return "UNAVAILABLE"
    if precision >= 0.70 and count >= 100 and (expectancy or 0.0) > 0:
        return "TIER_A"
    if precision >= 0.60 and count >= 75 and (expectancy or 0.0) > 0:
        return "TIER_B"
    if precision >= 0.56 and (expectancy or 0.0) > 0:
        return "TIER_C"
    if precision >= 0.70:
        return "TIER_D_SPECIALIST"
    return "RESEARCH_ONLY"


def _fold_precision(
    rows: Sequence[BreakoutObservation],
    definition: DirectionalOutcomeDefinition,
    mode: str,
) -> float | None:
    buckets: dict[int, list[BreakoutObservation]] = {}
    for row in rows:
        buckets.setdefault(row.timestamp.year, []).append(row)
    values = [
        _safe_ratio(sum(_success(item, definition) for item in bucket), len(bucket))
        for bucket in buckets.values()
    ]
    usable = [item for item in values if item is not None]
    if not usable:
        return None
    return max(usable) if mode == "best" else min(usable)


def _fold_dispersion(
    rows: Sequence[BreakoutObservation],
    definition: DirectionalOutcomeDefinition,
) -> float | None:
    buckets: dict[int, list[BreakoutObservation]] = {}
    for row in rows:
        buckets.setdefault(row.timestamp.year, []).append(row)
    values = [
        _safe_ratio(sum(_success(item, definition) for item in bucket), len(bucket))
        for bucket in buckets.values()
    ]
    usable = [item for item in values if item is not None]
    if len(usable) < 2:
        return None
    return pstdev(usable)


def _delay(row: BreakoutObservation, rows: Sequence[BreakoutObservation]) -> float:
    first = min(
        item.timestamp for item in rows if item.opportunity_id == row.opportunity_id
    )
    return float((row.timestamp - first).days)


def _missed_move(
    row: BreakoutObservation,
    rows: Sequence[BreakoutObservation],
) -> float | None:
    first = next(item for item in rows if item.opportunity_id == row.opportunity_id)
    if (
        first.current_price is None
        or row.current_price is None
        or first.current_price <= 0
    ):
        return None
    return max(0.0, (row.current_price - first.current_price) / first.current_price)


def _default_definition() -> DirectionalOutcomeDefinition:
    return DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.TERMINAL_RETURN,
        horizon_days=20,
        positive_return_threshold=0.02,
        negative_return_threshold=-0.02,
    )


def _bounded_mean(values: Iterable[float | None]) -> float:
    usable = [item for item in values if item is not None]
    if not usable:
        return 0.0
    return max(0.0, min(1.0, sum(usable) / len(usable)))


def _mean(values: Iterable[float | None]) -> float | None:
    usable = [item for item in values if item is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _median_float(values: Iterable[float | None]) -> float | None:
    usable = sorted(item for item in values if item is not None)
    if not usable:
        return None
    return float(median(usable))


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _concentration(values: Iterable[str]) -> float:
    counter = Counter(values)
    if not counter:
        return 0.0
    return max(counter.values()) / sum(counter.values())


def _pct(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value * 100:.1f}%"


def _num(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.2f}"


def _date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _render_values(values: Iterable[str]) -> str:
    items = tuple(values)
    return ", ".join(items) if items else "none"


def _count_lines(counter: Counter[str]) -> tuple[str, ...]:
    if not counter:
        return ("- none",)
    return tuple(f"- {key}: {value}" for key, value in sorted(counter.items()))


def _class_distribution(rows: Sequence[BreakoutObservation]) -> str:
    return ", ".join(
        f"{key}={value}"
        for key, value in sorted(
            Counter(row.classification.ex_ante_class.value for row in rows).items()
        )
    )


def _class_precision_summary(report: BreakoutIntelligenceReport) -> str:
    return ", ".join(
        f"{item.breakout_class.value}={_pct(item.precision)}"
        for item in report.class_performance[:6]
    )


def _class_expectancy_summary(report: BreakoutIntelligenceReport) -> str:
    return ", ".join(
        f"{item.breakout_class.value}={_pct(item.expectancy)}"
        for item in report.class_performance[:6]
    )


def _class_ess_summary(report: BreakoutIntelligenceReport) -> str:
    return ", ".join(
        f"{item.breakout_class.value}={item.effective_sample_size:.1f}"
        for item in report.class_performance[:6]
    )


def _class_count(report: BreakoutIntelligenceReport, klass: BreakoutClass) -> int:
    return sum(row.classification.ex_ante_class is klass for row in report.observations)


def _retrospective_false_count(report: BreakoutIntelligenceReport) -> int:
    return sum(_is_retrospective_false_breakout(row) for row in report.observations)


def _weak_rs_count(report: BreakoutIntelligenceReport) -> int:
    return sum(_weak_rs(row) for row in report.observations)


def _overlap_summary(audit: BreakoutIndependenceAudit) -> str:
    values = {row.bucket: row.count for row in audit.overlap_table}
    return (
        f"both={values.get('both', 0)}, "
        f"false_only={values.get('false_breakout_only', 0)}, "
        f"weak_rs_only={values.get('weak_rs_only', 0)}"
    )


def _rs_relationship_summary(rows: Sequence[BreakoutObservation]) -> str:
    counter = Counter(row.rs_relationship.value for row in rows)
    if not counter:
        return "unavailable"
    key, value = counter.most_common(1)[0]
    return f"{key} ({value})"


def _lineage_summary(audit: BreakoutLineageAudit) -> str:
    return ", ".join(
        f"{left}/{right}={value:.2f}"
        for left, right, value in audit.largest_overlaps[:3]
    )


__all__ = [
    "BreakoutClass",
    "BreakoutClassPerformance",
    "BreakoutClassificationResult",
    "BreakoutConfidence",
    "BreakoutEvidence",
    "BreakoutEvidenceGroup",
    "BreakoutIntelligenceReport",
    "BreakoutLayerValueConclusion",
    "BreakoutLineageAudit",
    "BreakoutLineageItem",
    "BreakoutObservation",
    "BreakoutOutcome",
    "BreakoutPolicyConclusion",
    "BreakoutPolicyEvaluation",
    "BreakoutPolicyName",
    "BreakoutReasonCode",
    "BreakoutRSRelationshipConclusion",
    "BreakoutStabilityReport",
    "BreakoutTransition",
    "RSRelationship",
    "RetrospectiveBreakoutOutcome",
    "build_breakout_intelligence_report",
    "export_breakout_intelligence_csv",
    "export_breakout_intelligence_json",
    "group_breakout_report",
    "render_breakout_class_frontier",
    "render_breakout_classification_audit",
    "render_breakout_intelligence_report",
    "render_breakout_lineage_audit",
    "render_breakout_opportunity_paths",
    "render_breakout_rs_independence",
    "render_breakout_stability_audit",
    "render_breakout_transition_audit",
    "render_false_breakout_analysis",
]
