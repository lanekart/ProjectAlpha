from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.snapshots import (
    ImmutableMarketSnapshot,
    PointInTimeSnapshotEngine,
)

HTR007C_CONTRACT_VERSION = "HTR-007C-v1.0.0"
PRODUCTION_INFLUENCE = False


class SnapshotParityStatus(StrEnum):
    CREATED = "created"
    REUSED = "reused"
    VERIFIED = "verified"
    MISSING = "missing"
    INVALID = "invalid"
    CONFLICT = "conflict"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class SnapshotFailureCode(StrEnum):
    CALENDAR_REPORT_INVALID = "CALENDAR_REPORT_INVALID"
    NOT_OFFICIAL_SPECIAL_SESSION = "NOT_OFFICIAL_SPECIAL_SESSION"
    CANONICAL_SESSION_MISSING = "CANONICAL_SESSION_MISSING"
    SNAPSHOT_MISSING = "SNAPSHOT_MISSING"
    SNAPSHOT_READ_FAILED = "SNAPSHOT_READ_FAILED"
    SNAPSHOT_CHECKSUM_MISMATCH = "SNAPSHOT_CHECKSUM_MISMATCH"
    SNAPSHOT_DATE_MISMATCH = "SNAPSHOT_DATE_MISMATCH"
    SNAPSHOT_EXCHANGE_MISMATCH = "SNAPSHOT_EXCHANGE_MISMATCH"
    SNAPSHOT_SYMBOL_COUNT_MISMATCH = "SNAPSHOT_SYMBOL_COUNT_MISMATCH"
    SNAPSHOT_CANDLE_CONTENT_MISMATCH = "SNAPSHOT_CANDLE_CONTENT_MISMATCH"
    SNAPSHOT_METADATA_MISMATCH = "SNAPSHOT_METADATA_MISMATCH"
    IMMUTABLE_SNAPSHOT_CONFLICT = "IMMUTABLE_SNAPSHOT_CONFLICT"
    SNAPSHOT_BUILD_FAILED = "SNAPSHOT_BUILD_FAILED"
    SNAPSHOT_PERSIST_FAILED = "SNAPSHOT_PERSIST_FAILED"
    SNAPSHOT_VERIFY_FAILED = "SNAPSHOT_VERIFY_FAILED"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class SnapshotParityState(StrEnum):
    COMPLETE_SNAPSHOT_PARITY = "COMPLETE_SNAPSHOT_PARITY"
    INCOMPLETE_MISSING_SNAPSHOTS = "INCOMPLETE_MISSING_SNAPSHOTS"
    BLOCKED_INVALID_SNAPSHOTS = "BLOCKED_INVALID_SNAPSHOTS"
    BLOCKED_CONFLICTING_SNAPSHOTS = "BLOCKED_CONFLICTING_SNAPSHOTS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class SnapshotParityRecord:
    trading_date: date
    official_calendar_classification: str
    calendar_source_ids: tuple[str, ...]
    canonical_candles_available: bool
    canonical_row_count: int
    canonical_source_hashes: tuple[str, ...]
    expected_snapshot_path: str
    pre_run_snapshot_state: str
    post_run_snapshot_state: str
    snapshot_status: SnapshotParityStatus
    snapshot_failure_code: SnapshotFailureCode | None
    snapshot_failure_detail: str | None
    snapshot_content_sha256: str | None
    snapshot_file_sha256: str | None
    snapshot_symbol_count: int | None
    snapshot_total_volume: int | None
    snapshot_completeness_score: float | None
    snapshot_verification_valid: bool
    snapshot_created: bool
    snapshot_reused: bool
    canonical_snapshot_row_match: bool
    canonical_snapshot_content_match: bool

    @property
    def valid(self) -> bool:
        return (
            self.snapshot_verification_valid
            and self.canonical_snapshot_row_match
            and self.canonical_snapshot_content_match
            and self.snapshot_status
            in {
                SnapshotParityStatus.CREATED,
                SnapshotParityStatus.REUSED,
                SnapshotParityStatus.VERIFIED,
            }
        )


