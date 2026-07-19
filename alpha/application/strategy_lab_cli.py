from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import typer

from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.strategy_discovery.historical_signal_generator import (
    HistoricalSignalGenerator,
)
from alpha.strategy_lab.backtest_engine import BacktestRequest
from alpha.strategy_lab.combination_generator import GenerationRequest
from alpha.strategy_lab.execution_assumptions import default_execution_profile
from alpha.strategy_lab.experiment_registry import StrategyLabExperimentRegistry
from alpha.strategy_lab.exporting import export_registry
from alpha.strategy_lab.leaderboard import StrategyLeaderboard
from alpha.strategy_lab.models import (
    EntryRule,
    LabEvidenceClass,
    LeaderboardView,
    StopRule,
    TargetRule,
)
from alpha.strategy_lab.rendering import (
    render_attribution,
    render_backtest,
    render_comparison,
    render_generation,
    render_inventory,
    render_leaderboard,
    render_report,
    render_robustness,
    render_timeline,
)
from alpha.strategy_lab.service import StrategyLabService
from alpha.strategy_lab.strategy_comparison import StrategyComparisonEngine

strategy_lab_app = typer.Typer(
    help="Bounded strategy and indicator combination research lab."
)


@strategy_lab_app.command(name="inventory")
def strategy_lab_inventory(
    export: Path | None = typer.Option(None, "--export"),
) -> None:
    """Show point-in-time indicators, quarantines, and strategy templates."""

    service = StrategyLabService()
    _print(render_inventory(service.inventory()))
    if export is not None:
        report = service.report()
        export_registry(service.experiment_registry, export)
        del report


@strategy_lab_app.command(name="generate")
def strategy_lab_generate(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    family: str | None = typer.Option(None, "--family"),
    indicators: str = typer.Option("", "--indicators"),
    max_components: int = typer.Option(3, "--max-components"),
    entry_rule: EntryRule = typer.Option(EntryRule.RECORDED_REFERENCE, "--entry-rule"),
    stop_rule: StopRule = typer.Option(StopRule.RECORDED_PLAN, "--stop-rule"),
    target_rule: TargetRule = typer.Option(TargetRule.RECORDED_PLAN, "--target-rule"),
    holding_period: int = typer.Option(20, "--holding-period"),
) -> None:
    """Generate a deterministic bounded strategy search manifest."""

    service = _service(learning_ledger, None, None)
    generated = service.generate(
        request=_generation(
            family,
            indicators,
            max_components,
            entry_rule,
            stop_rule,
            target_rule,
            holding_period,
        )
    )
    _print(render_generation(generated))


@strategy_lab_app.command(name="backtest")
def strategy_lab_backtest(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    family: str | None = typer.Option(None, "--family"),
    indicators: str = typer.Option("", "--indicators"),
    max_components: int = typer.Option(3, "--max-components"),
    entry_rule: EntryRule = typer.Option(EntryRule.RECORDED_REFERENCE, "--entry-rule"),
    stop_rule: StopRule = typer.Option(StopRule.RECORDED_PLAN, "--stop-rule"),
    target_rule: TargetRule = typer.Option(TargetRule.RECORDED_PLAN, "--target-rule"),
    holding_period: int = typer.Option(20, "--holding-period"),
    start_date: str | None = typer.Option(None, "--start-date"),
    end_date: str | None = typer.Option(None, "--end-date"),
    symbols: str = typer.Option("", "--symbols"),
    setups: str = typer.Option("", "--setups"),
    evidence_class: LabEvidenceClass | None = typer.Option(None, "--evidence-class"),
    cost_bps: str = typer.Option("20", "--cost-bps"),
    slippage_bps: str = typer.Option("10", "--slippage-bps"),
    export: Path | None = typer.Option(None, "--export"),
) -> None:
    """Run comparable historical strategy tests and persist every result."""

    service = _service(learning_ledger, registry, research_registry)
    report = service.report(
        generation_request=_generation(
            family,
            indicators,
            max_components,
            entry_rule,
            stop_rule,
            target_rule,
            holding_period,
        ),
        backtest_request=BacktestRequest(
            start_date=_date(start_date, "start-date"),
            end_date=_date(end_date, "end-date"),
            symbols=_split(symbols),
            setups=_split(setups),
            evidence_class=evidence_class,
        ),
        execution_profile=default_execution_profile(
            cost_bps=_decimal(cost_bps, "cost-bps"),
            slippage_bps=_decimal(slippage_bps, "slippage-bps"),
        ),
    )
    _export(service, export)
    _print(render_backtest(report))


