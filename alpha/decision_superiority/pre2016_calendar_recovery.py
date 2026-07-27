"""Official-document recovery for DSI-010 pre-2011 session calendars."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol
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
        return _RequestsResponseAdapter(
            self._session.get(url, headers=headers, timeout=timeout)
        )


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
    http_status: int | None
    content_type: str
    response_bytes: int
    response_sha256: str | None
    pdf_signature_valid: bool
    text_extraction_status: str
    extracted_text_sha256: str | None
    exchange_match: bool
    segment_match: bool
    subject_match: bool
    year_match: bool
    download_number_match: bool
    circular_date_match: bool
    holiday_table_match: bool
    muhurat_statement_match: bool
    content_validation_passed: bool
    recovery_state: str
    document_path: str | None
    extracted_text_path: str | None
    duplicate_of_source_id: str | None
    error: str | None


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
    output.mkdir(parents=True, exist_ok=True)
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
    requested_years = tuple(sorted({candidate.year for candidate in candidates}))
    fully_recovered = tuple(
        year
        for year in requested_years
        if any(
            attempt.year == year
            and attempt.recovery_state == "VERIFIED_OFFICIAL_EVIDENCE"
            for attempt in attempts
        )
    )
    partially_recovered = tuple(
        year
        for year in requested_years
        if year not in fully_recovered
        and any(
            attempt.year == year
            and attempt.recovery_state
            == "PARTIALLY_VERIFIED_OFFICIAL_EVIDENCE"
            for attempt in attempts
        )
    )
    unrecovered = tuple(
        year
        for year in requested_years
        if year not in fully_recovered and year not in partially_recovered
    )
    return Pre2011CalendarRecoveryResult(
        attempts=attempts,
        requested_years=requested_years,
        fully_recovered_years=fully_recovered,
        partially_recovered_years=partially_recovered,
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

    rows = tuple(asdict(attempt) for attempt in result.attempts)
    _write_csv(attempts_csv, rows)
    attempts_json.write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    accepted = sum(
        attempt.recovery_state == "VERIFIED_OFFICIAL_EVIDENCE"
        for attempt in result.attempts
    )
    partial = sum(
        attempt.recovery_state == "PARTIALLY_VERIFIED_OFFICIAL_EVIDENCE"
        for attempt in result.attempts
    )
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
    try:
        response = client.get(
            candidate.source_url,
            headers=headers,
            timeout=timeout_seconds,
        )
    except (OSError, requests.RequestException) as exc:
        return _failed_attempt(
            candidate,
            recovery_state="OFFICIAL_SOURCE_NOT_FOUND",
            error=f"{type(exc).__name__}: {exc}",
        )

    raw = response.content
    digest = hashlib.sha256(raw).hexdigest() if raw else None
    content_type = str(response.headers.get("Content-Type") or "")
    pdf_signature = raw.startswith(b"%PDF-")
    document_path: Path | None = None
    if raw:
        suffix = ".pdf" if pdf_signature else ".bin"
        document_path = (
            documents
            / str(candidate.year)
            / f"{_safe_token(candidate.source_id)}_{digest[:12]}{suffix}"
        )
        document_path.parent.mkdir(parents=True, exist_ok=True)
        if document_path.exists() and document_path.read_bytes() != raw:
            raise Pre2016ExternalValidationError(
                "PRE2011_CALENDAR_DOCUMENT_IMMUTABILITY_VIOLATION"
            )
        document_path.write_bytes(raw)

    base = {
        "year": candidate.year,
        "source_id": candidate.source_id,
        "requested_url": candidate.source_url,
        "final_url": response.url,
        "segment_scope": candidate.segment_scope,
        "http_status": response.status_code,
        "content_type": content_type,
        "response_bytes": len(raw),
        "response_sha256": digest,
        "pdf_signature_valid": pdf_signature,
        "document_path": str(document_path) if document_path else None,
    }
    if response.status_code != 200:
        return _attempt_from_base(
            base,
            recovery_state="OFFICIAL_SOURCE_NOT_FOUND",
            error=f"HTTP_{response.status_code}",
        )
    if not pdf_signature:
        state = (
            "HTML_RESPONSE_REJECTED"
            if "html" in content_type.casefold() or raw.lstrip().startswith(b"<")
            else "PDF_SIGNATURE_MISSING"
        )
        return _attempt_from_base(
            base,
            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",
            error=state,
        )
    if candidate.expected_sha256 and digest != candidate.expected_sha256:
        return _attempt_from_base(
            base,
            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",
            error="SOURCE_DOCUMENT_HASH_MISMATCH",
        )
    if digest is None:
        return _attempt_from_base(
            base,
            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",
            error="EMPTY_SOURCE_DOCUMENT",
        )
    duplicate = seen_hashes.get(digest)
    if duplicate is not None:
        return _attempt_from_base(
            base,
            recovery_state="DUPLICATE_DOCUMENT",
            duplicate_of_source_id=duplicate,
            error="DUPLICATE_SOURCE_DOCUMENT_SHA256",
        )
    seen_hashes[digest] = candidate.source_id

    try:
        text = _extract_pdf_text(raw)
    except (OSError, ValueError) as exc:
        return _attempt_from_base(
            base,
            recovery_state="OFFICIAL_SOURCE_CONTENT_INVALID",
            text_extraction_status="FAILED",
            error=f"PDF_TEXT_EXTRACTION_FAILED:{type(exc).__name__}",
        )
    text_path = (
        extracted
        / str(candidate.year)
        / f"{_safe_token(candidate.source_id)}_{digest[:12]}.txt"
    )
    text_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_text = text.rstrip() + "\n"
    text_path.write_text(rendered_text, encoding="utf-8")
    text_digest = hashlib.sha256(rendered_text.encode("utf-8")).hexdigest()
    checks = _validate_content(candidate, text)
    content_valid = all(checks.values())
    if content_valid and candidate.segment_scope in {
        "CAPITAL_MARKET",
        "EXCHANGE_WIDE",
    }:
        recovery_state = "VERIFIED_OFFICIAL_EVIDENCE"
    elif content_valid and candidate.segment_scope in {
        "FUTURES_AND_OPTIONS",
        "CROSS_SEGMENT_CORROBORATION",
    }:
        recovery_state = "PARTIALLY_VERIFIED_OFFICIAL_EVIDENCE"
    else:
        recovery_state = "OFFICIAL_SOURCE_CONTENT_INVALID"
    return Pre2011CalendarSourceAttempt(
        **base,
        text_extraction_status="EXTRACTED",
        extracted_text_sha256=text_digest,
        **checks,
        content_validation_passed=content_valid,
        recovery_state=recovery_state,
        extracted_text_path=str(text_path),
        duplicate_of_source_id=None,
        error=None if content_valid else "MANDATORY_CONTENT_VALIDATION_FAILED",
    )


def _validate_content(
    candidate: Pre2011CalendarSourceCandidate,
    text: str,
) -> dict[str, bool]:
    normalized = _normalize(text)
    segment_tokens = {
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
    date_patterns = (
        r"\b\d{1,2}[-/]\w{3,9}[-/]\d{2,4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
    )
    return {
        "exchange_match": "national stock exchange of india" in normalized,
        "segment_match": any(
            token in normalized for token in segment_tokens[candidate.segment_scope]
        ),
        "subject_match": _normalize(candidate.expected_subject) in normalized,
        "year_match": str(candidate.year) in normalized,
        "download_number_match": (
            candidate.expected_download_number is None
            or _normalize(candidate.expected_download_number) in normalized
        ),
        "circular_date_match": (
            candidate.expected_circular_date is None
            or _normalize(candidate.expected_circular_date) in normalized
        ),
        "holiday_table_match": any(
            re.search(pattern, text, flags=re.IGNORECASE) is not None
            for pattern in date_patterns
        ),
        "muhurat_statement_match": (
            not candidate.requires_muhurat_statement
            or "muhurat trading" in normalized
        ),
    }


def _extract_pdf_text(raw: bytes) -> str:
    reader = PdfReader(BytesIO(raw))
    pages = tuple((page.extract_text() or "").strip() for page in reader.pages)
    text = "\n".join(page for page in pages if page)
    if not text.strip():
        raise ValueError("PDF_TEXT_EMPTY")
    return text


def _load_candidates(path: Path) -> tuple[Pre2011CalendarSourceCandidate, ...]:
    if not path.is_file():
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_CANDIDATE_REGISTRY_MISSING"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_CANDIDATE_REGISTRY_INVALID"
        ) from exc
    raw_candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_CANDIDATE_REGISTRY_EMPTY"
        )
    candidates = tuple(
        _candidate_from_payload(item)
        for item in raw_candidates
        if isinstance(item, dict)
    )
    if len(candidates) != len(raw_candidates):
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_CANDIDATE_REGISTRY_INVALID"
        )
    identities = {(item.year, item.source_id, item.source_url) for item in candidates}
    if len(identities) != len(candidates):
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_CANDIDATE_DUPLICATE"
        )
    return tuple(
        sorted(candidates, key=lambda item: (item.year, item.source_id, item.source_url))
    )


def _candidate_from_payload(payload: Mapping[str, object]) -> Pre2011CalendarSourceCandidate:
    try:
        year = int(payload["year"])
        source_id = str(payload["source_id"]).strip()
        source_url = str(payload["source_url"]).strip()
        segment_scope = str(payload["segment_scope"]).strip().upper()
        expected_subject = str(payload["expected_subject"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_CANDIDATE_INVALID"
        ) from exc
    if year not in PRE2011_CALENDAR_YEARS:
        raise Pre2016ExternalValidationError("PRE2011_CALENDAR_CANDIDATE_YEAR_INVALID")
    if not source_id or not expected_subject:
        raise Pre2016ExternalValidationError("PRE2011_CALENDAR_CANDIDATE_INVALID")
    _validate_official_url(source_url)
    if segment_scope not in _ALLOWED_SEGMENT_SCOPES:
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_SEGMENT_SCOPE_INVALID"
        )
    expected_sha256 = _optional_string(payload.get("expected_sha256"))
    if expected_sha256 is not None and not re.fullmatch(
        r"[0-9a-f]{64}", expected_sha256
    ):
        raise Pre2016ExternalValidationError(
            "PRE2011_CALENDAR_EXPECTED_SHA256_INVALID"
        )
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


def _failed_attempt(
    candidate: Pre2011CalendarSourceCandidate,
    *,
    recovery_state: str,
    error: str,
) -> Pre2011CalendarSourceAttempt:
    base: dict[str, object] = {
        "year": candidate.year,
        "source_id": candidate.source_id,
        "requested_url": candidate.source_url,
        "final_url": candidate.source_url,
        "segment_scope": candidate.segment_scope,
        "http_status": None,
        "content_type": "",
        "response_bytes": 0,
        "response_sha256": None,
        "pdf_signature_valid": False,
        "document_path": None,
    }
    return _attempt_from_base(base, recovery_state=recovery_state, error=error)


def _attempt_from_base(
    base: Mapping[str, object],
    *,
    recovery_state: str,
    text_extraction_status: str = "NOT_ATTEMPTED",
    duplicate_of_source_id: str | None = None,
    error: str | None,
) -> Pre2011CalendarSourceAttempt:
    return Pre2011CalendarSourceAttempt(
        year=int(base["year"]),
        source_id=str(base["source_id"]),
        requested_url=str(base["requested_url"]),
        final_url=str(base["final_url"]),
        segment_scope=str(base["segment_scope"]),
        http_status=(
            int(base["http_status"]) if base.get("http_status") is not None else None
        ),
        content_type=str(base["content_type"]),
        response_bytes=int(base["response_bytes"]),
        response_sha256=(
            str(base["response_sha256"])
            if base.get("response_sha256") is not None
            else None
        ),
        pdf_signature_valid=bool(base["pdf_signature_valid"]),
        text_extraction_status=text_extraction_status,
        extracted_text_sha256=None,
        exchange_match=False,
        segment_match=False,
        subject_match=False,
        year_match=False,
        download_number_match=False,
        circular_date_match=False,
        holiday_table_match=False,
        muhurat_statement_match=False,
        content_validation_passed=False,
        recovery_state=recovery_state,
        document_path=(
            str(base["document_path"])
            if base.get("document_path") is not None
            else None
        ),
        extracted_text_path=None,
        duplicate_of_source_id=duplicate_of_source_id,
        error=error,
    )


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
