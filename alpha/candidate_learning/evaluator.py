from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.recommendation_intelligence.models import OHLCVBar

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_TWO = Decimal("0.01")

WINDOWS: tuple[tuple[str, int], ...] = (
    ("1d", 1),
    ("3d", 3),
    ("5d", 5),
    ("10d", 10),
    ("20d", 20),
    ("60d", 60),
)


class CandidateForwardOutcomeEvaluator:
    def evaluate(
        self,
        *,
        record: CandidateDecisionRecord,
        bars: tuple[OHLCVBar, ...],
    ) -> CandidateForwardOutcome:
        future_bars = tuple(
            sorted(
                (bar for bar in bars if bar.observed_on > record.evaluation_date),
                key=lambda bar: bar.observed_on,
            )
        )
        return CandidateForwardOutcome(
            candidate_id=record.candidate_id,
            symbol=record.symbol,
            evaluated_at=datetime.now(tz=UTC),
            windows=tuple(
                _window_outcome(record=record, bars=future_bars, label=label, size=size)
                for label, size in WINDOWS
            ),
        )


def _window_outcome(
    *,
    record: CandidateDecisionRecord,
    bars: tuple[OHLCVBar, ...],
    label: str,
    size: int,
) -> CandidateForwardWindowOutcome:
    if len(bars) < size:
        return CandidateForwardWindowOutcome(
            window=label,
            forward_open=None,
            forward_high=None,
            forward_low=None,
            forward_close=None,
            forward_return_pct_from_close=None,
            forward_return_pct_from_entry=None,
            max_favourable_excursion_pct=None,
            max_adverse_excursion_pct=None,
            target_1_touched=False,
            risk_stop_touched=False,
            outcome_label=CandidateOutcomeLabel.DATA_MISSING,
        )
    window = bars[:size]
    first = window[0]
    last = window[-1]
    high = max(bar.high_price for bar in window)
    low = min(bar.low_price for bar in window)
    target_touched = record.target_1 is not None and high >= record.target_1
    stop_touched = record.risk_stop is not None and low <= record.risk_stop
    entry = record.confirmation_entry or record.entry_zone_high or record.entry_zone_low
    return_from_close = _return_pct(first.open_price, last.close_price)
    return_from_entry = None if entry is None else _return_pct(entry, last.close_price)
    label_value = _label(
        target_touched=target_touched,
        stop_touched=stop_touched,
        return_pct=return_from_entry or return_from_close,
    )
    reference = entry or first.open_price
    return CandidateForwardWindowOutcome(
        window=label,
        forward_open=first.open_price,
        forward_high=high,
        forward_low=low,
        forward_close=last.close_price,
        forward_return_pct_from_close=return_from_close,
        forward_return_pct_from_entry=return_from_entry,
        max_favourable_excursion_pct=_return_pct(reference, high),
        max_adverse_excursion_pct=_return_pct(reference, low),
        target_1_touched=target_touched,
        risk_stop_touched=stop_touched,
        outcome_label=label_value,
    )


def _label(
    *,
    target_touched: bool,
    stop_touched: bool,
    return_pct: Decimal,
) -> CandidateOutcomeLabel:
    if stop_touched:
        return CandidateOutcomeLabel.WOULD_HAVE_LOST
    if target_touched:
        return CandidateOutcomeLabel.WOULD_HAVE_WON
    if return_pct >= Decimal("3"):
        return CandidateOutcomeLabel.WOULD_HAVE_WON
    if return_pct <= Decimal("-2"):
        return CandidateOutcomeLabel.WOULD_HAVE_LOST
    return CandidateOutcomeLabel.NEUTRAL


def _return_pct(start: Decimal, end: Decimal) -> Decimal:
    if start <= _ZERO:
        return _ZERO
    return ((end - start) / start * _HUNDRED).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


__all__ = ["CandidateForwardOutcomeEvaluator", "WINDOWS"]
