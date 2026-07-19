from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.runtime import ProjectAlphaRuntime
from alpha.application.runtime_models import RuntimeMode, RuntimeResult
from alpha.autonomous_loop.decision_freezer import ScheduledDecisionFreezer
from alpha.autonomous_loop.engine import AutonomousDecisionLoop
from alpha.autonomous_loop.forward_dna import (
    ForwardDNADriftEngine,
    ForwardObservedDNAEngine,
)
from alpha.autonomous_loop.hypothesis_pipeline import (
    EvidenceLinkedHypothesisGenerator,
    GovernedHypothesisRouter,
)
from alpha.autonomous_loop.mark_to_market import DecisionMarkToMarketEngine
from alpha.autonomous_loop.models import (
    DecisionKind,
    DecisionResolution,
    DriftState,
    ForwardDNACohort,
    ForwardDNAObservation,
    FrozenDecision,
    HypothesisStage,
    LoopEvidenceClass,
    ResolutionKind,
    RunStage,
    RunStatus,
    ValidationGate,
    default_schedule,
    default_universe,
)
from alpha.autonomous_loop.registry import (
    AutonomousLoopIntegrityError,
    AutonomousLoopRegistry,
    canonical_json,
)
from alpha.autonomous_loop.scheduling import ScheduleEvaluator
from alpha.cli import app
from alpha.continuous_learning.continuous_learning_engine import (
    ContinuousLearningEngine,
)
from alpha.continuous_learning.models import (
    LearningConfidence,
    ResearchRecommendation,
)
from alpha.forward_validation.forward_validation_engine import ForwardValidationEngine
from alpha.forward_validation.models import PolicyVersion
from alpha.forward_validation.validation_registry import ForwardValidationRegistry
from alpha.recommendation_intelligence.models import OHLCVBar


class StaticPriceSource:
    def __init__(self, bars: dict[str, tuple[OHLCVBar, ...]]) -> None:
        self.values = bars
        self.closed = False

    def bars(
        self, *, symbol: str, start_date: date, end_date: date
    ) -> tuple[OHLCVBar, ...]:
        return tuple(
            item
            for item in self.values.get(symbol, ())
            if start_date <= item.observed_on <= end_date
        )

    def close(self) -> None:
        self.closed = True


class FailingRuntime:
    def run(self, *, universe: object, as_of: date) -> RuntimeResult:
        del universe, as_of
        raise RuntimeError("provider data unavailable")


def test_default_schedule_is_due_only_after_weekday_close() -> None:
    evaluator = ScheduleEvaluator()
    schedule = default_schedule()
    before = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    after = datetime(2026, 1, 5, 11, 0, tzinfo=UTC)
    weekend = datetime(2026, 1, 4, 12, 0, tzinfo=UTC)

    assert evaluator.due_slot(schedule, now=before) is None
    assert evaluator.due_slot(schedule, now=weekend) is None
    slot = evaluator.due_slot(schedule, now=after)
    assert slot == datetime(2026, 1, 5, 10, 15, tzinfo=UTC)
    assert evaluator.run_id(schedule, slot) == evaluator.run_id(schedule, slot)


def test_registry_registration_and_run_events_are_idempotent(tmp_path: Path) -> None:
    store = AutonomousLoopRegistry(tmp_path / "loop.json")
    assert store.register_universe(default_universe())
    assert not store.register_universe(default_universe())
    assert store.register_schedule(default_schedule())
    slot = datetime(2026, 1, 5, 10, 15, tzinfo=UTC)
    first = store.append_run_stage(
        run_id="run-1",
        schedule_id=default_schedule().schedule_id,
        scheduled_for=slot,
        occurred_at=slot,
        stage=RunStage.STARTED,
        detail="started",
    )
    second = store.append_run_stage(
        run_id="run-1",
        schedule_id=default_schedule().schedule_id,
        scheduled_for=slot,
        occurred_at=slot + timedelta(minutes=1),
        stage=RunStage.STARTED,
        detail="started",
    )

    assert first == second
    assert len(store.run_events()) == 1


