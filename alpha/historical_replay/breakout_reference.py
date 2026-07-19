from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import Any, cast
from zoneinfo import ZoneInfo

from alpha.historical_replay.precision_frontier import DirectionalObservation

BREAKOUT_REFERENCE_DATASET_VERSION = "breakout_reference_dataset_v1"
BREAKOUT_REFERENCE_SCHEMA_VERSION = "breakout-reference-record-v1"
BREAKOUT_REFERENCE_ALGORITHM_VERSION = "point-in-time-breakout-reference-v1"
DEFAULT_BREAKOUT_REFERENCE_PATH = Path(".alpha/breakout_reference_dataset_v1.json")
INDIA_TIMEZONE = "Asia/Kolkata"
PRODUCTION_INFLUENCE = False

_IST = ZoneInfo(INDIA_TIMEZONE)
_MARKET_OPEN = time(9, 15)
_MARKET_CLOSE = time(15, 30)
_FOUR = Decimal("0.0001")
_SIX = Decimal("0.000001")
_HUNDRED = Decimal("100")
_ZERO = Decimal("0")


class BreakoutReferenceMethod(StrEnum):
    PRIOR_SWING_HIGH = "PRIOR_SWING_HIGH"
    RANGE_RESISTANCE = "RANGE_RESISTANCE"
    ROLLING_HIGH = "ROLLING_HIGH"


class BreakoutReferenceReadinessStatus(StrEnum):
    READY = "READY"
    INSUFFICIENT_LOOKBACK = "INSUFFICIENT_LOOKBACK"
    MISSING_BARS = "MISSING_BARS"
    AMBIGUOUS_DECISION_CUTOFF = "AMBIGUOUS_DECISION_CUTOFF"
    INVALID_PRICE_SERIES = "INVALID_PRICE_SERIES"
    TIMEZONE_MISMATCH = "TIMEZONE_MISMATCH"
    SYMBOL_IDENTITY_UNRESOLVED = "SYMBOL_IDENTITY_UNRESOLVED"
    LISTING_DATE_VIOLATION = "LISTING_DATE_VIOLATION"
    DELISTING_DATE_VIOLATION = "DELISTING_DATE_VIOLATION"
    CORPORATE_ACTION_AMBIGUITY = "CORPORATE_ACTION_AMBIGUITY"
    ADJUSTMENT_MODE_MISMATCH = "ADJUSTMENT_MODE_MISMATCH"
    REFERENCE_NOT_FORMED = "REFERENCE_NOT_FORMED"
    UNSUPPORTED_REFERENCE_METHOD = "UNSUPPORTED_REFERENCE_METHOD"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    PROVENANCE_INCOMPLETE = "PROVENANCE_INCOMPLETE"
    RECONSTRUCTION_ERROR = "RECONSTRUCTION_ERROR"


class BreakoutCutoffSemantics(StrEnum):
    PRE_MARKET_PREVIOUS_SESSION = "PRE_MARKET_PREVIOUS_SESSION"
    INTRADAY_PREVIOUS_SESSION = "INTRADAY_PREVIOUS_SESSION"
    AFTER_CLOSE_CANDIDATE_SESSION = "AFTER_CLOSE_CANDIDATE_SESSION"
    LEGACY_DATE_ONLY_PREVIOUS_SESSION = "LEGACY_DATE_ONLY_PREVIOUS_SESSION"
    LEGACY_DATE_ONLY_AMBIGUOUS = "LEGACY_DATE_ONLY_AMBIGUOUS"
    NON_TRADING_DATE_PREVIOUS_SESSION = "NON_TRADING_DATE_PREVIOUS_SESSION"


class LegacyDateCutoffPolicy(StrEnum):
    PREVIOUS_COMPLETED_SESSION = "PREVIOUS_COMPLETED_SESSION"
    AMBIGUOUS = "AMBIGUOUS"


class PriceAdjustmentMode(StrEnum):
    RAW_UNADJUSTED = "RAW_UNADJUSTED"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    FULLY_ADJUSTED = "FULLY_ADJUSTED"
    UNKNOWN = "UNKNOWN"


class BreakoutHistoricalReadinessConclusion(StrEnum):
    BREAKOUT_HISTORY_READY = "BREAKOUT_HISTORY_READY"
    BREAKOUT_HISTORY_PARTIALLY_READY = "BREAKOUT_HISTORY_PARTIALLY_READY"
    BREAKOUT_HISTORY_BLOCKED_BY_CUTOFF_AMBIGUITY = (
        "BREAKOUT_HISTORY_BLOCKED_BY_CUTOFF_AMBIGUITY"
    )
    BREAKOUT_HISTORY_BLOCKED_BY_SOURCE_GAPS = "BREAKOUT_HISTORY_BLOCKED_BY_SOURCE_GAPS"
    BREAKOUT_HISTORY_BLOCKED_BY_SYMBOL_IDENTITY = (
        "BREAKOUT_HISTORY_BLOCKED_BY_SYMBOL_IDENTITY"
    )
    BREAKOUT_HISTORY_BLOCKED_BY_PROVENANCE = "BREAKOUT_HISTORY_BLOCKED_BY_PROVENANCE"
    BREAKOUT_HISTORY_NOT_READY = "BREAKOUT_HISTORY_NOT_READY"


class BreakoutIntegrityStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NO_RECORDS = "NO_RECORDS"


class BreakoutReferenceOperation(StrEnum):
    CREATED = "CREATED"
    REUSED = "REUSED"
    SKIPPED = "SKIPPED"
    EXCLUDED = "EXCLUDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class BreakoutSourceBar:
    observed_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal | None
    exchange: str = "NSE"
    adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW_UNADJUSTED

    def __post_init__(self) -> None:
        for name in ("open_price", "high_price", "low_price", "close_price"):
            object.__setattr__(self, name, _decimal(getattr(self, name)))
        if self.volume is not None:
            object.__setattr__(self, "volume", _decimal(self.volume))
        object.__setattr__(self, "exchange", self.exchange.strip().upper())


@dataclass(frozen=True, slots=True)
class BreakoutReconstructionCandidate:
    replay_run_id: str
    candidate_id: str
    historical_symbol: str
    observation_date: date
    decision_at: datetime | None = None
    timestamp_is_proven: bool = False
    exchange: str = "NSE"
    market_session: str = "NSE_REGULAR"
    timezone: str = INDIA_TIMEZONE

    def __post_init__(self) -> None:
        object.__setattr__(self, "historical_symbol", self.historical_symbol.upper())
        object.__setattr__(self, "exchange", self.exchange.upper())


@dataclass(frozen=True, slots=True)
class HistoricalSecurityIdentity:
    instrument_identifier: str | None
    historical_symbol: str
    exchange: str
    security_master_version: str | None
    evidence_reference: str | None
    resolved: bool
    listing_date: date | None = None
    delisting_date: date | None = None
    identity_quality: str = "UNKNOWN"
    previous_symbol: str | None = None
    successor_symbol: str | None = None


@dataclass(frozen=True, slots=True)
class CorporateActionEvent:
    symbol: str
    effective_date: date
    action_type: str
    source: str
    adjustment_mode: PriceAdjustmentMode


@dataclass(frozen=True, slots=True)
class BreakoutReferenceConfiguration:
    reference_method: BreakoutReferenceMethod = BreakoutReferenceMethod.PRIOR_SWING_HIGH
    minimum_lookback: int = 60
    reference_lookback: int = 120
    swing_left_bars: int = 2
    swing_right_bars: int = 2
    range_minimum_touches: int = 2
    touch_tolerance_pct: Decimal = Decimal("0.0075")
    atr_period: int = 14
    volume_baseline_period: int = 20
    volume_confirmation_ratio: Decimal = Decimal("1.50")
    maximum_missing_session_ratio: Decimal = Decimal("0.10")
    discontinuity_threshold: Decimal = Decimal("0.45")
    legacy_date_policy: LegacyDateCutoffPolicy = (
        LegacyDateCutoffPolicy.PREVIOUS_COMPLETED_SESSION
    )
    adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW_UNADJUSTED
    algorithm_name: str = "PointInTimeBreakoutReferenceEngine"
    algorithm_version: str = BREAKOUT_REFERENCE_ALGORITHM_VERSION

    def __post_init__(self) -> None:
        if self.minimum_lookback < 5:
            raise ValueError("minimum_lookback must be at least 5")
        if self.reference_lookback < self.minimum_lookback:
            raise ValueError("reference_lookback cannot be below minimum_lookback")
        if self.swing_left_bars < 1 or self.swing_right_bars < 1:
            raise ValueError("swing confirmation windows must be positive")
        if self.range_minimum_touches < 2:
            raise ValueError("range resistance requires at least two touches")

    @property
    def configuration_hash(self) -> str:
        return _hash(_jsonable(asdict(self)))


@dataclass(frozen=True, slots=True)
class BreakoutCutoffDecision:
    semantics: BreakoutCutoffSemantics
    allowed_cutoff: datetime | None
    candidate_session_close_available: bool
    inclusive: bool
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class BreakoutReferenceEvidence:
    primary_reference_level: Decimal | None
    reference_level_type: BreakoutReferenceMethod
    formation_start: datetime | None
    confirmation_end: datetime | None
    touch_count: int
    touch_timestamps: tuple[datetime, ...]
    tolerance: Decimal | None
    clustering_rule: str
    lookback_length: int
    consolidation_high: Decimal | None
    consolidation_low: Decimal | None
    consolidation_width: Decimal | None
    prior_swing_high: Decimal | None
    base_duration: int | None
    volume_baseline: Decimal | None
    candidate_session_price: Decimal | None
    distance_to_reference: Decimal | None
    atr: Decimal | None
    atr_normalized_distance: Decimal | None
    breakout_attempt_evidence: str
    breakout_confirmation_evidence: str
    close_location_evidence: Decimal | None
    retest_evidence: str
    support_level: Decimal | None
    observation_bar_timestamp: datetime | None


@dataclass(frozen=True, slots=True)
class BreakoutReferenceProvenance:
    source_provider: str
    source_dataset: str
    retrieval_timestamp: datetime
    raw_series_checksum: str
    normalized_series_checksum: str
    adjustment_mode: PriceAdjustmentMode
    algorithm_name: str
    algorithm_version: str
    configuration_hash: str
    component_version: str
    reconstruction_timestamp: datetime
    security_master_version: str | None
    security_master_evidence_reference: str | None
    source_bar_timestamps: tuple[datetime, ...]
    warnings: tuple[str, ...]
    exclusion_reasons: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return all(
            (
                self.source_provider,
                self.source_dataset,
                self.raw_series_checksum,
                self.normalized_series_checksum,
                self.algorithm_name,
                self.algorithm_version,
                self.configuration_hash,
                self.component_version,
                self.security_master_version,
                self.security_master_evidence_reference,
            )
        )


