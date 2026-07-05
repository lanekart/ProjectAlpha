from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from alpha.execution.exit.exit_policy import ExitPolicy
from alpha.execution.exit.signals import ExitSignal


@dataclass
class ExitEngine:
    """
    Aggregates multiple exit policies.
    """

    policies: list[ExitPolicy] = field(default_factory=list)

    def evaluate(
        self,
        context: Mapping[str, Any],
    ) -> list[ExitSignal]:
        signals: list[ExitSignal] = []

        for policy in self.policies:
            signals.extend(policy.evaluate(context))

        return signals
