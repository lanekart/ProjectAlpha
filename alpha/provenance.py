from __future__ import annotations

import csv
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

from alpha.market_intelligence.snapshots import (
    MARKET_STATE_CLASSIFIER_VERSION,
    MARKET_STATE_SNAPSHOT_SCHEMA_VERSION,
)
from alpha.release import current_release

DECISION_PROVENANCE_SCHEMA_VERSION = "1.0"
DEFAULT_DECISION_PROVENANCE_PATH = Path(".alpha/decision_provenance.json")
ANALYTICAL_RELEASE_MANIFEST_REVIEWED_AT = datetime(1970, 1, 1, tzinfo=UTC)

BENCHMARK_BUILDER_VERSION = "benchmark-state-builder-v1"
MARKET_FEATURE_DEFINITION_VERSION = "market-feature-definitions-v1"
MARKET_CLASSIFIER_NAME = "MarketIntelligenceCompositeEngine"
MARKET_CLASSIFIER_CONFIG_VERSION = "market-classifier-config-v1"
MARKET_FALLBACK_POLICY_VERSION = "market-fallback-policy-v1"
MARKET_INTELLIGENCE_ENGINE_VERSION = "market-intelligence-composite-v1"
RECOMMENDATION_ENGINE_VERSION = "recommendation-engine-v1"
RECOMMENDATION_POLICY_VERSION = "recommendation-policy-v1"
ENTRY_TIMING_ENGINE_VERSION = "entry-timing-engine-v1"
TRADE_PLAN_ENGINE_VERSION = "trade-plan-engine-v1"
APPROVAL_POLICY_VERSION = "institutional-approval-policy-v1"
ALLOCATION_POLICY_VERSION = "allocation-policy-v1"


