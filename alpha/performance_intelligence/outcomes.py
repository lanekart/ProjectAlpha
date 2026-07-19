from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from alpha.performance_intelligence.models import (
    NextDayOutcomeLabel,
    RecommendationExitReason,
    RecommendationLedgerEntry,
    RecommendationOutcome,
    RecommendationOutcomeStatus,
)
from alpha.recommendation_intelligence.models import OHLCVBar

_ZERO = Decimal("0")
_ONE_HUNDRED = Decimal("100")
_TWO_PLACES = Decimal("0.01")


class RecommendationOutcomeEvaluator:
    """Evaluate post-recommendation OHLCV bars against the recorded trade plan."""

    def __init__(self, *, default_expiry_bars: int = 20) -> None:
        if default_expiry_bars <= 0:
            raise ValueError("default_expiry_bars must be positive")
        self.default_expiry_bars = default_expiry_bars

    def evaluate(
        self,
        entry: RecommendationLedgerEntry,
        bars: tuple[OHLCVBar, ...],
    ) -> RecommendationOutcome:
        ordered_bars = tuple(
            sorted(
                (bar for bar in bars if bar.observed_on > entry.generated_at.date()),
                key=lambda bar: bar.observed_on,
            )
        )
        return _with_next_day_snapshot(
            entry=entry,
            outcome=self._evaluate_ordered(entry, ordered_bars),
            ordered_bars=ordered_bars,
        )

    def _evaluate_ordered(
        self,
        entry: RecommendationLedgerEntry,
        ordered_bars: tuple[OHLCVBar, ...],
    ) -> RecommendationOutcome:
        if not ordered_bars:
            return RecommendationOutcome(
                recommendation_id=entry.recommendation_id,
                symbol=entry.symbol,
                status=RecommendationOutcomeStatus.PENDING,
                explanation=("No future bars available for outcome evaluation.",),
            )

        trigger_price = _entry_trigger_price(entry)
        if trigger_price is None:
            return RecommendationOutcome(
                recommendation_id=entry.recommendation_id,
                symbol=entry.symbol,
                status=RecommendationOutcomeStatus.NOT_TRIGGERED,
                exit_reason=RecommendationExitReason.NOT_TRIGGERED,
                explanation=("No entry trigger price was recorded.",),
            )

        active = False
        entry_price: Decimal | None = None
        entry_date = None
        entry_index = 0
        stop_loss = entry.stop_loss
        target_1 = entry.target_1
        target_2 = entry.target_2
        target_3 = entry.target_3
        high_watermark: Decimal | None = None
        trailing_stop: Decimal | None = None
        target_1_hit = False
        target_2_hit = False
        target_3_hit = False
        maximum_favorable_excursion = _ZERO
        maximum_adverse_excursion = _ZERO
        explanation: list[str] = []

        for index, bar in enumerate(ordered_bars):
            if not active:
                if bar.high_price >= trigger_price:
                    active = True
                    entry_price = trigger_price
                    entry_date = bar.observed_on
                    entry_index = index
                    high_watermark = bar.close_price
                    explanation.append(
                        "Entry triggered on "
                        f"{bar.observed_on.isoformat()} at {entry_price}."
                    )
                elif index + 1 >= self.default_expiry_bars:
                    return RecommendationOutcome(
                        recommendation_id=entry.recommendation_id,
                        symbol=entry.symbol,
                        status=RecommendationOutcomeStatus.NOT_TRIGGERED,
                        exit_reason=RecommendationExitReason.NOT_TRIGGERED,
                        holding_period_bars=index + 1,
                        holding_period_days=(
                            bar.observed_on - ordered_bars[0].observed_on
                        ).days,
                        explanation=(
                            "Entry was not triggered within "
                            f"{self.default_expiry_bars} bars.",
                        ),
                    )
                continue

            if entry_price is None or entry_date is None:
                raise RuntimeError("active outcome missing entry state")

            holding_bars = index - entry_index + 1
            holding_days = (bar.observed_on - entry_date).days
            high_watermark = (
                bar.close_price
                if high_watermark is None
                else max(high_watermark, bar.close_price)
            )
            maximum_favorable_excursion = max(
                maximum_favorable_excursion,
                bar.high_price - entry_price,
            )
            maximum_adverse_excursion = min(
                maximum_adverse_excursion,
                bar.low_price - entry_price,
            )
            trailing_stop = _trailing_stop(
                high_watermark=high_watermark,
                fallback_stop=trailing_stop,
                snapshot=entry.trailing_stop_strategy,
            )

            stop_hit = stop_loss is not None and bar.low_price <= stop_loss
            target_3_hit = target_3_hit or (
                target_3 is not None and bar.high_price >= target_3
            )
            target_2_hit = target_2_hit or (
                target_2 is not None and bar.high_price >= target_2
            )
            target_1_hit = target_1_hit or (
                target_1 is not None and bar.high_price >= target_1
            )
            trailing_hit = trailing_stop is not None and bar.low_price <= trailing_stop

            target_exit = _highest_target_hit(
                target_1=target_1,
                target_2=target_2,
                target_3=target_3,
                bar=bar,
            )
            if stop_hit and target_exit is not None:
                explanation.append(
                    "Stop and target appeared in the same bar; conservative "
                    "ordering classified the stop first."
                )
                return _exited_outcome(
                    entry=entry,
                    entry_price=entry_price,
                    entry_date=entry_date,
                    exit_price=stop_loss,
                    exit_date=bar.observed_on,
                    exit_reason=RecommendationExitReason.STOP_LOSS,
                    stop_hit=True,
                    target_1_hit=target_1_hit,
                    target_2_hit=target_2_hit,
                    target_3_hit=target_3_hit,
                    trailing_stop_hit=False,
                    mfe=maximum_favorable_excursion,
                    mae=maximum_adverse_excursion,
                    holding_bars=holding_bars,
                    holding_days=holding_days,
                    explanation=tuple(explanation),
                )
            if stop_hit:
                explanation.append(
                    f"Stop loss hit on {bar.observed_on.isoformat()} at {stop_loss}."
                )
                return _exited_outcome(
                    entry=entry,
                    entry_price=entry_price,
                    entry_date=entry_date,
                    exit_price=stop_loss,
                    exit_date=bar.observed_on,
                    exit_reason=RecommendationExitReason.STOP_LOSS,
                    stop_hit=True,
                    target_1_hit=target_1_hit,
                    target_2_hit=target_2_hit,
                    target_3_hit=target_3_hit,
                    trailing_stop_hit=False,
                    mfe=maximum_favorable_excursion,
                    mae=maximum_adverse_excursion,
                    holding_bars=holding_bars,
                    holding_days=holding_days,
                    explanation=tuple(explanation),
                )
            if trailing_hit:
                explanation.append(
                    "Trailing stop hit on "
                    f"{bar.observed_on.isoformat()} at {trailing_stop}."
                )
                return _exited_outcome(
                    entry=entry,
                    entry_price=entry_price,
                    entry_date=entry_date,
                    exit_price=trailing_stop,
                    exit_date=bar.observed_on,
                    exit_reason=RecommendationExitReason.TRAILING_STOP,
                    stop_hit=False,
                    target_1_hit=target_1_hit,
                    target_2_hit=target_2_hit,
                    target_3_hit=target_3_hit,
                    trailing_stop_hit=True,
                    mfe=maximum_favorable_excursion,
                    mae=maximum_adverse_excursion,
                    holding_bars=holding_bars,
                    holding_days=holding_days,
                    explanation=tuple(explanation),
                )
            if target_exit is not None:
                target_reason, target_price = target_exit
                explanation.append(
                    f"{target_reason.value} hit on "
                    f"{bar.observed_on.isoformat()} at {target_price}."
                )
                return _exited_outcome(
                    entry=entry,
                    entry_price=entry_price,
                    entry_date=entry_date,
                    exit_price=target_price,
                    exit_date=bar.observed_on,
                    exit_reason=target_reason,
                    stop_hit=False,
                    target_1_hit=target_1_hit,
                    target_2_hit=target_2_hit,
                    target_3_hit=target_3_hit,
                    trailing_stop_hit=False,
                    mfe=maximum_favorable_excursion,
                    mae=maximum_adverse_excursion,
                    holding_bars=holding_bars,
                    holding_days=holding_days,
                    explanation=tuple(explanation),
                )
            if holding_bars >= self.default_expiry_bars:
                explanation.append(
                    f"Trade expired after {self.default_expiry_bars} bars without exit."
                )
                return RecommendationOutcome(
                    recommendation_id=entry.recommendation_id,
                    symbol=entry.symbol,
                    status=RecommendationOutcomeStatus.EXPIRED,
                    entry_triggered=True,
                    entry_date=entry_date,
                    entry_price=entry_price,
                    target_1_hit=target_1_hit,
                    target_2_hit=target_2_hit,
                    target_3_hit=target_3_hit,
                    exit_date=bar.observed_on,
                    exit_price=bar.close_price,
                    exit_reason=RecommendationExitReason.EXPIRED,
                    maximum_favorable_excursion=maximum_favorable_excursion,
                    maximum_adverse_excursion=maximum_adverse_excursion,
                    realized_r_multiple=_r_multiple(
                        entry_price,
                        stop_loss,
                        bar.close_price,
                    ),
                    realized_percent_return=_percent_return(
                        entry_price,
                        bar.close_price,
                    ),
                    holding_period_bars=holding_bars,
                    holding_period_days=holding_days,
                    explanation=tuple(explanation),
                )

        if active and entry_price is not None and entry_date is not None:
            last_bar = ordered_bars[-1]
            holding_bars = len(ordered_bars) - entry_index
            return RecommendationOutcome(
                recommendation_id=entry.recommendation_id,
                symbol=entry.symbol,
                status=RecommendationOutcomeStatus.ACTIVE,
                entry_triggered=True,
                entry_date=entry_date,
                entry_price=entry_price,
                target_1_hit=target_1_hit,
                target_2_hit=target_2_hit,
                target_3_hit=target_3_hit,
                maximum_favorable_excursion=maximum_favorable_excursion,
                maximum_adverse_excursion=maximum_adverse_excursion,
                holding_period_bars=holding_bars,
                holding_period_days=(last_bar.observed_on - entry_date).days,
                explanation=tuple(explanation)
                + ("Trade remains active with no stop or target exit.",),
            )

        return RecommendationOutcome(
            recommendation_id=entry.recommendation_id,
            symbol=entry.symbol,
            status=RecommendationOutcomeStatus.PENDING,
            holding_period_bars=len(ordered_bars),
            holding_period_days=(
                ordered_bars[-1].observed_on - ordered_bars[0].observed_on
            ).days,
            explanation=("Entry has not triggered yet.",),
        )


