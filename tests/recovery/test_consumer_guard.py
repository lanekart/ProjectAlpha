"""Tests for fail-closed canonical replay consumer attestations."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from alpha.recovery.canonical_replay import (
    CanonicalReplayBar,
    CanonicalReplayStatus,
    canonical_replay_sha256,
)
from alpha.recovery.consumer_attestation import (
    CONSUMER_CONTRACT_VERSION,
    export_consumer_attestations,
)
from alpha.recovery.consumer_guard import CanonicalReplayConsumerGuard
from alpha.recovery.consumer_hash import (
    canonical_frame_sha256,
    stamp_canonical_frame,
)

_TRADE_DATE = date(2025, 1, 10)


def _row(
    security_id: str = "SEC-1",
    raw_symbol: str = "ALPHA",
    canonical_symbol: str = "NEWALPHA",
) -> dict[str, object]:
    return {
        "security_id": security_id,
        "raw_symbol": raw_symbol,
        "canonical_symbol": canonical_symbol,
        "symbol": canonical_symbol,
        "trade_date": _TRADE_DATE,
        "replay_as_of": _TRADE_DATE.isoformat(),
        "raw_open": 90,
        "raw_high": 110,
        "raw_low": 80,
        "raw_close": 100,
        "raw_volume": 1000,
        "adjusted_open": "90.00000000",
        "adjusted_high": "110.00000000",
        "adjusted_low": "80.00000000",
        "adjusted_close": "100.00000000",
        "adjusted_volume": "1000.00000000",
        "open": 90.0,
        "high": 110.0,
        "low": 80.0,
        "close": 100.0,
        "volume": 1000.0,
        "cumulative_price_factor": "1.00000000",
        "cumulative_volume_factor": "1.00000000",
        "applied_event_ids": (),
        "unresolved_event_ids": (),
        "replay_status": "READY",
        "recovery_version": "HTR-004-v1.0.0",
        "canonical_snapshot_sha256": "",
        "canonical_replay_enforced": True,
        "replay_contract_version": CONSUMER_CONTRACT_VERSION,
    }


def _canonical_bar(row: dict[str, object]) -> CanonicalReplayBar:
    return CanonicalReplayBar(
        security_id=str(row["security_id"]),
        raw_symbol=str(row["raw_symbol"]),
        canonical_symbol=str(row["canonical_symbol"]),
        trading_date=_TRADE_DATE,
        as_of=_TRADE_DATE,
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
        applied_event_ids=tuple(row["applied_event_ids"]),
        unresolved_event_ids=tuple(row["unresolved_event_ids"]),
        status=CanonicalReplayStatus(str(row["replay_status"])),
        recovery_version=str(row["recovery_version"]),
    )


def _stamped_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    snapshot_sha256 = canonical_replay_sha256(
        tuple(
            sorted(
                (_canonical_bar(row) for row in rows),
                key=lambda item: (
                    item.trading_date,
                    item.security_id,
                    item.raw_symbol,
                ),
            )
        )
    )
    for row in rows:
        row["canonical_snapshot_sha256"] = snapshot_sha256
    return stamp_canonical_frame(pd.DataFrame(rows))


def _frame() -> pd.DataFrame:
    return _stamped_frame([_row()])


def test_guard_attests_frame_and_hash_is_order_independent() -> None:
    rows = [
        _row(),
        _row("SEC-2", "BETA", "NEWBETA"),
    ]
    first = _stamped_frame(rows)
    second = _stamped_frame(list(reversed([_row(), _row("SEC-2", "BETA", "NEWBETA")])))
    guard = CanonicalReplayConsumerGuard()

    first_attestation = guard.validate(first)
    second_attestation = guard.validate(second)

    assert first_attestation == second_attestation
    assert first_attestation.row_count == 2
    assert first_attestation.security_ids == ("SEC-1", "SEC-2")
    assert first_attestation.canonical_replay_enforced
    assert len(first_attestation.attestation_sha256) == 64
    assert canonical_frame_sha256(first) == canonical_frame_sha256(second)


def test_guard_rejects_missing_governance_columns() -> None:
    frame = _frame().drop(columns=["canonical_snapshot_sha256"])

    with pytest.raises(ValueError, match="consumer contract missing"):
        CanonicalReplayConsumerGuard().validate(frame)


def test_guard_rejects_tampered_consumer_price() -> None:
    frame = _frame()
    frame.loc[0, "close"] = 101.0

    with pytest.raises(ValueError, match="does not match exact adjusted"):
        CanonicalReplayConsumerGuard().validate(frame)


def test_guard_rejects_restamped_snapshot_tampering() -> None:
    frame = _frame()
    frame.loc[0, "adjusted_close"] = "101.00000000"
    frame.loc[0, "close"] = 101.0
    frame = stamp_canonical_frame(frame)

    with pytest.raises(ValueError, match="snapshot digest does not match content"):
        CanonicalReplayConsumerGuard().validate(frame)


def test_guard_rejects_unresolved_or_non_ready_rows() -> None:
    row = _row()
    row["replay_status"] = "QUARANTINED"
    row["unresolved_event_ids"] = ("SEC-1:RIGHTS:2025-01-15",)
    frame = _stamped_frame([row])

    with pytest.raises(ValueError, match="non-ready rows"):
        CanonicalReplayConsumerGuard().validate(frame)


def test_attestation_exports_are_deterministic(tmp_path: Path) -> None:
    attestation = CanonicalReplayConsumerGuard().validate(_frame())

    paths = export_consumer_attestations((attestation,), tmp_path)

    assert tuple(path.name for path in paths) == (
        "canonical_replay_attestations.json",
        "canonical_replay_attestations.csv",
        "canonical_replay_attestations.md",
    )
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload[0]["canonical_replay_enforced"] is True
    assert payload[0]["canonical_frame_sha256"] == attestation.canonical_frame_sha256
    assert attestation.attestation_sha256 in paths[2].read_text(encoding="utf-8")
