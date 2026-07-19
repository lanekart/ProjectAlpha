from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from alpha.continuous_learning.models import (
    LearningConfidence,
    LearningOutcomeStatus,
    LearningThresholds,
    OutcomeObservation,
    StrategyHealth,
    StrategyHealthClassification,
)


class StrategyHealthMonitor:
    """Measure evidence health by recorded setup without changing strategy state."""

    def __init__(self, thresholds: LearningThresholds | None = None) -> None:
        self.thresholds = thresholds or LearningThresholds()

    def assess(
        self, observations: tuple[OutcomeObservation, ...]
    ) -> tuple[StrategyHealth, ...]:
        grouped: dict[str, list[OutcomeObservation]] = defaultdict(list)
        for item in observations:
            grouped[item.setup_type or "UNCLASSIFIED"].append(item)
        return tuple(
            self._group(key, tuple(sorted(rows, key=lambda item: item.observed_at)))
            for key, rows in sorted(grouped.items())
        )

    def _group(
        self,
        key: str,
        rows: tuple[OutcomeObservation, ...],
    ) -> StrategyHealth:
        completed = tuple(
            item
            for item in rows
            if item.status is LearningOutcomeStatus.EXITED
            and item.realised_return_pct is not None
        )
        returns = tuple(
            item.realised_return_pct
            for item in completed
            if item.realised_return_pct is not None
        )
        winners = tuple(value for value in returns if value > Decimal("0"))
        win_rate = _percent(len(winners), len(returns))
        expectancy = _average(returns)
        drawdown = _drawdown(returns)
        stability = _stability(returns)
        frequency = _frequency(rows)
        confidence = _confidence(len(completed), self.thresholds)
        score = _health_score(win_rate, expectancy, drawdown, stability)
        classification = _classification(
            completed=len(completed),
            expectancy=expectancy,
            win_rate=win_rate,
            stability=stability,
            thresholds=self.thresholds,
        )
        evidence = (
            f"completed outcomes={len(completed)} of {len(rows)} recommendations",
            f"win rate={_text(win_rate)} percent",
            f"expectancy={_text(expectancy)} percent",
            f"maximum outcome-sequence drawdown={_text(drawdown)} percent",
            "recall unavailable because the ledger does not contain all market "
            "opportunities",
            "classification is advisory and cannot retire a production strategy",
        )
        return StrategyHealth(
            strategy_key=key,
            sample_count=len(rows),
            completed_count=len(completed),
            win_rate_pct=win_rate,
            expectancy_pct=expectancy,
            maximum_drawdown_pct=drawdown,
            trade_frequency_per_month=frequency,
            precision_pct=win_rate,
            recall_pct=None,
            stability_score=stability,
            confidence=confidence,
            health_score=score,
            classification=classification,
            evidence=evidence,
        )


def _classification(
    *,
    completed: int,
    expectancy: Decimal | None,
    win_rate: Decimal | None,
    stability: Decimal | None,
    thresholds: LearningThresholds,
) -> StrategyHealthClassification:
    if completed < thresholds.minimum_health_sample:
        return StrategyHealthClassification.RESEARCH_REQUIRED
    if (
        completed >= thresholds.retirement_evidence_sample
        and expectancy is not None
        and expectancy < Decimal("-2")
        and stability is not None
        and stability < Decimal("25")
    ):
        return StrategyHealthClassification.RETIRE
    if expectancy is not None and expectancy < Decimal("0"):
        return StrategyHealthClassification.DEGRADING
    if (
        completed >= thresholds.strong_health_sample
        and expectancy is not None
        and expectancy > Decimal("0")
        and win_rate is not None
        and win_rate >= Decimal("50")
        and stability is not None
        and stability >= Decimal("60")
    ):
        return StrategyHealthClassification.HEALTHY
    return StrategyHealthClassification.WATCH


def _confidence(count: int, thresholds: LearningThresholds) -> LearningConfidence:
    if count < thresholds.minimum_health_sample:
        return LearningConfidence.INSUFFICIENT
    if count < thresholds.strong_health_sample:
        return LearningConfidence.LOW
    if count < thresholds.retirement_evidence_sample:
        return LearningConfidence.MEDIUM
    return LearningConfidence.HIGH


def _health_score(
    win_rate: Decimal | None,
    expectancy: Decimal | None,
    drawdown: Decimal | None,
    stability: Decimal | None,
) -> Decimal | None:
    if None in {win_rate, expectancy, drawdown, stability}:
        return None
    assert win_rate is not None
    assert expectancy is not None
    assert drawdown is not None
    assert stability is not None
    expectancy_score = min(Decimal("100"), max(Decimal("0"), (expectancy + 10) * 5))
    drawdown_score = max(Decimal("0"), Decimal("100") - drawdown * 4)
    return _q(
        win_rate * Decimal("0.35")
        + expectancy_score * Decimal("0.35")
        + stability * Decimal("0.20")
        + drawdown_score * Decimal("0.10")
    )


def _stability(returns: tuple[Decimal, ...]) -> Decimal | None:
    if len(returns) < 4:
        return None
    midpoint = len(returns) // 2
    earlier = _average(returns[:midpoint])
    recent = _average(returns[midpoint:])
    if earlier is None or recent is None:
        return None
    return _q(max(Decimal("0"), Decimal("100") - abs(recent - earlier) * 10))


def _drawdown(returns: tuple[Decimal, ...]) -> Decimal | None:
    if not returns:
        return None
    equity = Decimal("100")
    peak = equity
    maximum = Decimal("0")
    for value in returns:
        equity *= Decimal("1") + value / Decimal("100")
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak * Decimal("100"))
    return _q(maximum)


def _frequency(rows: tuple[OutcomeObservation, ...]) -> Decimal | None:
    if not rows:
        return None
    days = max(1, (rows[-1].generated_at.date() - rows[0].generated_at.date()).days)
    return _q(Decimal(len(rows)) / Decimal(days) * Decimal("30.4375"))


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    return None if not values else _q(sum(values, Decimal("0")) / Decimal(len(values)))


def _percent(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return _q(Decimal(numerator) / Decimal(denominator) * Decimal("100"))


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _text(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


__all__ = ["StrategyHealthMonitor"]
