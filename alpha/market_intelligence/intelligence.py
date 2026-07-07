from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_FOUR_PLACES = Decimal("0.0001")
_TWO_PLACES = Decimal("0.01")


class IntelligenceBias(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


class AccumulationPhase(StrEnum):
    STRONG_ACCUMULATION = "STRONG_ACCUMULATION"
    MODERATE_ACCUMULATION = "MODERATE_ACCUMULATION"
    NO_ACCUMULATION = "NO_ACCUMULATION"


class DistributionPhase(StrEnum):
    STRONG_DISTRIBUTION = "STRONG_DISTRIBUTION"
    MODERATE_DISTRIBUTION = "MODERATE_DISTRIBUTION"
    NO_DISTRIBUTION = "NO_DISTRIBUTION"


class LiquidityQuality(StrEnum):
    HIGH = "HIGH"
    ACCEPTABLE = "ACCEPTABLE"
    THIN = "THIN"


class BreadthCondition(StrEnum):
    BROAD_PARTICIPATION = "BROAD_PARTICIPATION"
    SELECTIVE_PARTICIPATION = "SELECTIVE_PARTICIPATION"
    WEAK_PARTICIPATION = "WEAK_PARTICIPATION"


class SectorRotationPhase(StrEnum):
    LEADERSHIP_EXPANSION = "LEADERSHIP_EXPANSION"
    SELECTIVE_LEADERSHIP = "SELECTIVE_LEADERSHIP"
    LEADERSHIP_CONTRACTION = "LEADERSHIP_CONTRACTION"


class CorrelationRisk(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class StockIntelligenceInput:
    symbol: str
    observed_on: date
    price_change_percent: Decimal
    delivery_percent: Decimal
    delivery_change_percent: Decimal
    volume_change_percent: Decimal
    turnover_value: Decimal
    average_turnover_value: Decimal
    spread_percent: Decimal
    volatility_percent: Decimal

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("stock intelligence symbol cannot be empty")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "price_change_percent",
            Decimal(str(self.price_change_percent)),
        )
        object.__setattr__(
            self,
            "delivery_percent",
            _bounded_percent(self.delivery_percent, "delivery_percent"),
        )
        object.__setattr__(
            self,
            "delivery_change_percent",
            Decimal(str(self.delivery_change_percent)),
        )
        object.__setattr__(
            self,
            "volume_change_percent",
            Decimal(str(self.volume_change_percent)),
        )
        object.__setattr__(
            self,
            "turnover_value",
            _non_negative(self.turnover_value, "turnover_value"),
        )
        object.__setattr__(
            self,
            "average_turnover_value",
            _non_negative(self.average_turnover_value, "average_turnover_value"),
        )
        object.__setattr__(
            self,
            "spread_percent",
            _non_negative(self.spread_percent, "spread_percent"),
        )
        object.__setattr__(
            self,
            "volatility_percent",
            _non_negative(self.volatility_percent, "volatility_percent"),
        )


@dataclass(frozen=True, slots=True)
class MarketBreadthInput:
    observed_on: date
    advances: int
    declines: int
    unchanged: int = 0

    def __post_init__(self) -> None:
        if self.advances < 0:
            raise ValueError("advances cannot be negative")
        if self.declines < 0:
            raise ValueError("declines cannot be negative")
        if self.unchanged < 0:
            raise ValueError("unchanged cannot be negative")
        if self.total_count <= 0:
            raise ValueError("market breadth requires at least one constituent")

    @property
    def total_count(self) -> int:
        return self.advances + self.declines + self.unchanged


@dataclass(frozen=True, slots=True)
class SectorPerformanceInput:
    sector: str
    return_percent: Decimal
    breadth_percent: Decimal
    turnover_change_percent: Decimal

    def __post_init__(self) -> None:
        sector = self.sector.strip().upper()
        if not sector:
            raise ValueError("sector cannot be empty")
        object.__setattr__(self, "sector", sector)
        object.__setattr__(
            self,
            "return_percent",
            Decimal(str(self.return_percent)),
        )
        object.__setattr__(
            self,
            "breadth_percent",
            _bounded_percent(self.breadth_percent, "breadth_percent"),
        )
        object.__setattr__(
            self,
            "turnover_change_percent",
            Decimal(str(self.turnover_change_percent)),
        )


@dataclass(frozen=True, slots=True)
class CorrelationInput:
    symbol: str
    correlation_to_index: Decimal
    correlation_to_sector: Decimal

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("correlation symbol cannot be empty")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "correlation_to_index",
            _bounded_correlation(self.correlation_to_index, "correlation_to_index"),
        )
        object.__setattr__(
            self,
            "correlation_to_sector",
            _bounded_correlation(self.correlation_to_sector, "correlation_to_sector"),
        )


