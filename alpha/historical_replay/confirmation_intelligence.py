from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from statistics import pstdev
from typing import Any

from alpha.historical_replay.opportunity_evolution import (
    OpportunityObservation,
    OpportunityPath,
    TriggerRuleName,
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


class GroupingQuality(StrEnum):
    GROUPING_VALID = "GROUPING_VALID"
    OPPORTUNITY_SPLIT_TOO_AGGRESSIVELY = "OPPORTUNITY_SPLIT_TOO_AGGRESSIVELY"
    DISTINCT_SETUPS_MERGED = "DISTINCT_SETUPS_MERGED"
    RESET_EVENT_MISSED = "RESET_EVENT_MISSED"
    INSUFFICIENT_OBSERVATIONS = "INSUFFICIENT_OBSERVATIONS"
    GROUPING_AMBIGUOUS = "GROUPING_AMBIGUOUS"


class TriggerFailureCause(StrEnum):
    FALSE_BREAKOUT = "FALSE_BREAKOUT"
    INSUFFICIENT_VOLUME_CONFIRMATION = "INSUFFICIENT_VOLUME_CONFIRMATION"
    DISTRIBUTION_AFTER_TRIGGER = "DISTRIBUTION_AFTER_TRIGGER"
    WEAK_RELATIVE_STRENGTH = "WEAK_RELATIVE_STRENGTH"
    SECTOR_NON_CONFIRMATION = "SECTOR_NON_CONFIRMATION"
    HOSTILE_MARKET_BREADTH = "HOSTILE_MARKET_BREADTH"
    HOSTILE_MARKET_REGIME = "HOSTILE_MARKET_REGIME"
    REGIME_TRANSITION_FAILURE = "REGIME_TRANSITION_FAILURE"
    RESISTANCE_NOT_CLEARED = "RESISTANCE_NOT_CLEARED"
    BREAKOUT_CLOSE_WEAK = "BREAKOUT_CLOSE_WEAK"
    BREAKOUT_GAP_UNSTABLE = "BREAKOUT_GAP_UNSTABLE"
    RETEST_FAILED = "RETEST_FAILED"
    SUPPORT_NOT_ESTABLISHED = "SUPPORT_NOT_ESTABLISHED"
    VOLATILITY_TOO_HIGH = "VOLATILITY_TOO_HIGH"
    VOLATILITY_EXPANSION_ADVERSE = "VOLATILITY_EXPANSION_ADVERSE"
    STOP_TOO_TIGHT = "STOP_TOO_TIGHT"
    STOP_TOO_WIDE = "STOP_TOO_WIDE"
    REWARD_RISK_COLLAPSED = "REWARD_RISK_COLLAPSED"
    ENTRY_TOO_EARLY = "ENTRY_TOO_EARLY"
    ENTRY_TOO_LATE = "ENTRY_TOO_LATE"
    ENTRY_TOO_EXTENDED = "ENTRY_TOO_EXTENDED"
    SETUP_INCOMPLETE = "SETUP_INCOMPLETE"
    SETUP_STALE = "SETUP_STALE"
    MULTIPLE_FAILED_ATTEMPTS = "MULTIPLE_FAILED_ATTEMPTS"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    GAP_THROUGH_STOP = "GAP_THROUGH_STOP"
    EVENT_SHOCK = "EVENT_SHOCK"
    DIRECTIONAL_SCORE_ERROR = "DIRECTIONAL_SCORE_ERROR"
    OPPORTUNITY_GROUPING_ERROR = "OPPORTUNITY_GROUPING_ERROR"
    LABEL_AMBIGUITY = "LABEL_AMBIGUITY"
    DATA_QUALITY_FAILURE = "DATA_QUALITY_FAILURE"
    INHERENT_MARKET_UNCERTAINTY = "INHERENT_MARKET_UNCERTAINTY"


class Preventability(StrEnum):
    PREVENTABLE_WITH_EXISTING_EVIDENCE = "PREVENTABLE_WITH_EXISTING_EVIDENCE"
    PREVENTABLE_WITH_NEW_POINT_IN_TIME_FEATURE = (
        "PREVENTABLE_WITH_NEW_POINT_IN_TIME_FEATURE"
    )
    STOP_OR_TRADE_PLAN_PRIMARY = "STOP_OR_TRADE_PLAN_PRIMARY"
    OPPORTUNITY_GROUPING_PRIMARY = "OPPORTUNITY_GROUPING_PRIMARY"
    LABEL_OR_OUTCOME_AMBIGUITY = "LABEL_OR_OUTCOME_AMBIGUITY"
    NOT_REASONABLY_PREVENTABLE = "NOT_REASONABLY_PREVENTABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ConfirmationGroup(StrEnum):
    PRICE_CONFIRMATION = "PRICE_CONFIRMATION"
    VOLUME_CONFIRMATION = "VOLUME_CONFIRMATION"
    PARTICIPATION_CONFIRMATION = "PARTICIPATION_CONFIRMATION"
    RELATIVE_STRENGTH_CONFIRMATION = "RELATIVE_STRENGTH_CONFIRMATION"
    RISK_CONFIRMATION = "RISK_CONFIRMATION"
    REGIME_CONFIRMATION = "REGIME_CONFIRMATION"
    SETUP_CONFIRMATION = "SETUP_CONFIRMATION"
    RETEST_QUALITY = "RETEST_QUALITY"
    PERSISTENCE = "PERSISTENCE"
    CANCELLATION = "CANCELLATION"


class ParticipationSequence(StrEnum):
    CONTRACTION_THEN_EXPANSION = "CONTRACTION_THEN_EXPANSION"
    ACCUMULATION_THEN_BREAKOUT = "ACCUMULATION_THEN_BREAKOUT"
    BREAKOUT_THEN_LOW_VOLUME_RETEST = "BREAKOUT_THEN_LOW_VOLUME_RETEST"
    BREAKOUT_VOLUME_PERSISTENCE = "BREAKOUT_VOLUME_PERSISTENCE"
    HIGH_VOLUME_ADVANCE_LOW_VOLUME_PULLBACK = "HIGH_VOLUME_ADVANCE_LOW_VOLUME_PULLBACK"
    RS_BREAKOUT_WITH_VOLUME_CONFIRMATION = "RS_BREAKOUT_WITH_VOLUME_CONFIRMATION"
    SUPPORT_HOLD_WITH_RENEWED_DEMAND = "SUPPORT_HOLD_WITH_RENEWED_DEMAND"


class RetestState(StrEnum):
    NO_RETEST = "NO_RETEST"
    RETEST_FORMING = "RETEST_FORMING"
    CONTROLLED_RETEST = "CONTROLLED_RETEST"
    SUPPORT_HOLD_CONFIRMED = "SUPPORT_HOLD_CONFIRMED"
    DEEP_RETEST = "DEEP_RETEST"
    FAILED_RETEST = "FAILED_RETEST"
    RETEST_UNAVAILABLE = "RETEST_UNAVAILABLE"


class CancellationReason(StrEnum):
    PRICE_CONFIRMATION_LOST = "PRICE_CONFIRMATION_LOST"
    VOLUME_CONFIRMATION_LOST = "VOLUME_CONFIRMATION_LOST"
    SUPPORT_FAILED = "SUPPORT_FAILED"
    REGIME_TURNED_HOSTILE = "REGIME_TURNED_HOSTILE"
    RS_DETERIORATED = "RS_DETERIORATED"
    TRADE_PLAN_DEGRADED = "TRADE_PLAN_DEGRADED"
    SETUP_INVALIDATED = "SETUP_INVALIDATED"
    VOLATILITY_SPIKED = "VOLATILITY_SPIKED"
    GAP_RISK_INCREASED = "GAP_RISK_INCREASED"
    DATA_QUALITY_DEGRADED = "DATA_QUALITY_DEGRADED"


class BreakoutClassification(StrEnum):
    CLEAN_BREAKOUT = "CLEAN_BREAKOUT"
    WEAK_BREAKOUT = "WEAK_BREAKOUT"
    UNCONFIRMED_BREAKOUT = "UNCONFIRMED_BREAKOUT"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"
    BREAKOUT_THEN_RETEST = "BREAKOUT_THEN_RETEST"
    BREAKOUT_THEN_DISTRIBUTION = "BREAKOUT_THEN_DISTRIBUTION"
    AMBIGUOUS_BREAKOUT = "AMBIGUOUS_BREAKOUT"


class DirectionFailureClassification(StrEnum):
    DIRECTION_WRONG = "DIRECTION_WRONG"
    DIRECTION_RIGHT_BUT_ENTRY_WRONG = "DIRECTION_RIGHT_BUT_ENTRY_WRONG"
    DIRECTION_RIGHT_BUT_STOP_WRONG = "DIRECTION_RIGHT_BUT_STOP_WRONG"
    DIRECTION_RIGHT_BUT_HORIZON_WRONG = "DIRECTION_RIGHT_BUT_HORIZON_WRONG"
    DIRECTION_AMBIGUOUS = "DIRECTION_AMBIGUOUS"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class ConfirmationRuleName(StrEnum):
    FROZEN_FULL_STACK_PLUS_TIMING = "FROZEN_FULL_STACK_PLUS_TIMING"
    PRICE_CONFIRMATION_RULE = "PRICE_CONFIRMATION_RULE"
    VOLUME_PARTICIPATION_RULE = "VOLUME_PARTICIPATION_RULE"
    PARTICIPATION_SEQUENCE_RULE = "PARTICIPATION_SEQUENCE_RULE"
    RS_CONFIRMATION_RULE = "RS_CONFIRMATION_RULE"
    RISK_CONFIRMATION_RULE = "RISK_CONFIRMATION_RULE"
    RETEST_HOLD_RULE = "RETEST_HOLD_RULE"
    PERSISTENCE_CONFIRMATION_RULE = "PERSISTENCE_CONFIRMATION_RULE"
    CANCELLATION_AWARE_RULE = "CANCELLATION_AWARE_RULE"
    MULTI_STAGE_CONFIRMATION_RULE = "MULTI_STAGE_CONFIRMATION_RULE"


class ConfirmationBottleneck(StrEnum):
    PRICE_CONFIRMATION_PRIMARY = "PRICE_CONFIRMATION_PRIMARY"
    PARTICIPATION_CONFIRMATION_PRIMARY = "PARTICIPATION_CONFIRMATION_PRIMARY"
    FALSE_BREAKOUT_PRIMARY = "FALSE_BREAKOUT_PRIMARY"
    RETEST_QUALITY_PRIMARY = "RETEST_QUALITY_PRIMARY"
    RELATIVE_STRENGTH_CONFIRMATION_PRIMARY = "RELATIVE_STRENGTH_CONFIRMATION_PRIMARY"
    REGIME_CONFIRMATION_PRIMARY = "REGIME_CONFIRMATION_PRIMARY"
    RISK_CONFIRMATION_PRIMARY = "RISK_CONFIRMATION_PRIMARY"
    TRIGGER_PERSISTENCE_PRIMARY = "TRIGGER_PERSISTENCE_PRIMARY"
    TRIGGER_CANCELLATION_PRIMARY = "TRIGGER_CANCELLATION_PRIMARY"
    STOP_DESIGN_PRIMARY = "STOP_DESIGN_PRIMARY"
    OPPORTUNITY_GROUPING_PRIMARY = "OPPORTUNITY_GROUPING_PRIMARY"
    DIRECTIONAL_QUALITY_PRIMARY = "DIRECTIONAL_QUALITY_PRIMARY"
    MULTIPLE_CONFIRMATION_BOTTLENECKS = "MULTIPLE_CONFIRMATION_BOTTLENECKS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ConfirmationConclusion(StrEnum):
    STABLE_70_PERCENT_CONFIRMED_TRIGGER_FOUND = (
        "STABLE_70_PERCENT_CONFIRMED_TRIGGER_FOUND"
    )
    STABLE_60_PERCENT_CONFIRMED_TRIGGER_FOUND = (
        "STABLE_60_PERCENT_CONFIRMED_TRIGGER_FOUND"
    )
    CONFIRMATION_IMPROVEMENT_FOUND = "CONFIRMATION_IMPROVEMENT_FOUND"
    RETEST_SPECIALIST_TRIGGER_FOUND = "RETEST_SPECIALIST_TRIGGER_FOUND"
    PARTICIPATION_SIGNAL_ADDS_VALUE = "PARTICIPATION_SIGNAL_ADDS_VALUE"
    HIGH_PRECISION_LOW_COVERAGE_ONLY = "HIGH_PRECISION_LOW_COVERAGE_ONLY"
    CURRENT_FULL_STACK_PLUS_TIMING_REMAINS_SUPERIOR = (
        "CURRENT_FULL_STACK_PLUS_TIMING_REMAINS_SUPERIOR"
    )
    ENTRY_CONFIRMATION_NOT_PRIMARY = "ENTRY_CONFIRMATION_NOT_PRIMARY"
    MORE_DATA_REQUIRED = "MORE_DATA_REQUIRED"


@dataclass(frozen=True, slots=True)
class ConfirmationScore:
    name: str
    score: float
    lineage: tuple[str, ...]
    missing: bool
    overlap_with_existing: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TriggerFailureAttribution:
    opportunity_id: str
    symbol: str
    trigger_date: date
    primary_cause: TriggerFailureCause
    secondary_causes: tuple[TriggerFailureCause, ...]
    evidence_available_at_trigger: tuple[str, ...]
    evidence_after_trigger: tuple[str, ...]
    preventability: Preventability
    financial_impact: float | None
    mae: float | None
    mfe: float | None
    time_to_failure: int | None
    setup: str
    regime: str
    lifecycle_state: str
    timing_state: str
    grouping_quality: GroupingQuality
    direction_failure: DirectionFailureClassification

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["trigger_date"] = self.trigger_date.isoformat()
        payload["primary_cause"] = self.primary_cause.value
        payload["secondary_causes"] = [item.value for item in self.secondary_causes]
        payload["preventability"] = self.preventability.value
        payload["grouping_quality"] = self.grouping_quality.value
        payload["direction_failure"] = self.direction_failure.value
        return payload


@dataclass(frozen=True, slots=True)
class ParticipationSequenceResult:
    sequence: ParticipationSequence
    occurrence_count: int
    success_precision: float | None
    failure_precision: float | None
    effective_sample_size: float
    setup_distribution: tuple[tuple[str, int], ...]
    regime_distribution: tuple[tuple[str, int], ...]
    average_entry_delay: float | None
    missed_move: float | None
    expectancy: float | None
    mae: float | None
    mfe: float | None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sequence"] = self.sequence.value
        return payload


@dataclass(frozen=True, slots=True)
class ConfirmationCandidateEvaluation:
    rule: ConfirmationRuleName
    description: str
    retained_groups: tuple[ConfirmationGroup, ...]
    triggered_opportunities: int
    successes: int
    failures: int
    precision: float | None
    confidence_interval: tuple[float | None, float | None]
    recall: float | None
    opportunity_coverage: float | None
    annual_unique_signals: float
    effective_sample_size: float
    expectancy: float | None
    cost_adjusted_expectancy: float | None
    mae: float | None
    mfe: float | None
    stop_hit_rate: float | None
    target_hit_rate: float | None
    average_delay: float | None
    median_delay: float | None
    missed_move: float | None
    cancellation_rate: float | None
    worst_fold_precision: float | None
    best_fold_precision: float | None
    fold_dispersion: float | None
    year_concentration: float
    regime_concentration: float
    setup_concentration: float
    symbol_concentration: float
    sector_concentration: float
    complexity: int
    tier: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rule"] = self.rule.value
        payload["retained_groups"] = [item.value for item in self.retained_groups]
        payload["confidence_interval"] = list(self.confidence_interval)
        return payload


@dataclass(frozen=True, slots=True)
class ConfirmationOpportunityRecord:
    opportunity_id: str
    instrument: str
    setup: str
    regime: str
    baseline_trigger_date: date | None
    confirmed_trigger_date: date | None
    baseline_outcome: str
    confirmed_outcome: str
    failure_causes: tuple[TriggerFailureCause, ...]
    preventability: Preventability | None
    confirmation_features: tuple[ConfirmationScore, ...]
    participation_proxies: tuple[str, ...]
    retest_state: RetestState
    persistence_state: str
    cancellation_reasons: tuple[CancellationReason, ...]
    stop: float | None
    target: float | None
    mae: float | None
    mfe: float | None
    realised_return: float | None
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "instrument": self.instrument,
            "setup": self.setup,
            "regime": self.regime,
            "baseline_trigger_date": _date(self.baseline_trigger_date),
            "confirmed_trigger_date": _date(self.confirmed_trigger_date),
            "baseline_outcome": self.baseline_outcome,
            "confirmed_outcome": self.confirmed_outcome,
            "failure_causes": [item.value for item in self.failure_causes],
            "preventability": None
            if self.preventability is None
            else self.preventability.value,
            "confirmation_features": [
                item.as_dict() for item in self.confirmation_features
            ],
            "participation_proxies": list(self.participation_proxies),
            "retest_state": self.retest_state.value,
            "persistence_state": self.persistence_state,
            "cancellation_reasons": [item.value for item in self.cancellation_reasons],
            "stop": self.stop,
            "target": self.target,
            "mae": self.mae,
            "mfe": self.mfe,
            "realised_return": self.realised_return,
            "production_influence": self.production_influence,
        }


