from __future__ import annotations

from datetime import date

from alpha.canonical_integrity_audit.models import (
    MajorOpportunityEvent,
    OpportunityDefinition,
)
from alpha.canonical_integrity_audit.opportunity_events import (
    DEFAULT_OPPORTUNITY_DEFINITIONS,
    MajorOpportunityEventEngine,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore


class ForwardMoveEventEngine:
    """Construct retrospective labels; never candidate entry conditions."""

    def construct(
        self,
        *,
        store: LegacyMarketDataStore,
        start: date | None = None,
        end: date | None = None,
        symbol: str | None = None,
        definitions: tuple[
            OpportunityDefinition, ...
        ] = DEFAULT_OPPORTUNITY_DEFINITIONS,
    ) -> tuple[MajorOpportunityEvent, ...]:
        return MajorOpportunityEventEngine().construct(
            store=store,
            start=start,
            end=end,
            symbol=symbol,
            definitions=definitions,
        )


__all__ = ["DEFAULT_OPPORTUNITY_DEFINITIONS", "ForwardMoveEventEngine"]
