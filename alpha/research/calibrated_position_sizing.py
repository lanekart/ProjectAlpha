"""Governed DSI-011D calibrated edge and position-sizing audit.

The audit replays the exact completed DSI-011C trade paths and changes only the
entry risk allocation. Trade selection, entry dates, exit dates, execution
prices, stop policy, target policy, and trailing policy remain frozen.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

import duckdb

AUDIT_VERSION = "DSI-011D-CALIBRATED-SIZING-v1.0.0"
PRODUCTION_INFLUENCE = False
_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")


class SizingPolicy(StrEnum):
    FLAT_1PCT_REFERENCE = "FLAT_1PCT_REFERENCE"
    FLAT_1PCT_RISK_CAP = "FLAT_1PCT_RISK_CAP"
    UNIFORM_1_5PCT = "UNIFORM_1_5PCT"
    SCORE_TIERED = "SCORE_TIERED"
    WALK_FORWARD_EDGE = "WALK_FORWARD_EDGE"
    FRACTIONAL_KELLY = "FRACTIONAL_KELLY"


@dataclass(frozen=True, slots=True)
class SizingAuditConfig:
    initial_capital: Decimal = Decimal("10000000")
    low_risk_fraction: Decimal = Decimal("0.005")
    baseline_risk_fraction: Decimal = Decimal("0.01")
    high_risk_fraction: Decimal = Decimal("0.015")
    aggregate_open_risk_cap: Decimal = Decimal("0.03")
    maximum_positions: int = 5
    drawdown_throttle_percent: Decimal = Decimal("8")
    hard_stop_percent: Decimal = Decimal("12")
    minimum_score_history: int = 20
    minimum_completed_history: int = 20
    minimum_bucket_history: int = 8
    beta_prior_wins: int = 2
    beta_prior_losses: int = 2
    high_expected_r_threshold: Decimal = Decimal("0.5")
    fractional_kelly_multiplier: Decimal = Decimal("0.25")
    fixed_stop_percent: Decimal = Decimal("5")
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        fractions = (
            self.low_risk_fraction,
            self.baseline_risk_fraction,
            self.high_risk_fraction,
        )
        if self.initial_capital <= 0:
            raise ValueError("initial capital must be positive")
        if not all(_ZERO < value <= _ONE for value in fractions):
            raise ValueError("risk fractions must be in (0, 1]")
        if not (
            self.low_risk_fraction
            <= self.baseline_risk_fraction
            <= self.high_risk_fraction
        ):
            raise ValueError("risk fractions must be ordered low <= base <= high")
        if not (_ZERO < self.aggregate_open_risk_cap <= _ONE):
            raise ValueError("aggregate risk cap must be in (0, 1]")
        if self.maximum_positions < 1:
            raise ValueError("maximum positions must be positive")
        if self.drawdown_throttle_percent <= 0:
            raise ValueError("drawdown throttle must be positive")
        if self.hard_stop_percent <= self.drawdown_throttle_percent:
            raise ValueError("hard stop must exceed drawdown throttle")
        if self.minimum_score_history < 1:
            raise ValueError("score history must be positive")
        if self.minimum_completed_history < 1:
            raise ValueError("completed history must be positive")
        if self.minimum_bucket_history < 1:
            raise ValueError("bucket history must be positive")
        if self.beta_prior_wins < 1 or self.beta_prior_losses < 1:
            raise ValueError("beta prior counts must be positive")
        if self.fractional_kelly_multiplier <= 0:
            raise ValueError("fractional Kelly multiplier must be positive")
        if not (_ZERO < self.fixed_stop_percent < _HUNDRED):
            raise ValueError("fixed stop percent must be in (0, 100)")
        if self.production_influence:
            raise ValueError("research audit cannot influence production")

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], _jsonable(asdict(self)))


@dataclass(frozen=True, slots=True)
class ExitTemplate:
    exit_date: date
    baseline_quantity: int
    exit_price: Decimal
    reason: str
    ambiguous_session: bool


@dataclass(frozen=True, slots=True)
class TradeTemplate:
    trade_id: str
    security_id: str
    symbol: str
    signal_date: date
    entry_date: date
    exit_date: date
    baseline_quantity: int
    entry_price: Decimal
    initial_stop: Decimal
    recommendation_score: Decimal
    final_signal: str
    score_tier: str
    baseline_gross_return_percent: Decimal
    baseline_realized_r: Decimal
    exit_legs: tuple[ExitTemplate, ...]


@dataclass(frozen=True, slots=True)
class CalibrationEstimate:
    history_count: int
    bucket_history_count: int
    posterior_success_probability: Decimal | None
    average_win_r: Decimal | None
    average_loss_r: Decimal | None
    expected_r: Decimal | None
    mean_r: Decimal | None
    variance_r: Decimal | None
    sample_source: str


@dataclass(frozen=True, slots=True)
class SizingDecision:
    requested_risk_fraction: Decimal
    posterior_success_probability: Decimal | None
    expected_r: Decimal | None
    kelly_fraction: Decimal | None
    calibration_history_count: int
    calibration_bucket_count: int
    calibration_source: str
    fallback_reason: str | None


@dataclass(slots=True)
class OpenSizingPosition:
    template: TradeTemplate
    original_quantity: int
    remaining_quantity: int
    requested_risk_fraction: Decimal
    effective_risk_fraction: Decimal
    posterior_success_probability: Decimal | None
    expected_r: Decimal | None
    kelly_fraction: Decimal | None
    calibration_history_count: int
    calibration_bucket_count: int
    calibration_source: str
    fallback_reason: str | None
    proceeds: Decimal = _ZERO
    exit_records: list[dict[str, object]] | None = None

    def __post_init__(self) -> None:
        if self.exit_records is None:
            self.exit_records = []


@dataclass(frozen=True, slots=True)
class CompletedSizingTrade:
    policy: str
    trade_id: str
    security_id: str
    symbol: str
    signal_date: date
    entry_date: date
    exit_date: date
    recommendation_score: Decimal
    final_signal: str
    score_tier: str
    original_quantity: int
    entry_price: Decimal
    initial_stop: Decimal
    gross_profit_loss: Decimal
    gross_return_percent: Decimal
    realized_r: Decimal
    requested_risk_fraction: Decimal
    effective_risk_fraction: Decimal
    posterior_success_probability: Decimal | None
    expected_r: Decimal | None
    kelly_fraction: Decimal | None
    calibration_history_count: int
    calibration_bucket_count: int
    calibration_source: str
    fallback_reason: str | None
    final_exit_reason: str
    exit_records: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        payload = cast(dict[str, object], _jsonable(asdict(self)))
        payload["exit_records"] = list(self.exit_records)
        return payload


@dataclass(frozen=True, slots=True)
class SizingEquityPoint:
    trading_date: date
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    drawdown_percent: Decimal
    open_positions: int
    aggregate_initial_risk_percent: Decimal
    hard_stop_active: bool

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], _jsonable(asdict(self)))


@dataclass(frozen=True, slots=True)
class PolicyResult:
    policy: SizingPolicy
    trades: tuple[CompletedSizingTrade, ...]
    equity_curve: tuple[SizingEquityPoint, ...]
    rejected_entries: tuple[dict[str, object], ...]
    starting_capital: Decimal
    ending_equity: Decimal
    hard_stop_date: date | None

    def summary(self) -> dict[str, object]:
        wins = tuple(item for item in self.trades if item.gross_profit_loss > 0)
        losses = tuple(item for item in self.trades if item.gross_profit_loss < 0)
        gains = sum((item.gross_profit_loss for item in wins), _ZERO)
        loss_value = abs(sum((item.gross_profit_loss for item in losses), _ZERO))
        elapsed_days = (
            0
            if len(self.equity_curve) < 2
            else (
                self.equity_curve[-1].trading_date - self.equity_curve[0].trading_date
            ).days
        )
        cagr: Decimal | None = None
        if elapsed_days > 0 and self.ending_equity > 0:
            exponent = Decimal("365.2425") / Decimal(elapsed_days)
            cagr = _percent(
                (self.ending_equity / self.starting_capital) ** exponent - _ONE
            )
        average_return = _average(
            tuple(item.gross_return_percent for item in self.trades)
        )
        average_r = _average(tuple(item.realized_r for item in self.trades))
        average_requested = _average(
            tuple(item.requested_risk_fraction for item in self.trades)
        )
        average_effective = _average(
            tuple(item.effective_risk_fraction for item in self.trades)
        )
        return {
            "policy": self.policy.value,
            "initial_capital": str(self.starting_capital),
            "final_equity": str(self.ending_equity),
            "gross_total_return_percent": str(
                _percent(self.ending_equity / self.starting_capital - _ONE)
            ),
            "gross_cagr_percent": None if cagr is None else str(cagr),
            "maximum_drawdown_percent": (
                None
                if not self.equity_curve
                else str(min(item.drawdown_percent for item in self.equity_curve))
            ),
            "entry_count": len(self.trades),
            "completed_trade_count": len(self.trades),
            "rejected_entry_count": len(self.rejected_entries),
            "win_rate_percent": (
                None
                if not self.trades
                else str(_percent(Decimal(len(wins)) / Decimal(len(self.trades))))
            ),
            "expectancy_percent": None
            if average_return is None
            else str(average_return),
            "expectancy_r": None if average_r is None else str(average_r),
            "profit_factor": None if loss_value == 0 else str(gains / loss_value),
            "average_exposure_percent": _average_exposure(self.equity_curve),
            "turnover_percent": _turnover(self.trades, self.starting_capital),
            "average_requested_risk_percent": (
                None if average_requested is None else str(_percent(average_requested))
            ),
            "average_effective_risk_percent": (
                None if average_effective is None else str(_percent(average_effective))
            ),
            "hard_stop_triggered": self.hard_stop_date is not None,
            "hard_stop_date": (
                None if self.hard_stop_date is None else self.hard_stop_date.isoformat()
            ),
            "results_are_gross_of_costs": True,
            "production_influence": False,
        }


def assign_walk_forward_score_tiers(
    templates: tuple[TradeTemplate, ...],
    *,
    minimum_history: int,
) -> tuple[TradeTemplate, ...]:
    ordered = sorted(templates, key=lambda item: (item.signal_date, item.trade_id))
    prior_scores: list[Decimal] = []
    assigned: list[TradeTemplate] = []
    by_date: dict[date, list[TradeTemplate]] = defaultdict(list)
    for item in ordered:
        by_date[item.signal_date].append(item)
    for signal_date in sorted(by_date):
        group = by_date[signal_date]
        lower: Decimal | None = None
        upper: Decimal | None = None
        if len(prior_scores) >= minimum_history:
            ranked = sorted(prior_scores)
            lower = _nearest_rank(ranked, 1, 3)
            upper = _nearest_rank(ranked, 2, 3)
        for item in group:
            if lower is None or upper is None:
                tier = "UNSEASONED"
            elif item.recommendation_score <= lower:
                tier = "LOW"
            elif item.recommendation_score >= upper:
                tier = "HIGH"
            else:
                tier = "MID"
            assigned.append(replace(item, score_tier=tier))
        prior_scores.extend(item.recommendation_score for item in group)
    return tuple(sorted(assigned, key=lambda item: (item.entry_date, item.trade_id)))


def calibration_estimate(
    template: TradeTemplate,
    completed: tuple[CompletedSizingTrade, ...],
    config: SizingAuditConfig,
) -> CalibrationEstimate:
    eligible = tuple(item for item in completed if item.exit_date < template.entry_date)
    bucket = tuple(item for item in eligible if item.score_tier == template.score_tier)
    if len(bucket) >= config.minimum_bucket_history:
        sample = bucket
        source = "SCORE_TIER"
    else:
        sample = eligible
        source = "GLOBAL_FALLBACK"
    if not sample:
        return CalibrationEstimate(
            0, len(bucket), None, None, None, None, None, None, source
        )
    values = tuple(item.realized_r for item in sample)
    wins = tuple(value for value in values if value > 0)
    losses = tuple(abs(value) for value in values if value < 0)
    probability = Decimal(len(wins) + config.beta_prior_wins) / Decimal(
        len(sample) + config.beta_prior_wins + config.beta_prior_losses
    )
    average_win = _average(wins) or Decimal("2")
    average_loss = _average(losses) or _ONE
    expected_r = probability * average_win - (_ONE - probability) * average_loss
    mean_r = _average(values)
    variance_r: Decimal | None = None
    if mean_r is not None:
        variance_r = sum(((value - mean_r) ** 2 for value in values), _ZERO) / Decimal(
            len(values)
        )
    return CalibrationEstimate(
        history_count=len(eligible),
        bucket_history_count=len(bucket),
        posterior_success_probability=probability,
        average_win_r=average_win,
        average_loss_r=average_loss,
        expected_r=expected_r,
        mean_r=mean_r,
        variance_r=variance_r,
        sample_source=source,
    )


def sizing_decision(
    policy: SizingPolicy,
    template: TradeTemplate,
    completed: tuple[CompletedSizingTrade, ...],
    config: SizingAuditConfig,
) -> SizingDecision:
    estimate = calibration_estimate(template, completed, config)
    fallback: str | None = None
    kelly_fraction: Decimal | None = None
    if policy in {SizingPolicy.FLAT_1PCT_REFERENCE, SizingPolicy.FLAT_1PCT_RISK_CAP}:
        requested = config.baseline_risk_fraction
    elif policy is SizingPolicy.UNIFORM_1_5PCT:
        requested = config.high_risk_fraction
    elif policy is SizingPolicy.SCORE_TIERED:
        requested = {
            "LOW": config.low_risk_fraction,
            "MID": config.baseline_risk_fraction,
            "HIGH": config.high_risk_fraction,
            "UNSEASONED": config.baseline_risk_fraction,
        }[template.score_tier]
        if template.score_tier == "UNSEASONED":
            fallback = "INSUFFICIENT_PRIOR_SCORE_HISTORY"
    elif estimate.history_count < config.minimum_completed_history:
        requested = config.baseline_risk_fraction
        fallback = "INSUFFICIENT_COMPLETED_HISTORY"
    elif policy is SizingPolicy.WALK_FORWARD_EDGE:
        expected = estimate.expected_r or _ZERO
        if expected <= 0:
            requested = config.low_risk_fraction
        elif expected >= config.high_expected_r_threshold:
            requested = config.high_risk_fraction
        else:
            requested = config.baseline_risk_fraction
    elif policy is SizingPolicy.FRACTIONAL_KELLY:
        mean_r = estimate.mean_r or _ZERO
        variance_r = estimate.variance_r or _ZERO
        if mean_r <= 0 or variance_r <= 0:
            requested = config.low_risk_fraction
            kelly_fraction = _ZERO
            fallback = "NON_POSITIVE_OR_ZERO_VARIANCE_EDGE"
        else:
            kelly_fraction = config.fractional_kelly_multiplier * mean_r / variance_r
            requested = min(
                config.high_risk_fraction,
                max(config.low_risk_fraction, kelly_fraction),
            )
    else:
        raise ValueError(f"unsupported sizing policy: {policy}")
    return SizingDecision(
        requested_risk_fraction=requested,
        posterior_success_probability=estimate.posterior_success_probability,
        expected_r=estimate.expected_r,
        kelly_fraction=kelly_fraction,
        calibration_history_count=estimate.history_count,
        calibration_bucket_count=estimate.bucket_history_count,
        calibration_source=estimate.sample_source,
        fallback_reason=fallback,
    )


def simulate_policy(
    *,
    policy: SizingPolicy,
    templates: tuple[TradeTemplate, ...],
    trading_dates: tuple[date, ...],
    price_map: dict[tuple[date, str], tuple[Decimal, Decimal]],
    config: SizingAuditConfig,
) -> PolicyResult:
    entries: dict[date, list[TradeTemplate]] = defaultdict(list)
    exits: dict[date, list[tuple[TradeTemplate, int, ExitTemplate]]] = defaultdict(list)
    for template in templates:
        entries[template.entry_date].append(template)
        for index, leg in enumerate(template.exit_legs):
            exits[leg.exit_date].append((template, index, leg))

    cash = config.initial_capital
    peak_equity = config.initial_capital
    last_equity = config.initial_capital
    latest_close: dict[str, Decimal] = {}
    positions: dict[str, OpenSizingPosition] = {}
    completed: list[CompletedSizingTrade] = []
    rejected: list[dict[str, object]] = []
    curve: list[SizingEquityPoint] = []
    hard_stop_date: date | None = None
    terminated = False

    for trading_date in trading_dates:
        for template, leg_index, leg in sorted(
            exits.get(trading_date, []),
            key=lambda item: (item[0].trade_id, item[1]),
        ):
            position = positions.get(template.trade_id)
            if position is None:
                continue
            is_final = leg_index == len(template.exit_legs) - 1
            quantity = (
                position.remaining_quantity
                if is_final
                else _scaled_leg_quantity(position, leg)
            )
            if quantity <= 0:
                continue
            proceeds = leg.exit_price * Decimal(quantity)
            cash += proceeds
            position.proceeds += proceeds
            position.remaining_quantity -= quantity
            cast(list[dict[str, object]], position.exit_records).append(
                {
                    "exit_date": trading_date.isoformat(),
                    "quantity": quantity,
                    "exit_price": str(leg.exit_price),
                    "reason": leg.reason,
                    "ambiguous_session": leg.ambiguous_session,
                }
            )
            if position.remaining_quantity == 0:
                completed.append(
                    _complete_position(policy, position, leg.reason, trading_date)
                )
                del positions[template.trade_id]

        prior_drawdown = _percent(last_equity / peak_equity - _ONE)
        for template in sorted(
            entries.get(trading_date, []),
            key=lambda item: (
                0 if item.final_signal == "STRONG_BUY" else 1,
                -item.recommendation_score,
                item.trade_id,
            ),
        ):
            if terminated:
                rejected.append(
                    _rejection(policy, template, trading_date, "HARD_STOP_ACTIVE")
                )
                continue
            if len(positions) >= config.maximum_positions:
                rejected.append(
                    _rejection(
                        policy, template, trading_date, "MAXIMUM_POSITIONS_REACHED"
                    )
                )
                continue
            opening_market = sum(
                (
                    price_map.get(
                        (trading_date, item.template.security_id),
                        (
                            latest_close.get(
                                item.template.security_id,
                                item.template.entry_price,
                            ),
                            latest_close.get(
                                item.template.security_id,
                                item.template.entry_price,
                            ),
                        ),
                    )[0]
                    * Decimal(item.remaining_quantity)
                    for item in positions.values()
                ),
                _ZERO,
            )
            opening_equity = cash + opening_market
            decision = sizing_decision(policy, template, tuple(completed), config)
            requested = decision.requested_risk_fraction
            if prior_drawdown <= -config.drawdown_throttle_percent:
                requested *= Decimal("0.5")
            if prior_drawdown <= -config.hard_stop_percent:
                requested = _ZERO
            effective = requested
            if policy is not SizingPolicy.FLAT_1PCT_REFERENCE:
                open_risk = _open_initial_risk(positions)
                available = max(
                    _ZERO,
                    config.aggregate_open_risk_cap * opening_equity - open_risk,
                )
                effective = min(effective, available / opening_equity)
            if effective <= 0:
                rejected.append(
                    _rejection(
                        policy, template, trading_date, "RISK_CAPACITY_EXHAUSTED"
                    )
                )
                continue
            quantity = _risk_sized_quantity(
                equity=opening_equity,
                cash=cash,
                entry_price=template.entry_price,
                stop_price=template.initial_stop,
                risk_fraction=effective,
            )
            if quantity < 1:
                rejected.append(
                    _rejection(
                        policy, template, trading_date, "INSUFFICIENT_CASH_OR_RISK"
                    )
                )
                continue
            positions[template.trade_id] = OpenSizingPosition(
                template=template,
                original_quantity=quantity,
                remaining_quantity=quantity,
                requested_risk_fraction=requested,
                effective_risk_fraction=effective,
                posterior_success_probability=decision.posterior_success_probability,
                expected_r=decision.expected_r,
                kelly_fraction=decision.kelly_fraction,
                calibration_history_count=decision.calibration_history_count,
                calibration_bucket_count=decision.calibration_bucket_count,
                calibration_source=decision.calibration_source,
                fallback_reason=decision.fallback_reason,
            )
            cash -= template.entry_price * Decimal(quantity)

        for template in templates:
            prices = price_map.get((trading_date, template.security_id))
            if prices is not None:
                latest_close[template.security_id] = prices[1]
        market_value = sum(
            (
                latest_close.get(item.template.security_id, item.template.entry_price)
                * Decimal(item.remaining_quantity)
                for item in positions.values()
            ),
            _ZERO,
        )
        equity = cash + market_value
        peak_equity = max(peak_equity, equity)
        drawdown = _percent(equity / peak_equity - _ONE)
        if not terminated and drawdown <= -config.hard_stop_percent:
            for trade_id in sorted(tuple(positions)):
                position = positions[trade_id]
                close_price = latest_close.get(
                    position.template.security_id,
                    position.template.entry_price,
                )
                quantity = position.remaining_quantity
                proceeds = close_price * Decimal(quantity)
                cash += proceeds
                position.proceeds += proceeds
                position.remaining_quantity = 0
                cast(list[dict[str, object]], position.exit_records).append(
                    {
                        "exit_date": trading_date.isoformat(),
                        "quantity": quantity,
                        "exit_price": str(close_price),
                        "reason": "HARD_PORTFOLIO_STOP",
                        "ambiguous_session": False,
                    }
                )
                completed.append(
                    _complete_position(
                        policy,
                        position,
                        "HARD_PORTFOLIO_STOP",
                        trading_date,
                    )
                )
                del positions[trade_id]
            market_value = _ZERO
            equity = cash
            drawdown = _percent(equity / peak_equity - _ONE)
            hard_stop_date = trading_date
            terminated = True
        curve.append(
            SizingEquityPoint(
                trading_date=trading_date,
                cash=cash,
                market_value=market_value,
                equity=equity,
                drawdown_percent=drawdown,
                open_positions=len(positions),
                aggregate_initial_risk_percent=(
                    _ZERO
                    if equity <= 0
                    else _percent(_open_initial_risk(positions) / equity)
                ),
                hard_stop_active=terminated,
            )
        )
        last_equity = equity

    if positions:
        final_date = trading_dates[-1]
        for trade_id in sorted(tuple(positions)):
            position = positions[trade_id]
            close_price = latest_close.get(
                position.template.security_id,
                position.template.entry_price,
            )
            quantity = position.remaining_quantity
            proceeds = close_price * Decimal(quantity)
            cash += proceeds
            position.proceeds += proceeds
            position.remaining_quantity = 0
            cast(list[dict[str, object]], position.exit_records).append(
                {
                    "exit_date": final_date.isoformat(),
                    "quantity": quantity,
                    "exit_price": str(close_price),
                    "reason": "FORCED_BOUNDARY_EXIT",
                    "ambiguous_session": False,
                }
            )
            completed.append(
                _complete_position(policy, position, "FORCED_BOUNDARY_EXIT", final_date)
            )
            del positions[trade_id]
        if curve:
            final_drawdown = _percent(cash / max(peak_equity, cash) - _ONE)
            curve[-1] = replace(
                curve[-1],
                cash=cash,
                market_value=_ZERO,
                equity=cash,
                drawdown_percent=final_drawdown,
                open_positions=0,
                aggregate_initial_risk_percent=_ZERO,
            )

    return PolicyResult(
        policy=policy,
        trades=tuple(completed),
        equity_curve=tuple(curve),
        rejected_entries=tuple(rejected),
        starting_capital=config.initial_capital,
        ending_equity=cash,
        hard_stop_date=hard_stop_date,
    )


def run_sizing_audit(
    *,
    database: Path,
    challenger_output: Path,
    output: Path,
    config: SizingAuditConfig | None = None,
) -> dict[str, object]:
    resolved = config or SizingAuditConfig()
    output.mkdir(parents=True, exist_ok=True)
    templates, trading_dates, price_map, baseline_payload = load_audit_inputs(
        database=database,
        challenger_output=challenger_output,
        config=resolved,
    )
    results = {
        policy: simulate_policy(
            policy=policy,
            templates=templates,
            trading_dates=trading_dates,
            price_map=price_map,
            config=resolved,
        )
        for policy in SizingPolicy
    }
    parity = _reference_parity(
        baseline=cast(dict[str, object], baseline_payload["summary"]),
        replay=results[SizingPolicy.FLAT_1PCT_REFERENCE].summary(),
    )
    if not parity["passed"]:
        raise RuntimeError("flat 1% sizing replay failed DSI-011C parity")

    comparison = [results[policy].summary() for policy in SizingPolicy]
    calibration = {
        policy.value: _calibration_report(results[policy].trades)
        for policy in SizingPolicy
    }
    ranked = sorted(
        comparison,
        key=lambda row: (
            -_optional_number(row.get("gross_cagr_percent")),
            -_optional_number(row.get("maximum_drawdown_percent")),
        ),
    )
    for rank, row in enumerate(ranked, start=1):
        row["descriptive_rank"] = rank
        row["meets_research_hurdles"] = _meets_hurdles(row)

    payload: dict[str, object] = {
        "audit_version": AUDIT_VERSION,
        "source_commit": _source_commit(),
        "challenger_artifact_logical_sha256": baseline_payload.get(
            "artifact_logical_sha256"
        ),
        "challenger_output": str(challenger_output),
        "config": resolved.as_dict(),
        "fixed_trade_path_count": len(templates),
        "reference_parity": parity,
        "policy_comparison": ranked,
        "calibration": calibration,
        "production_influence": False,
        "automatic_strategy_promotion": False,
    }
    logical_hash = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    payload["artifact_logical_sha256"] = logical_hash

    _write_json(output / "sizing_audit.json", payload)
    _write_json(output / "policy_comparison.json", ranked)
    _write_csv(output / "policy_comparison.csv", ranked)
    _write_json(output / "calibration.json", calibration)
    _write_markdown(output / "sizing_audit.md", payload)
    for policy, result in results.items():
        policy_dir = output / policy.value.lower()
        policy_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            policy_dir / "trades.json",
            [item.as_dict() for item in result.trades],
        )
        _write_csv(
            policy_dir / "trades.csv",
            [item.as_dict() for item in result.trades],
        )
        _write_json(
            policy_dir / "equity_curve.json",
            [item.as_dict() for item in result.equity_curve],
        )
        _write_csv(
            policy_dir / "equity_curve.csv",
            [item.as_dict() for item in result.equity_curve],
        )
        _write_json(policy_dir / "summary.json", result.summary())
    _write_json(
        output / "manifest.json",
        {
            "audit_version": AUDIT_VERSION,
            "source_commit": payload["source_commit"],
            "challenger_artifact_logical_sha256": payload[
                "challenger_artifact_logical_sha256"
            ],
            "artifact_logical_sha256": logical_hash,
            "production_influence": False,
            "automatic_strategy_promotion": False,
        },
    )

    print("DSI-011D sizing audit complete")
    for row in ranked:
        print(
            f"{row['policy']}: CAGR={row['gross_cagr_percent']}; "
            f"MDD={row['maximum_drawdown_percent']}; "
            f"PF={row['profit_factor']}; trades={row['completed_trade_count']}"
        )
    print(f"Reference parity: {parity['passed']}")
    print(f"Artifact logical SHA-256: {logical_hash}")
    print(f"Results: {output / 'sizing_audit.json'}")
    return payload


def load_audit_inputs(
    *,
    database: Path,
    challenger_output: Path,
    config: SizingAuditConfig,
) -> tuple[
    tuple[TradeTemplate, ...],
    tuple[date, ...],
    dict[tuple[date, str], tuple[Decimal, Decimal]],
    dict[str, object],
]:
    result_path = challenger_output / "challenger_result.json"
    trades_path = challenger_output / "trades.json"
    if not database.is_file():
        raise FileNotFoundError(f"Historical Truth database not found: {database}")
    if not result_path.is_file() or not trades_path.is_file():
        raise FileNotFoundError("DSI-011C challenger artifacts are incomplete")
    baseline = cast(
        dict[str, object], json.loads(result_path.read_text(encoding="utf-8"))
    )
    raw_trades = cast(
        list[dict[str, Any]], json.loads(trades_path.read_text(encoding="utf-8"))
    )
    replay_run_id = str(baseline["retrospective_alpha_replay_run_id"])
    data_start = date.fromisoformat(str(baseline["data_start"]))
    data_end = date.fromisoformat(str(baseline["data_end"]))
    keys = tuple(
        (date.fromisoformat(str(row["signal_date"])), str(row["security_id"]))
        for row in raw_trades
    )
    metadata = _load_signal_metadata(database, replay_run_id, data_start, data_end)
    templates: list[TradeTemplate] = []
    for row, key in zip(raw_trades, keys, strict=True):
        score, verdict = metadata.get(key, (_ZERO, "UNKNOWN"))
        legs = tuple(
            ExitTemplate(
                exit_date=date.fromisoformat(str(item["exit_date"])),
                baseline_quantity=int(item["quantity"]),
                exit_price=_decimal(item["exit_price"]),
                reason=str(item["reason"]),
                ambiguous_session=bool(item["ambiguous_session"]),
            )
            for item in cast(list[dict[str, Any]], row["exit_legs"])
        )
        gross_return = _decimal(row["gross_return_percent"])
        templates.append(
            TradeTemplate(
                trade_id=str(row["trade_id"]),
                security_id=str(row["security_id"]),
                symbol=str(row["symbol"]),
                signal_date=key[0],
                entry_date=date.fromisoformat(str(row["entry_date"])),
                exit_date=date.fromisoformat(str(row["exit_date"])),
                baseline_quantity=int(row["original_quantity"]),
                entry_price=_decimal(row["entry_price"]),
                initial_stop=_decimal(row["initial_stop"]),
                recommendation_score=score,
                final_signal=verdict,
                score_tier="UNSEASONED",
                baseline_gross_return_percent=gross_return,
                baseline_realized_r=gross_return / config.fixed_stop_percent,
                exit_legs=legs,
            )
        )
    assigned = assign_walk_forward_score_tiers(
        tuple(templates),
        minimum_history=config.minimum_score_history,
    )
    trading_dates, price_map = _load_prices(
        database=database,
        identities=tuple(sorted({item.security_id for item in assigned})),
        start=data_start,
        end=data_end,
    )
    return assigned, trading_dates, price_map, baseline


def _load_signal_metadata(
    database: Path,
    replay_run_id: str,
    start: date,
    end: date,
) -> dict[tuple[date, str], tuple[Decimal, str]]:
    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT generated_at::DATE, isin,
                   TRY_CAST(recommendation_score AS DOUBLE), final_verdict
            FROM frozen_recommendation
            WHERE run_id = ? AND generated_at::DATE BETWEEN ? AND ?
            """,
            [replay_run_id, start, end],
        ).fetchall()
    return {
        (cast(date, row[0]), str(row[1])): (_decimal(row[2]), str(row[3]))
        for row in rows
    }


