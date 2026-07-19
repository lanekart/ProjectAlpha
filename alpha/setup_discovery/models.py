from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

PRODUCTION_INFLUENCE = False
SDE_VERSION = "setup-discovery-evidence-v1.0"
SDE_POLICY_ID = "SDE_RESEARCH_v1.0"
CANONICAL_LOOKBACK = 60
EXPANDED_LOOKBACKS = (90, 120, 160, 200)


class EvidencePartition(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"


class GeometryState(StrEnum):
    FLAT = "FLAT"
    ASCENDING = "ASCENDING"
    CONTRACTING = "CONTRACTING"
    REVERSAL = "REVERSAL"
    IRREGULAR = "IRREGULAR"


class LookbackProofStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    REJECTED_CANONICAL_WINDOW_SUFFICIENT = "REJECTED_CANONICAL_WINDOW_SUFFICIENT"
    REJECTED_NO_EXPANDED_LOOKBACK_PROOF = "REJECTED_NO_EXPANDED_LOOKBACK_PROOF"
    REJECTED_ENTRY_TOO_EXTENDED = "REJECTED_ENTRY_TOO_EXTENDED"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"


class VocabularyClassification(StrEnum):
    EXISTING_CANONICAL_SETUP = "EXISTING_CANONICAL_SETUP"
    CANONICAL_VARIANT = "CANONICAL_VARIANT"
    NEW_ARCHETYPE = "NEW_ARCHETYPE"
    AMBIGUOUS = "AMBIGUOUS"
    DISCARD = "DISCARD"


class ResearchRecommendation(StrEnum):
    INTRODUCE_AS_RESEARCH_SETUP = "INTRODUCE_AS_RESEARCH_SETUP"
    EXTEND_CANONICAL_IN_RESEARCH = "EXTEND_CANONICAL_IN_RESEARCH"
    RESEARCH_FURTHER = "RESEARCH_FURTHER"
    DO_NOT_INTRODUCE = "DO_NOT_INTRODUCE"


@dataclass(frozen=True, slots=True)
class SetupDiscoveryManifest:
    policy_id: str
    parent_policy_id: str
    source_audit_id: str
    dataset_version: str
    feature_version: str
    clustering_version: str
    lookback_version: str
    canonical_lookback: int
    expanded_lookbacks: tuple[int, ...]
    cluster_bounds: tuple[int, int]
    outcomes_excluded_from_clustering: bool
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("setup discovery cannot influence production")
        if not self.outcomes_excluded_from_clustering:
            raise ValueError("setup clustering must exclude outcomes")
        object.__setattr__(self, "expanded_lookbacks", tuple(self.expanded_lookbacks))


@dataclass(frozen=True, slots=True)
class RawMissedSetupCase:
    case_id: str
    event_id: str
    onset_id: str
    symbol: str
    onset_date: date
    onset_sequence: int
    event_family: str
    failure_reason: str
    entry_trigger: Decimal
    prospective_stop: Decimal
    prospective_target: Decimal
    prospective_rr: Decimal
    onset_confidence: Decimal
    point_in_time_inputs: Mapping[str, str]
    forward_return: Decimal
    event_holding_period: int
    event_start_date: date
    event_peak_date: date

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(
            self,
            "point_in_time_inputs",
            MappingProxyType(dict(sorted(self.point_in_time_inputs.items()))),
        )


@dataclass(frozen=True, slots=True)
class SetupFeatureRecord:
    case_id: str
    event_id: str
    onset_id: str
    symbol: str
    onset_date: date
    event_family: str
    failure_reason: str
    base_duration: int
    base_depth: Decimal
    volatility_contraction: Decimal | None
    moving_average_alignment: Decimal | None
    relative_strength_trend: Decimal | None
    breakout_angle: Decimal
    breakout_volume: Decimal | None
    atr_expansion: Decimal | None
    trend_slope: Decimal
    consolidation_geometry: GeometryState
    liquidity_profile: Decimal | None
    prospective_rr: Decimal
    onset_confidence: Decimal
    forward_return: Decimal
    holding_period: int
    net_return_60: Decimal | None
    partition: EvidencePartition
    feature_hash: str

    def cluster_vector(self) -> tuple[Decimal | None, ...]:
        """Return point-in-time features only; outcomes are intentionally absent."""
        geometry = tuple(
            Decimal("1") if self.consolidation_geometry is item else Decimal("0")
            for item in GeometryState
        )
        return (
            Decimal(self.base_duration),
            self.base_depth,
            self.volatility_contraction,
            self.moving_average_alignment,
            self.relative_strength_trend,
            self.breakout_angle,
            self.breakout_volume,
            self.atr_expansion,
            self.trend_slope,
            self.liquidity_profile,
            *geometry,
        )


@dataclass(frozen=True, slots=True)
class SetupCluster:
    cluster_id: str
    family_name: str
    occurrences: int
    unsupported_case_share: Decimal
    dominant_event_family: str
    family_purity: Decimal
    representative_symbols: tuple[str, ...]
    representative_case_ids: tuple[str, ...]
    representative_chart_pages: tuple[int, ...]
    average_reward_risk: Decimal
    median_holding_period: Decimal
    average_forward_outcome: Decimal
    average_net_return_60: Decimal | None
    distinct_archetype_confidence: Decimal
    development_expectancy: Decimal | None
    validation_expectancy: Decimal | None
    holdout_expectancy: Decimal | None
    cross_partition_stability: str
    candidate_explosion_risk: str
    feature_centroid: Mapping[str, str]

    def __post_init__(self) -> None:
        for name in (
            "representative_symbols",
            "representative_case_ids",
            "representative_chart_pages",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(
            self,
            "feature_centroid",
            MappingProxyType(dict(sorted(self.feature_centroid.items()))),
        )


@dataclass(frozen=True, slots=True)
class LookbackEvidence:
    case_id: str
    event_id: str
    onset_id: str
    symbol: str
    event_family: str
    onset_date: date
    canonical_lookback: int
    canonical_setup_detected: bool
    minimum_visible_lookback: int | None
    first_detectable_date: date | None
    expanded_candidate_date: date | None
    additional_bars_required: int | None
    entry_extension: Decimal | None
    extension_acceptable: bool | None
    window_results: Mapping[str, str]
    status: LookbackProofStatus
    classification_retained: bool
    difference_explained: str
    evidence_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "window_results",
            MappingProxyType(dict(sorted(self.window_results.items()))),
        )


@dataclass(frozen=True, slots=True)
class TopMissedOpportunity:
    rank: int
    case_id: str
    symbol: str
    onset_date: date
    event_family: str
    cluster_id: str | None
    cluster_name: str
    canonical_detection_state: str
    unsupported_pattern_description: str
    canonical_lookback: int
    required_lookback: int | None
    prospective_rr: Decimal
    candidate_blocker: str
    classification_confidence: Decimal
    forward_outcome: Decimal
    evidence_book_page: int


@dataclass(frozen=True, slots=True)
class SetupFamilyCatalogEntry:
    cluster_id: str
    family_name: str
    classification: VocabularyClassification
    closest_canonical_setup: str | None
    occurrences_explained: int
    unsupported_case_share: Decimal
    average_expectancy: Decimal | None
    average_reward_risk: Decimal
    stability: str
    candidate_explosion_risk: str
    evidence_strength: str
    rationale: str


@dataclass(frozen=True, slots=True)
class SetupRecommendationRecord:
    cluster_id: str
    family_name: str
    recommendation: ResearchRecommendation
    evidence_strength: str
    risk: str
    reason: str
    production_eligible: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_eligible:
            raise ValueError("SDE recommendations cannot be production eligible")


@dataclass(frozen=True, slots=True)
class ChartBar:
    observed_on: date
    close: Decimal
    volume: Decimal
    ema_20: Decimal | None
    ema_50: Decimal | None


@dataclass(frozen=True, slots=True)
class EvidenceChart:
    case_id: str
    symbol: str
    onset_date: date
    bars: tuple[ChartBar, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bars", tuple(self.bars))
        if any(item.observed_on > self.onset_date for item in self.bars):
            raise ValueError("evidence chart cannot contain post-onset bars")


@dataclass(frozen=True, slots=True)
class SetupDiscoverySummary:
    unsupported_cases: int
    unsupported_cases_clustered: int
    unsupported_cases_unclustered: int
    lookback_cases_claimed: int
    lookback_cases_confirmed: int
    lookback_cases_rejected: int
    lookback_cases_data_insufficient: int
    clusters_selected: int
    top_three_clusters: tuple[str, ...]
    top_three_case_share: Decimal
    strongest_research_family: str
    families_not_to_add: tuple[str, ...]
    overall_evidence_confidence: str


@dataclass(frozen=True, slots=True)
class SetupDiscoveryReport:
    report_id: str
    generated_at: datetime
    manifest: SetupDiscoveryManifest
    features: tuple[SetupFeatureRecord, ...]
    clusters: tuple[SetupCluster, ...]
    lookback_evidence: tuple[LookbackEvidence, ...]
    top_opportunities: tuple[TopMissedOpportunity, ...]
    charts: tuple[EvidenceChart, ...]
    catalog: tuple[SetupFamilyCatalogEntry, ...]
    recommendations: tuple[SetupRecommendationRecord, ...]
    kalyan_deep_dive: str
    pcjeweller_deep_dive: str
    summary: SetupDiscoverySummary
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("SDE report cannot influence production")
        for name in (
            "features",
            "clusters",
            "lookback_evidence",
            "top_opportunities",
            "charts",
            "catalog",
            "recommendations",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))


def to_primitive(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_primitive(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: to_primitive(getattr(value, item.name)) for item in fields(value)
        }
    return value


__all__ = [
    "CANONICAL_LOOKBACK",
    "EXPANDED_LOOKBACKS",
    "PRODUCTION_INFLUENCE",
    "SDE_POLICY_ID",
    "SDE_VERSION",
    "ChartBar",
    "EvidenceChart",
    "EvidencePartition",
    "GeometryState",
    "LookbackEvidence",
    "LookbackProofStatus",
    "RawMissedSetupCase",
    "ResearchRecommendation",
    "SetupCluster",
    "SetupDiscoveryManifest",
    "SetupDiscoveryReport",
    "SetupDiscoverySummary",
    "SetupFamilyCatalogEntry",
    "SetupFeatureRecord",
    "SetupRecommendationRecord",
    "TopMissedOpportunity",
    "VocabularyClassification",
    "to_primitive",
]