def test_registry_detects_immutable_decision_conflict(tmp_path: Path) -> None:
    store = AutonomousLoopRegistry(tmp_path / "loop.json")
    decision = _decision("decision-1", DecisionKind.NO_TRADE)
    assert store.append_decisions((decision,)) == 1
    with pytest.raises(AutonomousLoopIntegrityError, match="immutable decisions"):
        store.append_decisions((_decision("decision-1", DecisionKind.REJECTED),))


def test_snapshot_override_makes_scheduler_retry_stable() -> None:
    runtime = _live_runtime(date(2026, 1, 5))
    freezer = ScheduledDecisionFreezer()
    schedule = default_schedule()
    frozen_at = datetime(2026, 1, 5, 10, 20, tzinfo=UTC)

    first = freezer.freeze(
        runtime,
        run_id="scheduled-run",
        generated_at=frozen_at,
        as_of=date(2026, 1, 5),
        schedule=schedule,
        universe=default_universe(),
    )
    second = freezer.freeze(
        runtime,
        run_id="scheduled-run",
        generated_at=frozen_at,
        as_of=date(2026, 1, 5),
        schedule=schedule,
        universe=default_universe(),
    )

    assert tuple(item.snapshot_hash for item in first[0]) == tuple(
        item.snapshot_hash for item in second[0]
    )
    assert tuple(item.artifact_hash for item in first[1]) == tuple(
        item.artifact_hash for item in second[1]
    )


def test_stale_runtime_freezes_data_blocked_decisions() -> None:
    runtime = _live_runtime(date(2026, 1, 1))
    _, decisions, healthy = ScheduledDecisionFreezer().freeze(
        runtime,
        run_id="stale-run",
        generated_at=datetime(2026, 1, 10, tzinfo=UTC),
        as_of=date(2026, 1, 10),
        schedule=default_schedule(),
        universe=default_universe(),
    )

    assert not healthy
    assert decisions
    assert all(item.decision_kind is DecisionKind.DATA_BLOCKED for item in decisions)
    assert all("stale" in " ".join(item.reasons) for item in decisions)


def test_mark_to_market_appends_every_bar_and_resolves_at_frozen_horizon(
    tmp_path: Path,
) -> None:
    store = AutonomousLoopRegistry(tmp_path / "loop.json")
    decision = _decision("decision-1", DecisionKind.APPROVED_TRADE, horizon=3)
    store.append_decisions((decision,))
    source = StaticPriceSource({"TEST": _bars(date(2026, 1, 2), (101, 103, 106))})
    engine = DecisionMarkToMarketEngine(
        registry=store, price_source_factory=lambda: source
    )

    summary = engine.update(as_of=date(2026, 1, 4))

    assert summary.marks_inserted == 3
    assert summary.resolutions_inserted == 1
    assert store.resolutions()[0].resolution_kind is ResolutionKind.WINNER
    assert store.resolutions()[0].bars_observed == 3
    assert "not realized shadow trade P/L" in store.resolutions()[0].reason
    assert source.closed


def test_missing_prices_leave_decision_unresolved_and_out_of_dna(
    tmp_path: Path,
) -> None:
    store = AutonomousLoopRegistry(tmp_path / "loop.json")
    store.append_decisions((_decision("decision-1", DecisionKind.NO_TRADE),))
    engine = DecisionMarkToMarketEngine(
        registry=store,
        price_source_factory=lambda: StaticPriceSource({}),
    )

    summary = engine.update(as_of=date(2026, 2, 1))
    inserted, _ = ForwardObservedDNAEngine(store).update()

    assert summary.missing_data_count == 1
    assert summary.unresolved_count == 1
    assert inserted == 0
    assert not store.forward_dna()