def _load_prices(
    *,
    database: Path,
    identities: tuple[str, ...],
    start: date,
    end: date,
) -> tuple[tuple[date, ...], dict[tuple[date, str], tuple[Decimal, Decimal]]]:
    placeholders = ", ".join("?" for _ in identities)
    with duckdb.connect(str(database), read_only=True) as connection:
        date_rows = connection.execute(
            """
            SELECT DISTINCT trading_date
            FROM research_daily_candle
            WHERE trading_date BETWEEN ? AND ?
              AND research_eligibility_state = 'ELIGIBLE_EQUITY'
            ORDER BY trading_date
            """,
            [start, end],
        ).fetchall()
        price_rows = connection.execute(
            f"""
            SELECT trading_date, isin, adjusted_open, adjusted_close
            FROM research_daily_candle
            WHERE trading_date BETWEEN ? AND ?
              AND isin IN ({placeholders})
              AND research_eligibility_state = 'ELIGIBLE_EQUITY'
            ORDER BY trading_date, isin
            """,
            [start, end, *identities],
        ).fetchall()
    trading_dates = tuple(cast(date, row[0]) for row in date_rows)
    price_map = {
        (cast(date, row[0]), str(row[1])): (_decimal(row[2]), _decimal(row[3]))
        for row in price_rows
    }
    return trading_dates, price_map


