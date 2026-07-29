"""Fail-closed Historical Truth contract for DSI-011 research execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

DATA_CONTRACT_VERSION = "DSI-011-data-contract-v1.0.0"
_UNRESOLVED_BASIS_STATES = (
    "ADJUSTMENT_FACTOR_UNKNOWN",
    "IDENTITY_TRANSITION_UNRESOLVED",
    "MIXED_PRICE_BASIS",
)


@dataclass(frozen=True, slots=True)
class ResearchDataContract:
    requested_start: date
    actual_start: date | None
    actual_end: date | None
    expected_trading_sessions: int
    observed_trading_sessions: int
    certified_securities: int
    raw_security_session_rows: int
    adjusted_security_session_rows: int
    unresolved_security_identities: int
    unresolved_series_intervals: int
    unresolved_corporate_action_factors: int
    mixed_price_basis_intervals: int
    invalid_adjusted_ohlc_rows: int
    duplicate_security_session_rows: int
    missing_adjusted_rows: int
    alpha_signal_records: int
    database_sha256: str
    blockers: tuple[str, ...]
    contract_version: str = DATA_CONTRACT_VERSION
    free_official_data_only: bool = True
    pre2016_data_used: bool = False
    production_influence: bool = False

    @property
    def ready(self) -> bool:
        return (
            not self.blockers
            and self.actual_start is not None
            and self.actual_end is not None
        )

    @property
    def alpha_signal_ready(self) -> bool:
        return self.ready and self.alpha_signal_records > 0

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("requested_start", "actual_start", "actual_end"):
            value = payload[key]
            payload[key] = None if value is None else value.isoformat()
        payload["ready"] = self.ready
        payload["alpha_signal_ready"] = self.alpha_signal_ready
        return payload

    @property
    def contract_sha256(self) -> str:
        encoded = json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


class ResearchDataContractAuditor:
    """Audit the complete post-2016 execution population without exclusions."""

    def audit(
        self,
        database: Path,
        *,
        requested_start: date = date(2016, 1, 1),
    ) -> ResearchDataContract:
        if requested_start < date(2016, 1, 1):
            raise ValueError("DSI-011 requested start cannot precede 2016-01-01")
        if not database.is_file():
            raise FileNotFoundError(f"Historical Truth database not found: {database}")
        connection = duckdb.connect(str(database), read_only=True)
        try:
            raw = connection.execute(
                """
                SELECT MIN(trading_date), MAX(trading_date),
                       COUNT(DISTINCT trading_date), COUNT(*),
                       COUNT(DISTINCT isin)
                FROM daily_candle
                WHERE trading_date >= ? AND UPPER(exchange) = 'NSE'
                """,
                (requested_start,),
            ).fetchone()
            adjusted = connection.execute(
                """
                SELECT MIN(trading_date), MAX(trading_date),
                       COUNT(DISTINCT trading_date), COUNT(*),
                       COUNT(DISTINCT isin),
                       SUM(CASE WHEN adjusted_open <= 0 OR adjusted_high <= 0
                                  OR adjusted_low <= 0 OR adjusted_close <= 0
                                  OR adjusted_high < GREATEST(adjusted_open,
                                      adjusted_low, adjusted_close)
                                  OR adjusted_low > LEAST(adjusted_open,
                                      adjusted_high, adjusted_close)
                                THEN 1 ELSE 0 END)
                FROM adjusted_daily_candle
                WHERE trading_date >= ? AND UPPER(exchange) = 'NSE'
                """,
                (requested_start,),
            ).fetchone()
            duplicate_rows = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM (
                    SELECT trading_date, exchange, isin, series, COUNT(*) AS n
                    FROM adjusted_daily_candle
                    WHERE trading_date >= ? AND UPPER(exchange) = 'NSE'
                    GROUP BY 1, 2, 3, 4 HAVING COUNT(*) > 1
                )
                """,
                requested_start,
            )
            unresolved_factors = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM corporate_action_adjustment_factor
                WHERE effective_date >= ?
                  AND state IN ('UNKNOWN', 'AMBIGUOUS')
                """,
                requested_start,
            )
            mixed_intervals = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM price_basis_interval
                WHERE COALESCE(valid_to, DATE '9999-12-31') >= ?
                  AND state IN (?, ?, ?)
                """,
                requested_start,
                *_UNRESOLVED_BASIS_STATES,
            )
            unresolved_identities = _scalar(
                connection,
                """
                SELECT COUNT(DISTINCT identity_key) FROM price_basis_interval
                WHERE COALESCE(valid_to, DATE '9999-12-31') >= ?
                  AND state = 'IDENTITY_TRANSITION_UNRESOLVED'
                """,
                requested_start,
            )
            unresolved_series = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM price_basis_interval
                WHERE COALESCE(valid_to, DATE '9999-12-31') >= ?
                  AND list_contains(
                      from_json(issue_codes, '["VARCHAR"]'),
                      'SERIES_INTERVAL_UNRESOLVED'
                  )
                """,
                requested_start,
                fallback=0,
            )
            signal_records = _historical_signal_count(connection, requested_start)
        finally:
            connection.close()

        raw_start = raw[0] if raw else None
        raw_end = raw[1] if raw else None
        raw_sessions = int(raw[2] or 0) if raw else 0
        raw_rows = int(raw[3] or 0) if raw else 0
        adjusted_start = adjusted[0] if adjusted else None
        adjusted_end = adjusted[1] if adjusted else None
        adjusted_sessions = int(adjusted[2] or 0) if adjusted else 0
        adjusted_rows = int(adjusted[3] or 0) if adjusted else 0
        adjusted_securities = int(adjusted[4] or 0) if adjusted else 0
        invalid_rows = int(adjusted[5] or 0) if adjusted else 0
        missing_adjusted = max(0, raw_rows - adjusted_rows)
        blockers: list[str] = []
        if raw_start is None or raw_end is None:
            blockers.append("POST2016_DAILY_CANDLES_UNAVAILABLE")
        if raw_sessions != adjusted_sessions:
            blockers.append(
                "EXPECTED_TRADING_SESSIONS_DO_NOT_EQUAL_ADJUSTED_SESSIONS:"
                f"{raw_sessions}!={adjusted_sessions}"
            )
        if unresolved_identities:
            blockers.append(f"UNRESOLVED_SECURITY_IDENTITIES:{unresolved_identities}")
        if unresolved_series:
            blockers.append(f"UNRESOLVED_SERIES_INTERVALS:{unresolved_series}")
        if unresolved_factors:
            blockers.append(f"UNRESOLVED_CORPORATE_ACTION_FACTORS:{unresolved_factors}")
        if mixed_intervals:
            blockers.append(f"MIXED_PRICE_BASIS_INTERVALS:{mixed_intervals}")
        if invalid_rows:
            blockers.append(f"INVALID_ADJUSTED_OHLC_ROWS:{invalid_rows}")
        if duplicate_rows:
            blockers.append(f"DUPLICATE_SECURITY_SESSION_ROWS:{duplicate_rows}")
        if missing_adjusted:
            blockers.append(
                f"MISSING_ADJUSTED_SECURITY_SESSION_ROWS:{missing_adjusted}"
            )
        return ResearchDataContract(
            requested_start=requested_start,
            actual_start=adjusted_start,
            actual_end=adjusted_end,
            expected_trading_sessions=raw_sessions,
            observed_trading_sessions=adjusted_sessions,
            certified_securities=adjusted_securities,
            raw_security_session_rows=raw_rows,
            adjusted_security_session_rows=adjusted_rows,
            unresolved_security_identities=unresolved_identities,
            unresolved_series_intervals=unresolved_series,
            unresolved_corporate_action_factors=unresolved_factors,
            mixed_price_basis_intervals=mixed_intervals,
            invalid_adjusted_ohlc_rows=invalid_rows,
            duplicate_security_session_rows=duplicate_rows,
            missing_adjusted_rows=missing_adjusted,
            alpha_signal_records=signal_records,
            database_sha256=_file_sha256(database),
            blockers=tuple(blockers),
        )


def _scalar(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    *parameters: object,
    fallback: int | None = None,
) -> int:
    try:
        row = connection.execute(query, parameters).fetchone()
    except duckdb.Error:
        if fallback is not None:
            return fallback
        raise
    return int(row[0] or 0) if row else 0


def _historical_signal_count(
    connection: duckdb.DuckDBPyConnection,
    start: date,
) -> int:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    for table in (
        "frozen_recommendation",
        "recommendation_snapshot",
        "historical_recommendation",
    ):
        if table in tables:
            return _scalar(
                connection,
                f"SELECT COUNT(*) FROM {table} WHERE generated_at::DATE >= ?",
                start,
            )
    return 0


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = [
    "DATA_CONTRACT_VERSION",
    "ResearchDataContract",
    "ResearchDataContractAuditor",
]
