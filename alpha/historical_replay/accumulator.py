from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol


class ReplaySampleFrequency(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class ReplayDateRepository(Protocol):
    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]: ...


@dataclass(frozen=True, slots=True)
class ReplaySamplePlan:
    requested_start: date
    requested_end: date
    frequency: ReplaySampleFrequency
    available_trade_dates: int
    selected_dates: tuple[date, ...]

    @property
    def selected_count(self) -> int:
        return len(self.selected_dates)

    @property
    def explanation(self) -> str:
        if not self.selected_dates:
            return "No persisted trade dates were available for the requested window."
        return (
            f"Selected {self.selected_count} {self.frequency.value} replay dates "
            f"from {self.available_trade_dates} available persisted trade dates."
        )


class HistoricalReplaySampler:
    def __init__(self, *, repository: ReplayDateRepository) -> None:
        self.repository = repository

    def plan(
        self,
        *,
        start: date,
        end: date,
        frequency: ReplaySampleFrequency = ReplaySampleFrequency.MONTHLY,
        max_dates: int | None = None,
    ) -> ReplaySamplePlan:
        if end < start:
            raise ValueError("end must be on or after start")
        if max_dates is not None and max_dates <= 0:
            raise ValueError("max_dates must be positive when provided")

        trade_dates = self.repository.find_trade_dates(start=start, end=end)
        selected = _select_dates(trade_dates=trade_dates, frequency=frequency)
        if max_dates is not None:
            selected = selected[:max_dates]
        return ReplaySamplePlan(
            requested_start=start,
            requested_end=end,
            frequency=frequency,
            available_trade_dates=len(trade_dates),
            selected_dates=selected,
        )


def render_replay_sample_plan(plan: ReplaySamplePlan) -> tuple[str, ...]:
    lines = [
        "Historical Replay Sample Plan",
        f"Requested Window: {plan.requested_start} to {plan.requested_end}",
        f"Frequency: {plan.frequency.value}",
        f"Available Trade Dates: {plan.available_trade_dates}",
        f"Selected Replay Dates: {plan.selected_count}",
        f"Plan: {plan.explanation}",
    ]
    if plan.selected_dates:
        preview = ", ".join(item.isoformat() for item in plan.selected_dates[:12])
        suffix = " ..." if len(plan.selected_dates) > 12 else ""
        lines.append(f"Preview: {preview}{suffix}")
    return tuple(lines)


def _select_dates(
    *,
    trade_dates: tuple[date, ...],
    frequency: ReplaySampleFrequency,
) -> tuple[date, ...]:
    grouped: dict[tuple[int, int], date] = {}
    for trade_date in sorted(trade_dates):
        key = _group_key(trade_date=trade_date, frequency=frequency)
        grouped.setdefault(key, trade_date)
    return tuple(grouped[key] for key in sorted(grouped))


def _group_key(
    *,
    trade_date: date,
    frequency: ReplaySampleFrequency,
) -> tuple[int, int]:
    if frequency is ReplaySampleFrequency.WEEKLY:
        iso = trade_date.isocalendar()
        return (iso.year, iso.week)
    if frequency is ReplaySampleFrequency.QUARTERLY:
        quarter = ((trade_date.month - 1) // 3) + 1
        return (trade_date.year, quarter)
    return (trade_date.year, trade_date.month)


__all__ = [
    "HistoricalReplaySampler",
    "ReplayDateRepository",
    "ReplaySampleFrequency",
    "ReplaySamplePlan",
    "render_replay_sample_plan",
]
