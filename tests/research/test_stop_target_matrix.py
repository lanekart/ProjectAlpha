from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from alpha.backtest.research_runner import (
    ResearchBacktestResult,
    ResearchTrade,
)
from alpha.research.lab_models import (
    AlphaSignalSource,
    StopPolicy,
    StopRule,
    StrategyMode,
    TargetPolicy,
    TargetRule,
)
from alpha.research.stop_target_matrix import (
    audit_execution_levels,
    build_frozen_parent,
    matrix_size,
    stop_choices,
    target_choices,
)


def _trade(
    *,
    stop_price: Decimal | None,
    target_price: Decimal | None,
) -> ResearchTrade:
    return ResearchTrade(
        trade_id="TEST-T000001",
        security_id="INE000000001",
        symbol="TEST",
        signal_date=date(2020, 1, 1),
        entry_date=date(2020, 1, 2),
        exit_date=date(2020, 1, 3),
        quantity=10,
        entry_price=Decimal("100"),
        exit_price=Decimal("105"),
        stop_price=stop_price,
        target_price=target_price,
        exit_reason="TIME_EXIT",
        gross_profit_loss=Decimal("50"),
        gross_return_percent=Decimal("5"),
        holding_sessions=1,
        ambiguous_session=False,
        signal_evidence={},
    )


def _result(trade: ResearchTrade) -> ResearchBacktestResult:
    return ResearchBacktestResult(
        trades=(trade,),
        rejected_entries=(),
        equity_curve=(),
        ambiguous_sessions=0,
        starting_capital=Decimal("1000"),
        ending_equity=Decimal("1050"),
    )


def test_matrix_contract_is_exact_five_by_five() -> None:
    assert len(stop_choices()) == 5
    assert len(target_choices()) == 5
    assert matrix_size() == 25
    assert tuple(item.policy_id for item in stop_choices()) == (
        "STOP_FIXED_5",
        "STOP_FIXED_8",
        "STOP_FIXED_10",
        "STOP_ATR_2",
        "STOP_STRUCTURAL_10D",
    )
    assert tuple(item.policy_id for item in target_choices()) == (
        "TARGET_FIXED_10",
        "TARGET_FIXED_20",
        "TARGET_R_2",
        "TARGET_R_3",
        "TARGET_NONE",
    )


def test_frozen_parent_matches_dsi011a_filtered_entry_population() -> None:
    parent = build_frozen_parent(
        start_date=date(2016, 1, 1),
        end_date=date(2026, 7, 28),
    )

    assert parent.strategy_mode is StrategyMode.HYBRID
    assert (
        parent.alpha_signal_source
        is AlphaSignalSource.RETROSPECTIVE_FROZEN_ALPHA_REPLAY
    )
    assert parent.base_signal_source == ("BUY", "STRONG_BUY")
    assert tuple(item.condition_id for item in parent.entry_conditions.conditions) == (
        "RSI_14_ABOVE_50",
        "CLOSE_ABOVE_SMA_200",
        "VOLUME_RATIO_1.5_20",
    )
    assert parent.maximum_holding_sessions == 20
    assert parent.maximum_concurrent_positions == 10
    assert parent.production_influence is False


def test_execution_level_audit_accepts_valid_stop_and_target() -> None:
    spec = replace(
        build_frozen_parent(
            start_date=date(2016, 1, 1),
            end_date=date(2026, 7, 28),
        ),
        stop_policy=StopPolicy(
            rules=(StopRule("FIXED_PERCENT", Decimal("8")),)
        ),
        target_policy=TargetPolicy(
            rules=(TargetRule("R_MULTIPLE", Decimal("2")),)
        ),
    )

    audit = audit_execution_levels(
        _result(_trade(stop_price=Decimal("92"), target_price=Decimal("116"))),
        spec,
    )

    assert audit.valid is True
    assert audit.status == "VALID"


def test_execution_level_audit_fails_closed_for_wrong_side_levels() -> None:
    spec = replace(
        build_frozen_parent(
            start_date=date(2016, 1, 1),
            end_date=date(2026, 7, 28),
        ),
        stop_policy=StopPolicy(
            rules=(StopRule("STOP-STRUCTURAL-10D"),)
        ),
        target_policy=TargetPolicy(
            rules=(TargetRule("R_MULTIPLE", Decimal("2")),)
        ),
    )

    audit = audit_execution_levels(
        _result(_trade(stop_price=Decimal("125"), target_price=Decimal("50"))),
        spec,
    )

    assert audit.valid is False
    assert audit.status == "INVALID_EXECUTION_LEVELS"
    assert audit.invalid_stop_count == 1
    assert audit.invalid_target_count == 1
    assert audit.samples[0]["symbol"] == "TEST"


def test_execution_level_audit_fails_closed_for_missing_requested_levels() -> None:
    spec = replace(
        build_frozen_parent(
            start_date=date(2016, 1, 1),
            end_date=date(2026, 7, 28),
        ),
        stop_policy=StopPolicy(rules=(StopRule("ATR", Decimal("2")),)),
        target_policy=TargetPolicy(
            rules=(TargetRule("R_MULTIPLE", Decimal("3")),)
        ),
    )

    audit = audit_execution_levels(
        _result(_trade(stop_price=None, target_price=None)),
        spec,
    )

    assert audit.valid is False
    assert audit.missing_stop_count == 1
    assert audit.missing_target_count == 1
