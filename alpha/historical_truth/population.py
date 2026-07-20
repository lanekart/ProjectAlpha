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
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PopulationSummary:
    total: int
    complete: int
    partial: int
    failed: int
    unavailable: int
    skipped: int
    ingested_rows: int
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
            errors = tuple(issue for issue in issues if issue.severity.value == "error")
            if errors:
                return PopulationRecord(
                    trading_date=request.trading_date,
                    status=PopulationStatus.FAILED,
                    downloaded=True,
                    validated=False,
                    ingested_rows=0,
                    snapshot_path=None,
                    error="; ".join(issue.code for issue in errors),
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
        complete_or_partial = (
            counts[PopulationStatus.COMPLETE] + counts[PopulationStatus.PARTIAL]
        )
        coverage = complete_or_partial / len(records) if records else 1.0
        return PopulationSummary(
            total=len(records),
            complete=counts[PopulationStatus.COMPLETE],
            partial=counts[PopulationStatus.PARTIAL],
            failed=counts[PopulationStatus.FAILED],
            unavailable=counts[PopulationStatus.UNAVAILABLE],
            skipped=counts[PopulationStatus.SKIPPED],
            ingested_rows=sum(record.ingested_rows for record in records),
            coverage_ratio=round(coverage, 6),
        )

    @staticmethod
    def export(
        records: tuple[PopulationRecord, ...],
        output_dir: Path,
    ) -> tuple[Path, Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = HistoricalPopulationEngine.summarise(records)
        payload = [HistoricalPopulationEngine._record_payload(record) for record in records]

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
        fieldnames = list(payload[0]) if payload else [
            "trading_date",
            "status",
            "downloaded",
            "validated",
            "ingested_rows",
            "snapshot_path",
            "error",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(payload)

        lines = [
            "# Historical Population Report",
            "",
            f"Coverage: {summary.coverage_ratio:.2%}",
            f"Complete: {summary.complete}",
            f"Partial: {summary.partial}",
            f"Failed: {summary.failed}",
            f"Unavailable: {summary.unavailable}",
            f"Skipped: {summary.skipped}",
            f"Ingested rows: {summary.ingested_rows}",
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
        return payload
