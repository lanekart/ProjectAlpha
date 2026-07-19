from __future__ import annotations

from collections import Counter
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256

from alpha.strategy_discovery.models import (
    DiscoveryRow,
    DiscoveryRunConfig,
    EvaluationCosts,
    EvaluationStage,
    RobustnessResult,
    StrategyEvaluation,
    StrategySpecification,
)
from alpha.strategy_discovery.parameter_stability import ParameterStabilityEngine
from alpha.strategy_discovery.strategy_evaluator import StrategyEvaluator
from alpha.strategy_discovery.walk_forward_engine import ChronologicalPartition


class RobustnessEngine:
    """Apply deterministic perturbation, ablation, stress, and concentration tests."""

    def __init__(
        self,
        *,
        evaluator: StrategyEvaluator | None = None,
        stability: ParameterStabilityEngine | None = None,
    ) -> None:
        self.evaluator = evaluator or StrategyEvaluator()
        self.stability = stability or ParameterStabilityEngine(self.evaluator)

    def evaluate(
        self,
        *,
        strategy: StrategySpecification,
        evaluation: StrategyEvaluation,
        partition: ChronologicalPartition,
        config: DiscoveryRunConfig,
    ) -> RobustnessResult:
        validation_rows = partition.validation_rows
        stability = self.stability.evaluate(
            strategy=strategy,
            rows=validation_rows,
            config=config,
        )
        ablation_passed = self._ablation(
            strategy=strategy,
            rows=validation_rows,
            config=config,
        )
        stressed_config = replace(
            config,
            costs=EvaluationCosts(
                transaction_cost_bps=config.costs.transaction_cost_bps * 2,
                slippage_bps=config.costs.slippage_bps * 2,
                version=f"{config.costs.version}-double-stress",
                rationale="Deterministic double-cost robustness stress.",
            ),
        )
        stressed = self.evaluator.metrics(
            strategy=strategy,
            rows=validation_rows,
            config=stressed_config,
        )
        selected = self.evaluator.selected_rows(strategy, validation_rows)
        missed_fill_rows = tuple(
            row for index, row in enumerate(selected, start=1) if index % 10 != 0
        )
        missed = self.evaluator.metrics(
            strategy=strategy,
            rows=missed_fill_rows,
            config=config,
        )
        returns = self.evaluator.net_returns(strategy, validation_rows, config)
        bootstrap_low, bootstrap_high = _bootstrap_interval(
            returns,
            seed=strategy.strategy_hash,
        )
        validation_folds = tuple(
            item.metrics
            for item in evaluation.fold_evaluations
            if item.stage is EvaluationStage.VALIDATION
        )
        positive_folds = sum(
            1
            for metrics in validation_folds
            if metrics.expectancy_pct is not None
            and metrics.expectancy_pct > Decimal("0")
        )
        fold_consistency = _rate(positive_folds, len(validation_folds))
        symbol_concentration = _category_concentration(
            tuple(row.symbol for row in selected)
        )
        setup_concentration = _category_concentration(
            tuple(row.setup or "UNAVAILABLE" for row in selected)
        )
        winner_concentration = (
            evaluation.validation_metrics.largest_winner_contribution_pct
        )
        weaknesses: list[str] = []
        if not stability.passed:
            weaknesses.append(
                "expectancy collapses under 10 percent parameter perturbation"
            )
        if not ablation_passed:
            weaknesses.append("feature ablation removes positive validation expectancy")
        cost_passed = (
            stressed.expectancy_pct is not None
            and stressed.expectancy_pct > Decimal("0")
        )
        if not cost_passed:
            weaknesses.append("double transaction-cost stress removes profitability")
        missed_passed = (
            missed.expectancy_pct is not None and missed.expectancy_pct > Decimal("0")
        )
        if not missed_passed:
            weaknesses.append("deterministic missed-fill stress removes profitability")
        if bootstrap_low is None or bootstrap_low <= Decimal("0"):
            weaknesses.append("bootstrap expectancy lower bound is not positive")
        if (
            winner_concentration is not None
            and winner_concentration
            > config.constraints.maximum_winner_concentration_pct
        ):
            weaknesses.append("profits are concentrated in a small number of winners")
        return RobustnessResult(
            strategy_version=strategy.strategy_version,
            parameter_perturbation_passed=stability.passed,
            feature_ablation_passed=ablation_passed,
            cost_stress_passed=cost_passed,
            delayed_entry_status="UNAVAILABLE_NO_BAR_LEVEL_FILL_PATH",
            missed_fill_passed=missed_passed,
            stop_gap_status="UNAVAILABLE_NO_INTRABAR_GAP_ORDERING",
            bootstrap_expectancy_low_pct=bootstrap_low,
            bootstrap_expectancy_high_pct=bootstrap_high,
            fold_consistency_pct=fold_consistency,
            symbol_concentration_pct=symbol_concentration,
            setup_concentration_pct=setup_concentration,
            winner_concentration_pct=winner_concentration,
            weaknesses=tuple(weaknesses),
        )

    def _ablation(
        self,
        *,
        strategy: StrategySpecification,
        rows: tuple[DiscoveryRow, ...],
        config: DiscoveryRunConfig,
    ) -> bool:
        if not strategy.conditions:
            return True
        for index in range(len(strategy.conditions)):
            conditions = tuple(
                condition
                for condition_index, condition in enumerate(strategy.conditions)
                if condition_index != index
            )
            metrics = self.evaluator.metrics(
                strategy=replace(
                    strategy,
                    strategy_hash=f"{strategy.strategy_hash}-a{index}",
                    conditions=conditions,
                ),
                rows=rows,
                config=config,
            )
            if metrics.expectancy_pct is None or metrics.expectancy_pct <= Decimal("0"):
                return False
        return True


def _bootstrap_interval(
    returns: tuple[Decimal, ...],
    *,
    seed: str,
    samples: int = 500,
) -> tuple[Decimal | None, Decimal | None]:
    if len(returns) < 2:
        return None, None
    state = int(sha256(seed.encode()).hexdigest()[:16], 16)
    means: list[Decimal] = []
    for _ in range(samples):
        draw: list[Decimal] = []
        for _ in returns:
            state = (6364136223846793005 * state + 1442695040888963407) % (2**64)
            draw.append(returns[state % len(returns)])
        means.append(sum(draw, start=Decimal("0")) / Decimal(len(draw)))
    ordered = sorted(means)
    low = ordered[int(samples * 0.025)]
    high = ordered[min(samples - 1, int(samples * 0.975))]
    return _quantize(low), _quantize(high)


def _category_concentration(values: tuple[str, ...]) -> Decimal | None:
    if not values:
        return None
    count = Counter(values).most_common(1)[0][1]
    return _rate(count, len(values))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return _quantize(Decimal(numerator) / Decimal(denominator) * Decimal("100"))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


__all__ = ["RobustnessEngine"]
