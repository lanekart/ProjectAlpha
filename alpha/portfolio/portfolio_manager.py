from __future__ import annotations

from dataclasses import dataclass, field

from alpha.execution.execution_result import ExecutionResult


@dataclass
class PortfolioManager:
    _positions: dict[str, int] = field(default_factory=dict)

    def apply_execution_result(self, result: ExecutionResult) -> None:
        if result is None:
            raise ValueError("ExecutionResult cannot be None")

        if not result.accepted:
            return

        for fill in result.fills:
            symbol = str(fill.order_id)
            self._positions[symbol] = self._positions.get(symbol, 0) + fill.quantity
