from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.portfolio_policy.evaluation import RuleEvaluationResult
from alpha.portfolio_policy.models import (
    PolicyDecision,
    PolicyEvaluation,
    PolicyReason,
    PolicySeverity,
    PolicyStatus,
    PolicyViolation,
)
from alpha.portfolio_policy.pipeline import PolicyRulePipeline
from alpha.portfolio_policy.rule import PolicyEvaluationContext, PortfolioPolicyRule

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class PortfolioPolicyEngine:
    """Deterministic institutional portfolio-governance engine.

    The engine orchestrates a rule pipeline and aggregates rule-level outputs
    into one PolicyEvaluation. It does not compute recommendation quality,
    allocation sizing, constraint feasibility, or portfolio construction.
    """

    pipeline: PolicyRulePipeline = PolicyRulePipeline()

    @classmethod
    def from_rules(
        cls,
        rules: tuple[PortfolioPolicyRule, ...],
    ) -> PortfolioPolicyEngine:
        """Create an engine from a deterministic collection of policy rules."""

        return cls(pipeline=PolicyRulePipeline(rules=rules))

    def evaluate(
        self,
        *,
        subject: str,
        context: PolicyEvaluationContext | None = None,
    ) -> PolicyEvaluation:
        """Evaluate one subject against the configured governance pipeline."""

        normalized_subject = subject.strip().upper()
        if not normalized_subject:
            raise ValueError("portfolio policy evaluation subject cannot be empty")

        results = self.pipeline.evaluate(
            subject=normalized_subject,
            context={} if context is None else context,
        )

        return PolicyEvaluation(
            subject=normalized_subject,
            decision=_aggregate_decision(results),
            status=_aggregate_status(results),
            score=_aggregate_score(results),
            reasons=_aggregate_reasons(results),
            violations=_aggregate_violations(results),
            metadata=_aggregate_metadata(results),
        )


def _aggregate_decision(results: tuple[RuleEvaluationResult, ...]) -> PolicyDecision:
    if not results:
        return PolicyDecision.APPROVE

    if any(result.has_blocking_violations for result in results):
        return PolicyDecision.REJECT

    decisions = {result.decision for result in results}
    if PolicyDecision.REJECT in decisions:
        return PolicyDecision.REJECT
    if PolicyDecision.RESTRICT in decisions:
        return PolicyDecision.RESTRICT
    if PolicyDecision.REVIEW in decisions:
        return PolicyDecision.REVIEW
    return PolicyDecision.APPROVE


def _aggregate_status(results: tuple[RuleEvaluationResult, ...]) -> PolicyStatus:
    if not results:
        return PolicyStatus.PASS

    statuses = {result.status for result in results}
    if PolicyStatus.FAIL in statuses:
        return PolicyStatus.FAIL
    if PolicyStatus.WATCH in statuses:
        return PolicyStatus.WATCH
    return PolicyStatus.PASS


def _aggregate_score(results: tuple[RuleEvaluationResult, ...]) -> Decimal:
    if not results:
        return _HUNDRED

    total = sum((result.score for result in results), start=_ZERO)
    return total / Decimal(len(results))


def _aggregate_reasons(
    results: tuple[RuleEvaluationResult, ...],
) -> tuple[PolicyReason, ...]:
    return tuple(reason for result in results for reason in result.reasons)


def _aggregate_violations(
    results: tuple[RuleEvaluationResult, ...],
) -> tuple[PolicyViolation, ...]:
    return tuple(violation for result in results for violation in result.violations)


def _aggregate_metadata(results: tuple[RuleEvaluationResult, ...]) -> dict[str, str]:
    return {
        "policy_engine": "PortfolioPolicyEngine",
        "policy_rules_evaluated": str(len(results)),
        "policy_rule_ids": ",".join(result.rule_id for result in results),
        "policy_blocking_violations": str(
            sum(1 for result in results if result.has_blocking_violations)
        ),
        "policy_non_blocking_violations": str(
            sum(
                len(
                    tuple(
                        violation
                        for violation in result.violations
                        if violation.severity is not PolicySeverity.BLOCKING
                    )
                )
                for result in results
            )
        ),
    }


__all__ = ["PortfolioPolicyEngine"]
