from __future__ import annotations

from dataclasses import dataclass, field

from alpha.portfolio.ledger_event import LedgerEvent


@dataclass
class PortfolioLedger:
    """
    Immutable portfolio accounting ledger.

    Every accounting event is appended exactly once.

    The ledger is the permanent source of truth for the portfolio.
    """

    _events: list[LedgerEvent] = field(default_factory=list)

    def append(self, event: LedgerEvent) -> None:
        """
        Append a new accounting event.
        """
        self._events.append(event)

    def events(self) -> tuple[LedgerEvent, ...]:
        """
        Return the complete immutable event history.
        """
        return tuple(self._events)

    def last_event(self) -> LedgerEvent | None:
        """
        Return the latest event if one exists.
        """
        if not self._events:
            return None

        return self._events[-1]

    def __len__(self) -> int:
        return len(self._events)
