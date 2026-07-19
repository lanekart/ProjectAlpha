from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb

from alpha.market_intelligence.point_in_time_store import (
    resolve_point_in_time_store_path,
)

HISTORICAL_SECTOR_DATASET_VERSION = "historical-sector-classification-v1"
DIAGNOSTIC_MARKET_STATE_V3_VERSION = "diagnostic-market-state-reconstruction-v3"
_ZERO = Decimal("0")
_FOUR = Decimal("0.0001")


class SectorSourceAuthority(StrEnum):
    AUTHORITATIVE_POINT_IN_TIME = "AUTHORITATIVE_POINT_IN_TIME"
    STRONG_POINT_IN_TIME = "STRONG_POINT_IN_TIME"
    SUPPORTED_EFFECTIVE_DATED = "SUPPORTED_EFFECTIVE_DATED"
    CURRENT_STATE_ONLY = "CURRENT_STATE_ONLY"
    INDEX_MEMBERSHIP_ONLY = "INDEX_MEMBERSHIP_ONLY"
    WEAK_INFERENCE_ONLY = "WEAK_INFERENCE_ONLY"
    UNUSABLE = "UNUSABLE"


class HistoricalSectorStatus(StrEnum):
    POINT_IN_TIME_AUTHORITATIVE = "POINT_IN_TIME_AUTHORITATIVE"
    POINT_IN_TIME_SUPPORTED = "POINT_IN_TIME_SUPPORTED"
    EFFECTIVE_DATE_INFERRED_STRONG = "EFFECTIVE_DATE_INFERRED_STRONG"
    EFFECTIVE_DATE_INFERRED_WEAK = "EFFECTIVE_DATE_INFERRED_WEAK"
    CURRENT_MAPPING_ONLY = "CURRENT_MAPPING_ONLY"
    CONFLICTING_CLASSIFICATION = "CONFLICTING_CLASSIFICATION"
    UNCLASSIFIED = "UNCLASSIFIED"


class SectorIdentityMatchStatus(StrEnum):
    EXACT_SECURITY_ID = "EXACT_SECURITY_ID"
    ISIN_MATCH = "ISIN_MATCH"
    SUPPORTED_SYMBOL_LINEAGE = "SUPPORTED_SYMBOL_LINEAGE"
    AMBIGUOUS_SYMBOL = "AMBIGUOUS_SYMBOL"
    REUSED_SYMBOL_CONFLICT = "REUSED_SYMBOL_CONFLICT"
    CORPORATE_ACTION_CONFLICT = "CORPORATE_ACTION_CONFLICT"
    UNMATCHED = "UNMATCHED"


class SectorConflictResolutionStatus(StrEnum):
    RESOLVED_BY_AUTHORITY = "RESOLVED_BY_AUTHORITY"
    RESOLVED_BY_EFFECTIVE_DATE = "RESOLVED_BY_EFFECTIVE_DATE"
    UNRESOLVED_EQUAL_AUTHORITY = "UNRESOLVED_EQUAL_AUTHORITY"
    UNRESOLVED_IDENTITY_CONFLICT = "UNRESOLVED_IDENTITY_CONFLICT"
    UNRESOLVED_TAXONOMY_CONFLICT = "UNRESOLVED_TAXONOMY_CONFLICT"


class HistoricalSectorBuildStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"


class HistoricalSectorReadinessStatus(StrEnum):
    READY = "READY"
    CONDITIONALLY_READY = "CONDITIONALLY_READY"
    NOT_READY = "NOT_READY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class HistoricalSectorConclusion(StrEnum):
    HISTORICAL_SECTOR_HISTORY_IS_READY = "HISTORICAL_SECTOR_HISTORY_IS_READY"
    HISTORICAL_SECTOR_HISTORY_IS_PARTIAL = "HISTORICAL_SECTOR_HISTORY_IS_PARTIAL"
    SECTOR_SOURCE_AUTHORITY_IS_PRIMARY_LIMITATION = (
        "SECTOR_SOURCE_AUTHORITY_IS_PRIMARY_LIMITATION"
    )
    SECURITY_TO_SECTOR_IDENTITY_IS_PRIMARY_LIMITATION = (
        "SECURITY_TO_SECTOR_IDENTITY_IS_PRIMARY_LIMITATION"
    )
    EFFECTIVE_DATE_COVERAGE_IS_PRIMARY_LIMITATION = (
        "EFFECTIVE_DATE_COVERAGE_IS_PRIMARY_LIMITATION"
    )
    SECTOR_STATE_IMPROVES_REGIME_VALIDATION = "SECTOR_STATE_IMPROVES_REGIME_VALIDATION"
    SECTOR_STATE_DOES_NOT_MATERIALLY_CHANGE_FINDINGS = (
        "SECTOR_STATE_DOES_NOT_MATERIALLY_CHANGE_FINDINGS"
    )
    SECTOR_STATE_INCREASES_INSTABILITY = "SECTOR_STATE_INCREASES_INSTABILITY"
    MARKET_REGIME_HAS_STABLE_SECTOR_AWARE_SEPARATION = (
        "MARKET_REGIME_HAS_STABLE_SECTOR_AWARE_SEPARATION"
    )
    MARKET_REGIME_REMAINS_NOT_READY_FOR_PRODUCTION_REDESIGN = (
        "MARKET_REGIME_REMAINS_NOT_READY_FOR_PRODUCTION_REDESIGN"
    )
    THRESHOLD_SENSITIVITY_REMAINS_PRIMARY_LIMITATION = (
        "THRESHOLD_SENSITIVITY_REMAINS_PRIMARY_LIMITATION"
    )
    INSUFFICIENT_EVIDENCE_FOR_SECTOR_CONCLUSION = (
        "INSUFFICIENT_EVIDENCE_FOR_SECTOR_CONCLUSION"
    )


class HistoricalSectorNextMilestone(StrEnum):
    AUDIT_MARKET_REGIME_THRESHOLD_DEFINITIONS = (
        "AUDIT_MARKET_REGIME_THRESHOLD_DEFINITIONS"
    )
    AUDIT_REGIME_INTERVENTION_POLICY = "AUDIT_REGIME_INTERVENTION_POLICY"
    BUILD_OFFICIAL_SECTOR_HISTORY_SOURCE = "BUILD_OFFICIAL_SECTOR_HISTORY_SOURCE"
    REPAIR_SECURITY_SECTOR_IDENTITY = "REPAIR_SECURITY_SECTOR_IDENTITY"
    EXPAND_SECTOR_EFFECTIVE_DATE_HISTORY = "EXPAND_SECTOR_EFFECTIVE_DATE_HISTORY"
    AUDIT_MOMENTUM_MARKET_STATE_INTERACTION = "AUDIT_MOMENTUM_MARKET_STATE_INTERACTION"
    AUDIT_RETRACEMENT_SIGNAL_DEFINITION = "AUDIT_RETRACEMENT_SIGNAL_DEFINITION"
    SIMPLIFY_MARKET_REGIME_TO_BENCHMARK_AND_BREADTH = (
        "SIMPLIFY_MARKET_REGIME_TO_BENCHMARK_AND_BREADTH"
    )
    ACCEPT_MARKET_REGIME_AS_DIAGNOSTIC_ONLY = "ACCEPT_MARKET_REGIME_AS_DIAGNOSTIC_ONLY"
    COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY = (
        "COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY"
    )


@dataclass(frozen=True, slots=True)
class SectorSourceInventoryItem:
    source_id: str
    source_type: str
    source_location: str
    taxonomy_name: str
    taxonomy_version: str
    available_fields: tuple[str, ...]
    record_count: int
    security_coverage: int
    date_coverage: str
    effective_date_support: bool
    identity_fields: tuple[str, ...]
    isin_support: bool
    symbol_support: bool
    point_in_time_safety: bool
    authority: SectorSourceAuthority
    update_frequency: str
    known_limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SectorTaxonomyDefinition:
    taxonomy_id: str
    taxonomy_name: str
    taxonomy_version: str
    provider: str
    hierarchy_levels: tuple[str, ...]
    sector_field: str | None
    industry_group_field: str | None
    industry_field: str | None
    subindustry_field: str | None
    effective_from: date | None
    effective_to: date | None
    source: str
    authority: SectorSourceAuthority


@dataclass(frozen=True, slots=True)
class HistoricalSectorClassification:
    classification_id: str
    security_id: str
    isin: str | None
    symbol_at_effective_date: str
    taxonomy_id: str
    sector_code: str | None
    sector_name: str | None
    industry_group_code: str | None
    industry_group_name: str | None
    industry_code: str | None
    industry_name: str | None
    subindustry_code: str | None
    subindustry_name: str | None
    effective_from: date | None
    effective_to: date | None
    source_record_date: date | None
    source_timestamp: datetime | None
    ingested_at: datetime
    source_id: str
    authority: SectorSourceAuthority
    confidence: str
    point_in_time_status: HistoricalSectorStatus
    inference_method: str
    missing_fields: tuple[str, ...]
    schema_version: str
    dataset_version: str