@dataclass(frozen=True, slots=True)
class SnapshotParitySummary:
    canonical_observed_dates: int
    snapshot_files_expected: int
    snapshot_files_present: int
    missing_snapshot_dates: tuple[date, ...]
    invalid_snapshot_dates: tuple[date, ...]
    orphan_snapshot_dates: tuple[date, ...]
    symbol_count_mismatch_dates: tuple[date, ...]
    content_mismatch_dates: tuple[date, ...]
    official_special_session_snapshots_expected: int
    official_special_session_snapshots_present: int
    official_special_session_snapshots_valid: int
    final_parity_state: SnapshotParityState


@dataclass(frozen=True, slots=True)
class SnapshotParityReport:
    database_path: str
    snapshot_root: str
    calendar_report_path: str
    calendar_report_sha256: str
    start_date: date
    end_date: date
    verify_only: bool
    records: tuple[SnapshotParityRecord, ...]
    summary: SnapshotParitySummary
    production_influence: bool
    report_sha256: str
    contract_version: str = HTR007C_CONTRACT_VERSION

    @property
    def complete(self) -> bool:
        return (
            self.summary.final_parity_state
            is SnapshotParityState.COMPLETE_SNAPSHOT_PARITY
            and all(record.valid for record in self.records)
        )


@dataclass(frozen=True, slots=True)
class _CalendarSpecialSession:
    trading_date: date
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CalendarEvidence:
    report_sha256: str
    special_sessions: Mapping[date, _CalendarSpecialSession]


@dataclass(frozen=True, slots=True)
class _SnapshotValues:
    content_sha256: str
    file_sha256: str
    symbol_count: int
    total_volume: int
    completeness_score: float


