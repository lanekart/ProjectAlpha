from __future__ import annotations

from collections import defaultdict

from alpha.candidate_generation_research.models import (
    PineCandidateParity,
    PineCandidateParityRecord,
    TradableOpportunityOnset,
)
from alpha.canonical_integrity_audit.models import CanonicalTradeEvent, PineTrade


class PineCandidateParityEngine:
    def compare(
        self,
        *,
        pine_trades: tuple[PineTrade, ...],
        onsets: tuple[TradableOpportunityOnset, ...],
        candidates: tuple[CanonicalTradeEvent, ...],
    ) -> tuple[PineCandidateParityRecord, ...]:
        onsets_by_symbol: dict[str, list[TradableOpportunityOnset]] = defaultdict(list)
        candidates_by_symbol: dict[str, list[CanonicalTradeEvent]] = defaultdict(list)
        for onset_row in onsets:
            onsets_by_symbol[onset_row.symbol].append(onset_row)
        for candidate_row in candidates:
            candidates_by_symbol[candidate_row.symbol].append(candidate_row)
        rows = []
        for pine in pine_trades:
            onset = min(
                (
                    item
                    for item in onsets_by_symbol.get(pine.symbol, ())
                    if abs((item.onset_date - pine.entry_date).days) <= 10
                ),
                key=lambda item: abs((item.onset_date - pine.entry_date).days),
                default=None,
            )
            candidate = min(
                (
                    item
                    for item in candidates_by_symbol.get(pine.symbol, ())
                    if abs((item.observed_on - pine.entry_date).days) <= 10
                ),
                key=lambda item: abs((item.observed_on - pine.entry_date).days),
                default=None,
            )
            classification, explanation = _classification(pine, onset, candidate)
            rows.append(
                PineCandidateParityRecord(
                    pine_trade_id=pine.trade_id,
                    symbol=pine.symbol,
                    pine_entry_date=pine.entry_date,
                    pine_setup=pine.setup_family,
                    onset_id=None if onset is None else onset.onset_id,
                    canonical_candidate_id=(
                        None if candidate is None else candidate.candidate_id
                    ),
                    classification=classification,
                    explanation=explanation,
                )
            )
        return tuple(rows)


def _classification(
    pine: PineTrade,
    onset: TradableOpportunityOnset | None,
    candidate: CanonicalTradeEvent | None,
) -> tuple[PineCandidateParity, str]:
    if onset is None and candidate is None:
        return (
            PineCandidateParity.UNMATCHED,
            "No comparable point-in-time onset or canonical candidate.",
        )
    if candidate is None:
        return (
            PineCandidateParity.PINE_ONLY_APPROXIMATION,
            "Pine entry aligns with a research onset but no canonical candidate.",
        )
    delay = (candidate.observed_on - pine.entry_date).days
    if delay > 2:
        return (
            PineCandidateParity.PINE_DETECTS_EARLIER,
            f"Pine entry preceded canonical detection by {delay} calendar days.",
        )
    if _normalize(pine.setup_family) != _normalize(candidate.setup):
        return (
            PineCandidateParity.PINE_DETECTS_DIFFERENT_SETUP,
            "Entry timing aligns but setup labels differ.",
        )
    if abs(delay) <= 2:
        return (
            PineCandidateParity.PINE_AND_ALPHA_AGREE,
            "Candidate recognition aligns within two calendar days.",
        )
    return (
        PineCandidateParity.TIMING_DIFFERENCE,
        "Candidate dates differ outside the parity tolerance.",
    )


def _normalize(value: str) -> str:
    return value.strip().upper().replace("_", " ")


__all__ = ["PineCandidateParityEngine"]
