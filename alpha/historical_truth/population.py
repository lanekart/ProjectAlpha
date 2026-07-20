from __future__ import annotations

import csv
import json
import zipfile
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.models import ArchiveRequest, ManifestStatus
from alpha.historical_truth.resumable import HistoricalTruthWarehouse
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine


class PopulationStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class PopulationRecord:
    trading_date: date
    status: PopulationStatus
    downloaded: bool
    validated: bool
    ingested_rows: int
    snapshot_path: str | None
    evidence_complete: bool | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PopulationSummary:
    total: int
    complete: int
    partial: int
    candle_snapshots: int
    evidence_complete_snapshots: int
    evidence_incomplete_snapshots: int
    failed: int
    unavailable: int
    skipped: int
    ingested_rows: int
    available_rows: int
    coverage_ratio: float


class HistoricalPopulationEngine:
    """Populate canonical history and immutable snapshots from official archives."""

    def __init__(
        self,
        archive: HistoricalTruthWarehouse,
        canonical: CanonicalPointInTimeWarehouse,
        snapshots: PointInTimeSnapshotEngine,
        *,
        staging_root: Path | None = None,
    ) -> None:
        self.archive = archive
        self.canonical = canonical
        self.snapshots = snapshots
        self.staging_root = staging_root or archive.root / "staging" / "population"

    def populate(
        self,
        requests: tuple[ArchiveRequest, ...],
        *,
        retry_failed: bool = True,
    ) -> tuple[PopulationRecord, ...]:
        results: list[PopulationRecord] = []
        for request in requests:
            results.append(self._populate_one(request, retry_failed=retry_failed))
        return tuple(results)

    def _populate_one(
        self,
        request: ArchiveRequest,
        *,
        retry_failed: bool,
    ) -> PopulationRecord:
        existing_snapshot = self.snapshots.path_for(
            request.trading_date,
            exchange=request.exchange,
        )
        if existing_snapshot.exists():
            snapshot = self.snapshots.load(
                request.trading_date,
                exchange=request.exchange,
            )
            verification = self.snapshots.verify(snapshot)
            if verification.valid:
                return PopulationRecord(
                    trading_date=request.trading_date,
                    status=PopulationStatus.SKIPPED,
                    downloaded=True,
                    validated=True,
                    ingested_rows=snapshot.metadata.symbol_count,
                    snapshot_path=str(existing_snapshot),
                    evidence_complete=(snapshot.metadata.completeness_score == 1.0),
                )

        manifest = self.archive._existing_record(request)
        if (
            manifest is not None
            and manifest.status is ManifestStatus.FAILED
            and not retry_failed
        ):
            return PopulationRecord(
                trading_date=request.trading_date,
                status=PopulationStatus.SKIPPED,
                downloaded=False,
                validated=False,
                ingested_rows=0,
                snapshot_path=None,
                error=manifest.error,
            )

        fetched = self.archive.fetch(request)
        if fetched.status is ManifestStatus.UNAVAILABLE:
            return PopulationRecord(
                trading_date=request.trading_date,
                status=PopulationStatus.UNAVAILABLE,
                downloaded=False,
                validated=False,
                ingested_rows=0,
                snapshot_path=None,
                error=fetched.error,
            )
        if fetched.status is ManifestStatus.FAILED:
            return PopulationRecord(
                trading_date=request.trading_date,
                status=PopulationStatus.FAILED,
                downloaded=False,
                validated=False,
                ingested_rows=0,
                snapshot_path=None,
                error=fetched.error,
            )

        archive_path = self.archive.raw_root / request.relative_path
        try:
            csv_path = self._extract_single_csv(archive_path, request)
            issues = self.archive.validate_bhavcopy_csv(csv_path)
            self.canonical.record_validation_issues(
                request.trading_date,
                issues,
                exchange=request.exchange,
                source_sha256=fetched.sha256,
            )
            errors = tuple(issue for issue in issues if issue.severity.value == "error")
            if errors:
                return PopulationRecord(
                    trading_date=request.trading_date,
                    status=PopulationStatus.FAILED,
                    downloaded=True,
                    validated=False,
                    ingested_rows=0,
                    snapshot_path=None,
                    error="; ".join(
                        f"{issue.code}: {issue.message}" for issue in errors
                    ),
                )
            row_count = self.canonical.ingest_bhavcopy_csv(
                csv_path,
                trading_date=request.trading_date,
                exchange=request.exchange,
                source_sha256=fetched.sha256,
            )
            snapshot = self.snapshots.build(
                request.trading_date,
                exchange=request.exchange,
            )
            snapshot_path = self.snapshots.persist(snapshot)
            status = (
                PopulationStatus.COMPLETE
                if snapshot.metadata.completeness_score == 1.0
                else PopulationStatus.PARTIAL
            )
            return PopulationRecord(
                trading_date=request.trading_date,
                status=status,
                downloaded=True,
                validated=True,
                ingested_rows=row_count,
                snapshot_path=str(snapshot_path),
                evidence_complete=(snapshot.metadata.completeness_score == 1.0),
            )
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return PopulationRecord(
                trading_date=request.trading_date,
                status=PopulationStatus.FAILED,
                downloaded=True,
                validated=False,
                ingested_rows=0,
                snapshot_path=None,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _extract_single_csv(
        self,
        archive_path: Path,
        request: ArchiveRequest,
    ) -> Path:
        target_dir = (
            self.staging_root
            / request.exchange.lower()
            / request.dataset.value
            / request.trading_date.isoformat()
        )
        target_dir.mkdir(parents=True, exist_ok=True)
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
            safe_name = Path(member.filename).name
            if not safe_name:
                raise ValueError("archive CSV member has an invalid name")
            destination = target_dir / safe_name
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            with archive.open(member) as source, temporary.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
            temporary.replace(destination)
        return destination

    @staticmethod
    def summarise(records: tuple[PopulationRecord, ...]) -> PopulationSummary:
        counts = {status: 0 for status in PopulationStatus}
        for record in records:
            counts[record.status] += 1
        snapshot_records = tuple(
            record
            for record in records
            if record.validated and record.snapshot_path is not None
        )
        candle_snapshots = len(snapshot_records)
        evidence_complete = sum(
            record.evidence_complete is True for record in snapshot_records
        )
        evidence_incomplete = candle_snapshots - evidence_complete
        coverage = candle_snapshots / len(records) if records else 1.0
        return PopulationSummary(
            total=len(records),
            complete=counts[PopulationStatus.COMPLETE],
            partial=counts[PopulationStatus.PARTIAL],
            candle_snapshots=candle_snapshots,
            evidence_complete_snapshots=evidence_complete,
            evidence_incomplete_snapshots=evidence_incomplete,
            failed=counts[PopulationStatus.FAILED],
            unavailable=counts[PopulationStatus.UNAVAILABLE],
            skipped=counts[PopulationStatus.SKIPPED],
            ingested_rows=sum(
                record.ingested_rows
                for record in records
                if record.status
                in {PopulationStatus.COMPLETE, PopulationStatus.PARTIAL}
            ),
            available_rows=sum(record.ingested_rows for record in snapshot_records),
            coverage_ratio=round(coverage, 6),
        )

    @staticmethod
    def export(
        records: tuple[PopulationRecord, ...],
        output_dir: Path,
    ) -> tuple[Path, Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = HistoricalPopulationEngine.summarise(records)
        payload = [
            HistoricalPopulationEngine._record_payload(record) for record in records
        ]

        json_path = output_dir / "historical_population.json"
        csv_path = output_dir / "historical_population.csv"
        markdown_path = output_dir / "historical_population.md"
        json_path.write_text(
            json.dumps(
                {"summary": asdict(summary), "records": payload},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        fieldnames = (
            list(payload[0])
            if payload
            else [
                "trading_date",
                "status",
                "downloaded",
                "validated",
                "ingested_rows",
                "snapshot_path",
                "error",
            ]
        )
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(payload)

        lines = [
            "# Historical Population Report",
            "",
            f"Weekday request coverage: {summary.coverage_ratio:.2%}",
            f"Candle snapshots available: {summary.candle_snapshots}",
            (f"Evidence-complete snapshots: {summary.evidence_complete_snapshots}"),
            (f"Evidence-incomplete snapshots: {summary.evidence_incomplete_snapshots}"),
            f"Failed: {summary.failed}",
            f"Unavailable: {summary.unavailable}",
            f"Skipped: {summary.skipped}",
            f"Rows ingested this run: {summary.ingested_rows}",
            f"Rows available in snapshots: {summary.available_rows}",
            "",
            "| Date | Status | Rows | Snapshot | Error |",
            "|---|---|---:|---|---|",
        ]
        for record in records:
            lines.append(
                "| "
                + " | ".join(
                    (
                        record.trading_date.isoformat(),
                        record.status.value,
                        str(record.ingested_rows),
                        record.snapshot_path or "",
                        (record.error or "").replace("|", "/"),
                    )
                )
                + " |"
            )
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return json_path, csv_path, markdown_path

    @staticmethod
    def _record_payload(record: PopulationRecord) -> dict[str, object]:
        payload = asdict(record)
        payload["trading_date"] = record.trading_date.isoformat()
        payload["status"] = record.status.value
        payload["candle_ingestion"] = (
            "ingested_this_run"
            if record.status in {PopulationStatus.COMPLETE, PopulationStatus.PARTIAL}
            else (
                "already_available"
                if record.validated and record.snapshot_path is not None
                else "not_available"
            )
        )
        payload["evidence_completeness"] = (
            "complete"
            if record.evidence_complete is True
            else (
                "incomplete" if record.evidence_complete is False else "not_applicable"
            )
        )
        return payload
