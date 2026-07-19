from __future__ import annotations

import getpass
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv

from alpha.live.models import MarketSessionState

UPSTOX_API_BASE_URL = "https://api.upstox.com"
UPSTOX_AUTHORIZE_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = f"{UPSTOX_API_BASE_URL}/v2/login/authorization/token"
UPSTOX_PROFILE_URL = f"{UPSTOX_API_BASE_URL}/v2/user/profile"
UPSTOX_FEED_AUTHORIZE_V3_URL = (
    f"{UPSTOX_API_BASE_URL}/v3/feed/market-data-feed/authorize"
)
UPSTOX_MARKET_DATA_FEED_VERSION = "UPSTOX_MARKET_DATA_FEED_V3"
UPSTOX_OAUTH_USER_AGENT = "ProjectAlpha/1.0 UpstoxOAuthClient"
DEFAULT_UPSTOX_TOKEN_METADATA_PATH = Path(".alpha/upstox_token_metadata.json")
IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


class UpstoxCredentialPurpose(StrEnum):
    REQUIRED_FOR_AUTHORIZATION = "REQUIRED_FOR_AUTHORIZATION"
    REQUIRED_FOR_TOKEN_EXCHANGE = "REQUIRED_FOR_TOKEN_EXCHANGE"
    REQUIRED_FOR_LIVE_FEED = "REQUIRED_FOR_LIVE_FEED"
    OPTIONAL = "OPTIONAL"
    DEPRECATED = "DEPRECATED"


class UpstoxTokenStatus(StrEnum):
    TOKEN_VALID = "TOKEN_VALID"
    TOKEN_MISSING = "TOKEN_MISSING"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_REJECTED = "TOKEN_REJECTED"
    TOKEN_VALIDATION_FAILED = "TOKEN_VALIDATION_FAILED"


class UpstoxReadinessStatus(StrEnum):
    PROVIDER_READY = "PROVIDER_READY"
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    TOKEN_MISSING = "TOKEN_MISSING"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    FEED_AUTHORIZATION_FAILED = "FEED_AUTHORIZATION_FAILED"
    INSTRUMENT_REGISTRY_UNAVAILABLE = "INSTRUMENT_REGISTRY_UNAVAILABLE"
    MARKET_CLOSED = "MARKET_CLOSED"
    READY_WITH_MARKET_CLOSED = "READY_WITH_MARKET_CLOSED"


class UpstoxProviderHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    MARKET_CLOSED = "MARKET_CLOSED"
    NO_DATA = "NO_DATA"


class InstrumentResolutionStatus(StrEnum):
    RESOLVED_EXACT = "RESOLVED_EXACT"
    RESOLVED_ALIAS = "RESOLVED_ALIAS"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    STALE_REGISTRY = "STALE_REGISTRY"


class UpstoxDisconnectCause(StrEnum):
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    AUTHENTICATION_REJECTED = "AUTHENTICATION_REJECTED"
    NETWORK_INTERRUPTION = "NETWORK_INTERRUPTION"
    SERVER_DISCONNECT = "SERVER_DISCONNECT"
    SUBSCRIPTION_REJECTED = "SUBSCRIPTION_REJECTED"
    DECODE_FAILURE = "DECODE_FAILURE"
    NORMAL_CLOSE = "NORMAL_CLOSE"


class UpstoxTokenExchangeFailure(StrEnum):
    INVALID_CLIENT_CREDENTIALS = "INVALID_CLIENT_CREDENTIALS"
    REDIRECT_URI_INVALID = "REDIRECT_URI_INVALID"
    INVALID_OR_USED_AUTHORIZATION_CODE = "INVALID_OR_USED_AUTHORIZATION_CODE"
    NO_ACTIVE_TRADING_SEGMENTS = "NO_ACTIVE_TRADING_SEGMENTS"
    CLOUDFLARE_CLIENT_SIGNATURE_REJECTED = "CLOUDFLARE_CLIENT_SIGNATURE_REJECTED"
    TOKEN_EXCHANGE_NETWORK_FAILURE = "TOKEN_EXCHANGE_NETWORK_FAILURE"
    TOKEN_EXCHANGE_PROVIDER_REJECTION = "TOKEN_EXCHANGE_PROVIDER_REJECTION"


