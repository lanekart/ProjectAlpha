"""DSI-012 fixed daily-notional overlay and acceptance accounting."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from alpha.decision_superiority.entry_stop_improvement import _stable_id
from alpha.decision_superiority.regime_strategy_models import TournamentPolicy
from alpha.decision_superiority.regime_strategy_tournament import _portfolio_metrics
from alpha.decision_superiority.structural_stop_risk_scaling_models import (
    StructuralStopRiskScalingError,
    StructuralStopRiskScalingPolicy,
)


def _apply_daily_notional_overlay(
    *,
    curve: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    policy: StructuralStopRiskScalingPolicy,
    financing_rate: float,
    scenario: str,
) -> dict[str, Any]:
    if not curve:
        raise StructuralStopRiskScalingError("DSI012_BASE_EQUITY_CURVE_EMPTY")
    tournament_policy = TournamentPolicy()
    value = tournament_policy.starting_capital
    peak = value
    cumulative_financing = 0.0
    rows: list[dict[str, Any]] = []
    financing_rows: list[dict[str, Any]] = []
    previous_scaled_transaction_costs = 0.0
    for raw in curve:
        base_return = float(raw.get("daily_return") or 0.0)
        base_exposure = max(0.0, float(raw.get("gross_exposure") or 0.0))
        target_exposure = base_exposure * policy.risk_multiplier
        borrowed_fraction = max(0.0, target_exposure - 1.0)
        financing_fraction = (
            borrowed_fraction * financing_rate / policy.sessions_per_year
        )
        scaled_return = policy.risk_multiplier * base_return - financing_fraction
        previous_value = value
        value *= 1.0 + scaled_return
        if not math.isfinite(value) or value <= 0:
            raise StructuralStopRiskScalingError("DSI012_CAPITAL_RECONCILIATION_DEFECT")
        financing_amount = previous_value * financing_fraction
        cumulative_financing += financing_amount
        peak = max(peak, value)
        scaled_transaction_costs = (
            float(raw.get("cumulative_costs") or 0.0) * policy.risk_multiplier
        )
        daily_transaction_cost = (
            scaled_transaction_costs - previous_scaled_transaction_costs
        )
        previous_scaled_transaction_costs = scaled_transaction_costs
        open_position_value = value * target_exposure
        cash = value - open_position_value
        row = {
            "portfolio_day_id": _stable_id(
                "DAY", "DSI012", scenario, raw["observed_on"]
            ),
            "portfolio_name": f"DSI012_{scenario}",
            "observed_on": raw["observed_on"],
            "base_daily_return": base_return,
            "risk_multiplier": policy.risk_multiplier,
            "gross_exposure": target_exposure,
            "net_exposure": target_exposure,
            "borrowed_fraction": borrowed_fraction,
            "cash": cash,
            "open_position_value": open_position_value,
            "portfolio_value": value,
            "daily_return": scaled_return,
            "drawdown": value / peak - 1.0,
            "daily_transaction_cost": daily_transaction_cost,
            "daily_financing_cost": financing_amount,
            "cumulative_transaction_costs": scaled_transaction_costs,
            "cumulative_financing_costs": cumulative_financing,
            "cumulative_costs": scaled_transaction_costs + cumulative_financing,
            "open_positions": int(raw.get("open_positions") or 0),
            "financing_rate": financing_rate,
            "financing_basis": "END_OF_DAY_SCALED_GROSS_EXPOSURE",
        }
        rows.append(_rounded_row(row))
        financing_rows.append(
            {
                "financing_event_id": _stable_id(
                    "FINANCING", scenario, raw["observed_on"]
                ),
                "scenario": scenario,
                "observed_on": raw["observed_on"],
                "borrowed_fraction": _round(borrowed_fraction),
                "annual_rate": financing_rate,
                "daily_rate": _round(financing_rate / policy.sessions_per_year),
                "amount": _round(financing_amount),
                "cumulative_amount": _round(cumulative_financing),
                "used_for_selection": False,
            }
        )
    scaled_trades = _scaled_trade_ledger(
        trades,
        multiplier=policy.risk_multiplier,
    )
    metrics = _portfolio_metrics(
        name=f"DSI012_{scenario}",
        curve=rows,
        trades=scaled_trades,
        policy=tournament_policy,
    )
    daily_pnl = [
        float(row["portfolio_value"])
        - (
            tournament_policy.starting_capital
            if index == 0
            else float(rows[index - 1]["portfolio_value"])
        )
        for index, row in enumerate(rows)
    ]
    positive = sum(item for item in daily_pnl if item > 0)
    negative = abs(sum(item for item in daily_pnl if item < 0))
    enriched = dict(metrics)
    scaled_transaction_costs = sum(
        float(item.get("costs", 0.0)) for item in scaled_trades
    )
    total_costs = scaled_transaction_costs + cumulative_financing
    years = float(enriched["years"])
    gross_ending = float(enriched["ending_capital"]) + total_costs
    enriched["total_costs"] = _round(total_costs)
    enriched["gross_cagr"] = _round(
        (gross_ending / tournament_policy.starting_capital) ** (1.0 / years) - 1.0
    )
    enriched["scaled_transaction_costs"] = _round(scaled_transaction_costs)
    enriched["daily_profit_factor"] = (
        None if negative == 0 else _round(positive / negative)
    )
    enriched["total_financing_costs"] = _round(cumulative_financing)
    enriched["financing_rate"] = financing_rate
    enriched["maximum_gross_exposure"] = _round(
        max(float(row["gross_exposure"]) for row in rows)
    )
    enriched["scenario"] = scenario
    return {
        "curve": rows,
        "financing": financing_rows,
        "metrics": enriched,
    }


def _scaled_position_ledger(
    *,
    base_positions: Sequence[Mapping[str, Any]],
    scaled_curve: Sequence[Mapping[str, Any]],
    multiplier: float,
) -> list[dict[str, Any]]:
    curve_by_date = {row["observed_on"]: row for row in scaled_curve}
    rows: list[dict[str, Any]] = []
    for raw in base_positions:
        curve = curve_by_date.get(raw["observed_on"])
        if curve is None:
            raise StructuralStopRiskScalingError("DSI012_POSITION_CURVE_DATE_MISSING")
        scaled_market_value = float(raw["market_value"]) * multiplier
        portfolio_value = float(curve["portfolio_value"])
        fraction = (
            math.inf if portfolio_value <= 0 else scaled_market_value / portfolio_value
        )
        rows.append(
            {
                **dict(raw),
                "base_quantity": raw["quantity"],
                "base_market_value": raw["market_value"],
                "scaled_notional_quantity": _round(
                    float(raw["quantity"]) * multiplier
                ),
                "scaled_market_value": _round(scaled_market_value),
                "scaled_portfolio_fraction": _round(fraction),
                "overlay_is_daily_notional_not_whole_share_execution": True,
            }
        )
    return rows


def _scaled_trade_ledger(
    trades: Sequence[Mapping[str, Any]],
    *,
    multiplier: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade in trades:
        base_quantity = float(trade["quantity"])
        base_gross_pnl = float(trade["gross_pnl"])
        base_net_pnl = float(trade["net_pnl"])
        base_costs = float(trade["costs"])
        rows.append(
            {
                **dict(trade),
                "base_quantity": trade["quantity"],
                "base_gross_pnl": trade["gross_pnl"],
                "base_net_pnl": trade["net_pnl"],
                "base_costs": trade["costs"],
                "quantity": _round(base_quantity * multiplier),
                "gross_pnl": _round(base_gross_pnl * multiplier),
                "net_pnl": _round(base_net_pnl * multiplier),
                "costs": _round(base_costs * multiplier),
                "scaled_notional_quantity": _round(base_quantity * multiplier),
                "scaled_gross_pnl": _round(base_gross_pnl * multiplier),
                "scaled_net_pnl_before_financing": _round(
                    base_net_pnl * multiplier
                ),
                "scaled_transaction_costs": _round(base_costs * multiplier),
                "risk_multiplier": multiplier,
                "financing_allocated_at_portfolio_day_level": True,
            }
        )
    return rows


def _scaled_cost_ledger(
    costs: Sequence[Mapping[str, Any]],
    *,
    multiplier: float,
) -> list[dict[str, Any]]:
    return [
        {
            **dict(row),
            "base_amount": row["amount"],
            "amount": _round(float(row["amount"]) * multiplier),
            "scaled_amount": _round(float(row["amount"]) * multiplier),
            "risk_multiplier": multiplier,
        }
        for row in costs
    ]


def _acceptance(
    *,
    base_metrics: Mapping[str, Any],
    benchmark_cagr: float,
    capacity_rows: Sequence[Mapping[str, Any]],
    position_rows: Sequence[Mapping[str, Any]],
    parity_ok: bool,
    policy: StructuralStopRiskScalingPolicy,
) -> tuple[list[dict[str, Any]], list[str]]:
    maximum_position = max(
        (float(row["scaled_portfolio_fraction"]) for row in position_rows),
        default=0.0,
    )
    capacity_failures = sum(
        not bool(row["capacity_passed"]) for row in capacity_rows
    )
    checks = (
        ("REHYDRATION_PARITY", parity_ok, True, parity_ok),
        (
            "NET_CAGR",
            base_metrics.get("net_cagr"),
            policy.minimum_net_cagr,
            _metric_value(base_metrics, "net_cagr", default=-math.inf)
            >= policy.minimum_net_cagr,
        ),
        (
            "MAXIMUM_DRAWDOWN",
            base_metrics.get("maximum_drawdown"),
            policy.maximum_drawdown_floor,
            _metric_value(base_metrics, "maximum_drawdown", default=-math.inf)
            >= policy.maximum_drawdown_floor,
        ),
        (
            "CALMAR",
            base_metrics.get("calmar"),
            policy.minimum_calmar,
            _metric_value(base_metrics, "calmar", default=-math.inf)
            >= policy.minimum_calmar,
        ),
        (
            "DAILY_PROFIT_FACTOR",
            base_metrics.get("daily_profit_factor"),
            policy.minimum_profit_factor,
            _metric_value(base_metrics, "daily_profit_factor", default=-math.inf)
            >= policy.minimum_profit_factor,
        ),
        (
            "TRADE_EXPECTANCY",
            base_metrics.get("expectancy"),
            0.0,
            _metric_value(base_metrics, "expectancy", default=-math.inf) > 0,
        ),
        (
            "BENCHMARK_EXCESS_CAGR",
            (
                None
                if base_metrics.get("net_cagr") is None
                else float(base_metrics["net_cagr"]) - benchmark_cagr
            ),
            policy.minimum_excess_cagr,
            (
                base_metrics.get("net_cagr") is not None
                and float(base_metrics["net_cagr"]) - benchmark_cagr
                >= policy.minimum_excess_cagr
            ),
        ),
        ("CAPACITY_FAILURE_COUNT", capacity_failures, 0, capacity_failures == 0),
        (
            "MAXIMUM_GROSS_EXPOSURE",
            base_metrics.get("maximum_gross_exposure"),
            policy.maximum_gross_exposure,
            _metric_value(base_metrics, "maximum_gross_exposure", default=math.inf)
            <= policy.maximum_gross_exposure,
        ),
        (
            "MAXIMUM_POSITION_FRACTION",
            maximum_position,
            policy.maximum_position_fraction,
            maximum_position <= policy.maximum_position_fraction,
        ),
    )
    rows = [
        {
            "gate": name,
            "actual": actual,
            "threshold": threshold,
            "passed": passed,
            "pre_registered": True,
        }
        for name, actual, threshold, passed in checks
    ]
    blockers = [
        f"{row['gate']}_FAILED" for row in rows if not bool(row["passed"])
    ]
    return rows, blockers


def _metric_value(
    metrics: Mapping[str, Any],
    key: str,
    *,
    default: float,
) -> float:
    value = metrics.get(key)
    if value is None:
        return default
    number = float(value)
    return number if math.isfinite(number) else default


def _round(value: float) -> float:
    return round(float(value), 8)


def _rounded_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: (
            _round(value)
            if isinstance(value, float) and math.isfinite(value)
            else value
        )
        for key, value in row.items()
    }


__all__ = [
    "_acceptance",
    "_apply_daily_notional_overlay",
    "_scaled_cost_ledger",
    "_scaled_position_ledger",
    "_scaled_trade_ledger",
]
