from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.manager import ArchiveTask, HistoricalArchiveManager, TaskState
from alpha.historical_truth.population import (
    HistoricalPopulationEngine,
    PopulationRecord,
    PopulationStatus,
)
from alpha.historical_truth.resumable import HistoricalTruthWarehouse
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine

HTR007_BACKFILL_CONTRACT_VERSION = "1.0"
PLANNING_BASIS = "WEEKDAY_CANDIDATES_UNRECONCILED"


class BackfillCertificationState(StrEnum):
    UNRECONCILED_NOT_CERTIFIED = "unreconciled_not_certified"


class BackfillRecordStatus(StrEnum):
    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    SKIPPED = "skipped"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class BackfillRecord:
    trading_date: date
    source_url: str
    archive_relative_path: str
    status: BackfillRecordStatus
    download_state: str
    download_attempts: int
    population_status: str
    downloaded: bool
    validated: bool
    ingested_rows: int
    snapshot_relative_path: str | None
    snapshot_valid: bool
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["trading_date"] = self.trading_date.isoformat()
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True, slots=True)
class BackfillReport:
    contract_version: str
    start_date: date
    end_date: date
    planning_basis: str
    certification_state: BackfillCertificationState
    workers: int
    retry_failed: bool
    run_complete: bool
    operationally_complete: bool
    candidate_date_count: int
    complete_count: int
    unavailable_count: int
    failed_count: int
    skipped_count: int
    deferred_count: int
    records: tuple[BackfillRecord, ...]
    report_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            **self._hash_payload(),
            "report_sha256": self.report_sha256,
        }

    def _hash_payload(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "planning_basis": self.planning_basis,
            "certification_state": self.certification_state.value,
            "workers": self.workers,
            "retry_failed": self.retry_failed,
            "run_complete": self.run_complete,
            "operationally_complete": self.operationally_complete,
            "candidate_date_count": self.candidate_date_count,
            "complete_count": self.complete_count,
            "unavailable_count": self.unavailable_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "deferred_count": self.deferred_count,
            "records": [record.as_dict() for record in self.records],
        }


