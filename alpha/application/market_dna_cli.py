from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.market_dna.dna_registry import DNARegistry
from alpha.market_dna.exporting import export_registry
from alpha.market_dna.models import DNAEvidenceClass
from alpha.market_dna.rendering import (
    render_cohort_definitions,
    render_cohorts,
    render_discovery,
    render_findings,
    render_hierarchy,
    render_hypotheses,
    render_interactions,
    render_inventory,
    render_publication,
    render_report,
)
from alpha.market_dna.service import MarketDNARequest, MarketDNAService
from alpha.market_dna.strategy_lab_bridge import StrategyLabBridge
from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.strategy_discovery.historical_signal_generator import (
    HistoricalSignalGenerator,
)

market_dna_app = typer.Typer(help="Outcome-first point-in-time Market DNA research.")


@market_dna_app.command(name="inventory")
def market_dna_inventory() -> None:
    """Show usable, cautious, and quarantined DNA features."""

    _print(render_inventory(MarketDNAService().feature_manifest.definitions))


@market_dna_app.command(name="cohorts")
def market_dna_cohorts(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    export: Path | None = typer.Option(None, "--export"),
) -> None:
    """Show explicit cohort definitions and their current populations."""

    service = _service(learning_ledger, registry, research_registry)
    report = service.report()
    _export(service, export)
    _print(render_cohort_definitions(service.cohort_registry.definitions))
    _print(render_cohorts(report))


@market_dna_app.command(name="discover")
def market_dna_discover(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    horizon: str | None = typer.Option(None, "--horizon"),
    outcome_cohort: str = typer.Option("", "--outcome-cohort"),
    setup: str | None = typer.Option(None, "--setup"),
    symbols: str = typer.Option("", "--symbols"),
    sector: str | None = typer.Option(None, "--sector"),
    start_date: str | None = typer.Option(None, "--start-date"),
    end_date: str | None = typer.Option(None, "--end-date"),
    evidence_class: DNAEvidenceClass | None = typer.Option(None, "--evidence-class"),
    minimum_sample: int = typer.Option(30, "--minimum-sample"),
    max_interactions: int = typer.Option(50, "--max-interactions"),
    export: Path | None = typer.Option(None, "--export"),
) -> None:
    """Run bounded outcome-first discovery and persist every result."""

    service = _service(learning_ledger, registry, research_registry)
    report = service.report(
        _request(
            horizon,
            outcome_cohort,
            setup,
            symbols,
            sector,
            start_date,
            end_date,
            evidence_class,
            minimum_sample,
            max_interactions,
        )
    )
    _export(service, export)
    _print(render_discovery(report))


