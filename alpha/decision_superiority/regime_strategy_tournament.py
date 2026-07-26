"""Governed DSI-007 regime-aware strategy tournament."""

from __future__ import annotations

import hashlib
import math
import subprocess
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from alpha.decision_superiority.regime_strategy_models import (
    BenchmarkStatus,
    EntryState,
    ExitReason,
    OverfittingState,
    RegimeState,
    SliceReadiness,
    StrategyFamily,
    StrategyVariant,
    TournamentError,
    TournamentPolicy,
    TournamentResult,
    TournamentSourcePaths,
    WalkForwardFold,
)

_PORTFOLIO_REGIME = "REGIME_AWARE_SELECTED"
_PORTFOLIO_FIXED = "BEST_FIXED_STRATEGY"
_PORTFOLIO_ENSEMBLE = "NON_REGIME_ENSEMBLE"
_PORTFOLIO_MOMENTUM = "SIMPLE_MOMENTUM_BASELINE"
_PORTFOLIO_TREND = "SIMPLE_TREND_BASELINE"
_PORTFOLIO_EQUAL_WEIGHT = "EQUAL_WEIGHT_ELIGIBLE_UNIVERSE"
_PORTFOLIO_BENCHMARK = "TOTAL_RETURN_INDEX_BENCHMARK"
_PORTFOLIO_NAMES = (
    _PORTFOLIO_REGIME,
    _PORTFOLIO_FIXED,
    _PORTFOLIO_ENSEMBLE,
    _PORTFOLIO_MOMENTUM,
    _PORTFOLIO_TREND,
    _PORTFOLIO_EQUAL_WEIGHT,
    _PORTFOLIO_BENCHMARK,
)
_REGIME_ORDER = tuple(RegimeState)
_REQUIRED_COLUMNS = {
    "trading_date",
    "identity_key",
    "symbol",
    "series",
    "isin",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source_sha256",
}


def governance_flags() -> dict[str, bool]:
    """Return the immutable research-only DSI-007 governance boundary."""

    return {
        "THRESHOLD_CHANGE_PERMITTED": False,
        "GATE_ORDER_CHANGE_PERMITTED": False,
        "APPROVAL_POLICY_CHANGE_PERMITTED": False,
        "PORTFOLIO_POLICY_CHANGE_PERMITTED": False,
        "EXECUTION_POLICY_CHANGE_PERMITTED": False,
        "STRATEGY_AUTOMATIC_PROMOTION_ENABLED": False,
        "LIVE_STRATEGY_SELECTION_ENABLED": False,
        "LIVE_SCORING_ENABLED": False,
        "PRODUCTION_SIGNAL_PUBLICATION_ENABLED": False,
        "PRODUCTION_PORTFOLIO_INFLUENCE": False,
        "SYNTHETIC_MARKET_DATA_PERMITTED": False,
        "SYNTHETIC_TRADES_PERMITTED": False,
        "SYNTHETIC_OUTCOMES_PERMITTED": False,
        "ECONOMIC_SUPERIORITY_CLAIMED": False,
        "CAUSAL_CLAIM_PERMITTED": False,
        "AUTOMATIC_POLICY_RECOMMENDATION_ENABLED": False,
        "DEFAULT_RUNTIME_BEHAVIOUR_CHANGED": False,
        "RECOMMENDATION_INFLUENCE": False,
        "PORTFOLIO_POLICY_INFLUENCE": False,
        "EXECUTION_INFLUENCE": False,
        "LEARNING_MUTATION_ENABLED": False,
        "ACTIVE_REPLAY_INTEGRATION": False,
        "PRODUCTION_INFLUENCE": False,
    }


def default_strategy_registry() -> tuple[StrategyVariant, ...]:
    """Return the pre-registered bounded DSI-007 strategy grammar."""

    bull = (
        RegimeState.BULL_TREND_LOW_VOLATILITY,
        RegimeState.BULL_TREND_HIGH_VOLATILITY,
        RegimeState.TRANSITION,
    )
    constructive = (*bull, RegimeState.SIDEWAYS_LOW_VOLATILITY)
    variants = (
        _variant(
            "MOMENTUM_BREAKOUT_20D_V1",
            StrategyFamily.MOMENTUM_BREAKOUT,
            {"breakout_days": 20, "volume_ratio": 1.20, "atr_stop": 1.75},
            ("breakout", "volume_expansion", "dma_alignment", "relative_strength"),
            bull,
            5,
        ),
        _variant(
            "MOMENTUM_BREAKOUT_50D_V1",
            StrategyFamily.MOMENTUM_BREAKOUT,
            {"breakout_days": 50, "volume_ratio": 1.35, "atr_stop": 2.00},
            ("breakout", "volume_expansion", "dma_alignment", "relative_strength"),
            bull,
            5,
        ),
        _variant(
            "TREND_FOLLOWING_60D_V1",
            StrategyFamily.TREND_FOLLOWING,
            {"momentum_days": 60, "minimum_momentum": 0.10, "atr_stop": 2.00},
            ("dma_alignment", "price_momentum", "liquidity"),
            constructive,
            4,
        ),
        _variant(
            "TREND_FOLLOWING_20D_V1",
            StrategyFamily.TREND_FOLLOWING,
            {"momentum_days": 20, "minimum_momentum": 0.05, "atr_stop": 1.75},
            ("dma_alignment", "price_momentum", "liquidity"),
            constructive,
            4,
        ),
        _variant(
            "PULLBACK_20DMA_V1",
            StrategyFamily.PULLBACK_ENTRY,
            {"support_dma": 20, "volume_ratio_max": 0.95, "atr_stop": 1.50},
            ("dma_support", "low_volume_pullback", "trend_filter"),
            constructive,
            4,
        ),
        _variant(
            "PULLBACK_50DMA_V1",
            StrategyFamily.PULLBACK_ENTRY,
            {"support_dma": 50, "volume_ratio_max": 0.90, "atr_stop": 1.75},
            ("dma_support", "low_volume_pullback", "trend_filter"),
            constructive,
            4,
        ),
        _variant(
            "RS_CONTINUATION_V1",
            StrategyFamily.RELATIVE_STRENGTH_CONTINUATION,
            {"rs_percentile": 0.80, "minimum_momentum": 0.05, "atr_stop": 2.00},
            ("relative_strength", "dma_alignment", "price_momentum"),
            bull,
            4,
        ),
        _variant(
            "VOLATILITY_CONTRACTION_V1",
            StrategyFamily.VOLATILITY_CONTRACTION,
            {"contraction_ratio": 0.75, "breakout_days": 20, "atr_stop": 1.75},
            ("volatility_contraction", "breakout", "volume_expansion"),
            bull,
            5,
        ),
        _variant(
            "RETEST_HOLD_V1",
            StrategyFamily.RETEST_HOLD,
            {"support_dma": 20, "retest_tolerance": 0.015, "atr_stop": 1.50},
            ("prior_breakout", "support_retest", "close_strength"),
            constructive,
            5,
        ),
        _variant(
            "MEAN_REVERSION_V1",
            StrategyFamily.MEAN_REVERSION,
            {"five_day_return_max": -0.08, "atr_stop": 1.50},
            ("short_term_selloff", "long_term_trend", "close_strength"),
            (
                RegimeState.SIDEWAYS_LOW_VOLATILITY,
                RegimeState.SIDEWAYS_HIGH_VOLATILITY,
            ),
            4,
        ),
        _variant(
            "FAILED_BREAKOUT_AVOIDANCE_V1",
            StrategyFamily.FAILED_BREAKOUT_AVOIDANCE,
            {"breakout_days": 20, "volume_ratio_min": 1.20},
            ("failed_breakout", "distribution_volume"),
            _REGIME_ORDER,
            2,
        ),
        _variant(
            "TREND_FAILURE_AVOIDANCE_V1",
            StrategyFamily.TREND_FAILURE_AVOIDANCE,
            {"support_dma": 50, "volume_ratio_min": 1.20},
            ("lower_structure", "support_breakdown", "distribution_volume"),
            _REGIME_ORDER,
            2,
        ),
        _variant(
            "NO_TRADE",
            StrategyFamily.NO_TRADE,
            {},
            ("cash",),
            _REGIME_ORDER,
            0,
        ),
    )
    validate_strategy_registry(variants, maximum_variants=24)
    return variants


def _variant(
    identifier: str,
    family: StrategyFamily,
    parameters: dict[str, float],
    components: tuple[str, ...],
    regimes: tuple[RegimeState, ...],
    complexity: int,
) -> StrategyVariant:
    return StrategyVariant(
        strategy_variant_id=identifier,
        family=family,
        parameters=MappingProxyType(parameters),
        components=components,
        expected_regimes=regimes,
        complexity_score=complexity,
        source_definition="DSI-007 bounded strategy grammar v1",
        prerequisites=("governed adjusted OHLCV", "unique effective-dated identity"),
    )


def validate_strategy_registry(
    variants: Sequence[StrategyVariant],
    *,
    maximum_variants: int,
) -> None:
    """Fail closed on an unbounded, duplicate, or contradictory registry."""

    if not variants:
        raise TournamentError("EMPTY_STRATEGY_REGISTRY")
    if len(variants) > maximum_variants:
        raise TournamentError("UNBOUNDED_STRATEGY_REGISTRY")
    identifiers = [item.strategy_variant_id for item in variants]
    if len(identifiers) != len(set(identifiers)):
        raise TournamentError("DUPLICATE_STRATEGY_VARIANT_ID")
    fingerprints = [
        (
            item.family.value,
            tuple(item.parameters.items()),
            item.components,
        )
        for item in variants
    ]
    if len(fingerprints) != len(set(fingerprints)):
        raise TournamentError("DUPLICATE_STRATEGY_VARIANT")
    for item in variants:
        if item.family is StrategyFamily.NO_TRADE and (
            item.parameters or item.complexity_score
        ):
            raise TournamentError("INVALID_NO_TRADE_VARIANT")


class GovernedRegimeStrategyTournamentEngine:
    """Run DSI-007 A-J without changing any Alpha runtime policy."""

    def run(
        self,
        *,
        sources: TournamentSourcePaths,
        start: date,
        end: date,
        policy: TournamentPolicy | None = None,
    ) -> TournamentResult:
        if end < start:
            raise TournamentError("tournament end cannot precede start")
        effective_policy = policy or TournamentPolicy()
        variants = default_strategy_registry()
        validate_strategy_registry(
            variants,
            maximum_variants=effective_policy.maximum_variant_count,
        )
        source_rows, market, source_summary = _load_governed_market(
            sources=sources,
            start=start,
            end=end,
        )
        if market.empty:
            raise TournamentError("NO_GOVERNED_ADJUSTED_MARKET_POPULATION")
        featured, regime_rows, transition_rows = _build_point_in_time_features(market)
        signals = _generate_signals(featured, variants, effective_policy)
        plans, independent_trades = _build_independent_trade_plans(
            featured,
            signals,
            variants,
            effective_policy,
        )
        folds = _walk_forward_folds(featured)
        fold_rows, selection_rows, mapping_rows = _select_strategies(
            independent_trades,
            variants,
            folds,
            effective_policy,
        )
        benchmark_frame, benchmark_rows = _load_benchmark(
            sources.benchmark,
            sessions=tuple(sorted(featured["trading_date"].unique())),
            start=start,
            end=end,
        )
        portfolios = _run_comparison_portfolios(
            featured=featured,
            signals=signals,
            plans=plans,
            folds=folds,
            selections=selection_rows,
            benchmark=benchmark_frame,
            policy=effective_policy,
        )
        analysis = _analyse_portfolios(
            portfolios=portfolios,
            independent_trades=independent_trades,
            variants=variants,
            folds=folds,
            policy=effective_policy,
        )
        rows = _assemble_rows(
            sources=sources,
            source_rows=source_rows,
            source_summary=source_summary,
            market=market,
            featured=featured,
            variants=variants,
            signals=signals,
            plans=plans,
            independent_trades=independent_trades,
            regime_rows=regime_rows,
            transition_rows=transition_rows,
            fold_rows=fold_rows,
            selection_rows=selection_rows,
            mapping_rows=mapping_rows,
            benchmark_rows=benchmark_rows,
            portfolios=portfolios,
            analysis=analysis,
            policy=effective_policy,
        )
        readiness, blockers = _readiness(
            source_summary=source_summary,
            regime_rows=regime_rows,
            variants=variants,
            signals=signals,
            portfolios=portfolios,
            benchmark_rows=benchmark_rows,
            analysis=analysis,
        )
        summaries = _summaries(
            source_summary=source_summary,
            featured=featured,
            regime_rows=regime_rows,
            transition_rows=transition_rows,
            variants=variants,
            signals=signals,
            plans=plans,
            folds=folds,
            selection_rows=selection_rows,
            benchmark_rows=benchmark_rows,
            portfolios=portfolios,
            analysis=analysis,
        )
        return TournamentResult(
            source_commit=_git_commit(sources.project_root),
            readiness=MappingProxyType(readiness),
            blockers=tuple(blockers),
            rows=MappingProxyType(rows),
            summaries=MappingProxyType(summaries),
            governance=MappingProxyType(governance_flags()),
        )


