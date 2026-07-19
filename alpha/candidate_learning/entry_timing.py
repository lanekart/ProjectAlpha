from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from statistics import median

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_HUNDRED = Decimal("100")


class EntryTimingState(StrEnum):
    SETUP_FORMING = "SETUP_FORMING"
    EARLY_ENTRY = "EARLY_ENTRY"
    AGGRESSIVE_ENTRY = "AGGRESSIVE_ENTRY"
    PREFERRED_ENTRY = "PREFERRED_ENTRY"
    CONFIRMATION_ENTRY = "CONFIRMATION_ENTRY"
    EXTENDED_ENTRY = "EXTENDED_ENTRY"
    LATE_ENTRY = "LATE_ENTRY"
    INVALID_ENTRY = "INVALID_ENTRY"
    ENTRY_UNAVAILABLE = "ENTRY_UNAVAILABLE"


class PriceExtensionState(StrEnum):
    NOT_EXTENDED = "NOT_EXTENDED"
    MILDLY_EXTENDED = "MILDLY_EXTENDED"
    MODERATELY_EXTENDED = "MODERATELY_EXTENDED"
    SEVERELY_EXTENDED = "SEVERELY_EXTENDED"
    EXTENSION_UNAVAILABLE = "EXTENSION_UNAVAILABLE"


class VolumeConfirmationState(StrEnum):
    CONFIRMED_EXPANSION = "CONFIRMED_EXPANSION"
    WEAK_CONFIRMATION = "WEAK_CONFIRMATION"
    PULLBACK_CONTRACTION = "PULLBACK_CONTRACTION"
    EXHAUSTION_RISK = "EXHAUSTION_RISK"
    ABNORMAL_VOLUME = "ABNORMAL_VOLUME"
    UNAVAILABLE = "UNAVAILABLE"


class RelativeStrengthTimingState(StrEnum):
    OUTPERFORMING = "OUTPERFORMING"
    NEUTRAL = "NEUTRAL"
    UNDERPERFORMING = "UNDERPERFORMING"
    UNAVAILABLE = "UNAVAILABLE"


class TimingConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TimingDataCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class EntryTimingReasonCode(StrEnum):
    INSIDE_PREFERRED_ZONE = "INSIDE_PREFERRED_ZONE"
    CONFIRMATION_PRESENT = "CONFIRMATION_PRESENT"
    NEAR_SUPPORT = "NEAR_SUPPORT"
    FAVOURABLE_STOP_DISTANCE = "FAVOURABLE_STOP_DISTANCE"
    FAVOURABLE_REWARD_RISK = "FAVOURABLE_REWARD_RISK"
    PRICE_EXTENDED = "PRICE_EXTENDED"
    SETUP_STALE = "SETUP_STALE"
    STRUCTURE_INVALID = "STRUCTURE_INVALID"
    SETUP_STILL_FORMING = "SETUP_STILL_FORMING"
    DATA_MISSING = "DATA_MISSING"
    VOLUME_CONFIRMS = "VOLUME_CONFIRMS"
    RELATIVE_STRENGTH_SUPPORTS = "RELATIVE_STRENGTH_SUPPORTS"


class EntryTimingWarningCode(StrEnum):
    EXCESSIVE_STOP_DISTANCE = "EXCESSIVE_STOP_DISTANCE"
    WEAK_REWARD_RISK = "WEAK_REWARD_RISK"
    PRICE_EXTENSION = "PRICE_EXTENSION"
    NEAR_RESISTANCE = "NEAR_RESISTANCE"
    WEAK_VOLUME_CONFIRMATION = "WEAK_VOLUME_CONFIRMATION"
    UNDERPERFORMING_RELATIVE_STRENGTH = "UNDERPERFORMING_RELATIVE_STRENGTH"
    MISSING_STRUCTURAL_REFERENCE = "MISSING_STRUCTURAL_REFERENCE"
    LOW_SAMPLE_SIZE = "LOW_SAMPLE_SIZE"


class EntryTimingConclusion(StrEnum):
    ENTRY_TIMING_SEPARATES_OUTCOMES = "ENTRY_TIMING_SEPARATES_OUTCOMES"
    ENTRY_TIMING_WEAKLY_SEPARATES_OUTCOMES = "ENTRY_TIMING_WEAKLY_SEPARATES_OUTCOMES"
    EXTENDED_ENTRIES_PRIMARY_PROBLEM = "EXTENDED_ENTRIES_PRIMARY_PROBLEM"
    LATE_ENTRIES_PRIMARY_PROBLEM = "LATE_ENTRIES_PRIMARY_PROBLEM"
    ACCEPTABLE_TIMING_BUT_OTHER_GATES_FAIL = "ACCEPTABLE_TIMING_BUT_OTHER_GATES_FAIL"
    ENTRY_TIMING_MODEL_NEEDS_REFINEMENT = "ENTRY_TIMING_MODEL_NEEDS_REFINEMENT"
    DATA_COVERAGE_INSUFFICIENT = "DATA_COVERAGE_INSUFFICIENT"
    MULTIPLE_TIMING_BOTTLENECKS = "MULTIPLE_TIMING_BOTTLENECKS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class EntryTimingConfig:
    preferred_support_distance_pct: Decimal = Decimal("3")
    early_support_distance_pct: Decimal = Decimal("5")
    extended_support_distance_pct: Decimal = Decimal("10")
    late_support_distance_pct: Decimal = Decimal("20")
    maximum_preferred_stop_pct: Decimal = Decimal("10")
    late_stop_distance_pct: Decimal = Decimal("18")
    minimum_preferred_reward_risk: Decimal = Decimal("2")
    weak_reward_risk: Decimal = Decimal("1.2")
    mild_extension_atr: Decimal = Decimal("1.5")
    moderate_extension_atr: Decimal = Decimal("3")
    severe_extension_atr: Decimal = Decimal("5")
    stale_setup_bars: int = 20
    minimum_completed_outcomes_per_state: int = 10
    minimum_symbols_per_state: int = 3
    minimum_replay_dates_per_state: int = 3
    timing_score_bucket_size: int = 10


@dataclass(frozen=True, slots=True)
class EntryTimingInput:
    symbol: str
    evaluation_date: date
    setup_type: str | None
    current_price: Decimal | None
    reference_entry: Decimal | None
    structural_support: Decimal | None
    structural_resistance: Decimal | None
    breakout_level: Decimal | None
    retracement_low: Decimal | None
    retracement_high: Decimal | None
    recent_swing_low: Decimal | None
    recent_swing_high: Decimal | None
    dma_20: Decimal | None
    dma_50: Decimal | None
    dma_200: Decimal | None
    atr: Decimal | None
    stop_loss: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    market_regime: str | None
    sector_regime: str | None
    setup_age_bars: int | None
    volume_confirmation_state: VolumeConfirmationState
    relative_strength_state: RelativeStrengthTimingState


@dataclass(frozen=True, slots=True)
class EntryTimingAssessment:
    symbol: str
    evaluation_date: date
    setup_type: str | None
    entry_state: EntryTimingState
    price_extension_state: PriceExtensionState
    current_price: Decimal | None
    reference_entry: Decimal | None
    structural_support: Decimal | None
    structural_resistance: Decimal | None
    breakout_level: Decimal | None
    retracement_low: Decimal | None
    retracement_high: Decimal | None
    recent_swing_low: Decimal | None
    recent_swing_high: Decimal | None
    dma_20: Decimal | None
    dma_50: Decimal | None
    dma_200: Decimal | None
    atr: Decimal | None
    atr_percent: Decimal | None
    distance_from_support_pct: Decimal | None
    distance_from_support_atr: Decimal | None
    distance_from_breakout_pct: Decimal | None
    distance_from_breakout_atr: Decimal | None
    distance_from_20dma_pct: Decimal | None
    distance_from_50dma_pct: Decimal | None
    distance_from_recent_swing_low_pct: Decimal | None
    distance_to_resistance_pct: Decimal | None
    remaining_upside_to_target_1_pct: Decimal | None
    stop_distance_pct: Decimal | None
    reward_risk: Decimal | None
    volume_confirmation_state: VolumeConfirmationState
    relative_strength_state: RelativeStrengthTimingState
    market_regime: str | None
    sector_regime: str | None
    setup_age_bars: int | None
    timing_score: Decimal
    timing_confidence: TimingConfidence
    timing_reasons: tuple[EntryTimingReasonCode, ...]
    timing_warnings: tuple[EntryTimingWarningCode, ...]
    data_completeness: TimingDataCompleteness
    actionable_now: bool
    wait_condition: str | None
    invalidation_condition: str | None


@dataclass(frozen=True, slots=True)
class EntryTimingOutcomeRow:
    assessment: EntryTimingAssessment
    candidate_id: str
    approved: bool
    primary_rejection_reason: str | None
    completed_outcome: bool
    profitable: bool
    forward_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    target_1_hit: bool | None
    target_2_hit: bool | None
    stop_hit: bool | None


@dataclass(frozen=True, slots=True)
class EntryTimingStatePerformance:
    entry_state: EntryTimingState
    candidate_count: int
    completed_outcomes: int
    profitable_outcomes: int
    unsuccessful_outcomes: int
    success_rate: Decimal | None
    average_forward_return: Decimal | None
    median_forward_return: Decimal | None
    average_mfe: Decimal | None
    average_mae: Decimal | None
    target_1_hit_rate: Decimal | None
    target_2_hit_rate: Decimal | None
    stop_hit_rate: Decimal | None
    invalidation_hit_rate: Decimal | None
    average_reward_risk: Decimal | None
    average_stop_distance: Decimal | None
    average_timing_score: Decimal | None
    data_completeness: TimingDataCompleteness
    evidence_warning: str | None


@dataclass(frozen=True, slots=True)
class TimingFeatureComparison:
    feature: str
    winner_count: int
    loser_count: int
    winner_mean: Decimal | None
    loser_mean: Decimal | None
    winner_median: Decimal | None
    loser_median: Decimal | None
    winner_range: tuple[Decimal | None, Decimal | None]
    loser_range: tuple[Decimal | None, Decimal | None]
    missing_count: int
    effect_direction: str
    evidence_warning: str | None


@dataclass(frozen=True, slots=True)
class EntryTimingDecision:
    conclusion: EntryTimingConclusion
    supporting_metrics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EntryTimingReplayReport:
    rows: tuple[EntryTimingOutcomeRow, ...]
    state_performance: tuple[EntryTimingStatePerformance, ...]
    winner_loser_comparison: tuple[TimingFeatureComparison, ...]
    profitable_rejection_rows: tuple[EntryTimingOutcomeRow, ...]
    conclusion: EntryTimingDecision
    candidates_evaluated: int
    completed_outcomes: int
    approval_count_before: int
    approval_count_after: int


