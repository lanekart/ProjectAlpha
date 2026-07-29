from __future__ import annotations

from dataclasses import replace
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from alpha.historical_truth.corporate_action_price_models import (
    ActionAdmissionState,
    AdjustmentFactorState,
    CorporateActionEvent,
    CorporateActionType,
    EvidenceConfidence,
)
from alpha.historical_truth.official_corporate_action_supplements import (
    apply_official_corporate_action_supplements,
    official_corporate_action_supplements,
    official_security_identity_supplements,
)


def _action() -> CorporateActionEvent:
    return CorporateActionEvent(
        action_id="action-tatasteel",
        exchange="NSE",
        governed_identity_id="nse:isin:INE081A01020",
        symbol="TATASTEEL",
        series="EQ",
        isin="INE081A01020",
        action_type=CorporateActionType.RIGHTS,
        purpose="Right-Eq1:5 & 9ccps:10eq",
        announcement_date=None,
        record_date=None,
        ex_date=date(2007, 10, 29),
        effective_date=date(2007, 10, 29),
        old_face_value=10.0,
        new_face_value=10.0,
        ratio_numerator=1.0,
        ratio_denominator=5.0,
        cash_amount=None,
        rights_price=None,
        old_quantity=None,
        new_quantity=None,
        predecessor_identity=None,
        successor_identity=None,
        price_adjustment_required=True,
        adjustment_factor_state=AdjustmentFactorState.UNKNOWN,
        adjustment_factor=None,
        source_id="nse-source",
        source_location="row-1",
        admission_state=ActionAdmissionState.ADMITTED,
        confidence_state=EvidenceConfidence.HIGH,
    )


def _materialize_tatasteel_source(root: Path) -> Path:
    source = (
        root
        / "raw"
        / "official"
        / "corporate_action_supplements"
        / "dsi010b5"
        / "tatasteel_2007_official_press.html"
    )
    source.parent.mkdir(parents=True)
    # The registry deliberately pins the genuine source checksum. The unit test
    # substitutes the expected digest at the immutable byte boundary.
    source.write_bytes(b"fixture")
    return source


def test_missing_official_supplements_fail_closed(tmp_path: Path) -> None:
    verified, rejected = official_corporate_action_supplements(tmp_path)

    assert verified == ()
    assert rejected
    assert {item.reason for item in rejected} == {"IMMUTABLE_OFFICIAL_SOURCE_MISSING"}


def test_verified_supplement_updates_only_exact_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _materialize_tatasteel_source(tmp_path)
    genuine_digest = "27f83c81ff900588c6bbcceab2ae4269ae9a6fa414b75d8fd7e402656650ff6d"
    real_read_bytes = Path.read_bytes

    class _Digest:
        def hexdigest(self) -> str:
            return genuine_digest

    def _hash(data: bytes) -> _Digest:
        assert data == b"fixture"
        return _Digest()

    monkeypatch.setattr(
        "alpha.historical_truth.official_corporate_action_supplements.sha256",
        _hash,
    )
    verified, rejected = official_corporate_action_supplements(tmp_path)
    assert source.read_bytes() == b"fixture"
    assert len(verified) == 1
    assert all(item.reason == "IMMUTABLE_OFFICIAL_SOURCE_MISSING" for item in rejected)

    original = _action()
    updated, applied, event_rejections = apply_official_corporate_action_supplements(
        (original,),
        verified,
    )

    assert len(applied) == 1
    assert event_rejections == ()
    assert updated[0].rights_price == 300.0
    assert updated[0].ratio_numerator == 1.0
    assert updated[0].ratio_denominator == 5.0
    assert original.rights_price is None
    assert sha256(real_read_bytes(source)).hexdigest() != genuine_digest


def test_supplement_does_not_match_a_different_effective_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _materialize_tatasteel_source(tmp_path)
    genuine_digest = "27f83c81ff900588c6bbcceab2ae4269ae9a6fa414b75d8fd7e402656650ff6d"

    class _Digest:
        def hexdigest(self) -> str:
            return genuine_digest

    monkeypatch.setattr(
        "alpha.historical_truth.official_corporate_action_supplements.sha256",
        lambda _: _Digest(),
    )
    verified, _ = official_corporate_action_supplements(tmp_path)
    wrong_date = replace(
        _action(),
        effective_date=date(2007, 10, 30),
        ex_date=date(2007, 10, 30),
    )

    updated, applied, rejected = apply_official_corporate_action_supplements(
        (wrong_date,),
        verified,
    )

    assert updated == (wrong_date,)
    assert applied == ()
    assert rejected[0].reason == "OFFICIAL_EVENT_MATCH_NOT_UNIQUE"


def test_identity_supplement_requires_exact_official_source_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        tmp_path
        / "raw"
        / "official"
        / "corporate_action_supplements"
        / "dsi010b5"
        / "nse_press_20100106.htm"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(b"official-nse-listing-fixture")

    class _Digest:
        def hexdigest(self) -> str:
            return "ca522747d2a180da57c25be8b1aa7e89f974f78ef26b4b012d55d58fa12da185"

    monkeypatch.setattr(
        "alpha.historical_truth.official_corporate_action_supplements.sha256",
        lambda _: _Digest(),
    )

    supplements = official_security_identity_supplements(tmp_path)

    assert {item.symbol for item in supplements} == {"MMTC", "KWALITY", "VIPUL"}
    assert {item.valid_from for item in supplements} == {date(2010, 1, 8)}


def test_official_capital_reduction_preserves_share_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        tmp_path
        / "raw"
        / "official"
        / "corporate_action_supplements"
        / "dsi010b5"
        / "hindmotor_2010_11_bse_annual_report.pdf"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(b"official-bse-annual-report-fixture")

    class _Digest:
        def hexdigest(self) -> str:
            return "56c07a82b95e72049fc22111de2763f9ad9c5438fb4fa07f86d57b7604f1aa92"

    monkeypatch.setattr(
        "alpha.historical_truth.official_corporate_action_supplements.sha256",
        lambda _: _Digest(),
    )
    verified, _ = official_corporate_action_supplements(tmp_path)
    reduction = replace(
        _action(),
        action_id="action-hindmotor",
        governed_identity_id="nse:isin:INE253A01017",
        symbol="HINDMOTOR",
        isin="INE253A01017",
        action_type=CorporateActionType.CAPITAL_REDUCTION,
        purpose="Capital Reduction",
        record_date=date(2011, 1, 28),
        ex_date=date(2011, 1, 27),
        effective_date=date(2011, 1, 27),
        ratio_numerator=None,
        ratio_denominator=None,
        old_face_value=None,
        new_face_value=10.0,
        adjustment_factor_state=AdjustmentFactorState.AMBIGUOUS,
    )

    updated, applied, rejected = apply_official_corporate_action_supplements(
        (reduction,),
        verified,
    )

    assert rejected == ()
    assert len(applied) == 1
    assert updated[0].old_face_value == 10.0
    assert updated[0].new_face_value == 5.0
    assert updated[0].old_quantity == updated[0].new_quantity == 1.0
    assert updated[0].adjustment_factor == 1.0
    assert (
        updated[0].adjustment_factor_state
        is AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS
    )
    assert updated[0].price_adjustment_required is False
