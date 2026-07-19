from __future__ import annotations

import csv
import gzip
import io
import json
import mimetypes
import zipfile
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath

from alpha.market_truth.warehouse.models import (
    Exchange,
    IngestionStatus,
    SourceAuthorisation,
    SourceFileRecord,
    WarehouseDataset,
    WarehousePaths,
    stable_hash,
)


class UnsafeArchiveError(ValueError):
    pass


class RawArchiveVault:
    """Content-addressed immutable source custody with a verified manifest."""

    def __init__(self, paths: WarehousePaths) -> None:
        self.paths = paths

    def import_file(
        self,
        source: Path,
        *,
        exchange: Exchange,
        dataset: WarehouseDataset,
        authorisation: SourceAuthorisation,
        trading_date: date | None,
        publication_timestamp: datetime | None = None,
        retrieval_timestamp: datetime | None = None,
    ) -> tuple[SourceFileRecord, bool]:
        if not source.is_file():
            raise FileNotFoundError(f"source file does not exist: {source}")
        raw = source.read_bytes()
        digest = sha256(raw).hexdigest()
        manifest = self.records()
        duplicate = next((item for item in manifest if item.sha256 == digest), None)
        if duplicate is not None:
            if (
                duplicate.provider != authorisation.provider
                or duplicate.dataset_type is not dataset
                or duplicate.exchange is not exchange
            ):
                raise ValueError(
                    "identical bytes were previously registered with conflicting "
                    "source metadata"
                )
            self.verify(duplicate)
            return duplicate, True

        schema_fingerprint = _schema_fingerprint(source.name, raw)
        timestamp = retrieval_timestamp or datetime.now(tz=UTC)
        source_file_id = (
            "source-"
            + stable_hash(
                {
                    "sha256": digest,
                    "provider": authorisation.provider,
                    "dataset": dataset.value,
                }
            )[:24]
        )
        previous = _latest_for_session(
            manifest,
            provider=authorisation.provider,
            dataset=dataset,
            exchange=exchange,
            trading_date=trading_date,
        )
        year = str((trading_date or timestamp.date()).year)
        target_dir = (
            self.paths.raw
            / exchange.value.lower()
            / dataset.value.lower()
            / year
            / source_file_id
        )
        target_dir.mkdir(parents=True, exist_ok=False)
        target = target_dir / source.name
        target.write_bytes(raw)
        record = SourceFileRecord(
            source_file_id=source_file_id,
            provider=authorisation.provider,
            dataset_type=dataset,
            exchange=exchange,
            trading_date=trading_date,
            publication_timestamp=publication_timestamp,
            retrieval_timestamp=timestamp,
            original_filename=source.name,
            content_type=mimetypes.guess_type(source.name)[0]
            or "application/octet-stream",
            file_size=len(raw),
            sha256=digest,
            schema_fingerprint=schema_fingerprint,
            authorisation_record_id=authorisation.record_id,
            ingestion_status=IngestionStatus.ARCHIVED,
            vault_path=str(target.relative_to(self.paths.root)),
            supersedes_file_id=(None if previous is None else previous.source_file_id),
        )
        self._write_manifest((*manifest, record))
        return record, False

    def update_status(
        self, source_file_id: str, status: IngestionStatus
    ) -> SourceFileRecord:
        records = self.records()
        updated: list[SourceFileRecord] = []
        result: SourceFileRecord | None = None
        for record in records:
            if record.source_file_id == source_file_id:
                record = replace(record, ingestion_status=status)
                result = record
            updated.append(record)
        if result is None:
            raise KeyError(f"unknown source file: {source_file_id}")
        self._write_manifest(tuple(updated))
        return result

    def records(self) -> tuple[SourceFileRecord, ...]:
        if not self.paths.manifest.exists():
            return ()
        payload = json.loads(self.paths.manifest.read_text())
        if not isinstance(payload, list):
            raise ValueError("raw vault manifest must contain a JSON list")
        return tuple(_record_from_dict(item) for item in payload)

    def require(self, source_file_id: str) -> SourceFileRecord:
        for record in self.records():
            if record.source_file_id == source_file_id:
                return record
        raise KeyError(f"unknown source file: {source_file_id}")

    def path_for(self, record: SourceFileRecord) -> Path:
        return self.paths.root / record.vault_path

    def verify(self, record: SourceFileRecord) -> None:
        path = self.path_for(record)
        if not path.is_file():
            raise RuntimeError(f"vault bytes missing for {record.source_file_id}")
        digest = sha256(path.read_bytes()).hexdigest()
        if digest != record.sha256:
            raise RuntimeError(f"vault checksum mismatch for {record.source_file_id}")

    def manifest_hash(self) -> str:
        if not self.paths.manifest.exists():
            return stable_hash([])
        return sha256(self.paths.manifest.read_bytes()).hexdigest()

    def _write_manifest(self, records: tuple[SourceFileRecord, ...]) -> None:
        self.paths.manifest.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            _record_as_dict(item)
            for item in sorted(records, key=lambda value: value.source_file_id)
        ]
        temporary = self.paths.manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        temporary.replace(self.paths.manifest)