class EntryTimingIntelligenceEngine:
    def __init__(self, config: EntryTimingConfig | None = None) -> None:
        self.config = config or EntryTimingConfig()

    def assess(self, entry: EntryTimingInput) -> EntryTimingAssessment:
        distances = _distances(entry)
        data_completeness = _data_completeness(entry)
        extension_state = _extension_state(distances, self.config)
        reasons: list[EntryTimingReasonCode] = []
        warnings: list[EntryTimingWarningCode] = []
        state = self._state(entry, distances, extension_state, reasons, warnings)
        score = self._score(entry, distances, extension_state, state)
        reasons.extend(_score_reasons(entry, distances))
        warnings.extend(_score_warnings(entry, distances, extension_state, self.config))
        confidence = _confidence(data_completeness, entry)
        actionable = state in {
            EntryTimingState.AGGRESSIVE_ENTRY,
            EntryTimingState.PREFERRED_ENTRY,
            EntryTimingState.CONFIRMATION_ENTRY,
        }
        return EntryTimingAssessment(
            symbol=entry.symbol.strip().upper(),
            evaluation_date=entry.evaluation_date,
            setup_type=entry.setup_type,
            entry_state=state,
            price_extension_state=extension_state,
            current_price=entry.current_price,
            reference_entry=entry.reference_entry,
            structural_support=entry.structural_support,
            structural_resistance=entry.structural_resistance,
            breakout_level=entry.breakout_level,
            retracement_low=entry.retracement_low,
            retracement_high=entry.retracement_high,
            recent_swing_low=entry.recent_swing_low,
            recent_swing_high=entry.recent_swing_high,
            dma_20=entry.dma_20,
            dma_50=entry.dma_50,
            dma_200=entry.dma_200,
            atr=entry.atr,
            atr_percent=distances.atr_percent,
            distance_from_support_pct=distances.support_pct,
            distance_from_support_atr=distances.support_atr,
            distance_from_breakout_pct=distances.breakout_pct,
            distance_from_breakout_atr=distances.breakout_atr,
            distance_from_20dma_pct=distances.dma20_pct,
            distance_from_50dma_pct=distances.dma50_pct,
            distance_from_recent_swing_low_pct=distances.swing_low_pct,
            distance_to_resistance_pct=distances.resistance_pct,
            remaining_upside_to_target_1_pct=distances.target1_upside_pct,
            stop_distance_pct=distances.stop_pct,
            reward_risk=distances.reward_risk,
            volume_confirmation_state=entry.volume_confirmation_state,
            relative_strength_state=entry.relative_strength_state,
            market_regime=entry.market_regime,
            sector_regime=entry.sector_regime,
            setup_age_bars=entry.setup_age_bars,
            timing_score=score,
            timing_confidence=confidence,
            timing_reasons=tuple(dict.fromkeys(reasons)),
            timing_warnings=tuple(dict.fromkeys(warnings)),
            data_completeness=data_completeness,
            actionable_now=actionable,
            wait_condition=_wait_condition(state, entry),
            invalidation_condition=_invalidation_condition(entry),
        )

    def assess_record(self, record: CandidateDecisionRecord) -> EntryTimingAssessment:
        return self.assess(_input_from_record(record))

    def assess_candidate(
        self,
        candidate: object,
    ) -> EntryTimingAssessment:
        return self.assess(_input_from_candidate(candidate))

    def _state(
        self,
        entry: EntryTimingInput,
        distances: _Distances,
        extension_state: PriceExtensionState,
        reasons: list[EntryTimingReasonCode],
        warnings: list[EntryTimingWarningCode],
    ) -> EntryTimingState:
        if entry.current_price is None or entry.reference_entry is None:
            reasons.append(EntryTimingReasonCode.DATA_MISSING)
            warnings.append(EntryTimingWarningCode.MISSING_STRUCTURAL_REFERENCE)
            return EntryTimingState.ENTRY_UNAVAILABLE
        if entry.stop_loss is not None and entry.current_price <= entry.stop_loss:
            reasons.append(EntryTimingReasonCode.STRUCTURE_INVALID)
            return EntryTimingState.INVALID_ENTRY
        if entry.structural_support is None and entry.breakout_level is None:
            reasons.append(EntryTimingReasonCode.DATA_MISSING)
            warnings.append(EntryTimingWarningCode.MISSING_STRUCTURAL_REFERENCE)
            return EntryTimingState.ENTRY_UNAVAILABLE
        if _is_late(entry, distances, extension_state, self.config):
            reasons.append(EntryTimingReasonCode.SETUP_STALE)
            warnings.append(EntryTimingWarningCode.EXCESSIVE_STOP_DISTANCE)
            return EntryTimingState.LATE_ENTRY
        if extension_state in {
            PriceExtensionState.MODERATELY_EXTENDED,
            PriceExtensionState.SEVERELY_EXTENDED,
        }:
            reasons.append(EntryTimingReasonCode.PRICE_EXTENDED)
            warnings.append(EntryTimingWarningCode.PRICE_EXTENSION)
            return EntryTimingState.EXTENDED_ENTRY
        setup = (entry.setup_type or "").lower()
        if "breakout" in setup:
            return self._breakout_state(entry, distances, reasons, warnings)
        if "retracement" in setup or "pullback" in setup:
            return self._retracement_state(entry, distances, reasons, warnings)
        if "reversal" in setup:
            return self._reversal_state(entry, distances, reasons, warnings)
        if "continuation" in setup or "momentum" in setup or "trend" in setup:
            return self._continuation_state(entry, distances, reasons, warnings)
        return self._unknown_state(entry, distances, reasons, warnings)

    def _breakout_state(
        self,
        entry: EntryTimingInput,
        distances: _Distances,
        reasons: list[EntryTimingReasonCode],
        warnings: list[EntryTimingWarningCode],
    ) -> EntryTimingState:
        if distances.breakout_pct is None:
            reasons.append(EntryTimingReasonCode.SETUP_STILL_FORMING)
            return EntryTimingState.SETUP_FORMING
        if distances.breakout_pct < _ZERO:
            reasons.append(EntryTimingReasonCode.SETUP_STILL_FORMING)
            return EntryTimingState.SETUP_FORMING
        if _acceptable_entry(distances, self.config):
            if (
                entry.volume_confirmation_state
                is VolumeConfirmationState.CONFIRMED_EXPANSION
            ):
                reasons.append(EntryTimingReasonCode.CONFIRMATION_PRESENT)
                return EntryTimingState.CONFIRMATION_ENTRY
            reasons.append(EntryTimingReasonCode.FAVOURABLE_REWARD_RISK)
            return EntryTimingState.PREFERRED_ENTRY
        warnings.append(EntryTimingWarningCode.WEAK_REWARD_RISK)
        return EntryTimingState.EXTENDED_ENTRY

    def _retracement_state(
        self,
        entry: EntryTimingInput,
        distances: _Distances,
        reasons: list[EntryTimingReasonCode],
        warnings: list[EntryTimingWarningCode],
    ) -> EntryTimingState:
        return self._support_based_state(entry, distances, reasons, warnings)

    def _reversal_state(
        self,
        entry: EntryTimingInput,
        distances: _Distances,
        reasons: list[EntryTimingReasonCode],
        warnings: list[EntryTimingWarningCode],
    ) -> EntryTimingState:
        if (
            entry.volume_confirmation_state
            is VolumeConfirmationState.CONFIRMED_EXPANSION
        ):
            reasons.append(EntryTimingReasonCode.CONFIRMATION_PRESENT)
            if _acceptable_entry(distances, self.config):
                return EntryTimingState.CONFIRMATION_ENTRY
        return self._support_based_state(entry, distances, reasons, warnings)

    def _continuation_state(
        self,
        entry: EntryTimingInput,
        distances: _Distances,
        reasons: list[EntryTimingReasonCode],
        warnings: list[EntryTimingWarningCode],
    ) -> EntryTimingState:
        return self._support_based_state(entry, distances, reasons, warnings)

    def _unknown_state(
        self,
        entry: EntryTimingInput,
        distances: _Distances,
        reasons: list[EntryTimingReasonCode],
        warnings: list[EntryTimingWarningCode],
    ) -> EntryTimingState:
        if _preferred(distances, self.config):
            reasons.append(EntryTimingReasonCode.INSIDE_PREFERRED_ZONE)
            return EntryTimingState.PREFERRED_ENTRY
        if _near_support(distances, self.config):
            reasons.append(EntryTimingReasonCode.NEAR_SUPPORT)
            warnings.append(EntryTimingWarningCode.WEAK_VOLUME_CONFIRMATION)
            return EntryTimingState.EARLY_ENTRY
        reasons.append(EntryTimingReasonCode.SETUP_STILL_FORMING)
        return EntryTimingState.SETUP_FORMING

    def _support_based_state(
        self,
        entry: EntryTimingInput,
        distances: _Distances,
        reasons: list[EntryTimingReasonCode],
        warnings: list[EntryTimingWarningCode],
    ) -> EntryTimingState:
        if _preferred(distances, self.config):
            reasons.append(EntryTimingReasonCode.INSIDE_PREFERRED_ZONE)
            return EntryTimingState.PREFERRED_ENTRY
        if _near_support(distances, self.config):
            if distances.reward_risk is not None and distances.reward_risk >= Decimal(
                "1.5"
            ):
                reasons.append(EntryTimingReasonCode.NEAR_SUPPORT)
                return EntryTimingState.AGGRESSIVE_ENTRY
            reasons.append(EntryTimingReasonCode.NEAR_SUPPORT)
            return EntryTimingState.EARLY_ENTRY
        reasons.append(EntryTimingReasonCode.SETUP_STILL_FORMING)
        warnings.append(EntryTimingWarningCode.MISSING_STRUCTURAL_REFERENCE)
        return EntryTimingState.SETUP_FORMING

    def _score(
        self,
        entry: EntryTimingInput,
        distances: _Distances,
        extension_state: PriceExtensionState,
        state: EntryTimingState,
    ) -> Decimal:
        if state is EntryTimingState.ENTRY_UNAVAILABLE:
            return _ZERO
        if state is EntryTimingState.INVALID_ENTRY:
            return Decimal("5")
        structural = _structural_score(distances, self.config)
        stop = _stop_score(distances.stop_pct)
        reward = _reward_score(distances.reward_risk)
        extension = _extension_score(extension_state)
        volume = _volume_score(entry.volume_confirmation_state)
        relative_strength = _relative_strength_score(entry.relative_strength_state)
        freshness = _freshness_score(entry.setup_age_bars, self.config)
        score = (
            structural * Decimal("0.25")
            + stop * Decimal("0.20")
            + reward * Decimal("0.20")
            + extension * Decimal("0.15")
            + volume * Decimal("0.08")
            + relative_strength * Decimal("0.07")
            + freshness * Decimal("0.05")
        )
        state_penalty = {
            EntryTimingState.LATE_ENTRY: Decimal("25"),
            EntryTimingState.EXTENDED_ENTRY: Decimal("15"),
            EntryTimingState.SETUP_FORMING: Decimal("10"),
            EntryTimingState.EARLY_ENTRY: Decimal("5"),
        }.get(state, _ZERO)
        return max(_ZERO, score - state_penalty).quantize(_TWO)


