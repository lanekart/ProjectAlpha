"""Immutable storage and integrity verification for canonical replay snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

from .canonical_replay import (
    CanonicalReplayBar,
    CanonicalReplayStatus,
    canonical_replay_sha256,
)


@dataclass(frozen=True, slots=True)
class CanonicalReplaySnapshot:
    """Immutable point-in-time collection of canonical replay observations."""

    as_of: date
    bars: tuple[CanonicalReplayBar, ...]
    snapshot_sha256: str
    recovery_version: str = "HTR-004-v1.0.0"

    def __post_init__(self) -> None:
        expected = canonical_replay_sha256(self.bars)
        if self.snapshot_sha256 != expected:
            raise ValueError("snapshot_sha256 does not match replay content")
        if any(bar.as_of != self.as_of for bar in self.bars):
            raise ValueError("all replay bars must use the snapshot as_of date")
        keys = tuple(
            (bar.security_id, bar.trading_date, bar.raw_symbol) for bar in self.bars
        )
        if len(keys) != len(set(keys)):
            raise ValueError("canonical replay snapshot contains duplicate bars")
        if keys != tuple(sorted(keys, key=lambda item: (item[1], item[0], item[2]))):
            raise ValueError(
                "canonical replay snapshot bars must be deterministically sorted"
            )

    @classmethod
    def build(
        cls,
        bars: Iterable[CanonicalReplayBar],
        *,
        as_of: date,
    ) -> CanonicalReplaySnapshot:
        ordered = tuple(
            sorted(
                bars,
                key=lambda item: (
                    item.trading_date,
                    item.security_id,
                    item.raw_symbol,
                ),
            )
        )
        return cls(
            as_of=as_of,
            bars=ordered,
            snapshot_sha256=canonical_replay_sha256(ordered),
        )


class CanonicalReplaySnapshotRepository:
    """Persist immutable replay snapshots with deterministic integrity metadata."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def write(self, snapshot: CanonicalReplaySnapshot) -> Path:
        directory = self._root / snapshot.as_of.isoformat()
        data_path = directory / "replay.jsonl"
        manifest_path = directory / "manifest.json"
        data = _encode_bars(snapshot.bars)
        manifest = _manifest(snapshot)

        if directory.exists():
            if not data_path.exists() or not manifest_path.exists():
                raise ValueError("existing replay snapshot directory is incomplete")
            if data_path.read_text(encoding="utf-8") != data:
                raise ValueError("immutable replay snapshot content already differs")
            existing_manifest = manifest_path.read_text(encoding="utf-8")
            if existing_manifest != manifest:
                raise ValueError("immutable replay snapshot manifest already differs")
            return directory

        directory.mkdir(parents=True, exist_ok=False)
        _atomic_write(data_path, data)
        _atomic_write(manifest_path, manifest)
        return directory

    def read(self, as_of: date) -> CanonicalReplaySnapshot:
        directory = self._root / as_of.isoformat()
        data_path = directory / "replay.jsonl"
        manifest_path = directory / "manifest.json"
        if not data_path.exists() or not manifest_path.exists():
            raise FileNotFoundError(f"canonical replay snapshot not found for {as_of}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bars = _decode_bars(data_path.read_text(encoding="utf-8"))
        snapshot = CanonicalReplaySnapshot(
            as_of=date.fromisoformat(str(manifest["as_of"])),
            bars=bars,
            snapshot_sha256=str(manifest["snapshot_sha256"]),
            recovery_version=str(manifest["recovery_version"]),
        )
        if snapshot.as_of != as_of:
            raise ValueError("replay snapshot manifest date does not match its path")
        if int(manifest["bar_count"]) != len(snapshot.bars):
            raise ValueError("replay snapshot manifest bar count is invalid")
        return snapshot

    def available_dates(self) -> tuple[date, ...]:
        if not self._root.exists():
            return ()
        dates: list[date] = []
        for path in self._root.iterdir():
            if not path.is_dir():
                continue
            try:
                dates.append(date.fromisoformat(path.name))
            except ValueError:
                continue
        return tuple(sorted(dates))

    def latest_on_or_before(self, as_of: date) -> CanonicalReplaySnapshot:
        eligible = tuple(item for item in self.available_dates() if item <= as_of)
        if not eligible:
            raise FileNotFoundError(
                f"no canonical replay snapshot available on or before {as_of}"
            )
        return self.read(eligible[-1])


def _manifest(snapshot: CanonicalReplaySnapshot) -> str:
    payload = {
        "as_of": snapshot.as_of.isoformat(),
        "bar_count": len(snapshot.bars),
        "recovery_version": snapshot.recovery_version,
        "snapshot_sha256": snapshot.snapshot_sha256,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _encode_bars(bars: Iterable[CanonicalReplayBar]) -> str:
    lines = [json.dumps(_bar_payload(bar), sort_keys=True) for bar in bars]
    return "".join(f"{line}\n" for line in lines)


def _bar_payload(bar: CanonicalReplayBar) -> dict[str, object]:
    payload = asdict(bar)
    for field in ("trading_date", "as_of"):
        payload[field] = str(payload[field])
    for field in (
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "raw_volume",
        "adjusted_open",
        "adjusted_high",
        "adjusted_low",
        "adjusted_close",
        "adjusted_volume",
        "cumulative_price_factor",
        "cumulative_volume_factor",
    ):
        payload[field] = str(payload[field])
    payload["status"] = str(bar.status)
    payload["applied_event_ids"] = list(bar.applied_event_ids)
    payload["unresolved_event_ids"] = list(bar.unresolved_event_ids)
    return payload


def _decode_bars(content: str) -> tuple[CanonicalReplayBar, ...]:
    bars: list[CanonicalReplayBar] = []
    for line in content.splitlines():
        if not line.strip():
            continue
        row = cast(dict[str, object], json.loads(line))
        bars.append(_bar_from_payload(row))
    return tuple(bars)


def _bar_from_payload(row: dict[str, object]) -> CanonicalReplayBar:
    return CanonicalReplayBar(
        security_id=str(row["security_id"]),
        raw_symbol=str(row["raw_symbol"]),
        canonical_symbol=str(row["canonical_symbol"]),
        trading_date=date.fromisoformat(str(row["trading_date"])),
        as_of=date.fromisoformat(str(row["as_of"])),
        raw_open=Decimal(str(row["raw_open"])),
        raw_high=Decimal(str(row["raw_high"])),
        raw_low=Decimal(str(row["raw_low"])),
        raw_close=Decimal(str(row["raw_close"])),
        raw_volume=Decimal(str(row["raw_volume"])),
        adjusted_open=Decimal(str(row["adjusted_open"])),
        adjusted_high=Decimal(str(row["adjusted_high"])),
        adjusted_low=Decimal(str(row["adjusted_low"])),
        adjusted_close=Decimal(str(row["adjusted_close"])),
        adjusted_volume=Decimal(str(row["adjusted_volume"])),
        cumulative_price_factor=Decimal(str(row["cumulative_price_factor"])),
        cumulative_volume_factor=Decimal(str(row["cumulative_volume_factor"])),
        applied_event_ids=_string_tuple(row["applied_event_ids"]),
        unresolved_event_ids=_string_tuple(row["unresolved_event_ids"]),
        status=CanonicalReplayStatus(str(row["status"])),
        recovery_version=str(row["recovery_version"]),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("replay event lineage must be encoded as a list")
    return tuple(str(item) for item in value)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
