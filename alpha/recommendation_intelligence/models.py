from __future__ import annotations

from collections.abc import Mapping
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


class RecommendationAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    ACCUMULATE = "ACCUMULATE"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    AVOID = "AVOID"


@dataclass(frozen=True, slots=True)
class OHLCVBar:
    observed_on: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        for field_name in (
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
        ):
            value = _as_decimal(getattr(self, field_name))
            if value < _ZERO:
                raise ValueError(f"{field_name} cannot be negative")
            object.__setattr__(self, field_name, value)

        if self.high_price < self.low_price:
            raise ValueError("bar high cannot be below low")
        if self.open_price > self.high_price or self.open_price < self.low_price:
            raise ValueError("bar open must be within high/low range")
        if self.close_price > self.high_price or self.close_price < self.low_price:
            raise ValueError("bar close must be within high/low range")


class RecommendationDecision(StrEnum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    WATCHLIST = "WATCHLIST"
    HOLD = "HOLD"
    AVOID = "AVOID"
    SELL = "SELL"


class EvidenceDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class EntryTriggerStyle(StrEnum):
    ENTER_IN_ZONE = "ENTER_IN_ZONE"
    CROSS_ABOVE = "CROSS_ABOVE"
    CLOSE_ABOVE = "CLOSE_ABOVE"
    BREAKOUT_WITH_VOLUME = "BREAKOUT_WITH_VOLUME"
    RETEST_HOLD = "RETEST_HOLD"
    PULLBACK_TO_LEVEL = "PULLBACK_TO_LEVEL"


class TriggerStatus(StrEnum):
    TRIGGER_CONFIRMED = "TRIGGER_CONFIRMED"
    WAITING_FOR_CLOSE_ABOVE = "WAITING_FOR_CLOSE_ABOVE"
    WAITING_FOR_CROSS_ABOVE = "WAITING_FOR_CROSS_ABOVE"
    WAITING_FOR_VOLUME_CONFIRMATION = "WAITING_FOR_VOLUME_CONFIRMATION"
    INVALID_OR_NOT_ACTIONABLE = "INVALID_OR_NOT_ACTIONABLE"


class TradeStrategyType(StrEnum):
    MOMENTUM_BREAKOUT = "MOMENTUM_BREAKOUT"
    PULLBACK_ENTRY = "PULLBACK_ENTRY"
    AGGRESSIVE_ACCUMULATION = "AGGRESSIVE_ACCUMULATION"
    RETEST_HOLD = "RETEST_HOLD"
    NO_TRADE = "NO_TRADE"


class TradeStrategyAction(StrEnum):
    BUY_NOW = "BUY_NOW"
    WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"
    WAIT_FOR_DEEP_PULLBACK = "WAIT_FOR_DEEP_PULLBACK"
    WAIT_FOR_RETEST = "WAIT_FOR_RETEST"
    WAIT_FOR_CONFIRMATION = "WAIT_FOR_CONFIRMATION"
    HOLD_EXISTING = "HOLD_EXISTING"
    AVOID = "AVOID"


class StrategySuitability(StrEnum):
    HIGH_PROBABILITY = "HIGH_PROBABILITY"
    BALANCED = "BALANCED"
    HIGH_RISK_REWARD = "HIGH_RISK_REWARD"
    SPECULATIVE = "SPECULATIVE"
    NOT_SUITABLE = "NOT_SUITABLE"


class EdgeConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class StrategyQuality(StrEnum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    SPECULATIVE = "SPECULATIVE"
    NOT_SUITABLE = "NOT_SUITABLE"


class EntryZoneBasisType(StrEnum):
    BREAKOUT_LEVEL = "BREAKOUT_LEVEL"
    PRIOR_RESISTANCE = "PRIOR_RESISTANCE"
    SUPPORT = "SUPPORT"
    SWING_LOW = "SWING_LOW"
    FIBONACCI_RETRACEMENT = "FIBONACCI_RETRACEMENT"
    MOVING_AVERAGE_20 = "MOVING_AVERAGE_20"
    MOVING_AVERAGE_50 = "MOVING_AVERAGE_50"
    ATR_BAND = "ATR_BAND"
    VOLUME_DEMAND_ZONE = "VOLUME_DEMAND_ZONE"
    RECENT_CLOSE = "RECENT_CLOSE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class EntryZoneBasis:
    basis_type: EntryZoneBasisType
    level: Decimal | None
    description: str

    def __post_init__(self) -> None:
        description = self.description.strip()
        if not description:
            raise ValueError("entry zone basis description cannot be empty")
        object.__setattr__(self, "basis_type", EntryZoneBasisType(self.basis_type))
        object.__setattr__(self, "level", _optional_decimal(self.level))
        object.__setattr__(self, "description", description)


@dataclass(frozen=True, slots=True)
class StrategyEdgeStats:
    sample_size: int
    target_1_hit_rate: Decimal | None
    target_2_hit_rate: Decimal | None
    target_3_hit_rate: Decimal | None
    stop_loss_hit_rate: Decimal | None
    average_return: Decimal | None
    median_return: Decimal | None
    average_drawdown: Decimal | None
    median_holding_period_days: int | None
    expectancy: Decimal | None
    fill_probability: Decimal | None
    fill_window_days: int | None
    confidence: EdgeConfidence

    def __post_init__(self) -> None:
        if self.sample_size < 0:
            raise ValueError("strategy edge sample size cannot be negative")
        if (
            self.median_holding_period_days is not None
            and self.median_holding_period_days < 0
        ):
            raise ValueError("median holding period cannot be negative")
        if self.fill_window_days is not None and self.fill_window_days < 0:
            raise ValueError("fill window days cannot be negative")

        object.__setattr__(
            self,
            "target_1_hit_rate",
            _optional_bounded_ratio(self.target_1_hit_rate, "target 1 hit rate"),
        )
        object.__setattr__(
            self,
            "target_2_hit_rate",
            _optional_bounded_ratio(self.target_2_hit_rate, "target 2 hit rate"),
        )
        object.__setattr__(
            self,
            "target_3_hit_rate",
            _optional_bounded_ratio(self.target_3_hit_rate, "target 3 hit rate"),
        )
        object.__setattr__(
            self,
            "stop_loss_hit_rate",
            _optional_bounded_ratio(self.stop_loss_hit_rate, "stop loss hit rate"),
        )
        object.__setattr__(
            self,
            "average_return",
            _optional_decimal(self.average_return),
        )
        object.__setattr__(self, "median_return", _optional_decimal(self.median_return))
        object.__setattr__(
            self,
            "average_drawdown",
            _optional_decimal(self.average_drawdown),
        )
        object.__setattr__(self, "expectancy", _optional_decimal(self.expectancy))
        object.__setattr__(
            self,
            "fill_probability",
            _optional_bounded_ratio(self.fill_probability, "fill probability"),
        )
        object.__setattr__(self, "confidence", EdgeConfidence(self.confidence))


@dataclass(frozen=True, slots=True)
class StrategyRank:
    rank: int | None
    label: str
    quality: StrategyQuality
    rationale: str

    def __post_init__(self) -> None:
        label = self.label.strip()
        rationale = self.rationale.strip()
        if self.rank is not None and self.rank <= 0:
            raise ValueError("strategy rank must be positive")
        if not label:
            raise ValueError("strategy rank label cannot be empty")
        if not rationale:
            raise ValueError("strategy rank rationale cannot be empty")
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "quality", StrategyQuality(self.quality))
        object.__setattr__(self, "rationale", rationale)


@dataclass(frozen=True, slots=True)
class TradeStrategyPlaybook:
    strategy_type: TradeStrategyType
    name: str
    action: TradeStrategyAction
    strategy_rank: StrategyRank
    edge_stats: StrategyEdgeStats | None
    entry_zone_basis: tuple[EntryZoneBasis, ...]
    expected_wait_days: int | None
    entry_low: Decimal | None
    entry_high: Decimal | None
    trigger_text: str
    stop_loss: Decimal | None
    stop_rule: str
    trend_invalidation_reference: str | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    risk_reward: Decimal | None
    position_size_multiplier: Decimal
    expected_holding_period: str
    explanation: str

    def __post_init__(self) -> None:
        name = self.name.strip()
        trigger_text = self.trigger_text.strip()
        stop_rule = self.stop_rule.strip()
        trend_reference = (
            self.trend_invalidation_reference.strip()
            if self.trend_invalidation_reference is not None
            else None
        )
        expected_holding_period = self.expected_holding_period.strip()
        explanation = self.explanation.strip()

        if not name:
            raise ValueError("trade strategy name cannot be empty")
        if not trigger_text:
            raise ValueError("trade strategy trigger text cannot be empty")
        if not stop_rule:
            raise ValueError("trade strategy stop rule cannot be empty")
        if not expected_holding_period:
            raise ValueError("trade strategy holding period cannot be empty")
        if not explanation:
            raise ValueError("trade strategy explanation cannot be empty")
        if self.expected_wait_days is not None and self.expected_wait_days < 0:
            raise ValueError("expected wait days cannot be negative")

        object.__setattr__(
            self,
            "strategy_type",
            TradeStrategyType(self.strategy_type),
        )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "action", TradeStrategyAction(self.action))
        object.__setattr__(self, "entry_zone_basis", tuple(self.entry_zone_basis))
        object.__setattr__(self, "entry_low", _optional_decimal(self.entry_low))
        object.__setattr__(self, "entry_high", _optional_decimal(self.entry_high))
        object.__setattr__(self, "trigger_text", trigger_text)
        object.__setattr__(self, "stop_loss", _optional_decimal(self.stop_loss))
        object.__setattr__(self, "stop_rule", stop_rule)
        object.__setattr__(
            self,
            "trend_invalidation_reference",
            trend_reference if trend_reference else None,
        )
        object.__setattr__(self, "target_1", _optional_decimal(self.target_1))
        object.__setattr__(self, "target_2", _optional_decimal(self.target_2))
        object.__setattr__(self, "target_3", _optional_decimal(self.target_3))
        object.__setattr__(self, "risk_reward", _optional_decimal(self.risk_reward))
        object.__setattr__(
            self,
            "position_size_multiplier",
            _bounded_ratio(
                self.position_size_multiplier,
                "position size multiplier",
            ),
        )
        object.__setattr__(self, "expected_holding_period", expected_holding_period)
        object.__setattr__(self, "explanation", explanation)


