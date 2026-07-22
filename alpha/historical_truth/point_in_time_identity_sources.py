"""Governed official-source acquisition for HTR-009A."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import requests

from alpha.historical_truth.point_in_time_identity_models import (
    EvidenceType,
    OfficialSourceSpec,
    RejectedEvidenceRecord,
    SourceInventoryRecord,
    SourceStatus,
    valid_isin,
)

OFFICIAL_HOSTS = frozenset({"nseindia.com", "nsearchives.nseindia.com"})
DEFAULT_HEADERS = {
    "Accept": "text/csv,application/gzip,application/octet-stream,*/*",
    "User-Agent": "ProjectAlpha-HistoricalTruth/1.0",
}


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
class ParsedSource:
    inventory: SourceInventoryRecord
    rows: tuple[dict[str, str], ...]
    rejected: tuple[RejectedEvidenceRecord, ...]


def default_source_specs(as_of: date) -> tuple[OfficialSourceSpec, ...]:
    stamp = as_of.strftime("%d%m%Y")
    return (
        OfficialSourceSpec(
            source_id=f"nse_cm_security_{stamp}",
            evidence_type=EvidenceType.MII_SECURITY_MASTER,
            url=(
                "https://nsearchives.nseindia.com/content/cm/"
                f"NSE_CM_security_{stamp}.csv.gz"
            ),
            parser="mii_security_csv_v1",
            expected_segment="CM",
            effective_date=as_of,
        ),
        OfficialSourceSpec(
            source_id="nse_current_equity_list",
            evidence_type=EvidenceType.CURRENT_SECURITY_LIST,
            url=("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"),
            parser="nse_equity_list_csv_v1",
            expected_segment="CM",
            current_only=True,
        ),
        OfficialSourceSpec(
            source_id="nse_symbol_change_history",
            evidence_type=EvidenceType.SYMBOL_CHANGE_HISTORY,
            url=("https://nsearchives.nseindia.com/content/equities/symbolchange.csv"),
            parser="nse_symbol_change_csv_v1",
            expected_segment="CM",
        ),
        OfficialSourceSpec(
            source_id="nse_name_change_history",
            evidence_type=EvidenceType.NAME_CHANGE_HISTORY,
            url=("https://nsearchives.nseindia.com/content/equities/namechange.csv"),
            parser="nse_name_change_csv_v1",
            expected_segment="CM",
        ),
    )


class OfficialSecurityEvidenceStore:
    """Acquire and verify immutable NSE identity evidence."""

    def __init__(
        self,
        root: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root / "raw" / "nse" / "security_master" / "historical"
        self._now = now or (lambda: datetime.now(UTC))

    def acquire(
        self,
        specs: Sequence[OfficialSourceSpec],
        *,
        session: HttpSession | None = None,
        timeout_seconds: float = 30.0,
    ) -> tuple[ParsedSource, ...]:
        client = (
            session if session is not None else cast(HttpSession, requests.Session())
        )
        return tuple(self._acquire_one(spec, client, timeout_seconds) for spec in specs)

    def verify_or_missing(
        self,
        specs: Sequence[OfficialSourceSpec],
    ) -> tuple[ParsedSource, ...]:
        return tuple(self._reuse_one(spec) for spec in specs)

    def _acquire_one(
        self,
        spec: OfficialSourceSpec,
        session: HttpSession,
        timeout_seconds: float,
    ) -> ParsedSource:
        host = (urlparse(spec.url).hostname or "").lower()
        if not self._official_host(host):
            return self._rejected_source(spec, "THIRD_PARTY_SOURCE", host)
        date_match = re.search(r"security_(\d{8})", spec.url, flags=re.IGNORECASE)
        if date_match and spec.effective_date is not None:
            expected_stamp = spec.effective_date.strftime("%d%m%Y")
            if date_match.group(1) != expected_stamp:
                return self._rejected_source(
                    spec,
                    "WRONG_YEAR_OR_EFFECTIVE_DATE",
                    f"expected {expected_stamp}; URL carries {date_match.group(1)}",
                )
        try:
            response = session.get(
                spec.url,
                headers=DEFAULT_HEADERS,
                timeout=timeout_seconds,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return self._failed_source(spec, "NETWORK_OR_HTTP_ERROR", str(exc))
        except Exception as exc:  # fake deterministic transports may not use requests
            return self._failed_source(spec, "NETWORK_OR_HTTP_ERROR", str(exc))
        raw = response.content
        content_type = response.headers.get("Content-Type")
        final_host = (urlparse(response.url).hostname or "").lower()
        if not self._official_host(final_host):
            return self._rejected_source(
                spec,
                "UNOFFICIAL_REDIRECT",
                final_host,
                content_type=content_type,
            )
        validation = self._validate_document(raw, content_type)
        if validation is not None:
            return self._rejected_source(
                spec,
                validation,
                "source bytes failed document validation",
                content_type=content_type,
            )
        parsed_rows, rejected = self._parse_rows(spec, raw)
        digest = hashlib.sha256(raw).hexdigest()
        extension = ".csv.gz" if raw.startswith(b"\x1f\x8b") else ".csv"
        directory = self.root / (
            str(spec.effective_date.year) if spec.effective_date else "reference"
        )
        directory.mkdir(parents=True, exist_ok=True)
        source_path = directory / f"{spec.source_id}_{digest}{extension}"
        if source_path.exists() and source_path.read_bytes() != raw:
            return self._rejected_source(
                spec,
                "CHECKSUM_PATH_CONFLICT",
                str(source_path),
            )
        if not source_path.exists():
            source_path.write_bytes(raw)
        acquired_at = self._now().astimezone(UTC).isoformat()
        redirects = tuple(str(item.url) for item in response.history) + (
            str(response.url),
        )
        manifest_path = source_path.with_suffix(source_path.suffix + ".manifest.json")
        existing_manifest: dict[str, Any] | None = None
        if manifest_path.exists():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing_manifest = loaded
            except json.JSONDecodeError:
                existing_manifest = None
        if existing_manifest is not None:
            acquired_at = str(existing_manifest.get("acquired_at") or acquired_at)
            redirects = tuple(existing_manifest.get("redirect_chain", redirects))
        inventory = SourceInventoryRecord(
            source_id=spec.source_id,
            evidence_type=spec.evidence_type,
            source_path=str(source_path),
            source_url=spec.url,
            official_host=True,
            sha256=digest,
            acquired_at=acquired_at,
            covered_from=spec.effective_date,
            covered_to=spec.effective_date,
            file_format=extension.removeprefix("."),
            parser=spec.parser,
            row_count=len(parsed_rows) + len(rejected),
            admitted_records=len(parsed_rows),
            rejected_records=len(rejected),
            status=SourceStatus.ACQUIRED,
            limitations=self._limitations(spec),
            redirect_chain=redirects,
            content_type=content_type,
        )
        if existing_manifest is None:
            manifest_path.write_text(
                json.dumps(
                    self._inventory_payload(inventory),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        return ParsedSource(inventory, parsed_rows, rejected)

    def _reuse_one(self, spec: OfficialSourceSpec) -> ParsedSource:
        manifest = self._latest_manifest(spec.source_id)
        if manifest is None:
            return self._failed_source(
                spec,
                "IMMUTABLE_SOURCE_NOT_FOUND",
                "verification-only mode cannot acquire missing evidence",
            )
        return self._load_manifest(spec, manifest)

    def _load_manifest(self, spec: OfficialSourceSpec, path: Path) -> ParsedSource:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            source_path = Path(str(payload["source_path"]))
            raw = source_path.read_bytes()
            actual = hashlib.sha256(raw).hexdigest()
            expected = str(payload["sha256"])
            if actual != expected:
                return self._rejected_source(
                    spec,
                    "CHECKSUM_MISMATCH",
                    f"expected {expected}; observed {actual}",
                )
            rows, rejected = self._parse_rows(spec, raw)
            inventory = SourceInventoryRecord(
                source_id=spec.source_id,
                evidence_type=spec.evidence_type,
                source_path=str(source_path),
                source_url=spec.url,
                official_host=True,
                sha256=actual,
                acquired_at=str(payload.get("acquired_at") or "") or None,
                covered_from=spec.effective_date,
                covered_to=spec.effective_date,
                file_format=str(payload.get("file_format", "csv")),
                parser=spec.parser,
                row_count=len(rows) + len(rejected),
                admitted_records=len(rows),
                rejected_records=len(rejected),
                status=SourceStatus.REUSED,
                limitations=self._limitations(spec),
                redirect_chain=tuple(payload.get("redirect_chain", ())),
                content_type=payload.get("content_type"),
            )
            return ParsedSource(inventory, rows, rejected)
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            return self._rejected_source(spec, "INVALID_MANIFEST", str(exc))

    def _parse_rows(
        self,
        spec: OfficialSourceSpec,
        raw: bytes,
    ) -> tuple[tuple[dict[str, str], ...], tuple[RejectedEvidenceRecord, ...]]:
        decoded = gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
        text = decoded.decode("utf-8-sig", errors="replace")
        if spec.evidence_type is EvidenceType.SYMBOL_CHANGE_HISTORY:
            reader = csv.DictReader(
                io.StringIO(text),
                fieldnames=(
                    "company_name",
                    "old_symbol",
                    "new_symbol",
                    "effective_date",
                ),
            )
        else:
            reader = csv.DictReader(io.StringIO(text))
        admitted: list[dict[str, str]] = []
        rejected: list[RejectedEvidenceRecord] = []
        seen: set[tuple[tuple[str, str], ...]] = set()
        for row_number, raw_row in enumerate(reader, 2):
            row = {
                str(key).strip(): str(value or "").strip()
                for key, value in raw_row.items()
                if key is not None
            }
            normalized = tuple(sorted(row.items()))
            if normalized in seen:
                rejected.append(
                    RejectedEvidenceRecord(
                        spec.source_id,
                        spec.url,
                        "DUPLICATE_RECORD",
                        "duplicate source row",
                        row_number,
                    )
                )
                continue
            seen.add(normalized)
            segment = self._field(row, "segment", "sgmt", "market_segment")
            if segment and segment.upper() not in {"CM", "CAPITAL MARKET"}:
                rejected.append(
                    RejectedEvidenceRecord(
                        spec.source_id,
                        spec.url,
                        "WRONG_SEGMENT",
                        f"expected CM; observed {segment}",
                        row_number,
                    )
                )
                continue
            isin = self._field(row, "isin", "isin_number", "isin_no")
            if isin and not valid_isin(isin):
                rejected.append(
                    RejectedEvidenceRecord(
                        spec.source_id,
                        spec.url,
                        "MALFORMED_ISIN",
                        "record contains a structurally invalid ISIN",
                        row_number,
                        isin,
                    )
                )
                continue
            if not row:
                continue
            admitted.append(row)
        conflicts: set[tuple[str, str]] = set()
        isins_by_security: dict[tuple[str, str], set[str]] = {}
        for row in admitted:
            symbol = self._field(row, "symbol", "tckrsymb", "security_symbol")
            series = self._field(row, "series", "sctysrs", "security_series")
            isin = self._field(row, "isin", "isin_number", "isin_no")
            if symbol and series and isin:
                key = (symbol.upper(), series.upper())
                isins_by_security.setdefault(key, set()).add(isin.upper())
                if len(isins_by_security[key]) > 1:
                    conflicts.add(key)
        if conflicts:
            retained: list[dict[str, str]] = []
            for row_number, row in enumerate(admitted, 2):
                key = (
                    self._field(
                        row,
                        "symbol",
                        "tckrsymb",
                        "security_symbol",
                    ).upper(),
                    self._field(
                        row,
                        "series",
                        "sctysrs",
                        "security_series",
                    ).upper(),
                )
                if key in conflicts:
                    rejected.append(
                        RejectedEvidenceRecord(
                            spec.source_id,
                            spec.url,
                            "CONFLICTING_RECORDS",
                            "same symbol-series has multiple ISINs in one source",
                            row_number,
                            ":".join(key),
                        )
                    )
                else:
                    retained.append(row)
            admitted = retained
        return tuple(admitted), tuple(rejected)

    @staticmethod
    def _field(row: Mapping[str, str], *names: str) -> str:
        lookup = {key.lower().replace(" ", "_"): value for key, value in row.items()}
        return next((lookup[name] for name in names if lookup.get(name)), "")

    @staticmethod
    def _validate_document(raw: bytes, content_type: str | None) -> str | None:
        if not raw:
            return "EMPTY_RESPONSE"
        prefix = raw[:512].lower().lstrip()
        if prefix.startswith((b"<!doctype html", b"<html")):
            return "HTML_MASQUERADING_AS_DATA"
        if content_type and "html" in content_type.lower():
            return "HTML_MASQUERADING_AS_DATA"
        try:
            decoded = gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
        except (gzip.BadGzipFile, EOFError):
            return "INVALID_GZIP"
        if b"," not in decoded[:4096]:
            return "UNEXPECTED_DOCUMENT_TYPE"
        return None

    def _latest_manifest(self, source_id: str) -> Path | None:
        paths = sorted(self.root.glob(f"**/{source_id}_*.manifest.json"))
        if not paths:
            return None

        def acquisition_key(path: Path) -> tuple[str, str]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                acquired_at = str(payload.get("acquired_at", ""))
            except (OSError, json.JSONDecodeError, AttributeError):
                acquired_at = ""
            return acquired_at, str(path)

        return max(paths, key=acquisition_key)

    @staticmethod
    def _official_host(host: str) -> bool:
        return any(host == item or host.endswith(f".{item}") for item in OFFICIAL_HOSTS)

    @staticmethod
    def _limitations(spec: OfficialSourceSpec) -> tuple[str, ...]:
        limitations: list[str] = []
        if spec.current_only:
            limitations.append("CURRENT_ONLY_NOT_HISTORICAL_BACKFILL")
        if spec.effective_date is not None:
            limitations.append("SINGLE_EFFECTIVE_DATE_ONLY")
        if spec.evidence_type in {
            EvidenceType.SYMBOL_CHANGE_HISTORY,
            EvidenceType.NAME_CHANGE_HISTORY,
        }:
            limitations.append("DOES_NOT_PROVE_DAILY_TRADING_MEMBERSHIP")
        return tuple(limitations)

    @staticmethod
    def _inventory_payload(record: SourceInventoryRecord) -> dict[str, Any]:
        return {
            "source_id": record.source_id,
            "evidence_type": record.evidence_type.value,
            "source_path": record.source_path,
            "source_url": record.source_url,
            "official_host": record.official_host,
            "sha256": record.sha256,
            "acquired_at": record.acquired_at,
            "covered_from": (
                record.covered_from.isoformat() if record.covered_from else None
            ),
            "covered_to": record.covered_to.isoformat() if record.covered_to else None,
            "file_format": record.file_format,
            "parser": record.parser,
            "row_count": record.row_count,
            "admitted_records": record.admitted_records,
            "rejected_records": record.rejected_records,
            "status": record.status.value,
            "limitations": list(record.limitations),
            "redirect_chain": list(record.redirect_chain),
            "content_type": record.content_type,
        }

    def _failed_source(
        self,
        spec: OfficialSourceSpec,
        code: str,
        detail: str,
    ) -> ParsedSource:
        return self._terminal_source(spec, SourceStatus.FAILED, code, detail)

    def _rejected_source(
        self,
        spec: OfficialSourceSpec,
        code: str,
        detail: str,
        *,
        content_type: str | None = None,
    ) -> ParsedSource:
        return self._terminal_source(
            spec,
            SourceStatus.REJECTED,
            code,
            detail,
            content_type=content_type,
        )

    def _terminal_source(
        self,
        spec: OfficialSourceSpec,
        status: SourceStatus,
        code: str,
        detail: str,
        *,
        content_type: str | None = None,
    ) -> ParsedSource:
        host = (urlparse(spec.url).hostname or "").lower()
        inventory = SourceInventoryRecord(
            source_id=spec.source_id,
            evidence_type=spec.evidence_type,
            source_path=None,
            source_url=spec.url,
            official_host=self._official_host(host),
            sha256=None,
            acquired_at=None,
            covered_from=spec.effective_date,
            covered_to=spec.effective_date,
            file_format="unknown",
            parser=spec.parser,
            row_count=0,
            admitted_records=0,
            rejected_records=1,
            status=status,
            limitations=self._limitations(spec) + (code,),
            content_type=content_type,
        )
        rejected = RejectedEvidenceRecord(
            spec.source_id,
            spec.url,
            code,
            detail,
        )
        return ParsedSource(inventory, (), (rejected,))


__all__ = [
    "DEFAULT_HEADERS",
    "OFFICIAL_HOSTS",
    "OfficialSecurityEvidenceStore",
    "ParsedSource",
    "default_source_specs",
]
