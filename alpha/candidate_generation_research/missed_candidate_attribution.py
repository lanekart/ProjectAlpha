from __future__ import annotations

from collections import Counter

from alpha.candidate_generation_research.models import (
    CandidateCoverage,
    CandidateFunnelRecord,
    CandidateTimingRecord,
    MissedCandidateAttribution,
    TimingClassification,
)


class MissedCandidateAttributionEngine:
    def attribute(
        self,
        *,
        funnel: tuple[CandidateFunnelRecord, ...],
        timing: tuple[CandidateTimingRecord, ...],
    ) -> tuple[MissedCandidateAttribution, ...]:
        timing_by_event = {item.event_id: item for item in timing}
        rows = []
        for item in funnel:
            if item.coverage in {
                CandidateCoverage.CAPTURED_BY_CANONICAL,
                CandidateCoverage.PARTIALLY_CAPTURED_BY_CANONICAL,
            }:
                continue
            timing_row = timing_by_event.get(item.event_id)
            primary = _primary(item, timing_row)
            secondary = (
                None
                if item.failure_reason is None or item.failure_reason.value == primary
                else item.failure_reason.value
            )
            rows.append(
                MissedCandidateAttribution(
                    event_id=item.event_id,
                    onset_id=item.onset_id,
                    symbol=item.symbol,
                    coverage=item.coverage,
                    primary_blocker=primary,
                    secondary_blocker=secondary,
                    canonical_candidate_date=(
                        None
                        if timing_row is None
                        else timing_row.canonical_candidate_date
                    ),
                    evidence=item.evidence_limitation or "Frozen canonical trace.",
                )
            )
        return tuple(rows)

    @staticmethod
    def primary_blocker(
        rows: tuple[MissedCandidateAttribution, ...],
    ) -> str:
        counts = Counter(item.primary_blocker for item in rows)
        return counts.most_common(1)[0][0] if counts else "UNAVAILABLE"


def _primary(
    item: CandidateFunnelRecord,
    timing: CandidateTimingRecord | None,
) -> str:
    if item.coverage is CandidateCoverage.NOT_ACTUALLY_TRADABLE:
        return "NO_POINT_IN_TIME_TRADABLE_ONSET"
    if item.coverage is CandidateCoverage.DATA_BLOCKED:
        return "IDENTITY_OR_CORPORATE_ACTION_BLOCK"
    if timing is not None and timing.classification in {
        TimingClassification.EXTENDED_BEFORE_DETECTION,
        TimingClassification.MISSED_TIMING_WINDOW,
    }:
        return timing.classification.value
    if item.failure_reason is not None:
        return item.failure_reason.value
    return item.coverage.value


__all__ = ["MissedCandidateAttributionEngine"]
