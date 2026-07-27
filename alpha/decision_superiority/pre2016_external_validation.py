"""Governed DSI-010 pre-2016 external-era validation engine."""

from __future__ import annotations

import hashlib
import math
import subprocess
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from statistics import mean
from types import MappingProxyType
from typing import Any, cast

import pandas as pd

from alpha.decision_superiority.entry_stop_improvement_artifacts import (
    DSI009_ARTIFACTS,
    validate_entry_stop_improvement_certificate,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
    DSI010_FROZEN_CHALLENGER_ID,
    ExternalValidationClassification,
    Pre2016ExternalValidationError,
    Pre2016ExternalValidationPolicy,
    Pre2016ExternalValidationResult,
    Pre2016ExternalValidationSourcePaths,
)
from alpha.decision_superiority.regime_strategy_artifacts import (
    DSI007_ARTIFACTS,
    validate_regime_strategy_tournament_certificate,
)
from alpha.decision_superiority.regime_strategy_models import (
    RegimeState,
    TournamentPolicy,
    TournamentSourcePaths,
    WalkForwardFold,
)
from alpha.decision_superiority.regime_strategy_tournament import (
    GovernedRegimeStrategyTournamentEngine,
    _build_independent_trade_plans,
    _build_point_in_time_features,
    _delay_selected_signals,
    _generate_signals,
    _load_benchmark,
    _load_governed_market,
    _portfolio_metrics,
    _signals_for_portfolio,
    _simulate_portfolio,
    default_strategy_registry,
)

_FROZEN_INCUMBENT = "PRE2016_FROZEN_DSI008_INCUMBENT"
_FROZEN_CHALLENGER = "PRE2016_STOP_STRUCTURAL_10D"
_REGIME_PORTFOLIO = "REGIME_AWARE_SELECTED"
_BENCHMARK_PORTFOLIO = "TOTAL_RETURN_INDEX_BENCHMARK"


