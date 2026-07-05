from __future__ import annotations

from alpha.execution.execution_result import ExecutionResult
from alpha.trading.trade_engine import TradeEngine
from alpha.trading.trade_ledger import TradeLedger


class TradeBridge:
    """
    Connects execution system to trade lifecycle system.

    This is the missing institutional glue layer.
    """

    def __init__(self, engine: TradeEngine, ledger: TradeLedger):
        self._engine = engine
        self._ledger = ledger

    def process_execution(
        self,
        result: ExecutionResult,
    ) -> None:

        if not result.accepted:
            return

        for fill in result.fills:
            # 1. Open trade if needed
            trade = self._engine.open_trade(
                symbol=str(fill.order_id),
                price=fill.price,
                quantity=fill.quantity,
            )

            # 2. Immediately mark as closed only if a reversal is detected.
            #    Simplified G19.1 model. G20 introduces proper exit matching.
            # In G20 this becomes proper exit matching logic

            if fill.quantity < 0:
                self._engine.close_trade(
                    trade_id=str(trade.trade_id),
                    exit_price=fill.price,
                )
