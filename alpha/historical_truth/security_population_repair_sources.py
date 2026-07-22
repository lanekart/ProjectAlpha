"""Official source parsing and bounded discovery for HTR-010A1."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import requests

from alpha.historical_truth.complete_security_dataset_sources import (
    CompleteDatasetSourceInventory,
)

_SUSPENSION_LINK = re.compile(
    r'href=["\'](?P<url>[^"\']*(?:suspension|suspended)[^"\']*\.xlsx)["\']',
    re.IGNORECASE,
)
_OFFICIAL_HOSTS = frozenset(
    {"nseindia.com", "www.nseindia.com", "nsearchives.nseindia.com"}
)
_HEADERS = {
    "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
    "User-Agent": "ProjectAlpha-HistoricalTruth/1.0",
}


@dataclass(frozen=True, slots=True)
class OfficialMasterRecord:
    symbol: str
    series: str
    isin: str | None
    security_name: str | None
    security_type_flag: str | None
    instrument_type: str | None
    listing_date: date | None
    removal_date: date | None
    readmission_date: date | None
    deleted: bool
    checkpoint_date: date
    source_id: str
    source_path: str
    source_sha256: str

    @property
    def identity_key(self) -> str:
        if self.isin:
            return f"nse:isin:{self.isin}"
        material = f"NSE|{self.symbol}|{self.series}".encode()
        return f"nse:synthetic:{hashlib.sha256(material).hexdigest()}"


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    source_id: str
    source_path: str
    source_sha256: str
    source_url: str
    status: str
    evidence_type: str
    failure_code: str | None = None
    failure_detail: str | None = None


class Response(Protocol):
    content: bytes
    status_code: int
    url: str

    def raise_for_status(self) -> None: ...


class Session(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
        allow_redirects: bool,
    ) -> Response: ...


class SecurityPopulationSourceInventory:
    """Read immutable masters and discover official suspension evidence."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.master_root = root / "raw" / "nse" / "security_master" / "historical"
        self.identity_root = root / "raw" / "nse" / "security_identity" / "historical"
        self.destination = root / "raw" / "nse" / "security_population" / "historical"

    def collect(
        self,
        *,
        refresh_sources: bool,
        session: Session | None = None,
    ) -> tuple[
        tuple[OfficialMasterRecord, ...],
        tuple[SourceEvidence, ...],
    ]:
        records = (*self._historical_master(), *self._current_equity_master())
        inventory = CompleteDatasetSourceInventory(self.root)
        if refresh_sources:
            inventory.collect(
                refresh_sources=True,
                verify_only=False,
                session=cast(Any, session),
            )
        inherited, _ = inventory.collect(
            refresh_sources=False,
            verify_only=False,
            session=cast(Any, session),
        )
        normalized: dict[str, SourceEvidence] = {}
        for item in inherited:
            record = SourceEvidence(
                item.source_id,
                item.source_path or "",
                item.sha256 or "",
                item.source_url,
                "REUSED" if item.source_path and item.sha256 else item.status.value,
                item.source_family,
                item.failure_code,
                item.failure_code if item.failure_code else None,
            )
            previous = normalized.get(record.source_id)
            if previous is None or record.source_path > previous.source_path:
                normalized[record.source_id] = record
        if refresh_sources:
            self._suspension_workbook(True, session)
        workbook = self._suspension_workbook(False, session)
        normalized[workbook.source_id] = workbook
        evidence = list(normalized.values())
        return (
            tuple(sorted(records, key=_master_sort_key)),
            tuple(sorted(evidence, key=lambda item: item.source_id)),
        )

    def _historical_master(self) -> tuple[OfficialMasterRecord, ...]:
        records: list[OfficialMasterRecord] = []
        for path in sorted(self.master_root.glob("[0-9][0-9][0-9][0-9]/*.csv.gz")):
            checksum = _sha256(path)
            checkpoint = _checkpoint_from_path(path)
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    records.append(
                        OfficialMasterRecord(
                            symbol=_clean(row.get("TckrSymb")) or "",
                            series=_clean(row.get("SctySrs")) or "",
                            isin=_valid_isin(row.get("ISIN")),
                            security_name=_clean(row.get("FinInstrmNm")),
                            security_type_flag=_clean(row.get("SctyTpFlg")),
                            instrument_type=_clean(row.get("InstrmTp"))
                            or _clean(row.get("FinInstrmTp")),
                            listing_date=_epoch_date(row.get("ListgDt")),
                            removal_date=_epoch_date(row.get("RmvlDt")),
                            readmission_date=_epoch_date(row.get("RadmssnDt")),
                            deleted=_clean(row.get("DelFlg")) == "Y",
                            checkpoint_date=checkpoint,
                            source_id=f"nse_cm_checkpoint_{checkpoint:%d%m%Y}",
                            source_path=str(path),
                            source_sha256=checksum,
                        )
                    )
        return tuple(records)

    def _current_equity_master(self) -> tuple[OfficialMasterRecord, ...]:
        records: list[OfficialMasterRecord] = []
        for path in sorted(
            self.master_root.glob("reference/*current_equity_list*.csv")
        ):
            checksum = _sha256(path)
            checkpoint = _retrieval_date(path) or date.fromtimestamp(
                path.stat().st_mtime
            )
            with path.open(encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    normalized = {key.strip(): value for key, value in row.items()}
                    records.append(
                        OfficialMasterRecord(
                            symbol=_clean(normalized.get("SYMBOL")) or "",
                            series=_clean(normalized.get("SERIES")) or "EQ",
                            isin=_valid_isin(normalized.get("ISIN NUMBER")),
                            security_name=_clean(normalized.get("NAME OF COMPANY")),
                            security_type_flag="0",
                            instrument_type="EQUITY_ACTIVE_LIST",
                            listing_date=_text_date(normalized.get("DATE OF LISTING")),
                            removal_date=None,
                            readmission_date=None,
                            deleted=False,
                            checkpoint_date=checkpoint,
                            source_id=f"nse_current_equity_{checkpoint.isoformat()}",
                            source_path=str(path),
                            source_sha256=checksum,
                        )
                    )
        return tuple(records)

    def _suspension_workbook(
        self,
        refresh: bool,
        session: Session | None,
    ) -> SourceEvidence:
        links = self._discovered_suspension_links()
        if not links:
            return SourceEvidence(
                "nse_current_suspension_workbook",
                "",
                "",
                "https://www.nseindia.com/regulations/listing-compliance",
                "FAILED",
                "SUSPENSION_AND_RESTORATION",
                "OFFICIAL_SOURCE_NOT_FOUND",
                "official discovery page exposed no suspension workbook",
            )
        url = links[-1]
        existing = sorted(self.destination.glob("nse_suspension_list_*.xlsx"))
        if not refresh:
            if existing:
                path = existing[-1]
                return SourceEvidence(
                    "nse_current_suspension_workbook",
                    str(path),
                    _sha256(path),
                    url,
                    "REUSED",
                    "SUSPENSION_AND_RESTORATION",
                )
            return SourceEvidence(
                "nse_current_suspension_workbook",
                "",
                "",
                url,
                "FAILED",
                "SUSPENSION_AND_RESTORATION",
                "SOURCE_NOT_ACQUIRED",
                "refresh is required for the discovered official workbook",
            )
        client = session or requests.Session()
        try:
            response = client.get(
                url,
                headers=_HEADERS,
                timeout=30.0,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return SourceEvidence(
                "nse_current_suspension_workbook",
                "",
                "",
                url,
                "FAILED",
                "SUSPENSION_AND_RESTORATION",
                "NETWORK_OR_HTTP_ERROR",
                type(exc).__name__,
            )
        host = (urlparse(response.url).hostname or "").lower()
        if host not in _OFFICIAL_HOSTS:
            raise ValueError(
                "suspension evidence redirected outside official NSE hosts"
            )
        checksum = hashlib.sha256(response.content).hexdigest()
        self.destination.mkdir(parents=True, exist_ok=True)
        path = self.destination / f"nse_suspension_list_{checksum}.xlsx"
        if not path.exists():
            path.write_bytes(response.content)
            manifest = {
                "source_id": "nse_current_suspension_workbook",
                "source_url": url,
                "source_path": str(path),
                "retrieval_timestamp": datetime.now(UTC).isoformat(),
                "sha256": checksum,
                "byte_size": len(response.content),
                "status": "ACQUIRED",
            }
            path.with_suffix(path.suffix + ".manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return SourceEvidence(
            "nse_current_suspension_workbook",
            str(path),
            checksum,
            url,
            "ACQUIRED",
            "SUSPENSION_AND_RESTORATION",
        )

    def _discovered_suspension_links(self) -> tuple[str, ...]:
        links: set[str] = set()
        for path in sorted(self.identity_root.glob("*listing_compliance*html")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            links.update(
                match.group("url") for match in _SUSPENSION_LINK.finditer(text)
            )
        return tuple(sorted(links))


def verify_source_checksums(evidence: tuple[SourceEvidence, ...]) -> None:
    for item in evidence:
        if not item.source_path or not item.source_sha256:
            continue
        path = Path(item.source_path)
        if not path.exists() or _sha256(path) != item.source_sha256:
            raise ValueError(f"source checksum mismatch: {item.source_id}")


def _clean(value: object) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def _valid_isin(value: object) -> str | None:
    text = _clean(value)
    return text if text and len(text) == 12 and text.startswith("IN") else None


def _epoch_date(value: object) -> date | None:
    try:
        timestamp = int(str(value or "0"))
    except ValueError:
        return None
    return datetime.fromtimestamp(timestamp, UTC).date() if timestamp > 0 else None


def _text_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d-%b-%Y").date()
    except ValueError:
        return None


def _checkpoint_from_path(path: Path) -> date:
    match = re.search(r"_(\d{2})(\d{2})(\d{4})_", path.name)
    if not match:
        raise ValueError(f"checkpoint date missing from {path}")
    return date(int(match[3]), int(match[2]), int(match[1]))


def _retrieval_date(path: Path) -> date | None:
    manifest = path.with_suffix(path.suffix + ".manifest.json")
    if not manifest.exists():
        return None
    try:
        payload = json.loads(manifest.read_text())
        value = payload.get("retrieval_timestamp") or payload["acquired_at"]
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _master_sort_key(item: OfficialMasterRecord) -> tuple[object, ...]:
    return (
        item.identity_key,
        item.checkpoint_date,
        item.symbol,
        item.series,
        item.source_id,
    )


__all__ = [
    "OfficialMasterRecord",
    "SecurityPopulationSourceInventory",
    "SourceEvidence",
    "verify_source_checksums",
]
