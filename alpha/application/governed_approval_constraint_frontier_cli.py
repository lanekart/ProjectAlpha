"""CLI surface for HTR-010B6 governed approval-constraint frontiers."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from alpha.benchmark_replay.governed_approval_constraint_frontier import (
    GovernedApprovalConstraintFrontierEngine,
)
from alpha.config.settings import settings

DEFAULT_HTR010B6_OUTPUT = Path(
    ".alpha/benchmark/htr010b6_governed_approval_constraint_frontier"
)
_CONSOLE = Console(stderr=True)


class _B6Progress:
    """Render one determinate progress bar across the complete B6 milestone."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def __enter__(self) -> _B6Progress:
        if self.enabled:
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=_CONSOLE,
                refresh_per_second=10,
            )
            self._progress.start()
            self._task_id = self._progress.add_task(
                "Starting HTR-010B6 approval-constraint frontier",
                total=7,
            )
        return self

    def __exit__(self, *_: object) -> None:
        if self._progress is not None:
            self._progress.stop()

    def update(self, current: int, total: int, description: str) -> None:
        if self._progress is None or self._task_id is None:
            return
        self._progress.update(
            self._task_id,
            description=description,
            total=total,
            completed=current,
        )


def register_governed_approval_constraint_frontier_command(
    app: typer.Typer,
) -> None:
    """Register the B6 command on the existing benchmark application."""

    app.command("governed-approval-constraint-frontier")(
        governed_approval_constraint_frontier
    )


def governed_approval_constraint_frontier(
    b5_certificate: Annotated[Path, typer.Option("--b5-certificate")],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTR010B6_OUTPUT,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Measure frozen institutional constraints without changing policy."""

    with _B6Progress(enabled=not quiet) as progress:
        result = GovernedApprovalConstraintFrontierEngine().run(
            b5_certificate=b5_certificate,
            output=output,
            project_root=settings.project_root,
            progress=None if quiet else progress.update,
        )

    report = result.report
    raw = report["raw_frontier_summary"]
    adjusted = report["adjusted_frontier_summary"]
    probes = report["probe_summary"]
    typer.echo("HTR-010B6 Governed Approval-Constraint Frontier")
    typer.echo(f"Readiness: {report['readiness_decision']}")
    typer.echo(f"Replay sessions: {report['session_count']}")
    typer.echo(f"RAW approvable candidates: {raw['candidate_count']}")
    typer.echo(f"ADJUSTED approvable candidates: {adjusted['candidate_count']}")
    typer.echo(f"RAW constraints: {raw['constraint_count']}")
    typer.echo(f"ADJUSTED constraints: {adjusted['constraint_count']}")
    typer.echo(f"RAW minimum remediation count: {raw['minimum_remediation_count']}")
    typer.echo(
        f"ADJUSTED minimum remediation count: {adjusted['minimum_remediation_count']}"
    )
    typer.echo(f"RAW dominant gate: {raw['dominant_gate_code']}")
    typer.echo(f"ADJUSTED dominant gate: {adjusted['dominant_gate_code']}")
    typer.echo(f"RAW nearest frontier: {raw['nearest_frontier_symbol']}")
    typer.echo(f"ADJUSTED nearest frontier: {adjusted['nearest_frontier_symbol']}")
    typer.echo(
        f"Constraint evidence complete: {report['constraint_evidence_complete']}"
    )
    typer.echo(f"Boundary probes passed: {probes['passed_probe_count']}")
    typer.echo(f"Implementation defects: {report['implementation_defect_count']}")
    typer.echo(
        "Unexplained constraint divergences: "
        f"{report['unexplained_constraint_divergence_count']}"
    )
    blockers = report["readiness_blockers"]
    typer.echo(f"Readiness blockers: {','.join(blockers) if blockers else 'NONE'}")
    typer.echo(
        "Governed approval-constraint research enabled: "
        f"{report['governed_approval_constraint_research_enabled']}"
    )
    typer.echo("POLICY_CHANGE_PERMITTED=false")
    typer.echo("THRESHOLD_CHANGE_PERMITTED=false")
    typer.echo("COUNTERFACTUAL_APPROVAL_CLAIMED=false")
    typer.echo("GOVERNED_ADJUSTED_TRADE_RESEARCH_ENABLED=false")
    typer.echo(f"Research scope: {report['research_scope']}")
    typer.echo(f"Report SHA256: {report['report_sha256']}")
    typer.echo("LIVE_SCORING_ENABLED=false")
    typer.echo("EXECUTION_INFLUENCE=false")
    typer.echo("ACTIVE_REPLAY_INTEGRATION=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(result.paths)} files)")


__all__ = [
    "DEFAULT_HTR010B6_OUTPUT",
    "governed_approval_constraint_frontier",
    "register_governed_approval_constraint_frontier_command",
]
