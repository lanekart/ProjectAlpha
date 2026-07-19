from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType

_ZERO = Decimal("0")
_ONE = Decimal("1")
_FOUR = Decimal("0.0001")
_TWO = Decimal("0.01")


class EvidenceStrength(StrEnum):
    INSUFFICIENT = "insufficient"
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


@dataclass(frozen=True, slots=True)
class SetupFingerprint:
    final_verdict: str
    setup_type: str
    setup_state: str
    market_regime: str
    sector: str
    trend_regime: str
    volume_regime: str
    volatility_regime: str
    relative_strength_regime: str
    candle_pattern: str
    breakout_retracement_state: str
    dma_alignment: str
    data_completeness_level: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = str(getattr(self, field_name)).strip().upper()
            object.__setattr__(self, field_name, value or "UNKNOWN")

    @property
    def key(self) -> str:
        parts = (
            ("verdict", self.final_verdict),
            ("setup", self.setup_type),
            ("state", self.setup_state),
            ("regime", self.market_regime),
            ("sector", self.sector),
            ("trend", self.trend_regime),
            ("volume", self.volume_regime),
            ("volatility", self.volatility_regime),
            ("rs", self.relative_strength_regime),
            ("candle", self.candle_pattern),
            ("breakout", self.breakout_retracement_state),
            ("dma", self.dma_alignment),
            ("data", self.data_completeness_level),
        )
        return "|".join(f"{label}={value}" for label, value in parts)

    @property
    def dimensions(self) -> MappingProxyType[str, str]:
        return MappingProxyType(
            {
                "final_verdict": self.final_verdict,
                "setup_type": self.setup_type,
                "setup_state": self.setup_state,
                "market_regime": self.market_regime,
                "sector": self.sector,
                "trend_regime": self.trend_regime,
                "volume_regime": self.volume_regime,
                "volatility_regime": self.volatility_regime,
                "relative_strength_regime": self.relative_strength_regime,
                "candle_pattern": self.candle_pattern,
                "breakout_retracement_state": self.breakout_retracement_state,
                "dma_alignment": self.dma_alignment,
                "data_completeness_level": self.data_completeness_level,
            }
        )


@dataclass(frozen=True, slots=True)
class LearningOutcomeSample:
    fingerprint: SetupFingerprint
    completed: bool
    win: bool
    pending: bool
    not_triggered: bool
    target_1_hit: bool
    target_2_hit: bool
    target_3_hit: bool
    stop_hit: bool
    realized_r: Decimal | None
    holding_period_days: int | None
    max_drawdown_proxy: Decimal | None = None


@dataclass(frozen=True, slots=True)
class FingerprintStatistics:
    fingerprint: SetupFingerprint
    sample_count: int
    completed_trade_count: int
    win_count: int
    loss_count: int
    pending_count: int
    not_triggered_count: int
    target_1_hit_rate: Decimal | None
    target_2_hit_rate: Decimal | None
    target_3_hit_rate: Decimal | None
    stop_hit_rate: Decimal | None
    average_r: Decimal | None
    expectancy: Decimal | None
    average_holding_period: Decimal | None
    max_drawdown_proxy: Decimal | None
    evidence_strength: EvidenceStrength

    @property
    def insufficient(self) -> bool:
        return self.evidence_strength is EvidenceStrength.INSUFFICIENT


@dataclass(frozen=True, slots=True)
class BayesianCalibration:
    prior_win_probability: Decimal
    posterior_win_probability: Decimal
    lower_confidence_bound: Decimal
    upper_confidence_bound: Decimal
    evidence_strength: EvidenceStrength
    completed_samples: int
    alpha_prior: Decimal
    beta_prior: Decimal


@dataclass(frozen=True, slots=True)
class ConfidenceCalibration:
    base_confidence: str
    adjusted_confidence: str
    adjustment_reason: str
    evidence_sample_count: int
    uncertainty_penalty: Decimal


@dataclass(frozen=True, slots=True)
class FeatureContribution:
    dimension: str
    value: str
    sample_count: int
    average_expectancy: Decimal | None
    stop_hit_rate: Decimal | None
    target_hit_rate: Decimal | None
    direction: str


@dataclass(frozen=True, slots=True)
class AdaptiveLearningAssessment:
    fingerprint: SetupFingerprint
    statistics: FingerprintStatistics
    bayesian: BayesianCalibration
    confidence: ConfidenceCalibration


@dataclass(frozen=True, slots=True)
class AdaptiveLearningReport:
    total_completed_samples: int
    fingerprint_statistics: tuple[FingerprintStatistics, ...]
    strongest_fingerprints: tuple[FingerprintStatistics, ...]
    weakest_fingerprints: tuple[FingerprintStatistics, ...]
    sector_statistics: MappingProxyType[str, FingerprintStatistics]
    regime_statistics: MappingProxyType[str, FingerprintStatistics]
    confidence_statistics: MappingProxyType[str, FingerprintStatistics]
    feature_contributions: tuple[FeatureContribution, ...]
    insufficient_sample_warnings: tuple[str, ...]


def evidence_strength(completed_samples: int) -> EvidenceStrength:
    if completed_samples < 5:
        return EvidenceStrength.INSUFFICIENT
    if completed_samples < 15:
        return EvidenceStrength.WEAK
    if completed_samples < 30:
        return EvidenceStrength.MODERATE
    return EvidenceStrength.STRONG


def rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _FOUR,
        rounding=ROUND_HALF_UP,
    )


def average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def bounded_probability(value: Decimal) -> Decimal:
    return min(max(value, _ZERO), _ONE).quantize(_FOUR, rounding=ROUND_HALF_UP)


__all__ = [
    "AdaptiveLearningAssessment",
    "AdaptiveLearningReport",
    "BayesianCalibration",
    "ConfidenceCalibration",
    "EvidenceStrength",
    "FeatureContribution",
    "FingerprintStatistics",
    "LearningOutcomeSample",
    "SetupFingerprint",
    "average",
    "bounded_probability",
    "evidence_strength",
    "rate",
]