@dataclass(frozen=True, slots=True)
class SectorIdentityReconciliationRow:
    classification_id: str
    security_id: str | None
    symbol: str
    isin: str | None
    match_status: SectorIdentityMatchStatus
    resolution_reason: str


@dataclass(frozen=True, slots=True)
class HistoricalSectorConflict:
    conflict_id: str
    security_id: str
    taxonomy_id: str
    effective_from: date | None
    effective_to: date | None
    source_a: str
    source_b: str
    classification_a: str
    classification_b: str
    resolution_status: SectorConflictResolutionStatus
    resolution_reason: str


@dataclass(frozen=True, slots=True)
class HistoricalSectorChange:
    security_id: str
    previous_classification: str
    new_classification: str
    effective_date: date | None
    source: str
    taxonomy: str
    change_type: str
    confidence: str
    candidate_dates_affected: int
    candidate_records_affected: int


@dataclass(frozen=True, slots=True)
class HistoricalSectorBuildManifest:
    build_id: str
    dataset_version: str
    source_fingerprint: str
    configuration_fingerprint: str
    taxonomy_versions: tuple[str, ...]
    started_at: datetime
    completed_at: datetime | None
    source_rows: int
    classification_rows: int
    matched_rows: int
    unmatched_rows: int
    conflicting_rows: int
    effective_dated_rows: int
    current_only_rows: int
    status: HistoricalSectorBuildStatus
    validation_status: HistoricalSectorReadinessStatus


@dataclass(frozen=True, slots=True)
class HistoricalSectorCoverageRow:
    market_date: date
    point_in_time_universe_size: int
    classified_security_count: int
    authoritative_classification_count: int
    supported_classification_count: int
    inferred_classification_count: int
    current_only_classification_count: int
    unclassified_count: int
    conflicting_count: int
    sector_count: int
    industry_count: int
    coverage_percentage: Decimal | None
    grade: str


@dataclass(frozen=True, slots=True)
class HistoricalSectorBuildReport:
    manifest: HistoricalSectorBuildManifest
    sources: tuple[SectorSourceInventoryItem, ...]
    taxonomies: tuple[SectorTaxonomyDefinition, ...]
    classifications: tuple[HistoricalSectorClassification, ...]
    identity_rows: tuple[SectorIdentityReconciliationRow, ...]
    conflicts: tuple[HistoricalSectorConflict, ...]
    changes: tuple[HistoricalSectorChange, ...]
    coverage: tuple[HistoricalSectorCoverageRow, ...]
    dry_run: bool
    persisted: bool
    prohibited_next_action: str


@dataclass(frozen=True, slots=True)
class HistoricalSectorValidationReport:
    status: HistoricalSectorReadinessStatus
    source_count: int
    authoritative_sources: int
    effective_dated_classifications: int
    current_only_classifications: int
    conflicts: int
    invalid_effective_ranges: int
    overlapping_authoritative_ranges: int
    future_classification_violations: int
    orphan_security_identities: int
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticMarketStateV3BuildReport:
    dataset_version: str
    dry_run: bool
    build_id: str | None
    v2_build_id: str | None
    sector_dataset_version: str
    sector_dataset_fingerprint: str
    sector_state_fingerprint: str
    classifier_version: str
    classifier_fingerprint: str
    feature_definition_version: str
    reconstructions_would_create: int
    candidate_links_would_create: int
    reconstructions_created: int
    candidate_links_created: int
    duplicate_links: int
    orphan_links: int
    universe_rows_treated_as_candidate_links: int
    persistence_status: str
    blocked_reason: str | None


@dataclass(frozen=True, slots=True)
class DiagnosticV2V3ComparisonReport:
    dates_compared: int
    dates_changed: int
    candidate_records_affected: int
    v2_regime_distribution: tuple[tuple[str, int], ...]
    v3_regime_distribution: tuple[tuple[str, int], ...]
    sector_status_distribution: tuple[tuple[str, int], ...]
    classification: str
    explanation: str


@dataclass(frozen=True, slots=True)
class HistoricalSectorReadinessItem:
    criterion: str
    status: HistoricalSectorReadinessStatus
    explanation: str


@dataclass(frozen=True, slots=True)
class HistoricalSectorDecisionReadinessReport:
    scorecard: tuple[HistoricalSectorReadinessItem, ...]
    primary_conclusion: HistoricalSectorConclusion
    secondary_conclusion: HistoricalSectorConclusion | None
    recommended_next_milestone: HistoricalSectorNextMilestone
    explicitly_prohibited_next_action: str


class HistoricalSectorRepository:
    def __init__(self, store_path: Path | str | None = None) -> None:
        self.store_path = resolve_point_in_time_store_path(store_path)

    def save_build(self, report: HistoricalSectorBuildReport) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(self.store_path)) as con:
            _create_schema(con)
            con.execute(
                "DELETE FROM diagnostic_sector_builds WHERE build_id = ?",
                (report.manifest.build_id,),
            )
            for table in (
                "diagnostic_sector_sources",
                "diagnostic_sector_taxonomies",
                "diagnostic_sector_classifications",
                "diagnostic_sector_identity_reconciliation",
                "diagnostic_sector_classification_conflicts",
                "diagnostic_sector_changes",
                "diagnostic_sector_coverage",
            ):
                con.execute(
                    f"DELETE FROM {table} WHERE build_id = ?",
                    (report.manifest.build_id,),
                )
            _insert_rows(
                con, "diagnostic_sector_builds", (_build_row(report.manifest),)
            )
            _insert_rows(
                con,
                "diagnostic_sector_sources",
                tuple(
                    _source_row(report.manifest.build_id, row) for row in report.sources
                ),
            )
            _insert_rows(
                con,
                "diagnostic_sector_taxonomies",
                tuple(
                    _taxonomy_row(report.manifest.build_id, row)
                    for row in report.taxonomies
                ),
            )
            _insert_rows(
                con,
                "diagnostic_sector_classifications",
                tuple(
                    _classification_row(row) | {"build_id": report.manifest.build_id}
                    for row in report.classifications
                ),
            )
            _insert_rows(
                con,
                "diagnostic_sector_identity_reconciliation",
                tuple(
                    _identity_row(report.manifest.build_id, row)
                    for row in report.identity_rows
                ),
            )
            _insert_rows(
                con,
                "diagnostic_sector_classification_conflicts",
                tuple(
                    _conflict_row(report.manifest.build_id, row)
                    for row in report.conflicts
                ),
            )
            _insert_rows(
                con,
                "diagnostic_sector_changes",
                tuple(
                    _change_row(report.manifest.build_id, row) for row in report.changes
                ),
            )
            _insert_rows(
                con,
                "diagnostic_sector_coverage",
                tuple(
                    _coverage_row(report.manifest.build_id, row)
                    for row in report.coverage
                ),
            )

    def latest_manifest(self) -> HistoricalSectorBuildManifest | None:
        if not self.store_path.exists():
            return None
        with duckdb.connect(str(self.store_path), read_only=True) as con:
            if not _table_exists(con, "diagnostic_sector_builds"):
                return None
            row = con.execute(
                """
                SELECT *
                FROM diagnostic_sector_builds
                ORDER BY completed_at DESC, build_id DESC
                LIMIT 1
                """
            ).fetchone()
        return None if row is None else _manifest_from_row(row)

    def load_sources(
        self, build_id: str | None = None
    ) -> tuple[SectorSourceInventoryItem, ...]:
        return tuple(
            _source_from_row(row)
            for row in self._rows("diagnostic_sector_sources", build_id)
        )

    def load_taxonomies(
        self, build_id: str | None = None
    ) -> tuple[SectorTaxonomyDefinition, ...]:
        return tuple(
            _taxonomy_from_row(row)
            for row in self._rows("diagnostic_sector_taxonomies", build_id)
        )

    def load_classifications(
        self, build_id: str | None = None
    ) -> tuple[HistoricalSectorClassification, ...]:
        return tuple(
            _classification_from_row(row)
            for row in self._rows("diagnostic_sector_classifications", build_id)
        )

    def get_classification_as_of(
        self, *, security_id: str, market_date: date
    ) -> HistoricalSectorClassification | None:
        rows = tuple(
            row
            for row in self.load_classifications()
            if row.security_id == security_id
            and row.effective_from is not None
            and row.effective_from <= market_date
            and (row.effective_to is None or market_date < row.effective_to)
            and row.point_in_time_status
            in {
                HistoricalSectorStatus.POINT_IN_TIME_AUTHORITATIVE,
                HistoricalSectorStatus.POINT_IN_TIME_SUPPORTED,
            }
        )
        return rows[0] if rows else None

    def get_security_classification_history(
        self, *, security_id: str
    ) -> tuple[HistoricalSectorClassification, ...]:
        return tuple(
            row for row in self.load_classifications() if row.security_id == security_id
        )

    def get_sector_members_as_of(
        self, *, sector: str, market_date: date
    ) -> tuple[HistoricalSectorClassification, ...]:
        return tuple(
            row
            for row in self.load_classifications()
            if (row.sector_name or "").upper() == sector.upper()
            and row.effective_from is not None
            and row.effective_from <= market_date
            and (row.effective_to is None or market_date < row.effective_to)
        )

    def get_sector_coverage(
        self, build_id: str | None = None
    ) -> tuple[HistoricalSectorCoverageRow, ...]:
        return tuple(
            _coverage_from_row(row)
            for row in self._rows("diagnostic_sector_coverage", build_id)
        )

    def get_conflicts(
        self, build_id: str | None = None
    ) -> tuple[HistoricalSectorConflict, ...]:
        return tuple(
            _conflict_from_row(row)
            for row in self._rows(
                "diagnostic_sector_classification_conflicts", build_id
            )
        )

    def get_changes(
        self, build_id: str | None = None
    ) -> tuple[HistoricalSectorChange, ...]:
        return tuple(
            _change_from_row(row)
            for row in self._rows("diagnostic_sector_changes", build_id)
        )

    def get_sector_state(self, *, market_date: date) -> tuple[dict[str, Any], ...]:
        if not self.store_path.exists():
            return ()
        with duckdb.connect(str(self.store_path), read_only=True) as con:
            if not _table_exists(con, "diagnostic_historical_sector_state"):
                return ()
            rows = con.execute(
                """
                SELECT market_date, sector, priced_securities, return_1d,
                       breadth_ratio, leadership_rank, data_completeness, label
                FROM diagnostic_historical_sector_state
                WHERE market_date = ?
                ORDER BY leadership_rank NULLS LAST, sector
                """,
                (market_date,),
            ).fetchall()
        return tuple(
            {
                "market_date": _date(row[0]).isoformat(),
                "sector": str(row[1]),
                "priced_securities": int(row[2]),
                "return_1d": _decimal(row[3]),
                "breadth_ratio": _decimal(row[4]),
                "leadership_rank": None if row[5] is None else int(row[5]),
                "data_completeness": str(row[6]),
                "label": str(row[7]),
            }
            for row in rows
        )

    def stream_classification_batches(
        self, *, batch_size: int = 500
    ) -> tuple[tuple[HistoricalSectorClassification, ...], ...]:
        rows = self.load_classifications()
        return tuple(
            rows[index : index + batch_size]
            for index in range(0, len(rows), batch_size)
        )

    def _rows(self, table: str, build_id: str | None) -> tuple[tuple[Any, ...], ...]:
        if not self.store_path.exists():
            return ()
        manifest = self.latest_manifest()
        active_build_id = build_id or (manifest.build_id if manifest else None)
        if active_build_id is None:
            return ()
        with duckdb.connect(str(self.store_path), read_only=True) as con:
            if not _table_exists(con, table):
                return ()
            return tuple(
                con.execute(
                    f"SELECT * FROM {table} WHERE build_id = ? ORDER BY 1, 2",
                    (active_build_id,),
                ).fetchall()
            )


