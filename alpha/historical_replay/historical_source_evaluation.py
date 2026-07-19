from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

from alpha.historical_replay.breakout_source_gap import BreakoutGapCause

HISTORICAL_SOURCE_MANIFEST_VERSION = "breakout_external_source_evaluation_manifest_v1"
HISTORICAL_SOURCE_SAMPLE_VERSION = "historical-source-stratified-sample-v1"
HISTORICAL_SOURCE_EVALUATION_VERSION = "historical-source-evaluation-v1"
PRODUCTION_INFLUENCE = False

_FOUR = Decimal("0.0001")
_HUNDRED = Decimal("100")
_ZERO = Decimal("0")


class HistoricalRequirementPriority(StrEnum):
    MANDATORY = "MANDATORY"
    STRONGLY_PREFERRED = "STRONGLY_PREFERRED"
    OPTIONAL = "OPTIONAL"
    NOT_REQUIRED = "NOT_REQUIRED"


class HistoricalEvidenceLevel(StrEnum):
    DOCUMENTED = "DOCUMENTED"
    OBSERVED_IN_SAMPLE = "OBSERVED_IN_SAMPLE"
    FULL_POPULATION_VERIFIED = "FULL_POPULATION_VERIFIED"
    UNKNOWN = "UNKNOWN"


class HistoricalCapabilityStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class HistoricalSourceClass(StrEnum):
    EXCHANGE_PUBLIC_ARCHIVE = "EXCHANGE_PUBLIC_ARCHIVE"
    EXCHANGE_LICENSED_DATA = "EXCHANGE_LICENSED_DATA"
    BROKER_API = "BROKER_API"
    AUTHORIZED_MARKET_DATA_VENDOR = "AUTHORIZED_MARKET_DATA_VENDOR"
    SPECIALIST_INSTITUTIONAL_VENDOR = "SPECIALIST_INSTITUTIONAL_VENDOR"


class HistoricalLicenseStatus(StrEnum):
    CLEARLY_PERMITTED = "CLEARLY_PERMITTED"
    PERMITTED_WITH_CONDITIONS = "PERMITTED_WITH_CONDITIONS"
    REQUIRES_COMMERCIAL_LICENSE = "REQUIRES_COMMERCIAL_LICENSE"
    PERSONAL_RESEARCH_ONLY = "PERSONAL_RESEARCH_ONLY"
    RESTRICTIONS_UNCLEAR = "RESTRICTIONS_UNCLEAR"
    APPARENTLY_PROHIBITED = "APPARENTLY_PROHIBITED"
    TERMS_NOT_FOUND = "TERMS_NOT_FOUND"


class HistoricalPermissionStatus(StrEnum):
    PERMITTED = "PERMITTED"
    PERMITTED_WITH_CONDITIONS = "PERMITTED_WITH_CONDITIONS"
    PROHIBITED = "PROHIBITED"
    REQUIRES_WRITTEN_PERMISSION = "REQUIRES_WRITTEN_PERMISSION"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class HistoricalCredentialStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    CONFIGURED = "CONFIGURED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    SUBSCRIPTION_REQUIRED = "SUBSCRIPTION_REQUIRED"


class HistoricalEvaluationStatus(StrEnum):
    DOCUMENTED_ONLY = "DOCUMENTED_ONLY"
    OBSERVED_SAMPLE_COMPLETE = "OBSERVED_SAMPLE_COMPLETE"
    OBSERVED_SAMPLE_PARTIAL = "OBSERVED_SAMPLE_PARTIAL"
    FULL_POPULATION_VERIFIED = "FULL_POPULATION_VERIFIED"
    NOT_EVALUATED_CREDENTIALS_REQUIRED = "NOT_EVALUATED_CREDENTIALS_REQUIRED"
    NOT_EVALUATED_TERMS_RESTRICT_CACHING = "NOT_EVALUATED_TERMS_RESTRICT_CACHING"
    DRY_RUN_DOCUMENTED_ONLY = "DRY_RUN_DOCUMENTED_ONLY"


class HistoricalSourceRecommendationStatus(StrEnum):
    PRIMARY_SOURCE_CANDIDATE = "PRIMARY_SOURCE_CANDIDATE"
    SECONDARY_VALIDATION_SOURCE = "SECONDARY_VALIDATION_SOURCE"
    CORPORATE_ACTION_SOURCE_ONLY = "CORPORATE_ACTION_SOURCE_ONLY"
    IDENTITY_SOURCE_ONLY = "IDENTITY_SOURCE_ONLY"
    PRICE_SOURCE_ONLY = "PRICE_SOURCE_ONLY"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    UNSUITABLE = "UNSUITABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class HistoricalArchitectureConclusion(StrEnum):
    SINGLE_AUTHORITATIVE_SOURCE_IDENTIFIED = "SINGLE_AUTHORITATIVE_SOURCE_IDENTIFIED"
    MULTI_SOURCE_ARCHITECTURE_REQUIRED = "MULTI_SOURCE_ARCHITECTURE_REQUIRED"
    EXCHANGE_ARCHIVE_SHOULD_BE_PRIMARY = "EXCHANGE_ARCHIVE_SHOULD_BE_PRIMARY"
    BROKER_API_SUITABLE_AS_SECONDARY = "BROKER_API_SUITABLE_AS_SECONDARY"
    COMMERCIAL_VENDOR_REQUIRED = "COMMERCIAL_VENDOR_REQUIRED"


class HistoricalNextStepConclusion(StrEnum):
    LICENSING_BLOCKS_INTEGRATION = "LICENSING_BLOCKS_INTEGRATION"
    COVERAGE_REMAINS_INSUFFICIENT = "COVERAGE_REMAINS_INSUFFICIENT"
    EVALUATION_BLOCKED_BY_CREDENTIALS = "EVALUATION_BLOCKED_BY_CREDENTIALS"
    SOURCE_EVIDENCE_INSUFFICIENT = "SOURCE_EVIDENCE_INSUFFICIENT"
    COVERAGE_PROOF_COMPLETE = "COVERAGE_PROOF_COMPLETE"


@dataclass(frozen=True, slots=True)
class HistoricalSourceRequirement:
    key: str
    label: str
    priority: HistoricalRequirementPriority
    rationale: str
    existing_dependency: str


@dataclass(frozen=True, slots=True)
class HistoricalSourceDocument:
    title: str
    url: str
    evidence_level: HistoricalEvidenceLevel = HistoricalEvidenceLevel.DOCUMENTED


@dataclass(frozen=True, slots=True)
class HistoricalSourceCapability:
    requirement_key: str
    status: HistoricalCapabilityStatus
    evidence_level: HistoricalEvidenceLevel
    explanation: str
    source_url: str | None


