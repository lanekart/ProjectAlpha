from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from alpha.historical_truth.legacy_isin_reference_bridge import (
    LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION,
    LegacyIsinReferenceBridge,
)

IDENTITY = "nse:isin:INE000A01010"
EVENT_ID = "nse-event:official-listing"


def _write_output(
    root: Path,
    *,
    membership: bool = True,
    overlap: bool = False,
    event_series: str = "EQ",
    symbol_lineage: tuple[str, ...] = (EVENT_ID,),
) -> Path:
    memberships = []
    if membership:
        memberships.append(
            {
                "identity_key": IDENTITY,
                "valid_from": "2010-01-01",
                "valid_to": "2015-12-31",
                "state": "UNRESOLVED_NO_TERMINATION_EVIDENCE",
                "source_event_ids": [EVENT_ID],
            }
        )
    symbols = [
        {
            "identity_key": IDENTITY,
            "symbol": "ALPHA",
            "valid_from": "2010-01-01",
            "valid_to": "2015-12-31",
            "confidence_state": "HIGH",
            "issue_codes": [],
            "source_event_ids": list(symbol_lineage),
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
                "source_event_ids": ["nse-event:other"],
            }
        )
    events = [
        {
            "event_id": EVENT_ID,
            "event_type": "LISTING",
            "effective_date": "2010-01-01",
            "old_symbol": None,
            "new_symbol": "ALPHA",
            "old_series": None,
            "new_series": event_series,
            "old_isin": None,
            "new_isin": "INE000A01010",
            "predecessor_identity": None,
            "successor_identity": IDENTITY,
            "official_source_id": "nse-official-listing",
            "admission_state": "ADMITTED",
            "confidence_state": "HIGH",
        }
    ]
    for name, rows in (
        ("htr009a2_membership_intervals.json", memberships),
        ("htr009a2_symbol_intervals.json", symbols),
        ("htr009a2_security_events.json", events),
    ):
        (root / name).write_text(
            json.dumps({"records": rows}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return root


def _resolve(bridge: LegacyIsinReferenceBridge):
    return bridge.resolve(
        identity_key=IDENTITY,
        symbol="ALPHA",
        series="EQ",
        isin="INE000A01010",
        reference_date=date(2015, 1, 2),
    )


def test_exact_dated_official_bridge_is_certified_and_hash_bound(
    tmp_path: Path,
) -> None:
    bridge = LegacyIsinReferenceBridge.from_output(_write_output(tmp_path))
    result = _resolve(bridge)

    assert result.certified is True
    assert result.state == "CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE"
    assert result.official_event_ids == (EVENT_ID,)
    assert result.official_source_ids == ("nse-official-listing",)
    provenance = result.provenance()
    assert provenance["reference_price_bridge_contract_version"] == (
        LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION
    )
    assert len(bridge.source_checksums) == 3
    assert all(len(digest) == 64 for _, digest in bridge.source_checksums)


def test_bridge_fails_closed_when_membership_is_missing(tmp_path: Path) -> None:
    bridge = LegacyIsinReferenceBridge.from_output(
        _write_output(tmp_path, membership=False)
    )

    result = _resolve(bridge)

    assert result.certified is False
    assert result.state == "MEMBERSHIP_INTERVAL_NOT_UNIQUE"


def test_bridge_fails_closed_on_overlapping_symbol_identity(tmp_path: Path) -> None:
    bridge = LegacyIsinReferenceBridge.from_output(
        _write_output(tmp_path, overlap=True)
    )

    result = _resolve(bridge)

    assert result.certified is False
    assert result.state == "OVERLAPPING_SYMBOL_IDENTITY"


def test_bridge_fails_closed_on_official_series_mismatch(tmp_path: Path) -> None:
    bridge = LegacyIsinReferenceBridge.from_output(
        _write_output(tmp_path, event_series="BE")
    )

    result = _resolve(bridge)

    assert result.certified is False
    assert result.state == "OFFICIAL_EVENT_SERIES_MISMATCH"


def test_bridge_requires_lineage_convergence(tmp_path: Path) -> None:
    bridge = LegacyIsinReferenceBridge.from_output(
        _write_output(tmp_path, symbol_lineage=("nse-event:different",))
    )

    result = _resolve(bridge)

    assert result.certified is False
    assert result.state == "SYMBOL_EVENT_LINEAGE_DIVERGES"


def test_bridge_rejects_missing_records_envelope(tmp_path: Path) -> None:
    _write_output(tmp_path)
    path = tmp_path / "htr009a2_security_events.json"
    path.write_text(json.dumps({"wrong": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="records array"):
        LegacyIsinReferenceBridge.from_output(tmp_path)
