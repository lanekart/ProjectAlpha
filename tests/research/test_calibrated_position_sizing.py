from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from alpha.research.calibrated_position_sizing import (
    CompletedSizingTrade,
    ExitTemplate,
    SizingAuditConfig,
    SizingPolicy,
    TradeTemplate,
    assign_walk_forward_score_tiers,
    calibration_estimate,
    simulate_policy,
    sizing_decision,
)


def _template(
    index: int,
    *,
    score: Decimal | None = None,
    signal_date: date | None = None,
    entry_date: date | None = None,
    exit_date: date | None = None,
    security_id: str | None = None,
    score_tier: str = "UNSEASONED",
) -> TradeTemplate:
    signal = signal_date or date(2024, 1, 1) + timedelta(days=index)
    entry = entry_date or signal + timedelta(days=1)
    exit_on = exit_date or entry + timedelta(days=1)
    identity = security_id or f"INE{index:09d}"
    return TradeTemplate(
        trade_id=f"T{index:03d}",
        security_id=identity,
        symbol=f"S{index}",
        signal_date=signal,
        entry_date=entry,
        exit_date=exit_on,
        baseline_quantity=200,
        entry_price=Decimal("100"),
        initial_stop=Decimal("95"),
        recommendation_score=score or Decimal(index),
        final_signal="BUY",
        score_tier=score_tier,
        baseline_gross_return_percent=Decimal("10"),
        baseline_realized_r=Decimal("2"),
        exit_legs=(
            ExitTemplate(
                exit_date=exit_on,
                baseline_quantity=200,
                exit_price=Decimal("110"),
                reason="TARGET",
                ambiguous_session=False,
            ),
        ),
    )


def _completed(
    index: int,
    *,
    realized_r: Decimal,
    exit_date: date,
    tier: str = "MID",
) -> CompletedSizingTrade:
    pnl = realized_r * Decimal("500")
    proceeds = Decimal("10000") + pnl
    return CompletedSizingTrade(
        policy=SizingPolicy.FLAT_1PCT_REFERENCE.value,
        trade_id=f"C{index:03d}",
        security_id=f"INEC{index:08d}",
        symbol=f"C{index}",
        signal_date=exit_date - timedelta(days=2),
        entry_date=exit_date - timedelta(days=1),
        exit_date=exit_date,
        recommendation_score=Decimal("50"),
        final_signal="BUY",
        score_tier=tier,
        original_quantity=100,
        entry_price=Decimal("100"),
        initial_stop=Decimal("95"),
        gross_profit_loss=pnl,
        gross_return_percent=(proceeds / Decimal("10000") - 1) * Decimal("100"),
        realized_r=realized_r,
        requested_risk_fraction=Decimal("0.01"),
        effective_risk_fraction=Decimal("0.01"),
        posterior_success_probability=None,
        expected_r=None,
        kelly_fraction=None,
        calibration_history_count=0,
        calibration_bucket_count=0,
        calibration_source="TEST",
        fallback_reason=None,
        final_exit_reason="TEST",
        exit_records=(),
    )


def test_score_tiers_use_only_prior_signal_dates() -> None:
    same_day = date(2024, 1, 4)
    templates = (
        _template(1, score=Decimal("10"), signal_date=date(2024, 1, 1)),
        _template(2, score=Decimal("20"), signal_date=date(2024, 1, 2)),
        _template(3, score=Decimal("30"), signal_date=date(2024, 1, 3)),
        _template(4, score=Decimal("5"), signal_date=same_day),
        _template(5, score=Decimal("40"), signal_date=same_day),
    )

    assigned = assign_walk_forward_score_tiers(templates, minimum_history=3)
    tiers = {item.trade_id: item.score_tier for item in assigned}

    assert tiers["T001"] == "UNSEASONED"
    assert tiers["T002"] == "UNSEASONED"
    assert tiers["T003"] == "UNSEASONED"
    assert tiers["T004"] == "LOW"
    assert tiers["T005"] == "HIGH"


def test_calibration_excludes_same_day_outcomes() -> None:
    config = replace(
        SizingAuditConfig(),
        minimum_bucket_history=1,
        minimum_completed_history=1,
    )
    template = _template(
        10,
        entry_date=date(2024, 2, 10),
        score_tier="MID",
    )
    completed = (
        _completed(1, realized_r=Decimal("2"), exit_date=date(2024, 2, 9)),
        _completed(2, realized_r=Decimal("-1"), exit_date=date(2024, 2, 10)),
    )

    estimate = calibration_estimate(template, completed, config)

    assert estimate.history_count == 1
    assert estimate.bucket_history_count == 1
    assert estimate.posterior_success_probability == Decimal("0.6")
    assert estimate.expected_r == Decimal("0.8")


