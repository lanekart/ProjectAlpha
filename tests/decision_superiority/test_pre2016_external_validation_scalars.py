from __future__ import annotations

from alpha.application.decision_superiority_pre2016_external_validation_cli import (
    _percent,
)
from alpha.decision_superiority.pre2016_external_validation import _optional_float
from alpha.decision_superiority.pre2016_external_validation_artifacts import (
    _display,
)


def test_optional_float_accepts_numeric_scalars_and_strings() -> None:
    assert _optional_float(1) == 1.0
    assert _optional_float(1.25) == 1.25
    assert _optional_float("2.5") == 2.5


def test_optional_float_rejects_absent_invalid_and_non_finite_values() -> None:
    assert _optional_float(None) is None
    assert _optional_float("not-a-number") is None
    assert _optional_float(float("nan")) is None
    assert _optional_float(float("inf")) is None


def test_report_display_is_type_safe() -> None:
    assert _display("0.125", percent=True) == "12.50%"
    assert _display(2, percent=False) == "2.0000"
    assert _display(None) == "UNKNOWN"
    assert _display(object())


def test_cli_percent_is_type_safe() -> None:
    assert _percent("0.125") == "12.50%"
    assert _percent(0.5) == "50.00%"
    assert _percent(None) == "UNKNOWN"
    assert _percent(object()) == "UNKNOWN"
