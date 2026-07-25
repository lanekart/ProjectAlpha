"""Immutable governed metric models shared by DSI diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class EvidenceStrengthLevel(StrEnum):
    """Governed qualitative evidence-strength classification."""

    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


@dataclass(frozen=True, slots=True)
class EconomicDistribution:
    """Resolved return distribution for one governed population."""

    sample_count: int
    resolved_count: int
    positive_count: int
    negative_count: int
    flat_count: int
    mean_return_pct: Decimal
    median_return_pct: Decimal
    best_return_pct: Decimal
    worst_return_pct: Decimal

    def __post_init__(self) -> None:
        _require_non_negative("sample_count", self.sample_count)
        _require_non_negative("resolved_count", self.resolved_count)
        _require_non_negative("positive_count", self.positive_count)
        _require_non_negative("negative_count", self.negative_count)
        _require_non_negative("flat_count", self.flat_count)

        if self.resolved_count > self.sample_count:
            raise ValueError("resolved_count cannot exceed sample_count")

        classified = self.positive_count + self.negative_count + self.flat_count
        if classified != self.resolved_count:
            raise ValueError(
                "positive_count + negative_count + flat_count must equal resolved_count"
            )

        if self.resolved_count == 0:
            zero_metrics = (
                self.mean_return_pct,
                self.median_return_pct,
                self.best_return_pct,
                self.worst_return_pct,
            )
            if any(value != Decimal("0") for value in zero_metrics):
                raise ValueError(
                    "empty resolved distribution must use zero-valued metrics"
                )

        if self.resolved_count > 0 and self.best_return_pct < self.worst_return_pct:
            raise ValueError("best_return_pct cannot be below worst_return_pct")


@dataclass(frozen=True, slots=True)
class EvidenceStrength:
    """Governed evidence sufficiency and qualitative strength."""

    sample_count: int
    resolved_count: int
    minimum_required: int
    level: EvidenceStrengthLevel
    sufficient: bool

    def __post_init__(self) -> None:
        _require_non_negative("sample_count", self.sample_count)
        _require_non_negative("resolved_count", self.resolved_count)
        _require_non_negative("minimum_required", self.minimum_required)

        if self.resolved_count > self.sample_count:
            raise ValueError("resolved_count cannot exceed sample_count")

        expected_sufficient = (
            self.resolved_count > 0 and self.resolved_count >= self.minimum_required
        )
        if self.sufficient is not expected_sufficient:
            raise ValueError(
                "sufficient must equal resolved_count > 0 and "
                "resolved_count >= minimum_required"
            )


@dataclass(frozen=True, slots=True)
class GateEconomicValue:
    """Economic accounting for a governed rejection gate."""

    profitable_rejection_cost: Decimal
    avoided_loss_benefit: Decimal
    net_gate_value: Decimal

    def __post_init__(self) -> None:
        if self.profitable_rejection_cost < Decimal("0"):
            raise ValueError("profitable_rejection_cost cannot be negative")

        if self.avoided_loss_benefit < Decimal("0"):
            raise ValueError("avoided_loss_benefit cannot be negative")

        expected_net = self.avoided_loss_benefit - self.profitable_rejection_cost
        if self.net_gate_value != expected_net:
            raise ValueError(
                "net_gate_value must equal "
                "avoided_loss_benefit - profitable_rejection_cost"
            )


@dataclass(frozen=True, slots=True)
class GateMetricSnapshot:
    """Complete immutable metric snapshot for one gate population."""

    gate_code: str
    distribution: EconomicDistribution
    evidence: EvidenceStrength
    economic_value: GateEconomicValue

    def __post_init__(self) -> None:
        if not self.gate_code.strip():
            raise ValueError("gate_code cannot be empty")

        if self.distribution.sample_count != self.evidence.sample_count:
            raise ValueError("distribution and evidence sample_count values must match")

        if self.distribution.resolved_count != self.evidence.resolved_count:
            raise ValueError(
                "distribution and evidence resolved_count values must match"
            )


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