@dataclass(frozen=True, slots=True)
class RecommendationEvidence:
    label: str
    score_points: Decimal
    max_points: Decimal
    rationale: str

    def __post_init__(self) -> None:
        label = self.label.strip()
        rationale = self.rationale.strip()
        score_points = _as_decimal(self.score_points)
        max_points = _as_decimal(self.max_points)

        if not label:
            raise ValueError("evidence label cannot be empty")
        if not rationale:
            raise ValueError("evidence rationale cannot be empty")
        if score_points < _ZERO:
            raise ValueError("evidence score points cannot be negative")
        if max_points <= _ZERO:
            raise ValueError("evidence max points must be positive")
        if score_points > max_points:
            raise ValueError("evidence score points cannot exceed max points")

        object.__setattr__(self, "label", label)
        object.__setattr__(self, "score_points", score_points)
        object.__setattr__(self, "max_points", max_points)
        object.__setattr__(self, "rationale", rationale)

    @property
    def score_ratio(self) -> Decimal:
        return _quantize(self.score_points / self.max_points)


@dataclass(frozen=True, slots=True)
class RecommendationRisk:
    label: str
    penalty_points: Decimal
    rationale: str

    def __post_init__(self) -> None:
        label = self.label.strip()
        rationale = self.rationale.strip()
        penalty_points = _as_decimal(self.penalty_points)

        if not label:
            raise ValueError("risk label cannot be empty")
        if not rationale:
            raise ValueError("risk rationale cannot be empty")
        if penalty_points < _ZERO:
            raise ValueError("risk penalty points cannot be negative")

        object.__setattr__(self, "label", label)
        object.__setattr__(self, "penalty_points", penalty_points)
        object.__setattr__(self, "rationale", rationale)


