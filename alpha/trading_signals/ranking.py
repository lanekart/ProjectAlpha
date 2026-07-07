from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.trading_signals.research import (
    MultiStrategyResearchReport,
    StrategyResearchResult,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_ROBUSTNESS_WEIGHT = Decimal("0.50")
_HIT_RATE_WEIGHT = Decimal("0.30")
_SCORE_WEIGHT = Decimal("0.15")
_COVERAGE_WEIGHT = Decimal("0.05")


@dataclass(frozen=True, slots=True)
class RankedStrategy:
    """Immutable deterministic ranking row for one researched strategy."""

    rank: int
    strategy: str
    robustness_score: Decimal
    hit_rate: Decimal
    average_score: Decimal
    coverage: Decimal
    composite_score: Decimal
    fold_count: int
    evaluated_signals: int
    actionable_signals: int
    winning_signals: int

    def __post_init__(self) -> None:
        normalized_strategy = self.strategy.strip().lower()
        if self.rank <= 0:
            raise ValueError("strategy rank must be positive")
        if not normalized_strategy:
            raise ValueError("ranked strategy name cannot be empty")
        if self.fold_count < 0:
            raise ValueError("fold count cannot be negative")
        if self.evaluated_signals < 0:
            raise ValueError("evaluated signals cannot be negative")
        if self.actionable_signals < 0:
            raise ValueError("actionable signals cannot be negative")
        if self.winning_signals < 0:
            raise ValueError("winning signals cannot be negative")
        if self.winning_signals > self.actionable_signals:
            raise ValueError("winning signals cannot exceed actionable signals")

        object.__setattr__(self, "strategy", normalized_strategy)

    @property
    def is_actionable(self) -> bool:
        return self.actionable_signals > 0


@dataclass(frozen=True, slots=True)
class StrategyRankingReport:
    """Immutable deterministic ranking report for a research run."""

    ranked: tuple[RankedStrategy, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        ranks: set[int] = set()

        for row in self.ranked:
            if row.strategy in seen:
                raise ValueError(f"duplicate ranked strategy: {row.strategy}")
            if row.rank in ranks:
                raise ValueError(f"duplicate strategy rank: {row.rank}")
            seen.add(row.strategy)
            ranks.add(row.rank)

        ordered = tuple(sorted(self.ranked, key=lambda row: row.rank))
        expected_ranks = tuple(range(1, len(ordered) + 1))
        actual_ranks = tuple(row.rank for row in ordered)
        if actual_ranks != expected_ranks:
            raise ValueError("strategy ranks must be contiguous from one")

        object.__setattr__(self, "ranked", ordered)

    @property
    def strategy_count(self) -> int:
        return len(self.ranked)

    @property
    def strategies(self) -> tuple[str, ...]:
        return tuple(row.strategy for row in self.ranked)

    @property
    def best(self) -> RankedStrategy | None:
        if not self.ranked:
            return None
        return self.ranked[0]

    def get(self, strategy: str) -> RankedStrategy:
        normalized_strategy = strategy.strip().lower()
        for row in self.ranked:
            if row.strategy == normalized_strategy:
                return row
        raise KeyError(f"unknown ranked strategy: {strategy}")


@dataclass(frozen=True, slots=True)
class StrategyRankingEngine:
    """Rank strategy research results using deterministic robustness metrics."""

    def rank(
        self,
        report: MultiStrategyResearchReport,
    ) -> StrategyRankingReport:
        rows = tuple(
            self._ranked_strategy(
                rank=index,
                result=result,
            )
            for index, result in enumerate(
                self._ordered_results(report),
                start=1,
            )
        )
        return StrategyRankingReport(ranked=rows)

    def _ordered_results(
        self,
        report: MultiStrategyResearchReport,
    ) -> tuple[StrategyResearchResult, ...]:
        return tuple(
            sorted(
                report.results,
                key=lambda result: (
                    self._composite_score(result),
                    result.robustness_score,
                    result.hit_rate,
                    result.average_score,
                    result.actionable_signals,
                    result.strategy,
                ),
                reverse=True,
            )
        )

    def _ranked_strategy(
        self,
        *,
        rank: int,
        result: StrategyResearchResult,
    ) -> RankedStrategy:
        coverage = self._coverage(result)
        composite_score = self._composite_score(result)
        return RankedStrategy(
            rank=rank,
            strategy=result.strategy,
            robustness_score=result.robustness_score,
            hit_rate=result.hit_rate,
            average_score=result.average_score,
            coverage=coverage,
            composite_score=composite_score,
            fold_count=result.fold_count,
            evaluated_signals=result.evaluated_signals,
            actionable_signals=result.actionable_signals,
            winning_signals=result.winning_signals,
        )

    def _composite_score(self, result: StrategyResearchResult) -> Decimal:
        if result.evaluated_signals == 0:
            return _ZERO

        return (
            (result.robustness_score * _ROBUSTNESS_WEIGHT)
            + (result.hit_rate * _HIT_RATE_WEIGHT)
            + (result.average_score * _SCORE_WEIGHT)
            + (self._coverage(result) * _COVERAGE_WEIGHT)
        )

    def _coverage(self, result: StrategyResearchResult) -> Decimal:
        if result.evaluated_signals == 0:
            return _ZERO

        coverage = Decimal(result.actionable_signals) / Decimal(
            result.evaluated_signals
        )
        return min(coverage, _ONE)
