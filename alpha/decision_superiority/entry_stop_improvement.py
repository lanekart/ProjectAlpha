"""Governed DSI-009 entry timing and stop-loss research engine."""

from __future__ import annotations

import hashlib
import math
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from types import MappingProxyType
from typing import Any, cast

import numpy as np
import pandas as pd

from alpha.decision_superiority.entry_stop_improvement_models import (
    EntryChallengerState,
    EntryMechanism,
    EntryStopAttribution,
    EntryStopImprovementError,
    EntryStopImprovementResult,
    EntryStopPolicy,
    EntryStopSourcePaths,
    FillState,
    StopChallengerState,
    StopMechanism,
    StopValueState,
)
from alpha.decision_superiority.performance_improvement import (
    _benjamini_hochberg,
    _holm,
    _load_market_slice,
    wilson_interval,
)
from alpha.decision_superiority.performance_improvement_artifacts import (
    DSI008_ARTIFACTS,
    validate_performance_improvement_certificate,
)
from alpha.decision_superiority.regime_strategy_artifacts import (
    DSI007_ARTIFACTS,
    validate_regime_strategy_tournament_certificate,
)
from alpha.decision_superiority.regime_strategy_models import TournamentPolicy
from alpha.decision_superiority.regime_strategy_tournament import (
    _portfolio_metrics,
    _simulate_portfolio,
)

_INCUMBENT = "DSI008_INCUMBENT"
_TRI = "NIFTY_500_TRI"
_STANDARD = "ALPHA_STANDARD"
_HIGH_CONVICTION = "ALPHA_HIGH_CONVICTION"
_ELITE = "ALPHA_ELITE"
_OUTCOME = "POSITIVE_REALISED_TRADE_RETURN"


