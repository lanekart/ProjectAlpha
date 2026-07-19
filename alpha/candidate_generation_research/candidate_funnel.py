from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from alpha.candidate_generation_research.models import (
    CandidateCoverage,
    CandidateFailureReason,
    CandidateFunnelRecord,
    OpportunityFamily,
    StageStatus,
    TradableOpportunityOnset,
)
from alpha.canonical_integrity_audit.models import (
    CanonicalTradeEvent,
    MajorOpportunityEvent,
    RuntimeFailureRecord,
)
from alpha.canonical_universe_audit.models import CandidateOutcomeRecord

_CANONICAL_SUPPORTED = {
    OpportunityFamily.BREAKOUT_FROM_BASE,
    OpportunityFamily.VOLUME_BREAKOUT,
    OpportunityFamily.PULLBACK_CONTINUATION,
    OpportunityFamily.RETEST_HOLD,
    OpportunityFamily.VOLATILITY_CONTRACTION_BREAKOUT,
    OpportunityFamily.FAILED_BREAKOUT_REVERSAL,
}


class CandidateGenerationFunnelEngine:
    """Trace each actionable outcome label through the frozen candidate surface."""

    def trace(
        self,
        *,
        events: tuple[MajorOpportunityEvent, ...],
        onsets: tuple[TradableOpportunityOnset, ...],
        candidates: tuple[CanonicalTradeEvent, ...],
        outcomes: tuple[CandidateOutcomeRecord, ...] = (),
        runtime_failures: tuple[RuntimeFailureRecord, ...] = (),
    ) -> tuple[CandidateFunnelRecord, ...]:
        onsets_by_event: dict[str, list[TradableOpportunityOnset]] = defaultdict(list)
        for onset_row in onsets:
            if onset_row.forward_event_id is not None:
                onsets_by_event[onset_row.forward_event_id].append(onset_row)
        candidates_by_symbol: dict[str, list[CanonicalTradeEvent]] = defaultdict(list)
        for candidate_row in candidates:
            candidates_by_symbol[candidate_row.symbol].append(candidate_row)
        outcomes_by_key = {(item.observed_on, item.symbol): item for item in outcomes}
        failures_by_symbol: dict[str, list[RuntimeFailureRecord]] = defaultdict(list)
        for failure_row in runtime_failures:
            failures_by_symbol[failure_row.symbol].append(failure_row)
        rows = []
        for event in events:
            onset: TradableOpportunityOnset | None = min(
                onsets_by_event.get(event.event_id, ()),
                key=lambda item: item.onset_sequence,
                default=None,
            )
            candidate: CanonicalTradeEvent | None = _candidate_for(
                event=event,
                onset=onset,
                candidates=candidates_by_symbol.get(event.symbol, ()),
            )
            runtime_blocked = any(
                event.start_date <= item.trading_date <= event.peak_date
                for item in failures_by_symbol.get(event.symbol, ())
            )
            outcome = (
                None
                if candidate is None
                else outcomes_by_key.get((candidate.observed_on, candidate.symbol))
            )
            rows.append(
                _record(
                    event=event,
                    onset=onset,
                    candidate=candidate,
                    outcome=outcome,
                    runtime_blocked=runtime_blocked,
                )
            )
        return tuple(rows)


def _record(
    *,
    event: MajorOpportunityEvent,
    onset: TradableOpportunityOnset | None,
    candidate: CanonicalTradeEvent | None,
    outcome: CandidateOutcomeRecord | None,
    runtime_blocked: bool,
) -> CandidateFunnelRecord:
    if event.forward_return >= Decimal("10"):
        return _blocked_record(event, onset, StageStatus.DATA_BLOCKED)
    if onset is None:
        return _blocked_record(event, None, StageStatus.FAIL)
    if runtime_blocked and candidate is None:
        return CandidateFunnelRecord(
            event_id=event.event_id,
            onset_id=onset.onset_id,
            symbol=event.symbol,
            onset_date=onset.onset_date,
            event_family=onset.event_family.value,
            tradable_onset=StageStatus.PASS,
            canonical_setup_recognized=StageStatus.RUNTIME_BLOCKED,
            canonical_candidate_created=StageStatus.RUNTIME_BLOCKED,
            candidate_scored=StageStatus.RUNTIME_BLOCKED,
            verdict_assigned=StageStatus.RUNTIME_BLOCKED,
            timing_actionable=StageStatus.RUNTIME_BLOCKED,
            trade_plan_feasible=StageStatus.RUNTIME_BLOCKED,
            institutional_gate_evaluated=StageStatus.RUNTIME_BLOCKED,
            canonical_candidate_id=None,
            failure_reason=CandidateFailureReason.CANDIDATE_ADAPTER_DEFECT,
            coverage=CandidateCoverage.CANONICAL_SETUP_MISSED,
            evidence_limitation="Runtime failed inside the event window.",
        )
    setup_recognized = candidate is not None and _valid_setup(candidate.setup)
    trade_plan = candidate is not None and _valid_trade_plan(candidate)
    timing = candidate is not None and candidate.setup_state in {
        "ENTRY_READY",
        "ACTIVE",
    }
    coverage = _coverage(candidate, outcome, timing, trade_plan)
    reason = None if candidate is not None else _failure_reason(onset)
    return CandidateFunnelRecord(
        event_id=event.event_id,
        onset_id=onset.onset_id,
        symbol=event.symbol,
        onset_date=onset.onset_date,
        event_family=onset.event_family.value,
        tradable_onset=StageStatus.PASS,
        canonical_setup_recognized=(
            StageStatus.PASS if setup_recognized else StageStatus.FAIL
        ),
        canonical_candidate_created=(
            StageStatus.PASS if candidate is not None else StageStatus.FAIL
        ),
        candidate_scored=(
            StageStatus.PASS
            if candidate is not None and candidate.score is not None
            else StageStatus.FAIL
        ),
        verdict_assigned=(
            StageStatus.PASS
            if candidate is not None and candidate.final_signal not in {"", "UNKNOWN"}
            else StageStatus.FAIL
        ),
        timing_actionable=(
            StageStatus.PASS
            if timing
            else StageStatus.FAIL
            if candidate
            else StageStatus.NOT_APPLICABLE
        ),
        trade_plan_feasible=(
            StageStatus.PASS
            if trade_plan
            else StageStatus.FAIL
            if candidate
            else StageStatus.NOT_APPLICABLE
        ),
        institutional_gate_evaluated=(
            StageStatus.PASS if candidate is not None else StageStatus.NOT_APPLICABLE
        ),
        canonical_candidate_id=None if candidate is None else candidate.candidate_id,
        failure_reason=reason,
        coverage=coverage,
        evidence_limitation=(
            "The frozen ACU artifact retains the ranked candidate surface, not every "
            "negative internal setup decision."
            if candidate is None
            else None
        ),
    )


