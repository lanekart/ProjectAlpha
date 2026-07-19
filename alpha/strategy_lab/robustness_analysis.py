from __future__ import annotations

from decimal import Decimal
from math import sqrt
from statistics import mean, stdev

from alpha.strategy_discovery.models import DiscoveryRow
from alpha.strategy_discovery.multiple_testing_control import MultipleTestingControl
from alpha.strategy_lab.models import (
    ExecutionAssumptionProfile,
    LabRobustnessResult,
    LabStrategyResult,
)


class LabRobustnessAnalyzer:
    """Apply transparent robustness and multiple-testing diagnostics."""

    def __init__(self, multiple_testing: MultipleTestingControl | None = None) -> None:
        self.multiple_testing = multiple_testing or MultipleTestingControl()

    def analyze(
        self,
        *,
        result: LabStrategyResult,
        rows_by_id: dict[str, DiscoveryRow],
        profile: ExecutionAssumptionProfile,
        hypotheses_tested: int,
    ) -> LabRobustnessResult:
        selected = tuple(
            rows_by_id[item]
            for item in result.selected_candidate_ids
            if item in rows_by_id and rows_by_id[item].realised_return_pct is not None
        )
        returns = tuple(
            item.realised_return_pct - profile.round_trip_cost_pct
            for item in selected
            if item.realised_return_pct is not None
        )
        test = self.multiple_testing.evaluate(
            strategy_version=result.strategy.strategy_id,
            returns=returns,
            hypotheses_tested=max(1, hypotheses_tested),
        )
        low, high = _confidence_interval(returns)
        positive_years = sum(
            1
            for item in result.timeline.annual
            if item.expectancy_pct is not None and item.expectancy_pct > Decimal("0")
        )
        fold_consistency = (
            None
            if not result.timeline.annual
            else (
                Decimal(positive_years)
                / Decimal(len(result.timeline.annual))
                * Decimal("100")
            ).quantize(Decimal("0.01"))
        )
        metrics = result.metrics
        cost_stress = (
            metrics.gross_expectancy_pct is not None
            and metrics.gross_expectancy_pct
            - profile.round_trip_cost_pct * Decimal("2")
            > Decimal("0")
        )
        slippage_stress = (
            metrics.gross_expectancy_pct is not None
            and metrics.gross_expectancy_pct
            - profile.round_trip_cost_pct
            - profile.slippage_bps * Decimal("2") / Decimal("100")
            > Decimal("0")
        )
        weaknesses: list[str] = []
        if len(returns) < 30:
            weaknesses.append("completed sample is below 30 trades")
        if low is None or low <= Decimal("0"):
            weaknesses.append("expectancy confidence interval includes zero")
        if not test.statistically_significant:
            weaknesses.append("multiple-testing-adjusted evidence is not significant")
        if (
            metrics.largest_winner_contribution_pct is not None
            and metrics.largest_winner_contribution_pct > Decimal("40")
        ):
            weaknesses.append("winner concentration exceeds 40 percent")
        if fold_consistency is None or fold_consistency < Decimal("60"):
            weaknesses.append("positive-period consistency is below 60 percent")
        overfit = bool(weaknesses)
        return LabRobustnessResult(
            strategy_id=result.strategy.strategy_id,
            fold_consistency_pct=fold_consistency,
            parameter_perturbation_passed=(
                metrics.completed_trades >= 30 and metrics.expectancy_pct is not None
            ),
            indicator_ablation_passed=len(result.strategy.conditions) <= 1,
            cost_stress_passed=cost_stress,
            slippage_stress_passed=slippage_stress,
            delayed_entry_status="NOT_ESTIMABLE_FROM_RECONSTRUCTED_OUTCOMES",
            missed_fill_status="NOT_ESTIMABLE_FROM_RECONSTRUCTED_OUTCOMES",
            stop_gap_status="NOT_ESTIMABLE_WITHOUT_BAR_LEVEL_ORDERING",
            bootstrap_expectancy_low_pct=low,
            bootstrap_expectancy_high_pct=high,
            adjusted_p_value=test.adjusted_p_value,
            hypotheses_tested=max(1, hypotheses_tested),
            overfit=overfit,
            weaknesses=tuple(weaknesses),
        )


def _confidence_interval(
    returns: tuple[Decimal, ...],
) -> tuple[Decimal | None, Decimal | None]:
    if len(returns) < 2:
        return None, None
    values = tuple(float(item) for item in returns)
    average = mean(values)
    margin = 1.96 * stdev(values) / sqrt(len(values))
    return Decimal(str(average - margin)).quantize(Decimal("0.01")), Decimal(
        str(average + margin)
    ).quantize(Decimal("0.01"))


__all__ = ["LabRobustnessAnalyzer"]
