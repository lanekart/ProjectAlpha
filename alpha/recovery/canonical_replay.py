"""Governed point-in-time canonical replay boundary for historical OHLCV."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from .corporate_actions import (
    CorporateActionAdjustmentEngine,
    CorporateActionBar,
    CorporateActionStatus,
    CorporateActionTimeline,
)


class CanonicalReplayStatus(StrEnum):
    """Whether a historical observation is safe for governed replay."""

    READY = "READY"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True, slots=True)
class CanonicalReplayBar:
    """Immutable raw and adjusted replay observation with complete lineage."""

    security_id: str
    raw_symbol: str
    canonical_symbol: str
    trading_date: date
    as_of: date
    raw_open: Decimal
    raw_high: Decimal
    raw_low: Decimal
    raw_close: Decimal
    raw_volume: Decimal
    adjusted_open: Decimal
    adjusted_high: Decimal
    adjusted_low: Decimal
    adjusted_close: Decimal
    adjusted_volume: Decimal
    cumulative_price_factor: Decimal
    cumulative_volume_factor: Decimal
    applied_event_ids: tuple[str, ...]
    unresolved_event_ids: tuple[str, ...]
    status: CanonicalReplayStatus
    recovery_version: str

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError("security_id must not be empty")
        if self.trading_date > self.as_of:
            raise ValueError("trading_date cannot be after replay as_of date")
        if self.cumulative_price_factor <= 0 or self.cumulative_volume_factor <= 0:
            raise ValueError("canonical replay factors must be positive")
        if self.status is CanonicalReplayStatus.READY and self.unresolved_event_ids:
            raise ValueError("ready replay bars cannot contain unresolved events")


@dataclass(frozen=True, slots=True)
class CanonicalReplayAudit:
    """Deterministic coverage and quarantine summary for one replay build."""

    bars_examined: int
    bars_ready: int
    bars_quarantined: int
    bars_adjusted: int
    securities_examined: int
    unresolved_event_ids: tuple[str, ...]
    snapshot_sha256: str
    passed: bool


class CanonicalReplayBuilder:
    """Build canonical replay bars and fail closed on unresolved material actions."""

    recovery_version = "HTR-004-v1.0.0"

    def __init__(self, timeline: CorporateActionTimeline) -> None:
        self._timeline = timeline
        self._adjuster = CorporateActionAdjustmentEngine(timeline)

    def build_bar(self, bar: CorporateActionBar, *, as_of: date) -> CanonicalReplayBar:
        if bar.trading_date > as_of:
            raise ValueError("cannot replay a bar after the replay as_of date")

        adjusted = self._adjuster.adjust_bar(bar, as_of=as_of)
        unresolved = tuple(
            event.event_id
            for event in self._timeline.for_security(bar.security_id, as_of=as_of)
            if event.status is CorporateActionStatus.UNRESOLVED
            and bar.trading_date < event.effective_date
        )
        status = (
            CanonicalReplayStatus.QUARANTINED
            if unresolved
            else CanonicalReplayStatus.READY
        )
        return CanonicalReplayBar(
            security_id=bar.security_id,
            raw_symbol=bar.symbol,
            canonical_symbol=adjusted.symbol,
            trading_date=bar.trading_date,
            as_of=as_of,
            raw_open=bar.open,
            raw_high=bar.high,
            raw_low=bar.low,
            raw_close=bar.close,
            raw_volume=bar.volume,
            adjusted_open=adjusted.open,
            adjusted_high=adjusted.high,
            adjusted_low=adjusted.low,
            adjusted_close=adjusted.close,
            adjusted_volume=adjusted.volume,
            cumulative_price_factor=adjusted.cumulative_price_factor,
            cumulative_volume_factor=adjusted.cumulative_volume_factor,
            applied_event_ids=adjusted.applied_event_ids,
            unresolved_event_ids=unresolved,
            status=status,
            recovery_version=self.recovery_version,
        )

    def build(
        self,
        bars: Iterable[CorporateActionBar],
        *,
        as_of: date,
    ) -> tuple[CanonicalReplayBar, ...]:
        """Build a stable replay set sorted by date, security, and raw symbol."""

        source = sorted(
            bars,
            key=lambda item: (item.trading_date, item.security_id, item.symbol),
        )
        return tuple(self.build_bar(bar, as_of=as_of) for bar in source)

    def audit(
        self,
        bars: Iterable[CorporateActionBar],
        *,
        as_of: date,
    ) -> CanonicalReplayAudit:
        replay = self.build(bars, as_of=as_of)
        ready = tuple(
            item
            for item in replay
            if item.status is CanonicalReplayStatus.READY
        )
        quarantined = tuple(
            item
            for item in replay
            if item.status is CanonicalReplayStatus.QUARANTINED
        )
        adjusted = tuple(item for item in replay if item.applied_event_ids)
        unresolved = tuple(
            sorted(
                {
                    event_id
                    for item in replay
                    for event_id in item.unresolved_event_ids
                }
            )
        )
        return CanonicalReplayAudit(
            bars_examined=len(replay),
            bars_ready=len(ready),
            bars_quarantined=len(quarantined),
            bars_adjusted=len(adjusted),
            securities_examined=len({item.security_id for item in replay}),
            unresolved_event_ids=unresolved,
            snapshot_sha256=canonical_replay_sha256(replay),
            passed=not quarantined,
        )


def canonical_replay_sha256(bars: Iterable[CanonicalReplayBar]) -> str:
    """Return a deterministic content digest for immutable replay snapshots."""

    payload = [
        {
            key: str(value) if isinstance(value, (date, Decimal)) else value
            for key, value in asdict(bar).items()
        }
        for bar in bars
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
