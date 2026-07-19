from __future__ import annotations

from pathlib import Path

import typer

from alpha.continuous_learning.continuous_learning_engine import (
    ContinuousLearningEngine,
)
from alpha.continuous_learning.rendering import (
    render_calibration,
    render_collection,
    render_drift,
    render_learning_report,
    render_outcomes,
    render_recommendations,
    render_strategy_health,
)


def register_continuous_learning_commands(app: typer.Typer) -> None:
    app.command(name="collect")(continuous_learning_collect)
    app.command(name="outcomes")(continuous_learning_outcomes)
    app.command(name="drift")(continuous_learning_drift)
    app.command(name="strategy-health")(continuous_learning_strategy_health)
    app.command(name="calibration")(continuous_learning_calibration)
    app.command(name="recommendations")(continuous_learning_recommendations)


def continuous_learning_collect(
    ledger: Path | None = typer.Option(None, "--ledger"),
    forward_registry: Path | None = typer.Option(None, "--forward-registry"),
    learning_registry: Path | None = typer.Option(None, "--learning-registry"),
    export_json: Path | None = typer.Option(None, "--export-json"),
    export_csv: Path | None = typer.Option(None, "--export-csv"),
) -> None:
    """Collect immutable recommendation outcomes and prediction learning events."""

    engine = _engine(ledger, forward_registry, learning_registry)
    summary = engine.collect()
    _exports(engine, export_json, export_csv)
    _print(render_collection(summary))


def continuous_learning_outcomes(
    ledger: Path | None = typer.Option(None, "--ledger"),
    forward_registry: Path | None = typer.Option(None, "--forward-registry"),
    learning_registry: Path | None = typer.Option(None, "--learning-registry"),
) -> None:
    """Show latest immutable outcome state for every tracked recommendation."""

    report = _engine(ledger, forward_registry, learning_registry).report()
    _print(
        render_outcomes(
            report.outcomes,
            analytically_eligible_recommendations=(
                report.analytically_eligible_recommendations
            ),
            quarantined_recommendations=report.quarantined_recommendations,
        )
    )


def continuous_learning_drift(
    ledger: Path | None = typer.Option(None, "--ledger"),
    forward_registry: Path | None = typer.Option(None, "--forward-registry"),
    learning_registry: Path | None = typer.Option(None, "--learning-registry"),
) -> None:
    """Measure concept, timing, score, volatility, and sector population drift."""

    report = _engine(ledger, forward_registry, learning_registry).report()
    _print(render_drift(report.drifts))


def continuous_learning_strategy_health(
    ledger: Path | None = typer.Option(None, "--ledger"),
    forward_registry: Path | None = typer.Option(None, "--forward-registry"),
    learning_registry: Path | None = typer.Option(None, "--learning-registry"),
) -> None:
    """Show advisory setup health classifications from resolved outcomes."""

    report = _engine(ledger, forward_registry, learning_registry).report()
    _print(render_strategy_health(report.strategy_health))


def continuous_learning_calibration(
    ledger: Path | None = typer.Option(None, "--ledger"),
    forward_registry: Path | None = typer.Option(None, "--forward-registry"),
    learning_registry: Path | None = typer.Option(None, "--learning-registry"),
) -> None:
    """Measure frozen confidence reliability without recalibrating production."""

    report = _engine(ledger, forward_registry, learning_registry).report()
    _print(render_calibration(report.calibration))


def continuous_learning_recommendations(
    ledger: Path | None = typer.Option(None, "--ledger"),
    forward_registry: Path | None = typer.Option(None, "--forward-registry"),
    learning_registry: Path | None = typer.Option(None, "--learning-registry"),
) -> None:
    """Generate evidence-referenced research tasks without changing policy."""

    report = _engine(ledger, forward_registry, learning_registry).report()
    _print(render_recommendations(report.research_recommendations))


def continuous_learning_report_lines(
    *,
    ledger: Path | None,
    forward_registry: Path | None,
    learning_registry: Path | None,
) -> tuple[str, ...]:
    report = _engine(ledger, forward_registry, learning_registry).report()
    return render_learning_report(report)


def _engine(
    ledger: Path | None,
    forward_registry: Path | None,
    learning_registry: Path | None,
) -> ContinuousLearningEngine:
    return ContinuousLearningEngine.from_paths(
        performance_ledger=ledger,
        forward_registry=forward_registry,
        learning_registry=learning_registry,
    )


def _exports(
    engine: ContinuousLearningEngine,
    export_json: Path | None,
    export_csv: Path | None,
) -> None:
    if export_json is not None:
        engine.learning_registry.export_json(export_json)
    if export_csv is not None:
        engine.learning_registry.export_csv(export_csv)


def _print(lines: tuple[str, ...]) -> None:
    for line in lines:
        print(line)


__all__ = [
    "continuous_learning_report_lines",
    "register_continuous_learning_commands",
]
