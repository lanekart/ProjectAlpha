"""Opt-in contract for governed recommendation snapshot capture."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from alpha.application.intelligence_inputs import IntelligenceInputSet
from alpha.portfolio_intelligence import CapitalAllocationPlan
from alpha.recommendation_intelligence import RecommendationReport


class GovernedRecommendationSnapshotRecorder(Protocol):
    """Capture one intelligence run without influencing its decisions."""

    def begin_capture(
        self,
        *,
        observed_on: date,
        inputs: IntelligenceInputSet,
    ) -> str:
        """Persist the complete pre-recommendation input boundary."""
        ...

    def capture_recommendations(
        self,
        *,
        capture_id: str,
        recommendations: tuple[RecommendationReport, ...],
    ) -> None:
        """Persist canonical recommendation objects immediately after creation."""
        ...

    def complete_capture(
        self,
        *,
        capture_id: str,
        recommendations: tuple[RecommendationReport, ...],
        institutional_evaluation: object | None,
        allocation_plan: CapitalAllocationPlan,
    ) -> None:
        """Finalize the append-only complete-stack snapshot package."""
        ...


__all__ = ["GovernedRecommendationSnapshotRecorder"]
