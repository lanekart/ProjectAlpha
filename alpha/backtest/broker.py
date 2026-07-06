from __future__ import annotations

from decimal import Decimal

from alpha.backtest.models import BacktestOrder, BacktestTrade


class BrokerSimulator:
    def execute(
        self,
        *,
        order: BacktestOrder,
        prices: dict[str, Decimal],
    ) -> BacktestTrade | None:
        if order.quantity == 0:
            return None

        price = self._get_price(order.symbol, prices)
        notional = price * Decimal(abs(order.quantity))

        return BacktestTrade(
            symbol=order.symbol,
            quantity=order.quantity,
            price=price,
            notional=notional,
        )

    def _get_price(self, symbol: str, prices: dict[str, Decimal]) -> Decimal:
        try:
            price = prices[symbol]
        except KeyError as error:
            raise ValueError(f"missing price for symbol: {symbol}") from error

        if price <= Decimal("0"):
            raise ValueError("price must be greater than zero")

        return price
