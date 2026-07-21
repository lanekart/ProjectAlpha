from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.models import ArchiveRequest, ManifestRecord, ManifestStatus
from alpha.historical_truth.population import (
    HistoricalPopulationEngine,
    PopulationStatus,
)
from alpha.historical_truth.resumable import HistoricalTruthWarehouse
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine

HTR007_PILOT_CONTRACT_VERSION = "HTR-007-pilot-v1.0.0"
UDIFF_START_DATE = date(2024, 7, 8)
DEFAULT_CROSS_ERA_DATES = (
    date(2016, 1, 4),
    date(2020, 1, 2),
    date(2023, 1, 2),
    date(2026, 1, 2),
)


class BackfillPilotStatus(StrEnum):
    """Stable result states for one cross-era acquisition probe."""

    COMPLETE = "complete"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class BackfillPilotRecord:
    """Deterministic evidence for one official NSE bhavcopy date."""

    trading_date: date
    source_url: str
    raw_relative_path: str
    expected_schema: str
    status: BackfillPilotStatus
    manifest_status: str
    archive_sha256: str | None
    byte_size: int | None
    archive_member: str | None
    detected_schema: str | None
    archive_row_count: int
    validation_passed: bool
    population_status: str | None
    ingested_rows: int
    snapshot_relative_path: str | None
    snapshot_valid: bool
    snapshot_symbol_count: int
    checksum_drift: bool
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["trading_date"] = self.trading_date.isoformat()
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True, slots=True)
class BackfillPilotReport:
    """Immutable cross-era acquisition proof without embedding wall-clock fields."""

    records: tuple[BackfillPilotRecord, ...]
    contract_version: str = HTR007_PILOT_CONTRACT_VERSION
    official_source: str = "NSE"
    live_downloads_executed_by_ci: bool = False

    def __post_init__(self) -> None:
        dates = tuple(record.trading_date for record in self.records)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("pilot dates must be sorted and unique")
        if self.contract_version != HTR007_PILOT_CONTRACT_VERSION:
            raise ValueError("unsupported HTR-007 pilot contract")
        if self.live_downloads_executed_by_ci:
            raise ValueError("HTR-007 CI must not execute live archive downloads")

    @property
    def complete(self) -> bool:
        return bool(self.records) and all(
            record.status is BackfillPilotStatus.COMPLETE for record in self.records
        )

    @property
    def schemas_observed(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    record.detected_schema
                    for record in self.records
                    if record.detected_schema is not None
                }
            )
        )

    @property
    def report_sha256(self) -> str:
        encoded = json.dumps(
            self.as_dict(include_digest=False),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "records": [record.as_dict() for record in self.records],
            "complete": self.complete,
            "schemas_observed": list(self.schemas_observed),
            "contract_version": self.contract_version,
            "official_source": self.official_source,
            "live_downloads_executed_by_ci": self.live_downloads_executed_by_ci,
        }
        if include_digest:
            payload["report_sha256"] = self.report_sha256
        return payload


@dataclass(frozen=True, slots=True)
class _ArchiveInspection:
    member_name: str
    schema: str
    row_count: int


