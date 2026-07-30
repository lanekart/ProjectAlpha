"""DSI-012 source-chain rehydration, parity, and capacity evidence."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from numbers import Real
from pathlib import Path
from typing import Any, cast

import pandas as pd

from alpha.decision_superiority.entry_stop_improvement import (
    _candidate_frame,
    _entry_tournament,
    _governed_market,
    _load_dsi007_selections,
    _load_dsi008_ledgers,
    _market_sha256,
    _outer_signals,
    _stable_id,
    _stop_level,
    default_entry_registry,
    default_stop_registry,
)
from alpha.decision_superiority.entry_stop_improvement_artifacts import (
    DSI009_ARTIFACTS,
)
from alpha.decision_superiority.entry_stop_improvement_models import (
    EntryStopPolicy,
    FillState,
)
from alpha.decision_superiority.regime_strategy_models import TournamentPolicy
from alpha.decision_superiority.regime_strategy_tournament import (
    _portfolio_metrics,
    _simulate_portfolio,
)
from alpha.decision_superiority.structural_stop_risk_scaling_models import (
    DSI012_MECHANISM_ID,
    StructuralStopRiskScalingError,
    StructuralStopRiskScalingPolicy,
    StructuralStopRiskScalingSourcePaths,
)


def _validate_source_chain(
    *,
    sources: StructuralStopRiskScalingSourcePaths,
    dsi009: Mapping[str, Any],
) -> None:
    hashes = cast(Mapping[str, Any], dsi009["source_chain_hashes"])
    expected = {
        "DSI008_CERTIFICATE": _sha256(sources.dsi008_certificate),
        "DSI007_CERTIFICATE": _sha256(sources.dsi007_certificate),
    }
    for role, actual in expected.items():
        if str(hashes.get(role)) != actual:
            raise StructuralStopRiskScalingError(
                f"DSI012_SOURCE_CHAIN_HASH_MISMATCH:{role}"
            )


def _rehydrate_structural_stop(
    *,
    sources: StructuralStopRiskScalingSourcePaths,
    dsi008: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any], str]:
    research_policy = EntryStopPolicy()
    tournament_policy = TournamentPolicy()
    ledgers = _load_dsi008_ledgers(sources.dsi008_certificate.parent)
    selections = _load_dsi007_selections(sources.dsi007_certificate.parent)
    signals = _outer_signals(
        ledgers["signals"],
        selections=selections,
        policy=research_policy,
    )
    market = _governed_market(
        sources.database,
        signals,
        start=date.fromisoformat(research_policy.comparison_start),
        end=date.fromisoformat(research_policy.comparison_end),
    )
    market_hash = _market_sha256(market)
    candidates = _candidate_frame(signals, market)
    entry_fill_rows, _ = _entry_tournament(
        candidates=candidates,
        market=market,
        entries=default_entry_registry(),
        start=date.fromisoformat(research_policy.comparison_start),
        end=date.fromisoformat(research_policy.comparison_end),
        tournament_policy=tournament_policy,
        policy=research_policy,
    )
    source = pd.DataFrame(
        [
            row
            for row in entry_fill_rows
            if row["mechanism_id"] == "ENTRY-INCUMBENT-NEXT-OPEN"
            and row["fill_state"] == FillState.ENTERED.value
        ]
    )
    if source.empty:
        raise StructuralStopRiskScalingError("DSI012_INCUMBENT_ENTRY_POPULATION_EMPTY")
    stops = {stop.mechanism_id: stop for stop in default_stop_registry()}
    stop = stops.get(DSI012_MECHANISM_ID)
    if stop is None:
        raise StructuralStopRiskScalingError("DSI012_STRUCTURAL_STOP_NOT_REGISTERED")
    support_lookup = candidates.set_index("signal_id")["support10"].to_dict()
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
        lambda value: _stable_id(
            "PLAN",
            "ENTRY-INCUMBENT-NEXT-OPEN",
            DSI012_MECHANISM_ID,
            value,
        )
    )
    simulation = _simulate_portfolio(
        name=DSI012_MECHANISM_ID,
        featured=market,
        selected_signals=selected,
        start=date.fromisoformat(research_policy.comparison_start),
        end=date.fromisoformat(research_policy.comparison_end),
        policy=tournament_policy,
    )
    metrics = _portfolio_metrics(
        name=DSI012_MECHANISM_ID,
        curve=simulation["curve"],
        trades=simulation["trades"],
        policy=tournament_policy,
    )
    signed_incumbent = cast(Mapping[str, Any], dsi008["incumbent_summary"])
    if (
        float(signed_incumbent["starting_capital"])
        != tournament_policy.starting_capital
    ):
        raise StructuralStopRiskScalingError("DSI012_STARTING_CAPITAL_MISMATCH")
    return selected, simulation, metrics, market_hash


def _validate_market_slice(
    *,
    actual_market_hash: str,
    dsi009: Mapping[str, Any],
) -> None:
    expected = str(
        cast(Mapping[str, Any], dsi009["source_chain_hashes"])["GOVERNED_MARKET_SLICE"]
    )
    if actual_market_hash != expected:
        raise StructuralStopRiskScalingError("DSI012_GOVERNED_MARKET_SLICE_DRIFT")


def _parity_rows(
    *,
    base_metrics: Mapping[str, Any],
    dsi009_certificate: Path,
) -> tuple[list[dict[str, Any]], bool]:
    stop_results_path = (
        dsi009_certificate.resolve().parent / DSI009_ARTIFACTS["stop_results"]
    )
    if not stop_results_path.is_file():
        raise StructuralStopRiskScalingError("DSI012_SIGNED_STOP_RESULTS_UNAVAILABLE")
    stop_results = pd.read_csv(stop_results_path, low_memory=False)
    if "mechanism_id" not in stop_results.columns:
        raise StructuralStopRiskScalingError(
            "DSI012_SIGNED_STOP_RESULTS_SCHEMA_INVALID"
        )
    expected_rows = stop_results.loc[
        stop_results["mechanism_id"].astype(str).eq(DSI012_MECHANISM_ID)
    ]
    if len(expected_rows) != 1:
        raise StructuralStopRiskScalingError(
            f"DSI012_SIGNED_STRUCTURAL_STOP_RESULT_INVALID:{len(expected_rows)}"
        )
    expected = cast(Mapping[str, Any], expected_rows.iloc[0].to_dict())
    tolerances = {
        "net_cagr": 2e-8,
        "maximum_drawdown": 2e-8,
        "calmar": 2e-7,
        "win_rate": 2e-8,
        "expectancy": 2e-8,
        "trade_count": 0.0,
    }
    rows: list[dict[str, Any]] = []
    passed = True
    for metric, tolerance in tolerances.items():
        actual = base_metrics.get(metric)
        target = expected.get(metric)
        delta = (
            None if actual is None or target is None else float(actual) - float(target)
        )
        metric_passed = (
            actual is not None
            and target is not None
            and abs(float(actual) - float(target)) <= tolerance
        )
        passed = passed and metric_passed
        rows.append(
            {
                "metric": metric,
                "expected": target,
                "actual": actual,
                "delta": delta,
                "tolerance": tolerance,
                "passed": metric_passed,
            }
        )
    return rows, passed


def _capacity_ledger(
    *,
    selected: pd.DataFrame,
    trades: Sequence[Mapping[str, Any]],
    policy: StructuralStopRiskScalingPolicy,
    tournament_policy: TournamentPolicy,
) -> list[dict[str, Any]]:
    average_value_by_trade = {
        _stable_id("PORTFOLIO_TRADE", DSI012_MECHANISM_ID, row.trade_plan_id): float(
            row.average_traded_value20
        )
        for row in cast(Iterable[Any], selected.itertuples(index=False))
    }
    rows: list[dict[str, Any]] = []
    for trade in trades:
        logical_trade_id = str(trade["logical_trade_id"])
        average_value = average_value_by_trade.get(logical_trade_id)
        if average_value is None:
            raise StructuralStopRiskScalingError(
                f"DSI012_CAPACITY_LINEAGE_MISSING:{logical_trade_id}"
            )
        base_notional = float(trade["quantity"]) * float(trade["entry_price"])
        scaled_notional = base_notional * policy.risk_multiplier
        capacity_limit = (
            average_value
            * tournament_policy.maximum_market_volume_fraction
            * policy.capacity_multiplier
        )
        utilization = (
            math.inf if capacity_limit <= 0 else scaled_notional / capacity_limit
        )
        rows.append(
            {
                "logical_trade_id": logical_trade_id,
                "symbol": trade["symbol"],
                "entry_date": trade["entry_date"],
                "average_traded_value20": _round(average_value),
                "maximum_market_volume_fraction": (
                    tournament_policy.maximum_market_volume_fraction
                ),
                "capacity_limit": _round(capacity_limit),
                "base_entry_notional": _round(base_notional),
                "scaled_entry_notional": _round(scaled_notional),
                "capacity_utilization": _round(utilization),
                "capacity_passed": (math.isfinite(utilization) and utilization <= 1.0),
            }
        )
    return rows


def _source_contract_rows(
    *,
    sources: StructuralStopRiskScalingSourcePaths,
    dsi009: Mapping[str, Any],
    dsi007: Mapping[str, Any],
    market_hash: str,
) -> list[dict[str, Any]]:
    dsi007_hashes = cast(Mapping[str, Any], dsi007["source_chain_hashes"])
    return [
        {
            "source_role": "DSI009_CERTIFICATE",
            "path": _portable_path(sources.dsi009_certificate),
            "sha256": _sha256(sources.dsi009_certificate),
        },
        {
            "source_role": "DSI008_CERTIFICATE",
            "path": _portable_path(sources.dsi008_certificate),
            "sha256": _sha256(sources.dsi008_certificate),
        },
        {
            "source_role": "DSI007_CERTIFICATE",
            "path": _portable_path(sources.dsi007_certificate),
            "sha256": _sha256(sources.dsi007_certificate),
        },
        {
            "source_role": "GOVERNED_MARKET_SLICE",
            "path": "REHYDRATED_FROM_CURRENT_GOVERNED_DATABASE",
            "sha256": market_hash,
        },
        {
            "source_role": "CURRENT_DATABASE_CONTAINER",
            "path": _portable_path(sources.database),
            "sha256": _sha256(sources.database),
        },
        {
            "source_role": "DSI007_CERTIFIED_DATABASE_LINEAGE",
            "path": "SIGNED_DSI007_CERTIFICATE_FIELD",
            "sha256": str(dsi007_hashes["HISTORICAL_TRUTH_DATABASE"]),
        },
    ]


def _portable_path(path: Path) -> str:
    parts = path.resolve().parts
    if "artifacts" in parts:
        return "/".join(parts[parts.index("artifacts") :])
    return path.name


def _optional_float(value: object) -> float | None:
    if not isinstance(value, Real):
        return None
    number = float(value)
    return None if math.isnan(number) else number


def _round(value: float) -> float:
    return round(float(value), 8)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "_capacity_ledger",
    "_parity_rows",
    "_rehydrate_structural_stop",
    "_source_contract_rows",
    "_validate_market_slice",
    "_validate_source_chain",
]
