from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import median

import pandas as pd

from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.market_opportunity_truth.models import (
    MarketOpportunity,
    MarketSupplySummary,
    OpportunityLifecycle,
    OpportunityQuality,
    OpportunitySeed,
    OutcomeMaturity,
)

_TWO = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class _OutcomeEvidence:
    opportunity_id: str
    mfe_120d: Decimal | None
    mae_120d: Decimal | None
    realized_r: Decimal | None
    target_before_stop: bool | None
    stop_hit: bool | None
    exit_reason: str
    first_event_date: date | None
    available_forward_bars: int


class OpportunityLifecycleEngine:
    """Attach post-onset market reality after point-in-time decisions are frozen."""

    def evaluate(
        self,
        *,
        store: LegacyMarketDataStore,
        seeds: tuple[OpportunitySeed, ...],
        outcome_labels_path: Path | str,
        batch_size: int = 5_000,
    ) -> tuple[OpportunityLifecycle, ...]:
        if batch_size < 1:
            raise ValueError("MOTA lifecycle batch size must be positive")
        outcomes = _load_outcomes(Path(outcome_labels_path))
        if set(outcomes) != {item.onset.opportunity_id for item in seeds}:
            raise ValueError("MOTA outcome labels do not match the frozen population")
        rows: list[OpportunityLifecycle] = []
        for batch in _batches(seeds, batch_size):
            candidates = pd.DataFrame(
                {
                    "candidate_id": item.onset.opportunity_id,
                    "symbol": item.onset.symbol,
                    "observed_on": item.onset.onset_date,
                }
                for item in batch
            )
            future = store.future_bars(candidates, limit=120)
            by_id = {
                str(opportunity_id): frame.sort_values("trade_date")
                for opportunity_id, frame in future.groupby("candidate_id", sort=True)
            }
            for seed in batch:
                outcome = outcomes[seed.onset.opportunity_id]
                frame = by_id.get(seed.onset.opportunity_id, pd.DataFrame())
                rows.append(_lifecycle(seed, outcome, frame))
        return tuple(sorted(rows, key=lambda item: item.opportunity_id))


def assemble_market_opportunities(
    seeds: tuple[OpportunitySeed, ...],
    lifecycles: tuple[OpportunityLifecycle, ...],
) -> tuple[MarketOpportunity, ...]:
    lifecycle_by_id = {item.opportunity_id: item for item in lifecycles}
    if len(lifecycle_by_id) != len(seeds):
        raise ValueError("MOTA lifecycle population is incomplete")
    rows = []
    for seed in seeds:
        onset = seed.onset
        trade = seed.tradability
        quality = seed.quality
        lifecycle = lifecycle_by_id[onset.opportunity_id]
        rows.append(
            MarketOpportunity(
                opportunity_id=onset.opportunity_id,
                symbol=onset.symbol,
                onset_date=onset.onset_date,
                entry=onset.entry,
                initial_stop=onset.initial_stop,
                reasonable_target=onset.reasonable_target,
                prospective_rr=onset.prospective_rr,
                liquidity_turnover=trade.liquidity_turnover,
                liquidity_state=trade.liquidity_state,
                trend_state=trade.trend_state,
                volatility_state=trade.volatility_state,
                quality=quality.quality,
                quality_score=quality.score,
                quality_explanation=quality.explanation,
                cluster_id=seed.cluster_id,
                cluster_explanation=seed.cluster_explanation,
                market_regime="UNAVAILABLE_AUTHORITATIVE_HISTORY",
                days_to_peak=lifecycle.days_to_peak,
                days_to_failure=lifecycle.days_to_failure,
                mfe_percent=lifecycle.mfe_percent,
                mae_percent=lifecycle.mae_percent,
                rr_achieved=lifecycle.rr_achieved,
                target_before_stop=lifecycle.target_before_stop,
                stop_hit=lifecycle.stop_hit,
                lifecycle_status=lifecycle.maturity,
                available_forward_bars=lifecycle.available_forward_bars,
                exit_reason=lifecycle.exit_reason,
                first_event_date=lifecycle.first_event_date,
                point_in_time_decision_hash=seed.point_in_time_decision_hash,
            )
        )
    return tuple(
        sorted(
            rows, key=lambda item: (item.onset_date, item.symbol, item.opportunity_id)
        )
    )


