"""Deterministic trading signal domain primitives."""

from __future__ import annotations

from alpha.trading_signals.adapters import (
    MarketSignalRecord,
    MomentumSignalAdapter,
    StrategyAdapterRegistry,
    StrategySignalAdapter,
    default_strategy_adapter_registry,
)
from alpha.trading_signals.ensemble import (
    EnsembleDecisionEngine,
    EnsembleDecisionReport,
    TradeRecommendation,
)
from alpha.trading_signals.models import (
    SignalBatch,
    SignalSide,
    TradingSignal,
)
from alpha.trading_signals.position_sizing import (
    PositionSizingConfig,
    RecommendationPositionSizer,
    SizedTradeRecommendation,
    TradePlan,
)
from alpha.trading_signals.ranking import (
    RankedStrategy,
    StrategyRankingEngine,
    StrategyRankingReport,
)
from alpha.trading_signals.registry import (
    StrategyDefinition,
    StrategyRegistry,
    default_strategy_registry,
)
from alpha.trading_signals.research import (
    MultiStrategyResearchEngine,
    MultiStrategyResearchReport,
    StrategyResearchResult,
)
from alpha.trading_signals.walk_forward import (
    SignalOutcome,
    WalkForwardConfig,
    WalkForwardFoldResult,
    WalkForwardMode,
    WalkForwardPlanner,
    WalkForwardValidationReport,
    WalkForwardValidator,
    WalkForwardWindow,
)

__all__ = [
    "EnsembleDecisionEngine",
    "EnsembleDecisionReport",
    "MarketSignalRecord",
    "MomentumSignalAdapter",
    "MultiStrategyResearchEngine",
    "MultiStrategyResearchReport",
    "PositionSizingConfig",
    "RankedStrategy",
    "RecommendationPositionSizer",
    "SignalBatch",
    "SignalOutcome",
    "SignalSide",
    "SizedTradeRecommendation",
    "StrategyAdapterRegistry",
    "StrategyDefinition",
    "StrategyRankingEngine",
    "StrategyRankingReport",
    "StrategyRegistry",
    "StrategyResearchResult",
    "StrategySignalAdapter",
    "TradePlan",
    "TradeRecommendation",
    "TradingSignal",
    "WalkForwardConfig",
    "WalkForwardFoldResult",
    "WalkForwardMode",
    "WalkForwardPlanner",
    "WalkForwardValidationReport",
    "WalkForwardValidator",
    "WalkForwardWindow",
    "default_strategy_adapter_registry",
    "default_strategy_registry",
]
