"""CLI surface for HTR-010B5 institutional approval-gate forensics."""

from __future__ import annotations

import json
from datetime import date
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

from alpha.benchmark_replay.governed_approval_gate_forensics import (
    GovernedApprovalGateForensicsEngine,
)
from alpha.config.settings import settings
from alpha.historical_truth.replay import HistoricalTruthReplayStore

DEFAULT_HTR010B5_OUTPUT = Path(
    ".alpha/benchmark/htr010b5_governed_approval_gate_forensics"
)
_CONSOLE = Console(stderr=True)


class _B5Progress:
    """Render one determinate progress bar across the complete B5 milestone."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def __enter__(self) -> _B5Progress:
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
                "Starting HTR-010B5 approval-gate forensics",
                total=9,
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


def register_governed_approval_gate_forensics_command(app: typer.Typer) -> None:
    """Register the B5 command on the existing benchmark application."""

    app.command("governed-approval-gate-forensics")(governed_approval_gate_forensics)


def governed_approval_gate_forensics(
    b2_report: Annotated[Path, typer.Option("--b2-report")],
    b4_certificate: Annotated[Path, typer.Option("--b4-certificate")],
    raw_benchmark: Annotated[Path, typer.Option("--raw-benchmark")],
    adjusted_benchmark: Annotated[Path, typer.Option("--adjusted-benchmark")],
    identity_artifact: Annotated[Path, typer.Option("--identity-artifact")],
    corporate_action_artifact: Annotated[
        Path,
        typer.Option("--corporate-action-artifact"),
    ],
    final_closure_report: Annotated[
        Path,
        typer.Option("--final-closure-report"),
    ],
    admission_contract: Annotated[
        Path,
        typer.Option("--admission-contract"),
    ],
    identity_admission: Annotated[
        Path,
        typer.Option("--identity-admission"),
    ],
    raw_universe: Annotated[Path, typer.Option("--raw-universe")],
    adjusted_universe: Annotated[Path, typer.Option("--adjusted-universe")],
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    historical_truth_snapshots: Annotated[
        Path,
        typer.Option("--historical-truth-snapshots"),
    ] = Path("alpha_data/snapshots"),
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTR010B5_OUTPUT,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Certify institutional gate behavior without changing frozen policy."""

    dependency_start, dependency_end = _dependency_window(admission_contract)
    source = HistoricalTruthReplayStore(
        database_path=database,
        snapshot_root=historical_truth_snapshots,
        start=dependency_start,
        end=dependency_end,
    )
    completed = False
    with _B5Progress(enabled=not quiet) as progress:
        try:
            result = GovernedApprovalGateForensicsEngine().run(
                source=source,
                b2_report=b2_report,
                b4_certificate=b4_certificate,
                raw_benchmark=raw_benchmark,
                adjusted_benchmark=adjusted_benchmark,
                identity_artifact=identity_artifact,
                corporate_action_artifact=corporate_action_artifact,
                final_closure_report=final_closure_report,
                admission_contract=admission_contract,
                identity_admission=identity_admission,
                raw_universe=raw_universe,
                adjusted_universe=adjusted_universe,
                output=output,
                project_root=settings.project_root,
                progress=None if quiet else progress.update,
            )
            completed = True
        finally:
            if not completed:
                source.close()

    report = result.report
    raw = report["raw_forensic_summary"]
    adjusted = report["adjusted_forensic_summary"]
    probes = report["structural_probe_summary"]
    typer.echo("HTR-010B5 Governed Institutional Approval-Gate Forensics")
    typer.echo(f"Readiness: {report['readiness_decision']}")
    typer.echo(f"Replay sessions: {report['session_count']}")
    typer.echo(f"Raw candidates: {raw['candidate_count']}")
    typer.echo(f"Adjusted candidates: {adjusted['candidate_count']}")
    typer.echo(f"Raw approvable candidates: {raw['approvable_candidate_count']}")
    typer.echo(
        f"Adjusted approvable candidates: {adjusted['approvable_candidate_count']}"
    )
    typer.echo(f"Raw institutional approvals: {raw['institutional_approval_count']}")
    typer.echo(
        f"Adjusted institutional approvals: {adjusted['institutional_approval_count']}"
    )
    typer.echo(f"Empirical gate reached: {report['empirical_gate_reached']}")
    typer.echo(
        f"Approval-gate trace complete: {report['approval_gate_trace_complete']}"
    )
    typer.echo(f"Approval gate non-vacuous: {report['approval_gate_non_vacuous']}")
    typer.echo(
        f"Zero-approval policy consistent: {report['zero_approval_policy_consistent']}"
    )
    typer.echo(f"Acceptance path reachable: {probes['acceptance_path_reachable']}")
    typer.echo(
        "All base gate families discriminating: "
        f"{probes['all_base_gate_families_discriminating']}"
    )
    typer.echo(
        "Stress rejection path discriminating: "
        f"{probes['stress_rejection_path_discriminating']}"
    )
    typer.echo(
        "Trade-plan rejection path discriminating: "
        f"{probes['trade_plan_rejection_path_discriminating']}"
    )
    typer.echo(
        "All institutional stages discriminating: "
        f"{probes['all_institutional_stages_discriminating']}"
    )
    typer.echo(f"Implementation defects: {report['implementation_defect_count']}")
    typer.echo(
        f"Unexplained arm divergences: {report['unexplained_arm_divergence_count']}"
    )
    blockers = report["readiness_blockers"]
    typer.echo(f"Readiness blockers: {','.join(blockers) if blockers else 'NONE'}")
    typer.echo(
        "Governed approval-gate research enabled: "
        f"{report['governed_approval_gate_research_enabled']}"
    )
    typer.echo("GOVERNED_ADJUSTED_TRADE_RESEARCH_ENABLED=false")
    typer.echo(f"Research scope: {report['research_scope']}")
    typer.echo(f"Report SHA256: {report['report_sha256']}")
    typer.echo("LIVE_SCORING_ENABLED=false")
    typer.echo("EXECUTION_INFLUENCE=false")
    typer.echo("ACTIVE_REPLAY_INTEGRATION=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(result.paths)} files)")


def _dependency_window(path: Path) -> tuple[date, date]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise typer.BadParameter("admission contract must contain a mapping")
    try:
        start = date.fromisoformat(str(payload["dependency_start"]))
        end = date.fromisoformat(str(payload["dependency_end"]))
    except (KeyError, ValueError) as error:
        raise typer.BadParameter(
            "admission contract requires valid dependency_start and dependency_end"
        ) from error
    if end < start:
        raise typer.BadParameter("admission dependency window is inverted")
    return start, end


__all__ = [
    "DEFAULT_HTR010B5_OUTPUT",
    "governed_approval_gate_forensics",
    "register_governed_approval_gate_forensics_command",
]
