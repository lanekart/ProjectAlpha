from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpha.historical_replay.historical_source_evaluation import (
    HistoricalSourceEvaluationManifestRecord,
)
from alpha.historical_replay.upstox_historical_probe import (
    PRODUCTION_INFLUENCE,
    UpstoxHistoricalCandidateEvidence,
)

NSE_ARCHIVE_PROOF_VERSION = "nse-archive-proof-v1"
NSE_TRIAL_DATE_FROM = date(2016, 7, 11)
NSE_TRIAL_DATE_TO = date(2016, 7, 18)

NSE_CONTROL_SYMBOLS = frozenset(
    {"ICICIBANK", "TATASTEEL", "PNB", "SUZLON", "HINDALCO", "ASHOKLEY"}
)
NSE_RENAME_OR_INACTIVE_SYMBOLS = frozenset(
    {"IDFC", "L&TFH", "GMRINFRA", "TATAMOTORS", "TV18BRDCST", "WELSPUNIND"}
)

_OFFICIAL_DOMAINS = (
    "https://www.nseindia.com/",
    "https://archives.nseindia.com/",
    "https://nsearchives.nseindia.com/",
)


class NseArchiveSourceType(StrEnum):
    CM_BHAVCOPY = "CM_BHAVCOPY"
    CM_MII_SECURITY_FILE = "CM_MII_SECURITY_FILE"
    CM_NEAT_SECURITY_FILE = "CM_NEAT_SECURITY_FILE"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    SYMBOL_CHANGE_CIRCULAR = "SYMBOL_CHANGE_CIRCULAR"
    LISTING_SUSPENSION_DELISTING_CIRCULAR = "LISTING_SUSPENSION_DELISTING_CIRCULAR"
    SCHEME_OF_ARRANGEMENT_CIRCULAR = "SCHEME_OF_ARRANGEMENT_CIRCULAR"


class NseArchiveAccessResult(StrEnum):
    LOCAL_CACHE_AVAILABLE = "LOCAL_CACHE_AVAILABLE"
    RETRIEVED = "RETRIEVED"
    FILE_MISSING = "FILE_MISSING"
    NOT_AVAILABLE_FOR_DATE = "NOT_AVAILABLE_FOR_DATE"
    NOT_COLLECTED = "NOT_COLLECTED"
    TERMS_AUTHORIZATION_REQUIRED = "TERMS_AUTHORIZATION_REQUIRED"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    MALFORMED_ARCHIVE = "MALFORMED_ARCHIVE"


class NseSecuritySchemaVersion(StrEnum):
    LEGACY_CM_BHAVCOPY_V1 = "LEGACY_CM_BHAVCOPY_V1"
    UDIFF_CM_BHAVCOPY_V1 = "UDIFF_CM_BHAVCOPY_V1"
    MII_CM_SECURITY_V1 = "MII_CM_SECURITY_V1"
    NEAT_CM_SECURITY_V1 = "NEAT_CM_SECURITY_V1"
    UNKNOWN = "UNKNOWN"


class NseIdentityProofStatus(StrEnum):
    NSE_PERMANENT_ID_INTERVAL_MATCH = "NSE_PERMANENT_ID_INTERVAL_MATCH"
    NSE_ISIN_INTERVAL_MATCH = "NSE_ISIN_INTERVAL_MATCH"
    NSE_SYMBOL_SERIES_DATE_MATCH = "NSE_SYMBOL_SERIES_DATE_MATCH"
    NSE_RENAME_CHAIN_MATCH = "NSE_RENAME_CHAIN_MATCH"
    NSE_SUCCESSION_CHAIN_MATCH = "NSE_SUCCESSION_CHAIN_MATCH"
    NSE_CURRENT_STATE_ONLY = "NSE_CURRENT_STATE_ONLY"
    NSE_SERIES_MISSING = "NSE_SERIES_MISSING"
    NSE_ISIN_MISSING = "NSE_ISIN_MISSING"
    NSE_SYMBOL_NOT_FOUND = "NSE_SYMBOL_NOT_FOUND"
    NSE_ARCHIVE_FILE_MISSING = "NSE_ARCHIVE_FILE_MISSING"
    NSE_INTERVAL_AMBIGUOUS = "NSE_INTERVAL_AMBIGUOUS"
    NSE_SOURCE_CONFLICT = "NSE_SOURCE_CONFLICT"
    NSE_MANUAL_REVIEW_REQUIRED = "NSE_MANUAL_REVIEW_REQUIRED"
    NSE_IDENTITY_UNRESOLVED = "NSE_IDENTITY_UNRESOLVED"


class NseCorporateActionProofStatus(StrEnum):
    NSE_CA_EVIDENCE_COMPLETE = "NSE_CA_EVIDENCE_COMPLETE"
    NSE_CA_EVENT_FOUND_FIELDS_PARTIAL = "NSE_CA_EVENT_FOUND_FIELDS_PARTIAL"
    NSE_CA_CIRCULAR_ONLY = "NSE_CA_CIRCULAR_ONLY"
    NSE_CA_NOT_FOUND = "NSE_CA_NOT_FOUND"
    NSE_CA_CONFLICT = "NSE_CA_CONFLICT"
    NSE_CA_MANUAL_REVIEW_REQUIRED = "NSE_CA_MANUAL_REVIEW_REQUIRED"


class NseCorporateActionType(StrEnum):
    BONUS = "BONUS"
    SPLIT = "SPLIT"
    CONSOLIDATION = "CONSOLIDATION"
    RIGHTS = "RIGHTS"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
    ISIN_CHANGE = "ISIN_CHANGE"
    DIVIDEND = "DIVIDEND"
    OTHER = "OTHER"


class NseIdentityEventType(StrEnum):
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
    SUCCESSION = "SUCCESSION"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    LISTING = "LISTING"
    DELISTING = "DELISTING"
    SUSPENSION = "SUSPENSION"
    RELISTING = "RELISTING"


class NseArchiveCoverageConclusion(StrEnum):
    NSE_PUBLIC_ARCHIVE_SUFFICIENT = "NSE_PUBLIC_ARCHIVE_SUFFICIENT"
    NSE_PUBLIC_ARCHIVE_PARTIALLY_SUFFICIENT = "NSE_PUBLIC_ARCHIVE_PARTIALLY_SUFFICIENT"
    NSE_PAID_HISTORICAL_PACKAGE_REQUIRED = "NSE_PAID_HISTORICAL_PACKAGE_REQUIRED"
    NSE_ARCHIVE_IDENTITY_FIELDS_INSUFFICIENT = (
        "NSE_ARCHIVE_IDENTITY_FIELDS_INSUFFICIENT"
    )
    NSE_ARCHIVE_COVERAGE_GAPS_MATERIAL = "NSE_ARCHIVE_COVERAGE_GAPS_MATERIAL"
    NSE_ACCESS_OR_RETENTION_TERMS_BLOCKING = "NSE_ACCESS_OR_RETENTION_TERMS_BLOCKING"
    NSE_PROOF_INCOMPLETE = "NSE_PROOF_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class NseArchiveSourceDefinition:
    source_type: NseArchiveSourceType
    official_url_pattern: str
    archive_category: str
    mime_type: str
    compression_format: str
    schema_version: NseSecuritySchemaVersion
    documented_availability: str
    official_reference: str