def _blocked_record(
    event: MajorOpportunityEvent,
    onset: TradableOpportunityOnset | None,
    status: StageStatus,
) -> CandidateFunnelRecord:
    data_blocked = status is StageStatus.DATA_BLOCKED
    return CandidateFunnelRecord(
        event_id=event.event_id,
        onset_id=None if onset is None else onset.onset_id,
        symbol=event.symbol,
        onset_date=None if onset is None else onset.onset_date,
        event_family=(
            OpportunityFamily.NO_TRADABLE_ONSET.value
            if onset is None
            else onset.event_family.value
        ),
        tradable_onset=status,
        canonical_setup_recognized=StageStatus.NOT_APPLICABLE,
        canonical_candidate_created=StageStatus.NOT_APPLICABLE,
        candidate_scored=StageStatus.NOT_APPLICABLE,
        verdict_assigned=StageStatus.NOT_APPLICABLE,
        timing_actionable=StageStatus.NOT_APPLICABLE,
        trade_plan_feasible=StageStatus.NOT_APPLICABLE,
        institutional_gate_evaluated=StageStatus.NOT_APPLICABLE,
        canonical_candidate_id=None,
        failure_reason=(
            CandidateFailureReason.IDENTITY_OR_CORPORATE_ACTION_BLOCK
            if data_blocked
            else None
        ),
        coverage=(
            CandidateCoverage.DATA_BLOCKED
            if data_blocked
            else CandidateCoverage.NOT_ACTUALLY_TRADABLE
        ),
        evidence_limitation=(
            "Move of at least 1,000% requires identity and corporate-action validation."
            if data_blocked
            else "No point-in-time onset passed tradability requirements."
        ),
    )


def _candidate_for(
    *,
    event: MajorOpportunityEvent,
    onset: TradableOpportunityOnset | None,
    candidates: list[CanonicalTradeEvent] | tuple[CanonicalTradeEvent, ...],
) -> CanonicalTradeEvent | None:
    if onset is None:
        return None
    rows = tuple(
        item
        for item in candidates
        if onset.onset_date <= item.observed_on <= event.peak_date
    )
    return min(rows, key=lambda item: item.observed_on, default=None)


def _coverage(
    candidate: CanonicalTradeEvent | None,
    outcome: CandidateOutcomeRecord | None,
    timing: bool,
    trade_plan: bool,
) -> CandidateCoverage:
    if candidate is None:
        return CandidateCoverage.CANONICAL_SETUP_MISSED
    if not timing:
        return CandidateCoverage.CANONICAL_TIMING_MISSED
    if not trade_plan:
        return CandidateCoverage.CANONICAL_TRADE_PLAN_FAILED
    if candidate.rejection_reason is not None:
        return CandidateCoverage.CANONICAL_CANDIDATE_REJECTED
    if outcome is not None and outcome.entered:
        return CandidateCoverage.CAPTURED_BY_CANONICAL
    return CandidateCoverage.PARTIALLY_CAPTURED_BY_CANONICAL


def _failure_reason(onset: TradableOpportunityOnset) -> CandidateFailureReason:
    if onset.event_family not in _CANONICAL_SUPPORTED:
        return CandidateFailureReason.SETUP_FAMILY_NOT_SUPPORTED
    volume = onset.point_in_time_inputs.get("volume_ratio_20")
    if volume in {None, "UNAVAILABLE"}:
        return CandidateFailureReason.MISSING_FEATURE
    if volume is not None and Decimal(volume) < Decimal("1.20"):
        return CandidateFailureReason.VOLUME_RULE_FAILED
    if onset.confidence < Decimal("0.65"):
        return CandidateFailureReason.PATTERN_THRESHOLD_TOO_STRICT
    return CandidateFailureReason.LOOKBACK_MISMATCH


def _valid_setup(value: str) -> bool:
    return value.strip().upper().replace("_", " ") not in {
        "",
        "UNKNOWN",
        "NO VALID SETUP",
        "NO VALID SETUP DETECTED",
    }


def _valid_trade_plan(candidate: CanonicalTradeEvent) -> bool:
    return (
        candidate.entry is not None
        and candidate.stop is not None
        and candidate.targets[0] is not None
        and candidate.stop < candidate.entry < candidate.targets[0]
    )


__all__ = ["CandidateGenerationFunnelEngine"]
