from __future__ import annotations

from collections import Counter
from decimal import Decimal

from alpha.canonical_integrity_audit.models import (
    CanonicalTradeEvent,
    ParityClassification,
    ParityDivergenceSummary,
    PineAlphaTradeMatch,
    PineTrade,
    RuntimeFailureRecord,
)
from alpha.canonical_integrity_audit.parity_matching import match_pine_trade


class TradingViewParityEngine:
    def compare(
        self,
        *,
        pine_trades: tuple[PineTrade, ...],
        alpha_events: tuple[CanonicalTradeEvent, ...],
        runtime_failures: tuple[RuntimeFailureRecord, ...] = (),
    ) -> tuple[tuple[PineAlphaTradeMatch, ...], tuple[ParityDivergenceSummary, ...]]:
        matches = tuple(
            match_pine_trade(trade, alpha_events, runtime_failures)
            for trade in sorted(pine_trades, key=lambda item: item.trade_id)
        )
        counts = Counter(item.classification.value for item in matches)
        total = len(matches)
        divergences = tuple(
            ParityDivergenceSummary(
                divergence_stage=stage,
                count=count,
                share=(Decimal(count) / Decimal(total) if total else Decimal("0")),
            )
            for stage, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )
            if stage
            not in {
                ParityClassification.EXACT_MATCH.value,
                ParityClassification.SEMANTIC_MATCH.value,
            }
        )
        return matches, divergences


__all__ = ["TradingViewParityEngine"]
