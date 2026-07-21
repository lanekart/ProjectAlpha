from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from pypdf import PdfReader

from alpha.historical_truth.session_calendar import OfficialSessionCalendarEngine

HTR007_HISTORICAL_SESSION_EVIDENCE_CONTRACT_VERSION = "1.0"
NSE_YEAR_PAGE_TEMPLATE = (
    "https://www.nseindia.com/static/holidays-for-the-calendar-year-{year}"
)
NSE_HOME = "https://www.nseindia.com/"


class HistoricalEvidenceStatus(StrEnum):
    COMPLETE = "complete"
    REUSED = "reused"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HistoricalEvidenceRecord:
    year: int
    status: HistoricalEvidenceStatus
    year_page_url: str
    year_page_path: str | None
    year_page_sha256: str | None
    circular_url: str | None
    circular_path: str | None
    circular_sha256: str | None
    normalized_path: str | None
    normalized_sha256: str | None
    holiday_count: int
    special_session_count: int
    error: str | None


@dataclass(frozen=True, slots=True)
class HistoricalEvidenceReport:
    contract_version: str
    start_year: int
    end_year: int
    records: tuple[HistoricalEvidenceRecord, ...]
    complete_count: int
    reused_count: int
    failed_count: int
    holiday_count: int
    special_session_count: int
    report_sha256: str


@dataclass(frozen=True, slots=True)
class ParsedAnnualCalendar:
    year: int
    holidays: tuple[date, ...]
    special_sessions: tuple[date, ...]


