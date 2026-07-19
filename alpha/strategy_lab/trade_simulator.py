from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import ROUND_HALF_UP, Decimal

from alpha.recommendation_intelligence.models import OHLCVBar
from alpha.strategy_lab.models import (
    EntryRule,
    ExecutionAssumptionProfile,
    StopRule,
    TargetRule,
    TradeExitReason,
    TradeSimulation,
    TradeSimulationRequest,
)

_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")


class TradeSimulator:
    """Conservative deterministic long-trade lifecycle simulator."""

    def simulate(
        self,
        request: TradeSimulationRequest,
        profile: ExecutionAssumptionProfile,
    ) -> TradeSimulation:
        bars = tuple(sorted(request.bars, key=lambda item: item.observed_on))
        eligible = tuple(
            item for item in bars if item.observed_on >= request.decision_time.date()
        )
        entry = _entry(request, eligible, profile)
        if entry is None:
            return _not_entered(request, profile, "entry condition was not reached")
        entry_index, entry_price = entry
        stop = _stop(request, entry_price)
        targets = _targets(request, entry_price, stop)
        if stop is None or stop <= Decimal("0") or stop >= entry_price:
            return _not_entered(
                request,
                profile,
                "valid long stop was unavailable",
                entry_price=entry_price,
            )
        if not targets:
            return _not_entered(
                request,
                profile,
                "valid target was unavailable",
                entry_price=entry_price,
                stop=stop,
            )
        start_index = entry_index + (
            1 if request.entry_rule is EntryRule.NEXT_SESSION_CLOSE else 0
        )
        active = eligible[start_index : start_index + request.holding_period_days]
        if not active:
            return _not_entered(
                request,
                profile,
                "no bars remain after entry",
                entry_price=entry_price,
                stop=stop,
            )
        return self._run(
            request=request,
            profile=profile,
            bars=active,
            entry_index=entry_index,
            entry_price=entry_price,
            stop=stop,
            targets=targets,
        )

    def _run(
        self,
        *,
        request: TradeSimulationRequest,
        profile: ExecutionAssumptionProfile,
        bars: tuple[OHLCVBar, ...],
        entry_index: int,
        entry_price: Decimal,
        stop: Decimal,
        targets: tuple[Decimal, ...],
    ) -> TradeSimulation:
        risk = entry_price - stop
        highest = entry_price
        lowest = entry_price
        current_stop = stop
        target_index = 0
        remaining = Decimal("1")
        realised_return = Decimal("0")
        partial_fraction = Decimal("0")
        ambiguities = 0
        audit: list[str] = [
            f"Entry filled using {request.entry_rule.value}.",
            f"Stop derived using {request.stop_rule.value}.",
            f"Targets derived using {request.target_rule.value}.",
        ]
        exit_bar: OHLCVBar | None = None
        exit_price: Decimal | None = None
        exit_reason = TradeExitReason.END_OF_HORIZON
        for bar in bars:
            highest = max(highest, bar.high_price)
            lowest = min(lowest, bar.low_price)
            target = targets[min(target_index, len(targets) - 1)]
            stop_hit = bar.low_price <= current_stop
            target_hit = bar.high_price >= target
            if stop_hit and target_hit:
                ambiguities += 1
                audit.append(
                    f"{bar.observed_on}: stop and target both touched; conservative "
                    "stop-first ordering applied."
                )
            if stop_hit:
                fill = bar.open_price if bar.open_price < current_stop else current_stop
                realised_return += remaining * _return_pct(entry_price, fill)
                exit_bar = bar
                exit_price = fill
                exit_reason = (
                    TradeExitReason.TRAILING_STOP
                    if current_stop > stop
                    else TradeExitReason.STOP
                )
                break
            if target_hit:
                if (
                    request.target_rule
                    in {
                        TargetRule.PARTIAL_THEN_RUNNER,
                        TargetRule.TRAILING_AFTER_TARGET_1,
                    }
                    and target_index == 0
                ):
                    fraction = min(profile.partial_fill_fraction, remaining)
                    realised_return += fraction * _return_pct(entry_price, target)
                    remaining -= fraction
                    partial_fraction += fraction
                    current_stop = max(current_stop, entry_price)
                    target_index = min(1, len(targets) - 1)
                    audit.append(
                        f"{bar.observed_on}: partial exit at target 1 and stop moved "
                        "to breakeven."
                    )
                    if remaining <= Decimal("0"):
                        exit_bar = bar
                        exit_price = target
                        exit_reason = TradeExitReason.TARGET_1
                        break
                else:
                    realised_return += remaining * _return_pct(entry_price, target)
                    remaining = Decimal("0")
                    exit_bar = bar
                    exit_price = target
                    exit_reason = _target_reason(target_index)
                    break
            if (
                request.target_rule is TargetRule.TRAILING_AFTER_TARGET_1
                and partial_fraction > Decimal("0")
                and request.atr is not None
            ):
                current_stop = max(
                    current_stop,
                    bar.close_price - Decimal("2") * request.atr,
                )
        if exit_bar is None:
            exit_bar = bars[-1]
            exit_price = exit_bar.close_price
            realised_return += remaining * _return_pct(entry_price, exit_price)
            exit_reason = (
                TradeExitReason.TIME_EXIT
                if request.target_rule is TargetRule.TIME_EXIT
                else TradeExitReason.END_OF_HORIZON
            )
        gross = _q(realised_return)
        costs = profile.round_trip_cost_pct
        net = _q(gross - costs)
        return TradeSimulation(
            recommendation_id=request.recommendation_id,
            symbol=request.symbol,
            entered=True,
            entry_time=_bar_time(
                bars[0] if entry_index >= len(bars) else request.bars[entry_index]
            ),
            entry_price=entry_price,
            entry_delay_sessions=entry_index,
            stop_price=stop,
            targets=targets,
            exit_time=_bar_time(exit_bar),
            exit_price=exit_price,
            exit_reason=exit_reason,
            gross_return_pct=gross,
            net_return_pct=net,
            mfe_pct=_q(_return_pct(entry_price, highest)),
            mae_pct=_q(_return_pct(entry_price, lowest)),
            realised_r_multiple=(
                None
                if risk <= Decimal("0")
                else (gross * entry_price / Decimal("100") / risk).quantize(_FOUR)
            ),
            holding_period_days=max(
                0, (exit_bar.observed_on - request.decision_time.date()).days
            ),
            costs_pct=costs,
            slippage_pct=profile.slippage_bps * Decimal("2") / Decimal("100"),
            partial_exit_fraction=partial_fraction,
            ambiguity_count=ambiguities,
            missed_trade_reason=None,
            audit=tuple(audit),
        )


