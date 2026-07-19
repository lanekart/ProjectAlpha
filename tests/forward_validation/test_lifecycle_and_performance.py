from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from alpha.forward_validation.models import (
    PolicyVersion,
    PortfolioValuation,
    PositionEventType,
    PositionStatus,
)
from alpha.forward_validation.performance_tracker import PerformanceTracker
from alpha.forward_validation.position_tracker import PositionTracker
from alpha.forward_validation.shadow_portfolio import ShadowPortfolio
from alpha.forward_validation.validation_registry import ForwardValidationRegistry
from alpha.recommendation_intelligence.models import OHLCVBar


def test_position_lifecycle_enters_and_exits_at_highest_target(
    tmp_path, snapshot_factory
) -> None:  # type: ignore[no-untyped-def]
    snapshot = snapshot_factory(atr_value=None)
    bars = (
        _bar("2026-01-02", high="111", low="95", close="108"),
        _bar("2026-01-03", high="131", low="105", close="125"),
    )
    drafts = PositionTracker().evaluate(
        snapshot=snapshot,
        bars=bars,
        existing_events=(),
        approved_amount=Decimal("1000"),
    )
    registry = ForwardValidationRegistry(tmp_path / "registry.json")
    registry.append_snapshots((snapshot,))
    for draft in drafts:
        registry.append_event(draft)

    event_types = tuple(event.event_type for event in registry.load_events())
    assert event_types[0] is PositionEventType.ENTRY
    assert PositionEventType.TARGET_1_HIT in event_types
    assert PositionEventType.TARGET_2_HIT in event_types
    assert event_types[-1] is PositionEventType.TARGET_3_HIT

    portfolio = ShadowPortfolio().build(
        initial_capital=Decimal("10000"),
        policy_version=PolicyVersion("APPROVAL_POLICY_V1"),
        snapshots=(snapshot,),
        events=registry.load_events(),
        valued_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert portfolio.cash == Decimal("10300")
    assert portfolio.realized_profit_loss == Decimal("300")
    assert portfolio.positions[0].status is PositionStatus.EXITED


def test_same_bar_stop_is_conservative(tmp_path, snapshot_factory) -> None:  # type: ignore[no-untyped-def]
    snapshot = snapshot_factory(atr_value=None)
    drafts = PositionTracker().evaluate(
        snapshot=snapshot,
        bars=(_bar("2026-01-02", high="120", low="89", close="110"),),
        existing_events=(),
        approved_amount=Decimal("1000"),
    )
    exit_events = tuple(
        draft for draft in drafts if draft.event_type is PositionEventType.STOP_HIT
    )
    assert len(exit_events) == 1
    assert exit_events[0].price == Decimal("90")
    assert not any(
        draft.event_type is PositionEventType.TARGET_1_HIT for draft in drafts
    )


def test_pending_entry_expires_when_frozen_window_elapses(snapshot_factory) -> None:  # type: ignore[no-untyped-def]
    snapshot = snapshot_factory(
        trigger_status="WAITING_FOR_CLOSE_ABOVE",
        confirmation_entry=Decimal("105"),
        maximum_holding_days=2,
    )
    drafts = PositionTracker().evaluate(
        snapshot=snapshot,
        bars=(
            _bar("2026-01-02", high="104", low="98", close="103"),
            _bar("2026-01-03", high="104", low="97", close="102"),
        ),
        existing_events=(),
        approved_amount=Decimal("1000"),
    )
    assert tuple(item.event_type for item in drafts) == (
        PositionEventType.ENTRY_MISSED,
    )


def test_performance_metrics_use_realized_events_and_valuation_drawdown(
    tmp_path, snapshot_factory
) -> None:  # type: ignore[no-untyped-def]
    snapshot = snapshot_factory(atr_value=None)
    registry = ForwardValidationRegistry(tmp_path / "registry.json")
    registry.append_snapshots((snapshot,))
    drafts = PositionTracker().evaluate(
        snapshot=snapshot,
        bars=(_bar("2026-01-02", high="131", low="95", close="125"),),
        existing_events=(),
        approved_amount=Decimal("1000"),
    )
    for draft in drafts:
        registry.append_event(draft)
    policy = PolicyVersion("APPROVAL_POLICY_V1")
    valuations = (
        PortfolioValuation(
            valued_at=datetime(2026, 1, 1, tzinfo=UTC),
            policy_version=policy,
            cash=Decimal("10000"),
            invested_value=Decimal("0"),
            portfolio_value=Decimal("10000"),
            realized_profit_loss=Decimal("0"),
            unrealized_profit_loss=Decimal("0"),
            capital_utilization_pct=Decimal("0"),
            event_head_hash="a",
        ),
        PortfolioValuation(
            valued_at=datetime(2026, 1, 2, tzinfo=UTC),
            policy_version=policy,
            cash=Decimal("9800"),
            invested_value=Decimal("0"),
            portfolio_value=Decimal("9800"),
            realized_profit_loss=Decimal("-200"),
            unrealized_profit_loss=Decimal("0"),
            capital_utilization_pct=Decimal("0"),
            event_head_hash="b",
        ),
    )
    metrics = PerformanceTracker().metrics(
        policy_version=policy,
        snapshots=(snapshot,),
        events=registry.load_events(),
        valuations=valuations,
        initial_capital=Decimal("10000"),
    )

    assert metrics.completed_count == 1
    assert metrics.win_rate_pct == Decimal("100.00")
    assert metrics.expectancy_pct == Decimal("30.00")
    assert metrics.maximum_drawdown_pct == Decimal("2.00")


def _bar(day: str, *, high: str, low: str, close: str) -> OHLCVBar:
    return OHLCVBar(
        observed_on=date.fromisoformat(day),
        open_price=Decimal(close),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
        volume=Decimal("100000"),
    )
