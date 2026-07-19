from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from alpha.canonical_integrity_audit.models import (
    CanonicalTradeEvent,
    CoverageClassification,
    MajorOpportunityEvent,
    OpportunityCoverageRecord,
    RuntimeFailureRecord,
)
from alpha.canonical_universe_audit.models import CandidateOutcomeRecord


class MajorOpportunityCoverageEngine:
    """Attribute major moves to the frozen canonical decision funnel."""

    def classify(
        self,
        *,
        events: tuple[MajorOpportunityEvent, ...],
        candidates: tuple[CanonicalTradeEvent, ...],
        outcomes: tuple[CandidateOutcomeRecord, ...] = (),
        runtime_failures: tuple[RuntimeFailureRecord, ...] = (),
        sessions: tuple[date, ...] = (),
    ) -> tuple[OpportunityCoverageRecord, ...]:
        outcome_by_key = {(item.observed_on, item.symbol): item for item in outcomes}
        candidates_by_symbol: dict[str, list[CanonicalTradeEvent]] = defaultdict(list)
        for candidate_row in candidates:
            candidates_by_symbol[candidate_row.symbol].append(candidate_row)
        runtime_by_symbol: dict[str, list[RuntimeFailureRecord]] = defaultdict(list)
        for failure in runtime_failures:
            runtime_by_symbol[failure.symbol].append(failure)
        rows = []
        for event in events:
            relevant = tuple(
                item
                for item in candidates_by_symbol.get(event.symbol, ())
                if event.start_date <= item.observed_on <= event.peak_date
            )
            runtime = any(
                event.start_date <= item.trading_date <= event.peak_date
                for item in runtime_by_symbol.get(event.symbol, ())
            )
            candidate = (
                min(relevant, key=lambda item: item.observed_on) if relevant else None
            )
            outcome = (
                None
                if candidate is None
                else outcome_by_key.get((candidate.observed_on, candidate.symbol))
            )
            rows.append(
                _coverage_record(
                    event=event,
                    candidate=candidate,
                    outcome=outcome,
                    runtime=runtime,
                    sessions=sessions,
                )
            )
        return tuple(rows)


def _coverage_record(
    *,
    event: MajorOpportunityEvent,
    candidate: CanonicalTradeEvent | None,
    outcome: CandidateOutcomeRecord | None,
    runtime: bool,
    sessions: tuple[date, ...],
) -> OpportunityCoverageRecord:
    classification: CoverageClassification
    primary: str | None
    secondary: str | None
    if event.forward_return >= Decimal("10"):
        classification = CoverageClassification.DATA_BLOCKED
        primary = (
            "Unreconciled move of at least 1,000% requires corporate-action and "
            "identity validation before economic attribution."
        )
        secondary = "LEGACY_DATASET_PROVISIONAL"
    else:
        classification, primary, secondary = _classification(
            candidate=candidate,
            outcome=outcome,
            runtime=runtime,
        )
    captured_return = _captured_return(outcome)
    share = (
        None
        if captured_return is None or event.forward_return == 0
        else captured_return / event.forward_return
    )
    if (
        classification is CoverageClassification.PARTIALLY_CAPTURED
        and share is not None
    ):
        if share >= Decimal("0.50"):
            classification = CoverageClassification.CAPTURED
            primary = "Alpha entered and captured at least half of the bounded move."
    return OpportunityCoverageRecord(
        event_id=event.event_id,
        symbol=event.symbol,
        classification=classification,
        alpha_candidate_id=None if candidate is None else candidate.candidate_id,
        entry_delay_sessions=(
            None
            if candidate is None
            else _session_distance(event.start_date, candidate.observed_on, sessions)
        ),
        captured_return=captured_return,
        captured_r=None if outcome is None else outcome.realized_r,
        share_of_total_move=share,
        exit_efficiency=share,
        stop_efficiency=None,
        time_in_trade=None if outcome is None else outcome.holding_period_days,
        mfe=None,
        mae=None,
        primary_blocker=primary,
        secondary_blocker=secondary,
        score=None if candidate is None else candidate.score,
        setup_state=None if candidate is None else candidate.setup_state,
        timing_state=(
            None
            if candidate is None
            else "VALID"
            if candidate.setup_state in {"ENTRY_READY", "ACTIVE"}
            else "PENDING"
        ),
        trade_plan_grade=(
            None
            if candidate is None
            else "VALID"
            if _valid_trade_plan(candidate)
            else "UNAVAILABLE"
        ),
        stop_distance=_stop_distance(candidate),
        minimum_rr=_reward_risk(candidate),
        volume_confirmation=None,
        trend_confirmation=None,
    )


def _classification(
    *,
    candidate: CanonicalTradeEvent | None,
    outcome: CandidateOutcomeRecord | None,
    runtime: bool,
) -> tuple[CoverageClassification, str | None, str | None]:
    if candidate is None:
        if runtime:
            return (
                CoverageClassification.RUNTIME_BLOCKED,
                "Canonical execution failed during the event capture window.",
                None,
            )
        return (
            CoverageClassification.MISSED,
            "No canonical technical candidate was created in the capture window.",
            None,
        )
    if candidate.rejection_reason is not None:
        return (
            CoverageClassification.REJECTED,
            candidate.rejection_reason,
            candidate.final_gate,
        )
    if outcome is None or not outcome.completed:
        return (
            CoverageClassification.UNSCORABLE,
            "A candidate passed, but no completed comparable outcome is available.",
            None,
        )
    if not outcome.entered:
        return (
            CoverageClassification.PARTIALLY_CAPTURED,
            "The candidate existed but its recorded entry was not achieved.",
            outcome.exit_reason,
        )
    return (
        CoverageClassification.PARTIALLY_CAPTURED,
        "Alpha entered the move; capture quality is measured against the event.",
        outcome.exit_reason,
    )


def _captured_return(outcome: CandidateOutcomeRecord | None) -> Decimal | None:
    if outcome is None or not outcome.entered or outcome.realized_return_pct is None:
        return None
    return outcome.realized_return_pct / Decimal("100")


def _valid_trade_plan(candidate: CanonicalTradeEvent) -> bool:
    return (
        candidate.entry is not None
        and candidate.stop is not None
        and candidate.targets[0] is not None
        and candidate.stop < candidate.entry < candidate.targets[0]
    )


def _stop_distance(candidate: CanonicalTradeEvent | None) -> Decimal | None:
    if candidate is None or candidate.entry is None or candidate.stop is None:
        return None
    if candidate.entry <= 0 or candidate.stop >= candidate.entry:
        return None
    return (candidate.entry - candidate.stop) / candidate.entry


def _reward_risk(candidate: CanonicalTradeEvent | None) -> Decimal | None:
    if candidate is None or not _valid_trade_plan(candidate):
        return None
    assert candidate.entry is not None
    assert candidate.stop is not None
    assert candidate.targets[0] is not None
    return (candidate.targets[0] - candidate.entry) / (candidate.entry - candidate.stop)


def _session_distance(start: date, end: date, sessions: tuple[date, ...]) -> int:
    if not sessions:
        return max((end - start).days, 0)
    positions: Mapping[date, int] = {item: index for index, item in enumerate(sessions)}
    if start not in positions or end not in positions:
        return max((end - start).days, 0)
    return max(positions[end] - positions[start], 0)


__all__ = ["MajorOpportunityCoverageEngine"]
