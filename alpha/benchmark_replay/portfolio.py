from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from alpha.benchmark_replay.models import (
    BenchmarkPolicy,
    CapitalCurveRecord,
    PositionHistoryRecord,
    TradeRecord,
)

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class MarketBar:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    def __post_init__(self) -> None:
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("market bar prices must be positive")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("market bar high is invalid")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("market bar low is invalid")


@dataclass(frozen=True, slots=True)
class ExecutionCandidate:
    symbol: str
    sector: str
    decision_date: date
    opportunity_score: Decimal
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    confirmation_entry: Decimal | None
    maximum_chase_price: Decimal | None
    stop: Decimal
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    atr: Decimal | None
    maximum_holding_sessions: int

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("execution candidate symbol cannot be empty")
        if self.stop <= 0:
            raise ValueError("execution candidate stop must be positive")
        if self.maximum_holding_sessions < 1:
            raise ValueError("holding sessions must be positive")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "sector", self.sector.strip().upper() or "UNKNOWN")


@dataclass(slots=True)
class _PendingOrder:
    candidate: ExecutionCandidate
    age: int = 0


@dataclass(slots=True)
class _Position:
    trade_id: str
    candidate: ExecutionCandidate
    entry_date: date
    entry_price: Decimal
    initial_quantity: Decimal
    quantity: Decimal
    initial_stop: Decimal
    current_stop: Decimal
    highest_close: Decimal
    holding_sessions: int = 0
    target_1_hit: bool = False
    realised_profit_loss: Decimal = _ZERO
    gross_profit_loss: Decimal = _ZERO
    entry_transaction_cost: Decimal = _ZERO
    entry_slippage_cost: Decimal = _ZERO
    exit_transaction_cost: Decimal = _ZERO
    exit_slippage_cost: Decimal = _ZERO
    ambiguity_count: int = 0
    targets_hit: list[int] = field(default_factory=list)


