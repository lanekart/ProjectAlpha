"""Deterministic paired warehouse sample construction for WDA."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from alpha.warehouse_delta_audit.models import (
    MANDATORY_SYMBOLS,
    SampleProfile,
    WarehouseDeltaRequest,
)


@dataclass(slots=True)
class PreparedWarehouseSample:
    profile: SampleProfile
    legacy_sample: Path
    comparison_sample: Path
    legacy_replay_sample: Path
    comparison_replay_sample: Path
    comparison_files: tuple[Path, ...]
    _temporary_root: Path

    def close(self) -> None:
        shutil.rmtree(self._temporary_root, ignore_errors=True)

    def __enter__(self) -> PreparedWarehouseSample:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class WarehouseSampleBuilder:
    """Create isolated legacy and comparison DuckDBs for identical replay."""

    def prepare(self, request: WarehouseDeltaRequest) -> PreparedWarehouseSample:
        legacy = Path(request.legacy_database)
        source = Path(request.comparison_source)
        if not legacy.exists():
            raise FileNotFoundError(f"legacy warehouse not found: {legacy}")
        files = _comparison_files(source)
        if not files:
            raise FileNotFoundError(
                f"comparison source contains no CSV files: {source}"
            )
        with duckdb.connect(str(legacy), read_only=True) as connection:
            start, end = _comparison_dates(connection, request)
        equity_symbols = _eligible_equity_symbols(files, start=start, end=end)
        if not equity_symbols:
            raise ValueError("comparison source contains no NSE EQ-series equities")
        with duckdb.connect(str(legacy), read_only=True) as connection:
            universe = _eligible_universe(
                connection,
                start=start,
                end=end,
                equity_symbols=equity_symbols,
            )
            selected, strata = _select_symbols(universe, request.sample_size)
            session_row = connection.execute(
                """
                SELECT COUNT(DISTINCT trade_date)
                FROM daily_prices
                WHERE trade_date BETWEEN ? AND ?
                """,
                (start, end),
            ).fetchone()
            if session_row is None:
                raise ValueError("legacy warehouse session count unavailable")
            sessions = int(session_row[0])
        selected_set = set(selected)
        mandatory_present = tuple(
            symbol for symbol in MANDATORY_SYMBOLS if symbol in selected_set
        )
        mandatory_missing = tuple(
            symbol for symbol in MANDATORY_SYMBOLS if symbol not in selected_set
        )
        profile = SampleProfile(
            requested_symbols=request.sample_size,
            selected_symbols=selected,
            mandatory_symbols_present=mandatory_present,
            mandatory_symbols_missing=mandatory_missing,
            start=start,
            end=end,
            sessions=sessions,
            source_files=len(files),
            liquidity_high=strata["HIGH"],
            liquidity_medium=strata["MEDIUM"],
            liquidity_low=strata["LOW"],
            sector_coverage="UNKNOWN: legacy warehouse has no historical sectors",
            market_cap_coverage=(
                "UNAVAILABLE: NSE EQ-series plus INE ISIN filter used; liquidity "
                "strata are not market-cap labels"
            ),
        )
        temporary = Path(tempfile.mkdtemp(prefix="alpha-wda-"))
        legacy_sample = temporary / "legacy_sample.duckdb"
        comparison_sample = temporary / "comparison_sample.duckdb"
        legacy_replay_sample = temporary / "legacy_replay.duckdb"
        comparison_replay_sample = temporary / "comparison_replay.duckdb"
        try:
            _materialize_legacy(
                source=legacy,
                destination=legacy_sample,
                symbols=selected,
                start=start,
                end=end,
            )
            _materialize_comparison(
                files=files,
                destination=comparison_sample,
                symbols=selected,
                start=start,
                end=end,
            )
            common_start, common_end, common_sessions = _materialize_common_replay(
                legacy_sample=legacy_sample,
                comparison_sample=comparison_sample,
                legacy_replay=legacy_replay_sample,
                comparison_replay=comparison_replay_sample,
            )
            profile = replace(
                profile,
                start=common_start,
                end=common_end,
                sessions=common_sessions,
            )
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return PreparedWarehouseSample(
            profile=profile,
            legacy_sample=legacy_sample,
            comparison_sample=comparison_sample,
            legacy_replay_sample=legacy_replay_sample,
            comparison_replay_sample=comparison_replay_sample,
            comparison_files=files,
            _temporary_root=temporary,
        )


def _comparison_files(source: Path) -> tuple[Path, ...]:
    if source.is_file() and source.suffix.lower() == ".csv":
        return (source.resolve(),)
    if not source.is_dir():
        return ()
    return tuple(
        sorted(path.resolve() for path in source.rglob("*.csv") if path.is_file())
    )


def _comparison_dates(
    connection: duckdb.DuckDBPyConnection,
    request: WarehouseDeltaRequest,
) -> tuple[date, date]:
    row = connection.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM daily_prices"
    ).fetchone()
    if row is None or row[0] is None or row[1] is None:
        raise ValueError("legacy warehouse contains no daily prices")
    start = request.start or row[0]
    end = request.end or row[1]
    if end < start:
        raise ValueError("comparison range is empty")
    return start, end


def _eligible_universe(
    connection: duckdb.DuckDBPyConnection,
    *,
    start: date,
    end: date,
    equity_symbols: tuple[str, ...],
) -> tuple[tuple[str, float, int], ...]:
    _register_symbols(connection, equity_symbols)
    rows = connection.execute(
        """
        SELECT
            UPPER(TRIM(prices.symbol)) AS symbol,
            AVG(CAST(prices.close AS DOUBLE) *
                CAST(prices.volume AS DOUBLE)) AS turnover,
            COUNT(*) AS observations
        FROM daily_prices AS prices
        JOIN _selected_symbols AS equities
          ON UPPER(TRIM(prices.symbol)) = equities.symbol
        WHERE prices.trade_date BETWEEN ? AND ?
          AND prices.close > 0
          AND prices.volume >= 0
        GROUP BY UPPER(TRIM(prices.symbol))
        HAVING COUNT(*) >= 200
        ORDER BY turnover, symbol
        """,
        (start, end),
    ).fetchall()
    connection.unregister("_selected_symbols")
    return tuple(
        (str(symbol), float(turnover or 0), int(count))
        for symbol, turnover, count in rows
    )


def _eligible_equity_symbols(
    files: tuple[Path, ...],
    *,
    start: date,
    end: date,
) -> tuple[str, ...]:
    source_expression = _duckdb_file_list(files)
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TEMP VIEW _raw_source AS SELECT * FROM "
            f"read_csv_auto({source_expression}, union_by_name=true, "
            "all_varchar=true, filename=true, ignore_errors=true)"
        )
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info('_raw_source')").fetchall()
        }
        symbol = _coalesce(columns, ("TckrSymb", "SYMBOL"), "VARCHAR")
        series = _coalesce(columns, ("SctySrs", "SERIES"), "VARCHAR")
        observed_on = _date_expression(columns)
        isin = _coalesce(columns, ("ISIN",), "VARCHAR")
        rows = connection.execute(
            f"""
            SELECT DISTINCT UPPER(TRIM({symbol})) AS symbol
            FROM _raw_source AS raw
            WHERE UPPER(TRIM({series})) = 'EQ'
              AND UPPER(TRIM({isin})) LIKE 'INE%'
              AND {observed_on} BETWEEN ? AND ?
            ORDER BY symbol
            """,
            (start, end),
        ).fetchall()
    return tuple(str(row[0]) for row in rows if str(row[0]).strip())


def _select_symbols(
    universe: tuple[tuple[str, float, int], ...],
    sample_size: int,
) -> tuple[tuple[str, ...], dict[str, int]]:
    if len(universe) < len(MANDATORY_SYMBOLS):
        raise ValueError("eligible universe is too small for mandatory sample")
    symbols = tuple(row[0] for row in universe)
    available = set(symbols)
    selected = [symbol for symbol in MANDATORY_SYMBOLS if symbol in available]
    remaining = max(0, min(sample_size, len(symbols)) - len(selected))
    groups = _liquidity_groups(universe)
    per_group = remaining // 3
    extra = remaining % 3
    counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for index, label in enumerate(("HIGH", "MEDIUM", "LOW")):
        quota = per_group + (1 if index < extra else 0)
        choices = sorted(
            (symbol for symbol in groups[label] if symbol not in selected),
            key=lambda symbol: (_stable_order(symbol), symbol),
        )
        taken = choices[:quota]
        selected.extend(taken)
        counts[label] += len(taken)
    if len(selected) < min(sample_size, len(symbols)):
        choices = sorted(
            (symbol for symbol in symbols if symbol not in selected),
            key=lambda symbol: (_stable_order(symbol), symbol),
        )
        selected.extend(choices[: min(sample_size, len(symbols)) - len(selected)])
    labels = {symbol: label for label, values in groups.items() for symbol in values}
    counts = {
        label: sum(labels.get(symbol) == label for symbol in selected)
        for label in counts
    }
    return tuple(sorted(selected)), counts


def _liquidity_groups(
    universe: tuple[tuple[str, float, int], ...],
) -> dict[str, tuple[str, ...]]:
    size = len(universe)
    first = size // 3
    second = (size * 2) // 3
    return {
        "LOW": tuple(row[0] for row in universe[:first]),
        "MEDIUM": tuple(row[0] for row in universe[first:second]),
        "HIGH": tuple(row[0] for row in universe[second:]),
    }


def _stable_order(symbol: str) -> str:
    return hashlib.sha256(f"WDA_v1.0:{symbol}".encode()).hexdigest()


def _materialize_legacy(
    *,
    source: Path,
    destination: Path,
    symbols: tuple[str, ...],
    start: date,
    end: date,
) -> None:
    with duckdb.connect(str(destination)) as connection:
        connection.execute(f"ATTACH {_sql_path(source)} AS legacy (READ_ONLY)")
        _register_symbols(connection, symbols)
        connection.execute(
            """
            CREATE TABLE daily_prices AS
            SELECT
                UPPER(TRIM(prices.symbol)) AS symbol,
                prices.trade_date,
                prices.open,
                prices.high,
                prices.low,
                prices.close,
                prices.volume,
                prices.sector,
                prices.exchange
            FROM legacy.daily_prices AS prices
            JOIN _selected_symbols AS selected
              ON UPPER(TRIM(prices.symbol)) = selected.symbol
            WHERE prices.trade_date BETWEEN ? AND ?
              AND prices.open > 0
              AND prices.high > 0
              AND prices.low > 0
              AND prices.close > 0
              AND prices.volume >= 0
              AND prices.high >= GREATEST(
                  prices.open, prices.low, prices.close
              )
              AND prices.low <= LEAST(
                  prices.open, prices.high, prices.close
              )
            ORDER BY symbol, trade_date
            """,
            (start, end),
        )
        connection.execute(
            """
            CREATE TABLE source_duplicates AS
            SELECT symbol, SUM(row_count - 1)::BIGINT AS duplicate_observations
            FROM (
                SELECT symbol, trade_date, COUNT(*) AS row_count
                FROM daily_prices
                GROUP BY symbol, trade_date
                HAVING COUNT(*) > 1
            )
            GROUP BY symbol
            """
        )
        connection.execute(
            """
            CREATE TABLE source_invalid_rows AS
            SELECT
                UPPER(TRIM(prices.symbol)) AS symbol,
                COUNT(*)::BIGINT AS invalid_observations
            FROM legacy.daily_prices AS prices
            JOIN _selected_symbols AS selected
              ON UPPER(TRIM(prices.symbol)) = selected.symbol
            WHERE prices.trade_date BETWEEN ? AND ?
              AND (
                  prices.open IS NULL OR prices.high IS NULL
                  OR prices.low IS NULL OR prices.close IS NULL
                  OR prices.volume IS NULL
                  OR prices.open <= 0 OR prices.high <= 0
                  OR prices.low <= 0 OR prices.close <= 0
                  OR prices.volume < 0
                  OR prices.high < GREATEST(
                      prices.open, prices.low, prices.close
                  )
                  OR prices.low > LEAST(
                      prices.open, prices.high, prices.close
                  )
              )
            GROUP BY UPPER(TRIM(prices.symbol))
            """,
            (start, end),
        )
        connection.execute(
            "CREATE INDEX legacy_symbol_date ON daily_prices(symbol, trade_date)"
        )
        connection.unregister("_selected_symbols")


def _materialize_comparison(
    *,
    files: tuple[Path, ...],
    destination: Path,
    symbols: tuple[str, ...],
    start: date,
    end: date,
) -> None:
    source_expression = _duckdb_file_list(files)
    with duckdb.connect(str(destination)) as connection:
        _register_symbols(connection, symbols)
        connection.execute(
            "CREATE TEMP VIEW _raw_source AS SELECT * FROM "
            f"read_csv_auto({source_expression}, union_by_name=true, "
            "all_varchar=true, filename=true, ignore_errors=true)"
        )
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info('_raw_source')").fetchall()
        }
        symbol = _coalesce(columns, ("TckrSymb", "SYMBOL"), "VARCHAR")
        series = _coalesce(columns, ("SctySrs", "SERIES"), "VARCHAR")
        observed_on = _date_expression(columns)
        open_price = _coalesce(columns, ("OpnPric", "OPEN"), "DOUBLE")
        high_price = _coalesce(columns, ("HghPric", "HIGH"), "DOUBLE")
        low_price = _coalesce(columns, ("LwPric", "LOW"), "DOUBLE")
        close_price = _coalesce(columns, ("ClsPric", "CLOSE"), "DOUBLE")
        volume = _coalesce(columns, ("TtlTradgVol", "TOTTRDQTY"), "DOUBLE")
        isin = _coalesce(columns, ("ISIN",), "VARCHAR", default="NULL")
        connection.execute(
            f"""
            CREATE TABLE source_rows AS
            SELECT
                UPPER(TRIM({symbol})) AS symbol,
                {observed_on} AS trade_date,
                {open_price} AS open,
                {high_price} AS high,
                {low_price} AS low,
                {close_price} AS close,
                {volume} AS volume,
                {isin} AS isin,
                raw.filename AS source_file
            FROM _raw_source AS raw
            JOIN _selected_symbols AS selected
              ON UPPER(TRIM({symbol})) = selected.symbol
            WHERE UPPER(TRIM({series})) = 'EQ'
              AND {observed_on} BETWEEN ? AND ?
            """,
            (start, end),
        )
        connection.execute(
            """
            CREATE TABLE source_duplicates AS
            SELECT symbol, SUM(row_count - 1)::BIGINT AS duplicate_observations
            FROM (
                SELECT symbol, trade_date, COUNT(*) AS row_count
                FROM source_rows
                GROUP BY symbol, trade_date
                HAVING COUNT(*) > 1
            )
            GROUP BY symbol
            """
        )
        connection.execute(
            """
            CREATE TABLE source_invalid_rows AS
            SELECT symbol, COUNT(*)::BIGINT AS invalid_observations
            FROM source_rows
            WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
               OR volume IS NULL
               OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
               OR volume < 0
               OR high < GREATEST(open, low, close)
               OR low > LEAST(open, high, close)
            GROUP BY symbol
            """
        )
        connection.execute(
            """
            CREATE TABLE daily_prices AS
            SELECT
                symbol,
                trade_date,
                open,
                high,
                low,
                close,
                volume,
                NULL::VARCHAR AS sector,
                'NSE'::VARCHAR AS exchange
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY symbol, trade_date
                    ORDER BY source_file, isin
                ) AS source_rank
                FROM source_rows
            )
            WHERE source_rank = 1
              AND open > 0
              AND high > 0
              AND low > 0
              AND close > 0
              AND volume >= 0
              AND high >= GREATEST(open, low, close)
              AND low <= LEAST(open, high, close)
            ORDER BY symbol, trade_date
            """
        )
        connection.execute(
            "CREATE INDEX comparison_symbol_date ON daily_prices(symbol, trade_date)"
        )
        connection.unregister("_selected_symbols")


def _register_symbols(
    connection: duckdb.DuckDBPyConnection,
    symbols: tuple[str, ...],
) -> None:
    connection.register(
        "_selected_symbols",
        pd.DataFrame({"symbol": list(symbols)}),
    )


def _coalesce(
    columns: set[str],
    choices: tuple[str, ...],
    cast_type: str,
    *,
    default: str | None = None,
) -> str:
    available = [
        f'TRY_CAST(raw."{name}" AS {cast_type})' for name in choices if name in columns
    ]
    if not available:
        if default is not None:
            return default
        raise ValueError(f"comparison CSV missing columns: {', '.join(choices)}")
    return available[0] if len(available) == 1 else f"COALESCE({', '.join(available)})"


def _date_expression(columns: set[str]) -> str:
    expressions = []
    if "TradDt" in columns:
        expressions.append('TRY_CAST(raw."TradDt" AS DATE)')
    if "TIMESTAMP" in columns:
        expressions.append("TRY_STRPTIME(raw.\"TIMESTAMP\", '%d-%b-%Y')::DATE")
    if not expressions:
        raise ValueError("comparison CSV has no supported trade-date column")
    return (
        expressions[0]
        if len(expressions) == 1
        else f"COALESCE({', '.join(expressions)})"
    )


def _duckdb_file_list(files: tuple[Path, ...]) -> str:
    escaped = ["'" + str(path).replace("'", "''") + "'" for path in files]
    return "[" + ",".join(escaped) + "]"


def _materialize_common_replay(
    *,
    legacy_sample: Path,
    comparison_sample: Path,
    legacy_replay: Path,
    comparison_replay: Path,
) -> tuple[date, date, int]:
    with duckdb.connect() as connection:
        connection.execute(f"ATTACH {_sql_path(legacy_sample)} AS legacy (READ_ONLY)")
        connection.execute(
            f"ATTACH {_sql_path(comparison_sample)} AS comparison (READ_ONLY)"
        )
        common_dates = tuple(
            row[0]
            for row in connection.execute(
                """
                SELECT DISTINCT trade_date FROM legacy.daily_prices
                INTERSECT
                SELECT DISTINCT trade_date FROM comparison.daily_prices
                ORDER BY trade_date
                """
            ).fetchall()
        )
    if not common_dates:
        raise ValueError("legacy and comparison samples have no common sessions")
    for source, destination in (
        (legacy_sample, legacy_replay),
        (comparison_sample, comparison_replay),
    ):
        with duckdb.connect(str(destination)) as output:
            output.execute(f"ATTACH {_sql_path(source)} AS source (READ_ONLY)")
            output.register(
                "_common_dates",
                pd.DataFrame({"trade_date": list(common_dates)}),
            )
            output.execute(
                """
                CREATE TABLE daily_prices AS
                SELECT prices.*
                FROM source.daily_prices AS prices
                JOIN _common_dates AS sessions USING(trade_date)
                ORDER BY symbol, trade_date
                """
            )
            output.execute(
                "CREATE INDEX replay_symbol_date ON daily_prices(symbol, trade_date)"
            )
            output.unregister("_common_dates")
    return common_dates[0], common_dates[-1], len(common_dates)


def _sql_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


__all__ = ["PreparedWarehouseSample", "WarehouseSampleBuilder"]