@pytest.mark.parametrize(
    ("kind", "return_pct", "expected"),
    (
        (DecisionKind.APPROVED_TRADE, Decimal("5"), ForwardDNACohort.WINNERS),
        (DecisionKind.APPROVED_TRADE, Decimal("-5"), ForwardDNACohort.LOSERS),
        (
            DecisionKind.APPROVED_TRADE,
            Decimal("-30"),
            ForwardDNACohort.CATASTROPHIC_LOSSES,
        ),
        (
            DecisionKind.NO_TRADE,
            Decimal("5"),
            ForwardDNACohort.MISSED_OPPORTUNITIES,
        ),
        (
            DecisionKind.REJECTED,
            Decimal("5"),
            ForwardDNACohort.REJECTED_OPPORTUNITIES,
        ),
    ),
)
def test_forward_dna_cohorts_are_explicit_and_forward_only(
    tmp_path: Path,
    kind: DecisionKind,
    return_pct: Decimal,
    expected: ForwardDNACohort,
) -> None:
    store = AutonomousLoopRegistry(tmp_path / f"{kind.value}.json")
    decision = _decision("decision-1", kind)
    resolution = _resolution(decision, return_pct)
    store.append_decisions((decision,))
    store.append_resolutions((resolution,))

    inserted, _ = ForwardObservedDNAEngine(store).update()

    assert inserted == 1
    assert store.forward_dna()[0].cohort is expected
    assert store.forward_dna()[0].evidence_class is LoopEvidenceClass.FORWARD_OBSERVED


def test_forward_dna_registry_rejects_mixed_evidence_payload(tmp_path: Path) -> None:
    store = AutonomousLoopRegistry(tmp_path / "loop.json")
    decision = _decision("decision-1", DecisionKind.APPROVED_TRADE)
    resolution = _resolution(decision, Decimal("5"))
    store.append_decisions((decision,))
    store.append_resolutions((resolution,))
    ForwardObservedDNAEngine(store).update()
    payload = json.loads(store.path.read_text())
    payload["forward_dna"][0]["evidence_class"] = "RECONSTRUCTED"
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        store.forward_dna()


def test_dna_drift_is_unknown_until_both_segments_mature() -> None:
    observations, resolutions = _dna_population(10, recent_winners=5)

    assessments = ForwardDNADriftEngine(minimum_segment=10).assess(
        observations=observations,
        resolutions=resolutions,
    )

    assert all(item.state is DriftState.UNKNOWN for item in assessments)


def test_dna_drift_detects_large_forward_prevalence_shift() -> None:
    observations, resolutions = _dna_population(40, recent_winners=18)

    assessments = ForwardDNADriftEngine(minimum_segment=10).assess(
        observations=observations,
        resolutions=resolutions,
    )
    winners = next(
        item for item in assessments if item.cohort is ForwardDNACohort.WINNERS
    )

    assert winners.state is DriftState.SIGNIFICANT_DRIFT
    assert winners.change_pct_points == Decimal("90.00")


def test_hypotheses_require_evidence_and_enter_strategy_lab_queue(
    tmp_path: Path,
) -> None:
    store = AutonomousLoopRegistry(tmp_path / "loop.json")
    recommendation = ResearchRecommendation(
        recommendation_id="research-1",
        priority="P1",
        subsystem="ENTRY_TIMING",
        title="Investigate entry timing drift",
        evidence_ids=("drift-1",),
        evidence_summary="timing weakened",
        recommended_research="Run a chronological timing experiment.",
        confidence=LearningConfidence.MEDIUM,
    )
    hypothesis = EvidenceLinkedHypothesisGenerator().generate(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        learning=(recommendation,),
        dna_drifts=(),
    )[0]
    router = GovernedHypothesisRouter(store)

    assert (
        router.register_and_route((hypothesis,), occurred_at=hypothesis.created_at) == 1
    )
    assert (
        router.stage(hypothesis.hypothesis_id) is HypothesisStage.STRATEGY_LAB_PENDING
    )
    assert store.validation_events()[0].result.value == "SUBMITTED"


