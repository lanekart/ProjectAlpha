"""CLI surface for HTR-010B10 adaptive institutional and trade shadow replay."""

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

from alpha.benchmark_replay.governed_adaptive_institutional_trade_shadow import (
    GovernedAdaptiveInstitutionalTradeShadowEngine,
)
from alpha.config.settings import settings
from alpha.historical_truth.replay import HistoricalTruthReplayStore

DEFAULT_HTR010B10_OUTPUT = Path(
    ".alpha/benchmark/htr010b10_governed_adaptive_institutional_trade_shadow"
)
_CONSOLE = Console(stderr=True)


class _B10Progress:
    """Render one determinate progress bar across B10 certification."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def __enter__(self) -> _B10Progress:
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
                "Starting HTR-010B10 adaptive institutional shadow replay",
                total=12,
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


def register_governed_adaptive_institutional_trade_shadow_command(
    app: typer.Typer,
) -> None:
    """Register B10 on the existing benchmark application."""

    app.command("governed-adaptive-institutional-trade-shadow")(
        governed_adaptive_institutional_trade_shadow
    )


def governed_adaptive_institutional_trade_shadow(
    b9_certificate: Annotated[Path, typer.Option("--b9-certificate")],
    b8_certificate: Annotated[Path, typer.Option("--b8-certificate")],
    b7_certificate: Annotated[Path, typer.Option("--b7-certificate")],
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
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTR010B10_OUTPUT,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Certify adaptive institutional and trade effects in a shadow-only replay."""

    dependency_start, dependency_end = _dependency_window(admission_contract)
    source = HistoricalTruthReplayStore(
        database_path=database,
        snapshot_root=historical_truth_snapshots,
        start=dependency_start,
        end=dependency_end,
    )
    completed = False
    with _B10Progress(enabled=not quiet) as progress:
        try:
            result = GovernedAdaptiveInstitutionalTradeShadowEngine().run(
                source=source,
                b9_certificate=b9_certificate,
                b8_certificate=b8_certificate,
                b7_certificate=b7_certificate,
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
    publication = report["publication_summary"]
    institutional = report["institutional_effect_summary"]
    trades = report["trade_formation_summary"]
    point_in_time = report["point_in_time_summary"]
    arms = report["arm_effect_summary"]
    probes = report["probe_summary"]

    typer.echo("HTR-010B10 Governed Adaptive Institutional and Trade Shadow Replay")
    typer.echo(f"Readiness: {report['readiness_decision']}")
    typer.echo(f"Replay sessions: {report['session_count']}")
    typer.echo(f"Published recommendation rows: {publication['row_count']}")
    typer.echo(
        "Rows with prior completed evidence: "
        f"{publication['rows_with_prior_completed_evidence']}"
    )
    typer.echo(f"Candidates compared: {institutional['candidate_count']}")
    typer.echo(f"Default approvals: {institutional['default_approval_count']}")
    typer.echo(f"Adaptive approvals: {institutional['adaptive_approval_count']}")
    typer.echo(f"Approval transitions: {institutional['approval_change_count']}")
    typer.echo(
        "Unexplained institutional divergences: "
        f"{institutional['unexplained_divergence_count']}"
    )
    typer.echo(
        "Default/adaptive trade formations: "
        f"{trades['default_trade_formation_count']}/"
        f"{trades['adaptive_trade_formation_count']}"
    )
    typer.echo(f"Trade transitions: {trades['trade_formation_change_count']}")
    typer.echo(
        f"Unexplained trade divergences: {trades['unexplained_divergence_count']}"
    )
    typer.echo(f"Point-in-time eligible outcomes: {point_in_time['eligible_count']}")
    typer.echo(f"Point-in-time leakage: {point_in_time['leakage_count']}")
    typer.echo(
        "Unexplained RAW/ADJUSTED effects: "
        f"{arms['unexplained_divergence_count']}"
    )
    typer.echo(f"Non-vacuity probes passed: {probes['passed_probe_count']}")
    typer.echo(
        "Recommendation semantic drift: "
        f"{report['recommendation_semantic_drift_count']}"
    )
    typer.echo(f"Implementation defects: {report['implementation_defect_count']}")
    blockers = report["readiness_blockers"]
    typer.echo(f"Readiness blockers: {','.join(blockers) if blockers else 'NONE'}")
    typer.echo(
        "Governed shadow adaptive publication enabled: "
        f"{report['governed_shadow_adaptive_publication_enabled']}"
    )
    typer.echo("DEFAULT_RUNTIME_ADAPTIVE_PUBLICATION_ENABLED=false")
    typer.echo("APPROVAL_POLICY_CHANGE_PERMITTED=false")
    typer.echo("EVIDENCE_THRESHOLD_CHANGE_PERMITTED=false")
    typer.echo("FINGERPRINT_MATCHING_CHANGE_PERMITTED=false")
    typer.echo("PORTFOLIO_POLICY_CHANGE_PERMITTED=false")
    typer.echo("EXECUTION_POLICY_CHANGE_PERMITTED=false")
    typer.echo("PRODUCTION_LEDGER_MUTATION_ENABLED=false")
    typer.echo("ECONOMIC_SUPERIORITY_CLAIMED=false")
    typer.echo(f"Research scope: {report['research_scope']}")
    typer.echo(f"Report SHA256: {report['report_sha256']}")
    typer.echo("RECOMMENDATION_INFLUENCE=false")
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
    "DEFAULT_HTR010B10_OUTPUT",
    "governed_adaptive_institutional_trade_shadow",
    "register_governed_adaptive_institutional_trade_shadow_command",
]
