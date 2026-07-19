from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpha.historical_replay.breakout_source_gap_service import (
    build_project_breakout_source_gap_audit,
)
from alpha.historical_replay.historical_source_evaluation import (
    HistoricalSourceEvaluationManifest,
    HistoricalSourceEvaluationManifestRecord,
)
from alpha.historical_replay.historical_source_evaluation_service import (
    build_project_historical_source_evaluation,
)
from alpha.historical_replay.upstox_historical_probe import (
    PRODUCTION_INFLUENCE,
    UpstoxHistoricalCandidateEvidence,
    UpstoxHistoricalEvidenceDataset,
    UpstoxHistoricalEvidenceRepository,
    UpstoxIdentityStatus,
)
from alpha.market_intelligence.point_in_time_store import (
    PointInTimeAnalyticalRepository,
)

HISTORICAL_IDENTITY_BRIDGE_VERSION = "historical-identity-bridge-v1"
HISTORICAL_IDENTITY_EVIDENCE_VERSION = "historical-identity-evidence-v1"
DEFAULT_HISTORICAL_IDENTITY_EVIDENCE_PATH = Path(
    ".alpha/historical_identity_evidence_v1.json"
)


class HistoricalIdentityStatus(StrEnum):
    AUTHORITATIVE_PERMANENT_ID_MATCH = "AUTHORITATIVE_PERMANENT_ID_MATCH"
    AUTHORITATIVE_ISIN_INTERVAL_MATCH = "AUTHORITATIVE_ISIN_INTERVAL_MATCH"
    AUTHORITATIVE_HISTORICAL_SYMBOL_INTERVAL_MATCH = (
        "AUTHORITATIVE_HISTORICAL_SYMBOL_INTERVAL_MATCH"
    )
    AUTHORITATIVE_RENAME_CHAIN_MATCH = "AUTHORITATIVE_RENAME_CHAIN_MATCH"
    AUTHORITATIVE_SUCCESSOR_PREDECESSOR_MATCH = (
        "AUTHORITATIVE_SUCCESSOR_PREDECESSOR_MATCH"
    )
    PROVISIONAL_PROVIDER_SYMBOL_MATCH = "PROVISIONAL_PROVIDER_SYMBOL_MATCH"
    CURRENT_SYMBOL_ONLY_UNPROVEN = "CURRENT_SYMBOL_ONLY_UNPROVEN"
    SYMBOL_REUSE_AMBIGUITY = "SYMBOL_REUSE_AMBIGUITY"
    SERIES_MIGRATION_AMBIGUITY = "SERIES_MIGRATION_AMBIGUITY"
    MERGER_OR_DEMERGER_AMBIGUITY = "MERGER_OR_DEMERGER_AMBIGUITY"
    LISTING_INTERVAL_CONFLICT = "LISTING_INTERVAL_CONFLICT"
    DELISTING_INTERVAL_CONFLICT = "DELISTING_INTERVAL_CONFLICT"
    ISIN_CONFLICT = "ISIN_CONFLICT"
    MULTIPLE_INSTRUMENT_MATCHES = "MULTIPLE_INSTRUMENT_MATCHES"
    INSTRUMENT_NOT_FOUND = "INSTRUMENT_NOT_FOUND"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"


class IdentityMatchMethod(StrEnum):
    PERMANENT_EXCHANGE_IDENTIFIER = "PERMANENT_EXCHANGE_IDENTIFIER"
    ISIN_EFFECTIVE_INTERVAL = "ISIN_EFFECTIVE_INTERVAL"
    HISTORICAL_SYMBOL_EXCHANGE_SERIES_INTERVAL = (
        "HISTORICAL_SYMBOL_EXCHANGE_SERIES_INTERVAL"
    )
    RENAME_CHAIN = "RENAME_CHAIN"
    SUCCESSOR_PREDECESSOR_CHAIN = "SUCCESSOR_PREDECESSOR_CHAIN"
    PROVIDER_INSTRUMENT_BRIDGE = "PROVIDER_INSTRUMENT_BRIDGE"
    PROVIDER_SYMBOL_ONLY = "PROVIDER_SYMBOL_ONLY"
    NONE = "NONE"


class IdentityEvidenceConfidence(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    PROVISIONAL = "PROVISIONAL"
    CONFLICTED = "CONFLICTED"
    INSUFFICIENT = "INSUFFICIENT"


class IdentityProvenanceCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class IdentitySourceAuthority(StrEnum):
    OFFICIAL_EXCHANGE = "OFFICIAL_EXCHANGE"
    LICENSED_SECURITY_MASTER = "LICENSED_SECURITY_MASTER"
    AUTHORIZED_VENDOR = "AUTHORIZED_VENDOR"
    AUTHORITATIVE_REPOSITORY = "AUTHORITATIVE_REPOSITORY"
    PROVIDER_PROVISIONAL = "PROVIDER_PROVISIONAL"
    INTERNAL_DIAGNOSTIC = "INTERNAL_DIAGNOSTIC"

    @property
    def authoritative(self) -> bool:
        return self in {
            IdentitySourceAuthority.OFFICIAL_EXCHANGE,
            IdentitySourceAuthority.LICENSED_SECURITY_MASTER,
            IdentitySourceAuthority.AUTHORIZED_VENDOR,
            IdentitySourceAuthority.AUTHORITATIVE_REPOSITORY,
        }


class ProvisionalMatchClassification(StrEnum):
    LIKELY_CORRECT_BUT_UNAUTHORITATIVE = "LIKELY_CORRECT_BUT_UNAUTHORITATIVE"
    AMBIGUOUS = "AMBIGUOUS"
    CONTRADICTED = "CONTRADICTED"
    READY_IF_AUTHORITY_SUPPLIED = "READY_IF_AUTHORITY_SUPPLIED"


class UnresolvedIdentityCause(StrEnum):
    HISTORICAL_SYMBOL_NO_LONGER_ACTIVE = "HISTORICAL_SYMBOL_NO_LONGER_ACTIVE"
    KNOWN_RENAME = "KNOWN_RENAME"
    KNOWN_MERGER = "KNOWN_MERGER"
    KNOWN_DEMERGER = "KNOWN_DEMERGER"
    SYMBOL_REUSED = "SYMBOL_REUSED"
    SERIES_CHANGED = "SERIES_CHANGED"
    DELISTED = "DELISTED"
    SUSPENDED = "SUSPENDED"
    PROVIDER_DOES_NOT_INDEX_INACTIVE_SECURITY = (
        "PROVIDER_DOES_NOT_INDEX_INACTIVE_SECURITY"
    )
    MANIFEST_MISSING_ISIN = "MANIFEST_MISSING_ISIN"
    MANIFEST_MISSING_EXCHANGE_SERIES = "MANIFEST_MISSING_EXCHANGE_SERIES"
    PROVIDER_SEARCH_FAILURE = "PROVIDER_SEARCH_FAILURE"
    AMBIGUOUS_MULTIPLE_MATCH = "AMBIGUOUS_MULTIPLE_MATCH"
    NO_EVIDENCE_SOURCE_AVAILABLE = "NO_EVIDENCE_SOURCE_AVAILABLE"
    UNKNOWN = "UNKNOWN"


class IdentityAuditConclusion(StrEnum):
    EXISTING_IDENTITY_EVIDENCE_SUFFICIENT = "EXISTING_IDENTITY_EVIDENCE_SUFFICIENT"
    EXISTING_IDENTITY_EVIDENCE_PARTIALLY_SUFFICIENT = (
        "EXISTING_IDENTITY_EVIDENCE_PARTIALLY_SUFFICIENT"
    )
    AUTHORITATIVE_EXTERNAL_IDENTITY_SOURCE_REQUIRED = (
        "AUTHORITATIVE_EXTERNAL_IDENTITY_SOURCE_REQUIRED"
    )
    ISIN_ENRICHMENT_REQUIRED = "ISIN_ENRICHMENT_REQUIRED"
    HISTORICAL_SYMBOL_CHAIN_REQUIRED = "HISTORICAL_SYMBOL_CHAIN_REQUIRED"
    MANUAL_IDENTITY_ADJUDICATION_REQUIRED = "MANUAL_IDENTITY_ADJUDICATION_REQUIRED"


class DuplicateOriginClassification(StrEnum):
    EXACT_DUPLICATE_PROVIDER_ROW = "EXACT_DUPLICATE_PROVIDER_ROW"
    CONFLICTING_DUPLICATE_PROVIDER_ROW = "CONFLICTING_DUPLICATE_PROVIDER_ROW"
    REQUEST_WINDOW_OVERLAP = "REQUEST_WINDOW_OVERLAP"
    RESUME_MERGE_DUPLICATE = "RESUME_MERGE_DUPLICATE"
    NORMALIZATION_DUPLICATE = "NORMALIZATION_DUPLICATE"
    UNKNOWN_DUPLICATE_ORIGIN = "UNKNOWN_DUPLICATE_ORIGIN"


@dataclass(frozen=True, slots=True)
class HistoricalIdentitySourceRecord:
    permanent_identifier: str
    historical_symbol: str
    exchange: str
    series: str | None
    isin: str | None
    provider_instrument_key: str | None
    source: str
    source_version: str
    source_authority: IdentitySourceAuthority
    effective_from: date | None
    effective_to: date | None
    listing_date: date | None = None
    delisting_date: date | None = None
    current_symbol: str | None = None
    predecessor_identifier: str | None = None
    successor_identifier: str | None = None
    rename_event: str | None = None
    series_migration_event: str | None = None
    merger_or_demerger_event: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "historical_symbol", self.historical_symbol.upper())
        object.__setattr__(self, "exchange", self.exchange.upper())
        if self.series is not None:
            object.__setattr__(self, "series", self.series.upper())
        if self.isin is not None:
            object.__setattr__(self, "isin", self.isin.upper())
        if self.current_symbol is not None:
            object.__setattr__(self, "current_symbol", self.current_symbol.upper())

    @property
    def authoritative(self) -> bool:
        return self.source_authority.authoritative

    def covers(self, value: date) -> bool:
        return (self.effective_from is None or value >= self.effective_from) and (
            self.effective_to is None or value <= self.effective_to
        )


