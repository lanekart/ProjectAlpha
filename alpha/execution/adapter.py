"""Execution → Portfolio adapter layer."""

from __future__ import annotations

from typing import Any

from alpha.execution.execution_result import ExecutionResult


class ExecutionAdapter:
    """
    Translates execution outcomes into portfolio events.

    Keeps the execution layer decoupled from portfolio internals.
    """

    def normalize(self, result: ExecutionResult) -> dict[str, Any]:
        return {
            "accepted": result.accepted,
            "fills": result.fills,
            "rejection_reason": result.rejection_reason,
            "total_quantity": result.total_quantity,
            "average_price": result.average_price,
        }
