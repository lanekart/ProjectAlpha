"""Plugin registry and adapters for existing Project Alpha diagnostics."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from functools import cached_property
from importlib.metadata import entry_points
from typing import Protocol, runtime_checkable

from alpha.candidate_learning.approval_diagnostics import (
    ApprovalDiagnosticsEngine,
    ApprovalDiagnosticSummary,
)
from alpha.candidate_learning.directional_signal_audit import (
    DirectionalSignalAuditReport,
    DirectionalSignalQualityAuditEngine,
)
from alpha.candidate_learning.entry_timing_audit import (
    EntryTimingValidationEngine,
    EntryTimingValidationReport,
)
from alpha.candidate_learning.market_regime_audit import (
    MarketRegimeAuditEngine,
    MarketRegimeAuditReport,
)
from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
)
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.historical_replay.breakout_source_gap import BreakoutSourceGapAuditReport
from alpha.historical_replay.breakout_source_gap_service import (
    build_project_breakout_source_gap_audit,
)
from alpha.historical_replay.nse_archive_proof import NseArchiveProofBundle
from alpha.historical_replay.nse_archive_proof_service import (
    ProjectNseArchiveProofService,
)
from alpha.market_intelligence.point_in_time import (
    PointInTimeUniverseCoverageReport,
)
from alpha.market_intelligence.point_in_time_store import (
    PointInTimeAnalyticalRepository,
    PointInTimeStoreStatusReport,
)
from alpha.research.metric_truth_audit import regime_reference_scale_is_valid
from alpha.research.models import (
    BottleneckStatus,
    DiagnosticEvidence,
    DiagnosticState,
    EvidenceQuality,
    MetricAvailability,
    MetricProvenance,
    ResearchConfidence,
    ResearchMaturity,
    ResearchMetric,
    ResearchSubsystem,
)

DIAGNOSTIC_ENTRY_POINT_GROUP = "project_alpha.research_diagnostics"


@runtime_checkable
class ResearchDiagnosticPlugin(Protocol):
    """Stable interface implemented by built-in and future diagnostics."""

    @property
    def diagnostic_id(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def subsystem(self) -> ResearchSubsystem: ...

    @property
    def source_module(self) -> str: ...

    def collect(self) -> DiagnosticEvidence:
        """Collect immutable diagnostic evidence without production influence."""


@dataclass(frozen=True, slots=True)
class CallableDiagnosticPlugin:
    diagnostic_id: str
    title: str
    subsystem: ResearchSubsystem
    source_module: str
    collector: Callable[[], DiagnosticEvidence]

    def collect(self) -> DiagnosticEvidence:
        return self.collector()


class DiagnosticRegistry:
    """Deterministic plugin registry for research-only diagnostics."""

    def __init__(self) -> None:
        self._plugins: dict[str, ResearchDiagnosticPlugin] = {}

    def register(self, plugin: ResearchDiagnosticPlugin) -> None:
        diagnostic_id = plugin.diagnostic_id.strip()
        if not diagnostic_id:
            raise ValueError("diagnostic plugin id cannot be empty")
        if diagnostic_id in self._plugins:
            raise ValueError(f"diagnostic already registered: {diagnostic_id}")
        self._plugins[diagnostic_id] = plugin

    def register_module(self, module_name: str) -> int:
        """Register plugins exposed by a module without changing IRD core."""

        module = importlib.import_module(module_name)
        candidates: Iterable[object]
        factory = getattr(module, "research_diagnostic_plugins", None)
        if callable(factory):
            produced = factory()
            if not isinstance(produced, Iterable):
                raise TypeError("research_diagnostic_plugins must return an iterable")
            candidates = produced
        else:
            candidate = getattr(module, "RESEARCH_DIAGNOSTIC_PLUGIN", None)
            candidates = () if candidate is None else (candidate,)
        count = 0
        for candidate in candidates:
            if not isinstance(candidate, ResearchDiagnosticPlugin):
                raise TypeError(
                    f"module {module_name} exposed an invalid diagnostic plugin"
                )
            self.register(candidate)
            count += 1
        return count

    def discover_entry_points(self) -> int:
        """Load third-party diagnostics from the documented entry-point group."""

        count = 0
        discovered = entry_points(group=DIAGNOSTIC_ENTRY_POINT_GROUP)
        for item in sorted(discovered, key=lambda value: value.name):
            candidate = item.load()
            if not isinstance(candidate, ResearchDiagnosticPlugin):
                raise TypeError(f"entry point {item.name} is not a diagnostic plugin")
            self.register(candidate)
            count += 1
        return count

    @property
    def plugin_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))

    def collect(self) -> tuple[DiagnosticEvidence, ...]:
        evidence: list[DiagnosticEvidence] = []
        for diagnostic_id in self.plugin_ids:
            plugin = self._plugins[diagnostic_id]
            try:
                item = plugin.collect()
            except (OSError, RuntimeError, ValueError) as error:
                item = _failed_evidence(plugin, error)
            if item.diagnostic_id != diagnostic_id:
                raise ValueError(
                    "diagnostic plugin returned a mismatched diagnostic id: "
                    f"{diagnostic_id} != {item.diagnostic_id}"
                )
            evidence.append(item)
        return tuple(evidence)


class ExistingReplayEvidence:
    """Lazy, process-local view over Alpha's existing replay artifacts."""

    def __init__(
        self,
        *,
        learning_repository: LearningLedgerRepository | None = None,
        point_in_time_repository: PointInTimeAnalyticalRepository | None = None,
        nse_service: ProjectNseArchiveProofService | None = None,
    ) -> None:
        self.learning_repository = learning_repository or LearningLedgerRepository()
        self.point_in_time_repository = (
            point_in_time_repository or PointInTimeAnalyticalRepository()
        )
        self.nse_service = nse_service or ProjectNseArchiveProofService()

    @cached_property
    def records(self) -> tuple[CandidateDecisionRecord, ...]:
        return self.learning_repository.load_records()

    @cached_property
    def outcomes(self) -> tuple[CandidateForwardOutcome, ...]:
        return self.learning_repository.load_outcomes()

    @cached_property
    def approval(self) -> ApprovalDiagnosticSummary:
        return ApprovalDiagnosticsEngine().build(
            records=self.records,
            outcomes=self.outcomes,
        )

    @cached_property
    def entry_timing(self) -> EntryTimingValidationReport:
        return EntryTimingValidationEngine().audit(
            records=self.records,
            outcomes=self.outcomes,
        )

    @cached_property
    def directional(self) -> DirectionalSignalAuditReport:
        return DirectionalSignalQualityAuditEngine().analyze(
            records=self.records,
            outcomes=self.outcomes,
        )

    @cached_property
    def market_regime(self) -> MarketRegimeAuditReport:
        return MarketRegimeAuditEngine().analyze(
            records=self.records,
            outcomes=self.outcomes,
        )

    @cached_property
    def replay_readiness(self) -> BreakoutSourceGapAuditReport:
        return build_project_breakout_source_gap_audit()

    @cached_property
    def nse_archive(self) -> NseArchiveProofBundle:
        return self.nse_service.build()

    @cached_property
    def point_in_time_status(self) -> PointInTimeStoreStatusReport:
        return self.point_in_time_repository.status()

    @cached_property
    def point_in_time_coverage(self) -> PointInTimeUniverseCoverageReport:
        status = self.point_in_time_status
        if not status.exists or status.build_id is None:
            raise ValueError("point-in-time analytical store is unavailable")
        return self.point_in_time_repository.universe_coverage(build_id=status.build_id)


