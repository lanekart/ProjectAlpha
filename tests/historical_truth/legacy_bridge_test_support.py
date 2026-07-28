from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from alpha.historical_truth.legacy_isin_reference_bridge import (
    LegacyBridgeSourceContract,
)

IDENTITY = "nse:isin:INE000A01010"
ISIN = "INE000A01010"
EVENT_ID = "nse-event:official-listing"
SOURCE_ID = "nse-official-listing"
REPORT_SHA256 = "a" * 64
SOURCE_SHA256 = "b" * 64


def write_bridge_fixture(
    root: Path,
    *,
    membership: bool = True,
    membership_state: str = "UNRESOLVED_NO_TERMINATION_EVIDENCE",
    membership_lineage: tuple[str, ...] = (EVENT_ID,),
    symbol: bool = True,
    symbol_value: str = "ALPHA",
    symbol_confidence: str = "HIGH",
    symbol_lineage: tuple[str, ...] = (EVENT_ID,),
    same_identity_symbol_overlap: bool = False,
    event_series: str = "EQ",
    event_isin: str = ISIN,
    event_admission: str = "ADMITTED",
    event_confidence: str = "HIGH",
    overlap: bool = False,
    symbol_reuse: bool = False,
    symbol_change: bool = False,
    series_transition: bool = False,
    tradable: bool = True,
    tradability_state: str | None = None,
    valid_from: str = "2010-01-01",
    valid_to: str = "2015-12-31",
) -> tuple[Path, Path]:
    htr009a2 = root / "htr009a2"
    htr010a3 = root / "htr010a3"
    htr009a2.mkdir(parents=True)
    htr010a3.mkdir(parents=True)

    memberships = []
    if membership:
        memberships.append(
            {
                "identity_key": IDENTITY,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "state": membership_state,
                "source_event_ids": list(membership_lineage),
            }
        )
    symbols = []
    if symbol:
        symbols.append(
            {
                "identity_key": IDENTITY,
                "symbol": symbol_value,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "confidence_state": symbol_confidence,
                "issue_codes": [],
                "source_event_ids": list(symbol_lineage),
            }
        )
    if same_identity_symbol_overlap:
        symbols.append(
            {
                "identity_key": IDENTITY,
                "symbol": "OLDALPHA",
                "valid_from": valid_from,
                "valid_to": valid_to,
                "confidence_state": "HIGH",
                "issue_codes": [],
                "source_event_ids": list(symbol_lineage),
            }
        )
    events: list[dict[str, Any]] = [
        {
            "event_id": EVENT_ID,
            "event_type": "LISTED",
            "effective_date": "2010-01-01",
            "old_symbol": None,
            "new_symbol": "ALPHA",
            "old_series": None,
            "new_series": event_series,
            "old_isin": None,
            "new_isin": event_isin,
            "predecessor_identity": None,
            "successor_identity": IDENTITY,
            "official_source_id": SOURCE_ID,
            "admission_state": event_admission,
            "confidence_state": event_confidence,
        }
    ]
    if overlap:
        symbols.append(
            {
                "identity_key": "nse:isin:INE999A01010",
                "symbol": "ALPHA",
                "valid_from": "2014-01-01",
                "valid_to": "2015-12-31",
                "confidence_state": "HIGH",
                "issue_codes": [],
                "source_event_ids": [],
            }
        )
    reuse_rows = []
    if symbol_reuse:
        reuse_rows.append(
            {
                "symbol": "ALPHA",
                "identity_keys": [IDENTITY, "nse:isin:INE999A01010"],
                "final_status": "SYMBOL_REUSE_CONFLICT",
            }
        )
    change_rows = []
    if symbol_change:
        change_rows.append(
            {
                "old_symbol": "OLDALPHA",
                "new_symbol": "ALPHA",
                "effective_date": None,
                "old_identity": IDENTITY,
                "new_identity": IDENTITY,
                "final_status": "UNRESOLVED_IDENTITY_TRANSITION",
            }
        )
    if series_transition:
        events.append(
            {
                "event_id": "nse-event:series-change",
                "event_type": "SERIES_CHANGED",
                "effective_date": "2015-01-02",
                "old_symbol": "ALPHA",
                "new_symbol": "ALPHA",
                "old_series": "BE",
                "new_series": None,
                "old_isin": ISIN,
                "new_isin": ISIN,
                "predecessor_identity": IDENTITY,
                "successor_identity": IDENTITY,
                "official_source_id": SOURCE_ID,
                "admission_state": "PROVISIONAL",
                "confidence_state": "MEDIUM",
            }
        )
    payloads: dict[str, object] = {
        "htr009a2_certification.json": {
            "contract_version": "HTR-009A2-v1.0.0",
            "production_influence": False,
            "report_sha256": REPORT_SHA256,
        },
        "htr009a2_executive_report.json": {
            "contract_version": "HTR-009A2-v1.0.0",
            "production_influence": False,
            "report_sha256": REPORT_SHA256,
        },
        "htr009a2_source_inventory.json": {
            "records": [
                {
                    "source_id": SOURCE_ID,
                    "sha256": SOURCE_SHA256,
                    "source_path": "raw/nse/listing.pdf",
                    "official_host": True,
                }
            ]
        },
        "htr009a2_membership_intervals.json": {"records": memberships},
        "htr009a2_tradability_intervals.json": {
            "records": [
                {
                    "identity_key": IDENTITY,
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                    "tradable": tradable,
                    "state": (
                        tradability_state
                        or (
                            membership_state
                            if tradable
                            else "CERTIFIED_ACTIVE_SUSPENDED"
                        )
                    ),
                    "source_event_ids": [EVENT_ID],
                }
            ]
        },
        "htr009a2_symbol_intervals.json": {"records": symbols},
        "htr009a2_security_events.json": {"records": events},
        "htr009a2_identity_relationships.json": {"records": []},
        "htr009a2_symbol_reuse.json": {"records": reuse_rows},
        "htr009a2_symbol_changes.json": {"records": change_rows},
    }
    for name, payload in payloads.items():
        (htr009a2 / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    _write_json(
        htr010a3 / "htr010a3_corporate_action_join_readiness.json",
        [
            {
                "identity_key": IDENTITY,
                "symbol": "ALPHA",
                "isin": ISIN,
                "state": "JOIN_READY_CERTIFIED",
                "admitted_to_certified_join": True,
            }
        ],
    )
    _write_json(
        htr010a3 / "htr010a3_readiness.json",
        {
            "production_influence": False,
            "readiness": {
                "state": "CONDITIONALLY_READY_FOR_HTR_010B",
                "denominator_identities": 1,
                "admitted_identities": 1,
                "quarantined_identities": 0,
            },
        },
    )
    return htr009a2, htr010a3


def fixture_source_contract(htr009a2: Path) -> LegacyBridgeSourceContract:
    checksums = tuple(
        sorted(
            (
                path.name,
                sha256(path.read_bytes()).hexdigest(),
            )
            for path in htr009a2.glob("htr009a2_*.json")
        )
    )
    return LegacyBridgeSourceContract(
        contract_id="SYNTHETIC-SIGNED-FIXTURE-v1",
        workflow_run_id=1,
        artifact_id=1,
        artifact_name="synthetic",
        artifact_digest=f"sha256:{'c' * 64}",
        source_head_sha="d" * 40,
        expected_file_sha256=checksums,
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
