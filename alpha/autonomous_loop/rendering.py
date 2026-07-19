from __future__ import annotations

from collections import Counter

from alpha.autonomous_loop.forward_dna import cohort_counts
from alpha.autonomous_loop.hypothesis_pipeline import GovernedHypothesisRouter
from alpha.autonomous_loop.models import (
    AutonomousLoopStatus,
    AutonomousRunSummary,
    DNADriftAssessment,
    FrozenDecision,
    ImprovementHypothesis,
    RunEvent,
    ScheduleDefinition,
    UniverseDefinition,
    ValidationEvent,
)


def render_bootstrap(
    *,
    universe_created: bool,
    schedule_created: bool,
    universes: tuple[UniverseDefinition, ...],
    schedules: tuple[ScheduleDefinition, ...],
) -> tuple[str, ...]:
    lines = [
        "Autonomous Decision and Evidence Loop",
        f"Universe Registry: {'created' if universe_created else 'already present'}",
        f"Schedule Registry: {'created' if schedule_created else 'already present'}",
        "Registered Universes:",
    ]
    lines.extend(
        f"- {item.universe_id}: {item.source.value}; symbols={len(item.symbols)}"
        for item in universes
    )
    lines.append("Registered Schedules:")
    lines.extend(
        (
            f"- {item.schedule_id}: {item.local_time.isoformat()} "
            f"{item.timezone}; weekdays={','.join(str(day) for day in item.weekdays)}; "
            f"policy={item.policy_version.value}"
        )
        for item in schedules
    )
    lines.extend(_safety_footer())
    return tuple(lines)


def render_run(summary: AutonomousRunSummary) -> tuple[str, ...]:
    return (
        "Autonomous Loop Run",
        f"Run ID: {summary.run_id}",
        f"Schedule: {summary.schedule_id}",
        f"Scheduled For: {summary.scheduled_for.isoformat()}",
        f"Status: {summary.status.value}",
        f"Decisions Frozen: {summary.decisions_frozen}",
        f"Shadow Events: {summary.shadow_events}",
        f"Daily Marks Inserted: {summary.marks_inserted}",
        f"Decisions Resolved: {summary.resolutions_inserted}",
        f"Matured Outcomes Published: {summary.matured_outcomes_published}",
        f"Forward DNA Inserted: {summary.forward_dna_inserted}",
        f"Drift Alerts: {summary.drift_alerts}",
        f"Hypotheses Routed: {summary.hypotheses_routed}",
        f"Missing Data: {summary.missing_data_count}",
        f"Detail: {summary.detail}",
        *_safety_footer(),
    )


def render_status(status: AutonomousLoopStatus) -> tuple[str, ...]:
    return (
        "Autonomous Loop Status",
        f"Generated At: {status.generated_at.isoformat()}",
        f"Universes / Schedules: {status.universes} / {status.schedules}",
        f"Runs: {status.runs}",
        f"Completed / Failed: {status.completed_runs} / {status.failed_runs}",
        f"Frozen Decisions: {status.frozen_decisions}",
        f"Unresolved / Resolved: "
        f"{status.unresolved_decisions} / {status.resolved_decisions}",
        f"Forward DNA Observations: {status.forward_dna_observations}",
        f"Open Hypotheses: {status.open_hypotheses}",
        f"Human-Approved Hypotheses: {status.human_approved_hypotheses}",
        f"Last Completed Run: {status.last_completed_run or 'unavailable'}",
        *_safety_footer(),
    )


def render_journal(
    *,
    decisions: tuple[FrozenDecision, ...],
    events: tuple[RunEvent, ...],
) -> tuple[str, ...]:
    kinds = Counter(item.decision_kind.value for item in decisions)
    lines = [
        "Autonomous Decision Journal",
        f"Frozen Decisions: {len(decisions)}",
        "Decision Kinds: "
        + ", ".join(f"{key}={value}" for key, value in sorted(kinds.items())),
        "Latest Decisions:",
    ]
    lines.extend(
        (
            f"- {item.generated_at.isoformat()} {item.symbol}: "
            f"{item.decision_kind.value}; verdict={item.final_verdict}; "
            f"policy={item.policy_version.value}"
        )
        for item in decisions[-20:]
    )
    lines.append("Latest Run Events:")
    lines.extend(
        f"- {item.run_id}: {item.stage.value}; {item.detail}" for item in events[-20:]
    )
    lines.extend(_safety_footer())
    return tuple(lines)


def render_dna(
    *,
    observations: tuple[object, ...],
    resolved_count: int,
) -> tuple[str, ...]:
    from alpha.autonomous_loop.models import ForwardDNAObservation

    typed = tuple(
        item for item in observations if isinstance(item, ForwardDNAObservation)
    )
    counts = cohort_counts(typed)
    lines = [
        "Forward-Observed Market DNA",
        "Evidence Class: FORWARD_OBSERVED",
        f"Resolved Decision Markouts: {resolved_count}",
        f"DNA Observations: {len(typed)}",
    ]
    lines.extend(f"- {cohort.value}: {count}" for cohort, count in counts.items())
    lines.extend(
        (
            "Flat and unresolved outcomes are not forced into DNA cohorts.",
            "Reconstructed Market DNA is stored separately and is never mixed here.",
            *_safety_footer(),
        )
    )
    return tuple(lines)


def render_drift(assessments: tuple[DNADriftAssessment, ...]) -> tuple[str, ...]:
    lines = ["Forward DNA Drift", f"Assessments: {len(assessments)}"]
    lines.extend(
        (
            f"- {item.cohort.value}: {item.state.value}; "
            f"baseline={item.baseline_count}; recent={item.recent_count}; "
            "change="
            + (
                str(item.change_pct_points)
                if item.change_pct_points is not None
                else "unavailable"
            )
        )
        for item in assessments[-10:]
    )
    lines.extend(_safety_footer())
    return tuple(lines)


def render_hypotheses(
    *,
    hypotheses: tuple[ImprovementHypothesis, ...],
    validations: tuple[ValidationEvent, ...],
    router: GovernedHypothesisRouter,
) -> tuple[str, ...]:
    lines = [
        "Governed Improvement Hypotheses",
        f"Hypotheses: {len(hypotheses)}",
    ]
    for item in hypotheses:
        stage = router.stage(item.hypothesis_id)
        evidence_count = len(item.evidence_ids)
        lines.extend(
            (
                f"- {item.hypothesis_id}: {item.title}",
                f"  Stage: {stage.value}; evidence records={evidence_count}",
                f"  Statement: {item.statement}",
            )
        )
    lines.append(f"Validation Events: {len(validations)}")
    lines.extend(
        (
            "Promotion requires Strategy Lab, walk-forward, shadow validation, "
            "and explicit human approval in that order.",
        )
    )
    lines.extend(_safety_footer())
    return tuple(lines)


def _safety_footer() -> tuple[str, ...]:
    return (
        "Broker Orders: DISABLED",
        "Automatic Capital Deployment: DISABLED",
        "Automatic Policy Mutation: DISABLED",
        "PRODUCTION_INFLUENCE=false",
    )


__all__ = [
    "render_bootstrap",
    "render_dna",
    "render_drift",
    "render_hypotheses",
    "render_journal",
    "render_run",
    "render_status",
]
