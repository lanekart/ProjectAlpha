from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb

from alpha.market_intelligence.point_in_time_store import (
    resolve_point_in_time_store_path,
)

_PROHIBITED_NEXT_ACTION = (
    "Do not build diagnostic v3, persist historical sector classifications, "
    "apply current sector mappings backward, infer effective periods without "
    "labels, treat index membership as sector classification, modify regime "
    "thresholds, alter regime labels, change classifier conditions, alter "
    "market-intelligence weights, change recommendation scores, modify "
    "candidate generation, change verdicts, alter entry timing, modify gates, "
    "change trade plans, alter approvals, modify allocation, or flip "
    "retracement signs."
)


class HistoricalSectorSourceAuthority(StrEnum):
    OFFICIAL_AUTHORITATIVE = "OFFICIAL_AUTHORITATIVE"
    OFFICIAL_WITH_LIMITATIONS = "OFFICIAL_WITH_LIMITATIONS"
    STRONG_COMMERCIAL = "STRONG_COMMERCIAL"
    STRONG_PUBLIC_ARCHIVE = "STRONG_PUBLIC_ARCHIVE"
    SUPPORTED_RECONSTRUCTION_SOURCE = "SUPPORTED_RECONSTRUCTION_SOURCE"
    CURRENT_STATE_ONLY = "CURRENT_STATE_ONLY"
    INDEX_MEMBERSHIP_ONLY = "INDEX_MEMBERSHIP_ONLY"
    WEAK = "WEAK"
    UNUSABLE = "UNUSABLE"


class TemporalSuitability(StrEnum):
    TRUE_EFFECTIVE_DATED = "TRUE_EFFECTIVE_DATED"
    ARCHIVED_SNAPSHOT_DATED = "ARCHIVED_SNAPSHOT_DATED"
    CHANGE_EVENT_DATED = "CHANGE_EVENT_DATED"
    PUBLICATION_DATE_ONLY = "PUBLICATION_DATE_ONLY"
    CURRENT_ONLY = "CURRENT_ONLY"
    TEMPORAL_STATUS_UNKNOWN = "TEMPORAL_STATUS_UNKNOWN"


class IdentityJoinability(StrEnum):
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    MODERATE_CONFIDENCE = "MODERATE_CONFIDENCE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNUSABLE = "UNUSABLE"


class TaxonomyStability(StrEnum):
    STABLE_VERSIONED_TAXONOMY = "STABLE_VERSIONED_TAXONOMY"
    VERSIONED_WITH_MAPPING_AVAILABLE = "VERSIONED_WITH_MAPPING_AVAILABLE"
    VERSIONED_WITHOUT_MAPPING = "VERSIONED_WITHOUT_MAPPING"
    UNVERSIONED_TAXONOMY = "UNVERSIONED_TAXONOMY"
    CURRENT_TAXONOMY_ONLY = "CURRENT_TAXONOMY_ONLY"


class HistoricalSectorCoverageStatus(StrEnum):
    FULL = "FULL"
    HIGH = "HIGH"
    PARTIAL = "PARTIAL"
    LOW = "LOW"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class SourceCombinationFinding(StrEnum):
    SINGLE_SOURCE_SUFFICIENT = "SINGLE_SOURCE_SUFFICIENT"
    MULTI_SOURCE_RECONSTRUCTION_FEASIBLE = "MULTI_SOURCE_RECONSTRUCTION_FEASIBLE"
    MULTI_SOURCE_RECONSTRUCTION_HIGH_RISK = "MULTI_SOURCE_RECONSTRUCTION_HIGH_RISK"
    NO_SAFE_SOURCE_COMBINATION = "NO_SAFE_SOURCE_COMBINATION"


class OperationalStatus(StrEnum):
    AUTOMATABLE = "AUTOMATABLE"
    AUTOMATABLE_WITH_LIMITATIONS = "AUTOMATABLE_WITH_LIMITATIONS"
    MANUAL_ARCHIVE_REQUIRED = "MANUAL_ARCHIVE_REQUIRED"
    PAID_VENDOR_REQUIRED = "PAID_VENDOR_REQUIRED"
    LICENSING_REVIEW_REQUIRED = "LICENSING_REVIEW_REQUIRED"
    OPERATIONALLY_UNSUITABLE = "OPERATIONALLY_UNSUITABLE"


class CostValueTier(StrEnum):
    HIGH_VALUE = "HIGH_VALUE"
    MODERATE_VALUE = "MODERATE_VALUE"
    LOW_VALUE = "LOW_VALUE"
    UNJUSTIFIED = "UNJUSTIFIED"
    UNKNOWN = "UNKNOWN"


class SectorNecessityClassification(StrEnum):
    SECTOR_LIKELY_MATERIAL = "SECTOR_LIKELY_MATERIAL"
    SECTOR_POTENTIALLY_MATERIAL = "SECTOR_POTENTIALLY_MATERIAL"
    SECTOR_LIKELY_MINOR = "SECTOR_LIKELY_MINOR"
    SECTOR_UNUSED_BY_CURRENT_CLASSIFIER = "SECTOR_UNUSED_BY_CURRENT_CLASSIFIER"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AcquisitionDecisionStatus(StrEnum):
    RECOMMENDED = "RECOMMENDED"
    CONDITIONALLY_RECOMMENDED = "CONDITIONALLY_RECOMMENDED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AcquisitionPrimaryConclusion(StrEnum):
    OFFICIAL_SECTOR_SOURCE_IS_AVAILABLE = "OFFICIAL_SECTOR_SOURCE_IS_AVAILABLE"
    COMMERCIAL_SECTOR_SOURCE_IS_REQUIRED = "COMMERCIAL_SECTOR_SOURCE_IS_REQUIRED"
    MULTI_SOURCE_RECONSTRUCTION_IS_FEASIBLE = "MULTI_SOURCE_RECONSTRUCTION_IS_FEASIBLE"
    ONLY_CURRENT_STATE_SECTOR_DATA_IS_AVAILABLE = (
        "ONLY_CURRENT_STATE_SECTOR_DATA_IS_AVAILABLE"
    )
    HISTORICAL_SECTOR_SOURCE_COVERAGE_IS_INSUFFICIENT = (
        "HISTORICAL_SECTOR_SOURCE_COVERAGE_IS_INSUFFICIENT"
    )
    SECTOR_IDENTITY_JOINABILITY_IS_PRIMARY_BOTTLENECK = (
        "SECTOR_IDENTITY_JOINABILITY_IS_PRIMARY_BOTTLENECK"
    )
    SECTOR_TAXONOMY_VERSIONING_IS_PRIMARY_BOTTLENECK = (
        "SECTOR_TAXONOMY_VERSIONING_IS_PRIMARY_BOTTLENECK"
    )
    LICENSING_IS_PRIMARY_BOTTLENECK = "LICENSING_IS_PRIMARY_BOTTLENECK"
    SECTOR_DATA_VALUE_DOES_NOT_JUSTIFY_ACQUISITION = (
        "SECTOR_DATA_VALUE_DOES_NOT_JUSTIFY_ACQUISITION"
    )
    INSUFFICIENT_EVIDENCE_FOR_SECTOR_SOURCE_DECISION = (
        "INSUFFICIENT_EVIDENCE_FOR_SECTOR_SOURCE_DECISION"
    )


