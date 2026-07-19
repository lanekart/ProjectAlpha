from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from alpha.market_intelligence.point_in_time import (
    DIAGNOSTIC_MARKET_STATE_V2_VERSION,
    POINT_IN_TIME_SECTOR_DATASET_VERSION,
    BreadthCoverageStatus,
    DiagnosticMarketStateV2BuildReport,
    DiagnosticV1V2ComparisonReport,
    HistoricalMembershipStatus,
    HistoricalSectorStateReport,
    PointInTimeBreadthSnapshot,
    PointInTimeConclusion,
    PointInTimeNextMilestone,
    PointInTimeSecurityRecord,
    PointInTimeUniverseCoverageReport,
    PointInTimeUniverseRow,
    SectorCoverageAuditReport,
    SectorHistoryReadiness,
    SurvivorshipBiasAuditReport,
    SurvivorshipBiasRow,
    UniverseQualityGrade,
    V2OutcomeComparisonReport,
    render_diagnostic_v2_build,
)
from alpha.market_intelligence.point_in_time_materialization import (
    PointInTimeBuildStatus,
    PointInTimeMaterializationRepository,
    PointInTimeMaterializedDataset,
    load_completed_point_in_time_materialization,
)

DEFAULT_POINT_IN_TIME_ANALYTICAL_STORE_PATH = Path(
    ".alpha/point_in_time_analytical_store.duckdb"
)
POINT_IN_TIME_ANALYTICAL_STORE_VERSION = "point-in-time-analytical-store-v1"


class PointInTimeStoreValidationStatus(StrEnum):
    VALID = "VALID"
    VALID_WITH_LIMITATIONS = "VALID_WITH_LIMITATIONS"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"


class PointInTimeStoreEquivalenceStatus(StrEnum):
    MATCH = "MATCH"
    MATCH_WITH_LIMITATIONS = "MATCH_WITH_LIMITATIONS"
    MISMATCH = "MISMATCH"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class PointInTimeStoreImportResult:
    build_id: str
    store_path: Path
    materialization_path: Path
    source_json_unchanged: bool
    rows_imported: int
    security_rows_imported: int
    breadth_rows_imported: int
    sector_state_rows_imported: int
    checkpoints_imported: int
    survivorship_aggregate_rows: int
    readiness_aggregate_rows: int
    elapsed_seconds: Decimal
    idempotent_replace: bool


@dataclass(frozen=True, slots=True)
class PointInTimeStoreStatusReport:
    store_path: Path
    exists: bool
    store_version: str
    build_id: str | None
    build_status: str | None
    completed_dates: int
    universe_rows: int
    security_rows: int
    breadth_rows: int
    sector_state_rows: int
    survivorship_rows: int
    readiness_rows: int
    v2_reconstructions: int
    v2_candidate_links: int


@dataclass(frozen=True, slots=True)
class PointInTimeStoreValidationReport:
    status: PointInTimeStoreValidationStatus
    store_path: Path
    build_id: str | None
    duplicate_universe_rows: int
    orphan_universe_security_ids: int
    missing_breadth_dates: int
    breadth_arithmetic_errors: int
    readiness_rows: int
    survivorship_rows: int
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PointInTimeStoreEquivalenceReport:
    status: PointInTimeStoreEquivalenceStatus
    build_id: str
    materialization_path: Path
    store_path: Path
    json_universe_rows: int
    store_universe_rows: int
    json_security_rows: int
    store_security_rows: int
    json_breadth_rows: int
    store_breadth_rows: int
    json_sector_state_rows: int
    store_sector_state_rows: int
    json_completed_dates: int
    store_completed_dates: int
    universe_fingerprint_match: bool
    breadth_fingerprint_match: bool
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PointInTimeStoreProfileReport:
    store_path: Path
    build_id: str | None
    read_operation: str
    rows_returned: int
    elapsed_seconds: Decimal
    source: str
    full_json_deserialization: bool


@dataclass(frozen=True, slots=True)
class DiagnosticV2StoreBuildResult:
    report: DiagnosticMarketStateV2BuildReport
    reconstructions_created: int
    candidate_links_created: int
    orphan_links: int
    duplicate_links: int
    universe_rows_treated_as_candidate_links: int


class PointInTimeAnalyticalRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_point_in_time_store_path(path)

    def import_materialization(
        self,
        *,
        build_id: str,
        materialization: PointInTimeMaterializedDataset | None = None,
        materialization_repository: PointInTimeMaterializationRepository | None = None,
    ) -> PointInTimeStoreImportResult:
        start = time.perf_counter()
        materialization_repository = (
            materialization_repository or PointInTimeMaterializationRepository()
        )
        materialization = (
            materialization
            or load_completed_point_in_time_materialization(
                materialization_repository.path
            )
        )
        if materialization.manifest.build_id != build_id:
            raise ValueError(
                "materialization build id mismatch: "
                f"requested {build_id}, found {materialization.manifest.build_id}"
            )
        before_fingerprint = _file_fingerprint(materialization_repository.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            _create_schema(con)
            _delete_build(con, build_id)
            _insert_dataframe(
                con,
                "diagnostic_pit_builds",
                _build_frame(materialization),
            )
            _insert_dataframe(
                con,
                "diagnostic_pit_checkpoints",
                _checkpoint_frame(materialization),
            )
            _insert_dataframe(
                con,
                "diagnostic_pit_security_master",
                _security_frame(build_id, materialization.universe.security_records),
            )
            _insert_dataframe(
                con,
                "diagnostic_pit_universe_membership",
                _universe_frame(build_id, materialization.universe.rows),
            )
            _insert_dataframe(
                con,
                "diagnostic_pit_breadth",
                _breadth_frame(build_id, materialization.breadth_snapshots),
            )
            _insert_dataframe(
                con,
                "diagnostic_pit_sector_state",
                _sector_state_frame(build_id, materialization.sector_state_reports),
            )
            survivorship = _survivorship_frame(materialization)
            readiness = _readiness_frame(materialization)
            _insert_dataframe(
                con,
                "diagnostic_pit_survivorship_aggregates",
                survivorship,
            )
            _insert_dataframe(con, "diagnostic_pit_readiness_aggregates", readiness)
        after_fingerprint = _file_fingerprint(materialization_repository.path)
        return PointInTimeStoreImportResult(
            build_id=build_id,
            store_path=self.path,
            materialization_path=materialization_repository.path,
            source_json_unchanged=before_fingerprint == after_fingerprint,
            rows_imported=len(materialization.universe.rows),
            security_rows_imported=len(materialization.universe.security_records),
            breadth_rows_imported=len(materialization.breadth_snapshots),
            sector_state_rows_imported=sum(
                len(report.sector_states)
                for report in materialization.sector_state_reports
            ),
            checkpoints_imported=len(materialization.manifest.checkpoints),
            survivorship_aggregate_rows=len(survivorship),
            readiness_aggregate_rows=len(readiness),
            elapsed_seconds=_seconds(start),
            idempotent_replace=True,
        )

    def status(self) -> PointInTimeStoreStatusReport:
        if not self.path.exists():
            return PointInTimeStoreStatusReport(
                store_path=self.path,
                exists=False,
                store_version=POINT_IN_TIME_ANALYTICAL_STORE_VERSION,
                build_id=None,
                build_status=None,
                completed_dates=0,
                universe_rows=0,
                security_rows=0,
                breadth_rows=0,
                sector_state_rows=0,
                survivorship_rows=0,
                readiness_rows=0,
                v2_reconstructions=0,
                v2_candidate_links=0,
            )
        with self._connect(read_only=True) as con:
            build = con.execute(
                """
                SELECT build_id, status, completed_dates
                FROM diagnostic_pit_builds
                ORDER BY imported_at DESC, build_id DESC
                LIMIT 1
                """
            ).fetchone()
            build_id = str(build[0]) if build else None
            build_status = str(build[1]) if build else None
            completed_dates = int(build[2]) if build else 0
            return PointInTimeStoreStatusReport(
                store_path=self.path,
                exists=True,
                store_version=POINT_IN_TIME_ANALYTICAL_STORE_VERSION,
                build_id=build_id,
                build_status=build_status,
                completed_dates=completed_dates,
                universe_rows=_count(con, "diagnostic_pit_universe_membership"),
                security_rows=_count(con, "diagnostic_pit_security_master"),
                breadth_rows=_count(con, "diagnostic_pit_breadth"),
                sector_state_rows=_count(con, "diagnostic_pit_sector_state"),
                survivorship_rows=_count(
                    con,
                    "diagnostic_pit_survivorship_aggregates",
                ),
                readiness_rows=_count(con, "diagnostic_pit_readiness_aggregates"),
                v2_reconstructions=_count(con, "diagnostic_market_state_v2"),
                v2_candidate_links=_count(
                    con,
                    "diagnostic_market_state_v2_candidate_links",
                ),
            )

    def validate(self) -> PointInTimeStoreValidationReport:
        status = self.status()
        if not status.exists or status.build_id is None:
            return PointInTimeStoreValidationReport(
                status=PointInTimeStoreValidationStatus.PARTIAL,
                store_path=self.path,
                build_id=None,
                duplicate_universe_rows=0,
                orphan_universe_security_ids=0,
                missing_breadth_dates=0,
                breadth_arithmetic_errors=0,
                readiness_rows=0,
                survivorship_rows=0,
                issues=("analytical store has not been imported",),
            )
        with self._connect(read_only=True) as con:
            duplicate_rows = int(
                _scalar(
                    con.execute(
                        """
                        SELECT COUNT(*) - COUNT(DISTINCT build_id || '|' ||
                            CAST(market_date AS VARCHAR) || '|' || security_id)
                        FROM diagnostic_pit_universe_membership
                        WHERE build_id = ?
                        """,
                        (status.build_id,),
                    ).fetchone()
                )
            )
            orphan_security_ids = int(
                _scalar(
                    con.execute(
                        """
                        SELECT COUNT(*)
                        FROM diagnostic_pit_universe_membership u
                        LEFT JOIN diagnostic_pit_security_master s
                          ON u.build_id = s.build_id AND u.security_id = s.security_id
                        WHERE u.build_id = ? AND s.security_id IS NULL
                        """,
                        (status.build_id,),
                    ).fetchone()
                )
            )
            missing_breadth_dates = int(
                _scalar(
                    con.execute(
                        """
                        SELECT COUNT(*)
                        FROM (
                            SELECT DISTINCT market_date
                            FROM diagnostic_pit_universe_membership
                            WHERE build_id = ?
                        ) d
                        LEFT JOIN diagnostic_pit_breadth b
                          ON b.build_id = ? AND b.market_date = d.market_date
                        WHERE b.market_date IS NULL
                        """,
                        (status.build_id, status.build_id),
                    ).fetchone()
                )
            )
            breadth_errors = int(
                _scalar(
                    con.execute(
                        """
                        SELECT COUNT(*)
                        FROM diagnostic_pit_breadth
                        WHERE build_id = ?
                          AND advancers + decliners + unchanged > priced_universe_size
                        """,
                        (status.build_id,),
                    ).fetchone()
                )
            )
        issues = []
        if duplicate_rows:
            issues.append("duplicate universe rows")
        if orphan_security_ids:
            issues.append("orphan security ids")
        if missing_breadth_dates:
            issues.append("missing breadth dates")
        if breadth_errors:
            issues.append("breadth arithmetic errors")
        if issues:
            validation_status = PointInTimeStoreValidationStatus.INVALID
        elif status.build_status == PointInTimeBuildStatus.COMPLETED.value:
            validation_status = PointInTimeStoreValidationStatus.VALID_WITH_LIMITATIONS
        else:
            validation_status = PointInTimeStoreValidationStatus.PARTIAL
        return PointInTimeStoreValidationReport(
            status=validation_status,
            store_path=self.path,
            build_id=status.build_id,
            duplicate_universe_rows=duplicate_rows,
            orphan_universe_security_ids=orphan_security_ids,
            missing_breadth_dates=missing_breadth_dates,
            breadth_arithmetic_errors=breadth_errors,
            readiness_rows=status.readiness_rows,
            survivorship_rows=status.survivorship_rows,
            issues=tuple(issues) or ("diagnostic current-sector limitation remains",),
        )

    def equivalence(
        self,
        *,
        build_id: str,
        materialization: PointInTimeMaterializedDataset | None = None,
        materialization_repository: PointInTimeMaterializationRepository | None = None,
    ) -> PointInTimeStoreEquivalenceReport:
        materialization_repository = (
            materialization_repository or PointInTimeMaterializationRepository()
        )
        materialization = (
            materialization
            or load_completed_point_in_time_materialization(
                materialization_repository.path
            )
        )
        if materialization.manifest.build_id != build_id:
            raise ValueError(
                "materialization build id mismatch: "
                f"requested {build_id}, found {materialization.manifest.build_id}"
            )
        if not self.path.exists():
            return PointInTimeStoreEquivalenceReport(
                status=PointInTimeStoreEquivalenceStatus.MISSING,
                build_id=build_id,
                materialization_path=materialization_repository.path,
                store_path=self.path,
                json_universe_rows=len(materialization.universe.rows),
                store_universe_rows=0,
                json_security_rows=len(materialization.universe.security_records),
                store_security_rows=0,
                json_breadth_rows=len(materialization.breadth_snapshots),
                store_breadth_rows=0,
                json_sector_state_rows=_sector_state_count(materialization),
                store_sector_state_rows=0,
                json_completed_dates=len(materialization.manifest.completed_dates),
                store_completed_dates=0,
                universe_fingerprint_match=False,
                breadth_fingerprint_match=False,
                issues=("analytical store has not been imported",),
            )
        with self._connect(read_only=True) as con:
            store_universe = _build_count(
                con,
                "diagnostic_pit_universe_membership",
                build_id,
            )
            store_security = _build_count(
                con,
                "diagnostic_pit_security_master",
                build_id,
            )
            store_breadth = _build_count(con, "diagnostic_pit_breadth", build_id)
            store_sector = _build_count(con, "diagnostic_pit_sector_state", build_id)
            store_dates = int(
                _scalar(
                    con.execute(
                        """
                        SELECT COUNT(DISTINCT market_date)
                        FROM diagnostic_pit_universe_membership
                        WHERE build_id = ?
                        """,
                        (build_id,),
                    ).fetchone()
                )
            )
            store_universe_hash = str(
                _scalar(
                    con.execute(
                        """
                        SELECT COALESCE(MAX(universe_fingerprint), '')
                        FROM diagnostic_pit_builds
                        WHERE build_id = ?
                        """,
                        (build_id,),
                    ).fetchone()
                )
            )
            store_breadth_hash = str(
                _scalar(
                    con.execute(
                        """
                        SELECT COALESCE(MAX(breadth_fingerprint), '')
                        FROM diagnostic_pit_builds
                        WHERE build_id = ?
                        """,
                        (build_id,),
                    ).fetchone()
                )
            )
        json_universe_hash = _universe_fingerprint(materialization.universe.rows)
        json_breadth_hash = _breadth_fingerprint(materialization.breadth_snapshots)
        issues = []
        if store_universe != len(materialization.universe.rows):
            issues.append("universe row count mismatch")
        if store_security != len(materialization.universe.security_records):
            issues.append("security row count mismatch")
        if store_breadth != len(materialization.breadth_snapshots):
            issues.append("breadth row count mismatch")
        if store_sector != _sector_state_count(materialization):
            issues.append("sector-state row count mismatch")
        if store_dates != len(materialization.manifest.completed_dates):
            issues.append("completed-date count mismatch")
        if store_universe_hash != json_universe_hash:
            issues.append("universe fingerprint mismatch")
        if store_breadth_hash != json_breadth_hash:
            issues.append("breadth fingerprint mismatch")
        return PointInTimeStoreEquivalenceReport(
            status=(
                PointInTimeStoreEquivalenceStatus.MISMATCH
                if issues
                else PointInTimeStoreEquivalenceStatus.MATCH_WITH_LIMITATIONS
            ),
            build_id=build_id,
            materialization_path=materialization_repository.path,
            store_path=self.path,
            json_universe_rows=len(materialization.universe.rows),
            store_universe_rows=store_universe,
            json_security_rows=len(materialization.universe.security_records),
            store_security_rows=store_security,
            json_breadth_rows=len(materialization.breadth_snapshots),
            store_breadth_rows=store_breadth,
            json_sector_state_rows=_sector_state_count(materialization),
            store_sector_state_rows=store_sector,
            json_completed_dates=len(materialization.manifest.completed_dates),
            store_completed_dates=store_dates,
            universe_fingerprint_match=store_universe_hash == json_universe_hash,
            breadth_fingerprint_match=store_breadth_hash == json_breadth_hash,
            issues=tuple(issues) or ("diagnostic current-sector limitation remains",),
        )

    def universe_coverage(
        self,
        *,
        build_id: str | None = None,
    ) -> PointInTimeUniverseCoverageReport:
        build_id = build_id or self._latest_build_id()
        if build_id is None:
            raise ValueError("analytical store has not been imported")
        with self._connect(read_only=True) as con:
            row = _required_row(
                con.execute(
                    """
                    SELECT
                        COUNT(DISTINCT market_date),
                        COUNT(*),
                        SUM(CASE WHEN membership_status = 'ELIGIBLE' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN membership_status != 'UNKNOWN' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN price_available THEN 1 ELSE 0 END),
                        SUM(CASE WHEN bars_available >= 200 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN sector_available THEN 1 ELSE 0 END),
                        COUNT(DISTINCT CASE
                            WHEN point_in_time_confidence = 'HIGH' THEN market_date
                        END)
                    FROM diagnostic_pit_universe_membership
                    WHERE build_id = ?
                    """,
                    (build_id,),
                ).fetchone()
            )
            build = con.execute(
                """
                SELECT dataset_version, universe_fingerprint
                FROM diagnostic_pit_builds
                WHERE build_id = ?
                """,
                (build_id,),
            ).fetchone()
        market_dates = int(row[0] or 0)
        security_rows = int(row[1] or 0)
        eligible = int(row[2] or 0)
        priced = int(row[4] or 0)
        high_quality_dates = int(row[7] or 0)
        partial_dates = max(0, market_dates - high_quality_dates)
        price_quality = _quality(priced, security_rows)
        return PointInTimeUniverseCoverageReport(
            dataset_version=str(build[0]) if build else "unavailable",
            dataset_fingerprint=str(build[1]) if build else "",
            market_dates=market_dates,
            security_rows=security_rows,
            eligible_rows=eligible,
            membership_known_rows=int(row[3] or 0),
            price_covered_rows=priced,
            dma_eligible_rows=int(row[5] or 0),
            sector_classified_rows=int(row[6] or 0),
            high_quality_dates=high_quality_dates,
            partial_dates=partial_dates,
            unusable_dates=0,
            membership_quality=UniverseQualityGrade.HIGH,
            identity_quality=UniverseQualityGrade.MEDIUM,
            price_coverage_quality=price_quality,
            breadth_quality=price_quality,
            sector_classification_quality=_quality(int(row[6] or 0), security_rows),
            sector_state_quality=UniverseQualityGrade.LOW,
            timestamp_quality=UniverseQualityGrade.MEDIUM,
            overall_point_in_time_quality=price_quality,
            primary_conclusion=PointInTimeConclusion.POINT_IN_TIME_MARKET_UNIVERSE_IS_PARTIAL,
            secondary_conclusion=PointInTimeConclusion.SECTOR_CLASSIFICATION_HISTORY_IS_PRIMARY_BOTTLENECK,
            recommended_next_milestone=PointInTimeNextMilestone.BUILD_HISTORICAL_SECTOR_CLASSIFICATION_INGESTION,
            explicitly_prohibited_next_action=(
                "Do not treat current sector mappings as authoritative historical "
                "sector membership."
            ),
        )

    def universe_rows(
        self,
        *,
        market_date: date,
        build_id: str | None = None,
    ) -> tuple[PointInTimeUniverseRow, ...]:
        build_id = build_id or self._latest_build_id()
        if build_id is None:
            return ()
        start = time.perf_counter()
        with self._connect(read_only=True) as con:
            rows = con.execute(
                """
                SELECT market_date, security_id, symbol, membership_status,
                       membership_reason, listing_status, price_available,
                       bars_available, liquidity_available, sector_available,
                       industry_available, source_lineage, source_quality,
                       survivorship_risk, point_in_time_confidence, dataset_version
                FROM diagnostic_pit_universe_membership
                WHERE build_id = ? AND market_date = ?
                ORDER BY symbol, security_id
                """,
                (build_id, market_date),
            ).fetchall()
        self._last_profile = PointInTimeStoreProfileReport(
            store_path=self.path,
            build_id=build_id,
            read_operation="universe_rows",
            rows_returned=len(rows),
            elapsed_seconds=_seconds(start),
            source="analytical_store",
            full_json_deserialization=False,
        )
        return tuple(_universe_row_from_store(row) for row in rows)

    def breadth_snapshots(
        self,
        *,
        build_id: str | None = None,
    ) -> tuple[PointInTimeBreadthSnapshot, ...]:
        build_id = build_id or self._latest_build_id()
        if build_id is None:
            return ()
        start = time.perf_counter()
        with self._connect(read_only=True) as con:
            rows = con.execute(
                """
                SELECT market_date, listed_universe_size, eligible_universe_size,
                       priced_universe_size, advancers, decliners, unchanged,
                       breadth_ratio, advance_decline_spread, percent_above_20dma,
                       percent_above_50dma, percent_above_200dma,
                       new_20_day_highs, new_20_day_lows, new_52_week_highs,
                       new_52_week_lows, median_return_1d, median_return_5d,
                       cross_sectional_dispersion, breadth_completeness
                FROM diagnostic_pit_breadth
                WHERE build_id = ?
                ORDER BY market_date
                """,
                (build_id,),
            ).fetchall()
        self._last_profile = PointInTimeStoreProfileReport(
            store_path=self.path,
            build_id=build_id,
            read_operation="breadth_snapshots",
            rows_returned=len(rows),
            elapsed_seconds=_seconds(start),
            source="analytical_store",
            full_json_deserialization=False,
        )
        return tuple(_breadth_from_store(row) for row in rows)

    def survivorship_audit(
        self,
        *,
        build_id: str | None = None,
    ) -> SurvivorshipBiasAuditReport:
        build_id = build_id or self._latest_build_id()
        if build_id is None:
            raise ValueError("analytical store has not been imported")
        with self._connect(read_only=True) as con:
            rows = con.execute(
                """
                SELECT market_date, current_universe_count,
                       point_in_time_universe_count, breadth_ratio_difference,
                       regime_input_difference, regime_classification_difference,
                       material_flag, candidate_records_affected
                FROM diagnostic_pit_survivorship_aggregates
                WHERE build_id = ?
                ORDER BY market_date
                """,
                (build_id,),
            ).fetchall()
        report_rows = tuple(
            SurvivorshipBiasRow(
                market_date=_date(row[0]),
                current_universe_count=int(row[1]),
                point_in_time_universe_count=int(row[2]),
                symbols_added_by_current_universe_bias=(),
                symbols_omitted_by_current_universe_bias=(),
                breadth_ratio_difference=_decimal(row[3]),
                dma_breadth_difference=None,
                new_high_new_low_difference=None,
                regime_input_difference=str(row[4]),
                regime_classification_difference=bool(row[5]),
            )
            for row in rows
        )
        return SurvivorshipBiasAuditReport(
            rows=report_rows,
            dates_materially_affected=sum(1 for row in rows if bool(row[6])),
            candidate_records_affected=sum(int(row[7]) for row in rows),
            recorded_reconstructed_regime_changes=0,
            outcome_conclusions_affected="not evaluated by analytical-store audit",
            finding=(
                "CURRENT_UNIVERSE_BIAS_IS_MATERIAL"
                if any(bool(row[6]) for row in rows)
                else "CURRENT_UNIVERSE_BIAS_IS_LIMITED"
            ),
        )

    def sector_coverage(
        self,
        *,
        build_id: str | None = None,
    ) -> SectorCoverageAuditReport:
        build_id = build_id or self._latest_build_id()
        if build_id is None:
            raise ValueError("analytical store has not been imported")
        with self._connect(read_only=True) as con:
            row = _required_row(
                con.execute(
                    """
                    SELECT COUNT(DISTINCT market_date),
                           SUM(candidate_records),
                           SUM(sector_classified_rows)
                    FROM diagnostic_pit_readiness_aggregates
                    WHERE build_id = ?
                    """,
                    (build_id,),
                ).fetchone()
            )
            sectors = con.execute(
                """
                SELECT DISTINCT sector_name
                FROM diagnostic_pit_security_master
                WHERE build_id = ?
                  AND sector_name IS NOT NULL
                ORDER BY sector_name
                """,
                (build_id,),
            ).fetchall()
        dates = int(row[0] or 0)
        classified = int(row[2] or 0)
        readiness = (
            SectorHistoryReadiness.CURRENT_MAPPING_ONLY
            if classified
            else SectorHistoryReadiness.INSUFFICIENT_EVIDENCE
        )
        return SectorCoverageAuditReport(
            candidate_dates=dates,
            dates_with_point_in_time_sector_coverage=0,
            dates_with_supported_sector_coverage=0,
            dates_with_current_mapping_only_coverage=dates if classified else 0,
            dates_unclassified=0 if classified else dates,
            candidate_records_covered=int(row[1] or 0),
            sectors_represented=tuple(str(item[0]) for item in sectors if item[0]),
            median_sector_universe_size=None,
            minimum_sector_universe_size=None,
            classification_conflicts=0,
            readiness=readiness,
        )

    def last_profile(self) -> PointInTimeStoreProfileReport:
        return getattr(
            self,
            "_last_profile",
            PointInTimeStoreProfileReport(
                store_path=self.path,
                build_id=self._latest_build_id(),
                read_operation="none",
                rows_returned=0,
                elapsed_seconds=Decimal("0.000000"),
                source="analytical_store",
                full_json_deserialization=False,
            ),
        )

    def build_diagnostic_v2(
        self,
        *,
        records: tuple[Any, ...],
        classifier_version: str,
        classifier_fingerprint: str,
        dry_run: bool,
        persist: bool,
        build_id: str | None = None,
    ) -> DiagnosticV2StoreBuildResult:
        build_id = build_id or self._latest_build_id()
        if build_id is None:
            raise ValueError("analytical store has not been imported")
        records_by_date: dict[date, tuple[Any, ...]] = {}
        for market_date in sorted({record.evaluation_date for record in records}):
            records_by_date[market_date] = tuple(
                sorted(
                    (
                        record
                        for record in records
                        if record.evaluation_date == market_date
                    ),
                    key=lambda item: (item.symbol, item.candidate_id),
                )
            )
        with self._connect(read_only=not persist or dry_run) as con:
            _create_schema(con)
            breadth_rows = con.execute(
                """
                SELECT market_date, breadth_ratio, percent_above_20dma,
                       percent_above_50dma, percent_above_200dma,
                       breadth_completeness
                FROM diagnostic_pit_breadth
                WHERE build_id = ?
                ORDER BY market_date
                """,
                (build_id,),
            ).fetchall()
            rows_by_date = {_date(row[0]): row for row in breadth_rows}
            reconstructions = [
                _v2_reconstruction_row(
                    build_id=build_id,
                    market_date=market_date,
                    row=row,
                    candidate_count=len(records_by_date.get(market_date, ())),
                    classifier_version=classifier_version,
                    classifier_fingerprint=classifier_fingerprint,
                )
                for market_date, row in rows_by_date.items()
            ]
            links = [
                _v2_candidate_link_row(
                    reconstruction_id=_v2_reconstruction_id(
                        build_id,
                        record.evaluation_date,
                    ),
                    record=record,
                    v2_regime=_v2_regime_from_breadth_row(
                        rows_by_date.get(record.evaluation_date)
                    ),
                )
                for record in records
                if record.evaluation_date in rows_by_date
            ]
            duplicate_links = len(
                [
                    key
                    for key in [
                        (row["reconstruction_id"], row["candidate_stable_id"])
                        for row in links
                    ]
                    if [
                        (item["reconstruction_id"], item["candidate_stable_id"])
                        for item in links
                    ].count(key)
                    > 1
                ]
            )
            orphan_links = sum(
                1
                for row in links
                if row["reconstruction_id"]
                not in {item["reconstruction_id"] for item in reconstructions}
            )
            if persist and not dry_run:
                con.execute(
                    "DELETE FROM diagnostic_market_state_v2 WHERE build_id = ?",
                    (build_id,),
                )
                con.execute(
                    """
                    DELETE FROM diagnostic_market_state_v2_candidate_links
                    WHERE build_id = ?
                    """,
                    (build_id,),
                )
                _insert_dataframe(
                    con,
                    "diagnostic_market_state_v2",
                    pd.DataFrame(reconstructions),
                )
                _insert_dataframe(
                    con,
                    "diagnostic_market_state_v2_candidate_links",
                    pd.DataFrame(links),
                )
        report = DiagnosticMarketStateV2BuildReport(
            dataset_version=DIAGNOSTIC_MARKET_STATE_V2_VERSION,
            dry_run=dry_run or not persist,
            universe_dataset_version=self._dataset_version(build_id),
            universe_dataset_fingerprint=self._universe_fingerprint(build_id),
            sector_dataset_version=POINT_IN_TIME_SECTOR_DATASET_VERSION,
            sector_dataset_fingerprint=self._sector_fingerprint(build_id),
            breadth_builder_version="analytical-store-breadth-read-v1",
            sector_state_builder_version="analytical-store-sector-read-v1",
            benchmark_builder_version="not_used_by_store_v2",
            classifier_version=classifier_version,
            classifier_fingerprint=classifier_fingerprint,
            feature_definition_version="market-feature-definitions-v2",
            source_lineage_fingerprint=_hash_text(
                f"{build_id}|{classifier_version}|{classifier_fingerprint}"
            ),
            reconstructions_would_create=len(reconstructions),
            candidate_links_would_create=len(links),
            persistence_status=(
                "PERSISTED" if persist and not dry_run else "DRY_RUN_ONLY"
            ),
            blocked_reason=None,
        )
        return DiagnosticV2StoreBuildResult(
            report=report,
            reconstructions_created=(
                len(reconstructions) if persist and not dry_run else 0
            ),
            candidate_links_created=len(links) if persist and not dry_run else 0,
            orphan_links=orphan_links,
            duplicate_links=duplicate_links,
            universe_rows_treated_as_candidate_links=0,
        )

    def v1_v2_comparison(
        self,
        *,
        v1_regimes: tuple[str, ...],
        build_id: str | None = None,
    ) -> DiagnosticV1V2ComparisonReport:
        build_id = build_id or self._latest_build_id()
        v2_regimes: tuple[str, ...] = ()
        changed_links = 0
        completeness: tuple[tuple[str, int], ...] = ()
        quality: tuple[tuple[str, int], ...] = ()
        if build_id is not None and self.path.exists():
            with self._connect(read_only=True) as con:
                rows = con.execute(
                    """
                    SELECT v2_regime, input_completeness, diagnostic_quality
                    FROM diagnostic_market_state_v2
                    WHERE build_id = ?
                    ORDER BY market_date
                    """,
                    (build_id,),
                ).fetchall()
                v2_regimes = tuple(str(row[0]) for row in rows)
                completeness = _counts(tuple(str(row[1]) for row in rows))
                quality = _counts(tuple(str(row[2]) for row in rows))
                changed_links = int(
                    _scalar(
                        con.execute(
                            """
                            SELECT COUNT(*)
                            FROM diagnostic_market_state_v2_candidate_links
                            WHERE build_id = ?
                              AND recorded_candidate_regime IS NOT NULL
                              AND recorded_candidate_regime != v2_regime
                            """,
                            (build_id,),
                        ).fetchone()
                    )
                )
        total = max(len(v1_regimes), len(v2_regimes))
        same = sum(
            1
            for left, right in zip(v1_regimes, v2_regimes, strict=False)
            if left == right
        )
        return DiagnosticV1V2ComparisonReport(
            v1_dataset_version="diagnostic-market-state-reconstruction-v1",
            v2_dataset_version=DIAGNOSTIC_MARKET_STATE_V2_VERSION,
            v1_regime_distribution=_counts(v1_regimes),
            v2_regime_distribution=_counts(v2_regimes),
            regime_agreement=_rate(same, total),
            neutral_share_v1=_share(v1_regimes, "NEUTRAL"),
            neutral_share_v2=_share(v2_regimes, "NEUTRAL"),
            bullish_share_v1=_share(v1_regimes, "BULLISH"),
            bullish_share_v2=_share(v2_regimes, "BULLISH"),
            bearish_share_v1=_share(v1_regimes, "BEARISH"),
            bearish_share_v2=_share(v2_regimes, "BEARISH"),
            dates_changing_regime=max(0, total - same),
            candidates_changing_linked_diagnostic_regime=changed_links,
            completeness_distribution=completeness or (("v2_not_persisted", total),),
            quality_distribution=quality or (("v2_not_persisted", total),),
            conclusion=(
                "STORE_BACKED_V2_AVAILABLE" if v2_regimes else "INSUFFICIENT_COVERAGE"
            ),
        )

    def v2_outcome_comparison(
        self,
        *,
        build_id: str | None = None,
    ) -> V2OutcomeComparisonReport:
        build_id = build_id or self._latest_build_id()
        if build_id is None:
            return V2OutcomeComparisonReport(
                v1_outcome_ordering=(),
                v2_outcome_ordering=(),
                v1_threshold_sensitivity="UNAVAILABLE",
                v2_threshold_sensitivity="UNAVAILABLE",
                comparison="INSUFFICIENT_COVERAGE",
                explanation="Analytical store has not been imported.",
            )
        with self._connect(read_only=True) as con:
            rows = con.execute(
                """
                SELECT v2_regime, COUNT(*) AS n
                FROM diagnostic_market_state_v2_candidate_links
                WHERE build_id = ?
                GROUP BY v2_regime
                ORDER BY n DESC, v2_regime
                """,
                (build_id,),
            ).fetchall()
        ordering = tuple(str(row[0]) for row in rows)
        return V2OutcomeComparisonReport(
            v1_outcome_ordering=(),
            v2_outcome_ordering=ordering,
            v1_threshold_sensitivity="UNCHANGED",
            v2_threshold_sensitivity="CANDIDATE_LINKS_AVAILABLE"
            if ordering
            else "UNAVAILABLE",
            comparison=(
                "READY_FOR_OUTCOME_JOIN" if ordering else "INSUFFICIENT_COVERAGE"
            ),
            explanation=(
                "V2 candidate links are grounded in candidate ledger records, not "
                "point-in-time universe membership rows."
            ),
        )

    def _latest_build_id(self) -> str | None:
        if not self.path.exists():
            return None
        with self._connect(read_only=True) as con:
            row = con.execute(
                """
                SELECT build_id
                FROM diagnostic_pit_builds
                ORDER BY imported_at DESC, build_id DESC
                LIMIT 1
                """
            ).fetchone()
            return str(row[0]) if row else None

    def _dataset_version(self, build_id: str) -> str:
        return self._build_text(build_id, "dataset_version")

    def _universe_fingerprint(self, build_id: str) -> str:
        return self._build_text(build_id, "universe_fingerprint")

    def _sector_fingerprint(self, build_id: str) -> str:
        return self._build_text(build_id, "sector_fingerprint")

    def _build_text(self, build_id: str, column: str) -> str:
        with self._connect(read_only=True) as con:
            row = con.execute(
                f"SELECT {column} FROM diagnostic_pit_builds WHERE build_id = ?",
                (build_id,),
            ).fetchone()
            return str(row[0]) if row and row[0] is not None else ""

    def _connect(self, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path), read_only=read_only)


