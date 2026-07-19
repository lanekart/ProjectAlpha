"""Immutable domain models for the Institutional Research Director."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

IRD_VERSION = "institutional-research-director-v1"
PRODUCTION_INFLUENCE = False

MetricValue = bool | int | str | Decimal | None


class ResearchSubsystem(StrEnum):
    APPROVAL = "APPROVAL"
    ENTRY_TIMING = "ENTRY_TIMING"
    DIRECTIONAL_SIGNAL = "DIRECTIONAL_SIGNAL"
    MARKET_REGIME = "MARKET_REGIME"
    REPLAY_READINESS = "REPLAY_READINESS"
    IDENTITY = "IDENTITY"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    POINT_IN_TIME = "POINT_IN_TIME"
    STRATEGY_DISCOVERY = "STRATEGY_DISCOVERY"
    STRATEGY_LAB = "STRATEGY_LAB"
    MARKET_DNA = "MARKET_DNA"
    MARKET_TRUTH = "MARKET_TRUTH"
    AUTONOMOUS_LOOP = "AUTONOMOUS_LOOP"
    CONTINUOUS_LEARNING = "CONTINUOUS_LEARNING"
    ADAPTIVE_WEIGHTS = "ADAPTIVE_WEIGHTS"
    FEATURE_ATTRIBUTION = "FEATURE_ATTRIBUTION"
    RESEARCH_GOVERNANCE = "RESEARCH_GOVERNANCE"


class DiagnosticState(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class ResearchMaturity(StrEnum):
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    NASCENT = "NASCENT"
    PARTIAL = "PARTIAL"
    VALIDATED = "VALIDATED"


class EvidenceQuality(StrEnum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ResearchConfidence(StrEnum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MetricAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_ESTIMABLE = "NOT_ESTIMABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class BottleneckStatus(StrEnum):
    PROVEN = "PROVEN"
    UNKNOWN = "UNKNOWN"
    NO_MATERIAL_GAP = "NO_MATERIAL_GAP"


class EngineeringComplexity(StrEnum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RoadmapPriority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    DEFERRED = "DEFERRED"


class ExperimentStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ExperimentDecision(StrEnum):
    UNKNOWN = "UNKNOWN"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class MetricProvenance:
    """Identity needed to interpret and safely compare one research metric."""

    source: str
    definition: str
    population: str
    version: str

    def __post_init__(self) -> None:
        for name in ("source", "definition", "population", "version"):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"metric provenance {name} cannot be empty")
            object.__setattr__(self, name, value)

    @property
    def comparison_key(self) -> tuple[str, str, str, str]:
        return (self.source, self.definition, self.population, self.version)


@dataclass(frozen=True, slots=True)
class ResearchMetric:
    metric_id: str
    label: str
    value: MetricValue
    unit: str
    provenance: MetricProvenance
    numerator: int | Decimal | None = None
    denominator: int | Decimal | None = None
    availability: MetricAvailability | None = None

    def __post_init__(self) -> None:
        metric_id = self.metric_id.strip()
        label = self.label.strip()
        unit = self.unit.strip()
        if not metric_id:
            raise ValueError("metric_id cannot be empty")
        if not label:
            raise ValueError("metric label cannot be empty")
        if not unit:
            raise ValueError("metric unit cannot be empty")
        object.__setattr__(self, "metric_id", metric_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "unit", unit)
        availability = self.availability or (
            MetricAvailability.UNAVAILABLE
            if self.value is None
            else MetricAvailability.AVAILABLE
        )
        if availability is MetricAvailability.AVAILABLE and self.value is None:
            raise ValueError("available metric requires a value")
        if availability is not MetricAvailability.AVAILABLE and self.value is not None:
            raise ValueError("unavailable or invalid metric cannot carry a value")
        if self.denominator is not None and self.denominator < 0:
            raise ValueError("metric denominator cannot be negative")
        if self.numerator is not None and self.numerator < 0:
            raise ValueError("metric numerator cannot be negative")
        if availability is MetricAvailability.AVAILABLE and self.denominator == 0:
            raise ValueError("zero-denominator metric cannot be available")
        if (
            self.unit == "ratio"
            and isinstance(self.value, (int, Decimal))
            and not isinstance(self.value, bool)
        ):
            numeric_value = Decimal(self.value)
            if numeric_value < Decimal("0") or numeric_value > Decimal("1"):
                raise ValueError("ratio metric value must be between zero and one")
        object.__setattr__(self, "availability", availability)

    @property
    def available(self) -> bool:
        return self.value is not None

    @property
    def availability_status(self) -> MetricAvailability:
        availability = self.availability
        if availability is None:  # Defensive for static typing; post-init sets it.
            raise RuntimeError("research metric availability was not initialized")
        return availability

    def comparable_with(self, other: ResearchMetric) -> bool:
        return (
            self.metric_id == other.metric_id
            and self.unit == other.unit
            and self.provenance.comparison_key == other.provenance.comparison_key
        )


@dataclass(frozen=True, slots=True)
class DiagnosticEvidence:
    diagnostic_id: str
    title: str
    subsystem: ResearchSubsystem
    source_module: str
    source_version: str
    state: DiagnosticState
    maturity: ResearchMaturity
    evidence_quality: EvidenceQuality
    confidence: ResearchConfidence
    bottleneck_status: BottleneckStatus
    metrics: tuple[ResearchMetric, ...]
    finding: str
    recommended_action: str
    dependencies: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        diagnostic_id = self.diagnostic_id.strip()
        if not diagnostic_id:
            raise ValueError("diagnostic_id cannot be empty")
        if self.production_influence:
            raise ValueError("IRD diagnostics cannot influence production")
        metric_ids = tuple(metric.metric_id for metric in self.metrics)
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("diagnostic metric ids must be unique")
        object.__setattr__(self, "diagnostic_id", diagnostic_id)
        object.__setattr__(self, "dependencies", tuple(sorted(self.dependencies)))
        object.__setattr__(self, "limitations", tuple(sorted(self.limitations)))

    def metric(self, metric_id: str) -> ResearchMetric | None:
        return next(
            (metric for metric in self.metrics if metric.metric_id == metric_id),
            None,
        )


@dataclass(frozen=True, slots=True)
class RegisteredResearchExperiment:
    experiment_id: str
    title: str
    subsystem: ResearchSubsystem
    experiment_date: date
    purpose: str
    evidence_sources: tuple[str, ...]
    baseline: tuple[ResearchMetric, ...]
    treatment: tuple[ResearchMetric, ...]
    metrics: tuple[str, ...]
    statistical_confidence: ResearchConfidence
    decision: ExperimentDecision
    status: ExperimentStatus
    findings: tuple[str, ...] = ()
    lessons_learned: tuple[str, ...] = ()
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        experiment_id = self.experiment_id.strip()
        if not experiment_id:
            raise ValueError("experiment_id cannot be empty")
        if not self.title.strip() or not self.purpose.strip():
            raise ValueError("experiment title and purpose cannot be empty")
        if self.production_influence:
            raise ValueError("IRD experiments cannot influence production")
        if not self.evidence_sources:
            raise ValueError("experiment requires at least one evidence source")
        object.__setattr__(self, "experiment_id", experiment_id)
        object.__setattr__(
            self,
            "evidence_sources",
            tuple(sorted(set(self.evidence_sources))),
        )
        object.__setattr__(self, "metrics", tuple(sorted(set(self.metrics))))
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "lessons_learned", tuple(self.lessons_learned))


@dataclass(frozen=True, slots=True)
class RankedBottleneck:
    bottleneck_id: str
    subsystem: ResearchSubsystem
    title: str
    status: BottleneckStatus
    current_maturity: ResearchMaturity
    evidence_quality: EvidenceQuality
    confidence: ResearchConfidence
    dependencies: tuple[str, ...]
    engineering_complexity: EngineeringComplexity
    priority: RoadmapPriority
    supporting_diagnostics: tuple[str, ...]
    evidence_summary: str
    recommended_action: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class MeasuredRoiDelta:
    experiment_id: str
    metric_id: str
    metric_label: str
    baseline: Decimal
    treatment: Decimal
    absolute_change: Decimal
    unit: str
    confidence: ResearchConfidence
    provenance: MetricProvenance


@dataclass(frozen=True, slots=True)
class EstimatedRoiOpportunity:
    bottleneck_id: str
    subsystem: ResearchSubsystem
    estimated_gain: None
    confidence: ResearchConfidence
    explanation: str
    supporting_diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EngineeringRoiReport:
    measured: tuple[MeasuredRoiDelta, ...]
    estimated: tuple[EstimatedRoiOpportunity, ...]
    completed_experiments: int
    highest_roi_completed_project: str | None
    comparison_warning: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class RoadmapItem:
    priority: RoadmapPriority
    project_id: str
    title: str
    subsystem: ResearchSubsystem
    rationale: str
    supporting_diagnostics: tuple[str, ...]
    dependencies: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class ResearchRoadmap:
    items: tuple[RoadmapItem, ...]
    production_influence: bool = PRODUCTION_INFLUENCE

    def items_for(self, priority: RoadmapPriority) -> tuple[RoadmapItem, ...]:
        return tuple(item for item in self.items if item.priority is priority)


@dataclass(frozen=True, slots=True)
class ExecutiveResearchBrief:
    current_replay_readiness: str
    largest_proven_bottleneck: str
    largest_unknown: str
    highest_confidence_finding: str
    highest_roi_completed_project: str
    highest_priority_future_project: str
    recommended_next_sprint: str
    overall_research_confidence: ResearchConfidence
    diagnostics_considered: int
    initial_evidence: tuple[ResearchMetric, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class InstitutionalResearchSnapshot:
    diagnostics: tuple[DiagnosticEvidence, ...]
    bottlenecks: tuple[RankedBottleneck, ...]
    roadmap: ResearchRoadmap
    roi: EngineeringRoiReport
    briefing: ExecutiveResearchBrief
    production_influence: bool = PRODUCTION_INFLUENCE


__all__ = [
    "BottleneckStatus",
    "DiagnosticEvidence",
    "DiagnosticState",
    "EngineeringComplexity",
    "EngineeringRoiReport",
    "EstimatedRoiOpportunity",
    "EvidenceQuality",
    "ExecutiveResearchBrief",
    "ExperimentDecision",
    "ExperimentStatus",
    "IRD_VERSION",
    "InstitutionalResearchSnapshot",
    "MeasuredRoiDelta",
    "MetricAvailability",
    "MetricProvenance",
    "PRODUCTION_INFLUENCE",
    "RankedBottleneck",
    "RegisteredResearchExperiment",
    "ResearchConfidence",
    "ResearchMaturity",
    "ResearchMetric",
    "ResearchRoadmap",
    "ResearchSubsystem",
    "RoadmapItem",
    "RoadmapPriority",
]
