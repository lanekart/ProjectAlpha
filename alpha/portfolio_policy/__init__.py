"""Portfolio policy domain primitives and deterministic governance engine.

The portfolio_policy package owns institutional portfolio-governance language.
It answers whether an opportunity is policy-compliant before allocation sizing
and construction mechanics are applied.
"""

from __future__ import annotations

from alpha.portfolio_policy.engine import PortfolioPolicyEngine
from alpha.portfolio_policy.evaluation import RuleEvaluationResult
from alpha.portfolio_policy.models import (
    PolicyCategory,
    PolicyDecision,
    PolicyEvaluation,
    PolicyEvidence,
    PolicyReason,
    PolicyScope,
    PolicySeverity,
    PolicyStatus,
    PolicyViolation,
    PortfolioPolicy,
)
from alpha.portfolio_policy.pipeline import PolicyRulePipeline
from alpha.portfolio_policy.rule import PolicyEvaluationContext, PortfolioPolicyRule

__all__ = [
    "PolicyCategory",
    "PolicyDecision",
    "PolicyEvaluation",
    "PolicyEvaluationContext",
    "PolicyEvidence",
    "PolicyReason",
    "PolicyRulePipeline",
    "PolicyScope",
    "PolicySeverity",
    "PolicyStatus",
    "PolicyViolation",
    "PortfolioPolicy",
    "PortfolioPolicyEngine",
    "PortfolioPolicyRule",
    "RuleEvaluationResult",
]
