from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from statistics import median
from typing import Any

from alpha.historical_replay.buy_signal_reconstruction import (
    BuyFeatureGroup,
)
from alpha.historical_replay.buy_signal_reconstruction import (
    _feature_value as _buy_feature_value,
)
from alpha.historical_replay.buy_signal_reconstruction import (
    _regime_value as _buy_regime_value,
)
from alpha.historical_replay.buy_signal_reconstruction import (
    _timing_value as _buy_timing_value,
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


class OpportunitySide(StrEnum):
    BUY = "BUY"


class OpportunityLifecycleState(StrEnum):
    DETECTED = "DETECTED"
    FORMING = "FORMING"
    IMPROVING = "IMPROVING"
    TRADEABLE_EARLY = "TRADEABLE_EARLY"
    TRADEABLE_PREFERRED = "TRADEABLE_PREFERRED"
    CONFIRMED = "CONFIRMED"
    EXTENDED = "EXTENDED"
    DISTRIBUTING = "DISTRIBUTING"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"
    UNAVAILABLE = "UNAVAILABLE"


class TransitionDriver(StrEnum):
    DIRECTIONAL_EVIDENCE_IMPROVED = "DIRECTIONAL_EVIDENCE_IMPROVED"
    TRADEABILITY_IMPROVED = "TRADEABILITY_IMPROVED"
    RISK_CONTRACTED = "RISK_CONTRACTED"
    CONFIRMATION_ARRIVED = "CONFIRMATION_ARRIVED"
    REGIME_IMPROVED = "REGIME_IMPROVED"
    SETUP_MATURED = "SETUP_MATURED"
    LIQUIDITY_IMPROVED = "LIQUIDITY_IMPROVED"
    NO_MEANINGFUL_IMPROVEMENT = "NO_MEANINGFUL_IMPROVEMENT"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"


class MaturationFeatureGroup(StrEnum):
    PRICE_STRUCTURE_EVOLUTION = "PRICE_STRUCTURE_EVOLUTION"
    VOLUME_EVOLUTION = "VOLUME_EVOLUTION"
    VOLATILITY_EVOLUTION = "VOLATILITY_EVOLUTION"
    RELATIVE_STRENGTH_EVOLUTION = "RELATIVE_STRENGTH_EVOLUTION"
    SETUP_EVOLUTION = "SETUP_EVOLUTION"
    TIMING_EVOLUTION = "TIMING_EVOLUTION"
    REGIME_EVOLUTION = "REGIME_EVOLUTION"
    TRADE_PLAN_EVOLUTION = "TRADE_PLAN_EVOLUTION"
    DATA_QUALITY_EVOLUTION = "DATA_QUALITY_EVOLUTION"


class EntryMarker(StrEnum):
    HINDSIGHT_BEST_ENTRY_DIAGNOSTIC_ONLY = "HINDSIGHT_BEST_ENTRY_DIAGNOSTIC_ONLY"
    EARLIEST_VALID_ENTRY = "EARLIEST_VALID_ENTRY"
    BEST_RULE_BASED_ENTRY = "BEST_RULE_BASED_ENTRY"
    FIRST_CONFIRMATION_ENTRY = "FIRST_CONFIRMATION_ENTRY"
    CURRENT_POLICY_ENTRY = "CURRENT_POLICY_ENTRY"


class TriggerRuleName(StrEnum):
    DETECTED_IMMEDIATE = "DETECTED_IMMEDIATE"
    CURRENT_PRODUCTION_ENTRY = "CURRENT_PRODUCTION_ENTRY"
    FIRST_EARLY_STATE = "FIRST_EARLY_STATE"
    FIRST_AGGRESSIVE_STATE = "FIRST_AGGRESSIVE_STATE"
    FIRST_PREFERRED_STATE = "FIRST_PREFERRED_STATE"
    FIRST_CONFIRMATION_STATE = "FIRST_CONFIRMATION_STATE"
    BEST_TIMING_THRESHOLD = "BEST_TIMING_THRESHOLD"
    FULL_STACK_SCORE_ONLY = "FULL_STACK_SCORE_ONLY"
    FULL_STACK_PLUS_TIMING = "FULL_STACK_PLUS_TIMING"
    NO_TRIGGER_REJECTED = "NO_TRIGGER_REJECTED"
    PRICE_CONFIRMATION_TRIGGER = "PRICE_CONFIRMATION_TRIGGER"
    VOLUME_CONFIRMATION_TRIGGER = "VOLUME_CONFIRMATION_TRIGGER"
    RISK_CONTRACTION_TRIGGER = "RISK_CONTRACTION_TRIGGER"
    RETEST_HOLD_TRIGGER = "RETEST_HOLD_TRIGGER"
    MULTI_FACTOR_MATURATION_TRIGGER = "MULTI_FACTOR_MATURATION_TRIGGER"
    TRAJECTORY_IMPROVEMENT_TRIGGER = "TRAJECTORY_IMPROVEMENT_TRIGGER"
    PERSISTENCE_TRIGGER = "PERSISTENCE_TRIGGER"


class OpportunityClassification(StrEnum):
    VALID_OPPORTUNITY_VALID_TRIGGER = "VALID_OPPORTUNITY_VALID_TRIGGER"
    VALID_OPPORTUNITY_EARLY_TRIGGER = "VALID_OPPORTUNITY_EARLY_TRIGGER"
    VALID_OPPORTUNITY_LATE_TRIGGER = "VALID_OPPORTUNITY_LATE_TRIGGER"
    VALID_OPPORTUNITY_NO_TRIGGER = "VALID_OPPORTUNITY_NO_TRIGGER"
    INVALID_OPPORTUNITY_TRIGGERED = "INVALID_OPPORTUNITY_TRIGGERED"
    INVALID_OPPORTUNITY_REJECTED = "INVALID_OPPORTUNITY_REJECTED"
    AMBIGUOUS_OPPORTUNITY = "AMBIGUOUS_OPPORTUNITY"
    UNAVAILABLE_OUTCOME = "UNAVAILABLE_OUTCOME"


class TimingBottleneck(StrEnum):
    TRIGGER_FIRES_TOO_EARLY = "TRIGGER_FIRES_TOO_EARLY"
    TRIGGER_FIRES_TOO_LATE = "TRIGGER_FIRES_TOO_LATE"
    TRIGGER_TOO_SPARSE = "TRIGGER_TOO_SPARSE"
    TRIGGER_TOO_PERMISSIVE = "TRIGGER_TOO_PERMISSIVE"
    SETUP_MATURATION_NOT_MODELLED = "SETUP_MATURATION_NOT_MODELLED"
    RISK_CONTRACTION_NOT_MODELLED = "RISK_CONTRACTION_NOT_MODELLED"
    CONFIRMATION_NOT_MODELLED = "CONFIRMATION_NOT_MODELLED"
    OPPORTUNITY_GROUPING_INSUFFICIENT = "OPPORTUNITY_GROUPING_INSUFFICIENT"
    STOP_DESIGN_PRIMARY = "STOP_DESIGN_PRIMARY"
    MULTIPLE_TIMING_BOTTLENECKS = "MULTIPLE_TIMING_BOTTLENECKS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class OpportunityEvolutionConclusion(StrEnum):
    STABLE_70_PERCENT_TRIGGER_FOUND = "STABLE_70_PERCENT_TRIGGER_FOUND"
    STABLE_60_PERCENT_TRIGGER_FOUND = "STABLE_60_PERCENT_TRIGGER_FOUND"
    TIMING_IMPROVEMENT_FOUND = "TIMING_IMPROVEMENT_FOUND"
    HIGH_PRECISION_LOW_COVERAGE_TRIGGER_FOUND = (
        "HIGH_PRECISION_LOW_COVERAGE_TRIGGER_FOUND"
    )
    CURRENT_TIMING_REMAINS_SUPERIOR = "CURRENT_TIMING_REMAINS_SUPERIOR"
    ENTRY_TIMING_NOT_ROOT_CAUSE = "ENTRY_TIMING_NOT_ROOT_CAUSE"
    MORE_DATA_REQUIRED = "MORE_DATA_REQUIRED"


class EarlyEntryFailureCause(StrEnum):
    SETUP_INCOMPLETE = "SETUP_INCOMPLETE"
    RESISTANCE_NOT_CLEARED = "RESISTANCE_NOT_CLEARED"
    WEAK_BREAKOUT_VOLUME = "WEAK_BREAKOUT_VOLUME"
    SUPPORT_NOT_ESTABLISHED = "SUPPORT_NOT_ESTABLISHED"
    VOLATILITY_STILL_EXPANDING = "VOLATILITY_STILL_EXPANDING"
    STOP_TOO_WIDE = "STOP_TOO_WIDE"
    REWARD_RISK_INSUFFICIENT = "REWARD_RISK_INSUFFICIENT"
    HOSTILE_MARKET_REGIME = "HOSTILE_MARKET_REGIME"
    WEAK_SECTOR_STATE = "WEAK_SECTOR_STATE"
    RELATIVE_STRENGTH_NOT_CONFIRMED = "RELATIVE_STRENGTH_NOT_CONFIRMED"
    REPEATED_FAILED_BREAKOUT = "REPEATED_FAILED_BREAKOUT"
    EXTENDED_FROM_SUPPORT_DESPITE_EARLY_LABEL = (
        "EXTENDED_FROM_SUPPORT_DESPITE_EARLY_LABEL"
    )
    GAP_INSTABILITY = "GAP_INSTABILITY"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    SIGNAL_SCORE_DECAY = "SIGNAL_SCORE_DECAY"
    SETUP_DETERIORATION = "SETUP_DETERIORATION"
    LABEL_AMBIGUITY = "LABEL_AMBIGUITY"
    UNAVOIDABLE_MARKET_NOISE = "UNAVOIDABLE_MARKET_NOISE"


class EarlyEntryFailureClass(StrEnum):
    WAITING_WOULD_HAVE_HELPED = "WAITING_WOULD_HAVE_HELPED"
    WAITING_WOULD_NOT_HAVE_HELPED = "WAITING_WOULD_NOT_HAVE_HELPED"
    OPPORTUNITY_WAS_NEVER_VALID = "OPPORTUNITY_WAS_NEVER_VALID"
    STOP_DESIGN_PRIMARY = "STOP_DESIGN_PRIMARY"
    LABEL_AMBIGUITY = "LABEL_AMBIGUITY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ConfirmationDelayCause(StrEnum):
    ENTERED_AFTER_MOST_UPSIDE = "ENTERED_AFTER_MOST_UPSIDE"
    REWARD_RISK_COLLAPSED = "REWARD_RISK_COLLAPSED"
    STOP_DISTANCE_WIDENED = "STOP_DISTANCE_WIDENED"
    TARGET_TOO_CLOSE = "TARGET_TOO_CLOSE"
    EXTENDED_FROM_SUPPORT = "EXTENDED_FROM_SUPPORT"
    VOLUME_CLIMAX = "VOLUME_CLIMAX"
    REGIME_DETERIORATION = "REGIME_DETERIORATION"
    SETUP_AGE_EXCESSIVE = "SETUP_AGE_EXCESSIVE"
    BREAKOUT_ALREADY_EXHAUSTED = "BREAKOUT_ALREADY_EXHAUSTED"
    NO_MEANINGFUL_DELAY_COST = "NO_MEANINGFUL_DELAY_COST"


@dataclass(frozen=True, slots=True)
class OpportunityIdentity:
    opportunity_id: str
    symbol: str
    setup_family: str
    side: OpportunitySide
    first_detection_date: date
    start_boundary: date
    end_boundary: date
    reset_index: int
    reset_reason: str
    regime_context: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["side"] = self.side.value
        for key in ("first_detection_date", "start_boundary", "end_boundary"):
            payload[key] = payload[key].isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class MaturationFeatureSnapshot:
    group: MaturationFeatureGroup
    current_level: float | None
    one_observation_delta: float | None
    multi_observation_slope: float | None
    rolling_minimum: float | None
    rolling_maximum: float | None
    change_since_detection: float | None
    acceleration: float | None
    persistence_count: int
    reversal_flag: bool
    lineage: tuple[str, ...]
    point_in_time: bool = True

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["group"] = self.group.value
        return payload


@dataclass(frozen=True, slots=True)
class OpportunityObservation:
    opportunity_id: str
    observed_at: date
    symbol: str
    lifecycle_state: OpportunityLifecycleState
    opportunity_quality_score: float
    entry_trigger_score: float
    directional_score: float
    tradeability_score: float
    price: float | None
    support: float | None
    resistance: float | None
    stop_candidate: float | None
    target_candidate: float | None
    volume_condition: str
    data_quality_status: str
    setup: str
    regime: str
    timing_state: str
    source_features: tuple[MaturationFeatureSnapshot, ...]
    underlying: DirectionalObservation
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "observed_at": self.observed_at.isoformat(),
            "symbol": self.symbol,
            "lifecycle_state": self.lifecycle_state.value,
            "opportunity_quality_score": self.opportunity_quality_score,
            "entry_trigger_score": self.entry_trigger_score,
            "directional_score": self.directional_score,
            "tradeability_score": self.tradeability_score,
            "price": self.price,
            "support": self.support,
            "resistance": self.resistance,
            "stop_candidate": self.stop_candidate,
            "target_candidate": self.target_candidate,
            "volume_condition": self.volume_condition,
            "data_quality_status": self.data_quality_status,
            "setup": self.setup,
            "regime": self.regime,
            "timing_state": self.timing_state,
            "source_features": [item.as_dict() for item in self.source_features],
            "production_influence": self.production_influence,
        }


