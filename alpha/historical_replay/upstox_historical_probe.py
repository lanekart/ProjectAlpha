from __future__ import annotations

import csv
import json
import os
import time
import urllib.parse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv

from alpha.historical_replay.historical_source_evaluation import (
    HistoricalSourceEvaluationManifest,
    HistoricalSourceEvaluationManifestRecord,
    HistoricalSourceSampleManifest,
)
from alpha.market_truth.provider_transport import (
    MarketTruthNetworkError,
    ReadOnlyProviderTransport,
)

UPSTOX_HISTORICAL_PROBE_VERSION = "upstox-historical-evidence-probe-v1"
UPSTOX_HISTORICAL_EVIDENCE_VERSION = "upstox-historical-evidence-dataset-v1"
UPSTOX_INSTRUMENT_SEARCH_URL = "https://api.upstox.com/v2/instruments/search"
UPSTOX_INSTRUMENT_SEARCH_DEFAULT_RECORDS = 10
UPSTOX_INSTRUMENT_SEARCH_MIN_RECORDS = 1
UPSTOX_INSTRUMENT_SEARCH_MAX_RECORDS = 30
UPSTOX_HISTORICAL_V3_BASE_URL = "https://api.upstox.com/v3/historical-candle"
UPSTOX_ANALYTICS_TOKEN_DOC_URL = (
    "https://upstox.com/developer/api-documentation/analytics-token/"
)
UPSTOX_HISTORICAL_V3_DOC_URL = (
    "https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/"
)
UPSTOX_INSTRUMENT_SEARCH_DOC_URL = (
    "https://upstox.com/developer/api-documentation/instrument-search/"
)
DEFAULT_UPSTOX_HISTORICAL_EVIDENCE_PATH = Path(
    ".alpha/upstox_historical_evidence_v1.json"
)
PRODUCTION_INFLUENCE = False

_ALLOWED_HOST = "api.upstox.com"
_ALLOWED_PATHS = (
    "/v2/instruments/search",
    "/v3/historical-candle/",
)
_IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
_ZERO = Decimal("0")
_FOUR = Decimal("0.0001")


class UpstoxProbeCredentialStatus(StrEnum):
    CREDENTIALS_NOT_CONFIGURED = "CREDENTIALS_NOT_CONFIGURED"
    CONFIGURED_REDACTED = "CONFIGURED_REDACTED"


class UpstoxAuthProbeStatus(StrEnum):
    TOKEN_NOT_CONFIGURED = "TOKEN_NOT_CONFIGURED"
    TOKEN_ACCEPTED = "TOKEN_ACCEPTED"
    TOKEN_REJECTED = "TOKEN_REJECTED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    ENDPOINT_FORBIDDEN = "ENDPOINT_FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTOX_UNAVAILABLE = "UPSTOX_UNAVAILABLE"
    PROBE_NOT_RUN = "PROBE_NOT_RUN"
    PROBE_ERROR = "PROBE_ERROR"


class UpstoxEndpointProbeStatus(StrEnum):
    ACCESSIBLE = "ACCESSIBLE"
    NOT_TESTED = "NOT_TESTED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class UpstoxProbeErrorCategory(StrEnum):
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    ENDPOINT_FORBIDDEN = "ENDPOINT_FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT_PROVIDER_ERROR = "TRANSIENT_PROVIDER_ERROR"
    PERSISTENT_PROVIDER_ERROR = "PERSISTENT_PROVIDER_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INSTRUMENT_SEARCH_PAGE_SIZE_INVALID = "INSTRUMENT_SEARCH_PAGE_SIZE_INVALID"
    ENDPOINT_NOT_ALLOWED = "ENDPOINT_NOT_ALLOWED"


class UpstoxIdentityMatchMethod(StrEnum):
    AUTHORITATIVE_INSTRUMENT_KEY = "AUTHORITATIVE_INSTRUMENT_KEY"
    ISIN = "ISIN"
    HISTORICAL_SYMBOL_EFFECTIVE_INTERVAL = "HISTORICAL_SYMBOL_EFFECTIVE_INTERVAL"
    UPSTOX_INSTRUMENT_SEARCH = "UPSTOX_INSTRUMENT_SEARCH"
    OFFICIAL_INSTRUMENT_FILE = "OFFICIAL_INSTRUMENT_FILE"
    UNRESOLVED = "UNRESOLVED"


class UpstoxIdentityConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class UpstoxIdentityStatus(StrEnum):
    RESOLVED_AUTHORITATIVE = "RESOLVED_AUTHORITATIVE"
    RESOLVED_PROVISIONAL_FOR_PRICE_PROBE = "RESOLVED_PROVISIONAL_FOR_PRICE_PROBE"
    CURRENT_SYMBOL_ONLY_REJECTED = "CURRENT_SYMBOL_ONLY_REJECTED"
    HISTORICAL_CONTINUITY_UNPROVEN = "HISTORICAL_CONTINUITY_UNPROVEN"
    AMBIGUOUS = "AMBIGUOUS"
    INSTRUMENT_NOT_FOUND = "INSTRUMENT_NOT_FOUND"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"


class UpstoxCoverageClassification(StrEnum):
    FULL_PRICE_COVERAGE = "FULL_PRICE_COVERAGE"
    PARTIAL_PRICE_COVERAGE = "PARTIAL_PRICE_COVERAGE"
    INSUFFICIENT_LOOKBACK = "INSUFFICIENT_LOOKBACK"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    HISTORICAL_SYMBOL_UNAVAILABLE = "HISTORICAL_SYMBOL_UNAVAILABLE"
    INSTRUMENT_NOT_FOUND = "INSTRUMENT_NOT_FOUND"
    CANDIDATE_WINDOW_MISSING = "CANDIDATE_WINDOW_MISSING"
    MULTI_SESSION_GAPS = "MULTI_SESSION_GAPS"
    INVALID_SERIES = "INVALID_SERIES"
    RATE_LIMITED = "RATE_LIMITED"
    RATE_LIMITED_UNRESOLVED = "RATE_LIMITED_UNRESOLVED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PROVIDER_ERROR_UNRESOLVED = "PROVIDER_ERROR_UNRESOLVED"
    NOT_TESTED = "NOT_TESTED"


class UpstoxSeriesDefect(StrEnum):
    DUPLICATE_SESSION = "DUPLICATE_SESSION"
    INVALID_OHLC_RELATIONSHIP = "INVALID_OHLC_RELATIONSHIP"
    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
    NEGATIVE_VOLUME = "NEGATIVE_VOLUME"
    TIMEZONE_MISMATCH = "TIMEZONE_MISMATCH"
    NON_TRADING_SESSION = "NON_TRADING_SESSION"
    OUT_OF_ORDER_BARS = "OUT_OF_ORDER_BARS"
    POST_CUTOFF_CONTAMINATION = "POST_CUTOFF_CONTAMINATION"
    MIXED_ADJUSTMENT_EVIDENCE = "MIXED_ADJUSTMENT_EVIDENCE"
    MALFORMED_TIMESTAMP = "MALFORMED_TIMESTAMP"
    INSUFFICIENT_VALID_BARS_AFTER_FILTERING = "INSUFFICIENT_VALID_BARS_AFTER_FILTERING"
    UNKNOWN_SERIES_DEFECT = "UNKNOWN_SERIES_DEFECT"


class UpstoxAdjustmentStatus(StrEnum):
    RAW_SERIES_CONFIRMED = "RAW_SERIES_CONFIRMED"
    ADJUSTED_SERIES_CONFIRMED = "ADJUSTED_SERIES_CONFIRMED"
    ADJUSTMENT_UNDOCUMENTED = "ADJUSTMENT_UNDOCUMENTED"
    ADJUSTMENT_INCONSISTENT = "ADJUSTMENT_INCONSISTENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class UpstoxCorporateActionStatus(StrEnum):
    CORPORATE_ACTION_EVIDENCE_REQUIRED = "CORPORATE_ACTION_EVIDENCE_REQUIRED"
    AUTHORITATIVE_CASE_CONSISTENT = "AUTHORITATIVE_CASE_CONSISTENT"
    CONFLICTING_CORPORATE_ACTION_EVIDENCE = "CONFLICTING_CORPORATE_ACTION_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class UpstoxRecommendedSourceRole(StrEnum):
    EMPIRICAL_TRIAL_ONLY = "EMPIRICAL_TRIAL_ONLY"
    SECONDARY_PRICE_VALIDATION = "SECONDARY_PRICE_VALIDATION"
    LIMITED_SECONDARY_PRICE_VALIDATION = "LIMITED_SECONDARY_PRICE_VALIDATION"
    NOT_USEFUL_FOR_HISTORICAL_RECOVERY = "NOT_USEFUL_FOR_HISTORICAL_RECOVERY"
    NOT_SUITABLE = "NOT_SUITABLE"


class UpstoxProbeConclusion(StrEnum):
    UPSTOX_PRICE_SOURCE_PROMISING = "UPSTOX_PRICE_SOURCE_PROMISING"
    UPSTOX_SUITABLE_AS_SECONDARY_VALIDATION = "UPSTOX_SUITABLE_AS_SECONDARY_VALIDATION"
    UPSTOX_HISTORY_TOO_SHALLOW = "UPSTOX_HISTORY_TOO_SHALLOW"
    UPSTOX_IDENTITY_COVERAGE_INSUFFICIENT = "UPSTOX_IDENTITY_COVERAGE_INSUFFICIENT"
    UPSTOX_CORPORATE_ACTION_EVIDENCE_INSUFFICIENT = (
        "UPSTOX_CORPORATE_ACTION_EVIDENCE_INSUFFICIENT"
    )
    UPSTOX_CREDENTIALS_NOT_CONFIGURED = "UPSTOX_CREDENTIALS_NOT_CONFIGURED"
    UPSTOX_EMPIRICAL_EVIDENCE_INSUFFICIENT = "UPSTOX_EMPIRICAL_EVIDENCE_INSUFFICIENT"
    UPSTOX_TRIAL_BLOCKED = "UPSTOX_TRIAL_BLOCKED"
    UPSTOX_SECONDARY_PRICE_SOURCE_USEFUL = "UPSTOX_SECONDARY_PRICE_SOURCE_USEFUL"
    UPSTOX_SECONDARY_PRICE_SOURCE_LIMITED = "UPSTOX_SECONDARY_PRICE_SOURCE_LIMITED"
    UPSTOX_PRICE_COVERAGE_TOO_LOW = "UPSTOX_PRICE_COVERAGE_TOO_LOW"
    UPSTOX_PRICE_COVERAGE_YEAR_BIASED = "UPSTOX_PRICE_COVERAGE_YEAR_BIASED"
    UPSTOX_IDENTITY_LIMITS_DOMINATE = "UPSTOX_IDENTITY_LIMITS_DOMINATE"
    UPSTOX_CORPORATE_ACTION_LIMITS_DOMINATE = "UPSTOX_CORPORATE_ACTION_LIMITS_DOMINATE"
    UPSTOX_OPERATIONALLY_UNRELIABLE = "UPSTOX_OPERATIONALLY_UNRELIABLE"
    UPSTOX_FULL_TRIAL_INCOMPLETE = "UPSTOX_FULL_TRIAL_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class UpstoxAnalyticsTokenConfig:
    token: str | None = field(repr=False, compare=False)

    @classmethod
    def from_environment(cls) -> UpstoxAnalyticsTokenConfig:
        load_dotenv(override=False)
        value = os.environ.get("UPSTOX_ANALYTICS_TOKEN")
        token = value.strip() if value and value.strip() else None
        return cls(token=token)

    @property
    def credential_status(self) -> UpstoxProbeCredentialStatus:
        return (
            UpstoxProbeCredentialStatus.CONFIGURED_REDACTED
            if self.token
            else UpstoxProbeCredentialStatus.CREDENTIALS_NOT_CONFIGURED
        )


@dataclass(frozen=True, slots=True)
class UpstoxProbeHttpResponse:
    payload: Mapping[str, Any]
    http_status: int
    diagnostic_headers: Mapping[str, str]