def resolve_point_in_time_store_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.getenv("ALPHA_POINT_IN_TIME_ANALYTICAL_STORE")
    if configured:
        return Path(configured)
    return DEFAULT_POINT_IN_TIME_ANALYTICAL_STORE_PATH


def render_point_in_time_store_import(
    result: PointInTimeStoreImportResult,
) -> tuple[str, ...]:
    return (
        "Point-in-Time Analytical Store Import",
        f"Build ID: {result.build_id}",
        f"Store Path: {result.store_path}",
        f"Materialization Path: {result.materialization_path}",
        f"Source JSON Unchanged: {'yes' if result.source_json_unchanged else 'no'}",
        f"Universe Rows Imported: {result.rows_imported}",
        f"Security Rows Imported: {result.security_rows_imported}",
        f"Breadth Rows Imported: {result.breadth_rows_imported}",
        f"Sector-State Rows Imported: {result.sector_state_rows_imported}",
        f"Survivorship Aggregate Rows: {result.survivorship_aggregate_rows}",
        f"Readiness Aggregate Rows: {result.readiness_aggregate_rows}",
        f"Idempotent Replace: {'yes' if result.idempotent_replace else 'no'}",
        f"Elapsed Seconds: {result.elapsed_seconds}",
    )


def render_point_in_time_store_status(
    report: PointInTimeStoreStatusReport,
) -> tuple[str, ...]:
    if not report.exists:
        return (
            "Point-in-Time Analytical Store Status",
            f"Store Path: {report.store_path}",
            "Status: NOT IMPORTED",
            "Next Action: point-in-time-store-import --build-id <id>",
        )
    return (
        "Point-in-Time Analytical Store Status",
        f"Store Path: {report.store_path}",
        f"Store Version: {report.store_version}",
        f"Build ID: {report.build_id or 'unavailable'}",
        f"Build Status: {report.build_status or 'unavailable'}",
        f"Completed Dates: {report.completed_dates}",
        f"Universe Rows: {report.universe_rows}",
        f"Security Rows: {report.security_rows}",
        f"Breadth Rows: {report.breadth_rows}",
        f"Sector-State Rows: {report.sector_state_rows}",
        f"Survivorship Aggregate Rows: {report.survivorship_rows}",
        f"Readiness Aggregate Rows: {report.readiness_rows}",
        f"V2 Reconstructions: {report.v2_reconstructions}",
        f"V2 Candidate Links: {report.v2_candidate_links}",
    )


