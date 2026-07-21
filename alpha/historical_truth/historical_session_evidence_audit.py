from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from alpha.historical_truth.historical_session_evidence import (
    NSE_HOME,
    HistoricalEvidenceRecord,
    HistoricalEvidenceReport,
    HistoricalEvidenceStatus,
    HistoricalSessionEvidenceEngine,
    ParsedAnnualCalendar,
)
from alpha.historical_truth.session_calendar import (
    SessionCalendarReport,
    SessionClassification,
)

HTR007A_ACQUISITION_AUDIT_CONTRACT_VERSION = "1.0"
NSE_HOLIDAY_DIRECTORY = (
    "https://www.nseindia.com/resources/exchange-communication-holidays"
)
NSE_CIRCULAR_DIRECTORY = "https://www.nseindia.com/static/list-circulars"
OFFICIAL_HOSTS = ("nseindia.com", "nsearchives.nseindia.com")


class AcquisitionFailureCode(StrEnum):
    OFFICIAL_DOCUMENT_NOT_FOUND = "OFFICIAL_DOCUMENT_NOT_FOUND"
    HTTP_ACCESS_DENIED = "HTTP_ACCESS_DENIED"
    HTTP_RATE_LIMITED = "HTTP_RATE_LIMITED"
    REDIRECTED_TO_HTML = "REDIRECTED_TO_HTML"
    INVALID_CONTENT_TYPE = "INVALID_CONTENT_TYPE"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    PDF_PARSE_FAILED = "PDF_PARSE_FAILED"
    HTML_PARSE_FAILED = "HTML_PARSE_FAILED"
    NO_SESSION_RECORDS_FOUND = "NO_SESSION_RECORDS_FOUND"
    PARTIAL_SESSION_RECORDS_FOUND = "PARTIAL_SESSION_RECORDS_FOUND"
    SOURCE_YEAR_MISMATCH = "SOURCE_YEAR_MISMATCH"
    SOURCE_SEGMENT_MISMATCH = "SOURCE_SEGMENT_MISMATCH"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class DocumentParser(StrEnum):
    PDF = "pdf"
    HTML = "html"
    TEXT = "text"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AcquisitionAttempt:
    year: int
    source_family: str
    requested_url: str
    final_url: str | None
    requested_at: str
    http_status: int | None
    content_type: str | None
    byte_size: int
    redirect_chain: tuple[str, ...]
    inferred_extension: str | None
    sha256: str | None
    parser: DocumentParser
    records_inspected: int
    holidays_parsed: int
    special_sessions_parsed: int
    acquisition_status: str
    parse_status: str
    evidence_status: str
    failure_code: AcquisitionFailureCode | None
    failure_detail: str | None


@dataclass(frozen=True, slots=True)
class AcquisitionAuditReport:
    contract_version: str
    start_year: int
    end_year: int
    attempts: tuple[AcquisitionAttempt, ...]
    complete_years: int
    reused_years: int
    failed_years: int
    report_sha256: str


@dataclass(frozen=True, slots=True)
class UnresolvedSessionAudit:
    trading_date: date
    weekday: str
    observed_candles: bool
    failed_source_years: tuple[int, ...]
    unresolved_reason: str
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Document:
    family: str
    url: str
    raw: bytes
    parser: DocumentParser
    extension: str


