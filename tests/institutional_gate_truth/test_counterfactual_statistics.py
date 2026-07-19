from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd

from alpha.institutional_gate_truth.counterfactual import (
    CounterfactualPortfolioEngine,
)
from alpha.institutional_gate_truth.rejection_outcomes import RejectionOutcomeEngine
from alpha.institutional_gate_truth.rejection_reason_analysis import reason_statistics
from tests.institutional_gate_truth.conftest import bars, candidate


def test_counterfactual_enters_every_triggered_rejection() -> None:
    winner = candidate(candidate_id="WIN", symbol="WIN")
    loser = candidate(candidate_id="LOSS", symbol="LOSS")
    frame = pd.concat(
        (
            bars(
                "WIN",
                (
                    ("2024-01-02", "100", "105", "95", "102"),
                    ("2024-01-03", "102", "121", "101", "120"),
                ),
            ),
            bars(
                "LOSS",
                (
                    ("2024-01-02", "100", "105", "95", "102"),
                    ("2024-01-03", "88", "92", "85", "89"),
                ),
            ),
        ),
        ignore_index=True,
    )
    assessments = RejectionOutcomeEngine().evaluate(
        candidates=(winner, loser),
        future_bars=frame,
    )
    trades, curve, statistics = CounterfactualPortfolioEngine().run(
        assessments=assessments,
        future_bars=frame,
        sessions=(date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)),
        starting_capital=Decimal("1000000"),
        round_trip_friction_percent=Decimal("0.30"),
    )
    assert len(trades) == 2
    assert statistics.entered_trades == 2
    assert statistics.winning_trades == 1
    assert statistics.losing_trades == 1
    assert statistics.payoff_ratio is not None
    assert len(curve) == 3


def test_every_failed_gate_reason_receives_statistics() -> None:
    item = candidate()
    frame = bars(
        item.candidate_id,
        (
            ("2024-01-02", "100", "105", "95", "102"),
            ("2024-01-03", "102", "121", "101", "120"),
        ),
    )
    assessment = RejectionOutcomeEngine().evaluate(
        candidates=(item,), future_bars=frame
    )
    rows = reason_statistics(assessment, initial_capital=Decimal("1000000"))
    keys = {(row.reason_scope, row.rejection_reason) for row in rows}
    assert ("PRIMARY", "WEAK_SETUP") in keys
    assert ("ALL_FAILURES", "WEAK_SETUP") in keys
    assert ("ALL_FAILURES", "INSUFFICIENT_EVIDENCE") in keys
