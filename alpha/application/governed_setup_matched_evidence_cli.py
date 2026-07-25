"""CLI surface for HTR-010B7 setup-matched evidence certification."""

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

from alpha.benchmark_replay.governed_setup_matched_evidence import (
    GovernedSetupMatchedEvidenceEngine,
)
from alpha.config.settings import settings
from alpha.historical_truth.replay import HistoricalTruthReplayStore

DEFAULT_HTR010B7_OUTPUT = Path(
    ".alpha/benchmark/htr010b7_governed_setup_matched_evidence"
)
_CONSOLE = Console(stderr=True)


class _B7Progress:
    """Render one determinate progress bar across the complete B7 milestone."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def __enter__(self) -> _B7Progress:
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
                "Starting HTR-010B7 setup-matched evidence certification",
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


def register_governed_setup_matched_evidence_command(app: typer.Typer) -> None:
    """Register the B7 command on the existing benchmark application."""

    app.command("governed-setup-matched-evidence")(governed_setup_matched_evidence)


def governed_setup_matched_evidence(
    b5_certificate: Annotated[Path, typer.Option("--b5-certificate")],
    b6_certificate: Annotated[Path, typer.Option("--b6-certificate")],
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
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTR010B7_OUTPUT,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Certify setup-matched evidence coverage without changing policy."""

    dependency_start, dependency_end = _dependency_window(admission_contract)
    source = HistoricalTruthReplayStore(
        database_path=database,
        snapshot_root=historical_truth_snapshots,
        start=dependency_start,
        end=dependency_end,
    )
    completed = False
    with _B7Progress(enabled=not quiet) as progress:
        try:
            result = GovernedSetupMatchedEvidenceEngine().run(
                source=source,
                b5_certificate=b5_certificate,
                b6_certificate=b6_certificate,
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
    raw = report["raw_evidence_summary"]
    adjusted = report["adjusted_evidence_summary"]
    probes = report["probe_summary"]
    typer.echo("HTR-010B7 Governed Setup-Matched Evidence Certification")
    typer.echo(f"Readiness: {report['readiness_decision']}")
    typer.echo(f"Replay sessions: {report['session_count']}")
    typer.echo(f"RAW approvable candidates: {raw['candidate_count']}")
    typer.echo(f"ADJUSTED approvable candidates: {adjusted['candidate_count']}")
    typer.echo(f"RAW setup types: {raw['setup_type_count']}")
    typer.echo(f"ADJUSTED setup types: {adjusted['setup_type_count']}")
    typer.echo(f"RAW candidates below 60 samples: {raw['below_requirement_count']}")
    typer.echo(
        f"ADJUSTED candidates below 60 samples: {adjusted['below_requirement_count']}"
    )
    typer.echo(f"RAW total sample deficit: {raw['total_sample_deficit']}")
    typer.echo(f"ADJUSTED total sample deficit: {adjusted['total_sample_deficit']}")
    typer.echo(f"RAW completed forward outcomes: {raw['forward_completed_count']}")
    typer.echo(
        f"ADJUSTED completed forward outcomes: {adjusted['forward_completed_count']}"
    )
    typer.echo(f"RAW dominant setup: {raw['dominant_setup_type']}")
    typer.echo(f"ADJUSTED dominant setup: {adjusted['dominant_setup_type']}")
    typer.echo(f"RAW dominant observed cause: {raw['dominant_observed_cause']}")
    typer.echo(
        f"ADJUSTED dominant observed cause: {adjusted['dominant_observed_cause']}"
    )
    typer.echo(f"Setup identity complete: {report['setup_identity_complete']}")
    typer.echo(
        f"Evidence provenance complete: {report['evidence_provenance_complete']}"
    )
    typer.echo(f"Evidence probes passed: {probes['passed_probe_count']}")
    typer.echo(f"Setup identity defects: {report['setup_identity_defect_count']}")
    typer.echo(f"Implementation defects: {report['implementation_defect_count']}")
    typer.echo(
        "Unexplained evidence divergences: "
        f"{report['unexplained_evidence_divergence_count']}"
    )
    blockers = report["readiness_blockers"]
    typer.echo(f"Readiness blockers: {','.join(blockers) if blockers else 'NONE'}")
    typer.echo(
        "Governed setup-matched evidence research enabled: "
        f"{report['governed_setup_matched_evidence_research_enabled']}"
    )
    typer.echo("THRESHOLD_CHANGE_PERMITTED=false")
    typer.echo("SYNTHETIC_OUTCOMES_PERMITTED=false")
    typer.echo("OUTCOME_BACKFILL_MUTATION_ENABLED=false")
    typer.echo("DIAGNOSTIC_SUSPICION_MAY_BE_CLAIMED_AS_CAUSALITY=false")
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
    "DEFAULT_HTR010B7_OUTPUT",
    "governed_setup_matched_evidence",
    "register_governed_setup_matched_evidence_command",
]
