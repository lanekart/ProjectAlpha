from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from alpha.market_truth.warehouse.models import (
    AdjustedDailyRecord,
    AdjustmentMode,
    AggregateBar,
    AggregatePeriod,
    CanonicalDailyRecord,
    Exchange,
    SessionInventoryRecord,
    SessionState,
)
from alpha.market_truth.warehouse.storage import WarehouseStore


class WarehouseAggregationService:
    def __init__(self, store: WarehouseStore) -> None:
        self.store = store

    def generate(
        self,
        *,
        period: AggregatePeriod,
        mode: AdjustmentMode = AdjustmentMode.RAW,
    ) -> tuple[AggregateBar, ...]:
        rows: tuple[CanonicalDailyRecord | AdjustedDailyRecord, ...]
        if mode is AdjustmentMode.RAW:
            rows = self.store.daily_records()
        else:
            rows = self.store.adjusted_records(mode)
        records = aggregate_bars(rows, period=period, sessions=self.store.sessions())
        with self.store.transaction() as database:
            self.store.replace_aggregates(records, period=period, database=database)
        return records


def aggregate_bars(
    records: tuple[CanonicalDailyRecord | AdjustedDailyRecord, ...],
    *,
    period: AggregatePeriod,
    sessions: tuple[SessionInventoryRecord, ...] = (),
) -> tuple[AggregateBar, ...]:
    grouped: dict[
        tuple[Exchange, str, tuple[int, int]],
        list[CanonicalDailyRecord | AdjustedDailyRecord],
    ] = defaultdict(list)
    for item in records:
        raw = item.raw if isinstance(item, AdjustedDailyRecord) else item
        bucket = _bucket(raw.trading_date, period)
        grouped[(raw.exchange, raw.security_id, bucket)].append(item)
    output: list[AggregateBar] = []
    for (exchange, security_id, bucket), values in sorted(
        grouped.items(), key=lambda item: str(item[0])
    ):
        values.sort(key=lambda item: _raw(item).trading_date)
        first, last = values[0], values[-1]
        first_raw, last_raw = _raw(first), _raw(last)
        period_start, period_end = _period_bounds(first_raw.trading_date, period)
        expected = _expected_sessions(
            sessions, exchange, period_start, period_end, fallback=len(values)
        )
        turnover_values: list[Decimal] = []
        trade_values: list[int] = []
        for item in values:
            raw = _raw(item)
            if raw.turnover is not None:
                turnover_values.append(raw.turnover)
            if raw.trade_count is not None:
                trade_values.append(raw.trade_count)
        volume = sum((_volume(item) for item in values), Decimal("0"))
        turnover = sum(turnover_values, Decimal("0")) if turnover_values else None
        output.append(
            AggregateBar(
                period=period,
                exchange=exchange,
                security_id=security_id,
                symbol=first_raw.symbol_as_traded,
                period_start=period_start,
                period_end=period_end,
                first_trading_date=first_raw.trading_date,
                last_trading_date=last_raw.trading_date,
                open=_open(first),
                high=max(_high(item) for item in values),
                low=min(_low(item) for item in values),
                close=_close(last),
                volume=volume,
                turnover=turnover,
                trade_count=sum(trade_values) if trade_values else None,
                vwap=(None if turnover is None or volume == 0 else turnover / volume),
                session_count=len({(_raw(item).trading_date) for item in values}),
                expected_session_count=expected,
                completeness=(
                    Decimal("0")
                    if expected == 0
                    else Decimal(len(values)) / Decimal(expected)
                ),
                source_daily_version=last_raw.dataset_version,
                adjustment_policy_version=(
                    "RAW_UNADJUSTED"
                    if isinstance(last, CanonicalDailyRecord)
                    else last.adjustment_policy_version
                ),
            )
        )
    return tuple(output)


def _bucket(value: date, period: AggregatePeriod) -> tuple[int, int]:
    if period is AggregatePeriod.WEEKLY:
        iso = value.isocalendar()
        return iso.year, iso.week
    return value.year, value.month


def _period_bounds(value: date, period: AggregatePeriod) -> tuple[date, date]:
    if period is AggregatePeriod.WEEKLY:
        start = value - timedelta(days=value.weekday())
        return start, start + timedelta(days=6)
    start = value.replace(day=1)
    return start, value.replace(day=calendar.monthrange(value.year, value.month)[1])


def _expected_sessions(
    sessions: tuple[SessionInventoryRecord, ...],
    exchange: Exchange,
    start: date,
    end: date,
    *,
    fallback: int,
) -> int:
    matching = tuple(
        item
        for item in sessions
        if item.exchange == exchange
        and start <= item.session_date <= end
        and item.state is not SessionState.HOLIDAY
    )
    return len(matching) if matching else fallback


def _raw(item: CanonicalDailyRecord | AdjustedDailyRecord) -> CanonicalDailyRecord:
    return item.raw if isinstance(item, AdjustedDailyRecord) else item


def _open(item: CanonicalDailyRecord | AdjustedDailyRecord) -> Decimal:
    return item.open


def _high(item: CanonicalDailyRecord | AdjustedDailyRecord) -> Decimal:
    return item.high


def _low(item: CanonicalDailyRecord | AdjustedDailyRecord) -> Decimal:
    return item.low


def _close(item: CanonicalDailyRecord | AdjustedDailyRecord) -> Decimal:
    return item.close


def _volume(item: CanonicalDailyRecord | AdjustedDailyRecord) -> Decimal:
    return item.volume


__all__ = ["WarehouseAggregationService", "aggregate_bars"]
