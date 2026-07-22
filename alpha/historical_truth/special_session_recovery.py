from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import requests

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.service import HistoricalTruthWarehouse
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine
from alpha.historical_truth.special_session_snapshot_parity import (
    SnapshotFailureCode,
    SnapshotParityRecord,
    SnapshotParityStatus,
    SpecialSessionSnapshotParityEngine,
)

HTR007B_CONTRACT_VERSION = "HTR-007B-v1.1.0"
PRODUCTION_INFLUENCE = False
_OFFICIAL_HOST_SUFFIX = "nseindia.com"
_LEGACY_DATE_COLUMNS = ("TIMESTAMP", "TRADE_DATE")
_UDIFF_DATE_COLUMNS = ("TradDt", "BizDt")


class SpecialSessionSourceStatus(StrEnum):
    ACQUIRED = "acquired"
    REUSED = "reused"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"


class SpecialSessionValidationStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    NOT_TESTED = "not_tested"


class SpecialSessionIngestionStatus(StrEnum):
    INGESTED = "ingested"
    REUSED = "reused"
    CONFLICT = "conflict"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"


class SpecialSessionRecoveryStatus(StrEnum):
    COMPLETE = "complete"
    REUSED = "reused"
    FAILED = "failed"


class SpecialSessionFailureCode(StrEnum):
    CALENDAR_REPORT_INVALID = "CALENDAR_REPORT_INVALID"
    NOT_OFFICIAL_SPECIAL_SESSION = "NOT_OFFICIAL_SPECIAL_SESSION"
    OFFICIAL_ARCHIVE_NOT_FOUND = "OFFICIAL_ARCHIVE_NOT_FOUND"
    HTTP_ACCESS_DENIED = "HTTP_ACCESS_DENIED"
    HTTP_RATE_LIMITED = "HTTP_RATE_LIMITED"
    HTTP_ERROR = "HTTP_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    INVALID_ARCHIVE_FORMAT = "INVALID_ARCHIVE_FORMAT"
    ARCHIVE_PARSE_FAILED = "ARCHIVE_PARSE_FAILED"
    ARCHIVE_MEMBER_INVALID = "ARCHIVE_MEMBER_INVALID"
    ARCHIVE_DATE_MISMATCH = "ARCHIVE_DATE_MISMATCH"
    SOURCE_DATE_MISMATCH = "SOURCE_DATE_MISMATCH"
    MIXED_TRADING_DATES = "MIXED_TRADING_DATES"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    INVALID_CANDLE_DATA = "INVALID_CANDLE_DATA"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    CANONICAL_CONFLICT = "CANONICAL_CONFLICT"
    IDENTITY_RESOLUTION_FAILED = "IDENTITY_RESOLUTION_FAILED"
    INGESTION_FAILED = "INGESTION_FAILED"
    SNAPSHOT_PARITY_FAILED = "SNAPSHOT_PARITY_FAILED"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class SpecialSessionSourcePattern(StrEnum):
    NSEARCHIVES_LEGACY_CM = "NSEARCHIVES_LEGACY_CM"
    ARCHIVES_LEGACY_CM = "ARCHIVES_LEGACY_CM"


@dataclass(frozen=True, slots=True)
class SpecialSessionSourceAttempt:
    source_pattern: SpecialSessionSourcePattern
    source_url: str
    attempted_at: str
    http_status: int | None
    content_type: str | None
    byte_size: int
    redirect_chain: tuple[str, ...]
    source_sha256: str | None
    failure_code: SpecialSessionFailureCode | None
    failure_detail: str | None


@dataclass(frozen=True, slots=True)
class SpecialSessionValidationFinding:
    code: str
    row_number: int | None
    detail: str


@dataclass(frozen=True, slots=True)
class SpecialSessionRecoveryRecord:
    trading_date: date
    calendar_report_sha256: str
    calendar_source_ids: tuple[str, ...]
    calendar_classification: str
    calendar_missing_at_start: bool
    official_source_url: str | None
    attempted_source_pattern: str | None
    attempts: tuple[SpecialSessionSourceAttempt, ...]
    acquisition_timestamp: str | None
    http_status: int | None
    content_type: str | None
    byte_size: int
    redirect_chain: tuple[str, ...]
    source_sha256: str | None
    archive_filename: str | None
    archive_format: str | None
    raw_archive_path: str | None
    extracted_filename: str | None
    extracted_source_path: str | None
    extracted_sha256: str | None
    normalized_path: str | None
    normalized_sha256: str | None
    acquisition_manifest_path: str | None
    parser_selected: str | None
    row_count: int
    unique_securities: int
    identity_resolved_rows: int
    validation_findings: tuple[SpecialSessionValidationFinding, ...]
    source_status: SpecialSessionSourceStatus
    validation_status: SpecialSessionValidationStatus
    ingestion_status: SpecialSessionIngestionStatus
    recovery_status: SpecialSessionRecoveryStatus
    inserted_rows: int
    reused_rows: int
    lineage_rows: int
    snapshot_path: str | None
    snapshot_status: SnapshotParityStatus | None
    snapshot_failure_code: SnapshotFailureCode | None
    snapshot_failure_detail: str | None
    snapshot_content_sha256: str | None
    snapshot_symbol_count: int | None
    snapshot_total_volume: int | None
    snapshot_completeness_score: float | None
    snapshot_verification_valid: bool
    snapshot_created: bool
    snapshot_reused: bool
    canonical_snapshot_row_match: bool
    canonical_snapshot_content_match: bool
    failure_code: SpecialSessionFailureCode | None
    failure_detail: str | None


@dataclass(frozen=True, slots=True)
class SpecialSessionRecoveryReport:
    calendar_report_path: str
    calendar_report_sha256: str
    database_path: str
    records: tuple[SpecialSessionRecoveryRecord, ...]
    complete_count: int
    reused_count: int
    failed_count: int
    production_influence: bool
    report_sha256: str
    contract_version: str = HTR007B_CONTRACT_VERSION

    @property
    def complete(self) -> bool:
        return bool(self.records) and self.failed_count == 0


@dataclass(frozen=True, slots=True)
class _CalendarTarget:
    trading_date: date
    source_ids: tuple[str, ...]
    report_sha256: str
    missing_at_start: bool


@dataclass(frozen=True, slots=True)
class _AcquiredArchive:
    source_url: str
    source_pattern: SpecialSessionSourcePattern
    acquisition_timestamp: str
    http_status: int
    content_type: str | None
    byte_size: int
    redirect_chain: tuple[str, ...]
    source_sha256: str
    archive_filename: str
    raw_path: Path
    manifest_path: Path
    attempts: tuple[SpecialSessionSourceAttempt, ...]
    reused: bool