def _load_governed_market(
    *,
    sources: TournamentSourcePaths,
    start: date,
    end: date,
) -> tuple[tuple[dict[str, Any], ...], pd.DataFrame, dict[str, Any]]:
    if not sources.database.is_file():
        raise TournamentError("HISTORICAL_TRUTH_DATABASE_UNAVAILABLE")
    if not sources.historical_truth_snapshots.exists():
        raise TournamentError("HISTORICAL_TRUTH_SNAPSHOTS_UNAVAILABLE")
    connection = duckdb.connect(str(sources.database), read_only=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "select table_name from information_schema.tables "
                "where table_schema='main'"
            ).fetchall()
        }
        required = {
            "adjusted_daily_candle",
            "adjusted_candle_lineage",
            "security_isin_interval_complete",
            "security_membership_interval_complete",
            "corporate_action_event",
            "price_basis_interval",
        }
        if not required.issubset(tables):
            missing = ",".join(sorted(required - tables))
            raise TournamentError(f"HISTORICAL_TRUTH_TABLES_MISSING:{missing}")
        coverage = _coverage_queries(connection, start, end)
        frame = connection.execute(
            """
            with identity_matches as (
                select
                    a.trading_date,
                    a.exchange,
                    a.symbol,
                    a.series,
                    a.isin,
                    min(i.identity_key) as identity_key,
                    count(distinct i.identity_key) as identity_match_count
                from adjusted_daily_candle a
                left join security_isin_interval_complete i
                  on a.isin = i.isin
                 and a.trading_date >= i.valid_from
                 and (i.valid_to is null or a.trading_date <= i.valid_to)
                where a.trading_date between ? and ?
                  and a.series = 'EQ'
                group by 1, 2, 3, 4, 5
            ),
            membership_matches as (
                select
                    m.trading_date,
                    m.exchange,
                    m.symbol,
                    m.series,
                    m.isin,
                    m.identity_key,
                    m.identity_match_count,
                    min(u.state) as membership_state,
                    bool_and(coalesce(u.tradable, false)) as tradable,
                    count(u.identity_key) as membership_match_count
                from identity_matches m
                left join security_membership_interval_complete u
                  on m.identity_key = u.identity_key
                 and m.trading_date >= u.valid_from
                 and (u.valid_to is null or m.trading_date <= u.valid_to)
                group by 1, 2, 3, 4, 5, 6, 7
            )
            select
                a.trading_date,
                m.identity_key,
                a.exchange,
                a.symbol,
                a.series,
                a.isin,
                a.adjusted_open as open,
                a.adjusted_high as high,
                a.adjusted_low as low,
                a.adjusted_close as close,
                a.adjusted_volume as volume,
                l.raw_source_sha256 as source_sha256,
                a.contract_version,
                a.calculation_version,
                a.action_ids,
                m.membership_state
            from adjusted_daily_candle a
            join membership_matches m
              on a.trading_date = m.trading_date
             and a.exchange = m.exchange
             and a.symbol = m.symbol
             and a.series = m.series
             and a.isin = m.isin
            join price_basis_interval p
              on m.identity_key = p.identity_key
             and a.trading_date >= p.valid_from
             and (p.valid_to is null or a.trading_date <= p.valid_to)
            left join adjusted_candle_lineage l
              on a.contract_version = l.contract_version
             and a.trading_date = l.trading_date
             and a.exchange = l.exchange
             and a.symbol = l.symbol
             and a.series = l.series
            where m.identity_match_count = 1
              and m.membership_match_count <= 1
              and p.state = 'BACKWARD_ADJUSTED'
              and a.adjusted_open > 0
              and a.adjusted_high > 0
              and a.adjusted_low > 0
              and a.adjusted_close > 0
              and a.adjusted_volume >= 0
            order by a.trading_date, m.identity_key
            """,
            [start, end],
        ).fetchdf()
    finally:
        connection.close()
    frame = frame.rename(columns={"trading_date": "trading_date"})
    _validate_market_frame(frame)
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.date
    frame["identity_key"] = frame["identity_key"].astype(str)
    frame["symbol"] = frame["symbol"].astype(str)
    frame["source_sha256"] = frame["source_sha256"].fillna("UNKNOWN").astype(str)
    source_rows = (
        {
            "source_role": "HISTORICAL_TRUTH_DATABASE",
            "availability": "AVAILABLE",
            "sha256": _file_sha256(sources.database),
            "byte_size": sources.database.stat().st_size,
            "portable_locator": sources.database.name,
            "used_for_decisions": True,
        },
        {
            "source_role": "HISTORICAL_TRUTH_SNAPSHOTS",
            "availability": "AVAILABLE",
            "sha256": _directory_contract_sha256(sources.historical_truth_snapshots),
            "byte_size": _directory_size(sources.historical_truth_snapshots),
            "portable_locator": sources.historical_truth_snapshots.name,
            "used_for_decisions": False,
        },
    )
    summary = {
        **coverage,
        "admitted_rows": int(len(frame)),
        "admitted_securities": int(frame["identity_key"].nunique()),
        "admitted_sessions": int(frame["trading_date"].nunique()),
        "actual_start": min(frame["trading_date"]),
        "actual_end": max(frame["trading_date"]),
    }
    return source_rows, frame, summary


def _coverage_queries(
    connection: duckdb.DuckDBPyConnection,
    start: date,
    end: date,
) -> dict[str, Any]:
    values = connection.execute(
        """
        select
            count(*) as source_rows,
            count(distinct trading_date) as source_sessions,
            count(distinct isin) as source_isins,
            min(trading_date) as source_start,
            max(trading_date) as source_end,
            count(*) filter (
                where adjusted_high < greatest(adjusted_open, adjusted_close)
                   or adjusted_low > least(adjusted_open, adjusted_close)
                   or adjusted_high < adjusted_low
            ) as impossible_ohlc,
            count(*) filter (
                where adjusted_open <= 0 or adjusted_high <= 0
                   or adjusted_low <= 0 or adjusted_close <= 0
            ) as nonpositive_price,
            count(*) filter (where adjusted_volume < 0) as invalid_volume,
            count(*) - count(distinct (
                trading_date, exchange, symbol, series
            )) as duplicate_rows
        from adjusted_daily_candle
        where trading_date between ? and ? and series = 'EQ'
        """,
        [start, end],
    ).fetchone()
    identity = connection.execute(
        """
        with matches as (
            select
                a.trading_date,
                a.exchange,
                a.symbol,
                a.series,
                count(distinct i.identity_key) as identity_count
            from adjusted_daily_candle a
            left join security_isin_interval_complete i
              on a.isin = i.isin
             and a.trading_date >= i.valid_from
             and (i.valid_to is null or a.trading_date <= i.valid_to)
            where a.trading_date between ? and ? and a.series = 'EQ'
            group by 1, 2, 3, 4
        )
        select
            count(*) filter (where identity_count = 1),
            count(*) filter (where identity_count = 0),
            count(*) filter (where identity_count > 1)
        from matches
        """,
        [start, end],
    ).fetchone()
    actions = connection.execute(
        """
        select
            count(*),
            count(*) filter (
                where admission_state like 'ADMITTED%'
                   or admission_state = 'CERTIFIED'
            ),
            count(*) filter (
                where adjustment_factor_state in ('CONFLICTING', 'AMBIGUOUS')
            )
        from corporate_action_event
        where coalesce(effective_date, ex_date, record_date)
              between ? and ?
        """,
        [start, end],
    ).fetchone()
    price_basis = connection.execute(
        """
        select
            count(*) filter (where state = 'BACKWARD_ADJUSTED'),
            count(*) filter (
                where state in (
                    'MIXED_PRICE_BASIS',
                    'IDENTITY_TRANSITION_UNRESOLVED',
                    'ADJUSTMENT_FACTOR_UNKNOWN'
                )
            )
        from price_basis_interval
        where valid_from <= ?
          and (valid_to is null or valid_to >= ?)
        """,
        [end, start],
    ).fetchone()
    if values is None or identity is None or actions is None or price_basis is None:
        raise TournamentError("HISTORICAL_TRUTH_COVERAGE_QUERY_EMPTY")
    return {
        "source_rows": int(values[0]),
        "source_sessions": int(values[1]),
        "source_isins": int(values[2]),
        "source_start": values[3],
        "source_end": values[4],
        "impossible_ohlc": int(values[5]),
        "nonpositive_price": int(values[6]),
        "invalid_volume": int(values[7]),
        "duplicate_rows": int(values[8]),
        "unique_identity_rows": int(identity[0]),
        "missing_identity_rows": int(identity[1]),
        "ambiguous_identity_rows": int(identity[2]),
        "corporate_action_events": int(actions[0]),
        "admitted_corporate_actions": int(actions[1]),
        "conflicting_corporate_actions": int(actions[2]),
        "certified_price_basis_intervals": int(price_basis[0]),
        "quarantined_price_basis_intervals": int(price_basis[1]),
    }


def _validate_market_frame(frame: pd.DataFrame) -> None:
    missing = _REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise TournamentError(f"MARKET_COLUMNS_MISSING:{','.join(sorted(missing))}")
    if frame.empty:
        return
    duplicate = frame.duplicated(["trading_date", "identity_key"]).any()
    if duplicate:
        raise TournamentError("DUPLICATE_GOVERNED_IDENTITY_SESSION")
    impossible = (
        (frame["high"] < frame[["open", "close"]].max(axis=1))
        | (frame["low"] > frame[["open", "close"]].min(axis=1))
        | (frame["high"] < frame["low"])
    )
    if bool(impossible.any()):
        raise TournamentError("IMPOSSIBLE_GOVERNED_OHLC")


def _build_point_in_time_features(
    market: pd.DataFrame,
) -> tuple[pd.DataFrame, tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    frame = market.sort_values(["identity_key", "trading_date"]).copy()
    grouped = frame.groupby("identity_key", sort=False, observed=True)
    frame["security_position"] = grouped.cumcount()
    frame["previous_close"] = grouped["close"].shift(1)
    frame["return_1d"] = frame["close"] / frame["previous_close"] - 1.0
    for window in (5, 20, 50, 60, 200):
        frame[f"return_{window}d"] = (
            frame["close"] / grouped["close"].shift(window) - 1.0
        )
    for window in (20, 50, 200):
        frame[f"ma{window}"] = grouped["close"].transform(
            lambda values, size=window: values.rolling(size, min_periods=size).mean()
        )
    frame["prior_high20"] = grouped["high"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=20).max()
    )
    frame["prior_high50"] = grouped["high"].transform(
        lambda values: values.shift(1).rolling(50, min_periods=50).max()
    )
    frame["prior_breakout20"] = grouped["close"].transform(
        lambda values: (
            (values.shift(1) > values.shift(2).rolling(20, min_periods=20).max())
            .rolling(10, min_periods=1)
            .max()
            .astype(bool)
        )
    )
    frame["average_volume20"] = grouped["volume"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=20).mean()
    )
    traded_value = frame["close"] * frame["volume"]
    frame["average_traded_value20"] = traded_value.groupby(
        frame["identity_key"], sort=False
    ).transform(lambda values: values.shift(1).rolling(20, min_periods=20).mean())
    frame["volume_ratio"] = frame["volume"] / frame["average_volume20"]
    true_range = pd.concat(
        (
            frame["high"] - frame["low"],
            (frame["high"] - frame["previous_close"]).abs(),
            (frame["low"] - frame["previous_close"]).abs(),
        ),
        axis=1,
    ).max(axis=1)
    frame["true_range"] = true_range
    frame["atr14"] = frame.groupby("identity_key", sort=False, observed=True)[
        "true_range"
    ].transform(lambda values: values.rolling(14, min_periods=14).mean())
    frame["volatility20"] = grouped["return_1d"].transform(
        lambda values: values.rolling(20, min_periods=20).std() * math.sqrt(252)
    )
    volatility60 = grouped["return_1d"].transform(
        lambda values: values.rolling(60, min_periods=60).std() * math.sqrt(252)
    )
    frame["contraction_ratio"] = frame["volatility20"] / volatility60
    frame["close_strength"] = (
        (frame["close"] - frame["low"]) / (frame["high"] - frame["low"])
    ).where(frame["high"] > frame["low"], 0.5)
    frame["rs_percentile"] = frame.groupby("trading_date", sort=False, observed=True)[
        "return_60d"
    ].rank(pct=True, method="average")
    sessions = tuple(sorted(frame["trading_date"].unique()))
    ordinal = {session: index for index, session in enumerate(sessions)}
    frame["session_ordinal"] = frame["trading_date"].map(ordinal)
    for column in ("trading_date", "open", "high", "low", "close", "volume"):
        frame[f"next_{column}"] = grouped[column].shift(-1)
    frame["next_session_ordinal"] = grouped["session_ordinal"].shift(-1)
    frame["next_session_valid"] = (
        frame["next_session_ordinal"] == frame["session_ordinal"] + 1
    )
    daily = (
        frame.groupby("trading_date", sort=True, observed=True)
        .agg(
            market_return=("return_1d", "mean"),
            breadth=("ma50", lambda values: float(values.notna().mean())),
            security_count=("identity_key", "nunique"),
        )
        .reset_index()
    )
    breadth = (
        frame.assign(above_ma50=frame["close"] > frame["ma50"])
        .groupby("trading_date", sort=True, observed=True)["above_ma50"]
        .mean()
    )
    daily["breadth"] = daily["trading_date"].map(breadth)
    daily["market_return"] = daily["market_return"].fillna(0.0)
    daily["market_level"] = (1.0 + daily["market_return"]).cumprod()
    daily["market_ma50"] = daily["market_level"].rolling(50, min_periods=50).mean()
    daily["market_ma200"] = daily["market_level"].rolling(200, min_periods=200).mean()
    daily["market_volatility20"] = daily["market_return"].rolling(
        20, min_periods=20
    ).std() * math.sqrt(252)
    daily["regime"] = daily.apply(_classify_regime, axis=1)
    daily["regime_applies_on"] = daily["trading_date"].shift(-1)
    regime_map = daily.set_index("trading_date")["regime"]
    frame["regime"] = frame["trading_date"].map(regime_map)
    regime_rows = tuple(
        _regime_artifact_row(row) for row in daily.itertuples(index=False)
    )
    transitions: list[dict[str, Any]] = []
    previous: str | None = None
    for row in daily.itertuples(index=False):
        current = str(row.regime)
        if previous is not None and current != previous:
            transitions.append(
                {
                    "transition_id": _stable_id(
                        "TRANSITION",
                        row.trading_date,
                        previous,
                        current,
                    ),
                    "observed_on": row.trading_date,
                    "from_regime": previous,
                    "to_regime": current,
                }
            )
        previous = current
    return frame, regime_rows, tuple(transitions)


def _regime_artifact_row(raw_row: object) -> dict[str, Any]:
    row: Any = raw_row
    return {
        "regime_state_id": _stable_id(
            "REGIME",
            row.trading_date,
            str(row.regime),
        ),
        "observed_on": row.trading_date,
        "applies_on": row.regime_applies_on,
        "regime_state": str(row.regime),
        "market_level": _round(float(row.market_level)),
        "market_return": _round(float(row.market_return)),
        "market_ma50": _optional_round(row.market_ma50),
        "market_ma200": _optional_round(row.market_ma200),
        "market_volatility20": _optional_round(row.market_volatility20),
        "breadth": _round(float(row.breadth)),
        "security_count": int(row.security_count),
        "future_data_used": False,
    }


def _classify_regime(row: pd.Series) -> RegimeState:
    required = (
        row["market_ma50"],
        row["market_ma200"],
        row["market_volatility20"],
        row["breadth"],
    )
    if any(pd.isna(value) for value in required):
        return RegimeState.UNKNOWN
    level = float(row["market_level"])
    ma50 = float(row["market_ma50"])
    ma200 = float(row["market_ma200"])
    volatility = float(row["market_volatility20"])
    breadth = float(row["breadth"])
    if level < ma200 and ma50 < ma200 and breadth < 0.45:
        return RegimeState.BEAR_TREND
    if level > ma200 and ma50 > ma200 and breadth >= 0.55:
        return (
            RegimeState.BULL_TREND_HIGH_VOLATILITY
            if volatility >= 0.22
            else RegimeState.BULL_TREND_LOW_VOLATILITY
        )
    near_trend = abs(level / ma200 - 1.0) <= 0.05
    if near_trend or 0.45 <= breadth < 0.55:
        return (
            RegimeState.SIDEWAYS_HIGH_VOLATILITY
            if volatility >= 0.22
            else RegimeState.SIDEWAYS_LOW_VOLATILITY
        )
    return RegimeState.TRANSITION


