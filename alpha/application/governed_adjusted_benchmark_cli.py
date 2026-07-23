"""CLI surface for HTR-010B2 governed adjusted benchmark research."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

import typer

from alpha.benchmark_replay.governed_adjusted import (
    GovernedAdjustedBenchmarkEngine,
)
from alpha.benchmark_replay.models import BenchmarkPolicy
from alpha.config.settings import settings
from alpha.historical_truth.replay import HistoricalTruthReplayStore

DEFAULT_HTR010B2_OUTPUT = Path(
    ".alpha/benchmark/htr010b2_governed_adjusted_benchmark"
)


def register_governed_adjusted_benchmark_command(app: typer.Typer) -> None:
    """Register the B2 command on the existing benchmark application."""

    app.command("governed-adjusted-replay")(governed_adjusted_benchmark)


def governed_adjusted_benchmark(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    historical_truth_snapshots: Annotated[
        Path,
        typer.Option("--historical-truth-snapshots"),
    ] = Path("alpha_data/snapshots"),
    identity_artifact: Annotated[
        Path,
        typer.Option("--identity-artifact"),
    ] = Path("artifacts/htr010b1_final/canonical_identities.json"),
    corporate_action_artifact: Annotated[
        Path,
        typer.Option("--corporate-action-artifact"),
    ] = Path("artifacts/htr010b1_final/canonical_actions.json"),
    final_closure_report: Annotated[
        Path,
        typer.Option("--final-closure-report"),
    ] = Path("artifacts/htr010b1_final/htr010b1_final_closure_report.json"),
    admission_contract: Annotated[
        Path,
        typer.Option("--admission-contract"),
    ] = Path("artifacts/htr010b1h/htr010b1h_replay_contract.json"),
    identity_admission: Annotated[
        Path,
        typer.Option("--identity-admission"),
    ] = Path("artifacts/htr010b1h/htr010b1h_identity_admission.json"),
    raw_universe: Annotated[
        Path,
        typer.Option("--raw-universe"),
    ] = Path("artifacts/htr010b1h/htr010b1h_raw_universe.json"),
    adjusted_universe: Annotated[
        Path,
        typer.Option("--adjusted-universe"),
    ] = Path("artifacts/htr010b1h/htr010b1h_adjusted_universe.json"),
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
    source = HistoricalTruthReplayStore(
        database_path=database,
        snapshot_root=historical_truth_snapshots,
        start=dependency_start,
        end=dependency_end,
    )
    completed = False
    try:
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
            progress=None if quiet else _progress,
        )
        completed = True
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
    typer.echo(f"Raw candidates: {raw['technical_candidate_count']}")
    typer.echo(f"Adjusted candidates: {adjusted['technical_candidate_count']}")
    typer.echo(
        "Unexplained divergences: "
        f"{comparison['unexplained_divergence_count']}"
    )
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


def _progress(current: int, total: int, observed_on: date) -> None:
    if current == 1 or current == total or current % 100 == 0:
        typer.echo(
            f"HTR-010B2 progress: {current}/{total} through {observed_on}",
            err=True,
        )


__all__ = [
    "DEFAULT_HTR010B2_OUTPUT",
    "governed_adjusted_benchmark",
    "register_governed_adjusted_benchmark_command",
]