@dataclass(frozen=True, slots=True)
class RecommendationCandidate:
    symbol: str
    observed_on: date
    action: RecommendationAction
    strategy_score: Decimal
    probability_score: Decimal
    market_intelligence_score: Decimal
    liquidity_score: Decimal
    risk_score: Decimal
    expected_return: Decimal
    expected_drawdown: Decimal
    expected_holding_period_days: Decimal
    evidence: tuple[RecommendationEvidence, ...]
    risks: tuple[RecommendationRisk, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
    price_history: tuple[OHLCVBar, ...] = ()
    retracement_score: Decimal = Decimal("0.50")
    trend_structure_score: Decimal | None = None
    relative_strength_score: Decimal | None = None
    volume_confirmation_score: Decimal | None = None
    breakout_setup_score: Decimal | None = None
    market_regime_score: Decimal | None = None
    sector_strength_score: Decimal | None = None
    momentum_confirmation_score: Decimal | None = None
    price_trend_score: Decimal | None = None
    price_momentum_score: Decimal | None = None
    price_breakout_score: Decimal | None = None
    price_breakdown_score: Decimal | None = None
    price_structure_score: Decimal | None = None
    close_location_score: Decimal | None = None
    volatility_expansion_score: Decimal | None = None
    volume_expansion_score: Decimal | None = None
    volume_dry_up_score: Decimal | None = None
    accumulation_score: Decimal | None = None
    distribution_score: Decimal | None = None
    breakout_volume_confirmation: Decimal | None = None
    selloff_volume_penalty: Decimal | None = None
    dma_200: Decimal | None = None
    ema_20: Decimal | None = None
    ema_50: Decimal | None = None
    ema_200: Decimal | None = None
    benchmark_relative_strength: Decimal | None = None
    historical_win_rate: Decimal | None = None
    historical_average_gain: Decimal | None = None
    historical_average_loss: Decimal | None = None
    historical_expected_value: Decimal | None = None
    historical_average_hold_days: Decimal | None = None
    setup_type: str | None = None
    higher_highs_higher_lows: bool = False
    lower_highs_lower_lows: bool = False
    breakout_attempt: bool = False
    breakdown_attempt: bool = False
    market_regime: str = "SIDEWAYS"
    open_price: Decimal | None = None
    high_price: Decimal | None = None
    low_price: Decimal | None = None
    previous_close: Decimal | None = None
    previous_open_price: Decimal | None = None
    previous_high_price: Decimal | None = None
    previous_low_price: Decimal | None = None
    two_day_prior_open_price: Decimal | None = None
    two_day_prior_high_price: Decimal | None = None
    two_day_prior_low_price: Decimal | None = None
    two_day_prior_close: Decimal | None = None
    current_price: Decimal | None = None
    support_level: Decimal | None = None
    resistance_level: Decimal | None = None
    recent_high: Decimal | None = None
    prior_day_high: Decimal | None = None
    reversal_candle_high: Decimal | None = None
    retracement_low: Decimal | None = None
    dma_20: Decimal | None = None
    dma_50: Decimal | None = None
    atr: Decimal | None = None
    swing_high: Decimal | None = None
    swing_low: Decimal | None = None
    fibonacci_382: Decimal | None = None
    fibonacci_500: Decimal | None = None
    fibonacci_618: Decimal | None = None
    fibonacci_786: Decimal | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        metadata = _normalize_metadata(self.metadata)

        if not symbol:
            raise ValueError("candidate symbol cannot be empty")
        if len(self.evidence) == 0:
            raise ValueError("candidate requires at least one evidence item")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "price_history",
            tuple(sorted(self.price_history, key=lambda bar: bar.observed_on)),
        )
        object.__setattr__(
            self,
            "strategy_score",
            _bounded_ratio(self.strategy_score, "strategy_score"),
        )
        object.__setattr__(
            self,
            "probability_score",
            _bounded_ratio(self.probability_score, "probability_score"),
        )
        object.__setattr__(
            self,
            "market_intelligence_score",
            _bounded_ratio(
                self.market_intelligence_score,
                "market_intelligence_score",
            ),
        )
        object.__setattr__(
            self,
            "liquidity_score",
            _bounded_ratio(self.liquidity_score, "liquidity_score"),
        )
        object.__setattr__(
            self,
            "risk_score",
            _bounded_ratio(self.risk_score, "risk_score"),
        )
        object.__setattr__(
            self,
            "expected_return",
            _as_decimal(self.expected_return),
        )
        object.__setattr__(
            self,
            "expected_drawdown",
            _as_decimal(self.expected_drawdown),
        )
        object.__setattr__(
            self,
            "expected_holding_period_days",
            _as_decimal(self.expected_holding_period_days),
        )
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(
            self,
            "retracement_score",
            _bounded_ratio(self.retracement_score, "retracement_score"),
        )
        object.__setattr__(
            self,
            "trend_structure_score",
            _optional_bounded_ratio(
                self.trend_structure_score,
                "trend_structure_score",
            ),
        )
        object.__setattr__(
            self,
            "relative_strength_score",
            _optional_bounded_ratio(
                self.relative_strength_score,
                "relative_strength_score",
            ),
        )
        object.__setattr__(
            self,
            "volume_confirmation_score",
            _optional_bounded_ratio(
                self.volume_confirmation_score,
                "volume_confirmation_score",
            ),
        )
        object.__setattr__(
            self,
            "breakout_setup_score",
            _optional_bounded_ratio(
                self.breakout_setup_score,
                "breakout_setup_score",
            ),
        )
        object.__setattr__(
            self,
            "market_regime_score",
            _optional_bounded_ratio(
                self.market_regime_score,
                "market_regime_score",
            ),
        )
        object.__setattr__(
            self,
            "sector_strength_score",
            _optional_bounded_ratio(
                self.sector_strength_score,
                "sector_strength_score",
            ),
        )
        object.__setattr__(
            self,
            "momentum_confirmation_score",
            _optional_bounded_ratio(
                self.momentum_confirmation_score,
                "momentum_confirmation_score",
            ),
        )
        for field_name in (
            "price_trend_score",
            "price_momentum_score",
            "price_breakout_score",
            "price_breakdown_score",
            "price_structure_score",
            "close_location_score",
            "volatility_expansion_score",
            "volume_expansion_score",
            "volume_dry_up_score",
            "accumulation_score",
            "distribution_score",
            "breakout_volume_confirmation",
            "selloff_volume_penalty",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_bounded_ratio(
                    getattr(self, field_name),
                    field_name,
                ),
            )
        object.__setattr__(
            self,
            "benchmark_relative_strength",
            _optional_bounded_ratio(
                self.benchmark_relative_strength,
                "benchmark_relative_strength",
            ),
        )
        object.__setattr__(
            self,
            "historical_win_rate",
            _optional_bounded_ratio(
                self.historical_win_rate,
                "historical_win_rate",
            ),
        )
        object.__setattr__(self, "market_regime", self.market_regime.strip().upper())
        object.__setattr__(
            self,
            "setup_type",
            self.setup_type.strip().upper() if self.setup_type else None,
        )
        for field_name in (
            "open_price",
            "high_price",
            "low_price",
            "previous_close",
            "previous_open_price",
            "previous_high_price",
            "previous_low_price",
            "two_day_prior_open_price",
            "two_day_prior_high_price",
            "two_day_prior_low_price",
            "two_day_prior_close",
            "current_price",
            "support_level",
            "resistance_level",
            "recent_high",
            "prior_day_high",
            "reversal_candle_high",
            "retracement_low",
            "dma_20",
            "dma_50",
            "dma_200",
            "ema_20",
            "ema_50",
            "ema_200",
            "atr",
            "swing_high",
            "swing_low",
            "fibonacci_382",
            "fibonacci_500",
            "fibonacci_618",
            "fibonacci_786",
            "historical_average_gain",
            "historical_average_loss",
            "historical_expected_value",
            "historical_average_hold_days",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_decimal(getattr(self, field_name)),
            )


@dataclass(frozen=True, slots=True)
class RecommendationScoreBreakdown:
    strategy_points: Decimal
    probability_points: Decimal
    market_intelligence_points: Decimal
    liquidity_points: Decimal
    risk_points: Decimal
    portfolio_adjustment_points: Decimal
    opportunity_cost_points: Decimal
    retracement_points: Decimal = Decimal("0")
    trend_structure_points: Decimal = Decimal("0")
    relative_strength_points: Decimal = Decimal("0")
    volume_confirmation_points: Decimal = Decimal("0")
    breakout_setup_points: Decimal = Decimal("0")
    market_regime_points: Decimal = Decimal("0")
    sector_strength_points: Decimal = Decimal("0")
    candle_pattern_points: Decimal = Decimal("0")
    candle_weight: Decimal = Decimal("0")
    retracement_weight: Decimal = Decimal("0")
    evidence_points: Decimal = Decimal("0")
    conflict_penalty_points: Decimal = Decimal("0")
    regime_adjustment_points: Decimal = Decimal("0")

    @property
    def gross_points(self) -> Decimal:
        return _quantize(
            self.strategy_points
            + self.probability_points
            + self.market_intelligence_points
            + self.liquidity_points
        )

    @property
    def total_points(self) -> Decimal:
        return _quantize(
            self.gross_points
            + self.retracement_points
            + self.trend_structure_points
            + self.relative_strength_points
            + self.volume_confirmation_points
            + self.breakout_setup_points
            + self.candle_pattern_points
            + self.market_regime_points
            + self.sector_strength_points
            + self.evidence_points
            + self.regime_adjustment_points
            + self.risk_points
            + self.portfolio_adjustment_points
            + self.opportunity_cost_points
            - self.conflict_penalty_points
        )


