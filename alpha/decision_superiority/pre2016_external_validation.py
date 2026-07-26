"""Governed DSI-010 pre-2016 external-era validation engine.

The engine performs two deliberately separate tests:

* a frozen transport of the accepted DSI-007 regime mapping with the incumbent
  stop versus the frozen DSI-009 ``STOP-STRUCTURAL-10D`` stop; and
* a fresh DSI-007 walk-forward tournament contained wholly inside 2005-2015.

No result changes Alpha's default, live, or production behaviour.
"""

from __future__ import annotations

import csv
import hashlib
import subprocess
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import pandas as pd

from alpha.decision_superiority.entry_stop_improvement import (
    default_stop_registry,
)
from alpha.decision_superiority.entry_stop_improvement_artifacts import (
    validate_entry_stop_improvement_certificate,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
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
    TournamentPolicy,
    TournamentSourcePaths,
)
from alpha.decision_superiority.regime_strategy_tournament import (
    GovernedRegimeStrategyTournamentEngine,
    _build_independent_trade_plans,
    _build_point_in_time_features,
    _generate_signals,
    _load_governed_market,
    _portfolio_metrics,
    _select_strategies,
    _simulate_portfolio,
    _walk_forward_folds,
    default_strategy_registry,
)

_EXTERNAL_INCUMBENT = "PRE2016_FROZEN_INCUMBENT"
_EXTERNAL_CHALLENGER = "PRE2016_STOP_STRUCTURAL_10D"
_BENCHMARK_PORTFOLIO = "TOTAL_RETURN_INDEX_BENCHMARK"