@strategy_lab_app.command(name="leaderboard")
def strategy_lab_leaderboard(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    view: LeaderboardView = typer.Option(LeaderboardView.COMPOSITE, "--view"),
    top: int = typer.Option(10, "--top"),
    export: Path | None = typer.Option(None, "--export"),
) -> None:
    """Show a selected transparent leaderboard view."""

    service = _service(learning_ledger, registry, research_registry)
    report = service.report()
    ranked = StrategyLeaderboard().rank(report.results, view=view, top=top)
    _export(service, export)
    _print(render_leaderboard(ranked, view=view, top=top))


@strategy_lab_app.command(name="compare")
def strategy_lab_compare(
    strategy: list[str] = typer.Option([], "--strategy"),
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Compare two or more strategy IDs on the same source population."""

    report = _service(learning_ledger, registry, research_registry).report()
    ids = tuple(strategy) or tuple(
        item.strategy.strategy_id for item in report.results[:2]
    )
    comparison = StrategyComparisonEngine().compare(
        report.results,
        ids,
        shared_population=report.source_rows,
    )
    _print(render_comparison(comparison))


@strategy_lab_app.command(name="attribution")
def strategy_lab_attribution(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    top: int = typer.Option(20, "--top"),
) -> None:
    """Show indicator ablation and combination value attribution."""

    report = _service(learning_ledger, registry, research_registry).report()
    _print(render_attribution(report, top=top))


@strategy_lab_app.command(name="timeline")
def strategy_lab_timeline(
    strategy_id: str | None = typer.Option(None, "--strategy-id"),
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
) -> None:
    """Show annual, quarterly, rolling, equity, and drawdown evidence."""

    report = _service(learning_ledger, registry, research_registry).report()
    result = next(
        (
            item
            for item in report.results
            if strategy_id is None or item.strategy.strategy_id == strategy_id
        ),
        None,
    )
    if result is None:
        raise typer.BadParameter("unknown strategy id")
    _print(render_timeline(result))


@strategy_lab_app.command(name="robustness")
def strategy_lab_robustness(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    top: int = typer.Option(10, "--top"),
) -> None:
    """Run cost, concentration, confidence, and multiple-testing diagnostics."""

    report = _service(learning_ledger, registry, research_registry).report()
    _print(render_robustness(report, top=top))


@strategy_lab_app.command(name="report")
def strategy_lab_report(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    registry: Path | None = typer.Option(None, "--registry"),
    research_registry: Path | None = typer.Option(None, "--research-registry"),
    top: int = typer.Option(10, "--top"),
    export: Path | None = typer.Option(None, "--export"),
) -> None:
    """Render the complete strategy-lab research conclusion."""

    service = _service(learning_ledger, registry, research_registry)
    report = service.report()
    _export(service, export)
    _print(render_report(report, top=top))


def _service(
    ledger: Path | None,
    registry: Path | None,
    research_registry: Path | None,
) -> StrategyLabService:
    return StrategyLabService(
        signal_generator=HistoricalSignalGenerator(
            repository=LearningLedgerRepository(ledger)
        ),
        experiment_registry=StrategyLabExperimentRegistry(registry),
        research_registry=ResearchExperimentRegistry(research_registry),
    )


def _generation(
    family: str | None,
    indicators: str,
    max_components: int,
    entry_rule: EntryRule,
    stop_rule: StopRule,
    target_rule: TargetRule,
    holding_period: int,
) -> GenerationRequest:
    return GenerationRequest(
        maximum_components=max_components,
        family=None if family is None else family.strip().upper(),
        indicators=_split(indicators),
        entry_rule=entry_rule,
        stop_rule=stop_rule,
        target_rule=target_rule,
        holding_period_days=holding_period,
    )


def _split(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _date(value: str | None, label: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(f"{label} must use YYYY-MM-DD format") from error


def _decimal(value: str, label: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except Exception as error:
        raise typer.BadParameter(f"{label} must be numeric") from error
    if parsed < Decimal("0"):
        raise typer.BadParameter(f"{label} cannot be negative")
    return parsed


def _export(service: StrategyLabService, destination: Path | None) -> None:
    if destination is not None:
        export_registry(service.experiment_registry, destination)


def _print(lines: tuple[str, ...]) -> None:
    for line in lines:
        print(line)


__all__ = ["strategy_lab_app"]
