from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import duckdb

from alpha.historical_truth.models import ValidationIssue

_LEGACY_REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "SYMBOL",
    "SERIES",
    "OPEN",
    "HIGH",
    "LOW",
    "CLOSE",
    "TOTTRDQTY",
)
_UDIFF_REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "TckrSymb",
    "SctySrs",
    "OpnPric",
    "HghPric",
    "LwPric",
    "ClsPric",
    "TtlTradgVol",
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


@dataclass(frozen=True, slots=True)
class CanonicalIngestionResult:
    parsed_rows: int
    inserted_rows: int
    reused_rows: int
    lineage_rows: int
    identity_resolved_rows: int


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
                CREATE TABLE IF NOT EXISTS validation_quarantine (
                    trading_date DATE NOT NULL,
                    exchange VARCHAR NOT NULL,
                    code VARCHAR NOT NULL,
                    severity VARCHAR NOT NULL,
                    row_number BIGINT NOT NULL,
                    message VARCHAR NOT NULL,
                    source_sha256 VARCHAR,
                    PRIMARY KEY (
                        trading_date,
                        exchange,
                        code,
                        row_number,
                        message
                    )
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS candle_ingestion_lineage (
                    trading_date DATE NOT NULL,
                    exchange VARCHAR NOT NULL,
                    symbol VARCHAR NOT NULL,
                    series VARCHAR NOT NULL,
                    source_sha256 VARCHAR NOT NULL,
                    source_url VARCHAR NOT NULL,
                    archive_path VARCHAR NOT NULL,
                    normalized_path VARCHAR NOT NULL,
                    PRIMARY KEY (
                        trading_date,
                        exchange,
                        symbol,
                        series,
                        source_sha256
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

    def ingest_bhavcopy_csv_fail_closed(
        self,
        csv_path: Path,
        *,
        trading_date: date,
        source_sha256: str,
        source_url: str,
        archive_path: str,
        normalized_path: str,
        exchange: str = "nse",
    ) -> CanonicalIngestionResult:
        """Insert new evidence or reuse identical rows without overwriting data."""

        if not source_sha256:
            raise ValueError("source_sha256 is required for governed ingestion")
        rows = self._read_bhavcopy(csv_path, trading_date, exchange)
        keys = tuple((row.symbol, row.series) for row in rows)
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate symbol/series rows cannot be ingested")

        self.initialise()
        exchange_key = exchange.lower()
        with self._connect() as connection:
            existing_rows = connection.execute(
                """
                SELECT trading_date, exchange, symbol, series, isin,
                       open_price, high_price, low_price, close_price, volume
                FROM daily_candle
                WHERE trading_date = ? AND exchange = ?
                """,
                [trading_date, exchange_key],
            ).fetchall()
            existing = {
                (str(item[2]), str(item[3])): CanonicalCandle(
                    trading_date=item[0],
                    exchange=str(item[1]),
                    symbol=str(item[2]),
                    series=str(item[3]),
                    isin=str(item[4]) if item[4] is not None else None,
                    open_price=float(item[5]),
                    high_price=float(item[6]),
                    low_price=float(item[7]),
                    close_price=float(item[8]),
                    volume=int(item[9]),
                )
                for item in existing_rows
            }
            conflicts = tuple(
                row
                for row in rows
                if (current := existing.get((row.symbol, row.series))) is not None
                and not self._same_candle(current, row)
            )
            if conflicts:
                names = ", ".join(f"{row.symbol}/{row.series}" for row in conflicts[:5])
                raise ValueError(
                    "canonical candle conflict; existing rows were not changed: "
                    f"{names}"
                )

            self._validate_identity_compatibility(
                connection,
                rows,
                trading_date=trading_date,
                exchange=exchange_key,
            )
            new_rows = tuple(
                row for row in rows if (row.symbol, row.series) not in existing
            )
            connection.execute("BEGIN TRANSACTION")
            try:
                if new_rows:
                    connection.executemany(
                        """
                        INSERT INTO daily_candle VALUES (
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
                            for row in new_rows
                        ],
                    )
                before_result = connection.execute(
                    "SELECT count(*) FROM candle_ingestion_lineage"
                ).fetchone()
                if before_result is None:
                    raise RuntimeError("lineage count query returned no result")
                before = int(before_result[0])
                connection.executemany(
                    """
                    INSERT INTO candle_ingestion_lineage VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?
                    ) ON CONFLICT DO NOTHING
                    """,
                    [
                        (
                            row.trading_date,
                            row.exchange,
                            row.symbol,
                            row.series,
                            source_sha256,
                            source_url,
                            archive_path,
                            normalized_path,
                        )
                        for row in rows
                    ],
                )
                after_result = connection.execute(
                    "SELECT count(*) FROM candle_ingestion_lineage"
                ).fetchone()
                if after_result is None:
                    raise RuntimeError("lineage count query returned no result")
                after = int(after_result[0])
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

        return CanonicalIngestionResult(
            parsed_rows=len(rows),
            inserted_rows=len(new_rows),
            reused_rows=len(rows) - len(new_rows),
            lineage_rows=after - before,
            identity_resolved_rows=len(rows),
        )

    def record_validation_issues(
        self,
        trading_date: date,
        issues: tuple[ValidationIssue, ...],
        *,
        exchange: str = "nse",
        source_sha256: str | None = None,
    ) -> int:
        """Persist exact source-validation evidence without changing source rows."""

        if not issues:
            return 0
        self.initialise()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO validation_quarantine VALUES (
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    (
                        trading_date,
                        exchange.lower(),
                        issue.code,
                        issue.severity.value,
                        issue.row_number if issue.row_number is not None else -1,
                        issue.message,
                        source_sha256,
                    )
                    for issue in issues
                ],
            )
        return len(issues)

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
    def _same_candle(existing: CanonicalCandle, incoming: CanonicalCandle) -> bool:
        isin_matches = (
            existing.isin is None
            or incoming.isin is None
            or existing.isin == incoming.isin
        )
        return isin_matches and (
            existing.open_price,
            existing.high_price,
            existing.low_price,
            existing.close_price,
            existing.volume,
        ) == (
            incoming.open_price,
            incoming.high_price,
            incoming.low_price,
            incoming.close_price,
            incoming.volume,
        )

    @staticmethod
    def _validate_identity_compatibility(
        connection: duckdb.DuckDBPyConnection,
        rows: tuple[CanonicalCandle, ...],
        *,
        trading_date: date,
        exchange: str,
    ) -> None:
        identities = connection.execute(
            """
            SELECT symbol, series, isin
            FROM security_identity
            WHERE exchange = ?
              AND valid_from <= ?
              AND (valid_to IS NULL OR valid_to >= ?)
            """,
            [exchange, trading_date, trading_date],
        ).fetchall()
        by_key: dict[tuple[str, str], set[str]] = {}
        for symbol, series, isin in identities:
            if isin is not None:
                by_key.setdefault((str(symbol), str(series)), set()).add(str(isin))
        for row in rows:
            known = by_key.get((row.symbol, row.series), set())
            isin_conflict = (
                row.isin is not None and bool(known) and row.isin not in known
            )
            if len(known) > 1 or isin_conflict:
                raise ValueError(
                    f"security identity conflict for {row.symbol}/{row.series}"
                )

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
            fields = CanonicalPointInTimeWarehouse._schema_fields(columns)
            rows: list[CanonicalCandle] = []
            for raw in reader:
                rows.append(
                    CanonicalCandle(
                        trading_date=trading_date,
                        exchange=exchange.lower(),
                        symbol=raw[fields["symbol"]].strip(),
                        series=raw[fields["series"]].strip(),
                        isin=(raw.get(fields["isin"]) or "").strip() or None,
                        open_price=float(raw[fields["open"]]),
                        high_price=float(raw[fields["high"]]),
                        low_price=float(raw[fields["low"]]),
                        close_price=float(raw[fields["close"]]),
                        volume=int(float(raw[fields["volume"]])),
                    )
                )
        return tuple(rows)

    @staticmethod
    def _schema_fields(columns: tuple[str, ...]) -> dict[str, str]:
        column_set = set(columns)
        if set(_LEGACY_REQUIRED_COLUMNS) <= column_set:
            return {
                "symbol": "SYMBOL",
                "series": "SERIES",
                "isin": "ISIN",
                "open": "OPEN",
                "high": "HIGH",
                "low": "LOW",
                "close": "CLOSE",
                "volume": "TOTTRDQTY",
            }
        if set(_UDIFF_REQUIRED_COLUMNS) <= column_set:
            return {
                "symbol": "TckrSymb",
                "series": "SctySrs",
                "isin": "ISIN",
                "open": "OpnPric",
                "high": "HghPric",
                "low": "LwPric",
                "close": "ClsPric",
                "volume": "TtlTradgVol",
            }
        missing_legacy = [
            column for column in _LEGACY_REQUIRED_COLUMNS if column not in column_set
        ]
        missing_udiff = [
            column for column in _UDIFF_REQUIRED_COLUMNS if column not in column_set
        ]
        raise ValueError(
            "unsupported bhavcopy schema; missing legacy columns: "
            f"{', '.join(missing_legacy)}; missing UDiFF columns: "
            f"{', '.join(missing_udiff)}"
        )
