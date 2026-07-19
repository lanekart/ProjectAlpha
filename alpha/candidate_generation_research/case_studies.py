from __future__ import annotations

from collections import defaultdict

from alpha.candidate_generation_research.models import (
    CandidateCaseStudy,
    CandidateFunnelRecord,
    CandidateTimingRecord,
    CandidateVariantResult,
    TradableOpportunityOnset,
)
from alpha.canonical_integrity_audit.models import MajorOpportunityEvent

MANDATORY_CASES = (
    "KALYANKJIL",
    "PCJEWELLER",
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "LT",
    "TATASTEEL",
)


class CandidateResearchCaseStudyEngine:
    def build(
        self,
        *,
        events: tuple[MajorOpportunityEvent, ...],
        onsets: tuple[TradableOpportunityOnset, ...],
        funnel: tuple[CandidateFunnelRecord, ...],
        timing: tuple[CandidateTimingRecord, ...],
        variants: tuple[CandidateVariantResult, ...],
        available_symbols: tuple[str, ...],
    ) -> tuple[CandidateCaseStudy, ...]:
        aliases = _aliases(available_symbols)
        events_by_symbol: dict[str, list[MajorOpportunityEvent]] = defaultdict(list)
        for event_row in events:
            events_by_symbol[event_row.symbol].append(event_row)
        onset_by_event: dict[str, list[TradableOpportunityOnset]] = defaultdict(list)
        for onset_row in onsets:
            if onset_row.forward_event_id is not None:
                onset_by_event[onset_row.forward_event_id].append(onset_row)
        funnel_by_event = {item.event_id: item for item in funnel}
        timing_by_event = {item.event_id: item for item in timing}
        variant_lines = _variant_lines(variants)
        rows = []
        for requested in MANDATORY_CASES:
            resolved = aliases.get(requested)
            event: MajorOpportunityEvent | None = _largest(
                events_by_symbol.get(resolved or "", ())
            )
            onset: TradableOpportunityOnset | None = (
                None
                if event is None
                else min(
                    onset_by_event.get(event.event_id, ()),
                    key=lambda item: item.onset_sequence,
                    default=None,
                )
            )
            trace = None if event is None else funnel_by_event.get(event.event_id)
            timing_row = None if event is None else timing_by_event.get(event.event_id)
            rows.append(
                _study(
                    requested=requested,
                    resolved=resolved,
                    event=event,
                    onset=onset,
                    trace=trace,
                    timing=timing_row,
                    variant_lines=variant_lines,
                )
            )
        return tuple(rows)