@dataclass(frozen=True, slots=True)
class ConfirmationIntelligenceReport:
    generated_on: date
    replay_date_range: tuple[date | None, date | None]
    frozen_baseline_trigger: TriggerRuleName
    eligible_opportunities: int
    baseline: ConfirmationCandidateEvaluation
    best_confirmed_rule: ConfirmationCandidateEvaluation
    best_specialist_rule: ConfirmationCandidateEvaluation
    frontier: tuple[ConfirmationCandidateEvaluation, ...]
    pareto_frontier: tuple[ConfirmationCandidateEvaluation, ...]
    failures: tuple[TriggerFailureAttribution, ...]
    opportunity_records: tuple[ConfirmationOpportunityRecord, ...]
    participation_sequences: tuple[ParticipationSequenceResult, ...]
    ordered_addition: tuple[ConfirmationCandidateEvaluation, ...]
    ablation: tuple[ConfirmationCandidateEvaluation, ...]
    top_failure_causes: tuple[tuple[str, int], ...]
    retained_confirmation_groups: tuple[ConfirmationGroup, ...]
    rejected_confirmation_groups: tuple[ConfirmationGroup, ...]
    preventable_failure_percentage: float | None
    false_breakout_rate: float | None
    controlled_retest_count: int
    participation_confirmed_count: int
    primary_bottleneck: ConfirmationBottleneck
    final_conclusion: ConfirmationConclusion
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_on": self.generated_on.isoformat(),
            "replay_date_range": [
                _date(self.replay_date_range[0]),
                _date(self.replay_date_range[1]),
            ],
            "frozen_baseline_trigger": self.frozen_baseline_trigger.value,
            "eligible_opportunities": self.eligible_opportunities,
            "baseline": self.baseline.as_dict(),
            "best_confirmed_rule": self.best_confirmed_rule.as_dict(),
            "best_specialist_rule": self.best_specialist_rule.as_dict(),
            "frontier": [item.as_dict() for item in self.frontier],
            "pareto_frontier": [item.as_dict() for item in self.pareto_frontier],
            "failures": [item.as_dict() for item in self.failures],
            "opportunity_records": [
                item.as_dict() for item in self.opportunity_records
            ],
            "participation_sequences": [
                item.as_dict() for item in self.participation_sequences
            ],
            "ordered_addition": [item.as_dict() for item in self.ordered_addition],
            "ablation": [item.as_dict() for item in self.ablation],
            "top_failure_causes": list(self.top_failure_causes),
            "retained_confirmation_groups": [
                item.value for item in self.retained_confirmation_groups
            ],
            "rejected_confirmation_groups": [
                item.value for item in self.rejected_confirmation_groups
            ],
            "preventable_failure_percentage": self.preventable_failure_percentage,
            "false_breakout_rate": self.false_breakout_rate,
            "controlled_retest_count": self.controlled_retest_count,
            "participation_confirmed_count": self.participation_confirmed_count,
            "primary_bottleneck": self.primary_bottleneck.value,
            "final_conclusion": self.final_conclusion.value,
            "production_influence": self.production_influence,
        }