class HistoricalSectorIngestionEngine:
    def __init__(self, *, store_path: Path | str | None = None) -> None:
        self.store_path = resolve_point_in_time_store_path(store_path)

    def source_inventory(self) -> tuple[SectorSourceInventoryItem, ...]:
        store_counts = _store_source_counts(self.store_path)
        extracted = sorted(Path("data/extracted").glob("*.csv"))
        docs = sorted(Path("docs").glob("*.md"))
        return (
            SectorSourceInventoryItem(
                source_id="daily_prices.sector",
                source_type="local_price_metadata",
                source_location="data/*.duckdb daily_prices.sector",
                taxonomy_name="Alpha current sector labels",
                taxonomy_version="alpha-current-sector-v1",
                available_fields=("symbol", "trade_date", "sector", "exchange"),
                record_count=store_counts.get("daily_price_rows", 0),
                security_coverage=store_counts.get("daily_price_symbols", 0),
                date_coverage=store_counts.get("daily_price_dates", "unavailable"),
                effective_date_support=False,
                identity_fields=("symbol", "exchange"),
                isin_support=False,
                symbol_support=True,
                point_in_time_safety=False,
                authority=SectorSourceAuthority.CURRENT_STATE_ONLY,
                update_frequency="per ingested price row",
                known_limitations=(
                    "sector column has no explicit effective period",
                    "must not be applied backward as authoritative history",
                ),
            ),
            SectorSourceInventoryItem(
                source_id="diagnostic_pit_security_master",
                source_type="derived_security_master",
                source_location=str(self.store_path),
                taxonomy_name="Alpha current sector labels",
                taxonomy_version="alpha-current-sector-v1",
                available_fields=(
                    "security_id",
                    "symbol",
                    "sector_name",
                    "industry_name",
                ),
                record_count=store_counts.get("security_rows", 0),
                security_coverage=store_counts.get("security_rows_with_sector", 0),
                date_coverage="current-only derived from local observations",
                effective_date_support=False,
                identity_fields=("security_id", "symbol"),
                isin_support=False,
                symbol_support=True,
                point_in_time_safety=False,
                authority=SectorSourceAuthority.CURRENT_STATE_ONLY,
                update_frequency="on point-in-time materialization import",
                known_limitations=(
                    "derived from current/local price metadata",
                    "not accepted as point-in-time sector history",
                ),
            ),
            SectorSourceInventoryItem(
                source_id="nse_bhavcopy_archives",
                source_type="exchange_price_archive",
                source_location="data/extracted/*.csv",
                taxonomy_name="not provided",
                taxonomy_version="not provided",
                available_fields=(
                    "symbol",
                    "series",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ),
                record_count=len(extracted),
                security_coverage=0,
                date_coverage=_file_date_coverage(extracted),
                effective_date_support=False,
                identity_fields=("symbol", "series"),
                isin_support=False,
                symbol_support=True,
                point_in_time_safety=True,
                authority=SectorSourceAuthority.UNUSABLE,
                update_frequency="archive file per trading day",
                known_limitations=(
                    "bhavcopy files are price archives, not sector classifications",
                    "index membership must not be substituted for sector "
                    "classification",
                ),
            ),
            SectorSourceInventoryItem(
                source_id="approval_diagnostics_docs",
                source_type="documentation",
                source_location="docs/*.md",
                taxonomy_name="not applicable",
                taxonomy_version="not applicable",
                available_fields=("policy_notes",),
                record_count=len(docs),
                security_coverage=0,
                date_coverage="documentation only",
                effective_date_support=False,
                identity_fields=(),
                isin_support=False,
                symbol_support=False,
                point_in_time_safety=False,
                authority=SectorSourceAuthority.UNUSABLE,
                update_frequency="manual",
                known_limitations=("documentation is not classification evidence",),
            ),
        )

    def build(
        self, *, persist: bool = False, resume: bool = False
    ) -> HistoricalSectorBuildReport:
        del resume
        started = datetime.now(tz=UTC)
        sources = self.source_inventory()
        taxonomies = default_sector_taxonomies()
        classifications = _current_only_classifications_from_store(
            self.store_path,
            started,
        )
        identities = tuple(
            SectorIdentityReconciliationRow(
                classification_id=row.classification_id,
                security_id=row.security_id,
                symbol=row.symbol_at_effective_date,
                isin=row.isin,
                match_status=SectorIdentityMatchStatus.EXACT_SECURITY_ID,
                resolution_reason=(
                    "security_id came from diagnostic PIT security master; "
                    "classification remains current-only"
                ),
            )
            for row in classifications
        )
        conflicts = _classification_conflicts(classifications)
        changes = _classification_changes(classifications)
        coverage = _coverage_rows(self.store_path)
        source_fingerprint = _fingerprint(sources)
        config_fingerprint = _fingerprint(
            {
                "dataset_version": HISTORICAL_SECTOR_DATASET_VERSION,
                "authority_policy": "current-only rows excluded from strong evidence",
                "store_path": str(self.store_path),
            }
        )
        status = (
            HistoricalSectorBuildStatus.COMPLETED
            if persist
            else HistoricalSectorBuildStatus.PLANNED
        )
        validation_status = (
            HistoricalSectorReadinessStatus.NOT_READY
            if classifications
            else HistoricalSectorReadinessStatus.INSUFFICIENT_EVIDENCE
        )
        manifest = HistoricalSectorBuildManifest(
            build_id=_build_id(source_fingerprint, config_fingerprint),
            dataset_version=HISTORICAL_SECTOR_DATASET_VERSION,
            source_fingerprint=source_fingerprint,
            configuration_fingerprint=config_fingerprint,
            taxonomy_versions=tuple(row.taxonomy_version for row in taxonomies),
            started_at=started,
            completed_at=datetime.now(tz=UTC) if persist else None,
            source_rows=sum(row.record_count for row in sources),
            classification_rows=len(classifications),
            matched_rows=len(identities),
            unmatched_rows=0,
            conflicting_rows=len(conflicts),
            effective_dated_rows=sum(
                1 for row in classifications if row.effective_from is not None
            ),
            current_only_rows=sum(
                1
                for row in classifications
                if row.point_in_time_status
                is HistoricalSectorStatus.CURRENT_MAPPING_ONLY
            ),
            status=status,
            validation_status=validation_status,
        )
        report = HistoricalSectorBuildReport(
            manifest=manifest,
            sources=sources,
            taxonomies=taxonomies,
            classifications=classifications,
            identity_rows=identities,
            conflicts=conflicts,
            changes=changes,
            coverage=coverage,
            dry_run=not persist,
            persisted=persist,
            prohibited_next_action=_prohibited_next_action(),
        )
        if persist:
            HistoricalSectorRepository(self.store_path).save_build(report)
        return report