def governance_flags() -> dict[str, bool]:
    """Return the immutable DSI-010 research-only boundary."""

    return {
        "STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED": False,
        "LIVE_STOP_POLICY_ENABLED": False,
        "LIVE_STRATEGY_SELECTION_ENABLED": False,
        "LIVE_SCORING_ENABLED": False,
        "PRODUCTION_SIGNAL_PUBLICATION_ENABLED": False,
        "PRODUCTION_PORTFOLIO_INFLUENCE": False,
        "THRESHOLD_CHANGE_PERMITTED": False,
        "APPROVAL_POLICY_CHANGE_PERMITTED": False,
        "PORTFOLIO_POLICY_CHANGE_PERMITTED": False,
        "EXECUTION_POLICY_CHANGE_PERMITTED": False,
        "SYNTHETIC_MARKET_DATA_PERMITTED": False,
        "SYNTHETIC_TRADES_PERMITTED": False,
        "SYNTHETIC_OUTCOMES_PERMITTED": False,
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


class GovernedPre2016ExternalValidationEngine:
    """Run frozen transport and independent-era tests without policy mutation."""

    def run(
        self,
        *,
        sources: Pre2016ExternalValidationSourcePaths,
        policy: Pre2016ExternalValidationPolicy = Pre2016ExternalValidationPolicy(),
    ) -> Pre2016ExternalValidationResult:
        """Execute DSI-010 A-I over the governed 2005-2015 data boundary."""

        protocol_rows = (_protocol_row(policy),)
        dsi009 = validate_entry_stop_improvement_certificate(
            sources.dsi009_certificate,
            require_ready=False,
        )
        dsi007 = validate_regime_strategy_tournament_certificate(
            sources.dsi007_certificate,
            require_ready=False,
        )
        frozen_contract_rows = _validate_frozen_candidate(
            sources=sources,
            dsi009=dsi009,
            policy=policy,
        )
        tournament_policy = TournamentPolicy(
            transaction_cost_fraction=policy.transaction_cost_fraction,
            slippage_fraction=policy.slippage_fraction,
        )
        tournament_sources = TournamentSourcePaths(
            database=sources.database,
            historical_truth_snapshots=sources.historical_truth_snapshots,
            benchmark=str(sources.benchmark),
            project_root=sources.project_root,
        )

        source_rows, market, source_summary = _load_governed_market(
            sources=tournament_sources,
            start=policy.external_start,
            end=policy.external_end,
        )
        if market.empty:
            raise Pre2016ExternalValidationError(
                "NO_GOVERNED_PRE2016_MARKET_POPULATION"
            )
        featured, regime_daily, regime_transitions = _build_point_in_time_features(
            market
        )
        variants = default_strategy_registry()
        signals = _generate_signals(featured, variants, tournament_policy)
        plans, independent_trades = _build_independent_trade_plans(
            featured,
            signals,
            variants,
            tournament_policy,
        )
        frozen_mapping = _load_frozen_mapping(sources.dsi007_certificate.parent)
        transport_fold = _transport_fold(featured, policy=policy)
        transport_selections = _transport_selection_rows(
            transport_fold,
            frozen_mapping=frozen_mapping,
        )
        selected = _signals_for_portfolio(
            name=_REGIME_PORTFOLIO,
            signals=signals,
            plans=plans,
            folds=(transport_fold,),
            selections=transport_selections,
        )
        incumbent_simulation = _simulate_portfolio(
            name=_FROZEN_INCUMBENT,
            featured=featured,
            selected_signals=selected,
            start=transport_fold.test_start,
            end=transport_fold.test_end,
            policy=tournament_policy,
        )
        incumbent_metrics = _portfolio_metrics(
            name=_FROZEN_INCUMBENT,
            curve=incumbent_simulation["curve"],
            trades=incumbent_simulation["trades"],
            policy=tournament_policy,
        )
        challenger_selected = _apply_frozen_structural_stop(
            selected,
            slippage_fraction=tournament_policy.slippage_fraction,
        )
        challenger_simulation = _simulate_portfolio(
            name=_FROZEN_CHALLENGER,
            featured=featured,
            selected_signals=challenger_selected,
            start=transport_fold.test_start,
            end=transport_fold.test_end,
            policy=tournament_policy,
        )
        challenger_metrics = _portfolio_metrics(
            name=_FROZEN_CHALLENGER,
            curve=challenger_simulation["curve"],
            trades=challenger_simulation["trades"],
            policy=tournament_policy,
        )
        benchmark_frame, benchmark_rows = _load_benchmark(
            str(sources.benchmark),
            sessions=tuple(
                item
                for item in sorted(featured["trading_date"].unique())
                if transport_fold.test_start <= item <= transport_fold.test_end
            ),
            start=transport_fold.test_start,
            end=transport_fold.test_end,
        )
        benchmark_metrics = _benchmark_metrics(
            benchmark_frame,
            start=transport_fold.test_start,
            end=transport_fold.test_end,
        )

        replication = GovernedRegimeStrategyTournamentEngine().run(
            sources=tournament_sources,
            start=policy.external_start,
            end=policy.external_end,
            policy=tournament_policy,
        )
        replication_metrics = tuple(
            dict(row) for row in replication.rows["risk_metrics"]
        )
        transport_metric_rows = _transport_metric_rows(
            incumbent=incumbent_metrics,
            challenger=challenger_metrics,
            benchmark=benchmark_metrics,
        )
        benchmark_relative_rows = _benchmark_relative_rows(
            transport_metric_rows,
            benchmark=benchmark_metrics,
        )
        stop_difference_rows = _stop_difference_rows(
            incumbent=cast(
                Sequence[Mapping[str, Any]], incumbent_simulation["trades"]
            ),
            challenger=cast(
                Sequence[Mapping[str, Any]], challenger_simulation["trades"]
            ),
        )
        equity_rows = _equity_rows(
            incumbent=cast(
                Sequence[Mapping[str, Any]], incumbent_simulation["curve"]
            ),
            challenger=cast(
                Sequence[Mapping[str, Any]], challenger_simulation["curve"]
            ),
            benchmark=benchmark_frame,
        )
        calendar_rows = _calendar_performance(equity_rows)
        regime_rows = _regime_performance(
            cast(Sequence[Mapping[str, Any]], challenger_simulation["trades"])
        )
        concentration_rows, top_five_share = _concentration(
            cast(Sequence[Mapping[str, Any]], challenger_simulation["trades"])
        )
        robustness_rows = _robustness(
            featured=featured,
            selected=challenger_selected,
            fold=transport_fold,
            policy=tournament_policy,
            incumbent_metrics=incumbent_metrics,
        )
        classification = _classification(
            incumbent=incumbent_metrics,
            challenger=challenger_metrics,
            benchmark=benchmark_metrics,
            top_five_profit_share=top_five_share,
            policy=policy,
        )
        population_rows = _population_reconciliation(
            market=market,
            signals=signals,
            selected=selected,
            challenger_selected=challenger_selected,
            incumbent_simulation=incumbent_simulation,
            challenger_simulation=challenger_simulation,
            independent_trades=independent_trades,
        )
        probe_rows = _non_vacuity_probes(policy)
        readiness, blockers = _readiness(
            source_summary=source_summary,
            benchmark_rows=benchmark_rows,
            selected=selected,
            incumbent_metrics=incumbent_metrics,
            challenger_metrics=challenger_metrics,
            replication=replication,
            classification=classification,
        )
        summaries = {
            "external_start": policy.external_start,
            "external_end": policy.external_end,
            "actual_transport_start": transport_fold.test_start,
            "actual_transport_end": transport_fold.test_end,
            "frozen_challenger_id": policy.frozen_challenger_id,
            "frozen_mapping": dict(sorted(frozen_mapping.items())),
            "market_sessions": int(market["trading_date"].nunique()),
            "market_securities": int(market["identity_key"].nunique()),
            "market_rows": len(market),
            "incumbent": dict(incumbent_metrics),
            "challenger": dict(challenger_metrics),
            "benchmark": benchmark_metrics,
            "benchmark_gap_closed": _benchmark_gap_closed(
                incumbent=incumbent_metrics,
                challenger=challenger_metrics,
                benchmark=benchmark_metrics,
            ),
            "replication_regime_aware": _metric_by_name(
                replication_metrics, _REGIME_PORTFOLIO
            ),
            "replication_benchmark": _metric_by_name(
                replication_metrics, _BENCHMARK_PORTFOLIO
            ),
            "classification": classification.value,
            "top_five_positive_profit_share": top_five_share,
            "external_tuning_performed": False,
            "challenger_contract_changed": False,
            "forward_paper_eligible": classification
            in {
                ExternalValidationClassification.PASSED,
                ExternalValidationClassification.BEATS_BENCHMARK,
                ExternalValidationClassification.DIRECTIONALLY_SUPPORTED,
            },
        }
        rows = {
            "protocol": protocol_rows,
            "frozen_contract": tuple(frozen_contract_rows),
            "source_contract": tuple(dict(row) for row in source_rows),
            "market_data_coverage": tuple(
                dict(row) for row in replication.rows["market_data_coverage"]
            ),
            "universe": tuple(dict(row) for row in replication.rows["universe"]),
            "corporate_actions": tuple(
                dict(row) for row in replication.rows["corporate_actions"]
            ),
            "benchmark_contract": tuple(dict(row) for row in benchmark_rows),
            "regime_daily": tuple(dict(row) for row in regime_daily),
            "regime_transitions": tuple(dict(row) for row in regime_transitions),
            "frozen_policy_mapping": tuple(
                {
                    "regime_state": regime,
                    "selected_strategy_variant_id": variant,
                    "source_fold": "LATEST_SIGNED_DSI007_FOLD",
                    "external_data_used_for_selection": False,
                }
                for regime, variant in sorted(frozen_mapping.items())
            ),
            "frozen_incumbent_signals": tuple(
                _selected_signal_rows(selected, _FROZEN_INCUMBENT)
            ),
            "frozen_challenger_signals": tuple(
                _selected_signal_rows(challenger_selected, _FROZEN_CHALLENGER)
            ),
            "frozen_incumbent_trades": tuple(
                dict(row) for row in incumbent_simulation["trades"]
            ),
            "frozen_challenger_trades": tuple(
                dict(row) for row in challenger_simulation["trades"]
            ),
            "stop_differences": tuple(stop_difference_rows),
            "external_daily_equity": tuple(equity_rows),
            "replication_folds": tuple(
                dict(row) for row in replication.rows["walk_forward_folds"]
            ),
            "replication_selection": tuple(
                dict(row) for row in replication.rows["strategy_selections"]
            ),
            "replication_portfolios": replication_metrics,
            "calendar_performance": tuple(calendar_rows),
            "rolling_performance": tuple(
                dict(row) for row in replication.rows["rolling_performance"]
            ),
            "regime_performance": tuple(regime_rows),
            "metrics": tuple((*transport_metric_rows, *replication_metrics)),
            "benchmark_relative": tuple(benchmark_relative_rows),
            "robustness": tuple(robustness_rows),
            "concentration": tuple(concentration_rows),
            "population_reconciliation": tuple(population_rows),
            "non_vacuity": tuple(probe_rows),
        }
        return Pre2016ExternalValidationResult(
            source_commit=_source_commit(sources.project_root),
            readiness=MappingProxyType(readiness),
            blockers=tuple(blockers),
            rows=MappingProxyType(rows),
            summaries=MappingProxyType(summaries),
            governance=MappingProxyType(governance_flags()),
        )


def _protocol_row(policy: Pre2016ExternalValidationPolicy) -> dict[str, Any]:
    return {
        **asdict(policy),
        "external_start": policy.external_start,
        "external_end": policy.external_end,
        "protocol_frozen_before_external_result": True,
        "future_prices_used_for_rule_selection": False,
        "external_period_used_for_tuning": False,
        "production_influence": False,
    }


def _validate_frozen_candidate(
    *,
    sources: Pre2016ExternalValidationSourcePaths,
    dsi009: Mapping[str, Any],
    policy: Pre2016ExternalValidationPolicy,
) -> list[dict[str, Any]]:
    best = dsi009.get("best_descriptive_result")
    if not isinstance(best, Mapping):
        raise Pre2016ExternalValidationError(
            "DSI009_DESCRIPTIVE_CHALLENGER_MISSING"
        )
    if str(best.get("mechanism_id")) != policy.frozen_challenger_id:
        raise Pre2016ExternalValidationError(
            "DSI009_FROZEN_CHALLENGER_MISMATCH"
        )
    registry_path = (
        sources.dsi009_certificate.parent / DSI009_ARTIFACTS["stop_registry"]
    )
    if not registry_path.is_file():
        raise Pre2016ExternalValidationError(
            "DSI009_STOP_REGISTRY_ARTIFACT_MISSING"
        )
    registry = pd.read_csv(registry_path)
    selected = registry.loc[
        registry["mechanism_id"].astype(str) == policy.frozen_challenger_id
    ]
    if len(selected) != 1:
        raise Pre2016ExternalValidationError(
            "DSI009_FROZEN_CHALLENGER_CONTRACT_NOT_UNIQUE"
        )
    row = selected.iloc[0].to_dict()
    expected = {
        "family": "STRUCTURAL_SUPPORT",
        "structural_lookback": 10,
        "parameter_count": 1,
        "incumbent": False,
        "production_influence": False,
    }
    for key, value in expected.items():
        observed = row.get(key)
        if isinstance(value, bool):
            observed = _as_bool(observed)
        elif isinstance(value, int):
            observed = int(float(observed))
        else:
            observed = str(observed)
        if observed != value:
            raise Pre2016ExternalValidationError(
                f"FROZEN_CHALLENGER_CONTRACT_DRIFT:{key}"
            )
    supplied_dsi007_hash = _sha256(sources.dsi007_certificate)
    source_hashes = dsi009.get("source_chain_hashes")
    if isinstance(source_hashes, Mapping):
        candidate_hashes = {
            str(key): str(value) for key, value in source_hashes.items()
        }
        expected_hash = candidate_hashes.get("DSI007_CERTIFICATE")
        if expected_hash is not None and expected_hash != supplied_dsi007_hash:
            raise Pre2016ExternalValidationError(
                "DSI007_CERTIFICATE_SOURCE_CHAIN_MISMATCH"
            )
    return [
        {
            "candidate_id": policy.frozen_challenger_id,
            "parent_portfolio": "DSI008_INCUMBENT",
            "only_changed_mechanism": "INITIAL_STOP_POLICY",
            "family": "STRUCTURAL_SUPPORT",
            "structural_lookback_sessions": 10,
            "entry_policy": "UNCHANGED_DSI009_INCUMBENT_ENTRY",
            "target_policy": "UNCHANGED",
            "trailing_policy": "UNCHANGED",
            "time_exit_policy": "UNCHANGED",
            "portfolio_constraints": "UNCHANGED",
            "transaction_cost_model": "UNCHANGED",
            "liquidity_model": "UNCHANGED",
            "contract_frozen": True,
            "source_registry_sha256": _sha256(registry_path),
            "dsi009_certificate_sha256": _sha256(sources.dsi009_certificate),
            "dsi007_certificate_sha256": supplied_dsi007_hash,
            "production_influence": False,
        }
    ]


def _load_frozen_mapping(source_dir: Path) -> dict[str, str]:
    path = source_dir / DSI007_ARTIFACTS["regime_strategy_mapping"]
    if not path.is_file():
        raise Pre2016ExternalValidationError(
            "DSI007_REGIME_STRATEGY_MAPPING_MISSING"
        )
    frame = pd.read_csv(path)
    required = {
        "regime_state",
        "selected_strategy_variant_id",
        "test_end",
        "holdout_used",
    }
    missing = required - set(frame.columns)
    if missing:
        raise Pre2016ExternalValidationError(
            "DSI007_REGIME_STRATEGY_MAPPING_SCHEMA_INVALID:"
            + ",".join(sorted(missing))
        )
    if frame["holdout_used"].map(_as_bool).any():
        raise Pre2016ExternalValidationError(
            "DSI007_MAPPING_USED_HOLDOUT_FOR_SELECTION"
        )
    frame["test_end"] = pd.to_datetime(frame["test_end"], errors="raise").dt.date
    mapping: dict[str, str] = {}
    for regime, values in frame.groupby("regime_state", sort=True):
        latest = values.sort_values(
            ["test_end", "walk_forward_fold_id"]
        ).iloc[-1]
        mapping[str(regime)] = str(latest["selected_strategy_variant_id"])
    for regime in RegimeState:
        mapping.setdefault(regime.value, "NO_TRADE")
    return mapping


def _transport_fold(
    featured: pd.DataFrame,
    *,
    policy: Pre2016ExternalValidationPolicy,
) -> WalkForwardFold:
    sessions = tuple(sorted(featured["trading_date"].unique()))
    if len(sessions) < 504:
        raise Pre2016ExternalValidationError(
            "INSUFFICIENT_PRE2016_SESSIONS_FOR_TRANSPORT"
        )
    train_end = sessions[min(251, len(sessions) - 3)]
    validation_start = sessions[min(252, len(sessions) - 2)]
    validation_end = sessions[min(503, len(sessions) - 2)]
    test_start_index = min(504, len(sessions) - 1)
    test_start = sessions[test_start_index]
    if test_start >= policy.external_end:
        raise Pre2016ExternalValidationError(
            "NO_PRE2016_EXTERNAL_TRANSPORT_WINDOW"
        )
    return WalkForwardFold(
        walk_forward_fold_id="PRE2016-FROZEN-TRANSPORT",
        train_start=sessions[0],
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        test_start=test_start,
        test_end=sessions[-1],
    )


def _transport_selection_rows(
    fold: WalkForwardFold,
    *,
    frozen_mapping: Mapping[str, str],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "walk_forward_fold_id": fold.walk_forward_fold_id,
            "selection_scope": f"REGIME:{regime.value}",
            "selected": True,
            "selected_strategy_variant_id": frozen_mapping.get(
                regime.value, "NO_TRADE"
            ),
            "outer_test_used_for_selection": False,
            "eligible": True,
            "objective_score": None,
            "complexity_score": 0,
            "strategy_variant_id": frozen_mapping.get(
                regime.value, "NO_TRADE"
            ),
            "selection_data_end": "SIGNED_DSI007_LATEST_FOLD",
            "test_start": fold.test_start,
            "test_end": fold.test_end,
        }
        for regime in RegimeState
    )


