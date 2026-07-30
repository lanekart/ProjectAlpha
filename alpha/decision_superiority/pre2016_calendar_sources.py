"""Official-source discovery and normalization for DSI-010 calendars."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import duckdb

from .pre2016_external_validation_models import (
    DSI010_EXTERNAL_END,
    DSI010_EXTERNAL_START,
    Pre2016ExternalValidationError,
)

_ALLOWED_OFFICIAL_HOSTS = frozenset(
    {
        "nseindia.com",
        "www.nseindia.com",
        "nsearchives.nseindia.com",
        "archives.nseindia.com",
    }
)
_ALLOWED_CLASSIFICATIONS = frozenset({"HOLIDAY", "SPECIAL_SESSION"})
_ALLOWED_SEGMENT_SCOPES = frozenset(
    {
        "CAPITAL_MARKET",
        "FUTURES_AND_OPTIONS",
        "EXCHANGE_WIDE",
        "CROSS_SEGMENT_CORROBORATION",
        "UNKNOWN",
    }
)


@dataclass(frozen=True, slots=True)
class Pre2016CalendarDiscovery:
    """Unresolved archive dates and observed weekend sessions requiring evidence."""

    unavailable_rows: tuple[dict[str, object], ...]
    weekend_session_rows: tuple[dict[str, object], ...]
    annual_rows: tuple[dict[str, object], ...]
    manifest_status_case_normalized: bool


def discover_pre2016_calendar_evidence(
    *,
    database: Path,
    manifest: Path,
) -> Pre2016CalendarDiscovery:
    """Build an evidence-discovery population without classifying any dates."""

    if not database.is_file():
        raise Pre2016ExternalValidationError("PRE2016_DISCOVERY_DATABASE_MISSING")
    if not manifest.is_file():
        raise Pre2016ExternalValidationError("PRE2016_DISCOVERY_MANIFEST_MISSING")

    latest = _latest_manifest_rows(manifest)
    unavailable_rows: list[dict[str, object]] = []
    status_case_normalized = False
    for trading_date in sorted(latest):
        payload = latest[trading_date]
        raw_status = str(payload.get("status") or "UNKNOWN")
        normalized_status = raw_status.strip().lower()
        status_case_normalized = (
            status_case_normalized or raw_status != normalized_status
        )
        if normalized_status != "unavailable":
            continue
        unavailable_rows.append(
            {
                "trading_date": trading_date,
                "calendar_year": trading_date.year,
                "weekday": trading_date.strftime("%A"),
                "manifest_status_raw": raw_status,
                "manifest_status_normalized": normalized_status,
                "manifest_error": str(payload.get("error") or ""),
                "archive_source_url": str(payload.get("source_url") or ""),
                "classification": "UNREVIEWED",
                "description": "",
                "official_source_id": "",
                "official_source_url": "",
                "official_document_path": "",
                "review_state": "PENDING_OFFICIAL_EVIDENCE",
                "inferred_from_http_404": False,
            }
        )

    connection = duckdb.connect(str(database), read_only=True)
    try:
        weekend_dates = connection.execute(
            """
            select distinct trading_date
            from daily_candle
            where trading_date between date '2005-01-01' and date '2015-12-31'
              and extract(isodow from trading_date) in (6, 7)
            order by trading_date
            """
        ).fetchall()
    finally:
        connection.close()

    weekend_session_rows = tuple(
        {
            "trading_date": row[0],
            "calendar_year": row[0].year,
            "weekday": row[0].strftime("%A"),
            "observed_candles": True,
            "classification": "UNREVIEWED",
            "description": "",
            "official_source_id": "",
            "official_source_url": "",
            "official_document_path": "",
            "review_state": "PENDING_SPECIAL_SESSION_EVIDENCE",
            "inferred_from_observation": False,
        }
        for row in weekend_dates
    )

    unavailable_by_year = _count_by_year(unavailable_rows)
    weekend_by_year = _count_by_year(weekend_session_rows)
    annual_rows = tuple(
        {
            "calendar_year": year,
            "archive_unavailable_weekdays": unavailable_by_year.get(year, 0),
            "observed_weekend_sessions": weekend_by_year.get(year, 0),
            "official_source_coverage": "MISSING",
            "calendar_certification_permitted": False,
        }
        for year in range(DSI010_EXTERNAL_START.year, DSI010_EXTERNAL_END.year + 1)
    )
    return Pre2016CalendarDiscovery(
        unavailable_rows=tuple(unavailable_rows),
        weekend_session_rows=weekend_session_rows,
        annual_rows=annual_rows,
        manifest_status_case_normalized=status_case_normalized,
    )


def export_pre2016_calendar_discovery(
    result: Pre2016CalendarDiscovery,
    output: Path,
) -> tuple[Path, ...]:
    """Export reviewable evidence-discovery ledgers."""

    output.mkdir(parents=True, exist_ok=True)
    unavailable_path = output / "dsi010_calendar_unavailable_discovery.csv"
    weekend_path = output / "dsi010_calendar_weekend_session_discovery.csv"
    annual_path = output / "dsi010_calendar_discovery_annual_summary.csv"
    summary_path = output / "dsi010_calendar_discovery_summary.json"

    _write_csv(unavailable_path, result.unavailable_rows)
    _write_csv(weekend_path, result.weekend_session_rows)
    _write_csv(annual_path, result.annual_rows)
    summary = {
        "external_start": DSI010_EXTERNAL_START.isoformat(),
        "external_end": DSI010_EXTERNAL_END.isoformat(),
        "archive_unavailable_count": len(result.unavailable_rows),
        "observed_weekend_session_count": len(result.weekend_session_rows),
        "manifest_status_case_normalized": result.manifest_status_case_normalized,
        "classification_inferred_from_archive_status": False,
        "classification_inferred_from_observed_candles": False,
        "calendar_certification_permitted": False,
        "production_influence": False,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return (unavailable_path, weekend_path, annual_path, summary_path)


def build_reviewed_official_calendar_source(
    *,
    review_csv: Path,
    source_document: Path,
    source_url: str,
    source_id: str,
    covered_years: tuple[int, ...],
    output: Path,
    segment_scope: str = "UNKNOWN",
    extracted_text: Path | None = None,
    content_validation: Path | None = None,
    content_validation_passed: bool = True,
    manual_review_completed: bool = True,
) -> Path:
    """Normalize reviewed rows into the official calendar source contract."""

    if not review_csv.is_file():
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_REVIEW_CSV_MISSING")
    if not source_document.is_file():
        raise Pre2016ExternalValidationError("PRE2016_OFFICIAL_DOCUMENT_MISSING")
    if extracted_text is not None and not extracted_text.is_file():
        raise Pre2016ExternalValidationError("PRE2016_EXTRACTED_TEXT_MISSING")
    if content_validation is not None and not content_validation.is_file():
        raise Pre2016ExternalValidationError("PRE2016_CONTENT_VALIDATION_MISSING")
    _validate_official_url(source_url)
    normalized_source_id = source_id.strip()
    if not normalized_source_id:
        raise Pre2016ExternalValidationError("PRE2016_OFFICIAL_SOURCE_ID_EMPTY")
    normalized_scope = segment_scope.strip().upper()
    if normalized_scope not in _ALLOWED_SEGMENT_SCOPES:
        raise Pre2016ExternalValidationError("PRE2016_SEGMENT_SCOPE_INVALID")
    if not content_validation_passed:
        raise Pre2016ExternalValidationError(
            "PRE2016_OFFICIAL_SOURCE_CONTENT_VALIDATION_FAILED"
        )
    if not manual_review_completed:
        raise Pre2016ExternalValidationError(
            "PRE2016_OFFICIAL_SOURCE_MANUAL_REVIEW_INCOMPLETE"
        )
    years = tuple(sorted(set(covered_years)))
    if not years:
        raise Pre2016ExternalValidationError("PRE2016_OFFICIAL_COVERED_YEARS_EMPTY")
    allowed_years = set(range(DSI010_EXTERNAL_START.year, DSI010_EXTERNAL_END.year + 1))
    if not set(years).issubset(allowed_years):
        raise Pre2016ExternalValidationError("PRE2016_OFFICIAL_COVERED_YEAR_INVALID")

    with review_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise Pre2016ExternalValidationError("PRE2016_CALENDAR_REVIEW_EMPTY")

    holidays: list[dict[str, str]] = []
    special_sessions: list[dict[str, str]] = []
    observed_dates: set[date] = set()
    for row in rows:
        review_state = str(row.get("review_state") or "").strip().upper()
        if review_state != "VERIFIED_OFFICIAL_EVIDENCE":
            raise Pre2016ExternalValidationError("PRE2016_CALENDAR_REVIEW_NOT_VERIFIED")
        row_scope = str(row.get("segment_scope") or "").strip().upper()
        if row_scope and row_scope != normalized_scope:
            raise Pre2016ExternalValidationError(
                "PRE2016_CALENDAR_REVIEW_SEGMENT_SCOPE_MISMATCH"
            )
        row_source_id = str(row.get("source_id") or "").strip()
        if row_source_id and row_source_id != normalized_source_id:
            raise Pre2016ExternalValidationError(
                "PRE2016_CALENDAR_REVIEW_SOURCE_ID_MISMATCH"
            )
        classification = str(row.get("classification") or "").strip().upper()
        if classification not in _ALLOWED_CLASSIFICATIONS:
            raise Pre2016ExternalValidationError(
                "PRE2016_CALENDAR_CLASSIFICATION_INVALID"
            )
        try:
            trading_date = date.fromisoformat(str(row.get("trading_date") or ""))
        except ValueError as exc:
            raise Pre2016ExternalValidationError(
                "PRE2016_CALENDAR_REVIEW_DATE_INVALID"
            ) from exc
        if trading_date.year not in years:
            raise Pre2016ExternalValidationError(
                "PRE2016_CALENDAR_REVIEW_DATE_OUTSIDE_COVERAGE"
            )
        if trading_date in observed_dates:
            raise Pre2016ExternalValidationError(
                "PRE2016_CALENDAR_REVIEW_DUPLICATE_DATE"
            )
        observed_dates.add(trading_date)
        description = str(row.get("description") or "").strip()
        if not description:
            raise Pre2016ExternalValidationError(
                "PRE2016_CALENDAR_REVIEW_DESCRIPTION_EMPTY"
            )
        record = {
            "trading_date": trading_date.isoformat(),
            "description": description,
        }
        if classification == "HOLIDAY":
            holidays.append(record)
        else:
            special_sessions.append(record)

    payload: dict[str, object] = {
        "source_id": normalized_source_id,
        "source_url": source_url,
        "calendar_year": years[0] if len(years) == 1 else None,
        "covered_years": list(years),
        "segment_scope": normalized_scope,
        "holidays": sorted(holidays, key=lambda row: row["trading_date"]),
        "special_sessions": sorted(
            special_sessions,
            key=lambda row: row["trading_date"],
        ),
        "source_document_path": str(source_document.resolve()),
        "source_document_sha256": _sha256(source_document),
        "review_csv_path": str(review_csv.resolve()),
        "review_csv_sha256": _sha256(review_csv),
        "extracted_text_path": (
            str(extracted_text.resolve()) if extracted_text is not None else None
        ),
        "extracted_text_sha256": (
            _sha256(extracted_text) if extracted_text is not None else None
        ),
        "content_validation_path": (
            str(content_validation.resolve())
            if content_validation is not None
            else None
        ),
        "content_validation_sha256": (
            _sha256(content_validation) if content_validation is not None else None
        ),
        "content_validation_passed": content_validation_passed,
        "manual_review_completed": manual_review_completed,
        "classification_inferred_from_archive_status": False,
        "classification_inferred_from_observed_candles": False,
        "production_influence": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def validate_hash_bound_official_calendar_source(
    source_path: Path,
    *,
    require_capital_market_scope: bool = False,
) -> dict[str, object]:
    """Validate all governed files and scope before a source is consumed."""

    if not source_path.is_file():
        raise Pre2016ExternalValidationError("PRE2016_OFFICIAL_SOURCE_FILE_MISSING")
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Pre2016ExternalValidationError("PRE2016_OFFICIAL_SOURCE_INVALID") from exc
    if not isinstance(payload, dict):
        raise Pre2016ExternalValidationError("PRE2016_OFFICIAL_SOURCE_INVALID")
    _validate_bound_path(
        payload,
        path_key="source_document_path",
        hash_key="source_document_sha256",
        missing_code="PRE2016_OFFICIAL_DOCUMENT_MISSING",
        mismatch_code="PRE2016_OFFICIAL_DOCUMENT_HASH_MISMATCH",
        required=True,
    )
    _validate_bound_path(
        payload,
        path_key="review_csv_path",
        hash_key="review_csv_sha256",
        missing_code="PRE2016_CALENDAR_REVIEW_CSV_MISSING",
        mismatch_code="PRE2016_CALENDAR_REVIEW_HASH_MISMATCH",
        required=True,
    )
    _validate_bound_path(
        payload,
        path_key="extracted_text_path",
        hash_key="extracted_text_sha256",
        missing_code="PRE2016_EXTRACTED_TEXT_MISSING",
        mismatch_code="PRE2016_EXTRACTED_TEXT_HASH_MISMATCH",
        required=False,
    )
    _validate_bound_path(
        payload,
        path_key="content_validation_path",
        hash_key="content_validation_sha256",
        missing_code="PRE2016_CONTENT_VALIDATION_MISSING",
        mismatch_code="PRE2016_CONTENT_VALIDATION_HASH_MISMATCH",
        required=False,
    )
    if payload.get("content_validation_passed") is not True:
        raise Pre2016ExternalValidationError(
            "PRE2016_OFFICIAL_SOURCE_CONTENT_VALIDATION_FAILED"
        )
    if payload.get("manual_review_completed") is not True:
        raise Pre2016ExternalValidationError(
            "PRE2016_OFFICIAL_SOURCE_MANUAL_REVIEW_INCOMPLETE"
        )
    if payload.get("classification_inferred_from_archive_status") is not False:
        raise Pre2016ExternalValidationError(
            "PRE2016_CALENDAR_ARCHIVE_STATUS_INFERENCE_FORBIDDEN"
        )
    if payload.get("classification_inferred_from_observed_candles") is not False:
        raise Pre2016ExternalValidationError(
            "PRE2016_CALENDAR_CANDLE_INFERENCE_FORBIDDEN"
        )
    if payload.get("production_influence") is not False:
        raise Pre2016ExternalValidationError(
            "PRE2016_OFFICIAL_SOURCE_PRODUCTION_INFLUENCE_FORBIDDEN"
        )
    scope = str(payload.get("segment_scope") or "UNKNOWN").strip().upper()
    if scope not in _ALLOWED_SEGMENT_SCOPES:
        raise Pre2016ExternalValidationError("PRE2016_SEGMENT_SCOPE_INVALID")
    if require_capital_market_scope and scope not in {
        "CAPITAL_MARKET",
        "EXCHANGE_WIDE",
    }:
        raise Pre2016ExternalValidationError(
            "PRE2016_CAPITAL_MARKET_SEGMENT_SCOPE_INSUFFICIENT"
        )
    return {str(key): value for key, value in payload.items()}


def _validate_bound_path(
    payload: dict[str, object],
    *,
    path_key: str,
    hash_key: str,
    missing_code: str,
    mismatch_code: str,
    required: bool,
) -> None:
    raw_path = payload.get(path_key)
    raw_hash = payload.get(hash_key)
    if raw_path is None and raw_hash is None and not required:
        return
    if not raw_path or not raw_hash:
        raise Pre2016ExternalValidationError(missing_code)
    path = Path(str(raw_path))
    if not path.is_file():
        raise Pre2016ExternalValidationError(missing_code)
    if _sha256(path) != str(raw_hash):
        raise Pre2016ExternalValidationError(mismatch_code)


def _latest_manifest_rows(manifest: Path) -> dict[date, dict[str, object]]:
    latest: dict[date, dict[str, object]] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            trading_date = date.fromisoformat(str(payload.get("trading_date") or ""))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        if DSI010_EXTERNAL_START <= trading_date <= DSI010_EXTERNAL_END:
            latest[trading_date] = payload
    return latest


def _count_by_year(
    rows: tuple[dict[str, object], ...] | list[dict[str, object]],
) -> dict[int, int]:
    counts: dict[int, int] = {}
    for row in rows:
        raw_year = row["calendar_year"]
        if isinstance(raw_year, bool) or not isinstance(raw_year, (int, str)):
            raise Pre2016ExternalValidationError(
                "PRE2016_DISCOVERY_CALENDAR_YEAR_INVALID"
            )
        try:
            year = int(raw_year)
        except ValueError as exc:
            raise Pre2016ExternalValidationError(
                "PRE2016_DISCOVERY_CALENDAR_YEAR_INVALID"
            ) from exc
        counts[year] = counts.get(year, 0) + 1
    return counts


def _write_csv(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    fieldnames = tuple(rows[0]) if rows else ("trading_date",)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: value.isoformat() if isinstance(value, date) else value
                    for key, value in row.items()
                }
            )


def _validate_official_url(source_url: str) -> None:
    parsed = urlparse(source_url.strip())
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_OFFICIAL_HOSTS:
        raise Pre2016ExternalValidationError("PRE2016_OFFICIAL_SOURCE_URL_INVALID")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "Pre2016CalendarDiscovery",
    "build_reviewed_official_calendar_source",
    "discover_pre2016_calendar_evidence",
    "export_pre2016_calendar_discovery",
    "validate_hash_bound_official_calendar_source",
]