class HistoricalSessionEvidenceEngine:
    """Acquire, verify and normalize official annual NSE CM session evidence."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.source_root = root / "raw" / "nse" / "calendar" / "historical"
        self.manifest_root = root / "manifests"

    def acquire_range(
        self,
        start_year: int,
        end_year: int,
        *,
        timeout_seconds: float = 30.0,
        session: requests.Session | None = None,
        progress: Callable[[int, int, int], None] | None = None,
    ) -> HistoricalEvidenceReport:
        if start_year > end_year:
            raise ValueError("start_year must be on or before end_year")
        years = tuple(range(start_year, end_year + 1))
        records: list[HistoricalEvidenceRecord] = []
        client = session or requests.Session()
        for index, year in enumerate(years, start=1):
            records.append(
                self.acquire_year(
                    year,
                    timeout_seconds=timeout_seconds,
                    session=client,
                )
            )
            if progress is not None:
                progress(index, len(years), year)
        return self._report(start_year, end_year, tuple(records))

    def acquire_year(
        self,
        year: int,
        *,
        timeout_seconds: float = 30.0,
        session: requests.Session | None = None,
    ) -> HistoricalEvidenceRecord:
        if year < 1994:
            raise ValueError("NSE equity-session evidence predates the exchange")
        checkpoint = self._checkpoint_path(year)
        reused = self._load_reusable_checkpoint(checkpoint)
        if reused is not None:
            return reused

        page_url = NSE_YEAR_PAGE_TEMPLATE.format(year=year)
        client = session or requests.Session()
        headers = {
            "User-Agent": "ProjectAlpha-HistoricalTruth/1.0",
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
            "Referer": NSE_HOME,
        }
        try:
            client.get(NSE_HOME, headers=headers, timeout=timeout_seconds)
            page_response = client.get(
                page_url,
                headers=headers,
                timeout=timeout_seconds,
            )
            page_response.raise_for_status()
            page_bytes = page_response.content
            if not page_bytes:
                raise ValueError("official NSE year page is empty")
            page_path, page_sha = self._persist_immutable(
                self.source_root / str(year) / "page",
                f"nse_holidays_{year}",
                ".html",
                page_bytes,
            )
            circular_url = self.discover_cm_circular_url(
                page_bytes.decode("utf-8", errors="replace"),
                page_url,
            )
            circular_response = client.get(
                circular_url,
                headers=headers,
                timeout=timeout_seconds,
            )
            circular_response.raise_for_status()
            circular_bytes = circular_response.content
            if not circular_bytes.startswith(b"%PDF"):
                raise ValueError("resolved Capital Market attachment is not a PDF")
            circular_path, circular_sha = self._persist_immutable(
                self.source_root / str(year) / "circular",
                f"nse_cm_holidays_{year}",
                ".pdf",
                circular_bytes,
            )
            text = self.extract_pdf_text(circular_bytes)
            parsed = self.parse_annual_calendar_text(text, year)
            normalized_payload = self._normalized_payload(
                parsed,
                page_url=page_url,
                page_path=page_path,
                page_sha256=page_sha,
                circular_url=circular_url,
                circular_path=circular_path,
                circular_sha256=circular_sha,
            )
            normalized_bytes = (
                json.dumps(normalized_payload, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            normalized_path, normalized_sha = self._persist_immutable(
                self.source_root / str(year) / "normalized",
                f"nse_cm_session_evidence_{year}",
                ".json",
                normalized_bytes,
            )
            record = HistoricalEvidenceRecord(
                year=year,
                status=HistoricalEvidenceStatus.COMPLETE,
                year_page_url=page_url,
                year_page_path=str(page_path),
                year_page_sha256=page_sha,
                circular_url=circular_url,
                circular_path=str(circular_path),
                circular_sha256=circular_sha,
                normalized_path=str(normalized_path),
                normalized_sha256=normalized_sha,
                holiday_count=len(parsed.holidays),
                special_session_count=len(parsed.special_sessions),
                error=None,
            )
        except Exception as exc:
            record = HistoricalEvidenceRecord(
                year=year,
                status=HistoricalEvidenceStatus.FAILED,
                year_page_url=page_url,
                year_page_path=None,
                year_page_sha256=None,
                circular_url=None,
                circular_path=None,
                circular_sha256=None,
                normalized_path=None,
                normalized_sha256=None,
                holiday_count=0,
                special_session_count=0,
                error=f"{type(exc).__name__}: {exc}",
            )
        self._write_checkpoint(checkpoint, record)
        return record

    @staticmethod
    def discover_cm_circular_url(page_text: str, page_url: str) -> str:
        decoded = html.unescape(page_text)
        marker = re.search(
            r"Capital\s+Market\s*\(Equities\)\s*Trade",
            decoded,
            flags=re.IGNORECASE,
        )
        if marker is None:
            raise ValueError("Capital Market (Equities) Trade attachment row not found")
        start = max(0, marker.start() - 1500)
        end = min(len(decoded), marker.end() + 5000)
        nearby = decoded[start:end]
        patterns = (
            r"https?://[^\s\"'<>]+\.pdf(?:\?[^\s\"'<>]*)?",
            r"(?:href|data-url|data-file|data-download)\s*=\s*[\"']([^\"']+)[\"']",
            r"[\"']([^\"']*(?:CMTR|cmtr)\d+\.pdf[^\"']*)[\"']",
        )
        candidates: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, nearby, flags=re.IGNORECASE):
                value = match.group(1) if match.lastindex else match.group(0)
                value = value.strip().replace("\\/", "/")
                if ".pdf" not in value.lower():
                    continue
                resolved = urljoin(page_url, value)
                host = urlparse(resolved).hostname or ""
                if host.endswith("nseindia.com"):
                    candidates.append(resolved)
        unique = tuple(dict.fromkeys(candidates))
        cmtr = tuple(url for url in unique if "cmtr" in url.lower())
        selected = cmtr or unique
        if len(selected) != 1:
            raise ValueError(
                "Capital Market PDF attachment is missing or ambiguous: "
                f"candidates={list(selected)}"
            )
        return selected[0]

    @staticmethod
    def extract_pdf_text(raw: bytes) -> str:
        reader = PdfReader(BytesIO(raw))
        pages = tuple((page.extract_text() or "").strip() for page in reader.pages)
        text = "\n".join(page for page in pages if page)
        if not text.strip():
            raise ValueError("official circular PDF contains no extractable text")
        return text

    @classmethod
    def parse_annual_calendar_text(
        cls,
        text: str,
        year: int,
    ) -> ParsedAnnualCalendar:
        normalized = re.sub(r"[\u00a0\t]+", " ", text)
        normalized = re.sub(r" +", " ", normalized)
        lower = normalized.lower()
        start_markers = (
            "trading holidays for the calendar year",
            "exchange hereby notifies trading holidays",
            "trading holidays for the year",
        )
        starts = [lower.find(marker) for marker in start_markers]
        starts = [position for position in starts if position >= 0]
        section_start = min(starts) if starts else 0
        end_markers = (
            "holidays falling on saturday",
            "holidays falling on a saturday",
            "holidays falling on sunday",
        )
        ends = [lower.find(marker, section_start + 1) for marker in end_markers]
        ends = [position for position in ends if position >= 0]
        section_end = min(ends) if ends else len(normalized)
        section = normalized[section_start:section_end]
        holidays = tuple(sorted(cls._dates_for_year(section, year)))
        if not 5 <= len(holidays) <= 25:
            raise ValueError(
                "annual CM holiday table failed sanity bounds: "
                f"year={year}; parsed={len(holidays)}; dates={holidays}"
            )

        specials: set[date] = set()
        for match in re.finditer(r"muhurat\s+trading", lower):
            context = normalized[max(0, match.start() - 250) : match.end() + 350]
            specials.update(cls._dates_for_year(context, year))
        if len(specials) > 1:
            holiday_specials = specials.intersection(holidays)
            if len(holiday_specials) == 1:
                specials = holiday_specials
            else:
                raise ValueError(
                    f"Muhurat trading date is ambiguous for {year}: {sorted(specials)}"
                )
        return ParsedAnnualCalendar(
            year=year,
            holidays=holidays,
            special_sessions=tuple(sorted(specials)),
        )

    @classmethod
    def _dates_for_year(cls, text: str, year: int) -> set[date]:
        month_names = (
            "January|February|March|April|May|June|July|August|September|"
            "October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
        )
        patterns = (
            rf"\b\d{{1,2}}[-/ ](?:{month_names})[-/ ,]+\d{{2,4}}\b",
            rf"\b(?:{month_names})\s+\d{{1,2}}(?:st|nd|rd|th)?[,]?\s+\d{{4}}\b",
            r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b",
        )
        dates: set[date] = set()
        for pattern in patterns:
            for token in re.findall(pattern, text, flags=re.IGNORECASE):
                if isinstance(token, tuple):
                    continue
                parsed = cls._parse_flexible_date(token)
                if parsed is not None and parsed.year == year:
                    dates.add(parsed)
        return dates

    @staticmethod
    def _parse_flexible_date(value: str) -> date | None:
        cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value, flags=re.I)
        cleaned = re.sub(r"\s+", " ", cleaned.replace(",", " ")).strip()
        formats = (
            "%d-%b-%Y",
            "%d-%B-%Y",
            "%d %b %Y",
            "%d %B %Y",
            "%B %d %Y",
            "%b %d %Y",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%d/%m/%y",
            "%d-%m-%y",
            "%d %b %y",
            "%d-%b-%y",
        )
        for format_ in formats:
            try:
                return datetime.strptime(cleaned, format_).date()
            except ValueError:
                continue
        return None

    def export(
        self,
        report: HistoricalEvidenceReport,
        output_dir: Path,
    ) -> tuple[Path, Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "htr007_historical_session_evidence.json"
        csv_path = output_dir / "htr007_historical_session_evidence.csv"
        markdown_path = output_dir / "htr007_historical_session_evidence.md"
        payload = self._report_payload(report, include_hash=True)
        json_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=tuple(asdict(report.records[0]).keys())
                if report.records
                else ("year", "status", "error"),
            )
            writer.writeheader()
            for record in report.records:
                row = asdict(record)
                row["status"] = record.status.value
                writer.writerow(row)
        markdown_path.write_text(self._markdown(report), encoding="utf-8")
        return json_path, csv_path, markdown_path

    def normalized_source_paths(
        self,
        records: Iterable[HistoricalEvidenceRecord],
    ) -> tuple[Path, ...]:
        return tuple(
            Path(record.normalized_path)
            for record in records
            if record.normalized_path is not None
            and record.status
            in {HistoricalEvidenceStatus.COMPLETE, HistoricalEvidenceStatus.REUSED}
        )

    @staticmethod
    def _normalized_payload(
        parsed: ParsedAnnualCalendar,
        *,
        page_url: str,
        page_path: Path,
        page_sha256: str,
        circular_url: str,
        circular_path: Path,
        circular_sha256: str,
    ) -> dict[str, object]:
        return {
            "contract_version": HTR007_HISTORICAL_SESSION_EVIDENCE_CONTRACT_VERSION,
            "covered_years": [parsed.year],
            "source_url": circular_url,
            "source_evidence": {
                "year_page_url": page_url,
                "year_page_path": str(page_path),
                "year_page_sha256": page_sha256,
                "circular_path": str(circular_path),
                "circular_sha256": circular_sha256,
            },
            "holidays": [
                {
                    "date": item.isoformat(),
                    "description": f"Official NSE CM trading holiday ({parsed.year})",
                }
                for item in parsed.holidays
            ],
            "special_sessions": [
                {
                    "date": item.isoformat(),
                    "description": f"Official NSE Muhurat trading session ({parsed.year})",
                }
                for item in parsed.special_sessions
            ],
        }

    def _report(
        self,
        start_year: int,
        end_year: int,
        records: tuple[HistoricalEvidenceRecord, ...],
    ) -> HistoricalEvidenceReport:
        provisional = HistoricalEvidenceReport(
            contract_version=HTR007_HISTORICAL_SESSION_EVIDENCE_CONTRACT_VERSION,
            start_year=start_year,
            end_year=end_year,
            records=records,
            complete_count=sum(
                item.status is HistoricalEvidenceStatus.COMPLETE for item in records
            ),
            reused_count=sum(
                item.status is HistoricalEvidenceStatus.REUSED for item in records
            ),
            failed_count=sum(
                item.status is HistoricalEvidenceStatus.FAILED for item in records
            ),
            holiday_count=sum(item.holiday_count for item in records),
            special_session_count=sum(
                item.special_session_count for item in records
            ),
            report_sha256="",
        )
        digest = hashlib.sha256(
            json.dumps(
                self._report_payload(provisional, include_hash=False),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return replace(provisional, report_sha256=digest)

    @staticmethod
    def _report_payload(
        report: HistoricalEvidenceReport,
        *,
        include_hash: bool,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_version": report.contract_version,
            "start_year": report.start_year,
            "end_year": report.end_year,
            "complete_count": report.complete_count,
            "reused_count": report.reused_count,
            "failed_count": report.failed_count,
            "holiday_count": report.holiday_count,
            "special_session_count": report.special_session_count,
            "records": [
                {**asdict(record), "status": record.status.value}
                for record in report.records
            ],
        }
        if include_hash:
            payload["report_sha256"] = report.report_sha256
        return payload

    @staticmethod
    def _markdown(report: HistoricalEvidenceReport) -> str:
        lines = [
            "# HTR-007 Historical NSE Session Evidence",
            "",
            f"Window: `{report.start_year}` to `{report.end_year}`",
            f"Complete: {report.complete_count}",
            f"Reused: {report.reused_count}",
            f"Failed: {report.failed_count}",
            f"Holidays parsed: {report.holiday_count}",
            f"Special sessions parsed: {report.special_session_count}",
            f"Report SHA-256: `{report.report_sha256}`",
            "",
            "| Year | Status | Holidays | Special sessions | Error |",
            "|---:|:---|---:|---:|:---|",
        ]
        for record in report.records:
            lines.append(
                f"| {record.year} | {record.status.value} | "
                f"{record.holiday_count} | {record.special_session_count} | "
                f"{record.error or ''} |"
            )
        return "\n".join(lines) + "\n"

    def _checkpoint_path(self, year: int) -> Path:
        return self.manifest_root / f"htr007_historical_session_evidence_{year}.json"

    def _load_reusable_checkpoint(
        self,
        checkpoint: Path,
    ) -> HistoricalEvidenceRecord | None:
        if not checkpoint.exists():
            return None
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        record_payload = payload.get("record")
        if not isinstance(record_payload, dict):
            return None
        status = HistoricalEvidenceStatus(str(record_payload["status"]))
        if status not in {
            HistoricalEvidenceStatus.COMPLETE,
            HistoricalEvidenceStatus.REUSED,
        }:
            return None
        verification_pairs = (
            (record_payload.get("year_page_path"), record_payload.get("year_page_sha256")),
            (record_payload.get("circular_path"), record_payload.get("circular_sha256")),
            (record_payload.get("normalized_path"), record_payload.get("normalized_sha256")),
        )
        for path_value, expected in verification_pairs:
            if not path_value or not expected:
                return None
            path = Path(str(path_value))
            if not path.exists() or self._sha256(path.read_bytes()) != str(expected):
                raise ValueError(f"checkpointed evidence checksum mismatch: {path}")
        return HistoricalEvidenceRecord(
            **{
                **record_payload,
                "status": HistoricalEvidenceStatus.REUSED,
            }
        )

    def _write_checkpoint(
        self,
        checkpoint: Path,
        record: HistoricalEvidenceRecord,
    ) -> None:
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "contract_version": HTR007_HISTORICAL_SESSION_EVIDENCE_CONTRACT_VERSION,
            "written_at": datetime.now(UTC).isoformat(),
            "record": {**asdict(record), "status": record.status.value},
        }
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        temporary = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(checkpoint)

    @classmethod
    def _persist_immutable(
        cls,
        directory: Path,
        stem: str,
        suffix: str,
        content: bytes,
    ) -> tuple[Path, str]:
        digest = cls._sha256(content)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{stem}_{digest[:12]}{suffix}"
        if destination.exists():
            if destination.read_bytes() != content:
                raise FileExistsError(f"immutable evidence differs: {destination}")
            return destination, digest
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
        return destination, digest

    @staticmethod
    def _sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()


def load_calendar_sources(paths: Iterable[Path]) -> tuple[object, ...]:
    """Load normalized evidence through the governed calendar source parser."""

    return tuple(OfficialSessionCalendarEngine.load_source(path) for path in paths)
