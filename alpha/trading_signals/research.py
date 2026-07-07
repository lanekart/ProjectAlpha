from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from alpha.trading_signals.models import SignalBatch
from alpha.trading_signals.walk_forward import (
    SignalOutcome,
    WalkForwardValidationReport,
    WalkForwardValidator,
    WalkForwardWindow,
)

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class StrategyResearchResult:
    """Immutable research result for one strategy."""

    strategy: str
    validation: WalkForwardValidationReport

    def __post_init__(self) -> None:
        normalized_strategy = self.strategy.strip().lower()
        if not normalized_strategy:
            raise ValueError("strategy research result strategy cannot be empty")
        if self.validation.strategy != normalized_strategy:
            raise ValueError("validation strategy must match research strategy")

        object.__setattr__(self, "strategy", normalized_strategy)

    @property
    def fold_count(self) -> int:
        return self.validation.fold_count

    @property
    def evaluated_signals(self) -> int:
        return self.validation.evaluated_signals

    @property
    def actionable_signals(self) -> int:
        return self.validation.actionable_signals

    @property
    def winning_signals(self) -> int:
        return self.validation.winning_signals

    @property
    def hit_rate(self) -> Decimal:
        return self.validation.hit_rate

    @property
    def average_score(self) -> Decimal:
        return self.validation.average_score

    @property
    def robustness_score(self) -> Decimal:
        if self.fold_count == 0:
            return _ZERO
        if self.actionable_signals == 0:
            return _ZERO

        return self.hit_rate * self.average_score


@dataclass(frozen=True, slots=True)
class MultiStrategyResearchReport:
    """Deterministic cross-strategy research report."""

    results: tuple[StrategyResearchResult, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        sorted_results = tuple(
            sorted(
                self.results,
                key=lambda result: result.strategy,
            )
        )
        for result in sorted_results:
            if result.strategy in seen:
                raise ValueError(
                    f"duplicate strategy research result: {result.strategy}"
                )
            seen.add(result.strategy)

        object.__setattr__(self, "results", sorted_results)

    @property
    def strategy_count(self) -> int:
        return len(self.results)

    @property
    def strategies(self) -> tuple[str, ...]:
        return tuple(result.strategy for result in self.results)

    @property
    def evaluated_signals(self) -> int:
        return sum(result.evaluated_signals for result in self.results)

    @property
    def actionable_signals(self) -> int:
        return sum(result.actionable_signals for result in self.results)

    @property
    def winning_signals(self) -> int:
        return sum(result.winning_signals for result in self.results)

    @property
    def hit_rate(self) -> Decimal:
        if self.actionable_signals == 0:
            return _ZERO
        return Decimal(self.winning_signals) / Decimal(self.actionable_signals)

    @property
    def ranked_results(self) -> tuple[StrategyResearchResult, ...]:
        return tuple(
            sorted(
                self.results,
                key=lambda result: (
                    result.robustness_score,
                    result.hit_rate,
                    result.average_score,
                    result.actionable_signals,
                    result.strategy,
                ),
                reverse=True,
            )
        )

    @property
    def best_result(self) -> StrategyResearchResult | None:
        ranked = self.ranked_results
        if not ranked:
            return None
        return ranked[0]

    def get(self, strategy: str) -> StrategyResearchResult:
        normalized_strategy = strategy.strip().lower()
        for result in self.results:
            if result.strategy == normalized_strategy:
                return result
        raise KeyError(f"unknown strategy research result: {strategy}")


@dataclass(frozen=True, slots=True)
class MultiStrategyResearchEngine:
    """Run deterministic walk-forward validation across many strategies."""

    validator: WalkForwardValidator = WalkForwardValidator()

    def run(
        self,
        *,
        strategies: Iterable[str],
        windows: Iterable[WalkForwardWindow],
        batches_by_strategy: Mapping[str, Iterable[SignalBatch]],
        outcomes: Iterable[SignalOutcome],
    ) -> MultiStrategyResearchReport:
        normalized_strategies = _normalize_strategies(strategies)
        reusable_windows = tuple(windows)
        reusable_outcomes = tuple(outcomes)
        normalized_batches = _normalize_batches_by_strategy(batches_by_strategy)

        results = tuple(
            self._run_strategy(
                strategy=strategy,
                windows=reusable_windows,
                batches=normalized_batches.get(strategy, ()),
                outcomes=reusable_outcomes,
            )
            for strategy in normalized_strategies
        )
        return MultiStrategyResearchReport(results=results)

    def _run_strategy(
        self,
        *,
        strategy: str,
        windows: tuple[WalkForwardWindow, ...],
        batches: tuple[SignalBatch, ...],
        outcomes: tuple[SignalOutcome, ...],
    ) -> StrategyResearchResult:
        validation = self.validator.validate(
            strategy=strategy,
            windows=windows,
            batches=batches,
            outcomes=outcomes,
        )
        return StrategyResearchResult(
            strategy=strategy,
            validation=validation,
        )


def _normalize_strategies(strategies: Iterable[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for strategy in strategies:
        name = strategy.strip().lower()
        if not name:
            raise ValueError("research strategy cannot be empty")
        normalized.add(name)

    return tuple(sorted(normalized))


def _normalize_batches_by_strategy(
    batches_by_strategy: Mapping[str, Iterable[SignalBatch]],
) -> Mapping[str, tuple[SignalBatch, ...]]:
    normalized: dict[str, tuple[SignalBatch, ...]] = {}
    for strategy, batches in batches_by_strategy.items():
        name = strategy.strip().lower()
        if not name:
            raise ValueError("research batch strategy cannot be empty")

        batch_tuple = tuple(batches)
        for batch in batch_tuple:
            if batch.strategy != name:
                raise ValueError("batch strategy must match mapping key")
        normalized[name] = batch_tuple

    return MappingProxyType(dict(sorted(normalized.items())))
