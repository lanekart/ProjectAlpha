from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from alpha.candidate_generation_research.models import (
    CandidateTimingRecord,
    TimingClassification,
    TradableOpportunityOnset,
)
from alpha.canonical_integrity_audit.models import (
    CanonicalTradeEvent,
    MajorOpportunityEvent,
)


class CandidateTimingAuditEngine:
    def measure(
        self,
        *,
        events: tuple[MajorOpportunityEvent, ...],
        onsets: tuple[TradableOpportunityOnset, ...],
        candidates: tuple[CanonicalTradeEvent, ...],
        sessions: tuple[date, ...],
    ) -> tuple[CandidateTimingRecord, ...]:
        events_by_id = {item.event_id: item for item in events}
        candidates_by_symbol: dict[str, list[CanonicalTradeEvent]] = defaultdict(list)
        for candidate_row in candidates:
            candidates_by_symbol[candidate_row.symbol].append(candidate_row)
        position = {value: index for index, value in enumerate(sessions)}
        rows = []
        for onset in onsets:
            if onset.forward_event_id is None:
                continue
            event = events_by_id.get(onset.forward_event_id)
            if event is None:
                continue
            candidate: CanonicalTradeEvent | None = min(
                (
                    item
                    for item in candidates_by_symbol.get(onset.symbol, ())
                    if onset.onset_date <= item.observed_on <= event.peak_date
                ),
                key=lambda item: item.observed_on,
                default=None,
            )
            delay = (
                None
                if candidate is None
                else _distance(onset.onset_date, candidate.observed_on, position)
            )
            rr = _candidate_rr(candidate)
            extension = _candidate_extension(onset, candidate)
            rows.append(
                CandidateTimingRecord(
                    event_id=event.event_id,
                    onset_id=onset.onset_id,
                    symbol=onset.symbol,
                    earliest_tradable_date=onset.onset_date,
                    canonical_candidate_date=(
                        None if candidate is None else candidate.observed_on
                    ),
                    delay_sessions=delay,
                    entry_timing_state_at_onset="ACTIONABLE_POINT_IN_TIME",
                    entry_timing_state_at_candidate=(
                        "UNAVAILABLE" if candidate is None else candidate.setup_state
                    ),
                    extension_at_candidate=extension,
                    remaining_forward_move=(
                        None
                        if candidate is None
                        or candidate.entry is None
                        or candidate.entry <= 0
                        else event.peak_price / candidate.entry - 1
                    ),
                    prospective_rr_at_onset=onset.prospective_rr,
                    prospective_rr_at_candidate=rr,
                    classification=_classification(candidate, delay, extension),
                )
            )
        return tuple(rows)


def _classification(
    candidate: CanonicalTradeEvent | None,
    delay: int | None,
    extension: Decimal | None,
) -> TimingClassification:
    if candidate is None or delay is None:
        return TimingClassification.NO_CANDIDATE
    if extension is not None and extension > Decimal("0.10"):
        return TimingClassification.EXTENDED_BEFORE_DETECTION
    if candidate.setup_state in {"LATE", "INVALID"}:
        return TimingClassification.MISSED_TIMING_WINDOW
    if delay <= 2:
        return TimingClassification.ON_TIME
    if delay <= 5:
        return TimingClassification.SLIGHTLY_LATE
    if delay <= 15:
        return TimingClassification.MATERIALLY_LATE
    return TimingClassification.MISSED_TIMING_WINDOW


def _candidate_rr(candidate: CanonicalTradeEvent | None) -> Decimal | None:
    if (
        candidate is None
        or candidate.entry is None
        or candidate.stop is None
        or candidate.targets[0] is None
        or not candidate.stop < candidate.entry < candidate.targets[0]
    ):
        return None
    return (candidate.targets[0] - candidate.entry) / (candidate.entry - candidate.stop)


def _candidate_extension(
    onset: TradableOpportunityOnset,
    candidate: CanonicalTradeEvent | None,
) -> Decimal | None:
    if candidate is None or candidate.entry is None or onset.entry_trigger <= 0:
        return None
    return candidate.entry / onset.entry_trigger - 1


def _distance(start: date, end: date, positions: dict[date, int]) -> int:
    if start in positions and end in positions:
        return max(positions[end] - positions[start], 0)
    return max((end - start).days, 0)


__all__ = ["CandidateTimingAuditEngine"]