@dataclass(frozen=True, slots=True)
class HistoricalSourceLicenseAssessment:
    status: HistoricalLicenseStatus
    terms_url: str | None
    automated_download: HistoricalPermissionStatus
    local_storage: HistoricalPermissionStatus
    derived_use: HistoricalPermissionStatus
    redistribution: HistoricalPermissionStatus
    commercial_use: HistoricalPermissionStatus
    personal_research: HistoricalPermissionStatus
    caching: HistoricalPermissionStatus
    attribution_required: bool | None
    unresolved_questions: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class HistoricalSourceDimensionScore:
    dimension: str
    score: int
    evidence_level: HistoricalEvidenceLevel
    explanation: str

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError("source dimension score must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class HistoricalSourceCandidate:
    provider_id: str
    name: str
    source_class: HistoricalSourceClass
    documents: tuple[HistoricalSourceDocument, ...]
    capabilities: tuple[HistoricalSourceCapability, ...]
    license_assessment: HistoricalSourceLicenseAssessment
    credential_environment_names: tuple[str, ...]
    authentication_requirement: str
    rate_limit: str
    batch_capability: str
    cost_status: str
    revision_risk: str
    operational_risks: tuple[str, ...]
    recommendation_status: HistoricalSourceRecommendationStatus
    scorecard: tuple[HistoricalSourceDimensionScore, ...]

    @property
    def requires_credentials(self) -> bool:
        return bool(self.credential_environment_names)

    def capability(self, key: str) -> HistoricalSourceCapability:
        for capability in self.capabilities:
            if capability.requirement_key == key:
                return capability
        raise KeyError(key)


@dataclass(frozen=True, slots=True)
class HistoricalSourceEvaluationManifestRecord:
    candidate_id: str
    candidate_date: date
    current_symbol: str | None
    historical_symbol: str
    permanent_identifier: str | None
    required_start_date: date
    required_end_date: date
    required_start_basis: str
    minimum_bars_required: int
    gap_cause: BreakoutGapCause
    corporate_action_requirement: bool
    identity_uncertainty: bool
    recovery_population: str
    replay_year: int
    sector: str | None
    market_regime: str | None
    setup_type: str | None
    liquidity_proxy: Decimal | None
    continuity_status: str


@dataclass(frozen=True, slots=True)
class HistoricalSourceEvaluationManifest:
    manifest_version: str
    records: tuple[HistoricalSourceEvaluationManifestRecord, ...]
    source_required_count: int
    recovery_uncertain_count: int
    unique_symbols: int
    earliest_required_date: date | None
    latest_required_date: date | None
    checksum: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class HistoricalSourceSampleManifest:
    sample_version: str
    source_manifest_version: str
    population_count: int
    requested_sample_size: int
    records: tuple[HistoricalSourceEvaluationManifestRecord, ...]
    stratum_counts: tuple[tuple[str, int], ...]
    limitations: tuple[str, ...]
    checksum: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class HistoricalSourceObservation:
    provider_id: str
    candidate_id: str
    query_succeeded: bool
    bars_returned: int
    usable_bars: int
    ohlc_complete: bool
    volume_complete: bool
    historical_symbol_matched: bool
    current_symbol_only: bool
    renamed_symbol_supported: bool | None
    delisted_symbol_supported: bool | None
    corporate_action_evidence_available: bool | None
    timezone_consistent: bool
    adjustment_consistent: bool
    duplicate_or_conflicting_bars: bool
    revision_identifier: str | None
    response_checksum: str | None
    missing_reason: str | None = None


@dataclass(frozen=True, slots=True)
class HistoricalSourceIdentityResult:
    provider_id: str
    candidate_id: str
    current_symbol_queryable: bool | None
    historical_symbol_queryable: bool | None
    isin_queryable: bool | None
    permanent_identifier_queryable: bool | None
    renamed_security_supported: bool | None
    delisted_security_supported: bool | None
    suspended_security_supported: bool | None
    relisted_security_supported: bool | None
    symbol_reuse_resolved: bool | None
    series_history_available: bool | None
    effective_dated_identity: bool | None
    evidence_level: HistoricalEvidenceLevel
    explanation: str


@dataclass(frozen=True, slots=True)
class HistoricalSourceCorporateActionResult:
    provider_id: str
    candidate_id: str
    raw_series_available: bool | None
    adjusted_series_available: bool | None
    adjustment_mode_explicit: bool | None
    adjustment_factors_available: bool | None
    effective_dates_available: bool | None
    price_volume_adjustment_consistent: bool | None
    retrospective_revision_versioned: bool | None
    existing_raw_policy_compatible: bool | None
    evidence_level: HistoricalEvidenceLevel
    explanation: str


@dataclass(frozen=True, slots=True)
class HistoricalSourceCoverageResult:
    provider_id: str
    provider_name: str
    evidence_level: HistoricalEvidenceLevel
    evaluation_status: HistoricalEvaluationStatus
    credential_status: HistoricalCredentialStatus
    target_candidates: int
    target_symbols: int
    observations_received: int
    candidate_2016_target: int
    candidate_2016_returned: int | None
    candidate_2016_sufficient: int | None
    candidates_queryable: int | None
    candidates_returned: int | None
    candidates_with_sufficient_lookback: int | None
    unique_symbols_covered: int | None
    historical_symbol_success_rate: Decimal | None
    renamed_symbol_success_rate: Decimal | None
    delisted_symbol_success_rate: Decimal | None
    corporate_action_evidence_success_rate: Decimal | None
    sufficient_lookback_rate: Decimal | None
    ohlc_completeness_rate: Decimal | None
    volume_completeness_rate: Decimal | None
    multi_session_gap_rate: Decimal | None
    duplicate_or_conflict_rate: Decimal | None
    timezone_consistency_rate: Decimal | None
    adjustment_consistency_rate: Decimal | None
    earliest_covered_candidate: date | None
    latest_covered_candidate: date | None
    unresolved_count: int | None
    projected_reconstruction_readiness: Decimal | None
    mandatory_gate_passed: bool
    mandatory_failures: tuple[str, ...]
    scorecard: tuple[HistoricalSourceDimensionScore, ...]
    warnings: tuple[str, ...]
    observed_checksum: str | None
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class HistoricalSourceRecommendationReport:
    evaluation_version: str
    requirements: tuple[HistoricalSourceRequirement, ...]
    manifest: HistoricalSourceEvaluationManifest
    sample: HistoricalSourceSampleManifest
    providers: tuple[HistoricalSourceCandidate, ...]
    coverage_results: tuple[HistoricalSourceCoverageResult, ...]
    total_missing_candidates_evaluated: int
    source_required_candidates: int
    recovery_uncertain_candidates: int
    providers_assessed: int
    providers_sampled: int
    providers_requiring_credentials: int
    providers_excluded_for_licensing_or_terms: int
    best_price_history_source: str
    best_historical_identity_source: str
    best_corporate_action_source: str
    best_exchange_authoritative_source: str
    projected_readiness_approved_combination: Decimal | None
    projected_remaining_unresolved_candidates: int | None
    projected_selection_bias_reduction: str
    licensing_conclusion: HistoricalLicenseStatus
    operational_risk_conclusion: str
    recommended_architecture: str
    architecture_conclusion: HistoricalArchitectureConclusion
    next_step_conclusion: HistoricalNextStepConclusion
    limitations: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


def historical_source_requirements() -> tuple[HistoricalSourceRequirement, ...]:
    mandatory = HistoricalRequirementPriority.MANDATORY
    preferred = HistoricalRequirementPriority.STRONGLY_PREFERRED
    optional = HistoricalRequirementPriority.OPTIONAL
    not_required = HistoricalRequirementPriority.NOT_REQUIRED
    return (
        _requirement("daily_open", "Daily open", mandatory, "OHLC integrity"),
        _requirement("daily_high", "Daily high", mandatory, "OHLC integrity"),
        _requirement("daily_low", "Daily low", mandatory, "OHLC integrity"),
        _requirement("daily_close", "Daily close", mandatory, "candidate comparison"),
        _requirement(
            "daily_volume",
            "Daily traded volume",
            mandatory,
            "20-session volume baseline",
        ),
        _requirement("trading_date", "Trading date", mandatory, "session cutoff"),
        _requirement(
            "exchange_session", "Exchange session", mandatory, "missing-session audit"
        ),
        _requirement(
            "historical_symbol", "Historical symbol", mandatory, "point-in-time lookup"
        ),
        _requirement(
            "permanent_identifier",
            "Permanent instrument identifier",
            mandatory,
            "identity continuity",
        ),
        _requirement(
            "listing_date", "Listing effective date", mandatory, "short-history proof"
        ),
        _requirement(
            "delisting_date",
            "Delisting effective date",
            mandatory,
            "survivorship audit",
        ),
        _requirement(
            "symbol_change_history",
            "Effective-dated symbol changes",
            mandatory,
            "historical identity",
        ),
        _requirement(
            "split_bonus_history",
            "Split and bonus history",
            mandatory,
            "raw discontinuity explanation",
        ),
        _requirement(
            "corporate_action_effective_dates",
            "Corporate-action effective dates",
            mandatory,
            "candidate cutoff and discontinuity",
        ),
        _requirement(
            "adjustment_mode",
            "Explicit adjustment mode",
            mandatory,
            "raw-series consistency",
        ),
        _requirement(
            "raw_series",
            "Raw unadjusted price and volume",
            mandatory,
            "existing adjustment policy",
        ),
        _requirement(
            "suspended_sessions",
            "Suspended-session evidence",
            mandatory,
            "gap classification",
        ),
        _requirement(
            "zero_trade_sessions",
            "Zero-trade-session evidence",
            mandatory,
            "no invented flat bars",
        ),
        _requirement("provenance", "Source provenance", mandatory, "lineage checksum"),
        _requirement(
            "revision_policy",
            "Revision and correction policy",
            mandatory,
            "reproducibility",
        ),
        _requirement(
            "publication_timing",
            "Source publication timing",
            mandatory,
            "point-in-time availability",
        ),
        _requirement(
            "historical_availability_start",
            "Historical availability start",
            mandatory,
            "121-bar proof",
        ),
        _requirement(
            "local_storage_permission",
            "Local storage permission",
            mandatory,
            "immutable sidecar and checksums",
        ),
        _requirement(
            "derived_use_permission",
            "Derived analytical use permission",
            mandatory,
            "breakout reconstruction",
        ),
        _requirement(
            "price_volume_consistency",
            "Price-volume adjustment consistency",
            preferred,
            "corporate-action validation",
        ),
        _requirement("isin", "ISIN", preferred, "cross-provider identity"),
        _requirement(
            "series_history", "EQ/BE and series history", preferred, "series continuity"
        ),
        _requirement(
            "relisting_history", "Relisting history", preferred, "identity continuity"
        ),
        _requirement(
            "archived_original_publication",
            "Originally published archive",
            preferred,
            "publication-time reconstruction",
        ),
        _requirement(
            "dividend_history",
            "Dividend history",
            optional,
            "diagnostic only under raw policy",
        ),
        _requirement(
            "redistribution_permission",
            "Redistribution permission",
            not_required,
            "internal diagnostic does not redistribute data",
        ),
        _requirement(
            "delivery_volume",
            "Delivery volume",
            not_required,
            "classifier uses traded volume",
        ),
        _requirement(
            "adjusted_prices",
            "Retrospectively adjusted prices",
            not_required,
            "existing policy requires raw data",
        ),
    )


def _requirement(
    key: str,
    label: str,
    priority: HistoricalRequirementPriority,
    dependency: str,
) -> HistoricalSourceRequirement:
    return HistoricalSourceRequirement(
        key=key,
        label=label,
        priority=priority,
        rationale=f"Required classification: {priority.value}.",
        existing_dependency=dependency,
    )


class HistoricalSourceEvaluationEngine:
    """Evaluate evidence without registering or calling production providers."""

    def evaluate(
        self,
        *,
        manifest: HistoricalSourceEvaluationManifest,
        sample: HistoricalSourceSampleManifest,
        providers: Sequence[HistoricalSourceCandidate],
        credential_statuses: Mapping[str, HistoricalCredentialStatus],
        observations: Sequence[HistoricalSourceObservation] = (),
        full_population: bool = False,
        dry_run: bool = False,
    ) -> HistoricalSourceRecommendationReport:
        requirements = historical_source_requirements()
        target = manifest.records if full_population else sample.records
        target_ids = {item.candidate_id for item in target}
        observations_by_provider: dict[str, list[HistoricalSourceObservation]] = (
            defaultdict(list)
        )
        for observation in observations:
            if observation.candidate_id in target_ids:
                observations_by_provider[observation.provider_id].append(observation)
        ordered_providers = tuple(sorted(providers, key=lambda item: item.provider_id))
        results = tuple(
            self._evaluate_provider(
                provider=provider,
                target=target,
                manifest=manifest,
                credentials=credential_statuses.get(
                    provider.provider_id,
                    HistoricalCredentialStatus.NOT_CONFIGURED,
                ),
                observations=tuple(
                    sorted(
                        observations_by_provider.get(provider.provider_id, ()),
                        key=lambda item: item.candidate_id,
                    )
                ),
                full_population=full_population,
                dry_run=dry_run,
                requirements=requirements,
            )
            for provider in ordered_providers
        )
        sampled = sum(item.observations_received > 0 for item in results)
        excluded = sum(
            provider.license_assessment.status
            in {
                HistoricalLicenseStatus.APPARENTLY_PROHIBITED,
                HistoricalLicenseStatus.PERSONAL_RESEARCH_ONLY,
                HistoricalLicenseStatus.RESTRICTIONS_UNCLEAR,
                HistoricalLicenseStatus.TERMS_NOT_FOUND,
            }
            for provider in ordered_providers
        )
        provider_index = {item.provider_id: item for item in ordered_providers}
        verified = tuple(
            item
            for item in results
            if item.mandatory_gate_passed
            and item.evidence_level is HistoricalEvidenceLevel.FULL_POPULATION_VERIFIED
        )
        authoritative_verified = tuple(
            item
            for item in verified
            if provider_index[item.provider_id].source_class
            is not HistoricalSourceClass.BROKER_API
        )
        primary = (
            min(
                authoritative_verified,
                key=lambda item: _provider_preference(provider_index[item.provider_id]),
            )
            if authoritative_verified
            else None
        )
        if primary is not None:
            primary_provider = provider_index[primary.provider_id]
            best_price_source = primary.provider_id
            best_identity_source = primary.provider_id
            best_corporate_action_source = primary.provider_id
            best_exchange_source = (
                primary.provider_id
                if primary_provider.source_class
                in {
                    HistoricalSourceClass.EXCHANGE_PUBLIC_ARCHIVE,
                    HistoricalSourceClass.EXCHANGE_LICENSED_DATA,
                }
                else "NO_EXCHANGE_SOURCE_FULLY_VERIFIED"
            )
            architecture = (
                HistoricalArchitectureConclusion.SINGLE_AUTHORITATIVE_SOURCE_IDENTIFIED
            )
            next_step = HistoricalNextStepConclusion.COVERAGE_PROOF_COMPLETE
            licensing = primary_provider.license_assessment.status
            architecture_text = (
                f"{primary.provider_id} is the only fully verified source required "
                "for the evaluated population."
            )
        else:
            best_price_source = "NSE_DATA_ANALYTICS_LICENSED"
            best_identity_source = "LSEG_DATASCOPE_SELECT"
            best_corporate_action_source = "NSE_DATA_ANALYTICS_LICENSED"
            best_exchange_source = "NSE_DATA_ANALYTICS_LICENSED"
            architecture = (
                HistoricalArchitectureConclusion.MULTI_SOURCE_ARCHITECTURE_REQUIRED
            )
            next_step = HistoricalNextStepConclusion.SOURCE_EVIDENCE_INSUFFICIENT
            licensing = HistoricalLicenseStatus.REQUIRES_COMMERCIAL_LICENSE
            architecture_text = (
                "Licensed NSE historical/EOD prices and corporate data as the "
                "authoritative base; a contracted LSEG identity feed for delisted "
                "and renamed continuity; broker APIs only for secondary overlap "
                "validation."
            )
        return HistoricalSourceRecommendationReport(
            evaluation_version=HISTORICAL_SOURCE_EVALUATION_VERSION,
            requirements=requirements,
            manifest=manifest,
            sample=sample,
            providers=ordered_providers,
            coverage_results=results,
            total_missing_candidates_evaluated=len(manifest.records),
            source_required_candidates=manifest.source_required_count,
            recovery_uncertain_candidates=manifest.recovery_uncertain_count,
            providers_assessed=len(ordered_providers),
            providers_sampled=sampled,
            providers_requiring_credentials=sum(
                provider.requires_credentials for provider in ordered_providers
            ),
            providers_excluded_for_licensing_or_terms=excluded,
            best_price_history_source=best_price_source,
            best_historical_identity_source=best_identity_source,
            best_corporate_action_source=best_corporate_action_source,
            best_exchange_authoritative_source=best_exchange_source,
            projected_readiness_approved_combination=None,
            projected_remaining_unresolved_candidates=None,
            projected_selection_bias_reduction=(
                "NOT_ESTIMABLE_WITHOUT_OBSERVED_CANDIDATE_COVERAGE"
            ),
            licensing_conclusion=licensing,
            operational_risk_conclusion=(
                "CONTRACT_ENTITLEMENT_AND_FULL_POPULATION_SAMPLE_REQUIRED"
            ),
            recommended_architecture=architecture_text,
            architecture_conclusion=architecture,
            next_step_conclusion=next_step,
            limitations=(
                "No external provider response was fabricated.",
                "Documented availability is not measured candidate coverage.",
                "No provider has proven all 657 records or permitted storage and "
                "derived use under a reviewed contract.",
                "Projected readiness and bias reduction remain unavailable.",
            ),
        )

    def _evaluate_provider(
        self,
        *,
        provider: HistoricalSourceCandidate,
        target: tuple[HistoricalSourceEvaluationManifestRecord, ...],
        manifest: HistoricalSourceEvaluationManifest,
        credentials: HistoricalCredentialStatus,
        observations: tuple[HistoricalSourceObservation, ...],
        full_population: bool,
        dry_run: bool,
        requirements: tuple[HistoricalSourceRequirement, ...],
    ) -> HistoricalSourceCoverageResult:
        mandatory_failures = tuple(
            requirement.key
            for requirement in requirements
            if requirement.priority is HistoricalRequirementPriority.MANDATORY
            and provider.capability(requirement.key).status
            is not HistoricalCapabilityStatus.SUPPORTED
        )
        license_block = provider.license_assessment.local_storage in {
            HistoricalPermissionStatus.PROHIBITED,
            HistoricalPermissionStatus.UNKNOWN,
            HistoricalPermissionStatus.REQUIRES_WRITTEN_PERMISSION,
        } or provider.license_assessment.derived_use in {
            HistoricalPermissionStatus.PROHIBITED,
            HistoricalPermissionStatus.UNKNOWN,
            HistoricalPermissionStatus.REQUIRES_WRITTEN_PERMISSION,
        }
        if dry_run:
            status = HistoricalEvaluationStatus.DRY_RUN_DOCUMENTED_ONLY
        elif observations:
            status = (
                HistoricalEvaluationStatus.FULL_POPULATION_VERIFIED
                if full_population and len(observations) == len(target)
                else HistoricalEvaluationStatus.OBSERVED_SAMPLE_COMPLETE
                if len(observations) == len(target)
                else HistoricalEvaluationStatus.OBSERVED_SAMPLE_PARTIAL
            )
        elif provider.requires_credentials and credentials in {
            HistoricalCredentialStatus.NOT_CONFIGURED,
            HistoricalCredentialStatus.SUBSCRIPTION_REQUIRED,
        }:
            status = HistoricalEvaluationStatus.NOT_EVALUATED_CREDENTIALS_REQUIRED
        elif license_block:
            status = HistoricalEvaluationStatus.NOT_EVALUATED_TERMS_RESTRICT_CACHING
        else:
            status = HistoricalEvaluationStatus.DOCUMENTED_ONLY
        if not observations:
            return HistoricalSourceCoverageResult(
                provider_id=provider.provider_id,
                provider_name=provider.name,
                evidence_level=HistoricalEvidenceLevel.DOCUMENTED,
                evaluation_status=status,
                credential_status=credentials,
                target_candidates=len(target),
                target_symbols=len({item.historical_symbol for item in target}),
                observations_received=0,
                candidate_2016_target=sum(item.replay_year == 2016 for item in target),
                candidate_2016_returned=None,
                candidate_2016_sufficient=None,
                candidates_queryable=None,
                candidates_returned=None,
                candidates_with_sufficient_lookback=None,
                unique_symbols_covered=None,
                historical_symbol_success_rate=None,
                renamed_symbol_success_rate=None,
                delisted_symbol_success_rate=None,
                corporate_action_evidence_success_rate=None,
                sufficient_lookback_rate=None,
                ohlc_completeness_rate=None,
                volume_completeness_rate=None,
                multi_session_gap_rate=None,
                duplicate_or_conflict_rate=None,
                timezone_consistency_rate=None,
                adjustment_consistency_rate=None,
                earliest_covered_candidate=None,
                latest_covered_candidate=None,
                unresolved_count=None,
                projected_reconstruction_readiness=None,
                mandatory_gate_passed=False,
                mandatory_failures=mandatory_failures,
                scorecard=provider.scorecard,
                warnings=(
                    "DOCUMENTED capability only; exact candidate coverage unknown.",
                    "No projected readiness is calculated without observed records.",
                ),
                observed_checksum=None,
            )
        record_index = {item.candidate_id: item for item in target}
        observations_by_candidate: dict[str, list[HistoricalSourceObservation]] = (
            defaultdict(list)
        )
        for observation in observations:
            observations_by_candidate[observation.candidate_id].append(observation)
        response_conflicts = tuple(
            candidate
            for candidate, rows in sorted(observations_by_candidate.items())
            if len(
                {
                    item.response_checksum
                    for item in rows
                    if item.response_checksum is not None
                }
            )
            > 1
        )
        revisions_detected = tuple(
            candidate
            for candidate, rows in sorted(observations_by_candidate.items())
            if len(
                {
                    item.revision_identifier
                    for item in rows
                    if item.revision_identifier is not None
                }
            )
            > 1
        )
        canonical_observations = tuple(
            sorted(
                (
                    sorted(
                        rows,
                        key=lambda item: (
                            item.revision_identifier or "",
                            item.response_checksum or "",
                        ),
                    )[-1]
                    for rows in observations_by_candidate.values()
                ),
                key=lambda item: item.candidate_id,
            )
        )
        successful = tuple(
            item for item in canonical_observations if item.query_succeeded
        )
        returned = tuple(item for item in successful if item.usable_bars > 0)
        sufficient = tuple(
            item
            for item in returned
            if item.usable_bars >= record_index[item.candidate_id].minimum_bars_required
            and item.ohlc_complete
            and item.volume_complete
            and item.historical_symbol_matched
            and not item.current_symbol_only
            and item.timezone_consistent
            and item.adjustment_consistent
            and not item.duplicate_or_conflicting_bars
            and (
                not record_index[item.candidate_id].corporate_action_requirement
                or item.corporate_action_evidence_available is True
            )
        )
        covered_dates = tuple(
            record_index[item.candidate_id].candidate_date for item in returned
        )
        observed_checksum = _hash(
            tuple(
                _jsonable(item)
                for item in sorted(
                    observations,
                    key=lambda row: (
                        row.candidate_id,
                        row.revision_identifier or "",
                        row.response_checksum or "",
                    ),
                )
            )
        )
        evidence = (
            HistoricalEvidenceLevel.FULL_POPULATION_VERIFIED
            if full_population and len(observations) == len(manifest.records)
            else HistoricalEvidenceLevel.OBSERVED_IN_SAMPLE
        )
        mandatory_gate = (
            not mandatory_failures
            and not license_block
            and not response_conflicts
            and len(sufficient) == len(target)
            and len(canonical_observations) == len(target)
        )
        projected_ready = (
            889 + len(sufficient)
            if full_population and len(observations) == len(manifest.records)
            else None
        )
        return HistoricalSourceCoverageResult(
            provider_id=provider.provider_id,
            provider_name=provider.name,
            evidence_level=evidence,
            evaluation_status=status,
            credential_status=credentials,
            target_candidates=len(target),
            target_symbols=len({item.historical_symbol for item in target}),
            observations_received=len(canonical_observations),
            candidate_2016_target=sum(item.replay_year == 2016 for item in target),
            candidate_2016_returned=sum(
                record_index[item.candidate_id].replay_year == 2016 for item in returned
            ),
            candidate_2016_sufficient=sum(
                record_index[item.candidate_id].replay_year == 2016
                for item in sufficient
            ),
            candidates_queryable=sum(
                item.query_succeeded for item in canonical_observations
            ),
            candidates_returned=len(returned),
            candidates_with_sufficient_lookback=len(sufficient),
            unique_symbols_covered=len(
                {record_index[item.candidate_id].historical_symbol for item in returned}
            ),
            historical_symbol_success_rate=_optional_boolean_rate(
                canonical_observations,
                lambda item: item.historical_symbol_matched,
            ),
            renamed_symbol_success_rate=_nullable_boolean_rate(
                canonical_observations,
                lambda item: item.renamed_symbol_supported,
            ),
            delisted_symbol_success_rate=_nullable_boolean_rate(
                canonical_observations,
                lambda item: item.delisted_symbol_supported,
            ),
            corporate_action_evidence_success_rate=_nullable_boolean_rate(
                tuple(
                    item
                    for item in canonical_observations
                    if record_index[item.candidate_id].corporate_action_requirement
                ),
                lambda item: item.corporate_action_evidence_available,
            ),
            sufficient_lookback_rate=_rate(
                len(sufficient), len(canonical_observations)
            ),
            ohlc_completeness_rate=_optional_boolean_rate(
                canonical_observations, lambda item: item.ohlc_complete
            ),
            volume_completeness_rate=_optional_boolean_rate(
                canonical_observations, lambda item: item.volume_complete
            ),
            multi_session_gap_rate=_rate(
                sum(
                    item.query_succeeded
                    and item.usable_bars
                    < record_index[item.candidate_id].minimum_bars_required
                    for item in canonical_observations
                ),
                len(canonical_observations),
            ),
            duplicate_or_conflict_rate=_optional_boolean_rate(
                canonical_observations,
                lambda item: item.duplicate_or_conflicting_bars,
            ),
            timezone_consistency_rate=_optional_boolean_rate(
                canonical_observations, lambda item: item.timezone_consistent
            ),
            adjustment_consistency_rate=_optional_boolean_rate(
                canonical_observations, lambda item: item.adjustment_consistent
            ),
            earliest_covered_candidate=min(covered_dates, default=None),
            latest_covered_candidate=max(covered_dates, default=None),
            unresolved_count=len(target) - len(sufficient),
            projected_reconstruction_readiness=(
                _rate(projected_ready, 1546) if projected_ready is not None else None
            ),
            mandatory_gate_passed=mandatory_gate,
            mandatory_failures=mandatory_failures,
            scorecard=provider.scorecard,
            warnings=tuple(
                item
                for item in (
                    "Observed sample coverage is not full-population coverage."
                    if not full_population
                    else "Full-population result still requires license approval.",
                    "Provider returned conflicting checksums for candidates: "
                    + ", ".join(response_conflicts)
                    if response_conflicts
                    else None,
                    "Provider revision identifiers changed for candidates: "
                    + ", ".join(revisions_detected)
                    if revisions_detected
                    else None,
                )
                if item is not None
            ),
            observed_checksum=observed_checksum,
        )


def build_historical_source_candidates() -> tuple[HistoricalSourceCandidate, ...]:
    nse_policy = "https://www.nseindia.com/static/market-data/nse-data-policy"
    nse_terms = "https://www.nseindia.com/static/nse-terms-of-use"
    nse_reports = "https://www.nseindia.com/all-reports"
    nse_securities = (
        "https://www.nseindia.com/static/market-data/securities-available-for-trading"
    )
    nse_paid = (
        "https://www.nseindia.com/static/market-data/eod-historical-data-subscription"
    )
    upstox_history = (
        "https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/"
    )
    upstox_instruments = "https://upstox.com/developer/api-documentation/instruments/"
    kite_history = "https://kite.trade/docs/connect/v3/historical/"
    kite_terms = "https://kite.trade/terms/"
    dhan_history = "https://dhanhq.co/docs/v2/historical-data/"
    dhan_instruments = "https://dhanhq.co/docs/v2/instruments/"
    gfdl = "https://globaldatafeeds.in/"
    truedata = "https://www.truedata.in/market-data-apis"
    lseg = (
        "https://www.lseg.com/en/data-analytics/products/"
        "datascope-plus-securities-database"
    )
    factset = "https://developer.factset.com/api-catalog/symbology-api"
    return tuple(
        sorted(
            (
                _provider(
                    provider_id="NSE_PUBLIC_ARCHIVES",
                    name="NSE public reports and archives",
                    source_class=HistoricalSourceClass.EXCHANGE_PUBLIC_ARCHIVE,
                    documents=(
                        HistoricalSourceDocument("NSE All Reports", nse_reports),
                        HistoricalSourceDocument(
                            "NSE securities and symbol changes", nse_securities
                        ),
                        HistoricalSourceDocument("NSE Terms of Use", nse_terms),
                        HistoricalSourceDocument(
                            "NSE Data Sharing and Usage Policy", nse_policy
                        ),
                    ),
                    supported={
                        "daily_open": nse_reports,
                        "daily_high": nse_reports,
                        "daily_low": nse_reports,
                        "daily_close": nse_reports,
                        "daily_volume": nse_reports,
                        "trading_date": nse_reports,
                        "exchange_session": nse_reports,
                        "historical_symbol": nse_reports,
                        "symbol_change_history": nse_securities,
                        "split_bonus_history": nse_reports,
                        "corporate_action_effective_dates": nse_reports,
                        "adjustment_mode": nse_reports,
                        "raw_series": nse_reports,
                        "provenance": nse_reports,
                        "publication_timing": nse_reports,
                        "archived_original_publication": nse_reports,
                    },
                    partial={
                        "permanent_identifier": nse_securities,
                        "listing_date": nse_securities,
                        "delisting_date": nse_securities,
                        "suspended_sessions": nse_reports,
                        "zero_trade_sessions": nse_reports,
                        "revision_policy": nse_policy,
                        "historical_availability_start": nse_reports,
                        "isin": nse_securities,
                        "series_history": nse_securities,
                    },
                    unsupported={
                        "local_storage_permission": nse_terms,
                        "derived_use_permission": nse_terms,
                    },
                    license_assessment=HistoricalSourceLicenseAssessment(
                        status=HistoricalLicenseStatus.PERSONAL_RESEARCH_ONLY,
                        terms_url=nse_terms,
                        automated_download=HistoricalPermissionStatus.PROHIBITED,
                        local_storage=HistoricalPermissionStatus.REQUIRES_WRITTEN_PERMISSION,
                        derived_use=HistoricalPermissionStatus.REQUIRES_WRITTEN_PERMISSION,
                        redistribution=HistoricalPermissionStatus.PROHIBITED,
                        commercial_use=HistoricalPermissionStatus.REQUIRES_WRITTEN_PERMISSION,
                        personal_research=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        caching=HistoricalPermissionStatus.REQUIRES_WRITTEN_PERMISSION,
                        attribution_required=True,
                        unresolved_questions=(
                            "Whether Alpha's retained analytical store is permitted "
                            "without a subscriber agreement.",
                        ),
                        explanation=(
                            "Public downloads are authoritative, but automated "
                            "collection and retained production use are not cleared."
                        ),
                    ),
                    credentials=(),
                    authentication="Public website; licensed use requires agreement",
                    rate_limit="No supported bulk automation rate documented",
                    batch="Daily and report ZIP files",
                    cost="Public personal downloads; licensed use priced separately",
                    revision=(
                        "Website files may be corrected; no local revision feed proven"
                    ),
                    risks=(
                        "anti-automation terms",
                        "historical identity fragmentation",
                    ),
                    recommendation=HistoricalSourceRecommendationStatus.RESEARCH_ONLY,
                    scores=(
                        100,
                        75,
                        0,
                        50,
                        25,
                        75,
                        75,
                        90,
                        75,
                        35,
                        20,
                        50,
                        25,
                        25,
                        90,
                        45,
                        40,
                    ),
                ),
                _provider(
                    provider_id="NSE_DATA_ANALYTICS_LICENSED",
                    name=(
                        "NSE Data & Analytics licensed EOD, historical and "
                        "corporate data"
                    ),
                    source_class=HistoricalSourceClass.EXCHANGE_LICENSED_DATA,
                    documents=(
                        HistoricalSourceDocument(
                            "NSE paid EOD and historical data", nse_paid
                        ),
                        HistoricalSourceDocument(
                            "NSE Data Sharing and Usage Policy", nse_policy
                        ),
                    ),
                    supported={
                        "daily_open": nse_paid,
                        "daily_high": nse_paid,
                        "daily_low": nse_paid,
                        "daily_close": nse_paid,
                        "daily_volume": nse_paid,
                        "trading_date": nse_paid,
                        "exchange_session": nse_paid,
                        "historical_symbol": nse_paid,
                        "permanent_identifier": nse_paid,
                        "split_bonus_history": nse_policy,
                        "corporate_action_effective_dates": nse_policy,
                        "adjustment_mode": nse_paid,
                        "raw_series": nse_paid,
                        "suspended_sessions": nse_paid,
                        "zero_trade_sessions": nse_paid,
                        "provenance": nse_paid,
                        "revision_policy": nse_policy,
                        "publication_timing": nse_paid,
                        "historical_availability_start": nse_paid,
                        "isin": nse_paid,
                        "series_history": nse_paid,
                        "archived_original_publication": nse_paid,
                    },
                    partial={
                        "listing_date": nse_paid,
                        "delisting_date": nse_paid,
                        "symbol_change_history": nse_paid,
                        "relisting_history": nse_paid,
                        "local_storage_permission": nse_policy,
                        "derived_use_permission": nse_policy,
                    },
                    unsupported={},
                    license_assessment=HistoricalSourceLicenseAssessment(
                        status=HistoricalLicenseStatus.REQUIRES_COMMERCIAL_LICENSE,
                        terms_url=nse_policy,
                        automated_download=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        local_storage=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        derived_use=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        redistribution=HistoricalPermissionStatus.REQUIRES_WRITTEN_PERMISSION,
                        commercial_use=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        personal_research=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        caching=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        attribution_required=None,
                        unresolved_questions=(
                            "Exact storage, retention, derived-signal and user-display "
                            "rights must be written into the subscriber agreement.",
                        ),
                        explanation=(
                            "Technically strongest exchange source; contractual "
                            "entitlement required."
                        ),
                    ),
                    credentials=("NSE_DATA_SUBSCRIPTION_ID",),
                    authentication="Commercial subscription and entitlement",
                    rate_limit="SFTP or online delivery under subscription",
                    batch="EOD files, historical platform and corporate data products",
                    cost="Commercial tariff or quote required",
                    revision=(
                        "Exchange-controlled files; correction/version process "
                        "must be contracted"
                    ),
                    risks=(
                        "commercial dependency",
                        "contract-specific field entitlement",
                    ),
                    recommendation=HistoricalSourceRecommendationStatus.PRIMARY_SOURCE_CANDIDATE,
                    scores=(
                        100,
                        100,
                        0,
                        75,
                        75,
                        100,
                        100,
                        100,
                        95,
                        80,
                        75,
                        100,
                        50,
                        50,
                        10,
                        55,
                        65,
                    ),
                ),
                _provider(
                    provider_id="UPSTOX_HISTORICAL_V3",
                    name="Upstox Historical Candle Data V3",
                    source_class=HistoricalSourceClass.BROKER_API,
                    documents=(
                        HistoricalSourceDocument(
                            "Upstox Historical Candle Data V3", upstox_history
                        ),
                        HistoricalSourceDocument(
                            "Upstox Instruments", upstox_instruments
                        ),
                    ),
                    supported=_price_capabilities(upstox_history)
                    | {
                        "permanent_identifier": upstox_instruments,
                        "isin": upstox_instruments,
                        "historical_availability_start": upstox_history,
                    },
                    partial={
                        "historical_symbol": upstox_instruments,
                        "publication_timing": upstox_history,
                        "provenance": upstox_history,
                    },
                    unsupported={
                        "listing_date": upstox_instruments,
                        "delisting_date": upstox_instruments,
                        "symbol_change_history": upstox_instruments,
                        "split_bonus_history": upstox_history,
                        "corporate_action_effective_dates": upstox_history,
                        "suspended_sessions": upstox_instruments,
                        "zero_trade_sessions": upstox_history,
                    },
                    license_assessment=_unknown_terms_license(
                        "Official API documentation does not establish retained "
                        "database and derived-use rights."
                    ),
                    credentials=("UPSTOX_ANALYTICS_TOKEN", "UPSTOX_ACCESS_TOKEN"),
                    authentication="Bearer analytics or access token",
                    rate_limit=(
                        "50/second, 500/minute, 2000/30 minutes for standard APIs"
                    ),
                    batch="One instrument/date range; daily data documented from 2000",
                    cost=(
                        "Account/token required; historical endpoint price not "
                        "separately stated"
                    ),
                    revision=(
                        "Returns data up to access time; revision lineage not "
                        "documented"
                    ),
                    risks=(
                        "BOD master excludes delisted equities",
                        "no corporate-action feed",
                    ),
                    recommendation=HistoricalSourceRecommendationStatus.SECONDARY_VALIDATION_SOURCE,
                    scores=(
                        70,
                        100,
                        0,
                        45,
                        0,
                        0,
                        35,
                        75,
                        60,
                        90,
                        90,
                        20,
                        0,
                        0,
                        75,
                        85,
                        55,
                    ),
                ),
                _provider(
                    provider_id="ZERODHA_KITE_HISTORICAL",
                    name="Zerodha Kite Connect historical candles",
                    source_class=HistoricalSourceClass.BROKER_API,
                    documents=(
                        HistoricalSourceDocument(
                            "Kite historical candle data", kite_history
                        ),
                        HistoricalSourceDocument("Kite Connect terms", kite_terms),
                    ),
                    supported=_price_capabilities(kite_history),
                    partial={
                        "historical_symbol": kite_history,
                        "historical_availability_start": kite_history,
                        "publication_timing": kite_history,
                        "provenance": kite_history,
                    },
                    unsupported={
                        "permanent_identifier": kite_history,
                        "listing_date": kite_history,
                        "delisting_date": kite_history,
                        "symbol_change_history": kite_history,
                        "split_bonus_history": kite_history,
                        "corporate_action_effective_dates": kite_history,
                        "suspended_sessions": kite_history,
                        "zero_trade_sessions": kite_history,
                        "local_storage_permission": kite_terms,
                    },
                    license_assessment=HistoricalSourceLicenseAssessment(
                        status=HistoricalLicenseStatus.PERMITTED_WITH_CONDITIONS,
                        terms_url=kite_terms,
                        automated_download=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        local_storage=HistoricalPermissionStatus.PROHIBITED,
                        derived_use=HistoricalPermissionStatus.UNKNOWN,
                        redistribution=HistoricalPermissionStatus.PROHIBITED,
                        commercial_use=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        personal_research=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        caching=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        attribution_required=None,
                        unresolved_questions=(
                            "A separate written license would be required for a "
                            "permanent historical database.",
                        ),
                        explanation=(
                            "API use is licensed, but permanent content copies "
                            "are restricted."
                        ),
                    ),
                    credentials=("KITE_API_KEY", "KITE_ACCESS_TOKEN"),
                    authentication="Kite Connect account and token",
                    rate_limit=(
                        "Provider-controlled; exact current historical limit not "
                        "documented on endpoint page"
                    ),
                    batch="One instrument token and bounded date range",
                    cost=(
                        "Paid Kite Connect access; current exact price not relied upon"
                    ),
                    revision=(
                        "Archive is up to date at access time; no revision versions "
                        "documented"
                    ),
                    risks=("current token dependency", "permanent cache restriction"),
                    recommendation=HistoricalSourceRecommendationStatus.SECONDARY_VALIDATION_SOURCE,
                    scores=(
                        70,
                        60,
                        0,
                        30,
                        0,
                        0,
                        25,
                        75,
                        55,
                        75,
                        60,
                        60,
                        0,
                        20,
                        45,
                        80,
                        50,
                    ),
                ),
                _provider(
                    provider_id="DHAN_HISTORICAL_V2",
                    name="DhanHQ daily historical data",
                    source_class=HistoricalSourceClass.BROKER_API,
                    documents=(
                        HistoricalSourceDocument(
                            "DhanHQ historical data", dhan_history
                        ),
                        HistoricalSourceDocument(
                            "DhanHQ instruments", dhan_instruments
                        ),
                    ),
                    supported=_price_capabilities(dhan_history)
                    | {"historical_availability_start": dhan_history},
                    partial={
                        "historical_symbol": dhan_instruments,
                        "permanent_identifier": dhan_instruments,
                        "provenance": dhan_history,
                    },
                    unsupported={
                        "listing_date": dhan_instruments,
                        "delisting_date": dhan_instruments,
                        "symbol_change_history": dhan_instruments,
                        "split_bonus_history": dhan_history,
                        "corporate_action_effective_dates": dhan_history,
                        "suspended_sessions": dhan_instruments,
                        "zero_trade_sessions": dhan_history,
                    },
                    license_assessment=_unknown_terms_license(
                        "API documentation and subscription pricing do not prove "
                        "retained storage or derived-signal rights."
                    ),
                    credentials=("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN"),
                    authentication="Dhan account, data subscription and token",
                    rate_limit="5 data requests/second and 100000/day",
                    batch="One active security ID/date range",
                    cost=(
                        "Commercial access; exact current price not established "
                        "from the linked endpoint documentation"
                    ),
                    revision=(
                        "Revision and original-publication versioning not documented"
                    ),
                    risks=(
                        "documentation says active instruments",
                        "no corporate-action feed",
                    ),
                    recommendation=HistoricalSourceRecommendationStatus.SECONDARY_VALIDATION_SOURCE,
                    scores=(
                        70,
                        75,
                        0,
                        35,
                        0,
                        0,
                        25,
                        75,
                        50,
                        80,
                        80,
                        20,
                        0,
                        0,
                        80,
                        85,
                        55,
                    ),
                ),
                _provider(
                    provider_id="GLOBAL_DATAFEEDS",
                    name="Global Datafeeds historical/EOD API",
                    source_class=HistoricalSourceClass.AUTHORIZED_MARKET_DATA_VENDOR,
                    documents=(HistoricalSourceDocument("Global Datafeeds", gfdl),),
                    supported=_price_capabilities(gfdl) | {"provenance": gfdl},
                    partial={"historical_availability_start": gfdl},
                    unsupported={},
                    license_assessment=_unknown_terms_license(
                        "Vendor is NSE-authorized for real-time data, but exact "
                        "historical retention, identity and derived-use terms were "
                        "not found."
                    ),
                    credentials=("GDFL_ACCESS_KEY",),
                    authentication="Commercial API subscription",
                    rate_limit="Not established for the required historical workload",
                    batch="Historical GetHistory endpoint documented",
                    cost="Commercial quote or plan required",
                    revision="Correction and revision lineage not established",
                    risks=(
                        "exact depth unknown",
                        "delisted and rename coverage unknown",
                    ),
                    recommendation=HistoricalSourceRecommendationStatus.INSUFFICIENT_EVIDENCE,
                    scores=(
                        80,
                        50,
                        0,
                        25,
                        10,
                        0,
                        25,
                        70,
                        50,
                        70,
                        50,
                        20,
                        0,
                        0,
                        20,
                        70,
                        55,
                    ),
                ),
                _provider(
                    provider_id="TRUEDATA",
                    name="TrueData historical/EOD and corporate feeds",
                    source_class=HistoricalSourceClass.AUTHORIZED_MARKET_DATA_VENDOR,
                    documents=(
                        HistoricalSourceDocument("TrueData Market Data API", truedata),
                    ),
                    supported=_price_capabilities(truedata) | {"provenance": truedata},
                    partial={
                        "historical_availability_start": truedata,
                        "split_bonus_history": truedata,
                        "corporate_action_effective_dates": truedata,
                    },
                    unsupported={},
                    license_assessment=_unknown_terms_license(
                        "Corporate feeds are advertised, but exact historical depth, "
                        "identity retention and license rights require a written quote."
                    ),
                    credentials=("TRUEDATA_API_KEY",),
                    authentication="Commercial API subscription",
                    rate_limit="Plan-specific and not established for this evaluation",
                    batch="Historical EOD API advertised",
                    cost="Commercial subscription or quote required",
                    revision=(
                        "Correction and original-publication lineage not established"
                    ),
                    risks=(
                        "historical identity unknown",
                        "contract terms not reviewed",
                    ),
                    recommendation=HistoricalSourceRecommendationStatus.INSUFFICIENT_EVIDENCE,
                    scores=(
                        80,
                        50,
                        0,
                        25,
                        10,
                        50,
                        25,
                        70,
                        50,
                        70,
                        50,
                        20,
                        0,
                        0,
                        20,
                        70,
                        55,
                    ),
                ),
                _provider(
                    provider_id="LSEG_DATASCOPE_SELECT",
                    name="LSEG DataScope Select/Plus",
                    source_class=HistoricalSourceClass.SPECIALIST_INSTITUTIONAL_VENDOR,
                    documents=(HistoricalSourceDocument("LSEG DataScope Plus", lseg),),
                    supported={
                        **_price_capabilities(lseg),
                        "historical_symbol": lseg,
                        "permanent_identifier": lseg,
                        "listing_date": lseg,
                        "delisting_date": lseg,
                        "symbol_change_history": lseg,
                        "split_bonus_history": lseg,
                        "corporate_action_effective_dates": lseg,
                        "provenance": lseg,
                        "revision_policy": lseg,
                        "historical_availability_start": lseg,
                        "isin": lseg,
                        "series_history": lseg,
                        "relisting_history": lseg,
                    },
                    partial={
                        "adjustment_mode": lseg,
                        "raw_series": lseg,
                        "publication_timing": lseg,
                        "suspended_sessions": lseg,
                        "zero_trade_sessions": lseg,
                        "local_storage_permission": lseg,
                        "derived_use_permission": lseg,
                    },
                    unsupported={},
                    license_assessment=HistoricalSourceLicenseAssessment(
                        status=HistoricalLicenseStatus.REQUIRES_COMMERCIAL_LICENSE,
                        terms_url=lseg,
                        automated_download=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        local_storage=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        derived_use=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        redistribution=HistoricalPermissionStatus.REQUIRES_WRITTEN_PERMISSION,
                        commercial_use=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        personal_research=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        caching=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        attribution_required=None,
                        unresolved_questions=(
                            "NSE field entitlements, raw-price mode, retained storage "
                            "and derived-output rights require a negotiated contract.",
                        ),
                        explanation=(
                            "Broad active/delisted identity and corporate-action "
                            "capability is documented."
                        ),
                    ),
                    credentials=("LSEG_DATASCOPE_USERNAME", "LSEG_DATASCOPE_PASSWORD"),
                    authentication="Commercial account and field entitlements",
                    rate_limit="Contract and entitlement dependent",
                    batch="REST, SFTP and bulk delivery",
                    cost="Institutional commercial quote required",
                    revision="Historical corrections and maintenance data documented",
                    risks=(
                        "high cost",
                        "third-party field entitlements",
                        "vendor dependency",
                    ),
                    recommendation=HistoricalSourceRecommendationStatus.IDENTITY_SOURCE_ONLY,
                    scores=(
                        85,
                        95,
                        0,
                        100,
                        100,
                        100,
                        70,
                        95,
                        95,
                        90,
                        80,
                        75,
                        50,
                        50,
                        0,
                        50,
                        55,
                    ),
                ),
                _provider(
                    provider_id="FACTSET_SYMBOLOGY",
                    name="FactSet Symbology API",
                    source_class=HistoricalSourceClass.SPECIALIST_INSTITUTIONAL_VENDOR,
                    documents=(
                        HistoricalSourceDocument("FactSet Symbology API", factset),
                    ),
                    supported={
                        "historical_symbol": factset,
                        "permanent_identifier": factset,
                        "symbol_change_history": factset,
                        "isin": factset,
                        "provenance": factset,
                    },
                    partial={
                        "listing_date": factset,
                        "delisting_date": factset,
                        "relisting_history": factset,
                    },
                    unsupported={
                        "daily_open": factset,
                        "daily_high": factset,
                        "daily_low": factset,
                        "daily_close": factset,
                        "daily_volume": factset,
                    },
                    license_assessment=HistoricalSourceLicenseAssessment(
                        status=HistoricalLicenseStatus.REQUIRES_COMMERCIAL_LICENSE,
                        terms_url="https://www.factset.com/third-party-terms",
                        automated_download=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        local_storage=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        derived_use=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        redistribution=HistoricalPermissionStatus.REQUIRES_WRITTEN_PERMISSION,
                        commercial_use=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        personal_research=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        caching=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
                        attribution_required=None,
                        unresolved_questions=(
                            "NSE-specific symbology entitlement and database rights "
                            "must be confirmed in a direct agreement.",
                        ),
                        explanation=(
                            "Effective-dated symbol history is documented; price "
                            "coverage is not evaluated here."
                        ),
                    ),
                    credentials=("FACTSET_USERNAME", "FACTSET_API_KEY"),
                    authentication="Commercial API entitlement",
                    rate_limit="Entitlement dependent",
                    batch="Identifier resolution API",
                    cost="Institutional commercial quote required",
                    revision="Symbology history with effective dates documented",
                    risks=("separate price source required", "third-party terms"),
                    recommendation=HistoricalSourceRecommendationStatus.IDENTITY_SOURCE_ONLY,
                    scores=(
                        80,
                        20,
                        0,
                        100,
                        90,
                        20,
                        50,
                        90,
                        90,
                        85,
                        75,
                        65,
                        50,
                        50,
                        0,
                        70,
                        65,
                    ),
                ),
            ),
            key=lambda item: item.provider_id,
        )
    )


def _price_capabilities(url: str) -> dict[str, str]:
    return {
        "daily_open": url,
        "daily_high": url,
        "daily_low": url,
        "daily_close": url,
        "daily_volume": url,
        "trading_date": url,
        "exchange_session": url,
    }


def _unknown_terms_license(explanation: str) -> HistoricalSourceLicenseAssessment:
    return HistoricalSourceLicenseAssessment(
        status=HistoricalLicenseStatus.TERMS_NOT_FOUND,
        terms_url=None,
        automated_download=HistoricalPermissionStatus.PERMITTED_WITH_CONDITIONS,
        local_storage=HistoricalPermissionStatus.UNKNOWN,
        derived_use=HistoricalPermissionStatus.UNKNOWN,
        redistribution=HistoricalPermissionStatus.UNKNOWN,
        commercial_use=HistoricalPermissionStatus.UNKNOWN,
        personal_research=HistoricalPermissionStatus.UNKNOWN,
        caching=HistoricalPermissionStatus.UNKNOWN,
        attribution_required=None,
        unresolved_questions=(
            "Obtain provider and exchange terms covering local retention, derived "
            "signals and internal production use.",
        ),
        explanation=explanation,
    )


_SCORE_DIMENSIONS = (
    "authority",
    "historical_depth",
    "candidate_coverage",
    "historical_identity",
    "delisted_security_coverage",
    "corporate_action_evidence",
    "point_in_time_suitability",
    "data_quality",
    "deterministic_reproducibility",
    "api_reliability",
    "rate_limit_practicality",
    "licensing_clarity",
    "storage_permission",
    "derived_use_permission",
    "cost",
    "implementation_complexity",
    "operational_dependency_risk",
)


def _provider(
    *,
    provider_id: str,
    name: str,
    source_class: HistoricalSourceClass,
    documents: tuple[HistoricalSourceDocument, ...],
    supported: Mapping[str, str],
    partial: Mapping[str, str],
    unsupported: Mapping[str, str],
    license_assessment: HistoricalSourceLicenseAssessment,
    credentials: tuple[str, ...],
    authentication: str,
    rate_limit: str,
    batch: str,
    cost: str,
    revision: str,
    risks: tuple[str, ...],
    recommendation: HistoricalSourceRecommendationStatus,
    scores: tuple[int, ...],
) -> HistoricalSourceCandidate:
    requirements = historical_source_requirements()
    capabilities = tuple(
        _capability(requirement.key, supported, partial, unsupported)
        for requirement in requirements
    )
    if len(scores) != len(_SCORE_DIMENSIONS):
        raise ValueError("provider scorecard dimension count mismatch")
    scorecard = tuple(
        HistoricalSourceDimensionScore(
            dimension=dimension,
            score=score,
            evidence_level=(
                HistoricalEvidenceLevel.UNKNOWN
                if dimension in {"candidate_coverage"}
                else HistoricalEvidenceLevel.DOCUMENTED
            ),
            explanation=(
                "No measured candidate coverage."
                if dimension == "candidate_coverage"
                else "Transparent documented-capability rubric; no aggregate score."
            ),
        )
        for dimension, score in zip(_SCORE_DIMENSIONS, scores, strict=True)
    )
    return HistoricalSourceCandidate(
        provider_id=provider_id,
        name=name,
        source_class=source_class,
        documents=documents,
        capabilities=capabilities,
        license_assessment=license_assessment,
        credential_environment_names=credentials,
        authentication_requirement=authentication,
        rate_limit=rate_limit,
        batch_capability=batch,
        cost_status=cost,
        revision_risk=revision,
        operational_risks=risks,
        recommendation_status=recommendation,
        scorecard=scorecard,
    )


def _capability(
    key: str,
    supported: Mapping[str, str],
    partial: Mapping[str, str],
    unsupported: Mapping[str, str],
) -> HistoricalSourceCapability:
    if key in supported:
        return HistoricalSourceCapability(
            requirement_key=key,
            status=HistoricalCapabilityStatus.SUPPORTED,
            evidence_level=HistoricalEvidenceLevel.DOCUMENTED,
            explanation="Official provider documentation supports this capability.",
            source_url=supported[key],
        )
    if key in partial:
        return HistoricalSourceCapability(
            requirement_key=key,
            status=HistoricalCapabilityStatus.PARTIAL,
            evidence_level=HistoricalEvidenceLevel.DOCUMENTED,
            explanation=(
                "Official documentation is relevant but does not prove "
                "full-population coverage."
            ),
            source_url=partial[key],
        )
    if key in unsupported:
        return HistoricalSourceCapability(
            requirement_key=key,
            status=HistoricalCapabilityStatus.UNSUPPORTED,
            evidence_level=HistoricalEvidenceLevel.DOCUMENTED,
            explanation=(
                "Official documentation does not provide this required capability."
            ),
            source_url=unsupported[key],
        )
    return HistoricalSourceCapability(
        requirement_key=key,
        status=HistoricalCapabilityStatus.UNKNOWN,
        evidence_level=HistoricalEvidenceLevel.UNKNOWN,
        explanation="No authoritative capability evidence was located.",
        source_url=None,
    )


def deterministic_historical_source_sample(
    manifest: HistoricalSourceEvaluationManifest,
    *,
    sample_size: int = 30,
) -> HistoricalSourceSampleManifest:
    if sample_size <= 0:
        raise ValueError("sample size must be positive")
    records = manifest.records
    selected: dict[str, HistoricalSourceEvaluationManifestRecord] = {}

    def add(record: HistoricalSourceEvaluationManifestRecord | None) -> None:
        if record is not None and len(selected) < min(sample_size, len(records)):
            selected.setdefault(record.candidate_id, record)

    if records:
        add(records[0])
        add(records[-1])
    for year in sorted({item.replay_year for item in records}):
        add(next((item for item in records if item.replay_year == year), None))
    for cause in BreakoutGapCause:
        add(next((item for item in records if item.gap_cause is cause), None))
    for value in sorted({item.setup_type or "UNAVAILABLE" for item in records}):
        add(
            next(
                (
                    item
                    for item in records
                    if (item.setup_type or "UNAVAILABLE") == value
                ),
                None,
            )
        )
    for value in sorted({item.market_regime or "UNAVAILABLE" for item in records}):
        add(
            next(
                (
                    item
                    for item in records
                    if (item.market_regime or "UNAVAILABLE") == value
                ),
                None,
            )
        )
    for value in sorted({item.continuity_status for item in records}):
        add(next((item for item in records if item.continuity_status == value), None))
    liquidity_rows = tuple(
        sorted(
            (item for item in records if item.liquidity_proxy is not None),
            key=lambda item: (
                item.liquidity_proxy,
                item.candidate_date,
                item.candidate_id,
            ),
        )
    )
    if liquidity_rows:
        add(liquidity_rows[0])
        add(liquidity_rows[-1])
    symbol_counts = Counter(item.historical_symbol for item in records)
    repeated = tuple(
        item for item in records if symbol_counts[item.historical_symbol] > 1
    )
    add(repeated[0] if repeated else None)
    for item in sorted(
        (row for row in records if row.replay_year == 2016),
        key=lambda row: (_stable_key(row.candidate_id), row.candidate_id),
    )[:10]:
        add(item)
    for item in sorted(
        records, key=lambda row: (_stable_key(row.candidate_id), row.candidate_id)
    ):
        add(item)
    sample_records = tuple(sorted(selected.values(), key=_manifest_record_sort_key))
    stratum_counts = tuple(
        sorted(Counter(f"year={item.replay_year}" for item in sample_records).items())
    ) + tuple(
        sorted(
            Counter(f"cause={item.gap_cause.value}" for item in sample_records).items()
        )
    )
    limitations = (
        "No effective-dated renamed-symbol labels exist in the current manifest; "
        "historical-symbol cases are retained but rename coverage cannot be sampled.",
        "SOURCE_CONTINUITY_ENDED_BEFORE_SOURCE_END is a continuity proxy, not proof "
        "of delisting.",
        "Sector is UNKNOWN for the missing population and cannot support "
        "stratification.",
        "Liquidity-proxy extremes are sampled, but the proxy does not establish "
        "large- or small-cap membership.",
        "A deterministic sample does not prove full-population coverage.",
    )
    checksum = _hash(tuple(_jsonable(item) for item in sample_records))
    return HistoricalSourceSampleManifest(
        sample_version=HISTORICAL_SOURCE_SAMPLE_VERSION,
        source_manifest_version=manifest.manifest_version,
        population_count=len(records),
        requested_sample_size=sample_size,
        records=sample_records,
        stratum_counts=stratum_counts,
        limitations=limitations,
        checksum=checksum,
    )


def filter_historical_source_manifest(
    records: Sequence[HistoricalSourceEvaluationManifestRecord],
    *,
    symbol: str | None = None,
    candidate_id: str | None = None,
    year: int | None = None,
    gap_cause: BreakoutGapCause | None = None,
) -> tuple[HistoricalSourceEvaluationManifestRecord, ...]:
    normalized_symbol = symbol.strip().upper() if symbol else None
    filtered = tuple(
        item
        for item in records
        if normalized_symbol is None or item.historical_symbol == normalized_symbol
        if candidate_id is None or item.candidate_id == candidate_id
        if year is None or item.replay_year == year
        if gap_cause is None or item.gap_cause is gap_cause
    )
    if candidate_id is not None and not filtered:
        raise ValueError(f"candidate id not found: {candidate_id}")
    return filtered


def parse_historical_source_provider(
    value: str,
    providers: Sequence[HistoricalSourceCandidate],
) -> str:
    normalized = value.strip().upper().replace("-", "_")
    allowed = {item.provider_id for item in providers}
    if normalized not in allowed:
        raise ValueError(
            f"unsupported historical source provider {value!r}; choose one of: "
            + ", ".join(sorted(allowed))
        )
    return normalized


def render_historical_source_requirements(
    requirements: Sequence[HistoricalSourceRequirement],
) -> tuple[str, ...]:
    counts = Counter(item.priority.value for item in requirements)
    return (
        "Historical Market Data Source Requirements",
        f"Requirements Version: {HISTORICAL_SOURCE_EVALUATION_VERSION}",
        "Priority Distribution: " + _counts(counts),
        "Existing Breakout Window: 121 completed daily bars ending at the "
        "existing point-in-time cutoff",
        "Adjustment Policy: RAW_UNADJUSTED",
        "Delivery Volume: NOT_REQUIRED; daily traded volume is MANDATORY",
        "Requirements:",
        *tuple(
            f"- {item.label}: {item.priority.value}; dependency "
            f"{item.existing_dependency}"
            for item in requirements
        ),
        "PRODUCTION_INFLUENCE=false",
    )


def render_historical_source_manifest(
    manifest: HistoricalSourceEvaluationManifest,
    sample: HistoricalSourceSampleManifest,
) -> tuple[str, ...]:
    causes = Counter(item.gap_cause.value for item in manifest.records)
    sample_causes = Counter(item.gap_cause.value for item in sample.records)
    return (
        "Historical Source Evaluation Manifest",
        f"Manifest Version: {manifest.manifest_version}",
        f"Manifest Checksum: {manifest.checksum}",
        f"Candidates: {len(manifest.records)}",
        f"Source Required: {manifest.source_required_count}",
        f"Recovery Uncertain: {manifest.recovery_uncertain_count}",
        f"Unique Historical Symbols: {manifest.unique_symbols}",
        "Required Date Range: "
        f"{_date_text(manifest.earliest_required_date)} to "
        f"{_date_text(manifest.latest_required_date)}",
        "Minimum Bars: 121 for every manifest record",
        "Gap Causes: " + _counts(causes),
        f"Deterministic Sample: {len(sample.records)}",
        f"Sample Checksum: {sample.checksum}",
        "Sample Gap Causes: " + _counts(sample_causes),
        *tuple(f"Limitation: {item}" for item in sample.limitations),
        "PRODUCTION_INFLUENCE=false",
    )


def render_historical_source_evaluation(
    report: HistoricalSourceRecommendationReport,
) -> tuple[str, ...]:
    rows = tuple(
        line
        for provider in report.providers
        for item in report.coverage_results
        if item.provider_id == provider.provider_id
        for line in (
            f"- {item.provider_id}: {item.evaluation_status.value}; evidence "
            f"{item.evidence_level.value}; observations {item.observations_received}/"
            f"{item.target_candidates}; mandatory gate "
            f"{'PASS' if item.mandatory_gate_passed else 'FAIL'}",
            "  documented capabilities: "
            + _counts(
                Counter(capability.status.value for capability in provider.capabilities)
            ),
            "  official documents: "
            + "; ".join(document.url for document in provider.documents),
        )
    )
    return (
        "Historical Source Provider Evaluation",
        f"Evaluation Version: {report.evaluation_version}",
        f"Target Missing Candidates: {report.total_missing_candidates_evaluated}",
        f"Providers Assessed: {report.providers_assessed}",
        f"Providers Empirically Sampled: {report.providers_sampled}",
        "Documented capability is not measured coverage.",
        *rows,
        "No provider response was fabricated and no production provider was added.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_historical_source_coverage(
    report: HistoricalSourceRecommendationReport,
) -> tuple[str, ...]:
    rows = tuple(
        line
        for item in report.coverage_results
        for line in (
            f"- {item.provider_id}: evidence={item.evidence_level.value}; "
            f"status={item.evaluation_status.value}; target={item.target_candidates}; "
            f"returned={_optional_int(item.candidates_returned)}; sufficient="
            f"{_optional_int(item.candidates_with_sufficient_lookback)}; symbols="
            f"{_optional_int(item.unique_symbols_covered)}; 2016="
            f"{_optional_int(item.candidate_2016_sufficient)}/"
            f"{item.candidate_2016_target}; projected-readiness="
            f"{_optional_pct(item.projected_reconstruction_readiness)}",
            "  identity: historical="
            f"{_optional_pct(item.historical_symbol_success_rate)}; renamed="
            f"{_optional_pct(item.renamed_symbol_success_rate)}; delisted="
            f"{_optional_pct(item.delisted_symbol_success_rate)}; corporate-actions="
            f"{_optional_pct(item.corporate_action_evidence_success_rate)}; "
            f"unresolved={_optional_int(item.unresolved_count)}",
            "  integrity: OHLC="
            f"{_optional_pct(item.ohlc_completeness_rate)}; volume="
            f"{_optional_pct(item.volume_completeness_rate)}; multi-session-gaps="
            f"{_optional_pct(item.multi_session_gap_rate)}; duplicates="
            f"{_optional_pct(item.duplicate_or_conflict_rate)}; timezone="
            f"{_optional_pct(item.timezone_consistency_rate)}; adjustment="
            f"{_optional_pct(item.adjustment_consistency_rate)}; covered="
            f"{_covered_date_range(item)}",
        )
    )
    return (
        "Historical Source Coverage Proof",
        f"Population: {report.total_missing_candidates_evaluated}",
        f"Source Required / Recovery Uncertain: "
        f"{report.source_required_candidates} / {report.recovery_uncertain_candidates}",
        "Observed Coverage:",
        *rows,
        "Projected Combined Readiness: unavailable; no approved full-population "
        "coverage exists.",
        "Projected Selection-Bias Reduction: "
        f"{report.projected_selection_bias_reduction}",
        "PRODUCTION_INFLUENCE=false",
    )


def render_historical_source_license_audit(
    report: HistoricalSourceRecommendationReport,
) -> tuple[str, ...]:
    rows = tuple(
        f"- {provider.provider_id}: {provider.license_assessment.status.value}; "
        f"automation={provider.license_assessment.automated_download.value}; "
        f"storage={provider.license_assessment.local_storage.value}; derived-use="
        f"{provider.license_assessment.derived_use.value}; caching="
        f"{provider.license_assessment.caching.value}; terms="
        f"{provider.license_assessment.terms_url or 'not found'}"
        for provider in report.providers
    )
    return (
        "Historical Source License and Permitted-Use Audit",
        f"Providers Assessed: {report.providers_assessed}",
        *rows,
        f"Overall Licensing Conclusion: {report.licensing_conclusion.value}",
        "This is an evidence classification, not legal advice.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_historical_source_recommendation(
    report: HistoricalSourceRecommendationReport,
) -> tuple[str, ...]:
    provider_rows = tuple(
        f"- {provider.provider_id}: {provider.recommendation_status.value}; "
        "candidate coverage="
        f"{_optional_int(coverage.candidates_with_sufficient_lookback)}"
        f"/{coverage.target_candidates}; symbol coverage="
        f"{_optional_int(coverage.unique_symbols_covered)}/{coverage.target_symbols}; "
        f"2016 coverage={_optional_int(coverage.candidate_2016_sufficient)}"
        f"/{coverage.candidate_2016_target}; renamed="
        f"{_optional_pct(coverage.renamed_symbol_success_rate)}; delisted="
        f"{_optional_pct(coverage.delisted_symbol_success_rate)}; corporate-actions="
        f"{_optional_pct(coverage.corporate_action_evidence_success_rate)}; "
        f"evidence={coverage.evidence_level.value}; license="
        f"{provider.license_assessment.status.value}"
        for provider, coverage in (
            (
                provider,
                next(
                    item
                    for item in report.coverage_results
                    if item.provider_id == provider.provider_id
                ),
            )
            for provider in report.providers
        )
    )
    return (
        "Authoritative Historical Source Recommendation",
        "Total Missing Candidates Evaluated: "
        f"{report.total_missing_candidates_evaluated}",
        f"Source Required Candidates: {report.source_required_candidates}",
        f"Recovery-Uncertain Candidates: {report.recovery_uncertain_candidates}",
        f"Providers Assessed: {report.providers_assessed}",
        f"Providers Sampled: {report.providers_sampled}",
        f"Providers Requiring Credentials: {report.providers_requiring_credentials}",
        "Providers Excluded for Licensing or Terms: "
        f"{report.providers_excluded_for_licensing_or_terms}",
        f"Best Price-History Source: {report.best_price_history_source}",
        f"Best Historical-Identity Source: {report.best_historical_identity_source}",
        f"Best Corporate-Action Source: {report.best_corporate_action_source}",
        "Best Exchange-Authoritative Source: "
        f"{report.best_exchange_authoritative_source}",
        "Provider Status:",
        *provider_rows,
        "Projected Readiness by Provider: unavailable without full-population "
        "observations and approved rights.",
        "Projected Readiness Using Approved Combination: unavailable",
        "Remaining Unresolved Candidates: unavailable",
        "Estimated Selection-Bias Reduction: "
        f"{report.projected_selection_bias_reduction}",
        f"Licensing Conclusion: {report.licensing_conclusion.value}",
        f"Operational-Risk Conclusion: {report.operational_risk_conclusion}",
        f"Recommended Architecture: {report.recommended_architecture}",
        f"Architecture Conclusion: {report.architecture_conclusion.value}",
        f"Next-Step Conclusion: {report.next_step_conclusion.value}",
        "No permanent provider, historical record, reconstruction, classifier, "
        "recommendation, approval, timing, stop, target, or production policy changed.",
        "PRODUCTION_INFLUENCE=false",
    )


def export_historical_source_json(payload: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def export_historical_source_csv(
    rows: Sequence[Mapping[str, object]],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = tuple(rows)
    fields = tuple(ordered[0].keys()) if ordered else ("status",)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ordered)


def requirement_csv_rows(
    requirements: Sequence[HistoricalSourceRequirement],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "key": item.key,
            "label": item.label,
            "priority": item.priority.value,
            "rationale": item.rationale,
            "existing_dependency": item.existing_dependency,
        }
        for item in requirements
    )


def manifest_csv_rows(
    records: Sequence[HistoricalSourceEvaluationManifestRecord],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "candidate_id": item.candidate_id,
            "candidate_date": item.candidate_date.isoformat(),
            "current_symbol": item.current_symbol,
            "historical_symbol": item.historical_symbol,
            "permanent_identifier": item.permanent_identifier,
            "required_start_date": item.required_start_date.isoformat(),
            "required_end_date": item.required_end_date.isoformat(),
            "minimum_bars_required": item.minimum_bars_required,
            "gap_cause": item.gap_cause.value,
            "corporate_action_requirement": item.corporate_action_requirement,
            "identity_uncertainty": item.identity_uncertainty,
            "recovery_population": item.recovery_population,
        }
        for item in records
    )


