from __future__ import annotations

from pathlib import Path

SOURCES = Path("alpha/historical_truth/corporate_action_price_sources.py")
FORENSICS = Path("alpha/historical_truth/factor_transformation_forensics.py")
BRIDGE_REPAIR = Path("alpha/historical_truth/bridge_aware_factor_validation_repair.py")
PROPAGATION = Path("alpha/historical_truth/bridge_aware_admission_state_propagation.py")
TEST = Path("tests/historical_truth/test_pre2016_composite_factor_closure.py")


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
    text = SOURCES.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    if action_type is CorporateActionType.BONUS:
        if numerator is None or denominator is None:
            return AdjustmentFactorState.AMBIGUOUS, None
        if numerator <= 0 or denominator <= 0:
            return AdjustmentFactorState.INVALID, None
        return (
            AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS,
            denominator / (denominator + numerator),
        )
''',
        '''    if action_type is CorporateActionType.BONUS:
        if numerator is None or denominator is None:
            return AdjustmentFactorState.AMBIGUOUS, None
        if numerator <= 0 or denominator <= 0:
            return AdjustmentFactorState.INVALID, None
        factor = denominator / (denominator + numerator)
        if old_face is not None or new_face is not None:
            if old_face is None or new_face is None:
                return AdjustmentFactorState.AMBIGUOUS, None
            if old_face <= 0 or new_face <= 0:
                return AdjustmentFactorState.INVALID, None
            factor *= new_face / old_face
        return AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS, factor
