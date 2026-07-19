"""Effective-dated immutable security identity registry."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from alpha.point_in_time_universe.models import SecurityIdentity


class SecurityMaster:
    def __init__(self, records: tuple[SecurityIdentity, ...]) -> None:
        self.records = tuple(sorted(records, key=lambda item: item.security_id))
        self._by_id = {item.security_id: item for item in self.records}
        if len(self._by_id) != len(self.records):
            raise ValueError("security ids must be unique")
        self._validate_symbol_intervals()

    def get(self, security_id: str) -> SecurityIdentity | None:
        return self._by_id.get(security_id)

    def resolve_symbol(
        self, symbol: str, as_of: date, *, exchange: str | None = None
    ) -> SecurityIdentity | None:
        normalized = symbol.strip().upper()
        matches = tuple(
            item
            for item in self.records
            if (exchange is None or item.exchange == exchange.strip().upper())
            and item.symbol_on(as_of) == normalized
        )
        if len(matches) > 1:
            raise ValueError(
                f"ambiguous point-in-time symbol {normalized} on {as_of.isoformat()}"
            )
        return matches[0] if matches else None

    def existing_on(self, as_of: date) -> tuple[SecurityIdentity, ...]:
        return tuple(item for item in self.records if item.existed_on(as_of) is True)

    def _validate_symbol_intervals(self) -> None:
        symbols: dict[tuple[str, str], list[tuple[date, date | None, str]]] = (
            defaultdict(list)
        )
        for identity in self.records:
            for historical in identity.historical_symbols:
                symbols[(identity.exchange, historical.symbol)].append(
                    (
                        historical.interval.effective_from,
                        historical.interval.effective_to,
                        identity.security_id,
                    )
                )
        for (exchange, symbol), intervals in symbols.items():
            ordered = sorted(
                intervals,
                key=lambda item: (item[0], item[1] or date.max, item[2]),
            )
            for previous, current in zip(ordered, ordered[1:], strict=False):
                previous_end = previous[1]
                if previous_end is None or current[0] <= previous_end:
                    if previous[2] != current[2]:
                        raise ValueError(
                            "overlapping identity intervals for "
                            f"{exchange}:{symbol}: {previous[2]} and {current[2]}"
                        )


__all__ = ["SecurityMaster"]
