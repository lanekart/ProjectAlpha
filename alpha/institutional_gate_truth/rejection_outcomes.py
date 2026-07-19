from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pandas as pd

from alpha.institutional_gate_truth.models import (
    HorizonOutcome,
    RejectionAssessment,
    RejectionCandidate,
)
from alpha.institutional_gate_truth.rejection_classifier import classify_rejection

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class OutcomePolicy:
    transaction_cost_percent: Decimal = Decimal("0.20")
    slippage_percent: Decimal = Decimal("0.10")
    entry_validity_sessions: int = 5
    horizons: tuple[int, ...] = (20, 60, 120)

    def __post_init__(self) -> None:
        if self.entry_validity_sessions < 1:
            raise ValueError("entry validity sessions must be positive")
        if self.transaction_cost_percent < 0 or self.slippage_percent < 0:
            raise ValueError("outcome costs cannot be negative")
        if self.horizons != (20, 60, 120):
            raise ValueError("IGTA v1.0 requires 20D, 60D, and 120D horizons")

    @property
    def round_trip_friction_percent(self) -> Decimal:
        return self.transaction_cost_percent + self.slippage_percent


@dataclass(frozen=True, slots=True)
class _Bar:
    observed_on: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class RejectionOutcomeEngine:
    """Evaluate strictly post-decision bars against each frozen trade plan."""

    def __init__(self, policy: OutcomePolicy | None = None) -> None:
        self.policy = policy or OutcomePolicy()

    def evaluate(
        self,
        *,
        candidates: tuple[RejectionCandidate, ...],
        future_bars: pd.DataFrame,
    ) -> tuple[RejectionAssessment, ...]:
        bars_by_id = _bars_by_candidate(future_bars)
        assessments: list[RejectionAssessment] = []
        for candidate in candidates:
            bars = bars_by_id.get(candidate.candidate_id, ())
            planned = self._outcome(
                candidate=candidate,
                bars=bars,
                horizon=candidate.holding_period_sessions,
            )
            outcomes = {
                horizon: self._outcome(
                    candidate=candidate,
                    bars=bars,
                    horizon=horizon,
                )
                for horizon in self.policy.horizons
            }
            classification, reason = classify_rejection(candidate, planned)
            assessments.append(
                RejectionAssessment(
                    candidate=candidate,
                    classification=classification,
                    classification_reason=reason,
                    planned_outcome=planned,
                    horizon_20d=outcomes[20],
                    horizon_60d=outcomes[60],
                    horizon_120d=outcomes[120],
                    primary_component=_primary_component(candidate),
                )
            )
        return tuple(assessments)

    def _outcome(
        self,
        *,
        candidate: RejectionCandidate,
        bars: tuple[_Bar, ...],
        horizon: int,
    ) -> HorizonOutcome:
        window = bars[:horizon]
        complete = len(window) >= horizon
        if not candidate.trade_plan_valid:
            return _unavailable(horizon, len(window), complete, "INVALID_TRADE_PLAN")
        entry_price = candidate.entry_price
        stop = candidate.prospective_stop
        target = candidate.prospective_target
        assert entry_price is not None
        assert stop is not None
        assert target is not None
        entry_index = _entry_index(
            window,
            entry_price,
            validity=self.policy.entry_validity_sessions,
        )
        if entry_index is None:
            return _unavailable(horizon, len(window), complete, "NOT_TRIGGERED")
        entry_bar = window[entry_index]
        execution_price = max(entry_price, entry_bar.open)
        risk = execution_price - stop
        if risk <= 0:
            return _unavailable(
                horizon,
                len(window),
                complete,
                "ENTRY_AT_OR_BELOW_STOP",
            )
        active = window[entry_index:]
        highs: list[Decimal] = []
        lows: list[Decimal] = []
        exit_date: date | None = None
        exit_price: Decimal | None = None
        exit_reason = "HORIZON_EXIT" if complete else "DATA_BOUNDARY_EXIT"
        target_reached = False
        stop_reached = False
        stop_before_target: bool | None = None
        ambiguity_count = 0
        for index, bar in enumerate(active):
            highs.append(bar.high)
            lows.append(bar.low)
            hit_stop = bar.low <= stop
            hit_target = bar.high >= target
            if hit_stop and hit_target:
                ambiguity_count += 1
            if hit_stop:
                stop_reached = True
                target_reached = hit_target
                stop_before_target = True
                exit_date = bar.observed_on
                exit_price = stop if index == 0 else min(stop, bar.open)
                exit_reason = "STOP"
                break
            if hit_target:
                target_reached = True
                stop_before_target = False
                exit_date = bar.observed_on
                exit_price = target
                exit_reason = "TARGET"
                break
        if exit_price is None and active:
            last = active[-1]
            exit_date = last.observed_on
            exit_price = last.close
        if exit_price is None:
            return _unavailable(horizon, len(window), complete, "NO_POST_ENTRY_BAR")
        gross_return = (exit_price / execution_price - Decimal("1")) * _HUNDRED
        net_return = gross_return - self.policy.round_trip_friction_percent
        cost_per_share = (
            execution_price * self.policy.round_trip_friction_percent / _HUNDRED
        )
        realized_r = (exit_price - execution_price - cost_per_share) / risk
        mfe = (
            (max(highs) / execution_price - Decimal("1")) * _HUNDRED if highs else _ZERO
        )
        mae = (min(lows) / execution_price - Decimal("1")) * _HUNDRED if lows else _ZERO
        return HorizonOutcome(
            horizon_sessions=horizon,
            available_sessions=len(window),
            holding_sessions=len(highs),
            complete=complete,
            entered=True,
            entry_date=entry_bar.observed_on,
            execution_price=_q(execution_price),
            exit_date=exit_date,
            exit_price=_q(exit_price),
            exit_reason=exit_reason,
            target_reached=target_reached,
            stop_reached=stop_reached,
            stop_before_target=stop_before_target,
            maximum_favourable_excursion_percent=_q(mfe),
            maximum_adverse_excursion_percent=_q(mae),
            gross_return_percent=_q(gross_return),
            net_return_percent=_q(net_return),
            realized_r=realized_r.quantize(_FOUR, rounding=ROUND_HALF_UP),
            positive_after_costs=net_return > 0,
            ambiguity_count=ambiguity_count,
        )


