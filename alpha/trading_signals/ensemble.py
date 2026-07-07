from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from alpha.trading_signals.models import SignalBatch, SignalSide, TradingSignal
from alpha.trading_signals.ranking import RankedStrategy, StrategyRankingReport

_ZERO = Decimal("0")
_ONE = Decimal("1")
_DEFAULT_WEIGHT = Decimal("1")
_AGREEMENT_WEIGHT = Decimal("0.35")
_STRATEGY_QUALITY_WEIGHT = Decimal("0.35")
_SIGNAL_CONFIDENCE_WEIGHT = Decimal("0.20")
_COVERAGE_WEIGHT = Decimal("0.10")


@dataclass(frozen=True, slots=True)
class TradeRecommendation:
    """Explainable deterministic recommendation for one symbol."""

    symbol: str
    action: SignalSide
    confidence: Decimal
    score: Decimal
    supporting_strategies: tuple[str, ...]
    opposing_strategies: tuple[str, ...]
    neutral_strategies: tuple[str, ...]
    reasons: tuple[str, ...]
    agreement_score: Decimal = _ZERO
    strategy_quality_score: Decimal = _ZERO
    signal_confidence_score: Decimal = _ZERO
    coverage_score: Decimal = _ZERO
    recommendation_score: Decimal = _ZERO

    def __post_init__(self) -> None:
        normalized_symbol = self.symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("recommendation symbol cannot be empty")

        normalized_confidence = _bounded_decimal(
            value=self.confidence,
            label="recommendation confidence",
        )
        normalized_score = Decimal(str(self.score))
        normalized_agreement = _bounded_decimal(
            value=self.agreement_score,
            label="recommendation agreement score",
        )
        normalized_strategy_quality = _bounded_decimal(
            value=self.strategy_quality_score,
            label="recommendation strategy quality score",
        )
        normalized_signal_confidence = _bounded_decimal(
            value=self.signal_confidence_score,
            label="recommendation signal confidence score",
        )
        normalized_coverage = _bounded_decimal(
            value=self.coverage_score,
            label="recommendation coverage score",
        )
        normalized_recommendation_score = _bounded_decimal(
            value=self.recommendation_score,
            label="recommendation score",
        )

        normalized_supporting = _normalize_names(self.supporting_strategies)
        normalized_opposing = _normalize_names(self.opposing_strategies)
        normalized_neutral = _normalize_names(self.neutral_strategies)
        normalized_reasons = tuple(reason.strip() for reason in self.reasons)

        if any(not reason for reason in normalized_reasons):
            raise ValueError("recommendation reasons cannot contain empty values")

        object.__setattr__(self, "symbol", normalized_symbol)
        object.__setattr__(self, "confidence", normalized_confidence)
        object.__setattr__(self, "score", normalized_score)
        object.__setattr__(self, "agreement_score", normalized_agreement)
        object.__setattr__(
            self,
            "strategy_quality_score",
            normalized_strategy_quality,
        )
        object.__setattr__(
            self,
            "signal_confidence_score",
            normalized_signal_confidence,
        )
        object.__setattr__(self, "coverage_score", normalized_coverage)
        object.__setattr__(
            self,
            "recommendation_score",
            normalized_recommendation_score,
        )
        object.__setattr__(self, "supporting_strategies", normalized_supporting)
        object.__setattr__(self, "opposing_strategies", normalized_opposing)
        object.__setattr__(self, "neutral_strategies", normalized_neutral)
        object.__setattr__(self, "reasons", normalized_reasons)

    @property
    def is_actionable(self) -> bool:
        return self.action in {SignalSide.BUY, SignalSide.SELL}


