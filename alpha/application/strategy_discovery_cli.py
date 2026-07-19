from __future__ import annotations

from pathlib import Path

import typer

from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.strategy_discovery.discovery_service import StrategyDiscoveryService
from alpha.strategy_discovery.historical_signal_generator import (
    HistoricalSignalGenerator,
)
from alpha.strategy_discovery.rendering import (
    render_discovery,
    render_discovery_report,
    render_evaluation,
    render_leaderboard,
    render_publication,
    render_robustness,
    render_walk_forward,
)
from alpha.strategy_discovery.shadow_candidate_publisher import (
    ShadowCandidatePublisher,
)
from alpha.strategy_discovery.strategy_registry import StrategyRegistry

strategy_app = typer.Typer(
    help="Bounded, point-in-time strategy discovery with no production influence."
)


@strategy_app.command(name="discover")
def strategy_discover(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    export_json: Path | None = typer.Option(None, "--export-json"),
    export_csv: Path | None = typer.Option(None, "--export-csv"),
) -> None:
    """Generate the bounded strategy search without accessing holdout evidence."""

    service = _service(learning_ledger, registry, research_registry)
    artifacts = service.discover()
    _exports(service.registry, export_json, export_csv)
    _print(
        render_discovery(
            artifacts.dataset,
            service.feature_manifest.definitions,
            artifacts.search_manifest,
        )
    )


@strategy_app.command(name="walk-forward")
def strategy_walk_forward(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Evaluate expanding chronological folds while leaving holdout untouched."""

    artifacts = _service(learning_ledger, registry, research_registry).discover()
    _print(
        render_walk_forward(
            artifacts.dataset,
            artifacts.partition.folds,
            artifacts.evaluations,
        )
    )


@strategy_app.command(name="evaluate")
def strategy_evaluate(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    export_json: Path | None = typer.Option(None, "--export-json"),
    export_csv: Path | None = typer.Option(None, "--export-csv"),
) -> None:
    """Evaluate the final shortlist with controlled one-time holdout access."""

    service = _service(learning_ledger, registry, research_registry)
    report = service.report()
    _exports(service.registry, export_json, export_csv)
    _print(render_evaluation(report))


@strategy_app.command(name="robustness")
def strategy_robustness(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Run perturbation, ablation, cost, concentration, and bootstrap checks."""

    report = _service(learning_ledger, registry, research_registry).report()
    _print(render_robustness(report))


@strategy_app.command(name="leaderboard")
def strategy_leaderboard(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    export_json: Path | None = typer.Option(None, "--export-json"),
    export_csv: Path | None = typer.Option(None, "--export-csv"),
) -> None:
    """Show immutable classifications and benchmark comparisons."""

    service = _service(learning_ledger, registry, research_registry)
    report = service.report()
    _exports(service.registry, export_json, export_csv)
    _print(render_leaderboard(report))


@strategy_app.command(name="publish-shadow-candidate")
def strategy_publish_shadow_candidate(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    shadow_registry: Path | None = typer.Option(None, "--shadow-registry"),
) -> None:
    """Fail closed unless one candidate passes every generalisation gate."""

    report = _service(learning_ledger, registry, research_registry).report()
    candidate = ShadowCandidatePublisher(shadow_registry).publish(report)
    _print(
        render_publication(
            report,
            published_cohort=None if candidate is None else candidate.cohort_version,
        )
    )


@strategy_app.command(name="discovery-report")
def strategy_discovery_report(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    export_json: Path | None = typer.Option(None, "--export-json"),
    export_csv: Path | None = typer.Option(None, "--export-csv"),
) -> None:
    """Render the complete evidence, failure, benchmark, and final-decision report."""

    service = _service(learning_ledger, registry, research_registry)
    report = service.report()
    _exports(service.registry, export_json, export_csv)
    _print(render_discovery_report(report))


def _service(
    learning_ledger: Path | None,
    registry: Path | None,
    research_registry: Path | None,
) -> StrategyDiscoveryService:
    strategy_registry = StrategyRegistry(registry)
    return StrategyDiscoveryService(
        signal_generator=HistoricalSignalGenerator(
            repository=LearningLedgerRepository(learning_ledger)
        ),
        registry=strategy_registry,
        research_registry=ResearchExperimentRegistry(research_registry),
    )


def _exports(
    registry: StrategyRegistry,
    export_json: Path | None,
    export_csv: Path | None,
) -> None:
    if export_json is not None:
        registry.export_json(export_json)
    if export_csv is not None:
        registry.export_csv(export_csv)


def _print(lines: tuple[str, ...]) -> None:
    for line in lines:
        print(line)


__all__ = ["strategy_app"]