@dataclass(frozen=True, slots=True)
class NseArchiveFileEvidence:
    source_type: NseArchiveSourceType
    official_url_pattern: str
    archive_date: date
    filename: str
    archive_category: str
    mime_type: str
    compression_format: str
    schema_version: NseSecuritySchemaVersion
    source_checksum: str | None
    retrieval_timestamp: datetime | None
    access_result: NseArchiveAccessResult
    license_or_usage_notice: str
    retention_restriction: str
    redistribution_restriction: str
    local_path: str | None = None
    explanation: str = ""
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class NseSecurityRecord:
    as_of_date: date
    trading_symbol: str
    security_series: str | None
    isin: str | None
    exchange_security_identifier: str | None
    company_or_security_name: str | None
    instrument_type: str | None
    listing_status: str | None
    permitted_to_trade: bool | None
    face_value: Decimal | None
    issue_capital: Decimal | None
    listing_date: date | None
    delisting_date: date | None
    suspension_indicator: bool | None
    active_status: str | None
    predecessor_security_id: str | None
    successor_security_id: str | None
    source_type: NseArchiveSourceType
    source_filename: str
    source_checksum: str
    schema_version: NseSecuritySchemaVersion
    current_state_only: bool = False

    def valid_on(self, value: date) -> bool:
        return (self.listing_date is None or value >= self.listing_date) and (
            self.delisting_date is None or value <= self.delisting_date
        )


@dataclass(frozen=True, slots=True)
class NseSecurityFileInspection:
    file_evidence: NseArchiveFileEvidence
    schema_version: NseSecuritySchemaVersion
    fields_available: tuple[str, ...]
    fields_unavailable: tuple[str, ...]
    records: tuple[NseSecurityRecord, ...]
    malformed_rows: int
    deterministic_checksum: str | None
    explanation: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class NseIdentityEventRecord:
    event_type: NseIdentityEventType
    effective_date: date
    old_symbol: str | None
    new_symbol: str | None
    old_isin: str | None
    new_isin: str | None
    predecessor_security_id: str | None
    successor_security_id: str | None
    circular_reference: str
    source_checksum: str


@dataclass(frozen=True, slots=True)
class NseCorporateActionRecord:
    symbol: str
    series: str | None
    action_type: NseCorporateActionType
    purpose: str
    announcement_date: date | None
    record_date: date | None
    ex_date: date | None
    effective_date: date | None
    old_face_value: Decimal | None
    new_face_value: Decimal | None
    bonus_ratio: str | None
    split_or_consolidation_ratio: str | None
    rights_ratio: str | None
    old_symbol: str | None
    new_symbol: str | None
    old_isin: str | None
    new_isin: str | None
    predecessor_security_id: str | None
    successor_security_id: str | None
    circular_reference: str | None
    source_filename: str
    source_checksum: str
    circular_only: bool = False

    @property
    def event_date(self) -> date | None:
        return self.effective_date or self.ex_date or self.record_date


_AUTHORITATIVE_NSE_STATUSES = frozenset(
    {
        NseIdentityProofStatus.NSE_PERMANENT_ID_INTERVAL_MATCH,
        NseIdentityProofStatus.NSE_ISIN_INTERVAL_MATCH,
        NseIdentityProofStatus.NSE_SYMBOL_SERIES_DATE_MATCH,
        NseIdentityProofStatus.NSE_RENAME_CHAIN_MATCH,
        NseIdentityProofStatus.NSE_SUCCESSION_CHAIN_MATCH,
    }
)


@dataclass(frozen=True, slots=True)
class NseIdentityProofRecord:
    candidate_id: str
    candidate_date: date
    historical_symbol: str
    manifest_exchange: str
    manifest_series: str | None
    upstox_instrument_key: str | None
    upstox_symbol: str | None
    upstox_isin: str | None
    nse_permanent_identifier: str | None
    nse_isin: str | None
    nse_symbol: str | None
    nse_series: str | None
    source_filename: str | None
    source_checksum: str | None
    match_status: NseIdentityProofStatus
    provider_bridge_established: bool
    conflicts: tuple[str, ...]
    explanation: str
    inactive: bool
    renamed: bool
    corporate_action_required: bool
    full_price_coverage: bool
    setup_type: str | None
    entry_timing_state: str | None
    market_regime: str | None
    recovery_population: str
    gap_cause: str
    production_influence: bool = PRODUCTION_INFLUENCE

    @property
    def authoritative(self) -> bool:
        return self.match_status in _AUTHORITATIVE_NSE_STATUSES