@dataclass(frozen=True, slots=True)
class StateTransition:
    opportunity_id: str
    symbol: str
    previous_state: OpportunityLifecycleState
    new_state: OpportunityLifecycleState
    transition_timestamp: date
    transition_reason: str
    driver: TransitionDriver
    source_features: tuple[str, ...]
    setup: str
    regime: str
    timing_state: str
    directional_score: float
    tradeability_score: float
    price: float | None
    support: float | None
    resistance: float | None
    stop_candidate: float | None
    target_candidate: float | None
    volume_condition: str
    data_quality_status: str
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["previous_state"] = self.previous_state.value
        payload["new_state"] = self.new_state.value
        payload["driver"] = self.driver.value
        payload["transition_timestamp"] = self.transition_timestamp.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class EntryQualityOutcome:
    opportunity_id: str
    observed_at: date
    marker: EntryMarker
    entry_price: float | None
    stop: float | None
    target: float | None
    risk_distance: float | None
    reward_risk: float | None
    barrier_first_success: bool | None
    terminal_return: float | None
    mfe: float | None
    mae: float | None
    realized_r_multiple: float | None
    stop_hit: bool | None
    target_hit: bool | None
    time_to_target: int | None
    time_to_stop: int | None
    gap_through_stop_risk: bool
    max_drawdown: float | None
    outcome_available: bool
    diagnostic_only: bool

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_at"] = self.observed_at.isoformat()
        payload["marker"] = self.marker.value
        return payload


@dataclass(frozen=True, slots=True)
class OpportunityPath:
    identity: OpportunityIdentity
    observations: tuple[OpportunityObservation, ...]
    transitions: tuple[StateTransition, ...]
    entry_outcomes: tuple[EntryQualityOutcome, ...]
    classification: OpportunityClassification
    observation_count: int
    calendar_duration_days: int
    trading_day_duration: int
    first_tradeable_date: date | None
    preferred_entry_date: date | None
    confirmation_date: date | None
    invalidation_date: date | None
    expiry_date: date | None
    outcome_completion_date: date | None
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.as_dict(),
            "observations": [item.as_dict() for item in self.observations],
            "transitions": [item.as_dict() for item in self.transitions],
            "entry_outcomes": [item.as_dict() for item in self.entry_outcomes],
            "classification": self.classification.value,
            "observation_count": self.observation_count,
            "calendar_duration_days": self.calendar_duration_days,
            "trading_day_duration": self.trading_day_duration,
            "first_tradeable_date": _date(self.first_tradeable_date),
            "preferred_entry_date": _date(self.preferred_entry_date),
            "confirmation_date": _date(self.confirmation_date),
            "invalidation_date": _date(self.invalidation_date),
            "expiry_date": _date(self.expiry_date),
            "outcome_completion_date": _date(self.outcome_completion_date),
            "production_influence": self.production_influence,
        }


@dataclass(frozen=True, slots=True)
class TriggerPolicy:
    name: TriggerRuleName
    description: str
    complexity: int
    retained_features: tuple[MaturationFeatureGroup, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["name"] = self.name.value
        payload["retained_features"] = [item.value for item in self.retained_features]
        return payload


@dataclass(frozen=True, slots=True)
class TriggerEvaluation:
    policy: TriggerPolicy
    unique_opportunities: int
    triggered_opportunities: int
    completed_opportunities: int
    precision: float | None
    recall: float | None
    confidence_interval: tuple[float | None, float | None]
    opportunity_conversion_rate: float | None
    annual_unique_signals: float
    effective_sample_size: float
    expectancy: float | None
    cost_adjusted_expectancy: float | None
    mae: float | None
    mfe: float | None
    average_trigger_delay: float | None
    median_trigger_delay: float | None
    missed_move_percentage: float | None
    stop_hit_rate: float | None
    target_hit_rate: float | None
    holding_period: float | None
    worst_fold_precision: float | None
    setup_concentration: float
    regime_concentration: float
    year_concentration: float
    observation_level_precision: float | None
    opportunity_level_precision: float | None
    signal_inflation_factor: float
    tier: str
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["policy"] = self.policy.as_dict()
        payload["confidence_interval"] = list(self.confidence_interval)
        return payload


@dataclass(frozen=True, slots=True)
class EarlyEntryFailureRow:
    cause: EarlyEntryFailureCause
    classification: EarlyEntryFailureClass
    count: int
    average_return: float | None
    average_mae: float | None
    dominant_setup: str
    dominant_regime: str
    dominant_timing: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cause"] = self.cause.value
        payload["classification"] = self.classification.value
        return payload


@dataclass(frozen=True, slots=True)
class ConfirmationDelayRow:
    cause: ConfirmationDelayCause
    count: int
    return_missed_before_confirmation: float | None
    remaining_upside: float | None
    precision_gain_from_waiting: float | None
    expectancy_change: float | None
    mae_change: float | None
    reward_risk_change: float | None
    holding_period_change: float | None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cause"] = self.cause.value
        return payload


@dataclass(frozen=True, slots=True)
class OpportunityEvolutionReport:
    generated_on: date
    replay_date_range: tuple[date | None, date | None]
    raw_observations: int
    unique_opportunities: int
    completed_opportunities: int
    valid_opportunities: int
    invalid_opportunities: int
    average_observations_per_opportunity: float
    current_policy: TriggerEvaluation
    best_rule: TriggerEvaluation
    trigger_frontier: tuple[TriggerEvaluation, ...]
    pareto_frontier: tuple[TriggerEvaluation, ...]
    paths: tuple[OpportunityPath, ...]
    early_entry_failures: tuple[EarlyEntryFailureRow, ...]
    confirmation_delay: tuple[ConfirmationDelayRow, ...]
    transition_attribution: tuple[StateTransition, ...]
    opportunity_grouping_method: str
    primary_timing_bottleneck: TimingBottleneck
    final_conclusion: OpportunityEvolutionConclusion
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        start, end = self.replay_date_range
        return {
            "generated_on": self.generated_on.isoformat(),
            "replay_date_range": [_date(start), _date(end)],
            "raw_observations": self.raw_observations,
            "unique_opportunities": self.unique_opportunities,
            "completed_opportunities": self.completed_opportunities,
            "valid_opportunities": self.valid_opportunities,
            "invalid_opportunities": self.invalid_opportunities,
            "average_observations_per_opportunity": (
                self.average_observations_per_opportunity
            ),
            "current_policy": self.current_policy.as_dict(),
            "best_rule": self.best_rule.as_dict(),
            "trigger_frontier": [item.as_dict() for item in self.trigger_frontier],
            "pareto_frontier": [item.as_dict() for item in self.pareto_frontier],
            "paths": [item.as_dict() for item in self.paths],
            "early_entry_failures": [
                item.as_dict() for item in self.early_entry_failures
            ],
            "confirmation_delay": [item.as_dict() for item in self.confirmation_delay],
            "transition_attribution": [
                item.as_dict() for item in self.transition_attribution
            ],
            "opportunity_grouping_method": self.opportunity_grouping_method,
            "primary_timing_bottleneck": self.primary_timing_bottleneck.value,
            "final_conclusion": self.final_conclusion.value,
            "production_influence": self.production_influence,
        }


def build_opportunity_evolution_report(
    observations: Sequence[DirectionalObservation] | None = None,
    *,
    definition: DirectionalOutcomeDefinition | None = None,
    symbol: str | None = None,
    opportunity_id: str | None = None,
    trigger: str | None = None,
) -> OpportunityEvolutionReport:
    rows = tuple(observations or deterministic_research_observations())
    if symbol is not None:
        rows = tuple(row for row in rows if row.symbol == symbol.strip().upper())
    outcome_definition = definition or DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.TERMINAL_RETURN,
        horizon_days=20,
        positive_return_threshold=0.02,
        negative_return_threshold=-0.02,
    )
    paths = reconstruct_opportunity_paths(rows, definition=outcome_definition)
    if opportunity_id is not None:
        paths = tuple(
            path for path in paths if path.identity.opportunity_id == opportunity_id
        )
    policies = trigger_policies()
    if trigger is not None:
        normalized = trigger.strip().upper().replace("-", "_")
        policies = tuple(
            policy for policy in policies if policy.name.value == normalized
        )
    evaluations = tuple(
        evaluate_trigger_policy(paths, policy, definition=outcome_definition)
        for policy in policies
    )
    if not evaluations:
        evaluations = (
            evaluate_trigger_policy(
                paths,
                TriggerPolicy(
                    name=TriggerRuleName.NO_TRIGGER_REJECTED,
                    description="No trigger matched the filter.",
                    complexity=1,
                    retained_features=(),
                ),
                definition=outcome_definition,
            ),
        )
    pareto = pareto_trigger_frontier(evaluations)
    current = (
        _evaluation_by_name(evaluations, TriggerRuleName.CURRENT_PRODUCTION_ENTRY)
        or evaluations[0]
    )
    best = _best_trigger(pareto) or current
    all_dates = [row.observed_at for row in rows]
    return OpportunityEvolutionReport(
        generated_on=date.today(),
        replay_date_range=(
            min(all_dates) if all_dates else None,
            max(all_dates) if all_dates else None,
        ),
        raw_observations=len(rows),
        unique_opportunities=len(paths),
        completed_opportunities=sum(_path_has_outcome(path) for path in paths),
        valid_opportunities=sum(
            _path_is_valid(path, outcome_definition) for path in paths
        ),
        invalid_opportunities=sum(
            _path_is_invalid(path, outcome_definition) for path in paths
        ),
        average_observations_per_opportunity=_safe_ratio(
            sum(path.observation_count for path in paths), len(paths)
        )
        or 0.0,
        current_policy=current,
        best_rule=best,
        trigger_frontier=evaluations,
        pareto_frontier=pareto,
        paths=paths,
        early_entry_failures=early_entry_failure_taxonomy(paths, current),
        confirmation_delay=confirmation_delay_audit(paths, current, best),
        transition_attribution=tuple(
            transition for path in paths for transition in path.transitions
        ),
        opportunity_grouping_method=(
            "symbol + setup family + BUY side with reset on invalidation, "
            "setup change, regime discontinuity, or time gap"
        ),
        primary_timing_bottleneck=_timing_bottleneck(current, best, paths),
        final_conclusion=_final_conclusion(current, best),
        production_influence=False,
    )


