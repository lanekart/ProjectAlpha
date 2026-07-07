from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType

from alpha.trading_signals.models import SignalBatch, SignalSide

_ZERO = Decimal("0")


class WalkForwardMode(StrEnum):
    """Supported deterministic walk-forward windowing modes."""

    ROLLING = "rolling"
    EXPANDING = "expanding"


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    """Configuration for deterministic walk-forward validation windows."""

    start: date
    end: date
    train_days: int
    test_days: int
    step_days: int
    mode: WalkForwardMode = WalkForwardMode.ROLLING

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("walk-forward end must be on or after start")
        if self.train_days <= 0:
            raise ValueError("walk-forward train_days must be positive")
        if self.test_days <= 0:
            raise ValueError("walk-forward test_days must be positive")
        if self.step_days <= 0:
            raise ValueError("walk-forward step_days must be positive")


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    """Immutable train/test window for walk-forward validation."""

    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def __post_init__(self) -> None:
        if self.index < 1:
            raise ValueError("walk-forward window index must be positive")
        if self.train_end < self.train_start:
            raise ValueError("train window end must be on or after start")
        if self.test_end < self.test_start:
            raise ValueError("test window end must be on or after start")
        if self.test_start <= self.train_end:
            raise ValueError("test window must start after train window")

    @property
    def train_day_count(self) -> int:
        return (self.train_end - self.train_start).days + 1

    @property
    def test_day_count(self) -> int:
        return (self.test_end - self.test_start).days + 1


@dataclass(frozen=True, slots=True)
class SignalOutcome:
    """Observed forward return for a symbol on a validation date."""

    symbol: str
    observed_for: date
    forward_return: Decimal

    def __post_init__(self) -> None:
        normalized_symbol = self.symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("outcome symbol cannot be empty")

        try:
            normalized_return = Decimal(str(self.forward_return))
        except InvalidOperation as error:
            raise ValueError("outcome forward_return must be decimal") from error

        object.__setattr__(self, "symbol", normalized_symbol)
        object.__setattr__(self, "forward_return", normalized_return)


@dataclass(frozen=True, slots=True)
class WalkForwardFoldResult:
    """Deterministic validation result for one walk-forward fold."""

    window: WalkForwardWindow
    strategy: str
    evaluated_signals: int
    actionable_signals: int
    winning_signals: int
    average_score: Decimal

    def __post_init__(self) -> None:
        normalized_strategy = self.strategy.strip().lower()
        if not normalized_strategy:
            raise ValueError("fold strategy cannot be empty")
        if self.evaluated_signals < 0:
            raise ValueError("evaluated_signals cannot be negative")
        if self.actionable_signals < 0:
            raise ValueError("actionable_signals cannot be negative")
        if self.winning_signals < 0:
            raise ValueError("winning_signals cannot be negative")
        if self.actionable_signals > self.evaluated_signals:
            raise ValueError("actionable_signals cannot exceed evaluated_signals")
        if self.winning_signals > self.actionable_signals:
            raise ValueError("winning_signals cannot exceed actionable_signals")

        object.__setattr__(self, "strategy", normalized_strategy)
        object.__setattr__(
            self,
            "average_score",
            Decimal(str(self.average_score)),
        )

    @property
    def hit_rate(self) -> Decimal:
        if self.actionable_signals == 0:
            return _ZERO
        return Decimal(self.winning_signals) / Decimal(self.actionable_signals)


@dataclass(frozen=True, slots=True)
class WalkForwardValidationReport:
    """Aggregated deterministic walk-forward validation report."""

    strategy: str
    results: tuple[WalkForwardFoldResult, ...]

    def __post_init__(self) -> None:
        normalized_strategy = self.strategy.strip().lower()
        if not normalized_strategy:
            raise ValueError("walk-forward report strategy cannot be empty")

        sorted_results = tuple(
            sorted(
                self.results,
                key=lambda result: result.window.index,
            )
        )
        for result in sorted_results:
            if result.strategy != normalized_strategy:
                raise ValueError("fold result strategy must match report strategy")

        object.__setattr__(self, "strategy", normalized_strategy)
        object.__setattr__(self, "results", sorted_results)

    @property
    def fold_count(self) -> int:
        return len(self.results)

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
    def average_score(self) -> Decimal:
        if not self.results:
            return _ZERO

        total_score = sum(
            (
                result.average_score * Decimal(result.evaluated_signals)
                for result in self.results
            ),
            _ZERO,
        )
        if self.evaluated_signals == 0:
            return _ZERO
        return total_score / Decimal(self.evaluated_signals)