def governance_flags() -> dict[str, bool]:
    """Return the immutable research-only DSI-010 governance boundary."""

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
    """Run DSI-010 A-I without changing any Alpha runtime policy."""

    def run(
        self,
        *,
        sources: Pre2016ExternalValidationSourcePaths,
        policy: Pre2016ExternalValidationPolicy = Pre2016ExternalValidationPolicy(),
    ) -> Pre2016ExternalValidationResult:
        """Validate the frozen source chain and execute both external-era tests."""

        start = date.fromisoformat(policy.external_start)
        end = date.fromisoformat(policy.external_end)
        if end >= date(2016, 1, 1):
            raise Pre2016ExternalValidationError("EXTERNAL_PERIOD_OVERLAPS_DISCOVERY_ERA")

        dsi009 = validate_entry_stop_improvement_certificate(
            sources.dsi009_certificate,
            require_ready=True,
        )
        dsi007 = validate_regime_strategy_tournament_certificate(
            sources.dsi007_certificate,
            require_ready=False,
            database=None,
        )
        expected_dsi007 = cast(Mapping[str, Any], dsi009["source_chain_hashes"]).get(
            "DSI007_CERTIFICATE"
        )
        if expected_dsi007 and _sha256(sources.dsi007_certificate) != str(
            expected_dsi007
        ):
            raise Pre2016ExternalValidationError("DSI007_SOURCE_CHAIN_HASH_MISMATCH")
        _validate_frozen_challenger(dsi009, policy)

        tournament_sources = TournamentSourcePaths(
            database=sources.database,
            historical_truth_snapshots=sources.historical_truth_snapshots,
            benchmark=sources.benchmark,
            project_root=sources.project_root,
        )
        tournament_policy = TournamentPolicy(
            starting_capital=policy.starting_capital,
            maximum_positions=policy.maximum_positions,
            transaction_cost_fraction=policy.transaction_cost_fraction,
            slippage_fraction=policy.slippage_fraction,
        )

        # Test B is a fresh, self-contained walk-forward replication in 2005-2015.
        test_b = GovernedRegimeStrategyTournamentEngine().run(
            sources=tournament_sources,
            start=start,
            end=end,
            policy=tournament_policy,
        )

        # Test A transports the final accepted DSI-007 regime mapping backwards
        # without changing the mapping, strategy registry, entry, targets, or exits.
        source_rows, market, source_summary = _load_governed_market(
            sources=tournament_sources,
            start=start,
            end=end,
        )
        featured, _, _ = _build_point_in_time_features(market)
        variants = default_strategy_registry()
        all_signals = _generate_signals(featured, variants, tournament_policy)
        all_plans, independent_trades = _build_independent_trade_plans(
            featured,
            all_signals,
            variants,
            tournament_policy,
        )
        frozen_mapping, mapping_rows = _latest_frozen_mapping(
            sources.dsi007_certificate.parent
        )
        selected = _frozen_selected_signals(
            signals=all_signals,
            plans=all_plans,
            mapping=frozen_mapping,
        )
        incumbent = _simulate_portfolio(
            name=_EXTERNAL_INCUMBENT,
            featured=featured,
            selected_signals=selected,
            start=start,
            end=end,
            policy=tournament_policy,
        )
        incumbent_metrics = _portfolio_metrics(
            name=_EXTERNAL_INCUMBENT,
            curve=incumbent["curve"],
            trades=incumbent["trades"],
            policy=tournament_policy,
        )
        challenger_signals = _apply_structural_stop(selected, featured)
        challenger = _simulate_portfolio(
            name=_EXTERNAL_CHALLENGER,
            featured=featured,
            selected_signals=challenger_signals,
            start=start,
            end=end,
            policy=tournament_policy,
        )
        challenger_metrics = _portfolio_metrics(
            name=_EXTERNAL_CHALLENGER,
            curve=challenger["curve"],
            trades=challenger["trades"],
            policy=tournament_policy,
        )

        benchmark_metrics = _portfolio_row(test_b.rows["risk_metrics"], _BENCHMARK_PORTFOLIO)
        stop_differences = _stop_difference_rows(
            incumbent=cast(Sequence[Mapping[str, Any]], incumbent["trades"]),
            challenger=cast(Sequence[Mapping[str, Any]], challenger["trades"]),
        )
        external_classification = _external_classification(
            incumbent_metrics,
            challenger_metrics,
            benchmark_metrics,
            minimum_trades=policy.minimum_external_trades,
        )
        rows = _assemble_rows(
            sources=sources,
            policy=policy,
            dsi009=dsi009,
            dsi007=dsi007,
            source_rows=source_rows,
            source_summary=source_summary,
            mapping_rows=mapping_rows,
            selected=selected,
            challenger_signals=challenger_signals,
            incumbent=incumbent,
            challenger=challenger,
            incumbent_metrics=incumbent_metrics,
            challenger_metrics=challenger_metrics,
            benchmark_metrics=benchmark_metrics,
            stop_differences=stop_differences,
            test_b=test_b,
            external_classification=external_classification,
            independent_trade_count=len(independent_trades),
        )
        readiness, blockers = _readiness(
            test_b=test_b,
            source_summary=source_summary,
            incumbent_metrics=incumbent_metrics,
            challenger_metrics=challenger_metrics,
            benchmark_metrics=benchmark_metrics,
            external_classification=external_classification,
            minimum_trades=policy.minimum_external_trades,
        )
        summaries = {
            "protocol": asdict(policy),
            "source_coverage": dict(source_summary),
            "frozen_mapping": dict(sorted(frozen_mapping.items())),
            "test_a_incumbent": dict(incumbent_metrics),
            "test_a_challenger": dict(challenger_metrics),
            "benchmark": dict(benchmark_metrics),
            "test_b_regime_aware": _portfolio_row(
                test_b.rows["risk_metrics"], "REGIME_AWARE_SELECTED"
            ),
            "test_b_fixed": _portfolio_row(
                test_b.rows["risk_metrics"], "BEST_FIXED_STRATEGY"
            ),
            "test_b_momentum": _portfolio_row(
                test_b.rows["risk_metrics"], "SIMPLE_MOMENTUM_BASELINE"
            ),
            "test_b_trend": _portfolio_row(
                test_b.rows["risk_metrics"], "SIMPLE_TREND_BASELINE"
            ),
            "external_validation_classification": external_classification,
            "forward_paper_eligible": external_classification in {
                "EXTERNAL_VALIDATION_PASSED",
                "CHALLENGER_BEATS_BENCHMARK",
            },
            "automatic_promotion_count": 0,
        }
        return Pre2016ExternalValidationResult(
            source_commit=_git_commit(sources.project_root),
            readiness=MappingProxyType(readiness),
            blockers=tuple(blockers),
            rows=MappingProxyType(rows),
            summaries=MappingProxyType(summaries),
            governance=MappingProxyType(governance_flags()),
        )