def reconstruct_opportunity_paths(
    observations: Sequence[DirectionalObservation],
    *,
    definition: DirectionalOutcomeDefinition,
    reset_gap_days: int = 45,
) -> tuple[OpportunityPath, ...]:
    grouped: list[list[DirectionalObservation]] = []
    current: list[DirectionalObservation] = []
    reset_index = 0
    previous: DirectionalObservation | None = None
    for row in sorted(observations, key=lambda item: (item.symbol, item.observed_at)):
        if previous is None or _requires_reset(previous, row, reset_gap_days):
            if current:
                grouped.append(current)
            current = [row]
            reset_index += 1
        else:
            current.append(row)
        previous = row
    if current:
        grouped.append(current)
    paths = [
        _path_from_rows(rows, definition=definition, reset_index=index)
        for index, rows in enumerate(grouped, start=1)
    ]
    return tuple(sorted(paths, key=lambda item: item.identity.opportunity_id))


def evaluate_trigger_policy(
    paths: Sequence[OpportunityPath],
    policy: TriggerPolicy,
    *,
    definition: DirectionalOutcomeDefinition,
) -> TriggerEvaluation:
    triggered: list[tuple[OpportunityPath, OpportunityObservation]] = []
    for path in paths:
        observation = _first_trigger(path, policy)
        if observation is not None:
            triggered.append((path, observation))
    successes = sum(
        label_directional_outcome(item.underlying, definition)
        is DirectionalLabel.BUY_DIRECTIONAL
        for _, item in triggered
    )
    completed = sum(_path_has_outcome(path) for path in paths)
    valid = sum(_path_is_valid(path, definition) for path in paths)
    returns = [
        observation.underlying.forward_return
        for _, observation in triggered
        if observation.underlying.forward_return is not None
    ]
    maes = [
        observation.underlying.max_adverse_excursion
        for _, observation in triggered
        if observation.underlying.max_adverse_excursion is not None
    ]
    mfes = [
        observation.underlying.max_favorable_excursion
        for _, observation in triggered
        if observation.underlying.max_favorable_excursion is not None
    ]
    delays = [
        (observation.observed_at - path.identity.first_detection_date).days
        for path, observation in triggered
    ]
    missed = [_missed_move(path, observation) for path, observation in triggered]
    stop_hits = [_stop_hit(observation.underlying) for _, observation in triggered]
    target_hits = [_target_hit(observation.underlying) for _, observation in triggered]
    years = {path.identity.first_detection_date.year for path in paths}
    precision = _safe_ratio(successes, len(triggered))
    ci = wilson_interval(successes, len(triggered))
    observation_precision = _observation_level_precision(paths, policy, definition)
    return TriggerEvaluation(
        policy=policy,
        unique_opportunities=len(paths),
        triggered_opportunities=len(triggered),
        completed_opportunities=completed,
        precision=precision,
        recall=_safe_ratio(successes, valid),
        confidence_interval=ci,
        opportunity_conversion_rate=_safe_ratio(len(triggered), len(paths)),
        annual_unique_signals=len(triggered) / max(1, len(years)),
        effective_sample_size=effective_sample_size(
            tuple(item.underlying for _, item in triggered)
        ),
        expectancy=_mean(returns),
        cost_adjusted_expectancy=(
            None if not returns else (_mean(returns) or 0.0) - 0.0025
        ),
        mae=_mean(maes),
        mfe=_mean(mfes),
        average_trigger_delay=_mean(float(item) for item in delays),
        median_trigger_delay=None if not delays else float(median(delays)),
        missed_move_percentage=_mean(missed),
        stop_hit_rate=_safe_ratio(sum(stop_hits), len(stop_hits)),
        target_hit_rate=_safe_ratio(sum(target_hits), len(target_hits)),
        holding_period=float(definition.horizon_days) if triggered else None,
        worst_fold_precision=_worst_fold_precision(triggered, definition),
        setup_concentration=_trigger_concentration(triggered, "setup"),
        regime_concentration=_trigger_concentration(triggered, "regime"),
        year_concentration=_year_concentration(triggered),
        observation_level_precision=observation_precision,
        opportunity_level_precision=precision,
        signal_inflation_factor=_signal_inflation(paths, policy),
        tier=_tier(precision, len(triggered), returns),
        production_influence=False,
    )


def trigger_policies() -> tuple[TriggerPolicy, ...]:
    return (
        TriggerPolicy(
            TriggerRuleName.DETECTED_IMMEDIATE,
            "Trigger at first detection.",
            1,
            (MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,),
        ),
        TriggerPolicy(
            TriggerRuleName.CURRENT_PRODUCTION_ENTRY,
            "Trigger when current score reaches production-style threshold.",
            1,
            (MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,),
        ),
        TriggerPolicy(
            TriggerRuleName.FIRST_EARLY_STATE,
            "Trigger at first early/aggressive tradeable state.",
            2,
            (MaturationFeatureGroup.TIMING_EVOLUTION,),
        ),
        TriggerPolicy(
            TriggerRuleName.FIRST_AGGRESSIVE_STATE,
            "Trigger at first aggressive state.",
            2,
            (MaturationFeatureGroup.TIMING_EVOLUTION,),
        ),
        TriggerPolicy(
            TriggerRuleName.FIRST_PREFERRED_STATE,
            "Trigger at first preferred tradeable state.",
            2,
            (MaturationFeatureGroup.TIMING_EVOLUTION,),
        ),
        TriggerPolicy(
            TriggerRuleName.FIRST_CONFIRMATION_STATE,
            "Trigger at first confirmation state.",
            2,
            (MaturationFeatureGroup.TIMING_EVOLUTION,),
        ),
        TriggerPolicy(
            TriggerRuleName.BEST_TIMING_THRESHOLD,
            "Trigger when timing score reaches a selected threshold.",
            2,
            (MaturationFeatureGroup.TIMING_EVOLUTION,),
        ),
        TriggerPolicy(
            TriggerRuleName.FULL_STACK_SCORE_ONLY,
            "Trigger from full-stack opportunity quality only.",
            2,
            (MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,),
        ),
        TriggerPolicy(
            TriggerRuleName.FULL_STACK_PLUS_TIMING,
            "Trigger from full-stack quality plus timing state.",
            3,
            (
                MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,
                MaturationFeatureGroup.TIMING_EVOLUTION,
            ),
        ),
        TriggerPolicy(
            TriggerRuleName.NO_TRIGGER_REJECTED,
            "Reject all opportunities.",
            1,
            (),
        ),
        TriggerPolicy(
            TriggerRuleName.PRICE_CONFIRMATION_TRIGGER,
            "Price structure improving, resistance cleared, not extended.",
            3,
            (
                MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,
                MaturationFeatureGroup.SETUP_EVOLUTION,
            ),
        ),
        TriggerPolicy(
            TriggerRuleName.VOLUME_CONFIRMATION_TRIGGER,
            "Volume confirms maturation without distribution warning.",
            3,
            (
                MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,
                MaturationFeatureGroup.VOLUME_EVOLUTION,
            ),
        ),
        TriggerPolicy(
            TriggerRuleName.RISK_CONTRACTION_TRIGGER,
            "Risk distance contracts and reward/risk remains acceptable.",
            3,
            (
                MaturationFeatureGroup.VOLATILITY_EVOLUTION,
                MaturationFeatureGroup.TRADE_PLAN_EVOLUTION,
            ),
        ),
        TriggerPolicy(
            TriggerRuleName.RETEST_HOLD_TRIGGER,
            "Support/retest holds after setup maturation.",
            4,
            (
                MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,
                MaturationFeatureGroup.VOLUME_EVOLUTION,
                MaturationFeatureGroup.TRADE_PLAN_EVOLUTION,
            ),
        ),
        TriggerPolicy(
            TriggerRuleName.MULTI_FACTOR_MATURATION_TRIGGER,
            "Opportunity quality, timing, trade plan, and regime align.",
            5,
            (
                MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,
                MaturationFeatureGroup.TIMING_EVOLUTION,
                MaturationFeatureGroup.TRADE_PLAN_EVOLUTION,
                MaturationFeatureGroup.REGIME_EVOLUTION,
            ),
        ),
        TriggerPolicy(
            TriggerRuleName.TRAJECTORY_IMPROVEMENT_TRIGGER,
            "Opportunity quality and timing improve from detection.",
            4,
            (
                MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,
                MaturationFeatureGroup.TIMING_EVOLUTION,
            ),
        ),
        TriggerPolicy(
            TriggerRuleName.PERSISTENCE_TRIGGER,
            "Preferred or confirmed timing persists for two observations.",
            4,
            (MaturationFeatureGroup.TIMING_EVOLUTION,),
        ),
    )


