"""CLI surface for HTR-010B9 adaptive publication bridge certification."""

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

from alpha.benchmark_replay.governed_adaptive_publication_bridge import (
    GovernedAdaptivePublicationBridgeEngine,
)
from alpha.config.settings import settings

DEFAULT_HTR010B9_OUTPUT = Path(
    ".alpha/benchmark/htr010b9_governed_adaptive_publication_bridge"
)
_CONSOLE = Console(stderr=True)


class _B9Progress:
    """Render one determinate progress bar across the B9 certification."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def __enter__(self) -> _B9Progress:
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
                "Starting HTR-010B9 adaptive publication certification",
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


def register_governed_adaptive_publication_bridge_command(app: typer.Typer) -> None:
    """Register the B9 command on the benchmark application."""

    app.command("governed-adaptive-publication-bridge")(
        governed_adaptive_publication_bridge
    )


def governed_adaptive_publication_bridge(
    b8_certificate: Annotated[Path, typer.Option("--b8-certificate")],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTR010B9_OUTPUT,
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Certify the opt-in publication seam without enabling the default path."""

    with _B9Progress(enabled=not quiet) as progress:
        result = GovernedAdaptivePublicationBridgeEngine().run(
            b8_certificate=b8_certificate,
            output=output,
            project_root=settings.project_root,
            progress=None if quiet else progress.update,
        )

    report = result.report
    round_trip = report["round_trip_summary"]
    defaults = report["default_path_summary"]
    recorder = report["recorder_parity_summary"]
    point_in_time = report["point_in_time_summary"]
    arms = report["arm_transport_summary"]
    probes = report["probe_summary"]

    typer.echo("HTR-010B9 Governed Adaptive Publication Bridge")
    typer.echo(f"Readiness: {report['readiness_decision']}")
    typer.echo(f"Publication round-trip rows: {round_trip['row_count']}")
    typer.echo(f"Publication round-trip defects: {round_trip['failed_count']}")
    typer.echo(f"Default path drift: {defaults['drift_count']}")
    typer.echo(f"Disabled publisher calls: {defaults['publisher_call_count']}")
    typer.echo(f"Recorder parity defects: {recorder['defect_count']}")
    typer.echo(f"Candle pattern recorded: {recorder['candle_pattern_recorded']}")
    typer.echo(f"Retracement state recorded: {recorder['retracement_state_recorded']}")
    typer.echo(f"Strictly prior eligible outcomes: {point_in_time['eligible_count']}")
    typer.echo(f"Point-in-time leakage: {point_in_time['leakage_count']}")
    typer.echo(
        "Unexplained RAW/ADJUSTED transport divergences: "
        f"{arms['unexplained_divergence_count']}"
    )
    typer.echo(f"Non-vacuity probes passed: {probes['passed_probe_count']}")
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
    typer.echo("PRODUCTION_LEDGER_BACKFILL_ENABLED=false")
    typer.echo("GOVERNED_ADJUSTED_TRADE_RESEARCH_ENABLED=false")
    typer.echo(f"Research scope: {report['research_scope']}")
    typer.echo(f"Report SHA256: {report['report_sha256']}")
    typer.echo("RECOMMENDATION_INFLUENCE=false")
    typer.echo("EXECUTION_INFLUENCE=false")
    typer.echo("ACTIVE_REPLAY_INTEGRATION=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(result.paths)} files)")


__all__ = [
    "DEFAULT_HTR010B9_OUTPUT",
    "governed_adaptive_publication_bridge",
    "register_governed_adaptive_publication_bridge_command",
]