@dataclass(frozen=True, slots=True)
class NseCorporateActionProofRecord:
    candidate_id: str
    candidate_date: date
    symbol: str
    status: NseCorporateActionProofStatus
    action_type: NseCorporateActionType | None
    event_date: date | None
    source_reference: str | None
    source_checksum: str | None
    fields_available: tuple[str, ...]
    fields_missing: tuple[str, ...]
    identity_authority_established: bool
    price_adjustment_authority_established: bool
    explanation: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class NseArchiveSourceDiscoveryReport:
    report_version: str
    requested_date_from: date
    requested_date_to: date
    source_definitions: tuple[NseArchiveSourceDefinition, ...]
    files: tuple[NseArchiveFileEvidence, ...]
    dates_requested: int
    dates_with_local_bhavcopy: int
    dates_missing_bhavcopy: int
    network_opt_in: bool
    network_requests: int
    retention_or_license_blocking: bool
    limitations: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class NseSecurityFileInspectReport:
    report_version: str
    files_inspected: int
    records_inspected: int
    malformed_files: int
    malformed_rows: int
    schema_versions_observed: tuple[tuple[str, int], ...]
    fields_available: tuple[str, ...]
    fields_unavailable: tuple[str, ...]
    inspections: tuple[NseSecurityFileInspection, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class NseIdentityProofReport:
    report_version: str
    proof_candidates: int
    proof_unique_symbols: int
    authoritative_matches: int
    unresolved_candidates: int
    permanent_id_matches: int
    isin_matches: int
    symbol_series_matches: int
    rename_chain_matches: int
    succession_chain_matches: int
    inactive_identities_resolved: int
    renamed_identities_resolved: int
    source_conflicts: int
    status_counts: tuple[tuple[str, int], ...]
    records: tuple[NseIdentityProofRecord, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class NseCorporateActionProofReport:
    report_version: str
    cases_evaluated: int
    events_found: int
    complete_cases: int
    partial_cases: int
    circular_only_cases: int
    conflicts: int
    not_found: int
    records: tuple[NseCorporateActionProofRecord, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class NseArchiveCoverageReport:
    report_version: str
    proof_candidates: int
    proof_authoritative_matches: int
    proof_unresolved_candidates: int
    unresolved_upstox_candidates_tested: int
    unresolved_upstox_candidates_resolved: int
    provisional_upstox_candidates_tested: int
    provisional_upstox_candidates_confirmed: int
    full_population_candidates: int
    full_population_authoritative_matches: int
    full_population_unresolved: int
    full_population_unique_symbols_resolved: int
    projected_657_candidate_identity_coverage_percent: Decimal
    security_files_available: int
    corporate_action_files_available: int
    conclusion: NseArchiveCoverageConclusion
    paid_nse_data_still_required: bool
    limitations: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class NseArchiveReadinessReport:
    report_version: str
    missing_candidate_manifest: int
    current_authoritative_readiness: int
    full_upstox_price_coverage: int
    candidates_receiving_nse_identity: int
    identity_and_price_ready: int
    identity_ready_price_blocked: int
    price_ready_identity_blocked: int
    identity_and_price_ready_ca_blocked: int
    candidates_still_identity_blocked: int
    candidates_still_price_blocked: int
    maximum_readiness_after_identity_evidence: int
    maximum_readiness_after_identity_and_corporate_action_evidence: int
    actual_readiness_unchanged: int
    simulated_not_achieved: bool
    exact_next_step_conclusion: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class NseArchiveProofBundle:
    discovery: NseArchiveSourceDiscoveryReport
    security: NseSecurityFileInspectReport
    identity: NseIdentityProofReport
    corporate_actions: NseCorporateActionProofReport
    coverage: NseArchiveCoverageReport
    readiness: NseArchiveReadinessReport
    population_identity_records: tuple[NseIdentityProofRecord, ...]


_CANONICAL_SECURITY_FIELDS = (
    "trading_symbol",
    "security_series",
    "isin",
    "exchange_security_identifier",
    "company_or_security_name",
    "instrument_type",
    "listing_status",
    "permitted_to_trade",
    "face_value",
    "issue_capital",
    "listing_date",
    "delisting_date",
    "suspension_indicator",
    "active_status",
    "predecessor_security_id",
    "successor_security_id",
)

_FIELD_ALIASES: Mapping[str, tuple[str, ...]] = {
    "trading_symbol": ("SYMBOL", "TCKRSYMB", "TRADING_SYMBOL"),
    "security_series": ("SERIES", "SCTYSRS", "SECURITY_SERIES"),
    "isin": ("ISIN", "ISINNUMBER", "ISIN_NO"),
    "exchange_security_identifier": (
        "SECURITY_ID",
        "EXCHANGE_SECURITY_ID",
        "FININSTRMID",
        "TOKEN",
    ),
    "company_or_security_name": (
        "SECURITY_NAME",
        "NAME_OF_COMPANY",
        "FININSTRMNM",
        "COMPANY_NAME",
        "NAME",
    ),
    "instrument_type": ("INSTRUMENT_TYPE", "FININSTRMTP", "INSTRUMENT"),
    "listing_status": ("LISTING_STATUS", "STATUS"),
    "permitted_to_trade": ("PERMITTED_TO_TRADE", "PERMITTEDTOTRADE"),
    "face_value": ("FACE_VALUE", "FACEVALUE"),
    "issue_capital": ("ISSUE_CAPITAL", "ISSUECAPITAL"),
    "listing_date": ("LISTING_DATE", "DATE_OF_LISTING"),
    "delisting_date": ("DELISTING_DATE", "DATE_OF_DELISTING"),
    "suspension_indicator": ("SUSPENSION_INDICATOR", "SUSPENDED"),
    "active_status": ("ACTIVE_STATUS", "SECURITY_STATUS"),
    "predecessor_security_id": ("PREDECESSOR_SECURITY_ID",),
    "successor_security_id": ("SUCCESSOR_SECURITY_ID",),
}


def official_nse_source_catalog() -> tuple[NseArchiveSourceDefinition, ...]:
    return (
        NseArchiveSourceDefinition(
            source_type=NseArchiveSourceType.CM_BHAVCOPY,
            official_url_pattern=(
                "https://archives.nseindia.com/content/historical/EQUITIES/"
                "{YYYY}/{MON}/cm{DD}{MON}{YYYY}bhav.csv.zip"
            ),
            archive_category="NSE capital-market historical reports",
            mime_type="application/zip",
            compression_format="ZIP",
            schema_version=NseSecuritySchemaVersion.LEGACY_CM_BHAVCOPY_V1,
            documented_availability="dated legacy files; UDiFF replaced them in 2024",
            official_reference="https://www.nseindia.com/all-reports",
        ),
        NseArchiveSourceDefinition(
            source_type=NseArchiveSourceType.CM_MII_SECURITY_FILE,
            official_url_pattern=(
                "https://www.nseindia.com/all-reports -> "
                "NSE_CM_security_{DDMMYYYY}.csv.gz"
            ),
            archive_category="CM MII security master",
            mime_type="application/gzip",
            compression_format="GZIP",
            schema_version=NseSecuritySchemaVersion.MII_CM_SECURITY_V1,
            documented_availability="website dissemination effective 2024-02-05",
            official_reference=(
                "https://nsearchives.nseindia.com/content/circulars/MSD60315.pdf"
            ),
        ),
        NseArchiveSourceDefinition(
            source_type=NseArchiveSourceType.CM_NEAT_SECURITY_FILE,
            official_url_pattern="NSE member extranet /cmftp/common/ntneat/security.gz",
            archive_category="CM member security master",
            mime_type="application/gzip",
            compression_format="GZIP",
            schema_version=NseSecuritySchemaVersion.NEAT_CM_SECURITY_V1,
            documented_availability="member extranet; not a public archive endpoint",
            official_reference=(
                "https://nsearchives.nseindia.com/web/sites/default/files/"
                "inline-files/NSE-Masters%20Data-v1.6.pdf"
            ),
        ),
        NseArchiveSourceDefinition(
            source_type=NseArchiveSourceType.CORPORATE_ACTIONS,
            official_url_pattern=(
                "https://www.nseindia.com/companies-listing/corporate-filings-actions"
            ),
            archive_category="NSE corporate filings and actions",
            mime_type="text/csv",
            compression_format="NONE",
            schema_version=NseSecuritySchemaVersion.UNKNOWN,
            documented_availability="web query; historical retention not proven",
            official_reference=(
                "https://www.nseindia.com/companies-listing/corporate-filings-actions"
            ),
        ),
        NseArchiveSourceDefinition(
            source_type=NseArchiveSourceType.SYMBOL_CHANGE_CIRCULAR,
            official_url_pattern=(
                "https://nsearchives.nseindia.com/content/circulars/{REFERENCE}.pdf"
            ),
            archive_category="NSE listing circulars",
            mime_type="application/pdf",
            compression_format="NONE",
            schema_version=NseSecuritySchemaVersion.UNKNOWN,
            documented_availability=(
                "individual circulars; no complete trial index cached"
            ),
            official_reference=(
                "https://www.nseindia.com/resources/exchange-communication-circulars"
            ),
        ),
        NseArchiveSourceDefinition(
            source_type=(NseArchiveSourceType.LISTING_SUSPENSION_DELISTING_CIRCULAR),
            official_url_pattern=(
                "https://nsearchives.nseindia.com/content/circulars/{REFERENCE}.pdf"
            ),
            archive_category="NSE listing compliance circulars",
            mime_type="application/pdf",
            compression_format="NONE",
            schema_version=NseSecuritySchemaVersion.UNKNOWN,
            documented_availability="individual circulars; coverage unproven",
            official_reference=(
                "https://www.nseindia.com/resources/exchange-communication-circulars"
            ),
        ),
        NseArchiveSourceDefinition(
            source_type=NseArchiveSourceType.SCHEME_OF_ARRANGEMENT_CIRCULAR,
            official_url_pattern=(
                "https://nsearchives.nseindia.com/content/circulars/{REFERENCE}.pdf"
            ),
            archive_category="NSE merger, demerger and scheme circulars",
            mime_type="application/pdf",
            compression_format="NONE",
            schema_version=NseSecuritySchemaVersion.UNKNOWN,
            documented_availability="individual circulars; coverage unproven",
            official_reference=(
                "https://www.nseindia.com/resources/exchange-communication-circulars"
            ),
        ),
    )


class NseArchiveParser:
    def parse_security_file(
        self,
        payload: bytes,
        *,
        file_evidence: NseArchiveFileEvidence,
        current_state_only: bool = False,
    ) -> NseSecurityFileInspection:
        checksum = hashlib.sha256(payload).hexdigest()
        if (
            file_evidence.source_checksum is not None
            and checksum != file_evidence.source_checksum
        ):
            raise ValueError("NSE archive checksum does not match file evidence")
        text, member_name = _decode_archive(payload, file_evidence.filename)
        delimiter = "|" if _looks_pipe_delimited(text) else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError("NSE security file has no header")
        normalized_headers = {_normalize_header(item) for item in reader.fieldnames}
        resolved_schema = _security_schema(
            file_evidence.source_type,
            normalized_headers,
            delimiter=delimiter,
        )
        field_headers = {
            field: next(
                (
                    alias
                    for alias in aliases
                    if _normalize_header(alias) in normalized_headers
                ),
                None,
            )
            for field, aliases in _FIELD_ALIASES.items()
        }
        if field_headers["trading_symbol"] is None:
            raise ValueError("NSE security file is missing a trading symbol column")
        available = tuple(
            field for field in _CANONICAL_SECURITY_FIELDS if field_headers[field]
        )
        unavailable = tuple(
            field for field in _CANONICAL_SECURITY_FIELDS if not field_headers[field]
        )
        rows: list[NseSecurityRecord] = []
        malformed = 0
        for raw_row in reader:
            row = {
                _normalize_header(key): _clean(value) for key, value in raw_row.items()
            }
            symbol = _get_alias(row, _FIELD_ALIASES["trading_symbol"])
            if symbol is None:
                malformed += 1
                continue
            try:
                rows.append(
                    NseSecurityRecord(
                        as_of_date=file_evidence.archive_date,
                        trading_symbol=symbol.upper(),
                        security_series=_upper(
                            _get_alias(row, _FIELD_ALIASES["security_series"])
                        ),
                        isin=_upper(_get_alias(row, _FIELD_ALIASES["isin"])),
                        exchange_security_identifier=_get_alias(
                            row, _FIELD_ALIASES["exchange_security_identifier"]
                        ),
                        company_or_security_name=_get_alias(
                            row, _FIELD_ALIASES["company_or_security_name"]
                        ),
                        instrument_type=_get_alias(
                            row, _FIELD_ALIASES["instrument_type"]
                        ),
                        listing_status=_get_alias(
                            row, _FIELD_ALIASES["listing_status"]
                        ),
                        permitted_to_trade=_parse_bool(
                            _get_alias(row, _FIELD_ALIASES["permitted_to_trade"])
                        ),
                        face_value=_parse_decimal(
                            _get_alias(row, _FIELD_ALIASES["face_value"])
                        ),
                        issue_capital=_parse_decimal(
                            _get_alias(row, _FIELD_ALIASES["issue_capital"])
                        ),
                        listing_date=_parse_date(
                            _get_alias(row, _FIELD_ALIASES["listing_date"])
                        ),
                        delisting_date=_parse_date(
                            _get_alias(row, _FIELD_ALIASES["delisting_date"])
                        ),
                        suspension_indicator=_parse_bool(
                            _get_alias(row, _FIELD_ALIASES["suspension_indicator"])
                        ),
                        active_status=_get_alias(row, _FIELD_ALIASES["active_status"]),
                        predecessor_security_id=_get_alias(
                            row, _FIELD_ALIASES["predecessor_security_id"]
                        ),
                        successor_security_id=_get_alias(
                            row, _FIELD_ALIASES["successor_security_id"]
                        ),
                        source_type=file_evidence.source_type,
                        source_filename=member_name,
                        source_checksum=checksum,
                        schema_version=resolved_schema,
                        current_state_only=current_state_only,
                    )
                )
            except ValueError:
                malformed += 1
        ordered = tuple(
            sorted(
                rows,
                key=lambda item: (
                    item.trading_symbol,
                    item.security_series or "",
                    item.isin or "",
                    item.exchange_security_identifier or "",
                ),
            )
        )
        return NseSecurityFileInspection(
            file_evidence=file_evidence,
            schema_version=resolved_schema,
            fields_available=available,
            fields_unavailable=unavailable,
            records=ordered,
            malformed_rows=malformed,
            deterministic_checksum=checksum,
            explanation=(
                f"Parsed {len(ordered)} deterministic security rows from {member_name}."
            ),
        )

    def parse_identity_events(
        self,
        payload: bytes,
        *,
        filename: str,
    ) -> tuple[NseIdentityEventRecord, ...]:
        checksum = hashlib.sha256(payload).hexdigest()
        text, _ = _decode_archive(payload, filename)
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValueError("NSE identity event file has no header")
        events: list[NseIdentityEventRecord] = []
        for raw in reader:
            row = {_normalize_header(key): _clean(value) for key, value in raw.items()}
            effective = _parse_date(row.get("EFFECTIVE_DATE"))
            raw_type = row.get("EVENT_TYPE")
            reference = row.get("CIRCULAR_REFERENCE")
            if effective is None or raw_type is None or reference is None:
                raise ValueError("NSE identity event row is missing required fields")
            events.append(
                NseIdentityEventRecord(
                    event_type=NseIdentityEventType(raw_type.upper()),
                    effective_date=effective,
                    old_symbol=_upper(row.get("OLD_SYMBOL")),
                    new_symbol=_upper(row.get("NEW_SYMBOL")),
                    old_isin=_upper(row.get("OLD_ISIN")),
                    new_isin=_upper(row.get("NEW_ISIN")),
                    predecessor_security_id=row.get("PREDECESSOR_SECURITY_ID"),
                    successor_security_id=row.get("SUCCESSOR_SECURITY_ID"),
                    circular_reference=reference,
                    source_checksum=checksum,
                )
            )
        return tuple(
            sorted(
                events, key=lambda item: (item.effective_date, item.circular_reference)
            )
        )

    def parse_corporate_actions(
        self,
        payload: bytes,
        *,
        filename: str,
    ) -> tuple[NseCorporateActionRecord, ...]:
        checksum = hashlib.sha256(payload).hexdigest()
        text, member_name = _decode_archive(payload, filename)
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValueError("NSE corporate-action file has no header")
        records: list[NseCorporateActionRecord] = []
        for raw in reader:
            row = {_normalize_header(key): _clean(value) for key, value in raw.items()}
            symbol = row.get("SYMBOL") or row.get("TRADING_SYMBOL")
            purpose = row.get("PURPOSE") or row.get("ACTION_DESCRIPTION")
            if symbol is None or purpose is None:
                continue
            action_type = _corporate_action_type(purpose, row.get("ACTION_TYPE"))
            old_face, new_face = _face_values(purpose)
            records.append(
                NseCorporateActionRecord(
                    symbol=symbol.upper(),
                    series=_upper(row.get("SERIES")),
                    action_type=action_type,
                    purpose=purpose,
                    announcement_date=_parse_date(row.get("ANNOUNCEMENT_DATE")),
                    record_date=_parse_date(row.get("RECORD_DATE")),
                    ex_date=_parse_date(row.get("EX_DATE")),
                    effective_date=_parse_date(row.get("EFFECTIVE_DATE")),
                    old_face_value=(
                        _parse_decimal(row.get("OLD_FACE_VALUE")) or old_face
                    ),
                    new_face_value=(
                        _parse_decimal(row.get("NEW_FACE_VALUE")) or new_face
                    ),
                    bonus_ratio=row.get("BONUS_RATIO") or _ratio(purpose, "bonus"),
                    split_or_consolidation_ratio=(
                        row.get("SPLIT_RATIO") or _ratio(purpose, "split")
                    ),
                    rights_ratio=row.get("RIGHTS_RATIO") or _ratio(purpose, "rights"),
                    old_symbol=_upper(row.get("OLD_SYMBOL")),
                    new_symbol=_upper(row.get("NEW_SYMBOL")),
                    old_isin=_upper(row.get("OLD_ISIN")),
                    new_isin=_upper(row.get("NEW_ISIN")),
                    predecessor_security_id=row.get("PREDECESSOR_SECURITY_ID"),
                    successor_security_id=row.get("SUCCESSOR_SECURITY_ID"),
                    circular_reference=row.get("CIRCULAR_REFERENCE"),
                    source_filename=member_name,
                    source_checksum=checksum,
                    circular_only=_parse_bool(row.get("CIRCULAR_ONLY")) is True,
                )
            )
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.symbol,
                    item.event_date or date.min,
                    item.action_type.value,
                    item.purpose,
                ),
            )
        )


