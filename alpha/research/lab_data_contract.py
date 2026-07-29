"""Fail-closed Historical Truth contract for DSI-011A research execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import duckdb

from alpha.research.lab_models import AlphaSignalSource

DATA_CONTRACT_VERSION = "DSI-011A-data-contract-v1.0.0"


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
    recorded_historical_signal_records: int = 0
    retrospective_alpha_signal_records: int = 0
    walk_forward_alpha_signal_records: int = 0
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
    def pure_technical_ready(self) -> bool:
        return self.ready

    @property
    def retrospective_alpha_replay_ready(self) -> bool:
        unclassified_legacy_count = (
            self.alpha_signal_records
            if not (
                self.recorded_historical_signal_records
                or self.retrospective_alpha_signal_records
                or self.walk_forward_alpha_signal_records
            )
            else 0
        )
        return self.ready and (
            self.retrospective_alpha_signal_records + unclassified_legacy_count > 0
        )

    @property
    def walk_forward_alpha_replay_ready(self) -> bool:
        return self.ready and self.walk_forward_alpha_signal_records > 0

    @property
    def recorded_historical_signal_ready(self) -> bool:
        return self.ready and self.recorded_historical_signal_records > 0

    @property
    def alpha_signal_ready(self) -> bool:
        return self.retrospective_alpha_replay_ready

    def signal_source_ready(self, source: AlphaSignalSource) -> bool:
        mapping = {
            AlphaSignalSource.RECORDED_HISTORICAL_ALPHA_SIGNAL: (
                self.recorded_historical_signal_ready
            ),
            AlphaSignalSource.RETROSPECTIVE_FROZEN_ALPHA_REPLAY: (
                self.retrospective_alpha_replay_ready
            ),
            AlphaSignalSource.WALK_FORWARD_ALPHA_REPLAY: (
                self.walk_forward_alpha_replay_ready
            ),
        }
        return mapping[source]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("requested_start", "actual_start", "actual_end"):
            value = payload[key]
            payload[key] = None if value is None else value.isoformat()
        payload.update(
            {
                "ready": self.ready,
                "alpha_signal_ready": self.alpha_signal_ready,
                "pure_technical_ready": self.pure_technical_ready,
                "retrospective_alpha_replay_ready": (
                    self.retrospective_alpha_replay_ready
                ),
                "walk_forward_alpha_replay_ready": (
                    self.walk_forward_alpha_replay_ready
                ),
                "recorded_historical_signal_ready": (
                    self.recorded_historical_signal_ready
                ),
            }
        )
        return payload

    @property
    def contract_sha256(self) -> str:
        encoded = json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


class ResearchDataContractAuditor:
    """Audit the complete post-2016 governed research population."""

    def audit(
        self,
        database: Path,
        *,
        requested_start: date = date(2016, 1, 1),
    ) -> ResearchDataContract:
        if requested_start < date(2016, 1, 1):
            raise ValueError("DSI-011A requested start cannot precede 2016-01-01")
        if not database.is_file():
            raise FileNotFoundError(f"Historical Truth database not found: {database}")
        connection = duckdb.connect(str(database), read_only=True)
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'main'
                    """
                ).fetchall()
            }
            if "research_daily_candle" not in tables:
                return _missing_table_contract(database, requested_start)
            raw = connection.execute(
                """
                SELECT COUNT(DISTINCT trading_date), COUNT(*)
                FROM daily_candle
                WHERE trading_date >= ? AND UPPER(exchange) = 'NSE'
                  AND UPPER(TRIM(series)) IN ('BE', 'BZ', 'EQ', 'SM', 'ST')
                  AND UPPER(TRIM(isin)) LIKE 'INE%'
                  AND isin IS NOT NULL AND TRIM(isin) <> ''
                """,
                [requested_start],
            ).fetchone()
            research = connection.execute(
                """
                SELECT MIN(trading_date), MAX(trading_date),
                       COUNT(DISTINCT trading_date), COUNT(*),
                       COUNT(DISTINCT governed_identity_id),
                       COUNT(*) FILTER (
                           WHERE governed_identity_id IS NULL
                              OR identity_source NOT IN (
                                  'EXACT_DAILY_CANDLE_ISIN',
                                  'CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE'
                              )
                       ),
                       COUNT(*) FILTER (
                           WHERE price_basis_state NOT IN (
                               'CERTIFIED_FACTOR_ONE', 'CERTIFIED_ADJUSTED',
                               'CERTIFIED_NON_MULTIPLICATIVE_TRANSITION'
                           )
                       ),
                       COUNT(*) FILTER (
                           WHERE adjusted_open <= 0 OR adjusted_high <= 0
                              OR adjusted_low <= 0 OR adjusted_close <= 0
                              OR adjusted_high < GREATEST(
                                  adjusted_open, adjusted_low, adjusted_close
                              )
                              OR adjusted_low > LEAST(
                                  adjusted_open, adjusted_high, adjusted_close
                              )
                       )
                FROM research_daily_candle
                WHERE trading_date >= ?
                  AND research_eligibility_state = 'ELIGIBLE_EQUITY'
                """,
                [requested_start],
            ).fetchone()
            duplicates = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM (
                    SELECT trading_date, governed_identity_id, series, COUNT(*) n
                    FROM research_daily_candle
                    WHERE trading_date >= ?
                      AND research_eligibility_state = 'ELIGIBLE_EQUITY'
                    GROUP BY 1, 2, 3 HAVING COUNT(*) > 1
                )
                """,
                requested_start,
            )
            unresolved_factors = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM corporate_action_adjustment_factor f
                JOIN corporate_action_event e USING (action_id)
                WHERE f.effective_date >= ?
                  AND e.price_adjustment_required
                  AND f.state IN ('UNKNOWN', 'AMBIGUOUS', 'INVALID', 'CONFLICTING')
                """,
                requested_start,
            )
            signal_counts = _historical_signal_counts(
                connection,
                requested_start,
                cast(date | None, research[1] if research else None),
                tables,
            )
            governed_database_hash = _governed_database_hash(
                connection,
                database,
                tables,
            )
        finally:
            connection.close()
        raw_sessions = int(raw[0] or 0) if raw else 0
        raw_rows = int(raw[1] or 0) if raw else 0
        actual_start = research[0] if research else None
        actual_end = research[1] if research else None
        observed_sessions = int(research[2] or 0) if research else 0
        research_rows = int(research[3] or 0) if research else 0
        missing = max(0, raw_rows - research_rows)
        unresolved_identities = int(research[5] or 0) if research else 0
        mixed = int(research[6] or 0) if research else 0
        invalid = int(research[7] or 0) if research else 0
        blockers: list[str] = []
        checks = (
            (raw_sessions != observed_sessions, "SESSION_RECONCILIATION"),
            (unresolved_identities > 0, "UNRESOLVED_SECURITY_IDENTITIES"),
            (unresolved_factors > 0, "UNRESOLVED_CORPORATE_ACTION_FACTORS"),
            (mixed > 0, "MIXED_PRICE_BASIS_INTERVALS"),
            (invalid > 0, "INVALID_ADJUSTED_OHLC_ROWS"),
            (duplicates > 0, "DUPLICATE_SECURITY_SESSION_ROWS"),
            (missing > 0, "UNEXPLAINED_MISSING_RESEARCH_ROWS"),
        )
        values = (
            abs(raw_sessions - observed_sessions),
            unresolved_identities,
            unresolved_factors,
            mixed,
            invalid,
            duplicates,
            missing,
        )
        for (failed, name), value in zip(checks, values, strict=True):
            if failed:
                blockers.append(f"{name}:{value}")
        total_signals = sum(signal_counts.values())
        return ResearchDataContract(
            requested_start=requested_start,
            actual_start=actual_start,
            actual_end=actual_end,
            expected_trading_sessions=raw_sessions,
            observed_trading_sessions=observed_sessions,
            certified_securities=int(research[4] or 0) if research else 0,
            raw_security_session_rows=raw_rows,
            adjusted_security_session_rows=research_rows,
            unresolved_security_identities=unresolved_identities,
            unresolved_series_intervals=0,
            unresolved_corporate_action_factors=unresolved_factors,
            mixed_price_basis_intervals=mixed,
            invalid_adjusted_ohlc_rows=invalid,
            duplicate_security_session_rows=duplicates,
            missing_adjusted_rows=missing,
            alpha_signal_records=total_signals,
            database_sha256=governed_database_hash,
            blockers=tuple(blockers),
            recorded_historical_signal_records=signal_counts["recorded"],
            retrospective_alpha_signal_records=signal_counts["retrospective"],
            walk_forward_alpha_signal_records=signal_counts["walk_forward"],
        )