def test_validation_pipeline_cannot_skip_gates_or_auto_approve(
    tmp_path: Path,
) -> None:
    store, hypothesis_id, router = _routed_hypothesis(tmp_path)
    now = datetime(2026, 1, 2, tzinfo=UTC)

    with pytest.raises(ValueError, match="out of order"):
        router.record_result(
            hypothesis_id=hypothesis_id,
            gate=ValidationGate.WALK_FORWARD,
            passed=True,
            evidence_artifact_id="wf-1",
            explanation="invalid skip",
            actor="researcher",
            occurred_at=now,
        )
    assert (
        router.record_result(
            hypothesis_id=hypothesis_id,
            gate=ValidationGate.STRATEGY_LAB,
            passed=True,
            evidence_artifact_id="lab-1",
            explanation="lab passed",
            actor="researcher",
            occurred_at=now,
        )
        is HypothesisStage.WALK_FORWARD_PENDING
    )
    assert (
        router.record_result(
            hypothesis_id=hypothesis_id,
            gate=ValidationGate.WALK_FORWARD,
            passed=True,
            evidence_artifact_id="wf-1",
            explanation="walk forward passed",
            actor="researcher",
            occurred_at=now,
        )
        is HypothesisStage.SHADOW_VALIDATION_PENDING
    )
    assert (
        router.record_result(
            hypothesis_id=hypothesis_id,
            gate=ValidationGate.SHADOW_VALIDATION,
            passed=True,
            evidence_artifact_id="shadow-1",
            explanation="shadow passed",
            actor="researcher",
            occurred_at=now,
        )
        is HypothesisStage.HUMAN_APPROVAL_REQUIRED
    )
    with pytest.raises(ValueError, match="cannot be the autonomous loop"):
        router.human_approve(
            hypothesis_id=hypothesis_id,
            evidence_artifact_id="approval-1",
            explanation="not human",
            actor="AUTONOMOUS_DECISION_LOOP",
            occurred_at=now,
        )
    assert not any(
        item.gate is ValidationGate.HUMAN_APPROVAL for item in store.validation_events()
    )


def test_explicit_human_approval_records_evidence_but_mutates_no_policy(
    tmp_path: Path,
) -> None:
    _, hypothesis_id, router = _routed_hypothesis(tmp_path)
    now = datetime(2026, 1, 2, tzinfo=UTC)
    for gate in (
        ValidationGate.STRATEGY_LAB,
        ValidationGate.WALK_FORWARD,
        ValidationGate.SHADOW_VALIDATION,
    ):
        router.record_result(
            hypothesis_id=hypothesis_id,
            gate=gate,
            passed=True,
            evidence_artifact_id=f"evidence-{gate.value}",
            explanation="passed external validation",
            actor="researcher",
            occurred_at=now,
        )

    stage = router.human_approve(
        hypothesis_id=hypothesis_id,
        evidence_artifact_id="approval-minutes-1",
        explanation="approved for separately governed policy research",
        actor="Chief Risk Officer",
        occurred_at=now,
    )

    assert stage is HypothesisStage.HUMAN_APPROVED


def test_loop_fails_closed_records_blocked_decision_and_is_idempotent(
    tmp_path: Path,
) -> None:
    loop_path = tmp_path / "loop.json"
    forward_path = tmp_path / "forward.json"
    learning_path = tmp_path / "learning.json"
    performance_path = tmp_path / "performance.json"
    store = AutonomousLoopRegistry(loop_path)

    def source_factory() -> StaticPriceSource:
        return StaticPriceSource({})

    forward = ForwardValidationEngine(
        registry=ForwardValidationRegistry(forward_path),
        price_source_factory=source_factory,
    )
    learning = ContinuousLearningEngine.from_paths(
        performance_ledger=performance_path,
        forward_registry=forward_path,
        learning_registry=learning_path,
    )
    loop = AutonomousDecisionLoop(
        registry=store,
        runtime=FailingRuntime(),
        forward_engine=forward,
        learning_engine=learning,
        mark_engine=DecisionMarkToMarketEngine(
            registry=store, price_source_factory=source_factory
        ),
        clock=lambda: datetime(2026, 1, 5, 11, tzinfo=UTC),
    )
    loop.bootstrap_defaults()
    slot = datetime(2026, 1, 5, 10, 15, tzinfo=UTC)

    first = loop.execute(
        schedule_id=default_schedule().schedule_id,
        scheduled_for=slot,
        as_of=date(2026, 1, 5),
    )
    counts = (
        len(store.decisions()),
        len(store.run_events()),
        len(store.hypotheses()),
    )
    second = loop.execute(
        schedule_id=default_schedule().schedule_id,
        scheduled_for=slot,
        as_of=date(2026, 1, 5),
    )

    assert first.status is RunStatus.FAILED_CLOSED
    assert store.decisions()[0].decision_kind is DecisionKind.DATA_BLOCKED
    assert RunStage.COMPLETED in store.stages_for(first.run_id)
    assert second.status is RunStatus.ALREADY_COMPLETED
    assert counts == (
        len(store.decisions()),
        len(store.run_events()),
        len(store.hypotheses()),
    )