def test_score_tiered_policy_maps_low_mid_high_risk() -> None:
    config = SizingAuditConfig()
    completed: tuple[CompletedSizingTrade, ...] = ()

    low = sizing_decision(
        SizingPolicy.SCORE_TIERED,
        _template(1, score_tier="LOW"),
        completed,
        config,
    )
    mid = sizing_decision(
        SizingPolicy.SCORE_TIERED,
        _template(2, score_tier="MID"),
        completed,
        config,
    )
    high = sizing_decision(
        SizingPolicy.SCORE_TIERED,
        _template(3, score_tier="HIGH"),
        completed,
        config,
    )

    assert low.requested_risk_fraction == Decimal("0.005")
    assert mid.requested_risk_fraction == Decimal("0.01")
    assert high.requested_risk_fraction == Decimal("0.015")


def test_walk_forward_edge_raises_and_reduces_risk() -> None:
    config = replace(
        SizingAuditConfig(),
        minimum_completed_history=4,
        minimum_bucket_history=2,
    )
    entry = date(2024, 3, 10)
    high_history = tuple(
        _completed(
            index, realized_r=Decimal("2"), exit_date=entry - timedelta(days=index)
        )
        for index in range(1, 5)
    )
    low_history = tuple(
        _completed(
            index, realized_r=Decimal("-1"), exit_date=entry - timedelta(days=index)
        )
        for index in range(1, 5)
    )
    template = _template(10, entry_date=entry, score_tier="MID")

    high = sizing_decision(
        SizingPolicy.WALK_FORWARD_EDGE,
        template,
        high_history,
        config,
    )
    low = sizing_decision(
        SizingPolicy.WALK_FORWARD_EDGE,
        template,
        low_history,
        config,
    )

    assert high.requested_risk_fraction == Decimal("0.015")
    assert low.requested_risk_fraction == Decimal("0.005")


def test_fractional_kelly_is_capped_and_floored() -> None:
    config = replace(
        SizingAuditConfig(),
        minimum_completed_history=4,
        minimum_bucket_history=2,
    )
    entry = date(2024, 4, 10)
    strong = (
        _completed(1, realized_r=Decimal("2"), exit_date=date(2024, 4, 1)),
        _completed(2, realized_r=Decimal("2.1"), exit_date=date(2024, 4, 2)),
        _completed(3, realized_r=Decimal("1.9"), exit_date=date(2024, 4, 3)),
        _completed(4, realized_r=Decimal("2"), exit_date=date(2024, 4, 4)),
    )
    weak = tuple(
        _completed(index, realized_r=Decimal("-1"), exit_date=date(2024, 4, index))
        for index in range(1, 5)
    )
    template = _template(20, entry_date=entry, score_tier="MID")

    high = sizing_decision(
        SizingPolicy.FRACTIONAL_KELLY,
        template,
        strong,
        config,
    )
    low = sizing_decision(
        SizingPolicy.FRACTIONAL_KELLY,
        template,
        weak,
        config,
    )

    assert high.requested_risk_fraction == Decimal("0.015")
    assert low.requested_risk_fraction == Decimal("0.005")


def test_aggregate_risk_cap_blocks_third_simultaneous_position() -> None:
    entry = date(2024, 5, 2)
    exit_on = date(2024, 5, 3)
    templates = tuple(
        _template(
            index,
            signal_date=date(2024, 5, 1),
            entry_date=entry,
            exit_date=exit_on,
            security_id=f"INECAP{index:06d}",
            score_tier="HIGH",
        )
        for index in range(1, 4)
    )
    price_map = {
        (trading_day, template.security_id): (Decimal("100"), Decimal("100"))
        for trading_day in (entry, exit_on)
        for template in templates
    }
    config = replace(
        SizingAuditConfig(),
        initial_capital=Decimal("100000"),
        aggregate_open_risk_cap=Decimal("0.03"),
        hard_stop_percent=Decimal("99"),
        drawdown_throttle_percent=Decimal("90"),
    )

    result = simulate_policy(
        policy=SizingPolicy.UNIFORM_1_5PCT,
        templates=templates,
        trading_dates=(entry, exit_on),
        price_map=price_map,
        config=config,
    )

    assert len(result.trades) == 2
    assert len(result.rejected_entries) == 1
    assert result.rejected_entries[0]["reason"] == "RISK_CAPACITY_EXHAUSTED"


def test_flat_reference_replays_fixed_trade_path() -> None:
    entry = date(2024, 6, 2)
    exit_on = date(2024, 6, 3)
    template = _template(
        1,
        signal_date=date(2024, 6, 1),
        entry_date=entry,
        exit_date=exit_on,
        score_tier="UNSEASONED",
    )
    price_map = {
        (entry, template.security_id): (Decimal("100"), Decimal("100")),
        (exit_on, template.security_id): (Decimal("110"), Decimal("110")),
    }
    config = replace(
        SizingAuditConfig(),
        initial_capital=Decimal("100000"),
        hard_stop_percent=Decimal("99"),
        drawdown_throttle_percent=Decimal("90"),
    )

    result = simulate_policy(
        policy=SizingPolicy.FLAT_1PCT_REFERENCE,
        templates=(template,),
        trading_dates=(entry, exit_on),
        price_map=price_map,
        config=config,
    )

    assert len(result.trades) == 1
    assert result.trades[0].original_quantity == 200
    assert result.trades[0].gross_return_percent == Decimal("10.0000")
    assert result.ending_equity == Decimal("102000")
