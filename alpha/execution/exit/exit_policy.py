from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from alpha.execution.exit.signals import ExitSignal


class ExitPolicy(ABC):
    """
    Base class for all exit policies.
    """

    @abstractmethod
    def evaluate(
        self,
        context: Mapping[str, Any],
    ) -> list[ExitSignal]:
        """
        Evaluate portfolio + market context.
        """
        raise NotImplementedError