@dataclass(frozen=True, slots=True)
class WalkForwardPlanner:
    """Create deterministic walk-forward train/test windows."""

    def plan(
        self,
        config: WalkForwardConfig,
    ) -> tuple[WalkForwardWindow, ...]:
        windows: list[WalkForwardWindow] = []
        index = 1
        train_start = config.start

        while True:
            train_end = train_start + timedelta(days=config.train_days - 1)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + timedelta(days=config.test_days - 1)

            if test_end > config.end:
                break

            if config.mode is WalkForwardMode.EXPANDING:
                effective_train_start = config.start
            else:
                effective_train_start = train_start

            windows.append(
                WalkForwardWindow(
                    index=index,
                    train_start=effective_train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )
            index += 1
            train_start += timedelta(days=config.step_days)

        return tuple(windows)


@dataclass(frozen=True, slots=True)
class WalkForwardValidator:
    """Evaluate deterministic signal batches against forward outcomes."""

    def validate(
        self,
        *,
        strategy: str,
        windows: Iterable[WalkForwardWindow],
        batches: Iterable[SignalBatch],
        outcomes: Iterable[SignalOutcome],
    ) -> WalkForwardValidationReport:
        normalized_strategy = strategy.strip().lower()
        if not normalized_strategy:
            raise ValueError("walk-forward strategy cannot be empty")

        batches_by_date = _batches_by_date(
            batches=batches,
            strategy=normalized_strategy,
        )
        outcomes_by_key = _outcomes_by_key(outcomes)
        results = tuple(
            self._validate_window(
                strategy=normalized_strategy,
                window=window,
                batches_by_date=batches_by_date,
                outcomes_by_key=outcomes_by_key,
            )
            for window in windows
        )
        return WalkForwardValidationReport(
            strategy=normalized_strategy,
            results=results,
        )

    def _validate_window(
        self,
        *,
        strategy: str,
        window: WalkForwardWindow,
        batches_by_date: Mapping[date, tuple[SignalBatch, ...]],
        outcomes_by_key: Mapping[tuple[date, str], SignalOutcome],
    ) -> WalkForwardFoldResult:
        scores: list[Decimal] = []
        actionable_count = 0
        winning_count = 0
        current = window.test_start

        while current <= window.test_end:
            for batch in batches_by_date.get(current, ()):
                for signal in batch.signals:
                    outcome = outcomes_by_key.get((current, signal.symbol))
                    if outcome is None:
                        continue

                    score = _score_signal(
                        side=signal.side,
                        forward_return=outcome.forward_return,
                    )
                    scores.append(score)
                    if signal.is_actionable:
                        actionable_count += 1
                        if score > _ZERO:
                            winning_count += 1

            current += timedelta(days=1)

        average_score = _ZERO
        if scores:
            average_score = sum(scores, _ZERO) / Decimal(len(scores))

        return WalkForwardFoldResult(
            window=window,
            strategy=strategy,
            evaluated_signals=len(scores),
            actionable_signals=actionable_count,
            winning_signals=winning_count,
            average_score=average_score,
        )


def _batches_by_date(
    *,
    batches: Iterable[SignalBatch],
    strategy: str,
) -> Mapping[date, tuple[SignalBatch, ...]]:
    collected: dict[date, list[SignalBatch]] = {}
    for batch in batches:
        if batch.strategy != strategy:
            continue
        collected.setdefault(batch.generated_for, []).append(batch)

    normalized = {
        generated_for: tuple(items)
        for generated_for, items in sorted(collected.items())
    }
    return MappingProxyType(normalized)


def _outcomes_by_key(
    outcomes: Iterable[SignalOutcome],
) -> Mapping[tuple[date, str], SignalOutcome]:
    collected: dict[tuple[date, str], SignalOutcome] = {}
    for outcome in outcomes:
        key = (outcome.observed_for, outcome.symbol)
        collected[key] = outcome
    return MappingProxyType(dict(sorted(collected.items())))


def _score_signal(
    *,
    side: SignalSide,
    forward_return: Decimal,
) -> Decimal:
    if side is SignalSide.BUY:
        return forward_return
    if side is SignalSide.SELL:
        return -forward_return
    return _ZERO