def market_supply_summary(
    opportunities: tuple[MarketOpportunity, ...],
    *,
    monthly_counts: tuple[tuple[str, int, int], ...],
) -> MarketSupplySummary:
    if not monthly_counts:
        return MarketSupplySummary(
            total_opportunities=len(opportunities),
            institutional_quality_opportunities=sum(
                item.quality.institutional for item in opportunities
            ),
            mature_outcomes=sum(
                item.lifecycle_status is OutcomeMaturity.COMPLETE
                for item in opportunities
            ),
            months_observed=0,
            average_opportunities_per_month=None,
            median_opportunities_per_month=None,
            average_institutional_opportunities_per_month=None,
            median_institutional_opportunities_per_month=None,
            best_month="UNAVAILABLE",
            best_month_opportunities=0,
            worst_month="UNAVAILABLE",
            worst_month_opportunities=0,
            institutional_average_realized_r=None,
            other_average_realized_r=None,
            quality_tier_monotonic=None,
            institutional_quality_status="INSUFFICIENT_EVIDENCE",
            authoritative_market_regime_available=False,
        )
    totals = tuple(item[1] for item in monthly_counts)
    institutional = tuple(item[2] for item in monthly_counts)
    best = max(monthly_counts, key=lambda item: (item[1], item[0]))
    worst = min(monthly_counts, key=lambda item: (item[1], item[0]))
    mature = tuple(item for item in opportunities if item.rr_achieved is not None)
    institutional_r = tuple(
        item.rr_achieved
        for item in mature
        if item.quality.institutional and item.rr_achieved is not None
    )
    other_r = tuple(
        item.rr_achieved
        for item in mature
        if not item.quality.institutional and item.rr_achieved is not None
    )
    by_quality = {
        quality: _mean_decimal(
            tuple(
                item.rr_achieved
                for item in mature
                if item.quality is quality and item.rr_achieved is not None
            )
        )
        for quality in OpportunityQuality
        if quality is not OpportunityQuality.NOT_TRADABLE
    }
    tier_values = tuple(by_quality.values())
    monotonic = (
        None
        if any(value is None for value in tier_values)
        else all(
            left >= right
            for left, right in zip(tier_values, tier_values[1:], strict=False)
            if left is not None and right is not None
        )
    )
    institutional_average = _mean_decimal(institutional_r)
    other_average = _mean_decimal(other_r)
    quality_status = (
        "PROVISIONAL_GROUP_EXPECTANCY_SEPARATION_PASS"
        if institutional_average is not None
        and other_average is not None
        and institutional_average > other_average
        else "PROVISIONAL_GROUP_EXPECTANCY_SEPARATION_FAIL"
    )
    return MarketSupplySummary(
        total_opportunities=len(opportunities),
        institutional_quality_opportunities=sum(
            item.quality.institutional for item in opportunities
        ),
        mature_outcomes=sum(
            item.lifecycle_status is OutcomeMaturity.COMPLETE for item in opportunities
        ),
        months_observed=len(monthly_counts),
        average_opportunities_per_month=_mean_int(totals),
        median_opportunities_per_month=_median_int(totals),
        average_institutional_opportunities_per_month=_mean_int(institutional),
        median_institutional_opportunities_per_month=_median_int(institutional),
        best_month=best[0],
        best_month_opportunities=best[1],
        worst_month=worst[0],
        worst_month_opportunities=worst[1],
        institutional_average_realized_r=institutional_average,
        other_average_realized_r=other_average,
        quality_tier_monotonic=monotonic,
        institutional_quality_status=quality_status,
        authoritative_market_regime_available=False,
    )