@dataclass(frozen=True, slots=True)
class EnsembleDecisionReport:
    """Immutable deterministic ensemble recommendation report."""

    generated_for: date
    recommendations: tuple[TradeRecommendation, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        sorted_recommendations = tuple(
            sorted(
                self.recommendations,
                key=lambda recommendation: (
                    recommendation.action.value,
                    -recommendation.recommendation_score,
                    -recommendation.confidence,
                    recommendation.symbol,
                ),
            )
        )

        for recommendation in sorted_recommendations:
            if recommendation.symbol in seen:
                raise ValueError(
                    f"duplicate recommendation symbol: {recommendation.symbol}"
                )
            seen.add(recommendation.symbol)

        object.__setattr__(
            self,
            "recommendations",
            sorted_recommendations,
        )

    @property
    def recommendation_count(self) -> int:
        return len(self.recommendations)

    @property
    def actionable(self) -> tuple[TradeRecommendation, ...]:
        return tuple(
            recommendation
            for recommendation in self.recommendations
            if recommendation.is_actionable
        )

    @property
    def buys(self) -> tuple[TradeRecommendation, ...]:
        return tuple(
            recommendation
            for recommendation in self.recommendations
            if recommendation.action is SignalSide.BUY
        )

    @property
    def sells(self) -> tuple[TradeRecommendation, ...]:
        return tuple(
            recommendation
            for recommendation in self.recommendations
            if recommendation.action is SignalSide.SELL
        )

    @property
    def holds(self) -> tuple[TradeRecommendation, ...]:
        return tuple(
            recommendation
            for recommendation in self.recommendations
            if recommendation.action is SignalSide.HOLD
        )

    def get(self, symbol: str) -> TradeRecommendation:
        normalized_symbol = symbol.strip().upper()
        for recommendation in self.recommendations:
            if recommendation.symbol == normalized_symbol:
                return recommendation
        raise KeyError(f"unknown recommendation symbol: {symbol}")


@dataclass(frozen=True, slots=True)
class _Vote:
    strategy: str
    side: SignalSide
    strategy_quality: Decimal
    signal_confidence: Decimal
    weighted_score: Decimal
    signal: TradingSignal


@dataclass(frozen=True, slots=True)
class EnsembleDecisionEngine:
    """Combine ranked strategy signals into explainable recommendations."""

    def decide(
        self,
        *,
        ranking: StrategyRankingReport,
        batches: Iterable[SignalBatch],
    ) -> EnsembleDecisionReport:
        reusable_batches = tuple(batches)
        if not reusable_batches:
            raise ValueError("ensemble decision requires at least one signal batch")

        generated_for = self._generated_for(reusable_batches)
        weights = self._strategy_weights(ranking)
        votes_by_symbol = self._votes_by_symbol(
            batches=reusable_batches,
            weights=weights,
        )
        recommendations = tuple(
            self._recommendation(
                symbol=symbol,
                votes=votes,
            )
            for symbol, votes in sorted(votes_by_symbol.items())
        )
        return EnsembleDecisionReport(
            generated_for=generated_for,
            recommendations=recommendations,
        )

    def _generated_for(self, batches: tuple[SignalBatch, ...]) -> date:
        generated_dates = {batch.generated_for for batch in batches}
        if len(generated_dates) != 1:
            raise ValueError("ensemble batches must share the same generated date")
        return next(iter(generated_dates))

    def _strategy_weights(
        self,
        ranking: StrategyRankingReport,
    ) -> Mapping[str, Decimal]:
        weights: dict[str, Decimal] = {}
        for ranked in ranking.ranked:
            weights[ranked.strategy] = self._strategy_weight(ranked)
        return MappingProxyType(weights)

    def _strategy_weight(self, ranked: RankedStrategy) -> Decimal:
        if ranked.composite_score > _ZERO:
            return min(ranked.composite_score, _ONE)
        fallback_weight = _DEFAULT_WEIGHT / Decimal(ranked.rank)
        return min(fallback_weight, _ONE)

    def _votes_by_symbol(
        self,
        *,
        batches: tuple[SignalBatch, ...],
        weights: Mapping[str, Decimal],
    ) -> Mapping[str, tuple[_Vote, ...]]:
        mutable: dict[str, list[_Vote]] = {}
        seen: set[tuple[str, str]] = set()

        for batch in sorted(batches, key=lambda item: item.strategy):
            strategy_quality = weights.get(batch.strategy, _DEFAULT_WEIGHT)
            for signal in batch.signals:
                key = (signal.symbol, signal.strategy)
                if key in seen:
                    raise ValueError(
                        "duplicate strategy signal for recommendation symbol"
                    )
                seen.add(key)
                mutable.setdefault(signal.symbol, []).append(
                    _Vote(
                        strategy=signal.strategy,
                        side=signal.side,
                        strategy_quality=strategy_quality,
                        signal_confidence=signal.confidence,
                        weighted_score=(strategy_quality * signal.confidence),
                        signal=signal,
                    )
                )

        return MappingProxyType(
            {
                symbol: tuple(
                    sorted(
                        votes,
                        key=lambda vote: vote.strategy,
                    )
                )
                for symbol, votes in mutable.items()
            }
        )

    def _recommendation(
        self,
        *,
        symbol: str,
        votes: tuple[_Vote, ...],
    ) -> TradeRecommendation:
        buy_score = self._score_for(votes=votes, side=SignalSide.BUY)
        sell_score = self._score_for(votes=votes, side=SignalSide.SELL)
        hold_score = self._score_for(votes=votes, side=SignalSide.HOLD)
        action = self._action(
            buy_score=buy_score,
            sell_score=sell_score,
            hold_score=hold_score,
        )

        supporting = self._strategies_for_action(
            votes=votes,
            action=action,
        )
        opposing = self._opposing_strategies(
            votes=votes,
            action=action,
        )
        neutral = self._strategies_for_side(
            votes=votes,
            side=SignalSide.HOLD,
        )
        agreement_score = self._agreement_score(
            action=action,
            buy_score=buy_score,
            sell_score=sell_score,
            hold_score=hold_score,
        )
        strategy_quality_score = self._strategy_quality_score(
            votes=votes,
            action=action,
        )
        signal_confidence_score = self._signal_confidence_score(
            votes=votes,
            action=action,
        )
        coverage_score = self._coverage_score(
            supporting=supporting,
            votes=votes,
        )
        recommendation_score = self._recommendation_score(
            action=action,
            agreement_score=agreement_score,
            strategy_quality_score=strategy_quality_score,
            signal_confidence_score=signal_confidence_score,
            coverage_score=coverage_score,
        )
        net_score = buy_score - sell_score

        return TradeRecommendation(
            symbol=symbol,
            action=action,
            confidence=recommendation_score,
            score=net_score,
            supporting_strategies=supporting,
            opposing_strategies=opposing,
            neutral_strategies=neutral,
            reasons=self._reasons(
                action=action,
                agreement_score=agreement_score,
                strategy_quality_score=strategy_quality_score,
                signal_confidence_score=signal_confidence_score,
                coverage_score=coverage_score,
                recommendation_score=recommendation_score,
                supporting=supporting,
                opposing=opposing,
                neutral=neutral,
            ),
            agreement_score=agreement_score,
            strategy_quality_score=strategy_quality_score,
            signal_confidence_score=signal_confidence_score,
            coverage_score=coverage_score,
            recommendation_score=recommendation_score,
        )

    def _score_for(
        self,
        *,
        votes: tuple[_Vote, ...],
        side: SignalSide,
    ) -> Decimal:
        return sum(
            (vote.weighted_score for vote in votes if vote.side is side),
            _ZERO,
        )

    def _action(
        self,
        *,
        buy_score: Decimal,
        sell_score: Decimal,
        hold_score: Decimal,
    ) -> SignalSide:
        if buy_score > sell_score and buy_score > hold_score:
            return SignalSide.BUY
        if sell_score > buy_score and sell_score > hold_score:
            return SignalSide.SELL
        return SignalSide.HOLD

    def _agreement_score(
        self,
        *,
        action: SignalSide,
        buy_score: Decimal,
        sell_score: Decimal,
        hold_score: Decimal,
    ) -> Decimal:
        actionable_score = buy_score + sell_score
        total_score = actionable_score + hold_score

        if action is SignalSide.BUY and actionable_score > _ZERO:
            return buy_score / actionable_score
        if action is SignalSide.SELL and actionable_score > _ZERO:
            return sell_score / actionable_score
        if action is SignalSide.HOLD and total_score > _ZERO:
            return hold_score / total_score
        return _ZERO

    def _strategy_quality_score(
        self,
        *,
        votes: tuple[_Vote, ...],
        action: SignalSide,
    ) -> Decimal:
        supporting_votes = self._votes_for_action(
            votes=votes,
            action=action,
        )
        if not supporting_votes:
            return _ZERO
        return _average(vote.strategy_quality for vote in supporting_votes)

    def _signal_confidence_score(
        self,
        *,
        votes: tuple[_Vote, ...],
        action: SignalSide,
    ) -> Decimal:
        supporting_votes = self._votes_for_action(
            votes=votes,
            action=action,
        )
        if not supporting_votes:
            return _ZERO
        return _average(vote.signal_confidence for vote in supporting_votes)

    def _coverage_score(
        self,
        *,
        supporting: tuple[str, ...],
        votes: tuple[_Vote, ...],
    ) -> Decimal:
        if not votes:
            return _ZERO
        return Decimal(len(supporting)) / Decimal(len(votes))

    def _recommendation_score(
        self,
        *,
        action: SignalSide,
        agreement_score: Decimal,
        strategy_quality_score: Decimal,
        signal_confidence_score: Decimal,
        coverage_score: Decimal,
    ) -> Decimal:
        if action is SignalSide.HOLD:
            return _ZERO
        return min(
            (
                (_AGREEMENT_WEIGHT * agreement_score)
                + (_STRATEGY_QUALITY_WEIGHT * strategy_quality_score)
                + (_SIGNAL_CONFIDENCE_WEIGHT * signal_confidence_score)
                + (_COVERAGE_WEIGHT * coverage_score)
            ),
            _ONE,
        )

    def _votes_for_action(
        self,
        *,
        votes: tuple[_Vote, ...],
        action: SignalSide,
    ) -> tuple[_Vote, ...]:
        if action is SignalSide.HOLD:
            return tuple(vote for vote in votes if vote.side is SignalSide.HOLD)
        return tuple(vote for vote in votes if vote.side is action)

    def _strategies_for_action(
        self,
        *,
        votes: tuple[_Vote, ...],
        action: SignalSide,
    ) -> tuple[str, ...]:
        if action is SignalSide.HOLD:
            return self._strategies_for_side(
                votes=votes,
                side=SignalSide.HOLD,
            )
        return self._strategies_for_side(votes=votes, side=action)

    def _opposing_strategies(
        self,
        *,
        votes: tuple[_Vote, ...],
        action: SignalSide,
    ) -> tuple[str, ...]:
        if action is SignalSide.BUY:
            return self._strategies_for_side(
                votes=votes,
                side=SignalSide.SELL,
            )
        if action is SignalSide.SELL:
            return self._strategies_for_side(
                votes=votes,
                side=SignalSide.BUY,
            )
        return ()

    def _strategies_for_side(
        self,
        *,
        votes: tuple[_Vote, ...],
        side: SignalSide,
    ) -> tuple[str, ...]:
        return tuple(sorted(vote.strategy for vote in votes if vote.side is side))

    def _reasons(
        self,
        *,
        action: SignalSide,
        agreement_score: Decimal,
        strategy_quality_score: Decimal,
        signal_confidence_score: Decimal,
        coverage_score: Decimal,
        recommendation_score: Decimal,
        supporting: tuple[str, ...],
        opposing: tuple[str, ...],
        neutral: tuple[str, ...],
    ) -> tuple[str, ...]:
        return (
            f"ensemble action: {action.value}",
            f"agreement score: {agreement_score}",
            f"strategy quality score: {strategy_quality_score}",
            f"signal confidence score: {signal_confidence_score}",
            f"coverage score: {coverage_score}",
            f"recommendation score: {recommendation_score}",
            f"supporting strategies: {len(supporting)}",
            f"opposing strategies: {len(opposing)}",
            f"neutral strategies: {len(neutral)}",
        )


def _bounded_decimal(*, value: Decimal, label: str) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < _ZERO or normalized > _ONE:
        raise ValueError(f"{label} must be between 0 and 1")
    return normalized


def _average(values: Iterable[Decimal]) -> Decimal:
    reusable_values = tuple(values)
    if not reusable_values:
        return _ZERO
    return sum(reusable_values, _ZERO) / Decimal(len(reusable_values))


def _normalize_names(names: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(sorted(name.strip().lower() for name in names))
    if any(not name for name in normalized):
        raise ValueError("strategy names cannot contain empty values")
    return normalized
