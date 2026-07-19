from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from math import sqrt

from alpha.forward_validation.models import (
    DeploymentReadiness,
    ForwardPerformanceMetrics,
    ForwardValidationReport,
    PolicyVersion,
    PortfolioValuation,
    PositionEvent,
    PositionEventType,
    PositionJournalRow,
    PositionStatus,
    RecommendationSnapshot,
    ShadowPortfolioSnapshot,
    days_between,
)

_TWO = Decimal("0.01")
_EXIT_TYPES = {
    PositionEventType.STOP_HIT,
    PositionEventType.TARGET_3_HIT,
    PositionEventType.TRAILING_STOP_HIT,
    PositionEventType.TIME_EXIT,
    PositionEventType.INVALIDATED,
}


class PerformanceTracker:
    """Calculate policy-isolated metrics from immutable events and valuations."""

    def journal(
        self,
        *,
        snapshots: tuple[RecommendationSnapshot, ...],
        events: tuple[PositionEvent, ...],
    ) -> tuple[PositionJournalRow, ...]:
        rows: list[PositionJournalRow] = []
        for snapshot in snapshots:
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
                    if event.event_type in _EXIT_TYPES
                    or event.metadata.get("terminal") == "true"
                ),
                None,
            )
            return_pct = None
            if (
                entry is not None
                and exit_event is not None
                and entry.price is not None
                and exit_event.price is not None
                and entry.price > Decimal("0")
            ):
                return_pct = _quantize(
                    (exit_event.price - entry.price) / entry.price * Decimal("100")
                )
            rows.append(
                PositionJournalRow(
                    recommendation_id=snapshot.recommendation_id,
                    symbol=snapshot.symbol,
                    policy_version=snapshot.policy_version,
                    generated_at=snapshot.generated_at,
                    status=_journal_status(relevant, entry, exit_event),
                    entry_price=entry.price if entry is not None else None,
                    entry_at=entry.occurred_at if entry is not None else None,
                    exit_price=exit_event.price if exit_event is not None else None,
                    exit_at=(
                        exit_event.occurred_at if exit_event is not None else None
                    ),
                    exit_reason=exit_event.reason
                    if exit_event is not None
                    else (relevant[-1].reason if relevant else None),
                    return_pct=return_pct,
                    supporting_evidence_hash=snapshot.snapshot_hash,
                    event_ids=tuple(event.event_id for event in relevant),
                )
            )
        return tuple(sorted(rows, key=lambda row: (row.generated_at, row.symbol)))

    def metrics(
        self,
        *,
        policy_version: PolicyVersion,
        snapshots: tuple[RecommendationSnapshot, ...],
        events: tuple[PositionEvent, ...],
        valuations: tuple[PortfolioValuation, ...],
        initial_capital: Decimal,
    ) -> ForwardPerformanceMetrics:
        cohort = tuple(
            snapshot
            for snapshot in snapshots
            if snapshot.policy_version == policy_version
        )
        journal = tuple(
            row
            for row in self.journal(snapshots=cohort, events=events)
            if row.policy_version == policy_version
        )
        completed = tuple(
            row
            for row in journal
            if row.status in {PositionStatus.EXITED, PositionStatus.INVALIDATED}
            and row.return_pct is not None
        )
        winners = tuple(
            row.return_pct
            for row in completed
            if row.return_pct is not None and row.return_pct > Decimal("0")
        )
        losers = tuple(
            row.return_pct
            for row in completed
            if row.return_pct is not None and row.return_pct <= Decimal("0")
        )
        returns = tuple(
            row.return_pct for row in completed if row.return_pct is not None
        )
        holding_days = tuple(
            Decimal(str(days_between(row.entry_at, row.exit_at)))
            for row in completed
            if row.entry_at is not None and row.exit_at is not None
        )
        cohort_valuations = tuple(
            sorted(
                (
                    valuation
                    for valuation in valuations
                    if valuation.policy_version == policy_version
                ),
                key=lambda item: item.valued_at,
            )
        )
        valuation_returns = _valuation_returns(cohort_valuations)
        win_rate = _percent(Decimal(len(winners)), Decimal(len(completed)))
        latest = cohort_valuations[-1] if cohort_valuations else None
        cagr = _cagr(
            initial_capital=initial_capital,
            valuations=cohort_valuations,
            started_at=min(
                (snapshot.generated_at for snapshot in cohort),
                default=None,
            ),
        )
        return ForwardPerformanceMetrics(
            policy_version=policy_version,
            recommendation_count=len(cohort),
            entered_count=sum(1 for row in journal if row.entry_at is not None),
            completed_count=len(completed),
            open_count=sum(1 for row in journal if row.status is PositionStatus.ACTIVE),
            missed_count=sum(
                1
                for row in journal
                if row.status
                in {
                    PositionStatus.MISSED,
                    PositionStatus.RISK_BLOCKED,
                }
            ),
            win_rate_pct=win_rate,
            approval_precision_pct=win_rate,
            average_winner_pct=_average(winners),
            average_loser_pct=_average(losers),
            profit_factor=_profit_factor(winners, losers),
            expectancy_pct=_average(returns),
            average_holding_days=_average(holding_days),
            maximum_drawdown_pct=_maximum_drawdown(cohort_valuations),
            consecutive_losses=_maximum_streak(completed, winning=False),
            consecutive_wins=_maximum_streak(completed, winning=True),
            capital_utilization_pct=(
                latest.capital_utilization_pct if latest is not None else None
            ),
            cagr_pct=cagr,
            sharpe_ratio=_sharpe(valuation_returns),
            sortino_ratio=_sortino(valuation_returns),
        )

    def report(
        self,
        *,
        metrics: tuple[ForwardPerformanceMetrics, ...],
        portfolios: tuple[ShadowPortfolioSnapshot, ...],
        journal: tuple[PositionJournalRow, ...],
    ) -> ForwardValidationReport:
        completed = tuple(row for row in journal if row.return_pct is not None)
        largest_winner = max(
            completed,
            key=lambda row: row.return_pct or Decimal("0"),
            default=None,
        )
        largest_loser = min(
            completed,
            key=lambda row: row.return_pct or Decimal("0"),
            default=None,
        )
        recommendation_count = sum(item.recommendation_count for item in metrics)
        if recommendation_count == 0:
            readiness = DeploymentReadiness.NOT_READY
            reason = "No immutable forward recommendation evidence has been recorded."
        else:
            readiness = DeploymentReadiness.FORWARD_VALIDATION
            reason = (
                "Forward evidence collection is active. No governed capital-promotion "
                "criteria exist, so Alpha cannot infer LIMITED_CAPITAL or "
                "PRODUCTION_READY."
            )
        return ForwardValidationReport(
            generated_at=datetime.now(tz=UTC),
            metrics=metrics,
            portfolio=portfolios,
            largest_winner=largest_winner,
            largest_loser=largest_loser,
            readiness=readiness,
            readiness_reason=reason,
        )


