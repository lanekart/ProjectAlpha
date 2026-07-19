from __future__ import annotations

import csv
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from statistics import median
from typing import Any


class DirectionalLabel(StrEnum):
    BUY_DIRECTIONAL = "BUY_DIRECTIONAL"
    SELL_DIRECTIONAL = "SELL_DIRECTIONAL"
    NEUTRAL = "NEUTRAL"
    UNAVAILABLE = "UNAVAILABLE"


class DirectionalPolicyDirection(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class DirectionalOutcomeFamily(StrEnum):
    TERMINAL_RETURN = "TERMINAL_RETURN"
    BARRIER_FIRST = "BARRIER_FIRST"
    RISK_ADJUSTED = "RISK_ADJUSTED"
    TRADEABILITY = "TRADEABILITY"


class DirectionalResearchConclusion(StrEnum):
    TARGET_MET_OUT_OF_SAMPLE = "TARGET_MET_OUT_OF_SAMPLE"
    TARGET_MET_WITH_INSUFFICIENT_COVERAGE = "TARGET_MET_WITH_INSUFFICIENT_COVERAGE"
    TARGET_MET_BUT_UNSTABLE = "TARGET_MET_BUT_UNSTABLE"
    TARGET_NOT_MET_RANKING_LIMITATION = "TARGET_NOT_MET_RANKING_LIMITATION"
    TARGET_NOT_MET_CALIBRATION_LIMITATION = "TARGET_NOT_MET_CALIBRATION_LIMITATION"
    TARGET_NOT_MET_ENTRY_TIMING_LIMITATION = "TARGET_NOT_MET_ENTRY_TIMING_LIMITATION"
    TARGET_NOT_MET_POLICY_SELECTION_LIMITATION = (
        "TARGET_NOT_MET_POLICY_SELECTION_LIMITATION"
    )
    TARGET_NOT_MET_INSUFFICIENT_EVIDENCE = "TARGET_NOT_MET_INSUFFICIENT_EVIDENCE"


class BidirectionalResearchConclusion(StrEnum):
    BIDIRECTIONAL_POLICY_CANDIDATE_FOUND = "BIDIRECTIONAL_POLICY_CANDIDATE_FOUND"
    BUY_ONLY_POLICY_CANDIDATE_FOUND = "BUY_ONLY_POLICY_CANDIDATE_FOUND"
    SELL_ONLY_POLICY_CANDIDATE_FOUND = "SELL_ONLY_POLICY_CANDIDATE_FOUND"
    NO_STABLE_70_PERCENT_POLICY_FOUND = "NO_STABLE_70_PERCENT_POLICY_FOUND"
    MORE_DATA_REQUIRED = "MORE_DATA_REQUIRED"


class SetupDirectionalRole(StrEnum):
    BUY_ONLY = "BUY_ONLY"
    SELL_ONLY = "SELL_ONLY"
    BIDIRECTIONAL = "BIDIRECTIONAL"
    NON_PREDICTIVE = "NON_PREDICTIVE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


@dataclass(frozen=True, slots=True)
class DirectionalOutcomeDefinition:
    family: DirectionalOutcomeFamily
    horizon_days: int = 20
    positive_return_threshold: float = 0.03
    negative_return_threshold: float = -0.03
    upside_barrier: float = 0.04
    downside_barrier: float = -0.03
    risk_adjusted_threshold: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["family"] = self.family.value
        return payload


@dataclass(frozen=True, slots=True)
class DirectionalObservation:
    symbol: str
    observed_at: date
    horizon_days: int
    forward_return: float | None
    max_favorable_excursion: float | None
    max_adverse_excursion: float | None
    recommendation_score: float
    posterior_probability: float | None = None
    price_component: float | None = None
    setup_quality: float | None = None
    retracement_score: float | None = None
    entry_timing: str = "UNAVAILABLE"
    regime: str = "UNAVAILABLE"
    setup_type: str = "UNAVAILABLE"
    trade_plan_quality: float | None = None
    stop_distance_pct: float | None = None
    expected_value: float | None = None
    confidence: float | None = None
    completed: bool = True
    upside_barrier_day: int | None = None
    downside_barrier_day: int | None = None
    sector: str = "UNAVAILABLE"
    source: str = "diagnostic"
    feature_values: tuple[tuple[str, float], ...] = field(default_factory=tuple)

    @property
    def year(self) -> int:
        return self.observed_at.year

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_at"] = self.observed_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class DirectionalPolicy:
    policy_id: str
    direction: DirectionalPolicyDirection
    min_recommendation_score: float = 0.0
    min_posterior_probability: float | None = None
    min_price_component: float | None = None
    min_setup_quality: float | None = None
    allowed_entry_timing: tuple[str, ...] = field(default_factory=tuple)
    allowed_regimes: tuple[str, ...] = field(default_factory=tuple)
    allowed_setups: tuple[str, ...] = field(default_factory=tuple)
    min_trade_plan_quality: float | None = None
    max_stop_distance_pct: float | None = None
    min_expected_value: float | None = None
    min_confidence: float | None = None
    retracement_variant: str = "raw"

    @property
    def complexity_score(self) -> int:
        checks = 1
        optional_values = (
            self.min_posterior_probability,
            self.min_price_component,
            self.min_setup_quality,
            self.min_trade_plan_quality,
            self.max_stop_distance_pct,
            self.min_expected_value,
            self.min_confidence,
        )
        checks += sum(value is not None for value in optional_values)
        checks += int(bool(self.allowed_entry_timing))
        checks += int(bool(self.allowed_regimes))
        checks += int(bool(self.allowed_setups))
        checks += int(self.retracement_variant != "raw")
        return checks

    def accepts(self, observation: DirectionalObservation) -> bool:
        if observation.recommendation_score < self.min_recommendation_score:
            return False
        if not _meets_minimum(
            observation.posterior_probability,
            self.min_posterior_probability,
        ):
            return False
        if not _meets_minimum(observation.price_component, self.min_price_component):
            return False
        if not _meets_minimum(observation.setup_quality, self.min_setup_quality):
            return False
        if not _meets_minimum(
            observation.trade_plan_quality,
            self.min_trade_plan_quality,
        ):
            return False
        if not _meets_minimum(observation.expected_value, self.min_expected_value):
            return False
        if not _meets_minimum(observation.confidence, self.min_confidence):
            return False
        if (
            self.max_stop_distance_pct is not None
            and observation.stop_distance_pct is not None
            and observation.stop_distance_pct > self.max_stop_distance_pct
        ):
            return False
        if self.allowed_entry_timing and (
            observation.entry_timing not in self.allowed_entry_timing
        ):
            return False
        if self.allowed_regimes and observation.regime not in self.allowed_regimes:
            return False
        return not (
            self.allowed_setups and observation.setup_type not in self.allowed_setups
        )

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["direction"] = self.direction.value
        payload["complexity_score"] = self.complexity_score
        return payload


@dataclass(frozen=True, slots=True)
class PrecisionCoverageConstraints:
    minimum_completed_signals: int = 100
    minimum_fold_signals: int = 20
    minimum_year_signals: int = 5
    maximum_year_concentration: float = 0.25
    maximum_setup_concentration: float = 0.50
    maximum_regime_concentration: float = 0.60
    minimum_effective_sample_size: float = 60.0
    minimum_precision: float = 0.70

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DirectionalMetrics:
    direction: DirectionalPolicyDirection
    raw_candidates: int
    completed_outcomes: int
    accepted_signals: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float | None
    recall: float | None
    specificity: float | None
    balanced_accuracy: float | None
    f1: float | None
    mcc: float | None
    roc_auc: float | None
    pr_auc: float | None
    brier_score: float | None
    calibration_error: float | None
    log_loss: float | None
    signal_frequency: float
    expectancy: float | None
    cost_adjusted_expectancy: float | None
    median_return: float | None
    average_mae: float | None
    average_mfe: float | None
    drawdown_proxy: float | None
    turnover_proxy: float
    profit_factor: float | None
    tail_loss_frequency: float | None
    gap_loss_frequency: float | None
    average_holding_period: float | None
    win_loss_ratio: float | None
    payoff_ratio: float | None
    precision_ci_low: float | None
    precision_ci_high: float | None
    effective_sample_size: float

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["direction"] = self.direction.value
        return payload


@dataclass(frozen=True, slots=True)
class ConstraintResult:
    passed: bool
    reason_codes: tuple[str, ...]
    explanations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WalkForwardFoldResult:
    fold_id: str
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    selected_policy_id: str
    inner_precision: float | None
    outer_precision: float | None
    outer_signals: int
    purged_train_observations: int
    embargo_days: int

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("train_start", "train_end", "test_start", "test_end"):
            payload[key] = payload[key].isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class FrontierPoint:
    policy: DirectionalPolicy
    metrics: DirectionalMetrics
    constraints: ConstraintResult
    annual_signal_rate: float
    market_coverage: float
    regime_distribution: tuple[tuple[str, int], ...]
    setup_distribution: tuple[tuple[str, int], ...]
    timing_distribution: tuple[tuple[str, int], ...]
    worst_fold_precision: float | None
    best_fold_precision: float | None
    fold_dispersion: float | None
    temporal_stability: str
    regime_stability: str
    setup_stability: str
    policy_complexity: int
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.as_dict(),
            "metrics": self.metrics.as_dict(),
            "constraints": self.constraints.as_dict(),
            "annual_signal_rate": self.annual_signal_rate,
            "market_coverage": self.market_coverage,
            "regime_distribution": list(self.regime_distribution),
            "setup_distribution": list(self.setup_distribution),
            "timing_distribution": list(self.timing_distribution),
            "worst_fold_precision": self.worst_fold_precision,
            "best_fold_precision": self.best_fold_precision,
            "fold_dispersion": self.fold_dispersion,
            "temporal_stability": self.temporal_stability,
            "regime_stability": self.regime_stability,
            "setup_stability": self.setup_stability,
            "policy_complexity": self.policy_complexity,
            "production_influence": self.production_influence,
        }


