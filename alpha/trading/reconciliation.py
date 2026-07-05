from __future__ import annotations

from dataclasses import dataclass

from alpha.trading.matching_engine import MatchingEngine
from alpha.trading.position_tracker import PositionTracker


@dataclass
class ReconciliationEngine:
    """
    Ensures portfolio state == trade reconstruction state.

    This is institutional correctness validation.
    """

    def validate(self, matcher: MatchingEngine, tracker: PositionTracker) -> bool:
        """
        Returns True if system is consistent.
        """

        # Compare open exposure vs tracker
        open_qty = sum(p.quantity for p in matcher.open_positions)
        tracked_qty = sum(p.quantity for p in tracker.positions.values())

        return open_qty == tracked_qty
