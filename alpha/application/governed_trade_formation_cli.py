"""CLI surface for HTR-010B4 governed trade-formation certification."""

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

from alpha.benchmark_replay.governed_trade_formation import (
    GovernedTradeFormationEngine,
)

DEFAULT_HTR010B4_OUTPUT = Path(".alpha/benchmark/htr010b4_governed_trade_formation")
_CONSOLE = Console(stderr=True)


class _B4Progress:
    """Render one determinate progress bar across the complete B4 milestone."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def __enter__(self) -> _B4Progress:
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
                "Starting HTR-010B4 trade-formation certification",
                total=8,
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


def register_governed_trade_formation_command(app: typer.Typer) -> None:
    """Register the B4 command on the existing benchmark application."""

    app.command("governed-trade-formation")(governed_trade_formation)


def governed_trade_formation(
    b2_report: Annotated[Path, typer.Option("--b2-report")],
    b3_certificate: Annotated[Path, typer.Option("--b3-certificate")],
    b3_activation_contract: Annotated[
        Path,
        typer.Option("--b3-activation-contract"),
    ],
    raw_benchmark: Annotated[Path, typer.Option("--raw-benchmark")],
    adjusted_benchmark: Annotated[Path, typer.Option("--adjusted-benchmark")],
    corporate_action_artifact: Annotated[
        Path,
        typer.Option("--corporate-action-artifact"),
    ],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTR010B4_OUTPUT,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Certify the paired candidate-to-trade funnel without changing policy."""

    with _B4Progress(enabled=not quiet) as progress:
        result = GovernedTradeFormationEngine().run(
            b2_report=b2_report,
            b3_certificate=b3_certificate,
            b3_activation_contract=b3_activation_contract,
            raw_benchmark=raw_benchmark,
            adjusted_benchmark=adjusted_benchmark,
            corporate_action_artifact=corporate_action_artifact,
            output=output,
            progress=None if quiet else progress.update,
        )

    report = result.report
    raw = report["raw_funnel_summary"]
    adjusted = report["adjusted_funnel_summary"]
    trade = report["trade_pairing_summary"]
    typer.echo("HTR-010B4 Governed Trade-Formation Certification")
    typer.echo(f"Readiness: {report['readiness_decision']}")
    typer.echo(f"Replay sessions: {report['session_count']}")
    typer.echo(f"Raw candidates: {raw['candidate_count']}")
    typer.echo(f"Adjusted candidates: {adjusted['candidate_count']}")
    typer.echo(f"Raw approvable signals: {raw['approvable_signal_count']}")
    typer.echo(f"Adjusted approvable signals: {adjusted['approvable_signal_count']}")
    typer.echo(f"Raw institutional approvals: {raw['institutional_approval_count']}")
    typer.echo(
        f"Adjusted institutional approvals: {adjusted['institutional_approval_count']}"
    )
    typer.echo(f"Raw portfolio entries: {raw['portfolio_entry_count']}")
    typer.echo(f"Adjusted portfolio entries: {adjusted['portfolio_entry_count']}")
    typer.echo(f"Raw trades: {raw['trade_count']}")
    typer.echo(f"Adjusted trades: {adjusted['trade_count']}")
    typer.echo(f"Paired trades: {trade['paired_trade_count']}")
    typer.echo(f"Raw dominant gate: {raw['dominant_terminal_gate']}")
    typer.echo(f"Adjusted dominant gate: {adjusted['dominant_terminal_gate']}")
    typer.echo(
        f"Zero-trade policy consistent: {report['zero_trade_policy_consistent']}"
    )
    typer.echo(f"Implementation defects: {report['implementation_defect_count']}")
    typer.echo(
        f"Unexplained trade divergences: {report['unexplained_trade_divergence_count']}"
    )
    blockers = report["readiness_blockers"]
    typer.echo(f"Readiness blockers: {','.join(blockers) if blockers else 'NONE'}")
    typer.echo(
        "Governed adjusted trade research enabled: "
        f"{report['governed_adjusted_trade_research_enabled']}"
    )
    typer.echo(f"Research scope: {report['research_scope']}")
    typer.echo(f"Report SHA256: {report['report_sha256']}")
    typer.echo("LIVE_SCORING_ENABLED=false")
    typer.echo("EXECUTION_INFLUENCE=false")
    typer.echo("ACTIVE_REPLAY_INTEGRATION=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(result.paths)} files)")


__all__ = [
    "DEFAULT_HTR010B4_OUTPUT",
    "governed_trade_formation",
    "register_governed_trade_formation_command",
]
