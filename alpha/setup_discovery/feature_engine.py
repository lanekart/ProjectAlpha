from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.setup_discovery.models import (
    ChartBar,
    EvidenceChart,
    EvidencePartition,
    GeometryState,
    RawMissedSetupCase,
    SetupFeatureRecord,
)

FEATURE_VERSION = "point-in-time-technical-features-v1.0"
_FEATURE_NAMES = (
    "base_duration",
    "base_depth",
    "volatility_contraction",
    "moving_average_alignment",
    "relative_strength_trend",
    "breakout_angle",
    "breakout_volume",
    "atr_expansion",
    "trend_slope",
    "liquidity_profile",
    "geometry_flat",
    "geometry_ascending",
    "geometry_contracting",
    "geometry_reversal",
    "geometry_irregular",
)


@dataclass(frozen=True, slots=True)
class PreparedHistory:
    symbol: str
    frame: pd.DataFrame


class SetupFeatureEngine:
    """Build causal technical features and attach outcomes after extraction."""

    def extract(
        self,
        *,
        store: LegacyMarketDataStore,
        cases: tuple[RawMissedSetupCase, ...],
    ) -> tuple[SetupFeatureRecord, ...]:
        if not cases:
            return ()
        dates = store.trade_dates()
        partition_boundaries = _partition_boundaries(dates)
        by_symbol: dict[str, list[RawMissedSetupCase]] = {}
        for case in cases:
            by_symbol.setdefault(case.symbol, []).append(case)
        records: list[SetupFeatureRecord] = []
        symbols = tuple(sorted(by_symbol))
        for batch in _batches(symbols, 100):
            batch_cases = tuple(case for symbol in batch for case in by_symbol[symbol])
            histories = _load_histories(store, batch_cases)
            for case in batch_cases:
                history = histories.get(case.symbol)
                if history is None:
                    continue
                record = _extract_case(case, history, partition_boundaries)
                if record is not None:
                    records.append(record)
        return tuple(
            sorted(
                records, key=lambda item: (item.symbol, item.onset_date, item.case_id)
            )
        )

    def charts(
        self,
        *,
        store: LegacyMarketDataStore,
        cases: tuple[RawMissedSetupCase, ...],
        chart_bars: int = 90,
    ) -> tuple[EvidenceChart, ...]:
        if chart_bars < 20:
            raise ValueError("evidence charts require at least 20 bars")
        if not cases:
            return ()
        histories = _load_histories(store, cases, include_future=False)
        charts: list[EvidenceChart] = []
        for case in cases:
            history = histories.get(case.symbol)
            if history is None:
                continue
            visible = history.loc[history["trade_date"] <= case.onset_date].tail(
                chart_bars
            )
            if visible.empty:
                continue
            bars = tuple(
                ChartBar(
                    observed_on=_as_date(row.trade_date),
                    close=_decimal(row.close),
                    volume=_decimal(row.volume),
                    ema_20=_optional_decimal(row.ema_20),
                    ema_50=_optional_decimal(row.ema_50),
                )
                for row in visible.itertuples(index=False)
            )
            charts.append(
                EvidenceChart(
                    case_id=case.case_id,
                    symbol=case.symbol,
                    onset_date=case.onset_date,
                    bars=bars,
                )
            )
        return tuple(charts)


def cluster_feature_names() -> tuple[str, ...]:
    return _FEATURE_NAMES


def load_histories(
    store: LegacyMarketDataStore,
    cases: tuple[RawMissedSetupCase, ...],
    *,
    include_future: bool = True,
) -> Mapping[str, pd.DataFrame]:
    """Expose the causal history loader to the proof engine."""

    return _load_histories(store, cases, include_future=include_future)


def _load_histories(
    store: LegacyMarketDataStore,
    cases: tuple[RawMissedSetupCase, ...],
    *,
    include_future: bool = True,
) -> dict[str, pd.DataFrame]:
    if not cases:
        return {}
    symbols = tuple(sorted({case.symbol for case in cases}))
    first = min(case.onset_date for case in cases) - timedelta(days=420)
    last_extra = 180 if include_future else 0
    last = max(case.onset_date for case in cases) + timedelta(days=last_extra)
    placeholders = ", ".join("?" for _ in symbols)
    frame = store.connection.execute(
        f"""
        SELECT UPPER(symbol) AS symbol, trade_date, open, high, low, close, volume
        FROM daily_prices
        WHERE UPPER(symbol) IN ({placeholders})
          AND trade_date BETWEEN ? AND ?
          AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0
        ORDER BY symbol, trade_date
        """,
        (*symbols, first, last),
    ).fetchdf()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    result: dict[str, pd.DataFrame] = {}
    for symbol, raw in frame.groupby("symbol", sort=True):
        history = raw.drop_duplicates(subset="trade_date", keep="last").copy()
        history["ema_20"] = history["close"].ewm(span=20, adjust=False).mean()
        history["ema_50"] = history["close"].ewm(span=50, adjust=False).mean()
        result[str(symbol)] = history.reset_index(drop=True)
    return result