class HistoricalSessionEvidenceRepairEngine(HistoricalSessionEvidenceEngine):
    """Retry failed HTR-007 years through governed official NSE discovery."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.attempts: list[AcquisitionAttempt] = []

    def acquire_range_with_audit(
        self,
        start_year: int,
        end_year: int,
        *,
        timeout_seconds: float = 30.0,
        session: requests.Session | None = None,
        progress: Callable[[int, int, int], None] | None = None,
    ) -> tuple[HistoricalEvidenceReport, AcquisitionAuditReport]:
        if start_year > end_year:
            raise ValueError("start_year must be on or before end_year")
        self.attempts.clear()
        client = session or requests.Session()
        years = tuple(range(start_year, end_year + 1))
        records = []
        for index, year in enumerate(years, 1):
            records.append(
                self.acquire_year_repaired(
                    year, timeout_seconds=timeout_seconds, session=client
                )
            )
            if progress:
                progress(index, len(years), year)
        evidence = self._report(start_year, end_year, tuple(records))
        return evidence, self._audit(evidence)

    def acquire_year_repaired(
        self,
        year: int,
        *,
        timeout_seconds: float = 30.0,
        session: requests.Session | None = None,
    ) -> HistoricalEvidenceRecord:
        client = session or requests.Session()
        primary = super().acquire_year(
            year, timeout_seconds=timeout_seconds, session=client
        )
        self.attempts.append(self._primary_attempt(primary))
        if primary.status is not HistoricalEvidenceStatus.FAILED:
            return primary

        headers = {
            "User-Agent": "ProjectAlpha-HistoricalTruth/1.1",
            "Accept": "text/html,application/pdf,*/*",
            "Referer": NSE_HOME,
        }
        pages = (
            ("nse_holiday_directory", f"{NSE_HOLIDAY_DIRECTORY}?year={year}"),
            ("nse_circular_directory", NSE_CIRCULAR_DIRECTORY),
        )
        for family, page_url in pages:
            page = self._fetch(
                year, family, page_url, client, headers, timeout_seconds
            )
            if page is None:
                continue
            page_path, page_sha = self._persist_immutable(
                self.source_root / str(year) / "discovery",
                f"nse_session_discovery_{year}",
                page.extension,
                page.raw,
            )
            links = self.discover_documents(
                page.raw.decode("utf-8", errors="replace"), page.url, year
            )
            if not links:
                self.attempts.append(
                    self._failed_attempt(
                        year,
                        f"{family}:discovery",
                        page.url,
                        AcquisitionFailureCode.OFFICIAL_DOCUMENT_NOT_FOUND,
                        "no official Capital Market holiday attachment discovered",
                    )
                )
            for link in links:
                document = self._fetch(
                    year,
                    f"{family}:attachment",
                    link,
                    client,
                    headers,
                    timeout_seconds,
                )
                if document is None:
                    continue
                try:
                    parsed = self._parse(document, year)
                    self._validate(document, parsed, year)
                    source_path, source_sha = self._persist_immutable(
                        self.source_root / str(year) / "official",
                        f"nse_cm_session_source_{year}",
                        document.extension,
                        document.raw,
                    )
                    normalized = self._normalized_payload(
                        parsed,
                        page_url=page.url,
                        page_path=page_path,
                        page_sha256=page_sha,
                        circular_url=document.url,
                        circular_path=source_path,
                        circular_sha256=source_sha,
                    )
                    normalized_path, normalized_sha = self._persist_immutable(
                        self.source_root / str(year) / "normalized",
                        f"nse_cm_session_evidence_{year}",
                        ".json",
                        (json.dumps(normalized, indent=2, sort_keys=True) + "\n").encode(),
                    )
                    self._finish_attempt(document, parsed=parsed)
                    repaired = HistoricalEvidenceRecord(
                        year=year,
                        status=HistoricalEvidenceStatus.COMPLETE,
                        year_page_url=page.url,
                        year_page_path=str(page_path),
                        year_page_sha256=page_sha,
                        circular_url=document.url,
                        circular_path=str(source_path),
                        circular_sha256=source_sha,
                        normalized_path=str(normalized_path),
                        normalized_sha256=normalized_sha,
                        holiday_count=len(parsed.holidays),
                        special_session_count=len(parsed.special_sessions),
                        error=None,
                    )
                    self._write_checkpoint(self._checkpoint_path(year), repaired)
                    return repaired
                except Exception as exc:
                    self._finish_attempt(document, error=exc)
        return primary

    def _fetch(
        self,
        year: int,
        family: str,
        url: str,
        client: requests.Session,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _Document | None:
        requested_at = datetime.now(UTC).isoformat()
        try:
            response = client.get(url, headers=dict(headers), timeout=timeout)
        except Exception as exc:
            self.attempts.append(
                self._failed_attempt(
                    year,
                    family,
                    url,
                    AcquisitionFailureCode.NETWORK_ERROR,
                    f"{type(exc).__name__}: {exc}",
                    requested_at,
                )
            )
            return None
        status = int(getattr(response, "status_code", 0) or 0)
        final_url = str(getattr(response, "url", url) or url)
        raw = bytes(getattr(response, "content", b""))
        response_headers = getattr(response, "headers", {}) or {}
        content_type = str(response_headers.get("Content-Type", "")).split(";", 1)[0]
        redirects = tuple(
            str(item.url)
            for item in (getattr(response, "history", ()) or ())
            if getattr(item, "url", None)
        )
        parser, extension = self.inspect_content(raw, content_type, final_url)
        code, detail = self._response_failure(status, raw, parser, url)
        attempt = AcquisitionAttempt(
            year=year,
            source_family=family,
            requested_url=url,
            final_url=final_url,
            requested_at=requested_at,
            http_status=status,
            content_type=content_type or None,
            byte_size=len(raw),
            redirect_chain=redirects,
            inferred_extension=extension,
            sha256=hashlib.sha256(raw).hexdigest() if raw else None,
            parser=parser,
            records_inspected=0,
            holidays_parsed=0,
            special_sessions_parsed=0,
            acquisition_status="failed" if code else "acquired",
            parse_status="not_started",
            evidence_status="rejected" if code else "candidate",
            failure_code=code,
            failure_detail=detail,
        )
        self.attempts.append(attempt)
        if code or extension is None:
            return None
        return _Document(family, final_url, raw, parser, extension)

    @staticmethod
    def inspect_content(
        raw: bytes, content_type: str, url: str
    ) -> tuple[DocumentParser, str | None]:
        sample = raw[:512].lstrip().lower()
        if raw.startswith(b"%PDF"):
            return DocumentParser.PDF, ".pdf"
        if sample.startswith((b"<!doctype html", b"<html", b"<table")):
            return DocumentParser.HTML, ".html"
        if "html" in content_type.lower() or url.lower().endswith((".htm", ".html")):
            return DocumentParser.HTML, ".html"
        if "text" in content_type.lower() or url.lower().endswith(".txt"):
            return DocumentParser.TEXT, ".txt"
        return DocumentParser.UNKNOWN, None

    @staticmethod
    def discover_documents(page_text: str, page_url: str, year: int) -> tuple[str, ...]:
        decoded = html.unescape(page_text).replace("\\/", "/")
        found = []
        pattern = r"(?:href|data-url|data-file|data-download)\s*=\s*[\"']([^\"']+)[\"']"
        for match in re.finditer(pattern, decoded, flags=re.I):
            value = match.group(1).strip()
            if not re.search(r"\.(pdf|htm|html)(?:\?|$)", value, re.I):
                continue
            resolved = urljoin(page_url, value)
            host = (urlparse(resolved).hostname or "").lower()
            if not HistoricalSessionEvidenceRepairEngine._official_host(host):
                continue
            name = Path(urlparse(resolved).path).name.lower()
            if name.startswith(("faop", "cd", "com", "debt", "slb")):
                continue
            context = decoded[max(0, match.start() - 500) : match.end() + 500].lower()
            cm = any(
                x in context or x in name
                for x in ("capital market", "equities", "cmtr")
            )
            calendar = any(
                x in context for x in ("holiday", "muhurat", str(year))
            )
            if cm and calendar:
                found.append(resolved)
        return tuple(dict.fromkeys(found))

    @classmethod
    def _parse(cls, document: _Document, year: int) -> ParsedAnnualCalendar:
        if document.parser is DocumentParser.PDF:
            text = cls.extract_pdf_text(document.raw)
        elif document.parser in {DocumentParser.HTML, DocumentParser.TEXT}:
            text = document.raw.decode("utf-8", errors="replace")
            if document.parser is DocumentParser.HTML:
                text = html.unescape(re.sub(r"<[^>]+>", " ", text))
        else:
            raise ValueError("unsupported document layout")
        return cls.parse_annual_calendar_text(text, year)

    @staticmethod
    def _validate(document: _Document, parsed: ParsedAnnualCalendar, year: int) -> None:
        host = (urlparse(document.url).hostname or "").lower()
        if not HistoricalSessionEvidenceRepairEngine._official_host(host):
            raise ValueError("source is not an approved NSE domain")
        if parsed.year != year or any(item.year != year for item in parsed.holidays):
            raise ValueError("source year mismatch")
        text = document.raw.decode("utf-8", errors="ignore").lower()
        if not any(
            x in text or x in document.url.lower()
            for x in ("capital market", "equities", "cmtr")
        ):
            raise ValueError("source segment mismatch")

    def _finish_attempt(
        self,
        document: _Document,
        *,
        parsed: ParsedAnnualCalendar | None = None,
        error: Exception | None = None,
    ) -> None:
        for index in range(len(self.attempts) - 1, -1, -1):
            item = self.attempts[index]
            if item.final_url != document.url or item.evidence_status != "candidate":
                continue
            if parsed:
                self.attempts[index] = replace(
                    item,
                    records_inspected=len(parsed.holidays)
                    + len(parsed.special_sessions),
                    holidays_parsed=len(parsed.holidays),
                    special_sessions_parsed=len(parsed.special_sessions),
                    parse_status="parsed",
                    evidence_status="admitted",
                )
            else:
                assert error is not None
                self.attempts[index] = replace(
                    item,
                    parse_status="failed",
                    evidence_status="rejected",
                    failure_code=self._parse_failure(error, document.parser),
                    failure_detail=f"{type(error).__name__}: {error}",
                )
            return

    @staticmethod
    def _response_failure(
        status: int, raw: bytes, parser: DocumentParser, requested_url: str
    ) -> tuple[AcquisitionFailureCode | None, str | None]:
        if status in {401, 403}:
            return AcquisitionFailureCode.HTTP_ACCESS_DENIED, f"HTTP {status}"
        if status == 429:
            return AcquisitionFailureCode.HTTP_RATE_LIMITED, "HTTP 429"
        if status >= 400:
            return AcquisitionFailureCode.OFFICIAL_DOCUMENT_NOT_FOUND, f"HTTP {status}"
        if not raw:
            return AcquisitionFailureCode.EMPTY_RESPONSE, "empty response"
        if requested_url.lower().endswith(".pdf") and parser is DocumentParser.HTML:
            return AcquisitionFailureCode.REDIRECTED_TO_HTML, "PDF resolved to HTML"
        if parser is DocumentParser.UNKNOWN:
            return AcquisitionFailureCode.INVALID_CONTENT_TYPE, "unsupported content"
        return None, None

    @staticmethod
    def _parse_failure(
        exc: Exception, parser: DocumentParser
    ) -> AcquisitionFailureCode:
        text = str(exc).lower()
        if "year mismatch" in text:
            return AcquisitionFailureCode.SOURCE_YEAR_MISMATCH
        if "segment mismatch" in text or "approved nse domain" in text:
            return AcquisitionFailureCode.SOURCE_SEGMENT_MISMATCH
        if "sanity bounds" in text:
            return AcquisitionFailureCode.PARTIAL_SESSION_RECORDS_FOUND
        if "no extractable text" in text:
            return AcquisitionFailureCode.NO_SESSION_RECORDS_FOUND
        return (
            AcquisitionFailureCode.PDF_PARSE_FAILED
            if parser is DocumentParser.PDF
            else AcquisitionFailureCode.HTML_PARSE_FAILED
        )

    @classmethod
    def _primary_attempt(cls, record: HistoricalEvidenceRecord) -> AcquisitionAttempt:
        failed = record.status is HistoricalEvidenceStatus.FAILED
        return AcquisitionAttempt(
            record.year,
            "nse_current_annual_page",
            record.year_page_url,
            record.circular_url or record.year_page_url,
            "checkpoint-or-primary-run",
            None,
            None,
            0,
            (),
            Path(record.circular_path).suffix if record.circular_path else None,
            record.circular_sha256,
            DocumentParser.PDF if record.circular_path else DocumentParser.UNKNOWN,
            record.holiday_count + record.special_session_count,
            record.holiday_count,
            record.special_session_count,
            record.status.value,
            "failed" if failed else "parsed",
            "rejected" if failed else "admitted",
            cls._legacy_failure(record.error) if failed else None,
            record.error,
        )

    @staticmethod
    def _legacy_failure(error: str | None) -> AcquisitionFailureCode:
        text = (error or "").lower()
        if any(
            x in text for x in ("http 404", "row not found", "missing or ambiguous")
        ):
            return AcquisitionFailureCode.OFFICIAL_DOCUMENT_NOT_FOUND
        if "http 401" in text or "http 403" in text:
            return AcquisitionFailureCode.HTTP_ACCESS_DENIED
        if "http 429" in text:
            return AcquisitionFailureCode.HTTP_RATE_LIMITED
        if "empty" in text:
            return AcquisitionFailureCode.EMPTY_RESPONSE
        if "not a pdf" in text:
            return AcquisitionFailureCode.REDIRECTED_TO_HTML
        if "checksum mismatch" in text:
            return AcquisitionFailureCode.CHECKSUM_MISMATCH
        if any(x in text for x in ("connectionerror", "timeout", "network")):
            return AcquisitionFailureCode.NETWORK_ERROR
        return AcquisitionFailureCode.UNKNOWN_FAILURE

    @staticmethod
    def _failed_attempt(
        year: int,
        family: str,
        url: str,
        code: AcquisitionFailureCode,
        detail: str,
        requested_at: str | None = None,
    ) -> AcquisitionAttempt:
        return AcquisitionAttempt(
            year,
            family,
            url,
            None,
            requested_at or datetime.now(UTC).isoformat(),
            None,
            None,
            0,
            (),
            None,
            None,
            DocumentParser.UNKNOWN,
            0,
            0,
            0,
            "failed",
            "not_started",
            "rejected",
            code,
            detail,
        )

    def _audit(self, evidence: HistoricalEvidenceReport) -> AcquisitionAuditReport:
        attempts = tuple(
            sorted(
                self.attempts,
                key=lambda x: (x.year, x.source_family, x.requested_url),
            )
        )
        provisional = AcquisitionAuditReport(
            HTR007A_ACQUISITION_AUDIT_CONTRACT_VERSION,
            evidence.start_year,
            evidence.end_year,
            attempts,
            evidence.complete_count,
            evidence.reused_count,
            evidence.failed_count,
            "",
        )
        digest = hashlib.sha256(
            json.dumps(
                self._jsonable(asdict(provisional)),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return replace(provisional, report_sha256=digest)

    @classmethod
    def export_audit(
        cls, report: AcquisitionAuditReport, output_dir: Path
    ) -> tuple[Path, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = tuple(
            output_dir / name
            for name in (
                "htr007a_acquisition_audit.json",
                "htr007a_acquisition_audit.csv",
                "htr007a_acquisition_audit.md",
                "htr007a_rejected_evidence.json",
                "htr007a_rejected_evidence.csv",
            )
        )
        payload = cls._jsonable(asdict(report))
        rejected = [
            x for x in report.attempts if x.evidence_status == "rejected"
        ]
        paths[0].write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        cls._attempt_csv(paths[1], report.attempts)
        paths[2].write_text(cls._markdown(report), encoding="utf-8")
        paths[3].write_text(
            json.dumps(
                [cls._jsonable(asdict(x)) for x in rejected],
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        cls._attempt_csv(paths[4], rejected)
        return paths

    @classmethod
    def unresolved_sessions(
        cls,
        evidence: HistoricalEvidenceReport,
        calendar: SessionCalendarReport,
    ) -> tuple[UnresolvedSessionAudit, ...]:
        failed = {
            x.year
            for x in evidence.records
            if x.status is HistoricalEvidenceStatus.FAILED
        }
        return tuple(
            UnresolvedSessionAudit(
                x.trading_date,
                x.trading_date.strftime("%A"),
                x.observed_candles,
                (x.trading_date.year,) if x.trading_date.year in failed else (),
                "NO_ADMITTED_OFFICIAL_EVIDENCE",
                x.issue_codes,
            )
            for x in calendar.records
            if x.classification is SessionClassification.UNRESOLVED_WEEKDAY
        )

    @classmethod
    def export_unresolved(
        cls, records: Sequence[UnresolvedSessionAudit], output_dir: Path
    ) -> tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "htr007a_unresolved_sessions.json"
        csv_path = output_dir / "htr007a_unresolved_sessions.csv"
        json_path.write_text(
            json.dumps(
                [cls._jsonable(asdict(x)) for x in records],
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            fields = (
                "trading_date",
                "weekday",
                "observed_candles",
                "failed_source_years",
                "unresolved_reason",
                "issue_codes",
            )
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for item in records:
                row = asdict(item)
                row["trading_date"] = item.trading_date.isoformat()
                row["failed_source_years"] = ";".join(
                    map(str, item.failed_source_years)
                )
                row["issue_codes"] = ";".join(item.issue_codes)
                writer.writerow(row)
        return json_path, csv_path

    @staticmethod
    def certification_label(
        evidence: HistoricalEvidenceReport, calendar: SessionCalendarReport
    ) -> str:
        if calendar.conflict_count:
            return "conflicting_official_evidence"
        complete = (
            evidence.failed_count == 0
            and calendar.unresolved_weekday_count == 0
            and calendar.unconfirmed_special_session_count == 0
            and calendar.missing_special_session_count == 0
        )
        return (
            "complete_official_evidence"
            if complete
            else "incomplete_official_evidence"
        )

    @staticmethod
    def _official_host(host: str) -> bool:
        return any(host == x or host.endswith(f".{x}") for x in OFFICIAL_HOSTS)

    @staticmethod
    def _attempt_csv(
        path: Path, attempts: Sequence[AcquisitionAttempt]
    ) -> None:
        fields = (
            tuple(asdict(attempts[0]).keys())
            if attempts
            else ("year", "failure_code")
        )
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for item in attempts:
                row = asdict(item)
                row["redirect_chain"] = ";".join(item.redirect_chain)
                row["parser"] = item.parser.value
                row["failure_code"] = (
                    item.failure_code.value if item.failure_code else ""
                )
                writer.writerow(row)

    @staticmethod
    def _markdown(report: AcquisitionAuditReport) -> str:
        failures = Counter(
            x.failure_code.value for x in report.attempts if x.failure_code
        )
        lines = [
            "# HTR-007A Official Session Evidence Acquisition Audit",
            "",
            f"Window: `{report.start_year}` to `{report.end_year}`",
            f"Complete years: {report.complete_years}",
            f"Reused years: {report.reused_years}",
            f"Failed years: {report.failed_years}",
            f"Attempts: {len(report.attempts)}",
            f"Report SHA-256: `{report.report_sha256}`",
            "",
            "| Failure code | Count |",
            "|:---|---:|",
        ]
        lines.extend(
            f"| {code} | {count} |"
            for code, count in sorted(failures.items())
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _jsonable(value: object) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, dict):
            return {
                str(k): HistoricalSessionEvidenceRepairEngine._jsonable(v)
                for k, v in value.items()
            }
        if isinstance(value, (tuple, list)):
            return [
                HistoricalSessionEvidenceRepairEngine._jsonable(v) for v in value
            ]
        return value
