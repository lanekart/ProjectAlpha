from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from itertools import combinations

from alpha.strategy_regime.models import (
    HoldingPeriod,
    HoldingPeriodPerformance,
    IndicatorCombinationResult,
    MarketRegime,
    RegimePerformanceSummary,
    SampleConfidence,
    StrategyRegimeBacktestResult,
    StrategyRegimeBacktestRun,
    StrategyRegimeRank,
    StrategySignalObservation,
    StrategyTradeOutcome,
    confidence_for_sample,
)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")


DEFAULT_COMBINATIONS: tuple[tuple[str, ...], ...] = (
    ("breakout", "volume-expansion"),
    ("breakout", "relative-strength"),
    ("breakout", "sector-strength"),
    ("pullback-to-20-dma", "volume-dry-up"),
    ("20-dma-reclaim", "relative-strength"),
    ("candle-confirmation", "volume-confirmation"),
    ("sector-strength", "relative-strength", "market-breadth"),
    ("trend-continuation", "low-volatility"),
    ("high-volume-breakout", "bullish-market-regime"),
)


class StrategyRegimeBacktestEngine:
    def run(
        self,
        *,
        observations: tuple[StrategySignalObservation, ...],
        from_date: date,
        to_date: date,
        regimes: tuple[MarketRegime, ...] | None = None,
        strategies: tuple[str, ...] | None = None,
        holding_periods: tuple[HoldingPeriod, ...] | None = None,
        minimum_sample_size: int = 30,
    ) -> StrategyRegimeBacktestRun:
        if minimum_sample_size <= 0:
            raise ValueError("minimum_sample_size must be positive")
        selected_regimes = set(regimes or tuple(MarketRegime))
        selected_holding_periods = holding_periods or tuple(HoldingPeriod)
        filtered = tuple(
            observation
            for observation in observations
            if from_date <= observation.observed_on <= to_date
            and observation.regime in selected_regimes
        )
        strategy_sets = _strategy_sets(filtered, strategies)
        results = tuple(
            self._result(
                strategy_name=_strategy_name(indicators),
                indicators=indicators,
                regime=regime,
                observations=tuple(
                    observation
                    for observation in filtered
                    if observation.regime is regime
                    and set(indicators).issubset(set(observation.indicators))
                ),
                holding_periods=selected_holding_periods,
                minimum_sample_size=minimum_sample_size,
            )
            for regime in sorted(selected_regimes, key=lambda item: item.value)
            for indicators in strategy_sets
        )
        populated = tuple(
            result
            for result in results
            if any(item.total_trades > 0 for item in result.holding_period_results)
        )
        combinations_result = tuple(
            _combination_from_result(result) for result in populated
        )
        summaries = _summaries(combinations_result)
        ranks = _ranks(combinations_result)
        return StrategyRegimeBacktestRun(
            run_id=_run_id(
                from_date=from_date,
                to_date=to_date,
                result_count=len(populated),
            ),
            generated_at=datetime.now(tz=UTC),
            from_date=from_date,
            to_date=to_date,
            results=populated,
            summaries=summaries,
            ranks=ranks,
        )

    def _result(
        self,
        *,
        strategy_name: str,
        indicators: tuple[str, ...],
        regime: MarketRegime,
        observations: tuple[StrategySignalObservation, ...],
        holding_periods: tuple[HoldingPeriod, ...],
        minimum_sample_size: int,
    ) -> StrategyRegimeBacktestResult:
        return StrategyRegimeBacktestResult(
            strategy_name=strategy_name,
            indicators=indicators,
            regime=regime,
            holding_period_results=tuple(
                self._holding_performance(
                    outcomes=tuple(
                        _trade_outcome(
                            observation=observation,
                            strategy_name=strategy_name,
                            holding_period=holding_period,
                        )
                        for observation in observations
                        if holding_period.value in observation.holding_close
                    ),
                    holding_period=holding_period,
                    minimum_sample_size=minimum_sample_size,
                )
                for holding_period in holding_periods
            ),
        )

    def _holding_performance(
        self,
        *,
        outcomes: tuple[StrategyTradeOutcome, ...],
        holding_period: HoldingPeriod,
        minimum_sample_size: int,
    ) -> HoldingPeriodPerformance:
        wins = tuple(outcome for outcome in outcomes if outcome.return_pct > _ZERO)
        losses = tuple(outcome for outcome in outcomes if outcome.return_pct < _ZERO)
        breakeven = tuple(
            outcome for outcome in outcomes if outcome.return_pct == _ZERO
        )
        gains_pct = tuple(outcome.return_pct for outcome in wins)
        losses_pct = tuple(outcome.return_pct for outcome in losses)
        gains_rs = tuple(outcome.pnl_rs for outcome in wins)
        losses_rs = tuple(outcome.pnl_rs for outcome in losses)
        sample_size = len(outcomes)
        win_rate = _rate(len(wins), sample_size)
        loss_rate = _rate(len(losses), sample_size)
        average_gain_pct = _average(gains_pct)
        average_loss_pct = _average(losses_pct)
        average_gain_rs = _average(gains_rs)
        average_loss_rs = _average(losses_rs)
        return HoldingPeriodPerformance(
            holding_period=holding_period,
            total_trades=sample_size,
            winning_trades=len(wins),
            losing_trades=len(losses),
            breakeven_trades=len(breakeven),
            win_rate=win_rate,
            loss_rate=loss_rate,
            average_gain_pct=average_gain_pct,
            average_loss_pct=average_loss_pct,
            average_gain_rs=average_gain_rs,
            average_loss_rs=average_loss_rs,
            expected_value_pct=_expected_value(
                win_rate=win_rate,
                loss_rate=loss_rate,
                average_gain=average_gain_pct,
                average_loss=average_loss_pct,
            ),
            expected_value_rs=_expected_value(
                win_rate=win_rate,
                loss_rate=loss_rate,
                average_gain=average_gain_rs,
                average_loss=average_loss_rs,
            ),
            median_return=_median(tuple(outcome.return_pct for outcome in outcomes)),
            profit_factor=_profit_factor(outcomes),
            max_drawdown=min(
                (outcome.max_drawdown_pct for outcome in outcomes),
                default=None,
            ),
            average_holding_period=_average(
                tuple(Decimal(outcome.holding_days) for outcome in outcomes)
            ),
            median_holding_period=_median(
                tuple(Decimal(outcome.holding_days) for outcome in outcomes)
            ),
            best_trade=max(
                (outcome.return_pct for outcome in outcomes),
                default=None,
            ),
            worst_trade=min(
                (outcome.return_pct for outcome in outcomes),
                default=None,
            ),
            false_positive_rate=_rate(
                len(
                    tuple(
                        outcome for outcome in outcomes if outcome.return_pct <= _ZERO
                    )
                ),
                sample_size,
            ),
            sample_size_confidence=confidence_for_sample(
                sample_size,
                minimum_sample_size,
            ),
        )


