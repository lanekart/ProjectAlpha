"""Governed DSI-008 benchmark, attribution and mechanism research engine."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from statistics import NormalDist
from types import MappingProxyType
from typing import Any, cast

import duckdb
import numpy as np
import pandas as pd

from alpha.decision_superiority.performance_improvement_models import (
    BenchmarkKind,
    BenchmarkProvenance,
    ChallengerDefinition,
    ChallengerState,
    FinalReadiness,
    ImprovementPolicy,
    ImprovementSourcePaths,
    PerformanceImprovementError,
    PerformanceImprovementResult,
    RobustnessGrade,
)
from alpha.decision_superiority.regime_strategy_artifacts import (
    DSI007_ARTIFACTS,
    validate_regime_strategy_tournament_certificate,
)

_INCUMBENT = "DSI007_INCUMBENT"
_STANDARD = "ALPHA_STANDARD"
_HIGH_CONVICTION = "ALPHA_HIGH_CONVICTION"
_ELITE = "ALPHA_ELITE"
_TRI = "TRI_BENCHMARK"
_OUTCOME_NAMES = (
    "TARGET_BEFORE_STOP_1R",
    "TARGET_BEFORE_STOP_2R",
    "TARGET_BEFORE_STOP_3R",
    "POSITIVE_RETURN_5_SESSION",
    "POSITIVE_RETURN_10_SESSION",
    "POSITIVE_RETURN_20_SESSION",
    "POSITIVE_RETURN_60_SESSION",
    "BENCHMARK_OUTPERFORMANCE_20_SESSION",
    "BENCHMARK_OUTPERFORMANCE_60_SESSION",
    "POSITIVE_REALISED_TRADE_RETURN",
    "POSITIVE_REALISED_R",
)


def governance_flags() -> dict[str, bool]:
    """Return the immutable DSI-008 research-only boundary."""

    return {
        "THRESHOLD_CHANGE_PERMITTED": False,
        "GATE_ORDER_CHANGE_PERMITTED": False,
        "APPROVAL_POLICY_CHANGE_PERMITTED": False,
        "PORTFOLIO_POLICY_CHANGE_PERMITTED": False,
        "EXECUTION_POLICY_CHANGE_PERMITTED": False,
        "STRATEGY_AUTOMATIC_PROMOTION_ENABLED": False,
        "LIVE_STRATEGY_SELECTION_ENABLED": False,
        "LIVE_HIGH_CONVICTION_TIER_ENABLED": False,
        "LIVE_SCORING_ENABLED": False,
        "PRODUCTION_SIGNAL_PUBLICATION_ENABLED": False,
        "PRODUCTION_PORTFOLIO_INFLUENCE": False,
        "ECONOMIC_SUPERIORITY_CLAIMED": False,
        "CAUSAL_CLAIM_PERMITTED": False,
        "DEFAULT_RUNTIME_BEHAVIOUR_CHANGED": False,
        "RECOMMENDATION_INFLUENCE": False,
        "PORTFOLIO_POLICY_INFLUENCE": False,
        "EXECUTION_INFLUENCE": False,
        "LEARNING_MUTATION_ENABLED": False,
        "ACTIVE_REPLAY_INTEGRATION": False,
        "PRODUCTION_INFLUENCE": False,
    }


def default_challenger_registry() -> tuple[ChallengerDefinition, ...]:
    """Return the bounded, pre-registered one-factor challenger set."""

    unchanged = (
        "candidate_generation",
        "strategy_selection",
        "entry_price",
        "stop",
        "targets",
        "position_size",
        "cost_model",
    )
    return (
        ChallengerDefinition(
            "CH-SIGNAL-STRENGTH-070",
            "SECURITY_RANKING",
            "signal_strength",
            "GREATER_THAN_OR_EQUAL",
            0.70,
            unchanged,
            "Remove the weakest selected signals.",
            "Higher expectancy and lower drawdown.",
            "Coverage and capital utilisation may fall.",
            1,
            "Fixed before outer-test evaluation.",
        ),
        ChallengerDefinition(
            "CH-LIQUIDITY-10M",
            "LIQUIDITY_FILTER",
            "average_traded_value20",
            "GREATER_THAN_OR_EQUAL",
            10_000_000.0,
            unchanged,
            "Require stronger trading capacity.",
            "Lower execution and concentration risk.",
            "May remove profitable smaller securities.",
            1,
            "Fixed before outer-test evaluation.",
        ),
        ChallengerDefinition(
            "CH-STOP-DISTANCE-10PCT",
            "STOP_PLACEMENT",
            "stop_distance_fraction",
            "LESS_THAN_OR_EQUAL",
            0.10,
            unchanged,
            "Avoid entries with unusually wide initial risk.",
            "Lower loss magnitude and capital at risk.",
            "May reject volatile winners.",
            1,
            "Fixed before outer-test evaluation.",
        ),
        ChallengerDefinition(
            "CH-REWARD-RISK-2R",
            "TARGET_SELECTION",
            "reward_risk_target_1",
            "GREATER_THAN_OR_EQUAL",
            2.0,
            unchanged,
            "Require at least two units of planned reward per unit risk.",
            "Improve payoff quality.",
            "Nominal targets may not be attainable.",
            1,
            "Fixed before outer-test evaluation.",
        ),
        ChallengerDefinition(
            "CH-SKIP-UNKNOWN-REGIME",
            "REGIME_CLASSIFICATION",
            "regime_state",
            "NOT_EQUAL",
            "UNKNOWN",
            unchanged,
            "Avoid signals without a governed market-state classification.",
            "Reduce model-state uncertainty.",
            "May suppress valid early-history opportunities.",
            1,
            "Fixed before outer-test evaluation.",
        ),
        ChallengerDefinition(
            "CH-HOLDING-LIMIT-30",
            "TIME_EXIT",
            "maximum_holding_sessions",
            "LESS_THAN_OR_EQUAL",
            30.0,
            unchanged,
            "Prefer mechanisms with faster capital recycling.",
            "Improve capital utilisation.",
            "May remove slower trend winners.",
            1,
            "Fixed before outer-test evaluation.",
        ),
    )


def validate_challenger_registry(
    challengers: Sequence[ChallengerDefinition],
    *,
    maximum_challengers: int,
) -> None:
    """Fail closed on empty, duplicate, or unbounded challenger search."""

    if not challengers:
        raise PerformanceImprovementError("EMPTY_CHALLENGER_REGISTRY")
    if len(challengers) > maximum_challengers:
        raise PerformanceImprovementError("UNBOUNDED_MECHANISM_SEARCH")
    identifiers = [item.challenger_id for item in challengers]
    if len(identifiers) != len(set(identifiers)):
        raise PerformanceImprovementError("DUPLICATE_CHALLENGER_ID")
    fingerprints = [
        (item.parent_mechanism, item.changed_field, item.operator, item.value)
        for item in challengers
    ]
    if len(fingerprints) != len(set(fingerprints)):
        raise PerformanceImprovementError("DUPLICATE_CHALLENGER_CHANGE")


class GovernedPerformanceImprovementEngine:
    """Run DSI-008 A-I without influencing Alpha runtime behaviour."""

    def run(
        self,
        *,
        sources: ImprovementSourcePaths,
        policy: ImprovementPolicy = ImprovementPolicy(),
        challengers: Sequence[ChallengerDefinition] | None = None,
    ) -> PerformanceImprovementResult:
        """Validate sources and execute the governed research workflow."""

        registry = tuple(challengers or default_challenger_registry())
        validate_challenger_registry(
            registry,
            maximum_challengers=policy.maximum_challengers,
        )
        dsi007 = validate_regime_strategy_tournament_certificate(
            sources.dsi007_certificate,
            require_ready=False,
            database=sources.database,
        )
        source_dir = sources.dsi007_certificate.parent
        ledgers = _load_dsi007_ledgers(source_dir)
        benchmark, provenance, tri_contract = load_governed_tri(sources.tri_benchmark)
        _validate_tri_calendar(
            benchmark,
            ledgers["equity"],
            tolerance=policy.benchmark_calendar_tolerance,
        )

        source_rows = _source_contract_rows(
            sources=sources,
            dsi007=dsi007,
            provenance=provenance,
        )
        tri_rows = _tri_daily_rows(benchmark, provenance)
        attribution, excursions, wealth, bottlenecks = _baseline_attribution(
            ledgers=ledgers,
            benchmark=benchmark,
            database=sources.database,
        )
        outcomes = _signal_outcomes(
            ledgers=ledgers,
            benchmark=benchmark,
            database=sources.database,
        )
        calibration = _confidence_calibration(outcomes, policy=policy)
        registry_rows = [_challenger_row(item) for item in registry]
        change_rows = _challenger_change_rows(registry)
        fold_rows, challenger_rows = _evaluate_challengers(
            outcomes=outcomes,
            registry=registry,
            folds=ledgers["folds"],
            policy=policy,
        )
        tier_definitions, tier_outcomes = _evaluate_tiers(
            outcomes=outcomes,
            folds=ledgers["folds"],
            policy=policy,
        )
        accepted = _accepted_challenger(challenger_rows)
        portfolio_rows, equity_rows, tradeoff_rows = _portfolio_comparison(
            ledgers=ledgers,
            benchmark=benchmark,
            outcomes=outcomes,
            tier_outcomes=tier_outcomes,
            accepted_challenger=accepted,
            incumbent_metrics=cast(
                Mapping[str, Any],
                dsi007["portfolio_summary"],
            ),
        )
        year_rows, rolling_rows = _calendar_and_rolling(pd.DataFrame(equity_rows))
        multiple_rows = _multiple_testing(challenger_rows)
        robustness_rows = _robustness(
            outcomes=outcomes,
            accepted_challenger=accepted,
        )
        concentration_rows = _concentration(
            outcomes=outcomes,
            tier_outcomes=tier_outcomes,
        )
        population_rows = _population_reconciliation(
            ledgers=ledgers,
            outcomes=outcomes,
        )
        non_vacuity_rows = _non_vacuity(
            benchmark=benchmark,
            outcomes=outcomes,
            challengers=registry_rows,
        )
        readiness, blockers, grade = _readiness(
            provenance=provenance,
            attribution=attribution,
            outcomes=outcomes,
            challenger_results=challenger_rows,
            tier_outcomes=tier_outcomes,
            portfolio_rows=portfolio_rows,
            multiple_rows=multiple_rows,
            policy=policy,
        )
        summaries = _summaries(
            dsi007=dsi007,
            provenance=provenance,
            tri_contract=tri_contract,
            attribution=attribution,
            bottlenecks=bottlenecks,
            challenger_rows=challenger_rows,
            tier_outcomes=tier_outcomes,
            portfolio_rows=portfolio_rows,
            multiple_rows=multiple_rows,
            robustness_rows=robustness_rows,
            grade=grade,
        )
        rows: dict[str, tuple[dict[str, Any], ...]] = {
            "source_contract": tuple(source_rows),
            "tri_contract": (tri_contract,),
            "tri_daily": tuple(tri_rows),
            "baseline_attribution": tuple(attribution),
            "trade_excursions": tuple(excursions),
            "wealth_contribution": tuple(wealth),
            "mechanism_bottlenecks": tuple(bottlenecks),
            "signal_outcomes": tuple(outcomes),
            "confidence_calibration": tuple(calibration),
            "challenger_registry": tuple(registry_rows),
            "challenger_changes": tuple(change_rows),
            "champion_challenger_folds": tuple(fold_rows),
            "challenger_results": tuple(challenger_rows),
            "tier_definitions": tuple(tier_definitions),
            "tier_outcomes": tuple(tier_outcomes),
            "portfolio_comparison": tuple(portfolio_rows),
            "daily_equity": tuple(equity_rows),
            "accuracy_wealth_tradeoff": tuple(tradeoff_rows),
            "calendar_year": tuple(year_rows),
            "rolling_relative": tuple(rolling_rows),
            "multiple_testing": tuple(multiple_rows),
            "robustness": tuple(robustness_rows),
            "concentration": tuple(concentration_rows),
            "population_reconciliation": tuple(population_rows),
            "non_vacuity": tuple(non_vacuity_rows),
        }
        return PerformanceImprovementResult(
            source_commit=_source_commit(sources.project_root),
            readiness=MappingProxyType(readiness),
            blockers=tuple(blockers),
            rows=MappingProxyType(rows),
            summaries=MappingProxyType(summaries),
            governance=MappingProxyType(governance_flags()),
        )


def load_governed_tri(
    benchmark_path: Path,
) -> tuple[pd.DataFrame, BenchmarkProvenance, dict[str, Any]]:
    """Load an official benchmark and fail closed on weak provenance."""

    if not benchmark_path.is_file():
        raise PerformanceImprovementError("TRI_SOURCE_UNAVAILABLE")
    provenance_path = benchmark_path.with_suffix(
        benchmark_path.suffix + ".provenance.json"
    )
    if not provenance_path.is_file():
        raise PerformanceImprovementError("BENCHMARK_PROVENANCE_DEFECT")
    try:
        raw_provenance = json.loads(provenance_path.read_text("utf-8"))
        provenance = BenchmarkProvenance(
            index_identifier=str(raw_provenance["index_identifier"]),
            index_name=str(raw_provenance["index_name"]),
            benchmark_kind=BenchmarkKind(str(raw_provenance["benchmark_kind"])),
            source=str(raw_provenance["source"]),
            source_version=str(raw_provenance["source_version"]),
            currency=str(raw_provenance["currency"]),
            dividend_treatment=str(raw_provenance["dividend_treatment"]),
            adjustment_treatment=str(raw_provenance["adjustment_treatment"]),
            raw_source_sha256=str(raw_provenance["raw_source_sha256"]),
            acquired_at=str(raw_provenance["acquired_at"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PerformanceImprovementError("BENCHMARK_PROVENANCE_DEFECT") from exc
    actual_hash = _sha256(benchmark_path)
    if actual_hash != provenance.raw_source_sha256:
        raise PerformanceImprovementError("BENCHMARK_SOURCE_HASH_MISMATCH")
    if provenance.benchmark_kind is BenchmarkKind.PRICE_INDEX:
        raise PerformanceImprovementError("PRICE_INDEX_DIAGNOSTIC_ONLY")
    frame = pd.read_csv(benchmark_path)
    aliases = {
        "Date": "date",
        "Index Name": "index_name",
        "TotalReturnsIndex": "value",
        "total_return_index": "value",
    }
    frame = frame.rename(columns=aliases)
    required = {"date", "value"}
    if not required.issubset(frame.columns):
        raise PerformanceImprovementError("TRI_REQUIRED_FIELDS_MISSING")
    frame = frame.loc[:, ["date", "value"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    if frame.isna().any().any():
        raise PerformanceImprovementError("TRI_INVALID_VALUE")
    frame["date"] = frame["date"].dt.date
    frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
    duplicate_count = int(frame["date"].duplicated().sum())
    nonpositive_count = int((frame["value"] <= 0).sum())
    if duplicate_count:
        raise PerformanceImprovementError("TRI_DUPLICATE_DATE")
    if nonpositive_count:
        raise PerformanceImprovementError("TRI_NONPOSITIVE_VALUE")
    returns = frame["value"].pct_change()
    discontinuities = int((returns.abs() > 0.30).sum())
    if discontinuities:
        raise PerformanceImprovementError("TRI_DISCONTINUITY")
    contract = {
        "index_identifier": provenance.index_identifier,
        "index_name": provenance.index_name,
        "benchmark_kind": provenance.benchmark_kind.value,
        "start_date": frame["date"].iloc[0],
        "end_date": frame["date"].iloc[-1],
        "observed_sessions": len(frame),
        "duplicate_dates": duplicate_count,
        "nonpositive_values": nonpositive_count,
        "discontinuities": discontinuities,
        "source": provenance.source,
        "source_version": provenance.source_version,
        "source_sha256": actual_hash,
        "currency": provenance.currency,
        "dividend_treatment": provenance.dividend_treatment,
        "adjustment_treatment": provenance.adjustment_treatment,
        "return_calculation": "value_t/value_t_minus_1-1",
        "used_for_superiority": True,
    }
    return frame, provenance, contract


def _load_dsi007_ledgers(source_dir: Path) -> dict[str, pd.DataFrame]:
    mapping = {
        "signals": "signals",
        "plans": "trade_plans",
        "trades": "logical_trades",
        "equity": "portfolio_equity",
        "costs": "transaction_costs",
        "folds": "walk_forward_folds",
        "regimes": "regime_daily",
    }
    frames: dict[str, pd.DataFrame] = {}
    for key, artifact_key in mapping.items():
        path = source_dir / DSI007_ARTIFACTS[artifact_key]
        if not path.is_file():
            raise PerformanceImprovementError(
                f"DSI007_SUPPORT_ARTIFACT_MISSING:{path.name}"
            )
        frames[key] = pd.read_csv(path)
    for key in ("signals", "plans", "trades"):
        date_columns = [
            name
            for name in frames[key].columns
            if name.endswith("_date") or name in {"signal_date"}
        ]
        for name in date_columns:
            frames[key][name] = pd.to_datetime(
                frames[key][name], errors="coerce"
            ).dt.date
    frames["equity"]["observed_on"] = pd.to_datetime(
        frames["equity"]["observed_on"]
    ).dt.date
    for name in (
        "train_start",
        "train_end",
        "validation_start",
        "validation_end",
        "test_start",
        "test_end",
    ):
        frames["folds"][name] = pd.to_datetime(
            frames["folds"][name],
            errors="raise",
        ).dt.date
    return frames


def _validate_tri_calendar(
    benchmark: pd.DataFrame,
    equity: pd.DataFrame,
    *,
    tolerance: float,
) -> None:
    incumbent = equity.loc[equity["portfolio_name"] == "REGIME_AWARE_SELECTED"]
    expected = set(incumbent["observed_on"])
    observed = set(benchmark["date"])
    if not expected:
        raise PerformanceImprovementError("DSI007_EQUITY_EMPTY")
    missing = expected - observed
    if len(missing) / len(expected) > tolerance:
        raise PerformanceImprovementError("BENCHMARK_CALENDAR_DEFECT")


def _source_contract_rows(
    *,
    sources: ImprovementSourcePaths,
    dsi007: Mapping[str, Any],
    provenance: BenchmarkProvenance,
) -> list[dict[str, Any]]:
    return [
        {
            "source_role": "DSI007_CERTIFICATE",
            "contract_version": dsi007["contract_version"],
            "sha256": _sha256(sources.dsi007_certificate),
            "used_for_selection": False,
            "used_for_outer_evaluation": True,
        },
        {
            "source_role": "TRI_BENCHMARK",
            "contract_version": provenance.source_version,
            "sha256": _sha256(sources.tri_benchmark),
            "used_for_selection": False,
            "used_for_outer_evaluation": True,
        },
    ]


def _tri_daily_rows(
    benchmark: pd.DataFrame,
    provenance: BenchmarkProvenance,
) -> list[dict[str, Any]]:
    returns = benchmark["value"].pct_change()
    return [
        {
            "benchmark_session_id": _stable_id(
                "TRI", provenance.index_identifier, row.date
            ),
            "index_identifier": provenance.index_identifier,
            "index_name": provenance.index_name,
            "benchmark_kind": provenance.benchmark_kind.value,
            "observed_on": row.date,
            "value": round(float(row.value), 8),
            "daily_return": (
                None
                if pd.isna(returns.iloc[index])
                else round(float(returns.iloc[index]), 10)
            ),
            "source": provenance.source,
            "source_version": provenance.source_version,
            "source_sha256": provenance.raw_source_sha256,
            "currency": provenance.currency,
            "dividend_treatment": provenance.dividend_treatment,
            "adjustment_treatment": provenance.adjustment_treatment,
            "missing_session_state": "OBSERVED",
        }
        for index, row in enumerate(
            cast(Iterable[Any], benchmark.itertuples(index=False))
        )
    ]


def _baseline_attribution(
    *,
    ledgers: Mapping[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    database: Path | None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    trades = (
        ledgers["trades"]
        .loc[ledgers["trades"]["portfolio_name"] == "REGIME_AWARE_SELECTED"]
        .copy()
    )
    if trades.empty:
        raise PerformanceImprovementError("BASELINE_TRADE_ATTRIBUTION_DEFECT")
    plans = ledgers["plans"]
    plan_cols = [
        "signal_id",
        "identity_key",
        "signal_date",
        "strategy_variant_id",
        "initial_stop",
        "target_1",
        "target_2",
        "target_3",
        "maximum_holding_sessions",
        "average_traded_value20",
        "reward_risk_target_1",
    ]
    signals = ledgers["signals"][
        [
            "signal_id",
            "identity_key",
            "signal_date",
            "strategy_variant_id",
            "signal_strength",
            "strategy_family",
        ]
    ]
    plan_signal = plans[plan_cols].merge(
        signals,
        on=[
            "signal_id",
            "identity_key",
            "signal_date",
            "strategy_variant_id",
        ],
        how="left",
        validate="one_to_one",
    )
    trades = trades.merge(
        plan_signal,
        on=["identity_key", "signal_date", "strategy_variant_id"],
        how="left",
        validate="many_to_one",
    )
    market = _load_market_slice(database, trades)
    benchmark_index = benchmark.set_index("date")["value"]
    excursion_rows: list[dict[str, Any]] = []
    for trade in cast(Iterable[Any], trades.itertuples(index=False)):
        bars = market.get(str(trade.identity_key), pd.DataFrame())
        active = bars.loc[
            (bars["trading_date"] >= trade.entry_date)
            & (bars["trading_date"] <= trade.exit_date)
        ]
        entry = float(trade.entry_price)
        risk = max(entry - float(trade.initial_stop), 0.0)
        if active.empty:
            mfe = mae = None
        else:
            mfe = float(active["high"].max() / entry - 1.0)
            mae = float(active["low"].min() / entry - 1.0)
        benchmark_return = _period_return(
            benchmark_index, trade.entry_date, trade.exit_date
        )
        excursion_rows.append(
            {
                "logical_trade_id": trade.logical_trade_id,
                "symbol": trade.symbol,
                "walk_forward_fold_id": trade.walk_forward_fold_id,
                "strategy_variant_id": trade.strategy_variant_id,
                "strategy_family": trade.strategy_family,
                "regime_at_signal": trade.regime_state,
                "regime_at_entry": trade.regime_state,
                "regime_at_exit": trade.regime_state,
                "entry_date": trade.entry_date,
                "exit_date": trade.exit_date,
                "realised_return": round(float(trade.net_return), 10),
                "realised_r": (
                    None
                    if risk <= 0
                    else round(
                        (float(trade.exit_price) - entry) / risk,
                        8,
                    )
                ),
                "mfe": None if mfe is None else round(mfe, 10),
                "mae": None if mae is None else round(mae, 10),
                "entry_delay_sessions": _business_days(
                    trade.signal_date, trade.entry_date
                ),
                "stop_distance_fraction": (
                    None if entry <= 0 else round(risk / entry, 10)
                ),
                "target_1_distance_fraction": _distance(entry, trade.target_1),
                "target_2_distance_fraction": _distance(entry, trade.target_2),
                "target_3_distance_fraction": _distance(entry, trade.target_3),
                "holding_sessions": int(trade.holding_sessions),
                "exit_reason": trade.exit_reason,
                "benchmark_holding_return": benchmark_return,
                "excess_holding_return": (
                    None
                    if benchmark_return is None
                    else round(float(trade.net_return) - benchmark_return, 10)
                ),
                "costs": round(float(trade.costs), 8),
                "net_pnl": round(float(trade.net_pnl), 8),
                "signal_strength": _optional_float(trade.signal_strength),
                "average_traded_value20": _optional_float(trade.average_traded_value20),
                "reward_risk_target_1": _optional_float(trade.reward_risk_target_1),
                "maximum_holding_sessions": _optional_int(
                    trade.maximum_holding_sessions
                ),
            }
        )
    excursions = pd.DataFrame(excursion_rows)
    dimensions = {
        "FOLD": "walk_forward_fold_id",
        "YEAR": "exit_date",
        "REGIME": "regime_at_signal",
        "STRATEGY_VARIANT": "strategy_variant_id",
        "STRATEGY_FAMILY": "strategy_family",
        "SECURITY": "symbol",
        "EXIT_MECHANISM": "exit_reason",
        "HOLDING_PERIOD": "holding_sessions",
    }
    attribution: list[dict[str, Any]] = []
    for dimension, column in dimensions.items():
        temp = excursions.copy()
        if dimension == "YEAR":
            temp["_group"] = temp[column].map(lambda item: item.year)
        elif dimension == "HOLDING_PERIOD":
            temp["_group"] = pd.cut(
                temp[column],
                bins=[-1, 5, 10, 20, 40, math.inf],
                labels=["0-5", "6-10", "11-20", "21-40", "41+"],
            ).astype(str)
        else:
            temp["_group"] = temp[column].astype(str)
        for group, rows in temp.groupby("_group", sort=True):
            attribution.append(
                {
                    "dimension": dimension,
                    "group": group,
                    "trade_count": len(rows),
                    "wins": int((rows["realised_return"] > 0).sum()),
                    "losses": int((rows["realised_return"] < 0).sum()),
                    "mean_return": _mean(rows["realised_return"]),
                    "median_return": _median(rows["realised_return"]),
                    "net_pnl": round(float(rows["net_pnl"].sum()), 8),
                    "costs": round(float(rows["costs"].sum()), 8),
                    "benchmark_mean_return": _mean(rows["benchmark_holding_return"]),
                    "excess_mean_return": _mean(rows["excess_holding_return"]),
                }
            )
    ranked = excursions.sort_values(
        ["net_pnl", "logical_trade_id"], ascending=[False, True]
    )
    total_net = float(excursions["net_pnl"].sum())
    wealth_rows = [
        {
            "rank": index,
            "logical_trade_id": row.logical_trade_id,
            "symbol": row.symbol,
            "exit_date": row.exit_date,
            "net_pnl": row.net_pnl,
            "contribution_fraction": (
                None if total_net == 0 else round(row.net_pnl / total_net, 10)
            ),
            "cumulative_net_pnl": round(float(ranked.head(index)["net_pnl"].sum()), 8),
        }
        for index, row in enumerate(
            cast(Iterable[Any], ranked.itertuples(index=False)),
            start=1,
        )
    ]
    bottlenecks = _mechanism_bottlenecks(excursions)
    return attribution, excursion_rows, wealth_rows, bottlenecks


def _mechanism_bottlenecks(
    excursions: pd.DataFrame,
) -> list[dict[str, Any]]:
    losses = excursions.loc[excursions["net_pnl"] < 0]
    mapping = {
        "STOP_PLACEMENT": losses.loc[losses["exit_reason"] == "STOP"],
        "TIME_EXIT": losses.loc[losses["exit_reason"] == "TIME_EXIT"],
        "ENTRY_TIMING": losses.loc[losses["entry_delay_sessions"] > 0],
        "TRANSACTION_COST": excursions,
        "INSUFFICIENT_SAMPLE": excursions,
    }
    rows: list[dict[str, Any]] = []
    for mechanism, frame in mapping.items():
        if mechanism == "TRANSACTION_COST":
            loss = float(frame["costs"].sum())
            evidence_count = len(frame)
        elif mechanism == "INSUFFICIENT_SAMPLE":
            loss = 0.0
            evidence_count = len(frame)
        else:
            loss = abs(float(frame["net_pnl"].sum()))
            evidence_count = len(frame)
        rows.append(
            {
                "mechanism": mechanism,
                "evidence_count": evidence_count,
                "attributed_loss": round(loss, 8),
                "severity_rank": 0,
                "classification_basis": ("Executed DSI-007 out-of-sample trades only"),
            }
        )
    rows.sort(key=lambda row: (-float(row["attributed_loss"]), row["mechanism"]))
    for rank, row in enumerate(rows, start=1):
        row["severity_rank"] = rank
    return rows


def _signal_outcomes(
    *,
    ledgers: Mapping[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    database: Path | None,
) -> list[dict[str, Any]]:
    signals = ledgers["signals"].merge(
        ledgers["plans"],
        on=[
            "signal_id",
            "identity_key",
            "symbol",
            "strategy_variant_id",
            "signal_date",
            "entry_eligibility_date",
            "same_close_execution",
        ],
        how="inner",
        suffixes=("", "_plan"),
        validate="one_to_one",
    )
    trades = ledgers["trades"].loc[
        ledgers["trades"]["portfolio_name"] == "REGIME_AWARE_SELECTED"
    ]
    trade_lookup = {
        (
            str(row.identity_key),
            row.signal_date,
            str(row.strategy_variant_id),
        ): row
        for row in cast(Iterable[Any], trades.itertuples(index=False))
    }
    market = _load_market_slice(database, signals)
    market_arrays = {
        identity: (
            np.array(frame["trading_date"], dtype="datetime64[D]"),
            frame["high"].to_numpy(dtype=float),
            frame["low"].to_numpy(dtype=float),
            frame["close"].to_numpy(dtype=float),
        )
        for identity, frame in market.items()
    }
    benchmark_dates = np.array(benchmark["date"], dtype="datetime64[D]")
    benchmark_values = benchmark["value"].to_numpy(dtype=float)
    fold_rows = cast(
        list[dict[str, Any]],
        ledgers["folds"].to_dict("records"),
    )
    rows: list[dict[str, Any]] = []
    for signal in cast(Iterable[Any], signals.itertuples(index=False)):
        fold_id = _fold_for_date(signal.signal_date, fold_rows)
        trade = trade_lookup.get(
            (
                str(signal.identity_key),
                signal.signal_date,
                str(signal.strategy_variant_id),
            )
        )
        future_dates = np.array([], dtype="datetime64[D]")
        future_high = np.array([], dtype=float)
        future_low = np.array([], dtype=float)
        future_close = np.array([], dtype=float)
        arrays = market_arrays.get(str(signal.identity_key))
        if arrays is not None:
            dates, high, low, close = arrays
            start_index = int(
                np.searchsorted(
                    dates,
                    np.datetime64(signal.entry_eligibility_date),
                    side="left",
                )
            )
            end_index = min(start_index + 61, len(dates))
            future_dates = dates[start_index:end_index]
            future_high = high[start_index:end_index]
            future_low = low[start_index:end_index]
            future_close = close[start_index:end_index]
        entry = float(signal.entry_price)
        stop = float(signal.initial_stop)
        risk = entry - stop
        outcome: dict[str, Any] = {
            "signal_id": signal.signal_id,
            "identity_key": signal.identity_key,
            "symbol": signal.symbol,
            "signal_date": signal.signal_date,
            "entry_eligibility_date": signal.entry_eligibility_date,
            "walk_forward_fold_id": fold_id,
            "strategy_variant_id": signal.strategy_variant_id,
            "strategy_family": signal.strategy_family,
            "regime_state": signal.regime_state,
            "signal_strength": _optional_float(signal.signal_strength),
            "setup_quality": None,
            "relative_strength": None,
            "trend_quality": None,
            "breakout_quality": None,
            "volume_state": None,
            "retracement_state": None,
            "regime_confidence": None,
            "strategy_validation_score": None,
            "liquidity_quality": _optional_float(signal.average_traded_value20),
            "expected_reward_risk": _optional_float(signal.reward_risk_target_1),
            "historical_strategy_regime_performance": None,
            "entry_state": signal.entry_state,
            "entry_price": round(entry, 8),
            "initial_stop": round(stop, 8),
            "target_1": _optional_float(signal.target_1),
            "target_2": _optional_float(signal.target_2),
            "target_3": _optional_float(signal.target_3),
            "stop_distance_fraction": (
                None if entry <= 0 else round(max(risk, 0) / entry, 10)
            ),
            "average_traded_value20": _optional_float(signal.average_traded_value20),
            "reward_risk_target_1": _optional_float(signal.reward_risk_target_1),
            "maximum_holding_sessions": _optional_int(signal.maximum_holding_sessions),
            "entered": trade is not None,
            "completed": trade is not None,
            "realised_return": (
                None if trade is None else round(float(trade.net_return), 10)
            ),
            "realised_r": (
                None
                if trade is None or risk <= 0
                else round(
                    (float(trade.exit_price) - entry) / risk,
                    8,
                )
            ),
            "net_pnl": (None if trade is None else round(float(trade.net_pnl), 8)),
            "costs": (None if trade is None else round(float(trade.costs), 8)),
            "exit_date": None if trade is None else trade.exit_date,
            "exit_reason": None if trade is None else trade.exit_reason,
        }
        for name in _OUTCOME_NAMES:
            outcome[name] = None
        if len(future_dates) and risk > 0:
            hit_order = _target_stop_order_arrays(
                dates=future_dates,
                high=future_high,
                low=future_low,
                stop=stop,
                targets=(
                    float(signal.target_1),
                    float(signal.target_2),
                    float(signal.target_3),
                ),
            )
            for number in (1, 2, 3):
                outcome[f"TARGET_BEFORE_STOP_{number}R"] = hit_order[number]
            for horizon in (5, 10, 20, 60):
                outcome[f"POSITIVE_RETURN_{horizon}_SESSION"] = _forward_positive_array(
                    future_close,
                    entry,
                    horizon,
                )
            for horizon in (20, 60):
                stock_return = _forward_return_array(
                    future_close,
                    entry,
                    horizon,
                )
                benchmark_return = _forward_benchmark_return_arrays(
                    benchmark_dates,
                    benchmark_values,
                    signal.entry_eligibility_date,
                    horizon,
                )
                outcome[f"BENCHMARK_OUTPERFORMANCE_{horizon}_SESSION"] = (
                    None
                    if stock_return is None or benchmark_return is None
                    else stock_return > benchmark_return
                )
        if trade is not None:
            outcome["POSITIVE_REALISED_TRADE_RETURN"] = float(trade.net_return) > 0
            outcome["POSITIVE_REALISED_R"] = (
                outcome["realised_r"] is not None and float(outcome["realised_r"]) > 0
            )
        rows.append(outcome)
    return rows


def _confidence_calibration(
    outcomes: Sequence[dict[str, Any]],
    *,
    policy: ImprovementPolicy,
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(outcomes)
    completed = frame.loc[frame["POSITIVE_REALISED_TRADE_RETURN"].notna()].copy()
    if completed.empty:
        return []
    completed["confidence_bucket"] = pd.cut(
        completed["signal_strength"],
        bins=[-math.inf, 0.60, 0.70, 0.80, 0.90, math.inf],
        labels=["<=60", "60-70", "70-80", "80-90", ">90"],
        right=False,
    ).astype(str)
    rows: list[dict[str, Any]] = []
    for bucket, group in completed.groupby("confidence_bucket", sort=True):
        success = group["POSITIVE_REALISED_TRADE_RETURN"].astype(bool)
        wins = int(success.sum())
        count = len(group)
        low, high = wilson_interval(
            wins,
            count,
            confidence_level=policy.confidence_level,
        )
        predicted = _mean(group["signal_strength"])
        observed = wins / count
        rows.append(
            {
                "calibration_method": "MONOTONIC_BUCKET_DIAGNOSTIC",
                "confidence_bucket": bucket,
                "candidate_count": int(
                    (
                        frame["signal_strength"].between(
                            float(group["signal_strength"].min()),
                            float(group["signal_strength"].max()),
                        )
                    ).sum()
                ),
                "entered_count": count,
                "completed_count": count,
                "win_count": wins,
                "observed_accuracy": round(observed, 10),
                "mean_input_score": predicted,
                "calibration_gap": (
                    None if predicted is None else round(observed - predicted, 10)
                ),
                "mean_return": _mean(group["realised_return"]),
                "median_return": _median(group["realised_return"]),
                "expectancy": _mean(group["realised_return"]),
                "average_winner": _mean(
                    group.loc[group["realised_return"] > 0, "realised_return"]
                ),
                "average_loser": _mean(
                    group.loc[group["realised_return"] < 0, "realised_return"]
                ),
                "payoff_ratio": _payoff_ratio(group["realised_return"]),
                "wilson_lower": round(low, 10),
                "wilson_upper": round(high, 10),
                "fit_population": "COMPLETED_OUTER_FOLD_TRADES",
                "outer_test_used_for_fit": False,
                "predictive_use": False,
            }
        )
    return rows


def wilson_interval(
    wins: int,
    count: int,
    *,
    confidence_level: float = 0.95,
) -> tuple[float, float]:
    """Return a deterministic Wilson score interval."""

    if count <= 0:
        return 0.0, 1.0
    z = NormalDist().inv_cdf(1 - (1 - confidence_level) / 2)
    proportion = wins / count
    denominator = 1 + z * z / count
    centre = proportion + z * z / (2 * count)
    spread = z * math.sqrt(
        proportion * (1 - proportion) / count + z * z / (4 * count * count)
    )
    return (
        max(0.0, (centre - spread) / denominator),
        min(1.0, (centre + spread) / denominator),
    )


def _challenger_row(item: ChallengerDefinition) -> dict[str, Any]:
    row = asdict(item)
    row["unchanged_fields"] = "|".join(item.unchanged_fields)
    row["valid_regimes"] = "|".join(item.valid_regimes)
    row["invalid_combinations"] = "|".join(item.invalid_combinations)
    row["pre_registered"] = True
    row["production_influence"] = False
    return row


def _challenger_change_rows(
    registry: Sequence[ChallengerDefinition],
) -> list[dict[str, Any]]:
    return [
        {
            "challenger_id": item.challenger_id,
            "change_sequence": 1,
            "field": item.changed_field,
            "operator": item.operator,
            "value": item.value,
            "one_factor": True,
            "outer_test_result_used_to_define": False,
        }
        for item in registry
    ]


def _evaluate_challengers(
    *,
    outcomes: Sequence[dict[str, Any]],
    registry: Sequence[ChallengerDefinition],
    folds: pd.DataFrame,
    policy: ImprovementPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    frame = pd.DataFrame(outcomes)
    completed = frame.loc[frame["POSITIVE_REALISED_TRADE_RETURN"].notna()].copy()
    fold_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    for challenger in registry:
        fold_deltas: list[float] = []
        fold_trade_counts: list[int] = []
        for fold in cast(Iterable[Any], folds.itertuples(index=False)):
            fold_frame = completed.loc[
                completed["walk_forward_fold_id"] == fold.walk_forward_fold_id
            ]
            selected = _apply_challenger(fold_frame, challenger)
            incumbent_return = _mean(fold_frame["realised_return"])
            challenger_return = _mean(selected["realised_return"])
            delta = (
                None
                if incumbent_return is None or challenger_return is None
                else challenger_return - incumbent_return
            )
            if delta is not None:
                fold_deltas.append(delta)
            fold_trade_counts.append(len(selected))
            fold_rows.append(
                {
                    "challenger_id": challenger.challenger_id,
                    "walk_forward_fold_id": fold.walk_forward_fold_id,
                    "selection_data_end": fold.validation_end,
                    "outer_test_start": fold.test_start,
                    "outer_test_end": fold.test_end,
                    "incumbent_trade_count": len(fold_frame),
                    "challenger_trade_count": len(selected),
                    "incumbent_expectancy": incumbent_return,
                    "challenger_expectancy": challenger_return,
                    "expectancy_delta": delta,
                    "incumbent_win_rate": _boolean_mean(
                        fold_frame["POSITIVE_REALISED_TRADE_RETURN"]
                    ),
                    "challenger_win_rate": _boolean_mean(
                        selected["POSITIVE_REALISED_TRADE_RETURN"]
                    ),
                    "outer_test_used_for_selection": False,
                    "parameters_frozen_before_outer_test": True,
                }
            )
        all_selected = _apply_challenger(completed, challenger)
        incumbent_expectancy = _mean(completed["realised_return"])
        challenger_expectancy = _mean(all_selected["realised_return"])
        positive_folds = sum(delta > 0 for delta in fold_deltas)
        negative_folds = sum(delta < 0 for delta in fold_deltas)
        if len(all_selected) < policy.minimum_fold_trades * 2:
            state = ChallengerState.INSUFFICIENT_SAMPLE
        elif not fold_deltas or positive_folds <= negative_folds:
            state = ChallengerState.REJECTED
        elif (
            challenger_expectancy is not None
            and incumbent_expectancy is not None
            and challenger_expectancy > incumbent_expectancy
        ):
            state = ChallengerState.DESCRIPTIVELY_BETTER
        else:
            state = ChallengerState.REJECTED
        result_rows.append(
            {
                "challenger_id": challenger.challenger_id,
                "state": state.value,
                "completed_trade_count": len(all_selected),
                "incumbent_expectancy": incumbent_expectancy,
                "challenger_expectancy": challenger_expectancy,
                "expectancy_delta": (
                    None
                    if incumbent_expectancy is None or challenger_expectancy is None
                    else round(challenger_expectancy - incumbent_expectancy, 10)
                ),
                "challenger_win_rate": _boolean_mean(
                    all_selected["POSITIVE_REALISED_TRADE_RETURN"]
                ),
                "positive_fold_count": positive_folds,
                "negative_fold_count": negative_folds,
                "minimum_fold_trade_count": min(fold_trade_counts, default=0),
                "median_fold_improvement": _median(pd.Series(fold_deltas, dtype=float)),
                "outer_test_used_for_selection": False,
                "fresh_2026_holdout_available": False,
                "automatic_acceptance": False,
            }
        )
    return fold_rows, result_rows


def _apply_challenger(
    frame: pd.DataFrame,
    challenger: ChallengerDefinition,
) -> pd.DataFrame:
    if frame.empty or challenger.changed_field not in frame.columns:
        return frame.iloc[0:0]
    series = frame[challenger.changed_field]
    value = challenger.value
    if challenger.operator == "GREATER_THAN_OR_EQUAL":
        mask = pd.to_numeric(series, errors="coerce") >= float(value)
    elif challenger.operator == "LESS_THAN_OR_EQUAL":
        mask = pd.to_numeric(series, errors="coerce") <= float(value)
    elif challenger.operator == "NOT_EQUAL":
        mask = series.astype(str) != str(value)
    else:
        raise PerformanceImprovementError("INVALID_CHALLENGER_OPERATOR")
    return frame.loc[mask.fillna(False)].copy()


def _evaluate_tiers(
    *,
    outcomes: Sequence[dict[str, Any]],
    folds: pd.DataFrame,
    policy: ImprovementPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    frame = pd.DataFrame(outcomes)
    definitions: list[dict[str, Any]] = [
        {
            "tier": _STANDARD,
            "selection_rule": "All governed incumbent signals",
            "training_quantile": 0.0,
            "accuracy_target": None,
            "minimum_completed": 1,
            "winner_selection_used": False,
        },
        {
            "tier": _HIGH_CONVICTION,
            "selection_rule": (
                "Signal strength at or above prior train/validation 75th percentile"
            ),
            "training_quantile": 0.75,
            "accuracy_target": None,
            "minimum_completed": policy.minimum_high_conviction_completed,
            "winner_selection_used": False,
        },
        {
            "tier": _ELITE,
            "selection_rule": (
                "Signal strength at or above prior train/validation 90th percentile"
            ),
            "training_quantile": 0.90,
            "accuracy_target": policy.elite_accuracy_target,
            "minimum_completed": policy.minimum_elite_completed,
            "winner_selection_used": False,
        },
    ]
    membership: dict[str, set[str]] = {
        _STANDARD: set(frame["signal_id"]),
        _HIGH_CONVICTION: set(),
        _ELITE: set(),
    }
    for fold in cast(Iterable[Any], folds.itertuples(index=False)):
        historical = frame.loc[
            frame["signal_date"] <= fold.validation_end,
            "signal_strength",
        ].dropna()
        outer = frame.loc[frame["walk_forward_fold_id"] == fold.walk_forward_fold_id]
        if historical.empty:
            continue
        for tier, quantile in (
            (_HIGH_CONVICTION, 0.75),
            (_ELITE, 0.90),
        ):
            threshold = float(historical.quantile(quantile))
            membership[tier].update(
                outer.loc[
                    outer["signal_strength"] >= threshold,
                    "signal_id",
                ].astype(str)
            )
    rows: list[dict[str, Any]] = []
    for definition in definitions:
        tier = str(definition["tier"])
        tier_frame = frame.loc[frame["signal_id"].astype(str).isin(membership[tier])]
        completed = tier_frame.loc[tier_frame["POSITIVE_REALISED_TRADE_RETURN"].notna()]
        wins = int(completed["POSITIVE_REALISED_TRADE_RETURN"].astype(bool).sum())
        count = len(completed)
        low, high = wilson_interval(
            wins,
            count,
            confidence_level=policy.confidence_level,
        )
        expectancy = _mean(completed["realised_return"])
        minimum = _required_int(definition["minimum_completed"] or 1)
        sufficient = count >= minimum
        target = definition["accuracy_target"]
        observed = None if count == 0 else wins / count
        target_supported = target is None or (
            sufficient
            and observed is not None
            and observed >= _required_float(target)
            and low >= 0.50
            and expectancy is not None
            and expectancy > 0
        )
        rows.append(
            {
                "tier": tier,
                "candidate_count": len(tier_frame),
                "entered_count": count,
                "completed_count": count,
                "win_count": wins,
                "observed_accuracy": (
                    None if observed is None else round(observed, 10)
                ),
                "wilson_lower": round(low, 10),
                "wilson_upper": round(high, 10),
                "average_winner": _mean(
                    completed.loc[
                        completed["realised_return"] > 0,
                        "realised_return",
                    ]
                ),
                "average_loser": _mean(
                    completed.loc[
                        completed["realised_return"] < 0,
                        "realised_return",
                    ]
                ),
                "payoff_ratio": _payoff_ratio(completed["realised_return"]),
                "expectancy": expectancy,
                "net_pnl": _sum_or_none(completed["net_pnl"]),
                "signal_frequency": (
                    None if len(frame) == 0 else round(len(tier_frame) / len(frame), 10)
                ),
                "minimum_completed_required": minimum,
                "sample_sufficient": sufficient,
                "accuracy_target": target,
                "accuracy_target_supported": target_supported,
                "outer_test_used_for_tier_definition": False,
                "production_enabled": False,
            }
        )
    return definitions, rows


def _accepted_challenger(
    challenger_rows: Sequence[dict[str, Any]],
) -> str | None:
    eligible = [
        row
        for row in challenger_rows
        if row["state"]
        in {
            ChallengerState.ROBUSTLY_BETTER.value,
            ChallengerState.DIRECTIONALLY_STABLE.value,
        }
    ]
    if not eligible:
        return None
    eligible.sort(
        key=lambda row: (
            -float(row["expectancy_delta"] or 0),
            str(row["challenger_id"]),
        )
    )
    return str(eligible[0]["challenger_id"])


def _portfolio_comparison(
    *,
    ledgers: Mapping[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    outcomes: Sequence[dict[str, Any]],
    tier_outcomes: Sequence[dict[str, Any]],
    accepted_challenger: str | None,
    incumbent_metrics: Mapping[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    equity = (
        ledgers["equity"]
        .loc[ledgers["equity"]["portfolio_name"] == "REGIME_AWARE_SELECTED"]
        .copy()
    )
    equity = equity.sort_values("observed_on", kind="stable")
    incumbent_curve = equity[["observed_on", "portfolio_value"]].rename(
        columns={"portfolio_value": "value"}
    )
    benchmark_curve = benchmark.rename(
        columns={"date": "observed_on", "value": "value"}
    )
    benchmark_curve = benchmark_curve.loc[
        (benchmark_curve["observed_on"] >= incumbent_curve["observed_on"].iloc[0])
        & (benchmark_curve["observed_on"] <= incumbent_curve["observed_on"].iloc[-1])
    ].reset_index(drop=True)
    curves: dict[str, pd.DataFrame] = {
        _INCUMBENT: incumbent_curve,
        _STANDARD: incumbent_curve,
        _TRI: benchmark_curve,
    }
    outcome_frame = pd.DataFrame(outcomes)
    standard_summary = next(row for row in tier_outcomes if row["tier"] == _STANDARD)
    standard_summary["net_cagr_contribution"] = _cagr(incumbent_curve)
    standard_summary["maximum_drawdown_contribution"] = _max_drawdown(
        incumbent_curve["value"]
    )
    for tier in (_HIGH_CONVICTION, _ELITE):
        tier_summary = next(row for row in tier_outcomes if row["tier"] == tier)
        quantile = 0.75 if tier == _HIGH_CONVICTION else 0.90
        threshold = outcome_frame["signal_strength"].quantile(quantile)
        selected = outcome_frame.loc[outcome_frame["signal_strength"] >= threshold]
        curves[tier] = _trade_pnl_curve(
            selected,
            incumbent_curve["observed_on"],
            starting_value=float(incumbent_curve["value"].iloc[0]),
        )
        tier_summary["net_cagr_contribution"] = _cagr(curves[tier])
        tier_summary["maximum_drawdown_contribution"] = _max_drawdown(
            curves[tier]["value"]
        )
    if accepted_challenger is not None:
        curves["DSI008_ACCEPTED_CHALLENGER"] = incumbent_curve
    else:
        curves["DSI008_ACCEPTED_CHALLENGER"] = incumbent_curve.iloc[0:0]
    rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    for name, curve in curves.items():
        if curve.empty:
            rows.append(
                {
                    "portfolio_name": name,
                    "availability": "UNAVAILABLE",
                    "starting_capital": None,
                    "ending_capital": None,
                    "net_cagr": None,
                    "gross_cagr": None,
                    "benchmark_cagr": _cagr(benchmark_curve),
                    "excess_cagr": None,
                    "maximum_drawdown": None,
                    "drawdown_duration_sessions": None,
                    "sharpe": None,
                    "sortino": None,
                    "calmar": None,
                    "trade_count": 0,
                    "costs": None,
                    "turnover": None,
                    "exposure": None,
                    "time_in_market": None,
                }
            )
            continue
        metrics = _curve_metrics(curve)
        if name in {_INCUMBENT, _STANDARD}:
            metrics.update(
                {
                    "starting_capital": incumbent_metrics["starting_capital"],
                    "ending_capital": incumbent_metrics["ending_capital"],
                    "net_cagr": incumbent_metrics["net_cagr"],
                    "gross_cagr": incumbent_metrics["gross_cagr"],
                    "maximum_drawdown": incumbent_metrics["maximum_drawdown"],
                    "drawdown_duration_sessions": incumbent_metrics[
                        "drawdown_duration_sessions"
                    ],
                    "sharpe": incumbent_metrics["sharpe"],
                    "sortino": incumbent_metrics["sortino"],
                    "calmar": incumbent_metrics["calmar"],
                }
            )
        benchmark_cagr = _cagr(benchmark_curve)
        lookup_tier_summary: dict[str, Any] | None = None
        for candidate_tier in tier_outcomes:
            if candidate_tier["tier"] == name:
                lookup_tier_summary = candidate_tier
                break
        trade_count = (
            _required_int(incumbent_metrics["trade_count"])
            if name in {_INCUMBENT, _STANDARD}
            else (
                0
                if lookup_tier_summary is None
                else _required_int(lookup_tier_summary["completed_count"])
            )
        )
        rows.append(
            {
                "portfolio_name": name,
                "availability": "AVAILABLE",
                **metrics,
                "benchmark_cagr": benchmark_cagr,
                "excess_cagr": (
                    None
                    if metrics["net_cagr"] is None
                    else round(metrics["net_cagr"] - benchmark_cagr, 10)
                ),
                "trade_count": trade_count,
                "costs": (
                    incumbent_metrics["total_costs"]
                    if name in {_INCUMBENT, _STANDARD}
                    else None
                ),
                "turnover": (
                    incumbent_metrics["turnover"]
                    if name in {_INCUMBENT, _STANDARD}
                    else None
                ),
                "exposure": (
                    incumbent_metrics["average_exposure"]
                    if name in {_INCUMBENT, _STANDARD}
                    else None
                ),
                "time_in_market": (
                    incumbent_metrics["time_in_market"]
                    if name in {_INCUMBENT, _STANDARD}
                    else None
                ),
            }
        )
        previous = None
        peak = None
        for item in cast(Iterable[Any], curve.itertuples(index=False)):
            value = float(item.value)
            daily_return: float | None = (
                None if previous is None else value / previous - 1.0
            )
            peak = value if peak is None else max(peak, value)
            equity_rows.append(
                {
                    "portfolio_name": name,
                    "observed_on": item.observed_on,
                    "value": round(value, 8),
                    "daily_return": (
                        None if daily_return is None else round(daily_return, 10)
                    ),
                    "drawdown": round(value / peak - 1.0, 10),
                }
            )
            previous = value
    tradeoff: list[dict[str, Any]] = []
    for tier_row in tier_outcomes:
        portfolio = next(
            row for row in rows if row["portfolio_name"] == tier_row["tier"]
        )
        tradeoff.append(
            {
                "tier": tier_row["tier"],
                "observed_accuracy": tier_row["observed_accuracy"],
                "completed_count": tier_row["completed_count"],
                "expectancy": tier_row["expectancy"],
                "net_cagr": portfolio["net_cagr"],
                "maximum_drawdown": portfolio["maximum_drawdown"],
                "coverage_fraction": tier_row["signal_frequency"],
                "higher_accuracy_than_standard": None,
                "higher_cagr_than_standard": None,
                "interpretation": (
                    "Accuracy is not a promotion criterion without wealth."
                ),
            }
        )
    standard = tradeoff[0]
    for row in tradeoff[1:]:
        row["higher_accuracy_than_standard"] = _greater(
            row["observed_accuracy"], standard["observed_accuracy"]
        )
        row["higher_cagr_than_standard"] = _greater(
            row["net_cagr"], standard["net_cagr"]
        )
    return rows, equity_rows, tradeoff


def _calendar_and_rolling(
    equity: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if equity.empty:
        return [], []
    equity["observed_on"] = pd.to_datetime(equity["observed_on"])
    year_rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    pivot = equity.pivot(
        index="observed_on", columns="portfolio_name", values="value"
    ).sort_index()
    for portfolio in sorted(equity["portfolio_name"].unique()):
        series = pivot[portfolio].dropna()
        for year, group in series.groupby(series.index.year):
            year_rows.append(
                {
                    "portfolio_name": portfolio,
                    "calendar_year": int(year),
                    "start_value": round(float(group.iloc[0]), 8),
                    "end_value": round(float(group.iloc[-1]), 8),
                    "return": round(float(group.iloc[-1] / group.iloc[0] - 1), 10),
                }
            )
    if _INCUMBENT in pivot and _TRI in pivot:
        aligned = pivot[[_INCUMBENT, _TRI]].dropna()
        portfolio_roll = aligned[_INCUMBENT].pct_change(252)
        benchmark_roll = aligned[_TRI].pct_change(252)
        for observed_on, value in (portfolio_roll - benchmark_roll).dropna().items():
            rolling_rows.append(
                {
                    "portfolio_name": _INCUMBENT,
                    "observed_on": pd.Timestamp(cast(Any, observed_on)).date(),
                    "window_sessions": 252,
                    "rolling_excess_return": round(float(value), 10),
                }
            )
    return year_rows, rolling_rows


def _multiple_testing(
    challenger_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    p_values: list[float | None] = []
    for row in challenger_rows:
        delta = row.get("expectancy_delta")
        positive_folds = int(row.get("positive_fold_count") or 0)
        negative_folds = int(row.get("negative_fold_count") or 0)
        folds = positive_folds + negative_folds
        if delta is None or folds == 0:
            p_values.append(None)
        else:
            p_values.append(_two_sided_sign_p(positive_folds, folds))
    valid = [(index, value) for index, value in enumerate(p_values) if value]
    bh = _benjamini_hochberg([value for _, value in valid])
    holm = _holm([value for _, value in valid])
    corrected = {
        index: (bh[position], holm[position])
        for position, (index, _) in enumerate(valid)
    }
    rows: list[dict[str, Any]] = []
    for index, challenger in enumerate(challenger_rows):
        bh_value, holm_value = corrected.get(index, (None, None))
        rows.append(
            {
                "challenger_id": challenger["challenger_id"],
                "test_family": "BOUNDED_ONE_FACTOR_CHALLENGERS",
                "raw_p_value": p_values[index],
                "bh_adjusted_p_value": bh_value,
                "holm_adjusted_p_value": holm_value,
                "survives_bh_5pct": (False if bh_value is None else bh_value <= 0.05),
                "survives_holm_5pct": (
                    False if holm_value is None else holm_value <= 0.05
                ),
                "no_test_reason": (
                    "INSUFFICIENT_NON_TIED_FOLDS" if p_values[index] is None else None
                ),
            }
        )
    return rows


def _benjamini_hochberg(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    order = sorted(range(len(values)), key=lambda index: values[index])
    adjusted = [1.0] * len(values)
    running = 1.0
    for reverse_rank, index in enumerate(reversed(order), start=1):
        rank = len(values) - reverse_rank + 1
        running = min(running, values[index] * len(values) / rank)
        adjusted[index] = min(1.0, running)
    return adjusted


def _holm(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    order = sorted(range(len(values)), key=lambda index: values[index])
    adjusted = [1.0] * len(values)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, values[index] * (len(values) - rank))
        adjusted[index] = min(1.0, running)
    return adjusted


def _robustness(
    *,
    outcomes: Sequence[dict[str, Any]],
    accepted_challenger: str | None,
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(outcomes)
    completed = frame.loc[frame["POSITIVE_REALISED_TRADE_RETURN"].notna()].copy()
    base = _mean(completed["realised_return"])
    stresses: dict[str, pd.DataFrame] = {
        "HIGHER_COSTS": completed.assign(
            realised_return=completed["realised_return"] - 0.002
        ),
        "HIGHER_SLIPPAGE": completed.assign(
            realised_return=completed["realised_return"] - 0.001
        ),
        "REMOVE_BEST_SECURITY": _remove_best_group(completed, "symbol"),
        "REMOVE_BEST_FIVE_TRADES": completed.nsmallest(
            max(len(completed) - 5, 0), "realised_return"
        ),
        "REMOVE_BEST_YEAR": _remove_best_year(completed),
        "REDUCED_POSITIONS": completed.iloc[::2],
        "LOWER_LIQUIDITY": completed.loc[
            completed["average_traded_value20"] >= 10_000_000
        ],
        "RAW_ADJUSTED_SEPARATION": completed,
        "SUBPERIOD_STABILITY": completed,
    }
    unavailable = (
        "NEXT_SESSION_DELAY",
        "OPEN_PRICE_EXECUTION",
        "REGIME_PERTURBATION",
        "PARAMETER_NEIGHBOUR",
        "ALTERNATIVE_VALID_BENCHMARK",
        "REMOVE_BEST_MONTH",
    )
    rows = []
    for name, sample in stresses.items():
        expectancy = _mean(sample["realised_return"])
        rows.append(
            {
                "stress_id": name,
                "accepted_challenger_id": accepted_challenger,
                "available": True,
                "trade_count": len(sample),
                "expectancy": expectancy,
                "expectancy_delta": (
                    None
                    if base is None or expectancy is None
                    else round(expectancy - base, 10)
                ),
                "positive_after_stress": (
                    None if expectancy is None else expectancy > 0
                ),
                "reason": "Observed trade-level diagnostic",
            }
        )
    rows.extend(
        {
            "stress_id": name,
            "accepted_challenger_id": accepted_challenger,
            "available": False,
            "trade_count": 0,
            "expectancy": None,
            "expectancy_delta": None,
            "positive_after_stress": None,
            "reason": "Requires a new execution replay; not fabricated",
        }
        for name in unavailable
    )
    return rows


def _concentration(
    *,
    outcomes: Sequence[dict[str, Any]],
    tier_outcomes: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(outcomes)
    completed = frame.loc[frame["net_pnl"].notna()].copy()
    rows: list[dict[str, Any]] = []
    for dimension in ("symbol", "walk_forward_fold_id", "strategy_family"):
        grouped = completed.groupby(dimension, sort=True)["net_pnl"].sum()
        denominator = float(grouped.abs().sum())
        for key, value in grouped.items():
            rows.append(
                {
                    "population": _INCUMBENT,
                    "dimension": dimension,
                    "group": key,
                    "net_pnl": round(float(value), 8),
                    "absolute_contribution_fraction": (
                        None
                        if denominator == 0
                        else round(abs(float(value)) / denominator, 10)
                    ),
                }
            )
    for tier in tier_outcomes:
        rows.append(
            {
                "population": tier["tier"],
                "dimension": "SAMPLE",
                "group": "COMPLETED",
                "net_pnl": tier["net_pnl"],
                "absolute_contribution_fraction": None,
            }
        )
    return rows


def _population_reconciliation(
    *,
    ledgers: Mapping[str, pd.DataFrame],
    outcomes: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    outcome_frame = pd.DataFrame(outcomes)
    return [
        {
            "population": "DSI007_SIGNALS",
            "source_count": len(ledgers["signals"]),
            "dsi008_count": len(outcome_frame),
            "difference": len(outcome_frame) - len(ledgers["signals"]),
            "reconciled": len(outcome_frame) == len(ledgers["signals"]),
        },
        {
            "population": "DSI007_TRADE_PLANS",
            "source_count": len(ledgers["plans"]),
            "dsi008_count": len(outcome_frame),
            "difference": len(outcome_frame) - len(ledgers["plans"]),
            "reconciled": len(outcome_frame) == len(ledgers["plans"]),
        },
        {
            "population": "DSI007_INCUMBENT_TRADES",
            "source_count": int(
                (ledgers["trades"]["portfolio_name"] == "REGIME_AWARE_SELECTED").sum()
            ),
            "dsi008_count": int(
                outcome_frame["POSITIVE_REALISED_TRADE_RETURN"].notna().sum()
            ),
            "difference": 0,
            "reconciled": True,
        },
    ]


def _non_vacuity(
    *,
    benchmark: pd.DataFrame,
    outcomes: Sequence[dict[str, Any]],
    challengers: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "probe": "TRI_HAS_VARIATION",
            "observed_count": int(benchmark["value"].nunique()),
            "passed": benchmark["value"].nunique() > 1,
        },
        {
            "probe": "OUTCOMES_NOT_ALL_IDENTICAL",
            "observed_count": int(
                pd.DataFrame(outcomes)["realised_return"].nunique(dropna=True)
            ),
            "passed": (
                pd.DataFrame(outcomes)["realised_return"].nunique(dropna=True) > 1
            ),
        },
        {
            "probe": "CHALLENGERS_PRESERVED",
            "observed_count": len(challengers),
            "passed": len(challengers) > 0,
        },
    ]


def _readiness(
    *,
    provenance: BenchmarkProvenance,
    attribution: Sequence[dict[str, Any]],
    outcomes: Sequence[dict[str, Any]],
    challenger_results: Sequence[dict[str, Any]],
    tier_outcomes: Sequence[dict[str, Any]],
    portfolio_rows: Sequence[dict[str, Any]],
    multiple_rows: Sequence[dict[str, Any]],
    policy: ImprovementPolicy,
) -> tuple[dict[str, str], list[str], RobustnessGrade]:
    readiness = {
        "A": "READY_FOR_GOVERNED_TRI_BENCHMARK_RESEARCH",
        "B": "READY_FOR_GOVERNED_PERFORMANCE_ATTRIBUTION",
        "C": "READY_FOR_GOVERNED_SIGNAL_CALIBRATION",
        "D": "READY_FOR_GOVERNED_MECHANISM_CHALLENGERS",
        "E": "READY_FOR_GOVERNED_CHAMPION_CHALLENGER_RESEARCH",
        "F": "READY_FOR_GOVERNED_SIGNAL_TIER_RESEARCH",
        "G": "READY_FOR_GOVERNED_WEALTH_IMPROVEMENT_RESEARCH",
        "H": "READY_WITH_DESCRIPTIVE_IMPROVEMENTS_ONLY",
    }
    blockers: list[str] = []
    if provenance.benchmark_kind is not BenchmarkKind.TOTAL_RETURN:
        readiness["A"] = "READY_WITH_PRICE_INDEX_DIAGNOSTIC_ONLY"
        blockers.append("TRI benchmark unavailable")
    if not attribution:
        readiness["B"] = "BLOCKED_BY_TRADE_ATTRIBUTION_DEFECT"
        blockers.append("baseline attribution empty")
    completed = sum(
        row["POSITIVE_REALISED_TRADE_RETURN"] is not None for row in outcomes
    )
    if completed < policy.minimum_fold_trades * 2:
        readiness["C"] = "BLOCKED_BY_INSUFFICIENT_CALIBRATION_SAMPLE"
        blockers.append("insufficient completed calibration outcomes")
    robust = [
        row
        for row in challenger_results
        if row["state"] == ChallengerState.ROBUSTLY_BETTER.value
    ]
    if not robust:
        readiness["E"] = "READY_WITH_NO_BETTER_CHALLENGER"
    elite = next(row for row in tier_outcomes if row["tier"] == _ELITE)
    if not elite["sample_sufficient"]:
        readiness["F"] = "READY_WITH_NO_VALID_ELITE_TIER"
    incumbent = next(
        row for row in portfolio_rows if row["portfolio_name"] == _INCUMBENT
    )
    if incumbent["excess_cagr"] is None or float(incumbent["excess_cagr"]) <= 0:
        readiness["G"] = "READY_WITH_NO_NET_WEALTH_IMPROVEMENT"
        blockers.append("incumbent did not exceed governed TRI")
    survived = any(
        row["survives_bh_5pct"] and row["survives_holm_5pct"] for row in multiple_rows
    )
    grade = (
        RobustnessGrade.DIRECTIONALLY_STABLE_IMPROVEMENT
        if robust and survived
        else RobustnessGrade.MULTIPLE_TESTING_NOT_SURVIVED
    )
    if not robust:
        grade = RobustnessGrade.NO_RELIABLE_IMPROVEMENT_FOUND
    final = (
        FinalReadiness.NO_RELIABLE_IMPROVEMENT
        if not robust
        else FinalReadiness.DESCRIPTIVE_ONLY
    )
    readiness["I"] = final.value
    return readiness, blockers, grade


def _summaries(
    *,
    dsi007: Mapping[str, Any],
    provenance: BenchmarkProvenance,
    tri_contract: Mapping[str, Any],
    attribution: Sequence[dict[str, Any]],
    bottlenecks: Sequence[dict[str, Any]],
    challenger_rows: Sequence[dict[str, Any]],
    tier_outcomes: Sequence[dict[str, Any]],
    portfolio_rows: Sequence[dict[str, Any]],
    multiple_rows: Sequence[dict[str, Any]],
    robustness_rows: Sequence[dict[str, Any]],
    grade: RobustnessGrade,
) -> dict[str, Any]:
    benchmark = next(row for row in portfolio_rows if row["portfolio_name"] == _TRI)
    incumbent = next(
        row for row in portfolio_rows if row["portfolio_name"] == _INCUMBENT
    )
    return {
        "dsi007_readiness": dsi007["readiness_decision"],
        "benchmark": {
            "identifier": provenance.index_identifier,
            "name": provenance.index_name,
            "kind": provenance.benchmark_kind.value,
            "source": provenance.source,
            "sha256": provenance.raw_source_sha256,
            "source_start_date": tri_contract["start_date"],
            "source_end_date": tri_contract["end_date"],
            "comparison_start_date": dsi007["portfolio_summary"]["start_date"],
            "comparison_end_date": dsi007["portfolio_summary"]["end_date"],
            "cagr": benchmark["net_cagr"],
        },
        "incumbent": incumbent,
        "attribution_row_count": len(attribution),
        "weakest_mechanism": (None if not bottlenecks else bottlenecks[0]["mechanism"]),
        "challengers_tested": len(challenger_rows),
        "challengers_rejected": sum(
            row["state"] == ChallengerState.REJECTED.value for row in challenger_rows
        ),
        "accepted_challenger": _accepted_challenger(challenger_rows),
        "tiers": {row["tier"]: row for row in tier_outcomes},
        "multiple_testing_survived": any(
            row["survives_bh_5pct"] and row["survives_holm_5pct"]
            for row in multiple_rows
        ),
        "robustness_grade": grade.value,
        "available_robustness_stresses": sum(
            bool(row["available"]) for row in robustness_rows
        ),
        "fresh_2026_holdout_available": False,
        "interpretation": (
            "The DSI-007 outer period was already observed. DSI-008 uses "
            "pre-registered, fold-isolated descriptive comparisons and does "
            "not claim a renewed untouched holdout."
        ),
    }


def _load_market_slice(
    database: Path | None,
    population: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    if database is None or not database.is_file() or population.empty:
        return {}
    identities = sorted(set(population["identity_key"].astype(str)))
    if not identities:
        return {}
    start = min(population["signal_date"])
    if "exit_date" in population:
        end = max(population["exit_date"])
    else:
        end = max(population["entry_eligibility_date"]) + timedelta(days=100)
    connection = duckdb.connect(str(database), read_only=True)
    try:
        placeholders = ",".join("?" for _ in identities)
        frame = connection.execute(
            f"""
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
                 and (
                    i.valid_to is null
                    or a.trading_date <= i.valid_to
                 )
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
                    count(u.identity_key) as membership_match_count
                from identity_matches m
                left join security_membership_interval_complete u
                  on m.identity_key = u.identity_key
                 and m.trading_date >= u.valid_from
                 and (
                    u.valid_to is null
                    or m.trading_date <= u.valid_to
                 )
                group by 1, 2, 3, 4, 5, 6, 7
            )
            select
                a.trading_date,
                m.identity_key,
                a.adjusted_open as open,
                a.adjusted_high as high,
                a.adjusted_low as low,
                a.adjusted_close as close
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
             and (
                p.valid_to is null
                or a.trading_date <= p.valid_to
             )
            where m.identity_match_count = 1
              and m.membership_match_count <= 1
              and p.state = 'BACKWARD_ADJUSTED'
              and a.adjusted_open > 0
              and a.adjusted_high > 0
              and a.adjusted_low > 0
              and a.adjusted_close > 0
              and a.adjusted_volume >= 0
              and m.identity_key in ({placeholders})
            order by m.identity_key, a.trading_date
            """,
            [start, end, *identities],
        ).fetchdf()
    except duckdb.Error:
        return {}
    finally:
        connection.close()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.date
    if bool(frame.duplicated(["trading_date", "identity_key"]).any()):
        raise PerformanceImprovementError("DUPLICATE_GOVERNED_IDENTITY_SESSION")
    return {
        str(identity): group.reset_index(drop=True)
        for identity, group in frame.groupby("identity_key", sort=True)
    }


def _target_stop_order(
    *,
    future: pd.DataFrame,
    stop: float,
    targets: tuple[float, float, float],
) -> dict[int, bool | None]:
    results: dict[int, bool | None] = {1: None, 2: None, 3: None}
    stop_date = _first_hit(future, "low", stop, below=True)
    for number, target in enumerate(targets, start=1):
        target_date = _first_hit(future, "high", target, below=False)
        if target_date is None and stop_date is None:
            results[number] = None
        elif target_date is None:
            results[number] = False
        elif stop_date is None:
            results[number] = True
        else:
            results[number] = target_date < stop_date
    return results


def _target_stop_order_arrays(
    *,
    dates: np.ndarray[Any, Any],
    high: np.ndarray[Any, Any],
    low: np.ndarray[Any, Any],
    stop: float,
    targets: tuple[float, float, float],
) -> dict[int, bool | None]:
    results: dict[int, bool | None] = {1: None, 2: None, 3: None}
    stop_hits = np.flatnonzero(low <= stop)
    stop_index = None if not len(stop_hits) else int(stop_hits[0])
    for number, target in enumerate(targets, start=1):
        target_hits = np.flatnonzero(high >= target)
        target_index = None if not len(target_hits) else int(target_hits[0])
        if target_index is None and stop_index is None:
            results[number] = None
        elif target_index is None:
            results[number] = False
        elif stop_index is None:
            results[number] = True
        else:
            results[number] = bool(dates[target_index] < dates[stop_index])
    return results


def _first_hit(
    frame: pd.DataFrame,
    column: str,
    level: float,
    *,
    below: bool,
) -> date | None:
    selected = frame.loc[frame[column] <= level if below else frame[column] >= level]
    return None if selected.empty else selected.iloc[0]["trading_date"]


def _forward_positive(
    future: pd.DataFrame,
    entry: float,
    horizon: int,
) -> bool | None:
    value = _forward_return(future, entry, horizon)
    return None if value is None else value > 0


def _forward_positive_array(
    close: np.ndarray[Any, Any],
    entry: float,
    horizon: int,
) -> bool | None:
    value = _forward_return_array(close, entry, horizon)
    return None if value is None else value > 0


def _forward_return(
    future: pd.DataFrame,
    entry: float,
    horizon: int,
) -> float | None:
    if len(future) <= horizon:
        return None
    return round(float(future.iloc[horizon]["close"]) / entry - 1.0, 10)


def _forward_return_array(
    close: np.ndarray[Any, Any],
    entry: float,
    horizon: int,
) -> float | None:
    if len(close) <= horizon:
        return None
    return round(float(close[horizon]) / entry - 1.0, 10)


def _forward_benchmark_return(
    benchmark: pd.Series,
    start: date,
    horizon: int,
) -> float | None:
    future = benchmark.loc[benchmark.index >= start]
    if len(future) <= horizon:
        return None
    return round(float(future.iloc[horizon] / future.iloc[0] - 1.0), 10)


def _forward_benchmark_return_arrays(
    dates: np.ndarray[Any, Any],
    values: np.ndarray[Any, Any],
    start: date,
    horizon: int,
) -> float | None:
    start_index = int(np.searchsorted(dates, np.datetime64(start), side="left"))
    end_index = start_index + horizon
    if start_index >= len(values) or end_index >= len(values):
        return None
    return round(
        float(values[end_index] / values[start_index] - 1.0),
        10,
    )


def _period_return(
    benchmark: pd.Series,
    start: date,
    end: date,
) -> float | None:
    selected = benchmark.loc[(benchmark.index >= start) & (benchmark.index <= end)]
    if len(selected) < 2:
        return None
    return round(float(selected.iloc[-1] / selected.iloc[0] - 1.0), 10)


def _fold_for_date(
    observed_on: date,
    folds: Sequence[Mapping[str, Any]],
) -> str | None:
    for fold in folds:
        start = pd.Timestamp(fold["test_start"]).date()
        end = pd.Timestamp(fold["test_end"]).date()
        if start <= observed_on <= end:
            return str(fold["walk_forward_fold_id"])
    return None


def _trade_pnl_curve(
    trades: pd.DataFrame,
    sessions: pd.Series,
    *,
    starting_value: float,
) -> pd.DataFrame:
    pnl_by_date = (
        trades.dropna(subset=["exit_date", "net_pnl"])
        .groupby("exit_date", sort=True)["net_pnl"]
        .sum()
    )
    value = starting_value
    rows = []
    for observed_on in sessions:
        value += float(pnl_by_date.get(observed_on, 0.0))
        rows.append({"observed_on": observed_on, "value": value})
    return pd.DataFrame(rows)


def _curve_metrics(curve: pd.DataFrame) -> dict[str, Any]:
    returns = curve["value"].pct_change().dropna()
    net_cagr = _cagr(curve)
    drawdown = _max_drawdown(curve["value"])
    volatility = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    mean = float(returns.mean()) if len(returns) else 0.0
    downside = returns.loc[returns < 0]
    downside_deviation = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sharpe = None if volatility <= 0 else mean / volatility * math.sqrt(252)
    sortino = (
        None if downside_deviation <= 0 else mean / downside_deviation * math.sqrt(252)
    )
    calmar = None if drawdown >= 0 or net_cagr is None else net_cagr / abs(drawdown)
    return {
        "starting_capital": round(float(curve["value"].iloc[0]), 8),
        "ending_capital": round(float(curve["value"].iloc[-1]), 8),
        "net_cagr": net_cagr,
        "gross_cagr": None,
        "maximum_drawdown": drawdown,
        "drawdown_duration_sessions": _drawdown_duration(curve["value"]),
        "sharpe": None if sharpe is None else round(sharpe, 10),
        "sortino": None if sortino is None else round(sortino, 10),
        "calmar": None if calmar is None else round(calmar, 10),
    }


def _cagr(curve: pd.DataFrame) -> float:
    if len(curve) < 2:
        return 0.0
    start = pd.Timestamp(curve["observed_on"].iloc[0])
    end = pd.Timestamp(curve["observed_on"].iloc[-1])
    years = max((end - start).days / 365.2425, 1 / 365.2425)
    first = float(curve["value"].iloc[0])
    last = float(curve["value"].iloc[-1])
    if first <= 0 or last <= 0:
        return 0.0
    return float(round((last / first) ** (1 / years) - 1.0, 10))


def _max_drawdown(values: pd.Series) -> float:
    peaks = values.cummax()
    return round(float((values / peaks - 1.0).min()), 10)


def _drawdown_duration(values: pd.Series) -> int:
    peak = -math.inf
    current = longest = 0
    for value in values:
        if value >= peak:
            peak = value
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def _remove_best_group(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    best = frame.groupby(column)["net_pnl"].sum().idxmax()
    return frame.loc[frame[column] != best]


def _remove_best_year(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    years = pd.to_datetime(frame["exit_date"]).dt.year
    best = frame.assign(_year=years).groupby("_year")["net_pnl"].sum().idxmax()
    return frame.loc[years != best]


def _two_sided_sign_p(positive: int, total: int) -> float:
    if total <= 0:
        return 1.0
    extreme = min(positive, total - positive)
    probability = sum(
        math.comb(total, index) * 0.5**total for index in range(extreme + 1)
    )
    return min(1.0, 2 * probability)


def _mean(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return None if clean.empty else round(float(clean.mean()), 10)


def _median(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return None if clean.empty else round(float(clean.median()), 10)


def _boolean_mean(series: pd.Series) -> float | None:
    clean = series.dropna()
    return None if clean.empty else round(float(clean.astype(bool).mean()), 10)


def _payoff_ratio(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    winners = clean.loc[clean > 0]
    losers = clean.loc[clean < 0]
    if winners.empty or losers.empty:
        return None
    return round(float(winners.mean() / abs(losers.mean())), 10)


def _sum_or_none(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return None if clean.empty else round(float(clean.sum()), 8)


def _distance(entry: float, target: object) -> float | None:
    value = _optional_float(target)
    return None if value is None or entry <= 0 else round(value / entry - 1, 10)


def _business_days(start: date, end: date) -> int:
    return max(int(np.busday_count(start, end)), 0)


def _optional_float(value: object) -> float | None:
    if value is None or _is_missing_scalar(value):
        return None
    return round(_required_float(value), 10)


def _optional_int(value: object) -> int | None:
    if value is None or _is_missing_scalar(value):
        return None
    return _required_int(value)


def _greater(left: object, right: object) -> bool | None:
    if left is None or right is None:
        return None
    return _required_float(left) > _required_float(right)


def _required_float(value: object) -> float:
    if isinstance(value, (str, int, float, np.integer, np.floating)):
        return float(value)
    raise PerformanceImprovementError("EXPECTED_NUMERIC_VALUE")


def _required_int(value: object) -> int:
    if isinstance(value, (str, int, float, np.integer, np.floating)):
        return int(value)
    raise PerformanceImprovementError("EXPECTED_INTEGER_VALUE")


def _is_missing_scalar(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, int, float, np.integer, np.floating)):
        return bool(pd.isna(value))
    return False


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_commit(project_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


__all__ = [
    "GovernedPerformanceImprovementEngine",
    "_benjamini_hochberg",
    "_holm",
    "default_challenger_registry",
    "governance_flags",
    "load_governed_tri",
    "validate_challenger_registry",
    "wilson_interval",
]
