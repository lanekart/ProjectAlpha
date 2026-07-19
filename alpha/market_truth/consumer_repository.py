from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from alpha.config import settings
from alpha.market_truth.historical_service import market_bars
from alpha.market_truth.market_truth_engine import MarketTruthEngine

_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "sector",
    "exchange",
)


@dataclass(frozen=True, slots=True)
class LocalMarketInventory:
    global_start: date | None
    global_end: date | None
    global_sessions: int
    symbol_ranges: dict[str, tuple[date, date, int]]


class MarketTruthPriceRepository:
    """DataFrame compatibility adapter for consumers migrating to MTE."""

    def __init__(
        self,
        engine: MarketTruthEngine | None = None,
        *,
        database_path: Path | str | None = None,
    ) -> None:
        self.database_path = Path(database_path or settings.database_path)
        self.engine = engine or MarketTruthEngine.default(
            database_path=self.database_path
        )

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return self.find_range_by_symbols(
            symbols=(), start_date=trade_date, end_date=trade_date
        )

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        if limit <= 0:
            raise ValueError("history limit must be positive")
        start = end_date - timedelta(days=max(limit * 3, 30))
        frame = self.find_range_by_symbols(
            symbols=symbols,
            start_date=start,
            end_date=end_date,
        )
        if frame.empty:
            return frame
        return (
            frame.sort_values(["symbol", "trade_date"])
            .groupby("symbol", group_keys=False)
            .tail(limit)
            .reset_index(drop=True)
        )

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        truth = self.engine.historical.daily(
            symbols=symbols,
            start=start_date,
            end=end_date,
            as_of=end_date,
        )
        if not truth.actionable:
            return pd.DataFrame(columns=_COLUMNS)
        rows = [
            {
                "symbol": item.symbol,
                "trade_date": item.observed_at.date(),
                "open": float(item.open_price),
                "high": float(item.high_price),
                "low": float(item.low_price),
                "close": float(item.close_price),
                "volume": float(item.volume),
                "sector": None,
                "exchange": item.exchange or "UNKNOWN",
            }
            for item in market_bars(truth)
        ]
        return pd.DataFrame(rows, columns=_COLUMNS)

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        frame = self.find_range_by_symbols(symbols=(), start_date=start, end_date=end)
        if frame.empty:
            return ()
        return tuple(sorted(set(frame["trade_date"])))

    def inventory(self) -> LocalMarketInventory:
        """Return inventory metadata through an MTE-owned local-store adapter."""

        if not self.database_path.exists():
            return LocalMarketInventory(None, None, 0, {})
        database = duckdb.connect(str(self.database_path), read_only=True)
        try:
            global_row = database.execute(
                "SELECT MIN(trade_date), MAX(trade_date), "
                "COUNT(DISTINCT trade_date) FROM daily_prices"
            ).fetchone()
            rows = database.execute(
                "SELECT UPPER(symbol), MIN(trade_date), MAX(trade_date), COUNT(*) "
                "FROM daily_prices GROUP BY UPPER(symbol) ORDER BY UPPER(symbol)"
            ).fetchall()
        finally:
            database.close()
        return LocalMarketInventory(
            global_start=global_row[0] if global_row else None,
            global_end=global_row[1] if global_row else None,
            global_sessions=int(global_row[2] or 0) if global_row else 0,
            symbol_ranges={
                str(symbol): (first, last, int(count))
                for symbol, first, last, count in rows
                if first is not None and last is not None
            },
        )

    def close(self) -> None:
        return None


__all__ = ["LocalMarketInventory", "MarketTruthPriceRepository"]