@dataclass(frozen=True, slots=True)
class _ValidatedArchive:
    extracted_filename: str
    extracted_path: Path
    extracted_sha256: str
    normalized_path: Path
    normalized_sha256: str
    parser_selected: str
    row_count: int
    unique_securities: int
    identity_resolved_rows: int
    findings: tuple[SpecialSessionValidationFinding, ...]


class _RecoveryFailure(Exception):
    def __init__(
        self,
        code: SpecialSessionFailureCode,
        detail: str,
        *,
        attempts: tuple[SpecialSessionSourceAttempt, ...] = (),
        findings: tuple[SpecialSessionValidationFinding, ...] = (),
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.attempts = attempts
        self.findings = findings


class SpecialSessionCandleRecoveryEngine:
    """Recover official weekend NSE CM sessions without changing calendar policy."""

    def __init__(
        self,
        root: Path,
        canonical: CanonicalPointInTimeWarehouse,
        *,
        timeout_seconds: float = 30.0,
        session: requests.Session | None = None,
        clock: Callable[[], datetime] | None = None,
        snapshots: PointInTimeSnapshotEngine | None = None,
    ) -> None:
        self.root = root
        self.canonical = canonical
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.snapshots = snapshots or PointInTimeSnapshotEngine(
            canonical,
            root / "snapshots",
        )
        self.snapshot_parity = SpecialSessionSnapshotParityEngine(
            canonical,
            self.snapshots,
            clock=self.clock,
        )

    def recover(
        self,
        calendar_report: Path,
        *,
        selected_dates: tuple[date, ...] = (),
        refresh: bool = False,
        progress: Callable[[int, int, date], None] | None = None,
    ) -> SpecialSessionRecoveryReport:
        payload = self._load_calendar_report(calendar_report)
        report_sha = str(payload["report_sha256"])
        targets, invalid_dates = self._targets(payload, selected_dates)
        records: list[SpecialSessionRecoveryRecord] = [
            self._calendar_rejection(item, report_sha) for item in invalid_dates
        ]
        total = len(targets) + len(invalid_dates)
        completed = len(invalid_dates)
        for target in targets:
            records.append(self._recover_one(target, refresh=refresh))
            completed += 1
            if progress is not None:
                progress(completed, total, target.trading_date)
        ordered = tuple(sorted(records, key=lambda item: item.trading_date))
        provisional = SpecialSessionRecoveryReport(
            calendar_report_path=str(calendar_report),
            calendar_report_sha256=report_sha,
            database_path=str(self.canonical.database_path),
            records=ordered,
            complete_count=sum(
                item.recovery_status is SpecialSessionRecoveryStatus.COMPLETE
                for item in ordered
            ),
            reused_count=sum(
                item.recovery_status is SpecialSessionRecoveryStatus.REUSED
                for item in ordered
            ),
            failed_count=sum(
                item.recovery_status is SpecialSessionRecoveryStatus.FAILED
                for item in ordered
            ),
            production_influence=PRODUCTION_INFLUENCE,
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

    def _recover_one(
        self,
        target: _CalendarTarget,
        *,
        refresh: bool,
    ) -> SpecialSessionRecoveryRecord:
        attempts: tuple[SpecialSessionSourceAttempt, ...] = ()
        acquired: _AcquiredArchive | None = None
        try:
            acquired = self._acquire(target.trading_date, refresh=refresh)
            attempts = acquired.attempts
            validated = self._validate_archive(acquired, target.trading_date)
            try:
                ingestion = self.canonical.ingest_bhavcopy_csv_fail_closed(
                    validated.extracted_path,
                    trading_date=target.trading_date,
                    exchange="nse",
                    source_sha256=acquired.source_sha256,
                    source_url=acquired.source_url,
                    archive_path=str(acquired.raw_path),
                    normalized_path=str(validated.normalized_path),
                )
            except ValueError as exc:
                detail = str(exc)
                if "canonical candle conflict" in detail:
                    code = SpecialSessionFailureCode.CANONICAL_CONFLICT
                    ingestion_status = SpecialSessionIngestionStatus.CONFLICT
                elif "identity conflict" in detail:
                    code = SpecialSessionFailureCode.IDENTITY_RESOLUTION_FAILED
                    ingestion_status = SpecialSessionIngestionStatus.FAILED
                else:
                    code = SpecialSessionFailureCode.INGESTION_FAILED
                    ingestion_status = SpecialSessionIngestionStatus.FAILED
                return self._record(
                    target,
                    acquired=acquired,
                    validated=validated,
                    attempts=attempts,
                    ingestion_status=ingestion_status,
                    failure_code=code,
                    failure_detail=detail,
                )
            snapshot = self.snapshot_parity.ensure_snapshot(
                target.trading_date,
                source_ids=target.source_ids,
            )
            if not snapshot.valid:
                return self._record(
                    target,
                    acquired=acquired,
                    validated=validated,
                    attempts=attempts,
                    ingestion_status=(
                        SpecialSessionIngestionStatus.REUSED
                        if ingestion.inserted_rows == 0
                        else SpecialSessionIngestionStatus.INGESTED
                    ),
                    inserted_rows=ingestion.inserted_rows,
                    reused_rows=ingestion.reused_rows,
                    lineage_rows=ingestion.lineage_rows,
                    snapshot=snapshot,
                    failure_code=SpecialSessionFailureCode.SNAPSHOT_PARITY_FAILED,
                    failure_detail=(
                        snapshot.snapshot_failure_detail
                        or "immutable snapshot parity verification failed"
                    ),
                )
            reused = (
                ingestion.inserted_rows == 0
                and snapshot.snapshot_status is not SnapshotParityStatus.CREATED
            )
            return self._record(
                target,
                acquired=acquired,
                validated=validated,
                attempts=attempts,
                ingestion_status=(
                    SpecialSessionIngestionStatus.REUSED
                    if reused
                    else SpecialSessionIngestionStatus.INGESTED
                ),
                recovery_status=(
                    SpecialSessionRecoveryStatus.REUSED
                    if reused
                    else SpecialSessionRecoveryStatus.COMPLETE
                ),
                inserted_rows=ingestion.inserted_rows,
                reused_rows=ingestion.reused_rows,
                lineage_rows=ingestion.lineage_rows,
                snapshot=snapshot,
            )
        except _RecoveryFailure as exc:
            attempts = exc.attempts or attempts
            if exc.code is SpecialSessionFailureCode.OFFICIAL_ARCHIVE_NOT_FOUND:
                source_status = SpecialSessionSourceStatus.UNAVAILABLE
            elif acquired is None:
                source_status = SpecialSessionSourceStatus.FAILED
            elif acquired.reused:
                source_status = SpecialSessionSourceStatus.REUSED
            else:
                source_status = SpecialSessionSourceStatus.ACQUIRED
            validation_status = (
                SpecialSessionValidationStatus.INVALID
                if acquired is not None
                else SpecialSessionValidationStatus.NOT_TESTED
            )
            return self._record(
                target,
                acquired=acquired,
                attempts=attempts,
                validation_findings=exc.findings,
                source_status=source_status,
                validation_status=validation_status,
                failure_code=exc.code,
                failure_detail=exc.detail,
            )
        except Exception as exc:
            return self._record(
                target,
                acquired=acquired,
                attempts=attempts,
                failure_code=SpecialSessionFailureCode.UNKNOWN_FAILURE,
                failure_detail=f"{type(exc).__name__}: {exc}",
            )

    def _acquire(self, trading_date: date, *, refresh: bool) -> _AcquiredArchive:
        cached = self._cached_archive(trading_date)
        if cached is not None and not refresh:
            return cached

        attempts: list[SpecialSessionSourceAttempt] = []
        trusted_sha = cached.source_sha256 if cached is not None else None
        for pattern, source_url in self._source_candidates(trading_date):
            attempted_at = self.clock().isoformat()
            if not self._is_official_nse_url(source_url):
                raise _RecoveryFailure(
                    SpecialSessionFailureCode.HTTP_ACCESS_DENIED,
                    "source URL is outside approved NSE hosts",
                )
            try:
                response = self.session.get(
                    source_url,
                    timeout=self.timeout_seconds,
                    headers={
                        "Accept": "application/zip,application/octet-stream,*/*",
                        "User-Agent": "ProjectAlpha-HistoricalTruth/HTR-007B",
                        "Connection": "close",
                    },
                )
            except requests.RequestException as exc:
                attempts.append(
                    self._failed_attempt(
                        pattern,
                        source_url,
                        attempted_at,
                        SpecialSessionFailureCode.NETWORK_ERROR,
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            status = int(response.status_code)
            content_type = response.headers.get("Content-Type")
            redirect_chain = tuple(
                str(item.url) for item in (*response.history, response)
            )
            raw = bytes(response.content)
            if status == 404:
                attempts.append(
                    SpecialSessionSourceAttempt(
                        source_pattern=pattern,
                        source_url=source_url,
                        attempted_at=attempted_at,
                        http_status=status,
                        content_type=content_type,
                        byte_size=len(raw),
                        redirect_chain=redirect_chain,
                        source_sha256=None,
                        failure_code=(
                            SpecialSessionFailureCode.OFFICIAL_ARCHIVE_NOT_FOUND
                        ),
                        failure_detail="official NSE archive returned HTTP 404",
                    )
                )
                continue
            if status in {401, 403}:
                code = SpecialSessionFailureCode.HTTP_ACCESS_DENIED
            elif status == 429:
                code = SpecialSessionFailureCode.HTTP_RATE_LIMITED
            elif status >= 400:
                code = SpecialSessionFailureCode.HTTP_ERROR
            else:
                code = None
            if code is not None:
                attempts.append(
                    SpecialSessionSourceAttempt(
                        source_pattern=pattern,
                        source_url=source_url,
                        attempted_at=attempted_at,
                        http_status=status,
                        content_type=content_type,
                        byte_size=len(raw),
                        redirect_chain=redirect_chain,
                        source_sha256=None,
                        failure_code=code,
                        failure_detail=f"official NSE archive returned HTTP {status}",
                    )
                )
                continue
            if not raw:
                attempts.append(
                    self._failed_attempt(
                        pattern,
                        source_url,
                        attempted_at,
                        SpecialSessionFailureCode.EMPTY_RESPONSE,
                        "official NSE archive returned no bytes",
                        http_status=status,
                        content_type=content_type,
                        redirect_chain=redirect_chain,
                    )
                )
                continue
            if not raw.startswith(b"PK\x03\x04"):
                attempts.append(
                    self._failed_attempt(
                        pattern,
                        source_url,
                        attempted_at,
                        SpecialSessionFailureCode.INVALID_ARCHIVE_FORMAT,
                        "official response is not a ZIP archive",
                        http_status=status,
                        content_type=content_type,
                        byte_size=len(raw),
                        redirect_chain=redirect_chain,
                    )
                )
                continue
            digest = hashlib.sha256(raw).hexdigest()
            if trusted_sha is not None and trusted_sha != digest:
                raise _RecoveryFailure(
                    SpecialSessionFailureCode.CHECKSUM_MISMATCH,
                    "refetched archive differs from immutable trusted evidence",
                    attempts=tuple(attempts),
                )
            archive_filename = Path(urlparse(source_url).path).name
            raw_path = self._persist_raw(
                trading_date,
                archive_filename,
                digest,
                raw,
            )
            attempt = SpecialSessionSourceAttempt(
                source_pattern=pattern,
                source_url=source_url,
                attempted_at=attempted_at,
                http_status=status,
                content_type=content_type,
                byte_size=len(raw),
                redirect_chain=redirect_chain,
                source_sha256=digest,
                failure_code=None,
                failure_detail=None,
            )
            attempts.append(attempt)
            manifest_path = self._write_acquisition_manifest(
                trading_date,
                source_url=source_url,
                source_pattern=pattern,
                acquisition_timestamp=attempted_at,
                http_status=status,
                content_type=content_type,
                byte_size=len(raw),
                redirect_chain=redirect_chain,
                source_sha256=digest,
                archive_filename=archive_filename,
                raw_path=raw_path,
                attempts=tuple(attempts),
            )
            return _AcquiredArchive(
                source_url=source_url,
                source_pattern=pattern,
                acquisition_timestamp=attempted_at,
                http_status=status,
                content_type=content_type,
                byte_size=len(raw),
                redirect_chain=redirect_chain,
                source_sha256=digest,
                archive_filename=archive_filename,
                raw_path=raw_path,
                manifest_path=manifest_path,
                attempts=tuple(attempts),
                reused=False,
            )
        raise _RecoveryFailure(
            SpecialSessionFailureCode.OFFICIAL_ARCHIVE_NOT_FOUND,
            "no approved official NSE archive source returned session evidence",
            attempts=tuple(attempts),
        )

    def _validate_archive(
        self,
        acquired: _AcquiredArchive,
        trading_date: date,
    ) -> _ValidatedArchive:
        expected_token = trading_date.strftime("%d%b%Y").upper()
        if expected_token not in acquired.archive_filename.upper():
            raise _RecoveryFailure(
                SpecialSessionFailureCode.ARCHIVE_DATE_MISMATCH,
                "archive filename does not identify the intended session date",
            )
        try:
            with zipfile.ZipFile(acquired.raw_path) as archive:
                members = tuple(
                    item
                    for item in archive.infolist()
                    if not item.is_dir() and item.filename.lower().endswith(".csv")
                )
                if len(members) != 1:
                    raise _RecoveryFailure(
                        SpecialSessionFailureCode.ARCHIVE_MEMBER_INVALID,
                        "official archive must contain exactly one CSV member",
                    )
                member = members[0]
                member_path = PurePosixPath(member.filename)
                if member_path.name != member.filename or ".." in member_path.parts:
                    raise _RecoveryFailure(
                        SpecialSessionFailureCode.ARCHIVE_MEMBER_INVALID,
                        "archive CSV member is not a safe top-level file",
                    )
                if expected_token not in member_path.name.upper():
                    raise _RecoveryFailure(
                        SpecialSessionFailureCode.ARCHIVE_DATE_MISMATCH,
                        "archive member does not identify the intended session date",
                    )
                raw_csv = archive.read(member)
        except _RecoveryFailure:
            raise
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise _RecoveryFailure(
                SpecialSessionFailureCode.ARCHIVE_PARSE_FAILED,
                f"{type(exc).__name__}: {exc}",
            ) from exc
        extracted_sha = hashlib.sha256(raw_csv).hexdigest()
        extracted_path = self._persist_derivative(
            trading_date,
            "extracted",
            Path(member.filename).stem,
            ".csv",
            extracted_sha,
            raw_csv,
        )
        rows, schema, findings = self._validate_csv(
            raw_csv,
            trading_date=trading_date,
        )
        errors = tuple(item for item in findings if item.code != "INFO")
        if errors:
            code = self._validation_failure_code(errors)
            raise _RecoveryFailure(
                code,
                "; ".join(f"{item.code}: {item.detail}" for item in errors[:10]),
                findings=findings,
            )
        normalized = self._normalized_csv(
            rows,
            schema=schema,
            trading_date=trading_date,
            source_sha256=acquired.source_sha256,
        )
        normalized_sha = hashlib.sha256(normalized).hexdigest()
        normalized_path = self._persist_derivative(
            trading_date,
            "normalized",
            f"nse_cm_special_session_{trading_date.isoformat()}",
            ".csv",
            normalized_sha,
            normalized,
        )
        unique = len(
            {
                (
                    self._row_value(row, schema, "symbol"),
                    self._row_value(row, schema, "series"),
                )
                for _, row in rows
            }
        )
        return _ValidatedArchive(
            extracted_filename=member.filename,
            extracted_path=extracted_path,
            extracted_sha256=extracted_sha,
            normalized_path=normalized_path,
            normalized_sha256=normalized_sha,
            parser_selected=f"nse_{schema}_cm_bhavcopy",
            row_count=len(rows),
            unique_securities=unique,
            identity_resolved_rows=len(rows),
            findings=findings,
        )

    def _validate_csv(
        self,
        raw_csv: bytes,
        *,
        trading_date: date,
    ) -> tuple[
        tuple[tuple[int, dict[str, str]], ...],
        str,
        tuple[SpecialSessionValidationFinding, ...],
    ]:
        text = raw_csv.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        original_fields = tuple(reader.fieldnames or ())
        fields = tuple(item.strip() for item in original_fields)
        schema = HistoricalTruthWarehouse.detect_bhavcopy_schema(frozenset(fields))
        if schema is None:
            raise _RecoveryFailure(
                SpecialSessionFailureCode.UNSUPPORTED_SCHEMA,
                "official archive does not contain a governed Capital Market schema",
            )
        date_column = next(
            (
                item
                for item in (
                    _LEGACY_DATE_COLUMNS if schema == "legacy" else _UDIFF_DATE_COLUMNS
                )
                if item in fields
            ),
            None,
        )
        if date_column is None:
            raise _RecoveryFailure(
                SpecialSessionFailureCode.SOURCE_DATE_MISMATCH,
                "official bhavcopy has no governed trading-date column",
            )
        rows: list[tuple[int, dict[str, str]]] = []
        findings: list[SpecialSessionValidationFinding] = []
        source_dates: set[date] = set()
        seen: set[tuple[str, str]] = set()
        field_map = self._schema_field_map(schema)
        for row_number, original in enumerate(reader, start=2):
            row = {
                str(key).strip(): (value or "").strip()
                for key, value in original.items()
                if key is not None
            }
            rows.append((row_number, row))
            parsed_date = self._parse_source_date(row.get(date_column, ""))
            if parsed_date is None:
                findings.append(
                    SpecialSessionValidationFinding(
                        code="INVALID_TRADING_DATE",
                        row_number=row_number,
                        detail=f"invalid {date_column} value",
                    )
                )
            else:
                source_dates.add(parsed_date)
            symbol = row.get(field_map["symbol"], "")
            series = row.get(field_map["series"], "")
            if not self._valid_symbol(symbol) or not self._valid_series(series):
                findings.append(
                    SpecialSessionValidationFinding(
                        code="INVALID_SECURITY_IDENTITY",
                        row_number=row_number,
                        detail=f"invalid symbol/series {symbol!r}/{series!r}",
                    )
                )
            key = (symbol, series)
            if key in seen:
                findings.append(
                    SpecialSessionValidationFinding(
                        code="DUPLICATE_SYMBOL_SERIES",
                        row_number=row_number,
                        detail=f"duplicate {symbol}/{series}",
                    )
                )
            seen.add(key)
            try:
                open_price = float(row[field_map["open"]])
                high_price = float(row[field_map["high"]])
                low_price = float(row[field_map["low"]])
                close_price = float(row[field_map["close"]])
                volume = float(row[field_map["volume"]])
            except (KeyError, ValueError):
                findings.append(
                    SpecialSessionValidationFinding(
                        code="INVALID_NUMERIC_VALUE",
                        row_number=row_number,
                        detail=f"invalid OHLCV for {symbol}/{series}",
                    )
                )
                continue
            if min(open_price, high_price, low_price, close_price, volume) < 0:
                findings.append(
                    SpecialSessionValidationFinding(
                        code="NEGATIVE_OHLCV",
                        row_number=row_number,
                        detail=f"negative OHLCV for {symbol}/{series}",
                    )
                )
            if not (
                high_price >= max(open_price, low_price, close_price)
                and low_price <= min(open_price, high_price, close_price)
            ):
                findings.append(
                    SpecialSessionValidationFinding(
                        code="IMPOSSIBLE_OHLC",
                        row_number=row_number,
                        detail=f"impossible OHLC for {symbol}/{series}",
                    )
                )
        if not rows:
            findings.append(
                SpecialSessionValidationFinding(
                    code="EMPTY_SOURCE",
                    row_number=None,
                    detail="official bhavcopy contains no candle rows",
                )
            )
        if len(source_dates) > 1:
            finding = SpecialSessionValidationFinding(
                code="MIXED_TRADING_DATES",
                row_number=None,
                detail="official source contains more than one trading date",
            )
            raise _RecoveryFailure(
                SpecialSessionFailureCode.MIXED_TRADING_DATES,
                finding.detail,
                findings=(*findings, finding),
            )
        if source_dates and source_dates != {trading_date}:
            finding = SpecialSessionValidationFinding(
                code="SOURCE_DATE_MISMATCH",
                row_number=None,
                detail="candle rows do not match the intended special-session date",
            )
            raise _RecoveryFailure(
                SpecialSessionFailureCode.SOURCE_DATE_MISMATCH,
                finding.detail,
                findings=(*findings, finding),
            )
        return tuple(rows), schema, tuple(findings)

    def _load_calendar_report(self, path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid calendar report: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("records"), list
        ):
            raise ValueError("calendar report has an unsupported structure")
        expected_hash = payload.get("report_sha256")
        without_hash = dict(payload)
        without_hash.pop("report_sha256", None)
        observed_hash = hashlib.sha256(
            json.dumps(
                without_hash,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if expected_hash != observed_hash:
            raise ValueError("calendar report checksum verification failed")
        self._verify_calendar_sources(payload)
        return payload

    def _verify_calendar_sources(self, payload: Mapping[str, object]) -> None:
        sources = payload.get("sources")
        if not isinstance(sources, list):
            raise ValueError("calendar report has no source registry")
        for raw in sources:
            if not isinstance(raw, dict):
                raise ValueError("calendar source registry is malformed")
            url = raw.get("source_url")
            source_path = raw.get("source_path")
            source_sha = raw.get("source_sha256")
            if not isinstance(url, str) or not self._is_official_nse_url(url):
                raise ValueError("calendar source is not controlled by NSE")
            if not isinstance(source_path, str) or not isinstance(source_sha, str):
                raise ValueError("calendar source lacks path or checksum lineage")
            path = Path(source_path)
            if not path.exists():
                raise ValueError(f"calendar source evidence is missing: {path}")
            observed = hashlib.sha256(path.read_bytes()).hexdigest()
            if observed != source_sha:
                raise ValueError(f"calendar source checksum mismatch: {path}")

    def _targets(
        self,
        payload: Mapping[str, object],
        selected_dates: tuple[date, ...],
    ) -> tuple[tuple[_CalendarTarget, ...], tuple[date, ...]]:
        report_sha = str(payload["report_sha256"])
        records = payload["records"]
        assert isinstance(records, list)
        source_registry = payload.get("sources")
        assert isinstance(source_registry, list)
        governed_source_ids = {
            str(item["source_id"])
            for item in source_registry
            if isinstance(item, dict) and item.get("source_id")
        }
        specials: dict[date, _CalendarTarget] = {}
        for raw in records:
            if (
                not isinstance(raw, dict)
                or raw.get("classification") != "special_session"
            ):
                continue
            value = date.fromisoformat(str(raw["trading_date"]))
            source_ids_raw = raw.get("source_ids", [])
            source_ids = tuple(str(item) for item in source_ids_raw)
            if not source_ids or not set(source_ids).issubset(governed_source_ids):
                raise ValueError(
                    "special-session record lacks governed calendar-source lineage"
                )
            missing = "MISSING_OFFICIAL_SPECIAL_SESSION" in raw.get("issue_codes", [])
            specials[value] = _CalendarTarget(
                trading_date=value,
                source_ids=source_ids,
                report_sha256=report_sha,
                missing_at_start=missing,
            )
        selected = tuple(sorted(set(selected_dates)))
        if selected:
            invalid = tuple(item for item in selected if item not in specials)
            targets = tuple(specials[item] for item in selected if item in specials)
            return targets, invalid
        return (
            tuple(
                item
                for item in sorted(
                    specials.values(), key=lambda value: value.trading_date
                )
                if item.missing_at_start
            ),
            (),
        )

    def _cached_archive(self, trading_date: date) -> _AcquiredArchive | None:
        manifest_dir = self.root / "manifests" / "htr007b_special_sessions"
        manifests = tuple(
            sorted(manifest_dir.glob(f"{trading_date.isoformat()}_*.json"))
        )
        if not manifests:
            return None
        if len(manifests) != 1:
            raise _RecoveryFailure(
                SpecialSessionFailureCode.CHECKSUM_MISMATCH,
                "multiple immutable acquisition manifests exist for one session",
            )
        payload = json.loads(manifests[0].read_text(encoding="utf-8"))
        raw_path = self.root / str(payload["raw_relative_path"])
        expected = str(payload["source_sha256"])
        if not raw_path.exists():
            raise _RecoveryFailure(
                SpecialSessionFailureCode.CHECKSUM_MISMATCH,
                "immutable archive referenced by manifest is missing",
            )
        observed = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if observed != expected:
            raise _RecoveryFailure(
                SpecialSessionFailureCode.CHECKSUM_MISMATCH,
                "immutable archive checksum does not match acquisition manifest",
            )
        attempts_raw = payload.get("attempts")
        if not isinstance(attempts_raw, list):
            raise _RecoveryFailure(
                SpecialSessionFailureCode.CHECKSUM_MISMATCH,
                "acquisition manifest has no source-attempt lineage",
            )
        attempts = tuple(self._attempt_from_payload(item) for item in attempts_raw)
        return _AcquiredArchive(
            source_url=str(payload["source_url"]),
            source_pattern=SpecialSessionSourcePattern(str(payload["source_pattern"])),
            acquisition_timestamp=str(payload["acquisition_timestamp"]),
            http_status=int(payload["http_status"]),
            content_type=(
                str(payload["content_type"]) if payload.get("content_type") else None
            ),
            byte_size=int(payload["byte_size"]),
            redirect_chain=tuple(str(item) for item in payload["redirect_chain"]),
            source_sha256=expected,
            archive_filename=str(payload["archive_filename"]),
            raw_path=raw_path,
            manifest_path=manifests[0],
            attempts=attempts,
            reused=True,
        )

    def _write_acquisition_manifest(
        self,
        trading_date: date,
        **values: object,
    ) -> Path:
        attempts = values.pop("attempts")
        raw_path = values.pop("raw_path")
        assert isinstance(attempts, tuple)
        assert isinstance(raw_path, Path)
        payload = {
            "contract_version": HTR007B_CONTRACT_VERSION,
            "trading_date": trading_date.isoformat(),
            **values,
            "source_pattern": str(values["source_pattern"]),
            "raw_relative_path": str(raw_path.relative_to(self.root)),
            "attempts": [self._attempt_payload(item) for item in attempts],
            "production_influence": PRODUCTION_INFLUENCE,
        }
        digest = str(payload["source_sha256"])
        path = (
            self.root
            / "manifests"
            / "htr007b_special_sessions"
            / f"{trading_date.isoformat()}_{digest[:12]}.json"
        )
        encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
        self._persist_immutable(path, encoded)
        return path

    def _persist_raw(
        self,
        trading_date: date,
        filename: str,
        digest: str,
        raw: bytes,
    ) -> Path:
        stem = filename.removesuffix(".csv.zip")
        path = (
            self.root
            / "raw"
            / "nse"
            / "special_sessions"
            / str(trading_date.year)
            / trading_date.isoformat()
            / "archives"
            / f"{stem}_{digest[:12]}.csv.zip"
        )
        self._persist_immutable(path, raw)
        return path

    def _persist_derivative(
        self,
        trading_date: date,
        kind: str,
        stem: str,
        suffix: str,
        digest: str,
        raw: bytes,
    ) -> Path:
        path = (
            self.root
            / "raw"
            / "nse"
            / "special_sessions"
            / str(trading_date.year)
            / trading_date.isoformat()
            / kind
            / f"{stem}_{digest[:12]}{suffix}"
        )
        self._persist_immutable(path, raw)
        return path

    @staticmethod
    def _persist_immutable(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != raw:
                raise _RecoveryFailure(
                    SpecialSessionFailureCode.CHECKSUM_MISMATCH,
                    f"immutable path contains different bytes: {path}",
                )
            return
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(raw)
        os.replace(temporary, path)

    @staticmethod
    def _source_candidates(
        trading_date: date,
    ) -> tuple[tuple[SpecialSessionSourcePattern, str], ...]:
        year = trading_date.strftime("%Y")
        month = trading_date.strftime("%b").upper()
        filename = f"cm{trading_date.strftime('%d%b%Y').upper()}bhav.csv.zip"
        tail = f"content/historical/EQUITIES/{year}/{month}/{filename}"
        return (
            (
                SpecialSessionSourcePattern.NSEARCHIVES_LEGACY_CM,
                f"https://nsearchives.nseindia.com/{tail}",
            ),
            (
                SpecialSessionSourcePattern.ARCHIVES_LEGACY_CM,
                f"https://archives.nseindia.com/{tail}",
            ),
        )

    @staticmethod
    def _normalized_csv(
        rows: tuple[tuple[int, dict[str, str]], ...],
        *,
        schema: str,
        trading_date: date,
        source_sha256: str,
    ) -> bytes:
        fields = SpecialSessionCandleRecoveryEngine._schema_field_map(schema)
        output = io.StringIO(newline="")
        names = (
            "trading_date",
            "exchange",
            "symbol",
            "series",
            "isin",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "source_sha256",
            "source_row_number",
        )
        writer = csv.DictWriter(output, fieldnames=names, lineterminator="\n")
        writer.writeheader()
        ordered = sorted(
            rows,
            key=lambda item: (
                item[1].get(fields["symbol"], ""),
                item[1].get(fields["series"], ""),
                item[0],
            ),
        )
        for row_number, row in ordered:
            writer.writerow(
                {
                    "trading_date": trading_date.isoformat(),
                    "exchange": "nse",
                    "symbol": row.get(fields["symbol"], ""),
                    "series": row.get(fields["series"], ""),
                    "isin": row.get(fields["isin"], "") if fields["isin"] else "",
                    "open_price": row.get(fields["open"], ""),
                    "high_price": row.get(fields["high"], ""),
                    "low_price": row.get(fields["low"], ""),
                    "close_price": row.get(fields["close"], ""),
                    "volume": row.get(fields["volume"], ""),
                    "source_sha256": source_sha256,
                    "source_row_number": row_number,
                }
            )
        return output.getvalue().encode("utf-8")

    @staticmethod
    def _schema_field_map(schema: str) -> dict[str, str]:
        if schema == "legacy":
            return {
                "symbol": "SYMBOL",
                "series": "SERIES",
                "isin": "ISIN",
                "open": "OPEN",
                "high": "HIGH",
                "low": "LOW",
                "close": "CLOSE",
                "volume": "TOTTRDQTY",
            }
        return {
            "symbol": "TckrSymb",
            "series": "SctySrs",
            "isin": "ISIN",
            "open": "OpnPric",
            "high": "HghPric",
            "low": "LwPric",
            "close": "ClsPric",
            "volume": "TtlTradgVol",
        }

    @classmethod
    def _row_value(cls, row: Mapping[str, str], schema: str, name: str) -> str:
        return row.get(cls._schema_field_map(schema)[name], "")

    @staticmethod
    def _parse_source_date(value: str) -> date | None:
        cleaned = value.strip()
        for format_ in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(cleaned, format_).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _valid_symbol(value: str) -> bool:
        return (
            bool(value)
            and len(value) <= 64
            and re.fullmatch(r"[A-Z0-9&._-]+", value) is not None
        )

    @staticmethod
    def _valid_series(value: str) -> bool:
        return (
            bool(value)
            and len(value) <= 12
            and re.fullmatch(r"[A-Z0-9]+", value) is not None
        )

    @staticmethod
    def _validation_failure_code(
        findings: tuple[SpecialSessionValidationFinding, ...],
    ) -> SpecialSessionFailureCode:
        codes = {item.code for item in findings}
        if "MIXED_TRADING_DATES" in codes:
            return SpecialSessionFailureCode.MIXED_TRADING_DATES
        if "INVALID_TRADING_DATE" in codes:
            return SpecialSessionFailureCode.SOURCE_DATE_MISMATCH
        return SpecialSessionFailureCode.INVALID_CANDLE_DATA

    @staticmethod
    def _is_official_nse_url(url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == _OFFICIAL_HOST_SUFFIX or host.endswith(
            f".{_OFFICIAL_HOST_SUFFIX}"
        )

    @staticmethod
    def _failed_attempt(
        pattern: SpecialSessionSourcePattern,
        source_url: str,
        attempted_at: str,
        code: SpecialSessionFailureCode,
        detail: str,
        *,
        http_status: int | None = None,
        content_type: str | None = None,
        byte_size: int = 0,
        redirect_chain: tuple[str, ...] = (),
    ) -> SpecialSessionSourceAttempt:
        return SpecialSessionSourceAttempt(
            source_pattern=pattern,
            source_url=source_url,
            attempted_at=attempted_at,
            http_status=http_status,
            content_type=content_type,
            byte_size=byte_size,
            redirect_chain=redirect_chain,
            source_sha256=None,
            failure_code=code,
            failure_detail=detail,
        )

    @staticmethod
    def _attempt_payload(item: SpecialSessionSourceAttempt) -> dict[str, object]:
        return {
            **asdict(item),
            "source_pattern": item.source_pattern.value,
            "failure_code": item.failure_code.value if item.failure_code else None,
            "redirect_chain": list(item.redirect_chain),
        }

    @staticmethod
    def _attempt_from_payload(
        payload: Mapping[str, object],
    ) -> SpecialSessionSourceAttempt:
        failure = payload.get("failure_code")
        http_status = payload.get("http_status")
        byte_size = payload.get("byte_size", 0)
        redirect_chain = payload.get("redirect_chain", [])
        if not isinstance(redirect_chain, Sequence) or isinstance(
            redirect_chain, (str, bytes)
        ):
            raise _RecoveryFailure(
                SpecialSessionFailureCode.CHECKSUM_MISMATCH,
                "acquisition manifest redirect lineage is malformed",
            )
        return SpecialSessionSourceAttempt(
            source_pattern=SpecialSessionSourcePattern(str(payload["source_pattern"])),
            source_url=str(payload["source_url"]),
            attempted_at=str(payload["attempted_at"]),
            http_status=(int(str(http_status)) if http_status is not None else None),
            content_type=(
                str(payload["content_type"]) if payload.get("content_type") else None
            ),
            byte_size=int(str(byte_size)),
            redirect_chain=tuple(str(item) for item in redirect_chain),
            source_sha256=(
                str(payload["source_sha256"]) if payload.get("source_sha256") else None
            ),
            failure_code=(SpecialSessionFailureCode(str(failure)) if failure else None),
            failure_detail=(
                str(payload["failure_detail"])
                if payload.get("failure_detail")
                else None
            ),
        )

    def _record(
        self,
        target: _CalendarTarget,
        *,
        acquired: _AcquiredArchive | None = None,
        validated: _ValidatedArchive | None = None,
        attempts: tuple[SpecialSessionSourceAttempt, ...] = (),
        validation_findings: tuple[SpecialSessionValidationFinding, ...] = (),
        source_status: SpecialSessionSourceStatus | None = None,
        validation_status: SpecialSessionValidationStatus | None = None,
        ingestion_status: SpecialSessionIngestionStatus = (
            SpecialSessionIngestionStatus.NOT_ATTEMPTED
        ),
        recovery_status: SpecialSessionRecoveryStatus = (
            SpecialSessionRecoveryStatus.FAILED
        ),
        inserted_rows: int = 0,
        reused_rows: int = 0,
        lineage_rows: int = 0,
        snapshot: SnapshotParityRecord | None = None,
        failure_code: SpecialSessionFailureCode | None = None,
        failure_detail: str | None = None,
    ) -> SpecialSessionRecoveryRecord:
        return SpecialSessionRecoveryRecord(
            trading_date=target.trading_date,
            calendar_report_sha256=target.report_sha256,
            calendar_source_ids=target.source_ids,
            calendar_classification="special_session",
            calendar_missing_at_start=target.missing_at_start,
            official_source_url=acquired.source_url if acquired else None,
            attempted_source_pattern=(
                acquired.source_pattern.value if acquired else None
            ),
            attempts=attempts,
            acquisition_timestamp=(
                acquired.acquisition_timestamp if acquired else None
            ),
            http_status=acquired.http_status if acquired else None,
            content_type=acquired.content_type if acquired else None,
            byte_size=acquired.byte_size if acquired else 0,
            redirect_chain=acquired.redirect_chain if acquired else (),
            source_sha256=acquired.source_sha256 if acquired else None,
            archive_filename=acquired.archive_filename if acquired else None,
            archive_format="zip" if acquired else None,
            raw_archive_path=str(acquired.raw_path) if acquired else None,
            extracted_filename=(validated.extracted_filename if validated else None),
            extracted_source_path=(
                str(validated.extracted_path) if validated else None
            ),
            extracted_sha256=validated.extracted_sha256 if validated else None,
            normalized_path=str(validated.normalized_path) if validated else None,
            normalized_sha256=validated.normalized_sha256 if validated else None,
            acquisition_manifest_path=(
                str(acquired.manifest_path) if acquired else None
            ),
            parser_selected=validated.parser_selected if validated else None,
            row_count=validated.row_count if validated else 0,
            unique_securities=validated.unique_securities if validated else 0,
            identity_resolved_rows=(
                validated.identity_resolved_rows if validated else 0
            ),
            validation_findings=(
                validated.findings if validated else validation_findings
            ),
            source_status=(
                source_status
                or (
                    SpecialSessionSourceStatus.REUSED
                    if acquired and acquired.reused
                    else (
                        SpecialSessionSourceStatus.ACQUIRED
                        if acquired
                        else SpecialSessionSourceStatus.FAILED
                    )
                )
            ),
            validation_status=(
                validation_status
                or (
                    SpecialSessionValidationStatus.VALID
                    if validated
                    else SpecialSessionValidationStatus.NOT_TESTED
                )
            ),
            ingestion_status=ingestion_status,
            recovery_status=recovery_status,
            inserted_rows=inserted_rows,
            reused_rows=reused_rows,
            lineage_rows=lineage_rows,
            snapshot_path=(
                snapshot.expected_snapshot_path if snapshot is not None else None
            ),
            snapshot_status=(
                snapshot.snapshot_status if snapshot is not None else None
            ),
            snapshot_failure_code=(
                snapshot.snapshot_failure_code if snapshot is not None else None
            ),
            snapshot_failure_detail=(
                snapshot.snapshot_failure_detail if snapshot is not None else None
            ),
            snapshot_content_sha256=(
                snapshot.snapshot_content_sha256 if snapshot is not None else None
            ),
            snapshot_symbol_count=(
                snapshot.snapshot_symbol_count if snapshot is not None else None
            ),
            snapshot_total_volume=(
                snapshot.snapshot_total_volume if snapshot is not None else None
            ),
            snapshot_completeness_score=(
                snapshot.snapshot_completeness_score if snapshot is not None else None
            ),
            snapshot_verification_valid=(
                snapshot.snapshot_verification_valid if snapshot is not None else False
            ),
            snapshot_created=(
                snapshot.snapshot_created if snapshot is not None else False
            ),
            snapshot_reused=(
                snapshot.snapshot_reused if snapshot is not None else False
            ),
            canonical_snapshot_row_match=(
                snapshot.canonical_snapshot_row_match if snapshot is not None else False
            ),
            canonical_snapshot_content_match=(
                snapshot.canonical_snapshot_content_match
                if snapshot is not None
                else False
            ),
            failure_code=failure_code,
            failure_detail=failure_detail,
        )

    def _calendar_rejection(
        self,
        trading_date: date,
        report_sha: str,
    ) -> SpecialSessionRecoveryRecord:
        target = _CalendarTarget(
            trading_date=trading_date,
            source_ids=(),
            report_sha256=report_sha,
            missing_at_start=False,
        )
        return self._record(
            target,
            source_status=SpecialSessionSourceStatus.NOT_ATTEMPTED,
            failure_code=SpecialSessionFailureCode.NOT_OFFICIAL_SPECIAL_SESSION,
            failure_detail=(
                "date is not classified as an official special session in the "
                "governed calendar report"
            ),
        )

    @classmethod
    def export(
        cls,
        report: SpecialSessionRecoveryReport,
        output: Path,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        recovery_json = output / "htr007b_special_session_recovery.json"
        recovery_csv = output / "htr007b_special_session_recovery.csv"
        recovery_md = output / "htr007b_special_session_recovery.md"
        validation_json = output / "htr007b_special_session_validation.json"
        validation_csv = output / "htr007b_special_session_validation.csv"
        ingestion_json = output / "htr007b_special_session_ingestion.json"
        ingestion_csv = output / "htr007b_special_session_ingestion.csv"

        payload = cls._report_payload(report, include_hash=True)
        recovery_json.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        recovery_rows = [cls._record_payload(item) for item in report.records]
        cls._write_csv(recovery_csv, recovery_rows)
        recovery_md.write_text(cls._markdown(report), encoding="utf-8")

        validation_rows = [cls._validation_payload(item) for item in report.records]
        validation_json.write_text(
            json.dumps(
                {
                    "contract_version": report.contract_version,
                    "records": validation_rows,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        cls._write_csv(validation_csv, validation_rows)

        ingestion_rows = [cls._ingestion_payload(item) for item in report.records]
        ingestion_json.write_text(
            json.dumps(
                {
                    "contract_version": report.contract_version,
                    "records": ingestion_rows,
                    "production_influence": report.production_influence,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        cls._write_csv(ingestion_csv, ingestion_rows)
        return (
            recovery_json,
            recovery_csv,
            recovery_md,
            validation_json,
            validation_csv,
            ingestion_json,
            ingestion_csv,
        )

    @classmethod
    def _report_payload(
        cls,
        report: SpecialSessionRecoveryReport,
        *,
        include_hash: bool,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_version": report.contract_version,
            "calendar_report_path": report.calendar_report_path,
            "calendar_report_sha256": report.calendar_report_sha256,
            "database_path": report.database_path,
            "complete": report.complete,
            "complete_count": report.complete_count,
            "reused_count": report.reused_count,
            "failed_count": report.failed_count,
            "production_influence": report.production_influence,
            "records": [cls._record_payload(item) for item in report.records],
        }
        if include_hash:
            payload["report_sha256"] = report.report_sha256
        return payload

    @classmethod
    def _record_payload(cls, item: SpecialSessionRecoveryRecord) -> dict[str, object]:
        return {
            **asdict(item),
            "trading_date": item.trading_date.isoformat(),
            "attempts": [cls._attempt_payload(value) for value in item.attempts],
            "validation_findings": [
                asdict(value) for value in item.validation_findings
            ],
            "source_status": item.source_status.value,
            "validation_status": item.validation_status.value,
            "ingestion_status": item.ingestion_status.value,
            "recovery_status": item.recovery_status.value,
            "failure_code": item.failure_code.value if item.failure_code else None,
            "snapshot_status": (
                item.snapshot_status.value if item.snapshot_status else None
            ),
            "snapshot_failure_code": (
                item.snapshot_failure_code.value if item.snapshot_failure_code else None
            ),
            "calendar_source_ids": list(item.calendar_source_ids),
            "redirect_chain": list(item.redirect_chain),
        }

    @staticmethod
    def _validation_payload(item: SpecialSessionRecoveryRecord) -> dict[str, object]:
        return {
            "trading_date": item.trading_date.isoformat(),
            "source_sha256": item.source_sha256,
            "extracted_sha256": item.extracted_sha256,
            "normalized_sha256": item.normalized_sha256,
            "parser_selected": item.parser_selected,
            "row_count": item.row_count,
            "unique_securities": item.unique_securities,
            "identity_resolved_rows": item.identity_resolved_rows,
            "validation_status": item.validation_status.value,
            "findings": [asdict(value) for value in item.validation_findings],
            "failure_code": item.failure_code.value if item.failure_code else None,
            "failure_detail": item.failure_detail,
        }

    @staticmethod
    def _ingestion_payload(item: SpecialSessionRecoveryRecord) -> dict[str, object]:
        return {
            "trading_date": item.trading_date.isoformat(),
            "database_rows": item.row_count,
            "inserted_rows": item.inserted_rows,
            "reused_rows": item.reused_rows,
            "lineage_rows": item.lineage_rows,
            "ingestion_status": item.ingestion_status.value,
            "recovery_status": item.recovery_status.value,
            "source_sha256": item.source_sha256,
            "normalized_path": item.normalized_path,
            "snapshot_path": item.snapshot_path,
            "snapshot_status": (
                item.snapshot_status.value if item.snapshot_status else None
            ),
            "snapshot_failure_code": (
                item.snapshot_failure_code.value if item.snapshot_failure_code else None
            ),
            "snapshot_content_sha256": item.snapshot_content_sha256,
            "snapshot_verification_valid": item.snapshot_verification_valid,
            "canonical_snapshot_content_match": (item.canonical_snapshot_content_match),
            "failure_code": item.failure_code.value if item.failure_code else None,
            "failure_detail": item.failure_detail,
        }

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
        fields = tuple(rows[0]) if rows else ("trading_date",)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        key: json.dumps(value, sort_keys=True)
                        if isinstance(value, (list, dict, tuple))
                        else value
                        for key, value in row.items()
                    }
                )

    @staticmethod
    def _markdown(report: SpecialSessionRecoveryReport) -> str:
        lines = [
            "# HTR-007B Special Session Candle Recovery",
            "",
            f"Complete: `{report.complete}`",
            f"Recovered: {report.complete_count}",
            f"Reused: {report.reused_count}",
            f"Failed: {report.failed_count}",
            f"Production influence: `{str(report.production_influence).lower()}`",
            f"Report SHA-256: `{report.report_sha256}`",
            "",
            "| Date | Source | Validation | Ingestion | Rows | Result | Failure |",
            "|:---|:---|:---|:---|---:|:---|:---|",
        ]
        for item in report.records:
            lines.append(
                f"| {item.trading_date} | {item.source_status.value} | "
                f"{item.validation_status.value} | {item.ingestion_status.value} | "
                f"{item.row_count} | {item.recovery_status.value} | "
                f"{item.failure_code.value if item.failure_code else ''} |"
            )
        return "\n".join(lines) + "\n"