def candidate_frame(candidates: tuple[RejectionCandidate, ...]) -> pd.DataFrame:
    return pd.DataFrame.from_records(
        (
            {
                "candidate_id": item.candidate_id,
                "symbol": item.symbol,
                "observed_on": item.observed_on,
            }
            for item in candidates
        ),
        columns=("candidate_id", "symbol", "observed_on"),
    )


def _bars_by_candidate(frame: pd.DataFrame) -> dict[str, tuple[_Bar, ...]]:
    required = {"candidate_id", "trade_date", "open", "high", "low", "close"}
    if frame.empty:
        return {}
    if not required.issubset(frame.columns):
        missing = ", ".join(sorted(required.difference(frame.columns)))
        raise ValueError(f"future bars are missing columns: {missing}")
    result: dict[str, tuple[_Bar, ...]] = {}
    ordered = frame.sort_values(["candidate_id", "trade_date"])
    for candidate_id, group in ordered.groupby("candidate_id", sort=True):
        bars = tuple(_bar(row) for row in group.to_dict("records"))
        result[str(candidate_id)] = bars
    return result


def _bar(row: Mapping[Hashable, Any]) -> _Bar:
    observed_on = _date(row["trade_date"])
    bar = _Bar(
        observed_on=observed_on,
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
    )
    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
        raise ValueError("future bar prices must be positive")
    if bar.high < max(bar.open, bar.low, bar.close):
        raise ValueError("future bar high is invalid")
    if bar.low > min(bar.open, bar.high, bar.close):
        raise ValueError("future bar low is invalid")
    return bar


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _entry_index(
    bars: tuple[_Bar, ...],
    entry: Decimal,
    *,
    validity: int,
) -> int | None:
    for index, bar in enumerate(bars[:validity]):
        if bar.high >= entry:
            return index
    return None


def _unavailable(
    horizon: int,
    available: int,
    complete: bool,
    reason: str,
) -> HorizonOutcome:
    return HorizonOutcome(
        horizon_sessions=horizon,
        available_sessions=available,
        holding_sessions=0,
        complete=complete,
        entered=False,
        entry_date=None,
        execution_price=None,
        exit_date=None,
        exit_price=None,
        exit_reason=reason,
        target_reached=None,
        stop_reached=None,
        stop_before_target=None,
        maximum_favourable_excursion_percent=None,
        maximum_adverse_excursion_percent=None,
        gross_return_percent=None,
        net_return_percent=None,
        realized_r=None,
        positive_after_costs=None,
    )


def _primary_component(candidate: RejectionCandidate) -> str:
    category = (
        candidate.rejection_categories[0]
        if candidate.rejection_categories
        else "UNKNOWN"
    )
    mapping = {
        "Price": "Price Structure",
        "Trend": "Trend",
        "Volume": "Volume",
        "Retracement": "Retracement",
        "Candles": "Candle",
        "Breakout": "Breakout",
        "Risk": "Risk",
        "Entry Timing": "Timing",
        "Approval": "Evidence",
        "Portfolio": "Portfolio",
        "Other": "Other",
    }
    return mapping.get(category, "Unknown")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["OutcomePolicy", "RejectionOutcomeEngine", "candidate_frame"]