def _study(
    *,
    requested: str,
    resolved: str | None,
    event: MajorOpportunityEvent | None,
    onset: TradableOpportunityOnset | None,
    trace: CandidateFunnelRecord | None,
    timing: CandidateTimingRecord | None,
    variant_lines: tuple[str, ...],
) -> CandidateCaseStudy:
    if event is None:
        return CandidateCaseStudy(
            requested_symbol=requested,
            resolved_symbol=resolved,
            forward_move_definition="UNAVAILABLE",
            onset_date=None,
            setup_family="NO_TRADABLE_ONSET",
            base_or_reversal_evidence="UNAVAILABLE",
            volume_evidence="UNAVAILABLE",
            trend_evidence="UNAVAILABLE",
            relative_strength_evidence="UNAVAILABLE",
            prospective_stop=None,
            prospective_target=None,
            prospective_rr=None,
            canonical_setup_result="UNAVAILABLE",
            canonical_candidate_result="UNAVAILABLE",
            canonical_timing_result="UNAVAILABLE",
            candidate_variant_results=variant_lines,
            coverage_classification="UNAVAILABLE",
            primary_reason="No comparable forward-move event exists.",
        )
    if onset is None:
        return CandidateCaseStudy(
            requested_symbol=requested,
            resolved_symbol=resolved,
            forward_move_definition=(
                f"{event.event_definition}: {event.forward_return * 100:.2f}%"
            ),
            onset_date=None,
            setup_family="NO_TRADABLE_ONSET",
            base_or_reversal_evidence="No point-in-time structure passed tradability.",
            volume_evidence="No qualifying onset volume evidence.",
            trend_evidence=event.trend_state,
            relative_strength_evidence=(
                "UNAVAILABLE: benchmark history not authoritative"
            ),
            prospective_stop=None,
            prospective_target=None,
            prospective_rr=None,
            canonical_setup_result="NOT_APPLICABLE",
            canonical_candidate_result="NOT_APPLICABLE",
            canonical_timing_result="NOT_APPLICABLE",
            candidate_variant_results=variant_lines,
            coverage_classification=(
                "NOT_ACTUALLY_TRADABLE" if trace is None else trace.coverage.value
            ),
            primary_reason=(
                "The later advance is an outcome label, but no valid entry was visible "
                "under the frozen point-in-time tradability definition."
            ),
        )
    evidence = set(onset.setup_evidence)
    return CandidateCaseStudy(
        requested_symbol=requested,
        resolved_symbol=resolved,
        forward_move_definition=(
            f"{event.event_definition}: {event.forward_return * 100:.2f}%"
        ),
        onset_date=onset.onset_date,
        setup_family=onset.event_family.value,
        base_or_reversal_evidence=_matching(evidence, ("base", "family=")),
        volume_evidence=_matching(evidence, ("volume", "turnover")),
        trend_evidence=_matching(evidence, ("ema", "resistance")),
        relative_strength_evidence=(
            "UNAVAILABLE: benchmark history not authoritative"
            if onset.point_in_time_inputs.get("relative_strength_20") == "UNAVAILABLE"
            else (
                "20-session relative strength "
                f"{onset.point_in_time_inputs.get('relative_strength_20')}"
            )
        ),
        prospective_stop=onset.prospective_stop,
        prospective_target=onset.prospective_target,
        prospective_rr=onset.prospective_rr,
        canonical_setup_result=(
            "UNAVAILABLE" if trace is None else trace.canonical_setup_recognized.value
        ),
        canonical_candidate_result=(
            "UNAVAILABLE" if trace is None else trace.canonical_candidate_created.value
        ),
        canonical_timing_result=(
            "UNAVAILABLE" if timing is None else timing.classification.value
        ),
        candidate_variant_results=variant_lines,
        coverage_classification=(
            "UNAVAILABLE" if trace is None else trace.coverage.value
        ),
        primary_reason=(
            "UNAVAILABLE"
            if trace is None
            else trace.failure_reason.value
            if trace.failure_reason is not None
            else trace.coverage.value
        ),
    )


def _aliases(symbols: tuple[str, ...]) -> dict[str, str]:
    available = set(symbols)
    result = {}
    for requested in MANDATORY_CASES:
        candidates = {
            requested,
            requested.replace("JEWELLER", "JEWELLERS"),
            requested.replace("KJIL", "KJIL-EQ"),
        }
        match = next((item for item in sorted(candidates) if item in available), None)
        if match is not None:
            result[requested] = match
    return result


def _largest(
    values: list[MajorOpportunityEvent] | tuple[MajorOpportunityEvent, ...],
) -> MajorOpportunityEvent | None:
    return max(values, key=lambda item: item.forward_return, default=None)


def _matching(values: set[str], fragments: tuple[str, ...]) -> str:
    selected = sorted(
        item for item in values if any(fragment in item for fragment in fragments)
    )
    return "; ".join(selected) if selected else "No qualifying evidence recorded."


def _variant_lines(values: tuple[CandidateVariantResult, ...]) -> tuple[str, ...]:
    return tuple(
        f"{item.variant_id}/{item.partition.value}: {'PASS' if item.passed else 'FAIL'}"
        for item in values
        if item.partition.value in {"VALIDATION", "HOLDOUT"}
    )


__all__ = ["MANDATORY_CASES", "CandidateResearchCaseStudyEngine"]
