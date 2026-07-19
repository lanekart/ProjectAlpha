from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from alpha.application.runtime_models import RuntimeResult
from alpha.autonomous_loop.decision_freezer import ScheduledDecisionFreezer
from alpha.autonomous_loop.forward_dna import ForwardObservedDNAEngine
from alpha.autonomous_loop.hypothesis_pipeline import (
    EvidenceLinkedHypothesisGenerator,
    GovernedHypothesisRouter,
)
from alpha.autonomous_loop.mark_to_market import DecisionMarkToMarketEngine
from alpha.autonomous_loop.models import (
    AutonomousLoopStatus,
    AutonomousRunSummary,
    DecisionKind,
    DNADriftAssessment,
    DriftState,
    HypothesisStage,
    MarkToMarketSummary,
    RunStage,
    RunStatus,
    ScheduleDefinition,
    UniverseDefinition,
    default_schedule,
    default_universe,
)
from alpha.autonomous_loop.registry import AutonomousLoopRegistry
from alpha.autonomous_loop.runtime_adapter import RegisteredUniverseRuntime
from alpha.autonomous_loop.scheduling import ScheduleEvaluator
from alpha.continuous_learning.continuous_learning_engine import (
    ContinuousLearningEngine,
)
from alpha.continuous_learning.models import LearningOutcomeStatus
from alpha.forward_validation.forward_validation_engine import ForwardValidationEngine
from alpha.forward_validation.models import (
    ForwardValidationConfig,
    RecommendationSnapshot,
)
from alpha.forward_validation.validation_registry import (
    ForwardValidationIntegrityError,
    ForwardValidationRegistry,
)


class ScheduledRuntime(Protocol):
    def run(self, *, universe: UniverseDefinition, as_of: date) -> RuntimeResult: ...


