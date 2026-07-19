from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import typer

from alpha.autonomous_loop.engine import AutonomousDecisionLoop
from alpha.autonomous_loop.hypothesis_pipeline import GovernedHypothesisRouter
from alpha.autonomous_loop.models import (
    DEFAULT_SCHEDULE_ID,
    ScheduleDefinition,
    UniverseDefinition,
    UniverseSource,
    ValidationGate,
)
from alpha.autonomous_loop.registry import AutonomousLoopRegistry
from alpha.autonomous_loop.rendering import (
    render_bootstrap,
    render_dna,
    render_drift,
    render_hypotheses,
    render_journal,
    render_run,
    render_status,
)
from alpha.forward_validation.models import PolicyVersion

autonomous_app = typer.Typer(
    help="Scheduler-driven, fail-closed decision and evidence operations."
)


@autonomous_app.command(name="bootstrap")
def autonomous_bootstrap(
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Register the canonical universe and weekday post-close schedule."""

    engine = _engine(registry=registry)
    universe_created, schedule_created = engine.bootstrap_defaults()
    _print(
        render_bootstrap(
            universe_created=universe_created,
            schedule_created=schedule_created,
            universes=engine.registry.universes(),
            schedules=engine.registry.schedules(),
        )
    )


@autonomous_app.command(name="register-universe")
def autonomous_register_universe(
    universe_id: str = typer.Option(..., "--id"),
    source: UniverseSource = typer.Option(..., "--source"),
    symbols: str = typer.Option("", "--symbols"),
    version: str = typer.Option("universe-v1", "--version"),
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Register an immutable canonical or explicit-symbol universe."""

    store = AutonomousLoopRegistry(registry)
    try:
        universe = UniverseDefinition(
            universe_id=universe_id,
            source=source,
            symbols=tuple(item.strip() for item in symbols.split(",") if item.strip()),
            version=version,
        )
        created = store.register_universe(universe)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(
        (
            f"Universe: {universe.universe_id}",
            f"Status: {'REGISTERED' if created else 'ALREADY_REGISTERED'}",
            f"Source: {universe.source.value}",
            f"Symbols: {len(universe.symbols)}",
            "PRODUCTION_INFLUENCE=false",
        )
    )


@autonomous_app.command(name="register-schedule")
def autonomous_register_schedule(
    schedule_id: str = typer.Option(..., "--id"),
    universe_id: str = typer.Option(..., "--universe"),
    local_time: str = typer.Option(..., "--time"),
    timezone: str = typer.Option("Asia/Kolkata", "--timezone"),
    weekdays: str = typer.Option("0,1,2,3,4", "--weekdays"),
    policy_version: str = typer.Option("APPROVAL_POLICY_V1", "--policy"),
    shadow_capital: str = typer.Option("1000000", "--shadow-capital"),
    maximum_data_age_days: int = typer.Option(3, "--maximum-data-age-days"),
    markout_horizon_bars: int = typer.Option(20, "--markout-horizon-bars"),
    version: str = typer.Option("schedule-v1", "--version"),
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Register one immutable schedule referencing a registered universe."""

    store = AutonomousLoopRegistry(registry)
    try:
        schedule = ScheduleDefinition(
            schedule_id=schedule_id,
            universe_id=universe_id,
            local_time=time.fromisoformat(local_time),
            timezone=timezone,
            weekdays=tuple(int(item.strip()) for item in weekdays.split(",")),
            policy_version=PolicyVersion(policy_version),
            shadow_initial_capital=Decimal(shadow_capital),
            maximum_data_age_days=maximum_data_age_days,
            markout_horizon_bars=markout_horizon_bars,
            version=version,
        )
        created = store.register_schedule(schedule)
    except (InvalidOperation, KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(
        (
            f"Schedule: {schedule.schedule_id}",
            f"Status: {'REGISTERED' if created else 'ALREADY_REGISTERED'}",
            f"Universe: {schedule.universe_id}",
            f"Local Trigger: {schedule.local_time.isoformat()} {schedule.timezone}",
            f"Policy Cohort: {schedule.policy_version.value}",
            "PRODUCTION_INFLUENCE=false",
        )
    )


@autonomous_app.command(name="tick")
def autonomous_tick(
    now: str = typer.Option("now", "--now"),
    registry: Path | None = typer.Option(None, "--registry"),
    forward_registry: Path | None = typer.Option(None, "--forward-registry"),
    learning_registry: Path | None = typer.Option(None, "--learning-registry"),
    performance_ledger: Path | None = typer.Option(None, "--performance-ledger"),
) -> None:
    """Run every schedule due at the supplied clock instant."""

    engine = _engine(
        registry=registry,
        forward_registry=forward_registry,
        learning_registry=learning_registry,
        performance_ledger=performance_ledger,
    )
    summaries = engine.tick(now=_datetime(now))
    if not summaries:
        _print(
            (
                "Autonomous Loop Tick",
                "No registered schedule is due.",
                "PRODUCTION_INFLUENCE=false",
            )
        )
        return
    for index, summary in enumerate(summaries):
        if index:
            print()
        _print(render_run(summary))


@autonomous_app.command(name="run")
def autonomous_run(
    schedule: str = typer.Option(DEFAULT_SCHEDULE_ID, "--schedule"),
    scheduled_for: str = typer.Option("now", "--scheduled-for"),
    as_of: str = typer.Option("today", "--as-of"),
    registry: Path | None = typer.Option(None, "--registry"),
    forward_registry: Path | None = typer.Option(None, "--forward-registry"),
    learning_registry: Path | None = typer.Option(None, "--learning-registry"),
    performance_ledger: Path | None = typer.Option(None, "--performance-ledger"),
) -> None:
    """Execute or resume one deterministic schedule slot."""

    timestamp = _datetime(scheduled_for)
    engine = _engine(
        registry=registry,
        forward_registry=forward_registry,
        learning_registry=learning_registry,
        performance_ledger=performance_ledger,
    )
    summary = engine.execute(
        schedule_id=schedule,
        scheduled_for=timestamp,
        as_of=_date(as_of),
    )
    _print(render_run(summary))


@autonomous_app.command(name="status")
def autonomous_status(
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Show scheduler, evidence, and validation health."""

    _print(render_status(_engine(registry=registry).status()))


@autonomous_app.command(name="journal")
def autonomous_journal(
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Show immutable run checkpoints and frozen decision outcomes."""

    store = AutonomousLoopRegistry(registry)
    _print(render_journal(decisions=store.decisions(), events=store.run_events()))


@autonomous_app.command(name="dna")
def autonomous_dna(
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Show isolated FORWARD_OBSERVED DNA cohort counts."""

    store = AutonomousLoopRegistry(registry)
    _print(
        render_dna(
            observations=store.forward_dna(),
            resolved_count=len(store.resolutions()),
        )
    )


@autonomous_app.command(name="drift")
def autonomous_drift(
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Show versioned forward DNA drift assessments."""

    _print(render_drift(AutonomousLoopRegistry(registry).dna_drifts()))


@autonomous_app.command(name="hypotheses")
def autonomous_hypotheses(
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Show research hypotheses and their governed validation stage."""

    store = AutonomousLoopRegistry(registry)
    router = GovernedHypothesisRouter(store)
    _print(
        render_hypotheses(
            hypotheses=store.hypotheses(),
            validations=store.validation_events(),
            router=router,
        )
    )


@autonomous_app.command(name="validate")
def autonomous_validate(
    hypothesis: str = typer.Option(..., "--hypothesis"),
    gate: ValidationGate = typer.Option(..., "--gate"),
    passed: bool = typer.Option(..., "--passed/--failed"),
    evidence: str = typer.Option(..., "--evidence"),
    explanation: str = typer.Option(..., "--explanation"),
    actor: str = typer.Option(..., "--actor"),
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Record external validation evidence without changing any policy."""

    store = AutonomousLoopRegistry(registry)
    router = GovernedHypothesisRouter(store)
    try:
        stage = router.record_result(
            hypothesis_id=hypothesis,
            gate=gate,
            passed=passed,
            evidence_artifact_id=evidence,
            explanation=explanation,
            actor=actor,
            occurred_at=datetime.now(tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(
        (
            f"Hypothesis: {hypothesis}",
            f"Stage: {stage.value}",
            "Production policy was not changed.",
            "PRODUCTION_INFLUENCE=false",
        )
    )


@autonomous_app.command(name="approve")
def autonomous_approve(
    hypothesis: str = typer.Option(..., "--hypothesis"),
    evidence: str = typer.Option(..., "--evidence"),
    explanation: str = typer.Option(..., "--explanation"),
    actor: str = typer.Option(..., "--actor"),
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Record explicit human approval after all three validation gates pass."""

    store = AutonomousLoopRegistry(registry)
    router = GovernedHypothesisRouter(store)
    try:
        stage = router.human_approve(
            hypothesis_id=hypothesis,
            evidence_artifact_id=evidence,
            explanation=explanation,
            actor=actor,
            occurred_at=datetime.now(tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(
        (
            f"Hypothesis: {hypothesis}",
            f"Stage: {stage.value}",
            "Human approval is evidence only; no production policy was mutated.",
            "PRODUCTION_INFLUENCE=false",
        )
    )


@autonomous_app.command(name="export")
def autonomous_export(
    json_path: Path = typer.Option(..., "--json"),
    csv_path: Path = typer.Option(..., "--csv"),
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Export the complete immutable autonomous evidence registry."""

    store = AutonomousLoopRegistry(registry)
    written_json = store.export_json(json_path)
    written_csv = store.export_csv(csv_path)
    _print(
        (
            f"JSON Export: {written_json}",
            f"CSV Export: {written_csv}",
            "PRODUCTION_INFLUENCE=false",
        )
    )


def _engine(
    *,
    registry: Path | None,
    forward_registry: Path | None = None,
    learning_registry: Path | None = None,
    performance_ledger: Path | None = None,
) -> AutonomousDecisionLoop:
    return AutonomousDecisionLoop.from_paths(
        loop_registry=registry,
        forward_registry=forward_registry,
        learning_registry=learning_registry,
        performance_ledger=performance_ledger,
    )


def _datetime(value: str) -> datetime:
    if value.strip().lower() == "now":
        return datetime.now(tz=UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("datetime must be now or ISO-8601") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _date(value: str) -> date:
    if value.strip().lower() == "today":
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("date must be today or YYYY-MM-DD") from exc


def _print(lines: tuple[str, ...]) -> None:
    for line in lines:
        print(line)


__all__ = ["autonomous_app"]