def _historical_signal_counts(
    connection: duckdb.DuckDBPyConnection,
    start: date,
    end: date | None,
    tables: set[str],
) -> dict[str, int]:
    result = {"recorded": 0, "retrospective": 0, "walk_forward": 0}
    if "frozen_recommendation" not in tables or end is None:
        return result
    rows = connection.execute(
        """
        SELECT signal_source_state, COUNT(*)
        FROM frozen_recommendation
        WHERE generated_at::DATE BETWEEN ? AND ?
          AND signal_source_state IN (
              'RECORDED_HISTORICAL_ALPHA_SIGNAL',
              'WALK_FORWARD_ALPHA_REPLAY'
          )
        GROUP BY signal_source_state
        """,
        [start, end],
    ).fetchall()
    mapping = {
        "RECORDED_HISTORICAL_ALPHA_SIGNAL": "recorded",
        "RETROSPECTIVE_FROZEN_ALPHA_REPLAY": "retrospective",
        "WALK_FORWARD_ALPHA_REPLAY": "walk_forward",
    }
    for state, count in rows:
        key = mapping.get(str(state))
        if key is not None:
            result[key] = int(count)
    if "frozen_recommendation_replay_run" not in tables:
        return result
    run = connection.execute(
        """
        SELECT run_id
        FROM frozen_recommendation_replay_run
        WHERE start_date <= ? AND end_date >= ?
          AND readiness_state = 'RETROSPECTIVE_ALPHA_REPLAY_READY'
          AND sessions_failed = 0
        ORDER BY start_date DESC, end_date ASC, run_id
        LIMIT 1
        """,
        [start, end],
    ).fetchone()
    if run is not None:
        result["retrospective"] = _scalar(
            connection,
            """
            SELECT COUNT(*) FROM frozen_recommendation
            WHERE run_id = ?
              AND signal_source_state = 'RETROSPECTIVE_FROZEN_ALPHA_REPLAY'
            """,
            str(run[0]),
        )
    return result