class HistoricalBackfillPilot:
    """Orchestrate representative official archives through the governed warehouse."""

    def __init__(
        self,
        archive: HistoricalTruthWarehouse,
        canonical: CanonicalPointInTimeWarehouse,
        snapshots: PointInTimeSnapshotEngine,
    ) -> None:
        self.archive = archive
        self.canonical = canonical
        self.snapshots = snapshots
        self.population = HistoricalPopulationEngine(archive, canonical, snapshots)

    def run(
        self,
        dates: tuple[date, ...] = DEFAULT_CROSS_ERA_DATES,
    ) -> BackfillPilotReport:
        ordered_dates = tuple(sorted(set(dates)))
        if not ordered_dates:
            raise ValueError("pilot requires at least one representative date")
        records = tuple(self._run_one(item) for item in ordered_dates)
        return BackfillPilotReport(records=records)

    def _run_one(self, trading_date: date) -> BackfillPilotRecord:
        request = self._request_for(trading_date)
        expected_schema = "udiff" if trading_date >= UDIFF_START_DATE else "legacy"
        previous = self._latest_manifest(request)
        fetched = self.archive.fetch(request)
        checksum_drift_before_status = bool(
            previous is not None
            and previous.sha256 is not None
            and fetched.sha256 is not None
            and previous.sha256 != fetched.sha256
        ) or fetched.error in {
            "immutable archive checksum drift detected",
            "refetched archive checksum differs from trusted manifest",
        }
        if fetched.status is ManifestStatus.UNAVAILABLE:
            return self._failure_record(
                request,
                expected_schema,
                fetched,
                BackfillPilotStatus.UNAVAILABLE,
                fetched.error,
                checksum_drift=checksum_drift_before_status,
            )
        if fetched.status not in {ManifestStatus.DOWNLOADED, ManifestStatus.VALIDATED}:
            return self._failure_record(
                request,
                expected_schema,
                fetched,
                BackfillPilotStatus.FAILED,
                fetched.error,
                checksum_drift=checksum_drift_before_status,
            )

        checksum_drift = bool(
            previous is not None
            and previous.sha256 is not None
            and fetched.sha256 is not None
            and previous.sha256 != fetched.sha256
        )
        if checksum_drift:
            return self._failure_record(
                request,
                expected_schema,
                fetched,
                BackfillPilotStatus.FAILED,
                "immutable archive checksum drift detected",
                checksum_drift=True,
            )

        raw_path = self.archive.raw_root / request.relative_path
        try:
            inspection = self._inspect_archive(raw_path)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return self._failure_record(
                request,
                expected_schema,
                fetched,
                BackfillPilotStatus.FAILED,
                f"{type(exc).__name__}: {exc}",
            )
        if inspection.schema != expected_schema:
            return self._failure_record(
                request,
                expected_schema,
                fetched,
                BackfillPilotStatus.FAILED,
                (
                    "archive schema does not match the official format era: "
                    f"expected={expected_schema}; observed={inspection.schema}"
                ),
                inspection=inspection,
            )

        population = self.population.populate((request,))[0]
        snapshot_valid = False
        snapshot_symbol_count = 0
        snapshot_relative_path: str | None = None
        if population.snapshot_path is not None:
            snapshot_path = Path(population.snapshot_path)
            snapshot_relative_path = self._relative_to_root(snapshot_path)
            snapshot = self.snapshots.load(trading_date, exchange=request.exchange)
            verification = self.snapshots.verify(snapshot)
            snapshot_valid = verification.valid
            snapshot_symbol_count = snapshot.metadata.symbol_count

        population_success = population.status in {
            PopulationStatus.COMPLETE,
            PopulationStatus.PARTIAL,
        } or (
            population.status is PopulationStatus.SKIPPED
            and population.validated
            and population.snapshot_path is not None
        )
        validation_passed = population.validated and population.error is None
        complete = population_success and validation_passed and snapshot_valid
        error = population.error
        if not snapshot_valid and error is None:
            error = "point-in-time snapshot verification failed"
        return BackfillPilotRecord(
            trading_date=trading_date,
            source_url=request.source_url,
            raw_relative_path=str(request.relative_path),
            expected_schema=expected_schema,
            status=(
                BackfillPilotStatus.COMPLETE if complete else BackfillPilotStatus.FAILED
            ),
            manifest_status=fetched.status.value,
            archive_sha256=fetched.sha256,
            byte_size=fetched.byte_size,
            archive_member=inspection.member_name,
            detected_schema=inspection.schema,
            archive_row_count=inspection.row_count,
            validation_passed=validation_passed,
            population_status=(
                "available" if population_success else population.status.value
            ),
            ingested_rows=population.ingested_rows,
            snapshot_relative_path=snapshot_relative_path,
            snapshot_valid=snapshot_valid,
            snapshot_symbol_count=snapshot_symbol_count,
            checksum_drift=False,
            error=error,
        )

    def _inspect_archive(self, archive_path: Path) -> _ArchiveInspection:
        with zipfile.ZipFile(archive_path) as archive:
            members = tuple(
                member
                for member in archive.infolist()
                if not member.is_dir() and member.filename.lower().endswith(".csv")
            )
            if len(members) != 1:
                raise ValueError(
                    "expected exactly one CSV member in official bhavcopy archive"
                )
            member = members[0]
            path = PurePosixPath(member.filename)
            if path.name != member.filename or ".." in path.parts:
                raise ValueError("archive CSV member must be a safe top-level file")
            with archive.open(member) as raw:
                with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
                    reader = csv.DictReader(text)
                    columns = frozenset(reader.fieldnames or ())
                    schema = self.archive.detect_bhavcopy_schema(columns)
                    if schema is None:
                        raise ValueError("unsupported bhavcopy schema")
                    row_count = sum(1 for _ in reader)
            if row_count < 1:
                raise ValueError("official bhavcopy contains no data rows")
            return _ArchiveInspection(
                member_name=member.filename,
                schema=schema,
                row_count=row_count,
            )

    def _request_for(self, trading_date: date) -> ArchiveRequest:
        requests = self.archive.plan_nse_bhavcopies(trading_date, trading_date)
        if len(requests) != 1:
            raise ValueError(
                f"representative date is not a planned NSE weekday: {trading_date}"
            )
        return requests[0]

    def _latest_manifest(self, request: ArchiveRequest) -> ManifestRecord | None:
        for record in self.archive.records():
            if (
                record.exchange == request.exchange
                and record.dataset is request.dataset
                and record.trading_date == request.trading_date
            ):
                return record
        return None

    def _failure_record(
        self,
        request: ArchiveRequest,
        expected_schema: str,
        manifest: ManifestRecord,
        status: BackfillPilotStatus,
        error: str | None,
        *,
        checksum_drift: bool = False,
        inspection: _ArchiveInspection | None = None,
    ) -> BackfillPilotRecord:
        return BackfillPilotRecord(
            trading_date=request.trading_date,
            source_url=request.source_url,
            raw_relative_path=str(request.relative_path),
            expected_schema=expected_schema,
            status=status,
            manifest_status=manifest.status.value,
            archive_sha256=manifest.sha256,
            byte_size=manifest.byte_size,
            archive_member=(inspection.member_name if inspection is not None else None),
            detected_schema=(inspection.schema if inspection is not None else None),
            archive_row_count=(inspection.row_count if inspection is not None else 0),
            validation_passed=False,
            population_status=None,
            ingested_rows=0,
            snapshot_relative_path=None,
            snapshot_valid=False,
            snapshot_symbol_count=0,
            checksum_drift=checksum_drift,
            error=error,
        )

    def _relative_to_root(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.archive.root))
        except ValueError:
            return path.name

    @staticmethod
    def export(report: BackfillPilotReport, output: Path) -> tuple[Path, Path, Path]:
        output.mkdir(parents=True, exist_ok=True)
        json_path = output / "htr007_backfill_pilot.json"
        csv_path = output / "htr007_backfill_pilot.csv"
        markdown_path = output / "htr007_backfill_pilot.md"

        payload = report.as_dict()
        json_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rows = [record.as_dict() for record in report.records]
        fieldnames = tuple(rows[0]) if rows else ("trading_date",)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        lines = [
            "# HTR-007 Cross-Era Backfill Pilot",
            "",
            f"- Complete: `{report.complete}`",
            f"- Records: `{len(report.records)}`",
            f"- Schemas Observed: `{', '.join(report.schemas_observed)}`",
            f"- Report SHA-256: `{report.report_sha256}`",
            "- Official Source: `NSE`",
            "- Live Downloads in CI: `False`",
            "",
            "| Date | Status | Schema | Rows | Snapshot | Error |",
            "|---|---|---|---:|---|---|",
        ]
        for record in report.records:
            lines.append(
                "| "
                + " | ".join(
                    (
                        record.trading_date.isoformat(),
                        record.status.value,
                        record.detected_schema or "",
                        str(record.archive_row_count),
                        "valid" if record.snapshot_valid else "invalid",
                        (record.error or "").replace("|", "/"),
                    )
                )
                + " |"
            )
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return json_path, csv_path, markdown_path


__all__ = [
    "BackfillPilotRecord",
    "BackfillPilotReport",
    "BackfillPilotStatus",
    "DEFAULT_CROSS_ERA_DATES",
    "HTR007_PILOT_CONTRACT_VERSION",
    "HistoricalBackfillPilot",
]