def default_diagnostic_registry(
    *,
    evidence: ExistingReplayEvidence | None = None,
    discover_plugins: bool = True,
) -> DiagnosticRegistry:
    """Register all existing replay diagnostics through isolated adapters."""

    context = evidence or ExistingReplayEvidence()
    registry = DiagnosticRegistry()
    builtins = (
        _plugin(
            "approval-diagnostics",
            "Institutional approval diagnostics",
            ResearchSubsystem.APPROVAL,
            "alpha.candidate_learning.approval_diagnostics",
            lambda: _approval_evidence(context),
        ),
        _plugin(
            "entry-timing-audit",
            "Entry timing validation",
            ResearchSubsystem.ENTRY_TIMING,
            "alpha.candidate_learning.entry_timing_audit",
            lambda: _entry_timing_evidence(context),
        ),
        _plugin(
            "directional-signal-audit",
            "Directional signal quality",
            ResearchSubsystem.DIRECTIONAL_SIGNAL,
            "alpha.candidate_learning.directional_signal_audit",
            lambda: _directional_evidence(context),
        ),
        _plugin(
            "market-regime-audit",
            "Market regime intervention audit",
            ResearchSubsystem.MARKET_REGIME,
            "alpha.candidate_learning.market_regime_audit",
            lambda: _market_regime_evidence(context),
        ),
        _plugin(
            "replay-readiness",
            "Breakout replay readiness",
            ResearchSubsystem.REPLAY_READINESS,
            "alpha.historical_replay.breakout_source_gap",
            lambda: _replay_readiness_evidence(context),
        ),
        _plugin(
            "identity-coverage",
            "Historical identity coverage",
            ResearchSubsystem.IDENTITY,
            "alpha.historical_replay.nse_archive_proof",
            lambda: _identity_evidence(context),
        ),
        _plugin(
            "corporate-action-coverage",
            "Corporate-action coverage",
            ResearchSubsystem.CORPORATE_ACTION,
            "alpha.historical_replay.nse_archive_proof",
            lambda: _corporate_action_evidence(context),
        ),
        _plugin(
            "point-in-time-audit",
            "Point-in-time analytical coverage",
            ResearchSubsystem.POINT_IN_TIME,
            "alpha.market_intelligence.point_in_time_store",
            lambda: _point_in_time_evidence(context),
        ),
    )
    for plugin in builtins:
        registry.register(plugin)
    registry.register_module("alpha.strategy_discovery.research_integration")
    registry.register_module("alpha.strategy_lab.research_integration")
    registry.register_module("alpha.market_dna.research_integration")
    registry.register_module("alpha.market_truth.research_integration")
    registry.register_module("alpha.autonomous_loop.research_integration")
    registry.register_module("alpha.continuous_learning.research_integration")
    registry.register_module("alpha.adaptive_weights.research_integration")
    registry.register_module("alpha.canonical_universe_audit.research_integration")
    registry.register_module("alpha.canonical_integrity_audit.research_integration")
    registry.register_module("alpha.candidate_generation_research.research_integration")
    registry.register_module("alpha.setup_discovery.research_integration")
    registry.register_module("alpha.feature_attribution_research.research_integration")
    if discover_plugins:
        registry.discover_entry_points()
    return registry