class NseIdentityProofEngine:
    def resolve(
        self,
        candidate: HistoricalSourceEvaluationManifestRecord,
        *,
        provider: UpstoxHistoricalCandidateEvidence | None,
        inspection: NseSecurityFileInspection | None,
        identity_events: Sequence[NseIdentityEventRecord] = (),
    ) -> NseIdentityProofRecord:
        base = _identity_base(candidate, provider)
        if inspection is None:
            chained = self._event_match(candidate, provider, identity_events, base)
            if chained is not None:
                return chained
            return NseIdentityProofRecord(
                **base,
                nse_permanent_identifier=None,
                nse_isin=None,
                nse_symbol=None,
                nse_series=None,
                source_filename=None,
                source_checksum=None,
                match_status=NseIdentityProofStatus.NSE_ARCHIVE_FILE_MISSING,
                provider_bridge_established=False,
                conflicts=(),
                explanation="No official dated NSE security artifact is available.",
            )
        if inspection.file_evidence.access_result not in {
            NseArchiveAccessResult.LOCAL_CACHE_AVAILABLE,
            NseArchiveAccessResult.RETRIEVED,
        }:
            return NseIdentityProofRecord(
                **base,
                nse_permanent_identifier=None,
                nse_isin=None,
                nse_symbol=None,
                nse_series=None,
                source_filename=inspection.file_evidence.filename,
                source_checksum=inspection.deterministic_checksum,
                match_status=NseIdentityProofStatus.NSE_ARCHIVE_FILE_MISSING,
                provider_bridge_established=False,
                conflicts=(inspection.file_evidence.access_result.value,),
                explanation="The dated NSE source could not be inspected.",
            )
        symbol = candidate.historical_symbol.upper()
        matches = tuple(
            item for item in inspection.records if item.trading_symbol == symbol
        )
        if not matches:
            chained = self._event_match(candidate, provider, identity_events, base)
            if chained is not None:
                return chained
            return NseIdentityProofRecord(
                **base,
                nse_permanent_identifier=None,
                nse_isin=None,
                nse_symbol=None,
                nse_series=None,
                source_filename=inspection.file_evidence.filename,
                source_checksum=inspection.deterministic_checksum,
                match_status=NseIdentityProofStatus.NSE_SYMBOL_NOT_FOUND,
                provider_bridge_established=False,
                conflicts=(),
                explanation="Historical symbol is absent from the dated NSE artifact.",
            )
        if all(item.current_state_only for item in matches):
            return _proof_from_source(
                base,
                matches[0],
                NseIdentityProofStatus.NSE_CURRENT_STATE_ONLY,
                "Only a current-state NSE security record is available.",
                provider,
            )
        candidate_matches = tuple(
            item
            for item in matches
            if item.as_of_date == candidate.candidate_date
            and item.valid_on(candidate.candidate_date)
        )
        if not candidate_matches:
            reason = "NSE listing/delisting interval does not cover candidate date."
            return _proof_from_source(
                base,
                matches[0],
                NseIdentityProofStatus.NSE_INTERVAL_AMBIGUOUS,
                reason,
                provider,
                conflicts=(reason,),
            )
        if any(item.suspension_indicator for item in candidate_matches):
            return _proof_from_source(
                base,
                candidate_matches[0],
                NseIdentityProofStatus.NSE_MANUAL_REVIEW_REQUIRED,
                "NSE record marks the security suspended on the candidate date.",
                provider,
                conflicts=("SUSPENDED_SECURITY",),
            )
        provider_series = _upper(provider.provider_series) if provider else None
        narrowed = candidate_matches
        if provider_series is not None:
            series_matches = tuple(
                item for item in narrowed if item.security_series == provider_series
            )
            if series_matches:
                narrowed = series_matches
        provider_isin = _upper(provider.isin) if provider else None
        if provider_isin is not None:
            isin_matches = tuple(
                item for item in narrowed if item.isin == provider_isin
            )
            if isin_matches:
                narrowed = isin_matches
        identities = {
            (
                item.security_series,
                item.isin,
                item.exchange_security_identifier,
            )
            for item in narrowed
        }
        if len(identities) > 1:
            same_security_different_series = (
                len({isin for _, isin, _ in identities}) == 1
                and len({security_id for _, _, security_id in identities}) == 1
            )
            return _proof_from_source(
                base,
                narrowed[0],
                (
                    NseIdentityProofStatus.NSE_INTERVAL_AMBIGUOUS
                    if same_security_different_series
                    else NseIdentityProofStatus.NSE_SOURCE_CONFLICT
                ),
                (
                    "Multiple NSE series share the same dated security identity, but "
                    "the candidate series was not retained."
                    if same_security_different_series
                    else "Multiple dated NSE records identify different securities."
                ),
                provider,
                conflicts=tuple(
                    sorted(
                        f"series={series or 'missing'};isin={isin or 'missing'};"
                        f"security_id={security_id or 'missing'}"
                        for series, isin, security_id in identities
                    )
                ),
            )
        source = narrowed[0]
        if source.security_series is None:
            return _proof_from_source(
                base,
                source,
                NseIdentityProofStatus.NSE_SERIES_MISSING,
                "Dated NSE record lacks security series.",
                provider,
            )
        if (
            source.exchange_security_identifier
            and provider
            and provider.provider_exchange_token == source.exchange_security_identifier
        ):
            return _proof_from_source(
                base,
                source,
                NseIdentityProofStatus.NSE_PERMANENT_ID_INTERVAL_MATCH,
                "Dated NSE exchange identifier matches the provider exchange token.",
                provider,
            )
        if source.isin and provider_isin and source.isin == provider_isin:
            return _proof_from_source(
                base,
                source,
                NseIdentityProofStatus.NSE_ISIN_INTERVAL_MATCH,
                "Dated NSE ISIN matches the provisional provider identity.",
                provider,
            )
        return _proof_from_source(
            base,
            source,
            NseIdentityProofStatus.NSE_SYMBOL_SERIES_DATE_MATCH,
            "Official dated NSE symbol and series establish candidate-date identity.",
            provider,
        )

    def build_report(
        self,
        records: Sequence[NseIdentityProofRecord],
    ) -> NseIdentityProofReport:
        ordered = tuple(
            sorted(records, key=lambda item: (item.candidate_date, item.candidate_id))
        )
        counts = Counter(item.match_status.value for item in ordered)
        authoritative = tuple(item for item in ordered if item.authoritative)
        return NseIdentityProofReport(
            report_version=NSE_ARCHIVE_PROOF_VERSION,
            proof_candidates=len(ordered),
            proof_unique_symbols=len({item.historical_symbol for item in ordered}),
            authoritative_matches=len(authoritative),
            unresolved_candidates=len(ordered) - len(authoritative),
            permanent_id_matches=counts[
                NseIdentityProofStatus.NSE_PERMANENT_ID_INTERVAL_MATCH.value
            ],
            isin_matches=counts[NseIdentityProofStatus.NSE_ISIN_INTERVAL_MATCH.value],
            symbol_series_matches=counts[
                NseIdentityProofStatus.NSE_SYMBOL_SERIES_DATE_MATCH.value
            ],
            rename_chain_matches=counts[
                NseIdentityProofStatus.NSE_RENAME_CHAIN_MATCH.value
            ],
            succession_chain_matches=counts[
                NseIdentityProofStatus.NSE_SUCCESSION_CHAIN_MATCH.value
            ],
            inactive_identities_resolved=sum(
                item.authoritative and item.inactive for item in ordered
            ),
            renamed_identities_resolved=sum(
                item.authoritative and item.renamed for item in ordered
            ),
            source_conflicts=counts[NseIdentityProofStatus.NSE_SOURCE_CONFLICT.value],
            status_counts=tuple(sorted(counts.items())),
            records=ordered,
        )

    def _event_match(
        self,
        candidate: HistoricalSourceEvaluationManifestRecord,
        provider: UpstoxHistoricalCandidateEvidence | None,
        events: Sequence[NseIdentityEventRecord],
        base: Mapping[str, Any],
    ) -> NseIdentityProofRecord | None:
        provider_symbol = _upper(provider.matched_symbol) if provider else None
        symbol = candidate.historical_symbol.upper()
        rename_matches = tuple(
            item
            for item in events
            if item.event_type is NseIdentityEventType.SYMBOL_CHANGE
            and item.old_symbol == symbol
            and provider_symbol == item.new_symbol
            and candidate.candidate_date < item.effective_date
        )
        if len(rename_matches) == 1:
            event = rename_matches[0]
            return NseIdentityProofRecord(
                **base,
                nse_permanent_identifier=event.successor_security_id,
                nse_isin=event.old_isin,
                nse_symbol=event.old_symbol,
                nse_series=None,
                source_filename=event.circular_reference,
                source_checksum=event.source_checksum,
                match_status=NseIdentityProofStatus.NSE_RENAME_CHAIN_MATCH,
                provider_bridge_established=provider is not None,
                conflicts=(),
                explanation=(
                    "Official NSE circular establishes the symbol-change chain."
                ),
            )
        succession = tuple(
            item
            for item in events
            if item.event_type
            in {
                NseIdentityEventType.SUCCESSION,
                NseIdentityEventType.MERGER,
                NseIdentityEventType.DEMERGER,
            }
            and item.old_symbol == symbol
            and candidate.candidate_date <= item.effective_date
            and (
                provider_symbol is None
                or item.new_symbol is None
                or provider_symbol == item.new_symbol
            )
        )
        if len(succession) == 1:
            event = succession[0]
            return NseIdentityProofRecord(
                **base,
                nse_permanent_identifier=event.predecessor_security_id,
                nse_isin=event.old_isin,
                nse_symbol=event.old_symbol,
                nse_series=None,
                source_filename=event.circular_reference,
                source_checksum=event.source_checksum,
                match_status=NseIdentityProofStatus.NSE_SUCCESSION_CHAIN_MATCH,
                provider_bridge_established=provider is not None,
                conflicts=(),
                explanation="Official NSE circular establishes security succession.",
            )
        return None