def _apply_frozen_structural_stop(
    selected: pd.DataFrame,
    *,
    slippage_fraction: float,
) -> pd.DataFrame:
    if selected.empty:
        return selected.copy()
    if "support10" not in selected.columns:
        raise Pre2016ExternalValidationError(
            "POINT_IN_TIME_STRUCTURAL_SUPPORT_UNAVAILABLE"
        )
    challenger = selected.copy()
    challenger["incumbent_initial_stop"] = challenger["initial_stop"]
    challenger["initial_stop"] = challenger.apply(
        lambda row: _structural_stop_level(
            row,
            slippage_fraction=slippage_fraction,
        ),
        axis=1,
    )
    invalid = (
        challenger["initial_stop"].isna()
        | (challenger["initial_stop"].astype(float) <= 0)
        | (
            challenger["initial_stop"].astype(float)
            >= challenger["raw_entry_price"].astype(float)
            * (1.0 + slippage_fraction)
        )
    )
    if invalid.any():
        challenger = challenger.loc[~invalid].copy()
    challenger["frozen_stop_candidate_id"] = DSI010_FROZEN_CHALLENGER_ID
    challenger["external_data_used_for_stop_selection"] = False
    return challenger


def _structural_stop_level(
    row: pd.Series[Any],
    *,
    slippage_fraction: float,
) -> float:
    entry = float(row["raw_entry_price"]) * (1.0 + slippage_fraction)
    incumbent = float(row["initial_stop"])
    support = _optional_float(row.get("support10"))
    level = incumbent if support is None else support
    return round(max(0.01, min(level, entry - 0.01)), 8)


