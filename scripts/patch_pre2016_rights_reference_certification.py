from __future__ import annotations

from pathlib import Path

MODELS = Path("alpha/historical_truth/complete_corporate_action_models.py")
ENGINE = Path("alpha/historical_truth/complete_corporate_action_engine.py")
CONTINUITY = Path(
    "alpha/historical_truth/adjustment_replay_admission_continuity_validation.py"
)
FORENSICS = Path("alpha/historical_truth/factor_transformation_forensics.py")
BRIDGE = Path("alpha/historical_truth/factor_transformation_bridge_forensics.py")
REPAIR = Path("alpha/historical_truth/bridge_aware_factor_validation_repair.py")
TEST = Path("tests/historical_truth/test_pre2016_rights_reference_certification.py")


def replace_once(text: str, old: str, new: str, code: str) -> str:
    if old not in text:
        raise RuntimeError(code)
    return text.replace(old, new, 1)


def replace_function(text: str, start: str, end: str, new: str, code: str) -> str:
    left = text.find(start)
    right = text.find(end, left)
    if left < 0 or right < 0:
        raise RuntimeError(code)
    return text[:left] + new + text[right:]


def main() -> None:
    text = MODELS.read_text(encoding="utf-8")
    text = text.replace('HTR010B_CONTRACT_VERSION = "HTR-010B-v1.0.0"', 'HTR010B_CONTRACT_VERSION = "HTR-010B-v1.1.0"')
    text = text.replace('ADJUSTMENT_POLICY_VERSION = "HTR-010B-ADJUSTMENT-v1.0.0"', 'ADJUSTMENT_POLICY_VERSION = "HTR-010B-ADJUSTMENT-v1.1.0"')
    text = replace_once(
        text,
        '    FACTOR_CERTIFIED = "FACTOR_CERTIFIED"\n',
        '    FACTOR_CERTIFIED = "FACTOR_CERTIFIED"\n'
        '    FACTOR_CERTIFIED_REFERENCE_PRICE = "FACTOR_CERTIFIED_REFERENCE_PRICE"\n',
        "RIGHTS_REFERENCE_FACTOR_STATE_BOUNDARY_MISSING",
    )
    MODELS.write_text(text, encoding="utf-8")

    text = ENGINE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "        factors = derive_factors(self.database_path, canonical, actions_by_id)\n",
        "        factors = derive_factors(\n"
        "            self.database_path, canonical, actions_by_id, admitted\n"
        "        )\n",
        "RIGHTS_DERIVE_CALL_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        "        FactorState.FACTOR_DERIVED_OFFICIAL_TERMS,\n"
        "        FactorState.FACTOR_CERTIFIED,\n",
        "        FactorState.FACTOR_DERIVED_OFFICIAL_TERMS,\n"
        "        FactorState.FACTOR_CERTIFIED,\n"
        "        FactorState.FACTOR_CERTIFIED_REFERENCE_PRICE,\n",
        "RIGHTS_EVENT_ADMISSION_STATE_BOUNDARY_MISSING",
    )
    text = replace_function(
        text,
        "def derive_factors(\n",
        "\n\ndef cumulative_factors(",
        '''def derive_factors(
    database_path: Path,
    events: tuple[dict[str, Any], ...],
    actions_by_id: dict[str, CorporateActionEvent],
    joins: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    engine = AdjustmentFactorEngine()
    factors = []
    with duckdb.connect(str(database_path), read_only=True) as connection:
        for event in events:
            source_ids = event["raw_record_ids"]
            source = actions_by_id.get(str(source_ids[0])) if source_ids else None
            if source is None:
                continue
            reference = None
            provenance: dict[str, Any] = {
                "reference_price_date": None,
                "reference_price_series": None,
                "reference_price_isin": None,
                "reference_price_source_sha256": None,
                "reference_price_provenance_state": "NOT_APPLICABLE",
                "reference_price_certified": False,
            }
            if source.action_type is CorporateActionType.RIGHTS:
                reference, provenance = _rights_reference_context(
                    connection,
                    source=source,
                    event=event,
                    join=joins.get(str(event["governed_identity_id"]), {}),
                )
            factor = engine.derive(source, reference_price=reference)
            state = map_factor_state(source, normalize_action(source))
            if source.action_type is CorporateActionType.RIGHTS:
                if factor.price_factor is None:
                    state = FactorState.FACTOR_UNKNOWN_MISSING_TERMS
                elif provenance["reference_price_certified"]:
                    state = FactorState.FACTOR_CERTIFIED_REFERENCE_PRICE
                else:
                    state = FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE
            factors.append(
                {
                    "factor_id": stable_id(
                        "htr010b-factor", event["canonical_event_id"], "BACKWARD"
                    ),
                    "canonical_event_id": event["canonical_event_id"],
                    "identity_key": event["governed_identity_id"],
                    "effective_date": event["effective_date"],
                    "price_factor": factor.price_factor,
                    "quantity_factor": factor.quantity_factor,
                    "reference_price": reference,
                    **provenance,
                    "factor_state": state.value,
                    "calculation_version": ADJUSTMENT_POLICY_VERSION,
                    "explanation": factor.explanation,
                }
            )
    return tuple(
        sorted(
            factors,
            key=lambda row: (
                row["identity_key"],
                row["effective_date"],
                row["factor_id"],
            ),
        )
    )


def _rights_reference_context(
    connection: duckdb.DuckDBPyConnection,
    *,
    source: CorporateActionEvent,
    event: dict[str, Any],
    join: dict[str, Any],
) -> tuple[float | None, dict[str, Any]]:
    applicable = tuple(
        str(item).upper() for item in event.get("series_applicability", ())
    )
    row = connection.execute(
        "SELECT trading_date, upper(coalesce(isin, '')), close_price, "
        "coalesce(source_sha256, '') FROM daily_candle "
        "WHERE upper(symbol)=? AND upper(series)=? AND trading_date<? "
        "ORDER BY trading_date DESC LIMIT 1",
        [source.symbol.upper(), source.series.upper(), source.effective_date],
    ).fetchone()
    prior_date = row[0] if row else None
    prior_isin = str(row[1]) if row else ""
    close = float(row[2]) if row and row[2] is not None else None
    source_sha = str(row[3]) if row else ""
    event_isin = str(source.isin or "").upper()

    if not join.get("admitted_to_certified_join"):
        state = "A3_JOIN_NOT_ADMITTED"
    elif len(applicable) != 1 or applicable[0] != source.series.upper():
        state = "SERIES_NOT_UNIQUE"
    elif row is None:
        state = "PRIOR_CANDLE_MISSING"
    elif close is None or close <= 0:
        state = "PRIOR_CLOSE_INVALID"
    elif not source_sha:
        state = "SOURCE_SHA256_MISSING"
    elif not event_isin:
        state = "EVENT_ISIN_MISSING"
    elif not prior_isin:
        state = "PRIOR_ISIN_MISSING"
    elif prior_isin != event_isin:
        state = "PRIOR_ISIN_MISMATCH"
    else:
        state = "CERTIFIED_SAME_ISIN_CANONICAL_PRIOR_CLOSE"

    certified = state == "CERTIFIED_SAME_ISIN_CANONICAL_PRIOR_CLOSE"
    return close, {
        "reference_price_date": prior_date.isoformat() if prior_date else None,
        "reference_price_series": source.series.upper(),
        "reference_price_isin": prior_isin or None,
        "reference_price_source_sha256": source_sha or None,
        "reference_price_provenance_state": state,
        "reference_price_certified": certified,
    }
''',
        "RIGHTS_DERIVE_FUNCTION_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        "                FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value,\n"
        "                FactorState.FACTOR_AMBIGUOUS_TERMS.value,\n"
        "                FactorState.FACTOR_CONFLICTING_EVENTS.value,\n",
        "                FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value,\n"
        "                FactorState.FACTOR_AMBIGUOUS_TERMS.value,\n"
        "                FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE.value,\n"
        "                FactorState.FACTOR_CONFLICTING_EVENTS.value,\n",
        "RIGHTS_CUMULATIVE_QUARANTINE_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        "                FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value,\n"
        "                FactorState.FACTOR_AMBIGUOUS_TERMS.value,\n"
        "                FactorState.FACTOR_NOT_MULTIPLICATIVE.value,\n",
        "                FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value,\n"
        "                FactorState.FACTOR_AMBIGUOUS_TERMS.value,\n"
        "                FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE.value,\n"
        "                FactorState.FACTOR_NOT_MULTIPLICATIVE.value,\n",
        "RIGHTS_PRICE_BASIS_QUARANTINE_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        "        unknown = counts[FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value]\n"
        "        ambiguous = counts[FactorState.FACTOR_AMBIGUOUS_TERMS.value]\n",
        "        unknown = counts[FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value]\n"
        "        ambiguous = counts[FactorState.FACTOR_AMBIGUOUS_TERMS.value]\n"
        "        provisional = counts[\n"
        "            FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE.value\n"
        "        ]\n",
        "RIGHTS_COVERAGE_PROVISIONAL_COUNT_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        "        elif unknown or ambiguous:\n",
        "        elif unknown or ambiguous or provisional:\n",
        "RIGHTS_COVERAGE_PARTIAL_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        "                \"certified_factor_count\": counts[FactorState.FACTOR_CERTIFIED.value],\n",
        "                \"certified_factor_count\": counts[FactorState.FACTOR_CERTIFIED.value],\n"
        "                \"reference_certified_factor_count\": counts[\n"
        "                    FactorState.FACTOR_CERTIFIED_REFERENCE_PRICE.value\n"
        "                ],\n",
        "RIGHTS_COVERAGE_CERTIFIED_COUNT_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        "                FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value,\n"
        "                FactorState.FACTOR_AMBIGUOUS_TERMS.value,\n"
        "                FactorState.FACTOR_NOT_MULTIPLICATIVE.value,\n",
        "                FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value,\n"
        "                FactorState.FACTOR_AMBIGUOUS_TERMS.value,\n"
        "                FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE.value,\n"
        "                FactorState.FACTOR_NOT_MULTIPLICATIVE.value,\n",
        "RIGHTS_REPLAY_QUARANTINE_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        "        FactorState.FACTOR_CERTIFIED.value,\n"
        "        FactorState.FACTOR_DERIVED_OFFICIAL_TERMS.value,\n",
        "        FactorState.FACTOR_CERTIFIED.value,\n"
        "        FactorState.FACTOR_CERTIFIED_REFERENCE_PRICE.value,\n"
        "        FactorState.FACTOR_DERIVED_OFFICIAL_TERMS.value,\n",
        "RIGHTS_YTD_DERIVED_STATE_BOUNDARY_MISSING",
    )
    ENGINE.write_text(text, encoding="utf-8")

    text = CONTINUITY.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "FACTOR_CERTIFIED",\n',
        '        "FACTOR_CERTIFIED",\n        "FACTOR_CERTIFIED_REFERENCE_PRICE",\n',
        "RIGHTS_B1_CERTIFIED_STATE_BOUNDARY_MISSING",
    )
    CONTINUITY.write_text(text, encoding="utf-8")

    text = FORENSICS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    term_factor, term_formula = _official_term_factor(event, action_type)\n",
        "    reference_price = _number(factor.get(\"reference_price\"))\n"
        "    reference_price_certified = factor.get(\"reference_price_certified\") is True\n"
        "    term_factor, term_formula = _official_term_factor(\n"
        "        event, action_type, reference_price=reference_price\n"
        "    )\n",
        "RIGHTS_FORENSIC_TERM_CALL_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        "        same_day_factor_count=len(same_day_factors),\n"
        "    )\n",
        "        same_day_factor_count=len(same_day_factors),\n"
        "        reference_price_certified=reference_price_certified,\n"
        "    )\n",
        "RIGHTS_FORENSIC_CLASSIFY_CALL_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        '        "official_term_factor_matches": term_match,\n',
        '        "official_term_factor_matches": term_match,\n'
        '        "reference_price": reference_price,\n'
        '        "reference_price_date": factor.get("reference_price_date"),\n'
        '        "reference_price_isin": factor.get("reference_price_isin"),\n'
        '        "reference_price_source_sha256": factor.get(\n'
        '            "reference_price_source_sha256"\n'
        '        ),\n'
        '        "reference_price_provenance_state": factor.get(\n'
        '            "reference_price_provenance_state"\n'
        '        ),\n'
        '        "reference_price_certified": reference_price_certified,\n',
        "RIGHTS_FORENSIC_OUTPUT_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        "    same_day_factor_count: int,\n"
        ") -> tuple[str, str, dict[str, Any]]:\n",
        "    same_day_factor_count: int,\n"
        "    reference_price_certified: bool = False,\n"
        ") -> tuple[str, str, dict[str, Any]]:\n",
        "RIGHTS_FORENSIC_SIGNATURE_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        "    if action_type == \"RIGHTS\":\n"
        "        return (\n"
        "            \"RIGHTS_REFERENCE_PRICE_BASIS_UNCERTAIN\",\n",
        "    if (\n"
        "        action_type == \"RIGHTS\"\n"
        "        and reference_price_certified\n"
        "        and term_match is True\n"
        "    ):\n"
        "        return (\n"
        "            \"RESIDUAL_MARKET_GAP_NOT_FACTOR_ERROR\",\n"
        "            \"RETAIN_CERTIFIED_TERP_CLASSIFY_RESIDUAL_AS_MARKET_GAP\",\n"
        "            evidence,\n"
        "        )\n"
        "    if action_type == \"RIGHTS\":\n"
        "        return (\n"
        "            \"RIGHTS_REFERENCE_PRICE_BASIS_UNCERTAIN\",\n",
        "RIGHTS_FORENSIC_CLASSIFICATION_BOUNDARY_MISSING",
    )
    text = replace_function(
        text,
        "def _official_term_factor(\n",
        "\n\ndef _series_metrics(",
        '''def _official_term_factor(
    event: dict[str, Any],
    action_type: str,
    *,
    reference_price: float | None = None,
) -> tuple[float | None, str | None]:
    numerator = _number(event.get("ratio_numerator"))
    denominator = _number(event.get("ratio_denominator"))
    old_face = _number(event.get("old_face_value"))
    new_face = _number(event.get("new_face_value"))
    if action_type in {"SPLIT", "FACE_VALUE_CHANGE"}:
        if old_face and new_face and old_face > 0 and new_face > 0:
            return new_face / old_face, "new_face_value / old_face_value"
        if numerator and denominator and numerator > 0 and denominator > 0:
            return denominator / numerator, "ratio_denominator / ratio_numerator"
    if action_type == "BONUS" and numerator and denominator:
        if numerator > 0 and denominator > 0:
            factor = denominator / (numerator + denominator)
            formula = "ratio_denominator / (ratio_numerator + ratio_denominator)"
            if old_face is not None:
                if not new_face or old_face <= 0 or new_face <= 0:
                    return None, None
                factor *= new_face / old_face
                formula += " * new_face_value / old_face_value"
            return factor, formula
    if action_type == "RIGHTS" and numerator and denominator:
        rights_price = _number(event.get("rights_price"))
        if (
            numerator > 0
            and denominator > 0
            and rights_price is not None
            and rights_price >= 0
            and reference_price is not None
            and reference_price > 0
        ):
            terp = (
                denominator * reference_price + numerator * rights_price
            ) / (denominator + numerator)
            return terp / reference_price, (
                "((ratio_denominator * reference_price) + "
                "(ratio_numerator * rights_price)) / "
                "(ratio_denominator + ratio_numerator) / reference_price"
            )
    return None, None
''',
        "RIGHTS_FORENSIC_TERM_FUNCTION_BOUNDARY_MISSING",
    )
    FORENSICS.write_text(text, encoding="utf-8")

    text = BRIDGE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "b1d_official_term_factor_matches": case.get("official_term_factor_matches"),\n',
        '        "b1d_official_term_factor_matches": case.get("official_term_factor_matches"),\n'
        '        "b1d_reference_price_certified": case.get("reference_price_certified"),\n'
        '        "b1d_reference_price_provenance_state": case.get(\n'
        '            "reference_price_provenance_state"\n'
        '        ),\n',
        "RIGHTS_BRIDGE_PROVENANCE_BOUNDARY_MISSING",
    )
    BRIDGE.write_text(text, encoding="utf-8")

    text = REPAIR.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "        and str(row.get(\"action_type\") or \"\") in {\"BONUS\", \"SPLIT\", \"FACE_VALUE_CHANGE\"}\n"
        "    ):\n",
        "        and (\n"
        "            str(row.get(\"action_type\") or \"\")\n"
        "            in {\"BONUS\", \"SPLIT\", \"FACE_VALUE_CHANGE\"}\n"
        "            or (\n"
        "                str(row.get(\"action_type\") or \"\") == \"RIGHTS\"\n"
        "                and row.get(\"b1d_reference_price_certified\") is True\n"
        "            )\n"
        "        )\n"
        "    ):\n",
        "RIGHTS_B1D2_PROVENANCE_BOUNDARY_MISSING",
    )
    REPAIR.write_text(text, encoding="utf-8")

    TEST.write_text(
        '''from __future__ import annotations

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
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
