"""Official-document recovery for DSI-010 pre-2011 session calendars."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

from .pre2016_external_validation_models import Pre2016ExternalValidationError

PRE2011_CALENDAR_YEARS = tuple(range(2005, 2011))
_ALLOWED_OFFICIAL_HOSTS = frozenset(
    {
        "nseindia.com",
        "www.nseindia.com",
        "nsearchives.nseindia.com",
        "archives.nseindia.com",
    }
)
_ALLOWED_SEGMENT_SCOPES = frozenset(
    {
        "CAPITAL_MARKET",
        "FUTURES_AND_OPTIONS",
        "EXCHANGE_WIDE",
        "CROSS_SEGMENT_CORROBORATION",
        "UNKNOWN",
    }
)
_FULL_SCOPE = frozenset({"CAPITAL_MARKET", "EXCHANGE_WIDE"})
_PARTIAL_SCOPE = frozenset({"FUTURES_AND_OPTIONS", "CROSS_SEGMENT_CORROBORATION"})


class _HttpResponse(Protocol):
    status_code: int
    content: bytes
    headers: Mapping[str, str]
    url: str


class _HttpSession(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> _HttpResponse: ...


class _RequestsResponseAdapter:
    def __init__(self, response: requests.Response) -> None:
        self.status_code = response.status_code
        self.content = response.content
        self.headers: Mapping[str, str] = dict(response.headers)
        self.url = response.url


class _RequestsSessionAdapter:
    def __init__(self) -> None:
        self._session = requests.Session()

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> _HttpResponse:
        response = self._session.get(url, headers=headers, timeout=timeout)
        return _RequestsResponseAdapter(response)


@dataclass(frozen=True, slots=True)
class Pre2011CalendarSourceCandidate:
    """One deterministic official circular candidate."""

    year: int
    source_id: str
    source_url: str
    segment_scope: str
    expected_sha256: str | None
    expected_download_number: str | None
    expected_circular_date: str | None
    expected_subject: str
    requires_muhurat_statement: bool


@dataclass(frozen=True, slots=True)
class Pre2011CalendarSourceAttempt:
    """One immutable transport and content-validation result."""

    year: int
    source_id: str
    requested_url: str
    final_url: str
    segment_scope: str
    http_status: int | None = None
    content_type: str = ""
    response_bytes: int = 0
    response_sha256: str | None = None
    pdf_signature_valid: bool = False
    text_extraction_status: str = "NOT_ATTEMPTED"
    extracted_text_sha256: str | None = None
    exchange_match: bool = False
    segment_match: bool = False
    subject_match: bool = False
    year_match: bool = False
    download_number_match: bool = False
    circular_date_match: bool = False
    holiday_table_match: bool = False
    muhurat_statement_match: bool = False
    content_validation_passed: bool = False
    recovery_state: str = "OFFICIAL_SOURCE_NOT_FOUND"
    document_path: str | None = None
    extracted_text_path: str | None = None
    duplicate_of_source_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Pre2011CalendarRecoveryResult:
    """Recovery outcome across all requested pre-2011 years."""

    attempts: tuple[Pre2011CalendarSourceAttempt, ...]
    requested_years: tuple[int, ...]
    fully_recovered_years: tuple[int, ...]
    partially_recovered_years: tuple[int, ...]
    unrecovered_years: tuple[int, ...]


def recover_pre2011_official_calendar_sources(
    *,
    candidate_registry: Path,
    output: Path,
    timeout_seconds: float = 30.0,
    session: _HttpSession | None = None,
) -> Pre2011CalendarRecoveryResult:
    """Download and validate official NSE circular candidates fail-closed."""

    candidates = _load_candidates(candidate_registry)
    documents = output / "documents"
    extracted = output / "extracted_text"
    documents.mkdir(parents=True, exist_ok=True)
    extracted.mkdir(parents=True, exist_ok=True)
    client: _HttpSession = session or _RequestsSessionAdapter()
    headers = {
        "User-Agent": "ProjectAlpha-HistoricalTruth/1.0",
        "Accept": "application/pdf,application/octet-stream,*/*",
    }
    seen_hashes: dict[str, str] = {}
    attempts = tuple(
        _recover_candidate(
            candidate=candidate,
            documents=documents,
            extracted=extracted,
            client=client,
            headers=headers,
            timeout_seconds=timeout_seconds,
            seen_hashes=seen_hashes,
        )
        for candidate in candidates
    )
    requested = tuple(sorted({item.year for item in candidates}))
    fully = _recovered_years(attempts, "VERIFIED_OFFICIAL_EVIDENCE")
    partial = tuple(
        year
        for year in _recovered_years(
            attempts,
            "PARTIALLY_VERIFIED_OFFICIAL_EVIDENCE",
        )
        if year not in fully
    )
    unrecovered = tuple(
        year for year in requested if year not in fully and year not in partial
    )
    return Pre2011CalendarRecoveryResult(
        attempts=attempts,
        requested_years=requested,
        fully_recovered_years=fully,
        partially_recovered_years=partial,
        unrecovered_years=unrecovered,
    )


def export_pre2011_calendar_recovery(
    result: Pre2011CalendarRecoveryResult,
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic attempt, summary, and evidence-hash artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    attempts_csv = output / "source_candidate_attempts.csv"
    attempts_json = output / "source_candidate_attempts.json"
    summary_json = output / "source_recovery_summary.json"
    summary_markdown = output / "source_recovery_summary.md"
    hashes_path = output / "evidence_hashes.txt"
    rows = tuple(
        cast(dict[str, object], asdict(attempt)) for attempt in result.attempts
    )
    _write_csv(attempts_csv, rows)
    attempts_json.write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    accepted = _count_state(result, "VERIFIED_OFFICIAL_EVIDENCE")
    partial = _count_state(result, "PARTIALLY_VERIFIED_OFFICIAL_EVIDENCE")
    summary = {
        "requested_years": list(result.requested_years),
        "fully_recovered_years": list(result.fully_recovered_years),
        "partially_recovered_years": list(result.partially_recovered_years),
        "unrecovered_years": list(result.unrecovered_years),
        "attempt_count": len(result.attempts),
        "official_documents_accepted": accepted,
        "cross_segment_only_sources": partial,
        "calendar_certification_permitted": False,
        "certification_state": "incomplete_official_evidence",
        "classification_inferred_from_archive_status": False,
        "classification_inferred_from_observed_candles": False,
        "production_influence": False,
    }
    summary_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_markdown.write_text(
        _render_markdown(result, accepted=accepted, partial=partial),
        encoding="utf-8",
    )
    hashes_path.write_text(_render_hashes(result), encoding="utf-8")
    return (
        attempts_csv,
        attempts_json,
        summary_json,
        summary_markdown,
        hashes_path,
    )


def _recover_candidate(
    *,
    candidate: Pre2011CalendarSourceCandidate,
    documents: Path,
    extracted: Path,
    client: _HttpSession,
    headers: Mapping[str, str],
    timeout_seconds: float,
    seen_hashes: dict[str, str],
) -> Pre2011CalendarSourceAttempt:
    base = _base_attempt(candidate)
    try:
        response = client.get(
            candidate.source_url,
            headers=headers,
            timeout=timeout_seconds,
        )
    except (OSError, requests.RequestException) as exc:
        return replace(base, error=f"{type(exc).__name__}: {exc}")

    raw = response.content
    digest = hashlib.sha256(raw).hexdigest() if raw else None
    content_type = str(response.headers.get("Content-Type") or "")
    pdf_signature = raw.startswith(b"%PDF-")
    document_path = _persist_document(
        candidate,
        documents=documents,
        raw=raw,
        digest=digest,
        pdf_signature=pdf_signature,
    )
    base = replace(
        base,
        final_url=response.url,
        http_status=response.status_code,
        content_type=content_type,
        response_bytes=len(raw),
        response_sha256=digest,
        pdf_signature_valid=pdf_signature,
        document_path=str(document_path) if document_path else None,
    )
    if response.status_code != 200:
        return replace(base, error=f"HTTP_{response.status_code}")
    if not pdf_signature:
        error = (
            "HTML_RESPONSE_REJECTED"
            if "html" in content_type.casefold() or raw.lstrip().startswith(b"<")
            else "PDF_SIGNATURE_MISSING"
        )
        return replace(
            base,
            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",
            error=error,
        )
    if candidate.expected_sha256 and digest != candidate.expected_sha256:
        return replace(
            base,
            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",
            error="SOURCE_DOCUMENT_HASH_MISMATCH",
        )
    if digest is None:
        return replace(
            base,
            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",
            error="EMPTY_SOURCE_DOCUMENT",
        )
    duplicate = seen_hashes.get(digest)
    if duplicate is not None:
        return replace(
            base,
            recovery_state="DUPLICATE_DOCUMENT",
            duplicate_of_source_id=duplicate,
            error="DUPLICATE_SOURCE_DOCUMENT_SHA256",
        )
    seen_hashes[digest] = candidate.source_id
    try:
        text = _extract_pdf_text(raw)
    except (OSError, ValueError) as exc:
        return replace(
            base,
            text_extraction_status="FAILED",
            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",
            error=f"PDF_TEXT_EXTRACTION_FAILED:{type(exc).__name__}",
        )

    text_path, text_digest = _persist_text(candidate, extracted, digest, text)
    checks = _validate_content(candidate, text)
    valid = all(checks.values())
    state = _validated_state(candidate.segment_scope, valid)
    return replace(
        base,
        text_extraction_status="EXTRACTED",
        extracted_text_sha256=text_digest,
        exchange_match=checks["exchange_match"],
        segment_match=checks["segment_match"],
        subject_match=checks["subject_match"],
        year_match=checks["year_match"],
        download_number_match=checks["download_number_match"],
        circular_date_match=checks["circular_date_match"],
        holiday_table_match=checks["holiday_table_match"],
        muhurat_statement_match=checks["muhurat_statement_match"],
        content_validation_passed=valid,
        recovery_state=state,
        extracted_text_path=str(text_path),
        error=None if valid else "MANDATORY_CONTENT_VALIDATION_FAILED",
    )


def _base_attempt(
    candidate: Pre2011CalendarSourceCandidate,
) -> Pre2011CalendarSourceAttempt:
    return Pre2011CalendarSourceAttempt(
        year=candidate.year,
        source_id=candidate.source_id,
        requested_url=candidate.source_url,
        final_url=candidate.source_url,
        segment_scope=candidate.segment_scope,
    )


def _persist_document(
    candidate: Pre2011CalendarSourceCandidate,
    *,
    documents: Path,
    raw: bytes,
    digest: str | None,
    pdf_signature: bool,
) -> Path | None:
    if not raw or digest is None:
        return None
    suffix = ".pdf" if pdf_signature else ".bin"
    path = (
        documents
        / str(candidate.year)
        / f"{_safe_token(candidate.source_id)}_{digest[:12]}{suffix}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_DOCUMENT_IMMUTABILITY_VIOLATION"
        )
    path.write_bytes(raw)
    return path


def _persist_text(
    candidate: Pre2011CalendarSourceCandidate,
    root: Path,
    digest: str,
    text: str,
) -> tuple[Path, str]:
    rendered = text.rstrip() + "\n"
    path = (
        root
        / str(candidate.year)
        / f"{_safe_token(candidate.source_id)}_{digest[:12]}.txt"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return path, hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _validated_state(scope: str, valid: bool) -> str:
    if valid and scope in _FULL_SCOPE:
        return "VERIFIED_OFFICIAL_EVIDENCE"
    if valid and scope in _PARTIAL_SCOPE:
        return "PARTIALLY_VERIFIED_OFFICIAL_EVIDENCE"
    return "OFFICIAL_SOURCE_CONTENT_INVALID"


def _validate_content(
    candidate: Pre2011CalendarSourceCandidate,
    text: str,
) -> dict[str, bool]:
    normalized = _normalize(text)
    tokens = {
        "CAPITAL_MARKET": ("capital market segment",),
        "FUTURES_AND_OPTIONS": (
            "futures and options segment",
            "futures & options segment",
            "f&o segment",
        ),
        "EXCHANGE_WIDE": ("national stock exchange of india",),
        "CROSS_SEGMENT_CORROBORATION": (
            "capital market segment",
            "futures and options segment",
            "futures & options segment",
            "f&o segment",
        ),
        "UNKNOWN": (),
    }
    holiday_table = any(
        re.search(pattern, text, flags=re.IGNORECASE) is not None
        for pattern in (
            r"\b\d{1,2}[-/]\w{3,9}[-/]\d{2,4}\b",
            r"\b\d{4}-\d{2}-\d{2}\b",
        )
    )
    return {
        "exchange_match": "national stock exchange of india" in normalized,
        "segment_match": any(
            token in normalized for token in tokens[candidate.segment_scope]
        ),
        "subject_match": _normalize(candidate.expected_subject) in normalized,
        "year_match": str(candidate.year) in normalized,
        "download_number_match": (
            candidate.expected_download_number is None
            or candidate.expected_download_number in normalized
        ),
        "circular_date_match": (
            candidate.expected_circular_date is None
            or candidate.expected_circular_date in normalized
        ),
        "holiday_table_match": holiday_table,
        "muhurat_statement_match": (
            not candidate.requires_muhurat_statement or "muhurat trading" in normalized
        ),
    }


def _extract_pdf_text(raw: bytes) -> str:
    reader = PdfReader(BytesIO(raw))
    pages: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(text)
    rendered = "\n".join(pages)
    if not rendered:
        raise ValueError("PDF_TEXT_EMPTY")
    return rendered


def _load_candidates(path: Path) -> tuple[Pre2011CalendarSourceCandidate, ...]:
    if not path.is_file():
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_CANDIDATE_REGISTRY_MISSING"
        )
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_CANDIDATE_REGISTRY_INVALID"
        ) from exc
    if not isinstance(payload, dict):
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_CANDIDATE_REGISTRY_INVALID"
        )
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_CANDIDATE_REGISTRY_EMPTY"
        )
    candidates: list[Pre2011CalendarSourceCandidate] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            raise Pre2016ExternalValidationError(
                "PRE2011_CALENDAR_CANDIDATE_REGISTRY_INVALID"
            )
        candidates.append(_candidate_from_payload(item))
    identities = {(item.year, item.source_id, item.source_url) for item in candidates}
    if len(identities) != len(candidates):
        raise Pre2016ExternalValidationError("PRE2011_CALENDAR_CANDIDATE_DUPLICATE")
    return tuple(
        sorted(
            candidates,
            key=lambda item: (item.year, item.source_id, item.source_url),
        )
    )


def _candidate_from_payload(
    payload: Mapping[str, object],
) -> Pre2011CalendarSourceCandidate:
    raw_year = payload.get("year")
    if isinstance(raw_year, bool) or not isinstance(raw_year, (int, str)):
        raise Pre2016ExternalValidationError("PRE2011_CALENDAR_CANDIDATE_INVALID")
    try:
        year = int(raw_year)
    except ValueError as exc:
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_CANDIDATE_INVALID"
        ) from exc
    source_id = str(payload.get("source_id") or "").strip()
    source_url = str(payload.get("source_url") or "").strip()
    segment_scope = str(payload.get("segment_scope") or "").strip().upper()
    expected_subject = str(payload.get("expected_subject") or "").strip()
    if year not in PRE2011_CALENDAR_YEARS:
        raise Pre2016ExternalValidationError("PRE2011_CALENDAR_CANDIDATE_YEAR_INVALID")
    if not source_id or not expected_subject:
        raise Pre2016ExternalValidationError("PRE2011_CALENDAR_CANDIDATE_INVALID")
    _validate_official_url(source_url)
    if segment_scope not in _ALLOWED_SEGMENT_SCOPES:
        raise Pre2016ExternalValidationError("PRE2011_CALENDAR_SEGMENT_SCOPE_INVALID")
    expected_sha256 = _optional_string(payload.get("expected_sha256"))
    if expected_sha256 is not None and not re.fullmatch(
        r"[0-9a-f]{64}", expected_sha256
    ):
        raise Pre2016ExternalValidationError("PRE2011_CALENDAR_EXPECTED_SHA256_INVALID")
    requires_muhurat = payload.get("requires_muhurat_statement", False)
    if not isinstance(requires_muhurat, bool):
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_MUHURAT_REQUIREMENT_INVALID"
        )
    return Pre2011CalendarSourceCandidate(
        year=year,
        source_id=source_id,
        source_url=source_url,
        segment_scope=segment_scope,
        expected_sha256=expected_sha256,
        expected_download_number=_optional_string(
            payload.get("expected_download_number")
        ),
        expected_circular_date=_optional_string(payload.get("expected_circular_date")),
        expected_subject=expected_subject,
        requires_muhurat_statement=requires_muhurat,
    )


def _recovered_years(
    attempts: tuple[Pre2011CalendarSourceAttempt, ...],
    state: str,
) -> tuple[int, ...]:
    years = {attempt.year for attempt in attempts if attempt.recovery_state == state}
    return tuple(sorted(years))


def _count_state(result: Pre2011CalendarRecoveryResult, state: str) -> int:
    return sum(attempt.recovery_state == state for attempt in result.attempts)


def _validate_official_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_OFFICIAL_HOSTS:
        raise Pre2016ExternalValidationError("PRE2011_CALENDAR_SOURCE_URL_INVALID")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().casefold()
    return normalized or None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return token or "source"


def _write_csv(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    fieldnames = tuple(rows[0]) if rows else ("year", "source_id")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(
    result: Pre2011CalendarRecoveryResult,
    *,
    accepted: int,
    partial: int,
) -> str:
    return "\n".join(
        (
            "# DSI-010 Pre-2011 Official Calendar Recovery",
            "",
            f"- Requested years: {', '.join(map(str, result.requested_years))}",
            "- Fully recovered years: "
            + (", ".join(map(str, result.fully_recovered_years)) or "NONE"),
            "- Partially recovered years: "
            + (", ".join(map(str, result.partially_recovered_years)) or "NONE"),
            "- Unrecovered years: "
            + (", ".join(map(str, result.unrecovered_years)) or "NONE"),
            f"- Official documents accepted: {accepted}",
            f"- Cross-segment-only sources: {partial}",
            "- Calendar certification permitted: false",
            "- Production influence: false",
            "",
        )
    )


def _render_hashes(result: Pre2011CalendarRecoveryResult) -> str:
    rows: list[str] = []
    for attempt in result.attempts:
        if attempt.response_sha256 and attempt.document_path:
            rows.append(f"{attempt.response_sha256}  {attempt.document_path}")
        if attempt.extracted_text_sha256 and attempt.extracted_text_path:
            rows.append(
                f"{attempt.extracted_text_sha256}  {attempt.extracted_text_path}"
            )
    return "\n".join(rows) + ("\n" if rows else "")


__all__ = [
    "PRE2011_CALENDAR_YEARS",
    "Pre2011CalendarRecoveryResult",
    "Pre2011CalendarSourceAttempt",
    "Pre2011CalendarSourceCandidate",
    "export_pre2011_calendar_recovery",
    "recover_pre2011_official_calendar_sources",
]
