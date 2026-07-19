from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from alpha.market_truth.warehouse.models import (
    Exchange,
    SessionInventoryRecord,
    SessionState,
)
from alpha.market_truth.warehouse.storage import WarehouseStore


@dataclass(frozen=True, slots=True)
class SessionCoverage:
    exchange: Exchange
    start: date
    end: date
    expected: int
    validated: int
    partial: int
    missing: int
    holidays: int
    special_sessions: int
    quarantined: int
    superseded: int


class HistoricalSessionInventory:
    def __init__(self, store: WarehouseStore) -> None:
        self.store = store

    def materialise(
        self,
        *,
        start: date,
        end: date,
        exchanges: tuple[Exchange, ...] = (Exchange.NSE, Exchange.BSE),
        holidays: dict[Exchange, frozenset[date]] | None = None,
        special_sessions: dict[Exchange, frozenset[date]] | None = None,
    ) -> tuple[SessionInventoryRecord, ...]:
        if end < start:
            raise ValueError("session inventory end cannot precede start")
        current = {
            (item.exchange, item.session_date): item for item in self.store.sessions()
        }
        output: list[SessionInventoryRecord] = []
        holiday_map = holidays or {}
        special_map = special_sessions or {}
        for exchange in exchanges:
            cursor = start
            while cursor <= end:
                existing = current.get((exchange, cursor))
                if existing is not None and existing.state not in {
                    SessionState.EXPECTED,
                    SessionState.MISSING,
                    SessionState.HOLIDAY,
                }:
                    output.append(existing)
                elif cursor in special_map.get(exchange, frozenset()):
                    output.append(
                        SessionInventoryRecord(
                            exchange,
                            cursor,
                            SessionState.SPECIAL_SESSION,
                            None,
                            "Exchange calendar marks a special session.",
                        )
                    )
                elif cursor.weekday() >= 5 or cursor in holiday_map.get(
                    exchange, frozenset()
                ):
                    output.append(
                        SessionInventoryRecord(
                            exchange,
                            cursor,
                            SessionState.HOLIDAY,
                            None,
                            "Non-session according to the supplied exchange calendar.",
                        )
                    )
                else:
                    output.append(
                        SessionInventoryRecord(
                            exchange,
                            cursor,
                            SessionState.MISSING,
                            None,
                            "Expected weekday session has no validated source file.",
                        )
                    )
                cursor += timedelta(days=1)
        records = tuple(output)
        self.store.upsert_sessions(records)
        return records

    def missing(
        self, exchange: Exchange | None = None
    ) -> tuple[SessionInventoryRecord, ...]:
        return self.store.sessions(
            exchange=exchange,
            states=(
                SessionState.MISSING,
                SessionState.PARTIAL,
                SessionState.QUARANTINED,
            ),
        )

    def coverage(
        self, *, exchange: Exchange, start: date, end: date
    ) -> SessionCoverage:
        records = tuple(
            item
            for item in self.store.sessions(exchange=exchange)
            if start <= item.session_date <= end
        )
        active = tuple(
            item for item in records if item.state is not SessionState.HOLIDAY
        )
        return SessionCoverage(
            exchange=exchange,
            start=start,
            end=end,
            expected=len(active),
            validated=sum(item.state is SessionState.VALIDATED for item in records),
            partial=sum(item.state is SessionState.PARTIAL for item in records),
            missing=sum(item.state is SessionState.MISSING for item in records),
            holidays=sum(item.state is SessionState.HOLIDAY for item in records),
            special_sessions=sum(
                item.state is SessionState.SPECIAL_SESSION for item in records
            ),
            quarantined=sum(item.state is SessionState.QUARANTINED for item in records),
            superseded=sum(item.state is SessionState.SUPERSEDED for item in records),
        )


__all__ = ["HistoricalSessionInventory", "SessionCoverage"]