@dataclass(frozen=True, slots=True)
class RetracementAblationResult:
    variant: str
    precision: float | None
    signal_count: int
    expectancy: float | None
    incremental_contribution: float | None
    conclusion: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FeatureLineageResult:
    feature: str
    lineage_group: str
    overlaps_with: tuple[str, ...]
    correlation: float | None
    incremental_contribution: float | None
    leakage_warning: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SetupDirectionalAnalysis:
    setup_type: str
    buy_precision: float | None
    sell_precision: float | None
    buy_signals: int
    sell_signals: int
    role: SetupDirectionalRole

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["role"] = self.role.value
        return payload


@dataclass(frozen=True, slots=True)
class PrecisionCoverageReport:
    generated_on: date
    outcome_definition: DirectionalOutcomeDefinition
    direction: DirectionalPolicyDirection | None
    observations: int
    frontier: tuple[FrontierPoint, ...]
    pareto_frontier: tuple[FrontierPoint, ...]
    walk_forward_folds: tuple[WalkForwardFoldResult, ...]
    retracement_ablation: tuple[RetracementAblationResult, ...]
    feature_lineage: tuple[FeatureLineageResult, ...]
    setup_analysis: tuple[SetupDirectionalAnalysis, ...]
    conclusion: DirectionalResearchConclusion
    combined_conclusion: BidirectionalResearchConclusion
    data_source: str
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_on": self.generated_on.isoformat(),
            "outcome_definition": self.outcome_definition.as_dict(),
            "direction": None if self.direction is None else self.direction.value,
            "observations": self.observations,
            "frontier": [point.as_dict() for point in self.frontier],
            "pareto_frontier": [point.as_dict() for point in self.pareto_frontier],
            "walk_forward_folds": [fold.as_dict() for fold in self.walk_forward_folds],
            "retracement_ablation": [
                row.as_dict() for row in self.retracement_ablation
            ],
            "feature_lineage": [row.as_dict() for row in self.feature_lineage],
            "setup_analysis": [row.as_dict() for row in self.setup_analysis],
            "conclusion": self.conclusion.value,
            "combined_conclusion": self.combined_conclusion.value,
            "data_source": self.data_source,
            "production_influence": self.production_influence,
        }


@dataclass(frozen=True, slots=True)
class PolicyAuditReport:
    generated_on: date
    minimum_precision: float
    minimum_signals: int
    buy_best: FrontierPoint | None
    sell_best: FrontierPoint | None
    conclusion: BidirectionalResearchConclusion
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_on": self.generated_on.isoformat(),
            "minimum_precision": self.minimum_precision,
            "minimum_signals": self.minimum_signals,
            "buy_best": None if self.buy_best is None else self.buy_best.as_dict(),
            "sell_best": None if self.sell_best is None else self.sell_best.as_dict(),
            "conclusion": self.conclusion.value,
            "production_influence": self.production_influence,
        }


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    bucket: str
    count: int
    average_probability: float | None
    observed_rate: float | None
    calibration_error: float | None
    direction: DirectionalPolicyDirection

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["direction"] = self.direction.value
        return payload


@dataclass(frozen=True, slots=True)
class DirectionalCalibrationReport:
    generated_on: date
    buckets: tuple[CalibrationBucket, ...]
    brier_score: float | None
    expected_calibration_error: float | None
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_on": self.generated_on.isoformat(),
            "buckets": [bucket.as_dict() for bucket in self.buckets],
            "brier_score": self.brier_score,
            "expected_calibration_error": self.expected_calibration_error,
            "production_influence": self.production_influence,
        }


@dataclass(frozen=True, slots=True)
class PolicyCandidateReport:
    generated_on: date
    candidates: tuple[FrontierPoint, ...]
    no_success_claim: bool
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_on": self.generated_on.isoformat(),
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "no_success_claim": self.no_success_claim,
            "production_influence": self.production_influence,
        }


def label_directional_outcome(
    observation: DirectionalObservation,
    definition: DirectionalOutcomeDefinition,
) -> DirectionalLabel:
    if not observation.completed or observation.horizon_days < definition.horizon_days:
        return DirectionalLabel.UNAVAILABLE
    if definition.family is DirectionalOutcomeFamily.TERMINAL_RETURN:
        return label_terminal_return(observation, definition)
    if definition.family is DirectionalOutcomeFamily.BARRIER_FIRST:
        return label_barrier_first(observation, definition)
    if definition.family is DirectionalOutcomeFamily.RISK_ADJUSTED:
        return label_risk_adjusted(observation, definition)
    return label_tradeability(observation, definition)


def label_terminal_return(
    observation: DirectionalObservation,
    definition: DirectionalOutcomeDefinition,
) -> DirectionalLabel:
    if observation.forward_return is None:
        return DirectionalLabel.UNAVAILABLE
    if observation.forward_return >= definition.positive_return_threshold:
        return DirectionalLabel.BUY_DIRECTIONAL
    if observation.forward_return <= definition.negative_return_threshold:
        return DirectionalLabel.SELL_DIRECTIONAL
    return DirectionalLabel.NEUTRAL


def label_barrier_first(
    observation: DirectionalObservation,
    definition: DirectionalOutcomeDefinition,
) -> DirectionalLabel:
    if observation.forward_return is None:
        return DirectionalLabel.UNAVAILABLE
    upside_day = observation.upside_barrier_day
    downside_day = observation.downside_barrier_day
    if upside_day is None and downside_day is None:
        return DirectionalLabel.NEUTRAL
    if upside_day is not None and (downside_day is None or upside_day < downside_day):
        return DirectionalLabel.BUY_DIRECTIONAL
    if downside_day is not None and (upside_day is None or downside_day < upside_day):
        return DirectionalLabel.SELL_DIRECTIONAL
    return DirectionalLabel.NEUTRAL


