from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from alpha.strategy_discovery.models import (
    ConditionOperator,
    DiscoveryRow,
    DiscoveryRunConfig,
    StrategyCondition,
    StrategySpecification,
)
from alpha.strategy_discovery.strategy_evaluator import StrategyEvaluator


@dataclass(frozen=True, slots=True)
class ParameterStabilityResult:
    variants_tested: int
    positive_expectancy_variants: int
    passed: bool
    expectancies_pct: tuple[Decimal | None, ...]


class ParameterStabilityEngine:
    """Test small deterministic perturbations around numeric conditions."""

    def __init__(self, evaluator: StrategyEvaluator | None = None) -> None:
        self.evaluator = evaluator or StrategyEvaluator()

    def evaluate(
        self,
        *,
        strategy: StrategySpecification,
        rows: tuple[DiscoveryRow, ...],
        config: DiscoveryRunConfig,
    ) -> ParameterStabilityResult:
        variants = _perturbations(strategy)
        if not variants:
            return ParameterStabilityResult(0, 0, True, ())
        expectancies = tuple(
            self.evaluator.metrics(
                strategy=variant,
                rows=rows,
                config=config,
            ).expectancy_pct
            for variant in variants
        )
        positive = sum(
            1 for value in expectancies if value is not None and value > Decimal("0")
        )
        return ParameterStabilityResult(
            variants_tested=len(variants),
            positive_expectancy_variants=positive,
            passed=positive == len(variants),
            expectancies_pct=expectancies,
        )


def _perturbations(
    strategy: StrategySpecification,
) -> tuple[StrategySpecification, ...]:
    variants: list[StrategySpecification] = []
    for index, condition in enumerate(strategy.conditions):
        if condition.operator not in {
            ConditionOperator.GREATER_THAN_OR_EQUAL,
            ConditionOperator.LESS_THAN_OR_EQUAL,
        }:
            continue
        try:
            value = Decimal(condition.value)
        except Exception:
            continue
        for multiplier in (Decimal("0.9"), Decimal("1.1")):
            conditions = list(strategy.conditions)
            conditions[index] = StrategyCondition(
                feature_name=condition.feature_name,
                operator=condition.operator,
                value=str(value * multiplier),
            )
            variants.append(
                replace(
                    strategy,
                    strategy_hash=f"{strategy.strategy_hash}-p{index}-{multiplier}",
                    conditions=tuple(conditions),
                )
            )
    return tuple(variants)


__all__ = ["ParameterStabilityEngine", "ParameterStabilityResult"]