def _plugin(
    diagnostic_id: str,
    title: str,
    subsystem: ResearchSubsystem,
    source_module: str,
    collector: Callable[[], DiagnosticEvidence],
) -> CallableDiagnosticPlugin:
    return CallableDiagnosticPlugin(
        diagnostic_id=diagnostic_id,
        title=title,
        subsystem=subsystem,
        source_module=source_module,
        collector=collector,
    )


def _approval_evidence(context: ExistingReplayEvidence) -> DiagnosticEvidence:
    report = context.approval
    directional = context.directional
    strict_rows = tuple(
        row for row in directional.candidate_rows if row.strict_approved
    )
    raw_rows = tuple(row for row in directional.candidate_rows if row.raw_approved)
    completed_strict_rows = _completed_rows(strict_rows)
    completed_raw_rows = _completed_rows(raw_rows)
    strict_precision = _precision(completed_strict_rows)
    raw_precision = _precision(completed_raw_rows)
    confidence = _sample_confidence(report.total_candidates)
    return DiagnosticEvidence(
        diagnostic_id="approval-diagnostics",
        title="Institutional approval diagnostics",
        subsystem=ResearchSubsystem.APPROVAL,
        source_module="alpha.candidate_learning.approval_diagnostics",
        source_version="approval-diagnostics-schema-v1",
        state=DiagnosticState.AVAILABLE,
        maturity=(
            ResearchMaturity.BLOCKED
            if report.total_candidates and report.approved_candidates == 0
            else ResearchMaturity.PARTIAL
        ),
        evidence_quality=EvidenceQuality.HIGH,
        confidence=confidence,
        bottleneck_status=(
            BottleneckStatus.PROVEN
            if report.total_candidates and report.approved_candidates == 0
            else BottleneckStatus.UNKNOWN
        ),
        metrics=(
            _metric(
                "approval.candidates",
                "Candidates evaluated by strict institutional gate",
                report.total_candidates,
                "count",
                source="ApprovalDiagnosticsEngine.build",
                definition="all candidate records evaluated by the strict AND gate",
                population="candidate_learning_ledger strict-gate candidates",
                version="approval-diagnostics-schema-v1",
            ),
            _metric(
                "approval.strict.count",
                "Strict institutional approvals",
                report.approved_candidates,
                "count",
                source="ApprovalDiagnosticsEngine.build",
                definition="is_deployment_approved(record) with strict AND logic",
                population="candidate_learning_ledger strict-gate candidates",
                version="approval-diagnostics-schema-v1",
            ),
            _metric(
                "approval.strict.precision",
                "Strict approval precision",
                strict_precision,
                "ratio",
                source="DirectionalSignalQualityAuditEngine.analyze",
                definition=(
                    "profitable completed strict approvals / completed strict approvals"
                ),
                population="completed candidate rows with strict_approved=true",
                version="directional-signal-audit-schema-v1",
                numerator=sum(
                    bool(getattr(row, "profitable")) for row in completed_strict_rows
                ),
                denominator=len(completed_strict_rows),
                availability=(
                    MetricAvailability.NOT_ESTIMABLE
                    if not completed_strict_rows
                    else MetricAvailability.AVAILABLE
                ),
            ),
            _metric(
                "approval.raw.precision",
                "Raw approval precision",
                raw_precision,
                "ratio",
                source="DirectionalSignalQualityAuditEngine.analyze",
                definition=(
                    "profitable completed raw approvals / completed raw approvals"
                ),
                population="completed candidate rows with raw_approved=true",
                version="directional-signal-audit-schema-v1",
                numerator=sum(
                    bool(getattr(row, "profitable")) for row in completed_raw_rows
                ),
                denominator=len(completed_raw_rows),
            ),
            _metric(
                "approval.rejection_rate",
                "Strict rejection rate",
                report.rejection_rate,
                "ratio",
                source="ApprovalDiagnosticsEngine.build",
                definition="strictly rejected candidates / strict-gate candidates",
                population="candidate_learning_ledger strict-gate candidates",
                version="approval-diagnostics-schema-v1",
                numerator=report.rejected_candidates,
                denominator=report.total_candidates,
            ),
        ),
        finding=(
            f"The strict gate approved {report.approved_candidates} of "
            f"{report.total_candidates} candidates; strict approval precision is "
            f"unavailable when no candidate is approved."
        ),
        recommended_action=(
            "Investigate non-entry approval gates using matched outcomes."
        ),
        dependencies=("candidate learning ledger", "completed forward outcomes"),
        limitations=(
            "Strict institutional approvals and raw approvals are different concepts.",
        ),
    )


