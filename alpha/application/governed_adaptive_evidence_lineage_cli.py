"""CLI surface for HTR-010B8 adaptive evidence lineage certification."""

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

from alpha.benchmark_replay.governed_adaptive_evidence_lineage import (
    GovernedAdaptiveEvidenceLineageEngine,
)
from alpha.config.settings import settings

DEFAULT_HTR010B8_OUTPUT = Path(
    ".alpha/benchmark/htr010b8_governed_adaptive_evidence_lineage"
)
_CONSOLE = Console(stderr=True)


class _B8Progress:
    """Render one determinate progress bar across the complete B8 milestone."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def __enter__(self) -> _B8Progress:
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
                "Starting HTR-010B8 adaptive evidence lineage certification",
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


def register_governed_adaptive_evidence_lineage_command(app: typer.Typer) -> None:
    """Register the B8 command on the existing benchmark application."""

    app.command("governed-adaptive-evidence-lineage")(
        governed_adaptive_evidence_lineage
    )


def governed_adaptive_evidence_lineage(
    b7_certificate: Annotated[Path, typer.Option("--b7-certificate")],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTR010B8_OUTPUT,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Certify adaptive evidence lineage without publishing adaptive metadata."""

    with _B8Progress(enabled=not quiet) as progress:
        result = GovernedAdaptiveEvidenceLineageEngine().run(
            b7_certificate=b7_certificate,
            output=output,
            project_root=settings.project_root,
            progress=None if quiet else progress.update,
        )

    report = result.report
    raw = report["raw_adaptive_summary"]
    adjusted = report["adjusted_adaptive_summary"]
    publication = report["publication_contract_summary"]
    fingerprint = report["fingerprint_contract_summary"]
    point_in_time = report["point_in_time_summary"]
    probes = report["probe_summary"]

    typer.echo("HTR-010B8 Governed Adaptive Evidence Lineage Certification")
    typer.echo(f"Readiness: {report['readiness_decision']}")
    typer.echo(f"Replay sessions: {report['session_count']}")
    typer.echo(f"RAW candidates: {raw['candidate_count']}")
    typer.echo(f"ADJUSTED candidates: {adjusted['candidate_count']}")
    typer.echo(
        "RAW candidates with prior adaptive evidence: "
        f"{raw['candidate_with_prior_evidence_count']}"
    )
    typer.echo(
        "ADJUSTED candidates with prior adaptive evidence: "
        f"{adjusted['candidate_with_prior_evidence_count']}"
    )
    typer.echo(
        "Maximum point-in-time sample count: "
        f"{point_in_time['maximum_candidate_sample_count']}"
    )
    typer.echo(
        "Adaptive orchestrator invocation present: "
        f"{publication['orchestrator_invokes_adaptive_assessment']}"
    )
    typer.echo(
        "Producer adaptive metadata keys: "
        f"{publication['producer_publication_key_count']}/"
        f"{publication['metadata_key_count']}"
    )
    typer.echo(
        f"Current fingerprint contract mismatch: "
        f"{fingerprint['current_contract_mismatch']}"
    )
    typer.echo(f"Fingerprint gap explained: {fingerprint['current_gap_explained']}")
    typer.echo(
        "Complete snapshot parity reachable: "
        f"{fingerprint['complete_snapshot_parity_reachable']}"
    )
    typer.echo(f"Point-in-time leakage count: {report['point_in_time_leakage_count']}")
    typer.echo(f"Non-vacuity probes passed: {probes['passed_probe_count']}")
    typer.echo(f"Implementation defects: {report['implementation_defect_count']}")
    typer.echo(
        f"Unexplained publication gaps: {report['unexplained_publication_gap_count']}"
    )
    typer.echo(
        "Unexplained adaptive arm divergences: "
        f"{report['unexplained_adaptive_arm_divergence_count']}"
    )
    blockers = report["readiness_blockers"]
    typer.echo(f"Readiness blockers: {','.join(blockers) if blockers else 'NONE'}")
    typer.echo(
        "Governed adaptive evidence-lineage research enabled: "
        f"{report['governed_adaptive_evidence_lineage_research_enabled']}"
    )
    typer.echo("ADAPTIVE_METADATA_PUBLICATION_ENABLED=false")
    typer.echo("APPROVAL_POLICY_CHANGE_PERMITTED=false")
    typer.echo("EVIDENCE_THRESHOLD_CHANGE_PERMITTED=false")
    typer.echo("FINGERPRINT_MATCHING_CHANGE_PERMITTED=false")
    typer.echo("PRODUCTION_LEDGER_MUTATION_ENABLED=false")
    typer.echo("SYNTHETIC_OUTCOMES_PERMITTED=false")
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
    "DEFAULT_HTR010B8_OUTPUT",
    "governed_adaptive_evidence_lineage",
    "register_governed_adaptive_evidence_lineage_command",
]
