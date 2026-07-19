from __future__ import annotations

from collections import Counter, defaultdict

from alpha.candidate_generation_research.models import (
    CandidateFailureReason,
    CandidateFunnelRecord,
    TradableOpportunityOnset,
    ZeroCandidateDiagnostic,
    ZeroCandidateExplanation,
)
from alpha.canonical_integrity_audit.models import (
    CanonicalTradeEvent,
    MajorOpportunityEvent,
)


class ZeroCandidateClassificationEngine:
    def classify(
        self,
        *,
        symbols: tuple[str, ...],
        sessions_examined: int,
        events: tuple[MajorOpportunityEvent, ...],
        onsets: tuple[TradableOpportunityOnset, ...],
        funnel: tuple[CandidateFunnelRecord, ...],
        candidates: tuple[CanonicalTradeEvent, ...],
    ) -> tuple[ZeroCandidateDiagnostic, ...]:
        events_by_symbol: dict[str, list[MajorOpportunityEvent]] = defaultdict(list)
        onsets_by_symbol: dict[str, list[TradableOpportunityOnset]] = defaultdict(list)
        funnel_by_symbol: dict[str, list[CandidateFunnelRecord]] = defaultdict(list)
        candidates_by_symbol: dict[str, list[CanonicalTradeEvent]] = defaultdict(list)
        for event_row in events:
            events_by_symbol[event_row.symbol].append(event_row)
        for onset_row in onsets:
            onsets_by_symbol[onset_row.symbol].append(onset_row)
        for funnel_row in funnel:
            funnel_by_symbol[funnel_row.symbol].append(funnel_row)
        for candidate_row in candidates:
            candidates_by_symbol[candidate_row.symbol].append(candidate_row)
        rows = []
        for symbol in sorted(set(symbols)):
            symbol_onsets = onsets_by_symbol.get(symbol, [])
            symbol_funnel = funnel_by_symbol.get(symbol, [])
            symbol_candidates = candidates_by_symbol.get(symbol, [])
            primary, secondary = _blockers(symbol_funnel)
            rows.append(
                ZeroCandidateDiagnostic(
                    symbol=symbol,
                    sessions_examined=sessions_examined,
                    forward_move_events=len(events_by_symbol.get(symbol, ())),
                    tradable_onsets=len(symbol_onsets),
                    canonical_setup_detections=sum(
                        item.canonical_setup_recognized.value == "PASS"
                        for item in symbol_funnel
                    ),
                    canonical_candidates=len(symbol_candidates),
                    best_near_setup=(
                        "UNAVAILABLE"
                        if not symbol_onsets
                        else max(
                            symbol_onsets, key=lambda item: item.confidence
                        ).event_family.value
                    ),
                    primary_recognition_blocker=primary,
                    secondary_recognition_blocker=secondary,
                    earliest_near_candidate_date=(
                        None
                        if not symbol_onsets
                        else min(item.onset_date for item in symbol_onsets)
                    ),
                    explanation=_explanation(
                        events=len(events_by_symbol.get(symbol, ())),
                        onsets=symbol_onsets,
                        funnel=symbol_funnel,
                        candidates=symbol_candidates,
                    ),
                )
            )
        return tuple(rows)


def _blockers(rows: list[CandidateFunnelRecord]) -> tuple[str, str | None]:
    counts = Counter(
        item.failure_reason.value for item in rows if item.failure_reason is not None
    )
    ordered = [item for item, _ in counts.most_common()]
    return (
        ordered[0] if ordered else "NO_POINT_IN_TIME_TRADABLE_ONSET",
        ordered[1] if len(ordered) > 1 else None,
    )


def _explanation(
    *,
    events: int,
    onsets: list[TradableOpportunityOnset],
    funnel: list[CandidateFunnelRecord],
    candidates: list[CanonicalTradeEvent],
) -> ZeroCandidateExplanation:
    if not onsets:
        return (
            ZeroCandidateExplanation.NO_TRADABLE_OPPORTUNITY
            if events == 0
            else ZeroCandidateExplanation.CANONICAL_BEHAVIOR_CORRECT
        )
    reasons = {item.failure_reason for item in funnel}
    if CandidateFailureReason.SETUP_FAMILY_NOT_SUPPORTED in reasons:
        return ZeroCandidateExplanation.SETUP_VOCABULARY_GAP
    if candidates and any(
        item.setup_state in {"LATE", "INVALID"} for item in candidates
    ):
        return ZeroCandidateExplanation.TIMING_WINDOW_MISSED
    if CandidateFailureReason.PATTERN_THRESHOLD_TOO_STRICT in reasons:
        return ZeroCandidateExplanation.THRESHOLD_TOO_STRICT
    if any(
        item.failure_reason is CandidateFailureReason.IDENTITY_OR_CORPORATE_ACTION_BLOCK
        for item in funnel
    ):
        return ZeroCandidateExplanation.DATA_BLOCKED
    return ZeroCandidateExplanation.DETECTION_TOO_LATE


__all__ = ["ZeroCandidateClassificationEngine"]