def _entry_timing_evidence(context: ExistingReplayEvidence) -> DiagnosticEvidence:
    report = context.entry_timing
    preferred = next(
        (
            item
            for item in report.state_validation
            if item.entry_state.value == "PREFERRED_ENTRY"
        ),
        None,
    )
    insufficient = "INSUFFICIENT" in report.decision.primary_conclusion.value
    return DiagnosticEvidence(
        diagnostic_id="entry-timing-audit",
        title="Entry timing validation",
        subsystem=ResearchSubsystem.ENTRY_TIMING,
        source_module="alpha.candidate_learning.entry_timing_audit",
        source_version="entry-timing-validation-schema-v1",
        state=DiagnosticState.PARTIAL if insufficient else DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.PARTIAL,
        evidence_quality=EvidenceQuality.HIGH,
        confidence=_sample_confidence(report.completed_outcomes),
        bottleneck_status=(
            BottleneckStatus.UNKNOWN if insufficient else BottleneckStatus.PROVEN
        ),
        metrics=(
            _metric(
                "entry_timing.candidates",
                "Entry-timing candidates evaluated",
                report.candidates_evaluated,
                "count",
                source="EntryTimingValidationEngine.audit",
                definition="candidate records classified by the entry timing engine",
                population="candidate_learning_ledger timing-classified candidates",
                version="entry-timing-validation-schema-v1",
            ),
            _metric(
                "entry_timing.completed",
                "Completed entry-timing outcomes",
                report.completed_outcomes,
                "count",
                source="EntryTimingValidationEngine.audit",
                definition=(
                    "timing-classified candidates with completed forward outcomes"
                ),
                population="candidate_learning_ledger timing-classified candidates",
                version="entry-timing-validation-schema-v1",
            ),
            _metric(
                "entry_timing.preferred_success_rate",
                "Preferred-entry success rate",
                None if preferred is None else preferred.success_rate,
                "ratio",
                source="EntryTimingValidationEngine.audit",
                definition="profitable outcomes / completed PREFERRED_ENTRY outcomes",
                population="completed candidates classified PREFERRED_ENTRY",
                version="entry-timing-validation-schema-v1",
                numerator=None if preferred is None else preferred.winners,
                denominator=(
                    None if preferred is None else preferred.completed_outcomes
                ),
            ),
            _metric(
                "entry_timing.conclusion",
                "Entry-timing conclusion",
                report.decision.primary_conclusion.value,
                "category",
                source="EntryTimingValidationEngine.audit",
                definition="native deterministic entry-timing audit conclusion",
                population="candidate_learning_ledger timing audit",
                version="entry-timing-validation-schema-v1",
            ),
        ),
        finding=" ".join(report.decision.supporting_metrics),
        recommended_action=report.decision.recommended_next_milestone.value,
        dependencies=("candidate learning ledger", "completed forward outcomes"),
        limitations=report.decision.caveats,
    )


def _directional_evidence(context: ExistingReplayEvidence) -> DiagnosticEvidence:
    report = context.directional
    ranking = next(
        (
            metric
            for metric in report.ranking_metrics
            if metric.score_name == "recommendation_score"
        ),
        None,
    )
    accuracy = report.all_accuracy
    insufficient = "INSUFFICIENT" in report.decision.primary_conclusion.value
    return DiagnosticEvidence(
        diagnostic_id="directional-signal-audit",
        title="Directional signal quality",
        subsystem=ResearchSubsystem.DIRECTIONAL_SIGNAL,
        source_module="alpha.candidate_learning.directional_signal_audit",
        source_version="directional-signal-audit-schema-v1",
        state=DiagnosticState.PARTIAL if insufficient else DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.PARTIAL,
        evidence_quality=EvidenceQuality.HIGH,
        confidence=_sample_confidence(accuracy.candidate_count),
        bottleneck_status=(
            BottleneckStatus.UNKNOWN if insufficient else BottleneckStatus.PROVEN
        ),
        metrics=(
            _metric(
                "directional.completed_candidates",
                "Completed directional candidates",
                accuracy.candidate_count,
                "count",
                source="DirectionalSignalQualityAuditEngine.analyze",
                definition="completed outcomes in ALL_COMPLETED directional universe",
                population="ALL_COMPLETED candidate outcomes",
                version="directional-signal-audit-schema-v1",
            ),
            _metric(
                "directional.buy_precision",
                "BUY precision",
                accuracy.buy_precision,
                "ratio",
                source="DirectionalSignalQualityAuditEngine.analyze",
                definition="profitable positive signals / completed positive signals",
                population="ALL_COMPLETED positive-direction candidates",
                version="directional-signal-audit-schema-v1",
                numerator=sum(
                    row.profitable
                    for row in report.candidate_rows
                    if row.final_verdict in {"BUY", "STRONG_BUY"}
                ),
                denominator=accuracy.positive_signal_count,
            ),
            _metric(
                "directional.recommendation_auc",
                "Recommendation AUC",
                None if ranking is None else ranking.roc_auc,
                "ratio",
                source="DirectionalSignalQualityAuditEngine.analyze",
                definition="ROC AUC of recommendation score against profitable outcome",
                population="ALL_COMPLETED candidates with recommendation score",
                version="directional-signal-audit-schema-v1",
            ),
            _metric(
                "directional.balanced_accuracy",
                "Directional balanced accuracy",
                accuracy.balanced_accuracy,
                "ratio",
                source="DirectionalSignalQualityAuditEngine.analyze",
                definition=(
                    "mean sensitivity across positive and negative outcome classes"
                ),
                population="ALL_COMPLETED directional candidates",
                version="directional-signal-audit-schema-v1",
            ),
            _metric(
                "directional.coverage",
                "Directional coverage",
                accuracy.coverage,
                "ratio",
                source="DirectionalSignalQualityAuditEngine.analyze",
                definition="positive plus negative signals / completed candidates",
                population="ALL_COMPLETED directional candidates",
                version="directional-signal-audit-schema-v1",
                numerator=(
                    accuracy.positive_signal_count + accuracy.negative_signal_count
                ),
                denominator=accuracy.candidate_count,
            ),
        ),
        finding=(
            f"{report.decision.primary_conclusion.value}; "
            f"{'; '.join(report.decision.supporting_metrics)}"
        ),
        recommended_action=report.decision.recommended_next_milestone.value,
        dependencies=("candidate learning ledger", "completed forward outcomes"),
        limitations=(report.decision.prohibited_next_action,),
    )


