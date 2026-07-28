from __future__ import annotations

from pathlib import Path

SOURCE = Path("alpha/historical_truth/corporate_action_price_sources.py")
TEST = Path("tests/historical_truth/test_pre2016_rights_price_terms.py")


def replace_once(text: str, old: str, new: str, code: str) -> str:
    if old not in text:
        raise RuntimeError(code)
    return text.replace(old, new, 1)


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "_rights_price(purpose) if action_type is CorporateActionType.RIGHTS else None",
        (
            "_rights_price(purpose, face_value) "
            "if action_type is CorporateActionType.RIGHTS else None"
        ),
        "PRE2016_RIGHTS_PRICE_CALL_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        '''def _rights_price(value: str) -> float | None:
    matches = re.findall(
        r"(?:AT|@|PRICE(?:\\s+OF)?)\\s*(?:RS\\.?|RE\\.?)?\\s*([0-9]+(?:\\.[0-9]+)?)",
        value,
        flags=re.IGNORECASE,
    )
    return float(matches[-1]) if matches else None
''',
        '''def _rights_price(value: str, face_value: float | None) -> float | None:
    normalized = value.replace(",", " ")
    if re.search(r"(?:\\bAT\\s+PAR\\b|@\\s*PAR\\b)", normalized, re.IGNORECASE):
        return face_value if face_value is not None and face_value > 0 else None

    premium_matches = re.findall(
        r"(?:PREMIUM|PREM)\\s*(?:RS\\.?|RE\\.?|₹)?\\s*"
        r"([0-9]+(?:\\.[0-9]+)?)",
        normalized,
        flags=re.IGNORECASE,
    )
    if premium_matches:
        if face_value is None or face_value <= 0:
            return None
        return face_value + float(premium_matches[-1])

    matches = re.findall(
        r"(?:AT|@|PRICE(?:\\s+OF)?|ISSUE\\s+PRICE(?:\\s+PER\\s+EQUITY\\s+SHARE)?"
        r"(?:\\s+IS)?)\\s*(?:RS\\.?|RE\\.?|₹)?\\s*"
        r"([0-9]+(?:\\.[0-9]+)?)",
        normalized,
        flags=re.IGNORECASE,
    )
    return float(matches[-1]) if matches else None
''',
        "PRE2016_RIGHTS_PRICE_FUNCTION_BOUNDARY_MISSING",
    )
    SOURCE.write_text(text, encoding="utf-8")

    TEST.write_text(
        '''from __future__ import annotations

import json
from datetime import date
from hashlib import sha256

import pytest

from alpha.historical_truth.corporate_action_price_engine import AdjustmentFactorEngine
from alpha.historical_truth.corporate_action_price_models import (
    AdjustmentFactorState,
    CorporateActionSourceSpec,
)
from alpha.historical_truth.corporate_action_price_sources import (
    parse_corporate_action_source,
)


def _action(subject: str, *, face_value: str = "2"):
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
        "isin": "INE000A01010",
        "subject": subject,
        "exDate": "05-Jan-2015",
        "recDate": "06-Jan-2015",
        "caBroadcastDate": "01-Jan-2015",
        "faceVal": face_value,
    }
    raw = json.dumps([row], sort_keys=True).encode()
    actions = parse_corporate_action_source(spec, raw, sha256(raw).hexdigest())[1]
    assert len(actions) == 1
    return actions[0]


def test_rights_premium_is_converted_to_full_issue_price() -> None:
    action = _action(
        "Rights 5:8 @ Premium Rs 48.25/- Per Equity Share",
        face_value="2",
    )

    assert action.ratio_numerator == pytest.approx(5.0)
    assert action.ratio_denominator == pytest.approx(8.0)
    assert action.rights_price == pytest.approx(50.25)
    factor = AdjustmentFactorEngine().derive(action, reference_price=100.0)
    expected = (((8.0 * 100.0) + (5.0 * 50.25)) / 13.0) / 100.0
    assert factor.price_factor == pytest.approx(expected)
    assert factor.state is AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS


def test_rights_at_par_uses_governed_face_value() -> None:
    action = _action("Rights 1:1 At Par", face_value="10")

    assert action.rights_price == pytest.approx(10.0)
    factor = AdjustmentFactorEngine().derive(action, reference_price=100.0)
    assert factor.price_factor == pytest.approx(0.55)


def test_rights_at_par_without_face_value_stays_unknown() -> None:
    action = _action("Rights 1:1 At Par", face_value="")

    assert action.rights_price is None
    factor = AdjustmentFactorEngine().derive(action, reference_price=100.0)
    assert factor.price_factor is None
    assert factor.state is AdjustmentFactorState.UNKNOWN


def test_direct_rights_issue_price_remains_supported() -> None:
    action = _action("Rights 1:4 at Rs 50", face_value="10")

    assert action.rights_price == pytest.approx(50.0)
    factor = AdjustmentFactorEngine().derive(action, reference_price=100.0)
    assert factor.price_factor == pytest.approx(0.9)


def test_dividend_amount_does_not_override_rights_premium() -> None:
    action = _action(
        "Dividend Rs.1.80 Per Share And Rights 1:3 @ Premium Rs.30/- Per Share",
        face_value="2",
    )

    assert action.rights_price == pytest.approx(32.0)


def test_mixed_debt_rights_without_equity_ratio_remains_fail_closed() -> None:
    action = _action(
        "Rights Issue - 1 Ncd (Issue Price Rs.120/- Per Ncd) With 2 Detachable "
        "Warrants (Exercise Price Rs.120/- Per Warrant) For Every 8 Equity Shares",
        face_value="2",
    )

    assert action.ratio_numerator is None
    assert action.ratio_denominator is None
    factor = AdjustmentFactorEngine().derive(action, reference_price=100.0)
    assert factor.price_factor is None
    assert factor.state is AdjustmentFactorState.UNKNOWN
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