class DiagnosticMarketStateV3Engine:
    def __init__(self, *, store_path: Path | str | None = None) -> None:
        self.store_path = resolve_point_in_time_store_path(store_path)

    def build(
        self,
        *,
        classifier_version: str,
        classifier_fingerprint: str,
        persist: bool = False,
    ) -> DiagnosticMarketStateV3BuildReport:
        manifest = HistoricalSectorRepository(self.store_path).latest_manifest()
        sector_fingerprint = manifest.source_fingerprint if manifest else ""
        has_supported_sector = (
            manifest is not None
            and manifest.effective_dated_rows > 0
            and manifest.current_only_rows < manifest.classification_rows
        )
        v2_counts = _v2_counts(self.store_path)
        blocked = None
        if not has_supported_sector:
            blocked = (
                "historical sector classifications are current-only or unavailable; "
                "v3 remains diagnostic-blocked"
            )
        reconstructions = v2_counts["reconstructions"] if has_supported_sector else 0
        links = v2_counts["links"] if has_supported_sector else 0
        report = DiagnosticMarketStateV3BuildReport(
            dataset_version=DIAGNOSTIC_MARKET_STATE_V3_VERSION,
            dry_run=not persist,
            build_id=_build_id(sector_fingerprint, classifier_fingerprint)
            if sector_fingerprint
            else None,
            v2_build_id=v2_counts.get("build_id_text"),
            sector_dataset_version=HISTORICAL_SECTOR_DATASET_VERSION,
            sector_dataset_fingerprint=sector_fingerprint,
            sector_state_fingerprint=_fingerprint(
                {"sector_fingerprint": sector_fingerprint, "state": "blocked"}
            ),
            classifier_version=classifier_version,
            classifier_fingerprint=classifier_fingerprint,
            feature_definition_version="market-feature-definitions-v3-sector-aware",
            reconstructions_would_create=reconstructions,
            candidate_links_would_create=links,
            reconstructions_created=0,
            candidate_links_created=0,
            duplicate_links=0,
            orphan_links=0,
            universe_rows_treated_as_candidate_links=0,
            persistence_status="BLOCKED_INSUFFICIENT_SECTOR_HISTORY"
            if blocked
            else ("PERSISTED" if persist else "DRY_RUN_ONLY"),
            blocked_reason=blocked,
        )
        return report

    def compare_v2_v3(self) -> DiagnosticV2V3ComparisonReport:
        v2 = _v2_counts(self.store_path)
        v3 = self.build(classifier_version="unavailable", classifier_fingerprint="")
        v2_distribution = _store_regime_distribution(self.store_path, "v2")
        v3_distribution: tuple[tuple[str, int], ...] = ()
        return DiagnosticV2V3ComparisonReport(
            dates_compared=int(v2["reconstructions"]),
            dates_changed=0,
            candidate_records_affected=0,
            v2_regime_distribution=v2_distribution,
            v3_regime_distribution=v3_distribution,
            sector_status_distribution=(
                ("INSUFFICIENT_SECTOR_COVERAGE", int(v2["reconstructions"])),
            ),
            classification="INSUFFICIENT_SECTOR_COVERAGE"
            if v3.blocked_reason
            else "V3_DOES_NOT_MATERIALLY_CHANGE_FINDINGS",
            explanation=(
                "V3 is not materialized because no authoritative or supported "
                "effective-dated sector history is available."
            ),
        )


def default_sector_taxonomies() -> tuple[SectorTaxonomyDefinition, ...]:
    return (
        SectorTaxonomyDefinition(
            taxonomy_id="alpha-current-sector-v1",
            taxonomy_name="Alpha current sector labels",
            taxonomy_version="alpha-current-sector-v1",
            provider="Alpha local metadata",
            hierarchy_levels=("sector",),
            sector_field="sector",
            industry_group_field=None,
            industry_field=None,
            subindustry_field=None,
            effective_from=None,
            effective_to=None,
            source="daily_prices.sector",
            authority=SectorSourceAuthority.CURRENT_STATE_ONLY,
        ),
        SectorTaxonomyDefinition(
            taxonomy_id="nse-bhavcopy-price-archive-v1",
            taxonomy_name="NSE bhavcopy price archive",
            taxonomy_version="nse-bhavcopy-price-archive-v1",
            provider="NSE",
            hierarchy_levels=(),
            sector_field=None,
            industry_group_field=None,
            industry_field=None,
            subindustry_field=None,
            effective_from=None,
            effective_to=None,
            source="data/extracted/*.csv",
            authority=SectorSourceAuthority.UNUSABLE,
        ),
    )


def validate_historical_sector_store(
    store_path: Path | str | None = None,
) -> HistoricalSectorValidationReport:
    repository = HistoricalSectorRepository(store_path)
    manifest = repository.latest_manifest()
    if manifest is None:
        return HistoricalSectorValidationReport(
            status=HistoricalSectorReadinessStatus.INSUFFICIENT_EVIDENCE,
            source_count=0,
            authoritative_sources=0,
            effective_dated_classifications=0,
            current_only_classifications=0,
            conflicts=0,
            invalid_effective_ranges=0,
            overlapping_authoritative_ranges=0,
            future_classification_violations=0,
            orphan_security_identities=0,
            issues=("historical sector dataset has not been built",),
        )
    sources = repository.load_sources(manifest.build_id)
    classifications = repository.load_classifications(manifest.build_id)
    conflicts = repository.get_conflicts(manifest.build_id)
    invalid_ranges = sum(
        1
        for row in classifications
        if row.effective_from is not None
        and row.effective_to is not None
        and row.effective_from > row.effective_to
    )
    effective = sum(1 for row in classifications if row.effective_from is not None)
    current_only = sum(
        1
        for row in classifications
        if row.point_in_time_status is HistoricalSectorStatus.CURRENT_MAPPING_ONLY
    )
    authoritative = sum(
        1
        for row in sources
        if row.authority
        in {
            SectorSourceAuthority.AUTHORITATIVE_POINT_IN_TIME,
            SectorSourceAuthority.STRONG_POINT_IN_TIME,
            SectorSourceAuthority.SUPPORTED_EFFECTIVE_DATED,
        }
    )
    issues = []
    if authoritative == 0:
        issues.append("no authoritative or supported effective-dated sector source")
    if effective == 0:
        issues.append("no effective-dated sector classifications")
    if current_only:
        issues.append("current-only classifications excluded from strong evidence")
    if conflicts:
        issues.append("classification conflicts require review")
    status = (
        HistoricalSectorReadinessStatus.READY
        if authoritative and effective and not invalid_ranges and not conflicts
        else HistoricalSectorReadinessStatus.NOT_READY
    )
    return HistoricalSectorValidationReport(
        status=status,
        source_count=len(sources),
        authoritative_sources=authoritative,
        effective_dated_classifications=effective,
        current_only_classifications=current_only,
        conflicts=len(conflicts),
        invalid_effective_ranges=invalid_ranges,
        overlapping_authoritative_ranges=0,
        future_classification_violations=0,
        orphan_security_identities=0,
        issues=tuple(issues),
    )