class AcquisitionNextMilestone(StrEnum):
    IMPLEMENT_OFFICIAL_SECTOR_SOURCE_INGESTION = (
        "IMPLEMENT_OFFICIAL_SECTOR_SOURCE_INGESTION"
    )
    IMPLEMENT_MULTI_SOURCE_SECTOR_RECONSTRUCTION = (
        "IMPLEMENT_MULTI_SOURCE_SECTOR_RECONSTRUCTION"
    )
    INTEGRATE_COMMERCIAL_SECTOR_VENDOR = "INTEGRATE_COMMERCIAL_SECTOR_VENDOR"
    BUILD_SECTOR_TAXONOMY_MAPPING = "BUILD_SECTOR_TAXONOMY_MAPPING"
    REPAIR_SECURITY_IDENTITY_FOR_SECTOR_JOIN = (
        "REPAIR_SECURITY_IDENTITY_FOR_SECTOR_JOIN"
    )
    PERFORM_LICENSING_REVIEW = "PERFORM_LICENSING_REVIEW"
    SIMPLIFY_MARKET_REGIME_TO_BENCHMARK_AND_BREADTH = (
        "SIMPLIFY_MARKET_REGIME_TO_BENCHMARK_AND_BREADTH"
    )
    ACCEPT_MARKET_REGIME_AS_DIAGNOSTIC_ONLY = "ACCEPT_MARKET_REGIME_AS_DIAGNOSTIC_ONLY"
    COLLECT_MORE_SOURCE_EVIDENCE = "COLLECT_MORE_SOURCE_EVIDENCE"


@dataclass(frozen=True, slots=True)
class HistoricalSectorSourceCandidate:
    source_id: str
    provider: str
    source_name: str
    source_type: str
    official_status: str
    access_method: str
    format: str
    taxonomy_name: str
    taxonomy_version: str
    coverage_start: date | None
    coverage_end: date | None
    effective_date_support: bool
    temporal_suitability: TemporalSuitability
    security_identity_fields: tuple[str, ...]
    isin_available: bool
    symbol_available: bool
    historical_archives_available: bool
    update_frequency: str
    licensing_status: str
    cost_model: str
    automation_feasibility: OperationalStatus
    source_stability: str
    authority: HistoricalSectorSourceAuthority
    limitations: tuple[str, ...]
    sample_url_or_reference: str
    taxonomy_stability: TaxonomyStability
    expected_coverage: HistoricalSectorCoverageStatus
    expected_value: CostValueTier


@dataclass(frozen=True, slots=True)
class SectorSourceSampleReport:
    source_id: str
    sample_attempted: bool
    sample_records_parsed: int
    fields_observed: tuple[str, ...]
    date_fields: tuple[str, ...]
    identity_fields: tuple[str, ...]
    sector_fields: tuple[str, ...]
    taxonomy_fields: tuple[str, ...]
    archival_consistency: str
    schema_stability: str
    duplicate_records: int
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SectorSourceIdentityTestReport:
    source_id: str
    records_sampled: int
    exact_identity_matches: int
    isin_matches: int
    instrument_id_matches: int
    symbol_lineage_matches: int
    ambiguous_matches: int
    unmatched_records: int
    reused_symbol_conflicts: int
    corporate_action_conflicts: int
    joinability: IdentityJoinability
    explanation: str


@dataclass(frozen=True, slots=True)
class SectorSourceCoverageEstimate:
    source_id: str
    candidate_dates_total: int
    candidate_records_total: int
    candidate_dates_potentially_covered: int
    candidate_records_potentially_covered: int
    security_identities_potentially_covered: int
    earliest_usable_date: date | None
    latest_usable_date: date | None
    gaps: tuple[str, ...]
    taxonomy_changes: tuple[str, ...]
    identity_gaps: tuple[str, ...]
    effective_date_gaps: tuple[str, ...]
    coverage_status: HistoricalSectorCoverageStatus
    explanation: str


@dataclass(frozen=True, slots=True)
class SectorSourceTaxonomyAuditRow:
    source_id: str
    taxonomy_name: str
    taxonomy_version: str
    hierarchy: tuple[str, ...]
    stability: TaxonomyStability
    changes: tuple[str, ...]
    mapping_requirement: str
    conflict_risk: str


@dataclass(frozen=True, slots=True)
class SectorSourceLicensingAuditRow:
    source_id: str
    free_or_paid: str
    registration_required: bool
    api_available: bool
    bulk_download_available: bool
    manual_download_only: bool
    redistribution_restrictions: str
    storage_restrictions: str
    rate_limits: str
    commercial_use_restrictions: str
    automation_restrictions: str
    expected_maintenance_burden: str
    operational_status: OperationalStatus
    uncertainty: str


@dataclass(frozen=True, slots=True)
class SectorSourceCombinationAssessment:
    combination_id: str
    primary_source: str
    supporting_source: str
    identity_source: str
    effective_date_source: str
    taxonomy_mapping_requirement: str
    conflict_risk: str
    expected_authority: HistoricalSectorSourceAuthority
    expected_coverage: HistoricalSectorCoverageStatus
    finding: SourceCombinationFinding
    explanation: str


@dataclass(frozen=True, slots=True)
class SectorNecessitySensitivityReport:
    candidate_dates_potentially_affected_by_sector: int
    candidate_records_potentially_affected: int
    maximum_regime_assignment_changes: int
    maximum_score_intervention_changes: int
    classification: SectorNecessityClassification
    explanation: str


@dataclass(frozen=True, slots=True)
class SectorSourceDecisionMatrixRow:
    source_id: str
    authority: str
    effective_dating: str
    identity_joinability: str
    historical_coverage: str
    taxonomy_quality: str
    operational_feasibility: str
    licensing_clarity: str
    cost: str
    expected_analytical_value: str
    decision: AcquisitionDecisionStatus
    explanation: str


@dataclass(frozen=True, slots=True)
class SectorSourceAcquisitionDecisionReport:
    sources_inspected: int
    official_sources_found: int
    commercial_sources_found: int
    sources_with_effective_dates: int
    sources_with_archival_snapshots: int
    sources_with_isin: int
    sources_with_stable_taxonomy: int
    sample_records_parsed: int
    identity_match_rate: Decimal | None
    estimated_candidate_date_coverage: HistoricalSectorCoverageStatus
    licensing_status: str
    operational_feasibility: str
    expected_value: CostValueTier
    primary_conclusion: AcquisitionPrimaryConclusion
    secondary_conclusion: AcquisitionPrimaryConclusion | None
    recommended_next_milestone: AcquisitionNextMilestone
    explicitly_prohibited_next_action: str
    matrix: tuple[SectorSourceDecisionMatrixRow, ...]
    source_combination: SourceCombinationFinding
    sector_necessity: SectorNecessityClassification


