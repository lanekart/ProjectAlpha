from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from alpha.canonical_universe_audit.models import DatasetManifest
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine

_REPLAY_SERIES = frozenset({"EQ"})


class HistoricalTruthReplayStore(LegacyMarketDataStore):
    """Read verified immutable candle snapshots through the replay store contract."""

    def __init__(
        self,
        *,
        database_path: Path | str,
        snapshot_root: Path | str,
        start: date | None = None,
        end: date | None = None,
        exchange: str = "nse",
    ) -> None:
        self.path = Path(database_path)
        self.snapshot_root = Path(snapshot_root)
        self.exchange = exchange.strip().lower()
        if not self.path.is_file():
            raise FileNotFoundError(
                f"historical truth database not found: {self.path}"
            )
        if not self.snapshot_root.is_dir():
            raise FileNotFoundError(
                f"historical truth snapshot root not found: {self.snapshot_root}"
            )
        if start is not None and end is not None and end < start:
            raise ValueError("replay end date must be on or after start date")
        self.connection = duckdb.connect(":memory:")
        try:
            self._initialise_view(start=start, end=end)
        except Exception:
            self.connection.close()
            raise

    def manifest(self) -> DatasetManifest:
        row = self.connection.execute(
            """
            SELECT
                COUNT(*),
                COUNT(DISTINCT symbol),
                COUNT(DISTINCT trade_date),
                MIN(trade_date),
                MAX(trade_date),
                COUNT(sector),
                STRING_AGG(DISTINCT exchange, ', ' ORDER BY exchange)
            FROM daily_prices
            """
        ).fetchone()
        if row is None or row[3] is None or row[4] is None:
            raise ValueError("historical truth replay population is empty")
        return DatasetManifest(
            dataset_version="HISTORICAL_TRUTH_SNAPSHOT_V1",
            first_session=row[3],
            last_session=row[4],
            sessions=int(row[2]),
            rows=int(row[0]),
            symbols=int(row[1]),
            exchange=str(row[6]),
            sector_rows=int(row[5]),
        )

    def _initialise_view(
        self,
        *,
        start: date | None,
        end: date | None,
    ) -> None:
        self.connection.execute(
            """
            CREATE TABLE daily_prices (
                symbol VARCHAR NOT NULL,
                trade_date DATE NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume BIGINT NOT NULL,
                sector VARCHAR,
                exchange VARCHAR NOT NULL,
                PRIMARY KEY (symbol, trade_date)
            )
            """
        )
        source_dates = self._source_dates(start=start, end=end)
        if not source_dates:
            raise ValueError("historical truth warehouse has no candles in replay window")
        warehouse = CanonicalPointInTimeWarehouse(self.path)
        snapshots = PointInTimeSnapshotEngine(warehouse, self.snapshot_root)
        rows: list[tuple[object, ...]] = []
        for trading_date in source_dates:
            path = snapshots.path_for(trading_date, exchange=self.exchange)
            if not path.is_file():
                raise ValueError(
                    "historical truth replay blocked: immutable snapshot missing for "
                    f"{trading_date.isoformat()}"
                )
            snapshot = snapshots.load(trading_date, exchange=self.exchange)
            verification = snapshots.verify(snapshot)
            if not verification.valid:
                raise ValueError(
                    "historical truth replay blocked: snapshot checksum mismatch for "
                    f"{trading_date.isoformat()}"
                )
            if (
                snapshot.metadata.trading_date != trading_date
                or snapshot.metadata.exchange.lower() != self.exchange
                or not snapshot.metadata.availability.candles
            ):
                raise ValueError(
                    "historical truth replay blocked: snapshot metadata mismatch for "
                    f"{trading_date.isoformat()}"
                )
            selected = tuple(
                candle
                for candle in snapshot.candles
                if candle.exchange.lower() == self.exchange
                and candle.series.upper() in _REPLAY_SERIES
            )
            if not selected:
                raise ValueError(
                    "historical truth replay blocked: no EQ candles for "
                    f"{trading_date.isoformat()}"
                )
            for candle in selected:
                self._validate_candle(candle)
                rows.append(
                    (
                        candle.symbol.strip().upper(),
                        candle.trading_date,
                        candle.open_price,
                        candle.high_price,
                        candle.low_price,
                        candle.close_price,
                        candle.volume,
                        None,
                        candle.exchange.upper(),
                    )
                )
        try:
            self.connection.executemany(
                "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        except duckdb.ConstraintException as exc:
            raise ValueError(
                "historical truth replay blocked: duplicate EQ symbol/date"
            ) from exc

    def _source_dates(
        self,
        *,
        start: date | None,
        end: date | None,
    ) -> tuple[date, ...]:
        first = start or date.min
        last = end or date.max
        connection = duckdb.connect(str(self.path), read_only=True)
        try:
            rows = connection.execute(
                """
                SELECT DISTINCT trading_date
                FROM daily_candle
                WHERE exchange = ? AND trading_date BETWEEN ? AND ?
                ORDER BY trading_date
                """,
                (self.exchange, first, last),
            ).fetchall()
        except duckdb.CatalogException as exc:
            raise ValueError(
                "historical truth database is missing daily_candle"
            ) from exc
        finally:
            connection.close()
        return tuple(row[0] for row in rows)

    @staticmethod
    def _validate_candle(candle: object) -> None:
        open_price = float(getattr(candle, "open_price"))
        high_price = float(getattr(candle, "high_price"))
        low_price = float(getattr(candle, "low_price"))
        close_price = float(getattr(candle, "close_price"))
        volume = int(getattr(candle, "volume"))
        if min(open_price, high_price, low_price, close_price) <= 0:
            raise ValueError("historical truth replay blocked: non-positive price")
        if high_price < max(open_price, low_price, close_price):
            raise ValueError("historical truth replay blocked: invalid candle high")
        if low_price > min(open_price, high_price, close_price):
            raise ValueError("historical truth replay blocked: invalid candle low")
        if volume < 0:
            raise ValueError("historical truth replay blocked: negative volume")


__all__ = ["HistoricalTruthReplayStore"]