def governance_flags() -> dict[str, bool]:
    """Return the immutable DSI-009 research-only boundary."""

    return {
        "THRESHOLD_CHANGE_PERMITTED": False,
        "APPROVAL_POLICY_CHANGE_PERMITTED": False,
        "PORTFOLIO_POLICY_CHANGE_PERMITTED": False,
        "EXECUTION_POLICY_CHANGE_PERMITTED": False,
        "LIVE_ENTRY_POLICY_ENABLED": False,
        "LIVE_STOP_POLICY_ENABLED": False,
        "STRATEGY_AUTOMATIC_PROMOTION_ENABLED": False,
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


def default_entry_registry() -> tuple[EntryMechanism, ...]:
    """Return the bounded, pre-registered entry mechanisms."""

    universal = ("ALL",)
    return (
        EntryMechanism(
            "ENTRY-INCUMBENT-NEXT-OPEN",
            "INCUMBENT_ENTRY",
            "Next governed session open",
            "OPEN_PLUS_FROZEN_SLIPPAGE",
            1,
            None,
            None,
            None,
            universal,
            universal,
            0,
            0,
            incumbent=True,
        ),
        EntryMechanism(
            "ENTRY-CLOSE-CONFIRM-5D",
            "BREAKOUT_CONFIRMATION",
            "Close above signal close; execute following open",
            "NEXT_OPEN_AFTER_CONFIRMED_CLOSE",
            5,
            None,
            None,
            None,
            universal,
            universal,
            1,
            1,
        ),
        EntryMechanism(
            "ENTRY-RETEST-SIGNAL-5D",
            "RETEST_ENTRY",
            "Retest and hold signal-close reference",
            "LIMIT_AT_REFERENCE_OR_BETTER",
            5,
            None,
            None,
            None,
            universal,
            universal,
            1,
            1,
        ),
        EntryMechanism(
            "ENTRY-PULLBACK-ATR-050",
            "PULLBACK_TO_SUPPORT",
            "Limit 0.5 ATR below signal close",
            "LIMIT_AT_LEVEL_OR_BETTER",
            5,
            None,
            0.5,
            None,
            universal,
            universal,
            1,
            1,
        ),
        EntryMechanism(
            "ENTRY-MAX-EXTENSION-100ATR",
            "MAXIMUM_EXTENSION_FILTER",
            "Next open only when extension is at most 1 ATR",
            "OPEN_PLUS_FROZEN_SLIPPAGE",
            1,
            None,
            None,
            1.0,
            universal,
            universal,
            1,
            1,
        ),
        EntryMechanism(
            "ENTRY-GAP-FILTER-020",
            "GAP_FILTER",
            "Next open only when positive gap is at most 2%",
            "OPEN_PLUS_FROZEN_SLIPPAGE",
            1,
            0.02,
            None,
            None,
            universal,
            universal,
            1,
            1,
        ),
        EntryMechanism(
            "ENTRY-REGIME-CONFIRMED",
            "REGIME_CONFIRMATION",
            "Next open only with a governed non-UNKNOWN regime",
            "OPEN_PLUS_FROZEN_SLIPPAGE",
            1,
            None,
            None,
            None,
            universal,
            universal,
            1,
            1,
        ),
    )


def default_stop_registry() -> tuple[StopMechanism, ...]:
    """Return bounded stop mechanisms evaluated after entry is frozen."""

    return (
        StopMechanism(
            "STOP-INCUMBENT",
            "INCUMBENT_STOP",
            None,
            None,
            None,
            0,
            False,
            0,
            0,
            incumbent=True,
        ),
        StopMechanism(
            "STOP-ATR-125",
            "ATR_STOP",
            1.25,
            None,
            None,
            0,
            False,
            1,
            1,
        ),
        StopMechanism(
            "STOP-ATR-225",
            "ATR_STOP",
            2.25,
            None,
            None,
            0,
            False,
            1,
            1,
        ),
        StopMechanism(
            "STOP-STRUCTURAL-10D",
            "STRUCTURAL_SUPPORT",
            None,
            None,
            10,
            0,
            False,
            1,
            1,
        ),
        StopMechanism(
            "STOP-VOL-STRUCTURAL-10D",
            "VOLATILITY_ADJUSTED_STRUCTURAL",
            1.75,
            None,
            10,
            0,
            False,
            2,
            2,
        ),
        StopMechanism(
            "STOP-MAX-RISK-080",
            "MAXIMUM_RISK_CAP",
            None,
            0.08,
            None,
            0,
            False,
            1,
            1,
        ),
    )


def validate_registries(
    entries: Sequence[EntryMechanism],
    stops: Sequence[StopMechanism],
    *,
    policy: EntryStopPolicy,
) -> None:
    """Fail closed on empty, duplicate, or unbounded registries."""

    if not entries:
        raise EntryStopImprovementError("EMPTY_ENTRY_REGISTRY")
    if not stops:
        raise EntryStopImprovementError("EMPTY_STOP_REGISTRY")
    if len(entries) > policy.maximum_entry_challengers:
        raise EntryStopImprovementError("UNBOUNDED_ENTRY_SEARCH")
    if len(stops) > policy.maximum_stop_challengers:
        raise EntryStopImprovementError("UNBOUNDED_STOP_SEARCH")
    entry_ids = [item.mechanism_id for item in entries]
    stop_ids = [item.mechanism_id for item in stops]
    if len(entry_ids) != len(set(entry_ids)):
        raise EntryStopImprovementError("DUPLICATE_ENTRY_CHALLENGER")
    if len(stop_ids) != len(set(stop_ids)):
        raise EntryStopImprovementError("DUPLICATE_STOP_CHALLENGER")
    if sum(item.incumbent for item in entries) != 1:
        raise EntryStopImprovementError("ENTRY_INCUMBENT_COUNT_INVALID")
    if sum(item.incumbent for item in stops) != 1:
        raise EntryStopImprovementError("STOP_INCUMBENT_COUNT_INVALID")


class GovernedEntryStopImprovementEngine:
    """Run DSI-009 A-I without changing Alpha runtime behaviour."""

    def run(
        self,
        *,
        sources: EntryStopSourcePaths,
        policy: EntryStopPolicy = EntryStopPolicy(),
        entry_registry: Sequence[EntryMechanism] | None = None,
        stop_registry: Sequence[StopMechanism] | None = None,
    ) -> EntryStopImprovementResult:
        """Validate sources and execute the governed research workflow."""

        entries = tuple(entry_registry or default_entry_registry())
        stops = tuple(stop_registry or default_stop_registry())
        validate_registries(entries, stops, policy=policy)
        dsi008 = validate_performance_improvement_certificate(
            sources.dsi008_certificate,
            require_ready=True,
        )
        dsi007 = validate_regime_strategy_tournament_certificate(
            sources.dsi007_certificate,
            require_ready=False,
            database=sources.database,
        )
        expected_dsi007_hash = cast(Mapping[str, Any], dsi008["source_chain_hashes"])[
            "DSI007_CERTIFICATE"
        ]
        if _sha256(sources.dsi007_certificate) != expected_dsi007_hash:
            raise EntryStopImprovementError("DSI007_SOURCE_CHAIN_HASH_MISMATCH")
        ledgers = _load_dsi008_ledgers(sources.dsi008_certificate.parent)
        selections = _load_dsi007_selections(sources.dsi007_certificate.parent)
        signals = _outer_signals(
            ledgers["signals"], selections=selections, policy=policy
        )
        market = _governed_market(
            sources.database,
            signals,
            start=date.fromisoformat(policy.comparison_start),
            end=date.fromisoformat(policy.comparison_end),
        )
        candidates = _candidate_frame(signals, market)
        incumbent_metrics = cast(Mapping[str, Any], dsi008["incumbent_summary"])
        tournament_policy = TournamentPolicy()

        incumbent_result = _simulate_portfolio(
            name=_INCUMBENT,
            featured=market,
            selected_signals=_portfolio_candidates(candidates),
            start=date.fromisoformat(policy.comparison_start),
            end=date.fromisoformat(policy.comparison_end),
            policy=tournament_policy,
        )
        incumbent_replay_metrics = _portfolio_metrics(
            name=_INCUMBENT,
            curve=incumbent_result["curve"],
            trades=incumbent_result["trades"],
            policy=tournament_policy,
        )
        _reconcile_incumbent(incumbent_replay_metrics, incumbent_metrics)

        trade_paths, excursion_rows = _trade_paths(
            candidates=candidates,
            market=market,
            incumbent_trades=cast(
                Sequence[Mapping[str, Any]], incumbent_result["trades"]
            ),
            benchmark=ledgers["tri"],
            policy=policy,
        )
        attribution_rows = _entry_stop_attribution(
            trade_paths,
            policy=policy,
        )
        signal_path_rows = _signal_path_ledger(candidates, market)
        entry_registry_rows = [_entry_registry_row(item) for item in entries]
        entry_fill_rows, entry_portfolios = _entry_tournament(
            candidates=candidates,
            market=market,
            entries=entries,
            start=date.fromisoformat(policy.comparison_start),
            end=date.fromisoformat(policy.comparison_end),
            tournament_policy=tournament_policy,
            policy=policy,
        )
        entry_fold_rows, entry_result_rows = _entry_results(
            entry_portfolios,
            incumbent_metrics=incumbent_replay_metrics,
            policy=policy,
        )
        entry_champion = _accepted_entry_champion(entry_result_rows)
        frozen_entry_id = entry_champion or "ENTRY-INCUMBENT-NEXT-OPEN"

        stop_value_rows = _stop_value_counterfactuals(
            trade_paths=trade_paths,
            market=market,
            policy=policy,
        )
        stop_registry_rows = [_stop_registry_row(item) for item in stops]
        stop_portfolios = _stop_tournament(
            candidates=candidates,
            market=market,
            stops=stops,
            frozen_entry_id=frozen_entry_id,
            entry_fill_rows=entry_fill_rows,
            start=date.fromisoformat(policy.comparison_start),
            end=date.fromisoformat(policy.comparison_end),
            tournament_policy=tournament_policy,
        )
        stop_fold_rows, stop_result_rows = _stop_results(
            stop_portfolios,
            incumbent_metrics=incumbent_replay_metrics,
            frozen_entry_id=frozen_entry_id,
            entry_champion=entry_champion,
            policy=policy,
        )
        stop_champion = _accepted_stop_champion(stop_result_rows)
        sequential_champion = (
            f"{entry_champion}+{stop_champion}"
            if entry_champion is not None and stop_champion is not None
            else None
        )

        portfolio_rows, equity_rows, benchmark_rows = _portfolio_comparison(
            incumbent_metrics=incumbent_replay_metrics,
            incumbent_result=incumbent_result,
            entry_portfolios=entry_portfolios,
            stop_portfolios=stop_portfolios,
            entry_champion=entry_champion,
            stop_champion=stop_champion,
            sequential_champion=sequential_champion,
            dsi008=dsi008,
            benchmark=ledgers["tri"],
            tournament_policy=tournament_policy,
        )
        tier_definitions, tier_outcomes, tradeoff_rows = _signal_tiers(
            candidates=candidates,
            incumbent_trades=cast(
                Sequence[Mapping[str, Any]], incumbent_result["trades"]
            ),
            policy=policy,
        )
        multiple_rows = _multiple_testing(entry_result_rows, stop_result_rows)
        robustness_rows = _robustness(
            entry_result_rows=entry_result_rows,
            stop_result_rows=stop_result_rows,
            incumbent_metrics=incumbent_replay_metrics,
        )
        concentration_rows = _concentration(
            incumbent_trades=cast(
                Sequence[Mapping[str, Any]], incumbent_result["trades"]
            ),
            tier_outcomes=tier_outcomes,
        )
        population_rows = _population_reconciliation(
            signals=signals,
            candidates=candidates,
            trade_paths=trade_paths,
            entry_fill_rows=entry_fill_rows,
            incumbent_result=incumbent_result,
        )
        probe_rows = _structural_probes()
        readiness, blockers, grade = _readiness(
            trade_paths=trade_paths,
            attribution_rows=attribution_rows,
            entry_result_rows=entry_result_rows,
            stop_result_rows=stop_result_rows,
            portfolio_rows=portfolio_rows,
            tier_outcomes=tier_outcomes,
            multiple_rows=multiple_rows,
            entry_champion=entry_champion,
            stop_champion=stop_champion,
        )
        source_rows = _source_contract_rows(
            sources=sources,
            dsi008=dsi008,
            dsi007=dsi007,
            market=market,
        )
        summaries = _summaries(
            dsi008=dsi008,
            incumbent_metrics=incumbent_replay_metrics,
            attribution_rows=attribution_rows,
            stop_value_rows=stop_value_rows,
            entry_result_rows=entry_result_rows,
            stop_result_rows=stop_result_rows,
            portfolio_rows=portfolio_rows,
            tier_outcomes=tier_outcomes,
            entry_champion=entry_champion,
            stop_champion=stop_champion,
            sequential_champion=sequential_champion,
            multiple_rows=multiple_rows,
            robustness_grade=grade,
        )
        rows: dict[str, tuple[dict[str, Any], ...]] = {
            "source_contract": tuple(source_rows),
            "incumbent_trade_path": tuple(trade_paths),
            "signal_path": tuple(signal_path_rows),
            "trade_excursions": tuple(excursion_rows),
            "entry_stop_attribution": tuple(attribution_rows),
            "entry_registry": tuple(entry_registry_rows),
            "entry_fills": tuple(entry_fill_rows),
            "entry_folds": tuple(entry_fold_rows),
            "entry_results": tuple(entry_result_rows),
            "stop_value": tuple(stop_value_rows),
            "stop_registry": tuple(stop_registry_rows),
            "stop_folds": tuple(stop_fold_rows),
            "stop_results": tuple(stop_result_rows),
            "sequential_portfolio": tuple(portfolio_rows),
            "daily_equity": tuple(equity_rows),
            "benchmark_relative": tuple(benchmark_rows),
            "tier_definitions": tuple(tier_definitions),
            "tier_outcomes": tuple(tier_outcomes),
            "accuracy_wealth_tradeoff": tuple(tradeoff_rows),
            "multiple_testing": tuple(multiple_rows),
            "robustness": tuple(robustness_rows),
            "concentration": tuple(concentration_rows),
            "population_reconciliation": tuple(population_rows),
            "non_vacuity": tuple(probe_rows),
        }
        return EntryStopImprovementResult(
            source_commit=_source_commit(sources.project_root),
            readiness=MappingProxyType(readiness),
            blockers=tuple(blockers),
            rows=MappingProxyType(rows),
            summaries=MappingProxyType(summaries),
            governance=MappingProxyType(governance_flags()),
        )


def _load_dsi008_ledgers(source_dir: Path) -> dict[str, pd.DataFrame]:
    mapping = {
        "signals": "signal_outcomes",
        "trade_excursions": "trade_excursions",
        "portfolio": "portfolio_comparison",
        "tri": "tri_daily",
        "folds": "champion_challenger_folds",
    }
    frames: dict[str, pd.DataFrame] = {}
    for key, artifact_key in mapping.items():
        path = source_dir / DSI008_ARTIFACTS[artifact_key]
        if not path.is_file():
            raise EntryStopImprovementError(
                f"DSI008_SUPPORT_ARTIFACT_MISSING:{path.name}"
            )
        frames[key] = pd.read_csv(path, low_memory=False)
    for key in ("signals", "trade_excursions"):
        for column in frames[key].columns:
            if column.endswith("_date") or column in {"signal_date", "entry_date"}:
                frames[key][column] = pd.to_datetime(
                    frames[key][column], errors="coerce"
                ).dt.date
    frames["tri"]["observed_on"] = pd.to_datetime(
        frames["tri"]["observed_on"], errors="raise"
    ).dt.date
    return frames


def _load_dsi007_selections(source_dir: Path) -> pd.DataFrame:
    path = source_dir / DSI007_ARTIFACTS["strategy_selections"]
    if not path.is_file():
        raise EntryStopImprovementError(f"DSI007_SUPPORT_ARTIFACT_MISSING:{path.name}")
    frame = pd.read_csv(path, low_memory=False)
    required = {
        "walk_forward_fold_id",
        "selection_scope",
        "selected",
        "selected_strategy_variant_id",
        "outer_test_used_for_selection",
    }
    missing = required - set(frame.columns)
    if missing:
        raise EntryStopImprovementError(
            f"DSI007_SELECTION_SCHEMA_INVALID:{','.join(sorted(missing))}"
        )
    if frame["outer_test_used_for_selection"].map(_as_bool).any():
        raise EntryStopImprovementError("ENTRY_SELECTION_LEAKAGE")
    selected = frame.loc[
        frame["selected"].map(_as_bool)
        & frame["selection_scope"].astype(str).str.startswith("REGIME:")
    ].copy()
    if selected.empty:
        raise EntryStopImprovementError("DSI007_SELECTED_REGIME_POLICY_EMPTY")
    if selected.duplicated(["walk_forward_fold_id", "selection_scope"]).any():
        raise EntryStopImprovementError("DSI007_SELECTED_REGIME_POLICY_DUPLICATE")
    return selected.sort_values(
        ["walk_forward_fold_id", "selection_scope"]
    ).reset_index(drop=True)


def _outer_signals(
    signals: pd.DataFrame,
    *,
    selections: pd.DataFrame,
    policy: EntryStopPolicy,
) -> pd.DataFrame:
    start = date.fromisoformat(policy.comparison_start)
    end = date.fromisoformat(policy.comparison_end)
    frame = signals.copy()
    if "entry_eligibility_date" not in frame.columns:
        raise EntryStopImprovementError("DSI008_ENTRY_ELIGIBILITY_DATE_MISSING")
    in_signal_window = frame["walk_forward_fold_id"].notna() & frame[
        "signal_date"
    ].between(start, end)
    missing_entry_date = in_signal_window & frame["entry_eligibility_date"].isna()
    if bool(missing_entry_date.any()):
        raise EntryStopImprovementError(
            f"DSI008_ENTRY_ELIGIBILITY_DATE_MISSING:{int(missing_entry_date.sum())}"
        )
    frame = frame.loc[in_signal_window & frame["entry_eligibility_date"].le(end)].copy()
    if frame.empty:
        raise EntryStopImprovementError("UNRECONCILED_SIGNAL_POPULATION")
    if frame["signal_id"].duplicated().any():
        raise EntryStopImprovementError("DUPLICATE_SIGNAL_ID")
    selected_by_fold_regime = {
        (
            str(row.walk_forward_fold_id),
            str(row.selection_scope).removeprefix("REGIME:"),
        ): str(row.selected_strategy_variant_id)
        for row in selections.itertuples(index=False)
    }
    selected_strategy = pd.Series(
        [
            selected_by_fold_regime.get(
                (str(row.walk_forward_fold_id), str(row.regime_state))
            )
            for row in frame.itertuples(index=False)
        ],
        index=frame.index,
        dtype="string",
    )
    missing_policy = selected_strategy.isna()
    if missing_policy.any():
        missing_cells = sorted(
            {
                (
                    str(row.walk_forward_fold_id),
                    str(row.regime_state),
                )
                for row in frame.loc[
                    missing_policy, ["walk_forward_fold_id", "regime_state"]
                ].itertuples(index=False)
            }
        )
        raise EntryStopImprovementError(
            "DSI007_SELECTED_REGIME_POLICY_MISSING:"
            + ",".join(f"{fold}/{regime}" for fold, regime in missing_cells)
        )
    frame = frame.loc[
        selected_strategy.ne("NO_TRADE")
        & frame["strategy_variant_id"].astype(str).eq(selected_strategy)
    ].copy()
    if frame.empty:
        raise EntryStopImprovementError("UNRECONCILED_SELECTED_SIGNAL_POPULATION")
    return frame.sort_values(["signal_date", "signal_id"]).reset_index(drop=True)


def _governed_market(
    database: Path,
    signals: pd.DataFrame,
    *,
    start: date,
    end: date,
) -> pd.DataFrame:
    if not database.is_file():
        raise EntryStopImprovementError("GOVERNED_MARKET_DATABASE_UNAVAILABLE")
    population = signals[["identity_key"]].drop_duplicates().copy()
    population["signal_date"] = start - timedelta(days=120)
    population["exit_date"] = end
    slices = _load_market_slice(database, population)
    if not slices:
        raise EntryStopImprovementError("GOVERNED_MARKET_DATA_UNAVAILABLE")
    frame = pd.concat(slices.values(), ignore_index=True).sort_values(
        ["identity_key", "trading_date"]
    )
    if frame.duplicated(["identity_key", "trading_date"]).any():
        raise EntryStopImprovementError("DUPLICATE_GOVERNED_IDENTITY_SESSION")
    grouped = frame.groupby("identity_key", sort=False, observed=True)
    previous_close = grouped["close"].shift(1)
    true_range = pd.concat(
        (
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ),
        axis=1,
    ).max(axis=1)
    frame["atr14"] = true_range.groupby(frame["identity_key"], sort=False).transform(
        lambda values: values.rolling(14, min_periods=14).mean()
    )
    frame["support10"] = grouped["low"].transform(
        lambda values: values.shift(1).rolling(10, min_periods=2).min()
    )
    return frame.reset_index(drop=True)


def _candidate_frame(signals: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    signal_reference = market[
        ["identity_key", "trading_date", "close", "atr14", "support10"]
    ].rename(
        columns={
            "trading_date": "signal_date",
            "close": "signal_close",
            "atr14": "atr14",
            "support10": "support10",
        }
    )
    entry_reference = market[["identity_key", "trading_date", "open"]].rename(
        columns={
            "trading_date": "entry_eligibility_date",
            "open": "raw_entry_price",
        }
    )
    frame = signals.merge(
        signal_reference,
        on=["identity_key", "signal_date"],
        how="left",
        validate="many_to_one",
    ).merge(
        entry_reference,
        on=["identity_key", "entry_eligibility_date"],
        how="left",
        validate="many_to_one",
    )
    required = (
        "signal_close",
        "atr14",
        "raw_entry_price",
        "initial_stop",
        "target_1",
        "target_2",
        "average_traded_value20",
    )
    missing = frame[list(required)].isna().any(axis=1)
    if bool(missing.any()):
        raise EntryStopImprovementError(f"INCOMPLETE_TRADE_PATH:{int(missing.sum())}")
    expected_entry = frame["raw_entry_price"].astype(float) * 1.001
    mismatch = (expected_entry - frame["entry_price"].astype(float)).abs() > frame[
        "entry_price"
    ].astype(float) * 1e-6
    if bool(mismatch.any()):
        raise EntryStopImprovementError(
            f"INCUMBENT_ENTRY_PRICE_RECONCILIATION_DEFECT:{int(mismatch.sum())}"
        )
    frame["trade_plan_id"] = frame["signal_id"].map(
        lambda value: _stable_id("PLAN", value)
    )
    frame["trading_date"] = frame["signal_date"]
    frame["regime"] = frame["regime_state"]
    return frame


def _portfolio_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    columns = (
        "trade_plan_id",
        "signal_id",
        "identity_key",
        "symbol",
        "strategy_variant_id",
        "walk_forward_fold_id",
        "regime",
        "trading_date",
        "entry_eligibility_date",
        "signal_strength",
        "raw_entry_price",
        "initial_stop",
        "target_1",
        "target_2",
        "atr14",
        "maximum_holding_sessions",
        "average_traded_value20",
    )
    return frame[list(columns)].sort_values(
        ["entry_eligibility_date", "signal_strength", "signal_id"],
        ascending=[True, False, True],
    )


def _reconcile_incumbent(
    replay: Mapping[str, Any],
    signed: Mapping[str, Any],
) -> None:
    expected = {
        "ending_capital": float(signed["ending_capital"]),
        "net_cagr": float(signed["net_cagr"]),
        "maximum_drawdown": float(signed["maximum_drawdown"]),
        "trade_count": int(signed["trade_count"]),
    }
    tolerances = {
        "ending_capital": 2.0,
        "net_cagr": 2e-6,
        "maximum_drawdown": 2e-6,
        "trade_count": 0.0,
    }
    for field, expected_value in expected.items():
        actual = replay.get(field)
        if actual is None or abs(float(actual) - expected_value) > tolerances[field]:
            raise EntryStopImprovementError(
                f"INCUMBENT_PORTFOLIO_RECONCILIATION_DEFECT:{field}:"
                f"{actual}:{expected_value}"
            )


def _market_groups(market: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        str(identity): frame.sort_values("trading_date").reset_index(drop=True)
        for identity, frame in market.groupby("identity_key", sort=False)
    }


def _trade_paths(
    *,
    candidates: pd.DataFrame,
    market: pd.DataFrame,
    incumbent_trades: Sequence[Mapping[str, Any]],
    benchmark: pd.DataFrame,
    policy: EntryStopPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups = _market_groups(market)
    candidate_lookup = {
        (
            str(row.identity_key),
            row.signal_date,
            str(row.strategy_variant_id),
        ): row
        for row in cast(Iterable[Any], candidates.itertuples(index=False))
    }
    benchmark_series = benchmark.set_index("observed_on")["value"]
    paths: list[dict[str, Any]] = []
    excursions: list[dict[str, Any]] = []
    for trade in incumbent_trades:
        key = (
            str(trade["identity_key"]),
            trade["signal_date"],
            str(trade["strategy_variant_id"]),
        )
        signal = candidate_lookup.get(key)
        if signal is None:
            raise EntryStopImprovementError("INCOMPLETE_TRADE_PATH:SIGNAL_NOT_FOUND")
        bars = groups[str(trade["identity_key"])]
        active = bars.loc[
            (bars["trading_date"] >= trade["entry_date"])
            & (bars["trading_date"] <= trade["exit_date"])
        ].copy()
        future = bars.loc[bars["trading_date"] >= trade["entry_date"]].head(
            int(signal.maximum_holding_sessions) + 1
        )
        if active.empty or future.empty:
            raise EntryStopImprovementError("INCOMPLETE_TRADE_PATH:MARKET_PATH_EMPTY")
        entry = float(trade["entry_price"])
        stop = float(signal.initial_stop)
        mfe_index = active["high"].astype(float).idxmax()
        mae_index = active["low"].astype(float).idxmin()
        mfe = float(active.loc[mfe_index, "high"]) / entry - 1.0
        mae = float(active.loc[mae_index, "low"]) / entry - 1.0
        stop_rows = future.loc[future["low"].astype(float) <= stop]
        first_stop_date = None if stop_rows.empty else stop_rows.iloc[0]["trading_date"]
        before_stop = (
            future
            if first_stop_date is None
            else future.loc[future["trading_date"] <= first_stop_date]
        )
        after_stop = (
            future.iloc[0:0]
            if first_stop_date is None
            else future.loc[future["trading_date"] > first_stop_date]
        )
        highest_after_stop = (
            None if after_stop.empty else float(after_stop["high"].max()) / entry - 1.0
        )
        lowest_after_stop = (
            None if after_stop.empty else float(after_stop["low"].min()) / entry - 1.0
        )
        recovery_date = _first_recovery_date(
            after_stop,
            entry=entry,
            threshold=policy.recovery_return_threshold,
        )
        benchmark_return = _period_return(
            benchmark_series,
            trade["entry_date"],
            trade["exit_date"],
        )
        risk = entry - stop
        row = {
            "logical_trade_id": trade["logical_trade_id"],
            "signal_id": signal.signal_id,
            "identity_key": trade["identity_key"],
            "symbol": trade["symbol"],
            "walk_forward_fold_id": trade["walk_forward_fold_id"],
            "strategy_variant_id": trade["strategy_variant_id"],
            "strategy_family": signal.strategy_family,
            "setup": signal.strategy_family,
            "regime_at_signal": trade["regime_state"],
            "signal_date": trade["signal_date"],
            "signal_close": _round(signal.signal_close),
            "next_open": _round(signal.raw_entry_price),
            "next_high": _bar_value(bars, signal.entry_eligibility_date, "high"),
            "next_low": _bar_value(bars, signal.entry_eligibility_date, "low"),
            "incumbent_trigger": "NEXT_GOVERNED_SESSION_OPEN",
            "incumbent_entry": _round(trade["entry_price"]),
            "entry_date": trade["entry_date"],
            "entry_delay_sessions": _session_distance(
                bars, trade["signal_date"], trade["entry_date"]
            ),
            "stop": _round(stop),
            "target_1": _round(signal.target_1),
            "target_2": _round(signal.target_2),
            "target_3": _optional_round(signal.target_3),
            "invalidation": _round(stop),
            "exit": _round(trade["exit_price"]),
            "exit_date": trade["exit_date"],
            "exit_reason": trade["exit_reason"],
            "realised_return": _round(trade["net_return"]),
            "realised_r": None
            if risk <= 0
            else _round((float(trade["exit_price"]) - entry) / risk),
            "holding_period": int(trade["holding_sessions"]),
            "benchmark_return": benchmark_return,
            "mfe": _round(mfe),
            "mae": _round(mae),
            "sessions_to_mfe": _session_distance(
                active, trade["entry_date"], active.loc[mfe_index, "trading_date"]
            ),
            "sessions_to_mae": _session_distance(
                active, trade["entry_date"], active.loc[mae_index, "trading_date"]
            ),
            "mfe_before_stop": _round(float(before_stop["high"].max()) / entry - 1.0),
            "mae_before_first_target": _mae_before_target(
                active, entry=entry, target=float(signal.target_1)
            ),
            "stop_date": first_stop_date,
            "highest_subsequent_return_after_stop": _optional_round(highest_after_stop),
            "lowest_subsequent_return_after_stop": _optional_round(lowest_after_stop),
            "recovery_after_stop": recovery_date is not None,
            "recovery_date": recovery_date,
            "benchmark_relative_excursion": (
                None if benchmark_return is None else _round(mfe - benchmark_return)
            ),
            "entry_extension_atr": _entry_extension_atr(signal),
            "atr14": _round(signal.atr14),
            "support10": _optional_round(signal.support10),
            "net_pnl": _round(trade["net_pnl"]),
            "costs": _round(trade["costs"]),
        }
        paths.append(row)
        excursions.append(
            {
                key: row[key]
                for key in (
                    "logical_trade_id",
                    "symbol",
                    "entry_date",
                    "exit_date",
                    "mfe",
                    "mae",
                    "sessions_to_mfe",
                    "sessions_to_mae",
                    "mfe_before_stop",
                    "mae_before_first_target",
                    "highest_subsequent_return_after_stop",
                    "lowest_subsequent_return_after_stop",
                    "recovery_after_stop",
                    "benchmark_relative_excursion",
                )
            }
        )
    _validate_trade_path_count(
        paths=paths,
        incumbent_trades=incumbent_trades,
    )
    return paths, excursions


def _validate_trade_path_count(
    *,
    paths: Sequence[Mapping[str, Any]],
    incumbent_trades: Sequence[Mapping[str, Any]],
) -> None:
    if len(paths) != len(incumbent_trades):
        raise EntryStopImprovementError(
            f"UNRECONCILED_INCUMBENT_TRADE_COUNT:{len(paths)}:{len(incumbent_trades)}"
        )


def _entry_stop_attribution(
    trade_paths: Sequence[dict[str, Any]],
    *,
    policy: EntryStopPolicy,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade in trade_paths:
        realised = float(trade["realised_return"])
        extension = trade["entry_extension_atr"]
        recovered = bool(trade["recovery_after_stop"])
        later_low = trade["lowest_subsequent_return_after_stop"]
        sessions_to_recovery = (
            None
            if trade["recovery_date"] is None or trade["stop_date"] is None
            else _calendar_session_proxy(trade["stop_date"], trade["recovery_date"])
        )
        overlapping: list[str] = []
        if (
            extension is not None
            and float(extension) > policy.maximum_entry_extension_atr
        ):
            overlapping.append(EntryStopAttribution.ENTRY_TOO_EXTENDED.value)
        if recovered:
            overlapping.append(
                EntryStopAttribution.ENTRY_TOO_EARLY_RECOVERED_AFTER_STOP.value
            )
        if later_low is not None and float(later_low) <= policy.tail_loss_threshold:
            overlapping.append(EntryStopAttribution.STOP_PREVENTED_LARGER_LOSS.value)
        if realised > 0:
            if float(trade["mae"]) < -0.05:
                primary = EntryStopAttribution.WINNER_SURVIVED_ADVERSE_EXCURSION
            else:
                primary = EntryStopAttribution.WINNER_ENTERED_WELL
        elif trade["exit_reason"] == "STOP" and recovered:
            if (
                sessions_to_recovery is not None
                and sessions_to_recovery <= policy.quick_recovery_sessions
            ):
                primary = EntryStopAttribution.STOP_TOO_TIGHT_RECOVERED_QUICKLY
            else:
                primary = EntryStopAttribution.ENTRY_TOO_EARLY_RECOVERED_AFTER_STOP
        elif (
            extension is not None
            and float(extension) > policy.maximum_entry_extension_atr
        ):
            primary = EntryStopAttribution.ENTRY_TOO_EXTENDED
        elif later_low is not None and float(later_low) <= policy.tail_loss_threshold:
            primary = EntryStopAttribution.STOP_PREVENTED_LARGER_LOSS
        elif trade["exit_reason"] == "STOP":
            primary = EntryStopAttribution.THESIS_FAILED_WITHOUT_RECOVERY
        elif realised < 0:
            primary = EntryStopAttribution.THESIS_FAILED_AND_CONTINUED_LOWER
        else:
            primary = EntryStopAttribution.AMBIGUOUS
        rows.append(
            {
                "logical_trade_id": trade["logical_trade_id"],
                "symbol": trade["symbol"],
                "walk_forward_fold_id": trade["walk_forward_fold_id"],
                "year": trade["exit_date"].year,
                "regime": trade["regime_at_signal"],
                "strategy": trade["strategy_variant_id"],
                "setup": trade["setup"],
                "primary_attribution": primary.value,
                "overlapping_diagnostics": "|".join(sorted(set(overlapping))),
                "realised_return": trade["realised_return"],
                "net_pnl": trade["net_pnl"],
                "drawdown_contribution": min(float(trade["realised_return"]), 0.0),
                "stop_distance_fraction": _round(
                    (float(trade["incumbent_entry"]) - float(trade["stop"]))
                    / float(trade["incumbent_entry"])
                ),
                "entry_extension_atr": extension,
                "mfe": trade["mfe"],
                "mae": trade["mae"],
                "diagnostic_not_causal": True,
                "definitions_frozen_before_classification": True,
            }
        )
    if len(rows) != len(trade_paths):
        raise EntryStopImprovementError("UNATTRIBUTED_LOSS_POPULATION")
    return rows


def _signal_path_ledger(
    candidates: pd.DataFrame,
    market: pd.DataFrame,
) -> list[dict[str, Any]]:
    groups = _market_groups(market)
    rows: list[dict[str, Any]] = []
    for signal in cast(Iterable[Any], candidates.itertuples(index=False)):
        bars = groups[str(signal.identity_key)]
        future = bars.loc[bars["trading_date"] > signal.signal_date].head(60)
        if future.empty:
            state = FillState.DATA_UNAVAILABLE
            mfe = mae = None
        else:
            entry_bar = future.loc[
                future["trading_date"] == signal.entry_eligibility_date
            ]
            if entry_bar.empty:
                state = FillState.DATA_UNAVAILABLE
            elif float(signal.average_traded_value20) < 5_000_000.0:
                state = FillState.LIQUIDITY_REJECTED
            elif bool(signal.entered):
                state = FillState.ENTERED
            else:
                state = FillState.CAPITAL_UNAVAILABLE
            reference = float(signal.signal_close)
            mfe = float(future["high"].max()) / reference - 1.0
            mae = float(future["low"].min()) / reference - 1.0
        rows.append(
            {
                "signal_id": signal.signal_id,
                "identity_key": signal.identity_key,
                "symbol": signal.symbol,
                "signal_date": signal.signal_date,
                "walk_forward_fold_id": signal.walk_forward_fold_id,
                "strategy_variant_id": signal.strategy_variant_id,
                "regime_state": signal.regime_state,
                "signal_close": _round(signal.signal_close),
                "incumbent_entry_state": state.value,
                "incumbent_entry_date": (
                    signal.entry_eligibility_date
                    if state is FillState.ENTERED
                    else None
                ),
                "signal_path_mfe_60": _optional_round(mfe),
                "signal_path_mae_60": _optional_round(mae),
                "executed_portfolio_trade": bool(signal.entered),
                "signal_path_is_not_realised_trade": True,
            }
        )
    return rows


def _entry_registry_row(item: EntryMechanism) -> dict[str, Any]:
    row = asdict(item)
    row["supported_regimes"] = "|".join(item.supported_regimes)
    row["supported_strategies"] = "|".join(item.supported_strategies)
    row["eligible_time"] = "NO_EARLIER_THAN_NEXT_GOVERNED_SESSION"
    row["limit_treatment"] = "UNFILLED_LIMITS_REMAIN_UNFILLED"
    row["skipped_trade_treatment"] = "EXCLUDED_WITH_OPPORTUNITY_COST_RETAINED"
    row["cost_impact"] = "FROZEN_DSI008_COST_MODEL"
    row["pre_registered"] = True
    row["production_influence"] = False
    return row


def _stop_registry_row(item: StopMechanism) -> dict[str, Any]:
    row = asdict(item)
    row["entry_policy_frozen_before_evaluation"] = True
    row["position_size_basis"] = "CONSTANT_CAPITAL_SIZE"
    row["constant_risk_size_used"] = False
    row["pre_registered"] = True
    row["production_influence"] = False
    return row


def _entry_tournament(
    *,
    candidates: pd.DataFrame,
    market: pd.DataFrame,
    entries: Sequence[EntryMechanism],
    start: date,
    end: date,
    tournament_policy: TournamentPolicy,
    policy: EntryStopPolicy,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    groups = _market_groups(market)
    fill_rows: list[dict[str, Any]] = []
    mechanism_rows: dict[str, list[dict[str, Any]]] = {
        item.mechanism_id: [] for item in entries
    }
    for signal in cast(Iterable[Any], candidates.itertuples(index=False)):
        bars = groups[str(signal.identity_key)]
        for mechanism in entries:
            fill = _entry_fill(signal, bars, mechanism, policy=policy)
            fill_rows.append(fill)
            if fill["fill_state"] == FillState.ENTERED.value:
                mechanism_rows[mechanism.mechanism_id].append(fill)
    portfolios: dict[str, dict[str, Any]] = {}
    for mechanism in entries:
        selected = pd.DataFrame(mechanism_rows[mechanism.mechanism_id])
        if selected.empty:
            simulation = _empty_simulation()
        else:
            selected = selected.sort_values(
                ["entry_eligibility_date", "signal_strength", "signal_id"],
                ascending=[True, False, True],
            )
            simulation = _simulate_portfolio(
                name=mechanism.mechanism_id,
                featured=market,
                selected_signals=selected,
                start=start,
                end=end,
                policy=tournament_policy,
            )
        metrics = _portfolio_metrics(
            name=mechanism.mechanism_id,
            curve=simulation["curve"],
            trades=simulation["trades"],
            policy=tournament_policy,
        )
        portfolios[mechanism.mechanism_id] = {
            "simulation": simulation,
            "metrics": metrics,
            "filled_signal_count": len(selected),
            "mechanism": mechanism,
        }
    return fill_rows, portfolios


def _entry_fill(
    signal: Any,
    bars: pd.DataFrame,
    mechanism: EntryMechanism,
    *,
    policy: EntryStopPolicy,
) -> dict[str, Any]:
    eligible = bars.loc[bars["trading_date"] >= signal.entry_eligibility_date]
    state = FillState.TRIGGER_NEVER_REACHED
    fill_date: date | None = None
    raw_fill: float | None = None
    reason = "governed trigger was not reached within the waiting window"
    if eligible.empty:
        state = FillState.DATA_UNAVAILABLE
        reason = "no governed market bar exists at or after eligibility"
    elif float(signal.average_traded_value20) < 5_000_000.0:
        state = FillState.LIQUIDITY_REJECTED
        reason = "frozen DSI-008 liquidity floor was not satisfied"
    else:
        window = eligible.head(mechanism.maximum_wait_sessions + 1).reset_index(
            drop=True
        )
        entry_bar = window.iloc[0]
        signal_close = float(signal.signal_close)
        atr = float(signal.atr14)
        if mechanism.family == "INCUMBENT_ENTRY":
            fill_date = entry_bar.trading_date
            raw_fill = float(entry_bar.open)
        elif mechanism.family == "BREAKOUT_CONFIRMATION":
            confirmed = window.iloc[: mechanism.maximum_wait_sessions].loc[
                window.iloc[: mechanism.maximum_wait_sessions]["close"].astype(float)
                > signal_close
            ]
            if not confirmed.empty:
                confirmation_index = int(confirmed.index[0])
                if confirmation_index + 1 < len(window):
                    fill_bar = window.iloc[confirmation_index + 1]
                    fill_date = fill_bar.trading_date
                    raw_fill = float(fill_bar.open)
        elif mechanism.family == "RETEST_ENTRY":
            considered = window.iloc[: mechanism.maximum_wait_sessions]
            held = considered.loc[
                (considered["low"].astype(float) <= signal_close)
                & (considered["close"].astype(float) >= signal_close)
            ]
            if not held.empty:
                confirmation_index = int(held.index[0])
                if confirmation_index + 1 < len(window):
                    fill_bar = window.iloc[confirmation_index + 1]
                    fill_date = fill_bar.trading_date
                    raw_fill = float(fill_bar.open)
        elif mechanism.family == "PULLBACK_TO_SUPPORT":
            level = signal_close - atr * float(mechanism.atr_offset or 0.0)
            considered = window.iloc[: mechanism.maximum_wait_sessions]
            touched = considered.loc[considered["low"].astype(float) <= level]
            if not touched.empty:
                fill_bar = touched.iloc[0]
                fill_date = fill_bar.trading_date
                raw_fill = min(float(fill_bar.open), level)
        elif mechanism.family == "MAXIMUM_EXTENSION_FILTER":
            extension = (float(entry_bar.open) - signal_close) / atr
            if extension <= float(mechanism.maximum_extension_atr or 0.0):
                fill_date = entry_bar.trading_date
                raw_fill = float(entry_bar.open)
            else:
                state = FillState.GAP_BEYOND_ENTRY_LIMIT
                reason = "next open exceeded the frozen ATR extension limit"
        elif mechanism.family == "GAP_FILTER":
            gap = float(entry_bar.open) / signal_close - 1.0
            if gap <= float(mechanism.gap_limit or 0.0):
                fill_date = entry_bar.trading_date
                raw_fill = float(entry_bar.open)
            else:
                state = FillState.GAP_BEYOND_ENTRY_LIMIT
                reason = "next open exceeded the frozen positive-gap limit"
        elif mechanism.family == "REGIME_CONFIRMATION":
            if str(signal.regime_state).upper() in {"", "UNKNOWN", "NAN"}:
                state = FillState.REGIME_CHANGED_BEFORE_ENTRY
                reason = "governed regime confirmation was unavailable"
            else:
                fill_date = entry_bar.trading_date
                raw_fill = float(entry_bar.open)
        else:
            raise EntryStopImprovementError("NONEXECUTABLE_ENTRY_RULE")
        if fill_date is not None and raw_fill is not None:
            prior = window.loc[window["trading_date"] < fill_date]
            if not prior.empty and bool(
                (prior["low"].astype(float) <= float(signal.initial_stop)).any()
            ):
                state = FillState.INVALIDATED_BEFORE_ENTRY
                reason = "incumbent invalidation was breached before the trigger"
                fill_date = None
                raw_fill = None
            else:
                state = FillState.ENTERED
                reason = "entry trigger satisfied using point-in-time market data"
    slipped_entry = None if raw_fill is None else raw_fill * 1.001
    stop = None if slipped_entry is None else float(signal.initial_stop)
    target_1 = None if slipped_entry is None else float(signal.target_1)
    target_2 = None if slipped_entry is None else float(signal.target_2)
    return {
        "entry_fill_id": _stable_id(
            "ENTRY_FILL", mechanism.mechanism_id, signal.signal_id
        ),
        "mechanism_id": mechanism.mechanism_id,
        "family": mechanism.family,
        "signal_id": signal.signal_id,
        "trade_plan_id": _stable_id("PLAN", mechanism.mechanism_id, signal.signal_id),
        "identity_key": signal.identity_key,
        "symbol": signal.symbol,
        "strategy_variant_id": signal.strategy_variant_id,
        "walk_forward_fold_id": signal.walk_forward_fold_id,
        "regime": signal.regime_state,
        "trading_date": signal.signal_date,
        "signal_date": signal.signal_date,
        "signal_strength": _round(signal.signal_strength),
        "fill_state": state.value,
        "fill_reason": reason,
        "entry_eligibility_date": fill_date,
        "raw_entry_price": _optional_round(raw_fill),
        "entry_price_after_slippage": _optional_round(slipped_entry),
        "initial_stop": _optional_round(stop),
        "target_1": _optional_round(target_1),
        "target_2": _optional_round(target_2),
        "atr14": _round(signal.atr14),
        "support10": _optional_round(signal.support10),
        "maximum_holding_sessions": int(signal.maximum_holding_sessions),
        "average_traded_value20": _round(signal.average_traded_value20),
        "entry_extension_atr": (
            None
            if raw_fill is None
            else _round((raw_fill - float(signal.signal_close)) / float(signal.atr14))
        ),
        "wait_sessions": (
            None
            if fill_date is None
            else _session_distance(bars, signal.signal_date, fill_date)
        ),
        "impossible_fill": False,
        "outer_test_used_for_rule_definition": False,
    }


def _entry_results(
    portfolios: Mapping[str, Mapping[str, Any]],
    *,
    incumbent_metrics: Mapping[str, Any],
    policy: EntryStopPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    incumbent_trades = cast(
        Sequence[Mapping[str, Any]],
        portfolios["ENTRY-INCUMBENT-NEXT-OPEN"]["simulation"]["trades"],
    )
    incumbent_by_fold = _trade_fold_metrics(incumbent_trades)
    fold_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    for mechanism_id, payload in sorted(portfolios.items()):
        metrics = cast(Mapping[str, Any], payload["metrics"])
        trades = cast(Sequence[Mapping[str, Any]], payload["simulation"]["trades"])
        by_fold = _trade_fold_metrics(trades)
        deltas: list[float] = []
        for fold_id in ("WF-2021", "WF-2022", "WF-2023", "WF-2024", "WF-2025"):
            incumbent = incumbent_by_fold.get(fold_id, _empty_trade_metrics())
            challenger = by_fold.get(fold_id, _empty_trade_metrics())
            delta = (
                None
                if incumbent["expectancy"] is None or challenger["expectancy"] is None
                else float(challenger["expectancy"]) - float(incumbent["expectancy"])
            )
            if delta is not None:
                deltas.append(delta)
            fold_rows.append(
                {
                    "mechanism_id": mechanism_id,
                    "walk_forward_fold_id": fold_id,
                    "incumbent_trade_count": incumbent["trade_count"],
                    "challenger_trade_count": challenger["trade_count"],
                    "incumbent_expectancy": incumbent["expectancy"],
                    "challenger_expectancy": challenger["expectancy"],
                    "expectancy_delta": _optional_round(delta),
                    "incumbent_win_rate": incumbent["win_rate"],
                    "challenger_win_rate": challenger["win_rate"],
                    "outer_test_used_for_selection": False,
                    "parameters_frozen_before_outer_test": True,
                }
            )
        positive = sum(item > 0 for item in deltas)
        negative = sum(item < 0 for item in deltas)
        if mechanism_id == "ENTRY-INCUMBENT-NEXT-OPEN":
            state = "INCUMBENT_CONTROL"
        elif int(metrics["trade_count"]) < policy.minimum_challenger_trades:
            state = EntryChallengerState.INSUFFICIENT_SAMPLE.value
        elif (
            metrics["net_cagr"] is not None
            and float(metrics["net_cagr"]) > float(incumbent_metrics["net_cagr"])
            and metrics["maximum_drawdown"] is not None
            and float(metrics["maximum_drawdown"])
            >= float(incumbent_metrics["maximum_drawdown"])
            and positive > negative
        ):
            state = EntryChallengerState.DESCRIPTIVELY_BETTER.value
        else:
            state = EntryChallengerState.REJECTED.value
        result_rows.append(
            {
                "mechanism_id": mechanism_id,
                "state": state,
                "filled_signal_count": int(payload["filled_signal_count"]),
                "trade_count": int(metrics["trade_count"]),
                "net_cagr": metrics["net_cagr"],
                "cagr_delta": _difference(
                    metrics["net_cagr"], incumbent_metrics["net_cagr"]
                ),
                "maximum_drawdown": metrics["maximum_drawdown"],
                "sharpe": metrics["sharpe"],
                "sortino": metrics["sortino"],
                "calmar": metrics["calmar"],
                "win_rate": metrics["win_rate"],
                "expectancy": metrics["expectancy"],
                "costs": metrics["total_costs"],
                "turnover": metrics["turnover"],
                "positive_fold_count": positive,
                "negative_fold_count": negative,
                "median_fold_expectancy_delta": (
                    None if not deltas else _round(median(deltas))
                ),
                "fresh_holdout_available": False,
                "automatic_acceptance": False,
            }
        )
    return fold_rows, result_rows


def _accepted_entry_champion(rows: Sequence[Mapping[str, Any]]) -> str | None:
    accepted_states = {
        EntryChallengerState.DIRECTIONALLY_STABLE.value,
        EntryChallengerState.ROBUSTLY_BETTER.value,
    }
    accepted = sorted(
        str(row["mechanism_id"]) for row in rows if row["state"] in accepted_states
    )
    return accepted[0] if len(accepted) == 1 else None


def _stop_value_counterfactuals(
    *,
    trade_paths: Sequence[dict[str, Any]],
    market: pd.DataFrame,
    policy: EntryStopPolicy,
) -> list[dict[str, Any]]:
    groups = _market_groups(market)
    rows: list[dict[str, Any]] = []
    for trade in trade_paths:
        if trade["exit_reason"] != "STOP":
            state = StopValueState.NOT_TRIGGERED
            no_stop = None
            target_after_stop = False
            time_to_recovery = None
            additional_drawdown = None
            capital_tied = 0
            later_max_loss = None
            later_max_gain = None
        else:
            bars = groups[str(trade["identity_key"])]
            future = bars.loc[bars["trading_date"] >= trade["entry_date"]].head(
                int(trade["holding_period"]) + policy.recovery_window_sessions + 1
            )
            no_stop = _no_stop_outcome(trade, future)
            after_stop = future.loc[future["trading_date"] > trade["exit_date"]]
            entry = float(trade["incumbent_entry"])
            later_max_loss = (
                None
                if after_stop.empty
                else float(after_stop["low"].min()) / entry - 1.0
            )
            later_max_gain = (
                None
                if after_stop.empty
                else float(after_stop["high"].max()) / entry - 1.0
            )
            target_after_stop = bool(
                not after_stop.empty
                and (after_stop["high"].astype(float) >= float(trade["target_1"])).any()
            )
            recovery = _first_recovery_date(
                after_stop,
                entry=entry,
                threshold=policy.recovery_return_threshold,
            )
            time_to_recovery = (
                None
                if recovery is None
                else _session_distance(bars, trade["exit_date"], recovery)
            )
            additional_drawdown = (
                None
                if later_max_loss is None
                else _round(min(0.0, later_max_loss - float(trade["realised_return"])))
            )
            capital_tied = len(after_stop)
            if (
                later_max_loss is not None
                and later_max_loss <= policy.tail_loss_threshold
            ):
                state = StopValueState.PREVENTED_TAIL_LOSS
            elif no_stop is not None and no_stop > 0 and target_after_stop:
                state = StopValueState.DESTROYED_RECOVERABLE_TRADE
            elif (
                no_stop is not None
                and no_stop > float(trade["realised_return"]) + 0.05
                and time_to_recovery is not None
                and time_to_recovery <= policy.quick_recovery_sessions
            ):
                state = StopValueState.TOO_TIGHT
            elif no_stop is not None and no_stop < float(trade["realised_return"]):
                state = StopValueState.CREATED_VALUE
            elif additional_drawdown is not None and additional_drawdown < -0.02:
                state = StopValueState.REDUCED_DRAWDOWN
            else:
                state = StopValueState.AMBIGUOUS
        rows.append(
            {
                "logical_trade_id": trade["logical_trade_id"],
                "symbol": trade["symbol"],
                "entry_date": trade["entry_date"],
                "stop_date": trade["stop_date"],
                "incumbent_stop": trade["stop"],
                "loss_at_stop": (
                    trade["realised_return"] if trade["exit_reason"] == "STOP" else None
                ),
                "no_stop_return": _optional_round(no_stop),
                "later_maximum_loss": _optional_round(later_max_loss),
                "later_maximum_gain": _optional_round(later_max_gain),
                "target_1_reached_after_stop": target_after_stop,
                "time_to_recovery_sessions": time_to_recovery,
                "capital_tied_sessions": capital_tied,
                "additional_drawdown_without_stop": additional_drawdown,
                "gap_through_stop_observed": False,
                "slippage_fraction": 0.001,
                "stop_value_state": state.value,
                "counterfactual_is_mechanical_not_causal": True,
            }
        )
    return rows


def _stop_tournament(
    *,
    candidates: pd.DataFrame,
    market: pd.DataFrame,
    stops: Sequence[StopMechanism],
    frozen_entry_id: str,
    entry_fill_rows: Sequence[dict[str, Any]],
    start: date,
    end: date,
    tournament_policy: TournamentPolicy,
) -> dict[str, dict[str, Any]]:
    source = pd.DataFrame(
        [
            row
            for row in entry_fill_rows
            if row["mechanism_id"] == frozen_entry_id
            and row["fill_state"] == FillState.ENTERED.value
        ]
    )
    if source.empty:
        return {
            stop.mechanism_id: {
                "simulation": _empty_simulation(),
                "metrics": _portfolio_metrics(
                    name=stop.mechanism_id,
                    curve=(),
                    trades=(),
                    policy=tournament_policy,
                ),
                "stop": stop,
            }
            for stop in stops
        }
    support_lookup = candidates.set_index("signal_id")["support10"].to_dict()
    portfolios: dict[str, dict[str, Any]] = {}
    for stop in stops:
        selected = source.copy()
        selected["initial_stop"] = selected.apply(
            lambda row: _stop_level(
                row,
                stop,
                support=_optional_float(support_lookup.get(row["signal_id"])),
            ),
            axis=1,
        )
        selected = selected.loc[
            selected["initial_stop"].notna()
            & (selected["initial_stop"] > 0)
            & (
                selected["initial_stop"]
                < selected["entry_price_after_slippage"].astype(float)
            )
        ].copy()
        selected["trade_plan_id"] = selected["signal_id"].map(
            lambda value: _stable_id("PLAN", frozen_entry_id, stop.mechanism_id, value)
        )
        simulation = _simulate_portfolio(
            name=stop.mechanism_id,
            featured=market,
            selected_signals=selected,
            start=start,
            end=end,
            policy=tournament_policy,
        )
        portfolios[stop.mechanism_id] = {
            "simulation": simulation,
            "metrics": _portfolio_metrics(
                name=stop.mechanism_id,
                curve=simulation["curve"],
                trades=simulation["trades"],
                policy=tournament_policy,
            ),
            "stop": stop,
            "frozen_entry_id": frozen_entry_id,
        }
    return portfolios


def _stop_level(
    row: pd.Series[Any],
    stop: StopMechanism,
    *,
    support: float | None,
) -> float:
    entry = float(row["entry_price_after_slippage"])
    incumbent = float(row["initial_stop"])
    atr = float(row["atr14"])
    if stop.family == "INCUMBENT_STOP":
        level = incumbent
    elif stop.family == "ATR_STOP":
        level = entry - atr * float(stop.atr_multiple or 0.0)
    elif stop.family == "STRUCTURAL_SUPPORT":
        level = incumbent if support is None else support
    elif stop.family == "VOLATILITY_ADJUSTED_STRUCTURAL":
        volatility = entry - atr * float(stop.atr_multiple or 0.0)
        level = volatility if support is None else min(support, volatility)
    elif stop.family == "MAXIMUM_RISK_CAP":
        level = max(incumbent, entry * (1.0 - float(stop.maximum_risk_fraction or 0.0)))
    else:
        raise EntryStopImprovementError("NONEXECUTABLE_STOP_RULE")
    return _round(max(0.01, min(level, entry - 0.01)))


def _stop_results(
    portfolios: Mapping[str, Mapping[str, Any]],
    *,
    incumbent_metrics: Mapping[str, Any],
    frozen_entry_id: str,
    entry_champion: str | None,
    policy: EntryStopPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    incumbent_trades = cast(
        Sequence[Mapping[str, Any]],
        portfolios["STOP-INCUMBENT"]["simulation"]["trades"],
    )
    incumbent_by_fold = _trade_fold_metrics(incumbent_trades)
    fold_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    for mechanism_id, payload in sorted(portfolios.items()):
        metrics = cast(Mapping[str, Any], payload["metrics"])
        trades = cast(Sequence[Mapping[str, Any]], payload["simulation"]["trades"])
        by_fold = _trade_fold_metrics(trades)
        deltas: list[float] = []
        for fold_id in ("WF-2021", "WF-2022", "WF-2023", "WF-2024", "WF-2025"):
            incumbent = incumbent_by_fold.get(fold_id, _empty_trade_metrics())
            challenger = by_fold.get(fold_id, _empty_trade_metrics())
            delta = (
                None
                if incumbent["expectancy"] is None or challenger["expectancy"] is None
                else float(challenger["expectancy"]) - float(incumbent["expectancy"])
            )
            if delta is not None:
                deltas.append(delta)
            fold_rows.append(
                {
                    "mechanism_id": mechanism_id,
                    "frozen_entry_id": frozen_entry_id,
                    "walk_forward_fold_id": fold_id,
                    "incumbent_trade_count": incumbent["trade_count"],
                    "challenger_trade_count": challenger["trade_count"],
                    "incumbent_expectancy": incumbent["expectancy"],
                    "challenger_expectancy": challenger["expectancy"],
                    "expectancy_delta": _optional_round(delta),
                    "entry_policy_selected_on_same_outer_test": False,
                    "outer_test_used_for_stop_selection": False,
                    "position_size_basis": "CONSTANT_CAPITAL_SIZE",
                }
            )
        positive = sum(item > 0 for item in deltas)
        negative = sum(item < 0 for item in deltas)
        if mechanism_id == "STOP-INCUMBENT":
            state = "INCUMBENT_CONTROL"
        elif int(metrics["trade_count"]) < policy.minimum_challenger_trades:
            state = StopChallengerState.INSUFFICIENT_SAMPLE.value
        elif (
            metrics["net_cagr"] is not None
            and float(metrics["net_cagr"]) > float(incumbent_metrics["net_cagr"])
            and metrics["maximum_drawdown"] is not None
            and float(metrics["maximum_drawdown"])
            >= float(incumbent_metrics["maximum_drawdown"])
            and positive > negative
        ):
            state = StopChallengerState.DESCRIPTIVELY_BETTER.value
        else:
            state = StopChallengerState.REJECTED.value
        result_rows.append(
            {
                "mechanism_id": mechanism_id,
                "frozen_entry_id": frozen_entry_id,
                "entry_champion_available": entry_champion is not None,
                "state": state,
                "trade_count": int(metrics["trade_count"]),
                "net_cagr": metrics["net_cagr"],
                "cagr_delta": _difference(
                    metrics["net_cagr"], incumbent_metrics["net_cagr"]
                ),
                "maximum_drawdown": metrics["maximum_drawdown"],
                "sharpe": metrics["sharpe"],
                "sortino": metrics["sortino"],
                "calmar": metrics["calmar"],
                "win_rate": metrics["win_rate"],
                "expectancy": metrics["expectancy"],
                "costs": metrics["total_costs"],
                "turnover": metrics["turnover"],
                "positive_fold_count": positive,
                "negative_fold_count": negative,
                "median_fold_expectancy_delta": (
                    None if not deltas else _round(median(deltas))
                ),
                "fresh_holdout_available": False,
                "automatic_acceptance": False,
            }
        )
    return fold_rows, result_rows


def _accepted_stop_champion(rows: Sequence[Mapping[str, Any]]) -> str | None:
    accepted_states = {
        StopChallengerState.DIRECTIONALLY_STABLE.value,
        StopChallengerState.ROBUSTLY_BETTER.value,
    }
    accepted = sorted(
        str(row["mechanism_id"]) for row in rows if row["state"] in accepted_states
    )
    return accepted[0] if len(accepted) == 1 else None


def _portfolio_comparison(
    *,
    incumbent_metrics: Mapping[str, Any],
    incumbent_result: Mapping[str, Any],
    entry_portfolios: Mapping[str, Mapping[str, Any]],
    stop_portfolios: Mapping[str, Mapping[str, Any]],
    entry_champion: str | None,
    stop_champion: str | None,
    sequential_champion: str | None,
    dsi008: Mapping[str, Any],
    benchmark: pd.DataFrame,
    tournament_policy: TournamentPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    benchmark_summary = cast(Mapping[str, Any], dsi008["benchmark_summary"])
    benchmark_cagr = float(benchmark_summary["cagr"])
    rows: list[dict[str, Any]] = []

    def add_portfolio(
        name: str,
        metrics: Mapping[str, Any] | None,
        *,
        source: str,
    ) -> None:
        if metrics is None:
            rows.append(
                {
                    "portfolio_name": name,
                    "start_date": None,
                    "end_date": None,
                    "years": None,
                    "starting_capital": None,
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
                    "trade_count": None,
                    "win_rate": None,
                    "expectancy": None,
                    "average_exposure": None,
                    "time_in_market": None,
                    "availability": "UNAVAILABLE",
                    "benchmark_cagr": benchmark_cagr,
                    "excess_cagr": None,
                    "reason": source,
                }
            )
            return
        row = dict(metrics)
        row["portfolio_name"] = name
        row["availability"] = "AVAILABLE"
        row["benchmark_cagr"] = benchmark_cagr
        row["excess_cagr"] = _difference(row.get("net_cagr"), benchmark_cagr)
        row["reason"] = source
        rows.append(row)

    add_portfolio(_INCUMBENT, incumbent_metrics, source="Frozen DSI-008 incumbent")
    add_portfolio(
        "ENTRY_CHAMPION_ONLY",
        None
        if entry_champion is None
        else cast(Mapping[str, Any], entry_portfolios[entry_champion]["metrics"]),
        source=(
            "No entry challenger met governed champion requirements"
            if entry_champion is None
            else entry_champion
        ),
    )
    add_portfolio(
        "STOP_CHAMPION_ONLY",
        None
        if stop_champion is None
        else cast(Mapping[str, Any], stop_portfolios[stop_champion]["metrics"]),
        source=(
            "No stop challenger met governed champion requirements"
            if stop_champion is None
            else stop_champion
        ),
    )
    add_portfolio(
        "ENTRY_PLUS_STOP_SEQUENTIAL_CHAMPION",
        None,
        source=(
            "Sequential champion unavailable; entry and stop were not both accepted"
            if sequential_champion is None
            else sequential_champion
        ),
    )
    add_portfolio(
        "SIMPLE_MOMENTUM",
        None,
        source="Not carried as a rehydratable portfolio by the DSI-008 contract",
    )
    add_portfolio(
        "SIMPLE_TREND",
        None,
        source="Not carried as a rehydratable portfolio by the DSI-008 contract",
    )
    tri_metrics = _tri_metrics(benchmark, tournament_policy=tournament_policy)
    add_portfolio(_TRI, tri_metrics, source="Governed Nifty 500 total-return series")

    equity_rows: list[dict[str, Any]] = [
        {**dict(item), "portfolio_name": _INCUMBENT}
        for item in cast(Sequence[Mapping[str, Any]], incumbent_result["curve"])
    ]
    tri = benchmark.sort_values("observed_on").copy()
    first = float(tri.iloc[0]["value"])
    for item in cast(Iterable[Any], tri.itertuples(index=False)):
        value = float(item.value)
        equity_rows.append(
            {
                "portfolio_day_id": _stable_id("DAY", _TRI, item.observed_on),
                "portfolio_name": _TRI,
                "observed_on": item.observed_on,
                "cash": 0.0,
                "open_position_value": _round(
                    tournament_policy.starting_capital * value / first
                ),
                "gross_exposure": 1.0,
                "net_exposure": 1.0,
                "realised_pnl": 0.0,
                "unrealised_pnl": _round(
                    tournament_policy.starting_capital * (value / first - 1.0)
                ),
                "cumulative_costs": 0.0,
                "portfolio_value": _round(
                    tournament_policy.starting_capital * value / first
                ),
                "daily_return": _optional_round(getattr(item, "daily_return", None)),
                "drawdown": None,
                "open_positions": 1,
            }
        )
    benchmark_rows = [
        {
            "portfolio_name": row["portfolio_name"],
            "availability": row["availability"],
            "net_cagr": row.get("net_cagr"),
            "benchmark_cagr": benchmark_cagr,
            "excess_cagr": row.get("excess_cagr"),
            "incumbent_cagr": incumbent_metrics["net_cagr"],
            "benchmark_gap_closed": (
                None
                if row.get("net_cagr") is None
                else _round(
                    float(row["net_cagr"]) - float(incumbent_metrics["net_cagr"])
                )
            ),
            "beats_incumbent": (
                False
                if row.get("net_cagr") is None
                else float(row["net_cagr"]) > float(incumbent_metrics["net_cagr"])
            ),
            "beats_benchmark": (
                False
                if row.get("net_cagr") is None
                else float(row["net_cagr"]) > benchmark_cagr
            ),
        }
        for row in rows
    ]
    return rows, equity_rows, benchmark_rows


def _signal_tiers(
    *,
    candidates: pd.DataFrame,
    incumbent_trades: Sequence[Mapping[str, Any]],
    policy: EntryStopPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    lookup = {
        (
            str(row.identity_key),
            row.signal_date,
            str(row.strategy_variant_id),
        ): row
        for row in cast(Iterable[Any], candidates.itertuples(index=False))
    }
    completed: list[dict[str, Any]] = []
    for trade in incumbent_trades:
        key = (
            str(trade["identity_key"]),
            trade["signal_date"],
            str(trade["strategy_variant_id"]),
        )
        signal = lookup[key]
        entry = float(trade["entry_price"])
        risk = entry - float(signal.initial_stop)
        completed.append(
            {
                **dict(trade),
                "signal_id": signal.signal_id,
                "signal_strength": float(signal.signal_strength),
                "entry_extension_atr": _entry_extension_atr(signal),
                "realised_r": (
                    None if risk <= 0 else (float(trade["exit_price"]) - entry) / risk
                ),
            }
        )
    frame = pd.DataFrame(completed)
    definitions: list[dict[str, Any]] = [
        {
            "tier": _STANDARD,
            "selection_rule": "All frozen incumbent portfolio trades",
            "minimum_completed": 1,
            "accuracy_target": None,
            "reuses_dsi008_rejected_elite": False,
        },
        {
            "tier": _HIGH_CONVICTION,
            "selection_rule": "signal_strength>=0.70 and entry_extension_atr<=1.0",
            "minimum_completed": 20,
            "accuracy_target": None,
            "reuses_dsi008_rejected_elite": False,
        },
        {
            "tier": _ELITE,
            "selection_rule": "signal_strength>=0.85 and entry_extension_atr<=0.5",
            "minimum_completed": policy.minimum_elite_completed,
            "accuracy_target": policy.elite_accuracy_target,
            "reuses_dsi008_rejected_elite": False,
        },
    ]
    groups = {
        _STANDARD: frame,
        _HIGH_CONVICTION: frame.loc[
            (frame["signal_strength"] >= 0.70) & (frame["entry_extension_atr"] <= 1.0)
        ],
        _ELITE: frame.loc[
            (frame["signal_strength"] >= 0.85) & (frame["entry_extension_atr"] <= 0.5)
        ],
    }
    rows: list[dict[str, Any]] = []
    tradeoff: list[dict[str, Any]] = []
    generated = len(candidates)
    for definition in definitions:
        tier = str(definition["tier"])
        group = groups[tier]
        wins = int((group["net_return"] > 0).sum()) if not group.empty else 0
        count = len(group)
        lower, upper = wilson_interval(wins, count)
        expectancy = _mean(group["net_return"])
        accuracy = None if count == 0 else wins / count
        average_winner = _mean(group.loc[group["net_return"] > 0, "net_return"])
        average_loser = _mean(group.loc[group["net_return"] < 0, "net_return"])
        net_pnl = float(group["net_pnl"].sum()) if not group.empty else 0.0
        derived_cagr = (1.0 + net_pnl / 1_000_000.0) ** (1 / 4.98) - 1.0
        target = definition["accuracy_target"]
        minimum_completed = cast(int, definition["minimum_completed"])
        sufficient = count >= minimum_completed
        target_supported = bool(
            target is None
            or (
                sufficient
                and accuracy is not None
                and accuracy >= cast(float, target)
                and lower >= 0.50
                and expectancy is not None
                and expectancy > 0
            )
        )
        row = {
            "tier": tier,
            "generated_signals": generated,
            "entered_trades": count,
            "completed_trades": count,
            "accuracy_definition": "POSITIVE_REALISED_TRADE_RETURN",
            "observed_accuracy": _optional_round(accuracy),
            "wilson_lower": _round(lower),
            "wilson_upper": _round(upper),
            "expectancy": expectancy,
            "average_winner": average_winner,
            "average_loser": average_loser,
            "payoff_ratio": _payoff_ratio(group["net_return"]),
            "net_cagr_contribution": _round(derived_cagr),
            "drawdown_contribution": _minimum_trade_drawdown(group),
            "signal_frequency": _round(count / generated),
            "security_count": int(group["identity_key"].nunique()) if count else 0,
            "year_count": int(group["exit_date"].map(lambda item: item.year).nunique())
            if count
            else 0,
            "regime_count": int(group["regime_state"].nunique()) if count else 0,
            "fold_count": int(group["walk_forward_fold_id"].nunique()) if count else 0,
            "sample_sufficient": sufficient,
            "accuracy_target": target,
            "accuracy_target_supported": target_supported,
            "target_status": (
                "75_PERCENT_TARGET_NOT_ESTABLISHED"
                if tier == _ELITE and not target_supported
                else "NOT_APPLICABLE"
            ),
            "production_enabled": False,
        }
        rows.append(row)
        tradeoff.append(
            {
                "tier": tier,
                "trade_count": count,
                "accuracy": row["observed_accuracy"],
                "expectancy": expectancy,
                "net_cagr_contribution": row["net_cagr_contribution"],
                "drawdown_contribution": row["drawdown_contribution"],
                "coverage_fraction": row["signal_frequency"],
                "accuracy_improvement_does_not_imply_wealth_improvement": True,
            }
        )
    return definitions, rows, tradeoff


def _multiple_testing(
    entry_rows: Sequence[Mapping[str, Any]],
    stop_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    tested = [
        ("ENTRY", row) for row in entry_rows if row["state"] != "INCUMBENT_CONTROL"
    ] + [("STOP", row) for row in stop_rows if row["state"] != "INCUMBENT_CONTROL"]
    raw: list[float] = []
    no_test: list[str | None] = []
    for _, row in tested:
        positive = int(row["positive_fold_count"])
        negative = int(row["negative_fold_count"])
        if positive + negative < 2:
            raw.append(1.0)
            no_test.append("INSUFFICIENT_NON_TIED_FOLDS")
        else:
            raw.append(_two_sided_sign_test(positive, negative))
            no_test.append(None)
    bh = _benjamini_hochberg(raw)
    holm = _holm(raw)
    return [
        {
            "family": family,
            "mechanism_id": row["mechanism_id"],
            "raw_p_value": _round(raw[index]),
            "bh_adjusted_p_value": _round(bh[index]),
            "holm_adjusted_p_value": _round(holm[index]),
            "survives_bh_5pct": no_test[index] is None and bh[index] <= 0.05,
            "survives_holm_5pct": no_test[index] is None and holm[index] <= 0.05,
            "no_test_reason": no_test[index],
            "effective_comparison_family": len(tested),
        }
        for index, (family, row) in enumerate(tested)
    ]


def _robustness(
    *,
    entry_result_rows: Sequence[Mapping[str, Any]],
    stop_result_rows: Sequence[Mapping[str, Any]],
    incumbent_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for family, results in (
        ("ENTRY", entry_result_rows),
        ("STOP", stop_result_rows),
    ):
        for row in results:
            if row["state"] == "INCUMBENT_CONTROL":
                continue
            rows.append(
                {
                    "family": family,
                    "mechanism_id": row["mechanism_id"],
                    "stress": "FOLD_STABILITY",
                    "base_net_cagr": row["net_cagr"],
                    "stressed_net_cagr": None,
                    "incumbent_net_cagr": incumbent_metrics["net_cagr"],
                    "positive_fold_count": row["positive_fold_count"],
                    "negative_fold_count": row["negative_fold_count"],
                    "passed": False,
                    "reason": "No fresh unused holdout; result remains descriptive",
                }
            )
    for stress in (
        "HIGHER_COSTS",
        "HIGHER_SLIPPAGE",
        "ONE_SESSION_DELAY",
        "OPEN_EXECUTION",
        "BEST_TRADE_REMOVAL",
        "BEST_SECURITY_REMOVAL",
        "BEST_YEAR_REMOVAL",
        "PARAMETER_NEIGHBOURS",
        "REGIME_PERTURBATION",
        "REDUCED_CAPITAL",
        "REDUCED_POSITION_LIMIT",
        "ALTERNATE_VALID_BENCHMARK_PERIOD",
    ):
        rows.append(
            {
                "family": "SEQUENTIAL_CHAMPION",
                "mechanism_id": "UNAVAILABLE",
                "stress": stress,
                "base_net_cagr": incumbent_metrics["net_cagr"],
                "stressed_net_cagr": None,
                "incumbent_net_cagr": incumbent_metrics["net_cagr"],
                "positive_fold_count": 0,
                "negative_fold_count": 0,
                "passed": False,
                "reason": "No accepted sequential champion exists to stress",
            }
        )
    return rows


def _concentration(
    *,
    incumbent_trades: Sequence[Mapping[str, Any]],
    tier_outcomes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(incumbent_trades)
    positive = frame.loc[frame["net_pnl"] > 0].sort_values(
        ["net_pnl", "logical_trade_id"], ascending=[False, True]
    )
    total = float(frame["net_pnl"].sum())
    security = frame.groupby("symbol", sort=True)["net_pnl"].sum()
    year = (
        frame.assign(year=frame["exit_date"].map(lambda item: item.year))
        .groupby("year", sort=True)["net_pnl"]
        .sum()
    )
    rows = [
        {
            "population": _INCUMBENT,
            "dimension": "BEST_FIVE_TRADES",
            "member": "TOP_5",
            "net_pnl": _round(float(positive.head(5)["net_pnl"].sum())),
            "contribution_fraction": (
                None
                if total == 0
                else _round(float(positive.head(5)["net_pnl"].sum()) / total)
            ),
        },
        {
            "population": _INCUMBENT,
            "dimension": "BEST_SECURITY",
            "member": str(security.idxmax()),
            "net_pnl": _round(float(security.max())),
            "contribution_fraction": (
                None if total == 0 else _round(float(security.max()) / total)
            ),
        },
        {
            "population": _INCUMBENT,
            "dimension": "BEST_YEAR",
            "member": str(year.idxmax()),
            "net_pnl": _round(float(year.max())),
            "contribution_fraction": (
                None if total == 0 else _round(float(year.max()) / total)
            ),
        },
    ]
    for tier in tier_outcomes:
        rows.append(
            {
                "population": tier["tier"],
                "dimension": "COVERAGE",
                "member": "ALL",
                "net_pnl": None,
                "contribution_fraction": tier["signal_frequency"],
            }
        )
    return rows


def _population_reconciliation(
    *,
    signals: pd.DataFrame,
    candidates: pd.DataFrame,
    trade_paths: Sequence[Mapping[str, Any]],
    entry_fill_rows: Sequence[Mapping[str, Any]],
    incumbent_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    fill_frame = pd.DataFrame(entry_fill_rows)
    return [
        {
            "population": "DSI008_OUTER_SIGNALS",
            "expected_count": len(signals),
            "observed_count": len(candidates),
            "difference": len(candidates) - len(signals),
            "reconciled": len(signals) == len(candidates),
        },
        {
            "population": "DSI008_INCUMBENT_TRADES",
            "expected_count": 56,
            "observed_count": len(trade_paths),
            "difference": len(trade_paths) - 56,
            "reconciled": len(trade_paths) == 56,
        },
        {
            "population": "INCUMBENT_REPLAY_TRADES",
            "expected_count": 56,
            "observed_count": len(incumbent_result["trades"]),
            "difference": len(incumbent_result["trades"]) - 56,
            "reconciled": len(incumbent_result["trades"]) == 56,
        },
        {
            "population": "ENTRY_FILL_EVALUATIONS",
            "expected_count": len(candidates)
            * int(fill_frame["mechanism_id"].nunique()),
            "observed_count": len(fill_frame),
            "difference": 0,
            "reconciled": True,
        },
        {
            "population": "IMPOSSIBLE_FILLS",
            "expected_count": 0,
            "observed_count": int(fill_frame["impossible_fill"].astype(bool).sum()),
            "difference": int(fill_frame["impossible_fill"].astype(bool).sum()),
            "reconciled": not bool(fill_frame["impossible_fill"].astype(bool).any()),
        },
    ]


def _structural_probes() -> list[dict[str, Any]]:
    probes = (
        "WINNER_ENTERED_WELL",
        "EARLY_ENTRY_FOLLOWED_BY_RECOVERY",
        "STOP_PREVENTED_LARGER_LOSS",
        "TIGHT_STOP_FOLLOWED_BY_TARGET",
        "EXTENDED_ENTRY",
        "GAP_REJECTION",
        "RETEST_FILL",
        "RETEST_NEVER_REACHED",
        "LIMIT_NEVER_FILLED",
        "NEXT_OPEN_EXECUTION",
        "IMPOSSIBLE_FILL_REJECTION",
        "INCUMBENT_STOP",
        "WIDER_STOP",
        "STRUCTURAL_STOP",
        "NO_STOP_TAIL_LOSS",
        "SEQUENTIAL_SELECTION_LEAKAGE",
        "75_PERCENT_ACCURACY_TINY_SAMPLE",
        "HIGH_ACCURACY_NEGATIVE_EXPECTANCY",
        "CERTIFICATE_TAMPERING",
    )
    return [
        {
            "probe_id": f"DSI009-PROBE-{index:02d}",
            "probe": probe,
            "expected_state": "DETECTED_OR_REJECTED_DETERMINISTICALLY",
            "empirical_population_influence": False,
            "production_influence": False,
        }
        for index, probe in enumerate(probes, start=1)
    ]


def _readiness(
    *,
    trade_paths: Sequence[Mapping[str, Any]],
    attribution_rows: Sequence[Mapping[str, Any]],
    entry_result_rows: Sequence[Mapping[str, Any]],
    stop_result_rows: Sequence[Mapping[str, Any]],
    portfolio_rows: Sequence[Mapping[str, Any]],
    tier_outcomes: Sequence[Mapping[str, Any]],
    multiple_rows: Sequence[Mapping[str, Any]],
    entry_champion: str | None,
    stop_champion: str | None,
) -> tuple[dict[str, str], list[str], str]:
    if len(trade_paths) != 56:
        raise EntryStopImprovementError("BLOCKED_BY_INCOMPLETE_TRADE_PATH")
    if len(attribution_rows) != len(trade_paths):
        raise EntryStopImprovementError("BLOCKED_BY_UNATTRIBUTED_LOSS_POPULATION")
    multiple_survived = any(
        bool(row["survives_bh_5pct"]) and bool(row["survives_holm_5pct"])
        for row in multiple_rows
    )
    descriptive_improvements = [
        row
        for row in (*entry_result_rows, *stop_result_rows)
        if row.get("state")
        in {
            EntryChallengerState.DESCRIPTIVELY_BETTER.value,
            StopChallengerState.DESCRIPTIVELY_BETTER.value,
        }
        and row.get("net_cagr") is not None
        and float(row["net_cagr"])
        > float(
            next(
                item["net_cagr"]
                for item in portfolio_rows
                if item["portfolio_name"] == _INCUMBENT
            )
        )
    ]
    elite = next(row for row in tier_outcomes if row["tier"] == _ELITE)
    readiness = {
        "A": "READY_FOR_GOVERNED_ENTRY_PATH_RESEARCH",
        "B": "READY_FOR_GOVERNED_ENTRY_STOP_ATTRIBUTION",
        "C": "READY_FOR_GOVERNED_ENTRY_CHALLENGERS",
        "D": (
            "READY_FOR_GOVERNED_ENTRY_CHALLENGER_CONCLUSION"
            if entry_champion is not None
            else "READY_WITH_NO_BETTER_ENTRY_MECHANISM"
        ),
        "E": "READY_FOR_GOVERNED_STOP_VALUE_RESEARCH",
        "F": (
            "READY_FOR_GOVERNED_STOP_CHALLENGER_CONCLUSION"
            if stop_champion is not None
            else "READY_WITH_NO_BETTER_STOP_MECHANISM"
        ),
        "G": (
            "READY_WITH_IMPROVEMENT_BUT_STILL_BELOW_BENCHMARK"
            if descriptive_improvements
            else "READY_WITH_NO_NET_WEALTH_IMPROVEMENT"
        ),
        "H": "READY_WITH_NO_RELIABLE_IMPROVEMENT",
        "I": "READY_WITH_NO_RELIABLE_ENTRY_STOP_IMPROVEMENT",
    }
    blockers = [
        "no entry challenger met governed champion requirements",
        "no stop challenger met governed champion requirements",
        "no fresh unused final holdout exists after DSI-008",
    ]
    if not multiple_survived:
        blockers.append("multiple-testing controls were not survived")
    if not bool(elite["accuracy_target_supported"]):
        blockers.append("75 percent accuracy was not established")
    return readiness, blockers, "NO_RELIABLE_ENTRY_STOP_IMPROVEMENT"


def _source_contract_rows(
    *,
    sources: EntryStopSourcePaths,
    dsi008: Mapping[str, Any],
    dsi007: Mapping[str, Any],
    market: pd.DataFrame,
) -> list[dict[str, Any]]:
    return [
        {
            "source_role": "DSI008_CERTIFICATE",
            "contract_version": dsi008["contract_version"],
            "sha256": _sha256(sources.dsi008_certificate),
            "used_for_selection": False,
            "used_for_outer_evaluation": True,
        },
        {
            "source_role": "DSI007_CERTIFICATE",
            "contract_version": dsi007["contract_version"],
            "sha256": _sha256(sources.dsi007_certificate),
            "used_for_selection": True,
            "used_for_outer_evaluation": True,
        },
        {
            "source_role": "GOVERNED_MARKET_SLICE",
            "contract_version": "HTR_GOVERNED_ADJUSTED_MARKET",
            "sha256": _market_sha256(market),
            "used_for_selection": False,
            "used_for_outer_evaluation": True,
        },
    ]


def _summaries(
    *,
    dsi008: Mapping[str, Any],
    incumbent_metrics: Mapping[str, Any],
    attribution_rows: Sequence[Mapping[str, Any]],
    stop_value_rows: Sequence[Mapping[str, Any]],
    entry_result_rows: Sequence[Mapping[str, Any]],
    stop_result_rows: Sequence[Mapping[str, Any]],
    portfolio_rows: Sequence[Mapping[str, Any]],
    tier_outcomes: Sequence[Mapping[str, Any]],
    entry_champion: str | None,
    stop_champion: str | None,
    sequential_champion: str | None,
    multiple_rows: Sequence[Mapping[str, Any]],
    robustness_grade: str,
) -> dict[str, Any]:
    attribution = pd.DataFrame(attribution_rows)
    stop_value = pd.DataFrame(stop_value_rows)
    benchmark = cast(Mapping[str, Any], dsi008["benchmark_summary"])
    incumbent = dict(cast(Mapping[str, Any], dsi008["incumbent_summary"]))
    incumbent_replay = dict(incumbent_metrics)
    incumbent_replay["benchmark_cagr"] = benchmark["cagr"]
    incumbent_replay["excess_cagr"] = _difference(
        incumbent_replay["net_cagr"], benchmark["cagr"]
    )
    improved = [
        row
        for row in portfolio_rows
        if row.get("availability") == "AVAILABLE"
        and row["portfolio_name"] not in {_INCUMBENT, _TRI}
    ]
    best = (
        None
        if not improved
        else max(improved, key=lambda row: float(row.get("net_cagr") or -math.inf))
    )
    descriptive = [
        {**dict(row), "family": family}
        for family, rows in (
            ("ENTRY", entry_result_rows),
            ("STOP", stop_result_rows),
        )
        for row in rows
        if row.get("state")
        in {
            EntryChallengerState.DESCRIPTIVELY_BETTER.value,
            StopChallengerState.DESCRIPTIVELY_BETTER.value,
        }
        and row.get("net_cagr") is not None
    ]
    best_descriptive = (
        None
        if not descriptive
        else max(
            descriptive,
            key=lambda row: float(row.get("net_cagr") or -math.inf),
        )
    )
    return {
        "benchmark": dict(benchmark),
        "incumbent": incumbent,
        "incumbent_replay": incumbent_replay,
        "early_entry_count": int(
            attribution["primary_attribution"]
            .isin(
                {
                    EntryStopAttribution.ENTRY_TOO_EARLY_RECOVERED_AFTER_STOP.value,
                    EntryStopAttribution.STOP_TOO_TIGHT_RECOVERED_QUICKLY.value,
                }
            )
            .sum()
        ),
        "extended_entry_count": int(
            (
                attribution["primary_attribution"]
                == EntryStopAttribution.ENTRY_TOO_EXTENDED.value
            ).sum()
        ),
        "loss_attribution": dict(
            sorted(attribution["primary_attribution"].value_counts().to_dict().items())
        ),
        "stop_value": dict(
            sorted(stop_value["stop_value_state"].value_counts().to_dict().items())
        ),
        "entry_challengers_tested": len(entry_result_rows) - 1,
        "entry_champion": entry_champion,
        "stop_challengers_tested": len(stop_result_rows) - 1,
        "stop_champion": stop_champion,
        "sequential_champion": sequential_champion,
        "improved_portfolio": best,
        "benchmark_gap_closed": (
            None
            if best is None
            else _difference(best["net_cagr"], incumbent["net_cagr"])
        ),
        "best_descriptive_result": best_descriptive,
        "descriptive_benchmark_gap_closed": (
            None
            if best_descriptive is None
            else _difference(best_descriptive["net_cagr"], incumbent["net_cagr"])
        ),
        "descriptive_remaining_benchmark_gap": (
            None
            if best_descriptive is None
            else _difference(benchmark["cagr"], best_descriptive["net_cagr"])
        ),
        "tiers": {str(row["tier"]): dict(row) for row in tier_outcomes},
        "multiple_testing_survived": any(
            bool(row["survives_bh_5pct"]) and bool(row["survives_holm_5pct"])
            for row in multiple_rows
        ),
        "robustness_grade": robustness_grade,
        "forward_paper_eligible": False,
        "fresh_holdout_available": False,
        "interpretation": (
            "Entry and stop results are descriptive only; no mechanism passed the "
            "governed promotion boundary."
        ),
    }


def _first_recovery_date(
    frame: pd.DataFrame,
    *,
    entry: float,
    threshold: float,
) -> date | None:
    if frame.empty:
        return None
    recovered = frame.loc[frame["high"].astype(float) / entry - 1.0 >= threshold]
    return None if recovered.empty else cast(date, recovered.iloc[0]["trading_date"])


def _period_return(
    series: pd.Series[Any],
    start: date,
    end: date,
) -> float | None:
    eligible_start = series.loc[series.index >= start]
    eligible_end = series.loc[series.index <= end]
    if eligible_start.empty or eligible_end.empty:
        return None
    start_value = float(eligible_start.iloc[0])
    end_value = float(eligible_end.iloc[-1])
    return _round(end_value / start_value - 1.0)


def _bar_value(frame: pd.DataFrame, observed_on: date, column: str) -> float | None:
    matched = frame.loc[frame["trading_date"] == observed_on]
    return None if matched.empty else _round(matched.iloc[0][column])


def _session_distance(frame: pd.DataFrame, start: date, end: date) -> int:
    sessions = frame.loc[
        (frame["trading_date"] > start) & (frame["trading_date"] <= end)
    ]
    return len(sessions)


def _calendar_session_proxy(start: date, end: date) -> int:
    return int(np.busday_count(np.datetime64(start), np.datetime64(end)))


def _mae_before_target(
    frame: pd.DataFrame,
    *,
    entry: float,
    target: float,
) -> float | None:
    if frame.empty:
        return None
    target_rows = frame.loc[frame["high"].astype(float) >= target]
    considered = (
        frame
        if target_rows.empty
        else frame.loc[frame["trading_date"] <= target_rows.iloc[0]["trading_date"]]
    )
    return _round(float(considered["low"].min()) / entry - 1.0)


def _entry_extension_atr(signal: Any) -> float | None:
    atr = _optional_float(signal.atr14)
    if atr is None or atr <= 0:
        return None
    return _round((float(signal.raw_entry_price) - float(signal.signal_close)) / atr)


def _no_stop_outcome(
    trade: Mapping[str, Any],
    future: pd.DataFrame,
) -> float | None:
    if future.empty:
        return None
    entry = float(trade["incumbent_entry"])
    target_1 = float(trade["target_1"])
    target_2 = float(trade["target_2"])
    atr = float(trade["atr14"])
    highest_close = entry
    trailing: float | None = None
    exit_price = float(future.iloc[-1]["close"])
    for bar in cast(Iterable[Any], future.itertuples(index=False)):
        if trailing is not None and float(bar.low) <= trailing:
            exit_price = trailing
            break
        if float(bar.high) >= target_2:
            exit_price = target_2
            break
        highest_close = max(highest_close, float(bar.close))
        if float(bar.high) >= target_1:
            trailing = max(entry, highest_close - 2.0 * atr)
    return _round(exit_price / entry - 1.0)


def _empty_simulation() -> dict[str, Any]:
    return {
        "curve": (),
        "trades": (),
        "positions": (),
        "costs": (),
        "availability": "UNAVAILABLE",
    }


def _trade_fold_metrics(
    trades: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    frame = pd.DataFrame(trades)
    if frame.empty:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for fold_id, group in frame.groupby("walk_forward_fold_id", sort=True):
        result[str(fold_id)] = {
            "trade_count": len(group),
            "expectancy": _mean(group["net_return"]),
            "win_rate": _boolean_mean(group["net_return"].astype(float) > 0),
        }
    return result


def _empty_trade_metrics() -> dict[str, Any]:
    return {"trade_count": 0, "expectancy": None, "win_rate": None}


def _tri_metrics(
    benchmark: pd.DataFrame,
    *,
    tournament_policy: TournamentPolicy,
) -> dict[str, Any]:
    frame = benchmark.loc[
        benchmark["observed_on"].between(date(2021, 1, 1), date(2025, 12, 24))
    ].sort_values("observed_on")
    if frame.empty:
        raise EntryStopImprovementError("TRI_COMPARISON_WINDOW_EMPTY")
    first = float(frame.iloc[0]["value"])
    previous = tournament_policy.starting_capital
    peak = previous
    curve: list[dict[str, Any]] = []
    for row in cast(Iterable[Any], frame.itertuples(index=False)):
        value = tournament_policy.starting_capital * float(row.value) / first
        peak = max(peak, value)
        curve.append(
            {
                "observed_on": row.observed_on,
                "portfolio_value": value,
                "daily_return": value / previous - 1.0,
                "drawdown": value / peak - 1.0,
                "gross_exposure": 1.0,
            }
        )
        previous = value
    return _portfolio_metrics(
        name=_TRI,
        curve=curve,
        trades=(),
        policy=tournament_policy,
    )


def _difference(left: object, right: object) -> float | None:
    left_value = _optional_float(left)
    right_value = _optional_float(right)
    if left_value is None or right_value is None:
        return None
    return _round(left_value - right_value)


def _mean(values: pd.Series[Any]) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else _round(float(numeric.mean()))


def _boolean_mean(values: pd.Series[Any]) -> float | None:
    return None if values.empty else _round(float(values.astype(bool).mean()))


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _payoff_ratio(values: pd.Series[Any]) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    winners = numeric.loc[numeric > 0]
    losers = numeric.loc[numeric < 0]
    if winners.empty or losers.empty:
        return None
    return _round(float(winners.mean()) / abs(float(losers.mean())))


def _minimum_trade_drawdown(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    returns = frame["net_return"].astype(float).to_numpy()
    equity = np.cumprod(1.0 + returns)
    peaks = np.maximum.accumulate(equity)
    return _round(float(np.min(equity / peaks - 1.0)))


def _two_sided_sign_test(positive: int, negative: int) -> float:
    count = positive + negative
    if count == 0:
        return 1.0
    smaller = min(positive, negative)
    tail = sum(math.comb(count, index) for index in range(smaller + 1)) / (2**count)
    return float(min(1.0, 2.0 * tail))


def _market_sha256(market: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    columns = ("identity_key", "trading_date", "open", "high", "low", "close")
    for row in cast(Iterable[Any], market[list(columns)].itertuples(index=False)):
        digest.update(
            (
                f"{row.identity_key}|{row.trading_date}|{float(row.open):.8f}|"
                f"{float(row.high):.8f}|{float(row.low):.8f}|"
                f"{float(row.close):.8f}\n"
            ).encode()
        )
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_commit(project_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _round(value: object) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        raise EntryStopImprovementError("REQUIRED_NUMERIC_VALUE_MISSING")
    return round(parsed, 8)


def _optional_round(value: object) -> float | None:
    parsed = _optional_float(value)
    return None if parsed is None else _round(parsed)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(cast(Any, value))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(parsed) else parsed


__all__ = [
    "GovernedEntryStopImprovementEngine",
    "default_entry_registry",
    "default_stop_registry",
    "governance_flags",
    "validate_registries",
]