@market_dna_app.command(name="winners")
def market_dna_winners(
    top: int = typer.Option(10, "--top"),
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Show strong and moderate winner DNA."""

    report = _service(learning_ledger, registry, research_registry).report()
    _print(
        render_findings(
            report,
            cohort_ids=frozenset({"STRONG_WINNERS", "MODERATE_WINNERS"}),
            title="Market DNA Winner Characteristics",
            top=top,
        )
    )


@market_dna_app.command(name="losers")
def market_dna_losers(
    top: int = typer.Option(10, "--top"),
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Show small and large loser DNA."""

    report = _service(learning_ledger, registry, research_registry).report()
    _print(
        render_findings(
            report,
            cohort_ids=frozenset({"SMALL_LOSERS", "LARGE_LOSERS"}),
            title="Market DNA Loser Characteristics",
            top=top,
        )
    )


@market_dna_app.command(name="catastrophic-losses")
def market_dna_catastrophic_losses(
    top: int = typer.Option(10, "--top"),
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Show catastrophic-loss and high-MAE characteristics."""

    report = _service(learning_ledger, registry, research_registry).report()
    _print(
        render_findings(
            report,
            cohort_ids=frozenset({"CATASTROPHIC_LOSERS", "HIGH_MAE_FAILURES"}),
            title="Market DNA Catastrophic-Loss Characteristics",
            top=top,
        )
    )


@market_dna_app.command(name="missed-opportunities")
def market_dna_missed_opportunities(
    top: int = typer.Option(10, "--top"),
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Show profitable rejected and missed-entry proxy DNA."""

    report = _service(learning_ledger, registry, research_registry).report()
    _print(
        render_findings(
            report,
            cohort_ids=frozenset({"PROFITABLE_REJECTED", "MISSED_ENTRY_WINNERS"}),
            title="Market DNA Missed-Opportunity Characteristics",
            top=top,
        )
    )


@market_dna_app.command(name="interactions")
def market_dna_interactions(
    top: int = typer.Option(10, "--top"),
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Show bounded interactions after minimum-cell and FDR checks."""

    report = _service(learning_ledger, registry, research_registry).report()
    _print(render_interactions(report, top=top))


@market_dna_app.command(name="hierarchy")
def market_dna_hierarchy(
    top: int = typer.Option(20, "--top"),
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Show universal, setup, horizon, and descriptive cluster results."""

    report = _service(learning_ledger, registry, research_registry).report()
    _print(render_hierarchy(report, top=top))


@market_dna_app.command(name="hypotheses")
def market_dna_hypotheses(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Show only patterns eligible for controlled Strategy Lab tests."""

    report = _service(learning_ledger, registry, research_registry).report()
    _print(render_hypotheses(report))


@market_dna_app.command(name="publish-hypothesis")
def market_dna_publish_hypothesis(
    hypothesis: str = typer.Option(..., "--hypothesis"),
    bridge_registry: Path | None = typer.Option(None, "--bridge-registry"),
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Publish one selected hypothesis as an inert Strategy Lab specification."""

    report = _service(learning_ledger, registry, research_registry).report()
    selected = next(
        (item for item in report.hypotheses if item.hypothesis_id == hypothesis), None
    )
    if selected is None:
        raise typer.BadParameter("hypothesis is not an eligible registered candidate")
    _print(render_publication(StrategyLabBridge(bridge_registry).publish(selected)))


@market_dna_app.command(name="report")
def market_dna_report(
    top: int = typer.Option(5, "--top"),
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    export: Path | None = typer.Option(None, "--export"),
) -> None:
    """Render the complete governed Market DNA conclusion."""

    service = _service(learning_ledger, registry, research_registry)
    report = service.report()
    _export(service, export)
    _print(render_report(report, top=top))


def _service(
    ledger: Path | None,
    registry: Path | None,
    research_registry: Path | None,
) -> MarketDNAService:
    return MarketDNAService(
        data_source=HistoricalSignalGenerator(
            repository=LearningLedgerRepository(ledger)
        ),
        registry=DNARegistry(registry),
        research_registry=ResearchExperimentRegistry(research_registry),
    )


def _request(
    horizon: str | None,
    outcome_cohort: str,
    setup: str | None,
    symbols: str,
    sector: str | None,
    start_date: str | None,
    end_date: str | None,
    evidence_class: DNAEvidenceClass | None,
    minimum_sample: int,
    max_interactions: int,
) -> MarketDNARequest:
    try:
        return MarketDNARequest(
            horizon=horizon,
            outcome_cohorts=_split(outcome_cohort),
            setup=setup,
            symbols=_split(symbols),
            sector=sector,
            start_date=_date(start_date, "start-date"),
            end_date=_date(end_date, "end-date"),
            evidence_class=evidence_class,
            minimum_sample=minimum_sample,
            maximum_interactions=max_interactions,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _split(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _date(value: str | None, label: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(f"{label} must use YYYY-MM-DD format") from error


def _export(service: MarketDNAService, destination: Path | None) -> None:
    if destination is not None:
        try:
            export_registry(service.registry, destination)
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error


def _print(lines: tuple[str, ...]) -> None:
    for line in lines:
        print(line)


__all__ = ["market_dna_app"]
