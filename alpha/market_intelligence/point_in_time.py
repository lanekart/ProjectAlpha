from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import Any, cast

import pandas as pd

POINT_IN_TIME_UNIVERSE_DATASET_VERSION = "point-in-time-market-universe-v1"
POINT_IN_TIME_SECTOR_DATASET_VERSION = "point-in-time-sector-classification-v1"
DIAGNOSTIC_MARKET_STATE_V2_VERSION = "diagnostic-market-state-reconstruction-v2"
DEFAULT_POINT_IN_TIME_UNIVERSE_PATH = Path(".alpha/point_in_time_market_universe.json")
_ZERO = Decimal("0")
_FOUR = Decimal("0.0001")
_TWO = Decimal("0.01")
_HUNDRED = Decimal("100")


class HistoricalSourceUsefulness(StrEnum):
    AUTHORITATIVE_POINT_IN_TIME = "AUTHORITATIVE_POINT_IN_TIME"
    STRONG_POINT_IN_TIME = "STRONG_POINT_IN_TIME"
    RECONSTRUCTABLE_WITH_LIMITATIONS = "RECONSTRUCTABLE_WITH_LIMITATIONS"
    CURRENT_STATE_ONLY = "CURRENT_STATE_ONLY"
    WEAK_INFERENCE_ONLY = "WEAK_INFERENCE_ONLY"
    UNUSABLE = "UNUSABLE"


class PointInTimeStatus(StrEnum):
    POINT_IN_TIME_AUTHORITATIVE = "POINT_IN_TIME_AUTHORITATIVE"
    POINT_IN_TIME_SUPPORTED = "POINT_IN_TIME_SUPPORTED"
    CURRENT_MAPPING_DIAGNOSTIC = "CURRENT_MAPPING_DIAGNOSTIC"
    WEAK_INFERRED = "WEAK_INFERRED"
    UNCLASSIFIED = "UNCLASSIFIED"
    CONFLICTING_CLASSIFICATION = "CONFLICTING_CLASSIFICATION"
    UNKNOWN = "UNKNOWN"


class HistoricalMembershipStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_NOT_YET_LISTED = "INELIGIBLE_NOT_YET_LISTED"
    INELIGIBLE_DELISTED = "INELIGIBLE_DELISTED"
    INELIGIBLE_SUSPENDED = "INELIGIBLE_SUSPENDED"
    INELIGIBLE_INSTRUMENT_TYPE = "INELIGIBLE_INSTRUMENT_TYPE"
    INELIGIBLE_PRICE_HISTORY = "INELIGIBLE_PRICE_HISTORY"
    INELIGIBLE_LIQUIDITY = "INELIGIBLE_LIQUIDITY"
    INELIGIBLE_DATA_QUALITY = "INELIGIBLE_DATA_QUALITY"
    MEMBERSHIP_UNKNOWN = "MEMBERSHIP_UNKNOWN"


class HistoricalDateEvidence(StrEnum):
    OFFICIAL_DATE = "OFFICIAL_DATE"
    AUTHORITATIVE_SOURCE_DATE = "AUTHORITATIVE_SOURCE_DATE"
    STRONG_INFERRED_DATE = "STRONG_INFERRED_DATE"
    WEAK_INFERRED_DATE = "WEAK_INFERRED_DATE"
    UNKNOWN_DATE = "UNKNOWN_DATE"