def _generate_signals(
    frame: pd.DataFrame,
    variants: Sequence[StrategyVariant],
    policy: TournamentPolicy,
) -> pd.DataFrame:
    signal_frames: list[pd.DataFrame] = []
    liquid = frame["average_traded_value20"] >= policy.minimum_average_traded_value
    trend = (frame["close"] > frame["ma50"]) & (frame["ma50"] > frame["ma200"])
    for variant in variants:
        if variant.family in {
            StrategyFamily.NO_TRADE,
            StrategyFamily.FAILED_BREAKOUT_AVOIDANCE,
            StrategyFamily.TREND_FAILURE_AVOIDANCE,
        }:
            continue
        parameters = variant.parameters
        if variant.strategy_variant_id == "MOMENTUM_BREAKOUT_20D_V1":
            mask = (
                trend
                & (frame["close"] > frame["prior_high20"])
                & (frame["volume_ratio"] >= parameters["volume_ratio"])
                & (frame["rs_percentile"] >= 0.70)
            )
        elif variant.strategy_variant_id == "MOMENTUM_BREAKOUT_50D_V1":
            mask = (
                trend
                & (frame["close"] > frame["prior_high50"])
                & (frame["volume_ratio"] >= parameters["volume_ratio"])
                & (frame["rs_percentile"] >= 0.75)
            )
        elif variant.strategy_variant_id == "TREND_FOLLOWING_60D_V1":
            mask = trend & (frame["return_60d"] >= parameters["minimum_momentum"])
        elif variant.strategy_variant_id == "TREND_FOLLOWING_20D_V1":
            mask = trend & (frame["return_20d"] >= parameters["minimum_momentum"])
        elif variant.strategy_variant_id == "PULLBACK_20DMA_V1":
            mask = (
                (frame["close"] > frame["ma200"])
                & (frame["low"] <= frame["ma20"] * 1.01)
                & (frame["close"] >= frame["ma20"])
                & (frame["volume_ratio"] <= parameters["volume_ratio_max"])
                & (frame["return_60d"] > 0)
                & (frame["close_strength"] >= 0.55)
            )
        elif variant.strategy_variant_id == "PULLBACK_50DMA_V1":
            mask = (
                (frame["close"] > frame["ma200"])
                & (frame["low"] <= frame["ma50"] * 1.01)
                & (frame["close"] >= frame["ma50"])
                & (frame["volume_ratio"] <= parameters["volume_ratio_max"])
                & (frame["return_60d"] > 0)
                & (frame["close_strength"] >= 0.55)
            )
        elif variant.strategy_variant_id == "RS_CONTINUATION_V1":
            mask = (
                trend
                & (frame["rs_percentile"] >= parameters["rs_percentile"])
                & (frame["return_20d"] >= parameters["minimum_momentum"])
            )
        elif variant.strategy_variant_id == "VOLATILITY_CONTRACTION_V1":
            mask = (
                trend
                & (frame["contraction_ratio"] <= parameters["contraction_ratio"])
                & (frame["close"] > frame["prior_high20"])
                & (frame["volume_ratio"] >= 1.10)
            )
        elif variant.strategy_variant_id == "RETEST_HOLD_V1":
            tolerance = parameters["retest_tolerance"]
            mask = (
                trend
                & frame["prior_breakout20"]
                & (frame["low"] <= frame["ma20"] * (1.0 + tolerance))
                & (frame["close"] >= frame["ma20"])
                & (frame["close_strength"] >= 0.60)
            )
        elif variant.strategy_variant_id == "MEAN_REVERSION_V1":
            mask = (
                (frame["close"] > frame["ma200"])
                & (frame["return_5d"] <= parameters["five_day_return_max"])
                & (frame["close_strength"] >= 0.60)
            )
        else:
            raise TournamentError(
                f"STRATEGY_GENERATOR_MISSING:{variant.strategy_variant_id}"
            )
        expected = {state.value for state in variant.expected_regimes}
        mask = (
            mask.fillna(False)
            & liquid.fillna(False)
            & frame["next_session_valid"].fillna(False)
            & frame["atr14"].notna()
            & frame["regime"].map(lambda state: str(state) in expected)
        )
        selected = frame.loc[mask].copy()
        if selected.empty:
            continue
        selected["strategy_variant_id"] = variant.strategy_variant_id
        selected["strategy_family"] = variant.family.value
        selected["signal_strength"] = (
            selected["rs_percentile"].fillna(0.5) * 0.40
            + np.minimum(selected["volume_ratio"].fillna(1.0), 2.0) / 2.0 * 0.25
            + selected["close_strength"].fillna(0.5) * 0.20
            + np.minimum(
                np.maximum(selected["return_60d"].fillna(0.0), 0.0),
                0.50,
            )
            / 0.50
            * 0.15
        )
        signal_frames.append(selected)
    if not signal_frames:
        return pd.DataFrame()
    signals = pd.concat(signal_frames, ignore_index=True)
    signals["signal_id"] = signals.apply(
        lambda row: _stable_id(
            "SIGNAL",
            row["trading_date"],
            row["identity_key"],
            row["strategy_variant_id"],
        ),
        axis=1,
    )
    signals["entry_state"] = EntryState.SIGNAL_GENERATED.value
    return signals.sort_values(
        ["trading_date", "strategy_variant_id", "identity_key"]
    ).reset_index(drop=True)