def pareto_trigger_frontier(
    evaluations: Sequence[TriggerEvaluation],
) -> tuple[TriggerEvaluation, ...]:
    survivors: list[TriggerEvaluation] = []
    for candidate in evaluations:
        if not any(_dominates(other, candidate) for other in evaluations):
            survivors.append(candidate)
    return tuple(
        sorted(
            survivors,
            key=lambda item: (
                -(item.precision or 0.0),
                -item.triggered_opportunities,
                item.policy.complexity,
                item.policy.name.value,
            ),
        )
    )


def early_entry_failure_taxonomy(
    paths: Sequence[OpportunityPath],
    policy: TriggerEvaluation,
) -> tuple[EarlyEntryFailureRow, ...]:
    buckets: dict[EarlyEntryFailureCause, list[OpportunityObservation]] = {}
    policy_def = policy.policy
    for path in paths:
        observation = _first_trigger(path, policy_def)
        if observation is None or _path_is_valid_observation(observation):
            continue
        buckets.setdefault(_early_failure_cause(observation), []).append(observation)
    return tuple(
        _early_failure_row(cause, rows)
        for cause, rows in sorted(buckets.items(), key=lambda item: item[0].value)
    )


def confirmation_delay_audit(
    paths: Sequence[OpportunityPath],
    current: TriggerEvaluation,
    best: TriggerEvaluation,
) -> tuple[ConfirmationDelayRow, ...]:
    rows: list[ConfirmationDelayRow] = []
    comparisons: dict[ConfirmationDelayCause, list[tuple[float, float]]] = {}
    for path in paths:
        current_obs = _first_trigger(path, current.policy)
        best_obs = _first_trigger(path, best.policy)
        if current_obs is None or best_obs is None:
            continue
        missed = _missed_move(path, best_obs) or 0.0
        remaining = best_obs.underlying.max_favorable_excursion or 0.0
        cause = (
            ConfirmationDelayCause.ENTERED_AFTER_MOST_UPSIDE
            if missed > 0.5
            else ConfirmationDelayCause.NO_MEANINGFUL_DELAY_COST
        )
        comparisons.setdefault(cause, []).append((missed, remaining))
    for cause, values in sorted(comparisons.items(), key=lambda item: item[0].value):
        rows.append(
            ConfirmationDelayRow(
                cause=cause,
                count=len(values),
                return_missed_before_confirmation=_mean(value[0] for value in values),
                remaining_upside=_mean(value[1] for value in values),
                precision_gain_from_waiting=_delta(best.precision, current.precision),
                expectancy_change=_delta(best.expectancy, current.expectancy),
                mae_change=_delta(best.mae, current.mae),
                reward_risk_change=None,
                holding_period_change=_delta(
                    best.holding_period,
                    current.holding_period,
                ),
            )
        )
    return tuple(rows)


def export_opportunity_evolution_json(
    report: OpportunityEvolutionReport,
    path: Path,
) -> Path:
    path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def export_opportunity_evolution_csv(
    report: OpportunityEvolutionReport,
    path: Path,
) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "opportunity_id",
                "symbol",
                "first_detection_date",
                "observations",
                "classification",
                "first_tradeable_date",
                "confirmation_date",
                "invalidation_date",
                "production_influence",
            ),
        )
        writer.writeheader()
        for path_row in report.paths:
            writer.writerow(
                {
                    "opportunity_id": path_row.identity.opportunity_id,
                    "symbol": path_row.identity.symbol,
                    "first_detection_date": (
                        path_row.identity.first_detection_date.isoformat()
                    ),
                    "observations": path_row.observation_count,
                    "classification": path_row.classification.value,
                    "first_tradeable_date": _date(path_row.first_tradeable_date),
                    "confirmation_date": _date(path_row.confirmation_date),
                    "invalidation_date": _date(path_row.invalidation_date),
                    "production_influence": path_row.production_influence,
                }
            )
    return path


def render_opportunity_evolution_report(
    report: OpportunityEvolutionReport,
) -> tuple[str, ...]:
    start, end = report.replay_date_range
    low, high = report.best_rule.confidence_interval
    return (
        "Opportunity Evolution Intelligence",
        f"Replay Date Range: {_date(start)} to {_date(end)}",
        f"Raw Observations: {report.raw_observations}",
        f"Unique Opportunities: {report.unique_opportunities}",
        f"Completed Opportunities: {report.completed_opportunities}",
        f"Valid Opportunities: {report.valid_opportunities}",
        f"Invalid Opportunities: {report.invalid_opportunities}",
        "Average Observations Per Opportunity: "
        f"{report.average_observations_per_opportunity:.2f}",
        "Current-Policy Triggered Opportunities: "
        f"{report.current_policy.triggered_opportunities}",
        "Best-Rule Triggered Opportunities: "
        f"{report.best_rule.triggered_opportunities}",
        f"Current-Policy Precision: {_pct(report.current_policy.precision)}",
        f"Best-Rule Precision: {_pct(report.best_rule.precision)}",
        f"Confidence Interval: [{_pct(low)}, {_pct(high)}]",
        f"Effective Sample Size: {report.best_rule.effective_sample_size:.2f}",
        f"Annual Unique Signals: {report.best_rule.annual_unique_signals:.2f}",
        f"Average Trigger Delay: {_num(report.best_rule.average_trigger_delay)} days",
        f"Percentage Move Missed: {_pct(report.best_rule.missed_move_percentage)}",
        f"Expectancy: {_pct(report.best_rule.expectancy)}",
        f"MAE: {_pct(report.best_rule.mae)}",
        f"MFE: {_pct(report.best_rule.mfe)}",
        f"Stop-Hit Rate: {_pct(report.best_rule.stop_hit_rate)}",
        f"Target-Hit Rate: {_pct(report.best_rule.target_hit_rate)}",
        f"Worst Outer Fold: {_pct(report.best_rule.worst_fold_precision)}",
        f"Setup Concentration: {_pct(report.best_rule.setup_concentration)}",
        f"Regime Concentration: {_pct(report.best_rule.regime_concentration)}",
        f"Year Concentration: {_pct(report.best_rule.year_concentration)}",
        f"Opportunity Grouping Method: {report.opportunity_grouping_method}",
        f"Best Trigger Rule: {report.best_rule.policy.name.value}",
        "Retained Maturation Features: "
        f"{_feature_names(report.best_rule.policy.retained_features)}",
        f"Primary Timing Bottleneck: {report.primary_timing_bottleneck.value}",
        f"Final Conclusion: {report.final_conclusion.value}",
        "PRODUCTION_INFLUENCE=false",
    )


def render_lifecycle_audit(report: OpportunityEvolutionReport) -> tuple[str, ...]:
    lines = [
        "Opportunity Lifecycle Audit",
        "PRODUCTION_INFLUENCE=false",
        f"Paths: {len(report.paths)}",
        f"Transitions: {len(report.transition_attribution)}",
    ]
    lines.extend(_transition_lines(report.transition_attribution[:20]))
    return tuple(lines)


def render_entry_trigger_discovery(
    report: OpportunityEvolutionReport,
) -> tuple[str, ...]:
    return (
        "Entry Trigger Discovery",
        "PRODUCTION_INFLUENCE=false",
        *_trigger_lines(report.trigger_frontier),
    )


def render_entry_trigger_frontier(
    report: OpportunityEvolutionReport,
) -> tuple[str, ...]:
    return (
        "Entry Trigger Precision-Coverage-Delay Frontier",
        "PRODUCTION_INFLUENCE=false",
        *_trigger_lines(report.pareto_frontier),
    )


def render_early_entry_failures(
    report: OpportunityEvolutionReport,
) -> tuple[str, ...]:
    if not report.early_entry_failures:
        return ("Early Entry Failures", "PRODUCTION_INFLUENCE=false", "- none")
    return (
        "Early Entry Failures",
        "PRODUCTION_INFLUENCE=false",
        *(
            "- "
            f"{row.cause.value}: n={row.count}, "
            f"return {_pct(row.average_return)}, MAE {_pct(row.average_mae)}, "
            f"{row.classification.value}"
            for row in report.early_entry_failures
        ),
    )


def render_confirmation_delay_audit(
    report: OpportunityEvolutionReport,
) -> tuple[str, ...]:
    if not report.confirmation_delay:
        return ("Confirmation Delay Audit", "PRODUCTION_INFLUENCE=false", "- none")
    return (
        "Confirmation Delay Audit",
        "PRODUCTION_INFLUENCE=false",
        *(
            "- "
            f"{row.cause.value}: n={row.count}, "
            f"missed {_pct(row.return_missed_before_confirmation)}, "
            f"remaining {_pct(row.remaining_upside)}, "
            f"precision gain {_pct(row.precision_gain_from_waiting)}"
            for row in report.confirmation_delay
        ),
    )