def _extract_case(
    case: RawMissedSetupCase,
    history: pd.DataFrame,
    boundaries: tuple[date, date],
) -> SetupFeatureRecord | None:
    matched = history.index[history["trade_date"] == case.onset_date]
    if matched.empty:
        return None
    index = int(matched[-1])
    if index < 19:
        return None
    visible = history.iloc[: index + 1]
    current = visible.iloc[-1]
    recent_20 = visible.tail(20)
    support = _input(case.point_in_time_inputs, "support_20") or _decimal(
        recent_20["low"].min()
    )
    resistance = _input(case.point_in_time_inputs, "resistance_20") or _decimal(
        recent_20["high"].max()
    )
    base_duration = _base_duration(visible, support, resistance)
    base_window = visible.tail(max(20, min(base_duration, 80)))
    base_depth = _safe_ratio(
        _decimal(base_window["high"].max()) - _decimal(base_window["low"].min()),
        _decimal(base_window["high"].max()),
    )
    contraction = _contraction(visible)
    close = _decimal(current["close"])
    ema_20 = _input(case.point_in_time_inputs, "ema_20") or _decimal(current["ema_20"])
    ema_50 = _input(case.point_in_time_inputs, "ema_50") or _decimal(current["ema_50"])
    alignment = _safe_ratio(ema_20 - ema_50, close)
    relative_strength = _input(case.point_in_time_inputs, "relative_strength_20")
    angle = _normalized_slope(visible["close"].tail(10))
    trend_slope = _normalized_slope(visible["close"].tail(20))
    volume_ratio = _input(case.point_in_time_inputs, "volume_ratio_20")
    atr = _input(case.point_in_time_inputs, "atr_14")
    true_range = _decimal(current["high"]) - _decimal(current["low"])
    atr_expansion = None
    if atr is not None and atr != 0:
        atr_expansion = true_range / atr
    liquidity = _liquidity(case, recent_20)
    geometry = _geometry(
        visible=visible,
        contraction=contraction,
        trend_slope=trend_slope,
        ema_20=ema_20,
        close=close,
        base_depth=base_depth,
    )
    point_features: dict[str, object] = {
        "case_id": case.case_id,
        "onset_date": case.onset_date.isoformat(),
        "base_duration": base_duration,
        "base_depth": str(base_depth),
        "volatility_contraction": _string(contraction),
        "moving_average_alignment": _string(alignment),
        "relative_strength_trend": _string(relative_strength),
        "breakout_angle": str(angle),
        "breakout_volume": _string(volume_ratio),
        "atr_expansion": _string(atr_expansion),
        "trend_slope": str(trend_slope),
        "consolidation_geometry": geometry.value,
        "liquidity_profile": _string(liquidity),
        "source_feature_hash": case.point_in_time_inputs.get("feature_hash"),
        "feature_version": FEATURE_VERSION,
    }
    return SetupFeatureRecord(
        case_id=case.case_id,
        event_id=case.event_id,
        onset_id=case.onset_id,
        symbol=case.symbol,
        onset_date=case.onset_date,
        event_family=case.event_family,
        failure_reason=case.failure_reason,
        base_duration=base_duration,
        base_depth=_quantize(base_depth),
        volatility_contraction=_quantize_optional(contraction),
        moving_average_alignment=_quantize_optional(alignment),
        relative_strength_trend=_quantize_optional(relative_strength),
        breakout_angle=_quantize(angle),
        breakout_volume=_quantize_optional(volume_ratio),
        atr_expansion=_quantize_optional(atr_expansion),
        trend_slope=_quantize(trend_slope),
        consolidation_geometry=geometry,
        liquidity_profile=_quantize_optional(liquidity),
        prospective_rr=case.prospective_rr,
        onset_confidence=case.onset_confidence,
        forward_return=case.forward_return,
        holding_period=case.event_holding_period,
        net_return_60=_net_return_60(history, index, close),
        partition=_partition(case.onset_date, boundaries),
        feature_hash=_hash(point_features),
    )