def _market_regime_evidence(context: ExistingReplayEvidence) -> DiagnosticEvidence:
    report = context.market_regime
    quality = report.reference_quality
    reference_valid = regime_reference_scale_is_valid(context.records)
    if not reference_valid:
        return DiagnosticEvidence(
            diagnostic_id="market-regime-audit",
            title="Market regime intervention audit",
            subsystem=ResearchSubsystem.MARKET_REGIME,
            source_module="alpha.candidate_learning.market_regime_audit",
            source_version="market-regime-audit-schema-v1",
            state=DiagnosticState.PARTIAL,
            maturity=ResearchMaturity.UNKNOWN,
            evidence_quality=EvidenceQuality.LOW,
            confidence=ResearchConfidence.HIGH,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(
                _metric(
                    "market_regime.candidates",
                    "Regime candidates evaluated",
                    report.candidate_count,
                    "count",
                    source="MarketRegimeAuditEngine.analyze",
                    definition="candidate records included in market regime audit",
                    population="candidate_learning_ledger regime-audit candidates",
                    version="market-regime-audit-schema-v1",
                ),
                _metric(
                    "market_regime.completed",
                    "Completed regime outcomes",
                    report.completed_outcome_count,
                    "count",
                    source="MarketRegimeAuditEngine.analyze",
                    definition=("regime-audit candidates with completed outcomes"),
                    population="candidate_learning_ledger regime-audit candidates",
                    version="market-regime-audit-schema-v1",
                ),
                _metric(
                    "market_regime.balanced_accuracy",
                    "Regime balanced accuracy",
                    None,
                    "ratio",
                    source="MarketRegimeAuditEngine.analyze",
                    definition=(
                        "balanced accuracy against the native audit reference "
                        "market state; quarantined after reference-scale audit"
                    ),
                    population=(
                        "candidate timestamps with scale-defective synthetic "
                        "reference state"
                    ),
                    version="market-regime-audit-schema-v1",
                    availability=MetricAvailability.INVALID,
                ),
                _metric(
                    "market_regime.extreme_neutral_rate",
                    "Extreme reference neutral rate",
                    None,
                    "ratio",
                    source="MarketRegimeAuditEngine.analyze",
                    definition=(
                        "native extreme-state neutral rate; quarantined because "
                        "the reference-state scale is invalid"
                    ),
                    population=(
                        "candidate timestamps with scale-defective synthetic "
                        "reference state"
                    ),
                    version="market-regime-audit-schema-v1",
                    availability=MetricAvailability.INVALID,
                ),
            ),
            finding=(
                "The native balanced-accuracy arithmetic is reproducible, but "
                "its fallback compares normalized 0-1 price/trend scores with "
                "35/75 thresholds. Predictive quality is therefore INVALID, "
                "not 1.29%."
            ),
            recommended_action=(
                "Repair and independently validate the diagnostic reference-label "
                "scale before using regime accuracy in prioritization."
            ),
            dependencies=("candidate market-state attachment", "benchmark history"),
            limitations=(
                "The quarantine changes IRD interpretation only; the source audit "
                "and all production policies remain unchanged.",
            ),
        )
    insufficient = "INSUFFICIENT" in report.decision.primary_conclusion.value
    no_primary_gap = (
        report.decision.primary_conclusion.value
        == "MARKET_REGIME_IS_NOT_THE_PRIMARY_BOTTLENECK"
    )
    status = (
        BottleneckStatus.UNKNOWN
        if insufficient
        else BottleneckStatus.NO_MATERIAL_GAP
        if no_primary_gap
        else BottleneckStatus.PROVEN
    )
    return DiagnosticEvidence(
        diagnostic_id="market-regime-audit",
        title="Market regime intervention audit",
        subsystem=ResearchSubsystem.MARKET_REGIME,
        source_module="alpha.candidate_learning.market_regime_audit",
        source_version="market-regime-audit-schema-v1",
        state=DiagnosticState.PARTIAL if insufficient else DiagnosticState.AVAILABLE,
        maturity=(
            ResearchMaturity.NASCENT
            if status is BottleneckStatus.PROVEN
            else ResearchMaturity.PARTIAL
        ),
        evidence_quality=EvidenceQuality.HIGH,
        confidence=_sample_confidence(report.completed_outcome_count),
        bottleneck_status=status,
        metrics=(
            _metric(
                "market_regime.candidates",
                "Regime candidates evaluated",
                report.candidate_count,
                "count",
                source="MarketRegimeAuditEngine.analyze",
                definition="candidate records included in market regime audit",
                population="candidate_learning_ledger regime-audit candidates",
                version="market-regime-audit-schema-v1",
            ),
            _metric(
                "market_regime.completed",
                "Completed regime outcomes",
                report.completed_outcome_count,
                "count",
                source="MarketRegimeAuditEngine.analyze",
                definition="regime-audit candidates with completed outcomes",
                population="candidate_learning_ledger regime-audit candidates",
                version="market-regime-audit-schema-v1",
            ),
            _metric(
                "market_regime.balanced_accuracy",
                "Regime balanced accuracy",
                quality.balanced_accuracy,
                "ratio",
                source="MarketRegimeAuditEngine.analyze",
                definition="balanced accuracy against the audit reference market state",
                population="candidate timestamps with reconstructed reference state",
                version="market-regime-audit-schema-v1",
            ),
            _metric(
                "market_regime.extreme_neutral_rate",
                "Extreme reference neutral rate",
                quality.extreme_reference_neutral_rate,
                "ratio",
                source="MarketRegimeAuditEngine.analyze",
                definition=(
                    "extreme reference states classified neutral / extreme states"
                ),
                population="candidate timestamps with extreme reference state",
                version="market-regime-audit-schema-v1",
            ),
        ),
        finding=report.decision.explanation,
        recommended_action=report.decision.recommended_next_milestone.value,
        dependencies=("candidate market-state attachment", "benchmark history"),
        limitations=(report.decision.prohibited_next_action,),
    )