def render_opportunity_paths(report: OpportunityEvolutionReport) -> tuple[str, ...]:
    lines = ["Opportunity Paths", "PRODUCTION_INFLUENCE=false"]
    for path in report.paths[:30]:
        lines.append(
            "- "
            f"{path.identity.opportunity_id} {path.identity.symbol}: "
            f"{path.observation_count} observations, "
            f"{path.classification.value}, "
            f"first tradeable {_date(path.first_tradeable_date)}, "
            f"confirmation {_date(path.confirmation_date)}"
        )
    return tuple(lines)


def group_opportunity_report(
    report: OpportunityEvolutionReport,
    group_by: str,
) -> tuple[str, ...]:
    normalized = group_by.strip().lower()
    if normalized == "setup":
        return _count_lines(path.identity.setup_family for path in report.paths)
    if normalized == "regime":
        return _count_lines(path.identity.regime_context for path in report.paths)
    if normalized == "lifecycle-state":
        return _count_lines(
            observation.lifecycle_state.value
            for path in report.paths
            for observation in path.observations
        )
    if normalized == "transition":
        return _count_lines(item.driver.value for item in report.transition_attribution)
    if normalized == "trigger":
        return tuple(
            f"- {item.policy.name.value}: precision {_pct(item.precision)}, "
            f"signals {item.triggered_opportunities}"
            for item in report.trigger_frontier
        )
    if normalized == "year":
        return _count_lines(
            str(path.identity.first_detection_date.year) for path in report.paths
        )
    if normalized == "horizon":
        return ("- 20 trading days",)
    return ("- unsupported group-by",)


def _path_from_rows(
    rows: Sequence[DirectionalObservation],
    *,
    definition: DirectionalOutcomeDefinition,
    reset_index: int,
) -> OpportunityPath:
    ordered = tuple(sorted(rows, key=lambda item: item.observed_at))
    first = ordered[0]
    last = ordered[-1]
    opportunity_id = (
        f"{first.symbol}-{_slug(first.setup_type)}-BUY-"
        f"{first.observed_at.isoformat()}-{reset_index:03d}"
    )
    observations = tuple(
        _opportunity_observation(opportunity_id, row, ordered[: index + 1])
        for index, row in enumerate(ordered)
    )
    transitions = _transitions(observations)
    entry_outcomes = tuple(
        _entry_outcome(observation, marker=_entry_marker(observation, observations))
        for observation in observations
    )
    identity = OpportunityIdentity(
        opportunity_id=opportunity_id,
        symbol=first.symbol,
        setup_family=first.setup_type,
        side=OpportunitySide.BUY,
        first_detection_date=first.observed_at,
        start_boundary=first.observed_at,
        end_boundary=last.observed_at,
        reset_index=reset_index,
        reset_reason="initial detection or deterministic reset boundary",
        regime_context=first.regime,
    )
    return OpportunityPath(
        identity=identity,
        observations=observations,
        transitions=transitions,
        entry_outcomes=entry_outcomes,
        classification=_classify_path(observations, definition),
        observation_count=len(observations),
        calendar_duration_days=(last.observed_at - first.observed_at).days,
        trading_day_duration=len(observations),
        first_tradeable_date=_first_state_date(
            observations,
            {
                OpportunityLifecycleState.TRADEABLE_EARLY,
                OpportunityLifecycleState.TRADEABLE_PREFERRED,
                OpportunityLifecycleState.CONFIRMED,
            },
        ),
        preferred_entry_date=_first_state_date(
            observations,
            {OpportunityLifecycleState.TRADEABLE_PREFERRED},
        ),
        confirmation_date=_first_state_date(
            observations,
            {OpportunityLifecycleState.CONFIRMED},
        ),
        invalidation_date=_first_state_date(
            observations,
            {OpportunityLifecycleState.INVALIDATED},
        ),
        expiry_date=_expiry_date(observations),
        outcome_completion_date=last.observed_at,
        production_influence=False,
    )


def _opportunity_observation(
    opportunity_id: str,
    row: DirectionalObservation,
    history: Sequence[DirectionalObservation],
) -> OpportunityObservation:
    opportunity_quality = _opportunity_quality(row)
    trigger_score = _entry_trigger_score(row)
    state = _lifecycle_state(row, opportunity_quality, trigger_score, history)
    return OpportunityObservation(
        opportunity_id=opportunity_id,
        observed_at=row.observed_at,
        symbol=row.symbol,
        lifecycle_state=state,
        opportunity_quality_score=opportunity_quality,
        entry_trigger_score=trigger_score,
        directional_score=row.recommendation_score,
        tradeability_score=trigger_score,
        price=_feature(row, "price") or row.recommendation_score,
        support=_feature(row, "support"),
        resistance=_feature(row, "resistance") or _feature(row, "target_1"),
        stop_candidate=_feature(row, "stop") or row.stop_distance_pct,
        target_candidate=_feature(row, "target") or row.max_favorable_excursion,
        volume_condition=_volume_condition(row),
        data_quality_status="AVAILABLE" if row.completed else "UNAVAILABLE",
        setup=row.setup_type,
        regime=row.regime,
        timing_state=row.entry_timing,
        source_features=_maturation_features(row, history),
        underlying=row,
        production_influence=False,
    )


def _maturation_features(
    row: DirectionalObservation,
    history: Sequence[DirectionalObservation],
) -> tuple[MaturationFeatureSnapshot, ...]:
    groups = (
        MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,
        MaturationFeatureGroup.VOLUME_EVOLUTION,
        MaturationFeatureGroup.VOLATILITY_EVOLUTION,
        MaturationFeatureGroup.RELATIVE_STRENGTH_EVOLUTION,
        MaturationFeatureGroup.SETUP_EVOLUTION,
        MaturationFeatureGroup.TIMING_EVOLUTION,
        MaturationFeatureGroup.REGIME_EVOLUTION,
        MaturationFeatureGroup.TRADE_PLAN_EVOLUTION,
        MaturationFeatureGroup.DATA_QUALITY_EVOLUTION,
    )
    return tuple(_maturation_feature(row, history, group) for group in groups)


def _maturation_feature(
    row: DirectionalObservation,
    history: Sequence[DirectionalObservation],
    group: MaturationFeatureGroup,
) -> MaturationFeatureSnapshot:
    levels = [_group_level(item, group) for item in history]
    usable = [level for level in levels if level is not None]
    current = levels[-1] if levels else None
    previous = levels[-2] if len(levels) > 1 else None
    delta = _delta(current, previous)
    slope = None
    if len(usable) >= 2:
        slope = (usable[-1] - usable[0]) / max(1, len(usable) - 1)
    acceleration = None
    if (
        len(levels) >= 3
        and current is not None
        and previous is not None
        and delta is not None
    ):
        acceleration = delta - ((previous or 0.0) - (levels[-3] or 0.0))
    return MaturationFeatureSnapshot(
        group=group,
        current_level=current,
        one_observation_delta=delta,
        multi_observation_slope=slope,
        rolling_minimum=min(usable) if usable else None,
        rolling_maximum=max(usable) if usable else None,
        change_since_detection=_delta(current, levels[0] if levels else None),
        acceleration=acceleration,
        persistence_count=_persistence_count(levels),
        reversal_flag=bool(delta is not None and delta < -0.10),
        lineage=_lineage(group),
        point_in_time=True,
    )


def _transitions(
    observations: Sequence[OpportunityObservation],
) -> tuple[StateTransition, ...]:
    transitions: list[StateTransition] = []
    previous: OpportunityObservation | None = None
    for observation in observations:
        if previous is None:
            previous = observation
            continue
        if previous.lifecycle_state is observation.lifecycle_state:
            previous = observation
            continue
        driver = _transition_driver(previous, observation)
        transitions.append(
            StateTransition(
                opportunity_id=observation.opportunity_id,
                symbol=observation.symbol,
                previous_state=previous.lifecycle_state,
                new_state=observation.lifecycle_state,
                transition_timestamp=observation.observed_at,
                transition_reason=driver.value.lower().replace("_", " "),
                driver=driver,
                source_features=tuple(
                    item.group.value for item in observation.source_features
                ),
                setup=observation.setup,
                regime=observation.regime,
                timing_state=observation.timing_state,
                directional_score=observation.directional_score,
                tradeability_score=observation.tradeability_score,
                price=observation.price,
                support=observation.support,
                resistance=observation.resistance,
                stop_candidate=observation.stop_candidate,
                target_candidate=observation.target_candidate,
                volume_condition=observation.volume_condition,
                data_quality_status=observation.data_quality_status,
                production_influence=False,
            )
        )
        previous = observation
    return tuple(transitions)


def _entry_outcome(
    observation: OpportunityObservation,
    *,
    marker: EntryMarker,
) -> EntryQualityOutcome:
    row = observation.underlying
    risk = row.stop_distance_pct or abs(row.max_adverse_excursion or 0.0) or 0.05
    reward = row.max_favorable_excursion
    realized = None
    if row.forward_return is not None and risk > 0:
        realized = row.forward_return / risk
    return EntryQualityOutcome(
        opportunity_id=observation.opportunity_id,
        observed_at=observation.observed_at,
        marker=marker,
        entry_price=observation.price,
        stop=observation.stop_candidate,
        target=observation.target_candidate,
        risk_distance=risk,
        reward_risk=None if reward is None or risk <= 0 else reward / risk,
        barrier_first_success=_target_hit(row) and not _stop_hit(row),
        terminal_return=row.forward_return,
        mfe=row.max_favorable_excursion,
        mae=row.max_adverse_excursion,
        realized_r_multiple=realized,
        stop_hit=_stop_hit(row),
        target_hit=_target_hit(row),
        time_to_target=1 if _target_hit(row) else None,
        time_to_stop=1 if _stop_hit(row) else None,
        gap_through_stop_risk=bool((row.max_adverse_excursion or 0.0) < -0.08),
        max_drawdown=row.max_adverse_excursion,
        outcome_available=row.forward_return is not None,
        diagnostic_only=marker is EntryMarker.HINDSIGHT_BEST_ENTRY_DIAGNOSTIC_ONLY,
    )