class UniverseQualityGrade(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNUSABLE = "UNUSABLE"


class BreadthCoverageStatus(StrEnum):
    COMPLETE = "COMPLETE"
    HIGH_COVERAGE = "HIGH_COVERAGE"
    PARTIAL = "PARTIAL"
    LOW_COVERAGE = "LOW_COVERAGE"
    UNUSABLE = "UNUSABLE"


class SectorHistoryReadiness(StrEnum):
    POINT_IN_TIME_SECTOR_HISTORY_READY = "POINT_IN_TIME_SECTOR_HISTORY_READY"
    POINT_IN_TIME_SECTOR_HISTORY_PARTIAL = "POINT_IN_TIME_SECTOR_HISTORY_PARTIAL"
    CURRENT_MAPPING_ONLY = "CURRENT_MAPPING_ONLY"
    SECTOR_HISTORY_UNUSABLE = "SECTOR_HISTORY_UNUSABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class PointInTimeConclusion(StrEnum):
    POINT_IN_TIME_MARKET_UNIVERSE_IS_READY = "POINT_IN_TIME_MARKET_UNIVERSE_IS_READY"
    POINT_IN_TIME_MARKET_UNIVERSE_IS_PARTIAL = (
        "POINT_IN_TIME_MARKET_UNIVERSE_IS_PARTIAL"
    )
    HISTORICAL_SECURITY_IDENTITY_IS_PRIMARY_BOTTLENECK = (
        "HISTORICAL_SECURITY_IDENTITY_IS_PRIMARY_BOTTLENECK"
    )
    LISTING_AND_DELISTING_HISTORY_IS_PRIMARY_BOTTLENECK = (
        "LISTING_AND_DELISTING_HISTORY_IS_PRIMARY_BOTTLENECK"
    )
    POINT_IN_TIME_SECTOR_HISTORY_IS_READY = "POINT_IN_TIME_SECTOR_HISTORY_IS_READY"
    POINT_IN_TIME_SECTOR_HISTORY_IS_PARTIAL = "POINT_IN_TIME_SECTOR_HISTORY_IS_PARTIAL"
    SECTOR_CLASSIFICATION_HISTORY_IS_PRIMARY_BOTTLENECK = (
        "SECTOR_CLASSIFICATION_HISTORY_IS_PRIMARY_BOTTLENECK"
    )
    CURRENT_UNIVERSE_BIAS_IS_PRIMARY_BOTTLENECK = (
        "CURRENT_UNIVERSE_BIAS_IS_PRIMARY_BOTTLENECK"
    )
    POINT_IN_TIME_BREADTH_IMPROVES_REGIME_VALIDATION = (
        "POINT_IN_TIME_BREADTH_IMPROVES_REGIME_VALIDATION"
    )
    SECTOR_STATE_IMPROVES_REGIME_VALIDATION = "SECTOR_STATE_IMPROVES_REGIME_VALIDATION"
    POINT_IN_TIME_DATA_DOES_NOT_RESOLVE_THRESHOLD_READINESS = (
        "POINT_IN_TIME_DATA_DOES_NOT_RESOLVE_THRESHOLD_READINESS"
    )
    MULTIPLE_POINT_IN_TIME_DATA_GAPS_REMAIN = "MULTIPLE_POINT_IN_TIME_DATA_GAPS_REMAIN"
    INSUFFICIENT_EVIDENCE_FOR_POINT_IN_TIME_HISTORY = (
        "INSUFFICIENT_EVIDENCE_FOR_POINT_IN_TIME_HISTORY"
    )


class PointInTimeNextMilestone(StrEnum):
    AUDIT_MARKET_REGIME_THRESHOLD_DEFINITIONS = (
        "AUDIT_MARKET_REGIME_THRESHOLD_DEFINITIONS"
    )
    AUDIT_REGIME_INTERVENTION_POLICY = "AUDIT_REGIME_INTERVENTION_POLICY"
    BUILD_OFFICIAL_SECURITY_MASTER_INGESTION = (
        "BUILD_OFFICIAL_SECURITY_MASTER_INGESTION"
    )
    BUILD_HISTORICAL_SECTOR_CLASSIFICATION_INGESTION = (
        "BUILD_HISTORICAL_SECTOR_CLASSIFICATION_INGESTION"
    )
    REPAIR_SECURITY_IDENTITY_LINEAGE = "REPAIR_SECURITY_IDENTITY_LINEAGE"
    EXPAND_LISTING_DELISTING_HISTORY = "EXPAND_LISTING_DELISTING_HISTORY"
    COLLECT_MORE_POINT_IN_TIME_MARKET_HISTORY = (
        "COLLECT_MORE_POINT_IN_TIME_MARKET_HISTORY"
    )
    AUDIT_CANDIDATE_GENERATION_BY_MARKET_STATE = (
        "AUDIT_CANDIDATE_GENERATION_BY_MARKET_STATE"
    )
    ACCEPT_RECONSTRUCTED_REGIMES_AS_DIAGNOSTIC_ONLY = (
        "ACCEPT_RECONSTRUCTED_REGIMES_AS_DIAGNOSTIC_ONLY"
    )


@dataclass(frozen=True, slots=True)
class PointInTimeSecurityRecord:
    security_id: str
    symbol: str
    exchange: str
    instrument_type: str
    isin: str | None
    company_name: str | None
    effective_from: date | None
    effective_to: date | None
    listing_date: date | None
    delisting_date: date | None
    listing_date_evidence: HistoricalDateEvidence
    delisting_date_evidence: HistoricalDateEvidence
    status: str
    previous_symbol: str | None
    successor_symbol: str | None
    corporate_action_lineage: tuple[str, ...]
    sector_code: str | None
    sector_name: str | None
    industry_code: str | None
    industry_name: str | None
    classification_source: str | None
    classification_effective_from: date | None
    classification_effective_to: date | None
    source: str
    source_timestamp: datetime | None
    ingested_at: datetime
    source_authority: str
    point_in_time_status: PointInTimeStatus
    missing_fields: tuple[str, ...]
    schema_version: str


@dataclass(frozen=True, slots=True)
class PointInTimeSectorClassification:
    security_id: str
    effective_from: date | None
    effective_to: date | None
    sector_code: str | None
    sector_name: str | None
    industry_code: str | None
    industry_name: str | None
    classification_system: str
    classification_version: str
    source: str
    source_timestamp: datetime | None
    authority: str
    point_in_time_status: PointInTimeStatus
    confidence: UniverseQualityGrade


@dataclass(frozen=True, slots=True)
class SecurityLineageMapping:
    predecessor_security_id: str
    successor_security_id: str
    effective_date: date | None
    relationship_type: str
    source: str
    confidence: UniverseQualityGrade


@dataclass(frozen=True, slots=True)
class HistoricalSourceInventoryItem:
    source: str
    fields_available: tuple[str, ...]
    date_coverage: str
    record_count: int
    identity_quality: UniverseQualityGrade
    listing_date_evidence: HistoricalDateEvidence
    delisting_date_evidence: HistoricalDateEvidence
    sector_history_evidence: PointInTimeStatus
    industry_history_evidence: PointInTimeStatus
    point_in_time_safety: bool
    authority: str
    limitations: tuple[str, ...]
    usefulness: HistoricalSourceUsefulness


@dataclass(frozen=True, slots=True)
class SecurityIdentityAuditReport:
    securities: int
    symbols: int
    securities_with_isin: int
    symbol_changes: int
    reused_symbol_conflicts: int
    merger_lineage_records: int
    demerger_lineage_records: int
    unresolved_identity_conflicts: tuple[str, ...]
    primary_identity_rule: str


@dataclass(frozen=True, slots=True)
class ListingDelistingAuditReport:
    securities: int
    official_listing_dates: int
    inferred_listing_dates: int
    unknown_listing_dates: int
    official_delisting_dates: int
    inferred_delisting_dates: int
    unknown_delisting_dates: int
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PointInTimeUniverseRow:
    market_date: date
    security_id: str
    symbol: str
    membership_status: HistoricalMembershipStatus
    membership_reason: str
    listing_status: str
    price_available: bool
    bars_available: int
    liquidity_available: bool
    sector_available: bool
    industry_available: bool
    source_lineage: tuple[str, ...]
    source_quality: UniverseQualityGrade
    survivorship_risk: str
    point_in_time_confidence: UniverseQualityGrade
    dataset_version: str


@dataclass(frozen=True, slots=True)
class PointInTimeUniverseDataset:
    dataset_version: str
    rows: tuple[PointInTimeUniverseRow, ...]
    security_records: tuple[PointInTimeSecurityRecord, ...]
    sector_classifications: tuple[PointInTimeSectorClassification, ...]
    lineage: tuple[SecurityLineageMapping, ...]
    dry_run: bool
    created_at: datetime
    non_authoritative_warning: str


@dataclass(frozen=True, slots=True)
class PointInTimePersistenceResult:
    inserted_rows: int
    inserted_securities: int
    inserted_classifications: int
    path: Path
    dry_run: bool
    dataset_version: str


@dataclass(frozen=True, slots=True)
class PointInTimeUniverseCoverageReport:
    dataset_version: str
    dataset_fingerprint: str
    market_dates: int
    security_rows: int
    eligible_rows: int
    membership_known_rows: int
    price_covered_rows: int
    dma_eligible_rows: int
    sector_classified_rows: int
    high_quality_dates: int
    partial_dates: int
    unusable_dates: int
    membership_quality: UniverseQualityGrade
    identity_quality: UniverseQualityGrade
    price_coverage_quality: UniverseQualityGrade
    breadth_quality: UniverseQualityGrade
    sector_classification_quality: UniverseQualityGrade
    sector_state_quality: UniverseQualityGrade
    timestamp_quality: UniverseQualityGrade
    overall_point_in_time_quality: UniverseQualityGrade
    primary_conclusion: PointInTimeConclusion
    secondary_conclusion: PointInTimeConclusion | None
    recommended_next_milestone: PointInTimeNextMilestone
    explicitly_prohibited_next_action: str


@dataclass(frozen=True, slots=True)
class PointInTimeBreadthSnapshot:
    market_date: date
    listed_universe_size: int
    eligible_universe_size: int
    priced_universe_size: int
    advancers: int
    decliners: int
    unchanged: int
    breadth_ratio: Decimal | None
    advance_decline_spread: int
    percent_above_20dma: Decimal | None
    percent_above_50dma: Decimal | None
    percent_above_200dma: Decimal | None
    new_20_day_highs: int | None
    new_20_day_lows: int | None
    new_52_week_highs: int | None
    new_52_week_lows: int | None
    median_return_1d: Decimal | None
    median_return_5d: Decimal | None
    cross_sectional_dispersion: Decimal | None
    breadth_completeness: BreadthCoverageStatus


@dataclass(frozen=True, slots=True)
class HistoricalSectorState:
    market_date: date
    sector: str
    eligible_securities: int
    priced_securities: int
    return_1d: Decimal | None
    return_5d: Decimal | None
    return_20d: Decimal | None
    breadth_ratio: Decimal | None
    percent_above_20dma: Decimal | None
    percent_above_50dma: Decimal | None
    percent_above_200dma: Decimal | None
    sector_volatility: Decimal | None
    sector_dispersion: Decimal | None
    relative_return_versus_benchmark: Decimal | None
    leadership_rank: int | None
    participation: Decimal | None
    data_completeness: BreadthCoverageStatus
    label: str


@dataclass(frozen=True, slots=True)
class HistoricalSectorStateReport:
    market_date: date
    sector_states: tuple[HistoricalSectorState, ...]
    leading_sector: str | None
    lagging_sector: str | None
    sector_leadership_concentration: Decimal | None
    sector_dispersion: Decimal | None
    positive_sector_share: Decimal | None
    negative_sector_share: Decimal | None
    broad_sector_participation: bool
    data_completeness: BreadthCoverageStatus


@dataclass(frozen=True, slots=True)
class SectorClassificationConflict:
    security_id: str
    date_range: str
    source_a_classification: str
    source_b_classification: str
    conflict_type: str
    candidate_records_affected: int
    market_dates_affected: int
    resolution_status: str


@dataclass(frozen=True, slots=True)
class SectorCoverageAuditReport:
    candidate_dates: int
    dates_with_point_in_time_sector_coverage: int
    dates_with_supported_sector_coverage: int
    dates_with_current_mapping_only_coverage: int
    dates_unclassified: int
    candidate_records_covered: int
    sectors_represented: tuple[str, ...]
    median_sector_universe_size: Decimal | None
    minimum_sector_universe_size: int | None
    classification_conflicts: int
    readiness: SectorHistoryReadiness


@dataclass(frozen=True, slots=True)
class SurvivorshipBiasRow:
    market_date: date
    current_universe_count: int
    point_in_time_universe_count: int
    symbols_added_by_current_universe_bias: tuple[str, ...]
    symbols_omitted_by_current_universe_bias: tuple[str, ...]
    breadth_ratio_difference: Decimal | None
    dma_breadth_difference: Decimal | None
    new_high_new_low_difference: Decimal | None
    regime_input_difference: str
    regime_classification_difference: bool


@dataclass(frozen=True, slots=True)
class SurvivorshipBiasAuditReport:
    rows: tuple[SurvivorshipBiasRow, ...]
    dates_materially_affected: int
    candidate_records_affected: int
    recorded_reconstructed_regime_changes: int
    outcome_conclusions_affected: str
    finding: str


@dataclass(frozen=True, slots=True)
class DiagnosticMarketStateV2BuildReport:
    dataset_version: str
    dry_run: bool
    universe_dataset_version: str
    universe_dataset_fingerprint: str
    sector_dataset_version: str
    sector_dataset_fingerprint: str
    breadth_builder_version: str
    sector_state_builder_version: str
    benchmark_builder_version: str
    classifier_version: str
    classifier_fingerprint: str
    feature_definition_version: str
    source_lineage_fingerprint: str
    reconstructions_would_create: int
    candidate_links_would_create: int
    persistence_status: str
    blocked_reason: str | None


@dataclass(frozen=True, slots=True)
class DiagnosticV1V2ComparisonReport:
    v1_dataset_version: str
    v2_dataset_version: str
    v1_regime_distribution: tuple[tuple[str, int], ...]
    v2_regime_distribution: tuple[tuple[str, int], ...]
    regime_agreement: Decimal | None
    neutral_share_v1: Decimal | None
    neutral_share_v2: Decimal | None
    bullish_share_v1: Decimal | None
    bullish_share_v2: Decimal | None
    bearish_share_v1: Decimal | None
    bearish_share_v2: Decimal | None
    dates_changing_regime: int
    candidates_changing_linked_diagnostic_regime: int
    completeness_distribution: tuple[tuple[str, int], ...]
    quality_distribution: tuple[tuple[str, int], ...]
    conclusion: str


@dataclass(frozen=True, slots=True)
class V2OutcomeComparisonReport:
    v1_outcome_ordering: tuple[str, ...]
    v2_outcome_ordering: tuple[str, ...]
    v1_threshold_sensitivity: str
    v2_threshold_sensitivity: str
    comparison: str
    explanation: str


@dataclass(frozen=True, slots=True)
class SectorIncrementalValueReport:
    comparisons: tuple[tuple[str, Decimal | None], ...]
    conclusion: str
    explanation: str


class PointInTimeUniverseRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_point_in_time_universe_path(path)

    def save_dataset(
        self,
        dataset: PointInTimeUniverseDataset,
        *,
        replace_dataset_version: bool = False,
    ) -> PointInTimePersistenceResult:
        if dataset.dry_run:
            return PointInTimePersistenceResult(
                inserted_rows=len(dataset.rows),
                inserted_securities=len(dataset.security_records),
                inserted_classifications=len(dataset.sector_classifications),
                path=self.path,
                dry_run=True,
                dataset_version=dataset.dataset_version,
            )
        existing = self.load_dataset()
        rows = list(existing.rows)
        securities = list(existing.security_records)
        classifications = list(existing.sector_classifications)
        lineage = list(existing.lineage)
        if replace_dataset_version:
            rows = [
                row for row in rows if row.dataset_version != dataset.dataset_version
            ]
        existing_row_keys = {
            (row.dataset_version, row.market_date, row.security_id) for row in rows
        }
        inserted_rows = 0
        for row in dataset.rows:
            key = (row.dataset_version, row.market_date, row.security_id)
            if key in existing_row_keys:
                continue
            inserted_rows += 1
            existing_row_keys.add(key)
            rows.append(row)
        security_keys = {row.security_id for row in securities}
        inserted_securities = 0
        for security in dataset.security_records:
            if security.security_id in security_keys:
                continue
            inserted_securities += 1
            security_keys.add(security.security_id)
            securities.append(security)
        classification_keys: set[tuple[str, date | None, str | None]] = {
            (row.security_id, row.effective_from, row.sector_name)
            for row in classifications
        }
        inserted_classifications = 0
        for classification in dataset.sector_classifications:
            classification_key = (
                classification.security_id,
                classification.effective_from,
                classification.sector_name,
            )
            if classification_key in classification_keys:
                continue
            inserted_classifications += 1
            classification_keys.add(classification_key)
            classifications.append(classification)
        lineage.extend(item for item in dataset.lineage if item not in set(lineage))
        self._write(
            PointInTimeUniverseDataset(
                dataset_version=dataset.dataset_version,
                rows=tuple(rows),
                security_records=tuple(securities),
                sector_classifications=tuple(classifications),
                lineage=tuple(lineage),
                dry_run=False,
                created_at=dataset.created_at,
                non_authoritative_warning=dataset.non_authoritative_warning,
            )
        )
        return PointInTimePersistenceResult(
            inserted_rows=inserted_rows,
            inserted_securities=inserted_securities,
            inserted_classifications=inserted_classifications,
            path=self.path,
            dry_run=False,
            dataset_version=dataset.dataset_version,
        )

    def load_dataset(self) -> PointInTimeUniverseDataset:
        payload = self._read()
        return PointInTimeUniverseDataset(
            dataset_version=str(
                payload.get("dataset_version", POINT_IN_TIME_UNIVERSE_DATASET_VERSION)
            ),
            rows=tuple(
                PointInTimeUniverseRow(**_parse_dates(row))
                for row in payload.get("rows", [])
                if isinstance(row, dict)
            ),
            security_records=tuple(
                _security_from_dict(row)
                for row in payload.get("security_records", [])
                if isinstance(row, dict)
            ),
            sector_classifications=tuple(
                _classification_from_dict(row)
                for row in payload.get("sector_classifications", [])
                if isinstance(row, dict)
            ),
            lineage=tuple(
                _lineage_from_dict(row)
                for row in payload.get("lineage", [])
                if isinstance(row, dict)
            ),
            dry_run=False,
            created_at=_payload_datetime(payload.get("created_at"))
            or datetime(1970, 1, 1, tzinfo=UTC),
            non_authoritative_warning=str(
                payload.get("non_authoritative_warning", _warning())
            ),
        )

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_payload()
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return _empty_payload()
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else _empty_payload()

    def _write(self, dataset: PointInTimeUniverseDataset) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(_jsonable(dataset), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class PointInTimeUniverseBuilder:
    def __init__(
        self,
        *,
        dataset_version: str = POINT_IN_TIME_UNIVERSE_DATASET_VERSION,
        created_at: datetime | None = None,
    ) -> None:
        self.dataset_version = dataset_version
        self.created_at = created_at or datetime(1970, 1, 1, tzinfo=UTC)

    def build(
        self,
        *,
        records: tuple[Any, ...],
        price_repository: Any,
        dry_run: bool = True,
    ) -> PointInTimeUniverseDataset:
        candidate_dates = tuple(sorted({record.evaluation_date for record in records}))
        price_frames = _price_frames_by_date(price_repository, candidate_dates)
        securities = _security_records(price_frames, self.created_at)
        security_by_symbol = {security.symbol: security for security in securities}
        bars_by_symbol_date = _history_counts(
            price_repository,
            tuple(security.symbol for security in securities),
            candidate_dates,
        )
        rows: list[PointInTimeUniverseRow] = []
        for market_date in candidate_dates:
            frame = price_frames.get(market_date, _empty_price_frame())
            symbols_on_date = set(_series(frame, "symbol"))
            for symbol in sorted(symbols_on_date):
                security = security_by_symbol.get(symbol)
                if security is None:
                    continue
                status = _membership_status(security, market_date, symbols_on_date)
                bars = bars_by_symbol_date.get((security.symbol, market_date), 0)
                rows.append(
                    PointInTimeUniverseRow(
                        market_date=market_date,
                        security_id=security.security_id,
                        symbol=security.symbol,
                        membership_status=status,
                        membership_reason=_membership_reason(status),
                        listing_status=security.status,
                        price_available=security.symbol in symbols_on_date,
                        bars_available=bars,
                        liquidity_available=_liquidity_available(
                            frame, security.symbol
                        ),
                        sector_available=bool(security.sector_name),
                        industry_available=bool(security.industry_name),
                        source_lineage=("daily_prices", "first_last_local_appearance"),
                        source_quality=UniverseQualityGrade.LOW,
                        survivorship_risk=(
                            "local-history-window; no official membership archive"
                        ),
                        point_in_time_confidence=UniverseQualityGrade.LOW,
                        dataset_version=self.dataset_version,
                    )
                )
        classifications = tuple(
            PointInTimeSectorClassification(
                security_id=row.security_id,
                effective_from=None,
                effective_to=None,
                sector_code=None,
                sector_name=row.sector_name,
                industry_code=None,
                industry_name=row.industry_name,
                classification_system="UNKNOWN",
                classification_version=POINT_IN_TIME_SECTOR_DATASET_VERSION,
                source=row.classification_source or "daily_prices.sector",
                source_timestamp=row.source_timestamp,
                authority="local diagnostic current mapping only",
                point_in_time_status=PointInTimeStatus.CURRENT_MAPPING_DIAGNOSTIC
                if row.sector_name
                else PointInTimeStatus.UNCLASSIFIED,
                confidence=UniverseQualityGrade.LOW
                if row.sector_name
                else UniverseQualityGrade.UNUSABLE,
            )
            for row in securities
        )
        return PointInTimeUniverseDataset(
            dataset_version=self.dataset_version,
            rows=tuple(sorted(rows, key=lambda item: (item.market_date, item.symbol))),
            security_records=securities,
            sector_classifications=classifications,
            lineage=(),
            dry_run=dry_run,
            created_at=self.created_at,
            non_authoritative_warning=_warning(),
        )


class PointInTimeMarketBreadthBuilder:
    version = "point-in-time-market-breadth-builder-v1"
    unchanged_tolerance = Decimal("0")

    def build(
        self,
        *,
        market_date: date,
        universe_rows: tuple[PointInTimeUniverseRow, ...],
        price_repository: Any,
    ) -> PointInTimeBreadthSnapshot:
        rows = tuple(
            row
            for row in universe_rows
            if row.market_date == market_date
            and row.membership_status is HistoricalMembershipStatus.ELIGIBLE
        )
        symbols = tuple(row.symbol for row in rows)
        frame = _price_frame(price_repository, market_date)
        frame = frame[frame["symbol"].astype(str).str.upper().isin(symbols)]
        advancers = decliners = unchanged = 0
        returns_1d: list[Decimal] = []
        closes: dict[str, Decimal] = {}
        for item in frame.to_dict("records"):
            close = _decimal(item.get("close"))
            previous = _decimal(item.get("open"))
            symbol = str(item.get("symbol", "")).upper()
            if close is None or previous is None:
                continue
            closes[symbol] = close
            move = close - previous
            returns_1d.append(_pct_return(close, previous) or _ZERO)
            if move > self.unchanged_tolerance:
                advancers += 1
            elif move < -self.unchanged_tolerance:
                decliners += 1
            else:
                unchanged += 1
        dma20 = dma50 = dma200 = highs20 = lows20 = highs52 = lows52 = 0
        eligible20 = eligible50 = eligible200 = highlow20 = highlow52 = 0
        returns_5d: list[Decimal] = []
        for symbol, close in closes.items():
            history = _history(price_repository, symbol, market_date, 260)
            close_values = [
                value
                for value in (_decimal(row.get("close")) for row in history)
                if value is not None
            ]
            if len(close_values) >= 5:
                returns_5d.append(
                    _pct_return(close_values[-1], close_values[-5]) or _ZERO
                )
            if len(close_values) >= 20:
                eligible20 += 1
                highlow20 += 1
                avg20 = sum(close_values[-20:], _ZERO) / Decimal("20")
                dma20 += int(close >= avg20)
                highs20 += int(close >= max(close_values[-20:]))
                lows20 += int(close <= min(close_values[-20:]))
            if len(close_values) >= 50:
                eligible50 += 1
                avg50 = sum(close_values[-50:], _ZERO) / Decimal("50")
                dma50 += int(close >= avg50)
            if len(close_values) >= 200:
                eligible200 += 1
                highlow52 += 1
                avg200 = sum(close_values[-200:], _ZERO) / Decimal("200")
                dma200 += int(close >= avg200)
                highs52 += int(close >= max(close_values[-252:]))
                lows52 += int(close <= min(close_values[-252:]))
        priced = len(closes)
        return PointInTimeBreadthSnapshot(
            market_date=market_date,
            listed_universe_size=len(rows),
            eligible_universe_size=len(rows),
            priced_universe_size=priced,
            advancers=advancers,
            decliners=decliners,
            unchanged=unchanged,
            breadth_ratio=_rate(advancers, advancers + decliners),
            advance_decline_spread=advancers - decliners,
            percent_above_20dma=_rate(dma20, eligible20),
            percent_above_50dma=_rate(dma50, eligible50),
            percent_above_200dma=_rate(dma200, eligible200),
            new_20_day_highs=highs20 if highlow20 else None,
            new_20_day_lows=lows20 if highlow20 else None,
            new_52_week_highs=highs52 if highlow52 else None,
            new_52_week_lows=lows52 if highlow52 else None,
            median_return_1d=_median(returns_1d),
            median_return_5d=_median(returns_5d),
            cross_sectional_dispersion=_dispersion(returns_1d),
            breadth_completeness=_breadth_status(priced, len(rows), eligible200),
        )


class HistoricalSectorStateBuilder:
    version = "historical-sector-state-builder-v1"

    def build(
        self,
        *,
        market_date: date,
        universe_rows: tuple[PointInTimeUniverseRow, ...],
        price_repository: Any,
    ) -> HistoricalSectorStateReport:
        eligible = tuple(
            row
            for row in universe_rows
            if row.market_date == market_date
            and row.membership_status is HistoricalMembershipStatus.ELIGIBLE
            and row.sector_available
        )
        if not eligible:
            return HistoricalSectorStateReport(
                market_date=market_date,
                sector_states=(),
                leading_sector=None,
                lagging_sector=None,
                sector_leadership_concentration=None,
                sector_dispersion=None,
                positive_sector_share=None,
                negative_sector_share=None,
                broad_sector_participation=False,
                data_completeness=BreadthCoverageStatus.UNUSABLE,
            )
        frame = _price_frame(price_repository, market_date)
        sector_by_symbol = _sector_by_symbol(frame)
        grouped: dict[str, list[str]] = defaultdict(list)
        for row in eligible:
            sector = sector_by_symbol.get(row.symbol)
            if sector:
                grouped[sector].append(row.symbol)
        states: list[HistoricalSectorState] = []
        benchmark_return = _benchmark_return(frame)
        for sector, symbols in sorted(grouped.items()):
            returns = _returns_for_symbols(frame, tuple(symbols))
            avg_return = _mean(returns)
            breadth = _rate(sum(1 for value in returns if value > _ZERO), len(returns))
            states.append(
                HistoricalSectorState(
                    market_date=market_date,
                    sector=sector,
                    eligible_securities=len(symbols),
                    priced_securities=len(returns),
                    return_1d=avg_return,
                    return_5d=None,
                    return_20d=None,
                    breadth_ratio=breadth,
                    percent_above_20dma=None,
                    percent_above_50dma=None,
                    percent_above_200dma=None,
                    sector_volatility=None,
                    sector_dispersion=_dispersion(returns),
                    relative_return_versus_benchmark=None
                    if avg_return is None or benchmark_return is None
                    else _quantize(avg_return - benchmark_return),
                    leadership_rank=None,
                    participation=_rate(len(returns), len(symbols)),
                    data_completeness=_breadth_status(len(returns), len(symbols), 0),
                    label="stock-aggregated sector state; not sector index",
                )
            )
        ranked = sorted(
            states,
            key=lambda item: (
                item.return_1d if item.return_1d is not None else Decimal("-999")
            ),
            reverse=True,
        )
        ranked = [
            HistoricalSectorState(**{**asdict(item), "leadership_rank": index})
            for index, item in enumerate(ranked, start=1)
        ]
        positives = sum(1 for item in ranked if (item.return_1d or _ZERO) > _ZERO)
        negatives = sum(1 for item in ranked if (item.return_1d or _ZERO) < _ZERO)
        returns = tuple(item.return_1d for item in ranked if item.return_1d is not None)
        return HistoricalSectorStateReport(
            market_date=market_date,
            sector_states=tuple(ranked),
            leading_sector=ranked[0].sector if ranked else None,
            lagging_sector=ranked[-1].sector if ranked else None,
            sector_leadership_concentration=_rate(
                ranked[0].priced_securities if ranked else 0,
                sum(item.priced_securities for item in ranked),
            ),
            sector_dispersion=_dispersion(returns),
            positive_sector_share=_rate(positives, len(ranked)),
            negative_sector_share=_rate(negatives, len(ranked)),
            broad_sector_participation=positives >= max(1, len(ranked) // 2),
            data_completeness=BreadthCoverageStatus.PARTIAL,
        )


def build_historical_source_inventory(
    *,
    price_repository: Any,
    records: tuple[Any, ...],
) -> tuple[HistoricalSourceInventoryItem, ...]:
    dates = tuple(sorted({record.evaluation_date for record in records}))
    sample = _price_frame(price_repository, dates[0]) if dates else pd.DataFrame()
    total_rows = sum(len(_price_frame(price_repository, item)) for item in dates)
    sector_dates = sum(
        1
        for item in dates
        if not _price_frame(price_repository, item).empty
        and "sector" in _price_frame(price_repository, item)
        and _price_frame(price_repository, item)["sector"].dropna().size
    )
    return (
        HistoricalSourceInventoryItem(
            source="daily_prices",
            fields_available=tuple(str(column) for column in sample.columns),
            date_coverage=f"{dates[0]} to {dates[-1]}" if dates else "unavailable",
            record_count=total_rows,
            identity_quality=UniverseQualityGrade.LOW,
            listing_date_evidence=HistoricalDateEvidence.WEAK_INFERRED_DATE,
            delisting_date_evidence=HistoricalDateEvidence.WEAK_INFERRED_DATE,
            sector_history_evidence=PointInTimeStatus.CURRENT_MAPPING_DIAGNOSTIC
            if sector_dates
            else PointInTimeStatus.UNCLASSIFIED,
            industry_history_evidence=PointInTimeStatus.UNCLASSIFIED,
            point_in_time_safety=False,
            authority="local price observations",
            limitations=(
                "first local price is not official listing date",
                "last local price is not official delisting date",
                "sector field has no effective period",
            ),
            usefulness=HistoricalSourceUsefulness.RECONSTRUCTABLE_WITH_LIMITATIONS,
        ),
        HistoricalSourceInventoryItem(
            source="candidate_learning_ledger",
            fields_available=tuple(
                sorted(set().union(*(record.as_dict().keys() for record in records)))
            )
            if records and hasattr(records[0], "as_dict")
            else (),
            date_coverage=f"{dates[0]} to {dates[-1]}" if dates else "unavailable",
            record_count=len(records),
            identity_quality=UniverseQualityGrade.LOW,
            listing_date_evidence=HistoricalDateEvidence.UNKNOWN_DATE,
            delisting_date_evidence=HistoricalDateEvidence.UNKNOWN_DATE,
            sector_history_evidence=PointInTimeStatus.CURRENT_MAPPING_DIAGNOSTIC,
            industry_history_evidence=PointInTimeStatus.UNCLASSIFIED,
            point_in_time_safety=False,
            authority="Alpha generated candidates",
            limitations=("candidate universe is selected, not market universe",),
            usefulness=HistoricalSourceUsefulness.WEAK_INFERENCE_ONLY,
        ),
    )


def build_universe_coverage_report(
    dataset: PointInTimeUniverseDataset,
) -> PointInTimeUniverseCoverageReport:
    rows = dataset.rows
    by_date: dict[date, list[PointInTimeUniverseRow]] = defaultdict(list)
    for row in rows:
        by_date[row.market_date].append(row)
    date_grades = tuple(_date_quality(tuple(group)) for group in by_date.values())
    high = sum(1 for grade in date_grades if grade is UniverseQualityGrade.HIGH)
    partial = sum(
        1
        for grade in date_grades
        if grade in {UniverseQualityGrade.MEDIUM, UniverseQualityGrade.LOW}
    )
    unusable = sum(1 for grade in date_grades if grade is UniverseQualityGrade.UNUSABLE)
    eligible = tuple(
        row
        for row in rows
        if row.membership_status is HistoricalMembershipStatus.ELIGIBLE
    )
    sector_rows = tuple(row for row in rows if row.sector_available)
    primary = (
        PointInTimeConclusion.POINT_IN_TIME_MARKET_UNIVERSE_IS_PARTIAL
        if eligible
        else PointInTimeConclusion.INSUFFICIENT_EVIDENCE_FOR_POINT_IN_TIME_HISTORY
    )
    return PointInTimeUniverseCoverageReport(
        dataset_version=dataset.dataset_version,
        dataset_fingerprint=point_in_time_dataset_fingerprint(dataset),
        market_dates=len(by_date),
        security_rows=len(rows),
        eligible_rows=len(eligible),
        membership_known_rows=sum(
            1
            for row in rows
            if row.membership_status
            is not HistoricalMembershipStatus.MEMBERSHIP_UNKNOWN
        ),
        price_covered_rows=sum(1 for row in rows if row.price_available),
        dma_eligible_rows=sum(1 for row in rows if row.bars_available >= 200),
        sector_classified_rows=len(sector_rows),
        high_quality_dates=high,
        partial_dates=partial,
        unusable_dates=unusable,
        membership_quality=UniverseQualityGrade.LOW,
        identity_quality=UniverseQualityGrade.LOW,
        price_coverage_quality=UniverseQualityGrade.MEDIUM
        if eligible
        else UniverseQualityGrade.UNUSABLE,
        breadth_quality=UniverseQualityGrade.LOW,
        sector_classification_quality=UniverseQualityGrade.UNUSABLE,
        sector_state_quality=UniverseQualityGrade.UNUSABLE,
        timestamp_quality=UniverseQualityGrade.HIGH,
        overall_point_in_time_quality=UniverseQualityGrade.LOW
        if eligible
        else UniverseQualityGrade.UNUSABLE,
        primary_conclusion=primary,
        secondary_conclusion=PointInTimeConclusion.SECTOR_CLASSIFICATION_HISTORY_IS_PRIMARY_BOTTLENECK,
        recommended_next_milestone=PointInTimeNextMilestone.BUILD_HISTORICAL_SECTOR_CLASSIFICATION_INGESTION,
        explicitly_prohibited_next_action=_prohibited_next_action(),
    )


def build_security_identity_audit(
    dataset: PointInTimeUniverseDataset,
) -> SecurityIdentityAuditReport:
    symbols = [row.symbol for row in dataset.security_records]
    conflicts = tuple(symbol for symbol, count in Counter(symbols).items() if count > 1)
    return SecurityIdentityAuditReport(
        securities=len(dataset.security_records),
        symbols=len(set(symbols)),
        securities_with_isin=sum(1 for row in dataset.security_records if row.isin),
        symbol_changes=sum(
            1 for row in dataset.security_records if row.previous_symbol
        ),
        reused_symbol_conflicts=len(conflicts),
        merger_lineage_records=sum(
            1 for row in dataset.lineage if row.relationship_type == "MERGER"
        ),
        demerger_lineage_records=sum(
            1 for row in dataset.lineage if row.relationship_type == "DEMERGER"
        ),
        unresolved_identity_conflicts=conflicts,
        primary_identity_rule=(
            "ISIN > provider instrument key > stable internal security ID"
        ),
    )


def build_listing_delisting_audit(
    dataset: PointInTimeUniverseDataset,
) -> ListingDelistingAuditReport:
    rows = dataset.security_records
    return ListingDelistingAuditReport(
        securities=len(rows),
        official_listing_dates=sum(
            1
            for row in rows
            if row.listing_date_evidence is HistoricalDateEvidence.OFFICIAL_DATE
        ),
        inferred_listing_dates=sum(
            1
            for row in rows
            if row.listing_date_evidence is HistoricalDateEvidence.WEAK_INFERRED_DATE
        ),
        unknown_listing_dates=sum(
            1
            for row in rows
            if row.listing_date_evidence is HistoricalDateEvidence.UNKNOWN_DATE
        ),
        official_delisting_dates=sum(
            1
            for row in rows
            if row.delisting_date_evidence is HistoricalDateEvidence.OFFICIAL_DATE
        ),
        inferred_delisting_dates=sum(
            1
            for row in rows
            if row.delisting_date_evidence is HistoricalDateEvidence.WEAK_INFERRED_DATE
        ),
        unknown_delisting_dates=sum(
            1
            for row in rows
            if row.delisting_date_evidence is HistoricalDateEvidence.UNKNOWN_DATE
        ),
        limitations=(
            "first local price is weak listing evidence",
            "last local price is weak delisting evidence",
            "archive gaps are not proof of non-listing",
        ),
    )


def build_sector_coverage_audit(
    dataset: PointInTimeUniverseDataset,
) -> SectorCoverageAuditReport:
    rows = dataset.rows
    dates = {row.market_date for row in rows}
    current_mapping_dates = {row.market_date for row in rows if row.sector_available}
    sector_counts = Counter(
        row.symbol
        for row in rows
        if row.sector_available
        and row.membership_status is HistoricalMembershipStatus.ELIGIBLE
    )
    sectors = tuple(
        sorted(
            {
                classification.sector_name
                for classification in dataset.sector_classifications
                if classification.sector_name
            }
        )
    )
    return SectorCoverageAuditReport(
        candidate_dates=len(dates),
        dates_with_point_in_time_sector_coverage=0,
        dates_with_supported_sector_coverage=0,
        dates_with_current_mapping_only_coverage=len(current_mapping_dates),
        dates_unclassified=len(dates - current_mapping_dates),
        candidate_records_covered=sum(1 for row in rows if row.sector_available),
        sectors_represented=tuple(str(item) for item in sectors),
        median_sector_universe_size=_median_int(tuple(sector_counts.values())),
        minimum_sector_universe_size=min(sector_counts.values())
        if sector_counts
        else None,
        classification_conflicts=len(build_sector_conflicts(dataset)),
        readiness=SectorHistoryReadiness.CURRENT_MAPPING_ONLY
        if current_mapping_dates
        else SectorHistoryReadiness.SECTOR_HISTORY_UNUSABLE,
    )


def build_sector_conflicts(
    dataset: PointInTimeUniverseDataset,
) -> tuple[SectorClassificationConflict, ...]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for item in dataset.sector_classifications:
        if item.sector_name:
            grouped[item.security_id].add(item.sector_name)
    return tuple(
        SectorClassificationConflict(
            security_id=security_id,
            date_range="effective period unavailable",
            source_a_classification=",".join(sorted(sectors)),
            source_b_classification="unavailable",
            conflict_type="multiple current classifications without effective dates",
            candidate_records_affected=0,
            market_dates_affected=0,
            resolution_status="unresolved",
        )
        for security_id, sectors in sorted(grouped.items())
        if len(sectors) > 1
    )


def build_breadth_snapshots(
    *,
    dataset: PointInTimeUniverseDataset,
    price_repository: Any,
) -> tuple[PointInTimeBreadthSnapshot, ...]:
    builder = PointInTimeMarketBreadthBuilder()
    return tuple(
        builder.build(
            market_date=market_date,
            universe_rows=dataset.rows,
            price_repository=price_repository,
        )
        for market_date in sorted({row.market_date for row in dataset.rows})
    )


def build_sector_state_report(
    *,
    dataset: PointInTimeUniverseDataset,
    price_repository: Any,
    market_date: date,
) -> HistoricalSectorStateReport:
    return HistoricalSectorStateBuilder().build(
        market_date=market_date,
        universe_rows=dataset.rows,
        price_repository=price_repository,
    )


def build_survivorship_bias_audit(
    *,
    dataset: PointInTimeUniverseDataset,
    price_repository: Any,
) -> SurvivorshipBiasAuditReport:
    rows = []
    material = 0
    affected_records = 0
    for market_date in sorted({row.market_date for row in dataset.rows}):
        frame = _price_frame(price_repository, market_date)
        current_symbols = set(_series(frame, "symbol"))
        pit_symbols = {
            row.symbol
            for row in dataset.rows
            if row.market_date == market_date
            and row.membership_status is HistoricalMembershipStatus.ELIGIBLE
        }
        added = tuple(sorted(current_symbols - pit_symbols))
        omitted = tuple(sorted(pit_symbols - current_symbols))
        current_ratio = _same_day_breadth_ratio(frame)
        pit_snapshot = PointInTimeMarketBreadthBuilder().build(
            market_date=market_date,
            universe_rows=dataset.rows,
            price_repository=price_repository,
        )
        difference = None
        if current_ratio is not None and pit_snapshot.breadth_ratio is not None:
            difference = _quantize(current_ratio - pit_snapshot.breadth_ratio)
        is_material = bool(
            added
            or omitted
            or (difference is not None and abs(difference) > Decimal("0.10"))
        )
        material += int(is_material)
        affected_records += (
            sum(1 for row in dataset.rows if row.market_date == market_date)
            if is_material
            else 0
        )
        rows.append(
            SurvivorshipBiasRow(
                market_date=market_date,
                current_universe_count=len(current_symbols),
                point_in_time_universe_count=len(pit_symbols),
                symbols_added_by_current_universe_bias=added,
                symbols_omitted_by_current_universe_bias=omitted,
                breadth_ratio_difference=difference,
                dma_breadth_difference=None,
                new_high_new_low_difference=None,
                regime_input_difference="breadth_ratio" if difference else "none",
                regime_classification_difference=False,
            )
        )
    finding = (
        "CURRENT_UNIVERSE_BIAS_IS_MATERIAL"
        if material
        else "CURRENT_UNIVERSE_BIAS_IS_LIMITED"
    )
    return SurvivorshipBiasAuditReport(
        rows=tuple(rows),
        dates_materially_affected=material,
        candidate_records_affected=affected_records,
        recorded_reconstructed_regime_changes=0,
        outcome_conclusions_affected="not evaluated in this source-coverage milestone",
        finding=finding,
    )


def build_diagnostic_v2_report(
    *,
    dataset: PointInTimeUniverseDataset,
    classifier_version: str,
    classifier_fingerprint: str,
    dry_run: bool,
) -> DiagnosticMarketStateV2BuildReport:
    universe_fingerprint = point_in_time_dataset_fingerprint(dataset)
    sector_fingerprint = sha256(
        json.dumps(
            _jsonable(dataset.sector_classifications),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    dates = {row.market_date for row in dataset.rows}
    eligible = bool(dataset.rows) and any(
        row.membership_status is HistoricalMembershipStatus.ELIGIBLE
        for row in dataset.rows
    )
    blocked = None if eligible else "point-in-time universe has no eligible rows"
    if not dry_run and blocked is None:
        blocked = "persistence requires full point-in-time integrity validation"
    source_payload = {
        "universe": universe_fingerprint,
        "sector": sector_fingerprint,
        "breadth_builder": PointInTimeMarketBreadthBuilder.version,
        "sector_state_builder": HistoricalSectorStateBuilder.version,
        "classifier": classifier_fingerprint,
    }
    return DiagnosticMarketStateV2BuildReport(
        dataset_version=DIAGNOSTIC_MARKET_STATE_V2_VERSION,
        dry_run=dry_run,
        universe_dataset_version=dataset.dataset_version,
        universe_dataset_fingerprint=universe_fingerprint,
        sector_dataset_version=POINT_IN_TIME_SECTOR_DATASET_VERSION,
        sector_dataset_fingerprint=sector_fingerprint,
        breadth_builder_version=PointInTimeMarketBreadthBuilder.version,
        sector_state_builder_version=HistoricalSectorStateBuilder.version,
        benchmark_builder_version="BenchmarkStateBuilder",
        classifier_version=classifier_version,
        classifier_fingerprint=classifier_fingerprint,
        feature_definition_version="market-feature-definitions-v2",
        source_lineage_fingerprint=_stable_id(source_payload),
        reconstructions_would_create=len(dates) if eligible else 0,
        candidate_links_would_create=len(dataset.rows) if eligible else 0,
        persistence_status="DRY_RUN"
        if dry_run
        else "PERSISTENCE_BLOCKED_PENDING_FULL_INTEGRITY",
        blocked_reason=blocked,
    )


def build_v1_v2_comparison(
    *,
    v1_regimes: tuple[str, ...],
    v2_regimes: tuple[str, ...],
) -> DiagnosticV1V2ComparisonReport:
    total = max(len(v1_regimes), len(v2_regimes))
    agree = sum(
        1 for left, right in zip(v1_regimes, v2_regimes, strict=False) if left == right
    )
    return DiagnosticV1V2ComparisonReport(
        v1_dataset_version="diagnostic-market-state-reconstruction-v1",
        v2_dataset_version=DIAGNOSTIC_MARKET_STATE_V2_VERSION,
        v1_regime_distribution=_counts(v1_regimes),
        v2_regime_distribution=_counts(v2_regimes),
        regime_agreement=_rate(agree, total),
        neutral_share_v1=_share(v1_regimes, "NEUTRAL"),
        neutral_share_v2=_share(v2_regimes, "NEUTRAL"),
        bullish_share_v1=_share(v1_regimes, "BULLISH"),
        bullish_share_v2=_share(v2_regimes, "BULLISH"),
        bearish_share_v1=_share(v1_regimes, "BEARISH"),
        bearish_share_v2=_share(v2_regimes, "BEARISH"),
        dates_changing_regime=total - agree,
        candidates_changing_linked_diagnostic_regime=total - agree,
        completeness_distribution=(("v2_not_persisted", total),),
        quality_distribution=(("v2_not_persisted", total),),
        conclusion="INSUFFICIENT_COVERAGE",
    )


def build_v2_outcome_comparison() -> V2OutcomeComparisonReport:
    return V2OutcomeComparisonReport(
        v1_outcome_ordering=("NEUTRAL", "BULLISH", "BEARISH"),
        v2_outcome_ordering=(),
        v1_threshold_sensitivity="HIGHLY_SENSITIVE",
        v2_threshold_sensitivity="UNAVAILABLE",
        comparison="INSUFFICIENT_COVERAGE",
        explanation=(
            "Diagnostic v2 is not persisted until point-in-time sector history is "
            "supported."
        ),
    )


def build_sector_incremental_value_report(
    sector_report: SectorCoverageAuditReport,
) -> SectorIncrementalValueReport:
    return SectorIncrementalValueReport(
        comparisons=(
            ("BENCHMARK_ONLY", None),
            ("BENCHMARK_PLUS_BREADTH", None),
            ("BENCHMARK_PLUS_SECTOR", None),
            ("BENCHMARK_PLUS_BREADTH_PLUS_SECTOR", None),
            ("CURRENT_COMPATIBLE_CLASSIFIER", None),
        ),
        conclusion="INSUFFICIENT_COVERAGE"
        if sector_report.readiness
        is not SectorHistoryReadiness.POINT_IN_TIME_SECTOR_HISTORY_READY
        else "SECTOR_STATE_TESTABLE",
        explanation=(
            "Sector classifications are current-mapping-only; incremental value "
            "cannot be claimed."
        ),
    )


def point_in_time_dataset_fingerprint(dataset: PointInTimeUniverseDataset) -> str:
    payload = {
        "dataset_version": dataset.dataset_version,
        "rows": sorted(
            (_jsonable(row) for row in dataset.rows),
            key=lambda item: (item["market_date"], item["security_id"]),
        ),
        "security_records": sorted(
            (_jsonable(row) for row in dataset.security_records),
            key=lambda item: item["security_id"],
        ),
        "sector_classifications": sorted(
            (_jsonable(row) for row in dataset.sector_classifications),
            key=lambda item: (item["security_id"], str(item["sector_name"])),
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def render_source_inventory(
    items: tuple[HistoricalSourceInventoryItem, ...],
) -> tuple[str, ...]:
    lines = ["Historical Security Master Source Audit"]
    for item in items:
        lines.append(
            f"- {item.source}: records={item.record_count}, "
            f"usefulness={item.usefulness.value}, point_in_time="
            f"{'yes' if item.point_in_time_safety else 'no'}, "
            f"coverage={item.date_coverage}"
        )
    return tuple(lines)


def render_security_identity_audit(
    report: SecurityIdentityAuditReport,
) -> tuple[str, ...]:
    return (
        "Security Identity Audit",
        f"Securities: {report.securities}",
        f"Symbols: {report.symbols}",
        f"Securities With ISIN: {report.securities_with_isin}",
        f"Symbol Changes: {report.symbol_changes}",
        f"Reused Symbol Conflicts: {report.reused_symbol_conflicts}",
        f"Merger Lineage Records: {report.merger_lineage_records}",
        f"Demerger Lineage Records: {report.demerger_lineage_records}",
        "Unresolved Identity Conflicts: "
        f"{_text_list(report.unresolved_identity_conflicts)}",
        f"Primary Identity Rule: {report.primary_identity_rule}",
    )


def render_listing_delisting_audit(
    report: ListingDelistingAuditReport,
) -> tuple[str, ...]:
    return (
        "Listing and Delisting Audit",
        f"Securities: {report.securities}",
        f"Official Listing Dates: {report.official_listing_dates}",
        f"Inferred Listing Dates: {report.inferred_listing_dates}",
        f"Unknown Listing Dates: {report.unknown_listing_dates}",
        f"Official Delisting Dates: {report.official_delisting_dates}",
        f"Inferred Delisting Dates: {report.inferred_delisting_dates}",
        f"Unknown Delisting Dates: {report.unknown_delisting_dates}",
        f"Limitations: {_text_list(report.limitations)}",
    )


def render_universe_build(result: PointInTimePersistenceResult) -> tuple[str, ...]:
    return (
        "Point-in-Time Universe Build",
        f"Dataset Version: {result.dataset_version}",
        f"Dry Run: {'yes' if result.dry_run else 'no'}",
        f"Rows: {result.inserted_rows}",
        f"Securities: {result.inserted_securities}",
        f"Classifications: {result.inserted_classifications}",
        f"Path: {result.path}",
        f"Warning: {_warning()}",
    )


def render_universe_coverage(
    report: PointInTimeUniverseCoverageReport,
) -> tuple[str, ...]:
    return (
        "Point-in-Time Universe Coverage",
        f"Dataset Version: {report.dataset_version}",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
        f"Market Dates: {report.market_dates}",
        f"Security Rows: {report.security_rows}",
        f"Eligible Rows: {report.eligible_rows}",
        f"Membership Known Rows: {report.membership_known_rows}",
        f"Price Covered Rows: {report.price_covered_rows}",
        f"DMA Eligible Rows: {report.dma_eligible_rows}",
        f"Sector Classified Rows: {report.sector_classified_rows}",
        f"High Quality Dates: {report.high_quality_dates}",
        f"Partial Dates: {report.partial_dates}",
        f"Unusable Dates: {report.unusable_dates}",
        f"Membership Quality: {report.membership_quality.value}",
        f"Identity Quality: {report.identity_quality.value}",
        f"Price Coverage Quality: {report.price_coverage_quality.value}",
        f"Breadth Quality: {report.breadth_quality.value}",
        f"Sector Classification Quality: {report.sector_classification_quality.value}",
        f"Sector State Quality: {report.sector_state_quality.value}",
        f"Timestamp Quality: {report.timestamp_quality.value}",
        f"Overall Point-in-Time Quality: {report.overall_point_in_time_quality.value}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        f"Secondary Conclusion: {_enum_text(report.secondary_conclusion)}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        "Explicitly Prohibited Next Action: "
        f"{report.explicitly_prohibited_next_action}",
    )


def render_universe_show(
    rows: tuple[PointInTimeUniverseRow, ...],
    market_date: date,
) -> tuple[str, ...]:
    lines = [f"Point-in-Time Universe: {market_date.isoformat()}"]
    for row in rows[:200]:
        lines.append(
            f"- {row.symbol}: {row.membership_status.value}, "
            f"price={'yes' if row.price_available else 'no'}, "
            f"bars={row.bars_available}, "
            f"sector={'yes' if row.sector_available else 'no'}"
        )
    if len(rows) > 200:
        lines.append(f"- ... {len(rows) - 200} additional rows omitted")
    return tuple(lines)


def render_sector_coverage(report: SectorCoverageAuditReport) -> tuple[str, ...]:
    return (
        "Point-in-Time Sector Coverage",
        f"Candidate Dates: {report.candidate_dates}",
        "Point-in-Time Sector Dates: "
        f"{report.dates_with_point_in_time_sector_coverage}",
        f"Supported Sector Dates: {report.dates_with_supported_sector_coverage}",
        "Current-Mapping-Only Dates: "
        f"{report.dates_with_current_mapping_only_coverage}",
        f"Unclassified Dates: {report.dates_unclassified}",
        f"Candidate Records Covered: {report.candidate_records_covered}",
        f"Sectors Represented: {_text_list(report.sectors_represented)}",
        f"Median Sector Universe Size: {_text(report.median_sector_universe_size)}",
        f"Minimum Sector Universe Size: {_text(report.minimum_sector_universe_size)}",
        f"Classification Conflicts: {report.classification_conflicts}",
        f"Readiness: {report.readiness.value}",
    )


def render_sector_conflicts(
    conflicts: tuple[SectorClassificationConflict, ...],
) -> tuple[str, ...]:
    lines = ["Sector Classification Conflicts"]
    if not conflicts:
        lines.append("- none detected")
    for item in conflicts:
        lines.append(
            f"- {item.security_id}: {item.conflict_type}, "
            f"resolution={item.resolution_status}"
        )
    return tuple(lines)


def render_breadth_snapshots(
    snapshots: tuple[PointInTimeBreadthSnapshot, ...],
) -> tuple[str, ...]:
    lines = ["Point-in-Time Breadth"]
    for item in snapshots[:200]:
        lines.append(
            f"- {item.market_date}: eligible={item.eligible_universe_size}, "
            f"priced={item.priced_universe_size}, adv={item.advancers}, "
            f"dec={item.decliners}, breadth={_text(item.breadth_ratio)}, "
            f"200dma={_text(item.percent_above_200dma)}, "
            f"status={item.breadth_completeness.value}"
        )
    return tuple(lines)


def render_sector_state(report: HistoricalSectorStateReport) -> tuple[str, ...]:
    lines = [
        f"Historical Sector State: {report.market_date}",
        "Label: stock-aggregated sector state; not sector index",
        f"Leading Sector: {report.leading_sector or 'unavailable'}",
        f"Lagging Sector: {report.lagging_sector or 'unavailable'}",
        f"Data Completeness: {report.data_completeness.value}",
    ]
    for item in report.sector_states[:100]:
        lines.append(
            f"- {item.sector}: n={item.priced_securities}, "
            f"return_1d={_text(item.return_1d)}, breadth={_text(item.breadth_ratio)}, "
            f"rank={_text(item.leadership_rank)}"
        )
    return tuple(lines)


def render_survivorship_bias(report: SurvivorshipBiasAuditReport) -> tuple[str, ...]:
    return (
        "Survivorship-Bias Audit",
        f"Dates Checked: {len(report.rows)}",
        f"Dates Materially Affected: {report.dates_materially_affected}",
        f"Candidate Records Affected: {report.candidate_records_affected}",
        f"Regime Changes: {report.recorded_reconstructed_regime_changes}",
        f"Outcome Conclusions Affected: {report.outcome_conclusions_affected}",
        f"Finding: {report.finding}",
    )


def render_diagnostic_v2_build(
    report: DiagnosticMarketStateV2BuildReport,
) -> tuple[str, ...]:
    return (
        "Diagnostic Market-State V2 Build",
        f"Dataset Version: {report.dataset_version}",
        f"Dry Run: {'yes' if report.dry_run else 'no'}",
        f"Universe Dataset Version: {report.universe_dataset_version}",
        f"Universe Fingerprint: {report.universe_dataset_fingerprint}",
        f"Sector Dataset Version: {report.sector_dataset_version}",
        f"Sector Fingerprint: {report.sector_dataset_fingerprint}",
        f"Breadth Builder: {report.breadth_builder_version}",
        f"Sector-State Builder: {report.sector_state_builder_version}",
        f"Classifier Version: {report.classifier_version}",
        f"Source Lineage Fingerprint: {report.source_lineage_fingerprint}",
        f"Reconstructions Would Create: {report.reconstructions_would_create}",
        f"Candidate Links Would Create: {report.candidate_links_would_create}",
        f"Persistence Status: {report.persistence_status}",
        f"Blocked Reason: {report.blocked_reason or 'none'}",
    )


def render_v1_v2_comparison(report: DiagnosticV1V2ComparisonReport) -> tuple[str, ...]:
    return (
        "Diagnostic Market-State V1/V2 Comparison",
        f"V1 Distribution: {_pairs(report.v1_regime_distribution)}",
        f"V2 Distribution: {_pairs(report.v2_regime_distribution)}",
        f"Regime Agreement: {_text(report.regime_agreement)}",
        f"Neutral Share V1: {_text(report.neutral_share_v1)}",
        f"Neutral Share V2: {_text(report.neutral_share_v2)}",
        f"Dates Changing Regime: {report.dates_changing_regime}",
        "Candidates Changing Linked Regime: "
        f"{report.candidates_changing_linked_diagnostic_regime}",
        f"Conclusion: {report.conclusion}",
    )


def render_v2_outcome_comparison(report: V2OutcomeComparisonReport) -> tuple[str, ...]:
    return (
        "Diagnostic Market-State V2 Outcome Comparison",
        f"V1 Outcome Ordering: {_text_list(report.v1_outcome_ordering)}",
        f"V2 Outcome Ordering: {_text_list(report.v2_outcome_ordering)}",
        f"V1 Threshold Sensitivity: {report.v1_threshold_sensitivity}",
        f"V2 Threshold Sensitivity: {report.v2_threshold_sensitivity}",
        f"Comparison: {report.comparison}",
        f"Explanation: {report.explanation}",
    )


def render_sector_incremental_value(
    report: SectorIncrementalValueReport,
) -> tuple[str, ...]:
    lines = [
        "Sector Incremental-Value Audit",
        f"Conclusion: {report.conclusion}",
        f"Explanation: {report.explanation}",
    ]
    lines.extend(f"- {name}: {_text(value)}" for name, value in report.comparisons)
    return tuple(lines)


def render_point_in_time_history_readiness(
    coverage: PointInTimeUniverseCoverageReport,
    sector: SectorCoverageAuditReport,
    survivorship: SurvivorshipBiasAuditReport,
) -> tuple[str, ...]:
    primary = _readiness_conclusion(coverage, sector, survivorship)
    return (
        "Point-in-Time History Readiness",
        f"Universe Quality: {coverage.overall_point_in_time_quality.value}",
        f"Sector Readiness: {sector.readiness.value}",
        f"Survivorship Finding: {survivorship.finding}",
        f"Primary Conclusion: {primary.value}",
        "Secondary Conclusion: "
        f"{PointInTimeConclusion.SECTOR_CLASSIFICATION_HISTORY_IS_PRIMARY_BOTTLENECK.value}",
        "Recommended Next Milestone: "
        f"{PointInTimeNextMilestone.BUILD_HISTORICAL_SECTOR_CLASSIFICATION_INGESTION.value}",
        f"Explicitly Prohibited Next Action: {_prohibited_next_action()}",
    )


def export_point_in_time_json(payload: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")
    return path


def export_point_in_time_csv(rows: tuple[Any, ...], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    dictionaries = [_jsonable(row) for row in rows] or [{"status": "unavailable"}]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(dictionaries[0].keys()))
        writer.writeheader()
        writer.writerows(dictionaries)
    return path


def resolve_point_in_time_universe_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("ALPHA_POINT_IN_TIME_UNIVERSE_LEDGER")
    if configured:
        return Path(configured)
    return DEFAULT_POINT_IN_TIME_UNIVERSE_PATH


def _security_records(
    price_frames: dict[date, pd.DataFrame],
    ingested_at: datetime,
) -> tuple[PointInTimeSecurityRecord, ...]:
    seen: dict[str, dict[str, Any]] = {}
    for market_date, frame in sorted(price_frames.items()):
        for price_row in frame.to_dict("records"):
            symbol = str(price_row.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            entry = seen.setdefault(
                symbol,
                {
                    "first": market_date,
                    "last": market_date,
                    "sectors": set(),
                    "exchange": str(price_row.get("exchange") or "NSE").upper(),
                },
            )
            entry["first"] = min(entry["first"], market_date)
            entry["last"] = max(entry["last"], market_date)
            sector = _optional_text(price_row.get("sector"))
            if sector:
                entry["sectors"].add(sector)
    securities = []
    for symbol, security_data in sorted(seen.items()):
        sectors = sorted(security_data["sectors"])
        sector = sectors[-1] if sectors else None
        security_id = _stable_id(
            {
                "symbol": symbol,
                "exchange": security_data["exchange"],
                "instrument_type": "EQUITY_OR_UNKNOWN",
                "first": security_data["first"].isoformat(),
            }
        )
        missing = []
        if not sector:
            missing.append("sector")
        missing.extend(("isin", "official_listing_date", "official_delisting_date"))
        securities.append(
            PointInTimeSecurityRecord(
                security_id=security_id,
                symbol=symbol,
                exchange=security_data["exchange"],
                instrument_type="EQUITY_OR_UNKNOWN",
                isin=None,
                company_name=None,
                effective_from=security_data["first"],
                effective_to=None,
                listing_date=security_data["first"],
                delisting_date=security_data["last"],
                listing_date_evidence=HistoricalDateEvidence.WEAK_INFERRED_DATE,
                delisting_date_evidence=HistoricalDateEvidence.WEAK_INFERRED_DATE,
                status="LOCAL_PRICE_OBSERVED",
                previous_symbol=None,
                successor_symbol=None,
                corporate_action_lineage=(),
                sector_code=None,
                sector_name=sector,
                industry_code=None,
                industry_name=None,
                classification_source="daily_prices.sector" if sector else None,
                classification_effective_from=None,
                classification_effective_to=None,
                source="daily_prices",
                source_timestamp=None,
                ingested_at=ingested_at,
                source_authority="local diagnostic price archive",
                point_in_time_status=PointInTimeStatus.WEAK_INFERRED,
                missing_fields=tuple(missing),
                schema_version="point-in-time-security-record-v1",
            )
        )
    return tuple(securities)


def _membership_status(
    security: PointInTimeSecurityRecord,
    market_date: date,
    symbols_on_date: set[str],
) -> HistoricalMembershipStatus:
    if security.listing_date and market_date < security.listing_date:
        return HistoricalMembershipStatus.INELIGIBLE_NOT_YET_LISTED
    if security.delisting_date and market_date > security.delisting_date:
        return HistoricalMembershipStatus.INELIGIBLE_DELISTED
    if security.symbol not in symbols_on_date:
        return HistoricalMembershipStatus.INELIGIBLE_PRICE_HISTORY
    if security.instrument_type not in {"EQUITY", "EQUITY_OR_UNKNOWN"}:
        return HistoricalMembershipStatus.INELIGIBLE_INSTRUMENT_TYPE
    return HistoricalMembershipStatus.ELIGIBLE


def _membership_reason(status: HistoricalMembershipStatus) -> str:
    if status is HistoricalMembershipStatus.ELIGIBLE:
        return "local same-date price exists; listing status weak-inferred"
    return status.value.lower()


def _price_frame(price_repository: Any, market_date: date) -> pd.DataFrame:
    if not hasattr(price_repository, "find_by_trade_date"):
        return _empty_price_frame()
    frame = price_repository.find_by_trade_date(market_date)
    if frame.empty:
        return cast(pd.DataFrame, frame)
    frame = frame.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    return cast(pd.DataFrame, frame)


def _price_frames_by_date(
    price_repository: Any,
    candidate_dates: tuple[date, ...],
) -> dict[date, pd.DataFrame]:
    if not candidate_dates:
        return {}
    database = getattr(price_repository, "db", None)
    execute = getattr(database, "execute", None)
    if callable(execute):
        placeholders = ", ".join("?" for _ in candidate_dates)
        result = execute(
            f"""
            SELECT
                symbol,
                trade_date,
                open,
                high,
                low,
                close,
                volume,
                sector,
                exchange
            FROM daily_prices
            WHERE trade_date IN ({placeholders})
            ORDER BY trade_date, symbol
            """,
            candidate_dates,
        )
        frame = pd.DataFrame(
            result.fetchall(),
            columns=(
                "symbol",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "sector",
                "exchange",
            ),
        )
        if frame.empty:
            return {
                market_date: _empty_price_frame() for market_date in candidate_dates
            }
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
        return {
            market_date: group.reset_index(drop=True)
            for market_date, group in frame.groupby("trade_date")
            if isinstance(market_date, date)
        } | {
            market_date: _empty_price_frame()
            for market_date in candidate_dates
            if market_date not in set(frame["trade_date"])
        }
    return {
        market_date: _price_frame(price_repository, market_date)
        for market_date in candidate_dates
    }


def _empty_price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=(
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "sector",
            "exchange",
        )
    )


def _history(
    price_repository: Any, symbol: str, market_date: date, limit: int
) -> tuple[dict[str, Any], ...]:
    if not hasattr(price_repository, "find_history_by_symbols"):
        return ()
    frame = price_repository.find_history_by_symbols(
        symbols=(symbol,),
        end_date=market_date,
        limit=limit,
    )
    return tuple(frame.to_dict("records"))


def _history_counts(
    price_repository: Any,
    symbols: tuple[str, ...],
    candidate_dates: tuple[date, ...],
) -> dict[tuple[str, date], int]:
    if not symbols or not candidate_dates:
        return {}
    database = getattr(price_repository, "db", None)
    execute = getattr(database, "execute", None)
    if callable(execute):
        normalized_symbols = tuple(dict.fromkeys(symbol.upper() for symbol in symbols))
        symbol_placeholders = ", ".join("?" for _ in normalized_symbols)
        date_values = ", ".join("(?)" for _ in candidate_dates)
        result = execute(
            f"""
            WITH candidate_dates(market_date) AS (
                VALUES {date_values}
            )
            SELECT
                UPPER(prices.symbol) AS symbol,
                candidate_dates.market_date AS market_date,
                COUNT(*) AS bars_available
            FROM daily_prices AS prices
            JOIN candidate_dates
              ON prices.trade_date <= candidate_dates.market_date
            WHERE UPPER(prices.symbol) IN ({symbol_placeholders})
            GROUP BY 1, 2
            """,
            (*candidate_dates, *normalized_symbols),
        )
        return {
            (str(symbol).upper(), market_date): int(count)
            for symbol, market_date, count in result.fetchall()
            if isinstance(market_date, date)
        }
    if not hasattr(price_repository, "find_history_by_symbols"):
        return {}
    frame = price_repository.find_history_by_symbols(
        symbols=symbols,
        end_date=max(candidate_dates),
        limit=260,
    )
    if frame.empty:
        return {}
    history_by_symbol: dict[str, list[date]] = defaultdict(list)
    for row in frame.to_dict("records"):
        symbol = str(row.get("symbol", "")).upper()
        trade_date = row.get("trade_date")
        if symbol and isinstance(trade_date, date):
            history_by_symbol[symbol].append(trade_date)
    counts: dict[tuple[str, date], int] = {}
    for symbol, dates in history_by_symbol.items():
        sorted_dates = sorted(dates)
        for market_date in candidate_dates:
            counts[(symbol, market_date)] = sum(
                1 for trade_date in sorted_dates if trade_date <= market_date
            )
    return counts


def _bars_available(price_repository: Any, symbol: str, market_date: date) -> int:
    return len(_history(price_repository, symbol, market_date, 260))


def _liquidity_available(frame: pd.DataFrame, symbol: str) -> bool:
    if frame.empty or "volume" not in frame:
        return False
    rows = frame[frame["symbol"].astype(str).str.upper() == symbol]
    if rows.empty:
        return False
    volume = _decimal(rows.iloc[-1].get("volume"))
    return volume is not None and volume > _ZERO


def _sector_by_symbol(frame: pd.DataFrame) -> dict[str, str]:
    if frame.empty or "sector" not in frame:
        return {}
    return {
        str(row["symbol"]).upper(): str(row["sector"]).upper()
        for row in frame.to_dict("records")
        if _optional_text(row.get("sector"))
    }


def _returns_for_symbols(
    frame: pd.DataFrame, symbols: tuple[str, ...]
) -> tuple[Decimal, ...]:
    values = []
    symbol_set = set(symbols)
    for row in frame.to_dict("records"):
        if str(row.get("symbol", "")).upper() not in symbol_set:
            continue
        close = _decimal(row.get("close"))
        opening = _decimal(row.get("open"))
        if close is not None and opening is not None:
            value = _pct_return(close, opening)
            if value is not None:
                values.append(value)
    return tuple(values)


def _benchmark_return(frame: pd.DataFrame) -> Decimal | None:
    if frame.empty:
        return None
    rows = frame[frame["symbol"].astype(str).str.upper() == "NIFTYBEES"]
    if rows.empty:
        return None
    row = rows.iloc[-1]
    close = _decimal(row.get("close"))
    opening = _decimal(row.get("open"))
    if close is None or opening is None:
        return None
    return _pct_return(close, opening)


def _same_day_breadth_ratio(frame: pd.DataFrame) -> Decimal | None:
    adv = dec = 0
    for row in frame.to_dict("records"):
        close = _decimal(row.get("close"))
        opening = _decimal(row.get("open"))
        if close is None or opening is None:
            continue
        if close > opening:
            adv += 1
        elif close < opening:
            dec += 1
    return _rate(adv, adv + dec)


def _date_quality(rows: tuple[PointInTimeUniverseRow, ...]) -> UniverseQualityGrade:
    if not rows:
        return UniverseQualityGrade.UNUSABLE
    eligible = sum(
        1
        for row in rows
        if row.membership_status is HistoricalMembershipStatus.ELIGIBLE
    )
    if eligible <= 0:
        return UniverseQualityGrade.UNUSABLE
    coverage = Decimal(eligible) / Decimal(len(rows))
    if coverage >= Decimal("0.90") and all(row.bars_available >= 200 for row in rows):
        return UniverseQualityGrade.HIGH
    if coverage >= Decimal("0.70"):
        return UniverseQualityGrade.MEDIUM
    return UniverseQualityGrade.LOW


def _breadth_status(
    priced: int,
    eligible: int,
    dma200_eligible: int,
) -> BreadthCoverageStatus:
    if eligible <= 0 or priced <= 0:
        return BreadthCoverageStatus.UNUSABLE
    coverage = Decimal(priced) / Decimal(eligible)
    if coverage >= Decimal("0.95") and dma200_eligible >= max(1, eligible // 2):
        return BreadthCoverageStatus.COMPLETE
    if coverage >= Decimal("0.80"):
        return BreadthCoverageStatus.HIGH_COVERAGE
    if coverage >= Decimal("0.50"):
        return BreadthCoverageStatus.PARTIAL
    return BreadthCoverageStatus.LOW_COVERAGE


def _readiness_conclusion(
    coverage: PointInTimeUniverseCoverageReport,
    sector: SectorCoverageAuditReport,
    survivorship: SurvivorshipBiasAuditReport,
) -> PointInTimeConclusion:
    if sector.readiness in {
        SectorHistoryReadiness.CURRENT_MAPPING_ONLY,
        SectorHistoryReadiness.SECTOR_HISTORY_UNUSABLE,
    }:
        return PointInTimeConclusion.SECTOR_CLASSIFICATION_HISTORY_IS_PRIMARY_BOTTLENECK
    if survivorship.finding == "CURRENT_UNIVERSE_BIAS_IS_MATERIAL":
        return PointInTimeConclusion.CURRENT_UNIVERSE_BIAS_IS_PRIMARY_BOTTLENECK
    return coverage.primary_conclusion


def _empty_payload() -> dict[str, Any]:
    return {
        "dataset_version": POINT_IN_TIME_UNIVERSE_DATASET_VERSION,
        "rows": [],
        "security_records": [],
        "sector_classifications": [],
        "lineage": [],
        "created_at": datetime(1970, 1, 1, tzinfo=UTC).isoformat(),
        "non_authoritative_warning": _warning(),
    }


def _security_from_dict(payload: dict[str, Any]) -> PointInTimeSecurityRecord:
    row = _parse_dates(payload)
    return PointInTimeSecurityRecord(
        **{
            **row,
            "listing_date_evidence": HistoricalDateEvidence(
                row["listing_date_evidence"]
            ),
            "delisting_date_evidence": HistoricalDateEvidence(
                row["delisting_date_evidence"]
            ),
            "point_in_time_status": PointInTimeStatus(row["point_in_time_status"]),
            "corporate_action_lineage": tuple(row.get("corporate_action_lineage", ())),
            "missing_fields": tuple(row.get("missing_fields", ())),
        }
    )


def _classification_from_dict(
    payload: dict[str, Any],
) -> PointInTimeSectorClassification:
    row = _parse_dates(payload)
    return PointInTimeSectorClassification(
        **{
            **row,
            "point_in_time_status": PointInTimeStatus(row["point_in_time_status"]),
            "confidence": UniverseQualityGrade(row["confidence"]),
        }
    )


def _lineage_from_dict(payload: dict[str, Any]) -> SecurityLineageMapping:
    row = _parse_dates(payload)
    return SecurityLineageMapping(
        **{**row, "confidence": UniverseQualityGrade(row["confidence"])}
    )


def _parse_dates(payload: dict[str, Any]) -> dict[str, Any]:
    row = dict(payload)
    for key in (
        "market_date",
        "effective_from",
        "effective_to",
        "listing_date",
        "delisting_date",
        "classification_effective_from",
        "classification_effective_to",
        "source_timestamp",
        "ingested_at",
        "created_at",
        "effective_date",
    ):
        if key not in row or row[key] is None:
            continue
        if key.endswith("_at") or key in {
            "source_timestamp",
            "ingested_at",
            "created_at",
        }:
            row[key] = _payload_datetime(row[key])
        else:
            row[key] = date.fromisoformat(str(row[key]))
    if "membership_status" in row:
        row["membership_status"] = HistoricalMembershipStatus(row["membership_status"])
    if "source_quality" in row:
        row["source_quality"] = UniverseQualityGrade(row["source_quality"])
    if "point_in_time_confidence" in row:
        row["point_in_time_confidence"] = UniverseQualityGrade(
            row["point_in_time_confidence"]
        )
    if "source_lineage" in row:
        row["source_lineage"] = tuple(row["source_lineage"])
    return row


def _payload_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _series(frame: pd.DataFrame, column: str) -> tuple[str, ...]:
    if frame.empty or column not in frame:
        return ()
    return tuple(str(item).strip().upper() for item in frame[column].dropna().tolist())


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NONE", "NAN", "<NA>"}:
        return None
    return Decimal(text)


def _pct_return(close: Decimal, previous: Decimal) -> Decimal | None:
    if previous == _ZERO:
        return None
    return _quantize((close - previous) / previous * _HUNDRED)


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return _quantize(Decimal(numerator) / Decimal(denominator))


def _share(values: tuple[str, ...], target: str) -> Decimal | None:
    return _rate(sum(1 for value in values if value == target), len(values))


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return _quantize(sum(values) / Decimal(len(values)))


def _median(values: tuple[Decimal, ...] | list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return _quantize(Decimal(str(median(values))))


def _median_int(values: tuple[int, ...]) -> Decimal | None:
    if not values:
        return None
    return Decimal(str(median(values))).quantize(_TWO)


def _dispersion(values: tuple[Decimal, ...] | list[Decimal]) -> Decimal | None:
    if not values:
        return None
    avg = sum(values) / Decimal(len(values))
    absolute = [abs(value - avg) for value in values]
    return _mean(tuple(absolute))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_FOUR, rounding=ROUND_HALF_UP)


def _counts(values: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(values).items()))


def _pairs(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values) or "unavailable"


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return None if text in {"", "NONE", "NAN", "<NA>"} else text


def _text(value: object | None) -> str:
    return "unavailable" if value is None else str(value)


def _text_list(values: tuple[str, ...]) -> str:
    return ", ".join(values) or "none"


def _enum_text(value: StrEnum | None) -> str:
    return "none" if value is None else value.value


def _stable_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def _warning() -> str:
    return (
        "Point-in-time universe records are diagnostic unless backed by official "
        "security-master and sector-classification effective-period sources."
    )


def _prohibited_next_action() -> str:
    return (
        "Do not tune market-regime thresholds, select historically optimal "
        "boundaries, change regime labels, classifier weights, intervention, "
        "scores, candidate generation, verdicts, entry timing, gates, trade "
        "plans, approvals, allocation, retracement signs, legacy candidates, "
        "diagnostic v1, or represent diagnostic data as exact production history."
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


__all__ = [
    "DEFAULT_POINT_IN_TIME_UNIVERSE_PATH",
    "DIAGNOSTIC_MARKET_STATE_V2_VERSION",
    "POINT_IN_TIME_SECTOR_DATASET_VERSION",
    "POINT_IN_TIME_UNIVERSE_DATASET_VERSION",
    "BreadthCoverageStatus",
    "DiagnosticMarketStateV2BuildReport",
    "DiagnosticV1V2ComparisonReport",
    "HistoricalMembershipStatus",
    "HistoricalSectorStateBuilder",
    "HistoricalSectorStateReport",
    "HistoricalSourceInventoryItem",
    "HistoricalSourceUsefulness",
    "PointInTimeBreadthSnapshot",
    "PointInTimeConclusion",
    "PointInTimeMarketBreadthBuilder",
    "PointInTimeNextMilestone",
    "PointInTimePersistenceResult",
    "PointInTimeSectorClassification",
    "PointInTimeSecurityRecord",
    "PointInTimeStatus",
    "PointInTimeUniverseBuilder",
    "PointInTimeUniverseCoverageReport",
    "PointInTimeUniverseDataset",
    "PointInTimeUniverseRepository",
    "PointInTimeUniverseRow",
    "SectorCoverageAuditReport",
    "SectorHistoryReadiness",
    "SecurityIdentityAuditReport",
    "SurvivorshipBiasAuditReport",
    "UniverseQualityGrade",
    "V2OutcomeComparisonReport",
    "build_breadth_snapshots",
    "build_diagnostic_v2_report",
    "build_historical_source_inventory",
    "build_listing_delisting_audit",
    "build_sector_conflicts",
    "build_sector_coverage_audit",
    "build_sector_incremental_value_report",
    "build_sector_state_report",
    "build_security_identity_audit",
    "build_survivorship_bias_audit",
    "build_universe_coverage_report",
    "build_v1_v2_comparison",
    "build_v2_outcome_comparison",
    "export_point_in_time_csv",
    "export_point_in_time_json",
    "point_in_time_dataset_fingerprint",
    "render_breadth_snapshots",
    "render_diagnostic_v2_build",
    "render_listing_delisting_audit",
    "render_point_in_time_history_readiness",
    "render_sector_conflicts",
    "render_sector_coverage",
    "render_sector_incremental_value",
    "render_sector_state",
    "render_security_identity_audit",
    "render_source_inventory",
    "render_survivorship_bias",
    "render_universe_build",
    "render_universe_coverage",
    "render_universe_show",
    "render_v1_v2_comparison",
    "render_v2_outcome_comparison",
    "resolve_point_in_time_universe_path",
]