def historical_edge_metadata(
    *,
    setup_indicators: tuple[str, ...],
    regime: str,
    run: StrategyRegimeBacktestRun | None,
    minimum_confidence: SampleConfidence = SampleConfidence.MODERATE_EVIDENCE,
) -> dict[str, str]:
    if run is None:
        return {"historical_setup_edge": "Not yet computed"}
    normalized = tuple(
        indicator.strip().lower().replace("_", "-")
        for indicator in setup_indicators
        if indicator.strip()
    )
    if not normalized:
        return {"historical_setup_edge": "Not yet computed"}
    try:
        current_regime = MarketRegime(regime.strip().upper())
    except ValueError:
        return {"historical_setup_edge": "Not yet computed"}
    match = next(
        (
            result.best_holding_period
            for result in run.results
            if result.regime is current_regime
            and set(result.indicators) == set(normalized)
            and result.best_holding_period is not None
        ),
        None,
    )
    if match is None or _confidence_rank(
        match.sample_size_confidence
    ) < _confidence_rank(minimum_confidence):
        return {"historical_setup_edge": "Not yet computed"}
    return {
        "historical_setup_edge": "computed",
        "historical_setup_regime": current_regime.value,
        "historical_setup_trades": str(match.total_trades),
        "historical_setup_win_rate": _text(match.win_rate),
        "historical_setup_ev_pct": _text(match.expected_value_pct),
        "historical_setup_ev_rs": _text(match.expected_value_rs),
        "historical_setup_best_holding_period": match.holding_period.value,
        "historical_setup_evidence_strength": match.sample_size_confidence.value,
    }