@dataclass(frozen=True, slots=True)
class RecommendationScore:
    symbol: str
    score: Decimal
    decision: RecommendationDecision
    breakdown: RecommendationScoreBreakdown

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        score = _bounded_points(self.score, "recommendation score")

        if not symbol:
            raise ValueError("recommendation score symbol cannot be empty")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "score", score)

    @property
    def is_actionable(self) -> bool:
        return self.decision in {
            RecommendationDecision.STRONG_BUY,
            RecommendationDecision.BUY,
        }


@dataclass(frozen=True, slots=True)
class ExpectedValueAssessment:
    symbol: str
    expected_return: Decimal
    expected_drawdown: Decimal
    reward_to_risk: Decimal
    expected_holding_period_days: Decimal
    score: Decimal
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        reasons = tuple(reason.strip() for reason in self.reasons)

        if not symbol:
            raise ValueError("expected value symbol cannot be empty")
        if any(not reason for reason in reasons):
            raise ValueError("expected value reasons cannot be empty")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "expected_return",
            _as_decimal(self.expected_return),
        )
        object.__setattr__(
            self,
            "expected_drawdown",
            _as_decimal(self.expected_drawdown),
        )
        object.__setattr__(self, "reward_to_risk", _as_decimal(self.reward_to_risk))
        object.__setattr__(
            self,
            "expected_holding_period_days",
            _as_decimal(self.expected_holding_period_days),
        )
        object.__setattr__(self, "score", _bounded_ratio(self.score, "ev score"))
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class CandidateComparison:
    symbol: str
    score: Decimal
    expected_return: Decimal
    expected_drawdown: Decimal
    rank: int

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("comparison symbol cannot be empty")
        if self.rank <= 0:
            raise ValueError("comparison rank must be positive")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "score", _bounded_ratio(self.score, "score"))
        object.__setattr__(
            self,
            "expected_return",
            _as_decimal(self.expected_return),
        )
        object.__setattr__(
            self,
            "expected_drawdown",
            _as_decimal(self.expected_drawdown),
        )


@dataclass(frozen=True, slots=True)
class OpportunityCostAssessment:
    symbol: str
    rank: int
    candidate_count: int
    percentile: Decimal
    opportunity_cost_points: Decimal
    better_candidates: tuple[CandidateComparison, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        reasons = tuple(reason.strip() for reason in self.reasons)

        if not symbol:
            raise ValueError("opportunity cost symbol cannot be empty")
        if self.rank <= 0:
            raise ValueError("opportunity cost rank must be positive")
        if self.candidate_count <= 0:
            raise ValueError("candidate_count must be positive")
        if self.rank > self.candidate_count:
            raise ValueError("rank cannot exceed candidate_count")
        if any(not reason for reason in reasons):
            raise ValueError("opportunity cost reasons cannot be empty")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "percentile",
            _bounded_ratio(self.percentile, "percentile"),
        )
        object.__setattr__(
            self,
            "opportunity_cost_points",
            _as_decimal(self.opportunity_cost_points),
        )
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class AllocationAdjustment:
    base_allocation_percent: Decimal
    adjusted_allocation_percent: Decimal
    adjustment_points: Decimal
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        reasons = tuple(reason.strip() for reason in self.reasons)
        base_allocation = _as_decimal(self.base_allocation_percent)
        adjusted_allocation = _as_decimal(self.adjusted_allocation_percent)

        if base_allocation < _ZERO:
            raise ValueError("base allocation cannot be negative")
        if adjusted_allocation < _ZERO:
            raise ValueError("adjusted allocation cannot be negative")
        if any(not reason for reason in reasons):
            raise ValueError("allocation reasons cannot be empty")

        object.__setattr__(self, "base_allocation_percent", base_allocation)
        object.__setattr__(self, "adjusted_allocation_percent", adjusted_allocation)
        object.__setattr__(
            self,
            "adjustment_points",
            _as_decimal(self.adjustment_points),
        )
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class PriceEvidence:
    trend_state: str
    structure_state: str
    breakout_state: str
    retracement_state: str
    support_resistance_state: str
    close_strength: Decimal
    volatility_state: str
    price_score: Decimal

    def __post_init__(self) -> None:
        for field_name in (
            "trend_state",
            "structure_state",
            "breakout_state",
            "retracement_state",
            "support_resistance_state",
            "volatility_state",
        ):
            value = getattr(self, field_name).strip().upper()
            if not value:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, value)
        object.__setattr__(
            self,
            "close_strength",
            _bounded_ratio(self.close_strength, "close_strength"),
        )
        object.__setattr__(
            self,
            "price_score",
            _bounded_ratio(self.price_score, "price_score"),
        )


