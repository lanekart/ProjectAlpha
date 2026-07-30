from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from alpha.historical_truth.legacy_isin_reference_bridge import (
    LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION,
    LegacyBridgeDecision,
    LegacyIsinReferenceBridge,
)
from tests.historical_truth.legacy_bridge_test_support import (
    EVENT_ID,
    IDENTITY,
    ISIN,
    fixture_source_contract,
    write_bridge_fixture,
)


def _bridge(
    tmp_path: Path,
    **changes: object,
) -> LegacyIsinReferenceBridge:
    htr009a2, htr010a3 = write_bridge_fixture(tmp_path, **changes)
    return LegacyIsinReferenceBridge.from_fixture_output(
        htr009a2,
        htr010a3_output=htr010a3,
    )


def _resolve(
    bridge: LegacyIsinReferenceBridge,
    *,
    symbol: str = "ALPHA",
    series: str = "EQ",
    isin: str = ISIN,
    reference_date: date = date(2015, 1, 2),
    prior_isin_mismatch: bool = False,
):
    return bridge.resolve(
        identity_key=IDENTITY,
        symbol=symbol,
        series=series,
        isin=isin,
        reference_date=reference_date,
        prior_isin_mismatch=prior_isin_mismatch,
    )


def test_exact_dated_official_bridge_is_certified_and_hash_bound(
    tmp_path: Path,
) -> None:
    bridge = _bridge(tmp_path)

    result = _resolve(bridge)

    assert result.certified is True
    assert (
        result.decision is LegacyBridgeDecision.CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE
    )
    assert result.official_event_ids == (EVENT_ID,)
    provenance = result.provenance()
    assert provenance["reference_price_bridge_contract_version"] == (
        LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION
    )
    assert provenance["reference_price_bridge_candle_isin_remained_missing"] is True
    assert provenance["reference_price_bridge_membership_interval_ids"]
    assert provenance["reference_price_bridge_symbol_interval_ids"]
    assert provenance["reference_price_bridge_evidence_sha256"]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"membership": False},
            LegacyBridgeDecision.NO_MATCHING_OFFICIAL_INTERVAL,
        ),
        (
            {"valid_to": "2014-12-31"},
            LegacyBridgeDecision.DATE_OUTSIDE_INTERVAL,
        ),
        (
            {"symbol": False},
            LegacyBridgeDecision.SYMBOL_MISMATCH,
        ),
        (
            {"symbol_value": "OTHER"},
            LegacyBridgeDecision.SYMBOL_MISMATCH,
        ),
        (
            {"event_series": "BE"},
            LegacyBridgeDecision.SERIES_MISMATCH,
        ),
        (
            {"event_isin": "INE999A01010"},
            LegacyBridgeDecision.INSUFFICIENT_OFFICIAL_EVIDENCE,
        ),
        (
            {"symbol_confidence": "MEDIUM"},
            LegacyBridgeDecision.INTERVAL_CONFIDENCE_NOT_HIGH,
        ),
        (
            {"membership_lineage": ()},
            LegacyBridgeDecision.INTERVAL_LINEAGE_MISSING,
        ),
        (
            {"symbol_lineage": ()},
            LegacyBridgeDecision.INTERVAL_LINEAGE_MISSING,
        ),
        (
            {"overlap": True},
            LegacyBridgeDecision.OVERLAPPING_IDENTITY_CONFLICT,
        ),
        (
            {"symbol_reuse": True},
            LegacyBridgeDecision.SYMBOL_REUSE_CONFLICT,
        ),
        (
            {"symbol_change": True},
            LegacyBridgeDecision.SYMBOL_CHANGE_BOUNDARY_UNRESOLVED,
        ),
        (
            {"same_identity_symbol_overlap": True},
            LegacyBridgeDecision.SYMBOL_CHANGE_BOUNDARY_UNRESOLVED,
        ),
        (
            {"series_transition": True},
            LegacyBridgeDecision.SERIES_TRANSITION_UNRESOLVED,
        ),
        (
            {"tradable": False},
            LegacyBridgeDecision.MEMBERSHIP_NOT_COMPATIBLE,
        ),
        (
            {"membership_state": "PROVISIONAL_ACTIVE"},
            LegacyBridgeDecision.MEMBERSHIP_NOT_COMPATIBLE,
        ),
    ],
)
def test_bridge_fails_closed_on_incomplete_or_conflicting_evidence(
    tmp_path: Path,
    changes: dict[str, object],
    expected: LegacyBridgeDecision,
) -> None:
    result = _resolve(_bridge(tmp_path, **changes))

    assert result.certified is False
    assert result.decision is expected