def _replay_readiness_evidence(
    context: ExistingReplayEvidence,
) -> DiagnosticEvidence:
    report = context.replay_readiness
    return DiagnosticEvidence(
        diagnostic_id="replay-readiness",
        title="Breakout replay readiness",
        subsystem=ResearchSubsystem.REPLAY_READINESS,
        source_module="alpha.historical_replay.breakout_source_gap",
        source_version=report.audit_version,
        state=DiagnosticState.PARTIAL,
        maturity=ResearchMaturity.PARTIAL,
        evidence_quality=EvidenceQuality.HIGH,
        confidence=_sample_confidence(report.total_candidates),
        bottleneck_status=(
            BottleneckStatus.PROVEN
            if report.unreconstructable_records
            else BottleneckStatus.NO_MATERIAL_GAP
        ),
        metrics=(
            _metric(
                "replay.total_candidates",
                "Replay candidates",
                report.total_candidates,
                "count",
                source="BreakoutSourceGapAuditEngine.analyze",
                definition="breakout reference reconstruction records audited",
                population="breakout reference reconstruction dataset",
                version=report.audit_version,
            ),
            _metric(
                "replay.ready_records",
                "Replay-ready records",
                report.ready_records,
                "count",
                source="BreakoutSourceGapAuditEngine.analyze",
                definition="records with point-in-time breakout reference ready",
                population="breakout reference reconstruction dataset",
                version=report.audit_version,
                numerator=report.ready_records,
                denominator=report.total_candidates,
            ),
            _metric(
                "replay.readiness",
                "Replay readiness",
                report.overall_readiness,
                "ratio",
                source="BreakoutSourceGapAuditEngine.analyze",
                definition="ready breakout reference records / audited records",
                population="breakout reference reconstruction dataset",
                version=report.audit_version,
            ),
        ),
        finding=(
            f"{report.ready_records} of {report.total_candidates} records are ready; "
            f"native conclusion: {report.conclusion.value}."
        ),
        recommended_action=report.conclusion.value,
        dependencies=(
            "authoritative historical prices",
            "historical identity continuity",
            "corporate-action evidence",
        ),
        limitations=("Readiness is specific to breakout reference reconstruction.",),
    )