class HistoricalSectorSourceFeasibilityEngine:
    def __init__(self, *, store_path: Path | str | None = None) -> None:
        self.store_path = resolve_point_in_time_store_path(store_path)

    def source_candidates(self) -> tuple[HistoricalSectorSourceCandidate, ...]:
        return _source_candidates()

    def get_source(self, source_id: str) -> HistoricalSectorSourceCandidate:
        source_id_normalized = source_id.lower()
        for source in self.source_candidates():
            if source.source_id.lower() == source_id_normalized:
                return source
        raise ValueError(f"Unknown historical sector source: {source_id}")

    def sample_source(self, source_id: str) -> SectorSourceSampleReport:
        source = self.get_source(source_id)
        if source.source_id == "local_nse_bhavcopy_archives":
            return _sample_local_bhavcopy_archives()
        return SectorSourceSampleReport(
            source_id=source.source_id,
            sample_attempted=False,
            sample_records_parsed=0,
            fields_observed=(),
            date_fields=(),
            identity_fields=source.security_identity_fields,
            sector_fields=(),
            taxonomy_fields=(),
            archival_consistency="not tested; external sample not acquired",
            schema_stability="not tested",
            duplicate_records=0,
            limitations=(
                "sample acquisition requires source-specific access and terms review",
                "no classifications are persisted during feasibility audit",
            ),
        )

    def identity_test(self, source_id: str) -> SectorSourceIdentityTestReport:
        source = self.get_source(source_id)
        if source.source_id == "local_nse_bhavcopy_archives":
            symbols = _sample_local_bhavcopy_symbols(limit=250)
            return _symbol_identity_test(self.store_path, source.source_id, symbols)
        return SectorSourceIdentityTestReport(
            source_id=source.source_id,
            records_sampled=0,
            exact_identity_matches=0,
            isin_matches=0,
            instrument_id_matches=0,
            symbol_lineage_matches=0,
            ambiguous_matches=0,
            unmatched_records=0,
            reused_symbol_conflicts=0,
            corporate_action_conflicts=0,
            joinability=_expected_joinability(source),
            explanation=(
                "identity joinability is estimated from available fields; no external "
                "sample records were acquired in this diagnostic run"
            ),
        )

    def coverage_estimates(self) -> tuple[SectorSourceCoverageEstimate, ...]:
        dates_total, records_total = _candidate_universe_counts(self.store_path)
        return tuple(
            _coverage_estimate(source, dates_total, records_total)
            for source in self.source_candidates()
        )

    def taxonomy_audit(self) -> tuple[SectorSourceTaxonomyAuditRow, ...]:
        return tuple(_taxonomy_row(source) for source in self.source_candidates())

    def licensing_audit(self) -> tuple[SectorSourceLicensingAuditRow, ...]:
        return tuple(_licensing_row(source) for source in self.source_candidates())

    def source_combinations(self) -> tuple[SectorSourceCombinationAssessment, ...]:
        return (
            SectorSourceCombinationAssessment(
                combination_id="nse-indices-plus-security-master",
                primary_source="nse_indices_industry_classification_subscription",
                supporting_source="nse_securities_available_for_trading",
                identity_source="nse_securities_available_for_trading",
                effective_date_source="nse_indices_industry_classification_subscription",
                taxonomy_mapping_requirement=(
                    "requires explicit taxonomy version and historical mappings"
                ),
                conflict_risk="medium; official source may be subscription-only",
                expected_authority=HistoricalSectorSourceAuthority.OFFICIAL_WITH_LIMITATIONS,
                expected_coverage=HistoricalSectorCoverageStatus.UNKNOWN,
                finding=SourceCombinationFinding.MULTI_SOURCE_RECONSTRUCTION_HIGH_RISK,
                explanation=(
                    "official identity and official classification could be combined "
                    "only after sample files prove dated classification semantics"
                ),
            ),
            SectorSourceCombinationAssessment(
                combination_id="filings-plus-taxonomy-manual-reconstruction",
                primary_source="sebi_company_filings_and_annual_reports",
                supporting_source="nse_industry_classification_structure",
                identity_source="nse_securities_available_for_trading",
                effective_date_source="company annual report dates",
                taxonomy_mapping_requirement=(
                    "manual mapping from business description to NSE taxonomy"
                ),
                conflict_risk="high; this is inference-heavy and not authoritative",
                expected_authority=HistoricalSectorSourceAuthority.SUPPORTED_RECONSTRUCTION_SOURCE,
                expected_coverage=HistoricalSectorCoverageStatus.PARTIAL,
                finding=SourceCombinationFinding.MULTI_SOURCE_RECONSTRUCTION_HIGH_RISK,
                explanation=(
                    "filings can support research reconstruction, but not a clean "
                    "official point-in-time classification dataset by themselves"
                ),
            ),
            SectorSourceCombinationAssessment(
                combination_id="index-constituents-as-sector-proxy",
                primary_source="nse_index_constituent_archives",
                supporting_source="nse_sector_index_history",
                identity_source="symbol only or constituent file names",
                effective_date_source="index rebalance or report date",
                taxonomy_mapping_requirement="not applicable",
                conflict_risk="unacceptable; membership is not classification",
                expected_authority=HistoricalSectorSourceAuthority.INDEX_MEMBERSHIP_ONLY,
                expected_coverage=HistoricalSectorCoverageStatus.NONE,
                finding=SourceCombinationFinding.NO_SAFE_SOURCE_COMBINATION,
                explanation=(
                    "sector index membership must not be substituted for a full "
                    "security sector classification"
                ),
            ),
        )

    def sector_necessity(self) -> SectorNecessitySensitivityReport:
        dates_total, records_total = _candidate_universe_counts(self.store_path)
        sector_available_dates = _v2_sector_available_dates(self.store_path)
        if sector_available_dates == 0:
            return SectorNecessitySensitivityReport(
                candidate_dates_potentially_affected_by_sector=0,
                candidate_records_potentially_affected=0,
                maximum_regime_assignment_changes=0,
                maximum_score_intervention_changes=0,
                classification=SectorNecessityClassification.SECTOR_UNUSED_BY_CURRENT_CLASSIFIER,
                explanation=(
                    f"v2 has {dates_total} candidate dates and {records_total} "
                    "candidate links, but sector availability is zero; current "
                    "sector-aware branches cannot be validated without source data"
                ),
            )
        return SectorNecessitySensitivityReport(
            candidate_dates_potentially_affected_by_sector=sector_available_dates,
            candidate_records_potentially_affected=records_total,
            maximum_regime_assignment_changes=sector_available_dates,
            maximum_score_intervention_changes=sector_available_dates,
            classification=SectorNecessityClassification.SECTOR_POTENTIALLY_MATERIAL,
            explanation="sector state exists for some diagnostic dates",
        )

    def decision_matrix(self) -> tuple[SectorSourceDecisionMatrixRow, ...]:
        return tuple(_matrix_row(source) for source in self.source_candidates())

    def acquisition_decision(self) -> SectorSourceAcquisitionDecisionReport:
        ac = AcquisitionPrimaryConclusion
        sources = self.source_candidates()
        samples = tuple(self.sample_source(source.source_id) for source in sources)
        identity_reports = tuple(
            self.identity_test(source.source_id) for source in sources
        )
        matrix = self.decision_matrix()
        coverage = self.coverage_estimates()
        combinations = self.source_combinations()
        necessity = self.sector_necessity()
        matched = sum(
            row.exact_identity_matches
            + row.isin_matches
            + row.instrument_id_matches
            + row.symbol_lineage_matches
            for row in identity_reports
        )
        sampled = sum(row.records_sampled for row in identity_reports)
        identity_match_rate = (
            None
            if sampled == 0
            else (Decimal(matched) / Decimal(sampled)).quantize(Decimal("0.0001"))
        )
        viable = tuple(
            row
            for row in matrix
            if row.decision
            in {
                AcquisitionDecisionStatus.RECOMMENDED,
                AcquisitionDecisionStatus.CONDITIONALLY_RECOMMENDED,
            }
        )
        if viable:
            primary = AcquisitionPrimaryConclusion.OFFICIAL_SECTOR_SOURCE_IS_AVAILABLE
            next_milestone = AcquisitionNextMilestone.PERFORM_LICENSING_REVIEW
        else:
            primary = ac.INSUFFICIENT_EVIDENCE_FOR_SECTOR_SOURCE_DECISION
            next_milestone = AcquisitionNextMilestone.COLLECT_MORE_SOURCE_EVIDENCE
        if any(
            row.finding
            is SourceCombinationFinding.MULTI_SOURCE_RECONSTRUCTION_HIGH_RISK
            for row in combinations
        ):
            secondary = ac.HISTORICAL_SECTOR_SOURCE_COVERAGE_IS_INSUFFICIENT
        else:
            secondary = None
        return SectorSourceAcquisitionDecisionReport(
            sources_inspected=len(sources),
            official_sources_found=sum(
                row.authority
                in {
                    HistoricalSectorSourceAuthority.OFFICIAL_AUTHORITATIVE,
                    HistoricalSectorSourceAuthority.OFFICIAL_WITH_LIMITATIONS,
                }
                for row in sources
            ),
            commercial_sources_found=sum(
                row.authority is HistoricalSectorSourceAuthority.STRONG_COMMERCIAL
                for row in sources
            ),
            sources_with_effective_dates=sum(
                row.effective_date_support for row in sources
            ),
            sources_with_archival_snapshots=sum(
                row.temporal_suitability is TemporalSuitability.ARCHIVED_SNAPSHOT_DATED
                for row in sources
            ),
            sources_with_isin=sum(row.isin_available for row in sources),
            sources_with_stable_taxonomy=sum(
                row.taxonomy_stability
                in {
                    TaxonomyStability.STABLE_VERSIONED_TAXONOMY,
                    TaxonomyStability.VERSIONED_WITH_MAPPING_AVAILABLE,
                }
                for row in sources
            ),
            sample_records_parsed=sum(row.sample_records_parsed for row in samples),
            identity_match_rate=identity_match_rate,
            estimated_candidate_date_coverage=_best_coverage_status(coverage),
            licensing_status="licensing review required for all promising sources",
            operational_feasibility="no fully automatable authoritative source proven",
            expected_value=CostValueTier.UNKNOWN
            if not viable
            else CostValueTier.MODERATE_VALUE,
            primary_conclusion=primary,
            secondary_conclusion=secondary,
            recommended_next_milestone=next_milestone,
            explicitly_prohibited_next_action=_PROHIBITED_NEXT_ACTION,
            matrix=matrix,
            source_combination=SourceCombinationFinding.MULTI_SOURCE_RECONSTRUCTION_HIGH_RISK,
            sector_necessity=necessity.classification,
        )


