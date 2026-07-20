from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import duckdb

_REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "SYMBOL",
    "SERIES",
    "OPEN",
    "HIGH",
    "LOW",
    "CLOSE",
    "TOTTRDQTY",
)


@dataclass(frozen=True, slots=True)
class CanonicalCandle:
    trading_date: date
    exchange: str
    symbol: str
    series: str
    isin: str | None
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    trading_date: date
    exchange: str
    candles: tuple[CanonicalCandle, ...]
    symbol_count: int
    total_volume: int


@dataclass(frozen=True, slots=True)
class CompletenessReport:
    start_date: date
    end_date: date
    observed_dates: tuple[date, ...]
    missing_weekdays: tuple[date, ...]
    coverage_ratio: float


class CanonicalPointInTimeWarehouse:
    """DuckDB-backed canonical market warehouse with point-in-time reads."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialise(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS security_identity (
                    exchange VARCHAR NOT NULL,
                    symbol VARCHAR NOT NULL,
                    series VARCHAR NOT NULL,
                    isin VARCHAR,
                    valid_from DATE NOT NULL,
                    valid_to DATE,
                    PRIMARY KEY (exchange, symbol, series, valid_from)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_candle (
                    trading_date DATE NOT NULL,
                    exchange VARCHAR NOT NULL,
                    symbol VARCHAR NOT NULL,
                    series VARCHAR NOT NULL,
                    isin VARCHAR,
                    open_price DOUBLE NOT NULL,
                    high_price DOUBLE NOT NULL,
                    low_price DOUBLE NOT NULL,
                    close_price DOUBLE NOT NULL,
                    volume BIGINT NOT NULL,
                    source_sha256 VARCHAR,
                    PRIMARY KEY (trading_date, exchange, symbol, series)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS corporate_action (
                    exchange VARCHAR NOT NULL,
                    isin VARCHAR,
                    symbol VARCHAR NOT NULL,
                    action_type VARCHAR NOT NULL,
                    ex_date DATE NOT NULL,
                    ratio_numerator DOUBLE,
                    ratio_denominator DOUBLE,
                    source_sha256 VARCHAR,
                    PRIMARY KEY (
                        exchange,
                        symbol,
                        action_type,
                        ex_date
                    )
                )
                """
            )

    def ingest_bhavcopy_csv(
        self,
        csv_path: Path,
        *,
        trading_date: date,
        exchange: str = "nse",
        source_sha256: str | None = None,
    ) -> int:
        rows = self._read_bhavcopy(csv_path, trading_date, exchange)
        self.initialise()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO daily_candle VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    (
                        row.trading_date,
                        row.exchange,
                        row.symbol,
                        row.series,
                        row.isin,
                        row.open_price,
                        row.high_price,
                        row.low_price,
                        row.close_price,
                        row.volume,
                        source_sha256,
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def snapshot(
        self,
        trading_date: date,
        *,
        exchange: str = "nse",
    ) -> MarketSnapshot:
        self.initialise()
        with self._connect() as connection:
            result = connection.execute(
                """
                SELECT trading_date, exchange, symbol, series, isin,
                       open_price, high_price, low_price, close_price, volume
                FROM daily_candle
                WHERE trading_date = ? AND exchange = ?
                ORDER BY symbol, series
                """,
                [trading_date, exchange.lower()],
            ).fetchall()
        candles = tuple(
            CanonicalCandle(
                trading_date=row[0],
                exchange=str(row[1]),
                symbol=str(row[2]),
                series=str(row[3]),
                isin=str(row[4]) if row[4] is not None else None,
                open_price=float(row[5]),
                high_price=float(row[6]),
                low_price=float(row[7]),
                close_price=float(row[8]),
                volume=int(row[9]),
            )
            for row in result
        )
        return MarketSnapshot(
            trading_date=trading_date,
            exchange=exchange.lower(),
            candles=candles,
            symbol_count=len(candles),
            total_volume=sum(candle.volume for candle in candles),
        )

    def completeness(
        self,
        start_date: date,
        end_date: date,
        *,
        exchange: str = "nse",
    ) -> CompletenessReport:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        self.initialise()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT trading_date
                FROM daily_candle
                WHERE exchange = ? AND trading_date BETWEEN ? AND ?
                ORDER BY trading_date
                """,
                [exchange.lower(), start_date, end_date],
            ).fetchall()
        observed = tuple(row[0] for row in rows)
        observed_set = set(observed)
        expected = tuple(
            candidate
            for candidate in self._date_range(start_date, end_date)
            if candidate.weekday() < 5
        )
        missing = tuple(
            candidate for candidate in expected if candidate not in observed_set
        )
        coverage = len(observed) / len(expected) if expected else 1.0
        return CompletenessReport(
            start_date=start_date,
            end_date=end_date,
            observed_dates=observed,
            missing_weekdays=missing,
            coverage_ratio=coverage,
        )

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.database_path))

    @staticmethod
    def _date_range(start_date: date, end_date: date) -> tuple[date, ...]:
        days = (end_date - start_date).days
        return tuple(
            date.fromordinal(start_date.toordinal() + offset)
            for offset in range(days + 1)
        )

    @staticmethod
    def _read_bhavcopy(
        csv_path: Path,
        trading_date: date,
        exchange: str,
    ) -> tuple[CanonicalCandle, ...]:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = tuple(reader.fieldnames or ())
            missing = [
                column for column in _REQUIRED_COLUMNS if column not in columns
            ]
            if missing:
                raise ValueError(
                    f"missing required columns: {', '.join(missing)}"
                )
            rows: list[CanonicalCandle] = []
            for raw in reader:
                rows.append(
                    CanonicalCandle(
                        trading_date=trading_date,
                        exchange=exchange.lower(),
                        symbol=raw["SYMBOL"].strip(),
                        series=raw["SERIES"].strip(),
                        isin=(raw.get("ISIN") or "").strip() or None,
                        open_price=float(raw["OPEN"]),
                        high_price=float(raw["HIGH"]),
                        low_price=float(raw["LOW"]),
                        close_price=float(raw["CLOSE"]),
                        volume=int(float(raw["TOTTRDQTY"])),
                    )
                )
        return tuple(rows)