def coverage_csv_rows(
    results: Sequence[HistoricalSourceCoverageResult],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "provider_id": item.provider_id,
            "evidence_level": item.evidence_level.value,
            "evaluation_status": item.evaluation_status.value,
            "credential_status": item.credential_status.value,
            "target_candidates": item.target_candidates,
            "observations_received": item.observations_received,
            "candidate_2016_target": item.candidate_2016_target,
            "candidate_2016_returned": item.candidate_2016_returned,
            "candidate_2016_sufficient": item.candidate_2016_sufficient,
            "candidates_returned": item.candidates_returned,
            "sufficient_lookback": item.candidates_with_sufficient_lookback,
            "symbols_covered": item.unique_symbols_covered,
            "projected_readiness": item.projected_reconstruction_readiness,
            "mandatory_gate_passed": item.mandatory_gate_passed,
        }
        for item in results
    )


def license_csv_rows(
    providers: Sequence[HistoricalSourceCandidate],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "provider_id": item.provider_id,
            "license_status": item.license_assessment.status.value,
            "automated_download": item.license_assessment.automated_download.value,
            "local_storage": item.license_assessment.local_storage.value,
            "derived_use": item.license_assessment.derived_use.value,
            "redistribution": item.license_assessment.redistribution.value,
            "commercial_use": item.license_assessment.commercial_use.value,
            "caching": item.license_assessment.caching.value,
            "terms_url": item.license_assessment.terms_url,
        }
        for item in providers
    )