def _entry_marker(
    observation: OpportunityObservation,
    observations: Sequence[OpportunityObservation],
) -> EntryMarker:
    best = max(
        observations,
        key=lambda item: item.underlying.forward_return or -999.0,
    )
    if observation is best:
        return EntryMarker.HINDSIGHT_BEST_ENTRY_DIAGNOSTIC_ONLY
    if observation.lifecycle_state is OpportunityLifecycleState.CONFIRMED:
        return EntryMarker.FIRST_CONFIRMATION_ENTRY
    if observation.lifecycle_state in {
        OpportunityLifecycleState.TRADEABLE_EARLY,
        OpportunityLifecycleState.TRADEABLE_PREFERRED,
    }:
        return EntryMarker.EARLIEST_VALID_ENTRY
    if observation.underlying.recommendation_score >= 0.75:
        return EntryMarker.CURRENT_POLICY_ENTRY
    return EntryMarker.BEST_RULE_BASED_ENTRY


def _first_trigger(
    path: OpportunityPath,
    policy: TriggerPolicy,
) -> OpportunityObservation | None:
    if policy.name is TriggerRuleName.NO_TRIGGER_REJECTED:
        return None
    for index, observation in enumerate(path.observations):
        if _trigger_matches(path, observation, policy, index):
            return observation
    return None


def _trigger_matches(
    path: OpportunityPath,
    observation: OpportunityObservation,
    policy: TriggerPolicy,
    index: int,
) -> bool:
    state = observation.lifecycle_state
    if policy.name is TriggerRuleName.DETECTED_IMMEDIATE:
        return index == 0
    if policy.name is TriggerRuleName.CURRENT_PRODUCTION_ENTRY:
        return observation.directional_score >= 0.75
    if policy.name is TriggerRuleName.FIRST_EARLY_STATE:
        return state in {
            OpportunityLifecycleState.TRADEABLE_EARLY,
            OpportunityLifecycleState.TRADEABLE_PREFERRED,
            OpportunityLifecycleState.CONFIRMED,
        }
    if policy.name is TriggerRuleName.FIRST_AGGRESSIVE_STATE:
        return "AGGRESSIVE" in observation.timing_state.upper()
    if policy.name is TriggerRuleName.FIRST_PREFERRED_STATE:
        return state in {
            OpportunityLifecycleState.TRADEABLE_PREFERRED,
            OpportunityLifecycleState.CONFIRMED,
        }
    if policy.name is TriggerRuleName.FIRST_CONFIRMATION_STATE:
        return state is OpportunityLifecycleState.CONFIRMED
    if policy.name is TriggerRuleName.BEST_TIMING_THRESHOLD:
        return observation.entry_trigger_score >= 0.60
    if policy.name is TriggerRuleName.FULL_STACK_SCORE_ONLY:
        return observation.opportunity_quality_score >= 0.65
    if policy.name is TriggerRuleName.FULL_STACK_PLUS_TIMING:
        return (
            observation.opportunity_quality_score >= 0.60
            and observation.entry_trigger_score >= 0.55
        )
    if policy.name is TriggerRuleName.PRICE_CONFIRMATION_TRIGGER:
        return (
            _feature_delta(
                observation,
                MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,
            )
            >= 0
            and observation.opportunity_quality_score >= 0.55
        )
    if policy.name is TriggerRuleName.VOLUME_CONFIRMATION_TRIGGER:
        return (
            observation.volume_condition == "CONFIRMED"
            and observation.opportunity_quality_score >= 0.50
        )
    if policy.name is TriggerRuleName.RISK_CONTRACTION_TRIGGER:
        return (
            _feature_delta(
                observation,
                MaturationFeatureGroup.VOLATILITY_EVOLUTION,
            )
            >= 0
            and observation.entry_trigger_score >= 0.55
        )
    if policy.name is TriggerRuleName.RETEST_HOLD_TRIGGER:
        return (
            state
            in {
                OpportunityLifecycleState.TRADEABLE_PREFERRED,
                OpportunityLifecycleState.CONFIRMED,
            }
            and observation.entry_trigger_score >= 0.58
        )
    if policy.name is TriggerRuleName.MULTI_FACTOR_MATURATION_TRIGGER:
        return (
            observation.opportunity_quality_score >= 0.58
            and observation.entry_trigger_score >= 0.58
            and _regime_value(observation.regime) >= 0.40
        )
    if policy.name is TriggerRuleName.TRAJECTORY_IMPROVEMENT_TRIGGER:
        return (
            _feature_delta(
                observation,
                MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION,
            )
            > 0
            and _feature_delta(
                observation,
                MaturationFeatureGroup.TIMING_EVOLUTION,
            )
            >= 0
        )
    if policy.name is TriggerRuleName.PERSISTENCE_TRIGGER:
        if index == 0:
            return False
        previous = path.observations[index - 1]
        return state in {
            OpportunityLifecycleState.TRADEABLE_PREFERRED,
            OpportunityLifecycleState.CONFIRMED,
        } and previous.lifecycle_state in {
            OpportunityLifecycleState.TRADEABLE_PREFERRED,
            OpportunityLifecycleState.CONFIRMED,
        }
    return False


def _requires_reset(
    previous: DirectionalObservation,
    current: DirectionalObservation,
    reset_gap_days: int,
) -> bool:
    if previous.symbol != current.symbol:
        return True
    if previous.setup_type != current.setup_type:
        return True
    if (current.observed_at - previous.observed_at).days > reset_gap_days:
        return True
    if "INVALID" in previous.entry_timing.upper():
        return True
    if _regime_family(previous.regime) != _regime_family(current.regime):
        return True
    return False


def _opportunity_quality(row: DirectionalObservation) -> float:
    values = (
        _feature_value(row, BuyFeatureGroup.PRICE_STRUCTURE),
        _feature_value(row, BuyFeatureGroup.VOLUME),
        _feature_value(row, BuyFeatureGroup.SETUP),
        _feature_value(row, BuyFeatureGroup.RELATIVE_STRENGTH),
        _regime_value(row.regime),
    )
    return _bounded_mean(values, fallback=row.recommendation_score)


def _entry_trigger_score(row: DirectionalObservation) -> float:
    values = (
        _timing_value(row),
        _feature_value(row, BuyFeatureGroup.TRADE_PLAN_QUALITY),
        _feature_value(row, BuyFeatureGroup.VOLATILITY_RISK),
        _feature_value(row, BuyFeatureGroup.BREAKOUT_CONFIRMATION),
    )
    return _bounded_mean(values, fallback=_timing_value(row))


def _lifecycle_state(
    row: DirectionalObservation,
    opportunity_quality: float,
    trigger_score: float,
    history: Sequence[DirectionalObservation],
) -> OpportunityLifecycleState:
    timing = row.entry_timing.upper()
    if not row.completed:
        return OpportunityLifecycleState.UNAVAILABLE
    if "INVALID" in timing or opportunity_quality <= 0.18:
        return OpportunityLifecycleState.INVALIDATED
    if "LATE" in timing or "EXTENDED" in timing:
        return OpportunityLifecycleState.EXTENDED
    if "DISTRIBUT" in row.setup_type.upper():
        return OpportunityLifecycleState.DISTRIBUTING
    if "CONFIRM" in timing or (opportunity_quality >= 0.70 and trigger_score >= 0.65):
        return OpportunityLifecycleState.CONFIRMED
    if "PREFERRED" in timing:
        return OpportunityLifecycleState.TRADEABLE_PREFERRED
    if "EARLY" in timing or "AGGRESSIVE" in timing or trigger_score >= 0.55:
        return OpportunityLifecycleState.TRADEABLE_EARLY
    if len(history) >= 2 and opportunity_quality > _opportunity_quality(history[-2]):
        return OpportunityLifecycleState.IMPROVING
    if opportunity_quality >= 0.40:
        return OpportunityLifecycleState.FORMING
    return OpportunityLifecycleState.DETECTED


def _transition_driver(
    previous: OpportunityObservation,
    current: OpportunityObservation,
) -> TransitionDriver:
    if current.lifecycle_state is OpportunityLifecycleState.CONFIRMED:
        return TransitionDriver.CONFIRMATION_ARRIVED
    if current.entry_trigger_score - previous.entry_trigger_score > 0.10:
        return TransitionDriver.TRADEABILITY_IMPROVED
    if current.opportunity_quality_score - previous.opportunity_quality_score > 0.10:
        return TransitionDriver.DIRECTIONAL_EVIDENCE_IMPROVED
    if _regime_value(current.regime) > _regime_value(previous.regime):
        return TransitionDriver.REGIME_IMPROVED
    if current.stop_candidate is not None and previous.stop_candidate is not None:
        if current.stop_candidate < previous.stop_candidate:
            return TransitionDriver.RISK_CONTRACTED
    return TransitionDriver.NO_MEANINGFUL_IMPROVEMENT


def _classify_path(
    observations: Sequence[OpportunityObservation],
    definition: DirectionalOutcomeDefinition,
) -> OpportunityClassification:
    if not observations:
        return OpportunityClassification.UNAVAILABLE_OUTCOME
    valid = any(
        label_directional_outcome(item.underlying, definition)
        is DirectionalLabel.BUY_DIRECTIONAL
        for item in observations
    )
    triggered = any(item.entry_trigger_score >= 0.55 for item in observations)
    late = triggered and any(
        item.lifecycle_state is OpportunityLifecycleState.EXTENDED
        for item in observations
        if item.entry_trigger_score >= 0.55
    )
    early = triggered and any(
        item.lifecycle_state
        in {
            OpportunityLifecycleState.DETECTED,
            OpportunityLifecycleState.FORMING,
        }
        for item in observations
        if item.entry_trigger_score >= 0.55
    )
    if valid and triggered and early:
        return OpportunityClassification.VALID_OPPORTUNITY_EARLY_TRIGGER
    if valid and triggered and late:
        return OpportunityClassification.VALID_OPPORTUNITY_LATE_TRIGGER
    if valid and triggered:
        return OpportunityClassification.VALID_OPPORTUNITY_VALID_TRIGGER
    if valid:
        return OpportunityClassification.VALID_OPPORTUNITY_NO_TRIGGER
    if triggered:
        return OpportunityClassification.INVALID_OPPORTUNITY_TRIGGERED
    return OpportunityClassification.INVALID_OPPORTUNITY_REJECTED