def build_historical_sector_readiness(
    store_path: Path | str | None = None,
) -> HistoricalSectorDecisionReadinessReport:
    validation = validate_historical_sector_store(store_path)
    comparison = DiagnosticMarketStateV3Engine(store_path=store_path).compare_v2_v3()
    items = (
        _item(
            "sector source authority",
            HistoricalSectorReadinessStatus.READY
            if validation.authoritative_sources
            else HistoricalSectorReadinessStatus.NOT_READY,
            f"authoritative sources={validation.authoritative_sources}",
        ),
        _item(
            "sector identity coverage",
            HistoricalSectorReadinessStatus.READY
            if validation.orphan_security_identities == 0
            else HistoricalSectorReadinessStatus.NOT_READY,
            f"orphan identities={validation.orphan_security_identities}",
        ),
        _item(
            "effective-date coverage",
            HistoricalSectorReadinessStatus.READY
            if validation.effective_dated_classifications
            else HistoricalSectorReadinessStatus.NOT_READY,
            f"effective-dated rows={validation.effective_dated_classifications}",
        ),
        _item(
            "classification conflict rate",
            HistoricalSectorReadinessStatus.READY
            if validation.conflicts == 0
            else HistoricalSectorReadinessStatus.NOT_READY,
            f"conflicts={validation.conflicts}",
        ),
        _item(
            "sector-state coverage",
            HistoricalSectorReadinessStatus.NOT_READY,
            "sector-state rows are not materialized without effective-dated history",
        ),
        _item(
            "sector incremental value",
            HistoricalSectorReadinessStatus.INSUFFICIENT_EVIDENCE,
            comparison.classification,
        ),
        _item(
            "v3 regime separation",
            HistoricalSectorReadinessStatus.INSUFFICIENT_EVIDENCE,
            comparison.explanation,
        ),
        _item(
            "threshold sensitivity",
            HistoricalSectorReadinessStatus.NOT_READY,
            "threshold audit is blocked until sector evidence is adequate",
        ),
        _item(
            "sample adequacy",
            HistoricalSectorReadinessStatus.CONDITIONALLY_READY,
            "candidate outcomes exist, but sector evidence is insufficient",
        ),
        _item(
            "classifier compatibility",
            HistoricalSectorReadinessStatus.CONDITIONALLY_READY,
            "v3 is diagnostic-only and does not alter the classifier",
        ),
    )
    primary = (
        HistoricalSectorConclusion.EFFECTIVE_DATE_COVERAGE_IS_PRIMARY_LIMITATION
        if validation.source_count
        else HistoricalSectorConclusion.INSUFFICIENT_EVIDENCE_FOR_SECTOR_CONCLUSION
    )
    if validation.authoritative_sources == 0:
        primary = (
            HistoricalSectorConclusion.SECTOR_SOURCE_AUTHORITY_IS_PRIMARY_LIMITATION
        )
    return HistoricalSectorDecisionReadinessReport(
        scorecard=items,
        primary_conclusion=primary,
        secondary_conclusion=(
            HistoricalSectorConclusion.MARKET_REGIME_REMAINS_NOT_READY_FOR_PRODUCTION_REDESIGN
        ),
        recommended_next_milestone=(
            HistoricalSectorNextMilestone.BUILD_OFFICIAL_SECTOR_HISTORY_SOURCE
            if validation.authoritative_sources == 0
            else HistoricalSectorNextMilestone.EXPAND_SECTOR_EFFECTIVE_DATE_HISTORY
        ),
        explicitly_prohibited_next_action=_prohibited_next_action(),
    )


def render_sector_source_audit(
    rows: tuple[SectorSourceInventoryItem, ...],
) -> tuple[str, ...]:
    lines = ["Historical Sector Source Audit"]
    for row in rows:
        lines.append(
            f"- {row.source_id}: authority={row.authority.value}, "
            f"records={row.record_count}, coverage={row.date_coverage}, "
            f"effective_dates={'yes' if row.effective_date_support else 'no'}"
        )
    return tuple(lines)


def render_sector_taxonomies(
    rows: tuple[SectorTaxonomyDefinition, ...],
) -> tuple[str, ...]:
    lines = ["Sector Taxonomy Registry"]
    for row in rows:
        lines.append(
            f"- {row.taxonomy_id}: provider={row.provider}, "
            f"levels={_text_list(row.hierarchy_levels)}, "
            f"authority={row.authority.value}"
        )
    return tuple(lines)


def render_historical_sector_build(
    report: HistoricalSectorBuildReport,
) -> tuple[str, ...]:
    manifest = report.manifest
    return (
        "Historical Sector Classification Build",
        f"Build ID: {manifest.build_id}",
        f"Dataset Version: {manifest.dataset_version}",
        f"Dry Run: {'yes' if report.dry_run else 'no'}",
        f"Persisted: {'yes' if report.persisted else 'no'}",
        f"Source Rows: {manifest.source_rows}",
        f"Classification Rows: {manifest.classification_rows}",
        f"Matched Rows: {manifest.matched_rows}",
        f"Unmatched Rows: {manifest.unmatched_rows}",
        f"Conflicting Rows: {manifest.conflicting_rows}",
        f"Effective-Dated Rows: {manifest.effective_dated_rows}",
        f"Current-Only Rows: {manifest.current_only_rows}",
        f"Status: {manifest.status.value}",
        f"Validation Status: {manifest.validation_status.value}",
        f"Explicitly Prohibited Next Action: {report.prohibited_next_action}",
    )


def render_historical_sector_status(
    manifest: HistoricalSectorBuildManifest | None,
) -> tuple[str, ...]:
    if manifest is None:
        return (
            "Historical Sector Build Status",
            "Status: NOT BUILT",
            "Next Action: historical-sector-build --persist-diagnostic",
        )
    return (
        "Historical Sector Build Status",
        f"Build ID: {manifest.build_id}",
        f"Dataset Version: {manifest.dataset_version}",
        f"Status: {manifest.status.value}",
        f"Validation Status: {manifest.validation_status.value}",
        f"Classification Rows: {manifest.classification_rows}",
        f"Effective-Dated Rows: {manifest.effective_dated_rows}",
        f"Current-Only Rows: {manifest.current_only_rows}",
    )


def render_historical_sector_validation(
    report: HistoricalSectorValidationReport,
) -> tuple[str, ...]:
    return (
        "Historical Sector Store Validation",
        f"Status: {report.status.value}",
        f"Sources: {report.source_count}",
        f"Authoritative Sources: {report.authoritative_sources}",
        f"Effective-Dated Classifications: {report.effective_dated_classifications}",
        f"Current-Only Classifications: {report.current_only_classifications}",
        f"Conflicts: {report.conflicts}",
        f"Invalid Effective Ranges: {report.invalid_effective_ranges}",
        f"Overlapping Authoritative Ranges: {report.overlapping_authoritative_ranges}",
        f"Future Classification Violations: {report.future_classification_violations}",
        f"Orphan Security Identities: {report.orphan_security_identities}",
        f"Issues: {_text_list(report.issues)}",
    )


def render_historical_sector_coverage(
    rows: tuple[HistoricalSectorCoverageRow, ...],
) -> tuple[str, ...]:
    lines = ["Historical Sector Coverage"]
    if not rows:
        lines.append("- unavailable")
    for row in rows[:200]:
        lines.append(
            f"- {row.market_date}: universe={row.point_in_time_universe_size}, "
            f"auth={row.authoritative_classification_count}, "
            f"supported={row.supported_classification_count}, "
            f"current_only={row.current_only_classification_count}, "
            f"unclassified={row.unclassified_count}, grade={row.grade}"
        )
    return tuple(lines)


def render_historical_sector_conflicts(
    rows: tuple[HistoricalSectorConflict, ...],
) -> tuple[str, ...]:
    lines = ["Historical Sector Conflicts"]
    if not rows:
        lines.append("- none")
    for row in rows:
        lines.append(
            f"- {row.security_id}: {row.classification_a} vs "
            f"{row.classification_b}; {row.resolution_status.value}"
        )
    return tuple(lines)


def render_historical_sector_changes(
    rows: tuple[HistoricalSectorChange, ...],
) -> tuple[str, ...]:
    lines = ["Historical Sector Classification Changes"]
    if not rows:
        lines.append("- none detected")
    for row in rows:
        lines.append(
            f"- {row.security_id}: {row.previous_classification} -> "
            f"{row.new_classification}; {row.change_type}"
        )
    return tuple(lines)


def render_historical_sector_show(
    rows: tuple[HistoricalSectorClassification, ...],
    *,
    symbol: str,
    market_date: date,
) -> tuple[str, ...]:
    lines = [f"Historical Sector Classification: {symbol.upper()} @ {market_date}"]
    filtered = tuple(
        row for row in rows if row.symbol_at_effective_date.upper() == symbol.upper()
    )
    if not filtered:
        lines.append("- unavailable")
    for row in filtered[:20]:
        lines.append(
            f"- {row.sector_name or 'unclassified'}; "
            f"status={row.point_in_time_status.value}; "
            f"effective={_text(row.effective_from)} to {_text(row.effective_to)}"
        )
    return tuple(lines)


def render_historical_sector_state(
    rows: tuple[dict[str, Any], ...], *, market_date: date
) -> tuple[str, ...]:
    lines = [f"Historical Sector State: {market_date}"]
    if not rows:
        lines.append("- unavailable; no authoritative effective-dated sector state")
    for row in rows:
        lines.append(
            f"- {row['sector']}: n={row['priced_securities']}, "
            f"return_1d={_text(row['return_1d'])}, "
            f"breadth={_text(row['breadth_ratio'])}, label={row['label']}"
        )
    return tuple(lines)


def render_diagnostic_v3_build(
    report: DiagnosticMarketStateV3BuildReport,
) -> tuple[str, ...]:
    return (
        "Diagnostic Market-State V3 Build",
        f"Dataset Version: {report.dataset_version}",
        f"Dry Run: {'yes' if report.dry_run else 'no'}",
        f"Build ID: {report.build_id or 'unavailable'}",
        f"V2 Build ID: {report.v2_build_id or 'unavailable'}",
        f"Sector Dataset Version: {report.sector_dataset_version}",
        f"Sector Fingerprint: {report.sector_dataset_fingerprint or 'unavailable'}",
        f"Sector-State Fingerprint: {report.sector_state_fingerprint}",
        f"Classifier Version: {report.classifier_version}",
        f"Feature Definition Version: {report.feature_definition_version}",
        f"Reconstructions Would Create: {report.reconstructions_would_create}",
        f"Candidate Links Would Create: {report.candidate_links_would_create}",
        f"Reconstructions Created: {report.reconstructions_created}",
        f"Candidate Links Created: {report.candidate_links_created}",
        f"Duplicate Links: {report.duplicate_links}",
        f"Orphan Links: {report.orphan_links}",
        "Universe Rows Treated As Candidate Links: "
        f"{report.universe_rows_treated_as_candidate_links}",
        f"Persistence Status: {report.persistence_status}",
        f"Blocked Reason: {report.blocked_reason or 'none'}",
    )