@dataclass(frozen=True, slots=True)
class HistoricalIdentityEvidenceDataset:
    dataset_version: str
    authorized_for_diagnostic_use: bool
    records: tuple[HistoricalIdentitySourceRecord, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class EffectiveDatedIdentityRecord:
    candidate_id: str
    candidate_date: date
    historical_symbol: str
    exchange: str
    historical_series: str | None
    provider_symbol: str | None
    provider_instrument_key: str | None
    provider_isin: str | None
    repository_isin: str | None
    authoritative_permanent_identifier: str | None
    manifest_internal_identifier: str | None
    identity_source: str
    identity_source_version: str | None
    effective_from: date | None
    effective_to: date | None
    listing_date: date | None
    delisting_date: date | None
    predecessor_identifier: str | None
    successor_identifier: str | None
    rename_event: str | None
    series_migration_event: str | None
    merger_or_demerger_event: str | None
    match_method: IdentityMatchMethod
    evidence_confidence: IdentityEvidenceConfidence
    ambiguity_reasons: tuple[str, ...]
    provenance_completeness: IdentityProvenanceCompleteness
    final_identity_status: HistoricalIdentityStatus
    provisional_classification: ProvisionalMatchClassification | None
    unresolved_cause: UnresolvedIdentityCause | None
    full_price_coverage: bool
    corporate_action_required: bool
    inactive: bool
    renamed: bool
    production_influence: bool = PRODUCTION_INFLUENCE

    @property
    def authoritative(self) -> bool:
        return self.final_identity_status in _AUTHORITATIVE_STATUSES


@dataclass(frozen=True, slots=True)
class UnresolvedIdentityCluster:
    cause: UnresolvedIdentityCause
    candidate_count: int
    unique_symbol_count: int
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IdentitySourceCoverage:
    source: str
    source_version: str
    authority: IdentitySourceAuthority
    records: int
    fields_available: tuple[str, ...]
    fields_missing: tuple[str, ...]
    candidate_matches: int
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HistoricalIdentityBridgeReport:
    report_version: str
    total_candidates: int
    historical_symbols: int
    provisional_upstox_matches: int
    unresolved_candidates: int
    unresolved_unique_symbols: int
    authoritative_identities: int
    authoritative_by_permanent_identifier: int
    authoritative_by_isin: int
    authoritative_by_historical_symbol_interval: int
    authoritative_by_rename_chain: int
    authoritative_by_successor_predecessor: int
    symbol_reuse_ambiguities: int
    listing_conflicts: int
    delisting_conflicts: int
    missing_isin_count: int
    missing_series_count: int
    candidates_bridgeable_with_existing_evidence: int
    candidates_requiring_external_identity_source: int
    candidates_requiring_manual_adjudication: int
    identity_only_resolved_candidates: int
    identity_plus_corporate_action_ready_candidates: int
    identity_resolved_corporate_action_blocked_candidates: int
    full_price_covered_identity_blocked_candidates: int
    full_price_covered_corporate_action_blocked_candidates: int
    projected_readiness_with_existing_evidence: int
    projected_readiness_if_authority_supplied: int
    actual_authoritative_readiness: int
    unresolved_clusters: tuple[UnresolvedIdentityCluster, ...]
    source_coverage: tuple[IdentitySourceCoverage, ...]
    records: tuple[EffectiveDatedIdentityRecord, ...]
    conclusion: IdentityAuditConclusion
    limitations: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class UpstoxIdentityMetadataAudit:
    observed_candidates: int
    provisional_matches: int
    unresolved_candidates: int
    retained_field_counts: tuple[tuple[str, int], ...]
    parser_fields_available: tuple[str, ...]
    candidate_fields_persisted: tuple[str, ...]
    fields_previously_discarded_from_candidate_evidence: tuple[str, ...]
    fields_not_proven_returned: tuple[str, ...]
    secret_fields_persisted: tuple[str, ...]
    account_fields_persisted: tuple[str, ...]
    provenance_conclusion: str
    rerun_required: bool
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class DuplicateSessionObservation:
    candidate_id: str
    symbol: str
    session_date: date
    ohlcv_fingerprint: str
    provider_row_fingerprint: str | None = None
    request_id: str | None = None
    request_window: str | None = None
    normalization_stage: str | None = None
    resume_generation: int | None = None


@dataclass(frozen=True, slots=True)
class DuplicateOriginAttribution:
    candidate_id: str
    symbol: str
    duplicated_date: date | None
    duplicate_rows: int
    exact_ohlcv: bool | None
    cross_symbol_same_session: bool | None
    origin: DuplicateOriginClassification
    explanation: str


@dataclass(frozen=True, slots=True)
class UpstoxDuplicateOriginAudit:
    duplicate_session_candidates: int
    duplicate_sessions_reported: int
    attributions: tuple[DuplicateOriginAttribution, ...]
    origin_distribution: tuple[tuple[str, int], ...]
    duplicated_dates_available: int
    exactness_available: int
    cross_symbol_pattern_available: bool
    future_safe_deduplication_supportable: bool
    conclusion: str
    required_missing_evidence: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class HistoricalIdentityAuditBundle:
    bridge: HistoricalIdentityBridgeReport
    metadata: UpstoxIdentityMetadataAudit
    duplicates: UpstoxDuplicateOriginAudit


_AUTHORITATIVE_STATUSES = {
    HistoricalIdentityStatus.AUTHORITATIVE_PERMANENT_ID_MATCH,
    HistoricalIdentityStatus.AUTHORITATIVE_ISIN_INTERVAL_MATCH,
    HistoricalIdentityStatus.AUTHORITATIVE_HISTORICAL_SYMBOL_INTERVAL_MATCH,
    HistoricalIdentityStatus.AUTHORITATIVE_RENAME_CHAIN_MATCH,
    HistoricalIdentityStatus.AUTHORITATIVE_SUCCESSOR_PREDECESSOR_MATCH,
}


class HistoricalIdentityEvidenceRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        configured = os.environ.get("ALPHA_HISTORICAL_IDENTITY_EVIDENCE_PATH")
        self.path = Path(
            path or configured or DEFAULT_HISTORICAL_IDENTITY_EVIDENCE_PATH
        )

    def load(self) -> HistoricalIdentityEvidenceDataset:
        if not self.path.exists():
            return HistoricalIdentityEvidenceDataset(
                dataset_version=HISTORICAL_IDENTITY_EVIDENCE_VERSION,
                authorized_for_diagnostic_use=False,
                records=(),
            )
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("historical identity evidence must be a JSON object")
        authorized = bool(payload.get("authorized_for_diagnostic_use", False))
        raw_records = payload.get("records", [])
        if not isinstance(raw_records, list):
            raise ValueError("historical identity evidence records must be a list")
        records = tuple(
            _source_record_from_payload(item)
            for item in raw_records
            if isinstance(item, dict)
        )
        if records and not authorized:
            raise ValueError(
                "identity evidence package is not authorized for diagnostic use"
            )
        return HistoricalIdentityEvidenceDataset(
            dataset_version=str(
                payload.get("dataset_version", HISTORICAL_IDENTITY_EVIDENCE_VERSION)
            ),
            authorized_for_diagnostic_use=authorized,
            records=records,
        )


class HistoricalIdentityBridgeEngine:
    def build(
        self,
        *,
        manifest: HistoricalSourceEvaluationManifest,
        upstox_dataset: UpstoxHistoricalEvidenceDataset | None,
        identity_dataset: HistoricalIdentityEvidenceDataset,
        source_coverage: Sequence[IdentitySourceCoverage] = (),
        actual_authoritative_readiness: int = 0,
    ) -> HistoricalIdentityBridgeReport:
        evidence_index = {
            item.candidate_id: item
            for item in (upstox_dataset.records if upstox_dataset else ())
        }
        sources = (
            identity_dataset.records
            if identity_dataset.authorized_for_diagnostic_use
            else ()
        )
        records = tuple(
            self.resolve_candidate(
                candidate,
                provider=evidence_index.get(candidate.candidate_id),
                sources=sources,
            )
            for candidate in sorted(
                manifest.records,
                key=lambda item: (item.candidate_date, item.candidate_id),
            )
        )
        authoritative = tuple(item for item in records if item.authoritative)
        provisional = tuple(
            item
            for item in records
            if item.final_identity_status
            is HistoricalIdentityStatus.PROVISIONAL_PROVIDER_SYMBOL_MATCH
        )
        unresolved = tuple(
            item
            for item in records
            if not item.authoritative and item not in provisional
        )
        clusters = _unresolved_clusters(unresolved)
        full_identity_blocked = tuple(
            item
            for item in records
            if item.full_price_coverage and not item.authoritative
        )
        full_corporate_blocked = tuple(
            item
            for item in records
            if item.full_price_coverage and item.corporate_action_required
        )
        existing_additions = sum(
            item.full_price_coverage
            and item.authoritative
            and not item.corporate_action_required
            for item in records
        )
        authority_scenario_additions = sum(
            item.full_price_coverage
            and item.provider_instrument_key is not None
            and not item.corporate_action_required
            for item in records
        )
        conclusions = _identity_conclusion(records)
        return HistoricalIdentityBridgeReport(
            report_version=HISTORICAL_IDENTITY_BRIDGE_VERSION,
            total_candidates=len(records),
            historical_symbols=len({item.historical_symbol for item in records}),
            provisional_upstox_matches=len(provisional),
            unresolved_candidates=len(unresolved),
            unresolved_unique_symbols=len(
                {item.historical_symbol for item in unresolved}
            ),
            authoritative_identities=len(authoritative),
            authoritative_by_permanent_identifier=_status_count(
                records,
                HistoricalIdentityStatus.AUTHORITATIVE_PERMANENT_ID_MATCH,
            ),
            authoritative_by_isin=_status_count(
                records,
                HistoricalIdentityStatus.AUTHORITATIVE_ISIN_INTERVAL_MATCH,
            ),
            authoritative_by_historical_symbol_interval=_status_count(
                records,
                HistoricalIdentityStatus.AUTHORITATIVE_HISTORICAL_SYMBOL_INTERVAL_MATCH,
            ),
            authoritative_by_rename_chain=_status_count(
                records,
                HistoricalIdentityStatus.AUTHORITATIVE_RENAME_CHAIN_MATCH,
            ),
            authoritative_by_successor_predecessor=_status_count(
                records,
                HistoricalIdentityStatus.AUTHORITATIVE_SUCCESSOR_PREDECESSOR_MATCH,
            ),
            symbol_reuse_ambiguities=_status_count(
                records, HistoricalIdentityStatus.SYMBOL_REUSE_AMBIGUITY
            ),
            listing_conflicts=_status_count(
                records, HistoricalIdentityStatus.LISTING_INTERVAL_CONFLICT
            ),
            delisting_conflicts=_status_count(
                records, HistoricalIdentityStatus.DELISTING_INTERVAL_CONFLICT
            ),
            missing_isin_count=sum(item.provider_isin is None for item in records),
            missing_series_count=sum(
                item.historical_series is None for item in records
            ),
            candidates_bridgeable_with_existing_evidence=len(authoritative),
            candidates_requiring_external_identity_source=sum(
                not item.authoritative for item in records
            ),
            candidates_requiring_manual_adjudication=len(unresolved),
            identity_only_resolved_candidates=len(authoritative),
            identity_plus_corporate_action_ready_candidates=sum(
                not item.corporate_action_required for item in authoritative
            ),
            identity_resolved_corporate_action_blocked_candidates=sum(
                item.corporate_action_required for item in authoritative
            ),
            full_price_covered_identity_blocked_candidates=len(full_identity_blocked),
            full_price_covered_corporate_action_blocked_candidates=len(
                full_corporate_blocked
            ),
            projected_readiness_with_existing_evidence=(
                actual_authoritative_readiness + existing_additions
            ),
            projected_readiness_if_authority_supplied=(
                actual_authoritative_readiness + authority_scenario_additions
            ),
            actual_authoritative_readiness=actual_authoritative_readiness,
            unresolved_clusters=clusters,
            source_coverage=tuple(source_coverage),
            records=records,
            conclusion=conclusions,
            limitations=(
                "Manifest permanent identifiers are internal diagnostic security "
                "keys, not proven permanent exchange identifiers.",
                "The point-in-time security master is derived from local prices and "
                "is WEAK_INFERRED; it cannot establish identity authority.",
                "Upstox instrument keys, ISINs, and symbol matches remain provisional "
                "until bridged through effective-dated authoritative evidence.",
                "Identity authority does not establish split, bonus, dividend, or "
                "price-adjustment authority.",
            ),
        )

    def resolve_candidate(
        self,
        candidate: HistoricalSourceEvaluationManifestRecord,
        *,
        provider: UpstoxHistoricalCandidateEvidence | None,
        sources: Sequence[HistoricalIdentitySourceRecord],
    ) -> EffectiveDatedIdentityRecord:
        authoritative = tuple(item for item in sources if item.authoritative)
        symbol_sources = tuple(
            item
            for item in authoritative
            if item.historical_symbol == candidate.historical_symbol.upper()
            or item.current_symbol == candidate.historical_symbol.upper()
        )
        provider_isin = provider.isin.upper() if provider and provider.isin else None
        provider_key = provider.instrument_key if provider else None
        provider_symbol = (
            provider.matched_symbol.upper()
            if provider and provider.matched_symbol
            else None
        )
        provider_series = provider.provider_series if provider else None
        provider_exchange = provider.provider_exchange if provider else None
        exchange = (provider_exchange or "NSE").upper()

        listing_conflicts = tuple(
            item
            for item in symbol_sources
            if item.listing_date is not None
            and candidate.candidate_date < item.listing_date
        )
        if symbol_sources and len(listing_conflicts) == len(symbol_sources):
            return _identity_record(
                candidate,
                provider,
                source=listing_conflicts[0],
                status=HistoricalIdentityStatus.LISTING_INTERVAL_CONFLICT,
                method=IdentityMatchMethod.NONE,
                confidence=IdentityEvidenceConfidence.CONFLICTED,
                reasons=("candidate date precedes authoritative listing date",),
                cause=UnresolvedIdentityCause.NO_EVIDENCE_SOURCE_AVAILABLE,
            )
        delisting_conflicts = tuple(
            item
            for item in symbol_sources
            if item.delisting_date is not None
            and candidate.candidate_date > item.delisting_date
        )
        if symbol_sources and len(delisting_conflicts) == len(symbol_sources):
            return _identity_record(
                candidate,
                provider,
                source=delisting_conflicts[0],
                status=HistoricalIdentityStatus.DELISTING_INTERVAL_CONFLICT,
                method=IdentityMatchMethod.NONE,
                confidence=IdentityEvidenceConfidence.CONFLICTED,
                reasons=("candidate date follows authoritative delisting date",),
                cause=UnresolvedIdentityCause.DELISTED,
            )

        permanent_matches = tuple(
            item
            for item in authoritative
            if candidate.permanent_identifier
            and item.permanent_identifier == candidate.permanent_identifier
            and item.covers(candidate.candidate_date)
        )
        result = _unique_authoritative_match(
            candidate,
            provider,
            permanent_matches,
            status=HistoricalIdentityStatus.AUTHORITATIVE_PERMANENT_ID_MATCH,
            method=IdentityMatchMethod.PERMANENT_EXCHANGE_IDENTIFIER,
        )
        if result is not None:
            return result

        isin_matches = tuple(
            item
            for item in authoritative
            if provider_isin
            and item.isin == provider_isin
            and item.covers(candidate.candidate_date)
        )
        result = _unique_authoritative_match(
            candidate,
            provider,
            isin_matches,
            status=HistoricalIdentityStatus.AUTHORITATIVE_ISIN_INTERVAL_MATCH,
            method=IdentityMatchMethod.ISIN_EFFECTIVE_INTERVAL,
        )
        if result is not None:
            return result

        valid_symbol_sources = tuple(
            item for item in symbol_sources if item.covers(candidate.candidate_date)
        )
        distinct_ids = {item.permanent_identifier for item in valid_symbol_sources}
        if len(distinct_ids) > 1:
            return _identity_record(
                candidate,
                provider,
                source=None,
                status=HistoricalIdentityStatus.SYMBOL_REUSE_AMBIGUITY,
                method=IdentityMatchMethod.NONE,
                confidence=IdentityEvidenceConfidence.CONFLICTED,
                reasons=("multiple securities use this symbol on the candidate date",),
                cause=UnresolvedIdentityCause.SYMBOL_REUSED,
            )
        if (
            provider_isin
            and valid_symbol_sources
            and all(
                item.isin and item.isin != provider_isin
                for item in valid_symbol_sources
            )
        ):
            return _identity_record(
                candidate,
                provider,
                source=valid_symbol_sources[0],
                status=HistoricalIdentityStatus.ISIN_CONFLICT,
                method=IdentityMatchMethod.NONE,
                confidence=IdentityEvidenceConfidence.CONFLICTED,
                reasons=("provider ISIN conflicts with authoritative symbol record",),
                cause=UnresolvedIdentityCause.NO_EVIDENCE_SOURCE_AVAILABLE,
            )
        if (
            provider_series
            and valid_symbol_sources
            and any(
                item.series is not None and item.series != provider_series.upper()
                for item in valid_symbol_sources
            )
        ):
            return _identity_record(
                candidate,
                provider,
                source=valid_symbol_sources[0],
                status=HistoricalIdentityStatus.SERIES_MIGRATION_AMBIGUITY,
                method=IdentityMatchMethod.NONE,
                confidence=IdentityEvidenceConfidence.CONFLICTED,
                reasons=("provider series conflicts with authoritative interval",),
                cause=UnresolvedIdentityCause.SERIES_CHANGED,
            )

        symbol_interval_matches = tuple(
            item
            for item in valid_symbol_sources
            if item.exchange == exchange
            and item.series is not None
            and provider_series is not None
            and item.series == provider_series.upper()
        )
        result = _unique_authoritative_match(
            candidate,
            provider,
            symbol_interval_matches,
            status=(
                HistoricalIdentityStatus.AUTHORITATIVE_HISTORICAL_SYMBOL_INTERVAL_MATCH
            ),
            method=IdentityMatchMethod.HISTORICAL_SYMBOL_EXCHANGE_SERIES_INTERVAL,
        )
        if result is not None:
            return result

        rename_matches = tuple(
            item
            for item in authoritative
            if item.rename_event
            and item.historical_symbol == candidate.historical_symbol.upper()
            and provider_symbol is not None
            and item.current_symbol == provider_symbol
            and item.covers(candidate.candidate_date)
        )
        result = _unique_authoritative_match(
            candidate,
            provider,
            rename_matches,
            status=HistoricalIdentityStatus.AUTHORITATIVE_RENAME_CHAIN_MATCH,
            method=IdentityMatchMethod.RENAME_CHAIN,
        )
        if result is not None:
            return result

        succession_matches = tuple(
            item
            for item in authoritative
            if item.covers(candidate.candidate_date)
            and (
                item.predecessor_identifier == candidate.permanent_identifier
                or (
                    provider_key is not None
                    and item.provider_instrument_key == provider_key
                    and (
                        item.predecessor_identifier is not None
                        or item.successor_identifier is not None
                    )
                )
            )
        )
        result = _unique_authoritative_match(
            candidate,
            provider,
            succession_matches,
            status=(HistoricalIdentityStatus.AUTHORITATIVE_SUCCESSOR_PREDECESSOR_MATCH),
            method=IdentityMatchMethod.SUCCESSOR_PREDECESSOR_CHAIN,
        )
        if result is not None:
            return result

        provider_bridge_matches = tuple(
            item
            for item in authoritative
            if provider_key is not None
            and item.provider_instrument_key == provider_key
            and item.covers(candidate.candidate_date)
            and item.merger_or_demerger_event is None
            and item.series_migration_event is None
        )
        result = _unique_authoritative_match(
            candidate,
            provider,
            provider_bridge_matches,
            status=HistoricalIdentityStatus.AUTHORITATIVE_PERMANENT_ID_MATCH,
            method=IdentityMatchMethod.PROVIDER_INSTRUMENT_BRIDGE,
        )
        if result is not None:
            return result

        if any(item.merger_or_demerger_event for item in valid_symbol_sources):
            return _identity_record(
                candidate,
                provider,
                source=valid_symbol_sources[0],
                status=HistoricalIdentityStatus.MERGER_OR_DEMERGER_AMBIGUITY,
                method=IdentityMatchMethod.NONE,
                confidence=IdentityEvidenceConfidence.CONFLICTED,
                reasons=("merger or demerger lineage lacks a direct identity bridge",),
                cause=(
                    UnresolvedIdentityCause.KNOWN_DEMERGER
                    if "demerger"
                    in (valid_symbol_sources[0].merger_or_demerger_event or "").lower()
                    else UnresolvedIdentityCause.KNOWN_MERGER
                ),
            )

        if provider and provider.instrument_key:
            if (
                provider_symbol is not None
                and provider_symbol != candidate.historical_symbol.upper()
            ):
                return _identity_record(
                    candidate,
                    provider,
                    source=None,
                    status=HistoricalIdentityStatus.CURRENT_SYMBOL_ONLY_UNPROVEN,
                    method=IdentityMatchMethod.PROVIDER_SYMBOL_ONLY,
                    confidence=IdentityEvidenceConfidence.INSUFFICIENT,
                    reasons=("provider matched a different current symbol only",),
                    cause=UnresolvedIdentityCause.KNOWN_RENAME,
                )
            return _identity_record(
                candidate,
                provider,
                source=None,
                status=HistoricalIdentityStatus.PROVISIONAL_PROVIDER_SYMBOL_MATCH,
                method=IdentityMatchMethod.PROVIDER_SYMBOL_ONLY,
                confidence=IdentityEvidenceConfidence.PROVISIONAL,
                reasons=(
                    "matching provider symbol and ISIN are not effective-dated "
                    "identity authority",
                ),
                provisional=(
                    ProvisionalMatchClassification.READY_IF_AUTHORITY_SUPPLIED
                    if provider_isin
                    else (
                        ProvisionalMatchClassification.LIKELY_CORRECT_BUT_UNAUTHORITATIVE
                    )
                ),
            )

        if provider and provider.identity_status is UpstoxIdentityStatus.AMBIGUOUS:
            return _identity_record(
                candidate,
                provider,
                source=None,
                status=HistoricalIdentityStatus.MULTIPLE_INSTRUMENT_MATCHES,
                method=IdentityMatchMethod.NONE,
                confidence=IdentityEvidenceConfidence.CONFLICTED,
                reasons=(
                    provider.identity_ambiguity_reason or "multiple provider matches",
                ),
                cause=UnresolvedIdentityCause.AMBIGUOUS_MULTIPLE_MATCH,
            )
        if (
            provider
            and provider.identity_status is UpstoxIdentityStatus.INSTRUMENT_NOT_FOUND
        ):
            return _identity_record(
                candidate,
                provider,
                source=None,
                status=HistoricalIdentityStatus.INSTRUMENT_NOT_FOUND,
                method=IdentityMatchMethod.NONE,
                confidence=IdentityEvidenceConfidence.INSUFFICIENT,
                reasons=("provider instrument search found no matching instrument",),
                cause=UnresolvedIdentityCause.PROVIDER_SEARCH_FAILURE,
            )
        return _identity_record(
            candidate,
            provider,
            source=None,
            status=HistoricalIdentityStatus.IDENTITY_UNRESOLVED,
            method=IdentityMatchMethod.NONE,
            confidence=IdentityEvidenceConfidence.INSUFFICIENT,
            reasons=("no authoritative or provisional identity evidence is available",),
            cause=(
                UnresolvedIdentityCause.MANIFEST_MISSING_ISIN
                if provider_isin is None
                else UnresolvedIdentityCause.NO_EVIDENCE_SOURCE_AVAILABLE
            ),
        )


class UpstoxIdentityMetadataAuditEngine:
    def build(
        self,
        dataset: UpstoxHistoricalEvidenceDataset | None,
    ) -> UpstoxIdentityMetadataAudit:
        records = dataset.records if dataset else ()
        counts = (
            ("isin", sum(item.isin is not None for item in records)),
            (
                "instrument_key",
                sum(item.instrument_key is not None for item in records),
            ),
            (
                "trading_symbol",
                sum(item.matched_symbol is not None for item in records),
            ),
            ("exchange", sum(item.provider_exchange is not None for item in records)),
            ("segment", sum(item.provider_segment is not None for item in records)),
            ("series", sum(item.provider_series is not None for item in records)),
            (
                "exchange_token",
                sum(item.provider_exchange_token is not None for item in records),
            ),
            (
                "security_type",
                sum(item.provider_security_type is not None for item in records),
            ),
            (
                "instrument_type",
                sum(item.provider_instrument_type is not None for item in records),
            ),
            (
                "metadata_source",
                sum(item.provider_metadata_source is not None for item in records),
            ),
            (
                "search_query",
                sum(item.identity_search_query is not None for item in records),
            ),
            (
                "search_page_size",
                sum(item.identity_search_page_size is not None for item in records),
            ),
            (
                "active_or_continuity_status",
                sum(bool(item.active_status) for item in records),
            ),
            (
                "request_configuration_hash",
                sum(bool(item.request_configuration_hash) for item in records),
            ),
        )
        return UpstoxIdentityMetadataAudit(
            observed_candidates=len(records),
            provisional_matches=sum(
                item.identity_status
                is UpstoxIdentityStatus.RESOLVED_PROVISIONAL_FOR_PRICE_PROBE
                for item in records
            ),
            unresolved_candidates=sum(item.instrument_key is None for item in records),
            retained_field_counts=counts,
            parser_fields_available=(
                "instrument_key",
                "trading_symbol",
                "isin",
                "exchange",
                "segment",
                "series",
                "exchange_token",
                "security_type",
                "instrument_type",
                "source",
            ),
            candidate_fields_persisted=(
                "instrument_key",
                "matched_symbol",
                "isin",
                "active_status",
                "inactive_security",
                "request_configuration_hash",
                "provider_exchange",
                "provider_segment",
                "provider_series",
                "provider_exchange_token",
                "provider_security_type",
                "provider_instrument_type",
                "provider_metadata_source",
                "identity_search_query",
                "identity_search_page_size",
            ),
            fields_previously_discarded_from_candidate_evidence=(
                "exchange",
                "segment",
                "instrument_type",
                "instrument_source",
                "search_query",
                "search_page_size",
            ),
            fields_not_proven_returned=(
                "exchange_token",
                "security_type",
                "series",
                "provider_active_status",
                "expiry_or_derivative_metadata",
            ),
            secret_fields_persisted=(),
            account_fields_persisted=(),
            provenance_conclusion=(
                "The completed dataset proves ISIN, instrument key, and trading "
                "symbol retention. Exchange/segment/type were parsed in memory but "
                "not persisted; whether token/security-type/series were returned "
                "cannot be proved from retained evidence. New optional fields retain "
                "these values in future explicitly authorized probes."
            ),
            rerun_required=False,
        )


class UpstoxDuplicateOriginAuditEngine:
    def build(
        self,
        records: Sequence[UpstoxHistoricalCandidateEvidence],
        *,
        observations: Sequence[DuplicateSessionObservation] = (),
    ) -> UpstoxDuplicateOriginAudit:
        duplicate_records = tuple(
            item for item in records if item.duplicate_sessions > 0
        )
        grouped: dict[tuple[str, date], list[DuplicateSessionObservation]] = (
            defaultdict(list)
        )
        for observation in observations:
            grouped[(observation.candidate_id, observation.session_date)].append(
                observation
            )
        sessions_to_symbols: dict[date, set[str]] = defaultdict(set)
        for items in grouped.values():
            if len(items) > 1:
                sessions_to_symbols[items[0].session_date].add(items[0].symbol)
        attributions: list[DuplicateOriginAttribution] = []
        observed_candidates: set[str] = set()
        for (candidate_id, session), items in sorted(grouped.items()):
            if len(items) < 2:
                continue
            observed_candidates.add(candidate_id)
            origin = classify_duplicate_origin(items)
            exact = len({item.ohlcv_fingerprint for item in items}) == 1
            attributions.append(
                DuplicateOriginAttribution(
                    candidate_id=candidate_id,
                    symbol=items[0].symbol,
                    duplicated_date=session,
                    duplicate_rows=len(items),
                    exact_ohlcv=exact,
                    cross_symbol_same_session=(
                        len(sessions_to_symbols.get(session, set())) > 1
                    ),
                    origin=origin,
                    explanation=_duplicate_explanation(origin),
                )
            )
        for record in sorted(
            duplicate_records,
            key=lambda row: (row.candidate_date, row.candidate_id),
        ):
            if record.candidate_id in observed_candidates:
                continue
            attributions.append(
                DuplicateOriginAttribution(
                    candidate_id=record.candidate_id,
                    symbol=record.requested_historical_symbol,
                    duplicated_date=None,
                    duplicate_rows=record.duplicate_sessions + 1,
                    exact_ohlcv=None,
                    cross_symbol_same_session=None,
                    origin=DuplicateOriginClassification.UNKNOWN_DUPLICATE_ORIGIN,
                    explanation=(
                        "Persisted evidence retained only a duplicate count; date, "
                        "OHLCV equality, request boundary, and row lineage are absent."
                    ),
                )
            )
        distribution = Counter(item.origin.value for item in attributions)
        known = bool(attributions) and all(
            item.origin is not DuplicateOriginClassification.UNKNOWN_DUPLICATE_ORIGIN
            and item.exact_ohlcv is not None
            and item.duplicated_date is not None
            for item in attributions
        )
        return UpstoxDuplicateOriginAudit(
            duplicate_session_candidates=len(duplicate_records),
            duplicate_sessions_reported=sum(
                item.duplicate_sessions for item in duplicate_records
            ),
            attributions=tuple(attributions),
            origin_distribution=tuple(sorted(distribution.items())),
            duplicated_dates_available=sum(
                item.duplicated_date is not None for item in attributions
            ),
            exactness_available=sum(
                item.exact_ohlcv is not None for item in attributions
            ),
            cross_symbol_pattern_available=bool(grouped),
            future_safe_deduplication_supportable=known
            and all(item.exact_ohlcv is True for item in attributions),
            conclusion=(
                "DUPLICATE_SOURCE_ARTIFACT_CONFIRMED"
                if known
                else "DUPLICATE_ORIGIN_UNRESOLVED"
            ),
            required_missing_evidence=(
                ()
                if known
                else (
                    "duplicated session date",
                    "duplicate-row OHLCV fingerprints",
                    "request and window identifiers",
                    "normalization row lineage",
                    "resume-generation lineage",
                )
            ),
        )


def classify_duplicate_origin(
    observations: Sequence[DuplicateSessionObservation],
) -> DuplicateOriginClassification:
    if len(observations) < 2:
        return DuplicateOriginClassification.UNKNOWN_DUPLICATE_ORIGIN
    resume = {item.resume_generation for item in observations}
    if None not in resume and len(resume) > 1:
        return DuplicateOriginClassification.RESUME_MERGE_DUPLICATE
    windows = {item.request_window for item in observations}
    requests = {item.request_id for item in observations}
    if None not in windows and len(windows) > 1 and len(requests) > 1:
        return DuplicateOriginClassification.REQUEST_WINDOW_OVERLAP
    provider_rows = {item.provider_row_fingerprint for item in observations}
    stages = {item.normalization_stage for item in observations}
    if None not in provider_rows and len(provider_rows) == 1 and len(stages) > 1:
        return DuplicateOriginClassification.NORMALIZATION_DUPLICATE
    if len({item.ohlcv_fingerprint for item in observations}) > 1:
        return DuplicateOriginClassification.CONFLICTING_DUPLICATE_PROVIDER_ROW
    return DuplicateOriginClassification.EXACT_DUPLICATE_PROVIDER_ROW


class ProjectHistoricalIdentityAuditService:
    def __init__(
        self,
        *,
        upstox_repository: UpstoxHistoricalEvidenceRepository | None = None,
        identity_repository: HistoricalIdentityEvidenceRepository | None = None,
        point_in_time_repository: PointInTimeAnalyticalRepository | None = None,
    ) -> None:
        self.upstox_repository = (
            upstox_repository or UpstoxHistoricalEvidenceRepository()
        )
        self.identity_repository = (
            identity_repository or HistoricalIdentityEvidenceRepository()
        )
        self.point_in_time_repository = (
            point_in_time_repository or PointInTimeAnalyticalRepository()
        )

    def build(self) -> HistoricalIdentityAuditBundle:
        baseline = build_project_historical_source_evaluation(dry_run=True)
        upstox = self.upstox_repository.load()
        identities = self.identity_repository.load()
        breakout = build_project_breakout_source_gap_audit()
        coverage = _project_source_coverage(
            baseline.manifest,
            upstox,
            identities,
            self.point_in_time_repository,
        )
        bridge = HistoricalIdentityBridgeEngine().build(
            manifest=baseline.manifest,
            upstox_dataset=upstox,
            identity_dataset=identities,
            source_coverage=coverage,
            actual_authoritative_readiness=breakout.ready_records,
        )
        return HistoricalIdentityAuditBundle(
            bridge=bridge,
            metadata=UpstoxIdentityMetadataAuditEngine().build(upstox),
            duplicates=UpstoxDuplicateOriginAuditEngine().build(
                upstox.records if upstox else ()
            ),
        )


def filter_identity_records(
    records: Sequence[EffectiveDatedIdentityRecord],
    *,
    candidate_id: str | None = None,
    symbol: str | None = None,
    status: str | None = None,
    source: str | None = None,
    year: int | None = None,
    inactive: bool = False,
    renamed: bool = False,
    limit: int | None = None,
) -> tuple[EffectiveDatedIdentityRecord, ...]:
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be positive")
    normalized_symbol = symbol.upper() if symbol else None
    normalized_status = status.upper() if status else None
    normalized_source = source.upper() if source else None
    selected = tuple(
        item
        for item in records
        if candidate_id is None or item.candidate_id == candidate_id
        if normalized_symbol is None or item.historical_symbol == normalized_symbol
        if normalized_status is None
        or item.final_identity_status.value == normalized_status
        if normalized_source is None
        or item.identity_source.upper() == normalized_source
        if year is None or item.candidate_date.year == year
        if not inactive or item.inactive
        if not renamed or item.renamed
    )
    if candidate_id and not selected:
        raise ValueError(f"candidate id not found: {candidate_id}")
    return selected[:limit] if limit is not None else selected


def render_historical_identity_bridge_audit(
    report: HistoricalIdentityBridgeReport,
) -> tuple[str, ...]:
    return (
        "Authoritative Historical Identity Bridge Audit",
        f"Total Candidates: {report.total_candidates}",
        f"Historical Symbols: {report.historical_symbols}",
        f"Provisional Upstox Matches: {report.provisional_upstox_matches}",
        f"Unresolved Candidates: {report.unresolved_candidates}",
        f"Unresolved Unique Symbols: {report.unresolved_unique_symbols}",
        f"Authoritative Identities Established: {report.authoritative_identities}",
        "Authoritative Matches, Permanent ID / ISIN / Symbol Interval / Rename / "
        "Succession: "
        f"{report.authoritative_by_permanent_identifier} / "
        f"{report.authoritative_by_isin} / "
        f"{report.authoritative_by_historical_symbol_interval} / "
        f"{report.authoritative_by_rename_chain} / "
        f"{report.authoritative_by_successor_predecessor}",
        f"Symbol-Reuse Ambiguities: {report.symbol_reuse_ambiguities}",
        f"Listing / Delisting Conflicts: {report.listing_conflicts} / "
        f"{report.delisting_conflicts}",
        f"Missing Provider ISIN: {report.missing_isin_count}",
        f"Missing Historical Series: {report.missing_series_count}",
        "Bridgeable with Existing Authority: "
        f"{report.candidates_bridgeable_with_existing_evidence}",
        "External Identity Source Required: "
        f"{report.candidates_requiring_external_identity_source}",
        "Manual Adjudication Required: "
        f"{report.candidates_requiring_manual_adjudication}",
        "Identity Only / Identity + Corporate Action Ready / Corporate Action "
        "Blocked: "
        f"{report.identity_only_resolved_candidates} / "
        f"{report.identity_plus_corporate_action_ready_candidates} / "
        f"{report.identity_resolved_corporate_action_blocked_candidates}",
        "Full-Price-Covered, Identity / Corporate-Action Blocked: "
        f"{report.full_price_covered_identity_blocked_candidates} / "
        f"{report.full_price_covered_corporate_action_blocked_candidates}",
        "Projected Readiness with Existing Evidence: "
        f"{report.projected_readiness_with_existing_evidence}",
        "Projected Readiness if Identity Authority Is Supplied: "
        f"{report.projected_readiness_if_authority_supplied}",
        f"Actual Authoritative Readiness: {report.actual_authoritative_readiness}",
        f"Exact Next-Step Conclusion: {report.conclusion.value}",
        "PRODUCTION_INFLUENCE=false",
    )


def render_historical_identity_unresolved(
    report: HistoricalIdentityBridgeReport,
    records: Sequence[EffectiveDatedIdentityRecord],
) -> tuple[str, ...]:
    selected_ids = {item.candidate_id for item in records}
    clusters = _unresolved_clusters(
        tuple(
            item
            for item in report.records
            if item.candidate_id in selected_ids
            and not item.authoritative
            and item.final_identity_status
            is not HistoricalIdentityStatus.PROVISIONAL_PROVIDER_SYMBOL_MATCH
        )
    )
    return (
        "Historical Identity Unresolved Clusters",
        f"Candidates: {sum(item.candidate_count for item in clusters)}",
        "Unique Symbols: "
        f"{len({symbol for item in clusters for symbol in item.symbols})}",
        *(
            f"- {item.cause.value}: candidates={item.candidate_count}; "
            f"unique_symbols={item.unique_symbol_count}; "
            f"symbols={','.join(item.symbols)}"
            for item in clusters
        ),
        "Repeated symbols are counted once at symbol level.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_historical_identity_provisional(
    records: Sequence[EffectiveDatedIdentityRecord],
) -> tuple[str, ...]:
    provisional = tuple(
        item
        for item in records
        if item.final_identity_status
        is HistoricalIdentityStatus.PROVISIONAL_PROVIDER_SYMBOL_MATCH
    )
    classes = Counter(
        item.provisional_classification.value
        if item.provisional_classification
        else "UNCLASSIFIED"
        for item in provisional
    )
    matching_symbols = sum(
        item.historical_symbol == item.provider_symbol for item in provisional
    )
    return (
        "Historical Identity Provisional Match Audit",
        f"Candidates: {len(provisional)}",
        f"Unique Symbols: {len({item.historical_symbol for item in provisional})}",
        f"Candidate Symbol Equals Provider Symbol: {matching_symbols}",
        f"Inactive / Renamed: {sum(item.inactive for item in provisional)} / "
        f"{sum(item.renamed for item in provisional)}",
        "Classifications: " + _pairs(tuple(sorted(classes.items()))),
        "No provisional match is treated as authoritative.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_historical_identity_source_coverage(
    report: HistoricalIdentityBridgeReport,
) -> tuple[str, ...]:
    lines = ["Historical Identity Source Coverage"]
    for item in report.source_coverage:
        lines.extend(
            (
                f"- {item.source} ({item.source_version})",
                f"  Authority: {item.authority.value}",
                "  Records / Candidate Matches: "
                f"{item.records} / {item.candidate_matches}",
                f"  Fields Available: {', '.join(item.fields_available) or 'none'}",
                f"  Fields Missing: {', '.join(item.fields_missing) or 'none'}",
                f"  Limitation: {'; '.join(item.limitations) or 'none'}",
            )
        )
    lines.append(f"Exact Conclusion: {report.conclusion.value}")
    lines.append("PRODUCTION_INFLUENCE=false")
    return tuple(lines)


def render_upstox_identity_metadata_audit(
    report: UpstoxIdentityMetadataAudit,
) -> tuple[str, ...]:
    return (
        "Upstox Identity Metadata Retention Audit",
        f"Observed / Provisional / Unresolved: {report.observed_candidates} / "
        f"{report.provisional_matches} / {report.unresolved_candidates}",
        "Retained Field Counts: " + _pairs(report.retained_field_counts),
        "Parser Fields Available: " + ", ".join(report.parser_fields_available),
        "Candidate Fields Persisted: " + ", ".join(report.candidate_fields_persisted),
        "Previously Discarded from Candidate Evidence: "
        + ", ".join(report.fields_previously_discarded_from_candidate_evidence),
        "Not Proven Returned by Persisted Evidence: "
        + ", ".join(report.fields_not_proven_returned),
        "Secret Fields Persisted: "
        + (", ".join(report.secret_fields_persisted) or "none"),
        "Account Fields Persisted: "
        + (", ".join(report.account_fields_persisted) or "none"),
        f"Rerun Required: {'yes' if report.rerun_required else 'no'}",
        f"Conclusion: {report.provenance_conclusion}",
        "PRODUCTION_INFLUENCE=false",
    )


def render_upstox_duplicate_origin_audit(
    report: UpstoxDuplicateOriginAudit,
) -> tuple[str, ...]:
    return (
        "Upstox Duplicate-Session Origin Audit",
        f"Duplicate Candidates / Sessions: {report.duplicate_session_candidates} / "
        f"{report.duplicate_sessions_reported}",
        "Origin Distribution: " + _pairs(report.origin_distribution),
        f"Duplicated Dates Available: {report.duplicated_dates_available}",
        f"OHLCV Exactness Available: {report.exactness_available}",
        "Cross-Symbol Same-Session Pattern Available: "
        f"{'yes' if report.cross_symbol_pattern_available else 'no'}",
        "Future Safe Deterministic De-duplication Supportable: "
        f"{'yes' if report.future_safe_deduplication_supportable else 'no'}",
        "Missing Evidence: " + (", ".join(report.required_missing_evidence) or "none"),
        f"Exact Conclusion: {report.conclusion}",
        "INVALID_SERIES policy unchanged.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_historical_identity_readiness(
    report: HistoricalIdentityBridgeReport,
) -> tuple[str, ...]:
    return (
        "Historical Identity Reconstruction Readiness",
        f"Actual Authoritative Readiness: {report.actual_authoritative_readiness}",
        "Identity Authority Added from Existing Evidence: "
        f"{report.candidates_bridgeable_with_existing_evidence}",
        "Projected Readiness with Existing Evidence: "
        f"{report.projected_readiness_with_existing_evidence}",
        "Projected Readiness if Effective-Dated Authority Is Supplied: "
        f"{report.projected_readiness_if_authority_supplied}",
        "Full-Price-Covered Candidates Still Identity Blocked: "
        f"{report.full_price_covered_identity_blocked_candidates}",
        "Full-Price-Covered Candidates Still Corporate-Action Blocked: "
        f"{report.full_price_covered_corporate_action_blocked_candidates}",
        "Identity and corporate-action gates remain independent.",
        "No reconstruction records were changed.",
        f"Exact Next-Step Conclusion: {report.conclusion.value}",
        "PRODUCTION_INFLUENCE=false",
    )


def export_identity_json(value: Any, path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def export_identity_records_csv(
    records: Sequence[EffectiveDatedIdentityRecord],
    path: Path | str,
) -> None:
    rows = tuple(_flatten_identity_record(item) for item in records)
    fields = tuple(rows[0]) if rows else tuple(_flatten_identity_record(None))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export_identity_summary_csv(value: Any, path: Path | str) -> None:
    payload = _jsonable(value)
    rows = (
        tuple(
            {"field": str(key), "value": json.dumps(item, sort_keys=True)}
            for key, item in sorted(payload.items())
        )
        if isinstance(payload, dict)
        else ({"field": "value", "value": json.dumps(payload, sort_keys=True)},)
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("field", "value"))
        writer.writeheader()
        writer.writerows(rows)


def _unique_authoritative_match(
    candidate: HistoricalSourceEvaluationManifestRecord,
    provider: UpstoxHistoricalCandidateEvidence | None,
    matches: Sequence[HistoricalIdentitySourceRecord],
    *,
    status: HistoricalIdentityStatus,
    method: IdentityMatchMethod,
) -> EffectiveDatedIdentityRecord | None:
    if not matches:
        return None
    if len({item.permanent_identifier for item in matches}) > 1:
        return _identity_record(
            candidate,
            provider,
            source=None,
            status=HistoricalIdentityStatus.MULTIPLE_INSTRUMENT_MATCHES,
            method=IdentityMatchMethod.NONE,
            confidence=IdentityEvidenceConfidence.CONFLICTED,
            reasons=("multiple authoritative instruments match the same evidence",),
            cause=UnresolvedIdentityCause.AMBIGUOUS_MULTIPLE_MATCH,
        )
    source = sorted(matches, key=_source_sort_key)[0]
    return _identity_record(
        candidate,
        provider,
        source=source,
        status=status,
        method=method,
        confidence=IdentityEvidenceConfidence.AUTHORITATIVE,
        reasons=(),
    )


def _identity_record(
    candidate: HistoricalSourceEvaluationManifestRecord,
    provider: UpstoxHistoricalCandidateEvidence | None,
    *,
    source: HistoricalIdentitySourceRecord | None,
    status: HistoricalIdentityStatus,
    method: IdentityMatchMethod,
    confidence: IdentityEvidenceConfidence,
    reasons: tuple[str, ...],
    provisional: ProvisionalMatchClassification | None = None,
    cause: UnresolvedIdentityCause | None = None,
) -> EffectiveDatedIdentityRecord:
    complete = bool(
        source
        and source.permanent_identifier
        and source.source
        and source.source_version
        and (source.effective_from is not None or source.listing_date is not None)
    )
    partial = source is not None or (
        provider is not None and provider.instrument_key is not None
    )
    return EffectiveDatedIdentityRecord(
        candidate_id=candidate.candidate_id,
        candidate_date=candidate.candidate_date,
        historical_symbol=candidate.historical_symbol.upper(),
        exchange=(
            source.exchange
            if source
            else (provider.provider_exchange if provider else None)
        )
        or "NSE",
        historical_series=(
            source.series
            if source
            else (provider.provider_series if provider else None)
        ),
        provider_symbol=provider.matched_symbol if provider else None,
        provider_instrument_key=provider.instrument_key if provider else None,
        provider_isin=provider.isin if provider else None,
        repository_isin=source.isin if source else None,
        authoritative_permanent_identifier=(
            source.permanent_identifier if source else None
        ),
        manifest_internal_identifier=candidate.permanent_identifier,
        identity_source=source.source if source else "UPSTOX_PROVISIONAL_OR_NONE",
        identity_source_version=source.source_version if source else None,
        effective_from=source.effective_from if source else None,
        effective_to=source.effective_to if source else None,
        listing_date=source.listing_date if source else None,
        delisting_date=source.delisting_date if source else None,
        predecessor_identifier=source.predecessor_identifier if source else None,
        successor_identifier=source.successor_identifier if source else None,
        rename_event=source.rename_event if source else None,
        series_migration_event=source.series_migration_event if source else None,
        merger_or_demerger_event=(source.merger_or_demerger_event if source else None),
        match_method=method,
        evidence_confidence=confidence,
        ambiguity_reasons=reasons,
        provenance_completeness=(
            IdentityProvenanceCompleteness.COMPLETE
            if complete
            else IdentityProvenanceCompleteness.PARTIAL
            if partial
            else IdentityProvenanceCompleteness.INSUFFICIENT
        ),
        final_identity_status=status,
        provisional_classification=provisional,
        unresolved_cause=cause,
        full_price_coverage=bool(provider and provider.full_price_coverage),
        corporate_action_required=candidate.corporate_action_requirement,
        inactive=bool(provider and provider.inactive_security),
        renamed=bool(source and source.rename_event),
    )


def _unresolved_clusters(
    records: Sequence[EffectiveDatedIdentityRecord],
) -> tuple[UnresolvedIdentityCluster, ...]:
    grouped: dict[UnresolvedIdentityCause, list[EffectiveDatedIdentityRecord]] = (
        defaultdict(list)
    )
    for item in records:
        grouped[item.unresolved_cause or UnresolvedIdentityCause.UNKNOWN].append(item)
    return tuple(
        UnresolvedIdentityCluster(
            cause=cause,
            candidate_count=len(items),
            unique_symbol_count=len({item.historical_symbol for item in items}),
            symbols=tuple(sorted({item.historical_symbol for item in items})),
        )
        for cause, items in sorted(grouped.items(), key=lambda item: item[0].value)
    )


def _identity_conclusion(
    records: Sequence[EffectiveDatedIdentityRecord],
) -> IdentityAuditConclusion:
    authoritative = sum(item.authoritative for item in records)
    if authoritative == len(records) and records:
        return IdentityAuditConclusion.EXISTING_IDENTITY_EVIDENCE_SUFFICIENT
    if authoritative:
        return IdentityAuditConclusion.EXISTING_IDENTITY_EVIDENCE_PARTIALLY_SUFFICIENT
    return IdentityAuditConclusion.AUTHORITATIVE_EXTERNAL_IDENTITY_SOURCE_REQUIRED


def _project_source_coverage(
    manifest: HistoricalSourceEvaluationManifest,
    upstox: UpstoxHistoricalEvidenceDataset | None,
    identities: HistoricalIdentityEvidenceDataset,
    point_in_time: PointInTimeAnalyticalRepository,
) -> tuple[IdentitySourceCoverage, ...]:
    upstox_records = upstox.records if upstox else ()
    pit = point_in_time.status()
    return (
        IdentitySourceCoverage(
            source="HISTORICAL_REPLAY_MANIFEST",
            source_version=manifest.manifest_version,
            authority=IdentitySourceAuthority.INTERNAL_DIAGNOSTIC,
            records=len(manifest.records),
            fields_available=(
                "candidate_date",
                "historical_symbol",
                "internal_security_id",
            ),
            fields_missing=(
                "exchange_series",
                "isin",
                "effective_identity_interval",
                "rename_or_succession_chain",
            ),
            candidate_matches=len(manifest.records),
            limitations=(
                "internal security IDs are derived diagnostic keys, not "
                "exchange authority",
            ),
        ),
        IdentitySourceCoverage(
            source="UPSTOX_HISTORICAL_EVIDENCE",
            source_version=(upstox.dataset_version if upstox else "not_available"),
            authority=IdentitySourceAuthority.PROVIDER_PROVISIONAL,
            records=len(upstox_records),
            fields_available=(
                "provider_instrument_key",
                "provider_isin",
                "trading_symbol",
            ),
            fields_missing=(
                "authoritative_effective_interval",
                "historical_series",
                "rename_or_succession_chain",
            ),
            candidate_matches=sum(
                item.instrument_key is not None for item in upstox_records
            ),
            limitations=(
                "matching provider metadata is provisional identity evidence",
            ),
        ),
        IdentitySourceCoverage(
            source="DIAGNOSTIC_POINT_IN_TIME_SECURITY_MASTER",
            source_version=pit.store_version,
            authority=IdentitySourceAuthority.INTERNAL_DIAGNOSTIC,
            records=pit.security_rows,
            fields_available=("symbol", "exchange", "weak_inferred_listing_interval"),
            fields_missing=(
                "isin",
                "official_dates",
                "symbol_lineage",
                "authoritative_id",
            ),
            candidate_matches=0,
            limitations=(
                "all records are derived from local price observations and are "
                "WEAK_INFERRED",
            ),
        ),
        IdentitySourceCoverage(
            source="AUTHORIZED_EFFECTIVE_DATED_IDENTITY_PACKAGE",
            source_version=identities.dataset_version,
            authority=(
                identities.records[0].source_authority
                if identities.records
                else IdentitySourceAuthority.AUTHORITATIVE_REPOSITORY
            ),
            records=len(identities.records),
            fields_available=(
                "permanent_identifier",
                "isin",
                "symbol_exchange_series",
                "effective_interval",
                "lineage",
            )
            if identities.records
            else (),
            fields_missing=()
            if identities.records
            else ("authorized identity evidence package not supplied",),
            candidate_matches=0,
            limitations=()
            if identities.records
            else ("external authority is required before any bridge can be accepted",),
        ),
    )


def _source_record_from_payload(
    payload: Mapping[str, Any],
) -> HistoricalIdentitySourceRecord:
    row = dict(payload)
    for key in ("effective_from", "effective_to", "listing_date", "delisting_date"):
        row[key] = date.fromisoformat(str(row[key])) if row.get(key) else None
    row["source_authority"] = IdentitySourceAuthority(str(row["source_authority"]))
    return HistoricalIdentitySourceRecord(**row)


def _source_sort_key(item: HistoricalIdentitySourceRecord) -> tuple[str, str, str]:
    return item.source, item.source_version, item.permanent_identifier


def _status_count(
    records: Sequence[EffectiveDatedIdentityRecord],
    status: HistoricalIdentityStatus,
) -> int:
    return sum(item.final_identity_status is status for item in records)


def _duplicate_explanation(origin: DuplicateOriginClassification) -> str:
    return {
        DuplicateOriginClassification.EXACT_DUPLICATE_PROVIDER_ROW: (
            "Repeated provider rows have identical OHLCV fingerprints."
        ),
        DuplicateOriginClassification.CONFLICTING_DUPLICATE_PROVIDER_ROW: (
            "Repeated provider rows disagree on OHLCV values."
        ),
        DuplicateOriginClassification.REQUEST_WINDOW_OVERLAP: (
            "The same session arrived from overlapping request windows."
        ),
        DuplicateOriginClassification.RESUME_MERGE_DUPLICATE: (
            "The same session was merged from different resume generations."
        ),
        DuplicateOriginClassification.NORMALIZATION_DUPLICATE: (
            "One provider row was emitted by multiple normalization stages."
        ),
        DuplicateOriginClassification.UNKNOWN_DUPLICATE_ORIGIN: (
            "Available row lineage cannot determine duplicate origin."
        ),
    }[origin]


def _pairs(values: Sequence[tuple[str, int]]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values) or "none"


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _flatten_identity_record(
    item: EffectiveDatedIdentityRecord | None,
) -> dict[str, object]:
    if item is None:
        return {
            "candidate_id": "",
            "candidate_date": "",
            "historical_symbol": "",
            "provider_symbol": "",
            "provider_instrument_key": "",
            "provider_isin": "",
            "repository_isin": "",
            "authoritative_permanent_identifier": "",
            "identity_source": "",
            "match_method": "",
            "evidence_confidence": "",
            "final_identity_status": "",
            "unresolved_cause": "",
            "full_price_coverage": "",
            "corporate_action_required": "",
            "production_influence": "",
        }
    return {
        "candidate_id": item.candidate_id,
        "candidate_date": item.candidate_date.isoformat(),
        "historical_symbol": item.historical_symbol,
        "provider_symbol": item.provider_symbol or "",
        "provider_instrument_key": item.provider_instrument_key or "",
        "provider_isin": item.provider_isin or "",
        "repository_isin": item.repository_isin or "",
        "authoritative_permanent_identifier": (
            item.authoritative_permanent_identifier or ""
        ),
        "identity_source": item.identity_source,
        "match_method": item.match_method.value,
        "evidence_confidence": item.evidence_confidence.value,
        "final_identity_status": item.final_identity_status.value,
        "unresolved_cause": item.unresolved_cause.value
        if item.unresolved_cause
        else "",
        "full_price_coverage": item.full_price_coverage,
        "corporate_action_required": item.corporate_action_required,
        "production_influence": item.production_influence,
    }


__all__ = [
    "DEFAULT_HISTORICAL_IDENTITY_EVIDENCE_PATH",
    "DuplicateOriginClassification",
    "DuplicateSessionObservation",
    "EffectiveDatedIdentityRecord",
    "HistoricalIdentityAuditBundle",
    "HistoricalIdentityBridgeEngine",
    "HistoricalIdentityBridgeReport",
    "HistoricalIdentityEvidenceDataset",
    "HistoricalIdentityEvidenceRepository",
    "HistoricalIdentitySourceRecord",
    "HistoricalIdentityStatus",
    "IdentityAuditConclusion",
    "IdentityEvidenceConfidence",
    "IdentityMatchMethod",
    "IdentitySourceAuthority",
    "ProjectHistoricalIdentityAuditService",
    "ProvisionalMatchClassification",
    "UnresolvedIdentityCause",
    "UpstoxDuplicateOriginAudit",
    "UpstoxDuplicateOriginAuditEngine",
    "UpstoxIdentityMetadataAudit",
    "UpstoxIdentityMetadataAuditEngine",
    "classify_duplicate_origin",
    "export_identity_json",
    "export_identity_records_csv",
    "export_identity_summary_csv",
    "filter_identity_records",
    "render_historical_identity_bridge_audit",
    "render_historical_identity_provisional",
    "render_historical_identity_readiness",
    "render_historical_identity_source_coverage",
    "render_historical_identity_unresolved",
    "render_upstox_duplicate_origin_audit",
    "render_upstox_identity_metadata_audit",
]