def _entry_trigger_price(entry: RecommendationLedgerEntry) -> Decimal | None:
    if entry.confirmation_entry is not None:
        return entry.confirmation_entry
    if entry.entry_zone_high is not None:
        return entry.entry_zone_high
    return entry.entry_zone_low


def _with_next_day_snapshot(
    *,
    entry: RecommendationLedgerEntry,
    outcome: RecommendationOutcome,
    ordered_bars: tuple[OHLCVBar, ...],
) -> RecommendationOutcome:
    realized_pnl = _pnl_from_return(
        entry=entry,
        percent_return=outcome.realized_percent_return,
    )
    if not ordered_bars:
        return replace(outcome, realized_pnl_rs=realized_pnl)

    next_day = ordered_bars[0]
    trigger_price = _entry_trigger_price(entry)
    return_from_entry = (
        None
        if trigger_price is None
        else _percent_return(trigger_price, next_day.close_price)
    )
    return_from_confirmation = (
        None
        if entry.confirmation_entry is None
        else _percent_return(entry.confirmation_entry, next_day.close_price)
    )
    target_touched = (
        entry.target_1 is not None and next_day.high_price >= entry.target_1
    )
    stop_touched = entry.stop_loss is not None and next_day.low_price <= entry.stop_loss
    close_above_entry = (
        None if trigger_price is None else next_day.close_price >= trigger_price
    )
    label = _next_day_label(
        trigger_price=trigger_price,
        bar=next_day,
        target_touched=target_touched,
        stop_touched=stop_touched,
    )
    return replace(
        outcome,
        realized_pnl_rs=realized_pnl,
        next_day_open=next_day.open_price,
        next_day_high=next_day.high_price,
        next_day_low=next_day.low_price,
        next_day_close=next_day.close_price,
        next_day_return_from_entry=return_from_entry,
        next_day_return_from_confirmation_entry=return_from_confirmation,
        next_day_target_1_touched=target_touched,
        next_day_stop_touched=stop_touched,
        next_day_close_above_entry=close_above_entry,
        next_day_outcome_label=label,
        next_day_pnl_rs=_pnl_from_return(entry=entry, percent_return=return_from_entry),
        next_day_pnl_pct=return_from_entry,
    )


