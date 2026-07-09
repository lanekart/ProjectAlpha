from __future__ import annotations

from dataclasses import dataclass

from alpha.portfolio_policy.evaluation import RuleEvaluationResult
from alpha.portfolio_policy.rule import PolicyEvaluationContext, PortfolioPolicyRule


@dataclass(frozen=True, slots=True)
class PolicyRulePipeline:
    """Deterministic ordered pipeline for portfolio-policy rules.

    The pipeline owns rule ordering and execution only. It does not aggregate
    business decisions and it does not perform allocation or construction logic.
    """

    rules: tuple[PortfolioPolicyRule, ...] = ()

    def __post_init__(self) -> None:
        ordered_rules = tuple(
            sorted(
                self.rules,
                key=lambda rule: (rule.order, rule.rule_id),
            )
        )
        _validate_unique_rule_ids(ordered_rules)
        object.__setattr__(self, "rules", ordered_rules)

    def evaluate(
        self,
        *,
        subject: str,
        context: PolicyEvaluationContext,
    ) -> tuple[RuleEvaluationResult, ...]:
        """Evaluate all enabled rules for one subject in deterministic order."""

        normalized_subject = subject.strip().upper()
        if not normalized_subject:
            raise ValueError("policy pipeline subject cannot be empty")

        return tuple(
            rule.evaluate(subject=normalized_subject, context=context)
            for rule in self.rules
            if rule.policy.enabled
        )


def _validate_unique_rule_ids(rules: tuple[PortfolioPolicyRule, ...]) -> None:
    seen: set[str] = set()
    for rule in rules:
        rule_id = rule.rule_id.strip().upper().replace(" ", "_")
        if not rule_id:
            raise ValueError("portfolio policy rule_id cannot be empty")
        if rule_id in seen:
            raise ValueError(f"duplicate portfolio policy rule_id: {rule_id}")
        seen.add(rule_id)


__all__ = ["PolicyRulePipeline"]
