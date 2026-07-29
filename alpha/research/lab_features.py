"""Point-in-time feature and candle evaluation for research specifications."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any, cast

import numpy as np
import pandas as pd

from alpha.research.lab_models import (
    ComparisonOperator,
    Condition,
    ConditionGroup,
    LogicOperator,
    ResearchExperimentSpec,
    RuleKind,
    StrategyMode,
)

_IDENTITY = "security_id"


class ResearchFeatureEngine:
    """Evaluate registered daily features without using future observations."""

    def build(
        self,
        frame: pd.DataFrame,
        spec: ResearchExperimentSpec,
    ) -> pd.DataFrame:
        required = {
            "trading_date",
            _IDENTITY,
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
        }
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"research frame missing columns: {sorted(missing)}")
        result = frame.copy()
        result["trading_date"] = pd.to_datetime(result["trading_date"])
        result = result.sort_values([_IDENTITY, "trading_date"], kind="stable")
        result = self._add_execution_features(result, spec)
        for condition in _conditions(spec.entry_conditions):
            result = self._add_condition(result, condition)
        result["entry_condition"] = _evaluate_group(result, spec.entry_conditions)
        signal = result["entry_condition"].fillna(False)
        if spec.strategy_mode is not StrategyMode.PURE_TECHNICAL:
            if "final_signal" not in result:
                raise ValueError(
                    "Alpha-signal strategy requires frozen final_signal records"
                )
            signal &= result["final_signal"].isin(spec.base_signal_source)
        result["research_signal"] = signal.astype(bool)
        return result.sort_values(["trading_date", _IDENTITY], kind="stable")

    def _add_execution_features(
        self,
        frame: pd.DataFrame,
        spec: ResearchExperimentSpec,
    ) -> pd.DataFrame:
        result = frame
        atr_periods = {
            rule.atr_period or 14
            for rule in spec.stop_policy.rules
            if rule.rule_id == "ATR"
        }
        atr_periods.update(
            14 for rule in spec.target_policy.rules if rule.rule_id == "ATR_MULTIPLE"
        )
        if atr_periods:
            if len(atr_periods) != 1:
                raise ValueError("execution rules require one governed ATR period")
            period = next(iter(atr_periods))
            result["atr"] = _by_identity(
                result,
                lambda values: _atr(values, period),
            )
        if any(
            rule.rule_id in {"SWING_LOW", "STOP-STRUCTURAL-10D"}
            for rule in spec.stop_policy.rules
        ):
            result["swing_low"] = result.groupby(
                _IDENTITY,
                sort=False,
            )["low"].transform(lambda values: values.rolling(10, min_periods=10).min())
        return result

    def _add_condition(
        self,
        frame: pd.DataFrame,
        condition: Condition,
    ) -> pd.DataFrame:
        result = frame
        name = condition.name
        column = _column_name(condition)
        group = result.groupby(_IDENTITY, sort=False, group_keys=False)
        if condition.kind is RuleKind.CANDLE:
            result[column] = _candle(result, name)
            return result
        period = condition.period or 14
        if name == "SMA":
            result[column] = group["close"].transform(
                lambda values: values.rolling(period, min_periods=period).mean()
            )
        elif name == "EMA":
            result[column] = group["close"].transform(
                lambda values: values.ewm(
                    span=period, adjust=False, min_periods=period
                ).mean()
            )
        elif name == "RSI":
            result[column] = group["close"].transform(
                lambda values: _rsi(values, period)
            )
        elif name == "ATR":
            result[column] = _by_identity(result, lambda values: _atr(values, period))
        elif name == "VOLUME_RATIO":
            average = group["volume"].transform(
                lambda values: values.rolling(period, min_periods=period).mean()
            )
            result[column] = result["volume"] / average.replace(0, np.nan)
        elif name == "ADX":
            result[column] = _by_identity(result, lambda values: _adx(values, period))
        else:
            raise ValueError(f"indicator is registered but not executable: {name}")
        return result


def condition_evidence(
    row: pd.Series,
    group: ConditionGroup,
) -> dict[str, object]:
    return {
        condition.condition_id: _plain(row.get(_column_name(condition)))
        for condition in _conditions(group)
    }


def _evaluate_group(frame: pd.DataFrame, group: ConditionGroup) -> pd.Series:
    if group.empty:
        return pd.Series(True, index=frame.index, dtype=bool)
    children = [
        _evaluate_condition(frame, condition) for condition in group.conditions
    ] + [_evaluate_group(frame, child) for child in group.groups]
    matrix = pd.concat(children, axis=1).fillna(False)
    if group.operator is LogicOperator.ALL:
        return matrix.all(axis=1)
    if group.operator is LogicOperator.ANY:
        return matrix.any(axis=1)
    if group.operator is LogicOperator.NOT:
        return ~matrix.iloc[:, 0]
    required = group.required_count or 1
    return matrix.sum(axis=1) >= required


def _evaluate_condition(
    frame: pd.DataFrame,
    condition: Condition,
) -> pd.Series:
    column = _column_name(condition)
    values = frame[column]
    if condition.kind is RuleKind.CANDLE:
        return values.fillna(False).astype(bool)
    if condition.name == "SMA" and condition.reference == "CLOSE":
        left = frame["close"]
        comparison_target: object = values
    else:
        left = values
        comparison_target = (
            float(condition.value) if condition.value is not None else 0.0
        )
    operator = condition.operator
    if operator in {ComparisonOperator.ABOVE, ComparisonOperator.AT_LEAST}:
        return left >= comparison_target
    if operator in {ComparisonOperator.BELOW, ComparisonOperator.AT_MOST}:
        return left <= comparison_target
    if operator is ComparisonOperator.CROSSES_ABOVE:
        prior = left.groupby(frame[_IDENTITY], sort=False).shift(1)
        return (left > comparison_target) & (prior <= comparison_target)
    if operator is ComparisonOperator.CROSSES_BELOW:
        prior = left.groupby(frame[_IDENTITY], sort=False).shift(1)
        return (left < comparison_target) & (prior >= comparison_target)
    return left.fillna(False).astype(bool)


def _conditions(group: ConditionGroup) -> Iterable[Condition]:
    yield from group.conditions
    for child in group.groups:
        yield from _conditions(child)


def _column_name(condition: Condition) -> str:
    return f"feature__{condition.condition_id.lower()}"


def _rsi(values: pd.Series, period: int) -> pd.Series:
    delta = values.diff()
    gain = (
        delta.clip(lower=0)
        .ewm(alpha=1 / period, adjust=False, min_periods=period)
        .mean()
    )
    loss = (
        -delta.clip(upper=0)
        .ewm(alpha=1 / period, adjust=False, min_periods=period)
        .mean()
    )
    strength = gain / loss.replace(0, np.nan)
    result = 100 - 100 / (1 + strength)
    return result.where(loss.ne(0), 100.0)


def _true_range(values: pd.DataFrame) -> pd.Series:
    prior = values["close"].shift(1)
    return pd.concat(
        (
            values["high"] - values["low"],
            (values["high"] - prior).abs(),
            (values["low"] - prior).abs(),
        ),
        axis=1,
    ).max(axis=1)


def _atr(values: pd.DataFrame, period: int) -> pd.Series:
    return (
        _true_range(values)
        .ewm(alpha=1 / period, adjust=False, min_periods=period)
        .mean()
    )


def _adx(values: pd.DataFrame, period: int) -> pd.Series:
    high_change = values["high"].diff()
    low_change = -values["low"].diff()
    plus_dm = high_change.where((high_change > low_change) & (high_change > 0), 0.0)
    minus_dm = low_change.where((low_change > high_change) & (low_change > 0), 0.0)
    atr = _atr(values, period).replace(0, np.nan)
    plus_di = (
        100
        * plus_dm.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()
        / atr
    )
    minus_di = (
        100
        * minus_dm.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()
        / atr
    )
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


def _candle(frame: pd.DataFrame, name: str) -> pd.Series:
    open_price = frame["open"]
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    span = (high - low).replace(0, np.nan)
    body = (close - open_price).abs()
    prior_open = frame.groupby(_IDENTITY, sort=False)["open"].shift(1)
    prior_close = frame.groupby(_IDENTITY, sort=False)["close"].shift(1)
    prior_high = frame.groupby(_IDENTITY, sort=False)["high"].shift(1)
    prior_low = frame.groupby(_IDENTITY, sort=False)["low"].shift(1)
    if name == "BULLISH_CANDLE":
        return close > open_price
    if name == "BEARISH_CANDLE":
        return close < open_price
    if name == "DOJI":
        return body <= span * 0.1
    if name == "HAMMER":
        lower_wick = open_price.where(open_price < close, close) - low
        upper_wick = high - open_price.where(open_price > close, close)
        return (lower_wick >= body * 2) & (upper_wick <= body)
    if name == "BULLISH_ENGULFING":
        return (
            (prior_close < prior_open)
            & (close > open_price)
            & (open_price <= prior_close)
            & (close >= prior_open)
        )
    if name == "BEARISH_ENGULFING":
        return (
            (prior_close > prior_open)
            & (close < open_price)
            & (open_price >= prior_close)
            & (close <= prior_open)
        )
    if name == "INSIDE_BAR":
        return (high < prior_high) & (low > prior_low)
    if name == "OUTSIDE_BAR":
        return (high > prior_high) & (low < prior_low)
    if name == "INSIDE_BAR_BREAKOUT":
        prior_inside = (prior_high < prior_high.shift(1)) & (
            prior_low > prior_low.shift(1)
        )
        return prior_inside & (close > prior_high)
    if name == "CLOSE_TOP_20_PERCENT":
        return (close - low) / span >= 0.8
    if name == "MARUBOZU":
        return body / span >= 0.9
    if name == "SPINNING_TOP":
        return body / span <= 0.3
    if name == "LONG_UPPER_WICK":
        return (high - open_price.where(open_price > close, close)) >= body * 2
    if name == "LONG_LOWER_WICK":
        return (open_price.where(open_price < close, close) - low) >= body * 2
    raise ValueError(f"candle pattern is registered but not executable: {name}")


def _plain(value: object) -> object:
    if value is None or bool(pd.isna(cast(Any, value))):
        return None
    if isinstance(value, (np.floating, float)):
        return str(Decimal(str(float(value))).quantize(Decimal("0.000001")))
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _by_identity(
    frame: pd.DataFrame,
    calculation: Any,
) -> pd.Series:
    result = pd.Series(index=frame.index, dtype=float)
    for _, values in frame.groupby(_IDENTITY, sort=False):
        computed = cast(pd.Series, calculation(values))
        result.loc[values.index] = computed.to_numpy()
    return result


__all__ = ["ResearchFeatureEngine", "condition_evidence"]