def _strategy_sets(
    observations: tuple[StrategySignalObservation, ...],
    strategies: tuple[str, ...] | None,
) -> tuple[tuple[str, ...], ...]:
    if strategies and "all" not in strategies:
        return tuple(
            (strategy.strip().lower().replace("_", "-"),) for strategy in strategies
        )
    individual = sorted(
        {
            indicator
            for observation in observations
            for indicator in observation.indicators
        }
    )
    generated: set[tuple[str, ...]] = {(indicator,) for indicator in individual}
    for observation in observations:
        for size in (2, 3):
            for combo in combinations(sorted(observation.indicators), size):
                generated.add(combo)
    generated.update(DEFAULT_COMBINATIONS)
    return tuple(sorted(generated, key=lambda item: (" + ".join(item), len(item))))


def _trade_outcome(
    *,
    observation: StrategySignalObservation,
    strategy_name: str,
    holding_period: HoldingPeriod,
) -> StrategyTradeOutcome:
    close = observation.holding_close[holding_period.value]
    path_high = observation.path_high.get(holding_period.value, close)
    path_low = observation.path_low.get(holding_period.value, close)
    stop_hit = observation.stop_loss is not None and path_low <= observation.stop_loss
    target_hit = (
        observation.target_price is not None and path_high >= observation.target_price
    )
    if stop_hit and target_hit:
        exit_price = observation.stop_loss or close
        exit_reason = "STOP_FIRST_SAME_CANDLE"
    elif stop_hit:
        exit_price = observation.stop_loss or close
        exit_reason = "STOP_LOSS"
    elif target_hit:
        exit_price = observation.target_price or close
        exit_reason = "TARGET"
    else:
        exit_price = close
        exit_reason = "HOLDING_PERIOD_CLOSE"
    return_pct = _return_pct(observation.entry_open, exit_price)
    return StrategyTradeOutcome(
        symbol=observation.symbol,
        regime=observation.regime,
        strategy_name=strategy_name,
        holding_period=holding_period,
        return_pct=return_pct,
        pnl_rs=(observation.capital * return_pct / _HUNDRED).quantize(
            _TWO,
            rounding=ROUND_HALF_UP,
        ),
        holding_days=holding_period.bars,
        exit_reason=exit_reason,
        target_hit=target_hit,
        stop_hit=stop_hit,
        max_drawdown_pct=_return_pct(observation.entry_open, path_low),
    )


def _combination_from_result(
    result: StrategyRegimeBacktestResult,
) -> IndicatorCombinationResult:
    best = result.best_holding_period
    if best is None:
        return IndicatorCombinationResult(
            strategy_name=result.strategy_name,
            indicators=result.indicators,
            regime=result.regime,
            best_holding_period=HoldingPeriod.NEXT_DAY,
            expected_value_pct=None,
            expected_value_rs=None,
            total_trades=0,
            win_rate=None,
            profit_factor=None,
            sample_size_confidence=SampleConfidence.INSUFFICIENT_SAMPLE,
        )
    return IndicatorCombinationResult(
        strategy_name=result.strategy_name,
        indicators=result.indicators,
        regime=result.regime,
        best_holding_period=best.holding_period,
        expected_value_pct=best.expected_value_pct,
        expected_value_rs=best.expected_value_rs,
        total_trades=best.total_trades,
        win_rate=best.win_rate,
        profit_factor=best.profit_factor,
        sample_size_confidence=best.sample_size_confidence,
    )


