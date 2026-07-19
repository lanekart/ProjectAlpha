from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import mean

import pandas as pd

from alpha.candidate_generation_research.models import (
    CandidatePartition,
    CandidateVariantDefinition,
    CandidateVariantResult,
    OpportunityFamily,
    TradableOpportunityOnset,
    VariantFamily,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore

_ALL_LONG_FAMILIES = tuple(
    item
    for item in OpportunityFamily
    if item
    not in {
        OpportunityFamily.NO_TRADABLE_ONSET,
        OpportunityFamily.FAILED_BREAKOUT_REVERSAL,
    }
)
_CANONICAL_FAMILIES = (
    OpportunityFamily.BREAKOUT_FROM_BASE,
    OpportunityFamily.VOLUME_BREAKOUT,
    OpportunityFamily.PULLBACK_CONTINUATION,
    OpportunityFamily.RETEST_HOLD,
    OpportunityFamily.VOLATILITY_CONTRACTION_BREAKOUT,
)


@dataclass(frozen=True, slots=True)
class _Outcome:
    onset_id: str
    return_after_costs: Decimal | None
    mae: Decimal | None
    bars: int


def default_candidate_variants() -> tuple[CandidateVariantDefinition, ...]:
    return (
        _variant(
            "CANONICAL",
            VariantFamily.RECOGNITION_TOLERANCE,
            _CANONICAL_FAMILIES,
            "0.70",
            "1.20",
            "0.08",
            "2.0",
            20,
            10,
            "Frozen-like strict recognition",
        ),
        _variant(
            "A_RELAXED_STRUCTURE",
            VariantFamily.RECOGNITION_TOLERANCE,
            _CANONICAL_FAMILIES,
            "0.60",
            "1.10",
            "0.10",
            "1.5",
            15,
            20,
            "Slightly relaxed structural tolerance",
        ),
        _variant(
            "A_SHORT_PIVOT_DELAY",
            VariantFamily.RECOGNITION_TOLERANCE,
            _CANONICAL_FAMILIES,
            "0.65",
            "1.10",
            "0.09",
            "1.5",
            10,
            15,
            "Earlier pivot confirmation and shorter cooldown",
        ),
        _variant(
            "B_GENERIC_BASE",
            VariantFamily.SETUP_VOCABULARY,
            _CANONICAL_FAMILIES + (OpportunityFamily.EARLY_ACCUMULATION,),
            "0.60",
            "1.10",
            "0.10",
            "1.5",
            15,
            20,
            "Canonical vocabulary plus generic base",
        ),
        _variant(
            "B_TREND_REVERSAL",
            VariantFamily.SETUP_VOCABULARY,
            _CANONICAL_FAMILIES + (OpportunityFamily.TREND_REVERSAL,),
            "0.60",
            "1.10",
            "0.10",
            "1.5",
            15,
            20,
            "Canonical vocabulary plus trend reversal",
        ),
        _variant(
            "B_EMA_RECLAIM",
            VariantFamily.SETUP_VOCABULARY,
            _CANONICAL_FAMILIES + (OpportunityFamily.EMA_RECLAIM,),
            "0.60",
            "1.00",
            "0.10",
            "1.5",
            15,
            20,
            "Canonical vocabulary plus EMA reclaim",
        ),
        _variant(
            "B_RS_BREAKOUT",
            VariantFamily.SETUP_VOCABULARY,
            _CANONICAL_FAMILIES + (OpportunityFamily.RELATIVE_STRENGTH_BREAKOUT,),
            "0.60",
            "1.10",
            "0.10",
            "1.5",
            15,
            20,
            "Canonical vocabulary plus relative-strength breakout",
        ),
        _variant(
            "C_EARLY_ACTIONABLE",
            VariantFamily.TIMING_WINDOW,
            _ALL_LONG_FAMILIES,
            "0.55",
            "1.00",
            "0.08",
            "1.5",
            15,
            20,
            "Early actionable state with extension guard",
        ),
        _variant(
            "C_CONFIRMATION_ONLY",
            VariantFamily.TIMING_WINDOW,
            _ALL_LONG_FAMILIES,
            "0.70",
            "1.20",
            "0.08",
            "2.0",
            20,
            10,
            "Confirmation-only timing",
        ),
        _variant(
            "C_EARLY_PLUS_CONFIRMATION",
            VariantFamily.TIMING_WINDOW,
            _ALL_LONG_FAMILIES,
            "0.65",
            "1.10",
            "0.10",
            "1.5",
            15,
            15,
            "Early plus confirmation timing",
        ),
        _variant(
            "D_SCORE_FIRST",
            VariantFamily.CANDIDATE_CREATION,
            _ALL_LONG_FAMILIES,
            "0.75",
            "1.10",
            "0.08",
            "1.5",
            20,
            10,
            "Score-first point-in-time candidate creation",
        ),
        _variant(
            "D_EVENT_FIRST",
            VariantFamily.CANDIDATE_CREATION,
            _ALL_LONG_FAMILIES,
            "0.60",
            "1.10",
            "0.10",
            "1.5",
            15,
            20,
            "Structural-event-first; never future-return-first",
        ),
        _variant(
            "D_HYBRID",
            VariantFamily.CANDIDATE_CREATION,
            _ALL_LONG_FAMILIES,
            "0.65",
            "1.10",
            "0.09",
            "1.5",
            15,
            15,
            "Hybrid structure and score candidate creation",
        ),
    )


class CandidateVariantGenerator:
    def evaluate(
        self,
        *,
        store: LegacyMarketDataStore,
        all_onsets: tuple[TradableOpportunityOnset, ...],
        associated_onsets: tuple[TradableOpportunityOnset, ...],
        sessions: tuple[date, ...],
        variants: tuple[CandidateVariantDefinition, ...] | None = None,
    ) -> tuple[CandidateVariantResult, ...]:
        if not sessions:
            return ()
        variants = variants or default_candidate_variants()
        partitions = partition_ranges(sessions)
        outcome_by_id = _outcomes(store, all_onsets)
        positive_keys = {
            (item.symbol, item.onset_date, item.event_family)
            for item in associated_onsets
        }
        positive_events_by_partition = _positive_event_counts(
            associated_onsets, partitions
        )
        rows = []
        for variant in variants:
            selected, duplicate_rate = _select(all_onsets, variant)
            for partition, (first, last) in partitions.items():
                subset = tuple(
                    item for item in selected if first <= item.onset_date <= last
                )
                raw_days = sum(first <= item <= last for item in sessions)
                outcomes = tuple(
                    outcome_by_id[item.onset_id]
                    for item in subset
                    if item.onset_id in outcome_by_id
                )
                positives = sum(
                    (item.symbol, item.onset_date, item.event_family) in positive_keys
                    for item in subset
                )
                unique_positive_events = len(
                    {
                        item.forward_event_id
                        for item in associated_onsets
                        if item.forward_event_id is not None
                        and first <= item.onset_date <= last
                        and _passes(item, variant)
                    }
                )
                result = _result(
                    variant=variant,
                    partition=partition,
                    subset=subset,
                    outcomes=outcomes,
                    positives=positives,
                    unique_positive_events=unique_positive_events,
                    available_positive_events=positive_events_by_partition[partition],
                    trading_days=raw_days,
                    duplicate_rate=duplicate_rate,
                )
                rows.append(result)
        return tuple(rows)


def partition_ranges(
    sessions: tuple[date, ...],
) -> dict[CandidatePartition, tuple[date, date]]:
    ordered = tuple(sorted(set(sessions)))
    if len(ordered) < 5:
        raise ValueError("chronological validation requires at least five sessions")
    development_end = max(0, int(len(ordered) * 0.60) - 1)
    validation_end = max(development_end + 1, int(len(ordered) * 0.80) - 1)
    validation_end = min(validation_end, len(ordered) - 2)
    return {
        CandidatePartition.DEVELOPMENT: (ordered[0], ordered[development_end]),
        CandidatePartition.VALIDATION: (
            ordered[development_end + 1],
            ordered[validation_end],
        ),
        CandidatePartition.HOLDOUT: (ordered[validation_end + 1], ordered[-1]),
    }


def _result(
    *,
    variant: CandidateVariantDefinition,
    partition: CandidatePartition,
    subset: tuple[TradableOpportunityOnset, ...],
    outcomes: tuple[_Outcome, ...],
    positives: int,
    unique_positive_events: int,
    available_positive_events: int,
    trading_days: int,
    duplicate_rate: Decimal,
) -> CandidateVariantResult:
    count = len(subset)
    per_day = Decimal(count) / Decimal(max(trading_days, 1))
    returns = [
        item.return_after_costs
        for item in outcomes
        if item.return_after_costs is not None
    ]
    maes = [item.mae for item in outcomes if item.mae is not None]
    precision = None if count == 0 else Decimal(positives) / Decimal(count)
    recall = (
        None
        if available_positive_events == 0
        else Decimal(unique_positive_events) / Decimal(available_positive_events)
    )
    symbol_concentration = _concentration(item.symbol for item in subset)
    average_rr = _average(item.prospective_rr for item in subset)
    explosion = (
        max(
            Decimal("0"),
            per_day / Decimal(variant.maximum_candidates_per_day) - 1,
        )
        + duplicate_rate
    )
    if symbol_concentration is not None and symbol_concentration > Decimal("0.10"):
        explosion += symbol_concentration - Decimal("0.10")
    expectancy = _average(value for value in returns if value is not None)
    false_rate = None if precision is None else Decimal("1") - precision
    failures = _failure_reasons(
        count=count,
        expectancy=expectancy,
        false_rate=false_rate,
        per_day=per_day,
        maximum_per_day=variant.maximum_candidates_per_day,
        average_rr=average_rr,
        explosion=explosion,
    )
    return CandidateVariantResult(
        variant_id=variant.variant_id,
        variant_family=variant.family,
        partition=partition,
        candidates=count,
        trading_days=trading_days,
        candidates_per_day=per_day,
        candidates_per_month=per_day * Decimal("21"),
        candidate_precision=precision,
        candidate_recall=recall,
        forward_expectancy_after_costs=expectancy,
        false_candidate_rate=false_rate,
        duplicate_candidate_rate=duplicate_rate,
        sector_concentration=None,
        symbol_concentration=symbol_concentration,
        turnover=None,
        trade_plan_feasibility=(None if count == 0 else Decimal("1")),
        tradable_onset_coverage=recall,
        major_move_capture_rate=recall,
        average_prospective_rr=average_rr,
        maximum_drawdown_proxy=min(maes) if maes else None,
        explosion_penalty=explosion,
        stability="PENDING_CROSS_PARTITION_COMPARISON",
        passed=not failures,
        failure_reasons=failures,
    )


def _failure_reasons(
    *,
    count: int,
    expectancy: Decimal | None,
    false_rate: Decimal | None,
    per_day: Decimal,
    maximum_per_day: int,
    average_rr: Decimal | None,
    explosion: Decimal,
) -> tuple[str, ...]:
    rows = []
    if count < 30:
        rows.append("INSUFFICIENT_SAMPLE")
    if expectancy is None or expectancy <= 0:
        rows.append("NON_POSITIVE_EXPECTANCY_AFTER_COSTS")
    if false_rate is None or false_rate > Decimal("0.90"):
        rows.append("FALSE_CANDIDATE_RATE_TOO_HIGH")
    if per_day > Decimal(maximum_per_day):
        rows.append("CANDIDATE_VOLUME_EXCEEDS_BOUND")
    if average_rr is None or average_rr < Decimal("1.50"):
        rows.append("PROSPECTIVE_REWARD_RISK_TOO_LOW")
    if explosion > Decimal("0.25"):
        rows.append("CANDIDATE_EXPLOSION_PENALTY")
    return tuple(rows)


def _select(
    values: tuple[TradableOpportunityOnset, ...],
    variant: CandidateVariantDefinition,
) -> tuple[tuple[TradableOpportunityOnset, ...], Decimal]:
    eligible = tuple(item for item in values if _passes(item, variant))
    selected = []
    latest: dict[tuple[str, OpportunityFamily], int] = {}
    duplicates = 0
    for item in sorted(
        eligible, key=lambda value: (value.onset_date, value.symbol, value.event_family)
    ):
        key = (item.symbol, item.event_family)
        previous = latest.get(key)
        if (
            previous is not None
            and item.onset_sequence - previous <= variant.duplicate_cooldown_sessions
        ):
            duplicates += 1
            continue
        selected.append(item)
        latest[key] = item.onset_sequence
    denominator = len(selected) + duplicates
    rate = Decimal(duplicates) / Decimal(denominator) if denominator else Decimal("0")
    return tuple(selected), rate


def _passes(
    item: TradableOpportunityOnset,
    variant: CandidateVariantDefinition,
) -> bool:
    volume = _point_decimal(item, "volume_ratio_20")
    extension = _point_decimal(item, "extension_pct")
    return (
        item.event_family in variant.supported_families
        and item.confidence >= variant.minimum_confidence
        and volume is not None
        and volume >= variant.minimum_volume_ratio
        and extension is not None
        and extension <= variant.maximum_extension
        and item.prospective_rr >= variant.minimum_rr
    )


def _outcomes(
    store: LegacyMarketDataStore,
    onsets: tuple[TradableOpportunityOnset, ...],
) -> dict[str, _Outcome]:
    if not onsets:
        return {}
    frame = pd.DataFrame(
        {
            "onset_id": [item.onset_id for item in onsets],
            "symbol": [item.symbol for item in onsets],
            "onset_date": [item.onset_date for item in onsets],
            "onset_sequence": [item.onset_sequence for item in onsets],
            "entry": [float(item.entry_trigger) for item in onsets],
        }
    )
    store.connection.register("_research_onsets", frame)
    try:
        rows = store.connection.execute(
            """
            WITH indexed_prices AS (
                SELECT
                    UPPER(symbol) AS symbol,
                    trade_date,
                    close,
                    low,
                    ROW_NUMBER() OVER (
                        PARTITION BY UPPER(symbol) ORDER BY trade_date
                    ) - 1 AS sequence
                FROM daily_prices
                WHERE open > 0 AND high > 0 AND low > 0 AND close > 0
                  AND volume >= 0
                  AND high >= GREATEST(open, low, close)
                  AND low <= LEAST(open, high, close)
            )
            SELECT
                onsets.onset_id,
                (ARG_MAX(prices.close, prices.trade_date) / ANY_VALUE(onsets.entry))
                    - 1 - 0.002
                    AS return_after_costs,
                (MIN(prices.low) / ANY_VALUE(onsets.entry)) - 1 AS mae,
                COUNT(*) AS bars
            FROM _research_onsets AS onsets
            JOIN indexed_prices AS prices
              ON prices.symbol = UPPER(onsets.symbol)
             AND prices.sequence > onsets.onset_sequence
             AND prices.sequence <= onsets.onset_sequence + 60
            GROUP BY onsets.onset_id
            ORDER BY onsets.onset_id
            """
        ).fetchall()
    finally:
        store.connection.unregister("_research_onsets")
    return {
        str(onset_id): _Outcome(
            onset_id=str(onset_id),
            return_after_costs=Decimal(str(outcome)) if outcome is not None else None,
            mae=min(Decimal("0"), Decimal(str(mae))) if mae is not None else None,
            bars=int(bars),
        )
        for onset_id, outcome, mae, bars in rows
    }


def _positive_event_counts(
    values: tuple[TradableOpportunityOnset, ...],
    partitions: dict[CandidatePartition, tuple[date, date]],
) -> dict[CandidatePartition, int]:
    return {
        partition: len(
            {
                item.forward_event_id
                for item in values
                if item.forward_event_id is not None
                and first <= item.onset_date <= last
            }
        )
        for partition, (first, last) in partitions.items()
    }


def _variant(
    variant_id: str,
    family: VariantFamily,
    supported: tuple[OpportunityFamily, ...],
    confidence: str,
    volume: str,
    extension: str,
    rr: str,
    cooldown: int,
    maximum: int,
    description: str,
) -> CandidateVariantDefinition:
    return CandidateVariantDefinition(
        variant_id=variant_id,
        family=family,
        description=description,
        supported_families=tuple(dict.fromkeys(supported)),
        minimum_confidence=Decimal(confidence),
        minimum_volume_ratio=Decimal(volume),
        maximum_extension=Decimal(extension),
        minimum_rr=Decimal(rr),
        duplicate_cooldown_sessions=cooldown,
        maximum_candidates_per_day=maximum,
    )


def _point_decimal(item: TradableOpportunityOnset, key: str) -> Decimal | None:
    value = item.point_in_time_inputs.get(key)
    if value in {None, "UNAVAILABLE"}:
        return None
    assert value is not None
    return Decimal(value)


def _average(values: Iterable[Decimal]) -> Decimal | None:
    materialized = tuple(values)
    if not materialized:
        return None
    return Decimal(str(mean(materialized)))


def _concentration(values: Iterable[str]) -> Decimal | None:
    counts = Counter(values)
    total = sum(counts.values())
    return None if total == 0 else Decimal(max(counts.values())) / Decimal(total)


__all__ = [
    "CandidateVariantGenerator",
    "default_candidate_variants",
    "partition_ranges",
]