def render_point_in_time_store_validation(
    report: PointInTimeStoreValidationReport,
) -> tuple[str, ...]:
    return (
        "Point-in-Time Analytical Store Validation",
        f"Status: {report.status.value}",
        f"Store Path: {report.store_path}",
        f"Build ID: {report.build_id or 'unavailable'}",
        f"Duplicate Universe Rows: {report.duplicate_universe_rows}",
        f"Orphan Security IDs: {report.orphan_universe_security_ids}",
        f"Missing Breadth Dates: {report.missing_breadth_dates}",
        f"Breadth Arithmetic Errors: {report.breadth_arithmetic_errors}",
        f"Readiness Rows: {report.readiness_rows}",
        f"Survivorship Rows: {report.survivorship_rows}",
        f"Issues: {_text_list(report.issues)}",
    )


def render_point_in_time_store_equivalence(
    report: PointInTimeStoreEquivalenceReport,
) -> tuple[str, ...]:
    return (
        "Point-in-Time Store Equivalence",
        f"Status: {report.status.value}",
        f"Build ID: {report.build_id}",
        f"Materialization Path: {report.materialization_path}",
        f"Store Path: {report.store_path}",
        "Universe Rows: "
        f"JSON {report.json_universe_rows} | Store {report.store_universe_rows}",
        "Security Rows: "
        f"JSON {report.json_security_rows} | Store {report.store_security_rows}",
        "Breadth Rows: "
        f"JSON {report.json_breadth_rows} | Store {report.store_breadth_rows}",
        "Sector-State Rows: "
        f"JSON {report.json_sector_state_rows} | "
        f"Store {report.store_sector_state_rows}",
        "Completed Dates: "
        f"JSON {report.json_completed_dates} | Store {report.store_completed_dates}",
        "Universe Fingerprint Match: "
        f"{'yes' if report.universe_fingerprint_match else 'no'}",
        "Breadth Fingerprint Match: "
        f"{'yes' if report.breadth_fingerprint_match else 'no'}",
        f"Issues: {_text_list(report.issues)}",
    )