class AutonomousDecisionLoop:
    """Run the complete decision/evidence loop with no production write path."""

    def __init__(
        self,
        *,
        registry: AutonomousLoopRegistry | None = None,
        runtime: ScheduledRuntime | None = None,
        forward_engine: ForwardValidationEngine | None = None,
        learning_engine: ContinuousLearningEngine | None = None,
        freezer: ScheduledDecisionFreezer | None = None,
        mark_engine: DecisionMarkToMarketEngine | None = None,
        dna_engine: ForwardObservedDNAEngine | None = None,
        schedule_evaluator: ScheduleEvaluator | None = None,
        hypothesis_generator: EvidenceLinkedHypothesisGenerator | None = None,
        hypothesis_router: GovernedHypothesisRouter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.registry = registry or AutonomousLoopRegistry()
        self.runtime = runtime or RegisteredUniverseRuntime()
        self.forward_engine = forward_engine or ForwardValidationEngine()
        self.learning_engine = learning_engine or ContinuousLearningEngine.from_paths()
        self.freezer = freezer or ScheduledDecisionFreezer()
        self.mark_engine = mark_engine or DecisionMarkToMarketEngine(
            registry=self.registry
        )
        self.dna_engine = dna_engine or ForwardObservedDNAEngine(self.registry)
        self.schedule_evaluator = schedule_evaluator or ScheduleEvaluator()
        self.hypothesis_generator = (
            hypothesis_generator or EvidenceLinkedHypothesisGenerator()
        )
        self.hypothesis_router = hypothesis_router or GovernedHypothesisRouter(
            self.registry
        )
        self.clock = clock or (lambda: datetime.now(tz=UTC))

    @classmethod
    def from_paths(
        cls,
        *,
        loop_registry: Path | str | None = None,
        forward_registry: Path | str | None = None,
        learning_registry: Path | str | None = None,
        performance_ledger: Path | str | None = None,
    ) -> AutonomousDecisionLoop:
        loop_store = AutonomousLoopRegistry(loop_registry)
        forward_store = ForwardValidationRegistry(forward_registry)
        return cls(
            registry=loop_store,
            forward_engine=ForwardValidationEngine(registry=forward_store),
            learning_engine=ContinuousLearningEngine.from_paths(
                performance_ledger=performance_ledger,
                forward_registry=forward_registry,
                learning_registry=learning_registry,
            ),
            mark_engine=DecisionMarkToMarketEngine(registry=loop_store),
            dna_engine=ForwardObservedDNAEngine(loop_store),
        )

    def bootstrap_defaults(self) -> tuple[bool, bool]:
        universe_created = self.registry.register_universe(default_universe())
        schedule_created = self.registry.register_schedule(default_schedule())
        return universe_created, schedule_created

    def tick(self, *, now: datetime | None = None) -> tuple[AutonomousRunSummary, ...]:
        timestamp = _utc(now or self.clock())
        summaries: list[AutonomousRunSummary] = []
        for schedule in self.registry.schedules():
            slot = self.schedule_evaluator.due_slot(schedule, now=timestamp)
            if slot is None:
                continue
            summaries.append(
                self.execute(
                    schedule_id=schedule.schedule_id,
                    scheduled_for=slot,
                    as_of=timestamp.date(),
                    occurred_at=timestamp,
                )
            )
        return tuple(summaries)

    def execute(
        self,
        *,
        schedule_id: str,
        scheduled_for: datetime,
        as_of: date,
        occurred_at: datetime | None = None,
    ) -> AutonomousRunSummary:
        timestamp = _utc(occurred_at or self.clock())
        schedule = self.registry.require_schedule(schedule_id)
        universe = self.registry.require_universe(schedule.universe_id)
        run_id = self.schedule_evaluator.run_id(schedule, scheduled_for)
        with self.registry.execution_lock():
            stages = self.registry.stages_for(run_id)
            if RunStage.COMPLETED in stages:
                return self._summary(
                    run_id=run_id,
                    schedule=schedule,
                    scheduled_for=scheduled_for,
                    status=RunStatus.ALREADY_COMPLETED,
                    detail="deterministic schedule slot was already completed",
                )
            if RunStage.STARTED not in stages:
                self.registry.append_run_stage(
                    run_id=run_id,
                    schedule_id=schedule.schedule_id,
                    scheduled_for=scheduled_for,
                    occurred_at=timestamp,
                    stage=RunStage.STARTED,
                    detail="scheduler acquired the deterministic run slot",
                )
            else:
                self.registry.append_run_stage(
                    run_id=run_id,
                    schedule_id=schedule.schedule_id,
                    scheduled_for=scheduled_for,
                    occurred_at=timestamp,
                    stage=RunStage.RESUMED,
                    detail="restart resumed from immutable stage checkpoints",
                )
            try:
                data_blocked = self._freeze_stage(
                    run_id=run_id,
                    schedule=schedule,
                    scheduled_for=scheduled_for,
                    as_of=as_of,
                    occurred_at=timestamp,
                    universe=universe,
                )
                self._shadow_stage(
                    run_id=run_id,
                    schedule=schedule,
                    scheduled_for=scheduled_for,
                    as_of=as_of,
                    occurred_at=timestamp,
                )
                mark_summary = self._mark_stage(
                    run_id=run_id,
                    schedule=schedule,
                    scheduled_for=scheduled_for,
                    as_of=as_of,
                    occurred_at=timestamp,
                )
                matured = self._learning_stage(
                    run_id=run_id,
                    schedule=schedule,
                    scheduled_for=scheduled_for,
                    occurred_at=timestamp,
                )
                dna_inserted, drifts = self._dna_stage(
                    run_id=run_id,
                    schedule=schedule,
                    scheduled_for=scheduled_for,
                    occurred_at=timestamp,
                )
                drift_alerts, hypotheses = self._research_stage(
                    run_id=run_id,
                    schedule=schedule,
                    scheduled_for=scheduled_for,
                    occurred_at=timestamp,
                    dna_drifts=drifts,
                )
                self.registry.append_run_stage(
                    run_id=run_id,
                    schedule_id=schedule.schedule_id,
                    scheduled_for=scheduled_for,
                    occurred_at=timestamp,
                    stage=RunStage.COMPLETED,
                    detail=(
                        "run completed fail-closed with no actionable decision"
                        if data_blocked
                        else "all autonomous evidence stages completed"
                    ),
                    metrics={
                        "data_blocked": str(data_blocked).lower(),
                        "missing_data": str(mark_summary.missing_data_count),
                    },
                )
                return self._summary(
                    run_id=run_id,
                    schedule=schedule,
                    scheduled_for=scheduled_for,
                    status=(
                        RunStatus.FAILED_CLOSED if data_blocked else RunStatus.COMPLETED
                    ),
                    detail=(
                        "decision generation was blocked by data health; prior "
                        "evidence maintenance still completed"
                        if data_blocked
                        else "all stages completed without production influence"
                    ),
                    matured=matured,
                    dna_inserted=dna_inserted,
                    drift_alerts=drift_alerts,
                    hypotheses=hypotheses,
                )
            except Exception as exc:
                self.registry.append_run_stage(
                    run_id=run_id,
                    schedule_id=schedule.schedule_id,
                    scheduled_for=scheduled_for,
                    occurred_at=timestamp,
                    stage=RunStage.FAILED,
                    detail=f"fail-closed exception: {type(exc).__name__}: {exc}",
                )
                return self._summary(
                    run_id=run_id,
                    schedule=schedule,
                    scheduled_for=scheduled_for,
                    status=RunStatus.FAILED_CLOSED,
                    detail=f"{type(exc).__name__}: {exc}",
                )

    def status(self, *, generated_at: datetime | None = None) -> AutonomousLoopStatus:
        timestamp = _utc(generated_at or self.clock())
        events = self.registry.run_events()
        run_ids = {item.run_id for item in events}
        completed = {item.run_id for item in events if item.stage is RunStage.COMPLETED}
        failed = {
            item.run_id
            for item in events
            if item.stage is RunStage.FAILED and item.run_id not in completed
        }
        decisions = self.registry.decisions()
        resolved = {item.decision_id for item in self.registry.resolutions()}
        router = self.hypothesis_router
        stages = {
            item.hypothesis_id: router.stage(item.hypothesis_id)
            for item in self.registry.hypotheses()
        }
        last_completed = next(
            (
                item.run_id
                for item in reversed(events)
                if item.stage is RunStage.COMPLETED
            ),
            None,
        )
        return AutonomousLoopStatus(
            generated_at=timestamp,
            universes=len(self.registry.universes()),
            schedules=len(self.registry.schedules()),
            runs=len(run_ids),
            completed_runs=len(completed),
            failed_runs=len(failed),
            frozen_decisions=len(decisions),
            unresolved_decisions=sum(
                1 for item in decisions if item.decision_id not in resolved
            ),
            resolved_decisions=len(resolved),
            forward_dna_observations=len(self.registry.forward_dna()),
            open_hypotheses=sum(
                1
                for value in stages.values()
                if value
                not in {
                    HypothesisStage.HUMAN_APPROVED,
                    HypothesisStage.REJECTED,
                }
            ),
            human_approved_hypotheses=sum(
                1
                for value in stages.values()
                if value is HypothesisStage.HUMAN_APPROVED
            ),
            last_completed_run=last_completed,
        )

    def _freeze_stage(
        self,
        *,
        run_id: str,
        schedule: ScheduleDefinition,
        scheduled_for: datetime,
        as_of: date,
        occurred_at: datetime,
        universe: UniverseDefinition,
    ) -> bool:
        if RunStage.DECISIONS_FROZEN in self.registry.stages_for(run_id):
            return any(
                item.decision_kind is DecisionKind.DATA_BLOCKED
                for item in self.registry.decisions()
                if item.run_id == run_id
            )
        start_event = next(
            item
            for item in self.registry.run_events()
            if item.run_id == run_id and item.stage is RunStage.STARTED
        )
        snapshots: tuple[RecommendationSnapshot, ...] = ()
        try:
            runtime = self.runtime.run(universe=universe, as_of=as_of)
            snapshots, decisions, healthy = self.freezer.freeze(
                runtime,
                run_id=run_id,
                generated_at=start_event.occurred_at,
                as_of=as_of,
                schedule=schedule,
                universe=universe,
            )
        except Exception as exc:
            healthy = False
            decisions = (
                self.freezer.blocked_run(
                    run_id=run_id,
                    generated_at=start_event.occurred_at,
                    observed_on=as_of,
                    schedule=schedule,
                    universe=universe,
                    reason=f"runtime unavailable: {type(exc).__name__}: {exc}",
                ),
            )
        inserted = self.registry.append_decisions(decisions)
        if healthy:
            self._ensure_forward_config(schedule, scheduled_for)
            self.forward_engine.registry.append_snapshots(snapshots)
        self.registry.append_run_stage(
            run_id=run_id,
            schedule_id=schedule.schedule_id,
            scheduled_for=scheduled_for,
            occurred_at=occurred_at,
            stage=RunStage.DECISIONS_FROZEN,
            detail="all recommendation, no-trade, and blocked outcomes were frozen",
            metrics={
                "decisions": str(len(decisions)),
                "inserted": str(inserted),
                "healthy": str(healthy).lower(),
            },
        )
        return not healthy

    def _shadow_stage(
        self,
        *,
        run_id: str,
        schedule: ScheduleDefinition,
        scheduled_for: datetime,
        as_of: date,
        occurred_at: datetime,
    ) -> None:
        if RunStage.SHADOW_UPDATED in self.registry.stages_for(run_id):
            return
        self._ensure_forward_config(schedule, scheduled_for)
        summary = self.forward_engine.update(as_of=as_of)
        self.registry.append_run_stage(
            run_id=run_id,
            schedule_id=schedule.schedule_id,
            scheduled_for=scheduled_for,
            occurred_at=occurred_at,
            stage=RunStage.SHADOW_UPDATED,
            detail="policy-isolated shadow lifecycles were evaluated",
            metrics={
                "new_events": str(summary.new_events),
                "newly_entered": str(summary.newly_entered),
                "newly_exited": str(summary.newly_exited),
                "missing_data": str(summary.missing_data_count),
            },
        )

    def _mark_stage(
        self,
        *,
        run_id: str,
        schedule: ScheduleDefinition,
        scheduled_for: datetime,
        as_of: date,
        occurred_at: datetime,
    ) -> MarkToMarketSummary:
        existing = next(
            (
                item
                for item in self.registry.run_events()
                if item.run_id == run_id and item.stage is RunStage.MARKED_TO_MARKET
            ),
            None,
        )
        if existing is not None:
            return MarkToMarketSummary(
                decisions_checked=int(existing.metrics.get("checked", "0")),
                marks_inserted=int(existing.metrics.get("marks", "0")),
                resolutions_inserted=int(existing.metrics.get("resolutions", "0")),
                unresolved_count=int(existing.metrics.get("unresolved", "0")),
                missing_data_count=int(existing.metrics.get("missing_data", "0")),
            )
        summary = self.mark_engine.update(as_of=as_of)
        self.registry.append_run_stage(
            run_id=run_id,
            schedule_id=schedule.schedule_id,
            scheduled_for=scheduled_for,
            occurred_at=occurred_at,
            stage=RunStage.MARKED_TO_MARKET,
            detail="every markable unresolved decision was valued from stored bars",
            metrics={
                "checked": str(summary.decisions_checked),
                "marks": str(summary.marks_inserted),
                "resolutions": str(summary.resolutions_inserted),
                "unresolved": str(summary.unresolved_count),
                "missing_data": str(summary.missing_data_count),
            },
        )
        return summary

    def _learning_stage(
        self,
        *,
        run_id: str,
        schedule: ScheduleDefinition,
        scheduled_for: datetime,
        occurred_at: datetime,
    ) -> int:
        existing = next(
            (
                item
                for item in self.registry.run_events()
                if item.run_id == run_id and item.stage is RunStage.OUTCOMES_PUBLISHED
            ),
            None,
        )
        if existing is not None:
            return int(existing.metrics.get("matured", "0"))
        before = {
            item.recommendation_id
            for item in self.learning_engine.learning_registry.latest_observations()
            if item.status is LearningOutcomeStatus.EXITED
        }
        self.learning_engine.collect()
        after = {
            item.recommendation_id
            for item in self.learning_engine.learning_registry.latest_observations()
            if item.status is LearningOutcomeStatus.EXITED
        }
        matured = len(after - before)
        self.registry.append_run_stage(
            run_id=run_id,
            schedule_id=schedule.schedule_id,
            scheduled_for=scheduled_for,
            occurred_at=occurred_at,
            stage=RunStage.OUTCOMES_PUBLISHED,
            detail="matured immutable shadow outcomes were published to CLL",
            metrics={"matured": str(matured)},
        )
        return matured

    def _dna_stage(
        self,
        *,
        run_id: str,
        schedule: ScheduleDefinition,
        scheduled_for: datetime,
        occurred_at: datetime,
    ) -> tuple[int, tuple[DNADriftAssessment, ...]]:
        existing = next(
            (
                item
                for item in self.registry.run_events()
                if item.run_id == run_id and item.stage is RunStage.DNA_UPDATED
            ),
            None,
        )
        if existing is not None:
            return (
                int(existing.metrics.get("inserted", "0")),
                self.registry.dna_drifts(),
            )
        inserted, drifts = self.dna_engine.update()
        if not all(isinstance(item, DNADriftAssessment) for item in drifts):
            raise TypeError("DNA drift assessment required")
        self.registry.append_run_stage(
            run_id=run_id,
            schedule_id=schedule.schedule_id,
            scheduled_for=scheduled_for,
            occurred_at=occurred_at,
            stage=RunStage.DNA_UPDATED,
            detail="matured markouts updated isolated FORWARD_OBSERVED DNA cohorts",
            metrics={"inserted": str(inserted), "drifts": str(len(drifts))},
        )
        return inserted, drifts

    def _research_stage(
        self,
        *,
        run_id: str,
        schedule: ScheduleDefinition,
        scheduled_for: datetime,
        occurred_at: datetime,
        dna_drifts: tuple[DNADriftAssessment, ...],
    ) -> tuple[int, int]:
        existing = next(
            (
                item
                for item in self.registry.run_events()
                if item.run_id == run_id and item.stage is RunStage.HYPOTHESES_ROUTED
            ),
            None,
        )
        if existing is not None:
            return (
                int(existing.metrics.get("drift_alerts", "0")),
                int(existing.metrics.get("hypotheses", "0")),
            )
        learning = self.learning_engine.report(collect_first=False)
        drift_alerts = sum(
            1
            for item in learning.drifts
            if item.status.value in {"EARLY_DRIFT", "SIGNIFICANT_DRIFT"}
        ) + sum(
            1
            for item in dna_drifts
            if item.state in {DriftState.EARLY_DRIFT, DriftState.SIGNIFICANT_DRIFT}
        )
        hypotheses = self.hypothesis_generator.generate(
            created_at=occurred_at,
            learning=learning.research_recommendations,
            dna_drifts=dna_drifts,
        )
        routed = self.hypothesis_router.register_and_route(
            hypotheses, occurred_at=occurred_at
        )
        self.registry.append_run_stage(
            run_id=run_id,
            schedule_id=schedule.schedule_id,
            scheduled_for=scheduled_for,
            occurred_at=occurred_at,
            stage=RunStage.DRIFT_EVALUATED,
            detail="calibration, feature, timing, concept, and DNA drift evaluated",
            metrics={"alerts": str(drift_alerts)},
        )
        self.registry.append_run_stage(
            run_id=run_id,
            schedule_id=schedule.schedule_id,
            scheduled_for=scheduled_for,
            occurred_at=occurred_at,
            stage=RunStage.HYPOTHESES_ROUTED,
            detail="evidence-linked hypotheses entered governed validation queues",
            metrics={
                "drift_alerts": str(drift_alerts),
                "hypotheses": str(routed),
            },
        )
        return drift_alerts, routed

    def _ensure_forward_config(
        self, schedule: ScheduleDefinition, started_at: datetime
    ) -> None:
        try:
            config = self.forward_engine.registry.load_config()
        except ForwardValidationIntegrityError:
            self.forward_engine.start(
                ForwardValidationConfig(
                    started_at=started_at,
                    initial_capital=schedule.shadow_initial_capital,
                    policy_version=schedule.policy_version,
                )
            )
            return
        if config.policy_version != schedule.policy_version:
            raise ValueError(
                "schedule policy differs from the isolated forward registry policy"
            )

    def _summary(
        self,
        *,
        run_id: str,
        schedule: ScheduleDefinition,
        scheduled_for: datetime,
        status: RunStatus,
        detail: str,
        matured: int = 0,
        dna_inserted: int = 0,
        drift_alerts: int = 0,
        hypotheses: int = 0,
    ) -> AutonomousRunSummary:
        run_events = tuple(
            item for item in self.registry.run_events() if item.run_id == run_id
        )
        decisions = tuple(
            item for item in self.registry.decisions() if item.run_id == run_id
        )
        stage_metrics = {item.stage: dict(item.metrics) for item in run_events}
        shadow = stage_metrics.get(RunStage.SHADOW_UPDATED, {})
        marks = stage_metrics.get(RunStage.MARKED_TO_MARKET, {})
        learning = stage_metrics.get(RunStage.OUTCOMES_PUBLISHED, {})
        dna = stage_metrics.get(RunStage.DNA_UPDATED, {})
        research = stage_metrics.get(RunStage.HYPOTHESES_ROUTED, {})
        return AutonomousRunSummary(
            run_id=run_id,
            schedule_id=schedule.schedule_id,
            scheduled_for=scheduled_for,
            status=status,
            decisions_frozen=len(decisions),
            shadow_events=int(shadow.get("new_events", "0")),
            marks_inserted=int(marks.get("marks", "0")),
            resolutions_inserted=int(marks.get("resolutions", "0")),
            matured_outcomes_published=int(learning.get("matured", str(matured))),
            forward_dna_inserted=int(dna.get("inserted", str(dna_inserted))),
            drift_alerts=int(research.get("drift_alerts", str(drift_alerts))),
            hypotheses_routed=int(research.get("hypotheses", str(hypotheses))),
            missing_data_count=int(marks.get("missing_data", "0")),
            detail=detail,
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["AutonomousDecisionLoop", "ScheduledRuntime"]
