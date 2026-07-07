"""Deterministic recommendation intelligence primitives.

M14 converts market intelligence, strategy evidence, empirical probability,
and portfolio context into explainable, auditable recommendation reports.
"""

from __future__ import annotations

from alpha.recommendation_intelligence.engines import (
    ExpectedValueEngine,
    OpportunityCostEngine,
    PortfolioAwarenessEngine,
    RecommendationEngine,
    RecommendationScoringEngine,
)
from alpha.recommendation_intelligence.models import (
    AllocationAdjustment,
    CandidateComparison,
    ExpectedValueAssessment,
    OpportunityCostAssessment,
    PortfolioContext,
    RecommendationAction,
    RecommendationCandidate,
    RecommendationDecision,
    RecommendationEvidence,
    RecommendationReport,
    RecommendationRisk,
    RecommendationScore,
    RecommendationScoreBreakdown,
)

__all__ = [
    "AllocationAdjustment",
    "CandidateComparison",
    "ExpectedValueAssessment",
    "ExpectedValueEngine",
    "OpportunityCostAssessment",
    "OpportunityCostEngine",
    "PortfolioAwarenessEngine",
    "PortfolioContext",
    "RecommendationAction",
    "RecommendationCandidate",
    "RecommendationDecision",
    "RecommendationEngine",
    "RecommendationEvidence",
    "RecommendationReport",
    "RecommendationRisk",
    "RecommendationScore",
    "RecommendationScoreBreakdown",
    "RecommendationScoringEngine",
]
