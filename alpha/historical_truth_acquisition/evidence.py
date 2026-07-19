from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from alpha.historical_truth_acquisition.models import (
    DatasetEvidence,
    EvidenceEvent,
    json_value,
)


class EvidenceStore:
    """Append-only source evidence used by certification and restart recovery."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def events(self) -> tuple[EvidenceEvent, ...]:
        if not self.path.exists():
            return ()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("HTA evidence store must contain a JSON list")
        return tuple(_event(item) for item in payload)

    def append(self, event: EvidenceEvent) -> bool:
        indexed = {item.source_file_id: item for item in self.events()}
        existing = indexed.get(event.source_file_id)
        if existing is not None:
            if existing != event:
                raise ValueError("HTA source evidence is immutable after registration")
            return False
        indexed[event.source_file_id] = event
        self._write(tuple(indexed[key] for key in sorted(indexed)))
        return True

    def dataset_evidence(
        self,
        dataset_ids: tuple[str, ...],
        *,
        expected_sessions: dict[str, int | None] | None = None,
    ) -> tuple[DatasetEvidence, ...]:
        grouped: dict[str, list[EvidenceEvent]] = defaultdict(list)
        for event in self.events():
            grouped[event.dataset_id].append(event)
        expected = expected_sessions or {}
        return tuple(
            _summarise(
                dataset_id,
                tuple(grouped.get(dataset_id, ())),
                expected.get(dataset_id),
            )
            for dataset_id in dataset_ids
        )

    def _write(self, events: tuple[EvidenceEvent, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(
                [json_value(item) for item in events],
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


def _summarise(
    dataset_id: str,
    events: tuple[EvidenceEvent, ...],
    expected_sessions: int | None,
) -> DatasetEvidence:
    dates = tuple(sorted({item for event in events for item in event.observed_dates}))
    return DatasetEvidence(
        dataset_id=dataset_id,
        source_files=len(events),
        verified_files=sum(item.checksum_verified for item in events),
        accepted_records=sum(item.accepted_records for item in events),
        rejected_records=sum(item.rejected_records for item in events),
        duplicate_records=sum(item.duplicate_records for item in events),
        coverage_start=(None if not dates else dates[0]),
        coverage_end=(None if not dates else dates[-1]),
        observed_sessions=len(dates),
        expected_sessions=expected_sessions,
        source_checksums=tuple(sorted({item.checksum for item in events})),
        source_file_ids=tuple(sorted(item.source_file_id for item in events)),
        schema_fingerprints=tuple(sorted({item.schema_fingerprint for item in events})),
        unresolved_identity_records=sum(
            item.unresolved_identity_records for item in events
        ),
    )


def _event(value: object) -> EvidenceEvent:
    if not isinstance(value, dict):
        raise ValueError("HTA evidence event is invalid")
    raw_dates = value.get("observed_dates", [])
    if not isinstance(raw_dates, list):
        raise ValueError("HTA evidence dates are invalid")
    return EvidenceEvent(
        source_file_id=str(value["source_file_id"]),
        dataset_id=str(value["dataset_id"]),
        checksum=str(value["checksum"]),
        schema_fingerprint=str(value["schema_fingerprint"]),
        accepted_records=int(str(value["accepted_records"])),
        rejected_records=int(str(value["rejected_records"])),
        duplicate_records=int(str(value["duplicate_records"])),
        coverage_start=_optional_date(value.get("coverage_start")),
        coverage_end=_optional_date(value.get("coverage_end")),
        observed_dates=tuple(date.fromisoformat(str(item)) for item in raw_dates),
        checksum_verified=bool(value["checksum_verified"]),
        unresolved_identity_records=int(
            str(value.get("unresolved_identity_records", 0))
        ),
    )


def _optional_date(value: object) -> date | None:
    return None if value is None else date.fromisoformat(str(value))


__all__ = ["EvidenceStore"]