def _entry(
    request: TradeSimulationRequest,
    bars: tuple[OHLCVBar, ...],
    profile: ExecutionAssumptionProfile,
) -> tuple[int, Decimal] | None:
    start = profile.entry_delay_sessions
    window = bars[start : start + profile.entry_validity_sessions]
    if not window:
        return None
    if request.entry_rule is EntryRule.NEXT_SESSION_OPEN:
        return start, window[0].open_price
    if request.entry_rule is EntryRule.NEXT_SESSION_CLOSE:
        return start, window[0].close_price
    level = {
        EntryRule.RECORDED_REFERENCE: request.confirmation_entry
        or request.entry_zone_high,
        EntryRule.PREFERRED_ENTRY: request.entry_zone_high,
        EntryRule.AGGRESSIVE_ENTRY: request.entry_zone_low,
        EntryRule.CONFIRMATION_ENTRY: request.confirmation_entry,
        EntryRule.BREAKOUT_ENTRY: request.confirmation_entry,
    }.get(request.entry_rule)
    if request.entry_rule is EntryRule.LIMIT_ENTRY_ZONE:
        low = request.entry_zone_low
        high = request.entry_zone_high
        if low is None or high is None or low > high:
            return None
        for offset, bar in enumerate(window, start=start):
            if bar.low_price <= high and bar.high_price >= low:
                return offset, min(max(bar.open_price, low), high)
        return None
    if level is None or level <= Decimal("0"):
        return None
    for offset, bar in enumerate(window, start=start):
        if bar.high_price >= level:
            return offset, max(bar.open_price, level)
    return None


