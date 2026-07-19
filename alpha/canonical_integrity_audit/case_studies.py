from __future__ import annotations

from decimal import Decimal

from alpha.canonical_integrity_audit.models import (
    CanonicalTradeEvent,
    CaseStudy,
    MajorOpportunityEvent,
    OpportunityCoverageRecord,
    RuntimeFailureRecord,
)

MANDATORY_CASE_STUDIES = (
    "KALYANKJIL",
    "PCJEWELLER",
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "LT",
    "TATASTEEL",
)

_ALIASES = {
    "KALYANKJIL": ("KALYANKJIL", "KALYAN", "KALYANJEWELLERS"),
    "PCJEWELLER": ("PCJEWELLER", "PCJEWELLERS", "PCJEWELLERLTD"),
}


class CaseStudyEngine:
    def build(
        self,
        *,
        requested_symbols: tuple[str, ...] = MANDATORY_CASE_STUDIES,
        available_symbols: tuple[str, ...],
        events: tuple[MajorOpportunityEvent, ...],
        coverage: tuple[OpportunityCoverageRecord, ...],
        candidates: tuple[CanonicalTradeEvent, ...],
        runtime_failures: tuple[RuntimeFailureRecord, ...] = (),
    ) -> tuple[CaseStudy, ...]:
        available = {item.upper() for item in available_symbols}
        coverage_by_event = {item.event_id: item for item in coverage}
        studies = []
        for requested in requested_symbols:
            resolved = _resolve(requested, available)
            symbol_events = tuple(
                item
                for item in events
                if resolved is not None and item.symbol == resolved
            )
            selected = (
                max(symbol_events, key=lambda item: item.forward_return)
                if symbol_events
                else None
            )
            event_coverage = (
                None if selected is None else coverage_by_event.get(selected.event_id)
            )
            candidate = _candidate_for(selected, candidates)
            runtime = any(
                item.symbol == resolved
                and selected is not None
                and selected.start_date <= item.trading_date <= selected.peak_date
                for item in runtime_failures
            )
            studies.append(
                _study(
                    requested=requested,
                    resolved=resolved,
                    event=selected,
                    coverage=event_coverage,
                    candidate=candidate,
                    runtime=runtime,
                )
            )
        return tuple(studies)


def _study(
    *,
    requested: str,
    resolved: str | None,
    event: MajorOpportunityEvent | None,
    coverage: OpportunityCoverageRecord | None,
    candidate: CanonicalTradeEvent | None,
    runtime: bool,
) -> CaseStudy:
    if event is None:
        return CaseStudy(
            requested_symbol=requested,
            resolved_symbol=resolved,
            event_ids=(),
            major_move_definition="NO_QUALIFYING_EVENT",
            event_dates="UNAVAILABLE",
            candidate_creation_status="UNAVAILABLE",
            setup_detection="UNAVAILABLE",
            component_scores={"status": "UNAVAILABLE_IN_ACU_ARTIFACT"},
            final_score=None,
            verdict="UNAVAILABLE",
            entry_timing_state="UNAVAILABLE",
            approval_result="UNAVAILABLE",
            trade_plan_result="UNAVAILABLE",
            runtime_state="NO_RELEVANT_EVENT",
            coverage_classification="DATA_BLOCKED",
            primary_reason="No qualifying bounded event exists for this symbol.",
        )
    return CaseStudy(
        requested_symbol=requested,
        resolved_symbol=resolved,
        event_ids=(event.event_id,),
        major_move_definition=(
            f"{event.event_definition}: {event.forward_return * Decimal('100'):.2f}%"
        ),
        event_dates=(
            f"{event.start_date.isoformat()} to {event.peak_date.isoformat()}"
        ),
        candidate_creation_status="CREATED" if candidate is not None else "NOT_CREATED",
        setup_detection="NOT_DETECTED" if candidate is None else candidate.setup,
        component_scores={
            "final_score": "UNAVAILABLE"
            if candidate is None or candidate.score is None
            else str(candidate.score),
            "component_breakdown": "UNAVAILABLE_IN_ACU_ARTIFACT",
        },
        final_score=None if candidate is None else candidate.score,
        verdict="UNAVAILABLE" if candidate is None else candidate.final_signal,
        entry_timing_state="UNAVAILABLE"
        if candidate is None
        else candidate.setup_state,
        approval_result=(
            "UNAVAILABLE"
            if candidate is None
            else "PASSED"
            if candidate.rejection_reason is None
            else candidate.final_gate
        ),
        trade_plan_result=(
            "UNAVAILABLE"
            if candidate is None
            else "VALID"
            if _valid_plan(candidate)
            else "INVALID_OR_MISSING"
        ),
        runtime_state="BLOCKED" if runtime else "AVAILABLE",
        coverage_classification=(
            "UNSCORABLE" if coverage is None else coverage.classification.value
        ),
        primary_reason=(
            "Coverage evidence is unavailable."
            if coverage is None
            else coverage.primary_blocker or "Alpha captured the bounded move."
        ),
    )


def _resolve(requested: str, available: set[str]) -> str | None:
    for alias in _ALIASES.get(requested, (requested,)):
        if alias in available:
            return alias
    return None


def _candidate_for(
    event: MajorOpportunityEvent | None,
    candidates: tuple[CanonicalTradeEvent, ...],
) -> CanonicalTradeEvent | None:
    if event is None:
        return None
    relevant = tuple(
        item
        for item in candidates
        if item.symbol == event.symbol
        and event.start_date <= item.observed_on <= event.peak_date
    )
    return min(relevant, key=lambda item: item.observed_on) if relevant else None


def _valid_plan(candidate: CanonicalTradeEvent) -> bool:
    return (
        candidate.entry is not None
        and candidate.stop is not None
        and candidate.targets[0] is not None
        and candidate.stop < candidate.entry < candidate.targets[0]
    )


__all__ = ["MANDATORY_CASE_STUDIES", "CaseStudyEngine"]