@dataclass(frozen=True, slots=True)
class VolumeEvidence:
    volume_vs_average: Decimal
    volume_expansion_score: Decimal
    volume_dry_up_score: Decimal
    accumulation_score: Decimal
    distribution_score: Decimal
    breakout_volume_confirmation: Decimal
    selloff_volume_penalty: Decimal
    volume_score: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "volume_vs_average",
            _as_decimal(self.volume_vs_average),
        )
        for field_name in (
            "volume_expansion_score",
            "volume_dry_up_score",
            "accumulation_score",
            "distribution_score",
            "breakout_volume_confirmation",
            "selloff_volume_penalty",
            "volume_score",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded_ratio(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class PriceVolumeAssessment:
    price_evidence: PriceEvidence
    volume_evidence: VolumeEvidence
    supports_buy: bool
    supports_sell: bool
    override_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        reasons = tuple(reason.strip() for reason in self.override_reasons)
        if any(not reason for reason in reasons):
            raise ValueError("price-volume override reasons cannot be empty")
        object.__setattr__(self, "override_reasons", reasons)


@dataclass(frozen=True, slots=True)
class CandlePatternAssessment:
    pattern: str
    score: Decimal
    weight: Decimal
    confirmation: str
    entry_trigger: Decimal | None
    stop_level: Decimal | None
    invalidation_level: Decimal | None
    explanation: str
    volume_confirmed: bool

    def __post_init__(self) -> None:
        pattern = self.pattern.strip().upper()
        confirmation = self.confirmation.strip().upper()
        explanation = self.explanation.strip()
        if not pattern:
            raise ValueError("candle pattern cannot be empty")
        if not confirmation:
            raise ValueError("candle confirmation cannot be empty")
        if not explanation:
            raise ValueError("candle explanation cannot be empty")

        object.__setattr__(self, "pattern", pattern)
        object.__setattr__(
            self,
            "score",
            _bounded_ratio(self.score, "candle score"),
        )
        object.__setattr__(
            self,
            "weight",
            _bounded_ratio(self.weight, "candle weight"),
        )
        object.__setattr__(self, "confirmation", confirmation)
        object.__setattr__(
            self,
            "entry_trigger",
            _optional_decimal(self.entry_trigger),
        )
        object.__setattr__(self, "stop_level", _optional_decimal(self.stop_level))
        object.__setattr__(
            self,
            "invalidation_level",
            _optional_decimal(self.invalidation_level),
        )
        object.__setattr__(self, "explanation", explanation)


@dataclass(frozen=True, slots=True)
class EvidenceSignal:
    label: str
    direction: EvidenceDirection
    score: Decimal
    weight: Decimal
    points: Decimal
    rationale: str

    def __post_init__(self) -> None:
        label = self.label.strip()
        rationale = self.rationale.strip()
        score = _bounded_ratio(self.score, "evidence score")
        weight = _bounded_ratio(self.weight, "evidence weight")
        points = _as_decimal(self.points)

        if not label:
            raise ValueError("evidence signal label cannot be empty")
        if not rationale:
            raise ValueError("evidence signal rationale cannot be empty")

        object.__setattr__(self, "label", label)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "weight", weight)
        object.__setattr__(self, "points", points)
        object.__setattr__(self, "rationale", rationale)


@dataclass(frozen=True, slots=True)
class SetupQualityAssessment:
    setup_type: str
    score: Decimal
    classification: str
    rationale: str

    def __post_init__(self) -> None:
        setup_type = self.setup_type.strip().upper()
        classification = self.classification.strip().upper()
        rationale = self.rationale.strip()

        if not setup_type:
            raise ValueError("setup type cannot be empty")
        if not classification:
            raise ValueError("setup classification cannot be empty")
        if not rationale:
            raise ValueError("setup rationale cannot be empty")

        object.__setattr__(self, "setup_type", setup_type)
        object.__setattr__(
            self,
            "score",
            _bounded_ratio(self.score, "setup score"),
        )
        object.__setattr__(self, "classification", classification)
        object.__setattr__(self, "rationale", rationale)


@dataclass(frozen=True, slots=True)
class TradeSetupAssessment:
    setup_name: str
    setup_category: str
    setup_quality: str
    setup_confidence: Decimal
    setup_stage: str
    entry_ready: bool
    aggressive_entry: Decimal | None
    preferred_entry: Decimal | None
    confirmation_entry: Decimal | None
    maximum_chase_price: Decimal | None
    stop_chase_price: Decimal | None
    initial_stop: Decimal | None
    move_stop_to_breakeven: Decimal | None
    partial_exit: Decimal | None
    atr_trail: str
    final_exit: Decimal | None
    historical_win_rate: Decimal | None = None
    average_gain: Decimal | None = None
    average_loss: Decimal | None = None
    average_hold_period_days: Decimal | None = None
    profit_factor: Decimal | None = None
    expected_value: Decimal | None = None
    expected_holding_period: str = "unavailable"
    minimum_holding_period: int | None = None
    maximum_holding_period: int | None = None
    holding_period_basis: str = "unavailable"
    rationale: str = ""
    readiness_reason: str = ""

    def __post_init__(self) -> None:
        setup_name = self.setup_name.strip().upper()
        setup_category = self.setup_category.strip().upper()
        setup_quality = self.setup_quality.strip().upper()
        setup_stage = self.setup_stage.strip().upper()
        atr_trail = self.atr_trail.strip()
        expected_holding_period = self.expected_holding_period.strip()
        holding_period_basis = self.holding_period_basis.strip()
        rationale = self.rationale.strip()
        readiness_reason = self.readiness_reason.strip()

        if not setup_name:
            raise ValueError("setup name cannot be empty")
        if not setup_category:
            raise ValueError("setup category cannot be empty")
        if not setup_quality:
            raise ValueError("setup quality cannot be empty")
        if not setup_stage:
            raise ValueError("setup stage cannot be empty")
        if not atr_trail:
            raise ValueError("setup ATR trail cannot be empty")
        if not expected_holding_period:
            raise ValueError("expected holding period cannot be empty")
        if not holding_period_basis:
            raise ValueError("holding period basis cannot be empty")
        if not rationale:
            raise ValueError("setup rationale cannot be empty")
        if not readiness_reason:
            raise ValueError("setup readiness reason cannot be empty")
        if setup_stage in {"ENTRY_READY", "ACTIVE"} and not self.entry_ready:
            raise ValueError("ENTRY_READY and ACTIVE setups must be entry-ready")
        if (
            setup_stage
            in {
                "BUILDING",
                "READY_FOR_CONFIRMATION",
                "LATE",
                "INVALID",
            }
            and self.entry_ready
        ):
            raise ValueError(f"{setup_stage} setups cannot be entry-ready")

        object.__setattr__(self, "setup_name", setup_name)
        object.__setattr__(self, "setup_category", setup_category)
        object.__setattr__(self, "setup_quality", setup_quality)
        object.__setattr__(
            self,
            "setup_confidence",
            _bounded_points(self.setup_confidence, "setup confidence"),
        )
        object.__setattr__(self, "setup_stage", setup_stage)
        for field_name in (
            "aggressive_entry",
            "preferred_entry",
            "confirmation_entry",
            "maximum_chase_price",
            "stop_chase_price",
            "initial_stop",
            "move_stop_to_breakeven",
            "partial_exit",
            "final_exit",
            "average_gain",
            "average_loss",
            "average_hold_period_days",
            "profit_factor",
            "expected_value",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_decimal(getattr(self, field_name)),
            )
        if self.minimum_holding_period is not None and self.minimum_holding_period < 0:
            raise ValueError("minimum holding period cannot be negative")
        if self.maximum_holding_period is not None and self.maximum_holding_period < 0:
            raise ValueError("maximum holding period cannot be negative")
        object.__setattr__(
            self,
            "historical_win_rate",
            _optional_bounded_ratio(self.historical_win_rate, "setup win rate"),
        )
        object.__setattr__(self, "atr_trail", atr_trail)
        object.__setattr__(
            self,
            "expected_holding_period",
            expected_holding_period,
        )
        object.__setattr__(self, "holding_period_basis", holding_period_basis)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "readiness_reason", readiness_reason)

    @property
    def expectancy_status(self) -> str:
        if any(
            value is not None
            for value in (
                self.historical_win_rate,
                self.average_gain,
                self.average_loss,
                self.average_hold_period_days,
                self.profit_factor,
                self.expected_value,
            )
        ):
            return "available"
        return "unavailable"


@dataclass(frozen=True, slots=True)
class HistoricalExpectancy:
    win_rate: Decimal | None = None
    average_gain: Decimal | None = None
    average_loss: Decimal | None = None
    expected_value: Decimal | None = None
    average_hold_period_days: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "win_rate",
            _optional_bounded_ratio(self.win_rate, "historical win rate"),
        )
        for field_name in (
            "average_gain",
            "average_loss",
            "expected_value",
            "average_hold_period_days",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_decimal(getattr(self, field_name)),
            )

    @property
    def is_available(self) -> bool:
        return any(
            value is not None
            for value in (
                self.win_rate,
                self.average_gain,
                self.average_loss,
                self.expected_value,
                self.average_hold_period_days,
            )
        )

    @property
    def status(self) -> str:
        if self.is_available:
            return "available"
        return "unavailable"


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    signals: tuple[EvidenceSignal, ...]
    score: Decimal
    confidence_score: Decimal
    conflict_penalty_points: Decimal
    regime_adjustment_points: Decimal
    regime_reason: str
    setup_quality: SetupQualityAssessment
    historical_expectancy: HistoricalExpectancy
    price_volume: PriceVolumeAssessment
    candle_pattern: CandlePatternAssessment

    def __post_init__(self) -> None:
        if len(self.signals) == 0:
            raise ValueError("evidence assessment requires at least one signal")
        regime_reason = self.regime_reason.strip()
        if not regime_reason:
            raise ValueError("regime reason cannot be empty")

        object.__setattr__(
            self,
            "score",
            _bounded_points(self.score, "evidence score"),
        )
        object.__setattr__(
            self,
            "confidence_score",
            _bounded_ratio(self.confidence_score, "confidence score"),
        )
        object.__setattr__(
            self,
            "conflict_penalty_points",
            _as_decimal(self.conflict_penalty_points),
        )
        object.__setattr__(
            self,
            "regime_adjustment_points",
            _as_decimal(self.regime_adjustment_points),
        )
        object.__setattr__(self, "regime_reason", regime_reason)

    @property
    def bullish_signals(self) -> tuple[EvidenceSignal, ...]:
        return tuple(
            signal
            for signal in self.signals
            if signal.direction is EvidenceDirection.BULLISH
        )

    @property
    def bearish_signals(self) -> tuple[EvidenceSignal, ...]:
        return tuple(
            signal
            for signal in self.signals
            if signal.direction is EvidenceDirection.BEARISH
        )

    @property
    def top_contributors(self) -> tuple[EvidenceSignal, ...]:
        return tuple(
            sorted(
                self.signals,
                key=lambda signal: (
                    -abs(signal.points),
                    signal.label,
                ),
            )[:3]
        )

    @property
    def price_evidence(self) -> PriceEvidence:
        return self.price_volume.price_evidence

    @property
    def volume_evidence(self) -> VolumeEvidence:
        return self.price_volume.volume_evidence