def _summaries(
    combinations_result: tuple[IndicatorCombinationResult, ...],
) -> tuple[RegimePerformanceSummary, ...]:
    grouped: dict[MarketRegime, list[IndicatorCombinationResult]] = defaultdict(list)
    for result in combinations_result:
        grouped[result.regime].append(result)
    summaries = []
    for regime, items in sorted(grouped.items(), key=lambda item: item[0].value):
        ranked = sorted(items, key=_rank_key, reverse=True)
        worst = sorted(items, key=_rank_key)
        avoid = tuple(
            item.strategy_name
            for item in worst
            if (item.expected_value_pct or _ZERO) < _ZERO
        )[:5]
        summaries.append(
            RegimePerformanceSummary(
                regime=regime,
                best_strategies=tuple(ranked[:10]),
                worst_strategies=tuple(worst[:10]),
                avoid_strategies=avoid,
            )
        )
    return tuple(summaries)


def _ranks(
    combinations_result: tuple[IndicatorCombinationResult, ...],
) -> tuple[StrategyRegimeRank, ...]:
    ranked = sorted(combinations_result, key=_rank_key, reverse=True)
    return tuple(
        StrategyRegimeRank(
            rank=index,
            strategy_name=result.strategy_name,
            regime=result.regime,
            holding_period=result.best_holding_period,
            expected_value_pct=result.expected_value_pct,
            profit_factor=result.profit_factor,
            sample_size_confidence=result.sample_size_confidence,
        )
        for index, result in enumerate(ranked, start=1)
    )


def _rank_key(
    result: IndicatorCombinationResult,
) -> tuple[Decimal, int, Decimal, Decimal]:
    return (
        result.expected_value_pct or Decimal("-999"),
        _confidence_rank(result.sample_size_confidence),
        result.profit_factor or _ZERO,
        Decimal(result.total_trades),
    )


def _strategy_name(indicators: tuple[str, ...]) -> str:
    return " + ".join(indicators)


def _run_id(*, from_date: date, to_date: date, result_count: int) -> str:
    raw = f"{from_date.isoformat()}|{to_date.isoformat()}|{result_count}"
    return sha256(raw.encode("utf-8")).hexdigest()[:20]


def _return_pct(entry: Decimal, exit_price: Decimal) -> Decimal:
    if entry <= _ZERO:
        return _ZERO
    return ((exit_price - entry) / entry * _HUNDRED).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _FOUR,
        rounding=ROUND_HALF_UP,
    )


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def _median(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    ordered = tuple(sorted(values))
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle].quantize(_TWO, rounding=ROUND_HALF_UP)
    return ((ordered[middle - 1] + ordered[middle]) / Decimal("2")).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def _expected_value(
    *,
    win_rate: Decimal | None,
    loss_rate: Decimal | None,
    average_gain: Decimal | None,
    average_loss: Decimal | None,
) -> Decimal | None:
    if win_rate is None or loss_rate is None:
        return None
    gain = average_gain or _ZERO
    loss = average_loss or _ZERO
    return ((win_rate * gain) - (loss_rate * abs(loss))).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def _profit_factor(outcomes: tuple[StrategyTradeOutcome, ...]) -> Decimal | None:
    gains = sum(
        (outcome.pnl_rs for outcome in outcomes if outcome.pnl_rs > _ZERO),
        _ZERO,
    )
    losses = sum(
        (abs(outcome.pnl_rs) for outcome in outcomes if outcome.pnl_rs < _ZERO),
        _ZERO,
    )
    if losses == _ZERO:
        return None
    return (gains / losses).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _confidence_rank(value: SampleConfidence) -> int:
    return {
        SampleConfidence.INSUFFICIENT_SAMPLE: 0,
        SampleConfidence.WEAK_EVIDENCE: 1,
        SampleConfidence.MODERATE_EVIDENCE: 2,
        SampleConfidence.STRONG_EVIDENCE: 3,
    }[value]


def _text(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


__all__ = [
    "DEFAULT_COMBINATIONS",
    "StrategyRegimeBacktestEngine",
    "historical_edge_metadata",
]