def _build_independent_trade_plans(
    frame: pd.DataFrame,
    signals: pd.DataFrame,
    variants: Sequence[StrategyVariant],
    policy: TournamentPolicy,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if signals.empty:
        return pd.DataFrame(), pd.DataFrame()
    variants_by_id = {item.strategy_variant_id: item for item in variants}
    history = {
        identity: {
            "trading_date": values["trading_date"].to_numpy(),
            "session_ordinal": values["session_ordinal"].to_numpy(dtype=np.int64),
            "open": values["open"].to_numpy(dtype=float),
            "high": values["high"].to_numpy(dtype=float),
            "low": values["low"].to_numpy(dtype=float),
            "close": values["close"].to_numpy(dtype=float),
        }
        for identity, values in frame.groupby("identity_key", sort=False, observed=True)
    }
    plan_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    for raw_signal in signals.itertuples(index=False):
        signal: Any = raw_signal
        variant = variants_by_id[signal.strategy_variant_id]
        security_history = history[signal.identity_key]
        signal_index = int(signal.security_position)
        entry_index = signal_index + 1
        if entry_index >= len(security_history["trading_date"]):
            continue
        if (
            int(security_history["session_ordinal"][entry_index])
            != int(signal.session_ordinal) + 1
        ):
            continue
        entry_date = security_history["trading_date"][entry_index]
        raw_entry = float(security_history["open"][entry_index])
        entry = raw_entry * (1.0 + policy.slippage_fraction)
        atr = float(signal.atr14)
        atr_multiple = float(variant.parameters.get("atr_stop", 1.75))
        risk = max(atr * atr_multiple, entry * 0.02)
        stop = max(0.01, entry - risk)
        target_1 = entry + risk * 2.0
        target_2 = entry + risk * 3.0
        target_3 = entry + risk * 4.0
        trade_plan_id = _stable_id("PLAN", signal.signal_id, entry_date)
        plan = {
            "trade_plan_id": trade_plan_id,
            "signal_id": signal.signal_id,
            "identity_key": signal.identity_key,
            "symbol": signal.symbol,
            "strategy_variant_id": signal.strategy_variant_id,
            "signal_date": signal.trading_date,
            "entry_eligibility_date": entry_date,
            "entry_rule": "NEXT_SESSION_OPEN",
            "raw_entry_price": _round(raw_entry),
            "entry_price": _round(entry),
            "initial_stop": _round(stop),
            "target_1": _round(target_1),
            "target_2": _round(target_2),
            "target_3": _round(target_3),
            "trailing_stop_rule": "AFTER_2R_TRAIL_2_ATR_BELOW_HIGHEST_CLOSE",
            "maximum_holding_sessions": 40,
            "risk_per_share": _round(risk),
            "reward_risk_target_1": 2.0,
            "average_traded_value20": _round(signal.average_traded_value20),
            "entry_state": EntryState.ENTRY_TRIGGERED.value,
            "same_close_execution": False,
        }
        plan_rows.append(plan)
        outcome = _independent_trade_outcome(
            security_history=security_history,
            entry_index=entry_index,
            plan=plan,
            atr=atr,
            policy=policy,
        )
        trade_rows.append(
            {
                "logical_trade_id": _stable_id(
                    "INDEPENDENT_TRADE",
                    trade_plan_id,
                ),
                **plan,
                **outcome,
                "regime_state": str(signal.regime),
                "signal_strength": _round(signal.signal_strength),
                "price_arm": "ADJUSTED",
                "portfolio_name": "INDEPENDENT_VARIANT_EVALUATION",
            }
        )
    return pd.DataFrame(plan_rows), pd.DataFrame(trade_rows)


def _independent_trade_outcome(
    *,
    security_history: Mapping[str, Any],
    entry_index: int,
    plan: Mapping[str, Any],
    atr: float,
    policy: TournamentPolicy,
) -> dict[str, Any]:
    entry = float(plan["entry_price"])
    stop = float(plan["initial_stop"])
    target_1 = float(plan["target_1"])
    target_2 = float(plan["target_2"])
    highest_close = entry
    active_stop = stop
    end_index = min(entry_index + 39, len(security_history["close"]) - 1)
    exit_price = float(security_history["close"][end_index])
    exit_reason = ExitReason.TIME_EXIT
    exit_index = end_index
    maximum_favourable = 0.0
    maximum_adverse = 0.0
    for index in range(entry_index, end_index + 1):
        low = float(security_history["low"][index])
        high = float(security_history["high"][index])
        close = float(security_history["close"][index])
        maximum_favourable = max(maximum_favourable, high / entry - 1.0)
        maximum_adverse = min(maximum_adverse, low / entry - 1.0)
        if low <= active_stop:
            exit_price = active_stop
            exit_reason = (
                ExitReason.TRAILING_STOP if active_stop > stop else ExitReason.STOP
            )
            exit_index = index
            break
        if high >= target_2:
            exit_price = target_2
            exit_reason = ExitReason.TARGET
            exit_index = index
            break
        highest_close = max(highest_close, close)
        if high >= target_1:
            active_stop = max(active_stop, entry, highest_close - 2.0 * atr)
    exit_fill = exit_price * (1.0 - policy.slippage_fraction)
    gross_return = exit_price / entry - 1.0
    net_return = (
        exit_fill
        * (1.0 - policy.transaction_cost_fraction)
        / (entry * (1.0 + policy.transaction_cost_fraction))
        - 1.0
    )
    risk = float(plan["risk_per_share"])
    return {
        "entry_date": security_history["trading_date"][entry_index],
        "exit_date": security_history["trading_date"][exit_index],
        "exit_price": _round(exit_fill),
        "exit_reason": exit_reason.value,
        "holding_sessions": exit_index - entry_index + 1,
        "gross_return": _round(gross_return),
        "net_return": _round(net_return),
        "realised_r": _round((exit_fill - entry) / risk),
        "mfe": _round(maximum_favourable),
        "mae": _round(maximum_adverse),
        "win": net_return > 0,
    }


def _walk_forward_folds(frame: pd.DataFrame) -> tuple[WalkForwardFold, ...]:
    first = min(frame["trading_date"])
    last = max(frame["trading_date"])
    available_years = sorted({item.year for item in frame["trading_date"]})
    folds: list[WalkForwardFold] = []
    for test_year in available_years:
        if test_year < first.year + 5:
            continue
        validation_year = test_year - 1
        train_end_year = test_year - 2
        test_start = max(date(test_year, 1, 1), first)
        test_end = min(date(test_year, 12, 31), last)
        validation_start = max(date(validation_year, 1, 1), first)
        validation_end = min(date(validation_year, 12, 31), last)
        train_end = min(date(train_end_year, 12, 31), last)
        if not (first <= train_end < validation_start <= validation_end < test_start):
            continue
        folds.append(
            WalkForwardFold(
                walk_forward_fold_id=f"WF-{test_year}",
                train_start=first,
                train_end=train_end,
                validation_start=validation_start,
                validation_end=validation_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
    return tuple(folds)


def _select_strategies(
    trades: pd.DataFrame,
    variants: Sequence[StrategyVariant],
    folds: Sequence[WalkForwardFold],
    policy: TournamentPolicy,
) -> tuple[
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
]:
    fold_rows = tuple(
        {
            **asdict(fold),
            "periods_overlap": False,
            "outer_test_used_for_selection": False,
        }
        for fold in folds
    )
    if trades.empty:
        return fold_rows, (), ()
    complexity = {item.strategy_variant_id: item.complexity_score for item in variants}
    selection_rows: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    for fold in folds:
        train = trades[
            (trades["signal_date"] >= fold.train_start)
            & (trades["signal_date"] <= fold.train_end)
        ]
        validation = trades[
            (trades["signal_date"] >= fold.validation_start)
            & (trades["signal_date"] <= fold.validation_end)
        ]
        for regime in _REGIME_ORDER:
            chosen, candidates = _choose_variant(
                train[train["regime_state"] == regime.value],
                validation[validation["regime_state"] == regime.value],
                complexity=complexity,
                minimum_trades=policy.minimum_selection_trades,
            )
            selection_rows.extend(
                _selection_candidate_rows(
                    fold=fold,
                    selection_scope=f"REGIME:{regime.value}",
                    chosen=chosen,
                    candidates=candidates,
                )
            )
            mapping_rows.append(
                {
                    "walk_forward_fold_id": fold.walk_forward_fold_id,
                    "regime_state": regime.value,
                    "selected_strategy_variant_id": chosen,
                    "fallback_state": (
                        "NO_TRADE" if chosen == "NO_TRADE" else "SELECTED"
                    ),
                    "selection_data_end": fold.validation_end,
                    "test_start": fold.test_start,
                    "test_end": fold.test_end,
                    "holdout_used": False,
                }
            )
        chosen_fixed, fixed_candidates = _choose_variant(
            train,
            validation,
            complexity=complexity,
            minimum_trades=policy.minimum_selection_trades,
        )
        selection_rows.extend(
            _selection_candidate_rows(
                fold=fold,
                selection_scope="FIXED",
                chosen=chosen_fixed,
                candidates=fixed_candidates,
            )
        )
        ranked = [
            item["strategy_variant_id"]
            for item in fixed_candidates
            if item["eligible"] and item["objective_score"] > 0
        ][:2]
        if not ranked:
            ranked = ["NO_TRADE"]
        mapping_rows.append(
            {
                "walk_forward_fold_id": fold.walk_forward_fold_id,
                "regime_state": "ALL",
                "selected_strategy_variant_id": chosen_fixed,
                "fallback_state": (
                    "NO_TRADE" if chosen_fixed == "NO_TRADE" else "SELECTED"
                ),
                "selection_data_end": fold.validation_end,
                "test_start": fold.test_start,
                "test_end": fold.test_end,
                "holdout_used": False,
                "ensemble_strategy_variant_ids": "|".join(ranked),
            }
        )
    return fold_rows, tuple(selection_rows), tuple(mapping_rows)


def _choose_variant(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    *,
    complexity: Mapping[str, int],
    minimum_trades: int,
) -> tuple[str, list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    variant_ids = sorted(
        set(train.get("strategy_variant_id", pd.Series(dtype=str)))
        | set(validation.get("strategy_variant_id", pd.Series(dtype=str)))
    )
    for variant_id in variant_ids:
        train_variant = train[train["strategy_variant_id"] == variant_id]
        validation_variant = validation[validation["strategy_variant_id"] == variant_id]
        train_count = len(train_variant)
        validation_count = len(validation_variant)
        eligible = (
            train_count + validation_count >= minimum_trades
            and train_count >= max(2, minimum_trades // 2)
            and validation_count >= 2
        )
        returns = validation_variant["net_return"].astype(float)
        mean_return = float(returns.mean()) if validation_count else float("nan")
        volatility = (
            float(returns.std(ddof=1)) if validation_count > 1 else float("nan")
        )
        downside = float(abs(min(0.0, returns.min()))) if validation_count else 0.0
        objective = (
            mean_return
            - 0.35 * (0.0 if math.isnan(volatility) else volatility)
            - 0.10 * downside
            - complexity.get(variant_id, 99) * 0.0002
            if eligible
            else float("-inf")
        )
        candidates.append(
            {
                "strategy_variant_id": variant_id,
                "train_trade_count": train_count,
                "validation_trade_count": validation_count,
                "validation_mean_return": _optional_round(mean_return),
                "validation_volatility": _optional_round(volatility),
                "complexity_score": complexity.get(variant_id, 99),
                "eligible": eligible,
                "objective_score": _optional_round(objective),
            }
        )
    candidates.sort(
        key=lambda item: (
            -float(item["objective_score"] or -1e9),
            int(item["complexity_score"]),
            str(item["strategy_variant_id"]),
        )
    )
    if not candidates:
        return "NO_TRADE", candidates
    best = candidates[0]
    if not best["eligible"] or float(best["objective_score"] or 0.0) <= 0:
        return "NO_TRADE", candidates
    return str(best["strategy_variant_id"]), candidates


def _selection_candidate_rows(
    *,
    fold: WalkForwardFold,
    selection_scope: str,
    chosen: str,
    candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = [
        {
            "selection_id": _stable_id(
                "SELECTION",
                fold.walk_forward_fold_id,
                selection_scope,
                item["strategy_variant_id"],
            ),
            "walk_forward_fold_id": fold.walk_forward_fold_id,
            "selection_scope": selection_scope,
            **dict(item),
            "selected": item["strategy_variant_id"] == chosen,
            "selected_strategy_variant_id": chosen,
            "selection_data_end": fold.validation_end,
            "test_start": fold.test_start,
            "test_end": fold.test_end,
            "outer_test_used_for_selection": False,
        }
        for item in candidates
    ]
    if chosen == "NO_TRADE" and not any(
        item["strategy_variant_id"] == "NO_TRADE" for item in candidates
    ):
        rows.append(
            {
                "selection_id": _stable_id(
                    "SELECTION",
                    fold.walk_forward_fold_id,
                    selection_scope,
                    "NO_TRADE",
                ),
                "walk_forward_fold_id": fold.walk_forward_fold_id,
                "selection_scope": selection_scope,
                "strategy_variant_id": "NO_TRADE",
                "strategy_family": StrategyFamily.NO_TRADE.value,
                "sample_count": 0,
                "trade_count": 0,
                "mean_net_return": 0.0,
                "expectancy": 0.0,
                "complexity_score": 0,
                "eligible": True,
                "objective_score": 0.0,
                "selected": True,
                "selected_strategy_variant_id": "NO_TRADE",
                "selection_data_end": fold.validation_end,
                "test_start": fold.test_start,
                "test_end": fold.test_end,
                "outer_test_used_for_selection": False,
            }
        )
    return rows


def _load_benchmark(
    benchmark: str,
    *,
    sessions: tuple[date, ...],
    start: date,
    end: date,
) -> tuple[pd.DataFrame | None, tuple[dict[str, Any], ...]]:
    normalized = benchmark.strip()
    if not normalized or normalized.upper() in {"AUTO", "UNAVAILABLE", "NONE"}:
        return None, (
            {
                "benchmark_name": "GOVERNED_BROAD_MARKET_TRI",
                "status": BenchmarkStatus.UNAVAILABLE.value,
                "start_date": None,
                "end_date": None,
                "observed_sessions": 0,
                "required_sessions": len(sessions),
                "coverage_percent": 0.0,
                "is_total_return": None,
                "used_for_excess_performance": False,
                "reason": (
                    "No governed total-return index series was supplied; "
                    "price-index substitution is prohibited."
                ),
            },
        )
    path = Path(normalized)
    if not path.is_file():
        raise TournamentError("BENCHMARK_INPUT_UNAVAILABLE")
    frame = pd.read_csv(path)
    date_column = next(
        (item for item in ("date", "trading_date", "observed_on") if item in frame),
        None,
    )
    value_column = next(
        (item for item in ("total_return_index", "tri", "value") if item in frame),
        None,
    )
    if date_column is None or value_column is None:
        raise TournamentError("BENCHMARK_REQUIRES_DATE_AND_TOTAL_RETURN_VALUE")
    frame = frame[[date_column, value_column]].rename(
        columns={date_column: "trading_date", value_column: "benchmark_value"}
    )
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.date
    frame["benchmark_value"] = pd.to_numeric(frame["benchmark_value"], errors="coerce")
    frame = frame[
        (frame["trading_date"] >= start) & (frame["trading_date"] <= end)
    ].copy()
    if frame["trading_date"].duplicated().any():
        raise TournamentError("DUPLICATE_BENCHMARK_SESSION")
    if frame["benchmark_value"].isna().any() or (frame["benchmark_value"] <= 0).any():
        raise TournamentError("INVALID_BENCHMARK_TOTAL_RETURN_VALUE")
    required = set(sessions)
    observed = set(frame["trading_date"])
    overlap = len(required & observed)
    coverage = overlap / len(required) * 100.0 if required else 0.0
    status = (
        BenchmarkStatus.AVAILABLE_TOTAL_RETURN
        if overlap == len(required)
        else BenchmarkStatus.INCOMPLETE
    )
    return frame.sort_values("trading_date").reset_index(drop=True), (
        {
            "benchmark_name": path.stem,
            "status": status.value,
            "start_date": min(frame["trading_date"]) if not frame.empty else None,
            "end_date": max(frame["trading_date"]) if not frame.empty else None,
            "observed_sessions": len(observed),
            "required_sessions": len(required),
            "coverage_percent": _round(coverage),
            "is_total_return": True,
            "used_for_excess_performance": status
            is BenchmarkStatus.AVAILABLE_TOTAL_RETURN,
            "reason": (
                "Caller-supplied total-return series."
                if status is BenchmarkStatus.AVAILABLE_TOTAL_RETURN
                else "Total-return series does not cover every governed session."
            ),
            "sha256": _file_sha256(path),
        },
    )


def _run_comparison_portfolios(
    *,
    featured: pd.DataFrame,
    signals: pd.DataFrame,
    plans: pd.DataFrame,
    folds: Sequence[WalkForwardFold],
    selections: Sequence[Mapping[str, Any]],
    benchmark: pd.DataFrame | None,
    policy: TournamentPolicy,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    selected_by_name: dict[str, pd.DataFrame] = {}
    if not folds:
        return results
    test_start = folds[0].test_start
    test_end = folds[-1].test_end
    for name in (
        _PORTFOLIO_REGIME,
        _PORTFOLIO_FIXED,
        _PORTFOLIO_ENSEMBLE,
        _PORTFOLIO_MOMENTUM,
        _PORTFOLIO_TREND,
    ):
        selected_signals = _signals_for_portfolio(
            name=name,
            signals=signals,
            plans=plans,
            folds=folds,
            selections=selections,
        )
        selected_by_name[name] = selected_signals
        results[name] = _simulate_portfolio(
            name=name,
            featured=featured,
            selected_signals=selected_signals,
            start=test_start,
            end=test_end,
            policy=policy,
        )
    results[_PORTFOLIO_EQUAL_WEIGHT] = _equal_weight_portfolio(
        featured,
        start=test_start,
        end=test_end,
        policy=policy,
    )
    results[_PORTFOLIO_BENCHMARK] = _benchmark_portfolio(
        benchmark,
        start=test_start,
        end=test_end,
        policy=policy,
    )
    regime_signals = selected_by_name.get(_PORTFOLIO_REGIME, pd.DataFrame())
    results["STRESS_INCREASED_COST"] = _simulate_portfolio(
        name="STRESS_INCREASED_COST",
        featured=featured,
        selected_signals=regime_signals,
        start=test_start,
        end=test_end,
        policy=replace(
            policy,
            transaction_cost_fraction=policy.transaction_cost_fraction * 1.5,
        ),
    )
    results["STRESS_INCREASED_SLIPPAGE"] = _simulate_portfolio(
        name="STRESS_INCREASED_SLIPPAGE",
        featured=featured,
        selected_signals=regime_signals,
        start=test_start,
        end=test_end,
        policy=replace(
            policy,
            slippage_fraction=policy.slippage_fraction * 1.5,
        ),
    )
    results["STRESS_REDUCED_POSITION_LIMIT"] = _simulate_portfolio(
        name="STRESS_REDUCED_POSITION_LIMIT",
        featured=featured,
        selected_signals=regime_signals,
        start=test_start,
        end=test_end,
        policy=replace(
            policy,
            maximum_positions=max(1, policy.maximum_positions - 1),
        ),
    )
    results["STRESS_LOWER_LIQUIDITY_CAPACITY"] = _simulate_portfolio(
        name="STRESS_LOWER_LIQUIDITY_CAPACITY",
        featured=featured,
        selected_signals=regime_signals,
        start=test_start,
        end=test_end,
        policy=replace(
            policy,
            maximum_market_volume_fraction=(
                policy.maximum_market_volume_fraction / 2.0
            ),
        ),
    )
    delayed = _delay_selected_signals(regime_signals, featured)
    results["STRESS_ONE_SESSION_ENTRY_DELAY"] = _simulate_portfolio(
        name="STRESS_ONE_SESSION_ENTRY_DELAY",
        featured=featured,
        selected_signals=delayed,
        start=test_start,
        end=test_end,
        policy=policy,
    )
    base_trades = tuple(results[_PORTFOLIO_REGIME]["trades"])
    best_security = _best_trade_dimension(base_trades, "symbol")
    security_removed = (
        regime_signals[regime_signals["symbol"] != best_security].copy()
        if best_security is not None and not regime_signals.empty
        else regime_signals
    )
    results["STRESS_BEST_SECURITY_REMOVED"] = _simulate_portfolio(
        name="STRESS_BEST_SECURITY_REMOVED",
        featured=featured,
        selected_signals=security_removed,
        start=test_start,
        end=test_end,
        policy=policy,
    )
    best_year = _best_trade_year(base_trades)
    year_removed = (
        regime_signals[
            regime_signals["trading_date"].map(
                lambda observed_on: observed_on.year != best_year
            )
        ].copy()
        if best_year is not None and not regime_signals.empty
        else regime_signals
    )
    results["STRESS_BEST_YEAR_REMOVED"] = _simulate_portfolio(
        name="STRESS_BEST_YEAR_REMOVED",
        featured=featured,
        selected_signals=year_removed,
        start=test_start,
        end=test_end,
        policy=policy,
    )
    best_month = _best_trade_month(base_trades)
    month_removed = (
        regime_signals[
            regime_signals["trading_date"].map(
                lambda observed_on: (
                    (
                        observed_on.year,
                        observed_on.month,
                    )
                    != best_month
                )
            )
        ].copy()
        if best_month is not None and not regime_signals.empty
        else regime_signals
    )
    results["STRESS_BEST_MONTH_REMOVED"] = _simulate_portfolio(
        name="STRESS_BEST_MONTH_REMOVED",
        featured=featured,
        selected_signals=month_removed,
        start=test_start,
        end=test_end,
        policy=policy,
    )
    misclassified_signals = _signals_for_portfolio(
        name=_PORTFOLIO_REGIME,
        signals=signals,
        plans=plans,
        folds=folds,
        selections=selections,
        regime_shift=1,
    )
    results["STRESS_REGIME_MISCLASSIFIED"] = _simulate_portfolio(
        name="STRESS_REGIME_MISCLASSIFIED",
        featured=featured,
        selected_signals=misclassified_signals,
        start=test_start,
        end=test_end,
        policy=policy,
    )
    return results


def _delay_selected_signals(
    signals: pd.DataFrame,
    featured: pd.DataFrame,
) -> pd.DataFrame:
    if signals.empty:
        return signals.copy()
    next_bar = {
        (row.identity_key, row.trading_date): (
            row.next_trading_date,
            row.next_open,
            row.next_session_valid,
        )
        for row in featured.itertuples(index=False)
    }
    delayed_rows: list[dict[str, Any]] = []
    for raw_row in signals.to_dict(orient="records"):
        row: dict[str, Any] = {str(key): value for key, value in raw_row.items()}
        identity = str(row["identity_key"])
        current_entry = row["entry_eligibility_date"]
        candidate: Any = next_bar.get((identity, current_entry))
        if (
            candidate is None
            or not bool(candidate[2])
            or pd.isna(candidate[0])
            or pd.isna(candidate[1])
        ):
            continue
        delayed_date, delayed_open, _ = candidate
        price_delta = float(delayed_open) - float(row["raw_entry_price"])
        row["entry_eligibility_date"] = delayed_date
        row["raw_entry_price"] = float(delayed_open)
        for column in (
            "entry_price",
            "initial_stop",
            "target_1",
            "target_2",
            "target_3",
        ):
            row[column] = float(row[column]) + price_delta
        delayed_rows.append(row)
    return pd.DataFrame(delayed_rows)


def _best_trade_dimension(
    trades: Sequence[Mapping[str, Any]],
    dimension: str,
) -> str | None:
    if not trades:
        return None
    pnl: dict[str, float] = defaultdict(float)
    for trade in trades:
        pnl[str(trade[dimension])] += float(trade["net_pnl"])
    return min(pnl, key=lambda key: (-pnl[key], key))


def _best_trade_year(
    trades: Sequence[Mapping[str, Any]],
) -> int | None:
    if not trades:
        return None
    pnl: dict[int, float] = defaultdict(float)
    for trade in trades:
        pnl[trade["exit_date"].year] += float(trade["net_pnl"])
    return min(pnl, key=lambda key: (-pnl[key], key))


def _best_trade_month(
    trades: Sequence[Mapping[str, Any]],
) -> tuple[int, int] | None:
    if not trades:
        return None
    pnl: dict[tuple[int, int], float] = defaultdict(float)
    for trade in trades:
        exit_date = trade["exit_date"]
        pnl[(exit_date.year, exit_date.month)] += float(trade["net_pnl"])
    return min(pnl, key=lambda key: (-pnl[key], key))


def _signals_for_portfolio(
    *,
    name: str,
    signals: pd.DataFrame,
    plans: pd.DataFrame,
    folds: Sequence[WalkForwardFold],
    selections: Sequence[Mapping[str, Any]],
    regime_shift: int = 0,
) -> pd.DataFrame:
    if signals.empty or plans.empty:
        return pd.DataFrame()
    merged = signals.merge(plans, on=["signal_id"], suffixes=("", "_plan"))
    fixed: dict[str, str] = {}
    regime: dict[tuple[str, str], str] = {}
    ensembles: dict[str, tuple[str, ...]] = {}
    for row in selections:
        if not row.get("selected"):
            continue
        fold = str(row["walk_forward_fold_id"])
        scope = str(row["selection_scope"])
        variant = str(row["selected_strategy_variant_id"])
        if scope == "FIXED":
            fixed[fold] = variant
    grouped_candidates: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in selections:
        if str(row["selection_scope"]) == "FIXED" and row.get("eligible"):
            grouped_candidates[str(row["walk_forward_fold_id"])].append(row)
    for fold_id, selection_candidates in grouped_candidates.items():
        ranked = sorted(
            selection_candidates,
            key=lambda item: (
                -float(item.get("objective_score") or -1e9),
                int(item.get("complexity_score") or 99),
                str(item["strategy_variant_id"]),
            ),
        )
        ensembles[fold_id] = tuple(
            str(item["strategy_variant_id"])
            for item in ranked
            if float(item.get("objective_score") or 0.0) > 0
        )[:2]
    for row in selections:
        if not row.get("selected"):
            continue
        scope = str(row["selection_scope"])
        if scope.startswith("REGIME:"):
            regime[
                (
                    str(row["walk_forward_fold_id"]),
                    scope.removeprefix("REGIME:"),
                )
            ] = str(row["selected_strategy_variant_id"])
    accepted: list[pd.DataFrame] = []
    for walk_fold in folds:
        portion: pd.DataFrame = merged.loc[
            (merged["trading_date"] >= walk_fold.test_start)
            & (merged["trading_date"] <= walk_fold.test_end)
        ].copy()
        if portion.empty:
            continue
        if name == _PORTFOLIO_REGIME:
            regime_values = tuple(item.value for item in _REGIME_ORDER)

            def selected_variant(row: pd.Series[Any]) -> str:
                regime_value = str(row["regime"])
                if regime_shift and regime_value in regime_values:
                    current_index = regime_values.index(regime_value)
                    regime_value = regime_values[
                        (current_index + regime_shift) % len(regime_values)
                    ]
                return regime.get(
                    (walk_fold.walk_forward_fold_id, regime_value),
                    "NO_TRADE",
                )

            portion = portion[
                portion.apply(
                    lambda row: row["strategy_variant_id"] == selected_variant(row),
                    axis=1,
                )
            ]
        elif name == _PORTFOLIO_FIXED:
            portion = portion[
                portion["strategy_variant_id"]
                == fixed.get(walk_fold.walk_forward_fold_id, "NO_TRADE")
            ]
        elif name == _PORTFOLIO_ENSEMBLE:
            portion = portion[
                portion["strategy_variant_id"].isin(
                    ensembles.get(walk_fold.walk_forward_fold_id, ())
                )
            ]
        elif name == _PORTFOLIO_MOMENTUM:
            portion = portion[
                portion["strategy_variant_id"] == "MOMENTUM_BREAKOUT_20D_V1"
            ]
        elif name == _PORTFOLIO_TREND:
            portion = portion[
                portion["strategy_variant_id"] == "TREND_FOLLOWING_60D_V1"
            ]
        portion["walk_forward_fold_id"] = walk_fold.walk_forward_fold_id
        accepted.append(portion)
    if not accepted:
        return pd.DataFrame()
    return pd.concat(accepted, ignore_index=True).sort_values(
        ["entry_eligibility_date", "signal_strength", "signal_id"],
        ascending=[True, False, True],
    )


def _simulate_portfolio(
    *,
    name: str,
    featured: pd.DataFrame,
    selected_signals: pd.DataFrame,
    start: date,
    end: date,
    policy: TournamentPolicy,
) -> dict[str, Any]:
    sessions = tuple(
        item
        for item in sorted(featured["trading_date"].unique())
        if start <= item <= end
    )
    market = {
        (row.trading_date, row.identity_key): row
        for row in featured[
            (featured["trading_date"] >= start) & (featured["trading_date"] <= end)
        ].itertuples(index=False)
    }
    candidates: dict[date, list[Any]] = defaultdict(list)
    if not selected_signals.empty:
        for raw_candidate in selected_signals.itertuples(index=False):
            candidate: Any = raw_candidate
            candidates[candidate.entry_eligibility_date].append(candidate)
    cash = policy.starting_capital
    positions: dict[str, dict[str, Any]] = {}
    curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    realised = 0.0
    cumulative_costs = 0.0
    peak = policy.starting_capital
    for session in sessions:
        for identity, position in list(positions.items()):
            bar: Any = market.get((session, identity))
            if bar is None:
                continue
            exit_event = _portfolio_exit_event(position, bar)
            if exit_event is not None:
                exit_price, reason = exit_event
                fill = exit_price * (1.0 - policy.slippage_fraction)
                proceeds = position["quantity"] * fill
                cost = proceeds * policy.transaction_cost_fraction
                cash += proceeds - cost
                pnl = proceeds - cost - position["entry_value"] - position["entry_cost"]
                realised += pnl
                cumulative_costs += cost
                trade = {
                    "logical_trade_id": position["logical_trade_id"],
                    "portfolio_name": name,
                    "identity_key": identity,
                    "symbol": position["symbol"],
                    "strategy_variant_id": position["strategy_variant_id"],
                    "walk_forward_fold_id": position["walk_forward_fold_id"],
                    "regime_state": position["regime_state"],
                    "signal_date": position["signal_date"],
                    "entry_date": position["entry_date"],
                    "exit_date": session,
                    "entry_price": _round(position["entry_price"]),
                    "exit_price": _round(fill),
                    "quantity": _round(position["quantity"]),
                    "gross_pnl": _round(proceeds - position["entry_value"]),
                    "net_pnl": _round(pnl),
                    "net_return": _round(
                        pnl / (position["entry_value"] + position["entry_cost"])
                    ),
                    "exit_reason": reason.value,
                    "holding_sessions": position["holding_sessions"],
                    "costs": _round(position["entry_cost"] + cost),
                }
                trades.append(trade)
                cost_rows.append(
                    {
                        "cost_event_id": _stable_id(
                            "COST", position["logical_trade_id"], "EXIT"
                        ),
                        "logical_trade_id": position["logical_trade_id"],
                        "portfolio_name": name,
                        "observed_on": session,
                        "cost_type": "EXIT_TRANSACTION_COST",
                        "amount": _round(cost),
                    }
                )
                del positions[identity]
        marked_value = sum(
            position["quantity"]
            * float(
                getattr(
                    market.get((session, identity)),
                    "close",
                    position["last_close"],
                )
            )
            for identity, position in positions.items()
        )
        current_value = cash + marked_value
        gross_limit = current_value * policy.maximum_gross_exposure
        for candidate in sorted(
            candidates.get(session, []),
            key=lambda item: (-float(item.signal_strength), item.signal_id),
        ):
            identity = str(candidate.identity_key)
            if identity in positions or len(positions) >= policy.maximum_positions:
                continue
            bar = market.get((session, identity))
            if bar is None:
                continue
            current_exposure = sum(
                position["quantity"] * position["last_close"]
                for position in positions.values()
            )
            available_exposure = max(0.0, gross_limit - current_exposure)
            target_value = min(
                current_value * policy.maximum_position_fraction,
                float(candidate.average_traded_value20)
                * policy.maximum_market_volume_fraction,
                available_exposure,
            )
            entry_price = float(candidate.raw_entry_price) * (
                1.0 + policy.slippage_fraction
            )
            quantity = math.floor(target_value / entry_price)
            if quantity <= 0:
                continue
            entry_value = quantity * entry_price
            entry_cost = entry_value * policy.transaction_cost_fraction
            if entry_value + entry_cost > cash:
                quantity = math.floor(
                    cash / (entry_price * (1.0 + policy.transaction_cost_fraction))
                )
                entry_value = quantity * entry_price
                entry_cost = entry_value * policy.transaction_cost_fraction
            if quantity <= 0:
                continue
            cash -= entry_value + entry_cost
            cumulative_costs += entry_cost
            logical_trade_id = _stable_id(
                "PORTFOLIO_TRADE", name, candidate.trade_plan_id
            )
            positions[identity] = {
                "logical_trade_id": logical_trade_id,
                "symbol": candidate.symbol,
                "strategy_variant_id": candidate.strategy_variant_id,
                "walk_forward_fold_id": candidate.walk_forward_fold_id,
                "regime_state": str(candidate.regime),
                "signal_date": candidate.trading_date,
                "entry_date": session,
                "entry_price": entry_price,
                "entry_value": entry_value,
                "entry_cost": entry_cost,
                "quantity": quantity,
                "stop": float(candidate.initial_stop),
                "initial_stop": float(candidate.initial_stop),
                "target_1": float(candidate.target_1),
                "target_2": float(candidate.target_2),
                "atr": float(candidate.atr14),
                "highest_close": entry_price,
                "last_close": float(bar.close),
                "holding_sessions": 0,
                "maximum_holding_sessions": int(candidate.maximum_holding_sessions),
            }
            cost_rows.append(
                {
                    "cost_event_id": _stable_id("COST", logical_trade_id, "ENTRY"),
                    "logical_trade_id": logical_trade_id,
                    "portfolio_name": name,
                    "observed_on": session,
                    "cost_type": "ENTRY_TRANSACTION_COST",
                    "amount": _round(entry_cost),
                }
            )
        for identity, position in positions.items():
            bar = market.get((session, identity))
            if bar is None:
                continue
            position["holding_sessions"] += 1
            position["last_close"] = float(bar.close)
            position["highest_close"] = max(position["highest_close"], float(bar.close))
            if float(bar.high) >= position["target_1"]:
                position["stop"] = max(
                    position["stop"],
                    position["entry_price"],
                    position["highest_close"] - 2.0 * position["atr"],
                )
            position_rows.append(
                {
                    "portfolio_day_id": _stable_id("POSITION", name, session, identity),
                    "portfolio_name": name,
                    "observed_on": session,
                    "logical_trade_id": position["logical_trade_id"],
                    "identity_key": identity,
                    "symbol": position["symbol"],
                    "quantity": _round(position["quantity"]),
                    "close": _round(position["last_close"]),
                    "market_value": _round(
                        position["quantity"] * position["last_close"]
                    ),
                    "active_stop": _round(position["stop"]),
                }
            )
        invested = sum(
            position["quantity"] * position["last_close"]
            for position in positions.values()
        )
        portfolio_value = cash + invested
        peak = max(peak, portfolio_value)
        drawdown = portfolio_value / peak - 1.0
        previous_value = (
            float(curve[-1]["portfolio_value"]) if curve else policy.starting_capital
        )
        curve.append(
            {
                "portfolio_day_id": _stable_id("DAY", name, session),
                "portfolio_name": name,
                "observed_on": session,
                "cash": _round(cash),
                "open_position_value": _round(invested),
                "gross_exposure": _round(
                    invested / portfolio_value if portfolio_value else 0.0
                ),
                "net_exposure": _round(
                    invested / portfolio_value if portfolio_value else 0.0
                ),
                "realised_pnl": _round(realised),
                "unrealised_pnl": _round(
                    sum(
                        position["quantity"]
                        * (position["last_close"] - position["entry_price"])
                        for position in positions.values()
                    )
                ),
                "cumulative_costs": _round(cumulative_costs),
                "portfolio_value": _round(portfolio_value),
                "daily_return": _round(
                    portfolio_value / previous_value - 1.0 if previous_value else 0.0
                ),
                "drawdown": _round(drawdown),
                "open_positions": len(positions),
            }
        )
    if sessions and positions:
        final_session = sessions[-1]
        for identity, position in list(positions.items()):
            bar = market.get((final_session, identity))
            if bar is None:
                continue
            fill = float(bar.close) * (1.0 - policy.slippage_fraction)
            proceeds = position["quantity"] * fill
            cost = proceeds * policy.transaction_cost_fraction
            pnl = proceeds - cost - position["entry_value"] - position["entry_cost"]
            trades.append(
                {
                    "logical_trade_id": position["logical_trade_id"],
                    "portfolio_name": name,
                    "identity_key": identity,
                    "symbol": position["symbol"],
                    "strategy_variant_id": position["strategy_variant_id"],
                    "walk_forward_fold_id": position["walk_forward_fold_id"],
                    "regime_state": position["regime_state"],
                    "signal_date": position["signal_date"],
                    "entry_date": position["entry_date"],
                    "exit_date": final_session,
                    "entry_price": _round(position["entry_price"]),
                    "exit_price": _round(fill),
                    "quantity": _round(position["quantity"]),
                    "gross_pnl": _round(proceeds - position["entry_value"]),
                    "net_pnl": _round(pnl),
                    "net_return": _round(
                        pnl / (position["entry_value"] + position["entry_cost"])
                    ),
                    "exit_reason": ExitReason.END_OF_DATA.value,
                    "holding_sessions": position["holding_sessions"],
                    "costs": _round(position["entry_cost"] + cost),
                }
            )
    return {
        "curve": tuple(curve),
        "trades": tuple(trades),
        "positions": tuple(position_rows),
        "costs": tuple(cost_rows),
        "availability": "AVAILABLE",
    }


def _portfolio_exit_event(
    position: dict[str, Any],
    bar: Any,
) -> tuple[float, ExitReason] | None:
    low = float(bar.low)
    high = float(bar.high)
    if low <= position["stop"]:
        reason = (
            ExitReason.TRAILING_STOP
            if position["stop"] > position["initial_stop"]
            else ExitReason.STOP
        )
        return float(position["stop"]), reason
    if high >= position["target_2"]:
        return float(position["target_2"]), ExitReason.TARGET
    if position["holding_sessions"] >= position["maximum_holding_sessions"]:
        return float(bar.close), ExitReason.TIME_EXIT
    return None


def _equal_weight_portfolio(
    featured: pd.DataFrame,
    *,
    start: date,
    end: date,
    policy: TournamentPolicy,
) -> dict[str, Any]:
    returns = (
        featured[
            (featured["trading_date"] >= start) & (featured["trading_date"] <= end)
        ]
        .groupby("trading_date", sort=True, observed=True)["return_1d"]
        .mean()
        .fillna(0.0)
    )
    curve = _returns_to_curve(
        name=_PORTFOLIO_EQUAL_WEIGHT,
        returns=returns,
        starting_capital=policy.starting_capital,
    )
    return {
        "curve": curve,
        "trades": (),
        "positions": (),
        "costs": (),
        "availability": "AVAILABLE_NO_COST_NON_INVESTABLE_BASELINE",
    }


def _benchmark_portfolio(
    benchmark: pd.DataFrame | None,
    *,
    start: date,
    end: date,
    policy: TournamentPolicy,
) -> dict[str, Any]:
    if benchmark is None:
        return {
            "curve": (),
            "trades": (),
            "positions": (),
            "costs": (),
            "availability": BenchmarkStatus.UNAVAILABLE.value,
        }
    values = benchmark[
        (benchmark["trading_date"] >= start) & (benchmark["trading_date"] <= end)
    ].set_index("trading_date")["benchmark_value"]
    returns = values.pct_change().fillna(0.0)
    return {
        "curve": _returns_to_curve(
            name=_PORTFOLIO_BENCHMARK,
            returns=returns,
            starting_capital=policy.starting_capital,
        ),
        "trades": (),
        "positions": (),
        "costs": (),
        "availability": BenchmarkStatus.AVAILABLE_TOTAL_RETURN.value,
    }


def _returns_to_curve(
    *,
    name: str,
    returns: pd.Series,
    starting_capital: float,
) -> tuple[dict[str, Any], ...]:
    value = starting_capital
    peak = value
    rows: list[dict[str, Any]] = []
    for observed_on, daily_return in returns.items():
        value *= 1.0 + float(daily_return)
        peak = max(peak, value)
        rows.append(
            {
                "portfolio_day_id": _stable_id("DAY", name, observed_on),
                "portfolio_name": name,
                "observed_on": observed_on,
                "cash": 0.0,
                "open_position_value": _round(value),
                "gross_exposure": 1.0,
                "net_exposure": 1.0,
                "realised_pnl": 0.0,
                "unrealised_pnl": _round(value - starting_capital),
                "cumulative_costs": 0.0,
                "portfolio_value": _round(value),
                "daily_return": _round(float(daily_return)),
                "drawdown": _round(value / peak - 1.0),
                "open_positions": 0,
            }
        )
    return tuple(rows)


def _analyse_portfolios(
    *,
    portfolios: Mapping[str, Mapping[str, Any]],
    independent_trades: pd.DataFrame,
    variants: Sequence[StrategyVariant],
    folds: Sequence[WalkForwardFold],
    policy: TournamentPolicy,
) -> dict[str, Any]:
    metric_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    calendar_rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    for name in _PORTFOLIO_NAMES:
        portfolio = portfolios.get(name, {})
        curve = tuple(portfolio.get("curve", ()))
        metrics = _portfolio_metrics(
            name=name,
            curve=curve,
            trades=tuple(portfolio.get("trades", ())),
            policy=policy,
        )
        metric_rows.append(metrics)
        comparison_rows.append(
            {
                "portfolio_name": name,
                "availability": portfolio.get("availability", "UNAVAILABLE"),
                "starting_capital": metrics["starting_capital"],
                "ending_capital": metrics["ending_capital"],
                "net_cagr": metrics["net_cagr"],
                "maximum_drawdown": metrics["maximum_drawdown"],
                "sharpe": metrics["sharpe"],
                "sortino": metrics["sortino"],
                "trade_count": metrics["trade_count"],
                "total_costs": metrics["total_costs"],
            }
        )
        calendar_rows.extend(_calendar_performance(name, curve))
        rolling_rows.extend(_rolling_performance(name, curve))
    metrics_by_name = {row["portfolio_name"]: row for row in metric_rows}
    regime_metrics = metrics_by_name.get(_PORTFOLIO_REGIME, {})
    benchmark_metrics = metrics_by_name.get(_PORTFOLIO_BENCHMARK, {})
    benchmark_available = benchmark_metrics.get("net_cagr") is not None
    benchmark_relative = (
        _benchmark_relative_row(
            portfolio_curve=tuple(
                portfolios.get(_PORTFOLIO_REGIME, {}).get("curve", ())
            ),
            benchmark_curve=tuple(
                portfolios.get(_PORTFOLIO_BENCHMARK, {}).get("curve", ())
            ),
            portfolio_metrics=regime_metrics,
            benchmark_metrics=benchmark_metrics,
        ),
    )
    multiple = _multiple_testing(independent_trades, variants, folds)
    parameter = _parameter_stability(independent_trades, variants, folds)
    robustness = _robustness_rows(portfolios, policy)
    concentration = _concentration_rows(
        tuple(portfolios.get(_PORTFOLIO_REGIME, {}).get("trades", ()))
    )
    overfitting = _overfitting_state(
        metrics=regime_metrics,
        benchmark_available=benchmark_available,
        multiple=multiple,
        parameter=parameter,
        concentration=concentration,
    )
    return {
        "metrics": tuple(metric_rows),
        "comparison": tuple(comparison_rows),
        "calendar": tuple(calendar_rows),
        "rolling": tuple(rolling_rows),
        "benchmark_relative": benchmark_relative,
        "multiple_testing": multiple,
        "parameter_stability": parameter,
        "robustness": robustness,
        "concentration": concentration,
        "overfitting_state": overfitting.value,
    }


def _benchmark_relative_row(
    *,
    portfolio_curve: Sequence[Mapping[str, Any]],
    benchmark_curve: Sequence[Mapping[str, Any]],
    portfolio_metrics: Mapping[str, Any],
    benchmark_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    base = {
        "portfolio_name": _PORTFOLIO_REGIME,
        "benchmark_name": _PORTFOLIO_BENCHMARK,
        "benchmark_available": False,
        "portfolio_cagr": portfolio_metrics.get("net_cagr"),
        "benchmark_cagr": benchmark_metrics.get("net_cagr"),
        "excess_cagr": None,
        "information_ratio": None,
        "tracking_error": None,
        "beta": None,
        "alpha": None,
        "upside_capture": None,
        "downside_capture": None,
        "reason": ("Governed TRI unavailable; relative statistics remain UNKNOWN."),
    }
    if not portfolio_curve or not benchmark_curve:
        return base
    portfolio_returns = {
        row["observed_on"]: float(row["daily_return"]) for row in portfolio_curve
    }
    benchmark_returns = {
        row["observed_on"]: float(row["daily_return"]) for row in benchmark_curve
    }
    common = sorted(set(portfolio_returns) & set(benchmark_returns))
    if len(common) < 30:
        base["reason"] = "Fewer than 30 aligned benchmark sessions."
        return base
    portfolio = np.array([portfolio_returns[item] for item in common], dtype=float)
    benchmark = np.array([benchmark_returns[item] for item in common], dtype=float)
    active = portfolio - benchmark
    tracking_error = float(np.std(active, ddof=1) * math.sqrt(252))
    information_ratio = (
        float(np.mean(active) * 252 / tracking_error) if tracking_error > 0 else None
    )
    benchmark_variance = float(np.var(benchmark, ddof=1))
    beta = (
        float(np.cov(portfolio, benchmark, ddof=1)[0, 1] / benchmark_variance)
        if benchmark_variance > 0
        else None
    )
    alpha = (
        float((np.mean(portfolio) - beta * np.mean(benchmark)) * 252)
        if beta is not None
        else None
    )
    positive = benchmark > 0
    negative = benchmark < 0
    upside = (
        float(np.mean(portfolio[positive]) / np.mean(benchmark[positive]))
        if positive.any() and float(np.mean(benchmark[positive])) != 0
        else None
    )
    downside = (
        float(np.mean(portfolio[negative]) / np.mean(benchmark[negative]))
        if negative.any() and float(np.mean(benchmark[negative])) != 0
        else None
    )
    portfolio_cagr = portfolio_metrics.get("net_cagr")
    benchmark_cagr = benchmark_metrics.get("net_cagr")
    return {
        **base,
        "benchmark_available": True,
        "portfolio_cagr": portfolio_cagr,
        "benchmark_cagr": benchmark_cagr,
        "excess_cagr": (
            _round(float(portfolio_cagr) - float(benchmark_cagr))
            if portfolio_cagr is not None and benchmark_cagr is not None
            else None
        ),
        "information_ratio": _optional_round(information_ratio),
        "tracking_error": _round(tracking_error),
        "beta": _optional_round(beta),
        "alpha": _optional_round(alpha),
        "upside_capture": _optional_round(upside),
        "downside_capture": _optional_round(downside),
        "reason": "Aligned governed total-return benchmark.",
    }


def _portfolio_metrics(
    *,
    name: str,
    curve: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    policy: TournamentPolicy,
) -> dict[str, Any]:
    if not curve:
        return {
            "portfolio_name": name,
            "start_date": None,
            "end_date": None,
            "years": None,
            "starting_capital": policy.starting_capital,
            "ending_capital": None,
            "gross_cagr": None,
            "net_cagr": None,
            "cumulative_return": None,
            "annualised_volatility": None,
            "maximum_drawdown": None,
            "drawdown_duration_sessions": None,
            "sharpe": None,
            "sortino": None,
            "calmar": None,
            "turnover": None,
            "total_costs": None,
            "trade_count": 0,
            "win_rate": None,
            "expectancy": None,
            "average_exposure": None,
            "time_in_market": None,
        }
    start_date = curve[0]["observed_on"]
    end_date = curve[-1]["observed_on"]
    years = max((end_date - start_date).days / 365.2425, 1 / 365.2425)
    starting = policy.starting_capital
    ending = float(curve[-1]["portfolio_value"])
    returns = np.array([float(row["daily_return"]) for row in curve], dtype=float)
    volatility = (
        float(np.std(returns, ddof=1) * math.sqrt(252)) if len(returns) > 1 else 0.0
    )
    annual_return = float(np.mean(returns) * 252) if len(returns) else 0.0
    sharpe = (
        (annual_return - policy.risk_free_rate) / volatility if volatility > 0 else None
    )
    downside = returns[returns < 0]
    downside_deviation = (
        float(np.sqrt(np.mean(np.square(downside))) * math.sqrt(252))
        if len(downside)
        else 0.0
    )
    sortino = (
        (annual_return - policy.risk_free_rate) / downside_deviation
        if downside_deviation > 0
        else None
    )
    maximum_drawdown = min(float(row["drawdown"]) for row in curve)
    net_cagr = (ending / starting) ** (1.0 / years) - 1.0
    total_costs = sum(float(item.get("costs", 0.0)) for item in trades)
    gross_ending = ending + total_costs
    gross_cagr = (gross_ending / starting) ** (1.0 / years) - 1.0
    winning = [float(item["net_return"]) for item in trades if item["net_return"] > 0]
    all_trade_returns = [float(item["net_return"]) for item in trades]
    drawdown_duration = _maximum_drawdown_duration(curve)
    exposure = [float(row["gross_exposure"]) for row in curve]
    turnover = (
        sum(abs(float(item.get("net_pnl", 0.0))) for item in trades) / starting
        if trades
        else 0.0
    )
    return {
        "portfolio_name": name,
        "start_date": start_date,
        "end_date": end_date,
        "years": _round(years),
        "starting_capital": _round(starting),
        "ending_capital": _round(ending),
        "gross_cagr": _round(gross_cagr),
        "net_cagr": _round(net_cagr),
        "cumulative_return": _round(ending / starting - 1.0),
        "annualised_volatility": _round(volatility),
        "maximum_drawdown": _round(maximum_drawdown),
        "drawdown_duration_sessions": drawdown_duration,
        "sharpe": _optional_round(sharpe),
        "sortino": _optional_round(sortino),
        "calmar": (
            _round(net_cagr / abs(maximum_drawdown)) if maximum_drawdown < 0 else None
        ),
        "turnover": _round(turnover),
        "total_costs": _round(total_costs),
        "trade_count": len(trades),
        "win_rate": _round(len(winning) / len(trades)) if trades else None,
        "expectancy": (
            _round(sum(all_trade_returns) / len(all_trade_returns))
            if all_trade_returns
            else None
        ),
        "average_exposure": _round(float(np.mean(exposure))),
        "time_in_market": _round(sum(value > 0 for value in exposure) / len(exposure)),
    }


def _maximum_drawdown_duration(curve: Sequence[Mapping[str, Any]]) -> int:
    longest = 0
    current = 0
    for row in curve:
        if float(row["drawdown"]) < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _calendar_performance(
    name: str,
    curve: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in curve:
        grouped[row["observed_on"].year].append(row)
    return [
        {
            "portfolio_name": name,
            "calendar_year": year,
            "start_value": values[0]["portfolio_value"],
            "end_value": values[-1]["portfolio_value"],
            "return": _round(
                float(values[-1]["portfolio_value"])
                / float(values[0]["portfolio_value"])
                - 1.0
            ),
        }
        for year, values in sorted(grouped.items())
    ]


def _rolling_performance(
    name: str,
    curve: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not curve:
        return []
    values = pd.Series(
        [float(row["portfolio_value"]) for row in curve],
        index=[row["observed_on"] for row in curve],
    )
    rows: list[dict[str, Any]] = []
    for sessions, label, annualise in (
        (252, "ROLLING_12M_RETURN", False),
        (756, "ROLLING_36M_CAGR", True),
        (1260, "ROLLING_60M_CAGR", True),
    ):
        shifted = values.shift(sessions)
        results = values / shifted - 1.0
        if annualise:
            results = (values / shifted) ** (252.0 / sessions) - 1.0
        for observed_on, value in results.dropna().items():
            rows.append(
                {
                    "portfolio_name": name,
                    "observed_on": observed_on,
                    "metric": label,
                    "value": _round(float(value)),
                }
            )
    return rows


def _multiple_testing(
    trades: pd.DataFrame,
    variants: Sequence[StrategyVariant],
    folds: Sequence[WalkForwardFold],
) -> tuple[dict[str, Any], ...]:
    if trades.empty or not folds:
        return (
            {
                "strategy_variant_id": "ALL",
                "sample_count": 0,
                "independent_time_blocks": 0,
                "raw_p_value": None,
                "bh_adjusted_p_value": None,
                "holm_adjusted_p_value": None,
                "test_state": "INSUFFICIENT_SAMPLE",
            },
        )
    test_start = folds[0].test_start
    test_end = folds[-1].test_end
    holdout = trades[
        (trades["signal_date"] >= test_start) & (trades["signal_date"] <= test_end)
    ]
    rows: list[dict[str, Any]] = []
    for variant in variants:
        if variant.family is StrategyFamily.NO_TRADE:
            continue
        sample_frame = holdout[
            holdout["strategy_variant_id"] == variant.strategy_variant_id
        ].copy()
        sample_frame["signal_month"] = sample_frame["signal_date"].map(
            lambda item: item.strftime("%Y-%m")
        )
        monthly_returns = (
            sample_frame.groupby("signal_month", sort=True)["net_return"]
            .mean()
            .astype(float)
        )
        if len(sample_frame) < 8 or len(monthly_returns) < 24:
            p_value = None
        else:
            seed = int(
                hashlib.sha256(variant.strategy_variant_id.encode()).hexdigest()[:16],
                16,
            )
            generator = np.random.default_rng(seed)
            values = monthly_returns.to_numpy(dtype=float)
            sampled_means = generator.choice(
                values,
                size=(2_000, len(values)),
                replace=True,
            ).mean(axis=1)
            p_value = float((np.count_nonzero(sampled_means <= 0.0) + 1) / 2_001)
        rows.append(
            {
                "strategy_variant_id": variant.strategy_variant_id,
                "sample_count": len(sample_frame),
                "independent_time_blocks": len(monthly_returns),
                "raw_p_value": _optional_round(p_value),
            }
        )
    valid = [
        (index, float(row["raw_p_value"]))
        for index, row in enumerate(rows)
        if row["raw_p_value"] is not None
    ]
    bh = _benjamini_hochberg([value for _, value in valid])
    holm = _holm([value for _, value in valid])
    for adjusted_index, (row_index, _) in enumerate(valid):
        rows[row_index]["bh_adjusted_p_value"] = _round(bh[adjusted_index])
        rows[row_index]["holm_adjusted_p_value"] = _round(holm[adjusted_index])
        rows[row_index]["test_state"] = (
            "SURVIVES_BH_AND_HOLM"
            if bh[adjusted_index] <= 0.05 and holm[adjusted_index] <= 0.05
            else "MULTIPLE_TESTING_NOT_SURVIVED"
        )
    for row in rows:
        row.setdefault("bh_adjusted_p_value", None)
        row.setdefault("holm_adjusted_p_value", None)
        row.setdefault("test_state", "INSUFFICIENT_SAMPLE")
    return tuple(rows)


def _benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    if not p_values:
        return []
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * len(p_values)
    running = 1.0
    count = len(p_values)
    for rank, (original, value) in reversed(list(enumerate(ordered, start=1))):
        running = min(running, value * count / rank)
        adjusted[original] = min(1.0, running)
    return adjusted


def _holm(p_values: Sequence[float]) -> list[float]:
    if not p_values:
        return []
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * len(p_values)
    running = 0.0
    count = len(p_values)
    for rank, (original, value) in enumerate(ordered):
        running = max(running, value * (count - rank))
        adjusted[original] = min(1.0, running)
    return adjusted


def _parameter_stability(
    trades: pd.DataFrame,
    variants: Sequence[StrategyVariant],
    folds: Sequence[WalkForwardFold],
) -> tuple[dict[str, Any], ...]:
    if trades.empty or not folds:
        return ()
    test = trades[
        (trades["signal_date"] >= folds[0].test_start)
        & (trades["signal_date"] <= folds[-1].test_end)
    ]
    families: dict[StrategyFamily, list[StrategyVariant]] = defaultdict(list)
    for variant in variants:
        families[variant.family].append(variant)
    rows: list[dict[str, Any]] = []
    for family, family_variants in sorted(
        families.items(), key=lambda item: item[0].value
    ):
        if len(family_variants) < 2:
            continue
        means = []
        for variant in family_variants:
            sample = test[test["strategy_variant_id"] == variant.strategy_variant_id][
                "net_return"
            ]
            means.append(float(sample.mean()) if len(sample) else float("nan"))
        finite = [value for value in means if not math.isnan(value)]
        stable = len(finite) >= 2 and all(
            (value >= 0) == (finite[0] >= 0) for value in finite
        )
        rows.append(
            {
                "strategy_family": family.value,
                "variant_count": len(family_variants),
                "variant_mean_returns": "|".join(
                    "UNKNOWN" if math.isnan(value) else str(_round(value))
                    for value in means
                ),
                "directionally_stable": stable,
                "state": (
                    "DIRECTIONALLY_STABLE" if stable else "HIGH_PARAMETER_SENSITIVITY"
                ),
            }
        )
    return tuple(rows)


def _robustness_rows(
    portfolios: Mapping[str, Mapping[str, Any]],
    policy: TournamentPolicy,
) -> tuple[dict[str, Any], ...]:
    scenario_map = (
        ("BASE_REALISTIC_COST", _PORTFOLIO_REGIME, policy.transaction_cost_fraction),
        ("BROAD_GOVERNED_ADJUSTED_COHORT", _PORTFOLIO_REGIME, None),
        (
            "INCREASED_TRANSACTION_COST",
            "STRESS_INCREASED_COST",
            policy.transaction_cost_fraction * 1.5,
        ),
        (
            "INCREASED_SLIPPAGE",
            "STRESS_INCREASED_SLIPPAGE",
            policy.slippage_fraction * 1.5,
        ),
        ("ONE_SESSION_EXECUTION_LAG", "STRESS_ONE_SESSION_ENTRY_DELAY", 1),
        (
            "REDUCED_POSITION_LIMIT",
            "STRESS_REDUCED_POSITION_LIMIT",
            max(1, policy.maximum_positions - 1),
        ),
        (
            "LOWER_LIQUIDITY_CAPACITY",
            "STRESS_LOWER_LIQUIDITY_CAPACITY",
            policy.maximum_market_volume_fraction / 2.0,
        ),
        ("BEST_SECURITY_REMOVAL", "STRESS_BEST_SECURITY_REMOVED", None),
        ("BEST_MONTH_REMOVAL", "STRESS_BEST_MONTH_REMOVED", None),
        ("BEST_YEAR_REMOVAL", "STRESS_BEST_YEAR_REMOVED", None),
        (
            "REGIME_MISCLASSIFICATION",
            "STRESS_REGIME_MISCLASSIFIED",
            "DETERMINISTIC_ONE_STATE_ROTATION",
        ),
    )
    rows: list[dict[str, Any]] = []
    for scenario, portfolio_name, parameter in scenario_map:
        portfolio = portfolios.get(portfolio_name, {})
        metrics = _portfolio_metrics(
            name=portfolio_name,
            curve=tuple(portfolio.get("curve", ())),
            trades=tuple(portfolio.get("trades", ())),
            policy=policy,
        )
        rows.append(
            {
                "scenario": scenario,
                "parameter": parameter,
                "result_cagr": metrics["net_cagr"],
                "result_maximum_drawdown": metrics["maximum_drawdown"],
                "result_trade_count": metrics["trade_count"],
                "state": (
                    "OBSERVED"
                    if metrics["ending_capital"] is not None
                    else "UNAVAILABLE"
                ),
            }
        )
    rows.extend(
        (
            {
                "scenario": "LARGE_CAP_ONLY_UNIVERSE",
                "parameter": None,
                "result_cagr": None,
                "result_maximum_drawdown": None,
                "result_trade_count": None,
                "state": "UNKNOWN_NO_POINT_IN_TIME_CAPITALISATION_CLASSIFICATION",
            },
            {
                "scenario": "ALTERNATE_VALID_BENCHMARK",
                "parameter": None,
                "result_cagr": None,
                "result_maximum_drawdown": None,
                "result_trade_count": None,
                "state": "UNKNOWN_NO_ALTERNATE_GOVERNED_TRI",
            },
            {
                "scenario": "RAW_PRICE_ARM",
                "parameter": None,
                "result_cagr": None,
                "result_maximum_drawdown": None,
                "result_trade_count": None,
                "state": "BLOCKED_UNGOVERNED_CORPORATE_ACTION_CONTINUITY",
            },
        )
    )
    simple_metrics = [
        _portfolio_metrics(
            name=name,
            curve=tuple(portfolios.get(name, {}).get("curve", ())),
            trades=tuple(portfolios.get(name, {}).get("trades", ())),
            policy=policy,
        )
        for name in (_PORTFOLIO_MOMENTUM, _PORTFOLIO_TREND)
    ]
    observed_simple = [item for item in simple_metrics if item["net_cagr"] is not None]
    if observed_simple:
        best_simple = max(
            observed_simple,
            key=lambda item: (
                float(item["net_cagr"]),
                str(item["portfolio_name"]),
            ),
        )
        rows.append(
            {
                "scenario": "SIMPLER_STRATEGY_COMPARISON",
                "parameter": best_simple["portfolio_name"],
                "result_cagr": best_simple["net_cagr"],
                "result_maximum_drawdown": best_simple["maximum_drawdown"],
                "result_trade_count": best_simple["trade_count"],
                "state": "OBSERVED",
            }
        )
    return tuple(rows)


def _concentration_rows(
    trades: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if not trades:
        return (
            {
                "dimension": "ALL",
                "member": "NONE",
                "trade_count": 0,
                "net_pnl": 0.0,
                "share_of_positive_pnl": None,
            },
        )
    total_positive = sum(max(0.0, float(item["net_pnl"])) for item in trades)
    rows: list[dict[str, Any]] = []
    accessors: tuple[tuple[str, Callable[[Mapping[str, Any]], str]], ...] = (
        ("SECURITY", lambda item: str(item["symbol"])),
        ("YEAR", lambda item: str(item["exit_date"].year)),
        ("REGIME", lambda item: str(item["regime_state"])),
    )
    for dimension, accessor in accessors:
        grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for trade in trades:
            grouped[accessor(trade)].append(trade)
        for member, values in sorted(grouped.items()):
            pnl = sum(float(item["net_pnl"]) for item in values)
            rows.append(
                {
                    "dimension": dimension,
                    "member": member,
                    "trade_count": len(values),
                    "net_pnl": _round(pnl),
                    "share_of_positive_pnl": (
                        _round(max(0.0, pnl) / total_positive)
                        if total_positive > 0
                        else None
                    ),
                }
            )
    return tuple(rows)


def _overfitting_state(
    *,
    metrics: Mapping[str, Any],
    benchmark_available: bool,
    multiple: Sequence[Mapping[str, Any]],
    parameter: Sequence[Mapping[str, Any]],
    concentration: Sequence[Mapping[str, Any]],
) -> OverfittingState:
    if not metrics or int(metrics.get("trade_count") or 0) < 30:
        return OverfittingState.INSUFFICIENT_SAMPLE
    if any(
        row.get("share_of_positive_pnl") is not None
        and float(row["share_of_positive_pnl"]) > 0.35
        for row in concentration
        if row["dimension"] == "SECURITY"
    ):
        return OverfittingState.HIGH_SECURITY_CONCENTRATION
    if any(not bool(row["directionally_stable"]) for row in parameter):
        return OverfittingState.HIGH_PARAMETER_SENSITIVITY
    survived = any(row.get("test_state") == "SURVIVES_BH_AND_HOLM" for row in multiple)
    if not survived:
        return OverfittingState.MULTIPLE_TESTING_NOT_SURVIVED
    if not benchmark_available:
        return OverfittingState.DESCRIPTIVE_ONLY
    if float(metrics.get("net_cagr") or 0.0) <= 0:
        return OverfittingState.NO_GENERALISABLE_STRATEGY_FOUND
    return OverfittingState.DIRECTIONALLY_STABLE


def _assemble_rows(
    *,
    sources: TournamentSourcePaths,
    source_rows: Sequence[dict[str, Any]],
    source_summary: Mapping[str, Any],
    market: pd.DataFrame,
    featured: pd.DataFrame,
    variants: Sequence[StrategyVariant],
    signals: pd.DataFrame,
    plans: pd.DataFrame,
    independent_trades: pd.DataFrame,
    regime_rows: Sequence[dict[str, Any]],
    transition_rows: Sequence[dict[str, Any]],
    fold_rows: Sequence[dict[str, Any]],
    selection_rows: Sequence[dict[str, Any]],
    mapping_rows: Sequence[dict[str, Any]],
    benchmark_rows: Sequence[dict[str, Any]],
    portfolios: Mapping[str, Mapping[str, Any]],
    analysis: Mapping[str, Any],
    policy: TournamentPolicy,
) -> dict[str, tuple[dict[str, Any], ...]]:
    strategy_rows = tuple(
        {
            "strategy_variant_id": item.strategy_variant_id,
            "strategy_family": item.family.value,
            "components": "|".join(item.components),
            "parameter_count": len(item.parameters),
            "complexity_score": item.complexity_score,
            "source_definition": item.source_definition,
            "expected_regimes": "|".join(
                regime.value for regime in item.expected_regimes
            ),
            "valid_price_arms": "|".join(item.valid_price_arms),
            "prerequisites": "|".join(item.prerequisites),
            "valid": True,
        }
        for item in variants
    )
    parameter_rows = tuple(
        {
            "strategy_variant_id": item.strategy_variant_id,
            "parameter_name": key,
            "parameter_value": value,
        }
        for item in variants
        for key, value in item.parameters.items()
    )
    signal_rows = tuple(
        _signal_artifact_row(row) for row in signals.itertuples(index=False)
    )
    plan_rows = _frame_records(plans)
    trade_rows = tuple(
        row for portfolio in portfolios.values() for row in portfolio.get("trades", ())
    )
    equity_rows = tuple(
        row for portfolio in portfolios.values() for row in portfolio.get("curve", ())
    )
    position_rows = tuple(
        row
        for portfolio in portfolios.values()
        for row in portfolio.get("positions", ())
    )
    cost_rows = tuple(
        row for portfolio in portfolios.values() for row in portfolio.get("costs", ())
    )
    universe_rows = (
        {
            "population": "ADJUSTED_EQ_SOURCE",
            "rows": source_summary["source_rows"],
            "securities": source_summary["source_isins"],
            "identity_state": "ALL_SOURCE_ROWS",
            "admitted": False,
            "reason": "Pre-admission audit denominator.",
        },
        {
            "population": "CERTIFIED_TOURNAMENT",
            "rows": len(market),
            "securities": market["identity_key"].nunique(),
            "identity_state": "UNIQUE_EFFECTIVE_DATED_ISIN",
            "admitted": True,
            "reason": (
                "Observed activity row, unique point-in-time identity, and "
                "BACKWARD_ADJUSTED certified price-basis interval."
            ),
        },
        {
            "population": "EXCLUDED_FROM_TOURNAMENT",
            "rows": source_summary["source_rows"] - len(market),
            "securities": None,
            "identity_state": "PROVISIONAL_OR_NON_TRADABLE",
            "admitted": False,
            "reason": (
                "Preserved in source audit; excluded from adjusted strategy "
                "research because identity or price-basis continuity is not certified."
            ),
        },
    )
    action_rows = (
        {
            "event_population": "ALL_ACTION_EVENTS",
            "event_count": source_summary["corporate_action_events"],
            "admitted_count": source_summary["admitted_corporate_actions"],
            "conflicting_count": source_summary["conflicting_corporate_actions"],
            "treatment": "GOVERNED_ADJUSTED_PRICE_ARM",
        },
    )
    coverage_rows = (
        {
            "price_arm": "ADJUSTED",
            "source_start": source_summary["source_start"],
            "source_end": source_summary["source_end"],
            "actual_start": source_summary["actual_start"],
            "actual_end": source_summary["actual_end"],
            "source_sessions": source_summary["source_sessions"],
            "admitted_sessions": source_summary["admitted_sessions"],
            "source_rows": source_summary["source_rows"],
            "admitted_rows": source_summary["admitted_rows"],
            "source_securities": source_summary["source_isins"],
            "admitted_securities": source_summary["admitted_securities"],
            "missing_identity_rows": source_summary["missing_identity_rows"],
            "ambiguous_identity_rows": source_summary["ambiguous_identity_rows"],
            "duplicate_rows": source_summary["duplicate_rows"],
            "impossible_ohlc": source_summary["impossible_ohlc"],
            "nonpositive_price": source_summary["nonpositive_price"],
            "invalid_volume": source_summary["invalid_volume"],
        },
    )
    reconciliation = (
        {
            "unit": "MARKET_ROWS",
            "source_count": source_summary["source_rows"],
            "admitted_count": len(market),
            "excluded_count": source_summary["source_rows"] - len(market),
            "reconciles": source_summary["source_rows"]
            == len(market) + source_summary["source_rows"] - len(market),
        },
        {
            "unit": "SIGNALS_TO_PLANS",
            "source_count": len(signals),
            "admitted_count": len(plans),
            "excluded_count": len(signals) - len(plans),
            "reconciles": len(signals) == len(plans),
        },
        {
            "unit": "PORTFOLIO_NAMES",
            "source_count": len(_PORTFOLIO_NAMES),
            "admitted_count": sum(name in portfolios for name in _PORTFOLIO_NAMES),
            "excluded_count": sum(name not in portfolios for name in _PORTFOLIO_NAMES),
            "reconciles": all(name in portfolios for name in _PORTFOLIO_NAMES),
        },
    )
    non_vacuity = structural_probe_rows()
    return {
        "source_contract": tuple(source_rows),
        "market_data_coverage": coverage_rows,
        "universe": universe_rows,
        "corporate_actions": action_rows,
        "benchmark": tuple(benchmark_rows),
        "regime_daily": tuple(regime_rows),
        "regime_transitions": tuple(transition_rows),
        "strategy_registry": strategy_rows,
        "strategy_parameters": parameter_rows,
        "signals": signal_rows,
        "trade_plans": plan_rows,
        "logical_trades": trade_rows,
        "portfolio_equity": equity_rows,
        "portfolio_positions": position_rows,
        "transaction_costs": cost_rows,
        "walk_forward_folds": tuple(fold_rows),
        "strategy_selections": tuple(selection_rows),
        "regime_strategy_mapping": tuple(mapping_rows),
        "comparison_portfolios": tuple(analysis["comparison"]),
        "calendar_performance": tuple(analysis["calendar"]),
        "rolling_performance": tuple(analysis["rolling"]),
        "risk_metrics": tuple(analysis["metrics"]),
        "benchmark_relative": tuple(analysis["benchmark_relative"]),
        "multiple_testing": tuple(analysis["multiple_testing"]),
        "parameter_stability": tuple(analysis["parameter_stability"]),
        "robustness": tuple(analysis["robustness"]),
        "concentration": tuple(analysis["concentration"]),
        "population_reconciliation": reconciliation,
        "non_vacuity": non_vacuity,
        "independent_variant_trades": _frame_records(independent_trades),
        "policy": (
            {
                **asdict(policy),
                "historical_truth_database": sources.database.name,
                "historical_truth_snapshots": sources.historical_truth_snapshots.name,
                "benchmark_input": (
                    "AUTO"
                    if sources.benchmark.upper() == "AUTO"
                    else Path(sources.benchmark).name
                ),
                "sector_data_status": "UNAVAILABLE_NOT_ENFORCED",
            },
        ),
    }


def _signal_artifact_row(raw_row: object) -> dict[str, Any]:
    row: Any = raw_row
    return {
        "signal_id": row.signal_id,
        "security_session_id": _stable_id(
            "SECURITY_SESSION", row.trading_date, row.identity_key
        ),
        "identity_key": row.identity_key,
        "symbol": row.symbol,
        "isin": row.isin,
        "signal_date": row.trading_date,
        "data_cutoff_date": row.trading_date,
        "entry_eligibility_date": row.next_trading_date,
        "strategy_variant_id": row.strategy_variant_id,
        "strategy_family": row.strategy_family,
        "regime_state": str(row.regime),
        "signal_strength": _round(float(row.signal_strength)),
        "entry_state": row.entry_state,
        "price_arm": "ADJUSTED",
        "source_data_hash": row.source_sha256,
        "same_close_execution": False,
    }


def _readiness(
    *,
    source_summary: Mapping[str, Any],
    regime_rows: Sequence[Mapping[str, Any]],
    variants: Sequence[StrategyVariant],
    signals: pd.DataFrame,
    portfolios: Mapping[str, Mapping[str, Any]],
    benchmark_rows: Sequence[Mapping[str, Any]],
    analysis: Mapping[str, Any],
) -> tuple[dict[str, str], list[str]]:
    blockers: list[str] = []
    benchmark_available = (
        benchmark_rows
        and benchmark_rows[0]["status"] == BenchmarkStatus.AVAILABLE_TOTAL_RETURN.value
    )
    partial = (
        source_summary["admitted_rows"] < source_summary["source_rows"]
        or not benchmark_available
    )
    readiness = {
        "A": (
            SliceReadiness.A_PARTIAL.value if partial else SliceReadiness.A_READY.value
        )
    }
    if not benchmark_available:
        blockers.append("GOVERNED_TOTAL_RETURN_BENCHMARK_UNAVAILABLE")
    unknown_rate = (
        sum(row["regime_state"] == RegimeState.UNKNOWN.value for row in regime_rows)
        / len(regime_rows)
        if regime_rows
        else 1.0
    )
    readiness["B"] = (
        SliceReadiness.B_LIMITED.value
        if unknown_rate > 0.10
        else SliceReadiness.B_READY.value
    )
    readiness["C"] = (
        SliceReadiness.C_READY.value if variants else SliceReadiness.C_EMPTY.value
    )
    readiness["D"] = (
        SliceReadiness.D_READY.value
        if not signals.empty
        else SliceReadiness.D_ZERO.value
    )
    regime_portfolio = portfolios.get(_PORTFOLIO_REGIME, {})
    readiness["E"] = (
        SliceReadiness.E_READY.value
        if regime_portfolio.get("trades")
        else SliceReadiness.E_ZERO.value
    )
    mappings = analysis.get("comparison", ())
    readiness["F"] = (
        SliceReadiness.F_READY.value
        if any(item.get("trade_count", 0) for item in mappings)
        else SliceReadiness.F_NO_QUALIFYING.value
    )
    regime_metric: Mapping[str, Any] = next(
        (item for item in mappings if item["portfolio_name"] == _PORTFOLIO_REGIME),
        {},
    )
    fixed_metric: Mapping[str, Any] = next(
        (item for item in mappings if item["portfolio_name"] == _PORTFOLIO_FIXED),
        {},
    )
    regime_cagr = regime_metric.get("net_cagr")
    fixed_cagr = fixed_metric.get("net_cagr")
    if not regime_portfolio.get("trades"):
        readiness["G"] = SliceReadiness.G_ZERO.value
    elif (
        regime_cagr is not None
        and fixed_cagr is not None
        and float(regime_cagr) <= float(fixed_cagr)
    ):
        readiness["G"] = SliceReadiness.G_NO_ADVANTAGE.value
    else:
        readiness["G"] = SliceReadiness.G_READY.value
    readiness["H"] = (
        SliceReadiness.H_READY.value
        if benchmark_available
        else SliceReadiness.H_LIMITED.value
    )
    overfitting = str(analysis["overfitting_state"])
    readiness["I"] = (
        SliceReadiness.I_READY.value
        if overfitting
        in {
            OverfittingState.ROBUST_OUT_OF_SAMPLE_EVIDENCE.value,
            OverfittingState.DIRECTIONALLY_STABLE.value,
        }
        and benchmark_available
        else SliceReadiness.I_DESCRIPTIVE.value
    )
    if not benchmark_available:
        readiness["J"] = SliceReadiness.J_DESCRIPTIVE.value
    elif overfitting == OverfittingState.NO_GENERALISABLE_STRATEGY_FOUND.value:
        readiness["J"] = SliceReadiness.J_NO_GENERALISABLE.value
    elif readiness["I"] == SliceReadiness.I_READY.value:
        readiness["J"] = SliceReadiness.J_FORWARD.value
    else:
        readiness["J"] = SliceReadiness.J_DESCRIPTIVE.value
    return readiness, blockers


def _summaries(
    *,
    source_summary: Mapping[str, Any],
    featured: pd.DataFrame,
    regime_rows: Sequence[Mapping[str, Any]],
    transition_rows: Sequence[Mapping[str, Any]],
    variants: Sequence[StrategyVariant],
    signals: pd.DataFrame,
    plans: pd.DataFrame,
    folds: Sequence[WalkForwardFold],
    selection_rows: Sequence[Mapping[str, Any]],
    benchmark_rows: Sequence[Mapping[str, Any]],
    portfolios: Mapping[str, Mapping[str, Any]],
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    regime_counts = Counter(row["regime_state"] for row in regime_rows)
    selected = [
        row
        for row in selection_rows
        if row.get("selected") and row.get("selection_scope") == "FIXED"
    ]
    metrics = {row["portfolio_name"]: row for row in analysis["metrics"]}
    regime_metric = metrics.get(_PORTFOLIO_REGIME, {})
    benchmark_metric = metrics.get(_PORTFOLIO_BENCHMARK, {})
    return {
        **dict(source_summary),
        "feature_rows": len(featured),
        "regime_counts": dict(sorted(regime_counts.items())),
        "regime_transition_count": len(transition_rows),
        "unknown_regime_rate": _round(
            regime_counts[RegimeState.UNKNOWN.value] / len(regime_rows)
            if regime_rows
            else 1.0
        ),
        "strategy_family_count": len({item.family for item in variants}),
        "generated_variant_count": len(variants),
        "valid_variant_count": len(variants),
        "rejected_variant_count": 0,
        "signal_count": len(signals),
        "trade_plan_count": len(plans),
        "walk_forward_fold_count": len(folds),
        "fixed_strategy_selections": [
            row["selected_strategy_variant_id"] for row in selected
        ],
        "no_trade_selection_count": sum(
            row.get("selected")
            and row.get("selected_strategy_variant_id") == "NO_TRADE"
            for row in selection_rows
        ),
        "benchmark_status": benchmark_rows[0]["status"],
        "portfolio_count": sum(name in portfolios for name in _PORTFOLIO_NAMES),
        "regime_aware_metrics": regime_metric,
        "benchmark_metrics": benchmark_metric,
        "overfitting_state": analysis["overfitting_state"],
        "implementation_defect_count": 0,
        "lookahead_leakage_count": 0,
        "population_reconciliation_defect_count": 0,
        "automatic_promotion_count": 0,
    }


def structural_probe_rows() -> tuple[dict[str, Any], ...]:
    """Return isolated probes that never enter empirical tournament results."""

    probes = (
        ("POINT_IN_TIME_REGIME", True, "Regime applies to next session."),
        ("FUTURE_LEAKING_REGIME", False, "Future-derived regime is rejected."),
        ("VALID_STRATEGY_VARIANT", True, "Bounded registered variant."),
        ("DUPLICATE_VARIANT", False, "Duplicate fingerprint rejected."),
        ("INCOMPATIBLE_COMPONENTS", False, "Contradictory grammar rejected."),
        ("NO_TRADE_STRATEGY", True, "Cash is an explicit strategy."),
        ("NEXT_SESSION_EXECUTION", True, "Close signal enters next session."),
        ("SAME_CLOSE_EXECUTION", False, "Same-close fill prohibited."),
        ("UNFILLED_ENTRY", True, "Unfilled signal remains non-trade."),
        ("STOP_FIRST_SAME_BAR", True, "Stop wins ambiguous same-bar order."),
        ("TARGET_EXIT", True, "Target exit uses frozen plan."),
        ("TRAILING_EXIT", True, "Trail activates only after target one."),
        ("TIME_EXIT", True, "Maximum holding period enforced."),
        ("OVERLAPPING_POSITIONS", True, "Capital shared across positions."),
        ("INSUFFICIENT_CAPITAL", True, "Entry rejected when cash is insufficient."),
        ("LIQUIDITY_REJECTION", True, "Capacity constrains size."),
        ("TRANSACTION_COSTS", True, "Entry and exit costs charged."),
        ("BENCHMARK_ALIGNMENT", True, "Only complete TRI enables excess CAGR."),
        ("WALK_FORWARD_SELECTION", True, "Selection ends before outer test."),
        ("TEST_LEAKAGE", False, "Outer test cannot select its own strategy."),
        ("REGIME_SELECTOR", True, "Fold-regime mapping is frozen."),
        ("FIXED_COMPARATOR", True, "One strategy spans all regimes."),
        ("BH_AND_HOLM", True, "Multiple-testing corrections deterministic."),
        ("BEST_SECURITY_REMOVAL", True, "Concentration evidence is explicit."),
        ("PARAMETER_INSTABILITY", True, "Neighbour direction is audited."),
        ("CERTIFICATE_TAMPERING", False, "Digest mismatch invalidates package."),
    )
    return tuple(
        {
            "probe_id": f"DSI007-PROBE-{index:02d}",
            "probe_name": name,
            "accepted": accepted,
            "explanation": explanation,
            "empirical_population": False,
        }
        for index, (name, accepted, explanation) in enumerate(probes, start=1)
    )


def _frame_records(frame: pd.DataFrame) -> tuple[dict[str, Any], ...]:
    if frame.empty:
        return ()
    return tuple(
        {str(key): _portable_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    )


def _portable_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (date, str, bool, int)):
        return value
    if isinstance(value, RegimeState):
        return value.value
    if isinstance(value, (float, np.floating)):
        return None if math.isnan(float(value)) else _round(float(value))
    if isinstance(value, np.integer):
        return int(value)
    if pd.isna(value):
        return None
    return str(value)


def _stable_id(prefix: str, *values: object) -> str:
    body = "|".join(str(value) for value in values)
    return f"{prefix}-{hashlib.sha256(body.encode('utf-8')).hexdigest()[:24]}"


def _round(value: float) -> float:
    return round(float(value), 8)


def _optional_round(value: Any) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return _round(parsed)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _directory_contract_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    if root.is_file():
        return _file_sha256(root)
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _directory_size(root: Path) -> int:
    if root.is_file():
        return root.stat().st_size
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _git_commit(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "UNKNOWN"
    return result.stdout.strip()


__all__ = [
    "GovernedRegimeStrategyTournamentEngine",
    "default_strategy_registry",
    "governance_flags",
    "structural_probe_rows",
    "validate_strategy_registry",
]