@dataclass(frozen=True, slots=True)
class RecommendationTradePlan:
    final_signal: str
    final_score: Decimal
    confidence: str
    entry_price: Decimal | None
    entry_trigger_style: EntryTriggerStyle
    trigger_status: TriggerStatus
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    initial_stop_loss: Decimal | None
    trailing_stop_strategy: str
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    risk_reward_ratio: Decimal | None
    invalidation_level: Decimal | None
    invalidation_reason: str
    retracement_score: Decimal
    retracement_weight: Decimal
    retracement_zone: str
    nearest_fibonacci_level: Decimal | None
    swing_high: Decimal | None
    swing_low: Decimal | None
    support_level_used: Decimal | None
    atr_value: Decimal | None
    dma_20_invalidation: Decimal | None
    dma_50: Decimal | None
    dma_200: Decimal | None
    relative_volume: Decimal | None
    historical_bar_count: int
    unavailable_reasons: tuple[str, ...]
    candle_pattern: str
    candle_score: Decimal
    candle_weight: Decimal
    candle_confirmation: str
    candle_entry_trigger: Decimal | None
    candle_stop_level: Decimal | None
    candle_invalidation_level: Decimal | None
    candle_explanation: str
    setup_name: str
    setup_category: str
    setup_quality_label: str
    setup_confidence: Decimal
    setup_stage: str
    setup_entry_ready: bool
    aggressive_entry: Decimal | None
    preferred_entry: Decimal | None
    confirmation_entry: Decimal | None
    maximum_chase_price: Decimal | None
    stop_chase_price: Decimal | None
    move_stop_to_breakeven: Decimal | None
    partial_exit: Decimal | None
    atr_trail: str
    final_exit: Decimal | None
    setup_expectancy_status: str
    expected_holding_period: str
    minimum_holding_period: int | None
    maximum_holding_period: int | None
    holding_period_basis: str
    setup_rationale: str
    setup_readiness_reason: str
    trade_plan_explanation: str

    def __post_init__(self) -> None:
        final_signal = self.final_signal.strip().upper()
        confidence = self.confidence.strip().upper()
        invalidation_reason = self.invalidation_reason.strip()
        retracement_zone = self.retracement_zone.strip()
        trailing_stop_strategy = self.trailing_stop_strategy.strip()
        trade_plan_explanation = self.trade_plan_explanation.strip()
        setup_name = self.setup_name.strip().upper()
        setup_category = self.setup_category.strip().upper()
        setup_quality_label = self.setup_quality_label.strip().upper()
        setup_stage = self.setup_stage.strip().upper()
        atr_trail = self.atr_trail.strip()
        setup_expectancy_status = self.setup_expectancy_status.strip().lower()
        expected_holding_period = self.expected_holding_period.strip()
        holding_period_basis = self.holding_period_basis.strip()
        setup_rationale = self.setup_rationale.strip()
        setup_readiness_reason = self.setup_readiness_reason.strip()

        if not final_signal:
            raise ValueError("final signal cannot be empty")
        if not confidence:
            raise ValueError("confidence cannot be empty")
        if not invalidation_reason:
            raise ValueError("invalidation reason cannot be empty")
        if not retracement_zone:
            raise ValueError("retracement zone cannot be empty")
        if not trailing_stop_strategy:
            raise ValueError("trailing stop strategy cannot be empty")
        if not trade_plan_explanation:
            raise ValueError("trade plan explanation cannot be empty")
        if not setup_name:
            raise ValueError("setup name cannot be empty")
        if not setup_category:
            raise ValueError("setup category cannot be empty")
        if not setup_quality_label:
            raise ValueError("setup quality label cannot be empty")
        if not setup_stage:
            raise ValueError("setup stage cannot be empty")
        if not atr_trail:
            raise ValueError("setup ATR trail cannot be empty")
        if not setup_expectancy_status:
            raise ValueError("setup expectancy status cannot be empty")
        if not expected_holding_period:
            raise ValueError("expected holding period cannot be empty")
        if not holding_period_basis:
            raise ValueError("holding period basis cannot be empty")
        if not setup_rationale:
            raise ValueError("setup rationale cannot be empty")
        if not setup_readiness_reason:
            raise ValueError("setup readiness reason cannot be empty")

        object.__setattr__(self, "final_signal", final_signal)
        object.__setattr__(
            self,
            "final_score",
            _bounded_points(self.final_score, "final_score"),
        )
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(
            self,
            "entry_trigger_style",
            EntryTriggerStyle(self.entry_trigger_style),
        )
        object.__setattr__(
            self,
            "trigger_status",
            TriggerStatus(self.trigger_status),
        )
        object.__setattr__(self, "entry_price", _optional_decimal(self.entry_price))
        object.__setattr__(
            self,
            "entry_zone_low",
            _optional_decimal(self.entry_zone_low),
        )
        object.__setattr__(
            self,
            "entry_zone_high",
            _optional_decimal(self.entry_zone_high),
        )
        object.__setattr__(
            self,
            "initial_stop_loss",
            _optional_decimal(self.initial_stop_loss),
        )
        object.__setattr__(self, "target_1", _optional_decimal(self.target_1))
        object.__setattr__(self, "target_2", _optional_decimal(self.target_2))
        object.__setattr__(self, "target_3", _optional_decimal(self.target_3))
        object.__setattr__(
            self,
            "risk_reward_ratio",
            _optional_decimal(self.risk_reward_ratio),
        )
        object.__setattr__(
            self,
            "invalidation_level",
            _optional_decimal(self.invalidation_level),
        )
        object.__setattr__(
            self,
            "retracement_score",
            _bounded_ratio(self.retracement_score, "retracement_score"),
        )
        object.__setattr__(
            self,
            "retracement_weight",
            _bounded_ratio(self.retracement_weight, "retracement_weight"),
        )
        object.__setattr__(
            self,
            "nearest_fibonacci_level",
            _optional_decimal(self.nearest_fibonacci_level),
        )
        object.__setattr__(self, "swing_high", _optional_decimal(self.swing_high))
        object.__setattr__(self, "swing_low", _optional_decimal(self.swing_low))
        object.__setattr__(
            self,
            "support_level_used",
            _optional_decimal(self.support_level_used),
        )
        object.__setattr__(self, "atr_value", _optional_decimal(self.atr_value))
        object.__setattr__(
            self,
            "dma_20_invalidation",
            _optional_decimal(self.dma_20_invalidation),
        )
        object.__setattr__(self, "dma_50", _optional_decimal(self.dma_50))
        object.__setattr__(self, "dma_200", _optional_decimal(self.dma_200))
        object.__setattr__(
            self,
            "relative_volume",
            _optional_decimal(self.relative_volume),
        )
        if self.historical_bar_count < 0:
            raise ValueError("historical bar count cannot be negative")
        object.__setattr__(
            self,
            "unavailable_reasons",
            tuple(
                reason.strip() for reason in self.unavailable_reasons if reason.strip()
            ),
        )
        object.__setattr__(self, "candle_pattern", self.candle_pattern.strip().upper())
        object.__setattr__(
            self,
            "candle_score",
            _bounded_ratio(self.candle_score, "candle_score"),
        )
        object.__setattr__(
            self,
            "candle_weight",
            _bounded_ratio(self.candle_weight, "candle_weight"),
        )
        object.__setattr__(
            self,
            "candle_confirmation",
            self.candle_confirmation.strip().upper(),
        )
        object.__setattr__(
            self,
            "candle_entry_trigger",
            _optional_decimal(self.candle_entry_trigger),
        )
        object.__setattr__(
            self,
            "candle_stop_level",
            _optional_decimal(self.candle_stop_level),
        )
        object.__setattr__(
            self,
            "candle_invalidation_level",
            _optional_decimal(self.candle_invalidation_level),
        )
        object.__setattr__(
            self,
            "candle_explanation",
            self.candle_explanation.strip(),
        )
        object.__setattr__(self, "setup_name", setup_name)
        object.__setattr__(self, "setup_category", setup_category)
        object.__setattr__(self, "setup_quality_label", setup_quality_label)
        object.__setattr__(
            self,
            "setup_confidence",
            _bounded_points(self.setup_confidence, "setup confidence"),
        )
        object.__setattr__(self, "setup_stage", setup_stage)
        object.__setattr__(
            self,
            "aggressive_entry",
            _optional_decimal(self.aggressive_entry),
        )
        object.__setattr__(
            self,
            "preferred_entry",
            _optional_decimal(self.preferred_entry),
        )
        object.__setattr__(
            self,
            "confirmation_entry",
            _optional_decimal(self.confirmation_entry),
        )
        object.__setattr__(
            self,
            "maximum_chase_price",
            _optional_decimal(self.maximum_chase_price),
        )
        object.__setattr__(
            self,
            "stop_chase_price",
            _optional_decimal(self.stop_chase_price),
        )
        object.__setattr__(
            self,
            "move_stop_to_breakeven",
            _optional_decimal(self.move_stop_to_breakeven),
        )
        object.__setattr__(self, "partial_exit", _optional_decimal(self.partial_exit))
        object.__setattr__(self, "atr_trail", atr_trail)
        object.__setattr__(self, "final_exit", _optional_decimal(self.final_exit))
        object.__setattr__(
            self,
            "setup_expectancy_status",
            setup_expectancy_status,
        )
        if self.minimum_holding_period is not None and self.minimum_holding_period < 0:
            raise ValueError("minimum holding period cannot be negative")
        if self.maximum_holding_period is not None and self.maximum_holding_period < 0:
            raise ValueError("maximum holding period cannot be negative")
        object.__setattr__(
            self,
            "expected_holding_period",
            expected_holding_period,
        )
        object.__setattr__(self, "holding_period_basis", holding_period_basis)
        object.__setattr__(self, "setup_rationale", setup_rationale)
        object.__setattr__(self, "setup_readiness_reason", setup_readiness_reason)
        object.__setattr__(self, "invalidation_reason", invalidation_reason)
        object.__setattr__(self, "retracement_zone", retracement_zone)
        object.__setattr__(self, "trailing_stop_strategy", trailing_stop_strategy)
        object.__setattr__(self, "trade_plan_explanation", trade_plan_explanation)


