from __future__ import annotations

from pathlib import Path

from alpha.market_dna.dna_registry import DNARegistry


def export_registry(registry: DNARegistry, destination: Path) -> Path:
    suffix = destination.suffix.lower()
    if suffix == ".json":
        return registry.export_json(destination)
    if suffix == ".csv":
        return registry.export_csv(destination)
    raise ValueError("Market DNA export must use .json or .csv")


__all__ = ["export_registry"]