def build_confirmation_intelligence_report(
    observations: Sequence[DirectionalObservation] | None = None,
    *,
    definition: DirectionalOutcomeDefinition | None = None,
    symbol: str | None = None,
    opportunity_id: str | None = None,
) -> ConfirmationIntelligenceReport:
    rows = tuple(observations or deterministic_research_observations())
    if symbol is not None:
        rows = tuple(row for row in rows if row.symbol == symbol.strip().upper())
    outcome_definition = definition or DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.TERMINAL_RETURN,
        horizon_days=20,
        positive_return_threshold=0.02,
        negative_return_threshold=-0.02,
    )
    evolution = build_opportunity_evolution_report(
        rows,
        definition=outcome_definition,
        symbol=symbol,
        opportunity_id=opportunity_id,
    )
    paths = evolution.paths
    baseline = _evaluate_confirmation_rule(
        paths,
        ConfirmationRuleName.FROZEN_FULL_STACK_PLUS_TIMING,
        outcome_definition,
    )
    candidates = tuple(
        _evaluate_confirmation_rule(paths, rule, outcome_definition)
        for rule in ConfirmationRuleName
    )
    pareto = _pareto(candidates)
    best = _best_confirmed_rule(pareto, baseline)
    specialist = _best_specialist_rule(candidates, baseline)
    failures = tuple(
        _failure_attribution(path, trigger, outcome_definition)
        for path, trigger in _baseline_triggered(paths)
        if not _is_success(trigger, outcome_definition)
    )
    records = tuple(
        _opportunity_record(path, outcome_definition, best.rule) for path in paths
    )
    top_causes = tuple(
        (cause.value, count)
        for cause, count in Counter(
            item.primary_cause for item in failures
        ).most_common(8)
    )
    retained = best.retained_groups
    rejected = tuple(group for group in ConfirmationGroup if group not in retained)
    all_dates = [row.observed_at for row in rows]
    return ConfirmationIntelligenceReport(
        generated_on=date.today(),
        replay_date_range=(
            min(all_dates) if all_dates else None,
            max(all_dates) if all_dates else None,
        ),
        frozen_baseline_trigger=TriggerRuleName.FULL_STACK_PLUS_TIMING,
        eligible_opportunities=len(paths),
        baseline=baseline,
        best_confirmed_rule=best,
        best_specialist_rule=specialist,
        frontier=candidates,
        pareto_frontier=pareto,
        failures=failures,
        opportunity_records=records,
        participation_sequences=_participation_sequences(paths, outcome_definition),
        ordered_addition=_ordered_addition(candidates),
        ablation=_ablation(candidates, best),
        top_failure_causes=top_causes,
        retained_confirmation_groups=retained,
        rejected_confirmation_groups=rejected,
        preventable_failure_percentage=_safe_ratio(
            sum(
                item.preventability is Preventability.PREVENTABLE_WITH_EXISTING_EVIDENCE
                for item in failures
            ),
            len(failures),
        ),
        false_breakout_rate=_safe_ratio(
            sum(
                item.primary_cause is TriggerFailureCause.FALSE_BREAKOUT
                for item in failures
            ),
            len(failures),
        ),
        controlled_retest_count=sum(
            item.retest_state
            in {RetestState.CONTROLLED_RETEST, RetestState.SUPPORT_HOLD_CONFIRMED}
            for item in records
        ),
        participation_confirmed_count=sum(
            bool(item.participation_proxies) for item in records
        ),
        primary_bottleneck=_primary_bottleneck(failures, best, baseline),
        final_conclusion=_final_conclusion(best, baseline),
        production_influence=False,
    )


def export_confirmation_intelligence_json(
    report: ConfirmationIntelligenceReport,
    path: Path,
) -> Path:
    path.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n")
    return path


