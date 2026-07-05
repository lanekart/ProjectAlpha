from __future__ import annotations

from decimal import Decimal

from alpha.execution.execution_result import ExecutionResult
from alpha.execution.fill import Fill
from alpha.research.performance_tracker import PerformanceTracker


class PerformanceBridge:
    """
    Converts execution outcomes into strategy learning signals.

    This is the feedback loop of Alpha.
    """

    def __init__(self, tracker: PerformanceTracker) -> None:
        self._tracker = tracker

    def process(
        self,
        strategy_id: str,
        result: ExecutionResult,
        cost_per_trade: Decimal = Decimal("0"),
    ) -> None:
        if not result.accepted:
            return

        for fill in result.fills:
            pnl = self._estimate_pnl(fill)

            self._tracker.update_trade(
                strategy_id=strategy_id,
                pnl=pnl,
                cost=cost_per_trade,
                is_win=pnl > Decimal("0"),
            )

    def _estimate_pnl(self, fill: Fill) -> Decimal:
        """
        Simplified mark-to-market placeholder.

        In G19 we will replace this with:
        - real exit-based PnL
        - portfolio-level attribution
        """

        return Decimal("0")
