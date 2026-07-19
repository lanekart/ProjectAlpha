from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from statistics import median

from alpha.candidate_generation_research.models import (
    CandidateFunnelRecord,
    OpportunityFamily,
    SetupRecognitionMetric,
    StageStatus,
    TradableOpportunityOnset,
)
from alpha.canonical_integrity_audit.models import CanonicalTradeEvent

CANONICAL_SETUP_FAMILIES = (
    "Bull Flag",
    "EMA Pullback",
    "VCP",
    "Cup and Handle",
    "Flat Base",
    "Failed Breakout",
    "Trend Failure",
    "No Valid Setup",
)

_COMPATIBILITY = {
    "Bull Flag": {
        OpportunityFamily.BREAKOUT_FROM_BASE,
        OpportunityFamily.PULLBACK_CONTINUATION,
    },
    "EMA Pullback": {
        OpportunityFamily.EMA_RECLAIM,
        OpportunityFamily.PULLBACK_CONTINUATION,
        OpportunityFamily.RETEST_HOLD,
    },
    "VCP": {OpportunityFamily.VOLATILITY_CONTRACTION_BREAKOUT},
    "Cup and Handle": {OpportunityFamily.BREAKOUT_FROM_BASE},
    "Flat Base": {
        OpportunityFamily.BREAKOUT_FROM_BASE,
        OpportunityFamily.VOLUME_BREAKOUT,
    },
    "Failed Breakout": {OpportunityFamily.FAILED_BREAKOUT_REVERSAL},
    "Trend Failure": set(),
    "No Valid Setup": set(),
}


class SetupRecognitionAuditEngine:
    def measure(
        self,
        *,
        onsets: tuple[TradableOpportunityOnset, ...],
        funnel: tuple[CandidateFunnelRecord, ...],
        candidates: tuple[CanonicalTradeEvent, ...],
    ) -> tuple[SetupRecognitionMetric, ...]:
        onset_by_id = {item.onset_id: item for item in onsets}
        candidate_by_id = {item.candidate_id: item for item in candidates}
        matched_candidate_ids = {
            item.canonical_candidate_id
            for item in funnel
            if item.canonical_candidate_id is not None
        }
        unmatched_by_setup: dict[str, int] = defaultdict(int)
        for candidate_row in candidates:
            if candidate_row.candidate_id not in matched_candidate_ids:
                unmatched_by_setup[_canonical_name(candidate_row.setup)] += 1
        rows = []
        for family in CANONICAL_SETUP_FAMILIES:
            compatible_families = _COMPATIBILITY[family]
            compatible = tuple(
                item for item in onsets if item.event_family in compatible_families
            )
            compatible_ids = {item.onset_id for item in compatible}
            detections = []
            delays = []
            for trace in funnel:
                if trace.onset_id is None or trace.canonical_candidate_id is None:
                    continue
                onset = onset_by_id.get(trace.onset_id)
                candidate: CanonicalTradeEvent | None = candidate_by_id.get(
                    trace.canonical_candidate_id
                )
                if onset is None or candidate is None:
                    continue
                if onset.event_family not in compatible_families:
                    continue
                if _canonical_name(candidate.setup) != family:
                    continue
                detections.append(trace)
                delays.append(max((candidate.observed_on - onset.onset_date).days, 0))
            false_positives = unmatched_by_setup[family]
            denominator = len(detections) + false_positives
            rows.append(
                SetupRecognitionMetric(
                    setup_family=family,
                    compatible_tradable_onsets=len(compatible),
                    canonical_detections=len(detections),
                    false_negatives=max(len(compatible) - len(detections), 0),
                    false_positives=false_positives,
                    precision=(
                        None
                        if denominator == 0
                        else Decimal(len(detections)) / Decimal(denominator)
                    ),
                    recall=(
                        None
                        if not compatible
                        else Decimal(len(detections)) / Decimal(len(compatible))
                    ),
                    median_detection_delay=(
                        None if not delays else Decimal(str(median(delays)))
                    ),
                    median_extension_at_detection=None,
                    captured_forward_move_share=(
                        None
                        if not compatible
                        else Decimal(
                            sum(
                                item.canonical_setup_recognized is StageStatus.PASS
                                for item in funnel
                                if item.onset_id in compatible_ids
                            )
                        )
                        / Decimal(len(compatible))
                    ),
                )
            )
        return tuple(rows)


def _canonical_name(value: str) -> str:
    normalized = value.strip().upper().replace("_", " ")
    for family in CANONICAL_SETUP_FAMILIES:
        if family.upper() == normalized:
            return family
    return "No Valid Setup"


__all__ = ["CANONICAL_SETUP_FAMILIES", "SetupRecognitionAuditEngine"]