def build_entry_timing_replay_report(
    *,
    records: tuple[CandidateDecisionRecord, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
    config: EntryTimingConfig | None = None,
) -> EntryTimingReplayReport:
    engine = EntryTimingIntelligenceEngine(config=config)
    outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
    rows = tuple(
        _row_for_record(engine, record, outcome_by_id.get(record.candidate_id))
        for record in records
    )
    state_performance = _state_performance(rows, engine.config)
    comparison = _winner_loser_comparison(rows, engine.config)
    profitable_rejections = tuple(
        row
        for row in rows
        if not row.approved and row.completed_outcome and row.profitable
    )
    decision = _conclusion(rows, state_performance, engine.config)
    approval_count = sum(1 for record in records if record.approved_for_deployment)
    return EntryTimingReplayReport(
        rows=tuple(sorted(rows, key=_row_sort_key)),
        state_performance=state_performance,
        winner_loser_comparison=comparison,
        profitable_rejection_rows=tuple(
            sorted(profitable_rejections, key=_row_sort_key)
        ),
        conclusion=decision,
        candidates_evaluated=len(rows),
        completed_outcomes=sum(1 for row in rows if row.completed_outcome),
        approval_count_before=approval_count,
        approval_count_after=approval_count,
    )


def filter_entry_timing_rows(
    rows: tuple[EntryTimingOutcomeRow, ...],
    *,
    entry_state: str | None = None,
    setup_type: str | None = None,
    market_regime: str | None = None,
    profitable_only: bool = False,
    unprofitable_only: bool = False,
    extended_only: bool = False,
    late_only: bool = False,
    preferred_only: bool = False,
    confirmation_only: bool = False,
    symbol: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    minimum_return: Decimal | None = None,
    minimum_mfe: Decimal | None = None,
) -> tuple[EntryTimingOutcomeRow, ...]:
    result = rows
    if entry_state:
        result = tuple(
            row for row in result if row.assessment.entry_state.value == entry_state
        )
    if setup_type:
        result = tuple(row for row in result if row.assessment.setup_type == setup_type)
    if market_regime:
        result = tuple(
            row for row in result if row.assessment.market_regime == market_regime
        )
    if profitable_only:
        result = tuple(row for row in result if row.profitable)
    if unprofitable_only:
        result = tuple(
            row for row in result if row.completed_outcome and not row.profitable
        )
    if extended_only:
        result = tuple(
            row
            for row in result
            if row.assessment.entry_state is EntryTimingState.EXTENDED_ENTRY
        )
    if late_only:
        result = tuple(
            row
            for row in result
            if row.assessment.entry_state is EntryTimingState.LATE_ENTRY
        )
    if preferred_only:
        result = tuple(
            row
            for row in result
            if row.assessment.entry_state is EntryTimingState.PREFERRED_ENTRY
        )
    if confirmation_only:
        result = tuple(
            row
            for row in result
            if row.assessment.entry_state is EntryTimingState.CONFIRMATION_ENTRY
        )
    if symbol:
        normalized = symbol.strip().upper()
        result = tuple(row for row in result if row.assessment.symbol == normalized)
    if from_date:
        result = tuple(
            row for row in result if row.assessment.evaluation_date >= from_date
        )
    if to_date:
        result = tuple(
            row for row in result if row.assessment.evaluation_date <= to_date
        )
    if minimum_return is not None:
        result = tuple(
            row
            for row in result
            if row.forward_return is not None and row.forward_return >= minimum_return
        )
    if minimum_mfe is not None:
        result = tuple(
            row for row in result if row.mfe is not None and row.mfe >= minimum_mfe
        )
    return tuple(sorted(result, key=_row_sort_key))


def group_entry_timing_report(
    report: EntryTimingReplayReport,
    *,
    group_by: str,
) -> tuple[str, ...]:
    counters: Counter[str] = Counter()
    for row in report.rows:
        assessment = row.assessment
        if group_by == "entry-state":
            counters[assessment.entry_state.value] += 1
        elif group_by == "setup-type":
            counters[assessment.setup_type or "UNKNOWN"] += 1
        elif group_by == "market-regime":
            counters[assessment.market_regime or "UNKNOWN"] += 1
        elif group_by == "sector-regime":
            counters[assessment.sector_regime or "UNKNOWN"] += 1
        elif group_by == "timing-score":
            counters[_score_bucket(assessment.timing_score)] += 1
        elif group_by == "stop-distance":
            bucket = _optional_bucket(assessment.stop_distance_pct, (5, 10, 15, 20))
            counters[bucket] += 1
        elif group_by == "price-extension":
            counters[assessment.price_extension_state.value] += 1
        elif group_by == "volume-confirmation":
            counters[assessment.volume_confirmation_state.value] += 1
        elif group_by == "relative-strength":
            counters[assessment.relative_strength_state.value] += 1
        else:
            raise ValueError(f"Unsupported grouping: {group_by}")
    return tuple(f"- {key}: {value}" for key, value in sorted(counters.items()))


def render_entry_timing_report(report: EntryTimingReplayReport) -> tuple[str, ...]:
    lines = [
        "Entry Timing Intelligence Replay Report",
        f"Candidates Evaluated: {report.candidates_evaluated}",
        f"Completed Outcomes: {report.completed_outcomes}",
        "Approval Count Before: "
        f"{report.approval_count_before} | After: {report.approval_count_after}",
        "",
        "Entry-State Performance:",
        *_performance_lines(report.state_performance),
        "",
        "Winner Versus Loser Timing Comparison:",
        *_comparison_lines(report.winner_loser_comparison),
        "",
        "Profitable-Rejection Timing Analysis:",
        *_profitable_rejection_lines(report.profitable_rejection_rows),
        "",
        f"Conclusion: {report.conclusion.conclusion.value}",
        "Evidence:",
        *[f"- {metric}" for metric in report.conclusion.supporting_metrics],
        "",
        "Policy Integrity: entry timing did not change approval thresholds, "
        "recommendation weights, allocation, or replay approval counts.",
    ]
    return tuple(lines)


def render_entry_timing_failures(
    rows: tuple[EntryTimingOutcomeRow, ...],
) -> tuple[str, ...]:
    lines = ["Entry Timing Candidate Inspection"]
    if not rows:
        return tuple([*lines, "- none"])
    for row in rows:
        assessment = row.assessment
        lines.append(
            f"- {assessment.symbol} {assessment.evaluation_date}: "
            f"{assessment.entry_state.value}, score {assessment.timing_score}, "
            f"return {_metric(row.forward_return)}, MFE {_metric(row.mfe)}, "
            f"stop {_metric(assessment.stop_distance_pct)}, RR "
            f"{_metric(assessment.reward_risk)}"
        )
        lines.append(
            f"  extension {assessment.price_extension_state.value}; "
            f"volume {assessment.volume_confirmation_state.value}; "
            f"RS {assessment.relative_strength_state.value}; "
            f"reason {row.primary_rejection_reason or 'none'}"
        )
    return tuple(lines)


def export_entry_timing_json(report: EntryTimingReplayReport, path: Path) -> None:
    path.write_text(json.dumps(_report_dict(report), indent=2) + "\n", encoding="utf-8")


def export_entry_timing_csv(report: EntryTimingReplayReport, path: Path) -> None:
    _write_csv(tuple(_row_dict(row) for row in report.rows), path)


def export_entry_timing_failures_json(
    rows: tuple[EntryTimingOutcomeRow, ...],
    path: Path,
) -> None:
    path.write_text(
        json.dumps([_row_dict(row) for row in rows], indent=2) + "\n",
        encoding="utf-8",
    )


def export_entry_timing_failures_csv(
    rows: tuple[EntryTimingOutcomeRow, ...],
    path: Path,
) -> None:
    _write_csv(tuple(_row_dict(row) for row in rows), path)


@dataclass(frozen=True, slots=True)
class _Distances:
    atr_percent: Decimal | None
    support_pct: Decimal | None
    support_atr: Decimal | None
    breakout_pct: Decimal | None
    breakout_atr: Decimal | None
    dma20_pct: Decimal | None
    dma50_pct: Decimal | None
    swing_low_pct: Decimal | None
    resistance_pct: Decimal | None
    target1_upside_pct: Decimal | None
    stop_pct: Decimal | None
    reward_risk: Decimal | None


def _input_from_record(record: CandidateDecisionRecord) -> EntryTimingInput:
    current = (
        record.confirmation_entry or record.entry_zone_high or record.entry_zone_low
    )
    support = record.entry_zone_low or record.risk_stop
    indicator = record.indicator_scores
    return EntryTimingInput(
        symbol=record.symbol,
        evaluation_date=record.evaluation_date,
        setup_type=record.setup_type,
        current_price=current,
        reference_entry=current,
        structural_support=support,
        structural_resistance=record.target_1,
        breakout_level=record.entry_zone_high,
        retracement_low=record.entry_zone_low,
        retracement_high=record.entry_zone_high,
        recent_swing_low=record.risk_stop,
        recent_swing_high=record.target_1,
        dma_20=_indicator_decimal(indicator, ("dma-20", "dma_20", "20dma")),
        dma_50=_indicator_decimal(indicator, ("dma-50", "dma_50", "50dma")),
        dma_200=_indicator_decimal(indicator, ("dma-200", "dma_200", "200dma")),
        atr=_indicator_decimal(indicator, ("atr",)),
        stop_loss=record.risk_stop,
        target_1=record.target_1,
        target_2=record.target_2,
        market_regime=record.market_regime,
        sector_regime=record.sector,
        setup_age_bars=_indicator_int(indicator, ("setup-age-bars", "setup_age_bars")),
        volume_confirmation_state=_volume_state(indicator),
        relative_strength_state=_relative_strength_state(indicator),
    )


def _input_from_candidate(candidate: object) -> EntryTimingInput:
    support = (
        getattr(candidate, "support_level", None)
        or getattr(candidate, "swing_low", None)
        or getattr(candidate, "stop", None)
    )
    setup_type = getattr(candidate, "setup_quality", None) or getattr(
        candidate, "setup_stage", None
    )
    return EntryTimingInput(
        symbol=str(getattr(candidate, "symbol", "UNKNOWN")),
        evaluation_date=date.today(),
        setup_type=setup_type,
        current_price=getattr(candidate, "entry", None),
        reference_entry=getattr(candidate, "entry", None),
        structural_support=support,
        structural_resistance=getattr(candidate, "resistance_level", None)
        or getattr(candidate, "swing_high", None),
        breakout_level=getattr(candidate, "entry", None),
        retracement_low=support,
        retracement_high=getattr(candidate, "entry", None),
        recent_swing_low=getattr(candidate, "swing_low", None),
        recent_swing_high=getattr(candidate, "swing_high", None),
        dma_20=getattr(candidate, "dma_20", None),
        dma_50=None,
        dma_200=None,
        atr=getattr(candidate, "atr", None),
        stop_loss=getattr(candidate, "stop", None),
        target_1=getattr(candidate, "target_1", None),
        target_2=getattr(candidate, "target_2", None),
        market_regime=getattr(candidate, "market_regime", None),
        sector_regime=getattr(candidate, "sector", None),
        setup_age_bars=None,
        volume_confirmation_state=VolumeConfirmationState.UNAVAILABLE,
        relative_strength_state=RelativeStrengthTimingState.UNAVAILABLE,
    )


def _distances(entry: EntryTimingInput) -> _Distances:
    current = entry.current_price
    return _Distances(
        atr_percent=_pct(entry.atr, current),
        support_pct=_distance_pct(current, entry.structural_support),
        support_atr=_distance_atr(current, entry.structural_support, entry.atr),
        breakout_pct=_distance_pct(current, entry.breakout_level),
        breakout_atr=_distance_atr(current, entry.breakout_level, entry.atr),
        dma20_pct=_distance_pct(current, entry.dma_20),
        dma50_pct=_distance_pct(current, entry.dma_50),
        swing_low_pct=_distance_pct(current, entry.recent_swing_low),
        resistance_pct=_distance_pct(entry.structural_resistance, current),
        target1_upside_pct=_distance_pct(entry.target_1, current),
        stop_pct=_distance_pct(current, entry.stop_loss),
        reward_risk=_reward_risk(entry),
    )


def _pct(value: Decimal | None, base: Decimal | None) -> Decimal | None:
    if value is None or base is None or base <= _ZERO:
        return None
    return (value / base * _HUNDRED).quantize(_TWO)


def _distance_pct(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None or right <= _ZERO:
        return None
    return ((left - right) / right * _HUNDRED).quantize(_TWO)


def _distance_atr(
    left: Decimal | None,
    right: Decimal | None,
    atr: Decimal | None,
) -> Decimal | None:
    if left is None or right is None or atr is None or atr <= _ZERO:
        return None
    return ((left - right) / atr).quantize(_TWO)


def _reward_risk(entry: EntryTimingInput) -> Decimal | None:
    current = entry.current_price
    stop = entry.stop_loss
    target = entry.target_2 or entry.target_1
    if current is None or stop is None or target is None or current <= stop:
        return None
    return ((target - current) / (current - stop)).quantize(_TWO)


def _data_completeness(entry: EntryTimingInput) -> TimingDataCompleteness:
    required = (entry.current_price, entry.reference_entry, entry.stop_loss)
    structural = (entry.structural_support, entry.breakout_level, entry.dma_20)
    if any(value is None for value in required):
        return TimingDataCompleteness.INSUFFICIENT
    if any(value is None for value in structural):
        return TimingDataCompleteness.PARTIAL
    return TimingDataCompleteness.COMPLETE


def _extension_state(
    distances: _Distances,
    config: EntryTimingConfig,
) -> PriceExtensionState:
    if distances.support_pct is None and distances.support_atr is None:
        return PriceExtensionState.EXTENSION_UNAVAILABLE
    if (
        distances.support_atr is not None
        and distances.support_atr >= config.severe_extension_atr
    ) or (
        distances.support_pct is not None
        and distances.support_pct >= config.late_support_distance_pct
    ):
        return PriceExtensionState.SEVERELY_EXTENDED
    if (
        distances.support_atr is not None
        and distances.support_atr >= config.moderate_extension_atr
    ) or (
        distances.support_pct is not None
        and distances.support_pct >= config.extended_support_distance_pct
    ):
        return PriceExtensionState.MODERATELY_EXTENDED
    if (
        distances.support_atr is not None
        and distances.support_atr >= config.mild_extension_atr
    ) or (
        distances.support_pct is not None
        and distances.support_pct >= config.early_support_distance_pct
    ):
        return PriceExtensionState.MILDLY_EXTENDED
    return PriceExtensionState.NOT_EXTENDED


def _is_late(
    entry: EntryTimingInput,
    distances: _Distances,
    extension_state: PriceExtensionState,
    config: EntryTimingConfig,
) -> bool:
    return (
        extension_state is PriceExtensionState.SEVERELY_EXTENDED
        or (
            distances.stop_pct is not None
            and distances.stop_pct >= config.late_stop_distance_pct
        )
        or (
            distances.reward_risk is not None
            and distances.reward_risk < config.weak_reward_risk
        )
        or (
            entry.setup_age_bars is not None
            and entry.setup_age_bars > config.stale_setup_bars
        )
    )


def _acceptable_entry(
    distances: _Distances,
    config: EntryTimingConfig,
) -> bool:
    return (
        distances.stop_pct is not None
        and distances.stop_pct <= config.maximum_preferred_stop_pct
        and distances.reward_risk is not None
        and distances.reward_risk >= config.minimum_preferred_reward_risk
    )


def _preferred(distances: _Distances, config: EntryTimingConfig) -> bool:
    return (
        distances.support_pct is not None
        and distances.support_pct <= config.preferred_support_distance_pct
        and _acceptable_entry(distances, config)
    )


def _near_support(distances: _Distances, config: EntryTimingConfig) -> bool:
    return (
        distances.support_pct is not None
        and distances.support_pct <= config.early_support_distance_pct
        and distances.stop_pct is not None
        and distances.stop_pct <= config.maximum_preferred_stop_pct
    )


def _structural_score(distances: _Distances, config: EntryTimingConfig) -> Decimal:
    if distances.support_pct is None:
        return Decimal("35")
    if distances.support_pct <= config.preferred_support_distance_pct:
        return Decimal("95")
    if distances.support_pct <= config.early_support_distance_pct:
        return Decimal("80")
    if distances.support_pct <= config.extended_support_distance_pct:
        return Decimal("55")
    if distances.support_pct <= config.late_support_distance_pct:
        return Decimal("35")
    return Decimal("10")


def _stop_score(stop_pct: Decimal | None) -> Decimal:
    if stop_pct is None:
        return Decimal("30")
    if stop_pct <= Decimal("6"):
        return Decimal("95")
    if stop_pct <= Decimal("10"):
        return Decimal("80")
    if stop_pct <= Decimal("15"):
        return Decimal("45")
    return Decimal("15")


def _reward_score(reward_risk: Decimal | None) -> Decimal:
    if reward_risk is None:
        return Decimal("30")
    if reward_risk >= Decimal("3"):
        return Decimal("95")
    if reward_risk >= Decimal("2"):
        return Decimal("80")
    if reward_risk >= Decimal("1.2"):
        return Decimal("45")
    return Decimal("10")


def _extension_score(value: PriceExtensionState) -> Decimal:
    return {
        PriceExtensionState.NOT_EXTENDED: Decimal("95"),
        PriceExtensionState.MILDLY_EXTENDED: Decimal("70"),
        PriceExtensionState.MODERATELY_EXTENDED: Decimal("35"),
        PriceExtensionState.SEVERELY_EXTENDED: Decimal("5"),
        PriceExtensionState.EXTENSION_UNAVAILABLE: Decimal("35"),
    }[value]


def _volume_score(value: VolumeConfirmationState) -> Decimal:
    return {
        VolumeConfirmationState.CONFIRMED_EXPANSION: Decimal("95"),
        VolumeConfirmationState.PULLBACK_CONTRACTION: Decimal("85"),
        VolumeConfirmationState.WEAK_CONFIRMATION: Decimal("45"),
        VolumeConfirmationState.ABNORMAL_VOLUME: Decimal("55"),
        VolumeConfirmationState.EXHAUSTION_RISK: Decimal("15"),
        VolumeConfirmationState.UNAVAILABLE: Decimal("45"),
    }[value]


def _relative_strength_score(value: RelativeStrengthTimingState) -> Decimal:
    return {
        RelativeStrengthTimingState.OUTPERFORMING: Decimal("90"),
        RelativeStrengthTimingState.NEUTRAL: Decimal("60"),
        RelativeStrengthTimingState.UNDERPERFORMING: Decimal("20"),
        RelativeStrengthTimingState.UNAVAILABLE: Decimal("45"),
    }[value]


def _freshness_score(age: int | None, config: EntryTimingConfig) -> Decimal:
    if age is None:
        return Decimal("55")
    if age <= 5:
        return Decimal("95")
    if age <= config.stale_setup_bars:
        return Decimal("65")
    return Decimal("15")


def _score_reasons(
    entry: EntryTimingInput,
    distances: _Distances,
) -> tuple[EntryTimingReasonCode, ...]:
    reasons = []
    if distances.stop_pct is not None and distances.stop_pct <= Decimal("10"):
        reasons.append(EntryTimingReasonCode.FAVOURABLE_STOP_DISTANCE)
    if distances.reward_risk is not None and distances.reward_risk >= Decimal("2"):
        reasons.append(EntryTimingReasonCode.FAVOURABLE_REWARD_RISK)
    if entry.volume_confirmation_state is VolumeConfirmationState.CONFIRMED_EXPANSION:
        reasons.append(EntryTimingReasonCode.VOLUME_CONFIRMS)
    if entry.relative_strength_state is RelativeStrengthTimingState.OUTPERFORMING:
        reasons.append(EntryTimingReasonCode.RELATIVE_STRENGTH_SUPPORTS)
    return tuple(reasons)


def _score_warnings(
    entry: EntryTimingInput,
    distances: _Distances,
    extension_state: PriceExtensionState,
    config: EntryTimingConfig,
) -> tuple[EntryTimingWarningCode, ...]:
    warnings = []
    if (
        distances.stop_pct is not None
        and distances.stop_pct > config.maximum_preferred_stop_pct
    ):
        warnings.append(EntryTimingWarningCode.EXCESSIVE_STOP_DISTANCE)
    if distances.reward_risk is not None and distances.reward_risk < Decimal("2"):
        warnings.append(EntryTimingWarningCode.WEAK_REWARD_RISK)
    if extension_state in {
        PriceExtensionState.MODERATELY_EXTENDED,
        PriceExtensionState.SEVERELY_EXTENDED,
    }:
        warnings.append(EntryTimingWarningCode.PRICE_EXTENSION)
    if entry.volume_confirmation_state is VolumeConfirmationState.WEAK_CONFIRMATION:
        warnings.append(EntryTimingWarningCode.WEAK_VOLUME_CONFIRMATION)
    if entry.relative_strength_state is RelativeStrengthTimingState.UNDERPERFORMING:
        warnings.append(EntryTimingWarningCode.UNDERPERFORMING_RELATIVE_STRENGTH)
    return tuple(warnings)


def _confidence(
    completeness: TimingDataCompleteness,
    entry: EntryTimingInput,
) -> TimingConfidence:
    if completeness is TimingDataCompleteness.COMPLETE and entry.atr is not None:
        return TimingConfidence.HIGH
    if completeness is TimingDataCompleteness.INSUFFICIENT:
        return TimingConfidence.LOW
    return TimingConfidence.MEDIUM


def _wait_condition(state: EntryTimingState, entry: EntryTimingInput) -> str | None:
    if state in {EntryTimingState.PREFERRED_ENTRY, EntryTimingState.CONFIRMATION_ENTRY}:
        return None
    if state is EntryTimingState.SETUP_FORMING:
        return "Wait for close above resistance with confirmed volume."
    if state is EntryTimingState.EARLY_ENTRY:
        return "Wait for confirmation or use only aggressive execution sizing."
    if state in {EntryTimingState.EXTENDED_ENTRY, EntryTimingState.LATE_ENTRY}:
        return (
            "Wait for price to return near structural support or rebuild reward/risk."
        )
    if state is EntryTimingState.INVALID_ENTRY:
        return "Avoid until the setup reforms above structural support."
    if entry.breakout_level is not None:
        return f"Wait for price action around breakout level {entry.breakout_level}."
    return "Wait for a defensible structural entry reference."


def _invalidation_condition(entry: EntryTimingInput) -> str | None:
    if entry.stop_loss is not None:
        return f"Entry thesis invalid below stop/support {entry.stop_loss}."
    if entry.structural_support is not None:
        return f"Entry thesis invalid below support {entry.structural_support}."
    return None


def _row_for_record(
    engine: EntryTimingIntelligenceEngine,
    record: CandidateDecisionRecord,
    outcome: CandidateForwardOutcome | None,
) -> EntryTimingOutcomeRow:
    assessment = engine.assess_record(record)
    window = _primary_window(outcome)
    completed = _completed(window)
    forward_return = window.forward_return_pct_from_entry if window else None
    profitable = forward_return is not None and forward_return > _ZERO
    target_2_hit = _target_2_hit(record, window)
    return EntryTimingOutcomeRow(
        assessment=assessment,
        candidate_id=record.candidate_id,
        approved=record.approved_for_deployment,
        primary_rejection_reason=record.rejection_reasons[0]
        if record.rejection_reasons
        else None,
        completed_outcome=completed,
        profitable=profitable,
        forward_return=forward_return,
        mfe=window.max_favourable_excursion_pct if window else None,
        mae=window.max_adverse_excursion_pct if window else None,
        target_1_hit=window.target_1_touched if window else None,
        target_2_hit=target_2_hit,
        stop_hit=window.risk_stop_touched if window else None,
    )


def _state_performance(
    rows: tuple[EntryTimingOutcomeRow, ...],
    config: EntryTimingConfig,
) -> tuple[EntryTimingStatePerformance, ...]:
    result = []
    for state in EntryTimingState:
        state_rows = tuple(row for row in rows if row.assessment.entry_state is state)
        if not state_rows:
            continue
        completed = tuple(row for row in state_rows if row.completed_outcome)
        profitable = tuple(row for row in completed if row.profitable)
        symbols = {row.assessment.symbol for row in completed}
        dates = {row.assessment.evaluation_date for row in completed}
        warning = None
        if (
            len(completed) < config.minimum_completed_outcomes_per_state
            or len(symbols) < config.minimum_symbols_per_state
            or len(dates) < config.minimum_replay_dates_per_state
        ):
            warning = "INSUFFICIENT EVIDENCE"
        result.append(
            EntryTimingStatePerformance(
                entry_state=state,
                candidate_count=len(state_rows),
                completed_outcomes=len(completed),
                profitable_outcomes=len(profitable),
                unsuccessful_outcomes=len(completed) - len(profitable),
                success_rate=_rate(len(profitable), len(completed)),
                average_forward_return=_average(
                    tuple(row.forward_return for row in completed)
                ),
                median_forward_return=_median(
                    tuple(row.forward_return for row in completed)
                ),
                average_mfe=_average(tuple(row.mfe for row in completed)),
                average_mae=_average(tuple(row.mae for row in completed)),
                target_1_hit_rate=_rate(
                    sum(1 for row in completed if row.target_1_hit),
                    len(completed),
                ),
                target_2_hit_rate=_rate(
                    sum(1 for row in completed if row.target_2_hit),
                    len(completed),
                ),
                stop_hit_rate=_rate(
                    sum(1 for row in completed if row.stop_hit),
                    len(completed),
                ),
                invalidation_hit_rate=None,
                average_reward_risk=_average(
                    tuple(row.assessment.reward_risk for row in completed)
                ),
                average_stop_distance=_average(
                    tuple(row.assessment.stop_distance_pct for row in completed)
                ),
                average_timing_score=_average(
                    tuple(row.assessment.timing_score for row in completed)
                ),
                data_completeness=_dominant_completeness(state_rows),
                evidence_warning=warning,
            )
        )
    return tuple(result)


def _winner_loser_comparison(
    rows: tuple[EntryTimingOutcomeRow, ...],
    config: EntryTimingConfig,
) -> tuple[TimingFeatureComparison, ...]:
    features = (
        ("timing_score", lambda row: row.assessment.timing_score),
        ("stop_distance", lambda row: row.assessment.stop_distance_pct),
        ("reward_risk", lambda row: row.assessment.reward_risk),
        ("distance_from_support", lambda row: row.assessment.distance_from_support_pct),
        (
            "atr_distance_from_support",
            lambda row: row.assessment.distance_from_support_atr,
        ),
        (
            "distance_from_breakout",
            lambda row: row.assessment.distance_from_breakout_pct,
        ),
        ("distance_from_20dma", lambda row: row.assessment.distance_from_20dma_pct),
        ("distance_from_50dma", lambda row: row.assessment.distance_from_50dma_pct),
        (
            "distance_to_resistance",
            lambda row: row.assessment.distance_to_resistance_pct,
        ),
        ("setup_age", lambda row: _decimal_int(row.assessment.setup_age_bars)),
    )
    comparisons = []
    completed = tuple(row for row in rows if row.completed_outcome)
    for name, getter in features:
        winner_values: list[Decimal] = []
        loser_values: list[Decimal] = []
        missing = 0
        for row in completed:
            value = getter(row)
            if value is None:
                missing += 1
            elif row.profitable:
                winner_values.append(value)
            else:
                loser_values.append(value)
        winner_mean = _average(tuple(winner_values))
        loser_mean = _average(tuple(loser_values))
        warning = (
            "INSUFFICIENT EVIDENCE"
            if len(winner_values) < config.minimum_completed_outcomes_per_state
            or len(loser_values) < config.minimum_completed_outcomes_per_state
            else None
        )
        comparisons.append(
            TimingFeatureComparison(
                feature=name,
                winner_count=len(winner_values),
                loser_count=len(loser_values),
                winner_mean=winner_mean,
                loser_mean=loser_mean,
                winner_median=_median(tuple(winner_values)),
                loser_median=_median(tuple(loser_values)),
                winner_range=_range(tuple(winner_values)),
                loser_range=_range(tuple(loser_values)),
                missing_count=missing,
                effect_direction=_effect_direction(winner_mean, loser_mean),
                evidence_warning=warning,
            )
        )
    return tuple(comparisons)


def _conclusion(
    rows: tuple[EntryTimingOutcomeRow, ...],
    performance: tuple[EntryTimingStatePerformance, ...],
    config: EntryTimingConfig,
) -> EntryTimingDecision:
    completed = tuple(row for row in rows if row.completed_outcome)
    if len(completed) < config.minimum_completed_outcomes_per_state:
        return EntryTimingDecision(
            EntryTimingConclusion.INSUFFICIENT_EVIDENCE,
            (f"Only {len(completed)} completed outcomes are available.",),
        )
    profitable_rejections = tuple(
        row for row in completed if row.profitable and not row.approved
    )
    extended = tuple(
        row
        for row in profitable_rejections
        if row.assessment.entry_state is EntryTimingState.EXTENDED_ENTRY
    )
    late = tuple(
        row
        for row in profitable_rejections
        if row.assessment.entry_state is EntryTimingState.LATE_ENTRY
    )
    acceptable = tuple(
        row
        for row in profitable_rejections
        if row.assessment.entry_state
        in {EntryTimingState.PREFERRED_ENTRY, EntryTimingState.CONFIRMATION_ENTRY}
    )
    preferred_perf = _perf(performance, EntryTimingState.PREFERRED_ENTRY)
    extended_perf = _perf(performance, EntryTimingState.EXTENDED_ENTRY)
    separation = None
    if preferred_perf and extended_perf:
        if (
            preferred_perf.success_rate is not None
            and extended_perf.success_rate is not None
        ):
            separation = preferred_perf.success_rate - extended_perf.success_rate
    metrics = (
        f"{_pct_text(_rate(len(extended), len(profitable_rejections)))} of profitable "
        "rejections were extended entries.",
        f"{_pct_text(_rate(len(late), len(profitable_rejections)))} of profitable "
        "rejections were late entries.",
        f"{_pct_text(_rate(len(acceptable), len(profitable_rejections)))} of "
        "profitable rejections had preferred or confirmation timing.",
        f"Preferred-minus-extended success-rate separation is {_metric(separation)}.",
    )
    if len(profitable_rejections) == 0:
        conclusion = EntryTimingConclusion.DATA_COVERAGE_INSUFFICIENT
    elif separation is not None and separation >= Decimal("0.15"):
        conclusion = EntryTimingConclusion.ENTRY_TIMING_SEPARATES_OUTCOMES
    elif (_rate(len(extended), len(profitable_rejections)) or _ZERO) >= Decimal("0.40"):
        conclusion = EntryTimingConclusion.EXTENDED_ENTRIES_PRIMARY_PROBLEM
    elif (_rate(len(late), len(profitable_rejections)) or _ZERO) >= Decimal("0.30"):
        conclusion = EntryTimingConclusion.LATE_ENTRIES_PRIMARY_PROBLEM
    elif (_rate(len(acceptable), len(profitable_rejections)) or _ZERO) >= Decimal(
        "0.30"
    ):
        conclusion = EntryTimingConclusion.ACCEPTABLE_TIMING_BUT_OTHER_GATES_FAIL
    elif separation is not None and abs(separation) >= Decimal("0.05"):
        conclusion = EntryTimingConclusion.ENTRY_TIMING_WEAKLY_SEPARATES_OUTCOMES
    else:
        conclusion = EntryTimingConclusion.ENTRY_TIMING_MODEL_NEEDS_REFINEMENT
    return EntryTimingDecision(conclusion, metrics)


def _perf(
    performance: tuple[EntryTimingStatePerformance, ...],
    state: EntryTimingState,
) -> EntryTimingStatePerformance | None:
    return next((item for item in performance if item.entry_state is state), None)


def _primary_window(
    outcome: CandidateForwardOutcome | None,
) -> CandidateForwardWindowOutcome | None:
    if outcome is None:
        return None
    by_window = {window.window: window for window in outcome.windows}
    return next(
        (
            by_window[label]
            for label in ("20d", "10d", "5d", "3d", "1d", "60d")
            if label in by_window
        ),
        outcome.windows[0] if outcome.windows else None,
    )


def _completed(window: CandidateForwardWindowOutcome | None) -> bool:
    return (
        window is not None
        and window.outcome_label is not CandidateOutcomeLabel.DATA_MISSING
        and window.forward_return_pct_from_entry is not None
    )


def _target_2_hit(
    record: CandidateDecisionRecord,
    window: CandidateForwardWindowOutcome | None,
) -> bool | None:
    if window is None or window.forward_high is None or record.target_2 is None:
        return None
    return window.forward_high >= record.target_2


def _dominant_completeness(
    rows: tuple[EntryTimingOutcomeRow, ...],
) -> TimingDataCompleteness:
    counter = Counter(row.assessment.data_completeness for row in rows)
    return counter.most_common(1)[0][0]


def _volume_state(scores: dict[str, str] | object) -> VolumeConfirmationState:
    value = _indicator_decimal(
        scores,
        ("volume-confirmation", "volume", "relative-volume"),
    )
    if value is None:
        return VolumeConfirmationState.UNAVAILABLE
    if value >= Decimal("2.5"):
        return VolumeConfirmationState.ABNORMAL_VOLUME
    if value >= Decimal("1.5"):
        return VolumeConfirmationState.CONFIRMED_EXPANSION
    if value >= Decimal("1"):
        return VolumeConfirmationState.WEAK_CONFIRMATION
    return VolumeConfirmationState.PULLBACK_CONTRACTION


def _relative_strength_state(
    scores: dict[str, str] | object,
) -> RelativeStrengthTimingState:
    value = _indicator_decimal(scores, ("relative-strength", "relative_strength", "rs"))
    if value is None:
        return RelativeStrengthTimingState.UNAVAILABLE
    if value >= Decimal("60"):
        return RelativeStrengthTimingState.OUTPERFORMING
    if value <= Decimal("40"):
        return RelativeStrengthTimingState.UNDERPERFORMING
    return RelativeStrengthTimingState.NEUTRAL


def _indicator_decimal(
    scores: dict[str, str] | object,
    keys: tuple[str, ...],
) -> Decimal | None:
    if not hasattr(scores, "items"):
        return None
    normalized = {
        str(key).strip().lower().replace("_", "-"): str(value)
        for key, value in scores.items()
    }
    for key in keys:
        value = normalized.get(key.strip().lower().replace("_", "-"))
        if value is not None:
            try:
                return Decimal(value)
            except Exception:
                return None
    return None


def _indicator_int(
    scores: dict[str, str] | object,
    keys: tuple[str, ...],
) -> int | None:
    value = _indicator_decimal(scores, keys)
    return None if value is None else int(value)


def _average(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    return (sum(present, _ZERO) / Decimal(len(present))).quantize(_FOUR)


def _median(values: tuple[Decimal | None, ...]) -> Decimal | None:
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    return Decimal(str(median(present))).quantize(_FOUR)


def _range(values: tuple[Decimal, ...]) -> tuple[Decimal | None, Decimal | None]:
    if not values:
        return (None, None)
    return (min(values), max(values))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(_FOUR)


def _decimal_int(value: int | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _effect_direction(winner: Decimal | None, loser: Decimal | None) -> str:
    if winner is None or loser is None:
        return "unavailable"
    difference = winner - loser
    if abs(difference) < Decimal("0.01"):
        return "flat"
    return "higher_for_winners" if difference > _ZERO else "lower_for_winners"


def _score_bucket(score: Decimal) -> str:
    lower = int(score // Decimal("10")) * 10
    upper = lower + 9
    return f"{lower}-{upper}"


def _optional_bucket(value: Decimal | None, boundaries: tuple[int, ...]) -> str:
    if value is None:
        return "unavailable"
    for boundary in boundaries:
        if value < Decimal(boundary):
            return f"<{boundary}"
    return f">={boundaries[-1]}"


def _row_sort_key(row: EntryTimingOutcomeRow) -> tuple[date, str, str]:
    return (
        row.assessment.evaluation_date,
        row.assessment.symbol,
        row.candidate_id,
    )


def _performance_lines(
    performance: tuple[EntryTimingStatePerformance, ...],
) -> tuple[str, ...]:
    if not performance:
        return ("- unavailable",)
    return tuple(
        f"- {item.entry_state.value}: candidates {item.candidate_count}, completed "
        f"{item.completed_outcomes}, profitable {item.profitable_outcomes}, "
        f"success {_pct_text(item.success_rate)}, avg return "
        f"{_metric(item.average_forward_return)}, avg stop "
        f"{_metric(item.average_stop_distance)}, avg timing "
        f"{_metric(item.average_timing_score)}"
        + (f" — {item.evidence_warning}" if item.evidence_warning else "")
        for item in performance
    )


def _comparison_lines(
    comparisons: tuple[TimingFeatureComparison, ...],
) -> tuple[str, ...]:
    if not comparisons:
        return ("- unavailable",)
    return tuple(
        f"- {item.feature}: winners mean {_metric(item.winner_mean)}, losers mean "
        f"{_metric(item.loser_mean)}, effect {item.effect_direction}, missing "
        f"{item.missing_count}"
        + (f" — {item.evidence_warning}" if item.evidence_warning else "")
        for item in comparisons[:10]
    )


def _profitable_rejection_lines(
    rows: tuple[EntryTimingOutcomeRow, ...],
) -> tuple[str, ...]:
    if not rows:
        return ("- none",)
    counter = Counter(row.assessment.entry_state for row in rows)
    lines = [
        f"- {state.value}: {count}"
        for state, count in sorted(counter.items(), key=lambda item: item[0].value)
    ]
    acceptable = sum(
        count
        for state, count in counter.items()
        if state
        in {EntryTimingState.PREFERRED_ENTRY, EntryTimingState.CONFIRMATION_ENTRY}
    )
    lines.append(f"- acceptable timing but rejected for other gates: {acceptable}")
    return tuple(lines)


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _pct_text(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{(value * _HUNDRED).quantize(_TWO)}%"


def _row_dict(row: EntryTimingOutcomeRow) -> dict[str, object]:
    assessment = row.assessment
    return {
        "symbol": assessment.symbol,
        "evaluation_date": assessment.evaluation_date.isoformat(),
        "candidate_id": row.candidate_id,
        "entry_state": assessment.entry_state.value,
        "timing_score": str(assessment.timing_score),
        "timing_confidence": assessment.timing_confidence.value,
        "price_extension_state": assessment.price_extension_state.value,
        "current_price": _text(assessment.current_price),
        "structural_support": _text(assessment.structural_support),
        "breakout_level": _text(assessment.breakout_level),
        "stop_distance_pct": _text(assessment.stop_distance_pct),
        "reward_risk": _text(assessment.reward_risk),
        "distance_from_support_pct": _text(assessment.distance_from_support_pct),
        "distance_from_support_atr": _text(assessment.distance_from_support_atr),
        "distance_from_breakout_pct": _text(assessment.distance_from_breakout_pct),
        "distance_from_20dma_pct": _text(assessment.distance_from_20dma_pct),
        "distance_from_50dma_pct": _text(assessment.distance_from_50dma_pct),
        "volume_confirmation_state": assessment.volume_confirmation_state.value,
        "relative_strength_state": assessment.relative_strength_state.value,
        "data_completeness": assessment.data_completeness.value,
        "actionable_now": assessment.actionable_now,
        "timing_reasons": [reason.value for reason in assessment.timing_reasons],
        "timing_warnings": [warning.value for warning in assessment.timing_warnings],
        "approved": row.approved,
        "completed_outcome": row.completed_outcome,
        "profitable": row.profitable,
        "forward_return": _text(row.forward_return),
        "mfe": _text(row.mfe),
        "mae": _text(row.mae),
        "target_1_hit": row.target_1_hit,
        "target_2_hit": row.target_2_hit,
        "stop_hit": row.stop_hit,
        "primary_rejection_reason": row.primary_rejection_reason,
    }


def _report_dict(report: EntryTimingReplayReport) -> dict[str, object]:
    return {
        "candidates_evaluated": report.candidates_evaluated,
        "completed_outcomes": report.completed_outcomes,
        "approval_count_before": report.approval_count_before,
        "approval_count_after": report.approval_count_after,
        "rows": [_row_dict(row) for row in report.rows],
        "state_performance": [
            {
                "entry_state": item.entry_state.value,
                "candidate_count": item.candidate_count,
                "completed_outcomes": item.completed_outcomes,
                "profitable_outcomes": item.profitable_outcomes,
                "success_rate": _text(item.success_rate),
                "average_forward_return": _text(item.average_forward_return),
                "average_stop_distance": _text(item.average_stop_distance),
                "average_timing_score": _text(item.average_timing_score),
                "evidence_warning": item.evidence_warning,
            }
            for item in report.state_performance
        ],
        "winner_loser_comparison": [
            {
                "feature": item.feature,
                "winner_mean": _text(item.winner_mean),
                "loser_mean": _text(item.loser_mean),
                "effect_direction": item.effect_direction,
                "missing_count": item.missing_count,
                "evidence_warning": item.evidence_warning,
            }
            for item in report.winner_loser_comparison
        ],
        "conclusion": report.conclusion.conclusion.value,
        "supporting_metrics": list(report.conclusion.supporting_metrics),
    }


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _write_csv(rows: tuple[dict[str, object], ...], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
