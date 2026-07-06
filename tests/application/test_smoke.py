from __future__ import annotations

from decimal import Decimal

import pytest

from alpha.application.smoke import SmokeApplication, SmokeInput, run_smoke_application


def test_smoke_application_runs_end_to_end() -> None:
    report = run_smoke_application()

    assert report.processed == 5
    assert report.buy_count >= 1
    assert "Project Alpha Smoke Report" in report.render()


def test_smoke_application_sorts_by_return_descending() -> None:
    app = SmokeApplication()

    report = app.run(
        [
            SmokeInput("AAA", Decimal("100"), Decimal("100")),
            SmokeInput("BBB", Decimal("110"), Decimal("100")),
            SmokeInput("CCC", Decimal("90"), Decimal("100")),
        ]
    )

    assert [result.symbol for result in report.results] == ["BBB", "AAA", "CCC"]


def test_smoke_application_generates_buy_hold_sell_signals() -> None:
    app = SmokeApplication()

    report = app.run(
        [
            SmokeInput("BUYME", Decimal("103"), Decimal("100")),
            SmokeInput("HOLDME", Decimal("101"), Decimal("100")),
            SmokeInput("SELLME", Decimal("97"), Decimal("100")),
        ]
    )

    signals = {result.symbol: result.signal for result in report.results}

    assert signals == {
        "BUYME": "BUY",
        "HOLDME": "HOLD",
        "SELLME": "SELL",
    }


def test_smoke_application_rejects_invalid_previous_close() -> None:
    app = SmokeApplication()

    with pytest.raises(ValueError):
        app.run([SmokeInput("BAD", Decimal("100"), Decimal("0"))])