def render_sector_source_candidates(
    rows: tuple[HistoricalSectorSourceCandidate, ...],
) -> tuple[str, ...]:
    lines = ["Historical Sector Source Candidates"]
    for row in rows:
        lines.append(
            f"- {row.source_id}: {row.provider}; authority={row.authority.value}; "
            f"temporal={row.temporal_suitability.value}; "
            f"coverage={row.expected_coverage.value}; value={row.expected_value.value}"
        )
    return tuple(lines)


def render_sector_source_show(
    source: HistoricalSectorSourceCandidate,
) -> tuple[str, ...]:
    return (
        f"Historical Sector Source: {source.source_id}",
        f"Provider: {source.provider}",
        f"Source Name: {source.source_name}",
        f"Type: {source.source_type}",
        f"Official Status: {source.official_status}",
        f"Access Method: {source.access_method}",
        f"Format: {source.format}",
        f"Taxonomy: {source.taxonomy_name} ({source.taxonomy_version})",
        f"Coverage: {_text(source.coverage_start)} to {_text(source.coverage_end)}",
        f"Temporal Suitability: {source.temporal_suitability.value}",
        f"Effective Date Support: {'yes' if source.effective_date_support else 'no'}",
        f"Identity Fields: {_text_list(source.security_identity_fields)}",
        f"ISIN Available: {'yes' if source.isin_available else 'no'}",
        f"Symbol Available: {'yes' if source.symbol_available else 'no'}",
        "Archives Available: "
        f"{'yes' if source.historical_archives_available else 'no'}",
        f"Licensing: {source.licensing_status}",
        f"Cost Model: {source.cost_model}",
        f"Operational Status: {source.automation_feasibility.value}",
        f"Authority: {source.authority.value}",
        f"Taxonomy Stability: {source.taxonomy_stability.value}",
        f"Expected Coverage: {source.expected_coverage.value}",
        f"Expected Value: {source.expected_value.value}",
        f"Reference: {source.sample_url_or_reference}",
        f"Limitations: {_text_list(source.limitations)}",
    )


def render_sector_source_sample(report: SectorSourceSampleReport) -> tuple[str, ...]:
    return (
        f"Historical Sector Source Sample: {report.source_id}",
        f"Sample Attempted: {'yes' if report.sample_attempted else 'no'}",
        f"Sample Records Parsed: {report.sample_records_parsed}",
        f"Fields Observed: {_text_list(report.fields_observed)}",
        f"Date Fields: {_text_list(report.date_fields)}",
        f"Identity Fields: {_text_list(report.identity_fields)}",
        f"Sector Fields: {_text_list(report.sector_fields)}",
        f"Taxonomy Fields: {_text_list(report.taxonomy_fields)}",
        f"Archival Consistency: {report.archival_consistency}",
        f"Schema Stability: {report.schema_stability}",
        f"Duplicate Records: {report.duplicate_records}",
        f"Limitations: {_text_list(report.limitations)}",
    )


def render_sector_source_identity(
    report: SectorSourceIdentityTestReport,
) -> tuple[str, ...]:
    return (
        f"Historical Sector Source Identity Test: {report.source_id}",
        f"Records Sampled: {report.records_sampled}",
        f"Exact Identity Matches: {report.exact_identity_matches}",
        f"ISIN Matches: {report.isin_matches}",
        f"Instrument-ID Matches: {report.instrument_id_matches}",
        f"Symbol-Lineage Matches: {report.symbol_lineage_matches}",
        f"Ambiguous Matches: {report.ambiguous_matches}",
        f"Unmatched Records: {report.unmatched_records}",
        f"Reused Symbol Conflicts: {report.reused_symbol_conflicts}",
        f"Corporate-Action Conflicts: {report.corporate_action_conflicts}",
        f"Joinability: {report.joinability.value}",
        f"Explanation: {report.explanation}",
    )


def render_sector_source_coverage(
    rows: tuple[SectorSourceCoverageEstimate, ...],
) -> tuple[str, ...]:
    lines = ["Historical Sector Source Coverage Estimate"]
    for row in rows:
        lines.append(
            f"- {row.source_id}: status={row.coverage_status.value}; "
            f"dates={row.candidate_dates_potentially_covered}/"
            f"{row.candidate_dates_total}; records="
            f"{row.candidate_records_potentially_covered}/"
            f"{row.candidate_records_total}; explanation={row.explanation}"
        )
    return tuple(lines)


def render_sector_source_taxonomy(
    rows: tuple[SectorSourceTaxonomyAuditRow, ...],
) -> tuple[str, ...]:
    lines = ["Historical Sector Source Taxonomy Audit"]
    for row in rows:
        lines.append(
            f"- {row.source_id}: {row.stability.value}; hierarchy="
            f"{_text_list(row.hierarchy)}; mapping={row.mapping_requirement}; "
            f"risk={row.conflict_risk}"
        )
    return tuple(lines)


def render_sector_source_licensing(
    rows: tuple[SectorSourceLicensingAuditRow, ...],
) -> tuple[str, ...]:
    lines = ["Historical Sector Source Licensing Audit"]
    for row in rows:
        lines.append(
            f"- {row.source_id}: {row.free_or_paid}; "
            f"operational={row.operational_status.value}; "
            f"uncertainty={row.uncertainty}"
        )
    return tuple(lines)


def render_sector_source_value(
    report: SectorNecessitySensitivityReport,
) -> tuple[str, ...]:
    return (
        "Historical Sector Source Value Sensitivity",
        "Candidate Dates Potentially Affected: "
        f"{report.candidate_dates_potentially_affected_by_sector}",
        "Candidate Records Potentially Affected: "
        f"{report.candidate_records_potentially_affected}",
        "Maximum Regime Assignment Changes: "
        f"{report.maximum_regime_assignment_changes}",
        "Maximum Score Intervention Changes: "
        f"{report.maximum_score_intervention_changes}",
        f"Classification: {report.classification.value}",
        f"Explanation: {report.explanation}",
    )


def render_sector_source_combinations(
    rows: tuple[SectorSourceCombinationAssessment, ...],
) -> tuple[str, ...]:
    lines = ["Historical Sector Source Combination Feasibility"]
    for row in rows:
        lines.append(
            f"- {row.combination_id}: {row.finding.value}; "
            f"primary={row.primary_source}; supporting={row.supporting_source}; "
            f"risk={row.conflict_risk}; {row.explanation}"
        )
    return tuple(lines)