class UpstoxTokenExchangeError(ValueError):
    def __init__(
        self,
        *,
        category: UpstoxTokenExchangeFailure,
        http_status: int | None,
        provider_error_code: str | None,
        sanitized_message: str,
        diagnostic_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.category = category
        self.http_status = http_status
        self.provider_error_code = provider_error_code
        self.sanitized_message = sanitized_message
        self.diagnostic_headers = dict(diagnostic_headers or {})
        status = "HTTP unavailable" if http_status is None else f"HTTP {http_status}"
        code = (
            "provider code unavailable"
            if provider_error_code is None
            else provider_error_code
        )
        details = f"{category.value} ({status}, {code}): {sanitized_message}"
        if self.diagnostic_headers:
            headers = ", ".join(
                f"{name}: {value}" for name, value in self.diagnostic_headers.items()
            )
            details = f"{details} [{headers}]"
        super().__init__(details)


class UpstoxProviderHttpError(ValueError):
    def __init__(
        self,
        *,
        http_status: int,
        provider_error_code: str | None,
        sanitized_message: str,
        diagnostic_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.http_status = http_status
        self.provider_error_code = provider_error_code
        self.sanitized_message = sanitized_message
        self.diagnostic_headers = dict(diagnostic_headers or {})
        super().__init__(
            f"Upstox provider error HTTP {http_status}: {sanitized_message}"
        )


@dataclass(frozen=True, slots=True)
class UpstoxCredentialStatus:
    name: str
    purpose: UpstoxCredentialPurpose
    configured: bool
    source: str
    masked_suffix: str | None
    validation_status: str


@dataclass(frozen=True, slots=True)
class UpstoxAuthConfig:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    access_token: str | None
    websocket_url: str
    token_metadata_path: Path

    @classmethod
    def from_environment(cls) -> UpstoxAuthConfig:
        load_dotenv(override=False)
        configured_path = os.environ.get("UPSTOX_TOKEN_METADATA_PATH")
        return cls(
            client_id=_optional_env("UPSTOX_CLIENT_ID"),
            client_secret=_optional_env("UPSTOX_CLIENT_SECRET"),
            redirect_uri=_optional_env("UPSTOX_REDIRECT_URI"),
            access_token=_optional_env("UPSTOX_ACCESS_TOKEN"),
            websocket_url=os.environ.get(
                "UPSTOX_WEBSOCKET_URL",
                "wss://api.upstox.com/v3/feed/market-data-feed",
            ),
            token_metadata_path=(
                Path(configured_path)
                if configured_path
                else DEFAULT_UPSTOX_TOKEN_METADATA_PATH
            ),
        )

    def credential_statuses(self) -> tuple[UpstoxCredentialStatus, ...]:
        return (
            _credential_status(
                "UPSTOX_CLIENT_ID",
                self.client_id,
                UpstoxCredentialPurpose.REQUIRED_FOR_AUTHORIZATION,
            ),
            _credential_status(
                "UPSTOX_CLIENT_SECRET",
                self.client_secret,
                UpstoxCredentialPurpose.REQUIRED_FOR_TOKEN_EXCHANGE,
            ),
            _credential_status(
                "UPSTOX_REDIRECT_URI",
                self.redirect_uri,
                UpstoxCredentialPurpose.REQUIRED_FOR_TOKEN_EXCHANGE,
            ),
            _credential_status(
                "UPSTOX_ACCESS_TOKEN",
                self.access_token,
                UpstoxCredentialPurpose.REQUIRED_FOR_LIVE_FEED,
            ),
            _credential_status(
                "UPSTOX_WEBSOCKET_URL",
                self.websocket_url,
                UpstoxCredentialPurpose.OPTIONAL,
            ),
        )

    def authorization_ready(self) -> bool:
        return bool(self.client_id and self.redirect_uri)

    def exchange_ready(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


@dataclass(frozen=True, slots=True)
class UpstoxTokenMetadata:
    provider: str
    token_fingerprint: str
    issued_at: datetime | None
    expected_expiry: datetime
    last_validation_at: datetime | None
    validation_status: UpstoxTokenStatus
    credential_source: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issued_at"] = (
            None if self.issued_at is None else self.issued_at.isoformat()
        )
        payload["expected_expiry"] = self.expected_expiry.isoformat()
        payload["last_validation_at"] = (
            None
            if self.last_validation_at is None
            else self.last_validation_at.isoformat()
        )
        payload["validation_status"] = self.validation_status.value
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> UpstoxTokenMetadata:
        return cls(
            provider=str(payload["provider"]),
            token_fingerprint=str(payload["token_fingerprint"]),
            issued_at=(
                None
                if payload.get("issued_at") is None
                else datetime.fromisoformat(str(payload["issued_at"]))
            ),
            expected_expiry=datetime.fromisoformat(str(payload["expected_expiry"])),
            last_validation_at=(
                None
                if payload.get("last_validation_at") is None
                else datetime.fromisoformat(str(payload["last_validation_at"]))
            ),
            validation_status=UpstoxTokenStatus(str(payload["validation_status"])),
            credential_source=str(payload["credential_source"]),
        )


@dataclass(frozen=True, slots=True)
class UpstoxTokenValidation:
    status: UpstoxTokenStatus
    token_configured: bool
    expected_expiry: datetime | None
    last_validation_at: datetime | None
    token_fingerprint: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class UpstoxFeedAuthorization:
    authorized: bool
    feed_api_version: str
    authorized_redirect_uri_present: bool
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class UpstoxInstrumentResolution:
    requested_symbol: str
    exchange: str
    instrument_key: str | None
    instrument_type: str | None
    status: InstrumentResolutionStatus
    registry_timestamp: datetime | None
    registry_version: str | None


@dataclass(frozen=True, slots=True)
class UpstoxProviderStatusReport:
    provider: str
    configured: bool
    credentials: tuple[UpstoxCredentialStatus, ...]
    token_validation: UpstoxTokenValidation
    feed_api_version: str
    feed_authorization: UpstoxFeedAuthorization
    instrument_resolution: UpstoxInstrumentResolution | None
    market_session: MarketSessionState
    websocket_implementation: str
    protobuf_contract: str
    provider_health: UpstoxProviderHealthStatus
    overall_readiness: UpstoxReadinessStatus


class UpstoxHttpTransport(Protocol):
    def post_form(
        self,
        url: str,
        form: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> Mapping[str, Any]: ...

    def get_json(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> Mapping[str, Any]: ...


class UrlLibUpstoxTransport:
    def post_form(
        self,
        url: str,
        form: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> Mapping[str, Any]:
        data = urllib.parse.urlencode(form).encode("utf-8")
        request_headers = dict(headers)
        if url == UPSTOX_TOKEN_URL:
            request_headers.setdefault("Connection", "close")
            request_headers.setdefault("User-Agent", UPSTOX_OAUTH_USER_AGENT)
        request = urllib.request.Request(
            url,
            data=data,
            headers=request_headers,
            method="POST",
        )
        return _read_json(request)

    def get_json(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> Mapping[str, Any]:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        return _read_json(request)


class UpstoxAuthService:
    def __init__(
        self,
        *,
        config: UpstoxAuthConfig | None = None,
        transport: UpstoxHttpTransport | None = None,
    ) -> None:
        self.config = config or UpstoxAuthConfig.from_environment()
        self.transport = transport or UrlLibUpstoxTransport()

    def authorization_url(self, *, state: str | None = None) -> str:
        if not self.config.authorization_ready():
            raise ValueError("UPSTOX_CLIENT_ID and UPSTOX_REDIRECT_URI are required")
        params = {
            "response_type": "code",
            "client_id": self.config.client_id or "",
            "redirect_uri": self.config.redirect_uri or "",
        }
        if state:
            params["state"] = state
        return f"{UPSTOX_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str) -> UpstoxTokenMetadata:
        clean_code = code.strip()
        if not clean_code:
            raise ValueError("authorization code cannot be empty")
        if not self.config.exchange_ready():
            raise ValueError(
                "UPSTOX_CLIENT_ID, UPSTOX_CLIENT_SECRET and UPSTOX_REDIRECT_URI "
                "are required for token exchange"
            )
        form = {
            "code": clean_code,
            "client_id": self.config.client_id or "",
            "client_secret": self.config.client_secret or "",
            "redirect_uri": self.config.redirect_uri or "",
            "grant_type": "authorization_code",
        }
        headers = {
            "Accept": "application/json",
            "Connection": "close",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": UPSTOX_OAUTH_USER_AGENT,
        }
        try:
            payload = self.transport.post_form(UPSTOX_TOKEN_URL, form, headers)
        except UpstoxProviderHttpError as exc:
            raise _token_exchange_error_from_provider(
                exc,
                sensitive_values=(
                    clean_code,
                    self.config.client_secret,
                    self.config.access_token,
                ),
            ) from None
        except urllib.error.HTTPError as exc:
            raise _token_exchange_error(
                exc,
                sensitive_values=(
                    clean_code,
                    self.config.client_secret,
                    self.config.access_token,
                ),
            ) from None
        except OSError as exc:
            raise UpstoxTokenExchangeError(
                category=UpstoxTokenExchangeFailure.TOKEN_EXCHANGE_NETWORK_FAILURE,
                http_status=None,
                provider_error_code=None,
                sanitized_message=(
                    f"Token exchange failed with {exc.__class__.__name__}."
                ),
            ) from None
        token = str(payload.get("access_token") or "")
        if not token:
            raise ValueError("Upstox token response did not include access_token")
        metadata = UpstoxTokenMetadata(
            provider="upstox",
            token_fingerprint=_fingerprint(token),
            issued_at=datetime.now(UTC),
            expected_expiry=_next_upstox_expiry(datetime.now(UTC)),
            last_validation_at=None,
            validation_status=UpstoxTokenStatus.TOKEN_VALID,
            credential_source="exchange-code",
        )
        self.save_metadata(metadata)
        return metadata

    def validate_token(self, *, remote: bool = True) -> UpstoxTokenValidation:
        token = self.config.access_token
        metadata = self.load_metadata()
        if not token:
            return UpstoxTokenValidation(
                status=UpstoxTokenStatus.TOKEN_MISSING,
                token_configured=False,
                expected_expiry=None if metadata is None else metadata.expected_expiry,
                last_validation_at=(
                    None if metadata is None else metadata.last_validation_at
                ),
                token_fingerprint=(
                    None if metadata is None else metadata.token_fingerprint
                ),
                reason="UPSTOX_ACCESS_TOKEN is not configured.",
            )
        metadata_matches = (
            metadata is not None and metadata.token_fingerprint == _fingerprint(token)
        )
        expected_expiry = (
            metadata.expected_expiry
            if metadata_matches and metadata is not None
            else _next_upstox_expiry(datetime.now(UTC))
        )
        if datetime.now(UTC) >= expected_expiry.astimezone(UTC):
            return UpstoxTokenValidation(
                status=UpstoxTokenStatus.TOKEN_EXPIRED,
                token_configured=True,
                expected_expiry=expected_expiry,
                last_validation_at=(
                    None if metadata is None else metadata.last_validation_at
                ),
                token_fingerprint=_fingerprint(token),
                reason="Configured token is past its expected Upstox expiry.",
            )
        if not remote:
            return UpstoxTokenValidation(
                status=UpstoxTokenStatus.TOKEN_VALID,
                token_configured=True,
                expected_expiry=expected_expiry,
                last_validation_at=(
                    None if metadata is None else metadata.last_validation_at
                ),
                token_fingerprint=_fingerprint(token),
                reason="Token is configured and not past expected expiry.",
            )
        try:
            self.transport.get_json(
                UPSTOX_PROFILE_URL,
                {
                    "accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
        except UpstoxProviderHttpError as exc:
            status = (
                UpstoxTokenStatus.TOKEN_REJECTED
                if exc.http_status in {401, 403}
                else UpstoxTokenStatus.TOKEN_VALIDATION_FAILED
            )
            return UpstoxTokenValidation(
                status=status,
                token_configured=True,
                expected_expiry=expected_expiry,
                last_validation_at=datetime.now(UTC),
                token_fingerprint=_fingerprint(token),
                reason=(f"Upstox token validation failed with HTTP {exc.http_status}."),
            )
        except urllib.error.HTTPError as exc:
            status = (
                UpstoxTokenStatus.TOKEN_REJECTED
                if exc.code in {401, 403}
                else UpstoxTokenStatus.TOKEN_VALIDATION_FAILED
            )
            return UpstoxTokenValidation(
                status=status,
                token_configured=True,
                expected_expiry=expected_expiry,
                last_validation_at=datetime.now(UTC),
                token_fingerprint=_fingerprint(token),
                reason=f"Upstox token validation failed with HTTP {exc.code}.",
            )
        except OSError as exc:
            return UpstoxTokenValidation(
                status=UpstoxTokenStatus.TOKEN_VALIDATION_FAILED,
                token_configured=True,
                expected_expiry=expected_expiry,
                last_validation_at=datetime.now(UTC),
                token_fingerprint=_fingerprint(token),
                reason=f"Upstox token validation failed: {exc.__class__.__name__}.",
            )
        validation = UpstoxTokenValidation(
            status=UpstoxTokenStatus.TOKEN_VALID,
            token_configured=True,
            expected_expiry=expected_expiry,
            last_validation_at=datetime.now(UTC),
            token_fingerprint=_fingerprint(token),
            reason="Provider accepted the configured token.",
        )
        self.save_metadata(
            UpstoxTokenMetadata(
                provider="upstox",
                token_fingerprint=_fingerprint(token),
                issued_at=None if metadata is None else metadata.issued_at,
                expected_expiry=expected_expiry,
                last_validation_at=validation.last_validation_at,
                validation_status=validation.status,
                credential_source="environment",
            )
        )
        return validation

    def authorize_market_data_feed_v3(self) -> UpstoxFeedAuthorization:
        token = self.config.access_token
        if not token:
            return UpstoxFeedAuthorization(
                authorized=False,
                feed_api_version=UPSTOX_MARKET_DATA_FEED_VERSION,
                authorized_redirect_uri_present=False,
                status="TOKEN_MISSING",
                reason="UPSTOX_ACCESS_TOKEN is not configured.",
            )
        try:
            payload = self.transport.get_json(
                UPSTOX_FEED_AUTHORIZE_V3_URL,
                {
                    "accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
        except UpstoxProviderHttpError as exc:
            return UpstoxFeedAuthorization(
                authorized=False,
                feed_api_version=UPSTOX_MARKET_DATA_FEED_VERSION,
                authorized_redirect_uri_present=False,
                status="FEED_AUTHORIZATION_FAILED",
                reason=f"Feed authorization failed with HTTP {exc.http_status}.",
            )
        except urllib.error.HTTPError as exc:
            return UpstoxFeedAuthorization(
                authorized=False,
                feed_api_version=UPSTOX_MARKET_DATA_FEED_VERSION,
                authorized_redirect_uri_present=False,
                status="FEED_AUTHORIZATION_FAILED",
                reason=f"Feed authorization failed with HTTP {exc.code}.",
            )
        except OSError as exc:
            return UpstoxFeedAuthorization(
                authorized=False,
                feed_api_version=UPSTOX_MARKET_DATA_FEED_VERSION,
                authorized_redirect_uri_present=False,
                status="FEED_AUTHORIZATION_FAILED",
                reason=f"Feed authorization failed: {exc.__class__.__name__}.",
            )
        data = payload.get("data")
        redirect = (
            data.get("authorized_redirect_uri") if isinstance(data, dict) else None
        )
        return UpstoxFeedAuthorization(
            authorized=bool(redirect),
            feed_api_version=UPSTOX_MARKET_DATA_FEED_VERSION,
            authorized_redirect_uri_present=bool(redirect),
            status="AUTHORIZED" if redirect else "FEED_AUTHORIZATION_FAILED",
            reason=(
                "Authorized V3 websocket redirect URI received."
                if redirect
                else "V3 authorize response did not include redirect URI."
            ),
        )

    def load_metadata(self) -> UpstoxTokenMetadata | None:
        path = self.config.token_metadata_path
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        return UpstoxTokenMetadata.from_dict(payload)

    def save_metadata(self, metadata: UpstoxTokenMetadata) -> None:
        path = self.config.token_metadata_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(metadata.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def clear_metadata(self) -> bool:
        path = self.config.token_metadata_path
        if not path.exists():
            return False
        path.unlink()
        return True


class UpstoxInstrumentResolver:
    def __init__(
        self,
        *,
        registry_path: Path | None = None,
        registry_version: str | None = None,
        registry_timestamp: datetime | None = None,
    ) -> None:
        configured = os.environ.get("UPSTOX_INSTRUMENT_REGISTRY")
        self.registry_path = registry_path or (Path(configured) if configured else None)
        self.registry_version = registry_version or _optional_env(
            "UPSTOX_INSTRUMENT_REGISTRY_VERSION"
        )
        self.registry_timestamp = registry_timestamp

    def resolve(self, symbol: str) -> UpstoxInstrumentResolution:
        requested = symbol.strip().upper()
        if "|" in requested:
            exchange, raw_symbol = requested.split("|", 1)
            return UpstoxInstrumentResolution(
                requested_symbol=raw_symbol,
                exchange=exchange,
                instrument_key=requested,
                instrument_type=None,
                status=InstrumentResolutionStatus.RESOLVED_EXACT,
                registry_timestamp=self.registry_timestamp,
                registry_version=self.registry_version,
            )
        rows = self._load_rows()
        matches = [
            row
            for row in rows
            if str(row.get("tradingsymbol", row.get("symbol", ""))).upper() == requested
        ]
        if len(matches) == 1:
            row = matches[0]
            return UpstoxInstrumentResolution(
                requested_symbol=requested,
                exchange=str(row.get("exchange", "NSE")),
                instrument_key=_optional_text(row.get("instrument_key")),
                instrument_type=_optional_text(row.get("instrument_type")),
                status=InstrumentResolutionStatus.RESOLVED_EXACT,
                registry_timestamp=self.registry_timestamp,
                registry_version=self.registry_version,
            )
        if len(matches) > 1:
            return UpstoxInstrumentResolution(
                requested_symbol=requested,
                exchange="NSE",
                instrument_key=None,
                instrument_type=None,
                status=InstrumentResolutionStatus.AMBIGUOUS,
                registry_timestamp=self.registry_timestamp,
                registry_version=self.registry_version,
            )
        return UpstoxInstrumentResolution(
            requested_symbol=requested,
            exchange="NSE",
            instrument_key=None,
            instrument_type=None,
            status=(
                InstrumentResolutionStatus.NOT_FOUND
                if rows
                else InstrumentResolutionStatus.STALE_REGISTRY
            ),
            registry_timestamp=self.registry_timestamp,
            registry_version=self.registry_version,
        )

    def resolve_instrument_key(self, instrument_key: str) -> UpstoxInstrumentResolution:
        requested = instrument_key.strip()
        if not requested or "*" in requested:
            return UpstoxInstrumentResolution(
                requested_symbol=requested,
                exchange="UNKNOWN",
                instrument_key=None,
                instrument_type=None,
                status=InstrumentResolutionStatus.NOT_FOUND,
                registry_timestamp=self.registry_timestamp,
                registry_version=self.registry_version,
            )
        rows = self._load_rows()
        matches = [
            row
            for row in rows
            if str(row.get("instrument_key", "")).strip() == requested
        ]
        if len(matches) == 1:
            row = matches[0]
            return UpstoxInstrumentResolution(
                requested_symbol=str(
                    row.get("tradingsymbol", row.get("symbol", requested))
                ).upper(),
                exchange=str(row.get("exchange", "NSE")).upper(),
                instrument_key=requested,
                instrument_type=_optional_text(row.get("instrument_type")),
                status=InstrumentResolutionStatus.RESOLVED_EXACT,
                registry_timestamp=self.registry_timestamp,
                registry_version=self.registry_version,
            )
        if len(matches) > 1:
            return UpstoxInstrumentResolution(
                requested_symbol=requested,
                exchange="UNKNOWN",
                instrument_key=None,
                instrument_type=None,
                status=InstrumentResolutionStatus.AMBIGUOUS,
                registry_timestamp=self.registry_timestamp,
                registry_version=self.registry_version,
            )
        return UpstoxInstrumentResolution(
            requested_symbol=requested,
            exchange="UNKNOWN",
            instrument_key=None,
            instrument_type=None,
            status=(
                InstrumentResolutionStatus.NOT_FOUND
                if rows
                else InstrumentResolutionStatus.STALE_REGISTRY
            ),
            registry_timestamp=self.registry_timestamp,
            registry_version=self.registry_version,
        )

    def _load_rows(self) -> tuple[dict[str, Any], ...]:
        if self.registry_path is None or not self.registry_path.exists():
            return ()
        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return tuple(row for row in payload if isinstance(row, dict))
        if isinstance(payload, dict) and isinstance(payload.get("instruments"), list):
            return tuple(row for row in payload["instruments"] if isinstance(row, dict))
        return ()


class UpstoxProviderPreflight:
    def __init__(
        self,
        *,
        auth: UpstoxAuthService | None = None,
        resolver: UpstoxInstrumentResolver | None = None,
    ) -> None:
        self.auth = auth or UpstoxAuthService()
        self.resolver = resolver or UpstoxInstrumentResolver()

    def status(
        self,
        *,
        symbol: str | None = None,
        validate_remote: bool = False,
        authorize_feed: bool = False,
        market_session: MarketSessionState = MarketSessionState.UNKNOWN,
    ) -> UpstoxProviderStatusReport:
        config = self.auth.config
        token = self.auth.validate_token(remote=validate_remote)
        feed = (
            self.auth.authorize_market_data_feed_v3()
            if authorize_feed and token.status is UpstoxTokenStatus.TOKEN_VALID
            else UpstoxFeedAuthorization(
                authorized=False,
                feed_api_version=UPSTOX_MARKET_DATA_FEED_VERSION,
                authorized_redirect_uri_present=False,
                status="NOT_REQUESTED",
                reason="Feed authorization was not requested.",
            )
        )
        instrument = None if symbol is None else self.resolver.resolve(symbol)
        readiness = _readiness(
            config=config,
            token=token,
            feed=feed,
            instrument=instrument,
        )
        health = _health(readiness, token, feed)
        return UpstoxProviderStatusReport(
            provider="Upstox",
            configured=bool(config.access_token),
            credentials=config.credential_statuses(),
            token_validation=token,
            feed_api_version=UPSTOX_MARKET_DATA_FEED_VERSION,
            feed_authorization=feed,
            instrument_resolution=instrument,
            market_session=market_session,
            websocket_implementation="provider shell; V3 authorize supported",
            protobuf_contract="not materialized; decoder bindings unavailable",
            provider_health=health,
            overall_readiness=readiness,
        )


def render_upstox_status(report: UpstoxProviderStatusReport) -> tuple[str, ...]:
    lines = [
        "Upstox Provider Status",
        f"Provider Configured: {report.configured}",
        f"Feed API Version: {report.feed_api_version}",
        f"WebSocket Implementation: {report.websocket_implementation}",
        f"Protobuf Contract: {report.protobuf_contract}",
        "Credentials:",
    ]
    lines.extend(
        f"- {item.name}: configured={item.configured}, "
        f"purpose={item.purpose.value}, source={item.source}, "
        f"suffix={item.masked_suffix or 'unavailable'}, "
        f"status={item.validation_status}"
        for item in report.credentials
    )
    lines.extend(
        (
            f"Token Validation: {report.token_validation.status.value}",
            f"Expected Expiry: {_text(report.token_validation.expected_expiry)}",
            f"Last Validation: {_text(report.token_validation.last_validation_at)}",
            f"Feed Authorization: {report.feed_authorization.status}",
        )
    )
    if report.instrument_resolution is not None:
        resolution = report.instrument_resolution
        lines.extend(
            (
                f"Requested Symbol: {resolution.requested_symbol}",
                f"Exchange: {resolution.exchange}",
                f"Instrument Key: {_text(resolution.instrument_key)}",
                f"Instrument Type: {_text(resolution.instrument_type)}",
                f"Resolution Status: {resolution.status.value}",
                f"Registry Version: {_text(resolution.registry_version)}",
            )
        )
    lines.extend(
        (
            f"Market Session: {report.market_session.value}",
            f"Provider Health: {report.provider_health.value}",
            f"Overall Readiness: {report.overall_readiness.value}",
        )
    )
    return tuple(lines)


def prompt_authorization_code() -> str:
    return getpass.getpass("Paste Upstox authorization code: ").strip()


def _read_json(request: urllib.request.Request) -> Mapping[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw_body = _read_http_error_body(exc)
        provider_code, provider_message = _provider_error(raw_body)
        sensitive_values = _request_sensitive_values(request)
        message = provider_message or f"Upstox request failed with HTTP {exc.code}."
        if _is_cloudflare_error_1010(raw_body):
            provider_code = "1010"
            message = (
                "Cloudflare rejected the OAuth token request with error 1010 "
                "before Upstox OAuth validation completed."
            )
        raise UpstoxProviderHttpError(
            http_status=exc.code,
            provider_error_code=provider_code,
            sanitized_message=_sanitize_message(
                message,
                sensitive_values=sensitive_values,
            ),
            diagnostic_headers=_safe_response_headers(exc),
        ) from None
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Upstox response was not a JSON object")
    return payload


def _token_exchange_error_from_provider(
    error: UpstoxProviderHttpError,
    *,
    sensitive_values: tuple[str | None, ...],
) -> UpstoxTokenExchangeError:
    message = (
        _token_exchange_user_message(
            error.provider_error_code,
            error.sanitized_message,
        )
        or error.sanitized_message
    )
    return UpstoxTokenExchangeError(
        category=_token_exchange_category_from_error(
            error.provider_error_code,
            message,
        ),
        http_status=error.http_status,
        provider_error_code=error.provider_error_code,
        sanitized_message=_sanitize_message(
            message,
            sensitive_values=sensitive_values,
        ),
        diagnostic_headers=error.diagnostic_headers,
    )


def _token_exchange_error(
    error: urllib.error.HTTPError,
    *,
    sensitive_values: tuple[str | None, ...],
) -> UpstoxTokenExchangeError:
    raw_body = _read_http_error_body(error)
    provider_code, provider_message = _provider_error(raw_body)
    if _is_cloudflare_error_1010(raw_body):
        provider_code = "1010"
        provider_message = (
            "Cloudflare rejected the OAuth token request with error 1010 "
            "before Upstox OAuth validation completed."
        )
    provider_message = _token_exchange_user_message(provider_code, provider_message)
    sanitized = _sanitize_message(
        provider_message or f"Upstox token exchange failed with HTTP {error.code}.",
        sensitive_values=sensitive_values,
    )
    return UpstoxTokenExchangeError(
        category=_token_exchange_category_from_error(provider_code, sanitized),
        http_status=error.code,
        provider_error_code=provider_code,
        sanitized_message=sanitized,
        diagnostic_headers=_safe_response_headers(error),
    )


def _read_http_error_body(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read()
    except OSError:
        return ""
    if not body:
        return ""
    return body.decode("utf-8", errors="replace")


def _provider_error(raw_body: str) -> tuple[str | None, str | None]:
    if not raw_body.strip():
        return None, None
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return None, "Provider returned a non-JSON error response."
    if not isinstance(payload, dict):
        return None, "Provider returned an unexpected error response."
    errors = payload.get("errors")
    first = None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        first = errors[0]
    elif isinstance(payload.get("error"), dict):
        first = payload["error"]
    if first is None:
        message = payload.get("message")
        code = payload.get("error_code") or payload.get("errorCode")
        return _optional_text(code), _optional_text(message)
    code = first.get("error_code") or first.get("errorCode")
    message = first.get("message")
    return _optional_text(code), _optional_text(message)


def _is_cloudflare_error_1010(raw_body: str) -> bool:
    body = raw_body.casefold()
    return "cloudflare" in body and ("error 1010" in body or ">1010<" in body)


def _safe_response_headers(error: urllib.error.HTTPError) -> dict[str, str]:
    headers = error.headers
    if headers is None:
        return {}
    diagnostics: dict[str, str] = {}
    for name in ("Content-Type", "Server", "CF-Ray", "CF-Mitigated"):
        value = headers.get(name)
        if value:
            diagnostics[name] = str(value)
    return diagnostics


def _token_exchange_category(
    provider_code: str | None,
) -> UpstoxTokenExchangeFailure:
    return {
        "UDAPI100069": UpstoxTokenExchangeFailure.INVALID_CLIENT_CREDENTIALS,
        "UDAPI100070": UpstoxTokenExchangeFailure.REDIRECT_URI_INVALID,
        "UDAPI100057": (UpstoxTokenExchangeFailure.INVALID_OR_USED_AUTHORIZATION_CODE),
        "UDAPI100058": UpstoxTokenExchangeFailure.NO_ACTIVE_TRADING_SEGMENTS,
    }.get(
        provider_code or "",
        UpstoxTokenExchangeFailure.TOKEN_EXCHANGE_PROVIDER_REJECTION,
    )


def _token_exchange_category_from_error(
    provider_code: str | None,
    sanitized_message: str,
) -> UpstoxTokenExchangeFailure:
    if (
        provider_code == "1010"
        and "cloudflare" in sanitized_message.casefold()
        and "1010" in sanitized_message
    ):
        return UpstoxTokenExchangeFailure.CLOUDFLARE_CLIENT_SIGNATURE_REJECTED
    return _token_exchange_category(provider_code)


def _token_exchange_user_message(
    provider_code: str | None,
    fallback: str | None,
) -> str | None:
    if provider_code == "UDAPI100058":
        return (
            "Upstox account has no active trading segments. Reactivate at least one "
            "segment in Upstox, wait for activation confirmation, and then generate "
            "a fresh authorization code."
        )
    return fallback


def _sanitize_message(
    message: str,
    *,
    sensitive_values: tuple[str | None, ...],
) -> str:
    sanitized = message
    for value in sensitive_values:
        if value:
            sanitized = sanitized.replace(value, "[redacted]")
    return sanitized


def _request_sensitive_values(
    request: urllib.request.Request,
) -> tuple[str | None, ...]:
    raw = request.data
    if not raw:
        return ()
    if not isinstance(raw, bytes | bytearray):
        return ()
    try:
        parsed = urllib.parse.parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        return ()
    values: list[str | None] = []
    for field in ("code", "client_secret", "access_token"):
        values.extend(parsed.get(field, ()))
    return tuple(values)


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _credential_status(
    name: str,
    value: str | None,
    purpose: UpstoxCredentialPurpose,
) -> UpstoxCredentialStatus:
    return UpstoxCredentialStatus(
        name=name,
        purpose=purpose,
        configured=bool(value),
        source="environment" if value else "unavailable",
        masked_suffix=_masked_suffix(value),
        validation_status="CONFIGURED" if value else "MISSING",
    )


def _masked_suffix(value: str | None) -> str | None:
    if not value:
        return None
    suffix = value[-4:] if len(value) >= 4 else value
    return f"***{suffix}"


def _fingerprint(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _next_upstox_expiry(now: datetime) -> datetime:
    local = now.astimezone(IST)
    expiry = datetime.combine(local.date(), time(3, 30), tzinfo=IST)
    if local >= expiry:
        expiry = expiry + timedelta(days=1)
    return expiry.astimezone(UTC)


def _readiness(
    *,
    config: UpstoxAuthConfig,
    token: UpstoxTokenValidation,
    feed: UpstoxFeedAuthorization,
    instrument: UpstoxInstrumentResolution | None,
) -> UpstoxReadinessStatus:
    if not config.access_token:
        return UpstoxReadinessStatus.TOKEN_MISSING
    if token.status is UpstoxTokenStatus.TOKEN_EXPIRED:
        return UpstoxReadinessStatus.TOKEN_EXPIRED
    if token.status is UpstoxTokenStatus.TOKEN_REJECTED:
        return UpstoxReadinessStatus.AUTHENTICATION_FAILED
    if token.status is UpstoxTokenStatus.TOKEN_VALIDATION_FAILED:
        return UpstoxReadinessStatus.AUTHENTICATION_FAILED
    if instrument is not None and instrument.status not in {
        InstrumentResolutionStatus.RESOLVED_EXACT,
        InstrumentResolutionStatus.RESOLVED_ALIAS,
    }:
        return UpstoxReadinessStatus.INSTRUMENT_REGISTRY_UNAVAILABLE
    if feed.status == "FEED_AUTHORIZATION_FAILED":
        return UpstoxReadinessStatus.FEED_AUTHORIZATION_FAILED
    return UpstoxReadinessStatus.PROVIDER_READY


def _health(
    readiness: UpstoxReadinessStatus,
    token: UpstoxTokenValidation,
    feed: UpstoxFeedAuthorization,
) -> UpstoxProviderHealthStatus:
    if token.status in {
        UpstoxTokenStatus.TOKEN_MISSING,
        UpstoxTokenStatus.TOKEN_EXPIRED,
        UpstoxTokenStatus.TOKEN_REJECTED,
        UpstoxTokenStatus.TOKEN_VALIDATION_FAILED,
    }:
        return UpstoxProviderHealthStatus.AUTHENTICATION_REQUIRED
    if feed.status == "FEED_AUTHORIZATION_FAILED":
        return UpstoxProviderHealthStatus.DISCONNECTED
    if readiness is UpstoxReadinessStatus.PROVIDER_READY:
        return UpstoxProviderHealthStatus.HEALTHY
    return UpstoxProviderHealthStatus.DEGRADED


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _text(value: object | None) -> str:
    return "unavailable" if value is None else str(value)


__all__ = [
    "InstrumentResolutionStatus",
    "UPSTOX_MARKET_DATA_FEED_VERSION",
    "UpstoxAuthConfig",
    "UpstoxAuthService",
    "UpstoxCredentialPurpose",
    "UpstoxDisconnectCause",
    "UpstoxFeedAuthorization",
    "UpstoxInstrumentResolution",
    "UpstoxInstrumentResolver",
    "UpstoxProviderHealthStatus",
    "UpstoxProviderPreflight",
    "UpstoxProviderHttpError",
    "UpstoxProviderStatusReport",
    "UpstoxReadinessStatus",
    "UpstoxTokenExchangeError",
    "UpstoxTokenExchangeFailure",
    "UpstoxTokenMetadata",
    "UpstoxTokenStatus",
    "UpstoxTokenValidation",
    "prompt_authorization_code",
    "render_upstox_status",
]
