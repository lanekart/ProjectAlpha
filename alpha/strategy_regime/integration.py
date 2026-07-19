from __future__ import annotations

from alpha.strategy_regime.engine import historical_edge_metadata
from alpha.strategy_regime.repository import StrategyRegimeBacktestRepository


def recommendation_historical_edge_metadata(
    *,
    setup_name: str | None,
    market_regime: str | None,
    repository: StrategyRegimeBacktestRepository | None = None,
) -> dict[str, str]:
    indicators = setup_to_indicators(setup_name)
    if market_regime is None:
        return {"historical_setup_edge": "Not yet computed"}
    repo = repository or StrategyRegimeBacktestRepository()
    return historical_edge_metadata(
        setup_indicators=indicators,
        regime=market_regime,
        run=repo.latest_run(),
    )


def setup_to_indicators(setup_name: str | None) -> tuple[str, ...]:
    if setup_name is None:
        return ()
    normalized = setup_name.strip().lower().replace("_", " ").replace("-", " ")
    indicators: list[str] = []
    if "breakout" in normalized:
        indicators.append("breakout")
    if "relative" in normalized or "rs" in normalized:
        indicators.append("relative-strength")
    if "volume" in normalized:
        indicators.append("volume-expansion")
    if "pullback" in normalized:
        indicators.append("pullback-to-20-dma")
    if "20" in normalized and "reclaim" in normalized:
        indicators.append("20-dma-reclaim")
    if "sector" in normalized:
        indicators.append("sector-strength")
    if "trend" in normalized or "continuation" in normalized:
        indicators.append("trend-continuation")
    if "hammer" in normalized:
        indicators.append("hammer")
    if "engulf" in normalized:
        indicators.append("bullish-engulfing")
    if not indicators and normalized:
        indicators.append(normalized.replace(" ", "-"))
    return tuple(dict.fromkeys(indicators))


__all__ = ["recommendation_historical_edge_metadata", "setup_to_indicators"]
