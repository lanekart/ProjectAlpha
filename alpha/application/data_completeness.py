from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from alpha.recommendation_intelligence import OHLCVBar


class DataRequirement(StrEnum):
    DMA_20 = "20-DMA"
    DMA_50 = "50-DMA"
    DMA_200 = "200-DMA"
    ATR_14 = "ATR"
    RELATIVE_VOLUME = "relative volume"


@dataclass(frozen=True, slots=True)
class DataCompletionResult:
    status: str
    available_before_fetch: int
    available_after_fetch: int
    fetch_attempted: bool
    missing_requirements: tuple[DataRequirement, ...]
    providers_attempted: tuple[str, ...]


class DataCompletenessEngine:
    def assess(self, price_history: tuple[OHLCVBar, ...]) -> DataCompletionResult:
        available = len(price_history)
        missing = tuple(
            requirement
            for requirement, required_bars in (
                (DataRequirement.DMA_20, 20),
                (DataRequirement.DMA_50, 50),
                (DataRequirement.DMA_200, 200),
                (DataRequirement.ATR_14, 15),
                (DataRequirement.RELATIVE_VOLUME, 20),
            )
            if available < required_bars
        )
        fetch_attempted = bool(missing)
        return DataCompletionResult(
            status="Complete" if not missing else "Partial",
            available_before_fetch=available,
            available_after_fetch=available,
            fetch_attempted=fetch_attempted,
            missing_requirements=missing,
            providers_attempted=("local_archive",) if fetch_attempted else (),
        )