def export_confirmation_intelligence_csv(
    report: ConfirmationIntelligenceReport,
    path: Path,
) -> Path:
    fieldnames = (
        "opportunity_id",
        "instrument",
        "setup",
        "regime",
        "baseline_trigger_date",
        "confirmed_trigger_date",
        "baseline_outcome",
        "confirmed_outcome",
        "failure_causes",
        "preventability",
        "retest_state",
        "persistence_state",
        "cancellation_reasons",
        "mae",
        "mfe",
        "realised_return",
        "production_influence",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in report.opportunity_records:
            payload = record.as_dict()
            writer.writerow(
                {
                    key: "|".join(payload[key])
                    if isinstance(payload.get(key), list)
                    else payload.get(key)
                    for key in fieldnames
                }
            )
    return path


def render_confirmation_intelligence_report(
    report: ConfirmationIntelligenceReport,
) -> tuple[str, ...]:
    low, high = report.best_confirmed_rule.confidence_interval
    retained_groups = _render_values(
        group.value for group in report.retained_confirmation_groups
    )
    rejected_groups = _render_values(
        group.value for group in report.rejected_confirmation_groups
    )
    return (
        "Entry Trigger Confirmation Intelligence",
        "Replay Period: "
        f"{_date(report.replay_date_range[0])} to "
        f"{_date(report.replay_date_range[1])}",
        f"Frozen Baseline Trigger: {report.frozen_baseline_trigger.value}",
        f"Eligible Opportunities: {report.eligible_opportunities}",
        f"Baseline Triggered Opportunities: {report.baseline.triggered_opportunities}",
        f"Baseline Successes: {report.baseline.successes}",
        f"Baseline Failures: {report.baseline.failures}",
        f"Baseline Precision: {_pct(report.baseline.precision)}",
        "Best Confirmed-Trigger Precision: "
        f"{_pct(report.best_confirmed_rule.precision)}",
        f"Confidence Interval: [{_pct(low)}, {_pct(high)}]",
        "Effective Sample Size: "
        f"{report.best_confirmed_rule.effective_sample_size:.2f}",
        "Opportunity Coverage: "
        f"{_pct(report.best_confirmed_rule.opportunity_coverage)}",
        f"Annual Signals: {report.best_confirmed_rule.annual_unique_signals:.2f}",
        f"Expectancy: {_pct(report.best_confirmed_rule.expectancy)}",
        "Cost-Adjusted Expectancy: "
        f"{_pct(report.best_confirmed_rule.cost_adjusted_expectancy)}",
        f"MAE: {_pct(report.best_confirmed_rule.mae)}",
        f"MFE: {_pct(report.best_confirmed_rule.mfe)}",
        f"Average Delay: {_num(report.best_confirmed_rule.average_delay)} days",
        f"Missed Move: {_pct(report.best_confirmed_rule.missed_move)}",
        "Confirmation Cancellation Rate: "
        f"{_pct(report.best_confirmed_rule.cancellation_rate)}",
        f"False-Breakout Rate: {_pct(report.false_breakout_rate)}",
        f"Controlled-Retest Count: {report.controlled_retest_count}",
        f"Participation-Confirmed Count: {report.participation_confirmed_count}",
        "Preventable Failure Percentage: "
        f"{_pct(report.preventable_failure_percentage)}",
        f"Top Failure Causes: {_render_pairs(report.top_failure_causes)}",
        f"Retained Confirmation Groups: {retained_groups}",
        f"Rejected Confirmation Groups: {rejected_groups}",
        f"Best Transparent Rule: {report.best_confirmed_rule.rule.value}",
        f"Best Specialist Rule: {report.best_specialist_rule.rule.value}",
        f"Worst Outer Fold: {_pct(report.best_confirmed_rule.worst_fold_precision)}",
        f"Concentration Status: {_concentration_status(report.best_confirmed_rule)}",
        f"Primary Bottleneck: {report.primary_bottleneck.value}",
        f"Final Conclusion: {report.final_conclusion.value}",
        "PRODUCTION_INFLUENCE=false",
    )


def render_trigger_failure_attribution(
    report: ConfirmationIntelligenceReport,
) -> tuple[str, ...]:
    lines = ["Trigger Failure Attribution", "PRODUCTION_INFLUENCE=false"]
    lines.extend(
        "- "
        f"{item.symbol} {item.trigger_date.isoformat()}: "
        f"{item.primary_cause.value}, {item.preventability.value}, "
        f"impact {_pct(item.financial_impact)}"
        for item in report.failures[:40]
    )
    return tuple(lines) if len(lines) > 2 else (*lines, "- none")


def render_participation_confirmation(
    report: ConfirmationIntelligenceReport,
) -> tuple[str, ...]:
    return (
        "Participation Confirmation",
        "Concept: PARTICIPATION_CONFIRMATION, not direct institutional flow.",
        "Limitation: proxies use only replay price/volume/RS/liquidity fields.",
        "PRODUCTION_INFLUENCE=false",
        *_sequence_lines(report.participation_sequences),
    )


def render_false_breakout_audit(
    report: ConfirmationIntelligenceReport,
) -> tuple[str, ...]:
    counter = Counter(
        record.confirmed_outcome
        for record in report.opportunity_records
        if "BREAKOUT" in record.confirmed_outcome
    )
    return (
        "False Breakout Audit",
        "PRODUCTION_INFLUENCE=false",
        *_count_lines(counter),
    )


def render_retest_quality_audit(
    report: ConfirmationIntelligenceReport,
) -> tuple[str, ...]:
    return (
        "Retest Quality Audit",
        "PRODUCTION_INFLUENCE=false",
        *_count_lines(
            Counter(record.retest_state.value for record in report.opportunity_records)
        ),
    )


def render_trigger_persistence_audit(
    report: ConfirmationIntelligenceReport,
) -> tuple[str, ...]:
    return (
        "Trigger Persistence Audit",
        "PRODUCTION_INFLUENCE=false",
        *_frontier_lines(
            item
            for item in report.frontier
            if item.rule
            in {
                ConfirmationRuleName.PERSISTENCE_CONFIRMATION_RULE,
                ConfirmationRuleName.MULTI_STAGE_CONFIRMATION_RULE,
            }
        ),
    )


def render_trigger_cancellation_audit(
    report: ConfirmationIntelligenceReport,
) -> tuple[str, ...]:
    reasons = Counter(
        reason.value
        for record in report.opportunity_records
        for reason in record.cancellation_reasons
    )
    return (
        "Trigger Cancellation Audit",
        "PRODUCTION_INFLUENCE=false",
        *_count_lines(reasons),
    )


def render_confirmation_frontier(
    report: ConfirmationIntelligenceReport,
) -> tuple[str, ...]:
    return (
        "Confirmation Precision-Coverage-Delay Frontier",
        "PRODUCTION_INFLUENCE=false",
        *_frontier_lines(report.pareto_frontier),
    )


def group_confirmation_report(
    report: ConfirmationIntelligenceReport,
    group_by: str,
) -> tuple[str, ...]:
    normalized = group_by.strip().lower()
    if normalized == "failure-cause":
        return _count_lines(
            Counter(item.primary_cause.value for item in report.failures)
        )
    if normalized == "preventability":
        return _count_lines(
            Counter(item.preventability.value for item in report.failures)
        )
    if normalized == "setup":
        return _count_lines(Counter(item.setup for item in report.opportunity_records))
    if normalized == "regime":
        return _count_lines(Counter(item.regime for item in report.opportunity_records))
    if normalized == "confirmation":
        return _frontier_lines(report.ordered_addition)
    if normalized == "trigger":
        return _frontier_lines(report.frontier)
    if normalized == "year":
        return _count_lines(
            Counter(
                str(record.baseline_trigger_date.year)
                for record in report.opportunity_records
                if record.baseline_trigger_date is not None
            )
        )
    if normalized == "horizon":
        return ("- 20 trading days",)
    return ("- unsupported group-by",)


def _evaluate_confirmation_rule(
    paths: Sequence[OpportunityPath],
    rule: ConfirmationRuleName,
    definition: DirectionalOutcomeDefinition,
) -> ConfirmationCandidateEvaluation:
    triggered = [
        (path, observation)
        for path in paths
        if (observation := _first_rule_trigger(path, rule)) is not None
    ]
    successes = sum(
        _is_success(observation, definition) for _, observation in triggered
    )
    failures = len(triggered) - successes
    returns = [item.underlying.forward_return for _, item in triggered]
    maes = [item.underlying.max_adverse_excursion for _, item in triggered]
    mfes = [item.underlying.max_favorable_excursion for _, item in triggered]
    delays = [
        (item.observed_at - path.identity.first_detection_date).days
        for path, item in triggered
    ]
    missed = [_missed_move(path, item) for path, item in triggered]
    cancellations = [_cancellation_reasons(path, item) for path, item in triggered]
    years = {path.identity.first_detection_date.year for path in paths}
    valid_paths = sum(_path_has_success(path, definition) for path in paths)
    precision = _safe_ratio(successes, len(triggered))
    return ConfirmationCandidateEvaluation(
        rule=rule,
        description=_rule_description(rule),
        retained_groups=_rule_groups(rule),
        triggered_opportunities=len(triggered),
        successes=successes,
        failures=failures,
        precision=precision,
        confidence_interval=wilson_interval(successes, len(triggered)),
        recall=_safe_ratio(successes, valid_paths),
        opportunity_coverage=_safe_ratio(len(triggered), len(paths)),
        annual_unique_signals=len(triggered) / max(1, len(years)),
        effective_sample_size=effective_sample_size(
            tuple(item.underlying for _, item in triggered)
        ),
        expectancy=_mean(returns),
        cost_adjusted_expectancy=None
        if not triggered
        else (_mean(returns) or 0.0) - 0.0025,
        mae=_mean(maes),
        mfe=_mean(mfes),
        stop_hit_rate=_safe_ratio(
            sum(_stop_hit(item) for _, item in triggered),
            len(triggered),
        ),
        target_hit_rate=_safe_ratio(
            sum(_target_hit(item) for _, item in triggered),
            len(triggered),
        ),
        average_delay=_mean(float(item) for item in delays),
        median_delay=_median(delays),
        missed_move=_mean(missed),
        cancellation_rate=_safe_ratio(
            sum(bool(item) for item in cancellations),
            len(cancellations),
        ),
        worst_fold_precision=_fold_precision(triggered, definition, "worst"),
        best_fold_precision=_fold_precision(triggered, definition, "best"),
        fold_dispersion=_fold_dispersion(triggered, definition),
        year_concentration=_concentration(
            str(path.identity.first_detection_date.year) for path, _ in triggered
        ),
        regime_concentration=_concentration(
            path.identity.regime_context for path, _ in triggered
        ),
        setup_concentration=_concentration(
            path.identity.setup_family for path, _ in triggered
        ),
        symbol_concentration=_concentration(
            path.identity.symbol for path, _ in triggered
        ),
        sector_concentration=_concentration(
            item.underlying.sector for _, item in triggered
        ),
        complexity=max(1, len(_rule_groups(rule))),
        tier=_tier(
            precision,
            len(triggered),
            _mean(returns),
            _fold_precision(triggered, definition, "worst"),
        ),
    )


def _baseline_triggered(
    paths: Sequence[OpportunityPath],
) -> tuple[tuple[OpportunityPath, OpportunityObservation], ...]:
    return tuple(
        (path, observation)
        for path in paths
        if (
            observation := _first_rule_trigger(
                path,
                ConfirmationRuleName.FROZEN_FULL_STACK_PLUS_TIMING,
            )
        )
        is not None
    )


def _first_rule_trigger(
    path: OpportunityPath,
    rule: ConfirmationRuleName,
) -> OpportunityObservation | None:
    for index, observation in enumerate(path.observations):
        if _rule_matches(path, observation, index, rule):
            return observation
    return None


def _rule_matches(
    path: OpportunityPath,
    observation: OpportunityObservation,
    index: int,
    rule: ConfirmationRuleName,
) -> bool:
    baseline = (
        observation.opportunity_quality_score >= 0.60
        and observation.entry_trigger_score >= 0.55
    )
    if rule is ConfirmationRuleName.FROZEN_FULL_STACK_PLUS_TIMING:
        return baseline
    if not baseline:
        return False
    scores = _confirmation_scores(path, observation)
    price = _score(scores, "BREAKOUT_CONFIRMATION_SCORE")
    participation = _score(scores, "PARTICIPATION_CONFIRMATION_SCORE")
    rs = _feature(observation, "relative_strength")
    risk = _score(scores, "RISK_CONFIRMATION_SCORE")
    retest = _retest_state(path, observation)
    cancellation = bool(_cancellation_reasons(path, observation))
    if rule is ConfirmationRuleName.PRICE_CONFIRMATION_RULE:
        return price >= 0.58
    if rule is ConfirmationRuleName.VOLUME_PARTICIPATION_RULE:
        return participation >= 0.58
    if rule is ConfirmationRuleName.PARTICIPATION_SEQUENCE_RULE:
        return bool(_participation_proxies(path, observation))
    if rule is ConfirmationRuleName.RS_CONFIRMATION_RULE:
        return (rs or 0.0) >= 0.58
    if rule is ConfirmationRuleName.RISK_CONFIRMATION_RULE:
        return risk >= 0.58
    if rule is ConfirmationRuleName.RETEST_HOLD_RULE:
        return retest in {
            RetestState.CONTROLLED_RETEST,
            RetestState.SUPPORT_HOLD_CONFIRMED,
        }
    if rule is ConfirmationRuleName.PERSISTENCE_CONFIRMATION_RULE:
        return (
            index > 0
            and path.observations[index - 1].opportunity_quality_score >= 0.60
            and path.observations[index - 1].entry_trigger_score >= 0.55
        )
    if rule is ConfirmationRuleName.CANCELLATION_AWARE_RULE:
        return not cancellation
    if rule is ConfirmationRuleName.MULTI_STAGE_CONFIRMATION_RULE:
        return (
            price >= 0.55
            and participation >= 0.55
            and risk >= 0.50
            and not cancellation
        )
    return False


def _failure_attribution(
    path: OpportunityPath,
    trigger: OpportunityObservation,
    definition: DirectionalOutcomeDefinition,
) -> TriggerFailureAttribution:
    causes = _failure_causes(path, trigger)
    primary = causes[0]
    return TriggerFailureAttribution(
        opportunity_id=path.identity.opportunity_id,
        symbol=path.identity.symbol,
        trigger_date=trigger.observed_at,
        primary_cause=primary,
        secondary_causes=tuple(causes[1:]),
        evidence_available_at_trigger=_evidence_available(path, trigger),
        evidence_after_trigger=_evidence_after_trigger(path, trigger),
        preventability=_preventability(primary),
        financial_impact=trigger.underlying.forward_return,
        mae=trigger.underlying.max_adverse_excursion,
        mfe=trigger.underlying.max_favorable_excursion,
        time_to_failure=trigger.underlying.downside_barrier_day,
        setup=path.identity.setup_family,
        regime=path.identity.regime_context,
        lifecycle_state=trigger.lifecycle_state.value,
        timing_state=trigger.timing_state,
        grouping_quality=_grouping_quality(path),
        direction_failure=_direction_failure(trigger, definition),
    )


def _failure_causes(
    path: OpportunityPath,
    trigger: OpportunityObservation,
) -> tuple[TriggerFailureCause, ...]:
    causes: list[TriggerFailureCause] = []
    if (
        _breakout_classification(path, trigger)
        is BreakoutClassification.FAILED_BREAKOUT
    ):
        causes.append(TriggerFailureCause.FALSE_BREAKOUT)
    if (_feature(trigger, "volume") or 0.0) < 0.45:
        causes.append(TriggerFailureCause.INSUFFICIENT_VOLUME_CONFIRMATION)
    if (_feature(trigger, "relative_strength") or 0.0) < 0.45:
        causes.append(TriggerFailureCause.WEAK_RELATIVE_STRENGTH)
    if "BEAR" in trigger.regime.upper():
        causes.append(TriggerFailureCause.HOSTILE_MARKET_REGIME)
    if trigger.entry_trigger_score < 0.58:
        causes.append(TriggerFailureCause.ENTRY_TOO_EARLY)
    if trigger.lifecycle_state.value == "EXTENDED":
        causes.append(TriggerFailureCause.ENTRY_TOO_EXTENDED)
    if trigger.underlying.stop_distance_pct is not None:
        if trigger.underlying.stop_distance_pct <= 0.02:
            causes.append(TriggerFailureCause.STOP_TOO_TIGHT)
        if trigger.underlying.stop_distance_pct >= 0.08:
            causes.append(TriggerFailureCause.STOP_TOO_WIDE)
    if _retest_state(path, trigger) is RetestState.FAILED_RETEST:
        causes.append(TriggerFailureCause.RETEST_FAILED)
    if trigger.underlying.max_adverse_excursion is not None:
        if trigger.underlying.max_adverse_excursion < -0.08:
            causes.append(TriggerFailureCause.VOLATILITY_EXPANSION_ADVERSE)
    if _grouping_quality(path) is not GroupingQuality.GROUPING_VALID:
        causes.append(TriggerFailureCause.OPPORTUNITY_GROUPING_ERROR)
    if not trigger.underlying.completed:
        causes.append(TriggerFailureCause.DATA_QUALITY_FAILURE)
    return tuple(dict.fromkeys(causes)) or (
        TriggerFailureCause.INHERENT_MARKET_UNCERTAINTY,
    )


def _opportunity_record(
    path: OpportunityPath,
    definition: DirectionalOutcomeDefinition,
    confirmed_rule: ConfirmationRuleName,
) -> ConfirmationOpportunityRecord:
    baseline = _first_rule_trigger(
        path,
        ConfirmationRuleName.FROZEN_FULL_STACK_PLUS_TIMING,
    )
    confirmed = _first_rule_trigger(path, confirmed_rule)
    failure = (
        None
        if baseline is None or _is_success(baseline, definition)
        else _failure_attribution(path, baseline, definition)
    )
    observation = confirmed or baseline or path.observations[-1]
    cancellation_observation = (
        baseline if failure is not None and baseline else observation
    )
    return ConfirmationOpportunityRecord(
        opportunity_id=path.identity.opportunity_id,
        instrument=path.identity.symbol,
        setup=path.identity.setup_family,
        regime=path.identity.regime_context,
        baseline_trigger_date=None if baseline is None else baseline.observed_at,
        confirmed_trigger_date=None if confirmed is None else confirmed.observed_at,
        baseline_outcome=_outcome_label(baseline, definition),
        confirmed_outcome=_confirmed_outcome_label(path, confirmed, definition),
        failure_causes=()
        if failure is None
        else (failure.primary_cause, *failure.secondary_causes),
        preventability=None if failure is None else failure.preventability,
        confirmation_features=_confirmation_scores(path, observation),
        participation_proxies=_participation_proxies(path, observation),
        retest_state=_retest_state(path, observation),
        persistence_state=_persistence_state(path, observation),
        cancellation_reasons=_cancellation_reasons(path, cancellation_observation),
        stop=observation.stop_candidate,
        target=observation.target_candidate,
        mae=observation.underlying.max_adverse_excursion,
        mfe=observation.underlying.max_favorable_excursion,
        realised_return=observation.underlying.forward_return,
        production_influence=False,
    )


def _confirmation_scores(
    path: OpportunityPath,
    observation: OpportunityObservation,
) -> tuple[ConfirmationScore, ...]:
    price = _bounded_mean(
        (
            observation.opportunity_quality_score,
            _feature(observation, "breakout_confirmation"),
            _feature(observation, "price_volume"),
        )
    )
    participation = _bounded_mean(
        (
            _feature(observation, "volume"),
            _feature(observation, "relative_volume"),
            _feature(observation, "liquidity"),
            _sequence_score(path, observation),
        )
    )
    breakout = _bounded_mean((price, observation.entry_trigger_score))
    retest = _retest_score(_retest_state(path, observation))
    risk = _bounded_mean(
        (
            observation.underlying.trade_plan_quality,
            None
            if observation.underlying.stop_distance_pct is None
            else 1.0 - min(1.0, observation.underlying.stop_distance_pct * 8.0),
        )
    )
    return (
        ConfirmationScore(
            "OPPORTUNITY_QUALITY_SCORE",
            observation.opportunity_quality_score,
            ("price_structure", "setup", "regime", "relative_strength"),
            False,
            ("entry_trigger_score",),
        ),
        ConfirmationScore(
            "ENTRY_TRIGGER_SCORE",
            observation.entry_trigger_score,
            ("timing_state", "trade_plan", "risk", "breakout"),
            False,
            ("opportunity_quality_score",),
        ),
        ConfirmationScore(
            "PARTICIPATION_CONFIRMATION_SCORE",
            participation,
            ("volume", "relative_volume", "liquidity", "price_volume_sequence"),
            _feature(observation, "volume") is None,
            ("volume_confirmation",),
        ),
        ConfirmationScore(
            "BREAKOUT_CONFIRMATION_SCORE",
            breakout,
            ("breakout_confirmation", "price_volume", "close_quality_proxy"),
            False,
            ("price_structure",),
        ),
        ConfirmationScore(
            "RETEST_QUALITY_SCORE",
            retest,
            ("support", "pullback_depth", "volume_contraction", "support_hold"),
            _retest_state(path, observation) is RetestState.RETEST_UNAVAILABLE,
            ("support_resistance",),
        ),
        ConfirmationScore(
            "RISK_CONFIRMATION_SCORE",
            risk,
            ("trade_plan_quality", "stop_distance_pct", "volatility_proxy"),
            observation.underlying.stop_distance_pct is None,
            ("trade_plan_quality",),
        ),
        ConfirmationScore(
            "CONFIRMED_ENTRY_SCORE",
            _bounded_mean((price, participation, retest, risk)),
            ("price", "participation", "retest", "risk"),
            False,
            (
                "opportunity_quality_score",
                "entry_trigger_score",
                "risk_confirmation_score",
            ),
        ),
    )


def _participation_sequences(
    paths: Sequence[OpportunityPath],
    definition: DirectionalOutcomeDefinition,
) -> tuple[ParticipationSequenceResult, ...]:
    rows: list[ParticipationSequenceResult] = []
    for sequence in ParticipationSequence:
        matched = [
            (path, observation)
            for path in paths
            for observation in path.observations
            if _sequence_matches(path, observation, sequence)
        ]
        successes = sum(_is_success(item, definition) for _, item in matched)
        setups = Counter(path.identity.setup_family for path, _ in matched)
        regimes = Counter(path.identity.regime_context for path, _ in matched)
        rows.append(
            ParticipationSequenceResult(
                sequence=sequence,
                occurrence_count=len(matched),
                success_precision=_safe_ratio(successes, len(matched)),
                failure_precision=_safe_ratio(len(matched) - successes, len(matched)),
                effective_sample_size=effective_sample_size(
                    tuple(item.underlying for _, item in matched)
                ),
                setup_distribution=tuple(sorted(setups.items())),
                regime_distribution=tuple(sorted(regimes.items())),
                average_entry_delay=_mean(
                    float((item.observed_at - path.identity.first_detection_date).days)
                    for path, item in matched
                ),
                missed_move=_mean(_missed_move(path, item) for path, item in matched),
                expectancy=_mean(item.underlying.forward_return for _, item in matched),
                mae=_mean(item.underlying.max_adverse_excursion for _, item in matched),
                mfe=_mean(
                    item.underlying.max_favorable_excursion for _, item in matched
                ),
            )
        )
    return tuple(rows)


def _sequence_matches(
    path: OpportunityPath,
    observation: OpportunityObservation,
    sequence: ParticipationSequence,
) -> bool:
    index = path.observations.index(observation)
    previous = path.observations[index - 1] if index > 0 else None
    volume = _feature(observation, "volume") or 0.0
    rs = _feature(observation, "relative_strength") or 0.0
    previous_volume = 0.0 if previous is None else (_feature(previous, "volume") or 0.0)
    if sequence is ParticipationSequence.CONTRACTION_THEN_EXPANSION:
        return previous is not None and previous_volume <= 0.45 and volume >= 0.60
    if sequence is ParticipationSequence.ACCUMULATION_THEN_BREAKOUT:
        return volume >= 0.60 and observation.opportunity_quality_score >= 0.60
    if sequence is ParticipationSequence.BREAKOUT_THEN_LOW_VOLUME_RETEST:
        return _retest_state(path, observation) is RetestState.CONTROLLED_RETEST
    if sequence is ParticipationSequence.BREAKOUT_VOLUME_PERSISTENCE:
        return previous is not None and previous_volume >= 0.55 and volume >= 0.55
    if sequence is ParticipationSequence.HIGH_VOLUME_ADVANCE_LOW_VOLUME_PULLBACK:
        return previous is not None and previous_volume >= 0.60 and volume <= 0.50
    if sequence is ParticipationSequence.RS_BREAKOUT_WITH_VOLUME_CONFIRMATION:
        return rs >= 0.60 and volume >= 0.60
    if sequence is ParticipationSequence.SUPPORT_HOLD_WITH_RENEWED_DEMAND:
        return _retest_state(path, observation) is RetestState.SUPPORT_HOLD_CONFIRMED
    return False


def _retest_state(
    path: OpportunityPath,
    observation: OpportunityObservation,
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


def _cancellation_reasons(
    path: OpportunityPath,
    observation: OpportunityObservation,
) -> tuple[CancellationReason, ...]:
    index = path.observations.index(observation)
    later = path.observations[index + 1 : index + 2]
    if not later:
        return ()
    next_observation = later[0]
    reasons: list[CancellationReason] = []
    if (
        next_observation.opportunity_quality_score
        < observation.opportunity_quality_score - 0.12
    ):
        reasons.append(CancellationReason.PRICE_CONFIRMATION_LOST)
    if (_feature(next_observation, "volume") or 0.0) < 0.35:
        reasons.append(CancellationReason.VOLUME_CONFIRMATION_LOST)
    if "BEAR" in next_observation.regime.upper():
        reasons.append(CancellationReason.REGIME_TURNED_HOSTILE)
    if (_feature(next_observation, "relative_strength") or 0.0) < 0.35:
        reasons.append(CancellationReason.RS_DETERIORATED)
    if next_observation.entry_trigger_score < observation.entry_trigger_score - 0.12:
        reasons.append(CancellationReason.TRADE_PLAN_DEGRADED)
    if next_observation.lifecycle_state.value == "INVALIDATED":
        reasons.append(CancellationReason.SETUP_INVALIDATED)
    if (next_observation.underlying.max_adverse_excursion or 0.0) < -0.08:
        reasons.append(CancellationReason.VOLATILITY_SPIKED)
    return tuple(dict.fromkeys(reasons))


def _breakout_classification(
    path: OpportunityPath,
    observation: OpportunityObservation,
) -> BreakoutClassification:
    volume = _feature(observation, "volume") or 0.0
    breakout = _feature(observation, "breakout_confirmation") or 0.0
    if not _target_hit(observation) and _stop_hit(observation):
        return BreakoutClassification.FAILED_BREAKOUT
    if volume >= 0.60 and breakout >= 0.60 and _target_hit(observation):
        return BreakoutClassification.CLEAN_BREAKOUT
    if _retest_state(path, observation) in {
        RetestState.CONTROLLED_RETEST,
        RetestState.SUPPORT_HOLD_CONFIRMED,
    }:
        return BreakoutClassification.BREAKOUT_THEN_RETEST
    if volume < 0.45:
        return BreakoutClassification.UNCONFIRMED_BREAKOUT
    if breakout < 0.50:
        return BreakoutClassification.WEAK_BREAKOUT
    return BreakoutClassification.AMBIGUOUS_BREAKOUT


def _ordered_addition(
    candidates: Sequence[ConfirmationCandidateEvaluation],
) -> tuple[ConfirmationCandidateEvaluation, ...]:
    order = (
        ConfirmationRuleName.FROZEN_FULL_STACK_PLUS_TIMING,
        ConfirmationRuleName.PRICE_CONFIRMATION_RULE,
        ConfirmationRuleName.VOLUME_PARTICIPATION_RULE,
        ConfirmationRuleName.PARTICIPATION_SEQUENCE_RULE,
        ConfirmationRuleName.RS_CONFIRMATION_RULE,
        ConfirmationRuleName.RISK_CONFIRMATION_RULE,
        ConfirmationRuleName.RETEST_HOLD_RULE,
        ConfirmationRuleName.PERSISTENCE_CONFIRMATION_RULE,
        ConfirmationRuleName.CANCELLATION_AWARE_RULE,
        ConfirmationRuleName.MULTI_STAGE_CONFIRMATION_RULE,
    )
    by_rule = {item.rule: item for item in candidates}
    return tuple(by_rule[item] for item in order if item in by_rule)


def _ablation(
    candidates: Sequence[ConfirmationCandidateEvaluation],
    best: ConfirmationCandidateEvaluation,
) -> tuple[ConfirmationCandidateEvaluation, ...]:
    return tuple(
        item
        for item in candidates
        if item.rule is not best.rule
        and set(item.retained_groups).issubset(set(best.retained_groups))
    )


def _pareto(
    candidates: Sequence[ConfirmationCandidateEvaluation],
) -> tuple[ConfirmationCandidateEvaluation, ...]:
    return tuple(
        sorted(
            (
                candidate
                for candidate in candidates
                if not any(_dominates(other, candidate) for other in candidates)
            ),
            key=lambda item: (
                -(item.precision or 0.0),
                -item.triggered_opportunities,
                item.average_delay or 999.0,
                item.rule.value,
            ),
        )
    )


def _dominates(
    candidate: ConfirmationCandidateEvaluation,
    other: ConfirmationCandidateEvaluation,
) -> bool:
    if candidate is other:
        return False
    return (
        (candidate.precision or 0.0) >= (other.precision or 0.0)
        and (candidate.opportunity_coverage or 0.0)
        >= (other.opportunity_coverage or 0.0)
        and (candidate.expectancy or -999.0) >= (other.expectancy or -999.0)
        and (candidate.average_delay or 999.0) <= (other.average_delay or 999.0)
        and (
            (candidate.precision or 0.0) > (other.precision or 0.0)
            or (candidate.opportunity_coverage or 0.0)
            > (other.opportunity_coverage or 0.0)
            or (candidate.expectancy or -999.0) > (other.expectancy or -999.0)
            or (candidate.average_delay or 999.0) < (other.average_delay or 999.0)
        )
    )


def _best_confirmed_rule(
    candidates: Sequence[ConfirmationCandidateEvaluation],
    baseline: ConfirmationCandidateEvaluation,
) -> ConfirmationCandidateEvaluation:
    eligible = [item for item in candidates if item.triggered_opportunities >= 5]
    return max(
        eligible or [baseline],
        key=lambda item: (
            item.precision or 0.0,
            item.cost_adjusted_expectancy or -999.0,
            item.triggered_opportunities,
            -(item.average_delay or 999.0),
        ),
    )


def _best_specialist_rule(
    candidates: Sequence[ConfirmationCandidateEvaluation],
    baseline: ConfirmationCandidateEvaluation,
) -> ConfirmationCandidateEvaluation:
    eligible = [item for item in candidates if item.precision is not None]
    return max(
        eligible or [baseline],
        key=lambda item: (
            item.precision or 0.0,
            item.effective_sample_size,
            item.expectancy or -999.0,
        ),
    )


def _rule_groups(rule: ConfirmationRuleName) -> tuple[ConfirmationGroup, ...]:
    mapping = {
        ConfirmationRuleName.FROZEN_FULL_STACK_PLUS_TIMING: (),
        ConfirmationRuleName.PRICE_CONFIRMATION_RULE: (
            ConfirmationGroup.PRICE_CONFIRMATION,
        ),
        ConfirmationRuleName.VOLUME_PARTICIPATION_RULE: (
            ConfirmationGroup.VOLUME_CONFIRMATION,
            ConfirmationGroup.PARTICIPATION_CONFIRMATION,
        ),
        ConfirmationRuleName.PARTICIPATION_SEQUENCE_RULE: (
            ConfirmationGroup.PARTICIPATION_CONFIRMATION,
        ),
        ConfirmationRuleName.RS_CONFIRMATION_RULE: (
            ConfirmationGroup.RELATIVE_STRENGTH_CONFIRMATION,
        ),
        ConfirmationRuleName.RISK_CONFIRMATION_RULE: (
            ConfirmationGroup.RISK_CONFIRMATION,
        ),
        ConfirmationRuleName.RETEST_HOLD_RULE: (ConfirmationGroup.RETEST_QUALITY,),
        ConfirmationRuleName.PERSISTENCE_CONFIRMATION_RULE: (
            ConfirmationGroup.PERSISTENCE,
        ),
        ConfirmationRuleName.CANCELLATION_AWARE_RULE: (ConfirmationGroup.CANCELLATION,),
        ConfirmationRuleName.MULTI_STAGE_CONFIRMATION_RULE: (
            ConfirmationGroup.PRICE_CONFIRMATION,
            ConfirmationGroup.PARTICIPATION_CONFIRMATION,
            ConfirmationGroup.RISK_CONFIRMATION,
            ConfirmationGroup.CANCELLATION,
        ),
    }
    return mapping[rule]


def _rule_description(rule: ConfirmationRuleName) -> str:
    return rule.value.lower().replace("_", " ")


def _primary_bottleneck(
    failures: Sequence[TriggerFailureAttribution],
    best: ConfirmationCandidateEvaluation,
    baseline: ConfirmationCandidateEvaluation,
) -> ConfirmationBottleneck:
    if len(failures) < 5:
        return ConfirmationBottleneck.INSUFFICIENT_EVIDENCE
    cause = Counter(item.primary_cause for item in failures).most_common(1)[0][0]
    if cause is TriggerFailureCause.FALSE_BREAKOUT:
        return ConfirmationBottleneck.FALSE_BREAKOUT_PRIMARY
    if cause is TriggerFailureCause.INSUFFICIENT_VOLUME_CONFIRMATION:
        return ConfirmationBottleneck.PARTICIPATION_CONFIRMATION_PRIMARY
    if cause is TriggerFailureCause.RETEST_FAILED:
        return ConfirmationBottleneck.RETEST_QUALITY_PRIMARY
    if cause is TriggerFailureCause.WEAK_RELATIVE_STRENGTH:
        return ConfirmationBottleneck.RELATIVE_STRENGTH_CONFIRMATION_PRIMARY
    if cause is TriggerFailureCause.HOSTILE_MARKET_REGIME:
        return ConfirmationBottleneck.REGIME_CONFIRMATION_PRIMARY
    if cause in {TriggerFailureCause.STOP_TOO_TIGHT, TriggerFailureCause.STOP_TOO_WIDE}:
        return ConfirmationBottleneck.STOP_DESIGN_PRIMARY
    if (best.precision or 0.0) <= (baseline.precision or 0.0):
        return ConfirmationBottleneck.DIRECTIONAL_QUALITY_PRIMARY
    return ConfirmationBottleneck.MULTIPLE_CONFIRMATION_BOTTLENECKS


def _final_conclusion(
    best: ConfirmationCandidateEvaluation,
    baseline: ConfirmationCandidateEvaluation,
) -> ConfirmationConclusion:
    precision = best.precision or 0.0
    if best.triggered_opportunities < 5:
        return ConfirmationConclusion.MORE_DATA_REQUIRED
    if precision >= 0.70 and best.effective_sample_size >= 100:
        return ConfirmationConclusion.STABLE_70_PERCENT_CONFIRMED_TRIGGER_FOUND
    if precision >= 0.60 and best.effective_sample_size >= 100:
        return ConfirmationConclusion.STABLE_60_PERCENT_CONFIRMED_TRIGGER_FOUND
    if precision >= 0.70:
        return ConfirmationConclusion.HIGH_PRECISION_LOW_COVERAGE_ONLY
    if precision > (baseline.precision or 0.0) + 0.03:
        if ConfirmationGroup.PARTICIPATION_CONFIRMATION in best.retained_groups:
            return ConfirmationConclusion.PARTICIPATION_SIGNAL_ADDS_VALUE
        if ConfirmationGroup.RETEST_QUALITY in best.retained_groups:
            return ConfirmationConclusion.RETEST_SPECIALIST_TRIGGER_FOUND
        return ConfirmationConclusion.CONFIRMATION_IMPROVEMENT_FOUND
    return ConfirmationConclusion.CURRENT_FULL_STACK_PLUS_TIMING_REMAINS_SUPERIOR


def _is_success(
    observation: OpportunityObservation,
    definition: DirectionalOutcomeDefinition,
) -> bool:
    return (
        label_directional_outcome(observation.underlying, definition)
        is DirectionalLabel.BUY_DIRECTIONAL
    )


def _path_has_success(
    path: OpportunityPath,
    definition: DirectionalOutcomeDefinition,
) -> bool:
    return any(_is_success(item, definition) for item in path.observations)


def _outcome_label(
    observation: OpportunityObservation | None,
    definition: DirectionalOutcomeDefinition,
) -> str:
    if observation is None:
        return "NOT_TRIGGERED"
    return "SUCCESS" if _is_success(observation, definition) else "FAILED"


def _confirmed_outcome_label(
    path: OpportunityPath,
    observation: OpportunityObservation | None,
    definition: DirectionalOutcomeDefinition,
) -> str:
    if observation is None:
        return "NOT_TRIGGERED"
    breakout = _breakout_classification(path, observation).value
    outcome = "SUCCESS" if _is_success(observation, definition) else "FAILED"
    return f"{outcome}_{breakout}"


def _direction_failure(
    observation: OpportunityObservation,
    definition: DirectionalOutcomeDefinition,
) -> DirectionFailureClassification:
    if observation.underlying.forward_return is None:
        return DirectionFailureClassification.DATA_UNAVAILABLE
    if _is_success(observation, definition):
        return DirectionFailureClassification.DIRECTION_AMBIGUOUS
    if (observation.underlying.max_favorable_excursion or 0.0) >= 0.04:
        if _stop_hit(observation):
            return DirectionFailureClassification.DIRECTION_RIGHT_BUT_STOP_WRONG
        return DirectionFailureClassification.DIRECTION_RIGHT_BUT_ENTRY_WRONG
    if observation.underlying.forward_return > 0:
        return DirectionFailureClassification.DIRECTION_RIGHT_BUT_HORIZON_WRONG
    return DirectionFailureClassification.DIRECTION_WRONG


def _preventability(cause: TriggerFailureCause) -> Preventability:
    if cause in {
        TriggerFailureCause.INSUFFICIENT_VOLUME_CONFIRMATION,
        TriggerFailureCause.WEAK_RELATIVE_STRENGTH,
        TriggerFailureCause.HOSTILE_MARKET_REGIME,
        TriggerFailureCause.ENTRY_TOO_EARLY,
        TriggerFailureCause.ENTRY_TOO_EXTENDED,
        TriggerFailureCause.STOP_TOO_TIGHT,
        TriggerFailureCause.STOP_TOO_WIDE,
    }:
        return Preventability.PREVENTABLE_WITH_EXISTING_EVIDENCE
    if cause in {
        TriggerFailureCause.FALSE_BREAKOUT,
        TriggerFailureCause.DISTRIBUTION_AFTER_TRIGGER,
        TriggerFailureCause.EVENT_SHOCK,
    }:
        return Preventability.PREVENTABLE_WITH_NEW_POINT_IN_TIME_FEATURE
    if cause in {
        TriggerFailureCause.REWARD_RISK_COLLAPSED,
        TriggerFailureCause.GAP_THROUGH_STOP,
    }:
        return Preventability.STOP_OR_TRADE_PLAN_PRIMARY
    if cause is TriggerFailureCause.OPPORTUNITY_GROUPING_ERROR:
        return Preventability.OPPORTUNITY_GROUPING_PRIMARY
    if cause is TriggerFailureCause.LABEL_AMBIGUITY:
        return Preventability.LABEL_OR_OUTCOME_AMBIGUITY
    if cause is TriggerFailureCause.DATA_QUALITY_FAILURE:
        return Preventability.INSUFFICIENT_EVIDENCE
    return Preventability.NOT_REASONABLY_PREVENTABLE


def _grouping_quality(path: OpportunityPath) -> GroupingQuality:
    if path.observation_count < 2:
        return GroupingQuality.INSUFFICIENT_OBSERVATIONS
    setups = {item.setup for item in path.observations}
    regimes = {item.regime for item in path.observations}
    if len(setups) > 1:
        return GroupingQuality.DISTINCT_SETUPS_MERGED
    if len(regimes) > 2:
        return GroupingQuality.RESET_EVENT_MISSED
    if path.calendar_duration_days > 90:
        return GroupingQuality.GROUPING_AMBIGUOUS
    return GroupingQuality.GROUPING_VALID


def _evidence_available(
    path: OpportunityPath,
    observation: OpportunityObservation,
) -> tuple[str, ...]:
    return tuple(
        item.name
        for item in _confirmation_scores(path, observation)
        if not item.missing
    )


def _evidence_after_trigger(
    path: OpportunityPath,
    observation: OpportunityObservation,
) -> tuple[str, ...]:
    reasons = _cancellation_reasons(path, observation)
    return tuple(item.value for item in reasons)


def _participation_proxies(
    path: OpportunityPath,
    observation: OpportunityObservation,
) -> tuple[str, ...]:
    proxies: list[str] = []
    volume = _feature(observation, "volume") or 0.0
    rs = _feature(observation, "relative_strength") or 0.0
    if volume >= 0.60 and observation.opportunity_quality_score >= 0.60:
        proxies.append("high relative volume on advancing setup")
    if _sequence_score(path, observation) >= 0.60:
        proxies.append("positive price-volume participation sequence")
    if (
        volume <= 0.45
        and _retest_state(path, observation) is RetestState.CONTROLLED_RETEST
    ):
        proxies.append("low-volume retest")
    if volume >= 0.55 and rs >= 0.55:
        proxies.append("RS confirmation with volume")
    return tuple(proxies)


def _sequence_score(
    path: OpportunityPath,
    observation: OpportunityObservation,
) -> float:
    matches = sum(
        _sequence_matches(path, observation, sequence)
        for sequence in ParticipationSequence
    )
    return min(1.0, matches / 3.0)


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


def _persistence_state(
    path: OpportunityPath,
    observation: OpportunityObservation,
) -> str:
    index = path.observations.index(observation)
    if index == 0:
        return "FIRST_OBSERVATION"
    previous = path.observations[index - 1]
    if (
        previous.opportunity_quality_score >= 0.60
        and previous.entry_trigger_score >= 0.55
    ):
        return "PERSISTENT"
    return "NOT_PERSISTENT"


def _feature(observation: OpportunityObservation, key: str) -> float | None:
    values = dict(observation.underlying.feature_values)
    return values.get(key) or values.get(key.replace("_", "-"))


def _score(scores: Sequence[ConfirmationScore], name: str) -> float:
    for score in scores:
        if score.name == name:
            return score.score
    return 0.0


def _missed_move(
    path: OpportunityPath,
    observation: OpportunityObservation,
) -> float | None:
    first = path.observations[0].price
    current = observation.price
    if first is None or current is None or first <= 0:
        return None
    return max(0.0, (current - first) / first)


def _target_hit(observation: OpportunityObservation) -> bool:
    return bool(
        observation.underlying.upside_barrier_day is not None
        or (
            observation.underlying.max_favorable_excursion is not None
            and observation.underlying.max_favorable_excursion >= 0.04
        )
    )


def _stop_hit(observation: OpportunityObservation) -> bool:
    return bool(
        observation.underlying.downside_barrier_day is not None
        or (
            observation.underlying.max_adverse_excursion is not None
            and observation.underlying.max_adverse_excursion <= -0.03
        )
    )


def _fold_precision(
    triggered: Sequence[tuple[OpportunityPath, OpportunityObservation]],
    definition: DirectionalOutcomeDefinition,
    mode: str,
) -> float | None:
    buckets: dict[int, list[OpportunityObservation]] = {}
    for _, observation in triggered:
        buckets.setdefault(observation.observed_at.year, []).append(observation)
    values = [
        _safe_ratio(
            sum(_is_success(item, definition) for item in observations),
            len(observations),
        )
        for observations in buckets.values()
    ]
    usable = [item for item in values if item is not None]
    if not usable:
        return None
    return max(usable) if mode == "best" else min(usable)


def _fold_dispersion(
    triggered: Sequence[tuple[OpportunityPath, OpportunityObservation]],
    definition: DirectionalOutcomeDefinition,
) -> float | None:
    buckets: dict[int, list[OpportunityObservation]] = {}
    for _, observation in triggered:
        buckets.setdefault(observation.observed_at.year, []).append(observation)
    values = [
        _safe_ratio(
            sum(_is_success(item, definition) for item in observations),
            len(observations),
        )
        for observations in buckets.values()
    ]
    usable = [item for item in values if item is not None]
    if len(usable) < 2:
        return None
    return pstdev(usable)


def _concentration(values: Iterable[str]) -> float:
    counter = Counter(values)
    if not counter:
        return 0.0
    return max(counter.values()) / sum(counter.values())


def _concentration_status(evaluation: ConfirmationCandidateEvaluation) -> str:
    if (
        max(
            evaluation.year_concentration,
            evaluation.setup_concentration,
            evaluation.symbol_concentration,
            evaluation.sector_concentration,
        )
        > 0.65
    ):
        return "CONCENTRATED"
    return "ACCEPTABLE"


def _tier(
    precision: float | None,
    count: int,
    expectancy: float | None,
    worst_fold: float | None,
) -> str:
    if precision is None:
        return "UNAVAILABLE"
    if (
        precision >= 0.70
        and count >= 100
        and (expectancy or 0.0) > 0
        and (worst_fold or 0.0) >= 0.55
    ):
        return "TIER_A"
    if precision >= 0.60 and count >= 100 and (expectancy or 0.0) > 0:
        return "TIER_B"
    if precision >= 0.55 and (expectancy or 0.0) > 0:
        return "TIER_C"
    if precision >= 0.70:
        return "TIER_D_SPECIALIST"
    return "RESEARCH_ONLY"


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


def _median(values: Sequence[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


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


def _render_pairs(values: Sequence[tuple[str, int]]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={count}" for key, count in values)


def _count_lines(counter: Counter[str]) -> tuple[str, ...]:
    if not counter:
        return ("- none",)
    return tuple(f"- {key}: {value}" for key, value in sorted(counter.items()))


def _frontier_lines(
    evaluations: Iterable[ConfirmationCandidateEvaluation],
) -> tuple[str, ...]:
    rows = tuple(evaluations)
    if not rows:
        return ("- none",)
    return tuple(
        "- "
        f"{item.rule.value}: precision {_pct(item.precision)}, "
        f"coverage {_pct(item.opportunity_coverage)}, "
        f"signals {item.triggered_opportunities}, "
        f"delay {_num(item.average_delay)}d, "
        f"expectancy {_pct(item.expectancy)}, "
        f"tier {item.tier}"
        for item in rows
    )


def _sequence_lines(
    sequences: Sequence[ParticipationSequenceResult],
) -> tuple[str, ...]:
    if not sequences:
        return ("- none",)
    lines: list[str] = []
    for item in sequences:
        delay = (
            "unavailable"
            if item.average_entry_delay is None
            else f"{item.average_entry_delay:.2f}d"
        )
        lines.append(
            "- "
            f"{item.sequence.value}: n={item.occurrence_count}, "
            f"success {_pct(item.success_precision)}, "
            f"expectancy {_pct(item.expectancy)}, delay {delay}"
        )
    return tuple(lines)


__all__ = [
    "BreakoutClassification",
    "CancellationReason",
    "ConfirmationBottleneck",
    "ConfirmationCandidateEvaluation",
    "ConfirmationConclusion",
    "ConfirmationGroup",
    "ConfirmationIntelligenceReport",
    "ConfirmationOpportunityRecord",
    "ConfirmationRuleName",
    "ConfirmationScore",
    "DirectionFailureClassification",
    "GroupingQuality",
    "ParticipationSequence",
    "ParticipationSequenceResult",
    "Preventability",
    "RetestState",
    "TriggerFailureAttribution",
    "TriggerFailureCause",
    "build_confirmation_intelligence_report",
    "export_confirmation_intelligence_csv",
    "export_confirmation_intelligence_json",
    "group_confirmation_report",
    "render_confirmation_frontier",
    "render_confirmation_intelligence_report",
    "render_false_breakout_audit",
    "render_participation_confirmation",
    "render_retest_quality_audit",
    "render_trigger_cancellation_audit",
    "render_trigger_failure_attribution",
    "render_trigger_persistence_audit",
]