def source_payload(path: Path) -> tuple[str, bytes]:
    raw = path.read_bytes()
    lower = path.name.lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = tuple(
                item
                for item in archive.infolist()
                if not item.is_dir() and _safe_member(item.filename)
            )
            if len(members) != 1:
                raise UnsafeArchiveError(
                    "archive must contain exactly one safe source file"
                )
            member = members[0]
            if member.file_size > 1_000_000_000:
                raise UnsafeArchiveError("archive member exceeds the 1 GB limit")
            return Path(member.filename).name, archive.read(member)
    if lower.endswith(".gz"):
        return path.stem, gzip.decompress(raw)
    return path.name, raw


def _safe_member(name: str) -> bool:
    member = PurePosixPath(name)
    if member.is_absolute() or ".." in member.parts:
        raise UnsafeArchiveError("archive contains an unsafe path")
    return True


def _schema_fingerprint(filename: str, raw: bytes) -> str:
    suffix = filename.lower()
    try:
        if suffix.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = tuple(
                    item for item in archive.infolist() if not item.is_dir()
                )
                if not members:
                    return stable_hash({"empty_archive": True})
                raw = archive.read(members[0])
        elif suffix.endswith(".gz"):
            raw = gzip.decompress(raw)
        line = raw.decode("utf-8-sig", errors="replace").splitlines()[0]
        columns = next(csv.reader((line,)))
    except (IndexError, csv.Error, OSError, zipfile.BadZipFile):
        columns = []
    return stable_hash([item.strip().lower() for item in columns])


def _latest_for_session(
    records: tuple[SourceFileRecord, ...],
    *,
    provider: str,
    dataset: WarehouseDataset,
    exchange: Exchange,
    trading_date: date | None,
) -> SourceFileRecord | None:
    matching = tuple(
        item
        for item in records
        if item.provider == provider
        and item.dataset_type is dataset
        and item.exchange is exchange
        and item.trading_date == trading_date
    )
    return max(matching, key=lambda item: item.retrieval_timestamp, default=None)


def _record_as_dict(record: SourceFileRecord) -> dict[str, object]:
    payload = asdict(record)
    payload["dataset_type"] = record.dataset_type.value
    payload["exchange"] = record.exchange.value
    payload["trading_date"] = (
        None if record.trading_date is None else record.trading_date.isoformat()
    )
    payload["publication_timestamp"] = (
        None
        if record.publication_timestamp is None
        else record.publication_timestamp.isoformat()
    )
    payload["retrieval_timestamp"] = record.retrieval_timestamp.isoformat()
    payload["ingestion_status"] = record.ingestion_status.value
    return payload


def _record_from_dict(payload: object) -> SourceFileRecord:
    if not isinstance(payload, dict):
        raise ValueError("raw vault manifest record must be an object")
    return SourceFileRecord(
        source_file_id=str(payload["source_file_id"]),
        provider=str(payload["provider"]),
        dataset_type=WarehouseDataset(str(payload["dataset_type"])),
        exchange=Exchange(str(payload["exchange"])),
        trading_date=(
            None
            if payload.get("trading_date") is None
            else date.fromisoformat(str(payload["trading_date"]))
        ),
        publication_timestamp=(
            None
            if payload.get("publication_timestamp") is None
            else datetime.fromisoformat(str(payload["publication_timestamp"]))
        ),
        retrieval_timestamp=datetime.fromisoformat(str(payload["retrieval_timestamp"])),
        original_filename=str(payload["original_filename"]),
        content_type=str(payload["content_type"]),
        file_size=int(payload["file_size"]),
        sha256=str(payload["sha256"]),
        schema_fingerprint=str(payload["schema_fingerprint"]),
        authorisation_record_id=str(payload["authorisation_record_id"]),
        ingestion_status=IngestionStatus(str(payload["ingestion_status"])),
        vault_path=str(payload["vault_path"]),
        supersedes_file_id=(
            None
            if payload.get("supersedes_file_id") is None
            else str(payload["supersedes_file_id"])
        ),
    )


__all__ = ["RawArchiveVault", "UnsafeArchiveError", "source_payload"]