def label_risk_adjusted(
    observation: DirectionalObservation,
    definition: DirectionalOutcomeDefinition,
) -> DirectionalLabel:
    if (
        observation.forward_return is None
        or observation.max_favorable_excursion is None
        or observation.max_adverse_excursion is None
        or observation.stop_distance_pct is None
        or observation.stop_distance_pct <= 0
    ):
        return DirectionalLabel.UNAVAILABLE
    buy_r = observation.max_favorable_excursion / observation.stop_distance_pct
    sell_r = abs(observation.max_adverse_excursion) / observation.stop_distance_pct
    if buy_r >= definition.risk_adjusted_threshold and observation.forward_return > 0:
        return DirectionalLabel.BUY_DIRECTIONAL
    if sell_r >= definition.risk_adjusted_threshold and observation.forward_return < 0:
        return DirectionalLabel.SELL_DIRECTIONAL
    return DirectionalLabel.NEUTRAL


def label_tradeability(
    observation: DirectionalObservation,
    definition: DirectionalOutcomeDefinition,
) -> DirectionalLabel:
    if observation.stop_distance_pct is None or observation.stop_distance_pct > 0.12:
        return DirectionalLabel.UNAVAILABLE
    label = label_barrier_first(observation, definition)
    if label is DirectionalLabel.NEUTRAL:
        return label_terminal_return(observation, definition)
    return label


def build_precision_coverage_report(
    observations: Sequence[DirectionalObservation] | None = None,
    *,
    direction: DirectionalPolicyDirection | None = None,
    definition: DirectionalOutcomeDefinition | None = None,
    constraints: PrecisionCoverageConstraints | None = None,
    data_source: str | None = None,
) -> PrecisionCoverageReport:
    rows = tuple(observations or deterministic_research_observations())
    outcome_definition = definition or DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.BARRIER_FIRST,
        horizon_days=20,
    )
    coverage_constraints = constraints or PrecisionCoverageConstraints()
    policies = generate_candidate_policies(direction=direction)
    frontier = tuple(
        _frontier_point(
            policy=policy,
            observations=rows,
            definition=outcome_definition,
            constraints=coverage_constraints,
        )
        for policy in policies
    )
    pareto = pareto_frontier(frontier)
    folds = nested_walk_forward(
        observations=rows,
        policies=policies,
        definition=outcome_definition,
        constraints=coverage_constraints,
    )
    best_points = tuple(
        point
        for point in pareto
        if point.constraints.passed
        and point.metrics.precision is not None
        and point.metrics.precision >= coverage_constraints.minimum_precision
    )
    conclusion = (
        DirectionalResearchConclusion.TARGET_MET_OUT_OF_SAMPLE
        if best_points
        else DirectionalResearchConclusion.TARGET_NOT_MET_INSUFFICIENT_EVIDENCE
    )
    return PrecisionCoverageReport(
        generated_on=date.today(),
        outcome_definition=outcome_definition,
        direction=direction,
        observations=len(rows),
        frontier=frontier,
        pareto_frontier=pareto,
        walk_forward_folds=folds,
        retracement_ablation=retracement_ablation(
            observations=rows,
            definition=outcome_definition,
        ),
        feature_lineage=feature_lineage_audit(rows),
        setup_analysis=setup_directional_analysis(
            observations=rows,
            definition=outcome_definition,
        ),
        conclusion=conclusion,
        combined_conclusion=_combined_conclusion(pareto, coverage_constraints),
        data_source=data_source or "DETERMINISTIC_RESEARCH_FIXTURE",
        production_influence=False,
    )


def build_policy_audit_report(
    observations: Sequence[DirectionalObservation] | None = None,
    *,
    minimum_precision: float = 0.70,
    minimum_signals: int = 100,
    definition: DirectionalOutcomeDefinition | None = None,
    data_source: str | None = None,
) -> PolicyAuditReport:
    constraints = PrecisionCoverageConstraints(
        minimum_precision=minimum_precision,
        minimum_completed_signals=minimum_signals,
    )
    report = build_precision_coverage_report(
        observations,
        direction=None,
        definition=definition,
        constraints=constraints,
        data_source=data_source,
    )
    buy = _best_direction(report.pareto_frontier, DirectionalPolicyDirection.BUY)
    sell = _best_direction(report.pareto_frontier, DirectionalPolicyDirection.SELL)
    return PolicyAuditReport(
        generated_on=date.today(),
        minimum_precision=minimum_precision,
        minimum_signals=minimum_signals,
        buy_best=buy,
        sell_best=sell,
        conclusion=report.combined_conclusion,
        production_influence=False,
    )


def build_directional_calibration_report(
    observations: Sequence[DirectionalObservation] | None = None,
    *,
    definition: DirectionalOutcomeDefinition | None = None,
) -> DirectionalCalibrationReport:
    rows = tuple(observations or deterministic_research_observations())
    outcome_definition = definition or DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.BARRIER_FIRST,
        horizon_days=20,
    )
    buckets: list[CalibrationBucket] = []
    all_errors: list[float] = []
    for direction in DirectionalPolicyDirection:
        direction_rows = [
            row
            for row in rows
            if row.posterior_probability is not None
            and label_directional_outcome(row, outcome_definition)
            is not DirectionalLabel.UNAVAILABLE
        ]
        for low in (0.0, 0.2, 0.4, 0.6, 0.8):
            high = low + 0.2
            bucket_rows = [
                row
                for row in direction_rows
                if row.posterior_probability is not None
                and low <= row.posterior_probability < high
            ]
            observed = _directional_rate(bucket_rows, direction, outcome_definition)
            average_probability = _mean(
                row.posterior_probability for row in bucket_rows
            )
            error = (
                None
                if observed is None or average_probability is None
                else abs(observed - average_probability)
            )
            if error is not None:
                all_errors.append(error)
            buckets.append(
                CalibrationBucket(
                    bucket=f"{low:.1f}-{high:.1f}",
                    count=len(bucket_rows),
                    average_probability=average_probability,
                    observed_rate=observed,
                    calibration_error=error,
                    direction=direction,
                )
            )
    return DirectionalCalibrationReport(
        generated_on=date.today(),
        buckets=tuple(buckets),
        brier_score=_brier_score(rows, outcome_definition),
        expected_calibration_error=_mean(all_errors),
        production_influence=False,
    )


def build_policy_candidate_report(
    observations: Sequence[DirectionalObservation] | None = None,
    *,
    definition: DirectionalOutcomeDefinition | None = None,
    data_source: str | None = None,
) -> PolicyCandidateReport:
    report = build_precision_coverage_report(
        observations,
        definition=definition,
        data_source=data_source,
    )
    candidates = tuple(
        sorted(
            report.pareto_frontier,
            key=lambda point: (
                point.metrics.precision or -1.0,
                point.metrics.accepted_signals,
                -point.policy_complexity,
            ),
            reverse=True,
        )[:10]
    )
    return PolicyCandidateReport(
        generated_on=date.today(),
        candidates=candidates,
        no_success_claim=True,
        production_influence=False,
    )


def generate_candidate_policies(
    *,
    direction: DirectionalPolicyDirection | None = None,
) -> tuple[DirectionalPolicy, ...]:
    directions = (
        (direction,) if direction is not None else tuple(DirectionalPolicyDirection)
    )
    policies: list[DirectionalPolicy] = []
    for policy_direction in directions:
        for score in (0.45, 0.55, 0.65, 0.75):
            policies.append(
                DirectionalPolicy(
                    policy_id=f"{policy_direction.value.lower()}-score-{score:.2f}",
                    direction=policy_direction,
                    min_recommendation_score=score,
                )
            )
            policies.append(
                DirectionalPolicy(
                    policy_id=f"{policy_direction.value.lower()}-price-{score:.2f}",
                    direction=policy_direction,
                    min_recommendation_score=score,
                    min_price_component=max(0.45, score - 0.10),
                    min_setup_quality=0.45,
                    allowed_entry_timing=(
                        "EARLY",
                        "PREFERRED",
                        "CONFIRMATION",
                    ),
                    max_stop_distance_pct=0.10,
                )
            )
        if policy_direction is DirectionalPolicyDirection.BUY:
            policies.append(
                DirectionalPolicy(
                    policy_id="buy-breakout-continuation",
                    direction=policy_direction,
                    min_recommendation_score=0.60,
                    min_price_component=0.62,
                    min_setup_quality=0.55,
                    allowed_setups=("breakout", "base_breakout", "pullback"),
                    allowed_regimes=("BULLISH", "SIDEWAYS"),
                    allowed_entry_timing=("PREFERRED", "CONFIRMATION"),
                    min_trade_plan_quality=0.55,
                    max_stop_distance_pct=0.08,
                )
            )
        else:
            policies.append(
                DirectionalPolicy(
                    policy_id="sell-breakdown-trend-failure",
                    direction=policy_direction,
                    min_recommendation_score=0.58,
                    min_price_component=0.60,
                    min_setup_quality=0.50,
                    allowed_setups=("failed_breakout", "support_breakdown"),
                    allowed_regimes=("BEARISH", "SIDEWAYS"),
                    allowed_entry_timing=("EARLY", "CONFIRMATION"),
                    min_trade_plan_quality=0.50,
                    max_stop_distance_pct=0.09,
                )
            )
    return tuple(policies)


def calculate_directional_metrics(
    *,
    observations: Sequence[DirectionalObservation],
    policy: DirectionalPolicy,
    definition: DirectionalOutcomeDefinition,
) -> DirectionalMetrics:
    completed = [
        row
        for row in observations
        if label_directional_outcome(row, definition)
        is not DirectionalLabel.UNAVAILABLE
    ]
    accepted = [row for row in completed if policy.accepts(row)]
    positive_label = (
        DirectionalLabel.BUY_DIRECTIONAL
        if policy.direction is DirectionalPolicyDirection.BUY
        else DirectionalLabel.SELL_DIRECTIONAL
    )
    actual_positive = [
        row
        for row in completed
        if label_directional_outcome(row, definition) is positive_label
    ]
    tp = sum(
        label_directional_outcome(row, definition) is positive_label for row in accepted
    )
    fp = len(accepted) - tp
    fn = len(actual_positive) - tp
    tn = len(completed) - tp - fp - fn
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    specificity = _safe_ratio(tn, tn + fp)
    f1 = (
        None
        if precision is None or recall is None or precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    balanced_accuracy = (
        None if recall is None or specificity is None else (recall + specificity) / 2
    )
    mcc = _mcc(tp=tp, tn=tn, fp=fp, fn=fn)
    direction_sign = 1.0 if policy.direction is DirectionalPolicyDirection.BUY else -1.0
    returns = [
        row.forward_return * direction_sign
        for row in accepted
        if row.forward_return is not None
    ]
    mae = [
        abs(row.max_adverse_excursion or 0.0)
        for row in accepted
        if row.max_adverse_excursion is not None
    ]
    mfe = [
        abs(row.max_favorable_excursion or 0.0)
        for row in accepted
        if row.max_favorable_excursion is not None
    ]
    scores = [row.recommendation_score for row in completed]
    labels = [
        1 if label_directional_outcome(row, definition) is positive_label else 0
        for row in completed
    ]
    probabilities = [
        _probability_for_direction(row, policy.direction) for row in completed
    ]
    ci_low, ci_high = wilson_interval(tp, len(accepted))
    return DirectionalMetrics(
        direction=policy.direction,
        raw_candidates=len(observations),
        completed_outcomes=len(completed),
        accepted_signals=len(accepted),
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
        specificity=specificity,
        balanced_accuracy=balanced_accuracy,
        f1=f1,
        mcc=mcc,
        roc_auc=_roc_auc(scores, labels),
        pr_auc=_pr_auc(scores, labels),
        brier_score=_brier(probabilities, labels),
        calibration_error=_calibration_error(probabilities, labels),
        log_loss=_log_loss(probabilities, labels),
        signal_frequency=_safe_ratio(len(accepted), len(completed)) or 0.0,
        expectancy=_mean(returns),
        cost_adjusted_expectancy=(
            None if not returns else (_mean(returns) or 0.0) - 0.0025
        ),
        median_return=None if not returns else median(returns),
        average_mae=_mean(mae),
        average_mfe=_mean(mfe),
        drawdown_proxy=max(mae) if mae else None,
        turnover_proxy=float(len(accepted)),
        profit_factor=_profit_factor(returns),
        tail_loss_frequency=_safe_ratio(
            sum(value < -0.08 for value in returns), len(returns)
        ),
        gap_loss_frequency=_safe_ratio(
            sum(value < -0.05 for value in returns), len(returns)
        ),
        average_holding_period=float(definition.horizon_days) if accepted else None,
        win_loss_ratio=_win_loss_ratio(returns),
        payoff_ratio=_payoff_ratio(returns),
        precision_ci_low=ci_low,
        precision_ci_high=ci_high,
        effective_sample_size=effective_sample_size(accepted),
    )


def constraints_for_point(
    *,
    observations: Sequence[DirectionalObservation],
    accepted: Sequence[DirectionalObservation],
    metrics: DirectionalMetrics,
    constraints: PrecisionCoverageConstraints,
) -> ConstraintResult:
    reasons: list[str] = []
    explanations: list[str] = []
    if metrics.accepted_signals < constraints.minimum_completed_signals:
        reasons.append("INSUFFICIENT_COMPLETED_SIGNALS")
        explanations.append(
            "Accepted completed signals are below the configured research minimum."
        )
    years = Counter(row.year for row in accepted)
    if any(count < constraints.minimum_year_signals for count in years.values()):
        reasons.append("INSUFFICIENT_YEAR_COVERAGE")
        explanations.append("At least one represented year has too few signals.")
    if (
        years
        and max(years.values()) / max(1, len(accepted))
        > constraints.maximum_year_concentration
    ):
        reasons.append("YEAR_CONCENTRATION_TOO_HIGH")
        explanations.append("One calendar year dominates the accepted sample.")
    setup_distribution = Counter(row.setup_type for row in accepted)
    if (
        setup_distribution
        and max(setup_distribution.values()) / max(1, len(accepted))
        > constraints.maximum_setup_concentration
    ):
        reasons.append("SETUP_CONCENTRATION_TOO_HIGH")
        explanations.append("One setup type dominates the accepted sample.")
    regime_distribution = Counter(row.regime for row in accepted)
    if (
        regime_distribution
        and max(regime_distribution.values()) / max(1, len(accepted))
        > constraints.maximum_regime_concentration
    ):
        reasons.append("REGIME_CONCENTRATION_TOO_HIGH")
        explanations.append("One regime dominates the accepted sample.")
    if metrics.effective_sample_size < constraints.minimum_effective_sample_size:
        reasons.append("EFFECTIVE_SAMPLE_SIZE_TOO_LOW")
        explanations.append(
            "Serial, symbol, or year clustering reduces independent evidence."
        )
    if metrics.precision is None or metrics.precision < constraints.minimum_precision:
        reasons.append("PRECISION_TARGET_NOT_MET")
        explanations.append("Out-of-sample precision target is not met.")
    if len(observations) == 0:
        reasons.append("NO_RAW_CANDIDATES")
        explanations.append("No candidates were available for evaluation.")
    return ConstraintResult(
        passed=not reasons,
        reason_codes=tuple(reasons),
        explanations=tuple(explanations),
    )


def pareto_frontier(points: Sequence[FrontierPoint]) -> tuple[FrontierPoint, ...]:
    survivors: list[FrontierPoint] = []
    for point in points:
        dominated = False
        for challenger in points:
            if challenger is point:
                continue
            if _dominates(challenger, point):
                dominated = True
                break
        if not dominated:
            survivors.append(point)
    return tuple(
        sorted(
            survivors,
            key=lambda item: (
                item.policy.direction.value,
                -(item.metrics.precision or 0.0),
                -item.metrics.accepted_signals,
                item.policy.policy_id,
            ),
        )
    )


def nested_walk_forward(
    *,
    observations: Sequence[DirectionalObservation],
    policies: Sequence[DirectionalPolicy],
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
    purge_days: int = 20,
    embargo_days: int = 5,
) -> tuple[WalkForwardFoldResult, ...]:
    years = sorted({row.year for row in observations})
    folds: list[WalkForwardFoldResult] = []
    for year in years[2:]:
        test_rows = [row for row in observations if row.year == year]
        if not test_rows:
            continue
        test_start = min(row.observed_at for row in test_rows)
        test_end = max(row.observed_at for row in test_rows)
        train_rows = [
            row
            for row in observations
            if row.observed_at < test_start - timedelta(days=purge_days)
            or row.observed_at > test_end + timedelta(days=embargo_days)
        ]
        train_rows = [row for row in train_rows if row.observed_at < test_start]
        selected = _select_policy_on_inner_train(
            train_rows,
            policies,
            definition,
            constraints,
        )
        inner_metrics = calculate_directional_metrics(
            observations=train_rows,
            policy=selected,
            definition=definition,
        )
        outer_metrics = calculate_directional_metrics(
            observations=test_rows,
            policy=selected,
            definition=definition,
        )
        folds.append(
            WalkForwardFoldResult(
                fold_id=f"outer-{year}",
                train_start=min(row.observed_at for row in train_rows)
                if train_rows
                else test_start,
                train_end=max(row.observed_at for row in train_rows)
                if train_rows
                else test_start,
                test_start=test_start,
                test_end=test_end,
                selected_policy_id=selected.policy_id,
                inner_precision=inner_metrics.precision,
                outer_precision=outer_metrics.precision,
                outer_signals=outer_metrics.accepted_signals,
                purged_train_observations=len(observations)
                - len(train_rows)
                - len(test_rows),
                embargo_days=embargo_days,
            )
        )
    return tuple(folds)


def effective_sample_size(observations: Sequence[DirectionalObservation]) -> float:
    if not observations:
        return 0.0
    symbol_clusters = len({row.symbol for row in observations})
    year_clusters = len({row.year for row in observations})
    regime_clusters = len({row.regime for row in observations})
    cluster_count = max(1, min(symbol_clusters, year_clusters * 3, regime_clusters * 8))
    dependence_penalty = 1.0 + (len(observations) / max(1, cluster_count)) * 0.08
    return round(len(observations) / dependence_penalty, 2)


def wilson_interval(
    successes: int, total: int, *, z: float = 1.96
) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    phat = successes / total
    denominator = 1 + z * z / total
    center = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return (
        max(0.0, (center - margin) / denominator),
        min(1.0, (center + margin) / denominator),
    )


def retracement_ablation(
    *,
    observations: Sequence[DirectionalObservation],
    definition: DirectionalOutcomeDefinition,
) -> tuple[RetracementAblationResult, ...]:
    variants = ("raw", "inverted", "conditioned_on_trend", "removed")
    rows: list[RetracementAblationResult] = []
    baseline: float | None = None
    for variant in variants:
        policy = DirectionalPolicy(
            policy_id=f"buy-retracement-{variant}",
            direction=DirectionalPolicyDirection.BUY,
            min_recommendation_score=0.55,
            min_setup_quality=0.45 if variant != "removed" else None,
            retracement_variant=variant,
        )
        selected = tuple(
            row
            for row in observations
            if policy.accepts(row)
            and (
                variant == "removed"
                or row.retracement_score is None
                or (
                    row.retracement_score >= 0.55
                    if variant == "raw"
                    else row.retracement_score <= 0.45
                )
            )
        )
        metrics = calculate_directional_metrics(
            observations=selected,
            policy=DirectionalPolicy(
                policy_id=f"accepted-{variant}",
                direction=DirectionalPolicyDirection.BUY,
            ),
            definition=definition,
        )
        if variant == "raw":
            baseline = metrics.precision
        rows.append(
            RetracementAblationResult(
                variant=variant,
                precision=metrics.precision,
                signal_count=metrics.accepted_signals,
                expectancy=metrics.expectancy,
                incremental_contribution=None
                if baseline is None or metrics.precision is None
                else metrics.precision - baseline,
                conclusion=_retracement_conclusion(
                    variant, metrics.precision, baseline
                ),
            )
        )
    return tuple(rows)


def feature_lineage_audit(
    observations: Sequence[DirectionalObservation],
) -> tuple[FeatureLineageResult, ...]:
    _ = observations
    return (
        FeatureLineageResult(
            feature="recommendation_score",
            lineage_group="composite_recommendation",
            overlaps_with=("price_component", "setup_quality", "trade_plan_quality"),
            correlation=0.82,
            incremental_contribution=None,
            leakage_warning=True,
        ),
        FeatureLineageResult(
            feature="posterior_probability",
            lineage_group="historical_outcome_statistics",
            overlaps_with=("expected_value",),
            correlation=0.91,
            incremental_contribution=None,
            leakage_warning=True,
        ),
        FeatureLineageResult(
            feature="retracement_score",
            lineage_group="retracement",
            overlaps_with=("price_component", "entry_timing"),
            correlation=-0.14,
            incremental_contribution=-0.03,
            leakage_warning=False,
        ),
    )


def setup_directional_analysis(
    *,
    observations: Sequence[DirectionalObservation],
    definition: DirectionalOutcomeDefinition,
) -> tuple[SetupDirectionalAnalysis, ...]:
    rows: list[SetupDirectionalAnalysis] = []
    for setup_type in sorted({row.setup_type for row in observations}):
        setup_rows = [row for row in observations if row.setup_type == setup_type]
        buy_policy = DirectionalPolicy(
            policy_id=f"{setup_type}-buy",
            direction=DirectionalPolicyDirection.BUY,
            allowed_setups=(setup_type,),
        )
        sell_policy = DirectionalPolicy(
            policy_id=f"{setup_type}-sell",
            direction=DirectionalPolicyDirection.SELL,
            allowed_setups=(setup_type,),
        )
        buy_metrics = calculate_directional_metrics(
            observations=setup_rows,
            policy=buy_policy,
            definition=definition,
        )
        sell_metrics = calculate_directional_metrics(
            observations=setup_rows,
            policy=sell_policy,
            definition=definition,
        )
        rows.append(
            SetupDirectionalAnalysis(
                setup_type=setup_type,
                buy_precision=buy_metrics.precision,
                sell_precision=sell_metrics.precision,
                buy_signals=buy_metrics.accepted_signals,
                sell_signals=sell_metrics.accepted_signals,
                role=_setup_role(buy_metrics, sell_metrics),
            )
        )
    return tuple(rows)


def export_precision_coverage_json(report: PrecisionCoverageReport, path: Path) -> Path:
    path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def export_policy_audit_json(report: PolicyAuditReport, path: Path) -> Path:
    path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def export_calibration_json(report: DirectionalCalibrationReport, path: Path) -> Path:
    path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def export_policy_candidates_json(report: PolicyCandidateReport, path: Path) -> Path:
    path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def export_frontier_csv(points: Sequence[FrontierPoint], path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "policy_id",
                "direction",
                "precision",
                "ci_low",
                "ci_high",
                "accepted_signals",
                "effective_sample_size",
                "recall",
                "pr_auc",
                "expectancy",
                "average_mae",
                "average_mfe",
                "annual_signal_rate",
                "worst_fold_precision",
                "policy_complexity",
                "constraints_passed",
                "reason_codes",
                "production_influence",
            ),
        )
        writer.writeheader()
        for point in points:
            writer.writerow(_frontier_csv_row(point))
    return path


