from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Any

from alpha.portfolio_policy.models import (
    PolicyDecision,
    PolicyReason,
    PolicyStatus,
    PolicyViolation,
    PortfolioPolicy,
)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class RuleEvaluationResult:
    """Deterministic result emitted by one portfolio-policy rule.

    This object is intentionally internal to the policy-engine layer. It lets
    individual rules remain independently explainable while the engine remains
    responsible for aggregating rule-level evidence into a PolicyEvaluation.
    """

    rule_id: str
    policy: PortfolioPolicy
    status: PolicyStatus
    decision: PolicyDecision
    score: Decimal
    reasons: tuple[PolicyReason, ...] = ()
    violations: tuple[PolicyViolation, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        rule_id = self.rule_id.strip().upper().replace(" ", "_")
        if not rule_id:
            raise ValueError("rule evaluation result rule_id cannot be empty")

        score = _bounded_score(self.score)
        metadata = _normalize_metadata(self.metadata)

        object.__setattr__(self, "rule_id", rule_id)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "violations", tuple(self.violations))
        object.__setattr__(self, "metadata", metadata)

        self._validate_consistency()

    @property
    def has_blocking_violations(self) -> bool:
        return any(violation.is_blocking for violation in self.violations)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "policy": self.policy.as_dict(),
            "status": self.status.value,
            "decision": self.decision.value,
            "score": str(self.score),
            "reasons": [reason.as_dict() for reason in self.reasons],
            "violations": [violation.as_dict() for violation in self.violations],
            "metadata": dict(self.metadata),
        }

    def _validate_consistency(self) -> None:
        if self.decision is PolicyDecision.REJECT and self.status is PolicyStatus.PASS:
            raise ValueError("rejected rule evaluation cannot have PASS status")

        if self.status is PolicyStatus.FAIL and self.decision is PolicyDecision.APPROVE:
            raise ValueError("failed rule evaluation cannot be approved")

        if self.has_blocking_violations and self.decision is PolicyDecision.APPROVE:
            raise ValueError("blocking rule violations cannot be approved")


def _normalize_metadata(metadata: Mapping[str, str]) -> Mapping[str, str]:
    normalized = {
        key.strip(): value.strip()
        for key, value in metadata.items()
        if key.strip() and value.strip()
    }
    return MappingProxyType(dict(sorted(normalized.items())))


def _bounded_score(value: Decimal) -> Decimal:
    score = Decimal(str(value))
    if score < _ZERO or score > _HUNDRED:
        raise ValueError("rule evaluation score must be between 0 and 100")
    return score.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


__all__ = ["RuleEvaluationResult"]
