"""Immutable contracts for HTR-010A1 population and interval repair."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Any

HTR010A1_CONTRACT_VERSION = "HTR-010A1-v1.0.0"
SUPPORT_POLICY_VERSION = "NSE-CM-SUPPORT-v1.0.0"
PRODUCTION_INFLUENCE = False


class InstrumentType(StrEnum):
    MAINBOARD_EQUITY = "MAINBOARD_EQUITY"
    TRADE_FOR_TRADE_EQUITY = "TRADE_FOR_TRADE_EQUITY"
    SME_EQUITY = "SME_EQUITY"
    SME_TRADE_FOR_TRADE = "SME_TRADE_FOR_TRADE"
    SUSPENDED_EQUITY = "SUSPENDED_EQUITY"
    RELISTED_EQUITY = "RELISTED_EQUITY"
    ETF = "ETF"
    MUTUAL_FUND_UNIT = "MUTUAL_FUND_UNIT"
    REIT = "REIT"
    INVIT = "INVIT"
    PREFERENCE_SHARE = "PREFERENCE_SHARE"
    PARTLY_PAID_EQUITY = "PARTLY_PAID_EQUITY"
    RIGHTS_ENTITLEMENT = "RIGHTS_ENTITLEMENT"
    WARRANT = "WARRANT"
    GOVERNMENT_SECURITY = "GOVERNMENT_SECURITY"
    CORPORATE_DEBT = "CORPORATE_DEBT"
    SECURITISED_DEBT = "SECURITISED_DEBT"
    SOVEREIGN_GOLD_BOND = "SOVEREIGN_GOLD_BOND"
    MUNICIPAL_DEBT = "MUNICIPAL_DEBT"
    INTEREST_RATE_INSTRUMENT = "INTEREST_RATE_INSTRUMENT"
    TEMPORARY_OR_AUCTION_SERIES = "TEMPORARY_OR_AUCTION_SERIES"
    TEST_OR_ADMINISTRATIVE_RECORD = "TEST_OR_ADMINISTRATIVE_RECORD"
    UNKNOWN_SECURITY_TYPE = "UNKNOWN_SECURITY_TYPE"


class SupportState(StrEnum):
    TIER_A_CORE_EQUITY = "TIER_A_CORE_EQUITY"
    SUPPORTED_EQUITY_NON_CORE = "SUPPORTED_EQUITY_NON_CORE"
    SUPPORTED_SEPARATE_ASSET_CLASS = "SUPPORTED_SEPARATE_ASSET_CLASS"
    PRESERVED_UNSUPPORTED = "PRESERVED_UNSUPPORTED"
    UNKNOWN_CLASSIFICATION = "UNKNOWN_CLASSIFICATION"
    CONFLICTING_CLASSIFICATION = "CONFLICTING_CLASSIFICATION"


class BoundaryState(StrEnum):
    OFFICIAL_EXACT = "OFFICIAL_EXACT"
    GOVERNED_LOWER_BOUND = "GOVERNED_LOWER_BOUND"
    GOVERNED_UPPER_BOUND = "GOVERNED_UPPER_BOUND"
    ACTIVE_FINAL_CHECKPOINT = "ACTIVE_FINAL_CHECKPOINT"
    INACTIVE_CHECKPOINT = "INACTIVE_CHECKPOINT"
    FIRST_CHECKPOINT_OBSERVATION = "FIRST_CHECKPOINT_OBSERVATION"
    FIRST_CANDLE_OBSERVATION = "FIRST_CANDLE_OBSERVATION"
    PROBABLE_CESSATION_NOT_CERTIFIED = "PROBABLE_CESSATION_NOT_CERTIFIED"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    UNKNOWN = "UNKNOWN"


class OverlapClassification(StrEnum):
    DUPLICATE_EVIDENCE = "DUPLICATE_EVIDENCE"
    DUPLICATE_RECONSTRUCTED_INTERVAL = "DUPLICATE_RECONSTRUCTED_INTERVAL"
    SYMBOL_REUSE_DIFFERENT_ISIN = "SYMBOL_REUSE_DIFFERENT_ISIN"
    SERIES_OVERLAP_SAME_IDENTITY = "SERIES_OVERLAP_SAME_IDENTITY"
    LEGITIMATE_PARALLEL_SERIES = "LEGITIMATE_PARALLEL_SERIES"
    PREDECESSOR_SUCCESSOR_TRANSITION = "PREDECESSOR_SUCCESSOR_TRANSITION"
    RELISTING = "RELISTING"
    CORPORATE_REORGANISATION = "CORPORATE_REORGANISATION"
    CURRENT_MASTER_BACKFILL_ERROR = "CURRENT_MASTER_BACKFILL_ERROR"
    SYNTHETIC_IDENTITY_COLLISION = "SYNTHETIC_IDENTITY_COLLISION"
    CONFLICTING_OFFICIAL_EVIDENCE = "CONFLICTING_OFFICIAL_EVIDENCE"
    UNRESOLVED = "UNRESOLVED"


class GapClassification(StrEnum):
    SUSPENSION = "SUSPENSION"
    SERIES_TRANSITION = "SERIES_TRANSITION"
    SYMBOL_TRANSITION = "SYMBOL_TRANSITION"
    TEMPORARY_CESSATION = "TEMPORARY_CESSATION"
    CORPORATE_REORGANISATION = "CORPORATE_REORGANISATION"
    MISSING_CHECKPOINT = "MISSING_CHECKPOINT"
    SOURCE_ACQUISITION_GAP = "SOURCE_ACQUISITION_GAP"
    ARCHIVE_ABSENCE = "ARCHIVE_ABSENCE"
    RECONSTRUCTION_BUG = "RECONSTRUCTION_BUG"
    LEGITIMATE_INTERVAL_GAP = "LEGITIMATE_INTERVAL_GAP"
    UNRESOLVED = "UNRESOLVED"


class RepairAction(StrEnum):
    MERGED = "MERGED"
    SPLIT = "SPLIT"
    RETAINED_PARALLEL = "RETAINED_PARALLEL"
    RETAINED_CONFLICTING = "RETAINED_CONFLICTING"
    EXCLUDED_FROM_SUPPORTED_DENOMINATOR = "EXCLUDED_FROM_SUPPORTED_DENOMINATOR"
    NO_CHANGE = "NO_CHANGE"


class CertificationState(StrEnum):
    TIER_A_CERTIFIED = "TIER_A_CERTIFIED"
    TIER_A_MEMBERSHIP_PARTIAL = "TIER_A_MEMBERSHIP_PARTIAL"
    TIER_A_TRADABILITY_PARTIAL = "TIER_A_TRADABILITY_PARTIAL"
    IDENTITY_CERTIFIED_INTERVAL_CONFLICT = "IDENTITY_CERTIFIED_INTERVAL_CONFLICT"
    IDENTITY_PARTIAL = "IDENTITY_PARTIAL"
    UNRESOLVED = "UNRESOLVED"
    CONFLICTING = "CONFLICTING"
    PRESERVED_UNSUPPORTED = "PRESERVED_UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class InstrumentTaxonomyRecord:
    identity_key: str
    exchange: str
    symbol: str
    series: str
    isin: str | None
    security_name: str | None
    official_security_type: str | None
    official_instrument_type: str | None
    instrument_type: InstrumentType
    valid_from: date | None
    valid_to: date | None
    source_id: str
    source_path: str
    source_sha256: str
    classification_reason: str
    confidence: str
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SupportPolicyRecord:
    identity_key: str
    symbol: str
    series: str
    instrument_type: InstrumentType
    support_state: SupportState
    valid_from: date | None
    valid_to: date | None
    policy_version: str
    classification_reason: str
    confidence: str
    conflicts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CensusReconciliationRecord:
    dimension: str
    value: str
    source_records: int
    distinct_identities: int
    distinct_symbols: int
    candle_records: int
    master_only_records: int
    duplicate_records: int


@dataclass(frozen=True, slots=True)
class IdentityDenominatorRecord:
    identity_key: str
    support_state: SupportState
    earliest_possible_membership: date | None
    official_listing_date: date | None
    earliest_official_observation: date | None
    first_canonical_candle: date | None
    termination_date: date | None
    last_official_active_checkpoint: date | None
    last_canonical_candle: date | None
    currently_active: bool | None
    interval_state: str
    expected_identity_days: int
    certified_identity_days: int
    provisional_identity_days: int
    unresolved_identity_days: int
    boundary_issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntervalConflictRecord:
    conflict_id: str
    identity_key: str
    attribute: str
    left_value: str
    right_value: str
    overlap_start: date
    overlap_end: date
    classification: OverlapClassification
    repair_action: RepairAction
    left_source_event_ids: tuple[str, ...]
    right_source_event_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntervalRepairRecord:
    repair_id: str
    identity_key: str
    attribute: str
    value: str
    before_intervals: tuple[str, ...]
    repaired_from: date
    repaired_to: date
    action: RepairAction
    classification: str
    source_lineage: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntervalGapRecord:
    gap_id: str
    identity_key: str
    attribute: str
    left_value: str
    right_value: str
    gap_start: date
    gap_end: date
    gap_days: int
    classification: GapClassification
    repair_action: RepairAction
    evidence_source_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BoundaryEvidenceRecord:
    identity_key: str
    boundary_type: str
    boundary_date: date | None
    boundary_state: BoundaryState
    source_id: str | None
    source_path: str | None
    confidence: str
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SuspensionEvidenceRecord:
    identity_key: str | None
    symbol: str | None
    suspension_date: date | None
    restoration_date: date | None
    evidence_type: str
    source_id: str
    source_url: str
    source_path: str | None
    source_sha256: str | None
    status: str
    failure_code: str | None
    failure_detail: str | None


@dataclass(frozen=True, slots=True)
class CheckpointReconciliationRecord:
    checkpoint_date: date
    support_state: SupportState
    expected_active_identities: int
    reconstructed_active_identities: int
    master_active_identities: int
    missing_identities: int
    unexpected_identities: int
    symbol_mismatches: int
    series_mismatches: int
    isin_mismatches: int
    security_type_mismatches: int
    source_id: str


@dataclass(frozen=True, slots=True)
class UniverseReconciliationRecord:
    as_of_date: date
    support_state: SupportState
    active_identities: int
    distinct_symbols: int
    duplicate_series_records: int
    official_checkpoint_identities: int
    provisional_identities: int
    unresolved_identities: int
    explanation: str


@dataclass(frozen=True, slots=True)
class TierCandleReconciliationRecord:
    support_state: SupportState
    reconciliation_state: str
    row_count: int
    distinct_identities: int
    first_date: date | None
    last_date: date | None


@dataclass(frozen=True, slots=True)
class TierContinuityRecord:
    support_state: SupportState
    expected_sessions: int
    observed_sessions: int
    pre_listing_exclusions: int
    post_termination_exclusions: int
    suspension_exclusions: int
    unsupported_population_exclusions: int
    archive_absences: int
    validation_rejections: int
    identity_resolution_failures: int
    explained_missing: int
    unexplained_missing: int
    identities_with_unexplained_gaps: int


@dataclass(frozen=True, slots=True)
class SupportedSecurityCertification:
    identity_key: str
    support_state: SupportState
    instrument_type: InstrumentType
    listing_coverage: str
    termination_or_active_coverage: str
    symbol_history_coverage: str
    series_history_coverage: str
    membership_coverage: str
    tradability_coverage: str
    interval_conflicts: int
    interval_gaps: int
    certification_state: CertificationState
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PopulationRepairSummary:
    htr008_raw_symbols: int
    htr010a_raw_symbols: int
    corrected_identities: int
    duplicate_identity_records: int
    tier_a_identities: int
    supported_non_core_identities: int
    separate_asset_class_identities: int
    preserved_unsupported_identities: int
    unknown_classification_identities: int
    conflicting_classification_identities: int
    master_only_identities: int
    candle_only_identities: int


@dataclass(frozen=True, slots=True)
class RepairSummary:
    overlaps_classified: int
    duplicate_overlaps_repaired: int
    legitimate_overlaps_retained: int
    unresolved_overlaps: int
    gaps_classified: int
    gaps_repaired: int
    unresolved_gaps: int
    symbol_reuse_resolved: int
    symbol_reuse_unresolved: int


@dataclass(frozen=True, slots=True)
class DenominatorSummary:
    support_state: SupportState
    identities: int
    expected_identity_days: int
    certified_identity_days: int
    provisional_identity_days: int
    unresolved_identity_days: int


@dataclass(frozen=True, slots=True)
class PopulationRepairCertification:
    primary_state: str
    tier_a_ready_for_htr010b: bool
    readiness_decision: str
    secondary_blockers: tuple[str, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class SecurityPopulationRepairReport:
    contract_version: str
    support_policy_version: str
    production_influence: bool
    database_path: str
    start_date: date
    end_date: date
    taxonomy: tuple[InstrumentTaxonomyRecord, ...]
    support_policy: tuple[SupportPolicyRecord, ...]
    census_reconciliation: tuple[CensusReconciliationRecord, ...]
    denominator_audit: tuple[IdentityDenominatorRecord, ...]
    interval_overlaps: tuple[IntervalConflictRecord, ...]
    interval_repairs: tuple[IntervalRepairRecord, ...]
    interval_gaps: tuple[IntervalGapRecord, ...]
    symbol_reuse: tuple[dict[str, Any], ...]
    listing_boundaries: tuple[BoundaryEvidenceRecord, ...]
    termination_boundaries: tuple[BoundaryEvidenceRecord, ...]
    suspension_evidence: tuple[SuspensionEvidenceRecord, ...]
    checkpoint_reconciliation: tuple[CheckpointReconciliationRecord, ...]
    universe_2026: tuple[UniverseReconciliationRecord, ...]
    candle_reconciliation: tuple[TierCandleReconciliationRecord, ...]
    continuity: tuple[TierContinuityRecord, ...]
    certification_matrix: tuple[SupportedSecurityCertification, ...]
    rejected_evidence: tuple[dict[str, Any], ...]
    population_summary: PopulationRepairSummary
    repair_summary: RepairSummary
    denominator_summary: tuple[DenominatorSummary, ...]
    certification: PopulationRepairCertification
    source_checksums: tuple[tuple[str, str], ...]
    report_sha256: str

    def payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        raw = _jsonable(asdict(self))
        if not isinstance(raw, dict):
            raise TypeError("HTR-010A1 report must serialize to an object")
        if not include_hash:
            raw["report_sha256"] = ""
        return raw

    def calculated_sha256(self) -> str:
        encoded = json.dumps(
            self.payload(include_hash=False),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return sha256(encoded).hexdigest()


def stable_record_id(prefix: str, *values: object) -> str:
    material = "|".join(str(value or "").upper() for value in values)
    return f"{prefix}:{sha256(material.encode()).hexdigest()}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


__all__ = [
    "BoundaryEvidenceRecord",
    "BoundaryState",
    "CensusReconciliationRecord",
    "CertificationState",
    "CheckpointReconciliationRecord",
    "DenominatorSummary",
    "GapClassification",
    "HTR010A1_CONTRACT_VERSION",
    "IdentityDenominatorRecord",
    "InstrumentTaxonomyRecord",
    "InstrumentType",
    "IntervalConflictRecord",
    "IntervalGapRecord",
    "IntervalRepairRecord",
    "PRODUCTION_INFLUENCE",
    "PopulationRepairCertification",
    "PopulationRepairSummary",
    "RepairAction",
    "RepairSummary",
    "SUPPORT_POLICY_VERSION",
    "SecurityPopulationRepairReport",
    "SupportPolicyRecord",
    "SupportState",
    "SupportedSecurityCertification",
    "SuspensionEvidenceRecord",
    "TierCandleReconciliationRecord",
    "TierContinuityRecord",
    "UniverseReconciliationRecord",
    "stable_record_id",
]
