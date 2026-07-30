"""Pre-registered five-minute entry mechanisms for DSI-013."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from statistics import median

from alpha.decision_superiority.intraday_execution_models import (
    IntradayBar,
    IntradayExecutionError,
    IntradayExecutionPolicy,
    IntradayMechanismId,
)
from alpha.decision_superiority.intraday_execution_population import (
    IntradayCandidate,
)

OPENING_RANGE_TIMES = (time(9, 15), time(9, 20), time(9, 25))
ORB_EVALUATION_START = time(9, 30)
CLOSING_EVALUATION_START = time(14, 30)
CLOSING_EVALUATION_END = time(15, 10)


class IntradayEntryState(StrEnum):
    """Deterministic terminal state for one candidate/mechanism pair."""

    ENTERED = "ENTERED"
    NOT_ENTERED = "NOT_ENTERED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    NEXT_BAR_UNAVAILABLE = "NEXT_BAR_UNAVAILABLE"
    ENTRY_CUTOFF_EXCEEDED = "ENTRY_CUTOFF_EXCEEDED"


@dataclass(frozen=True, slots=True)
class IntradayEntryFill:
    """One immutable control or challenger entry result."""

    signal_id: str
    identity_key: str
    session_date: str
    mechanism_id: IntradayMechanismId
    state: IntradayEntryState
    reason: str
    trigger_timestamp: datetime | None
    fill_timestamp: datetime | None
    raw_fill_price: float | None
    fill_price_after_slippage: float | None
    control_raw_entry_price: float
    raw_price_delta_vs_control: float | None
    trigger_vwap: float | None
    opening_range_high: float | None
    cumulative_volume_at_trigger: int | None
    fill_bar_volume: int | None


@dataclass(frozen=True, slots=True)
class _FeatureBar:
    bar: IntradayBar
    vwap: float | None
    cumulative_volume: int
    session_high: float
    prior_volume_median: float | None


def evaluate_intraday_entries(
    candidate: IntradayCandidate,
    bars: Sequence[IntradayBar],
    *,
    comparable_session_median_volume: float | None = None,
    policy: IntradayExecutionPolicy | None = None,
) -> tuple[IntradayEntryFill, ...]:
    """Evaluate the frozen control and four DSI-013 challengers exactly once."""

    active_policy = policy or IntradayExecutionPolicy()
    ordered = _validated_session(candidate, bars)
    features = _features(ordered)
    opening_high = _opening_range_high(ordered)
    return (
        _control(candidate, ordered),
        _orb15(candidate, features, opening_high, active_policy),
        _vwap_reclaim(candidate, features, opening_high, active_policy),
        _first_pullback(candidate, features, opening_high, active_policy),
        _closing_continuation(
            candidate,
            features,
            opening_high,
            comparable_session_median_volume,
            active_policy,
        ),
    )


def _validated_session(
    candidate: IntradayCandidate,
    bars: Sequence[IntradayBar],
) -> tuple[IntradayBar, ...]:
    ordered = tuple(sorted(bars, key=lambda item: item.timestamp))
    if not ordered:
        raise IntradayExecutionError(
            f"DSI013_ENTRY_SESSION_EMPTY:{candidate.signal_id}"
        )
    if any(bar.governed_identity != candidate.identity_key for bar in ordered):
        raise IntradayExecutionError(
            f"DSI013_ENTRY_IDENTITY_MISMATCH:{candidate.signal_id}"
        )
    if any(bar.timestamp.date() != candidate.entry_session for bar in ordered):
        raise IntradayExecutionError(
            f"DSI013_ENTRY_SESSION_DATE_MISMATCH:{candidate.signal_id}"
        )
    timestamps = [bar.timestamp for bar in ordered]
    if len(timestamps) != len(set(timestamps)):
        raise IntradayExecutionError(
            f"DSI013_ENTRY_DUPLICATE_TIMESTAMP:{candidate.signal_id}"
        )
    return ordered


def _features(bars: Sequence[IntradayBar]) -> tuple[_FeatureBar, ...]:
    cumulative_volume = 0
    cumulative_value = 0.0
    session_high = 0.0
    prior_volumes: list[int] = []
    rows: list[_FeatureBar] = []
    for bar in bars:
        typical_price = (bar.high + bar.low + bar.close) / 3.0
        cumulative_volume += bar.volume
        cumulative_value += typical_price * bar.volume
        session_high = max(session_high, bar.high)
        current_vwap = (
            None
            if cumulative_volume <= 0
            else cumulative_value / float(cumulative_volume)
        )
        rows.append(
            _FeatureBar(
                bar=bar,
                vwap=current_vwap,
                cumulative_volume=cumulative_volume,
                session_high=session_high,
                prior_volume_median=(
                    None if not prior_volumes else float(median(prior_volumes))
                ),
            )
        )
        prior_volumes.append(bar.volume)
    return tuple(rows)


def _opening_range_high(bars: Sequence[IntradayBar]) -> float | None:
    by_time = {_local_time(bar): bar for bar in bars}
    opening = [by_time.get(value) for value in OPENING_RANGE_TIMES]
    if any(bar is None for bar in opening):
        return None
    return max(bar.high for bar in opening if bar is not None)


def _control(
    candidate: IntradayCandidate,
    bars: Sequence[IntradayBar],
) -> IntradayEntryFill:
    first = bars[0]
    return IntradayEntryFill(
        signal_id=candidate.signal_id,
        identity_key=candidate.identity_key,
        session_date=candidate.entry_session.isoformat(),
        mechanism_id=IntradayMechanismId.NEXT_SESSION_OPEN,
        state=IntradayEntryState.ENTERED,
        reason="SIGNED_DSI009_CONTROL_FILL",
        trigger_timestamp=None,
        fill_timestamp=first.timestamp,
        raw_fill_price=candidate.signed_raw_entry_price,
        fill_price_after_slippage=candidate.signed_entry_price_after_slippage,
        control_raw_entry_price=candidate.signed_raw_entry_price,
        raw_price_delta_vs_control=0.0,
        trigger_vwap=None,
        opening_range_high=None,
        cumulative_volume_at_trigger=None,
        fill_bar_volume=first.volume,
    )


def _orb15(
    candidate: IntradayCandidate,
    features: Sequence[_FeatureBar],
    opening_high: float | None,
    policy: IntradayExecutionPolicy,
) -> IntradayEntryFill:
    mechanism = IntradayMechanismId.ORB15_BREAKOUT
    if opening_high is None:
        return _unavailable(candidate, mechanism, "OPENING_RANGE_INCOMPLETE")
    for index, feature in enumerate(features):
        if _local_time(feature.bar) < ORB_EVALUATION_START:
            continue
        if feature.bar.close > opening_high:
            return _next_bar_fill(
                candidate,
                mechanism,
                features,
                index,
                opening_high=opening_high,
                cutoff=policy.last_standard_entry,
                policy=policy,
                reason="CLOSE_ABOVE_ORB15_HIGH",
            )
    return _not_entered(candidate, mechanism, "ORB15_BREAKOUT_NOT_TRIGGERED")


def _vwap_reclaim(
    candidate: IntradayCandidate,
    features: Sequence[_FeatureBar],
    opening_high: float | None,
    policy: IntradayExecutionPolicy,
) -> IntradayEntryFill:
    mechanism = IntradayMechanismId.VWAP_RECLAIM
    seen_below = False
    for index, feature in enumerate(features):
        if feature.vwap is None:
            continue
        if feature.bar.close < feature.vwap:
            seen_below = True
            continue
        if (
            seen_below
            and feature.bar.close > feature.vwap
            and feature.prior_volume_median is not None
            and feature.bar.volume > feature.prior_volume_median
        ):
            return _next_bar_fill(
                candidate,
                mechanism,
                features,
                index,
                opening_high=opening_high,
                cutoff=policy.last_standard_entry,
                policy=policy,
                reason="ABOVE_VWAP_AFTER_BELOW_WITH_VOLUME",
            )
    return _not_entered(candidate, mechanism, "VWAP_RECLAIM_NOT_TRIGGERED")


def _first_pullback(
    candidate: IntradayCandidate,
    features: Sequence[_FeatureBar],
    opening_high: float | None,
    policy: IntradayExecutionPolicy,
) -> IntradayEntryFill:
    mechanism = IntradayMechanismId.FIRST_PULLBACK
    if opening_high is None:
        return _unavailable(candidate, mechanism, "OPENING_RANGE_INCOMPLETE")
    impulse_index = next(
        (
            index
            for index, feature in enumerate(features)
            if _local_time(feature.bar) >= ORB_EVALUATION_START
            and feature.bar.close > opening_high
        ),
        None,
    )
    if impulse_index is None:
        return _not_entered(candidate, mechanism, "INITIAL_ORB_MOVE_NOT_PRESENT")
    impulse_volume = sum(
        feature.bar.volume for feature in features[3 : impulse_index + 1]
    )
    pullback: list[_FeatureBar] = []
    for index in range(impulse_index + 1, len(features)):
        feature = features[index]
        if feature.vwap is None:
            return _unavailable(candidate, mechanism, "PULLBACK_VWAP_UNAVAILABLE")
        if feature.bar.close < feature.vwap:
            return _not_entered(candidate, mechanism, "FIRST_PULLBACK_BROKE_VWAP")
        previous = features[index - 1]
        pullback_volume = sum(item.bar.volume for item in pullback)
        if (
            len(pullback) >= 2
            and feature.bar.close > previous.bar.high
            and pullback_volume < impulse_volume
        ):
            return _next_bar_fill(
                candidate,
                mechanism,
                features,
                index,
                opening_high=opening_high,
                cutoff=policy.last_standard_entry,
                policy=policy,
                reason="FIRST_LOW_VOLUME_PULLBACK_RESOLVED",
            )
        pullback.append(feature)
    return _not_entered(candidate, mechanism, "FIRST_PULLBACK_NOT_TRIGGERED")


def _closing_continuation(
    candidate: IntradayCandidate,
    features: Sequence[_FeatureBar],
    opening_high: float | None,
    comparable_session_median_volume: float | None,
    policy: IntradayExecutionPolicy,
) -> IntradayEntryFill:
    mechanism = IntradayMechanismId.CLOSING_CONTINUATION
    if opening_high is None:
        return _unavailable(candidate, mechanism, "OPENING_RANGE_INCOMPLETE")
    if (
        comparable_session_median_volume is None
        or comparable_session_median_volume <= 0
    ):
        return _unavailable(
            candidate,
            mechanism,
            "COMPARABLE_SESSION_MEDIAN_VOLUME_UNAVAILABLE",
        )
    threshold = comparable_session_median_volume * 1.25
    for index, feature in enumerate(features):
        local_time = _local_time(feature.bar)
        if not CLOSING_EVALUATION_START <= local_time <= CLOSING_EVALUATION_END:
            continue
        if feature.vwap is None:
            continue
        if (
            feature.bar.close > feature.vwap
            and feature.bar.close > opening_high
            and feature.bar.close >= feature.session_high * 0.995
            and feature.cumulative_volume >= threshold
        ):
            return _next_bar_fill(
                candidate,
                mechanism,
                features,
                index,
                opening_high=opening_high,
                cutoff=policy.final_closing_fill,
                policy=policy,
                reason="LATE_SESSION_VWAP_ORB_HIGH_CONTINUATION",
            )
    return _not_entered(candidate, mechanism, "CLOSING_CONTINUATION_NOT_TRIGGERED")


def _next_bar_fill(
    candidate: IntradayCandidate,
    mechanism: IntradayMechanismId,
    features: Sequence[_FeatureBar],
    trigger_index: int,
    *,
    opening_high: float | None,
    cutoff: time,
    policy: IntradayExecutionPolicy,
    reason: str,
) -> IntradayEntryFill:
    trigger = features[trigger_index]
    next_index = trigger_index + 1
    if next_index >= len(features):
        return _terminal(
            candidate,
            mechanism,
            IntradayEntryState.NEXT_BAR_UNAVAILABLE,
            "QUALIFYING_TRIGGER_WITHOUT_NEXT_BAR",
            trigger=trigger,
            opening_high=opening_high,
        )
    fill = features[next_index]
    if _local_time(fill.bar) > cutoff:
        return _terminal(
            candidate,
            mechanism,
            IntradayEntryState.ENTRY_CUTOFF_EXCEEDED,
            "QUALIFYING_TRIGGER_AFTER_ENTRY_CUTOFF",
            trigger=trigger,
            opening_high=opening_high,
        )
    raw_price = float(fill.bar.open)
    price_after_slippage = raw_price * (1.0 + policy.base_slippage_bps / 10_000.0)
    return IntradayEntryFill(
        signal_id=candidate.signal_id,
        identity_key=candidate.identity_key,
        session_date=candidate.entry_session.isoformat(),
        mechanism_id=mechanism,
        state=IntradayEntryState.ENTERED,
        reason=reason,
        trigger_timestamp=trigger.bar.timestamp,
        fill_timestamp=fill.bar.timestamp,
        raw_fill_price=raw_price,
        fill_price_after_slippage=round(price_after_slippage, 8),
        control_raw_entry_price=candidate.signed_raw_entry_price,
        raw_price_delta_vs_control=round(
            raw_price - candidate.signed_raw_entry_price,
            8,
        ),
        trigger_vwap=None if trigger.vwap is None else round(trigger.vwap, 8),
        opening_range_high=opening_high,
        cumulative_volume_at_trigger=trigger.cumulative_volume,
        fill_bar_volume=fill.bar.volume,
    )


def _unavailable(
    candidate: IntradayCandidate,
    mechanism: IntradayMechanismId,
    reason: str,
) -> IntradayEntryFill:
    return _terminal(
        candidate,
        mechanism,
        IntradayEntryState.DATA_UNAVAILABLE,
        reason,
    )


def _not_entered(
    candidate: IntradayCandidate,
    mechanism: IntradayMechanismId,
    reason: str,
) -> IntradayEntryFill:
    return _terminal(
        candidate,
        mechanism,
        IntradayEntryState.NOT_ENTERED,
        reason,
    )


def _terminal(
    candidate: IntradayCandidate,
    mechanism: IntradayMechanismId,
    state: IntradayEntryState,
    reason: str,
    *,
    trigger: _FeatureBar | None = None,
    opening_high: float | None = None,
) -> IntradayEntryFill:
    return IntradayEntryFill(
        signal_id=candidate.signal_id,
        identity_key=candidate.identity_key,
        session_date=candidate.entry_session.isoformat(),
        mechanism_id=mechanism,
        state=state,
        reason=reason,
        trigger_timestamp=None if trigger is None else trigger.bar.timestamp,
        fill_timestamp=None,
        raw_fill_price=None,
        fill_price_after_slippage=None,
        control_raw_entry_price=candidate.signed_raw_entry_price,
        raw_price_delta_vs_control=None,
        trigger_vwap=(
            None if trigger is None or trigger.vwap is None else round(trigger.vwap, 8)
        ),
        opening_range_high=opening_high,
        cumulative_volume_at_trigger=(
            None if trigger is None else trigger.cumulative_volume
        ),
        fill_bar_volume=None,
    )


def _local_time(bar: IntradayBar) -> time:
    return bar.timestamp.timetz().replace(tzinfo=None)


__all__ = [
    "CLOSING_EVALUATION_END",
    "CLOSING_EVALUATION_START",
    "IntradayEntryFill",
    "IntradayEntryState",
    "OPENING_RANGE_TIMES",
    "ORB_EVALUATION_START",
    "evaluate_intraday_entries",
]