@dataclass(frozen=True, slots=True)
class BreakoutReferenceReconstructionRecord:
    dataset_version: str
    schema_version: str
    replay_run_id: str
    candidate_id: str
    instrument_identifier: str | None
    historical_symbol: str
    exchange: str
    candidate_observation_date: date
    candidate_observation_timestamp: datetime | None
    market_session: str
    timezone: str
    security_master_version: str | None
    last_bar_timestamp_allowed: datetime | None
    last_bar_timestamp_used: datetime | None
    candidate_session_close_available: bool
    cutoff_semantics: BreakoutCutoffSemantics
    cutoff_inclusive: bool
    historical_bars_requested: int
    historical_bars_available: int
    usable_bars: int
    evidence: BreakoutReferenceEvidence
    provenance: BreakoutReferenceProvenance
    readiness_status: BreakoutReferenceReadinessStatus
    semantic_hash: str
    production_influence: bool = PRODUCTION_INFLUENCE

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (
            self.dataset_version,
            self.candidate_id,
            self.evidence.reference_level_type.value,
            self.provenance.algorithm_version,
        )

    @property
    def is_historically_usable(self) -> bool:
        return self.readiness_status in {
            BreakoutReferenceReadinessStatus.READY,
            BreakoutReferenceReadinessStatus.REFERENCE_NOT_FORMED,
        }

    def semantic_payload(self) -> dict[str, Any]:
        payload = self.as_dict()
        payload.pop("semantic_hash", None)
        provenance = payload["provenance"]
        provenance.pop("retrieval_timestamp", None)
        provenance.pop("reconstruction_timestamp", None)
        return payload

    def calculated_semantic_hash(self) -> str:
        return _hash(self.semantic_payload())

    def as_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(asdict(self)))

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> BreakoutReferenceReconstructionRecord:
        evidence_payload = _mapping(payload["evidence"])
        provenance_payload = _mapping(payload["provenance"])
        evidence = BreakoutReferenceEvidence(
            primary_reference_level=_optional_decimal(
                evidence_payload.get("primary_reference_level")
            ),
            reference_level_type=BreakoutReferenceMethod(
                str(evidence_payload["reference_level_type"])
            ),
            formation_start=_optional_datetime(evidence_payload.get("formation_start")),
            confirmation_end=_optional_datetime(
                evidence_payload.get("confirmation_end")
            ),
            touch_count=int(evidence_payload.get("touch_count", 0)),
            touch_timestamps=tuple(
                _datetime(item) for item in evidence_payload.get("touch_timestamps", ())
            ),
            tolerance=_optional_decimal(evidence_payload.get("tolerance")),
            clustering_rule=str(evidence_payload.get("clustering_rule", "")),
            lookback_length=int(evidence_payload.get("lookback_length", 0)),
            consolidation_high=_optional_decimal(
                evidence_payload.get("consolidation_high")
            ),
            consolidation_low=_optional_decimal(
                evidence_payload.get("consolidation_low")
            ),
            consolidation_width=_optional_decimal(
                evidence_payload.get("consolidation_width")
            ),
            prior_swing_high=_optional_decimal(
                evidence_payload.get("prior_swing_high")
            ),
            base_duration=_optional_int(evidence_payload.get("base_duration")),
            volume_baseline=_optional_decimal(evidence_payload.get("volume_baseline")),
            candidate_session_price=_optional_decimal(
                evidence_payload.get("candidate_session_price")
            ),
            distance_to_reference=_optional_decimal(
                evidence_payload.get("distance_to_reference")
            ),
            atr=_optional_decimal(evidence_payload.get("atr")),
            atr_normalized_distance=_optional_decimal(
                evidence_payload.get("atr_normalized_distance")
            ),
            breakout_attempt_evidence=str(
                evidence_payload.get("breakout_attempt_evidence", "UNAVAILABLE")
            ),
            breakout_confirmation_evidence=str(
                evidence_payload.get("breakout_confirmation_evidence", "UNAVAILABLE")
            ),
            close_location_evidence=_optional_decimal(
                evidence_payload.get("close_location_evidence")
            ),
            retest_evidence=str(evidence_payload.get("retest_evidence", "UNAVAILABLE")),
            support_level=_optional_decimal(evidence_payload.get("support_level")),
            observation_bar_timestamp=_optional_datetime(
                evidence_payload.get("observation_bar_timestamp")
            ),
        )
        provenance = BreakoutReferenceProvenance(
            source_provider=str(provenance_payload["source_provider"]),
            source_dataset=str(provenance_payload["source_dataset"]),
            retrieval_timestamp=_datetime(provenance_payload["retrieval_timestamp"]),
            raw_series_checksum=str(provenance_payload["raw_series_checksum"]),
            normalized_series_checksum=str(
                provenance_payload["normalized_series_checksum"]
            ),
            adjustment_mode=PriceAdjustmentMode(
                str(provenance_payload["adjustment_mode"])
            ),
            algorithm_name=str(provenance_payload["algorithm_name"]),
            algorithm_version=str(provenance_payload["algorithm_version"]),
            configuration_hash=str(provenance_payload["configuration_hash"]),
            component_version=str(provenance_payload["component_version"]),
            reconstruction_timestamp=_datetime(
                provenance_payload["reconstruction_timestamp"]
            ),
            security_master_version=_optional_text(
                provenance_payload.get("security_master_version")
            ),
            security_master_evidence_reference=_optional_text(
                provenance_payload.get("security_master_evidence_reference")
            ),
            source_bar_timestamps=tuple(
                _datetime(item)
                for item in provenance_payload.get("source_bar_timestamps", ())
            ),
            warnings=tuple(
                str(item) for item in provenance_payload.get("warnings", ())
            ),
            exclusion_reasons=tuple(
                str(item) for item in provenance_payload.get("exclusion_reasons", ())
            ),
        )
        return cls(
            dataset_version=str(payload["dataset_version"]),
            schema_version=str(payload["schema_version"]),
            replay_run_id=str(payload["replay_run_id"]),
            candidate_id=str(payload["candidate_id"]),
            instrument_identifier=_optional_text(payload.get("instrument_identifier")),
            historical_symbol=str(payload["historical_symbol"]),
            exchange=str(payload["exchange"]),
            candidate_observation_date=date.fromisoformat(
                str(payload["candidate_observation_date"])
            ),
            candidate_observation_timestamp=_optional_datetime(
                payload.get("candidate_observation_timestamp")
            ),
            market_session=str(payload["market_session"]),
            timezone=str(payload["timezone"]),
            security_master_version=_optional_text(
                payload.get("security_master_version")
            ),
            last_bar_timestamp_allowed=_optional_datetime(
                payload.get("last_bar_timestamp_allowed")
            ),
            last_bar_timestamp_used=_optional_datetime(
                payload.get("last_bar_timestamp_used")
            ),
            candidate_session_close_available=bool(
                payload["candidate_session_close_available"]
            ),
            cutoff_semantics=BreakoutCutoffSemantics(str(payload["cutoff_semantics"])),
            cutoff_inclusive=bool(payload["cutoff_inclusive"]),
            historical_bars_requested=int(payload["historical_bars_requested"]),
            historical_bars_available=int(payload["historical_bars_available"]),
            usable_bars=int(payload["usable_bars"]),
            evidence=evidence,
            provenance=provenance,
            readiness_status=BreakoutReferenceReadinessStatus(
                str(payload["readiness_status"])
            ),
            semantic_hash=str(payload["semantic_hash"]),
            production_influence=bool(payload.get("production_influence", False)),
        )


@dataclass(frozen=True, slots=True)
class BreakoutReferenceManifest:
    dataset_version: str
    schema_version: str
    created_at: datetime
    record_count: int
    algorithm_versions: tuple[str, ...]
    configuration_hashes: tuple[str, ...]
    source_datasets: tuple[str, ...]
    dataset_semantic_hash: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class BreakoutReferenceDataset:
    manifest: BreakoutReferenceManifest
    records: tuple[BreakoutReferenceReconstructionRecord, ...]


@dataclass(frozen=True, slots=True)
class BreakoutReferencePersistenceResult:
    path: Path
    created: int
    reused: int
    skipped: int
    excluded: int
    failed: int
    dry_run: bool
    total_records: int


@dataclass(frozen=True, slots=True)
class BreakoutReferenceCoverageRow:
    key: str
    candidates: int
    historically_usable: int
    availability_pct: Decimal


@dataclass(frozen=True, slots=True)
class BreakoutHistoricalReadinessReport:
    dataset_version: str
    total_replay_candidates: int
    unique_symbols: int
    date_range: tuple[date | None, date | None]
    candidates_attempted: int
    ready_records: int
    reference_not_formed_records: int
    unreconstructable_records: int
    readiness_percentage: Decimal
    availability_by_year: tuple[BreakoutReferenceCoverageRow, ...]
    availability_by_symbol: tuple[BreakoutReferenceCoverageRow, ...]
    availability_by_source: tuple[BreakoutReferenceCoverageRow, ...]
    availability_by_reference_method: tuple[BreakoutReferenceCoverageRow, ...]
    availability_by_timing_semantics: tuple[BreakoutReferenceCoverageRow, ...]
    exclusion_reason_counts: tuple[tuple[str, int], ...]
    median_usable_lookback: Decimal | None
    minimum_usable_lookback: int | None
    ambiguous_cutoff_count: int
    corporate_action_ambiguity_count: int
    unresolved_symbol_count: int
    provenance_completeness_rate: Decimal
    deterministic_reconstruction_check: bool
    leakage_audit_result: BreakoutIntegrityStatus
    conclusion: BreakoutHistoricalReadinessConclusion
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class BreakoutReferenceIntegrityAudit:
    records_checked: int
    future_bar_violations: int
    future_swing_confirmation_violations: int
    post_candidate_retest_violations: int
    outcome_derived_field_violations: int
    future_market_state_violations: int
    semantic_hash_violations: int
    duplicate_key_conflicts: int
    configuration_hash_violations: int
    source_checksum_violations: int
    identity_violations: int
    listing_interval_violations: int
    adjustment_consistency_violations: int
    duplicate_bar_violations: int
    invalid_ohlc_violations: int
    incomplete_ready_lineage: int
    exclusions_without_reason: int
    determinism_status: BreakoutIntegrityStatus
    leakage_status: BreakoutIntegrityStatus
    identity_status: BreakoutIntegrityStatus
    series_status: BreakoutIntegrityStatus
    lineage_status: BreakoutIntegrityStatus
    overall_status: BreakoutIntegrityStatus
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class _ReferenceResult:
    level: Decimal | None
    formation_start: datetime | None
    confirmation_end: datetime | None
    touches: tuple[datetime, ...]
    tolerance: Decimal | None
    prior_swing_high: Decimal | None


