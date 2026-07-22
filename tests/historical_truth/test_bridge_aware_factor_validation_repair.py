from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from alpha.__main__ import _historical_truth_app
from alpha.historical_truth.bridge_aware_factor_validation_repair import (
    BridgeAwareFactorValidationRepairEngine,
)


def _case(
    case_id: str,
    *,
    identity: str,
    effective: str,
    factor: float,
    bridge_type: str,
    bridge_classification: str,
    prior_close: float | None,
    action_open: float | None,
    atr: float | None,
    prior_isin: str = "INE000000001",
    current_isin: str = "INE000000001",
    prior_series: str = "EQ",
    current_series: str = "EQ",
    action_type: str = "SPLIT",
) -> dict[str, object]:
    raw_gap = _gap(action_open, prior_close, atr, 1.0)
    adjusted_gap = _gap(action_open, prior_close, atr, factor)
    return {
        "case_id": case_id,
        "event_id": f"event-{case_id}",
        "identity_key": identity,
        "symbol": identity,
        "action_type": action_type,
        "effective_date": effective,
        "official_price_factor": factor,
        "prior_isin": prior_isin,
        "prior_series": prior_series,
        "prior_session": "2025-12-31",
        "current_isin": current_isin,
        "current_series": current_series,
        "current_session": effective,
        "bridge_type": bridge_type,
        "bridge_classification": bridge_classification,
        "bridge_raw_gap_atr": raw_gap,
        "bridge_adjusted_gap_atr": adjusted_gap,
        "selected_bridge": {
            "prior": {"close_price": prior_close},
            "current": {"open_price": action_open},
            "atr_before": atr,
        },
        "official_factor_retained": True,
        "admitted_to_replay": False,
    }


def _gap(
    price: float | None,
    previous_close: float | None,
    atr: float | None,
    factor: float,
) -> float | None:
    if price is None or previous_close is None or atr is None or atr <= 0:
        return None
    return abs(price - previous_close * factor) / (atr * factor)


