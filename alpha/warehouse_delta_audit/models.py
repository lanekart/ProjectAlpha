"""Immutable domain models for the Warehouse Delta Audit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

WDA_VERSION = "WDA_v1.0"
BASELINE_ID = "ALPHA_BASELINE_v1.0"
DATA_PLATFORM_ID = "ALPHA_DATA_PLATFORM_v1.0"
PRODUCTION_INFLUENCE = False
NO_REPLAY_CHANGES = True
NO_GATE_CHANGES = True
NO_FEATURE_CHANGES = True
NO_WEIGHT_CHANGES = True

MANDATORY_SYMBOLS = (
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "LT",
    "TATASTEEL",
    "PCJEWELLER",
    "KALYANKJIL",
)


class SourceLineage(StrEnum):
    INDEPENDENT_OFFICIAL = "INDEPENDENT_OFFICIAL"
    LEGACY_LINEAGE_RAW_SOURCE = "LEGACY_LINEAGE_RAW_SOURCE"
    UNATTESTED_OFFICIAL_FORMAT = "UNATTESTED_OFFICIAL_FORMAT"
    UNKNOWN = "UNKNOWN"


class AuditStatus(StrEnum):
    COMPLETE = "COMPLETE"
    COMPLETE_SAME_LINEAGE_CONTROL = "COMPLETE_SAME_LINEAGE_CONTROL"
    INSUFFICIENT_PAIRED_EVIDENCE = "INSUFFICIENT_PAIRED_EVIDENCE"
    FAILED_CLOSED = "FAILED_CLOSED"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT = "INSUFFICIENT"


class DecisionSeverity(StrEnum):
    NO_CHANGE = "NO_CHANGE"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"
    CRITICAL = "CRITICAL"


class PurchaseRecommendation(StrEnum):
    PURCHASE_NOT_JUSTIFIED = "PURCHASE_NOT_JUSTIFIED"
    PURCHASE_JUSTIFIED = "PURCHASE_JUSTIFIED"
    PURCHASE_HIGH_PRIORITY = "PURCHASE_HIGH_PRIORITY"


class PersonalDecision(StrEnum):
    YES = "Yes"
    NO = "No"
    NOT_YET = "Not yet"


@dataclass(frozen=True, slots=True)
class DeltaThresholdPolicy:
    price_small_relative: Decimal = Decimal("0.0005")
    volume_small_relative: Decimal = Decimal("0.005")
    indicator_material_relative: Decimal = Decimal("0.0005")
    candidate_score_material: Decimal = Decimal("5")
    timing_shift_days: int = 7

    def __post_init__(self) -> None:
        for name in (
            "price_small_relative",
            "volume_small_relative",
            "indicator_material_relative",
            "candidate_score_material",
        ):
            if Decimal(getattr(self, name)) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.timing_shift_days < 1:
            raise ValueError("timing shift days must be positive")


@dataclass(frozen=True, slots=True)
class WarehouseDeltaRequest:
    legacy_database: str
    comparison_source: str
    output_directory: str
    sample_size: int = 500
    start: date | None = None
    end: date | None = None
    source_lineage: SourceLineage = SourceLineage.LEGACY_LINEAGE_RAW_SOURCE
    source_attestation: str | None = None
    thresholds: DeltaThresholdPolicy = DeltaThresholdPolicy()

    def __post_init__(self) -> None:
        if self.sample_size < len(MANDATORY_SYMBOLS):
            raise ValueError("sample size cannot exclude mandatory symbols")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("comparison end cannot precede start")
        if (
            self.source_lineage is SourceLineage.INDEPENDENT_OFFICIAL
            and not (self.source_attestation or "").strip()
        ):
            raise ValueError("independent official source requires an attestation")


@dataclass(frozen=True, slots=True)
class SampleProfile:
    requested_symbols: int
    selected_symbols: tuple[str, ...]
    mandatory_symbols_present: tuple[str, ...]
    mandatory_symbols_missing: tuple[str, ...]
    start: date
    end: date
    sessions: int
    source_files: int
    liquidity_high: int
    liquidity_medium: int
    liquidity_low: int
    sector_coverage: str
    market_cap_coverage: str

    @property
    def symbols(self) -> int:
        return len(self.selected_symbols)

    @property
    def spans_five_years(self) -> bool:
        return (self.end - self.start).days >= 365 * 5


@dataclass(frozen=True, slots=True)
class WarehouseDeltaManifest:
    audit_version: str
    baseline_id: str
    data_platform_id: str
    source_commit: str
    warehouse_version: str
    comparison_warehouse_version: str
    feature_version: str
    candidate_version: str
    policy_version: str
    baseline_manifest_hash: str
    data_platform_manifest_hash: str
    legacy_warehouse_hash: str
    comparison_source_hash: str
    sample_symbols_hash: str
    manifest_hash: str
    source_lineage: SourceLineage
    source_attestation: str | None
    production_influence: bool = False
    no_replay_changes: bool = True
    no_gate_changes: bool = True
    no_feature_changes: bool = True
    no_weight_changes: bool = True

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("WDA cannot influence production")
        if not all(
            (
                self.no_replay_changes,
                self.no_gate_changes,
                self.no_feature_changes,
                self.no_weight_changes,
            )
        ):
            raise ValueError("WDA guardrail flags must remain true")


@dataclass(frozen=True, slots=True)
class PriceDeltaRecord:
    symbol: str
    matched_observations: int
    exact_observations: int
    small_difference_observations: int
    large_difference_observations: int
    missing_from_comparison: int
    missing_from_legacy: int
    legacy_duplicate_observations: int
    comparison_duplicate_observations: int
    open_changed: int
    high_changed: int
    low_changed: int
    close_changed: int
    volume_changed: int
    maximum_close_relative_delta: Decimal | None
    maximum_volume_relative_delta: Decimal | None
    legacy_invalid_observations: int = 0
    comparison_invalid_observations: int = 0


@dataclass(frozen=True, slots=True)
class IndicatorDeltaRecord:
    symbol: str
    indicator: str
    compared_observations: int
    identical_observations: int
    minor_changes: int
    material_changes: int
    signal_changes: int
    maximum_relative_delta: Decimal | None


@dataclass(frozen=True, slots=True)
class CandidateDeltaRecord:
    symbol: str
    candidate_on_both: int
    candidate_only_legacy: int
    candidate_only_comparison: int
    timing_shifted: int
    score_shifted: int
    average_absolute_score_shift: Decimal | None
    maximum_absolute_score_shift: Decimal | None


@dataclass(frozen=True, slots=True)
class DecisionDeltaRecord:
    observed_on: date
    symbol: str
    legacy_score: Decimal | None
    comparison_score: Decimal | None
    legacy_approved: bool | None
    comparison_approved: bool | None
    legacy_reason: str
    comparison_reason: str
    severity: DecisionSeverity
    explanation: str


@dataclass(frozen=True, slots=True)
class ReplayDeltaRecord:
    metric: str
    legacy_value: Decimal | None
    comparison_value: Decimal | None
    delta: Decimal | None
    unit: str
    interpretation: str


@dataclass(frozen=True, slots=True)
class CorporateActionDeltaRecord:
    event_type: str
    legacy_events: int | None
    comparison_events: int | None
    indicator_changing_events: int | None
    replay_changing_events: int | None
    status: str
    explanation: str


@dataclass(frozen=True, slots=True)
class ValueAttributionRecord:
    source: str
    observable_changes: int | None
    decision_changes: int | None
    replay_effect: str
    confidence: ConfidenceLevel
    explanation: str


@dataclass(frozen=True, slots=True)
class WarehouseDeltaReport:
    manifest: WarehouseDeltaManifest
    sample: SampleProfile
    status: AuditStatus
    price_deltas: tuple[PriceDeltaRecord, ...]
    indicator_deltas: tuple[IndicatorDeltaRecord, ...]
    candidate_deltas: tuple[CandidateDeltaRecord, ...]
    decision_deltas: tuple[DecisionDeltaRecord, ...]
    replay_deltas: tuple[ReplayDeltaRecord, ...]
    corporate_action_deltas: tuple[CorporateActionDeltaRecord, ...]
    value_attribution: tuple[ValueAttributionRecord, ...]
    purchase_recommendation: PurchaseRecommendation
    personal_decision: PersonalDecision
    estimated_alpha_improvement: str
    confidence: ConfidenceLevel
    recommendation_reason: str
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.manifest.production_influence:
            raise ValueError("WDA report cannot influence production")

    @property
    def material_decisions(self) -> int:
        return sum(
            item.severity in {DecisionSeverity.MATERIAL, DecisionSeverity.CRITICAL}
            for item in self.decision_deltas
        )

    @property
    def critical_decisions(self) -> int:
        return sum(
            item.severity is DecisionSeverity.CRITICAL for item in self.decision_deltas
        )


__all__ = [
    "AuditStatus",
    "BASELINE_ID",
    "ConfidenceLevel",
    "CorporateActionDeltaRecord",
    "CandidateDeltaRecord",
    "DATA_PLATFORM_ID",
    "DecisionDeltaRecord",
    "DecisionSeverity",
    "DeltaThresholdPolicy",
    "IndicatorDeltaRecord",
    "MANDATORY_SYMBOLS",
    "PersonalDecision",
    "PriceDeltaRecord",
    "PurchaseRecommendation",
    "ReplayDeltaRecord",
    "SampleProfile",
    "SourceLineage",
    "ValueAttributionRecord",
    "WarehouseDeltaManifest",
    "WarehouseDeltaReport",
    "WarehouseDeltaRequest",
]
