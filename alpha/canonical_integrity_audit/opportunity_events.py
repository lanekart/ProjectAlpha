from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

import pandas as pd

from alpha.canonical_integrity_audit.models import (
    LEGACY_DATASET_VERSION,
    MajorOpportunityEvent,
    OpportunityDefinition,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore

DEFAULT_OPPORTUNITY_DEFINITIONS = (
    OpportunityDefinition("UP_20_WITHIN_60", Decimal("0.20"), 60),
    OpportunityDefinition("UP_30_WITHIN_90", Decimal("0.30"), 90),
    OpportunityDefinition("UP_50_WITHIN_180", Decimal("0.50"), 180),
)


class MajorOpportunityEventEngine:
    """Construct bounded forward events with deterministic overlap merging."""

    def construct(
        self,
        *,
        store: LegacyMarketDataStore,
        definitions: tuple[
            OpportunityDefinition, ...
        ] = DEFAULT_OPPORTUNITY_DEFINITIONS,
        start: date | None = None,
        end: date | None = None,
        symbol: str | None = None,
    ) -> tuple[MajorOpportunityEvent, ...]:
        events: list[MajorOpportunityEvent] = []
        for definition in definitions:
            frame = self._candidate_frame(
                store=store,
                definition=definition,
                start=start,
                end=end,
                symbol=symbol,
            )
            events.extend(self._events_from_candidates(frame, definition))
        return _deduplicate_cross_definition(tuple(events))

    def construct_from_frame(
        self,
        frame: pd.DataFrame,
        *,
        definitions: tuple[
            OpportunityDefinition, ...
        ] = DEFAULT_OPPORTUNITY_DEFINITIONS,
    ) -> tuple[MajorOpportunityEvent, ...]:
        required = {"symbol", "trade_date", "high", "low", "close", "volume"}
        if not required.issubset(frame.columns):
            raise ValueError("opportunity frame requires symbol/date/OHLCV fields")
        rows: list[MajorOpportunityEvent] = []
        for definition in definitions:
            candidates = []
            for symbol, group in frame.sort_values("trade_date").groupby("symbol"):
                ordered = group.reset_index(drop=True)
                for index in range(len(ordered) - 1):
                    future = ordered.iloc[
                        index + 1 : index + 1 + definition.forward_horizon
                    ]
                    if future.empty:
                        continue
                    start_price = Decimal(str(ordered.iloc[index]["close"]))
                    peak_index = int(future["high"].astype(float).idxmax())
                    peak = ordered.loc[peak_index]
                    peak_price = Decimal(str(peak["high"]))
                    forward_return = peak_price / start_price - 1
                    if forward_return < definition.minimum_return:
                        continue
                    pre_peak = ordered.iloc[index + 1 : peak_index + 1]
                    minimum = Decimal(str(pre_peak["low"].min()))
                    average_volume = ordered.iloc[max(0, index - 19) : index + 1][
                        "volume"
                    ].mean()
                    current_volume = Decimal(str(ordered.iloc[index]["volume"]))
                    candidates.append(
                        {
                            "symbol": str(symbol).upper(),
                            "start_date": _as_date(ordered.iloc[index]["trade_date"]),
                            "peak_date": _as_date(peak["trade_date"]),
                            "start_price": start_price,
                            "peak_price": peak_price,
                            "forward_return": forward_return,
                            "mae": minimum / start_price - 1,
                            "volume_expansion": (
                                None
                                if average_volume is None or average_volume <= 0
                                else current_volume / Decimal(str(average_volume))
                            ),
                            "time_to_peak": peak_index - index,
                            "trend_state": _trend_state(ordered, index),
                        }
                    )
            rows.extend(
                self._events_from_candidates(pd.DataFrame(candidates), definition)
            )
        return _deduplicate_cross_definition(tuple(rows))

    def _candidate_frame(
        self,
        *,
        store: LegacyMarketDataStore,
        definition: OpportunityDefinition,
        start: date | None,
        end: date | None,
        symbol: str | None,
    ) -> pd.DataFrame:
        filters = ["forward_high / close - 1 >= ?"]
        parameters: list[object] = [definition.minimum_return]
        if start is not None:
            filters.append("trade_date >= ?")
            parameters.append(start)
        if end is not None:
            filters.append("trade_date <= ?")
            parameters.append(end)
        if symbol is not None:
            filters.append("UPPER(symbol) = ?")
            parameters.append(symbol.strip().upper())
        where = " AND ".join(filters)
        horizon = definition.forward_horizon
        return store.connection.execute(
            f"""
            WITH base AS (
                SELECT
                    UPPER(symbol) AS symbol,
                    trade_date,
                    high,
                    low,
                    close,
                    volume,
                    ROW_NUMBER() OVER (
                        PARTITION BY UPPER(symbol) ORDER BY trade_date
                    ) AS sequence,
                    AVG(close) OVER (
                        PARTITION BY UPPER(symbol) ORDER BY trade_date
                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS average_close_20,
                    AVG(CAST(volume AS DOUBLE)) OVER (
                        PARTITION BY UPPER(symbol) ORDER BY trade_date
                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS average_volume_20
                FROM daily_prices
                WHERE open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0
            ), ordered AS (
                SELECT
                    *,
                    MAX(high) OVER (
                        PARTITION BY symbol ORDER BY trade_date
                        ROWS BETWEEN 1 FOLLOWING AND {horizon} FOLLOWING
                    ) AS forward_high,
                    ARG_MAX(trade_date, high) OVER (
                        PARTITION BY symbol ORDER BY trade_date
                        ROWS BETWEEN 1 FOLLOWING AND {horizon} FOLLOWING
                    ) AS peak_date,
                    ARG_MAX(sequence, high) OVER (
                        PARTITION BY symbol ORDER BY trade_date
                        ROWS BETWEEN 1 FOLLOWING AND {horizon} FOLLOWING
                    ) AS peak_sequence
                FROM base
            )
            SELECT
                symbol,
                trade_date AS start_date,
                peak_date,
                close AS start_price,
                forward_high AS peak_price,
                forward_high / close - 1 AS forward_return,
                (
                    SELECT MIN(future.low)
                    FROM daily_prices AS future
                    WHERE UPPER(future.symbol) = ordered.symbol
                      AND future.trade_date > ordered.trade_date
                      AND future.trade_date <= ordered.peak_date
                ) / close - 1 AS mae,
                CASE
                    WHEN average_volume_20 > 0 THEN volume / average_volume_20
                    ELSE NULL
                END AS volume_expansion,
                CAST(peak_sequence - sequence AS INTEGER) AS time_to_peak,
                CASE WHEN close >= average_close_20 THEN 'ABOVE_20_SESSION_MEAN'
                     ELSE 'BELOW_20_SESSION_MEAN' END AS trend_state
            FROM ordered
            WHERE {where}
            ORDER BY symbol, start_date
            """,
            tuple(parameters),
        ).fetchdf()

    def _events_from_candidates(
        self,
        frame: pd.DataFrame,
        definition: OpportunityDefinition,
    ) -> tuple[MajorOpportunityEvent, ...]:
        if frame.empty:
            return ()
        selected: list[dict[str, object]] = []
        for _, group in frame.sort_values(["symbol", "start_date"]).groupby("symbol"):
            cluster: list[dict[str, object]] = []
            cluster_peak: date | None = None
            for raw_row in group.to_dict("records"):
                row = cast(dict[str, object], raw_row)
                start_date = _as_date(row["start_date"])
                if cluster and cluster_peak is not None and start_date > cluster_peak:
                    selected.append(_representative(cluster))
                    cluster = []
                    cluster_peak = None
                cluster.append(row)
                peak_date = _as_date(row["peak_date"])
                cluster_peak = (
                    peak_date if cluster_peak is None else max(cluster_peak, peak_date)
                )
            if cluster:
                selected.append(_representative(cluster))
        events = []
        for row in selected:
            symbol = str(row["symbol"]).upper()
            start_date = _as_date(row["start_date"])
            peak_date = _as_date(row["peak_date"])
            forward_return = Decimal(str(row["forward_return"]))
            start_price = Decimal(str(row["start_price"]))
            peak_price = Decimal(str(row["peak_price"]))
            events.append(
                MajorOpportunityEvent(
                    event_id=_event_id(symbol, start_date, definition.name),
                    symbol=symbol,
                    start_date=start_date,
                    breakout_date=start_date,
                    peak_date=peak_date,
                    forward_horizon=definition.forward_horizon,
                    forward_return=forward_return,
                    event_definition=definition.name,
                    maximum_forward_return=forward_return,
                    time_to_peak=int(str(row["time_to_peak"])),
                    maximum_adverse_excursion_before_peak=min(
                        Decimal("0"), Decimal(str(row["mae"]))
                    ),
                    volume_expansion=_optional_decimal(row.get("volume_expansion")),
                    base_length=20,
                    trend_state=str(row["trend_state"]),
                    start_price=start_price,
                    peak_price=peak_price,
                    dataset_version=LEGACY_DATASET_VERSION,
                )
            )
        return tuple(events)


def _representative(cluster: list[dict[str, object]]) -> dict[str, object]:
    return min(
        cluster,
        key=lambda row: (
            -Decimal(str(row["forward_return"])),
            _as_date(row["start_date"]),
        ),
    )


def _event_id(symbol: str, start_date: date, definition: str) -> str:
    payload = f"{symbol}|{start_date.isoformat()}|{definition}|{LEGACY_DATASET_VERSION}"
    return "major-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _as_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return pd.Timestamp(cast(Any, value)).date()


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or bool(pd.isna(cast(Any, value))):
        return None
    return Decimal(str(value))


def _trend_state(frame: pd.DataFrame, index: int) -> str:
    window = frame.iloc[max(0, index - 19) : index + 1]
    mean = Decimal(str(window["close"].mean()))
    close = Decimal(str(frame.iloc[index]["close"]))
    return "ABOVE_20_SESSION_MEAN" if close >= mean else "BELOW_20_SESSION_MEAN"


def _deduplicate_cross_definition(
    events: tuple[MajorOpportunityEvent, ...],
) -> tuple[MajorOpportunityEvent, ...]:
    grouped: dict[tuple[str, date], list[MajorOpportunityEvent]] = {}
    for event in events:
        grouped.setdefault((event.symbol, event.peak_date), []).append(event)
    selected = tuple(
        min(
            rows,
            key=lambda item: (
                -item.forward_return,
                item.start_date,
                -item.forward_horizon,
                item.event_definition,
            ),
        )
        for rows in grouped.values()
    )
    return tuple(
        sorted(
            selected,
            key=lambda item: (
                item.symbol,
                item.start_date,
                item.event_definition,
            ),
        )
    )


__all__ = ["DEFAULT_OPPORTUNITY_DEFINITIONS", "MajorOpportunityEventEngine"]