@dataclass(frozen=True, slots=True)
class IntelligenceAssessment:
    name: str
    score: Decimal
    bias: IntelligenceBias
    classification: str
    reasons: tuple[str, ...]
    metrics: Mapping[str, Decimal] = MappingProxyType({})

    def __post_init__(self) -> None:
        name = self.name.strip()
        classification = self.classification.strip().upper()
        reasons = tuple(reason.strip() for reason in self.reasons)
        metrics = MappingProxyType(
            dict(
                sorted(
                    (key.strip(), Decimal(str(value)))
                    for key, value in self.metrics.items()
                )
            )
        )

        if not name:
            raise ValueError("assessment name cannot be empty")
        if not classification:
            raise ValueError("assessment classification cannot be empty")
        if any(not reason for reason in reasons):
            raise ValueError("assessment reasons cannot be empty")
        if any(not key for key in metrics):
            raise ValueError("assessment metric names cannot be empty")

        object.__setattr__(self, "name", name)
        object.__setattr__(
            self,
            "score",
            _bounded_score(self.score, "assessment score"),
        )
        object.__setattr__(self, "classification", classification)
        object.__setattr__(self, "reasons", reasons)
        object.__setattr__(self, "metrics", metrics)


@dataclass(frozen=True, slots=True)
class SectorLeadership:
    sector: str
    score: Decimal
    rank: int
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        sector = self.sector.strip().upper()
        reasons = tuple(reason.strip() for reason in self.reasons)
        if not sector:
            raise ValueError("sector leadership sector cannot be empty")
        if self.rank <= 0:
            raise ValueError("sector leadership rank must be positive")
        if any(not reason for reason in reasons):
            raise ValueError("sector leadership reasons cannot be empty")
        object.__setattr__(self, "sector", sector)
        object.__setattr__(self, "score", _bounded_score(self.score, "sector score"))
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class SectorRotationAssessment:
    phase: SectorRotationPhase
    leaders: tuple[SectorLeadership, ...]
    score: Decimal
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        reasons = tuple(reason.strip() for reason in self.reasons)
        if not self.leaders:
            raise ValueError("sector rotation requires at least one sector")
        if any(not reason for reason in reasons):
            raise ValueError("sector rotation reasons cannot be empty")
        object.__setattr__(self, "score", _bounded_score(self.score, "rotation score"))
        object.__setattr__(self, "reasons", reasons)

    @property
    def top_sector(self) -> SectorLeadership:
        return self.leaders[0]


@dataclass(frozen=True, slots=True)
class MarketIntelligenceReport:
    symbol: str
    observed_on: date
    accumulation: IntelligenceAssessment
    distribution: IntelligenceAssessment
    liquidity: IntelligenceAssessment
    breadth: IntelligenceAssessment
    sector_rotation: SectorRotationAssessment
    correlation: IntelligenceAssessment
    composite_score: Decimal
    bias: IntelligenceBias
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        reasons = tuple(reason.strip() for reason in self.reasons)
        if not symbol:
            raise ValueError("market intelligence report symbol cannot be empty")
        if any(not reason for reason in reasons):
            raise ValueError("market intelligence report reasons cannot be empty")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "composite_score",
            _bounded_score(self.composite_score, "composite score"),
        )
        object.__setattr__(self, "reasons", reasons)

    @property
    def is_constructive(self) -> bool:
        return self.bias is IntelligenceBias.POSITIVE

    @property
    def has_elevated_risk(self) -> bool:
        return self.bias is IntelligenceBias.NEGATIVE


class InstitutionalAccumulationEngine:
    def assess(self, data: StockIntelligenceInput) -> IntelligenceAssessment:
        score = _weighted_score(
            (
                (data.delivery_percent / _HUNDRED, Decimal("0.45")),
                (
                    _positive_percent_score(data.delivery_change_percent),
                    Decimal("0.30"),
                ),
                (_positive_percent_score(data.price_change_percent), Decimal("0.15")),
                (_positive_percent_score(data.volume_change_percent), Decimal("0.10")),
            )
        )
        classification = AccumulationPhase.NO_ACCUMULATION
        bias = IntelligenceBias.NEUTRAL
        if score >= Decimal("0.70"):
            classification = AccumulationPhase.STRONG_ACCUMULATION
            bias = IntelligenceBias.POSITIVE
        elif score >= Decimal("0.50"):
            classification = AccumulationPhase.MODERATE_ACCUMULATION
            bias = IntelligenceBias.POSITIVE

        return IntelligenceAssessment(
            name="Institutional Accumulation",
            score=score,
            bias=bias,
            classification=classification.value,
            reasons=(
                f"delivery percent: {_format_decimal(data.delivery_percent)}",
                (
                    "delivery change percent: "
                    f"{_format_decimal(data.delivery_change_percent)}"
                ),
                f"price change percent: {_format_decimal(data.price_change_percent)}",
                f"volume change percent: {_format_decimal(data.volume_change_percent)}",
            ),
            metrics={
                "delivery_percent": data.delivery_percent,
                "delivery_change_percent": data.delivery_change_percent,
                "price_change_percent": data.price_change_percent,
                "volume_change_percent": data.volume_change_percent,
            },
        )


