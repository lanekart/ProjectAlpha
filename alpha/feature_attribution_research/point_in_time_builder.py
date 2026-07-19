"""Causal feature construction using only bars visible at each onset."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.feature_attribution_research.feature_registry import FeatureRegistry
from alpha.feature_attribution_research.models import (
    EvidencePartition,
    FeatureScalar,
    FeatureSnapshot,
    ResearchPopulationRecord,
)

DEFAULT_CANDIDATE_LEDGER = Path(".alpha/candidate_learning_ledger.json")
DEFAULT_ACU_RANKINGS = Path(".alpha/acu/ALPHA_CANONICAL_v1.0/candidate_rankings.csv")
_PERCENTILE_FEATURES = {
    "turnover_percentile": "turnover_20d",
    "atr_percentile": "atr_percent",
    "bandwidth_percentile": "bollinger_bandwidth",
}


class PointInTimeFeatureBuilder:
    """Build raw features in symbol batches and freeze development transforms."""

    def build(
        self,
        *,
        store: LegacyMarketDataStore,
        population: tuple[ResearchPopulationRecord, ...],
        candidate_ledger: Path | str = DEFAULT_CANDIDATE_LEDGER,
        acu_rankings: Path | str = DEFAULT_ACU_RANKINGS,
        batch_size: int = 100,
    ) -> tuple[FeatureSnapshot, ...]:
        if batch_size < 1:
            raise ValueError("feature batch size must be positive")
        components = _canonical_components(Path(candidate_ledger), Path(acu_rankings))
        by_symbol: dict[str, list[ResearchPopulationRecord]] = {}
        for item in population:
            by_symbol.setdefault(item.symbol, []).append(item)
        rows: list[FeatureSnapshot] = []
        symbols = tuple(sorted(by_symbol))
        for batch in _batches(symbols, batch_size):
            history = _load_history(store, batch)
            for symbol, group in history.groupby("symbol", sort=True):
                symbol_rows = tuple(
                    sorted(
                        by_symbol.get(str(symbol), ()), key=lambda item: item.onset_date
                    )
                )
                rows.extend(
                    self.build_frame(
                        frame=group,
                        population=symbol_rows,
                        canonical_components=components,
                    )
                )
        return apply_development_transforms(
            tuple(sorted(rows, key=lambda item: item.onset_id))
        )

    def build_frame(
        self,
        *,
        frame: pd.DataFrame,
        population: tuple[ResearchPopulationRecord, ...],
        canonical_components: Mapping[tuple[str, date], Mapping[str, float | None]]
        | None = None,
    ) -> tuple[FeatureSnapshot, ...]:
        required = {"symbol", "trade_date", "open", "high", "low", "close", "volume"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"feature history missing columns: {sorted(missing)}")
        if frame.empty or not population:
            return ()
        history = _prepare_history(frame)
        arrays = _history_arrays(history)
        date_to_index = {
            value: index for index, value in enumerate(history["trade_date"])
        }
        component_values = canonical_components or {}
        definitions = FeatureRegistry().feature_ids
        snapshots: list[FeatureSnapshot] = []
        for item in population:
            index = date_to_index.get(item.onset_date)
            if index is None:
                continue
            values = _feature_values(arrays, index, item)
            values.update(component_values.get((item.symbol, item.onset_date), {}))
            normalized = tuple((name, values.get(name)) for name in definitions)
            snapshots.append(
                FeatureSnapshot(
                    onset_id=item.onset_id,
                    symbol=item.symbol,
                    onset_date=item.onset_date,
                    partition=item.partition,
                    values=normalized,
                    source_max_date=item.onset_date,
                    feature_snapshot_hash=_feature_hash(item, normalized),
                )
            )
        return tuple(snapshots)


def apply_development_transforms(
    snapshots: tuple[FeatureSnapshot, ...],
) -> tuple[FeatureSnapshot, ...]:
    """Fit percentile reference distributions on development only."""

    reference: dict[str, np.ndarray[Any, np.dtype[np.float64]]] = {}
    for output, source in _PERCENTILE_FEATURES.items():
        del output
        development_values = [
            _numeric(item.value(source))
            for item in snapshots
            if item.partition is EvidencePartition.DEVELOPMENT
        ]
        reference[source] = np.sort(
            np.asarray(
                [item for item in development_values if item is not None], dtype=float
            )
        )
    result: list[FeatureSnapshot] = []
    for snapshot in snapshots:
        transformed: dict[str, FeatureScalar] = dict(snapshot.values)
        for output, source in _PERCENTILE_FEATURES.items():
            raw = _numeric(transformed.get(source))
            sample = reference[source]
            transformed[output] = (
                None
                if raw is None or sample.size == 0
                else float(np.searchsorted(sample, raw, side="right") / sample.size)
            )
        normalized = tuple((name, transformed[name]) for name, _ in snapshot.values)
        result.append(
            replace(
                snapshot,
                values=normalized,
                feature_snapshot_hash=_hash_values(snapshot.onset_id, normalized),
            )
        )
    return tuple(result)


def _prepare_history(frame: pd.DataFrame) -> pd.DataFrame:
    history = frame.copy()
    history["symbol"] = history["symbol"].astype(str).str.upper()
    history["trade_date"] = pd.to_datetime(history["trade_date"]).dt.date
    history = history.sort_values("trade_date").drop_duplicates(
        subset="trade_date", keep="last"
    )
    close = history["close"].astype(float)
    for period in (20, 50, 200):
        history[f"ema_{period}"] = close.ewm(
            span=period, adjust=False, min_periods=period
        ).mean()
    previous = close.shift(1)
    history["true_range"] = pd.concat(
        (
            history["high"].astype(float) - history["low"].astype(float),
            (history["high"].astype(float) - previous).abs(),
            (history["low"].astype(float) - previous).abs(),
        ),
        axis=1,
    ).max(axis=1)
    history["atr_14"] = history["true_range"].rolling(14, min_periods=14).mean()
    return history.reset_index(drop=True)


def _history_arrays(history: pd.DataFrame) -> dict[str, NDArray[np.float64]]:
    return {
        column: history[column].to_numpy(dtype=float)
        for column in (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "ema_20",
            "ema_50",
            "ema_200",
            "atr_14",
            "true_range",
        )
    }


def _feature_values(
    arrays: Mapping[str, NDArray[np.float64]],
    index: int,
    onset: ResearchPopulationRecord,
) -> dict[str, FeatureScalar]:
    close = arrays["close"]
    high = arrays["high"]
    low = arrays["low"]
    open_price = arrays["open"]
    volume = arrays["volume"]
    ema20 = arrays["ema_20"]
    ema50 = arrays["ema_50"]
    ema200 = arrays["ema_200"]
    atr14 = arrays["atr_14"]
    true_range = arrays["true_range"]
    current = close[index]
    window20 = slice(max(0, index - 19), index + 1)
    window60 = slice(max(0, index - 59), index + 1)
    prior60 = slice(max(0, index - 60), index)
    c20, c60 = close[window20], close[window60]
    h20, h60 = high[window20], high[window60]
    l20, l60 = low[window20], low[window60]
    v20 = volume[window20]
    returns20 = _returns(c20)
    returns60 = _returns(c60)
    support = float(np.min(low[prior60])) if index > 0 else math.nan
    resistance = float(np.max(high[prior60])) if index > 0 else math.nan
    mean20 = float(np.mean(c20)) if len(c20) >= 20 else math.nan
    std20 = float(np.std(c20, ddof=0)) if len(c20) >= 20 else math.nan
    bandwidth = _ratio(4 * std20, mean20)
    tr20 = true_range[window20]
    prior_tr20 = true_range[max(0, index - 39) : max(0, index - 19)]
    prior_tr60 = true_range[max(0, index - 119) : max(0, index - 59)]
    current_range = high[index] - low[index]
    turnover20 = float(np.mean(c20 * v20)) if len(c20) >= 20 else math.nan
    volume_mean20 = float(np.mean(v20[:-1])) if len(v20) >= 20 else math.nan
    volume_mean5 = (
        float(np.mean(volume[max(0, index - 5) : index])) if index >= 5 else math.nan
    )
    up_mask = returns20 > 0
    down_mask = returns20 < 0
    aligned_volume = v20[1:]
    up_volume = float(np.sum(aligned_volume[up_mask]))
    down_volume = float(np.sum(aligned_volume[down_mask]))
    price_volume_corr = _correlation(returns20, np.diff(v20) / np.maximum(v20[:-1], 1))
    base_duration = _base_duration(high, low, index, support, resistance)
    base_start = max(0, index - max(base_duration - 1, 0))
    base_high = float(np.max(high[base_start : index + 1]))
    base_low = float(np.min(low[base_start : index + 1]))
    base_depth = _ratio(base_high - base_low, base_high)
    contraction20 = _ratio(_mean(tr20), _mean(prior_tr20))
    contraction60 = _ratio(_mean(true_range[window60]), _mean(prior_tr60))
    contraction_count = _contraction_count(high, low, index)
    inputs = dict(onset.point_in_time_inputs)
    values: dict[str, FeatureScalar] = {
        "distance_from_20ema": _distance(current, _at(ema20, index)),
        "distance_from_50ema": _distance(current, _at(ema50, index)),
        "distance_from_200ema": _distance(current, _at(ema200, index)),
        "ema20_slope": _series_slope(ema20, index, 5),
        "ema50_slope": _series_slope(ema50, index, 10),
        "ema200_slope": _series_slope(ema200, index, 20),
        "ema20_above_ema50": _comparison(_at(ema20, index), _at(ema50, index)),
        "ema50_above_ema200": _comparison(_at(ema50, index), _at(ema200, index)),
        "close_position_in_20d_range": _range_position(current, h20, l20, 20),
        "close_position_in_60d_range": _range_position(current, h60, l60, 60),
        "distance_from_20d_high": _distance(
            current, float(np.max(h20)) if len(h20) >= 20 else math.nan
        ),
        "distance_from_60d_high": _distance(
            current, float(np.max(h60)) if len(h60) >= 60 else math.nan
        ),
        "distance_from_support": _distance(current, support),
        "distance_from_resistance": _distance(current, resistance),
        "support_density": _density(l60, support, 0.02, minimum=60),
        "resistance_clearance": _distance(current, resistance),
        "higher_high_count": _positive_differences(h20, minimum=20),
        "higher_low_count": _positive_differences(l20, minimum=20),
        "swing_structure_score": _structure_score(h20, l20),
        "positive_return_days_20d": int(np.sum(returns20 > 0))
        if len(c20) >= 20
        else None,
        "positive_return_days_60d": int(np.sum(returns60 > 0))
        if len(c60) >= 60
        else None,
        "trend_efficiency_20d": _trend_efficiency(c20, minimum=20),
        "trend_efficiency_60d": _trend_efficiency(c60, minimum=60),
        "directional_persistence": _directional_persistence(returns60, minimum=59),
        "price_regression_slope_20d": _normalized_slope(c20, minimum=20),
        "price_regression_slope_60d": _normalized_slope(c60, minimum=60),
        "trend_acceleration": _difference(
            _normalized_slope(c20, minimum=20), _normalized_slope(c60, minimum=60)
        ),
        "days_above_20ema": _days_above(close, ema20, index, 60),
        "days_above_50ema": _days_above(close, ema50, index, 60),
        "days_above_200ema": _days_above(close, ema200, index, 60),
        "relative_volume_5d": _ratio(volume[index], volume_mean5),
        "relative_volume_20d": _ratio(volume[index], volume_mean20),
        "breakout_relative_volume": _optional_float(inputs.get("volume_ratio_20")),
        "volume_slope_20d": _normalized_slope(v20, minimum=20),
        "volume_acceleration": _volume_acceleration(volume, index),
        "up_day_down_day_volume_ratio": _ratio(up_volume, down_volume),
        "price_volume_confirmation": price_volume_corr,
        "turnover_20d": _finite(turnover20),
        "turnover_percentile": None,
        "liquidity_persistence": _liquidity_persistence(close, volume, index),
        "volume_concentration": _ratio(float(np.max(v20)), float(np.sum(v20)))
        if len(v20) >= 20
        else None,
        "accumulation_volume_ratio": _ratio(up_volume, down_volume),
        "atr_percent": _ratio(_at(atr14, index), current),
        "atr_percentile": None,
        "realized_volatility_20d": _realized_volatility(returns20, minimum=19),
        "realized_volatility_60d": _realized_volatility(returns60, minimum=59),
        "volatility_contraction_20d": contraction20,
        "volatility_contraction_60d": contraction60,
        "volatility_expansion": _ratio(
            _at(atr14, index), _mean(atr14[max(0, index - 20) : index])
        ),
        "range_compression": _ratio(current_range, _mean(tr20)),
        "bollinger_bandwidth": _finite_optional(bandwidth),
        "bandwidth_percentile": None,
        "gap_frequency": _gap_frequency(open_price, close, index, 60),
        "base_duration": base_duration,
        "base_depth": _finite_optional(base_depth),
        "base_tightness": None if base_depth is None else 1 - base_depth,
        "base_slope": _normalized_slope(close[base_start : index + 1], minimum=10),
        "contraction_count": contraction_count,
        "contraction_quality": None if contraction20 is None else 1 - contraction20,
        "pivot_distance": _distance(current, resistance),
        "breakout_clearance": _distance(current, resistance),
        "consolidation_efficiency": _consolidation_efficiency(
            close[base_start : index + 1]
        ),
        "pre_breakout_extension": _distance(current, _at(ema20, index)),
        "prospective_stop_distance": float(
            (onset.entry_trigger - onset.prospective_stop) / onset.entry_trigger
        ),
        "prospective_target_distance": float(
            (onset.prospective_target - onset.entry_trigger) / onset.entry_trigger
        ),
        "prospective_reward_risk": float(onset.prospective_rr),
        "entry_extension": _optional_float(inputs.get("extension_pct")),
        "expected_slippage_proxy": _slippage_proxy(
            _ratio(_at(atr14, index), current), turnover20
        ),
        "average_traded_value": _finite(turnover20),
        "position_capacity_proxy": None
        if not math.isfinite(turnover20)
        else turnover20 * 0.01,
        "symbol_history_length": index + 1,
    }
    return values


def _canonical_components(
    ledger_path: Path, rankings_path: Path
) -> dict[tuple[str, date], dict[str, float | None]]:
    rows: dict[tuple[str, date], dict[str, float | None]] = {}
    if rankings_path.exists():
        with rankings_path.open(encoding="utf-8", newline="") as handle:
            for item in csv.DictReader(handle):
                key = (item["symbol"].upper(), date.fromisoformat(item["observed_on"]))
                rows.setdefault(key, {})["canonical_total_score"] = _optional_float(
                    item.get("score")
                )
    if not ledger_path.exists():
        return rows
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    records = payload.get("records", []) if isinstance(payload, dict) else []
    name_map = {
        "price": "price_structure_component",
        "volume": "volume_component",
        "retracement": "retracement_component",
        "candle": "candlestick_component",
    }
    for item in sorted(
        records, key=lambda value: str(value.get("recommendation_id", ""))
    ):
        key = (
            str(item.get("symbol", "")).upper(),
            date.fromisoformat(str(item["evaluation_date"])),
        )
        destination = rows.setdefault(key, {})
        scores = item.get("indicator_scores", {})
        if isinstance(scores, dict):
            for source, target in name_map.items():
                destination[target] = _optional_float(scores.get(source))
        destination["canonical_total_score"] = _optional_float(
            item.get("strategy_score")
        )
    return rows


def _load_history(
    store: LegacyMarketDataStore, symbols: tuple[str, ...]
) -> pd.DataFrame:
    placeholders = ", ".join("?" for _ in symbols)
    return store.connection.execute(
        f"""
        SELECT UPPER(symbol) AS symbol, trade_date, open, high, low, close, volume
        FROM daily_prices
        WHERE UPPER(symbol) IN ({placeholders})
          AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0
          AND high >= GREATEST(open, low, close)
          AND low <= LEAST(open, high, close)
        ORDER BY symbol, trade_date
        """,
        symbols,
    ).fetchdf()


def _base_duration(
    high: np.ndarray[Any, np.dtype[np.float64]],
    low: np.ndarray[Any, np.dtype[np.float64]],
    index: int,
    support: float,
    resistance: float,
) -> int:
    if not math.isfinite(support) or not math.isfinite(resistance):
        return 0
    count = 0
    for position in range(index, max(-1, index - 160), -1):
        if low[position] < support * 0.97 or high[position] > resistance * 1.03:
            break
        count += 1
    return count


def _contraction_count(
    high: np.ndarray[Any, np.dtype[np.float64]],
    low: np.ndarray[Any, np.dtype[np.float64]],
    index: int,
) -> int | None:
    if index < 59:
        return None
    ranges = high[index - 59 : index + 1] - low[index - 59 : index + 1]
    blocks = [float(np.mean(ranges[pos : pos + 10])) for pos in range(0, 60, 10)]
    return sum(later < earlier for earlier, later in zip(blocks, blocks[1:]))


def _volume_acceleration(
    volume: np.ndarray[Any, np.dtype[np.float64]], index: int
) -> float | None:
    if index < 39:
        return None
    recent = _normalized_slope(volume[index - 19 : index + 1], minimum=20)
    prior = _normalized_slope(volume[index - 39 : index - 19], minimum=20)
    return _difference(recent, prior)


def _days_above(
    close: np.ndarray[Any, np.dtype[np.float64]],
    moving_average: np.ndarray[Any, np.dtype[np.float64]],
    index: int,
    window: int,
) -> int | None:
    if index + 1 < window:
        return None
    values = moving_average[index - window + 1 : index + 1]
    if not np.all(np.isfinite(values)):
        return None
    return int(np.sum(close[index - window + 1 : index + 1] > values))


def _gap_frequency(
    open_price: np.ndarray[Any, np.dtype[np.float64]],
    close: np.ndarray[Any, np.dtype[np.float64]],
    index: int,
    window: int,
) -> float | None:
    if index < window:
        return None
    gaps = np.abs(
        open_price[index - window + 1 : index + 1] / close[index - window : index] - 1
    )
    return float(np.mean(gaps >= 0.02))


def _liquidity_persistence(
    close: np.ndarray[Any, np.dtype[np.float64]],
    volume: np.ndarray[Any, np.dtype[np.float64]],
    index: int,
) -> float | None:
    if index < 59:
        return None
    turnover = close[index - 59 : index + 1] * volume[index - 59 : index + 1]
    return float(np.mean(turnover >= 5_000_000))


def _consolidation_efficiency(
    values: np.ndarray[Any, np.dtype[np.float64]],
) -> float | None:
    if len(values) < 10:
        return None
    path = float(np.sum(np.abs(np.diff(values))))
    if path <= 0:
        return None
    displacement = abs(float(values[-1] - values[0]))
    return max(0.0, min(1.0, 1 - displacement / path))


def _slippage_proxy(atr_percent: float | None, turnover: float) -> float | None:
    if atr_percent is None or not math.isfinite(turnover) or turnover <= 0:
        return None
    return atr_percent / math.sqrt(max(turnover / 1_000_000, 1))


def _returns(
    values: np.ndarray[Any, np.dtype[np.float64]],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    if len(values) < 2:
        return np.asarray([], dtype=float)
    return np.diff(values) / values[:-1]


def _trend_efficiency(
    values: np.ndarray[Any, np.dtype[np.float64]], *, minimum: int
) -> float | None:
    if len(values) < minimum:
        return None
    path = float(np.sum(np.abs(np.diff(values))))
    return None if path <= 0 else abs(float(values[-1] - values[0])) / path


def _directional_persistence(
    values: np.ndarray[Any, np.dtype[np.float64]], *, minimum: int
) -> float | None:
    if len(values) < minimum:
        return None
    denominator = float(np.sum(np.abs(values)))
    return None if denominator <= 0 else float(np.sum(values)) / denominator


def _normalized_slope(
    values: np.ndarray[Any, np.dtype[np.float64]], *, minimum: int
) -> float | None:
    finite = values[np.isfinite(values)]
    if len(values) < minimum or len(finite) != len(values):
        return None
    average = float(np.mean(values))
    if average <= 0:
        return None
    slope = float(np.polyfit(np.arange(len(values), dtype=float), values, 1)[0])
    return slope / average


def _series_slope(
    values: np.ndarray[Any, np.dtype[np.float64]], index: int, lag: int
) -> float | None:
    if index < lag:
        return None
    current, previous = values[index], values[index - lag]
    if not math.isfinite(current) or not math.isfinite(previous) or previous == 0:
        return None
    return float((current / previous - 1) / lag)


def _range_position(
    current: float,
    highs: np.ndarray[Any, np.dtype[np.float64]],
    lows: np.ndarray[Any, np.dtype[np.float64]],
    minimum: int,
) -> float | None:
    if len(highs) < minimum:
        return None
    low_value, high_value = float(np.min(lows)), float(np.max(highs))
    return _ratio(current - low_value, high_value - low_value)


def _density(
    values: np.ndarray[Any, np.dtype[np.float64]],
    level: float,
    tolerance: float,
    *,
    minimum: int,
) -> float | None:
    if len(values) < minimum or not math.isfinite(level) or level <= 0:
        return None
    return float(np.mean(np.abs(values / level - 1) <= tolerance))


def _positive_differences(
    values: np.ndarray[Any, np.dtype[np.float64]], *, minimum: int
) -> int | None:
    return None if len(values) < minimum else int(np.sum(np.diff(values) > 0))


def _structure_score(
    highs: np.ndarray[Any, np.dtype[np.float64]],
    lows: np.ndarray[Any, np.dtype[np.float64]],
) -> float | None:
    if len(highs) < 20:
        return None
    return float((np.mean(np.diff(highs) > 0) + np.mean(np.diff(lows) > 0)) / 2)


def _realized_volatility(
    values: np.ndarray[Any, np.dtype[np.float64]], *, minimum: int
) -> float | None:
    return (
        None
        if len(values) < minimum
        else float(np.std(values, ddof=1) * math.sqrt(252))
    )


def _correlation(
    first: np.ndarray[Any, np.dtype[np.float64]],
    second: np.ndarray[Any, np.dtype[np.float64]],
) -> float | None:
    if len(first) < 10 or len(first) != len(second):
        return None
    if np.std(first) == 0 or np.std(second) == 0:
        return None
    return float(np.corrcoef(first, second)[0, 1])


def _comparison(first: float, second: float) -> bool | None:
    if not math.isfinite(first) or not math.isfinite(second):
        return None
    return bool(first > second)


def _distance(value: float, reference: float) -> float | None:
    return _ratio(value - reference, reference)


def _difference(first: float | None, second: float | None) -> float | None:
    return None if first is None or second is None else first - second


def _ratio(numerator: float, denominator: float) -> float | None:
    if (
        not math.isfinite(numerator)
        or not math.isfinite(denominator)
        or denominator == 0
    ):
        return None
    return float(numerator / denominator)


def _mean(values: np.ndarray[Any, np.dtype[np.float64]]) -> float:
    finite = values[np.isfinite(values)]
    return math.nan if finite.size == 0 else float(np.mean(finite))


def _at(values: np.ndarray[Any, np.dtype[np.float64]], index: int) -> float:
    return float(values[index])


def _finite(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def _finite_optional(value: float | None) -> float | None:
    return None if value is None else _finite(value)


def _numeric(value: FeatureScalar) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _optional_float(value: object) -> float | None:
    if value in {None, "", "NONE", "UNAVAILABLE"}:
        return None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _feature_hash(
    item: ResearchPopulationRecord,
    values: tuple[tuple[str, FeatureScalar], ...],
) -> str:
    return _hash_values(item.onset_id, values)


def _hash_values(onset_id: str, values: tuple[tuple[str, FeatureScalar], ...]) -> str:
    payload = json.dumps(
        {"onset_id": onset_id, "values": dict(values)},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _batches(values: tuple[str, ...], size: int) -> Iterable[tuple[str, ...]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


__all__ = [
    "DEFAULT_ACU_RANKINGS",
    "DEFAULT_CANDIDATE_LEDGER",
    "PointInTimeFeatureBuilder",
    "apply_development_transforms",
]
