"""Official source acquisition and parsing for DSI-010B6 identity evidence."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import requests

from alpha.historical_truth.corporate_action_price_sources import (
    OfficialCorporateActionStore,
    default_corporate_action_sources,
)

OFFICIAL_IDENTITY_HOSTS = frozenset(
    {"nseindia.com", "www.nseindia.com", "nsearchives.nseindia.com"}
)
SOURCE_HEADERS = {
    "Accept": "text/html,application/pdf,application/octet-stream,*/*",
    "User-Agent": "ProjectAlpha-HistoricalTruth/1.0",
}
HISTORICAL_MASTER_PRODUCT_URL = (
    "https://www.nseindia.com/static/market-data/eod-historical-data-subscription"
)
HISTORICAL_MASTER_SPECIFICATION_URL = (
    "https://nsearchives.nseindia.com/content/press/Data_details_CM.pdf"
)


class IdentitySourceState(StrEnum):
    ACQUIRED = "ACQUIRED"
    REUSED = "REUSED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    SUBSCRIPTION_REQUIRED = "SUBSCRIPTION_REQUIRED"


class HttpResponse(Protocol):
    status_code: int
    content: bytes
    headers: Mapping[str, str]
    url: str
    history: Sequence[Any]

    def raise_for_status(self) -> None: ...


class HttpSession(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        allow_redirects: bool,
    ) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class OfficialIdentitySourceSpec:
    source_id: str
    source_url: str
    parser: str
    effective_date: date | None = None
    allowed_symbols: tuple[str, ...] = ()
    evidence_only: bool = False


@dataclass(frozen=True, slots=True)
class OfficialIdentitySourceRecord:
    source_id: str
    source_url: str
    source_path: str | None
    sha256: str | None
    parser: str
    effective_date: date | None
    state: IdentitySourceState
    official_host: bool
    byte_size: int
    record_count: int
    acquired_at: str | None
    redirect_chain: tuple[str, ...]
    limitation: str | None


@dataclass(frozen=True, slots=True)
class OfficialIdentityObservation:
    source_id: str
    source_sha256: str
    source_url: str
    effective_date: date
    symbol: str
    series: str
    isin: str
    security_name: str | None
    status: str
    evidence_type: str

    @property
    def identity_key(self) -> str:
        return f"nse:isin:{self.isin}"


@dataclass(frozen=True, slots=True)
class ParsedIdentitySource:
    inventory: OfficialIdentitySourceRecord
    observations: tuple[OfficialIdentityObservation, ...]
    rejections: tuple[str, ...]


def default_identity_source_specs() -> tuple[OfficialIdentitySourceSpec, ...]:
    """Return official public evidence relevant to the signed B5 queue."""

    return (
        OfficialIdentitySourceSpec(
            source_id="nse_press_20100628_permitted_securities",
            source_url=("https://nsearchives.nseindia.com/content/press/28062010.htm"),
            parser="nse_press_permitted_security_html_v1",
            effective_date=date(2010, 6, 30),
            allowed_symbols=("MANAPPURAM",),
        ),
        OfficialIdentitySourceSpec(
            source_id="nse_historical_cm_master_specification",
            source_url=HISTORICAL_MASTER_SPECIFICATION_URL,
            parser="evidence_only_binary_v1",
            evidence_only=True,
        ),
    )


class OfficialPre2016IdentityStore:
    """Retain official identity evidence without altering canonical candles."""

    def __init__(
        self,
        root: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root / "raw" / "nse" / "identity_master" / "historical"
        self._now = now or (lambda: datetime.now(UTC))

    def acquire(
        self,
        specs: Sequence[OfficialIdentitySourceSpec],
        *,
        session: HttpSession | None = None,
        timeout_seconds: float = 45.0,
    ) -> tuple[ParsedIdentitySource, ...]:
        client = (
            session if session is not None else cast(HttpSession, requests.Session())
        )
        return tuple(self._acquire_one(spec, client, timeout_seconds) for spec in specs)

    def verify_or_missing(
        self,
        specs: Sequence[OfficialIdentitySourceSpec],
    ) -> tuple[ParsedIdentitySource, ...]:
        return tuple(self._reuse_one(spec) for spec in specs)

    def acquire_historical_action_checkpoints(
        self,
        *,
        root: Path,
        refresh_sources: bool,
    ) -> tuple[Any, ...]:
        """Acquire/reuse complete official NSE action checkpoints before 2005."""

        specs = default_corporate_action_sources(
            date(1995, 1, 1),
            date(2004, 12, 31),
        )
        store = OfficialCorporateActionStore(root)
        if refresh_sources:
            return store.acquire(specs)
        return store.verify_or_missing(specs)

    def _acquire_one(
        self,
        spec: OfficialIdentitySourceSpec,
        session: HttpSession,
        timeout_seconds: float,
    ) -> ParsedIdentitySource:
        host = (urlparse(spec.source_url).hostname or "").lower()
        if host not in OFFICIAL_IDENTITY_HOSTS:
            return self._terminal(
                spec,
                IdentitySourceState.REJECTED,
                "source host is not an approved NSE host",
            )
        try:
            response = session.get(
                spec.source_url,
                headers=SOURCE_HEADERS,
                timeout=timeout_seconds,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return self._terminal(
                spec,
                IdentitySourceState.FAILED,
                f"official NSE request failed with HTTP {status or 'unknown'}",
            )
        except Exception as exc:
            return self._terminal(
                spec,
                IdentitySourceState.FAILED,
                type(exc).__name__,
            )
        redirects = tuple(str(item.url) for item in response.history) + (
            str(response.url),
        )
        if not all(
            (urlparse(item).hostname or "").lower() in OFFICIAL_IDENTITY_HOSTS
            for item in redirects
        ):
            return self._terminal(
                spec,
                IdentitySourceState.REJECTED,
                "response redirected outside approved NSE hosts",
            )
        raw = response.content
        if not raw:
            return self._terminal(
                spec,
                IdentitySourceState.REJECTED,
                "official response was empty",
            )
        digest = hashlib.sha256(raw).hexdigest()
        suffix = ".pdf" if raw.startswith(b"%PDF") else ".html"
        directory = self.root / (
            str(spec.effective_date.year) if spec.effective_date else "reference"
        )
        directory.mkdir(parents=True, exist_ok=True)
        source_path = directory / f"{spec.source_id}_{digest}{suffix}"
        if source_path.exists() and source_path.read_bytes() != raw:
            return self._terminal(
                spec,
                IdentitySourceState.REJECTED,
                "checksum-addressed path contains different bytes",
            )
        if not source_path.exists():
            source_path.write_bytes(raw)
        manifest_path = source_path.with_suffix(source_path.suffix + ".manifest.json")
        acquired_at = self._now().astimezone(UTC).isoformat()
        if manifest_path.exists():
            payload = _object(manifest_path)
            acquired_at = str(payload.get("acquired_at") or acquired_at)
            redirects = tuple(payload.get("redirect_chain") or redirects)
        observations, rejections = _parse_source(spec, raw, digest)
        inventory = OfficialIdentitySourceRecord(
            source_id=spec.source_id,
            source_url=spec.source_url,
            source_path=str(source_path),
            sha256=digest,
            parser=spec.parser,
            effective_date=spec.effective_date,
            state=IdentitySourceState.ACQUIRED,
            official_host=True,
            byte_size=len(raw),
            record_count=len(observations),
            acquired_at=acquired_at,
            redirect_chain=redirects,
            limitation=None,
        )
        if not manifest_path.exists():
            manifest_path.write_text(
                json.dumps(_jsonable(asdict(inventory)), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        return ParsedIdentitySource(inventory, observations, rejections)

    def _reuse_one(
        self,
        spec: OfficialIdentitySourceSpec,
    ) -> ParsedIdentitySource:
        manifests = sorted(self.root.glob(f"**/{spec.source_id}_*.manifest.json"))
        if not manifests:
            return self._terminal(
                spec,
                IdentitySourceState.FAILED,
                "immutable official source is unavailable in verify-only mode",
            )
        payload = _object(manifests[-1])
        source_path = Path(str(payload.get("source_path") or ""))
        if not source_path.is_file():
            return self._terminal(
                spec,
                IdentitySourceState.FAILED,
                "manifest source path is unavailable",
            )
        raw = source_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != payload.get("sha256"):
            return self._terminal(
                spec,
                IdentitySourceState.REJECTED,
                "immutable source checksum mismatch",
            )
        observations, rejections = _parse_source(spec, raw, digest)
        inventory = OfficialIdentitySourceRecord(
            source_id=spec.source_id,
            source_url=spec.source_url,
            source_path=str(source_path),
            sha256=digest,
            parser=spec.parser,
            effective_date=spec.effective_date,
            state=IdentitySourceState.REUSED,
            official_host=True,
            byte_size=len(raw),
            record_count=len(observations),
            acquired_at=_optional_text(payload.get("acquired_at")),
            redirect_chain=tuple(payload.get("redirect_chain") or ()),
            limitation=None,
        )
        return ParsedIdentitySource(inventory, observations, rejections)

    def _terminal(
        self,
        spec: OfficialIdentitySourceSpec,
        state: IdentitySourceState,
        limitation: str,
    ) -> ParsedIdentitySource:
        return ParsedIdentitySource(
            OfficialIdentitySourceRecord(
                source_id=spec.source_id,
                source_url=spec.source_url,
                source_path=None,
                sha256=None,
                parser=spec.parser,
                effective_date=spec.effective_date,
                state=state,
                official_host=(
                    (urlparse(spec.source_url).hostname or "").lower()
                    in OFFICIAL_IDENTITY_HOSTS
                ),
                byte_size=0,
                record_count=0,
                acquired_at=None,
                redirect_chain=(),
                limitation=limitation,
            ),
            (),
            (limitation,),
        )


class _CellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._inside_cell = False
        self._current: list[str] = []
        self.cells: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.lower() in {"td", "th"}:
            self._inside_cell = True
            self._current = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"} and self._inside_cell:
            value = " ".join("".join(self._current).split())
            self.cells.append(html.unescape(value))
            self._inside_cell = False
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._inside_cell:
            self._current.append(data)


def _parse_source(
    spec: OfficialIdentitySourceSpec,
    raw: bytes,
    digest: str,
) -> tuple[tuple[OfficialIdentityObservation, ...], tuple[str, ...]]:
    if spec.evidence_only:
        return (), ()
    if spec.parser != "nse_press_permitted_security_html_v1":
        return (), (f"unsupported identity parser: {spec.parser}",)
    if spec.effective_date is None:
        return (), ("effective date is required for permitted-security evidence",)
    parser = _CellParser()
    parser.feed(raw.decode("windows-1252", errors="replace"))
    allowed = {symbol.upper() for symbol in spec.allowed_symbols}
    observations: list[OfficialIdentityObservation] = []
    rejections: list[str] = []
    for index, cell in enumerate(parser.cells):
        symbol = cell.strip().upper()
        if symbol not in allowed:
            continue
        window = parser.cells[index : index + 5]
        isin = next(
            (
                value.strip().upper()
                for value in window
                if re.fullmatch(r"IN[A-Z0-9]{10}", value.strip().upper())
            ),
            None,
        )
        if isin is None:
            rejections.append(f"{symbol}: official row did not expose an ISIN")
            continue
        observations.append(
            OfficialIdentityObservation(
                source_id=spec.source_id,
                source_sha256=digest,
                source_url=spec.source_url,
                effective_date=spec.effective_date,
                symbol=symbol,
                series="EQ",
                isin=isin,
                security_name=None,
                status="PERMITTED_TO_TRADE",
                evidence_type="OFFICIAL_NSE_LISTING_PRESS_RELEASE",
            )
        )
    if allowed - {item.symbol for item in observations}:
        missing = sorted(allowed - {item.symbol for item in observations})
        rejections.append(f"expected symbols absent from official source: {missing}")
    return tuple(observations), tuple(rejections)


def historical_master_evidence_ceiling() -> OfficialIdentitySourceRecord:
    """Describe the authoritative data product that is not publicly downloadable."""

    return OfficialIdentitySourceRecord(
        source_id="nse_paid_historical_cm_masters",
        source_url=HISTORICAL_MASTER_PRODUCT_URL,
        source_path=None,
        sha256=None,
        parser="nse_monthly_historical_master_v1",
        effective_date=None,
        state=IdentitySourceState.SUBSCRIPTION_REQUIRED,
        official_host=True,
        byte_size=0,
        record_count=0,
        acquired_at=None,
        redirect_chain=(),
        limitation=(
            "NSE documents monthly Masters snapshots with ISIN, symbol, series, "
            "name and deletion state, but the 2005-2015 bytes require an NSE "
            "historical-data subscription and were not available to this run."
        ),
    )


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _jsonable(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


__all__ = [
    "HISTORICAL_MASTER_PRODUCT_URL",
    "HISTORICAL_MASTER_SPECIFICATION_URL",
    "IdentitySourceState",
    "OfficialIdentityObservation",
    "OfficialIdentitySourceRecord",
    "OfficialIdentitySourceSpec",
    "OfficialPre2016IdentityStore",
    "ParsedIdentitySource",
    "default_identity_source_specs",
    "historical_master_evidence_ceiling",
]