def _next_day_label(
    *,
    trigger_price: Decimal | None,
    bar: OHLCVBar,
    target_touched: bool,
    stop_touched: bool,
) -> NextDayOutcomeLabel:
    if trigger_price is None or bar.high_price < trigger_price:
        return NextDayOutcomeLabel.OPEN
    if stop_touched:
        return NextDayOutcomeLabel.LOSS
    if target_touched:
        return NextDayOutcomeLabel.WIN
    if bar.close_price > trigger_price:
        return NextDayOutcomeLabel.WIN
    if bar.close_price < trigger_price:
        return NextDayOutcomeLabel.LOSS
    return NextDayOutcomeLabel.NEUTRAL


def _pnl_from_return(
    *,
    entry: RecommendationLedgerEntry,
    percent_return: Decimal | None,
) -> Decimal | None:
    position_size = entry.recommended_position_size_rs or entry.approved_deployment_rs
    if position_size is None or percent_return is None:
        return None
    return (position_size * percent_return / _ONE_HUNDRED).quantize(
        _TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )


def _trailing_stop(
    *,
    high_watermark: Decimal,
    fallback_stop: Decimal | None,
    snapshot: str | None,
) -> Decimal | None:
    if snapshot is None or "ATR" not in snapshot.upper():
        return fallback_stop
    atr = _atr_value(snapshot)
    if atr is None:
        return fallback_stop
    return high_watermark - (atr * Decimal("2"))


