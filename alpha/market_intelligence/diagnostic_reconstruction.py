from __future__ import annotations

import csv
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pandas as pd

from alpha.market_intelligence.benchmark import (
    BenchmarkFeatureCompleteness,
    BenchmarkState,
    BenchmarkStateBuilder,
    canonical_benchmark_configuration,
)
from alpha.market_intelligence.snapshots import MARKET_STATE_CLASSIFIER_VERSION
from alpha.provenance import (
    HistoricalEraAssignmentStatus,
    build_historical_manifest_audit,
    current_market_classifier_fingerprint,
)

DIAGNOSTIC_MARKET_STATE_DATASET_VERSION = "diagnostic-market-state-reconstruction-v1"
DEFAULT_DIAGNOSTIC_MARKET_STATE_PATH = Path(
    ".alpha/diagnostic_market_state_reconstructions.json"
)


class DiagnosticAuthoritativeStatus(StrEnum):
    DIAGNOSTIC_RECONSTRUCTED = "DIAGNOSTIC_RECONSTRUCTED"
    DIAGNOSTIC_PARTIAL = "DIAGNOSTIC_PARTIAL"
    DIAGNOSTIC_MINIMUM_VIABLE = "DIAGNOSTIC_MINIMUM_VIABLE"
    DIAGNOSTIC_UNAVAILABLE = "DIAGNOSTIC_UNAVAILABLE"


class DiagnosticInputCompleteness(StrEnum):
    COMPLETE_DIAGNOSTIC = "COMPLETE_DIAGNOSTIC"
    PARTIAL_DIAGNOSTIC = "PARTIAL_DIAGNOSTIC"
    MINIMUM_VIABLE_DIAGNOSTIC = "MINIMUM_VIABLE_DIAGNOSTIC"
    INSUFFICIENT_DIAGNOSTIC = "INSUFFICIENT_DIAGNOSTIC"
    UNAVAILABLE = "UNAVAILABLE"


class DiagnosticReconstructionQuality(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNUSABLE = "UNUSABLE"


class DiagnosticCompatibilityLabel(StrEnum):
    PERSISTED_EXACT = "PERSISTED_EXACT"
    EXACT_FINGERPRINT = "EXACT_FINGERPRINT"
    VERIFIED_MANIFEST = "VERIFIED_MANIFEST"
    SEMANTIC_COMPATIBILITY_ONLY = "SEMANTIC_COMPATIBILITY_ONLY"
    FORWARD_COMPATIBLE_DIAGNOSTIC = "FORWARD_COMPATIBLE_DIAGNOSTIC"
    UNKNOWN = "UNKNOWN"


class DiagnosticSectorAvailability(StrEnum):
    POINT_IN_TIME_SECTOR_STATE = "POINT_IN_TIME_SECTOR_STATE"
    CURRENT_MAPPING_DIAGNOSTIC_ONLY = "CURRENT_MAPPING_DIAGNOSTIC_ONLY"
    PARTIAL_SECTOR_STATE = "PARTIAL_SECTOR_STATE"
    SECTOR_STATE_UNAVAILABLE = "SECTOR_STATE_UNAVAILABLE"


class DiagnosticBreadthSourceType(StrEnum):
    DIAGNOSTIC_CURRENT_UNIVERSE_RECONSTRUCTION = (
        "DIAGNOSTIC_CURRENT_UNIVERSE_RECONSTRUCTION"
    )
    BREADTH_UNAVAILABLE = "BREADTH_UNAVAILABLE"


class TransparentReferenceState(StrEnum):
    STRONG_POSITIVE = "STRONG_POSITIVE"
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    STRONG_NEGATIVE = "STRONG_NEGATIVE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    DISTRIBUTION = "DISTRIBUTION"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"


class RegimeComparisonClass(StrEnum):
    ALL_MATCH = "ALL_MATCH"
    RECORDED_AND_REPLAY_MATCH = "RECORDED_AND_REPLAY_MATCH"
    REPLAY_AND_REFERENCE_DIRECTIONAL_MATCH = "REPLAY_AND_REFERENCE_DIRECTIONAL_MATCH"
    RECORDED_NEUTRAL_REPLAY_NON_NEUTRAL = "RECORDED_NEUTRAL_REPLAY_NON_NEUTRAL"
    RECORDED_NON_NEUTRAL_REPLAY_NEUTRAL = "RECORDED_NON_NEUTRAL_REPLAY_NEUTRAL"
    RECORDED_AND_REPLAY_SIGN_CONFLICT = "RECORDED_AND_REPLAY_SIGN_CONFLICT"
    REPLAY_AND_REFERENCE_SIGN_CONFLICT = "REPLAY_AND_REFERENCE_SIGN_CONFLICT"
    RECORDED_DEFAULTED = "RECORDED_DEFAULTED"
    RECONSTRUCTION_UNAVAILABLE = "RECONSTRUCTION_UNAVAILABLE"


class NeutralCollapseFinding(StrEnum):
    CONFIRMED = "CONFIRMED"
    PARTIALLY_CONFIRMED = "PARTIALLY_CONFIRMED"
    OVERTURNED = "OVERTURNED"
    NOT_TESTABLE = "NOT_TESTABLE"


class DiagnosticConclusion(StrEnum):
    DIAGNOSTIC_RECONSTRUCTION_RECOVERS_REGIME_DIVERSITY = (
        "DIAGNOSTIC_RECONSTRUCTION_RECOVERS_REGIME_DIVERSITY"
    )
    RECORDED_NEUTRAL_COLLAPSE_WAS_PRIMARILY_DATA_FALLBACK = (
        "RECORDED_NEUTRAL_COLLAPSE_WAS_PRIMARILY_DATA_FALLBACK"
    )
    RECORDED_NEUTRAL_COLLAPSE_REMAINS_AFTER_RECONSTRUCTION = (
        "RECORDED_NEUTRAL_COLLAPSE_REMAINS_AFTER_RECONSTRUCTION"
    )
    RECONSTRUCTED_REGIME_HAS_USEFUL_OUTCOME_SEPARATION = (
        "RECONSTRUCTED_REGIME_HAS_USEFUL_OUTCOME_SEPARATION"
    )
    RECONSTRUCTED_REGIME_HAS_LIMITED_OUTCOME_SEPARATION = (
        "RECONSTRUCTED_REGIME_HAS_LIMITED_OUTCOME_SEPARATION"
    )
    REGIME_INTERVENTION_REMAINS_LOW_VALUE = "REGIME_INTERVENTION_REMAINS_LOW_VALUE"
    MOMENTUM_MARKET_STATE_INTERACTION_IS_PRIMARY_RESEARCH_FINDING = (
        "MOMENTUM_MARKET_STATE_INTERACTION_IS_PRIMARY_RESEARCH_FINDING"
    )
    RETRACEMENT_REGIME_INTERACTION_IS_PRIMARY_RESEARCH_FINDING = (
        "RETRACEMENT_REGIME_INTERACTION_IS_PRIMARY_RESEARCH_FINDING"
    )
    CANDIDATE_SELECTION_EFFECT_REMAINS_PRIMARY = (
        "CANDIDATE_SELECTION_EFFECT_REMAINS_PRIMARY"
    )
    DIAGNOSTIC_DATA_QUALITY_IS_INSUFFICIENT = "DIAGNOSTIC_DATA_QUALITY_IS_INSUFFICIENT"
    NO_SINGLE_REGIME_RESEARCH_CONCLUSION = "NO_SINGLE_REGIME_RESEARCH_CONCLUSION"


class DiagnosticNextMilestone(StrEnum):
    COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY = (
        "COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY"
    )
    BUILD_POINT_IN_TIME_BREADTH_HISTORY = "BUILD_POINT_IN_TIME_BREADTH_HISTORY"
    BUILD_POINT_IN_TIME_SECTOR_HISTORY = "BUILD_POINT_IN_TIME_SECTOR_HISTORY"
    AUDIT_MARKET_REGIME_THRESHOLD_DEFINITIONS = (
        "AUDIT_MARKET_REGIME_THRESHOLD_DEFINITIONS"
    )
    AUDIT_REGIME_INTERVENTION_POLICY = "AUDIT_REGIME_INTERVENTION_POLICY"
    AUDIT_MOMENTUM_MARKET_STATE_INTERACTION = "AUDIT_MOMENTUM_MARKET_STATE_INTERACTION"
    AUDIT_RETRACEMENT_SIGNAL_DEFINITION = "AUDIT_RETRACEMENT_SIGNAL_DEFINITION"
    AUDIT_CANDIDATE_GENERATION_BY_MARKET_STATE = (
        "AUDIT_CANDIDATE_GENERATION_BY_MARKET_STATE"
    )
    ACCEPT_LEGACY_REGIME_ANALYSIS_AS_DIAGNOSTIC_ONLY = (
        "ACCEPT_LEGACY_REGIME_ANALYSIS_AS_DIAGNOSTIC_ONLY"
    )
    INSUFFICIENT_EVIDENCE_COLLECT_MORE_DATA = "INSUFFICIENT_EVIDENCE_COLLECT_MORE_DATA"


@dataclass(frozen=True, slots=True)
class DiagnosticMarketBreadth:
    source_type: DiagnosticBreadthSourceType
    universe_definition: str
    universe_size: int
    eligible_universe_size: int
    advancers: int | None
    decliners: int | None
    unchanged: int | None
    breadth_ratio: Decimal | None
    percent_above_20dma: Decimal | None
    percent_above_50dma: Decimal | None
    percent_above_200dma: Decimal | None
    new_20_day_highs: int | None
    new_20_day_lows: int | None
    breadth_score: Decimal | None
    coverage_ratio: Decimal | None
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "warnings",
            tuple(warning.strip() for warning in self.warnings if warning.strip()),
        )


