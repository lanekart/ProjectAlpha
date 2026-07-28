from __future__ import annotations

import json
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from alpha.historical_truth.adjustment_replay_admission_models import (
    AdmissionState,
    ValidationOutcome,
)
from alpha.historical_truth.bridge_aware_admission_state_propagation import (
    propagated_readiness,
)
from alpha.historical_truth.bridge_aware_factor_validation_repair import _repair_case
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.corporate_action_price_models import (
    CorporateActionSourceSpec,
)
from alpha.historical_truth.corporate_action_price_sources import (
    parse_corporate_action_source,
)
from alpha.historical_truth.factor_transformation_bridge_forensics import (
    FactorTransformationBridgeForensicsEngine,
)
from alpha.historical_truth.factor_transformation_forensics import (
    _official_term_factor,
)


def _spec(year: int) -> CorporateActionSourceSpec:
    return CorporateActionSourceSpec(
        f"nse_equity_corporate_actions_{year}",
        "NSE_EQUITY_CORPORATE_ACTIONS",
        "https://www.nseindia.com/api/corporates-corporateActions",
        date(year, 1, 1),
        date(year, 12, 31),
    )


def _action(subject: str, *, year: int, ex_date: str, face_value: str):
    row = {
        "symbol": "ALPHA",
        "series": "EQ",
        "isin": "INE000A01010",
        "subject": subject,
        "exDate": ex_date,
        "recDate": ex_date,
        "caBroadcastDate": ex_date,
        "faceVal": face_value,
    }
    raw = json.dumps([row], sort_keys=True).encode()
    actions = parse_corporate_action_source(_spec(year), raw, sha256(raw).hexdigest())[
        1
    ]
    assert len(actions) == 1
    return actions[0]


def test_bonus_and_split_terms_are_composed_from_official_text() -> None:
    minda = _action(
        "Bonus 1:1 / Face Value Split From Rs 10/- Per Share To Rs 2/- Per Share",
        year=2015,
        ex_date="05-Jan-2015",
        face_value="2",
    )
    jbma = _action(
        "Bonus 1:1 And Face Value Split Rs.10/- To Rs.5/- Per Share",
        year=2014,
        ex_date="08-Oct-2014",
        face_value="1",
    )
    ordinary = _action(
        "Bonus 1:1",
        year=2014,
        ex_date="08-Oct-2014",
        face_value="5",
    )

    assert minda.old_face_value == pytest.approx(10.0)
    assert minda.new_face_value == pytest.approx(2.0)
    assert minda.adjustment_factor == pytest.approx(0.1)
    assert jbma.old_face_value == pytest.approx(10.0)
    assert jbma.new_face_value == pytest.approx(5.0)
    assert jbma.adjustment_factor == pytest.approx(0.25)
    assert ordinary.old_face_value is None
    assert ordinary.adjustment_factor == pytest.approx(0.5)


def test_forensic_term_factor_composes_bonus_and_split() -> None:
    factor, formula = _official_term_factor(
        {
            "ratio_numerator": 1.0,
            "ratio_denominator": 1.0,
            "old_face_value": 10.0,
            "new_face_value": 2.0,
        },
        "BONUS",
    )

    assert factor == pytest.approx(0.1)
    assert formula is not None and "new_face_value" in formula


def test_bridge_forensics_carries_governed_term_match(tmp_path: Path) -> None:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    warehouse.initialise()
    with warehouse._connect() as connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO daily_candle VALUES (
                ?, 'nse', ?, ?, ?, ?, ?, ?, ?, ?, 'fixture-sha'
            )
            """,
            (
                (
                    date(2013, 11, 8),
                    "OMAXE",
                    "EQ",
                    "INE800H01010",
                    140.25,
                    141.45,
                    138.65,
                    140.45,
                    362854,
                ),
                (
                    date(2013, 11, 11),
                    "OMAXE",
                    "EQ",
                    "INE800H01010",
                    128.55,
                    130.15,
                    116.9,
                    123.5,
                    728826,
                ),
            ),
        )
    b = tmp_path / "b"
    b1d = tmp_path / "b1d"
    b.mkdir()
    b1d.mkdir()
    (b / "htr010b_identity_transitions.json").write_text("[]\n")
    (b1d / "htr010b1d_factor_transformation_cases.json").write_text(
        json.dumps(
            [
                {
                    "case_id": "case:omaxe",
                    "event_id": "event:omaxe",
                    "identity_key": "nse:isin:INE800H01010",
                    "symbol": "OMAXE",
                    "isin": "INE800H01010",
                    "action_type": "BONUS",
                    "effective_date": "2013-11-11",
                    "official_price_factor": 39.0 / 49.0,
                    "official_term_factor": 39.0 / 49.0,
                    "official_term_formula": "bonus ratio",
                    "official_term_factor_matches": True,
                    "forensic_classification": "SERIES_SELECTION_MISMATCH",
                    "forensic_evidence": {},
                }
            ]
        )
        + "\n"
    )

    report = FactorTransformationBridgeForensicsEngine().run(
        database_path=tmp_path / "truth.duckdb",
        htr010b_output=b,
        htr010b1d_output=b1d,
        start_date=date(2013, 1, 1),
        end_date=date(2013, 12, 31),
    )

    case = report["cases"][0]
    assert case["b1d_official_term_factor_matches"] is True
    assert case["b1d_official_term_factor"] == pytest.approx(39.0 / 49.0)


def test_governed_term_match_survives_stable_bridge_repair() -> None:
    row = {
        "bridge_type": "STABLE_SECURITY_SERIES",
        "bridge_classification": "STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT",
        "bridge_raw_gap_atr": 4.18,
        "bridge_adjusted_gap_atr": 7.39,
        "b1d_official_term_factor_matches": True,
        "action_type": "BONUS",
    }
    repaired = _repair_case(row, {"factor_count": 1})

    assert repaired["factor_quality_confirmed"] is True
    assert repaired["proposed_validation_outcome"] == (
        "FACTOR_CONFIRMED_CORRECT_MARKET_GAP"
    )
    assert repaired["bridge_certified_for_replay"] is True


def test_readiness_reports_actual_defects_not_unresolved_intervals() -> None:
    defects = tuple(
        {"validation_outcome": ValidationOutcome.IMPLEMENTATION_DEFECT.value}
        for _ in range(3)
    )
    certified = AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL.value
    readiness = propagated_readiness(
        base={"blockers": ["FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS"]},
        intervals=({"admission_state": certified},),
        reporting={},
        residual_summary={"attribution_counts": {}},
        validation_results=defects,
    )

    assert readiness["final_unresolved_interval_count"] == 0
    assert readiness["implementation_defect_count"] == 3
    assert "FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS" in readiness["blockers"]