def _journal_status(
    events: tuple[PositionEvent, ...],
    entry: PositionEvent | None,
    exit_event: PositionEvent | None,
) -> PositionStatus:
    if exit_event is not None:
        return (
            PositionStatus.INVALIDATED
            if exit_event.event_type is PositionEventType.INVALIDATED
            else PositionStatus.EXITED
        )
    if entry is not None:
        return PositionStatus.ACTIVE
    if any(event.event_type is PositionEventType.ENTRY_MISSED for event in events):
        return PositionStatus.MISSED
    if any(event.event_type is PositionEventType.MANUAL_EXPIRY for event in events):
        return PositionStatus.EXPIRED
    if any(event.event_type is PositionEventType.RISK_BLOCKED for event in events):
        return PositionStatus.RISK_BLOCKED
    if any(event.event_type is PositionEventType.INVALIDATED for event in events):
        return PositionStatus.INVALIDATED
    return PositionStatus.PENDING


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return _quantize(sum(values, start=Decimal("0")) / Decimal(len(values)))


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= Decimal("0"):
        return None
    return _quantize(numerator / denominator * Decimal("100"))


def _profit_factor(
    winners: tuple[Decimal, ...],
    losers: tuple[Decimal, ...],
) -> Decimal | None:
    gross_loss = abs(sum(losers, start=Decimal("0")))
    if gross_loss == Decimal("0"):
        return None
    return _quantize(sum(winners, start=Decimal("0")) / gross_loss)


def _maximum_drawdown(
    valuations: tuple[PortfolioValuation, ...],
) -> Decimal | None:
    if not valuations:
        return None
    peak = Decimal("0")
    maximum = Decimal("0")
    for valuation in valuations:
        peak = max(peak, valuation.portfolio_value)
        if peak > Decimal("0"):
            maximum = max(
                maximum,
                (peak - valuation.portfolio_value) / peak * Decimal("100"),
            )
    return _quantize(maximum)


def _maximum_streak(
    completed: tuple[PositionJournalRow, ...],
    *,
    winning: bool,
) -> int:
    ordered = tuple(sorted(completed, key=lambda row: row.exit_at or row.generated_at))
    current = 0
    maximum = 0
    for row in ordered:
        is_win = row.return_pct is not None and row.return_pct > Decimal("0")
        if is_win is winning:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _valuation_returns(
    valuations: tuple[PortfolioValuation, ...],
) -> tuple[Decimal, ...]:
    results: list[Decimal] = []
    for prior, current in zip(valuations, valuations[1:], strict=False):
        if prior.portfolio_value > Decimal("0"):
            results.append(
                (current.portfolio_value - prior.portfolio_value)
                / prior.portfolio_value
            )
    return tuple(results)


def _sharpe(returns: tuple[Decimal, ...]) -> Decimal | None:
    if len(returns) < 2:
        return None
    values = tuple(float(item) for item in returns)
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    if variance <= 0:
        return None
    return _quantize(Decimal(str(mean / sqrt(variance) * sqrt(252))))


def _sortino(returns: tuple[Decimal, ...]) -> Decimal | None:
    if len(returns) < 2:
        return None
    values = tuple(float(item) for item in returns)
    downside = tuple(min(0.0, item) for item in values)
    downside_deviation = sqrt(sum(item**2 for item in downside) / len(values))
    if downside_deviation <= 0:
        return None
    mean = sum(values) / len(values)
    return _quantize(Decimal(str(mean / downside_deviation * sqrt(252))))


def _cagr(
    *,
    initial_capital: Decimal,
    valuations: tuple[PortfolioValuation, ...],
    started_at: datetime | None,
) -> Decimal | None:
    if not valuations or started_at is None or initial_capital <= Decimal("0"):
        return None
    days = (valuations[-1].valued_at.date() - started_at.date()).days
    if days < 1 or valuations[-1].portfolio_value <= Decimal("0"):
        return None
    ratio = float(valuations[-1].portfolio_value / initial_capital)
    return _quantize(Decimal(str((ratio ** (365 / days) - 1) * 100)))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["PerformanceTracker"]