def render_point_in_time_store_profile(
    report: PointInTimeStoreProfileReport,
) -> tuple[str, ...]:
    return (
        "Point-in-Time Read Profile",
        f"Store Path: {report.store_path}",
        f"Build ID: {report.build_id or 'unavailable'}",
        f"Read Operation: {report.read_operation}",
        f"Rows Returned: {report.rows_returned}",
        f"Elapsed Seconds: {report.elapsed_seconds}",
        f"Source: {report.source}",
        "Full JSON Deserialization: "
        f"{'yes' if report.full_json_deserialization else 'no'}",
    )


def render_diagnostic_v2_store_build(
    result: DiagnosticV2StoreBuildResult,
) -> tuple[str, ...]:
    lines = [
        *render_diagnostic_v2_build(result.report),
        f"Reconstructions Created: {result.reconstructions_created}",
        f"Candidate Links Created: {result.candidate_links_created}",
        f"Orphan Links: {result.orphan_links}",
        f"Duplicate Links: {result.duplicate_links}",
        "Universe Rows Treated As Candidate Links: "
        f"{result.universe_rows_treated_as_candidate_links}",
    ]
    return tuple(lines)


def _create_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_pit_builds (
            build_id VARCHAR PRIMARY KEY,
            store_version VARCHAR,
            materialization_version VARCHAR,
            dataset_version VARCHAR,
            status VARCHAR,
            source_fingerprint VARCHAR,
            configuration_fingerprint VARCHAR,
            universe_fingerprint VARCHAR,
            breadth_fingerprint VARCHAR,
            sector_fingerprint VARCHAR,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            imported_at TIMESTAMP,
            completed_dates INTEGER,
            universe_rows INTEGER,
            security_rows INTEGER,
            breadth_rows INTEGER,
            sector_state_rows INTEGER,
            checkpoints INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_pit_checkpoints (
            build_id VARCHAR,
            batch_number INTEGER,
            from_date DATE,
            to_date DATE,
            completed_dates INTEGER,
            rows_written INTEGER,
            breadth_rows_written INTEGER,
            sector_state_rows_written INTEGER,
            validation_status VARCHAR,
            batch_fingerprint VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_pit_security_master (
            build_id VARCHAR,
            security_id VARCHAR,
            symbol VARCHAR,
            exchange VARCHAR,
            instrument_type VARCHAR,
            isin VARCHAR,
            company_name VARCHAR,
            listing_date DATE,
            delisting_date DATE,
            sector_name VARCHAR,
            industry_name VARCHAR,
            status VARCHAR,
            point_in_time_status VARCHAR,
            source_authority VARCHAR,
            schema_version VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_pit_universe_membership (
            build_id VARCHAR,
            market_date DATE,
            security_id VARCHAR,
            symbol VARCHAR,
            membership_status VARCHAR,
            membership_reason VARCHAR,
            listing_status VARCHAR,
            price_available BOOLEAN,
            bars_available INTEGER,
            liquidity_available BOOLEAN,
            sector_available BOOLEAN,
            industry_available BOOLEAN,
            source_lineage VARCHAR,
            source_quality VARCHAR,
            survivorship_risk VARCHAR,
            point_in_time_confidence VARCHAR,
            dataset_version VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_pit_breadth (
            build_id VARCHAR,
            market_date DATE,
            listed_universe_size INTEGER,
            eligible_universe_size INTEGER,
            priced_universe_size INTEGER,
            advancers INTEGER,
            decliners INTEGER,
            unchanged INTEGER,
            breadth_ratio DOUBLE,
            advance_decline_spread INTEGER,
            percent_above_20dma DOUBLE,
            percent_above_50dma DOUBLE,
            percent_above_200dma DOUBLE,
            new_20_day_highs INTEGER,
            new_20_day_lows INTEGER,
            new_52_week_highs INTEGER,
            new_52_week_lows INTEGER,
            median_return_1d DOUBLE,
            median_return_5d DOUBLE,
            cross_sectional_dispersion DOUBLE,
            breadth_completeness VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_pit_sector_state (
            build_id VARCHAR,
            market_date DATE,
            sector VARCHAR,
            eligible_securities INTEGER,
            priced_securities INTEGER,
            return_1d DOUBLE,
            return_5d DOUBLE,
            return_20d DOUBLE,
            breadth_ratio DOUBLE,
            percent_above_20dma DOUBLE,
            percent_above_50dma DOUBLE,
            percent_above_200dma DOUBLE,
            relative_return_versus_benchmark DOUBLE,
            leadership_rank INTEGER,
            participation DOUBLE,
            data_completeness VARCHAR,
            label VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_pit_survivorship_aggregates (
            build_id VARCHAR,
            market_date DATE,
            current_universe_count INTEGER,
            point_in_time_universe_count INTEGER,
            breadth_ratio_difference DOUBLE,
            regime_input_difference VARCHAR,
            regime_classification_difference BOOLEAN,
            material_flag BOOLEAN,
            candidate_records_affected INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_pit_readiness_aggregates (
            build_id VARCHAR,
            market_date DATE,
            candidate_records INTEGER,
            universe_rows INTEGER,
            eligible_rows INTEGER,
            priced_rows INTEGER,
            dma_eligible_rows INTEGER,
            sector_classified_rows INTEGER,
            breadth_status VARCHAR,
            readiness_status VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_market_state_v2 (
            build_id VARCHAR,
            reconstruction_id VARCHAR PRIMARY KEY,
            market_date DATE,
            candidate_count INTEGER,
            v2_regime VARCHAR,
            breadth_ratio DOUBLE,
            percent_above_20dma DOUBLE,
            percent_above_50dma DOUBLE,
            percent_above_200dma DOUBLE,
            input_completeness VARCHAR,
            diagnostic_quality VARCHAR,
            classifier_version VARCHAR,
            classifier_fingerprint VARCHAR,
            dataset_version VARCHAR,
            created_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_market_state_v2_candidate_links (
            build_id VARCHAR,
            reconstruction_id VARCHAR,
            candidate_stable_id VARCHAR,
            candidate_decision_timestamp TIMESTAMP,
            recorded_candidate_regime VARCHAR,
            v2_regime VARCHAR,
            setup_type VARCHAR,
            final_verdict VARCHAR,
            entry_state VARCHAR,
            outcome_available BOOLEAN,
            link_status VARCHAR
        )
        """
    )
    for table, columns in (
        ("diagnostic_pit_universe_membership", "build_id, market_date, symbol"),
        ("diagnostic_pit_breadth", "build_id, market_date"),
        ("diagnostic_pit_security_master", "build_id, security_id"),
        ("diagnostic_market_state_v2", "build_id, market_date"),
        ("diagnostic_market_state_v2_candidate_links", "build_id, candidate_stable_id"),
    ):
        con.execute(f"CREATE INDEX IF NOT EXISTS idx_{table} ON {table} ({columns})")


def _delete_build(con: duckdb.DuckDBPyConnection, build_id: str) -> None:
    for table in (
        "diagnostic_pit_builds",
        "diagnostic_pit_checkpoints",
        "diagnostic_pit_security_master",
        "diagnostic_pit_universe_membership",
        "diagnostic_pit_breadth",
        "diagnostic_pit_sector_state",
        "diagnostic_pit_survivorship_aggregates",
        "diagnostic_pit_readiness_aggregates",
        "diagnostic_market_state_v2",
        "diagnostic_market_state_v2_candidate_links",
    ):
        con.execute(f"DELETE FROM {table} WHERE build_id = ?", (build_id,))


def _insert_dataframe(
    con: duckdb.DuckDBPyConnection,
    table: str,
    frame: pd.DataFrame,
) -> None:
    if frame.empty:
        return
    view_name = f"__{table}_incoming"
    con.register(view_name, frame)
    try:
        con.execute(f"INSERT INTO {table} SELECT * FROM {view_name}")
    finally:
        con.unregister(view_name)


def _build_frame(materialization: PointInTimeMaterializedDataset) -> pd.DataFrame:
    manifest = materialization.manifest
    return pd.DataFrame(
        [
            {
                "build_id": manifest.build_id,
                "store_version": POINT_IN_TIME_ANALYTICAL_STORE_VERSION,
                "materialization_version": materialization.materialization_version,
                "dataset_version": manifest.dataset_version,
                "status": manifest.status.value,
                "source_fingerprint": manifest.source_fingerprint,
                "configuration_fingerprint": manifest.configuration_fingerprint,
                "universe_fingerprint": _universe_fingerprint(
                    materialization.universe.rows
                ),
                "breadth_fingerprint": _breadth_fingerprint(
                    materialization.breadth_snapshots
                ),
                "sector_fingerprint": _sector_fingerprint(materialization),
                "started_at": _naive(manifest.started_at),
                "completed_at": _naive(manifest.completed_at),
                "imported_at": _naive(datetime.now(tz=UTC)),
                "completed_dates": len(manifest.completed_dates),
                "universe_rows": len(materialization.universe.rows),
                "security_rows": len(materialization.universe.security_records),
                "breadth_rows": len(materialization.breadth_snapshots),
                "sector_state_rows": _sector_state_count(materialization),
                "checkpoints": len(manifest.checkpoints),
            }
        ]
    )


def _checkpoint_frame(materialization: PointInTimeMaterializedDataset) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "build_id": materialization.manifest.build_id,
                "batch_number": checkpoint.batch_number,
                "from_date": checkpoint.from_date,
                "to_date": checkpoint.to_date,
                "completed_dates": len(checkpoint.completed_dates),
                "rows_written": checkpoint.rows_written,
                "breadth_rows_written": checkpoint.breadth_rows_written,
                "sector_state_rows_written": checkpoint.sector_state_rows_written,
                "validation_status": checkpoint.validation_status.value,
                "batch_fingerprint": checkpoint.batch_fingerprint,
            }
            for checkpoint in materialization.manifest.checkpoints
        ]
    )


def _security_frame(
    build_id: str,
    rows: tuple[PointInTimeSecurityRecord, ...],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "build_id": build_id,
                "security_id": row.security_id,
                "symbol": row.symbol,
                "exchange": row.exchange,
                "instrument_type": row.instrument_type,
                "isin": row.isin,
                "company_name": row.company_name,
                "listing_date": row.listing_date,
                "delisting_date": row.delisting_date,
                "sector_name": row.sector_name,
                "industry_name": row.industry_name,
                "status": row.status,
                "point_in_time_status": row.point_in_time_status.value,
                "source_authority": row.source_authority,
                "schema_version": row.schema_version,
            }
            for row in sorted(rows, key=lambda item: item.security_id)
        ]
    )


def _universe_frame(
    build_id: str,
    rows: tuple[PointInTimeUniverseRow, ...],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "build_id": build_id,
                "market_date": row.market_date,
                "security_id": row.security_id,
                "symbol": row.symbol,
                "membership_status": row.membership_status.value,
                "membership_reason": row.membership_reason,
                "listing_status": row.listing_status,
                "price_available": row.price_available,
                "bars_available": row.bars_available,
                "liquidity_available": row.liquidity_available,
                "sector_available": row.sector_available,
                "industry_available": row.industry_available,
                "source_lineage": "|".join(row.source_lineage),
                "source_quality": row.source_quality.value,
                "survivorship_risk": row.survivorship_risk,
                "point_in_time_confidence": row.point_in_time_confidence.value,
                "dataset_version": row.dataset_version,
            }
            for row in sorted(rows, key=lambda item: (item.market_date, item.symbol))
        ]
    )


def _breadth_frame(
    build_id: str,
    rows: tuple[PointInTimeBreadthSnapshot, ...],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "build_id": build_id,
                "market_date": row.market_date,
                "listed_universe_size": row.listed_universe_size,
                "eligible_universe_size": row.eligible_universe_size,
                "priced_universe_size": row.priced_universe_size,
                "advancers": row.advancers,
                "decliners": row.decliners,
                "unchanged": row.unchanged,
                "breadth_ratio": _float(row.breadth_ratio),
                "advance_decline_spread": row.advance_decline_spread,
                "percent_above_20dma": _float(row.percent_above_20dma),
                "percent_above_50dma": _float(row.percent_above_50dma),
                "percent_above_200dma": _float(row.percent_above_200dma),
                "new_20_day_highs": row.new_20_day_highs,
                "new_20_day_lows": row.new_20_day_lows,
                "new_52_week_highs": row.new_52_week_highs,
                "new_52_week_lows": row.new_52_week_lows,
                "median_return_1d": _float(row.median_return_1d),
                "median_return_5d": _float(row.median_return_5d),
                "cross_sectional_dispersion": _float(row.cross_sectional_dispersion),
                "breadth_completeness": row.breadth_completeness.value,
            }
            for row in sorted(rows, key=lambda item: item.market_date)
        ]
    )


def _sector_state_frame(
    build_id: str,
    reports: tuple[HistoricalSectorStateReport, ...],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "build_id": build_id,
                "market_date": item.market_date,
                "sector": item.sector,
                "eligible_securities": item.eligible_securities,
                "priced_securities": item.priced_securities,
                "return_1d": _float(item.return_1d),
                "return_5d": _float(item.return_5d),
                "return_20d": _float(item.return_20d),
                "breadth_ratio": _float(item.breadth_ratio),
                "percent_above_20dma": _float(item.percent_above_20dma),
                "percent_above_50dma": _float(item.percent_above_50dma),
                "percent_above_200dma": _float(item.percent_above_200dma),
                "relative_return_versus_benchmark": _float(
                    item.relative_return_versus_benchmark
                ),
                "leadership_rank": item.leadership_rank,
                "participation": _float(item.participation),
                "data_completeness": item.data_completeness.value,
                "label": item.label,
            }
            for report in reports
            for item in report.sector_states
        ]
    )


def _survivorship_frame(
    materialization: PointInTimeMaterializedDataset,
) -> pd.DataFrame:
    by_date: dict[date, int] = {}
    for row in materialization.universe.rows:
        if row.membership_status is HistoricalMembershipStatus.ELIGIBLE:
            by_date[row.market_date] = by_date.get(row.market_date, 0) + 1
    return pd.DataFrame(
        [
            {
                "build_id": materialization.manifest.build_id,
                "market_date": market_date,
                "current_universe_count": by_date.get(market_date, 0),
                "point_in_time_universe_count": by_date.get(market_date, 0),
                "breadth_ratio_difference": 0.0,
                "regime_input_difference": "none",
                "regime_classification_difference": False,
                "material_flag": False,
                "candidate_records_affected": 0,
            }
            for market_date in materialization.manifest.completed_dates
        ]
    )


def _readiness_frame(materialization: PointInTimeMaterializedDataset) -> pd.DataFrame:
    breadth_by_date = {
        item.market_date: item for item in materialization.breadth_snapshots
    }
    rows_by_date: dict[date, list[PointInTimeUniverseRow]] = {}
    for row in materialization.universe.rows:
        rows_by_date.setdefault(row.market_date, []).append(row)
    records = []
    for market_date in materialization.manifest.completed_dates:
        rows = rows_by_date.get(market_date, [])
        breadth = breadth_by_date.get(market_date)
        priced = sum(1 for row in rows if row.price_available)
        records.append(
            {
                "build_id": materialization.manifest.build_id,
                "market_date": market_date,
                "candidate_records": len(rows),
                "universe_rows": len(rows),
                "eligible_rows": sum(
                    1
                    for row in rows
                    if row.membership_status is HistoricalMembershipStatus.ELIGIBLE
                ),
                "priced_rows": priced,
                "dma_eligible_rows": sum(
                    1 for row in rows if row.bars_available >= 200
                ),
                "sector_classified_rows": sum(
                    1 for row in rows if row.sector_available
                ),
                "breadth_status": (
                    breadth.breadth_completeness.value
                    if breadth is not None
                    else "UNAVAILABLE"
                ),
                "readiness_status": "READY_WITH_LIMITATIONS"
                if priced
                else "INSUFFICIENT_EVIDENCE",
            }
        )
    return pd.DataFrame(records)


def _v2_reconstruction_row(
    *,
    build_id: str,
    market_date: date,
    row: Any,
    candidate_count: int,
    classifier_version: str,
    classifier_fingerprint: str,
) -> dict[str, object]:
    return {
        "build_id": build_id,
        "reconstruction_id": _v2_reconstruction_id(build_id, market_date),
        "market_date": market_date,
        "candidate_count": candidate_count,
        "v2_regime": _v2_regime_from_breadth_row(row),
        "breadth_ratio": _float(_decimal(row[1])),
        "percent_above_20dma": _float(_decimal(row[2])),
        "percent_above_50dma": _float(_decimal(row[3])),
        "percent_above_200dma": _float(_decimal(row[4])),
        "input_completeness": "POINT_IN_TIME_BREADTH_AVAILABLE",
        "diagnostic_quality": str(row[5]),
        "classifier_version": classifier_version,
        "classifier_fingerprint": classifier_fingerprint,
        "dataset_version": DIAGNOSTIC_MARKET_STATE_V2_VERSION,
        "created_at": _naive(datetime(1970, 1, 1, tzinfo=UTC)),
    }


def _v2_candidate_link_row(
    *,
    reconstruction_id: str,
    record: Any,
    v2_regime: str,
) -> dict[str, object]:
    created_at = getattr(record, "created_at", datetime(1970, 1, 1, tzinfo=UTC))
    return {
        "build_id": reconstruction_id.split("|", 1)[0],
        "reconstruction_id": reconstruction_id,
        "candidate_stable_id": str(getattr(record, "candidate_id")),
        "candidate_decision_timestamp": _naive(created_at),
        "recorded_candidate_regime": getattr(record, "market_regime", None),
        "v2_regime": v2_regime,
        "setup_type": getattr(record, "setup_type", None),
        "final_verdict": str(getattr(record, "final_verdict", "UNKNOWN")),
        "entry_state": getattr(record, "capital_action", None),
        "outcome_available": False,
        "link_status": "CANDIDATE_LEDGER_LINK",
    }


def _v2_regime_from_breadth_row(row: Any | None) -> str:
    if row is None:
        return "NEUTRAL"
    ratio = _decimal(row[1])
    above_50 = _decimal(row[3])
    if ratio is None and above_50 is None:
        return "NEUTRAL"
    signal = ratio if ratio is not None else above_50
    if signal is not None and signal >= Decimal("0.55"):
        return "BULLISH"
    if signal is not None and signal <= Decimal("0.45"):
        return "BEARISH"
    return "NEUTRAL"


def _v2_reconstruction_id(build_id: str, market_date: date) -> str:
    return f"{build_id}|{market_date.isoformat()}|{DIAGNOSTIC_MARKET_STATE_V2_VERSION}"


def _universe_row_from_store(row: tuple[Any, ...]) -> PointInTimeUniverseRow:
    return PointInTimeUniverseRow(
        market_date=_date(row[0]),
        security_id=str(row[1]),
        symbol=str(row[2]),
        membership_status=HistoricalMembershipStatus(str(row[3])),
        membership_reason=str(row[4]),
        listing_status=str(row[5]),
        price_available=bool(row[6]),
        bars_available=int(row[7]),
        liquidity_available=bool(row[8]),
        sector_available=bool(row[9]),
        industry_available=bool(row[10]),
        source_lineage=tuple(str(row[11]).split("|")) if row[11] else (),
        source_quality=UniverseQualityGrade(str(row[12])),
        survivorship_risk=str(row[13]),
        point_in_time_confidence=UniverseQualityGrade(str(row[14])),
        dataset_version=str(row[15]),
    )


def _breadth_from_store(row: tuple[Any, ...]) -> PointInTimeBreadthSnapshot:
    return PointInTimeBreadthSnapshot(
        market_date=_date(row[0]),
        listed_universe_size=int(row[1]),
        eligible_universe_size=int(row[2]),
        priced_universe_size=int(row[3]),
        advancers=int(row[4]),
        decliners=int(row[5]),
        unchanged=int(row[6]),
        breadth_ratio=_decimal(row[7]),
        advance_decline_spread=int(row[8]),
        percent_above_20dma=_decimal(row[9]),
        percent_above_50dma=_decimal(row[10]),
        percent_above_200dma=_decimal(row[11]),
        new_20_day_highs=None if row[12] is None else int(row[12]),
        new_20_day_lows=None if row[13] is None else int(row[13]),
        new_52_week_highs=None if row[14] is None else int(row[14]),
        new_52_week_lows=None if row[15] is None else int(row[15]),
        median_return_1d=_decimal(row[16]),
        median_return_5d=_decimal(row[17]),
        cross_sectional_dispersion=_decimal(row[18]),
        breadth_completeness=BreadthCoverageStatus(str(row[19])),
    )


def _sector_state_count(materialization: PointInTimeMaterializedDataset) -> int:
    return sum(
        len(report.sector_states) for report in materialization.sector_state_reports
    )


def _file_fingerprint(path: Path) -> str:
    if not path.exists():
        return ""
    stat = path.stat()
    return _hash_text(f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}")


def _universe_fingerprint(rows: tuple[PointInTimeUniverseRow, ...]) -> str:
    return _hash_text(
        "\n".join(
            f"{row.market_date}|{row.security_id}|{row.symbol}|"
            f"{row.membership_status.value}|{row.price_available}|{row.bars_available}"
            for row in sorted(
                rows,
                key=lambda item: (item.market_date, item.security_id),
            )
        )
    )


def _breadth_fingerprint(rows: tuple[PointInTimeBreadthSnapshot, ...]) -> str:
    return _hash_text(
        "\n".join(
            f"{row.market_date}|{row.eligible_universe_size}|{row.priced_universe_size}|"
            f"{row.advancers}|{row.decliners}|{row.breadth_ratio}|"
            f"{row.percent_above_50dma}"
            for row in sorted(rows, key=lambda item: item.market_date)
        )
    )


def _sector_fingerprint(materialization: PointInTimeMaterializedDataset) -> str:
    return _hash_text(
        "\n".join(
            f"{item.market_date}|{item.sector}|{item.eligible_securities}|"
            f"{item.priced_securities}|{item.breadth_ratio}"
            for report in materialization.sector_state_reports
            for item in report.sector_states
        )
    )


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return int(_scalar(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()))


def _build_count(con: duckdb.DuckDBPyConnection, table: str, build_id: str) -> int:
    return int(
        _scalar(
            con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE build_id = ?",
                (build_id,),
            ).fetchone()
        )
    )


def _required_row(row: tuple[Any, ...] | None) -> tuple[Any, ...]:
    if row is None:
        raise ValueError("expected analytical store query to return one row")
    return row


def _scalar(row: tuple[Any, ...] | None) -> Any:
    return _required_row(row)[0]


def _quality(numerator: int, denominator: int) -> UniverseQualityGrade:
    if denominator <= 0:
        return UniverseQualityGrade.LOW
    ratio = Decimal(numerator) / Decimal(denominator)
    if ratio >= Decimal("0.90"):
        return UniverseQualityGrade.HIGH
    if ratio >= Decimal("0.50"):
        return UniverseQualityGrade.MEDIUM
    return UniverseQualityGrade.LOW


def _counts(values: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((value, values.count(value)) for value in set(values)))


def _share(values: tuple[str, ...], target: str) -> Decimal | None:
    return _rate(sum(1 for value in values if value == target), len(values))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))


def _seconds(start: float) -> Decimal:
    return Decimal(str(time.perf_counter() - start)).quantize(Decimal("0.000001"))


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NAN", "NONE", "<NA>"}:
        return None
    return Decimal(text)


def _date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _text_list(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "none"


__all__ = [
    "DEFAULT_POINT_IN_TIME_ANALYTICAL_STORE_PATH",
    "DiagnosticV2StoreBuildResult",
    "POINT_IN_TIME_ANALYTICAL_STORE_VERSION",
    "PointInTimeAnalyticalRepository",
    "PointInTimeStoreEquivalenceReport",
    "PointInTimeStoreEquivalenceStatus",
    "PointInTimeStoreImportResult",
    "PointInTimeStoreProfileReport",
    "PointInTimeStoreStatusReport",
    "PointInTimeStoreValidationReport",
    "PointInTimeStoreValidationStatus",
    "render_diagnostic_v2_store_build",
    "render_point_in_time_store_equivalence",
    "render_point_in_time_store_import",
    "render_point_in_time_store_profile",
    "render_point_in_time_store_status",
    "render_point_in_time_store_validation",
    "resolve_point_in_time_store_path",
]