class NseCorporateActionProofEngine:
    def build(
        self,
        candidates: Sequence[HistoricalSourceEvaluationManifestRecord],
        *,
        actions: Sequence[NseCorporateActionRecord],
        identity_records: Mapping[str, NseIdentityProofRecord],
    ) -> NseCorporateActionProofReport:
        results = tuple(
            self._resolve(
                candidate, actions, identity_records.get(candidate.candidate_id)
            )
            for candidate in sorted(
                candidates, key=lambda item: (item.candidate_date, item.candidate_id)
            )
            if candidate.corporate_action_requirement
        )
        counts = Counter(item.status for item in results)
        return NseCorporateActionProofReport(
            report_version=NSE_ARCHIVE_PROOF_VERSION,
            cases_evaluated=len(results),
            events_found=sum(
                item.status is not NseCorporateActionProofStatus.NSE_CA_NOT_FOUND
                for item in results
            ),
            complete_cases=counts[
                NseCorporateActionProofStatus.NSE_CA_EVIDENCE_COMPLETE
            ],
            partial_cases=counts[
                NseCorporateActionProofStatus.NSE_CA_EVENT_FOUND_FIELDS_PARTIAL
            ],
            circular_only_cases=counts[
                NseCorporateActionProofStatus.NSE_CA_CIRCULAR_ONLY
            ],
            conflicts=counts[NseCorporateActionProofStatus.NSE_CA_CONFLICT],
            not_found=counts[NseCorporateActionProofStatus.NSE_CA_NOT_FOUND],
            records=results,
        )

    def _resolve(
        self,
        candidate: HistoricalSourceEvaluationManifestRecord,
        actions: Sequence[NseCorporateActionRecord],
        identity: NseIdentityProofRecord | None,
    ) -> NseCorporateActionProofRecord:
        matched = tuple(
            item
            for item in actions
            if item.symbol == candidate.historical_symbol.upper()
            and item.event_date is not None
            and candidate.required_start_date
            <= item.event_date
            <= candidate.candidate_date
        )
        if not matched:
            return NseCorporateActionProofRecord(
                candidate_id=candidate.candidate_id,
                candidate_date=candidate.candidate_date,
                symbol=candidate.historical_symbol,
                status=NseCorporateActionProofStatus.NSE_CA_NOT_FOUND,
                action_type=None,
                event_date=None,
                source_reference=None,
                source_checksum=None,
                fields_available=(),
                fields_missing=(
                    "action_type",
                    "event_date",
                    "official_reference",
                ),
                identity_authority_established=bool(
                    identity and identity.authoritative
                ),
                price_adjustment_authority_established=False,
                explanation=(
                    "No locally authorized NSE corporate-action record matched."
                ),
            )
        signatures = {
            (item.action_type, item.event_date, item.old_isin, item.new_isin)
            for item in matched
        }
        if len(signatures) > 1:
            return _ca_result(
                candidate,
                matched[0],
                identity,
                NseCorporateActionProofStatus.NSE_CA_CONFLICT,
                "Multiple NSE corporate-action records conflict for this interval.",
                complete=False,
            )
        action = matched[0]
        if action.circular_only:
            return _ca_result(
                candidate,
                action,
                identity,
                NseCorporateActionProofStatus.NSE_CA_CIRCULAR_ONLY,
                "An official circular exists but structured adjustment fields do not.",
                complete=False,
            )
        complete = _corporate_action_complete(action)
        return _ca_result(
            candidate,
            action,
            identity,
            (
                NseCorporateActionProofStatus.NSE_CA_EVIDENCE_COMPLETE
                if complete
                else NseCorporateActionProofStatus.NSE_CA_EVENT_FOUND_FIELDS_PARTIAL
            ),
            (
                "NSE action fields establish event and adjustment semantics."
                if complete
                else "NSE event exists but required adjustment fields are incomplete."
            ),
            complete=complete,
        )