class DistributionEngine:
    def assess(self, data: StockIntelligenceInput) -> IntelligenceAssessment:
        score = _weighted_score(
            (
                (data.delivery_percent / _HUNDRED, Decimal("0.35")),
                (_positive_percent_score(-data.price_change_percent), Decimal("0.30")),
                (_positive_percent_score(data.volume_change_percent), Decimal("0.25")),
                (
                    _positive_percent_score(data.delivery_change_percent),
                    Decimal("0.10"),
                ),
            )
        )
        classification = DistributionPhase.NO_DISTRIBUTION
        bias = IntelligenceBias.NEUTRAL
        if score >= Decimal("0.60"):
            classification = DistributionPhase.STRONG_DISTRIBUTION
            bias = IntelligenceBias.NEGATIVE
        elif score >= Decimal("0.45"):
            classification = DistributionPhase.MODERATE_DISTRIBUTION
            bias = IntelligenceBias.NEGATIVE

        return IntelligenceAssessment(
            name="Distribution Pressure",
            score=score,
            bias=bias,
            classification=classification.value,
            reasons=(
                f"delivery percent: {_format_decimal(data.delivery_percent)}",
                (
                    "price weakness percent: "
                    f"{_format_decimal(-data.price_change_percent)}"
                ),
                f"volume change percent: {_format_decimal(data.volume_change_percent)}",
            ),
            metrics={
                "delivery_percent": data.delivery_percent,
                "price_weakness_percent": -data.price_change_percent,
                "volume_change_percent": data.volume_change_percent,
            },
        )


class LiquidityIntelligenceEngine:
    def assess(self, data: StockIntelligenceInput) -> IntelligenceAssessment:
        turnover_score = _turnover_score(
            turnover_value=data.turnover_value,
            average_turnover_value=data.average_turnover_value,
        )
        spread_score = _ONE - min(data.spread_percent / Decimal("2"), _ONE)
        volatility_penalty = min(data.volatility_percent / Decimal("12"), _ONE)
        score = _bounded_score(
            turnover_score * Decimal("0.55")
            + spread_score * Decimal("0.30")
            + (_ONE - volatility_penalty) * Decimal("0.15"),
            "liquidity score",
        )

        quality = LiquidityQuality.THIN
        bias = IntelligenceBias.NEGATIVE
        if score >= Decimal("0.70"):
            quality = LiquidityQuality.HIGH
            bias = IntelligenceBias.POSITIVE
        elif score >= Decimal("0.45"):
            quality = LiquidityQuality.ACCEPTABLE
            bias = IntelligenceBias.NEUTRAL

        return IntelligenceAssessment(
            name="Liquidity Intelligence",
            score=score,
            bias=bias,
            classification=quality.value,
            reasons=(
                f"turnover value: {_format_decimal(data.turnover_value)}",
                (
                    "average turnover value: "
                    f"{_format_decimal(data.average_turnover_value)}"
                ),
                f"spread percent: {_format_decimal(data.spread_percent)}",
                f"volatility percent: {_format_decimal(data.volatility_percent)}",
            ),
            metrics={
                "turnover_score": turnover_score,
                "spread_score": spread_score,
                "volatility_penalty": volatility_penalty,
            },
        )


class MarketBreadthEngine:
    def assess(self, data: MarketBreadthInput) -> IntelligenceAssessment:
        advance_ratio = Decimal(data.advances) / Decimal(data.total_count)
        decline_ratio = Decimal(data.declines) / Decimal(data.total_count)
        score = _bounded_score(advance_ratio, "breadth score")

        condition = BreadthCondition.WEAK_PARTICIPATION
        bias = IntelligenceBias.NEGATIVE
        if score >= Decimal("0.60"):
            condition = BreadthCondition.BROAD_PARTICIPATION
            bias = IntelligenceBias.POSITIVE
        elif score >= Decimal("0.45"):
            condition = BreadthCondition.SELECTIVE_PARTICIPATION
            bias = IntelligenceBias.NEUTRAL

        return IntelligenceAssessment(
            name="Market Breadth",
            score=score,
            bias=bias,
            classification=condition.value,
            reasons=(
                f"advances: {data.advances}",
                f"declines: {data.declines}",
                f"unchanged: {data.unchanged}",
            ),
            metrics={
                "advance_ratio": advance_ratio,
                "decline_ratio": decline_ratio,
            },
        )


