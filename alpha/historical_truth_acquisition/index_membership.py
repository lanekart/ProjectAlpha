from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from alpha.historical_truth_acquisition.identity import resolve_symbol
from alpha.historical_truth_acquisition.models import (
    ConfidenceGrade,
    IndexMembershipRecord,
    json_value,
)
from alpha.market_truth.warehouse.archive_vault import source_payload
from alpha.market_truth.warehouse.models import IdentityRecord


class IndexMembershipRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self) -> tuple[IndexMembershipRecord, ...]:
        if not self.path.exists():
            return ()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("HTA index membership store must contain a JSON list")
        return tuple(_record(item) for item in payload)

    def append(self, records: tuple[IndexMembershipRecord, ...]) -> int:
        indexed = {_key(item): item for item in self.records()}
        added = 0
        for record in records:
            key = _key(record)
            existing = indexed.get(key)
            if existing is not None and existing != record:
                raise ValueError("historical membership evidence cannot be rewritten")
            if existing is None:
                indexed[key] = record
                added += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(
                [json_value(indexed[key]) for key in sorted(indexed)],
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)
        return added


def parse_membership_file(
    path: Path,
    *,
    source_file_id: str,
    identities: tuple[IdentityRecord, ...],
) -> tuple[tuple[IndexMembershipRecord, ...], tuple[str, ...], int]:
    _, raw = source_payload(path)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="strict")))
    if reader.fieldnames is None:
        raise ValueError("historical membership source has no header")
    rows = tuple(
        {_column(key): value.strip() for key, value in row.items() if key is not None}
        for row in reader
    )
    records: list[IndexMembershipRecord] = []
    issues: list[str] = []
    unresolved = 0
    for row_number, row in enumerate(rows, start=2):
        try:
            index_name = _value(row, "index", "indexname").upper()
            effective = date.fromisoformat(
                _value(row, "effectivedate", "date", "rebalanceeffectivedate")
            )
            symbol = _value(row, "symbol", "constituent", "ticker").upper()
            if not index_name or not symbol:
                raise ValueError("index and symbol are required")
            isin = _optional(_value(row, "isin"))
            security_id, confidence, resolved = resolve_symbol(
                identities,
                symbol=symbol,
                effective_date=effective,
                isin=isin,
            )
            unresolved += int(not resolved)
            change = (_value(row, "change", "action") or "MEMBER").upper()
            is_member = _boolean(_value(row, "ismember", "member"), change)
            complete_snapshot = _truthy(
                _value(row, "completesnapshot", "iscompletesnapshot")
            )
            records.append(
                IndexMembershipRecord(
                    index_name=index_name,
                    effective_date=effective,
                    alpha_security_id=security_id,
                    symbol=symbol,
                    isin=isin,
                    change=change,
                    is_member=is_member,
                    complete_snapshot=complete_snapshot,
                    source_file_id=source_file_id,
                    source="NSE_INDICES_OFFICIAL_FILE",
                    confidence=confidence,
                )
            )
        except (KeyError, ValueError) as error:
            issues.append(f"row {row_number}: {error}")
    return tuple(records), tuple(issues), unresolved


def _record(value: object) -> IndexMembershipRecord:
    if not isinstance(value, dict):
        raise ValueError("HTA membership record is invalid")
    return IndexMembershipRecord(
        index_name=str(value["index_name"]),
        effective_date=date.fromisoformat(str(value["effective_date"])),
        alpha_security_id=str(value["alpha_security_id"]),
        symbol=str(value["symbol"]),
        isin=None if value.get("isin") is None else str(value["isin"]),
        change=str(value["change"]),
        is_member=bool(value["is_member"]),
        complete_snapshot=bool(value["complete_snapshot"]),
        source_file_id=str(value["source_file_id"]),
        source=str(value["source"]),
        confidence=ConfidenceGrade(str(value["confidence"])),
    )


def _key(record: IndexMembershipRecord) -> tuple[str, date, str, str]:
    return (
        record.index_name,
        record.effective_date,
        record.alpha_security_id,
        record.source_file_id,
    )


def _column(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


def _value(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(_column(name), "")
        if value:
            return value
    return ""


def _optional(value: str) -> str | None:
    return value.upper() if value else None


def _truthy(value: str) -> bool:
    return value.strip().upper() in {"1", "TRUE", "YES", "Y"}


def _boolean(value: str, change: str) -> bool:
    if value:
        return _truthy(value)
    return change not in {"REMOVE", "REMOVAL", "DELETED", "EXIT"}


__all__ = ["IndexMembershipRepository", "parse_membership_file"]
