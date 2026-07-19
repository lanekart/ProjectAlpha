from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pandas as pd

from alpha.candidate_generation_research.models import PointInTimeFeatureSnapshot
from alpha.canonical_universe_audit.store import LegacyMarketDataStore

_REQUIRED_COLUMNS = {
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
}


class PointInTimeFeatureEngine:
    """Build features using only the current and preceding bars."""

    def build(
        self,
        frame: pd.DataFrame,
        *,
        benchmark_returns: pd.Series | None = None,
        near_setup_only: bool = False,
    ) -> tuple[PointInTimeFeatureSnapshot, ...]:
        missing = _REQUIRED_COLUMNS - set(frame.columns)
        if missing:
            raise ValueError(f"feature frame missing columns: {sorted(missing)}")
        if frame.empty:
            return ()
        snapshots: list[PointInTimeFeatureSnapshot] = []
        normalized = frame.copy()
        normalized["symbol"] = normalized["symbol"].astype(str).str.upper()
        normalized["trade_date"] = pd.to_datetime(normalized["trade_date"])
        for _, group in normalized.groupby("symbol", sort=True):
            snapshots.extend(
                self._symbol_snapshots(
                    group.sort_values("trade_date").reset_index(drop=True),
                    benchmark_returns=benchmark_returns,
                    near_setup_only=near_setup_only,
                )
            )
        return tuple(snapshots)

    def detect_store_candidates(
        self,
        *,
        store: LegacyMarketDataStore,
        start: date | None = None,
        end: date | None = None,
        symbol: str | None = None,
        batch_size: int = 150,
    ) -> tuple[PointInTimeFeatureSnapshot, ...]:
        rows: list[PointInTimeFeatureSnapshot] = []
        for batch in self.iter_store_candidate_batches(
            store=store,
            start=start,
            end=end,
            symbol=symbol,
            batch_size=batch_size,
        ):
            rows.extend(batch)
        return tuple(sorted(rows, key=lambda item: (item.symbol, item.sequence)))

    def iter_store_candidate_batches(
        self,
        *,
        store: LegacyMarketDataStore,
        start: date | None = None,
        end: date | None = None,
        symbol: str | None = None,
        batch_size: int = 150,
    ) -> Iterator[tuple[PointInTimeFeatureSnapshot, ...]]:
        symbols = (symbol.strip().upper(),) if symbol else self._symbols(store)
        for symbol_batch in _batches(symbols, batch_size):
            frame = self._history(store, batch=symbol_batch, end=end)
            yield tuple(
                snapshot
                for snapshot in self.build(frame, near_setup_only=True)
                if (start is None or snapshot.observed_on >= start)
                and (end is None or snapshot.observed_on <= end)
            )

    def _symbol_snapshots(
        self,
        frame: pd.DataFrame,
        *,
        benchmark_returns: pd.Series | None,
        near_setup_only: bool,
    ) -> list[PointInTimeFeatureSnapshot]:
        close = frame["close"].astype(float)
        high = frame["high"].astype(float)
        low = frame["low"].astype(float)
        open_price = frame["open"].astype(float)
        volume = frame["volume"].astype(float)
        prior_close = close.shift(1)
        true_range = pd.concat(
            (
                high - low,
                (high - prior_close).abs(),
                (low - prior_close).abs(),
            ),
            axis=1,
        ).max(axis=1)
        resistance = high.shift(1).rolling(20, min_periods=10).max()
        support = low.shift(1).rolling(20, min_periods=10).min()
        ema20 = close.ewm(span=20, adjust=False, min_periods=10).mean()
        ema50 = close.ewm(span=50, adjust=False, min_periods=20).mean()
        atr14 = true_range.rolling(14, min_periods=10).mean()
        average_volume = volume.shift(1).rolling(20, min_periods=10).mean()
        average_turnover = (close * volume).shift(1).rolling(20, min_periods=10).mean()
        candle_range = (high - low).replace(0, float("nan"))
        close_location = (close - low) / candle_range
        range_ratio = (high - low) / close.replace(0, float("nan"))
        recent_range = range_ratio.shift(1).rolling(5, min_periods=3).mean()
        prior_range = range_ratio.shift(6).rolling(15, min_periods=8).mean()
        return20 = close / close.shift(20) - 1
        recent_low = low.shift(1).rolling(10, min_periods=5).min()
        previous_high = high.shift(1)
        previous_ema20 = ema20.shift(1)
        prior_resistance = resistance.shift(1)
        prior_breakout_rows = (prior_close > prior_resistance).fillna(False)
        prior_breakout = (
            prior_breakout_rows.astype(int).rolling(10, min_periods=1).max() > 0
        )
        relative_strength = _relative_strength(
            frame["trade_date"], return20, benchmark_returns
        )
        volume_ratio = volume / average_volume.replace(0, float("nan"))
        base_width = (resistance - support) / support.replace(0, float("nan"))
        indices: Iterable[int] = range(9, len(frame))
        if near_setup_only:
            near_setup = (
                (close >= resistance * 0.98)
                | ((prior_close <= previous_ema20) & (close > ema20))
                | ((ema20 > ema50) & (low <= ema20 * 1.03) & (close >= ema20))
                | ((base_width <= 0.20) & (volume_ratio >= 1.10))
                | prior_breakout
            ).fillna(False)
            indices = tuple(int(index) for index in frame.index[near_setup])
        result: list[PointInTimeFeatureSnapshot] = []
        for index in indices:
            if index < 9:
                continue
            row = frame.iloc[index]
            values = {
                "close": close.iloc[index],
                "resistance_20": resistance.iloc[index],
                "support_20": support.iloc[index],
                "ema_20": ema20.iloc[index],
                "ema_50": ema50.iloc[index],
                "atr_14": atr14.iloc[index],
                "volume_ratio_20": volume_ratio.iloc[index],
                "average_turnover_20": average_turnover.iloc[index],
                "base_width": base_width.iloc[index],
                "recent_range_ratio": recent_range.iloc[index],
                "prior_range_ratio": prior_range.iloc[index],
                "return_20": return20.iloc[index],
                "relative_strength_20": relative_strength.iloc[index],
                "close_location": close_location.iloc[index],
                "recent_low_10": recent_low.iloc[index],
            }
            result.append(
                PointInTimeFeatureSnapshot(
                    symbol=str(row["symbol"]),
                    observed_on=cast(pd.Timestamp, row["trade_date"]).date(),
                    sequence=index,
                    open=_decimal(open_price.iloc[index]) or Decimal("0"),
                    high=_decimal(high.iloc[index]) or Decimal("0"),
                    low=_decimal(low.iloc[index]) or Decimal("0"),
                    close=_decimal(close.iloc[index]) or Decimal("0"),
                    volume=_decimal(volume.iloc[index]) or Decimal("0"),
                    prior_close=_decimal(prior_close.iloc[index]),
                    prior_high=_decimal(previous_high.iloc[index]),
                    resistance_20=_decimal(resistance.iloc[index]),
                    support_20=_decimal(support.iloc[index]),
                    ema_20=_decimal(ema20.iloc[index]),
                    prior_ema_20=_decimal(previous_ema20.iloc[index]),
                    ema_50=_decimal(ema50.iloc[index]),
                    atr_14=_decimal(atr14.iloc[index]),
                    volume_ratio_20=_decimal(values["volume_ratio_20"]),
                    average_turnover_20=_decimal(average_turnover.iloc[index]),
                    base_width=_decimal(values["base_width"]),
                    recent_range_ratio=_decimal(recent_range.iloc[index]),
                    prior_range_ratio=_decimal(prior_range.iloc[index]),
                    return_20=_decimal(return20.iloc[index]),
                    relative_strength_20=_decimal(relative_strength.iloc[index]),
                    close_location=_decimal(close_location.iloc[index]),
                    recent_low_10=_decimal(recent_low.iloc[index]),
                    prior_breakout=bool(prior_breakout.iloc[index]),
                    input_hash=_input_hash(
                        str(row["symbol"]), row["trade_date"], values
                    ),
                )
            )
        return result

    @staticmethod
    def _symbols(store: LegacyMarketDataStore) -> tuple[str, ...]:
        rows = store.connection.execute(
            "SELECT DISTINCT UPPER(symbol) FROM daily_prices ORDER BY 1"
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    @staticmethod
    def _history(
        store: LegacyMarketDataStore,
        *,
        batch: tuple[str, ...],
        end: date | None,
    ) -> pd.DataFrame:
        placeholders = ", ".join("?" for _ in batch)
        end_filter = "" if end is None else "AND trade_date <= ?"
        parameters: tuple[object, ...] = (*batch,) if end is None else (*batch, end)
        return store.connection.execute(
            f"""
            SELECT UPPER(symbol) AS symbol, trade_date, open, high, low, close, volume
            FROM daily_prices
            WHERE UPPER(symbol) IN ({placeholders})
              {end_filter}
              AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0
              AND high >= GREATEST(open, low, close)
              AND low <= LEAST(open, high, close)
            ORDER BY symbol, trade_date
            """,
            parameters,
        ).fetchdf()


def _relative_strength(
    dates: pd.Series,
    returns: pd.Series,
    benchmark_returns: pd.Series | None,
) -> pd.Series:
    if benchmark_returns is None:
        return pd.Series(float("nan"), index=returns.index)
    benchmark = benchmark_returns.copy()
    benchmark.index = pd.to_datetime(benchmark.index)
    aligned = pd.Series(pd.to_datetime(dates)).map(benchmark)
    return returns - aligned


def _input_hash(symbol: str, observed_on: object, values: dict[str, float]) -> str:
    payload = "|".join(
        (
            symbol.upper(),
            str(observed_on),
            *(f"{key}={values[key]}" for key in sorted(values)),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    return Decimal(str(value))


def _batches(values: tuple[str, ...], size: int) -> Iterator[tuple[str, ...]]:
    if size < 1:
        raise ValueError("feature batch size must be positive")
    for index in range(0, len(values), size):
        yield values[index : index + size]


__all__ = ["PointInTimeFeatureEngine"]
