"""HTR-008 replay eligibility and security continuity certification engine."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.replay_eligibility_models import (
    HTR008_CONTRACT_VERSION,
    PRODUCTION_INFLUENCE,
    BaselineBenchmarkSummary,
    CandidateExposureRecord,
    CandleQualitySummary,
    CertificationState,
    CertificationSummary,
    ContinuitySummary,
    CorporateActionRiskRecord,
    CorporateActionSeverity,
    DepthSummary,
    EligibilityAuditPolicy,
    EligibilityFunnelRecord,
    EligibilityReconciliation,
    PopulationSummary,
    ReplayEligibilityIntegrityReport,
    ReplayReadinessClassification,
    SecurityEligibilityRecord,
    SnapshotAuditSummary,
    SurvivorshipRisk,
)
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine

_SUPPORTED_REPLAY_SERIES = frozenset({"EQ"})
_BLOCKING_CLASSIFICATIONS = frozenset(
    {
        ReplayReadinessClassification.IDENTITY_AMBIGUITY,
        ReplayReadinessClassification.SYMBOL_REUSE_CONFLICT,
        ReplayReadinessClassification.ISIN_CONFLICT,
        ReplayReadinessClassification.IDENTITY_INTERVAL_OVERLAP,
        ReplayReadinessClassification.INVALID_CANDLE_CONTAMINATION,
        ReplayReadinessClassification.CONFLICTING_EVIDENCE,
        ReplayReadinessClassification.CORPORATE_ACTION_CONTAMINATION,
    }
)


@dataclass(frozen=True, slots=True)
class _IdentityChecks:
    symbol_reuse: frozenset[str]
    symbol_change: frozenset[str]
    supported_symbol_change: frozenset[str]
    identity_overlap: frozenset[str]
    identity_gap: frozenset[str]
    isin_conflict: frozenset[str]
    outside_interval: frozenset[str]
    lineage_disagreement: frozenset[str]
    symbol_reuse_cases: int


class ReplayEligibilityIntegrityEngine:
    """Audit replay eligibility without changing benchmark or warehouse behavior."""

    def __init__(
        self,
        database_path: Path,
        snapshot_root: Path,
        *,
        policy: EligibilityAuditPolicy | None = None,
    ) -> None:
        self.database_path = database_path
        self.snapshot_root = snapshot_root
        self.policy = policy or EligibilityAuditPolicy()
        self.warehouse = CanonicalPointInTimeWarehouse(database_path)
        self.snapshots = PointInTimeSnapshotEngine(self.warehouse, snapshot_root)

    def run(
        self,
        *,
        calendar_report: Path,
        benchmark_output: Path,
        start_date: date,
        end_date: date,
        symbols: tuple[str, ...] = (),
        isins: tuple[str, ...] = (),
        years: tuple[int, ...] = (),
        classifications: tuple[ReplayReadinessClassification, ...] = (),
        issue_codes: tuple[str, ...] = (),
        only_not_ready: bool = False,
    ) -> ReplayEligibilityIntegrityReport:
        if end_date < start_date:
            raise ValueError("audit end date must be on or after start date")
        sessions = self._official_sessions(
            calendar_report,
            start_date=start_date,
            end_date=end_date,
        )
        baseline = self._baseline(benchmark_output)
        snapshots = self._snapshot_audit(sessions)
        connection = self._connection()
        try:
            self._prepare_sql(
                connection,
                sessions=sessions,
                start_date=start_date,
                end_date=end_date,
            )
            checks = self._identity_checks(connection)
            corporate_actions = self._corporate_actions(connection)
            records = self._records(
                connection,
                checks=checks,
                corporate_actions=corporate_actions,
                snapshots=snapshots,
            )
            all_records = records
            records = self._filter_records(
                records,
                symbols=symbols,
                isins=isins,
                years=years,
                classifications=classifications,
                issue_codes=issue_codes,
                only_not_ready=only_not_ready,
            )
            record_by_key = {record.identity_key: record for record in all_records}
            self._register_certifications(connection, all_records)
            funnel = self._funnel(connection, snapshots)
            exposure = self._candidate_exposure(
                connection,
                benchmark_output=benchmark_output,
                record_by_key=record_by_key,
            )
            population = self._population(connection, all_records, checks)
            depth = self._depth(records)
            continuity = self._continuity(records)
            quality = self._candle_quality(connection, snapshots)
            annual_coverage = self._annual_coverage(connection)
            reconciliation = self._reconciliation(baseline, all_records)
            certification = self._certification(all_records, snapshots)
        finally:
            connection.close()
        draft = ReplayEligibilityIntegrityReport(
            contract_version=HTR008_CONTRACT_VERSION,
            production_influence=PRODUCTION_INFLUENCE,
            database_path=str(self.database_path),
            calendar_report_path=str(calendar_report),
            snapshot_root=str(self.snapshot_root),
            start_date=start_date,
            end_date=end_date,
            policy=self.policy,
            baseline=baseline,
            population=population,
            depth=depth,
            continuity=continuity,
            candle_quality=quality,
            snapshots=snapshots,
            reconciliation=reconciliation,
            certification=certification,
            records=records,
            corporate_actions=corporate_actions,
            funnel=funnel,
            candidate_exposure=exposure,
            annual_coverage=annual_coverage,
            report_sha256="",
        )
        return replace(draft, report_sha256=draft.calculated_sha256())

    def _connection(self) -> duckdb.DuckDBPyConnection:
        if not self.database_path.is_file():
            raise FileNotFoundError(
                f"historical truth database not found: {self.database_path}"
            )
        connection = duckdb.connect(":memory:")
        escaped = str(self.database_path.resolve()).replace("'", "''")
        connection.execute(f"ATTACH '{escaped}' AS source (READ_ONLY)")
        return connection

    @staticmethod
    def _official_sessions(
        path: Path,
        *,
        start_date: date,
        end_date: date,
    ) -> tuple[tuple[date, str], ...]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("calendar report must be a JSON object")
        if payload.get("certification_state") not in {"certified", "complete"}:
            raise ValueError("calendar report is not certified")
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise ValueError("calendar report records are unavailable")
        sessions: list[tuple[date, str]] = []
        for raw in raw_records:
            if not isinstance(raw, dict):
                continue
            classification = str(raw.get("classification", ""))
            if classification not in {"regular_session", "special_session"}:
                continue
            trading_date = date.fromisoformat(str(raw["trading_date"]))
            if start_date <= trading_date <= end_date:
                sessions.append((trading_date, classification))
        sessions.sort(key=lambda item: item[0])
        if not sessions:
            raise ValueError("calendar report has no official sessions in audit window")
        if len({item[0] for item in sessions}) != len(sessions):
            raise ValueError("calendar report contains duplicate official sessions")
        return tuple(sessions)

    def _prepare_sql(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        sessions: tuple[tuple[date, str], ...],
        start_date: date,
        end_date: date,
    ) -> None:
        connection.execute(
            """
            CREATE TEMP TABLE official_session (
                trading_date DATE PRIMARY KEY,
                session_ordinal INTEGER NOT NULL,
                classification VARCHAR NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO official_session VALUES (?, ?, ?)",
            [
                (trading_date, index, classification)
                for index, (trading_date, classification) in enumerate(
                    sessions,
                    start=1,
                )
            ],
        )
        connection.execute(
            """
            CREATE TEMP TABLE scoped_candle AS
            WITH identity_presence AS (
                SELECT exchange, isin, COUNT(*) AS identity_rows
                FROM source.security_identity
                WHERE isin IS NOT NULL
                GROUP BY exchange, isin
            ),
            detailed_lineage AS (
                SELECT DISTINCT trading_date, exchange, symbol, series,
                                source_sha256
                FROM source.candle_ingestion_lineage
            ),
            any_lineage AS (
                SELECT DISTINCT trading_date, exchange, symbol, series
                FROM source.candle_ingestion_lineage
            )
            SELECT
                c.*,
                CASE
                    WHEN c.isin IS NOT NULL THEN
                        LOWER(c.exchange) || ':isin:' || UPPER(c.isin)
                    ELSE LOWER(c.exchange) || ':symbol:' ||
                         UPPER(c.symbol) || ':' || UPPER(c.series)
                END AS identity_key,
                os.session_ordinal,
                os.classification AS session_classification,
                COUNT(si.symbol) AS active_identity_candidates,
                COUNT(si.symbol) FILTER (
                    WHERE c.isin IS NULL OR si.isin IS NULL OR si.isin = c.isin
                ) AS active_matching_identity_candidates,
                COALESCE(MAX(ip.identity_rows), 0) AS identity_evidence_rows,
                MAX(CASE WHEN dl.source_sha256 IS NOT NULL THEN 1 ELSE 0 END)
                    AS detailed_lineage_present,
                MAX(CASE WHEN al.symbol IS NOT NULL THEN 1 ELSE 0 END)
                    AS any_lineage_present,
                CASE WHEN
                    c.high_price < c.low_price OR
                    c.open_price > c.high_price OR
                    c.open_price < c.low_price OR
                    c.close_price > c.high_price OR
                    c.close_price < c.low_price OR
                    LEAST(c.open_price, c.high_price, c.low_price, c.close_price) < 0 OR
                    c.volume < 0 OR
                    LEAST(c.open_price, c.high_price, c.low_price, c.close_price) = 0
                THEN 1 ELSE 0 END AS invalid_candle
            FROM source.daily_candle c
            JOIN official_session os USING (trading_date)
            LEFT JOIN source.security_identity si
              ON si.exchange = c.exchange
             AND si.symbol = c.symbol
             AND si.series = c.series
             AND c.trading_date >= si.valid_from
             AND (si.valid_to IS NULL OR c.trading_date <= si.valid_to)
            LEFT JOIN identity_presence ip
              ON ip.exchange = c.exchange AND ip.isin = c.isin
            LEFT JOIN detailed_lineage dl
              ON dl.trading_date = c.trading_date
             AND dl.exchange = c.exchange
             AND dl.symbol = c.symbol
             AND dl.series = c.series
             AND dl.source_sha256 = c.source_sha256
            LEFT JOIN any_lineage al
              ON al.trading_date = c.trading_date
             AND al.exchange = c.exchange
             AND al.symbol = c.symbol
             AND al.series = c.series
            WHERE c.trading_date BETWEEN ? AND ?
            GROUP BY ALL
            """,
            [start_date, end_date],
        )
        connection.execute(
            """
            CREATE TEMP TABLE valid_observation AS
            SELECT DISTINCT identity_key, trading_date, session_ordinal
            FROM scoped_candle
            WHERE invalid_candle = 0 AND UPPER(series) = 'EQ'
            """
        )
        connection.execute(
            """
            CREATE TEMP TABLE ranked_observation AS
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY identity_key ORDER BY trading_date
            ) AS valid_history_count
            FROM valid_observation
            """
        )

    @staticmethod
    def _identity_checks(
        connection: duckdb.DuckDBPyConnection,
    ) -> _IdentityChecks:
        reuse_rows = connection.execute(
            """
            SELECT symbol, series, LIST_SORT(LIST(DISTINCT identity_key))
            FROM scoped_candle
            WHERE isin IS NOT NULL
            GROUP BY symbol, series
            HAVING COUNT(DISTINCT isin) > 1
            ORDER BY symbol, series
            """
        ).fetchall()
        symbol_reuse = frozenset(str(key) for row in reuse_rows for key in row[2])
        symbol_change_rows = connection.execute(
            """
            SELECT identity_key
            FROM scoped_candle
            GROUP BY identity_key
            HAVING COUNT(DISTINCT symbol) > 1
            ORDER BY identity_key
            """
        ).fetchall()
        symbol_change = frozenset(str(row[0]) for row in symbol_change_rows)
        supported_rows = connection.execute(
            """
            SELECT LOWER(exchange) || ':isin:' || UPPER(isin)
            FROM source.security_identity
            WHERE isin IS NOT NULL
            GROUP BY exchange, isin
            HAVING COUNT(DISTINCT symbol) > 1
            UNION
            SELECT LOWER(exchange) || ':isin:' || UPPER(isin)
            FROM source.corporate_action
            WHERE isin IS NOT NULL AND UPPER(action_type) = 'SYMBOL_CHANGE'
            ORDER BY 1
            """
        ).fetchall()
        supported_symbol_change = frozenset(str(row[0]) for row in supported_rows)
        overlap_rows = connection.execute(
            """
            SELECT DISTINCT LOWER(a.exchange) || ':isin:' || UPPER(a.isin)
            FROM source.security_identity a
            JOIN source.security_identity b
              ON a.exchange = b.exchange AND a.isin = b.isin
             AND (a.symbol, a.series, a.valid_from) <
                 (b.symbol, b.series, b.valid_from)
             AND COALESCE(a.valid_to, DATE '9999-12-31') >= b.valid_from
             AND COALESCE(b.valid_to, DATE '9999-12-31') >= a.valid_from
            WHERE a.isin IS NOT NULL
            ORDER BY 1
            """
        ).fetchall()
        identity_overlap = frozenset(str(row[0]) for row in overlap_rows)
        gap_rows = connection.execute(
            """
            WITH ordered AS (
                SELECT exchange, isin, valid_from, valid_to,
                       LAG(valid_to) OVER (
                           PARTITION BY exchange, isin ORDER BY valid_from
                       ) AS previous_to
                FROM source.security_identity
                WHERE isin IS NOT NULL
            )
            SELECT DISTINCT LOWER(exchange) || ':isin:' || UPPER(isin)
            FROM ordered
            WHERE previous_to IS NOT NULL AND valid_from > previous_to + 1
            ORDER BY 1
            """
        ).fetchall()
        identity_gap = frozenset(str(row[0]) for row in gap_rows)
        isin_conflict = frozenset(
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT identity_key
                FROM scoped_candle
                WHERE active_identity_candidates > 0
                  AND active_matching_identity_candidates = 0
                ORDER BY identity_key
                """
            ).fetchall()
        )
        outside_interval = frozenset(
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT identity_key
                FROM scoped_candle
                WHERE identity_evidence_rows > 0
                  AND active_identity_candidates = 0
                ORDER BY identity_key
                """
            ).fetchall()
        )
        lineage_disagreement = frozenset(
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT identity_key
                FROM scoped_candle
                WHERE any_lineage_present = 1
                  AND detailed_lineage_present = 0
                ORDER BY identity_key
                """
            ).fetchall()
        )
        return _IdentityChecks(
            symbol_reuse=symbol_reuse,
            symbol_change=symbol_change,
            supported_symbol_change=(supported_symbol_change - identity_overlap),
            identity_overlap=identity_overlap,
            identity_gap=identity_gap,
            isin_conflict=isin_conflict,
            outside_interval=outside_interval,
            lineage_disagreement=lineage_disagreement,
            symbol_reuse_cases=len(reuse_rows),
        )

    def _records(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        checks: _IdentityChecks,
        corporate_actions: tuple[CorporateActionRiskRecord, ...],
        snapshots: SnapshotAuditSummary,
    ) -> tuple[SecurityEligibilityRecord, ...]:
        rows = connection.execute(
            """
            WITH base AS (
                SELECT
                    identity_key,
                    MIN(exchange) AS exchange,
                    LIST_SORT(LIST(DISTINCT UPPER(symbol))) AS symbols,
                    LIST_SORT(LIST(DISTINCT UPPER(series))) AS series,
                    LIST_SORT(
                        LIST(DISTINCT UPPER(isin)) FILTER (WHERE isin IS NOT NULL)
                    ) AS isins,
                    MIN(trading_date) AS first_observed,
                    MAX(trading_date) AS last_observed,
                    COUNT(*) AS total_rows,
                    COUNT(DISTINCT trading_date) FILTER (
                        WHERE invalid_candle = 1 AND UPPER(series) = 'EQ'
                    ) AS invalid_sessions,
                    COUNT(*) - COUNT(DISTINCT (
                        trading_date, exchange, symbol, series
                    )) AS duplicate_sessions,
                    MAX(active_identity_candidates) AS active_candidates_max,
                    MIN(CASE
                        WHEN active_identity_candidates = 1
                         AND active_matching_identity_candidates = 1
                        THEN 1 ELSE 0
                    END) AS every_row_governed,
                    MAX(CASE WHEN isin IS NULL THEN 1 ELSE 0 END) AS missing_isin,
                    SUM(CASE WHEN source_sha256 IS NOT NULL THEN 1 ELSE 0 END)
                        AS source_hash_rows,
                    SUM(detailed_lineage_present) AS detailed_lineage_rows,
                    MAX(CASE WHEN UPPER(series) = 'EQ' THEN 1 ELSE 0 END)
                        AS supports_eq
                FROM scoped_candle
                GROUP BY identity_key
            ),
            ranked AS (
                SELECT
                    identity_key,
                    COUNT(*) AS valid_sessions,
                    MIN(trading_date) AS first_valid,
                    MAX(trading_date) AS last_valid,
                    MAX(CASE WHEN valid_history_count = 20 THEN trading_date END)
                        AS first_20,
                    MAX(CASE WHEN valid_history_count = 50 THEN trading_date END)
                        AS first_50,
                    MAX(CASE WHEN valid_history_count = 100 THEN trading_date END)
                        AS first_100,
                    MAX(CASE WHEN valid_history_count = 150 THEN trading_date END)
                        AS first_150,
                    MAX(CASE WHEN valid_history_count = 200 THEN trading_date END)
                        AS first_200,
                    MAX(CASE WHEN valid_history_count = 500 THEN trading_date END)
                        AS first_500,
                    MAX(CASE WHEN valid_history_count = 1000 THEN trading_date END)
                        AS first_1000,
                    COUNT(*) FILTER (
                        WHERE valid_history_count >= ?
                    ) AS eligible_days
                FROM ranked_observation
                GROUP BY identity_key
            ),
            continuity_source AS (
                SELECT *, session_ordinal - ROW_NUMBER() OVER (
                    PARTITION BY identity_key ORDER BY trading_date
                ) AS streak_group,
                session_ordinal - LAG(session_ordinal) OVER (
                    PARTITION BY identity_key ORDER BY trading_date
                ) - 1 AS missing_before
                FROM valid_observation
            ),
            streaks AS (
                SELECT identity_key, streak_group, COUNT(*) AS streak
                FROM continuity_source
                GROUP BY identity_key, streak_group
            ),
            continuity AS (
                SELECT c.identity_key,
                       COALESCE(MAX(s.streak), 0) AS longest_streak,
                       COALESCE(MAX(c.missing_before), 0) AS longest_gap,
                       COUNT(*) FILTER (WHERE c.missing_before > 0) AS gap_count,
                       COALESCE(SUM(c.missing_before) FILTER (
                           WHERE c.missing_before > 0
                       ), 0) AS missing_sessions
                FROM continuity_source c
                LEFT JOIN streaks s USING (identity_key, streak_group)
                GROUP BY c.identity_key
            ),
            identity_interval AS (
                SELECT
                    LOWER(exchange) || ':isin:' || UPPER(isin) AS identity_key,
                    GREATEST(
                        MIN(valid_from),
                        (SELECT MIN(trading_date) FROM official_session)
                    ) AS active_from,
                    LEAST(
                        CASE
                            WHEN COUNT(*) FILTER (WHERE valid_to IS NULL) > 0
                            THEN (SELECT MAX(trading_date) FROM official_session)
                            ELSE MAX(valid_to)
                        END,
                        (SELECT MAX(trading_date) FROM official_session)
                    ) AS active_to
                FROM source.security_identity
                WHERE isin IS NOT NULL
                GROUP BY exchange, isin
            ),
            expected AS (
                SELECT r.identity_key, COUNT(os.trading_date) AS expected_sessions
                FROM ranked r
                LEFT JOIN identity_interval ii USING (identity_key)
                JOIN official_session os
                  ON os.trading_date BETWEEN
                     COALESCE(ii.active_from, r.first_valid)
                     AND COALESCE(ii.active_to, r.last_valid)
                GROUP BY r.identity_key
            )
            SELECT
                b.*, COALESCE(r.valid_sessions, 0),
                r.first_20, r.first_50, r.first_100, r.first_150,
                r.first_200, r.first_500, r.first_1000,
                COALESCE(r.eligible_days, 0),
                COALESCE(e.expected_sessions, 0),
                COALESCE(c.longest_streak, 0),
                COALESCE(c.longest_gap, 0),
                COALESCE(c.gap_count, 0),
                COALESCE(c.missing_sessions, 0)
            FROM base b
            LEFT JOIN ranked r USING (identity_key)
            LEFT JOIN expected e USING (identity_key)
            LEFT JOIN continuity c USING (identity_key)
            ORDER BY b.identity_key
            """,
            [self.policy.minimum_history_sessions],
        ).fetchall()
        actions_by_key: dict[str, list[CorporateActionRiskRecord]] = defaultdict(list)
        for action in corporate_actions:
            actions_by_key[action.identity_key].append(action)
        records: list[SecurityEligibilityRecord] = []
        for row in rows:
            identity_key = str(row[0])
            symbols = tuple(str(item) for item in (row[2] or []))
            series = tuple(str(item) for item in (row[3] or []))
            isins = tuple(str(item) for item in (row[4] or []))
            valid_sessions = int(row[16])
            expected_sessions = int(row[25])
            missing_sessions = int(row[29])
            active_max = int(row[10])
            governed = bool(row[11]) and active_max == 1
            action_rows = actions_by_key.get(identity_key, [])
            action_severity = self._maximum_action_severity(action_rows)
            issues = self._issues(
                identity_key=identity_key,
                governed=governed,
                active_max=active_max,
                missing_isin=bool(row[12]),
                supports_eq=bool(row[15]),
                valid_sessions=valid_sessions,
                invalid_sessions=int(row[8]),
                missing_sessions=missing_sessions,
                expected_sessions=expected_sessions,
                source_hash_rows=int(row[13]),
                total_rows=int(row[7]),
                detailed_lineage_rows=int(row[14]),
                action_count=len(action_rows),
                action_severity=action_severity,
                checks=checks,
                snapshots=snapshots,
            )
            primary = self._primary_classification(issues)
            survivorship = (
                SurvivorshipRisk.UNKNOWN
                if not governed
                else (
                    SurvivorshipRisk.BLOCKING
                    if "FUTURE_IDENTITY_MAPPING_LEAKAGE" in issues
                    else SurvivorshipRisk.NONE
                )
            )
            records.append(
                SecurityEligibilityRecord(
                    identity_key=identity_key,
                    exchange=str(row[1]).upper(),
                    symbols=symbols,
                    series=series,
                    isins=isins,
                    identity_governed=governed,
                    active_identity_candidates_max=active_max,
                    first_observed_session=row[5],
                    last_observed_session=row[6],
                    total_candle_rows=int(row[7]),
                    valid_candle_sessions=valid_sessions,
                    invalid_candle_sessions=int(row[8]),
                    duplicate_sessions=int(row[9]),
                    expected_sessions=expected_sessions,
                    observed_sessions=valid_sessions,
                    explained_missing_sessions=0,
                    unexplained_missing_sessions=missing_sessions,
                    coverage_ratio=(
                        round(valid_sessions / expected_sessions, 8)
                        if expected_sessions
                        else 0.0
                    ),
                    longest_continuous_valid_session_streak=int(row[26]),
                    longest_unexplained_internal_gap=int(row[27]),
                    unexplained_internal_gap_count=int(row[28]),
                    first_20_session_date=row[17],
                    first_50_session_date=row[18],
                    first_100_session_date=row[19],
                    first_150_session_date=row[20],
                    first_200_session_date=row[21],
                    first_500_session_date=row[22],
                    first_1000_session_date=row[23],
                    replay_eligible_start_date=row[21],
                    replay_eligible_security_days=int(row[24]),
                    source_hash_rows=int(row[13]),
                    detailed_lineage_rows=int(row[14]),
                    snapshot_evidence_valid=(
                        not snapshots.missing_dates and not snapshots.invalid_dates
                    ),
                    corporate_action_count=len(action_rows),
                    corporate_action_severity=action_severity,
                    survivorship_risk=survivorship,
                    primary_classification=primary,
                    secondary_issue_codes=tuple(
                        issue for issue in issues if issue != primary.value
                    ),
                )
            )
        return tuple(records)

    def _issues(
        self,
        *,
        identity_key: str,
        governed: bool,
        active_max: int,
        missing_isin: bool,
        supports_eq: bool,
        valid_sessions: int,
        invalid_sessions: int,
        missing_sessions: int,
        expected_sessions: int,
        source_hash_rows: int,
        total_rows: int,
        detailed_lineage_rows: int,
        action_count: int,
        action_severity: CorporateActionSeverity,
        checks: _IdentityChecks,
        snapshots: SnapshotAuditSummary,
    ) -> tuple[str, ...]:
        issues: set[str] = set()
        if missing_isin:
            issues.add(ReplayReadinessClassification.IDENTITY_AMBIGUITY.value)
            issues.add("MISSING_ISIN")
        if active_max > 1:
            issues.add(ReplayReadinessClassification.IDENTITY_INTERVAL_OVERLAP.value)
            issues.add("MULTIPLE_ACTIVE_IDENTITIES")
        for values, classification in (
            (
                checks.symbol_reuse,
                ReplayReadinessClassification.SYMBOL_REUSE_CONFLICT,
            ),
            (
                checks.identity_overlap,
                ReplayReadinessClassification.IDENTITY_INTERVAL_OVERLAP,
            ),
            (
                checks.identity_gap,
                ReplayReadinessClassification.IDENTITY_INTERVAL_GAP,
            ),
            (checks.isin_conflict, ReplayReadinessClassification.ISIN_CONFLICT),
        ):
            if identity_key in values:
                issues.add(classification.value)
        if (
            identity_key in checks.symbol_change
            and identity_key not in checks.supported_symbol_change
        ):
            issues.add(ReplayReadinessClassification.SYMBOL_CHANGE_DISCONTINUITY.value)
        if invalid_sessions:
            issues.add(ReplayReadinessClassification.INVALID_CANDLE_CONTAMINATION.value)
        if not supports_eq:
            issues.add(ReplayReadinessClassification.UNSUPPORTED_SERIES.value)
        if valid_sessions < self.policy.minimum_history_sessions:
            issues.add(ReplayReadinessClassification.INSUFFICIENT_VALID_HISTORY.value)
        if expected_sessions and (
            missing_sessions > self.policy.maximum_unexplained_gap_sessions
            or valid_sessions / expected_sessions < self.policy.minimum_continuity_ratio
        ):
            issues.add(ReplayReadinessClassification.INTERNAL_CANDLE_GAPS.value)
            issues.add("UNEXPLAINED_INTERNAL_GAP")
        if not governed:
            issues.update(
                {
                    ReplayReadinessClassification.POINT_IN_TIME_UNIVERSE_MISSING.value,
                    ReplayReadinessClassification.LISTING_BOUNDARY_UNVERIFIED.value,
                    ReplayReadinessClassification.DELISTING_BOUNDARY_UNVERIFIED.value,
                    ReplayReadinessClassification.SUSPENSION_BOUNDARY_UNVERIFIED.value,
                    "IDENTITY_EVIDENCE_OBSERVED_ONLY",
                }
            )
        if identity_key in checks.outside_interval:
            issues.add("CANDLE_OUTSIDE_IDENTITY_INTERVAL")
            issues.add(ReplayReadinessClassification.SURVIVORSHIP_RISK.value)
        if source_hash_rows < total_rows:
            issues.add("MISSING_SOURCE_HASH")
            issues.add(ReplayReadinessClassification.SOURCE_LINEAGE_INCOMPLETE.value)
        if detailed_lineage_rows < total_rows:
            issues.add("LEGACY_DETAILED_INGESTION_LINEAGE_UNAVAILABLE")
            if self.policy.require_detailed_lineage_for_certification:
                issues.add(
                    ReplayReadinessClassification.SOURCE_LINEAGE_INCOMPLETE.value
                )
        if identity_key in checks.lineage_disagreement:
            issues.add("LINEAGE_CHECKSUM_DISAGREEMENT")
            issues.add(ReplayReadinessClassification.CONFLICTING_EVIDENCE.value)
        if action_count == 0:
            issues.add("CORPORATE_ACTION_EVIDENCE_MISSING")
        if action_severity in {
            CorporateActionSeverity.HIGH,
            CorporateActionSeverity.BLOCKING,
        }:
            issues.add(
                ReplayReadinessClassification.CORPORATE_ACTION_CONTAMINATION.value
            )
        if snapshots.missing_dates or snapshots.invalid_dates:
            issues.add(
                ReplayReadinessClassification.SNAPSHOT_EVIDENCE_INSUFFICIENT.value
            )
        return tuple(sorted(issues))

    @staticmethod
    def _primary_classification(
        issues: tuple[str, ...],
    ) -> ReplayReadinessClassification:
        values = set(issues)
        precedence = (
            ReplayReadinessClassification.CONFLICTING_EVIDENCE,
            ReplayReadinessClassification.ISIN_CONFLICT,
            ReplayReadinessClassification.IDENTITY_INTERVAL_OVERLAP,
            ReplayReadinessClassification.SYMBOL_REUSE_CONFLICT,
            ReplayReadinessClassification.IDENTITY_AMBIGUITY,
            ReplayReadinessClassification.SYMBOL_CHANGE_DISCONTINUITY,
            ReplayReadinessClassification.INVALID_CANDLE_CONTAMINATION,
            ReplayReadinessClassification.UNSUPPORTED_SERIES,
            ReplayReadinessClassification.INSUFFICIENT_VALID_HISTORY,
            ReplayReadinessClassification.POINT_IN_TIME_UNIVERSE_MISSING,
            ReplayReadinessClassification.INTERNAL_CANDLE_GAPS,
            ReplayReadinessClassification.SOURCE_LINEAGE_INCOMPLETE,
            ReplayReadinessClassification.CORPORATE_ACTION_CONTAMINATION,
            ReplayReadinessClassification.SURVIVORSHIP_RISK,
            ReplayReadinessClassification.SNAPSHOT_EVIDENCE_INSUFFICIENT,
            ReplayReadinessClassification.IDENTITY_INTERVAL_GAP,
            ReplayReadinessClassification.LISTING_BOUNDARY_UNVERIFIED,
            ReplayReadinessClassification.DELISTING_BOUNDARY_UNVERIFIED,
            ReplayReadinessClassification.SUSPENSION_BOUNDARY_UNVERIFIED,
        )
        for classification in precedence:
            if classification.value in values:
                return classification
        return ReplayReadinessClassification.REPLAY_READY

    def _corporate_actions(
        self,
        connection: duckdb.DuckDBPyConnection,
    ) -> tuple[CorporateActionRiskRecord, ...]:
        rows = connection.execute(
            """
            SELECT exchange, isin, symbol, action_type, ex_date,
                   ratio_numerator, ratio_denominator, source_sha256
            FROM source.corporate_action
            ORDER BY ex_date, exchange, symbol, action_type
            """
        ).fetchall()
        records: list[CorporateActionRiskRecord] = []
        for row in rows:
            exchange, isin, symbol, action_type, ex_date = row[:5]
            identity_key = (
                f"{str(exchange).lower()}:isin:{str(isin).upper()}"
                if isin
                else f"{str(exchange).lower()}:symbol:{str(symbol).upper()}:EQ"
            )
            prices = connection.execute(
                """
                SELECT
                    (SELECT close_price FROM scoped_candle
                     WHERE identity_key = ? AND trading_date < ?
                       AND UPPER(series) = 'EQ' AND invalid_candle = 0
                     ORDER BY trading_date DESC LIMIT 1),
                    (SELECT open_price FROM scoped_candle
                     WHERE identity_key = ? AND trading_date >= ?
                       AND UPPER(series) = 'EQ' AND invalid_candle = 0
                     ORDER BY trading_date LIMIT 1),
                    (SELECT close_price FROM scoped_candle
                     WHERE identity_key = ? AND trading_date >= ?
                       AND UPPER(series) = 'EQ' AND invalid_candle = 0
                     ORDER BY trading_date LIMIT 1)
                """,
                [identity_key, ex_date, identity_key, ex_date, identity_key, ex_date],
            ).fetchone()
            previous = float(prices[0]) if prices and prices[0] is not None else None
            next_open = float(prices[1]) if prices and prices[1] is not None else None
            next_close = float(prices[2]) if prices and prices[2] is not None else None
            discontinuity = (
                next_open / previous - 1 if previous and next_open is not None else None
            )
            numerator = float(row[5]) if row[5] is not None else None
            denominator = float(row[6]) if row[6] is not None else None
            factor = None
            if numerator is not None and numerator != 0.0 and denominator is not None:
                factor = denominator / numerator
            severity = self._action_severity(
                action_type=str(action_type),
                discontinuity=discontinuity,
                factor=factor,
            )
            risks = (
                (
                    "FALSE_BREAKOUT",
                    "FALSE_BREAKDOWN",
                    "FALSE_VOLATILITY_SPIKE",
                    "FALSE_RETURN",
                    "FALSE_STOP_OR_TARGET",
                )
                if severity
                in {
                    CorporateActionSeverity.HIGH,
                    CorporateActionSeverity.BLOCKING,
                }
                else ()
            )
            records.append(
                CorporateActionRiskRecord(
                    identity_key=identity_key,
                    symbol=str(symbol).upper(),
                    isin=str(isin).upper() if isin else None,
                    event_date=ex_date,
                    event_type=str(action_type).upper(),
                    source_sha256=str(row[7]) if row[7] else None,
                    previous_valid_close=previous,
                    next_valid_open=next_open,
                    next_valid_close=next_close,
                    raw_overnight_discontinuity=(
                        round(discontinuity, 8) if discontinuity is not None else None
                    ),
                    expected_adjustment_factor=factor,
                    adjusted_canonical_prices_available=False,
                    benchmark_consumes_raw_prices=True,
                    false_signal_risks=risks,
                    severity=severity,
                )
            )
        return tuple(records)

    @staticmethod
    def _action_severity(
        *,
        action_type: str,
        discontinuity: float | None,
        factor: float | None,
    ) -> CorporateActionSeverity:
        kind = action_type.upper()
        material = {"SPLIT", "BONUS", "MERGER", "DEMERGER", "CAPITAL_REDUCTION"}
        if discontinuity is None:
            return CorporateActionSeverity.UNKNOWN
        magnitude = abs(discontinuity)
        if kind in material and magnitude >= 0.20:
            return CorporateActionSeverity.BLOCKING
        if kind in material and factor is None:
            return CorporateActionSeverity.HIGH
        if magnitude >= 0.20:
            return CorporateActionSeverity.HIGH
        if magnitude >= 0.10:
            return CorporateActionSeverity.MODERATE
        if magnitude >= 0.05:
            return CorporateActionSeverity.LOW
        return CorporateActionSeverity.NONE

    @staticmethod
    def _maximum_action_severity(
        records: Sequence[CorporateActionRiskRecord],
    ) -> CorporateActionSeverity:
        order = {
            CorporateActionSeverity.NONE: 0,
            CorporateActionSeverity.LOW: 1,
            CorporateActionSeverity.MODERATE: 2,
            CorporateActionSeverity.UNKNOWN: 3,
            CorporateActionSeverity.HIGH: 4,
            CorporateActionSeverity.BLOCKING: 5,
        }
        return max(
            (record.severity for record in records),
            key=order.__getitem__,
            default=CorporateActionSeverity.UNKNOWN,
        )

    def _snapshot_audit(
        self,
        sessions: tuple[tuple[date, str], ...],
    ) -> SnapshotAuditSummary:
        missing: list[date] = []
        invalid: list[date] = []
        inventory = hashlib.sha256()
        present = 0
        valid = 0
        for trading_date, _ in sessions:
            path = self.snapshots.path_for(trading_date, exchange="nse")
            if not path.is_file():
                missing.append(trading_date)
                continue
            present += 1
            file_bytes = path.read_bytes()
            relative = path.relative_to(self.snapshot_root).as_posix()
            inventory.update(relative.encode("utf-8"))
            inventory.update(b"\0")
            inventory.update(hashlib.sha256(file_bytes).digest())
            try:
                snapshot = self.snapshots.load(trading_date, exchange="nse")
                verification = self.snapshots.verify(snapshot)
                canonical = self.snapshots.build(
                    trading_date,
                    generated_at=datetime(2000, 1, 1, tzinfo=UTC),
                    exchange="nse",
                )
                matching = (
                    snapshot.metadata.trading_date == trading_date
                    and snapshot.metadata.exchange.lower() == "nse"
                    and snapshot.metadata.symbol_count
                    == canonical.metadata.symbol_count
                    and snapshot.candles == canonical.candles
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                matching = False
                verification = None
            if verification is not None and verification.valid and matching:
                valid += 1
            else:
                invalid.append(trading_date)
        return SnapshotAuditSummary(
            expected_dates=len(sessions),
            present_dates=present,
            valid_dates=valid,
            missing_dates=tuple(missing),
            invalid_dates=tuple(invalid),
            inventory_sha256=inventory.hexdigest(),
        )

    def _baseline(self, output: Path) -> BaselineBenchmarkSummary:
        eligibility = self._one_csv(output / "decision_eligibility.csv")
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        rejections = tuple(
            (row["reason_code"], int(row["rejected_candidates"]))
            for row in self._csv(output / "top_rejection_reasons.csv")
        )
        trades = len(self._csv(output / "trade_log.csv"))
        return BaselineBenchmarkSummary(
            benchmark_output=str(output),
            run_id=str(manifest["run_id"]),
            repository_commit=self._repository_commit(),
            database_sha256=self._sha256(self.database_path),
            snapshot_inventory_sha256=self._snapshot_inventory_digest(),
            sessions=int(eligibility["replay_sessions"]),
            eligible_securities=int(eligibility["eligible_securities"]),
            eligible_security_days=int(eligibility["eligible_security_days"]),
            technical_candidates=int(eligibility["raw_technical_candidates"]),
            buy_candidates=self._signal_count(output, "BUY"),
            strong_buy_candidates=self._signal_count(output, "STRONG_BUY"),
            institutional_approvals=int(eligibility["institutional_approvals"]),
            trades=trades,
            rejection_reasons=rejections,
        )

    def _snapshot_inventory_digest(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.snapshot_root.rglob("*.json")):
            relative = path.relative_to(self.snapshot_root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()

    @staticmethod
    def _repository_commit() -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _csv(path: Path) -> tuple[dict[str, str], ...]:
        with path.open(newline="", encoding="utf-8") as stream:
            return tuple(csv.DictReader(stream))

    @classmethod
    def _one_csv(cls, path: Path) -> dict[str, str]:
        rows = cls._csv(path)
        if len(rows) != 1:
            raise ValueError(f"expected one benchmark row in {path}")
        return rows[0]

    @classmethod
    def _signal_count(cls, output: Path, signal: str) -> int:
        return sum(
            row["final_signal"].upper().replace(" ", "_") == signal
            for row in cls._csv(output / "approval_statistics.csv")
        )

    @staticmethod
    def _population(
        connection: duckdb.DuckDBPyConnection,
        records: tuple[SecurityEligibilityRecord, ...],
        checks: _IdentityChecks,
    ) -> PopulationSummary:
        raw = connection.execute(
            """
            SELECT COUNT(DISTINCT symbol),
                   COUNT(DISTINCT (symbol, series)),
                   COUNT(DISTINCT isin) FILTER (WHERE isin IS NOT NULL)
            FROM scoped_candle
            """
        ).fetchone()
        if raw is None:
            raise ValueError("population aggregate returned no row")
        supported_count = len(checks.supported_symbol_change)
        change_count = len(checks.symbol_change)
        return PopulationSummary(
            distinct_raw_symbols=int(raw[0]),
            distinct_symbol_series_pairs=int(raw[1]),
            distinct_isins=int(raw[2]),
            governed_identities=sum(record.identity_governed for record in records),
            unresolved_identities=sum(not record.ready for record in records),
            ambiguous_identities=sum(
                record.primary_classification
                is ReplayReadinessClassification.IDENTITY_AMBIGUITY
                for record in records
            ),
            symbol_reuse_cases=checks.symbol_reuse_cases,
            supported_symbol_changes=supported_count,
            unsupported_symbol_changes=max(change_count - supported_count, 0),
            identity_overlaps=len(checks.identity_overlap),
            identity_gaps=len(checks.identity_gap),
        )

    @staticmethod
    def _depth(records: tuple[SecurityEligibilityRecord, ...]) -> DepthSummary:
        values = sorted(record.valid_candle_sessions for record in records)
        if not values:
            return DepthSummary(*(0 for _ in range(11)), *(0.0 for _ in range(8)))
        count = len(values)
        return DepthSummary(
            identity_count=count,
            at_least_20=sum(value >= 20 for value in values),
            at_least_50=sum(value >= 50 for value in values),
            at_least_100=sum(value >= 100 for value in values),
            at_least_150=sum(value >= 150 for value in values),
            at_least_200=sum(value >= 200 for value in values),
            at_least_500=sum(value >= 500 for value in values),
            at_least_1000=sum(value >= 1000 for value in values),
            at_least_2000=sum(value >= 2000 for value in values),
            minimum=values[0],
            maximum=values[-1],
            mean=round(sum(values) / count, 6),
            median=ReplayEligibilityIntegrityEngine._percentile(values, 0.50),
            p10=ReplayEligibilityIntegrityEngine._percentile(values, 0.10),
            p25=ReplayEligibilityIntegrityEngine._percentile(values, 0.25),
            p75=ReplayEligibilityIntegrityEngine._percentile(values, 0.75),
            p90=ReplayEligibilityIntegrityEngine._percentile(values, 0.90),
            p95=ReplayEligibilityIntegrityEngine._percentile(values, 0.95),
            p99=ReplayEligibilityIntegrityEngine._percentile(values, 0.99),
        )

    @staticmethod
    def _percentile(values: Sequence[int], fraction: float) -> float:
        if len(values) == 1:
            return float(values[0])
        position = (len(values) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        weight = position - lower
        return round(values[lower] * (1 - weight) + values[upper] * weight, 6)

    @staticmethod
    def _continuity(
        records: tuple[SecurityEligibilityRecord, ...],
    ) -> ContinuitySummary:
        return ContinuitySummary(
            expected_security_sessions=sum(
                record.expected_sessions for record in records
            ),
            observed_security_sessions=sum(
                record.observed_sessions for record in records
            ),
            valid_security_sessions=sum(
                record.valid_candle_sessions for record in records
            ),
            invalid_security_sessions=sum(
                record.invalid_candle_sessions for record in records
            ),
            explained_missing_security_sessions=sum(
                record.explained_missing_sessions for record in records
            ),
            unexplained_missing_security_sessions=sum(
                record.unexplained_missing_sessions for record in records
            ),
            identities_with_zero_unexplained_gaps=sum(
                record.unexplained_missing_sessions == 0 for record in records
            ),
            identities_with_unexplained_gaps=sum(
                record.unexplained_missing_sessions > 0 for record in records
            ),
        )

    @staticmethod
    def _candle_quality(
        connection: duckdb.DuckDBPyConnection,
        snapshots: SnapshotAuditSummary,
    ) -> CandleQualitySummary:
        row = connection.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE high_price < low_price),
                COUNT(*) FILTER (WHERE open_price > high_price),
                COUNT(*) FILTER (WHERE open_price < low_price),
                COUNT(*) FILTER (WHERE close_price > high_price),
                COUNT(*) FILTER (WHERE close_price < low_price),
                COUNT(*) FILTER (WHERE LEAST(
                    open_price, high_price, low_price, close_price
                ) < 0),
                COUNT(*) FILTER (WHERE volume < 0),
                COUNT(*) FILTER (WHERE LEAST(
                    open_price, high_price, low_price, close_price
                ) = 0),
                COUNT(*) - COUNT(DISTINCT (
                    trading_date, exchange, symbol, series
                )),
                COUNT(*) FILTER (WHERE LOWER(exchange) != 'nse'),
                COUNT(*) FILTER (WHERE UPPER(series) != 'EQ'),
                COUNT(*) FILTER (
                    WHERE UPPER(series) != 'EQ' AND invalid_candle = 1
                ),
                COUNT(*) FILTER (WHERE source_sha256 IS NULL),
                COUNT(*) FILTER (WHERE detailed_lineage_present = 0),
                COUNT(*) FILTER (
                    WHERE any_lineage_present = 1
                      AND detailed_lineage_present = 0
                )
            FROM scoped_candle
            """
        ).fetchone()
        conflicting = connection.execute(
            """
            SELECT COALESCE(SUM(rows - 1), 0)
            FROM (
                SELECT identity_key, trading_date, series, COUNT(*) AS rows
                FROM scoped_candle
                GROUP BY identity_key, trading_date, series
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()
        if row is None or conflicting is None:
            raise ValueError("candle-quality aggregate returned no row")
        return CandleQualitySummary(
            high_below_low=int(row[0]),
            open_above_high=int(row[1]),
            open_below_low=int(row[2]),
            close_above_high=int(row[3]),
            close_below_low=int(row[4]),
            negative_price=int(row[5]),
            negative_volume=int(row[6]),
            invalid_zero_price=int(row[7]),
            duplicate_rows=int(row[8]),
            conflicting_rows=int(conflicting[0]),
            unsupported_exchange_rows=int(row[9]),
            unsupported_series_rows=int(row[10]),
            unsupported_series_ohlc_exceptions=int(row[11]),
            missing_source_hash_rows=int(row[12]),
            missing_detailed_lineage_rows=int(row[13]),
            lineage_checksum_disagreement_rows=int(row[14]),
            snapshot_mismatch_dates=len(snapshots.invalid_dates),
        )

    @staticmethod
    def _register_certifications(
        connection: duckdb.DuckDBPyConnection,
        records: tuple[SecurityEligibilityRecord, ...],
    ) -> None:
        connection.execute(
            """
            CREATE TEMP TABLE identity_certification (
                identity_key VARCHAR PRIMARY KEY,
                classification VARCHAR NOT NULL,
                identity_governed BOOLEAN NOT NULL,
                continuity_acceptable BOOLEAN NOT NULL,
                lineage_acceptable BOOLEAN NOT NULL,
                corporate_action_acceptable BOOLEAN NOT NULL,
                point_in_time_supported BOOLEAN NOT NULL,
                replay_ready BOOLEAN NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO identity_certification VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    record.identity_key,
                    record.primary_classification.value,
                    record.identity_governed,
                    record.unexplained_missing_sessions == 0,
                    record.detailed_lineage_rows == record.total_candle_rows,
                    record.corporate_action_severity
                    not in {
                        CorporateActionSeverity.HIGH,
                        CorporateActionSeverity.BLOCKING,
                        CorporateActionSeverity.UNKNOWN,
                    },
                    record.identity_governed,
                    record.ready,
                )
                for record in records
            ],
        )

    def _funnel(
        self,
        connection: duckdb.DuckDBPyConnection,
        snapshots: SnapshotAuditSummary,
    ) -> tuple[EligibilityFunnelRecord, ...]:
        valid_snapshot_dates = snapshots.valid_dates == snapshots.expected_dates
        rows = connection.execute(
            """
            WITH observed AS (
                SELECT trading_date,
                       COUNT(DISTINCT symbol) AS canonical_observed,
                       COUNT(DISTINCT symbol) FILTER (
                           WHERE UPPER(series) = 'EQ'
                       ) AS supported,
                       COUNT(DISTINCT identity_key) FILTER (
                           WHERE active_identity_candidates = 1
                             AND active_matching_identity_candidates = 1
                       ) AS identity_resolved,
                       COUNT(DISTINCT identity_key) FILTER (
                           WHERE active_identity_candidates = 1
                       ) AS inside_interval,
                       COUNT(DISTINCT identity_key) FILTER (
                           WHERE invalid_candle = 0 AND UPPER(series) = 'EQ'
                       ) AS valid_candles
                FROM scoped_candle
                GROUP BY trading_date
            ),
            history AS (
                SELECT trading_date,
                       COUNT(*) FILTER (WHERE valid_history_count >= ?) AS depth
                FROM ranked_observation
                GROUP BY trading_date
            ),
            certified AS (
                SELECT r.trading_date,
                       COUNT(*) FILTER (WHERE i.continuity_acceptable) AS continuity,
                       COUNT(*) FILTER (WHERE i.lineage_acceptable) AS lineage,
                       COUNT(*) FILTER (
                           WHERE i.corporate_action_acceptable
                       ) AS corporate_actions,
                       COUNT(*) FILTER (
                           WHERE i.point_in_time_supported
                       ) AS point_in_time,
                       COUNT(*) FILTER (WHERE i.replay_ready) AS replay_ready
                FROM ranked_observation r
                JOIN identity_certification i USING (identity_key)
                WHERE r.valid_history_count >= ?
                GROUP BY r.trading_date
            )
            SELECT os.trading_date,
                   COALESCE(o.canonical_observed, 0),
                   COALESCE(o.supported, 0),
                   COALESCE(o.identity_resolved, 0),
                   COALESCE(o.inside_interval, 0),
                   COALESCE(o.valid_candles, 0),
                   COALESCE(h.depth, 0),
                   COALESCE(c.continuity, 0),
                   COALESCE(c.lineage, 0),
                   COALESCE(c.corporate_actions, 0),
                   COALESCE(c.point_in_time, 0),
                   COALESCE(c.replay_ready, 0)
            FROM official_session os
            LEFT JOIN observed o USING (trading_date)
            LEFT JOIN history h USING (trading_date)
            LEFT JOIN certified c USING (trading_date)
            ORDER BY os.trading_date
            """,
            [self.policy.minimum_history_sessions] * 2,
        ).fetchall()
        return tuple(
            EligibilityFunnelRecord(
                trading_date=row[0],
                canonical_securities_observed=int(row[1]),
                supported_series=int(row[2]),
                identity_resolved=int(row[3]),
                inside_governed_active_interval=int(row[4]),
                valid_candle_evidence=int(row[5]),
                minimum_history_met=int(row[6]),
                acceptable_continuity=int(row[7]),
                acceptable_lineage=int(row[8]),
                acceptable_corporate_action_risk=int(row[9]),
                snapshot_available_and_verified=(
                    int(row[6]) if valid_snapshot_dates else 0
                ),
                point_in_time_universe_supported=int(row[10]),
                final_replay_ready_population=int(row[11]),
            )
            for row in rows
        )

    def _candidate_exposure(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        benchmark_output: Path,
        record_by_key: dict[str, SecurityEligibilityRecord],
    ) -> tuple[CandidateExposureRecord, ...]:
        approvals = self._csv(benchmark_output / "approval_statistics.csv")
        connection.execute(
            """
            CREATE TEMP TABLE benchmark_candidate (
                trading_date DATE NOT NULL,
                symbol VARCHAR NOT NULL,
                final_signal VARCHAR NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO benchmark_candidate VALUES (?, ?, ?)",
            [
                (
                    date.fromisoformat(row["observed_on"]),
                    row["symbol"].upper(),
                    row["final_signal"].upper().replace(" ", "_"),
                )
                for row in approvals
            ],
        )
        rows = connection.execute(
            """
            SELECT c.trading_date, c.symbol, c.final_signal, s.identity_key
            FROM benchmark_candidate c
            LEFT JOIN scoped_candle s
              ON s.trading_date = c.trading_date
             AND UPPER(s.symbol) = c.symbol
             AND UPPER(s.series) = 'EQ'
            ORDER BY c.trading_date, c.symbol
            """
        ).fetchall()
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        flags: dict[str, tuple[bool, bool, bool, bool]] = {}
        for _, _, signal, identity_key_raw in rows:
            record = record_by_key.get(str(identity_key_raw))
            classification = (
                record.primary_classification.value
                if record is not None
                else ReplayReadinessClassification.IDENTITY_AMBIGUITY.value
            )
            counts[classification]["technical"] += 1
            if signal == "BUY":
                counts[classification]["buy"] += 1
            if signal == "STRONG_BUY":
                counts[classification]["strong_buy"] += 1
            flags[classification] = (
                record is None or not record.ready,
                record is None
                or record.primary_classification in _BLOCKING_CLASSIFICATIONS,
                record is None or record.corporate_action_count == 0,
                record is None or record.survivorship_risk is not SurvivorshipRisk.NONE,
            )
        return tuple(
            CandidateExposureRecord(
                certification_class=classification,
                technical_candidates=counter["technical"],
                buy_candidates=counter["buy"],
                strong_buy_candidates=counter["strong_buy"],
                unresolved_issues=flags[classification][0],
                blocking_contamination=flags[classification][1],
                corporate_action_evidence_missing=flags[classification][2],
                survivorship_risk=flags[classification][3],
            )
            for classification, counter in sorted(counts.items())
        )

    @staticmethod
    def _annual_coverage(
        connection: duckdb.DuckDBPyConnection,
    ) -> tuple[tuple[int, float], ...]:
        rows = connection.execute(
            """
            WITH span AS (
                SELECT identity_key, MIN(trading_date) AS first_date,
                       MAX(trading_date) AS last_date
                FROM valid_observation
                GROUP BY identity_key
            ),
            expected AS (
                SELECT YEAR(os.trading_date) AS year, COUNT(*) AS sessions
                FROM span s
                JOIN official_session os
                  ON os.trading_date BETWEEN s.first_date AND s.last_date
                GROUP BY year
            ),
            observed AS (
                SELECT YEAR(trading_date) AS year, COUNT(*) AS sessions
                FROM valid_observation
                GROUP BY year
            )
            SELECT e.year, o.sessions / e.sessions::DOUBLE
            FROM expected e JOIN observed o USING (year)
            ORDER BY e.year
            """
        ).fetchall()
        return tuple((int(row[0]), round(float(row[1]), 8)) for row in rows)

    @staticmethod
    def _reconciliation(
        baseline: BaselineBenchmarkSummary,
        records: tuple[SecurityEligibilityRecord, ...],
    ) -> EligibilityReconciliation:
        with_200_raw = sum(record.total_candle_rows >= 200 for record in records)
        with_200_valid = sum(record.valid_candle_sessions >= 200 for record in records)
        passing_identity = sum(
            record.identity_governed
            and record.primary_classification
            not in {
                ReplayReadinessClassification.IDENTITY_AMBIGUITY,
                ReplayReadinessClassification.SYMBOL_REUSE_CONFLICT,
                ReplayReadinessClassification.ISIN_CONFLICT,
                ReplayReadinessClassification.IDENTITY_INTERVAL_OVERLAP,
            }
            for record in records
        )
        passing_continuity = sum(
            record.unexplained_missing_sessions == 0 for record in records
        )
        passing_lineage = sum(
            record.detailed_lineage_rows == record.total_candle_rows
            for record in records
        )
        passing_actions = sum(
            record.corporate_action_severity
            not in {
                CorporateActionSeverity.UNKNOWN,
                CorporateActionSeverity.HIGH,
                CorporateActionSeverity.BLOCKING,
            }
            for record in records
        )
        ready = tuple(record for record in records if record.ready)
        ready_days = sum(record.replay_eligible_security_days for record in ready)
        return EligibilityReconciliation(
            benchmark_eligible_securities=baseline.eligible_securities,
            benchmark_eligible_security_days=baseline.eligible_security_days,
            identities_with_200_raw_rows=with_200_raw,
            identities_with_200_valid_sessions=with_200_valid,
            identities_passing_identity=passing_identity,
            identities_passing_continuity=passing_continuity,
            identities_passing_lineage=passing_lineage,
            identities_passing_corporate_actions=passing_actions,
            final_replay_ready_identities=len(ready),
            final_replay_ready_security_days=ready_days,
            eligible_security_discrepancy=len(ready) - baseline.eligible_securities,
            eligible_security_day_discrepancy=(
                ready_days - baseline.eligible_security_days
            ),
        )

    def _certification(
        self,
        records: tuple[SecurityEligibilityRecord, ...],
        snapshots: SnapshotAuditSummary,
    ) -> CertificationSummary:
        blockers: list[CertificationState] = []
        if any(
            record.primary_classification
            in {
                ReplayReadinessClassification.CONFLICTING_EVIDENCE,
                ReplayReadinessClassification.ISIN_CONFLICT,
            }
            for record in records
        ):
            blockers.append(CertificationState.BLOCKED_CONFLICTING_EVIDENCE)
        if any(not record.identity_governed for record in records):
            blockers.extend(
                [
                    CertificationState.BLOCKED_POINT_IN_TIME_UNIVERSE,
                    CertificationState.BLOCKED_IDENTITY_INTEGRITY,
                    CertificationState.BLOCKED_SURVIVORSHIP_RISK,
                ]
            )
        if any(record.unexplained_missing_sessions for record in records):
            blockers.append(CertificationState.BLOCKED_CONTINUITY_INTEGRITY)
        if self.policy.require_detailed_lineage_for_certification and any(
            record.detailed_lineage_rows < record.total_candle_rows
            for record in records
        ):
            blockers.append(CertificationState.BLOCKED_SOURCE_LINEAGE)
        if self.policy.require_corporate_action_evidence and any(
            record.corporate_action_count == 0 for record in records
        ):
            blockers.append(CertificationState.BLOCKED_CORPORATE_ACTION_RISK)
        if snapshots.missing_dates or snapshots.invalid_dates:
            blockers.append(CertificationState.INSUFFICIENT_EVIDENCE)
        blockers = list(dict.fromkeys(blockers))
        ready = sum(record.ready for record in records)
        if blockers:
            primary = blockers[0]
        elif ready == len(records) and records:
            primary = CertificationState.REPLAY_ELIGIBILITY_CERTIFIED
        elif ready:
            primary = CertificationState.PARTIALLY_CERTIFIED
        else:
            primary = CertificationState.INSUFFICIENT_EVIDENCE
        rationale = (
            f"{ready} of {len(records)} observed identities meet every configured "
            "HTR-008 diagnostic certification gate. Benchmark eligibility remains "
            "unchanged and is not treated as certification."
        )
        return CertificationSummary(
            primary_state=primary,
            secondary_blockers=tuple(
                blocker for blocker in blockers if blocker is not primary
            ),
            rationale=rationale,
        )

    @staticmethod
    def _filter_records(
        records: tuple[SecurityEligibilityRecord, ...],
        *,
        symbols: tuple[str, ...],
        isins: tuple[str, ...],
        years: tuple[int, ...],
        classifications: tuple[ReplayReadinessClassification, ...],
        issue_codes: tuple[str, ...],
        only_not_ready: bool,
    ) -> tuple[SecurityEligibilityRecord, ...]:
        symbol_set = {value.strip().upper() for value in symbols}
        isin_set = {value.strip().upper() for value in isins}
        year_set = set(years)
        classification_set = set(classifications)
        issue_set = {value.strip().upper() for value in issue_codes}

        def included(record: SecurityEligibilityRecord) -> bool:
            if symbol_set and not symbol_set.intersection(record.symbols):
                return False
            if isin_set and not isin_set.intersection(record.isins):
                return False
            if year_set and not any(
                record.first_observed_session.year
                <= year
                <= record.last_observed_session.year
                for year in year_set
            ):
                return False
            if (
                classification_set
                and record.primary_classification not in classification_set
            ):
                return False
            record_issues = {item.upper() for item in record.secondary_issue_codes}
            record_issues.add(record.primary_classification.value)
            if issue_set and not issue_set.intersection(record_issues):
                return False
            return not only_not_ready or not record.ready

        return tuple(record for record in records if included(record))


__all__ = ["ReplayEligibilityIntegrityEngine"]
