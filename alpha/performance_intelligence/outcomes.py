from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from alpha.performance_intelligence.models import (
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
