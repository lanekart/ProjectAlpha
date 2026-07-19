"""TradingView Research Laboratory evidence and governance boundary."""

from alpha.tradingview_research.aggregation import ResearchAggregationEngine
from alpha.tradingview_research.baseline import canonical_baseline_configuration
from alpha.tradingview_research.batch import BatchRunPlanner
from alpha.tradingview_research.comparison import ComparativeResearchEngine
from alpha.tradingview_research.grid import WeightGridGenerator
from alpha.tradingview_research.models import (
    PRODUCTION_INFLUENCE,
    ComparisonReport,
    LabConfiguration,
    PromotionAssessment,
    TradingViewExperiment,
)
from alpha.tradingview_research.promotion import CandidatePromotionEngine
from alpha.tradingview_research.registry import TradingViewResearchRegistry
from alpha.tradingview_research.variants import LabVariantGenerator

__all__ = [
    "PRODUCTION_INFLUENCE",
    "BatchRunPlanner",
    "CandidatePromotionEngine",
    "ComparativeResearchEngine",
    "ComparisonReport",
    "LabConfiguration",
    "LabVariantGenerator",
    "PromotionAssessment",
    "ResearchAggregationEngine",
    "TradingViewExperiment",
    "TradingViewResearchRegistry",
    "WeightGridGenerator",
    "canonical_baseline_configuration",
]
