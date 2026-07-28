from __future__ import annotations

import json
from datetime import date
from hashlib import sha256
from pathlib import Path

import duckdb
import pytest

from alpha.historical_truth.adjustment_replay_admission_continuity_validation import (
    CERTIFIED_FACTOR_STATES,
)
from alpha.historical_truth.bridge_aware_factor_validation_repair import _repair_case
from alpha.historical_truth.complete_corporate_action_engine import (
    cumulative_factors,
    derive_factors,
)
from alpha.historical_truth.complete_corporate_action_models import (
    FactorState,
)
from alpha.historical_truth.corporate_action_price_models import (
    CorporateActionSourceSpec,
)
from alpha.historical_truth.corporate_action_price_sources import (
    parse_corporate_action_source,
)
from alpha.historical_truth.factor_transformation_forensics import (
    _classify,
    _official_term_factor,
)


def _action(isin: str = "INE000A01010"):
    spec = CorporateActionSourceSpec(
        "nse_equity_corporate_actions_2015",
        "NSE_EQUITY_CORPORATE_ACTIONS",
        "https://www.nseindia.com/api/corporates-corporateActions",
        date(2015, 1, 1),
        date(2015, 12, 31),
    )
    row = {
        "symbol": "ALPHA",
        "series": "EQ",
        "isin": isin,
        "subject": "Rights 1:4 at Rs 50",
        "exDate": "05-Jan-2015",
        "recDate": "06-Jan-2015",
        "caBroadcastDate": "01-Jan-2015",
        "faceVal": "10",
    }
    raw = json.dumps([row], sort_keys=True).encode()
    actions = parse_corporate_action_source(spec, raw, sha256(raw).hexdigest())[1]
    assert len(actions) == 1
    return actions[0]


def _database(
    path: Path,
    *,
    candle_isin: str | None,
    source_sha256: str | None = "official-sha",
) -> Path:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE daily_candle(
                trading_date DATE,
                exchange VARCHAR,
                symbol VARCHAR,
                series VARCHAR,
                isin VARCHAR,
                open_price DOUBLE,
                high_price DOUBLE,
                low_price DOUBLE,
                close_price DOUBLE,
                volume BIGINT,
                source_sha256 VARCHAR
            )
            """
        )
        connection.execute(
            "INSERT INTO daily_candle VALUES "
            "('2015-01-02','nse','ALPHA','EQ',?,98,102,97,100,1000,?)",
            [candle_isin, source_sha256],
        )
    return path


def _event(action) -> dict[str, object]:
    return {
        "canonical_event_id": "event-rights",
        "governed_identity_id": f"nse:isin:{action.isin}",
        "effective_date": action.effective_date.isoformat(),
        "series_applicability": ["EQ"],
        "raw_record_ids": [action.action_id],
    }


def _derive(tmp_path: Path, *, candle_isin: str | None):
    action = _action()
    identity = f"nse:isin:{action.isin}"
    factors = derive_factors(
        _database(tmp_path / "truth.duckdb", candle_isin=candle_isin),
        (_event(action),),
        {action.action_id: action},
        {
            identity: {
                "identity_key": identity,
                "admitted_to_certified_join": True,
            }
        },
    )
    assert len(factors) == 1
    return factors[0]


def test_same_isin_reference_price_is_certified(tmp_path: Path) -> None:
    factor = _derive(tmp_path, candle_isin="INE000A01010")

    assert factor["factor_state"] == FactorState.FACTOR_CERTIFIED_REFERENCE_PRICE
    assert factor["reference_price"] == pytest.approx(100.0)
    assert factor["reference_price_date"] == "2015-01-02"
    assert factor["reference_price_isin"] == "INE000A01010"
    assert factor["reference_price_source_sha256"] == "official-sha"
    assert factor["reference_price_certified"] is True
    assert factor["reference_price_provenance_state"] == (
        "CERTIFIED_SAME_ISIN_CANONICAL_PRIOR_CLOSE"
    )
    assert "FACTOR_CERTIFIED_REFERENCE_PRICE" in CERTIFIED_FACTOR_STATES


def test_missing_isin_reference_stays_provisional_and_not_cumulative(
    tmp_path: Path,
) -> None:
    factor = _derive(tmp_path, candle_isin=None)

    assert factor["factor_state"] == FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE
    assert factor["reference_price_certified"] is False
    assert factor["reference_price_provenance_state"] == "PRIOR_ISIN_MISSING"
    cumulative = cumulative_factors((factor,))
    assert cumulative[0]["backward_cumulative_price_factor"] is None
    assert cumulative[0]["cumulative_quantity_factor"] is None


def test_mismatched_isin_reference_stays_provisional(tmp_path: Path) -> None:
    factor = _derive(tmp_path, candle_isin="INE000A01029")

    assert factor["factor_state"] == FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE
    assert factor["reference_price_provenance_state"] == "PRIOR_ISIN_MISMATCH"
    assert factor["reference_price_certified"] is False


def test_certified_rights_terp_is_governed_official_term_factor() -> None:
    event = {
        "ratio_numerator": 1.0,
        "ratio_denominator": 4.0,
        "rights_price": 50.0,
    }
    term_factor, formula = _official_term_factor(
        event,
        "RIGHTS",
        reference_price=100.0,
    )

    assert term_factor == pytest.approx(0.9)
    assert formula is not None and "reference_price" in formula
    classification, repair, _ = _classify(
        result={},
        action_type="RIGHTS",
        official_factor=0.9,
        term_factor=0.9,
        term_match=True,
        selected_series="EQ",
        selected_metrics={"open_adjusted_gap_atr": 4.0, "open_raw_gap_atr": 3.0},
        best_series={"series": "EQ", "open_adjusted_gap_atr": 4.0},
        close_basis={"close_adjusted_gap_atr": 4.0},
        best_inverse={"open_adjusted_gap_atr": 6.0},
        best_date={"candidate_date": "2015-01-05", "open_adjusted_gap_atr": 4.0},
        effective=date(2015, 1, 5),
        best_same_day=None,
        same_day_factor_count=1,
        reference_price_certified=True,
    )
    assert classification == "RESIDUAL_MARKET_GAP_NOT_FACTOR_ERROR"
    assert repair == "RETAIN_CERTIFIED_TERP_CLASSIFY_RESIDUAL_AS_MARKET_GAP"


def test_b1d2_accepts_only_reference_certified_rights_terms() -> None:
    certified = _repair_case(
        {
            "bridge_type": "STABLE_SECURITY_SERIES",
            "bridge_classification": "STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT",
            "bridge_raw_gap_atr": 3.0,
            "bridge_adjusted_gap_atr": 4.0,
            "b1d_official_term_factor_matches": True,
            "b1d_reference_price_certified": True,
            "action_type": "RIGHTS",
        },
        {"factor_count": 1},
    )
    provisional = _repair_case(
        {
            "bridge_type": "STABLE_SECURITY_SERIES",
            "bridge_classification": "STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT",
            "bridge_raw_gap_atr": 3.0,
            "bridge_adjusted_gap_atr": 4.0,
            "b1d_official_term_factor_matches": True,
            "b1d_reference_price_certified": False,
            "action_type": "RIGHTS",
        },
        {"factor_count": 1},
    )

    assert certified["factor_quality_confirmed"] is True
    assert certified["proposed_validation_outcome"] == (
        "FACTOR_CONFIRMED_CORRECT_MARKET_GAP"
    )
    assert provisional["factor_quality_confirmed"] is False