def _identity_evidence(context: ExistingReplayEvidence) -> DiagnosticEvidence:
    report = context.nse_archive.coverage
    coverage = report.projected_657_candidate_identity_coverage_percent / Decimal("100")
    return DiagnosticEvidence(
        diagnostic_id="identity-coverage",
        title="Historical identity coverage",
        subsystem=ResearchSubsystem.IDENTITY,
        source_module="alpha.historical_replay.nse_archive_proof",
        source_version=report.report_version,
        state=DiagnosticState.PARTIAL,
        maturity=(
            ResearchMaturity.VALIDATED
            if report.full_population_unresolved <= 1
            else ResearchMaturity.PARTIAL
        ),
        evidence_quality=EvidenceQuality.HIGH,
        confidence=_sample_confidence(report.full_population_candidates),
        bottleneck_status=(
            BottleneckStatus.PROVEN
            if report.full_population_unresolved
            else BottleneckStatus.NO_MATERIAL_GAP
        ),
        metrics=(
            _metric(
                "identity.population",
                "Historical identity population",
                report.full_population_candidates,
                "count",
                source="NseIdentityProofEngine.build_report",
                definition=(
                    "historical replay manifest candidates tested against NSE evidence"
                ),
                population="657-candidate historical source evaluation manifest",
                version=report.report_version,
            ),
            _metric(
                "identity.authoritative_matches",
                "Authoritative historical identity matches",
                report.full_population_authoritative_matches,
                "count",
                source="NseIdentityProofEngine.build_report",
                definition=(
                    "manifest candidates matched to dated NSE symbol-series-ISIN "
                    "evidence"
                ),
                population="657-candidate historical source evaluation manifest",
                version=report.report_version,
            ),
            _metric(
                "identity.coverage",
                "Authoritative identity coverage",
                coverage,
                "ratio",
                source="NseIdentityProofEngine.build_report",
                definition="authoritative NSE identity matches / manifest candidates",
                population="657-candidate historical source evaluation manifest",
                version=report.report_version,
                numerator=report.full_population_authoritative_matches,
                denominator=report.full_population_candidates,
            ),
        ),
        finding=(
            f"NSE evidence resolves {report.full_population_authoritative_matches} of "
            f"{report.full_population_candidates} manifest candidates."
        ),
        recommended_action=(
            "Resolve the remaining identity and preserve effective-dated lineage."
        ),
        dependencies=("authorized NSE historical identity evidence",),
        limitations=report.limitations,
    )


def _corporate_action_evidence(
    context: ExistingReplayEvidence,
) -> DiagnosticEvidence:
    report = context.nse_archive.corporate_actions
    coverage = (
        Decimal(report.complete_cases) / Decimal(report.cases_evaluated)
        if report.cases_evaluated
        else None
    )
    return DiagnosticEvidence(
        diagnostic_id="corporate-action-coverage",
        title="Corporate-action coverage",
        subsystem=ResearchSubsystem.CORPORATE_ACTION,
        source_module="alpha.historical_replay.nse_archive_proof",
        source_version=report.report_version,
        state=DiagnosticState.PARTIAL,
        maturity=(
            ResearchMaturity.BLOCKED
            if report.cases_evaluated and report.complete_cases == 0
            else ResearchMaturity.PARTIAL
        ),
        evidence_quality=EvidenceQuality.HIGH,
        confidence=_sample_confidence(report.cases_evaluated),
        bottleneck_status=(
            BottleneckStatus.PROVEN
            if report.not_found or report.conflicts
            else BottleneckStatus.NO_MATERIAL_GAP
        ),
        metrics=(
            _metric(
                "corporate_action.cases",
                "Corporate-action cases evaluated",
                report.cases_evaluated,
                "count",
                source="NseCorporateActionProofEngine.build",
                definition=(
                    "manifest cases requiring authoritative corporate-action proof"
                ),
                population="corporate-action-required historical replay cases",
                version=report.report_version,
            ),
            _metric(
                "corporate_action.complete",
                "Complete corporate-action cases",
                report.complete_cases,
                "count",
                source="NseCorporateActionProofEngine.build",
                definition=(
                    "cases with complete authoritative corporate-action evidence"
                ),
                population="corporate-action-required historical replay cases",
                version=report.report_version,
            ),
            _metric(
                "corporate_action.coverage",
                "Corporate-action coverage",
                coverage,
                "ratio",
                source="NseCorporateActionProofEngine.build",
                definition="complete corporate-action cases / evaluated cases",
                population="corporate-action-required historical replay cases",
                version=report.report_version,
                numerator=report.complete_cases,
                denominator=report.cases_evaluated,
            ),
        ),
        finding=(
            f"Complete authoritative evidence exists for {report.complete_cases} of "
            f"{report.cases_evaluated} corporate-action cases."
        ),
        recommended_action=(
            "Acquire authorized corporate-action adjustment evidence before "
            "reconstruction."
        ),
        dependencies=("authorized NSE corporate-action history",),
        limitations=(
            "No missing corporate action is inferred from adjusted price "
            "discontinuities.",
        ),
    )