def _complete_position(
    policy: SizingPolicy,
    position: OpenSizingPosition,
    reason: str,
    exit_date: date,
) -> CompletedSizingTrade:
    cost = position.template.entry_price * Decimal(position.original_quantity)
    pnl = position.proceeds - cost
    initial_risk = (
        position.template.entry_price - position.template.initial_stop
    ) * Decimal(position.original_quantity)
    realized_r = _ZERO if initial_risk == 0 else pnl / initial_risk
    return CompletedSizingTrade(
        policy=policy.value,
        trade_id=position.template.trade_id,
        security_id=position.template.security_id,
        symbol=position.template.symbol,
        signal_date=position.template.signal_date,
        entry_date=position.template.entry_date,
        exit_date=exit_date,
        recommendation_score=position.template.recommendation_score,
        final_signal=position.template.final_signal,
        score_tier=position.template.score_tier,
        original_quantity=position.original_quantity,
        entry_price=position.template.entry_price,
        initial_stop=position.template.initial_stop,
        gross_profit_loss=pnl,
        gross_return_percent=_percent(position.proceeds / cost - _ONE),
        realized_r=realized_r,
        requested_risk_fraction=position.requested_risk_fraction,
        effective_risk_fraction=position.effective_risk_fraction,
        posterior_success_probability=position.posterior_success_probability,
        expected_r=position.expected_r,
        kelly_fraction=position.kelly_fraction,
        calibration_history_count=position.calibration_history_count,
        calibration_bucket_count=position.calibration_bucket_count,
        calibration_source=position.calibration_source,
        fallback_reason=position.fallback_reason,
        final_exit_reason=reason,
        exit_records=tuple(cast(list[dict[str, object]], position.exit_records)),
    )