class SectorRotationEngine:
    def assess(
        self,
        sectors: Iterable[SectorPerformanceInput],
    ) -> SectorRotationAssessment:
        inputs = tuple(sectors)
        if not inputs:
            raise ValueError("sector rotation requires at least one sector")

        scored = tuple(
            sorted(
                (
                    SectorLeadership(
                        sector=item.sector,
                        score=self._sector_score(item),
                        rank=index + 1,
                        reasons=(
                            f"return percent: {_format_decimal(item.return_percent)}",
                            f"breadth percent: {_format_decimal(item.breadth_percent)}",
                            (
                                "turnover change percent: "
                                f"{_format_decimal(item.turnover_change_percent)}"
                            ),
                        ),
                    )
                    for index, item in enumerate(
                        sorted(
                            inputs,
                            key=lambda sector: self._sector_score(sector),
                            reverse=True,
                        )
                    )
                ),
                key=lambda leadership: leadership.rank,
            )
        )
        average_score = sum(
            (item.score for item in scored),
            _ZERO,
        ) / Decimal(len(scored))
        leader_count = sum(1 for item in scored if item.score >= Decimal("0.60"))
        participation = Decimal(leader_count) / Decimal(len(scored))

        phase = SectorRotationPhase.LEADERSHIP_CONTRACTION
        if participation >= Decimal("0.50"):
            phase = SectorRotationPhase.LEADERSHIP_EXPANSION
        elif participation > _ZERO:
            phase = SectorRotationPhase.SELECTIVE_LEADERSHIP

        return SectorRotationAssessment(
            phase=phase,
            leaders=scored,
            score=_bounded_score(average_score, "sector rotation score"),
            reasons=(
                f"leader count: {leader_count}",
                f"sector count: {len(scored)}",
                f"top sector: {scored[0].sector}",
            ),
        )

    def _sector_score(self, sector: SectorPerformanceInput) -> Decimal:
        return _weighted_score(
            (
                (_positive_percent_score(sector.return_percent), Decimal("0.45")),
                (sector.breadth_percent / _HUNDRED, Decimal("0.35")),
                (
                    _positive_percent_score(sector.turnover_change_percent),
                    Decimal("0.20"),
                ),
            )
        )


class CorrelationRiskEngine:
    def assess(self, data: CorrelationInput) -> IntelligenceAssessment:
        average_correlation = (
            abs(data.correlation_to_index) + abs(data.correlation_to_sector)
        ) / Decimal("2")
        diversification_score = _ONE - average_correlation

        risk = CorrelationRisk.LOW
        bias = IntelligenceBias.POSITIVE
        if average_correlation >= Decimal("0.80"):
            risk = CorrelationRisk.HIGH
            bias = IntelligenceBias.NEGATIVE
        elif average_correlation >= Decimal("0.60"):
            risk = CorrelationRisk.MODERATE
            bias = IntelligenceBias.NEUTRAL

        return IntelligenceAssessment(
            name="Correlation Risk",
            score=_bounded_score(diversification_score, "correlation score"),
            bias=bias,
            classification=risk.value,
            reasons=(
                f"index correlation: {_format_decimal(data.correlation_to_index)}",
                f"sector correlation: {_format_decimal(data.correlation_to_sector)}",
                f"average absolute correlation: {_format_decimal(average_correlation)}",
            ),
            metrics={
                "average_correlation": average_correlation,
                "diversification_score": diversification_score,
            },
        )