def test_explicit_prior_isin_mismatch_is_non_bridgeable(tmp_path: Path) -> None:
    result = _resolve(_bridge(tmp_path), prior_isin_mismatch=True)

    assert result.certified is False
    assert result.decision is LegacyBridgeDecision.PRIOR_ISIN_MISMATCH_NON_BRIDGEABLE


def test_uncertified_tradability_does_not_override_compatible_membership(
    tmp_path: Path,
) -> None:
    result = _resolve(
        _bridge(
            tmp_path,
            tradable=False,
            tradability_state="UNRESOLVED_NO_TERMINATION_EVIDENCE",
        )
    )

    assert result.certified is True
    assert result.tradability_interval is not None
    assert result.tradability_interval.value == "False"
    assert result.provenance()["reference_price_bridge_tradability_certified"] is False


def test_event_isin_must_be_valid_and_match_governed_identity(
    tmp_path: Path,
) -> None:
    result = _resolve(_bridge(tmp_path), isin="INVALID")

    assert result.decision is LegacyBridgeDecision.EVENT_ISIN_INVALID


def test_signed_loader_rejects_tampered_htr009a2_evidence(
    tmp_path: Path,
) -> None:
    htr009a2, htr010a3 = write_bridge_fixture(tmp_path)
    contract = fixture_source_contract(htr009a2)
    path = htr009a2 / "htr009a2_symbol_intervals.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["records"][0]["symbol"] = "TAMPERED"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        LegacyIsinReferenceBridge.from_output(
            htr009a2,
            htr010a3_output=htr010a3,
            source_contract=contract,
        )


def test_duplicate_interval_is_rejected(tmp_path: Path) -> None:
    htr009a2, htr010a3 = write_bridge_fixture(tmp_path)
    path = htr009a2 / "htr009a2_symbol_intervals.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["records"].append(dict(payload["records"][0]))
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate symbol interval"):
        LegacyIsinReferenceBridge.from_fixture_output(
            htr009a2,
            htr010a3_output=htr010a3,
        )


def test_malformed_interval_date_is_rejected(tmp_path: Path) -> None:
    htr009a2, htr010a3 = write_bridge_fixture(tmp_path)
    path = htr009a2 / "htr009a2_membership_intervals.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["records"][0]["valid_from"] = "not-a-date"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="malformed"):
        LegacyIsinReferenceBridge.from_fixture_output(
            htr009a2,
            htr010a3_output=htr010a3,
        )


def test_unrelated_official_dummy_identifier_does_not_reject_population(
    tmp_path: Path,
) -> None:
    htr009a2, htr010a3 = write_bridge_fixture(tmp_path)
    path = htr009a2 / "htr009a2_security_events.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["records"].append(
        {
            "event_id": "nse-event:official-warrant-listing",
            "event_type": "LISTED",
            "effective_date": "2010-01-01",
            "old_symbol": None,
            "new_symbol": "ALPHAW1",
            "old_series": None,
            "new_series": "W1",
            "old_isin": None,
            "new_isin": "DUMMY0000001",
            "predecessor_identity": None,
            "successor_identity": "nse:isin:DUMMY0000001",
            "official_source_id": "nse-official-listing",
            "admission_state": "ADMITTED",
            "confidence_state": "HIGH",
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")

    bridge = LegacyIsinReferenceBridge.from_fixture_output(
        htr009a2,
        htr010a3_output=htr010a3,
    )

    assert _resolve(bridge).certified is True