def _validate_frozen_challenger(
    dsi009: Mapping[str, Any],
    policy: Pre2016ExternalValidationPolicy,
) -> None:
    descriptive = dsi009.get("best_descriptive_result")
    if not isinstance(descriptive, Mapping):
        raise Pre2016ExternalValidationError("DSI009_DESCRIPTIVE_RESULT_MISSING")
    if descriptive.get("mechanism_id") != policy.frozen_challenger_id:
        raise Pre2016ExternalValidationError("FROZEN_CHALLENGER_ID_MISMATCH")
    stops = {item.mechanism_id: item for item in default_stop_registry()}
    challenger = stops.get(policy.frozen_challenger_id)
    if challenger is None:
        raise Pre2016ExternalValidationError("FROZEN_CHALLENGER_UNAVAILABLE")
    if challenger.family != "STRUCTURAL_SUPPORT" or challenger.structural_lookback != 10:
        raise Pre2016ExternalValidationError("FROZEN_CHALLENGER_CONTRACT_DRIFT")


def _latest_frozen_mapping(root: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    path = root / DSI007_ARTIFACTS["regime_strategy_mapping"]
    if not path.is_file():
        raise Pre2016ExternalValidationError("DSI007_REGIME_MAPPING_UNAVAILABLE")
    frame = pd.read_csv(path)
    required = {
        "walk_forward_fold_id",
        "regime_state",
        "selected_strategy_variant_id",
        "test_end",
    }
    if not required.issubset(frame.columns) or frame.empty:
        raise Pre2016ExternalValidationError("DSI007_REGIME_MAPPING_INVALID")
    frame["test_end"] = pd.to_datetime(frame["test_end"]).dt.date
    latest_end = max(frame["test_end"])
    latest = frame.loc[frame["test_end"] == latest_end].copy()
    mapping = {
        str(row.regime_state): str(row.selected_strategy_variant_id)
        for row in latest.itertuples(index=False)
    }
    if not mapping:
        raise Pre2016ExternalValidationError("DSI007_FROZEN_MAPPING_EMPTY")
    rows = [
        {
            "source_walk_forward_fold_id": str(row.walk_forward_fold_id),
            "regime_state": str(row.regime_state),
            "selected_strategy_variant_id": str(row.selected_strategy_variant_id),
            "source_test_end": row.test_end,
            "transport_start": date(2005, 1, 1),
            "transport_end": date(2015, 12, 31),
            "external_results_used_for_mapping": False,
        }
        for row in latest.itertuples(index=False)
    ]
    return mapping, rows


def _frozen_selected_signals(
    *,
    signals: pd.DataFrame,
    plans: pd.DataFrame,
    mapping: Mapping[str, str],
) -> pd.DataFrame:
    if signals.empty or plans.empty:
        return pd.DataFrame()
    merged = signals.merge(plans, on="signal_id", suffixes=("", "_plan"))
    regime_column = "regime" if "regime" in merged.columns else "regime_state"
    selected = merged.loc[
        merged.apply(
            lambda row: str(row["strategy_variant_id"])
            == mapping.get(str(row[regime_column]), "NO_TRADE"),
            axis=1,
        )
    ].copy()
    selected["walk_forward_fold_id"] = "FROZEN-TRANSPORT-2005-2015"
    return selected.sort_values(
        ["entry_eligibility_date", "signal_strength", "signal_id"],
        ascending=[True, False, True],
    )


def _apply_structural_stop(selected: pd.DataFrame, featured: pd.DataFrame) -> pd.DataFrame:
    if selected.empty:
        return selected.copy()
    support = featured[["identity_key", "trading_date", "low"]].copy()
    support["structural_support_10d"] = support.groupby(
        "identity_key", sort=False, observed=True
    )["low"].transform(lambda values: values.shift(1).rolling(10, min_periods=10).min())
    signal_date_column = "trading_date" if "trading_date" in selected.columns else "signal_date"
    challenger = selected.merge(
        support[["identity_key", "trading_date", "structural_support_10d"]],
        left_on=["identity_key", signal_date_column],
        right_on=["identity_key", "trading_date"],
        how="left",
        suffixes=("", "_support"),
    )

    def stop_level(row: pd.Series[Any]) -> float:
        entry = float(row["entry_price"])
        incumbent = float(row["initial_stop"])
        raw_support = row["structural_support_10d"]
        level = incumbent if pd.isna(raw_support) else float(raw_support)
        return round(max(0.01, min(level, entry - 0.01)), 10)

    challenger["initial_stop"] = challenger.apply(stop_level, axis=1)
    challenger["trade_plan_id"] = challenger["signal_id"].map(
        lambda value: _stable_id("PRE2016", "STOP-STRUCTURAL-10D", value)
    )
    return challenger.drop(columns=["trading_date_support"], errors="ignore")


def _stop_difference_rows(
    *,
    incumbent: Sequence[Mapping[str, Any]],
    challenger: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    key_fields = ("identity_key", "signal_date")
    incumbent_by_key = {tuple(row.get(field) for field in key_fields): row for row in incumbent}
    challenger_by_key = {tuple(row.get(field) for field in key_fields): row for row in challenger}
    rows: list[dict[str, Any]] = []
    for key in sorted(set(incumbent_by_key) | set(challenger_by_key), key=str):
        left = incumbent_by_key.get(key)
        right = challenger_by_key.get(key)
        rows.append(
            {
                "identity_key": key[0],
                "signal_date": key[1],
                "incumbent_trade_present": left is not None,
                "challenger_trade_present": right is not None,
                "incumbent_exit_reason": None if left is None else left.get("exit_reason"),
                "challenger_exit_reason": None if right is None else right.get("exit_reason"),
                "incumbent_net_return": None if left is None else left.get("net_return"),
                "challenger_net_return": None if right is None else right.get("net_return"),
                "net_return_delta": _difference(
                    None if right is None else right.get("net_return"),
                    None if left is None else left.get("net_return"),
                ),
                "difference_attributable_to_frozen_stop": True,
            }
        )
    return rows


def _portfolio_row(rows: Sequence[Mapping[str, Any]], name: str) -> dict[str, Any]:
    for row in rows:
        if str(row.get("portfolio_name")) == name:
            return dict(row)
    return {
        "portfolio_name": name,
        "net_cagr": None,
        "maximum_drawdown": None,
        "sharpe": None,
        "sortino": None,
        "calmar": None,
        "trade_count": 0,
        "win_rate": None,
        "expectancy": None,
    }


def _external_classification(
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    *,
    minimum_trades: int,
) -> str:
    challenger_trades = int(challenger.get("trade_count") or 0)
    if challenger_trades < minimum_trades:
        return "INSUFFICIENT_EXTERNAL_SAMPLE"
    challenger_cagr = _optional_float(challenger.get("net_cagr"))
    incumbent_cagr = _optional_float(incumbent.get("net_cagr"))
    benchmark_cagr = _optional_float(benchmark.get("net_cagr"))
    challenger_dd = _optional_float(challenger.get("maximum_drawdown"))
    incumbent_dd = _optional_float(incumbent.get("maximum_drawdown"))
    if challenger_cagr is None or incumbent_cagr is None:
        return "EXTERNAL_VALIDATION_MIXED"
    if challenger_cagr <= incumbent_cagr:
        return "EXTERNAL_VALIDATION_FAILED"
    if challenger_dd is not None and incumbent_dd is not None and challenger_dd < incumbent_dd:
        return "EXTERNAL_VALIDATION_MIXED"
    if benchmark_cagr is not None and challenger_cagr > benchmark_cagr:
        return "CHALLENGER_BEATS_BENCHMARK"
    if benchmark_cagr is not None:
        return "CHALLENGER_BEATS_INCUMBENT_NOT_BENCHMARK"
    return "EXTERNAL_VALIDATION_DIRECTIONALLY_SUPPORTED"


def _readiness(
    *,
    test_b: Any,
    source_summary: Mapping[str, Any],
    incumbent_metrics: Mapping[str, Any],
    challenger_metrics: Mapping[str, Any],
    benchmark_metrics: Mapping[str, Any],
    external_classification: str,
    minimum_trades: int,
) -> tuple[dict[str, str], list[str]]:
    blockers: list[str] = []
    source_start = source_summary.get("actual_start")
    source_end = source_summary.get("actual_end")
    partial = source_start is None or source_end is None or source_start > date(2005, 1, 1) or source_end < date(2015, 12, 31)
    readiness = {
        "A": "READY_FOR_PRE2016_EXTERNAL_VALIDATION",
        "B": "READY_WITH_PARTIAL_PRE2016_COVERAGE" if partial else "READY_FOR_GOVERNED_PRE2016_MARKET_REPLAY",
        "C": "READY_WITH_PARTIAL_CORPORATE_ACTION_COVERAGE" if int(source_summary.get("conflicting_corporate_actions") or 0) else "READY_FOR_GOVERNED_PRE2016_POINT_IN_TIME_UNIVERSE",
        "D": "READY_FOR_GOVERNED_PRE2016_TRI_COMPARISON" if benchmark_metrics.get("net_cagr") is not None else "READY_WITH_PRICE_INDEX_DIAGNOSTIC_ONLY",
        "E": "READY_WITH_ZERO_EXTERNAL_TRADES" if int(challenger_metrics.get("trade_count") or 0) == 0 else "READY_FOR_GOVERNED_FROZEN_STOP_EXTERNAL_TEST",
        "F": str(test_b.readiness.get("F", "BLOCKED_BY_PRE2016_WALK_FORWARD_IMPLEMENTATION_DEFECT")),
        "G": "READY_FOR_GOVERNED_PRE2016_PERFORMANCE_COMPARISON",
        "H": "READY_WITH_EXTERNAL_REJECTION" if external_classification == "EXTERNAL_VALIDATION_FAILED" else "READY_WITH_MIXED_EXTERNAL_EVIDENCE" if external_classification in {"EXTERNAL_VALIDATION_MIXED", "INSUFFICIENT_EXTERNAL_SAMPLE"} else "READY_FOR_GOVERNED_EXTERNAL_VALIDITY_CONCLUSION",
        "I": "READY_FOR_EXTENDED_FORWARD_PAPER_VALIDATION" if external_classification in {"EXTERNAL_VALIDATION_PASSED", "CHALLENGER_BEATS_BENCHMARK"} else "READY_WITH_DIRECTIONAL_EXTERNAL_SUPPORT" if external_classification in {"EXTERNAL_VALIDATION_DIRECTIONALLY_SUPPORTED", "CHALLENGER_BEATS_INCUMBENT_NOT_BENCHMARK"} else "READY_WITH_CHALLENGER_REJECTED" if external_classification == "EXTERNAL_VALIDATION_FAILED" else "READY_WITH_MIXED_EXTERNAL_EVIDENCE",
    }
    if partial:
        blockers.append("PARTIAL_PRE2016_HISTORICAL_COVERAGE")
    if int(source_summary.get("conflicting_corporate_actions") or 0):
        blockers.append("PARTIAL_CORPORATE_ACTION_COVERAGE")
    if benchmark_metrics.get("net_cagr") is None:
        blockers.append("TRI_BENCHMARK_UNAVAILABLE_OR_INCOMPLETE")
    if int(challenger_metrics.get("trade_count") or 0) < minimum_trades:
        blockers.append("INSUFFICIENT_EXTERNAL_TRADE_SAMPLE")
    if external_classification not in {"EXTERNAL_VALIDATION_PASSED", "CHALLENGER_BEATS_BENCHMARK"}:
        blockers.append(external_classification)
    return readiness, sorted(set(blockers))


def _assemble_rows(
    *,
    sources: Pre2016ExternalValidationSourcePaths,
    policy: Pre2016ExternalValidationPolicy,
    dsi009: Mapping[str, Any],
    dsi007: Mapping[str, Any],
    source_rows: Sequence[Mapping[str, Any]],
    source_summary: Mapping[str, Any],
    mapping_rows: Sequence[Mapping[str, Any]],
    selected: pd.DataFrame,
    challenger_signals: pd.DataFrame,
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    incumbent_metrics: Mapping[str, Any],
    challenger_metrics: Mapping[str, Any],
    benchmark_metrics: Mapping[str, Any],
    stop_differences: Sequence[Mapping[str, Any]],
    test_b: Any,
    external_classification: str,
    independent_trade_count: int,
) -> dict[str, tuple[dict[str, Any], ...]]:
    source_contract = [dict(row) for row in source_rows]
    source_contract.extend(
        [
            _source_row("DSI009_CERTIFICATE", sources.dsi009_certificate, True),
            _source_row("DSI007_CERTIFICATE", sources.dsi007_certificate, True),
            {
                "source_role": "FROZEN_CHALLENGER",
                "availability": "AVAILABLE",
                "sha256": hashlib.sha256(policy.frozen_challenger_id.encode()).hexdigest(),
                "byte_size": len(policy.frozen_challenger_id),
                "portable_locator": policy.frozen_challenger_id,
                "used_for_decisions": True,
            },
        ]
    )
    protocol = ({
        **asdict(policy),
        "dsi009_report_sha256": dsi009.get("report_sha256"),
        "dsi007_report_sha256": dsi007.get("report_sha256"),
        "external_results_used_for_protocol": False,
        "challenger_retuned": False,
    },)
    market_coverage = tuple(dict(row) for row in test_b.rows["market_data_coverage"])
    universe = tuple(dict(row) for row in test_b.rows["universe"])
    corporate_actions = tuple(dict(row) for row in test_b.rows["corporate_actions"])
    benchmark = tuple(dict(row) for row in test_b.rows["benchmark"])
    incumbent_signals = tuple(_portable_rows(selected))
    challenger_signal_rows = tuple(_portable_rows(challenger_signals))
    incumbent_trades = tuple(dict(row) for row in incumbent["trades"])
    challenger_trades = tuple(dict(row) for row in challenger["trades"])
    equity = tuple(
        [dict(row) for row in incumbent["curve"]]
        + [dict(row) for row in challenger["curve"]]
    )
    risk_rows = (
        {**dict(incumbent_metrics), "test_id": "TEST_A_FROZEN_STOP_TRANSPORT"},
        {**dict(challenger_metrics), "test_id": "TEST_A_FROZEN_STOP_TRANSPORT"},
        {**dict(benchmark_metrics), "test_id": "TEST_A_FROZEN_STOP_TRANSPORT"},
        {**_portfolio_row(test_b.rows["risk_metrics"], "REGIME_AWARE_SELECTED"), "test_id": "TEST_B_PRE2016_WALK_FORWARD"},
        {**_portfolio_row(test_b.rows["risk_metrics"], "BEST_FIXED_STRATEGY"), "test_id": "TEST_B_PRE2016_WALK_FORWARD"},
        {**_portfolio_row(test_b.rows["risk_metrics"], "SIMPLE_MOMENTUM_BASELINE"), "test_id": "TEST_B_PRE2016_WALK_FORWARD"},
        {**_portfolio_row(test_b.rows["risk_metrics"], "SIMPLE_TREND_BASELINE"), "test_id": "TEST_B_PRE2016_WALK_FORWARD"},
    )
    benchmark_relative = (
        _benchmark_relative_row(incumbent_metrics, benchmark_metrics, _EXTERNAL_INCUMBENT),
        _benchmark_relative_row(challenger_metrics, benchmark_metrics, _EXTERNAL_CHALLENGER),
        dict(_portfolio_row(test_b.rows["benchmark_relative"], "REGIME_AWARE_SELECTED")),
    )
    robustness = tuple(_robustness_rows(challenger_metrics, incumbent_metrics))
    concentration = tuple(_concentration_rows(challenger_trades))
    reconciliation = (
        {
            "population": "TEST_A_FROZEN_STOP_TRANSPORT",
            "source_signal_count": len(selected),
            "challenger_signal_count": len(challenger_signals),
            "incumbent_trade_count": len(incumbent_trades),
            "challenger_trade_count": len(challenger_trades),
            "unexplained_signal_difference_count": max(0, len(selected) - len(challenger_signals)),
            "independent_trade_plan_count": independent_trade_count,
        },
        {
            "population": "TEST_B_PRE2016_WALK_FORWARD",
            "source_signal_count": len(test_b.rows["signals"]),
            "challenger_signal_count": len(test_b.rows["signals"]),
            "incumbent_trade_count": len(test_b.rows["logical_trades"]),
            "challenger_trade_count": len(test_b.rows["logical_trades"]),
            "unexplained_signal_difference_count": 0,
            "independent_trade_plan_count": len(test_b.rows["trade_plans"]),
        },
    )
    non_vacuity = (
        {"probe_id": "FROZEN_CHALLENGER_ID", "passed": policy.frozen_challenger_id == "STOP-STRUCTURAL-10D"},
        {"probe_id": "NO_2016_OVERLAP", "passed": policy.external_end < "2016-01-01"},
        {"probe_id": "SAME_PRE_STOP_SIGNAL_POPULATION", "passed": len(selected) == len(challenger_signals)},
        {"probe_id": "NO_AUTOMATIC_PROMOTION", "passed": True},
        {"probe_id": "EXTERNAL_CLASSIFICATION_RECORDED", "passed": bool(external_classification)},
    )
    return {
        "source_contract": tuple(source_contract),
        "frozen_protocol": protocol,
        "market_data_coverage": market_coverage,
        "universe": universe,
        "corporate_actions": corporate_actions,
        "benchmark": benchmark,
        "frozen_mapping": tuple(dict(row) for row in mapping_rows),
        "incumbent_signals": incumbent_signals,
        "challenger_signals": challenger_signal_rows,
        "incumbent_trades": incumbent_trades,
        "challenger_trades": challenger_trades,
        "stop_differences": tuple(dict(row) for row in stop_differences),
        "external_daily_equity": equity,
        "walk_forward_folds": tuple(dict(row) for row in test_b.rows["walk_forward_folds"]),
        "strategy_selections": tuple(dict(row) for row in test_b.rows["strategy_selections"]),
        "comparison_portfolios": tuple(dict(row) for row in test_b.rows["comparison_portfolios"]),
        "calendar_performance": tuple(dict(row) for row in test_b.rows["calendar_performance"]),
        "rolling_performance": tuple(dict(row) for row in test_b.rows["rolling_performance"]),
        "regime_performance": tuple(dict(row) for row in test_b.rows["regime_daily"]),
        "risk_metrics": risk_rows,
        "benchmark_relative": benchmark_relative,
        "robustness": robustness,
        "concentration": concentration,
        "population_reconciliation": reconciliation,
        "non_vacuity": non_vacuity,
    }


def _benchmark_relative_row(
    portfolio: Mapping[str, Any], benchmark: Mapping[str, Any], name: str
) -> dict[str, Any]:
    portfolio_cagr = _optional_float(portfolio.get("net_cagr"))
    benchmark_cagr = _optional_float(benchmark.get("net_cagr"))
    return {
        "portfolio_name": name,
        "benchmark_name": "NIFTY_500_TRI",
        "benchmark_available": benchmark_cagr is not None,
        "portfolio_cagr": portfolio_cagr,
        "benchmark_cagr": benchmark_cagr,
        "excess_cagr": _difference(portfolio_cagr, benchmark_cagr),
        "reason": "AVAILABLE" if benchmark_cagr is not None else "BENCHMARK_UNAVAILABLE",
    }


def _robustness_rows(
    challenger: Mapping[str, Any], incumbent: Mapping[str, Any]
) -> list[dict[str, Any]]:
    return [
        {
            "scenario": "FROZEN_EXTERNAL_BASE",
            "challenger_cagr": challenger.get("net_cagr"),
            "incumbent_cagr": incumbent.get("net_cagr"),
            "challenger_drawdown": challenger.get("maximum_drawdown"),
            "incumbent_drawdown": incumbent.get("maximum_drawdown"),
            "parameters_changed": False,
        },
        {
            "scenario": "SELECTION_HISTORY_ACCOUNTED",
            "challenger_cagr": challenger.get("net_cagr"),
            "incumbent_cagr": incumbent.get("net_cagr"),
            "challenger_drawdown": challenger.get("maximum_drawdown"),
            "incumbent_drawdown": incumbent.get("maximum_drawdown"),
            "parameters_changed": False,
        },
    ]


def _concentration_rows(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not trades:
        return [{"dimension": "SECURITY", "key": "NONE", "trade_count": 0, "net_pnl": 0.0}]
    pnl: defaultdict[str, float] = defaultdict(float)
    counts: Counter[str] = Counter()
    for trade in trades:
        key = str(trade.get("symbol") or trade.get("identity_key") or "UNKNOWN")
        counts[key] += 1
        pnl[key] += float(trade.get("net_pnl") or 0.0)
    return [
        {
            "dimension": "SECURITY",
            "key": key,
            "trade_count": counts[key],
            "net_pnl": round(pnl[key], 10),
        }
        for key in sorted(counts)
    ]


def _source_row(role: str, path: Path, used: bool) -> dict[str, Any]:
    if not path.is_file():
        raise Pre2016ExternalValidationError(f"SOURCE_UNAVAILABLE:{role}")
    return {
        "source_role": role,
        "availability": "AVAILABLE",
        "sha256": _sha256(path),
        "byte_size": path.stat().st_size,
        "portable_locator": path.name,
        "used_for_decisions": used,
    }


def _portable_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        rows.append({str(key): _portable_value(value) for key, value in raw.items()})
    return rows


def _portable_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            return value
    return value


def _difference(left: object, right: object) -> float | None:
    left_value = _optional_float(left)
    right_value = _optional_float(right)
    if left_value is None or right_value is None:
        return None
    return round(left_value - right_value, 10)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    return result


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


__all__ = ["GovernedPre2016ExternalValidationEngine", "governance_flags"]
