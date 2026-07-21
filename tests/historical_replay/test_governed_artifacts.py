"""Tests for governed replay recovery artifact loading."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from alpha.historical_replay.governed_artifacts import load_governed_replay_inputs
from alpha.recovery.corporate_actions import CorporateActionStatus


def _write_csv(
    path: Path,
    *,
    fieldnames: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _identity_csv(path: Path) -> None:
    _write_csv(
        path,
        fieldnames=(
            "record_key",
            "security_id",
            "symbol",
            "exchange",
            "effective_from",
            "effective_to",
            "recovery_version",
        ),
        rows=[
            {
                "record_key": "SEC-1",
                "security_id": "SEC-1",
                "symbol": "NEWALPHA",
                "exchange": "NSE",
                "effective_from": "2020-01-01",
                "effective_to": "",
                "recovery_version": "HTR-002-v1.0.0",
            }
        ],
    )


def _action_csv(path: Path, *, unresolved: bool = False) -> None:
    rows: list[dict[str, object]] = [
        {
            "event_id": "SEC-1:SYMBOL_CHANGE:2024-01-01",
            "security_id": "SEC-1",
            "symbol": "NEWALPHA",
            "action_type": "SYMBOL_CHANGE",
            "effective_date": "2024-01-01",
            "announced_at": "2023-12-15",
            "price_factor": "",
            "volume_factor": "",
            "old_symbol": "ALPHA",
            "new_symbol": "NEWALPHA",
            "cash_amount": "",
            "ratio_numerator": "",
            "ratio_denominator": "",
            "status": "RESOLVED",
            "confidence": "0.99",
            "evidence_ids": json.dumps(["corporate_action:0"]),
            "source": "HTR-003-test",
        }
    ]
    if unresolved:
        rows.append(
            {
                "event_id": "SEC-1:RIGHTS:2025-01-15",
                "security_id": "SEC-1",
                "symbol": "NEWALPHA",
                "action_type": "RIGHTS",
                "effective_date": "2025-01-15",
                "announced_at": "2025-01-01",
                "price_factor": "",
                "volume_factor": "",
                "old_symbol": "",
                "new_symbol": "",
                "cash_amount": "",
                "ratio_numerator": "",
                "ratio_denominator": "",
                "status": "UNRESOLVED",
                "confidence": "0",
                "evidence_ids": json.dumps(["corporate_action:1"]),
                "source": "HTR-003-test",
            }
        )
    _write_csv(
        path,
        fieldnames=(
            "event_id",
            "security_id",
            "symbol",
            "action_type",
            "effective_date",
            "announced_at",
            "price_factor",
            "volume_factor",
            "old_symbol",
            "new_symbol",
            "cash_amount",
            "ratio_numerator",
            "ratio_denominator",
            "status",
            "confidence",
            "evidence_ids",
            "source",
        ),
        rows=rows,
    )


def test_loader_derives_historical_aliases_from_symbol_changes(tmp_path: Path) -> None:
    identity_path = tmp_path / "canonical_preview.csv"
    action_path = tmp_path / "canonical_timeline.csv"
    _identity_csv(identity_path)
    _action_csv(action_path)

    inputs = load_governed_replay_inputs(
        identity_path=identity_path,
        corporate_action_path=action_path,
    )

    old_identity = inputs.identities.resolve(
        "ALPHA",
        trading_date=date(2023, 12, 29),
        exchange="NSE",
    )
    current_identity = inputs.identities.resolve(
        "NEWALPHA",
        trading_date=date(2025, 1, 10),
        exchange="NSE",
    )
    assert old_identity is not None
    assert current_identity is not None
    assert old_identity.security_id == current_identity.security_id == "SEC-1"
    assert old_identity.historical_symbols == ("ALPHA",)
    assert old_identity.evidence_ids == ()
    assert len(inputs.actions.events) == 1
    assert inputs.actions.events[0].evidence_ids == ("corporate_action:0",)


def test_input_manifest_is_deterministic_and_source_backed(tmp_path: Path) -> None:
    identity_path = tmp_path / "identities.csv"
    action_path = tmp_path / "actions.csv"
    _identity_csv(identity_path)
    _action_csv(action_path)

    first = load_governed_replay_inputs(
        identity_path=identity_path,
        corporate_action_path=action_path,
    )
    second = load_governed_replay_inputs(
        identity_path=identity_path,
        corporate_action_path=action_path,
    )

    assert first.manifest == second.manifest
    assert first.manifest.manifest_sha256 == second.manifest.manifest_sha256
    assert first.manifest.identity_count == 1
    assert first.manifest.corporate_action_count == 1
    assert first.manifest.security_ids == ("SEC-1",)
    assert first.manifest.identity_sha256 != first.manifest.corporate_action_sha256


def test_loader_records_unresolved_actions_without_suppressing_them(
    tmp_path: Path,
) -> None:
    identity_path = tmp_path / "identities.csv"
    action_path = tmp_path / "actions.csv"
    _identity_csv(identity_path)
    _action_csv(action_path, unresolved=True)

    inputs = load_governed_replay_inputs(
        identity_path=identity_path,
        corporate_action_path=action_path,
    )

    assert inputs.manifest.unresolved_action_ids == (
        "SEC-1:RIGHTS:2025-01-15",
    )
    assert inputs.actions.events[-1].status is CorporateActionStatus.UNRESOLVED


def test_loader_accepts_json_artifacts_and_empty_action_list(tmp_path: Path) -> None:
    identity_path = tmp_path / "identities.json"
    action_path = tmp_path / "actions.json"
    identity_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "security_id": "SEC-1",
                        "symbol": "ALPHA",
                        "exchange": "NSE",
                        "historical_symbols": ["OLDALPHA"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    action_path.write_text(json.dumps({"records": []}), encoding="utf-8")

    inputs = load_governed_replay_inputs(
        identity_path=identity_path,
        corporate_action_path=action_path,
    )

    assert inputs.identities.resolve(
        "OLDALPHA",
        trading_date=date(2020, 1, 1),
        exchange="NSE",
    ) is not None
    assert inputs.actions.events == ()
    assert inputs.manifest.corporate_action_count == 0


def test_loader_fails_closed_on_missing_or_invalid_artifacts(tmp_path: Path) -> None:
    identity_path = tmp_path / "identities.csv"
    action_path = tmp_path / "actions.csv"
    _identity_csv(identity_path)

    with pytest.raises(FileNotFoundError):
        load_governed_replay_inputs(
            identity_path=identity_path,
            corporate_action_path=action_path,
        )

    action_path.write_text("not-json", encoding="utf-8")
    invalid_identity = tmp_path / "identities.json"
    invalid_identity.write_text(json.dumps({"records": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="identity artifact contains no records"):
        load_governed_replay_inputs(
            identity_path=invalid_identity,
            corporate_action_path=action_path,
        )