def _scaled_leg_quantity(
    position: OpenSizingPosition,
    leg: ExitTemplate,
) -> int:
    if position.remaining_quantity <= 1:
        return 0
    fraction = Decimal(leg.baseline_quantity) / Decimal(
        position.template.baseline_quantity
    )
    quantity = int(
        (Decimal(position.original_quantity) * fraction).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    quantity = max(1, quantity)
    return min(quantity, position.remaining_quantity - 1)


def _open_initial_risk(positions: dict[str, OpenSizingPosition]) -> Decimal:
    return sum(
        (
            (item.template.entry_price - item.template.initial_stop)
            * Decimal(item.remaining_quantity)
            for item in positions.values()
        ),
        _ZERO,
    )


def _risk_sized_quantity(
    *,
    equity: Decimal,
    cash: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
    risk_fraction: Decimal,
) -> int:
    risk_per_share = entry_price - stop_price
    if equity <= 0 or cash <= 0 or entry_price <= 0 or risk_per_share <= 0:
        return 0
    risk_quantity = int(
        (equity * risk_fraction / risk_per_share).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    cash_quantity = int((cash / entry_price).to_integral_value(rounding=ROUND_FLOOR))
    return max(0, min(risk_quantity, cash_quantity))


def _reference_parity(
    *,
    baseline: dict[str, object],
    replay: dict[str, object],
) -> dict[str, object]:
    exact_fields = ("entry_count", "completed_trade_count")
    numeric_fields = (
        "gross_total_return_percent",
        "gross_cagr_percent",
        "maximum_drawdown_percent",
    )
    differences: dict[str, object] = {}
    for field in exact_fields:
        if int(cast(int, baseline[field])) != int(cast(int, replay[field])):
            differences[field] = {
                "baseline": baseline[field],
                "replay": replay[field],
            }
    for field in numeric_fields:
        baseline_value = _decimal(baseline[field])
        replay_value = _decimal(replay[field])
        if abs(baseline_value - replay_value) > Decimal("0.0001"):
            differences[field] = {
                "baseline": str(baseline_value),
                "replay": str(replay_value),
            }
    return {"passed": not differences, "differences": differences}


def _calibration_report(
    trades: tuple[CompletedSizingTrade, ...],
) -> dict[str, object]:
    report: dict[str, object] = {}
    for tier in ("LOW", "MID", "HIGH", "UNSEASONED"):
        selected = tuple(item for item in trades if item.score_tier == tier)
        if not selected:
            continue
        wins = tuple(item for item in selected if item.gross_profit_loss > 0)
        report[tier] = {
            "trade_count": len(selected),
            "win_rate_percent": str(
                _percent(Decimal(len(wins)) / Decimal(len(selected)))
            ),
            "expectancy_r": str(
                sum((item.realized_r for item in selected), _ZERO)
                / Decimal(len(selected))
            ),
            "average_effective_risk_percent": str(
                _percent(
                    sum((item.effective_risk_fraction for item in selected), _ZERO)
                    / Decimal(len(selected))
                )
            ),
        }
    ordered = [
        cast(dict[str, object], report[tier])
        for tier in ("LOW", "MID", "HIGH")
        if tier in report
    ]
    expectancy = [_decimal(item["expectancy_r"]) for item in ordered]
    report["monotonic_expectancy"] = (
        len(expectancy) == 3 and expectancy[0] <= expectancy[1] <= expectancy[2]
    )
    return report


def _meets_hurdles(row: dict[str, object]) -> bool:
    return (
        _optional_number(row.get("gross_cagr_percent")) > 5.7140
        and _optional_number(row.get("maximum_drawdown_percent")) >= -12
        and _optional_number(row.get("profit_factor")) >= 1.5
        and not bool(row.get("hard_stop_triggered"))
    )


def _rejection(
    policy: SizingPolicy,
    template: TradeTemplate,
    trading_date: date,
    reason: str,
) -> dict[str, object]:
    return {
        "policy": policy.value,
        "trade_id": template.trade_id,
        "security_id": template.security_id,
        "symbol": template.symbol,
        "signal_date": template.signal_date.isoformat(),
        "entry_date": trading_date.isoformat(),
        "reason": reason,
    }


def _nearest_rank(
    values: list[Decimal],
    numerator: int,
    denominator: int,
) -> Decimal:
    index = max(
        0,
        (len(values) * numerator + denominator - 1) // denominator - 1,
    )
    return values[min(index, len(values) - 1)]


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, _ZERO) / Decimal(len(values))


def _average_exposure(curve: tuple[SizingEquityPoint, ...]) -> str | None:
    values = tuple(item.market_value / item.equity for item in curve if item.equity > 0)
    average = _average(values)
    return None if average is None else str(_percent(average))


def _turnover(
    trades: tuple[CompletedSizingTrade, ...],
    initial_capital: Decimal,
) -> str:
    notional = _ZERO
    for trade in trades:
        notional += trade.entry_price * Decimal(trade.original_quantity)
        notional += sum(
            (
                _decimal(item["exit_price"]) * Decimal(int(cast(int, item["quantity"])))
                for item in trade.exit_records
            ),
            _ZERO,
        )
    return str(_percent(notional / initial_capital))


def _decimal(value: object) -> Decimal:
    if value is None:
        return _ZERO
    return Decimal(str(value))


def _percent(value: Decimal) -> Decimal:
    return (value * _HUNDRED).quantize(Decimal("0.0001"))


def _optional_number(value: object) -> float:
    if value is None:
        return float("-inf")
    if isinstance(value, (str, int, float, Decimal)):
        return float(value)
    raise TypeError(f"unsupported numeric value: {type(value).__name__}")


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _source_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = [key for key in rows[0] if key not in {"exit_records"}]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _write_markdown(path: Path, payload: dict[str, object]) -> None:
    comparison = cast(list[dict[str, object]], payload["policy_comparison"])
    parity = cast(dict[str, object], payload["reference_parity"])
    lines = [
        "# DSI-011D Calibrated Edge and Position-Sizing Audit",
        "",
        f"- Fixed trade paths: {payload['fixed_trade_path_count']}",
        f"- Reference parity: {parity['passed']}",
        f"- Production influence: {payload['production_influence']}",
        "",
        "| Rank | Policy | CAGR % | MDD % | Profit factor | Trades | Hurdles |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for row in comparison:
        lines.append(
            (
                "| {rank} | {policy} | {cagr} | {mdd} | {pf} | {trades} | {hurdles} |"
            ).format(
                rank=row.get("descriptive_rank"),
                policy=row.get("policy"),
                cagr=row.get("gross_cagr_percent"),
                mdd=row.get("maximum_drawdown_percent"),
                pf=row.get("profit_factor"),
                trades=row.get("completed_trade_count"),
                hurdles=row.get("meets_research_hurdles"),
            )
        )
    lines.extend(
        [
            "",
            "Results are retrospective and gross of transaction costs and slippage.",
            "No policy is automatically promoted.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--challenger-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    run_sizing_audit(
        database=args.database,
        challenger_output=args.challenger_output,
        output=args.output,
    )


if __name__ == "__main__":
    main()


__all__ = [
    "AUDIT_VERSION",
    "CalibrationEstimate",
    "SizingAuditConfig",
    "SizingDecision",
    "SizingPolicy",
    "TradeTemplate",
    "assign_walk_forward_score_tiers",
    "calibration_estimate",
    "load_audit_inputs",
    "run_sizing_audit",
    "simulate_policy",
    "sizing_decision",
]
