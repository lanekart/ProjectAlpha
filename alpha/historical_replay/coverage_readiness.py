"""Deterministic warm-up, outcome, and eligible-security replay evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

HISTORICAL_REPLAY_COVERAGE_CONTRACT_VERSION = "HTR-006-coverage-v1.0.0"
REQUIRED_WARMUP_SESSIONS = 200
REQUIRED_OUTCOME_SESSIONS = 60
MINIMUM_ELIGIBLE_SECURITIES = 1
_TABLE_CANDIDATES = ("daily_prices", "daily_candle")
_SYMBOL_COLUMNS = ("security_id", "isin", "symbol", "ticker")
_DATE_COLUMNS = ("trade_date", "trading_date", "session_date", "date")


@dataclass(frozen=True, slots=True)
class HistoricalReplayCoverageEvidence:
    """Immutable proof of replay-window coverage and security eligibility."""

    from_date: date
    to_date: date
    observed_warmup_sessions: int
    observed_outcome_sessions: int
    eligible_security_ids: tuple[str, ...]
    source_table: str
    required_warmup_sessions: int = REQUIRED_WARMUP_SESSIONS
    required_outcome_sessions: int = REQUIRED_OUTCOME_SESSIONS
    minimum_eligible_securities: int = MINIMUM_ELIGIBLE_SECURITIES
    contract_version: str = HISTORICAL_REPLAY_COVERAGE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.to_date < self.from_date:
            raise ValueError("coverage end cannot precede start")
        if self.required_warmup_sessions != REQUIRED_WARMUP_SESSIONS:
            raise ValueError("unsupported warm-up-session requirement")
        if self.required_outcome_sessions != REQUIRED_OUTCOME_SESSIONS:
            raise ValueError("unsupported outcome-session requirement")
        if self.minimum_eligible_securities != MINIMUM_ELIGIBLE_SECURITIES:
            raise ValueError("unsupported minimum eligible-security requirement")
        if self.observed_warmup_sessions < 0 or self.observed_outcome_sessions < 0:
            raise ValueError("observed coverage sessions cannot be negative")
        normalized = tuple(sorted(set(self.eligible_security_ids)))
        if self.eligible_security_ids != normalized:
            raise ValueError("eligible security IDs must be sorted and unique")
        if self.contract_version != HISTORICAL_REPLAY_COVERAGE_CONTRACT_VERSION:
            raise ValueError("unsupported historical replay coverage contract")

    @property
    def eligible_security_count(self) -> int:
        return len(self.eligible_security_ids)

    @property
    def coverage_sha256(self) -> str:
        encoded = json.dumps(
            self.as_dict(include_digest=False),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "observed_warmup_sessions": self.observed_warmup_sessions,
            "observed_outcome_sessions": self.observed_outcome_sessions,
            "eligible_security_ids": list(self.eligible_security_ids),
            "eligible_security_count": self.eligible_security_count,
            "source_table": self.source_table,
            "required_warmup_sessions": self.required_warmup_sessions,
            "required_outcome_sessions": self.required_outcome_sessions,
            "minimum_eligible_securities": self.minimum_eligible_securities,
            "contract_version": self.contract_version,
        }
        if include_digest:
            payload["coverage_sha256"] = self.coverage_sha256
        return payload


def build_historical_replay_coverage_evidence(
    *,
    database: Path,
    from_date: date,
    to_date: date,
) -> HistoricalReplayCoverageEvidence:
    """Build conservative point-in-time replay coverage from the local warehouse."""

    if to_date < from_date:
        raise ValueError("to_date must be on or after from_date")
    if not database.exists():
        return _empty_evidence(from_date=from_date, to_date=to_date)

    connection = duckdb.connect(str(database), read_only=True)
    try:
        resolved = _resolve_source(connection)
        if resolved is None:
            return _empty_evidence(from_date=from_date, to_date=to_date)
        table, symbol_column, date_column = resolved
        identifier = f'"main"."{table}"'
        warmup_row = connection.execute(
            f'SELECT COUNT(DISTINCT "{date_column}") FROM {identifier} '
            f'WHERE "{date_column}" <= ?',
            [from_date],
        ).fetchone()
        outcome_row = connection.execute(
            f'SELECT COUNT(DISTINCT "{date_column}") FROM {identifier} '
            f'WHERE "{date_column}" > ?',
            [to_date],
        ).fetchone()
        rows = connection.execute(
            f'SELECT UPPER(TRIM(CAST("{symbol_column}" AS VARCHAR))) AS security_id, '
            f'COUNT(DISTINCT CASE WHEN "{date_column}" <= ? '
            f'THEN "{date_column}" END) AS warmup_sessions, '
            f'COUNT(DISTINCT CASE WHEN "{date_column}" > ? '
            f'THEN "{date_column}" END) AS outcome_sessions '
            f"FROM {identifier} "
            f'WHERE "{symbol_column}" IS NOT NULL '
            f"GROUP BY security_id ORDER BY security_id",
            [from_date, to_date],
        ).fetchall()
    finally:
        connection.close()

    eligible = tuple(
        str(security_id)
        for security_id, warmup_sessions, outcome_sessions in rows
        if str(security_id).strip()
        and int(warmup_sessions or 0) >= REQUIRED_WARMUP_SESSIONS
        and int(outcome_sessions or 0) >= REQUIRED_OUTCOME_SESSIONS
    )
    return HistoricalReplayCoverageEvidence(
        from_date=from_date,
        to_date=to_date,
        observed_warmup_sessions=int(warmup_row[0] or 0) if warmup_row else 0,
        observed_outcome_sessions=int(outcome_row[0] or 0) if outcome_row else 0,
        eligible_security_ids=eligible,
        source_table=f"main.{table}",
    )


def _resolve_source(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[str, str, str] | None:
    rows = connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
    ).fetchall()
    tables = {str(row[0]) for row in rows}
    for table in _TABLE_CANDIDATES:
        if table not in tables:
            continue
        columns = {
            str(row[0])
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = ?",
                [table],
            ).fetchall()
        }
        symbol_column = next(
            (column for column in _SYMBOL_COLUMNS if column in columns),
            None,
        )
        date_column = next(
            (column for column in _DATE_COLUMNS if column in columns),
            None,
        )
        if symbol_column is not None and date_column is not None:
            return table, symbol_column, date_column
    return None


def _empty_evidence(
    *,
    from_date: date,
    to_date: date,
) -> HistoricalReplayCoverageEvidence:
    return HistoricalReplayCoverageEvidence(
        from_date=from_date,
        to_date=to_date,
        observed_warmup_sessions=0,
        observed_outcome_sessions=0,
        eligible_security_ids=(),
        source_table="",
    )


__all__ = [
    "HISTORICAL_REPLAY_COVERAGE_CONTRACT_VERSION",
    "MINIMUM_ELIGIBLE_SECURITIES",
    "REQUIRED_OUTCOME_SESSIONS",
    "REQUIRED_WARMUP_SESSIONS",
    "HistoricalReplayCoverageEvidence",
    "build_historical_replay_coverage_evidence",
]
