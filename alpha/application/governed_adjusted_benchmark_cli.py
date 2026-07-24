"""CLI surface for HTR-010B2 governed adjusted benchmark research."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from alpha.benchmark_replay.governed_adjusted import (
    GovernedAdjustedBenchmarkEngine,
)
from alpha.benchmark_replay.models import BenchmarkPolicy
from alpha.config.settings import settings
from alpha.historical_truth.replay import HistoricalTruthReplayStore

DEFAULT_HTR010B2_OUTPUT = Path(".alpha/benchmark/htr010b2_governed_adjusted_benchmark")
_CONSOLE = Console(stderr=True)


class _B2Progress:
    """Show staged progress for snapshot loading and both benchmark arms."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._progress: Progress | None = None
        self._task_id: int | None = None
        self._phase = 0
        self._phase_total: int | None = None
        self._last_current = 0

    def __enter__(self) -> _B2Progress:
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
                "Loading verified Historical Truth snapshots",
                total=None,
            )
        return self

    def __exit__(self, *_: object) -> None:
        if self._progress is not None:
            self._progress.stop()

    def stage(self, description: str) -> None:
        if self._progress is None or self._task_id is None:
            return
        self._progress.update(
            self._task_id,
            description=description,
            total=None,
            completed=0,
        )

    def update(self, current: int, total: int, observed_on: date) -> None:
        if self._progress is None or self._task_id is None:
            return
        if total < 1:
            return
        if self._phase_total is None:
            self._phase_total = total
        elif current == 1 and self._last_current == self._phase_total:
            self._phase = 1
        phase_name = "RAW" if self._phase == 0 else "ADJUSTED"
        completed = self._phase * total + current
        self._progress.update(
            self._task_id,
            description=f"{phase_name} benchmark through {observed_on.isoformat()}",
            total=total * 2,
            completed=completed,
        )
        self._last_current = current

    def complete(self) -> None:
        if self._progress is None or self._task_id is None:
            return
        total = self._phase_total * 2 if self._phase_total is not None else 1
        self._progress.update(
            self._task_id,
            description="Governed RAW/ADJUSTED benchmark complete",
            total=total,
            completed=total,
        )


def register_governed_adjusted_benchmark_command(app: typer.Typer) -> None:
    """Register the B2 command on the existing benchmark application."""

    app.command("governed-adjusted-replay")(governed_adjusted_benchmark)


def governed_adjusted_benchmark(
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
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTR010B2_OUTPUT,
    capital: Annotated[str, typer.Option("--capital")] = "1000000",
    max_positions: Annotated[int, typer.Option("--max-positions", min=1)] = 3,
    transaction_cost: Annotated[
        str,
        typer.Option("--transaction-cost"),
    ] = "0.20",
    slippage: Annotated[str, typer.Option("--slippage")] = "0.10",
    quiet: Annotated[bool, typer.Option("--quiet")] = False,
) -> None:
    """Run paired raw and adjusted CABR under the signed B1H population."""

    dependency_start, dependency_end = _dependency_window(admission_contract)
    with _B2Progress(enabled=not quiet) as progress:
        progress.stage("Loading verified Historical Truth snapshots")
        source = HistoricalTruthReplayStore(
            database_path=database,
            snapshot_root=historical_truth_snapshots,
            start=dependency_start,
            end=dependency_end,
        )
        completed = False
        try:
            progress.stage("Building governed B2 identity-session stores")
            result = GovernedAdjustedBenchmarkEngine().run(
                source=source,
                identity_artifact=identity_artifact,
                corporate_action_artifact=corporate_action_artifact,
                final_closure_report=final_closure_report,
                admission_contract=admission_contract,
                identity_admission=identity_admission,
                raw_universe=raw_universe,
                adjusted_universe=adjusted_universe,
                output=output,
                policy=BenchmarkPolicy(
                    initial_capital=_decimal(capital, "capital"),
                    maximum_positions=max_positions,
                    transaction_cost_percent=_decimal(
                        transaction_cost,
                        "transaction cost",
                    ),
                    slippage_percent=_decimal(slippage, "slippage"),
                ),
                project_root=settings.project_root,
                progress=None if quiet else progress.update,
            )
            completed = True
            progress.complete()
        finally:
            if not completed:
                source.close()

    report = result.report
    raw = report["raw_summary"]
    adjusted = report["adjusted_summary"]
    comparison = report["comparison"]
    typer.echo("HTR-010B2 Governed Adjusted Benchmark")
    typer.echo(f"Readiness: {report['readiness_decision']}")
    typer.echo(f"Raw sessions: {raw['session_count']}")
    typer.echo(f"Adjusted sessions: {adjusted['session_count']}")
    typer.echo(f"Raw eligible securities: {raw['eligible_security_count']}")
    typer.echo(f"Adjusted eligible securities: {adjusted['eligible_security_count']}")
    typer.echo(
        "Raw eligible observations: "
        f"{raw['eligible_security_observation_count']}"
    )
    typer.echo(
        "Adjusted eligible observations: "
        f"{adjusted['eligible_security_observation_count']}"
    )
    typer.echo(
        "Benchmark population nonempty: "
        f"{comparison['benchmark_population_nonempty']}"
    )
    typer.echo(f"Decision metrics evaluated: {report['decision_metrics_evaluated']}")
    typer.echo(f"Raw candidates: {raw['technical_candidate_count']}")
    typer.echo(f"Adjusted candidates: {adjusted['technical_candidate_count']}")
    typer.echo(f"Unexplained divergences: {comparison['unexplained_divergence_count']}")
    blockers = comparison.get("readiness_blockers", [])
    typer.echo(f"Readiness blockers: {','.join(blockers) if blockers else 'NONE'}")
    typer.echo(f"Report SHA256: {report['report_sha256']}")
    typer.echo("ACTIVE_REPLAY_INTEGRATION=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output}")


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


def _decimal(value: str, label: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise typer.BadParameter(f"{label} must be numeric") from error
    if parsed < 0:
        raise typer.BadParameter(f"{label} cannot be negative")
    return parsed


__all__ = [
    "DEFAULT_HTR010B2_OUTPUT",
    "governed_adjusted_benchmark",
    "register_governed_adjusted_benchmark_command",
]