def _lifecycle(
    seed: OpportunitySeed,
    outcome: _OutcomeEvidence,
    frame: pd.DataFrame,
) -> OpportunityLifecycle:
    complete = outcome.available_forward_bars >= 120
    maturity = (
        OutcomeMaturity.COMPLETE
        if complete
        else OutcomeMaturity.PARTIAL
        if outcome.available_forward_bars > 0
        else OutcomeMaturity.UNAVAILABLE
    )
    days_to_peak = None
    days_to_failure = None
    if complete and not frame.empty:
        bounded = frame.head(120).reset_index(drop=True)
        maximum = bounded["high"].max()
        days_to_peak = int(bounded.index[bounded["high"] == maximum][0]) + 1
    if outcome.exit_reason == "STOP" and outcome.first_event_date is not None:
        for index, value in enumerate(frame["trade_date"].tolist(), start=1):
            if _as_date(value) == outcome.first_event_date:
                days_to_failure = index
                break
    mfe = _percent(outcome.mfe_120d)
    mae = _percent(outcome.mae_120d)
    return OpportunityLifecycle(
        opportunity_id=seed.onset.opportunity_id,
        maturity=maturity,
        available_forward_bars=outcome.available_forward_bars,
        days_to_peak=days_to_peak,
        days_to_failure=days_to_failure,
        mfe_percent=mfe,
        mae_percent=mae,
        rr_achieved=outcome.realized_r,
        target_before_stop=outcome.target_before_stop,
        stop_hit=outcome.stop_hit,
        exit_reason=outcome.exit_reason,
        first_event_date=outcome.first_event_date,
    )


def _load_outcomes(path: Path) -> dict[str, _OutcomeEvidence]:
    result: dict[str, _OutcomeEvidence] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            opportunity_id = _required(row, "onset_id")
            if opportunity_id in result:
                raise ValueError("duplicate MOTA outcome label")
            result[opportunity_id] = _OutcomeEvidence(
                opportunity_id=opportunity_id,
                mfe_120d=_decimal(row.get("mfe_120d")),
                mae_120d=_decimal(row.get("mae_120d")),
                realized_r=_decimal(row.get("realized_r")),
                target_before_stop=_boolean(row.get("target_before_stop")),
                stop_hit=_boolean(row.get("stop_hit")),
                exit_reason=_required(row, "exit_reason"),
                first_event_date=_date(row.get("first_event_date")),
                available_forward_bars=int(_required(row, "available_forward_bars")),
            )
    return result


def _batches(
    values: tuple[OpportunitySeed, ...], size: int
) -> Iterable[tuple[OpportunitySeed, ...]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _percent(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return (value * Decimal("100")).quantize(_TWO, rounding=ROUND_HALF_UP)


def _mean_int(values: tuple[int, ...]) -> Decimal:
    return (Decimal(sum(values)) / Decimal(len(values))).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def _median_int(values: tuple[int, ...]) -> Decimal:
    return Decimal(str(median(values))).quantize(_TWO, rounding=ROUND_HALF_UP)


def _mean_decimal(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def _decimal(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    return Decimal(value)


def _boolean(value: str | None) -> bool | None:
    if value is None or not value.strip():
        return None
    if value == "True":
        return True
    if value == "False":
        return False
    raise ValueError(f"invalid MOTA boolean: {value}")


def _date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    return date.fromisoformat(value[:10])


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _required(row: dict[str, str], key: str) -> str:
    value = row.get(key, "").strip()
    if not value:
        raise ValueError(f"MOTA outcome field is unavailable: {key}")
    return value


__all__ = [
    "OpportunityLifecycleEngine",
    "assemble_market_opportunities",
    "market_supply_summary",
]
