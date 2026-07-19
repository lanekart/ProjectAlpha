from __future__ import annotations

from decimal import Decimal
from math import erfc, sqrt
from statistics import mean, stdev

from alpha.strategy_discovery.models import MultipleTestingResult


class MultipleTestingControl:
    """Apply transparent Bonferroni correction to mean-return tests."""

    def evaluate(
        self,
        *,
        strategy_version: str,
        returns: tuple[Decimal, ...],
        hypotheses_tested: int,
    ) -> MultipleTestingResult:
        raw = _one_sided_mean_p_value(returns)
        adjusted = (
            min(Decimal("1"), raw * Decimal(max(1, hypotheses_tested)))
            if raw is not None
            else None
        )
        return MultipleTestingResult(
            strategy_version=strategy_version,
            raw_p_value=raw,
            adjusted_p_value=adjusted,
            hypotheses_tested=hypotheses_tested,
            adjustment_method="BONFERRONI_ONE_SIDED_MEAN_RETURN",
            statistically_significant=(
                adjusted is not None and adjusted < Decimal("0.05")
            ),
        )


def _one_sided_mean_p_value(returns: tuple[Decimal, ...]) -> Decimal | None:
    if len(returns) < 2:
        return None
    values = tuple(float(value) for value in returns)
    deviation = stdev(values)
    if deviation == 0:
        return Decimal("0") if mean(values) > 0 else Decimal("1")
    statistic = mean(values) / (deviation / sqrt(len(values)))
    p_value = 0.5 * erfc(statistic / sqrt(2))
    return Decimal(str(p_value)).quantize(Decimal("0.000001"))


__all__ = ["MultipleTestingControl"]
