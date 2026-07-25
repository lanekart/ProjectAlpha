"""Governed uncertainty calculations for decision-superiority diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum

from alpha.decision_superiority.metrics import EvidenceStrengthLevel
from alpha.decision_superiority.statistics import evidence_strength_level

DEFAULT_MINIMUM_RESOLVED = 20
Z_95 = Decimal("1.959963984540054")


class ConfidenceStatus(StrEnum):
    """Governed confidence-assessment status."""

    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class DecimalInterval:
    """Closed deterministic decimal interval."""

    lower: Decimal
    upper: Decimal
    confidence_level: Decimal
    method: str

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            raise ValueError("interval lower bound cannot exceed upper bound")
        if not Decimal("0") < self.confidence_level < Decimal("1"):
            raise ValueError("confidence_level must be between zero and one")
        if not self.method.strip():
            raise ValueError("interval method cannot be empty")


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    """Governed uncertainty assessment for one resolved population."""

    sample_count: int
    resolved_count: int
    minimum_required: int
    positive_count: int
    mean_return_pct: Decimal
    variance_return_pct: Decimal
    standard_deviation_return_pct: Decimal
    success_rate: Decimal | None
    success_rate_interval: DecimalInterval | None
    mean_return_interval: DecimalInterval | None
    evidence_strength: EvidenceStrengthLevel
    status: ConfidenceStatus
    insufficiency_reason: str

    def __post_init__(self) -> None:
        for name, value in (
            ("sample_count", self.sample_count),
            ("resolved_count", self.resolved_count),
            ("minimum_required", self.minimum_required),
            ("positive_count", self.positive_count),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.resolved_count > self.sample_count:
            raise ValueError("resolved_count cannot exceed sample_count")
        if self.positive_count > self.resolved_count:
            raise ValueError("positive_count cannot exceed resolved_count")
        sufficient = (
            self.resolved_count > 0 and self.resolved_count >= self.minimum_required
        )
        if sufficient and self.status is not ConfidenceStatus.SUFFICIENT:
            raise ValueError("sufficient population must use SUFFICIENT status")
        if not sufficient and self.status is ConfidenceStatus.SUFFICIENT:
            raise ValueError("insufficient population cannot use SUFFICIENT status")
        if self.status is ConfidenceStatus.SUFFICIENT and self.insufficiency_reason:
            raise ValueError(
                "sufficient assessment cannot include an insufficiency reason"
            )
        if self.status is not ConfidenceStatus.SUFFICIENT:
            if not self.insufficiency_reason:
                raise ValueError(
                    "non-sufficient assessment requires an insufficiency reason"
                )
        if self.resolved_count == 0:
            if self.success_rate is not None:
                raise ValueError("empty population cannot have a success rate")
            if self.success_rate_interval is not None:
                raise ValueError("empty population cannot have a success-rate interval")
            if self.mean_return_interval is not None:
                raise ValueError("empty population cannot have a mean-return interval")


def assess_evidence(
    *,
    sample_count: int,
    returns_pct: list[Decimal],
    minimum_required: int = DEFAULT_MINIMUM_RESOLVED,
    empty_reason: str = "NO_RESOLVED_OUTCOMES",
) -> EvidenceAssessment:
    """Assess sample sufficiency, dispersion, and deterministic 95% intervals."""

    if sample_count < 0:
        raise ValueError("sample_count cannot be negative")
    if minimum_required < 0:
        raise ValueError("minimum_required cannot be negative")
    if not empty_reason.strip():
        raise ValueError("empty_reason cannot be empty")

    returns = tuple(_decimal(value) for value in returns_pct)
    resolved_count = len(returns)
    if resolved_count > sample_count:
        raise ValueError("resolved return count cannot exceed sample_count")

    if not returns:
        return EvidenceAssessment(
            sample_count=sample_count,
            resolved_count=0,
            minimum_required=minimum_required,
            positive_count=0,
            mean_return_pct=Decimal("0"),
            variance_return_pct=Decimal("0"),
            standard_deviation_return_pct=Decimal("0"),
            success_rate=None,
            success_rate_interval=None,
            mean_return_interval=None,
            evidence_strength=EvidenceStrengthLevel.VERY_LOW,
            status=ConfidenceStatus.UNAVAILABLE,
            insufficiency_reason=empty_reason,
        )

    positive_count = sum(value > Decimal("0") for value in returns)
    mean = sum(returns, Decimal("0")) / Decimal(resolved_count)
    variance = sample_variance(returns)
    standard_deviation = _sqrt(variance)
    success_rate = Decimal(positive_count) / Decimal(resolved_count)
    success_interval = wilson_interval(
        positive_count=positive_count,
        resolved_count=resolved_count,
    )
    mean_interval = mean_confidence_interval(
        mean=mean,
        standard_deviation=standard_deviation,
        resolved_count=resolved_count,
    )
    sufficient = resolved_count >= minimum_required
    return EvidenceAssessment(
        sample_count=sample_count,
        resolved_count=resolved_count,
        minimum_required=minimum_required,
        positive_count=positive_count,
        mean_return_pct=mean,
        variance_return_pct=variance,
        standard_deviation_return_pct=standard_deviation,
        success_rate=success_rate,
        success_rate_interval=success_interval,
        mean_return_interval=mean_interval,
        evidence_strength=evidence_strength_level(resolved_count),
        status=(
            ConfidenceStatus.SUFFICIENT
            if sufficient
            else ConfidenceStatus.INSUFFICIENT_SAMPLE
        ),
        insufficiency_reason=(
            ""
            if sufficient
            else f"RESOLVED_OUTCOMES_BELOW_MINIMUM:{resolved_count}<{minimum_required}"
        ),
    )


def sample_variance(values: tuple[Decimal, ...]) -> Decimal:
    """Return deterministic sample variance using an n-1 denominator."""
    if not values or len(values) == 1:
        return Decimal("0")
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    squared_deviations = sum(
        ((value - mean) ** 2 for value in values),
        Decimal("0"),
    )
    return squared_deviations / Decimal(len(values) - 1)


def wilson_interval(
    *,
    positive_count: int,
    resolved_count: int,
) -> DecimalInterval | None:
    """Return a 95% Wilson score interval for the positive-outcome rate."""
    if resolved_count < 0:
        raise ValueError("resolved_count cannot be negative")
    if positive_count < 0:
        raise ValueError("positive_count cannot be negative")
    if positive_count > resolved_count:
        raise ValueError("positive_count cannot exceed resolved_count")
    if resolved_count == 0:
        return None
    n = Decimal(resolved_count)
    proportion = Decimal(positive_count) / n
    z_squared = Z_95**2
    denominator = Decimal("1") + z_squared / n
    center = (proportion + z_squared / (Decimal("2") * n)) / denominator
    margin = (
        Z_95
        * _sqrt(
            proportion * (Decimal("1") - proportion) / n
            + z_squared / (Decimal("4") * n**2)
        )
        / denominator
    )
    return DecimalInterval(
        lower=max(Decimal("0"), center - margin),
        upper=min(Decimal("1"), center + margin),
        confidence_level=Decimal("0.95"),
        method="WILSON_SCORE",
    )


def mean_confidence_interval(
    *,
    mean: Decimal,
    standard_deviation: Decimal,
    resolved_count: int,
) -> DecimalInterval | None:
    """Return a deterministic normal-approximation interval for mean return."""
    if resolved_count < 0:
        raise ValueError("resolved_count cannot be negative")
    if standard_deviation < Decimal("0"):
        raise ValueError("standard_deviation cannot be negative")
    if resolved_count == 0:
        return None
    standard_error = standard_deviation / _sqrt(Decimal(resolved_count))
    margin = Z_95 * standard_error
    return DecimalInterval(
        lower=mean - margin,
        upper=mean + margin,
        confidence_level=Decimal("0.95"),
        method="NORMAL_APPROXIMATION",
    )


def _sqrt(value: Decimal) -> Decimal:
    if value < Decimal("0"):
        raise ValueError("cannot take square root of a negative value")
    with localcontext() as context:
        context.prec = 50
        return value.sqrt()


def _decimal(value: Decimal | int | str) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal value: {value}") from exc
