from __future__ import annotations

import hashlib
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import replace
from datetime import date

import pandas as pd

from alpha.candidate_generation_research.feature_snapshots import (
    PointInTimeFeatureEngine,
)
from alpha.candidate_generation_research.models import TradableOpportunityOnset
from alpha.candidate_generation_research.tradability import (
    TradabilityConfig,
    TradabilityEngine,
)
from alpha.canonical_integrity_audit.models import MajorOpportunityEvent
from alpha.canonical_universe_audit.store import LegacyMarketDataStore


class TradableOpportunityOnsetEngine:
    """Detect point-in-time onsets, then associate them with outcome labels."""

    def detect(
        self,
        *,
        store: LegacyMarketDataStore,
        start: date | None = None,
        end: date | None = None,
        symbol: str | None = None,
        config: TradabilityConfig = TradabilityConfig(),
    ) -> tuple[TradableOpportunityOnset, ...]:
        detected_rows: list[TradableOpportunityOnset] = []
        feature_engine = PointInTimeFeatureEngine()
        tradability_engine = TradabilityEngine()
        for batch in feature_engine.iter_store_candidate_batches(
            store=store, start=start, end=end, symbol=symbol
        ):
            detected_rows.extend(
                onset
                for item in batch
                if (onset := tradability_engine.assess(item, config=config)) is not None
            )
        detected = tuple(detected_rows)
        return merge_duplicate_onsets(detected)

    def detect_frame(
        self,
        frame: pd.DataFrame,
        *,
        config: TradabilityConfig = TradabilityConfig(),
    ) -> tuple[TradableOpportunityOnset, ...]:
        detected = tuple(
            onset
            for item in PointInTimeFeatureEngine().build(frame)
            if (onset := TradabilityEngine().assess(item, config=config)) is not None
        )
        return merge_duplicate_onsets(detected)

    def associate(
        self,
        *,
        store: LegacyMarketDataStore,
        events: tuple[MajorOpportunityEvent, ...],
        onsets: tuple[TradableOpportunityOnset, ...],
        pre_event_sessions: int = 60,
    ) -> tuple[TradableOpportunityOnset, ...]:
        positions = _event_positions(store, events)
        by_symbol: dict[str, list[TradableOpportunityOnset]] = defaultdict(list)
        for onset in onsets:
            by_symbol[onset.symbol].append(onset)
        ordered_by_symbol = {
            symbol_key: tuple(
                sorted(symbol_onsets, key=lambda item: item.onset_sequence)
            )
            for symbol_key, symbol_onsets in by_symbol.items()
        }
        sequences_by_symbol = {
            symbol_key: tuple(item.onset_sequence for item in symbol_onsets)
            for symbol_key, symbol_onsets in ordered_by_symbol.items()
        }
        associated = []
        for event in events:
            position = positions.get(event.event_id)
            if position is None:
                continue
            start_sequence, peak_sequence = position
            rows = ordered_by_symbol.get(event.symbol, ())
            sequences = sequences_by_symbol.get(event.symbol, ())
            left = bisect_left(sequences, max(0, start_sequence - pre_event_sessions))
            right = bisect_right(sequences, peak_sequence)
            relevant = rows[left:right]
            selected = _materially_distinct(list(relevant))
            for onset in selected:
                associated.append(
                    replace(
                        onset,
                        onset_id=_associated_id(event.event_id, onset.onset_id),
                        forward_event_id=event.event_id,
                    )
                )
        return tuple(
            sorted(
                associated,
                key=lambda item: (
                    item.symbol,
                    item.onset_date,
                    item.forward_event_id or "",
                    item.event_family,
                ),
            )
        )


def merge_duplicate_onsets(
    values: tuple[TradableOpportunityOnset, ...],
    *,
    cooldown: int = 10,
) -> tuple[TradableOpportunityOnset, ...]:
    selected: list[TradableOpportunityOnset] = []
    latest: dict[tuple[str, str], int] = {}
    for item in sorted(
        values,
        key=lambda value: (value.symbol, value.onset_sequence, value.event_family),
    ):
        key = (item.symbol, item.event_family.value)
        previous = latest.get(key)
        if previous is not None and item.onset_sequence - previous <= cooldown:
            continue
        selected.append(item)
        latest[key] = item.onset_sequence
    return tuple(selected)


def _materially_distinct(
    values: list[TradableOpportunityOnset],
) -> tuple[TradableOpportunityOnset, ...]:
    selected: list[TradableOpportunityOnset] = []
    for item in values:
        if not selected:
            selected.append(item)
            continue
        if (
            item.event_family != selected[-1].event_family
            and item.onset_sequence - selected[-1].onset_sequence >= 10
        ):
            selected.append(item)
        if len(selected) == 2:
            break
    return tuple(selected)


def _event_positions(
    store: LegacyMarketDataStore,
    events: tuple[MajorOpportunityEvent, ...],
) -> dict[str, tuple[int, int]]:
    if not events:
        return {}
    frame = pd.DataFrame(
        {
            "event_id": item.event_id,
            "symbol": item.symbol,
            "start_date": item.start_date,
            "peak_date": item.peak_date,
        }
        for item in events
    )
    store.connection.register("_candidate_research_events", frame)
    try:
        rows = store.connection.execute(
            """
            WITH indexed AS (
                SELECT
                    UPPER(symbol) AS symbol,
                    trade_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY UPPER(symbol) ORDER BY trade_date
                    ) - 1 AS sequence
                FROM daily_prices
                WHERE open > 0 AND high > 0 AND low > 0 AND close > 0
                  AND volume >= 0
                  AND high >= GREATEST(open, low, close)
                  AND low <= LEAST(open, high, close)
            )
            SELECT
                events.event_id,
                start_bar.sequence AS start_sequence,
                peak_bar.sequence AS peak_sequence
            FROM _candidate_research_events AS events
            LEFT JOIN indexed AS start_bar
              ON start_bar.symbol = UPPER(events.symbol)
             AND start_bar.trade_date = events.start_date
            LEFT JOIN indexed AS peak_bar
              ON peak_bar.symbol = UPPER(events.symbol)
             AND peak_bar.trade_date = events.peak_date
            ORDER BY events.event_id
            """
        ).fetchall()
    finally:
        store.connection.unregister("_candidate_research_events")
    return {
        str(event_id): (int(start_sequence), int(peak_sequence))
        for event_id, start_sequence, peak_sequence in rows
        if start_sequence is not None and peak_sequence is not None
    }


def _associated_id(event_id: str, onset_id: str) -> str:
    payload = f"{event_id}|{onset_id}"
    return "linked-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


__all__ = ["TradableOpportunityOnsetEngine", "merge_duplicate_onsets"]