def _run(tmp_path: Path, cases: list[dict[str, object]]) -> dict[str, object]:
    source = tmp_path / "b1d1"
    source.mkdir(parents=True)
    (source / "htr010b1d1_bridge_cases.json").write_text(
        json.dumps(cases, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return BridgeAwareFactorValidationRepairEngine().run(
        htr010b1d1_output=source,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
    )


def test_same_session_factors_are_validated_as_composite(tmp_path: Path) -> None:
    cases = [
        _case(
            "split",
            identity="ALPHA",
            effective="2026-01-02",
            factor=0.2,
            bridge_type="CROSS_ISIN",
            bridge_classification="CROSS_ISIN_BRIDGE_UNCERTIFIED",
            prior_close=100.0,
            action_open=10.0,
            atr=5.0,
            current_isin="INE000000002",
        ),
        _case(
            "bonus",
            identity="ALPHA",
            effective="2026-01-02",
            factor=0.5,
            bridge_type="CROSS_ISIN",
            bridge_classification="CROSS_ISIN_BRIDGE_UNCERTIFIED",
            prior_close=100.0,
            action_open=10.0,
            atr=5.0,
            current_isin="INE000000002",
            action_type="BONUS",
        ),
    ]

    report = _run(tmp_path, cases)

    assert report["same_session_group_count"] == 1
    assert report["composite_confirmed_group_count"] == 1
    assert report["factor_confirmed_case_count"] == 2
    assert report["implementation_defect_should_remain_count"] == 0
    for row in report["cases"]:
        assert row["corrected_disposition"] == (
            "FACTOR_CONFIRMED_VIA_SAME_SESSION_COMPOSITE"
        )
        assert row["proposed_validation_outcome"] == (
            "FACTOR_CONFIRMED_CORRECT_MULTIPLE_ACTIONS"
        )
        assert row["bridge_certified_for_replay"] is False


def test_stable_and_uncertified_bridge_factor_quality_are_separate(
    tmp_path: Path,
) -> None:
    cases = [
        _case(
            "stable",
            identity="BETA",
            effective="2026-02-01",
            factor=0.5,
            bridge_type="STABLE_SECURITY_SERIES",
            bridge_classification="STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT",
            prior_close=100.0,
            action_open=50.0,
            atr=5.0,
        ),
        _case(
            "cross-isin",
            identity="GAMMA",
            effective="2026-02-02",
            factor=0.2,
            bridge_type="CROSS_ISIN",
            bridge_classification="CROSS_ISIN_BRIDGE_UNCERTIFIED",
            prior_close=100.0,
            action_open=20.0,
            atr=5.0,
            current_isin="INE000000003",
        ),
        _case(
            "cross-series",
            identity="DELTA",
            effective="2026-02-03",
            factor=0.5,
            bridge_type="CROSS_SERIES",
            bridge_classification="CROSS_SERIES_PAIRING_ARTIFACT",
            prior_close=100.0,
            action_open=50.0,
            atr=5.0,
            current_series="BE",
        ),
    ]

    report = _run(tmp_path, cases)
    by_id = {row["case_id"]: row for row in report["cases"]}

    assert by_id["stable"]["factor_quality_confirmed"] is True
    assert by_id["stable"]["bridge_certified_for_replay"] is True
    assert by_id["cross-isin"]["factor_quality_confirmed"] is True
    assert by_id["cross-isin"]["bridge_certified_for_replay"] is False
    assert by_id["cross-series"]["factor_quality_confirmed"] is True
    assert by_id["cross-series"]["bridge_certified_for_replay"] is False


def test_raw_continuity_is_not_misclassified_as_orientation(tmp_path: Path) -> None:
    case = _case(
        "raw-continuous",
        identity="EPSILON",
        effective="2026-03-01",
        factor=0.9,
        bridge_type="STABLE_SECURITY_SERIES",
        bridge_classification="STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT",
        prior_close=100.0,
        action_open=100.0,
        atr=5.0,
        action_type="BONUS",
    )

    report = _run(tmp_path, [case])
    row = report["cases"][0]

    assert row["corrected_disposition"] == (
        "RAW_CONTINUITY_ALREADY_PRESENT_FACTOR_NOT_VALIDATED"
    )
    assert row["proposed_validation_outcome"] == "FACTOR_INSUFFICIENT_EVIDENCE"
    assert row["factor_quality_confirmed"] is False
    assert report["implementation_defect_should_remain_count"] == 0


def test_missing_composite_context_stays_insufficient(tmp_path: Path) -> None:
    cases = [
        _case(
            "missing-split",
            identity="ZETA",
            effective="2026-04-01",
            factor=0.2,
            bridge_type="STABLE_SECURITY_SERIES",
            bridge_classification="STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT",
            prior_close=100.0,
            action_open=20.0,
            atr=None,
        ),
        _case(
            "missing-bonus",
            identity="ZETA",
            effective="2026-04-01",
            factor=0.5,
            bridge_type="STABLE_SECURITY_SERIES",
            bridge_classification="STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT",
            prior_close=100.0,
            action_open=20.0,
            atr=None,
            action_type="BONUS",
        ),
    ]

    report = _run(tmp_path, cases)

    assert report["composite_confirmed_group_count"] == 0
    assert report["factor_unconfirmed_case_count"] == 2
    for row in report["cases"]:
        assert row["proposed_validation_outcome"] == "FACTOR_INSUFFICIENT_EVIDENCE"


def test_report_and_exports_are_deterministic(tmp_path: Path) -> None:
    case = _case(
        "deterministic",
        identity="ETA",
        effective="2026-05-01",
        factor=0.5,
        bridge_type="STABLE_SECURITY_SERIES",
        bridge_classification="STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT",
        prior_close=100.0,
        action_open=50.0,
        atr=5.0,
    )
    first = _run(tmp_path / "first", [case])
    second = _run(tmp_path / "second", [case])

    assert first == second
    assert first["report_sha256"] == second["report_sha256"]
    paths = BridgeAwareFactorValidationRepairEngine.export(first, tmp_path / "export")
    assert len(paths) == 5
    assert all(path.exists() for path in paths)


def test_command_registration_is_idempotent() -> None:
    first = _historical_truth_app()
    second = _historical_truth_app()
    command_name = "bridge-aware-factor-validation-repair"

    assert (
        sum(command.name == command_name for command in first.registered_commands) == 1
    )
    assert (
        sum(command.name == command_name for command in second.registered_commands) == 1
    )