def test_cli_bootstrap_status_and_export_are_auditable(tmp_path: Path) -> None:
    runner = CliRunner()
    registry = tmp_path / "loop.json"
    bootstrap = runner.invoke(
        app, ["autonomous", "bootstrap", "--registry", str(registry)]
    )
    status = runner.invoke(app, ["autonomous", "status", "--registry", str(registry)])
    export = runner.invoke(
        app,
        [
            "autonomous",
            "export",
            "--registry",
            str(registry),
            "--json",
            str(tmp_path / "export.json"),
            "--csv",
            str(tmp_path / "export.csv"),
        ],
    )

    assert bootstrap.exit_code == 0
    assert "Broker Orders: DISABLED" in bootstrap.stdout
    assert status.exit_code == 0
    assert "Frozen Decisions: 0" in status.stdout
    assert export.exit_code == 0
    assert (tmp_path / "export.json").exists()
    assert (tmp_path / "export.csv").exists()


def _live_runtime(observed_on: date) -> RuntimeResult:
    runtime = ProjectAlphaRuntime().run_intelligence(
        date_str=observed_on.isoformat(), demo=True
    )
    metadata = replace(
        runtime.metadata,
        requested_on=observed_on,
        observed_on=observed_on,
        mode=RuntimeMode.LIVE,
        started_at=datetime.combine(observed_on, time(10), tzinfo=UTC),
        completed_at=datetime.combine(observed_on, time(10, 1), tzinfo=UTC),
    )
    return replace(runtime, metadata=metadata)


def _decision(
    decision_id: str,
    kind: DecisionKind,
    *,
    horizon: int = 20,
) -> FrozenDecision:
    payload: dict[str, object] = {
        "decision_id": decision_id,
        "run_id": "run-1",
        "schedule_id": "SCHEDULE-1",
        "universe_id": "UNIVERSE-1",
        "recommendation_id": f"recommendation-{decision_id}",
        "generated_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "observed_on": date(2026, 1, 1).isoformat(),
        "symbol": "TEST",
        "decision_kind": kind.value,
        "final_verdict": "BUY" if kind is DecisionKind.APPROVED_TRADE else "AVOID",
        "reference_price": "100",
        "approved_deployment": (
            "10000" if kind is DecisionKind.APPROVED_TRADE else None
        ),
        "policy_version": "APPROVAL_POLICY_V1",
        "markout_horizon_bars": horizon,
        "reasons": ["test decision"],
        "feature_snapshot": {"confidence": "HIGH", "setup": "BREAKOUT"},
        "evidence_hashes": {"source": "hash"},
        "evidence_class": LoopEvidenceClass.FORWARD_OBSERVED.value,
        "production_influence": False,
    }
    payload["artifact_hash"] = sha256(canonical_json(payload).encode()).hexdigest()
    return FrozenDecision(
        decision_id=decision_id,
        run_id="run-1",
        schedule_id="SCHEDULE-1",
        universe_id="UNIVERSE-1",
        recommendation_id=f"recommendation-{decision_id}",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        observed_on=date(2026, 1, 1),
        symbol="TEST",
        decision_kind=kind,
        final_verdict=str(payload["final_verdict"]),
        reference_price=Decimal("100"),
        approved_deployment=(
            Decimal("10000") if kind is DecisionKind.APPROVED_TRADE else None
        ),
        policy_version=PolicyVersion("APPROVAL_POLICY_V1"),
        markout_horizon_bars=horizon,
        reasons=("test decision",),
        feature_snapshot={"confidence": "HIGH", "setup": "BREAKOUT"},
        evidence_hashes={"source": "hash"},
        evidence_class=LoopEvidenceClass.FORWARD_OBSERVED,
        artifact_hash=str(payload["artifact_hash"]),
    )


