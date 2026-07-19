from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import ROUND_DOWN, Decimal

from alpha.forward_validation.models import (
    PositionEvent,
    PositionEventDraft,
    PositionEventType,
    RecommendationSnapshot,
)
from alpha.recommendation_intelligence.models import OHLCVBar

_TERMINAL_EVENTS = {
    PositionEventType.ENTRY_MISSED,
    PositionEventType.STOP_HIT,
    PositionEventType.TARGET_3_HIT,
    PositionEventType.TIME_EXIT,
    PositionEventType.MANUAL_EXPIRY,
    PositionEventType.INVALIDATED,
    PositionEventType.RISK_BLOCKED,
    PositionEventType.TRAILING_STOP_HIT,
}


class PositionTracker:
    """Derive append-only lifecycle events from frozen plans and later bars."""

    def evaluate(
        self,
        *,
        snapshot: RecommendationSnapshot,
        bars: tuple[OHLCVBar, ...],
        existing_events: tuple[PositionEvent, ...],
        approved_amount: Decimal | None,
    ) -> tuple[PositionEventDraft, ...]:
        relevant = tuple(
            event
            for event in existing_events
            if event.recommendation_id == snapshot.recommendation_id
        )
        if any(event.event_type in _TERMINAL_EVENTS for event in relevant):
            return ()
        if not relevant:
            rejection = self._initial_rejection(snapshot, approved_amount)
            if rejection is not None:
                return (rejection,)

        entry_event = next(
            (
                event
                for event in relevant
                if event.event_type is PositionEventType.ENTRY
            ),
            None,
        )
        ordered_bars = tuple(
            sorted(
                (
                    bar
                    for bar in bars
                    if bar.observed_on >= snapshot.generated_at.date()
                ),
                key=lambda item: item.observed_on,
            )
        )
        drafts: list[PositionEventDraft] = []
        entry_bar_index = -1
        close_only_entry = False
        if entry_event is None:
            entry = self._find_entry(snapshot, ordered_bars)
            if entry is None:
                expiry = self._pending_expiry(snapshot, ordered_bars)
                return () if expiry is None else (expiry,)
            entry_price, entry_at, entry_bar_index, close_only_entry = entry
            assert approved_amount is not None
            quantity = (approved_amount / entry_price).quantize(
                Decimal("1"), rounding=ROUND_DOWN
            )
            if quantity <= Decimal("0"):
                return (
                    PositionEventDraft(
                        recommendation_id=snapshot.recommendation_id,
                        symbol=snapshot.symbol,
                        occurred_at=entry_at,
                        event_type=PositionEventType.RISK_BLOCKED,
                        reason="approved deployment cannot purchase one whole share",
                    ),
                )
            entry_draft = PositionEventDraft(
                recommendation_id=snapshot.recommendation_id,
                symbol=snapshot.symbol,
                occurred_at=entry_at,
                event_type=PositionEventType.ENTRY,
                price=entry_price,
                quantity=quantity,
                cash_delta=-(entry_price * quantity),
                reason="frozen entry trigger satisfied",
                metadata={
                    "trigger_style": snapshot.trigger_style or "unavailable",
                    "fill_timing": "CLOSE" if close_only_entry else "INTRADAY",
                    "policy_version": snapshot.policy_version.value,
                },
            )
            drafts.append(entry_draft)
            simulated_entry_price = entry_price
            simulated_entry_at = entry_at
            simulated_quantity = quantity
        else:
            assert entry_event.price is not None and entry_event.quantity is not None
            simulated_entry_price = entry_event.price
            simulated_entry_at = entry_event.occurred_at
            simulated_quantity = entry_event.quantity
            entry_bar_index = next(
                (
                    index
                    for index, bar in enumerate(ordered_bars)
                    if bar.observed_on >= entry_event.occurred_at.date()
                ),
                -1,
            )
            close_only_entry = entry_event.metadata.get("fill_timing") == "CLOSE"

        prior_target_events = {
            event.event_type
            for event in relevant
            if event.event_type
            in {
                PositionEventType.TARGET_1_HIT,
                PositionEventType.TARGET_2_HIT,
            }
        }
        target_events = set(prior_target_events)
        highest_close = max(
            (
                bar.close_price
                for bar in ordered_bars
                if simulated_entry_at.date() <= bar.observed_on
                and any(
                    event.event_type is PositionEventType.MARK
                    and event.occurred_at.date() == bar.observed_on
                    for event in relevant
                )
            ),
            default=simulated_entry_price,
        )
        start_index = max(0, entry_bar_index + (1 if close_only_entry else 0))
        for bar in ordered_bars[start_index:]:
            if bar.observed_on < simulated_entry_at.date():
                continue
            occurred_at = _bar_time(bar)
            highest_close = max(highest_close, bar.close_price)
            stop = snapshot.stop_loss
            if stop is not None and bar.low_price <= stop:
                drafts.append(
                    _exit_draft(
                        snapshot,
                        occurred_at=occurred_at,
                        event_type=PositionEventType.STOP_HIT,
                        price=stop,
                        quantity=simulated_quantity,
                        reason=(
                            "frozen initial stop was touched; stop-first same-bar "
                            "policy"
                        ),
                    )
                )
                break
            if (
                snapshot.invalidation_level is not None
                and bar.close_price < snapshot.invalidation_level
            ):
                drafts.append(
                    _exit_draft(
                        snapshot,
                        occurred_at=occurred_at,
                        event_type=PositionEventType.INVALIDATED,
                        price=bar.close_price,
                        quantity=simulated_quantity,
                        reason="daily close breached the frozen invalidation level",
                    )
                )
                break
            trailing_level = self._trailing_level(
                snapshot=snapshot,
                highest_close=highest_close,
                target_events=target_events,
            )
            if trailing_level is not None and bar.low_price <= trailing_level:
                drafts.append(
                    _exit_draft(
                        snapshot,
                        occurred_at=occurred_at,
                        event_type=PositionEventType.TRAILING_STOP_HIT,
                        price=trailing_level,
                        quantity=simulated_quantity,
                        reason="frozen 2x ATR trailing stop was touched after target 1",
                        metadata={"trailing_level": str(trailing_level)},
                    )
                )
                break
            terminal_target = _terminal_target(snapshot)
            for number, level, event_type in _targets(snapshot):
                if (
                    level is None
                    or event_type in target_events
                    or bar.high_price < level
                ):
                    continue
                target_events.add(event_type)
                is_terminal = terminal_target == number
                drafts.append(
                    PositionEventDraft(
                        recommendation_id=snapshot.recommendation_id,
                        symbol=snapshot.symbol,
                        occurred_at=occurred_at,
                        event_type=event_type,
                        price=level,
                        quantity=simulated_quantity if is_terminal else None,
                        cash_delta=(
                            level * simulated_quantity if is_terminal else Decimal("0")
                        ),
                        reason=(
                            "highest configured frozen target reached; position closed"
                            if is_terminal
                            else (
                                f"frozen target {number} touched; position remains open"
                            )
                        ),
                        metadata={"terminal": "true"} if is_terminal else {},
                    )
                )
                if is_terminal:
                    return tuple(drafts)
            if (
                snapshot.maximum_holding_days is not None
                and (bar.observed_on - simulated_entry_at.date()).days
                >= snapshot.maximum_holding_days
            ):
                drafts.append(
                    _exit_draft(
                        snapshot,
                        occurred_at=occurred_at,
                        event_type=PositionEventType.TIME_EXIT,
                        price=bar.close_price,
                        quantity=simulated_quantity,
                        reason="frozen maximum holding period elapsed",
                    )
                )
                break
            drafts.append(
                PositionEventDraft(
                    recommendation_id=snapshot.recommendation_id,
                    symbol=snapshot.symbol,
                    occurred_at=occurred_at,
                    event_type=PositionEventType.MARK,
                    price=bar.close_price,
                    quantity=simulated_quantity,
                    reason="end-of-day mark from stored market data",
                )
            )
        return tuple(drafts)

    def _initial_rejection(
        self,
        snapshot: RecommendationSnapshot,
        approved_amount: Decimal | None,
    ) -> PositionEventDraft | None:
        if snapshot.final_verdict not in {"BUY", "STRONG_BUY"}:
            return PositionEventDraft(
                recommendation_id=snapshot.recommendation_id,
                symbol=snapshot.symbol,
                occurred_at=snapshot.generated_at,
                event_type=PositionEventType.RISK_BLOCKED,
                reason=f"frozen verdict {snapshot.final_verdict} was not deployable",
            )
        if approved_amount is None or approved_amount <= Decimal("0"):
            return PositionEventDraft(
                recommendation_id=snapshot.recommendation_id,
                symbol=snapshot.symbol,
                occurred_at=snapshot.generated_at,
                event_type=PositionEventType.RISK_BLOCKED,
                reason="frozen allocation approved no capital",
            )
        if snapshot.stop_loss is None:
            return PositionEventDraft(
                recommendation_id=snapshot.recommendation_id,
                symbol=snapshot.symbol,
                occurred_at=snapshot.generated_at,
                event_type=PositionEventType.RISK_BLOCKED,
                reason="frozen recommendation had no initial stop",
            )
        if all(
            target is None
            for target in (snapshot.target_1, snapshot.target_2, snapshot.target_3)
        ):
            return PositionEventDraft(
                recommendation_id=snapshot.recommendation_id,
                symbol=snapshot.symbol,
                occurred_at=snapshot.generated_at,
                event_type=PositionEventType.RISK_BLOCKED,
                reason="frozen recommendation had no target",
            )
        return None

    def _find_entry(
        self,
        snapshot: RecommendationSnapshot,
        bars: tuple[OHLCVBar, ...],
    ) -> tuple[Decimal, datetime, int, bool] | None:
        if snapshot.trigger_status == "TRIGGER_CONFIRMED":
            price = (
                snapshot.current_market_price
                or snapshot.confirmation_entry
                or snapshot.entry_zone_high
            )
            if price is None:
                return None
            return price, snapshot.generated_at, -1, True
        trigger = snapshot.confirmation_entry
        style = snapshot.trigger_style or ""
        for index, bar in enumerate(bars):
            if bar.observed_on <= snapshot.generated_at.date():
                continue
            if (
                style == "CLOSE_ABOVE"
                and trigger is not None
                and bar.close_price > trigger
            ):
                return bar.close_price, _bar_time(bar), index, True
            if (
                style == "CROSS_ABOVE"
                and trigger is not None
                and bar.high_price >= trigger
            ):
                return trigger, _bar_time(bar), index, False
            if style == "BREAKOUT_WITH_VOLUME":
                continue
            if style in {"ENTER_IN_ZONE", "PULLBACK_TO_LEVEL", "RETEST_HOLD"}:
                low = snapshot.entry_zone_low or snapshot.entry_zone_high
                high = snapshot.entry_zone_high or snapshot.entry_zone_low
                if (
                    low is not None
                    and high is not None
                    and bar.low_price <= high
                    and bar.high_price >= low
                ):
                    return (
                        min(max(bar.open_price, low), high),
                        _bar_time(bar),
                        index,
                        False,
                    )
        return None

    def _pending_expiry(
        self,
        snapshot: RecommendationSnapshot,
        bars: tuple[OHLCVBar, ...],
    ) -> PositionEventDraft | None:
        if snapshot.maximum_holding_days is None or not bars:
            return None
        final_bar = bars[-1]
        if (
            final_bar.observed_on - snapshot.generated_at.date()
        ).days < snapshot.maximum_holding_days:
            return None
        return PositionEventDraft(
            recommendation_id=snapshot.recommendation_id,
            symbol=snapshot.symbol,
            occurred_at=_bar_time(final_bar),
            event_type=PositionEventType.ENTRY_MISSED,
            reason="entry trigger was not satisfied within the frozen holding window",
        )

    def _trailing_level(
        self,
        *,
        snapshot: RecommendationSnapshot,
        highest_close: Decimal,
        target_events: set[PositionEventType],
    ) -> Decimal | None:
        if PositionEventType.TARGET_1_HIT not in target_events:
            return None
        strategy = (snapshot.trailing_stop_strategy or "").lower()
        if snapshot.atr_value is None or "2" not in strategy or "atr" not in strategy:
            return None
        return highest_close - (Decimal("2") * snapshot.atr_value)


