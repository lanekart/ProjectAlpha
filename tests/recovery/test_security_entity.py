"""Deterministic tests for security entity recovery."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from alpha.recovery import (
    RecoveryContext,
    SecurityEntityRecoveryEngine,
    export_security_entity_recovery,
)


def _context(tmp_path: Path, master: Path, listing: Path | None = None) -> RecoveryContext:
    parameters: dict[str, object] = {"security_master": master}
    if listing is not None:
        parameters["listing_history"] = listing
    return RecoveryContext(
        engine_key="security-entity-recovery",
        as_of=datetime(2026, 7, 20, tzinfo=UTC),
        output_directory=tmp_path,
        parameters=parameters,
    )


def test_recovers_security_entity_with_agreeing_provenance(tmp_path: Path) -> None:
    master = tmp_path / "security_master.json"
    master.write_text(
        json.dumps(
            [
                {
                    "security_id": "SEC-1",
                    "isin": "INE000000001",
                    "symbol": "AAA",
                    "exchange": "NSE",
                    "listing_date": "2020-01-01",
                    "historical_symbols": ["OLDAAA"],
                }
            ]
        ),
        encoding="utf-8",
    )
    listing = tmp_path / "listing_history.csv"
    listing.write_text(
        "security_id,official_listing_date\nSEC-1,2020-01-01\n",
        encoding="utf-8",
    )

    result = SecurityEntityRecoveryEngine().run(_context(tmp_path, master, listing))

    assert result.classification == "PREVIEW_READY"
    assert len(result.canonical_preview) == 1
    row = result.canonical_preview[0]
    assert row.record_key == "SEC-1"
    assert row.values["listing_date"] == "2020-01-01"
    provenance = row.values["field_provenance"]
    assert isinstance(provenance, dict)
    assert provenance["listing_date"] == (
        "listing_history:0",
        "security_master:0",
    )
    assert row.values["entity_confidence"] > 0.0
    assert result.metadata["canonical_writes"] is False


def test_conflict_resolution_prefers_weighted_security_master(tmp_path: Path) -> None:
    master = tmp_path / "security_master.json"
    master.write_text(
        json.dumps(
            [
                {
                    "security_id": "SEC-1",
                    "isin": "INE000000001",
                    "symbol": "AAA",
                    "listing_date": "2020-01-01",
                }
            ]
        ),
        encoding="utf-8",
    )
    listing = tmp_path / "listing_history.csv"
    listing.write_text(
        "security_id,official_listing_date\nSEC-1,2020-01-02\n",
        encoding="utf-8",
    )

    result = SecurityEntityRecoveryEngine().run(_context(tmp_path, master, listing))
    row = result.canonical_preview[0]

    assert row.values["listing_date"] == "2020-01-01"
    conflicts = row.values["field_conflicts"]
    assert isinstance(conflicts, dict)
    assert conflicts["listing_date"] == (
        "listing_history:0=2020-01-02",
    )
    confidence = row.values["field_confidence"]
    assert isinstance(confidence, dict)
    assert 0.4 < confidence["listing_date"] < 1.0


def test_duplicate_identity_blocks_preview(tmp_path: Path) -> None:
    master = tmp_path / "security_master.json"
    master.write_text(
        json.dumps(
            [
                {
                    "security_id": "SEC-1",
                    "isin": "INE000000001",
                    "symbol": "AAA",
                },
                {
                    "security_id": "SEC-1",
                    "isin": "INE000000002",
                    "symbol": "BBB",
                },
            ]
        ),
        encoding="utf-8",
    )

    result = SecurityEntityRecoveryEngine().run(_context(tmp_path, master))

    assert result.classification == "PREVIEW_BLOCKED"
    assert any(
        issue.issue_key == "duplicate-security-id:SEC-1"
        for issue in result.validation_issues
    )


def test_exports_are_deterministic(tmp_path: Path) -> None:
    master = tmp_path / "security_master.jsonl"
    master.write_text(
        '{"security_id":"SEC-1","isin":"INE000000001","symbol":"AAA"}\n',
        encoding="utf-8",
    )
    result = SecurityEntityRecoveryEngine().run(_context(tmp_path, master))

    paths = export_security_entity_recovery(result, tmp_path / "artifacts")

    assert tuple(path.name for path in paths) == (
        "canonical_preview.csv",
        "entity_provenance.json",
        "confidence_report.csv",
        "duplicates.csv",
        "verification.json",
        "report.md",
    )
    with paths[0].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["record_key"] == "SEC-1"
    verification = json.loads(paths[4].read_text(encoding="utf-8"))
    assert verification["classification"] == "PREVIEW_READY"
    assert paths[5].read_text(encoding="utf-8").startswith(
        "# Security Entity Recovery\n"
    )