def _resolution(decision: FrozenDecision, return_pct: Decimal) -> DecisionResolution:
    kind = (
        ResolutionKind.CATASTROPHIC_LOSS
        if decision.decision_kind is DecisionKind.APPROVED_TRADE
        and return_pct <= Decimal("-25")
        else ResolutionKind.LOSER
        if decision.decision_kind is DecisionKind.APPROVED_TRADE
        and return_pct <= Decimal("-1")
        else ResolutionKind.WINNER
        if decision.decision_kind is DecisionKind.APPROVED_TRADE
        and return_pct > Decimal("1")
        else ResolutionKind.REJECTED_OPPORTUNITY
        if decision.decision_kind is DecisionKind.REJECTED and return_pct > Decimal("1")
        else ResolutionKind.MISSED_OPPORTUNITY
    )
    return DecisionResolution(
        resolution_id=f"resolution-{decision.decision_id}",
        decision_id=decision.decision_id,
        resolved_at=datetime(2026, 2, 1, tzinfo=UTC),
        resolution_kind=kind,
        realised_return_pct=return_pct,
        maximum_favorable_excursion_pct=max(return_pct, Decimal("5")),
        maximum_adverse_excursion_pct=min(return_pct, Decimal("-5")),
        bars_observed=20,
        reason="matured test markout",
        terminal_mark_id=f"mark-{decision.decision_id}",
    )


def _bars(start: date, closes: tuple[int, ...]) -> tuple[OHLCVBar, ...]:
    return tuple(
        OHLCVBar(
            observed_on=start + timedelta(days=index),
            open_price=Decimal(str(close - 1)),
            high_price=Decimal(str(close + 1)),
            low_price=Decimal(str(close - 2)),
            close_price=Decimal(str(close)),
            volume=Decimal("100000"),
        )
        for index, close in enumerate(closes)
    )


def _dna_population(
    count: int, *, recent_winners: int
) -> tuple[tuple[ForwardDNAObservation, ...], tuple[DecisionResolution, ...]]:
    resolutions = tuple(
        DecisionResolution(
            resolution_id=f"resolution-{index}",
            decision_id=f"decision-{index}",
            resolved_at=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=index),
            resolution_kind=(
                ResolutionKind.WINNER
                if index >= count // 2 and index < count // 2 + recent_winners
                else ResolutionKind.FLAT
            ),
            realised_return_pct=Decimal("5") if index >= count // 2 else Decimal("0"),
            maximum_favorable_excursion_pct=Decimal("5"),
            maximum_adverse_excursion_pct=Decimal("-1"),
            bars_observed=20,
            reason="matured test markout",
            terminal_mark_id=f"mark-{index}",
        )
        for index in range(count)
    )
    observations = tuple(
        ForwardDNAObservation(
            observation_id=f"observation-{item.resolution_id}",
            decision_id=item.decision_id,
            recommendation_id=None,
            observed_at=item.resolved_at,
            symbol="TEST",
            cohort=ForwardDNACohort.WINNERS,
            realised_return_pct=item.realised_return_pct,
            features={"setup": "BREAKOUT"},
            source_resolution_id=item.resolution_id,
        )
        for item in resolutions
        if item.resolution_kind is ResolutionKind.WINNER
    )
    return observations, resolutions


def _routed_hypothesis(
    tmp_path: Path,
) -> tuple[AutonomousLoopRegistry, str, GovernedHypothesisRouter]:
    store = AutonomousLoopRegistry(tmp_path / "loop.json")
    recommendation = ResearchRecommendation(
        recommendation_id="research-1",
        priority="P1",
        subsystem="CALIBRATION",
        title="Investigate calibration",
        evidence_ids=("calibration-1",),
        evidence_summary="calibration changed",
        recommended_research="Run calibration research.",
        confidence=LearningConfidence.MEDIUM,
    )
    hypothesis = EvidenceLinkedHypothesisGenerator().generate(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        learning=(recommendation,),
        dna_drifts=(),
    )[0]
    router = GovernedHypothesisRouter(store)
    router.register_and_route((hypothesis,), occurred_at=hypothesis.created_at)
    return store, hypothesis.hypothesis_id, router
