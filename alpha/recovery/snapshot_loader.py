"""Verified snapshot-backed source for governed canonical replay consumers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .canonical_replay import (
    CanonicalReplayBar,
    CanonicalReplayStatus,
    canonical_replay_sha256,
)
from .replay_snapshot import (
    CanonicalReplaySnapshot,
    CanonicalReplaySnapshotRepository,
)


@dataclass(frozen=True, slots=True)
class CanonicalReplaySnapshotLoad:
    """Exact verified snapshot selection for one governed trading date."""

    trade_date: date
    as_of: date
    snapshot_sha256: str
    selected_sha256: str
    recovery_version: str
    bars: tuple[CanonicalReplayBar, ...]

    def __post_init__(self) -> None:
        if self.trade_date > self.as_of:
            raise ValueError("trade_date cannot be after snapshot as_of")
        if not self.bars:
            raise ValueError("snapshot selection must contain at least one bar")
        if any(bar.trading_date != self.trade_date for bar in self.bars):
            raise ValueError("snapshot selection contains a different trading date")
        if any(bar.as_of != self.as_of for bar in self.bars):
            raise ValueError("snapshot selection contains a different as_of date")
        if canonical_replay_sha256(self.bars) != self.selected_sha256:
            raise ValueError("selected_sha256 does not match selected replay bars")


class CanonicalReplaySnapshotLoader:
    """Load exact immutable replay snapshots and fail closed before consumption."""

    def __init__(
        self,
        repository: CanonicalReplaySnapshotRepository,
        *,
        expected_recovery_version: str = "HTR-004-v1.0.0",
    ) -> None:
        if not expected_recovery_version.strip():
            raise ValueError("expected_recovery_version must not be empty")
        self._repository = repository
        self._expected_recovery_version = expected_recovery_version

    def load(
        self,
        *,
        trade_date: date,
        as_of: date,
    ) -> CanonicalReplaySnapshotLoad:
        """Load the exact as-of snapshot and release only the requested date."""

        if trade_date > as_of:
            raise ValueError("trade_date cannot be after snapshot as_of")
        snapshot = self._repository.read(as_of)
        self._validate_snapshot(snapshot)
        selected = tuple(
            bar for bar in snapshot.bars if bar.trading_date == trade_date
        )
        if not selected:
            raise FileNotFoundError(
                "canonical replay snapshot contains no bars for "
                f"{trade_date.isoformat()} as of {as_of.isoformat()}"
            )
        quarantined = tuple(
            bar for bar in selected if bar.status is CanonicalReplayStatus.QUARANTINED
        )
        if quarantined:
            event_ids = tuple(
                sorted(
                    {
                        event_id
                        for bar in quarantined
                        for event_id in bar.unresolved_event_ids
                    }
                )
            )
            rendered = ", ".join(event_ids) or "unknown unresolved action"
            raise ValueError(
                "canonical replay snapshot selection is quarantined: " + rendered
            )
        return CanonicalReplaySnapshotLoad(
            trade_date=trade_date,
            as_of=as_of,
            snapshot_sha256=snapshot.snapshot_sha256,
            selected_sha256=canonical_replay_sha256(selected),
            recovery_version=snapshot.recovery_version,
            bars=selected,
        )

    def _validate_snapshot(self, snapshot: CanonicalReplaySnapshot) -> None:
        if snapshot.recovery_version != self._expected_recovery_version:
            raise ValueError(
                "canonical replay snapshot recovery version mismatch: "
                f"expected {self._expected_recovery_version}, "
                f"found {snapshot.recovery_version}"
            )
        versions = {bar.recovery_version for bar in snapshot.bars}
        if versions != {snapshot.recovery_version}:
            rendered = ", ".join(sorted(versions)) or "<EMPTY>"
            raise ValueError(
                "canonical replay snapshot contains mixed recovery versions: "
                + rendered
            )
        if any(bar.as_of != snapshot.as_of for bar in snapshot.bars):
            raise ValueError("canonical replay snapshot contains mixed as_of dates")
        if any(bar.trading_date > snapshot.as_of for bar in snapshot.bars):
            raise ValueError("canonical replay snapshot contains future bars")
        if any(
            bar.status is CanonicalReplayStatus.READY and bar.unresolved_event_ids
            for bar in snapshot.bars
        ):
            raise ValueError("ready snapshot bars contain unresolved event lineage")