class PortfolioReplayEngine:
    """Conservative next-session execution and mark-to-market accounting."""

    def __init__(self, policy: BenchmarkPolicy) -> None:
        self.policy = policy
        self.cash = policy.initial_capital
        self._pending: dict[str, _PendingOrder] = {}
        self._positions: dict[str, _Position] = {}
        self.trades: list[TradeRecord] = []
        self.position_history: list[PositionHistoryRecord] = []
        self.capital_curve: list[CapitalCurveRecord] = []
        self.rejected_ranking = 0
        self.rejected_capital = 0
        self.rejected_liquidity = 0
        self.entered_today = 0
        self.turnover = _ZERO

    def submit(self, candidate: ExecutionCandidate) -> str | None:
        if candidate.symbol in self._pending or candidate.symbol in self._positions:
            self.rejected_ranking += 1
            return "RANKING_DUPLICATE_EXPOSURE"
        active_and_pending = len(self._positions) + len(self._pending)
        if active_and_pending >= self.policy.maximum_positions:
            self.rejected_ranking += 1
            return "RANKING_POSITION_LIMIT"
        if self._entry_reference(candidate) is None:
            self.rejected_liquidity += 1
            return "TRADE_PLAN_ENTRY_UNAVAILABLE"
        self._pending[candidate.symbol] = _PendingOrder(candidate)
        return None

    def advance(self, observed_on: date, bars: Mapping[str, MarketBar]) -> None:
        self.entered_today = 0
        opening_cash = self.cash
        self._process_positions(observed_on, bars)
        self._process_pending(observed_on, bars, opening_cash=opening_cash)
        self._record_positions(observed_on, bars)
        self._record_capital(observed_on, bars)

    def finish(self, observed_on: date, bars: Mapping[str, MarketBar]) -> None:
        for symbol in sorted(tuple(self._positions)):
            position = self._positions[symbol]
            bar = bars.get(symbol)
            if bar is None:
                continue
            self._close(
                position,
                observed_on=observed_on,
                exit_price=bar.close,
                reason="FORCED_BOUNDARY_EXIT",
            )
        self._pending.clear()
        if self.capital_curve and self.capital_curve[-1].observed_on == observed_on:
            self.capital_curve.pop()
        self._record_capital(observed_on, bars)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def position_count(self) -> int:
        return len(self._positions)

    def _process_pending(
        self,
        observed_on: date,
        bars: Mapping[str, MarketBar],
        *,
        opening_cash: Decimal,
    ) -> None:
        available_at_open = opening_cash
        ordered = sorted(
            self._pending.values(),
            key=lambda item: (
                -item.candidate.opportunity_score,
                item.candidate.symbol,
            ),
        )
        for order in ordered:
            order.age += 1
            candidate = order.candidate
            bar = bars.get(candidate.symbol)
            if order.age > self.policy.entry_validity_sessions:
                self._pending.pop(candidate.symbol, None)
                continue
            if bar is None:
                continue
            fill = self._entry_fill(candidate, bar)
            if fill is None or fill <= candidate.stop:
                continue
            amount = self._position_amount(available_at_open)
            if amount <= 0:
                self.rejected_capital += 1
                self._pending.pop(candidate.symbol, None)
                continue
            execution_price = fill * (
                Decimal("1") + self.policy.slippage_percent / Decimal("200")
            )
            quantity = (amount / execution_price).to_integral_value(
                rounding=ROUND_FLOOR
            )
            if quantity <= 0:
                self.rejected_capital += 1
                self._pending.pop(candidate.symbol, None)
                continue
            notional = execution_price * quantity
            transaction_cost = (
                notional * self.policy.transaction_cost_percent / Decimal("200")
            )
            slippage_cost = (execution_price - fill) * quantity
            cash_required = notional + transaction_cost
            if cash_required > available_at_open or cash_required > self.cash:
                self.rejected_capital += 1
                self._pending.pop(candidate.symbol, None)
                continue
            self.cash -= cash_required
            available_at_open -= cash_required
            trade_id = _trade_id(candidate, observed_on)
            self._positions[candidate.symbol] = _Position(
                trade_id=trade_id,
                candidate=candidate,
                entry_date=observed_on,
                entry_price=execution_price,
                initial_quantity=quantity,
                quantity=quantity,
                initial_stop=candidate.stop,
                current_stop=candidate.stop,
                highest_close=bar.close,
                entry_transaction_cost=transaction_cost,
                entry_slippage_cost=slippage_cost,
            )
            self.turnover += notional
            self.entered_today += 1
            self._pending.pop(candidate.symbol, None)

    def _process_positions(
        self,
        observed_on: date,
        bars: Mapping[str, MarketBar],
    ) -> None:
        for symbol in sorted(tuple(self._positions)):
            position = self._positions.get(symbol)
            if position is None:
                continue
            bar = bars.get(symbol)
            if bar is None:
                continue
            position.holding_sessions += 1
            position.highest_close = max(position.highest_close, bar.close)
            if position.target_1_hit and position.candidate.atr is not None:
                position.current_stop = max(
                    position.current_stop,
                    position.entry_price,
                    position.highest_close - Decimal("2") * position.candidate.atr,
                )
            target = self._next_target(position)
            stop_hit = bar.low <= position.current_stop
            target_hit = target is not None and bar.high >= target[1]
            if stop_hit and target_hit:
                position.ambiguity_count += 1
            if stop_hit:
                fill = min(bar.open, position.current_stop)
                reason = (
                    "TRAILING_STOP"
                    if position.current_stop > position.initial_stop
                    else "STOP"
                )
                self._close(
                    position, observed_on=observed_on, exit_price=fill, reason=reason
                )
                continue
            if target_hit and target is not None:
                target_number, target_price = target
                if target_number == 1 and self._runner_target(position) is not None:
                    quantity = max(
                        Decimal("1"),
                        (position.quantity * Decimal("0.50")).to_integral_value(
                            rounding=ROUND_FLOOR
                        ),
                    )
                    quantity = min(quantity, position.quantity)
                    self._partial_exit(
                        position,
                        observed_on=observed_on,
                        exit_price=target_price,
                        quantity=quantity,
                    )
                    position.target_1_hit = True
                    position.targets_hit.append(1)
                    position.current_stop = max(
                        position.current_stop,
                        position.entry_price,
                    )
                    if position.quantity <= 0:
                        self._finalize_closed(
                            position,
                            observed_on=observed_on,
                            exit_price=target_price,
                            reason="TARGET_1",
                        )
                    continue
                position.targets_hit.append(target_number)
                self._close(
                    position,
                    observed_on=observed_on,
                    exit_price=target_price,
                    reason=f"TARGET_{target_number}",
                )
                continue
            if position.holding_sessions >= position.candidate.maximum_holding_sessions:
                self._close(
                    position,
                    observed_on=observed_on,
                    exit_price=bar.close,
                    reason="TIME_EXIT",
                )

    def _partial_exit(
        self,
        position: _Position,
        *,
        observed_on: date,
        exit_price: Decimal,
        quantity: Decimal,
    ) -> None:
        del observed_on
        proceeds, net_profit, exit_cost, exit_slippage = self._exit_cash(
            position, exit_price, quantity
        )
        self.cash += proceeds
        position.realised_profit_loss += net_profit
        position.gross_profit_loss += (exit_price - position.entry_price) * quantity
        position.exit_transaction_cost += exit_cost
        position.exit_slippage_cost += exit_slippage
        position.quantity -= quantity

    def _close(
        self,
        position: _Position,
        *,
        observed_on: date,
        exit_price: Decimal,
        reason: str,
    ) -> None:
        proceeds, net_profit, exit_cost, exit_slippage = self._exit_cash(
            position,
            exit_price,
            position.quantity,
        )
        self.cash += proceeds
        position.realised_profit_loss += net_profit
        position.gross_profit_loss += (
            exit_price - position.entry_price
        ) * position.quantity
        position.exit_transaction_cost += exit_cost
        position.exit_slippage_cost += exit_slippage
        self._finalize_closed(
            position,
            observed_on=observed_on,
            exit_price=exit_price,
            reason=reason,
        )

    def _finalize_closed(
        self,
        position: _Position,
        *,
        observed_on: date,
        exit_price: Decimal,
        reason: str,
        exit_cost: Decimal = _ZERO,
        exit_slippage: Decimal = _ZERO,
    ) -> None:
        gross = position.gross_profit_loss
        all_costs = (
            position.entry_transaction_cost + position.exit_transaction_cost + exit_cost
        )
        all_slippage = (
            position.entry_slippage_cost + position.exit_slippage_cost + exit_slippage
        )
        net = position.realised_profit_loss - position.entry_transaction_cost
        entry_notional = position.entry_price * position.initial_quantity
        risk = (
            position.entry_price - position.initial_stop
        ) * position.initial_quantity
        self.trades.append(
            TradeRecord(
                trade_id=position.trade_id,
                symbol=position.candidate.symbol,
                sector=position.candidate.sector,
                decision_date=position.candidate.decision_date,
                entry_date=position.entry_date,
                exit_date=observed_on,
                entry_price=_q(position.entry_price),
                exit_price=_q(exit_price),
                initial_stop=_q(position.initial_stop),
                target_1=position.candidate.target_1,
                target_2=position.candidate.target_2,
                target_3=position.candidate.target_3,
                quantity=position.initial_quantity,
                gross_profit_loss=_q(gross),
                net_profit_loss=_q(net),
                gross_return_percent=_q(gross / entry_notional * Decimal("100")),
                net_return_percent=_q(net / entry_notional * Decimal("100")),
                realised_r=(_ZERO if risk <= 0 else (net / risk).quantize(_FOUR)),
                holding_sessions=position.holding_sessions,
                holding_days=(observed_on - position.entry_date).days,
                exit_reason=reason,
                targets_hit=tuple(position.targets_hit),
                transaction_cost=_q(all_costs),
                slippage_cost=_q(all_slippage),
                ambiguity_count=position.ambiguity_count,
            )
        )
        self._positions.pop(position.candidate.symbol, None)

    def _exit_cash(
        self,
        position: _Position,
        raw_exit_price: Decimal,
        quantity: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        proceeds, net_profit, transaction_cost, slippage_cost = self._exit_cash_values(
            position,
            raw_exit_price,
            quantity,
        )
        self.turnover += proceeds + transaction_cost
        return proceeds, net_profit, transaction_cost, slippage_cost

    def _exit_cash_values(
        self,
        position: _Position,
        raw_exit_price: Decimal,
        quantity: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        execution_price = raw_exit_price * (
            Decimal("1") - self.policy.slippage_percent / Decimal("200")
        )
        notional = execution_price * quantity
        transaction_cost = (
            notional * self.policy.transaction_cost_percent / Decimal("200")
        )
        slippage_cost = (raw_exit_price - execution_price) * quantity
        proceeds = notional - transaction_cost
        net_profit = proceeds - position.entry_price * quantity
        return proceeds, net_profit, transaction_cost, slippage_cost

    def _record_positions(
        self,
        observed_on: date,
        bars: Mapping[str, MarketBar],
    ) -> None:
        for symbol, position in sorted(self._positions.items()):
            bar = bars.get(symbol)
            if bar is None:
                continue
            value = position.quantity * bar.close
            self.position_history.append(
                PositionHistoryRecord(
                    observed_on=observed_on,
                    trade_id=position.trade_id,
                    symbol=symbol,
                    status="ACTIVE",
                    quantity=position.quantity,
                    average_cost=_q(position.entry_price),
                    close_price=_q(bar.close),
                    stop_price=_q(position.current_stop),
                    market_value=_q(value),
                    unrealized_profit_loss=_q(
                        (bar.close - position.entry_price) * position.quantity
                    ),
                    highest_close=_q(position.highest_close),
                    holding_sessions=position.holding_sessions,
                )
            )

    def _record_capital(
        self,
        observed_on: date,
        bars: Mapping[str, MarketBar],
    ) -> None:
        invested = sum(
            (
                position.quantity
                * (bars[symbol].close if symbol in bars else position.entry_price)
                for symbol, position in self._positions.items()
            ),
            _ZERO,
        )
        value = self.cash + invested
        prior = (
            self.capital_curve[-1].portfolio_value
            if self.capital_curve
            else self.policy.initial_capital
        )
        peak = max(
            (item.portfolio_value for item in self.capital_curve),
            default=self.policy.initial_capital,
        )
        peak = max(peak, value)
        daily_return = _ZERO if prior <= 0 else (value / prior - 1) * Decimal("100")
        drawdown = _ZERO if peak <= 0 else (value / peak - 1) * Decimal("100")
        utilisation = _ZERO if value <= 0 else invested / value * Decimal("100")
        self.capital_curve.append(
            CapitalCurveRecord(
                observed_on=observed_on,
                cash=_q(self.cash),
                invested_capital=_q(invested),
                portfolio_value=_q(value),
                idle_cash=_q(self.cash),
                capital_utilisation_percent=_q(utilisation),
                daily_return_percent=daily_return.quantize(_FOUR),
                drawdown_percent=drawdown.quantize(_FOUR),
                open_positions=len(self._positions),
                pending_orders=len(self._pending),
            )
        )

    def _position_amount(self, available_at_open: Decimal) -> Decimal:
        reserve = self.policy.initial_capital * self.policy.cash_reserve_percent / 100
        deployable_cash = min(self.cash, available_at_open) - reserve
        single_cap = (
            self.policy.initial_capital
            * self.policy.maximum_single_name_exposure_percent
            / 100
        )
        requested = (
            self.policy.initial_capital * self.policy.position_size_percent / 100
        )
        return max(_ZERO, min(requested, single_cap, deployable_cash))

    @staticmethod
    def _entry_reference(candidate: ExecutionCandidate) -> Decimal | None:
        return (
            candidate.confirmation_entry
            or candidate.entry_zone_high
            or candidate.entry_zone_low
        )

    def _entry_fill(
        self,
        candidate: ExecutionCandidate,
        bar: MarketBar,
    ) -> Decimal | None:
        low = candidate.entry_zone_low
        high = candidate.entry_zone_high
        if low is not None and high is not None and low <= high:
            if bar.low <= high and bar.high >= low:
                fill = min(max(bar.open, low), high)
            else:
                return None
        else:
            level = self._entry_reference(candidate)
            if level is None or bar.high < level:
                return None
            fill = max(bar.open, level)
        if (
            candidate.maximum_chase_price is not None
            and fill > candidate.maximum_chase_price
        ):
            return None
        return fill

    @staticmethod
    def _next_target(position: _Position) -> tuple[int, Decimal] | None:
        if not position.target_1_hit and position.candidate.target_1 is not None:
            return 1, position.candidate.target_1
        runner = PortfolioReplayEngine._runner_target(position)
        return runner

    @staticmethod
    def _runner_target(position: _Position) -> tuple[int, Decimal] | None:
        if position.candidate.target_2 is not None:
            return 2, position.candidate.target_2
        if position.candidate.target_3 is not None:
            return 3, position.candidate.target_3
        return None


def _trade_id(candidate: ExecutionCandidate, entry_date: date) -> str:
    payload = f"{candidate.symbol}|{candidate.decision_date}|{entry_date}"
    return "cabr-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["ExecutionCandidate", "MarketBar", "PortfolioReplayEngine"]