@dataclass(frozen=True, slots=True)
class PortfolioContext:
    existing_symbols: tuple[str, ...] = ()
    sector_exposure: Mapping[str, Decimal] = field(default_factory=dict)
    symbol_sector: Mapping[str, str] = field(default_factory=dict)
    max_single_position_percent: Decimal = Decimal("10")
    max_sector_exposure_percent: Decimal = Decimal("25")

    def __post_init__(self) -> None:
        existing_symbols = tuple(
            sorted(symbol.strip().upper() for symbol in self.existing_symbols)
        )
        if any(not symbol for symbol in existing_symbols):
            raise ValueError("existing symbols cannot be empty")

        sector_exposure: dict[str, Decimal] = {}
        for sector, exposure in self.sector_exposure.items():
            normalized_sector = sector.strip().upper()
            if not normalized_sector:
                raise ValueError("sector exposure key cannot be empty")
            sector_exposure[normalized_sector] = _as_decimal(exposure)

        symbol_sector: dict[str, str] = {}
        for symbol, sector in self.symbol_sector.items():
            normalized_symbol = symbol.strip().upper()
            normalized_sector = sector.strip().upper()
            if not normalized_symbol or not normalized_sector:
                raise ValueError("symbol sector keys and values cannot be empty")
            symbol_sector[normalized_symbol] = normalized_sector

        max_single = _as_decimal(self.max_single_position_percent)
        max_sector = _as_decimal(self.max_sector_exposure_percent)
        if max_single <= _ZERO:
            raise ValueError("max single position must be positive")
        if max_sector <= _ZERO:
            raise ValueError("max sector exposure must be positive")

        object.__setattr__(self, "existing_symbols", existing_symbols)
        object.__setattr__(
            self,
            "sector_exposure",
            MappingProxyType(dict(sorted(sector_exposure.items()))),
        )
        object.__setattr__(
            self,
            "symbol_sector",
            MappingProxyType(dict(sorted(symbol_sector.items()))),
        )
        object.__setattr__(self, "max_single_position_percent", max_single)
        object.__setattr__(self, "max_sector_exposure_percent", max_sector)


