"""Point-in-time index membership with explicit unknown evidence windows."""

from __future__ import annotations

from datetime import date

from alpha.point_in_time_universe.models import (
    SUPPORTED_INDICES,
    ConfidenceGrade,
    EvidenceStatus,
    IndexEvidenceWindow,
    IndexMembershipRecord,
    IndexMembershipSnapshot,
    normalize_index,
)


class IndexMembershipHistory:
    def __init__(
        self,
        *,
        records: tuple[IndexMembershipRecord, ...] = (),
        evidence_windows: tuple[IndexEvidenceWindow, ...] = (),
    ) -> None:
        self.records = tuple(
            sorted(
                records,
                key=lambda item: (
                    item.index_name,
                    item.interval.effective_from,
                    item.security_id,
                ),
            )
        )
        self.evidence_windows = tuple(
            sorted(
                evidence_windows,
                key=lambda item: (item.index_name, item.interval.effective_from),
            )
        )

    def snapshot(
        self, index_name: str, as_of: date, *, previous_date: date | None = None
    ) -> IndexMembershipSnapshot:
        normalized = normalize_index(index_name)
        windows = tuple(
            item
            for item in self.evidence_windows
            if item.index_name == normalized and item.interval.covers(as_of)
        )
        if not windows:
            return IndexMembershipSnapshot(
                as_of=as_of,
                index_name=normalized,
                members=(),
                additions=(),
                removals=(),
                source=None,
                confidence=ConfidenceGrade.UNKNOWN,
                status=EvidenceStatus.UNKNOWN,
            )
        members = self.members(normalized, as_of)
        previous = (
            () if previous_date is None else self.members(normalized, previous_date)
        )
        sources = tuple(sorted({item.source for item in windows}))
        confidence = min((item.confidence for item in windows), key=_confidence_order)
        return IndexMembershipSnapshot(
            as_of=as_of,
            index_name=normalized,
            members=members,
            additions=tuple(sorted(set(members) - set(previous))),
            removals=tuple(sorted(set(previous) - set(members))),
            source=", ".join(sources),
            confidence=confidence,
            status=EvidenceStatus.KNOWN,
        )

    def members(self, index_name: str, as_of: date) -> tuple[str, ...]:
        normalized = normalize_index(index_name)
        return tuple(
            sorted(
                item.security_id
                for item in self.records
                if item.index_name == normalized and item.interval.covers(as_of)
            )
        )

    def all_snapshots(self, as_of: date) -> tuple[IndexMembershipSnapshot, ...]:
        return tuple(
            self.snapshot(index_name, as_of) for index_name in SUPPORTED_INDICES
        )


def _confidence_order(value: ConfidenceGrade) -> int:
    return {
        ConfidenceGrade.UNKNOWN: 0,
        ConfidenceGrade.LOW: 1,
        ConfidenceGrade.MEDIUM: 2,
        ConfidenceGrade.HIGH: 3,
        ConfidenceGrade.AUTHORITATIVE: 4,
    }[value]


__all__ = ["IndexMembershipHistory"]
