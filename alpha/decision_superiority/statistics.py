"""Deterministic governed statistics for decision-superiority diagnostics."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from statistics import median

from alpha.decision_superiority.metrics import (
    EconomicDistribution,
    EvidenceStrength,
    EvidenceStrengthLevel,
    GateEconomicValue,
)

VERY_HIGH_MINIMUM_RESOLVED = 100
HIGH_MINIMUM_RESOLVED = 50
MODERATE_MINIMUM_RESOLVED = 20
LOW_MINIMUM_RESOLVED = 10


def build_distribution(
    *,
    sample_count: int,
    returns_pct: list[Decimal],
) -> EconomicDistribution:
    """Build an immutable return distribution from resolved observations."""

    if sample_count < 0:
        raise ValueError("sample_count cannot be negative")

    resolved_returns = tuple(_decimal(value) for value in returns_pct)
    resolved_count = len(resolved_returns)

    if resolved_count > sample_count:
        raise ValueError("resolved return count cannot exceed sample_count")

    positive_count = sum(value > Decimal("0") for value in resolved_returns)
    negative_count = sum(value < Decimal("0") for value in resolved_returns)
    flat_count = resolved_count - positive_count - negative_count

    if not resolved_returns:
        return EconomicDistribution(
            sample_count=sample_count,
            resolved_count=0,
            positive_count=0,
            negative_count=0,
            flat_count=0,
            mean_return_pct=Decimal("0"),
            median_return_pct=Decimal("0"),
            best_return_pct=Decimal("0"),
            worst_return_pct=Decimal("0"),
        )

    return EconomicDistribution(
        sample_count=sample_count,
        resolved_count=resolved_count,
        positive_count=positive_count,
        negative_count=negative_count,
        flat_count=flat_count,
        mean_return_pct=sum(resolved_returns, Decimal("0")) / Decimal(resolved_count),
        median_return_pct=_median_decimal(resolved_returns),
        best_return_pct=max(resolved_returns),
        worst_return_pct=min(resolved_returns),
    )


def build_gate_value(
    *,
    returns_pct: list[Decimal],
) -> GateEconomicValue:
    """Build rejection opportunity-cost and avoided-loss accounting."""

    resolved_returns = tuple(_decimal(value) for value in returns_pct)

    profitable_rejection_cost = sum(
        (value for value in resolved_returns if value > Decimal("0")),
        Decimal("0"),
    )
    avoided_loss_benefit = sum(
        (abs(value) for value in resolved_returns if value < Decimal("0")),
        Decimal("0"),
    )

    return GateEconomicValue(
        profitable_rejection_cost=profitable_rejection_cost,
        avoided_loss_benefit=avoided_loss_benefit,
        net_gate_value=avoided_loss_benefit - profitable_rejection_cost,
    )


def build_evidence_strength(
    *,
    sample_count: int,
    resolved_count: int,
    minimum_required: int,
) -> EvidenceStrength:
    """Classify evidence strength without making a gate-value conclusion."""

    if sample_count < 0:
        raise ValueError("sample_count cannot be negative")

    if resolved_count < 0:
        raise ValueError("resolved_count cannot be negative")

    if minimum_required < 0:
        raise ValueError("minimum_required cannot be negative")

    if resolved_count > sample_count:
        raise ValueError("resolved_count cannot exceed sample_count")

    return EvidenceStrength(
        sample_count=sample_count,
        resolved_count=resolved_count,
        minimum_required=minimum_required,
        level=evidence_strength_level(resolved_count),
        sufficient=resolved_count >= minimum_required,
    )


def evidence_strength_level(resolved_count: int) -> EvidenceStrengthLevel:
    """Map resolved sample size to a deterministic qualitative level."""

    if resolved_count < 0:
        raise ValueError("resolved_count cannot be negative")

    if resolved_count >= VERY_HIGH_MINIMUM_RESOLVED:
        return EvidenceStrengthLevel.VERY_HIGH

    if resolved_count >= HIGH_MINIMUM_RESOLVED:
        return EvidenceStrengthLevel.HIGH

    if resolved_count >= MODERATE_MINIMUM_RESOLVED:
        return EvidenceStrengthLevel.MODERATE

    if resolved_count >= LOW_MINIMUM_RESOLVED:
        return EvidenceStrengthLevel.LOW

    return EvidenceStrengthLevel.VERY_LOW


def rank_gate_snapshots(
    rows: list[tuple[str, GateEconomicValue, EvidenceStrength]],
) -> tuple[tuple[str, GateEconomicValue, EvidenceStrength], ...]:
    """Rank gate metrics deterministically without asserting superiority."""

    return tuple(
        sorted(
            rows,
            key=lambda item: (
                -item[1].net_gate_value,
                -item[2].resolved_count,
                item[0],
            ),
        )
    )


def _median_decimal(values: tuple[Decimal, ...]) -> Decimal:
    result = median(values)
    return result if isinstance(result, Decimal) else Decimal(str(result))


def _decimal(value: Decimal | int | str) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal value: {value}") from exc
