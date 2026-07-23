"""Governed downloader for HTR-010B1F official bridge evidence documents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from alpha.historical_truth.official_bridge_source_role_validation import (
    validate_source_role_url,
)

HTR010B1F_DOWNLOAD_CONTRACT_VERSION = "HTR-010B1F-DOWNLOAD-v1.0.0"

_ALLOWED_HOST_SUFFIXES = (
    "nseindia.com",
    "nsearchives.nseindia.com",
    "bseindia.com",
    "archives.nseindia.com",
    "sebi.gov.in",
    "nsdl.co.in",
    "cdslindia.com",
)
_NSE_ACTION_LANDING_URL = (
    "https://www.nseindia.com/companies-listing/corporate-filings-actions"
)
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _NSE_ACTION_LANDING_URL,
}


@dataclass(frozen=True)
class DownloadResult:
    dossier_id: str
    source_url: str
    final_url: str | None
    relative_path: str | None
    source_sha256: str | None
    file_size_bytes: int | None
    content_type: str | None
    download_state: str
    error: str | None


class OfficialBridgeDocumentDownloader:
    """Download only role-valid official-source documents, fail closed otherwise."""

    def run(
        self,
        *,
        discoveries_path: Path,
        output_root: Path,
    ) -> dict[str, Any]:
        discoveries = _records(discoveries_path)
        output_root.mkdir(parents=True, exist_ok=True)
        results = tuple(self._download(row, output_root) for row in discoveries)
        report = {
            "contract_version": HTR010B1F_DOWNLOAD_CONTRACT_VERSION,
            "input_discovery_count": len(discoveries),
            "downloaded_document_count": sum(
                row.download_state == "DOWNLOADED_VERIFIED_BYTES" for row in results
            ),
            "rejected_source_count": sum(
                row.download_state == "REJECTED_NON_OFFICIAL_SOURCE" for row in results
            ),
            "rejected_role_source_count": sum(
                row.download_state == "REJECTED_ROLE_SOURCE_MISMATCH" for row in results
            ),
            "failed_download_count": sum(
                row.download_state == "DOWNLOAD_FAILED" for row in results
            ),
            "pending_url_count": sum(
                row.download_state == "PENDING_SOURCE_URL" for row in results
            ),
            "benchmark_replay_count": 0,
            "production_influence": False,
            "downloads": [row.__dict__ for row in results],
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "htr010b1f_download_report.json"
        registry_path = output / "htr010b1f_download_registry.json"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        registry_path.write_text(
            json.dumps(report.get("downloads", []), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report_path, registry_path

    def _download(self, row: dict[str, Any], output_root: Path) -> DownloadResult:
        dossier_id = str(row.get("dossier_id") or "")
        source_url = str(row.get("source_url") or "")
        evidence_role = str(row.get("evidence_role") or "")
        if not source_url:
            return DownloadResult(
                dossier_id=dossier_id,
                source_url="",
                final_url=None,
                relative_path=None,
                source_sha256=None,
                file_size_bytes=None,
                content_type=None,
                download_state="PENDING_SOURCE_URL",
                error=None,
            )
        if not _official_url(source_url):
            return DownloadResult(
                dossier_id=dossier_id,
                source_url=source_url,
                final_url=None,
                relative_path=None,
                source_sha256=None,
                file_size_bytes=None,
                content_type=None,
                download_state="REJECTED_NON_OFFICIAL_SOURCE",
                error="SOURCE_HOST_NOT_ALLOWLISTED",
            )
        if evidence_role:
            role_valid, role_reason = validate_source_role_url(
                evidence_role,
                source_url,
            )
            if not role_valid:
                return DownloadResult(
                    dossier_id=dossier_id,
                    source_url=source_url,
                    final_url=None,
                    relative_path=None,
                    source_sha256=None,
                    file_size_bytes=None,
                    content_type=None,
                    download_state="REJECTED_ROLE_SOURCE_MISMATCH",
                    error=role_reason,
                )
        request_url = _resolved_request_url(row, source_url)
        try:
            payload, final_url, content_type = _fetch(request_url)
            if not _official_url(final_url):
                raise ValueError("redirected outside official-source allowlist")
            if evidence_role:
                final_valid, final_reason = validate_source_role_url(
                    evidence_role,
                    final_url,
                )
                if not final_valid:
                    raise ValueError(final_reason)
        except Exception as exc:  # pragma: no cover - network dependent
            return DownloadResult(
                dossier_id=dossier_id,
                source_url=source_url,
                final_url=None,
                relative_path=None,
                source_sha256=None,
                file_size_bytes=None,
                content_type=None,
                download_state="DOWNLOAD_FAILED",
                error=f"{type(exc).__name__}: {exc}",
            )

        digest = sha256(payload).hexdigest()
        suffix = _suffix(content_type, final_url)
        safe_dossier = dossier_id.replace(":", "_").replace("/", "_") or "unknown"
        relative_path = Path(safe_dossier) / f"{digest}{suffix}"
        destination = output_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return DownloadResult(
            dossier_id=dossier_id,
            source_url=source_url,
            final_url=final_url,
            relative_path=relative_path.as_posix(),
            source_sha256=digest,
            file_size_bytes=len(payload),
            content_type=content_type,
            download_state="DOWNLOADED_VERIFIED_BYTES",
            error=None,
        )


def _resolved_request_url(row: dict[str, Any], source_url: str) -> str:
    role = str(row.get("evidence_role") or "").upper()
    parsed = urlparse(source_url)
    if role != "CORPORATE_ACTION" or parsed.path.lower().startswith("/api/"):
        return source_url

    symbol = str(row.get("post_symbol") or row.get("pre_symbol") or "").upper()
    effective = _as_date(row.get("effective_date"))
    if not symbol or effective is None:
        return source_url
    parameters = {
        "index": "equities",
        "symbol": symbol,
        "from_date": (effective - timedelta(days=10)).strftime("%d-%m-%Y"),
        "to_date": (effective + timedelta(days=10)).strftime("%d-%m-%Y"),
    }
    return "https://www.nseindia.com/api/corporates-corporateActions?" + urlencode(
        parameters
    )


def _fetch(source_url: str) -> tuple[bytes, str, str | None]:
    parsed = urlparse(source_url)
    is_nse_action_api = (
        (parsed.hostname or "").lower() == "www.nseindia.com"
        and parsed.path.lower() == "/api/corporates-corporateactions"
    )
    if is_nse_action_api:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        landing = Request(_NSE_ACTION_LANDING_URL, headers=_BROWSER_HEADERS)
        with opener.open(landing, timeout=30):  # noqa: S310
            pass
        request = Request(source_url, headers=_BROWSER_HEADERS)
        with opener.open(request, timeout=30) as response:  # noqa: S310
            payload = response.read()
            return payload, response.geturl(), response.headers.get_content_type()

    request = Request(source_url, headers=_BROWSER_HEADERS)
    with urlopen(request, timeout=30) as response:  # noqa: S310
        payload = response.read()
        return payload, response.geturl(), response.headers.get_content_type()


def _as_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _official_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host == suffix or host.endswith("." + suffix)
        for suffix in _ALLOWED_HOST_SUFFIXES
    )


def _suffix(content_type: str | None, url: str) -> str:
    if content_type == "application/pdf":
        return ".pdf"
    if content_type in {"application/json", "text/json"}:
        return ".json"
    if content_type in {"text/csv", "application/csv"}:
        return ".csv"
    if content_type in {"text/html", "application/xhtml+xml"}:
        return ".html"
    path_suffix = Path(urlparse(url).path).suffix.lower()
    return path_suffix if path_suffix and len(path_suffix) <= 10 else ".bin"


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        for key in ("records", "rows", "discoveries", "downloads"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return tuple(row for row in rows if isinstance(row, dict))
    raise ValueError(f"unsupported record payload: {path}")


def _digest(report: dict[str, Any]) -> str:
    payload = {**report, "report_sha256": ""}
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "HTR010B1F_DOWNLOAD_CONTRACT_VERSION",
    "OfficialBridgeDocumentDownloader",
]
