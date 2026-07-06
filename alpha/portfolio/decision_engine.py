from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from alpha.market.signals.signal_engine import Signal, SignalType
from alpha.portfolio.order_intent import OrderIntent, OrderSide


@dataclass(slots=True)
class DecisionEngine:
    """
    Converts signals into portfolio-level order intents.

    This is where:
    - risk rules
    - position sizing
    - directional decisions
    are enforced.
    """

    base_order_size: int = 100

    def generate(self, signals: Sequence[Signal], symbol: str) -> Sequence[OrderIntent]:
        intents: list[OrderIntent] = []

        for s in signals:
            intent = self._map_signal(s, symbol)

            if intent is not None:
                intents.append(intent)

        return tuple(intents)

    def _map_signal(self, signal: Signal, symbol: str) -> OrderIntent | None:
        if signal.signal == SignalType.HOLD:
            return None

        side = OrderSide.BUY if signal.signal == SignalType.BUY else OrderSide.SELL

        qty = self._size(signal.strength)

        if qty <= 0:
            return None

        return OrderIntent(
            symbol=symbol,
            side=side,
            quantity=qty,
            confidence=signal.strength,
        )

    def _size(self, strength: Decimal) -> int:
        """
        Deterministic sizing function.

        Simple linear scaling for now.
        """
        if strength <= Decimal("0"):
            return 0

        return int(self.base_order_size * min(strength, Decimal("1")))
