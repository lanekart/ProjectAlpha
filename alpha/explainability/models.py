from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class ConfidenceLevel(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class ExplainabilityBullet:
    """A single deterministic explanation point."""

    label: str
    detail: str
    score: Decimal | None = None

    def __post_init__(self) -> None:
        label = self.label.strip()
        detail = self.detail.strip()

        if not label:
            raise ValueError("explainability bullet label cannot be empty")
        if not detail:
            raise ValueError("explainability bullet detail cannot be empty")

        object.__setattr__(self, "label", label)
        object.__setattr__(self, "detail", detail)

        if self.score is not None:
            object.__setattr__(self, "score", Decimal(str(self.score)))

    def as_dict(self) -> dict[str, str]:
        payload = {
            "label": self.label,
            "detail": self.detail,
        }
        if self.score is not None:
            payload["score"] = str(self.score)
        return payload


@dataclass(frozen=True, slots=True)
class ExplainabilitySection:
    """A deterministic section of an explainability report."""

    title: str
    bullets: tuple[ExplainabilityBullet, ...] = ()

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title:
            raise ValueError("explainability section title cannot be empty")

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "bullets", tuple(self.bullets))

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "bullets": [bullet.as_dict() for bullet in self.bullets],
        }


@dataclass(frozen=True, slots=True)
class RecommendationExplanation:
    """Structured explanation for one recommendation."""

    symbol: str
    decision: str
    action: str
    confidence: ConfidenceLevel
    score: Decimal
    allocation_decision: str
    allocation_weight: Decimal
    primary_drivers: tuple[ExplainabilityBullet, ...] = ()
    primary_risks: tuple[ExplainabilityBullet, ...] = ()
    portfolio_reasons: tuple[ExplainabilityBullet, ...] = ()

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        decision = self.decision.strip().upper()
        action = self.action.strip().upper()
        allocation_decision = self.allocation_decision.strip().upper()

        if not symbol:
            raise ValueError("recommendation explanation symbol cannot be empty")
        if not decision:
            raise ValueError("recommendation explanation decision cannot be empty")
        if not action:
            raise ValueError("recommendation explanation action cannot be empty")
        if not allocation_decision:
            raise ValueError("allocation decision cannot be empty")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "score", Decimal(str(self.score)))
        object.__setattr__(
            self,
            "allocation_decision",
            allocation_decision,
        )
        object.__setattr__(
            self,
            "allocation_weight",
            Decimal(str(self.allocation_weight)),
        )
        object.__setattr__(self, "primary_drivers", tuple(self.primary_drivers))
        object.__setattr__(self, "primary_risks", tuple(self.primary_risks))
        object.__setattr__(self, "portfolio_reasons", tuple(self.portfolio_reasons))

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "decision": self.decision,
            "action": self.action,
            "confidence": self.confidence.value,
            "score": str(self.score),
            "allocation_decision": self.allocation_decision,
            "allocation_weight": str(self.allocation_weight),
            "primary_drivers": [bullet.as_dict() for bullet in self.primary_drivers],
            "primary_risks": [bullet.as_dict() for bullet in self.primary_risks],
            "portfolio_reasons": [
                bullet.as_dict() for bullet in self.portfolio_reasons
            ],
        }


@dataclass(frozen=True, slots=True)
class ExplainabilityReport:
    """Canonical internal explainability report.

    This model is intentionally presentation-neutral. CLI and export contracts
    can consume it without allowing this layer to change public output formats.
    """

    title: str
    observed_on: str
    confidence: ConfidenceLevel
    executive_summary: tuple[ExplainabilityBullet, ...]
    sections: tuple[ExplainabilitySection, ...]
    recommendations: tuple[RecommendationExplanation, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        title = self.title.strip()
        observed_on = self.observed_on.strip()
        metadata = _normalize_metadata(self.metadata)

        if not title:
            raise ValueError("explainability report title cannot be empty")
        if not observed_on:
            raise ValueError("explainability report observed_on cannot be empty")

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "observed_on", observed_on)
        object.__setattr__(
            self,
            "executive_summary",
            tuple(self.executive_summary),
        )
        object.__setattr__(self, "sections", tuple(self.sections))
        object.__setattr__(self, "recommendations", tuple(self.recommendations))
        object.__setattr__(self, "metadata", metadata)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "observed_on": self.observed_on,
            "confidence": self.confidence.value,
            "executive_summary": [
                bullet.as_dict() for bullet in self.executive_summary
            ],
            "sections": [section.as_dict() for section in self.sections],
            "recommendations": [
                recommendation.as_dict() for recommendation in self.recommendations
            ],
            "metadata": dict(self.metadata),
        }


def _normalize_metadata(metadata: Mapping[str, str]) -> Mapping[str, str]:
    normalized = {
        key.strip(): value.strip()
        for key, value in metadata.items()
        if key.strip() and value.strip()
    }
    return MappingProxyType(dict(sorted(normalized.items())))


__all__ = [
    "ConfidenceLevel",
    "ExplainabilityBullet",
    "ExplainabilityReport",
    "ExplainabilitySection",
    "RecommendationExplanation",
]