def _point_in_time_evidence(context: ExistingReplayEvidence) -> DiagnosticEvidence:
    status = context.point_in_time_status
    coverage = context.point_in_time_coverage
    sector_ratio = (
        Decimal(coverage.sector_classified_rows) / Decimal(coverage.security_rows)
        if coverage.security_rows
        else None
    )
    bottleneck = (
        BottleneckStatus.PROVEN
        if coverage.sector_classified_rows < coverage.security_rows
        else BottleneckStatus.NO_MATERIAL_GAP
    )
    return DiagnosticEvidence(
        diagnostic_id="point-in-time-audit",
        title="Point-in-time analytical coverage",
        subsystem=ResearchSubsystem.POINT_IN_TIME,
        source_module="alpha.market_intelligence.point_in_time_store",
        source_version=status.store_version,
        state=DiagnosticState.PARTIAL,
        maturity=ResearchMaturity.PARTIAL,
        evidence_quality=EvidenceQuality.HIGH,
        confidence=_sample_confidence(coverage.market_dates),
        bottleneck_status=bottleneck,
        metrics=(
            _metric(
                "point_in_time.market_dates",
                "Point-in-time market dates",
                coverage.market_dates,
                "count",
                source="PointInTimeAnalyticalRepository.universe_coverage",
                definition="distinct market dates materialized in the analytical store",
                population="latest completed point-in-time analytical build",
                version=status.store_version,
            ),
            _metric(
                "point_in_time.universe_rows",
                "Point-in-time universe rows",
                coverage.security_rows,
                "count",
                source="PointInTimeAnalyticalRepository.universe_coverage",
                definition=(
                    "security-date membership rows in the latest completed build"
                ),
                population="latest completed point-in-time analytical build",
                version=status.store_version,
                numerator=coverage.sector_classified_rows,
                denominator=coverage.security_rows,
            ),
            _metric(
                "point_in_time.sector_coverage",
                "Historical sector classification coverage",
                sector_ratio,
                "ratio",
                source="PointInTimeAnalyticalRepository.universe_coverage",
                definition="sector-classified security-date rows / security-date rows",
                population="latest completed point-in-time analytical build",
                version=status.store_version,
            ),
            _metric(
                "point_in_time.overall_quality",
                "Overall point-in-time quality",
                coverage.overall_point_in_time_quality.value,
                "category",
                source="PointInTimeAnalyticalRepository.universe_coverage",
                definition="native point-in-time aggregate quality grade",
                population="latest completed point-in-time analytical build",
                version=status.store_version,
            ),
        ),
        finding=(
            f"{coverage.primary_conclusion.value}; sector-classified rows: "
            f"{coverage.sector_classified_rows} of {coverage.security_rows}."
        ),
        recommended_action=coverage.recommended_next_milestone.value,
        dependencies=("historical sector classification source",),
        limitations=(coverage.explicitly_prohibited_next_action,),
    )


def _metric(
    metric_id: str,
    label: str,
    value: bool | int | str | Decimal | None,
    unit: str,
    *,
    source: str,
    definition: str,
    population: str,
    version: str,
    numerator: int | Decimal | None = None,
    denominator: int | Decimal | None = None,
    availability: MetricAvailability | None = None,
) -> ResearchMetric:
    return ResearchMetric(
        metric_id=metric_id,
        label=label,
        value=value,
        unit=unit,
        provenance=MetricProvenance(
            source=source,
            definition=definition,
            population=population,
            version=version,
        ),
        numerator=numerator,
        denominator=denominator,
        availability=availability,
    )


def _completed_rows(rows: tuple[object, ...]) -> tuple[object, ...]:
    return tuple(row for row in rows if getattr(row, "forward_return") is not None)


def _precision(rows: tuple[object, ...]) -> Decimal | None:
    if not rows:
        return None
    profitable = sum(bool(getattr(row, "profitable")) for row in rows)
    return (Decimal(profitable) / Decimal(len(rows))).quantize(Decimal("0.0001"))


def _sample_confidence(sample_count: int) -> ResearchConfidence:
    if sample_count >= 100:
        return ResearchConfidence.HIGH
    if sample_count >= 30:
        return ResearchConfidence.MEDIUM
    if sample_count > 0:
        return ResearchConfidence.LOW
    return ResearchConfidence.UNKNOWN


def _failed_evidence(
    plugin: ResearchDiagnosticPlugin,
    error: Exception,
) -> DiagnosticEvidence:
    message = str(error).strip() or error.__class__.__name__
    return DiagnosticEvidence(
        diagnostic_id=plugin.diagnostic_id,
        title=plugin.title,
        subsystem=plugin.subsystem,
        source_module=plugin.source_module,
        source_version="unavailable",
        state=DiagnosticState.FAILED,
        maturity=ResearchMaturity.UNKNOWN,
        evidence_quality=EvidenceQuality.UNKNOWN,
        confidence=ResearchConfidence.UNKNOWN,
        bottleneck_status=BottleneckStatus.UNKNOWN,
        metrics=(),
        finding=f"Diagnostic collection failed: {message}",
        recommended_action="Restore diagnostic evidence collection.",
        limitations=("No metric may be inferred from a failed diagnostic.",),
    )


__all__ = [
    "CallableDiagnosticPlugin",
    "DIAGNOSTIC_ENTRY_POINT_GROUP",
    "DiagnosticRegistry",
    "ExistingReplayEvidence",
    "ResearchDiagnosticPlugin",
    "default_diagnostic_registry",
]