def build_security_inspect_report(
    inspections: Sequence[NseSecurityFileInspection],
) -> NseSecurityFileInspectReport:
    ordered = tuple(
        sorted(
            inspections,
            key=lambda item: (
                item.file_evidence.archive_date,
                item.file_evidence.source_type.value,
            ),
        )
    )
    observed = Counter(item.schema_version.value for item in ordered)
    available = set().union(*(set(item.fields_available) for item in ordered))
    unavailable = set(_CANONICAL_SECURITY_FIELDS) - available
    return NseSecurityFileInspectReport(
        report_version=NSE_ARCHIVE_PROOF_VERSION,
        files_inspected=len(ordered),
        records_inspected=sum(len(item.records) for item in ordered),
        malformed_files=sum(
            item.file_evidence.access_result is NseArchiveAccessResult.MALFORMED_ARCHIVE
            for item in ordered
        ),
        malformed_rows=sum(item.malformed_rows for item in ordered),
        schema_versions_observed=tuple(sorted(observed.items())),
        fields_available=tuple(sorted(available)),
        fields_unavailable=tuple(sorted(unavailable)),
        inspections=ordered,
    )


def render_nse_archive_source_discovery(
    report: NseArchiveSourceDiscoveryReport,
) -> tuple[str, ...]:
    return (
        "NSE Archive Source Discovery",
        f"Date Scope: {report.requested_date_from} to {report.requested_date_to}",
        f"Official Source Types Catalogued: {len(report.source_definitions)}",
        f"Dates Requested: {report.dates_requested}",
        f"Dates with Local Official Bhavcopy: {report.dates_with_local_bhavcopy}",
        f"Dates Missing Bhavcopy: {report.dates_missing_bhavcopy}",
        f"Network Opt-In: {'yes' if report.network_opt_in else 'no'}",
        f"Network Requests: {report.network_requests}",
        "Access Results: " + _pairs(_counts(report.files, "access_result")),
        "File Types: "
        + ", ".join(item.source_type.value for item in report.source_definitions),
        "License / Retention: NSE terms prohibit systematic automated collection; "
        "electronic retention and redistribution require applicable permission.",
        "Retention or License Blocking: "
        f"{str(report.retention_or_license_blocking).lower()}",
        *tuple(f"Limitation: {item}" for item in report.limitations),
        "PRODUCTION_INFLUENCE=false",
    )


