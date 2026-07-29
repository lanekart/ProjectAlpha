"""Governed DSI-011C 20-DMA reclaim portfolio challenger.

This module intentionally implements the exact frozen challenger as a separate
research-only engine. It does not modify production recommendation, portfolio,
or risk policy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import duckdb
import numpy as np
import pandas as pd

from alpha.research.lab_data_contract import ResearchDataContractAuditor
from alpha.research.lab_models import AlphaSignalSource

CHALLENGER_VERSION = "DSI-011C-20DMA-RECLAIM-v1.0.0"
PRODUCTION_INFLUENCE = False
_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class ChallengerConfig:
    initial_capital: Decimal = Decimal("10000000")
    full_risk_fraction: Decimal = Decimal("0.01")
    throttled_risk_fraction: Decimal = Decimal("0.005")
    maximum_positions: int = 5
    fixed_stop_percent: Decimal = Decimal("5")
    first_target_r: Decimal = Decimal("2")
    final_target_r: Decimal = Decimal("3")
    partial_exit_percent: Decimal = Decimal("50")
    maximum_holding_sessions: int = 40
    drawdown_throttle_percent: Decimal = Decimal("8")
    hard_stop_percent: Decimal = Decimal("12")
    sma20_rise_lookback: int = 5
    volume_contraction_sessions: int = 3
    volume_baseline_sessions: int = 20
    volume_expansion_multiple: Decimal = Decimal("1.5")
    positive_regime: str = "POSITIVE"
    same_session_policy: str = "STOP_FIRST"
    transaction_cost_model: str = "NONE"
    slippage_model: str = "NONE"
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial capital must be positive")
        if not (Decimal("0") < self.full_risk_fraction <= Decimal("1")):
            raise ValueError("full risk fraction must be in (0, 1]")
        if not (Decimal("0") < self.throttled_risk_fraction <= self.full_risk_fraction):
            raise ValueError("throttled risk must be positive and no greater than full risk")
        if self.maximum_positions < 1:
            raise ValueError("maximum positions must be positive")
        if not (Decimal("0") < self.fixed_stop_percent < Decimal("100")):
            raise ValueError("fixed stop percent must be in (0, 100)")
        if self.first_target_r <= 0 or self.final_target_r <= self.first_target_r:
            raise ValueError("final R target must exceed the positive first target")
        if not (Decimal("0") < self.partial_exit_percent < Decimal("100")):
            raise ValueError("partial exit percent must be in (0, 100)")
        if self.maximum_holding_sessions < 1:
            raise ValueError("maximum holding sessions must be positive")
        if self.drawdown_throttle_percent <= 0:
            raise ValueError("drawdown throttle must be positive")
        if self.hard_stop_percent <= self.drawdown_throttle_percent:
            raise ValueError("hard stop must exceed drawdown throttle")
        if self.sma20_rise_lookback < 1:
            raise ValueError("SMA rise lookback must be positive")
        if self.volume_contraction_sessions < 1 or self.volume_baseline_sessions < 2:
            raise ValueError("volume windows are invalid")
        if self.volume_expansion_multiple <= 0:
            raise ValueError("volume expansion multiple must be positive")
        if self.same_session_policy != "STOP_FIRST":
            raise ValueError("DSI-011C supports only conservative stop-first handling")
        if self.transaction_cost_model != "NONE" or self.slippage_model != "NONE":
            raise ValueError("DSI-011C remains gross-of-costs research")
        if self.production_influence:
            raise ValueError("research challenger cannot influence production")

    def as_dict(self) -> dict[str, object]:
        return _jsonable(asdict(self))


@dataclass(frozen=True, slots=True)
class PendingEntry:
    security_id: str
    symbol: str
    signal_date: date
    final_signal: str
    recommendation_score: Decimal


@dataclass(frozen=True, slots=True)
class ExitLeg:
    exit_date: date
    quantity: int
    exit_price: Decimal
    reason: str
    ambiguous_session: bool

    def as_dict(self) -> dict[str, object]:
        return _jsonable(asdict(self))


@dataclass(slots=True)
class OpenPosition:
    trade_id: str
    security_id: str
    symbol: str
    signal_date: date
    entry_date: date
    original_quantity: int
    remaining_quantity: int
    entry_price: Decimal
    initial_stop: Decimal
    first_target: Decimal
    final_target: Decimal
    holding_sessions: int = 0
    partial_completed: bool = False
    exit_legs: list[ExitLeg] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CompletedTrade:
    trade_id: str
    security_id: str
    symbol: str
    signal_date: date
    entry_date: date
    exit_date: date
    original_quantity: int
    entry_price: Decimal
    initial_stop: Decimal
    first_target: Decimal
    final_target: Decimal
    gross_profit_loss: Decimal
    gross_return_percent: Decimal
    holding_sessions: int
    final_exit_reason: str
    partial_exit_completed: bool
    exit_legs: tuple[ExitLeg, ...]

    def as_dict(self) -> dict[str, object]:
        payload = _jsonable(asdict(self))
        payload["exit_legs"] = [item.as_dict() for item in self.exit_legs]
        return payload


@dataclass(frozen=True, slots=True)
class RejectedEntry:
    trading_date: date
    security_id: str
    symbol: str
    signal_date: date
    reason: str

    def as_dict(self) -> dict[str, object]:
        return _jsonable(asdict(self))


@dataclass(frozen=True, slots=True)
class EquityPoint:
    trading_date: date
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    drawdown_percent: Decimal
    open_positions: int
    new_entry_risk_fraction: Decimal
    hard_stop_active: bool

    def as_dict(self) -> dict[str, object]:
        return _jsonable(asdict(self))


@dataclass(frozen=True, slots=True)
class ChallengerResult:
    trades: tuple[CompletedTrade, ...]
    rejected_entries: tuple[RejectedEntry, ...]
    equity_curve: tuple[EquityPoint, ...]
    signal_count: int
    entry_count: int
    ambiguous_session_count: int
    hard_stop_date: date | None
    starting_capital: Decimal
    ending_equity: Decimal

    def summary(self) -> dict[str, object]:
        wins = tuple(item for item in self.trades if item.gross_profit_loss > 0)
        losses = tuple(item for item in self.trades if item.gross_profit_loss < 0)
        gross_gains = sum((item.gross_profit_loss for item in wins), _ZERO)
        gross_losses = abs(sum((item.gross_profit_loss for item in losses), _ZERO))
        average_return = (
            None
            if not self.trades
            else sum((item.gross_return_percent for item in self.trades), _ZERO)
            / Decimal(len(self.trades))
        )
        elapsed_days = (
            0
            if len(self.equity_curve) < 2
            else (self.equity_curve[-1].trading_date - self.equity_curve[0].trading_date).days
        )
        cagr = None
        if elapsed_days > 0 and self.ending_equity > 0:
            exponent = Decimal("365.2425") / Decimal(elapsed_days)
            cagr = _percent((self.ending_equity / self.starting_capital) ** exponent - 1)
        return {
            "initial_capital": str(self.starting_capital),
            "final_equity": str(self.ending_equity),
            "gross_total_return_percent": str(
                _percent(self.ending_equity / self.starting_capital - 1)
            ),
            "gross_cagr_percent": None if cagr is None else str(cagr),
            "maximum_drawdown_percent": (
                None
                if not self.equity_curve
                else str(min(item.drawdown_percent for item in self.equity_curve))
            ),
            "maximum_drawdown_duration_sessions": _maximum_drawdown_duration(
                self.equity_curve
            ),
            "signal_count": self.signal_count,
            "entry_count": self.entry_count,
            "completed_trade_count": len(self.trades),
            "rejected_entry_count": len(self.rejected_entries),
            "win_rate_percent": (
                None
                if not self.trades
                else str(_percent(Decimal(len(wins)) / Decimal(len(self.trades))))
            ),
            "expectancy_percent": None if average_return is None else str(average_return),
            "profit_factor": (
                None if gross_losses == 0 else str(gross_gains / gross_losses)
            ),
            "average_holding_period": (
                None
                if not self.trades
                else str(
                    Decimal(sum(item.holding_sessions for item in self.trades))
                    / Decimal(len(self.trades))
                )
            ),
            "average_exposure_percent": _average_exposure(self.equity_curve),
            "turnover_percent": _turnover(self.trades, self.starting_capital),
            "ambiguous_session_count": self.ambiguous_session_count,
            "hard_stop_date": (
                None if self.hard_stop_date is None else self.hard_stop_date.isoformat()
            ),
            "hard_stop_triggered": self.hard_stop_date is not None,
            "transaction_cost_model": "NONE",
            "slippage_model": "NONE",
            "results_are_gross_of_costs": True,
            "production_influence": False,
        }


def load_research_frame(database: Path) -> tuple[pd.DataFrame, str, date, date]:
    if not database.is_file():
        raise FileNotFoundError(f"Historical Truth database not found: {database}")
    contract = ResearchDataContractAuditor().audit(database)
    if not contract.ready:
        raise RuntimeError(
            "research data contract is not ready: " + ", ".join(contract.blockers)
        )
    source = AlphaSignalSource.RETROSPECTIVE_FROZEN_ALPHA_REPLAY
    if not contract.signal_source_ready(source):
        raise RuntimeError("retrospective frozen Alpha signal population is not ready")
    if contract.actual_start is None or contract.actual_end is None:
        raise RuntimeError("certified research boundary is unavailable")

    start = contract.actual_start
    end = contract.actual_end
    with duckdb.connect(str(database), read_only=True) as connection:
        run = connection.execute(
            """
            SELECT run_id
            FROM frozen_recommendation_replay_run
            WHERE start_date <= ? AND end_date >= ?
              AND readiness_state = 'RETROSPECTIVE_ALPHA_REPLAY_READY'
            ORDER BY start_date DESC, end_date ASC, run_id
            LIMIT 1
            """,
            [start, end],
        ).fetchone()
        if run is None:
            raise RuntimeError("no certified retrospective Alpha replay covers the window")
        run_id = str(run[0])
        frame = connection.execute(
            """
            WITH signals AS (
                SELECT generated_at::DATE AS trading_date,
                       isin AS security_id,
                       final_verdict AS final_signal,
                       regime,
                       TRY_CAST(recommendation_score AS DOUBLE) AS recommendation_score
                FROM frozen_recommendation
                WHERE run_id = ?
                  AND generated_at::DATE BETWEEN ? AND ?
                  AND final_verdict IN ('BUY', 'STRONG_BUY')
            ), identities AS (
                SELECT DISTINCT security_id FROM signals
            )
            SELECT c.trading_date,
                   c.isin AS security_id,
                   c.symbol,
                   c.adjusted_open AS open,
                   c.adjusted_high AS high,
                   c.adjusted_low AS low,
                   c.adjusted_close AS close,
                   c.adjusted_volume AS volume,
                   s.final_signal,
                   s.regime,
                   COALESCE(s.recommendation_score, 0.0) AS recommendation_score
            FROM research_daily_candle c
            JOIN identities i ON i.security_id = c.isin
            LEFT JOIN signals s
              ON s.trading_date = c.trading_date
             AND s.security_id = c.isin
            WHERE UPPER(c.exchange) = 'NSE'
              AND c.trading_date BETWEEN ? AND ?
              AND c.research_eligibility_state = 'ELIGIBLE_EQUITY'
              AND c.adjusted_open > 0
              AND c.adjusted_high > 0
              AND c.adjusted_low > 0
              AND c.adjusted_close > 0
              AND c.adjusted_volume >= 0
            ORDER BY c.trading_date, c.isin
            """,
            [run_id, start, end, start, end],
        ).fetchdf()
    return frame, run_id, start, end


def engineer_signals(frame: pd.DataFrame, config: ChallengerConfig) -> pd.DataFrame:
    required = {
        "trading_date",
        "security_id",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "final_signal",
        "regime",
        "recommendation_score",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"challenger frame missing columns: {sorted(missing)}")

    result = frame.copy()
    result["trading_date"] = pd.to_datetime(result["trading_date"])
    result = result.sort_values(["security_id", "trading_date"], kind="stable")
    grouped = result.groupby("security_id", sort=False, group_keys=False)
    result["sma20"] = grouped["close"].transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    result["sma200"] = grouped["close"].transform(
        lambda values: values.rolling(200, min_periods=200).mean()
    )
    result["sma20_lag"] = grouped["sma20"].shift(config.sma20_rise_lookback)
    result["sma20_previous"] = grouped["sma20"].shift(1)
    result["close_previous"] = grouped["close"].shift(1)
    result["rsi14"] = grouped["close"].transform(_rsi14)
    result["volume_prior_contraction"] = grouped["volume"].transform(
        lambda values: values.rolling(
            config.volume_contraction_sessions,
            min_periods=config.volume_contraction_sessions,
        ).mean().shift(1)
    )
    result["volume_prior_baseline"] = grouped["volume"].transform(
        lambda values: values.rolling(
            config.volume_baseline_sessions,
            min_periods=config.volume_baseline_sessions,
        ).mean().shift(1)
    )

    alpha_signal = result["final_signal"].isin(("BUY", "STRONG_BUY"))
    positive_regime = result["regime"].eq(config.positive_regime)
    long_term_trend = result["close"] > result["sma200"]
    rising_sma20 = result["sma20"] > result["sma20_lag"]
    reclaim = (result["close"] > result["sma20"]) & (
        result["close_previous"] <= result["sma20_previous"]
    )
    momentum = result["rsi14"] >= 50
    contraction = (
        result["volume_prior_contraction"] <= result["volume_prior_baseline"]
    )
    expansion = result["volume"] >= (
        result["volume_prior_baseline"] * float(config.volume_expansion_multiple)
    )

    result["alpha_signal_ok"] = alpha_signal
    result["positive_regime_ok"] = positive_regime
    result["long_term_trend_ok"] = long_term_trend
    result["rising_sma20_ok"] = rising_sma20
    result["reclaim_ok"] = reclaim
    result["momentum_ok"] = momentum
    result["volume_contraction_ok"] = contraction
    result["volume_expansion_ok"] = expansion
    result["research_signal"] = (
        alpha_signal
        & positive_regime
        & long_term_trend
        & rising_sma20
        & reclaim
        & momentum
        & contraction
        & expansion
    ).fillna(False)
    return result.sort_values(["trading_date", "security_id"], kind="stable")


def risk_sized_quantity(
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
    risk_budget = equity * risk_fraction
    risk_quantity = int((risk_budget / risk_per_share).to_integral_value(rounding="ROUND_FLOOR"))
    cash_quantity = int((cash / entry_price).to_integral_value(rounding="ROUND_FLOOR"))
    return max(0, min(risk_quantity, cash_quantity))


def simulate_challenger(
    featured: pd.DataFrame,
    config: ChallengerConfig | None = None,
) -> ChallengerResult:
    resolved = config or ChallengerConfig()
    required = {
        "trading_date",
        "security_id",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "sma20_previous",
        "research_signal",
        "final_signal",
        "recommendation_score",
    }
    missing = required - set(featured.columns)
    if missing:
        raise ValueError(f"featured challenger frame missing columns: {sorted(missing)}")

    rows = featured.copy()
    rows["trading_date"] = pd.to_datetime(rows["trading_date"]).dt.date
    rows = rows.sort_values(["trading_date", "security_id"], kind="stable")

    cash = resolved.initial_capital
    peak_equity = resolved.initial_capital
    last_equity = resolved.initial_capital
    positions: dict[str, OpenPosition] = {}
    pending: dict[str, PendingEntry] = {}
    completed: list[CompletedTrade] = []
    rejected: list[RejectedEntry] = []
    curve: list[EquityPoint] = []
    latest_close: dict[str, Decimal] = {}
    signal_count = int(rows["research_signal"].fillna(False).sum())
    entry_count = 0
    ambiguous_count = 0
    trade_counter = 0
    hard_stop_date: date | None = None
    terminated = False

    for group_date, daily in rows.groupby("trading_date", sort=True):
        trading_date = cast(date, group_date)
        records = cast(list[dict[str, Any]], daily.to_dict("records"))
        row_by_id = {str(item["security_id"]): item for item in records}

        for security_id in sorted(tuple(positions)):
            row = row_by_id.get(security_id)
            if row is None:
                continue
            position = positions[security_id]
            position.holding_sessions += 1
            open_price = _decimal(row["open"])
            high = _decimal(row["high"])
            low = _decimal(row["low"])
            close = _decimal(row["close"])
            prior_sma20 = _optional_decimal(row.get("sma20_previous"))
            active_stop = position.initial_stop
            if position.partial_completed and prior_sma20 is not None:
                active_stop = max(active_stop, prior_sma20)

            stop_hit = low <= active_stop
            first_hit = not position.partial_completed and high >= position.first_target
            final_hit = high >= position.final_target
            ambiguous = stop_hit and (first_hit or final_hit)
            if ambiguous:
                ambiguous_count += 1

            if stop_hit:
                fill = min(open_price, active_stop)
                reason = (
                    "INTRADAY_PATH_AMBIGUOUS_STOP_FIRST"
                    if ambiguous
                    else (
                        "TRAIL_20DMA"
                        if position.partial_completed and active_stop > position.initial_stop
                        else "INITIAL_STOP"
                    )
                )
                cash += _exit_position(
                    position,
                    trading_date=trading_date,
                    quantity=position.remaining_quantity,
                    exit_price=fill,
                    reason=reason,
                    ambiguous=ambiguous,
                )
                completed.append(_complete_position(position, reason))
                del positions[security_id]
                continue

            if not position.partial_completed and first_hit:
                partial_quantity = int(
                    Decimal(position.original_quantity)
                    * resolved.partial_exit_percent
                    / _HUNDRED
                )
                partial_quantity = min(partial_quantity, position.remaining_quantity - 1)
                if partial_quantity > 0:
                    fill = max(open_price, position.first_target)
                    cash += _exit_position(
                        position,
                        trading_date=trading_date,
                        quantity=partial_quantity,
                        exit_price=fill,
                        reason="TARGET_2R_PARTIAL",
                        ambiguous=False,
                    )
                position.partial_completed = True

            if final_hit and security_id in positions:
                fill = max(open_price, position.final_target)
                cash += _exit_position(
                    position,
                    trading_date=trading_date,
                    quantity=position.remaining_quantity,
                    exit_price=fill,
                    reason="TARGET_3R",
                    ambiguous=False,
                )
                completed.append(_complete_position(position, "TARGET_3R"))
                del positions[security_id]
                continue

            if (
                security_id in positions
                and position.holding_sessions >= resolved.maximum_holding_sessions
            ):
                cash += _exit_position(
                    position,
                    trading_date=trading_date,
                    quantity=position.remaining_quantity,
                    exit_price=close,
                    reason="TIME_EXIT",
                    ambiguous=False,
                )
                completed.append(_complete_position(position, "TIME_EXIT"))
                del positions[security_id]

        prior_drawdown = _percent(last_equity / peak_equity - 1)
        risk_fraction = resolved.full_risk_fraction
        if prior_drawdown <= -resolved.drawdown_throttle_percent:
            risk_fraction = resolved.throttled_risk_fraction
        if prior_drawdown <= -resolved.hard_stop_percent or terminated:
            risk_fraction = _ZERO

        pending_candidates = sorted(
            pending.values(),
            key=lambda item: (
                0 if item.final_signal == "STRONG_BUY" else 1,
                -item.recommendation_score,
                item.security_id,
            ),
        )
        pending = {}
        for candidate in pending_candidates:
            row = row_by_id.get(candidate.security_id)
            if row is None:
                pending[candidate.security_id] = candidate
                continue
            if candidate.security_id in positions:
                continue
            if terminated or risk_fraction <= 0:
                rejected.append(
                    RejectedEntry(
                        trading_date,
                        candidate.security_id,
                        candidate.symbol,
                        candidate.signal_date,
                        "PORTFOLIO_HARD_STOP_ACTIVE",
                    )
                )
                continue
            if len(positions) >= resolved.maximum_positions:
                rejected.append(
                    RejectedEntry(
                        trading_date,
                        candidate.security_id,
                        candidate.symbol,
                        candidate.signal_date,
                        "MAXIMUM_POSITIONS_REACHED",
                    )
                )
                continue

            entry_price = _decimal(row["open"])
            opening_market_value = sum(
                (
                    _decimal(row_by_id[key]["open"]) * Decimal(item.remaining_quantity)
                    if key in row_by_id
                    else latest_close.get(key, item.entry_price)
                    * Decimal(item.remaining_quantity)
                )
                for key, item in positions.items()
            )
            opening_equity = cash + opening_market_value
            stop_price = entry_price * (
                _ONE - resolved.fixed_stop_percent / _HUNDRED
            )
            quantity = risk_sized_quantity(
                equity=opening_equity,
                cash=cash,
                entry_price=entry_price,
                stop_price=stop_price,
                risk_fraction=risk_fraction,
            )
            if quantity < 1:
                rejected.append(
                    RejectedEntry(
                        trading_date,
                        candidate.security_id,
                        candidate.symbol,
                        candidate.signal_date,
                        "INSUFFICIENT_RISK_OR_CASH_CAPACITY",
                    )
                )
                continue

            risk_per_share = entry_price - stop_price
            trade_counter += 1
            positions[candidate.security_id] = OpenPosition(
                trade_id=f"DSI011C-T{trade_counter:06d}",
                security_id=candidate.security_id,
                symbol=candidate.symbol,
                signal_date=candidate.signal_date,
                entry_date=trading_date,
                original_quantity=quantity,
                remaining_quantity=quantity,
                entry_price=entry_price,
                initial_stop=stop_price,
                first_target=entry_price + risk_per_share * resolved.first_target_r,
                final_target=entry_price + risk_per_share * resolved.final_target_r,
            )
            cash -= entry_price * Decimal(quantity)
            entry_count += 1

        if not terminated:
            for row in records:
                security_id = str(row["security_id"])
                if not bool(row["research_signal"]):
                    continue
                if security_id in positions or security_id in pending:
                    continue
                pending[security_id] = PendingEntry(
                    security_id=security_id,
                    symbol=str(row["symbol"]),
                    signal_date=trading_date,
                    final_signal=str(row["final_signal"]),
                    recommendation_score=_decimal(row["recommendation_score"]),
                )

        for row in records:
            latest_close[str(row["security_id"])] = _decimal(row["close"])
        market_value = sum(
            latest_close.get(key, item.entry_price) * Decimal(item.remaining_quantity)
            for key, item in positions.items()
        )
        equity = cash + market_value
        peak_equity = max(peak_equity, equity)
        drawdown = _percent(equity / peak_equity - 1)

        if not terminated and drawdown <= -resolved.hard_stop_percent:
            for security_id in sorted(tuple(positions)):
                position = positions[security_id]
                exit_price = latest_close.get(security_id, position.entry_price)
                cash += _exit_position(
                    position,
                    trading_date=trading_date,
                    quantity=position.remaining_quantity,
                    exit_price=exit_price,
                    reason="HARD_PORTFOLIO_STOP",
                    ambiguous=False,
                )
                completed.append(_complete_position(position, "HARD_PORTFOLIO_STOP"))
                del positions[security_id]
            pending = {}
            terminated = True
            hard_stop_date = trading_date
            market_value = _ZERO
            equity = cash
            drawdown = _percent(equity / peak_equity - 1)

        next_risk_fraction = resolved.full_risk_fraction
        if drawdown <= -resolved.drawdown_throttle_percent:
            next_risk_fraction = resolved.throttled_risk_fraction
        if terminated or drawdown <= -resolved.hard_stop_percent:
            next_risk_fraction = _ZERO
        curve.append(
            EquityPoint(
                trading_date=trading_date,
                cash=cash,
                market_value=market_value,
                equity=equity,
                drawdown_percent=drawdown,
                open_positions=len(positions),
                new_entry_risk_fraction=next_risk_fraction,
                hard_stop_active=terminated,
            )
        )
        last_equity = equity

    if curve and positions:
        final_date = curve[-1].trading_date
        for security_id in sorted(tuple(positions)):
            position = positions[security_id]
            exit_price = latest_close.get(security_id, position.entry_price)
            cash += _exit_position(
                position,
                trading_date=final_date,
                quantity=position.remaining_quantity,
                exit_price=exit_price,
                reason="FORCED_BOUNDARY_EXIT",
                ambiguous=False,
            )
            completed.append(_complete_position(position, "FORCED_BOUNDARY_EXIT"))
        positions = {}
        final_drawdown = _percent(cash / max(peak_equity, cash) - 1)
        curve[-1] = EquityPoint(
            trading_date=final_date,
            cash=cash,
            market_value=_ZERO,
            equity=cash,
            drawdown_percent=final_drawdown,
            open_positions=0,
            new_entry_risk_fraction=_ZERO if terminated else resolved.full_risk_fraction,
            hard_stop_active=terminated,
        )

    return ChallengerResult(
        trades=tuple(completed),
        rejected_entries=tuple(rejected),
        equity_curve=tuple(curve),
        signal_count=signal_count,
        entry_count=entry_count,
        ambiguous_session_count=ambiguous_count,
        hard_stop_date=hard_stop_date,
        starting_capital=resolved.initial_capital,
        ending_equity=cash,
    )


def run_challenger(
    *,
    database: Path,
    output: Path,
    config: ChallengerConfig | None = None,
) -> dict[str, object]:
    resolved = config or ChallengerConfig()
    output.mkdir(parents=True, exist_ok=True)
    frame, replay_run_id, start, end = load_research_frame(database)
    featured = engineer_signals(frame, resolved)
    result = simulate_challenger(featured, resolved)
    summary = result.summary()
    source_commit = _source_commit()

    signal_audit = {
        "population_rows": int(len(featured)),
        "alpha_signal_rows": int(featured["alpha_signal_ok"].sum()),
        "positive_regime_rows": int(featured["positive_regime_ok"].sum()),
        "long_term_trend_rows": int(featured["long_term_trend_ok"].sum()),
        "rising_sma20_rows": int(featured["rising_sma20_ok"].sum()),
        "reclaim_rows": int(featured["reclaim_ok"].sum()),
        "momentum_rows": int(featured["momentum_ok"].sum()),
        "volume_contraction_rows": int(featured["volume_contraction_ok"].sum()),
        "volume_expansion_rows": int(featured["volume_expansion_ok"].sum()),
        "final_signal_rows": int(featured["research_signal"].sum()),
    }
    payload: dict[str, object] = {
        "challenger_version": CHALLENGER_VERSION,
        "source_commit": source_commit,
        "retrospective_alpha_replay_run_id": replay_run_id,
        "data_start": start.isoformat(),
        "data_end": end.isoformat(),
        "strategy_name": "ALPHA_20DMA_RECLAIM_200DMA_TREND_5STOP_STAGED_2R_3R",
        "strategy_specification": _strategy_specification(resolved),
        "config": resolved.as_dict(),
        "signal_audit": signal_audit,
        "summary": summary,
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

    _write_json(output / "challenger_result.json", payload)
    _write_json(output / "strategy_spec.json", payload["strategy_specification"])
    _write_json(output / "signal_audit.json", signal_audit)
    _write_json(output / "trades.json", [item.as_dict() for item in result.trades])
    _write_json(
        output / "rejected_entries.json",
        [item.as_dict() for item in result.rejected_entries],
    )
    _write_json(
        output / "equity_curve.json",
        [item.as_dict() for item in result.equity_curve],
    )
    _write_csv(output / "trades.csv", [item.as_dict() for item in result.trades])
    _write_csv(
        output / "equity_curve.csv",
        [item.as_dict() for item in result.equity_curve],
    )
    _write_markdown(output / "challenger_result.md", payload)
    _write_json(
        output / "manifest.json",
        {
            "challenger_version": CHALLENGER_VERSION,
            "source_commit": source_commit,
            "retrospective_alpha_replay_run_id": replay_run_id,
            "artifact_logical_sha256": logical_hash,
            "production_influence": False,
            "automatic_strategy_promotion": False,
        },
    )

    print("DSI-011C challenger complete")
    print(f"Signals: {summary['signal_count']}")
    print(f"Entries: {summary['entry_count']}")
    print(f"Completed trades: {summary['completed_trade_count']}")
    print(f"Gross CAGR: {summary['gross_cagr_percent']}")
    print(f"Maximum drawdown: {summary['maximum_drawdown_percent']}")
    print(f"Hard stop triggered: {summary['hard_stop_triggered']}")
    print(f"Artifact logical SHA-256: {logical_hash}")
    print(f"Results: {output / 'challenger_result.json'}")
    return payload


def _strategy_specification(config: ChallengerConfig) -> dict[str, object]:
    return {
        "signal_source": "RETROSPECTIVE_FROZEN_ALPHA_REPLAY",
        "signal_verdicts": ["BUY", "STRONG_BUY"],
        "regime": "POSITIVE only",
        "long_term_trend": "close > point-in-time SMA(200)",
        "timing": (
            "close crosses from at-or-below SMA(20) on the prior session to above "
            "SMA(20) on the signal session"
        ),
        "sma20_direction": (
            f"SMA(20) today > SMA(20) {config.sma20_rise_lookback} sessions ago"
        ),
        "momentum": "RSI(14) >= 50",
        "volume_contraction": (
            f"prior {config.volume_contraction_sessions}-session average volume <= "
            f"prior {config.volume_baseline_sessions}-session average volume"
        ),
        "volume_expansion": (
            f"signal-session volume >= {config.volume_expansion_multiple} x prior "
            f"{config.volume_baseline_sessions}-session average volume"
        ),
        "entry": "next valid eligible-equity session open",
        "candidate_priority": "STRONG_BUY, then recommendation score, then security id",
        "position_sizing": "fixed fractional risk using initial 5% stop",
        "risk_per_new_position": "1.0% of opening portfolio equity",
        "drawdown_throttled_risk": "0.5% when previous close drawdown is at least 8%",
        "maximum_positions": config.maximum_positions,
        "initial_stop": "5% below entry; adverse open gaps fill at the open",
        "first_exit": "50% at 2R when quantity permits",
        "final_exit": "remaining quantity at earliest of 3R or prior-session SMA(20) trail",
        "same_session_ambiguity": "stop-first",
        "maximum_holding_sessions": config.maximum_holding_sessions,
        "portfolio_hard_stop": (
            "liquidate at session close and permanently terminate new entries when "
            "close-to-close portfolio drawdown reaches or exceeds 12%"
        ),
        "transaction_cost_model": "NONE",
        "slippage_model": "NONE",
        "production_influence": False,
    }


def _exit_position(
    position: OpenPosition,
    *,
    trading_date: date,
    quantity: int,
    exit_price: Decimal,
    reason: str,
    ambiguous: bool,
) -> Decimal:
    if quantity < 1 or quantity > position.remaining_quantity:
        raise ValueError("invalid exit quantity")
    position.exit_legs.append(
        ExitLeg(
            exit_date=trading_date,
            quantity=quantity,
            exit_price=exit_price,
            reason=reason,
            ambiguous_session=ambiguous,
        )
    )
    position.remaining_quantity -= quantity
    return exit_price * Decimal(quantity)


def _complete_position(position: OpenPosition, reason: str) -> CompletedTrade:
    if position.remaining_quantity != 0:
        raise ValueError("cannot complete a position with remaining quantity")
    proceeds = sum(
        (item.exit_price * Decimal(item.quantity) for item in position.exit_legs),
        _ZERO,
    )
    cost = position.entry_price * Decimal(position.original_quantity)
    pnl = proceeds - cost
    return CompletedTrade(
        trade_id=position.trade_id,
        security_id=position.security_id,
        symbol=position.symbol,
        signal_date=position.signal_date,
        entry_date=position.entry_date,
        exit_date=position.exit_legs[-1].exit_date,
        original_quantity=position.original_quantity,
        entry_price=position.entry_price,
        initial_stop=position.initial_stop,
        first_target=position.first_target,
        final_target=position.final_target,
        gross_profit_loss=pnl,
        gross_return_percent=_percent(proceeds / cost - 1),
        holding_sessions=position.holding_sessions,
        final_exit_reason=reason,
        partial_exit_completed=position.partial_completed,
        exit_legs=tuple(position.exit_legs),
    )


def _rsi14(values: pd.Series) -> pd.Series:
    delta = values.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14,
    ).mean()
    strength = gain / loss.replace(0, np.nan)
    result = 100 - 100 / (1 + strength)
    return result.where(loss.ne(0), 100.0)


def _maximum_drawdown_duration(curve: tuple[EquityPoint, ...]) -> int:
    longest = 0
    current = 0
    for point in curve:
        if point.drawdown_percent < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _average_exposure(curve: tuple[EquityPoint, ...]) -> str | None:
    values = tuple(
        point.market_value / point.equity for point in curve if point.equity > 0
    )
    if not values:
        return None
    return str(_percent(sum(values, _ZERO) / Decimal(len(values))))


def _turnover(trades: tuple[CompletedTrade, ...], initial_capital: Decimal) -> str:
    notional = _ZERO
    for trade in trades:
        notional += trade.entry_price * Decimal(trade.original_quantity)
        notional += sum(
            (leg.exit_price * Decimal(leg.quantity) for leg in trade.exit_legs),
            _ZERO,
        )
    return str(_percent(notional / initial_capital))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = [key for key in rows[0] if key != "exit_legs"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _write_markdown(path: Path, payload: dict[str, object]) -> None:
    summary = cast(dict[str, object], payload["summary"])
    signal_audit = cast(dict[str, object], payload["signal_audit"])
    lines = [
        "# DSI-011C 20-DMA Reclaim Portfolio Challenger",
        "",
        f"- Data range: {payload['data_start']} to {payload['data_end']}",
        f"- Signals: {summary['signal_count']}",
        f"- Entries: {summary['entry_count']}",
        f"- Completed trades: {summary['completed_trade_count']}",
        f"- Gross CAGR: {summary['gross_cagr_percent']}%",
        f"- Maximum drawdown: {summary['maximum_drawdown_percent']}%",
        f"- Hard stop triggered: {summary['hard_stop_triggered']}",
        f"- Final signal rows: {signal_audit['final_signal_rows']}",
        "- Results are gross of transaction costs and slippage.",
        "- PRODUCTION_INFLUENCE=false",
        "",
        "## Frozen strategy",
        "",
        "- Alpha BUY/STRONG BUY, positive regime only",
        "- close above SMA(200)",
        "- true close-based reclaim of a rising SMA(20)",
        "- RSI(14) at least 50",
        "- three-session volume contraction followed by 1.5x expansion",
        "- next-session-open entry",
        "- 1% risk per position; 0.5% after 8% portfolio drawdown",
        "- maximum five positions",
        "- 5% initial stop",
        "- half at 2R; remainder at 3R or prior-session SMA(20) trail",
        "- 40-session maximum hold",
        "- close-based 12% portfolio hard stop and permanent termination",
        "",
        "## Governance",
        "",
        f"- Artifact logical SHA-256: `{payload['artifact_logical_sha256']}`",
        "- No automatic strategy promotion.",
        "- Retrospective signals are not historically issued recommendations.",
        "- PRODUCTION_INFLUENCE=false",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _source_commit() -> str:
    try:
        return subprocess.check_output(
            ("git", "rev-parse", "HEAD"),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or bool(pd.isna(cast(Any, value))):
        return None
    return _decimal(value)


def _percent(value: Decimal) -> Decimal:
    return (value * _HUNDRED).quantize(Decimal("0.0001"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the governed DSI-011C 20-DMA reclaim portfolio challenger."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("alpha_data/warehouse/historical_truth.duckdb"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".alpha/research/dsi011c_20dma_reclaim"),
    )
    args = parser.parse_args()
    run_challenger(database=args.database, output=args.output)


if __name__ == "__main__":
    main()


__all__ = [
    "CHALLENGER_VERSION",
    "ChallengerConfig",
    "ChallengerResult",
    "CompletedTrade",
    "EquityPoint",
    "ExitLeg",
    "PendingEntry",
    "RejectedEntry",
    "engineer_signals",
    "load_research_frame",
    "risk_sized_quantity",
    "run_challenger",
    "simulate_challenger",
]