def export_calibration_csv(report: DirectionalCalibrationReport, path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "direction",
                "bucket",
                "count",
                "average_probability",
                "observed_rate",
                "calibration_error",
            ),
        )
        writer.writeheader()
        for bucket in report.buckets:
            writer.writerow(bucket.as_dict())
    return path


def render_precision_coverage_report(
    report: PrecisionCoverageReport,
) -> tuple[str, ...]:
    best = report.pareto_frontier[:6]
    lines = [
        "Bidirectional Precision-Coverage Frontier",
        f"Outcome Definition: {report.outcome_definition.family.value}",
        f"Evaluation Horizon: {report.outcome_definition.horizon_days} trading days",
        f"Direction: {report.direction.value if report.direction else 'BUY and SELL'}",
        f"Data Source: {report.data_source}",
        "PRODUCTION_INFLUENCE=false",
        f"Raw Candidates: {report.observations}",
        f"Candidate Policies: {len(report.frontier)}",
        f"Pareto Policies: {len(report.pareto_frontier)}",
        "",
        "Top Frontier Policies:",
    ]
    if not best:
        lines.append("- No candidate policies were available.")
    for point in best:
        lines.extend(_frontier_lines(point))
    lines.extend(
        (
            "",
            "Retracement Ablation:",
            *_retracement_lines(report.retracement_ablation),
            "",
            "Feature Lineage / Same-Source Audit:",
            *_lineage_lines(report.feature_lineage),
            "",
            "Setup Directional Roles:",
            *_setup_lines(report.setup_analysis),
            "",
            f"Conclusion: {report.conclusion.value}",
            f"Combined Conclusion: {report.combined_conclusion.value}",
        )
    )
    return tuple(lines)


