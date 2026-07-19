from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from alpha.forward_validation.models import (
    ForwardRiskControls,
    PolicyVersion,
    PortfolioValuation,
    PositionEvent,
    PositionEventType,
    PositionStatus,
    RecommendationSnapshot,
    ShadowPortfolioSnapshot,
    ShadowPosition,
)

_TWO = Decimal("0.01")
_EXIT_EVENTS = {
    PositionEventType.STOP_HIT,
    PositionEventType.TARGET_3_HIT,
    PositionEventType.TRAILING_STOP_HIT,
    PositionEventType.TIME_EXIT,
    PositionEventType.INVALIDATED,
}


class ShadowPortfolio:
    """Reconstruct virtual accounting solely from immutable evidence."""

    def build(
        self,
        *,
        initial_capital: Decimal,
        policy_version: PolicyVersion,
        snapshots: tuple[RecommendationSnapshot, ...],
        events: tuple[PositionEvent, ...],
        valuations: tuple[PortfolioValuation, ...] = (),
        valued_at: datetime | None = None,
    ) -> ShadowPortfolioSnapshot:
        cohort = tuple(
            snapshot
            for snapshot in snapshots
            if snapshot.policy_version == policy_version
        )
        ids = {snapshot.recommendation_id for snapshot in cohort}
        cohort_events = tuple(
            event for event in events if event.recommendation_id in ids
        )
        position_rows = tuple(
            self._position(snapshot, cohort_events) for snapshot in cohort
        )
        cash = initial_capital + sum(
            (event.cash_delta for event in cohort_events),
            start=Decimal("0"),
        )
        realized = sum(
            (position.realized_profit_loss for position in position_rows),
            start=Decimal("0"),
        )
        unrealized = sum(
            (position.unrealized_profit_loss for position in position_rows),
            start=Decimal("0"),
        )
        invested = sum(
            (
                position.last_price * position.quantity
                for position in position_rows
                if position.status is PositionStatus.ACTIVE
            ),
            start=Decimal("0"),
        )
        total = cash + invested
        utilization = _percent(invested, total)
        cohort_valuations = tuple(
            item for item in valuations if item.policy_version == policy_version
        )
        peak = max(
            (item.portfolio_value for item in cohort_valuations),
            default=max(initial_capital, total),
        )
        drawdown = (
            ((peak - total) / peak * Decimal("100")).quantize(_TWO)
            if peak > Decimal("0")
            else None
        )
        timestamp = valued_at or max(
            (event.occurred_at for event in cohort_events),
            default=datetime.now(tz=UTC),
        )
        prior_value = next(
            (
                item.portfolio_value
                for item in reversed(cohort_valuations)
                if item.valued_at.date() < timestamp.date()
            ),
            None,
        )
        daily_loss = (
            max(
                Decimal("0"),
                (prior_value - total) / prior_value * Decimal("100"),
            ).quantize(_TWO)
            if prior_value is not None and prior_value > Decimal("0")
            else None
        )
        return ShadowPortfolioSnapshot(
            valued_at=timestamp,
            policy_version=policy_version,
            initial_capital=initial_capital,
            cash=cash,
            positions=position_rows,
            realized_profit_loss=realized,
            unrealized_profit_loss=unrealized,
            portfolio_value=total,
            capital_utilization_pct=utilization or Decimal("0"),
            drawdown_pct=drawdown,
            daily_loss_pct=daily_loss,
        )

    def risk_rejection(
        self,
        *,
        portfolio: ShadowPortfolioSnapshot,
        snapshot: RecommendationSnapshot,
        approved_amount: Decimal,
        controls: ForwardRiskControls,
    ) -> str | None:
        active = tuple(
            position
            for position in portfolio.positions
            if position.status is PositionStatus.ACTIVE
        )
        if (
            controls.maximum_simultaneous_positions is not None
            and len(active) >= controls.maximum_simultaneous_positions
        ):
            return "maximum simultaneous positions reached"
        if approved_amount > portfolio.cash:
            return "frozen approved deployment exceeds available shadow cash"
        if controls.maximum_allocation_per_position_pct is not None:
            allocation_pct = _percent(approved_amount, portfolio.portfolio_value)
            if (
                allocation_pct is not None
                and allocation_pct > controls.maximum_allocation_per_position_pct
            ):
                return "maximum allocation per position exceeded"
        if (
            controls.maximum_sector_allocation_pct is not None
            and snapshot.sector is not None
        ):
            sector_value = sum(
                (
                    position.last_price * position.quantity
                    for position in active
                    if position.sector == snapshot.sector
                ),
                start=Decimal("0"),
            )
            sector_pct = _percent(
                sector_value + approved_amount,
                portfolio.portfolio_value,
            )
            if (
                sector_pct is not None
                and sector_pct > controls.maximum_sector_allocation_pct
            ):
                return "maximum sector allocation exceeded"
        if (
            controls.daily_loss_limit_pct is not None
            and portfolio.daily_loss_pct is not None
            and portfolio.daily_loss_pct >= controls.daily_loss_limit_pct
        ):
            return "daily shadow-portfolio loss limit reached"
        if (
            controls.portfolio_drawdown_limit_pct is not None
            and portfolio.drawdown_pct is not None
            and portfolio.drawdown_pct >= controls.portfolio_drawdown_limit_pct
        ):
            return "portfolio drawdown limit reached"
        return None

    def valuation(
        self,
        portfolio: ShadowPortfolioSnapshot,
        *,
        event_head_hash: str,
    ) -> PortfolioValuation:
        invested = sum(
            (
                position.last_price * position.quantity
                for position in portfolio.positions
                if position.status is PositionStatus.ACTIVE
            ),
            start=Decimal("0"),
        )
        return PortfolioValuation(
            valued_at=portfolio.valued_at,
            policy_version=portfolio.policy_version,
            cash=portfolio.cash,
            invested_value=invested,
            portfolio_value=portfolio.portfolio_value,
            realized_profit_loss=portfolio.realized_profit_loss,
            unrealized_profit_loss=portfolio.unrealized_profit_loss,
            capital_utilization_pct=portfolio.capital_utilization_pct,
            event_head_hash=event_head_hash,
        )

    def _position(
        self,
        snapshot: RecommendationSnapshot,
        events: tuple[PositionEvent, ...],
    ) -> ShadowPosition:
        relevant = tuple(
            event
            for event in events
            if event.recommendation_id == snapshot.recommendation_id
        )
        entry = next(
            (
                event
                for event in relevant
                if event.event_type is PositionEventType.ENTRY
            ),
            None,
        )
        exit_event = next(
            (
                event
                for event in reversed(relevant)
                if event.event_type in _EXIT_EVENTS
                or event.metadata.get("terminal") == "true"
            ),
            None,
        )
        target_hits = tuple(
            number
            for number, event_type in (
                (1, PositionEventType.TARGET_1_HIT),
                (2, PositionEventType.TARGET_2_HIT),
                (3, PositionEventType.TARGET_3_HIT),
            )
            if any(event.event_type is event_type for event in relevant)
        )
        if entry is None:
            status = _pending_status(relevant)
            return ShadowPosition(
                recommendation_id=snapshot.recommendation_id,
                symbol=snapshot.symbol,
                sector=snapshot.sector,
                policy_version=snapshot.policy_version,
                status=status,
                quantity=Decimal("0"),
                average_cost=Decimal("0"),
                last_price=snapshot.current_market_price or Decimal("0"),
                entered_at=None,
                exited_at=None,
                realized_profit_loss=Decimal("0"),
                unrealized_profit_loss=Decimal("0"),
                targets_hit=target_hits,
                exit_reason=relevant[-1].reason if relevant else None,
            )
        assert entry.price is not None and entry.quantity is not None
        mark = next(
            (
                event
                for event in reversed(relevant)
                if event.price is not None
                and event.event_type in {PositionEventType.MARK, *_EXIT_EVENTS}
            ),
            entry,
        )
        assert mark.price is not None
        if exit_event is not None:
            assert exit_event.price is not None
            realized = (exit_event.price - entry.price) * entry.quantity
            unrealized = Decimal("0")
            status = (
                PositionStatus.INVALIDATED
                if exit_event.event_type is PositionEventType.INVALIDATED
                else PositionStatus.EXITED
            )
        else:
            realized = Decimal("0")
            unrealized = (mark.price - entry.price) * entry.quantity
            status = PositionStatus.ACTIVE
        return ShadowPosition(
            recommendation_id=snapshot.recommendation_id,
            symbol=snapshot.symbol,
            sector=snapshot.sector,
            policy_version=snapshot.policy_version,
            status=status,
            quantity=entry.quantity,
            average_cost=entry.price,
            last_price=mark.price,
            entered_at=entry.occurred_at,
            exited_at=exit_event.occurred_at if exit_event is not None else None,
            realized_profit_loss=realized,
            unrealized_profit_loss=unrealized,
            targets_hit=target_hits,
            exit_reason=exit_event.reason if exit_event is not None else None,
        )


def _pending_status(events: tuple[PositionEvent, ...]) -> PositionStatus:
    if any(event.event_type is PositionEventType.ENTRY_MISSED for event in events):
        return PositionStatus.MISSED
    if any(event.event_type is PositionEventType.MANUAL_EXPIRY for event in events):
        return PositionStatus.EXPIRED
    if any(event.event_type is PositionEventType.INVALIDATED for event in events):
        return PositionStatus.INVALIDATED
    if any(event.event_type is PositionEventType.RISK_BLOCKED for event in events):
        return PositionStatus.RISK_BLOCKED
    return PositionStatus.PENDING


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= Decimal("0"):
        return None
    return (numerator / denominator * Decimal("100")).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


__all__ = ["ShadowPortfolio"]
