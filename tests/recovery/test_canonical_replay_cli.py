"""Tests for the standalone canonical replay verification CLI."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from alpha.recovery.canonical_replay import CanonicalReplayBar, CanonicalReplayStatus
from alpha.recovery.replay_snapshot import (
    CanonicalReplaySnapshot,
    CanonicalReplaySnapshotRepository,
)
from typer.testing import CliRunner

from alpha.recovery.__main__ import app

_AS_OF = date(2025, 1, 15)


def _snapshot() -> CanonicalReplaySnapshot:
    bar = CanonicalReplayBar(
        security_id="SEC-1",
        raw_symbol="ALPHA",
        canonical_symbol="ALPHA",
        trading_date=date(2025, 1, 10),
        as_of=_AS_OF,
        raw_open=Decimal("100"),
        raw_high=Decimal("110"),
        raw_low=Decimal("90"),
        raw_close=Decimal("104"),
        raw_volume=Decimal("1000"),
        adjusted_open=Decimal("100"),
        adjusted_high=Decimal("110"),
        adjusted_low=Decimal("90"),
        adjusted_close=Decimal("104"),
        adjusted_volume=Decimal("1000"),
        cumulative_price_factor=Decimal("1"),
        cumulative_volume_factor=Decimal("1"),
        applied_event_ids=(),
        unresolved_event_ids=(),
        status=CanonicalReplayStatus.READY,
        recovery_version="HTR-004-v1.0.0",
    )
    return CanonicalReplaySnapshot.build((bar,), as_of=_AS_OF)


def test_cli_verifies_snapshot_and_exports_artifacts(tmp_path: Path) -> None:
    repository = CanonicalReplaySnapshotRepository(tmp_path / "snapshots")
    repository.write(_snapshot())
    output = tmp_path / "verification"

    result = CliRunner().invoke(
        app,
        [
            "verify-snapshot",
            "--root",
            str(tmp_path / "snapshots"),
            "--as-of",
            _AS_OF.isoformat(),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["integrity_verified"] is True
    assert payload["governed_replay_ready"] is True
    assert (output / "snapshot_verification.json").exists()
    assert (output / "snapshot_verification.md").exists()


def test_cli_lists_available_snapshots(tmp_path: Path) -> None:
    repository = CanonicalReplaySnapshotRepository(tmp_path)
    repository.write(_snapshot())

    result = CliRunner().invoke(app, ["list-snapshots", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert result.stdout.strip() == _AS_OF.isoformat()