class WorkingTreeState(StrEnum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"
    UNAVAILABLE = "UNAVAILABLE"


class ComponentCompatibility(StrEnum):
    EXACT_VERSION_MATCH = "EXACT_VERSION_MATCH"
    EXACT_FINGERPRINT_MATCH = "EXACT_FINGERPRINT_MATCH"
    SEMANTICALLY_COMPATIBLE = "SEMANTICALLY_COMPATIBLE"
    FORWARD_COMPATIBLE_FOR_REPLAY = "FORWARD_COMPATIBLE_FOR_REPLAY"
    INCOMPATIBLE = "INCOMPATIBLE"
    VERSION_UNKNOWN = "VERSION_UNKNOWN"
    FINGERPRINT_UNKNOWN = "FINGERPRINT_UNKNOWN"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EvidenceReliability(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    STRONG = "STRONG"
    SUPPORTING = "SUPPORTING"
    WEAK = "WEAK"
    UNUSABLE = "UNUSABLE"


class HistoricalEvidenceType(StrEnum):
    GIT_COMMIT_HISTORY = "GIT_COMMIT_HISTORY"
    GIT_TAG_HISTORY = "GIT_TAG_HISTORY"
    RELEASE_METADATA = "RELEASE_METADATA"
    DECISION_PROVENANCE_LEDGER = "DECISION_PROVENANCE_LEDGER"
    CANDIDATE_RECORD_FIELD = "CANDIDATE_RECORD_FIELD"
    MARKET_STATE_SNAPSHOT_FIELD = "MARKET_STATE_SNAPSHOT_FIELD"
    SCHEMA_SIGNATURE = "SCHEMA_SIGNATURE"
    OUTPUT_SIGNATURE = "OUTPUT_SIGNATURE"
    DOCUMENTATION = "DOCUMENTATION"
    DEPLOYMENT_HISTORY = "DEPLOYMENT_HISTORY"


class AnalyticalChangeImpact(StrEnum):
    BEHAVIOURAL_CHANGE = "BEHAVIOURAL_CHANGE"
    NON_BEHAVIOURAL_REFACTOR = "NON_BEHAVIOURAL_REFACTOR"
    SCHEMA_ONLY_CHANGE = "SCHEMA_ONLY_CHANGE"
    DOCUMENTATION_ONLY_CHANGE = "DOCUMENTATION_ONLY_CHANGE"
    TEST_ONLY_CHANGE = "TEST_ONLY_CHANGE"
    UNKNOWN_CHANGE_IMPACT = "UNKNOWN_CHANGE_IMPACT"


class ReleaseReviewStatus(StrEnum):
    VERIFIED = "VERIFIED"
    SUPPORTED = "SUPPORTED"
    PROVISIONAL = "PROVISIONAL"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class HistoricalEraAssignmentStatus(StrEnum):
    PERSISTED_EXACT_PROVENANCE = "PERSISTED_EXACT_PROVENANCE"
    PERSISTED_EXACT_CLASSIFIER_VERSION = "PERSISTED_EXACT_CLASSIFIER_VERSION"
    MATCHED_VERIFIED_MANIFEST = "MATCHED_VERIFIED_MANIFEST"
    MATCHED_SUPPORTED_MANIFEST = "MATCHED_SUPPORTED_MANIFEST"
    MULTIPLE_POSSIBLE_ERAS = "MULTIPLE_POSSIBLE_ERAS"
    OUTPUT_SIGNATURE_ONLY = "OUTPUT_SIGNATURE_ONLY"
    DATE_RANGE_ONLY = "DATE_RANGE_ONLY"
    KNOWN_INCOMPATIBLE_ERA = "KNOWN_INCOMPATIBLE_ERA"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    UNKNOWN_ERA = "UNKNOWN_ERA"


class ManifestBackfillEligibility(StrEnum):
    ELIGIBLE_PERSISTED_EXACT = "ELIGIBLE_PERSISTED_EXACT"
    ELIGIBLE_VERIFIED_MANIFEST = "ELIGIBLE_VERIFIED_MANIFEST"
    ELIGIBLE_EXACT_FINGERPRINT = "ELIGIBLE_EXACT_FINGERPRINT"
    ELIGIBLE_SUPPORTED_SEMANTIC = "ELIGIBLE_SUPPORTED_SEMANTIC"
    DIAGNOSTIC_ONLY_FORWARD_COMPATIBLE = "DIAGNOSTIC_ONLY_FORWARD_COMPATIBLE"
    BLOCKED_MULTIPLE_POSSIBLE_ERAS = "BLOCKED_MULTIPLE_POSSIBLE_ERAS"
    BLOCKED_DATE_ONLY = "BLOCKED_DATE_ONLY"
    BLOCKED_OUTPUT_SIGNATURE_ONLY = "BLOCKED_OUTPUT_SIGNATURE_ONLY"
    BLOCKED_CONFLICTING_EVIDENCE = "BLOCKED_CONFLICTING_EVIDENCE"
    BLOCKED_UNKNOWN_ERA = "BLOCKED_UNKNOWN_ERA"
    BLOCKED_KNOWN_INCOMPATIBLE = "BLOCKED_KNOWN_INCOMPATIBLE"
    BLOCKED_OTHER_MARKET_SOURCE = "BLOCKED_OTHER_MARKET_SOURCE"


class HistoricalManifestConclusion(StrEnum):
    HISTORICAL_RELEASE_MANIFEST_RECOVERS_EXACT_LINEAGE = (
        "HISTORICAL_RELEASE_MANIFEST_RECOVERS_EXACT_LINEAGE"
    )
    HISTORICAL_RELEASE_MANIFEST_RECOVERS_PARTIAL_LINEAGE = (
        "HISTORICAL_RELEASE_MANIFEST_RECOVERS_PARTIAL_LINEAGE"
    )
    GIT_HISTORY_SUPPORTS_SEMANTIC_COMPATIBILITY_ONLY = (
        "GIT_HISTORY_SUPPORTS_SEMANTIC_COMPATIBILITY_ONLY"
    )
    DEPLOYMENT_HISTORY_IS_PRIMARY_BOTTLENECK = (
        "DEPLOYMENT_HISTORY_IS_PRIMARY_BOTTLENECK"
    )
    HISTORICAL_CHANGE_BOUNDARIES_ARE_AMBIGUOUS = (
        "HISTORICAL_CHANGE_BOUNDARIES_ARE_AMBIGUOUS"
    )
    OUTPUT_SIGNATURES_ARE_INSUFFICIENT = "OUTPUT_SIGNATURES_ARE_INSUFFICIENT"
    MOST_LEGACY_HISTORY_REMAINS_UNKNOWN = "MOST_LEGACY_HISTORY_REMAINS_UNKNOWN"
    CONFLICTING_HISTORICAL_EVIDENCE_IS_PRIMARY_BOTTLENECK = (
        "CONFLICTING_HISTORICAL_EVIDENCE_IS_PRIMARY_BOTTLENECK"
    )
    HISTORICAL_VERSION_LINEAGE_IS_SUFFICIENT_FOR_BACKFILL = (
        "HISTORICAL_VERSION_LINEAGE_IS_SUFFICIENT_FOR_BACKFILL"
    )
    INSUFFICIENT_EVIDENCE_FOR_HISTORICAL_MANIFEST = (
        "INSUFFICIENT_EVIDENCE_FOR_HISTORICAL_MANIFEST"
    )


class HistoricalManifestNextMilestone(StrEnum):
    EXECUTE_VERSION_SAFE_MARKET_STATE_BACKFILL = (
        "EXECUTE_VERSION_SAFE_MARKET_STATE_BACKFILL"
    )
    DESIGN_DIAGNOSTIC_ONLY_MARKET_STATE_BACKFILL = (
        "DESIGN_DIAGNOSTIC_ONLY_MARKET_STATE_BACKFILL"
    )
    BUILD_POINT_IN_TIME_BREADTH_HISTORY = "BUILD_POINT_IN_TIME_BREADTH_HISTORY"
    BUILD_POINT_IN_TIME_SECTOR_HISTORY = "BUILD_POINT_IN_TIME_SECTOR_HISTORY"
    ADD_DEPLOYMENT_RELEASE_TRACKING = "ADD_DEPLOYMENT_RELEASE_TRACKING"
    COLLECT_EXTERNAL_DEPLOYMENT_EVIDENCE = "COLLECT_EXTERNAL_DEPLOYMENT_EVIDENCE"
    REPAIR_CONFLICTING_HISTORICAL_EVIDENCE = "REPAIR_CONFLICTING_HISTORICAL_EVIDENCE"
    ACCEPT_LEGACY_HISTORY_AS_DIAGNOSTIC_ONLY = (
        "ACCEPT_LEGACY_HISTORY_AS_DIAGNOSTIC_ONLY"
    )


class HistoricalVersionRecoveryStatus(StrEnum):
    PERSISTED_EXACT = "PERSISTED_EXACT"
    PERSISTED_FINGERPRINT = "PERSISTED_FINGERPRINT"
    RECOVERED_FROM_AUTHORITATIVE_RELEASE_METADATA = (
        "RECOVERED_FROM_AUTHORITATIVE_RELEASE_METADATA"
    )
    RECOVERED_SEMANTICALLY_COMPATIBLE = "RECOVERED_SEMANTICALLY_COMPATIBLE"
    DATE_RANGE_COMPATIBLE_ONLY = "DATE_RANGE_COMPATIBLE_ONLY"
    OUTPUT_SIGNATURE_COMPATIBLE_ONLY = "OUTPUT_SIGNATURE_COMPATIBLE_ONLY"
    VERSION_UNKNOWN = "VERSION_UNKNOWN"
    CONFLICTING_VERSION_EVIDENCE = "CONFLICTING_VERSION_EVIDENCE"
    KNOWN_INCOMPATIBLE = "KNOWN_INCOMPATIBLE"


class HistoricalBackfillVersionEligibility(StrEnum):
    ELIGIBLE_EXACT = "ELIGIBLE_EXACT"
    ELIGIBLE_FINGERPRINT_MATCH = "ELIGIBLE_FINGERPRINT_MATCH"
    ELIGIBLE_SEMANTICALLY_COMPATIBLE = "ELIGIBLE_SEMANTICALLY_COMPATIBLE"
    DIAGNOSTIC_RECONSTRUCTION_ONLY = "DIAGNOSTIC_RECONSTRUCTION_ONLY"
    BLOCKED_VERSION_UNKNOWN = "BLOCKED_VERSION_UNKNOWN"
    BLOCKED_VERSION_CONFLICT = "BLOCKED_VERSION_CONFLICT"
    BLOCKED_KNOWN_INCOMPATIBLE = "BLOCKED_KNOWN_INCOMPATIBLE"
    BLOCKED_OTHER_SOURCE = "BLOCKED_OTHER_SOURCE"


class VersionLineageConclusion(StrEnum):
    CLASSIFIER_VERSION_LINEAGE_IS_COMPLETE = "CLASSIFIER_VERSION_LINEAGE_IS_COMPLETE"
    CLASSIFIER_VERSION_LINEAGE_IS_PARTIAL = "CLASSIFIER_VERSION_LINEAGE_IS_PARTIAL"
    FUTURE_PROVENANCE_CAPTURE_IS_COMPLETE = "FUTURE_PROVENANCE_CAPTURE_IS_COMPLETE"
    HISTORICAL_VERSION_METADATA_IS_PRIMARY_BOTTLENECK = (
        "HISTORICAL_VERSION_METADATA_IS_PRIMARY_BOTTLENECK"
    )
    HISTORICAL_RELEASE_MAPPING_IS_PRIMARY_BOTTLENECK = (
        "HISTORICAL_RELEASE_MAPPING_IS_PRIMARY_BOTTLENECK"
    )
    VERSION_EVIDENCE_CONFLICT_IS_PRIMARY_BOTTLENECK = (
        "VERSION_EVIDENCE_CONFLICT_IS_PRIMARY_BOTTLENECK"
    )
    CURRENT_AND_HISTORICAL_CLASSIFIERS_ARE_COMPATIBLE = (
        "CURRENT_AND_HISTORICAL_CLASSIFIERS_ARE_COMPATIBLE"
    )
    CURRENT_CLASSIFIER_IS_NOT_HISTORICALLY_COMPATIBLE = (
        "CURRENT_CLASSIFIER_IS_NOT_HISTORICALLY_COMPATIBLE"
    )
    MOST_HISTORY_REMAINS_DIAGNOSTIC_ONLY = "MOST_HISTORY_REMAINS_DIAGNOSTIC_ONLY"
    INSUFFICIENT_EVIDENCE_FOR_VERSION_CONCLUSION = (
        "INSUFFICIENT_EVIDENCE_FOR_VERSION_CONCLUSION"
    )


class VersionLineageNextMilestone(StrEnum):
    EXECUTE_VERSION_SAFE_MARKET_STATE_BACKFILL = (
        "EXECUTE_VERSION_SAFE_MARKET_STATE_BACKFILL"
    )
    DESIGN_DIAGNOSTIC_ONLY_MARKET_STATE_BACKFILL = (
        "DESIGN_DIAGNOSTIC_ONLY_MARKET_STATE_BACKFILL"
    )
    ADD_HISTORICAL_RELEASE_MANIFEST = "ADD_HISTORICAL_RELEASE_MANIFEST"
    COLLECT_MORE_VERSION_EVIDENCE = "COLLECT_MORE_VERSION_EVIDENCE"
    BUILD_POINT_IN_TIME_SECTOR_HISTORY = "BUILD_POINT_IN_TIME_SECTOR_HISTORY"
    BUILD_POINT_IN_TIME_BREADTH_HISTORY = "BUILD_POINT_IN_TIME_BREADTH_HISTORY"
    HARDEN_FUTURE_DECISION_PROVENANCE = "HARDEN_FUTURE_DECISION_PROVENANCE"
    REPAIR_CONFLICTING_VERSION_LINEAGE = "REPAIR_CONFLICTING_VERSION_LINEAGE"


class VersionDriftConclusion(StrEnum):
    NO_VERSION_DRIFT = "NO_VERSION_DRIFT"
    NON_BEHAVIOURAL_VERSION_DRIFT = "NON_BEHAVIOURAL_VERSION_DRIFT"
    BEHAVIOURAL_VERSION_DRIFT = "BEHAVIOURAL_VERSION_DRIFT"
    UNKNOWN_VERSION_DRIFT = "UNKNOWN_VERSION_DRIFT"
    MIXED_VERSION_HISTORY = "MIXED_VERSION_HISTORY"


@dataclass(frozen=True, slots=True)
class ComponentVersion:
    name: str
    analytical_version: str
    config_version: str | None
    fingerprint: str
    payload: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("component name cannot be empty")
        if not self.analytical_version.strip():
            raise ValueError("component analytical version cannot be empty")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(
            self,
            "analytical_version",
            self.analytical_version.strip(),
        )
        object.__setattr__(
            self,
            "config_version",
            _optional_text(self.config_version),
        )
        object.__setattr__(
            self,
            "payload",
            tuple(sorted((key.strip(), value.strip()) for key, value in self.payload)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "analytical_version": self.analytical_version,
            "config_version": self.config_version,
            "fingerprint": self.fingerprint,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class DecisionProvenance:
    provenance_id: str
    application_version: str
    build_version: str | None
    git_commit: str | None
    git_branch: str | None
    working_tree_state: WorkingTreeState
    schema_version: str
    market_state_schema_version: str
    benchmark_builder_version: str
    market_feature_definition_version: str
    market_classifier_name: str
    market_classifier_version: str
    market_classifier_fingerprint: str
    market_classifier_config_version: str
    market_fallback_policy_version: str
    market_intelligence_engine_version: str
    recommendation_engine_version: str
    recommendation_policy_version: str
    entry_timing_engine_version: str
    trade_plan_engine_version: str
    approval_policy_version: str
    allocation_policy_version: str
    created_at: datetime
    runtime_command: str | None
    runtime_mode: str | None
    source: str

    def __post_init__(self) -> None:
        if not self.provenance_id.strip():
            raise ValueError("provenance_id cannot be empty")
        for field_name in (
            "application_version",
            "schema_version",
            "market_state_schema_version",
            "benchmark_builder_version",
            "market_feature_definition_version",
            "market_classifier_name",
            "market_classifier_version",
            "market_classifier_fingerprint",
            "market_classifier_config_version",
            "market_fallback_policy_version",
            "market_intelligence_engine_version",
            "recommendation_engine_version",
            "recommendation_policy_version",
            "entry_timing_engine_version",
            "trade_plan_engine_version",
            "approval_policy_version",
            "allocation_policy_version",
            "source",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "build_version", _optional_text(self.build_version))
        object.__setattr__(self, "git_commit", _clean_commit(self.git_commit))
        object.__setattr__(self, "git_branch", _optional_text(self.git_branch))
        object.__setattr__(
            self,
            "runtime_command",
            _optional_text(self.runtime_command),
        )
        object.__setattr__(self, "runtime_mode", _optional_text(self.runtime_mode))
        object.__setattr__(self, "created_at", _aware(self.created_at))

    def identity_payload(self) -> dict[str, Any]:
        payload = self.as_dict()
        payload.pop("provenance_id")
        payload.pop("created_at")
        return payload

    def as_dict(self) -> dict[str, Any]:
        return {
            "provenance_id": self.provenance_id,
            "application_version": self.application_version,
            "build_version": self.build_version,
            "git_commit": self.git_commit,
            "git_branch": self.git_branch,
            "working_tree_state": self.working_tree_state.value,
            "schema_version": self.schema_version,
            "market_state_schema_version": self.market_state_schema_version,
            "benchmark_builder_version": self.benchmark_builder_version,
            "market_feature_definition_version": self.market_feature_definition_version,
            "market_classifier_name": self.market_classifier_name,
            "market_classifier_version": self.market_classifier_version,
            "market_classifier_fingerprint": self.market_classifier_fingerprint,
            "market_classifier_config_version": self.market_classifier_config_version,
            "market_fallback_policy_version": self.market_fallback_policy_version,
            "market_intelligence_engine_version": (
                self.market_intelligence_engine_version
            ),
            "recommendation_engine_version": self.recommendation_engine_version,
            "recommendation_policy_version": self.recommendation_policy_version,
            "entry_timing_engine_version": self.entry_timing_engine_version,
            "trade_plan_engine_version": self.trade_plan_engine_version,
            "approval_policy_version": self.approval_policy_version,
            "allocation_policy_version": self.allocation_policy_version,
            "created_at": self.created_at.isoformat(),
            "runtime_command": self.runtime_command,
            "runtime_mode": self.runtime_mode,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DecisionProvenance:
        return cls(
            provenance_id=str(payload["provenance_id"]),
            application_version=str(payload["application_version"]),
            build_version=_payload_optional_text(payload.get("build_version")),
            git_commit=_payload_optional_text(payload.get("git_commit")),
            git_branch=_payload_optional_text(payload.get("git_branch")),
            working_tree_state=WorkingTreeState(
                str(payload.get("working_tree_state", WorkingTreeState.UNAVAILABLE))
            ),
            schema_version=str(payload.get("schema_version", "1.0")),
            market_state_schema_version=str(payload["market_state_schema_version"]),
            benchmark_builder_version=str(payload["benchmark_builder_version"]),
            market_feature_definition_version=str(
                payload["market_feature_definition_version"]
            ),
            market_classifier_name=str(payload["market_classifier_name"]),
            market_classifier_version=str(payload["market_classifier_version"]),
            market_classifier_fingerprint=str(payload["market_classifier_fingerprint"]),
            market_classifier_config_version=str(
                payload["market_classifier_config_version"]
            ),
            market_fallback_policy_version=str(
                payload["market_fallback_policy_version"]
            ),
            market_intelligence_engine_version=str(
                payload["market_intelligence_engine_version"]
            ),
            recommendation_engine_version=str(payload["recommendation_engine_version"]),
            recommendation_policy_version=str(payload["recommendation_policy_version"]),
            entry_timing_engine_version=str(payload["entry_timing_engine_version"]),
            trade_plan_engine_version=str(payload["trade_plan_engine_version"]),
            approval_policy_version=str(payload["approval_policy_version"]),
            allocation_policy_version=str(payload["allocation_policy_version"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            runtime_command=_payload_optional_text(payload.get("runtime_command")),
            runtime_mode=_payload_optional_text(payload.get("runtime_mode")),
            source=str(payload["source"]),
        )


@dataclass(frozen=True, slots=True)
class ProvenancePersistenceResult:
    provenance: DecisionProvenance
    inserted: bool
    path: Path


class DecisionProvenanceRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_decision_provenance_path(path)

    def upsert(self, provenance: DecisionProvenance) -> ProvenancePersistenceResult:
        existing = {item.provenance_id: item for item in self.load_all()}
        current = existing.get(provenance.provenance_id)
        if current is not None:
            if current.identity_payload() != provenance.identity_payload():
                raise ValueError("provenance_id collision with different identity")
            return ProvenancePersistenceResult(
                provenance=current,
                inserted=False,
                path=self.path,
            )
        existing[provenance.provenance_id] = provenance
        self._write(tuple(existing.values()))
        return ProvenancePersistenceResult(
            provenance=provenance,
            inserted=True,
            path=self.path,
        )

    def get(self, provenance_id: str) -> DecisionProvenance | None:
        normalized = provenance_id.strip()
        return next(
            (
                provenance
                for provenance in self.load_all()
                if provenance.provenance_id == normalized
            ),
            None,
        )

    def load_all(self) -> tuple[DecisionProvenance, ...]:
        if not self.path.exists():
            return ()
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return ()
        payload = json.loads(raw)
        rows = payload.get("provenance", ()) if isinstance(payload, dict) else ()
        return tuple(
            sorted(
                (
                    DecisionProvenance.from_dict(row)
                    for row in rows
                    if isinstance(row, dict)
                ),
                key=lambda row: (row.created_at, row.provenance_id),
            )
        )

    def _write(self, rows: tuple[DecisionProvenance, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(rows, key=lambda item: item.provenance_id)
        payload = {"provenance": [row.as_dict() for row in ordered]}
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


@dataclass(frozen=True, slots=True)
class VersionEvidenceSource:
    source: str
    record_coverage: int
    date_coverage: int
    reliability: EvidenceReliability
    granularity: str
    point_in_time_validity: bool
    exact_version_capability: bool
    compatibility_only_capability: bool
    limitations: str


@dataclass(frozen=True, slots=True)
class HistoricalEvidenceItem:
    evidence_id: str
    evidence_type: HistoricalEvidenceType
    source: str
    source_location: str
    effective_date_or_range: str | None
    component_affected: str
    observed_version: str | None
    observed_behavior: str
    reliability: EvidenceReliability
    record_level_applicability: bool
    release_level_applicability: bool
    supports_exact_match: bool
    supports_semantic_compatibility: bool
    limitations: str

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id cannot be empty")
        for field_name in (
            "source",
            "source_location",
            "component_affected",
            "observed_behavior",
            "limitations",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, value)
        object.__setattr__(
            self, "observed_version", _optional_text(self.observed_version)
        )
        object.__setattr__(
            self,
            "effective_date_or_range",
            _optional_text(self.effective_date_or_range),
        )


@dataclass(frozen=True, slots=True)
class AnalyticalChangePoint:
    change_id: str
    evidence_reference: str
    effective_date: date | None
    component: str
    previous_behavior_version: str | None
    new_behavior_version: str | None
    impact: AnalyticalChangeImpact
    confidence: EvidenceReliability
    supporting_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.change_id.strip():
            raise ValueError("change_id cannot be empty")
        if not self.evidence_reference.strip():
            raise ValueError("evidence_reference cannot be empty")
        if not self.component.strip():
            raise ValueError("component cannot be empty")
        object.__setattr__(
            self,
            "previous_behavior_version",
            _optional_text(self.previous_behavior_version),
        )
        object.__setattr__(
            self,
            "new_behavior_version",
            _optional_text(self.new_behavior_version),
        )
        object.__setattr__(
            self,
            "supporting_evidence",
            tuple(
                sorted(
                    item.strip() for item in self.supporting_evidence if item.strip()
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class HistoricalAnalyticalEra:
    era_id: str
    name: str
    effective_from: date | None
    effective_to: date | None
    application_version: str | None
    git_commit_start: str | None
    git_commit_end: str | None
    schema_versions: tuple[str, ...]
    component_versions: tuple[tuple[str, str], ...]
    component_fingerprints: tuple[tuple[str, str], ...]
    output_signature: str | None
    fallback_semantics: str | None
    evidence_ids: tuple[str, ...]
    evidence_strength: EvidenceReliability
    confidence: str
    exact_reproduction_supported: bool
    semantic_replay_supported: bool
    known_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.era_id.strip():
            raise ValueError("era_id cannot be empty")
        if not self.name.strip():
            raise ValueError("era name cannot be empty")
        if (
            self.effective_from
            and self.effective_to
            and self.effective_to < self.effective_from
        ):
            raise ValueError("era effective_to cannot be before effective_from")
        object.__setattr__(
            self, "application_version", _optional_text(self.application_version)
        )
        object.__setattr__(
            self, "git_commit_start", _clean_commit(self.git_commit_start)
        )
        object.__setattr__(self, "git_commit_end", _clean_commit(self.git_commit_end))
        object.__setattr__(
            self, "output_signature", _optional_text(self.output_signature)
        )
        object.__setattr__(
            self, "fallback_semantics", _optional_text(self.fallback_semantics)
        )
        object.__setattr__(
            self,
            "schema_versions",
            tuple(
                sorted(item.strip() for item in self.schema_versions if item.strip())
            ),
        )
        object.__setattr__(
            self,
            "component_versions",
            tuple(
                sorted(
                    (key.strip(), value.strip())
                    for key, value in self.component_versions
                )
            ),
        )
        object.__setattr__(
            self,
            "component_fingerprints",
            tuple(
                sorted(
                    (key.strip(), value.strip())
                    for key, value in self.component_fingerprints
                )
            ),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            tuple(sorted(item.strip() for item in self.evidence_ids if item.strip())),
        )
        object.__setattr__(
            self,
            "known_limitations",
            tuple(item.strip() for item in self.known_limitations if item.strip()),
        )


@dataclass(frozen=True, slots=True)
class AnalyticalReleaseManifestEntry:
    manifest_entry_id: str
    release_or_era: str
    effective_from: date | None
    effective_to: date | None
    application_version: str | None
    component_versions: tuple[tuple[str, str], ...]
    component_fingerprints: tuple[tuple[str, str], ...]
    classifier_version: str | None
    classifier_fingerprint: str | None
    feature_definition_version: str | None
    fallback_policy_version: str | None
    recommendation_policy_version: str | None
    entry_timing_version: str | None
    trade_plan_version: str | None
    approval_policy_version: str | None
    allocation_policy_version: str | None
    schema_signature: str | None
    output_signature: str | None
    evidence_refs: tuple[str, ...]
    evidence_strength: EvidenceReliability
    compatibility_policy: ComponentCompatibility
    confidence: str
    review_status: ReleaseReviewStatus
    exact_reproduction_supported: bool
    semantic_replay_supported: bool
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.manifest_entry_id.strip():
            raise ValueError("manifest_entry_id cannot be empty")
        if not self.release_or_era.strip():
            raise ValueError("release_or_era cannot be empty")
        if (
            self.effective_from
            and self.effective_to
            and self.effective_to < self.effective_from
        ):
            raise ValueError("manifest effective_to cannot be before effective_from")
        for field_name in (
            "application_version",
            "classifier_version",
            "classifier_fingerprint",
            "feature_definition_version",
            "fallback_policy_version",
            "recommendation_policy_version",
            "entry_timing_version",
            "trade_plan_version",
            "approval_policy_version",
            "allocation_policy_version",
            "schema_signature",
            "output_signature",
        ):
            object.__setattr__(
                self, field_name, _optional_text(getattr(self, field_name))
            )
        object.__setattr__(
            self,
            "component_versions",
            tuple(
                sorted(
                    (key.strip(), value.strip())
                    for key, value in self.component_versions
                )
            ),
        )
        object.__setattr__(
            self,
            "component_fingerprints",
            tuple(
                sorted(
                    (key.strip(), value.strip())
                    for key, value in self.component_fingerprints
                )
            ),
        )
        object.__setattr__(
            self,
            "evidence_refs",
            tuple(sorted(item.strip() for item in self.evidence_refs if item.strip())),
        )
        object.__setattr__(
            self,
            "limitations",
            tuple(item.strip() for item in self.limitations if item.strip()),
        )
        if self.review_status is ReleaseReviewStatus.VERIFIED:
            if self.evidence_strength not in {
                EvidenceReliability.AUTHORITATIVE,
                EvidenceReliability.STRONG,
            }:
                raise ValueError("verified manifest entry requires strong evidence")
            if self.exact_reproduction_supported and not self.classifier_fingerprint:
                raise ValueError("exact manifest entry requires classifier fingerprint")
        if self.review_status is ReleaseReviewStatus.SUPPORTED:
            if self.evidence_strength not in {
                EvidenceReliability.AUTHORITATIVE,
                EvidenceReliability.STRONG,
                EvidenceReliability.SUPPORTING,
            }:
                raise ValueError(
                    "supported manifest entry requires supporting evidence"
                )
        if self.review_status in {
            ReleaseReviewStatus.PROVISIONAL,
            ReleaseReviewStatus.UNKNOWN,
        }:
            if self.exact_reproduction_supported:
                raise ValueError("provisional or unknown entries cannot be exact")


@dataclass(frozen=True, slots=True)
class AnalyticalReleaseManifest:
    entries: tuple[AnalyticalReleaseManifestEntry, ...]
    evidence: tuple[HistoricalEvidenceItem, ...]
    reviewed_at: datetime
    reviewer: str

    def __post_init__(self) -> None:
        ids = [entry.manifest_entry_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate manifest entry id")
        evidence_ids = {item.evidence_id for item in self.evidence}
        for entry in self.entries:
            missing = [item for item in entry.evidence_refs if item not in evidence_ids]
            if missing:
                raise ValueError(
                    "manifest entry "
                    f"{entry.manifest_entry_id} references missing evidence"
                )
        verified = tuple(
            entry
            for entry in self.entries
            if entry.review_status is ReleaseReviewStatus.VERIFIED
            and entry.exact_reproduction_supported
            and entry.effective_from is not None
            and entry.effective_to is not None
        )
        for index, left in enumerate(verified):
            for right in verified[index + 1 :]:
                left_from = left.effective_from
                left_to = left.effective_to
                right_from = right.effective_from
                right_to = right.effective_to
                if left_from is None or left_to is None:
                    continue
                if right_from is None or right_to is None:
                    continue
                if left_from <= right_to and right_from <= left_to:
                    raise ValueError("overlapping verified exact manifest periods")
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(self.entries, key=lambda item: item.manifest_entry_id)),
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(sorted(self.evidence, key=lambda item: item.evidence_id)),
        )
        object.__setattr__(self, "reviewed_at", _aware(self.reviewed_at))
        if not self.reviewer.strip():
            raise ValueError("manifest reviewer cannot be empty")


@dataclass(frozen=True, slots=True)
class HistoricalFingerprintReconstruction:
    commit: str | None
    component: str
    reconstructed_analytical_version: str | None
    reconstructed_fingerprint: str | None
    current_fingerprint: str
    exact_match: bool
    semantic_match: bool
    reconstruction_confidence: EvidenceReliability
    missing_configuration: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateEraAssignment:
    candidate_id: str
    decision_date: date
    assigned_era_id: str | None
    classifier_version: str | None
    classifier_fingerprint: str | None
    compatibility_status: ComponentCompatibility
    assignment_status: HistoricalEraAssignmentStatus
    evidence_ids: tuple[str, ...]
    evidence_strength: EvidenceReliability
    confidence: str
    alternative_possible_eras: tuple[str, ...]
    blocking_reason: str | None


@dataclass(frozen=True, slots=True)
class ManifestBackfillEligibilityRow:
    candidate_id: str
    decision_date: date
    eligibility: ManifestBackfillEligibility
    market_source_readiness: str
    classifier_readiness: str
    authoritative_eligibility: bool
    blocking_reason: str | None


@dataclass(frozen=True, slots=True)
class ManifestCoverageLayer:
    layer: str
    incremental_records: int
    cumulative_records: int
    exact_records: int
    diagnostic_only_records: int


@dataclass(frozen=True, slots=True)
class HistoricalManifestAuditReport:
    candidate_records: int
    git_commits_inspected: int
    tags_inspected: int
    migrations_inspected: int
    release_documents_inspected: int
    behavioral_change_points: int
    analytical_eras_found: int
    verified_manifest_entries: int
    supported_manifest_entries: int
    provisional_manifest_entries: int
    persisted_exact_records: int
    verified_manifest_matched_records: int
    supported_manifest_matched_records: int
    semantic_compatible_records: int
    diagnostic_only_records: int
    multiple_era_records: int
    conflicting_records: int
    unknown_records: int
    backfill_eligible_exact: int
    backfill_eligible_verified_manifest: int
    backfill_eligible_semantic: int
    blocked_records: int
    evidence: tuple[HistoricalEvidenceItem, ...]
    change_points: tuple[AnalyticalChangePoint, ...]
    eras: tuple[HistoricalAnalyticalEra, ...]
    manifest: AnalyticalReleaseManifest
    fingerprint_reconstructions: tuple[HistoricalFingerprintReconstruction, ...]
    assignments: tuple[CandidateEraAssignment, ...]
    eligibility: tuple[ManifestBackfillEligibilityRow, ...]
    coverage_layers: tuple[ManifestCoverageLayer, ...]
    primary_conclusion: HistoricalManifestConclusion
    secondary_conclusion: HistoricalManifestConclusion | None
    recommended_next_milestone: HistoricalManifestNextMilestone
    explicitly_prohibited_next_action: str
    deployment_history_limitation: str


@dataclass(frozen=True, slots=True)
class CandidateVersionRecovery:
    candidate_id: str
    decision_date: date
    persisted_version: str | None
    recovered_version: str | None
    recovered_fingerprint: str | None
    compatibility_status: ComponentCompatibility
    recovery_status: HistoricalVersionRecoveryStatus
    evidence_sources: tuple[str, ...]
    evidence_strength: EvidenceReliability
    confidence: str
    blocking_reason: str | None


@dataclass(frozen=True, slots=True)
class HistoricalBackfillVersionEligibilityRow:
    candidate_id: str
    decision_date: date
    eligibility: HistoricalBackfillVersionEligibility
    compatibility_status: ComponentCompatibility
    version_blocking_reason: str | None


@dataclass(frozen=True, slots=True)
class VersionLineageAuditReport:
    total_candidate_records: int
    exact_version_coverage: int
    fingerprint_coverage: int
    semantically_compatible_coverage: int
    forward_compatible_only_coverage: int
    unknown_version_coverage: int
    conflicting_evidence: int
    backfill_eligible_records: int
    diagnostic_only_records: int
    recoveries: tuple[CandidateVersionRecovery, ...]
    eligibility: tuple[HistoricalBackfillVersionEligibilityRow, ...]
    evidence_sources: tuple[VersionEvidenceSource, ...]
    primary_conclusion: VersionLineageConclusion
    secondary_conclusion: VersionLineageConclusion | None
    recommended_next_milestone: VersionLineageNextMilestone
    prohibited_next_action: str


@dataclass(frozen=True, slots=True)
class ComponentDriftRow:
    component: str
    persisted_version: str | None
    current_version: str
    persisted_fingerprint: str | None
    current_fingerprint: str
    compatibility: ComponentCompatibility
    behavioural_change_known: bool
    affected_snapshots: int
    affected_candidates: int


@dataclass(frozen=True, slots=True)
class VersionDriftReport:
    rows: tuple[ComponentDriftRow, ...]
    conclusion: VersionDriftConclusion


def current_component_registry() -> tuple[ComponentVersion, ...]:
    components = (
        _component(
            "BenchmarkStateBuilder",
            BENCHMARK_BUILDER_VERSION,
            None,
            {
                "minimum_history_bars": "220",
                "return_windows": "1,5,20",
                "dma_windows": "20,50,200",
                "atr_window": "14",
                "volatility_window": "20",
                "timestamp_rule": "bars_at_or_before_decision_date",
            },
        ),
        _component(
            "MarketFeatureDefinitions",
            MARKET_FEATURE_DEFINITION_VERSION,
            None,
            {
                "benchmark_proxy": "NIFTYBEES_ETF",
                "dma_definition": "arithmetic_mean_close",
                "returns_definition": "close_t_over_close_t_minus_n_minus_one",
            },
        ),
        _component(
            MARKET_CLASSIFIER_NAME,
            MARKET_STATE_CLASSIFIER_VERSION,
            MARKET_CLASSIFIER_CONFIG_VERSION,
            {
                "ordered_bias_labels": "BULLISH,NEUTRAL,BEARISH",
                "fallback_policy": MARKET_FALLBACK_POLICY_VERSION,
                "composite_engine": MARKET_INTELLIGENCE_ENGINE_VERSION,
            },
        ),
        _component(
            "RecommendationEngine",
            RECOMMENDATION_ENGINE_VERSION,
            RECOMMENDATION_POLICY_VERSION,
            {
                "signals": "STRONG_BUY,BUY,WATCHLIST,HOLD,AVOID,SELL",
                "entry_trigger_semantics": "typed",
                "allocation_safety": "avoid_sell_zero",
            },
        ),
        _component(
            "EntryTimingEngine",
            ENTRY_TIMING_ENGINE_VERSION,
            None,
            {
                "states": (
                    "BUILDING,READY_FOR_CONFIRMATION,ENTRY_READY,ACTIVE,LATE,INVALID"
                )
            },
        ),
        _component(
            "TradePlanEngine",
            TRADE_PLAN_ENGINE_VERSION,
            None,
            {"targets": "2R,3R,extension", "trailing_stop": "2ATR_after_entry"},
        ),
        _component(
            "InstitutionalApprovalPolicy",
            APPROVAL_POLICY_VERSION,
            None,
            {"avoid_sell_reject": "skip", "buy_requires_valid_trade_plan": "true"},
        ),
        _component(
            "AllocationPolicy",
            ALLOCATION_POLICY_VERSION,
            None,
            {"deployable_actions": "BUY,ACCUMULATE_POLICY_APPROVED"},
        ),
    )
    names = [component.name for component in components]
    if len(set(names)) != len(names):
        raise ValueError("duplicate component registry entry")
    return components


def current_market_classifier_fingerprint() -> str:
    return _component_by_name(MARKET_CLASSIFIER_NAME).fingerprint


def capture_current_provenance(
    *,
    created_at: datetime,
    runtime_command: str | None,
    runtime_mode: str | None,
    source: str = "runtime",
) -> DecisionProvenance:
    release = current_release()
    git = _git_metadata()
    classifier = _component_by_name(MARKET_CLASSIFIER_NAME)
    working_tree = git["working_tree_state"]
    if not isinstance(working_tree, WorkingTreeState):
        working_tree = WorkingTreeState.UNAVAILABLE
    payload = {
        "application_version": release.version,
        "build_version": release.stage,
        "git_commit": git["commit"],
        "git_branch": git["branch"],
        "working_tree_state": working_tree.value,
        "schema_version": DECISION_PROVENANCE_SCHEMA_VERSION,
        "market_state_schema_version": MARKET_STATE_SNAPSHOT_SCHEMA_VERSION,
        "benchmark_builder_version": BENCHMARK_BUILDER_VERSION,
        "market_feature_definition_version": MARKET_FEATURE_DEFINITION_VERSION,
        "market_classifier_name": MARKET_CLASSIFIER_NAME,
        "market_classifier_version": MARKET_STATE_CLASSIFIER_VERSION,
        "market_classifier_fingerprint": classifier.fingerprint,
        "market_classifier_config_version": MARKET_CLASSIFIER_CONFIG_VERSION,
        "market_fallback_policy_version": MARKET_FALLBACK_POLICY_VERSION,
        "market_intelligence_engine_version": MARKET_INTELLIGENCE_ENGINE_VERSION,
        "recommendation_engine_version": RECOMMENDATION_ENGINE_VERSION,
        "recommendation_policy_version": RECOMMENDATION_POLICY_VERSION,
        "entry_timing_engine_version": ENTRY_TIMING_ENGINE_VERSION,
        "trade_plan_engine_version": TRADE_PLAN_ENGINE_VERSION,
        "approval_policy_version": APPROVAL_POLICY_VERSION,
        "allocation_policy_version": ALLOCATION_POLICY_VERSION,
        "runtime_command": runtime_command,
        "runtime_mode": runtime_mode,
        "source": source,
    }
    provenance_id = _stable_id(payload)
    return DecisionProvenance(
        provenance_id=provenance_id,
        created_at=created_at,
        application_version=release.version,
        build_version=release.stage,
        git_commit=str(git["commit"]) if git["commit"] is not None else None,
        git_branch=str(git["branch"]) if git["branch"] is not None else None,
        working_tree_state=working_tree,
        schema_version=DECISION_PROVENANCE_SCHEMA_VERSION,
        market_state_schema_version=MARKET_STATE_SNAPSHOT_SCHEMA_VERSION,
        benchmark_builder_version=BENCHMARK_BUILDER_VERSION,
        market_feature_definition_version=MARKET_FEATURE_DEFINITION_VERSION,
        market_classifier_name=MARKET_CLASSIFIER_NAME,
        market_classifier_version=MARKET_STATE_CLASSIFIER_VERSION,
        market_classifier_fingerprint=classifier.fingerprint,
        market_classifier_config_version=MARKET_CLASSIFIER_CONFIG_VERSION,
        market_fallback_policy_version=MARKET_FALLBACK_POLICY_VERSION,
        market_intelligence_engine_version=MARKET_INTELLIGENCE_ENGINE_VERSION,
        recommendation_engine_version=RECOMMENDATION_ENGINE_VERSION,
        recommendation_policy_version=RECOMMENDATION_POLICY_VERSION,
        entry_timing_engine_version=ENTRY_TIMING_ENGINE_VERSION,
        trade_plan_engine_version=TRADE_PLAN_ENGINE_VERSION,
        approval_policy_version=APPROVAL_POLICY_VERSION,
        allocation_policy_version=ALLOCATION_POLICY_VERSION,
        runtime_command=runtime_command,
        runtime_mode=runtime_mode,
        source=source,
    )


def build_version_lineage_audit(
    *,
    records: tuple[Any, ...],
    snapshots: tuple[Any, ...],
    provenances: tuple[DecisionProvenance, ...],
) -> VersionLineageAuditReport:
    provenance_by_id = {item.provenance_id: item for item in provenances}
    recoveries = tuple(_recover_record(record, provenance_by_id) for record in records)
    eligibility = tuple(_eligibility(row) for row in recoveries)
    evidence = _evidence_sources(records, snapshots, provenances)
    exact = sum(
        1
        for row in recoveries
        if row.recovery_status is HistoricalVersionRecoveryStatus.PERSISTED_EXACT
    )
    fingerprint = sum(
        1
        for row in recoveries
        if row.recovery_status is HistoricalVersionRecoveryStatus.PERSISTED_FINGERPRINT
    )
    semantic = sum(
        1
        for row in recoveries
        if row.recovery_status
        is HistoricalVersionRecoveryStatus.RECOVERED_SEMANTICALLY_COMPATIBLE
    )
    forward = sum(
        1
        for row in recoveries
        if row.recovery_status
        is HistoricalVersionRecoveryStatus.OUTPUT_SIGNATURE_COMPATIBLE_ONLY
    )
    unknown = sum(
        1
        for row in recoveries
        if row.recovery_status is HistoricalVersionRecoveryStatus.VERSION_UNKNOWN
    )
    conflicts = sum(
        1
        for row in recoveries
        if row.recovery_status
        is HistoricalVersionRecoveryStatus.CONFLICTING_VERSION_EVIDENCE
    )
    eligible = sum(
        1
        for row in eligibility
        if row.eligibility
        in {
            HistoricalBackfillVersionEligibility.ELIGIBLE_EXACT,
            HistoricalBackfillVersionEligibility.ELIGIBLE_FINGERPRINT_MATCH,
        }
    )
    diagnostic = sum(
        1
        for row in eligibility
        if row.eligibility
        is HistoricalBackfillVersionEligibility.DIAGNOSTIC_RECONSTRUCTION_ONLY
    )
    if conflicts:
        conclusion = (
            VersionLineageConclusion.VERSION_EVIDENCE_CONFLICT_IS_PRIMARY_BOTTLENECK
        )
        milestone = VersionLineageNextMilestone.REPAIR_CONFLICTING_VERSION_LINEAGE
    elif not records:
        conclusion = (
            VersionLineageConclusion.INSUFFICIENT_EVIDENCE_FOR_VERSION_CONCLUSION
        )
        milestone = VersionLineageNextMilestone.COLLECT_MORE_VERSION_EVIDENCE
    elif unknown > exact + fingerprint:
        conclusion = (
            VersionLineageConclusion.HISTORICAL_VERSION_METADATA_IS_PRIMARY_BOTTLENECK
        )
        milestone = (
            VersionLineageNextMilestone.ADD_HISTORICAL_RELEASE_MANIFEST
            if fingerprint
            else VersionLineageNextMilestone.HARDEN_FUTURE_DECISION_PROVENANCE
        )
    elif unknown:
        conclusion = VersionLineageConclusion.CLASSIFIER_VERSION_LINEAGE_IS_PARTIAL
        milestone = VersionLineageNextMilestone.COLLECT_MORE_VERSION_EVIDENCE
    else:
        conclusion = VersionLineageConclusion.CLASSIFIER_VERSION_LINEAGE_IS_COMPLETE
        milestone = (
            VersionLineageNextMilestone.EXECUTE_VERSION_SAFE_MARKET_STATE_BACKFILL
        )
    return VersionLineageAuditReport(
        total_candidate_records=len(records),
        exact_version_coverage=exact,
        fingerprint_coverage=fingerprint,
        semantically_compatible_coverage=semantic,
        forward_compatible_only_coverage=forward,
        unknown_version_coverage=unknown,
        conflicting_evidence=conflicts,
        backfill_eligible_records=eligible,
        diagnostic_only_records=diagnostic,
        recoveries=recoveries,
        eligibility=eligibility,
        evidence_sources=evidence,
        primary_conclusion=conclusion,
        secondary_conclusion=(
            VersionLineageConclusion.FUTURE_PROVENANCE_CAPTURE_IS_COMPLETE
            if fingerprint
            else VersionLineageConclusion.MOST_HISTORY_REMAINS_DIAGNOSTIC_ONLY
            if unknown
            else None
        ),
        recommended_next_milestone=milestone,
        prohibited_next_action=(
            "Do not execute historical market-state backfill, auto-assign unknown "
            "classifier versions, rewrite legacy candidates, tune thresholds, "
            "change verdicts, alter gates, modify trade plans, change approvals, "
            "or change allocation from this lineage audit."
        ),
    )


def build_version_drift_report(
    *,
    records: tuple[Any, ...],
    snapshots: tuple[Any, ...],
    provenances: tuple[DecisionProvenance, ...],
) -> VersionDriftReport:
    current = _component_by_name(MARKET_CLASSIFIER_NAME)
    affected_candidates = sum(
        1 for record in records if getattr(record, "decision_provenance_id", None)
    )
    affected_snapshots = sum(
        1 for snapshot in snapshots if getattr(snapshot, "provenance_id", None)
    )
    rows = []
    if not provenances:
        rows.append(
            ComponentDriftRow(
                component=MARKET_CLASSIFIER_NAME,
                persisted_version=None,
                current_version=current.analytical_version,
                persisted_fingerprint=None,
                current_fingerprint=current.fingerprint,
                compatibility=ComponentCompatibility.VERSION_UNKNOWN,
                behavioural_change_known=False,
                affected_snapshots=affected_snapshots,
                affected_candidates=affected_candidates,
            )
        )
        return VersionDriftReport(
            rows=tuple(rows),
            conclusion=VersionDriftConclusion.UNKNOWN_VERSION_DRIFT,
        )
    for provenance in provenances:
        compatibility = compatibility_for(
            persisted_version=provenance.market_classifier_version,
            current_version=current.analytical_version,
            persisted_fingerprint=provenance.market_classifier_fingerprint,
            current_fingerprint=current.fingerprint,
        )
        rows.append(
            ComponentDriftRow(
                component=MARKET_CLASSIFIER_NAME,
                persisted_version=provenance.market_classifier_version,
                current_version=current.analytical_version,
                persisted_fingerprint=provenance.market_classifier_fingerprint,
                current_fingerprint=current.fingerprint,
                compatibility=compatibility,
                behavioural_change_known=compatibility
                is ComponentCompatibility.INCOMPATIBLE,
                affected_snapshots=sum(
                    1
                    for snapshot in snapshots
                    if getattr(snapshot, "provenance_id", None)
                    == provenance.provenance_id
                ),
                affected_candidates=sum(
                    1
                    for record in records
                    if getattr(record, "decision_provenance_id", None)
                    == provenance.provenance_id
                ),
            )
        )
    conclusion = (
        VersionDriftConclusion.NO_VERSION_DRIFT
        if all(
            row.compatibility
            in {
                ComponentCompatibility.EXACT_VERSION_MATCH,
                ComponentCompatibility.EXACT_FINGERPRINT_MATCH,
            }
            for row in rows
        )
        else VersionDriftConclusion.MIXED_VERSION_HISTORY
    )
    return VersionDriftReport(rows=tuple(rows), conclusion=conclusion)


def build_historical_manifest_audit(
    *,
    records: tuple[Any, ...],
    snapshots: tuple[Any, ...],
    provenances: tuple[DecisionProvenance, ...],
) -> HistoricalManifestAuditReport:
    evidence = build_historical_evidence_inventory(
        records=records,
        snapshots=snapshots,
        provenances=provenances,
    )
    change_points = detect_analytical_change_points(evidence)
    eras = build_historical_analytical_eras(evidence, provenances)
    manifest = build_current_analytical_release_manifest(
        evidence=evidence,
        eras=eras,
    )
    assignments = assign_historical_candidate_eras(
        records=records,
        provenances=provenances,
        manifest=manifest,
    )
    eligibility = tuple(_manifest_eligibility(row) for row in assignments)
    coverage_layers = _manifest_coverage_layers(assignments)
    fingerprints = reconstruct_historical_semantic_fingerprints()
    verified = sum(
        1
        for entry in manifest.entries
        if entry.review_status is ReleaseReviewStatus.VERIFIED
    )
    supported = sum(
        1
        for entry in manifest.entries
        if entry.review_status is ReleaseReviewStatus.SUPPORTED
    )
    provisional = sum(
        1
        for entry in manifest.entries
        if entry.review_status is ReleaseReviewStatus.PROVISIONAL
    )
    persisted_exact = sum(
        1
        for row in assignments
        if row.assignment_status
        in {
            HistoricalEraAssignmentStatus.PERSISTED_EXACT_PROVENANCE,
            HistoricalEraAssignmentStatus.PERSISTED_EXACT_CLASSIFIER_VERSION,
        }
    )
    verified_matches = sum(
        1
        for row in assignments
        if row.assignment_status
        is HistoricalEraAssignmentStatus.MATCHED_VERIFIED_MANIFEST
    )
    supported_matches = sum(
        1
        for row in assignments
        if row.assignment_status
        is HistoricalEraAssignmentStatus.MATCHED_SUPPORTED_MANIFEST
    )
    semantic = sum(
        1
        for row in assignments
        if row.compatibility_status is ComponentCompatibility.SEMANTICALLY_COMPATIBLE
    )
    diagnostic = sum(
        1
        for row in assignments
        if row.assignment_status
        in {
            HistoricalEraAssignmentStatus.OUTPUT_SIGNATURE_ONLY,
            HistoricalEraAssignmentStatus.DATE_RANGE_ONLY,
        }
    )
    multiple = sum(
        1
        for row in assignments
        if row.assignment_status is HistoricalEraAssignmentStatus.MULTIPLE_POSSIBLE_ERAS
    )
    conflicting = sum(
        1
        for row in assignments
        if row.assignment_status is HistoricalEraAssignmentStatus.CONFLICTING_EVIDENCE
    )
    unknown = sum(
        1
        for row in assignments
        if row.assignment_status is HistoricalEraAssignmentStatus.UNKNOWN_ERA
    )
    eligible_exact = sum(
        1
        for row in eligibility
        if row.eligibility
        in {
            ManifestBackfillEligibility.ELIGIBLE_PERSISTED_EXACT,
            ManifestBackfillEligibility.ELIGIBLE_EXACT_FINGERPRINT,
        }
    )
    eligible_verified = sum(
        1
        for row in eligibility
        if row.eligibility is ManifestBackfillEligibility.ELIGIBLE_VERIFIED_MANIFEST
    )
    eligible_semantic = sum(
        1
        for row in eligibility
        if row.eligibility is ManifestBackfillEligibility.ELIGIBLE_SUPPORTED_SEMANTIC
    )
    blocked = len(eligibility) - eligible_exact - eligible_verified - eligible_semantic
    primary, secondary, milestone = _manifest_conclusions(
        candidate_records=len(records),
        persisted_exact=persisted_exact,
        verified_matches=verified_matches,
        supported_matches=supported_matches,
        diagnostic=diagnostic,
        unknown=unknown,
        conflicting=conflicting,
        eligible_exact=eligible_exact,
        eligible_verified=eligible_verified,
        eligible_semantic=eligible_semantic,
    )
    return HistoricalManifestAuditReport(
        candidate_records=len(records),
        git_commits_inspected=_git_count("rev-list", "--count", "HEAD"),
        tags_inspected=_git_count("tag", "--list"),
        migrations_inspected=_path_count(("migrations", "alpha/migrations")),
        release_documents_inspected=_path_count(("docs", "README.md", "CHANGELOG.md")),
        behavioral_change_points=sum(
            1
            for row in change_points
            if row.impact is AnalyticalChangeImpact.BEHAVIOURAL_CHANGE
        ),
        analytical_eras_found=len(eras),
        verified_manifest_entries=verified,
        supported_manifest_entries=supported,
        provisional_manifest_entries=provisional,
        persisted_exact_records=persisted_exact,
        verified_manifest_matched_records=verified_matches,
        supported_manifest_matched_records=supported_matches,
        semantic_compatible_records=semantic,
        diagnostic_only_records=diagnostic,
        multiple_era_records=multiple,
        conflicting_records=conflicting,
        unknown_records=unknown,
        backfill_eligible_exact=eligible_exact,
        backfill_eligible_verified_manifest=eligible_verified,
        backfill_eligible_semantic=eligible_semantic,
        blocked_records=blocked,
        evidence=evidence,
        change_points=change_points,
        eras=eras,
        manifest=manifest,
        fingerprint_reconstructions=fingerprints,
        assignments=assignments,
        eligibility=eligibility,
        coverage_layers=coverage_layers,
        primary_conclusion=primary,
        secondary_conclusion=secondary,
        recommended_next_milestone=milestone,
        explicitly_prohibited_next_action=(
            "Do not execute historical market-state backfill, auto-assign unknown "
            "eras, infer exact provenance from dates alone, rewrite legacy candidates, "
            "change analytical thresholds, alter gates, or change allocation."
        ),
        deployment_history_limitation=(
            "Repository history identifies available code states but does not "
            "necessarily prove which state produced a specific historical record."
        ),
    )


def build_historical_evidence_inventory(
    *,
    records: tuple[Any, ...],
    snapshots: tuple[Any, ...],
    provenances: tuple[DecisionProvenance, ...],
) -> tuple[HistoricalEvidenceItem, ...]:
    current = _component_by_name(MARKET_CLASSIFIER_NAME)
    git_commit = _git("rev-parse", "HEAD")
    git_commit_count = _git_count("rev-list", "--count", "HEAD")
    tag_count = _git_count("tag", "--list")
    classifier_versions = sum(
        1 for record in records if getattr(record, "classifier_version", None)
    )
    candidate_provenance = sum(
        1 for record in records if getattr(record, "decision_provenance_id", None)
    )
    snapshot_provenance = sum(
        1 for snapshot in snapshots if getattr(snapshot, "provenance_id", None)
    )
    output_signature_count = sum(
        1 for record in records if _has_candidate_output_signature(record)
    )
    created_dates = [
        value
        for value in (getattr(record, "created_at", None) for record in records)
        if isinstance(value, datetime)
    ]
    created_range = (
        None
        if not created_dates
        else (
            f"{min(created_dates).date().isoformat()}.."
            f"{max(created_dates).date().isoformat()}"
        )
    )
    return tuple(
        sorted(
            (
                HistoricalEvidenceItem(
                    evidence_id="git_commit_history",
                    evidence_type=HistoricalEvidenceType.GIT_COMMIT_HISTORY,
                    source="git rev-list HEAD",
                    source_location="local repository",
                    effective_date_or_range=None,
                    component_affected="all analytical components",
                    observed_version=git_commit,
                    observed_behavior=(
                        f"{git_commit_count} commits available for inspection"
                    ),
                    reliability=(
                        EvidenceReliability.SUPPORTING
                        if git_commit
                        else EvidenceReliability.UNUSABLE
                    ),
                    record_level_applicability=False,
                    release_level_applicability=True,
                    supports_exact_match=False,
                    supports_semantic_compatibility=git_commit is not None,
                    limitations=(
                        "Git proves code existed; it does not prove deployed runtime."
                    ),
                ),
                HistoricalEvidenceItem(
                    evidence_id="git_tag_history",
                    evidence_type=HistoricalEvidenceType.GIT_TAG_HISTORY,
                    source="git tag --list",
                    source_location="local repository",
                    effective_date_or_range=None,
                    component_affected="release packaging",
                    observed_version=None,
                    observed_behavior=f"{tag_count} tags available",
                    reliability=(
                        EvidenceReliability.STRONG
                        if tag_count
                        else EvidenceReliability.WEAK
                    ),
                    record_level_applicability=False,
                    release_level_applicability=bool(tag_count),
                    supports_exact_match=False,
                    supports_semantic_compatibility=bool(tag_count),
                    limitations=(
                        "Tags help identify release candidates only when tied to "
                        "deployment evidence."
                    ),
                ),
                HistoricalEvidenceItem(
                    evidence_id="release_metadata_current",
                    evidence_type=HistoricalEvidenceType.RELEASE_METADATA,
                    source="alpha.release.current_release",
                    source_location="alpha/release.py",
                    effective_date_or_range=None,
                    component_affected="application release",
                    observed_version=current_release().version,
                    observed_behavior=current_release().stage,
                    reliability=EvidenceReliability.SUPPORTING,
                    record_level_applicability=False,
                    release_level_applicability=True,
                    supports_exact_match=False,
                    supports_semantic_compatibility=True,
                    limitations=(
                        "Package metadata alone is not a record-level "
                        "provenance source."
                    ),
                ),
                HistoricalEvidenceItem(
                    evidence_id="component_registry_current",
                    evidence_type=HistoricalEvidenceType.SCHEMA_SIGNATURE,
                    source="current_component_registry",
                    source_location="alpha/provenance.py",
                    effective_date_or_range=None,
                    component_affected="analytical component registry",
                    observed_version=current.analytical_version,
                    observed_behavior=f"current fingerprint {current.fingerprint}",
                    reliability=EvidenceReliability.STRONG,
                    record_level_applicability=False,
                    release_level_applicability=True,
                    supports_exact_match=False,
                    supports_semantic_compatibility=True,
                    limitations=(
                        "Current registry is exact for current runtime only unless "
                        "linked to a persisted record."
                    ),
                ),
                HistoricalEvidenceItem(
                    evidence_id="decision_provenance_ledger",
                    evidence_type=HistoricalEvidenceType.DECISION_PROVENANCE_LEDGER,
                    source="DecisionProvenanceRepository",
                    source_location=str(DEFAULT_DECISION_PROVENANCE_PATH),
                    effective_date_or_range=_date_range(
                        tuple(item.created_at.date() for item in provenances)
                    ),
                    component_affected="runtime provenance",
                    observed_version=MARKET_STATE_CLASSIFIER_VERSION,
                    observed_behavior=(
                        f"{len(provenances)} persisted runtime provenance records"
                    ),
                    reliability=EvidenceReliability.AUTHORITATIVE,
                    record_level_applicability=True,
                    release_level_applicability=True,
                    supports_exact_match=bool(provenances),
                    supports_semantic_compatibility=bool(provenances),
                    limitations=(
                        "Only covers records created after provenance persistence "
                        "exists."
                    ),
                ),
                HistoricalEvidenceItem(
                    evidence_id="candidate_classifier_version_field",
                    evidence_type=HistoricalEvidenceType.CANDIDATE_RECORD_FIELD,
                    source="CandidateDecisionRecord.classifier_version",
                    source_location="candidate learning ledger",
                    effective_date_or_range=created_range,
                    component_affected="candidate classifier version",
                    observed_version=MARKET_STATE_CLASSIFIER_VERSION,
                    observed_behavior=(
                        f"{classifier_versions} candidate rows contain "
                        "classifier_version"
                    ),
                    reliability=(
                        EvidenceReliability.STRONG
                        if classifier_versions
                        else EvidenceReliability.UNUSABLE
                    ),
                    record_level_applicability=True,
                    release_level_applicability=False,
                    supports_exact_match=bool(classifier_versions),
                    supports_semantic_compatibility=bool(classifier_versions),
                    limitations=(
                        "Rows without this field cannot inherit the version from "
                        "nearby rows."
                    ),
                ),
                HistoricalEvidenceItem(
                    evidence_id="candidate_decision_provenance_field",
                    evidence_type=HistoricalEvidenceType.CANDIDATE_RECORD_FIELD,
                    source="CandidateDecisionRecord.decision_provenance_id",
                    source_location="candidate learning ledger",
                    effective_date_or_range=created_range,
                    component_affected="candidate runtime provenance link",
                    observed_version=None,
                    observed_behavior=(
                        f"{candidate_provenance} candidate rows link to provenance"
                    ),
                    reliability=EvidenceReliability.AUTHORITATIVE,
                    record_level_applicability=True,
                    release_level_applicability=False,
                    supports_exact_match=bool(candidate_provenance),
                    supports_semantic_compatibility=bool(candidate_provenance),
                    limitations=(
                        "Missing links remain unknown unless another exact source "
                        "exists."
                    ),
                ),
                HistoricalEvidenceItem(
                    evidence_id="snapshot_provenance_field",
                    evidence_type=HistoricalEvidenceType.MARKET_STATE_SNAPSHOT_FIELD,
                    source="MarketStateSnapshot.provenance_id",
                    source_location="market-state snapshot ledger",
                    effective_date_or_range=_date_range(
                        tuple(
                            snapshot.market_date
                            for snapshot in snapshots
                            if getattr(snapshot, "provenance_id", None)
                        )
                    ),
                    component_affected="market-state snapshot provenance",
                    observed_version=MARKET_STATE_CLASSIFIER_VERSION,
                    observed_behavior=(
                        f"{snapshot_provenance} snapshots link to provenance"
                    ),
                    reliability=EvidenceReliability.AUTHORITATIVE,
                    record_level_applicability=False,
                    release_level_applicability=True,
                    supports_exact_match=bool(snapshot_provenance),
                    supports_semantic_compatibility=bool(snapshot_provenance),
                    limitations=(
                        "Snapshot provenance does not automatically prove candidate "
                        "decision provenance."
                    ),
                ),
                HistoricalEvidenceItem(
                    evidence_id="candidate_output_signature",
                    evidence_type=HistoricalEvidenceType.OUTPUT_SIGNATURE,
                    source="CandidateDecisionRecord output fields",
                    source_location="candidate learning ledger",
                    effective_date_or_range=created_range,
                    component_affected="candidate output signature",
                    observed_version=None,
                    observed_behavior=(
                        f"{output_signature_count} rows expose current-style "
                        "trade-plan fields"
                    ),
                    reliability=(
                        EvidenceReliability.WEAK
                        if output_signature_count
                        else EvidenceReliability.UNUSABLE
                    ),
                    record_level_applicability=True,
                    release_level_applicability=False,
                    supports_exact_match=False,
                    supports_semantic_compatibility=bool(output_signature_count),
                    limitations=(
                        "Output signatures can support diagnostic replay but do not "
                        "establish exact historical provenance."
                    ),
                ),
                HistoricalEvidenceItem(
                    evidence_id="approval_diagnostics_documentation",
                    evidence_type=HistoricalEvidenceType.DOCUMENTATION,
                    source="docs/APPROVAL_DIAGNOSTICS.md",
                    source_location="docs/APPROVAL_DIAGNOSTICS.md",
                    effective_date_or_range=None,
                    component_affected="diagnostic documentation",
                    observed_version=None,
                    observed_behavior="documents lineage commands and limitations",
                    reliability=EvidenceReliability.SUPPORTING,
                    record_level_applicability=False,
                    release_level_applicability=True,
                    supports_exact_match=False,
                    supports_semantic_compatibility=True,
                    limitations="Documentation wording is not deployment proof.",
                ),
                HistoricalEvidenceItem(
                    evidence_id="deployment_history_absent",
                    evidence_type=HistoricalEvidenceType.DEPLOYMENT_HISTORY,
                    source="deployment logs/build artifacts",
                    source_location="not found in local repository",
                    effective_date_or_range=None,
                    component_affected="runtime deployment",
                    observed_version=None,
                    observed_behavior="no authoritative deployment manifest found",
                    reliability=EvidenceReliability.UNUSABLE,
                    record_level_applicability=False,
                    release_level_applicability=False,
                    supports_exact_match=False,
                    supports_semantic_compatibility=False,
                    limitations=(
                        "Absent deployment history blocks date-only exact historical "
                        "assignment."
                    ),
                ),
            ),
            key=lambda item: item.evidence_id,
        )
    )


def detect_analytical_change_points(
    evidence: tuple[HistoricalEvidenceItem, ...],
) -> tuple[AnalyticalChangePoint, ...]:
    change_points: list[AnalyticalChangePoint] = []
    if any(item.evidence_id == "component_registry_current" for item in evidence):
        change_points.append(
            AnalyticalChangePoint(
                change_id="current-component-registry-baseline",
                evidence_reference="component_registry_current",
                effective_date=None,
                component="analytical component registry",
                previous_behavior_version=None,
                new_behavior_version=MARKET_STATE_CLASSIFIER_VERSION,
                impact=AnalyticalChangeImpact.BEHAVIOURAL_CHANGE,
                confidence=EvidenceReliability.STRONG,
                supporting_evidence=("component_registry_current",),
            )
        )
    if any(
        item.evidence_id == "candidate_decision_provenance_field" for item in evidence
    ):
        change_points.append(
            AnalyticalChangePoint(
                change_id="decision-provenance-schema-introduction",
                evidence_reference="candidate_decision_provenance_field",
                effective_date=None,
                component="candidate record schema",
                previous_behavior_version=None,
                new_behavior_version=DECISION_PROVENANCE_SCHEMA_VERSION,
                impact=AnalyticalChangeImpact.SCHEMA_ONLY_CHANGE,
                confidence=EvidenceReliability.AUTHORITATIVE,
                supporting_evidence=(
                    "candidate_decision_provenance_field",
                    "decision_provenance_ledger",
                ),
            )
        )
    if any(
        item.evidence_id == "approval_diagnostics_documentation" for item in evidence
    ):
        change_points.append(
            AnalyticalChangePoint(
                change_id="approval-diagnostics-documentation",
                evidence_reference="approval_diagnostics_documentation",
                effective_date=None,
                component="documentation",
                previous_behavior_version=None,
                new_behavior_version=None,
                impact=AnalyticalChangeImpact.DOCUMENTATION_ONLY_CHANGE,
                confidence=EvidenceReliability.SUPPORTING,
                supporting_evidence=("approval_diagnostics_documentation",),
            )
        )
    return tuple(sorted(change_points, key=lambda item: item.change_id))


def build_historical_analytical_eras(
    evidence: tuple[HistoricalEvidenceItem, ...],
    provenances: tuple[DecisionProvenance, ...],
) -> tuple[HistoricalAnalyticalEra, ...]:
    components = current_component_registry()
    current_fingerprints = tuple(
        (component.name, component.fingerprint) for component in components
    )
    current_versions = tuple(
        (component.name, component.analytical_version) for component in components
    )
    dates = tuple(item.created_at.date() for item in provenances)
    effective_from = min(dates) if dates else None
    effective_to = max(dates) if dates else None
    eras = [
        HistoricalAnalyticalEra(
            era_id="current-provenance-era",
            name="Current Provenance-Captured Analytical Era",
            effective_from=effective_from,
            effective_to=effective_to,
            application_version=current_release().version,
            git_commit_start=_git("rev-parse", "HEAD"),
            git_commit_end=_git("rev-parse", "HEAD"),
            schema_versions=(
                DECISION_PROVENANCE_SCHEMA_VERSION,
                MARKET_STATE_SNAPSHOT_SCHEMA_VERSION,
            ),
            component_versions=current_versions,
            component_fingerprints=current_fingerprints,
            output_signature="current recommendation/trade-plan output contract",
            fallback_semantics=MARKET_FALLBACK_POLICY_VERSION,
            evidence_ids=(
                "component_registry_current",
                "decision_provenance_ledger",
                "release_metadata_current",
            ),
            evidence_strength=EvidenceReliability.AUTHORITATIVE
            if provenances
            else EvidenceReliability.STRONG,
            confidence="HIGH" if provenances else "MEDIUM",
            exact_reproduction_supported=bool(provenances),
            semantic_replay_supported=True,
            known_limitations=(
                "Exact assignment requires each record to link to persisted "
                "provenance.",
            ),
        ),
        HistoricalAnalyticalEra(
            era_id="legacy-output-signature-diagnostic-era",
            name="Legacy Output-Signature Diagnostic Era",
            effective_from=None,
            effective_to=None,
            application_version=None,
            git_commit_start=None,
            git_commit_end=None,
            schema_versions=("candidate-output-signature",),
            component_versions=(),
            component_fingerprints=(),
            output_signature="candidate record has current-style output fields",
            fallback_semantics=None,
            evidence_ids=("candidate_output_signature",),
            evidence_strength=EvidenceReliability.WEAK,
            confidence="LOW",
            exact_reproduction_supported=False,
            semantic_replay_supported=True,
            known_limitations=(
                "Output signature is diagnostic only and cannot establish exact "
                "lineage.",
            ),
        ),
    ]
    _validate_eras(tuple(eras))
    return tuple(sorted(eras, key=lambda item: item.era_id))


def build_current_analytical_release_manifest(
    *,
    evidence: tuple[HistoricalEvidenceItem, ...],
    eras: tuple[HistoricalAnalyticalEra, ...],
) -> AnalyticalReleaseManifest:
    evidence_by_id = {item.evidence_id for item in evidence}
    components = current_component_registry()
    component_versions = tuple(
        (component.name, component.analytical_version) for component in components
    )
    component_fingerprints = tuple(
        (component.name, component.fingerprint) for component in components
    )
    current_era = next(item for item in eras if item.era_id == "current-provenance-era")
    entries = [
        AnalyticalReleaseManifestEntry(
            manifest_entry_id="current-provenance-era",
            release_or_era=current_era.name,
            effective_from=current_era.effective_from,
            effective_to=current_era.effective_to,
            application_version=current_release().version,
            component_versions=component_versions,
            component_fingerprints=component_fingerprints,
            classifier_version=MARKET_STATE_CLASSIFIER_VERSION,
            classifier_fingerprint=current_market_classifier_fingerprint(),
            feature_definition_version=MARKET_FEATURE_DEFINITION_VERSION,
            fallback_policy_version=MARKET_FALLBACK_POLICY_VERSION,
            recommendation_policy_version=RECOMMENDATION_POLICY_VERSION,
            entry_timing_version=ENTRY_TIMING_ENGINE_VERSION,
            trade_plan_version=TRADE_PLAN_ENGINE_VERSION,
            approval_policy_version=APPROVAL_POLICY_VERSION,
            allocation_policy_version=ALLOCATION_POLICY_VERSION,
            schema_signature=MARKET_STATE_SNAPSHOT_SCHEMA_VERSION,
            output_signature="current recommendation/trade-plan output contract",
            evidence_refs=tuple(
                item
                for item in (
                    "component_registry_current",
                    "decision_provenance_ledger",
                    "release_metadata_current",
                )
                if item in evidence_by_id
            ),
            evidence_strength=EvidenceReliability.AUTHORITATIVE
            if current_era.exact_reproduction_supported
            else EvidenceReliability.STRONG,
            compatibility_policy=ComponentCompatibility.EXACT_FINGERPRINT_MATCH,
            confidence="HIGH" if current_era.exact_reproduction_supported else "MEDIUM",
            review_status=ReleaseReviewStatus.VERIFIED,
            exact_reproduction_supported=current_era.exact_reproduction_supported,
            semantic_replay_supported=True,
            limitations=(
                "This entry is exact only for records that carry matching "
                "persisted provenance.",
            ),
        ),
        AnalyticalReleaseManifestEntry(
            manifest_entry_id="legacy-output-signature-diagnostic-era",
            release_or_era="Legacy Output-Signature Diagnostic Era",
            effective_from=None,
            effective_to=None,
            application_version=None,
            component_versions=(),
            component_fingerprints=(),
            classifier_version=None,
            classifier_fingerprint=None,
            feature_definition_version=None,
            fallback_policy_version=None,
            recommendation_policy_version=None,
            entry_timing_version=None,
            trade_plan_version=None,
            approval_policy_version=None,
            allocation_policy_version=None,
            schema_signature="candidate-output-signature",
            output_signature="candidate record has current-style output fields",
            evidence_refs=tuple(
                item
                for item in ("candidate_output_signature",)
                if item in evidence_by_id
            ),
            evidence_strength=EvidenceReliability.WEAK,
            compatibility_policy=ComponentCompatibility.FORWARD_COMPATIBLE_FOR_REPLAY,
            confidence="LOW",
            review_status=ReleaseReviewStatus.PROVISIONAL,
            exact_reproduction_supported=False,
            semantic_replay_supported=True,
            limitations=(
                "Date-range and output-signature compatibility may support diagnostic "
                "replay but do not establish exact historical provenance.",
            ),
        ),
    ]
    return AnalyticalReleaseManifest(
        entries=tuple(entries),
        evidence=evidence,
        reviewed_at=ANALYTICAL_RELEASE_MANIFEST_REVIEWED_AT,
        reviewer="Project Alpha provenance audit",
    )


def reconstruct_historical_semantic_fingerprints() -> tuple[
    HistoricalFingerprintReconstruction, ...
]:
    current = _component_by_name(MARKET_CLASSIFIER_NAME)
    return (
        HistoricalFingerprintReconstruction(
            commit=_git("rev-parse", "HEAD"),
            component=MARKET_CLASSIFIER_NAME,
            reconstructed_analytical_version=MARKET_STATE_CLASSIFIER_VERSION,
            reconstructed_fingerprint=current.fingerprint,
            current_fingerprint=current.fingerprint,
            exact_match=True,
            semantic_match=True,
            reconstruction_confidence=EvidenceReliability.STRONG,
            missing_configuration=(),
        ),
    )


def assign_historical_candidate_eras(
    *,
    records: tuple[Any, ...],
    provenances: tuple[DecisionProvenance, ...],
    manifest: AnalyticalReleaseManifest,
) -> tuple[CandidateEraAssignment, ...]:
    provenance_by_id = {item.provenance_id: item for item in provenances}
    assignments = []
    for record in records:
        assignments.append(
            _assign_historical_candidate_era(
                record=record,
                provenance_by_id=provenance_by_id,
                manifest=manifest,
            )
        )
    return tuple(
        sorted(assignments, key=lambda item: (item.decision_date, item.candidate_id))
    )


def compatibility_for(
    *,
    persisted_version: str | None,
    current_version: str | None,
    persisted_fingerprint: str | None,
    current_fingerprint: str | None,
) -> ComponentCompatibility:
    if persisted_fingerprint and current_fingerprint:
        if persisted_fingerprint == current_fingerprint:
            return ComponentCompatibility.EXACT_FINGERPRINT_MATCH
    if persisted_version and current_version:
        if persisted_version == current_version:
            return ComponentCompatibility.EXACT_VERSION_MATCH
        return ComponentCompatibility.INCOMPATIBLE
    if not persisted_version:
        return ComponentCompatibility.VERSION_UNKNOWN
    return ComponentCompatibility.INSUFFICIENT_EVIDENCE


def render_current_provenance(provenance: DecisionProvenance) -> tuple[str, ...]:
    return (
        "Current Decision Provenance",
        f"Provenance ID: {provenance.provenance_id}",
        f"Application Version: {provenance.application_version}",
        f"Build Version: {_text(provenance.build_version)}",
        f"Git Commit: {_text(provenance.git_commit)}",
        f"Git Branch: {_text(provenance.git_branch)}",
        f"Working Tree: {provenance.working_tree_state.value}",
        f"Market Classifier Version: {provenance.market_classifier_version}",
        f"Market Classifier Fingerprint: {provenance.market_classifier_fingerprint}",
        f"Benchmark Builder Version: {provenance.benchmark_builder_version}",
        f"Recommendation Engine Version: {provenance.recommendation_engine_version}",
        f"Runtime Command: {_text(provenance.runtime_command)}",
        f"Runtime Mode: {_text(provenance.runtime_mode)}",
    )


def render_component_registry(
    components: tuple[ComponentVersion, ...],
) -> tuple[str, ...]:
    lines = ["Analytical Component Registry"]
    for component in components:
        lines.append(
            f"- {component.name}: version={component.analytical_version}, "
            f"fingerprint={component.fingerprint}"
        )
    return tuple(lines)


def render_provenance_history(rows: tuple[DecisionProvenance, ...]) -> tuple[str, ...]:
    lines = ["Decision Provenance History", f"Records: {len(rows)}"]
    for row in rows:
        lines.append(
            f"- {row.provenance_id}: classifier={row.market_classifier_version}, "
            f"fingerprint={row.market_classifier_fingerprint}, "
            f"created_at={row.created_at.isoformat()}"
        )
    return tuple(lines)


def render_provenance_coverage(
    *,
    records: tuple[Any, ...],
    snapshots: tuple[Any, ...],
    provenances: tuple[DecisionProvenance, ...],
) -> tuple[str, ...]:
    candidates_with = sum(
        1 for record in records if getattr(record, "decision_provenance_id", None)
    )
    snapshots_with = sum(
        1 for snapshot in snapshots if getattr(snapshot, "provenance_id", None)
    )
    return (
        "Decision Provenance Coverage",
        f"Provenance Records: {len(provenances)}",
        f"Candidate Records: {len(records)}",
        f"Candidates With Provenance: {candidates_with}",
        f"Candidates Missing Provenance: {len(records) - candidates_with}",
        f"Snapshots: {len(snapshots)}",
        f"Snapshots With Provenance: {snapshots_with}",
        f"Snapshots Missing Provenance: {len(snapshots) - snapshots_with}",
    )


def render_version_lineage_report(
    report: VersionLineageAuditReport,
    *,
    group_by: str | None = None,
) -> tuple[str, ...]:
    lines = [
        "Classifier Version Lineage Audit",
        f"Total Candidate Records: {report.total_candidate_records}",
        f"Exact Version Coverage: {report.exact_version_coverage}",
        f"Fingerprint Coverage: {report.fingerprint_coverage}",
        (
            "Semantically Compatible Coverage: "
            f"{report.semantically_compatible_coverage}"
        ),
        f"Forward-Compatible Only Coverage: {report.forward_compatible_only_coverage}",
        f"Unknown Version Coverage: {report.unknown_version_coverage}",
        f"Conflicting Evidence: {report.conflicting_evidence}",
        f"Backfill-Eligible Records: {report.backfill_eligible_records}",
        f"Diagnostic-Only Records: {report.diagnostic_only_records}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        (f"Secondary Conclusion: {_conclusion_text(report.secondary_conclusion)}"),
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        f"Explicitly Prohibited Next Action: {report.prohibited_next_action}",
    ]
    if group_by == "status":
        counts: dict[str, int] = {}
        for row in report.recoveries:
            counts[row.recovery_status.value] = (
                counts.get(row.recovery_status.value, 0) + 1
            )
        lines.append("")
        lines.append("By Recovery Status")
        lines.extend(f"- {key}: {value}" for key, value in sorted(counts.items()))
    return tuple(lines)


def render_version_evidence(
    sources: tuple[VersionEvidenceSource, ...],
) -> tuple[str, ...]:
    lines = ["Historical Version Evidence Inventory"]
    for source in sources:
        lines.append(
            f"- {source.source}: coverage={source.record_coverage}, "
            f"date_coverage={source.date_coverage}, "
            f"reliability={source.reliability.value}, "
            f"exact={source.exact_version_capability}, "
            f"compatibility_only={source.compatibility_only_capability}; "
            f"{source.limitations}"
        )
    return tuple(lines)


def render_version_compatibility(
    rows: tuple[CandidateVersionRecovery, ...],
) -> tuple[str, ...]:
    lines = ["Classifier Version Compatibility"]
    for row in rows[:200]:
        lines.append(
            f"- {row.candidate_id}: {row.compatibility_status.value}, "
            f"status={row.recovery_status.value}, "
            f"version={_text(row.persisted_version)}, "
            f"fingerprint={_text(row.recovered_fingerprint)}"
        )
    if len(rows) > 200:
        lines.append(f"- ... {len(rows) - 200} additional records omitted")
    return tuple(lines)


def render_backfill_version_eligibility(
    rows: tuple[HistoricalBackfillVersionEligibilityRow, ...],
) -> tuple[str, ...]:
    lines = ["Historical Backfill Version Eligibility"]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.eligibility.value] = counts.get(row.eligibility.value, 0) + 1
    lines.extend(f"- {key}: {value}" for key, value in sorted(counts.items()))
    return tuple(lines)


def render_version_drift(report: VersionDriftReport) -> tuple[str, ...]:
    lines = ["Analytical Version Drift", f"Conclusion: {report.conclusion.value}"]
    for row in report.rows:
        lines.append(
            f"- {row.component}: persisted={_text(row.persisted_version)}, "
            f"current={row.current_version}, compatibility={row.compatibility.value}, "
            f"affected_snapshots={row.affected_snapshots}, "
            f"affected_candidates={row.affected_candidates}"
        )
    return tuple(lines)


def render_historical_release_evidence(
    evidence: tuple[HistoricalEvidenceItem, ...],
) -> tuple[str, ...]:
    lines = ["Historical Release Evidence Inventory"]
    for item in evidence:
        lines.append(
            f"- {item.evidence_id}: type={item.evidence_type.value}, "
            f"reliability={item.reliability.value}, "
            f"record_exact={item.supports_exact_match}, "
            f"semantic={item.supports_semantic_compatibility}; "
            f"{item.observed_behavior}; limitation={item.limitations}"
        )
    return tuple(lines)


def render_historical_analytical_eras(
    eras: tuple[HistoricalAnalyticalEra, ...],
) -> tuple[str, ...]:
    lines = ["Historical Analytical Eras"]
    for era in eras:
        lines.append(
            f"- {era.era_id}: {era.name}; "
            f"from={_text(era.effective_from)}, to={_text(era.effective_to)}, "
            f"exact={era.exact_reproduction_supported}, "
            f"semantic={era.semantic_replay_supported}, "
            f"evidence={era.evidence_strength.value}, confidence={era.confidence}"
        )
    return tuple(lines)


def render_analytical_release_manifest(
    manifest: AnalyticalReleaseManifest,
) -> tuple[str, ...]:
    lines = [
        "Analytical Release Manifest",
        f"Entries: {len(manifest.entries)}",
        f"Reviewed At: {manifest.reviewed_at.isoformat()}",
        f"Reviewer: {manifest.reviewer}",
    ]
    for entry in manifest.entries:
        lines.append(
            f"- {entry.manifest_entry_id}: status={entry.review_status.value}, "
            f"classifier={_text(entry.classifier_version)}, "
            f"fingerprint={_text(entry.classifier_fingerprint)}, "
            f"exact={entry.exact_reproduction_supported}, "
            f"semantic={entry.semantic_replay_supported}, "
            f"confidence={entry.confidence}"
        )
    return tuple(lines)


def render_analytical_release_manifest_entry(
    entry: AnalyticalReleaseManifestEntry,
) -> tuple[str, ...]:
    return (
        "Analytical Release Manifest Entry",
        f"Entry ID: {entry.manifest_entry_id}",
        f"Release / Era: {entry.release_or_era}",
        f"Review Status: {entry.review_status.value}",
        f"Effective From: {_text(entry.effective_from)}",
        f"Effective To: {_text(entry.effective_to)}",
        f"Classifier Version: {_text(entry.classifier_version)}",
        f"Classifier Fingerprint: {_text(entry.classifier_fingerprint)}",
        f"Feature Definition Version: {_text(entry.feature_definition_version)}",
        f"Fallback Policy Version: {_text(entry.fallback_policy_version)}",
        f"Recommendation Policy Version: {_text(entry.recommendation_policy_version)}",
        f"Entry Timing Version: {_text(entry.entry_timing_version)}",
        f"Trade Plan Version: {_text(entry.trade_plan_version)}",
        f"Approval Policy Version: {_text(entry.approval_policy_version)}",
        f"Allocation Policy Version: {_text(entry.allocation_policy_version)}",
        f"Schema Signature: {_text(entry.schema_signature)}",
        f"Output Signature: {_text(entry.output_signature)}",
        f"Evidence Strength: {entry.evidence_strength.value}",
        f"Compatibility Policy: {entry.compatibility_policy.value}",
        f"Exact Reproduction Supported: {entry.exact_reproduction_supported}",
        f"Semantic Replay Supported: {entry.semantic_replay_supported}",
        f"Evidence Refs: {', '.join(entry.evidence_refs) or 'none'}",
        f"Limitations: {'; '.join(entry.limitations) or 'none'}",
    )


def render_manifest_validation(manifest: AnalyticalReleaseManifest) -> tuple[str, ...]:
    # Construction performs strict validation. If we have an object, it is valid.
    verified_exact = sum(
        1
        for entry in manifest.entries
        if entry.review_status is ReleaseReviewStatus.VERIFIED
        and entry.exact_reproduction_supported
    )
    return (
        "Analytical Release Manifest Validation",
        "Status: VALID",
        f"Entries: {len(manifest.entries)}",
        f"Evidence Items: {len(manifest.evidence)}",
        f"Verified Exact Entries: {verified_exact}",
        "No overlapping verified exact periods detected.",
        "No missing evidence references detected.",
        "Date-only and output-signature-only evidence remains non-exact.",
    )


def render_historical_manifest_coverage(
    report: HistoricalManifestAuditReport,
) -> tuple[str, ...]:
    lines = [
        "Historical Manifest Coverage",
        f"Candidate Records: {report.candidate_records}",
        f"Persisted Exact Coverage: {report.persisted_exact_records}",
        f"Verified Manifest Coverage: {report.verified_manifest_matched_records}",
        f"Supported Manifest Coverage: {report.supported_manifest_matched_records}",
        f"Semantic Compatibility Coverage: {report.semantic_compatible_records}",
        f"Diagnostic-Only Coverage: {report.diagnostic_only_records}",
        f"Unknown Coverage: {report.unknown_records}",
        f"Conflicting Evidence: {report.conflicting_records}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        (
            "Secondary Conclusion: "
            f"{_manifest_conclusion_text(report.secondary_conclusion)}"
        ),
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        (
            "Explicitly Prohibited Next Action: "
            f"{report.explicitly_prohibited_next_action}"
        ),
    ]
    lines.append("")
    lines.append("Coverage Attribution")
    lines.extend(
        f"- {row.layer}: incremental={row.incremental_records}, "
        f"cumulative={row.cumulative_records}, exact={row.exact_records}, "
        f"diagnostic={row.diagnostic_only_records}"
        for row in report.coverage_layers
    )
    return tuple(lines)


def render_historical_era_assignments(
    assignments: tuple[CandidateEraAssignment, ...],
    *,
    group_by: str | None = None,
) -> tuple[str, ...]:
    if group_by == "status":
        counts: dict[str, int] = {}
        for row in assignments:
            counts[row.assignment_status.value] = (
                counts.get(row.assignment_status.value, 0) + 1
            )
        return tuple(
            ["Historical Era Assignment By Status"]
            + [f"- {key}: {value}" for key, value in sorted(counts.items())]
        )
    lines = ["Historical Era Assignment"]
    for row in assignments[:200]:
        lines.append(
            f"- {row.candidate_id}: status={row.assignment_status.value}, "
            f"era={_text(row.assigned_era_id)}, "
            f"compatibility={row.compatibility_status.value}, "
            f"evidence={row.evidence_strength.value}, "
            f"blocking={_text(row.blocking_reason)}"
        )
    if len(assignments) > 200:
        lines.append(f"- ... {len(assignments) - 200} additional records omitted")
    return tuple(lines)


def render_historical_backfill_manifest_eligibility(
    rows: tuple[ManifestBackfillEligibilityRow, ...],
) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.eligibility.value] = counts.get(row.eligibility.value, 0) + 1
    lines = ["Historical Backfill Manifest Eligibility"]
    lines.extend(f"- {key}: {value}" for key, value in sorted(counts.items()))
    return tuple(lines)


def export_historical_manifest_report_json(
    report: HistoricalManifestAuditReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(report), indent=2), encoding="utf-8")
    return path


def export_historical_manifest_assignments_csv(
    report: HistoricalManifestAuditReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = (
            tuple(_jsonable(report.assignments[0]).keys())
            if report.assignments
            else ("candidate_id",)
        )
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in report.assignments:
            writer.writerow(_jsonable(row))
    return path


def export_version_lineage_json(report: VersionLineageAuditReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(report), indent=2), encoding="utf-8")
    return path


def export_version_lineage_csv(report: VersionLineageAuditReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = (
            tuple(_jsonable(report.recoveries[0]).keys())
            if report.recoveries
            else ("candidate_id",)
        )
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in report.recoveries:
            writer.writerow(_jsonable(row))
    return path


def resolve_decision_provenance_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("ALPHA_DECISION_PROVENANCE_LEDGER")
    if configured:
        return Path(configured)
    return DEFAULT_DECISION_PROVENANCE_PATH


def _component(
    name: str,
    analytical_version: str,
    config_version: str | None,
    payload: dict[str, str],
) -> ComponentVersion:
    normalized = tuple(sorted((str(key), str(value)) for key, value in payload.items()))
    fingerprint_payload = {
        "name": name,
        "analytical_version": analytical_version,
        "config_version": config_version,
        "payload": dict(normalized),
    }
    return ComponentVersion(
        name=name,
        analytical_version=analytical_version,
        config_version=config_version,
        fingerprint=_stable_id(fingerprint_payload),
        payload=normalized,
    )


def _component_by_name(name: str) -> ComponentVersion:
    return next(
        component
        for component in current_component_registry()
        if component.name == name
    )


def _recover_record(
    record: Any,
    provenance_by_id: dict[str, DecisionProvenance],
) -> CandidateVersionRecovery:
    provenance_id = getattr(record, "decision_provenance_id", None)
    provenance = (
        None if provenance_id is None else provenance_by_id.get(str(provenance_id))
    )
    persisted_version = getattr(record, "classifier_version", None)
    if provenance is not None:
        compatibility = compatibility_for(
            persisted_version=provenance.market_classifier_version,
            current_version=MARKET_STATE_CLASSIFIER_VERSION,
            persisted_fingerprint=provenance.market_classifier_fingerprint,
            current_fingerprint=current_market_classifier_fingerprint(),
        )
        return CandidateVersionRecovery(
            candidate_id=str(record.candidate_id),
            decision_date=record.evaluation_date,
            persisted_version=provenance.market_classifier_version,
            recovered_version=provenance.market_classifier_version,
            recovered_fingerprint=provenance.market_classifier_fingerprint,
            compatibility_status=compatibility,
            recovery_status=HistoricalVersionRecoveryStatus.PERSISTED_FINGERPRINT,
            evidence_sources=("decision_provenance",),
            evidence_strength=EvidenceReliability.AUTHORITATIVE,
            confidence="HIGH",
            blocking_reason=None,
        )
    if persisted_version:
        return CandidateVersionRecovery(
            candidate_id=str(record.candidate_id),
            decision_date=record.evaluation_date,
            persisted_version=str(persisted_version),
            recovered_version=str(persisted_version),
            recovered_fingerprint=None,
            compatibility_status=compatibility_for(
                persisted_version=str(persisted_version),
                current_version=MARKET_STATE_CLASSIFIER_VERSION,
                persisted_fingerprint=None,
                current_fingerprint=current_market_classifier_fingerprint(),
            ),
            recovery_status=HistoricalVersionRecoveryStatus.PERSISTED_EXACT,
            evidence_sources=("CandidateDecisionRecord.classifier_version",),
            evidence_strength=EvidenceReliability.STRONG,
            confidence="MEDIUM",
            blocking_reason=None,
        )
    return CandidateVersionRecovery(
        candidate_id=str(record.candidate_id),
        decision_date=record.evaluation_date,
        persisted_version=None,
        recovered_version=None,
        recovered_fingerprint=None,
        compatibility_status=ComponentCompatibility.VERSION_UNKNOWN,
        recovery_status=HistoricalVersionRecoveryStatus.VERSION_UNKNOWN,
        evidence_sources=(),
        evidence_strength=EvidenceReliability.UNUSABLE,
        confidence="LOW",
        blocking_reason="missing classifier-version and decision-provenance lineage",
    )


def _eligibility(
    row: CandidateVersionRecovery,
) -> HistoricalBackfillVersionEligibilityRow:
    if row.recovery_status is HistoricalVersionRecoveryStatus.PERSISTED_FINGERPRINT:
        eligibility = HistoricalBackfillVersionEligibility.ELIGIBLE_FINGERPRINT_MATCH
    elif row.recovery_status is HistoricalVersionRecoveryStatus.PERSISTED_EXACT:
        eligibility = HistoricalBackfillVersionEligibility.ELIGIBLE_EXACT
    elif row.compatibility_status in {
        ComponentCompatibility.SEMANTICALLY_COMPATIBLE,
        ComponentCompatibility.FORWARD_COMPATIBLE_FOR_REPLAY,
    }:
        eligibility = (
            HistoricalBackfillVersionEligibility.DIAGNOSTIC_RECONSTRUCTION_ONLY
        )
    elif row.recovery_status is HistoricalVersionRecoveryStatus.KNOWN_INCOMPATIBLE:
        eligibility = HistoricalBackfillVersionEligibility.BLOCKED_KNOWN_INCOMPATIBLE
    elif (
        row.recovery_status
        is HistoricalVersionRecoveryStatus.CONFLICTING_VERSION_EVIDENCE
    ):
        eligibility = HistoricalBackfillVersionEligibility.BLOCKED_VERSION_CONFLICT
    else:
        eligibility = HistoricalBackfillVersionEligibility.BLOCKED_VERSION_UNKNOWN
    return HistoricalBackfillVersionEligibilityRow(
        candidate_id=row.candidate_id,
        decision_date=row.decision_date,
        eligibility=eligibility,
        compatibility_status=row.compatibility_status,
        version_blocking_reason=row.blocking_reason,
    )


def _evidence_sources(
    records: tuple[Any, ...],
    snapshots: tuple[Any, ...],
    provenances: tuple[DecisionProvenance, ...],
) -> tuple[VersionEvidenceSource, ...]:
    dates = {record.evaluation_date for record in records}
    classifier_versions = sum(
        1 for record in records if getattr(record, "classifier_version", None)
    )
    candidate_provenance = sum(
        1 for record in records if getattr(record, "decision_provenance_id", None)
    )
    snapshot_provenance = sum(
        1 for snapshot in snapshots if getattr(snapshot, "provenance_id", None)
    )
    return (
        VersionEvidenceSource(
            source="CandidateDecisionRecord.classifier_version",
            record_coverage=classifier_versions,
            date_coverage=len(
                {
                    record.evaluation_date
                    for record in records
                    if getattr(record, "classifier_version", None)
                }
            ),
            reliability=EvidenceReliability.STRONG,
            granularity="candidate",
            point_in_time_validity=True,
            exact_version_capability=True,
            compatibility_only_capability=False,
            limitations="Only covers rows that persisted the classifier_version field.",
        ),
        VersionEvidenceSource(
            source="CandidateDecisionRecord.decision_provenance_id",
            record_coverage=candidate_provenance,
            date_coverage=len(
                {
                    record.evaluation_date
                    for record in records
                    if getattr(record, "decision_provenance_id", None)
                }
            ),
            reliability=EvidenceReliability.AUTHORITATIVE,
            granularity="runtime",
            point_in_time_validity=True,
            exact_version_capability=True,
            compatibility_only_capability=False,
            limitations=(
                "Available only for future records created after this milestone."
            ),
        ),
        VersionEvidenceSource(
            source="MarketStateSnapshot.provenance_id",
            record_coverage=snapshot_provenance,
            date_coverage=len(
                {
                    snapshot.market_date
                    for snapshot in snapshots
                    if getattr(snapshot, "provenance_id", None)
                }
            ),
            reliability=EvidenceReliability.AUTHORITATIVE,
            granularity="snapshot",
            point_in_time_validity=True,
            exact_version_capability=True,
            compatibility_only_capability=False,
            limitations="Legacy snapshots may not contain provenance_id.",
        ),
        VersionEvidenceSource(
            source="Application release metadata",
            record_coverage=0,
            date_coverage=len(dates),
            reliability=EvidenceReliability.SUPPORTING,
            granularity="release",
            point_in_time_validity=False,
            exact_version_capability=False,
            compatibility_only_capability=True,
            limitations=(
                "Documentation or package metadata alone is not record-level proof."
            ),
        ),
        VersionEvidenceSource(
            source="Decision provenance ledger",
            record_coverage=len(provenances),
            date_coverage=len({item.created_at.date() for item in provenances}),
            reliability=EvidenceReliability.AUTHORITATIVE,
            granularity="runtime",
            point_in_time_validity=True,
            exact_version_capability=True,
            compatibility_only_capability=False,
            limitations=(
                "Contains only runs captured after provenance persistence exists."
            ),
        ),
    )


def _assign_historical_candidate_era(
    *,
    record: Any,
    provenance_by_id: dict[str, DecisionProvenance],
    manifest: AnalyticalReleaseManifest,
) -> CandidateEraAssignment:
    provenance_id = getattr(record, "decision_provenance_id", None)
    provenance = (
        None if provenance_id is None else provenance_by_id.get(str(provenance_id))
    )
    persisted_version = _payload_optional_text(
        getattr(record, "classifier_version", None)
    )
    if provenance is not None:
        return CandidateEraAssignment(
            candidate_id=str(record.candidate_id),
            decision_date=record.evaluation_date,
            assigned_era_id="current-provenance-era",
            classifier_version=provenance.market_classifier_version,
            classifier_fingerprint=provenance.market_classifier_fingerprint,
            compatibility_status=compatibility_for(
                persisted_version=provenance.market_classifier_version,
                current_version=MARKET_STATE_CLASSIFIER_VERSION,
                persisted_fingerprint=provenance.market_classifier_fingerprint,
                current_fingerprint=current_market_classifier_fingerprint(),
            ),
            assignment_status=HistoricalEraAssignmentStatus.PERSISTED_EXACT_PROVENANCE,
            evidence_ids=(
                "candidate_decision_provenance_field",
                "decision_provenance_ledger",
            ),
            evidence_strength=EvidenceReliability.AUTHORITATIVE,
            confidence="HIGH",
            alternative_possible_eras=(),
            blocking_reason=None,
        )
    if provenance_id is not None:
        return CandidateEraAssignment(
            candidate_id=str(record.candidate_id),
            decision_date=record.evaluation_date,
            assigned_era_id=None,
            classifier_version=persisted_version,
            classifier_fingerprint=None,
            compatibility_status=ComponentCompatibility.INSUFFICIENT_EVIDENCE,
            assignment_status=HistoricalEraAssignmentStatus.CONFLICTING_EVIDENCE,
            evidence_ids=("candidate_decision_provenance_field",),
            evidence_strength=EvidenceReliability.WEAK,
            confidence="LOW",
            alternative_possible_eras=(),
            blocking_reason="candidate references missing decision provenance record",
        )
    if persisted_version:
        return CandidateEraAssignment(
            candidate_id=str(record.candidate_id),
            decision_date=record.evaluation_date,
            assigned_era_id=None,
            classifier_version=persisted_version,
            classifier_fingerprint=None,
            compatibility_status=compatibility_for(
                persisted_version=persisted_version,
                current_version=MARKET_STATE_CLASSIFIER_VERSION,
                persisted_fingerprint=None,
                current_fingerprint=current_market_classifier_fingerprint(),
            ),
            assignment_status=HistoricalEraAssignmentStatus.PERSISTED_EXACT_CLASSIFIER_VERSION,
            evidence_ids=("candidate_classifier_version_field",),
            evidence_strength=EvidenceReliability.STRONG,
            confidence="MEDIUM",
            alternative_possible_eras=(),
            blocking_reason=None,
        )
    exact_manifest = _matching_exact_manifest_entries(record, manifest)
    if len(exact_manifest) == 1:
        entry = exact_manifest[0]
        return CandidateEraAssignment(
            candidate_id=str(record.candidate_id),
            decision_date=record.evaluation_date,
            assigned_era_id=entry.manifest_entry_id,
            classifier_version=entry.classifier_version,
            classifier_fingerprint=entry.classifier_fingerprint,
            compatibility_status=entry.compatibility_policy,
            assignment_status=(
                HistoricalEraAssignmentStatus.MATCHED_VERIFIED_MANIFEST
                if entry.review_status is ReleaseReviewStatus.VERIFIED
                else HistoricalEraAssignmentStatus.MATCHED_SUPPORTED_MANIFEST
            ),
            evidence_ids=entry.evidence_refs,
            evidence_strength=entry.evidence_strength,
            confidence=entry.confidence,
            alternative_possible_eras=(),
            blocking_reason=None,
        )
    if len(exact_manifest) > 1:
        return CandidateEraAssignment(
            candidate_id=str(record.candidate_id),
            decision_date=record.evaluation_date,
            assigned_era_id=None,
            classifier_version=None,
            classifier_fingerprint=None,
            compatibility_status=ComponentCompatibility.INSUFFICIENT_EVIDENCE,
            assignment_status=HistoricalEraAssignmentStatus.MULTIPLE_POSSIBLE_ERAS,
            evidence_ids=tuple(
                sorted(
                    {
                        evidence
                        for entry in exact_manifest
                        for evidence in entry.evidence_refs
                    }
                )
            ),
            evidence_strength=EvidenceReliability.WEAK,
            confidence="LOW",
            alternative_possible_eras=tuple(
                sorted(entry.manifest_entry_id for entry in exact_manifest)
            ),
            blocking_reason="multiple manifest entries could apply",
        )
    if _has_candidate_output_signature(record):
        return CandidateEraAssignment(
            candidate_id=str(record.candidate_id),
            decision_date=record.evaluation_date,
            assigned_era_id="legacy-output-signature-diagnostic-era",
            classifier_version=None,
            classifier_fingerprint=None,
            compatibility_status=ComponentCompatibility.FORWARD_COMPATIBLE_FOR_REPLAY,
            assignment_status=HistoricalEraAssignmentStatus.OUTPUT_SIGNATURE_ONLY,
            evidence_ids=("candidate_output_signature",),
            evidence_strength=EvidenceReliability.WEAK,
            confidence="LOW",
            alternative_possible_eras=(),
            blocking_reason=(
                "output signature supports diagnostic replay only; exact lineage "
                "unknown"
            ),
        )
    return CandidateEraAssignment(
        candidate_id=str(record.candidate_id),
        decision_date=record.evaluation_date,
        assigned_era_id=None,
        classifier_version=None,
        classifier_fingerprint=None,
        compatibility_status=ComponentCompatibility.VERSION_UNKNOWN,
        assignment_status=HistoricalEraAssignmentStatus.UNKNOWN_ERA,
        evidence_ids=(),
        evidence_strength=EvidenceReliability.UNUSABLE,
        confidence="LOW",
        alternative_possible_eras=(),
        blocking_reason=(
            "missing exact provenance, classifier version, and usable signature"
        ),
    )


def _matching_exact_manifest_entries(
    record: Any,
    manifest: AnalyticalReleaseManifest,
) -> tuple[AnalyticalReleaseManifestEntry, ...]:
    # Date ranges alone are insufficient. Only entries with exact reproduction
    # support and authoritative evidence may participate, and persisted
    # provenance/classifier fields are handled before this function.
    decision_date = getattr(record, "evaluation_date", None)
    if not isinstance(decision_date, date):
        return ()
    matches = []
    for entry in manifest.entries:
        if not entry.exact_reproduction_supported:
            continue
        if entry.review_status not in {
            ReleaseReviewStatus.VERIFIED,
            ReleaseReviewStatus.SUPPORTED,
        }:
            continue
        if entry.effective_from is None or entry.effective_to is None:
            continue
        if not (entry.effective_from <= decision_date <= entry.effective_to):
            continue
        if "decision_provenance_ledger" not in entry.evidence_refs:
            continue
        # Without a record-level link, even a date match is not enough.
        if not getattr(record, "decision_provenance_id", None):
            continue
        matches.append(entry)
    return tuple(matches)


def _manifest_eligibility(
    row: CandidateEraAssignment,
) -> ManifestBackfillEligibilityRow:
    if (
        row.assignment_status
        is HistoricalEraAssignmentStatus.PERSISTED_EXACT_PROVENANCE
    ):
        eligibility = ManifestBackfillEligibility.ELIGIBLE_EXACT_FINGERPRINT
    elif (
        row.assignment_status
        is HistoricalEraAssignmentStatus.PERSISTED_EXACT_CLASSIFIER_VERSION
    ):
        eligibility = ManifestBackfillEligibility.ELIGIBLE_PERSISTED_EXACT
    elif (
        row.assignment_status is HistoricalEraAssignmentStatus.MATCHED_VERIFIED_MANIFEST
    ):
        eligibility = ManifestBackfillEligibility.ELIGIBLE_VERIFIED_MANIFEST
    elif (
        row.assignment_status
        is HistoricalEraAssignmentStatus.MATCHED_SUPPORTED_MANIFEST
    ):
        eligibility = ManifestBackfillEligibility.ELIGIBLE_SUPPORTED_SEMANTIC
    elif row.assignment_status is HistoricalEraAssignmentStatus.OUTPUT_SIGNATURE_ONLY:
        eligibility = ManifestBackfillEligibility.BLOCKED_OUTPUT_SIGNATURE_ONLY
    elif row.assignment_status is HistoricalEraAssignmentStatus.DATE_RANGE_ONLY:
        eligibility = ManifestBackfillEligibility.BLOCKED_DATE_ONLY
    elif row.assignment_status is HistoricalEraAssignmentStatus.MULTIPLE_POSSIBLE_ERAS:
        eligibility = ManifestBackfillEligibility.BLOCKED_MULTIPLE_POSSIBLE_ERAS
    elif row.assignment_status is HistoricalEraAssignmentStatus.CONFLICTING_EVIDENCE:
        eligibility = ManifestBackfillEligibility.BLOCKED_CONFLICTING_EVIDENCE
    elif row.assignment_status is HistoricalEraAssignmentStatus.KNOWN_INCOMPATIBLE_ERA:
        eligibility = ManifestBackfillEligibility.BLOCKED_KNOWN_INCOMPATIBLE
    else:
        eligibility = ManifestBackfillEligibility.BLOCKED_UNKNOWN_ERA
    return ManifestBackfillEligibilityRow(
        candidate_id=row.candidate_id,
        decision_date=row.decision_date,
        eligibility=eligibility,
        market_source_readiness="not evaluated in manifest audit",
        classifier_readiness=row.assignment_status.value,
        authoritative_eligibility=eligibility
        in {
            ManifestBackfillEligibility.ELIGIBLE_PERSISTED_EXACT,
            ManifestBackfillEligibility.ELIGIBLE_EXACT_FINGERPRINT,
            ManifestBackfillEligibility.ELIGIBLE_VERIFIED_MANIFEST,
        },
        blocking_reason=row.blocking_reason,
    )


def _manifest_coverage_layers(
    assignments: tuple[CandidateEraAssignment, ...],
) -> tuple[ManifestCoverageLayer, ...]:
    layers = (
        (
            "persisted version fields",
            {
                HistoricalEraAssignmentStatus.PERSISTED_EXACT_CLASSIFIER_VERSION,
            },
        ),
        (
            "persisted fingerprints",
            {
                HistoricalEraAssignmentStatus.PERSISTED_EXACT_PROVENANCE,
            },
        ),
        (
            "verified manifest",
            {
                HistoricalEraAssignmentStatus.MATCHED_VERIFIED_MANIFEST,
            },
        ),
        (
            "supported manifest",
            {
                HistoricalEraAssignmentStatus.MATCHED_SUPPORTED_MANIFEST,
            },
        ),
        (
            "output signature",
            {
                HistoricalEraAssignmentStatus.OUTPUT_SIGNATURE_ONLY,
            },
        ),
        (
            "unknown",
            {
                HistoricalEraAssignmentStatus.UNKNOWN_ERA,
                HistoricalEraAssignmentStatus.MULTIPLE_POSSIBLE_ERAS,
                HistoricalEraAssignmentStatus.CONFLICTING_EVIDENCE,
            },
        ),
    )
    cumulative = 0
    rows = []
    counted: set[str] = set()
    for layer, statuses in layers:
        matching = tuple(
            row
            for row in assignments
            if row.assignment_status in statuses and row.candidate_id not in counted
        )
        for row in matching:
            counted.add(row.candidate_id)
        cumulative += len(matching)
        rows.append(
            ManifestCoverageLayer(
                layer=layer,
                incremental_records=len(matching),
                cumulative_records=cumulative,
                exact_records=sum(
                    1
                    for row in matching
                    if row.assignment_status
                    in {
                        HistoricalEraAssignmentStatus.PERSISTED_EXACT_PROVENANCE,
                        HistoricalEraAssignmentStatus.PERSISTED_EXACT_CLASSIFIER_VERSION,
                        HistoricalEraAssignmentStatus.MATCHED_VERIFIED_MANIFEST,
                    }
                ),
                diagnostic_only_records=sum(
                    1
                    for row in matching
                    if row.assignment_status
                    is HistoricalEraAssignmentStatus.OUTPUT_SIGNATURE_ONLY
                ),
            )
        )
    return tuple(rows)


def _manifest_conclusions(
    *,
    candidate_records: int,
    persisted_exact: int,
    verified_matches: int,
    supported_matches: int,
    diagnostic: int,
    unknown: int,
    conflicting: int,
    eligible_exact: int,
    eligible_verified: int,
    eligible_semantic: int,
) -> tuple[
    HistoricalManifestConclusion,
    HistoricalManifestConclusion | None,
    HistoricalManifestNextMilestone,
]:
    if conflicting:
        return (
            HistoricalManifestConclusion.CONFLICTING_HISTORICAL_EVIDENCE_IS_PRIMARY_BOTTLENECK,
            None,
            HistoricalManifestNextMilestone.REPAIR_CONFLICTING_HISTORICAL_EVIDENCE,
        )
    if not candidate_records:
        return (
            HistoricalManifestConclusion.INSUFFICIENT_EVIDENCE_FOR_HISTORICAL_MANIFEST,
            None,
            HistoricalManifestNextMilestone.COLLECT_EXTERNAL_DEPLOYMENT_EVIDENCE,
        )
    authoritative = persisted_exact + verified_matches
    if (
        authoritative == candidate_records
        and eligible_exact + eligible_verified == candidate_records
    ):
        return (
            HistoricalManifestConclusion.HISTORICAL_VERSION_LINEAGE_IS_SUFFICIENT_FOR_BACKFILL,
            HistoricalManifestConclusion.HISTORICAL_RELEASE_MANIFEST_RECOVERS_EXACT_LINEAGE,
            HistoricalManifestNextMilestone.EXECUTE_VERSION_SAFE_MARKET_STATE_BACKFILL,
        )
    if verified_matches or supported_matches:
        return (
            HistoricalManifestConclusion.HISTORICAL_RELEASE_MANIFEST_RECOVERS_PARTIAL_LINEAGE,
            HistoricalManifestConclusion.DEPLOYMENT_HISTORY_IS_PRIMARY_BOTTLENECK
            if unknown
            else None,
            HistoricalManifestNextMilestone.COLLECT_EXTERNAL_DEPLOYMENT_EVIDENCE,
        )
    if diagnostic and diagnostic >= unknown:
        return (
            HistoricalManifestConclusion.GIT_HISTORY_SUPPORTS_SEMANTIC_COMPATIBILITY_ONLY,
            HistoricalManifestConclusion.DEPLOYMENT_HISTORY_IS_PRIMARY_BOTTLENECK,
            HistoricalManifestNextMilestone.DESIGN_DIAGNOSTIC_ONLY_MARKET_STATE_BACKFILL,
        )
    if eligible_semantic and not eligible_verified:
        return (
            HistoricalManifestConclusion.GIT_HISTORY_SUPPORTS_SEMANTIC_COMPATIBILITY_ONLY,
            None,
            HistoricalManifestNextMilestone.ACCEPT_LEGACY_HISTORY_AS_DIAGNOSTIC_ONLY,
        )
    return (
        HistoricalManifestConclusion.MOST_LEGACY_HISTORY_REMAINS_UNKNOWN,
        HistoricalManifestConclusion.DEPLOYMENT_HISTORY_IS_PRIMARY_BOTTLENECK,
        HistoricalManifestNextMilestone.ADD_DEPLOYMENT_RELEASE_TRACKING,
    )


def _validate_eras(eras: tuple[HistoricalAnalyticalEra, ...]) -> None:
    exact = tuple(
        era
        for era in eras
        if era.exact_reproduction_supported
        and era.effective_from is not None
        and era.effective_to is not None
    )
    for index, left in enumerate(exact):
        for right in exact[index + 1 :]:
            left_from = left.effective_from
            left_to = left.effective_to
            right_from = right.effective_from
            right_to = right.effective_to
            if left_from is None or left_to is None:
                continue
            if right_from is None or right_to is None:
                continue
            if left_from <= right_to and right_from <= left_to:
                raise ValueError("overlapping exact analytical eras")


def _has_candidate_output_signature(record: Any) -> bool:
    required = (
        "final_verdict",
        "capital_action",
        "strategy_score",
        "entry_zone_low",
        "confirmation_entry",
        "risk_stop",
        "target_1",
    )
    return all(hasattr(record, field_name) for field_name in required)


def _date_range(values: tuple[date, ...]) -> str | None:
    if not values:
        return None
    return f"{min(values).isoformat()}..{max(values).isoformat()}"


def _git_count(*args: str) -> int:
    value = _git(*args)
    if value is None:
        return 0
    if len(args) >= 2 and args[0] == "rev-list" and args[1] == "--count":
        try:
            return int(value)
        except ValueError:
            return 0
    return len([line for line in value.splitlines() if line.strip()])


def _path_count(paths: tuple[str, ...]) -> int:
    count = 0
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            count += 1
        elif path.is_dir():
            count += sum(1 for child in path.rglob("*") if child.is_file())
    return count


def _conclusion_text(value: VersionLineageConclusion | None) -> str:
    return "none" if value is None else value.value


def _manifest_conclusion_text(value: HistoricalManifestConclusion | None) -> str:
    return "none" if value is None else value.value


def _git_metadata() -> dict[str, str | WorkingTreeState | None]:
    commit = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    status = _git("status", "--porcelain")
    if status is None:
        tree = WorkingTreeState.UNAVAILABLE
    elif status.strip():
        tree = WorkingTreeState.DIRTY
    else:
        tree = WorkingTreeState.CLEAN
    return {"commit": commit, "branch": branch, "working_tree_state": tree}


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ("git", *args),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _stable_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def _clean_commit(value: str | None) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    if len(text) < 7 or len(text) > 64:
        return None
    if not all(character in "0123456789abcdefABCDEF" for character in text):
        return None
    return text.lower()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _payload_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _text(value: object | None) -> str:
    return "unavailable" if value is None else str(value)


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
    "ALLOCATION_POLICY_VERSION",
    "APPROVAL_POLICY_VERSION",
    "AnalyticalChangeImpact",
    "AnalyticalReleaseManifest",
    "AnalyticalReleaseManifestEntry",
    "BENCHMARK_BUILDER_VERSION",
    "ComponentCompatibility",
    "ComponentVersion",
    "DecisionProvenance",
    "DecisionProvenanceRepository",
    "ENTRY_TIMING_ENGINE_VERSION",
    "EvidenceReliability",
    "HistoricalAnalyticalEra",
    "HistoricalBackfillVersionEligibility",
    "HistoricalEraAssignmentStatus",
    "HistoricalEvidenceItem",
    "HistoricalEvidenceType",
    "HistoricalManifestAuditReport",
    "HistoricalManifestConclusion",
    "HistoricalManifestNextMilestone",
    "MARKET_CLASSIFIER_CONFIG_VERSION",
    "MARKET_CLASSIFIER_NAME",
    "MARKET_FALLBACK_POLICY_VERSION",
    "MARKET_FEATURE_DEFINITION_VERSION",
    "MARKET_INTELLIGENCE_ENGINE_VERSION",
    "ManifestBackfillEligibility",
    "RECOMMENDATION_ENGINE_VERSION",
    "RECOMMENDATION_POLICY_VERSION",
    "ReleaseReviewStatus",
    "TRADE_PLAN_ENGINE_VERSION",
    "VersionLineageConclusion",
    "VersionLineageNextMilestone",
    "WorkingTreeState",
    "assign_historical_candidate_eras",
    "build_current_analytical_release_manifest",
    "build_historical_analytical_eras",
    "build_historical_evidence_inventory",
    "build_historical_manifest_audit",
    "build_version_drift_report",
    "build_version_lineage_audit",
    "capture_current_provenance",
    "compatibility_for",
    "current_component_registry",
    "current_market_classifier_fingerprint",
    "detect_analytical_change_points",
    "export_historical_manifest_assignments_csv",
    "export_historical_manifest_report_json",
    "export_version_lineage_csv",
    "export_version_lineage_json",
    "reconstruct_historical_semantic_fingerprints",
    "render_backfill_version_eligibility",
    "render_analytical_release_manifest",
    "render_analytical_release_manifest_entry",
    "render_component_registry",
    "render_current_provenance",
    "render_historical_analytical_eras",
    "render_historical_backfill_manifest_eligibility",
    "render_historical_era_assignments",
    "render_historical_manifest_coverage",
    "render_historical_release_evidence",
    "render_manifest_validation",
    "render_provenance_coverage",
    "render_provenance_history",
    "render_version_compatibility",
    "render_version_drift",
    "render_version_evidence",
    "render_version_lineage_report",
    "resolve_decision_provenance_path",
]
