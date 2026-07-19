"""Effective-dated sector history without current-classification backfill."""

from __future__ import annotations

from datetime import date

from alpha.point_in_time_universe.models import (
    EvidenceStatus,
    SectorMembershipRecord,
)


class SectorHistory:
    def __init__(self, records: tuple[SectorMembershipRecord, ...] = ()) -> None:
        self.records = tuple(
            sorted(
                records,
                key=lambda item: (
                    item.security_id,
                    item.interval.effective_from,
                    item.sector,
                ),
            )
        )
        self._validate_overlaps()

    def classification(
        self, security_id: str, as_of: date
    ) -> tuple[SectorMembershipRecord | None, EvidenceStatus]:
        matches = tuple(
            item
            for item in self.records
            if item.security_id == security_id and item.interval.covers(as_of)
        )
        if not matches:
            return None, EvidenceStatus.UNKNOWN
        if len(matches) > 1:
            return None, EvidenceStatus.CONFLICTED
        return matches[0], EvidenceStatus.KNOWN

    def _validate_overlaps(self) -> None:
        by_security: dict[str, list[SectorMembershipRecord]] = {}
        for record in self.records:
            by_security.setdefault(record.security_id, []).append(record)
        for security_id, records in by_security.items():
            ordered = sorted(records, key=lambda item: item.interval.effective_from)
            for previous, current in zip(ordered, ordered[1:], strict=False):
                previous_end = previous.interval.effective_to
                if (
                    previous_end is None
                    or current.interval.effective_from <= previous_end
                ):
                    raise ValueError(f"overlapping sector history for {security_id}")


__all__ = ["SectorHistory"]