def _path_has_outcome(path: OpportunityPath) -> bool:
    return any(item.underlying.forward_return is not None for item in path.observations)


def _path_is_valid(
    path: OpportunityPath,
    definition: DirectionalOutcomeDefinition,
) -> bool:
    return any(
        label_directional_outcome(item.underlying, definition)
        is DirectionalLabel.BUY_DIRECTIONAL
        for item in path.observations
    )


def _path_is_invalid(
    path: OpportunityPath,
    definition: DirectionalOutcomeDefinition,
) -> bool:
    return _path_has_outcome(path) and not _path_is_valid(path, definition)


def _path_is_valid_observation(observation: OpportunityObservation) -> bool:
    return bool(
        observation.underlying.forward_return is not None
        and observation.underlying.forward_return > 0
    )


def _feature(row: DirectionalObservation, key: str) -> float | None:
    values = dict(row.feature_values)
    return values.get(key) or values.get(key.replace("_", "-"))


def _feature_value(row: DirectionalObservation, group: BuyFeatureGroup) -> float | None:
    try:
        return _buy_feature_value(row, group)
    except (NameError, KeyError, AttributeError):
        return None


def _regime_value(regime: str) -> float:
    return _buy_regime_value(regime)


def _timing_value(row: DirectionalObservation) -> float:
    return _buy_timing_value(row)


def _group_level(
    row: DirectionalObservation,
    group: MaturationFeatureGroup,
) -> float | None:
    if group is MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION:
        return _bounded_mean(
            (
                _feature_value(row, BuyFeatureGroup.PRICE_STRUCTURE),
                _feature_value(row, BuyFeatureGroup.TREND),
                _feature_value(row, BuyFeatureGroup.SUPPORT_RESISTANCE),
            ),
            fallback=row.price_component or row.recommendation_score,
        )
    if group is MaturationFeatureGroup.VOLUME_EVOLUTION:
        return _feature_value(row, BuyFeatureGroup.VOLUME)
    if group is MaturationFeatureGroup.VOLATILITY_EVOLUTION:
        raw = _feature_value(row, BuyFeatureGroup.VOLATILITY_RISK)
        if raw is not None:
            return raw
        if row.stop_distance_pct is None:
            return None
        return max(0.0, min(1.0, 1.0 - row.stop_distance_pct * 10.0))
    if group is MaturationFeatureGroup.RELATIVE_STRENGTH_EVOLUTION:
        return _feature_value(row, BuyFeatureGroup.RELATIVE_STRENGTH)
    if group is MaturationFeatureGroup.SETUP_EVOLUTION:
        return _bounded_mean(
            (
                _feature_value(row, BuyFeatureGroup.SETUP),
                _feature_value(row, BuyFeatureGroup.BREAKOUT_CONFIRMATION),
                row.setup_quality,
            ),
            fallback=row.setup_quality,
        )
    if group is MaturationFeatureGroup.TIMING_EVOLUTION:
        return _timing_value(row)
    if group is MaturationFeatureGroup.REGIME_EVOLUTION:
        return _regime_value(row.regime)
    if group is MaturationFeatureGroup.TRADE_PLAN_EVOLUTION:
        return _bounded_mean(
            (
                _feature_value(row, BuyFeatureGroup.TRADE_PLAN_QUALITY),
                row.trade_plan_quality,
            ),
            fallback=row.trade_plan_quality,
        )
    if group is MaturationFeatureGroup.DATA_QUALITY_EVOLUTION:
        return 1.0 if row.completed else 0.0
    return None


def _lineage(group: MaturationFeatureGroup) -> tuple[str, ...]:
    if group is MaturationFeatureGroup.PRICE_STRUCTURE_EVOLUTION:
        return ("price_component", "trend", "support_resistance")
    if group is MaturationFeatureGroup.VOLUME_EVOLUTION:
        return ("volume", "relative_volume", "breakout_volume")
    if group is MaturationFeatureGroup.VOLATILITY_EVOLUTION:
        return ("stop_distance_pct", "volatility_risk", "atr_proxy")
    if group is MaturationFeatureGroup.RELATIVE_STRENGTH_EVOLUTION:
        return ("relative_strength",)
    if group is MaturationFeatureGroup.SETUP_EVOLUTION:
        return ("setup_quality", "breakout_confirmation")
    if group is MaturationFeatureGroup.TIMING_EVOLUTION:
        return ("entry_timing",)
    if group is MaturationFeatureGroup.REGIME_EVOLUTION:
        return ("market_regime",)
    if group is MaturationFeatureGroup.TRADE_PLAN_EVOLUTION:
        return ("trade_plan_quality", "stop_distance", "target_candidate")
    return ("completed", "source")


def _feature_delta(
    observation: OpportunityObservation,
    group: MaturationFeatureGroup,
) -> float:
    for feature in observation.source_features:
        if feature.group is group:
            return feature.one_observation_delta or 0.0
    return 0.0


def _volume_condition(row: DirectionalObservation) -> str:
    volume = _feature_value(row, BuyFeatureGroup.VOLUME)
    if volume is None:
        return "UNAVAILABLE"
    if volume >= 0.65:
        return "CONFIRMED"
    if volume <= 0.30:
        return "WARNING"
    return "NEUTRAL"


def _target_hit(row: DirectionalObservation) -> bool:
    return bool(
        row.upside_barrier_day is not None
        or (
            row.max_favorable_excursion is not None
            and row.max_favorable_excursion >= 0.04
        )
    )


def _stop_hit(row: DirectionalObservation) -> bool:
    return bool(
        row.downside_barrier_day is not None
        or (
            row.max_adverse_excursion is not None and row.max_adverse_excursion <= -0.03
        )
    )


def _missed_move(
    path: OpportunityPath,
    observation: OpportunityObservation,
) -> float | None:
    first_price = path.observations[0].price
    trigger_price = observation.price
    if first_price is None or trigger_price is None or first_price <= 0:
        return None
    return max(0.0, (trigger_price - first_price) / first_price)


def _worst_fold_precision(
    triggered: Sequence[tuple[OpportunityPath, OpportunityObservation]],
    definition: DirectionalOutcomeDefinition,
) -> float | None:
    buckets: dict[int, list[OpportunityObservation]] = {}
    for _, observation in triggered:
        buckets.setdefault(observation.observed_at.year, []).append(observation)
    if not buckets:
        return None
    precisions = []
    for observations in buckets.values():
        wins = sum(
            label_directional_outcome(item.underlying, definition)
            is DirectionalLabel.BUY_DIRECTIONAL
            for item in observations
        )
        precision = _safe_ratio(wins, len(observations))
        if precision is not None:
            precisions.append(precision)
    return min(precisions) if precisions else None


def _trigger_concentration(
    triggered: Sequence[tuple[OpportunityPath, OpportunityObservation]],
    field: str,
) -> float:
    if not triggered:
        return 0.0
    if field == "setup":
        values = [path.identity.setup_family for path, _ in triggered]
    else:
        values = [path.identity.regime_context for path, _ in triggered]
    return max(Counter(values).values()) / len(values)


def _year_concentration(
    triggered: Sequence[tuple[OpportunityPath, OpportunityObservation]],
) -> float:
    if not triggered:
        return 0.0
    values = [path.identity.first_detection_date.year for path, _ in triggered]
    return max(Counter(values).values()) / len(values)


def _observation_level_precision(
    paths: Sequence[OpportunityPath],
    policy: TriggerPolicy,
    definition: DirectionalOutcomeDefinition,
) -> float | None:
    matches = [
        observation
        for path in paths
        for index, observation in enumerate(path.observations)
        if _trigger_matches(path, observation, policy, index)
    ]
    if not matches:
        return None
    wins = sum(
        label_directional_outcome(item.underlying, definition)
        is DirectionalLabel.BUY_DIRECTIONAL
        for item in matches
    )
    return _safe_ratio(wins, len(matches))


def _signal_inflation(paths: Sequence[OpportunityPath], policy: TriggerPolicy) -> float:
    observation_matches = sum(
        1
        for path in paths
        for index, observation in enumerate(path.observations)
        if _trigger_matches(path, observation, policy, index)
    )
    opportunity_matches = sum(
        _first_trigger(path, policy) is not None for path in paths
    )
    return _safe_ratio(observation_matches, opportunity_matches) or 0.0


def _tier(
    precision: float | None,
    triggered_count: int,
    returns: Sequence[float],
) -> str:
    expectancy = _mean(returns)
    if triggered_count < 5:
        return "INSUFFICIENT_SAMPLE"
    if precision is not None and precision >= 0.70 and (expectancy or 0.0) > 0:
        return "RESEARCH_CANDIDATE_A"
    if precision is not None and precision >= 0.60:
        return "RESEARCH_CANDIDATE_B"
    if precision is not None and precision >= 0.50:
        return "WATCH"
    return "REJECT"


def _dominates(candidate: TriggerEvaluation, other: TriggerEvaluation) -> bool:
    if candidate is other:
        return False
    candidate_precision = candidate.precision or 0.0
    other_precision = other.precision or 0.0
    candidate_coverage = candidate.opportunity_conversion_rate or 0.0
    other_coverage = other.opportunity_conversion_rate or 0.0
    candidate_delay = candidate.average_trigger_delay or 999.0
    other_delay = other.average_trigger_delay or 999.0
    return (
        candidate_precision >= other_precision
        and candidate_coverage >= other_coverage
        and candidate_delay <= other_delay
        and (
            candidate_precision > other_precision
            or candidate_coverage > other_coverage
            or candidate_delay < other_delay
        )
    )


def _evaluation_by_name(
    evaluations: Sequence[TriggerEvaluation],
    name: TriggerRuleName,
) -> TriggerEvaluation | None:
    return next((item for item in evaluations if item.policy.name is name), None)


def _best_trigger(
    evaluations: Sequence[TriggerEvaluation],
) -> TriggerEvaluation | None:
    if not evaluations:
        return None
    return max(
        evaluations,
        key=lambda item: (
            item.precision or 0.0,
            item.cost_adjusted_expectancy or -999.0,
            item.triggered_opportunities,
            -item.policy.complexity,
        ),
    )