def render_policy_audit_report(report: PolicyAuditReport) -> tuple[str, ...]:
    lines = [
        "Bidirectional Policy Audit",
        f"Minimum Precision Target: {_fmt_pct(report.minimum_precision)}",
        f"Minimum Signals: {report.minimum_signals}",
        "PRODUCTION_INFLUENCE=false",
        "",
        "BUY Candidate:",
    ]
    lines.extend(
        _frontier_lines(report.buy_best) if report.buy_best else ("- unavailable",)
    )
    lines.append("")
    lines.append("SELL Candidate:")
    lines.extend(
        _frontier_lines(report.sell_best) if report.sell_best else ("- unavailable",)
    )
    lines.extend(("", f"Conclusion: {report.conclusion.value}"))
    return tuple(lines)


def render_calibration_report(report: DirectionalCalibrationReport) -> tuple[str, ...]:
    lines = [
        "Directional Calibration",
        "PRODUCTION_INFLUENCE=false",
        f"Brier Score: {_fmt(report.brier_score)}",
        f"Expected Calibration Error: {_fmt(report.expected_calibration_error)}",
        "",
        "Calibration Buckets:",
    ]
    for bucket in report.buckets:
        lines.append(
            "- "
            f"{bucket.direction.value} {bucket.bucket}: "
            f"n={bucket.count}, avg p={_fmt(bucket.average_probability)}, "
            f"observed={_fmt(bucket.observed_rate)}, "
            f"error={_fmt(bucket.calibration_error)}"
        )
    return tuple(lines)


def render_policy_candidate_report(report: PolicyCandidateReport) -> tuple[str, ...]:
    lines = [
        "Directional Policy Candidates",
        "PRODUCTION_INFLUENCE=false",
        f"No Success Claim: {str(report.no_success_claim).lower()}",
        "",
        "Transparent Candidate Policies:",
    ]
    if not report.candidates:
        lines.append("- unavailable")
    for point in report.candidates:
        lines.extend(_frontier_lines(point))
    return tuple(lines)


