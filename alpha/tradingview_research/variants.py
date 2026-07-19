"""Deterministic TRL configuration-family generation."""

from __future__ import annotations

import itertools
from dataclasses import replace
from decimal import Decimal

from alpha.tradingview_research.models import ComponentWeight, LabConfiguration

_ABLATION_COMPONENTS = (
    "trend",
    "volume",
    "relative_strength",
    "retracement",
    "candle",
    "breakout",
    "risk",
)
_STOP_MODELS = ("ATR", "SWING_LOW", "SUPPORT", "EMA", "STRUCTURE", "FIXED_PERCENT")
_EXIT_MODELS = (
    "2R",
    "3R",
    "4R",
    "PARTIAL",
    "ATR_TRAIL",
    "EMA_TRAIL",
    "STRUCTURE_EXIT",
    "TIME_EXIT",
    "BREAK_EVEN",
)
_TIMEFRAMES = ("1M", "1W", "1D", "4H", "1H")


class LabVariantGenerator:
    """Enumerate complete research families before results are observed."""

    def component_ablation(
        self,
        baseline: LabConfiguration,
    ) -> tuple[LabConfiguration, ...]:
        variants = [replace(baseline, name="TRL_ABLATION_BASELINE")]
        weights = {item.component: item.weight for item in baseline.weights}
        missing = tuple(item for item in _ABLATION_COMPONENTS if item not in weights)
        if missing:
            raise ValueError(
                f"baseline lacks ablation components: {', '.join(missing)}"
            )
        for component in _ABLATION_COMPONENTS:
            variants.append(
                replace(
                    baseline,
                    name=f"TRL_REMOVE_{component.upper()}",
                    weights=tuple(
                        ComponentWeight(
                            component=item.component,
                            weight=(
                                Decimal("0")
                                if item.component == component
                                else item.weight
                            ),
                        )
                        for item in baseline.weights
                    ),
                )
            )
        return tuple(variants)

    def stop_exit(
        self,
        baseline: LabConfiguration,
    ) -> tuple[LabConfiguration, ...]:
        return tuple(
            replace(
                baseline,
                name=f"TRL_STOP_{stop}_EXIT_{exit_}",
                stop_model=stop,
                exit_model=exit_,
            )
            for stop, exit_ in itertools.product(_STOP_MODELS, _EXIT_MODELS)
        )

    def multi_timeframe(
        self,
        baseline: LabConfiguration,
    ) -> tuple[LabConfiguration, ...]:
        return tuple(
            replace(
                baseline,
                name=f"TRL_MTF_{trend}_{setup}_{entry}",
                trend_timeframe=trend,
                setup_timeframe=setup,
                entry_timeframe=entry,
            )
            for trend, setup, entry in itertools.product(_TIMEFRAMES, repeat=3)
        )