class SpecialSessionSnapshotParityEngine:
    """Audit and repair immutable snapshots for governed special sessions."""

    def __init__(
        self,
        canonical: CanonicalPointInTimeWarehouse,
        snapshots: PointInTimeSnapshotEngine,
        *,
        exchange: str = "nse",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.canonical = canonical
        self.snapshots = snapshots
        self.exchange = exchange.lower()
        self.clock = clock or (lambda: datetime.now(UTC))

    def run(
        self,
        calendar_report: Path,
        *,
        start_date: date,
        end_date: date,
        selected_dates: tuple[date, ...] = (),
        verify_only: bool = False,
        progress: Callable[[int, int, date], None] | None = None,
    ) -> SnapshotParityReport:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        calendar = self._load_calendar(calendar_report)
        specials = calendar.special_sessions
        requested = tuple(sorted(set(selected_dates)))
        target_dates = (
            requested
            if requested
            else tuple(
                item for item in sorted(specials) if start_date <= item <= end_date
            )
        )
        records: list[SnapshotParityRecord] = []
        for index, trading_date in enumerate(target_dates, start=1):
            special = specials.get(trading_date)
            if special is None:
                records.append(self._not_applicable(trading_date))
            else:
                records.append(
                    self.ensure_snapshot(
                        trading_date,
                        source_ids=special.source_ids,
                        verify_only=verify_only,
                    )
                )
            if progress is not None:
                progress(index, len(target_dates), trading_date)

        summary = self.audit_window(
            start_date,
            end_date,
            official_special_dates=frozenset(specials),
        )
        ordered = tuple(sorted(records, key=lambda item: item.trading_date))
        provisional = SnapshotParityReport(
            database_path=str(self.canonical.database_path),
            snapshot_root=str(self.snapshots.snapshot_root),
            calendar_report_path=str(calendar_report),
            calendar_report_sha256=calendar.report_sha256,
            start_date=start_date,
            end_date=end_date,
            verify_only=verify_only,
            records=ordered,
            summary=summary,
            production_influence=PRODUCTION_INFLUENCE,
            report_sha256="",
        )
        digest = hashlib.sha256(
            json.dumps(
                self._report_payload(provisional, include_hash=False),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return replace(provisional, report_sha256=digest)

    def ensure_snapshot(
        self,
        trading_date: date,
        *,
        source_ids: tuple[str, ...] = (),
        verify_only: bool = False,
    ) -> SnapshotParityRecord:
        canonical = self.canonical.snapshot(trading_date, exchange=self.exchange)
        path = self.snapshots.path_for(trading_date, exchange=self.exchange)
        source_hashes = self._source_hashes(trading_date)
        if not canonical.candles:
            return self._record(
                trading_date,
                source_ids=source_ids,
                canonical_row_count=0,
                source_hashes=source_hashes,
                path=path,
                pre_state="missing" if not path.exists() else "present",
                post_state="unchanged",
                status=SnapshotParityStatus.FAILED,
                failure_code=SnapshotFailureCode.CANONICAL_SESSION_MISSING,
                failure_detail="canonical warehouse has no candles for session",
            )
        if path.exists():
            status = (
                SnapshotParityStatus.VERIFIED
                if verify_only
                else SnapshotParityStatus.REUSED
            )
            return self._inspect_existing(
                trading_date,
                canonical=canonical,
                source_ids=source_ids,
                source_hashes=source_hashes,
                status=status,
                pre_state="present",
            )
        if verify_only:
            return self._record(
                trading_date,
                source_ids=source_ids,
                canonical_row_count=canonical.symbol_count,
                source_hashes=source_hashes,
                path=path,
                pre_state="missing",
                post_state="missing",
                status=SnapshotParityStatus.MISSING,
                failure_code=SnapshotFailureCode.SNAPSHOT_MISSING,
                failure_detail="immutable snapshot is absent in verification-only mode",
            )
        try:
            snapshot = self.snapshots.build(
                trading_date,
                exchange=self.exchange,
                generated_at=self.clock(),
            )
        except Exception as exc:
            return self._record(
                trading_date,
                source_ids=source_ids,
                canonical_row_count=canonical.symbol_count,
                source_hashes=source_hashes,
                path=path,
                pre_state="missing",
                post_state="missing",
                status=SnapshotParityStatus.FAILED,
                failure_code=SnapshotFailureCode.SNAPSHOT_BUILD_FAILED,
                failure_detail=f"{type(exc).__name__}: {exc}",
            )
        try:
            self.snapshots.persist(snapshot)
        except FileExistsError as exc:
            return self._record(
                trading_date,
                source_ids=source_ids,
                canonical_row_count=canonical.symbol_count,
                source_hashes=source_hashes,
                path=path,
                pre_state="missing",
                post_state="conflict",
                status=SnapshotParityStatus.CONFLICT,
                failure_code=SnapshotFailureCode.IMMUTABLE_SNAPSHOT_CONFLICT,
                failure_detail=str(exc),
            )
        except OSError as exc:
            return self._record(
                trading_date,
                source_ids=source_ids,
                canonical_row_count=canonical.symbol_count,
                source_hashes=source_hashes,
                path=path,
                pre_state="missing",
                post_state="missing",
                status=SnapshotParityStatus.FAILED,
                failure_code=SnapshotFailureCode.SNAPSHOT_PERSIST_FAILED,
                failure_detail=f"{type(exc).__name__}: {exc}",
            )
        return self._inspect_existing(
            trading_date,
            canonical=canonical,
            source_ids=source_ids,
            source_hashes=source_hashes,
            status=SnapshotParityStatus.CREATED,
            pre_state="missing",
        )

    def audit_window(
        self,
        start_date: date,
        end_date: date,
        *,
        official_special_dates: frozenset[date],
    ) -> SnapshotParitySummary:
        canonical_dates = self._canonical_dates(start_date, end_date)
        canonical_set = frozenset(canonical_dates)
        snapshot_dates = self._snapshot_dates(start_date, end_date)
        missing = tuple(item for item in canonical_dates if item not in snapshot_dates)
        orphan = tuple(sorted(snapshot_dates - canonical_set))
        invalid: list[date] = []
        symbol_mismatch: list[date] = []
        content_mismatch: list[date] = []
        valid_dates: set[date] = set()
        for trading_date in canonical_dates:
            if trading_date in missing:
                continue
            canonical = self.canonical.snapshot(
                trading_date,
                exchange=self.exchange,
            )
            inspected = self._inspect_existing(
                trading_date,
                canonical=canonical,
                source_ids=(),
                source_hashes=(),
                status=SnapshotParityStatus.VERIFIED,
                pre_state="present",
            )
            if inspected.valid:
                valid_dates.add(trading_date)
            else:
                invalid.append(trading_date)
            if not inspected.canonical_snapshot_row_match:
                symbol_mismatch.append(trading_date)
            if not inspected.canonical_snapshot_content_match:
                content_mismatch.append(trading_date)
        special_in_window = frozenset(
            item for item in official_special_dates if start_date <= item <= end_date
        )
        special_present = special_in_window & snapshot_dates & canonical_set
        special_valid = special_in_window & valid_dates
        if not canonical_dates:
            state = SnapshotParityState.INSUFFICIENT_EVIDENCE
        elif content_mismatch or orphan:
            state = SnapshotParityState.BLOCKED_CONFLICTING_SNAPSHOTS
        elif invalid:
            state = SnapshotParityState.BLOCKED_INVALID_SNAPSHOTS
        elif missing:
            state = SnapshotParityState.INCOMPLETE_MISSING_SNAPSHOTS
        else:
            state = SnapshotParityState.COMPLETE_SNAPSHOT_PARITY
        return SnapshotParitySummary(
            canonical_observed_dates=len(canonical_dates),
            snapshot_files_expected=len(canonical_dates),
            snapshot_files_present=len(canonical_dates) - len(missing),
            missing_snapshot_dates=missing,
            invalid_snapshot_dates=tuple(invalid),
            orphan_snapshot_dates=orphan,
            symbol_count_mismatch_dates=tuple(symbol_mismatch),
            content_mismatch_dates=tuple(content_mismatch),
            official_special_session_snapshots_expected=len(special_in_window),
            official_special_session_snapshots_present=len(special_present),
            official_special_session_snapshots_valid=len(special_valid),
            final_parity_state=state,
        )

    def _inspect_existing(
        self,
        trading_date: date,
        *,
        canonical: object,
        source_ids: tuple[str, ...],
        source_hashes: tuple[str, ...],
        status: SnapshotParityStatus,
        pre_state: str,
    ) -> SnapshotParityRecord:
        from alpha.historical_truth.canonical import MarketSnapshot

        if not isinstance(canonical, MarketSnapshot):
            raise TypeError("canonical market snapshot is required")
        path = self.snapshots.path_for(trading_date, exchange=self.exchange)
        try:
            raw = path.read_bytes()
            snapshot = self.snapshots.load(trading_date, exchange=self.exchange)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._record(
                trading_date,
                source_ids=source_ids,
                canonical_row_count=canonical.symbol_count,
                source_hashes=source_hashes,
                path=path,
                pre_state=pre_state,
                post_state="invalid",
                status=SnapshotParityStatus.INVALID,
                failure_code=SnapshotFailureCode.SNAPSHOT_READ_FAILED,
                failure_detail=f"{type(exc).__name__}: {exc}",
            )
        verification = self.snapshots.verify(snapshot)
        values = self._snapshot_values(snapshot, raw)
        if not verification.valid:
            return self._record(
                trading_date,
                source_ids=source_ids,
                canonical_row_count=canonical.symbol_count,
                source_hashes=source_hashes,
                path=path,
                pre_state=pre_state,
                post_state="invalid",
                status=SnapshotParityStatus.INVALID,
                failure_code=SnapshotFailureCode.SNAPSHOT_CHECKSUM_MISMATCH,
                failure_detail=verification.reason,
                snapshot_values=values,
            )
        if snapshot.metadata.trading_date != trading_date or any(
            candle.trading_date != trading_date for candle in snapshot.candles
        ):
            return self._invalid_snapshot(
                trading_date,
                canonical=canonical,
                source_ids=source_ids,
                source_hashes=source_hashes,
                path=path,
                pre_state=pre_state,
                code=SnapshotFailureCode.SNAPSHOT_DATE_MISMATCH,
                detail="snapshot metadata or candles use a different trading date",
                values=values,
            )
        if snapshot.metadata.exchange.lower() != self.exchange or any(
            candle.exchange.lower() != self.exchange for candle in snapshot.candles
        ):
            return self._invalid_snapshot(
                trading_date,
                canonical=canonical,
                source_ids=source_ids,
                source_hashes=source_hashes,
                path=path,
                pre_state=pre_state,
                code=SnapshotFailureCode.SNAPSHOT_EXCHANGE_MISMATCH,
                detail="snapshot metadata or candles use a different exchange",
                values=values,
            )
        row_match = (
            snapshot.metadata.symbol_count == canonical.symbol_count
            and len(snapshot.candles) == canonical.symbol_count
        )
        if not row_match:
            return self._record(
                trading_date,
                source_ids=source_ids,
                canonical_row_count=canonical.symbol_count,
                source_hashes=source_hashes,
                path=path,
                pre_state=pre_state,
                post_state="conflict",
                status=SnapshotParityStatus.CONFLICT,
                failure_code=SnapshotFailureCode.SNAPSHOT_SYMBOL_COUNT_MISMATCH,
                failure_detail="snapshot symbol count differs from canonical rows",
                row_match=False,
                content_match=False,
                snapshot_values=values,
            )
        if snapshot.candles != canonical.candles:
            return self._record(
                trading_date,
                source_ids=source_ids,
                canonical_row_count=canonical.symbol_count,
                source_hashes=source_hashes,
                path=path,
                pre_state=pre_state,
                post_state="conflict",
                status=SnapshotParityStatus.CONFLICT,
                failure_code=(SnapshotFailureCode.SNAPSHOT_CANDLE_CONTENT_MISMATCH),
                failure_detail="snapshot candles differ from canonical candles",
                row_match=True,
                content_match=False,
                snapshot_values=values,
            )
        expected_score = self._completeness_score(snapshot)
        metadata_valid = (
            snapshot.metadata.snapshot_version
            == PointInTimeSnapshotEngine.SNAPSHOT_VERSION
            and snapshot.metadata.total_volume == canonical.total_volume
            and snapshot.metadata.availability.candles
            and snapshot.metadata.completeness_score == expected_score
            and Path(snapshot.metadata.source_database).resolve()
            == self.canonical.database_path.resolve()
        )
        if not metadata_valid:
            return self._record(
                trading_date,
                source_ids=source_ids,
                canonical_row_count=canonical.symbol_count,
                source_hashes=source_hashes,
                path=path,
                pre_state=pre_state,
                post_state="invalid",
                status=SnapshotParityStatus.INVALID,
                failure_code=SnapshotFailureCode.SNAPSHOT_METADATA_MISMATCH,
                failure_detail="snapshot metadata differs from governed values",
                row_match=True,
                content_match=True,
                snapshot_values=values,
            )
        return self._record(
            trading_date,
            source_ids=source_ids,
            canonical_row_count=canonical.symbol_count,
            source_hashes=source_hashes,
            path=path,
            pre_state=pre_state,
            post_state="valid",
            status=status,
            verification_valid=True,
            row_match=True,
            content_match=True,
            snapshot_values=values,
        )

    def _invalid_snapshot(
        self,
        trading_date: date,
        *,
        canonical: object,
        source_ids: tuple[str, ...],
        source_hashes: tuple[str, ...],
        path: Path,
        pre_state: str,
        code: SnapshotFailureCode,
        detail: str,
        values: _SnapshotValues,
    ) -> SnapshotParityRecord:
        from alpha.historical_truth.canonical import MarketSnapshot

        assert isinstance(canonical, MarketSnapshot)
        return self._record(
            trading_date,
            source_ids=source_ids,
            canonical_row_count=canonical.symbol_count,
            source_hashes=source_hashes,
            path=path,
            pre_state=pre_state,
            post_state="invalid",
            status=SnapshotParityStatus.INVALID,
            failure_code=code,
            failure_detail=detail,
            snapshot_values=values,
        )

    @staticmethod
    def _snapshot_values(
        snapshot: ImmutableMarketSnapshot,
        raw: bytes,
    ) -> _SnapshotValues:
        return _SnapshotValues(
            content_sha256=snapshot.content_sha256,
            file_sha256=hashlib.sha256(raw).hexdigest(),
            symbol_count=snapshot.metadata.symbol_count,
            total_volume=snapshot.metadata.total_volume,
            completeness_score=snapshot.metadata.completeness_score,
        )

    @staticmethod
    def _completeness_score(snapshot: ImmutableMarketSnapshot) -> float:
        availability = snapshot.metadata.availability
        values = (
            availability.candles,
            availability.identity,
            availability.corporate_actions,
            availability.delivery,
            availability.indices,
            availability.vix,
        )
        return round(sum(values) / len(values), 6)

    def _record(
        self,
        trading_date: date,
        *,
        source_ids: tuple[str, ...],
        canonical_row_count: int,
        source_hashes: tuple[str, ...],
        path: Path,
        pre_state: str,
        post_state: str,
        status: SnapshotParityStatus,
        failure_code: SnapshotFailureCode | None = None,
        failure_detail: str | None = None,
        snapshot_values: _SnapshotValues | None = None,
        verification_valid: bool = False,
        row_match: bool = False,
        content_match: bool = False,
    ) -> SnapshotParityRecord:
        return SnapshotParityRecord(
            trading_date=trading_date,
            official_calendar_classification="special_session",
            calendar_source_ids=source_ids,
            canonical_candles_available=canonical_row_count > 0,
            canonical_row_count=canonical_row_count,
            canonical_source_hashes=source_hashes,
            expected_snapshot_path=str(path),
            pre_run_snapshot_state=pre_state,
            post_run_snapshot_state=post_state,
            snapshot_status=status,
            snapshot_failure_code=failure_code,
            snapshot_failure_detail=failure_detail,
            snapshot_content_sha256=(
                snapshot_values.content_sha256 if snapshot_values else None
            ),
            snapshot_file_sha256=(
                snapshot_values.file_sha256 if snapshot_values else None
            ),
            snapshot_symbol_count=(
                snapshot_values.symbol_count if snapshot_values else None
            ),
            snapshot_total_volume=(
                snapshot_values.total_volume if snapshot_values else None
            ),
            snapshot_completeness_score=(
                snapshot_values.completeness_score if snapshot_values else None
            ),
            snapshot_verification_valid=verification_valid,
            snapshot_created=status is SnapshotParityStatus.CREATED,
            snapshot_reused=status
            in {SnapshotParityStatus.REUSED, SnapshotParityStatus.VERIFIED},
            canonical_snapshot_row_match=row_match,
            canonical_snapshot_content_match=content_match,
        )

    def _not_applicable(self, trading_date: date) -> SnapshotParityRecord:
        path = self.snapshots.path_for(trading_date, exchange=self.exchange)
        return SnapshotParityRecord(
            trading_date=trading_date,
            official_calendar_classification="not_special_session",
            calendar_source_ids=(),
            canonical_candles_available=False,
            canonical_row_count=0,
            canonical_source_hashes=(),
            expected_snapshot_path=str(path),
            pre_run_snapshot_state="not_evaluated",
            post_run_snapshot_state="unchanged",
            snapshot_status=SnapshotParityStatus.NOT_APPLICABLE,
            snapshot_failure_code=(SnapshotFailureCode.NOT_OFFICIAL_SPECIAL_SESSION),
            snapshot_failure_detail=(
                "date is not classified as an official special session"
            ),
            snapshot_content_sha256=None,
            snapshot_file_sha256=None,
            snapshot_symbol_count=None,
            snapshot_total_volume=None,
            snapshot_completeness_score=None,
            snapshot_verification_valid=False,
            snapshot_created=False,
            snapshot_reused=False,
            canonical_snapshot_row_match=False,
            canonical_snapshot_content_match=False,
        )

    def _canonical_dates(
        self,
        start_date: date,
        end_date: date,
    ) -> tuple[date, ...]:
        self.canonical.initialise()
        with self.canonical._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT trading_date
                FROM daily_candle
                WHERE exchange = ? AND trading_date BETWEEN ? AND ?
                ORDER BY trading_date
                """,
                [self.exchange, start_date, end_date],
            ).fetchall()
        return tuple(row[0] for row in rows)

    def _source_hashes(self, trading_date: date) -> tuple[str, ...]:
        self.canonical.initialise()
        with self.canonical._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT source_sha256
                FROM daily_candle
                WHERE exchange = ? AND trading_date = ?
                  AND source_sha256 IS NOT NULL
                ORDER BY source_sha256
                """,
                [self.exchange, trading_date],
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def _snapshot_dates(
        self,
        start_date: date,
        end_date: date,
    ) -> frozenset[date]:
        root = self.snapshots.snapshot_root / self.exchange
        values: set[date] = set()
        for path in root.glob("*/*.json"):
            try:
                value = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if start_date <= value <= end_date:
                values.add(value)
        return frozenset(values)

    @staticmethod
    def _load_calendar(path: Path) -> _CalendarEvidence:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid certified calendar report: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("records"), list
        ):
            raise ValueError("certified calendar report has unsupported structure")
        expected_hash = payload.get("report_sha256")
        without_hash = dict(payload)
        without_hash.pop("report_sha256", None)
        observed_hash = hashlib.sha256(
            json.dumps(
                without_hash,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if expected_hash != observed_hash:
            raise ValueError("certified calendar report checksum verification failed")
        if payload.get("certification_state") not in {
            "certified",
            "complete_official_evidence",
        }:
            raise ValueError("calendar report is not certified")
        specials: dict[date, _CalendarSpecialSession] = {}
        for raw in payload["records"]:
            if not isinstance(raw, dict) or raw.get("classification") != (
                "special_session"
            ):
                continue
            trading_date = date.fromisoformat(str(raw["trading_date"]))
            source_ids = tuple(str(item) for item in raw.get("source_ids", []))
            if not source_ids:
                raise ValueError(
                    "special-session calendar record has no official source lineage"
                )
            specials[trading_date] = _CalendarSpecialSession(
                trading_date=trading_date,
                source_ids=source_ids,
            )
        return _CalendarEvidence(
            report_sha256=str(expected_hash),
            special_sessions=specials,
        )

    @classmethod
    def export(
        cls,
        report: SnapshotParityReport,
        output: Path,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        primary_json = output / "htr007c_special_session_snapshot_parity.json"
        primary_csv = output / "htr007c_special_session_snapshot_parity.csv"
        primary_md = output / "htr007c_special_session_snapshot_parity.md"
        missing_json = output / "htr007c_missing_snapshots.json"
        missing_csv = output / "htr007c_missing_snapshots.csv"
        verification_json = output / "htr007c_snapshot_verification.json"
        verification_csv = output / "htr007c_snapshot_verification.csv"
        payload = cls._report_payload(report, include_hash=True)
        primary_json.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rows = [cls._record_payload(item) for item in report.records]
        cls._write_csv(primary_csv, rows)
        primary_md.write_text(cls._markdown(report), encoding="utf-8")
        missing_rows = [
            cls._record_payload(item)
            for item in report.records
            if item.pre_run_snapshot_state == "missing"
        ]
        missing_payload = {
            "contract_version": report.contract_version,
            "records": missing_rows,
            "post_run_missing_dates": [
                item.isoformat() for item in report.summary.missing_snapshot_dates
            ],
        }
        missing_json.write_text(
            json.dumps(missing_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        cls._write_csv(missing_csv, missing_rows)
        verification_payload = {
            "contract_version": report.contract_version,
            "final_parity_state": report.summary.final_parity_state.value,
            "records": rows,
        }
        verification_json.write_text(
            json.dumps(verification_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        cls._write_csv(verification_csv, rows)
        return (
            primary_json,
            primary_csv,
            primary_md,
            missing_json,
            missing_csv,
            verification_json,
            verification_csv,
        )

    @classmethod
    def _report_payload(
        cls,
        report: SnapshotParityReport,
        *,
        include_hash: bool,
    ) -> dict[str, object]:
        summary = asdict(report.summary)
        for key in (
            "missing_snapshot_dates",
            "invalid_snapshot_dates",
            "orphan_snapshot_dates",
            "symbol_count_mismatch_dates",
            "content_mismatch_dates",
        ):
            summary[key] = [item.isoformat() for item in summary[key]]
        summary["final_parity_state"] = report.summary.final_parity_state.value
        payload: dict[str, object] = {
            "contract_version": report.contract_version,
            "database_path": report.database_path,
            "snapshot_root": report.snapshot_root,
            "calendar_report_path": report.calendar_report_path,
            "calendar_report_sha256": report.calendar_report_sha256,
            "start_date": report.start_date.isoformat(),
            "end_date": report.end_date.isoformat(),
            "verify_only": report.verify_only,
            "complete": report.complete,
            "records": [cls._record_payload(item) for item in report.records],
            "summary": summary,
            "production_influence": report.production_influence,
        }
        if include_hash:
            payload["report_sha256"] = report.report_sha256
        return payload

    @staticmethod
    def _record_payload(record: SnapshotParityRecord) -> dict[str, object]:
        return {
            **asdict(record),
            "trading_date": record.trading_date.isoformat(),
            "calendar_source_ids": list(record.calendar_source_ids),
            "canonical_source_hashes": list(record.canonical_source_hashes),
            "snapshot_status": record.snapshot_status.value,
            "snapshot_failure_code": (
                record.snapshot_failure_code.value
                if record.snapshot_failure_code
                else None
            ),
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
    def _markdown(report: SnapshotParityReport) -> str:
        summary = report.summary
        lines = [
            "# HTR-007C Special-Session Snapshot Parity",
            "",
            f"Parity state: `{summary.final_parity_state.value}`",
            f"Canonical dates: {summary.canonical_observed_dates}",
            f"Snapshots present: {summary.snapshot_files_present}",
            f"Missing snapshots: {len(summary.missing_snapshot_dates)}",
            f"Invalid snapshots: {len(summary.invalid_snapshot_dates)}",
            f"Orphan snapshots: {len(summary.orphan_snapshot_dates)}",
            f"Production influence: `{str(report.production_influence).lower()}`",
            "",
            "| Date | Pre-state | Post-state | Status | Rows | Checksum | Failure |",
            "|:---|:---|:---|:---|---:|:---|:---|",
        ]
        for item in report.records:
            failure = (
                item.snapshot_failure_code.value if item.snapshot_failure_code else ""
            )
            lines.append(
                f"| {item.trading_date} | {item.pre_run_snapshot_state} | "
                f"{item.post_run_snapshot_state} | {item.snapshot_status.value} | "
                f"{item.canonical_row_count} | "
                f"{item.snapshot_content_sha256 or ''} | "
                f"{failure} |"
            )
        return "\n".join(lines) + "\n"