class HistoricalBackfillEngine:
    """Checkpointed orchestration for unreconciled NSE weekday candidates."""

    def __init__(
        self,
        archive: HistoricalTruthWarehouse,
        canonical: CanonicalPointInTimeWarehouse,
        snapshots: PointInTimeSnapshotEngine,
        *,
        checkpoint_path: Path | None = None,
    ) -> None:
        self.archive = archive
        self.canonical = canonical
        self.snapshots = snapshots
        self.population = HistoricalPopulationEngine(archive, canonical, snapshots)
        self.checkpoint_path = checkpoint_path

    def run(
        self,
        start_date: date,
        end_date: date,
        *,
        workers: int = 4,
        retry_failed: bool = True,
        max_records: int | None = None,
    ) -> BackfillReport:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        if workers < 1:
            raise ValueError("workers must be at least 1")
        if max_records is not None and max_records < 1:
            raise ValueError("max_records must be at least 1 when supplied")

        requests = self.archive.plan_nse_bhavcopies(start_date, end_date)
        checkpoint_path = self.checkpoint_path or self._default_checkpoint_path(
            start_date, end_date
        )
        self._validate_existing_checkpoint(checkpoint_path, start_date, end_date)

        manager = HistoricalArchiveManager(
            self.archive,
            checkpoint_path=checkpoint_path.with_name(
                checkpoint_path.stem + "_downloads.json"
            ),
        )
        planned_tasks = manager.build_tasks(requests)
        safe_tasks: list[ArchiveTask] = []
        blocked_tasks: dict[str, ArchiveTask] = {}
        for task in planned_tasks:
            verification = self.archive.verify_raw_archive(task.request)
            if verification.valid:
                safe_tasks.append(task)
                continue
            blocked_tasks[task.task_id] = ArchiveTask(
                task_id=task.task_id,
                request=task.request,
                state=TaskState.FAILED,
                attempts=task.attempts,
                updated_at=task.updated_at,
                error=verification.reason,
            )

        completed_tasks = manager.run(
            tuple(safe_tasks),
            workers=workers,
            retry_failed=retry_failed,
        )
        tasks_by_id = {task.task_id: task for task in completed_tasks}
        tasks_by_id.update(blocked_tasks)

        records: list[BackfillRecord] = []
        for index, request in enumerate(requests):
            task_id = manager._task_id(request)
            task = tasks_by_id[task_id]
            if max_records is not None and index >= max_records:
                records.append(self._deferred_record(task))
                self._write_checkpoint(
                    checkpoint_path,
                    self._build_report(
                        start_date,
                        end_date,
                        workers,
                        retry_failed,
                        tuple(records),
                        candidate_date_count=len(requests),
                    ),
                )
                continue

            record = self._record_for_task(task, retry_failed=retry_failed)
            records.append(record)
            self._write_checkpoint(
                checkpoint_path,
                self._build_report(
                    start_date,
                    end_date,
                    workers,
                    retry_failed,
                    tuple(records),
                    candidate_date_count=len(requests),
                ),
            )

        report = self._build_report(
            start_date,
            end_date,
            workers,
            retry_failed,
            tuple(records),
            candidate_date_count=len(requests),
        )
        self._write_checkpoint(checkpoint_path, report)
        return report

    def export(
        self,
        report: BackfillReport,
        output_dir: Path,
    ) -> tuple[Path, Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "htr007_backfill.json"
        csv_path = output_dir / "htr007_backfill.csv"
        markdown_path = output_dir / "htr007_backfill.md"

        json_path.write_text(
            json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rows = [record.as_dict() for record in report.records]
        fieldnames = list(rows[0]) if rows else list(BackfillRecord.__dataclass_fields__)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        lines = [
            "# HTR-007 Checkpointed Backfill",
            "",
            f"Contract version: `{report.contract_version}`",
            f"Window: `{report.start_date}` to `{report.end_date}`",
            f"Planning basis: `{report.planning_basis}`",
            f"Certification state: `{report.certification_state.value}`",
            f"Operationally complete: `{report.operationally_complete}`",
            f"Report SHA-256: `{report.report_sha256}`",
            "",
            "> This run is not authoritative trading-calendar certification. Weekdays are candidate dates until official exchange-session reconciliation is complete.",
            "",
            "| Date | Status | Download | Population | Rows | Snapshot valid | Error |",
            "|---|---|---|---|---:|---|---|",
        ]
        for record in report.records:
            lines.append(
                "| "
                + " | ".join(
                    (
                        record.trading_date.isoformat(),
                        record.status.value,
                        record.download_state,
                        record.population_status,
                        str(record.ingested_rows),
                        str(record.snapshot_valid),
                        (record.error or "").replace("|", "/"),
                    )
                )
                + " |"
            )
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return json_path, csv_path, markdown_path

    def _record_for_task(
        self,
        task: ArchiveTask,
        *,
        retry_failed: bool,
    ) -> BackfillRecord:
        request = task.request
        if task.state is TaskState.UNAVAILABLE:
            return self._task_only_record(
                task,
                status=BackfillRecordStatus.UNAVAILABLE,
            )
        if task.state is TaskState.FAILED:
            return self._task_only_record(
                task,
                status=BackfillRecordStatus.FAILED,
            )
        if task.state is TaskState.SKIPPED:
            return self._task_only_record(
                task,
                status=BackfillRecordStatus.SKIPPED,
            )
        if task.state is not TaskState.COMPLETE:
            return self._task_only_record(
                task,
                status=BackfillRecordStatus.FAILED,
                error=f"unexpected download state: {task.state.value}",
            )

        population = self.population.populate(
            (request,),
            retry_failed=retry_failed,
        )[0]
        return self._population_record(task, population)

    def _population_record(
        self,
        task: ArchiveTask,
        population: PopulationRecord,
    ) -> BackfillRecord:
        snapshot_relative_path: str | None = None
        snapshot_valid = False
        verification_error: str | None = None
        if population.snapshot_path is not None:
            snapshot_path = Path(population.snapshot_path)
            snapshot_relative_path = self._relative_to_root(snapshot_path)
            try:
                snapshot = self.snapshots.load(
                    task.request.trading_date,
                    exchange=task.request.exchange,
                )
                verification = self.snapshots.verify(snapshot)
                snapshot_valid = verification.valid
                verification_error = verification.reason
            except (OSError, ValueError, KeyError, TypeError) as exc:
                verification_error = f"{type(exc).__name__}: {exc}"

        canonical_available = (
            population.validated
            and population.snapshot_path is not None
            and snapshot_valid
        )
        status = (
            BackfillRecordStatus.COMPLETE
            if canonical_available
            else BackfillRecordStatus.FAILED
        )
        error = population.error or verification_error
        if not canonical_available and error is None:
            error = "canonical snapshot is not valid and available"

        return BackfillRecord(
            trading_date=task.request.trading_date,
            source_url=task.request.source_url,
            archive_relative_path=str(task.request.relative_path),
            status=status,
            download_state=task.state.value,
            download_attempts=task.attempts,
            population_status=(
                "available"
                if canonical_available
                else population.status.value
            ),
            downloaded=population.downloaded,
            validated=population.validated,
            ingested_rows=population.ingested_rows,
            snapshot_relative_path=snapshot_relative_path,
            snapshot_valid=snapshot_valid,
            error=error,
        )

    @staticmethod
    def _task_only_record(
        task: ArchiveTask,
        *,
        status: BackfillRecordStatus,
        error: str | None = None,
    ) -> BackfillRecord:
        return BackfillRecord(
            trading_date=task.request.trading_date,
            source_url=task.request.source_url,
            archive_relative_path=str(task.request.relative_path),
            status=status,
            download_state=task.state.value,
            download_attempts=task.attempts,
            population_status="not_attempted",
            downloaded=False,
            validated=False,
            ingested_rows=0,
            snapshot_relative_path=None,
            snapshot_valid=False,
            error=error or task.error,
        )

    @staticmethod
    def _deferred_record(task: ArchiveTask) -> BackfillRecord:
        return HistoricalBackfillEngine._task_only_record(
            task,
            status=BackfillRecordStatus.DEFERRED,
            error="deferred by max_records execution limit",
        )

    def _relative_to_root(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.archive.root))
        except ValueError:
            return str(path)

    def _default_checkpoint_path(self, start_date: date, end_date: date) -> Path:
        token = f"{start_date.isoformat()}_{end_date.isoformat()}"
        return self.archive.root / "manifests" / f"htr007_backfill_{token}.json"

    @staticmethod
    def _validate_existing_checkpoint(
        checkpoint_path: Path,
        start_date: date,
        end_date: date,
    ) -> None:
        if not checkpoint_path.exists():
            return
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        expected = {
            "contract_version": HTR007_BACKFILL_CONTRACT_VERSION,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "planning_basis": PLANNING_BASIS,
            "certification_state": (
                BackfillCertificationState.UNRECONCILED_NOT_CERTIFIED.value
            ),
        }
        observed = {key: payload.get(key) for key in expected}
        if observed != expected:
            raise ValueError("existing backfill checkpoint contract does not match run")

    @staticmethod
    def _write_checkpoint(path: Path, report: BackfillReport) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _build_report(
        start_date: date,
        end_date: date,
        workers: int,
        retry_failed: bool,
        records: tuple[BackfillRecord, ...],
        *,
        candidate_date_count: int,
    ) -> BackfillReport:
        counts = {status: 0 for status in BackfillRecordStatus}
        for record in records:
            counts[record.status] += 1
        run_complete = (
            len(records) == candidate_date_count
            and counts[BackfillRecordStatus.DEFERRED] == 0
        )
        operationally_complete = (
            run_complete
            and counts[BackfillRecordStatus.FAILED] == 0
            and counts[BackfillRecordStatus.SKIPPED] == 0
        )
        partial = BackfillReport(
            contract_version=HTR007_BACKFILL_CONTRACT_VERSION,
            start_date=start_date,
            end_date=end_date,
            planning_basis=PLANNING_BASIS,
            certification_state=(
                BackfillCertificationState.UNRECONCILED_NOT_CERTIFIED
            ),
            workers=workers,
            retry_failed=retry_failed,
            run_complete=run_complete,
            operationally_complete=operationally_complete,
            candidate_date_count=candidate_date_count,
            complete_count=counts[BackfillRecordStatus.COMPLETE],
            unavailable_count=counts[BackfillRecordStatus.UNAVAILABLE],
            failed_count=counts[BackfillRecordStatus.FAILED],
            skipped_count=counts[BackfillRecordStatus.SKIPPED],
            deferred_count=counts[BackfillRecordStatus.DEFERRED],
            records=records,
            report_sha256="",
        )
        encoded = json.dumps(
            partial._hash_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return BackfillReport(
            **{
                **partial.__dict__,
                "report_sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )
