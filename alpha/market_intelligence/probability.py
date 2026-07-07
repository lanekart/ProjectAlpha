from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_FOUR_PLACES = Decimal("0.0001")
_TWO_PLACES = Decimal("0.01")


class HistoricalOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    OPEN = "OPEN"


@dataclass(frozen=True, slots=True)
class MarketFeatureSnapshot:
    """Immutable normalized market-state features for similarity matching."""

    symbol: str
    observed_on: date
    features: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        normalized_symbol = self.symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol cannot be empty")
        if len(self.features) == 0:
            raise ValueError("features cannot be empty")

        normalized_features: dict[str, Decimal] = {}
        for name, value in self.features.items():
            normalized_name = name.strip().lower()
            if not normalized_name:
                raise ValueError("feature name cannot be empty")
            normalized_features[normalized_name] = Decimal(str(value))

        object.__setattr__(self, "symbol", normalized_symbol)
        object.__setattr__(
            self,
            "features",
            MappingProxyType(dict(sorted(normalized_features.items()))),
        )

    def get(self, name: str) -> Decimal:
        normalized_name = name.strip().lower()
        if not normalized_name:
            raise ValueError("feature name cannot be empty")
        return self.features.get(normalized_name, _ZERO)


@dataclass(frozen=True, slots=True)
class RecommendationOutcome:
    """Historical recommendation and realized outcome for empirical learning."""

    snapshot: MarketFeatureSnapshot
    action: str
    outcome: HistoricalOutcome
    realized_return: Decimal
    maximum_drawdown: Decimal
    holding_period_days: int

    def __post_init__(self) -> None:
        normalized_action = self.action.strip().upper()
        if not normalized_action:
            raise ValueError("action cannot be empty")
        if self.maximum_drawdown < _ZERO:
            raise ValueError("maximum_drawdown cannot be negative")
        if self.holding_period_days < 0:
            raise ValueError("holding_period_days cannot be negative")

        object.__setattr__(self, "action", normalized_action)
        object.__setattr__(
            self,
            "realized_return",
            Decimal(str(self.realized_return)),
        )
        object.__setattr__(
            self,
            "maximum_drawdown",
            Decimal(str(self.maximum_drawdown)),
        )


@dataclass(frozen=True, slots=True)
class HistoricalMatch:
    """A historical observation similar to the current market state."""

    outcome: RecommendationOutcome
    similarity: Decimal
    distance: Decimal

    def __post_init__(self) -> None:
        similarity = Decimal(str(self.similarity))
        distance = Decimal(str(self.distance))
        if similarity < _ZERO or similarity > _ONE:
            raise ValueError("similarity must be between 0 and 1")
        if distance < _ZERO:
            raise ValueError("distance cannot be negative")

        object.__setattr__(self, "similarity", similarity)
        object.__setattr__(self, "distance", distance)


@dataclass(frozen=True, slots=True)
class ProbabilityEstimate:
    """Empirical probability estimate derived from historical matches."""

    symbol: str
    action: str
    generated_on: date
    match_count: int
    success_probability: Decimal
    failure_probability: Decimal
    expected_return: Decimal
    expected_drawdown: Decimal
    expected_holding_period_days: Decimal
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        normalized_symbol = self.symbol.strip().upper()
        normalized_action = self.action.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol cannot be empty")
        if not normalized_action:
            raise ValueError("action cannot be empty")
        if self.match_count < 0:
            raise ValueError("match_count cannot be negative")

        success_probability = _validate_probability(
            self.success_probability,
            "success_probability",
        )
        failure_probability = _validate_probability(
            self.failure_probability,
            "failure_probability",
        )
        if success_probability + failure_probability > _ONE:
            raise ValueError(
                "success_probability and failure_probability cannot exceed 1"
            )

        object.__setattr__(self, "symbol", normalized_symbol)
        object.__setattr__(self, "action", normalized_action)
        object.__setattr__(
            self,
            "success_probability",
            _quantize(success_probability),
        )
        object.__setattr__(
            self,
            "failure_probability",
            _quantize(failure_probability),
        )
        object.__setattr__(
            self,
            "expected_return",
            _quantize(Decimal(str(self.expected_return))),
        )
        object.__setattr__(
            self,
            "expected_drawdown",
            _quantize(Decimal(str(self.expected_drawdown))),
        )
        object.__setattr__(
            self,
            "expected_holding_period_days",
            _quantize(Decimal(str(self.expected_holding_period_days))),
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(item.strip() for item in self.evidence if item.strip()),
        )

    @property
    def is_actionable(self) -> bool:
        return self.match_count > 0 and self.success_probability > Decimal("0.5")


