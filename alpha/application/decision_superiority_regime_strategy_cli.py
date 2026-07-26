"""Permanent CLI for the governed DSI-007 strategy tournament."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from alpha.decision_superiority.regime_strategy_artifacts import (
    export_regime_strategy_tournament,
    validate_regime_strategy_tournament_certificate,
)
from alpha.decision_superiority.regime_strategy_models import (
    TournamentError,
    TournamentPolicy,
    TournamentSourcePaths,
)
from alpha.decision_superiority.regime_strategy_tournament import (
    GovernedRegimeStrategyTournamentEngine,
)

DEFAULT_DSI007_OUTPUT = Path(".alpha/benchmark/dsi007_regime_strategy_tournament")


def register_decision_superiority_regime_strategy_command(
    app: typer.Typer,
) -> None:
    """Register the DSI-007 runner and public certificate verifier."""

    app.command("decision-superiority-regime-strategy-tournament")(
        decision_superiority_regime_strategy_tournament
    )
    app.command("decision-superiority-regime-strategy-tournament-verify")(
        decision_superiority_regime_strategy_tournament_verify
    )


def decision_superiority_regime_strategy_tournament(
    database: Annotated[Path, typer.Option("--database")],
    historical_truth_snapshots: Annotated[
        Path,
        typer.Option("--historical-truth-snapshots"),
    ],
    start: Annotated[str, typer.Option("--start")] = "2016-01-01",
    end: Annotated[str, typer.Option("--end")] = "2026-07-20",
    benchmark: Annotated[str, typer.Option("--benchmark")] = "AUTO",
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_DSI007_OUTPUT,
    capital: Annotated[float, typer.Option("--capital", min=1.0)] = 1_000_000.0,
    max_positions: Annotated[int, typer.Option("--max-positions", min=1)] = 5,
    transaction_cost: Annotated[
        float,
        typer.Option("--transaction-cost", min=0.0),
    ] = 0.002,
    slippage: Annotated[
        float,
        typer.Option("--slippage", min=0.0),
    ] = 0.001,
) -> None:
    """Run the research-only point-in-time strategy tournament."""

    try:
        result = GovernedRegimeStrategyTournamentEngine().run(
            sources=TournamentSourcePaths(
                database=database,
                historical_truth_snapshots=historical_truth_snapshots,
                benchmark=benchmark,
                project_root=Path("."),
            ),
            start=date.fromisoformat(start),
            end=date.fromisoformat(end),
            policy=TournamentPolicy(
                starting_capital=capital,
                maximum_positions=max_positions,
                transaction_cost_fraction=transaction_cost,
                slippage_fraction=slippage,
            ),
        )
        paths = export_regime_strategy_tournament(result, output)
    except (OSError, TournamentError, ValueError) as exc:
        typer.echo(f"GOVERNED_STRATEGY_TOURNAMENT_FAILED: {exc}", err=True)
        raise typer.Exit(1) from exc
    for slice_id, readiness in result.readiness.items():
        typer.echo(f"DSI-007{slice_id} Readiness: {readiness}")
    summary = result.summaries
    metrics = summary["regime_aware_metrics"]
    typer.echo(
        "Sessions / securities / rows: "
        f"{summary['admitted_sessions']} / "
        f"{summary['admitted_securities']} / "
        f"{summary['admitted_rows']}"
    )
    typer.echo(
        "Variants / signals / trade plans: "
        f"{summary['valid_variant_count']} / "
        f"{summary['signal_count']} / "
        f"{summary['trade_plan_count']}"
    )
    typer.echo(
        "Out-of-sample trades / net CAGR / drawdown: "
        f"{metrics.get('trade_count', 0)} / "
        f"{_display(metrics.get('net_cagr'))} / "
        f"{_display(metrics.get('maximum_drawdown'))}"
    )
    typer.echo(f"Benchmark Status: {summary['benchmark_status']}")
    typer.echo("STRATEGY_AUTOMATIC_PROMOTION_ENABLED=false")
    typer.echo("DEFAULT_RUNTIME_BEHAVIOUR_CHANGED=false")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def decision_superiority_regime_strategy_tournament_verify(
    certificate: Annotated[Path, typer.Option("--certificate")],
    require_ready: Annotated[bool, typer.Option("--require-ready")] = False,
    database: Annotated[
        Path | None,
        typer.Option("--database"),
    ] = None,
) -> None:
    """Validate one public DSI-007 certificate and its support artifacts."""

    try:
        payload = validate_regime_strategy_tournament_certificate(
            certificate,
            require_ready=require_ready,
            database=database,
        )
    except TournamentError as exc:
        typer.echo(f"CERTIFICATE_INVALID: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Contract: {payload['contract_version']}")
    typer.echo(f"Readiness: {payload['readiness_decision']}")
    typer.echo("Certificate: VALID")


def _display(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    if not isinstance(value, (str, int, float)):
        return "UNKNOWN"
    return f"{float(value) * 100:.2f}%"


__all__ = ["register_decision_superiority_regime_strategy_command"]