class MarketIntelligenceCompositeEngine:
    def __init__(
        self,
        accumulation_engine: InstitutionalAccumulationEngine | None = None,
        distribution_engine: DistributionEngine | None = None,
        liquidity_engine: LiquidityIntelligenceEngine | None = None,
        breadth_engine: MarketBreadthEngine | None = None,
        sector_rotation_engine: SectorRotationEngine | None = None,
        correlation_engine: CorrelationRiskEngine | None = None,
    ) -> None:
        self._accumulation_engine = (
            accumulation_engine or InstitutionalAccumulationEngine()
        )
        self._distribution_engine = distribution_engine or DistributionEngine()
        self._liquidity_engine = liquidity_engine or LiquidityIntelligenceEngine()
        self._breadth_engine = breadth_engine or MarketBreadthEngine()
        self._sector_rotation_engine = sector_rotation_engine or SectorRotationEngine()
        self._correlation_engine = correlation_engine or CorrelationRiskEngine()

    def assess(
        self,
        *,
        stock: StockIntelligenceInput,
        breadth: MarketBreadthInput,
        sectors: Iterable[SectorPerformanceInput],
        correlation: CorrelationInput,
    ) -> MarketIntelligenceReport:
        accumulation = self._accumulation_engine.assess(stock)
        distribution = self._distribution_engine.assess(stock)
        liquidity = self._liquidity_engine.assess(stock)
        breadth_assessment = self._breadth_engine.assess(breadth)
        sector_rotation = self._sector_rotation_engine.assess(sectors)
        correlation_assessment = self._correlation_engine.assess(correlation)

        composite_score = _bounded_score(
            accumulation.score * Decimal("0.25")
            + (_ONE - distribution.score) * Decimal("0.20")
            + liquidity.score * Decimal("0.15")
            + breadth_assessment.score * Decimal("0.15")
            + sector_rotation.score * Decimal("0.15")
            + correlation_assessment.score * Decimal("0.10"),
            "market intelligence composite score",
        )
        bias = IntelligenceBias.NEUTRAL
        if composite_score >= Decimal("0.60"):
            bias = IntelligenceBias.POSITIVE
        elif composite_score <= Decimal("0.40"):
            bias = IntelligenceBias.NEGATIVE

        return MarketIntelligenceReport(
            symbol=stock.symbol,
            observed_on=stock.observed_on,
            accumulation=accumulation,
            distribution=distribution,
            liquidity=liquidity,
            breadth=breadth_assessment,
            sector_rotation=sector_rotation,
            correlation=correlation_assessment,
            composite_score=composite_score,
            bias=bias,
            reasons=(
                f"accumulation: {accumulation.classification}",
                f"distribution: {distribution.classification}",
                f"liquidity: {liquidity.classification}",
                f"breadth: {breadth_assessment.classification}",
                f"sector rotation: {sector_rotation.phase.value}",
                f"correlation risk: {correlation_assessment.classification}",
            ),
        )


def _weighted_score(values: Iterable[tuple[Decimal, Decimal]]) -> Decimal:
    total = sum((value * weight for value, weight in values), _ZERO)
    return _bounded_score(total, "weighted score")


def _turnover_score(
    *,
    turnover_value: Decimal,
    average_turnover_value: Decimal,
) -> Decimal:
    if average_turnover_value <= _ZERO:
        if turnover_value <= _ZERO:
            return _ZERO
        return _ONE
    return min(turnover_value / average_turnover_value, _ONE)


def _positive_percent_score(value: Decimal) -> Decimal:
    normalized = Decimal(str(value))
    if normalized <= _ZERO:
        return _ZERO
    return min(normalized / Decimal("20"), _ONE)


def _bounded_score(value: Decimal, label: str) -> Decimal:
    normalized = Decimal(str(value)).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)
    if normalized < _ZERO or normalized > _ONE:
        raise ValueError(f"{label} must be between 0 and 1")
    return normalized


def _bounded_percent(value: Decimal, label: str) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < _ZERO or normalized > _HUNDRED:
        raise ValueError(f"{label} must be between 0 and 100")
    return normalized


def _bounded_correlation(value: Decimal, label: str) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < Decimal("-1") or normalized > _ONE:
        raise ValueError(f"{label} must be between -1 and 1")
    return normalized


def _non_negative(value: Decimal, label: str) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < _ZERO:
        raise ValueError(f"{label} cannot be negative")
    return normalized


def _format_decimal(value: Decimal) -> str:
    return str(Decimal(str(value)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))


__all__ = [
    "AccumulationPhase",
    "BreadthCondition",
    "CorrelationInput",
    "CorrelationRisk",
    "CorrelationRiskEngine",
    "DistributionEngine",
    "DistributionPhase",
    "InstitutionalAccumulationEngine",
    "IntelligenceAssessment",
    "IntelligenceBias",
    "LiquidityIntelligenceEngine",
    "LiquidityQuality",
    "MarketBreadthEngine",
    "MarketBreadthInput",
    "MarketIntelligenceCompositeEngine",
    "MarketIntelligenceReport",
    "SectorLeadership",
    "SectorPerformanceInput",
    "SectorRotationAssessment",
    "SectorRotationEngine",
    "SectorRotationPhase",
    "StockIntelligenceInput",
]