def _manifest_record_sort_key(
    item: HistoricalSourceEvaluationManifestRecord,
) -> tuple[date, str, str]:
    return item.candidate_date, item.historical_symbol, item.candidate_id


def _provider_preference(
    provider: HistoricalSourceCandidate,
) -> tuple[int, int, str]:
    source_order = {
        HistoricalSourceClass.EXCHANGE_LICENSED_DATA: 0,
        HistoricalSourceClass.EXCHANGE_PUBLIC_ARCHIVE: 1,
        HistoricalSourceClass.SPECIALIST_INSTITUTIONAL_VENDOR: 2,
        HistoricalSourceClass.AUTHORIZED_MARKET_DATA_VENDOR: 3,
        HistoricalSourceClass.BROKER_API: 4,
    }
    authority = next(
        (item.score for item in provider.scorecard if item.dimension == "authority"),
        0,
    )
    return source_order[provider.source_class], -authority, provider.provider_id


def _stable_key(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _optional_boolean_rate(
    rows: Sequence[HistoricalSourceObservation],
    extractor: Any,
) -> Decimal | None:
    if not rows:
        return None
    return _rate(sum(bool(extractor(item)) for item in rows), len(rows))


def _nullable_boolean_rate(
    rows: Sequence[HistoricalSourceObservation],
    extractor: Any,
) -> Decimal | None:
    values = tuple(value for item in rows if (value := extractor(item)) is not None)
    if not values:
        return None
    return _rate(sum(values), len(values))


def _rate(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return _ZERO
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _FOUR,
        rounding=ROUND_HALF_UP,
    )


def _counts(values: Counter[str]) -> str:
    if not values:
        return "none"
    return "; ".join(f"{key}={values[key]}" for key in sorted(values))


def _date_text(value: date | None) -> str:
    return value.isoformat() if value is not None else "unavailable"


def _covered_date_range(item: HistoricalSourceCoverageResult) -> str:
    if item.earliest_covered_candidate is None or item.latest_covered_candidate is None:
        return "unavailable"
    return (
        f"{item.earliest_covered_candidate.isoformat()} to "
        f"{item.latest_covered_candidate.isoformat()}"
    )


def _optional_int(value: int | None) -> str:
    return str(value) if value is not None else "unavailable"


def _optional_pct(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value * _HUNDRED:.2f}%"


def _hash(value: object) -> str:
    payload = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _jsonable(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, Decimal, StrEnum)):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = [
    "HISTORICAL_SOURCE_EVALUATION_VERSION",
    "HISTORICAL_SOURCE_MANIFEST_VERSION",
    "HISTORICAL_SOURCE_SAMPLE_VERSION",
    "PRODUCTION_INFLUENCE",
    "HistoricalArchitectureConclusion",
    "HistoricalCapabilityStatus",
    "HistoricalCredentialStatus",
    "HistoricalEvaluationStatus",
    "HistoricalEvidenceLevel",
    "HistoricalLicenseStatus",
    "HistoricalNextStepConclusion",
    "HistoricalPermissionStatus",
    "HistoricalRequirementPriority",
    "HistoricalSourceCandidate",
    "HistoricalSourceCapability",
    "HistoricalSourceClass",
    "HistoricalSourceCoverageResult",
    "HistoricalSourceCorporateActionResult",
    "HistoricalSourceDimensionScore",
    "HistoricalSourceDocument",
    "HistoricalSourceEvaluationEngine",
    "HistoricalSourceEvaluationManifest",
    "HistoricalSourceEvaluationManifestRecord",
    "HistoricalSourceLicenseAssessment",
    "HistoricalSourceIdentityResult",
    "HistoricalSourceObservation",
    "HistoricalSourceRecommendationReport",
    "HistoricalSourceRecommendationStatus",
    "HistoricalSourceRequirement",
    "HistoricalSourceSampleManifest",
    "build_historical_source_candidates",
    "coverage_csv_rows",
    "deterministic_historical_source_sample",
    "export_historical_source_csv",
    "export_historical_source_json",
    "filter_historical_source_manifest",
    "historical_source_requirements",
    "license_csv_rows",
    "manifest_csv_rows",
    "parse_historical_source_provider",
    "render_historical_source_coverage",
    "render_historical_source_evaluation",
    "render_historical_source_license_audit",
    "render_historical_source_manifest",
    "render_historical_source_recommendation",
    "render_historical_source_requirements",
    "requirement_csv_rows",
]