def _targets(
    snapshot: RecommendationSnapshot,
) -> tuple[tuple[int, Decimal | None, PositionEventType], ...]:
    return (
        (1, snapshot.target_1, PositionEventType.TARGET_1_HIT),
        (2, snapshot.target_2, PositionEventType.TARGET_2_HIT),
        (3, snapshot.target_3, PositionEventType.TARGET_3_HIT),
    )


def _terminal_target(snapshot: RecommendationSnapshot) -> int:
    if snapshot.target_3 is not None:
        return 3
    if snapshot.target_2 is not None:
        return 2
    return 1


def _exit_draft(
    snapshot: RecommendationSnapshot,
    *,
    occurred_at: datetime,
    event_type: PositionEventType,
    price: Decimal,
    quantity: Decimal,
    reason: str,
    metadata: dict[str, str] | None = None,
) -> PositionEventDraft:
    return PositionEventDraft(
        recommendation_id=snapshot.recommendation_id,
        symbol=snapshot.symbol,
        occurred_at=occurred_at,
        event_type=event_type,
        price=price,
        quantity=quantity,
        cash_delta=price * quantity,
        reason=reason,
        metadata=metadata or {},
    )


def _bar_time(bar: OHLCVBar) -> datetime:
    return datetime.combine(bar.observed_on, time.min, tzinfo=UTC)


__all__ = ["PositionTracker"]
