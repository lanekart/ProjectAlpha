from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from alpha.market_opportunity_truth.models import (
    MarketOpportunity,
    OpportunityCalendarRecord,
    OpportunityQuality,
)

_TWO = Decimal("0.01")


def build_opportunity_calendar(
    opportunities: tuple[MarketOpportunity, ...],
    *,
    sessions: tuple[date, ...],
) -> tuple[OpportunityCalendarRecord, ...]:
    session_counts = Counter(item.strftime("%Y-%m") for item in sessions)
    grouped: dict[str, list[MarketOpportunity]] = {
        month: [] for month in sorted(session_counts)
    }
    for item in opportunities:
        grouped.setdefault(item.onset_date.strftime("%Y-%m"), []).append(item)
    rows = []
    for month in sorted(grouped):
        values = grouped[month]
        session_count = session_counts.get(month, 0)
        institutional = sum(item.quality.institutional for item in values)
        rows.append(
            OpportunityCalendarRecord(
                month=month,
                sessions=session_count,
                opportunities=len(values),
                institutional_quality=institutional,
                a_plus=sum(
                    item.quality is OpportunityQuality.A_PLUS for item in values
                ),
                grade_a=sum(item.quality is OpportunityQuality.A for item in values),
                grade_b=sum(item.quality is OpportunityQuality.B for item in values),
                grade_c=sum(item.quality is OpportunityQuality.C for item in values),
                not_tradable=sum(
                    item.quality is OpportunityQuality.NOT_TRADABLE for item in values
                ),
                opportunities_per_session=_rate(len(values), session_count),
                institutional_per_session=_rate(institutional, session_count),
            )
        )
    return tuple(rows)


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


__all__ = ["build_opportunity_calendar"]
