from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from alpha.execution.exit.exit_policy import ExitPolicy
from alpha.execution.exit.signals import ExitReason, ExitSignal


class TimeExitPolicy(ExitPolicy):
    """
    Exit positions that have exceeded the maximum holding period.
    """

    def __init__(self, max_days: int):
        self.max_days = max_days

    def evaluate(
        self,
        context: Mapping[str, Any],
    ) -> list[ExitSignal]:
        signals: list[ExitSignal] = []

        positions = context.get("positions", {})
        now = context.get("now")

        if not isinstance(now, datetime):
            return signals

        for position_id, position in positions.items():
            entry_time = position.get("entry_time")

            if not isinstance(entry_time, datetime):
                continue

            held_days = (now - entry_time).days

            if held_days >= self.max_days:
                signals.append(
                    ExitSignal(
                        position_id=UUID(position_id),
                        symbol=position["symbol"],
                        quantity=position["quantity"],
                        reason=ExitReason.TIME_EXIT,
                    )
                )

        return signals