def _partition_boundaries(dates: tuple[date, ...]) -> tuple[date, date]:
    if not dates:
        raise ValueError("market history has no sessions")
    development_end = dates[min(len(dates) - 1, max(0, int(len(dates) * 0.60) - 1))]
    validation_end = dates[min(len(dates) - 1, max(0, int(len(dates) * 0.80) - 1))]
    return development_end, validation_end


def _partition(observed_on: date, boundaries: tuple[date, date]) -> EvidencePartition:
    if observed_on <= boundaries[0]:
        return EvidencePartition.DEVELOPMENT
    if observed_on <= boundaries[1]:
        return EvidencePartition.VALIDATION
    return EvidencePartition.HOLDOUT


def _base_duration(
    visible: pd.DataFrame,
    support: Decimal,
    resistance: Decimal,
) -> int:
    lower = support * Decimal("0.97")
    upper = resistance * Decimal("1.03")
    count = 0
    for row in reversed(tuple(visible.tail(160).itertuples(index=False))):
        if _decimal(row.low) < lower or _decimal(row.high) > upper:
            break
        count += 1
    return max(1, count)


def _contraction(visible: pd.DataFrame) -> Decimal | None:
    if len(visible) < 20:
        return None
    ranges = (visible["high"] - visible["low"]) / visible["close"]
    recent = float(ranges.tail(5).mean())
    prior = float(ranges.iloc[-20:-5].mean())
    if prior <= 0 or not math.isfinite(recent) or not math.isfinite(prior):
        return None
    return Decimal(str(recent / prior))


def _normalized_slope(series: pd.Series[Any]) -> Decimal:
    values = np.asarray(series, dtype=float)
    if len(values) < 2 or float(np.mean(values)) <= 0:
        return Decimal("0")
    x_values = np.arange(len(values), dtype=float)
    slope = float(np.polyfit(x_values, values, 1)[0]) / float(np.mean(values))
    return Decimal(str(slope))


def _geometry(
    *,
    visible: pd.DataFrame,
    contraction: Decimal | None,
    trend_slope: Decimal,
    ema_20: Decimal,
    close: Decimal,
    base_depth: Decimal,
) -> GeometryState:
    if contraction is not None and contraction <= Decimal("0.80"):
        return GeometryState.CONTRACTING
    lows = np.asarray(visible["low"].tail(20), dtype=float)
    low_slope = (
        0.0 if len(lows) < 2 else float(np.polyfit(np.arange(len(lows)), lows, 1)[0])
    )
    return_20 = _safe_ratio(close, _decimal(visible.iloc[-20]["close"])) - Decimal("1")
    if return_20 < 0 and close >= ema_20:
        return GeometryState.REVERSAL
    if trend_slope > Decimal("0.001") and low_slope > 0:
        return GeometryState.ASCENDING
    if base_depth <= Decimal("0.18"):
        return GeometryState.FLAT
    return GeometryState.IRREGULAR


def _liquidity(
    case: RawMissedSetupCase,
    recent_20: pd.DataFrame,
) -> Decimal | None:
    turnover = _input(case.point_in_time_inputs, "average_turnover_20")
    if turnover is None:
        turnover = _decimal((recent_20["close"] * recent_20["volume"]).mean())
    if turnover <= 0:
        return None
    return Decimal(str(math.log10(float(turnover))))


def _net_return_60(
    history: pd.DataFrame,
    index: int,
    entry: Decimal,
) -> Decimal | None:
    future_index = index + 60
    if future_index >= len(history) or entry <= 0:
        return None
    exit_price = _decimal(history.iloc[future_index]["close"])
    return _quantize(exit_price / entry - Decimal("1.002"))


def _input(values: Mapping[str, str], key: str) -> Decimal | None:
    value = values.get(key)
    if value is None or value.upper() in {"", "NONE", "UNAVAILABLE"}:
        return None
    try:
        return Decimal(value)
    except ArithmeticError:
        return None


def _safe_ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    return Decimal("0") if denominator == 0 else numerator / denominator


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))


def _quantize_optional(value: Decimal | None) -> Decimal | None:
    return None if value is None else _quantize(value)


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    parsed = _decimal(value)
    return None if not parsed.is_finite() else parsed


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _string(value: object | None) -> str | None:
    return None if value is None else str(value)


def _hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _batches(values: tuple[str, ...], size: int) -> Iterable[tuple[str, ...]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


__all__ = [
    "FEATURE_VERSION",
    "SetupFeatureEngine",
    "cluster_feature_names",
    "load_histories",
]
