"""CLI surface for HTR-010B3 governed adjusted stability certification."""

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

from alpha.benchmark_replay.governed_adjusted_stability import (
    GovernedAdjustedStabilityEngine,
)

DEFAULT_HTR010B3_OUTPUT = Path(".alpha/benchmark/htr010b3_governed_adjusted_stability")
_CONSOLE = Console(stderr=True)


class _B3Progress:
    """Render one determinate progress bar across the complete B3 milestone."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def __enter__(self) -> _B3Progress:
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
                "Starting HTR-010B3 stability certification",
                total=6,
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


def register_governed_adjusted_stability_command(app: typer.Typer) -> None:
    """Register the B3 command on the existing benchmark application."""

    app.command("governed-adjusted-stability")(governed_adjusted_stability)


def governed_adjusted_stability(
    b2_report: Annotated[Path, typer.Option("--b2-report")],
    raw_benchmark: Annotated[Path, typer.Option("--raw-benchmark")],
    adjusted_benchmark: Annotated[Path, typer.Option("--adjusted-benchmark")],
    corporate_action_artifact: Annotated[
        Path,
        typer.Option("--corporate-action-artifact"),
    ],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTR010B3_OUTPUT,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Certify B2 stability and issue a research-only adjusted-price gate."""

    with _B3Progress(enabled=not quiet) as progress:
        result = GovernedAdjustedStabilityEngine().run(
            b2_report=b2_report,
            raw_benchmark=raw_benchmark,
            adjusted_benchmark=adjusted_benchmark,
            corporate_action_artifact=corporate_action_artifact,
            output=output,
            progress=None if quiet else progress.update,
        )

    report = result.report
    evidence = report["evidence_summary"]
    typer.echo("HTR-010B3 Governed Adjusted Stability Certification")
    typer.echo(f"Readiness: {report['readiness_decision']}")
    typer.echo(f"Replay sessions: {report['session_count']}")
    typer.echo(f"Stability windows: {len(report['window_stability'])}")
    typer.echo(f"Paired decisions: {evidence['paired_decision_count']}")
    typer.echo(
        "Action-affected paired decisions: "
        f"{evidence['action_affected_paired_decision_count']}"
    )
    typer.echo(
        f"Unaffected paired decisions: {evidence['unaffected_paired_decision_count']}"
    )
    typer.echo(f"Approval flips: {evidence['approval_flip_count']}")
    typer.echo(f"Signal changes: {evidence['signal_change_count']}")
    typer.echo(f"Raw trades: {evidence['raw_trade_count']}")
    typer.echo(f"Adjusted trades: {evidence['adjusted_trade_count']}")
    blockers = report["readiness_blockers"]
    typer.echo(f"Readiness blockers: {','.join(blockers) if blockers else 'NONE'}")
    typer.echo(
        "Governed adjusted research enabled: "
        f"{report['governed_adjusted_research_enabled']}"
    )
    typer.echo(f"Research scope: {report['research_scope']}")
    typer.echo(f"Report SHA256: {report['report_sha256']}")
    typer.echo("LIVE_SCORING_ENABLED=false")
    typer.echo("ACTIVE_REPLAY_INTEGRATION=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(result.paths)} files)")


__all__ = [
    "DEFAULT_HTR010B3_OUTPUT",
    "governed_adjusted_stability",
    "register_governed_adjusted_stability_command",
]