@dataclass(frozen=True, slots=True)
class RecommendationReport:
    symbol: str
    observed_on: date
    action: RecommendationAction
    decision: RecommendationDecision
    score: Decimal
    score_breakdown: RecommendationScoreBreakdown
    expected_value: ExpectedValueAssessment
    opportunity_cost: OpportunityCostAssessment
    allocation: AllocationAdjustment
    supporting_evidence: tuple[RecommendationEvidence, ...]
    opposing_evidence: tuple[RecommendationRisk, ...]
    explanation: tuple[str, ...]
    trade_plan: RecommendationTradePlan
    evidence_assessment: EvidenceAssessment
    trade_setup: TradeSetupAssessment
    trade_strategies: tuple[TradeStrategyPlaybook, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        explanation = tuple(line.strip() for line in self.explanation)
        metadata = _normalize_metadata(self.metadata)

        if not symbol:
            raise ValueError("recommendation report symbol cannot be empty")
        if any(not line for line in explanation):
            raise ValueError("recommendation explanation lines cannot be empty")
        trade_strategies = tuple(self.trade_strategies)

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "score", _bounded_points(self.score, "score"))
        object.__setattr__(self, "explanation", explanation)
        object.__setattr__(self, "trade_strategies", trade_strategies)
        object.__setattr__(self, "metadata", metadata)

    @property
    def final_signal(self) -> str:
        return self.trade_plan.final_signal

    @property
    def final_score(self) -> Decimal:
        return self.trade_plan.final_score

    @property
    def confidence(self) -> str:
        return self.trade_plan.confidence

    @property
    def trigger_status(self) -> TriggerStatus:
        return self.trade_plan.trigger_status

    @property
    def actionable_trade_strategy(self) -> TradeStrategyPlaybook | None:
        return next(
            (
                strategy
                for strategy in self.trade_strategies
                if strategy.action is TradeStrategyAction.BUY_NOW
            ),
            None,
        )

    @property
    def confidence_score(self) -> Decimal:
        return self.evidence_assessment.confidence_score

    @property
    def evidence_score(self) -> Decimal:
        return self.evidence_assessment.score

    @property
    def setup_quality(self) -> SetupQualityAssessment:
        return self.evidence_assessment.setup_quality

    @property
    def historical_expectancy(self) -> HistoricalExpectancy:
        return self.evidence_assessment.historical_expectancy

    @property
    def bullish_evidence(self) -> tuple[EvidenceSignal, ...]:
        return self.evidence_assessment.bullish_signals

    @property
    def bearish_evidence(self) -> tuple[EvidenceSignal, ...]:
        return self.evidence_assessment.bearish_signals

    @property
    def price_evidence(self) -> PriceEvidence:
        return self.evidence_assessment.price_evidence

    @property
    def volume_evidence(self) -> VolumeEvidence:
        return self.evidence_assessment.volume_evidence

    @property
    def candle_pattern(self) -> str:
        return self.trade_plan.candle_pattern

    @property
    def candle_score(self) -> Decimal:
        return self.trade_plan.candle_score

    @property
    def candle_weight(self) -> Decimal:
        return self.trade_plan.candle_weight

    @property
    def candle_confirmation(self) -> str:
        return self.trade_plan.candle_confirmation

    @property
    def candle_entry_trigger(self) -> Decimal | None:
        return self.trade_plan.candle_entry_trigger

    @property
    def candle_stop_level(self) -> Decimal | None:
        return self.trade_plan.candle_stop_level

    @property
    def candle_invalidation_level(self) -> Decimal | None:
        return self.trade_plan.candle_invalidation_level

    @property
    def candle_explanation(self) -> str:
        return self.trade_plan.candle_explanation

    @property
    def entry_price(self) -> Decimal | None:
        return self.trade_plan.entry_price

    @property
    def entry_zone_low(self) -> Decimal | None:
        return self.trade_plan.entry_zone_low

    @property
    def entry_zone_high(self) -> Decimal | None:
        return self.trade_plan.entry_zone_high

    @property
    def initial_stop_loss(self) -> Decimal | None:
        return self.trade_plan.initial_stop_loss

    @property
    def trailing_stop_strategy(self) -> str:
        return self.trade_plan.trailing_stop_strategy

    @property
    def target_1(self) -> Decimal | None:
        return self.trade_plan.target_1

    @property
    def target_2(self) -> Decimal | None:
        return self.trade_plan.target_2

    @property
    def target_3(self) -> Decimal | None:
        return self.trade_plan.target_3

    @property
    def risk_reward_ratio(self) -> Decimal | None:
        return self.trade_plan.risk_reward_ratio

    @property
    def current_market_price(self) -> Decimal | None:
        value = self.metadata.get("current_price") or self.metadata.get("price")
        if value is None:
            return None
        try:
            return _as_decimal(Decimal(str(value)))
        except Exception:
            return None

    @property
    def current_market_risk_reward_ratio(self) -> Decimal | None:
        if self.final_signal not in {"BUY", "STRONG_BUY", "WATCHLIST", "HOLD"}:
            return None
        current = self.current_market_price
        stop = self.initial_stop_loss
        target = self.target_1
        if current is None or stop is None or target is None:
            return None
        if current <= _ZERO or stop >= current or target <= current:
            return None
        risk = current - stop
        reward = target - current
        if risk <= _ZERO or reward <= _ZERO:
            return None
        return (reward / risk).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)

    @property
    def invalidation_level(self) -> Decimal | None:
        return self.trade_plan.invalidation_level

    @property
    def invalidation_reason(self) -> str:
        return self.trade_plan.invalidation_reason

    @property
    def retracement_score(self) -> Decimal:
        return self.trade_plan.retracement_score

    @property
    def retracement_weight(self) -> Decimal:
        return self.trade_plan.retracement_weight

    @property
    def retracement_zone(self) -> str:
        return self.trade_plan.retracement_zone

    @property
    def nearest_fibonacci_level(self) -> Decimal | None:
        return self.trade_plan.nearest_fibonacci_level

    @property
    def swing_high(self) -> Decimal | None:
        return self.trade_plan.swing_high

    @property
    def swing_low(self) -> Decimal | None:
        return self.trade_plan.swing_low

    @property
    def support_level_used(self) -> Decimal | None:
        return self.trade_plan.support_level_used

    @property
    def trade_plan_explanation(self) -> str:
        return self.trade_plan.trade_plan_explanation

    @property
    def dma_50(self) -> Decimal | None:
        return self.trade_plan.dma_50

    @property
    def dma_200(self) -> Decimal | None:
        return self.trade_plan.dma_200

    @property
    def relative_volume(self) -> Decimal | None:
        return self.trade_plan.relative_volume

    @property
    def historical_bar_count(self) -> int:
        return self.trade_plan.historical_bar_count

    @property
    def unavailable_reasons(self) -> tuple[str, ...]:
        return self.trade_plan.unavailable_reasons

    @property
    def setup_name(self) -> str:
        return self.trade_setup.setup_name

    @property
    def setup_category(self) -> str:
        return self.trade_setup.setup_category

    @property
    def setup_quality_label(self) -> str:
        return self.trade_setup.setup_quality

    @property
    def setup_confidence(self) -> Decimal:
        return self.trade_setup.setup_confidence

    @property
    def setup_stage(self) -> str:
        return self.trade_setup.setup_stage

    @property
    def setup_entry_ready(self) -> bool:
        return self.trade_setup.entry_ready


def _normalize_metadata(metadata: Mapping[str, str]) -> Mapping[str, str]:
    normalized = {
        key.strip(): value.strip()
        for key, value in metadata.items()
        if key.strip() and value.strip()
    }
    return MappingProxyType(dict(sorted(normalized.items())))


def _as_decimal(value: Decimal) -> Decimal:
    return Decimal(str(value))


def _bounded_ratio(value: Decimal, field_name: str) -> Decimal:
    score = _as_decimal(value)
    if score < _ZERO or score > _ONE:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return _quantize(score)


def _optional_bounded_ratio(value: Decimal | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _bounded_ratio(value, field_name)


def _optional_decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return _as_decimal(value)


def _bounded_points(value: Decimal, field_name: str) -> Decimal:
    score = _as_decimal(value)
    if score < _ZERO or score > _HUNDRED:
        raise ValueError(f"{field_name} must be between 0 and 100")
    return score.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _quantize(value: Decimal) -> Decimal:
    return _as_decimal(value).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)