def render_sector_acquisition_decision(
    report: SectorSourceAcquisitionDecisionReport,
) -> tuple[str, ...]:
    lines = [
        "Historical Sector Acquisition Decision",
        f"Sources Inspected: {report.sources_inspected}",
        f"Official Sources Found: {report.official_sources_found}",
        f"Commercial Sources Found: {report.commercial_sources_found}",
        f"Sources With Effective Dates: {report.sources_with_effective_dates}",
        f"Sources With Archival Snapshots: {report.sources_with_archival_snapshots}",
        f"Sources With ISIN: {report.sources_with_isin}",
        f"Sources With Stable Taxonomy: {report.sources_with_stable_taxonomy}",
        f"Sample Records Parsed: {report.sample_records_parsed}",
        f"Identity Match Rate: {_text(report.identity_match_rate)}",
        "Estimated Candidate-Date Coverage: "
        f"{report.estimated_candidate_date_coverage.value}",
        f"Licensing Status: {report.licensing_status}",
        f"Operational Feasibility: {report.operational_feasibility}",
        f"Expected Value: {report.expected_value.value}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        f"Secondary Conclusion: {_enum_text(report.secondary_conclusion)}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        f"Source Combination: {report.source_combination.value}",
        f"Sector Necessity: {report.sector_necessity.value}",
        "Explicitly Prohibited Next Action: "
        f"{report.explicitly_prohibited_next_action}",
        "Decision Matrix:",
    ]
    for row in report.matrix:
        lines.append(
            f"- {row.source_id}: decision={row.decision.value}; "
            f"authority={row.authority}; effective_dating={row.effective_dating}; "
            f"identity={row.identity_joinability}; coverage={row.historical_coverage}; "
            f"value={row.expected_analytical_value}; {row.explanation}"
        )
    return tuple(lines)