def render_nse_security_file_inspect(
    report: NseSecurityFileInspectReport,
) -> tuple[str, ...]:
    return (
        "NSE Historical Security-File Inspection",
        f"Files Inspected: {report.files_inspected}",
        f"Security Rows Inspected: {report.records_inspected}",
        f"Malformed Files / Rows: {report.malformed_files} / {report.malformed_rows}",
        "Schemas Observed: " + _pairs(report.schema_versions_observed),
        "Identity Fields Available: " + _values(report.fields_available),
        "Identity Fields Unavailable: " + _values(report.fields_unavailable),
        "Finding: dated bhavcopy proves symbol, series, ISIN, and exact "
        "candidate-date presence; it does not prove listing intervals or succession.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_nse_identity_proof(report: NseIdentityProofReport) -> tuple[str, ...]:
    return (
        "NSE Candidate-Date Identity Proof",
        f"Proof Candidates: {report.proof_candidates}",
        f"Proof Unique Symbols: {report.proof_unique_symbols}",
        f"Authoritative Matches: {report.authoritative_matches}",
        f"Unresolved Candidates: {report.unresolved_candidates}",
        f"Permanent ID Matches: {report.permanent_id_matches}",
        f"ISIN Matches: {report.isin_matches}",
        f"Symbol + Series + Date Matches: {report.symbol_series_matches}",
        f"Rename-Chain Matches: {report.rename_chain_matches}",
        f"Succession-Chain Matches: {report.succession_chain_matches}",
        f"Inactive Identities Resolved: {report.inactive_identities_resolved}",
        f"Renamed Identities Resolved: {report.renamed_identities_resolved}",
        f"Source Conflicts: {report.source_conflicts}",
        "Terminal Statuses: " + _pairs(report.status_counts),
        "Authority Boundary: only exact dated official NSE records or official "
        "effective-dated circular chains are authoritative.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_nse_corporate_action_proof(
    report: NseCorporateActionProofReport,
) -> tuple[str, ...]:
    return (
        "NSE Corporate-Action Proof",
        f"Cases Evaluated: {report.cases_evaluated}",
        f"Corporate-Action Cases Found: {report.events_found}",
        f"Complete Cases: {report.complete_cases}",
        f"Partial Cases: {report.partial_cases}",
        f"Circular-Only Cases: {report.circular_only_cases}",
        f"Conflicts: {report.conflicts}",
        f"Not Found in Authorized Local Evidence: {report.not_found}",
        "Identity / Adjustment Boundary: identity authority never clears the "
        "price-adjustment gate by itself.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_nse_archive_coverage(report: NseArchiveCoverageReport) -> tuple[str, ...]:
    return (
        "NSE Archive Empirical Coverage",
        "Proof Candidates Matched / Tested: "
        f"{report.proof_authoritative_matches} / {report.proof_candidates}",
        f"Proof Candidates Unresolved: {report.proof_unresolved_candidates}",
        "Unresolved Upstox Resolved / Tested: "
        f"{report.unresolved_upstox_candidates_resolved} / "
        f"{report.unresolved_upstox_candidates_tested}",
        "Provisional Upstox Confirmed / Tested: "
        f"{report.provisional_upstox_candidates_confirmed} / "
        f"{report.provisional_upstox_candidates_tested}",
        "Population Candidate-Date Matches / Candidates: "
        f"{report.full_population_authoritative_matches} / "
        f"{report.full_population_candidates}",
        f"Population Unresolved: {report.full_population_unresolved}",
        "Population Unique Symbols Resolved: "
        f"{report.full_population_unique_symbols_resolved}",
        "Empirical 657-Candidate Identity Coverage: "
        f"{report.projected_657_candidate_identity_coverage_percent}%",
        f"Security Files Available: {report.security_files_available}",
        f"Corporate-Action Files Available: {report.corporate_action_files_available}",
        f"Coverage Conclusion: {report.conclusion.value}",
        "Paid NSE Data Still Required: "
        f"{str(report.paid_nse_data_still_required).lower()}",
        *tuple(f"Limitation: {item}" for item in report.limitations),
        "PRODUCTION_INFLUENCE=false",
    )


def render_nse_archive_readiness(
    report: NseArchiveReadinessReport,
) -> tuple[str, ...]:
    return (
        "NSE Archive Readiness Simulation",
        f"Missing Candidate Manifest: {report.missing_candidate_manifest}",
        f"Current Authoritative Readiness: {report.current_authoritative_readiness}",
        f"Full Upstox Price Coverage: {report.full_upstox_price_coverage}",
        "Candidates Receiving NSE Identity: "
        f"{report.candidates_receiving_nse_identity}",
        f"Identity + Price Ready: {report.identity_and_price_ready}",
        f"Identity Ready, Price Blocked: {report.identity_ready_price_blocked}",
        f"Price Ready, Identity Blocked: {report.price_ready_identity_blocked}",
        "Identity + Price Ready, Corporate-Action Blocked: "
        f"{report.identity_and_price_ready_ca_blocked}",
        f"Still Identity Blocked: {report.candidates_still_identity_blocked}",
        f"Still Price Blocked: {report.candidates_still_price_blocked}",
        "Simulated Maximum after Identity Evidence: "
        f"{report.maximum_readiness_after_identity_evidence}",
        "Simulated Maximum after Identity + Corporate-Action Evidence: "
        f"{report.maximum_readiness_after_identity_and_corporate_action_evidence}",
        f"Actual Readiness, Unchanged: {report.actual_readiness_unchanged}",
        "Simulation Is Not Achieved Readiness: "
        f"{str(report.simulated_not_achieved).lower()}",
        f"Exact Next-Step Conclusion: {report.exact_next_step_conclusion}",
        "PRODUCTION_INFLUENCE=false",
    )


def export_nse_proof_json(value: Any, path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def export_nse_proof_csv(rows: Sequence[Any], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    flattened = tuple(_flatten(item) for item in rows)
    fields = sorted({key for item in flattened for key in item})
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flattened)


def official_bhavcopy_url(value: date) -> str:
    month = value.strftime("%b").upper()
    return (
        "https://archives.nseindia.com/content/historical/EQUITIES/"
        f"{value:%Y}/{month}/cm{value:%d}{month}{value:%Y}bhav.csv.zip"
    )


def validate_official_nse_url(url: str) -> None:
    if not url.startswith(_OFFICIAL_DOMAINS):
        raise ValueError("diagnostic retrieval is restricted to official NSE domains")


def _identity_base(
    candidate: HistoricalSourceEvaluationManifestRecord,
    provider: UpstoxHistoricalCandidateEvidence | None,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "candidate_date": candidate.candidate_date,
        "historical_symbol": candidate.historical_symbol.upper(),
        "manifest_exchange": "NSE",
        "manifest_series": None,
        "upstox_instrument_key": provider.instrument_key if provider else None,
        "upstox_symbol": provider.matched_symbol if provider else None,
        "upstox_isin": provider.isin if provider else None,
        "inactive": provider.inactive_security if provider else False,
        "renamed": provider.renamed_security if provider else False,
        "corporate_action_required": candidate.corporate_action_requirement,
        "full_price_coverage": provider.full_price_coverage if provider else False,
        "setup_type": candidate.setup_type,
        "entry_timing_state": provider.entry_timing_state if provider else None,
        "market_regime": candidate.market_regime,
        "recovery_population": candidate.recovery_population,
        "gap_cause": candidate.gap_cause.value,
    }


def _proof_from_source(
    base: Mapping[str, Any],
    source: NseSecurityRecord,
    status: NseIdentityProofStatus,
    explanation: str,
    provider: UpstoxHistoricalCandidateEvidence | None,
    *,
    conflicts: tuple[str, ...] = (),
) -> NseIdentityProofRecord:
    bridge = bool(
        provider
        and source.isin
        and provider.isin
        and source.isin == provider.isin.upper()
    )
    return NseIdentityProofRecord(
        **base,
        nse_permanent_identifier=source.exchange_security_identifier,
        nse_isin=source.isin,
        nse_symbol=source.trading_symbol,
        nse_series=source.security_series,
        source_filename=source.source_filename,
        source_checksum=source.source_checksum,
        match_status=status,
        provider_bridge_established=bridge,
        conflicts=conflicts,
        explanation=explanation,
    )


def _ca_result(
    candidate: HistoricalSourceEvaluationManifestRecord,
    action: NseCorporateActionRecord,
    identity: NseIdentityProofRecord | None,
    status: NseCorporateActionProofStatus,
    explanation: str,
    *,
    complete: bool,
) -> NseCorporateActionProofRecord:
    available = tuple(
        field
        for field in (
            "action_type",
            "announcement_date",
            "record_date",
            "ex_date",
            "effective_date",
            "old_face_value",
            "new_face_value",
            "bonus_ratio",
            "split_or_consolidation_ratio",
            "rights_ratio",
            "old_symbol",
            "new_symbol",
            "old_isin",
            "new_isin",
            "predecessor_security_id",
            "successor_security_id",
            "circular_reference",
        )
        if getattr(action, field) is not None
    )
    required = _required_ca_fields(action.action_type)
    missing = tuple(field for field in required if field not in available)
    return NseCorporateActionProofRecord(
        candidate_id=candidate.candidate_id,
        candidate_date=candidate.candidate_date,
        symbol=candidate.historical_symbol,
        status=status,
        action_type=action.action_type,
        event_date=action.event_date,
        source_reference=action.circular_reference or action.source_filename,
        source_checksum=action.source_checksum,
        fields_available=available,
        fields_missing=missing,
        identity_authority_established=bool(identity and identity.authoritative),
        price_adjustment_authority_established=complete,
        explanation=explanation,
    )


def _required_ca_fields(action_type: NseCorporateActionType) -> tuple[str, ...]:
    common = ("action_type", "effective_date", "circular_reference")
    if action_type is NseCorporateActionType.BONUS:
        return (*common, "bonus_ratio")
    if action_type in {
        NseCorporateActionType.SPLIT,
        NseCorporateActionType.CONSOLIDATION,
    }:
        return (*common, "old_face_value", "new_face_value")
    if action_type is NseCorporateActionType.RIGHTS:
        return (*common, "rights_ratio")
    if action_type in {
        NseCorporateActionType.MERGER,
        NseCorporateActionType.DEMERGER,
    }:
        return (*common, "predecessor_security_id", "successor_security_id")
    return common


def _corporate_action_complete(action: NseCorporateActionRecord) -> bool:
    available = {
        field
        for field in _required_ca_fields(action.action_type)
        if getattr(action, field) is not None
    }
    return len(available) == len(_required_ca_fields(action.action_type))


def _decode_archive(payload: bytes, filename: str) -> tuple[str, str]:
    if payload.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members = tuple(
                    item
                    for item in archive.namelist()
                    if item.lower().endswith((".csv", ".txt"))
                    and not item.endswith("/")
                )
                if not members:
                    raise ValueError("NSE ZIP contains no CSV or text member")
                member = sorted(members)[0]
                return _decode_text(archive.read(member)), member
        except zipfile.BadZipFile as exc:
            raise ValueError("malformed NSE ZIP archive") from exc
    if payload.startswith(b"\x1f\x8b") or filename.lower().endswith(".gz"):
        try:
            name = Path(filename).name.removesuffix(".gz")
            return _decode_text(gzip.decompress(payload)), name
        except (OSError, EOFError) as exc:
            raise ValueError("malformed NSE GZIP archive") from exc
    return _decode_text(payload), Path(filename).name


def _decode_text(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("NSE archive text encoding is unsupported")


def _looks_pipe_delimited(text: str) -> bool:
    first = text.splitlines()[0] if text.splitlines() else ""
    return first.count("|") > first.count(",")


def _security_schema(
    source_type: NseArchiveSourceType,
    headers: set[str],
    *,
    delimiter: str,
) -> NseSecuritySchemaVersion:
    if source_type is NseArchiveSourceType.CM_MII_SECURITY_FILE:
        return NseSecuritySchemaVersion.MII_CM_SECURITY_V1
    if source_type is NseArchiveSourceType.CM_NEAT_SECURITY_FILE or delimiter == "|":
        return NseSecuritySchemaVersion.NEAT_CM_SECURITY_V1
    if "TCKRSYMB" in headers or "FININSTRMID" in headers:
        return NseSecuritySchemaVersion.UDIFF_CM_BHAVCOPY_V1
    if "SYMBOL" in headers and "SERIES" in headers:
        return NseSecuritySchemaVersion.LEGACY_CM_BHAVCOPY_V1
    return NseSecuritySchemaVersion.UNKNOWN


def _normalize_header(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")


def _get_alias(row: Mapping[str, str | None], aliases: Sequence[str]) -> str | None:
    for alias in aliases:
        value = row.get(_normalize_header(alias))
        if value is not None:
            return value
    return None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.upper() in {"NA", "N/A", "NULL", "-"}:
        return None
    return cleaned


def _upper(value: str | None) -> str | None:
    return value.upper() if value else None


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    for pattern in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    raise ValueError(f"malformed NSE date: {value}")


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"malformed NSE decimal: {value}") from exc


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized in {"1", "Y", "YES", "TRUE", "ACTIVE", "PERMITTED"}:
        return True
    if normalized in {"0", "N", "NO", "FALSE", "INACTIVE", "NOT_PERMITTED"}:
        return False
    return None


def _corporate_action_type(
    purpose: str,
    explicit: str | None,
) -> NseCorporateActionType:
    value = (explicit or purpose).lower()
    for token, action_type in (
        ("demerger", NseCorporateActionType.DEMERGER),
        ("merger", NseCorporateActionType.MERGER),
        ("consolidat", NseCorporateActionType.CONSOLIDATION),
        ("split", NseCorporateActionType.SPLIT),
        ("sub-division", NseCorporateActionType.SPLIT),
        ("bonus", NseCorporateActionType.BONUS),
        ("rights", NseCorporateActionType.RIGHTS),
        ("symbol", NseCorporateActionType.SYMBOL_CHANGE),
        ("isin", NseCorporateActionType.ISIN_CHANGE),
        ("dividend", NseCorporateActionType.DIVIDEND),
    ):
        if token in value:
            return action_type
    return NseCorporateActionType.OTHER


def _face_values(purpose: str) -> tuple[Decimal | None, Decimal | None]:
    values = re.findall(r"(?:RS\.?|INR)\s*(\d+(?:\.\d+)?)", purpose.upper())
    if len(values) < 2:
        return None, None
    return Decimal(values[0]), Decimal(values[1])


def _ratio(purpose: str, keyword: str) -> str | None:
    if keyword not in purpose.lower():
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)", purpose)
    return f"{match.group(1)}:{match.group(2)}" if match else None


def _counts(values: Sequence[Any], field: str) -> tuple[tuple[str, int], ...]:
    counts = Counter(getattr(item, field).value for item in values)
    return tuple(sorted(counts.items()))


def _pairs(values: Sequence[tuple[str, int]]) -> str:
    return ", ".join(f"{name}={count}" for name, count in values) or "none"


def _values(values: Sequence[str]) -> str:
    return ", ".join(values) or "none"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime, Decimal, StrEnum)):
        return str(value)
    return value


def _flatten(value: Any) -> dict[str, str]:
    payload = _jsonable(value)
    if not isinstance(payload, dict):
        return {"value": json.dumps(payload, sort_keys=True)}
    result: dict[str, str] = {}
    for key, item in payload.items():
        if isinstance(item, (dict, list)):
            result[key] = json.dumps(item, separators=(",", ":"), sort_keys=True)
        elif item is None:
            result[key] = ""
        else:
            result[key] = str(item)
    return result