def _benchmark_metrics(
    benchmark: pd.DataFrame | None,
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    if benchmark is None or benchmark.empty:
        return {
            "portfolio_name": _BENCHMARK_PORTFOLIO,
            "available": False,
            "start_date": None,
            "end_date": None,
            "starting_value": None,
            "ending_value": None,
            "net_cagr": None,
            "cumulative_return": None,
        }
    frame = benchmark.loc[
        benchmark["trading_date"].between(start, end)
    ].sort_values("trading_date")
    if len(frame) < 2:
        return {
            "portfolio_name": _BENCHMARK_PORTFOLIO,
            "available": False,
            "start_date": None,
            "end_date": None,
            "starting_value": None,
            "ending_value": None,
            "net_cagr": None,
            "cumulative_return": None,
        }
    first = frame.iloc[0]
    last = frame.iloc[-1]
    years = max(
        (last["trading_date"] - first["trading_date"]).days / 365.2425,
        1 / 365.2425,
    )
    start_value = float(first["benchmark_value"])
    end_value = float(last["benchmark_value"])
    cumulative = end_value / start_value - 1.0
    cagr = (end_value / start_value) ** (1.0 / years) - 1.0
    return {
        "portfolio_name": _BENCHMARK_PORTFOLIO,
        "available": True,
        "start_date": first["trading_date"],
        "end_date": last["trading_date"],
        "years": round(years, 8),
        "starting_value": round(start_value, 8),
        "ending_value": round(end_value, 8),
        "net_cagr": round(cagr, 8),
        "cumulative_return": round(cumulative, 8),
    }


def _transport_metric_rows(
    *,
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    benchmark: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    rows = [
        {"test_scope": "FROZEN_POLICY_TRANSPORT", **dict(incumbent)},
        {"test_scope": "FROZEN_POLICY_TRANSPORT", **dict(challenger)},
        {"test_scope": "FROZEN_POLICY_TRANSPORT", **dict(benchmark)},
    ]
    return tuple(rows)


def _benchmark_relative_rows(
    metrics: Sequence[Mapping[str, Any]],
    *,
    benchmark: Mapping[str, Any],
) -> list[dict[str, Any]]:
    benchmark_cagr = _optional_float(benchmark.get("net_cagr"))
    rows: list[dict[str, Any]] = []
    for metric in metrics:
        name = str(metric.get("portfolio_name"))
        portfolio_cagr = _optional_float(metric.get("net_cagr"))
        excess = (
            None
            if benchmark_cagr is None or portfolio_cagr is None
            else portfolio_cagr - benchmark_cagr
        )
        rows.append(
            {
                "test_scope": str(metric.get("test_scope")),
                "portfolio_name": name,
                "benchmark_name": "NIFTY_500_TRI",
                "portfolio_cagr": portfolio_cagr,
                "benchmark_cagr": benchmark_cagr,
                "excess_cagr": _optional_round(excess),
                "benchmark_available": benchmark_cagr is not None,
            }
        )
    return rows


def _stop_difference_rows(
    *,
    incumbent: Sequence[Mapping[str, Any]],
    challenger: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    def key(row: Mapping[str, Any]) -> tuple[str, str]:
        return (str(row.get("symbol")), str(row.get("signal_date")))

    incumbent_by_key = {key(row): row for row in incumbent}
    challenger_by_key = {key(row): row for row in challenger}
    rows: list[dict[str, Any]] = []
    for trade_key in sorted(set(incumbent_by_key) | set(challenger_by_key)):
        base = incumbent_by_key.get(trade_key)
        candidate = challenger_by_key.get(trade_key)
        rows.append(
            {
                "symbol": trade_key[0],
                "signal_date": trade_key[1],
                "incumbent_present": base is not None,
                "challenger_present": candidate is not None,
                "incumbent_exit_reason": None
                if base is None
                else base.get("exit_reason"),
                "challenger_exit_reason": None
                if candidate is None
                else candidate.get("exit_reason"),
                "incumbent_net_return": None
                if base is None
                else base.get("net_return"),
                "challenger_net_return": None
                if candidate is None
                else candidate.get("net_return"),
                "net_return_delta": _difference(
                    None if candidate is None else candidate.get("net_return"),
                    None if base is None else base.get("net_return"),
                ),
                "only_stop_policy_changed_before_portfolio_divergence": True,
            }
        )
    return rows


def _equity_rows(
    *,
    incumbent: Sequence[Mapping[str, Any]],
    challenger: Sequence[Mapping[str, Any]],
    benchmark: pd.DataFrame | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, curve in (
        (_FROZEN_INCUMBENT, incumbent),
        (_FROZEN_CHALLENGER, challenger),
    ):
        for row in curve:
            rows.append({"portfolio_name": name, **dict(row)})
    if benchmark is not None and not benchmark.empty:
        first = float(benchmark.iloc[0]["benchmark_value"])
        for item in benchmark.itertuples(index=False):
            rows.append(
                {
                    "portfolio_name": _BENCHMARK_PORTFOLIO,
                    "observed_on": item.trading_date,
                    "portfolio_value": round(
                        1_000_000.0 * float(item.benchmark_value) / first,
                        8,
                    ),
                    "daily_return": None,
                    "drawdown": None,
                    "cash": None,
                    "open_position_value": None,
                    "gross_exposure": None,
                    "net_exposure": None,
                    "realised_pnl": None,
                    "unrealised_pnl": None,
                    "cumulative_costs": 0.0,
                    "open_positions": 0,
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            str(row["portfolio_name"]),
            str(row["observed_on"]),
        ),
    )


def _calendar_performance(
    equity_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(equity_rows)
    if frame.empty:
        return []
    frame["observed_on"] = pd.to_datetime(frame["observed_on"], errors="coerce")
    frame = frame.dropna(subset=["observed_on", "portfolio_value"])
    frame["calendar_year"] = frame["observed_on"].dt.year
    rows: list[dict[str, Any]] = []
    for (portfolio, year), values in frame.groupby(
        ["portfolio_name", "calendar_year"],
        sort=True,
    ):
        values = values.sort_values("observed_on")
        start_value = float(values.iloc[0]["portfolio_value"])
        end_value = float(values.iloc[-1]["portfolio_value"])
        rows.append(
            {
                "portfolio_name": portfolio,
                "calendar_year": int(year),
                "start_value": round(start_value, 8),
                "end_value": round(end_value, 8),
                "return": round(end_value / start_value - 1.0, 8),
            }
        )
    return rows


def _regime_performance(
    trades: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade.get("regime_state") or "UNKNOWN")].append(trade)
    for regime, values in sorted(grouped.items()):
        returns = [float(item["net_return"]) for item in values]
        pnl = [float(item["net_pnl"]) for item in values]
        rows.append(
            {
                "regime_state": regime,
                "trade_count": len(values),
                "win_rate": round(
                    sum(item > 0 for item in returns) / len(values),
                    8,
                ),
                "expectancy": round(mean(returns), 8),
                "net_pnl": round(sum(pnl), 8),
            }
        )
    return rows


def _concentration(
    trades: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], float | None]:
    if not trades:
        return [], None
    by_symbol: dict[str, dict[str, float]] = defaultdict(
        lambda: {"trade_count": 0.0, "net_pnl": 0.0}
    )
    positive_total = sum(max(0.0, float(item["net_pnl"])) for item in trades)
    for trade in trades:
        member = by_symbol[str(trade["symbol"])]
        member["trade_count"] += 1
        member["net_pnl"] += float(trade["net_pnl"])
    rows = [
        {
            "dimension": "SECURITY",
            "member": symbol,
            "trade_count": int(values["trade_count"]),
            "net_pnl": round(values["net_pnl"], 8),
            "share_of_positive_pnl": None
            if positive_total <= 0
            else round(max(0.0, values["net_pnl"]) / positive_total, 8),
        }
        for symbol, values in sorted(by_symbol.items())
    ]
    positive = sorted(
        (max(0.0, float(item["net_pnl"])) for item in trades),
        reverse=True,
    )
    top_five_share = (
        None
        if positive_total <= 0
        else round(sum(positive[:5]) / positive_total, 8)
    )
    rows.append(
        {
            "dimension": "TOP_FIVE_TRADES",
            "member": "TOP_FIVE",
            "trade_count": min(5, len(trades)),
            "net_pnl": round(sum(positive[:5]), 8),
            "share_of_positive_pnl": top_five_share,
        }
    )
    return rows, top_five_share


def _robustness(
    *,
    featured: pd.DataFrame,
    selected: pd.DataFrame,
    fold: WalkForwardFold,
    policy: TournamentPolicy,
    incumbent_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    scenarios = {
        "BASE_FROZEN_CHALLENGER": policy,
        "HIGHER_COSTS": replace(
            policy,
            transaction_cost_fraction=policy.transaction_cost_fraction * 1.5,
        ),
        "HIGHER_SLIPPAGE": replace(
            policy,
            slippage_fraction=policy.slippage_fraction * 1.5,
        ),
        "REDUCED_POSITIONS": replace(
            policy,
            maximum_positions=max(1, policy.maximum_positions - 1),
        ),
        "LOWER_LIQUIDITY_CAPACITY": replace(
            policy,
            maximum_market_volume_fraction=(
                policy.maximum_market_volume_fraction / 2.0
            ),
        ),
    }
    rows: list[dict[str, Any]] = []
    for scenario, scenario_policy in scenarios.items():
        simulation = _simulate_portfolio(
            name=f"{_FROZEN_CHALLENGER}:{scenario}",
            featured=featured,
            selected_signals=selected,
            start=fold.test_start,
            end=fold.test_end,
            policy=scenario_policy,
        )
        metrics = _portfolio_metrics(
            name=f"{_FROZEN_CHALLENGER}:{scenario}",
            curve=simulation["curve"],
            trades=simulation["trades"],
            policy=scenario_policy,
        )
        rows.append(
            {
                "scenario": scenario,
                "net_cagr": metrics.get("net_cagr"),
                "maximum_drawdown": metrics.get("maximum_drawdown"),
                "trade_count": metrics.get("trade_count"),
                "incumbent_cagr": incumbent_metrics.get("net_cagr"),
                "directionally_better_than_incumbent": (
                    _optional_float(metrics.get("net_cagr")) is not None
                    and _optional_float(incumbent_metrics.get("net_cagr"))
                    is not None
                    and float(metrics["net_cagr"])
                    > float(incumbent_metrics["net_cagr"])
                ),
            }
        )
    delayed = _delay_selected_signals(selected, featured)
    delayed_simulation = _simulate_portfolio(
        name=f"{_FROZEN_CHALLENGER}:ONE_SESSION_DELAY",
        featured=featured,
        selected_signals=delayed,
        start=fold.test_start,
        end=fold.test_end,
        policy=policy,
    )
    delayed_metrics = _portfolio_metrics(
        name=f"{_FROZEN_CHALLENGER}:ONE_SESSION_DELAY",
        curve=delayed_simulation["curve"],
        trades=delayed_simulation["trades"],
        policy=policy,
    )
    rows.append(
        {
            "scenario": "ONE_SESSION_DELAY",
            "net_cagr": delayed_metrics.get("net_cagr"),
            "maximum_drawdown": delayed_metrics.get("maximum_drawdown"),
            "trade_count": delayed_metrics.get("trade_count"),
            "incumbent_cagr": incumbent_metrics.get("net_cagr"),
            "directionally_better_than_incumbent": (
                _optional_float(delayed_metrics.get("net_cagr")) is not None
                and _optional_float(incumbent_metrics.get("net_cagr")) is not None
                and float(delayed_metrics["net_cagr"])
                > float(incumbent_metrics["net_cagr"])
            ),
        }
    )
    return rows


def _classification(
    *,
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    top_five_profit_share: float | None,
    policy: Pre2016ExternalValidationPolicy,
) -> ExternalValidationClassification:
    trade_count = int(challenger.get("trade_count") or 0)
    if trade_count < policy.minimum_external_trades:
        return ExternalValidationClassification.INSUFFICIENT_SAMPLE
    if (
        top_five_profit_share is not None
        and top_five_profit_share > policy.maximum_top_five_profit_share
    ):
        return ExternalValidationClassification.HIGH_CONCENTRATION
    incumbent_cagr = _optional_float(incumbent.get("net_cagr"))
    challenger_cagr = _optional_float(challenger.get("net_cagr"))
    benchmark_cagr = _optional_float(benchmark.get("net_cagr"))
    incumbent_drawdown = _optional_float(incumbent.get("maximum_drawdown"))
    challenger_drawdown = _optional_float(challenger.get("maximum_drawdown"))
    if incumbent_cagr is None or challenger_cagr is None:
        return ExternalValidationClassification.FAILED
    drawdown_preserved = (
        incumbent_drawdown is None
        or challenger_drawdown is None
        or challenger_drawdown >= incumbent_drawdown - 0.02
    )
    if challenger_cagr > incumbent_cagr and drawdown_preserved:
        if benchmark_cagr is not None and challenger_cagr > benchmark_cagr:
            return ExternalValidationClassification.BEATS_BENCHMARK
        if benchmark_cagr is not None:
            return ExternalValidationClassification.BEATS_INCUMBENT_NOT_BENCHMARK
        return ExternalValidationClassification.DIRECTIONALLY_SUPPORTED
    if challenger_cagr > 0 and challenger_cagr >= incumbent_cagr * 0.95:
        return ExternalValidationClassification.MIXED
    return ExternalValidationClassification.FAILED


def _population_reconciliation(
    *,
    market: pd.DataFrame,
    signals: pd.DataFrame,
    selected: pd.DataFrame,
    challenger_selected: pd.DataFrame,
    incumbent_simulation: Mapping[str, Any],
    challenger_simulation: Mapping[str, Any],
    independent_trades: pd.DataFrame,
) -> list[dict[str, Any]]:
    units = (
        ("MARKET_ROWS", len(market), len(market)),
        ("GENERATED_SIGNALS", len(signals), len(signals)),
        ("FROZEN_POLICY_SIGNALS", len(selected), len(selected)),
        (
            "CHALLENGER_SIGNALS",
            len(selected),
            len(challenger_selected),
        ),
        (
            "INCUMBENT_TRADES",
            len(incumbent_simulation["trades"]),
            len(incumbent_simulation["trades"]),
        ),
        (
            "CHALLENGER_TRADES",
            len(challenger_simulation["trades"]),
            len(challenger_simulation["trades"]),
        ),
        (
            "INDEPENDENT_VARIANT_TRADES",
            len(independent_trades),
            len(independent_trades),
        ),
    )
    return [
        {
            "unit": unit,
            "source_count": source_count,
            "admitted_count": admitted_count,
            "excluded_count": source_count - admitted_count,
            "reconciles": admitted_count <= source_count,
        }
        for unit, source_count, admitted_count in units
    ]


def _non_vacuity_probes(
    policy: Pre2016ExternalValidationPolicy,
) -> list[dict[str, Any]]:
    probes = (
        (
            "NO_2016_OVERLAP",
            policy.external_end < date(2016, 1, 1),
            "The external era ends before the DSI-007 discovery period.",
        ),
        (
            "FROZEN_CHALLENGER_ID",
            policy.frozen_challenger_id == DSI010_FROZEN_CHALLENGER_ID,
            "Only the signed STOP-STRUCTURAL-10D candidate is transported.",
        ),
        (
            "NO_EXTERNAL_TUNING",
            True,
            "External prices evaluate the frozen rules but never select them.",
        ),
        (
            "PRODUCTION_DISABLED",
            not any(governance_flags().values()),
            "All production and policy influence flags remain false.",
        ),
    )
    return [
        {
            "probe_id": probe_id,
            "probe_name": probe_id.replace("_", " ").title(),
            "accepted": accepted,
            "explanation": explanation,
            "empirical_population": False,
        }
        for probe_id, accepted, explanation in probes
    ]


def _readiness(
    *,
    source_summary: Mapping[str, Any],
    benchmark_rows: Sequence[Mapping[str, Any]],
    selected: pd.DataFrame,
    incumbent_metrics: Mapping[str, Any],
    challenger_metrics: Mapping[str, Any],
    replication: Any,
    classification: ExternalValidationClassification,
) -> tuple[dict[str, str], list[str]]:
    blockers: list[str] = []
    benchmark_status = (
        str(benchmark_rows[0].get("status")) if benchmark_rows else "UNAVAILABLE"
    )
    source_sessions = int(source_summary.get("admitted_sessions") or 0)
    readiness = {
        "A": "READY_FOR_PRE2016_EXTERNAL_VALIDATION",
        "B": (
            "READY_FOR_GOVERNED_PRE2016_MARKET_REPLAY"
            if source_sessions >= 1000
            else "READY_WITH_PARTIAL_PRE2016_COVERAGE"
        ),
        "C": "READY_FOR_GOVERNED_PRE2016_POINT_IN_TIME_UNIVERSE",
        "D": (
            "READY_FOR_GOVERNED_PRE2016_TRI_COMPARISON"
            if benchmark_status == "AVAILABLE_TOTAL_RETURN"
            else "READY_WITH_PARTIAL_TRI_COVERAGE"
        ),
        "E": (
            "READY_FOR_GOVERNED_FROZEN_STOP_EXTERNAL_TEST"
            if not selected.empty
            else "READY_WITH_ZERO_EXTERNAL_TRADES"
        ),
        "F": str(
            replication.readiness.get(
                "J", "READY_WITH_NO_GENERALISABLE_STRATEGY"
            )
        ),
        "G": "READY_FOR_GOVERNED_PRE2016_PERFORMANCE_COMPARISON",
        "H": (
            "READY_FOR_GOVERNED_EXTERNAL_VALIDITY_CONCLUSION"
            if classification
            not in {
                ExternalValidationClassification.FAILED,
                ExternalValidationClassification.INSUFFICIENT_SAMPLE,
            }
            else (
                "READY_WITH_EXTERNAL_REJECTION"
                if classification is ExternalValidationClassification.FAILED
                else "READY_WITH_MIXED_EXTERNAL_EVIDENCE"
            )
        ),
    }
    final = {
        ExternalValidationClassification.BEATS_BENCHMARK: (
            "READY_FOR_EXTENDED_FORWARD_PAPER_VALIDATION"
        ),
        ExternalValidationClassification.PASSED: (
            "READY_FOR_EXTENDED_FORWARD_PAPER_VALIDATION"
        ),
        ExternalValidationClassification.DIRECTIONALLY_SUPPORTED: (
            "READY_WITH_DIRECTIONAL_EXTERNAL_SUPPORT"
        ),
        ExternalValidationClassification.BEATS_INCUMBENT_NOT_BENCHMARK: (
            "READY_WITH_DIRECTIONAL_EXTERNAL_SUPPORT"
        ),
        ExternalValidationClassification.MIXED: (
            "READY_WITH_MIXED_EXTERNAL_EVIDENCE"
        ),
        ExternalValidationClassification.FAILED: "READY_WITH_CHALLENGER_REJECTED",
        ExternalValidationClassification.INSUFFICIENT_SAMPLE: (
            "READY_WITH_MIXED_EXTERNAL_EVIDENCE"
        ),
        ExternalValidationClassification.HIGH_CONCENTRATION: (
            "READY_WITH_MIXED_EXTERNAL_EVIDENCE"
        ),
        ExternalValidationClassification.REGIME_DEPENDENT: (
            "READY_WITH_MIXED_EXTERNAL_EVIDENCE"
        ),
    }[classification]
    readiness["I"] = final
    if source_sessions == 0:
        blockers.append("BLOCKED_BY_INSUFFICIENT_PRE2016_DATA")
    if benchmark_status == "UNAVAILABLE":
        blockers.append("BLOCKED_BY_BENCHMARK_DEFECT")
    if _optional_float(incumbent_metrics.get("net_cagr")) is None:
        blockers.append("BLOCKED_BY_EXTERNAL_REPLAY_DEFECT")
    if _optional_float(challenger_metrics.get("net_cagr")) is None:
        blockers.append("BLOCKED_BY_EXTERNAL_REPLAY_DEFECT")
    return readiness, sorted(set(blockers))


def _selected_signal_rows(
    selected: pd.DataFrame,
    portfolio_name: str,
) -> list[dict[str, Any]]:
    if selected.empty:
        return []
    columns = (
        "signal_id",
        "identity_key",
        "symbol",
        "trading_date",
        "entry_eligibility_date",
        "strategy_variant_id",
        "strategy_family",
        "regime",
        "signal_strength",
        "raw_entry_price",
        "initial_stop",
        "target_1",
        "target_2",
        "target_3",
        "support10",
        "average_traded_value20",
    )
    rows: list[dict[str, Any]] = []
    for raw in selected.to_dict(orient="records"):
        rows.append(
            {
                "portfolio_name": portfolio_name,
                **{column: raw.get(column) for column in columns},
                "external_data_used_for_rule_selection": False,
            }
        )
    return rows


def _benchmark_gap_closed(
    *,
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    benchmark: Mapping[str, Any],
) -> float | None:
    incumbent_cagr = _optional_float(incumbent.get("net_cagr"))
    challenger_cagr = _optional_float(challenger.get("net_cagr"))
    benchmark_cagr = _optional_float(benchmark.get("net_cagr"))
    if (
        incumbent_cagr is None
        or challenger_cagr is None
        or benchmark_cagr is None
    ):
        return None
    original_gap = benchmark_cagr - incumbent_cagr
    if original_gap <= 0:
        return 1.0
    return round((challenger_cagr - incumbent_cagr) / original_gap, 8)


def _metric_by_name(
    metrics: Sequence[Mapping[str, Any]],
    name: str,
) -> dict[str, Any] | None:
    matches = [
        dict(row)
        for row in metrics
        if str(row.get("portfolio_name")) == name
    ]
    return matches[0] if len(matches) == 1 else None


def _difference(left: object, right: object) -> float | None:
    left_value = _optional_float(left)
    right_value = _optional_float(right)
    if left_value is None or right_value is None:
        return None
    return round(left_value - right_value, 8)


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_round(value: object) -> float | None:
    number = _optional_float(value)
    return None if number is None else round(number, 8)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


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
    "GovernedPre2016ExternalValidationEngine",
    "governance_flags",
]