def export_sector_source_json(payload: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")
    return path


def export_sector_source_csv(rows: tuple[Any, ...], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    dictionaries = [_jsonable(row) for row in rows] or [{"status": "unavailable"}]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(dictionaries[0].keys()))
        writer.writeheader()
        writer.writerows(dictionaries)
    return path


def _source_candidates() -> tuple[HistoricalSectorSourceCandidate, ...]:
    return (
        HistoricalSectorSourceCandidate(
            source_id="nse_industry_classification_structure",
            provider="NSE Indices Limited",
            source_name=(
                "NSE Indices industry classification methodology/current structure"
            ),
            source_type="industry_classification_methodology",
            official_status="official NSE Indices public methodology",
            access_method=(
                "public web page and linked PDF; no historical company file proven"
            ),
            format="HTML/PDF",
            taxonomy_name="NSE Indices Industry Classification",
            taxonomy_version="current-public-structure",
            coverage_start=None,
            coverage_end=None,
            effective_date_support=False,
            temporal_suitability=TemporalSuitability.CURRENT_ONLY,
            security_identity_fields=(),
            isin_available=False,
            symbol_available=False,
            historical_archives_available=False,
            update_frequency="reviewed annually by methodology statement",
            licensing_status="public reference; data reuse terms require review",
            cost_model="free reference page",
            automation_feasibility=OperationalStatus.LICENSING_REVIEW_REQUIRED,
            source_stability="official taxonomy, but public page is current-state",
            authority=HistoricalSectorSourceAuthority.OFFICIAL_WITH_LIMITATIONS,
            limitations=(
                "describes taxonomy and methodology but not historical "
                "company assignments",
                "cannot classify securities without separate dated assignment files",
            ),
            sample_url_or_reference=(
                "https://www.nseindia.com/static/products-services/industry-classification"
            ),
            taxonomy_stability=TaxonomyStability.CURRENT_TAXONOMY_ONLY,
            expected_coverage=HistoricalSectorCoverageStatus.NONE,
            expected_value=CostValueTier.LOW_VALUE,
        ),
        HistoricalSectorSourceCandidate(
            source_id="nse_indices_industry_classification_subscription",
            provider="NSE Indices Limited",
            source_name="NSE Indices company industry classification data request",
            source_type="official_industry_classification_dataset",
            official_status="official source candidate; access not confirmed",
            access_method="contact NSE Indices / subscription or data request",
            format="unknown; likely CSV/XLS/PDF depending access",
            taxonomy_name="NSE Indices Industry Classification",
            taxonomy_version="unknown historical versions",
            coverage_start=None,
            coverage_end=None,
            effective_date_support=True,
            temporal_suitability=TemporalSuitability.TEMPORAL_STATUS_UNKNOWN,
            security_identity_fields=("symbol", "company_name", "isin if supplied"),
            isin_available=False,
            symbol_available=True,
            historical_archives_available=False,
            update_frequency="unknown",
            licensing_status="requires licensing and access review",
            cost_model="unknown; may require commercial subscription",
            automation_feasibility=OperationalStatus.LICENSING_REVIEW_REQUIRED,
            source_stability="potentially official, but sample unavailable",
            authority=HistoricalSectorSourceAuthority.OFFICIAL_WITH_LIMITATIONS,
            limitations=(
                "no acquired sample proving effective dates",
                "no confirmed bulk historical archive",
                "taxonomy mapping across years not yet reviewed",
            ),
            sample_url_or_reference="indices@nse.co.in",
            taxonomy_stability=TaxonomyStability.VERSIONED_WITHOUT_MAPPING,
            expected_coverage=HistoricalSectorCoverageStatus.UNKNOWN,
            expected_value=CostValueTier.UNKNOWN,
        ),
        HistoricalSectorSourceCandidate(
            source_id="nse_securities_available_for_trading",
            provider="NSE India",
            source_name="Securities available for trading",
            source_type="official_security_master",
            official_status="official current security master",
            access_method="public NSE market-data download page",
            format="CSV/XLSX",
            taxonomy_name="not a sector taxonomy",
            taxonomy_version="not applicable",
            coverage_start=None,
            coverage_end=None,
            effective_date_support=False,
            temporal_suitability=TemporalSuitability.CURRENT_ONLY,
            security_identity_fields=("symbol", "series", "isin", "company_name"),
            isin_available=True,
            symbol_available=True,
            historical_archives_available=False,
            update_frequency="current/downloadable",
            licensing_status="public download; reuse terms require review",
            cost_model="free public file",
            automation_feasibility=OperationalStatus.AUTOMATABLE_WITH_LIMITATIONS,
            source_stability="official identity reference, current-state only",
            authority=HistoricalSectorSourceAuthority.CURRENT_STATE_ONLY,
            limitations=(
                "supports identity joins but not sector classification",
                "current-state file must not be used backward as history",
            ),
            sample_url_or_reference=(
                "https://www.nseindia.com/static/market-data/securities-available-for-trading"
            ),
            taxonomy_stability=TaxonomyStability.CURRENT_TAXONOMY_ONLY,
            expected_coverage=HistoricalSectorCoverageStatus.NONE,
            expected_value=CostValueTier.MODERATE_VALUE,
        ),
        HistoricalSectorSourceCandidate(
            source_id="nse_index_constituent_archives",
            provider="NSE/NSE Indices",
            source_name="Index inclusion/exclusion and constituent archives",
            source_type="index_membership_archive",
            official_status="official or archived index membership evidence",
            access_method="NSE/Nifty Indices reports and historical archives",
            format="XLS/PDF/CSV depending report",
            taxonomy_name="index membership",
            taxonomy_version="not a sector classification taxonomy",
            coverage_start=None,
            coverage_end=None,
            effective_date_support=True,
            temporal_suitability=TemporalSuitability.CHANGE_EVENT_DATED,
            security_identity_fields=("symbol", "company_name"),
            isin_available=False,
            symbol_available=True,
            historical_archives_available=True,
            update_frequency="index rebalance/report cadence",
            licensing_status="source terms require review",
            cost_model="free/public archives where available",
            automation_feasibility=OperationalStatus.MANUAL_ARCHIVE_REQUIRED,
            source_stability="membership archive, not full classification archive",
            authority=HistoricalSectorSourceAuthority.INDEX_MEMBERSHIP_ONLY,
            limitations=(
                "index membership is not sector classification",
                "covers only index constituents, not the full NSE universe",
            ),
            sample_url_or_reference="https://www.nseindia.com/reports-indices-historical-index-data",
            taxonomy_stability=TaxonomyStability.UNVERSIONED_TAXONOMY,
            expected_coverage=HistoricalSectorCoverageStatus.LOW,
            expected_value=CostValueTier.UNJUSTIFIED,
        ),
        HistoricalSectorSourceCandidate(
            source_id="nse_sector_index_history",
            provider="NSE/Nifty Indices",
            source_name="Historical sector index data",
            source_type="sector_index_time_series",
            official_status="official index level data",
            access_method="NSE/Nifty Indices historical index data reports",
            format="CSV via web report",
            taxonomy_name="sector index family",
            taxonomy_version="index methodology dependent",
            coverage_start=None,
            coverage_end=None,
            effective_date_support=False,
            temporal_suitability=TemporalSuitability.PUBLICATION_DATE_ONLY,
            security_identity_fields=("index_name",),
            isin_available=False,
            symbol_available=False,
            historical_archives_available=True,
            update_frequency="daily index data",
            licensing_status="public report; reuse terms require review",
            cost_model="free public report",
            automation_feasibility=OperationalStatus.AUTOMATABLE_WITH_LIMITATIONS,
            source_stability="index time series stable, constituents not included",
            authority=HistoricalSectorSourceAuthority.INDEX_MEMBERSHIP_ONLY,
            limitations=(
                "provides index prices, not security-level sector assignment",
                "cannot classify non-index securities",
            ),
            sample_url_or_reference="https://niftyindices.com/reports/historical-data",
            taxonomy_stability=TaxonomyStability.UNVERSIONED_TAXONOMY,
            expected_coverage=HistoricalSectorCoverageStatus.NONE,
            expected_value=CostValueTier.UNJUSTIFIED,
        ),
        HistoricalSectorSourceCandidate(
            source_id="bse_security_master_industry",
            provider="BSE India",
            source_name="BSE security master / industry classification candidate",
            source_type="official_cross_exchange_security_master",
            official_status="official BSE source candidate",
            access_method="BSE public downloads or data services",
            format="CSV/XLS/API unknown",
            taxonomy_name="BSE industry classification",
            taxonomy_version="unknown",
            coverage_start=None,
            coverage_end=None,
            effective_date_support=False,
            temporal_suitability=TemporalSuitability.CURRENT_ONLY,
            security_identity_fields=("scrip_code", "isin", "company_name"),
            isin_available=True,
            symbol_available=False,
            historical_archives_available=False,
            update_frequency="unknown",
            licensing_status="requires source-specific review",
            cost_model="unknown",
            automation_feasibility=OperationalStatus.LICENSING_REVIEW_REQUIRED,
            source_stability="cross-exchange identity may help, taxonomy differs",
            authority=HistoricalSectorSourceAuthority.OFFICIAL_WITH_LIMITATIONS,
            limitations=(
                "not NSE-native",
                "taxonomy mapping to NSE Indices classification would be required",
                "historical effective dates not proven",
            ),
            sample_url_or_reference="BSE public/security master data services",
            taxonomy_stability=TaxonomyStability.UNVERSIONED_TAXONOMY,
            expected_coverage=HistoricalSectorCoverageStatus.UNKNOWN,
            expected_value=CostValueTier.UNKNOWN,
        ),
        HistoricalSectorSourceCandidate(
            source_id="sebi_company_filings_and_annual_reports",
            provider="SEBI/exchanges/company filings",
            source_name="Company filings, annual reports, RHP and segment disclosures",
            source_type="official_filing_reconstruction_source",
            official_status="official filings, not classification dataset",
            access_method="exchange/SEBI filing archives and annual reports",
            format="HTML/PDF/XBRL",
            taxonomy_name="business description / segment reporting",
            taxonomy_version="company-specific disclosures",
            coverage_start=None,
            coverage_end=None,
            effective_date_support=True,
            temporal_suitability=TemporalSuitability.PUBLICATION_DATE_ONLY,
            security_identity_fields=("symbol", "isin", "company_name"),
            isin_available=True,
            symbol_available=True,
            historical_archives_available=True,
            update_frequency="filing cadence",
            licensing_status="public filings; extraction/storage terms require review",
            cost_model="free but high labor/compute",
            automation_feasibility=OperationalStatus.MANUAL_ARCHIVE_REQUIRED,
            source_stability=(
                "source documents stable, classification inference unstable"
            ),
            authority=HistoricalSectorSourceAuthority.SUPPORTED_RECONSTRUCTION_SOURCE,
            limitations=(
                "not direct sector labels",
                "requires human or model-assisted mapping to taxonomy",
                "publication date is not automatically classification effective date",
            ),
            sample_url_or_reference=(
                "NSE/BSE/SEBI filing archives and company annual reports"
            ),
            taxonomy_stability=TaxonomyStability.VERSIONED_WITHOUT_MAPPING,
            expected_coverage=HistoricalSectorCoverageStatus.PARTIAL,
            expected_value=CostValueTier.LOW_VALUE,
        ),
        HistoricalSectorSourceCandidate(
            source_id="commercial_historical_security_master_vendor",
            provider="licensed market-data vendor",
            source_name="Commercial historical security master with sector history",
            source_type="commercial_security_master",
            official_status="not official; potentially strong licensed data",
            access_method="vendor contract and sample file",
            format="API/CSV/database export",
            taxonomy_name="vendor taxonomy or GICS/ICB/provider taxonomy",
            taxonomy_version="vendor-managed",
            coverage_start=None,
            coverage_end=None,
            effective_date_support=True,
            temporal_suitability=TemporalSuitability.TEMPORAL_STATUS_UNKNOWN,
            security_identity_fields=("provider_id", "isin", "symbol", "exchange"),
            isin_available=True,
            symbol_available=True,
            historical_archives_available=True,
            update_frequency="vendor dependent",
            licensing_status="paid license required",
            cost_model="paid vendor",
            automation_feasibility=OperationalStatus.PAID_VENDOR_REQUIRED,
            source_stability="unknown until sample and contract are reviewed",
            authority=HistoricalSectorSourceAuthority.STRONG_COMMERCIAL,
            limitations=(
                "not official NSE classification unless vendor sources it",
                "taxonomy mapping may be required",
                "cost and redistribution restrictions unknown",
            ),
            sample_url_or_reference="vendor sample request required",
            taxonomy_stability=TaxonomyStability.VERSIONED_WITHOUT_MAPPING,
            expected_coverage=HistoricalSectorCoverageStatus.UNKNOWN,
            expected_value=CostValueTier.UNKNOWN,
        ),
        HistoricalSectorSourceCandidate(
            source_id="local_nse_bhavcopy_archives",
            provider="NSE archive files already downloaded by Alpha",
            source_name="Local NSE bhavcopy archives",
            source_type="exchange_price_archive",
            official_status="official price archive copy, not classification source",
            access_method="local data/extracted CSV files",
            format="CSV",
            taxonomy_name="none",
            taxonomy_version="none",
            coverage_start=None,
            coverage_end=None,
            effective_date_support=False,
            temporal_suitability=TemporalSuitability.ARCHIVED_SNAPSHOT_DATED,
            security_identity_fields=("symbol", "series"),
            isin_available=False,
            symbol_available=True,
            historical_archives_available=True,
            update_frequency="daily trading archive",
            licensing_status="local operational archive; source terms still apply",
            cost_model="already stored locally",
            automation_feasibility=OperationalStatus.AUTOMATABLE,
            source_stability="stable price schema across observed files",
            authority=HistoricalSectorSourceAuthority.UNUSABLE,
            limitations=(
                "contains price/volume data, not sector classifications",
                "must not be used as sector evidence",
            ),
            sample_url_or_reference="data/extracted/*.csv",
            taxonomy_stability=TaxonomyStability.UNVERSIONED_TAXONOMY,
            expected_coverage=HistoricalSectorCoverageStatus.NONE,
            expected_value=CostValueTier.UNJUSTIFIED,
        ),
    )


def _sample_local_bhavcopy_archives() -> SectorSourceSampleReport:
    files = sorted(Path("data/extracted").glob("*.csv"))
    if not files:
        return SectorSourceSampleReport(
            source_id="local_nse_bhavcopy_archives",
            sample_attempted=True,
            sample_records_parsed=0,
            fields_observed=(),
            date_fields=(),
            identity_fields=(),
            sector_fields=(),
            taxonomy_fields=(),
            archival_consistency="no local files found",
            schema_stability="unavailable",
            duplicate_records=0,
            limitations=("no local bhavcopy sample files available",),
        )
    records = []
    headers: tuple[str, ...] = ()
    with files[0].open(newline="", encoding="utf-8", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        headers = tuple(reader.fieldnames or ())
        for row in reader:
            records.append(row)
            if len(records) >= 25:
                break
    duplicate_keys = len(records) - len(
        {
            (
                row.get("SYMBOL") or row.get("TckrSymb") or "",
                row.get("SERIES") or "",
            )
            for row in records
        }
    )
    identity_fields = tuple(
        field
        for field in headers
        if field.upper() in {"SYMBOL", "TCKRSYMB", "SERIES", "SCTYSRS"}
    )
    date_fields = tuple(
        field for field in headers if "DATE" in field.upper() or "DT" == field.upper()
    )
    return SectorSourceSampleReport(
        source_id="local_nse_bhavcopy_archives",
        sample_attempted=True,
        sample_records_parsed=len(records),
        fields_observed=headers,
        date_fields=date_fields,
        identity_fields=identity_fields,
        sector_fields=(),
        taxonomy_fields=(),
        archival_consistency="dated archive file parsed locally",
        schema_stability="single sample parsed; multi-file schema audit not performed",
        duplicate_records=max(duplicate_keys, 0),
        limitations=(
            "sample confirms price archive structure only",
            "no sector or industry classification fields observed",
        ),
    )


def _sample_local_bhavcopy_symbols(*, limit: int) -> tuple[str, ...]:
    files = sorted(Path("data/extracted").glob("*.csv"))
    symbols: list[str] = []
    for file in files[:10]:
        with file.open(newline="", encoding="utf-8", errors="ignore") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                symbol = row.get("SYMBOL") or row.get("TckrSymb") or row.get("SYMB")
                if symbol:
                    symbols.append(symbol.upper())
                if len(symbols) >= limit:
                    return tuple(symbols)
    return tuple(symbols)


def _symbol_identity_test(
    store_path: Path,
    source_id: str,
    symbols: tuple[str, ...],
) -> SectorSourceIdentityTestReport:
    if not store_path.exists() or not symbols:
        return SectorSourceIdentityTestReport(
            source_id=source_id,
            records_sampled=len(symbols),
            exact_identity_matches=0,
            isin_matches=0,
            instrument_id_matches=0,
            symbol_lineage_matches=0,
            ambiguous_matches=0,
            unmatched_records=len(symbols),
            reused_symbol_conflicts=0,
            corporate_action_conflicts=0,
            joinability=IdentityJoinability.UNUSABLE,
            explanation="no store or symbols available for identity test",
        )
    unique_symbols = tuple(dict.fromkeys(symbols))
    with duckdb.connect(str(store_path), read_only=True) as con:
        rows = con.execute(
            """
            SELECT symbol, COUNT(DISTINCT security_id)
            FROM diagnostic_pit_security_master
            WHERE symbol IN (
                SELECT UNNEST(?)
            )
            GROUP BY symbol
            """,
            (list(unique_symbols),),
        ).fetchall()
    counts = {str(row[0]).upper(): int(row[1]) for row in rows}
    matched = sum(1 for symbol in unique_symbols if counts.get(symbol) == 1)
    ambiguous = sum(1 for symbol in unique_symbols if counts.get(symbol, 0) > 1)
    unmatched = len(unique_symbols) - matched - ambiguous
    joinability = (
        IdentityJoinability.MODERATE_CONFIDENCE
        if matched and ambiguous == 0
        else IdentityJoinability.LOW_CONFIDENCE
        if matched
        else IdentityJoinability.UNUSABLE
    )
    return SectorSourceIdentityTestReport(
        source_id=source_id,
        records_sampled=len(unique_symbols),
        exact_identity_matches=0,
        isin_matches=0,
        instrument_id_matches=0,
        symbol_lineage_matches=matched,
        ambiguous_matches=ambiguous,
        unmatched_records=unmatched,
        reused_symbol_conflicts=ambiguous,
        corporate_action_conflicts=0,
        joinability=joinability,
        explanation=(
            "local bhavcopy identity uses symbol-only matching; this can support "
            "price linkage but not authoritative sector classification"
        ),
    )


def _candidate_universe_counts(store_path: Path) -> tuple[int, int]:
    if not store_path.exists():
        return 0, 0
    try:
        with duckdb.connect(str(store_path), read_only=True) as con:
            row = con.execute(
                """
                SELECT COUNT(DISTINCT CAST(candidate_decision_timestamp AS DATE)),
                       COUNT(*)
                FROM diagnostic_market_state_v2_candidate_links
                """
            ).fetchone()
    except duckdb.Error:
        return 0, 0
    if not row:
        return 0, 0
    return int(row[0] or 0), int(row[1] or 0)


def _v2_sector_available_dates(store_path: Path) -> int:
    if not store_path.exists():
        return 0
    try:
        with duckdb.connect(str(store_path), read_only=True) as con:
            row = con.execute(
                """
                SELECT COUNT(*)
                FROM diagnostic_market_state_v2_reconstructions
                WHERE sector_availability = 'POINT_IN_TIME_SECTOR_STATE'
                """
            ).fetchone()
    except duckdb.Error:
        return 0
    return 0 if not row else int(row[0] or 0)


def _coverage_estimate(
    source: HistoricalSectorSourceCandidate,
    dates_total: int,
    records_total: int,
) -> SectorSourceCoverageEstimate:
    if source.expected_coverage in {
        HistoricalSectorCoverageStatus.NONE,
        HistoricalSectorCoverageStatus.UNKNOWN,
    }:
        covered_dates = 0
        covered_records = 0
    elif source.expected_coverage is HistoricalSectorCoverageStatus.LOW:
        covered_dates = max(1, dates_total // 10) if dates_total else 0
        covered_records = max(1, records_total // 10) if records_total else 0
    elif source.expected_coverage is HistoricalSectorCoverageStatus.PARTIAL:
        covered_dates = dates_total // 2
        covered_records = records_total // 2
    elif source.expected_coverage is HistoricalSectorCoverageStatus.HIGH:
        covered_dates = (dates_total * 8) // 10
        covered_records = (records_total * 8) // 10
    else:
        covered_dates = dates_total
        covered_records = records_total
    return SectorSourceCoverageEstimate(
        source_id=source.source_id,
        candidate_dates_total=dates_total,
        candidate_records_total=records_total,
        candidate_dates_potentially_covered=covered_dates,
        candidate_records_potentially_covered=covered_records,
        security_identities_potentially_covered=covered_records,
        earliest_usable_date=source.coverage_start,
        latest_usable_date=source.coverage_end,
        gaps=tuple(source.limitations[:3]),
        taxonomy_changes=("taxonomy mapping not proven",)
        if source.taxonomy_stability
        in {
            TaxonomyStability.VERSIONED_WITHOUT_MAPPING,
            TaxonomyStability.UNVERSIONED_TAXONOMY,
            TaxonomyStability.CURRENT_TAXONOMY_ONLY,
        }
        else (),
        identity_gaps=("ISIN unavailable",) if not source.isin_available else (),
        effective_date_gaps=("effective dating not proven",)
        if source.temporal_suitability
        not in {
            TemporalSuitability.TRUE_EFFECTIVE_DATED,
            TemporalSuitability.ARCHIVED_SNAPSHOT_DATED,
            TemporalSuitability.CHANGE_EVENT_DATED,
        }
        else (),
        coverage_status=source.expected_coverage,
        explanation=(
            "estimated from source metadata only; no classifications ingested"
        ),
    )


def _taxonomy_row(
    source: HistoricalSectorSourceCandidate,
) -> SectorSourceTaxonomyAuditRow:
    hierarchy = (
        ("macro-economic sector", "sector", "industry", "basic industry")
        if "NSE Indices" in source.taxonomy_name
        else ("unavailable",)
        if source.taxonomy_name in {"none", "not a sector taxonomy"}
        else ("provider-specific",)
    )
    return SectorSourceTaxonomyAuditRow(
        source_id=source.source_id,
        taxonomy_name=source.taxonomy_name,
        taxonomy_version=source.taxonomy_version,
        hierarchy=hierarchy,
        stability=source.taxonomy_stability,
        changes=()
        if source.taxonomy_stability is TaxonomyStability.STABLE_VERSIONED_TAXONOMY
        else ("historical taxonomy changes not mapped",),
        mapping_requirement="none"
        if source.taxonomy_stability is TaxonomyStability.STABLE_VERSIONED_TAXONOMY
        else "explicit mapping required before combining years",
        conflict_risk="low"
        if source.taxonomy_stability is TaxonomyStability.STABLE_VERSIONED_TAXONOMY
        else "medium/high",
    )


def _licensing_row(
    source: HistoricalSectorSourceCandidate,
) -> SectorSourceLicensingAuditRow:
    paid = "paid" if "paid" in source.cost_model.lower() else "free/unknown"
    return SectorSourceLicensingAuditRow(
        source_id=source.source_id,
        free_or_paid=paid,
        registration_required=source.automation_feasibility
        in {
            OperationalStatus.PAID_VENDOR_REQUIRED,
            OperationalStatus.LICENSING_REVIEW_REQUIRED,
        },
        api_available=source.automation_feasibility
        in {
            OperationalStatus.AUTOMATABLE,
            OperationalStatus.AUTOMATABLE_WITH_LIMITATIONS,
        },
        bulk_download_available=source.historical_archives_available,
        manual_download_only=source.automation_feasibility
        is OperationalStatus.MANUAL_ARCHIVE_REQUIRED,
        redistribution_restrictions="unknown; source terms must be reviewed",
        storage_restrictions="unknown; source terms must be reviewed",
        rate_limits="unknown",
        commercial_use_restrictions="unknown; not legal advice",
        automation_restrictions="unknown"
        if "unknown" in source.licensing_status
        else source.licensing_status,
        expected_maintenance_burden="high"
        if source.automation_feasibility
        in {
            OperationalStatus.MANUAL_ARCHIVE_REQUIRED,
            OperationalStatus.LICENSING_REVIEW_REQUIRED,
        }
        else "medium",
        operational_status=source.automation_feasibility,
        uncertainty=source.licensing_status,
    )


def _matrix_row(
    source: HistoricalSectorSourceCandidate,
) -> SectorSourceDecisionMatrixRow:
    joinability = _expected_joinability(source)
    if source.authority is HistoricalSectorSourceAuthority.UNUSABLE:
        decision = AcquisitionDecisionStatus.REJECTED
        explanation = "not a sector classification source"
    elif source.authority is HistoricalSectorSourceAuthority.INDEX_MEMBERSHIP_ONLY:
        decision = AcquisitionDecisionStatus.REJECTED
        explanation = "index membership is not sector classification"
    elif source.authority is HistoricalSectorSourceAuthority.STRONG_COMMERCIAL:
        decision = AcquisitionDecisionStatus.RESEARCH_ONLY
        explanation = "request sample and terms before considering vendor integration"
    elif (
        source.authority is HistoricalSectorSourceAuthority.OFFICIAL_WITH_LIMITATIONS
        and source.temporal_suitability is TemporalSuitability.TEMPORAL_STATUS_UNKNOWN
    ):
        decision = AcquisitionDecisionStatus.INSUFFICIENT_EVIDENCE
        explanation = (
            "official candidate exists but sample/effective dating is unproven"
        )
    else:
        decision = AcquisitionDecisionStatus.RESEARCH_ONLY
        explanation = "use only as supporting evidence until dated assignments exist"
    return SectorSourceDecisionMatrixRow(
        source_id=source.source_id,
        authority=source.authority.value,
        effective_dating=source.temporal_suitability.value,
        identity_joinability=joinability.value,
        historical_coverage=source.expected_coverage.value,
        taxonomy_quality=source.taxonomy_stability.value,
        operational_feasibility=source.automation_feasibility.value,
        licensing_clarity=source.licensing_status,
        cost=source.cost_model,
        expected_analytical_value=source.expected_value.value,
        decision=decision,
        explanation=explanation,
    )


def _expected_joinability(
    source: HistoricalSectorSourceCandidate,
) -> IdentityJoinability:
    if "provider_id" in source.security_identity_fields or source.isin_available:
        return IdentityJoinability.HIGH_CONFIDENCE
    if source.symbol_available and source.security_identity_fields:
        return IdentityJoinability.MODERATE_CONFIDENCE
    if source.symbol_available:
        return IdentityJoinability.LOW_CONFIDENCE
    return IdentityJoinability.UNUSABLE


def _best_coverage_status(
    rows: tuple[SectorSourceCoverageEstimate, ...],
) -> HistoricalSectorCoverageStatus:
    order = {
        HistoricalSectorCoverageStatus.NONE: 0,
        HistoricalSectorCoverageStatus.UNKNOWN: 1,
        HistoricalSectorCoverageStatus.LOW: 2,
        HistoricalSectorCoverageStatus.PARTIAL: 3,
        HistoricalSectorCoverageStatus.HIGH: 4,
        HistoricalSectorCoverageStatus.FULL: 5,
    }
    if not rows:
        return HistoricalSectorCoverageStatus.UNKNOWN
    return max((row.coverage_status for row in rows), key=lambda item: order[item])


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _text(value: object) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, Decimal):
        return f"{value:.4f}"
    return str(value)


def _text_list(values: tuple[object, ...]) -> str:
    return ", ".join(str(value) for value in values) if values else "unavailable"


def _enum_text(value: StrEnum | None) -> str:
    return "none" if value is None else value.value


__all__ = [
    "AcquisitionDecisionStatus",
    "AcquisitionNextMilestone",
    "AcquisitionPrimaryConclusion",
    "CostValueTier",
    "HistoricalSectorCoverageStatus",
    "HistoricalSectorSourceAuthority",
    "HistoricalSectorSourceCandidate",
    "HistoricalSectorSourceFeasibilityEngine",
    "IdentityJoinability",
    "OperationalStatus",
    "SectorNecessityClassification",
    "SectorNecessitySensitivityReport",
    "SectorSourceAcquisitionDecisionReport",
    "SectorSourceCombinationAssessment",
    "SectorSourceCoverageEstimate",
    "SectorSourceDecisionMatrixRow",
    "SectorSourceIdentityTestReport",
    "SectorSourceLicensingAuditRow",
    "SectorSourceSampleReport",
    "SectorSourceTaxonomyAuditRow",
    "SourceCombinationFinding",
    "TaxonomyStability",
    "TemporalSuitability",
    "export_sector_source_csv",
    "export_sector_source_json",
    "render_sector_acquisition_decision",
    "render_sector_source_candidates",
    "render_sector_source_combinations",
    "render_sector_source_coverage",
    "render_sector_source_identity",
    "render_sector_source_licensing",
    "render_sector_source_sample",
    "render_sector_source_show",
    "render_sector_source_taxonomy",
    "render_sector_source_value",
]
