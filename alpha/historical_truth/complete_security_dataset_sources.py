"""Governed source inventory and supplemental discovery for HTR-010A."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import requests

from alpha.historical_truth.complete_security_dataset_models import (
    RejectedEvidenceRecord,
    SourceInventoryRecord,
    SourceStatus,
)

OFFICIAL_NSE_HOSTS = frozenset(
    {"nseindia.com", "nsearchives.nseindia.com", "archives.nseindia.com"}
)
SOURCE_HEADERS = {
    "Accept": "text/html,application/pdf,text/csv,application/json,*/*",
    "User-Agent": "ProjectAlpha-HistoricalTruth/1.0",
}


@dataclass(frozen=True, slots=True)
class DiscoverySourceSpec:
    source_id: str
    source_family: str
    url: str
    parser: str


SUPPLEMENTAL_DISCOVERY_SPECS = (
    DiscoverySourceSpec(
        "nse_suspended_security_legacy_csv",
        "SUSPENSION_AND_RESTORATION",
        "https://nsearchives.nseindia.com/content/equities/suspended.csv",
        "inventory_only_v1",
    ),
    DiscoverySourceSpec(
        "nse_listing_compliance_suspension_index",
        "SUSPENSION_AND_RESTORATION",
        "https://www.nseindia.com/regulations/listing-compliance",
        "official_discovery_page_v1",
    ),
    DiscoverySourceSpec(
        "nse_circular_archive_suspension_search",
        "SUSPENSION_AND_RESTORATION",
        "https://www.nseindia.com/resources/exchange-communication-circulars",
        "official_discovery_page_v1",
    ),
    DiscoverySourceSpec(
        "nse_compulsory_delisting_index",
        "TERMINATION_AND_DELISTING",
        "https://www.nseindia.com/regulations/listing-compliance",
        "official_discovery_page_v1",
    ),
)


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


class CompleteDatasetSourceInventory:
    """Inventory existing evidence and retain supplemental official documents."""

    def __init__(
        self,
        root: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root
        self.destination = root / "raw" / "nse" / "security_identity" / "historical"
        self._now = now or (lambda: datetime.now(UTC))

    def collect(
        self,
        *,
        refresh_sources: bool,
        verify_only: bool,
        session: HttpSession | None = None,
    ) -> tuple[tuple[SourceInventoryRecord, ...], tuple[RejectedEvidenceRecord, ...]]:
        if refresh_sources and verify_only:
            raise ValueError("refresh_sources and verify_only are mutually exclusive")
        existing = self._existing_governed_manifests()
        if refresh_sources:
            client = session or cast(HttpSession, requests.Session())
            supplemental = tuple(
                self._acquire(spec, client) for spec in SUPPLEMENTAL_DISCOVERY_SPECS
            )
        else:
            supplemental = tuple(
                self._reuse_or_missing(spec) for spec in SUPPLEMENTAL_DISCOVERY_SPECS
            )
        records = tuple(
            sorted(
                (*existing, *supplemental),
                key=lambda item: (item.source_family, item.source_id, item.source_url),
            )
        )
        rejected = tuple(
            RejectedEvidenceRecord(
                item.source_id,
                item.failure_code or "UNKNOWN_FAILURE",
                item.failure_detail or "source was not admitted",
            )
            for item in records
            if item.status in {SourceStatus.FAILED, SourceStatus.REJECTED}
        )
        return records, rejected

    def _existing_governed_manifests(self) -> tuple[SourceInventoryRecord, ...]:
        roots = (
            self.root / "raw" / "nse" / "security_events" / "historical",
            self.root / "raw" / "nse" / "security_master" / "historical",
            self.root / "raw" / "nse" / "corporate_actions" / "historical",
            self.root / "raw" / "nse" / "calendar",
        )
        records: list[SourceInventoryRecord] = []
        for source_root in roots:
            if not source_root.exists():
                continue
            for manifest in sorted(source_root.rglob("*.manifest.json")):
                record = self._manifest_record(manifest)
                if record is not None:
                    records.append(record)
            if source_root.name == "calendar":
                for path in sorted(source_root.glob("*.json")):
                    records.append(self._calendar_record(path))
        deduplicated = {item.source_id: item for item in records}
        return tuple(deduplicated[key] for key in sorted(deduplicated))

    def _manifest_record(self, manifest: Path) -> SourceInventoryRecord | None:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        source_path = payload.get("source_path") or str(manifest).removesuffix(
            ".manifest.json"
        )
        source_id = str(payload.get("source_id") or manifest.stem)
        family = str(
            payload.get("source_family") or _family_from_path(Path(str(source_path)))
        )
        status_text = str(payload.get("status") or "REUSED").upper()
        status = SourceStatus.REUSED
        if status_text in SourceStatus.__members__:
            status = SourceStatus[status_text]
            if status is SourceStatus.ACQUIRED:
                status = SourceStatus.REUSED
        return SourceInventoryRecord(
            source_id=source_id,
            source_family=family,
            source_url=str(payload.get("source_url") or "official:local-evidence"),
            source_path=str(source_path),
            official_host=True,
            retrieval_timestamp=_optional_text(payload.get("retrieval_timestamp")),
            http_status=_optional_int(payload.get("http_status")),
            content_type=_optional_text(payload.get("content_type")),
            redirects=tuple(str(item) for item in payload.get("redirects", ())),
            byte_size=int(
                payload.get("byte_size") or _file_size(Path(str(source_path)))
            ),
            sha256=_optional_text(payload.get("sha256"))
            or _checksum_if_exists(Path(str(source_path))),
            parser=str(payload.get("parser") or "governed_manifest_v1"),
            records_parsed=int(
                payload.get("records_parsed")
                or payload.get("events_parsed")
                or payload.get("records_inspected")
                or 0
            ),
            records_admitted=int(
                payload.get("records_admitted") or payload.get("events_admitted") or 0
            ),
            records_rejected=int(
                payload.get("records_rejected") or payload.get("events_rejected") or 0
            ),
            status=status,
            failure_code=_optional_text(payload.get("failure_code")),
            failure_detail=_sanitize(_optional_text(payload.get("failure_detail"))),
        )

    def _calendar_record(self, path: Path) -> SourceInventoryRecord:
        raw = path.read_bytes()
        return SourceInventoryRecord(
            source_id=f"official-calendar:{hashlib.sha256(raw).hexdigest()}",
            source_family="SESSION_CALENDAR",
            source_url="https://www.nseindia.com/api/holiday-master?type=trading",
            source_path=str(path),
            official_host=True,
            retrieval_timestamp=None,
            http_status=None,
            content_type="application/json",
            redirects=(),
            byte_size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            parser="official_session_calendar_v1",
            records_parsed=0,
            records_admitted=0,
            records_rejected=0,
            status=SourceStatus.REUSED,
            failure_code=None,
            failure_detail=None,
        )

    def _acquire(
        self,
        spec: DiscoverySourceSpec,
        session: HttpSession,
    ) -> SourceInventoryRecord:
        host = (urlparse(spec.url).hostname or "").lower()
        if not _official_host(host):
            return self._failure(
                spec, "OFFICIAL_SOURCE_NOT_FOUND", "source host is not governed"
            )
        try:
            response = session.get(
                spec.url,
                headers=SOURCE_HEADERS,
                timeout=30.0,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            code = _http_failure_code(status)
            return self._failure(
                spec, code, f"official source returned HTTP {status}", status
            )
        except requests.RequestException as exc:
            return self._failure(spec, "NETWORK_ERROR", type(exc).__name__)
        except Exception as exc:
            return self._failure(spec, "UNKNOWN_FAILURE", type(exc).__name__)
        final_host = (urlparse(response.url).hostname or "").lower()
        redirects = tuple(str(item.url) for item in response.history) + (
            str(response.url),
        )
        if not _official_host(final_host):
            return self._failure(
                spec,
                "HTTP_ACCESS_DENIED",
                "redirect left the governed NSE host boundary",
                response.status_code,
            )
        raw = response.content
        content_type = response.headers.get("Content-Type")
        if not raw:
            return self._failure(
                spec,
                "EMPTY_RESPONSE",
                "official source returned no bytes",
                response.status_code,
            )
        if _looks_like_access_denial(raw):
            return self._failure(
                spec,
                "HTTP_ACCESS_DENIED",
                "official source returned an access-denial document",
                response.status_code,
            )
        digest = hashlib.sha256(raw).hexdigest()
        suffix = _suffix(content_type, raw)
        self.destination.mkdir(parents=True, exist_ok=True)
        path = self.destination / f"{spec.source_id}_{digest}{suffix}"
        if path.exists() and path.read_bytes() != raw:
            return self._failure(
                spec, "CHECKSUM_MISMATCH", "immutable source path has different bytes"
            )
        if not path.exists():
            path.write_bytes(raw)
        retrieved = self._now().astimezone(UTC).isoformat()
        record = SourceInventoryRecord(
            spec.source_id,
            spec.source_family,
            spec.url,
            str(path),
            True,
            retrieved,
            response.status_code,
            content_type,
            redirects,
            len(raw),
            digest,
            spec.parser,
            0,
            0,
            0,
            SourceStatus.ACQUIRED,
            None,
            None,
        )
        manifest = path.with_suffix(path.suffix + ".manifest.json")
        if not manifest.exists():
            manifest.write_text(
                json.dumps(_jsonable(asdict(record)), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return record

    def _reuse_or_missing(self, spec: DiscoverySourceSpec) -> SourceInventoryRecord:
        manifests = sorted(self.destination.glob(f"{spec.source_id}_*.manifest.json"))
        if not manifests:
            return self._failure(
                spec,
                "OFFICIAL_SOURCE_NOT_FOUND",
                "no immutable local evidence exists; acquisition was not requested",
            )
        record = self._manifest_record(manifests[-1])
        if record is None:
            return self._failure(
                spec, "PARSER_FAILED", "stored source manifest is invalid"
            )
        return SourceInventoryRecord(
            **{**asdict(record), "status": SourceStatus.REUSED}
        )

    @staticmethod
    def _failure(
        spec: DiscoverySourceSpec,
        code: str,
        detail: str,
        status: int | None = None,
    ) -> SourceInventoryRecord:
        return SourceInventoryRecord(
            spec.source_id,
            spec.source_family,
            spec.url,
            None,
            _official_host((urlparse(spec.url).hostname or "").lower()),
            None,
            status,
            None,
            (),
            0,
            None,
            spec.parser,
            0,
            0,
            0,
            SourceStatus.FAILED,
            code,
            _sanitize(detail),
        )


def _official_host(host: str) -> bool:
    return any(host == item or host.endswith(f".{item}") for item in OFFICIAL_NSE_HOSTS)


def _http_failure_code(status: int | None) -> str:
    if status == 404:
        return "OFFICIAL_SOURCE_NOT_FOUND"
    if status == 429:
        return "HTTP_RATE_LIMITED"
    if status in {401, 403}:
        return "HTTP_ACCESS_DENIED"
    return "NETWORK_ERROR"


def _looks_like_access_denial(raw: bytes) -> bool:
    sample = raw[:4096].lower()
    return b"access denied" in sample or b"request rejected" in sample


def _suffix(content_type: str | None, raw: bytes) -> str:
    content = (content_type or "").lower()
    if raw.startswith(b"%PDF") or "application/pdf" in content:
        return ".pdf"
    if "json" in content:
        return ".json"
    if "csv" in content:
        return ".csv"
    return ".html"


def _family_from_path(path: Path) -> str:
    text = str(path).lower()
    if "corporate_action" in text:
        return "CORPORATE_ACTION_AND_REORGANISATION"
    if "security_master" in text:
        return "CHECKPOINT_MASTER"
    if "calendar" in text:
        return "SESSION_CALENDAR"
    return "IDENTITY_AND_MEMBERSHIP_EVENTS"


def _checksum_if_exists(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def _optional_text(value: object) -> str | None:
    return str(value) if value not in {None, ""} else None


def _optional_int(value: object) -> int | None:
    try:
        return int(cast(Any, value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sanitize(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("\n", " ").replace("\r", " ")[:500]


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, SourceStatus):
        return value.value
    return value


__all__ = [
    "CompleteDatasetSourceInventory",
    "DiscoverySourceSpec",
    "SUPPLEMENTAL_DISCOVERY_SPECS",
]
