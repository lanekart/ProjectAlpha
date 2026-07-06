from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


class IndicatorError(Exception):
    """Base indicator exception."""


def _to_decimal(x: float | Decimal | int) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def sma(values: Sequence[Decimal], period: int) -> Decimal:
    if period <= 0:
        raise IndicatorError("period must be positive")

    if len(values) < period:
        raise IndicatorError("not enough data for SMA")

    window = values[-period:]
    return sum(window, Decimal("0")) / Decimal(period)


def ema(values: Sequence[Decimal], period: int) -> Decimal:
    if period <= 0:
        raise IndicatorError("period must be positive")

    if len(values) < period:
        raise IndicatorError("not enough data for EMA")

    k = Decimal("2") / Decimal(period + 1)

    ema_val = values[0]

    for v in values[1:]:
        ema_val = (v * k) + (ema_val * (Decimal("1") - k))

    return ema_val


def returns(values: Sequence[Decimal]) -> Sequence[Decimal]:
    if len(values) < 2:
        return ()

    result = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        curr = values[i]

        if prev == 0:
            result.append(Decimal("0"))
        else:
            result.append((curr - prev) / prev)

    return tuple(result)


def volatility(values: Sequence[Decimal]) -> Decimal:
    if len(values) < 2:
        return Decimal("0")

    r = returns(values)

    if not r:
        return Decimal("0")

    mean = sum(r, Decimal("0")) / Decimal(len(r))

    var = sum((x - mean) ** 2 for x in r) / Decimal(len(r))

    return var.sqrt()
