"""Canonical broker-backed event runner for DSI-011 research experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Any, cast

import pandas as pd

from alpha.backtest.broker import BrokerSimulator
from alpha.backtest.models import BacktestOrder
from alpha.research.lab_features import condition_evidence
from alpha.research.lab_models import ResearchExperimentSpec, SameSessionPolicy

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ResearchTrade:
    trade_id: str
    security_id: str
    symbol: str
    signal_date: date
    entry_date: date
    exit_date: date
    quantity: int
    entry_price: Decimal
    exit_price: Decimal
    stop_price: Decimal | None
    target_price: Decimal | None
    exit_reason: str
    gross_profit_loss: Decimal
    gross_return_percent: Decimal
    holding_sessions: int
    ambiguous_session: bool
    signal_evidence: dict[str, object]


@dataclass(frozen=True, slots=True)
class RejectedEntry:
    security_id: str
    symbol: str
    signal_date: date
    reason: str


@dataclass(frozen=True, slots=True)
class ResearchEquityPoint:
    trading_date: date
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    drawdown_percent: Decimal
    open_positions: int


@dataclass(frozen=True, slots=True)
class ResearchBacktestResult:
    trades: tuple[ResearchTrade, ...]
    rejected_entries: tuple[RejectedEntry, ...]
    equity_curve: tuple[ResearchEquityPoint, ...]
    ambiguous_sessions: int
    starting_capital: Decimal
    ending_equity: Decimal

    def summary(self) -> dict[str, object]:
        wins = tuple(item for item in self.trades if item.gross_profit_loss > 0)
        losses = tuple(item for item in self.trades if item.gross_profit_loss < 0)
        gains = sum((item.gross_profit_loss for item in wins), _ZERO)
        lost = abs(sum((item.gross_profit_loss for item in losses), _ZERO))
        returns = tuple(item.gross_return_percent for item in self.trades)
        return {
            "initial_capital": str(self.starting_capital),
            "final_equity": str(self.ending_equity),
            "gross_total_return_percent": str(
                _percent(self.ending_equity / self.starting_capital - 1)
            ),
            "trade_count": len(self.trades),
            "win_rate_percent": (
                None
                if not self.trades
                else str(_percent(Decimal(len(wins)) / Decimal(len(self.trades))))
            ),
            "average_winner_percent": _average_return(wins),
            "average_loser_percent": _average_return(losses),
            "expectancy_percent": (
                None
                if not returns
                else str(sum(returns, _ZERO) / Decimal(len(returns)))
            ),
            "profit_factor": None if lost == 0 else str(gains / lost),
            "maximum_drawdown_percent": (
                None
                if not self.equity_curve
                else str(min(item.drawdown_percent for item in self.equity_curve))
            ),
            "average_holding_period": (
                None
                if not self.trades
                else str(
                    Decimal(sum(item.holding_sessions for item in self.trades))
                    / Decimal(len(self.trades))
                )
            ),
            "ambiguous_session_count": self.ambiguous_sessions,
            "transaction_cost_model": "NONE",
            "slippage_model": "NONE",
            "results_are_gross_of_costs": True,
        }

    def trade_dicts(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in self.trades]


@dataclass(slots=True)
class _Position:
    trade_id: str
    security_id: str
    symbol: str
    signal_date: date
    entry_date: date
    quantity: int
    entry_price: Decimal
    stop_price: Decimal | None
    target_price: Decimal | None
    holding_sessions: int
    highest_price: Decimal
    signal_evidence: dict[str, object]


@dataclass(frozen=True, slots=True)
class _Pending:
    security_id: str
    symbol: str
    signal_date: date
    signal_close: Decimal
    signal_low: Decimal
    atr: Decimal | None
    evidence: dict[str, object]


class CanonicalResearchBacktestRunner:
    """Use canonical fill primitives while preserving a dated research ledger."""

    def __init__(self, broker: BrokerSimulator | None = None) -> None:
        self._broker = broker or BrokerSimulator()

    def run(
        self,
        frame: pd.DataFrame,
        spec: ResearchExperimentSpec,
    ) -> ResearchBacktestResult:
        if "research_signal" not in frame:
            raise ValueError("research frame must contain evaluated signals")
        rows = frame.copy()
        rows["trading_date"] = pd.to_datetime(rows["trading_date"]).dt.date
        rows = rows.sort_values(["trading_date", "security_id"], kind="stable")
        cash = spec.initial_capital
        positions: dict[str, _Position] = {}
        pending: dict[str, _Pending] = {}
        trades: list[ResearchTrade] = []
        rejected: list[RejectedEntry] = []
        curve: list[ResearchEquityPoint] = []
        ambiguity_count = 0
        peak = spec.initial_capital
        trade_counter = 0
        latest_close: dict[str, Decimal] = {}

        for group_date, daily in rows.groupby("trading_date", sort=True):
            trading_date = cast(date, group_date)
            daily_records = cast(
                list[dict[str, Any]],
                daily.to_dict("records"),
            )
            row_by_id = {str(item["security_id"]): item for item in daily_records}
            for security_id in sorted(tuple(positions)):
                row = row_by_id.get(security_id)
                if row is None:
                    continue
                position = positions[security_id]
                position.holding_sessions += 1
                position.highest_price = max(
                    position.highest_price,
                    _decimal(row["high"]),
                )
                stop = _active_stop(position, spec)
                target = position.target_price
                stop_hit = stop is not None and _decimal(row["low"]) <= stop
                target_hit = target is not None and _decimal(row["high"]) >= target
                ambiguous = stop_hit and target_hit
                if ambiguous:
                    ambiguity_count += 1
                reason: str | None = None
                fill: Decimal | None = None
                if stop_hit and (
                    not target_hit
                    or spec.same_session_policy is SameSessionPolicy.ASSUME_STOP_FIRST
                ):
                    reason = (
                        "INTRADAY_PATH_AMBIGUOUS_STOP_FIRST" if ambiguous else "STOP"
                    )
                    fill = min(
                        stop or _decimal(row["open"]),
                        _decimal(row["open"]),
                    )
                elif target_hit:
                    reason = (
                        "INTRADAY_PATH_AMBIGUOUS_TARGET_FIRST"
                        if ambiguous
                        else "TARGET"
                    )
                    fill = max(
                        target or _decimal(row["open"]),
                        _decimal(row["open"]),
                    )
                elif (
                    spec.maximum_holding_sessions is not None
                    and position.holding_sessions >= spec.maximum_holding_sessions
                ):
                    reason = "TIME_EXIT"
                    fill = _decimal(row["close"])
                if fill is not None and reason is not None:
                    if (
                        "TARGET" in reason
                        and spec.target_policy.rules
                        and spec.target_policy.rules[0].exit_percent < 100
                        and position.quantity > 1
                    ):
                        partial_quantity = max(
                            1,
                            int(
                                Decimal(position.quantity)
                                * spec.target_policy.rules[0].exit_percent
                                / 100
                            ),
                        )
                        partial_quantity = min(
                            partial_quantity,
                            position.quantity - 1,
                        )
                        cash += _sell(
                            self._broker,
                            position.symbol,
                            partial_quantity,
                            fill,
                        )
                        partial_position = replace(
                            position,
                            trade_id=f"{position.trade_id}-P1",
                            quantity=partial_quantity,
                        )
                        trades.append(
                            _closed_trade(
                                partial_position,
                                exit_date=trading_date,
                                exit_price=fill,
                                exit_reason="TARGET_PARTIAL",
                                ambiguous=ambiguous,
                            )
                        )
                        position.quantity -= partial_quantity
                        position.target_price = None
                        continue
                    cash += _sell(
                        self._broker,
                        position.symbol,
                        position.quantity,
                        fill,
                    )
                    trades.append(
                        _closed_trade(
                            position,
                            exit_date=trading_date,
                            exit_price=fill,
                            exit_reason=reason,
                            ambiguous=ambiguous,
                        )
                    )
                    del positions[security_id]

            for security_id in sorted(tuple(pending)):
                row = row_by_id.get(security_id)
                if row is None:
                    continue
                item = pending.pop(security_id)
                if len(positions) >= spec.maximum_concurrent_positions:
                    rejected.append(
                        RejectedEntry(
                            security_id,
                            item.symbol,
                            item.signal_date,
                            "MAXIMUM_POSITIONS_REACHED",
                        )
                    )
                    continue
                entry_price = _entry_price(row, item, spec)
                if entry_price is None:
                    rejected.append(
                        RejectedEntry(
                            security_id,
                            item.symbol,
                            item.signal_date,
                            "ENTRY_TRIGGER_NOT_REACHED",
                        )
                    )
                    continue
                allocation = cash / Decimal(
                    max(1, spec.maximum_concurrent_positions - len(positions))
                )
                quantity = int(
                    (allocation / entry_price).to_integral_value(rounding=ROUND_DOWN)
                )
                if quantity < 1:
                    rejected.append(
                        RejectedEntry(
                            security_id,
                            item.symbol,
                            item.signal_date,
                            "INSUFFICIENT_CAPITAL_FOR_WHOLE_SHARE",
                        )
                    )
                    continue
                cost = _buy(self._broker, item.symbol, quantity, entry_price)
                if cost > cash:
                    quantity -= 1
                    if quantity < 1:
                        continue
                    cost = _buy(self._broker, item.symbol, quantity, entry_price)
                cash -= cost
                trade_counter += 1
                stop_price = _initial_stop(item, entry_price, spec)
                positions[security_id] = _Position(
                    trade_id=f"{spec.experiment_id}-T{trade_counter:06d}",
                    security_id=security_id,
                    symbol=item.symbol,
                    signal_date=item.signal_date,
                    entry_date=trading_date,
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=_initial_target(
                        entry_price, stop_price, item.atr, spec
                    ),
                    holding_sessions=0,
                    highest_price=entry_price,
                    signal_evidence=item.evidence,
                )

            for row in daily_records:
                security_id = str(row["security_id"])
                latest_close[security_id] = _decimal(row["close"])
                if bool(row["research_signal"]) and security_id not in positions:
                    pending[security_id] = _Pending(
                        security_id=security_id,
                        symbol=str(row["symbol"]),
                        signal_date=trading_date,
                        signal_close=_decimal(row["close"]),
                        signal_low=_decimal(row["low"]),
                        atr=_optional_decimal(row.get("atr")),
                        evidence=condition_evidence(
                            pd.Series(row),
                            spec.entry_conditions,
                        ),
                    )
            market_value = sum(
                (
                    latest_close.get(key, item.entry_price) * Decimal(item.quantity)
                    for key, item in positions.items()
                ),
                _ZERO,
            )
            equity = cash + market_value
            peak = max(peak, equity)
            curve.append(
                ResearchEquityPoint(
                    trading_date=trading_date,
                    cash=cash,
                    market_value=market_value,
                    equity=equity,
                    drawdown_percent=_percent(equity / peak - 1),
                    open_positions=len(positions),
                )
            )

        if curve:
            final_date = curve[-1].trading_date
            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                fill = latest_close.get(security_id, position.entry_price)
                cash += _sell(
                    self._broker,
                    position.symbol,
                    position.quantity,
                    fill,
                )
                trades.append(
                    _closed_trade(
                        position,
                        exit_date=final_date,
                        exit_price=fill,
                        exit_reason="FORCED_BOUNDARY_EXIT",
                        ambiguous=False,
                    )
                )
            curve[-1] = ResearchEquityPoint(
                trading_date=final_date,
                cash=cash,
                market_value=_ZERO,
                equity=cash,
                drawdown_percent=_percent(cash / max(peak, cash) - 1),
                open_positions=0,
            )
        return ResearchBacktestResult(
            trades=tuple(trades),
            rejected_entries=tuple(rejected),
            equity_curve=tuple(curve),
            ambiguous_sessions=ambiguity_count,
            starting_capital=spec.initial_capital,
            ending_equity=cash,
        )


def _entry_price(
    row: dict[str, Any],
    pending: _Pending,
    spec: ResearchExperimentSpec,
) -> Decimal | None:
    if spec.entry_rule.rule_id == "NEXT_VALID_SESSION_CLOSE":
        return _decimal(row["close"])
    if spec.entry_rule.rule_id == "BREAKOUT_ABOVE_SIGNAL_HIGH":
        signal_high = Decimal(str(pending.evidence.get("signal_high") or "0"))
        return signal_high if _decimal(row["high"]) >= signal_high > 0 else None
    if spec.entry_rule.rule_id == "PERCENT_RETRACEMENT_LIMIT":
        percent = spec.entry_rule.retracement_percent or _ZERO
        limit = pending.signal_close * (Decimal("1") - percent / 100)
        if _decimal(row["low"]) > limit:
            return None
        return min(_decimal(row["open"]), limit)
    return _decimal(row["open"])


def _initial_stop(
    pending: _Pending,
    entry: Decimal,
    spec: ResearchExperimentSpec,
) -> Decimal | None:
    levels: list[Decimal] = []
    for rule in spec.stop_policy.rules:
        if rule.rule_id == "FIXED_PERCENT" and rule.value is not None:
            levels.append(entry * (Decimal("1") - rule.value / 100))
        elif rule.rule_id == "ATR" and rule.value is not None and pending.atr:
            levels.append(entry - rule.value * pending.atr)
        elif rule.rule_id == "SIGNAL_CANDLE_LOW":
            levels.append(pending.signal_low)
        elif rule.rule_id in {"SWING_LOW", "STOP-STRUCTURAL-10D"}:
            swing = pending.evidence.get("swing_low")
            if swing is not None:
                levels.append(Decimal(str(swing)))
    if not levels:
        return None
    if spec.stop_policy.combination == "WIDER":
        return min(levels)
    return max(levels)


def _active_stop(
    position: _Position,
    spec: ResearchExperimentSpec,
) -> Decimal | None:
    levels = [position.stop_price] if position.stop_price is not None else []
    trailing = tuple(
        item
        for item in spec.stop_policy.rules
        if item.rule_id == "TRAILING_PERCENT" and item.value is not None
    )
    for rule in trailing:
        gain = (position.highest_price / position.entry_price - 1) * 100
        if rule.activation_gain_percent is None or gain >= rule.activation_gain_percent:
            levels.append(
                position.highest_price * (Decimal("1") - (rule.value or _ZERO) / 100)
            )
    if spec.target_policy.trailing_rule is not None:
        rule = spec.target_policy.trailing_rule
        if rule.value is not None:
            levels.append(position.highest_price * (Decimal("1") - rule.value / 100))
    return max(levels) if levels else None


def _initial_target(
    entry: Decimal,
    stop: Decimal | None,
    atr: Decimal | None,
    spec: ResearchExperimentSpec,
) -> Decimal | None:
    if not spec.target_policy.rules:
        return None
    rule = spec.target_policy.rules[0]
    if rule.rule_id == "FIXED_PERCENT" and rule.value is not None:
        return entry * (Decimal("1") + rule.value / 100)
    if rule.rule_id == "R_MULTIPLE" and rule.value is not None and stop is not None:
        return entry + (entry - stop) * rule.value
    if rule.rule_id == "ATR_MULTIPLE" and rule.value is not None and atr is not None:
        return entry + atr * rule.value
    return None


def _buy(
    broker: BrokerSimulator,
    symbol: str,
    quantity: int,
    price: Decimal,
) -> Decimal:
    trade = broker.execute(
        order=BacktestOrder(symbol=symbol, quantity=quantity),
        prices={symbol: price},
    )
    if trade is None:
        raise RuntimeError("canonical broker rejected non-zero buy")
    return trade.notional


def _sell(
    broker: BrokerSimulator,
    symbol: str,
    quantity: int,
    price: Decimal,
) -> Decimal:
    trade = broker.execute(
        order=BacktestOrder(symbol=symbol, quantity=-quantity),
        prices={symbol: price},
    )
    if trade is None:
        raise RuntimeError("canonical broker rejected non-zero sell")
    return trade.notional


def _closed_trade(
    position: _Position,
    *,
    exit_date: date,
    exit_price: Decimal,
    exit_reason: str,
    ambiguous: bool,
) -> ResearchTrade:
    pnl = (exit_price - position.entry_price) * Decimal(position.quantity)
    return ResearchTrade(
        trade_id=position.trade_id,
        security_id=position.security_id,
        symbol=position.symbol,
        signal_date=position.signal_date,
        entry_date=position.entry_date,
        exit_date=exit_date,
        quantity=position.quantity,
        entry_price=position.entry_price,
        exit_price=exit_price,
        stop_price=position.stop_price,
        target_price=position.target_price,
        exit_reason=exit_reason,
        gross_profit_loss=pnl,
        gross_return_percent=_percent(exit_price / position.entry_price - Decimal("1")),
        holding_sessions=position.holding_sessions,
        ambiguous_session=ambiguous,
        signal_evidence=position.signal_evidence,
    )


def _average_return(trades: tuple[ResearchTrade, ...]) -> str | None:
    if not trades:
        return None
    return str(
        sum((item.gross_return_percent for item in trades), _ZERO)
        / Decimal(len(trades))
    )


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or bool(pd.isna(cast(Any, value))):
        return None
    return _decimal(value)


def _percent(value: Decimal) -> Decimal:
    return (value * 100).quantize(Decimal("0.0001"))


__all__ = [
    "CanonicalResearchBacktestRunner",
    "RejectedEntry",
    "ResearchBacktestResult",
    "ResearchEquityPoint",
    "ResearchTrade",
]