''',
        "PRE2016_COMPOSITE_BONUS_FACTOR_BOUNDARY_MISSING",
    )
    text = replace_function(
        text,
        "def _face_values(value: str) -> tuple[float | None, float | None]:\n",
        "\n\ndef _ratio(value: str)",
        '''def _face_values(value: str) -> tuple[float | None, float | None]:
    normalized = value.replace(",", " ")
    patterns = (
        (
            r"FROM\\s+(?:RS\\.?|RE\\.?)?\\s*([0-9]+(?:\\.[0-9]+)?)"
            r".*?TO\\s+(?:RS\\.?|RE\\.?)?\\s*([0-9]+(?:\\.[0-9]+)?)"
        ),
        (
            r"(?:SPLIT|SUB-DIVISION|SUB DIVISION).*?"
            r"(?:RS\\.?|RE\\.?)?\\s*([0-9]+(?:\\.[0-9]+)?)\\s*(?:/-)?"
            r".*?TO\\s+(?:RS\\.?|RE\\.?)?\\s*"
            r"([0-9]+(?:\\.[0-9]+)?)"
        ),
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match is not None:
            return float(match.group(1)), float(match.group(2))
    return None, None
''',
        "PRE2016_FACE_VALUE_PARSER_BOUNDARY_MISSING",
    )
    SOURCES.write_text(text, encoding="utf-8")

    text = FORENSICS.read_text(encoding="utf-8")
    text = replace_function(
        text,
        "def _official_term_factor(\n",
        "\n\ndef _series_metrics(",
        '''def _official_term_factor(
    event: dict[str, Any], action_type: str
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
            if old_face is not None or new_face is not None:
                if not old_face or not new_face or old_face <= 0 or new_face <= 0:
                    return None, None
                factor *= new_face / old_face
                formula += " * new_face_value / old_face_value"
            return factor, formula
    return None, None
''',
        "PRE2016_FORENSIC_TERM_FACTOR_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        '''    if action_type == "RIGHTS":
        return (
            "RIGHTS_REFERENCE_PRICE_BASIS_UNCERTAIN",
''',
        '''    if action_type in {"BONUS", "SPLIT", "FACE_VALUE_CHANGE"} and term_match is True:
        return (
            "RESIDUAL_MARKET_GAP_NOT_FACTOR_ERROR",
            "RECLASSIFY_AS_MARKET_GAP_WITHOUT_FACTOR_MUTATION",
            evidence,
        )
    if action_type == "RIGHTS":
        return (
            "RIGHTS_REFERENCE_PRICE_BASIS_UNCERTAIN",
''',
        "PRE2016_DETERMINISTIC_TERM_CLASSIFICATION_BOUNDARY_MISSING",
    )
    FORENSICS.write_text(text, encoding="utf-8")

    text = BRIDGE_REPAIR.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    elif (
        bridge_type == "STABLE_SECURITY_SERIES"
        and raw_gap is not None
''',
        '''    elif (
        bridge_type == "STABLE_SECURITY_SERIES"
        and str(row.get("b1d_classification") or "")
        == "RESIDUAL_MARKET_GAP_NOT_FACTOR_ERROR"
    ):
        disposition = "FACTOR_CONFIRMED_BY_GOVERNED_OFFICIAL_TERMS"
        proposed = "FACTOR_CONFIRMED_CORRECT_MARKET_GAP"
        confirmed = True
        repair = "RETAIN_OFFICIAL_FACTOR_CLASSIFY_RESIDUAL_AS_MARKET_GAP"
    elif (
        bridge_type == "STABLE_SECURITY_SERIES"
        and raw_gap is not None
''',
        "PRE2016_B1D2_MARKET_GAP_PROPAGATION_BOUNDARY_MISSING",
    )
    BRIDGE_REPAIR.write_text(text, encoding="utf-8")

    text = PROPAGATION.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''        readiness = propagated_readiness(
            base=base.replay_readiness,
            intervals=intervals,
            reporting=reporting,
            residual_summary=residual_summary,
        )
''',
        '''        readiness = propagated_readiness(
            base=base.replay_readiness,
            intervals=intervals,
            reporting=reporting,
            residual_summary=residual_summary,
            validation_results=base.factor_validation_results,
        )
''',
        "PRE2016_PROPAGATED_READINESS_CALL_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        '''    counts = Counter(str(row["admission_state"]) for row in rows)
    unresolved = counts[AdmissionState.UNRESOLVED.value]
    return tuple(rows), {
''',
        '''    counts = Counter(str(row["admission_state"]) for row in rows)
    unresolved = counts[AdmissionState.UNRESOLVED.value]
    implementation_defects = sum(
        str(row.get("validation_outcome") or "")
        == ValidationOutcome.IMPLEMENTATION_DEFECT.value
        for row in validation_results
    )
    return tuple(rows), {
''',
        "PRE2016_INTERVAL_DEFECT_COUNT_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        '        "implementation_defect_count": int(unresolved > 0),\n',
        '        "implementation_defect_count": implementation_defects,\n',
        "PRE2016_INTERVAL_DEFECT_FIELD_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        '''def propagated_readiness(
    *,
    base: dict[str, Any],
    intervals: tuple[dict[str, Any], ...],
    reporting: dict[str, Any],
    residual_summary: dict[str, Any],
) -> dict[str, Any]:
''',
        '''def propagated_readiness(
    *,
    base: dict[str, Any],
    intervals: tuple[dict[str, Any], ...],
    reporting: dict[str, Any],
    residual_summary: dict[str, Any],
    validation_results: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
''',
        "PRE2016_READINESS_SIGNATURE_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        '''    bridge_count = int(base.get("bridge_uncertified_count", 0) or 0)
    admission_count = int(reporting.get("admission_quarantined_identity_count", 0))
''',
        '''    implementation_defects = sum(
        str(row.get("validation_outcome") or "")
        == ValidationOutcome.IMPLEMENTATION_DEFECT.value
        for row in validation_results
    )
    if implementation_defects:
        blockers.add("FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS")
    else:
        blockers.discard("FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS")
    bridge_count = int(base.get("bridge_uncertified_count", 0) or 0)
    admission_count = int(reporting.get("admission_quarantined_identity_count", 0))
''',
        "PRE2016_READINESS_DEFECT_BLOCKER_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        '        "implementation_defect_count": int(unresolved > 0),\n',
        '        "implementation_defect_count": implementation_defects,\n',
        "PRE2016_READINESS_DEFECT_FIELD_BOUNDARY_MISSING",
    )
    PROPAGATION.write_text(text, encoding="utf-8")

    TEST.write_text(
        '''from __future__ import annotations

import json
from datetime import date
from hashlib import sha256

import pytest

from alpha.historical_truth.adjustment_replay_admission_models import (
    AdmissionState,
    ValidationOutcome,
)
from alpha.historical_truth.bridge_aware_admission_state_propagation import (
    propagated_readiness,
)
from alpha.historical_truth.bridge_aware_factor_validation_repair import _repair_case
from alpha.historical_truth.corporate_action_price_models import CorporateActionSourceSpec
from alpha.historical_truth.corporate_action_price_sources import (
    parse_corporate_action_source,
)
from alpha.historical_truth.factor_transformation_forensics import (
    _classify,
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
    actions = parse_corporate_action_source(
        _spec(year), raw, sha256(raw).hexdigest()
    )[1]
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

    assert minda.old_face_value == pytest.approx(10.0)
    assert minda.new_face_value == pytest.approx(2.0)
    assert minda.adjustment_factor == pytest.approx(0.1)
    assert jbma.old_face_value == pytest.approx(10.0)
    assert jbma.new_face_value == pytest.approx(5.0)
    assert jbma.adjustment_factor == pytest.approx(0.25)


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


def test_pure_bonus_official_arithmetic_is_market_gap_not_defect() -> None:
    factor = 39.0 / 49.0
    classification, repair, _ = _classify(
        result={},
        action_type="BONUS",
        official_factor=factor,
        term_factor=factor,
        term_match=True,
        selected_series="EQ",
        selected_metrics={"open_adjusted_gap_atr": 7.39, "open_raw_gap_atr": 4.18},
        best_series={"series": "EQ", "open_adjusted_gap_atr": 7.39},
        close_basis={"close_adjusted_gap_atr": 8.0},
        best_inverse={"open_adjusted_gap_atr": 9.0},
        best_date={"candidate_date": "2013-11-11", "open_adjusted_gap_atr": 7.39},
        effective=date(2013, 11, 11),
        best_same_day=None,
        same_day_factor_count=1,
    )

    assert classification == "RESIDUAL_MARKET_GAP_NOT_FACTOR_ERROR"
    assert repair == "RECLASSIFY_AS_MARKET_GAP_WITHOUT_FACTOR_MUTATION"


def test_b1d_market_gap_classification_survives_stable_bridge_repair() -> None:
    row = {
        "bridge_type": "STABLE_SECURITY_SERIES",
        "bridge_classification": "STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT",
        "bridge_raw_gap_atr": 4.18,
        "bridge_adjusted_gap_atr": 7.39,
        "b1d_classification": "RESIDUAL_MARKET_GAP_NOT_FACTOR_ERROR",
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
    readiness = propagated_readiness(
        base={"blockers": ["FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS"]},
        intervals=(
            {"admission_state": AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL.value},
        ),
        reporting={},
        residual_summary={"attribution_counts": {}},
        validation_results=defects,
    )

    assert readiness["final_unresolved_interval_count"] == 0
    assert readiness["implementation_defect_count"] == 3
    assert "FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS" in readiness["blockers"]
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
