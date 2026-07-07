from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from alpha.backtest.accounting import BacktestTimestamp, EquityCurvePoint

_ZERO = Decimal("0")


class EquityCurveBuilder:
    """Build deterministic mark-to-market equity curve points.

    The builder is intentionally small and pure. It accepts already-computed
    cash, holdings value, and equity values so the accounting source of truth
    remains the execution ledger and backtest engine.
    """

    def build(
        self,
        *,
        starting_cash: Decimal,
        points: Sequence[tuple[BacktestTimestamp, Decimal, Decimal]],
    ) -> tuple[EquityCurvePoint, ...]:
        if starting_cash <= _ZERO:
            raise ValueError("starting_cash must be greater than zero")
        if not points:
            return ()

        curve: list[EquityCurvePoint] = []
        peak_equity = starting_cash
        previous_equity = starting_cash

        for timestamp, cash, holdings_market_value in points:
            if cash < _ZERO:
                raise ValueError("cash cannot be negative")
            if holdings_market_value < _ZERO:
                raise ValueError("holdings_market_value cannot be negative")

            equity = cash + holdings_market_value
            if equity < _ZERO:
                raise ValueError("equity cannot be negative")

            if equity > peak_equity:
                peak_equity = equity

            daily_return = self._period_return(
                previous_equity=previous_equity,
                current_equity=equity,
            )
            drawdown = self._drawdown(
                peak_equity=peak_equity,
                current_equity=equity,
            )
            cumulative_return = self._period_return(
                previous_equity=starting_cash,
                current_equity=equity,
            )

            point = EquityCurvePoint(
                timestamp=timestamp,
                cash=cash,
                holdings_market_value=holdings_market_value,
                equity=equity,
                daily_return=daily_return,
                drawdown=drawdown,
                cumulative_return=cumulative_return,
            )
            if not point.is_balanced:
                raise ValueError("equity curve point is not balanced")

            curve.append(point)
            previous_equity = equity

        return tuple(curve)

    def single_point(
        self,
        *,
        timestamp: BacktestTimestamp,
        starting_cash: Decimal,
        ending_cash: Decimal,
        holdings_market_value: Decimal,
    ) -> tuple[EquityCurvePoint, ...]:
        return self.build(
            starting_cash=starting_cash,
            points=((timestamp, ending_cash, holdings_market_value),),
        )

    def _period_return(
        self,
        *,
        previous_equity: Decimal,
        current_equity: Decimal,
    ) -> Decimal:
        if previous_equity <= _ZERO:
            raise ValueError("previous_equity must be greater than zero")
        return (current_equity - previous_equity) / previous_equity

    def _drawdown(
        self,
        *,
        peak_equity: Decimal,
        current_equity: Decimal,
    ) -> Decimal:
        if peak_equity <= _ZERO:
            raise ValueError("peak_equity must be greater than zero")
        return (current_equity - peak_equity) / peak_equity
