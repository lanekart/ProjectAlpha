from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from alpha.portfolio_policy.evaluation import RuleEvaluationResult
from alpha.portfolio_policy.models import PortfolioPolicy

PolicyEvaluationContext = Mapping[str, Any]


class PortfolioPolicyRule(Protocol):
    """Protocol implemented by deterministic portfolio-governance rules."""

    @property
    def rule_id(self) -> str:
        """Stable deterministic rule identifier."""
        ...

    @property
    def order(self) -> int:
        """Deterministic execution order within a policy pipeline."""
        ...

    @property
    def policy(self) -> PortfolioPolicy:
        """Policy definition owned by this rule."""
        ...

    def evaluate(
        self,
        *,
        subject: str,
        context: PolicyEvaluationContext,
    ) -> RuleEvaluationResult:
        """Evaluate one subject against this rule."""
        ...


__all__ = ["PolicyEvaluationContext", "PortfolioPolicyRule"]