@dataclass(frozen=True, slots=True)
class DiagnosticMarketStateReconstruction:
    reconstruction_id: str
    market_date: date
    decision_cutoff: datetime
    candidate_date: date
    candidate_count: int
    source_type: str
    authoritative_status: DiagnosticAuthoritativeStatus
    benchmark_symbol: str
    benchmark_latest_bar: date | None
    benchmark_alignment: str
    benchmark_close: Decimal | None
    benchmark_return_1d: Decimal | None
    benchmark_return_5d: Decimal | None
    benchmark_return_20d: Decimal | None
    benchmark_dma_20: Decimal | None
    benchmark_dma_50: Decimal | None
    benchmark_dma_200: Decimal | None
    benchmark_distance_20dma: Decimal | None
    benchmark_distance_50dma: Decimal | None
    benchmark_distance_200dma: Decimal | None
    benchmark_atr: Decimal | None
    benchmark_volatility: Decimal | None
    breadth_score: Decimal | None
    participation_score: Decimal | None
    sector_score: Decimal | None
    market_trend_score: Decimal | None
    market_volatility_score: Decimal | None
    current_classifier_regime: str
    transparent_reference_state: TransparentReferenceState
    classifier_version_used: str
    classifier_fingerprint_used: str
    compatibility_status: DiagnosticCompatibilityLabel
    manifest_era_status: str
    input_completeness: DiagnosticInputCompleteness
    reconstruction_quality: DiagnosticReconstructionQuality
    benchmark_quality: DiagnosticReconstructionQuality
    breadth_quality: DiagnosticReconstructionQuality
    sector_quality: DiagnosticReconstructionQuality
    timestamp_quality: DiagnosticReconstructionQuality
    classifier_compatibility_quality: DiagnosticReconstructionQuality
    source_lineage_quality: DiagnosticReconstructionQuality
    overall_diagnostic_quality: DiagnosticReconstructionQuality
    fallback_applied: bool
    fallback_reason: str | None
    source_lineage: tuple[str, ...]
    missing_fields: tuple[str, ...]
    created_at: datetime
    dataset_version: str
    breadth: DiagnosticMarketBreadth
    sector_availability: DiagnosticSectorAvailability
    exact_historical_reproduction: bool
    no_lookahead_violations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reconstruction_id.strip():
            raise ValueError("reconstruction_id cannot be empty")
        if self.candidate_count < 0:
            raise ValueError("candidate_count cannot be negative")
        if self.authoritative_status.name.startswith("AUTHORITATIVE"):
            raise ValueError("diagnostic reconstruction cannot be authoritative")
        object.__setattr__(self, "decision_cutoff", _aware(self.decision_cutoff))
        object.__setattr__(self, "created_at", _aware(self.created_at))
        object.__setattr__(
            self,
            "source_lineage",
            tuple(item.strip() for item in self.source_lineage if item.strip()),
        )
        object.__setattr__(
            self,
            "missing_fields",
            tuple(item.strip() for item in self.missing_fields if item.strip()),
        )
        object.__setattr__(
            self,
            "no_lookahead_violations",
            tuple(
                item.strip() for item in self.no_lookahead_violations if item.strip()
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DiagnosticMarketStateReconstruction:
        return cls(
            reconstruction_id=str(payload["reconstruction_id"]),
            market_date=date.fromisoformat(str(payload["market_date"])),
            decision_cutoff=datetime.fromisoformat(str(payload["decision_cutoff"])),
            candidate_date=date.fromisoformat(str(payload["candidate_date"])),
            candidate_count=int(payload["candidate_count"]),
            source_type=str(payload["source_type"]),
            authoritative_status=DiagnosticAuthoritativeStatus(
                str(payload["authoritative_status"])
            ),
            benchmark_symbol=str(payload["benchmark_symbol"]),
            benchmark_latest_bar=_payload_date(payload.get("benchmark_latest_bar")),
            benchmark_alignment=str(payload["benchmark_alignment"]),
            benchmark_close=_payload_decimal(payload.get("benchmark_close")),
            benchmark_return_1d=_payload_decimal(payload.get("benchmark_return_1d")),
            benchmark_return_5d=_payload_decimal(payload.get("benchmark_return_5d")),
            benchmark_return_20d=_payload_decimal(payload.get("benchmark_return_20d")),
            benchmark_dma_20=_payload_decimal(payload.get("benchmark_dma_20")),
            benchmark_dma_50=_payload_decimal(payload.get("benchmark_dma_50")),
            benchmark_dma_200=_payload_decimal(payload.get("benchmark_dma_200")),
            benchmark_distance_20dma=_payload_decimal(
                payload.get("benchmark_distance_20dma")
            ),
            benchmark_distance_50dma=_payload_decimal(
                payload.get("benchmark_distance_50dma")
            ),
            benchmark_distance_200dma=_payload_decimal(
                payload.get("benchmark_distance_200dma")
            ),
            benchmark_atr=_payload_decimal(payload.get("benchmark_atr")),
            benchmark_volatility=_payload_decimal(payload.get("benchmark_volatility")),
            breadth_score=_payload_decimal(payload.get("breadth_score")),
            participation_score=_payload_decimal(payload.get("participation_score")),
            sector_score=_payload_decimal(payload.get("sector_score")),
            market_trend_score=_payload_decimal(payload.get("market_trend_score")),
            market_volatility_score=_payload_decimal(
                payload.get("market_volatility_score")
            ),
            current_classifier_regime=str(payload["current_classifier_regime"]),
            transparent_reference_state=TransparentReferenceState(
                str(payload["transparent_reference_state"])
            ),
            classifier_version_used=str(payload["classifier_version_used"]),
            classifier_fingerprint_used=str(payload["classifier_fingerprint_used"]),
            compatibility_status=DiagnosticCompatibilityLabel(
                str(payload["compatibility_status"])
            ),
            manifest_era_status=str(payload["manifest_era_status"]),
            input_completeness=DiagnosticInputCompleteness(
                str(payload["input_completeness"])
            ),
            reconstruction_quality=DiagnosticReconstructionQuality(
                str(payload["reconstruction_quality"])
            ),
            benchmark_quality=DiagnosticReconstructionQuality(
                str(payload["benchmark_quality"])
            ),
            breadth_quality=DiagnosticReconstructionQuality(
                str(payload["breadth_quality"])
            ),
            sector_quality=DiagnosticReconstructionQuality(
                str(payload["sector_quality"])
            ),
            timestamp_quality=DiagnosticReconstructionQuality(
                str(payload["timestamp_quality"])
            ),
            classifier_compatibility_quality=DiagnosticReconstructionQuality(
                str(payload["classifier_compatibility_quality"])
            ),
            source_lineage_quality=DiagnosticReconstructionQuality(
                str(payload["source_lineage_quality"])
            ),
            overall_diagnostic_quality=DiagnosticReconstructionQuality(
                str(payload["overall_diagnostic_quality"])
            ),
            fallback_applied=bool(payload["fallback_applied"]),
            fallback_reason=_payload_text(payload.get("fallback_reason")),
            source_lineage=tuple(
                str(item) for item in payload.get("source_lineage", ())
            ),
            missing_fields=tuple(
                str(item) for item in payload.get("missing_fields", ())
            ),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            dataset_version=str(payload["dataset_version"]),
            breadth=DiagnosticMarketBreadth(
                source_type=DiagnosticBreadthSourceType(
                    str(payload["breadth"]["source_type"])
                ),
                universe_definition=str(payload["breadth"]["universe_definition"]),
                universe_size=int(payload["breadth"]["universe_size"]),
                eligible_universe_size=int(
                    payload["breadth"]["eligible_universe_size"]
                ),
                advancers=_payload_int(payload["breadth"].get("advancers")),
                decliners=_payload_int(payload["breadth"].get("decliners")),
                unchanged=_payload_int(payload["breadth"].get("unchanged")),
                breadth_ratio=_payload_decimal(payload["breadth"].get("breadth_ratio")),
                percent_above_20dma=_payload_decimal(
                    payload["breadth"].get("percent_above_20dma")
                ),
                percent_above_50dma=_payload_decimal(
                    payload["breadth"].get("percent_above_50dma")
                ),
                percent_above_200dma=_payload_decimal(
                    payload["breadth"].get("percent_above_200dma")
                ),
                new_20_day_highs=_payload_int(
                    payload["breadth"].get("new_20_day_highs")
                ),
                new_20_day_lows=_payload_int(payload["breadth"].get("new_20_day_lows")),
                breadth_score=_payload_decimal(payload["breadth"].get("breadth_score")),
                coverage_ratio=_payload_decimal(
                    payload["breadth"].get("coverage_ratio")
                ),
                warnings=tuple(
                    str(item) for item in payload["breadth"].get("warnings", ())
                ),
            ),
            sector_availability=DiagnosticSectorAvailability(
                str(payload["sector_availability"])
            ),
            exact_historical_reproduction=bool(
                payload["exact_historical_reproduction"]
            ),
            no_lookahead_violations=tuple(
                str(item) for item in payload.get("no_lookahead_violations", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class DiagnosticMarketStateCandidateLink:
    reconstruction_id: str
    candidate_stable_id: str
    link_status: str
    candidate_decision_timestamp: datetime
    timestamp_difference: str
    recorded_candidate_regime: str | None
    setup_type: str | None
    final_verdict: str
    entry_state: str | None
    outcome_available: bool

    def __post_init__(self) -> None:
        if not self.reconstruction_id.strip():
            raise ValueError("reconstruction_id cannot be empty")
        if not self.candidate_stable_id.strip():
            raise ValueError("candidate_stable_id cannot be empty")
        object.__setattr__(
            self,
            "candidate_decision_timestamp",
            _aware(self.candidate_decision_timestamp),
        )

    def as_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DiagnosticMarketStateCandidateLink:
        return cls(
            reconstruction_id=str(payload["reconstruction_id"]),
            candidate_stable_id=str(payload["candidate_stable_id"]),
            link_status=str(payload["link_status"]),
            candidate_decision_timestamp=datetime.fromisoformat(
                str(payload["candidate_decision_timestamp"])
            ),
            timestamp_difference=str(payload["timestamp_difference"]),
            recorded_candidate_regime=_payload_text(
                payload.get("recorded_candidate_regime")
            ),
            setup_type=_payload_text(payload.get("setup_type")),
            final_verdict=str(payload["final_verdict"]),
            entry_state=_payload_text(payload.get("entry_state")),
            outcome_available=bool(payload["outcome_available"]),
        )


@dataclass(frozen=True, slots=True)
class DiagnosticMarketStateDataset:
    dataset_version: str
    reconstructions: tuple[DiagnosticMarketStateReconstruction, ...]
    links: tuple[DiagnosticMarketStateCandidateLink, ...]
    dry_run: bool
    non_authoritative_warning: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosticPersistenceResult:
    inserted_reconstructions: int
    inserted_links: int
    path: Path
    dry_run: bool
    dataset_version: str


@dataclass(frozen=True, slots=True)
class DiagnosticMarketStateCoverageReport:
    dataset_version: str
    non_authoritative_warning: str
    candidate_dates: int
    candidate_records: int
    reconstructions: int
    complete_diagnostic_dates: int
    partial_diagnostic_dates: int
    minimum_viable_dates: int
    blocked_dates: int
    benchmark_coverage: int
    breadth_coverage: int
    sector_coverage: int
    exact_lineage_records: int
    compatibility_only_records: int
    no_lookahead_violations: int
    primary_conclusion: DiagnosticConclusion
    secondary_conclusion: DiagnosticConclusion | None
    recommended_next_milestone: DiagnosticNextMilestone
    explicitly_prohibited_next_action: str


@dataclass(frozen=True, slots=True)
class DiagnosticNoLookAheadReport:
    dataset_version: str
    reconstructions_checked: int
    violations: int
    violation_details: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticRegimeComparisonRow:
    candidate_id: str
    symbol: str
    market_date: date
    recorded_candidate_regime: str | None
    reconstructed_current_classifier_regime: str
    transparent_reference_state: TransparentReferenceState
    comparison: RegimeComparisonClass
    setup_type: str | None
    final_verdict: str
    outcome_available: bool


@dataclass(frozen=True, slots=True)
class DiagnosticRegimeComparisonReport:
    dataset_version: str
    rows: tuple[DiagnosticRegimeComparisonRow, ...]
    comparison_counts: tuple[tuple[str, int], ...]
    recorded_regime_distribution: tuple[tuple[str, int], ...]
    reconstructed_regime_distribution: tuple[tuple[str, int], ...]
    transparent_reference_distribution: tuple[tuple[str, int], ...]
    primary_conclusion: DiagnosticConclusion
    secondary_conclusion: DiagnosticConclusion | None
    recommended_next_milestone: DiagnosticNextMilestone
    explicitly_prohibited_next_action: str


class DiagnosticMarketStateRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_diagnostic_market_state_path(path)

    def save_dataset(
        self,
        dataset: DiagnosticMarketStateDataset,
        *,
        replace_dataset_version: bool = False,
    ) -> DiagnosticPersistenceResult:
        if dataset.dry_run:
            return DiagnosticPersistenceResult(
                inserted_reconstructions=len(dataset.reconstructions),
                inserted_links=len(dataset.links),
                path=self.path,
                dry_run=True,
                dataset_version=dataset.dataset_version,
            )
        existing_reconstructions = {
            row.reconstruction_id: row for row in self.load_reconstructions()
        }
        existing_links = {
            (row.reconstruction_id, row.candidate_stable_id): row
            for row in self.load_links()
        }
        if replace_dataset_version:
            existing_reconstructions = {
                key: row
                for key, row in existing_reconstructions.items()
                if row.dataset_version != dataset.dataset_version
            }
            existing_links = {
                key: row
                for key, row in existing_links.items()
                if row.reconstruction_id
                not in {item.reconstruction_id for item in dataset.reconstructions}
            }
        inserted_reconstructions = 0
        for row in dataset.reconstructions:
            if row.reconstruction_id not in existing_reconstructions:
                inserted_reconstructions += 1
            existing_reconstructions[row.reconstruction_id] = row
        inserted_links = 0
        for link in dataset.links:
            key = (link.reconstruction_id, link.candidate_stable_id)
            if key not in existing_links:
                inserted_links += 1
            existing_links[key] = link
        self._write(
            tuple(existing_reconstructions.values()),
            tuple(existing_links.values()),
        )
        return DiagnosticPersistenceResult(
            inserted_reconstructions=inserted_reconstructions,
            inserted_links=inserted_links,
            path=self.path,
            dry_run=False,
            dataset_version=dataset.dataset_version,
        )

    def load_reconstructions(
        self,
        *,
        dataset_version: str | None = None,
    ) -> tuple[DiagnosticMarketStateReconstruction, ...]:
        rows = self._read().get("reconstructions", [])
        if not isinstance(rows, list):
            return ()
        parsed = tuple(
            DiagnosticMarketStateReconstruction.from_dict(row)
            for row in rows
            if isinstance(row, dict)
        )
        if dataset_version is not None:
            parsed = tuple(
                row for row in parsed if row.dataset_version == dataset_version
            )
        return tuple(
            sorted(parsed, key=lambda row: (row.market_date, row.reconstruction_id))
        )

    def load_links(
        self,
    ) -> tuple[DiagnosticMarketStateCandidateLink, ...]:
        rows = self._read().get("links", [])
        if not isinstance(rows, list):
            return ()
        return tuple(
            sorted(
                (
                    DiagnosticMarketStateCandidateLink.from_dict(row)
                    for row in rows
                    if isinstance(row, dict)
                ),
                key=lambda row: (row.reconstruction_id, row.candidate_stable_id),
            )
        )

    def get(
        self,
        reconstruction_id: str,
    ) -> DiagnosticMarketStateReconstruction | None:
        return next(
            (
                row
                for row in self.load_reconstructions()
                if row.reconstruction_id == reconstruction_id.strip()
            ),
            None,
        )

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"reconstructions": [], "links": []}
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return {"reconstructions": [], "links": []}
        payload = json.loads(raw)
        return (
            payload
            if isinstance(payload, dict)
            else {"reconstructions": [], "links": []}
        )

    def _write(
        self,
        reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
        links: tuple[DiagnosticMarketStateCandidateLink, ...],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "reconstructions": [
                row.as_dict()
                for row in sorted(
                    reconstructions,
                    key=lambda item: (item.dataset_version, item.market_date),
                )
            ],
            "links": [
                row.as_dict()
                for row in sorted(
                    links,
                    key=lambda item: (item.reconstruction_id, item.candidate_stable_id),
                )
            ],
        }
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class DiagnosticMarketBreadthBuilder:
    def __init__(self, *, minimum_universe_size: int = 20) -> None:
        if minimum_universe_size <= 0:
            raise ValueError("minimum_universe_size must be positive")
        self.minimum_universe_size = minimum_universe_size

    def build(
        self,
        *,
        market_date: date,
        price_repository: Any,
        candidate_symbols: tuple[str, ...],
    ) -> DiagnosticMarketBreadth:
        if not hasattr(price_repository, "find_by_trade_date"):
            return _empty_breadth("price repository lacks find_by_trade_date")
        frame = price_repository.find_by_trade_date(market_date)
        if frame.empty:
            return _empty_breadth("no equity universe bars available on market date")
        frame = frame.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
        frame = frame[
            frame["symbol"] != canonical_benchmark_configuration().provider_symbol
        ]
        universe_symbols = tuple(sorted(set(frame["symbol"].tolist())))
        candidate_set = {symbol.upper() for symbol in candidate_symbols}
        warnings = [
            "DIAGNOSTIC_CURRENT_UNIVERSE_RECONSTRUCTION",
            "survivorship bias possible",
            "current-symbol-universe bias possible",
            "sector reclassification risk not resolved",
        ]
        if set(universe_symbols).issubset(candidate_set):
            warnings.append("candidate-only universe rejected")
            return _empty_breadth(*warnings)
        if len(universe_symbols) < self.minimum_universe_size:
            warnings.append("eligible universe below minimum threshold")
            return DiagnosticMarketBreadth(
                source_type=DiagnosticBreadthSourceType.DIAGNOSTIC_CURRENT_UNIVERSE_RECONSTRUCTION,
                universe_definition="all symbols with same-date local daily price bars",
                universe_size=len(universe_symbols),
                eligible_universe_size=len(universe_symbols),
                advancers=None,
                decliners=None,
                unchanged=None,
                breadth_ratio=None,
                percent_above_20dma=None,
                percent_above_50dma=None,
                percent_above_200dma=None,
                new_20_day_highs=None,
                new_20_day_lows=None,
                breadth_score=None,
                coverage_ratio=Decimal("0"),
                warnings=tuple(warnings),
            )
        metrics = _same_day_breadth_metrics(frame, universe_symbols)
        warnings.append(
            "dma breadth unavailable without point-in-time universe history"
        )
        warnings_tuple = tuple(warnings)
        return DiagnosticMarketBreadth(
            source_type=DiagnosticBreadthSourceType.DIAGNOSTIC_CURRENT_UNIVERSE_RECONSTRUCTION,
            universe_definition="all symbols with same-date local daily price bars",
            universe_size=len(universe_symbols),
            eligible_universe_size=metrics["eligible"],
            advancers=metrics["advancers"],
            decliners=metrics["decliners"],
            unchanged=metrics["unchanged"],
            breadth_ratio=metrics["breadth_ratio"],
            percent_above_20dma=None,
            percent_above_50dma=None,
            percent_above_200dma=None,
            new_20_day_highs=None,
            new_20_day_lows=None,
            breadth_score=metrics["breadth_score"],
            coverage_ratio=_ratio(
                Decimal(metrics["eligible"]), Decimal(len(universe_symbols))
            ),
            warnings=warnings_tuple,
        )


class DiagnosticMarketStateReconstructionEngine:
    def __init__(
        self,
        *,
        dataset_version: str = DIAGNOSTIC_MARKET_STATE_DATASET_VERSION,
        created_at: datetime | None = None,
    ) -> None:
        self.dataset_version = dataset_version
        self.created_at = _aware(created_at or datetime(1970, 1, 1, tzinfo=UTC))

    def build(
        self,
        *,
        records: tuple[Any, ...],
        outcomes: tuple[Any, ...],
        price_repository: Any,
        provenances: tuple[Any, ...] = (),
        snapshots: tuple[Any, ...] = (),
        from_date: date | None = None,
        to_date: date | None = None,
        dry_run: bool = True,
    ) -> DiagnosticMarketStateDataset:
        filtered = _filter_records(records, from_date=from_date, to_date=to_date)
        records_by_date: dict[date, list[Any]] = {}
        for record in filtered:
            records_by_date.setdefault(record.evaluation_date, []).append(record)
        manifest = build_historical_manifest_audit(
            records=filtered,
            snapshots=snapshots,
            provenances=provenances,
        )
        assignment_by_id = {row.candidate_id: row for row in manifest.assignments}
        outcome_ids = {getattr(outcome, "candidate_id", "") for outcome in outcomes}
        config = canonical_benchmark_configuration()
        reconstructions: list[DiagnosticMarketStateReconstruction] = []
        links: list[DiagnosticMarketStateCandidateLink] = []
        for market_date, date_records in sorted(records_by_date.items()):
            decision_cutoff = datetime.combine(
                market_date, datetime.max.time(), tzinfo=UTC
            )
            benchmark_history = price_repository.find_history_by_symbols(
                symbols=(config.provider_symbol,),
                end_date=market_date,
                limit=5000,
            )
            benchmark_state = BenchmarkStateBuilder(configuration=config).build(
                bars=benchmark_history,
                decision_as_of=decision_cutoff,
            )
            candidate_symbols = tuple(record.symbol for record in date_records)
            breadth = DiagnosticMarketBreadthBuilder().build(
                market_date=market_date,
                price_repository=price_repository,
                candidate_symbols=candidate_symbols,
            )
            assignment_statuses = tuple(
                _assignment_status(assignment_by_id.get(record.candidate_id))
                for record in date_records
            )
            compatibility = _compatibility_label(assignment_statuses)
            source_lineage = _source_lineage(config.provider_symbol, compatibility)
            reconstruction = _reconstruction(
                market_date=market_date,
                decision_cutoff=decision_cutoff,
                records=tuple(date_records),
                benchmark_state=benchmark_state,
                breadth=breadth,
                compatibility=compatibility,
                manifest_era_status=_manifest_status(assignment_statuses),
                source_lineage=source_lineage,
                dataset_version=self.dataset_version,
                created_at=self.created_at,
            )
            reconstructions.append(reconstruction)
            for record in date_records:
                links.append(
                    DiagnosticMarketStateCandidateLink(
                        reconstruction_id=reconstruction.reconstruction_id,
                        candidate_stable_id=record.candidate_id,
                        link_status="DIAGNOSTIC_LINK_ONLY",
                        candidate_decision_timestamp=record.created_at,
                        timestamp_difference=_timestamp_difference(
                            record.created_at, decision_cutoff
                        ),
                        recorded_candidate_regime=record.market_regime,
                        setup_type=record.setup_type,
                        final_verdict=record.final_verdict,
                        entry_state=_entry_state(record),
                        outcome_available=record.candidate_id in outcome_ids,
                    )
                )
        return DiagnosticMarketStateDataset(
            dataset_version=self.dataset_version,
            reconstructions=tuple(reconstructions),
            links=tuple(sorted(links, key=lambda item: item.candidate_stable_id)),
            dry_run=dry_run,
            non_authoritative_warning=_non_authoritative_warning(),
            created_at=self.created_at,
        )


def build_coverage_report(
    *,
    dataset: DiagnosticMarketStateDataset | None = None,
    reconstructions: tuple[DiagnosticMarketStateReconstruction, ...] = (),
    links: tuple[DiagnosticMarketStateCandidateLink, ...] = (),
) -> DiagnosticMarketStateCoverageReport:
    rows = dataset.reconstructions if dataset is not None else reconstructions
    link_rows = dataset.links if dataset is not None else links
    version = (
        dataset.dataset_version
        if dataset is not None
        else rows[0].dataset_version
        if rows
        else DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
    )
    complete = sum(
        1
        for row in rows
        if row.input_completeness is DiagnosticInputCompleteness.COMPLETE_DIAGNOSTIC
    )
    partial = sum(
        1
        for row in rows
        if row.input_completeness is DiagnosticInputCompleteness.PARTIAL_DIAGNOSTIC
    )
    minimum = sum(
        1
        for row in rows
        if row.input_completeness
        is DiagnosticInputCompleteness.MINIMUM_VIABLE_DIAGNOSTIC
    )
    blocked = sum(
        1
        for row in rows
        if row.input_completeness
        in {
            DiagnosticInputCompleteness.INSUFFICIENT_DIAGNOSTIC,
            DiagnosticInputCompleteness.UNAVAILABLE,
        }
    )
    exact_records = sum(
        1
        for row in rows
        if row.compatibility_status
        in {
            DiagnosticCompatibilityLabel.PERSISTED_EXACT,
            DiagnosticCompatibilityLabel.EXACT_FINGERPRINT,
            DiagnosticCompatibilityLabel.VERIFIED_MANIFEST,
        }
    )
    exact_links = sum(
        row.candidate_count
        for row in rows
        if row.compatibility_status
        in {
            DiagnosticCompatibilityLabel.PERSISTED_EXACT,
            DiagnosticCompatibilityLabel.EXACT_FINGERPRINT,
            DiagnosticCompatibilityLabel.VERIFIED_MANIFEST,
        }
    )
    del exact_records
    candidate_records = len(link_rows) or sum(row.candidate_count for row in rows)
    compatibility_only = max(candidate_records - exact_links, 0)
    violations = sum(len(row.no_lookahead_violations) for row in rows)
    primary = _primary_conclusion(rows)
    return DiagnosticMarketStateCoverageReport(
        dataset_version=version,
        non_authoritative_warning=_non_authoritative_warning(),
        candidate_dates=len({row.market_date for row in rows}),
        candidate_records=candidate_records,
        reconstructions=len(rows),
        complete_diagnostic_dates=complete,
        partial_diagnostic_dates=partial,
        minimum_viable_dates=minimum,
        blocked_dates=blocked,
        benchmark_coverage=sum(1 for row in rows if row.benchmark_close is not None),
        breadth_coverage=sum(
            1 for row in rows if row.breadth.breadth_score is not None
        ),
        sector_coverage=sum(
            1
            for row in rows
            if row.sector_availability
            is DiagnosticSectorAvailability.POINT_IN_TIME_SECTOR_STATE
        ),
        exact_lineage_records=exact_links,
        compatibility_only_records=compatibility_only,
        no_lookahead_violations=violations,
        primary_conclusion=primary,
        secondary_conclusion=DiagnosticConclusion.DIAGNOSTIC_DATA_QUALITY_IS_INSUFFICIENT
        if blocked
        else None,
        recommended_next_milestone=_next_milestone(primary, rows),
        explicitly_prohibited_next_action=_prohibited_next_action(),
    )


def build_no_lookahead_report(
    reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
) -> DiagnosticNoLookAheadReport:
    details = tuple(
        f"{row.reconstruction_id}: {violation}"
        for row in reconstructions
        for violation in row.no_lookahead_violations
    )
    version = (
        reconstructions[0].dataset_version
        if reconstructions
        else DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
    )
    return DiagnosticNoLookAheadReport(
        dataset_version=version,
        reconstructions_checked=len(reconstructions),
        violations=len(details),
        violation_details=details,
    )


def build_regime_comparison_report(
    *,
    reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
    links: tuple[DiagnosticMarketStateCandidateLink, ...],
    records: tuple[Any, ...],
    outcomes: tuple[Any, ...],
) -> DiagnosticRegimeComparisonReport:
    reconstruction_by_id = {row.reconstruction_id: row for row in reconstructions}
    record_by_id = {record.candidate_id: record for record in records}
    outcome_ids = {getattr(outcome, "candidate_id", "") for outcome in outcomes}
    rows = []
    for link in links:
        reconstruction = reconstruction_by_id.get(link.reconstruction_id)
        record = record_by_id.get(link.candidate_stable_id)
        if reconstruction is None or record is None:
            continue
        rows.append(
            DiagnosticRegimeComparisonRow(
                candidate_id=record.candidate_id,
                symbol=record.symbol,
                market_date=record.evaluation_date,
                recorded_candidate_regime=record.market_regime,
                reconstructed_current_classifier_regime=(
                    reconstruction.current_classifier_regime
                ),
                transparent_reference_state=reconstruction.transparent_reference_state,
                comparison=_comparison_class(record.market_regime, reconstruction),
                setup_type=record.setup_type,
                final_verdict=record.final_verdict,
                outcome_available=record.candidate_id in outcome_ids,
            )
        )
    comparison_counts = _counts(row.comparison.value for row in rows)
    recorded = _counts((row.recorded_candidate_regime or "UNAVAILABLE") for row in rows)
    reconstructed = _counts(row.reconstructed_current_classifier_regime for row in rows)
    reference = _counts(row.transparent_reference_state.value for row in rows)
    version = (
        reconstructions[0].dataset_version
        if reconstructions
        else DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
    )
    primary = _comparison_conclusion(rows)
    return DiagnosticRegimeComparisonReport(
        dataset_version=version,
        rows=tuple(sorted(rows, key=lambda row: (row.market_date, row.candidate_id))),
        comparison_counts=comparison_counts,
        recorded_regime_distribution=recorded,
        reconstructed_regime_distribution=reconstructed,
        transparent_reference_distribution=reference,
        primary_conclusion=primary,
        secondary_conclusion=None,
        recommended_next_milestone=_next_milestone(primary, reconstructions),
        explicitly_prohibited_next_action=_prohibited_next_action(),
    )


def neutral_collapse_finding(
    report: DiagnosticRegimeComparisonReport,
) -> NeutralCollapseFinding:
    if not report.rows:
        return NeutralCollapseFinding.NOT_TESTABLE
    recorded_neutral = sum(
        1
        for row in report.rows
        if _normalize_regime(row.recorded_candidate_regime) == "NEUTRAL"
    )
    replay_neutral = sum(
        1
        for row in report.rows
        if _normalize_regime(row.reconstructed_current_classifier_regime) == "NEUTRAL"
    )
    if (
        recorded_neutral
        and replay_neutral / len(report.rows) < recorded_neutral / len(report.rows) / 2
    ):
        return NeutralCollapseFinding.OVERTURNED
    if recorded_neutral > replay_neutral:
        return NeutralCollapseFinding.PARTIALLY_CONFIRMED
    return NeutralCollapseFinding.CONFIRMED


def render_diagnostic_build_result(
    result: DiagnosticPersistenceResult,
    *,
    dataset: DiagnosticMarketStateDataset,
) -> tuple[str, ...]:
    action = "DRY RUN" if result.dry_run else "PERSISTED DIAGNOSTIC DATASET"
    return (
        "Diagnostic Market-State Build",
        f"Dataset Status: DIAGNOSTIC ONLY ({action})",
        f"Dataset Version: {result.dataset_version}",
        f"Reconstructions: {len(dataset.reconstructions)}",
        f"Candidate Links: {len(dataset.links)}",
        f"Inserted Reconstructions: {result.inserted_reconstructions}",
        f"Inserted Links: {result.inserted_links}",
        f"Path: {result.path}",
        f"Warning: {dataset.non_authoritative_warning}",
    )


def render_diagnostic_coverage(
    report: DiagnosticMarketStateCoverageReport,
) -> tuple[str, ...]:
    return (
        "Diagnostic Market-State Coverage",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Version: {report.dataset_version}",
        f"Non-Authoritative Warning: {report.non_authoritative_warning}",
        f"Candidate Dates: {report.candidate_dates}",
        f"Candidate Records: {report.candidate_records}",
        f"Diagnostic Reconstructions: {report.reconstructions}",
        f"Complete Diagnostic Dates: {report.complete_diagnostic_dates}",
        f"Partial Diagnostic Dates: {report.partial_diagnostic_dates}",
        f"Minimum-Viable Dates: {report.minimum_viable_dates}",
        f"Blocked Dates: {report.blocked_dates}",
        f"Benchmark Coverage: {report.benchmark_coverage}",
        f"Breadth Coverage: {report.breadth_coverage}",
        f"Sector Coverage: {report.sector_coverage}",
        f"Exact-Lineage Records: {report.exact_lineage_records}",
        f"Compatibility-Only Records: {report.compatibility_only_records}",
        f"No-Look-Ahead Violations: {report.no_lookahead_violations}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        f"Secondary Conclusion: {_text_enum(report.secondary_conclusion)}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        (
            "Explicitly Prohibited Next Action: "
            f"{report.explicitly_prohibited_next_action}"
        ),
    )


def render_diagnostic_history(
    reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
) -> tuple[str, ...]:
    lines = ["Diagnostic Market-State History", "Dataset Status: DIAGNOSTIC ONLY"]
    for row in reconstructions[:200]:
        lines.append(
            f"- {row.reconstruction_id}: date={row.market_date}, "
            f"regime={row.current_classifier_regime}, "
            f"reference={row.transparent_reference_state.value}, "
            f"quality={row.overall_diagnostic_quality.value}, "
            f"candidates={row.candidate_count}"
        )
    if len(reconstructions) > 200:
        lines.append(f"- ... {len(reconstructions) - 200} additional rows omitted")
    return tuple(lines)


def render_diagnostic_show(
    row: DiagnosticMarketStateReconstruction,
) -> tuple[str, ...]:
    return (
        "Diagnostic Market-State Reconstruction",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Reconstruction ID: {row.reconstruction_id}",
        f"Market Date: {row.market_date}",
        f"Decision Cutoff: {row.decision_cutoff.isoformat()}",
        f"Candidate Count: {row.candidate_count}",
        f"Authoritative Status: {row.authoritative_status.value}",
        f"Benchmark: {row.benchmark_symbol}",
        f"Benchmark Latest Bar: {_text(row.benchmark_latest_bar)}",
        f"Benchmark Close: {_text(row.benchmark_close)}",
        f"Current Classifier Regime: {row.current_classifier_regime}",
        f"Transparent Reference State: {row.transparent_reference_state.value}",
        f"Input Completeness: {row.input_completeness.value}",
        f"Overall Quality: {row.overall_diagnostic_quality.value}",
        f"Missing Fields: {', '.join(row.missing_fields) or 'none'}",
        f"No-Look-Ahead Violations: {len(row.no_lookahead_violations)}",
    )


def render_diagnostic_lineage(
    row: DiagnosticMarketStateReconstruction,
) -> tuple[str, ...]:
    return (
        "Diagnostic Market-State Lineage",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Reconstruction ID: {row.reconstruction_id}",
        f"Dataset Version: {row.dataset_version}",
        f"Classifier Version Used: {row.classifier_version_used}",
        f"Classifier Fingerprint Used: {row.classifier_fingerprint_used}",
        f"Compatibility Status: {row.compatibility_status.value}",
        f"Manifest Era Status: {row.manifest_era_status}",
        f"Exact Historical Reproduction: {row.exact_historical_reproduction}",
        f"Source Lineage: {', '.join(row.source_lineage)}",
    )


def render_diagnostic_quality(
    reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
) -> tuple[str, ...]:
    lines = ["Diagnostic Market-State Quality", "Dataset Status: DIAGNOSTIC ONLY"]
    for label, values in (
        ("Benchmark Quality", [row.benchmark_quality.value for row in reconstructions]),
        ("Breadth Quality", [row.breadth_quality.value for row in reconstructions]),
        ("Sector Quality", [row.sector_quality.value for row in reconstructions]),
        ("Timestamp Quality", [row.timestamp_quality.value for row in reconstructions]),
        (
            "Classifier Compatibility Quality",
            [row.classifier_compatibility_quality.value for row in reconstructions],
        ),
        (
            "Overall Diagnostic Quality",
            [row.overall_diagnostic_quality.value for row in reconstructions],
        ),
    ):
        counts = Counter(values)
        lines.append(
            f"- {label}: "
            + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        )
    return tuple(lines)


def render_no_lookahead(report: DiagnosticNoLookAheadReport) -> tuple[str, ...]:
    lines = [
        "Diagnostic Market-State No-Look-Ahead Audit",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Version: {report.dataset_version}",
        f"Reconstructions Checked: {report.reconstructions_checked}",
        f"Violations: {report.violations}",
    ]
    lines.extend(f"- {item}" for item in report.violation_details[:100])
    return tuple(lines)


def render_regime_comparison(
    report: DiagnosticRegimeComparisonReport,
) -> tuple[str, ...]:
    lines = [
        "Recorded vs Reconstructed Regime Comparison",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Version: {report.dataset_version}",
        f"Candidate Records Compared: {len(report.rows)}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        f"Secondary Conclusion: {_text_enum(report.secondary_conclusion)}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        (
            "Explicitly Prohibited Next Action: "
            f"{report.explicitly_prohibited_next_action}"
        ),
        "",
        "Comparison Counts",
    ]
    lines.extend(f"- {key}: {value}" for key, value in report.comparison_counts)
    lines.append("")
    lines.append("Recorded Regime Distribution")
    lines.extend(
        f"- {key}: {value}" for key, value in report.recorded_regime_distribution
    )
    lines.append("")
    lines.append("Reconstructed Regime Distribution")
    lines.extend(
        f"- {key}: {value}" for key, value in report.reconstructed_regime_distribution
    )
    lines.append("")
    lines.append("Transparent Reference-State Distribution")
    lines.extend(
        f"- {key}: {value}" for key, value in report.transparent_reference_distribution
    )
    return tuple(lines)


def render_neutral_collapse(
    report: DiagnosticRegimeComparisonReport,
) -> tuple[str, ...]:
    total = len(report.rows)
    recorded_neutral = sum(
        1
        for row in report.rows
        if _normalize_regime(row.recorded_candidate_regime) == "NEUTRAL"
    )
    replay_neutral = sum(
        1
        for row in report.rows
        if _normalize_regime(row.reconstructed_current_classifier_regime) == "NEUTRAL"
    )
    reference_neutral = sum(
        1
        for row in report.rows
        if row.transparent_reference_state is TransparentReferenceState.NEUTRAL
    )
    return (
        "Reconstructed Neutral-Collapse Reassessment",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Candidate Records Compared: {total}",
        f"Recorded Neutral Share: {_pct(recorded_neutral, total)}",
        f"Reconstructed Classifier Neutral Share: {_pct(replay_neutral, total)}",
        f"Transparent Reference Neutral Share: {_pct(reference_neutral, total)}",
        f"Finding: {neutral_collapse_finding(report).value}",
        "Production Conclusion Replacement: not performed",
    )


def render_placeholder_research_audit(
    title: str,
    coverage: DiagnosticMarketStateCoverageReport,
) -> tuple[str, ...]:
    return (
        title,
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Version: {coverage.dataset_version}",
        f"Candidate Records: {coverage.candidate_records}",
        f"Usable Reconstructions: {coverage.reconstructions - coverage.blocked_dates}",
        "Result: insufficient frozen diagnostic/outcome evidence for a stable "
        "research conclusion in this command.",
        f"Primary Conclusion: {coverage.primary_conclusion.value}",
        f"Recommended Next Milestone: {coverage.recommended_next_milestone.value}",
        (
            "Explicitly Prohibited Next Action: "
            f"{coverage.explicitly_prohibited_next_action}"
        ),
    )


def export_diagnostic_json(
    dataset_or_report: Any,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(dataset_or_report), indent=2), encoding="utf-8"
    )
    return path


def export_reconstructions_csv(
    reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = (
            tuple(reconstructions[0].as_dict().keys())
            if reconstructions
            else ("reconstruction_id",)
        )
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in reconstructions:
            writer.writerow(row.as_dict())
    return path


def resolve_diagnostic_market_state_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("ALPHA_DIAGNOSTIC_MARKET_STATE_LEDGER")
    if configured:
        return Path(configured)
    return DEFAULT_DIAGNOSTIC_MARKET_STATE_PATH


def _reconstruction(
    *,
    market_date: date,
    decision_cutoff: datetime,
    records: tuple[Any, ...],
    benchmark_state: BenchmarkState,
    breadth: DiagnosticMarketBreadth,
    compatibility: DiagnosticCompatibilityLabel,
    manifest_era_status: str,
    source_lineage: tuple[str, ...],
    dataset_version: str,
    created_at: datetime,
) -> DiagnosticMarketStateReconstruction:
    latest_bar = (
        None
        if benchmark_state.latest_bar_timestamp is None
        else benchmark_state.latest_bar_timestamp.date()
    )
    missing = tuple(
        sorted(set((*benchmark_state.missing_fields, *_breadth_missing(breadth))))
    )
    no_lookahead = _no_lookahead_violations(
        decision_cutoff=decision_cutoff,
        benchmark_latest_bar=benchmark_state.latest_bar_timestamp,
    )
    benchmark_quality = _benchmark_quality(benchmark_state)
    breadth_quality = _breadth_quality(breadth)
    sector_quality = DiagnosticReconstructionQuality.UNUSABLE
    timestamp_quality = (
        DiagnosticReconstructionQuality.HIGH
        if not no_lookahead
        else DiagnosticReconstructionQuality.UNUSABLE
    )
    classifier_quality = _classifier_quality(compatibility)
    source_quality = (
        DiagnosticReconstructionQuality.MEDIUM
        if source_lineage
        else DiagnosticReconstructionQuality.UNUSABLE
    )
    completeness = _input_completeness(
        benchmark_state=benchmark_state,
        breadth=breadth,
        no_lookahead=no_lookahead,
    )
    overall = _overall_quality(
        benchmark_quality=benchmark_quality,
        breadth_quality=breadth_quality,
        timestamp_quality=timestamp_quality,
        classifier_quality=classifier_quality,
        completeness=completeness,
    )
    reference = _reference_state(benchmark_state, breadth)
    replay_regime = _current_classifier_regime(reference)
    trend_score = _trend_score(benchmark_state)
    volatility_score = _volatility_score(benchmark_state)
    payload = {
        "market_date": market_date.isoformat(),
        "decision_cutoff": decision_cutoff.isoformat(),
        "benchmark_symbol": benchmark_state.configuration.provider_symbol,
        "feature_definition_version": "market-feature-definitions-v1",
        "classifier_version": MARKET_STATE_CLASSIFIER_VERSION,
        "classifier_fingerprint": current_market_classifier_fingerprint(),
        "compatibility": compatibility.value,
        "dataset_version": dataset_version,
        "source_lineage_fingerprint": _stable_id({"source_lineage": source_lineage}),
    }
    return DiagnosticMarketStateReconstruction(
        reconstruction_id=_stable_id(payload),
        market_date=market_date,
        decision_cutoff=decision_cutoff,
        candidate_date=market_date,
        candidate_count=len(records),
        source_type="CURRENT_COMPATIBLE_CLASSIFIER_REPLAY",
        authoritative_status=_authoritative_status(completeness),
        benchmark_symbol=benchmark_state.configuration.provider_symbol,
        benchmark_latest_bar=latest_bar,
        benchmark_alignment=benchmark_state.alignment.value,
        benchmark_close=benchmark_state.benchmark_close,
        benchmark_return_1d=benchmark_state.benchmark_return_1d,
        benchmark_return_5d=benchmark_state.benchmark_return_5d,
        benchmark_return_20d=benchmark_state.benchmark_return_20d,
        benchmark_dma_20=benchmark_state.benchmark_dma_20,
        benchmark_dma_50=benchmark_state.benchmark_dma_50,
        benchmark_dma_200=benchmark_state.benchmark_dma_200,
        benchmark_distance_20dma=benchmark_state.benchmark_distance_20dma,
        benchmark_distance_50dma=benchmark_state.benchmark_distance_50dma,
        benchmark_distance_200dma=benchmark_state.benchmark_distance_200dma,
        benchmark_atr=benchmark_state.benchmark_atr_14,
        benchmark_volatility=benchmark_state.benchmark_volatility,
        breadth_score=breadth.breadth_score,
        participation_score=breadth.breadth_score,
        sector_score=None,
        market_trend_score=trend_score,
        market_volatility_score=volatility_score,
        current_classifier_regime=replay_regime,
        transparent_reference_state=reference,
        classifier_version_used=MARKET_STATE_CLASSIFIER_VERSION,
        classifier_fingerprint_used=current_market_classifier_fingerprint(),
        compatibility_status=compatibility,
        manifest_era_status=manifest_era_status,
        input_completeness=completeness,
        reconstruction_quality=overall,
        benchmark_quality=benchmark_quality,
        breadth_quality=breadth_quality,
        sector_quality=sector_quality,
        timestamp_quality=timestamp_quality,
        classifier_compatibility_quality=classifier_quality,
        source_lineage_quality=source_quality,
        overall_diagnostic_quality=overall,
        fallback_applied=completeness
        in {
            DiagnosticInputCompleteness.INSUFFICIENT_DIAGNOSTIC,
            DiagnosticInputCompleteness.UNAVAILABLE,
        },
        fallback_reason="missing minimum benchmark inputs"
        if benchmark_state.benchmark_close is None
        else None,
        source_lineage=source_lineage,
        missing_fields=missing,
        created_at=created_at,
        dataset_version=dataset_version,
        breadth=breadth,
        sector_availability=DiagnosticSectorAvailability.SECTOR_STATE_UNAVAILABLE,
        exact_historical_reproduction=False,
        no_lookahead_violations=no_lookahead,
    )


def _empty_breadth(*warnings: str) -> DiagnosticMarketBreadth:
    return DiagnosticMarketBreadth(
        source_type=DiagnosticBreadthSourceType.BREADTH_UNAVAILABLE,
        universe_definition="unavailable",
        universe_size=0,
        eligible_universe_size=0,
        advancers=None,
        decliners=None,
        unchanged=None,
        breadth_ratio=None,
        percent_above_20dma=None,
        percent_above_50dma=None,
        percent_above_200dma=None,
        new_20_day_highs=None,
        new_20_day_lows=None,
        breadth_score=None,
        coverage_ratio=None,
        warnings=warnings,
    )


def _same_day_breadth_metrics(
    frame: pd.DataFrame,
    symbols: tuple[str, ...],
) -> dict[str, Any]:
    frame = frame.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    eligible = 0
    advancers = 0
    decliners = 0
    unchanged = 0
    for symbol in symbols:
        symbol_frame = frame[frame["symbol"] == symbol]
        if symbol_frame.empty:
            continue
        latest_row = symbol_frame.iloc[-1]
        latest = Decimal(str(latest_row["close"]))
        opening = Decimal(str(latest_row["open"]))
        eligible += 1
        if latest > opening:
            advancers += 1
        elif latest < opening:
            decliners += 1
        else:
            unchanged += 1
    breadth_ratio = _ratio(Decimal(advancers), Decimal(max(advancers + decliners, 1)))
    score = (breadth_ratio or Decimal("0")) * Decimal("100")
    return {
        "eligible": eligible,
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "breadth_ratio": breadth_ratio,
        "breadth_score": score.quantize(Decimal("0.01")),
    }


def _reference_state(
    benchmark_state: BenchmarkState,
    breadth: DiagnosticMarketBreadth,
) -> TransparentReferenceState:
    if (
        benchmark_state.benchmark_close is None
        or benchmark_state.benchmark_return_20d is None
    ):
        return TransparentReferenceState.INSUFFICIENT_INPUT
    if (
        benchmark_state.benchmark_volatility is not None
        and benchmark_state.benchmark_volatility > Decimal("0.04")
    ):
        return TransparentReferenceState.HIGH_VOLATILITY
    if breadth.breadth_score is not None and breadth.breadth_score < Decimal("35"):
        return TransparentReferenceState.DISTRIBUTION
    above20 = benchmark_state.benchmark_above_20dma is True
    above50 = benchmark_state.benchmark_above_50dma is True
    above200 = benchmark_state.benchmark_above_200dma is True
    return20 = benchmark_state.benchmark_return_20d
    if above20 and above50 and above200 and return20 > Decimal("0.03"):
        return TransparentReferenceState.STRONG_POSITIVE
    if above20 and above50 and return20 > Decimal("0"):
        return TransparentReferenceState.POSITIVE
    if not above20 and not above50 and return20 < Decimal("-0.03"):
        return TransparentReferenceState.STRONG_NEGATIVE
    if not above20 and return20 < Decimal("0"):
        return TransparentReferenceState.NEGATIVE
    return TransparentReferenceState.NEUTRAL


def _current_classifier_regime(reference: TransparentReferenceState) -> str:
    if reference in {
        TransparentReferenceState.STRONG_POSITIVE,
        TransparentReferenceState.POSITIVE,
    }:
        return "BULLISH"
    if reference in {
        TransparentReferenceState.STRONG_NEGATIVE,
        TransparentReferenceState.NEGATIVE,
        TransparentReferenceState.DISTRIBUTION,
        TransparentReferenceState.HIGH_VOLATILITY,
    }:
        return "BEARISH"
    return "NEUTRAL"


def _input_completeness(
    *,
    benchmark_state: BenchmarkState,
    breadth: DiagnosticMarketBreadth,
    no_lookahead: tuple[str, ...],
) -> DiagnosticInputCompleteness:
    if no_lookahead:
        return DiagnosticInputCompleteness.UNAVAILABLE
    if (
        benchmark_state.completeness is BenchmarkFeatureCompleteness.COMPLETE
        and breadth.breadth_score is not None
    ):
        return DiagnosticInputCompleteness.COMPLETE_DIAGNOSTIC
    if benchmark_state.completeness in {
        BenchmarkFeatureCompleteness.COMPLETE,
        BenchmarkFeatureCompleteness.PARTIAL,
    }:
        return DiagnosticInputCompleteness.PARTIAL_DIAGNOSTIC
    if benchmark_state.has_minimum_features:
        return DiagnosticInputCompleteness.MINIMUM_VIABLE_DIAGNOSTIC
    if benchmark_state.completeness is BenchmarkFeatureCompleteness.UNAVAILABLE:
        return DiagnosticInputCompleteness.UNAVAILABLE
    return DiagnosticInputCompleteness.INSUFFICIENT_DIAGNOSTIC


def _authoritative_status(
    completeness: DiagnosticInputCompleteness,
) -> DiagnosticAuthoritativeStatus:
    if completeness is DiagnosticInputCompleteness.COMPLETE_DIAGNOSTIC:
        return DiagnosticAuthoritativeStatus.DIAGNOSTIC_RECONSTRUCTED
    if completeness is DiagnosticInputCompleteness.PARTIAL_DIAGNOSTIC:
        return DiagnosticAuthoritativeStatus.DIAGNOSTIC_PARTIAL
    if completeness is DiagnosticInputCompleteness.MINIMUM_VIABLE_DIAGNOSTIC:
        return DiagnosticAuthoritativeStatus.DIAGNOSTIC_MINIMUM_VIABLE
    return DiagnosticAuthoritativeStatus.DIAGNOSTIC_UNAVAILABLE


def _benchmark_quality(state: BenchmarkState) -> DiagnosticReconstructionQuality:
    if state.completeness is BenchmarkFeatureCompleteness.COMPLETE:
        return DiagnosticReconstructionQuality.HIGH
    if state.completeness is BenchmarkFeatureCompleteness.PARTIAL:
        return DiagnosticReconstructionQuality.MEDIUM
    if state.has_minimum_features:
        return DiagnosticReconstructionQuality.LOW
    return DiagnosticReconstructionQuality.UNUSABLE


def _breadth_quality(
    breadth: DiagnosticMarketBreadth,
) -> DiagnosticReconstructionQuality:
    if (
        breadth.breadth_score is not None
        and breadth.coverage_ratio
        and breadth.coverage_ratio >= Decimal("0.80")
    ):
        return DiagnosticReconstructionQuality.MEDIUM
    if breadth.breadth_score is not None:
        return DiagnosticReconstructionQuality.LOW
    return DiagnosticReconstructionQuality.UNUSABLE


def _classifier_quality(
    compatibility: DiagnosticCompatibilityLabel,
) -> DiagnosticReconstructionQuality:
    if compatibility in {
        DiagnosticCompatibilityLabel.PERSISTED_EXACT,
        DiagnosticCompatibilityLabel.EXACT_FINGERPRINT,
        DiagnosticCompatibilityLabel.VERIFIED_MANIFEST,
    }:
        return DiagnosticReconstructionQuality.HIGH
    if compatibility is DiagnosticCompatibilityLabel.FORWARD_COMPATIBLE_DIAGNOSTIC:
        return DiagnosticReconstructionQuality.MEDIUM
    return DiagnosticReconstructionQuality.LOW


def _overall_quality(
    *,
    benchmark_quality: DiagnosticReconstructionQuality,
    breadth_quality: DiagnosticReconstructionQuality,
    timestamp_quality: DiagnosticReconstructionQuality,
    classifier_quality: DiagnosticReconstructionQuality,
    completeness: DiagnosticInputCompleteness,
) -> DiagnosticReconstructionQuality:
    if timestamp_quality is DiagnosticReconstructionQuality.UNUSABLE:
        return DiagnosticReconstructionQuality.UNUSABLE
    if completeness is DiagnosticInputCompleteness.COMPLETE_DIAGNOSTIC:
        return DiagnosticReconstructionQuality.HIGH
    if (
        benchmark_quality
        in {
            DiagnosticReconstructionQuality.HIGH,
            DiagnosticReconstructionQuality.MEDIUM,
        }
        and classifier_quality is not DiagnosticReconstructionQuality.UNUSABLE
    ):
        return DiagnosticReconstructionQuality.MEDIUM
    if breadth_quality is DiagnosticReconstructionQuality.UNUSABLE:
        return DiagnosticReconstructionQuality.LOW
    return DiagnosticReconstructionQuality.LOW


def _compatibility_label(
    statuses: tuple[HistoricalEraAssignmentStatus, ...],
) -> DiagnosticCompatibilityLabel:
    if any(
        status is HistoricalEraAssignmentStatus.PERSISTED_EXACT_PROVENANCE
        for status in statuses
    ):
        return DiagnosticCompatibilityLabel.EXACT_FINGERPRINT
    if any(
        status is HistoricalEraAssignmentStatus.PERSISTED_EXACT_CLASSIFIER_VERSION
        for status in statuses
    ):
        return DiagnosticCompatibilityLabel.PERSISTED_EXACT
    if any(
        status is HistoricalEraAssignmentStatus.MATCHED_VERIFIED_MANIFEST
        for status in statuses
    ):
        return DiagnosticCompatibilityLabel.VERIFIED_MANIFEST
    if any(
        status is HistoricalEraAssignmentStatus.MATCHED_SUPPORTED_MANIFEST
        for status in statuses
    ):
        return DiagnosticCompatibilityLabel.SEMANTIC_COMPATIBILITY_ONLY
    if any(
        status is HistoricalEraAssignmentStatus.OUTPUT_SIGNATURE_ONLY
        for status in statuses
    ):
        return DiagnosticCompatibilityLabel.FORWARD_COMPATIBLE_DIAGNOSTIC
    return DiagnosticCompatibilityLabel.UNKNOWN


def _assignment_status(assignment: Any | None) -> HistoricalEraAssignmentStatus:
    if assignment is None:
        return HistoricalEraAssignmentStatus.UNKNOWN_ERA
    value = getattr(assignment, "assignment_status", None)
    if isinstance(value, HistoricalEraAssignmentStatus):
        return value
    return HistoricalEraAssignmentStatus.UNKNOWN_ERA


def _manifest_status(statuses: tuple[HistoricalEraAssignmentStatus, ...]) -> str:
    counts = Counter(status.value for status in statuses)
    return ",".join(f"{key}:{value}" for key, value in sorted(counts.items()))


def _source_lineage(
    benchmark_symbol: str,
    compatibility: DiagnosticCompatibilityLabel,
) -> tuple[str, ...]:
    return (
        "daily_prices",
        f"benchmark:{benchmark_symbol}",
        "BenchmarkStateBuilder",
        f"classifier:{MARKET_STATE_CLASSIFIER_VERSION}",
        f"fingerprint:{current_market_classifier_fingerprint()}",
        f"compatibility:{compatibility.value}",
        "diagnostic_non_authoritative",
    )


def _no_lookahead_violations(
    *,
    decision_cutoff: datetime,
    benchmark_latest_bar: datetime | None,
) -> tuple[str, ...]:
    if benchmark_latest_bar is not None and benchmark_latest_bar > decision_cutoff:
        return ("benchmark_latest_bar_after_decision_cutoff",)
    return ()


def _comparison_class(
    recorded: str | None,
    reconstruction: DiagnosticMarketStateReconstruction,
) -> RegimeComparisonClass:
    replay = _normalize_regime(reconstruction.current_classifier_regime)
    reference = _reference_direction(reconstruction.transparent_reference_state)
    recorded_norm = _normalize_regime(recorded)
    if reconstruction.input_completeness is DiagnosticInputCompleteness.UNAVAILABLE:
        return RegimeComparisonClass.RECONSTRUCTION_UNAVAILABLE
    if recorded_norm in {"", "UNAVAILABLE", "UNKNOWN"}:
        return RegimeComparisonClass.RECORDED_DEFAULTED
    if recorded_norm == replay and replay == reference:
        return RegimeComparisonClass.ALL_MATCH
    if recorded_norm == replay:
        return RegimeComparisonClass.RECORDED_AND_REPLAY_MATCH
    if replay == reference:
        return RegimeComparisonClass.REPLAY_AND_REFERENCE_DIRECTIONAL_MATCH
    if recorded_norm == "NEUTRAL" and replay != "NEUTRAL":
        return RegimeComparisonClass.RECORDED_NEUTRAL_REPLAY_NON_NEUTRAL
    if recorded_norm != "NEUTRAL" and replay == "NEUTRAL":
        return RegimeComparisonClass.RECORDED_NON_NEUTRAL_REPLAY_NEUTRAL
    if _sign(recorded_norm) != _sign(replay):
        return RegimeComparisonClass.RECORDED_AND_REPLAY_SIGN_CONFLICT
    if _sign(replay) != _sign(reference):
        return RegimeComparisonClass.REPLAY_AND_REFERENCE_SIGN_CONFLICT
    return RegimeComparisonClass.REPLAY_AND_REFERENCE_DIRECTIONAL_MATCH


def _reference_direction(reference: TransparentReferenceState) -> str:
    if reference in {
        TransparentReferenceState.STRONG_POSITIVE,
        TransparentReferenceState.POSITIVE,
    }:
        return "BULLISH"
    if reference in {
        TransparentReferenceState.STRONG_NEGATIVE,
        TransparentReferenceState.NEGATIVE,
        TransparentReferenceState.DISTRIBUTION,
        TransparentReferenceState.HIGH_VOLATILITY,
    }:
        return "BEARISH"
    return "NEUTRAL"


def _normalize_regime(value: str | None) -> str:
    return "" if value is None else value.strip().upper()


def _sign(value: str) -> int:
    if value in {"BULLISH", "POSITIVE", "STRONG_POSITIVE"}:
        return 1
    if value in {"BEARISH", "NEGATIVE", "STRONG_NEGATIVE"}:
        return -1
    return 0


def _primary_conclusion(
    rows: tuple[DiagnosticMarketStateReconstruction, ...],
) -> DiagnosticConclusion:
    if not rows:
        return DiagnosticConclusion.DIAGNOSTIC_DATA_QUALITY_IS_INSUFFICIENT
    usable = sum(
        1
        for row in rows
        if row.input_completeness
        not in {
            DiagnosticInputCompleteness.INSUFFICIENT_DIAGNOSTIC,
            DiagnosticInputCompleteness.UNAVAILABLE,
        }
    )
    regimes = {
        row.current_classifier_regime
        for row in rows
        if row.current_classifier_regime != "NEUTRAL"
    }
    if usable < max(len(rows) // 3, 1):
        return DiagnosticConclusion.DIAGNOSTIC_DATA_QUALITY_IS_INSUFFICIENT
    if len(regimes) >= 2:
        return DiagnosticConclusion.DIAGNOSTIC_RECONSTRUCTION_RECOVERS_REGIME_DIVERSITY
    return DiagnosticConclusion.NO_SINGLE_REGIME_RESEARCH_CONCLUSION


def _comparison_conclusion(
    rows: list[DiagnosticRegimeComparisonRow],
) -> DiagnosticConclusion:
    if not rows:
        return DiagnosticConclusion.DIAGNOSTIC_DATA_QUALITY_IS_INSUFFICIENT
    neutral_to_non = sum(
        1
        for row in rows
        if row.comparison is RegimeComparisonClass.RECORDED_NEUTRAL_REPLAY_NON_NEUTRAL
    )
    if neutral_to_non > len(rows) // 4:
        return (
            DiagnosticConclusion.RECORDED_NEUTRAL_COLLAPSE_WAS_PRIMARILY_DATA_FALLBACK
        )
    return DiagnosticConclusion.NO_SINGLE_REGIME_RESEARCH_CONCLUSION


def _next_milestone(
    conclusion: DiagnosticConclusion,
    rows: tuple[DiagnosticMarketStateReconstruction, ...],
) -> DiagnosticNextMilestone:
    if not rows:
        return DiagnosticNextMilestone.INSUFFICIENT_EVIDENCE_COLLECT_MORE_DATA
    if any(
        row.breadth_quality is DiagnosticReconstructionQuality.UNUSABLE for row in rows
    ):
        return DiagnosticNextMilestone.BUILD_POINT_IN_TIME_BREADTH_HISTORY
    if (
        conclusion
        is DiagnosticConclusion.DIAGNOSTIC_RECONSTRUCTION_RECOVERS_REGIME_DIVERSITY
    ):
        return DiagnosticNextMilestone.AUDIT_MARKET_REGIME_THRESHOLD_DEFINITIONS
    return DiagnosticNextMilestone.ACCEPT_LEGACY_REGIME_ANALYSIS_AS_DIAGNOSTIC_ONLY


def _prohibited_next_action() -> str:
    return (
        "Do not copy diagnostic reconstructions into authoritative snapshot storage, "
        "attach them to legacy candidates as production state, relabel historical "
        "regimes, tune thresholds, alter gates, change trade plans, approvals, "
        "allocation, or recommendation scoring from this milestone."
    )


def _filter_records(
    records: tuple[Any, ...],
    *,
    from_date: date | None,
    to_date: date | None,
) -> tuple[Any, ...]:
    return tuple(
        record
        for record in records
        if (from_date is None or record.evaluation_date >= from_date)
        and (to_date is None or record.evaluation_date <= to_date)
    )


def _entry_state(record: Any) -> str | None:
    if getattr(record, "approved_for_deployment", False):
        return "APPROVED"
    if getattr(record, "confirmation_entry", None) is not None:
        return "WAITING_FOR_CONFIRMATION"
    return "UNAVAILABLE"


def _timestamp_difference(start: datetime, end: datetime) -> str:
    seconds = int((_aware(end) - _aware(start)).total_seconds())
    return f"{seconds}s"


def _breadth_missing(breadth: DiagnosticMarketBreadth) -> tuple[str, ...]:
    missing = []
    if breadth.breadth_score is None:
        missing.append("market_breadth")
    if breadth.percent_above_200dma is None:
        missing.append("breadth_percent_above_200dma")
    return tuple(missing)


def _trend_score(state: BenchmarkState) -> Decimal | None:
    if state.benchmark_return_20d is None:
        return None
    score = Decimal("50") + (state.benchmark_return_20d * Decimal("500"))
    return max(Decimal("0"), min(Decimal("100"), score)).quantize(Decimal("0.01"))


def _volatility_score(state: BenchmarkState) -> Decimal | None:
    if state.benchmark_volatility is None:
        return None
    score = Decimal("100") - (state.benchmark_volatility * Decimal("1000"))
    return max(Decimal("0"), min(Decimal("100"), score)).quantize(Decimal("0.01"))


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == Decimal("0"):
        return None
    return (numerator / denominator).quantize(Decimal("0.0001"))


def _counts(values: Any) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(values).items()))


def _pct(count: int, total: int) -> str:
    if total <= 0:
        return "unavailable"
    value = (Decimal(count) / Decimal(total) * Decimal("100")).quantize(Decimal("0.01"))
    return f"{value}%"


def _non_authoritative_warning() -> str:
    return (
        "Diagnostic reconstructed market states describe what Alpha's compatible "
        "current research logic infers from point-in-time historical data. They "
        "do not prove what the original production system classified."
    )


def _stable_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _payload_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if not text or text == "None" else Decimal(text)


def _payload_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if not text or text == "None" else date.fromisoformat(text)


def _payload_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if not text or text == "None" else int(text)


def _payload_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _text(value: object | None) -> str:
    return "unavailable" if value is None else str(value)


def _text_enum(value: StrEnum | None) -> str:
    return "none" if value is None else value.value


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
    "DEFAULT_DIAGNOSTIC_MARKET_STATE_PATH",
    "DIAGNOSTIC_MARKET_STATE_DATASET_VERSION",
    "DiagnosticAuthoritativeStatus",
    "DiagnosticCompatibilityLabel",
    "DiagnosticInputCompleteness",
    "DiagnosticMarketBreadth",
    "DiagnosticMarketBreadthBuilder",
    "DiagnosticMarketStateCandidateLink",
    "DiagnosticMarketStateCoverageReport",
    "DiagnosticMarketStateDataset",
    "DiagnosticMarketStateReconstruction",
    "DiagnosticMarketStateReconstructionEngine",
    "DiagnosticMarketStateRepository",
    "DiagnosticNoLookAheadReport",
    "DiagnosticReconstructionQuality",
    "DiagnosticRegimeComparisonReport",
    "DiagnosticSectorAvailability",
    "NeutralCollapseFinding",
    "build_coverage_report",
    "build_no_lookahead_report",
    "build_regime_comparison_report",
    "export_diagnostic_json",
    "export_reconstructions_csv",
    "neutral_collapse_finding",
    "render_diagnostic_build_result",
    "render_diagnostic_coverage",
    "render_diagnostic_history",
    "render_diagnostic_lineage",
    "render_diagnostic_quality",
    "render_diagnostic_show",
    "render_neutral_collapse",
    "render_no_lookahead",
    "render_placeholder_research_audit",
    "render_regime_comparison",
    "resolve_diagnostic_market_state_path",
]
