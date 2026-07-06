"""Research platform domain APIs."""

from alpha.research.comparison import (
    StrategyComparisonEngine,
    StrategyComparisonReport,
    StrategyComparisonResult,
)
from alpha.research.parameter_sweep import (
    ParameterCombination,
    ParameterDefinition,
    ParameterGrid,
    ParameterSweepEngine,
    ParameterSweepEvaluator,
    ParameterSweepReport,
    ParameterSweepResult,
)
from alpha.research.persistence import (
    InMemoryResearchExperimentRepository,
    ResearchExperimentManifest,
    ResearchExperimentPersistenceService,
    ResearchExperimentRecord,
    ResearchExperimentRepository,
)
from alpha.research.reporting import (
    MarkdownResearchReportFormatter,
    ReportMetadataValue,
    ResearchReport,
    ResearchReportBuilder,
    ResearchReportFormatter,
    ResearchReportSection,
    TextResearchReportFormatter,
)
from alpha.research.session import (
    ResearchSession,
    ResearchSessionBuilder,
    ResearchSessionEntry,
    ResearchSessionSummary,
    SessionMetadataValue,
)
from alpha.research.walk_forward import (
    WalkForwardEngine,
    WalkForwardEvaluator,
    WalkForwardReport,
    WalkForwardResult,
    WalkForwardWindow,
    WalkForwardWindowGenerator,
)

__all__ = [
    "InMemoryResearchExperimentRepository",
    "MarkdownResearchReportFormatter",
    "ParameterCombination",
    "ParameterDefinition",
    "ParameterGrid",
    "ParameterSweepEngine",
    "ParameterSweepEvaluator",
    "ParameterSweepReport",
    "ParameterSweepResult",
    "ReportMetadataValue",
    "ResearchExperimentManifest",
    "ResearchExperimentPersistenceService",
    "ResearchExperimentRecord",
    "ResearchExperimentRepository",
    "ResearchReport",
    "ResearchReportBuilder",
    "ResearchReportFormatter",
    "ResearchReportSection",
    "ResearchSession",
    "ResearchSessionBuilder",
    "ResearchSessionEntry",
    "ResearchSessionSummary",
    "SessionMetadataValue",
    "StrategyComparisonEngine",
    "StrategyComparisonReport",
    "StrategyComparisonResult",
    "TextResearchReportFormatter",
    "WalkForwardEngine",
    "WalkForwardEvaluator",
    "WalkForwardReport",
    "WalkForwardResult",
    "WalkForwardWindow",
    "WalkForwardWindowGenerator",
]
