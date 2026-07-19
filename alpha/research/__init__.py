"""Research platform domain APIs."""

from alpha.research.comparison import (
    StrategyComparisonEngine,
    StrategyComparisonReport,
    StrategyComparisonResult,
)
from alpha.research.diagnostic_registry import (
    DiagnosticRegistry,
    ExistingReplayEvidence,
    ResearchDiagnosticPlugin,
    default_diagnostic_registry,
)
from alpha.research.institutional_research_director import (
    InstitutionalResearchDirector,
)
from alpha.research.metric_truth_audit import (
    MetricTruthAuditEngine,
    MetricTruthAuditReport,
)
from alpha.research.models import (
    DiagnosticEvidence,
    EngineeringRoiReport,
    ExecutiveResearchBrief,
    MetricAvailability,
    RankedBottleneck,
    RegisteredResearchExperiment,
    ResearchMetric,
    ResearchRoadmap,
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
from alpha.research.research_registry import ResearchExperimentRegistry
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
    "DiagnosticEvidence",
    "DiagnosticRegistry",
    "EngineeringRoiReport",
    "ExecutiveResearchBrief",
    "ExistingReplayEvidence",
    "InstitutionalResearchDirector",
    "MetricAvailability",
    "MetricTruthAuditEngine",
    "MetricTruthAuditReport",
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
    "ResearchExperimentRegistry",
    "ResearchExperimentPersistenceService",
    "ResearchExperimentRecord",
    "ResearchExperimentRepository",
    "ResearchReport",
    "ResearchReportBuilder",
    "ResearchReportFormatter",
    "ResearchReportSection",
    "ResearchDiagnosticPlugin",
    "ResearchMetric",
    "ResearchRoadmap",
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
    "RankedBottleneck",
    "RegisteredResearchExperiment",
    "default_diagnostic_registry",
]
