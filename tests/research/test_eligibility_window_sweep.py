from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from alpha.research.eligibility_window_sweep import (
    RISK_POLICIES,
    WINDOWS,
    _reference_parity,
    build_sweep_contract,
    build_window_signals,
)


def _row(
    offset: int,
    *,
    alpha: bool = False,
    technical: bool = False,
    score: int = 0,
    verdict: str | None = None,
    regime: str | None = None,
) -> dict[str, object]:
    return {
        "trading_date": date(2024, 1, 1) + timedelta(days=offset),
        "security_id": "INE000000001",
        "symbol": "TEST",
        "final_signal": verdict,
        "regime": regime,
        "recommendation_score": score,
        "alpha_signal_ok": alpha,
        "long_term_trend_ok": technical,
        "rising_sma20_ok": technical,
        "reclaim_ok": technical,
        "momentum_ok": technical,
        "volume_contraction_ok": technical,
        "volume_expansion_ok": technical,
    }


def test_exact_sweep_contract_is_five_windows_by_two_risk_policies() -> None:
    contract = build_sweep_contract()

    assert WINDOWS == (1, 3, 5, 10, 20)
    assert tuple(item.policy_id for item in RISK_POLICIES) == (
        "FLAT_1PCT",
        "UNIFORM_1_5PCT",
    )
    assert len(contract) == 10
    assert {(window, policy.policy_id) for window, policy in contract} == {
        (window, policy.policy_id)
        for window in WINDOWS
        for policy in RISK_POLICIES
    }


def test_same_session_window_does_not_use_later_technical_trigger() -> None:
    frame = pd.DataFrame(
        [
            _row(0, alpha=True, verdict="BUY", score=80, regime="NEUTRAL"),
            _row(1, technical=True),
        ]
    )

    featured, ledger, audit = build_window_signals(frame, window_sessions=1)

    assert int(featured["research_signal"].sum()) == 0
    assert ledger == []
    assert audit.eligibility_expired_count == 1


def test_three_session_window_allows_trigger_on_third_eligible_session() -> None:
    frame = pd.DataFrame(
        [
            _row(0, alpha=True, verdict="STRONG_BUY", score=91, regime="NEGATIVE"),
            _row(1),
            _row(2, technical=True),
        ]
    )

    featured, ledger, audit = build_window_signals(frame, window_sessions=3)
    trigger = featured.loc[featured["research_signal"]].iloc[0]

    assert len(ledger) == 1
    assert audit.technical_trigger_count == 1
    assert ledger[0]["eligibility_age_sessions"] == 2
    assert ledger[0]["origin_regime"] == "NEGATIVE"
    assert trigger["final_signal"] == "STRONG_BUY"
    assert trigger["recommendation_score"] == 91.0


def test_expired_eligibility_cannot_trigger_on_following_session() -> None:
    frame = pd.DataFrame(
        [
            _row(0, alpha=True, verdict="BUY", score=70, regime="POSITIVE"),
            _row(1),
            _row(2),
            _row(3, technical=True),
        ]
    )

    featured, ledger, audit = build_window_signals(frame, window_sessions=3)

    assert int(featured["research_signal"].sum()) == 0
    assert ledger == []
    assert audit.eligibility_expired_count == 1


def test_new_alpha_signal_supersedes_prior_unconsumed_eligibility() -> None:
    frame = pd.DataFrame(
        [
            _row(0, alpha=True, verdict="BUY", score=60, regime="NEUTRAL"),
            _row(1, alpha=True, verdict="STRONG_BUY", score=95, regime="POSITIVE"),
            _row(2, technical=True),
        ]
    )

    _, ledger, audit = build_window_signals(frame, window_sessions=5)

    assert audit.eligibility_superseded_count == 1
    assert len(ledger) == 1
    assert ledger[0]["alpha_signal_date"] == "2024-01-02"
    assert ledger[0]["final_signal"] == "STRONG_BUY"
    assert ledger[0]["recommendation_score"] == "95"


def test_eligibility_is_consumed_after_first_technical_trigger() -> None:
    frame = pd.DataFrame(
        [
            _row(0, alpha=True, verdict="BUY", score=80, regime="NEUTRAL"),
            _row(1, technical=True),
            _row(2, technical=True),
        ]
    )

    featured, ledger, _ = build_window_signals(frame, window_sessions=5)

    assert int(featured["research_signal"].sum()) == 1
    assert len(ledger) == 1


def test_reference_parity_requires_exact_counts_and_tight_metrics() -> None:
    summary = {
        "signal_count": 68,
        "entry_count": 67,
        "completed_trade_count": 67,
        "gross_total_return_percent": "79.9317",
        "gross_cagr_percent": "5.7140",
        "maximum_drawdown_percent": "-6.9513",
    }
    reference = {"summary": summary}

    passed = _reference_parity(reference, dict(summary))
    failed_summary = dict(summary)
    failed_summary["gross_cagr_percent"] = str(
        Decimal("5.7140") + Decimal("0.0002")
    )
    failed = _reference_parity(reference, failed_summary)

    assert passed["passed"] is True
    assert failed["passed"] is False
