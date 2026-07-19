from __future__ import annotations

from decimal import Decimal

from alpha.strategy_lab.models import ExecutionAssumptionProfile


def default_execution_profile(
    *,
    cost_bps: Decimal = Decimal("20"),
    slippage_bps: Decimal = Decimal("10"),
) -> ExecutionAssumptionProfile:
    """Return an explicit research profile, not a representation of current fees."""

    return ExecutionAssumptionProfile(
        profile_id=f"RESEARCH_EXECUTION_V1_{cost_bps}_{slippage_bps}",
        brokerage_bps=Decimal("0"),
        stt_bps=Decimal("0"),
        exchange_charge_bps=Decimal("0"),
        gst_bps=Decimal("0"),
        stamp_duty_bps=Decimal("0"),
        other_transaction_cost_bps=cost_bps / Decimal("2"),
        slippage_bps=slippage_bps / Decimal("2"),
        bid_ask_impact_bps=Decimal("0"),
        entry_delay_sessions=0,
        entry_validity_sessions=5,
        partial_fill_fraction=Decimal("0.50"),
        capital_per_trade_pct=Decimal("10"),
        gap_through_stop_policy="FILL_AT_OPEN_IF_OPEN_IS_BELOW_STOP",
        ambiguous_bar_policy="STOP_BEFORE_TARGET_CONSERVATIVE",
        rationale=(
            "Versioned research assumptions aligned with the existing discovery "
            "20 bps transaction-cost and 10 bps slippage round trip. Statutory fee "
            "fields remain zero because no current legal fee schedule is asserted."
        ),
        version="strategy-lab-execution-v1",
    )


__all__ = ["default_execution_profile"]