class UpstoxProbeHttpError(ValueError):
    def __init__(
        self,
        *,
        category: UpstoxProbeErrorCategory,
        http_status: int | None,
        provider_error_code: str | None,
        sanitized_message: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.category = category
        self.http_status = http_status
        self.provider_error_code = provider_error_code
        self.sanitized_message = sanitized_message
        self.retry_after_seconds = retry_after_seconds
        status = "HTTP unavailable" if http_status is None else f"HTTP {http_status}"
        code = provider_error_code or "provider code unavailable"
        super().__init__(f"{category.value} ({status}, {code}): {sanitized_message}")


class UpstoxHistoricalProbeTransport(Protocol):
    def get_json(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> UpstoxProbeHttpResponse: ...


class UrlLibUpstoxHistoricalProbeTransport:
    """GET-only transport restricted to two documented market-data endpoints."""

    def __init__(self) -> None:
        self._transport = ReadOnlyProviderTransport()

    def get_json(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> UpstoxProbeHttpResponse:
        _assert_allowed_read_only_url(url)
        token = _authorization_token(headers)
        try:
            response = self._transport.get(
                url,
                headers=dict(headers),
                timeout_seconds=20,
            )
        except MarketTruthNetworkError as exc:
            raise UpstoxProbeHttpError(
                category=UpstoxProbeErrorCategory.NETWORK_ERROR,
                http_status=None,
                provider_error_code=None,
                sanitized_message=(
                    f"Upstox request failed with {exc.__class__.__name__}."
                ),
            ) from None
        body = response.body.decode("utf-8")
        status = response.status
        diagnostics = _safe_headers(dict(response.headers))
        if status >= 400:
            code, message = _provider_error(body)
            sanitized = _redact(
                message or f"Upstox request failed with HTTP {status}.",
                token,
            )
            raise UpstoxProbeHttpError(
                category=_http_error_category(
                    status,
                    sanitized,
                    provider_error_code=code,
                ),
                http_status=status,
                provider_error_code=code,
                sanitized_message=sanitized,
                retry_after_seconds=_retry_after(dict(response.headers)),
            ) from None
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise UpstoxProbeHttpError(
                category=UpstoxProbeErrorCategory.INVALID_RESPONSE,
                http_status=status,
                provider_error_code=None,
                sanitized_message="Upstox returned a non-JSON response.",
            ) from exc
        if not isinstance(payload, dict):
            raise UpstoxProbeHttpError(
                category=UpstoxProbeErrorCategory.INVALID_RESPONSE,
                http_status=status,
                provider_error_code=None,
                sanitized_message="Upstox returned an unexpected JSON response.",
            )
        return UpstoxProbeHttpResponse(
            payload=payload,
            http_status=status,
            diagnostic_headers=diagnostics,
        )


@dataclass(frozen=True, slots=True)
class UpstoxAuthProbeResult:
    credential_status: UpstoxProbeCredentialStatus
    status: UpstoxAuthProbeStatus
    instrument_search_status: UpstoxEndpointProbeStatus
    historical_candle_status: UpstoxEndpointProbeStatus
    analytics_token_only: bool
    account_endpoint_called: bool
    order_endpoint_called: bool
    static_ip_required_for_selected_endpoints: bool
    http_status: int | None
    provider_error_code: str | None
    reason: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class UpstoxInstrumentRecord:
    instrument_key: str
    trading_symbol: str
    isin: str | None
    exchange: str
    segment: str | None
    instrument_type: str | None
    source: str
    exchange_token: str | None = None
    security_type: str | None = None
    series: str | None = None

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        source: str,
    ) -> UpstoxInstrumentRecord | None:
        key = _optional_text(payload.get("instrument_key"))
        symbol = _optional_text(
            payload.get("trading_symbol")
            or payload.get("tradingsymbol")
            or payload.get("symbol")
        )
        if key is None or symbol is None:
            return None
        exchange = _optional_text(payload.get("exchange")) or key.split("_", 1)[0]
        return cls(
            instrument_key=key,
            trading_symbol=symbol.upper(),
            isin=_optional_text(payload.get("isin")),
            exchange=exchange.upper(),
            segment=_optional_text(payload.get("segment")),
            instrument_type=_optional_text(payload.get("instrument_type")),
            source=source,
            exchange_token=_optional_text(payload.get("exchange_token")),
            security_type=_optional_text(payload.get("security_type")),
            series=_optional_text(payload.get("series")),
        )


@dataclass(frozen=True, slots=True)
class UpstoxIdentityHint:
    authoritative_instrument_key: str | None = None
    isin: str | None = None
    effective_historical_symbol: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    renamed_security: bool = False


@dataclass(frozen=True, slots=True)
class UpstoxIdentityResolution:
    candidate_id: str
    requested_historical_symbol: str
    matched_symbol: str | None
    isin: str | None
    instrument_key: str | None
    match_method: UpstoxIdentityMatchMethod
    match_confidence: UpstoxIdentityConfidence
    status: UpstoxIdentityStatus
    active_status: str
    historical_continuity_evidence: str
    ambiguity_reason: str | None
    price_probe_eligible: bool
    identity_confirmed: bool
    renamed_security: bool
    inactive_security: bool
    provider_exchange: str | None = None
    provider_segment: str | None = None
    provider_series: str | None = None
    provider_exchange_token: str | None = None
    provider_security_type: str | None = None
    provider_instrument_type: str | None = None
    provider_metadata_source: str | None = None
    identity_search_query: str | None = None
    identity_search_page_size: int | None = None


@dataclass(frozen=True, slots=True)
class UpstoxCandle:
    observed_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class UpstoxCandleBatch:
    candles: tuple[UpstoxCandle, ...]
    malformed_rows: int
    http_status: int
    response_checksum: str
    malformed_timestamp_rows: int = 0


@dataclass(frozen=True, slots=True)
class UpstoxCorporateActionCase:
    effective_date: date
    split_or_bonus_factor: Decimal
    authoritative: bool
    conflicting_evidence: bool = False


@dataclass(frozen=True, slots=True)
class UpstoxAdjustmentAssessment:
    adjustment_status: UpstoxAdjustmentStatus
    corporate_action_status: UpstoxCorporateActionStatus
    cases_evaluated: int
    volume_consistency: bool | None
    explanation: str


@dataclass(frozen=True, slots=True)
class UpstoxHistoricalCandidateEvidence:
    candidate_id: str
    candidate_date: date
    replay_year: int
    gap_cause: str
    setup_type: str | None
    market_regime: str | None
    entry_timing_state: str | None
    requested_historical_symbol: str
    matched_symbol: str | None
    isin: str | None
    instrument_key: str | None
    identity_match_method: UpstoxIdentityMatchMethod
    identity_confidence: UpstoxIdentityConfidence
    identity_status: UpstoxIdentityStatus
    active_status: str
    historical_continuity_evidence: str
    identity_ambiguity_reason: str | None
    price_probe_eligible: bool
    identity_confirmed: bool
    renamed_security: bool
    inactive_security: bool
    requested_start_date: date
    requested_end_date: date
    returned_start_date: date | None
    returned_end_date: date | None
    returned_bar_count: int
    usable_pre_candidate_bars: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    duplicate_sessions: int
    missing_sessions: int | None
    missing_session_rate: Decimal | None
    invalid_ohlc_rows: int
    negative_volume_rows: int
    volume_complete: bool
    timezone_consistent: bool
    candidate_date_included: bool
    future_bars_excluded: int
    sufficient_lookback: bool
    coverage_classification: UpstoxCoverageClassification
    http_status: int | None
    error_category: UpstoxProbeErrorCategory | None
    provider_error_code: str | None
    response_checksum: str | None
    response_checksum_retention: str
    request_configuration_hash: str
    adjustment_status: UpstoxAdjustmentStatus
    corporate_action_status: UpstoxCorporateActionStatus
    explanation: str
    raw_bars_returned: int = 0
    pre_cutoff_bars: int = 0
    normalized_bars: int = 0
    integrity_valid_bars: int = 0
    required_valid_bars: int = 121
    rejected_bars: int = 0
    has_sufficient_raw_lookback: bool = False
    has_sufficient_pre_cutoff_lookback: bool = False
    has_sufficient_valid_lookback: bool = False
    full_price_coverage: bool = False
    primary_series_defect: UpstoxSeriesDefect | None = None
    secondary_series_defects: tuple[UpstoxSeriesDefect, ...] = ()
    invalid_ohlc_relationship_rows: int = 0
    non_positive_price_rows: int = 0
    malformed_timestamp_rows: int = 0
    non_trading_session_rows: int = 0
    out_of_order_rows: int = 0
    provider_exchange: str | None = None
    provider_segment: str | None = None
    provider_series: str | None = None
    provider_exchange_token: str | None = None
    provider_security_type: str | None = None
    provider_instrument_type: str | None = None
    provider_metadata_source: str | None = None
    identity_search_query: str | None = None
    identity_search_page_size: int | None = None
    production_influence: bool = PRODUCTION_INFLUENCE

    def sanitized_for_persistence(self) -> UpstoxHistoricalCandidateEvidence:
        return replace(
            self,
            response_checksum=None,
            response_checksum_retention="NOT_RETAINED_TERMS_UNCLEAR",
        )


@dataclass(frozen=True, slots=True)
class UpstoxOperationalMetrics:
    total_network_requests: int = 0
    successful_requests: int = 0
    authentication_failures: int = 0
    rate_limit_responses: int = 0
    transient_failures: int = 0
    permanent_failures: int = 0
    retries: int = 0
    elapsed_seconds: Decimal = _ZERO
    request_rate_per_second: Decimal | None = None
    token_exposure_incidents: int = 0
    account_endpoint_calls: int = 0
    order_endpoint_calls: int = 0


@dataclass(frozen=True, slots=True)
class UpstoxHistoricalEvidenceDataset:
    dataset_version: str
    probe_version: str
    source_manifest_version: str
    source_manifest_checksum: str
    sample_checksum: str
    scope: str
    credential_status: UpstoxProbeCredentialStatus
    authentication_status: UpstoxAuthProbeStatus
    records: tuple[UpstoxHistoricalCandidateEvidence, ...]
    operational_metrics: UpstoxOperationalMetrics = field(
        default_factory=UpstoxOperationalMetrics
    )
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class UpstoxHistoricalEvidenceReport:
    probe_version: str
    credential_status: UpstoxProbeCredentialStatus
    authentication_status: UpstoxAuthProbeStatus
    manifest_candidates: int
    trial_candidates: int
    historical_symbols_tested: int
    instruments_resolved: int
    instruments_unresolved: int
    active_symbol_resolution: int
    historical_symbol_resolution: int
    inactive_symbol_resolution: int
    renamed_symbol_resolution: int
    candidates_with_121_raw_bars: int
    candidates_with_121_pre_cutoff_bars: int
    candidates_with_121_integrity_valid_bars: int
    full_price_coverage_candidates: int
    candidates_with_121_usable_bars: int
    candidates_with_partial_history: int
    candidates_with_no_history: int
    candidates_2016_tested: int
    candidates_2016_full_price_coverage: int
    candidates_2016_with_121_bars: int
    later_year_candidates_tested: int
    later_year_full_price_coverage: int
    later_year_candidates_with_121_bars: int
    missing_session_rate: Decimal | None
    invalid_series_count: int
    adjustment_conclusion: UpstoxAdjustmentStatus
    corporate_action_conclusion: UpstoxCorporateActionStatus
    observed_price_coverage_rate: Decimal | None
    projected_price_coverage: Decimal | None
    terminal_status_total: int
    terminal_statuses_reconcile: bool
    full_reconstruction_readiness: str
    selection_bias_implication: str
    recommended_source_role: UpstoxRecommendedSourceRole
    conclusion: UpstoxProbeConclusion
    sample_composition: tuple[tuple[str, int], ...]
    limitations: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


class UpstoxReadOnlyHistoricalClient:
    def __init__(
        self,
        *,
        config: UpstoxAnalyticsTokenConfig | None = None,
        transport: UpstoxHistoricalProbeTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        minimum_request_interval: float = 0.13,
        max_retries: int = 2,
        max_network_requests: int = 1900,
    ) -> None:
        self.config = config or UpstoxAnalyticsTokenConfig.from_environment()
        self.transport = transport or UrlLibUpstoxHistoricalProbeTransport()
        self.sleep = sleep
        self.monotonic = monotonic
        self.minimum_request_interval = max(0.0, minimum_request_interval)
        self.max_retries = max(0, max_retries)
        self.max_network_requests = max(1, max_network_requests)
        self._last_request_at: float | None = None
        self._first_request_at: float | None = None
        self._request_count = 0
        self._success_count = 0
        self._authentication_failures = 0
        self._rate_limit_responses = 0
        self._transient_failures = 0
        self._permanent_failures = 0
        self._retry_count = 0

    def operational_metrics(self) -> UpstoxOperationalMetrics:
        now = self.monotonic()
        elapsed = (
            max(0.0, now - self._first_request_at)
            if self._first_request_at is not None
            else 0.0
        )
        elapsed_decimal = Decimal(str(round(elapsed, 3)))
        rate = (
            (Decimal(self._request_count) / elapsed_decimal).quantize(_FOUR)
            if elapsed_decimal > _ZERO
            else None
        )
        return UpstoxOperationalMetrics(
            total_network_requests=self._request_count,
            successful_requests=self._success_count,
            authentication_failures=self._authentication_failures,
            rate_limit_responses=self._rate_limit_responses,
            transient_failures=self._transient_failures,
            permanent_failures=self._permanent_failures,
            retries=self._retry_count,
            elapsed_seconds=elapsed_decimal,
            request_rate_per_second=rate,
        )

    def authentication_probe(
        self,
        *,
        live: bool,
        as_of: date | None = None,
    ) -> UpstoxAuthProbeResult:
        credential = self.config.credential_status
        if self.config.token is None:
            return _auth_result(
                credential=credential,
                status=UpstoxAuthProbeStatus.TOKEN_NOT_CONFIGURED,
                reason="UPSTOX_ANALYTICS_TOKEN is not configured.",
            )
        if not live:
            return _auth_result(
                credential=credential,
                status=UpstoxAuthProbeStatus.PROBE_NOT_RUN,
                reason="No network call made; pass --live to probe read-only APIs.",
            )
        try:
            search = self.search_instruments("NIFTY 50")
        except UpstoxProbeHttpError as exc:
            return _auth_error_result(credential, exc, instrument_search=True)
        probe_end = as_of or date.today()
        probe_start = probe_end - timedelta(days=14)
        try:
            self.historical_candles(
                "NSE_INDEX|Nifty 50",
                from_date=probe_start,
                to_date=probe_end,
            )
        except UpstoxProbeHttpError as exc:
            result = _auth_error_result(credential, exc, instrument_search=False)
            return replace(
                result,
                instrument_search_status=UpstoxEndpointProbeStatus.ACCESSIBLE,
            )
        return UpstoxAuthProbeResult(
            credential_status=credential,
            status=UpstoxAuthProbeStatus.TOKEN_ACCEPTED,
            instrument_search_status=UpstoxEndpointProbeStatus.ACCESSIBLE,
            historical_candle_status=UpstoxEndpointProbeStatus.ACCESSIBLE,
            analytics_token_only=True,
            account_endpoint_called=False,
            order_endpoint_called=False,
            static_ip_required_for_selected_endpoints=False,
            http_status=search.http_status,
            provider_error_code=None,
            reason=(
                "Analytics Token accepted by Instrument Search and Historical "
                "Candle V3; only documented read-only market-data GETs were used."
            ),
        )

    def search_instruments(
        self,
        query: str,
        *,
        records: int = UPSTOX_INSTRUMENT_SEARCH_DEFAULT_RECORDS,
    ) -> UpstoxProbeHttpResponse:
        _validate_instrument_search_records(records)
        params = urllib.parse.urlencode(
            {
                "query": query,
                "exchanges": "NSE",
                "segments": "EQ",
                "page_number": "1",
                "records": str(records),
            }
        )
        return self._get(f"{UPSTOX_INSTRUMENT_SEARCH_URL}?{params}")

    def historical_candles(
        self,
        instrument_key: str,
        *,
        from_date: date,
        to_date: date,
    ) -> UpstoxCandleBatch:
        encoded_key = urllib.parse.quote(instrument_key, safe="")
        url = (
            f"{UPSTOX_HISTORICAL_V3_BASE_URL}/{encoded_key}/days/1/"
            f"{to_date.isoformat()}/{from_date.isoformat()}"
        )
        response = self._get(url)
        return _parse_candle_response(response)

    def _get(self, url: str) -> UpstoxProbeHttpResponse:
        token = self.config.token
        if token is None:
            raise UpstoxProbeHttpError(
                category=UpstoxProbeErrorCategory.AUTHENTICATION_FAILED,
                http_status=None,
                provider_error_code=None,
                sanitized_message="UPSTOX_ANALYTICS_TOKEN is not configured.",
            )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "ProjectAlpha/1.0 UpstoxHistoricalEvidenceProbe",
            "Connection": "close",
        }
        for attempt in range(self.max_retries + 1):
            if self._request_count >= self.max_network_requests:
                raise UpstoxProbeHttpError(
                    category=UpstoxProbeErrorCategory.RATE_LIMITED,
                    http_status=None,
                    provider_error_code="LOCAL_REQUEST_BUDGET_EXHAUSTED",
                    sanitized_message=(
                        "Conservative read-only request budget exhausted before "
                        "the documented rolling provider limit."
                    ),
                )
            self._throttle()
            self._request_count += 1
            if self._first_request_at is None:
                self._first_request_at = self.monotonic()
            try:
                response = self.transport.get_json(url, headers)
                self._success_count += 1
                return response
            except UpstoxProbeHttpError as exc:
                self._record_failure(exc.category)
                if exc.category in {
                    UpstoxProbeErrorCategory.AUTHENTICATION_FAILED,
                    UpstoxProbeErrorCategory.TOKEN_EXPIRED,
                    UpstoxProbeErrorCategory.ENDPOINT_FORBIDDEN,
                    UpstoxProbeErrorCategory.ENDPOINT_NOT_ALLOWED,
                }:
                    raise
                retryable = exc.category in {
                    UpstoxProbeErrorCategory.RATE_LIMITED,
                    UpstoxProbeErrorCategory.TRANSIENT_PROVIDER_ERROR,
                    UpstoxProbeErrorCategory.NETWORK_ERROR,
                }
                if not retryable or attempt >= self.max_retries:
                    if (
                        retryable
                        and exc.category is not UpstoxProbeErrorCategory.RATE_LIMITED
                    ):
                        raise UpstoxProbeHttpError(
                            category=UpstoxProbeErrorCategory.PERSISTENT_PROVIDER_ERROR,
                            http_status=exc.http_status,
                            provider_error_code=exc.provider_error_code,
                            sanitized_message=exc.sanitized_message,
                        ) from None
                    raise
                self._retry_count += 1
                delay = exc.retry_after_seconds or float(2**attempt)
                self.sleep(min(max(delay, 0.0), 30.0))
        raise AssertionError("unreachable retry loop")

    def _throttle(self) -> None:
        now = self.monotonic()
        if self._last_request_at is not None:
            wait = self.minimum_request_interval - (now - self._last_request_at)
            if wait > 0:
                self.sleep(wait)
                now = self.monotonic()
        self._last_request_at = now

    def _record_failure(self, category: UpstoxProbeErrorCategory) -> None:
        if category in {
            UpstoxProbeErrorCategory.AUTHENTICATION_FAILED,
            UpstoxProbeErrorCategory.TOKEN_EXPIRED,
            UpstoxProbeErrorCategory.ENDPOINT_FORBIDDEN,
        }:
            self._authentication_failures += 1
        elif category is UpstoxProbeErrorCategory.RATE_LIMITED:
            self._rate_limit_responses += 1
        elif category in {
            UpstoxProbeErrorCategory.TRANSIENT_PROVIDER_ERROR,
            UpstoxProbeErrorCategory.NETWORK_ERROR,
        }:
            self._transient_failures += 1
        else:
            self._permanent_failures += 1


class UpstoxIdentityResolver:
    """Resolve historical identities without treating a current symbol as history."""

    def resolve(
        self,
        record: HistoricalSourceEvaluationManifestRecord,
        *,
        search_response: Mapping[str, Any] | None = None,
        official_instruments: Sequence[UpstoxInstrumentRecord] = (),
        hint: UpstoxIdentityHint | None = None,
    ) -> UpstoxIdentityResolution:
        identity_hint = hint or UpstoxIdentityHint()
        inactive = record.continuity_status != "ACTIVE_TO_SOURCE_END"
        active_status = "INACTIVE_OR_ENDED" if inactive else "ACTIVE_TO_SOURCE_END"
        searched = _instrument_records(search_response, source="INSTRUMENT_SEARCH")
        available = _deduplicate_instruments((*searched, *official_instruments))

        if identity_hint.authoritative_instrument_key:
            match = next(
                (
                    item
                    for item in available
                    if item.instrument_key == identity_hint.authoritative_instrument_key
                ),
                None,
            )
            return _resolved_identity(
                record,
                match=match,
                instrument_key=identity_hint.authoritative_instrument_key,
                method=UpstoxIdentityMatchMethod.AUTHORITATIVE_INSTRUMENT_KEY,
                confidence=UpstoxIdentityConfidence.HIGH,
                status=UpstoxIdentityStatus.RESOLVED_AUTHORITATIVE,
                continuity="Existing authoritative instrument key.",
                confirmed=True,
                inactive=inactive,
                renamed=identity_hint.renamed_security,
                active_status=active_status,
            )

        if identity_hint.isin:
            isin_matches = tuple(
                item
                for item in available
                if item.isin and item.isin.upper() == identity_hint.isin.upper()
            )
            if len(isin_matches) == 1:
                return _resolved_identity(
                    record,
                    match=isin_matches[0],
                    method=UpstoxIdentityMatchMethod.ISIN,
                    confidence=UpstoxIdentityConfidence.HIGH,
                    status=UpstoxIdentityStatus.RESOLVED_AUTHORITATIVE,
                    continuity="Exact ISIN match from an official Upstox source.",
                    confirmed=True,
                    inactive=inactive,
                    renamed=identity_hint.renamed_security,
                    active_status=active_status,
                )
            if len(isin_matches) > 1:
                return _unresolved_identity(
                    record,
                    status=UpstoxIdentityStatus.AMBIGUOUS,
                    reason="Multiple Upstox instruments share the requested ISIN.",
                    inactive=inactive,
                    renamed=identity_hint.renamed_security,
                    active_status=active_status,
                )

        historical_symbol = (
            identity_hint.effective_historical_symbol or record.historical_symbol
        ).upper()
        effective = (
            identity_hint.effective_historical_symbol is not None
            and _date_in_interval(
                record.candidate_date,
                identity_hint.effective_from,
                identity_hint.effective_to,
            )
        )
        exact = tuple(
            item for item in available if item.trading_symbol == historical_symbol
        )
        if len(exact) > 1:
            return _unresolved_identity(
                record,
                status=UpstoxIdentityStatus.AMBIGUOUS,
                reason="Multiple exact historical-symbol instruments were returned.",
                inactive=inactive,
                renamed=identity_hint.renamed_security,
                active_status=active_status,
            )
        if len(exact) == 1:
            match = exact[0]
            if effective:
                return _resolved_identity(
                    record,
                    match=match,
                    method=(
                        UpstoxIdentityMatchMethod.HISTORICAL_SYMBOL_EFFECTIVE_INTERVAL
                    ),
                    confidence=UpstoxIdentityConfidence.HIGH,
                    status=UpstoxIdentityStatus.RESOLVED_AUTHORITATIVE,
                    continuity="Historical symbol is valid for the effective interval.",
                    confirmed=True,
                    inactive=inactive,
                    renamed=identity_hint.renamed_security,
                    active_status=active_status,
                )
            source_method = (
                UpstoxIdentityMatchMethod.UPSTOX_INSTRUMENT_SEARCH
                if match.source == "INSTRUMENT_SEARCH"
                else UpstoxIdentityMatchMethod.OFFICIAL_INSTRUMENT_FILE
            )
            return _resolved_identity(
                record,
                match=match,
                method=source_method,
                confidence=UpstoxIdentityConfidence.MEDIUM,
                status=(UpstoxIdentityStatus.RESOLVED_PROVISIONAL_FOR_PRICE_PROBE),
                continuity=(
                    "Exact historical symbol found, but no effective-dated alias "
                    "or security-master interval proves historical continuity."
                ),
                confirmed=False,
                inactive=inactive,
                renamed=identity_hint.renamed_security,
                active_status=active_status,
            )

        current_symbol = (
            record.current_symbol.upper() if record.current_symbol else None
        )
        current_matches = tuple(
            item
            for item in available
            if current_symbol is not None and item.trading_symbol == current_symbol
        )
        if current_matches:
            return _unresolved_identity(
                record,
                status=UpstoxIdentityStatus.CURRENT_SYMBOL_ONLY_REJECTED,
                reason=(
                    "Only the current symbol matched; no effective-dated continuity "
                    "evidence supports the historical interval."
                ),
                inactive=inactive,
                renamed=identity_hint.renamed_security,
                active_status=active_status,
            )
        return _unresolved_identity(
            record,
            status=UpstoxIdentityStatus.INSTRUMENT_NOT_FOUND,
            reason="No exact historical symbol or authoritative identifier matched.",
            inactive=inactive,
            renamed=identity_hint.renamed_security,
            active_status=active_status,
        )


class UpstoxHistoricalCandleValidator:
    def evaluate(
        self,
        record: HistoricalSourceEvaluationManifestRecord,
        identity: UpstoxIdentityResolution,
        *,
        batch: UpstoxCandleBatch | None = None,
        error: UpstoxProbeHttpError | None = None,
        adjustment: UpstoxAdjustmentAssessment | None = None,
        entry_timing_state: str | None = None,
        exchange_sessions: Sequence[date] | None = None,
    ) -> UpstoxHistoricalCandidateEvidence:
        request_hash = _request_configuration_hash(record, identity.instrument_key)
        assessment = adjustment or UpstoxAdjustmentAssessment(
            adjustment_status=UpstoxAdjustmentStatus.INSUFFICIENT_EVIDENCE,
            corporate_action_status=(
                UpstoxCorporateActionStatus.CORPORATE_ACTION_EVIDENCE_REQUIRED
                if record.corporate_action_requirement
                else UpstoxCorporateActionStatus.INSUFFICIENT_EVIDENCE
            ),
            cases_evaluated=0,
            volume_consistency=None,
            explanation="No authoritative corporate-action case was evaluated.",
        )
        if error is not None:
            return _empty_candidate_evidence(
                record,
                identity,
                entry_timing_state=entry_timing_state,
                classification=_coverage_for_error(error.category),
                request_hash=request_hash,
                adjustment=assessment,
                explanation=error.sanitized_message,
                error=error,
            )
        if not identity.price_probe_eligible:
            classification = (
                UpstoxCoverageClassification.INSTRUMENT_NOT_FOUND
                if identity.status is UpstoxIdentityStatus.INSTRUMENT_NOT_FOUND
                else UpstoxCoverageClassification.IDENTITY_UNRESOLVED
            )
            return _empty_candidate_evidence(
                record,
                identity,
                entry_timing_state=entry_timing_state,
                classification=classification,
                request_hash=request_hash,
                adjustment=assessment,
                explanation=identity.ambiguity_reason or "Identity unresolved.",
            )
        if batch is None:
            return _empty_candidate_evidence(
                record,
                identity,
                entry_timing_state=entry_timing_state,
                classification=UpstoxCoverageClassification.NOT_TESTED,
                request_hash=request_hash,
                adjustment=assessment,
                explanation="Historical Candle V3 was not called.",
            )

        raw_bars = len(batch.candles) + batch.malformed_rows
        original = batch.candles
        ordered = tuple(sorted(original, key=lambda item: item.observed_at))
        returned_dates = tuple(item.observed_at.date() for item in ordered)
        cutoff_rows = tuple(
            item
            for item in ordered
            if item.observed_at.date() <= record.required_end_date
            and item.observed_at.date() < record.candidate_date
        )
        cutoff_dates = tuple(item.observed_at.date() for item in cutoff_rows)
        duplicate_sessions = len(cutoff_dates) - len(set(cutoff_dates))
        timezone_consistent = all(
            item.observed_at.utcoffset() == _IST.utcoffset(None) for item in ordered
        )
        non_positive_prices = sum(_has_non_positive_price(item) for item in cutoff_rows)
        invalid_relationships = sum(
            not _has_non_positive_price(item) and not _valid_ohlc(item)
            for item in cutoff_rows
        )
        invalid_ohlc = (
            batch.malformed_rows + non_positive_prices + invalid_relationships
        )
        negative_volume = sum(item.volume < _ZERO for item in cutoff_rows)
        expected = (
            tuple(
                day
                for day in exchange_sessions
                if record.required_start_date <= day <= record.required_end_date
            )
            if exchange_sessions is not None
            else None
        )
        expected_set = set(expected) if expected is not None else None
        non_trading_sessions = sum(
            expected_set is not None and candle.observed_at.date() not in expected_set
            for candle in cutoff_rows
        )
        valid_by_date: dict[date, UpstoxCandle] = {}
        for candle in cutoff_rows:
            if (
                _valid_ohlc(candle)
                and candle.volume >= _ZERO
                and candle.observed_at.utcoffset() == _IST.utcoffset(None)
                and (expected_set is None or candle.observed_at.date() in expected_set)
            ):
                valid_by_date.setdefault(candle.observed_at.date(), candle)
        integrity_valid = tuple(valid_by_date.values())
        missing = (
            len(set(expected) - set(valid_by_date)) if expected is not None else None
        )
        missing_rate = (
            _ratio_decimal(missing, len(set(expected)))
            if missing is not None and expected
            else None
        )
        candidate_included = any(day >= record.candidate_date for day in returned_dates)
        future_excluded = sum(
            day > record.required_end_date or day >= record.candidate_date
            for day in returned_dates
        )
        has_raw = raw_bars >= record.minimum_bars_required
        has_pre_cutoff = len(cutoff_rows) >= record.minimum_bars_required
        has_valid = len(integrity_valid) >= record.minimum_bars_required
        defects = _series_defects(
            malformed_rows=batch.malformed_rows,
            malformed_timestamp_rows=batch.malformed_timestamp_rows,
            non_positive_prices=non_positive_prices,
            invalid_ohlc_relationships=invalid_relationships,
            negative_volume_rows=negative_volume,
            timezone_mismatch=not timezone_consistent,
            non_trading_sessions=non_trading_sessions,
            irregular_order=_has_irregular_bar_order(original),
            duplicate_sessions=duplicate_sessions,
            post_cutoff_bars=future_excluded,
            mixed_adjustment=(
                assessment.adjustment_status
                is UpstoxAdjustmentStatus.ADJUSTMENT_INCONSISTENT
            ),
            insufficient_after_filtering=(has_pre_cutoff and not has_valid),
        )
        primary_defect = defects[0] if defects else None
        secondary_defects = defects[1:] if defects else ()
        classification = _coverage_classification(
            valid_bars=len(integrity_valid),
            minimum_bars=record.minimum_bars_required,
            missing_sessions=missing,
            defects=defects,
        )
        full_price_coverage = (
            identity.price_probe_eligible
            and classification is UpstoxCoverageClassification.FULL_PRICE_COVERAGE
        )
        return UpstoxHistoricalCandidateEvidence(
            candidate_id=record.candidate_id,
            candidate_date=record.candidate_date,
            replay_year=record.replay_year,
            gap_cause=record.gap_cause.value,
            setup_type=record.setup_type,
            market_regime=record.market_regime,
            entry_timing_state=entry_timing_state,
            requested_historical_symbol=record.historical_symbol,
            matched_symbol=identity.matched_symbol,
            isin=identity.isin,
            instrument_key=identity.instrument_key,
            identity_match_method=identity.match_method,
            identity_confidence=identity.match_confidence,
            identity_status=identity.status,
            active_status=identity.active_status,
            historical_continuity_evidence=identity.historical_continuity_evidence,
            identity_ambiguity_reason=identity.ambiguity_reason,
            price_probe_eligible=identity.price_probe_eligible,
            identity_confirmed=identity.identity_confirmed,
            renamed_security=identity.renamed_security,
            inactive_security=identity.inactive_security,
            requested_start_date=record.required_start_date,
            requested_end_date=record.required_end_date,
            returned_start_date=min(returned_dates, default=None),
            returned_end_date=max(returned_dates, default=None),
            returned_bar_count=raw_bars,
            usable_pre_candidate_bars=len(integrity_valid),
            first_timestamp=ordered[0].observed_at if ordered else None,
            last_timestamp=ordered[-1].observed_at if ordered else None,
            duplicate_sessions=duplicate_sessions,
            missing_sessions=missing,
            missing_session_rate=missing_rate,
            invalid_ohlc_rows=invalid_ohlc,
            negative_volume_rows=negative_volume,
            volume_complete=negative_volume == 0 and bool(cutoff_rows),
            timezone_consistent=timezone_consistent,
            candidate_date_included=candidate_included,
            future_bars_excluded=future_excluded,
            sufficient_lookback=has_valid,
            coverage_classification=classification,
            http_status=batch.http_status,
            error_category=None,
            provider_error_code=None,
            response_checksum=batch.response_checksum,
            response_checksum_retention="IN_MEMORY_ONLY_TERMS_UNCLEAR",
            request_configuration_hash=request_hash,
            adjustment_status=assessment.adjustment_status,
            corporate_action_status=assessment.corporate_action_status,
            explanation=_coverage_explanation(
                classification,
                raw=raw_bars,
                pre_cutoff=len(cutoff_rows),
                normalized=len(cutoff_rows),
                valid=len(integrity_valid),
                missing=missing,
                primary_defect=primary_defect,
            ),
            raw_bars_returned=raw_bars,
            pre_cutoff_bars=len(cutoff_rows),
            normalized_bars=len(cutoff_rows),
            integrity_valid_bars=len(integrity_valid),
            required_valid_bars=record.minimum_bars_required,
            rejected_bars=max(0, raw_bars - len(integrity_valid)),
            has_sufficient_raw_lookback=has_raw,
            has_sufficient_pre_cutoff_lookback=has_pre_cutoff,
            has_sufficient_valid_lookback=has_valid,
            full_price_coverage=full_price_coverage,
            primary_series_defect=primary_defect,
            secondary_series_defects=secondary_defects,
            invalid_ohlc_relationship_rows=invalid_relationships,
            non_positive_price_rows=non_positive_prices,
            malformed_timestamp_rows=batch.malformed_timestamp_rows,
            non_trading_session_rows=non_trading_sessions,
            out_of_order_rows=1 if _has_irregular_bar_order(original) else 0,
            provider_exchange=identity.provider_exchange,
            provider_segment=identity.provider_segment,
            provider_series=identity.provider_series,
            provider_exchange_token=identity.provider_exchange_token,
            provider_security_type=identity.provider_security_type,
            provider_instrument_type=identity.provider_instrument_type,
            provider_metadata_source=identity.provider_metadata_source,
            identity_search_query=identity.identity_search_query,
            identity_search_page_size=identity.identity_search_page_size,
        )


class UpstoxAdjustmentAuditEngine:
    """Classify only against explicit authoritative corporate-action cases."""

    def evaluate(
        self,
        candles: Sequence[UpstoxCandle],
        cases: Sequence[UpstoxCorporateActionCase],
    ) -> UpstoxAdjustmentAssessment:
        authoritative = tuple(item for item in cases if item.authoritative)
        if not authoritative:
            return UpstoxAdjustmentAssessment(
                adjustment_status=UpstoxAdjustmentStatus.ADJUSTMENT_UNDOCUMENTED,
                corporate_action_status=(
                    UpstoxCorporateActionStatus.CORPORATE_ACTION_EVIDENCE_REQUIRED
                ),
                cases_evaluated=0,
                volume_consistency=None,
                explanation=(
                    "Upstox price and volume adjustment semantics are not proven "
                    "without an authoritative effective-dated corporate-action case."
                ),
            )
        if any(item.conflicting_evidence for item in authoritative):
            return UpstoxAdjustmentAssessment(
                adjustment_status=UpstoxAdjustmentStatus.ADJUSTMENT_INCONSISTENT,
                corporate_action_status=(
                    UpstoxCorporateActionStatus.CONFLICTING_CORPORATE_ACTION_EVIDENCE
                ),
                cases_evaluated=len(authoritative),
                volume_consistency=None,
                explanation="Authoritative corporate-action evidence conflicts.",
            )
        votes: list[UpstoxAdjustmentStatus] = []
        volume_checks: list[bool] = []
        for case in authoritative:
            before, after = _candles_around(candles, case.effective_date)
            if before is None or after is None or after.close_price == _ZERO:
                continue
            price_ratio = before.close_price / after.close_price
            if _approximately(price_ratio, case.split_or_bonus_factor):
                votes.append(UpstoxAdjustmentStatus.RAW_SERIES_CONFIRMED)
                volume_checks.append(
                    before.volume == _ZERO
                    or _approximately(
                        after.volume / before.volume,
                        case.split_or_bonus_factor,
                        tolerance=Decimal("0.50"),
                    )
                )
            elif _approximately(price_ratio, Decimal("1")):
                votes.append(UpstoxAdjustmentStatus.ADJUSTED_SERIES_CONFIRMED)
                volume_checks.append(True)
            else:
                votes.append(UpstoxAdjustmentStatus.ADJUSTMENT_INCONSISTENT)
        if not votes:
            return UpstoxAdjustmentAssessment(
                adjustment_status=UpstoxAdjustmentStatus.INSUFFICIENT_EVIDENCE,
                corporate_action_status=UpstoxCorporateActionStatus.INSUFFICIENT_EVIDENCE,
                cases_evaluated=0,
                volume_consistency=None,
                explanation="No corporate-action case had observations on both sides.",
            )
        unique = set(votes)
        volume_consistent = all(volume_checks) if volume_checks else None
        if len(unique) != 1 or volume_consistent is False:
            status = UpstoxAdjustmentStatus.ADJUSTMENT_INCONSISTENT
            corporate = (
                UpstoxCorporateActionStatus.CONFLICTING_CORPORATE_ACTION_EVIDENCE
            )
        else:
            status = votes[0]
            corporate = UpstoxCorporateActionStatus.AUTHORITATIVE_CASE_CONSISTENT
        return UpstoxAdjustmentAssessment(
            adjustment_status=status,
            corporate_action_status=corporate,
            cases_evaluated=len(votes),
            volume_consistency=volume_consistent,
            explanation=(
                f"Observed {len(votes)} authoritative case(s); price classification "
                f"is {status.value} and volume consistency is "
                f"{_display_optional_bool(volume_consistent)}."
            ),
        )


class UpstoxHistoricalEvidenceRepository:
    def __init__(self, path: Path | str = DEFAULT_UPSTOX_HISTORICAL_EVIDENCE_PATH):
        self.path = Path(path)

    def save(self, dataset: UpstoxHistoricalEvidenceDataset) -> None:
        safe = replace(
            dataset,
            records=tuple(item.sanitized_for_persistence() for item in dataset.records),
        )
        payload = json.dumps(
            _jsonable(safe), sort_keys=True, indent=2, separators=(",", ": ")
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def load(self) -> UpstoxHistoricalEvidenceDataset | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Upstox evidence dataset must be a JSON object")
        return _dataset_from_payload(payload)


class UpstoxHistoricalEvidenceReportEngine:
    def build(
        self,
        *,
        manifest: HistoricalSourceEvaluationManifest,
        sample: HistoricalSourceSampleManifest,
        dataset: UpstoxHistoricalEvidenceDataset | None,
        entry_timing_by_candidate: Mapping[str, str | None] | None = None,
    ) -> UpstoxHistoricalEvidenceReport:
        records = dataset.records if dataset is not None else ()
        tested = tuple(
            item
            for item in records
            if item.coverage_classification
            is not UpstoxCoverageClassification.NOT_TESTED
        )
        full = tuple(
            item
            for item in tested
            if item.coverage_classification
            is UpstoxCoverageClassification.FULL_PRICE_COVERAGE
        )
        raw_sufficient = tuple(
            item for item in tested if item.has_sufficient_raw_lookback
        )
        pre_cutoff_sufficient = tuple(
            item for item in tested if item.has_sufficient_pre_cutoff_lookback
        )
        valid_sufficient = tuple(
            item for item in tested if item.has_sufficient_valid_lookback
        )
        partial_statuses = {
            UpstoxCoverageClassification.PARTIAL_PRICE_COVERAGE,
            UpstoxCoverageClassification.INSUFFICIENT_LOOKBACK,
        }
        partial = tuple(
            item for item in tested if item.coverage_classification in partial_statuses
        )
        no_history_statuses = {
            UpstoxCoverageClassification.CANDIDATE_WINDOW_MISSING,
            UpstoxCoverageClassification.HISTORICAL_SYMBOL_UNAVAILABLE,
            UpstoxCoverageClassification.INSTRUMENT_NOT_FOUND,
            UpstoxCoverageClassification.IDENTITY_UNRESOLVED,
        }
        no_history = tuple(
            item
            for item in tested
            if item.coverage_classification in no_history_statuses
        )
        terminal_status_total = sum(
            Counter(item.coverage_classification for item in tested).values()
        )
        resolved = tuple(item for item in tested if item.instrument_key is not None)
        known_missing = tuple(
            item for item in tested if item.missing_sessions is not None
        )
        missing_total = sum(item.missing_sessions or 0 for item in known_missing)
        expected_total = sum(
            (item.missing_sessions or 0) + item.usable_pre_candidate_bars
            for item in known_missing
        )
        observed_rate = _ratio_decimal(len(full), len(tested)) if tested else None
        projected = (
            observed_rate
            if dataset is not None
            and dataset.scope == "FULL_POPULATION"
            and len(tested) == len(manifest.records)
            else None
        )
        adjustment = _aggregate_adjustment(tested)
        corporate = _aggregate_corporate_action(tested)
        identity_complete = bool(tested) and all(
            item.identity_confirmed for item in tested
        )
        price_complete = bool(tested) and len(full) == len(tested)
        corporate_complete = (
            corporate is UpstoxCorporateActionStatus.AUTHORITATIVE_CASE_CONSISTENT
        )
        readiness = (
            "READY_FOR_DIAGNOSTIC_RECONSTRUCTION_ONLY"
            if price_complete and identity_complete and corporate_complete
            else "BLOCKED_IDENTITY_CORPORATE_ACTION_OR_COVERAGE_INCOMPLETE"
        )
        credential = (
            dataset.credential_status
            if dataset is not None
            else UpstoxAnalyticsTokenConfig.from_environment().credential_status
        )
        authentication = (
            dataset.authentication_status
            if dataset is not None
            else UpstoxAuthProbeStatus.PROBE_NOT_RUN
        )
        conclusion, role = _report_conclusion(
            credential=credential,
            authentication=authentication,
            tested=len(tested),
            observed_rate=observed_rate,
            identity_complete=identity_complete,
            corporate_complete=corporate_complete,
            population_complete=(
                dataset is not None
                and dataset.scope == "FULL_POPULATION"
                and len(tested) == len(manifest.records)
            ),
        )
        composition = _sample_composition(
            sample.records,
            records,
            entry_timing_by_candidate=entry_timing_by_candidate or {},
        )
        return UpstoxHistoricalEvidenceReport(
            probe_version=UPSTOX_HISTORICAL_PROBE_VERSION,
            credential_status=credential,
            authentication_status=authentication,
            manifest_candidates=len(manifest.records),
            trial_candidates=len(tested),
            historical_symbols_tested=len(
                {item.requested_historical_symbol for item in tested}
            ),
            instruments_resolved=len(resolved),
            instruments_unresolved=len(tested) - len(resolved),
            active_symbol_resolution=sum(
                item.instrument_key is not None and not item.inactive_security
                for item in tested
            ),
            historical_symbol_resolution=sum(
                item.instrument_key is not None
                and item.matched_symbol == item.requested_historical_symbol
                for item in tested
            ),
            inactive_symbol_resolution=sum(
                item.instrument_key is not None and item.inactive_security
                for item in tested
            ),
            renamed_symbol_resolution=sum(
                item.instrument_key is not None and item.renamed_security
                for item in tested
            ),
            candidates_with_121_raw_bars=len(raw_sufficient),
            candidates_with_121_pre_cutoff_bars=len(pre_cutoff_sufficient),
            candidates_with_121_integrity_valid_bars=len(valid_sufficient),
            full_price_coverage_candidates=len(full),
            candidates_with_121_usable_bars=len(valid_sufficient),
            candidates_with_partial_history=len(partial),
            candidates_with_no_history=len(no_history),
            candidates_2016_tested=sum(item.replay_year == 2016 for item in tested),
            candidates_2016_full_price_coverage=sum(
                item.replay_year == 2016
                and item.coverage_classification
                is UpstoxCoverageClassification.FULL_PRICE_COVERAGE
                for item in tested
            ),
            candidates_2016_with_121_bars=sum(
                item.replay_year == 2016
                and item.coverage_classification
                is UpstoxCoverageClassification.FULL_PRICE_COVERAGE
                for item in tested
            ),
            later_year_candidates_tested=sum(
                item.replay_year > 2016 for item in tested
            ),
            later_year_full_price_coverage=sum(
                item.replay_year > 2016
                and item.coverage_classification
                is UpstoxCoverageClassification.FULL_PRICE_COVERAGE
                for item in tested
            ),
            later_year_candidates_with_121_bars=sum(
                item.replay_year > 2016
                and item.coverage_classification
                is UpstoxCoverageClassification.FULL_PRICE_COVERAGE
                for item in tested
            ),
            missing_session_rate=(
                _ratio_decimal(missing_total, expected_total)
                if expected_total
                else None
            ),
            invalid_series_count=sum(
                item.coverage_classification
                is UpstoxCoverageClassification.INVALID_SERIES
                for item in tested
            ),
            adjustment_conclusion=adjustment,
            corporate_action_conclusion=corporate,
            observed_price_coverage_rate=observed_rate,
            projected_price_coverage=projected,
            terminal_status_total=terminal_status_total,
            terminal_statuses_reconcile=terminal_status_total == len(tested),
            full_reconstruction_readiness=readiness,
            selection_bias_implication=(
                f"The full {len(manifest.records)}/{len(manifest.records)} manifest "
                f"was observed: {len(full)} candidates have full price coverage. "
                "Coverage is materially year-biased, and identity plus "
                "corporate-action authority remain separate blockers."
                if dataset is not None
                and dataset.scope == "FULL_POPULATION"
                and len(tested) == len(manifest.records)
                else "The deterministic stratified sample includes difficult "
                "historical cases, but it is not a probability sample; do not "
                "project its coverage unless the full manifest is tested."
            ),
            recommended_source_role=role,
            conclusion=conclusion,
            sample_composition=composition,
            limitations=(
                "Price coverage is separate from identity and corporate-action "
                "readiness.",
                "Missing-session rates are unavailable without an authoritative "
                "exchange calendar.",
                "Response rows and checksums are not persisted because storage "
                "terms remain unverified.",
                "PRODUCTION_INFLUENCE=false; Upstox is not registered as a "
                "production provider.",
            ),
        )


def render_upstox_auth_probe(result: UpstoxAuthProbeResult) -> tuple[str, ...]:
    return (
        "Upstox Read-Only Authentication Probe",
        f"Credential Status: {result.credential_status.value}",
        f"Authentication Status: {result.status.value}",
        f"Instrument Search: {result.instrument_search_status.value}",
        f"Historical Candle V3: {result.historical_candle_status.value}",
        f"Analytics Token Only: {_yes_no(result.analytics_token_only)}",
        f"Account Endpoint Called: {_yes_no(result.account_endpoint_called)}",
        f"Order Endpoint Called: {_yes_no(result.order_endpoint_called)}",
        "Static IP Required for Selected Endpoints: "
        + _yes_no(result.static_ip_required_for_selected_endpoints),
        f"HTTP Status: {_display(result.http_status)}",
        f"Provider Error Code: {_display(result.provider_error_code)}",
        f"Reason: {result.reason}",
        "PRODUCTION_INFLUENCE=false",
    )


def render_upstox_historical_sample(
    sample: HistoricalSourceSampleManifest,
    dataset: UpstoxHistoricalEvidenceDataset | None,
) -> tuple[str, ...]:
    records = dataset.records if dataset is not None else ()
    counts = Counter(item.coverage_classification.value for item in records)
    return (
        "Upstox Historical Evidence Sample",
        f"Population Candidates: {sample.population_count}",
        f"Planned Trial Candidates: {len(sample.records)}",
        f"Observed Candidates: {len(records)}",
        f"Sample Checksum: {sample.checksum}",
        "Coverage: " + _counts_text(counts),
        "Network Behaviour: no call unless --live is supplied",
        "PRODUCTION_INFLUENCE=false",
    )


def render_upstox_historical_coverage(
    records: Sequence[UpstoxHistoricalCandidateEvidence],
) -> tuple[str, ...]:
    counts = Counter(item.coverage_classification.value for item in records)
    return (
        "Upstox Historical Price Coverage",
        f"Candidates Tested: {len(records)}",
        "Coverage Classifications: " + _counts_text(counts),
        "Candidates with Required Raw Bars: "
        f"{sum(item.has_sufficient_raw_lookback for item in records)}",
        "Candidates with Required Pre-Cutoff Bars: "
        f"{sum(item.has_sufficient_pre_cutoff_lookback for item in records)}",
        "Candidates with Required Integrity-Valid Bars: "
        f"{sum(item.has_sufficient_valid_lookback for item in records)}",
        "Full Price Coverage Candidates: "
        f"{sum(item.full_price_coverage for item in records)}",
        "Candidate Results:",
        *(
            f"- {item.candidate_id} {item.requested_historical_symbol}: "
            f"{item.coverage_classification.value}; "
            f"raw={item.raw_bars_returned}; "
            f"pre_cutoff={item.pre_cutoff_bars}; "
            f"normalized={item.normalized_bars}; "
            f"integrity_valid={item.integrity_valid_bars}; "
            f"rejected={item.rejected_bars}; "
            f"duplicates={item.duplicate_sessions}; "
            f"invalid_ohlc={item.invalid_ohlc_relationship_rows}; "
            f"non_positive={item.non_positive_price_rows}; "
            f"negative_volume={item.negative_volume_rows}; "
            f"timezone={'valid' if item.timezone_consistent else 'invalid'}; "
            f"malformed_timestamps={item.malformed_timestamp_rows}; "
            f"post_cutoff={item.future_bars_excluded}; "
            f"out_of_order={item.out_of_order_rows}; "
            f"candidate_window_gaps={_display(item.missing_sessions)}; "
            "primary_defect="
            f"{_display_series_defect(item.primary_series_defect)}; "
            f"identity={item.identity_status.value}"
            for item in records
        ),
        "PRODUCTION_INFLUENCE=false",
    )


def render_upstox_identity_coverage(
    records: Sequence[UpstoxHistoricalCandidateEvidence],
) -> tuple[str, ...]:
    keys_found = sum(item.instrument_key is not None for item in records)
    provisional = sum(
        item.price_probe_eligible and not item.identity_confirmed for item in records
    )
    inactive = sum(
        item.inactive_security and item.instrument_key is not None for item in records
    )
    renamed = sum(
        item.renamed_security and item.instrument_key is not None for item in records
    )
    current_with_continuity = sum(
        item.instrument_key is not None
        and item.matched_symbol != item.requested_historical_symbol
        and item.identity_confirmed
        for item in records
    )
    duplicate_matches = sum(
        item.identity_status is UpstoxIdentityStatus.AMBIGUOUS
        and "multiple" in (item.identity_ambiguity_reason or "").lower()
        for item in records
    )
    isin_matches = sum(
        item.identity_match_method is UpstoxIdentityMatchMethod.ISIN for item in records
    )
    historical_symbol_matches = sum(
        item.instrument_key is not None
        and item.matched_symbol == item.requested_historical_symbol
        for item in records
    )
    current_only_rejected = sum(
        item.identity_status is UpstoxIdentityStatus.CURRENT_SYMBOL_ONLY_REJECTED
        for item in records
    )
    ambiguous = sum(
        item.identity_status is UpstoxIdentityStatus.AMBIGUOUS for item in records
    )
    return (
        "Upstox Historical Identity Coverage",
        f"Candidates Observed: {len(records)}",
        f"Instrument Keys Found: {keys_found}",
        f"Authoritative Identities: {sum(item.identity_confirmed for item in records)}",
        f"Provisional Price-Probe Identities: {provisional}",
        f"Matches by ISIN: {isin_matches}",
        f"Matches by Historical Symbol: {historical_symbol_matches}",
        f"Matches by Current Symbol plus Continuity: {current_with_continuity}",
        f"Current-Symbol-Only Matches Rejected: {current_only_rejected}",
        f"Inactive Identities Resolved: {inactive}",
        f"Renamed Identities Resolved: {renamed}",
        f"Ambiguous Matches: {ambiguous}",
        f"Duplicate Instrument Matches: {duplicate_matches}",
        "Identity Statuses: "
        + _counts_text(Counter(item.identity_status.value for item in records)),
        "Current-symbol-only matches are never accepted as historical continuity.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_upstox_adjustment_audit(
    records: Sequence[UpstoxHistoricalCandidateEvidence],
) -> tuple[str, ...]:
    return (
        "Upstox Historical Adjustment Audit",
        f"Candidates Observed: {len(records)}",
        "Adjustment Statuses: "
        + _counts_text(Counter(item.adjustment_status.value for item in records)),
        "Corporate-Action Statuses: "
        + _counts_text(Counter(item.corporate_action_status.value for item in records)),
        "Conclusion: price smoothness alone is not adjustment evidence; an "
        "authoritative effective-dated corporate-action source remains required.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_upstox_evidence_report(
    report: UpstoxHistoricalEvidenceReport,
) -> tuple[str, ...]:
    resolved = f"{report.instruments_resolved} / {report.instruments_unresolved}"
    identity_groups = (
        f"{report.active_symbol_resolution} / "
        f"{report.historical_symbol_resolution} / "
        f"{report.inactive_symbol_resolution} / "
        f"{report.renamed_symbol_resolution}"
    )
    history_groups = (
        f"{report.candidates_with_partial_history} / "
        f"{report.candidates_with_no_history}"
    )
    coverage_2016 = (
        f"{report.candidates_2016_full_price_coverage}/{report.candidates_2016_tested}"
    )
    coverage_later = (
        f"{report.later_year_full_price_coverage}/{report.later_year_candidates_tested}"
    )
    observed = _display_percent(report.observed_price_coverage_rate)
    projected = _display_percent(report.projected_price_coverage)
    return (
        "Upstox Historical Evidence Trial Report",
        f"Credential Status: {report.credential_status.value}",
        f"API Authentication Status: {report.authentication_status.value}",
        f"Manifest Candidates: {report.manifest_candidates}",
        f"Trial Candidates: {report.trial_candidates}",
        f"Historical Symbols Tested: {report.historical_symbols_tested}",
        f"Instruments Resolved / Unresolved: {resolved}",
        f"Active / Historical / Inactive / Renamed Resolution: {identity_groups}",
        f"Candidates with 121 Raw Bars: {report.candidates_with_121_raw_bars}",
        "Candidates with 121 Pre-Cutoff Bars: "
        f"{report.candidates_with_121_pre_cutoff_bars}",
        "Candidates with 121 Integrity-Valid Bars: "
        f"{report.candidates_with_121_integrity_valid_bars}",
        f"Full Price Coverage Candidates: {report.full_price_coverage_candidates}",
        f"Partial / No History (invalid series excluded): {history_groups}",
        f"2016 Full Price Coverage: {coverage_2016}",
        f"Later-Year Full Price Coverage: {coverage_later}",
        f"Missing-Session Rate: {_display_percent(report.missing_session_rate)}",
        f"Invalid-Series Count: {report.invalid_series_count}",
        f"Adjustment Conclusion: {report.adjustment_conclusion.value}",
        f"Corporate-Action Conclusion: {report.corporate_action_conclusion.value}",
        f"Observed Price-Coverage Rate: {observed}",
        f"Projected Price Coverage: {projected}",
        "Terminal Coverage Status Reconciliation: "
        f"{report.terminal_status_total}/{report.trial_candidates}; "
        f"{'RECONCILED' if report.terminal_statuses_reconcile else 'MISMATCH'}",
        f"Full Reconstruction Readiness: {report.full_reconstruction_readiness}",
        f"Selection-Bias Implication: {report.selection_bias_implication}",
        f"Recommended Upstox Source Role: {report.recommended_source_role.value}",
        f"Exact Conclusion: {report.conclusion.value}",
        "Sample Composition: " + _pairs_text(report.sample_composition),
        "Limitations:",
        *(f"- {item}" for item in report.limitations),
        "PRODUCTION_INFLUENCE=false",
    )


def export_upstox_evidence_json(
    payload: Any,
    path: Path | str,
) -> None:
    safe = _sanitize_export_payload(payload)
    Path(path).write_text(
        json.dumps(_jsonable(safe), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def export_upstox_evidence_csv(
    records: Sequence[UpstoxHistoricalCandidateEvidence],
    path: Path | str,
) -> None:
    fieldnames = (
        "candidate_id",
        "candidate_date",
        "historical_symbol",
        "matched_symbol",
        "instrument_key",
        "identity_status",
        "identity_confirmed",
        "coverage_classification",
        "raw_bars_returned",
        "pre_cutoff_bars",
        "normalized_bars",
        "integrity_valid_bars",
        "required_valid_bars",
        "rejected_bars",
        "has_sufficient_raw_lookback",
        "has_sufficient_pre_cutoff_lookback",
        "has_sufficient_valid_lookback",
        "full_price_coverage",
        "primary_series_defect",
        "secondary_series_defects",
        "invalid_ohlc_relationship_rows",
        "non_positive_price_rows",
        "negative_volume_rows",
        "malformed_timestamp_rows",
        "non_trading_session_rows",
        "out_of_order_rows",
        "post_cutoff_rows",
        "returned_start_date",
        "returned_end_date",
        "missing_sessions",
        "adjustment_status",
        "corporate_action_status",
        "request_configuration_hash",
        "production_influence",
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in sorted(records, key=lambda row: row.candidate_id):
            safe = item.sanitized_for_persistence()
            writer.writerow(
                {
                    "candidate_id": safe.candidate_id,
                    "candidate_date": safe.candidate_date.isoformat(),
                    "historical_symbol": safe.requested_historical_symbol,
                    "matched_symbol": safe.matched_symbol or "",
                    "instrument_key": safe.instrument_key or "",
                    "identity_status": safe.identity_status.value,
                    "identity_confirmed": safe.identity_confirmed,
                    "coverage_classification": safe.coverage_classification.value,
                    "raw_bars_returned": safe.raw_bars_returned,
                    "pre_cutoff_bars": safe.pre_cutoff_bars,
                    "normalized_bars": safe.normalized_bars,
                    "integrity_valid_bars": safe.integrity_valid_bars,
                    "required_valid_bars": safe.required_valid_bars,
                    "rejected_bars": safe.rejected_bars,
                    "has_sufficient_raw_lookback": (safe.has_sufficient_raw_lookback),
                    "has_sufficient_pre_cutoff_lookback": (
                        safe.has_sufficient_pre_cutoff_lookback
                    ),
                    "has_sufficient_valid_lookback": (
                        safe.has_sufficient_valid_lookback
                    ),
                    "full_price_coverage": safe.full_price_coverage,
                    "primary_series_defect": (
                        safe.primary_series_defect.value
                        if safe.primary_series_defect
                        else ""
                    ),
                    "secondary_series_defects": ";".join(
                        item.value for item in safe.secondary_series_defects
                    ),
                    "invalid_ohlc_relationship_rows": (
                        safe.invalid_ohlc_relationship_rows
                    ),
                    "non_positive_price_rows": safe.non_positive_price_rows,
                    "negative_volume_rows": safe.negative_volume_rows,
                    "malformed_timestamp_rows": safe.malformed_timestamp_rows,
                    "non_trading_session_rows": safe.non_trading_session_rows,
                    "out_of_order_rows": safe.out_of_order_rows,
                    "post_cutoff_rows": safe.future_bars_excluded,
                    "returned_start_date": safe.returned_start_date.isoformat()
                    if safe.returned_start_date
                    else "",
                    "returned_end_date": safe.returned_end_date.isoformat()
                    if safe.returned_end_date
                    else "",
                    "missing_sessions": safe.missing_sessions
                    if safe.missing_sessions is not None
                    else "",
                    "adjustment_status": safe.adjustment_status.value,
                    "corporate_action_status": safe.corporate_action_status.value,
                    "request_configuration_hash": safe.request_configuration_hash,
                    "production_influence": False,
                }
            )


def load_official_upstox_instruments(
    path: Path | str | None,
) -> tuple[UpstoxInstrumentRecord, ...]:
    if path is None or not str(path).strip():
        return ()
    target = Path(path)
    if not target.is_file():
        return ()
    payload = json.loads(target.read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("data", [])
    if not isinstance(rows, list):
        return ()
    return tuple(
        record
        for item in rows
        if isinstance(item, dict)
        if (
            record := UpstoxInstrumentRecord.from_payload(
                item, source="OFFICIAL_INSTRUMENT_FILE"
            )
        )
        is not None
    )


def _assert_allowed_read_only_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    allowed = (
        parsed.scheme == "https"
        and parsed.hostname == _ALLOWED_HOST
        and any(
            parsed.path == item or parsed.path.startswith(item)
            for item in _ALLOWED_PATHS
        )
    )
    if not allowed:
        raise UpstoxProbeHttpError(
            category=UpstoxProbeErrorCategory.ENDPOINT_NOT_ALLOWED,
            http_status=None,
            provider_error_code=None,
            sanitized_message=(
                "Only documented Instrument Search and Historical Candle V3 GET "
                "endpoints are allowed."
            ),
        )


def _authorization_token(headers: Mapping[str, str]) -> str | None:
    value = headers.get("Authorization") or headers.get("authorization")
    if not value:
        return None
    return value.removeprefix("Bearer ").strip() or None


def _safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    permitted = {"content-type", "server", "cf-ray", "cf-mitigated", "retry-after"}
    return {
        str(key): str(value)[:256]
        for key, value in headers.items()
        if str(key).lower() in permitted
    }


def _provider_error(body: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None, "Upstox returned a non-JSON error response."
    if not isinstance(payload, dict):
        return None, "Upstox returned an unexpected error response."
    errors = payload.get("errors")
    first = errors[0] if isinstance(errors, list) and errors else payload
    if not isinstance(first, dict):
        return None, "Upstox rejected the read-only request."
    code = _optional_text(
        first.get("errorCode") or first.get("error_code") or first.get("code")
    )
    message = _optional_text(
        first.get("message") or first.get("error") or payload.get("message")
    )
    return code, message


def _redact(value: str, token: str | None) -> str:
    redacted = value
    if token:
        redacted = redacted.replace(token, "[REDACTED]")
    for marker in ("Bearer ", "access_token", "authorization"):
        if marker.lower() in redacted.lower():
            return "Provider rejection details were redacted."
    return redacted[:512]


def _http_error_category(
    status: int,
    message: str,
    *,
    provider_error_code: str | None,
) -> UpstoxProbeErrorCategory:
    if provider_error_code == "UDAPI1173":
        return UpstoxProbeErrorCategory.INSTRUMENT_SEARCH_PAGE_SIZE_INVALID
    lowered = message.lower()
    if status == 401:
        return (
            UpstoxProbeErrorCategory.TOKEN_EXPIRED
            if "expir" in lowered
            else UpstoxProbeErrorCategory.AUTHENTICATION_FAILED
        )
    if status == 403:
        return UpstoxProbeErrorCategory.ENDPOINT_FORBIDDEN
    if status == 429:
        return UpstoxProbeErrorCategory.RATE_LIMITED
    if status >= 500:
        return UpstoxProbeErrorCategory.TRANSIENT_PROVIDER_ERROR
    return UpstoxProbeErrorCategory.PERSISTENT_PROVIDER_ERROR


def _validate_instrument_search_records(records: int) -> None:
    if (
        isinstance(records, bool)
        or records < UPSTOX_INSTRUMENT_SEARCH_MIN_RECORDS
        or records > UPSTOX_INSTRUMENT_SEARCH_MAX_RECORDS
    ):
        raise ValueError(
            "Instrument Search records must be between 1 and 30 inclusive."
        )


def _retry_after(headers: Any | None) -> float | None:
    if headers is None:
        return None
    value = headers.get("Retry-After") or headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _auth_result(
    *,
    credential: UpstoxProbeCredentialStatus,
    status: UpstoxAuthProbeStatus,
    reason: str,
) -> UpstoxAuthProbeResult:
    return UpstoxAuthProbeResult(
        credential_status=credential,
        status=status,
        instrument_search_status=UpstoxEndpointProbeStatus.NOT_TESTED,
        historical_candle_status=UpstoxEndpointProbeStatus.NOT_TESTED,
        analytics_token_only=True,
        account_endpoint_called=False,
        order_endpoint_called=False,
        static_ip_required_for_selected_endpoints=False,
        http_status=None,
        provider_error_code=None,
        reason=reason,
    )


def _auth_error_result(
    credential: UpstoxProbeCredentialStatus,
    error: UpstoxProbeHttpError,
    *,
    instrument_search: bool,
) -> UpstoxAuthProbeResult:
    status_map = {
        UpstoxProbeErrorCategory.AUTHENTICATION_FAILED: (
            UpstoxAuthProbeStatus.TOKEN_REJECTED
        ),
        UpstoxProbeErrorCategory.TOKEN_EXPIRED: UpstoxAuthProbeStatus.TOKEN_EXPIRED,
        UpstoxProbeErrorCategory.ENDPOINT_FORBIDDEN: (
            UpstoxAuthProbeStatus.ENDPOINT_FORBIDDEN
        ),
        UpstoxProbeErrorCategory.RATE_LIMITED: UpstoxAuthProbeStatus.RATE_LIMITED,
        UpstoxProbeErrorCategory.TRANSIENT_PROVIDER_ERROR: (
            UpstoxAuthProbeStatus.UPSTOX_UNAVAILABLE
        ),
        UpstoxProbeErrorCategory.PERSISTENT_PROVIDER_ERROR: (
            UpstoxAuthProbeStatus.UPSTOX_UNAVAILABLE
        ),
        UpstoxProbeErrorCategory.NETWORK_ERROR: (
            UpstoxAuthProbeStatus.UPSTOX_UNAVAILABLE
        ),
    }
    endpoint_map = {
        UpstoxProbeErrorCategory.AUTHENTICATION_FAILED: (
            UpstoxEndpointProbeStatus.AUTHENTICATION_FAILED
        ),
        UpstoxProbeErrorCategory.TOKEN_EXPIRED: (
            UpstoxEndpointProbeStatus.AUTHENTICATION_FAILED
        ),
        UpstoxProbeErrorCategory.ENDPOINT_FORBIDDEN: (
            UpstoxEndpointProbeStatus.FORBIDDEN
        ),
        UpstoxProbeErrorCategory.RATE_LIMITED: UpstoxEndpointProbeStatus.RATE_LIMITED,
    }
    endpoint_status = endpoint_map.get(
        error.category, UpstoxEndpointProbeStatus.PROVIDER_ERROR
    )
    return UpstoxAuthProbeResult(
        credential_status=credential,
        status=status_map.get(error.category, UpstoxAuthProbeStatus.PROBE_ERROR),
        instrument_search_status=endpoint_status
        if instrument_search
        else UpstoxEndpointProbeStatus.NOT_TESTED,
        historical_candle_status=endpoint_status
        if not instrument_search
        else UpstoxEndpointProbeStatus.NOT_TESTED,
        analytics_token_only=True,
        account_endpoint_called=False,
        order_endpoint_called=False,
        static_ip_required_for_selected_endpoints=False,
        http_status=error.http_status,
        provider_error_code=error.provider_error_code,
        reason=error.sanitized_message,
    )


def _parse_candle_response(response: UpstoxProbeHttpResponse) -> UpstoxCandleBatch:
    data = response.payload.get("data")
    candles_payload = data.get("candles") if isinstance(data, dict) else None
    if not isinstance(candles_payload, list):
        raise UpstoxProbeHttpError(
            category=UpstoxProbeErrorCategory.INVALID_RESPONSE,
            http_status=response.http_status,
            provider_error_code=None,
            sanitized_message="Historical Candle V3 response did not contain candles.",
        )
    normalized = json.dumps(candles_payload, sort_keys=True, separators=(",", ":"))
    parsed: list[UpstoxCandle] = []
    malformed = 0
    malformed_timestamps = 0
    for row in candles_payload:
        try:
            if not isinstance(row, list) or len(row) < 6:
                raise ValueError("malformed candle")
            try:
                observed = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    raise ValueError("timezone missing")
            except (TypeError, ValueError):
                malformed_timestamps += 1
                raise
            parsed.append(
                UpstoxCandle(
                    observed_at=observed,
                    open_price=Decimal(str(row[1])),
                    high_price=Decimal(str(row[2])),
                    low_price=Decimal(str(row[3])),
                    close_price=Decimal(str(row[4])),
                    volume=Decimal(str(row[5])),
                )
            )
        except (ValueError, TypeError, InvalidOperation):
            malformed += 1
    return UpstoxCandleBatch(
        candles=tuple(parsed),
        malformed_rows=malformed,
        http_status=response.http_status,
        response_checksum=sha256(normalized.encode("utf-8")).hexdigest(),
        malformed_timestamp_rows=malformed_timestamps,
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _instrument_records(
    payload: Mapping[str, Any] | None,
    *,
    source: str,
) -> tuple[UpstoxInstrumentRecord, ...]:
    if payload is None:
        return ()
    data = payload.get("data")
    rows = data if isinstance(data, list) else []
    return tuple(
        record
        for item in rows
        if isinstance(item, dict)
        if (record := UpstoxInstrumentRecord.from_payload(item, source=source))
        is not None
    )


def _deduplicate_instruments(
    instruments: Sequence[UpstoxInstrumentRecord],
) -> tuple[UpstoxInstrumentRecord, ...]:
    by_key: dict[str, UpstoxInstrumentRecord] = {}
    for item in instruments:
        by_key.setdefault(item.instrument_key, item)
    return tuple(by_key[key] for key in sorted(by_key))


def _date_in_interval(value: date, start: date | None, end: date | None) -> bool:
    return (start is None or value >= start) and (end is None or value <= end)


def _resolved_identity(
    record: HistoricalSourceEvaluationManifestRecord,
    *,
    match: UpstoxInstrumentRecord | None,
    method: UpstoxIdentityMatchMethod,
    confidence: UpstoxIdentityConfidence,
    status: UpstoxIdentityStatus,
    continuity: str,
    confirmed: bool,
    inactive: bool,
    renamed: bool,
    active_status: str,
    instrument_key: str | None = None,
) -> UpstoxIdentityResolution:
    return UpstoxIdentityResolution(
        candidate_id=record.candidate_id,
        requested_historical_symbol=record.historical_symbol,
        matched_symbol=match.trading_symbol if match else record.historical_symbol,
        isin=match.isin if match else None,
        instrument_key=instrument_key or (match.instrument_key if match else None),
        match_method=method,
        match_confidence=confidence,
        status=status,
        active_status=active_status,
        historical_continuity_evidence=continuity,
        ambiguity_reason=None,
        price_probe_eligible=True,
        identity_confirmed=confirmed,
        renamed_security=renamed,
        inactive_security=inactive,
        provider_exchange=match.exchange if match else None,
        provider_segment=match.segment if match else None,
        provider_series=match.series if match else None,
        provider_exchange_token=match.exchange_token if match else None,
        provider_security_type=match.security_type if match else None,
        provider_instrument_type=match.instrument_type if match else None,
        provider_metadata_source=match.source if match else None,
    )


def _unresolved_identity(
    record: HistoricalSourceEvaluationManifestRecord,
    *,
    status: UpstoxIdentityStatus,
    reason: str,
    inactive: bool,
    renamed: bool,
    active_status: str,
) -> UpstoxIdentityResolution:
    return UpstoxIdentityResolution(
        candidate_id=record.candidate_id,
        requested_historical_symbol=record.historical_symbol,
        matched_symbol=None,
        isin=None,
        instrument_key=None,
        match_method=UpstoxIdentityMatchMethod.UNRESOLVED,
        match_confidence=UpstoxIdentityConfidence.NONE,
        status=status,
        active_status=active_status,
        historical_continuity_evidence="No authoritative continuity evidence.",
        ambiguity_reason=reason,
        price_probe_eligible=False,
        identity_confirmed=False,
        renamed_security=renamed,
        inactive_security=inactive,
    )


def _valid_ohlc(candle: UpstoxCandle) -> bool:
    return (
        not _has_non_positive_price(candle)
        and candle.high_price >= candle.low_price
        and candle.low_price <= candle.open_price <= candle.high_price
        and candle.low_price <= candle.close_price <= candle.high_price
    )


def _has_non_positive_price(candle: UpstoxCandle) -> bool:
    return any(
        value <= _ZERO
        for value in (
            candle.open_price,
            candle.high_price,
            candle.low_price,
            candle.close_price,
        )
    )


def _has_irregular_bar_order(candles: Sequence[UpstoxCandle]) -> bool:
    if len(candles) < 3:
        return False
    timestamps = tuple(item.observed_at for item in candles)
    ascending = all(
        earlier <= later for earlier, later in zip(timestamps, timestamps[1:])
    )
    descending = all(
        earlier >= later for earlier, later in zip(timestamps, timestamps[1:])
    )
    return not ascending and not descending


def _series_defects(
    *,
    malformed_rows: int,
    malformed_timestamp_rows: int,
    non_positive_prices: int,
    invalid_ohlc_relationships: int,
    negative_volume_rows: int,
    timezone_mismatch: bool,
    non_trading_sessions: int,
    irregular_order: bool,
    duplicate_sessions: int,
    post_cutoff_bars: int,
    mixed_adjustment: bool,
    insufficient_after_filtering: bool,
) -> tuple[UpstoxSeriesDefect, ...]:
    defects: list[UpstoxSeriesDefect] = []
    if malformed_timestamp_rows:
        defects.append(UpstoxSeriesDefect.MALFORMED_TIMESTAMP)
    if non_positive_prices:
        defects.append(UpstoxSeriesDefect.NON_POSITIVE_PRICE)
    if invalid_ohlc_relationships:
        defects.append(UpstoxSeriesDefect.INVALID_OHLC_RELATIONSHIP)
    if negative_volume_rows:
        defects.append(UpstoxSeriesDefect.NEGATIVE_VOLUME)
    if timezone_mismatch:
        defects.append(UpstoxSeriesDefect.TIMEZONE_MISMATCH)
    if non_trading_sessions:
        defects.append(UpstoxSeriesDefect.NON_TRADING_SESSION)
    if irregular_order:
        defects.append(UpstoxSeriesDefect.OUT_OF_ORDER_BARS)
    if duplicate_sessions:
        defects.append(UpstoxSeriesDefect.DUPLICATE_SESSION)
    if post_cutoff_bars:
        defects.append(UpstoxSeriesDefect.POST_CUTOFF_CONTAMINATION)
    if mixed_adjustment:
        defects.append(UpstoxSeriesDefect.MIXED_ADJUSTMENT_EVIDENCE)
    if insufficient_after_filtering:
        defects.append(UpstoxSeriesDefect.INSUFFICIENT_VALID_BARS_AFTER_FILTERING)
    if malformed_rows > malformed_timestamp_rows:
        defects.append(UpstoxSeriesDefect.UNKNOWN_SERIES_DEFECT)
    return tuple(defects)


def _request_configuration_hash(
    record: HistoricalSourceEvaluationManifestRecord,
    instrument_key: str | None,
) -> str:
    payload = {
        "instrument_key": instrument_key,
        "from_date": record.required_start_date.isoformat(),
        "to_date": record.required_end_date.isoformat(),
        "unit": "days",
        "interval": 1,
        "minimum_bars": record.minimum_bars_required,
        "cutoff": "STRICTLY_BEFORE_CANDIDATE_AND_AT_OR_BEFORE_REQUIRED_END",
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _empty_candidate_evidence(
    record: HistoricalSourceEvaluationManifestRecord,
    identity: UpstoxIdentityResolution,
    *,
    entry_timing_state: str | None,
    classification: UpstoxCoverageClassification,
    request_hash: str,
    adjustment: UpstoxAdjustmentAssessment,
    explanation: str,
    error: UpstoxProbeHttpError | None = None,
) -> UpstoxHistoricalCandidateEvidence:
    return UpstoxHistoricalCandidateEvidence(
        candidate_id=record.candidate_id,
        candidate_date=record.candidate_date,
        replay_year=record.replay_year,
        gap_cause=record.gap_cause.value,
        setup_type=record.setup_type,
        market_regime=record.market_regime,
        entry_timing_state=entry_timing_state,
        requested_historical_symbol=record.historical_symbol,
        matched_symbol=identity.matched_symbol,
        isin=identity.isin,
        instrument_key=identity.instrument_key,
        identity_match_method=identity.match_method,
        identity_confidence=identity.match_confidence,
        identity_status=identity.status,
        active_status=identity.active_status,
        historical_continuity_evidence=identity.historical_continuity_evidence,
        identity_ambiguity_reason=identity.ambiguity_reason,
        price_probe_eligible=identity.price_probe_eligible,
        identity_confirmed=identity.identity_confirmed,
        renamed_security=identity.renamed_security,
        inactive_security=identity.inactive_security,
        requested_start_date=record.required_start_date,
        requested_end_date=record.required_end_date,
        returned_start_date=None,
        returned_end_date=None,
        returned_bar_count=0,
        usable_pre_candidate_bars=0,
        first_timestamp=None,
        last_timestamp=None,
        duplicate_sessions=0,
        missing_sessions=None,
        missing_session_rate=None,
        invalid_ohlc_rows=0,
        negative_volume_rows=0,
        volume_complete=False,
        timezone_consistent=False,
        candidate_date_included=False,
        future_bars_excluded=0,
        sufficient_lookback=False,
        coverage_classification=classification,
        http_status=error.http_status if error else None,
        error_category=error.category if error else None,
        provider_error_code=error.provider_error_code if error else None,
        response_checksum=None,
        response_checksum_retention="NOT_AVAILABLE",
        request_configuration_hash=request_hash,
        adjustment_status=adjustment.adjustment_status,
        corporate_action_status=adjustment.corporate_action_status,
        explanation=explanation,
        required_valid_bars=record.minimum_bars_required,
        provider_exchange=identity.provider_exchange,
        provider_segment=identity.provider_segment,
        provider_series=identity.provider_series,
        provider_exchange_token=identity.provider_exchange_token,
        provider_security_type=identity.provider_security_type,
        provider_instrument_type=identity.provider_instrument_type,
        provider_metadata_source=identity.provider_metadata_source,
        identity_search_query=identity.identity_search_query,
        identity_search_page_size=identity.identity_search_page_size,
    )


def _coverage_for_error(
    category: UpstoxProbeErrorCategory,
) -> UpstoxCoverageClassification:
    if category in {
        UpstoxProbeErrorCategory.AUTHENTICATION_FAILED,
        UpstoxProbeErrorCategory.TOKEN_EXPIRED,
    }:
        return UpstoxCoverageClassification.AUTHENTICATION_FAILED
    if category is UpstoxProbeErrorCategory.RATE_LIMITED:
        return UpstoxCoverageClassification.RATE_LIMITED_UNRESOLVED
    return UpstoxCoverageClassification.PROVIDER_ERROR_UNRESOLVED


def _coverage_classification(
    *,
    valid_bars: int,
    minimum_bars: int,
    missing_sessions: int | None,
    defects: Sequence[UpstoxSeriesDefect],
) -> UpstoxCoverageClassification:
    if defects:
        return UpstoxCoverageClassification.INVALID_SERIES
    if missing_sessions is not None and missing_sessions >= 2:
        return UpstoxCoverageClassification.MULTI_SESSION_GAPS
    if valid_bars >= minimum_bars:
        return UpstoxCoverageClassification.FULL_PRICE_COVERAGE
    if valid_bars == 0:
        return UpstoxCoverageClassification.CANDIDATE_WINDOW_MISSING
    if valid_bars < minimum_bars // 2:
        return UpstoxCoverageClassification.INSUFFICIENT_LOOKBACK
    return UpstoxCoverageClassification.PARTIAL_PRICE_COVERAGE


def _coverage_explanation(
    classification: UpstoxCoverageClassification,
    *,
    raw: int,
    pre_cutoff: int,
    normalized: int,
    valid: int,
    missing: int | None,
    primary_defect: UpstoxSeriesDefect | None,
) -> str:
    missing_text = "unavailable" if missing is None else str(missing)
    defect = primary_defect.value if primary_defect else "none"
    return (
        f"{classification.value}: raw={raw}; pre_cutoff={pre_cutoff}; "
        f"normalized={normalized}; integrity_valid={valid}; "
        f"primary_defect={defect}; missing_sessions={missing_text}."
    )


def _candles_around(
    candles: Sequence[UpstoxCandle], effective_date: date
) -> tuple[UpstoxCandle | None, UpstoxCandle | None]:
    before = tuple(item for item in candles if item.observed_at.date() < effective_date)
    after = tuple(item for item in candles if item.observed_at.date() >= effective_date)
    return (
        max(before, key=lambda item: item.observed_at, default=None),
        min(after, key=lambda item: item.observed_at, default=None),
    )


def _approximately(
    observed: Decimal,
    expected: Decimal,
    *,
    tolerance: Decimal = Decimal("0.15"),
) -> bool:
    if expected == _ZERO:
        return False
    return abs(observed - expected) / abs(expected) <= tolerance


def _display_optional_bool(value: bool | None) -> str:
    if value is None:
        return "unavailable"
    return "consistent" if value else "inconsistent"


def _ratio_decimal(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _FOUR, rounding=ROUND_HALF_UP
    )


def _aggregate_adjustment(
    records: Sequence[UpstoxHistoricalCandidateEvidence],
) -> UpstoxAdjustmentStatus:
    statuses = {item.adjustment_status for item in records}
    if UpstoxAdjustmentStatus.ADJUSTMENT_INCONSISTENT in statuses:
        return UpstoxAdjustmentStatus.ADJUSTMENT_INCONSISTENT
    confirmed = statuses & {
        UpstoxAdjustmentStatus.RAW_SERIES_CONFIRMED,
        UpstoxAdjustmentStatus.ADJUSTED_SERIES_CONFIRMED,
    }
    if len(confirmed) == 1 and statuses <= confirmed:
        return next(iter(confirmed))
    if records:
        return UpstoxAdjustmentStatus.ADJUSTMENT_UNDOCUMENTED
    return UpstoxAdjustmentStatus.INSUFFICIENT_EVIDENCE


def _aggregate_corporate_action(
    records: Sequence[UpstoxHistoricalCandidateEvidence],
) -> UpstoxCorporateActionStatus:
    statuses = {item.corporate_action_status for item in records}
    if UpstoxCorporateActionStatus.CONFLICTING_CORPORATE_ACTION_EVIDENCE in statuses:
        return UpstoxCorporateActionStatus.CONFLICTING_CORPORATE_ACTION_EVIDENCE
    if records and statuses == {
        UpstoxCorporateActionStatus.AUTHORITATIVE_CASE_CONSISTENT
    }:
        return UpstoxCorporateActionStatus.AUTHORITATIVE_CASE_CONSISTENT
    if records:
        return UpstoxCorporateActionStatus.CORPORATE_ACTION_EVIDENCE_REQUIRED
    return UpstoxCorporateActionStatus.INSUFFICIENT_EVIDENCE


def _report_conclusion(
    *,
    credential: UpstoxProbeCredentialStatus,
    authentication: UpstoxAuthProbeStatus,
    tested: int,
    observed_rate: Decimal | None,
    identity_complete: bool,
    corporate_complete: bool,
    population_complete: bool,
) -> tuple[UpstoxProbeConclusion, UpstoxRecommendedSourceRole]:
    if credential is UpstoxProbeCredentialStatus.CREDENTIALS_NOT_CONFIGURED:
        return (
            UpstoxProbeConclusion.UPSTOX_CREDENTIALS_NOT_CONFIGURED,
            UpstoxRecommendedSourceRole.EMPIRICAL_TRIAL_ONLY,
        )
    if authentication not in {
        UpstoxAuthProbeStatus.TOKEN_ACCEPTED,
        UpstoxAuthProbeStatus.PROBE_NOT_RUN,
    }:
        return (
            UpstoxProbeConclusion.UPSTOX_TRIAL_BLOCKED,
            UpstoxRecommendedSourceRole.EMPIRICAL_TRIAL_ONLY,
        )
    if not tested or observed_rate is None:
        return (
            UpstoxProbeConclusion.UPSTOX_EMPIRICAL_EVIDENCE_INSUFFICIENT,
            UpstoxRecommendedSourceRole.EMPIRICAL_TRIAL_ONLY,
        )
    if not population_complete:
        return (
            UpstoxProbeConclusion.UPSTOX_EMPIRICAL_EVIDENCE_INSUFFICIENT,
            UpstoxRecommendedSourceRole.EMPIRICAL_TRIAL_ONLY,
        )
    if observed_rate < Decimal("0.25"):
        return (
            UpstoxProbeConclusion.UPSTOX_PRICE_COVERAGE_TOO_LOW,
            UpstoxRecommendedSourceRole.NOT_USEFUL_FOR_HISTORICAL_RECOVERY,
        )
    if not identity_complete:
        return (
            UpstoxProbeConclusion.UPSTOX_IDENTITY_COVERAGE_INSUFFICIENT,
            UpstoxRecommendedSourceRole.LIMITED_SECONDARY_PRICE_VALIDATION,
        )
    if not corporate_complete:
        return (
            UpstoxProbeConclusion.UPSTOX_CORPORATE_ACTION_EVIDENCE_INSUFFICIENT,
            UpstoxRecommendedSourceRole.LIMITED_SECONDARY_PRICE_VALIDATION,
        )
    return (
        UpstoxProbeConclusion.UPSTOX_PRICE_SOURCE_PROMISING,
        UpstoxRecommendedSourceRole.SECONDARY_PRICE_VALIDATION,
    )


def _sample_composition(
    planned: Sequence[HistoricalSourceEvaluationManifestRecord],
    observed: Sequence[UpstoxHistoricalCandidateEvidence],
    *,
    entry_timing_by_candidate: Mapping[str, str | None],
) -> tuple[tuple[str, int], ...]:
    rows = observed if observed else planned
    counts: Counter[str] = Counter()
    for item in rows:
        year = item.replay_year
        counts[f"year={year}"] += 1
        gap = (
            item.gap_cause.value if hasattr(item.gap_cause, "value") else item.gap_cause
        )
        counts[f"gap={gap}"] += 1
        counts[f"setup={item.setup_type or 'UNAVAILABLE'}"] += 1
        counts[f"regime={item.market_regime or 'UNAVAILABLE'}"] += 1
        timing = getattr(item, "entry_timing_state", None) or (
            entry_timing_by_candidate.get(item.candidate_id)
        )
        counts[f"entry_timing={timing or 'UNAVAILABLE'}"] += 1
    return tuple(sorted(counts.items()))


def _dataset_from_payload(
    payload: Mapping[str, Any],
) -> UpstoxHistoricalEvidenceDataset:
    rows = payload.get("records", [])
    if not isinstance(rows, list):
        raise ValueError("Upstox evidence records must be a list")
    operations = payload.get("operational_metrics", {})
    if not isinstance(operations, Mapping):
        operations = {}
    elapsed = Decimal(str(operations.get("elapsed_seconds", "0")))
    request_rate = operations.get("request_rate_per_second")
    return UpstoxHistoricalEvidenceDataset(
        dataset_version=str(payload["dataset_version"]),
        probe_version=str(payload["probe_version"]),
        source_manifest_version=str(payload["source_manifest_version"]),
        source_manifest_checksum=str(payload["source_manifest_checksum"]),
        sample_checksum=str(payload["sample_checksum"]),
        scope=str(payload["scope"]),
        credential_status=UpstoxProbeCredentialStatus(
            str(payload["credential_status"])
        ),
        authentication_status=UpstoxAuthProbeStatus(
            str(payload["authentication_status"])
        ),
        records=tuple(
            _candidate_from_payload(item) for item in rows if isinstance(item, dict)
        ),
        operational_metrics=UpstoxOperationalMetrics(
            total_network_requests=int(operations.get("total_network_requests", 0)),
            successful_requests=int(operations.get("successful_requests", 0)),
            authentication_failures=int(operations.get("authentication_failures", 0)),
            rate_limit_responses=int(operations.get("rate_limit_responses", 0)),
            transient_failures=int(operations.get("transient_failures", 0)),
            permanent_failures=int(operations.get("permanent_failures", 0)),
            retries=int(operations.get("retries", 0)),
            elapsed_seconds=elapsed,
            request_rate_per_second=(
                Decimal(str(request_rate)) if request_rate is not None else None
            ),
            token_exposure_incidents=0,
            account_endpoint_calls=0,
            order_endpoint_calls=0,
        ),
        production_influence=False,
    )


def _candidate_from_payload(
    payload: Mapping[str, Any],
) -> UpstoxHistoricalCandidateEvidence:
    values = dict(payload)
    raw_bars = int(values.get("raw_bars_returned", values["returned_bar_count"]))
    future_bars = int(values.get("future_bars_excluded", 0))
    pre_cutoff = int(values.get("pre_cutoff_bars", max(0, raw_bars - future_bars)))
    normalized = int(values.get("normalized_bars", pre_cutoff))
    integrity_valid = int(
        values.get("integrity_valid_bars", values["usable_pre_candidate_bars"])
    )
    required_valid = int(values.get("required_valid_bars", 121))
    values.setdefault("raw_bars_returned", raw_bars)
    values.setdefault("pre_cutoff_bars", pre_cutoff)
    values.setdefault("normalized_bars", normalized)
    values.setdefault("integrity_valid_bars", integrity_valid)
    values.setdefault("required_valid_bars", required_valid)
    values.setdefault("rejected_bars", max(0, raw_bars - integrity_valid))
    values.setdefault("has_sufficient_raw_lookback", raw_bars >= required_valid)
    values.setdefault(
        "has_sufficient_pre_cutoff_lookback", pre_cutoff >= required_valid
    )
    values.setdefault(
        "has_sufficient_valid_lookback", integrity_valid >= required_valid
    )
    values.setdefault(
        "full_price_coverage",
        values["coverage_classification"]
        == UpstoxCoverageClassification.FULL_PRICE_COVERAGE.value,
    )
    values.setdefault(
        "invalid_ohlc_relationship_rows",
        int(values.get("invalid_ohlc_rows", 0)),
    )
    values.setdefault("non_positive_price_rows", 0)
    values.setdefault("malformed_timestamp_rows", 0)
    values.setdefault("non_trading_session_rows", 0)
    values.setdefault("out_of_order_rows", 0)
    if "primary_series_defect" not in values:
        legacy_defects = _legacy_series_defects(values)
        values["primary_series_defect"] = (
            legacy_defects[0].value if legacy_defects else None
        )
        values["secondary_series_defects"] = [item.value for item in legacy_defects[1:]]
    for key in (
        "candidate_date",
        "requested_start_date",
        "requested_end_date",
        "returned_start_date",
        "returned_end_date",
    ):
        if values.get(key):
            values[key] = date.fromisoformat(str(values[key]))
        elif key.startswith("returned_"):
            values[key] = None
    for key in ("first_timestamp", "last_timestamp"):
        values[key] = (
            datetime.fromisoformat(str(values[key])) if values.get(key) else None
        )
    values["missing_session_rate"] = (
        Decimal(str(values["missing_session_rate"]))
        if values.get("missing_session_rate") is not None
        else None
    )
    values["identity_match_method"] = UpstoxIdentityMatchMethod(
        str(values["identity_match_method"])
    )
    values["identity_confidence"] = UpstoxIdentityConfidence(
        str(values["identity_confidence"])
    )
    values["identity_status"] = UpstoxIdentityStatus(str(values["identity_status"]))
    values["coverage_classification"] = UpstoxCoverageClassification(
        str(values["coverage_classification"])
    )
    values["primary_series_defect"] = (
        UpstoxSeriesDefect(str(values["primary_series_defect"]))
        if values.get("primary_series_defect")
        else None
    )
    secondary = values.get("secondary_series_defects", [])
    values["secondary_series_defects"] = tuple(
        UpstoxSeriesDefect(str(item)) for item in secondary
    )
    values["error_category"] = (
        UpstoxProbeErrorCategory(str(values["error_category"]))
        if values.get("error_category")
        else None
    )
    values["adjustment_status"] = UpstoxAdjustmentStatus(
        str(values["adjustment_status"])
    )
    values["corporate_action_status"] = UpstoxCorporateActionStatus(
        str(values["corporate_action_status"])
    )
    values["production_influence"] = False
    return UpstoxHistoricalCandidateEvidence(**values)


def _legacy_series_defects(
    values: Mapping[str, Any],
) -> tuple[UpstoxSeriesDefect, ...]:
    if values.get("coverage_classification") != "INVALID_SERIES":
        return ()
    defects: list[UpstoxSeriesDefect] = []
    if int(values.get("duplicate_sessions", 0)) > 0:
        defects.append(UpstoxSeriesDefect.DUPLICATE_SESSION)
    if int(values.get("invalid_ohlc_rows", 0)) > 0:
        defects.append(UpstoxSeriesDefect.INVALID_OHLC_RELATIONSHIP)
    if int(values.get("negative_volume_rows", 0)) > 0:
        defects.append(UpstoxSeriesDefect.NEGATIVE_VOLUME)
    if values.get("timezone_consistent") is False:
        defects.append(UpstoxSeriesDefect.TIMEZONE_MISMATCH)
    if int(values.get("future_bars_excluded", 0)) > 0:
        defects.append(UpstoxSeriesDefect.POST_CUTOFF_CONTAMINATION)
    if values.get("adjustment_status") == "ADJUSTMENT_INCONSISTENT":
        defects.append(UpstoxSeriesDefect.MIXED_ADJUSTMENT_EVIDENCE)
    if not defects:
        defects.append(UpstoxSeriesDefect.UNKNOWN_SERIES_DEFECT)
    return tuple(defects)


def _sanitize_export_payload(payload: Any) -> Any:
    if isinstance(payload, UpstoxHistoricalEvidenceDataset):
        return replace(
            payload,
            records=tuple(item.sanitized_for_persistence() for item in payload.records),
        )
    if isinstance(payload, UpstoxHistoricalCandidateEvidence):
        return payload.sanitized_for_persistence()
    if isinstance(payload, tuple):
        return tuple(_sanitize_export_payload(item) for item in payload)
    return payload


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    return value


def _display(value: Any) -> str:
    return "unavailable" if value is None else str(value)


def _display_series_defect(value: UpstoxSeriesDefect | None) -> str:
    return value.value if value is not None else "none"


def _display_percent(value: Decimal | None) -> str:
    return (
        "unavailable"
        if value is None
        else f"{(value * 100).quantize(Decimal('0.01'))}%"
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _counts_text(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts)) or "none"


def _pairs_text(values: Sequence[tuple[str, int]]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values) or "none"


__all__ = [
    "DEFAULT_UPSTOX_HISTORICAL_EVIDENCE_PATH",
    "PRODUCTION_INFLUENCE",
    "UPSTOX_HISTORICAL_EVIDENCE_VERSION",
    "UPSTOX_HISTORICAL_PROBE_VERSION",
    "UPSTOX_INSTRUMENT_SEARCH_DEFAULT_RECORDS",
    "UPSTOX_INSTRUMENT_SEARCH_MAX_RECORDS",
    "UPSTOX_INSTRUMENT_SEARCH_MIN_RECORDS",
    "UpstoxAdjustmentAssessment",
    "UpstoxAdjustmentAuditEngine",
    "UpstoxAdjustmentStatus",
    "UpstoxAnalyticsTokenConfig",
    "UpstoxAuthProbeResult",
    "UpstoxAuthProbeStatus",
    "UpstoxCandle",
    "UpstoxCandleBatch",
    "UpstoxCorporateActionCase",
    "UpstoxCorporateActionStatus",
    "UpstoxCoverageClassification",
    "UpstoxHistoricalCandidateEvidence",
    "UpstoxHistoricalCandleValidator",
    "UpstoxHistoricalEvidenceDataset",
    "UpstoxHistoricalEvidenceReport",
    "UpstoxHistoricalEvidenceReportEngine",
    "UpstoxHistoricalEvidenceRepository",
    "UpstoxHistoricalProbeTransport",
    "UpstoxIdentityConfidence",
    "UpstoxIdentityHint",
    "UpstoxIdentityMatchMethod",
    "UpstoxIdentityResolution",
    "UpstoxIdentityResolver",
    "UpstoxIdentityStatus",
    "UpstoxInstrumentRecord",
    "UpstoxProbeConclusion",
    "UpstoxProbeCredentialStatus",
    "UpstoxProbeErrorCategory",
    "UpstoxProbeHttpError",
    "UpstoxProbeHttpResponse",
    "UpstoxReadOnlyHistoricalClient",
    "UpstoxRecommendedSourceRole",
    "UpstoxSeriesDefect",
    "UrlLibUpstoxHistoricalProbeTransport",
    "export_upstox_evidence_csv",
    "export_upstox_evidence_json",
    "load_official_upstox_instruments",
    "render_upstox_adjustment_audit",
    "render_upstox_auth_probe",
    "render_upstox_evidence_report",
    "render_upstox_historical_coverage",
    "render_upstox_historical_sample",
    "render_upstox_identity_coverage",
]