def _timing_bottleneck(
    current: TriggerEvaluation,
    best: TriggerEvaluation,
    paths: Sequence[OpportunityPath],
) -> TimingBottleneck:
    if current.triggered_opportunities < 5 or best.triggered_opportunities < 5:
        return TimingBottleneck.INSUFFICIENT_EVIDENCE
    if (best.precision or 0.0) <= (current.precision or 0.0):
        return TimingBottleneck.STOP_DESIGN_PRIMARY
    if (current.signal_inflation_factor or 0.0) > 1.5:
        return TimingBottleneck.OPPORTUNITY_GROUPING_INSUFFICIENT
    if (best.average_trigger_delay or 0.0) > (current.average_trigger_delay or 0.0):
        return TimingBottleneck.TRIGGER_FIRES_TOO_EARLY
    if any(
        path.classification is OpportunityClassification.VALID_OPPORTUNITY_LATE_TRIGGER
        for path in paths
    ):
        return TimingBottleneck.TRIGGER_FIRES_TOO_LATE
    return TimingBottleneck.SETUP_MATURATION_NOT_MODELLED


def _final_conclusion(
    current: TriggerEvaluation,
    best: TriggerEvaluation,
) -> OpportunityEvolutionConclusion:
    if best.triggered_opportunities < 5:
        return OpportunityEvolutionConclusion.MORE_DATA_REQUIRED
    if (best.precision or 0.0) >= 0.70 and (best.worst_fold_precision or 0.0) >= 0.55:
        return OpportunityEvolutionConclusion.STABLE_70_PERCENT_TRIGGER_FOUND
    if (best.precision or 0.0) >= 0.60 and (best.worst_fold_precision or 0.0) >= 0.50:
        return OpportunityEvolutionConclusion.STABLE_60_PERCENT_TRIGGER_FOUND
    if (best.precision or 0.0) > (current.precision or 0.0) + 0.05:
        return OpportunityEvolutionConclusion.TIMING_IMPROVEMENT_FOUND
    if (best.precision or 0.0) > 0.65 and (
        best.opportunity_conversion_rate or 0.0
    ) < 0.20:
        return OpportunityEvolutionConclusion.HIGH_PRECISION_LOW_COVERAGE_TRIGGER_FOUND
    return OpportunityEvolutionConclusion.CURRENT_TIMING_REMAINS_SUPERIOR


def _early_failure_cause(
    observation: OpportunityObservation,
) -> EarlyEntryFailureCause:
    if observation.volume_condition == "WARNING":
        return EarlyEntryFailureCause.WEAK_BREAKOUT_VOLUME
    if _regime_value(observation.regime) <= 0.25:
        return EarlyEntryFailureCause.HOSTILE_MARKET_REGIME
    if observation.entry_trigger_score < 0.45:
        return EarlyEntryFailureCause.SETUP_INCOMPLETE
    if observation.stop_candidate is not None and observation.stop_candidate > 0.08:
        return EarlyEntryFailureCause.STOP_TOO_WIDE
    if (observation.underlying.max_adverse_excursion or 0.0) < -0.08:
        return EarlyEntryFailureCause.VOLATILITY_STILL_EXPANDING
    if (observation.underlying.forward_return or 0.0) < -0.05:
        return EarlyEntryFailureCause.SIGNAL_SCORE_DECAY
    return EarlyEntryFailureCause.LABEL_AMBIGUITY


def _early_failure_class(
    cause: EarlyEntryFailureCause,
) -> EarlyEntryFailureClass:
    if cause in {
        EarlyEntryFailureCause.SETUP_INCOMPLETE,
        EarlyEntryFailureCause.RESISTANCE_NOT_CLEARED,
        EarlyEntryFailureCause.WEAK_BREAKOUT_VOLUME,
        EarlyEntryFailureCause.SUPPORT_NOT_ESTABLISHED,
        EarlyEntryFailureCause.RELATIVE_STRENGTH_NOT_CONFIRMED,
    }:
        return EarlyEntryFailureClass.WAITING_WOULD_HAVE_HELPED
    if cause in {
        EarlyEntryFailureCause.HOSTILE_MARKET_REGIME,
        EarlyEntryFailureCause.REPEATED_FAILED_BREAKOUT,
        EarlyEntryFailureCause.LOW_LIQUIDITY,
        EarlyEntryFailureCause.SETUP_DETERIORATION,
    }:
        return EarlyEntryFailureClass.OPPORTUNITY_WAS_NEVER_VALID
    if cause in {
        EarlyEntryFailureCause.STOP_TOO_WIDE,
        EarlyEntryFailureCause.REWARD_RISK_INSUFFICIENT,
    }:
        return EarlyEntryFailureClass.STOP_DESIGN_PRIMARY
    if cause is EarlyEntryFailureCause.LABEL_AMBIGUITY:
        return EarlyEntryFailureClass.LABEL_AMBIGUITY
    return EarlyEntryFailureClass.WAITING_WOULD_NOT_HAVE_HELPED


def _early_failure_row(
    cause: EarlyEntryFailureCause,
    rows: Sequence[OpportunityObservation],
) -> EarlyEntryFailureRow:
    setups = Counter(row.setup for row in rows)
    regimes = Counter(row.regime for row in rows)
    timings = Counter(row.timing_state for row in rows)
    return EarlyEntryFailureRow(
        cause=cause,
        classification=_early_failure_class(cause),
        count=len(rows),
        average_return=_mean(row.underlying.forward_return for row in rows),
        average_mae=_mean(row.underlying.max_adverse_excursion for row in rows),
        dominant_setup=setups.most_common(1)[0][0] if setups else "UNAVAILABLE",
        dominant_regime=regimes.most_common(1)[0][0] if regimes else "UNAVAILABLE",
        dominant_timing=timings.most_common(1)[0][0] if timings else "UNAVAILABLE",
    )


def _count_lines(values: Iterable[str]) -> tuple[str, ...]:
    counter = Counter(values)
    if not counter:
        return ("- none",)
    return tuple(
        f"- {key}: {count}"
        for key, count in sorted(counter.items(), key=lambda item: item[0])
    )


def _transition_lines(transitions: Sequence[StateTransition]) -> tuple[str, ...]:
    if not transitions:
        return ("- none",)
    return tuple(
        "- "
        f"{item.symbol} {item.transition_timestamp.isoformat()}: "
        f"{item.previous_state.value} -> {item.new_state.value} "
        f"({item.driver.value})"
        for item in transitions
    )


def _trigger_lines(evaluations: Sequence[TriggerEvaluation]) -> tuple[str, ...]:
    if not evaluations:
        return ("- none",)
    return tuple(
        "- "
        f"{item.policy.name.value}: precision {_pct(item.precision)}, "
        f"coverage {_pct(item.opportunity_conversion_rate)}, "
        f"signals {item.triggered_opportunities}, "
        f"delay {_num(item.average_trigger_delay)}d, "
        f"expectancy {_pct(item.expectancy)}, "
        f"tier {item.tier}"
        for item in evaluations
    )


def _feature_names(features: Sequence[MaturationFeatureGroup]) -> str:
    if not features:
        return "none"
    return ", ".join(item.value for item in features)


def _regime_family(regime: str) -> str:
    normalized = regime.upper()
    if "BULL" in normalized or "POSITIVE" in normalized or "UP" in normalized:
        return "BULLISH"
    if "BEAR" in normalized or "NEGATIVE" in normalized or "DOWN" in normalized:
        return "BEARISH"
    if "SIDE" in normalized or "NEUTRAL" in normalized or "RANGE" in normalized:
        return "NEUTRAL"
    if "TRANSITION" in normalized:
        return "TRANSITION"
    return normalized or "UNAVAILABLE"


def _first_state_date(
    observations: Sequence[OpportunityObservation],
    states: set[OpportunityLifecycleState],
) -> date | None:
    for observation in observations:
        if observation.lifecycle_state in states:
            return observation.observed_at
    return None


def _expiry_date(
    observations: Sequence[OpportunityObservation],
) -> date | None:
    if not observations:
        return None
    if observations[-1].lifecycle_state in {
        OpportunityLifecycleState.INVALIDATED,
        OpportunityLifecycleState.EXPIRED,
    }:
        return observations[-1].observed_at
    return None


def _slug(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() else "-" for character in value.upper()
    )
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts) or "UNAVAILABLE"


def _bounded_mean(
    values: Iterable[float | None],
    *,
    fallback: float | None = None,
) -> float:
    usable = [value for value in values if value is not None]
    if not usable:
        return max(0.0, min(1.0, fallback or 0.0))
    return max(0.0, min(1.0, sum(usable) / len(usable)))


def _persistence_count(values: Sequence[float | None]) -> int:
    count = 0
    for value in reversed(values):
        if value is None or value < 0.55:
            break
        count += 1
    return count


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _mean(values: Iterable[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous


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


__all__ = [
    "ConfirmationDelayCause",
    "ConfirmationDelayRow",
    "EarlyEntryFailureCause",
    "EarlyEntryFailureClass",
    "EarlyEntryFailureRow",
    "EntryMarker",
    "EntryQualityOutcome",
    "MaturationFeatureGroup",
    "MaturationFeatureSnapshot",
    "OpportunityClassification",
    "OpportunityEvolutionConclusion",
    "OpportunityEvolutionReport",
    "OpportunityIdentity",
    "OpportunityLifecycleState",
    "OpportunityObservation",
    "OpportunityPath",
    "OpportunitySide",
    "StateTransition",
    "TimingBottleneck",
    "TransitionDriver",
    "TriggerEvaluation",
    "TriggerPolicy",
    "TriggerRuleName",
    "build_opportunity_evolution_report",
    "confirmation_delay_audit",
    "early_entry_failure_taxonomy",
    "evaluate_trigger_policy",
    "export_opportunity_evolution_csv",
    "export_opportunity_evolution_json",
    "group_opportunity_report",
    "pareto_trigger_frontier",
    "reconstruct_opportunity_paths",
    "render_confirmation_delay_audit",
    "render_early_entry_failures",
    "render_entry_trigger_discovery",
    "render_entry_trigger_frontier",
    "render_lifecycle_audit",
    "render_opportunity_evolution_report",
    "render_opportunity_paths",
    "trigger_policies",
]