def _atr_value(text: str) -> Decimal | None:
    normalized = text.upper().replace("=", " ").replace(":", " ")
    tokens = normalized.split()
    for index, token in enumerate(tokens[:-1]):
        if token == "ATR":
            try:
                return Decimal(tokens[index + 1])
            except Exception:
                return None
    return None


def _highest_target_hit(
    *,
    target_1: Decimal | None,
    target_2: Decimal | None,
    target_3: Decimal | None,
    bar: OHLCVBar,
) -> tuple[RecommendationExitReason, Decimal] | None:
    if target_3 is not None and bar.high_price >= target_3:
        return RecommendationExitReason.TARGET_3, target_3
    if target_2 is not None and bar.high_price >= target_2:
        return RecommendationExitReason.TARGET_2, target_2
    if target_1 is not None and bar.high_price >= target_1:
        return RecommendationExitReason.TARGET_1, target_1
    return None


def _exited_outcome(
    *,
    entry: RecommendationLedgerEntry,
    entry_price: Decimal,
    entry_date: date,
    exit_price: Decimal | None,
    exit_date: date,
    exit_reason: RecommendationExitReason,
    stop_hit: bool,
    target_1_hit: bool,
    target_2_hit: bool,
    target_3_hit: bool,
    trailing_stop_hit: bool,
    mfe: Decimal,
    mae: Decimal,
    holding_bars: int,
    holding_days: int,
    explanation: tuple[str, ...],
) -> RecommendationOutcome:
    return RecommendationOutcome(
        recommendation_id=entry.recommendation_id,
        symbol=entry.symbol,
        status=RecommendationOutcomeStatus.EXITED,
        entry_triggered=True,
        entry_date=entry_date,
        entry_price=entry_price,
        stop_hit=stop_hit,
        target_1_hit=target_1_hit,
        target_2_hit=target_2_hit,
        target_3_hit=target_3_hit,
        trailing_stop_hit=trailing_stop_hit,
        exit_date=exit_date,
        exit_price=exit_price,
        exit_reason=exit_reason,
        maximum_favorable_excursion=mfe,
        maximum_adverse_excursion=mae,
        realized_r_multiple=_r_multiple(entry_price, entry.stop_loss, exit_price),
        realized_percent_return=_percent_return(entry_price, exit_price),
        holding_period_bars=holding_bars,
        holding_period_days=holding_days,
        explanation=explanation,
    )


def _r_multiple(
    entry_price: Decimal,
    stop_loss: Decimal | None,
    exit_price: Decimal | None,
) -> Decimal | None:
    if stop_loss is None or exit_price is None:
        return None
    risk = entry_price - stop_loss
    if risk <= _ZERO:
        return None
    return ((exit_price - entry_price) / risk).quantize(
        _TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )


def _percent_return(entry_price: Decimal, exit_price: Decimal | None) -> Decimal | None:
    if exit_price is None or entry_price <= _ZERO:
        return None
    return (((exit_price - entry_price) / entry_price) * _ONE_HUNDRED).quantize(
        _TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )


__all__ = ["RecommendationOutcomeEvaluator"]