def _stop(request: TradeSimulationRequest, entry: Decimal) -> Decimal | None:
    if request.stop_rule is StopRule.RECORDED_PLAN:
        return request.recorded_stop
    if request.stop_rule is StopRule.FIXED_PERCENT:
        return entry * (Decimal("1") - request.fixed_stop_pct / Decimal("100"))
    if request.stop_rule is StopRule.ATR_BASED:
        return None if request.atr is None else entry - Decimal("2") * request.atr
    if request.stop_rule is StopRule.SUPPORT_BASED:
        return _buffered(request.support, request.atr)
    if request.stop_rule is StopRule.SWING_LOW:
        return _buffered(request.swing_low, request.atr)
    if request.stop_rule is StopRule.VOLATILITY_ADJUSTED:
        support = request.support or request.swing_low
        return _buffered(support, request.atr, multiple=Decimal("1.5"))
    return None


def _targets(
    request: TradeSimulationRequest,
    entry: Decimal,
    stop: Decimal | None,
) -> tuple[Decimal, ...]:
    recorded = tuple(
        value
        for value in (request.target_1, request.target_2, request.target_3)
        if value is not None and value > entry
    )
    if request.target_rule is TargetRule.RECORDED_PLAN:
        return tuple(sorted(set(recorded)))
    if stop is None or stop >= entry:
        return ()
    risk = entry - stop
    fixed = entry + request.fixed_target_r * risk
    if request.target_rule is TargetRule.FIXED_REWARD_RISK:
        return (fixed,)
    if request.target_rule in {
        TargetRule.PARTIAL_THEN_RUNNER,
        TargetRule.TRAILING_AFTER_TARGET_1,
    }:
        values = recorded or (entry + Decimal("2") * risk, entry + Decimal("3") * risk)
        return tuple(sorted(set(values)))
    if request.target_rule is TargetRule.TIME_EXIT:
        return (entry + Decimal("1000") * risk,)
    return ()


def _buffered(
    level: Decimal | None,
    atr: Decimal | None,
    *,
    multiple: Decimal = Decimal("0.25"),
) -> Decimal | None:
    if level is None:
        return None
    buffer = Decimal("0") if atr is None else multiple * atr
    return level - buffer


def _not_entered(
    request: TradeSimulationRequest,
    profile: ExecutionAssumptionProfile,
    reason: str,
    *,
    entry_price: Decimal | None = None,
    stop: Decimal | None = None,
) -> TradeSimulation:
    return TradeSimulation(
        recommendation_id=request.recommendation_id,
        symbol=request.symbol,
        entered=False,
        entry_time=None,
        entry_price=entry_price,
        entry_delay_sessions=None,
        stop_price=stop,
        targets=(),
        exit_time=None,
        exit_price=None,
        exit_reason=TradeExitReason.NOT_ENTERED,
        gross_return_pct=None,
        net_return_pct=None,
        mfe_pct=None,
        mae_pct=None,
        realised_r_multiple=None,
        holding_period_days=None,
        costs_pct=profile.round_trip_cost_pct,
        slippage_pct=profile.slippage_bps * Decimal("2") / Decimal("100"),
        partial_exit_fraction=Decimal("0"),
        ambiguity_count=0,
        missed_trade_reason=reason,
        audit=(reason,),
    )


def _bar_time(bar: OHLCVBar) -> datetime:
    return datetime.combine(bar.observed_on, time.min, tzinfo=UTC)


def _return_pct(entry: Decimal, exit_price: Decimal) -> Decimal:
    return (exit_price - entry) / entry * Decimal("100")


def _target_reason(index: int) -> TradeExitReason:
    return (
        TradeExitReason.TARGET_1
        if index <= 0
        else TradeExitReason.TARGET_2
        if index == 1
        else TradeExitReason.TARGET_3
    )


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["TradeSimulator"]
