from __future__ import annotations

from pathlib import Path

from alpha.strategy_lab.experiment_registry import StrategyLabExperimentRegistry


def export_registry(
    registry: StrategyLabExperimentRegistry,
    destination: Path,
) -> Path:
    if destination.suffix.lower() == ".csv":
        return registry.export_csv(destination)
    return registry.export_json(destination)


__all__ = ["export_registry"]
