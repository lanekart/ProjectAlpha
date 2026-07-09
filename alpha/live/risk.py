from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from alpha.live.models import (
    FeedHealthSnapshot,
    FeedHealthStatus,
    LiveOHLCVBar,
    LiveQuote,
    LiveRiskWarning,
    LiveRiskWarningType,
    LiveTick,
)


@dataclass(frozen=True, slots=True)
class LiveRiskContext:
    tick: LiveTick | None
    quote: LiveQuote | None
    bar: LiveOHLCVBar | None
    previous_tick: LiveTick | None
    previous_bar: LiveOHLCVBar | None
    feed_health: FeedHealthSnapshot
    observed_at: datetime


class LiveRiskEngine:
    def evaluate(self, context: LiveRiskContext) -> tuple[LiveRiskWarning, ...]:
        warnings: list[LiveRiskWarning] = []
        symbol = _symbol(context)
        if context.feed_health.status in {
            FeedHealthStatus.STALE,
            FeedHealthStatus.DISCONNECTED,
            FeedHealthStatus.FAILED,
        }:
            stale = context.feed_health.stale_duration_seconds
            warnings.append(
                LiveRiskWarning(
                    symbol=symbol,
                    warning_type=LiveRiskWarningType.STALE_FEED,
                    severity="HIGH",
                    message=f"Feed stale for {stale} seconds"
                    if stale is not None
                    else "Feed unavailable",
                    why="No fresh tick has been accepted by the live pipeline.",
                    observed_at=context.observed_at,
                    operator_action="Pause live recommendation generation.",
                )
            )
        if context.tick is None:
            warnings.append(
                LiveRiskWarning(
                    symbol=symbol,
                    warning_type=LiveRiskWarningType.MISSING_TICKS,
                    severity="MEDIUM",
                    message="No live tick available",
                    why="The registry has no accepted tick for this symbol.",
                    observed_at=context.observed_at,
                    operator_action="Wait for a valid tick before acting.",
                )
            )
        if context.bar is None:
            warnings.append(
                LiveRiskWarning(
                    symbol=symbol,
                    warning_type=LiveRiskWarningType.MISSING_BARS,
                    severity="MEDIUM",
                    message="No live bar available",
                    why="The bar builder has not produced a current bar.",
                    observed_at=context.observed_at,
                    operator_action="Do not rely on intraday bar signals yet.",
                )
            )
        if context.quote is not None and context.quote.bid and context.quote.ask:
            spread = context.quote.ask - context.quote.bid
            if context.quote.last_price > Decimal("0"):
                spread_percent = (spread / context.quote.last_price) * Decimal("100")
                if spread_percent > Decimal("1"):
                    warnings.append(
                        LiveRiskWarning(
                            symbol=symbol,
                            warning_type=LiveRiskWarningType.LARGE_SPREAD,
                            severity="MEDIUM",
                            message=f"Large spread detected at {spread_percent:.2f}%",
                            why="Wide bid/ask spread can degrade execution quality.",
                            observed_at=context.observed_at,
                            operator_action=(
                                "Use limit orders or wait for spread to normalize."
                            ),
                        )
                    )
        if context.tick is not None and context.previous_tick is not None:
            previous = context.previous_tick.price
            if previous > Decimal("0"):
                change = abs((context.tick.price - previous) / previous) * Decimal(
                    "100"
                )
                if change > Decimal("5"):
                    warnings.append(
                        LiveRiskWarning(
                            symbol=symbol,
                            warning_type=LiveRiskWarningType.PRICE_GAP,
                            severity="HIGH",
                            message=f"Price gap detected at {change:.2f}%",
                            why="The latest tick moved sharply from the previous tick.",
                            observed_at=context.observed_at,
                            operator_action="Verify the feed before acting.",
                        )
                    )
        if context.bar is not None:
            range_percent = (
                (context.bar.high_price - context.bar.low_price)
                / context.bar.close_price
                * Decimal("100")
                if context.bar.close_price > Decimal("0")
                else Decimal("0")
            )
            if range_percent > Decimal("3"):
                warnings.append(
                    LiveRiskWarning(
                        symbol=symbol,
                        warning_type=LiveRiskWarningType.HIGH_VOLATILITY,
                        severity="MEDIUM",
                        message=f"High intrabar volatility at {range_percent:.2f}%",
                        why="The current bar range is unusually wide.",
                        observed_at=context.observed_at,
                        operator_action="Reduce urgency and check stop distance.",
                    )
                )
            if context.bar.volume <= Decimal("0"):
                warnings.append(
                    LiveRiskWarning(
                        symbol=symbol,
                        warning_type=LiveRiskWarningType.LOW_LIQUIDITY,
                        severity="MEDIUM",
                        message="Low liquidity detected",
                        why="The current bar has no accepted volume.",
                        observed_at=context.observed_at,
                        operator_action="Avoid market orders until liquidity improves.",
                    )
                )
        if context.bar is not None and context.previous_bar is not None:
            if context.previous_bar.volume > Decimal(
                "0"
            ) and context.bar.volume > context.previous_bar.volume * Decimal("5"):
                warnings.append(
                    LiveRiskWarning(
                        symbol=symbol,
                        warning_type=LiveRiskWarningType.ABNORMAL_VOLUME,
                        severity="LOW",
                        message="Abnormal volume detected",
                        why="Current bar volume is more than 5x the previous bar.",
                        observed_at=context.observed_at,
                        operator_action=(
                            "Confirm whether this is news-driven or feed-related."
                        ),
                    )
                )
        return tuple(warnings)


def _symbol(context: LiveRiskContext) -> str:
    if context.tick is not None:
        return context.tick.symbol
    if context.bar is not None:
        return context.bar.symbol
    if context.quote is not None:
        return context.quote.symbol
    return "UNKNOWN"


__all__ = ["LiveRiskContext", "LiveRiskEngine"]