class PointInTimeBreakoutReferenceEngine:
    def __init__(
        self,
        configuration: BreakoutReferenceConfiguration | None = None,
        *,
        source_provider: str = "PROJECT_ALPHA_CANONICAL_DAILY_PRICES",
        source_dataset: str = "data/ingestion.duckdb:daily_prices",
        clock: datetime | None = None,
    ) -> None:
        self.configuration = configuration or BreakoutReferenceConfiguration()
        self.source_provider = source_provider
        self.source_dataset = source_dataset
        self.clock = clock or datetime.now(UTC)

    def reconstruct(
        self,
        *,
        candidate: BreakoutReconstructionCandidate,
        bars: Sequence[BreakoutSourceBar],
        identity: HistoricalSecurityIdentity,
        exchange_sessions: Sequence[date],
        corporate_actions: Sequence[CorporateActionEvent] = (),
    ) -> BreakoutReferenceReconstructionRecord:
        raw_checksum = _bars_checksum(bars, preserve_order=True)
        requested = self.configuration.reference_lookback + 1
        cutoff = self._cutoff(candidate, exchange_sessions)
        if cutoff.allowed_cutoff is None:
            return self._record(
                candidate=candidate,
                identity=identity,
                cutoff=cutoff,
                bars=bars,
                normalized_bars=(),
                evidence=_empty_evidence(self.configuration.reference_method),
                status=BreakoutReferenceReadinessStatus.AMBIGUOUS_DECISION_CUTOFF,
                raw_checksum=raw_checksum,
                warnings=_optional_tuple(cutoff.warning),
                exclusion_reasons=("DECISION_TIMESTAMP_NOT_PROVEN",),
                requested=requested,
            )
        identity_status, identity_reason = _identity_status(candidate, identity)
        if identity_status is not None:
            return self._record(
                candidate=candidate,
                identity=identity,
                cutoff=cutoff,
                bars=bars,
                normalized_bars=(),
                evidence=_empty_evidence(self.configuration.reference_method),
                status=identity_status,
                raw_checksum=raw_checksum,
                warnings=_optional_tuple(cutoff.warning),
                exclusion_reasons=(identity_reason,),
                requested=requested,
            )
        normalized, validation_status, validation_reasons = self._validate_bars(
            candidate=candidate,
            bars=bars,
            exchange_sessions=exchange_sessions,
            cutoff=cutoff,
        )
        if validation_status is not None:
            return self._record(
                candidate=candidate,
                identity=identity,
                cutoff=cutoff,
                bars=bars,
                normalized_bars=normalized,
                evidence=_empty_evidence(self.configuration.reference_method),
                status=validation_status,
                raw_checksum=raw_checksum,
                warnings=_optional_tuple(cutoff.warning),
                exclusion_reasons=validation_reasons,
                requested=requested,
            )
        available = tuple(
            bar
            for bar in normalized
            if bar.observed_at <= cutoff.allowed_cutoff
            if cutoff.inclusive or bar.observed_at < cutoff.allowed_cutoff
        )
        if not available:
            return self._record(
                candidate=candidate,
                identity=identity,
                cutoff=cutoff,
                bars=bars,
                normalized_bars=available,
                evidence=_empty_evidence(self.configuration.reference_method),
                status=BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
                raw_checksum=raw_checksum,
                warnings=_optional_tuple(cutoff.warning),
                exclusion_reasons=("NO_BAR_AT_OR_BEFORE_ALLOWED_CUTOFF",),
                requested=requested,
            )
        available, action_warnings, action_status = self._apply_corporate_actions(
            candidate=candidate,
            bars=available,
            corporate_actions=corporate_actions,
        )
        warnings = tuple(filter(None, (cutoff.warning, *action_warnings)))
        if action_status is not None:
            return self._record(
                candidate=candidate,
                identity=identity,
                cutoff=cutoff,
                bars=bars,
                normalized_bars=available,
                evidence=_empty_evidence(self.configuration.reference_method),
                status=action_status,
                raw_checksum=raw_checksum,
                warnings=warnings,
                exclusion_reasons=("UNEXPLAINED_PRICE_DISCONTINUITY",),
                requested=requested,
            )
        observation_bar = available[-1]
        formation_bars = available[:-1]
        if len(formation_bars) < self.configuration.minimum_lookback:
            return self._record(
                candidate=candidate,
                identity=identity,
                cutoff=cutoff,
                bars=bars,
                normalized_bars=available,
                evidence=_empty_evidence(
                    self.configuration.reference_method,
                    observation=observation_bar,
                ),
                status=BreakoutReferenceReadinessStatus.INSUFFICIENT_LOOKBACK,
                raw_checksum=raw_checksum,
                warnings=warnings,
                exclusion_reasons=(
                    f"REQUIRES_{self.configuration.minimum_lookback}_FORMATION_BARS_HAS_"
                    f"{len(formation_bars)}",
                ),
                requested=requested,
            )
        missing_ratio = _missing_session_ratio(
            available,
            exchange_sessions,
            observation_bar.observed_at.date(),
            requested,
        )
        if missing_ratio > self.configuration.maximum_missing_session_ratio:
            return self._record(
                candidate=candidate,
                identity=identity,
                cutoff=cutoff,
                bars=bars,
                normalized_bars=available,
                evidence=_empty_evidence(
                    self.configuration.reference_method,
                    observation=observation_bar,
                ),
                status=BreakoutReferenceReadinessStatus.MISSING_BARS,
                raw_checksum=raw_checksum,
                warnings=warnings,
                exclusion_reasons=(f"MISSING_SESSION_RATIO_{missing_ratio}",),
                requested=requested,
            )
        evidence = self._build_evidence(formation_bars, observation_bar)
        status = (
            BreakoutReferenceReadinessStatus.READY
            if evidence.primary_reference_level is not None
            else BreakoutReferenceReadinessStatus.REFERENCE_NOT_FORMED
        )
        exclusions = (
            ()
            if status is BreakoutReferenceReadinessStatus.READY
            else ("VALID_HISTORY_CONTAINS_NO_QUALIFYING_REFERENCE",)
        )
        return self._record(
            candidate=candidate,
            identity=identity,
            cutoff=cutoff,
            bars=bars,
            normalized_bars=available,
            evidence=evidence,
            status=status,
            raw_checksum=raw_checksum,
            warnings=warnings,
            exclusion_reasons=exclusions,
            requested=requested,
        )

    def _cutoff(
        self,
        candidate: BreakoutReconstructionCandidate,
        exchange_sessions: Sequence[date],
    ) -> BreakoutCutoffDecision:
        sessions = tuple(sorted(set(exchange_sessions)))
        candidate_is_session = candidate.observation_date in sessions
        if candidate.decision_at is None or not candidate.timestamp_is_proven:
            if (
                self.configuration.legacy_date_policy
                is LegacyDateCutoffPolicy.AMBIGUOUS
            ):
                return BreakoutCutoffDecision(
                    semantics=BreakoutCutoffSemantics.LEGACY_DATE_ONLY_AMBIGUOUS,
                    allowed_cutoff=None,
                    candidate_session_close_available=False,
                    inclusive=False,
                    warning="Legacy replay timing is unproven.",
                )
            prior = _previous_session(
                sessions, candidate.observation_date, inclusive=False
            )
            semantics = (
                BreakoutCutoffSemantics.LEGACY_DATE_ONLY_PREVIOUS_SESSION
                if candidate_is_session
                else BreakoutCutoffSemantics.NON_TRADING_DATE_PREVIOUS_SESSION
            )
            return BreakoutCutoffDecision(
                semantics=semantics,
                allowed_cutoff=_session_close(prior) if prior is not None else None,
                candidate_session_close_available=False,
                inclusive=True,
                warning=(
                    "Legacy date-only record uses the previous completed session; "
                    "candidate-day close is excluded."
                ),
            )
        local = _as_ist(candidate.decision_at)
        if not candidate_is_session:
            prior = _previous_session(
                sessions, candidate.observation_date, inclusive=False
            )
            return BreakoutCutoffDecision(
                semantics=BreakoutCutoffSemantics.NON_TRADING_DATE_PREVIOUS_SESSION,
                allowed_cutoff=_session_close(prior) if prior is not None else None,
                candidate_session_close_available=False,
                inclusive=True,
                warning="Observation date is not a persisted exchange session.",
            )
        if local.time() < _MARKET_OPEN:
            prior = _previous_session(
                sessions, candidate.observation_date, inclusive=False
            )
            return BreakoutCutoffDecision(
                semantics=BreakoutCutoffSemantics.PRE_MARKET_PREVIOUS_SESSION,
                allowed_cutoff=_session_close(prior) if prior is not None else None,
                candidate_session_close_available=False,
                inclusive=True,
            )
        if local.time() <= _MARKET_CLOSE:
            prior = _previous_session(
                sessions, candidate.observation_date, inclusive=False
            )
            return BreakoutCutoffDecision(
                semantics=BreakoutCutoffSemantics.INTRADAY_PREVIOUS_SESSION,
                allowed_cutoff=_session_close(prior) if prior is not None else None,
                candidate_session_close_available=False,
                inclusive=True,
                warning="Daily OHLCV cannot represent a partial intraday session.",
            )
        return BreakoutCutoffDecision(
            semantics=BreakoutCutoffSemantics.AFTER_CLOSE_CANDIDATE_SESSION,
            allowed_cutoff=_session_close(candidate.observation_date),
            candidate_session_close_available=True,
            inclusive=True,
        )

    def _validate_bars(
        self,
        *,
        candidate: BreakoutReconstructionCandidate,
        bars: Sequence[BreakoutSourceBar],
        exchange_sessions: Sequence[date],
        cutoff: BreakoutCutoffDecision,
    ) -> tuple[
        tuple[BreakoutSourceBar, ...],
        BreakoutReferenceReadinessStatus | None,
        tuple[str, ...],
    ]:
        if not bars:
            return (
                (),
                BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
                ("SOURCE_SERIES_EMPTY",),
            )
        timestamps = tuple(bar.observed_at for bar in bars)
        if timestamps != tuple(sorted(timestamps)):
            return (
                (),
                BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES,
                ("BARS_NOT_CHRONOLOGICALLY_ORDERED",),
            )
        if len(set(timestamps)) != len(timestamps):
            return (
                (),
                BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES,
                ("DUPLICATE_BAR_TIMESTAMPS",),
            )
        if any(not _timezone_is_ist(bar.observed_at) for bar in bars):
            return (
                (),
                BreakoutReferenceReadinessStatus.TIMEZONE_MISMATCH,
                ("BAR_TIMEZONE_NOT_ASIA_KOLKATA",),
            )
        if any(bar.exchange != candidate.exchange for bar in bars):
            return (
                (),
                BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES,
                ("EXCHANGE_MISMATCH",),
            )
        modes = {bar.adjustment_mode for bar in bars}
        if modes != {self.configuration.adjustment_mode}:
            return (
                (),
                BreakoutReferenceReadinessStatus.ADJUSTMENT_MODE_MISMATCH,
                ("MIXED_OR_UNEXPECTED_ADJUSTMENT_MODE",),
            )
        sessions = set(exchange_sessions)
        for bar in bars:
            if sessions and bar.observed_at.date() not in sessions:
                return (
                    (),
                    BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES,
                    ("BAR_NOT_ALIGNED_TO_PERSISTED_EXCHANGE_SESSION",),
                )
            prices = (
                bar.open_price,
                bar.high_price,
                bar.low_price,
                bar.close_price,
            )
            if any(value <= _ZERO for value in prices):
                return (
                    (),
                    BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES,
                    ("NON_POSITIVE_PRICE",),
                )
            if (
                bar.high_price < bar.low_price
                or not bar.low_price <= bar.open_price <= bar.high_price
                or not bar.low_price <= bar.close_price <= bar.high_price
            ):
                return (
                    (),
                    BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES,
                    ("INVALID_OHLC_RELATIONSHIP",),
                )
            if bar.volume is None or bar.volume < _ZERO:
                return (
                    (),
                    BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES,
                    ("MISSING_OR_INVALID_VOLUME",),
                )
        normalized = tuple(bars)
        if cutoff.allowed_cutoff is not None and any(
            bar.observed_at > cutoff.allowed_cutoff for bar in normalized
        ):
            normalized = tuple(
                bar for bar in normalized if bar.observed_at <= cutoff.allowed_cutoff
            )
        return normalized, None, ()

    def _apply_corporate_actions(
        self,
        *,
        candidate: BreakoutReconstructionCandidate,
        bars: tuple[BreakoutSourceBar, ...],
        corporate_actions: Sequence[CorporateActionEvent],
    ) -> tuple[
        tuple[BreakoutSourceBar, ...],
        tuple[str, ...],
        BreakoutReferenceReadinessStatus | None,
    ]:
        relevant = tuple(
            action
            for action in corporate_actions
            if action.symbol.upper() == candidate.historical_symbol
            and action.effective_date <= candidate.observation_date
        )
        split_dates = tuple(
            action.effective_date
            for action in relevant
            if "SPLIT" in action.action_type.upper()
        )
        if (
            split_dates
            and self.configuration.adjustment_mode is PriceAdjustmentMode.RAW_UNADJUSTED
        ):
            latest_split = max(split_dates)
            bars = tuple(bar for bar in bars if bar.observed_at.date() >= latest_split)
            warning = f"HISTORY_TRIMMED_AFTER_SPLIT_{latest_split.isoformat()}"
            return bars, (warning,), None
        discontinuities = _discontinuity_dates(
            bars,
            self.configuration.discontinuity_threshold,
        )
        explained = {action.effective_date for action in relevant}
        unexplained = tuple(day for day in discontinuities if day not in explained)
        if unexplained:
            return bars, (), BreakoutReferenceReadinessStatus.CORPORATE_ACTION_AMBIGUITY
        return bars, (), None

    def _build_evidence(
        self,
        formation_bars: tuple[BreakoutSourceBar, ...],
        observation_bar: BreakoutSourceBar,
    ) -> BreakoutReferenceEvidence:
        window = formation_bars[-self.configuration.reference_lookback :]
        reference = self._reference(window)
        recent = window[-min(20, len(window)) :]
        consolidation_high = max((bar.high_price for bar in recent), default=None)
        consolidation_low = min((bar.low_price for bar in recent), default=None)
        consolidation_width = _relative_width(consolidation_high, consolidation_low)
        atr = _atr((*window, observation_bar), self.configuration.atr_period)
        volume_window = window[-self.configuration.volume_baseline_period :]
        volume_baseline = _mean_decimal(
            bar.volume for bar in volume_window if bar.volume is not None
        )
        close_location = _close_location(observation_bar)
        distance = _distance(observation_bar.close_price, reference.level)
        reference_level = reference.level
        atr_distance = (
            None
            if reference_level is None or atr is None or atr == _ZERO
            else _quantize((observation_bar.close_price - reference_level) / atr)
        )
        baseline = volume_baseline
        volume_ratio = (
            None
            if baseline is None or baseline == _ZERO or observation_bar.volume is None
            else observation_bar.volume / baseline
        )
        attempt, confirmation = _breakout_states(
            price=observation_bar.close_price,
            reference=reference.level,
            tolerance=reference.tolerance,
            volume_ratio=volume_ratio,
            close_location=close_location,
            required_volume=self.configuration.volume_confirmation_ratio,
        )
        retest = _retest_state(window, observation_bar, reference)
        return BreakoutReferenceEvidence(
            primary_reference_level=reference.level,
            reference_level_type=self.configuration.reference_method,
            formation_start=reference.formation_start,
            confirmation_end=reference.confirmation_end,
            touch_count=len(reference.touches),
            touch_timestamps=reference.touches,
            tolerance=reference.tolerance,
            clustering_rule=(
                "absolute distance <= max(level*"
                f"{self.configuration.touch_tolerance_pct}, "
                "0.15*ATR)"
            ),
            lookback_length=len(window),
            consolidation_high=consolidation_high,
            consolidation_low=consolidation_low,
            consolidation_width=consolidation_width,
            prior_swing_high=reference.prior_swing_high,
            base_duration=_base_duration(reference),
            volume_baseline=volume_baseline,
            candidate_session_price=observation_bar.close_price,
            distance_to_reference=distance,
            atr=atr,
            atr_normalized_distance=atr_distance,
            breakout_attempt_evidence=attempt,
            breakout_confirmation_evidence=confirmation,
            close_location_evidence=close_location,
            retest_evidence=retest,
            support_level=consolidation_low,
            observation_bar_timestamp=observation_bar.observed_at,
        )

    def _reference(
        self,
        bars: tuple[BreakoutSourceBar, ...],
    ) -> _ReferenceResult:
        method = self.configuration.reference_method
        if method is BreakoutReferenceMethod.PRIOR_SWING_HIGH:
            return self._prior_swing_high(bars)
        if method is BreakoutReferenceMethod.RANGE_RESISTANCE:
            return self._range_resistance(bars)
        if method is BreakoutReferenceMethod.ROLLING_HIGH:
            return self._rolling_high(bars)
        return _ReferenceResult(None, None, None, (), None, None)

    def _prior_swing_high(
        self,
        bars: tuple[BreakoutSourceBar, ...],
    ) -> _ReferenceResult:
        left = self.configuration.swing_left_bars
        right = self.configuration.swing_right_bars
        pivots: list[int] = []
        for index in range(left, len(bars) - right):
            high = bars[index].high_price
            left_highs = (bar.high_price for bar in bars[index - left : index])
            right_highs = (
                bar.high_price for bar in bars[index + 1 : index + right + 1]
            )
            if high > max(left_highs) and high >= max(right_highs):
                pivots.append(index)
        if not pivots:
            return _ReferenceResult(None, None, None, (), None, None)
        index = pivots[-1]
        level = bars[index].high_price
        tolerance = _touch_tolerance(level, bars, self.configuration)
        touches = tuple(
            bar.observed_at for bar in bars if abs(bar.high_price - level) <= tolerance
        )
        return _ReferenceResult(
            level=level,
            formation_start=bars[max(0, index - left)].observed_at,
            confirmation_end=bars[index + right].observed_at,
            touches=touches,
            tolerance=tolerance,
            prior_swing_high=level,
        )

    def _range_resistance(
        self,
        bars: tuple[BreakoutSourceBar, ...],
    ) -> _ReferenceResult:
        level = max(bar.high_price for bar in bars)
        tolerance = _touch_tolerance(level, bars, self.configuration)
        touch_bars = tuple(
            bar for bar in bars if abs(bar.high_price - level) <= tolerance
        )
        if len(touch_bars) < self.configuration.range_minimum_touches:
            return _ReferenceResult(None, None, None, (), tolerance, None)
        return _ReferenceResult(
            level=level,
            formation_start=touch_bars[0].observed_at,
            confirmation_end=touch_bars[-1].observed_at,
            touches=tuple(bar.observed_at for bar in touch_bars),
            tolerance=tolerance,
            prior_swing_high=level,
        )

    def _rolling_high(
        self,
        bars: tuple[BreakoutSourceBar, ...],
    ) -> _ReferenceResult:
        high_bar = max(bars, key=lambda bar: (bar.high_price, bar.observed_at))
        level = high_bar.high_price
        tolerance = _touch_tolerance(level, bars, self.configuration)
        touches = tuple(
            bar.observed_at for bar in bars if abs(bar.high_price - level) <= tolerance
        )
        return _ReferenceResult(
            level=level,
            formation_start=high_bar.observed_at,
            confirmation_end=bars[-1].observed_at,
            touches=touches,
            tolerance=tolerance,
            prior_swing_high=level,
        )

    def _record(
        self,
        *,
        candidate: BreakoutReconstructionCandidate,
        identity: HistoricalSecurityIdentity,
        cutoff: BreakoutCutoffDecision,
        bars: Sequence[BreakoutSourceBar],
        normalized_bars: Sequence[BreakoutSourceBar],
        evidence: BreakoutReferenceEvidence,
        status: BreakoutReferenceReadinessStatus,
        raw_checksum: str,
        warnings: tuple[str, ...],
        exclusion_reasons: tuple[str, ...],
        requested: int,
    ) -> BreakoutReferenceReconstructionRecord:
        normalized_checksum = _bars_checksum(normalized_bars, preserve_order=False)
        provenance = BreakoutReferenceProvenance(
            source_provider=self.source_provider,
            source_dataset=self.source_dataset,
            retrieval_timestamp=self.clock,
            raw_series_checksum=raw_checksum,
            normalized_series_checksum=normalized_checksum,
            adjustment_mode=self.configuration.adjustment_mode,
            algorithm_name=self.configuration.algorithm_name,
            algorithm_version=self.configuration.algorithm_version,
            configuration_hash=self.configuration.configuration_hash,
            component_version=BREAKOUT_REFERENCE_SCHEMA_VERSION,
            reconstruction_timestamp=self.clock,
            security_master_version=identity.security_master_version,
            security_master_evidence_reference=identity.evidence_reference,
            source_bar_timestamps=tuple(bar.observed_at for bar in normalized_bars),
            warnings=warnings,
            exclusion_reasons=exclusion_reasons,
        )
        if (
            status
            in {
                BreakoutReferenceReadinessStatus.READY,
                BreakoutReferenceReadinessStatus.REFERENCE_NOT_FORMED,
            }
            and not provenance.complete
        ):
            status = BreakoutReferenceReadinessStatus.PROVENANCE_INCOMPLETE
            provenance = replace(
                provenance,
                exclusion_reasons=(
                    *provenance.exclusion_reasons,
                    "PROVENANCE_INCOMPLETE",
                ),
            )
        record = BreakoutReferenceReconstructionRecord(
            dataset_version=BREAKOUT_REFERENCE_DATASET_VERSION,
            schema_version=BREAKOUT_REFERENCE_SCHEMA_VERSION,
            replay_run_id=candidate.replay_run_id,
            candidate_id=candidate.candidate_id,
            instrument_identifier=identity.instrument_identifier,
            historical_symbol=candidate.historical_symbol,
            exchange=candidate.exchange,
            candidate_observation_date=candidate.observation_date,
            candidate_observation_timestamp=(
                candidate.decision_at if candidate.timestamp_is_proven else None
            ),
            market_session=candidate.market_session,
            timezone=candidate.timezone,
            security_master_version=identity.security_master_version,
            last_bar_timestamp_allowed=cutoff.allowed_cutoff,
            last_bar_timestamp_used=(
                normalized_bars[-1].observed_at if normalized_bars else None
            ),
            candidate_session_close_available=cutoff.candidate_session_close_available,
            cutoff_semantics=cutoff.semantics,
            cutoff_inclusive=cutoff.inclusive,
            historical_bars_requested=requested,
            historical_bars_available=sum(
                1
                for bar in bars
                if cutoff.allowed_cutoff is not None
                and bar.observed_at <= cutoff.allowed_cutoff
            ),
            usable_bars=len(normalized_bars),
            evidence=evidence,
            provenance=provenance,
            readiness_status=status,
            semantic_hash="",
            production_influence=False,
        )
        return replace(record, semantic_hash=record.calculated_semantic_hash())


class BreakoutReferenceRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_breakout_reference_path(path)

    def load_dataset(self) -> BreakoutReferenceDataset:
        if not self.path.exists():
            return _empty_dataset()
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return _empty_dataset()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return _empty_dataset()
        records = tuple(
            sorted(
                (
                    BreakoutReferenceReconstructionRecord.from_dict(item)
                    for item in payload.get("records", ())
                    if isinstance(item, dict)
                ),
                key=_record_sort_key,
            )
        )
        manifest_payload = payload.get("manifest", {})
        if not isinstance(manifest_payload, dict):
            return _dataset(records)
        return BreakoutReferenceDataset(
            manifest=BreakoutReferenceManifest(
                dataset_version=str(
                    manifest_payload.get(
                        "dataset_version", BREAKOUT_REFERENCE_DATASET_VERSION
                    )
                ),
                schema_version=str(
                    manifest_payload.get(
                        "schema_version", BREAKOUT_REFERENCE_SCHEMA_VERSION
                    )
                ),
                created_at=_optional_datetime(manifest_payload.get("created_at"))
                or datetime(1970, 1, 1, tzinfo=UTC),
                record_count=int(manifest_payload.get("record_count", len(records))),
                algorithm_versions=tuple(
                    str(item) for item in manifest_payload.get("algorithm_versions", ())
                ),
                configuration_hashes=tuple(
                    str(item)
                    for item in manifest_payload.get("configuration_hashes", ())
                ),
                source_datasets=tuple(
                    str(item) for item in manifest_payload.get("source_datasets", ())
                ),
                dataset_semantic_hash=str(
                    manifest_payload.get(
                        "dataset_semantic_hash", _dataset_hash(records)
                    )
                ),
                production_influence=bool(
                    manifest_payload.get("production_influence", False)
                ),
            ),
            records=records,
        )

    def save_records(
        self,
        records: Sequence[BreakoutReferenceReconstructionRecord],
        *,
        dry_run: bool = False,
        force: bool = False,
    ) -> BreakoutReferencePersistenceResult:
        existing_dataset = self.load_dataset()
        existing = {record.key: record for record in existing_dataset.records}
        created = reused = skipped = excluded = failed = 0
        for record in sorted(records, key=_record_sort_key):
            if record.calculated_semantic_hash() != record.semantic_hash:
                failed += 1
                continue
            prior = existing.get(record.key)
            if prior is not None and prior.semantic_hash == record.semantic_hash:
                reused += 1
                continue
            if prior is not None and not force:
                skipped += 1
                continue
            if (
                record.readiness_status
                is BreakoutReferenceReadinessStatus.RECONSTRUCTION_ERROR
            ):
                failed += 1
            elif record.is_historically_usable:
                created += 1
            else:
                excluded += 1
            existing[record.key] = record
        merged = tuple(sorted(existing.values(), key=_record_sort_key))
        if not dry_run:
            self._write(_dataset(merged))
        return BreakoutReferencePersistenceResult(
            path=self.path,
            created=created,
            reused=reused,
            skipped=skipped,
            excluded=excluded,
            failed=failed,
            dry_run=dry_run,
            total_records=len(merged),
        )

    def _write(self, dataset: BreakoutReferenceDataset) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(_jsonable(dataset), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def build_breakout_historical_readiness_report(
    *,
    records: Sequence[BreakoutReferenceReconstructionRecord],
    total_replay_candidates: int | None = None,
) -> BreakoutHistoricalReadinessReport:
    rows = tuple(sorted(records, key=_record_sort_key))
    total = (
        total_replay_candidates if total_replay_candidates is not None else len(rows)
    )
    usable = tuple(row for row in rows if row.is_historically_usable)
    ready = sum(
        row.readiness_status is BreakoutReferenceReadinessStatus.READY for row in rows
    )
    not_formed = sum(
        row.readiness_status is BreakoutReferenceReadinessStatus.REFERENCE_NOT_FORMED
        for row in rows
    )
    exclusions = Counter(
        row.readiness_status.value for row in rows if not row.is_historically_usable
    )
    dates = tuple(row.candidate_observation_date for row in rows)
    integrity = audit_breakout_reference_integrity(rows)
    provenance_rate = _percentage(
        sum(row.provenance.complete for row in rows), len(rows)
    )
    ambiguous = exclusions[
        BreakoutReferenceReadinessStatus.AMBIGUOUS_DECISION_CUTOFF.value
    ]
    corporate = exclusions[
        BreakoutReferenceReadinessStatus.CORPORATE_ACTION_AMBIGUITY.value
    ]
    unresolved = exclusions[
        BreakoutReferenceReadinessStatus.SYMBOL_IDENTITY_UNRESOLVED.value
    ]
    readiness = _percentage(len(usable), total)
    conclusion = _readiness_conclusion(
        total=total,
        readiness=readiness,
        ambiguous=ambiguous,
        unresolved=unresolved,
        provenance_rate=provenance_rate,
        exclusions=exclusions,
        integrity=integrity,
    )
    return BreakoutHistoricalReadinessReport(
        dataset_version=BREAKOUT_REFERENCE_DATASET_VERSION,
        total_replay_candidates=total,
        unique_symbols=len({row.historical_symbol for row in rows}),
        date_range=(min(dates) if dates else None, max(dates) if dates else None),
        candidates_attempted=len(rows),
        ready_records=ready,
        reference_not_formed_records=not_formed,
        unreconstructable_records=len(rows) - len(usable),
        readiness_percentage=readiness,
        availability_by_year=_coverage(
            rows, lambda row: str(row.candidate_observation_date.year)
        ),
        availability_by_symbol=_coverage(rows, lambda row: row.historical_symbol),
        availability_by_source=_coverage(
            rows, lambda row: row.provenance.source_provider
        ),
        availability_by_reference_method=_coverage(
            rows, lambda row: row.evidence.reference_level_type.value
        ),
        availability_by_timing_semantics=_coverage(
            rows, lambda row: row.cutoff_semantics.value
        ),
        exclusion_reason_counts=tuple(sorted(exclusions.items())),
        median_usable_lookback=(
            _quantize(Decimal(str(median(row.usable_bars for row in usable))))
            if usable
            else None
        ),
        minimum_usable_lookback=min((row.usable_bars for row in usable), default=None),
        ambiguous_cutoff_count=ambiguous,
        corporate_action_ambiguity_count=corporate,
        unresolved_symbol_count=unresolved,
        provenance_completeness_rate=provenance_rate,
        deterministic_reconstruction_check=(
            integrity.determinism_status is BreakoutIntegrityStatus.PASS
        ),
        leakage_audit_result=integrity.leakage_status,
        conclusion=conclusion,
        production_influence=False,
    )


def audit_breakout_reference_integrity(
    records: Sequence[BreakoutReferenceReconstructionRecord],
) -> BreakoutReferenceIntegrityAudit:
    rows = tuple(records)
    if not rows:
        return BreakoutReferenceIntegrityAudit(
            records_checked=0,
            future_bar_violations=0,
            future_swing_confirmation_violations=0,
            post_candidate_retest_violations=0,
            outcome_derived_field_violations=0,
            future_market_state_violations=0,
            semantic_hash_violations=0,
            duplicate_key_conflicts=0,
            configuration_hash_violations=0,
            source_checksum_violations=0,
            identity_violations=0,
            listing_interval_violations=0,
            adjustment_consistency_violations=0,
            duplicate_bar_violations=0,
            invalid_ohlc_violations=0,
            incomplete_ready_lineage=0,
            exclusions_without_reason=0,
            determinism_status=BreakoutIntegrityStatus.NO_RECORDS,
            leakage_status=BreakoutIntegrityStatus.NO_RECORDS,
            identity_status=BreakoutIntegrityStatus.NO_RECORDS,
            series_status=BreakoutIntegrityStatus.NO_RECORDS,
            lineage_status=BreakoutIntegrityStatus.NO_RECORDS,
            overall_status=BreakoutIntegrityStatus.NO_RECORDS,
            production_influence=False,
        )
    future = sum(
        1
        for row in rows
        for timestamp in row.provenance.source_bar_timestamps
        if row.last_bar_timestamp_allowed is None
        or timestamp > row.last_bar_timestamp_allowed
    )
    future_confirmation = sum(
        row.evidence.confirmation_end is not None
        and row.evidence.observation_bar_timestamp is not None
        and row.evidence.confirmation_end >= row.evidence.observation_bar_timestamp
        for row in rows
    )
    post_retest = sum(
        row.evidence.retest_evidence != "UNAVAILABLE"
        and row.evidence.observation_bar_timestamp is not None
        and row.last_bar_timestamp_used is not None
        and row.evidence.observation_bar_timestamp > row.last_bar_timestamp_used
        for row in rows
    )
    semantic = sum(row.semantic_hash != row.calculated_semantic_hash() for row in rows)
    keys: dict[tuple[str, str, str, str], str] = {}
    key_conflicts = 0
    for row in rows:
        prior = keys.setdefault(row.key, row.semantic_hash)
        if prior != row.semantic_hash:
            key_conflicts += 1
    config_violations = sum(not row.provenance.configuration_hash for row in rows)
    checksum_violations = sum(
        not row.provenance.raw_series_checksum
        or not row.provenance.normalized_series_checksum
        for row in rows
    )
    identity = sum(
        row.is_historically_usable and not row.instrument_identifier for row in rows
    )
    adjustment = sum(
        row.provenance.adjustment_mode is PriceAdjustmentMode.UNKNOWN for row in rows
    )
    duplicate_bars = sum(
        len(row.provenance.source_bar_timestamps)
        != len(set(row.provenance.source_bar_timestamps))
        for row in rows
    )
    incomplete = sum(
        row.is_historically_usable and not row.provenance.complete for row in rows
    )
    exclusions_without_reason = sum(
        not row.is_historically_usable and not row.provenance.exclusion_reasons
        for row in rows
    )
    determinism_status = _status(
        semantic + key_conflicts + config_violations + checksum_violations
    )
    leakage_status = _status(future + future_confirmation + post_retest)
    identity_status = _status(identity)
    series_status = _status(adjustment + duplicate_bars)
    lineage_status = _status(incomplete + exclusions_without_reason)
    statuses = (
        determinism_status,
        leakage_status,
        identity_status,
        series_status,
        lineage_status,
    )
    return BreakoutReferenceIntegrityAudit(
        records_checked=len(rows),
        future_bar_violations=future,
        future_swing_confirmation_violations=future_confirmation,
        post_candidate_retest_violations=post_retest,
        outcome_derived_field_violations=0,
        future_market_state_violations=0,
        semantic_hash_violations=semantic,
        duplicate_key_conflicts=key_conflicts,
        configuration_hash_violations=config_violations,
        source_checksum_violations=checksum_violations,
        identity_violations=identity,
        listing_interval_violations=0,
        adjustment_consistency_violations=adjustment,
        duplicate_bar_violations=duplicate_bars,
        invalid_ohlc_violations=0,
        incomplete_ready_lineage=incomplete,
        exclusions_without_reason=exclusions_without_reason,
        determinism_status=determinism_status,
        leakage_status=leakage_status,
        identity_status=identity_status,
        series_status=series_status,
        lineage_status=lineage_status,
        overall_status=(
            BreakoutIntegrityStatus.PASS
            if all(status is BreakoutIntegrityStatus.PASS for status in statuses)
            else BreakoutIntegrityStatus.FAIL
        ),
        production_influence=False,
    )


def apply_reconstructed_breakout_references(
    observations: Sequence[DirectionalObservation],
    records: Sequence[BreakoutReferenceReconstructionRecord],
    *,
    reference_method: BreakoutReferenceMethod = (
        BreakoutReferenceMethod.PRIOR_SWING_HIGH
    ),
) -> tuple[DirectionalObservation, ...]:
    by_observation = {
        (row.historical_symbol, row.candidate_observation_date): row
        for row in records
        if row.evidence.reference_level_type is reference_method
    }
    enriched: list[DirectionalObservation] = []
    for observation in observations:
        record = by_observation.get((observation.symbol, observation.observed_at))
        if record is None:
            enriched.append(observation)
            continue
        features = dict(observation.feature_values)
        for key in ("resistance", "target_1"):
            features.pop(key, None)
        if record.readiness_status is BreakoutReferenceReadinessStatus.READY:
            evidence = record.evidence
            if evidence.candidate_session_price is not None:
                features["price"] = float(evidence.candidate_session_price)
            if evidence.primary_reference_level is not None:
                features["resistance"] = float(evidence.primary_reference_level)
            if evidence.support_level is not None:
                features["support"] = float(evidence.support_level)
            if evidence.atr is not None:
                features["atr"] = float(evidence.atr)
        enriched.append(
            replace(
                observation,
                source=(
                    f"{observation.source}|{BREAKOUT_REFERENCE_DATASET_VERSION}:"
                    f"{record.semantic_hash[:12]}"
                ),
                feature_values=tuple(sorted(features.items())),
            )
        )
    return tuple(enriched)


def render_breakout_reference_reconstruction(
    result: BreakoutReferencePersistenceResult,
) -> tuple[str, ...]:
    persistence = "DRY RUN - no records written" if result.dry_run else str(result.path)
    return (
        "Point-in-Time Breakout Reference Reconstruction",
        f"Dataset: {BREAKOUT_REFERENCE_DATASET_VERSION}",
        f"Created: {result.created}",
        f"Reused: {result.reused}",
        f"Skipped: {result.skipped}",
        f"Excluded: {result.excluded}",
        f"Failed: {result.failed}",
        f"Total Stored Records: {result.total_records}",
        f"Persistence: {persistence}",
        "PRODUCTION_INFLUENCE=false",
    )


def render_breakout_reference_readiness(
    report: BreakoutHistoricalReadinessReport,
) -> tuple[str, ...]:
    return (
        "Breakout Reference Historical Readiness",
        f"Dataset Version: {report.dataset_version}",
        f"Total Replay Candidates: {report.total_replay_candidates}",
        f"Unique Symbols: {report.unique_symbols}",
        f"Date Range: {_date_range(report.date_range)}",
        f"Candidates Attempted: {report.candidates_attempted}",
        f"Ready Records: {report.ready_records}",
        f"Valid REFERENCE_NOT_FORMED Records: {report.reference_not_formed_records}",
        f"Unreconstructable Records: {report.unreconstructable_records}",
        f"Readiness Percentage: {report.readiness_percentage}%",
        f"Availability By Year: {_coverage_summary(report.availability_by_year)}",
        "Availability By Symbol: "
        f"{_coverage_summary(report.availability_by_symbol, 10)}",
        "Availability By Data Source: "
        f"{_coverage_summary(report.availability_by_source)}",
        "Availability By Reference Method: "
        f"{_coverage_summary(report.availability_by_reference_method)}",
        "Availability By Timing Semantics: "
        f"{_coverage_summary(report.availability_by_timing_semantics)}",
        f"Top Exclusion Reasons: {_counts(report.exclusion_reason_counts)}",
        f"Median Usable Lookback: {_optional(report.median_usable_lookback)}",
        f"Minimum Usable Lookback: {_optional(report.minimum_usable_lookback)}",
        f"Ambiguous Cutoff Count: {report.ambiguous_cutoff_count}",
        f"Corporate-Action Ambiguity Count: {report.corporate_action_ambiguity_count}",
        f"Unresolved Symbol Count: {report.unresolved_symbol_count}",
        f"Provenance Completeness Rate: {report.provenance_completeness_rate}%",
        "Deterministic Reconstruction Check: "
        f"{'PASS' if report.deterministic_reconstruction_check else 'FAIL'}",
        f"Leakage Audit Result: {report.leakage_audit_result.value}",
        f"Overall Readiness Conclusion: {report.conclusion.value}",
        "Ready requires at least 95% usable history, complete provenance, and "
        "passing determinism/leakage audits.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_breakout_reference_integrity(
    audit: BreakoutReferenceIntegrityAudit,
) -> tuple[str, ...]:
    return (
        "Breakout Reference Integrity Audit",
        f"Records Checked: {audit.records_checked}",
        f"Future Bar Violations: {audit.future_bar_violations}",
        "Future Swing Confirmation Violations: "
        f"{audit.future_swing_confirmation_violations}",
        f"Post-Candidate Retest Violations: {audit.post_candidate_retest_violations}",
        f"Outcome-Derived Field Violations: {audit.outcome_derived_field_violations}",
        f"Future Market-State Violations: {audit.future_market_state_violations}",
        f"Semantic Hash Violations: {audit.semantic_hash_violations}",
        f"Duplicate-Key Conflicts: {audit.duplicate_key_conflicts}",
        f"Configuration Hash Violations: {audit.configuration_hash_violations}",
        f"Source Checksum Violations: {audit.source_checksum_violations}",
        f"Identity Violations: {audit.identity_violations}",
        f"Listing-Interval Violations: {audit.listing_interval_violations}",
        f"Adjustment Consistency Violations: {audit.adjustment_consistency_violations}",
        f"Duplicate-Bar Violations: {audit.duplicate_bar_violations}",
        f"Invalid-OHLC Violations: {audit.invalid_ohlc_violations}",
        f"Incomplete Ready Lineage: {audit.incomplete_ready_lineage}",
        f"Exclusions Without Reason: {audit.exclusions_without_reason}",
        f"Determinism: {audit.determinism_status.value}",
        f"Future Leakage: {audit.leakage_status.value}",
        f"Identity: {audit.identity_status.value}",
        f"Series Integrity: {audit.series_status.value}",
        f"Lineage: {audit.lineage_status.value}",
        f"Overall Integrity: {audit.overall_status.value}",
        "PRODUCTION_INFLUENCE=false",
    )


def render_breakout_reference_provenance(
    records: Sequence[BreakoutReferenceReconstructionRecord],
    *,
    limit: int = 20,
) -> tuple[str, ...]:
    rows = tuple(sorted(records, key=_record_sort_key))
    lines = [
        "Breakout Reference Provenance",
        f"Records: {len(rows)}",
        "PRODUCTION_INFLUENCE=false",
    ]
    for row in rows[:limit]:
        lines.append(
            f"- {row.candidate_id} {row.historical_symbol} "
            f"{row.candidate_observation_date}: {row.readiness_status.value}; "
            f"source={row.provenance.source_provider}; "
            f"cutoff={row.cutoff_semantics.value}; "
            f"algorithm={row.provenance.algorithm_version}; "
            f"semantic_hash={row.semantic_hash}; "
            f"raw_checksum={row.provenance.raw_series_checksum}; "
            f"normalized_checksum={row.provenance.normalized_series_checksum}"
        )
    return tuple(lines)


def render_breakout_reference_sample(
    records: Sequence[BreakoutReferenceReconstructionRecord],
    *,
    limit: int = 20,
) -> tuple[str, ...]:
    rows = tuple(sorted(records, key=_record_sort_key))[:limit]
    lines = [
        "Point-in-Time Breakout Reference Sample",
        f"Records Shown: {len(rows)}",
        "PRODUCTION_INFLUENCE=false",
    ]
    for row in rows:
        level = row.evidence.primary_reference_level
        lines.append(
            f"- {row.historical_symbol} {row.candidate_observation_date} "
            f"candidate={row.candidate_id} status={row.readiness_status.value} "
            f"method={row.evidence.reference_level_type.value} "
            f"reference={_optional(level)} price="
            f"{_optional(row.evidence.candidate_session_price)} "
            f"cutoff={_optional(row.last_bar_timestamp_allowed)} "
            f"bars={row.usable_bars}"
        )
    return tuple(lines)


def export_breakout_reference_json(
    payload: object,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def export_breakout_reference_csv(
    records: Sequence[BreakoutReferenceReconstructionRecord],
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        "candidate_id",
        "replay_run_id",
        "instrument_identifier",
        "historical_symbol",
        "exchange",
        "candidate_observation_date",
        "cutoff_semantics",
        "last_bar_timestamp_allowed",
        "last_bar_timestamp_used",
        "reference_method",
        "reference_level",
        "candidate_price",
        "distance_to_reference",
        "atr_normalized_distance",
        "touch_count",
        "usable_bars",
        "readiness_status",
        "source_provider",
        "algorithm_version",
        "configuration_hash",
        "semantic_hash",
        "production_influence",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(records, key=_record_sort_key):
            writer.writerow(
                {
                    "candidate_id": row.candidate_id,
                    "replay_run_id": row.replay_run_id,
                    "instrument_identifier": row.instrument_identifier,
                    "historical_symbol": row.historical_symbol,
                    "exchange": row.exchange,
                    "candidate_observation_date": row.candidate_observation_date,
                    "cutoff_semantics": row.cutoff_semantics.value,
                    "last_bar_timestamp_allowed": row.last_bar_timestamp_allowed,
                    "last_bar_timestamp_used": row.last_bar_timestamp_used,
                    "reference_method": row.evidence.reference_level_type.value,
                    "reference_level": row.evidence.primary_reference_level,
                    "candidate_price": row.evidence.candidate_session_price,
                    "distance_to_reference": row.evidence.distance_to_reference,
                    "atr_normalized_distance": row.evidence.atr_normalized_distance,
                    "touch_count": row.evidence.touch_count,
                    "usable_bars": row.usable_bars,
                    "readiness_status": row.readiness_status.value,
                    "source_provider": row.provenance.source_provider,
                    "algorithm_version": row.provenance.algorithm_version,
                    "configuration_hash": row.provenance.configuration_hash,
                    "semantic_hash": row.semantic_hash,
                    "production_influence": row.production_influence,
                }
            )
    return path


def filter_breakout_reference_records(
    records: Sequence[BreakoutReferenceReconstructionRecord],
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    symbol: str | None = None,
    candidate_id: str | None = None,
    replay_run_id: str | None = None,
    reference_method: BreakoutReferenceMethod | None = None,
) -> tuple[BreakoutReferenceReconstructionRecord, ...]:
    if from_date is not None and to_date is not None and to_date < from_date:
        raise ValueError("to_date must be on or after from_date")
    normalized_symbol = symbol.strip().upper() if symbol else None
    return tuple(
        row
        for row in sorted(records, key=_record_sort_key)
        if from_date is None or row.candidate_observation_date >= from_date
        if to_date is None or row.candidate_observation_date <= to_date
        if normalized_symbol is None or row.historical_symbol == normalized_symbol
        if candidate_id is None or row.candidate_id == candidate_id
        if replay_run_id is None or row.replay_run_id == replay_run_id
        if reference_method is None
        or row.evidence.reference_level_type is reference_method
    )


def resolve_breakout_reference_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("ALPHA_BREAKOUT_REFERENCE_DATASET")
    return Path(configured) if configured else DEFAULT_BREAKOUT_REFERENCE_PATH


def parse_breakout_reference_method(value: str) -> BreakoutReferenceMethod:
    try:
        return BreakoutReferenceMethod(value.strip().upper().replace("-", "_"))
    except ValueError as error:
        supported = ", ".join(
            method.value.lower() for method in BreakoutReferenceMethod
        )
        raise ValueError(
            f"unsupported reference method; choose one of: {supported}"
        ) from error


def source_bar_from_values(
    *,
    observed_on: date,
    open_price: object,
    high_price: object,
    low_price: object,
    close_price: object,
    volume: object,
    exchange: str = "NSE",
    adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW_UNADJUSTED,
) -> BreakoutSourceBar:
    observed_at = _session_close(observed_on)
    if observed_at is None:
        raise ValueError("observed_on is required")
    return BreakoutSourceBar(
        observed_at=observed_at,
        open_price=_decimal(open_price),
        high_price=_decimal(high_price),
        low_price=_decimal(low_price),
        close_price=_decimal(close_price),
        volume=None if volume is None else _decimal(volume),
        exchange=exchange,
        adjustment_mode=adjustment_mode,
    )


def _empty_evidence(
    method: BreakoutReferenceMethod,
    *,
    observation: BreakoutSourceBar | None = None,
) -> BreakoutReferenceEvidence:
    return BreakoutReferenceEvidence(
        primary_reference_level=None,
        reference_level_type=method,
        formation_start=None,
        confirmation_end=None,
        touch_count=0,
        touch_timestamps=(),
        tolerance=None,
        clustering_rule="unavailable",
        lookback_length=0,
        consolidation_high=None,
        consolidation_low=None,
        consolidation_width=None,
        prior_swing_high=None,
        base_duration=None,
        volume_baseline=None,
        candidate_session_price=(
            observation.close_price if observation is not None else None
        ),
        distance_to_reference=None,
        atr=None,
        atr_normalized_distance=None,
        breakout_attempt_evidence="UNAVAILABLE",
        breakout_confirmation_evidence="UNAVAILABLE",
        close_location_evidence=(
            _close_location(observation) if observation is not None else None
        ),
        retest_evidence="UNAVAILABLE",
        support_level=None,
        observation_bar_timestamp=(
            observation.observed_at if observation is not None else None
        ),
    )


def _identity_status(
    candidate: BreakoutReconstructionCandidate,
    identity: HistoricalSecurityIdentity,
) -> tuple[BreakoutReferenceReadinessStatus | None, str]:
    if (
        not identity.resolved
        or not identity.instrument_identifier
        or identity.historical_symbol.upper() != candidate.historical_symbol
        or identity.exchange.upper() != candidate.exchange
    ):
        return (
            BreakoutReferenceReadinessStatus.SYMBOL_IDENTITY_UNRESOLVED,
            "POINT_IN_TIME_SYMBOL_IDENTITY_UNRESOLVED",
        )
    if identity.listing_date and candidate.observation_date < identity.listing_date:
        return (
            BreakoutReferenceReadinessStatus.LISTING_DATE_VIOLATION,
            "CANDIDATE_PRECEDES_LISTING_DATE",
        )
    if identity.delisting_date and candidate.observation_date > identity.delisting_date:
        return (
            BreakoutReferenceReadinessStatus.DELISTING_DATE_VIOLATION,
            "CANDIDATE_FOLLOWS_DELISTING_DATE",
        )
    return None, ""


def _breakout_states(
    *,
    price: Decimal,
    reference: Decimal | None,
    tolerance: Decimal | None,
    volume_ratio: Decimal | None,
    close_location: Decimal | None,
    required_volume: Decimal,
) -> tuple[str, str]:
    if reference is None:
        return "NO_REFERENCE", "UNAVAILABLE"
    tolerance = tolerance or _ZERO
    if price > reference + tolerance:
        attempt = "CLOSE_ABOVE_REFERENCE"
    elif price >= reference - tolerance:
        attempt = "AT_REFERENCE"
    else:
        return "BELOW_REFERENCE", "NOT_CONFIRMED"
    if attempt != "CLOSE_ABOVE_REFERENCE":
        return attempt, "ATTEMPT_ONLY"
    if volume_ratio is None:
        return attempt, "ABOVE_REFERENCE_VOLUME_UNAVAILABLE"
    if volume_ratio >= required_volume and (close_location or _ZERO) >= Decimal("0.65"):
        return attempt, "CONFIRMED_BY_CLOSE_AND_VOLUME"
    if volume_ratio < required_volume:
        return attempt, "ABOVE_REFERENCE_WEAK_VOLUME"
    return attempt, "ABOVE_REFERENCE_WEAK_CLOSE"


def _retest_state(
    formation_bars: Sequence[BreakoutSourceBar],
    observation: BreakoutSourceBar,
    reference: _ReferenceResult,
) -> str:
    if reference.level is None or reference.confirmation_end is None:
        return "UNAVAILABLE"
    tolerance = reference.tolerance or _ZERO
    post_formation = tuple(
        bar for bar in formation_bars if bar.observed_at > reference.confirmation_end
    )
    breakout_seen = any(
        bar.close_price > reference.level + tolerance for bar in post_formation
    )
    if not breakout_seen:
        return "NO_PRIOR_BREAKOUT"
    if (
        observation.low_price <= reference.level + tolerance
        and observation.close_price >= reference.level - tolerance
    ):
        return "RETEST_HELD"
    if observation.close_price < reference.level - tolerance:
        return "RETEST_FAILED"
    return "RETEST_NOT_PRESENT"


def _touch_tolerance(
    level: Decimal,
    bars: Sequence[BreakoutSourceBar],
    configuration: BreakoutReferenceConfiguration,
) -> Decimal:
    percentage = level * configuration.touch_tolerance_pct
    atr = _atr(bars, configuration.atr_period) or _ZERO
    return _quantize(max(percentage, atr * Decimal("0.15")))


def _atr(
    bars: Sequence[BreakoutSourceBar],
    period: int,
) -> Decimal | None:
    if len(bars) < 2:
        return None
    ranges: list[Decimal] = []
    for previous, current in zip(bars, bars[1:], strict=False):
        ranges.append(
            max(
                current.high_price - current.low_price,
                abs(current.high_price - previous.close_price),
                abs(current.low_price - previous.close_price),
            )
        )
    return _mean_decimal(ranges[-period:])


def _close_location(bar: BreakoutSourceBar) -> Decimal | None:
    width = bar.high_price - bar.low_price
    if width <= _ZERO:
        return None
    return _quantize((bar.close_price - bar.low_price) / width)


def _distance(price: Decimal, reference: Decimal | None) -> Decimal | None:
    if reference is None or reference <= _ZERO:
        return None
    return _quantize((price - reference) / reference)


def _relative_width(
    high: Decimal | None,
    low: Decimal | None,
) -> Decimal | None:
    if high is None or low is None or low <= _ZERO:
        return None
    return _quantize((high - low) / low)


def _base_duration(reference: _ReferenceResult) -> int | None:
    if reference.formation_start is None or reference.confirmation_end is None:
        return None
    return (
        reference.confirmation_end.date() - reference.formation_start.date()
    ).days + 1


def _missing_session_ratio(
    bars: Sequence[BreakoutSourceBar],
    sessions: Sequence[date],
    observation_date: date,
    requested: int,
) -> Decimal:
    if not bars:
        return _ZERO
    first_observed = bars[0].observed_at.date()
    expected = tuple(
        day for day in sessions if first_observed <= day <= observation_date
    )[-requested:]
    if not expected:
        return _ZERO
    observed = {bar.observed_at.date() for bar in bars}
    missing = sum(day not in observed for day in expected)
    return _quantize(Decimal(missing) / Decimal(len(expected)))


def _discontinuity_dates(
    bars: Sequence[BreakoutSourceBar],
    threshold: Decimal,
) -> tuple[date, ...]:
    dates: list[date] = []
    for previous, current in zip(bars, bars[1:], strict=False):
        if previous.close_price <= _ZERO:
            continue
        change = abs(current.close_price - previous.close_price) / previous.close_price
        if change >= threshold:
            dates.append(current.observed_at.date())
    return tuple(dates)


def _previous_session(
    sessions: Sequence[date],
    target: date,
    *,
    inclusive: bool,
) -> date | None:
    candidates = tuple(
        session
        for session in sessions
        if (session <= target if inclusive else session < target)
    )
    return max(candidates) if candidates else None


def _session_close(day: date | None) -> datetime | None:
    if day is None:
        return None
    return datetime.combine(day, _MARKET_CLOSE, tzinfo=_IST)


def _as_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("decision timestamp must be timezone-aware")
    return value.astimezone(_IST)


def _timezone_is_ist(value: datetime) -> bool:
    if value.tzinfo is None:
        return False
    return value.utcoffset() == datetime(2024, 1, 1, tzinfo=_IST).utcoffset()


def _bars_checksum(
    bars: Sequence[BreakoutSourceBar],
    *,
    preserve_order: bool,
) -> str:
    rows = list(bars)
    if not preserve_order:
        rows.sort(key=lambda bar: bar.observed_at)
    payload = [
        {
            "observed_at": bar.observed_at.isoformat(),
            "open": str(bar.open_price),
            "high": str(bar.high_price),
            "low": str(bar.low_price),
            "close": str(bar.close_price),
            "volume": None if bar.volume is None else str(bar.volume),
            "exchange": bar.exchange,
            "adjustment_mode": bar.adjustment_mode.value,
        }
        for bar in rows
    ]
    return _hash(payload)


def _dataset(
    records: Sequence[BreakoutReferenceReconstructionRecord],
) -> BreakoutReferenceDataset:
    rows = tuple(sorted(records, key=_record_sort_key))
    created = max(
        (row.provenance.reconstruction_timestamp for row in rows),
        default=datetime(1970, 1, 1, tzinfo=UTC),
    )
    return BreakoutReferenceDataset(
        manifest=BreakoutReferenceManifest(
            dataset_version=BREAKOUT_REFERENCE_DATASET_VERSION,
            schema_version=BREAKOUT_REFERENCE_SCHEMA_VERSION,
            created_at=created,
            record_count=len(rows),
            algorithm_versions=tuple(
                sorted({row.provenance.algorithm_version for row in rows})
            ),
            configuration_hashes=tuple(
                sorted({row.provenance.configuration_hash for row in rows})
            ),
            source_datasets=tuple(
                sorted({row.provenance.source_dataset for row in rows})
            ),
            dataset_semantic_hash=_dataset_hash(rows),
            production_influence=False,
        ),
        records=rows,
    )


def _empty_dataset() -> BreakoutReferenceDataset:
    return _dataset(())


def _dataset_hash(records: Sequence[BreakoutReferenceReconstructionRecord]) -> str:
    return _hash([row.semantic_hash for row in sorted(records, key=_record_sort_key)])


def _record_sort_key(
    row: BreakoutReferenceReconstructionRecord,
) -> tuple[date, str, str, str]:
    return (
        row.candidate_observation_date,
        row.historical_symbol,
        row.candidate_id,
        row.evidence.reference_level_type.value,
    )


def _coverage(
    records: Sequence[BreakoutReferenceReconstructionRecord],
    key: Any,
) -> tuple[BreakoutReferenceCoverageRow, ...]:
    grouped: dict[str, list[BreakoutReferenceReconstructionRecord]] = defaultdict(list)
    for row in records:
        grouped[str(key(row))].append(row)
    return tuple(
        BreakoutReferenceCoverageRow(
            key=group,
            candidates=len(rows),
            historically_usable=sum(row.is_historically_usable for row in rows),
            availability_pct=_percentage(
                sum(row.is_historically_usable for row in rows), len(rows)
            ),
        )
        for group, rows in sorted(grouped.items())
    )


def _readiness_conclusion(
    *,
    total: int,
    readiness: Decimal,
    ambiguous: int,
    unresolved: int,
    provenance_rate: Decimal,
    exclusions: Counter[str],
    integrity: BreakoutReferenceIntegrityAudit,
) -> BreakoutHistoricalReadinessConclusion:
    if total == 0:
        return BreakoutHistoricalReadinessConclusion.BREAKOUT_HISTORY_NOT_READY
    if ambiguous / total >= 0.10:
        return BreakoutHistoricalReadinessConclusion(
            "BREAKOUT_HISTORY_BLOCKED_BY_CUTOFF_AMBIGUITY"
        )
    if unresolved / total >= 0.10:
        return BreakoutHistoricalReadinessConclusion(
            "BREAKOUT_HISTORY_BLOCKED_BY_SYMBOL_IDENTITY"
        )
    if (
        provenance_rate < Decimal("100")
        or integrity.lineage_status is BreakoutIntegrityStatus.FAIL
    ):
        return (
            BreakoutHistoricalReadinessConclusion.BREAKOUT_HISTORY_BLOCKED_BY_PROVENANCE
        )
    source_gaps = sum(
        exclusions[status.value]
        for status in (
            BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
            BreakoutReferenceReadinessStatus.MISSING_BARS,
            BreakoutReferenceReadinessStatus.INSUFFICIENT_LOOKBACK,
        )
    )
    if source_gaps / total >= 0.30:
        return BreakoutHistoricalReadinessConclusion(
            "BREAKOUT_HISTORY_BLOCKED_BY_SOURCE_GAPS"
        )
    if (
        readiness >= Decimal("95")
        and integrity.overall_status is BreakoutIntegrityStatus.PASS
    ):
        return BreakoutHistoricalReadinessConclusion.BREAKOUT_HISTORY_READY
    if readiness >= Decimal("70"):
        return BreakoutHistoricalReadinessConclusion.BREAKOUT_HISTORY_PARTIALLY_READY
    return BreakoutHistoricalReadinessConclusion.BREAKOUT_HISTORY_NOT_READY


def _status(violations: int) -> BreakoutIntegrityStatus:
    return (
        BreakoutIntegrityStatus.PASS
        if violations == 0
        else BreakoutIntegrityStatus.FAIL
    )


def _percentage(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return _ZERO.quantize(Decimal("0.01"))
    return (Decimal(numerator) * _HUNDRED / Decimal(denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _mean_decimal(values: Iterable[Decimal]) -> Decimal | None:
    rows = tuple(values)
    if not rows:
        return None
    return _quantize(sum(rows, _ZERO) / Decimal(len(rows)))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_SIX, rounding=ROUND_HALF_UP)


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else _datetime(value)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_tuple(value: str | None) -> tuple[str, ...]:
    return () if value is None else (value,)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("expected mapping payload")
    return value


def _hash(payload: object) -> str:
    raw = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def _jsonable(value: object) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        data = asdict(cast(Any, value))
        return {key: _jsonable(item) for key, item in data.items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_jsonable(item) for item in value]
    return value


def _date_range(value: tuple[date | None, date | None]) -> str:
    return f"{_optional(value[0])} to {_optional(value[1])}"


def _coverage_summary(
    rows: Sequence[BreakoutReferenceCoverageRow],
    limit: int | None = None,
) -> str:
    selected = rows if limit is None else rows[:limit]
    return (
        "; ".join(
            f"{row.key}={row.historically_usable}/{row.candidates} "
            f"({row.availability_pct}%)"
            for row in selected
        )
        or "unavailable"
    )


def _counts(rows: Sequence[tuple[str, int]]) -> str:
    return "; ".join(f"{key}={value}" for key, value in rows) or "none"


def _optional(value: object) -> str:
    return "unavailable" if value is None else str(value)


__all__ = [
    "BREAKOUT_REFERENCE_ALGORITHM_VERSION",
    "BREAKOUT_REFERENCE_DATASET_VERSION",
    "BREAKOUT_REFERENCE_SCHEMA_VERSION",
    "DEFAULT_BREAKOUT_REFERENCE_PATH",
    "BreakoutCutoffSemantics",
    "BreakoutHistoricalReadinessConclusion",
    "BreakoutHistoricalReadinessReport",
    "BreakoutIntegrityStatus",
    "BreakoutReconstructionCandidate",
    "BreakoutReferenceConfiguration",
    "BreakoutReferenceDataset",
    "BreakoutReferenceEvidence",
    "BreakoutReferenceIntegrityAudit",
    "BreakoutReferenceManifest",
    "BreakoutReferenceMethod",
    "BreakoutReferenceOperation",
    "BreakoutReferencePersistenceResult",
    "BreakoutReferenceProvenance",
    "BreakoutReferenceReadinessStatus",
    "BreakoutReferenceReconstructionRecord",
    "BreakoutReferenceRepository",
    "BreakoutSourceBar",
    "CorporateActionEvent",
    "HistoricalSecurityIdentity",
    "LegacyDateCutoffPolicy",
    "PointInTimeBreakoutReferenceEngine",
    "PriceAdjustmentMode",
    "apply_reconstructed_breakout_references",
    "audit_breakout_reference_integrity",
    "build_breakout_historical_readiness_report",
    "export_breakout_reference_csv",
    "export_breakout_reference_json",
    "filter_breakout_reference_records",
    "parse_breakout_reference_method",
    "render_breakout_reference_integrity",
    "render_breakout_reference_provenance",
    "render_breakout_reference_readiness",
    "render_breakout_reference_reconstruction",
    "render_breakout_reference_sample",
    "resolve_breakout_reference_path",
    "source_bar_from_values",
]
