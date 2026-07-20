from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import requests

from alpha.historical_truth.models import (
    ArchiveDataset,
    ArchiveRequest,
    ManifestRecord,
    ManifestStatus,
    ValidationIssue,
    ValidationSeverity,
)

_LEGACY_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {"SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY"}
)
_UDIFF_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {"TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"}
)
_UDIFF_START_DATE: Final[date] = date(2024, 7, 8)


class HistoricalTruthWarehouse:
    """Immutable archive store for official point-in-time market files."""

    def __init__(self, root: Path, *, timeout_seconds: float = 30.0) -> None:
        self.root = root
        self.timeout_seconds = timeout_seconds

    @property
    def raw_root(self) -> Path:
        return self.root / "raw"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifests" / "archive_manifest.jsonl"

    def initialise(self) -> None:
        for relative in (
            "raw/nse",
            "raw/bse",
            "staging",
            "warehouse",
            "snapshots",
            "derived",
            "manifests",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    def plan_nse_bhavcopies(self, start: date, end: date) -> tuple[ArchiveRequest, ...]:
        if end < start:
            raise ValueError("end date must be on or after start date")
        requests_: list[ArchiveRequest] = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                requests_.append(self._nse_bhavcopy_request(current))
            current += timedelta(days=1)
        return tuple(requests_)

    @staticmethod
    def _nse_bhavcopy_request(trading_date: date) -> ArchiveRequest:
        year = trading_date.strftime("%Y")
        if trading_date >= _UDIFF_START_DATE:
            filename = (
                "BhavCopy_NSE_CM_0_0_0_"
                f"{trading_date.strftime('%Y%m%d')}_F_0000.csv.zip"
            )
            source_url = f"https://nsearchives.nseindia.com/content/cm/{filename}"
        else:
            token = trading_date.strftime("%d%b%Y").upper()
            month = trading_date.strftime("%b").upper()
            filename = f"cm{token}bhav.csv.zip"
            source_url = (
                "https://nsearchives.nseindia.com/content/historical/EQUITIES/"
                f"{year}/{month}/{filename}"
            )
        return ArchiveRequest(
            exchange="nse",
            dataset=ArchiveDataset.BHAVCOPY,
            trading_date=trading_date,
            source_url=source_url,
            relative_path=Path("nse") / "bhavcopy" / year / filename,
        )

    def fetch(self, request: ArchiveRequest) -> ManifestRecord:
        self.initialise()
        destination = self.raw_root / request.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        existing = self._existing_record(request)
        if destination.exists():
            digest, byte_size = self._hash_file(destination)
            record = ManifestRecord(
                exchange=request.exchange,
                dataset=request.dataset,
                trading_date=request.trading_date,
                source_url=request.source_url,
                relative_path=str(request.relative_path),
                status=ManifestStatus.DOWNLOADED,
                retrieved_at=existing.retrieved_at if existing else None,
                sha256=digest,
                byte_size=byte_size,
                error=None,
            )
            self._append_manifest(record)
            return record

        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.unlink(missing_ok=True)
        try:
            response = requests.get(
                request.source_url,
                timeout=self.timeout_seconds,
                headers={"User-Agent": "ProjectAlpha-HistoricalTruth/1.0"},
            )
            if response.status_code == 404:
                record = self._failure_record(
                    request,
                    ManifestStatus.UNAVAILABLE,
                    "official archive returned HTTP 404",
                )
                self._append_manifest(record)
                return record
            response.raise_for_status()
            payload = response.content
            if not payload:
                raise ValueError("official archive returned an empty response")
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
            digest, byte_size = self._hash_file(destination)
            record = ManifestRecord(
                exchange=request.exchange,
                dataset=request.dataset,
                trading_date=request.trading_date,
                source_url=request.source_url,
                relative_path=str(request.relative_path),
                status=ManifestStatus.DOWNLOADED,
                retrieved_at=datetime.now(UTC),
                sha256=digest,
                byte_size=byte_size,
                error=None,
            )
        except (OSError, requests.RequestException, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            record = self._failure_record(
                request,
                ManifestStatus.FAILED,
                f"{type(exc).__name__}: {exc}",
            )
        self._append_manifest(record)
        return record

    def validate_bhavcopy_csv(self, csv_path: Path) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = frozenset(reader.fieldnames or ())
            schema = self._detect_bhavcopy_schema(columns)
            if schema is None:
                missing_legacy = sorted(_LEGACY_REQUIRED_COLUMNS - columns)
                missing_udiff = sorted(_UDIFF_REQUIRED_COLUMNS - columns)
                return (
                    ValidationIssue(
                        code="MISSING_REQUIRED_COLUMNS",
                        severity=ValidationSeverity.ERROR,
                        message=(
                            "Unsupported bhavcopy schema. Missing legacy columns: "
                            f"{', '.join(missing_legacy)}; missing UDiFF columns: "
                            f"{', '.join(missing_udiff)}"
                        ),
                    ),
                )
            fields = self._schema_fields(schema)
            seen: set[tuple[str, str]] = set()
            for row_number, row in enumerate(reader, start=2):
                symbol = (row.get(fields["symbol"]) or "").strip()
                series = (row.get(fields["series"]) or "").strip()
                key = (symbol, series)
                if key in seen:
                    issues.append(
                        ValidationIssue(
                            code="DUPLICATE_SYMBOL_SERIES",
                            severity=ValidationSeverity.ERROR,
                            message=f"Duplicate {symbol}/{series}",
                            row_number=row_number,
                        )
                    )
                seen.add(key)
                try:
                    open_ = float(row[fields["open"]])
                    high = float(row[fields["high"]])
                    low = float(row[fields["low"]])
                    close = float(row[fields["close"]])
                    volume = float(row[fields["volume"]])
                except (TypeError, ValueError, KeyError):
                    issues.append(
                        ValidationIssue(
                            code="INVALID_NUMERIC_VALUE",
                            severity=ValidationSeverity.ERROR,
                            message=f"Invalid OHLCV values for {symbol}/{series}",
                            row_number=row_number,
                        )
                    )
                    continue
                if high < max(open_, low, close) or low > min(open_, high, close):
                    issues.append(
                        ValidationIssue(
                            code="IMPOSSIBLE_OHLC",
                            severity=ValidationSeverity.ERROR,
                            message=f"Impossible OHLC values for {symbol}/{series}",
                            row_number=row_number,
                        )
                    )
                if volume < 0:
                    issues.append(
                        ValidationIssue(
                            code="NEGATIVE_VOLUME",
                            severity=ValidationSeverity.ERROR,
                            message=f"Negative volume for {symbol}/{series}",
                            row_number=row_number,
                        )
                    )
        return tuple(issues)

    @staticmethod
    def _detect_bhavcopy_schema(columns: frozenset[str]) -> str | None:
        if _LEGACY_REQUIRED_COLUMNS <= columns:
            return "legacy"
        if _UDIFF_REQUIRED_COLUMNS <= columns:
            return "udiff"
        return None

    @staticmethod
    def _schema_fields(schema: str) -> dict[str, str]:
        if schema == "legacy":
            return {
                "symbol": "SYMBOL",
                "series": "SERIES",
                "open": "OPEN",
                "high": "HIGH",
                "low": "LOW",
                "close": "CLOSE",
                "volume": "TOTTRDQTY",
            }
        return {
            "symbol": "TckrSymb",
            "series": "SctySrs",
            "open": "OpnPric",
            "high": "HghPric",
            "low": "LwPric",
            "close": "ClsPric",
            "volume": "TtlTradgVol",
        }

    def records(self) -> tuple[ManifestRecord, ...]:
        if not self.manifest_path.exists():
            return ()
        latest: dict[tuple[str, str, str], ManifestRecord] = {}
        for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            record = ManifestRecord(
                exchange=str(payload["exchange"]),
                dataset=ArchiveDataset(payload["dataset"]),
                trading_date=date.fromisoformat(payload["trading_date"]),
                source_url=str(payload["source_url"]),
                relative_path=str(payload["relative_path"]),
                status=ManifestStatus(payload["status"]),
                retrieved_at=(
                    datetime.fromisoformat(payload["retrieved_at"])
                    if payload.get("retrieved_at")
                    else None
                ),
                sha256=payload.get("sha256"),
                byte_size=payload.get("byte_size"),
                error=payload.get("error"),
            )
            key = (
                record.exchange,
                record.dataset.value,
                record.trading_date.isoformat(),
            )
            latest[key] = record
        return tuple(sorted(latest.values(), key=lambda item: item.trading_date))

    def export_status(self, output_dir: Path) -> tuple[Path, Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        records = self.records()
        json_path = output_dir / "historical_truth_status.json"
        csv_path = output_dir / "historical_truth_status.csv"
        markdown_path = output_dir / "historical_truth_status.md"
        payload = [self._serialise(record) for record in records]
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            fieldnames = (
                list(payload[0])
                if payload
                else [
                    "exchange",
                    "dataset",
                    "trading_date",
                    "source_url",
                    "relative_path",
                    "status",
                    "retrieved_at",
                    "sha256",
                    "byte_size",
                    "error",
                ]
            )
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(payload)
        lines = [
            "# Historical Truth Warehouse Status",
            "",
            f"Records: {len(records)}",
            "",
        ]
        lines.extend(
            [
                "| Date | Exchange | Dataset | Status | Bytes | Error |",
                "|---|---|---|---|---:|---|",
            ]
        )
        for record in records:
            lines.append(
                "| "
                + " | ".join(
                    (
                        record.trading_date.isoformat(),
                        record.exchange.upper(),
                        record.dataset.value,
                        record.status.value,
                        str(record.byte_size or ""),
                        (record.error or "").replace("|", "/"),
                    )
                )
                + " |"
            )
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return json_path, csv_path, markdown_path

    def _existing_record(self, request: ArchiveRequest) -> ManifestRecord | None:
        for record in reversed(self.records()):
            if (
                record.exchange == request.exchange
                and record.dataset == request.dataset
                and record.trading_date == request.trading_date
            ):
                return record
        return None

    def _append_manifest(self, record: ManifestRecord) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self._serialise(record), sort_keys=True) + "\n")

    def _failure_record(
        self,
        request: ArchiveRequest,
        status: ManifestStatus,
        error: str,
    ) -> ManifestRecord:
        return ManifestRecord(
            exchange=request.exchange,
            dataset=request.dataset,
            trading_date=request.trading_date,
            source_url=request.source_url,
            relative_path=str(request.relative_path),
            status=status,
            error=error,
        )

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        byte_size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                byte_size += len(chunk)
        return digest.hexdigest(), byte_size

    @staticmethod
    def _serialise(record: ManifestRecord) -> dict[str, object]:
        payload = asdict(record)
        payload["dataset"] = record.dataset.value
        payload["status"] = record.status.value
        payload["trading_date"] = record.trading_date.isoformat()
        payload["retrieved_at"] = (
            record.retrieved_at.isoformat() if record.retrieved_at else None
        )
        return payload
