from __future__ import annotations

from collections.abc import Mapping

import pytest

from alpha.decision_superiority.intraday_execution_models import (
    IntradayExecutionError,
)
from alpha.decision_superiority.intraday_execution_population import (
    CONTROL_MECHANISM_ID,
    plan_intraday_population,
)


def _row(
    signal_id: str,
    *,
    identity_key: str = "nse:isin:INE000A01000",
    signal_date: str = "2024-01-02",
    entry_date: str = "2024-01-03",
    mechanism_id: str = CONTROL_MECHANISM_ID,
    fill_state: str = "ENTERED",
    signal_strength: str = "0.75",
) -> dict[str, object]:
    return {
        "mechanism_id": mechanism_id,
        "fill_state": fill_state,
        "signal_id": signal_id,
        "identity_key": identity_key,
        "symbol": "ALPHA",
        "strategy_variant_id": "STRATEGY-1",
        "walk_forward_fold_id": "WF-2024",
        "regime": "BULL",
        "signal_date": signal_date,
        "entry_eligibility_date": entry_date,
        "signal_strength": signal_strength,
        "raw_entry_price": "100.00",
        "entry_price_after_slippage": "100.10",
        "initial_stop": "95.00",
        "target_1": "110.00",
        "target_2": "115.00",
        "maximum_holding_sessions": "20",
        "average_traded_value20": "10000000",
    }


def test_population_uses_only_entered_control_rows_in_overlap() -> None:
    rows: tuple[Mapping[str, object], ...] = (
        _row("SIG-1"),
        _row("SIG-2", mechanism_id="ENTRY-VWAP-RECLAIM"),
        _row("SIG-3", fill_state="LIQUIDITY_REJECTED"),
        _row("SIG-4", entry_date="2021-12-31"),
        _row("SIG-5", entry_date="2025-12-25"),
        _row("SIG-6", identity_key="nse:symbol:ALPHA"),
    )

    result = plan_intraday_population(rows)

    assert [candidate.signal_id for candidate in result.candidates] == ["SIG-1"]
    assert len(result.requests) == 1
    assert result.requests[0].identity_key == "nse:isin:INE000A01000"
    assert result.requests[0].session_date.isoformat() == "2024-01-03"
    assert result.requests[0].signal_ids == ("SIG-1",)
    assert {row["reason"] for row in result.exclusions} == {
        "CONTROL_FILL_NOT_ENTERED",
        "ENTRY_SESSION_BEFORE_INTRADAY_SOURCE_WINDOW",
        "ENTRY_SESSION_AFTER_FROZEN_COMPARISON_END",
        "GOVERNED_IDENTITY_NOT_EXACT_NSE_ISIN",
    }


def test_multiple_candidates_share_one_identity_session_request() -> None:
    result = plan_intraday_population(
        (
            _row("SIG-2", signal_strength="0.60"),
            _row("SIG-1", signal_strength="0.90"),
        )
    )

    assert [candidate.signal_id for candidate in result.candidates] == [
        "SIG-1",
        "SIG-2",
    ]
    assert len(result.requests) == 1
    assert result.requests[0].signal_ids == ("SIG-1", "SIG-2")
    counts = {
        str(row["population"]): int(row["count"])
        for row in result.reconciliation
    }
    assert counts["all_input_rows"] == 2
    assert counts["control_mechanism_rows"] == 2
    assert counts["control_entered_rows"] == 2
    assert counts["intraday_overlap_candidates"] == 2
    assert counts["intraday_unique_requests"] == 1


def test_duplicate_identical_signal_is_deduplicated() -> None:
    row = _row("SIG-1")

    result = plan_intraday_population((row, dict(row)))

    assert len(result.candidates) == 1
    assert result.requests[0].signal_ids == ("SIG-1",)


def test_duplicate_conflicting_signal_fails_closed() -> None:
    with pytest.raises(
        IntradayExecutionError,
        match="DSI013_DUPLICATE_SIGNAL_CONFLICT:SIG-1",
    ):
        plan_intraday_population(
            (
                _row("SIG-1", signal_strength="0.70"),
                _row("SIG-1", signal_strength="0.80"),
            )
        )


def test_entry_session_must_follow_signal_date() -> None:
    with pytest.raises(
        IntradayExecutionError,
        match="DSI013_NON_FORWARD_ENTRY_SESSION:SIG-1",
    ):
        plan_intraday_population(
            (_row("SIG-1", signal_date="2024-01-03", entry_date="2024-01-03"),)
        )


def test_missing_control_mechanism_population_fails_closed() -> None:
    with pytest.raises(
        IntradayExecutionError,
        match="DSI013_CONTROL_MECHANISM_POPULATION_EMPTY",
    ):
        plan_intraday_population(
            (_row("SIG-1", mechanism_id="ENTRY-VWAP-RECLAIM"),)
        )


def test_missing_required_candidate_field_fails_closed() -> None:
    row = _row("SIG-1")
    del row["initial_stop"]

    with pytest.raises(
        IntradayExecutionError,
        match="DSI013_CANDIDATE_FIELD_MISSING:0:initial_stop",
    ):
        plan_intraday_population((row,))
