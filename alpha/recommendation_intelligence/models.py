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
    ACCUMULATE = "ACCUMULATE"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    AVOID = "AVOID"


class RecommendationDecision(StrEnum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    WATCHLIST = "WATCHLIST"
    HOLD = "HOLD"
    AVOID = "AVOID"


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


@dataclass(frozen=True, slots=True)
class RecommendationScoreBreakdown:
    strategy_points: Decimal
    probability_points: Decimal
    market_intelligence_points: Decimal
    liquidity_points: Decimal
    risk_points: Decimal
    portfolio_adjustment_points: Decimal
    opportunity_cost_points: Decimal

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
            + self.risk_points
            + self.portfolio_adjustment_points
            + self.opportunity_cost_points
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
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        explanation = tuple(line.strip() for line in self.explanation)
        metadata = _normalize_metadata(self.metadata)

        if not symbol:
            raise ValueError("recommendation report symbol cannot be empty")
        if any(not line for line in explanation):
            raise ValueError("recommendation explanation lines cannot be empty")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "score", _bounded_points(self.score, "score"))
        object.__setattr__(self, "explanation", explanation)
        object.__setattr__(self, "metadata", metadata)


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


def _bounded_points(value: Decimal, field_name: str) -> Decimal:
    score = _as_decimal(value)
    if score < _ZERO or score > _HUNDRED:
        raise ValueError(f"{field_name} must be between 0 and 100")
    return score.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _quantize(value: Decimal) -> Decimal:
    return _as_decimal(value).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)
