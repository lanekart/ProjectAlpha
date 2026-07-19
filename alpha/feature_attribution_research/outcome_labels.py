"""Pre-registered forward outcome labels for causal market onsets."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

import pandas as pd

from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.feature_attribution_research.models import (
    OUTCOME_DEFINITION_VERSION,
    OutcomeDefinition,
    OutcomeRecord,
    ResearchPopulationRecord,
    TransactionCostPolicy,
)

_HORIZONS = (20, 60, 120)
_ONE = Decimal("1")
_ZERO = Decimal("0")


def preregistered_outcome_definitions() -> tuple[OutcomeDefinition, ...]:
    """Return immutable definitions before any feature attribution is run."""

    rows = [
        OutcomeDefinition(
            outcome_id="TARGET_BEFORE_STOP",
            definition=(
                "Frozen prospective target is touched before the frozen stop within "
                "120 sessions; stop wins same-bar ambiguity."
            ),
            horizon=120,
            primary=True,
        ),
        OutcomeDefinition(
            outcome_id="ACHIEVED_2R",
            definition="The standardized +2R price is touched before the frozen stop.",
            horizon=120,
            primary=False,
        ),
        OutcomeDefinition(
            outcome_id="HIGH_QUALITY_WINNER",
            definition=(
                "Frozen target precedes stop, deterministic realized R is at least "
                "2, and 60-session net return is positive."
            ),
            horizon=120,
            primary=False,
        ),
    ]
    for horizon in _HORIZONS:
        rows.extend(
            (
                OutcomeDefinition(
                    outcome_id=f"POSITIVE_AFTER_COSTS_{horizon}D",
                    definition=(
                        f"{horizon}-session close return net of configured costs "
                        "is positive."
                    ),
                    horizon=horizon,
                    primary=False,
                ),
                OutcomeDefinition(
                    outcome_id=f"NET_RETURN_{horizon}D",
                    definition=(
                        f"Close-to-entry return after {horizon} sessions net of the "
                        "configured transaction cost."
                    ),
                    horizon=horizon,
                    primary=False,
                ),
                OutcomeDefinition(
                    outcome_id=f"MFE_{horizon}D",
                    definition=f"Maximum high versus entry over {horizon} sessions.",
                    horizon=horizon,
                    primary=False,
                ),
                OutcomeDefinition(
                    outcome_id=f"MAE_{horizon}D",
                    definition=f"Minimum low versus entry over {horizon} sessions.",
                    horizon=horizon,
                    primary=False,
                ),
            )
        )
    return tuple(rows)


class OutcomeLabelEngine:
    """Attach future market truth only after the onset population is frozen."""

    def evaluate(
        self,
        *,
        store: LegacyMarketDataStore,
        population: tuple[ResearchPopulationRecord, ...],
        transaction_cost_policy: TransactionCostPolicy,
        batch_size: int = 5_000,
    ) -> tuple[OutcomeRecord, ...]:
        if batch_size < 1:
            raise ValueError("outcome batch size must be positive")
        results: list[OutcomeRecord] = []
        for batch in _batches(population, batch_size):
            candidates = pd.DataFrame(
                {
                    "candidate_id": item.onset_id,
                    "symbol": item.symbol,
                    "observed_on": item.onset_date,
                }
                for item in batch
            )
            future = store.future_bars(candidates, limit=120)
            by_onset = {
                str(onset_id): frame.sort_values("trade_date")
                for onset_id, frame in future.groupby("candidate_id", sort=True)
            }
            for item in batch:
                results.append(
                    _evaluate_one(
                        item,
                        by_onset.get(item.onset_id, pd.DataFrame()),
                        transaction_cost_policy,
                    )
                )
        return tuple(sorted(results, key=lambda item: item.onset_id))


def outcome_value(record: OutcomeRecord, outcome_id: str) -> bool | Decimal | None:
    lookup: dict[str, bool | Decimal | None] = {
        "TARGET_BEFORE_STOP": record.target_before_stop,
        "POSITIVE_AFTER_COSTS_60D": record.positive_after_costs_60d,
        "POSITIVE_AFTER_COSTS_20D": record.positive_after_costs_20d,
        "POSITIVE_AFTER_COSTS_120D": record.positive_after_costs_120d,
        "ACHIEVED_2R": record.positive_2r_before_stop,
        "HIGH_QUALITY_WINNER": record.high_quality_winner,
        "NET_RETURN_20D": record.net_return_20d,
        "NET_RETURN_60D": record.net_return_60d,
        "NET_RETURN_120D": record.net_return_120d,
        "MFE_20D": record.mfe_20d,
        "MFE_60D": record.mfe_60d,
        "MFE_120D": record.mfe_120d,
        "MAE_20D": record.mae_20d,
        "MAE_60D": record.mae_60d,
        "MAE_120D": record.mae_120d,
    }
    if outcome_id not in lookup:
        raise KeyError(f"unknown outcome: {outcome_id}")
    return lookup[outcome_id]


def _evaluate_one(
    item: ResearchPopulationRecord,
    frame: pd.DataFrame,
    policy: TransactionCostPolicy,
) -> OutcomeRecord:
    entry = item.entry_trigger
    stop = item.prospective_stop
    plan_target = item.prospective_target
    risk = entry - stop
    one_r = entry + risk
    two_r = entry + risk * Decimal("2")
    bars = tuple(frame.itertuples(index=False))
    available = len(bars)
    returns: dict[int, Decimal | None] = {}
    mfes: dict[int, Decimal | None] = {}
    maes: dict[int, Decimal | None] = {}
    for horizon in _HORIZONS:
        if available < horizon:
            returns[horizon] = None
            mfes[horizon] = None
            maes[horizon] = None
            continue
        window = bars[:horizon]
        last_close = _decimal(window[-1].close)
        returns[horizon] = last_close / entry - _ONE - policy.round_trip_rate
        mfes[horizon] = max(_decimal(row.high) for row in window) / entry - _ONE
        maes[horizon] = min(_decimal(row.low) for row in window) / entry - _ONE

    stop_date: date | None = None
    one_r_date: date | None = None
    two_r_date: date | None = None
    plan_target_date: date | None = None
    first_event = "PENDING_END_OF_DATA"
    first_event_date: date | None = None
    first_exit_price: Decimal | None = None
    for row in bars:
        observed_on = _as_date(row.trade_date)
        low = _decimal(row.low)
        high = _decimal(row.high)
        if stop_date is None and low <= stop:
            stop_date = observed_on
        if one_r_date is None and high >= one_r:
            one_r_date = observed_on
        if two_r_date is None and high >= two_r:
            two_r_date = observed_on
        if plan_target_date is None and high >= plan_target:
            plan_target_date = observed_on
        if first_event_date is None:
            if low <= stop:
                first_event = "STOP"
                first_event_date = observed_on
                first_exit_price = stop
            elif high >= plan_target:
                first_event = "PLAN_TARGET"
                first_event_date = observed_on
                first_exit_price = plan_target

    complete = available >= 120
    if first_event_date is None and complete:
        first_event = "TIME_EXIT_120D"
        first_event_date = _as_date(bars[119].trade_date)
        first_exit_price = _decimal(bars[119].close)
    realized_r = None
    if first_exit_price is not None and risk > 0:
        net_exit = first_exit_price - entry * policy.round_trip_rate
        realized_r = (net_exit - entry) / risk
    target_before_stop = _before(
        plan_target_date, stop_date, complete=complete, tie_wins=False
    )
    achieved_one_r = _before(one_r_date, stop_date, complete=complete, tie_wins=False)
    achieved_two_r = _before(two_r_date, stop_date, complete=complete, tie_wins=False)
    stopped_first = _before(
        stop_date, plan_target_date, complete=complete, tie_wins=True
    )
    positive_60 = _positive(returns[60])
    high_quality = (
        None
        if target_before_stop is None or positive_60 is None or realized_r is None
        else target_before_stop and realized_r >= Decimal("2") and positive_60
    )
    return OutcomeRecord(
        onset_id=item.onset_id,
        entry_price=entry,
        stop_price=stop,
        plan_target_price=plan_target,
        net_return_20d=returns[20],
        net_return_60d=returns[60],
        net_return_120d=returns[120],
        mfe_20d=mfes[20],
        mfe_60d=mfes[60],
        mfe_120d=mfes[120],
        mae_20d=maes[20],
        mae_60d=maes[60],
        mae_120d=maes[120],
        realized_r=realized_r,
        target_1_hit=achieved_one_r,
        target_2_hit=achieved_two_r,
        plan_target_hit=target_before_stop,
        stop_hit=stopped_first,
        target_before_stop=target_before_stop,
        positive_after_costs_20d=_positive(returns[20]),
        positive_after_costs_60d=positive_60,
        positive_after_costs_120d=_positive(returns[120]),
        positive_2r_before_stop=achieved_two_r,
        high_quality_winner=high_quality,
        exit_reason=first_event,
        first_event_date=first_event_date,
        available_forward_bars=available,
        transaction_cost_policy_id=policy.policy_id,
    )


def _before(
    event_date: date | None,
    competing_date: date | None,
    *,
    complete: bool,
    tie_wins: bool,
) -> bool | None:
    if event_date is not None and competing_date is not None:
        return event_date <= competing_date if tie_wins else event_date < competing_date
    if event_date is not None:
        return True
    if competing_date is not None:
        return False
    return False if complete else None


def _positive(value: Decimal | None) -> bool | None:
    return None if value is None else value > _ZERO


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _batches(
    values: tuple[ResearchPopulationRecord, ...], size: int
) -> Iterable[tuple[ResearchPopulationRecord, ...]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


__all__ = [
    "OUTCOME_DEFINITION_VERSION",
    "OutcomeLabelEngine",
    "outcome_value",
    "preregistered_outcome_definitions",
]