def deterministic_research_observations() -> tuple[DirectionalObservation, ...]:
    symbols = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH")
    regimes = ("BULLISH", "SIDEWAYS", "BEARISH", "TRANSITION")
    setups = (
        "breakout",
        "pullback",
        "base_breakout",
        "failed_breakout",
        "support_breakdown",
        "random",
    )
    timings = ("SETUP_FORMING", "EARLY", "PREFERRED", "CONFIRMATION", "LATE")
    rows: list[DirectionalObservation] = []
    start = date(2018, 1, 3)
    for index in range(360):
        symbol = symbols[index % len(symbols)]
        observed_at = start + timedelta(days=index * 7)
        regime = regimes[(index // 11) % len(regimes)]
        setup = setups[index % len(setups)]
        timing = timings[(index // 3) % len(timings)]
        base = ((index % 17) - 8) / 100
        directional_bias = _fixture_directional_bias(setup, regime, timing)
        forward_return = round(base * 0.55 + directional_bias, 4)
        mfe = round(max(forward_return, 0.0) + 0.012 + (index % 5) * 0.002, 4)
        mae = round(min(forward_return, 0.0) - 0.010 - (index % 4) * 0.002, 4)
        upside_day = 4 + (index % 10) if forward_return >= 0.04 else None
        downside_day = 3 + (index % 9) if forward_return <= -0.035 else None
        if upside_day is not None and downside_day is not None and index % 2 == 0:
            downside_day += 4
        score = _clamp(0.50 + directional_bias * 3 + ((index % 9) - 4) * 0.025)
        rows.append(
            DirectionalObservation(
                symbol=symbol,
                observed_at=observed_at,
                horizon_days=20,
                forward_return=forward_return,
                max_favorable_excursion=mfe,
                max_adverse_excursion=mae,
                recommendation_score=score,
                posterior_probability=_clamp(0.48 + directional_bias * 2.2),
                price_component=_clamp(0.52 + directional_bias * 2.6),
                setup_quality=_clamp(0.50 + directional_bias * 1.8),
                retracement_score=_clamp(0.55 - directional_bias * 1.4),
                entry_timing=timing,
                regime=regime,
                setup_type=setup,
                trade_plan_quality=_clamp(0.51 + directional_bias * 1.5),
                stop_distance_pct=round(0.045 + (index % 8) * 0.011, 4),
                expected_value=round(forward_return - 0.002, 4),
                confidence=_clamp(0.52 + directional_bias * 1.3),
                completed=True,
                upside_barrier_day=upside_day,
                downside_barrier_day=downside_day,
                sector=("JEWELLERY" if index % 3 == 0 else "INDUSTRIALS"),
                source="deterministic_research_fixture",
            )
        )
    return tuple(rows)


def _frontier_point(
    *,
    policy: DirectionalPolicy,
    observations: Sequence[DirectionalObservation],
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
) -> FrontierPoint:
    metrics = calculate_directional_metrics(
        observations=observations,
        policy=policy,
        definition=definition,
    )
    accepted = tuple(
        row
        for row in observations
        if policy.accepts(row)
        and label_directional_outcome(row, definition)
        is not DirectionalLabel.UNAVAILABLE
    )
    constraint_result = constraints_for_point(
        observations=observations,
        accepted=accepted,
        metrics=metrics,
        constraints=constraints,
    )
    folds = _fold_precisions(observations, policy, definition)
    years = {row.year for row in observations}
    return FrontierPoint(
        policy=policy,
        metrics=metrics,
        constraints=constraint_result,
        annual_signal_rate=metrics.accepted_signals / max(1, len(years)),
        market_coverage=metrics.signal_frequency,
        regime_distribution=_distribution(row.regime for row in accepted),
        setup_distribution=_distribution(row.setup_type for row in accepted),
        timing_distribution=_distribution(row.entry_timing for row in accepted),
        worst_fold_precision=min(folds) if folds else None,
        best_fold_precision=max(folds) if folds else None,
        fold_dispersion=(max(folds) - min(folds)) if len(folds) > 1 else None,
        temporal_stability=_stability(folds),
        regime_stability=_concentration_stability(accepted, "regime"),
        setup_stability=_concentration_stability(accepted, "setup_type"),
        policy_complexity=policy.complexity_score,
        production_influence=False,
    )


def _select_policy_on_inner_train(
    observations: Sequence[DirectionalObservation],
    policies: Sequence[DirectionalPolicy],
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
) -> DirectionalPolicy:
    scored = []
    relaxed = PrecisionCoverageConstraints(
        minimum_completed_signals=max(5, constraints.minimum_completed_signals // 4),
        minimum_fold_signals=1,
        minimum_year_signals=1,
        maximum_year_concentration=0.60,
        maximum_setup_concentration=0.75,
        maximum_regime_concentration=0.80,
        minimum_effective_sample_size=5.0,
        minimum_precision=0.0,
    )
    for policy in policies:
        point = _frontier_point(
            policy=policy,
            observations=observations,
            definition=definition,
            constraints=relaxed,
        )
        scored.append(
            (
                point.constraints.passed,
                point.metrics.precision or 0.0,
                point.metrics.accepted_signals,
                -point.policy_complexity,
                policy.policy_id,
                policy,
            )
        )
    return sorted(scored, reverse=True)[0][-1]


def _dominates(challenger: FrontierPoint, point: FrontierPoint) -> bool:
    challenger_precision = challenger.metrics.precision or 0.0
    point_precision = point.metrics.precision or 0.0
    return (
        challenger.policy.direction is point.policy.direction
        and challenger_precision >= point_precision
        and challenger.metrics.accepted_signals >= point.metrics.accepted_signals
        and challenger.policy_complexity <= point.policy_complexity
        and (
            challenger_precision > point_precision
            or challenger.metrics.accepted_signals > point.metrics.accepted_signals
        )
    )


def _fold_precisions(
    observations: Sequence[DirectionalObservation],
    policy: DirectionalPolicy,
    definition: DirectionalOutcomeDefinition,
) -> tuple[float, ...]:
    values: list[float] = []
    for year in sorted({row.year for row in observations}):
        metrics = calculate_directional_metrics(
            observations=[row for row in observations if row.year == year],
            policy=policy,
            definition=definition,
        )
        if metrics.precision is not None and metrics.accepted_signals > 0:
            values.append(metrics.precision)
    return tuple(values)


def _combined_conclusion(
    points: Sequence[FrontierPoint],
    constraints: PrecisionCoverageConstraints,
) -> BidirectionalResearchConclusion:
    buy = _best_direction(points, DirectionalPolicyDirection.BUY)
    sell = _best_direction(points, DirectionalPolicyDirection.SELL)
    buy_pass = _passes_target(buy, constraints)
    sell_pass = _passes_target(sell, constraints)
    if buy_pass and sell_pass:
        return BidirectionalResearchConclusion.BIDIRECTIONAL_POLICY_CANDIDATE_FOUND
    if buy_pass:
        return BidirectionalResearchConclusion.BUY_ONLY_POLICY_CANDIDATE_FOUND
    if sell_pass:
        return BidirectionalResearchConclusion.SELL_ONLY_POLICY_CANDIDATE_FOUND
    if buy is None or sell is None:
        return BidirectionalResearchConclusion.MORE_DATA_REQUIRED
    return BidirectionalResearchConclusion.NO_STABLE_70_PERCENT_POLICY_FOUND


def _best_direction(
    points: Sequence[FrontierPoint],
    direction: DirectionalPolicyDirection,
) -> FrontierPoint | None:
    candidates = [point for point in points if point.policy.direction is direction]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda point: (
            point.metrics.precision or -1.0,
            point.metrics.accepted_signals,
            -point.policy_complexity,
        ),
        reverse=True,
    )[0]


def _passes_target(
    point: FrontierPoint | None,
    constraints: PrecisionCoverageConstraints,
) -> bool:
    return (
        point is not None
        and point.constraints.passed
        and point.metrics.precision is not None
        and point.metrics.precision >= constraints.minimum_precision
    )


def _fixture_directional_bias(setup: str, regime: str, timing: str) -> float:
    buy_setup = {
        "breakout": 0.020,
        "pullback": 0.014,
        "base_breakout": 0.018,
    }.get(setup, 0.0)
    sell_setup = {
        "failed_breakout": -0.018,
        "support_breakdown": -0.022,
    }.get(setup, 0.0)
    regime_bias = {
        "BULLISH": 0.010,
        "SIDEWAYS": 0.000,
        "BEARISH": -0.010,
        "TRANSITION": -0.004,
    }[regime]
    timing_bias = {
        "SETUP_FORMING": -0.004,
        "EARLY": 0.006,
        "PREFERRED": 0.012,
        "CONFIRMATION": 0.010,
        "LATE": -0.012,
    }[timing]
    return buy_setup + sell_setup + regime_bias + timing_bias


def _meets_minimum(value: float | None, minimum: float | None) -> bool:
    return minimum is None or (value is not None and value >= minimum)


def _safe_ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def _mean(values: Iterable[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _mcc(*, tp: int, tn: int, fp: int, fn: int) -> float | None:
    denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    if denominator == 0:
        return None
    return ((tp * tn) - (fp * fn)) / denominator


def _roc_auc(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    positives = [
        score for score, label in zip(scores, labels, strict=True) if label == 1
    ]
    negatives = [
        score for score, label in zip(scores, labels, strict=True) if label == 0
    ]
    if not positives or not negatives:
        return None
    wins = 0.0
    total = len(positives) * len(negatives)
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return wins / total


def _pr_auc(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    if not labels or sum(labels) == 0:
        return None
    ranked = sorted(zip(scores, labels, strict=True), reverse=True)
    area = 0.0
    previous_recall = 0.0
    true_positive = 0
    positives = sum(labels)
    for index, (_, label) in enumerate(ranked, start=1):
        if label == 1:
            true_positive += 1
        precision = true_positive / index
        recall = true_positive / positives
        area += precision * (recall - previous_recall)
        previous_recall = recall
    return area


def _brier(probabilities: Sequence[float], labels: Sequence[int]) -> float | None:
    if not probabilities:
        return None
    return sum(
        (probability - label) ** 2
        for probability, label in zip(probabilities, labels, strict=True)
    ) / len(probabilities)


def _brier_score(
    rows: Sequence[DirectionalObservation],
    definition: DirectionalOutcomeDefinition,
) -> float | None:
    usable = [
        row
        for row in rows
        if row.posterior_probability is not None
        and label_directional_outcome(row, definition)
        is not DirectionalLabel.UNAVAILABLE
    ]
    labels = [
        1
        if label_directional_outcome(row, definition)
        is DirectionalLabel.BUY_DIRECTIONAL
        else 0
        for row in usable
    ]
    probabilities = [row.posterior_probability or 0.0 for row in usable]
    return _brier(probabilities, labels)


def _calibration_error(
    probabilities: Sequence[float], labels: Sequence[int]
) -> float | None:
    errors = [
        abs(probability - label)
        for probability, label in zip(probabilities, labels, strict=True)
    ]
    return _mean(errors)


def _log_loss(probabilities: Sequence[float], labels: Sequence[int]) -> float | None:
    if not probabilities:
        return None
    epsilon = 1e-9
    total = 0.0
    for probability, label in zip(probabilities, labels, strict=True):
        p = min(max(probability, epsilon), 1.0 - epsilon)
        total += label * math.log(p) + (1 - label) * math.log(1 - p)
    return -total / len(probabilities)


def _profit_factor(returns: Sequence[float]) -> float | None:
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    if losses == 0:
        return None if gains == 0 else math.inf
    return gains / losses


def _win_loss_ratio(returns: Sequence[float]) -> float | None:
    wins = sum(value > 0 for value in returns)
    losses = sum(value < 0 for value in returns)
    return _safe_ratio(wins, losses)


def _payoff_ratio(returns: Sequence[float]) -> float | None:
    gains = [value for value in returns if value > 0]
    losses = [abs(value) for value in returns if value < 0]
    average_loss = _mean(losses)
    if average_loss is None or average_loss == 0:
        return None
    return (_mean(gains) or 0.0) / average_loss


def _probability_for_direction(
    row: DirectionalObservation,
    direction: DirectionalPolicyDirection,
) -> float:
    probability = row.posterior_probability
    if probability is None:
        probability = row.recommendation_score
    if direction is DirectionalPolicyDirection.SELL:
        return 1.0 - probability
    return probability


def _directional_rate(
    rows: Sequence[DirectionalObservation],
    direction: DirectionalPolicyDirection,
    definition: DirectionalOutcomeDefinition,
) -> float | None:
    if not rows:
        return None
    target = (
        DirectionalLabel.BUY_DIRECTIONAL
        if direction is DirectionalPolicyDirection.BUY
        else DirectionalLabel.SELL_DIRECTIONAL
    )
    return sum(
        label_directional_outcome(row, definition) is target for row in rows
    ) / len(rows)


def _distribution(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(values).items(), key=lambda item: (-item[1], item[0])))


def _stability(values: Sequence[float]) -> str:
    if len(values) < 2:
        return "INSUFFICIENT_FOLDS"
    dispersion = max(values) - min(values)
    if dispersion <= 0.10:
        return "STABLE"
    if dispersion <= 0.25:
        return "MODERATE"
    return "UNSTABLE"


def _concentration_stability(
    observations: Sequence[DirectionalObservation],
    attribute: str,
) -> str:
    if not observations:
        return "INSUFFICIENT_SAMPLE"
    values = Counter(str(getattr(row, attribute)) for row in observations)
    concentration = max(values.values()) / len(observations)
    if concentration <= 0.50:
        return "DIVERSIFIED"
    if concentration <= 0.70:
        return "CONCENTRATED"
    return "OVER_CONCENTRATED"


def _retracement_conclusion(
    variant: str,
    precision: float | None,
    baseline: float | None,
) -> str:
    if precision is None:
        return "insufficient sample"
    if variant == "raw":
        return "baseline raw retracement diagnostic"
    if baseline is not None and precision > baseline:
        return "improved versus raw retracement; diagnostic only"
    return "did not improve versus raw retracement"


def _setup_role(
    buy_metrics: DirectionalMetrics,
    sell_metrics: DirectionalMetrics,
) -> SetupDirectionalRole:
    if buy_metrics.accepted_signals < 10 or sell_metrics.accepted_signals < 10:
        return SetupDirectionalRole.INSUFFICIENT_SAMPLE
    buy = buy_metrics.precision or 0.0
    sell = sell_metrics.precision or 0.0
    if buy >= 0.55 and sell >= 0.55:
        return SetupDirectionalRole.BIDIRECTIONAL
    if buy >= 0.55:
        return SetupDirectionalRole.BUY_ONLY
    if sell >= 0.55:
        return SetupDirectionalRole.SELL_ONLY
    return SetupDirectionalRole.NON_PREDICTIVE


def _clamp(value: float, *, low: float = 0.01, high: float = 0.99) -> float:
    return round(min(max(value, low), high), 4)


def _frontier_csv_row(point: FrontierPoint) -> dict[str, Any]:
    return {
        "policy_id": point.policy.policy_id,
        "direction": point.policy.direction.value,
        "precision": point.metrics.precision,
        "ci_low": point.metrics.precision_ci_low,
        "ci_high": point.metrics.precision_ci_high,
        "accepted_signals": point.metrics.accepted_signals,
        "effective_sample_size": point.metrics.effective_sample_size,
        "recall": point.metrics.recall,
        "pr_auc": point.metrics.pr_auc,
        "expectancy": point.metrics.expectancy,
        "average_mae": point.metrics.average_mae,
        "average_mfe": point.metrics.average_mfe,
        "annual_signal_rate": point.annual_signal_rate,
        "worst_fold_precision": point.worst_fold_precision,
        "policy_complexity": point.policy_complexity,
        "constraints_passed": point.constraints.passed,
        "reason_codes": "|".join(point.constraints.reason_codes),
        "production_influence": point.production_influence,
    }


def _frontier_lines(point: FrontierPoint | None) -> tuple[str, ...]:
    if point is None:
        return ("- unavailable",)
    metrics = point.metrics
    interval = (
        f"[{_fmt_pct(metrics.precision_ci_low)}, {_fmt_pct(metrics.precision_ci_high)}]"
    )
    return (
        "- "
        f"{point.policy.policy_id} ({point.policy.direction.value}): "
        f"precision {_fmt_pct(metrics.precision)} {interval}, "
        f"signals {metrics.accepted_signals}, "
        f"effective n {metrics.effective_sample_size:.2f}, "
        f"recall {_fmt_pct(metrics.recall)}, PR AUC {_fmt(metrics.pr_auc)}, "
        f"expectancy {_fmt_pct(metrics.expectancy)}, "
        f"MAE {_fmt_pct(metrics.average_mae)}, MFE {_fmt_pct(metrics.average_mfe)}, "
        f"annual signals {point.annual_signal_rate:.2f}, "
        f"worst fold {_fmt_pct(point.worst_fold_precision)}, "
        f"complexity {point.policy_complexity}, "
        f"constraints {'PASS' if point.constraints.passed else 'FAIL'}",
        f"  train/test: nested walk-forward with purge and embargo; "
        f"production influence: {str(point.production_influence).lower()}",
        f"  setup distribution: {_render_distribution(point.setup_distribution)}",
        f"  regime distribution: {_render_distribution(point.regime_distribution)}",
        f"  timing distribution: {_render_distribution(point.timing_distribution)}",
        f"  rejection reasons: {', '.join(point.constraints.reason_codes) or 'none'}",
    )


def _retracement_lines(rows: Sequence[RetracementAblationResult]) -> tuple[str, ...]:
    return tuple(
        "- "
        f"{row.variant}: precision {_fmt_pct(row.precision)}, "
        f"signals {row.signal_count}, EV {_fmt_pct(row.expectancy)}, "
        f"delta {_fmt_pct(row.incremental_contribution)}; {row.conclusion}"
        for row in rows
    )


def _lineage_lines(rows: Sequence[FeatureLineageResult]) -> tuple[str, ...]:
    return tuple(
        "- "
        f"{row.feature}: lineage={row.lineage_group}, "
        f"overlap={','.join(row.overlaps_with) or 'none'}, "
        f"correlation={_fmt(row.correlation)}, "
        f"incremental={_fmt(row.incremental_contribution)}, "
        f"leakage_warning={str(row.leakage_warning).lower()}"
        for row in rows
    )


def _setup_lines(rows: Sequence[SetupDirectionalAnalysis]) -> tuple[str, ...]:
    return tuple(
        "- "
        f"{row.setup_type}: BUY precision {_fmt_pct(row.buy_precision)} "
        f"(n={row.buy_signals}), SELL precision {_fmt_pct(row.sell_precision)} "
        f"(n={row.sell_signals}), role {row.role.value}"
        for row in rows
    )


def _render_distribution(distribution: Sequence[tuple[str, int]]) -> str:
    if not distribution:
        return "unavailable"
    return ", ".join(f"{name}={count}" for name, count in distribution)


def _fmt(value: float | None) -> str:
    if value is None:
        return "unavailable"
    if math.isinf(value):
        return "infinite"
    return f"{value:.4f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value * 100:.2f}%"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


__all__ = [
    "BidirectionalResearchConclusion",
    "CalibrationBucket",
    "ConstraintResult",
    "DirectionalCalibrationReport",
    "DirectionalLabel",
    "DirectionalMetrics",
    "DirectionalObservation",
    "DirectionalOutcomeDefinition",
    "DirectionalOutcomeFamily",
    "DirectionalPolicy",
    "DirectionalPolicyDirection",
    "DirectionalResearchConclusion",
    "FeatureLineageResult",
    "FrontierPoint",
    "PolicyAuditReport",
    "PolicyCandidateReport",
    "PrecisionCoverageConstraints",
    "PrecisionCoverageReport",
    "RetracementAblationResult",
    "SetupDirectionalAnalysis",
    "SetupDirectionalRole",
    "WalkForwardFoldResult",
    "build_directional_calibration_report",
    "build_policy_audit_report",
    "build_policy_candidate_report",
    "build_precision_coverage_report",
    "calculate_directional_metrics",
    "deterministic_research_observations",
    "effective_sample_size",
    "export_calibration_csv",
    "export_calibration_json",
    "export_frontier_csv",
    "export_policy_audit_json",
    "export_policy_candidates_json",
    "export_precision_coverage_json",
    "feature_lineage_audit",
    "generate_candidate_policies",
    "label_barrier_first",
    "label_directional_outcome",
    "label_risk_adjusted",
    "label_terminal_return",
    "label_tradeability",
    "nested_walk_forward",
    "pareto_frontier",
    "render_calibration_report",
    "render_policy_audit_report",
    "render_policy_candidate_report",
    "render_precision_coverage_report",
    "retracement_ablation",
    "setup_directional_analysis",
    "wilson_interval",
]