def _missing_table_contract(
    database: Path,
    requested_start: date,
) -> ResearchDataContract:
    return ResearchDataContract(
        requested_start=requested_start,
        actual_start=None,
        actual_end=None,
        expected_trading_sessions=0,
        observed_trading_sessions=0,
        certified_securities=0,
        raw_security_session_rows=0,
        adjusted_security_session_rows=0,
        unresolved_security_identities=0,
        unresolved_series_intervals=0,
        unresolved_corporate_action_factors=0,
        mixed_price_basis_intervals=0,
        invalid_adjusted_ohlc_rows=0,
        duplicate_security_session_rows=0,
        missing_adjusted_rows=0,
        alpha_signal_records=0,
        database_sha256=_file_sha256(database),
        blockers=("RESEARCH_DAILY_CANDLE_UNAVAILABLE",),
    )


def _governed_database_hash(
    connection: duckdb.DuckDBPyConnection,
    database: Path,
    tables: set[str],
) -> str:
    if "research_price_certification" not in tables:
        return _file_sha256(database)
    price_rows = connection.execute(
        """
        SELECT contract_version, start_date, end_date, logical_sha256,
               readiness_state
        FROM research_price_certification
        ORDER BY contract_version, start_date, end_date
        """
    ).fetchall()
    signal_rows: list[tuple[object, ...]] = []
    if "frozen_recommendation_replay_run" in tables:
        signal_rows = connection.execute(
            """
            SELECT run_id, start_date, end_date, data_logical_sha256,
                   ledger_logical_sha256, source_commit, engine_version,
                   readiness_state
            FROM frozen_recommendation_replay_run
            ORDER BY run_id
            """
        ).fetchall()
    payload = {
        "research_price_certifications": price_rows,
        "frozen_alpha_replays": signal_rows,
    }
    return hashlib.sha256(
        json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _scalar(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    *parameters: object,
) -> int:
    row = connection.execute(query, parameters).fetchone()
    return int(row[0] or 0) if row else 0


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
