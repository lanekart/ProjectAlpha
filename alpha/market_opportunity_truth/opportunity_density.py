from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from alpha.market_opportunity_truth.models import (
    MarketOpportunity,
    OpportunityDensityRecord,
    OpportunityQuality,
)

_TWO = Decimal("0.01")
_PERIOD_TYPES = ("DAY", "WEEK", "MONTH", "QUARTER", "YEAR")


def build_opportunity_density(
    opportunities: tuple[MarketOpportunity, ...],
    *,
    sessions: tuple[date, ...],
) -> tuple[OpportunityDensityRecord, ...]:
    rows: list[OpportunityDensityRecord] = []
    for period_type in _PERIOD_TYPES:
        session_counts = Counter(_period(item, period_type) for item in sessions)
        grouped: dict[str, list[MarketOpportunity]] = defaultdict(list)
        for item in opportunities:
            grouped[_period(item.onset_date, period_type)].append(item)
        for period in sorted(session_counts):
            values = grouped.get(period, [])
            rows.append(
                OpportunityDensityRecord(
                    period_type=period_type,
                    period=period,
                    sessions=session_counts[period],
                    opportunities=len(values),
                    high_quality=sum(item.quality.institutional for item in values),
                    medium_quality=sum(
                        item.quality is OpportunityQuality.B for item in values
                    ),
                    low_quality=sum(
                        item.quality is OpportunityQuality.C for item in values
                    ),
                    not_tradable=sum(
                        item.quality is OpportunityQuality.NOT_TRADABLE
                        for item in values
                    ),
                    opportunities_per_session=_rate(
                        len(values), session_counts[period]
                    ),
                )
            )
    return tuple(rows)


def _period(value: date, period_type: str) -> str:
    if period_type == "DAY":
        return value.isoformat()
    if period_type == "WEEK":
        iso = value.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if period_type == "MONTH":
        return value.strftime("%Y-%m")
    if period_type == "QUARTER":
        return f"{value.year}-Q{((value.month - 1) // 3) + 1}"
    return str(value.year)


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


__all__ = ["build_opportunity_density"]