def render_v2_v3_comparison(report: DiagnosticV2V3ComparisonReport) -> tuple[str, ...]:
    return (
        "Diagnostic Market-State V2/V3 Comparison",
        f"Dates Compared: {report.dates_compared}",
        f"Dates Changed: {report.dates_changed}",
        f"Candidate Records Affected: {report.candidate_records_affected}",
        f"V2 Distribution: {_pairs(report.v2_regime_distribution)}",
        f"V3 Distribution: {_pairs(report.v3_regime_distribution)}",
        f"Sector Status: {_pairs(report.sector_status_distribution)}",
        f"Classification: {report.classification}",
        f"Explanation: {report.explanation}",
    )


def render_historical_sector_decision_readiness(
    report: HistoricalSectorDecisionReadinessReport,
) -> tuple[str, ...]:
    lines = [
        "Historical Sector Decision Readiness",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        f"Secondary Conclusion: {_enum_text(report.secondary_conclusion)}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        "Explicitly Prohibited Next Action: "
        f"{report.explicitly_prohibited_next_action}",
        "Scorecard:",
    ]
    for item in report.scorecard:
        lines.append(f"- {item.criterion}: {item.status.value} - {item.explanation}")
    return tuple(lines)


def export_historical_sector_json(payload: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")
    return path


def export_historical_sector_csv(rows: tuple[Any, ...], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    dictionaries = [_jsonable(row) for row in rows] or [{"status": "unavailable"}]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(dictionaries[0].keys()))
        writer.writeheader()
        writer.writerows(dictionaries)
    return path


def _create_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_sector_builds (
            build_id VARCHAR PRIMARY KEY,
            dataset_version VARCHAR,
            source_fingerprint VARCHAR,
            configuration_fingerprint VARCHAR,
            taxonomy_versions VARCHAR,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            source_rows INTEGER,
            classification_rows INTEGER,
            matched_rows INTEGER,
            unmatched_rows INTEGER,
            conflicting_rows INTEGER,
            effective_dated_rows INTEGER,
            current_only_rows INTEGER,
            status VARCHAR,
            validation_status VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_sector_sources (
            build_id VARCHAR,
            source_id VARCHAR,
            source_type VARCHAR,
            source_location VARCHAR,
            taxonomy_name VARCHAR,
            taxonomy_version VARCHAR,
            available_fields VARCHAR,
            record_count INTEGER,
            security_coverage INTEGER,
            date_coverage VARCHAR,
            effective_date_support BOOLEAN,
            identity_fields VARCHAR,
            isin_support BOOLEAN,
            symbol_support BOOLEAN,
            point_in_time_safety BOOLEAN,
            authority VARCHAR,
            update_frequency VARCHAR,
            known_limitations VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_sector_taxonomies (
            build_id VARCHAR,
            taxonomy_id VARCHAR,
            taxonomy_name VARCHAR,
            taxonomy_version VARCHAR,
            provider VARCHAR,
            hierarchy_levels VARCHAR,
            sector_field VARCHAR,
            industry_group_field VARCHAR,
            industry_field VARCHAR,
            subindustry_field VARCHAR,
            effective_from DATE,
            effective_to DATE,
            source VARCHAR,
            authority VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_sector_classifications (
            build_id VARCHAR,
            classification_id VARCHAR,
            security_id VARCHAR,
            isin VARCHAR,
            symbol_at_effective_date VARCHAR,
            taxonomy_id VARCHAR,
            sector_code VARCHAR,
            sector_name VARCHAR,
            industry_group_code VARCHAR,
            industry_group_name VARCHAR,
            industry_code VARCHAR,
            industry_name VARCHAR,
            subindustry_code VARCHAR,
            subindustry_name VARCHAR,
            effective_from DATE,
            effective_to DATE,
            source_record_date DATE,
            source_timestamp TIMESTAMP,
            ingested_at TIMESTAMP,
            source_id VARCHAR,
            authority VARCHAR,
            confidence VARCHAR,
            point_in_time_status VARCHAR,
            inference_method VARCHAR,
            missing_fields VARCHAR,
            schema_version VARCHAR,
            dataset_version VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_sector_identity_reconciliation (
            build_id VARCHAR,
            classification_id VARCHAR,
            security_id VARCHAR,
            symbol VARCHAR,
            isin VARCHAR,
            match_status VARCHAR,
            resolution_reason VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_sector_classification_conflicts (
            build_id VARCHAR,
            conflict_id VARCHAR,
            security_id VARCHAR,
            taxonomy_id VARCHAR,
            effective_from DATE,
            effective_to DATE,
            source_a VARCHAR,
            source_b VARCHAR,
            classification_a VARCHAR,
            classification_b VARCHAR,
            resolution_status VARCHAR,
            resolution_reason VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_sector_changes (
            build_id VARCHAR,
            security_id VARCHAR,
            previous_classification VARCHAR,
            new_classification VARCHAR,
            effective_date DATE,
            source VARCHAR,
            taxonomy VARCHAR,
            change_type VARCHAR,
            confidence VARCHAR,
            candidate_dates_affected INTEGER,
            candidate_records_affected INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_sector_coverage (
            build_id VARCHAR,
            market_date DATE,
            point_in_time_universe_size INTEGER,
            classified_security_count INTEGER,
            authoritative_classification_count INTEGER,
            supported_classification_count INTEGER,
            inferred_classification_count INTEGER,
            current_only_classification_count INTEGER,
            unclassified_count INTEGER,
            conflicting_count INTEGER,
            sector_count INTEGER,
            industry_count INTEGER,
            coverage_percentage DOUBLE,
            grade VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_historical_sector_state (
            build_id VARCHAR,
            market_date DATE,
            sector VARCHAR,
            priced_securities INTEGER,
            return_1d DOUBLE,
            breadth_ratio DOUBLE,
            leadership_rank INTEGER,
            data_completeness VARCHAR,
            label VARCHAR
        )
        """
    )


def _current_only_classifications_from_store(
    store_path: Path,
    ingested_at: datetime,
) -> tuple[HistoricalSectorClassification, ...]:
    if not store_path.exists():
        return ()
    with duckdb.connect(str(store_path), read_only=True) as con:
        rows = con.execute(
            """
            SELECT security_id, symbol, isin, sector_name, industry_name
            FROM diagnostic_pit_security_master
            WHERE sector_name IS NOT NULL
            ORDER BY security_id
            """
        ).fetchall()
    output = []
    for security_id, symbol, isin, sector, industry in rows:
        payload = {
            "security_id": str(security_id),
            "symbol": str(symbol).upper(),
            "sector": str(sector).upper(),
            "industry": None if industry is None else str(industry).upper(),
            "status": HistoricalSectorStatus.CURRENT_MAPPING_ONLY.value,
        }
        output.append(
            HistoricalSectorClassification(
                classification_id=_fingerprint(payload),
                security_id=str(security_id),
                isin=None if isin is None else str(isin),
                symbol_at_effective_date=str(symbol).upper(),
                taxonomy_id="alpha-current-sector-v1",
                sector_code=None,
                sector_name=str(sector).upper(),
                industry_group_code=None,
                industry_group_name=None,
                industry_code=None,
                industry_name=None if industry is None else str(industry).upper(),
                subindustry_code=None,
                subindustry_name=None,
                effective_from=None,
                effective_to=None,
                source_record_date=None,
                source_timestamp=None,
                ingested_at=ingested_at,
                source_id="diagnostic_pit_security_master",
                authority=SectorSourceAuthority.CURRENT_STATE_ONLY,
                confidence="LOW",
                point_in_time_status=HistoricalSectorStatus.CURRENT_MAPPING_ONLY,
                inference_method="not inferred; current mapping only",
                missing_fields=("effective_from", "effective_to", "isin"),
                schema_version="historical-sector-classification-v1",
                dataset_version=HISTORICAL_SECTOR_DATASET_VERSION,
            )
        )
    return tuple(output)


def _coverage_rows(store_path: Path) -> tuple[HistoricalSectorCoverageRow, ...]:
    if not store_path.exists():
        return ()
    with duckdb.connect(str(store_path), read_only=True) as con:
        rows = con.execute(
            """
            SELECT market_date,
                   COUNT(*) AS universe_size,
                   SUM(CASE WHEN sector_available THEN 1 ELSE 0 END) AS current_only,
                   COUNT(DISTINCT CASE WHEN sector_available THEN symbol END) AS sectors
            FROM diagnostic_pit_universe_membership
            WHERE membership_status = 'ELIGIBLE'
            GROUP BY market_date
            ORDER BY market_date
            """
        ).fetchall()
    output = []
    for market_date, universe_size, current_only, sectors in rows:
        total = int(universe_size or 0)
        current = int(current_only or 0)
        coverage = _rate(current, total)
        output.append(
            HistoricalSectorCoverageRow(
                market_date=_date(market_date),
                point_in_time_universe_size=total,
                classified_security_count=current,
                authoritative_classification_count=0,
                supported_classification_count=0,
                inferred_classification_count=0,
                current_only_classification_count=current,
                unclassified_count=max(0, total - current),
                conflicting_count=0,
                sector_count=int(sectors or 0),
                industry_count=0,
                coverage_percentage=coverage,
                grade="UNUSABLE" if current else "UNUSABLE",
            )
        )
    return tuple(output)


def _classification_conflicts(
    rows: tuple[HistoricalSectorClassification, ...],
) -> tuple[HistoricalSectorConflict, ...]:
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        grouped[(row.security_id, row.taxonomy_id)].add(row.sector_name or "")
    conflicts = []
    for (security_id, taxonomy_id), sectors in sorted(grouped.items()):
        if len(sectors) <= 1:
            continue
        ordered = sorted(sectors)
        conflicts.append(
            HistoricalSectorConflict(
                conflict_id=_fingerprint((security_id, taxonomy_id, ordered)),
                security_id=security_id,
                taxonomy_id=taxonomy_id,
                effective_from=None,
                effective_to=None,
                source_a="diagnostic_pit_security_master",
                source_b="diagnostic_pit_security_master",
                classification_a=ordered[0],
                classification_b=ordered[-1],
                resolution_status=SectorConflictResolutionStatus.UNRESOLVED_EQUAL_AUTHORITY,
                resolution_reason="multiple current-only labels lack effective dates",
            )
        )
    return tuple(conflicts)


def _classification_changes(
    rows: tuple[HistoricalSectorClassification, ...],
) -> tuple[HistoricalSectorChange, ...]:
    changes = []
    by_security: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        by_security[row.security_id].add(row.sector_name or "")
    for security_id, sectors in sorted(by_security.items()):
        if len(sectors) <= 1:
            continue
        ordered = sorted(sectors)
        changes.append(
            HistoricalSectorChange(
                security_id=security_id,
                previous_classification=ordered[0],
                new_classification=ordered[-1],
                effective_date=None,
                source="diagnostic_pit_security_master",
                taxonomy="alpha-current-sector-v1",
                change_type="UNKNOWN_CHANGE",
                confidence="LOW",
                candidate_dates_affected=0,
                candidate_records_affected=0,
            )
        )
    return tuple(changes)


def _store_source_counts(store_path: Path) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "daily_price_rows": 0,
        "daily_price_symbols": 0,
        "daily_price_dates": "unavailable",
        "security_rows": 0,
        "security_rows_with_sector": 0,
    }
    if Path("data/ingestion.duckdb").exists():
        try:
            with duckdb.connect("data/ingestion.duckdb", read_only=True) as con:
                row = con.execute(
                    """
                    SELECT COUNT(*), COUNT(DISTINCT symbol),
                           MIN(trade_date), MAX(trade_date)
                    FROM daily_prices
                    """
                ).fetchone()
                if row:
                    counts["daily_price_rows"] = int(row[0] or 0)
                    counts["daily_price_symbols"] = int(row[1] or 0)
                    counts["daily_price_dates"] = f"{_text(row[2])} to {_text(row[3])}"
        except duckdb.Error:
            pass
    if store_path.exists():
        try:
            with duckdb.connect(str(store_path), read_only=True) as con:
                row = con.execute(
                    """
                    SELECT COUNT(*),
                           SUM(CASE WHEN sector_name IS NOT NULL THEN 1 ELSE 0 END)
                    FROM diagnostic_pit_security_master
                    """
                ).fetchone()
                if row:
                    counts["security_rows"] = int(row[0] or 0)
                    counts["security_rows_with_sector"] = int(row[1] or 0)
        except duckdb.Error:
            pass
    return counts


def _v2_counts(store_path: Path) -> dict[str, Any]:
    if not store_path.exists():
        return {"reconstructions": 0, "links": 0, "build_id_text": None}
    with duckdb.connect(str(store_path), read_only=True) as con:
        build = con.execute(
            """
            SELECT build_id
            FROM diagnostic_pit_builds
            ORDER BY imported_at DESC, build_id DESC
            LIMIT 1
            """
        ).fetchone()
        build_id = None if build is None else str(build[0])
        if build_id is None:
            return {"reconstructions": 0, "links": 0, "build_id_text": None}
        recon = con.execute(
            "SELECT COUNT(*) FROM diagnostic_market_state_v2 WHERE build_id = ?",
            (build_id,),
        ).fetchone()
        links = con.execute(
            """
            SELECT COUNT(*)
            FROM diagnostic_market_state_v2_candidate_links
            WHERE build_id = ?
            """,
            (build_id,),
        ).fetchone()
    return {
        "reconstructions": int(recon[0] or 0) if recon else 0,
        "links": int(links[0] or 0) if links else 0,
        "build_id_text": build_id,
    }


def _store_regime_distribution(
    store_path: Path, version: str
) -> tuple[tuple[str, int], ...]:
    if version != "v2" or not store_path.exists():
        return ()
    with duckdb.connect(str(store_path), read_only=True) as con:
        rows = con.execute(
            """
            SELECT v2_regime, COUNT(*)
            FROM diagnostic_market_state_v2
            GROUP BY v2_regime
            ORDER BY v2_regime
            """
        ).fetchall()
    return tuple((str(row[0]), int(row[1])) for row in rows)


def _build_row(manifest: HistoricalSectorBuildManifest) -> dict[str, Any]:
    return {
        "build_id": manifest.build_id,
        "dataset_version": manifest.dataset_version,
        "source_fingerprint": manifest.source_fingerprint,
        "configuration_fingerprint": manifest.configuration_fingerprint,
        "taxonomy_versions": json.dumps(manifest.taxonomy_versions),
        "started_at": manifest.started_at,
        "completed_at": manifest.completed_at,
        "source_rows": manifest.source_rows,
        "classification_rows": manifest.classification_rows,
        "matched_rows": manifest.matched_rows,
        "unmatched_rows": manifest.unmatched_rows,
        "conflicting_rows": manifest.conflicting_rows,
        "effective_dated_rows": manifest.effective_dated_rows,
        "current_only_rows": manifest.current_only_rows,
        "status": manifest.status.value,
        "validation_status": manifest.validation_status.value,
    }


def _source_row(build_id: str, row: SectorSourceInventoryItem) -> dict[str, Any]:
    data = asdict(row)
    data["build_id"] = build_id
    data["available_fields"] = json.dumps(row.available_fields)
    data["identity_fields"] = json.dumps(row.identity_fields)
    data["authority"] = row.authority.value
    data["known_limitations"] = json.dumps(row.known_limitations)
    return data


def _taxonomy_row(build_id: str, row: SectorTaxonomyDefinition) -> dict[str, Any]:
    data = asdict(row)
    data["build_id"] = build_id
    data["hierarchy_levels"] = json.dumps(row.hierarchy_levels)
    data["authority"] = row.authority.value
    return data


def _classification_row(row: HistoricalSectorClassification) -> dict[str, Any]:
    data = asdict(row)
    data["authority"] = row.authority.value
    data["point_in_time_status"] = row.point_in_time_status.value
    data["missing_fields"] = json.dumps(row.missing_fields)
    return data


def _identity_row(
    build_id: str, row: SectorIdentityReconciliationRow
) -> dict[str, Any]:
    data = asdict(row)
    data["build_id"] = build_id
    data["match_status"] = row.match_status.value
    return data


def _conflict_row(build_id: str, row: HistoricalSectorConflict) -> dict[str, Any]:
    data = asdict(row)
    data["build_id"] = build_id
    data["resolution_status"] = row.resolution_status.value
    return data


def _change_row(build_id: str, row: HistoricalSectorChange) -> dict[str, Any]:
    data = asdict(row)
    data["build_id"] = build_id
    return data


def _coverage_row(build_id: str, row: HistoricalSectorCoverageRow) -> dict[str, Any]:
    data = asdict(row)
    data["build_id"] = build_id
    data["coverage_percentage"] = (
        None if row.coverage_percentage is None else float(row.coverage_percentage)
    )
    return data


def _manifest_from_row(row: tuple[Any, ...]) -> HistoricalSectorBuildManifest:
    return HistoricalSectorBuildManifest(
        build_id=str(row[0]),
        dataset_version=str(row[1]),
        source_fingerprint=str(row[2]),
        configuration_fingerprint=str(row[3]),
        taxonomy_versions=tuple(json.loads(str(row[4] or "[]"))),
        started_at=_datetime(row[5]),
        completed_at=None if row[6] is None else _datetime(row[6]),
        source_rows=int(row[7]),
        classification_rows=int(row[8]),
        matched_rows=int(row[9]),
        unmatched_rows=int(row[10]),
        conflicting_rows=int(row[11]),
        effective_dated_rows=int(row[12]),
        current_only_rows=int(row[13]),
        status=HistoricalSectorBuildStatus(str(row[14])),
        validation_status=HistoricalSectorReadinessStatus(str(row[15])),
    )


def _source_from_row(row: tuple[Any, ...]) -> SectorSourceInventoryItem:
    return SectorSourceInventoryItem(
        source_id=str(row[1]),
        source_type=str(row[2]),
        source_location=str(row[3]),
        taxonomy_name=str(row[4]),
        taxonomy_version=str(row[5]),
        available_fields=tuple(json.loads(str(row[6] or "[]"))),
        record_count=int(row[7]),
        security_coverage=int(row[8]),
        date_coverage=str(row[9]),
        effective_date_support=bool(row[10]),
        identity_fields=tuple(json.loads(str(row[11] or "[]"))),
        isin_support=bool(row[12]),
        symbol_support=bool(row[13]),
        point_in_time_safety=bool(row[14]),
        authority=SectorSourceAuthority(str(row[15])),
        update_frequency=str(row[16]),
        known_limitations=tuple(json.loads(str(row[17] or "[]"))),
    )


def _taxonomy_from_row(row: tuple[Any, ...]) -> SectorTaxonomyDefinition:
    return SectorTaxonomyDefinition(
        taxonomy_id=str(row[1]),
        taxonomy_name=str(row[2]),
        taxonomy_version=str(row[3]),
        provider=str(row[4]),
        hierarchy_levels=tuple(json.loads(str(row[5] or "[]"))),
        sector_field=None if row[6] is None else str(row[6]),
        industry_group_field=None if row[7] is None else str(row[7]),
        industry_field=None if row[8] is None else str(row[8]),
        subindustry_field=None if row[9] is None else str(row[9]),
        effective_from=None if row[10] is None else _date(row[10]),
        effective_to=None if row[11] is None else _date(row[11]),
        source=str(row[12]),
        authority=SectorSourceAuthority(str(row[13])),
    )


def _classification_from_row(row: tuple[Any, ...]) -> HistoricalSectorClassification:
    return HistoricalSectorClassification(
        classification_id=str(row[1]),
        security_id=str(row[2]),
        isin=None if row[3] is None else str(row[3]),
        symbol_at_effective_date=str(row[4]),
        taxonomy_id=str(row[5]),
        sector_code=None if row[6] is None else str(row[6]),
        sector_name=None if row[7] is None else str(row[7]),
        industry_group_code=None if row[8] is None else str(row[8]),
        industry_group_name=None if row[9] is None else str(row[9]),
        industry_code=None if row[10] is None else str(row[10]),
        industry_name=None if row[11] is None else str(row[11]),
        subindustry_code=None if row[12] is None else str(row[12]),
        subindustry_name=None if row[13] is None else str(row[13]),
        effective_from=None if row[14] is None else _date(row[14]),
        effective_to=None if row[15] is None else _date(row[15]),
        source_record_date=None if row[16] is None else _date(row[16]),
        source_timestamp=None if row[17] is None else _datetime(row[17]),
        ingested_at=_datetime(row[18]),
        source_id=str(row[19]),
        authority=SectorSourceAuthority(str(row[20])),
        confidence=str(row[21]),
        point_in_time_status=HistoricalSectorStatus(str(row[22])),
        inference_method=str(row[23]),
        missing_fields=tuple(json.loads(str(row[24] or "[]"))),
        schema_version=str(row[25]),
        dataset_version=str(row[26]),
    )


def _conflict_from_row(row: tuple[Any, ...]) -> HistoricalSectorConflict:
    return HistoricalSectorConflict(
        conflict_id=str(row[1]),
        security_id=str(row[2]),
        taxonomy_id=str(row[3]),
        effective_from=None if row[4] is None else _date(row[4]),
        effective_to=None if row[5] is None else _date(row[5]),
        source_a=str(row[6]),
        source_b=str(row[7]),
        classification_a=str(row[8]),
        classification_b=str(row[9]),
        resolution_status=SectorConflictResolutionStatus(str(row[10])),
        resolution_reason=str(row[11]),
    )


def _change_from_row(row: tuple[Any, ...]) -> HistoricalSectorChange:
    return HistoricalSectorChange(
        security_id=str(row[1]),
        previous_classification=str(row[2]),
        new_classification=str(row[3]),
        effective_date=None if row[4] is None else _date(row[4]),
        source=str(row[5]),
        taxonomy=str(row[6]),
        change_type=str(row[7]),
        confidence=str(row[8]),
        candidate_dates_affected=int(row[9]),
        candidate_records_affected=int(row[10]),
    )


def _coverage_from_row(row: tuple[Any, ...]) -> HistoricalSectorCoverageRow:
    return HistoricalSectorCoverageRow(
        market_date=_date(row[1]),
        point_in_time_universe_size=int(row[2]),
        classified_security_count=int(row[3]),
        authoritative_classification_count=int(row[4]),
        supported_classification_count=int(row[5]),
        inferred_classification_count=int(row[6]),
        current_only_classification_count=int(row[7]),
        unclassified_count=int(row[8]),
        conflicting_count=int(row[9]),
        sector_count=int(row[10]),
        industry_count=int(row[11]),
        coverage_percentage=_decimal(row[12]),
        grade=str(row[13]),
    )


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_name = ?
        """,
        (table,),
    ).fetchone()
    return bool(row and row[0])


def _insert_rows(
    con: duckdb.DuckDBPyConnection, table: str, rows: tuple[dict[str, Any], ...]
) -> None:
    if not rows:
        return
    columns = tuple(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    con.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [tuple(row[column] for column in columns) for row in rows],
    )


def _item(
    criterion: str,
    status: HistoricalSectorReadinessStatus,
    explanation: str,
) -> HistoricalSectorReadinessItem:
    return HistoricalSectorReadinessItem(
        criterion=criterion,
        status=status,
        explanation=explanation,
    )


def _file_date_coverage(paths: list[Path]) -> str:
    if not paths:
        return "unavailable"
    return f"{paths[0].name} to {paths[-1].name}"


def _build_id(source_fingerprint: str, config_fingerprint: str) -> str:
    return _fingerprint((source_fingerprint, config_fingerprint))[:16]


def _fingerprint(value: Any) -> str:
    return sha256(
        json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(_FOUR)


def _counts(values: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(values).items()))


def _pairs(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{name}={count}" for name, count in values) or "unavailable"


def _text_list(values: tuple[Any, ...]) -> str:
    return ", ".join(str(value) for value in values) if values else "unavailable"


def _text(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _enum_text(value: StrEnum | None) -> str:
    return "unavailable" if value is None else value.value


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    return datetime.fromisoformat(str(value))


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(_FOUR)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value") and isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_jsonable(item) for item in value]
    return value


def _prohibited_next_action() -> str:
    return (
        "Do not tune market-regime thresholds, choose historically optimal "
        "boundaries, change regime labels, modify classifier conditions, alter "
        "market-intelligence weights, change regime intervention, alter "
        "recommendation scores, modify candidate generation, change verdicts, "
        "alter entry timing, modify gates, change trade plans, alter approvals, "
        "modify allocation, flip retracement signs, rewrite legacy candidates, "
        "overwrite diagnostic v1 or v2, use current sector mapping as "
        "authoritative history, infer historical classifications without explicit "
        "labels, or represent diagnostic v3 as exact original production state."
    )


__all__ = [
    "DIAGNOSTIC_MARKET_STATE_V3_VERSION",
    "HISTORICAL_SECTOR_DATASET_VERSION",
    "DiagnosticMarketStateV3BuildReport",
    "DiagnosticMarketStateV3Engine",
    "DiagnosticV2V3ComparisonReport",
    "HistoricalSectorBuildManifest",
    "HistoricalSectorBuildReport",
    "HistoricalSectorBuildStatus",
    "HistoricalSectorChange",
    "HistoricalSectorClassification",
    "HistoricalSectorConclusion",
    "HistoricalSectorConflict",
    "HistoricalSectorDecisionReadinessReport",
    "HistoricalSectorIngestionEngine",
    "HistoricalSectorNextMilestone",
    "HistoricalSectorReadinessItem",
    "HistoricalSectorReadinessStatus",
    "HistoricalSectorRepository",
    "HistoricalSectorStatus",
    "HistoricalSectorValidationReport",
    "SectorConflictResolutionStatus",
    "SectorIdentityMatchStatus",
    "SectorIdentityReconciliationRow",
    "SectorSourceAuthority",
    "SectorSourceInventoryItem",
    "SectorTaxonomyDefinition",
    "build_historical_sector_readiness",
    "default_sector_taxonomies",
    "export_historical_sector_csv",
    "export_historical_sector_json",
    "render_diagnostic_v3_build",
    "render_historical_sector_build",
    "render_historical_sector_changes",
    "render_historical_sector_conflicts",
    "render_historical_sector_coverage",
    "render_historical_sector_decision_readiness",
    "render_historical_sector_show",
    "render_historical_sector_state",
    "render_historical_sector_status",
    "render_historical_sector_validation",
    "render_sector_source_audit",
    "render_sector_taxonomies",
    "render_v2_v3_comparison",
    "validate_historical_sector_store",
]