class HistoricalSimilarityEngine:
    """Find historical market states similar to the current state."""

    def match(
        self,
        *,
        current: MarketFeatureSnapshot,
        history: Iterable[RecommendationOutcome],
        action: str,
        limit: int = 20,
    ) -> tuple[HistoricalMatch, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")

        normalized_action = action.strip().upper()
        if not normalized_action:
            raise ValueError("action cannot be empty")

        matches: list[HistoricalMatch] = []
        for outcome in history:
            if outcome.action != normalized_action:
                continue
            distance = self._distance(
                current.features,
                outcome.snapshot.features,
            )
            similarity = _ONE / (_ONE + distance)
            matches.append(
                HistoricalMatch(
                    outcome=outcome,
                    similarity=_quantize(similarity),
                    distance=_quantize(distance),
                )
            )

        return tuple(
            sorted(
                matches,
                key=lambda match: (
                    -match.similarity,
                    match.outcome.snapshot.observed_on,
                    match.outcome.snapshot.symbol,
                ),
            )[:limit]
        )

    def _distance(
        self,
        current: Mapping[str, Decimal],
        historical: Mapping[str, Decimal],
    ) -> Decimal:
        feature_names = tuple(sorted(set(current).union(historical)))
        if len(feature_names) == 0:
            return _ZERO

        total = _ZERO
        for name in feature_names:
            total += abs(current.get(name, _ZERO) - historical.get(name, _ZERO))

        return total / Decimal(len(feature_names))


class EmpiricalProbabilityEngine:
    """Estimate trade probabilities from similar historical outcomes."""

    def estimate(
        self,
        *,
        current: MarketFeatureSnapshot,
        action: str,
        matches: Iterable[HistoricalMatch],
    ) -> ProbabilityEstimate:
        normalized_action = action.strip().upper()
        if not normalized_action:
            raise ValueError("action cannot be empty")

        usable_matches = tuple(
            match
            for match in matches
            if match.outcome.outcome is not HistoricalOutcome.OPEN
        )
        if len(usable_matches) == 0:
            return ProbabilityEstimate(
                symbol=current.symbol,
                action=normalized_action,
                generated_on=current.observed_on,
                match_count=0,
                success_probability=_ZERO,
                failure_probability=_ZERO,
                expected_return=_ZERO,
                expected_drawdown=_ZERO,
                expected_holding_period_days=_ZERO,
                evidence=("No closed historical matches were available.",),
            )

        total_weight = sum(
            (match.similarity for match in usable_matches),
            _ZERO,
        )
        if total_weight <= _ZERO:
            total_weight = Decimal(len(usable_matches))

        success_weight = sum(
            (
                match.similarity
                for match in usable_matches
                if match.outcome.outcome is HistoricalOutcome.SUCCESS
            ),
            _ZERO,
        )
        failure_weight = sum(
            (
                match.similarity
                for match in usable_matches
                if match.outcome.outcome is HistoricalOutcome.FAILURE
            ),
            _ZERO,
        )

        expected_return = self._weighted_average(
            (
                (
                    match.outcome.realized_return,
                    match.similarity,
                )
                for match in usable_matches
            ),
            total_weight,
        )
        expected_drawdown = self._weighted_average(
            (
                (
                    match.outcome.maximum_drawdown,
                    match.similarity,
                )
                for match in usable_matches
            ),
            total_weight,
        )
        expected_holding_period = self._weighted_average(
            (
                (
                    Decimal(match.outcome.holding_period_days),
                    match.similarity,
                )
                for match in usable_matches
            ),
            total_weight,
        )

        success_probability = success_weight / total_weight
        failure_probability = failure_weight / total_weight

        return ProbabilityEstimate(
            symbol=current.symbol,
            action=normalized_action,
            generated_on=current.observed_on,
            match_count=len(usable_matches),
            success_probability=success_probability,
            failure_probability=failure_probability,
            expected_return=expected_return,
            expected_drawdown=expected_drawdown,
            expected_holding_period_days=expected_holding_period,
            evidence=self._evidence(
                match_count=len(usable_matches),
                success_probability=success_probability,
                expected_return=expected_return,
                expected_drawdown=expected_drawdown,
            ),
        )

    def _weighted_average(
        self,
        values: Iterable[tuple[Decimal, Decimal]],
        total_weight: Decimal,
    ) -> Decimal:
        if total_weight <= _ZERO:
            return _ZERO

        numerator = sum(
            (value * weight for value, weight in values),
            _ZERO,
        )
        return numerator / total_weight

    def _evidence(
        self,
        *,
        match_count: int,
        success_probability: Decimal,
        expected_return: Decimal,
        expected_drawdown: Decimal,
    ) -> tuple[str, ...]:
        return (
            f"Based on {match_count} closed historical matches.",
            (f"Weighted success probability is {_as_percent(success_probability)}."),
            f"Weighted expected return is {_as_percent(expected_return)}.",
            f"Weighted expected drawdown is {_as_percent(expected_drawdown)}.",
        )


def _validate_probability(value: Decimal, field_name: str) -> Decimal:
    probability = Decimal(str(value))
    if probability < _ZERO or probability > _ONE:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return probability


def _quantize(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(
        _FOUR_PLACES,
        rounding=ROUND_HALF_UP,
    )


def _as_percent(value: Decimal) -> str:
    percentage = (Decimal(str(value)) * _HUNDRED).quantize(
        _TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )
    return f"{percentage}%"


__all__ = [
    "EmpiricalProbabilityEngine",
    "HistoricalMatch",
    "HistoricalOutcome",
    "HistoricalSimilarityEngine",
    "MarketFeatureSnapshot",
    "ProbabilityEstimate",
    "RecommendationOutcome",
]
