from __future__ import annotations

from alpha.strategy_lab.models import LabStrategyResult


def benchmark_results(
    results: tuple[LabStrategyResult, ...],
) -> tuple[LabStrategyResult, ...]:
    return tuple(item for item in results if item.strategy.benchmark)


def candidate_results(
    results: tuple[LabStrategyResult, ...],
) -> tuple[LabStrategyResult, ...]:
    return tuple(item for item in results if not item.strategy.benchmark)


__all__ = ["benchmark_results", "candidate_results"]
